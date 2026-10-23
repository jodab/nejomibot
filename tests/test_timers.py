import asyncio
from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.asyncio import (  # pyright: ignore[reportMissingTypeStubs]
    AsyncIOScheduler,
)
from helpers import ALICE, BOB, EDIT_FROM_BEFORE, GROUP, ME, FakeApi, make_jpeg
from signalbot import (
    DataMessage,
    DataMessageContext,
    DataMessageHandler,
    EditMessage,
    SendMessage,
    SignalBot,
    TextMode,
    text_triggered,
)

from nejomibot import access, commands, messages, photos, specials, timers, weather
from nejomibot.access import HEADER
from nejomibot.account import Contact
from nejomibot.bot import handlers
from nejomibot.config import get_settings
from nejomibot.messages import Outbox, collected, reply
from nejomibot.timers import (
    Chats,
    Schedule,
    Timekeeper,
    Timer,
    Timers,
    chat_list,
    chats_numbered,
    check_commands,
    example_date,
    line_of,
    missed_run,
    parse_add,
    parse_line,
    parse_when,
)

TZ = ZoneInfo("Europe/Stockholm")
NOW = datetime(2026, 10, 12, 16, 0, tzinfo=TZ)  # a Monday
ADMIN = "+46700000009"
FRIENDS = "group.RnJpZW5kcw=="
CANT = "Timers, specials and /run can't run {}."


def at(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=TZ)


# When a timer runs


@pytest.mark.parametrize(
    ("text", "kept"),
    [
        ("08:00", "daily 08:00"),
        ("8.05", "daily 08:05"),
        ("every day 18:30, 08:00", "daily 08:00,18:30"),
        ("mon-fri 7:30", "weekdays 07:30"),
        ("Sat,Sun 10:00", "weekends 10:00"),
        ("Monday, wed, fri 08:00", "mon,wed,fri 08:00"),
        ("fri-mon 09:00", "mon,fri,sat,sun 09:00"),
        ("weekdays 06:45", "weekdays 06:45"),
        ("2026-12-24 15:00", "2026-12-24 15:00"),
        ("tomorrow 08:00", "2026-10-13 08:00"),
        ("today 18:00", "2026-10-12 18:00"),
        ("every 2h", "every 2h"),
        ("every 90min", "every 1h30m"),
    ],
)
def test_parse_when(text: str, kept: str) -> None:
    schedule = parse_when(text, NOW)
    assert isinstance(schedule, Schedule)
    assert schedule.text == kept
    # It's kept as text, which reads back the same
    assert parse_when(kept, NOW) == schedule


@pytest.mark.usefixtures("swedish")
@pytest.mark.parametrize(
    ("text", "kept", "shown"),
    [
        ("mån, ons, fre 08:00", "mon,wed,fri 08:00", "mån,ons,fre 08:00"),
        ("Måndag-fredag 7.30", "weekdays 07:30", "vardagar 07:30"),
        ("vardagar 06:45", "weekdays 06:45", "vardagar 06:45"),
        ("helg 10:00", "weekends 10:00", "helger 10:00"),
        ("idag 18:00", "2026-10-12 18:00", "2026-10-12 18:00"),
        ("imorgon 08:00", "2026-10-13 08:00", "2026-10-13 08:00"),
        ("var 30m", "every 30m", "varje 30m"),
        ("varje 2h", "every 2h", "varje 2h"),
        # English too
        ("mon-fri 07:30", "weekdays 07:30", "vardagar 07:30"),
    ],
)
def test_parse_when_in_swedish(text: str, kept: str, shown: str) -> None:
    schedule = parse_when(text, NOW)
    assert isinstance(schedule, Schedule)
    # Kept in English, whatever the language; shown in Swedish
    assert schedule.text == kept
    assert timers.shown(schedule.text) == shown


def test_swedish_words_in_english_too() -> None:
    # Every language's words are read, wherever, and shown in the chat's
    schedule = parse_when("vardagar 06:45", NOW)
    assert isinstance(schedule, Schedule)
    assert schedule.text == "weekdays 06:45"


