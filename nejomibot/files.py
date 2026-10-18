"""The files the bot keeps what it's told in, and what it's done: the timers,
the specials, the allowed list, the photos sent and the messages waiting to be
sent. They list phone numbers, so only the bot's user may read them."""

import contextlib
import os
import tempfile
from pathlib import Path


def write_privately(path: Path, text: str) -> None:
    """Replace the file with the text, through a temp file beside it, so it's
    never read half written, and on disk before it replaces the file, so a
    power cut can't leave it empty. Raises OSError, and then leaves the file
    as it was."""
    fd, name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".part"
    )
    part = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        part.replace(path)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    # The new name, too; a file system that can't sync a folder keeps it anyway
    with contextlib.suppress(OSError):
        folder = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(folder)
        finally:
            os.close(folder)


def append_privately(path: Path, line: str) -> None:
    """Add a line to the file, or start it. Raises OSError."""
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        os.fchmod(fd, 0o600)  # if it was made before, with another mode
        f.write(f"{line}\n")
