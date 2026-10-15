from __future__ import annotations

import json
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from file_utils import atomic_write_text


ThemeMode = Literal["system", "dark", "light"]
RawOcrMode = Literal["different", "always", "never"]
EpubOutputFormat = Literal["md", "txt"]

THEME_CHOICES: Final[tuple[ThemeMode, ...]] = ("system", "dark", "light")
RAW_OCR_MODE_CHOICES: Final[tuple[RawOcrMode, ...]] = ("different", "always", "never")
EPUB_OUTPUT_FORMAT_CHOICES: Final[tuple[EpubOutputFormat, ...]] = ("md", "txt")
DEFAULT_THEME: Final[ThemeMode] = "system"
DEFAULT_RAW_OCR_MODE: Final[RawOcrMode] = "different"
DEFAULT_EPUB_OUTPUT_FORMAT: Final[EpubOutputFormat] = "md"
DEFAULT_AUTO_OPEN_OUTPUT: Final[bool] = False
DEFAULT_INCLUDE_SUBFOLDERS: Final[bool] = True
_APP_SUPPORT_DIR_NAME: Final[str] = "MD Converter"
_PREFERENCES_FILENAME: Final[str] = "preferences.json"
_PRIMARY_OUTPUT_FOLDERS: Final[frozenset[str]] = frozenset({'quotes', 'pdf', 'docx', 'spreadsheets', 'html', 'txt', 'rtf', 'epub'})


def validate_epub_output_format(value: object) -> EpubOutputFormat:
    if not isinstance(value, str) or value not in EPUB_OUTPUT_FORMAT_CHOICES:
        raise ValueError('EPUB output must be Markdown (md) or plain text (txt).')
    return value


def _parse_epub_output_format(value: object) -> EpubOutputFormat:
    try:
        return validate_epub_output_format(value)
    except ValueError:
        return DEFAULT_EPUB_OUTPUT_FORMAT


def validate_copy_subfolder(value: object) -> str | None:
    """Return one safe, accent-preserving child folder name, or disable copies."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError('Folder name must be text.')
    if any(unicodedata.category(character).startswith('C') for character in value):
        raise ValueError('Folder name cannot contain control characters.')
    name = value.strip()
    if not name or name in {'.', '..'} or '/' in name or '\\' in name or Path(name).is_absolute():
        raise ValueError('Enter one folder name without slashes or path traversal.')
    if len(name.encode('utf-8')) > 255:
        raise ValueError('Folder name is too long. Use a shorter name.')
    if name.casefold() in _PRIMARY_OUTPUT_FOLDERS:
        raise ValueError('This folder is used for regular exports. Choose a different folder name.')
    return name


def _parse_copy_subfolder(value: object) -> str | None:
    try:
        return validate_copy_subfolder(value)
    except ValueError:
        return None


def _parse_auto_open_output(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return DEFAULT_AUTO_OPEN_OUTPUT


def _parse_output_dir(value: object) -> Path | None:
    if not isinstance(value, str) or not value or "\0" in value:
        return None
    try:
        path = Path(value).expanduser()
    except RuntimeError:
        return None
    if not path.is_absolute():
        return None
    return path


def _parse_theme(value: object) -> ThemeMode:
    if isinstance(value, str) and value in THEME_CHOICES:
        return value
    return DEFAULT_THEME


def _parse_raw_ocr_mode(value: object) -> RawOcrMode:
    if isinstance(value, str) and value in RAW_OCR_MODE_CHOICES:
        return value
    return DEFAULT_RAW_OCR_MODE


def default_preferences_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path.home() / "Library" / "Application Support" / _APP_SUPPORT_DIR_NAME / _PREFERENCES_FILENAME
    return Path(__file__).resolve().parent.parent / _PREFERENCES_FILENAME


@dataclass(frozen=True, slots=True)
class Preferences:
    theme: ThemeMode = DEFAULT_THEME
    raw_ocr_mode: RawOcrMode = DEFAULT_RAW_OCR_MODE
    output_dir: Path | None = None
    auto_open_output: bool = DEFAULT_AUTO_OPEN_OUTPUT
    include_subfolders: bool = DEFAULT_INCLUDE_SUBFOLDERS
    show_source_details: bool = False
    copy_subfolder: str | None = None
    epub_output_format: EpubOutputFormat = DEFAULT_EPUB_OUTPUT_FORMAT

    def __post_init__(self) -> None:
        if self.theme not in THEME_CHOICES:
            raise ValueError(f"Invalid theme: {self.theme}")
        if self.raw_ocr_mode not in RAW_OCR_MODE_CHOICES:
            raise ValueError(f"Invalid raw OCR mode: {self.raw_ocr_mode}")
        validate_epub_output_format(self.epub_output_format)
        if not isinstance(self.include_subfolders, bool):
            raise ValueError('Include subfolders must be a boolean.')
        if not isinstance(self.show_source_details, bool):
            raise ValueError('Show source details must be a boolean.')
        object.__setattr__(self, 'copy_subfolder', validate_copy_subfolder(self.copy_subfolder))

    def to_dict(self) -> dict[str, object]:
        return {
            "theme": self.theme,
            "raw_ocr_mode": self.raw_ocr_mode,
            "epub_output_format": self.epub_output_format,
            "output_dir": str(self.output_dir) if self.output_dir is not None else None,
            "auto_open_output": self.auto_open_output,
            "include_subfolders": self.include_subfolders,
            "show_source_details": self.show_source_details,
            "copy_subfolder": self.copy_subfolder,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Preferences:
        return cls(
            theme=_parse_theme(data.get("theme", DEFAULT_THEME)),
            raw_ocr_mode=_parse_raw_ocr_mode(data.get("raw_ocr_mode", DEFAULT_RAW_OCR_MODE)),
            epub_output_format=_parse_epub_output_format(data.get("epub_output_format", DEFAULT_EPUB_OUTPUT_FORMAT)),
            output_dir=_parse_output_dir(data.get("output_dir")),
            auto_open_output=_parse_auto_open_output(data.get("auto_open_output", DEFAULT_AUTO_OPEN_OUTPUT)),
            include_subfolders=(data['include_subfolders'] if isinstance(data.get('include_subfolders'), bool)
                                else DEFAULT_INCLUDE_SUBFOLDERS),
            show_source_details=(data['show_source_details'] if isinstance(data.get('show_source_details'), bool)
                                 else False),
            copy_subfolder=_parse_copy_subfolder(data.get('copy_subfolder')),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(self.to_dict(), indent=2) + "\n")

    @classmethod
    def load(cls, path: Path) -> Preferences:
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        return cls.from_dict(data)