def test_parse_when_in_detail() -> None:
    assert parse_when("mon,thu 18:30,08:00", NOW) == Schedule(
        text="mon,thu 08:00,18:30",
        days=frozenset({0, 3}),
        times=(at("2026-10-12 08:00").time(), at("2026-10-12 18:30").time()),
    )
    assert parse_when("2026-12-24 15:00", NOW) == Schedule(
        text="2026-12-24 15:00", once=at("2026-12-24 15:00")
    )
    assert parse_when("every 1h30m", NOW) == Schedule(
        text="every 1h30m", every=timedelta(minutes=90)
    )


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("", "At what time?"),
        ("mon", "At what time?"),
        ("08:00 soon", "soon?"),
        ("25:00", "25:00?"),
        ("2026-02-30 10:00", "no such day"),
        ("2026-12-24 08:00,09:00", "runs once"),
        ("mon 2026-12-24 08:00", "runs once"),
        ("every 5m", "Not more often than every 10m"),
        ("every", "Every how long?"),
        ("every soon", "Every how long?"),
    ],
)
def test_parse_when_refuses(text: str, why: str) -> None:
    result = parse_when(text, NOW)
    assert isinstance(result, str)
    assert why in result


def timer_of(when: str, last: str, chats: tuple[str, ...] = (GROUP,)) -> Timer:
    return Timer(
        id=1, when=when, chats=list(chats), commands=["/weather"], last=at(last)
    )


@pytest.mark.parametrize(
    ("when", "last", "now", "due"),
    [
        # Down from before 08:00 until 08:20: made up for
        ("daily 08:00", "2026-10-11 08:00", "2026-10-12 08:20", "2026-10-12 08:00"),
        # Too late to run it now
        ("daily 08:00", "2026-10-11 08:00", "2026-10-12 09:01", None),
        # It ran, then the bot restarted; or it was added after it was due
        ("daily 08:00", "2026-10-12 08:00", "2026-10-12 08:20", None),
        ("daily 08:00", "2026-10-12 08:10", "2026-10-12 08:20", None),
        # Not on a Saturday
        ("weekdays 08:00", "2026-10-15 08:00", "2026-10-17 08:20", None),
        # Missed just before midnight
        ("daily 23:30", "2026-10-11 23:30", "2026-10-13 00:10", "2026-10-12 23:30"),
        (
            "2026-12-24 15:00",
            "2026-10-12 12:00",
            "2026-12-24 15:30",
            "2026-12-24 15:00",
        ),
        ("2026-12-24 15:00", "2026-10-12 12:00", "2026-12-24 16:30", None),
        # Every so often just carries on
        ("every 2h", "2026-10-11 08:00", "2026-10-12 08:20", None),
    ],
)
def test_missed_run(when: str, last: str, now: str, due: str | None) -> None:
    schedule = parse_when(when, at(last))
    assert isinstance(schedule, Schedule)
    assert missed_run(timer_of(when, last), schedule, at(now)) == (
        at(due) if due else None
    )


# The timers file


def test_a_line_reads_back() -> None:
    timer = Timer(
        id=3,
        when="weekdays 07:30",
        chats=[GROUP, ALICE],
        commands=["/weather", "/about Hej, hej"],
        last=at("2026-10-12 08:00:01"),
    )
    line = line_of(timer)
    assert line == (
        f"3 | weekdays 07:30 | {GROUP} {ALICE} | /weather; /about Hej, hej | "
        "2026-10-12 08:00:01+02:00"
    )
    assert parse_line(line, NOW) == timer


def test_a_line_by_hand_is_tidied() -> None:
    line = f" 4 |mon-fri 7.30|  {GROUP}   {ALICE} |/weather;/photo;| 2026-10-12 08:00"
    assert parse_line(line, NOW) == Timer(
        id=4,
        when="weekdays 07:30",
        chats=[GROUP, ALICE],
        commands=["/weather", "/photo"],
        last=at("2026-10-12 08:00"),
    )


@pytest.mark.parametrize(
    "line",
    [
        "1 | daily 08:00 | +46700000001 | /weather",
        "1 | soon | +46700000001 | /weather | 2026-10-12 08:00",
        "x | daily 08:00 | +46700000001 | /weather | 2026-10-12 08:00",
        "1 | daily 08:00 |  | /weather | 2026-10-12 08:00",
        "1 | daily 08:00 | +46700000001 | /weather | yesterday",
    ],
)
def test_a_broken_line(line: str) -> None:
    with pytest.raises(ValueError):
        parse_line(line, NOW)


