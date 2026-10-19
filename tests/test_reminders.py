import logging
from datetime import datetime, timedelta
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from helpers import ALICE, BOB, EDIT_FROM_BEFORE, GROUP, NOW_MS, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import commands, reminders
from nejomibot.config import get_settings
from nejomibot.reminders import (
    Remind,
    Reminder,
    due_from,
    parse_line,
    post_due,
    serve,
)

TZ = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 10, 19, 16, 0, tzinfo=TZ)  # a Monday
FRIENDS = "group.RnJpZW5kcw=="  # a group the bot isn't in


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> list[datetime]:
    """Now, for the reminders: NOW, till the test moves it."""
    now = [NOW]
    monkeypatch.setattr(reminders, "now", lambda: now[0])
    return now


@pytest.mark.parametrize(
    ("words", "due", "used"),
    [
        ("18:00 Cake", at("2026-10-19 18:00"), 1),
        ("18.30 Cake", at("2026-10-19 18:30"), 1),
        # Past today: tomorrow
        ("15:00 Cake", at("2026-10-20 15:00"), 1),
        ("30m Cake", NOW + timedelta(minutes=30), 1),
        ("in 2h Cake", NOW + timedelta(hours=2), 2),
        ("1h30m Cake", NOW + timedelta(hours=1, minutes=30), 1),
        ("tomorrow 08:00 Cake", at("2026-10-20 08:00"), 2),
        ("fri 17:00 Cake", at("2026-10-23 17:00"), 2),
        # Monday's 15:00 is past: the next Monday's
        ("mon 15:00 Cake", at("2026-10-26 15:00"), 2),
        ("weekends 10:00 Cake", at("2026-10-24 10:00"), 2),
        ("2026-12-24 15:00 Cake", at("2026-12-24 15:00"), 2),
        # Past: add_reminder says so
        ("today 15:00 Cake", at("2026-10-19 15:00"), 2),
        # The time ends <when>, though what follows names a day
        ("18:00 tomorrow is the party", at("2026-10-19 18:00"), 1),
    ],
)
def test_due_from(words: str, due: datetime, used: int) -> None:
    assert due_from(words.split(), NOW) == (due, used)


@pytest.mark.parametrize(
    "words",
    ["Cake at 18:00", "in Cake", "in", "every 2h Cake", "0m Cake", "tomorow 08:00 x"],
)
def test_no_due(words: str) -> None:
    assert due_from(words.split(), NOW) is None


def test_how_soon_across_a_change_of_time() -> None:
    # Summer time ends at 03:00 on 25 October 2026: two hours from 01:30 is
    # 02:30 the second time
    now = at("2026-10-25 01:30")
    due, _used = due_from(["2h", "Tea"], now) or (now, 0)
    assert due - now == timedelta(hours=1)  # on the clock
    assert (due.astimezone(ZoneInfo("UTC")) - now.astimezone(ZoneInfo("UTC"))) == (
        timedelta(hours=2)
    )
    assert due.fold == 1


@pytest.mark.usefixtures("swedish")
def test_due_in_swedish() -> None:
    assert due_from(["om", "30m", "Tårtan"], NOW) == (NOW + timedelta(minutes=30), 2)
    assert due_from(["imorgon", "08:00", "Bob"], NOW) == (at("2026-10-20 08:00"), 2)
    assert due_from(["fre", "17:00", "Pizza"], NOW) == (at("2026-10-23 17:00"), 2)


async def ask(
    bot: SignalBot,
    answers: list[SendMessage],
    text: str,
    sender: str = ALICE,
    *,
    in_group: bool = False,
    edit: bool = False,
) -> str:
    answers.clear()
    message = message_from(sender, text, in_group=in_group, edit=edit)
    await Remind().handle_data_message(DataMessageContext(bot, message))
    return "\n".join(answer.text or "" for answer in answers)


