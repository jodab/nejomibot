"""/allowed, /allow and /disallow: the admins see and change who may use the
everyday commands, the allowed list (see access.py). For the admins only, in
direct chats.

/allow takes a phone number, Signal ID or group ID, the name of a group the
bot is in, or someone in /contacts, by their number there or their name.
/disallow takes the number /allowed shows, an ID, or a name. These can't
change what the admins may do (/admins), and the bot itself can't be
allowed.
"""

import logging
import re

from signalbot import DataMessageContext

from . import access, contacts
from .access import AllowedList, Entry, allowed_list, is_group
from .account import Account, Contact, fetch_account
from .commands import Command, Edits, Handler, answer, argument, undo_with
from .config import get_settings
from .help import shown_name
from .i18n import _, ngettext
from .messages import describe, escape, unreadable_text
from .timers import timekeeper

logger = logging.getLogger(__name__)


def allow_usage() -> str:
    return _(
        "Send /allow and who: a phone number, Signal ID or group ID, the name "
        "of a group the bot is in, or someone in /contacts, by their number "
        "there or name."
    )


def disallow_usage() -> str:
    return _(
        "Send /disallow and who: their number in /allowed, phone number, Signal "
        "ID or group ID, or name."
    )


def admin_text(who: str) -> str:
    return _("{who} is an admin, and may use every command: see /admins.").format(
        who=who
    )


def typed_chat_id(who: str) -> str | None:
    """The chat ID typed in a command, if it's one: a phone number may have
    spaces, dashes or brackets in it, as phones show numbers."""
    if who.startswith("+"):
        who = re.sub(r"[\s().-]", "", who)
    return access.chat_id_of(who)


def name_of(entry: Entry, names: dict[str, str]) -> str:
    """The chat's name as signal-cli knows it, else as the list has it, else
    its ID."""
    return names.get(entry.id) or entry.note or entry.id


def entry_text(entry: Entry, names: access.Names, member_of: set[str]) -> str:
    """E.g. '👥 Family', or '👤 Alice (+46701234567)'."""
    if is_group(entry.id):
        name = name_of(entry, names)
        if entry.id in member_of:
            return f"👥 {name}"
        return f"👥 {name} " + _("(the bot isn't in it)")
    return f"👤 {names.of(entry.id, entry.note)}"


def groups_of(context: DataMessageContext) -> set[str]:
    """The groups the bot is in."""
    return {group.id for group in context.bot.groups if group.member}


async def list_allowed(context: DataMessageContext) -> str:
    """Styled."""
    allowed = allowed_list.reread()
    names = await access.names(context.bot)
    member_of = groups_of(context)
    count = len(allowed.entries)
    title = _("Who may use the everyday commands ({count}):").format(count=count)
    entries = [
        f"{n} {entry_text(entry, names, member_of)}"
        for n, entry in enumerate(allowed.entries, start=1)
    ]
    lines = [""]
    if admins := access.admins():
        lines.append(
            "👑 "
            + _("The admins may use every command: {admins}").format(
                admins=", ".join(names.of(admin) for admin in admins)
            )
        )
    lines.append(_("/allow <who> adds one, /disallow <n> removes one."))
    if allowed.broken:
        lines.append(unreadable_text(allowed.broken))
    return f"📋 **{escape(title)}**\n" + escape("\n".join(entries + lines))


def person_entry(account: Account, person: Contact) -> Entry | None:
    """Someone, as the lists keep them: by phone number, else by Signal ID,
    with their name."""
    chat_id = access.chat_id_of(
        contacts.number_of(account, person) or person.uuid or ""
    )
    return Entry(chat_id, contacts.heading_of(account, person)) if chat_id else None


async def find_new(context: DataMessageContext, who: str) -> Entry | str:
    """Whom /allow means: an ID as it is, or a group the bot is in, by name,
    or someone in /contacts, by their number there, name or the start of
    their ID. Else why not."""
    if chat_id := typed_chat_id(who):
        # A phone number signal-cli can't put a Signal ID to, looked up first,
        # so its name is known, and the list has it
        await access.link([chat_id])
        names = await access.names(context.bot)
        return Entry(chat_id, names.get(chat_id, ""))
    if contacts.list_number(who) is not None:
        account = await fetch_account(context.bot)
        found = contacts.find_one(account, who, contacts.listed_for(context))
        if isinstance(found, str):
            return found
        return person_entry(account, found) or _(
            "No phone number or ID for {name}."
        ).format(name=contacts.heading_of(account, found))
    named = [
        Entry(group.id, group.name)
        for group in context.bot.groups
        if group.member and group.name.casefold() == who.casefold()
    ]
    try:
        account = await fetch_account(context.bot)
    except Exception as e:
        if not named:
            raise
        logger.warning("Could not look up people, only groups: %s", describe(e))
        people: list[Entry] = []
    else:
        people = [
            entry
            for person in contacts.find(account, who)
            if (entry := person_entry(account, person))
        ]
    found = named + people
    if not found:
        text = _("Nobody and no group is called {who}.").format(who=who)
        return f"{text}\n{allow_usage()}"
    if len(found) > 1:
        return _("{who} could be any of {count}, give their ID: {ids}").format(
            who=who, count=len(found), ids=", ".join(entry.id for entry in found)
        )
    return found[0]