# Reading /timer add


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        (
            "/timer add 08:00 1,2 /weather; /photo",
            ("08:00", [1, 2], ["/weather", "/photo"]),
        ),
        ("/timer add mon-fri 07:30 /ping", ("mon-fri 07:30", list[int](), ["/ping"])),
        (
            "/timer add daily 08:00,18:30 3 /weather",
            ("daily 08:00 18:30", [3], ["/weather"]),
        ),
        (
            "/timer add every 2h 1 2\n/ping\n/info",
            ("every 2h", [1, 2], ["/ping", "/info"]),
        ),
    ],
)
def test_parse_add(text: str, parsed: tuple[str, list[int], list[str]]) -> None:
    assert parse_add(text) == parsed


@pytest.mark.parametrize(
    ("text", "why"),
    [
        ("/timer add 08:00 1", "Which commands?"),
        ("/timer add 08:00 /weather; photo", "Commands start with /"),
        ("/timer add 08:00 " + "; ".join(["/ping"] * 11), "At most 10"),
    ],
)
def test_parse_add_refuses(text: str, why: str) -> None:
    result = parse_add(text)
    assert isinstance(result, str)
    assert why in result


@pytest.mark.parametrize(
    ("commands", "why"),
    [
        (
            [
                "/weather",
                "/today",
                "/uniquephoto",
                "/contacts",
                "/name Mybot",
                "/fortune",
                "/fortune list",
                "/fortune startrek",
            ],
            None,
        ),
        (["/weather", "/frobnicate"], "/frobnicate isn't a command"),
        (["/vädret"], "/vädret isn't a command"),
        (["/timer add 08:00 /ping"], CANT.format("/timer")),
        (["/timers run 1"], CANT.format("/timers")),
        (["/allow +46700000001"], CANT.format("/allow")),
        (["/disallow 1"], CANT.format("/disallow")),
        (["/msg 1 Hello"], CANT.format("/msg")),
        (["/run 1 /ping"], CANT.format("/run")),
        (["/specials add /x Hi"], CANT.format("/specials")),
        (["/special add /x Hi"], CANT.format("/special")),
        (["/remind 18:00 Hi"], CANT.format("/remind")),
        (["/list add milk"], CANT.format("/list")),
        (["/birthdays"], CANT.format("/birthdays")),
        (["/nameday add 08-08 Alice"], CANT.format("/nameday")),
        (["/about a|b"], "A timer's commands can't have a |"),
    ],
)
def test_check_commands(commands: list[str], why: str | None) -> None:
    result = check_commands(commands)
    if why is None:
        assert result is None
    else:
        assert (result or "").startswith(why)


@pytest.mark.usefixtures("swedish")
def test_check_commands_by_their_other_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/pic"], "/timer": ["/t"]}')
    get_settings.cache_clear()
    assert check_commands(["/väder", "/idag", "/Pic", "/spådom startrek"]) is None
    # Their subcommands too
    assert check_commands(["/unikbild", "/idag förhandsvisa imorgon"]) is None
    # Named as given
    for command in ("/t add 08:00 /ping", "/skicka 1 Hej", "/kör 1 /ping"):
        assert check_commands([command]) == (
            f"Timrar, specialkommandon och /kör kan inte köra {command.split()[0]}."
        )


def test_what_timers_mayn_t_run() -> None:
    # What changes timers, specials, birthdays, albums or who may use the bot,
    # posts
    # to chats of its own, or is a chat's own, as reminders and lists are:
    # /timers and /specials with more after them, which change them too
    assert {
        command.name
        for handler in commands.handlers()
        for command in handler.commands
        if not command.timers
    } == {
        "/timers",
        "/timer",
        "/allow",
        "/disallow",
        "/admin",
        "/msg",
        "/run",
        "/specials",
        "/special",
        "/birthday",
        "/nameday",
        "/birthdays",
        "/namedays",
        "/album",
        "/language",
        "/remind",
        "/list",
    }


def test_timers_may_run_what_only_lists() -> None:
    assert (
        check_commands(
            [
                "/chats",
                "/allowed",
                "/admins",
                "/incoming",
                "/incoming 4,9",
                "/delivery",
                "/timers",
                "/specials",
                "/today preview tomorrow",
            ]
        )
        is None
    )
    # Not what changes timers or specials, by either name
    for command in (
        "/timers run 1",
        "/timers add 08:00 /ping",
        "/timer list",
        "/specials add /x Hej",
    ):
        name = command.split()[0]
        assert check_commands([command]) == (
            f"Timers, specials and /run can't run {name}."
        )


