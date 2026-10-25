"""/onthisday: a photo taken on this day in an earlier year, captioned as
/photo captions it, under "3 years ago today" in bold; without one, a photo
taken within three days of it, under "3 years ago, around this day".
/onthisday Alice picks from the album Alice alone. Like /photo, it doesn't
count toward the round of /uniquephoto.

When each photo was taken comes from its EXIF, as its caption has it, in the
bot's timezone, read for each photo in the background once the bot has
started (photos.index()), and again only for a photo added or changed since
(photos.moments()).
"""

import asyncio
import logging
from datetime import date, datetime
from pathlib import Path

from signalbot import DataMessageContext, SendMessage

from .commands import Command, Handler, answer, argument
from .config import get_settings
from .i18n import _, ngettext
from .messages import chance, error_text, log_failure
from .photos import (
    MAX_ATTEMPTS,
    album_alone,
    by_album,
    moments,
    no_album,
    pick,
    scan_photos,
)

logger = logging.getLogger(__name__)

AROUND = 3  # days either side of the day, when no photo was taken on it


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


def photo_on(
    today: date, album: str | None = None, library: list[Path] | None = None
) -> SendMessage | None:
    """A photo taken on this day in an earlier year, or else the nearest
    days around it, of the album's if one is named, from the library given
    or listed now, captioned; None if there's none. Blocking."""
    library = scan_photos() if library is None else library
    found = moments(library)
    if album is not None:
        found = {p: found[p] for p in by_album(library).get(album, []) if p in found}
    by_days: dict[int, list[tuple[Path, int]]] = {}
    for path, moment in found.items():
        if (near := nearest(moment.date(), today)) and near[0] <= AROUND:
            days, years = near
            by_days.setdefault(days, []).append((path, years))
    if not by_days:
        return None
    days = min(by_days)
    candidates = by_days[days]
    for path, years in chance().sample(candidates, min(MAX_ATTEMPTS, len(candidates))):
        if message := pick([path], heading(days, years)):
            return message
    return None


def on_this_day_for(text: str) -> SendMessage | str:
    """What /onthisday answers what follows it with. Blocking."""
    library = scan_photos()
    album = None
    if text and (album := album_alone(text, library)) is None:
        return no_album(text)
    today = datetime.now(get_settings().tz).date()
    return photo_on(today, album, library) or _(
        "No photos from this day, or the days around it, in earlier years."
    )


async def on_this_day(text: str = "") -> SendMessage | str:
    """The photo, or what to say instead."""
    try:
        return await asyncio.to_thread(on_this_day_for, text)
    except Exception as e:
        log_failure(logger, "A photo from this day", e)
        return error_text(e)


class OnThisDay(Handler):
    everyday = True
    commands = (Command("/onthisday", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        text = argument(context.message.text)
        await answer(context, lambda: on_this_day(text), slow=True)
