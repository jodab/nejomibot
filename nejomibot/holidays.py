"""The calendar's special days, which the daily post names atop the weather:
the holidays, flag days and traditions of the countries in the setting
holidays, SE for Sweden and GR for Greece. Each comes after its country's
flag, in the bot's language; a day both keep, such as Christmas Day, comes
once, after both flags. Sweden's flag days say so.

Sweden's: its public holidays and their eves, its flag days (förordning
1982:270), the Sundays of Advent, and Shrove Tuesday, Valentine's Day,
Walpurgis Night, Mother's Day, Father's Day and Lucia. The day of the
election to the Riksdag, the second Sunday of September every fourth year,
is a flag day; so is that of the election to the European Parliament, but
its date is set anew each time, so it isn't here.

Greece's: its public holidays, by the Orthodox Easter, and Tsiknopempti,
Maundy Thursday, Holy Saturday, Valentine's Day, Mother's Day, Father's Day,
Christmas Eve and New Year's Eve.
"""

from calendar import FRIDAY, SATURDAY, SUNDAY
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from dateutil.easter import EASTER_ORTHODOX, EASTER_WESTERN, easter

from .i18n import N_, _

type Yearly = Callable[[int], date]  # the day in a year
type Rule = Callable[[int], date | None]  # the day in a year, if it has one


def on(month: int, day: int) -> Yearly:
    """The same day every year."""
    return lambda year: date(year, month, day)


def first(weekday: int, month: int, day: int) -> Yearly:
    """The first such weekday from the month's day: Midsummer Day is the first
    Saturday from 20 June."""

    def rule(year: int) -> date:
        start = date(year, month, day)
        return start + timedelta(days=(weekday - start.weekday()) % 7)

    return rule


def from_easter(days: int, method: Literal[1, 2, 3] = EASTER_WESTERN) -> Yearly:
    """So many days from Easter Sunday, the Western one or the Orthodox."""
    return lambda year: easter(year, method) + timedelta(days=days)


def advent(sunday: int) -> Yearly:
    """The Sundays of Advent, the first from 27 November."""
    first_sunday = first(SUNDAY, 11, 27)
    return lambda year: first_sunday(year) + timedelta(weeks=sunday - 1)


def riksdag_election(year: int) -> date | None:
    """The second Sunday of September, every fourth year, as in 2026."""
    return first(SUNDAY, 9, 8)(year) if year % 4 == 2 else None


def from_orthodox_easter(days: int) -> Yearly:
    return from_easter(days, EASTER_ORTHODOX)


@dataclass(frozen=True)
class Day:
    name: str  # in English, translated when shown
    when: Rule
    flag_day: bool = False


