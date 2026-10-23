"""Translations. The bot's messages are written in English, and the setting
language picks a translation from nejomibot/locale:

- <language>.po, in gettext's format, translates the messages. The image has
  it compiled instead, as <language>.mo, when it's built, which the bot
  reads; from a checkout, where there's none, it reads the .po with polib,
  which only development has.
- <language>.toml, if there is one, has the language's own name, its names
  for commands, as aliases do in the config, and its words for those the bot
  reads in commands: days for timers, and subcommands, such as lägg till for
  add. The bot takes every language's, from anyone.

Each chat may have a language of its own, which /language sets (languages.py)
and data_dir/languages.txt keeps: the bot speaks it while it answers there,
or posts there (speaking()); else the setting's.

Mark text with _() where it's used, ngettext() when it depends on a number,
and N_() in a table made ahead of use, then _() it when used. Put values in
with str.format, after translating: _("Weather in {city}").format(city=...).
tools/translations.sh brings the .po files up to date with the code.
"""

import gettext
import io
import tomllib
from collections.abc import Generator, Iterable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import get_settings
from .files import KeptLines

LOCALE_DIR = Path(__file__).parent / "locale"
SOURCE_LANGUAGE = "en"  # the language the messages are written in
SOURCE_NAME = "English"  # its own name


class Names(BaseModel):
    """A language's .toml: its own name, and for each English command or
    word, the language's."""

    model_config = ConfigDict(extra="forbid")

    name: str = ""
    commands: dict[str, list[str]] = {}
    words: dict[str, list[str]] = {}


@cache
def languages() -> list[str]:
    """English, and those translated: by their .po, or in the image, .mo.
    Read once, as the image's don't change."""
    translated = {path.stem for path in LOCALE_DIR.glob("*.[mp]o")}
    return [SOURCE_LANGUAGE, *sorted(translated)]


@dataclass(frozen=True)
class Language:
    translations: gettext.NullTranslations
    commands: dict[str, list[str]]
    words: dict[str, list[str]]
    name: str  # its own, as Svenska


def catalog(language: str) -> gettext.GNUTranslations:
    """The language's messages: its .mo, compiled as the image is built, or
    else its .po, compiled now."""
    try:
        with (LOCALE_DIR / f"{language}.mo").open("rb") as f:
            return gettext.GNUTranslations(f)
    except FileNotFoundError:
        import polib  # only development has it, and needs it

        po = polib.pofile(str(LOCALE_DIR / f"{language}.po"))
        return gettext.GNUTranslations(io.BytesIO(po.to_binary()))


@cache
def names_of(language: str) -> Names:
    """The language's own name, and its names for commands and words, from
    its .toml, read once: all the bot needs of a language it doesn't speak,
    whose catalog it doesn't load. Raises OSError or ValueError if it can't
    be read."""
    if language == SOURCE_LANGUAGE:
        return Names(name=SOURCE_NAME)
    try:
        with (LOCALE_DIR / f"{language}.toml").open("rb") as f:
            names = Names.model_validate(tomllib.load(f))
    except FileNotFoundError:
        names = Names()
    return names if names.name else names.model_copy(update={"name": language})


@cache
def load(language: str) -> Language:
    """The language's translations, read from its files once, when the bot
    first speaks it. Raises OSError or ValueError if they can't be read."""
    names = names_of(language)
    if language == SOURCE_LANGUAGE:
        translations = gettext.NullTranslations()
    else:
        translations = catalog(language)
    return Language(translations, names.commands, names.words, names.name)


# The language the bot speaks now, while it answers in a chat or posts to
# one: the chat's own, if it has one; None for the setting's
speaking_now: ContextVar[str | None] = ContextVar("speaking_now", default=None)


@contextmanager
def speaking(code: str) -> Generator[None]:
    """Speak the language, by its code, meanwhile."""
    token = speaking_now.set(code)
    try:
        yield
    finally:
        speaking_now.reset(token)


def spoken() -> str:
    """The code of the language the bot speaks now."""
    return speaking_now.get() or get_settings().language


def language() -> Language:
    return load(spoken())


def every_language() -> list[Names]:
    """The names of each language the bot has, which it takes from anyone,
    for commands and words."""
    return [names_of(code) for code in languages()]


def every_word(word: str) -> list[str]:
    """A word the bot reads in commands, and every language's words for it:
    e.g. 'mon', 'mån'."""
    return [
        word,
        *(each for lang in every_language() for each in lang.words.get(word, [])),
    ]


def _(message: str) -> str:
    return language().translations.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return language().translations.ngettext(singular, plural, n)


