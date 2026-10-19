"""Notices to the admins, in a direct chat with each, of what they'd otherwise
find out late:

- At a start after an update, the versions; after a stop that wasn't clean
  (a crash, a kill, a power cut), that the bot is up again. It knows from
  data_dir/run.json, which it writes as it starts, and again as it stops.
- When Signal starts rate-limiting the bot, how to lift the limit: once in
  six hours at most, and tried once, not kept to send later, as it may not
  get through either. The health check says so too, while messages wait.
- When someone's safety number changes, as signal-cli won't send to them
  until an admin trusts it. The bot looks every healthcheck_minutes, and at
  a start, for changes since it last ran.
"""

import asyncio
import logging
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from typing import Any

from pydantic import BaseModel, ValidationError
from signalbot import SendMessage, SignalBot

from . import access, rest
from .account import IDENTITIES, UNTRUSTED
from .config import get_settings
from .files import write_privately
from .i18n import _
from .messages import describe, outbox, send

logger = logging.getLogger(__name__)

RUN_FILE = "run.json"  # in data_dir
RATE_LIMIT_AGAIN = timedelta(hours=6)


class Run(BaseModel):
    """A run of the bot, as data_dir/run.json has it."""

    version: str
    started: datetime
    stopped: datetime | None = None  # when, if it stopped cleanly


def read_run() -> Run | None:
    """The run before this one, if the file has it."""
    path = get_settings().data_file(RUN_FILE)
    try:
        return Run.model_validate_json(path.read_bytes())
    except FileNotFoundError:
        return None
    except (OSError, ValidationError) as e:
        logger.warning("Could not read %s: %r", path, e)
        return None


def save_run(run: Run) -> None:
    path = get_settings().data_file(RUN_FILE)
    try:
        write_privately(path, run.model_dump_json())
    except OSError as e:
        logger.error("Could not save %s: %r", path, e)


def start_text(previous: Run | None, run: Run) -> str | None:
    """What the admins hear as the bot starts, if anything."""
    if previous is None:  # a first start, or debug mode
        return None
    lines: list[str] = []
    if previous.version != run.version:
        lines.append(
            _("🔄 Updated: nejomibot {old} → {new}.").format(
                old=previous.version, new=run.version
            )
        )
    if previous.stopped is None:
        since = previous.started.astimezone(get_settings().tz)
        lines.append(
            _(
                "⚠️ Up again, after a stop that wasn't clean, such as a crash, a "
                "kill or a power cut. It had run since {time}. Messages that had "
                "waited less than half a minute to be sent may be lost."
            ).format(time=f"{since:%Y-%m-%d %H:%M}")
        )
    return "\n\n".join(lines) or None


def rate_limited_text() -> str:
    return _(
        "⚠️ Signal rate-limits the bot, so messages wait, and are tried every half "
        "hour. To lift the limit, run signal-account.sh rate-limit --to <your "
        "number> on the server, and solve the captcha."
    )


def changed_text(name: str) -> str:
    return _(
        "🔐 The safety number of {name} has changed: they may have a new phone, "
        "or it may not be them. The bot can't send to them until it's trusted: "
        "compare it with theirs with /contacts {name}, then /trust."
    ).format(name=name)


class Notices:
    def __init__(self) -> None:
        self.run: Run | None = None  # this one
        self.previous: Run | None = None
        self.looked = datetime.now(UTC)  # at the safety numbers
        self.rate_limited_at: datetime | None = None  # when the admins were told
        self.tasks: set[asyncio.Task[None]] = set()

    def start(self, bot: SignalBot) -> None:
        """Note this run, beside the one before, and tell the admins once the
        bot is ready."""
        self.previous = read_run()
        self.run = Run(version=version("nejomibot"), started=datetime.now(UTC))
        save_run(self.run)
        if previous := self.previous:
            self.looked = previous.stopped or previous.started
        outbox.on_rate_limited = lambda: self.spawn(self.rate_limited(bot))
        bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
            self.serve,
            args=[bot],
            id="notices-start",
            misfire_grace_time=None,
            replace_existing=True,
        )

    def stopped(self) -> None:
        """As the bot stops cleanly."""
        if self.run is not None:
            save_run(self.run.model_copy(update={"stopped": datetime.now(UTC)}))

    def spawn(self, work: Coroutine[Any, Any, None]) -> None:
        """Run it beside what calls it, kept till it's done."""
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def serve(self, bot: SignalBot) -> None:
        """Once signalbot is ready: tell the admins of the start, if there's
        anything to tell, then look at the safety numbers every
        healthcheck_minutes."""
        await bot.wait_until_ready()
        if self.run is not None and (text := start_text(self.previous, self.run)):
            logger.info("Telling the admins of the start")
            await tell(bot, text)
        await self.look_at_safety_numbers(bot)
        bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
            self.look_at_safety_numbers,
            "interval",
            minutes=get_settings().healthcheck_minutes,
            args=[bot],
            id="notices-safety-numbers",
            misfire_grace_time=None,
            coalesce=True,
            max_instances=1,
            replace_existing=True,
        )

    async def rate_limited(self, bot: SignalBot) -> None:
        """Tell the admins that Signal rate-limits the bot, once in
        RATE_LIMIT_AGAIN at most, trying once."""
        now = datetime.now(UTC)
        if self.rate_limited_at and now - self.rate_limited_at < RATE_LIMIT_AGAIN:
            return
        self.rate_limited_at = now
        for admin in get_settings().admins:
            await outbox.try_once(admin, SendMessage(text=rate_limited_text()))

    async def look_at_safety_numbers(self, bot: SignalBot) -> None:
        """Tell the admins whose safety numbers have changed since the last
        look, and aren't trusted. Never raises."""
        now = datetime.now(UTC)
        try:
            identities = IDENTITIES.validate_python(await rest.identities())
        except Exception as e:
            logger.warning("Could not look at the safety numbers: %s", describe(e))
            return
        since, self.looked = self.looked, now
        changed = [
            identity
            for identity in identities
            if identity.status == UNTRUSTED
            and (added := identity.added_at) is not None
            and added > since
        ]
        if not changed:
            return
        names = await access.names(bot)
        for identity in changed:
            name = (
                names.get(identity.uuid or "")
                or names.get(identity.number or "")
                or identity.number
                or identity.uuid
                or "?"
            )
            logger.info("Telling the admins of a changed safety number")
            await tell(bot, changed_text(name))


async def tell(bot: SignalBot, text: str) -> None:
    """Send the text to each admin, waiting to be sent if need be."""
    for admin in get_settings().admins:
        await send(bot, admin, SendMessage(text=text))


notices = Notices()