def the_file() -> list[str]:
    path = get_settings().data_file("reminders.txt")
    return [line for line in path.read_text().splitlines() if not line.startswith("#")]


async def test_add_list_and_remove(bot: SignalBot, answers: list[SendMessage]) -> None:
    assert await ask(bot, answers, "/remind 18:00 Take the cake out") == (
        "✅ **Added**\n#1 · Monday 19 October 18:00 · Take the cake out"
    )
    assert await ask(bot, answers, "/remind  tomorrow 08:00  Pick up\nBob") == (
        "✅ **Added**\n#2 · Tuesday 20 October 08:00 · Pick up Bob"
    )
    assert the_file() == [
        f"1 | 2026-10-19 18:00:00+02:00 | {ALICE} | Take the cake out",
        f"2 | 2026-10-20 08:00:00+02:00 | {ALICE} | Pick up Bob",
    ]
    assert await ask(bot, answers, "/remind") == "\n".join(
        [
            "**🔔 2 reminders here**",
            "#1 · Monday 19 October 18:00 · Take the cake out",
            "#2 · Tuesday 20 October 08:00 · Pick up Bob",
        ]
    )
    assert await ask(bot, answers, "/remind remove 1") == (
        "🗑️ **Removed**\n#1 · Monday 19 October 18:00 · Take the cake out"
    )
    # The next is numbered past those there
    await ask(bot, answers, "/remind 30m Tea")
    assert [line.split(" | ")[0] for line in the_file()] == ["2", "3"]


async def test_each_chat_its_own(bot: SignalBot, answers: list[SendMessage]) -> None:
    await ask(bot, answers, "/remind 18:00 Dinner", ALICE, in_group=True)
    await ask(bot, answers, "/remind 18:00 Mine", ALICE)
    # Anyone in the group sees the group's, and may remove them
    assert await ask(bot, answers, "/remind", BOB, in_group=True) == (
        "**🔔 1 reminder here**\n#1 · Monday 19 October 18:00 · Dinner"
    )
    assert await ask(bot, answers, "/remind remove 2", BOB, in_group=True) == (
        "No reminder #2 here."
    )
    assert the_file() == [
        f"1 | 2026-10-19 18:00:00+02:00 | {GROUP} | Dinner",
        f"1 | 2026-10-19 18:00:00+02:00 | {ALICE} | Mine",
    ]
    assert (await ask(bot, answers, "/remind", BOB)).startswith("No reminders here.")


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("/remind Take the cake out", "When?\n\n/remind <when> <text>: a reminder"),
        ("/remind 18:00", "What should the reminder say?"),
        ("/remind today 15:00 Cake", "today 15:00 has already been."),
        ("/remind 2027-12-24 15:00 Cake", "A reminder can be at most a year ahead."),
        (f"/remind 18:00 {'x' * 501}", "A reminder has at most 500 characters."),
        ("/remind remove", "Which reminder? Give its number, as /remind shows."),
        ("/remind remove 3", "No reminder #3 here."),
    ],
)
async def test_refused(
    bot: SignalBot, answers: list[SendMessage], text: str, answer: str
) -> None:
    assert (await ask(bot, answers, text)).startswith(answer)
    assert not get_settings().data_file("reminders.txt").exists()


async def test_so_many_a_chat(
    bot: SignalBot, answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reminders, "MAX_PER_CHAT", 1)
    await ask(bot, answers, "/remind 18:00 One")
    assert await ask(bot, answers, "/remind 19:00 Two") == (
        "There are 1 reminders here already: remove one first."
    )
    assert (await ask(bot, answers, "/remind 19:00 Two", BOB)).startswith("✅")


