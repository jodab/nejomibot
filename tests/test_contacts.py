import asyncio
import time

import pytest
from aiohttp import web
from helpers import (
    ALICE,
    ALICE_ID,
    BOB,
    BOB_ID,
    CAROL_ID,
    DAVE_ID,
    ME,
    SAFETY_NUMBER,
    FakeApi,
    message_from,
)
from signalbot import DataMessageContext, SendMessage, SignalBot

from nejomibot import account as account_module
from nejomibot import contacts
from nejomibot.account import (
    Account,
    Contact,
    Identity,
    Nickname,
    Profile,
    with_fresh_profiles,
)
from nejomibot.contacts import (
    Contacts,
    Trust,
    add,
    contacts_answer,
    contacts_message,
    find,
    find_one,
    format_safety_number,
    parse_trust,
    person_card,
    verify,
)
from nejomibot.messages import collected, escape


def test_escape() -> None:
    assert escape(r"*Al`ice|~\ ") == r"\*Al\`ice\|\~\ "


def test_format_safety_number_like_the_apps() -> None:
    assert format_safety_number("12345 67890" * 6) == [
        "`12345 67890 12345 67890`",
        "`12345 67890 12345 67890`",
        "`12345 67890 12345 67890`",
    ]


def test_contacts_message(account: Account) -> None:
    # Two short lines each, as Signal's bubbles are narrow; no safety numbers.
    # Numbered across the sections, as /trust numbers them too.
    assert contacts_message(account) == (
        "👥 **Who the bot knows**\n"
        "🔐 3 safety numbers: 1 verified, 1 untrusted.\n\n"
        "📇 **Contacts** (1)\n"
        f"1 👤 **Alice** · {ALICE}\n"
        "✅ Verified · 👥 Familjen\n\n"
        # Not the bot itself; sorted by name, or by ID without one
        "💬 **Other known recipients** (2)\n"
        f"2 👤 **Bob Berg** · {BOB}\n"
        "❌ Untrusted: safety number changed · 🚫 blocked\n"
        "3 👤 **ca401000…** · phone number not shared\n"
        "⚪ Not verified · 👥 Familjen\n\n"
        "🔎 /contacts <n> shows one in full; /trust lists the safety numbers, to "
        "compare with their phones."
    )


def test_contacts_message_lists_safety_numbers_of_strangers(
    account: Account,
) -> None:
    account.recipients.pop()  # Carol
    assert (
        "🔢 **Only a safety number** (1)\n"
        "3 👤 **ca401000…** · phone number not shared\n"
        "⚪ Not verified · 👥 Familjen\n\n"
    ) in contacts_message(account)


def test_a_long_id_shows_by_its_start(account: Account) -> None:
    uuid = "0b7c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"
    account.recipients.append(Contact(uuid=uuid))
    assert "👤 **0b7c1d2e…** · phone number not shared" in contacts_message(account)


def test_a_username_shows_where_signal_cli_knows_it(account: Account) -> None:
    # As it does for someone it found by it
    account.recipients.append(Contact(uuid=DAVE_ID, name="Dave", username="dave.07"))
    # One that's all the name they have, once
    eve_id = "e7e00000-0000-4000-8000-000000000005"
    account.recipients.append(Contact(uuid=eve_id, username="eve.42"))
    text = contacts_message(account)
    assert "👤 **Dave** · phone number not shared · @dave.07\n" in text
    assert "👤 **eve.42** · phone number not shared\n" in text


def test_person_card(account: Account) -> None:
    alice = find_one(account, "alice")
    assert isinstance(alice, Contact)
    assert person_card(account, alice) == "\n".join(
        [
            "👤 **Alice**",
            f"📞 Number: {ALICE}",
            f"🆔 {ALICE_ID}",
            "👥 In Familjen",
            "✅ Verified, key from 1970-01-01",
            *format_safety_number(SAFETY_NUMBER),
        ]
    )


