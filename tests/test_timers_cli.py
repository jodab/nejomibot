import re

import pytest
from helpers import ALICE, GROUP, FakeApi
from signalbot import SignalBot

from nejomibot import timers_cli
from nejomibot.config import get_settings
from nejomibot.timers import Timekeeper, Timer
from nejomibot.timers_cli import Refused, add, chats_in, list_chats, list_timers, remove


def in_the_file() -> list[Timer]:
    keeper = Timekeeper()
    keeper.read()
    return list(keeper.timers.values())


def run_main(monkeypatch: pytest.MonkeyPatch, *args: str) -> None:
    monkeypatch.setattr("sys.argv", ["nejomibot-timers", *args])
    timers_cli.main()


def test_no_timers(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run_main(monkeypatch)
    assert capsys.readouterr().out == f"No timers in {get_settings().timers_file}.\n"


def test_no_such_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(SystemExit, match="ERROR: There's no timer 9 in"):
        run_main(monkeypatch, "remove", "9")


async def test_chats_are_numbered_as_in_signal(
    bot: SignalBot, signal_api: FakeApi
) -> None:
    get_settings().allowed_file.write_text(f"{ALICE}\n")
    assert await list_chats(bot) == (
        f"Timers can post to:\n  1  group   Familjen\n  2  person  Alice ({ALICE})"
    )


async def test_add_list_and_remove(bot: SignalBot, signal_api: FakeApi) -> None:
    added = await add(bot, "Mon-Fri 07:30", "1", "/weather; /photo", dry_run=False)
    assert added.startswith(
        "Added #1 weekdays 07:30 → Familjen: /weather; /photo (last "
    )
    [timer] = in_the_file()
    assert (timer.chats, timer.commands) == ([GROUP], ["/weather", "/photo"])
    assert (
        (await list_timers(bot))
        .splitlines()[1]
        .startswith("#1 weekdays 07:30 → Familjen: /weather; /photo")
    )
    assert (await remove(bot, "#1", dry_run=False)).startswith("Removed #1 ")
    assert in_the_file() == []


async def test_a_dry_run_changes_nothing(bot: SignalBot, signal_api: FakeApi) -> None:
    would = await add(bot, "08:00", ALICE, "/ping", dry_run=True)
    assert would.startswith(f"Would add: 1 | daily 08:00 | {ALICE} | /ping | ")
    assert in_the_file() == []
    await add(bot, "08:00", ALICE, "/ping", dry_run=False)
    assert (await remove(bot, "1", dry_run=True)).startswith("Would remove #1 ")
    assert len(in_the_file()) == 1


@pytest.mark.parametrize(
    ("when", "chats", "commands", "why"),
    [
        ("soon", "1", "/ping", "soon? <when> is a time"),
        ("08:00", "1", "ping", "Commands start with . or /, unlike ping."),
        ("08:00", "1", "/msg 1 Hi", "Timers, specials and /run can't run /msg."),
        ("08:00", "9", "/ping", "There's no chat 9: chats numbers them."),
        ("08:00", "Bob", "/ping", "Bob is no chat"),
        ("08:00", ",", "/ping", "Which chats?"),
    ],
)
async def test_refused(
    bot: SignalBot, signal_api: FakeApi, when: str, chats: str, commands: str, why: str
) -> None:
    with pytest.raises(Refused, match=f"^{re.escape(why)}"):
        await add(bot, when, chats, commands, dry_run=False)


async def test_chats_by_id(bot: SignalBot) -> None:
    # No need to ask signal-cli-rest-api for them
    assert await chats_in(bot, f"{GROUP}, {ALICE} {ALICE}") == [GROUP, ALICE]
