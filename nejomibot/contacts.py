"""/contacts: everyone the bot's Signal account knows, two short lines each,
and /contacts <who> one of them in full, with their safety number.
/contacts add <who> <name> makes someone a contact by that name, or renames
them, and /trust marks a safety number as verified, once it's been compared
with the one on their phone. They show phone numbers, so they only answer
the admins, in direct chats.

People who don't share their phone number on Signal are known only by their
ID (a UUID), so that's all the bot can show for them.
"""

import logging
import re

from signalbot import DataMessageContext, SignalBot, UpdateContact

from . import rest
from .account import (
    UNTRUSTED,
    VERIFIED,
    Account,
    Contact,
    Identity,
    fetch_account,
    full_name,
    with_fresh_profiles,
)
from .commands import Command, Edits, Handler, answer, undo_with
from .config import PHONE_NUMBER, get_settings
from .i18n import _, ngettext
from .messages import escape

logger = logging.getLogger(__name__)

SAFETY_NUMBER_DIGITS = 60


def add_usage() -> str:
    return _("Send: /contacts add <phone number, ID or name> <their name>")


def trust_usage() -> str:
    return _(
        "Compare their safety number here with the one on their phone, then "
        "send: /trust <name, phone number or ID> <safety number>"
    )


def digits(safety_number: str) -> str:
    return re.sub(r"\D", "", safety_number)


def format_safety_number(safety_number: str) -> list[str]:
    """Like the Signal apps: three rows of four groups of five digits."""
    numbers = digits(safety_number)
    groups = [numbers[i : i + 5] for i in range(0, len(numbers), 5)]
    return [f"`{' '.join(groups[i : i + 4])}`" for i in range(0, len(groups), 4)]


def known(account: Account) -> list[Contact]:
    """Everyone signal-cli knows, but the bot."""
    return [c for c in account.recipients if not c.is_one_of({account.id})]


def is_contact(account: Account, contact: Contact) -> bool:
    """In the contacts, not just known."""
    return contact.is_one_of(account.contact_ids)


def strangers(account: Account) -> list[Contact]:
    """Those signal-cli has only a safety number for."""
    theirs = {id(i) for c in known(account) if (i := account.identity_of(c))}
    return [
        Contact(number=i.number or None, uuid=i.uuid)
        for i in account.identities
        if id(i) not in theirs
    ]


def number_of(account: Account, contact: Contact) -> str | None:
    identity = account.identity_of(contact)
    return contact.number or (identity.number if identity else None) or None


def heading_of(account: Account, contact: Contact) -> str:
    """Their name, else their phone number, else their full ID."""
    return (
        contact.real_name or number_of(account, contact) or contact.uuid or _("unknown")
    )


def groups_of(account: Account, contact: Contact) -> list[str]:
    """The groups they're in with the bot, to tell who they are."""
    groups = {
        group.id: group
        for who in (contact.uuid, number_of(account, contact))
        if who
        for group in account.groups_by_member.get(who, [])
    }
    return sorted(group.name or f"{group.id[:14]}…" for group in groups.values())


def trust_mark(identity: Identity | None) -> str:
    """How far their safety number is trusted, in a word or few."""
    if identity is None:
        return _("No safety number yet")
    if identity.status == VERIFIED:
        return _("✅ Verified")
    if identity.status == UNTRUSTED:
        return _("❌ Untrusted: safety number changed")
    return _("⚪ Not verified")


def trust_text(identity: Identity | None) -> str:
    """trust_mark, and since when the safety number is theirs."""
    text = trust_mark(identity)
    if identity and (added := identity.added_at):
        day = f"{added.astimezone(get_settings().tz):%Y-%m-%d}"
        text += _(", key from {day}").format(day=day)
    return text


def short_heading(account: Account, contact: Contact) -> str:
    """heading_of, but an ID only by its start, as /contacts takes it."""
    heading = heading_of(account, contact)
    if heading == contact.uuid and len(heading) > 9:
        return f"{heading[:8]}…"
    return heading


