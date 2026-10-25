"""Notices to the admins, in a direct chat with each, of what they'd otherwise
find out late:

- At each start, that the bot is up, since when, and how long it took to be
  ready; after an update, the version before; after a stop that wasn't clean
  (a crash, a kill, a power cut), that messages may be lost. Then what needs
  their attention, such as lines of the bot's files it can't read, or a
  clock that isn't synchronized, and how the bot is: its timers, chats,
  photos and memory, its versions, and where it runs. Once in QUIET
  at most, but after an update: a start sooner after the last told waits
  till then, so a crash loop can't flood the admins, nor run into Signal's
  rate limits; should the bot stop meanwhile, the next start tells instead.
  It knows from data_dir/run.json, which it writes as it starts, as it
  tells, and as it stops. In debug mode, which keeps no files from one
  start to the next, each start tells.
- When Signal starts rate-limiting the bot, how to lift the limit: once in
  six hours at most, and tried once, not kept to send later, as it may not
  get through either. The health check says so too, while messages wait.
- When someone's safety number changes, as signal-cli won't send to them
  until an admin trusts it. The bot looks every healthcheck_minutes, and at
  a start, for changes since it last ran.
"""

import asyncio
import inspect
import logging
import os
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, datetime, timedelta
from functools import partial
from importlib.metadata import version
from typing import Any

from pydantic import BaseModel, ValidationError
from signalbot import About, SendMessage, SignalBot, TextMode

from . import access, birthdays, lists, photos, reminders, rest, system
from .account import IDENTITIES, UNTRUSTED, by_ids, fetch_recipients, find_by_ids
from .config import get_settings
from .files import write_privately
from .health import (
    CHECK_TIMEOUT,
    STARTED,
    Check,
    memory_check,
    run_check,
    version_lines,
)
from .i18n import (
    _,
    by_language,
    chat_language,
    chat_languages,
    day_and_time,
    format_duration,
    ngettext,
    speaking,
    when_text,
)
from .messages import RATE_LIMITED_FIRST, describe, escape, outbox, send
from .specials import own_specials
from .status import check_photos, clock_check
from .timers import timekeeper

logger = logging.getLogger(__name__)

RUN_FILE = "run.json"  # in data_dir
RATE_LIMIT_AGAIN = timedelta(hours=6)
# The least time between two notices of a start, but for an update's
QUIET = timedelta(minutes=10)


class Run(BaseModel):
    """A run of the bot, as data_dir/run.json has it."""

    version: str
    started: datetime
    stopped: datetime | None = None  # when, if it stopped cleanly
    told: datetime | None = None  # when the admins last heard of a start


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


# The notice of a start


def header_text(run: Run, ready: datetime) -> str:
    """The bot and its version, in bold, then when it started, in the bot's
    time zone, and how long it took to be ready. Styled."""
    title = _("nejomibot {version} started").format(version=run.version)
    when = day_and_time(run.started.astimezone(get_settings().tz))
    took = _("ready in {duration}").format(
        duration=format_duration(ready - run.started)
    )
    return f"🟢 **{escape(title)}**\n{escape(f'{when} · {took}')}"


def previous_lines(previous: Run | None, run: Run, now: datetime) -> list[str]:
    """What the admins should know of the run before: its version, if this
    is an update, and whether it stopped cleanly."""
    if previous is None:  # a first start, or debug mode
        return []
    lines: list[str] = []
    if previous.version != run.version:
        lines.append(_("🔄 Updated from {version}").format(version=previous.version))
    if previous.stopped is None:
        lines.append(
            _(
                "⚠️ The previous run, started {time}, did not shut down cleanly, "
                "as after a crash, a forced stop or a power failure. Messages "
                "queued for less than 30 seconds may have been lost."
            ).format(time=when_text(previous.started, now))
        )
    return lines


def unreadable_lines() -> list[str]:
    """For each of the bot's files with lines it can't read, how many. It
    leaves them as they are, and they do nothing, as a timer's that names a
    command the bot no longer has."""
    settings = get_settings()
    timekeeper.reread()
    counts = {
        settings.timers_file.name: len(timekeeper.broken),
        settings.specials_file.name: len(own_specials.current().broken),
        settings.allowed_file.name: len(access.allowed_list.current().broken),
        settings.admins_file.name: len(access.admin_list.current().broken),
    }
    for kept in (
        birthdays.kept,
        reminders.kept,
        lists.kept,
        photos.album_settings,
        chat_languages,
    ):
        counts[kept.name] = len(kept.current().broken)
    return [
        ngettext(
            "⚠️ {file}: {count} unreadable line, ignored and left unchanged",
            "⚠️ {file}: {count} unreadable lines, ignored and left unchanged",
            count,
        ).format(file=file, count=count)
        for file, count in counts.items()
        if count
    ]


