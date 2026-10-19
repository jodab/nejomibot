"""/remind: reminders, for everyone allowed, which the bot posts once, when
they're due, in the chat they were asked for in:

  /remind 18:00 Take the cake out    at 18:00, today, or tomorrow if it's past
  /remind 30m Call Bob               in 30 minutes; 2h, 1h30m, in 2h too
  /remind tomorrow 08:00 Pick up Bob
  /remind fri 17:00 Pizza!           the coming Friday
  /remind 2026-12-24 15:00 Presents!
  /remind                            the chat's reminders, numbered
  /remind remove 2                   or 2,3

When one is due, in the bot's timezone, the bot posts "⏰ Pick up Bob" in
the chat. A chat has at most 20, at most a year ahead. One due while the bot
was down comes once it's up, with a note that it's late; more than a day
late, it's dropped. A group gets its reminders only while the bot is in it.

They're kept in data_dir/reminders.txt, a line each, which can be changed by
hand: the bot reads it again when it changes, and leaves comments and lines
it can't read as they are. A reminder goes once it's posted.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from signalbot import DataMessageContext, SendMessage, SignalBot

from .access import chat_id_of, is_group
from .commands import Command, Edits, Handler, answer, numbers_in, undo_with
from .config import get_settings
from .files import KeptLines
from .i18n import _, day_and_time, format_duration, ngettext
from .messages import chat_id, chats_of, delayed, escape, send, to_whom
from .timers import (
    CLOCK,
    DURATION,
    Schedule,
    example_date,
    in_language,
    parse_when,
)

logger = logging.getLogger(__name__)

MAX_PER_CHAT = 20
MAX_AHEAD = timedelta(days=366)
MAX_TEXT = 500
# A reminder this late says so; one later than TOO_LATE is dropped
LATE = timedelta(minutes=2)
TOO_LATE = timedelta(days=1)
# How many words a <when> with a time can have: 2026-12-24 15:00, mon,fri 08:00
WHEN_WORDS = 3
# The word before how soon, as in /remind in 30m; the language may add its own
IN = "in"

HEADER = (
    "# nejomibot's reminders, one per line:",
    "#   number | when it's due | chat | text",
    "# The number is the reminder's in its chat, the chat a group ID, phone",
    "# number or Signal ID. Changed with /remind in Signal, or by hand: the bot",
    "# reads it again when it changes, and leaves comments and lines it can't",
    "# read as they are. A reminder goes once it's posted.",
)


@dataclass(frozen=True)
class Reminder:
    number: int  # in its chat
    due: datetime
    chat: str  # a group.… ID, phone number or Signal ID
    text: str


def parse_line(line: str) -> Reminder:
    """A line of the file. Raises ValueError."""
    fields = [field.strip() for field in line.split("|", 3)]
    if len(fields) != 4:
        raise ValueError(f"{len(fields)} fields, not 4")
    number, due, chat, text = fields
    if not number.isdecimal() or not text:
        raise ValueError("no number, or no text")
    if (where := chat_id_of(chat)) is None:
        raise ValueError(f"{chat} isn't a chat")
    when = datetime.fromisoformat(due)
    if when.tzinfo is None:
        when = when.replace(tzinfo=get_settings().tz)
    return Reminder(int(number), when, where, text)


def line_of(reminder: Reminder) -> str:
    due = reminder.due.astimezone(get_settings().tz).isoformat(" ", "seconds")
    return f"{reminder.number} | {due} | {reminder.chat} | {reminder.text}"


kept = KeptLines("reminders.txt", HEADER, parse_line, line_of)


def now() -> datetime:
    """Now, in the bot's time zone."""
    return datetime.now(get_settings().tz)


def usage() -> str:
    zone = get_settings().timezone.rsplit("/", 1)[-1].replace("_", " ")
    date = example_date(now().date())
    return "\n".join(
        [
            _("/remind <when> <text>: a reminder here, e.g."),
            "  " + _("/remind tomorrow 08:00 Pick up Bob"),
            "  "
            + _(
                "<when> is a time (18:00), a day and a time (fri 17:00, tomorrow "
                "08:00, {date} 15:00), or how soon (30m, 2h, 1h30m), in {zone} time"
            ).format(date=date, zone=zone),
            _("/remind: the reminders here"),
            _("/remind remove <n>: remove one"),
        ]
    )


def how_soon(word: str) -> timedelta | None:
    """30m, 2h or 1h30m as a timedelta; None if it isn't one."""
    match = DURATION.match(word)
    if not match or not (match[1] or match[2]):
        return None
    return timedelta(hours=int(match[1] or 0), minutes=int(match[2] or 0))


def next_time(schedule: Schedule, now: datetime) -> datetime:
    """The schedule's first time after now, on one of its days: within a
    week and a day, as it has a day and a time."""
    for ahead in range(8):
        day = now.date() + timedelta(days=ahead)
        if day.weekday() in schedule.days:
            for at in schedule.times:
                if (due := datetime.combine(day, at, now.tzinfo)) > now:
                    return due
    raise AssertionError("a schedule without days or times")


def due_from(words: list[str], now: datetime) -> tuple[datetime, int] | None:
    """When a reminder is due, as its first words say, and how many of them
    say it; None if they don't. now is in the bot's time zone."""
    lowered = [word.casefold() for word in words]
    start = 1 if lowered[:1] and lowered[0] in in_language({IN: True}) else 0
    if len(lowered) > start and (soon := how_soon(lowered[start])):
        # In UTC, so a change to or from summer time is counted too
        return (now.astimezone(UTC) + soon).astimezone(now.tzinfo), start + 1
    if start:
        return None
    for end, word in enumerate(lowered[:WHEN_WORDS]):
        if CLOCK.match(word):
            schedule = parse_when(" ".join(lowered[: end + 1]), now)
            if isinstance(schedule, str) or schedule.every:
                return None
            return schedule.once or next_time(schedule, now), end + 1
    return None


