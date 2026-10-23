"""Backups: every day at backups_at, 04:00 if not given, in the bot's time
zone, the bot backs up what it keeps in data_dir, and its config, into
backups_dir (data_dir/backups if not given): a compressed tar archive named
by when it was made, such as nejomibot-2026-10-19_0400.tar.zst, which
unpacks into a folder of that name. At a start, it makes one at once if the
latest is a day old or more, or there's none. When nothing in the files has
changed since the latest backup, by what they say, it makes none: the
backups are as current as before. It keeps the newest backups_kept (30, a
month's), and deletes older ones; anything else in the folder it leaves
alone. backups = false makes none.

An archive has every file in data_dir but run.json, which only says how the
bot last ran, and files over 10 MB, which aren't the bot's; nor the messages
waiting to be sent (data_dir/outbox), which would go out again, late. Then
the config, and the sample config of the version that made it
(config.example.toml in the working directory: /app in the image), each if
it's there. Only the bot's user may read them, as they list phone numbers,
and the config has the OpenWeatherMap key. In debug mode, which keeps its
files in a temp folder, there are none.

/status and the health check pings say how many there are, and how old the
newest and the oldest are; /status's check fails when the last backup
failed, or the backups haven't been current for two days.
"""

import asyncio
import hashlib
import logging
import os
import re
import tarfile
import time
from compression.zstd import ZstdError
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO, BinaryIO

from signalbot import SignalBot

from .config import config_file, get_settings
from .files import replace_privately
from .i18n import _, format_duration, ngettext
from .messages import describe, log_failure

logger = logging.getLogger(__name__)

STAMP = "%Y-%m-%d_%H%M"  # when it was made, in the bot's time zone
NAME = re.compile(r"^nejomibot-(\d{4}-\d{2}-\d{2}_\d{4})\.tar\.zst$")
LEFT_OUT = frozenset({"run.json"})  # how the bot last ran: nothing to restore
MAX_FILE = 10 * 2**20  # bytes: bigger files aren't the bot's
SAMPLE = Path("config.example.toml")  # in the working directory, as in the image
STALE = timedelta(days=2)  # not current for this long: they've stopped

last_failure: str | None = None  # why the last backup failed, till one works
# When the last backup was found needless, nothing having changed since the
# newest, till one is made: the backups were current then
unchanged_at: datetime | None = None


def backed_up() -> list[tuple[Path, str]]:
    """What a backup has, each by its name in it: the files in data_dir
    worth restoring, then the config and the sample config, if they're there,
    each once; but files too big to be the bot's."""
    found: dict[Path, str] = {}
    for path in sorted(get_settings().data_dir.iterdir()):
        if (
            path.name.startswith(".")  # temp files, being written
            or path.name in LEFT_OUT
            or NAME.match(path.name)  # backups, with backups_dir = data_dir
            or not path.is_file(follow_symlinks=False)  # outbox/, backups/
        ):
            continue
        found[path.resolve()] = path.name
    for path in (config_file(), SAMPLE):
        if path.is_file():
            found.setdefault(path.resolve(), path.name)
    files: list[tuple[Path, str]] = []
    for path, name in found.items():
        if path.stat().st_size > MAX_FILE:
            logger.warning("Left %s out of the backup: over 10 MB", name)
        else:
            files.append((path, name))
    return files


def add(tar: tarfile.TarFile, path: Path, name: str) -> None:
    """Add the file as name, by its owner's number only, as looking up their
    name loads libraries the bot has no other use for, and keeps them."""
    with path.open("rb") as f:
        stat = os.fstat(f.fileno())
        info = tarfile.TarInfo(name)
        info.size, info.mtime = stat.st_size, int(stat.st_mtime)
        info.mode = stat.st_mode & 0o7777
        info.uid, info.gid = stat.st_uid, stat.st_gid
        tar.addfile(info, f)


def write_archive(f: BinaryIO, name: str, files: list[tuple[Path, str]]) -> int:
    """The files, in a folder called name, as a tar archive compressed with
    Zstandard; how many there are."""
    with tarfile.open(fileobj=f, mode="w:zst") as tar:
        top = tarfile.TarInfo(name)
        top.type, top.mode, top.mtime = tarfile.DIRTYPE, 0o700, int(time.time())
        top.uid, top.gid = os.getuid(), os.getgid()
        tar.addfile(top)
        for path, each in files:
            add(tar, path, f"{name}/{each}")
    return len(files)


def digest(f: IO[bytes]) -> str:
    """What the file says, as a SHA-256, read a bit at a time."""
    sha = hashlib.sha256()
    while chunk := f.read(2**16):
        sha.update(chunk)
    return sha.hexdigest()


def digests(files: list[tuple[Path, str]]) -> dict[str, str]:
    """What each file says, by its name in a backup."""
    found: dict[str, str] = {}
    for path, name in files:
        with path.open("rb") as f:
            found[name] = digest(f)
    return found


def archived_digests(backup: Path) -> dict[str, str]:
    """What each file in the backup says, by its name in it."""
    found: dict[str, str] = {}
    with tarfile.open(backup, "r:zst") as tar:
        for member in tar:
            if member.isfile() and (f := tar.extractfile(member)):
                found[member.name.partition("/")[2]] = digest(f)
    return found


