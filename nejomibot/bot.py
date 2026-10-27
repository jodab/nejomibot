"""Entry point: wires up the command handlers, who may use them, the timers and
the health reports."""

import argparse
import asyncio
import logging
import os
import platform
import signal
import sys
import tempfile
from collections.abc import Callable
from importlib.metadata import version
from importlib.resources import files
from pathlib import Path
from types import FrameType

from pydantic import ValidationError
from signalbot import LOGGER_NAME, Config, ConnectionMode, InMemoryConfig, SignalBot

from . import access, health, photos, profile, reminders, rest, terminal
from .admins import Admin, Admins
from .albums import Album, Albums
from .allowed import Allow, Allowed, Disallow
from .birthdays import Birthday, Birthdays
from .client import client
from .commands import Handler, aliases, built_in
from .config import Settings, config_file, get_settings
from .contacts import Contacts, Trust
from .delete import Delete
from .delivery import Delivery, receipts
from .fortune import Fortune
from .greeting import greeter
from .help import Help
from .incoming import Incoming, inbox
from .info import Info
from .languages import Language
from .lists import Lists
from .mentions import Mention
from .messages import describe, outbox
from .notices import notices
from .onthisday import OnThisDay
from .photos import Photo
from .ping import Ping
from .profile import About, Avatar, Name, Profile, Username
from .relay import Msg, Run
from .reminders import Remind
from .selfpromote import SelfPromote
from .specials import Specials, SpecialsForEveryone
from .status import Status
from .timers import Chats, Timers, timekeeper
from .today import Today, TodayPreview
from .weather import Forecast, Weather

logger = logging.getLogger(__name__)

# How often to look again for signal-cli-rest-api and the account at startup:
# the bot starts with signal-cli-rest-api, often before it answers
WAIT_RETRY = 5  # seconds
# Python's usual, with the date: journald and podman logs stamp lines
# anyway, but a log file or the terminal don't
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

# A handler, the contacts it answers, the groups it answers in, and what else
# a message must pass, if anything
type Check = Callable[[object], bool]
type Registration = tuple[Handler, list[str] | bool, list[str] | bool, Check | None]


def handlers(bot: SignalBot, settings: Settings) -> list[Registration]:
    """Every handler, with who it answers, as it says (Handler.everyday)."""

    def allowed(message: object) -> bool:
        return access.permits(bot, message)

    every: list[Handler] = [
        # The everyday commands, the admins' specials for everyone too
        Ping(),
        Photo(),
        Albums(),
        OnThisDay(),
        Today(),
        Weather(),
        Forecast(),
        Info(),
        Fortune(),
        Remind(),
        Lists(),
        Birthdays(),
        Language(),
        Help(),
        SpecialsForEveryone(),
        # The admins' commands: they show what only the admins should see,
        # or change the bot, who may use it, or its timers, or post to other
        # chats
        Status(),
        TodayPreview(),
        Album(),
        Specials(),
        Contacts(),
        Trust(),
        Allowed(),
        Allow(),
        Disallow(),
        Admins(),
        Admin(),
        Profile(),
        Name(),
        About(),
        Avatar(),
        Username(),
        Chats(),
        Timers(),
        Msg(),
        Run(),
        SelfPromote(),
        Incoming(),
        Birthday(),
        Delivery(),
    ]
    # The everyday commands for the admins and the allowed list, checked for
    # each message, as /allow and /disallow change it; the admins' in direct
    # chats only, also checked for each message, as /admin changes who they
    # are
    registrations: list[Registration] = [
        (handler, True, True, allowed)
        if handler.everyday
        else (handler, True, False, access.from_admin)
        for handler in every
    ]
    # For the admins only, in every chat
    registrations.append((Delete(), True, settings.delete_groups, access.from_admin))
    registrations.append((Mention(), True, True, access.from_admin))
    return registrations


def check_aliases() -> None:
    """Every alias, the bot's own, the language's and the settings', is
    another name for a command the bot comes with, and not a command itself.
    Not for the admins' own specials and shortcuts, which come and go as the
    bot runs. Raises ValueError."""
    for alias, command in aliases(shortcuts=False).items():
        if not built_in(command):
            raise ValueError(f"aliases: {command} isn't a command (for {alias})")
        if built_in(alias):
            raise ValueError(f"aliases: {alias} is a command already")


