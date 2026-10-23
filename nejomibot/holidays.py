"""The calendar's special days, which /today names: the holidays, flag
days and traditions of the countries in the setting holidays, by their ISO
codes, such as SE for Sweden and GR for Greece. Each comes after its
country's flag, in the bot's language; a day two keep, such as Christmas
Day, comes once, after both flags. Sweden's flag days say so.

Sweden's: its public holidays and their eves, its flag days (förordning
1982:270), the Sundays of Advent, and Shrove Tuesday, Valentine's Day,
Walpurgis Night, Mother's Day, Father's Day and Lucia. The day of the
election to the Riksdag, the second Sunday of September every fourth year,
is a flag day; so is that of the election to the European Parliament, but
its date is set anew each time, so it isn't here.

Greece's: its public holidays, by the Orthodox Easter, and Tsiknopempti,
Maundy Thursday, Holy Saturday, Valentine's Day, Mother's Day, Father's Day,
Christmas Eve and New Year's Eve.

The other countries': their public holidays, those the whole country keeps
(the United Kingdom's, England's and Wales's; Switzerland's, those most
cantons keep; Canada's, the federal ones), each on its own day, not on the
day off in lieu; Valentine's Day, Easter Sunday, Christmas Eve and New
Year's Eve; Mother's Day and Father's Day, where the whole country keeps
them on the same day; and some traditions of their own, such as Halloween,
Guy Fawkes Night, Sinterklaas, Midsummer and Advent. Romania's, Bulgaria's
and Cyprus's Easter is the Orthodox. Their names are in English, but those
they share with Sweden or Greece, which are translated.
"""

from calendar import FRIDAY, MONDAY, SATURDAY, SUNDAY, THURSDAY
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


def kings_day(year: int) -> date:
    """The Netherlands': 27 April, or the 26th when the 27th is a Sunday."""
    day = date(year, 4, 27)
    return day - timedelta(days=1) if day.weekday() == SUNDAY else day


def st_brigids_day(year: int) -> date:
    """Ireland's: the first Monday of February, or the 1st if a Friday."""
    day = date(year, 2, 1)
    return day if day.weekday() == FRIDAY else first(MONDAY, 2, 1)(year)


def french_mothers_day(year: int) -> date:
    """The last Sunday of May, or the first of June when that's Whit Sunday."""
    day = first(SUNDAY, 5, 25)(year)
    whit_sunday = easter(year) + timedelta(days=49)
    return day + timedelta(weeks=1) if day == whit_sunday else day


# New Zealand's Matariki, by the Māori lunar calendar, as the law sets it for
# each year (Te Kāhui o Matariki Public Holiday Act 2022, schedule 1)
MATARIKI = {
    2026: (7, 10), 2027: (6, 25), 2028: (7, 14), 2029: (7, 6), 2030: (6, 21),
    2031: (7, 11), 2032: (7, 2), 2033: (6, 24), 2034: (7, 7), 2035: (6, 29),
    2036: (7, 18), 2037: (7, 10), 2038: (6, 25), 2039: (7, 15), 2040: (7, 6),
    2041: (7, 19), 2042: (7, 11), 2043: (7, 3), 2044: (6, 24), 2045: (7, 7),
    2046: (6, 29), 2047: (7, 19), 2048: (7, 3), 2049: (6, 25), 2050: (7, 15),
    2051: (6, 30), 2052: (6, 21),
}  # fmt: skip


def matariki(year: int) -> date | None:
    return date(year, *MATARIKI[year]) if year in MATARIKI else None


