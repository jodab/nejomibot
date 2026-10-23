"""/albums lists the photo library's albums, for everyone allowed: each folder
right in photos_dir, by name, with how many photos it has, the years they
were taken in, and the birth date its captions count an age from; then how
many photos are in no album. /album, for the admins, shows one, and sets
that birth date:

  /album Alice                the album
  /album Alice 2019-06-15     its captions show the age of who was born then
  /album Alice -              none of its own: photos_birth_date, if set

An album is named as /photo names it, in any case. The birth dates are kept
in data_dir/albums.txt, a line each (photos.birth_dates), which can be
changed by hand.
"""

import asyncio
from datetime import date, datetime
from pathlib import Path

from signalbot import DataMessageContext

from .commands import Command, Edits, Handler, answer, argument, undo_with
from .config import get_settings
from .i18n import _, ngettext
from .messages import escape
from .photos import (
    REMOVE,
    BirthDate,
    album_named,
    birth_date,
    birth_dates,
    by_album,
    moments,
    no_album,
    own_birth_dates,
    scan_photos,
)
from .timers import DATE


def years_of(photos: list[Path], found: dict[Path, datetime]) -> str:
    """The years the photos were taken in, as 2019–2026, if known."""
    years = sorted({found[path].year for path in photos if path in found})
    if not years:
        return ""
    return f"{years[0]}" if years[0] == years[-1] else f"{years[0]}–{years[-1]}"


def size_text(photos: list[Path], found: dict[Path, datetime]) -> str:
    """E.g. '1234 photos · 2019–2026'."""
    count = len(photos)
    text = ngettext("{count} photo", "{count} photos", count).format(count=count)
    return f"{text} · {years}" if (years := years_of(photos, found)) else text


def album_line(name: str, photos: list[Path], found: dict[Path, datetime]) -> str:
    """E.g. '1234 photos · 2019–2026 · 🎂 2019-06-15'."""
    text = size_text(photos, found)
    if born := birth_date(name):
        text += f" · {get_settings().photos_age_emoji} {born:%Y-%m-%d}"
    return text


def albums_text() -> str:
    """Every album, a line each, then the photos in none. Styled. Blocking."""
    library = scan_photos()
    groups = by_album(library)
    albums = {name: photos for name, photos in groups.items() if name is not None}
    if albums:
        title = ngettext("📚 {count} album", "📚 {count} albums", len(albums))
        lines = [f"**{escape(title.format(count=len(albums)))}**"]
        found = moments(library)
        lines += [
            f"**{escape(name)}** · {escape(album_line(name, albums[name], found))}"
            for name in sorted(albums, key=str.casefold)
        ]
    else:
        lines = [escape(_("📚 No albums: each folder in the photo library is one."))]
    if loose := len(groups.get(None, [])):
        lines.append(
            escape(
                ngettext(
                    "📷 {count} photo in no album",
                    "📷 {count} photos in no album",
                    loose,
                ).format(count=loose)
            )
        )
    return "\n".join(lines)


def album_usage() -> str:
    return _(
        "/album <album>: the album. /album <album> 2019-06-15: the birth date "
        "its captions count an age from; /album <album> -: none of its own. "
        "/albums lists the albums."
    )


def born_text(name: str) -> str:
    """The birth date the album's captions count an age from, and whose."""
    if own := own_birth_dates(name):
        return _("Born {day}").format(day=f"{own[-1].day:%Y-%m-%d}")
    if born := get_settings().photos_birth_date:
        return _("Born {day}, as photos_birth_date has it").format(
            day=f"{born:%Y-%m-%d}"
        )
    return _("No birth date, so its captions show no age")


def shown(name: str, photos: list[Path], found: dict[Path, datetime]) -> str:
    """The album, in a few lines. Styled."""
    emoji = get_settings().photos_age_emoji
    lines = [size_text(photos, found), f"{emoji} {born_text(name)}"]
    return f"📖 **{escape(name)}**\n{escape(chr(10).join(lines))}"


def set_birth_date(name: str, day: date) -> str:
    """Make it the album's birth date, for an edit to undo. Raises OSError."""
    change = birth_dates.change(own_birth_dates(name), [BirthDate(name, day)])
    undo_with(lambda: birth_dates.revert(change))
    return _("✅ {album}: born {day}, so its captions show the age.").format(
        album=name, day=f"{day:%Y-%m-%d}"
    )


def remove_birth_date(name: str) -> str:
    """Take the album's own birth date away, for an edit to undo. Raises
    OSError."""
    if not (own := own_birth_dates(name)):
        return _("{album} has no birth date of its own.").format(album=name)
    change = birth_dates.remove(own)
    undo_with(lambda: birth_dates.revert(change))
    if born := get_settings().photos_birth_date:
        return _(
            "✅ {album}: no birth date of its own, so photos_birth_date's, {day}, "
            "counts."
        ).format(album=name, day=f"{born:%Y-%m-%d}")
    return _("✅ {album}: no birth date, so its captions show no age.").format(
        album=name
    )


def album_answer(text: str) -> str:
    """What /album answers what follows it with. Styled. Blocking."""
    if not text:
        return escape(album_usage())
    library = scan_photos()
    groups = by_album(library)
    if (found := album_named(text, groups)) is None:
        # By its name alone, without the date or - after it
        return escape(no_album(text.rsplit(maxsplit=1)[0] if changes(text) else text))
    name, rest = found
    if not rest:
        return shown(name, groups[name], moments(library))
    if rest == REMOVE:
        return escape(remove_birth_date(name))
    try:
        day = date.fromisoformat(rest) if DATE.match(rest) else None
    except ValueError:
        day = None
    if day is None:
        return escape(_("{text} isn't a date, as 2019-06-15.").format(text=rest))
    return escape(set_birth_date(name, day))


def changes(text: str) -> bool:
    """Whether /album's text sets or removes a birth date: one an edit
    takes the place of."""
    words = text.split()
    return len(words) > 1 and (words[-1] == REMOVE or bool(DATE.match(words[-1])))


class Albums(Handler):
    commands = (Command("/albums"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(
            context, lambda: asyncio.to_thread(albums_text), slow=True, styled=True
        )


# For the admins: it changes what captions say
class Album(Handler):
    commands = (Command("/album", more=True, timers=False),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        text = argument(context.message.text)
        await answer(
            context,
            lambda: asyncio.to_thread(album_answer, text),
            edits=Edits.REPLACE if changes(text) else Edits.RUN_AGAIN,
            slow=True,
            styled=True,
        )
