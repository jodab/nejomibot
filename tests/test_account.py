from datetime import UTC, datetime

from helpers import ALICE, BOB, CAROL_ID, ME, NOW_MS, FakeApi
from signalbot import SignalBot

from nejomibot import status
from nejomibot.account import (
    Account,
    Device,
    account_lines,
    device_lines,
    fetch_account,
    fetch_devices,
    with_fresh_profiles,
)
from nejomibot.config import get_settings
from nejomibot.health import Check


def allow(*chats: str) -> None:
    get_settings().allowed_file.write_text("".join(f"{chat}\n" for chat in chats))


def test_account_lines(account: Account) -> None:
    # Short lines, as Signal's bubbles are narrow
    assert account_lines(account) == [
        f"{ME} · “Mybot” @mybot.01",
        "💬 Hej",
        "👤 1 contact · 4 known recipients",
        "🚫 blocked: Bob Berg",
        "🔐 Safety numbers: 2 trusted (1 verified) · 1 untrusted",
        "🆕 New or changed in the last week: Bob Berg",
        "👥 1 group (admin in 1) · 2 other members",
        "1 left · 1 pending invite",
        "🙋 Asking to join: Familjen (1)",
    ]


async def test_devices(signal_api: FakeApi) -> None:
    devices = await fetch_devices()
    now = datetime.fromtimestamp(NOW_MS / 1000, UTC)
    lines = device_lines(devices, now)
    assert lines[0].startswith("📟 #1 primary (seen 20")
    assert lines[1:] == ["📟 #2 signal-cli (seen today)"]
    assert device_lines([Device(id=3)], now) == ["📟 #3"]


def test_account_checks_find_problems(account: Account) -> None:
    allow(ALICE, BOB)
    assert status.account_checks(account) == [
        Check(
            "Safety numbers",
            ok=False,
            detail="untrusted, so messages are not sent: Bob Berg",
        ),
        Check("Recipients", ok=False, detail="blocked: Bob Berg"),
    ]


def test_account_checks_pass(account: Account) -> None:
    account.identities.pop(1)  # Bob's, untrusted
    allow(ALICE)
    assert [check.ok for check in status.account_checks(account)] == [True, True]


def test_a_blocked_group_is_found(account: Account) -> None:
    account.groups[0].blocked = True
    allow(account.groups[0].id)
    assert status.account_checks(account)[1] == Check(
        "Recipients", ok=False, detail="blocked: Familjen"
    )


def test_account_checks_without_the_account() -> None:
    checks = status.account_checks(ConnectionRefusedError("refused"))
    assert [check.ok for check in checks] == [False, False]
    assert checks[0].detail == "refused"


async def test_the_groups_come_from_signalbot(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    account = await fetch_account(bot)
    assert [group.name for group in account.groups] == ["Familjen", "Old"]
    assert signal_api.bodies("GET", f"/v1/groups/{ME}") == [None]


async def test_the_nameless_are_asked_for_again(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    # Which makes signal-cli fetch their profile
    await with_fresh_profiles(await fetch_account(bot))
    assert signal_api.bodies("GET", f"/v1/contacts/{ME}/{CAROL_ID}") == [None]
