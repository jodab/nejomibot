import asyncio
import base64
import socket
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from aiohttp import web
from helpers import ALICE, ALICE_ID, GROUP, FakeApi, message_from
from signalbot import Attachment, SignalBot

from nejomibot import chat_cli, incoming, messages, relay, terminal
from nejomibot.access import HEADER, Names
from nejomibot.chat_cli import File, Refused
from nejomibot.config import get_settings
from nejomibot.incoming import Incoming, Received
from nejomibot.messages import Outbox
from nejomibot.ping import Ping
from nejomibot.relay import Msg, Run
from nejomibot.terminal import Recent
from nejomibot.timers import Timekeeper

ADMIN = "+46700000009"
JPEG = b"\xff\xd8\xff\xe0" + bytes(100)


@pytest.fixture
async def chat(
    bot: SignalBot, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[Recent]:
    """The bot answers nejomibot-chat, its first admin ADMIN, with /chats as 1
    Familjen, 2 Alice, who is allowed, and 3 the admin. It sends through
    signalbot. The messages the bot received, which start with none."""
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()
    get_settings().allowed_file.write_text("\n".join([*HEADER, ALICE, ""]))
    outbox = Outbox()
    outbox.start(bot)
    monkeypatch.setattr(messages, "outbox", outbox)
    keeper = Timekeeper()
    keeper.start(bot, [Ping(), Msg(), Run(), Incoming()])
    monkeypatch.setattr(terminal, "timekeeper", keeper)
    monkeypatch.setattr(relay, "timekeeper", keeper)
    recent = Recent()
    monkeypatch.setattr(terminal, "recent", recent)

    async def ready() -> None:
        pass

    monkeypatch.setattr(bot, "wait_until_ready", ready)
    listener = terminal.Listener()
    monkeypatch.setattr(terminal, "listener", listener)
    await listener.serve(bot)
    yield recent
    await listener.stop()


async def ask(
    request: dict[str, Any], files: Sequence[File] = ()
) -> list[dict[str, Any]]:
    """What the bot says to nejomibot-chat's request, as it asks it."""
    return await asyncio.to_thread(lambda: list(chat_cli.exchange(request, files)))


def posted(signal_api: FakeApi) -> list[dict[str, Any]]:
    return signal_api.bodies("POST", "/v2/send")


@pytest.mark.usefixtures("chat")
async def test_answers_come_to_the_terminal(signal_api: FakeApi) -> None:
    [answer] = await ask({"text": "/ping"})
    assert answer["text"].startswith("pong!")
    assert (answer["styles"], answer["files"]) == ([], [])
    # None to Signal: no answer, nor a read receipt or typing
    assert signal_api.requests == []


@pytest.mark.usefixtures("chat")
async def test_no_answer(signal_api: FakeApi) -> None:
    assert await ask({"text": "Hello"}) == []


@pytest.mark.usefixtures("chat")
async def test_lists_number_as_in_the_direct_chat() -> None:
    # Unlike a timer's, the list is the admin's, for /incoming 1 next
    await ask({"text": "/incoming"})
    assert ADMIN in incoming.shown


@pytest.mark.usefixtures("chat")
async def test_msg_posts_the_files(signal_api: FakeApi) -> None:
    [answer] = await ask({"text": "/msg 1 Look!", "attachments": [
        File("a.jpg", JPEG).header
    ]}, [File("a.jpg", JPEG)])  # fmt: skip
    assert answer["text"] == "✉️ Sent to Familjen."
    [sent] = posted(signal_api)
    assert (sent["recipients"], sent["message"]) == ([GROUP], "Look!")
    assert sent["base64_attachments"] == [
        f"data:image/jpeg;filename=a.jpg;base64,{base64.b64encode(JPEG).decode()}"
    ]


@pytest.mark.usefixtures("chat")
async def test_msg_posts_files_without_a_text(signal_api: FakeApi) -> None:
    # From standard input, without a name
    files = [File("", JPEG), File("b.png", b"\x89PNG\r\n\x1a\n")]
    request = {"text": "/msg 2", "attachments": [file.header for file in files]}
    [answer] = await ask(request, files)
    assert answer["text"] == f"✉️ Sent to Alice ({ALICE})."
    [sent] = posted(signal_api)
    assert sent["message"] == ""  # as signalbot sends no text
    assert [url.partition(",")[0] for url in sent["base64_attachments"]] == [
        "data:image/jpeg;base64",
        "data:image/png;filename=b.png;base64",
    ]


@pytest.mark.usefixtures("chat")
async def test_msg_needs_a_text_or_files(signal_api: FakeApi) -> None:
    [answer] = await ask({"text": "/msg 1"})
    assert answer["text"].startswith("Send /msg <chats> <text>")
    assert posted(signal_api) == []


@pytest.mark.usefixtures("chat")
async def test_files_over_the_limit(signal_api: FakeApi) -> None:
    big = {"filename": "big.mp4", "size": chat_cli.MAX_ATTACHED + 1}
    with pytest.raises(Refused, match="over 25 MB"):
        await ask({"text": "/msg 1", "attachments": [big]})
    assert posted(signal_api) == []


@pytest.mark.usefixtures("chat")
@pytest.mark.parametrize("line", [b"Hello\n", b'{"text": 1}\n', b'{"nope": 1}\n'])
async def test_not_a_request(line: bytes) -> None:
    def send() -> bytes:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.connect(chat_cli.SOCKET)
            connection.sendall(line)
            connection.shutdown(socket.SHUT_WR)  # all sent, as nejomibot-chat says
            return connection.makefile("rb").read()

    assert b"no request of nejomibot-chat" in await asyncio.to_thread(send)


@pytest.mark.usefixtures("chat")
async def test_only_for_the_bots_user(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(terminal.os, "geteuid", lambda: 4242)
    with pytest.raises(Refused, match="only its own user, and root"):
        await ask({"text": "/ping"})
    # And why, with files after the request, which the bot then reads, as
    # closing before would reset the connection
    files = [File("big.jpg", bytes(1_000_000))]
    with pytest.raises(Refused, match="only its own user, and root"):
        await ask({"text": "/msg 1", "attachments": [files[0].header]}, files)


def test_shown_without_marks_and_with_names() -> None:
    names = Names()
    names[ALICE_ID] = "Alice"
    said = terminal.shown(f"**Hi** <@{ALICE_ID}>, \\*", names, styled=True)
    assert said == {
        "text": "Hi @Alice, *",
        "styles": [{"start": 0, "length": 2, "style": "BOLD"}],
    }
    plain = terminal.shown(f"**Hi** <@{ALICE_ID}>", names, styled=False)
    assert plain == {"text": "**Hi** @Alice", "styles": []}


def test_sent_files() -> None:
    data = base64.b64encode(JPEG).decode()
    assert terminal.sent_file(data) == {
        "content_type": "image/jpeg",
        "filename": "",
        "size": len(JPEG),
        "base64": data,
    }
    url = terminal.sent_file(f"data:image/png;filename=a.png;base64,{data}")
    assert (url["content_type"], url["filename"], url["base64"]) == (
        "image/png",
        "a.png",
        data,
    )


def test_attachments_get_safe_types_and_names() -> None:
    attached = terminal.Attached(filename="a;b,c/d.jpg", content_type="x y", size=1)
    made = terminal.attachment(attached, b"x")
    assert made.content_type == chat_cli.UNKNOWN
    assert made.remote_filename == "a_b_c_d.jpg"
    assert (made.size, made.base64_content) == (1, "eA==")


# The messages the bot received


async def test_recent_in_every_chat(chat: Recent) -> None:
    chat.keep(message_from(ALICE, "Hej **alla**", in_group=True), GROUP)
    chat.keep(message_from(ADMIN, "From the admin", timestamp=2))
    first, second = await ask({"recent": 10})
    assert (first["chat"], first["chat_name"], first["sender_name"]) == (
        GROUP,
        "Familjen",
        f"Alice ({ALICE})",
    )
    assert (first["text"], first["edited"]) == ("Hej **alla**", False)
    assert (second["chat"], second["text"]) == (None, "From the admin")
    # The latest one alone
    [latest] = await ask({"recent": 1})
    assert latest["text"] == "From the admin"


class Followers(set[asyncio.Queue[Received]]):
    """Those who follow the messages, and an event as they come and go."""

    def __init__(self) -> None:
        super().__init__()
        self.changed = asyncio.Event()

    def add(self, element: asyncio.Queue[Received]) -> None:
        super().add(element)
        self.changed.set()

    def discard(self, element: object) -> None:
        super().discard(element)
        self.changed.set()

    async def wait(self) -> None:
        async with asyncio.timeout(5):
            await self.changed.wait()
        self.changed.clear()


async def test_follow(chat: Recent) -> None:
    chat.followers = followers = Followers()
    following = chat_cli.exchange({"follow": True}, timeout=10)
    first = asyncio.create_task(asyncio.to_thread(next, following))
    await followers.wait()
    chat.keep(message_from(ALICE, "Hej!", edit=True))
    said = await first
    assert (said["text"], said["edited"]) == ("Hej!", True)
    following.close()  # as nejomibot-chat stops
    await followers.wait()
    assert not followers


async def test_follow_ends_as_the_bot_stops(chat: Recent) -> None:
    chat.followers = followers = Followers()
    following = asyncio.to_thread(chat_cli.received, chat_cli.Output(), None, True)
    stopped = asyncio.create_task(following)
    await followers.wait()
    await terminal.listener.stop()
    with pytest.raises(Refused, match="The bot has stopped"):
        await stopped


def photo(attachment_id: str, size: int = 4) -> Attachment:
    return Attachment.model_validate(
        {
            "contentType": "image/jpeg",
            "filename": "IMG_1.jpg",
            "id": attachment_id,
            "size": size,
            "isVoiceNote": False,
        }
    )


async def test_attachments_only_when_wanted(
    chat: Recent, monkeypatch: pytest.MonkeyPatch
) -> None:
    message = message_from(ALICE, "Look").model_copy(
        update={"attachments": [photo("p1")]}
    )
    chat.keep(message)
    [said] = await ask({"recent": 1, "files": True})
    assert (said["attachments"], said["files"]) == (1, [])
    monkeypatch.setenv("NEJOMIBOT_RECEIVED_ATTACHMENTS", "true")
    get_settings.cache_clear()
    chat.keep(message)
    [said] = await ask({"recent": 1})
    assert said["files"] == [
        {"content_type": "image/jpeg", "filename": "IMG_1.jpg", "size": 4}
    ]


async def test_attachments_fetched_for_save(
    chat: Recent, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("NEJOMIBOT_RECEIVED_ATTACHMENTS", "true")
    get_settings.cache_clear()

    async def kept(request: web.Request) -> web.Response:
        return web.Response(body=b"jpeg")

    signal_api.route("GET", "/v1/attachments/p1", kept)
    big = photo("p3", chat_cli.MAX_ATTACHED + 1)
    attachments = [photo("p1"), photo("p2"), big]
    chat.keep(message_from(ALICE, "").model_copy(update={"attachments": attachments}))
    [said] = await ask({"recent": 1, "files": True})
    one, two, three = said["files"]
    assert one["base64"] == base64.b64encode(b"jpeg").decode()
    assert two["missing"] and three["too_big"]
    # Not fetched: too big to go through the bot's memory
    assert signal_api.bodies("GET", "/v1/attachments/p3") == []
