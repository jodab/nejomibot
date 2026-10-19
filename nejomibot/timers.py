"""Timers: the bot runs commands on a schedule and posts the answers to chats,
such as the daily post: /timer add 08:00 1,2 /dailypost.

The admins manage them in a direct chat with the bot. /chats numbers the
chats a timer can post to: the groups the bot is in, then the people on the
allowed list, then the admins. /timer add 08:00 1,2 /weather; /photo adds a
timer that posts to chats 1 and 2 (or, without numbers, to the admin);
/timers lists them, /timer remove 3 removes one, and /timer run 3 runs one
now.

A timer runs each command once, as an admin would in a direct chat with the
bot, so it can run any command but those that manage timers, specials or the
allowed list, or post to chats of their own. Its answers are collected rather
than sent, then posted to each of the timer's chats, so every group gets the
same photo.

Timers are kept in data_dir/timers.txt, one per line, which
nejomibot-timers edits too: the bot rereads the file when it changes. In debug
mode it's a temp file, empty at each start. A run due while the bot was down
is made when it starts again, up to an hour late.
"""

import contextlib
import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from signalbot import (
    DataMessage,
    DataMessageContext,
    DataMessageHandler,
    SendMessage,
    SignalBot,
)

from . import access
from .commands import Command, Handler, answer, canonical, known
from .config import SIGNAL_ID, get_settings
from .files import write_privately
from .i18n import _, day_and_time, language_words, ngettext
from .messages import collected, escape, send

logger = logging.getLogger(__name__)

# A run this late is still made, after a restart
CATCH_UP = timedelta(hours=1)
# How often the bot looks for changes to the file, from nejomibot-timers
REREAD = timedelta(seconds=30)
MIN_EVERY = timedelta(minutes=10)
MAX_TIMERS = 50
MAX_COMMANDS = 10

HEADER = (
    "# nejomibot's timers, one per line:",
    "#   number | when | chats | commands | last run",
    "# Changed with /timer in Signal, or nejomibot-timers; the bot rereads it",
    "# within a minute of a change. The last run is when it last ran, or was",
    "# added. Chats are group IDs and phone numbers, separated by spaces.",
)

