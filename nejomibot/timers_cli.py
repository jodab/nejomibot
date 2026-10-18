"""nejomibot-timers: the bot's timers from a terminal, as /timers, /chats and
/timer have them in Signal. In the bot's container:

  podman exec nejomibot nejomibot-timers               the timers
  podman exec nejomibot nejomibot-timers chats         where timers can post
  podman exec nejomibot nejomibot-timers add "mon-fri 07:30" 1,2 "/weather; /photo"
  podman exec nejomibot nejomibot-timers remove 3

It reads the bot's settings as the bot does, and changes data_dir/timers.txt,
which the bot reads again within half a minute. WHEN is as /timer add takes
it, in the bot's time zone; CHATS are numbers from chats, like 1,2, or group
IDs, phone numbers and Signal IDs; COMMANDS are separated by ;. Chats, and
the chats' names, come from signal-cli-rest-api, at signal_service.
"""

import argparse
import asyncio
import logging
import re
from collections.abc import Awaitable, Callable

from signalbot import LOGGER_NAME, Config, ConnectionMode, InMemoryConfig, SignalBot

from . import access
from .bot import load_settings, set_up_logging
from .client import client
from .config import get_settings
from .messages import EXPECTED, describe
from .timers import (
    Chat,
    Timekeeper,
    Timer,
    add_new,
    chat_list,
    check_new,
    line_of,
    split_commands,
)


class Refused(Exception):
    """What's wrong with what was asked: said, and the tool stops."""


# What the tool does, with a signalbot to ask signal-cli-rest-api
type Work = Callable[[SignalBot], Awaitable[str]]


async def asking(work: Work) -> str:
    """Do the work with a signalbot for it to ask signal-cli-rest-api."""
    settings = get_settings()
    bot = SignalBot(
        Config(
            signal_service=settings.signal_service,
            phone_number=settings.account,
            connection_mode=ConnectionMode.HTTP_ONLY,
            logging_level=logging.WARNING,
            storage=InMemoryConfig(),
        )
    )
    logging.getLogger(LOGGER_NAME).handlers.clear()  # as the bot does
    try:
        return await work(bot)
    finally:
        await bot.close()
        await client.close()


async def names(bot: SignalBot) -> dict[str, str]:
    """The chats' names, as far as signal-cli-rest-api knows them."""
    try:
        await bot.groups.refresh()
    except Exception as e:
        logging.getLogger(__name__).warning("No groups' names: %s", e)
    return await access.names(bot)


def card(timer: Timer, known: dict[str, str]) -> str:
    """E.g. '#1 daily 08:00 → Family, Alice: /dailypost (last 2026-10-13 08:00)'."""
    chats = ", ".join(known.get(chat, chat) for chat in timer.chats)
    commands = "; ".join(timer.commands)
    last = f"{timer.last.astimezone(get_settings().tz):%Y-%m-%d %H:%M}"
    return f"#{timer.id} {timer.when} → {chats}: {commands} (last {last})"


async def list_timers(bot: SignalBot) -> str:
    keeper = Timekeeper()
    keeper.read()
    path = get_settings().timers_file
    if not keeper.timers and not keeper.broken:
        return f"No timers in {path}."
    known = await names(bot)
    timers = sorted(keeper.timers.values(), key=lambda timer: timer.id)
    return "\n".join(
        [
            f"Timers in {path}:",
            *(card(timer, known) for timer in timers),
            *(f"Not a timer, left as it is: {line}" for line in keeper.broken),
        ]
    )


async def list_chats(bot: SignalBot) -> str:
    await bot.groups.refresh()
    chats = await chat_list(bot)
    return "\n".join(
        [
            "Timers can post to:",
            *(
                f"{n:3}  {'group ' if access.is_group(chat_id) else 'person'}  {name}"
                for n, (chat_id, name) in enumerate(chats, start=1)
            ),
        ]
    )


async def chats_in(bot: SignalBot, text: str) -> list[str]:
    """The chats of the text: numbers from chats, or IDs."""
    listed: list[Chat] | None = None
    found: list[str] = []
    for word in (word for word in re.split(r"[\s,]+", text) if word):
        if word.isdigit():
            if listed is None:
                await bot.groups.refresh()
                listed = await chat_list(bot)
            if not 1 <= int(word) <= len(listed):
                raise Refused(f"There's no chat {word}: chats numbers them.")
            found.append(listed[int(word) - 1][0])
        elif chat_id := access.chat_id_of(word):
            found.append(chat_id)
        else:
            raise Refused(f"{word} is no chat: give numbers from chats, or IDs.")
    if not found:
        raise Refused("Which chats? Numbers from chats, like 1,2.")
    return list(dict.fromkeys(found))


async def add(bot: SignalBot, when: str, chats: str, text: str, dry_run: bool) -> str:
    if isinstance(commands := split_commands(text), str):
        raise Refused(commands)
    if isinstance(schedule := check_new(when, commands), str):
        raise Refused(schedule)
    chat_ids = await chats_in(bot, chats)
    keeper = Timekeeper()
    keeper.read()
    if dry_run:
        timer = keeper.new(schedule.text, chat_ids, commands)
        return f"Would add: {line_of(timer)}\nDry run: nothing has changed."
    if isinstance(added := add_new(keeper, schedule, chat_ids, commands), str):
        raise Refused(added)
    known = await names(bot)
    return f"Added {card(added, known)}\nThe bot takes it in within half a minute."


async def remove(bot: SignalBot, number: str, dry_run: bool) -> str:
    keeper = Timekeeper()
    keeper.read()
    timer_id = number.lstrip("#")
    if not timer_id.isdigit() or (timer := keeper.timers.get(int(timer_id))) is None:
        raise Refused(f"There's no timer {number} in {get_settings().timers_file}.")
    known = await names(bot)
    if dry_run:
        return f"Would remove {card(timer, known)}\nDry run: nothing has changed."
    keeper.remove(timer.id)
    return f"Removed {card(timer, known)}\nThe bot takes it in within half a minute."


def parser() -> argparse.ArgumentParser:
    tool = argparse.ArgumentParser(
        prog="nejomibot-timers",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    tool.add_argument(
        "-n", "--dry-run", action="store_true", help="show the change, not making it"
    )
    commands = tool.add_subparsers(dest="command", metavar="COMMAND")
    commands.add_parser("list", help="the timers (the default)")
    commands.add_parser("chats", help="where timers can post, numbered")
    new = commands.add_parser("add", help="a new timer")
    new.add_argument("when", metavar="WHEN")
    new.add_argument("chats", metavar="CHATS")
    new.add_argument("commands", metavar="COMMANDS")
    gone = commands.add_parser("remove", aliases=["delete"], help="remove a timer")
    gone.add_argument("number", metavar="NUMBER")
    return tool


def main() -> None:
    args = parser().parse_args()
    set_up_logging()
    load_settings()

    async def work(bot: SignalBot) -> str:
        match args.command:
            case "add":
                return await add(
                    bot, args.when, args.chats, args.commands, args.dry_run
                )
            case "remove" | "delete":
                return await remove(bot, args.number, args.dry_run)
            case "chats":
                return await list_chats(bot)
            case _:
                return await list_timers(bot)

    try:
        print(asyncio.run(asking(work)))
    except Refused as e:
        raise SystemExit(f"ERROR: {e}") from None
    except EXPECTED as e:
        raise SystemExit(f"ERROR: {describe(e)}") from None
