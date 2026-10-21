from typing import Any

import pytest
from helpers import (
    ALICE,
    ALICE_ID,
    BOB,
    BOB_ID,
    CAROL_ID,
    DAVE_ID,
    EDIT_FROM_BEFORE,
    GROUP,
    ME,
    FakeApi,
)
from signalbot import (
    DataMessage,
    DataMessageContext,
    EditMessage,
    SendMessage,
    SignalBot,
)

from nejomibot import access, commands, contacts
from nejomibot.access import ADMINS_HEADER, Entry, admin_list
from nejomibot.admins import Admin, Admins
from nejomibot.config import get_settings
from nejomibot.timers import people

ADMIN = "+46700000009"  # in the config
CAROL = "+46700000003"


class Chat:
    """A direct chat with the bot, and its replies."""

    def __init__(self, bot: SignalBot) -> None:
        self.bot = bot
        self.replies: list[str] = []

    async def send(
        self, text: str, *, sender: str = ADMIN, edit: bool = False, at: int = 2
    ) -> None:
        """Send the text, at at, in ms; with edit, as an edit of what was."""
        fields: dict[str, Any] = {
            "server_delivered_timestamp": 0,
            "server_received_timestamp": 0,
            "timestamp": at + 1 if edit else at,
            "source_number": sender if sender.startswith("+") else None,
            "source_uuid": None if sender.startswith("+") else sender,
            "text": text,
        }
        message = (
            EditMessage(**fields, target_sent_timestamp=at)
            if edit
            else DataMessage(**fields)
        )
        context = DataMessageContext(self.bot, message)
        for handler in (Admins(), Admin()):
            await handler.handle_data_message(context)


@pytest.fixture
async def chat(bot: SignalBot, monkeypatch: pytest.MonkeyPatch) -> Chat:
    """ADMIN is the config's admin, and Alice is on the allowed list."""
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()
    get_settings().allowed_file.write_text(f"{ALICE}\n")
    chat = Chat(bot)

    async def reply(_: DataMessageContext, message: SendMessage) -> None:
        chat.replies.append(message.text or "")

    async def mark_read(_: DataMessageContext) -> None:
        pass

    monkeypatch.setattr(commands, "reply", reply)
    monkeypatch.setattr(commands, "mark_read", mark_read)
    return chat


def added() -> list[str]:
    return [entry.id for entry in admin_list.reread().entries]


async def test_admins(chat: Chat) -> None:
    admin_list.reread().add(Entry(BOB_ID, "Bob"))
    with get_settings().admins_file.open("a") as f:
        # By hand, but by Signal ID only: a phone number can change hands
        f.write(f"{GROUP}\n{CAROL}\n")
    await chat.send("/admins")
    assert chat.replies[-1].splitlines() == [
        "👑 **Admins (2):**",
        f"👤 {ADMIN} · in the config",
        # By the name signal-cli has for him, with the number it knows
        f"1 👤 Bob Berg ({BOB})",
        "",
        "/admin add <who> adds one, /admin remove <n> removes one; only the "
        "admins in the config can.",
        "⚠️ The file has 2 lines the bot can't read, and leaves as they are: "
        f"{GROUP} / {CAROL}",
    ]


@pytest.mark.parametrize(
    ("who", "answer", "kept"),
    [
        # By Signal ID, however they're given
        (BOB, "👑 Bob Berg is an admin now, and may use every command.", BOB_ID),
        ("bob berg", "👑 Bob Berg is an admin now, and may use every command.", BOB_ID),
        (
            "CA401000",
            f"👑 {CAROL_ID} is an admin now, and may use every command.",
            CAROL_ID,
        ),
        # A Signal ID the bot doesn't know yet, as it is
        (
            DAVE_ID.upper(),
            f"👑 {DAVE_ID} is an admin now, and may use every command.",
            DAVE_ID,
        ),
    ],
)
async def test_add(chat: Chat, who: str, answer: str, kept: str) -> None:
    await chat.send(f"/admin add {who}")
    assert chat.replies == [answer]
    assert added() == [kept]
    assert get_settings().admins_file.read_text().splitlines()[:4] == list(
        ADMINS_HEADER
    )


async def test_add_by_their_number_in_contacts(chat: Chat) -> None:
    contacts.shown[ADMIN] = [(ALICE, None), (BOB, BOB_ID)]
    await chat.send("/admin add 2")
    assert chat.replies == ["👑 Bob Berg is an admin now, and may use every command."]
    assert added() == [BOB_ID]


@pytest.mark.parametrize(
    ("who", "answer"),
    [
        ("", "/admin add <who>: make someone an admin"),
        (ADMIN, f"{ADMIN} is an admin in the config already."),
        (ME, "That's the bot itself."),
        ("Familjen", "Nobody called Familjen in /contacts."),
        (GROUP, "Familjen is a group: admins are people."),
        ("1", "Which one? Send /contacts first, for their numbers."),
        # A phone number nobody the bot knows has: no Signal ID to keep
        (
            CAROL,
            f"The bot doesn't know the Signal ID of {CAROL} yet, by which admins "
            "are kept: once they've written to it, it does.",
        ),
    ],
)
async def test_add_refuses(chat: Chat, who: str, answer: str) -> None:
    await chat.send(f"/admin add {who}")
    assert chat.replies[-1].startswith(answer)
    assert added() == []