def N_(message: str) -> str:
    """Mark text for translation where it's defined; _() translates it."""
    return message


def shown_word(word: str) -> str:
    """A word the bot reads in commands as the language spoken shows it:
    its first word for it, if any, e.g. 'vardagar' for 'weekdays'."""
    return next(iter(language().words.get(word, [])), word)


# Each chat's own language


@dataclass(frozen=True)
class ChatLanguage:
    """The language a chat has of its own, by its code."""

    chat: str  # a group's ID, or a person's phone number or Signal ID
    code: str


CHAT_LANGUAGES_HEADER = (
    "# nejomibot's languages of chats, one per line:",
    "#   chat | language",
    "# The chat is a group's ID, or a person's phone number or Signal ID, as",
    "# /chats lists them; the language is en or one in nejomibot/locale, by",
    "# its code. A chat not here gets the language in the config.",
    "# Changed with /language in Signal, or by hand: the bot reads it again",
    "# when it changes, and leaves comments and lines it can't read as they",
    "# are.",
)


def parse_chat_language(line: str) -> ChatLanguage:
    """A line of the file. Raises ValueError."""
    chat, bar, code = (part.strip() for part in line.rpartition("|"))
    if not bar or not chat or code not in languages():
        raise ValueError(f"no chat, or no language the bot has: {code}")
    return ChatLanguage(chat, code)


def chat_language_line(entry: ChatLanguage) -> str:
    return f"{entry.chat} | {entry.code}"


chat_languages = KeptLines(
    "languages.txt", CHAT_LANGUAGES_HEADER, parse_chat_language, chat_language_line
)


def own_language(*ids: str | None) -> str | None:
    """The code of the language of its own that the chat known by any of
    these IDs has, if it has one: the last line's."""
    wanted = {each for each in ids if each}
    entries = chat_languages.current().entries
    return next((e.code for e in reversed(entries) if e.chat in wanted), None)


def chat_language(*ids: str | None) -> str:
    """The code of the language the bot speaks in the chat known by any of
    these IDs: its own, or else the setting's."""
    return own_language(*ids) or get_settings().language


def by_language(chats: Iterable[str]) -> dict[str, list[str]]:
    """The chats, by the language the bot speaks in each, in their order."""
    found: dict[str, list[str]] = {}
    for chat in chats:
        found.setdefault(chat_language(chat), []).append(chat)
    return found


def weekday_name(day: date) -> str:
    return (
        _("Monday"),
        _("Tuesday"),
        _("Wednesday"),
        _("Thursday"),
        _("Friday"),
        _("Saturday"),
        _("Sunday"),
    )[day.weekday()]


def month_name(day: date) -> str:
    return (
        _("January"),
        _("February"),
        _("March"),
        _("April"),
        _("May"),
        _("June"),
        _("July"),
        _("August"),
        _("September"),
        _("October"),
        _("November"),
        _("December"),
    )[day.month - 1]


def weekday_and_day(day: date) -> str:
    """E.g. 'Sunday 25 October'."""
    return _("{weekday} {day} {month}").format(
        weekday=weekday_name(day), day=day.day, month=month_name(day)
    )


def day_and_time(moment: datetime) -> str:
    """E.g. 'Sunday 11 October 15:30'."""
    return _("{weekday} {day} {month} {time}").format(
        weekday=weekday_name(moment),
        day=moment.day,
        month=month_name(moment),
        time=f"{moment:%H:%M}",
    )


def when_text(at: datetime, now: datetime) -> str:
    """When, in the bot's time zone, as short as now allows: '08:14',
    'yesterday 08:14', or '2026-10-16 08:14'."""
    tz = get_settings().tz
    local, today = at.astimezone(tz), now.astimezone(tz).date()
    time = f"{local:%H:%M}"
    if local.date() == today:
        return time
    if local.date() == today - timedelta(days=1):
        return _("yesterday {time}").format(time=time)
    return f"{local:%Y-%m-%d} {time}"


def format_duration(duration: timedelta) -> str:
    """E.g. '3 d 4 h', '4 h 12 min', '12 min' or '45 s'."""
    seconds = int(duration.total_seconds())
    if seconds < 60:
        return _("{seconds} s").format(seconds=seconds)
    hours, minutes = divmod(seconds // 60, 60)
    days, hours = divmod(hours, 24)
    if days:
        return _("{days} d {hours} h").format(days=days, hours=hours)
    if hours:
        return _("{hours} h {minutes} min").format(hours=hours, minutes=minutes)
    return _("{minutes} min").format(minutes=minutes)


def format_file_size(size: float) -> str:
    """E.g. '1.5MB'."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"
