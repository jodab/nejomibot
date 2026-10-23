import logging
import os
import tarfile
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from signalbot import SignalBot

from nejomibot import backups
from nejomibot.backups import back_up, catch_up, daily, due, made, prune, state
from nejomibot.config import get_settings

STOCKHOLM = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 10, 19, 4, 0, tzinfo=STOCKHOLM)
NAME = "nejomibot-2026-10-19_0400"


@pytest.fixture
def data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """data_dir with what the bot keeps, the config in it, as in the
    container, and the sample config in the working directory."""
    folder = get_settings().data_dir
    for name, text in {
        "allowed.txt": "+46700000001  # Alice\n",
        "timers.txt": "1 | daily 08:00 | group.ZmFtaWx5 | /today | -\n",
        "birthdays.txt": "birthday | 03-14 | * | Grandma\n",
        "sent-photos.txt": "2026/a.jpg\n",
        "run.json": "{}",
        ".timers.txt.abc.part": "half written",
        "config.toml": "# the config\n",
    }.items():
        (folder / name).write_text(text)
    (folder / "outbox").mkdir()
    (folder / "outbox" / "1.json").write_text("{}")
    sample = tmp_path / "config.example.toml"
    sample.write_text("# every setting\n")
    monkeypatch.setattr(backups, "SAMPLE", sample)
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(folder / "config.toml"))
    get_settings.cache_clear()
    return folder


def members(path: Path | None) -> dict[str, str]:
    """The archive's files, by name, and what they say."""
    assert path is not None
    with tarfile.open(path) as tar:
        return {
            info.name: (f.read().decode() if (f := tar.extractfile(info)) else "/")
            for info in tar.getmembers()
        }


def test_a_backup_has_what_the_bot_keeps(data: Path) -> None:
    path = back_up(NOW)
    assert path == data / "backups" / f"{NAME}.tar.zst"
    # Not how it last ran, nor messages that would go out again, nor files
    # being written; the config once, though it's in data_dir
    assert members(path) == {
        NAME: "/",
        f"{NAME}/allowed.txt": "+46700000001  # Alice\n",
        f"{NAME}/birthdays.txt": "birthday | 03-14 | * | Grandma\n",
        f"{NAME}/config.toml": "# the config\n",
        f"{NAME}/sent-photos.txt": "2026/a.jpg\n",
        f"{NAME}/timers.txt": "1 | daily 08:00 | group.ZmFtaWx5 | /today | -\n",
        f"{NAME}/config.example.toml": "# every setting\n",
    }


def test_only_the_bots_user_may_read_them(data: Path) -> None:
    (data / "allowed.txt").chmod(0o600)
    path = back_up(NOW)
    assert path is not None
    assert path.stat().st_mode & 0o777 == 0o600
    assert path.parent.stat().st_mode & 0o777 == 0o700
    with tarfile.open(path) as tar:
        assert tar.getmember(NAME).mode == 0o700
        assert tar.getmember(f"{NAME}/allowed.txt").mode == 0o600
    assert not list(path.parent.glob(".*.part"))


def test_it_unpacks_into_a_folder_of_its_name(data: Path, tmp_path: Path) -> None:
    with tarfile.open(back_up(NOW)) as tar:
        tar.extractall(tmp_path / "restored", filter="data")
    restored = tmp_path / "restored" / NAME
    assert (restored / "timers.txt").read_text() == (data / "timers.txt").read_text()


