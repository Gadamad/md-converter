#!/usr/bin/env python3
"""
MD Converter — Universal Markdown Converter App
Drag-and-drop (or browse) any PDF, DOCX, XLSX, HTML, TXT, or RTF file.
Converts to Markdown, organizes by type, delivers to Obsidian vault.
"""

import json
import subprocess
import sys

# A frozen worker reuses this executable, but must never initialize WebKit.
if __name__ == "__main__" and sys.argv[1:2] == ["--ocr-worker"]:
    from ocr_worker import main as ocr_worker_main
    raise SystemExit(ocr_worker_main(sys.argv[2:]))

import threading
from pathlib import Path
from typing import Callable, NamedTuple

import webview

from converters import SUPPORTED, ConvertResult, route, convert_pasted, convert_image_folder_quotes
from preferences import Preferences, default_preferences_path
from quote_checkpoint import QuoteCheckpoint, recovery_checkpoints
from app_version import VERSION

try:
    from native_drop import setup_native_drop
    _NATIVE_DROP = True
except ImportError:
    _NATIVE_DROP = False

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

APP_DIR = Path(__file__).resolve().parent.parent
DEFAULT_QUOTE_FOLDER = Path.home() / "Pictures"


def _output_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path.home() / "Documents" / "MD Converter" / "converted"
    return APP_DIR / "converted"


OUTPUT_DIR = _output_dir()

# Vault path: loaded from config.json if it exists, otherwise disabled.
# Copy config.example.json -> config.json and set your Obsidian vault path.
_CONFIG_PATH = APP_DIR / "config.json"
_config = {}
if _CONFIG_PATH.exists():
    try:
        _config = json.loads(_CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"WARNING: ignoring invalid config.json: {exc}", file=sys.stderr)
        _config = {}

VAULT_DIR = (
    Path(_config["vault_path"]).expanduser()
    if "vault_path" in _config
    else None
)

FILETYPES = (
    "All supported (*.pdf;*.docx;*.xlsx;*.html;*.htm;*.txt;*.rtf;*.png;*.jpg;*.jpeg;*.webp)",
    "Quote images (*.png;*.jpg;*.jpeg;*.webp)",
    "PDF files (*.pdf)",
    "Word files (*.docx)",
    "Excel files (*.xlsx)",
    "HTML files (*.html;*.htm)",
    "Text files (*.txt)",
    "RTF files (*.rtf)",
)

QUOTE_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


class StagedFolder(NamedTuple):
    id: str
    path: Path
    image_count: int
    images: tuple[str, ...]