def unchanged(files: list[tuple[Path, str]], backup: Path) -> bool:
    """Whether the backup has the files as they are now, by what they say,
    whatever their times. Raises OSError for the files."""
    now = digests(files)
    try:
        return archived_digests(backup) == now
    except (OSError, EOFError, ZstdError, tarfile.TarError) as e:
        logger.warning(
            "Could not read the backup %s, so making a new one: %s",
            backup.name,
            describe(e),
        )
        return False


def back_up(now: datetime) -> Path | None:
    """Make a backup, named by now, unless nothing has changed since the
    newest, then delete the oldest beyond backups_kept. The backup made, if
    one was. Raises OSError."""
    settings = get_settings()
    folder = settings.backups_folder
    folder.mkdir(mode=0o700, exist_ok=True)
    files = backed_up()
    backups = listed(folder)
    path: Path | None = None
    if backups and unchanged(files, backups[-1]):
        logger.info("Nothing changed since the backup %s", backups[-1].name)
    else:
        name = f"nejomibot-{now:{STAMP}}"
        path = folder / f"{name}.tar.zst"
        count = replace_privately(path, lambda f: write_archive(f, name, files))
        logger.info("Backed up %d files, in %s", count, path)
    prune(folder, settings.backups_kept)
    return path


def listed(folder: Path) -> list[Path]:
    """The backups in the folder, the oldest first, as their names say when
    they were made. Raises OSError."""
    return sorted(path for path in folder.iterdir() if NAME.match(path.name))


def prune(folder: Path, keep: int) -> None:
    """Delete the backups but the newest keep. Raises OSError."""
    backups = listed(folder)
    for path in backups[: max(len(backups) - keep, 0)]:
        path.unlink(missing_ok=True)
        logger.info("Deleted the old backup %s", path.name)


def made() -> list[datetime]:
    """When each backup was made, by its name, the oldest first. Raises
    OSError, but for a folder that isn't there yet."""
    try:
        backups = listed(get_settings().backups_folder)
    except FileNotFoundError:
        return []
    tz = get_settings().tz
    return [
        datetime.strptime(match[1], STAMP).replace(tzinfo=tz)
        for path in backups
        if (match := NAME.match(path.name))
    ]


def current_since(times: list[datetime]) -> datetime | None:
    """When the backups were current last: when the newest was made, or a
    backup since found needless."""
    return max([*times[-1:], *([unchanged_at] if unchanged_at else [])], default=None)


def due(now: datetime) -> bool:
    """Whether a backup is due at a start: none from the last day."""
    since = current_since(made())
    return since is None or now - since >= timedelta(days=1)


def state(now: datetime) -> tuple[bool, str]:
    """For /status and the health check pings: whether the backups are as
    they should be, and how many there are, and how old. Not as they should
    be when the last failed, or the newest is STALE. Reads the folder."""
    if not get_settings().backups:
        return True, _("off")
    try:
        times = made()
    except OSError as e:
        return False, describe(e)
    if not times:
        detail = _("none yet")
    else:
        detail = ngettext(
            "{count}, {newest} old",
            "{count}, the newest {newest} old, the oldest {oldest} old",
            len(times),
        ).format(
            count=len(times),
            newest=format_duration(now - times[-1]),
            oldest=format_duration(now - times[0]),
        )
    if unchanged_at:
        detail += "; " + _("last skipped: no changes")
    if last_failure:
        failed = _("last failed: {error}").format(error=last_failure)
        return False, f"{failed}; {detail}"
    since = current_since(times)
    return since is None or now - since < STALE, detail


async def daily() -> None:
    """Back up, in a thread, so the bot answers meanwhile; or find that
    nothing has changed since the newest backup. Never raises."""
    global last_failure, unchanged_at
    now = datetime.now(get_settings().tz)
    try:
        backup = await asyncio.to_thread(back_up, now)
    except Exception as e:
        log_failure(logger, "The backup", e)
        last_failure = describe(e)
        return
    last_failure = None
    unchanged_at = None if backup else now


async def catch_up() -> None:
    """At a start: back up now, if no backup is from the last day, as when
    the bot was down at backups_at. Never raises."""
    global last_failure
    try:
        if not due(datetime.now(get_settings().tz)):
            return
    except Exception as e:
        log_failure(logger, "Looking for the latest backup", e)
        last_failure = describe(e)
        return
    await daily()


def start(bot: SignalBot) -> None:
    """Back up every day at backups_at, and now if one's due; not in debug
    mode, nor with backups = false."""
    settings = get_settings()
    if settings.debug or not settings.backups:
        logger.info("No backups")
        return
    at = settings.backups_at
    logger.info(
        "Backups every day at %s, the newest %d kept, in %s",
        f"{at:%H:%M}",
        settings.backups_kept,
        settings.backups_folder,
    )
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        daily,
        "cron",
        hour=at.hour,
        minute=at.minute,
        timezone=settings.tz,
        id="backups",
        # However late, rather than skipped when more than a second late
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        catch_up, id="backups-start", misfire_grace_time=None, replace_existing=True
    )
