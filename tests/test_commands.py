import logging
from collections.abc import Callable
from typing import Any, cast

import pytest
from helpers import ALICE, EDIT_FROM_BEFORE
from signalbot import (
    DataMessage,
    DataMessageContext,
    EditMessage,
    SendMessage,
    SignalBot,
    TextMode,
)

from nejomibot import commands
from nejomibot.commands import (
    ALIASES,
    Command,
    Edits,
    Handler,
    aliases,
    answer,
    argument,
    cannot_undo,
    canonical,
    known,
    numbers_in,
    undo_with,
)
from nejomibot.config import get_settings
from nejomibot.messages import collected


@pytest.fixture
def pic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEJOMIBOT_ALIASES", '{"/photo": ["/pic", "Pic"], "/fortune": ["/f"]}'
    )
    get_settings.cache_clear()


@pytest.mark.usefixtures("swedish")
@pytest.mark.parametrize(
    ("text", "english"),
    [
        ("/lista lägg till mjölk", "/list add mjölk"),
        # Any case and spaces; what follows stays as it is
        ("/lista  Lägg\nTILL mjölk,\nägg", "/list  add mjölk,\nägg"),
        ("/timer ta bort 3", "/timer remove 3"),
        ("/timer radera 3", "/timer remove 3"),
        ("/timer kör 3", "/timer run 3"),
        ("/timers lista", "/timers list"),
        ("/radera lista", "/delete list"),
        ("/spådom alla", "/fortune all"),
        ("/spådom lista", "/fortune list"),
        ("/lista töm", "/list clear"),
        ("/födelsedag lägg till 03-14 Alice", "/birthday add 03-14 Alice"),
        ("/kontakter lägg till Alice Ali", "/contacts add Alice Ali"),
        ("/om ta bort", "/about remove"),
        ("/idag förhandsvisa imorgon", "/today preview imorgon"),
        ("/bild ny", "/photo new"),
        # The English ones too, in any language
        ("/list add milk", "/list add milk"),
        # Only a command's own subcommands, whole words, right after it
        ("/väder alla", "/weather alla"),
        ("/kontakter tabort", "/contacts tabort"),
        ("/lista mjölk lägg till", "/list mjölk lägg till"),
        ("/listan töm", "/listan töm"),
    ],
)
def test_subcommands_in_the_language(text: str, english: str) -> None:
    assert canonical(text) == english


def test_subcommands_in_english_only_in_english() -> None:
    assert canonical("/list lägg till milk") == "/list lägg till milk"


@pytest.mark.usefixtures("pic")
@pytest.mark.parametrize(
    ("text", "command"),
    [
        ("/pic", "/photo"),
        ("/PIC", "/photo"),
        ("pic", "/photo"),
        ("/f startrek", "/fortune startrek"),
        ("/f\nstartrek  ", "/fortune\nstartrek  "),
        # Not an alias at the start: as it is
        ("/picture", "/picture"),
        ("a /pic", "a /pic"),
        (" /pic", " /pic"),
        ("", ""),
    ],
)
def test_canonical(text: str, command: str) -> None:
    assert canonical(text) == command


def test_no_aliases_but_the_bots_own() -> None:
    assert aliases() == {"/test": "/status", "/time": "/info", "/safety": "/contacts"}
    assert canonical("/väder") == "/väder"  # Swedish, so not in English


@pytest.mark.parametrize("language", ["en", "sv"])
@pytest.mark.parametrize(
    ("text", "command"),
    [("/test", "/status"), ("/TIME", "/info"), ("/safety Alice", "/contacts Alice")],
)
def test_the_bots_own_aliases_in_every_language(
    monkeypatch: pytest.MonkeyPatch, language: str, text: str, command: str
) -> None:
    monkeypatch.setenv("NEJOMIBOT_LANGUAGE", language)
    get_settings.cache_clear()
    assert canonical(text) == command


