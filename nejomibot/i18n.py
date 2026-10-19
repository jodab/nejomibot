"""Translations. The bot's messages are written in English, and the setting
language picks a translation from nejomibot/locale:

- <language>.po, in gettext's format, translates the messages. The image has
  it compiled instead, as <language>.mo, when it's built, which the bot
  reads; from a checkout, where there's none, it reads the .po with polib,
  which only development has.
- <language>.toml, if there is one, has the language's names for commands,
  as aliases do in the config, and its words for those the bot reads in
  commands, such as days for timers.

Mark text with _() where it's used, ngettext() when it depends on a number,
and N_() in a table made ahead of use, then _() it when used. Put values in
with str.format, after translating: _("Weather in {city}").format(city=...).
tools/translations.sh brings the .po files up to date with the code.
"""

import gettext
import io
import tomllib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from .config import get_settings

LOCALE_DIR = Path(__file__).parent / "locale"
SOURCE_LANGUAGE = "en"  # the language the messages are written in


class Names(BaseModel):
    """A language's .toml: for each English command or word, the language's."""

    model_config = ConfigDict(extra="forbid")

    commands: dict[str, list[str]] = {}
    words: dict[str, list[str]] = {}


def languages() -> list[str]:
    """English, and those translated: by their .po, or in the image, .mo."""
    translated = {path.stem for path in LOCALE_DIR.glob("*.[mp]o")}
    return [SOURCE_LANGUAGE, *sorted(translated)]


@dataclass(frozen=True)
class Language:
    translations: gettext.NullTranslations
    commands: dict[str, list[str]]
    words: dict[str, list[str]]


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
def load(language: str) -> Language:
    """The language's translations, read from its files once. Raises
    OSError or ValueError if they can't be read."""
    if language == SOURCE_LANGUAGE:
        return Language(gettext.NullTranslations(), {}, {})
    translations = catalog(language)
    try:
        with (LOCALE_DIR / f"{language}.toml").open("rb") as f:
            names = Names.model_validate(tomllib.load(f))
    except FileNotFoundError:
        names = Names()
    return Language(translations, names.commands, names.words)


def language() -> Language:
    return load(get_settings().language)


def _(message: str) -> str:
    return language().translations.gettext(message)


def ngettext(singular: str, plural: str, n: int) -> str:
    return language().translations.ngettext(singular, plural, n)


def N_(message: str) -> str:
    """Mark text for translation where it's defined; _() translates it."""
    return message


def language_words(word: str) -> list[str]:
    """A word the bot reads in commands, and the language's words for it:
    e.g. 'mon', 'mån'."""
    return [word, *language().words.get(word, [])]


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