def flag(country: str) -> str:
    """The country's flag, as its two regional indicator letters."""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country)


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
# Days many countries keep, by the names Sweden's and Greece's have, so that
# a day two countries keep comes once, and they're translated; the other
# countries' own names aren't
NEW_YEARS_DAY = Day("New Year's Day", on(1, 1))
EPIPHANY = Day("Epiphany", on(1, 6))
VALENTINES_DAY = Day("Valentine's Day", on(2, 14))
SHROVE_TUESDAY = Day("Shrove Tuesday", from_easter(-47))
MAUNDY_THURSDAY = Day("Maundy Thursday", from_easter(-3))
GOOD_FRIDAY = Day("Good Friday", from_easter(-2))
EASTER_SUNDAY = Day("Easter Sunday", from_easter(0))
EASTER_MONDAY = Day("Easter Monday", from_easter(1))
WALPURGIS_NIGHT = Day("Walpurgis Night", on(4, 30))
MAY_DAY = Day("May Day", on(5, 1))
ASCENSION_DAY = Day("Ascension Day", from_easter(39))
WHIT_SUNDAY = Day("Whit Sunday", from_easter(49))
WHIT_MONDAY = Day("Whit Monday", from_easter(50))
MIDSUMMER_EVE = Day("Midsummer Eve", on(6, 23))  # but in Sweden and Finland
MIDSUMMER_DAY = Day("Midsummer Day", on(6, 24))
ADVENT = (
    Day("First Sunday of Advent", advent(1)),
    Day("Second Sunday of Advent", advent(2)),
    Day("Third Sunday of Advent", advent(3)),
    Day("Fourth Sunday of Advent", advent(4)),
)
CHRISTMAS_EVE = Day("Christmas Eve", on(12, 24))
CHRISTMAS_DAY = Day("Christmas Day", on(12, 25))
BOXING_DAY = Day("Boxing Day", on(12, 26))  # and St Stephen's Day
NEW_YEARS_EVE = Day("New Year's Eve", on(12, 31))
ORTHODOX_GOOD_FRIDAY = Day("Good Friday", from_orthodox_easter(-2))
ORTHODOX_HOLY_SATURDAY = Day("Holy Saturday", from_orthodox_easter(-1))
ORTHODOX_EASTER_SUNDAY = Day("Easter Sunday", from_orthodox_easter(0))
ORTHODOX_EASTER_MONDAY = Day("Easter Monday", from_orthodox_easter(1))
DORMITION = Day("Dormition of the Virgin Mary", on(8, 15))
# And others', by names of their own
ST_PATRICKS_DAY = Day("St Patrick's Day", on(3, 17))
CORPUS_CHRISTI = Day("Corpus Christi", from_easter(60))
ASSUMPTION_DAY = Day("Assumption Day", on(8, 15))
HALLOWEEN = Day("Halloween", on(10, 31))
ALL_SAINTS_DAY = Day("All Saints' Day", on(11, 1))
ST_NICHOLAS_DAY = Day("St Nicholas' Day", on(12, 6))
IMMACULATE_CONCEPTION = Day("Immaculate Conception", on(12, 8))
VE_DAY = Day("Victory in Europe Day", on(5, 8))


def mothers_day(when: Rule) -> Day:
    return Day("Mother's Day", when)


def fathers_day(when: Rule) -> Day:
    return Day("Father's Day", when)


