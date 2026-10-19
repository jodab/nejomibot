"""Birthdays and name days, which the daily post names atop the weather on
the day, in groups only: "🎂 Alice turns 36 today!", "🌸 Happy name day,
Bob!".

The admins keep them, in a direct chat with the bot. Someone on Signal is
given as /contacts takes them, by name, phone number or ID, and must be a
contact saved by name (/contacts add): theirs show in the groups they're in,
by that name, as the contacts have it at the time. Someone not on Signal is
given by name: theirs show in the groups given, by their numbers in /chats,
or else in every group.

  /birthday add 1990-03-14 Alice      a contact; the post says the age
  /birthday add 03-14 Bob             without the year, it doesn't
  /birthday add 1940-05-01 1 Grandma  someone not on Signal, in chat 1
  /nameday add 08-08 Alice
  /birthday remove 2                  by its number in /birthdays
  /nameday remove 1                   by its number in /namedays

A contact has one birthday and one name day: adding another changes it.
/birthdays and /namedays, for everyone allowed, list them, the coming ones
first: in a group, those it gets; in a direct chat, for the admins, all of
them, numbered. /birthday remove and /nameday remove take the numbers of the
list the admin was shown last, whatever changes meanwhile, until they ask
for it again. A birthday on 29 February comes on the 28th in other years.

They're kept in data_dir/birthdays.txt, a line each, which can be changed by
hand: the bot reads it again when it changes, and leaves comments and lines
it can't read as they are.
"""

import logging
import re
from calendar import isleap
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime

from signalbot import DataMessageContext, GroupEntry, SignalBot

from .access import chat_id_of, is_admin, is_group
from .account import Contact, by_ids, fetch_account, fetch_recipients
from .commands import Command, Edits, Handler, answer, numbers_in, undo_with
from .config import GROUP_ID, get_settings
from .contacts import find, find_one, is_contact, number_of
from .files import KeptLines
from .help import shown_name
from .i18n import _, month_name, ngettext
from .messages import chat_of, describe, escape
from .timers import chats_numbered

logger = logging.getLogger(__name__)

BIRTHDAY = "birthday"
NAMEDAY = "nameday"
EVERY_GROUP = "*"  # where someone not on Signal shows, without groups given
MAX_DAYS = 200  # birthdays and name days together
MAX_NAME = 100
DATE = re.compile(r"^(?:(\d{4})-)?(\d{2})-(\d{2})$")
CHAT_NUMBERS = re.compile(r"^[\d,]+$")
CHANGES = ("add", "remove", "delete")  # what follows /birthday and /nameday

HEADER = (
    "# nejomibot's birthdays and name days, one per line:",
    "#   birthday | 1990-03-14 | who | name     the year may be left out: 03-14",
    "#   nameday | 08-08 | who | name",
    "# who is a contact's Signal ID and phone number: it shows in the groups",
    "# they're in, by their name in the contacts. For someone not on Signal,",
    "# who is group IDs, or * for every group. The name is as it was saved.",
    "# Changed with /birthday and /nameday in Signal, or by hand: the bot reads",
    "# it again when it changes, and leaves comments and lines it can't read as",
    "# they are.",
)


@dataclass(frozen=True)
class Occasion:
    """A birthday or a name day."""

    kind: str  # BIRTHDAY or NAMEDAY
    month: int
    day: int
    name: str  # a contact's, as saved when it was added, or as given
    who: tuple[str, ...] = ()  # a contact's Signal ID and phone number, if known
    groups: tuple[str, ...] = ()  # else the groups it shows in; none, every group
    year: int | None = None  # a birthday's, if given

    def on(self, year: int) -> date:
        """Its day in the year: 29 February on the 28th but in leap years."""
        if (self.month, self.day) == (2, 29) and not isleap(year):
            return date(year, 2, 28)
        return date(year, self.month, self.day)

    def next(self, today: date) -> date:
        """Its next day, today or later."""
        day = self.on(today.year)
        return day if day >= today else self.on(today.year + 1)


def parse_date(text: str) -> tuple[int | None, int, int] | None:
    """The year, if given, month and day of 1990-03-14 or 03-14; None if it's
    no such day."""
    if not (match := DATE.match(text)):
        return None
    year = int(match[1]) if match[1] else None
    month, day = int(match[2]), int(match[3])
    try:
        date(year or 2000, month, day)  # 2000 has a 29 February
    except ValueError:
        return None
    return year, month, day