def test_the_profile_name_and_username_show_beside_the_contacts_name(
    account: Account,
) -> None:
    # Named Dave in the contacts, otherwise by himself, and found by his
    # username; his number he doesn't share
    dave = Contact(
        uuid=DAVE_ID,
        name="Dave",
        username="dave.07",
        profile=Profile(given_name="DaveTheBrave⚘"),
    )
    account.recipients.append(dave)
    assert person_card(account, dave) == "\n".join(
        [
            "👤 **Dave**",
            "🪪 Profile name: DaveTheBrave⚘",
            "🔗 Username: @dave.07",
            "📞 phone number not shared",
            f"🆔 {DAVE_ID}",
            "No safety number yet",
        ]
    )
    assert (
        "👤 **Dave** · phone number not shared · 🪪 DaveTheBrave⚘ · @dave.07\n"
    ) in contacts_message(account)


@pytest.mark.parametrize("who", ["u:dave.07", "@dave.07"])
async def test_add_someone_by_username(
    bot: SignalBot, account: Account, signal_api: FakeApi, who: str
) -> None:
    text = await add(bot, account, who, "Dave")
    assert text == "📇 Added @dave.07 to the contacts, as Dave."
    # As signal-cli takes a username, which it finds Dave by
    assert signal_api.bodies("PUT", f"/v1/contacts/{ME}") == [
        {"recipient": "u:dave.07", "name": "Dave"}
    ]


async def test_add_by_a_username_signal_cli_knows_renames(
    bot: SignalBot, account: Account, signal_api: FakeApi
) -> None:
    account.recipients.append(Contact(uuid=DAVE_ID, username="dave.07"))
    text = await add(bot, account, "@Dave.07", "Dave")
    assert text == "📇 Added dave.07 to the contacts, as Dave."
    [sent] = signal_api.bodies("PUT", f"/v1/contacts/{ME}")
    assert sent["recipient"] == DAVE_ID
    # Not a username: as before
    assert await add(bot, account, "u:x", "X") == "Nobody called u:x in /contacts."


def test_person_card_says_how_to_verify(account: Account) -> None:
    account.identities[0].status = "TRUSTED_UNVERIFIED"
    alice = find_one(account, "Alice")
    assert isinstance(alice, Contact)
    assert person_card(account, alice).endswith(
        "\nTo verify it, compare it with the one on their phone, then send: "
        "/trust Alice <safety number>"
    )
    # As the admin named them
    assert person_card(account, alice, "1").endswith(
        "then send: /trust 1 <safety number>"
    )


async def test_contacts_answer_shows_one_or_all(bot: SignalBot) -> None:
    assert (await contacts_answer(bot, "")).startswith("👥 **Who the bot knows**")
    assert (await contacts_answer(bot, "bob berg")).startswith("👤 **Bob Berg**\n")
    assert await contacts_answer(bot, "Carol") == "Nobody called Carol in /contacts."


def test_real_name_prefers_the_nickname_then_the_contact_then_the_profile() -> None:
    profile = Profile(given_name="Robert", lastname="Berg")
    assert Contact(profile=profile).real_name == "Robert Berg"
    assert Contact(given_name="Bob", profile=profile).real_name == "Bob"
    nickname = Nickname(given_name="Bobby", family_name="B")
    assert Contact(nickname=nickname, name="Bob").real_name == "Bobby B"
    assert Contact(username="bob.01").real_name == "bob.01"
    assert Contact(name=" ", profile=Profile(given_name="")).real_name is None


def test_contacts_message_heads_the_unnamed_with_their_number(
    account: Account,
) -> None:
    account.recipients.append(Contact(number="+46700000009", uuid="z-uuid"))
    text = contacts_message(account)
    assert "\n2 👤 **+46700000009**\nNo safety number yet\n" in text