def waiting_lines() -> list[str]:
    """The messages from before that wait to be sent again, if any."""
    if not (waiting := len(outbox)):
        return []
    text = ngettext(
        "{count} message queued for retry",
        "{count} messages queued for retry",
        waiting,
    ).format(count=waiting)
    return [f"📤 {text}"]


def timers_line() -> str:
    """How many timers, and when one runs next, in the bot's time zone."""
    if not (count := len(timekeeper.timers)):
        return _("⏰ No timers")
    if (at := timekeeper.next_run()) is None:
        return ngettext("⏰ {count} timer", "⏰ {count} timers", count).format(
            count=count
        )
    return ngettext(
        "⏰ {count} timer, next run {when}",
        "⏰ {count} timers, next run {when}",
        count,
    ).format(count=count, when=day_and_time(at.astimezone(get_settings().tz)))


def chats_line(bot: SignalBot) -> str:
    """The groups the bot is in, the chats on the allowed list, and the
    admins."""
    groups = sum(1 for group in bot.groups if group.member)
    allowed = len(access.allowed_list.current().entries)
    admins = len(access.admins())
    parts = [
        ngettext("Member of {count} group", "Member of {count} groups", groups).format(
            count=groups
        ),
        ngettext("{count} chat allowed", "{count} chats allowed", allowed).format(
            count=allowed
        ),
        ngettext("{count} admin", "{count} admins", admins).format(count=admins),
    ]
    return "👥 " + " · ".join(parts)


def host_line() -> str:
    """Where the bot runs: its host, in a container if it is, and the
    machine."""
    uname = os.uname()
    where = uname.nodename
    if engine := system.container_engine():
        where = _("{engine} on {host}").format(engine=engine.capitalize(), host=where)
    return f"🖥️ {where} · {uname.machine}"


def check_line(icon: str, check: Check) -> str:
    """The check's name and what it found, after its icon, or after ⚠️ if it
    failed."""
    return f"{icon if check.ok else '⚠️'} {check.name}: {check.shown}"


def local_checks() -> list[tuple[str, Check]]:
    """The checks of the host's state for a start's notice, with their icons.
    Blocking: reads /proc and /sys."""
    return [("🕐", clock_check()), ("🧠", memory_check())]


async def about_of(bot: SignalBot) -> About | None:
    """signal-cli-rest-api's version and mode, if it says them in time."""
    try:
        async with asyncio.timeout(CHECK_TIMEOUT):
            return await bot.general.about()
    except Exception as e:
        logger.warning("signal-cli-rest-api didn't say its version: %s", describe(e))
        return None


async def start_text(
    bot: SignalBot, previous: Run | None, run: Run, ready: datetime
) -> str:
    """What the admins hear of a start: when, and how it went; then what
    needs their attention, if anything; then how the bot is. Styled."""
    settings = get_settings()
    about, photos, checks = await asyncio.gather(
        about_of(bot),
        run_check(_("Photo library"), check_photos),
        asyncio.to_thread(local_checks),
    )
    checks = [("📷", photos), *checks]
    _nejomibot, runtime, api = version_lines(about)
    debug = _("Debug mode: communicating with {group} only").format(
        group=settings.debug_group
    )
    attention = [
        *([f"🐞 {debug}"] if settings.debug else []),
        *previous_lines(previous, run, datetime.now(UTC)),
        *unreadable_lines(),
        *([f"⚠️ {api}"] if about is None else []),
        *(check_line(icon, check) for icon, check in checks if not check.ok),
        *waiting_lines(),
    ]
    state = [
        timers_line(),
        chats_line(bot),
        *(check_line(icon, check) for icon, check in checks if check.ok),
    ]
    runs = [*([f"🔌 {api}"] if about else []), f"🐍 {runtime}", host_line()]
    blocks = [escape("\n".join(lines)) for lines in (attention, state, runs) if lines]
    return "\n\n".join([header_text(run, ready), *blocks])


# The other notices


