from datetime import UTC, datetime
from typing import Any

import pytest
from aiohttp import web
from helpers import (
    ALICE,
    BOB,
    BOB_ID,
    CAROL_ID,
    DAVE_ID,
    EDIT_FROM_BEFORE,
    GROUP,
    ME,
    FakeApi,
    group_entry,
)
from signalbot import (
    DataMessage,
    DataMessageContext,
    EditMessage,
    SendMessage,
    SignalBot,
)

from nejomibot import access, allowed, commands, contacts
from nejomibot.access import HEADER
from nejomibot.allowed import Allow, Allowed, Disallow
from nejomibot.config import get_settings
from nejomibot.timers import Timekeeper, Timer

ADMIN = "+46700000009"
CAROL = "+46700000003"
FRIENDS = "group.RnJpZW5kcw=="
GONE = "group.Z29uZQ=="


class Chat:
    """An admin's direct chat with the bot, and its replies."""

    def __init__(self, bot: SignalBot) -> None:
        self.bot = bot
        self.replies: list[str] = []

    async def send(self, text: str, *, edit: bool = False, at: int = 2) -> None:
        """Send the text, at at, in ms; with edit, as an edit of what was."""
        fields: dict[str, Any] = {
            "server_delivered_timestamp": 0,
            "server_received_timestamp": 0,
            "timestamp": at + 1 if edit else at,
            "source_number": ADMIN,
            "text": text,
        }
        message = (
            EditMessage(**fields, target_sent_timestamp=at)
            if edit
            else DataMessage(**fields)
        )
        context = DataMessageContext(self.bot, message)
        for handler in (Allowed(), Allow(), Disallow()):
            await handler.handle_data_message(context)