async def test_a_timer_doesn_t_run_what_it_mayn_t(keeper: Timekeeper) -> None:
    # Even from a file changed by hand: check_commands keeps them out
    assert await keeper.answers_to("/msg 1 Hi") == []


# Running timers


class FakeGroups:
    def __init__(self, *groups: SimpleNamespace) -> None:
        self._groups = groups

    def __iter__(self) -> Any:
        return iter(self._groups)


def group(group_id: str, name: str, *, member: bool = True) -> SimpleNamespace:
    return SimpleNamespace(id=group_id, name=name, member=member)


class FakeBot:
    def __init__(self) -> None:
        self.scheduler = AsyncIOScheduler()
        self.groups = FakeGroups(
            group(FRIENDS, "Friends"),
            group(GROUP, "Familjen"),
            group("group.b2xk", "Old", member=False),
        )

    async def wait_until_ready(self) -> None:
        pass

    def job_ids(self) -> list[str]:
        jobs: list[Any] = self.scheduler.get_jobs()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return sorted(job.id for job in jobs)


class Answer(DataMessageHandler):
    """Answers /ping with what it saw, and twice to /info."""

    @text_triggered("/ping", "/info")
    async def handle_data_message(self, context: DataMessageContext) -> None:
        message = context.message
        seen = f"{message.text} from {message.source_number}"
        await reply(
            context, SendMessage(text=f"{seen}, private {message.is_private()}")
        )
        if message.text == "/info":
            await asyncio.sleep(0.01)
            await reply(context, SendMessage(text="again"))


class Slow(DataMessageHandler):
    @text_triggered("/weather")
    async def handle_data_message(self, context: DataMessageContext) -> None:
        await asyncio.sleep(0.05)
        await reply(context, SendMessage(text="slow"))


class Broken(DataMessageHandler):
    async def handle_data_message(self, context: DataMessageContext) -> None:
        raise RuntimeError("broken")


type Sent = list[tuple[str, str | None]]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> Sent:
    """What the timers send: (chat, text)."""
    posted: Sent = []

    async def send(_: SignalBot, recipient: str, message: SendMessage) -> None:
        posted.append((recipient, message.text))

    monkeypatch.setattr(timers, "send", send)
    return posted


@pytest.fixture
def keeper() -> Timekeeper:
    keeper = Timekeeper()
    keeper.start(cast(SignalBot, FakeBot()), [Broken(), Answer(), Slow()])
    return keeper


def add(keeper: Timekeeper, when: str, chats: list[str], *commands: str) -> Timer:
    schedule = parse_when(when, datetime.now(TZ))
    assert isinstance(schedule, Schedule)
    return keeper.add(schedule.text, chats, list(commands))


async def test_run_posts_the_answers_to_every_chat(
    keeper: Timekeeper, sent: Sent
) -> None:
    timer = add(keeper, "08:00", [GROUP, ALICE], "/weather", "/info")
    await keeper.run(timer.id, on_schedule=False)
    # Each command once, as an admin would in a direct chat (the bot itself,
    # with no admins); its answers go to every chat before the next command's
    seen = f"/info from {ME}, private True"
    assert sent == [
        (GROUP, "slow"),
        (ALICE, "slow"),
        (GROUP, seen),
        (ALICE, seen),
        (GROUP, "again"),
        (ALICE, "again"),
    ]
    assert collected.get() is None


async def test_run_skips_a_group_the_bot_left(keeper: Timekeeper, sent: Sent) -> None:
    timer = add(keeper, "08:00", ["group.b2xk", ALICE], "/ping")
    await keeper.run(timer.id)
    assert [chat for chat, _ in sent] == [ALICE]


async def test_a_run_on_schedule_is_kept(keeper: Timekeeper, sent: Sent) -> None:
    timer = add(keeper, "08:00", [ALICE], "/ping")
    once = add(keeper, "2030-01-01 08:00", [ALICE], "/ping")
    timer.last = before = at("2026-10-01 08:00")
    await keeper.run(timer.id)
    await keeper.run(once.id)
    assert keeper.timers[timer.id].last > before
    # A timer on a date has run its once
    assert set(keeper.timers) == {timer.id}
    again = Timekeeper()
    again.read()
    assert again.timers == keeper.timers


