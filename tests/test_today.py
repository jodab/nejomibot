from datetime import date

import pytest
from helpers import ALICE, ALICE_ID, GROUP, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot.config import get_settings
from nejomibot.messages import collected, for_chat
from nejomibot.timers import check_commands
from nejomibot.today import Today, TodayPreview, day_message, preview, preview_day

ADMIN = "+46700000009"
NATIONAL_DAY = "🇸🇪 National Day of Sweden · flag day"


async def test_today_names_the_day(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_HOLIDAYS", '["SE"]')
    get_settings.cache_clear()
    get_settings().data_file("birthdays.txt").write_text(
        f"birthday | 1990-06-06 | {ALICE_ID} {ALICE} | Alice\n"
    )
    # In the group Alice is in, her birthday too; elsewhere, the day alone
    post = await day_message(bot, day=date(2026, 6, 6))
    assert post is not None
    assert for_chat(post, GROUP).text == f"{NATIONAL_DAY}\n🎂 Alice turns 36 today!"
    assert for_chat(post, ALICE).text == NATIONAL_DAY
    # Or that there's nothing special
    post = await day_message(bot, day=date(2026, 6, 8))
    assert post is not None
    assert post.text == "Nothing special today."


async def test_a_post_says_nothing_of_a_day_with_nothing(bot: SignalBot) -> None:
    get_settings().data_file("birthdays.txt").write_text(
        f"birthday | 1990-06-06 | {ALICE_ID} {ALICE} | Alice\n"
    )
    # As a timer, a special or /run runs it: a chat with nothing special
    # gets nothing, and with nothing anywhere, there's no message
    token = collected.set([])
    try:
        assert await day_message(bot, day=date(2026, 6, 8)) is None
        post = await day_message(bot, day=date(2026, 6, 6))
    finally:
        collected.reset(token)
    assert post is not None
    assert for_chat(post, GROUP).text == "🎂 Alice turns 36 today!"
    assert for_chat(post, ALICE).text == ""


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
        "👥 **Familjen**\nNothing special.\n\n👤 **In a direct chat**\nNothing special."
    )


@pytest.mark.usefixtures("swedish")
async def test_the_commands(bot: SignalBot, answers: list[SendMessage]) -> None:
    async def send(text: str) -> str:
        """What the bot answers an admin's direct message, as text."""
        answers.clear()
        context = DataMessageContext(bot, message_from(ADMIN, text))
        for handler in (Today(), TodayPreview()):
            await handler.handle_data_message(context)
        [answer] = answers
        return answer.text or ""

    # By their Swedish names, as an admin sends them; /day is /today too
    assert await send("/idag") == "Inget särskilt idag."
    assert await send("/dagen") == "Inget särskilt idag."
    assert await send("/day") == "Inget särskilt idag."
    assert (await send("/idag förhandsvisa imorgon")).startswith("**👁️ /idag på ")
    # The English word too
    assert (await send("/idag preview")).startswith("**👁️ /idag på ")
    assert await send("/idag förhandsvisa snart") == (
        "Vilken dag? Som 10-25, 2026-10-25 eller imorgon; ingen för idag."
    )
    # Timers run them all, the preview for the admins to have it posted
    # somewhere
    assert check_commands(["/idag", "/dagen", "/idag förhandsvisa"]) is None