def person_summary(account: Account, contact: Contact) -> str:
    """Two short lines, for the list: who, with their number, then how far
    they're trusted, if they're blocked, and the groups they're in. Styled."""
    number = number_of(account, contact)
    first = f"👤 **{escape(short_heading(account, contact))}**"
    if contact.real_name or not number:
        first += escape(" · " + (number or _("phone number not shared")))
    second = [trust_mark(account.identity_of(contact))]
    if contact.blocked:
        second.append(_("🚫 blocked"))
    if groups := groups_of(account, contact):
        second.append("👥 " + ", ".join(groups))
    return f"{first}\n{escape(' · '.join(second))}"


def person_card(account: Account, contact: Contact) -> str:
    """One person in full, for /contacts <who>: their numbers and ID, About,
    groups, and safety number to compare. Styled."""
    identity = account.identity_of(contact)
    number = number_of(account, contact)
    lines = [f"👤 **{escape(heading_of(account, contact))}**"]
    ids = [number or _("phone number not shared")]
    if contact.username and contact.username != contact.real_name:
        ids.append(f"@{contact.username}")
    lines.append(" · ".join(ids))
    if contact.uuid:
        lines.append(f"🆔 {contact.uuid}")
    if contact.profile and (about := full_name(contact.profile.about)):
        lines.append(f"💬 “{about}”")
    if groups := groups_of(account, contact):
        lines.append("👥 " + _("In {groups}").format(groups=", ".join(groups)))
    if contact.blocked:
        lines.append(_("🚫 blocked"))
    lines.append(trust_text(identity))
    text = escape("\n".join(lines[1:]))
    if identity and identity.safety_number:
        text += "\n" + "\n".join(format_safety_number(identity.safety_number))
        if identity.status != VERIFIED:
            text += "\n" + escape(trust_usage())
    return f"{lines[0]}\n{text}"


def section(icon: str, title: str, people: list[Contact], account: Account) -> str:
    people = sorted(people, key=lambda c: heading_of(account, c).casefold())
    return "\n".join(
        [
            f"{icon} **{escape(title)}** ({len(people)})",
            *(person_summary(account, c) for c in people),
        ]
    )


def contacts_message(account: Account) -> str:
    """Contacts first, then everyone else signal-cli knows, then anyone it
    only has a safety number for: two short lines each. Styled."""
    people = known(account)
    verified = sum(i.status == VERIFIED for i in account.identities)
    untrusted = sum(i.status == UNTRUSTED for i in account.identities)
    count = len(account.identities)
    summary = "🔐 " + ngettext(
        "{count} safety number: {verified} verified, {untrusted} untrusted.",
        "{count} safety numbers: {verified} verified, {untrusted} untrusted.",
        count,
    ).format(count=count, verified=verified, untrusted=untrusted)
    sections = [
        f"👥 **{escape(_('Who the bot knows'))}**\n" + escape(summary),
        section(
            "📇",
            _("Contacts"),
            [c for c in people if is_contact(account, c)],
            account,
        ),
        section(
            "💬",
            _("Other known recipients"),
            [c for c in people if not is_contact(account, c)],
            account,
        ),
    ]
    if only_safety_numbers := strangers(account):
        sections.append(
            section("🔢", _("Only a safety number"), only_safety_numbers, account)
        )
    sections.append(
        escape(
            "🔎 "
            + _(
                "/contacts <who> shows one, with their safety number to compare "
                "with their phone before /trust."
            )
        )
    )
    return "\n\n".join(sections)


async def contacts_answer(bot: SignalBot, who: str) -> str:
    """Everyone, or the one asked for in full. Styled."""
    account = await with_fresh_profiles(await fetch_account(bot))
    if not who:
        return contacts_message(account)
    if isinstance(found := find_one(account, who), str):
        return escape(found)
    return person_card(account, found)


def parse_trust(text: str) -> tuple[str, str] | None:
    """'/trust Alice 12345 67890 ...' -> ('Alice', '1234567890...'). The
    safety number is the words of digits at the end, however they're spaced."""
    words = text.split()[1:]
    number = ""
    while words and words[-1].isdigit() and len(number) < SAFETY_NUMBER_DIGITS:
        number = words.pop() + number
    if len(number) != SAFETY_NUMBER_DIGITS or not words:
        return None
    return " ".join(words), number


