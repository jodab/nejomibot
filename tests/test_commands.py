import logging
from typing import Any, cast

import pytest
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
    Command,
    Handler,
    aliases,
    answer,
    argument,
    canonical,
    known,
)
from nejomibot.config import get_settings
from nejomibot.messages import collected


@pytest.fixture
def pic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "NEJOMIBOT_ALIASES", '{"/photo": ["/pic", "Pic"], "/fortune": ["/f"]}'
    )
    get_settings.cache_clear()


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


def test_no_aliases_but_the_languages() -> None:
    assert aliases() == {}
    assert canonical("/väder") == "/väder"


@pytest.mark.usefixtures("swedish")
def test_the_settings_win_over_the_language(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["/tid", "/bilden"]}')
    get_settings.cache_clear()
    assert canonical("/tid") == "/photo"
    assert canonical("/väder") == "/weather"


class Seen(Handler):
    """Remembers the texts it was given, and the commands they were."""

    commands = (Command("/photo"), Command("/cache", hidden=("/stash",)))

    def __init__(self) -> None:
        self.seen: list[tuple[str | None, str]] = []

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        self.seen.append((context.message.text, command.name))


class SeenWithMore(Seen):
    commands = (Command("/fortune", more=True),)


def context_of(text: str | None, *, edit: bool = False) -> DataMessageContext:
    fields: dict[str, Any] = {
        "server_delivered_timestamp": 0,
        "server_received_timestamp": 0,
        "timestamp": 0,
        "source_number": "+46700000001",
        "text": text,
    }
    message = (
        EditMessage(**fields, target_sent_timestamp=1)
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


async def test_a_command_by_a_name_it_has_had_all_along() -> None:
    handler = Seen()
    await handler.handle_data_message(context_of("/STASH"))
    assert handler.seen == [("/STASH", "/cache")]


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
    assert known("/fortune startrek") == Command("/fortune", more=True)
    msg = known("/msg 1 Hi")
    assert msg is not None and not msg.timers
    assert known("/weather now") is None
    assert known("/frobnicate") is None


def test_every_name_starts_with_a_slash() -> None:
    # Plain words are for the config's aliases alone
    for handler in commands.handlers():
        for command in handler.commands:
            for name in (command.name, *command.hidden):
                assert name.startswith("/"), name


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


async def test_answer_lets_an_edit_be(replies: Replies) -> None:
    await answer(context_of("/allow Bob", edit=True), lambda: "Allowed", edits=False)
    assert replies.done == replies.sent == []
    await answer(context_of("/weather", edit=True), lambda: "Sunny")
    assert [m.text for m in replies.sent] == ["Sunny"]


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