def test_rereading_isnt_skipped_when_late(keeper: Timekeeper) -> None:
    # APScheduler skips a run more than a second late, by default
    bot = cast(FakeBot, keeper.bot)
    job = cast(Any, bot.scheduler.get_job("timers-reread"))  # pyright: ignore[reportUnknownMemberType]
    assert job.misfire_grace_time is None


def test_scheduled_as_kept(keeper: Timekeeper) -> None:
    bot = cast(FakeBot, keeper.bot)
    add(keeper, "mon,fri 08:00,18:30", [ALICE], "/ping")
    add(keeper, "every 2h", [ALICE], "/ping")
    assert bot.job_ids() == ["timer-1-0", "timer-1-1", "timer-2-0", "timers-reread"]

    # A restart schedules them again
    again = Timekeeper()
    again.start(cast(SignalBot, FakeBot()), [])
    assert again.timers == keeper.timers
    assert cast(FakeBot, again.bot).job_ids() == bot.job_ids()

    removed = keeper.remove(1)
    assert removed is not None
    assert removed.id == 1
    assert bot.job_ids() == ["timer-2-0", "timers-reread"]
    assert keeper.remove(1) is None


def test_changes_to_the_file_are_taken_in(keeper: Timekeeper) -> None:
    bot = cast(FakeBot, keeper.bot)
    add(keeper, "08:00", [ALICE], "/ping")
    path = get_settings().timers_file
    # As nejomibot-timers would add one; and a line nobody can read
    with path.open("a") as f:
        f.write(f"7 | every 2h | {ALICE} | /weather | 2026-10-12 08:00:00+02:00\n")
        f.write("8 | soon | nobody | /ping | never\n")
    keeper.reread()
    assert set(keeper.timers) == {1, 7}
    assert bot.job_ids() == ["timer-1-0", "timer-7-0", "timers-reread"]
    # The line it can't read stays as it is, after the timers
    keeper.remove(1)
    lines = [line for line in path.read_text().splitlines() if not line.startswith("#")]
    assert lines == [
        f"7 | every 2h | {ALICE} | /weather | 2026-10-12 08:00:00+02:00",
        "8 | soon | nobody | /ping | never",
    ]


def test_a_new_timer_takes_a_number_no_line_has(keeper: Timekeeper) -> None:
    # Not that of a line the bot can't read, which may be set right later
    path = get_settings().timers_file
    with path.open("a") as f:
        f.write("4 | soon | nobody | /ping | never\n")
    keeper.reread()
    assert add(keeper, "08:00", [ALICE], "/ping").id == 5


@pytest.mark.parametrize(
    ("today", "example"),
    [
        (date(2026, 10, 17), "2026-12-24"),
        (date(2026, 12, 24), "2027-12-24"),
        (date(2027, 1, 1), "2027-12-24"),
    ],
)
def test_the_example_date_is_still_to_come(today: date, example: str) -> None:
    assert example_date(today) == example


@pytest.mark.usefixtures("swedish")
async def test_a_daily_post_sends_everyone_the_same(
    sent: Sent, monkeypatch: pytest.MonkeyPatch
) -> None:
    photos_picked: list[bool] = []

    async def weather_message(city: str = "") -> str:
        return "Vädret"

    async def photo_message(text: str = "", *, unique: bool = False) -> SendMessage:
        photos_picked.append(unique)
        return SendMessage(text="📷", text_mode=TextMode.STYLED)

    monkeypatch.setattr(weather, "weather_message", weather_message)
    monkeypatch.setattr(photos, "photo_message", photo_message)
    # A special of the admins', as /special add keeps it: Dagens bild! in
    # bold over the photo
    get_settings().specials_file.write_text(
        "/dailypost | /today; /weather; **Dagens bild!** /uniquephoto\n"
    )
    bot = cast(SignalBot, FakeBot())
    keeper = Timekeeper()
    keeper.start(bot, [h for h, *_ in handlers(bot, get_settings())])
    monkeypatch.setattr(specials, "timekeeper", keeper)
    timer = add(keeper, "08:00", [GROUP, ALICE], "/dailypost")
    await keeper.run(timer.id)
    assert sent == [
        (GROUP, "Vädret"),
        (ALICE, "Vädret"),
        (GROUP, "**Dagens bild!**\n\n📷"),
        (ALICE, "**Dagens bild!**\n\n📷"),
    ]
    # One photo, from those not sent yet this round
    assert photos_picked == [True]


