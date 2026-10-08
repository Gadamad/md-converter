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
    atomic_write_chunks(path, (text,))


def atomic_write_chunks(path: Path, chunks) -> None:
    """Stream an iterable into an atomic replacement without joining it in RAM."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=f".{path.name}.", delete=False) as stream:
            temporary = Path(stream.name)
            for chunk in chunks:
                stream.write(chunk)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
