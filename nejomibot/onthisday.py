"""/onthisday: a photo taken on this day in an earlier year, captioned as
/photo captions it, under "3 years ago today" in bold; without one, a photo
taken within three days of it, under "3 years ago, around this day". Like
/photo, it doesn't count toward the daily post's round.

When each photo was taken comes from its EXIF, as its caption has it, in the
bot's timezone. The bot reads it once for each photo, only the file's header,
and keeps it while it runs, about 300 bytes a photo, so the first
/onthisday after a start takes longer: 0.2 s for 1150 photos on a desktop
whose disk cache has them. A photo that changes is read again.
"""

import asyncio
import logging
import random
import threading
from datetime import date, datetime
from pathlib import Path

from signalbot import DataMessageContext, SendMessage

from .commands import Command, Handler, answer
from .config import get_settings
from .i18n import _, ngettext
from .messages import error_text, log_failure
from .photos import MAX_ATTEMPTS, exif_datetime, exif_of, open_image, pick, scan_photos

logger = logging.getLogger(__name__)

AROUND = 3  # days either side of the day, when no photo was taken on it

# When each photo was taken, by its path, with its mtime and size when read
taken: dict[str, tuple[int, int, date | None]] = {}
reading = threading.Lock()  # one look through the library at a time


def day_taken(path: Path) -> date | None:
    """The day the photo was taken, as its caption has it; None if that's
    not known, or it's no image Pillow can read. Only its header is read."""
    try:
        with open_image(path) as img:
            exif = exif_of(img)
    except Exception as e:
        logger.warning("Could not read when %s was taken: %s", path, e)
        return None
    moment = exif_datetime(exif)
    return moment.date() if moment else None


def days_taken() -> dict[Path, date]:
    """When each photo in the library was taken, if known. Photos read
    before and unchanged since aren't read again. Blocking."""
    found: dict[Path, date] = {}
    with reading:
        seen: dict[str, tuple[int, int, date | None]] = {}
        for path in scan_photos():
            try:
                stat = path.stat()
            except OSError:
                continue
            known = taken.get(name := str(path))
            if known and known[:2] == (stat.st_mtime_ns, stat.st_size):
                day = known[2]
            else:
                day = day_taken(path)
            seen[name] = (stat.st_mtime_ns, stat.st_size, day)
            if day:
                found[path] = day
        taken.clear()
        taken.update(seen)
    return found


def in_year(day: date, year: int) -> date:
    """The same day in another year: 29 February on the 28th but in leap
    years."""
    try:
        return day.replace(year=year)
    except ValueError:
        return date(year, 2, 28)


def nearest(day: date, today: date) -> tuple[int, int] | None:
    """How many days from today the day is, in the year it's nearest of
    those at least a year after it, and how many years after it that is;
    None for a day in the future."""
    found = [
        (abs((in_year(day, year) - today).days), year - day.year)
        for year in (today.year - 1, today.year, today.year + 1)
        if year - day.year >= 1
    ]
    return min(found, default=None)


def heading(days: int, years: int) -> str:
    if days == 0:
        text = ngettext("{count} year ago today", "{count} years ago today", years)
    else:
        text = ngettext(
            "{count} year ago, around this day",
            "{count} years ago, around this day",
            years,
        )
    return text.format(count=years)


def photo_on(today: date) -> SendMessage | None:
    """A photo taken on this day in an earlier year, or else the nearest
    days around it, captioned; None if there's none. Blocking."""
    by_days: dict[int, list[tuple[Path, int]]] = {}
    for path, day in days_taken().items():
        if (found := nearest(day, today)) and found[0] <= AROUND:
            days, years = found
            by_days.setdefault(days, []).append((path, years))
    if not by_days:
        return None
    days = min(by_days)
    candidates = by_days[days]
    for path, years in random.sample(candidates, min(MAX_ATTEMPTS, len(candidates))):
        if message := pick([path], heading(days, years)):
            return message
    return None


async def on_this_day() -> SendMessage | str:
    """The photo, or what to say instead."""
    today = datetime.now(get_settings().tz).date()
    try:
        message = await asyncio.to_thread(photo_on, today)
    except Exception as e:
        log_failure(logger, "A photo from this day", e)
        return error_text(e)
    return message or _(
        "No photos from this day, or the days around it, in earlier years."
    )


class OnThisDay(Handler):
    commands = (Command("/onthisday"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, on_this_day, slow=True)