SWEDEN = (
    Day(N_("New Year's Day"), on(1, 1), flag_day=True),
    Day(N_("Epiphany"), on(1, 6)),
    Day(N_("The King's name day"), on(1, 28), flag_day=True),
    Day(N_("Valentine's Day"), on(2, 14)),
    Day(N_("Shrove Tuesday"), from_easter(-47)),
    Day(N_("The Crown Princess's name day"), on(3, 12), flag_day=True),
    Day(N_("Maundy Thursday"), from_easter(-3)),
    Day(N_("Good Friday"), from_easter(-2)),
    Day(N_("Holy Saturday"), from_easter(-1)),
    Day(N_("Easter Sunday"), from_easter(0), flag_day=True),
    Day(N_("Easter Monday"), from_easter(1)),
    Day(N_("The King's birthday"), on(4, 30), flag_day=True),
    Day(N_("Walpurgis Night"), on(4, 30)),
    Day(N_("May Day"), on(5, 1), flag_day=True),
    Day(N_("Ascension Day"), from_easter(39)),
    Day(N_("Mother's Day"), first(SUNDAY, 5, 25)),  # the last of May
    Day(N_("Veterans' Day"), on(5, 29), flag_day=True),
    Day(N_("Whit Sunday"), from_easter(49), flag_day=True),
    Day(N_("National Day of Sweden"), on(6, 6), flag_day=True),
    Day(N_("Midsummer Eve"), first(FRIDAY, 6, 19)),
    Day(N_("Midsummer Day"), first(SATURDAY, 6, 20), flag_day=True),
    Day(N_("The Crown Princess's birthday"), on(7, 14), flag_day=True),
    Day(N_("The Queen's name day"), on(8, 8), flag_day=True),
    Day(N_("Election day"), riksdag_election, flag_day=True),
    Day(N_("United Nations Day"), on(10, 24), flag_day=True),
    Day(N_("All Saints' Day"), first(SATURDAY, 10, 31)),
    Day(N_("Gustavus Adolphus Day"), on(11, 6), flag_day=True),
    Day(N_("Father's Day"), first(SUNDAY, 11, 8)),  # the second of November
    Day(N_("First Sunday of Advent"), advent(1)),
    Day(N_("Second Sunday of Advent"), advent(2)),
    Day(N_("Third Sunday of Advent"), advent(3)),
    Day(N_("Fourth Sunday of Advent"), advent(4)),
    Day(N_("Nobel Day"), on(12, 10), flag_day=True),
    Day(N_("St Lucy's Day"), on(12, 13)),
    Day(N_("The Queen's birthday"), on(12, 23), flag_day=True),
    Day(N_("Christmas Eve"), on(12, 24)),
    Day(N_("Christmas Day"), on(12, 25), flag_day=True),
    Day(N_("Boxing Day"), on(12, 26)),
    Day(N_("New Year's Eve"), on(12, 31)),
)
GREECE = (
    Day(N_("New Year's Day"), on(1, 1)),
    Day(N_("Epiphany"), on(1, 6)),
    Day(N_("Valentine's Day"), on(2, 14)),
    Day(N_("Tsiknopempti"), from_orthodox_easter(-59)),
    Day(N_("Clean Monday"), from_orthodox_easter(-48)),
    Day(N_("Greek Independence Day"), on(3, 25)),
    Day(N_("Maundy Thursday"), from_orthodox_easter(-3)),
    Day(N_("Good Friday"), from_orthodox_easter(-2)),
    Day(N_("Holy Saturday"), from_orthodox_easter(-1)),
    Day(N_("Easter Sunday"), from_orthodox_easter(0)),
    Day(N_("Easter Monday"), from_orthodox_easter(1)),
    Day(N_("May Day"), on(5, 1)),
    Day(N_("Mother's Day"), first(SUNDAY, 5, 8)),  # the second of May
    Day(N_("Whit Monday"), from_orthodox_easter(50)),
    Day(N_("Father's Day"), first(SUNDAY, 6, 15)),  # the third of June
    Day(N_("Dormition of the Virgin Mary"), on(8, 15)),
    Day(N_("Ochi Day"), on(10, 28)),
    Day(N_("Christmas Eve"), on(12, 24)),
    Day(N_("Christmas Day"), on(12, 25)),
    Day(N_("Boxing Day"), on(12, 26)),
    Day(N_("New Year's Eve"), on(12, 31)),
)
# By the codes the setting holidays takes
COUNTRIES = {"SE": ("🇸🇪", SWEDEN), "GR": ("🇬🇷", GREECE)}


def days_on(day: date, countries: Sequence[str]) -> list[str]:
    """The day's special days in the countries, a line each, in the bot's
    language, after the flags of the countries that keep them; first those
    of the first country, in the calendar's order."""
    found: dict[str, tuple[str, bool]] = {}  # their flags, and if a flag day
    for country in countries:
        flag, days = COUNTRIES[country]
        for each in days:
            if each.when(day.year) == day:
                flags, flag_day = found.get(each.name, ("", False))
                found[each.name] = (flags + flag, flag_day or each.flag_day)
    return [
        f"{flags} {_(name)}" + (f" · {_('flag day')}" if flag_day else "")
        for name, (flags, flag_day) in found.items()
    ]