def test_the_settings_win_over_the_bots_own(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/test"]}')
    get_settings.cache_clear()
    assert canonical("/test") == "/photo"
    assert canonical("/time") == "/info"


@pytest.mark.usefixtures("swedish")
def test_the_settings_win_over_the_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/tid", "/bilden"]}')
    get_settings.cache_clear()
    assert canonical("/tid") == "/photo"
    assert canonical("/väder") == "/weather"


class Seen(Handler):
    """Remembers the texts it was given, and the commands they were."""

    commands = (Command("/photo"), Command("/cache"))

    def __init__(self) -> None:
        self.seen: list[tuple[str | None, str]] = []

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        self.seen.append((context.message.text, command.name))


class SeenWithMore(Seen):
    commands = (Command("/fortune", more=True),)


def context_of(
    text: str | None, *, edit: bool = False, at: int = 0, of: int | None = None
) -> DataMessageContext:
    """A message sent at at, in ms; with edit, an edit of the message sent
    then, or of that sent at of, sent at at."""
    fields: dict[str, Any] = {
        "server_delivered_timestamp": 0,
        "server_received_timestamp": 0,
        "timestamp": at + 1 if edit and of is None else at,
        "source_number": ALICE,
        "text": text,
    }
    message = (
        EditMessage(**fields, target_sent_timestamp=at if of is None else of)
        if edit
        else DataMessage(**fields)
    )
    return DataMessageContext(cast(SignalBot, None), message)


@pytest.mark.usefixtures("pic")
async def test_a_command_is_the_whole_text() -> None:
    handler = Seen()
    for text in ["/photo", "/Cache", "Pic", "/pic now", "/photo now", None, "/f"]:
        await handler.handle_data_message(context_of(text))
    assert handler.seen == [
        ("/photo", "/photo"),
        ("/Cache", "/cache"),
        ("/photo", "/photo"),
    ]


async def test_a_command_by_a_name_the_bot_comes_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(commands, "ALIASES", {"/cache": ["/stash"]})
    handler = Seen()
    await handler.handle_data_message(context_of("/STASH"))
    assert handler.seen == [("/cache", "/cache")]


@pytest.mark.usefixtures("pic")
async def test_more_may_follow_a_command() -> None:
    handler = SeenWithMore()
    for text in ["/fortune", "/F startrek", "/fortunes", "/pic", "/fortune\nall"]:
        await handler.handle_data_message(context_of(text))
    assert [text for text, _command in handler.seen] == [
        "/fortune",
        "/fortune startrek",
        "/fortune\nall",
    ]


@pytest.mark.usefixtures("pic")
async def test_the_message_received_is_left_as_it_is() -> None:
    context = context_of("/pic")
    await Seen().handle_data_message(context)
    assert context.message.text == "/pic"


def test_known_commands() -> None:
    # Every command of every handler, by the name its handler takes
    weather = known("/WEATHER")
    assert weather is not None and weather.name == "/weather"
    assert known("weather") is None  # only an alias may be a plain word
    fortune = known("/fortune startrek")
    assert fortune is not None and (fortune.name, fortune.more) == ("/fortune", True)
    msg = known("/msg 1 Hi")
    assert msg is not None and not msg.timers
    assert known("/weather Stockholm") == Command("/weather", more=True)
    assert known("/ping now") is None
    assert known("/frobnicate") is None


def test_every_name_starts_with_a_slash() -> None:
    # Plain words are for the config's aliases alone
    for handler in commands.handlers():
        for command in handler.commands:
            assert command.name.startswith("/"), command.name
    for command, names in ALIASES.items():
        assert known(command), command
        for name in names:
            assert name.startswith("/") and not known(name), name


@pytest.mark.parametrize(
    ("text", "numbers"),
    [
        ("4,9", [4, 9]),
        ("4, 9 4", [4, 9]),
        ("#4", [4]),
        ("4,x", None),
        ("²", None),
        ("1" * 5000, None),  # more than int() reads
        (",", None),
    ],
)
def test_numbers_in(text: str, numbers: list[int] | None) -> None:
    assert numbers_in(text) == numbers


def test_argument() -> None:
    assert argument("/name  Mybot\n Boten ") == "Mybot Boten"
    assert argument("/name") == ""
    assert argument(None) == ""


class Replies:
    """What answer() sends, and whether it marked the command read and showed
    typing."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.sent: list[SendMessage] = []
        self.done: list[str] = []
        monkeypatch.setattr(commands, "reply", self.reply)
        monkeypatch.setattr(commands, "mark_read", self.mark_read)
        monkeypatch.setattr(commands, "show_typing", self.show_typing)

    async def reply(self, context: DataMessageContext, message: SendMessage) -> None:
        self.sent.append(message)

    async def mark_read(self, context: DataMessageContext) -> None:
        self.done.append("read")

    async def show_typing(self, context: DataMessageContext) -> None:
        self.done.append("typing")


@pytest.fixture
def replies(monkeypatch: pytest.MonkeyPatch) -> Replies:
    return Replies(monkeypatch)


async def test_answer(replies: Replies) -> None:
    async def hello() -> str:
        return "Hello *there*"

    await answer(context_of("/hello"), hello, slow=True)
    assert replies.done == ["read", "typing"]
    assert [(m.text, m.text_mode) for m in replies.sent] == [("Hello *there*", None)]


async def test_answer_styled_with_several_messages(replies: Replies) -> None:
    photo = SendMessage(text="A photo", base64_attachments=["aGVq"])
    await answer(context_of("/post"), lambda: ["**Hi**", photo], styled=True)
    assert replies.done == ["read"]
    assert replies.sent == [
        SendMessage(text="**Hi**", text_mode=TextMode.STYLED),
        photo,
    ]


async def test_answer_nothing(replies: Replies) -> None:
    await answer(context_of("/delete"), lambda: None)
    assert replies.done == ["read"]
    assert replies.sent == []


@pytest.mark.parametrize(("styled", "text"), [(False, "*oops*"), (True, r"\*oops\*")])
async def test_answer_says_what_went_wrong(
    replies: Replies, caplog: pytest.LogCaptureFixture, styled: bool, text: str
) -> None:
    def broken() -> str:
        raise KeyError("*oops*")

    await answer(context_of("/broken"), broken, styled=styled)
    assert [m.text for m in replies.sent] == [f"Something went wrong: '{text}'"]
    # A bug, so where it happened
    assert "/broken failed" in caplog.text
    assert "Traceback" in caplog.text


async def test_answer_logs_an_expected_failure_in_a_line(
    replies: Replies, caplog: pytest.LogCaptureFixture
) -> None:
    def unreachable() -> str:
        raise ConnectionRefusedError("refused")

    await answer(context_of("/weather"), unreachable)
    assert "/weather failed: refused" in caplog.text
    assert "Traceback" not in caplog.text


# Edits

# A message sent while the bot runs
RUNNING = int((commands.STARTED + 10 * 60) * 1000)
NOT_RUN = (
    "✏️ An edit of /msg isn't run, as what it did can't be undone. Send it as a "
    "new message instead."
)


def adding(items: list[str], item: str) -> Callable[[], str]:
    """A command that adds the item, and says how to undo that."""

    def run() -> str:
        items.append(item)
        undo_with(lambda: items.remove(item))
        return f"Added {item}"

    return run


async def test_an_edit_of_what_shows_something_runs_again(replies: Replies) -> None:
    await answer(context_of("/weather", edit=True), lambda: "Sunny")
    assert [m.text for m in replies.sent] == ["Sunny"]


async def test_an_edit_of_what_cant_be_undone_isnt_run(replies: Replies) -> None:
    ran: list[str] = []
    await answer(
        context_of("/msg 1 Hi", edit=True),
        lambda: ran.append("msg"),
        edits=Edits.NOT_RUN,
    )
    assert [m.text for m in replies.sent] == [NOT_RUN]
    # /delete's, quietly: what it posted would be the next to go
    await answer(
        context_of("/delete", edit=True), lambda: ran.append("del"), edits=Edits.IGNORE
    )
    assert ran == []
    assert len(replies.sent) == 1


async def test_an_edit_takes_the_place_of_what_it_edits(replies: Replies) -> None:
    items: list[str] = []
    for text, item, edit in [
        ("/add mlik", "mlik", False),
        ("/add milk", "milk", True),
        ("/add milk!", "milk!", True),  # an edit of the edit, of the same message
    ]:
        context = context_of(text, edit=edit, at=RUNNING)
        await answer(context, adding(items, item), edits=Edits.REPLACE)
    assert items == ["milk!"]
    assert [m.text for m in replies.sent] == ["Added mlik", "Added milk", "Added milk!"]


@pytest.mark.parametrize("names_the_latest", [True, False])
async def test_an_edit_of_an_edit(replies: Replies, names_the_latest: bool) -> None:
    # Signal Desktop names the latest edit, others the first message
    items: list[str] = []
    first, edited, again = RUNNING, RUNNING + 1000, RUNNING + 2000
    await answer(context_of("/a", at=first), adding(items, "a"), edits=Edits.REPLACE)
    context = context_of("/b", edit=True, at=edited, of=first)
    await answer(context, adding(items, "b"), edits=Edits.REPLACE)
    of = edited if names_the_latest else first
    context = context_of("/c", edit=True, at=again, of=of)
    await answer(context, adding(items, "c"), edits=Edits.REPLACE)
    assert items == ["c"]


async def test_an_edit_of_a_refused_edit_is_refused(replies: Replies) -> None:
    items: list[str] = []
    before_the_start = RUNNING - 10 * 60 * 1000
    context = context_of("/a", edit=True, at=RUNNING, of=before_the_start)
    await answer(context, adding(items, "a"), edits=Edits.REPLACE)
    # The next edit names the edit, sent while the bot runs
    context = context_of("/b", edit=True, at=RUNNING + 1000, of=RUNNING)
    await answer(context, adding(items, "b"), edits=Edits.REPLACE)
    assert items == []
    assert [m.text for m in replies.sent] == [EDIT_FROM_BEFORE] * 2


async def test_an_edit_of_what_changed_nothing_runs(replies: Replies) -> None:
    items: list[str] = []
    # The message the edit edits was no command, or one refused
    context = context_of("/add milk", edit=True, at=RUNNING)
    await answer(context, adding(items, "milk"), edits=Edits.REPLACE)
    assert items == ["milk"]


async def test_an_edit_of_a_message_from_before_the_start(replies: Replies) -> None:
    items: list[str] = []
    context = context_of("/add milk", edit=True, at=RUNNING - 10 * 60 * 1000)
    await answer(context, adding(items, "milk"), edits=Edits.REPLACE)
    assert items == []
    assert [m.text for m in replies.sent] == [EDIT_FROM_BEFORE]


async def test_an_edit_of_what_cant_be_undone_says_why(replies: Replies) -> None:
    def contact() -> str:
        cannot_undo("Not that one.")
        return "Made"

    await answer(context_of("/x", at=RUNNING), contact, edits=Edits.REPLACE)
    for _ in range(2):
        await answer(
            context_of("/x", edit=True, at=RUNNING), contact, edits=Edits.REPLACE
        )
    assert [m.text for m in replies.sent] == ["Made", "Not that one.", "Not that one."]


async def test_an_undo_that_fails(replies: Replies) -> None:
    def broken() -> str:
        def undo() -> None:
            raise OSError("disk full")

        undo_with(undo)
        return "Done"

    await answer(context_of("/x", at=RUNNING), broken, edits=Edits.REPLACE)
    for _ in range(2):
        await answer(
            context_of("/x", edit=True, at=RUNNING), broken, edits=Edits.REPLACE
        )
    assert [m.text for m in replies.sent] == [
        "Done",
        "Something went wrong: disk full",
        "✏️ That edit isn't run: undoing what the message it edits did failed. Send "
        "it as a new message instead.",
    ]


async def test_what_commands_did_is_kept_a_day(
    replies: Replies, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = [1000.0]
    monkeypatch.setattr(commands.time, "monotonic", lambda: clock[0])
    items: list[str] = []
    await answer(
        context_of("/add", at=RUNNING), adding(items, "a"), edits=Edits.REPLACE
    )
    clock[0] += commands.EDITABLE_FOR + 1
    await answer(
        context_of("/add", at=RUNNING + 1), adding(items, "b"), edits=Edits.REPLACE
    )
    assert list(commands.done) == [(ALICE, RUNNING + 1)]
    # And so many at most
    monkeypatch.setattr(commands, "MAX_DONE", 1)
    await answer(
        context_of("/add", at=RUNNING + 2), adding(items, "c"), edits=Edits.REPLACE
    )
    assert list(commands.done) == [(ALICE, RUNNING + 2)]


async def test_a_timers_commands_keep_nothing(replies: Replies) -> None:
    token = collected.set([])
    try:
        await answer(
            context_of("/add", at=RUNNING), lambda: "Added", edits=Edits.REPLACE
        )
    finally:
        collected.reset(token)
    assert commands.done == {}


async def test_the_log_says_what_and_where_not_who(
    replies: Replies, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, "nejomibot")
    await answer(context_of("/allow +46700000002"), lambda: "Allowed")
    assert "Received /allow in a direct chat" in caplog.text
    assert "+4670000000" not in caplog.text
    caplog.clear()
    token = collected.set([])
    try:
        await answer(context_of("/weather"), lambda: "Sunny")
    finally:
        collected.reset(token)
    assert "Received /weather for a timer, /run or a special" in caplog.text