def settings_errors(error: ValidationError) -> str:
    """A line for each wrong setting, saying what's wrong with it."""
    lines: list[str] = []
    for problem in error.errors():
        setting = ".".join(map(str, problem["loc"])) or "the settings"
        if problem["type"] == "extra_forbidden":
            what = "no such setting: renamed or removed?"
        elif problem["type"] == "missing":
            what = "missing"
        else:
            what = problem["msg"]
        lines.append(f"  {setting}: {what}")
    return "\n".join(lines)


def refused(what: str, error: OSError, needs: str) -> str:
    """Why the bot can't use a file or folder, and if it's not allowed to,
    who it runs as, and what that user must be able to do."""
    why = f"{what}: {error.strerror or error}."
    if isinstance(error, PermissionError):
        why += f" The bot runs as uid {os.getuid()}, which must be able to {needs}."
    return why


def config_where(path: Path) -> str:
    """The config file, as the messages about it name it. Stops the bot if
    the file is there but can't be read: pydantic-settings would go on
    without it, as if there were none."""
    try:
        with path.open("rb"):
            pass
    except FileNotFoundError:
        return f"config file: {path}, not there"
    except OSError as e:
        sys.exit(
            refused(
                f"Can't read the config file {path}",
                e,
                "read it, and open the folders it's in",
            )
        )
    return f"config file: {path}"


def check_data_dir(path: Path) -> None:
    """Stop the bot unless it can write in data_dir: without it, what the bot
    is told would be gone at the next start. A file made, and gone at once,
    tells, whatever stands in the way."""
    try:
        with tempfile.TemporaryFile(dir=path):
            pass
    except FileNotFoundError:
        sys.exit(f"No data_dir {path}, for the timers and the allowed list")
    except OSError as e:
        sys.exit(refused(f"Can't write in data_dir {path}", e, "write in it"))


def load_settings() -> Settings:
    where = config_where(config_file())
    try:
        settings = get_settings()
        check_aliases()
    except ValidationError as e:
        sys.exit(
            f"Invalid configuration ({where}):\n{settings_errors(e)}\n\n"
            "nejomibot --example-config prints every setting (in the image, "
            "/app/config.example.toml has them too). Settings can also be given "
            "as environment variables NEJOMIBOT_<SETTING>."
        )
    except (ValueError, OSError) as e:  # a file that won't parse, or aliases
        sys.exit(f"Invalid configuration ({where}):\n{e}")
    logger.info("Read the settings (%s)", where)
    if not settings.debug:  # which keeps its files in a temp folder
        check_data_dir(settings.data_dir)
    if settings.debug:
        logger.warning("DEBUG mode: communicating with %s only", settings.debug_group)
    if not settings.photos_dir.is_dir():
        logger.warning("Photos directory does not exist: %s", settings.photos_dir)
    return settings


async def wait_for_account() -> None:
    """Wait until signal-cli-rest-api answers, is one signalbot starts with,
    and has the account, saying what to do meanwhile. signalbot would wait
    too, but without saying why.

    Meanwhile the container's health check hears that the bot works: no
    restart would help, and on a new install one would cut the account's
    setup short, as that runs in the bot's container.

    It runs on an event loop of its own, before signalbot's, so the HTTP
    session it uses is closed once it's done: a session can't move to
    another loop."""
    settings = get_settings()
    api = f"signal-cli-rest-api at {settings.signal_service}"
    said = ""
    try:
        async with health.answering(
            lambda: f"OK: waiting: {said}" if said else "OK: starting"
        ):
            while True:
                try:
                    if refused := health.refused_by_signalbot(await rest.about()):
                        why = f"{api} won't do: {refused}"
                    elif settings.account in await rest.accounts():
                        logger.info("%s has the account", api)
                        return
                    else:
                        why = (
                            f"{api} has no account {settings.account} yet: register "
                            "or link it with nejomibot-account setup"
                        )
                except rest.RestError as e:
                    why = f"{api} answers with an error: {e}"
                except Exception as e:
                    why = f"Can't reach {api}: {describe(e)}"
                if why != said:
                    logger.warning("%s. Waiting.", why)
                    said = why
                await asyncio.sleep(WAIT_RETRY)
    finally:
        await client.close()


def stop(signum: int, frame: FrameType | None) -> None:
    """Stop at once, on SIGTERM, until signalbot runs, which then stops the bot
    gracefully. Without an init process in the container (RunInit=, init:),
    the bot is its first process, which SIGTERM only stops if it handles it."""
    sys.exit(0)