async def test_an_edit_takes_the_place_of_what_it_edits(
    bot: SignalBot, answers: list[SendMessage]
) -> None:
    await ask(bot, answers, "/remind 18:00 Take the cake out")
    assert await ask(bot, answers, "/remind 19:00 Take the cake out", edit=True) == (
        "✅ **Added**\n#1 · Monday 19 October 19:00 · Take the cake out"
    )
    assert the_file() == [
        f"1 | 2026-10-19 19:00:00+02:00 | {ALICE} | Take the cake out"
    ]
    # Showing them runs again
    assert (await ask(bot, answers, "/remind", edit=True)).startswith("**🔔 1 reminder")


async def test_an_edit_of_a_message_from_before_a_start(
    bot: SignalBot, answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    # The bot can't tell what the message did, as it has started again since
    monkeypatch.setattr(commands, "STARTED", NOW_MS / 1000 + 60)
    assert await ask(bot, answers, "/remind 18:00 Cake", edit=True) == (
        EDIT_FROM_BEFORE
    )
    assert not get_settings().data_file("reminders.txt").exists()


async def test_posted_when_due(
    bot: SignalBot,
    clock: list[datetime],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.INFO, logger="nejomibot")
    sent: list[tuple[str, str]] = []

    async def send(bot: SignalBot, chat: str, message: SendMessage) -> None:
        sent.append((chat, message.text or ""))

    monkeypatch.setattr(reminders, "send", send)
    get_settings().data_file("reminders.txt").write_text(
        f"1 | 2026-10-19 16:00:00+02:00 | {ALICE} | Now\n"
        f"1 | 2026-10-19 15:30:00+02:00 | {GROUP} | Late\n"
        f"2 | 2026-10-17 15:00:00+02:00 | {GROUP} | Too late\n"
        f"1 | 2026-10-19 15:00:00+02:00 | {FRIENDS} | Not in it\n"
        f"2 | 2026-10-19 16:01:00+02:00 | {ALICE} | Soon\n"
    )
    await post_due(bot)
    assert sent == [
        (GROUP, "⏰ Late\n\n⏳ Late: it should have been sent at 15:30"),
        (ALICE, "⏰ Now"),
    ]
    assert "Dropped a reminder to a group, due 2 d 1 h ago" in caplog.text
    assert "Dropped a reminder to a group the bot isn't in" in caplog.text
    # What they say isn't logged
    assert "Late" not in caplog.text.replace("Late:", "")
    # Posted once
    assert the_file() == [f"2 | 2026-10-19 16:01:00+02:00 | {ALICE} | Soon"]
    sent.clear()
    await post_due(bot)
    assert sent == []
    clock[0] += timedelta(minutes=1)
    await post_due(bot)
    assert sent == [(ALICE, "⏰ Soon")]


def test_lines() -> None:
    assert parse_line(f"3 | 2026-10-19 18:00 | {GROUP} | A | B") == Reminder(
        3, at("2026-10-19 18:00"), GROUP, "A | B"
    )
    for line in [
        f"x | 2026-10-19 18:00 | {GROUP} | A",
        f"1 | soon | {GROUP} | A",
        "1 | 2026-10-19 18:00 | Bob | A",
        f"1 | 2026-10-19 18:00 | {GROUP} |",
    ]:
        with pytest.raises(ValueError):
            parse_line(line)


async def test_served_every_minute(
    bot: SignalBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def ready() -> None:
        pass

    monkeypatch.setattr(bot, "wait_until_ready", ready)
    sent: list[str] = []

    async def send(bot: SignalBot, chat: str, message: SendMessage) -> None:
        sent.append(message.text or "")

    monkeypatch.setattr(reminders, "send", send)
    get_settings().data_file("reminders.txt").write_text(
        f"1 | 2026-10-19 15:59:00+02:00 | {ALICE} | Due while the bot was down\n"
    )
    await serve(bot)
    # What came due meanwhile, at once, then at the start of every minute
    assert sent == ["⏰ Due while the bot was down"]
    job = cast(Any, bot.scheduler.get_job("reminders"))  # pyright: ignore[reportUnknownMemberType]
    assert job is not None
    assert str(job.trigger) == "cron[second='0']"
