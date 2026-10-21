from collections.abc import Callable
from typing import Any

import pytest
from aiohttp import web
from helpers import ALICE, GROUP, ME, FakeApi
from signalbot import (
    DataMessage,
    DataMessageContext,
    EditMessage,
    SendMessage,
    SignalBot,
)

from nejomibot import commands, messages, relay
from nejomibot.access import HEADER
from nejomibot.config import get_settings
from nejomibot.messages import Outbox, collected
from nejomibot.ping import Ping
from nejomibot.relay import Msg, Run, parse
from nejomibot.timers import Timekeeper

ADMIN = "+46700000009"


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        ("/msg 1,2 Hello!", ([1, 2], "Hello!")),
        ("/msg 2 Two lines\nof text ", ([2], "Two lines\nof text")),
        ("/run 1 /weather; /photo", ([1], "/weather; /photo")),
        ("/msg 1,2", None),
        ("/msg Hello", None),
        # The chats are one word: this isn't "2 Hello" to chat 1
        ("/msg 1, 2 Hello", None),
        ("/msg 1,,2 Hello", None),
    ],
)
def test_parse(text: str, parsed: tuple[list[int], str] | None) -> None:
    assert parse(text) == parsed


class Chat:
    """An admin's direct chat with the bot, and its replies."""

    def __init__(self, bot: SignalBot) -> None:
        self.bot = bot
        self.replies: list[str] = []

    async def send(self, text: str, *, edit: bool = False) -> None:
        fields: dict[str, Any] = {
            "server_delivered_timestamp": 0,
            "server_received_timestamp": 0,
            "timestamp": 2,
            "source_number": ADMIN,
            "text": text,
        }
        message = (
            EditMessage(**fields, target_sent_timestamp=1)
            if edit
            else DataMessage(**fields)
        )
        context = DataMessageContext(self.bot, message)
        for handler in (Msg(), Run()):
            await handler.handle_data_message(context)


@pytest.fixture
async def chat(
    bot: SignalBot, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> Chat:
    """/chats has 1 Familjen, 2 Alice, who is allowed, and 3 the admin. The
    bot sends through signalbot, and runs commands as timers do, with /ping
    alone."""
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()
    get_settings().allowed_file.write_text("\n".join([*HEADER, ALICE, ""]))
    outbox = Outbox()
    outbox.start(bot)
    monkeypatch.setattr(messages, "outbox", outbox)
    keeper = Timekeeper()
    keeper.start(bot, [Ping()])
    monkeypatch.setattr(relay, "timekeeper", keeper)
    chat = Chat(bot)

    async def reply(context: DataMessageContext, message: SendMessage) -> None:
        if collected.get() is None:
            chat.replies.append(message.text or "")
        else:  # what /run collects
            await messages.reply(context, message)

    monkeypatch.setattr(commands, "reply", reply)
    return chat


def posted(signal_api: FakeApi) -> list[tuple[list[str], str]]:
    return [
        (sent["recipients"], sent["message"])
        for sent in signal_api.bodies("POST", "/v2/send")
    ]


async def test_msg(chat: Chat, signal_api: FakeApi) -> None:
    await chat.send("/msg 1,2 Hello!\nFrom the bot")
    assert posted(signal_api) == [
        ([GROUP], "Hello!\nFrom the bot"),
        ([ALICE], "Hello!\nFrom the bot"),
    ]
    assert chat.replies == [f"✉️ Sent to Familjen, Alice ({ALICE})."]


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("/msg", "Send /msg <chats> <text>, e.g. /msg 1,2 Hello!"),
        ("/msg 1", "Send /msg <chats> <text>"),
        ("/msg 9 Hello", "There's no chat 9: /chats numbers them."),
        ("/run 1", "Send /run <chats> <commands>, e.g. /run 1 /weather; /photo."),
        ("/run 1 ping", "Commands start with /, unlike ping."),
        ("/run 1 /frobnicate", "/frobnicate isn't a command the bot knows."),
        (
            "/run 1 /timer add 08:00 /ping",
            "Timers, specials and /run can't run /timer.",
        ),
        ("/run 1 /msg 2 Hello", "Timers, specials and /run can't run /msg."),
        ("/run 4 /ping", "There's no chat 4: /chats numbers them."),
    ],
)
async def test_refused(chat: Chat, signal_api: FakeApi, text: str, answer: str) -> None:
    await chat.send(text)
    assert [reply.startswith(answer) for reply in chat.replies] == [True]
    assert posted(signal_api) == []


async def test_run_posts_the_answers(chat: Chat, signal_api: FakeApi) -> None:
    await chat.send("/run 2,1 /ping")
    [(to_alice, pong), (to_group, pong_again)] = posted(signal_api)
    assert (to_alice, to_group) == ([ALICE], [GROUP])
    assert pong.startswith("pong!") and pong == pong_again
    assert chat.replies == [f"▶️ Posted the answers to Alice ({ALICE}), Familjen."]
    # A read receipt for /run, but none for the /ping it runs: nobody sent it
    assert len(signal_api.bodies("POST", f"/v1/receipts/{ME}")) == 1


async def test_run_here_speaks_for_itself(chat: Chat, signal_api: FakeApi) -> None:
    await chat.send("/run 3 /ping")
    assert [to for to, _text in posted(signal_api)] == [[ADMIN]]
    assert chat.replies == []


async def test_edits_post_nothing(chat: Chat, signal_api: FakeApi) -> None:
    await chat.send("/msg 1 Hello", edit=True)
    await chat.send("/run 1 /ping", edit=True)
    # What they posted has gone out, so they say an edit isn't run
    assert chat.replies == [
        f"✏️ An edit of {command} isn't run, as what it did can't be undone. "
        "Send it as a new message instead."
        for command in ("/msg", "/run")
    ]
    assert signal_api.requests == []


@pytest.mark.usefixtures("swedish")
async def test_in_swedish(chat: Chat, signal_api: FakeApi) -> None:
    await chat.send("/skicka 1 Hej!")
    await chat.send("/kör 2 /ping")
    assert [to for to, _text in posted(signal_api)] == [[GROUP], [ALICE]]
    assert chat.replies[0] == "✉️ Skickat till Familjen."


def failing_for(code: int, recipient: str) -> Callable[[web.Request], Any]:
    """Sends, but answers with the code for the recipient."""

    async def send(request: web.Request) -> web.Response:
        body = await request.json()
        if body["recipients"] == [recipient]:
            return web.json_response({"error": "failed"}, status=code)
        return web.json_response([{"timestamp": "1"}], status=201)

    return send


async def test_msg_says_where_it_only_waits(chat: Chat, signal_api: FakeApi) -> None:
    # Surely not sent to Alice: tried again later
    signal_api.route("POST", "/v2/send", failing_for(400, ALICE))
    await chat.send("/msg 1,2 Hello!")
    assert chat.replies == [
        "✉️ Sent to Familjen.\n"
        f"⏳ Not sent yet to Alice ({ALICE}): tried again for 3 hours."
    ]


async def test_run_says_where_it_may_not_have_arrived(
    chat: Chat, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def hang_up(request: web.Request) -> web.Response:
        body = await request.json()
        if body["recipients"] == [GROUP]:
            assert request.transport is not None
            request.transport.close()
        return web.json_response([{"timestamp": "1"}], status=201)

    signal_api.route("POST", "/v2/send", hang_up)
    await chat.send("/run 1,2 /ping")
    assert chat.replies == [
        f"▶️ Posted the answers to Alice ({ALICE}).\n⚠️ May not have reached Familjen."
    ]