async def allow(context: DataMessageContext, who: str) -> str:
    if not who:
        return allow_usage()
    if isinstance(found := await find_new(context, who), str):
        return found
    settings = get_settings()
    name = found.note or found.id
    if found.id == settings.account:
        return _("That's the bot itself.")
    if found.id in access.admins():
        return admin_text(name)
    allowed = allowed_list.reread()
    if found.id in allowed.ids:
        return _("{name} may use the everyday commands already.").format(name=name)
    if len(allowed.entries) >= access.MAX_ENTRIES:
        return _("The list is full: {count} at most.").format(count=access.MAX_ENTRIES)
    allowed_list.add(found)
    undo_with(lambda: allowed_list.remove(found.id))
    logger.info("Allowed a %s", "group" if is_group(found.id) else "contact")
    logger.debug("Allowed %s", found.line)
    if not is_group(found.id):
        return _("✅ {name} may use the everyday commands now.").format(name=name)
    text = _("✅ Everyone in {name} may use the everyday commands there now.")
    text = text.format(name=name)
    if found.id not in groups_of(context):
        text += "\n" + _("The bot isn't in the group: it answers there once added.")
    return text


def find_listed(
    chats: AllowedList, command: str, who: str, names: dict[str, str]
) -> Entry | str:
    """Whom /disallow or /admin remove means, on the list: by its number in
    what command lists, ID or name. Else why not."""
    entries = chats.reread().entries
    listing = shown_name(command)
    if who.isdigit():
        if not 1 <= int(who) <= len(entries):
            return _("There's no {n} in {command}.").format(n=who, command=listing)
        return entries[int(who) - 1]
    chat_id = typed_chat_id(who)
    wanted = who.casefold()
    found = [
        entry
        for entry in entries
        if entry.id == chat_id
        or wanted in (name_of(entry, names).casefold(), entry.note.casefold())
    ]
    if not found:
        return _("{who} isn't in {command}.").format(who=who, command=listing)
    if len(found) > 1:
        return _("{who} could be any of {count} in {command}: give its number.").format(
            who=who, count=len(found), command=listing
        )
    return found[0]


def timers_posting_to(chat_id: str) -> str:
    """A note that timers still post to the chat, if any do."""
    timekeeper.reread()
    numbers = sorted(t.id for t in timekeeper.timers.values() if chat_id in t.chats)
    if not numbers:
        return ""
    return "\n" + ngettext(
        "Timer {timers} still posts there: see /timers.",
        "Timers {timers} still post there: see /timers.",
        len(numbers),
    ).format(timers=", ".join(f"#{n}" for n in numbers))


async def disallow(context: DataMessageContext, who: str) -> str:
    if not who:
        return disallow_usage()
    admins = access.admins()
    names = await access.names(context.bot)
    if isinstance(found := find_listed(allowed_list, "/allowed", who, names), str):
        admin_names = {names.get(admin, admin).casefold() for admin in admins}
        if typed_chat_id(who) in admins or who.casefold() in admin_names:
            return admin_text(who)
        return found
    gone = allowed_list.remove(found.id)
    undo_with(lambda: allowed_list.restore(gone))
    logger.info("Disallowed a %s", "group" if is_group(found.id) else "contact")
    logger.debug("Disallowed %s", found.line)
    name = name_of(found, names)
    if is_group(found.id):
        text = _("🗑️ Nobody in {name} may use the everyday commands there now.")
    else:
        text = _("🗑️ {name} may no longer use the everyday commands.")
    text = text.format(name=name)
    if found.id in admins:  # put on the list by hand
        text += "\n" + _("They're an admin, so may still use them.")
    return text + timers_posting_to(found.id)


# How the admins see and change who may use the bot. Timers may run /allowed,
# which only lists, but not what changes it: run again and again, a number
# would name whoever has it by then. An edit runs /allowed again; an edit of
# /allow or /disallow takes the place of what it edits, which is undone first.


class Allowed(Handler):
    commands = (Command("/allowed"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, lambda: list_allowed(context), styled=True)


class Allow(Handler):
    commands = (Command("/allow", more=True, timers=False),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        who = argument(context.message.text)
        await answer(context, lambda: allow(context, who), edits=Edits.REPLACE)


class Disallow(Handler):
    commands = (Command("/disallow", more=True, timers=False),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        who = argument(context.message.text)
        await answer(context, lambda: disallow(context, who), edits=Edits.REPLACE)
