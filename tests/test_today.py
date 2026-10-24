from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from helpers import ALICE, ALICE_ID, GROUP, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import today
from nejomibot.config import get_settings
from nejomibot.messages import for_chat
from nejomibot.timers import check_commands
from nejomibot.today import Today, TodayPreview, day_message, preview, preview_day

ADMIN = "+46700000009"
NATIONAL_DAY = "🇸🇪 National Day of Sweden · flag day"
TZ = ZoneInfo("Europe/Stockholm")
SATURDAY = datetime(2026, 6, 6, 8, 0, tzinfo=TZ)  # National Day of Sweden
MONDAY = datetime(2026, 6, 8, 8, 0, tzinfo=TZ)  # nothing special


async def test_today_names_the_day(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_HOLIDAYS", '["SE"]')
    get_settings.cache_clear()
    get_settings().data_file("birthdays.txt").write_text(
        f"birthday | 1990-06-06 | {ALICE_ID} {ALICE} | Alice\n"
    )
    # The date and the time in bold; then, in the group Alice is in, her
    # birthday too; elsewhere, the day alone
    post = await day_message(bot, SATURDAY)
    heading = "📅 **Saturday 6 June** · 08:00"
    assert for_chat(post, GROUP).text == (
        f"{heading}\n{NATIONAL_DAY}\n🎂 Alice turns 36 today!"
    )
    assert for_chat(post, ALICE).text == f"{heading}\n{NATIONAL_DAY}"


async def test_a_day_with_nothing_special_is_the_date_alone(bot: SignalBot) -> None:
    get_settings().data_file("birthdays.txt").write_text(
        f"birthday | 1990-06-06 | {ALICE_ID} {ALICE} | Alice\n"
    )
    post = await day_message(bot, MONDAY)
    assert for_chat(post, GROUP).text == "📅 **Monday 8 June** · 08:00"
    assert for_chat(post, ALICE).text == "📅 **Monday 8 June** · 08:00"


async def test_every_chat_hears_it(
    bot: SignalBot, answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_HOLIDAYS", '["SE"]')
    get_settings.cache_clear()
    for at in (SATURDAY, MONDAY):
        monkeypatch.setattr(today, "now", lambda at=at: at)
        for in_group in (True, False):
            message = message_from(ADMIN, "/today", in_group=in_group)
            await Today().handle_data_message(DataMessageContext(bot, message))
    saturday = f"📅 **Saturday 6 June** · 08:00\n{NATIONAL_DAY}"
    monday = "📅 **Monday 8 June** · 08:00"
    assert [answer.text for answer in answers] == [saturday, saturday, monday, monday]


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
async def test_the_commands(
    bot: SignalBot, answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def send(text: str) -> str:
        """What the bot answers an admin's direct message, as text."""
        answers.clear()
        context = DataMessageContext(bot, message_from(ADMIN, text))
        for handler in (Today(), TodayPreview()):
            await handler.handle_data_message(context)
        [answer] = answers
        return answer.text or ""

    monkeypatch.setattr(today, "now", lambda: MONDAY)
    # By their Swedish names, as an admin sends them; /day is /today too, in
    # Swedish with the month capitalized, as always
    assert await send("/idag") == "📅 **Måndag 8 Juni** · 08:00"
    assert await send("/dagen") == "📅 **Måndag 8 Juni** · 08:00"
    assert await send("/day") == "📅 **Måndag 8 Juni** · 08:00"
    assert (await send("/idag förhandsvisa imorgon")).startswith("**👁️ /idag på ")
    # The English word too
    assert (await send("/idag preview")).startswith("**👁️ /idag på ")
    assert await send("/idag förhandsvisa snart") == (
        "Vilken dag? Som 10-25, 2026-10-25 eller imorgon; ingen för idag."
    )
    # Timers run them all, the preview for the admins to have it posted
    # somewhere
    assert check_commands(["/idag", "/dagen", "/idag förhandsvisa"]) is None
