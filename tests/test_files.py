import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from nejomibot.config import get_settings
from nejomibot.files import KeptLines, append_privately, write_privately


def test_written_privately(tmp_path: Path) -> None:
    (tmp_path / "files").mkdir()
    path = tmp_path / "files/list.txt"
    path.write_text("old\n")
    path.chmod(0o644)
    write_privately(path, "new ✓\n")
    assert path.read_text(encoding="utf-8") == "new ✓\n"
    assert path.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in path.parent.iterdir()] == ["list.txt"]


def test_appended_privately(tmp_path: Path) -> None:
    path = tmp_path / "sent.txt"
    append_privately(path, "å.jpg")
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)  # as it was made before
    append_privately(path, "b.jpg")
    assert path.read_text(encoding="utf-8") == "å.jpg\nb.jpg\n"
    assert path.stat().st_mode & 0o777 == 0o600


@dataclass(frozen=True)
class Word:
    text: str


def parse_word(line: str) -> Word:
    if not line.strip().isalpha():
        raise ValueError(f"{line} isn't a word")
    return Word(line.strip())


def words() -> KeptLines[Word]:
    return KeptLines("words.txt", ["# Words"], parse_word, lambda word: word.text)


def test_kept_lines_start_their_file() -> None:
    kept = words()
    assert kept.current().entries == []
    kept.add(Word("hej"), Word("då"))
    path = get_settings().data_file("words.txt")
    assert path.read_text(encoding="utf-8") == "# Words\nhej\ndå\n"
    assert path.stat().st_mode & 0o777 == 0o600
    assert kept.entries == [Word("hej"), Word("då")]


def test_kept_lines_changed_by_hand(caplog: pytest.LogCaptureFixture) -> None:
    kept = words()
    path = get_settings().data_file("words.txt")
    path.write_text("# mine\nhej\n7 + 7\n\ndå\n")
    assert kept.current().entries == [Word("hej"), Word("då")]
    assert kept.broken == ["7 + 7"]
    assert "words.txt line 3 left alone, as it can't be read" in caplog.text
    # What the line says may be someone's: only at DEBUG
    assert "7 + 7" not in caplog.text
    # Comments, blank lines and what can't be read stay as they are
    kept.add(Word("igen"))
    assert path.read_text() == "# mine\nhej\n7 + 7\n\ndå\nigen\n"
    path.unlink()
    assert kept.current().entries == []


def test_kept_lines_remove_the_lines_of_what_they_re_given() -> None:
    kept = words()
    kept.add(Word("hej"), Word("då"), Word("hej"))
    # The second hej, not the first, though they're alike
    kept.remove([kept.entries[2]])
    assert get_settings().data_file("words.txt").read_text() == "# Words\nhej\ndå\n"
    kept.remove(kept.entries)
    assert get_settings().data_file("words.txt").read_text() == "# Words\n"


def test_kept_lines_that_can_t_be_read_stay_as_they_were(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.ERROR)
    kept = words()
    kept.add(Word("hej"))
    path = get_settings().data_file("words.txt")
    path.write_bytes(b"\xff\xfe")
    assert kept.current().entries == [Word("hej")]
    assert kept.current().entries == [Word("hej")]
    # Logged once, not at every look
    assert caplog.text.count("Could not read") == 1


def test_kept_lines_keep_what_they_have_when_they_can_t_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kept = words()
    kept.add(Word("hej"))

    def full(path: Path, text: str) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("nejomibot.files.write_privately", full)
    with pytest.raises(OSError, match="No space"):
        kept.add(Word("då"))
    assert kept.entries == [Word("hej")]