def mine(chats: set[str]) -> list[Reminder]:
    """The chat's reminders, the first due first."""
    found = [each for each in kept.current().entries if each.chat in chats]
    return sorted(found, key=lambda each: each.due)


def reminder_line(reminder: Reminder) -> str:
    when = day_and_time(reminder.due.astimezone(get_settings().tz))
    return f"#{reminder.number} · {when} · {reminder.text}"


def list_reminders(chats: set[str]) -> str:
    """Styled."""
    if not (found := mine(chats)):
        return escape(_("No reminders here.") + f"\n\n{usage()}")
    title = ngettext(
        "🔔 {count} reminder here", "🔔 {count} reminders here", len(found)
    ).format(count=len(found))
    return "\n".join([f"**{escape(title)}**", *map(escape, map(reminder_line, found))])


def add_reminder(chat: str, chats: set[str], words: list[str], now: datetime) -> str:
    """Add the reminder the words describe, or say why not. Styled."""
    if (found := due_from(words, now)) is None:
        return escape(_("When?") + f"\n\n{usage()}")
    due, used = found
    text = " ".join(words[used:])
    if not text:
        return escape(_("What should the reminder say?"))
    if due <= now:
        return escape(_("{when} has already been.").format(when=" ".join(words[:used])))
    if due - now > MAX_AHEAD:
        return escape(_("A reminder can be at most a year ahead."))
    if len(text) > MAX_TEXT:
        return escape(
            _("A reminder has at most {count} characters.").format(count=MAX_TEXT)
        )
    others = mine(chats)
    if len(others) >= MAX_PER_CHAT:
        return escape(
            _("There are {count} reminders here already: remove one first.").format(
                count=MAX_PER_CHAT
            )
        )
    number = max((each.number for each in others), default=0) + 1
    reminder = Reminder(number, due, chat, text)
    change = kept.add(reminder)
    undo_with(lambda: kept.revert(change))
    return f"✅ **{escape(_('Added'))}**\n{escape(reminder_line(reminder))}"


def remove_reminders(chats: set[str], words: list[str]) -> str:
    """Remove the chat's reminders with these numbers, or say why not. Styled."""
    if not (numbers := numbers_in(" ".join(words))):
        return escape(_("Which reminder? Give its number, as /remind shows."))
    found = {each.number: each for each in mine(chats)}
    if wrong := [n for n in numbers if n not in found]:
        return escape(_("No reminder #{n} here.").format(n=wrong[0]))
    gone = [found[n] for n in numbers]
    change = kept.remove(gone)
    undo_with(lambda: kept.revert(change))
    return f"🗑️ **{escape(_('Removed'))}**\n" + "\n".join(
        escape(reminder_line(each)) for each in gone
    )


def remind_answer(context: DataMessageContext, words: list[str]) -> str:
    """What to answer /remind, as words. Styled."""
    chats = chats_of(context)
    action = words[1].casefold() if len(words) > 1 else ""
    if not action:
        return list_reminders(chats)
    if action in ("remove", "delete"):
        return remove_reminders(chats, words[2:])
    return add_reminder(chat_id(context), chats, words[1:], now())


class Remind(Handler):
    commands = (
        Command("/remind", more=True, timers=False, subcommands=("remove", "delete")),
    )

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        words = (context.message.text or "").split()
        await answer(
            context,
            lambda: remind_answer(context, words),
            # Listing them runs again; an edit of one that changes them
            # takes its place
            edits=Edits.RUN_AGAIN if len(words) == 1 else Edits.REPLACE,
            styled=True,
        )


# Posting them


async def post_due(bot: SignalBot) -> None:
    """Post the reminders that are due, and take them out of the file first,
    so none is posted twice. Never raises."""
    moment = now()
    due = [each for each in kept.current().entries if each.due <= moment]
    if not due:
        return
    try:
        kept.remove(due)
    except OSError as e:
        logger.error("Could not take reminders out of their file, so they wait: %r", e)
        return
    member_of = {group.id for group in bot.groups if group.member}
    for reminder in sorted(due, key=lambda each: each.due):
        late = moment - reminder.due
        if late > TOO_LATE:
            logger.warning(
                "Dropped a reminder %s, due %s ago",
                to_whom(reminder.chat),
                format_duration(late),
            )
            continue
        if is_group(reminder.chat) and reminder.chat not in member_of:
            logger.warning("Dropped a reminder to a group the bot isn't in")
            continue
        message = SendMessage(text=_("⏰ {text}").format(text=reminder.text))
        if late > LATE:
            message = delayed(message, reminder.due)
        logger.info("Reminding %s", to_whom(reminder.chat))
        await send(bot, reminder.chat, message)


async def serve(bot: SignalBot) -> None:
    """Once signalbot is ready: post what came due while the bot was down,
    then look for due reminders at the start of every minute."""
    await bot.wait_until_ready()
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        post_due,
        "cron",
        second=0,
        args=[bot],
        id="reminders",
        # However late, rather than skipped when more than a second late
        misfire_grace_time=None,
        coalesce=True,
        max_instances=1,
        replace_existing=True,
    )
    await post_due(bot)


def start(bot: SignalBot) -> None:
    bot.scheduler.add_job(  # pyright: ignore[reportUnknownMemberType]
        serve,
        args=[bot],
        id="reminders-start",
        misfire_grace_time=None,
        replace_existing=True,
    )
