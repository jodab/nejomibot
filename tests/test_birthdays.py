from datetime import date

import pytest
from aiohttp import web
from helpers import ALICE, ALICE_ID, BOB, GROUP, ME, FakeApi, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import birthdays
from nejomibot.birthdays import (
    BIRTHDAY,
    NAMEDAY,
    Birthday,
    Birthdays,
    Occasion,
    greetings,
    parse_line,
)
from nejomibot.commands import Handler
from nejomibot.config import get_settings

ADMIN = "+46700000009"
FRIENDS = "group.RnJpZW5kcw=="  # a group the bot isn't in


@pytest.fixture(autouse=True)
def admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}"]')
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def today(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(birthdays, "today", lambda: date(2026, 10, 19))


async def ask(
    bot: SignalBot,
    answers: list[SendMessage],
    text: str,
    sender: str = ADMIN,
    *,
    in_group: bool = False,
    edit: bool = False,
) -> str:
    """What the bot answers the message, as text; with edit, an edit of the
    one before."""
    answers.clear()
    changes = text.split()[0] in ("/birthday", "/nameday")
    handler: Handler = Birthday() if changes else Birthdays()
    message = message_from(sender, text, in_group=in_group, edit=edit)
    await handler.handle_data_message(DataMessageContext(bot, message))
    return "\n".join(answer.text or "" for answer in answers)


def the_file() -> list[str]:
    path = get_settings().data_file("birthdays.txt")
    return [line for line in path.read_text().splitlines() if not line.startswith("#")]


async def test_a_contact_s(bot: SignalBot, answers: list[SendMessage]) -> None:
    assert await ask(bot, answers, "/birthday add 1990-03-14 Alice") == (
        "✅ Added: 14 March · Alice\n👥 In the groups Alice is in"
    )
    # By their Signal ID and phone number, with their name as saved, which
    # only shows if the contacts can't be read
    assert the_file() == [f"birthday | 1990-03-14 | {ALICE_ID} {ALICE} | Alice"]
    # A contact has one: another changes it
    assert await ask(bot, answers, f"/birthday add 1990-03-15 {ALICE}") == (
        "✅ Changed: 15 March · Alice\n👥 In the groups Alice is in"
    )
    assert the_file() == [f"birthday | 1990-03-15 | {ALICE_ID} {ALICE} | Alice"]
    # A name day is apart from it
    await ask(bot, answers, "/nameday add 04-24 alice")
    assert the_file()[1:] == [f"nameday | 04-24 | {ALICE_ID} {ALICE} | Alice"]


async def test_someone_not_on_signal(
    bot: SignalBot, answers: list[SendMessage]
) -> None:
    # Nobody's called that: in every group, as the answer says, in case it's
    # a contact's name mistyped
    assert await ask(bot, answers, "/birthday add 1940-05-01 Grandma Berg") == (
        "✅ Added: 1 May · Grandma Berg\n👥 In every group: no contact is called "
        "Grandma Berg"
    )
    # Or in the groups given, by their numbers in /chats
    assert await ask(bot, answers, "/nameday add 05-01 1 Grandma Berg") == (
        "✅ Added: 1 May · Grandma Berg\n👥 Familjen"
    )
    assert the_file() == [
        "birthday | 1940-05-01 | * | Grandma Berg",
        f"nameday | 05-01 | {GROUP} | Grandma Berg",
    ]


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("/birthday", "/birthday add <date> [<chats>] <who>: a birthday, e.g."),
        ("/birthday add 1990-03-14", "/birthday add <date> [<chats>] <who>"),
        ("/birthday add 14/3 Alice", "14/3 isn't a day: give it as 1990-03-14"),
        ("/birthday add 1990-02-29 Alice", "1990-02-29 isn't a day"),
        ("/birthday add 2027-01-01 Alice", "2027-01-01 is still to come."),
        ("/nameday add 1990-08-08 Alice", "A name day has no year: give it as 08-08."),
        # Known, but not saved as a contact, so with no name to show
        (
            "/birthday add 03-14 Bob Berg",
            "Save Bob Berg as a contact first, by the name to show: /contacts add "
            "Bob Berg <name>",
        ),
        (
            "/birthday add 03-14 +46700000077",
            "Nobody called +46700000077 in /contacts.",
        ),
        ("/birthday add 03-14 9 Grandma", "There's no chat 9: /chats numbers them."),
        (
            "/birthday add 03-14 2 Grandma",
            f"{ADMIN} is no group: they show in groups only.",
        ),
        ("/birthday remove", "Which? Give its number, as /birthdays shows."),
        ("/nameday remove 1", "Which ones? Send /namedays first, for their"),
    ],
)
async def test_refused(
    bot: SignalBot, answers: list[SendMessage], text: str, answer: str
) -> None:
    assert (await ask(bot, answers, text)).startswith(answer)
    assert not get_settings().data_file("birthdays.txt").exists()