def set_up_logging() -> None:
    """The bot's lines at INFO, till the settings say log_level; the libraries'
    only when something's wrong. signalbot logs its own way, through its own
    handler: through the bot's instead, so every line looks the same."""
    logging.basicConfig(level=logging.WARNING, format=LOG_FORMAT)
    logging.getLogger(__package__).setLevel(logging.INFO)


def shutdown() -> None:
    """Once signalbot has stopped, and with it its event loop: stop what's
    left of the bot's own work, keep the messages waiting to be sent, and
    close the loop, as asyncio.run would."""
    loop = asyncio.get_event_loop()  # signalbot's
    try:
        tasks = asyncio.all_tasks(loop)
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        outbox.keep_all()
        notices.stopped()
        loop.run_until_complete(health.stop())
        loop.run_until_complete(terminal.stop())
        loop.run_until_complete(client.close())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
    finally:
        loop.close()
    logger.info("Stopped")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="The Signal bot. It reads its settings from ./config.toml, or "
        "the file NEJOMIBOT_CONFIG names, and NEJOMIBOT_<SETTING> variables."
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {version('nejomibot')}"
    )
    parser.add_argument(
        "--example-config",
        action="store_true",
        help="print every setting, described, to start a config.toml from, and exit",
    )
    if parser.parse_args().example_config:
        print(files(__package__).joinpath("config.example.toml").read_text(), end="")
        return
    signal.signal(signal.SIGTERM, stop)
    set_up_logging()
    logger.info(
        "Starting nejomibot %s, with Python %s",
        version("nejomibot"),
        platform.python_version(),
    )
    settings = load_settings()
    logging.getLogger(__package__).setLevel(settings.log_level)
    asyncio.run(wait_for_account())

    bot = SignalBot(
        Config(
            signal_service=settings.signal_service,
            phone_number=settings.account,
            # signal-cli-rest-api has no HTTPS of its own
            connection_mode=ConnectionMode.HTTP_ONLY,
            # At INFO it logs every message it receives, in full
            logging_level=logging.WARNING,
            # No handler needs what's attached to every message: /avatar
            # fetches its picture itself
            download_attachments=False,
            # The bot keeps nothing in signalbot's storage, so memory will do
            storage=InMemoryConfig(),
        )
    )
    logging.getLogger(LOGGER_NAME).handlers.clear()  # see set_up_logging
    logger.debug(
        "signalbot set up, for signal-cli-rest-api at %s", settings.signal_service
    )
    outbox.start(bot)
    # The receipts for what it sends, for /delivery, and a warning in the log
    # for a message nobody's phone confirmed
    receipts.start(bot)
    # The admins hear of an update or a stop that wasn't clean, and more
    notices.start(bot)

    access.allowed_list.start()
    logger.info(
        "%d chats on the allowed list, in %s",
        len(access.allowed_list.entries),
        settings.allowed_file,
    )
    access.admin_list.start()
    logger.info(
        "%d admins besides the config's, in %s",
        len(access.admin_list.entries),
        settings.admins_file,
    )
    # Whose the phone numbers on the lists are, for their names, once ready
    access.start(bot)
    registrations = handlers(bot, settings)
    for handler, contacts, groups, check in registrations:
        bot.register(handler, contacts=contacts, groups=groups, f=check)
    # What anyone writes in a direct chat, and deletes, for /incoming
    bot.register(inbox, contacts=True, groups=False)
    # What anyone writes anywhere, and deletes, for nejomibot-chat
    bot.register(terminal.recent, contacts=True, groups=True)
    # A greeting for the allowed list's messages that aren't commands; it
    # checks who wrote them itself
    bot.register(greeter, contacts=True, groups=False)
    logger.debug("%d handlers registered", len(registrations) + 3)
    # Timers run their commands through the same handlers, but for those
    # their commands say timers mayn't
    timekeeper.start(bot, [handler for handler, *_who in registrations])
    logger.info("%d timers, in %s", len(timekeeper.timers), settings.timers_file)
    reminders.start(bot)
    logger.info(
        "%d reminders, in %s",
        len(reminders.kept.current().entries),
        settings.data_file(reminders.kept.name),
    )
    # When each photo was taken, read in the background for the commands that
    # need it, so the first of them after a start doesn't wait for it
    photos.start(bot)
    # The profile data_dir/bot.txt has, or config.toml's bot_* settings
    profile.start(bot)
    health.start(bot)
    # The admins' messages from nejomibot-chat, once signalbot is ready
    terminal.start(bot)

    logger.debug("Starting signalbot: its event loop and scheduler")
    bot.start()
    shutdown()
