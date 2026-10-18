import asyncio
import time

import pytest
from aiohttp import web
from helpers import ALICE, ALICE_ID, BOB, CAROL_ID, ME, SAFETY_NUMBER, FakeApi
from signalbot import SignalBot

from nejomibot import account as account_module
from nejomibot.account import (
    Account,
    Contact,
    Identity,
    Nickname,
    Profile,
    with_fresh_profiles,
)
from nejomibot.contacts import (
    contacts_answer,
    contacts_message,
    find,
    find_one,
    format_safety_number,
    parse_trust,
    person_card,
    verify,
)
from nejomibot.messages import escape


def test_escape() -> None:
    assert escape(r"*Al`ice|~\ ") == r"\*Al\`ice\|\~\ "


def test_format_safety_number_like_the_apps() -> None:
    assert format_safety_number("12345 67890" * 6) == [
        "`12345 67890 12345 67890`",
        "`12345 67890 12345 67890`",
        "`12345 67890 12345 67890`",
    ]


def test_contacts_message(account: Account) -> None:
    # Two short lines each, as Signal's bubbles are narrow; no safety numbers
    assert contacts_message(account) == (
        "👥 **Who the bot knows**\n"
        "🔐 3 safety numbers: 1 verified, 1 untrusted.\n\n"
        "📇 **Contacts** (1)\n"
        f"👤 **Alice** · {ALICE}\n"
        "✅ Verified · 👥 Familjen\n\n"
        # Not the bot itself; sorted by name, or by ID without one
        "💬 **Other known recipients** (2)\n"
        f"👤 **Bob Berg** · {BOB}\n"
        "❌ Untrusted: safety number changed · 🚫 blocked\n"
        "👤 **ca401000…** · phone number not shared\n"
        "⚪ Not verified · 👥 Familjen\n\n"
        "🔎 /contacts <who> shows one, with their safety number to compare with "
        "their phone before /trust."
    )


def test_contacts_message_lists_safety_numbers_of_strangers(
    account: Account,
) -> None:
    account.recipients.pop()  # Carol
    assert (
        "🔢 **Only a safety number** (1)\n"
        "👤 **ca401000…** · phone number not shared\n"
        "⚪ Not verified · 👥 Familjen\n\n"
    ) in contacts_message(account)


def test_a_long_id_shows_by_its_start(account: Account) -> None:
    uuid = "0b7c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"
    account.recipients.append(Contact(uuid=uuid))
    assert "👤 **0b7c1d2e…** · phone number not shared" in contacts_message(account)


def test_person_card(account: Account) -> None:
    alice = find_one(account, "alice")
    assert isinstance(alice, Contact)
    assert person_card(account, alice) == "\n".join(
        [
            "👤 **Alice**",
            ALICE,
            f"🆔 {ALICE_ID}",
            "👥 In Familjen",
            "✅ Verified, key from 1970-01-01",
            *format_safety_number(SAFETY_NUMBER),
        ]
    )


def test_person_card_says_how_to_verify(account: Account) -> None:
    account.identities[0].status = "TRUSTED_UNVERIFIED"
    alice = find_one(account, "Alice")
    assert isinstance(alice, Contact)
    card = person_card(account, alice)
    assert card.endswith(
        "\nCompare their safety number here with the one on their phone, then "
        "send: /trust <name, phone number or ID> <safety number>"
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
    assert "\n👤 **+46700000009**\nNo safety number yet\n" in contacts_message(account)


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
        (f"/trust {SAFETY_NUMBER}", None),
        ("/trust Alice 12345", None),
        ("/trust", None),
    ],
)
def test_parse_trust(text: str, parsed: tuple[str, str] | None) -> None:
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