class QuoteBatchHooks:
    def __init__(
        self,
        on_image_processed: Callable[[int, int, str], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        on_image_started: Callable[[int, int, str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ):
        self.on_image_processed = on_image_processed
        self.should_cancel = should_cancel
        self.on_image_started = on_image_started
        self.on_status = on_status


def discover_quote_images(folder: Path) -> list[str]:
    return sorted(
        str(path)
        for path in folder.rglob("*")
        if path.is_file() and path.suffix.lower() in QUOTE_IMAGE_EXTENSIONS
    )


# ---------------------------------------------------------------------------
# CLI mode
# ---------------------------------------------------------------------------

def cli_mode(paths: list[str], vault: bool = True):
    """Convert files from command line without GUI."""
    vault_dir = VAULT_DIR if vault else None
    results: list[ConvertResult] = []

    print(f"{'File':<55} {'Words':>10} {'Status'}")
    print("-" * 85)

    for path in paths:
        display_source = path if path.startswith(("http://", "https://")) else Path(path).name
        display = display_source[:52]
        if len(display_source) > 55:
            display += "..."
        try:
            r = route(path, OUTPUT_DIR, vault_dir)
            results.append(r)
            print(f"{display:<55} {r.word_count:>10,} {r.message}")
        except Exception as e:
            results.append(ConvertResult(False, "", 0, f"ERROR: {e}"))
            print(f"{display:<55} {'?':>10} ERROR: {e}")

    ok = sum(1 for r in results if r.success)
    words = sum(r.word_count for r in results)
    print(f"\n{'=' * 85}")
    print(f"SUMMARY: {ok}/{len(paths)} converted | {words:,} total words")
    print(f"Output: {OUTPUT_DIR.resolve()}")
    if vault:
        if VAULT_DIR:
            print(f"Vault:  {VAULT_DIR.resolve()}")
        else:
            print("Vault:  disabled (no config.json)")


# ---------------------------------------------------------------------------
# Inline HTML for the pywebview GUI
# ---------------------------------------------------------------------------

from app_ui import HTML



# ---------------------------------------------------------------------------
# pywebview API class
# ---------------------------------------------------------------------------

class Api:
    """Exposed to JavaScript via pywebview.api."""

    def __init__(self):
        self.window = None          # set after window creation
        self._staged: list[str] = []
        self._staged_folders: list[StagedFolder] = []
        self._cancel_event = threading.Event()
        self._folder_sequence = 0
        self._job_running = False
        self._job_lock = threading.Lock()
        self._preferences_path = default_preferences_path()
        self._preferences = Preferences.load(self._preferences_path)

    # -- helpers to call JS safely from threads --
    def _js(self, code: str):
        """Evaluate JS on the UI thread."""
        if self.window:
            try:
                self.window.evaluate_js(code)
            except Exception:
                pass

    def _log(self, text: str, tag: str = "log-info"):
        safe = json.dumps(text)
        self._js(f"appendLog({safe}, {json.dumps(tag)})")

    def _set_progress(self, pct: float):
        self._js(f"setProgress({pct:.1f})")

    def _set_summary(self, text: str):
        self._js(f"setSummary({json.dumps(text)})")

    def _set_badge(self, text: str | None):
        self._js(f"setBadge({json.dumps(text)})")

    def _show_convert_button(self):
        self._js("showConvertButton()")

    def _hide_convert_button(self):
        self._js("hideConvertButton()")

    def _show_abort_button(self):
        self._js("showAbortButton()")

    def _hide_abort_button(self):
        self._js("hideAbortButton()")

    def _show_log_panel(self):
        self._js("showLogPanel()")

    def _next_folder_id(self) -> str:
        self._folder_sequence += 1
        return f"folder-{self._folder_sequence}"

    def _render_staged_folders(self):
        payload = [
            {
                "id": folder.id,
                "name": folder.path.name,
                "path": str(folder.path),
                "image_count": folder.image_count,
            }
            for folder in self._staged_folders
        ]
        state = {
            "total_count": len(self._collect_staged_paths()),
            "files": [{"path": p, "name": Path(p).name} for p in dict.fromkeys(self._staged)],
            "file_count": len(self._staged),
            "folder_count": len(self._staged_folders),
            "image_count": self._unique_staged_folder_image_count(),
        }
        self._js(f"renderFolderQueue({json.dumps(payload)}, {json.dumps(state)})")

    def _preferences_payload(self) -> dict[str, object]:
        return self._preferences.to_dict()

    def _save_preferences(self) -> None:
        self._preferences.save(self._preferences_path)

    def _effective_output_dir(self) -> Path:
        return self._preferences.output_dir or OUTPUT_DIR

    def _maybe_auto_open_output(self, output_paths: list[Path]) -> None:
        if not self._preferences.auto_open_output or not output_paths:
            return
        target = output_paths[0].resolve().parent if len(output_paths) == 1 else self._effective_output_dir().resolve()
        subprocess.run(["open", str(target)])

    def _refresh_stage_ui(self):
        self._render_staged_folders()
        file_count = len(self._staged)
        folder_count = len(self._staged_folders)
        image_count = self._unique_staged_folder_image_count()

        if file_count and folder_count:
            badge = (
                f"{file_count} file{'s' if file_count != 1 else ''} + "
                f"{folder_count} folder{'s' if folder_count != 1 else ''} staged"
            )
        elif file_count:
            badge = f"{file_count} file{'s' if file_count != 1 else ''} staged"
        elif folder_count:
            badge = (
                f"{folder_count} folder{'s' if folder_count != 1 else ''} staged "
                f"({image_count} image{'s' if image_count != 1 else ''})"
            )
        else:
            badge = None

        self._set_badge(badge)
        if file_count or folder_count:
            self._show_convert_button()
        else:
            self._hide_convert_button()

    def _collect_staged_paths(self) -> list[str]:
        paths: list[str] = []
        seen: set[Path] = set()

        for path in self._staged:
            try:
                resolved = Path(path).resolve()
            except OSError:
                resolved = Path(path).absolute()
            if resolved in seen:
                continue
            seen.add(resolved)
            paths.append(path)

        for folder in self._staged_folders:
            for image_path in folder.images:
                path_obj = Path(image_path)
                try:
                    resolved = path_obj.resolve()
                except OSError:
                    resolved = path_obj.absolute()
                if resolved in seen:
                    continue
                seen.add(resolved)
                paths.append(image_path)

        return paths

    def _unique_staged_folder_image_count(self) -> int:
        seen: set[Path] = set()
        count = 0
        for folder in self._staged_folders:
            for image_path in folder.images:
                path_obj = Path(image_path)
                try:
                    resolved = path_obj.resolve()
                except OSError:
                    resolved = path_obj.absolute()
                if resolved in seen:
                    continue
                seen.add(resolved)
                count += 1
        return count

    def _vault_checked(self) -> bool:
        if self.window:
            try:
                val = self.window.evaluate_js("getVaultChecked()")
                return bool(val)
            except Exception:
                return True
        return True

    # -- public API exposed to JS --

    def get_application_state(self):
        return {"version": VERSION, "output_dir": str(self._effective_output_dir()),
                "vault_configured": bool(VAULT_DIR), "recovery_jobs": self.get_recovery_jobs()}

    def get_recovery_jobs(self):
        jobs = []
        for checkpoint in recovery_checkpoints(self._effective_output_dir() / "quotes"):
            items = checkpoint.items
            jobs.append({"id": checkpoint.report_path.name,
                         "name": Path(items[0]["path"]).parent.name if items else checkpoint.path.stem,
                         "total": len(items), "saved": sum(item["status"] == "success" for item in items),
                         "failed": sum(item["status"] == "failed" for item in items),
                         "vault_pending": bool(checkpoint.report.get("vault_pending")),
                         "needs_finish": not any(item["status"] in ("pending", "failed") for item in items),
                         "pending": sum(item["status"] == "pending" for item in items)})
        return jobs

    def recover_job(self, job_id, retry_failed=False):
        if not isinstance(job_id, str) or job_id not in {job["id"] for job in self.get_recovery_jobs()}:
            self._log("This saved batch is no longer available.", "log-error")
            return False
        report_path = self._effective_output_dir() / "quotes" / job_id
        return self._start_job(self._recovery_worker, report_path, bool(retry_failed))

    def _recovery_worker(self, report_path, retry_failed):
        self._run_worker(self._recovery_worker_body, report_path, retry_failed)

    def _recovery_worker_body(self, report_path, retry_failed):
        checkpoint = QuoteCheckpoint.load(report_path)
        self._show_log_panel()
        self._show_abort_button()
        self._log("Retrying failed images" if retry_failed else "Resuming saved batch", "log-info")
        result = convert_image_folder_quotes(
            [item["path"] for item in checkpoint.items], report_path.parent,
            VAULT_DIR if self._vault_checked() else None,
            hooks=QuoteBatchHooks(
                should_cancel=self._cancel_event.is_set,
                on_image_started=lambda n, total, name: self._set_summary(f"Processing {n} / {total}: {name}"),
                on_image_processed=lambda n, total, name: self._set_progress(100 * n / total if total else 100),
                on_status=lambda text: self._log(text, "log-info")),
            checkpoint_path=report_path, retry_failed=retry_failed)
        self._log(result.message, "log-ok" if result.success else "log-error")
        self._set_summary(result.message)
        if result.output_path:
            self._maybe_auto_open_output([Path(result.output_path)])

    def clear_queue(self):
        if self._job_running:
            return
        self._staged.clear()
        self._staged_folders.clear()
        self._refresh_stage_ui()

    def remove_staged_file(self, path):
        self._staged = [item for item in self._staged if item != path]
        self._refresh_stage_ui()

    def get_preferences(self):
        return self._preferences_payload()

    def save_preferences(self, payload):
        data = self._preferences_payload()
        if isinstance(payload, dict):
            data.update(payload)
        self._preferences = Preferences.from_dict(data)
        self._save_preferences()
        return self._preferences_payload()

    def browse_output_directory(self):
        if not self.window:
            return None
        result = self.window.create_file_dialog(
            webview.FOLDER_DIALOG,
            allow_multiple=False,
            directory=str(self._effective_output_dir().parent),
        )
        if not result:
            return None
        return str(result[0])

    def convert_files(self, paths):
        """Called from JS drop or browse."""
        return self._start_job(self._worker, list(paths))

    def _start_job(self, target, *args, before_start=None):
        if not self._job_lock.acquire(blocking=False):
            self._log("A conversion is already running", "log-error")
            return False
        if self._job_running:
            self._job_lock.release()
            self._log("A conversion is already running", "log-error")
            return False
        self._job_running = True
        self._cancel_event.clear()

        def run():
            try:
                target(*args)
            finally:
                self._job_running = False
                self._job_lock.release()

        try:
            if before_start:
                before_start()
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            self._job_running = False
            self._job_lock.release()
            raise
        return True

    def _run_worker(self, target, *args):
        self._job_running = True
        self._js("setBusy(true)")
        try:
            target(*args)
        except Exception as exc:
            self._log(f"ERROR: {exc}", "log-error")
            self._set_summary(f"Failed: {exc}")
        finally:
            self._job_running = False
            self._hide_abort_button()
            self._js("setBusy(false)")
            try:
                self._js(f"renderRecoveryJobs({json.dumps(self.get_recovery_jobs())})")
            except OSError as exc:
                self._log(f"Could not refresh saved batches: {exc}", "log-error")

    def browse_files(self):
        """Open native file dialog and stage selected files."""
        if not self.window:
            return
        result = self.window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=True,
            file_types=FILETYPES,
        )
        if result:
            self.stage_files([str(p) for p in result])

    def browse_folder(self):
        self._browse_folder_dialog(replace=True)

    def add_folder(self):
        self._browse_folder_dialog(replace=False)

    def _browse_folder_dialog(self, replace: bool):
        if not self.window:
            return
        directory = str(self._staged_folders[-1].path if self._staged_folders else
                        DEFAULT_QUOTE_FOLDER if DEFAULT_QUOTE_FOLDER.exists() else Path.home())
        result = self.window.create_file_dialog(
            webview.FOLDER_DIALOG,
            allow_multiple=False,
            directory=directory,
        )
        if not result:
            return
        self.stage_quote_folder(Path(str(result[0])), replace=replace)

    def fetch_url(self, url):
        """Convert a URL or pasted text to markdown."""
        if not url or not url.strip():
            return False
        text = url.strip()
        return self._start_job(self._paste_worker, text)

    def stage_files(self, paths):
        """Stage files for conversion without converting immediately."""
        if self._job_running:
            return
        for path in paths:
            if Path(path).is_dir():
                self.stage_quote_folder(Path(path), replace=False)
            elif Path(path).suffix.lower() in SUPPORTED:
                if path not in self._staged:
                    self._staged.append(path)
                    self._log(f"Staged: {Path(path).name}", "log-info")
            else:
                self._log(f"Unsupported file: {Path(path).name}", "log-error")
        self._refresh_stage_ui()

    def stage_quote_folder(self, folder: Path, replace: bool = True):
        if self._job_running:
            return
        images = tuple(discover_quote_images(folder))
        if not images:
            self._log(f"No supported quote images found in {folder.name}", "log-error")
            return

        staged_folder = StagedFolder(
            id=self._next_folder_id(),
            path=folder,
            image_count=len(images),
            images=images,
        )

        if replace:
            self._staged_folders = [staged_folder]
            self._log(
                f"Staged folder: {folder.name} ({staged_folder.image_count} image{'s' if staged_folder.image_count != 1 else ''})",
                "log-info",
            )
        else:
            self._staged_folders = [
                existing for existing in self._staged_folders if existing.path != folder
            ]
            self._staged_folders.append(staged_folder)
            self._log(
                f"Added folder: {folder.name} ({staged_folder.image_count} image{'s' if staged_folder.image_count != 1 else ''})",
                "log-info",
            )

        self._refresh_stage_ui()

    def remove_staged_folder(self, folder_id: str):
        self._staged_folders = [
            folder for folder in self._staged_folders if folder.id != folder_id
        ]
        self._refresh_stage_ui()

    def clear_staged_folders(self):
        self._staged_folders = []
        self._refresh_stage_ui()

    def convert_staged(self):
        """Convert all staged files."""
        paths = self._collect_staged_paths()
        if not paths:
            return False
        if self._job_running:
            self._log("A conversion is already running", "log-error")
            return False
        def clear_queue():
            self._staged.clear()
            self._staged_folders = []
            self._refresh_stage_ui()
        return self._start_job(self._worker, paths, before_start=clear_queue)

    def cancel_current_job(self):
        self._cancel_event.set()
        self._log("Stopping after saving completed work…", "log-info")
        self._set_summary("Stopping · completed images are saved")

    def open_output(self):
        output_dir = self._effective_output_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(["open", str(output_dir)])

    def open_vault(self):
        if VAULT_DIR:
            VAULT_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(["open", str(VAULT_DIR)])
        else:
            self._log("No vault configured. Copy config.example.json -> config.json and set vault_path.", "log-error")

    def copy_to_clipboard(self, text):
        """Copy text to macOS clipboard via pbcopy."""
        try:
            proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
            proc.communicate(text.encode("utf-8"))
        except Exception:
            pass

    def close_window(self):
        self._cancel_event.set()
        if self.window:
            self.window.destroy()

    # -- paste worker (URL or plain text) --

    def _paste_worker(self, text: str):
        self._run_worker(self._paste_worker_body, text)

    def _paste_worker_body(self, text: str):
        use_vault = self._vault_checked()
        vault_dir = VAULT_DIR if use_vault else None
        output_dir = self._effective_output_dir()

        is_url = text.startswith("http://") or text.startswith("https://")
        display = text[:60] if is_url else f"Pasted text ({len(text.split())} words)"
        self._show_log_panel()
        self._log(f"Converting: {display}", "log-info")
        self._set_progress(0)

        r = convert_pasted(text, output_dir, vault_dir)
        tag = "log-ok" if r.success else "log-error"
        self._log(f"  {r.message} ({r.word_count:,} words)", tag)
        self._set_progress(100)
        self._set_summary("Done: 1 item converted" if r.success else f"Failed: {r.message}")
        if r.success and r.output_path:
            self._maybe_auto_open_output([Path(r.output_path)])

    # -- worker (runs in background thread) --

    def _worker(self, paths: list[str]):
        self._run_worker(self._worker_body, paths)

    def _worker_body(self, paths: list[str]):
        use_vault = self._vault_checked()
        vault_dir = VAULT_DIR if use_vault else None
        output_dir = self._effective_output_dir()
        ok_count = 0
        total_words = 0
        job_failed = False
        successful_outputs: list[Path] = []
        image_paths = [path for path in paths if Path(path).suffix.lower() in QUOTE_IMAGE_EXTENSIONS]
        other_paths = [path for path in paths if Path(path).suffix.lower() not in QUOTE_IMAGE_EXTENSIONS]
        total = len(other_paths) + len(image_paths)
        processed = 0

        self._show_log_panel()
        self._set_progress(0)
        self._show_abort_button()

        if image_paths:
            self._log(f"Converting: {len(image_paths)} quote image{'s' if len(image_paths) != 1 else ''}", "log-info")
            image_processed = 0
            image_batch_completed = False

            def on_image_started(current: int, total_images: int, image_name: str):
                self._set_summary(f"Processing {processed + current} / {total}: {image_name}")

            def on_image_processed(current: int, total_images: int, image_name: str):
                nonlocal image_processed
                image_processed = current
                overall_processed = processed + current
                pct = (overall_processed / total) * 100 if total else 100
                self._set_progress(pct)
                self._set_summary(f"Processed {overall_processed} / {total}: {image_name}")

            try:
                result = convert_image_folder_quotes(
                    image_paths,
                    output_dir / "quotes",
                    vault_dir,
                    hooks=QuoteBatchHooks(
                        on_image_processed=on_image_processed,
                        should_cancel=self._cancel_event.is_set,
                        on_image_started=on_image_started,
                        on_status=lambda message: self._log(message, "log-info"),
                    ),
                    raw_ocr_mode=self._preferences.raw_ocr_mode,
                )
                total_words += result.word_count
                if result.output_path:
                    successful_outputs.append(Path(result.output_path))
                if result.success:
                    ok_count += image_processed or len(image_paths)
                    tag = "log-ok"
                else:
                    job_failed = True
                    tag = "log-error"
                self._log(f"  {result.message} ({result.word_count:,} words)", tag)
                image_batch_completed = result.success
            except Exception as exc:
                job_failed = True
                self._log(f"  ERROR: {exc}", "log-error")

            if self._cancel_event.is_set():
                processed += image_processed
            elif image_batch_completed:
                processed += image_processed or len(image_paths)
            else:
                processed += image_processed
            if total:
                self._set_progress((processed / total) * 100)

        for path in other_paths:
            if self._cancel_event.is_set():
                break

            name = Path(path).name if not path.startswith("http") else path[:60]
            self._log(f"Converting: {name}", "log-info")
            self._set_summary(f"Processing {processed + 1} / {total}: {name}")

            try:
                options = {"should_cancel": self._cancel_event.is_set} if Path(path).suffix.lower() == ".pdf" else {}
                r = route(path, output_dir, vault_dir, **options)
                total_words += r.word_count
                if r.success:
                    ok_count += 1
                    tag = "log-ok"
                    if r.output_path:
                        successful_outputs.append(Path(r.output_path))
                else:
                    job_failed = True
                    tag = "log-error"
                self._log(f"  {r.message} ({r.word_count:,} words)", tag)
            except Exception as e:
                job_failed = True
                self._log(f"  ERROR: {e}", "log-error")

            processed += 1
            pct = ((processed) / total) * 100 if total else 100
            self._set_progress(pct)

        if self._cancel_event.is_set():
            summary_text = f"Canceled: {processed}/{total} processed | {total_words:,} total words"
            summary_tag = "log-info"
        elif job_failed:
            label = "Saved with issues" if total_words else "Failed"
            summary_text = f"{label}: {processed}/{total} processed | {total_words:,} total words"
            summary_tag = "log-error"
        else:
            summary_text = f"Done: {processed}/{total} processed | {total_words:,} total words"
            summary_tag = "log-ok"
        self._log(f"\n{summary_text}", summary_tag)
        self._set_summary(summary_text)
        self._set_badge(None)
        self._maybe_auto_open_output(successful_outputs)

    def _quote_folder_worker(self, paths: list[str]):
        self._worker(paths)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    from app_version import VERSION
    # CLI mode: arguments provided
    if len(sys.argv) > 1:
        cli_mode(sys.argv[1:])
        return

    # GUI mode
    api = Api()
    # Inject vault checkbox state into HTML before creating window
    vault_checked = "checked" if VAULT_DIR else ""
    html = HTML.replace("VAULT_CHECKED", vault_checked)

    window = webview.create_window(
        f"MD Converter {VERSION}",
        html=html,
        js_api=api,
        width=820,
        height=780,
        min_size=(640, 640),
        resizable=True,
        background_color="#181b1b",
    )
    api.window = window
    window.events.closing += lambda: api._cancel_event.set()

    def on_loaded():
        if _NATIVE_DROP:
            def drop_callback(file_paths):
                api.stage_files(file_paths)
            threading.Thread(
                target=setup_native_drop,
                args=(window, drop_callback),
                daemon=True,
            ).start()

    webview.start(func=on_loaded)


if __name__ == "__main__":
    main()