def test_a_config_elsewhere_by_its_name(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (data / "config.toml").unlink()
    config = tmp_path / "bot.toml"
    config.write_text("# elsewhere\n")
    monkeypatch.setenv("NEJOMIBOT_CONFIG", str(config))
    assert members(back_up(NOW))[f"{NAME}/bot.toml"] == "# elsewhere\n"


def test_without_a_config_or_a_sample(
    data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # All in the environment, and the bot run from elsewhere
    (data / "config.toml").unlink()
    monkeypatch.setattr(backups, "SAMPLE", tmp_path / "nowhere.toml")
    assert f"{NAME}/allowed.txt" in members(back_up(NOW))


def test_a_big_file_isnt_the_bots(
    data: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(backups, "MAX_FILE", 20)
    (data / "movie.mkv").write_bytes(b"x" * 21)
    assert f"{NAME}/movie.mkv" not in members(back_up(NOW))
    assert "Left movie.mkv out of the backup: over 10 MB" in caplog.messages


def stamp(folder: Path, when: datetime) -> Path:
    path = folder / f"nejomibot-{when:%Y-%m-%d_%H%M}.tar.zst"
    path.write_bytes(b"")
    return path


def test_the_newest_are_kept(tmp_path: Path) -> None:
    folder = tmp_path / "backups"
    folder.mkdir()
    old = [stamp(folder, NOW - timedelta(days=days)) for days in (4, 3, 2, 1)]
    (folder / "notes.txt").write_text("the admin's own")
    (folder / "nejomibot-old.tar.zst").write_bytes(b"")  # not one of the bot's
    prune(folder, 2)
    assert sorted(path.name for path in folder.iterdir()) == [
        old[2].name,
        old[3].name,
        "nejomibot-old.tar.zst",
        "notes.txt",
    ]


def test_a_backup_deletes_the_oldest_beyond_backups_kept(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_BACKUPS_KEPT", "2")
    get_settings.cache_clear()
    folder = data / "backups"
    folder.mkdir()
    for days in (3, 2, 1):
        stamp(folder, NOW - timedelta(days=days))
    back_up(NOW)
    assert sorted(path.name for path in folder.iterdir()) == [
        "nejomibot-2026-10-18_0400.tar.zst",
        f"{NAME}.tar.zst",
    ]


def test_due_when_none_is_from_the_last_day(data: Path) -> None:
    assert made() == []
    assert due(NOW)
    folder = data / "backups"
    folder.mkdir()
    stamp(folder, NOW - timedelta(days=2))
    stamp(folder, NOW - timedelta(hours=23))
    assert made() == [NOW - timedelta(days=2), NOW - timedelta(hours=23)]
    assert not due(NOW)
    assert due(NOW + timedelta(hours=1))


def test_elsewhere(data: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # As on a disk of their own
    monkeypatch.setenv("NEJOMIBOT_BACKUPS_DIR", str(tmp_path / "elsewhere"))
    get_settings.cache_clear()
    assert back_up(NOW) == tmp_path / "elsewhere" / f"{NAME}.tar.zst"
    assert made() == [NOW]
    assert not (data / "backups").exists()


def test_in_data_dir_itself(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The backups aren't backed up again
    monkeypatch.setenv("NEJOMIBOT_BACKUPS_DIR", str(data))
    get_settings.cache_clear()
    back_up(NOW - timedelta(days=1))
    # Nothing else changed: the backup made isn't a change
    assert back_up(NOW) is None
    (data / "timers.txt").write_text("")
    path = back_up(NOW)
    assert path is not None
    assert f"{NAME}/nejomibot-2026-10-18_0400.tar.zst" not in members(path)


def test_how_they_are(data: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    assert state(NOW) == (True, "none yet")
    folder = data / "backups"
    folder.mkdir()
    stamp(folder, NOW - timedelta(hours=5))
    assert state(NOW) == (True, "1, 5 h 0 min old")
    stamp(folder, NOW - timedelta(days=29, hours=5))
    stamp(folder, NOW - timedelta(days=1, hours=5))
    assert state(NOW) == (
        True,
        "3, the newest 5 h 0 min old, the oldest 29 d 5 h old",
    )
    # Stopped, as when the daily job no longer runs
    assert state(NOW + timedelta(days=2)) == (
        False,
        "3, the newest 2 d 5 h old, the oldest 31 d 5 h old",
    )
    monkeypatch.setenv("NEJOMIBOT_BACKUPS", "false")
    get_settings.cache_clear()
    assert state(NOW) == (True, "off")


async def test_a_failure_shows_till_a_backup_works(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backups, "last_failure", None)
    write = backups.replace_privately
    disk_full = True

    def replace_privately(path: Path, writer: Any) -> int:
        if disk_full:
            raise OSError(28, "No space left on device")
        return write(path, writer)

    monkeypatch.setattr(backups, "replace_privately", replace_privately)
    await daily()
    assert state(NOW) == (
        False,
        "last failed: [Errno 28] No space left on device; none yet",
    )
    disk_full = False
    await daily()
    ok, detail = state(datetime.now(STOCKHOLM))
    assert ok
    assert detail.startswith("1, ")


class FakeScheduler:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}

    def add_job(self, work: object, trigger: str | None = None, **job: Any) -> None:
        self.jobs[job["id"]] = {"work": work, "trigger": trigger, **job}


def started(monkeypatch: pytest.MonkeyPatch, **env: str) -> dict[str, dict[str, Any]]:
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    bot = SimpleNamespace(scheduler=FakeScheduler())
    backups.start(cast(SignalBot, bot))
    return bot.scheduler.jobs


def test_every_day_and_at_a_start(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = started(monkeypatch)
    assert jobs["backups"]["work"] is daily
    backup = jobs["backups"]
    assert (backup["trigger"], backup["hour"], backup["minute"]) == ("cron", 4, 0)
    assert backup["timezone"] == STOCKHOLM
    assert jobs["backups-start"]["work"] is catch_up


def test_at_a_time_of_your_own(monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = started(monkeypatch, NEJOMIBOT_BACKUPS_AT="23:45")
    assert (jobs["backups"]["hour"], jobs["backups"]["minute"]) == (23, 45)


@pytest.mark.parametrize(
    "env",
    [
        {"NEJOMIBOT_BACKUPS": "false"},
        # Which keeps its files in a temp folder, new at each start
        {"NEJOMIBOT_DEBUG": "1", "NEJOMIBOT_DEBUG_GROUP": "group.ZmFtaWx5"},
    ],
)
def test_none(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    assert started(monkeypatch, **env) == {}


async def test_a_start_backs_up_only_when_due(data: Path) -> None:
    await catch_up()
    made = list((data / "backups").iterdir())
    assert len(made) == 1
    await catch_up()
    assert list((data / "backups").iterdir()) == made


async def test_a_failure_is_logged(
    data: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(backups, "last_failure", None)
    (data / "backups").write_text("a file in the folder's place")
    await daily()
    await catch_up()
    failed = [r for r in caplog.records if r.levelno >= logging.WARNING]
    assert [r.getMessage().split(":")[0] for r in failed] == [
        "The backup failed",
        "Looking for the latest backup failed",
    ]


def test_none_when_nothing_changed(
    data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, "nejomibot")
    first = back_up(NOW - timedelta(days=1))
    assert first is not None
    assert back_up(NOW) is None
    assert f"Nothing changed since the backup {first.name}" in caplog.messages
    # Not by its time, but by what it says
    os.utime(data / "allowed.txt", (0, 0))
    assert back_up(NOW) is None
    (data / "allowed.txt").write_text("+46700000002  # Bob\n")
    assert back_up(NOW) is not None
    # Nor a file more, or less
    (data / "lists.txt").write_text("")
    assert back_up(NOW + timedelta(days=1)) is not None
    (data / "lists.txt").unlink()
    assert back_up(NOW + timedelta(days=2)) is not None


def test_a_backup_that_cant_be_read_is_made_anew(
    data: Path, caplog: pytest.LogCaptureFixture
) -> None:
    folder = data / "backups"
    folder.mkdir()
    for broken in (b"", b"not zstd at all", b"(\xb5/\xfd truncated"):
        stamp(folder, NOW - timedelta(days=1)).write_bytes(broken)
        assert back_up(NOW) is not None
        (folder / f"{NAME}.tar.zst").unlink()
    assert any(m.startswith("Could not read the backup") for m in caplog.messages)


async def test_unchanged_counts_as_current(
    data: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    back_up(datetime.now(STOCKHOLM) - timedelta(days=3))
    ok, detail = state(datetime.now(STOCKHOLM))
    assert not ok  # three days old
    await daily()
    ok, detail = state(datetime.now(STOCKHOLM))
    assert ok
    assert detail.startswith("1, 3 d ")
    assert detail.endswith("; last skipped: no changes")
    assert not due(datetime.now(STOCKHOLM))
    # Till a backup is made
    (data / "timers.txt").write_text("")
    await daily()
    assert backups.unchanged_at is None
    assert len(made()) == 2