def parse_where(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """A contact's Signal ID and phone number, or else group IDs, which * is
    every group of. Raises ValueError."""
    words = text.split()
    if words == [EVERY_GROUP]:
        return (), ()
    if words and all(re.match(GROUP_ID, word) for word in words):
        return (), tuple(words)
    ids = [found for word in words if (found := chat_id_of(word))]
    if words and len(ids) == len(words) and not any(map(is_group, ids)):
        return tuple(ids), ()
    raise ValueError(f"{text} is no contact, nor groups")


def parse_line(line: str) -> Occasion:
    """A line of the file. Raises ValueError."""
    fields = [field.strip() for field in line.split("|", 3)]
    if len(fields) != 4:
        raise ValueError(f"{len(fields)} fields, not 4")
    kind, when, where, name = fields
    if kind not in (BIRTHDAY, NAMEDAY) or not name:
        raise ValueError("no birthday or name day, or no name")
    if (found := parse_date(when)) is None:
        raise ValueError(f"{when} isn't a date")
    year, month, day = found
    if kind == NAMEDAY and year is not None:
        raise ValueError("a name day has no year")
    who, groups = parse_where(where)
    return Occasion(kind, month, day, name, who, groups, year)


def line_of(occasion: Occasion) -> str:
    when = f"{occasion.month:02}-{occasion.day:02}"
    if occasion.year is not None:
        when = f"{occasion.year:04}-{when}"
    where = " ".join(occasion.who or occasion.groups) or EVERY_GROUP
    return f"{occasion.kind} | {when} | {where} | {occasion.name}"


kept = KeptLines("birthdays.txt", HEADER, parse_line, line_of)

# The birthdays or name days each admin was shown last, by which and by who
# they are: /birthday remove and /nameday remove take the numbers from there.
# Only in memory, so after a restart, the list again.
shown: dict[tuple[str, str], list[Occasion]] = {}


# Whose day shows where


type Contacts = dict[str, Contact]  # by Signal ID and phone number


async def contacts_by_id() -> Contacts:
    """Everyone signal-cli knows, by Signal ID and phone number; no one if
    signal-cli-rest-api can't say, and then the names saved with the
    birthdays and name days stand in for the contacts'."""
    try:
        return by_ids(await fetch_recipients())
    except Exception as e:
        logger.warning("Could not look up the contacts' names: %s", describe(e))
        return {}


def contact_in(occasion: Occasion, contacts: Contacts) -> Contact | None:
    return next((contacts[each] for each in occasion.who if each in contacts), None)


def name_of(occasion: Occasion, contacts: Contacts) -> str:
    """A contact's name as the contacts have it now, else as saved with it."""
    contact = contact_in(occasion, contacts)
    return (contact.saved_name if contact else None) or occasion.name


def shows_in(
    occasion: Occasion, contacts: Contacts, groups: Iterable[GroupEntry]
) -> list[str]:
    """The groups the bot is in that it shows in, by ID: a contact's, those
    they're in; someone else's, those given, or else every group."""
    mine = [group for group in groups if group.member]
    if occasion.who:
        ids = set(occasion.who)
        if contact := contact_in(occasion, contacts):
            ids |= {each for each in (contact.uuid, contact.number) if each}
        return [group.id for group in mine if ids & set(group.members)]
    if occasion.groups:
        return [group.id for group in mine if group.id in occasion.groups]
    return [group.id for group in mine]


def greeting(occasion: Occasion, name: str, day: date) -> str:
    if occasion.kind == NAMEDAY:
        return _("🌸 Happy name day, {name}!").format(name=name)
    if occasion.year is not None and (age := day.year - occasion.year) > 0:
        return _("🎂 {name} turns {age} today!").format(name=name, age=age)
    return _("🎂 Happy birthday, {name}!").format(name=name)


async def greetings(bot: SignalBot, day: date) -> dict[str, list[str]]:
    """The day's birthdays, then its name days, a line each, by the group
    they show in, for the daily post."""
    found = [each for each in kept.current().entries if each.on(day.year) == day]
    if not found:
        return {}
    contacts = await contacts_by_id()
    lines: dict[str, list[str]] = {}
    for each in sorted(found, key=lambda each: each.kind != BIRTHDAY):
        line = greeting(each, name_of(each, contacts), day)
        for group in shows_in(each, contacts, bot.groups):
            lines.setdefault(group, []).append(line)
    return lines


# The lists


def today() -> date:
    return datetime.now(get_settings().tz).date()


def coming(kind: str, on: date) -> list[Occasion]:
    """The kind's, the soonest first, the day's own first of all, then as
    the file has them."""
    found = [each for each in kept.current().entries if each.kind == kind]
    return sorted(found, key=lambda each: each.next(on))


def day_text(day: date) -> str:
    """E.g. '14 March'."""
    return f"{day.day} {month_name(day)}"


def where_text(occasion: Occasion, groups: Iterable[GroupEntry]) -> str:
    """Where someone not on Signal shows: the groups' names, or every group;
    nothing for a contact, who shows where they are."""
    if occasion.who:
        return ""
    if not occasion.groups:
        return "👥 " + _("every group")
    names = {group.id: group.name for group in groups}
    shown = [names.get(each) or f"{each[:14]}…" for each in occasion.groups]
    return "👥 " + ", ".join(shown)


def list_text(
    kind: str,
    found: list[Occasion],
    contacts: Contacts,
    on: date,
    where: Callable[[Occasion], str] | None = None,
) -> str:
    """The birthdays or name days found, as they come, the soonest first;
    for the admins, numbered, with where they show. Styled."""
    count = len(found)
    if kind == BIRTHDAY:
        none = _("No birthdays here.")
        title = ngettext("🎂 {count} birthday", "🎂 {count} birthdays", count)
    else:
        none = _("No name days here.")
        title = ngettext("🌸 {count} name day", "🌸 {count} name days", count)
    if not found:
        return escape(none)
    lines = [f"**{escape(title.format(count=count))}**"]
    for n, each in enumerate(found, start=1):
        day = each.next(on)
        line = f"{day_text(day)} · {name_of(each, contacts)}"
        if where:  # the admins' list, whose numbers remove takes
            line = f"{n} · {line}"
        if each.year is not None and (age := day.year - each.year) > 0:
            line += " " + _("(turns {age})").format(age=age)
        if where and (place := where(each)):
            line += f" · {place}"
        lines.append(escape(line))
    return "\n".join(lines)


async def list_answer(context: DataMessageContext, kind: str) -> str:
    """In a group, those it gets; in a direct chat, for the admins, all of
    them, numbered for them to remove some, with where they show. Styled."""
    bot, message = context.bot, context.message
    if not message.is_group() and not is_admin(message):
        return escape(_("Birthdays and name days show in groups, for those in them."))
    on = today()
    found = coming(kind, on)
    contacts = await contacts_by_id() if found else {}
    if message.is_group():
        group = chat_of(bot, message.source_or_group_id())
        here = [each for each in found if group in shows_in(each, contacts, bot.groups)]
        return list_text(kind, here, contacts, on)
    shown[kind, admin_of(context)] = found
    return list_text(
        kind, found, contacts, on, lambda each: where_text(each, bot.groups)
    )


def admin_of(context: DataMessageContext) -> str:
    """Who sent the command, as the lists they were shown are kept."""
    return context.message.source_uuid or context.message.source_number or ""


# Adding and removing them


def usage(kind: str) -> str:
    if kind == BIRTHDAY:
        return "\n".join(
            [
                _("/birthday add <date> [<chats>] <who>: a birthday, e.g."),
                "  " + _("/birthday add 1990-03-14 Alice: a contact, where they are"),
                "  "
                + _(
                    "/birthday add 03-14 1,2 Grandma: someone not on Signal, in "
                    "chats 1 and 2 of /chats; without them, in every group"
                ),
                _("/birthday remove <n>: remove one, by its number in /birthdays"),
            ]
        )
    return "\n".join(
        [
            _("/nameday add <date> [<chats>] <who>: a name day, as /birthday takes it"),
            _("/nameday remove <n>: remove one, by its number in /namedays"),
        ]
    )


async def contact_of(
    bot: SignalBot, kind: str, who: str
) -> tuple[str, tuple[str, ...], list[Occasion]] | str:
    """For /birthday add without chats: the contact's name as saved, their
    Signal ID and phone number, those known, and the birthday or name day
    they have now, which the new one changes; or, if nobody is called who,
    someone not on Signal, by that name and without IDs; or why it can't
    be."""
    account = await fetch_account(bot)
    if not find(account, who):
        if chat_id_of(who):  # a phone number or ID nobody has
            return _("Nobody called {who} in /contacts.").format(who=who)
        return who, (), []
    if isinstance(contact := find_one(account, who), str):
        return contact  # it could be any of several
    ids = tuple(each for each in (contact.uuid, number_of(account, contact)) if each)
    name = contact.saved_name if is_contact(account, contact) else None
    if not name or not ids:
        return _(
            "Save {who} as a contact first, by the name to show: /contacts add "
            "{who} <name>"
        ).format(who=who)
    old = [each for each in kept.current().entries if each.kind == kind]
    return name, ids, [each for each in old if set(each.who) & set(ids)]


async def add(bot: SignalBot, kind: str, words: list[str], on: date) -> str:
    """Add the birthday or name day, or change a contact's; or say why
    not."""
    if len(words) < 2:
        return usage(kind)
    if (found := parse_date(words[0])) is None:
        return _("{text} isn't a day: give it as 1990-03-14, or 03-14.").format(
            text=words[0]
        )
    year, month, day = found
    if kind == NAMEDAY and year is not None:
        return _("A name day has no year: give it as 08-08.")
    if year is not None and date(year, month, day) > on:
        return _("{day} is still to come.").format(day=words[0])
    rest = words[1:]
    chats: list[str] = []
    while rest and CHAT_NUMBERS.match(rest[0]):
        chats.append(rest.pop(0))
    if not (who := " ".join(rest)):
        return usage(kind)
    if len(who) > MAX_NAME:
        return _("A name has at most {count} characters.").format(count=MAX_NAME)
    groups: tuple[str, ...] = ()
    if chats:
        if not (numbers := numbers_in(" ".join(chats))):
            return usage(kind)
        if isinstance(listed := await chats_numbered(bot, numbers), str):
            return listed
        if people := [name for chat, name in listed if not is_group(chat)]:
            return _("{name} is no group: they show in groups only.").format(
                name=people[0]
            )
        groups = tuple(chat for chat, _name in listed)
        name, their_ids, old = who, (), list[Occasion]()
    elif isinstance(found_contact := await contact_of(bot, kind, who), str):
        return found_contact
    else:
        name, their_ids, old = found_contact
    new = Occasion(kind, month, day, name, their_ids, groups, year)
    entries = kept.current().entries
    if new in entries:
        return _("{name} is there already, on that day.").format(name=name)
    if not old and len(entries) >= MAX_DAYS:
        return _(
            "There are {count} birthdays and name days already: remove one first."
        ).format(count=MAX_DAYS)
    change = kept.change(old, [new])
    undo_with(lambda: kept.revert(change))
    done = _("✅ Changed: {day} · {name}") if old else _("✅ Added: {day} · {name}")
    lines = [done.format(day=day_text(new.next(on)), name=name)]
    if their_ids:
        lines.append(_("👥 In the groups {name} is in").format(name=name))
    elif groups:
        lines.append(where_text(new, bot.groups))
    else:
        lines.append(
            _("👥 In every group: no contact is called {name}").format(name=name)
        )
    return "\n".join(lines)


def remove(kind: str, who: str, words: list[str], on: date) -> str:
    """Remove the birthdays or name days of those numbers in the list who was
    shown last, as the file has them now; or say why not."""
    listing = shown_name("/birthdays" if kind == BIRTHDAY else "/namedays")
    if not (numbers := numbers_in(" ".join(words))):
        return _("Which? Give its number, as {command} shows.").format(command=listing)
    if (listed := shown.get((kind, who))) is None:
        return _("Which ones? Send {command} first, for their numbers.").format(
            command=listing
        )
    if wrong := [n for n in numbers if not 1 <= n <= len(listed)]:
        return _("There's no {n} in {command}.").format(n=wrong[0], command=listing)
    entries = kept.current().entries
    gone: list[Occasion] = []
    lines: list[str] = []
    for n in numbers:
        # Alike, not the same: the file may have been read again since
        still = next(
            (
                each
                for each in entries
                if each == listed[n - 1] and all(each is not g for g in gone)
            ),
            None,
        )
        if still is None:
            note = _("{n} is gone already: removed or changed since.")
            lines.append(note.format(n=n))
        else:
            gone.append(still)
    if gone:
        change = kept.remove(gone)
        undo_with(lambda: kept.revert(change))
        removed = ", ".join(f"{day_text(e.next(on))} · {e.name}" for e in gone)
        lines.insert(0, _("🗑️ Removed: {what}").format(what=removed))
    return "\n".join(lines)


async def birthday_answer(
    context: DataMessageContext, kind: str, words: list[str]
) -> str:
    """What to answer /birthday or /nameday, as words."""
    action = words[1].casefold() if len(words) > 1 else ""
    if action == "add":
        return await add(context.bot, kind, words[2:], today())
    if action in ("remove", "delete"):
        return remove(kind, admin_of(context), words[2:], today())
    return usage(kind)


class Birthdays(Handler):
    """The lists, for everyone allowed. Not for timers, as what they show
    depends on the chat."""

    commands = (Command("/birthdays", timers=False), Command("/namedays", timers=False))

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        kind = BIRTHDAY if command.name == "/birthdays" else NAMEDAY
        await answer(context, lambda: list_answer(context, kind), styled=True)


class Birthday(Handler):
    """Adding and removing them, for the admins: an edit takes the place of
    what it edits; timers don't run them."""

    commands = (
        Command("/birthday", more=True, timers=False, subcommands=CHANGES),
        Command("/nameday", more=True, timers=False, subcommands=CHANGES),
    )

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        kind = BIRTHDAY if command.name == "/birthday" else NAMEDAY
        words = (context.message.text or "").split()
        action = words[1].casefold() if len(words) > 1 else ""
        await answer(
            context,
            lambda: birthday_answer(context, kind, words),
            # An edit of one that changes something takes its place
            edits=Edits.REPLACE if action in CHANGES else Edits.RUN_AGAIN,
        )