async def test_a_timer_runs_a_special_of_the_admins(
    sent: Sent, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_settings().specials_file.write_text("/morning | Morning! /cache; Bye!\n")
    bot = cast(SignalBot, FakeBot())
    keeper = Timekeeper()
    keeper.start(bot, [h for h, *_ in handlers(bot, get_settings())])
    monkeypatch.setattr(specials, "timekeeper", keeper)
    timer = add(keeper, "08:00", [GROUP, ALICE], "/morning")
    await keeper.run(timer.id)
    # The special's messages in order, each to every chat before the next
    cache = "Morning!\n\n📂 Photo cache contains 0 photos (0.0B):"
    assert sent == [(GROUP, cache), (ALICE, cache), (GROUP, "Bye!"), (ALICE, "Bye!")]
    # The timers file reads back with it
    again = Timekeeper()
    again.read()
    assert again.timers == keeper.timers


def test_no_file_no_timers(keeper: Timekeeper) -> None:
    assert keeper.timers == {}
    assert (get_settings().timers_file).read_text().startswith("# nejomibot's timers")


def test_debug_mode_starts_afresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_DEBUG", "1")
    monkeypatch.setenv("NEJOMIBOT_DEBUG_GROUP", FRIENDS)
    get_settings.cache_clear()
    keeper = Timekeeper()
    keeper.start(cast(SignalBot, FakeBot()), [])
    assert keeper.timers == {}
    path = get_settings().timers_file
    assert get_settings().data_dir not in path.parents
    assert path.read_text().startswith("# nejomibot's timers")


# The commands


@pytest.fixture
async def admin_chat(
    sent: Sent, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[Timekeeper, list[str]]]:
    """A started timekeeper, and the replies its commands send. Alice and Bob
    are allowed."""
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()
    get_settings().allowed_file.write_text("\n".join([*HEADER, ALICE, BOB, ""]))
    keeper = Timekeeper()
    bot = FakeBot()
    keeper.start(cast(SignalBot, bot), [Answer()])
    bot.scheduler.start()  # pyright: ignore[reportUnknownMemberType]
    replies: list[str] = []

    async def reply(_: DataMessageContext, message: SendMessage) -> None:
        replies.append(message.text or "")

    async def fetch_recipients() -> list[Contact]:
        return [
            Contact(number=ALICE, name="Alice"),
            Contact(number=ADMIN, name="Admin"),
        ]

    monkeypatch.setattr(timers, "timekeeper", keeper)
    monkeypatch.setattr(commands, "reply", reply)
    monkeypatch.setattr(access, "fetch_recipients", fetch_recipients)
    yield keeper, replies
    bot.scheduler.shutdown(wait=False)  # pyright: ignore[reportUnknownMemberType]


def context_of(
    keeper: Timekeeper, text: str, *, edit: bool = False
) -> DataMessageContext:
    fields: dict[str, Any] = {
        "server_delivered_timestamp": 0,
        "server_received_timestamp": 0,
        "timestamp": 2,
        "source_number": ADMIN,
        "text": text,
    }
    # An edit is of the message before, as Signal names it
    if edit:
        fields["timestamp"] = 3
        message = EditMessage(**fields, target_sent_timestamp=2)
    else:
        message = DataMessage(**fields)
    return DataMessageContext(cast(SignalBot, keeper.bot), message)


async def command(keeper: Timekeeper, text: str, *, edit: bool = False) -> None:
    handler = Chats() if text == "/chats" else Timers()
    await handler.handle_data_message(context_of(keeper, text, edit=edit))


async def test_chats_are_numbered(admin_chat: tuple[Timekeeper, list[str]]) -> None:
    keeper, replies = admin_chat
    await command(keeper, "/chats")
    # Groups by name, then the allowed list's people, then the admins
    assert replies[-1].splitlines() == [
        "🗨️ **Timers can post to:**",
        "1 👥 Familjen",
        "2 👥 Friends",
        f"3 👤 Alice ({ALICE})",
        f"4 👤 {BOB}",
        f"5 👤 Admin ({ADMIN})",
        "",
        "For /timer add, e.g. /timer add 08:00 1,2 /weather; /photo",
    ]


async def test_debug_mode_offers_only_the_debug_group(
    admin_chat: tuple[Timekeeper, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    keeper, _replies = admin_chat
    monkeypatch.setenv("NEJOMIBOT_DEBUG", "1")
    monkeypatch.setenv("NEJOMIBOT_DEBUG_GROUP", FRIENDS)
    get_settings.cache_clear()
    assert keeper.bot is not None
    assert [chat for chat, _name in await chat_list(keeper.bot)] == [FRIENDS, ADMIN]


async def test_chats_numbered(admin_chat: tuple[Timekeeper, list[str]]) -> None:
    keeper, _replies = admin_chat
    assert keeper.bot is not None
    assert await chats_numbered(keeper.bot, [3, 1, 3]) == [
        (ALICE, f"Alice ({ALICE})"),
        (GROUP, "Familjen"),
    ]
    assert await chats_numbered(keeper.bot, [6]) == (
        "There's no chat 6: /chats numbers them."
    )


async def test_add_list_run_and_remove(
    admin_chat: tuple[Timekeeper, list[str]], sent: Sent
) -> None:
    keeper, replies = admin_chat
    # A card each: when, where, what, and when next, in short lines
    first = f"**#1** · weekdays 07:30\n💬 Friends, Alice ({ALICE})\n▶️ /ping\n🔜 Next: "
    await command(keeper, "/timer add mon-fri 07:30 2,3 /ping")
    assert replies[-1].startswith(f"✅ **Added**\n{first}")
    await command(keeper, "/timer add every 2h /info")
    assert replies[-1].startswith(
        f"✅ **Added**\n**#2** · every 2h\n💬 Admin ({ADMIN})\n▶️ /info\n🔜 Next: "
    )

    await command(keeper, "/timers")
    title, card_1, card_2 = replies[-1].split("\n\n")
    assert title == "**⏰ 2 timers**"
    assert card_1.startswith(first)
    assert card_2.startswith(
        f"**#2** · every 2h\n💬 Admin ({ADMIN})\n▶️ /info\n🔜 Next: "
    )

    await command(keeper, "/timer run 1")
    assert replies[-1] == "▶️ Ran timer #1"
    assert [chat for chat, _ in sent] == [FRIENDS, ALICE]
    replies.clear()
    await command(keeper, "/timer run 2")
    # Posted to the admin, here, it speaks for itself
    assert replies == []
    assert [chat for chat, _ in sent[2:]] == [ADMIN, ADMIN]

    await command(keeper, "/timer remove 1")
    assert replies[-1] == (
        f"🗑️ **Removed**\n**#1** · weekdays 07:30\n💬 Friends, Alice ({ALICE})\n▶️ /ping"
    )
    assert set(keeper.timers) == {2}


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("/timer add 08:00 9 /ping", "There's no chat 9: /chats numbers them."),
        ("/timer add 08:00 1 /frobnicate", "/frobnicate isn't a command"),
        ("/timer add yesterday 08:00 1 /ping", "yesterday?"),
        ("/timer add 2020-01-01 08:00 1 /ping", "2020-01-01 08:00 has already been."),
        ("/timer remove 7", "No timer #7."),
        ("/timer run x", "Which timer?"),
        ("/timer frobnicate", "/chats: where timers can post"),
        ("/timers", "No timers yet."),
    ],
)
async def test_refused(
    admin_chat: tuple[Timekeeper, list[str]], text: str, answer: str
) -> None:
    keeper, replies = admin_chat
    await command(keeper, text)
    assert replies[-1].startswith(answer)
    assert keeper.timers == {}


async def test_an_edit_takes_the_place_of_what_it_edits(
    admin_chat: tuple[Timekeeper, list[str]],
) -> None:
    keeper, replies = admin_chat
    await command(keeper, "/timer add 08:00 1 /ping")
    await command(keeper, "/timer add 09:00 1 /ping", edit=True)
    assert [timer.when for timer in keeper.timers.values()] == ["daily 09:00"]
    # A timer removed comes back, with its number, for an edit to remove another
    [timer] = keeper.timers.values()
    await command(keeper, f"/timer remove {timer.id}")
    await command(keeper, "/timer remove 9", edit=True)
    assert list(keeper.timers) == [timer.id]
    assert replies[-1] == "No timer #9."
    # What a run posted has gone out
    await command(keeper, f"/timer run {timer.id}", edit=True)
    assert replies[-1] == (
        "✏️ An edit of /timer isn't run, as what it did can't be undone. Send it "
        "as a new message instead."
    )


async def test_an_edit_of_a_message_from_before_a_start(
    admin_chat: tuple[Timekeeper, list[str]],
) -> None:
    keeper, replies = admin_chat
    await command(keeper, "/timer add 08:00 1 /ping", edit=True)
    assert replies == [EDIT_FROM_BEFORE]
    assert keeper.timers == {}


# Through the real bot


async def test_a_real_command_answers_through_the_outbox(
    bot: SignalBot, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real bot's handlers take a timer's command like a received one."""
    outbox = Outbox()
    outbox.start(bot)
    monkeypatch.setattr(messages, "outbox", outbox)
    bot.init_task = asyncio.create_task(asyncio.sleep(0))  # as if started
    keeper = Timekeeper()
    keeper.start(bot, [h for h, *_ in handlers(bot, get_settings())])
    timer = add(keeper, "08:00", [ALICE, BOB], "/ping")
    await keeper.run(timer.id, on_schedule=False)
    posted = signal_api.bodies("POST", "/v2/send")
    assert [(m["recipients"], m["message"][:5]) for m in posted] == [
        ([ALICE], "pong!"),
        ([BOB], "pong!"),
    ]
    # No read receipt or typing: nobody sent the command
    assert {r.path for r in signal_api.requests} == {"/v2/send"}


def test_the_file_is_private_and_kept_on_errors(
    keeper: Timekeeper,
) -> None:
    add(keeper, "08:00", [ALICE], "/ping")
    path = get_settings().timers_file
    assert path.stat().st_mode & 0o777 == 0o600
    # A file that can't be read leaves the timers as they were
    path.write_bytes(b"\xff\xfe not UTF-8\n")
    keeper.reread()
    assert set(keeper.timers) == {1}


@pytest.mark.usefixtures("swedish")
async def test_the_file_keeps_the_english_names(
    admin_chat: tuple[Timekeeper, list[str]],
) -> None:
    keeper, replies = admin_chat
    # Subcommands too: /spådom alla as /fortune all
    await command(keeper, "/timer lägg till 08:00 /idag; /unikbild; /spådom alla")
    assert replies[-1].startswith(
        f"✅ **Tillagd**\n**#1** · dagligen 08:00\n💬 Admin ({ADMIN})\n"
        "▶️ /today; /uniquephoto; /fortune all\n🔜 Nästa: "
    )
    assert keeper.timers[1].commands == ["/today", "/uniquephoto", "/fortune all"]
    file = (get_settings().timers_file).read_text()
    assert "| /today; /uniquephoto; /fortune all |" in file
    # A line by hand, with Swedish names, reads as English too
    assert parse_line(
        f"2 | 08:00 | {ALICE} | /väder; /Bild | 2026-10-12 08:00", NOW
    ) == (
        Timer(2, "daily 08:00", [ALICE], ["/weather", "/photo"], at("2026-10-12 08:00"))
    )


async def test_a_timer_speaks_each_chats_language(sent: Sent, photos_dir: Path) -> None:
    for name in ["a.jpg", "b.jpg"]:
        make_jpeg(photos_dir / name)
    get_settings().data_file("languages.txt").write_text(f"{GROUP} | sv\n")
    bot = cast(SignalBot, FakeBot())
    keeper = Timekeeper()
    keeper.start(bot, [h for h, *_ in handlers(bot, get_settings())])
    timer = add(keeper, "08:00", [GROUP, ALICE], "/uniquephoto")
    for run in range(2):
        sent.clear()
        await keeper.run(timer.id)
        picked = get_settings().sent_photos_file.read_text().splitlines()
        # The round used up one photo a run, and both chats got it, each
        # captioned in its language
        assert len(picked) == run + 1
        assert sent == [
            (GROUP, f"⚠️ Datum okänt (se filnamn)\n🖼️ {picked[-1]}"),
            (ALICE, f"⚠️ Date unknown (see the file name)\n🖼️ {picked[-1]}"),
        ]
