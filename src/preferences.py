from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from file_utils import atomic_write_text


ThemeMode = Literal["system", "dark", "light"]
RawOcrMode = Literal["different", "always", "never"]

THEME_CHOICES: Final[tuple[ThemeMode, ...]] = ("system", "dark", "light")
RAW_OCR_MODE_CHOICES: Final[tuple[RawOcrMode, ...]] = ("different", "always", "never")
DEFAULT_THEME: Final[ThemeMode] = "system"
DEFAULT_RAW_OCR_MODE: Final[RawOcrMode] = "different"
DEFAULT_AUTO_OPEN_OUTPUT: Final[bool] = False
DEFAULT_INCLUDE_SUBFOLDERS: Final[bool] = True
_APP_SUPPORT_DIR_NAME: Final[str] = "MD Converter"
_PREFERENCES_FILENAME: Final[str] = "preferences.json"


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

    def __post_init__(self) -> None:
        if self.theme not in THEME_CHOICES:
            raise ValueError(f"Invalid theme: {self.theme}")
        if self.raw_ocr_mode not in RAW_OCR_MODE_CHOICES:
            raise ValueError(f"Invalid raw OCR mode: {self.raw_ocr_mode}")
        if not isinstance(self.include_subfolders, bool):
            raise ValueError('Include subfolders must be a boolean.')

    def to_dict(self) -> dict[str, object]:
        return {
            "theme": self.theme,
            "raw_ocr_mode": self.raw_ocr_mode,
            "output_dir": str(self.output_dir) if self.output_dir is not None else None,
            "auto_open_output": self.auto_open_output,
            "include_subfolders": self.include_subfolders,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Preferences:
        return cls(
            theme=_parse_theme(data.get("theme", DEFAULT_THEME)),
            raw_ocr_mode=_parse_raw_ocr_mode(data.get("raw_ocr_mode", DEFAULT_RAW_OCR_MODE)),
            output_dir=_parse_output_dir(data.get("output_dir")),
            auto_open_output=_parse_auto_open_output(data.get("auto_open_output", DEFAULT_AUTO_OPEN_OUTPUT)),
            include_subfolders=(data['include_subfolders'] if isinstance(data.get('include_subfolders'), bool)
                                else DEFAULT_INCLUDE_SUBFOLDERS),
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
