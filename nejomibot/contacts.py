"""/contacts: everyone the bot's Signal account knows, numbered, two short
lines each, and /contacts <who> one of them in full, with their safety
number. /trust lists everyone's safety numbers, in the same order and by the
same numbers, /trust <who> shows one, and /trust <who> <safety number> marks
it as verified, once it's been compared with the one on their phone.
/contacts add <who> <name> makes someone a contact by that name, or renames
them. They show phone numbers, so they only answer the admins, in direct
chats.

Who is someone's number in the list the admin was shown last, by /contacts
or /trust, whatever changes meanwhile, until they ask for it again; or
their phone number, ID, the start of it, or their name. /allow and /admin
add take the numbers too.

People who don't share their phone number on Signal are known only by their
ID (a UUID), so that's all the bot can show for them, besides their name.
The name they gave themselves in Signal, their profile name, shows beside
the one in the contacts where they differ. Their Signal username shows too,
if signal-cli knows it: Signal doesn't share usernames, so it knows only
those of people it found by them, as /contacts add u:alice.42 Alice does
for someone the bot doesn't know yet.
"""

import logging
import re
from collections.abc import Callable

from signalbot import DataMessageContext, SignalBot, UpdateContact

from . import rest
from .account import (
    UNTRUSTED,
    VERIFIED,
    Account,
    Contact,
    Identity,
    Profile,
    fetch_account,
    find_by_ids,
    full_name,
    with_fresh_profiles,
)
from .commands import Command, Edits, Handler, answer, undo_with
from .config import PHONE_NUMBER, get_settings
from .help import shown_name
from .i18n import _, ngettext
from .incoming import sender_of
from .messages import collected, escape

logger = logging.getLogger(__name__)

SAFETY_NUMBER_DIGITS = 60
LIST_NUMBER_DIGITS = 4  # at most, as a list numbers people

type Listed = list[tuple[str | None, str | None]]  # phone numbers and Signal IDs

# The people each admin was shown last, by /contacts or /trust, in order, by
# who the admin is: a number in place of who is one of them. Only in memory,
# so after a restart, the list again.
shown: dict[str, Listed] = {}


def add_usage() -> str:
    return _(
        "Send: /contacts add <number in /contacts, phone number, u:username, "
        "ID or name> <their name>"
    )


# A Signal username, as signal-cli takes it after u:, or as the bot shows it
# after @: 3 to 32 letters, digits or _, not first a digit, a dot, digits
USERNAME = re.compile(r"^(?:u:|@)([A-Za-z_][A-Za-z0-9_]{2,31}\.\d{2,9})$")


def username_in(who: str) -> str | None:
    """The Signal username who is, given as u:alice.42 or @alice.42."""
    found = USERNAME.match(who.strip())
    return found[1] if found else None


def trust_usage() -> str:
    return _(
        "To verify a safety number, compare it with the one on their phone, "
        "then send: {command} <who> <safety number>, all 60 digits"
    ).format(command=shown_name("/trust"))


def verify_hint(who: str) -> str:
    """How to verify a safety number, of who as the admin named them."""
    return _(
        "To verify it, compare it with the one on their phone, then send: "
        "{command} {who} <safety number>"
    ).format(command=shown_name("/trust"), who=who)


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


def username_of(contact: Contact) -> str | None:
    """Their Signal username, if signal-cli knows it, as it does for those it
    found by it, unless it's their name already."""
    if contact.username and contact.username != contact.real_name:
        return contact.username
    return None


def profile_name_of(contact: Contact) -> str | None:
    """The name they gave themselves in Signal, unless it's the name they
    show by already, as when they're not named in the contacts."""
    profile = contact.profile or Profile()
    own = full_name(profile.given_name, profile.lastname)
    return own if own and own != contact.real_name else None