@pytest.mark.parametrize(
    ("text", "parsed"),
    [
        (f"/trust Alice {SAFETY_NUMBER}", ("Alice", SAFETY_NUMBER)),
        (
            f"/TRUST {ALICE} "
            + " ".join(SAFETY_NUMBER[i : i + 5] for i in range(0, 60, 5)),
            (ALICE, SAFETY_NUMBER),
        ),
        (
            f"/trust {CAROL_ID}\n"
            + "\n".join(row.strip("`") for row in format_safety_number(SAFETY_NUMBER)),
            (CAROL_ID, SAFETY_NUMBER),
        ),
        (f"/trust Anna Maria {SAFETY_NUMBER}", ("Anna Maria", SAFETY_NUMBER)),
        (f"/trust 2 {SAFETY_NUMBER}", ("2", SAFETY_NUMBER)),
        # A word alone is who, as a number in the lists may be
        ("/trust 2", ("2", "")),
        (f"/trust {SAFETY_NUMBER}", (SAFETY_NUMBER, "")),
        ("/trust Alice 12345", ("Alice", "12345")),
        ("/trust Bob Berg", ("Bob Berg", "")),
        ("/trust", ("", "")),
    ],
)
def test_parse_trust(text: str, parsed: tuple[str, str]) -> None:
    assert parse_trust(text) == parsed


def test_find(account: Account) -> None:
    assert [c.uuid for c in find(account, ALICE)] == [ALICE_ID]
    assert [c.uuid for c in find(account, "ALICE")] == [ALICE_ID]
    assert [c.uuid for c in find(account, "CA40")] == [CAROL_ID]
    assert [c.uuid for c in find(account, CAROL_ID)] == [CAROL_ID]
    assert find(account, "ca4") == []  # too short to be the start of an ID
    assert find(account, "Carol") == []


TRUST = f"/v1/identities/{ME}/trust/{ALICE_ID}"


async def test_verify(account: Account, signal_api: FakeApi) -> None:
    account.identities[0].status = "TRUSTED_UNVERIFIED"
    assert await verify(account, "alice", SAFETY_NUMBER) == "✅ Alice verified."
    assert signal_api.bodies("PUT", TRUST) == [
        {"verified_safety_number": SAFETY_NUMBER}
    ]


async def test_verify_refuses_a_wrong_safety_number(
    account: Account, signal_api: FakeApi
) -> None:
    assert (await verify(account, "Alice", "1" * 60)).startswith("❌ That isn't")
    assert signal_api.bodies("PUT", TRUST) == []


async def test_verify_already_verified_or_unknown(account: Account) -> None:
    assert await verify(account, "Alice", SAFETY_NUMBER) == (
        "✅ Alice is already verified."
    )
    assert await verify(account, "bob berg", SAFETY_NUMBER) == (
        "No safety number for Bob Berg yet."
    )
    assert await verify(account, "Carol", SAFETY_NUMBER) == (
        "Nobody called Carol in /contacts."
    )


async def test_with_fresh_profiles_names_the_nameless(
    account: Account, signal_api: FakeApi
) -> None:
    fresh = {"uuid": CAROL_ID, "profile": {"given_name": "Carol"}}
    signal_api.responses[f"/v1/contacts/{ME}/{CAROL_ID}?all"] = fresh
    refreshed = await with_fresh_profiles(account)
    assert [c.display_name for c in refreshed.recipients] == [
        "Mybot",
        "Alice",
        "Bob Berg",
        "Carol",
    ]


async def test_with_fresh_profiles_keeps_whoever_cant_be_fetched(
    account: Account,
) -> None:
    refreshed = await with_fresh_profiles(account)
    assert refreshed.recipients == account.recipients


def uuid_of(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012}"