@pytest.fixture
async def chat(
    bot: SignalBot, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> Chat:
    """The bot is in the Familjen and Friends groups, out of Gone, and Alice
    is allowed."""
    signal_api.responses[f"/v1/groups/{ME}"] = [
        group_entry(GROUP, "Familjen"),
        group_entry(FRIENDS, "Friends"),
        group_entry(GONE, "Gone", member=False),
    ]
    await bot.groups.refresh()
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()
    get_settings().allowed_file.write_text("\n".join([*HEADER, ALICE, ""]))
    chat = Chat(bot)

    async def reply(_: DataMessageContext, message: SendMessage) -> None:
        chat.replies.append(message.text or "")

    async def mark_read(_: DataMessageContext) -> None:
        pass

    monkeypatch.setattr(commands, "reply", reply)
    monkeypatch.setattr(commands, "mark_read", mark_read)
    monkeypatch.setattr(allowed, "timekeeper", Timekeeper())
    return chat


def listed() -> list[str]:
    return sorted(access.allowed_list.reread().ids)


async def test_allowed(chat: Chat) -> None:
    access.allowed_list.reread().add(access.Entry(GONE, "Old friends"))
    with get_settings().allowed_file.open("a") as f:
        f.write("not anyone\n")
    await chat.send("/allowed")
    assert chat.replies[-1].splitlines() == [
        "📋 **Who may use the everyday commands (2):**",
        f"1 👤 Alice ({ALICE})",
        "2 👥 Gone (the bot isn't in it)",
        "",
        f"👑 The admins may use every command: {ADMIN}",
        "/allow <who> adds one, /disallow <n> removes one.",
        "⚠️ The file has a line the bot can't read, and leaves as it is: not anyone",
    ]


@pytest.mark.parametrize(
    ("who", "answer", "added"),
    [
        (CAROL, f"✅ {CAROL} may use the everyday commands now.", CAROL),
        ("+46 70-000 00 03", f"✅ {CAROL} may use the everyday commands now.", CAROL),
        ("bob berg", "✅ Bob Berg may use the everyday commands now.", BOB),
        (
            "familjen",
            "✅ Everyone in Familjen may use the everyday commands there now.",
            GROUP,
        ),
        (
            GONE,
            "✅ Everyone in Gone may use the everyday commands there now.\n"
            "The bot isn't in the group: it answers there once added.",
            GONE,
        ),
        # Someone known only by their Signal ID, by its start
        (
            "CA401000",
            f"✅ {CAROL_ID} may use the everyday commands now.",
            CAROL_ID,
        ),
    ],
)
async def test_allow(chat: Chat, who: str, answer: str, added: str) -> None:
    await chat.send(f"/allow {who}")
    assert chat.replies == [answer]
    assert listed() == sorted({ALICE, added})


@pytest.mark.parametrize(
    ("who", "answer"),
    [
        ("", "Send /allow and who:"),
        (ALICE, "Alice may use the everyday commands already."),
        (ADMIN, f"{ADMIN} is an admin, and may use every command: see /admins."),
        (ME, "That's the bot itself."),
        ("carol", "Nobody and no group is called carol.\nSend /allow"),
    ],
)
async def test_allow_refuses(chat: Chat, who: str, answer: str) -> None:
    await chat.send(f"/allow {who}")
    assert chat.replies[-1].startswith(answer)
    assert listed() == [ALICE]


async def test_allow_by_their_number_in_contacts(chat: Chat) -> None:
    await chat.send("/allow 2")
    assert chat.replies == ["Which one? Send /contacts first, for their numbers."]
    contacts.shown[ADMIN] = [(ALICE, None), (BOB, BOB_ID)]
    await chat.send("/allow 2")
    assert chat.replies[-1] == "✅ Bob Berg may use the everyday commands now."
    assert listed() == [ALICE, BOB]


async def test_allow_when_full(chat: Chat, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(access, "MAX_ENTRIES", 1)
    await chat.send(f"/allow {CAROL}")
    assert chat.replies == ["The list is full: 1 at most."]


@pytest.mark.parametrize("who", ["1", ALICE, "alice", "ALICE"])
async def test_disallow(chat: Chat, who: str) -> None:
    await chat.send(f"/disallow {who}")
    assert chat.replies == ["🗑️ Alice may no longer use the everyday commands."]
    assert listed() == []
    assert get_settings().allowed_file.read_text().splitlines() == list(HEADER)


async def test_disallow_says_which_timers_still_post_there(chat: Chat) -> None:
    access.allowed_list.reread().add(access.Entry(GROUP))
    last = datetime(2026, 10, 12, 8, 0, tzinfo=UTC)
    allowed.timekeeper.timers = {
        1: Timer(1, "daily 08:00", [GROUP, ALICE], ["/dailypost"], last),
        2: Timer(2, "every 2h", [ADMIN], ["/ping"], last),
    }
    await chat.send("/disallow Familjen")
    assert chat.replies == [
        "🗑️ Nobody in Familjen may use the everyday commands there now.\n"
        "Timer #1 still posts there: see /timers."
    ]
    assert listed() == [ALICE]


@pytest.mark.parametrize(
    ("who", "answer"),
    [
        ("", "Send /disallow and who:"),
        ("2", "There's no 2 in /allowed."),
        (BOB, f"{BOB} isn't in /allowed."),
        (ADMIN, f"{ADMIN} is an admin, and may use every command: see /admins."),
    ],
)
async def test_disallow_refuses(chat: Chat, who: str, answer: str) -> None:
    await chat.send(f"/disallow {who}")
    assert chat.replies[-1].startswith(answer)
    assert listed() == [ALICE]


async def test_an_admin_put_on_the_list_by_hand_stays_an_admin(
    chat: Chat,
) -> None:
    access.allowed_list.reread().add(access.Entry(ADMIN, "Admin"))
    await chat.send(f"/disallow {ADMIN}")
    assert chat.replies == [
        "🗑️ Admin may no longer use the everyday commands.\n"
        "They're an admin, so may still use them."
    ]


async def test_an_edit_takes_the_place_of_what_it_edits(chat: Chat) -> None:
    await chat.send(f"/allow {CAROL}")
    await chat.send(f"/allow {BOB}", edit=True)
    assert listed() == [ALICE, BOB]
    # Alice back where she was, so 2 is what it was
    await chat.send("/disallow 1")
    await chat.send("/disallow 2", edit=True)
    assert listed() == [ALICE]


async def test_an_edit_of_a_message_from_before_a_start(chat: Chat) -> None:
    await chat.send(f"/allow {CAROL}", edit=True, at=5)
    await chat.send(f"/disallow {ALICE}", edit=True, at=6)
    assert chat.replies == [EDIT_FROM_BEFORE] * 2
    assert listed() == [ALICE]


async def test_an_edit_lists_again(chat: Chat) -> None:
    # It only lists, unlike /allow and /disallow
    await chat.send("/allowed")
    await chat.send("/allowed", edit=True)
    assert len(chat.replies) == 2 and chat.replies[0] == chat.replies[1]


@pytest.mark.usefixtures("swedish")
async def test_in_swedish(chat: Chat) -> None:
    await chat.send(f"/tillåt {CAROL}")
    await chat.send("/neka 1")
    await chat.send("/tillåtna")
    assert chat.replies[:2] == [
        f"✅ {CAROL} får använda vardagskommandona nu.",
        "🗑️ Alice får inte längre använda vardagskommandona.",
    ]
    assert chat.replies[2].startswith(
        "📋 **Vilka som får använda vardagskommandona (1):**\n"
    )


async def test_allow_looks_up_a_number_signal_cli_doesnt_know(
    chat: Chat, signal_api: FakeApi
) -> None:
    # Dave doesn't share his number: Signal's contact discovery says whose it
    # is, and signal-cli knows from then on
    dave = "+46700000004"

    async def look_up(request: web.Request) -> web.Response:
        everyone = signal_api.responses[f"/v1/contacts/{ME}?all"]
        everyone.append({"number": dave, "uuid": DAVE_ID, "name": "Dave"})
        return web.json_response([{"number": dave, "registered": True}])

    signal_api.route("GET", f"/v1/search/{ME}", look_up)
    await chat.send(f"/allow {dave}")
    assert chat.replies == ["✅ Dave may use the everyday commands now."]
    assert f"{dave}  # Dave" in get_settings().allowed_file.read_text().splitlines()