def heading_line(account: Account, contact: Contact) -> str:
    """Who, with their phone number, profile name and username, as the lists
    show them. Styled."""
    number = number_of(account, contact)
    line = f"👤 **{escape(short_heading(account, contact))}**"
    ids: list[str] = []
    if contact.real_name or not number:
        ids.append(number or _("phone number not shared"))
    if own := profile_name_of(contact):
        ids.append(f"🪪 {own}")
    if username := username_of(contact):
        ids.append(f"@{username}")
    return line + escape("".join(f" · {each}" for each in ids))


def person_summary(account: Account, contact: Contact) -> str:
    """Two short lines, for /contacts: who, with their number, then how far
    they're trusted, if they're blocked, and the groups they're in. Styled."""
    second = [trust_mark(account.identity_of(contact))]
    if contact.blocked:
        second.append(_("🚫 blocked"))
    if groups := groups_of(account, contact):
        second.append("👥 " + ", ".join(groups))
    return f"{heading_line(account, contact)}\n{escape(' · '.join(second))}"


def safety_entry(account: Account, contact: Contact) -> str:
    """Who, how far their safety number is trusted, and the number, as the
    apps show it, for /trust. Styled."""
    identity = account.identity_of(contact)
    lines = [heading_line(account, contact), escape(trust_text(identity))]
    if identity and identity.safety_number:
        lines.extend(format_safety_number(identity.safety_number))
    return "\n".join(lines)


def unverified(account: Account, contact: Contact) -> bool:
    """Whether they have a safety number that isn't verified yet."""
    identity = account.identity_of(contact)
    return bool(identity and identity.safety_number and identity.status != VERIFIED)


def safety_card(account: Account, contact: Contact, who: str) -> str:
    """One person's safety number, for /trust <who>, and how to verify it.
    Styled."""
    text = safety_entry(account, contact)
    if unverified(account, contact):
        text += "\n" + escape(verify_hint(who))
    return text


def person_card(account: Account, contact: Contact, who: str | None = None) -> str:
    """One person in full, for /contacts <who>: their numbers and ID, About,
    groups, and safety number to compare. Styled."""
    identity = account.identity_of(contact)
    number = number_of(account, contact)
    lines = [f"👤 **{escape(heading_of(account, contact))}**"]
    if own := profile_name_of(contact):
        lines.append("🪪 " + _("Profile name: {name}").format(name=own))
    if contact.username:
        username = f"@{contact.username}"
        lines.append("🔗 " + _("Username: {username}").format(username=username))
    lines.append(
        "📞 "
        + (
            _("Number: {number}").format(number=number)
            if number
            else _("phone number not shared")
        )
    )
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
    if unverified(account, contact):
        text += "\n" + escape(verify_hint(who or heading_of(account, contact)))
    return f"{lines[0]}\n{text}"


# The lists, numbered alike


def sections(account: Account) -> list[tuple[str, str, list[Contact]]]:
    """Everyone, as /contacts and /trust list them: the contacts, everyone
    else signal-cli knows, then anyone it only has a safety number for, if
    any; each by name, or by phone number or ID without one."""
    people = known(account)
    found = [
        ("📇", _("Contacts"), [c for c in people if is_contact(account, c)]),
        (
            "💬",
            _("Other known recipients"),
            [c for c in people if not is_contact(account, c)],
        ),
    ]
    if only_safety_numbers := strangers(account):
        found.append(("🔢", _("Only a safety number"), only_safety_numbers))
    return [
        (icon, title, sorted(group, key=lambda c: heading_of(account, c).casefold()))
        for icon, title, group in found
    ]


def everyone(account: Account) -> Listed:
    """Everyone's phone number and Signal ID, in the order of the lists."""
    return [(c.number, c.uuid) for *_head, group in sections(account) for c in group]


def numbered(account: Account, entry: Callable[[Account, Contact], str]) -> list[str]:
    """The sections, each person as entry() has them, numbered from 1 across
    the sections. Styled."""
    texts: list[str] = []
    n = 0
    for icon, title, people in sections(account):
        lines = [f"{icon} **{escape(title)}** ({len(people)})"]
        for contact in people:
            n += 1
            lines.append(f"{n} {entry(account, contact)}")
        texts.append("\n".join(lines))
    return texts