async def test_twice(bot: SignalBot, answers: list[SendMessage]) -> None:
    await ask(bot, answers, "/birthday add 05-01 Grandma")
    assert await ask(bot, answers, "/birthday add 05-01 Grandma") == (
        "Grandma is there already, on that day."
    )


async def test_the_lists(bot: SignalBot, answers: list[SendMessage]) -> None:
    for text in [
        "/birthday add 1990-03-14 Alice",
        "/birthday add 1940-10-20 Grandma",
        "/birthday add 12-24 1 Santa",
    ]:
        await ask(bot, answers, text)
    path = get_settings().data_file("birthdays.txt")
    # Someone not on Signal in a group the bot isn't in
    path.write_text(path.read_text() + f"birthday | 10-21 | {FRIENDS} | Bob\n")
    # For the admins, in a direct chat: all of them, the coming ones first,
    # numbered as shown, with where they show but for contacts
    assert await ask(bot, answers, "/birthdays") == "\n".join(
        [
            "**🎂 4 birthdays**",
            "1 · 20 October · Grandma (turns 86) · 👥 every group",
            "2 · 21 October · Bob · 👥 group.RnJpZW5k…",
            "3 · 24 December · Santa · 👥 Familjen",
            "4 · 14 March · Alice (turns 37)",
        ]
    )
    # In a group, those it gets, unnumbered
    assert await ask(bot, answers, "/birthdays", ALICE, in_group=True) == "\n".join(
        [
            "**🎂 3 birthdays**",
            "20 October · Grandma (turns 86)",
            "24 December · Santa",
            "14 March · Alice (turns 37)",
        ]
    )
    # Not in anyone else's direct chat
    assert await ask(bot, answers, "/birthdays", ALICE) == (
        "Birthdays and name days show in groups, for those in them."
    )
    assert await ask(bot, answers, "/namedays", ALICE, in_group=True) == (
        "No name days here."
    )
    # By the numbers of the list the admin was shown
    assert await ask(bot, answers, "/birthday remove 1,2") == (
        "🗑️ Removed: 20 October · Grandma, 21 October · Bob"
    )
    assert len(the_file()) == 2


async def test_removed_by_the_list_shown_last(
    bot: SignalBot, answers: list[SendMessage], monkeypatch: pytest.MonkeyPatch
) -> None:
    other = "+46700000008"
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}", "{other}"]')
    get_settings.cache_clear()
    await ask(bot, answers, "/birthday add 10-20 Grandma")
    await ask(bot, answers, "/birthday add 12-24 Santa")
    # Not before a list
    assert await ask(bot, answers, "/birthday remove 1") == (
        "Which ones? Send /birthdays first, for their numbers."
    )
    await ask(bot, answers, "/birthdays")
    assert await ask(bot, answers, "/birthday remove 3") == (
        "There's no 3 in /birthdays."
    )
    # What's added since doesn't change the numbers shown, nor the next day
    await ask(bot, answers, "/birthday add 10-19 Today")
    assert await ask(bot, answers, "/birthday remove 2") == (
        "🗑️ Removed: 24 December · Santa"
    )
    assert await ask(bot, answers, "/birthday remove 2,1") == "\n".join(
        [
            "🗑️ Removed: 20 October · Grandma",
            "2 is gone already: removed or changed since.",
        ]
    )
    # Each admin has the list they were shown; name days have their own
    assert await ask(bot, answers, "/birthday remove 1", other) == (
        "Which ones? Send /birthdays first, for their numbers."
    )
    assert await ask(bot, answers, "/nameday remove 1") == (
        "Which ones? Send /namedays first, for their numbers."
    )
    assert the_file() == ["birthday | 10-19 | * | Today"]


