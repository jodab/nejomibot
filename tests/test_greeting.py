import logging
from typing import Any

import pytest
from aiohttp import web
from helpers import ALICE, ALICE_ID, BOB, GROUP, ME, FakeApi
from signalbot import (
    Attachment,
    DataMessage,
    DataMessageContext,
    EditMessage,
    GroupInfo,
    SendMessage,
    SignalBot,
)

from nejomibot import access, greeting
from nejomibot.access import Entry
from nejomibot.config import get_settings
from nejomibot.greeting import AGAIN, Greeter

EVE = "+46700000005"  # a stranger
PHOTO = Attachment.model_validate(
    {"contentType": "image/jpeg", "id": "x", "isVoiceNote": False}
)
# The bot, and Bob, the admin, by their profile names
GREETING = (
    "Hi, I'm Mybot, a bot. Try /help for a list of commands. "
    "Contact Bob Berg for more information."
)


def message(text: str | None, sender: str = ALICE, **fields: Any) -> DataMessage:
    """A message to the bot in a direct chat."""
    return DataMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=1,
        source_number=sender,
        source_uuid=ALICE_ID if sender == ALICE else None,
        text=text,
        **fields,
    )


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Greeted:
    """What a greeter of the test's own sends, on a clock of the test's own."""

    def __init__(self, bot: SignalBot, monkeypatch: pytest.MonkeyPatch) -> None:
        self.bot = bot
        self.clock = Clock()
        self.greeter = Greeter(self.clock)
        self.sent: list[str] = []

        async def nothing(context: DataMessageContext) -> None:
            pass

        monkeypatch.setattr(greeting, "reply", self.reply)
        monkeypatch.setattr(greeting, "mark_read", nothing)

    async def reply(self, context: DataMessageContext, message: SendMessage) -> None:
        self.sent.append(message.text or "")

    async def by(self, message: DataMessage) -> list[str]:
        self.sent.clear()
        await self.greeter.handle_data_message(DataMessageContext(self.bot, message))
        return self.sent


@pytest.fixture
def greeted(bot: SignalBot, monkeypatch: pytest.MonkeyPatch) -> Greeted:
    """Bob is the admin, Alice and the group are on the allowed list, and
    pic is another name for /photo."""
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{BOB}"]')
    monkeypatch.setenv("NEJOMIBOT_ALIASES", '{"/photo": ["pic"]}')
    get_settings.cache_clear()
    access.allowed_list.reread().add(Entry(ALICE))
    access.allowed_list.reread().add(Entry(GROUP))
    return Greeted(bot, monkeypatch)


async def test_greets_the_allowed_list_once_a_day(
    greeted: Greeted, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG, "nejomibot")
    assert await greeted.by(message("Hej!")) == [GREETING]
    # Not again that day, whatever they write
    assert await greeted.by(message("Thanks!")) == []
    greeted.clock.now += AGAIN - 1
    assert await greeted.by(message("Hej igen")) == []
    greeted.clock.now += 1
    assert await greeted.by(message("Good morning")) == [GREETING]
    # Who, only at DEBUG
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.INFO] == [
        "Greeted someone in a direct chat"
    ] * 2


@pytest.mark.parametrize(
    "sent",
    [
        message(None, attachments=[PHOTO]),
        message("/weathr"),  # no command, so the greeting points to /help
    ],
)
async def test_greets_what_isnt_a_command(greeted: Greeted, sent: DataMessage) -> None:
    assert await greeted.by(sent) == [GREETING]


@pytest.mark.parametrize(
    "text",
    [
        "/weather",
        "/HELP",  # in any case
        "/fortune startrek",  # with more after it
        "/time",  # the bot's own alias, for /info
        "pic",  # the config's
        "/status",  # an admin command, which the bot doesn't answer her
        "/dailypost",
        "/bins",  # one of the admins' own specials
    ],
)
async def test_commands_are_answered_as_ever_never_greeted(
    greeted: Greeted, text: str
) -> None:
    get_settings().specials_file.write_text("/bins | The bins!\n")
    assert await greeted.by(message(text)) == []
    # Nor do they use up the day's greeting
    assert await greeted.by(message("Hej!")) == [GREETING]


@pytest.mark.parametrize(
    "sent",
    [
        message("Hej!", sender=BOB),  # the admin
        message("Hej!", sender=EVE),  # a stranger
        # In a group on the allowed list
        message(
            "Hej!",
            group_info=GroupInfo.model_validate(
                {"groupId": "internal-Familjen", "revision": 1}
            ),
        ),
        EditMessage(**message("Hej!").model_dump(), target_sent_timestamp=0),
        message(None),  # as Signal's note of a new disappearing time
    ],
)
async def test_greets_nobody_else(greeted: Greeted, sent: DataMessage) -> None:
    assert await greeted.by(sent) == []


async def test_does_without_the_names_it_cant_have(
    greeted: Greeted, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def down(request: web.Request) -> web.Response:
        return web.json_response({"error": "down"}, status=500)

    signal_api.route("GET", f"/v1/contacts/{ME}", down)
    without = (
        "Hi, I'm a bot. Try /help for a list of commands. "
        "Contact the bot's admin for more information."
    )
    assert await greeting.greeting(greeted.bot) == without
    # Nor without a name for the bot, or admins
    del signal_api.routes["GET", f"/v1/contacts/{ME}"]
    me = signal_api.responses[f"/v1/contacts/{ME}?all"][0]
    me.update(username="", profile={"given_name": "", "lastname": ""})
    monkeypatch.setenv("NEJOMIBOT_ADMINS", "[]")
    get_settings.cache_clear()
    assert await greeting.greeting(greeted.bot) == without


@pytest.mark.usefixtures("swedish")
async def test_in_swedish(greeted: Greeted) -> None:
    assert await greeted.by(message("/hjälp")) == []
    assert await greeted.by(message("Hej!")) == [
        "Hej, jag är Mybot, en bot. Prova /hjälp för en lista med kommandon. "
        "Kontakta Bob Berg för mer information."
    ]