def remember(admin: str, account: Account) -> None:
    """Keep the order the admin is shown everyone in, for their numbers; not
    for a timer, /run or a special, which show it to others."""
    if collected.get() is None:
        shown[admin] = everyone(account)


def safety_count(account: Account) -> str:
    """E.g. '3 safety numbers: 1 verified, 1 untrusted.'"""
    verified = sum(i.status == VERIFIED for i in account.identities)
    untrusted = sum(i.status == UNTRUSTED for i in account.identities)
    count = len(account.identities)
    return ngettext(
        "{count} safety number: {verified} verified, {untrusted} untrusted.",
        "{count} safety numbers: {verified} verified, {untrusted} untrusted.",
        count,
    ).format(count=count, verified=verified, untrusted=untrusted)


def contacts_message(account: Account) -> str:
    """Contacts first, then everyone else signal-cli knows, then anyone it
    only has a safety number for: numbered, two short lines each. Styled."""
    hint = _(
        "/contacts <n> shows one in full; /trust lists the safety numbers, to "
        "compare with their phones."
    )
    return "\n\n".join(
        [
            f"👥 **{escape(_('Who the bot knows'))}**\n"
            + escape("🔐 " + safety_count(account)),
            *numbered(account, person_summary),
            escape("🔎 " + hint),
        ]
    )


def safety_numbers_message(account: Account) -> str:
    """Everyone's safety number, numbered as /contacts numbers them. Styled."""
    hint = _(
        "To verify one, compare it with the one on their phone, then send: "
        "{command} <n> <safety number>"
    ).format(command=shown_name("/trust"))
    return "\n\n".join(
        [
            f"🔐 **{escape(_('Safety numbers'))}**\n" + escape(safety_count(account)),
            *numbered(account, safety_entry),
            escape("🔎 " + hint),
        ]
    )


async def contacts_answer(bot: SignalBot, who: str, admin: str = "") -> str:
    """Everyone, numbered for the admin, or the one asked for in full.
    Styled."""
    account = await with_fresh_profiles(await fetch_account(bot))
    if not who:
        remember(admin, account)
        return contacts_message(account)
    if isinstance(found := find_one(account, who, shown.get(admin)), str):
        return escape(found)
    return person_card(account, found, who)


# Who's meant


def list_number(who: str) -> int | None:
    """who as a number in the lists, if it's one."""
    who = who.strip()
    return int(who) if who.isdecimal() and len(who) <= LIST_NUMBER_DIGITS else None


def current(account: Account, number: str | None, uuid: str | None) -> Contact:
    """Someone listed, as the account knows them now, if it still does."""
    found = find_by_ids(account.recipient_by_id, number, uuid)
    return found or Contact(number=number, uuid=uuid)


def find(account: Account, who: str) -> list[Contact]:
    """By phone number, ID, the start of an ID, or name (any case)."""
    people = known(account) + strangers(account)
    who = who.strip().casefold()

    def by_number_or_id(c: Contact) -> bool:
        ids = {number_of(account, c), (c.uuid or "").casefold()}
        if c.username:  # as u:alice.42, or @alice.42
            ids |= {f"u:{c.username.casefold()}", f"@{c.username.casefold()}"}
        return who in ids

    def by_start_of_id(c: Contact) -> bool:
        return len(who) >= 4 and (c.uuid or "").casefold().startswith(who)

    def by_name(c: Contact) -> bool:
        return (c.real_name or "").casefold() == who

    for matches in (by_number_or_id, by_start_of_id, by_name):
        if found := [c for c in people if matches(c)]:
            return found
    return []


