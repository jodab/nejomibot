from pathlib import Path

from nejomibot.files import append_privately, write_privately


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
