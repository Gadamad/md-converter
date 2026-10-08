"""Collision-safe output reservation and atomic checkpoint replacement."""
import os
from pathlib import Path
import tempfile


def reserve_output_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    index = 1
    while True:
        name = stem if index == 1 else f"{stem}_{index}"
        path = directory / f"{name}{suffix}"
        try:
            with path.open("x", encoding="utf-8"):
                pass
            return path
        except FileExistsError:
            index += 1


def atomic_write_text(path: Path, text: str) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