# The Nordic countries
NORWAY = (
    NEW_YEARS_DAY,
    mothers_day(first(SUNDAY, 2, 8)),  # the second of February
    VALENTINES_DAY,
    MAUNDY_THURSDAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    Day("Constitution Day", on(5, 17)),
    ASCENSION_DAY,
    WHIT_SUNDAY,
    WHIT_MONDAY,
    MIDSUMMER_EVE,
    fathers_day(first(SUNDAY, 11, 8)),  # the second of November
    *ADVENT,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
DENMARK = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    MAUNDY_THURSDAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    ASCENSION_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    WHIT_MONDAY,
    Day("Constitution Day", on(6, 5)),
    fathers_day(on(6, 5)),
    MIDSUMMER_EVE,
    *ADVENT,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
FINLAND = (
    NEW_YEARS_DAY,
    EPIPHANY,
    VALENTINES_DAY,
    SHROVE_TUESDAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    WALPURGIS_NIGHT,
    MAY_DAY,
    ASCENSION_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    Day("Midsummer Eve", first(FRIDAY, 6, 19)),  # as in Sweden
    Day("Midsummer Day", first(SATURDAY, 6, 20)),
    Day("All Saints' Day", first(SATURDAY, 10, 31)),
    fathers_day(first(SUNDAY, 11, 8)),  # the second of November
    *ADVENT,
    Day("Independence Day", on(12, 6)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
ICELAND = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    SHROVE_TUESDAY,
    MAUNDY_THURSDAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    Day("First Day of Summer", first(THURSDAY, 4, 19)),
    MAY_DAY,
    ASCENSION_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    WHIT_MONDAY,
    Day("National Day", on(6, 17)),
    Day("Commerce Day", first(MONDAY, 8, 1)),
    fathers_day(first(SUNDAY, 11, 8)),  # the second of November
    *ADVENT,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)

# North America, the British Isles, Australia and New Zealand
UNITED_STATES = (
    NEW_YEARS_DAY,
    Day("Martin Luther King Jr. Day", first(MONDAY, 1, 15)),  # the third
    VALENTINES_DAY,
    Day("Presidents' Day", first(MONDAY, 2, 15)),  # the third of February
    ST_PATRICKS_DAY,
    EASTER_SUNDAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    Day("Memorial Day", first(MONDAY, 5, 25)),  # the last of May
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Juneteenth", on(6, 19)),
    Day("Independence Day", on(7, 4)),
    Day("Labor Day", first(MONDAY, 9, 1)),
    Day("Columbus Day", first(MONDAY, 10, 8)),  # the second of October
    HALLOWEEN,
    Day("Veterans Day", on(11, 11)),
    Day("Thanksgiving", first(THURSDAY, 11, 22)),  # the fourth of November
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    NEW_YEARS_EVE,
)
CANADA = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    ST_PATRICKS_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    Day("Victoria Day", first(MONDAY, 5, 18)),  # the last before 25 May
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Canada Day", on(7, 1)),
    Day("Labour Day", first(MONDAY, 9, 1)),
    Day("National Day for Truth and Reconciliation", on(9, 30)),
    Day("Thanksgiving", first(MONDAY, 10, 8)),  # the second of October
    HALLOWEEN,
    Day("Remembrance Day", on(11, 11)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
UNITED_KINGDOM = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    Day("St David's Day", on(3, 1)),
    SHROVE_TUESDAY,
    ST_PATRICKS_DAY,
    mothers_day(from_easter(-21)),  # Mothering Sunday
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    Day("St George's Day", on(4, 23)),
    Day("Early May Bank Holiday", first(MONDAY, 5, 1)),
    Day("Spring Bank Holiday", first(MONDAY, 5, 25)),  # the last of May
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Summer Bank Holiday", first(MONDAY, 8, 25)),  # the last of August
    HALLOWEEN,
    Day("Guy Fawkes Night", on(11, 5)),
    Day("Remembrance Sunday", first(SUNDAY, 11, 8)),  # the second
    Day("St Andrew's Day", on(11, 30)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
IRELAND = (
    NEW_YEARS_DAY,
    Day("St Brigid's Day", st_brigids_day),
    VALENTINES_DAY,
    SHROVE_TUESDAY,
    ST_PATRICKS_DAY,
    mothers_day(from_easter(-21)),  # Mothering Sunday
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    Day("May Bank Holiday", first(MONDAY, 5, 1)),
    Day("June Bank Holiday", first(MONDAY, 6, 1)),
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("August Bank Holiday", first(MONDAY, 8, 1)),
    Day("October Bank Holiday", first(MONDAY, 10, 25)),  # the last
    HALLOWEEN,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
AUSTRALIA = (
    NEW_YEARS_DAY,
    Day("Australia Day", on(1, 26)),
    VALENTINES_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    Day("Anzac Day", on(4, 25)),
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    fathers_day(first(SUNDAY, 9, 1)),  # the first of September
    Day("Remembrance Day", on(11, 11)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
NEW_ZEALAND = (
    NEW_YEARS_DAY,
    Day("Day after New Year's Day", on(1, 2)),
    Day("Waitangi Day", on(2, 6)),
    VALENTINES_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    Day("Anzac Day", on(4, 25)),
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    Day("King's Birthday", first(MONDAY, 6, 1)),
    Day("Matariki", matariki),
    fathers_day(first(SUNDAY, 9, 1)),  # the first of September
    Day("Labour Day", first(MONDAY, 10, 22)),  # the fourth of October
    Day("Guy Fawkes Night", on(11, 5)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)

# The rest of the European Union, and Switzerland
GERMANY = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    ASCENSION_DAY,
    fathers_day(from_easter(39)),  # Ascension Day
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    WHIT_MONDAY,
    Day("German Unity Day", on(10, 3)),
    *ADVENT,
    ST_NICHOLAS_DAY,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
FRANCE = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    SHROVE_TUESDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    VE_DAY,
    ASCENSION_DAY,
    WHIT_SUNDAY,
    WHIT_MONDAY,
    mothers_day(french_mothers_day),
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Bastille Day", on(7, 14)),
    ASSUMPTION_DAY,
    ALL_SAINTS_DAY,
    Day("Armistice Day", on(11, 11)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    NEW_YEARS_EVE,
)
ITALY = (
    NEW_YEARS_DAY,
    EPIPHANY,
    VALENTINES_DAY,
    fathers_day(on(3, 19)),
    EASTER_SUNDAY,
    EASTER_MONDAY,
    Day("Liberation Day", on(4, 25)),
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    Day("Republic Day", on(6, 2)),
    ASSUMPTION_DAY,
    Day("St Francis of Assisi", on(10, 4)),
    ALL_SAINTS_DAY,
    Day("National Unity Day", first(SUNDAY, 11, 1)),
    IMMACULATE_CONCEPTION,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
SPAIN = (
    NEW_YEARS_DAY,
    EPIPHANY,
    VALENTINES_DAY,
    fathers_day(on(3, 19)),
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 1)),  # the first of May
    ASSUMPTION_DAY,
    Day("National Day of Spain", on(10, 12)),
    ALL_SAINTS_DAY,
    Day("Constitution Day", on(12, 6)),
    IMMACULATE_CONCEPTION,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    NEW_YEARS_EVE,
)
PORTUGAL = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    SHROVE_TUESDAY,
    fathers_day(on(3, 19)),
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    Day("Freedom Day", on(4, 25)),
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 1)),  # the first of May
    CORPUS_CHRISTI,
    Day("Portugal Day", on(6, 10)),
    ASSUMPTION_DAY,
    Day("Republic Day", on(10, 5)),
    ALL_SAINTS_DAY,
    Day("Restoration of Independence Day", on(12, 1)),
    IMMACULATE_CONCEPTION,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    NEW_YEARS_EVE,
)
POLAND = (
    NEW_YEARS_DAY,
    EPIPHANY,
    VALENTINES_DAY,
    Day("Fat Thursday", from_easter(-52)),
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    Day("Constitution Day", on(5, 3)),
    mothers_day(on(5, 26)),
    WHIT_SUNDAY,
    CORPUS_CHRISTI,
    fathers_day(on(6, 23)),
    ASSUMPTION_DAY,
    ALL_SAINTS_DAY,
    Day("Independence Day", on(11, 11)),
    ST_NICHOLAS_DAY,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
ROMANIA = (
    NEW_YEARS_DAY,
    Day("Day after New Year's Day", on(1, 2)),
    EPIPHANY,
    Day("St John the Baptist", on(1, 7)),
    Day("Union of the Principalities Day", on(1, 24)),
    VALENTINES_DAY,
    ORTHODOX_GOOD_FRIDAY,
    ORTHODOX_EASTER_SUNDAY,
    ORTHODOX_EASTER_MONDAY,
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 1)),  # the first of May
    fathers_day(first(SUNDAY, 5, 8)),  # the second of May
    Day("Children's Day", on(6, 1)),
    Day("Whit Sunday", from_orthodox_easter(49)),
    Day("Whit Monday", from_orthodox_easter(50)),
    DORMITION,
    Day("St Andrew's Day", on(11, 30)),
    Day("Great Union Day", on(12, 1)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
NETHERLANDS = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    Day("King's Day", kings_day),
    Day("Remembrance of the Dead", on(5, 4)),
    Day("Liberation Day", on(5, 5)),
    ASCENSION_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    WHIT_MONDAY,
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Sinterklaas", on(12, 5)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
BELGIUM = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    ASCENSION_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    WHIT_MONDAY,
    fathers_day(first(SUNDAY, 6, 8)),  # the second of June
    Day("National Day", on(7, 21)),
    ASSUMPTION_DAY,
    ALL_SAINTS_DAY,
    Day("Armistice Day", on(11, 11)),
    ST_NICHOLAS_DAY,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    NEW_YEARS_EVE,
)
CZECHIA = (
    NEW_YEARS_DAY,
    Day("Restoration Day of the Independent Czech State", on(1, 1)),
    VALENTINES_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    WALPURGIS_NIGHT,
    MAY_DAY,
    VE_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Saints Cyril and Methodius Day", on(7, 5)),
    Day("Jan Hus Day", on(7, 6)),
    Day("Statehood Day", on(9, 28)),
    Day("Independent Czechoslovak State Day", on(10, 28)),
    Day("Struggle for Freedom and Democracy Day", on(11, 17)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
HUNGARY = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    Day("1848 Revolution Day", on(3, 15)),
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 1)),  # the first of May
    WHIT_SUNDAY,
    WHIT_MONDAY,
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("State Foundation Day", on(8, 20)),
    Day("1956 Revolution Day", on(10, 23)),
    ALL_SAINTS_DAY,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
AUSTRIA = (
    NEW_YEARS_DAY,
    EPIPHANY,
    VALENTINES_DAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    ASCENSION_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    WHIT_MONDAY,
    CORPUS_CHRISTI,
    fathers_day(first(SUNDAY, 6, 8)),  # the second of June
    ASSUMPTION_DAY,
    Day("National Day", on(10, 26)),
    ALL_SAINTS_DAY,
    *ADVENT,
    ST_NICHOLAS_DAY,
    IMMACULATE_CONCEPTION,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
BULGARIA = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    Day("Liberation Day", on(3, 3)),
    ORTHODOX_GOOD_FRIDAY,
    ORTHODOX_HOLY_SATURDAY,
    ORTHODOX_EASTER_SUNDAY,
    ORTHODOX_EASTER_MONDAY,
    MAY_DAY,
    Day("St George's Day", on(5, 6)),
    Day("Bulgarian Culture Day", on(5, 24)),
    Day("Unification Day", on(9, 6)),
    Day("Independence Day", on(9, 22)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
SLOVAKIA = (
    NEW_YEARS_DAY,
    Day("Day of the Establishment of the Slovak Republic", on(1, 1)),
    EPIPHANY,
    VALENTINES_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    VE_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Saints Cyril and Methodius Day", on(7, 5)),
    Day("Slovak National Uprising Day", on(8, 29)),
    Day("Constitution Day", on(9, 1)),
    Day("Our Lady of Sorrows", on(9, 15)),
    ALL_SAINTS_DAY,
    Day("Struggle for Freedom and Democracy Day", on(11, 17)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
CROATIA = (
    NEW_YEARS_DAY,
    EPIPHANY,
    VALENTINES_DAY,
    fathers_day(on(3, 19)),
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    Day("Statehood Day", on(5, 30)),
    CORPUS_CHRISTI,
    Day("Anti-Fascist Struggle Day", on(6, 22)),
    Day("Victory and Homeland Thanksgiving Day", on(8, 5)),
    ASSUMPTION_DAY,
    ALL_SAINTS_DAY,
    Day("Vukovar Remembrance Day", on(11, 18)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
LITHUANIA = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    Day("Restoration of the State Day", on(2, 16)),
    Day("Restoration of Independence Day", on(3, 11)),
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 1)),  # the first of May
    fathers_day(first(SUNDAY, 6, 1)),  # the first of June
    MIDSUMMER_DAY,
    Day("Statehood Day", on(7, 6)),
    ASSUMPTION_DAY,
    ALL_SAINTS_DAY,
    Day("All Souls' Day", on(11, 2)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
LATVIA = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    Day("Restoration of Independence Day", on(5, 4)),
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    MIDSUMMER_EVE,
    MIDSUMMER_DAY,
    fathers_day(first(SUNDAY, 9, 8)),  # the second of September
    Day("Proclamation Day", on(11, 18)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
ESTONIA = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    Day("Independence Day", on(2, 24)),
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    WALPURGIS_NIGHT,
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    Day("Victory Day", on(6, 23)),
    MIDSUMMER_EVE,
    MIDSUMMER_DAY,
    Day("Restoration of Independence Day", on(8, 20)),
    fathers_day(first(SUNDAY, 11, 8)),  # the second of November
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
SLOVENIA = (
    NEW_YEARS_DAY,
    Day("Day after New Year's Day", on(1, 2)),
    Day("Prešeren Day", on(2, 8)),
    VALENTINES_DAY,
    mothers_day(on(3, 25)),
    EASTER_SUNDAY,
    EASTER_MONDAY,
    Day("Day of Uprising Against Occupation", on(4, 27)),
    MAY_DAY,
    Day("Day after May Day", on(5, 2)),
    WHIT_SUNDAY,
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Statehood Day", on(6, 25)),
    ASSUMPTION_DAY,
    Day("Reformation Day", on(10, 31)),
    ALL_SAINTS_DAY,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    Day("Independence and Unity Day", on(12, 26)),
    NEW_YEARS_EVE,
)
CYPRUS = (
    NEW_YEARS_DAY,
    EPIPHANY,
    VALENTINES_DAY,
    Day("Tsiknopempti", from_orthodox_easter(-59)),
    Day("Clean Monday", from_orthodox_easter(-48)),
    Day("Greek Independence Day", on(3, 25)),
    Day("Cyprus National Day", on(4, 1)),
    Day("Maundy Thursday", from_orthodox_easter(-3)),
    ORTHODOX_GOOD_FRIDAY,
    ORTHODOX_HOLY_SATURDAY,
    ORTHODOX_EASTER_SUNDAY,
    ORTHODOX_EASTER_MONDAY,
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    Day("Whit Monday", from_orthodox_easter(50)),
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    DORMITION,
    Day("Cyprus Independence Day", on(10, 1)),
    Day("Ochi Day", on(10, 28)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
LUXEMBOURG = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    MAY_DAY,
    Day("Europe Day", on(5, 9)),
    ASCENSION_DAY,
    WHIT_SUNDAY,
    WHIT_MONDAY,
    Day("National Day", on(6, 23)),
    ASSUMPTION_DAY,
    ALL_SAINTS_DAY,
    ST_NICHOLAS_DAY,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
MALTA = (
    NEW_YEARS_DAY,
    Day("St Paul's Shipwreck", on(2, 10)),
    VALENTINES_DAY,
    Day("St Joseph's Day", on(3, 19)),
    Day("Freedom Day", on(3, 31)),
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    MAY_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    Day("Sette Giugno", on(6, 7)),
    fathers_day(first(SUNDAY, 6, 15)),  # the third of June
    Day("Saints Peter and Paul", on(6, 29)),
    ASSUMPTION_DAY,
    Day("Victory Day", on(9, 8)),
    Day("Independence Day", on(9, 21)),
    IMMACULATE_CONCEPTION,
    Day("Republic Day", on(12, 13)),
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    NEW_YEARS_EVE,
)
SWITZERLAND = (
    NEW_YEARS_DAY,
    VALENTINES_DAY,
    GOOD_FRIDAY,
    EASTER_SUNDAY,
    EASTER_MONDAY,
    ASCENSION_DAY,
    mothers_day(first(SUNDAY, 5, 8)),  # the second of May
    WHIT_SUNDAY,
    WHIT_MONDAY,
    fathers_day(first(SUNDAY, 6, 1)),  # the first of June
    Day("Swiss National Day", on(8, 1)),
    Day("Federal Day of Prayer", first(SUNDAY, 9, 15)),  # the third
    *ADVENT,
    ST_NICHOLAS_DAY,
    CHRISTMAS_EVE,
    CHRISTMAS_DAY,
    BOXING_DAY,
    NEW_YEARS_EVE,
)
# By the codes the setting holidays takes, ISO 3166's
COUNTRIES = {
    country: (flag(country), days)
    for country, days in {
        "AT": AUSTRIA,
        "AU": AUSTRALIA,
        "BE": BELGIUM,
        "BG": BULGARIA,
        "CA": CANADA,
        "CH": SWITZERLAND,
        "CY": CYPRUS,
        "CZ": CZECHIA,
        "DE": GERMANY,
        "DK": DENMARK,
        "EE": ESTONIA,
        "ES": SPAIN,
        "FI": FINLAND,
        "FR": FRANCE,
        "GB": UNITED_KINGDOM,
        "GR": GREECE,
        "HR": CROATIA,
        "HU": HUNGARY,
        "IE": IRELAND,
        "IS": ICELAND,
        "IT": ITALY,
        "LT": LITHUANIA,
        "LU": LUXEMBOURG,
        "LV": LATVIA,
        "MT": MALTA,
        "NL": NETHERLANDS,
        "NO": NORWAY,
        "NZ": NEW_ZEALAND,
        "PL": POLAND,
        "PT": PORTUGAL,
        "RO": ROMANIA,
        "SE": SWEDEN,
        "SI": SLOVENIA,
        "SK": SLOVAKIA,
        "US": UNITED_STATES,
    }.items()
}


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