def find(account: Account, who: str) -> list[Contact]:
    """By phone number, ID, the start of an ID, or name (any case)."""
    people = known(account) + strangers(account)
    who = who.strip().casefold()

    def by_number_or_id(c: Contact) -> bool:
        return who in {number_of(account, c), (c.uuid or "").casefold()}

    def by_start_of_id(c: Contact) -> bool:
        return len(who) >= 4 and (c.uuid or "").casefold().startswith(who)

    def by_name(c: Contact) -> bool:
        return (c.real_name or "").casefold() == who

    for matches in (by_number_or_id, by_start_of_id, by_name):
        if found := [c for c in people if matches(c)]:
            return found
    return []


def find_one(account: Account, who: str) -> Contact | str:
    """The one person meant, or why there isn't one."""
    found = find(account, who)
    if not found:
        return _("Nobody called {who} in /contacts.").format(who=who)
    if len(found) > 1:
        ids = ", ".join(c.uuid or number_of(account, c) or "?" for c in found)
        return _("{who} could be any of {count}, use their ID: {ids}").format(
            who=who, count=len(found), ids=ids
        )
    return found[0]


async def verify(account: Account, who: str, safety_number: str) -> str:
    if isinstance(contact := find_one(account, who), str):
        return contact
    name = heading_of(account, contact)
    identity = account.identity_of(contact)
    if identity is None or not identity.safety_number:
        return _("No safety number for {name} yet.").format(name=name)
    if digits(identity.safety_number) != safety_number:
        return _(
            "❌ That isn't the safety number for {name}, so it's not verified. "
            "If theirs really is different, they may have reinstalled Signal, "
            "or it may not be them."
        ).format(name=name)
    if identity.status == VERIFIED:
        return _("✅ {name} is already verified.").format(name=name)
    recipient = contact.uuid or number_of(account, contact)
    if not recipient:
        return _("No phone number or ID for {name}.").format(name=name)
    await rest.trust(recipient, safety_number)
    return _("✅ {name} verified.").format(name=name)


async def add(bot: SignalBot, account: Account, who: str, name: str) -> str:
    """Make them a contact by this name, or rename them. Someone not known
    yet is added by their phone number."""
    if isinstance(contact := find_one(account, who), str):
        if not re.match(PHONE_NUMBER, who.strip()):
            return contact
        contact = Contact(number=who.strip())
    recipient = contact.uuid or number_of(account, contact)
    if not recipient:
        return _("No phone number or ID for {name}.").format(
            name=heading_of(account, contact)
        )
    was = heading_of(account, contact)
    await bot.contacts.update(UpdateContact(name=name), recipient)
    if is_contact(account, contact) and (old := contact.name):
        # For an edit: the old name back. A contact made can't be taken out.
        undo_with(lambda: bot.contacts.update(UpdateContact(name=old), recipient))
    if is_contact(account, contact):
        return _("✏️ Renamed {was} to {name} in the contacts.").format(
            was=was, name=name
        )
    return _("📇 Added {was} to the contacts, as {name}.").format(was=was, name=name)


def split_who(account: Account, words: list[str]) -> tuple[str, str]:
    """Who, and their new name: the longest start of the words that names
    someone, so a name with spaces works ('Bob Berg Bobby'), else the first
    word."""
    for end in range(len(words) - 1, 1, -1):
        if find(account, who := " ".join(words[:end])):
            return who, " ".join(words[end:])
    return words[0], " ".join(words[1:])


async def add_contact(bot: SignalBot, words: list[str]) -> str:
    """/contacts add, as words."""
    if len(words) < 2:
        return add_usage()
    account = await fetch_account(bot)
    return await add(bot, account, *split_who(account, words))


class Contacts(Handler):
    commands = (Command("/contacts", more=True, subcommands=("add",)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot, words = context.bot, (context.message.text or "").split()
        if words[1:2] and words[1].casefold() == "add":
            # An edit of it takes its place, a rename undone first
            await answer(
                context, lambda: add_contact(bot, words[2:]), edits=Edits.REPLACE
            )
        else:
            who = " ".join(words[1:])
            await answer(
                context, lambda: contacts_answer(bot, who), slow=True, styled=True
            )


async def trust(bot: SignalBot, text: str) -> str:
    """/trust, as text."""
    if not (parsed := parse_trust(text)):
        return trust_usage()
    return await verify(await fetch_account(bot), *parsed)


class Trust(Handler):
    commands = (Command("/trust", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, lambda: trust(context.bot, context.message.text or ""))