async def test_an_edit_takes_the_place_of_what_it_edits(
    bot: SignalBot, answers: list[SendMessage]
) -> None:
    await ask(bot, answers, "/birthday add 1990-03-14 Alice")
    assert await ask(bot, answers, "/birthday add 1990-03-15 Alice", edit=True) == (
        "✅ Added: 15 March · Alice\n👥 In the groups Alice is in"
    )
    await ask(bot, answers, "/nameday add 05-01 Grandma")
    await ask(bot, answers, "/nameday add 05-02 Grandma", edit=True)
    assert the_file() == [
        f"birthday | 1990-03-15 | {ALICE_ID} {ALICE} | Alice",
        "nameday | 05-02 | * | Grandma",
    ]
    # One removed comes back, for the edit to remove another
    await ask(bot, answers, "/birthdays")
    await ask(bot, answers, "/birthday remove 1")
    await ask(bot, answers, "/birthday remove 2", edit=True)
    assert len(the_file()) == 2


async def test_where_they_show(bot: SignalBot, signal_api: FakeApi) -> None:
    path = get_settings().data_file("birthdays.txt")
    path.write_text(
        f"birthday | 1990-10-19 | {ALICE_ID} {ALICE} | Ally\n"
        f"nameday | 10-19 | {ALICE_ID} | Ally\n"  # the group lists her number
        f"birthday | 10-19 | {BOB} | Bob\n"  # in no group with the bot
        "birthday | 1940-10-19 | * | Grandma\n"
        f"birthday | 10-19 | {FRIENDS} | Santa\n"  # a group the bot isn't in
        "birthday | 10-20 | * | Tomorrow\n"
    )
    # Birthdays first, by the contact's name as the contacts have it now; in
    # the groups they're in, by their Signal ID or number; none in a direct
    # chat
    assert await greetings(bot, date(2026, 10, 19)) == {
        GROUP: [
            "🎂 Alice turns 36 today!",
            "🎂 Grandma turns 86 today!",
            "🌸 Happy name day, Alice!",
        ]
    }
    # With no contacts to go by, the names saved, and the IDs saved
    signal_api.route("GET", f"/v1/contacts/{ME}", unavailable)
    assert await greetings(bot, date(2026, 10, 19)) == {
        GROUP: ["🎂 Ally turns 36 today!", "🎂 Grandma turns 86 today!"]
    }


async def unavailable(request: web.Request) -> web.Response:
    return web.json_response({"error": "down"}, status=500)


async def test_nothing_on_a_day_like_any_other(bot: SignalBot) -> None:
    get_settings().data_file("birthdays.txt").write_text(
        f"birthday | 1990-03-14 | {ALICE_ID} | Alice\n"
    )
    assert await greetings(bot, date(2026, 10, 19)) == {}


def test_29_february() -> None:
    leap = Occasion(BIRTHDAY, 2, 29, "Leap", year=2000)
    assert leap.on(2027) == date(2027, 2, 28)
    assert leap.on(2028) == date(2028, 2, 29)
    assert leap.next(date(2027, 3, 1)) == date(2028, 2, 29)


@pytest.mark.parametrize(
    "line",
    [
        "birthday | 1990-03-14 | Alice",  # no who
        "birthday | 1990-13-14 | * | Alice",
        "nameday | 1990-08-08 | * | Alice",  # with a year
        "birthday | 03-14 | someone | Alice",
        f"birthday | 03-14 | {ALICE} {GROUP} | Alice",  # a contact or groups
        "birthday | 03-14 | * |",
        "wedding | 03-14 | * | Alice",
    ],
)
def test_lines_it_can_t_read(line: str) -> None:
    with pytest.raises(ValueError):
        parse_line(line)


def test_lines() -> None:
    assert parse_line(f"birthday | 03-14 | {GROUP} {FRIENDS} | Alice | B") == (
        Occasion(BIRTHDAY, 3, 14, "Alice | B", groups=(GROUP, FRIENDS))
    )
    assert parse_line(f" nameday|08-08|{ALICE}|Alice ") == Occasion(
        NAMEDAY, 8, 8, "Alice", who=(ALICE,)
    )
    assert parse_line(f"birthday|03-14|{ALICE_ID.upper()} {ALICE}|Alice") == (
        Occasion(BIRTHDAY, 3, 14, "Alice", who=(ALICE_ID, ALICE))
    )