# The words of <when>, as the timers file keeps them. The language may have
# more for each (i18n.language_words).
DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FULL_DAY_NAMES = (
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
)  # fmt: skip
EVERY_DAY = frozenset(range(7))
WEEKDAYS = frozenset(range(5))
WEEKENDS = frozenset({5, 6})
DAY_SETS = {
    "daily": EVERY_DAY,
    "weekdays": WEEKDAYS,
    "weekends": WEEKENDS,
    "weekend": WEEKENDS,
}
DAYS_FROM_NOW = {"today": 0, "tomorrow": 1}
EVERY = "every"
CLOCK = re.compile(r"^([01]?\d|2[0-3])[:.]([0-5]\d)$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DURATION = re.compile(r"^(?:(\d+)h)?(?:(\d+)m(?:in)?)?$")


def in_language[T](table: dict[str, T]) -> dict[str, T]:
    """The table, with the language's words for each of its words."""
    return {
        name.casefold(): value
        for word, value in table.items()
        for name in language_words(word)
    }


def day_words() -> dict[str, int]:
    """Days by name, Monday 0: mon, monday, and the language's."""
    return in_language(
        {
            name: day
            for names in (DAY_NAMES, FULL_DAY_NAMES)
            for day, name in enumerate(names)
        }
    )


def shown(when: str) -> str:
    """A schedule's text in the language: its words as the language has them
    first, e.g. 'weekdays 07:30' as 'vardagar 07:30' in Swedish."""

    def word(text: str) -> str:
        names = language_words(text)
        return names[1] if len(names) > 1 else text

    return " ".join(",".join(map(word, part.split(","))) for part in when.split())


def example_date(today: date) -> str:
    """A date for the examples that's still to come: the next Christmas Eve."""
    eve = date(today.year, 12, 24)
    return f"{eve if today < eve else eve.replace(year=today.year + 1):%Y-%m-%d}"


def when_help() -> str:
    return _(
        "<when> is a time (08:00, or 08:00,18:30), days and a time (mon-fri "
        "07:30, sat,sun 10:00), a date and a time for once ({date} 15:00, "
        "tomorrow 08:00), or every 2h or 30m"
    ).format(date=example_date(datetime.now(get_settings().tz).date()))


def usage() -> str:
    zone = get_settings().timezone.rsplit("/", 1)[-1].replace("_", " ")
    return "\n".join(
        [
            _("/chats: where timers can post, numbered"),
            _("/timers: the timers"),
            _("/timer add <when> [<chats>] <commands>: a new one, e.g."),
            "  " + _("/timer add mon-fri 07:30 1,2 /weather; /photo"),
            "  "
            + _("The chats are numbers from /chats; without them, it posts to you."),
            _("/timer remove <n>, /timer run <n>: remove one, or run it now"),
            _("{when_help}, in {zone} time.").format(when_help=when_help(), zone=zone),
        ]
    )


# When


@dataclass(frozen=True)
class Schedule:
    """When a timer runs: at times on some days, once, or every so often."""

    text: str  # as shown and kept: it reads back as the same schedule
    days: frozenset[int] = EVERY_DAY  # Monday is 0
    times: tuple[time, ...] = ()
    once: datetime | None = None
    every: timedelta | None = None


def parse_days(word: str) -> frozenset[int] | None:
    """'mon' or a range, 'mon-fri' (or 'fri-mon', round the weekend)."""
    days = day_words()
    first, _dash, last = word.partition("-")
    if first not in days or (last and last not in days):
        return None
    start, end = days[first], days[last or first]
    return frozenset((start + i) % 7 for i in range((end - start) % 7 + 1))


def days_text(days: frozenset[int]) -> str:
    if days == EVERY_DAY:
        return "daily"
    if days == WEEKDAYS:
        return "weekdays"
    if days == WEEKENDS:
        return "weekends"
    return ",".join(DAY_NAMES[day] for day in sorted(days))


def duration_text(every: timedelta) -> str:
    """E.g. '2h', '30m' or '1h30m'."""
    hours, minutes = divmod(int(every.total_seconds()) // 60, 60)
    return f"{hours}h" * bool(hours) + f"{minutes}m" * bool(minutes)


def parse_every(amount: str) -> Schedule | str:
    match = DURATION.match(amount)
    if not amount or not match or not (match[1] or match[2]):
        return _("Every how long? Like every 30m, every 2h or every 1h30m.")
    every = timedelta(hours=int(match[1] or 0), minutes=int(match[2] or 0))
    if every < MIN_EVERY:
        return _("Not more often than every {every}.").format(
            every=duration_text(MIN_EVERY)
        )
    return Schedule(text=f"{EVERY} {duration_text(every)}", every=every)


def parse_when(text: str, now: datetime) -> Schedule | str:
    """The schedule in the text, or why it isn't one. Times are in now's time
    zone, the bot's; 'today' and 'tomorrow' become dates."""
    parts = [part for part in re.split(r"[\s,]+", text.casefold()) if part]
    if parts[:2] == [EVERY, "day"]:
        parts = ["daily", *parts[2:]]
    if parts and parts[0] in in_language({EVERY: True}):
        return parse_every("".join(parts[1:]))
    day_sets = in_language(DAY_SETS)
    days_from_now = in_language(DAYS_FROM_NOW)
    days: set[int] = set()
    times: set[time] = set()
    on: date | None = None
    for part in parts:
        if match := CLOCK.match(part):
            times.add(time(int(match[1]), int(match[2])))
        elif part in day_sets:
            days |= day_sets[part]
        elif (some_days := parse_days(part)) is not None:
            days |= some_days
        elif part in days_from_now:
            on = now.date() + timedelta(days=days_from_now[part])
        elif DATE.match(part):
            try:
                on = date.fromisoformat(part)
            except ValueError:
                return _("There's no such day as {day}.").format(day=part)
        else:
            return f"{part}? {when_help()}."
    if not times:
        return _("At what time?") + f" {when_help()}."
    clock = ",".join(f"{at:%H:%M}" for at in sorted(times))
    if on is not None:
        if days or len(times) > 1:
            return _("A timer on a date runs once: give it one time, and no days.")
        once = datetime.combine(on, min(times), now.tzinfo)
        return Schedule(text=f"{on:%Y-%m-%d} {clock}", once=once)
    on_days = frozenset(days) or EVERY_DAY
    return Schedule(
        text=f"{days_text(on_days)} {clock}", days=on_days, times=tuple(sorted(times))
    )


# The timers file


@dataclass
class Timer:
    id: int
    when: str  # a Schedule's text
    chats: list[str]  # group IDs (group.…) and people's numbers
    commands: list[str]
    last: datetime  # when it last ran, or was added


def just_now() -> datetime:
    """Now, to the second, as the file keeps it."""
    return datetime.now(UTC).replace(microsecond=0)


def line_of(timer: Timer) -> str:
    """E.g. '1 | daily 08:00 | group.… +4670… | /weather; /photo | 2026-…'."""
    last = timer.last.astimezone(get_settings().tz).isoformat(" ", "seconds")
    chats, commands = " ".join(timer.chats), "; ".join(timer.commands)
    return f"{timer.id} | {timer.when} | {chats} | {commands} | {last}"


def number_of(line: str) -> int | None:
    """The number a line of the file starts with, if it does."""
    first = line.split("|", 1)[0].strip().lstrip("#")
    return int(first) if first.isdigit() else None


def parse_line(line: str, now: datetime) -> Timer:
    """A line of the file, as line_of writes it. Raises ValueError."""
    fields = [field.strip() for field in line.split("|")]
    if len(fields) != 5:
        raise ValueError(f"{len(fields)} fields, not 5")
    number, when, chats, commands, last = fields
    if isinstance(schedule := parse_when(when, now), str):
        raise ValueError(schedule)
    timer = Timer(
        id=int(number.lstrip("#")),
        when=schedule.text,
        chats=chats.split(),
        # By their English names, so the timer doesn't hang on a language or
        # an alias that may change
        commands=[
            canonical(command.strip())
            for command in commands.split(";")
            if command.strip()
        ],
        last=datetime.fromisoformat(last),
    )
    if not timer.chats or not timer.commands:
        raise ValueError("no chats or no commands")
    if why_not := check_commands(timer.commands):
        raise ValueError(why_not)
    if timer.last.tzinfo is None:
        timer.last = timer.last.replace(tzinfo=get_settings().tz)
    return timer


def missed_run(timer: Timer, schedule: Schedule, now: datetime) -> datetime | None:
    """The run due while the bot was down, if it's recent enough to still make
    and later than the timer's last run (or its adding)."""
    if schedule.every:
        return None
    if schedule.once:
        candidates = [schedule.once]
    else:
        candidates = [
            datetime.combine(day, at, now.tzinfo)
            for day in (now.date() - timedelta(days=1), now.date())
            if day.weekday() in schedule.days
            for at in schedule.times
        ]
    due = [at for at in candidates if timer.last < at <= now <= at + CATCH_UP]
    return max(due, default=None)


class Timekeeper:
    """The timers: kept in the file, scheduled with the bot's scheduler, and
    run through its handlers."""

    def __init__(self) -> None:
        self.timers: dict[int, Timer] = {}
        self.broken: list[str] = []  # lines that can't be read, kept as they are
        self.seen: tuple[int, int] | None = None  # the file's mtime and size
        self.bot: SignalBot | None = None
        self.handlers: list[DataMessageHandler] = []

    def read(self) -> None:
        """Read the file; if it can't be read, the timers stay as they were."""
        path = get_settings().timers_file
        now = datetime.now(get_settings().tz)
        try:
            stat = path.stat()  # first, so a change while reading shows next time
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            self.timers, self.broken, self.seen = {}, [], None
            return
        except (OSError, UnicodeError) as e:
            logger.error("Could not read %s, the timers stay as they were: %r", path, e)
            with contextlib.suppress(OSError):  # so it's logged once a change
                stat = path.stat()
                self.seen = (stat.st_mtime_ns, stat.st_size)
            return
        timers: dict[int, Timer] = {}
        broken: list[str] = []
        for number, line in enumerate(lines, start=1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            try:
                timer = parse_line(line, now)
                if timer.id in timers:
                    raise ValueError(f"a second timer {timer.id}")
            except ValueError as e:
                logger.error("Line %d left alone, as it can't be read: %s", number, e)
                broken.append(line)
                continue
            timers[timer.id] = timer
        self.timers, self.broken = timers, broken
        self.seen = (stat.st_mtime_ns, stat.st_size)

    def write(self) -> None:
        """Through a temp file, so a failed write loses nothing."""
        path = get_settings().timers_file
        timers = sorted(self.timers.values(), key=lambda timer: timer.id)
        lines = [*HEADER, *map(line_of, timers), *self.broken]
        write_privately(path, "\n".join(lines) + "\n")
        stat = path.stat()
        self.seen = (stat.st_mtime_ns, stat.st_size)

    def changed(self) -> bool:
        try:
            stat = get_settings().timers_file.stat()
        except FileNotFoundError:
            return self.seen is not None
        except OSError:
            return False  # can't tell: the timers stay as they are
        return (stat.st_mtime_ns, stat.st_size) != self.seen

    def reread(self) -> None:
        """Take in changes made to the file elsewhere, e.g. by nejomibot-timers."""
        if self.changed():
            self.read()
            self.schedule_all()
            logger.info("The timers file changed: %d timers", len(self.timers))

    async def look_for_changes(self) -> None:
        """reread, on the event loop: the scheduler would run a plain function
        in a thread of its own, beside everything else."""
        self.reread()

    def start(self, bot: SignalBot, handlers: Iterable[DataMessageHandler]) -> None:
        """Read the timers, or start the file, and schedule them. A run missed
        while the bot was down, recently enough, is made once it's ready."""
        self.bot = bot
        self.handlers = list(handlers)
        settings = get_settings()
        if settings.timers_file.exists():
            self.read()
        else:
            self.timers = {}
            self.write_quietly()
        now = datetime.now(settings.tz)
        for timer in list(self.timers.values()):
            schedule = self.schedule_of(timer)
            if due := missed_run(timer, schedule, now):
                logger.warning("Timer %d was due at %s, running it now", timer.id, due)
                self.add_job(f"catch-up-{timer.id}", timer.id)
            elif schedule.once and schedule.once <= now:
                logger.warning(
                    "Timer %d was due at %s: too long ago", timer.id, timer.when
                )
                del self.timers[timer.id]
                self.write_quietly()
        self.schedule_all()
        bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
            self.look_for_changes,
            "interval",
            seconds=int(REREAD.total_seconds()),
            id="timers-reread",
            # However late, rather than skipped when more than a second late
            misfire_grace_time=None,
            coalesce=True,
            replace_existing=True,
        )

    def write_quietly(self) -> None:
        try:
            self.write()
        except OSError as e:
            logger.error("Could not save the timers: %r", e)

    def schedule_of(self, timer: Timer) -> Schedule:
        schedule = parse_when(timer.when, datetime.now(get_settings().tz))
        assert isinstance(schedule, Schedule)  # it was read as one
        return schedule

    def add_job(self, job_id: str, timer_id: int, **trigger: Any) -> None:
        """A run of the timer; without a trigger, one as soon as the scheduler
        runs. None outside the bot, as in nejomibot-timers."""
        if self.bot is None:
            return
        self.bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
            self.run,
            id=job_id,
            args=[timer_id],
            misfire_grace_time=int(CATCH_UP.total_seconds()),
            coalesce=True,
            replace_existing=True,
            **trigger,
        )

    def jobs(self, timer_id: int | None = None) -> list[Any]:
        if self.bot is None:  # outside the bot
            return []
        prefix = "timer-" if timer_id is None else f"timer-{timer_id}-"
        jobs: list[Any] = self.bot.scheduler.get_jobs()  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        return [job for job in jobs if job.id.startswith(prefix)]

    def schedule_all(self) -> None:
        for job in self.jobs():
            job.remove()
        for timer in self.timers.values():
            self.schedule(timer)

    def schedule(self, timer: Timer) -> None:
        settings = get_settings()
        schedule = self.schedule_of(timer)
        job_id = f"timer-{timer.id}"
        if schedule.every:
            # From its last run, so a restart keeps the rhythm
            self.add_job(
                f"{job_id}-0",
                timer.id,
                trigger="interval",
                seconds=int(schedule.every.total_seconds()),
                start_date=timer.last + schedule.every,
                timezone=settings.tz,
            )
        elif schedule.once:
            if schedule.once > datetime.now(settings.tz):
                self.add_job(
                    f"{job_id}-0", timer.id, trigger="date", run_date=schedule.once
                )
        else:
            days = (
                "*"
                if schedule.days == EVERY_DAY
                else ",".join(DAY_NAMES[day] for day in sorted(schedule.days))
            )
            for n, at in enumerate(schedule.times):
                self.add_job(
                    f"{job_id}-{n}",
                    timer.id,
                    trigger="cron",
                    day_of_week=days,
                    hour=at.hour,
                    minute=at.minute,
                    timezone=settings.tz,
                )

    def next_run(self, timer_id: int) -> datetime | None:
        # Jobs only get next_run_time once the scheduler has started
        times = (getattr(job, "next_run_time", None) for job in self.jobs(timer_id))
        return min((t for t in times if t), default=None)

    def new(self, when: str, chats: list[str], commands: list[str]) -> Timer:
        """A timer to add, numbered past the others, and past lines that can't
        be read, too, as they may be set right."""
        self.reread()
        taken = [*self.timers, *filter(None, map(number_of, self.broken))]
        return Timer(max(taken, default=0) + 1, when, chats, commands, just_now())

    def add(self, when: str, chats: list[str], commands: list[str]) -> Timer:
        timer = self.new(when, chats, commands)
        self.timers[timer.id] = timer
        try:
            self.write()
        except OSError:
            del self.timers[timer.id]
            raise
        self.schedule(timer)
        return timer

    def remove(self, timer_id: int) -> Timer | None:
        self.reread()
        if (timer := self.timers.pop(timer_id, None)) is None:
            return None
        try:
            self.write()
        except OSError:
            self.timers[timer_id] = timer
            raise
        for job in self.jobs(timer_id):
            job.remove()
        return timer

    async def run(self, timer_id: int, *, on_schedule: bool = True) -> None:
        """Run the timer's commands and post their answers to its chats, one
        command after the other. Never raises."""
        self.reread()
        if (timer := self.timers.get(timer_id)) is None or self.bot is None:
            return
        await self.bot.wait_until_ready()
        # By name, as what follows may name someone: answer() logs it at DEBUG
        names = "; ".join(command.split()[0] for command in timer.commands)
        logger.info("Timer %d: %s", timer.id, names)
        member_of = {group.id for group in self.bot.groups if group.member}
        chats = [c for c in timer.chats if c in member_of or not c.startswith("group.")]
        if left := set(timer.chats) - set(chats):
            logger.warning(
                "Timer %d: the bot isn't in %d of its groups", timer.id, len(left)
            )
        for command in timer.commands:
            for message in await self.answers_to(command):
                for chat in chats:
                    await send(self.bot, chat, message)
        if on_schedule:
            self.reread()
            if (timer := self.timers.get(timer_id)) is not None:
                timer.last = just_now()
                if self.schedule_of(timer).once:
                    del self.timers[timer_id]
                self.write_quietly()

    async def answers_to(self, command: str) -> list[SendMessage]:
        """Run the command as an admin would in a direct chat with the bot, and
        collect its answers; none for a command timers mayn't run, which
        check_commands keeps out anyway, or one that's gone, as a special
        taken out of its file by hand."""
        assert self.bot is not None
        if (found := known(canonical(command))) is None or not found.timers:
            logger.error(
                "Not run, as timers mayn't, or it's gone: %s", command.split()[0]
            )
            return []
        settings = get_settings()
        sender = (settings.admins or [settings.account])[0]
        by_id = bool(re.match(SIGNAL_ID, sender))
        ms = int(datetime.now(UTC).timestamp() * 1000)
        message = DataMessage(
            server_delivered_timestamp=ms,
            server_received_timestamp=ms,
            timestamp=ms,
            source_number=None if by_id else sender,
            source_uuid=sender if by_id else None,
            text=command,
        )
        answers: list[SendMessage] = []
        token = collected.set(answers)
        try:
            for handler in self.handlers:
                try:
                    await handler.handle_data_message(
                        DataMessageContext(self.bot, message)
                    )
                except Exception:
                    logger.exception("Timer command %s failed", found.name)
        finally:
            collected.reset(token)
        return answers


timekeeper = Timekeeper()


# What a timer can run: any command but those that manage timers, specials or
# who may use the bot, or post to chats of their own (Command.timers)


def check_commands(
    commands: list[str], find: Callable[[str], Command | None] = known
) -> str | None:
    """Why the commands can't be a timer's, /run's or a special's, if they
    can't. find knows the commands: a special's, only built_in ones."""
    for command in commands:
        found = find(canonical(command))
        if found is not None and not found.timers:
            return _(
                "Timers, specials and /run can't manage timers, specials or who "
                "may use the bot, nor run /msg, /run or /incoming."
            )
        if "|" in command:
            return _("A timer's commands can't have a |: the timers file uses it.")
        if found is None:
            return _("{command} isn't a command the bot knows.").format(command=command)
    return None


def split_commands(text: str) -> list[str] | str:
    """The commands in the text, each with its /, separated by ; or line
    breaks; or why they aren't commands."""
    commands = [command.strip() for command in re.split(r"[;\n]", text)]
    commands = [command for command in commands if command]
    if bad := [command for command in commands if not command.startswith("/")]:
        return _("Commands start with /, unlike {command}.").format(command=bad[0])
    if len(commands) > MAX_COMMANDS:
        return _("At most {count} commands at once.").format(count=MAX_COMMANDS)
    return commands


def parse_add(text: str) -> tuple[str, list[int], list[str]] | str:
    """'/timer add <when> [<chats>] <commands>' -> (when, chat numbers,
    commands). The chats are the numbers just before the first command; the
    commands start at the first /, separated by ;."""
    rest = text.split(maxsplit=2)[2] if len(text.split()) > 2 else ""
    start = re.search(r"(?:^|\s)/", rest)
    if start is None:
        return _("Which commands?") + f"\n\n{usage()}"
    words = [word for word in re.split(r"[\s,]+", rest[: start.start()]) if word]
    numbers: list[int] = []
    while words and words[-1].isdigit():
        numbers.insert(0, int(words.pop()))
    if isinstance(commands := split_commands(rest[start.start() :]), str):
        return commands
    return " ".join(words), numbers, commands


# The chats


type Chat = tuple[str, str]  # an ID (group.… or a number), and its name


def people() -> list[str]:
    """The people a timer can post to, in /chats' order: those on the allowed
    list, as it lists them, then the admins."""
    allowed = access.allowed_list.current().entries
    contacts_allowed = [entry.id for entry in allowed if not access.is_group(entry.id)]
    return list(dict.fromkeys([*contacts_allowed, *get_settings().admins]))


async def chat_list(bot: SignalBot) -> list[Chat]:
    """Where a timer can post, in /chats' order: the groups the bot is in by
    name, then people(). In debug mode, the only group is debug_group.
    nejomibot-timers numbers them the same way."""
    settings = get_settings()
    groups = sorted(
        (group.name, group.id)
        for group in bot.groups
        if group.member and (not settings.debug or group.id == settings.debug_group)
    )
    names = await access.names(bot)
    return [(gid, name) for name, gid in groups] + [
        (person, names.get(person, person)) for person in people()
    ]


def chats_text(chats: list[Chat]) -> str:
    """Styled."""
    lines = [
        f"{n} {'👥' if access.is_group(chat_id) else '👤'} {name}"
        for n, (chat_id, name) in enumerate(chats, start=1)
    ]
    hint = _("For /timer add, e.g. /timer add 08:00 1,2 /weather; /photo")
    return "\n".join(
        [
            f"🗨️ **{escape(_('Timers can post to:'))}**",
            escape("\n".join(lines)),
            "",
            escape(hint),
        ]
    )


def card(timer: Timer, names: dict[str, str]) -> str:
    """A timer in short lines: its number and when, its chats, its commands,
    and when it runs next. Styled."""
    chats = ", ".join(names.get(chat, chat) for chat in timer.chats)
    lines = [f"💬 {chats}", f"▶️ {'; '.join(timer.commands)}"]
    if (at := timekeeper.next_run(timer.id)) is not None:
        when = day_and_time(at.astimezone(get_settings().tz))
        lines.append("🔜 " + _("Next: {when}").format(when=when))
    first = f"**#{timer.id}** · {escape(shown(timer.when))}"
    return f"{first}\n{escape(chr(10).join(lines))}"


# The commands


async def list_timers(bot: SignalBot) -> str:
    timekeeper.reread()
    timers = sorted(timekeeper.timers.values(), key=lambda timer: timer.id)
    if not timers:
        return escape(_("No timers yet.") + f"\n\n{usage()}")
    names = await access.names(bot)
    title = ngettext("⏰ {count} timer", "⏰ {count} timers", len(timers)).format(
        count=len(timers)
    )
    return "\n\n".join([f"**{escape(title)}**", *(card(t, names) for t in timers)])


async def add_timer(context: DataMessageContext) -> str:
    """The new timer, or why there's none. Styled."""
    if isinstance(added := await new_timer(context), str):
        return escape(added)
    names = await access.names(context.bot)
    return f"✅ **{escape(_('Added'))}**\n{card(added, names)}"


async def chats_numbered(bot: SignalBot, numbers: list[int]) -> list[Chat] | str:
    """The chats with these numbers in /chats, each once, or why not."""
    listed = await chat_list(bot)
    if wrong := [n for n in numbers if not 1 <= n <= len(listed)]:
        return _("There's no chat {n}: /chats numbers them.").format(n=wrong[0])
    return [listed[n - 1] for n in dict.fromkeys(numbers)]


def check_new(when: str, commands: list[str]) -> Schedule | str:
    """A new timer's schedule, or why the timer can't be."""
    now = datetime.now(get_settings().tz)
    if isinstance(schedule := parse_when(when, now), str):
        return schedule
    if schedule.once and schedule.once <= now:
        return _("{when} has already been.").format(when=shown(schedule.text))
    return check_commands(commands) or schedule


def add_new(
    keeper: Timekeeper, schedule: Schedule, chats: list[str], commands: list[str]
) -> Timer | str:
    """Add the timer, its commands by their English names, as the file keeps
    them; or say why it can't be."""
    if len(keeper.timers) >= MAX_TIMERS:
        return _("There are {count} timers already: remove one first.").format(
            count=MAX_TIMERS
        )
    return keeper.add(schedule.text, chats, [canonical(c) for c in commands])


async def new_timer(context: DataMessageContext) -> Timer | str:
    """Add the timer /timer add describes, or say why it can't be."""
    parsed = parse_add(context.message.text or "")
    if isinstance(parsed, str):
        return parsed
    when, numbers, commands = parsed
    if isinstance(schedule := check_new(when, commands), str):
        return schedule
    if numbers:
        if isinstance(found := await chats_numbered(context.bot, numbers), str):
            return found
        chats = [chat_id for chat_id, _name in found]
    else:
        message = context.message
        chats = [message.source_number or message.source_uuid or ""]
    return add_new(timekeeper, schedule, chats, commands)


async def timer_answer(context: DataMessageContext, words: list[str]) -> str | None:
    """What to reply, if anything. Styled."""
    action = words[1].casefold() if len(words) > 1 else "list"
    if action == "list":
        return await list_timers(context.bot)
    if action == "add":
        return await add_timer(context)
    if action not in ("remove", "delete", "run"):
        return escape(usage())
    number = words[2].lstrip("#") if len(words) > 2 else ""
    if not number.isdigit():
        return escape(_("Which timer? Give its number, as /timers shows."))
    if action == "run":
        timekeeper.reread()
        if (timer := timekeeper.timers.get(int(number))) is None:
            return escape(_("No timer #{n}.").format(n=number))
        await timekeeper.run(timer.id, on_schedule=False)
        sender = context.message.source_number or context.message.source_uuid
        # Posted here, it speaks for itself
        if timer.chats == [sender]:
            return None
        return escape(_("▶️ Ran timer #{n}").format(n=timer.id))
    if (timer := timekeeper.remove(int(number))) is None:
        return escape(_("No timer #{n}.").format(n=number))
    names = await access.names(context.bot)
    return f"🗑️ **{escape(_('Removed'))}**\n{card(timer, names)}"


# They change timers, or say where timers post, so timers don't run them


class Timers(Handler):
    commands = (
        Command("/timers", more=True, timers=False),
        Command("/timer", more=True, timers=False),
    )

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        words = (context.message.text or "").split()
        await answer(
            context,
            lambda: timer_answer(context, words),
            # Only listing them is fine again
            edits=words[1:2] in ([], ["list"]),
            styled=True,
        )


class Chats(Handler):
    commands = (Command("/chats", timers=False),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot = context.bot
        await answer(context, lambda: chats_text_of(bot), styled=True)


async def chats_text_of(bot: SignalBot) -> str:
    return chats_text(await chat_list(bot))