async def test_with_fresh_profiles_asks_a_few_at_a_time(
    account: Account, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Each makes signal-cli ask Signal's servers, which rate-limit a burst
    monkeypatch.setattr(account_module, "MAX_PROFILES", 10)
    nameless = [Contact(uuid=uuid_of(n)) for n in range(12)]
    account.recipients.extend(nameless)
    asking = most = 0

    async def slowly(request: web.Request) -> web.Response:
        nonlocal asking, most
        asking += 1
        most = max(most, asking)
        await asyncio.sleep(0.01)
        asking -= 1
        return web.json_response({"uuid": request.path.rsplit("/", 1)[-1]})

    for contact in nameless:
        signal_api.route("GET", f"/v1/contacts/{ME}/{contact.uuid}", slowly)
    await with_fresh_profiles(account)
    assert most == account_module.PROFILES_AT_ONCE
    # Carol and nine of the twelve: at most ten for each command
    asked = [r for r in signal_api.requests if r.path.startswith(f"/v1/contacts/{ME}/")]
    assert len(asked) == 10


async def test_a_profile_asked_for_isnt_again_for_six_hours(
    account: Account, signal_api: FakeApi
) -> None:
    # As signal-cli keeps it that long itself, and each asks Signal's servers
    def asked() -> int:
        return sum(
            r.path == f"/v1/contacts/{ME}/{CAROL_ID}" for r in signal_api.requests
        )

    await with_fresh_profiles(account)
    await with_fresh_profiles(account)
    assert asked() == 1
    # Six hours on
    for uuid in account_module.refetched:
        account_module.refetched[uuid] -= account_module.REFETCH_AFTER
    await with_fresh_profiles(account)
    assert asked() == 2


def test_a_big_account_is_quick(account: Account) -> None:
    # Lookups by ID go through indexes, so a few thousand people take moments
    people = [Contact(number=f"+4670{n:07}", uuid=uuid_of(n)) for n in range(3000)]
    account.recipients.extend(people)
    account.identities.extend(
        Identity(number=c.number, uuid=c.uuid, status="TRUSTED_UNVERIFIED")
        for c in people
    )
    account.contacts.extend(people[:1000])
    start = time.monotonic()
    text = contacts_message(account)
    find(account, "nobody")
    assert time.monotonic() - start < 2
    assert "📇 **Contacts** (1001)" in text


# The numbers, as /contacts and /trust show them

ADMIN = "+46700000009"


async def say(bot: SignalBot, text: str, sender: str = ADMIN) -> None:
    """Send the text to /contacts and /trust, as an admin in a direct chat."""
    context = DataMessageContext(bot, message_from(sender, text))
    for handler in (Contacts(), Trust()):
        await handler.handle_data_message(context)


async def test_a_number_is_one_of_the_list_shown_last(
    bot: SignalBot, answers: list[SendMessage], signal_api: FakeApi
) -> None:
    await say(bot, "/contacts 2")
    assert answers[-1].text == "Which one? Send /contacts first, for their numbers."
    await say(bot, "/contacts")
    await say(bot, "/contacts 2")
    assert (answers[-1].text or "").startswith("👤 **Bob Berg**\n")
    await say(bot, "/contacts 4")
    assert answers[-1].text == "There's no 4 in /contacts."
    # Someone new, who'd come first now, doesn't move the numbers shown
    signal_api.responses[f"/v1/contacts/{ME}?all"].append(
        {"number": "+46700000004", "uuid": DAVE_ID, "name": "Aaron"}
    )
    await say(bot, "/contacts 2")
    assert (answers[-1].text or "").startswith("👤 **Bob Berg**\n")
    # Until the list is asked for again
    await say(bot, "/contacts")
    await say(bot, "/contacts 2")
    assert (answers[-1].text or "").startswith("👤 **Aaron**\n")


async def test_each_admin_has_the_numbers_they_were_shown(
    bot: SignalBot, answers: list[SendMessage]
) -> None:
    await say(bot, "/contacts")
    await say(bot, "/contacts 1", sender=ALICE_ID)
    assert answers[-1].text == "Which one? Send /contacts first, for their numbers."
    # Kept by phone number and Signal ID alone, not all that's known of them
    assert contacts.shown == {ADMIN: [(ALICE, ALICE_ID), (BOB, BOB_ID), ("", CAROL_ID)]}


async def test_a_timer_shows_no_admin_their_numbers(bot: SignalBot) -> None:
    # A timer, /run or a special shows the list to others
    token = collected.set([])
    try:
        await contacts_answer(bot, "", ADMIN)
    finally:
        collected.reset(token)
    assert contacts.shown == {}


async def test_trust_lists_everyones_safety_numbers(
    bot: SignalBot, answers: list[SendMessage]
) -> None:
    await say(bot, "/trust")
    text = answers[-1].text or ""
    assert text.startswith(
        "🔐 **Safety numbers**\n"
        "3 safety numbers: 1 verified, 1 untrusted.\n\n"
        "📇 **Contacts** (1)\n"
        f"1 👤 **Alice** · {ALICE}\n"
        "✅ Verified, key from 1970-01-01\n"
        + "\n".join(format_safety_number(SAFETY_NUMBER))
        + "\n\n💬 **Other known recipients** (2)\n"
        f"2 👤 **Bob Berg** · {BOB}\n"
        "❌ Untrusted: safety number changed, key from "
    )
    assert text.endswith(
        "\n3 👤 **ca401000…** · phone number not shared\n"
        "⚪ Not verified\n\n"
        "🔎 To verify one, compare it with the one on their phone, then send: "
        "/trust <n> <safety number>"
    )
    # Numbered as /contacts numbers them
    await say(bot, "/contacts 3")
    assert (answers[-1].text or "").startswith(f"👤 **{CAROL_ID}**\n")


async def test_trust_shows_one_and_verifies_it_by_number(
    bot: SignalBot, answers: list[SendMessage], signal_api: FakeApi
) -> None:
    signal_api.responses[f"/v1/identities/{ME}"][0]["status"] = "TRUSTED_UNVERIFIED"
    await say(bot, "/trust")
    await say(bot, "/trust 1")
    assert answers[-1].text == "\n".join(
        [
            f"👤 **Alice** · {ALICE}",
            "⚪ Not verified, key from 1970-01-01",
            *format_safety_number(SAFETY_NUMBER),
            "To verify it, compare it with the one on their phone, then send: "
            "/trust 1 <safety number>",
        ]
    )
    await say(bot, f"/trust 1 {SAFETY_NUMBER}")
    assert answers[-1].text == "✅ Alice verified."
    assert signal_api.bodies("PUT", TRUST) == [
        {"verified_safety_number": SAFETY_NUMBER}
    ]


@pytest.mark.parametrize(
    ("text", "answer"),
    [
        ("/trust bob berg", f"👤 **Bob Berg** · {BOB}\n❌ Untrusted"),
        ("/trust 1", "Which one? Send /contacts first, for their numbers."),
        ("/trust Carol", "Nobody called Carol in /contacts."),
        # Some of a safety number, or one without who
        ("/trust Alice 12345 67890", "To verify a safety number, compare it"),
        (f"/trust {SAFETY_NUMBER}", "To verify a safety number, compare it"),
    ],
)
async def test_trust_one_or_why_not(
    bot: SignalBot, answers: list[SendMessage], text: str, answer: str
) -> None:
    await say(bot, text)
    assert (answers[-1].text or "").startswith(answer)


async def test_trust_usage_needs_no_account(
    bot: SignalBot, answers: list[SendMessage], signal_api: FakeApi
) -> None:
    await say(bot, "/trust Alice 12345")
    assert answers[-1].text == (
        "To verify a safety number, compare it with the one on their phone, "
        "then send: /trust <who> <safety number>, all 60 digits"
    )
    assert signal_api.requests == []


async def test_add_a_contact_by_their_number(
    bot: SignalBot, answers: list[SendMessage], signal_api: FakeApi
) -> None:
    await say(bot, "/contacts")
    await say(bot, "/contacts add 3 Carl")
    assert answers[-1].text == f"📇 Added {CAROL_ID} to the contacts, as Carl."
    assert signal_api.bodies("PUT", f"/v1/contacts/{ME}") == [
        {"recipient": CAROL_ID, "name": "Carl"}
    ]