async def test_a_config_admin_by_either_id(
    chat: Chat, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The config has Alice's phone number; she's given by her name
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}", "{ALICE}"]')
    get_settings.cache_clear()
    await chat.send("/admin add alice")
    assert chat.replies == ["Alice is an admin in the config already."]
    assert added() == []


async def test_add_twice(chat: Chat) -> None:
    await chat.send(f"/admin add {BOB}")
    await chat.send("/admin add Bob Berg")
    assert chat.replies[-1] == "Bob Berg is an admin already."
    assert added() == [BOB_ID]


@pytest.mark.parametrize("who", ["1", BOB_ID, BOB, "bob berg"])
async def test_remove(chat: Chat, who: str) -> None:
    admin_list.reread().add(Entry(BOB_ID, "Bob"))
    await chat.send(f"/admin remove {who}")
    assert chat.replies == ["🗑️ Bob Berg is no longer an admin."]
    assert added() == []


async def test_remove_says_they_may_still_use_the_everyday_commands(
    chat: Chat,
) -> None:
    # Allowed by phone number, an admin by Signal ID
    admin_list.reread().add(Entry(ALICE_ID, "Alice"))
    await chat.send("/admin remove 1")
    assert chat.replies == [
        "🗑️ Alice is no longer an admin.\n"
        "They're on /allowed, so may still use the everyday commands."
    ]


@pytest.mark.parametrize(
    ("who", "answer"),
    [
        ("", "/admin add <who>: make someone an admin"),
        ("2", "There's no 2 in /admins."),
        (CAROL, f"{CAROL} isn't in /admins."),
        # No one takes away what the config's admins may do
        (ADMIN, f"{ADMIN} is an admin in the config, which no command changes."),
    ],
)
async def test_remove_refuses(chat: Chat, who: str, answer: str) -> None:
    admin_list.reread().add(Entry(BOB_ID, "Bob"))
    await chat.send(f"/admin remove {who}")
    assert chat.replies[-1].startswith(answer)
    assert added() == [BOB_ID]


async def test_only_the_configs_admins_add_and_remove_admins(chat: Chat) -> None:
    admin_list.reread().add(Entry(BOB_ID, "Bob"))
    await chat.send("/admin add CA401000", sender=BOB_ID)
    await chat.send("/admin remove 1", sender=BOB_ID)
    assert chat.replies == ["Only the admins in the config add and remove admins."] * 2
    assert added() == [BOB_ID]
    # But they see who the admins are
    await chat.send("/admins", sender=BOB_ID)
    assert chat.replies[-1].startswith("👑 **Admins (2):**")


async def test_an_edit_takes_the_place_of_what_it_edits(chat: Chat) -> None:
    await chat.send("/admin add CA401000")
    await chat.send(f"/admin add {BOB}", edit=True)
    assert added() == [BOB_ID]
    await chat.send("/admin remove 1", at=10)
    await chat.send("/admin remove 2", at=10, edit=True)
    assert chat.replies[-1] == "There's no 2 in /admins."
    assert added() == [BOB_ID]


async def test_an_edit_of_a_message_from_before_a_start(chat: Chat) -> None:
    await chat.send(f"/admin add {BOB}", edit=True, at=5)
    assert chat.replies == [EDIT_FROM_BEFORE]
    assert added() == []


@pytest.mark.usefixtures("swedish")
async def test_in_swedish(chat: Chat) -> None:
    await chat.send("/admin lägg till Bob Berg")
    await chat.send("/admin ta bort 1")
    assert chat.replies == [
        "👑 Bob Berg är admin nu och får använda alla kommandon.",
        "🗑️ Bob Berg är inte längre admin.",
    ]


# What an admin added may do


def message(sender: str, *, uuid: str | None = None) -> DataMessage:
    return DataMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=1,
        source_number=sender,
        source_uuid=uuid,
        text="/status",
    )


async def test_an_admin_added_is_an_admin(chat: Chat) -> None:
    admin_list.reread().add(Entry(BOB_ID, "Bob"))
    bob = message(BOB, uuid=BOB_ID)
    assert access.is_admin(bob)
    assert access.from_admin(bob)
    assert not access.is_config_admin(bob)
    assert access.is_config_admin(message(ADMIN))
    assert not access.from_admin(message(CAROL))
    assert not access.from_admin(object())
    # The config's first, then those added
    assert access.admins() == [ADMIN, BOB_ID]


async def test_timers_post_to_the_admins_added(chat: Chat) -> None:
    admin_list.reread().add(Entry(BOB_ID, "Bob"))
    assert people() == [ALICE, ADMIN, BOB_ID]


async def test_the_admins_added_are_recipients(chat: Chat, signal_api: FakeApi) -> None:
    admin_list.reread().add(Entry(BOB_ID, "Bob"))
    assert BOB_ID in access.recipients()
