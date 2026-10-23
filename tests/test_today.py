from datetime import date

import pytest
from helpers import ALICE, ALICE_ID, GROUP, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import today
from nejomibot.config import get_settings
from nejomibot.messages import for_chat
from nejomibot.timers import check_commands
from nejomibot.today import (
    Today,
    TodayPreview,
    day_message,
    preview,
    preview_day,
    today_message,
)

ADMIN = "+46700000009"
NATIONAL_DAY = "🇸🇪 National Day of Sweden · flag day"


@pytest.fixture
def weather(monkeypatch: pytest.MonkeyPatch) -> None:
    """The weather, without asking OpenWeatherMap."""

    async def weather_message() -> str:
        return "**Weather**"

    monkeypatch.setattr(today, "weather_message", weather_message)


@pytest.mark.usefixtures("weather")
async def test_today_names_the_day(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_HOLIDAYS", '["SE"]')
    get_settings.cache_clear()
    get_settings().data_file("birthdays.txt").write_text(
        f"birthday | 1990-06-06 | {ALICE_ID} {ALICE} | Alice\n"
    )
    post = await today_message(bot, date(2026, 6, 6))
    # In the group Alice is in, her birthday too; elsewhere, the day alone
    in_group = f"{NATIONAL_DAY}\n🎂 Alice turns 36 today!\n\n**Weather**"
    assert for_chat(post, GROUP).text == in_group
    assert for_chat(post, ALICE).text == f"{NATIONAL_DAY}\n\n**Weather**"
    # A day without any is the weather alone
    assert (await today_message(bot, date(2026, 6, 8))).text == "**Weather**"
    # Without the weather, the day alone, or that there's nothing special
    post = await day_message(bot, day=date(2026, 6, 6))
    assert for_chat(post, GROUP).text == f"{NATIONAL_DAY}\n🎂 Alice turns 36 today!"
    assert for_chat(post, ALICE).text == NATIONAL_DAY
    post = await day_message(bot, day=date(2026, 6, 8))
    assert post.text == "Nothing special today."


@pytest.mark.parametrize(
    ("words", "day"),
    [
        ([], date(2026, 10, 19)),
        (["tomorrow"], date(2026, 10, 20)),
        (["10-25"], date(2026, 10, 25)),
        (["10-18"], date(2027, 10, 18)),  # the next one
        (["2026-12-24"], date(2026, 12, 24)),
        (["02-29"], date(2028, 2, 29)),
        (["soon"], None),
        (["10-25", "x"], None),
        (["10-32"], None),
    ],
)
def test_the_day_previewed(words: list[str], day: date | None) -> None:
    assert preview_day(words, date(2026, 10, 19)) == day


async def test_the_preview(bot: SignalBot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_HOLIDAYS", '["SE"]')
    get_settings.cache_clear()
    get_settings().data_file("birthdays.txt").write_text(
        f"birthday | 1990-06-06 | {ALICE_ID} {ALICE} | Alice\n"
        "nameday | 06-06 | * | Grandma\n"
    )
    # In each group the bot is in, and in a direct chat, which has no
    # birthdays
    text = await preview(bot, ["06-06"], date(2026, 10, 19))
    assert text == "\n".join(
        [
            "**👁️ /today on Sunday 6 June**",
            "",
            "👥 **Familjen**",
            NATIONAL_DAY,
            "🎂 Alice turns 37 today!",
            "🌸 Happy name day, Grandma!",
            "",
            "👤 **In a direct chat**",
            NATIONAL_DAY,
        ]
    )
    assert (await preview(bot, [], date(2026, 10, 19))).endswith(
        "👥 **Familjen**\nNothing atop the weather.\n\n"
        "👤 **In a direct chat**\nNothing atop the weather."
    )


@pytest.mark.usefixtures("swedish", "weather")
async def test_the_commands(bot: SignalBot, answers: list[SendMessage]) -> None:
    async def send(text: str) -> str:
        """What the bot answers an admin's direct message, as text."""
        answers.clear()
        context = DataMessageContext(bot, message_from(ADMIN, text))
        for handler in (Today(), TodayPreview()):
            await handler.handle_data_message(context)
        [answer] = answers
        return answer.text or ""

    # By their Swedish names, as an admin sends them
    assert await send("/idag") == "**Weather**"
    assert await send("/dagen") == "Inget särskilt idag."
    assert (await send("/idag förhandsvisa imorgon")).startswith("**👁️ /idag på ")
    # The English word too
    assert (await send("/idag preview")).startswith("**👁️ /idag på ")
    assert await send("/idag förhandsvisa snart") == (
        "Vilken dag? Som 10-25, 2026-10-25 eller imorgon; ingen för idag."
    )
    # Timers run them all, the preview for the admins to have it posted
    # somewhere
    assert check_commands(["/idag", "/dagen", "/idag förhandsvisa"]) is None