def find_one(account: Account, who: str, listed: Listed | None = None) -> Contact | str:
    """The one person meant, or why there isn't one: by their number in the
    list the admin was shown last, else as find() finds them."""
    if (n := list_number(who)) is not None:
        command = shown_name("/contacts")
        if listed is None:
            return _("Which one? Send {command} first, for their numbers.").format(
                command=command
            )
        if not 1 <= n <= len(listed):
            return _("There's no {n} in {command}.").format(n=n, command=command)
        return current(account, *listed[n - 1])
    found = find(account, who)
    if not found:
        return _("Nobody called {who} in /contacts.").format(who=who)
    if len(found) > 1:
        ids = ", ".join(c.uuid or number_of(account, c) or "?" for c in found)
        return _("{who} could be any of {count}, use their ID: {ids}").format(
            who=who, count=len(found), ids=ids
        )
    return found[0]


# Safety numbers


def parse_trust(text: str) -> tuple[str, str]:
    """'/trust Alice 12345 67890 ...' -> ('Alice', '1234567890...'): who, and
    the digits at the end, however they're spaced, up to a safety number's.
    A word alone is who, as a number in the lists may be."""
    words = text.split()[1:]
    number = ""
    while len(words) > 1 and words[-1].isdigit() and len(number) < SAFETY_NUMBER_DIGITS:
        number = words.pop() + number
    return " ".join(words), number


async def verify(
    account: Account, who: str, safety_number: str, listed: Listed | None = None
) -> str:
    if isinstance(contact := find_one(account, who, listed), str):
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


async def trust(bot: SignalBot, text: str, admin: str = "") -> str:
    """/trust, as text: everyone's safety numbers, numbered for the admin,
    one's, or one marked as verified. Styled."""
    who, number = parse_trust(text)
    if len(number) != SAFETY_NUMBER_DIGITS and (
        number or (who.isdecimal() and list_number(who) is None)
    ):
        return escape(trust_usage())  # some of a safety number, or no who
    account = await fetch_account(bot)
    if not who:
        remember(admin, account)
        return safety_numbers_message(account)
    listed = shown.get(admin)
    if number:
        return escape(await verify(account, who, number, listed))
    if isinstance(found := find_one(account, who, listed), str):
        return escape(found)
    return safety_card(account, found, who)


# Adding contacts


async def add(
    bot: SignalBot,
    account: Account,
    who: str,
    name: str,
    listed: Listed | None = None,
) -> str:
    """Make them a contact by this name, or rename them. Someone not known
    yet is added by their phone number, or their Signal username."""
    if isinstance(contact := find_one(account, who, listed), str):
        if username := username_in(who):
            await rest.name_contact(f"u:{username}", name)
            return _("📇 Added {was} to the contacts, as {name}.").format(
                was=f"@{username}", name=name
            )
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


async def add_contact(
    bot: SignalBot, words: list[str], listed: Listed | None = None
) -> str:
    """/contacts add, as words."""
    if len(words) < 2:
        return add_usage()
    account = await fetch_account(bot)
    return await add(bot, account, *split_who(account, words), listed)


def listed_for(context: DataMessageContext) -> Listed | None:
    """Everyone, as the admin who sent the command was shown them last."""
    return shown.get(sender_of(context.message))


class Contacts(Handler):
    commands = (Command("/contacts", more=True, subcommands=("add",)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot, words = context.bot, (context.message.text or "").split()
        if words[1:2] and words[1].casefold() == "add":
            # An edit of it takes its place, a rename undone first
            await answer(
                context,
                lambda: add_contact(bot, words[2:], listed_for(context)),
                edits=Edits.REPLACE,
            )
        else:
            who, admin = " ".join(words[1:]), sender_of(context.message)
            await answer(
                context,
                lambda: contacts_answer(bot, who, admin),
                slow=True,
                styled=True,
            )


class Trust(Handler):
    commands = (Command("/trust", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot, text = context.bot, context.message.text or ""
        admin = sender_of(context.message)
        await answer(context, lambda: trust(bot, text, admin), styled=True)