def rate_limited_text() -> str:
    longest = timedelta(minutes=get_settings().rate_limit_retry_minutes)
    return _(
        "⚠️ Signal is rate-limiting the bot. Outgoing messages wait: the bot "
        "tries one again after {first}, then less and less often, every "
        "{longest} at most, and sends the rest once one goes out. To lift the "
        "limit, run signal-account.sh rate-limit --to <your number> on the "
        "server and solve the captcha, then send the bot any command: it tries "
        "again at once."
    ).format(
        first=format_duration(RATE_LIMITED_FIRST), longest=format_duration(longest)
    )


def changed_text(name: str) -> str:
    return _(
        "🔐 The safety number for {name} has changed. This usually means a new "
        "phone or a reinstall, but it may also mean that someone else is using "
        "the account. Messages to {name} cannot be sent until the new safety "
        "number is trusted: compare it with the one on their phone using "
        "/contacts {name}, then confirm it with /trust."
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
        self.run = Run(
            version=version("nejomibot"),
            started=STARTED,
            told=self.previous.told if self.previous else None,
        )
        save_run(self.run)
        if previous := self.previous:
            self.looked = previous.stopped or previous.started
            logger.debug(
                "The run before: %s, started %s, %s",
                previous.version,
                previous.started,
                f"stopped {previous.stopped}" if previous.stopped else "no clean stop",
            )
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
        """Once signalbot is ready: tell the admins of the start, beside what
        follows, then look at the safety numbers every healthcheck_minutes."""
        await bot.wait_until_ready()
        ready = datetime.now(UTC)
        logger.info("Ready, %.1f s after the start", (ready - STARTED).total_seconds())
        self.spawn(self.tell_of_start(bot, ready))
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

    def delay(self, now: datetime) -> timedelta:
        """How long to wait before telling the admins of this start: not at
        all after an update, else until QUIET after they last heard of one."""
        run, previous = self.run, self.previous
        if run is None or run.told is None:
            return timedelta()
        if previous is not None and previous.version != run.version:
            return timedelta()
        # QUIET at most, should the clock have been set back since
        return max(min(run.told + QUIET - now, QUIET), timedelta())

    async def tell_of_start(self, bot: SignalBot, ready: datetime) -> None:
        """Tell the admins of this start, which was ready then, once its
        delay is over. Never raises."""
        if (wait := self.delay(datetime.now(UTC))) > timedelta():
            logger.info("Telling the admins of the start in %d s", wait.total_seconds())
            await asyncio.sleep(wait.total_seconds())
        if (run := self.run) is None:
            return
        previous = self.previous
        try:
            texts = await worded(lambda: start_text(bot, previous, run, ready))
        except Exception:
            logger.exception("Could not say how the start went")
            return
        logger.info("Telling the admins of the start")
        await tell(bot, texts, styled=True)
        self.run = run.model_copy(update={"told": datetime.now(UTC)})
        save_run(self.run)

    async def rate_limited(self, bot: SignalBot) -> None:
        """Tell the admins that Signal rate-limits the bot, once in
        RATE_LIMIT_AGAIN at most, trying once."""
        now = datetime.now(UTC)
        if self.rate_limited_at and now - self.rate_limited_at < RATE_LIMIT_AGAIN:
            return
        self.rate_limited_at = now
        for admin in get_settings().admins:
            with speaking(chat_language(admin)):
                text = rate_limited_text()
            await outbox.try_once(admin, SendMessage(text=text))

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
        # Named as /contacts finds them, which the notice says to use: by
        # signal-cli's name, else by number or ID
        try:
            known = by_ids(await fetch_recipients())
        except Exception as e:
            logger.warning("Could not look up the names: %s", describe(e))
            known = {}
        for identity in changed:
            contact = find_by_ids(known, identity.number, identity.uuid)
            name = (
                (contact.real_name if contact else None)
                or identity.number
                or identity.uuid
                or "?"
            )
            logger.info("Telling the admins of a changed safety number")
            await tell(bot, await worded(partial(changed_text, name)))


async def worded(words: Callable[[], str | Awaitable[str]]) -> dict[str, str]:
    """What words() says in each language the admins speak, by its code:
    worded once for each, mostly one."""
    texts: dict[str, str] = {}
    for code in by_language(get_settings().admins):
        with speaking(code):
            text = words()
            texts[code] = await text if inspect.isawaitable(text) else text
    return texts


async def tell(bot: SignalBot, texts: dict[str, str], *, styled: bool = False) -> None:
    """Send each admin the text in their language, of texts by code, waiting
    to be sent if need be."""
    mode = TextMode.STYLED if styled else None
    for code, admins in by_language(get_settings().admins).items():
        for admin in admins:
            await send(bot, admin, SendMessage(text=texts[code], text_mode=mode))


notices = Notices()
