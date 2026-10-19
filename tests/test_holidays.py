from datetime import date, timedelta
from typing import get_args

import pytest
from pydantic import ValidationError

from nejomibot.config import Settings, get_settings
from nejomibot.holidays import COUNTRIES, days_on

BOTH = ["SE", "GR"]


@pytest.mark.parametrize(
    ("day", "lines"),
    [
        (date(2026, 1, 1), ["🇸🇪🇬🇷 New Year's Day · flag day"]),
        (date(2026, 2, 12), ["🇬🇷 Tsiknopempti"]),
        (date(2026, 2, 17), ["🇸🇪 Shrove Tuesday"]),
        (date(2026, 2, 23), ["🇬🇷 Clean Monday"]),
        (date(2026, 3, 25), ["🇬🇷 Greek Independence Day"]),
        # The Western Easter, then the Orthodox, a week apart in 2026
        (date(2026, 4, 3), ["🇸🇪 Good Friday"]),
        (date(2026, 4, 5), ["🇸🇪 Easter Sunday · flag day"]),
        (date(2026, 4, 12), ["🇬🇷 Easter Sunday"]),
        (date(2026, 4, 13), ["🇬🇷 Easter Monday"]),
        (
            date(2026, 4, 30),
            ["🇸🇪 The King's birthday · flag day", "🇸🇪 Walpurgis Night"],
        ),
        (date(2026, 5, 1), ["🇸🇪🇬🇷 May Day · flag day"]),
        (date(2026, 5, 10), ["🇬🇷 Mother's Day"]),
        (date(2026, 5, 14), ["🇸🇪 Ascension Day"]),
        (date(2026, 5, 24), ["🇸🇪 Whit Sunday · flag day"]),
        (date(2026, 5, 29), ["🇸🇪 Veterans' Day · flag day"]),
        (date(2026, 5, 31), ["🇸🇪 Mother's Day"]),
        (date(2026, 6, 1), ["🇬🇷 Whit Monday"]),
        (date(2026, 6, 6), ["🇸🇪 National Day of Sweden · flag day"]),
        (date(2026, 6, 19), ["🇸🇪 Midsummer Eve"]),
        (date(2026, 6, 20), ["🇸🇪 Midsummer Day · flag day"]),
        (date(2026, 6, 21), ["🇬🇷 Father's Day"]),
        (date(2026, 8, 15), ["🇬🇷 Dormition of the Virgin Mary"]),
        (date(2026, 9, 13), ["🇸🇪 Election day · flag day"]),
        (date(2026, 10, 28), ["🇬🇷 Ochi Day"]),
        (date(2026, 10, 31), ["🇸🇪 All Saints' Day"]),
        (date(2026, 11, 8), ["🇸🇪 Father's Day"]),
        (date(2026, 11, 29), ["🇸🇪 First Sunday of Advent"]),
        (date(2026, 12, 13), ["🇸🇪 Third Sunday of Advent", "🇸🇪 St Lucy's Day"]),
        (date(2026, 12, 20), ["🇸🇪 Fourth Sunday of Advent"]),
        (date(2026, 12, 24), ["🇸🇪🇬🇷 Christmas Eve"]),
        (date(2026, 12, 25), ["🇸🇪🇬🇷 Christmas Day · flag day"]),
        (date(2026, 12, 26), ["🇸🇪🇬🇷 Boxing Day"]),
        # A day like any other
        (date(2026, 10, 19), []),
    ],
)
def test_days_on(day: date, lines: list[str]) -> None:
    assert days_on(day, BOTH) == lines


def test_both_easters_on_one_day() -> None:
    # As in 2025: once, after both flags
    assert days_on(date(2025, 4, 18), BOTH) == ["🇸🇪🇬🇷 Good Friday"]
    assert days_on(date(2025, 4, 20), BOTH) == ["🇸🇪🇬🇷 Easter Sunday · flag day"]


def test_the_riksdag_election_every_fourth_year() -> None:
    assert days_on(date(2030, 9, 8), ["SE"]) == ["🇸🇪 Election day · flag day"]
    # The second Sunday of September in 2027 is a Sunday like any other
    assert days_on(date(2027, 9, 12), ["SE"]) == []


def test_only_the_countries_set() -> None:
    assert days_on(date(2026, 12, 25), ["GR"]) == ["🇬🇷 Christmas Day"]
    assert days_on(date(2026, 12, 25), ["GR", "SE"]) == [
        "🇬🇷🇸🇪 Christmas Day · flag day"
    ]
    assert days_on(date(2026, 12, 25), []) == []


def test_a_day_a_year() -> None:
    # No day falls twice in a year, nor is missed: each comes once
    for _flag, days in COUNTRIES.values():
        for each in days:
            found = [
                day
                for n in range(365)
                if each.when((day := date(2026, 1, 1) + timedelta(days=n)).year) == day
            ]
            assert len(found) == 1, each.name


@pytest.mark.usefixtures("swedish")
def test_in_swedish() -> None:
    assert days_on(date(2026, 6, 6), BOTH) == ["🇸🇪 Sveriges nationaldag · flaggdag"]
    assert days_on(date(2026, 4, 30), ["SE"]) == [
        "🇸🇪 Konungens födelsedag · flaggdag",
        "🇸🇪 Valborgsmässoafton",
    ]
    assert days_on(date(2026, 2, 23), BOTH) == ["🇬🇷 Ren måndag"]


def test_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    assert get_settings().holidays == []
    monkeypatch.setenv("NEJOMIBOT_HOLIDAYS", '["SE", "GR"]')
    get_settings.cache_clear()
    assert get_settings().holidays == BOTH
    monkeypatch.setenv("NEJOMIBOT_HOLIDAYS", '["FI"]')
    get_settings.cache_clear()
    with pytest.raises(ValidationError, match="holidays"):
        get_settings()
    # It takes the countries the calendar has
    annotation = Settings.model_fields["holidays"].annotation
    assert set(get_args(get_args(annotation)[0])) == set(COUNTRIES)
