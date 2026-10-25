import os
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from helpers import GROUP, ME, ME_ID, FakeApi, group_entry, write
from signalbot import SignalBot

from nejomibot import status, system
from nejomibot.account import Account, Contact
from nejomibot.config import get_settings
from nejomibot.health import Check
from nejomibot.timers import timekeeper


def test_clock_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(system, "clock_sync", lambda: (True, 0.4905))
    assert status.clock_check() == Check(
        "Clock", ok=True, detail="synchronized, max error 0.49 s"
    )
    monkeypatch.setattr(system, "clock_sync", lambda: (False, 16.0))
    assert not status.clock_check().ok


def test_host_lines(fake_system: Path) -> None:
    write(fake_system, "sys/class/dmi/id/sys_vendor", "QEMU\n")
    write(fake_system, "sys/class/dmi/id/product_name", "Standard PC (Q35)\n")
    write(fake_system, "proc/cpuinfo", "model name\t: Xeon\nflags\t: hypervisor\n")
    write(fake_system, "proc/uptime", "90.0 100.0\n")
    write(fake_system, "proc/pressure/cpu", "some avg10=1.00 avg60=2.50 avg300=0\n")
    write(
        fake_system,
        "proc/meminfo",
        "MemTotal: 4194304 kB\nMemAvailable: 1048576 kB\n"
        "SwapTotal: 2097152 kB\nSwapFree: 1572864 kB\n",
    )
    write(fake_system, "sys/class/hwmon/hwmon0/name", "coretemp\n")
    write(fake_system, "sys/class/hwmon/hwmon0/temp1_label", "Package id 0\n")
    write(fake_system, "sys/class/hwmon/hwmon0/temp1_input", "47000\n")

    lines = status.host_lines()
    assert lines[:2] == [
        "QEMU Standard PC (Q35) (virtual machine)",
        f"Xeon, {os.cpu_count()} CPUs",
    ]
    assert lines[3].startswith("Up 1 min, since ")
    assert "Waiting (last minute): cpu 2.5%" in lines
    assert "Memory 1.0GB available of 4.0GB" in lines
    assert "Swap 512.0MB used of 2.0GB" in lines
    assert lines[-1] == "🌡️ CPU 47°C"


def test_disk_check(tmp_path: Path) -> None:
    assert status.disk_check(tmp_path).detail.endswith("B")
    assert not status.disk_check(tmp_path / "missing").ok


async def test_check_photos_without_photos(photos_dir: Path) -> None:
    with pytest.raises(status.CheckFailed, match="no photos"):
        await status.check_photos()


GROUP_B = "group.bbbbbbbbbbbbbbbbbbbb="


def allow(*chats: str) -> None:
    get_settings().allowed_file.write_text("".join(f"{chat}\n" for chat in chats))


async def test_check_groups(bot: SignalBot, signal_api: FakeApi) -> None:
    signal_api.responses[f"/v1/groups/{ME}"].append(group_entry(GROUP_B, "B"))
    allow(GROUP, GROUP_B)
    # By the account's groups, which /status reads once
    account = status.account_or_error(bot)
    assert await status.check_groups(account) == "member of 2, all 2 allowed"


async def test_check_groups_names_missing_group(bot: SignalBot) -> None:
    # The bot has left "group.b2xk"
    allow(GROUP, GROUP_B, "group.b2xk")
    with pytest.raises(
        status.CheckFailed,
        match=r"not a member of group.b2xk…, group\.bbbbbbbb…",
    ):
        await status.check_groups(status.account_or_error(bot))


async def test_check_groups_fails_as_the_account_did() -> None:
    async def failed() -> Exception:
        return RuntimeError("no answer")

    with pytest.raises(RuntimeError, match="no answer"):
        await status.check_groups(failed())


def test_checks_text_when_all_pass() -> None:
    assert status.checks_text(
        [
            Check("Weather", ok=True, detail="23°", seconds=0.012),
            Check("Rates", ok=True, detail="1 EUR = 11 SEK", seconds=2.34),
        ]
    ) == (
        "🩺 **Status**\n✅ All 2 checks passed\n\n"
        # Only a slow check says how long it took
        "✅ Weather · 23°\n✅ Rates · 1 EUR = 11 SEK, in 2.3 s"
    )


def test_checks_text_puts_the_failed_first() -> None:
    text = status.checks_text(
        [
            Check("API", ok=False, detail="down"),
            Check("A", ok=True, detail="fine"),
            Check("B", ok=False, detail="broken"),
        ]
    )
    assert text == (
        "🩺 **Status**\n❌ 2 of 3 checks failed\n\n"
        "❌ **API**\ndown\n❌ **B**\nbroken\n\n"
        "✅ A · fine"
    )


def test_details_text() -> None:
    text = status.details_text(
        [("🤖", "Bot", ["nejomibot 0.3.0", "Up 3 min"]), ("🌐", "Internet", [])]
    )
    # A section without lines is left out
    assert text == "🤖 **Bot**\nnejomibot 0.3.0\nUp 3 min"


def test_reports_show_names_as_they_are() -> None:
    details = status.details_text(
        [("📱", "Signal account", ["🚫 blocked: ~Anna~, **Bob**"])]
    )
    assert details.endswith("🚫 blocked: \\~Anna\\~, \\*\\*Bob\\*\\*")
    checks = status.checks_text(
        [Check("Safety numbers", ok=False, detail="not trusted: ||Carl||")]
    )
    assert checks.endswith("❌ **Safety numbers**\nnot trusted: \\|\\|Carl\\|\\|")


def test_the_bots_lines_name_its_time_zone_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Not with each time, as the next timer run had it
    job = SimpleNamespace(
        id="timer-1-0", next_run_time=datetime(2026, 10, 19, 15, 41, tzinfo=UTC)
    )
    bot = SimpleNamespace(scheduler=SimpleNamespace(get_jobs=lambda: [job]))
    monkeypatch.setattr(timekeeper, "bot", bot)
    lines = status.bot_lines(None, 0.3)
    assert lines[3] == "Time zone Europe/Stockholm"
    assert lines[4].startswith("Up ")
    assert lines[5] == "Next timer run 2026-10-19 17:41"


def account_of(account_id: str, **me: str) -> Account:
    """The account, whose own entry has these fields."""
    recipients = [Contact.model_validate(me)]
    return Account(
        account_id, contacts=[], recipients=recipients, identities=[], groups=[]
    )


def username_checks(account: Account) -> list[tuple[str, bool, str]]:
    return [(c.name, c.ok, c.detail) for c in status.account_checks(account)][2:]


def test_an_account_without_a_number_needs_a_username() -> None:
    assert username_checks(account_of(ME_ID, uuid=ME_ID)) == [
        ("Username", False, "none, and without a phone number, nobody can find the bot")
    ]
    assert username_checks(account_of(ME_ID, uuid=ME_ID, username="mybot.42")) == [
        ("Username", True, "@mybot.42")
    ]
    # With a number, people can find it by that
    assert username_checks(account_of(ME, number=ME, uuid=ME_ID)) == []
