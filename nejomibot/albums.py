"""/albums lists the photo library's albums, for everyone allowed: each folder
right in photos_dir, by name, with how many photos it has, the years they
were taken in, the birth date its captions count an age from, and its
shortcuts; then how many photos are in no album. /album, for the admins,
shows one, and sets those:

  /album Alice                          the album
  /album Alice 2019-06-15               its captions show the age of who was
                                        born then
  /album Alice -                        none of its own: photos_birth_date,
                                        if set
  /album Alice shortcuts /alice /al     other names for /photo Alice, so
                                        /alice 2024 is /photo Alice 2024
  /album Alice shortcuts -              none

An album is named as /photo names it, in any case. A shortcut starts with a
/ or a ., as a plain word would make every message that starts with it a
command, so alice is taken as /alice; and it can't be a name the bot answers
to already. What albums have of their own is kept in
data_dir/albums.txt, a line each (photos.album_settings), which can be
changed by hand.
"""

import asyncio
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path

from signalbot import DataMessageContext

from .commands import (
    Command,
    Edits,
    Handler,
    answer,
    argument,
    shortcut_clash,
    undo_with,
)
from .config import as_command, get_settings
from .i18n import _, every_word, ngettext, prefixed
from .messages import escape
from .photos import (
    REMOVE,
    AlbumSettings,
    album_lines,
    album_named,
    album_settings,
    birth_date,
    by_album,
    moments,
    no_album,
    own_settings,
    scan_photos,
)
from .timers import DATE

SHORTCUTS = "shortcuts"  # after /album <album>: other names for /photo with it
MAX_SHORTCUTS = 5  # an album's


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
    """E.g. '1234 photos · 2019–2026 · 🎂 2019-06-15 · 🏷️ /alice /al'."""
    text = size_text(photos, found)
    if born := birth_date(name):
        text += f" · {get_settings().photos_age_emoji} {born:%Y-%m-%d}"
    if shortcuts := own_settings(name).shortcuts:
        text += f" · 🏷️ {' '.join(map(prefixed, shortcuts))}"
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
        "/album <album> shortcuts /alice: other names for /photo "
        "<album>; /album <album> shortcuts -: none. /albums lists the albums."
    )


def born_text(name: str) -> str:
    """The birth date the album's captions count an age from, and whose."""
    if own := own_settings(name).born:
        return _("Born {day}").format(day=f"{own:%Y-%m-%d}")
    if born := get_settings().photos_birth_date:
        return _("Born {day}, as photos_birth_date has it").format(
            day=f"{born:%Y-%m-%d}"
        )
    return _("No birth date, so its captions show no age")


def shortcuts_text(name: str) -> str:
    if shortcuts := own_settings(name).shortcuts:
        shown = ", ".join(map(prefixed, shortcuts))
        return _("Shortcuts: {shortcuts}").format(shortcuts=shown)
    return _("No shortcuts")


def shown(name: str, photos: list[Path], found: dict[Path, datetime]) -> str:
    """The album, in a few lines. Styled."""
    emoji = get_settings().photos_age_emoji
    lines = [
        size_text(photos, found),
        f"{emoji} {born_text(name)}",
        f"🏷️ {shortcuts_text(name)}",
    ]
    return f"📖 **{escape(name)}**\n{escape(chr(10).join(lines))}"


def keep(entry: AlbumSettings) -> None:
    """Make it what the album has of its own, in place of its lines: no line
    if it has nothing. For an edit to undo. Raises OSError."""
    added = [entry] if entry.born or entry.shortcuts else []
    change = album_settings.change(album_lines(entry.album), added)
    undo_with(lambda: album_settings.revert(change))


def set_birth_date(name: str, day: date) -> str:
    """Make it the album's birth date, for an edit to undo. Raises OSError."""
    keep(replace(own_settings(name), album=name, born=day))
    return _("✅ {album}: born {day}, so its captions show the age.").format(
        album=name, day=f"{day:%Y-%m-%d}"
    )


def remove_birth_date(name: str) -> str:
    """Take the album's own birth date away, for an edit to undo. Raises
    OSError."""
    if not (own := own_settings(name)).born:
        return _("{album} has no birth date of its own.").format(album=name)
    keep(replace(own, album=name, born=None))
    if born := get_settings().photos_birth_date:
        return _(
            "✅ {album}: no birth date of its own, so photos_birth_date's, {day}, "
            "counts."
        ).format(album=name, day=f"{born:%Y-%m-%d}")
    return _("✅ {album}: no birth date, so its captions show no age.").format(
        album=name
    )


def shortcut_problem(shortcut: str, name: str) -> str | None:
    """Why the album can't have the shortcut, if it can't: a name the bot
    answers to already would hide one of the two. Another album's is named
    by the album."""
    folded = shortcut.casefold()
    for entry in album_settings.current().entries:
        if entry.album.casefold() != name.casefold() and folded in (
            each.casefold() for each in entry.shortcuts
        ):
            return _("{name} is a shortcut for {album} already.").format(
                name=prefixed(shortcut), album=entry.album
            )
    return shortcut_clash(shortcut, f"/photo {name}")


def set_shortcuts(name: str, words: list[str]) -> str:
    """Make the words the album's shortcuts, or with -, take them away; for
    an edit to undo. Raises OSError."""
    own = own_settings(name)
    if not words:
        return album_usage()
    if words == [REMOVE]:
        if not own.shortcuts:
            return _("{album} has no shortcuts.").format(album=name)
        keep(replace(own, album=name, shortcuts=()))
        return _("✅ {album}: no shortcuts.").format(album=name)
    shortcuts = tuple(dict.fromkeys(map(as_command, words)))
    if len(shortcuts) > MAX_SHORTCUTS:
        return _("An album has at most {count} shortcuts.").format(count=MAX_SHORTCUTS)
    for shortcut in shortcuts:
        if why := shortcut_problem(shortcut, name):
            return why
    keep(replace(own, album=name, shortcuts=shortcuts))
    return _("✅ Shortcuts for /photo {album}: {shortcuts}.").format(
        album=name, shortcuts=", ".join(map(prefixed, shortcuts))
    )


def is_shortcuts(word: str) -> bool:
    return word.casefold() in (each.casefold() for each in every_word(SHORTCUTS))


def name_in(text: str) -> str:
    """The album's name in /album's text: what comes before the shortcuts,
    or before a date or - at its end."""
    words = text.split()
    for at, word in enumerate(words[1:], start=1):
        if is_shortcuts(word):
            return " ".join(words[:at])
    if len(words) > 1 and (words[-1] == REMOVE or DATE.match(words[-1])):
        return " ".join(words[:-1])
    return text


def changes(text: str) -> bool:
    """Whether /album's text sets or removes something, which an edit takes
    the place of."""
    return name_in(text) != text


def album_answer(text: str) -> str:
    """What /album answers what follows it with. Styled. Blocking."""
    if not text:
        return escape(album_usage())
    library = scan_photos()
    groups = by_album(library)
    if (found := album_named(text, groups)) is None:
        return escape(no_album(name_in(text)))
    name, rest = found
    words = rest.split()
    if not words:
        return shown(name, groups[name], moments(library))
    if is_shortcuts(words[0]):
        return escape(set_shortcuts(name, words[1:]))
    if rest == REMOVE:
        return escape(remove_birth_date(name))
    try:
        day = date.fromisoformat(rest) if DATE.match(rest) else None
    except ValueError:
        day = None
    if day is None:
        return escape(_("{text} isn't a date, as 2019-06-15.").format(text=rest))
    return escape(set_birth_date(name, day))


class Albums(Handler):
    commands = (Command("/albums"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(
            context, lambda: asyncio.to_thread(albums_text), slow=True, styled=True
        )


# For the admins: it changes what captions say, and what names the bot takes
class Album(Handler):
    commands = (Command("/album", more=True, timers=False, subcommands=(SHORTCUTS,)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        text = argument(context.message.text)
        await answer(
            context,
            lambda: asyncio.to_thread(album_answer, text),
            edits=Edits.REPLACE if changes(text) else Edits.RUN_AGAIN,
            slow=True,
            styled=True,
        )
