"""The bot's Signal account: its profile, contacts, safety numbers, groups and
linked devices. /status shows it and checks it for problems; /contacts lists
who it knows.

The groups come from signalbot. It can't list the rest, so that comes
straight from signal-cli-rest-api (rest.py).
"""

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from functools import cached_property

from pydantic import BaseModel, TypeAdapter
from signalbot import GroupEntry, SignalBot

from . import rest
from .config import get_settings
from .i18n import _, ngettext
from .messages import describe

logger = logging.getLogger(__name__)

# For all the account's requests together
FETCH_TIMEOUT = 30  # seconds
# Profiles asked for again at once, and at most per command: each one makes
# signal-cli ask Signal's servers, which rate-limit a burst
PROFILES_AT_ONCE = 4
MAX_PROFILES = 50
# A profile asked for again isn't again this soon, as signal-cli keeps one
# that long itself
REFETCH_AFTER = 6 * 60 * 60  # seconds
RECENT = timedelta(days=7)  # safety numbers new or changed this recently are named

UNTRUSTED = "UNTRUSTED"
VERIFIED = "TRUSTED_VERIFIED"


class Profile(BaseModel):
    given_name: str | None = None
    lastname: str | None = None
    about: str | None = None
    has_avatar: bool = False


class Nickname(BaseModel):
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None


def full_name(*parts: str | None) -> str | None:
    return " ".join(p.strip() for p in parts if p and p.strip()) or None


class Contact(BaseModel):
    number: str | None = None
    uuid: str | None = None
    name: str | None = None
    given_name: str | None = None
    username: str | None = None
    nickname: Nickname | None = None
    # The name they gave themselves; known once signal-cli has their profile
    profile: Profile | None = None
    blocked: bool = False

    @property
    def saved_name(self) -> str | None:
        """The nickname given them or their name in the contacts, as /contacts
        add saves it, if any: not one they gave themselves."""
        nickname = self.nickname or Nickname()
        return (
            full_name(nickname.name)
            or full_name(nickname.given_name, nickname.family_name)
            or full_name(self.name)
            or full_name(self.given_name)
        )

    @property
    def real_name(self) -> str | None:
        """The name saved for them, the name they gave themselves or their
        username, if any."""
        profile = self.profile or Profile()
        return (
            self.saved_name
            or full_name(profile.given_name, profile.lastname)
            or full_name(self.username)
        )

    @property
    def display_name(self) -> str:
        return self.real_name or self.number or f"{(self.uuid or '?')[:8]}…"

    def is_one_of(self, ids: set[str]) -> bool:
        return any(who in ids for who in (self.number, self.uuid) if who)


class Identity(BaseModel):
    number: str | None = None
    uuid: str | None = None
    status: str = ""
    added: str | None = None  # milliseconds since the epoch
    safety_number: str | None = None

    @property
    def added_at(self) -> datetime | None:
        try:
            ms = int(self.added or "")
        except ValueError:
            return None
        return datetime.fromtimestamp(ms / 1000, UTC) if ms > 0 else None


class Device(BaseModel):
    id: int
    name: str | None = None
    last_seen_timestamp: int | None = None

    @property
    def last_seen(self) -> datetime | None:
        ms = self.last_seen_timestamp
        return datetime.fromtimestamp(ms / 1000, UTC) if ms else None


def by_ids[T: (Contact, Identity)](people: list[T]) -> dict[str, T]:
    """The people by Signal ID and by phone number, the first for each."""
    found: dict[str, T] = {}
    for person in people:
        for key in (person.uuid, person.number):
            if key:
                found.setdefault(key, person)
    return found


def find_by_ids[T: (Contact, Identity)](
    index: dict[str, T], number: str | None, uuid: str | None
) -> T | None:
    """By Signal ID, else by phone number."""
    for key in (uuid, number):
        if key and (found := index.get(key)) is not None:
            return found
    return None


@dataclass(frozen=True)
class Account:
    """What signal-cli knows, as read at one time: looked up by ID, through
    indexes made at the first lookup, so the lists mustn't change after."""

    id: str  # the account: its phone number, as signal-cli knows it
    contacts: list[Contact]
    recipients: list[Contact]  # everyone signal-cli knows, contacts or not
    identities: list[Identity]
    groups: list[GroupEntry]

    @cached_property
    def me(self) -> Contact | None:
        return next((c for c in self.recipients if c.is_one_of({self.id})), None)

    @cached_property
    def contact_ids(self) -> set[str]:
        return set(by_ids(self.contacts))

    @cached_property
    def recipient_by_id(self) -> dict[str, Contact]:
        return by_ids(self.recipients)

    @cached_property
    def identity_by_id(self) -> dict[str, Identity]:
        return by_ids(self.identities)

    @cached_property
    def groups_by_member(self) -> dict[str, list[GroupEntry]]:
        """The groups the bot is in, by the IDs and numbers of their members."""
        found: dict[str, list[GroupEntry]] = {}
        for group in self.groups:
            if group.member:
                for member in dict.fromkeys(group.members):
                    found.setdefault(member, []).append(group)
        return found

    def identity_of(self, contact: Contact) -> Identity | None:
        return find_by_ids(self.identity_by_id, contact.number, contact.uuid)

    def name_of(self, number: str | None, uuid: str | None = None) -> str:
        if contact := find_by_ids(self.recipient_by_id, number, uuid):
            return contact.display_name
        return number or f"{(uuid or '?')[:8]}…"

    def is_me(self, member: str) -> bool:
        me = self.me
        return member == self.id or bool(me and me.uuid and member == me.uuid)

    def untrusted(self) -> list[str]:
        """Names of those whose safety number changed and isn't trusted yet:
        signal-cli won't send to them."""
        return sorted(
            self.name_of(i.number, i.uuid)
            for i in self.identities
            if i.status == UNTRUSTED
        )

    def blocked_recipients(self, recipients: list[str]) -> list[str]:
        """Which of these numbers, IDs and group IDs are blocked, by name."""
        groups = {g.id: g for g in self.groups}
        blocked: list[str] = []
        for recipient in recipients:
            if (group := groups.get(recipient)) is not None:
                if group.blocked:
                    blocked.append(group.name or f"{recipient[:14]}…")
            elif (person := self.recipient_by_id.get(recipient)) and person.blocked:
                blocked.append(person.display_name)
        return sorted(blocked)


CONTACTS = TypeAdapter(list[Contact])
IDENTITIES = TypeAdapter(list[Identity])
DEVICES = TypeAdapter(list[Device])


async def fetch_recipients() -> list[Contact]:
    """Everyone signal-cli knows, with their names: one request."""
    return CONTACTS.validate_python(await rest.recipients(everyone=True))


async def fetch_groups(bot: SignalBot) -> list[GroupEntry]:
    """Every group signal-cli knows, the bot's or not, freshly read."""
    await bot.groups.refresh()
    return list(bot.groups)


async def fetch_account(bot: SignalBot) -> Account:
    async with asyncio.timeout(FETCH_TIMEOUT):
        contacts, recipients, identities, groups = await asyncio.gather(
            rest.recipients(everyone=False),
            rest.recipients(everyone=True),
            rest.identities(),
            fetch_groups(bot),
        )
    account = Account(
        id=get_settings().account,
        contacts=CONTACTS.validate_python(contacts),
        recipients=CONTACTS.validate_python(recipients),
        identities=IDENTITIES.validate_python(identities),
        groups=groups,
    )
    # The bot's own safety number is nobody's to compare: not listed, nor
    # counted
    theirs = [
        identity
        for identity in account.identities
        if not any(
            account.is_me(who) for who in (identity.number, identity.uuid) if who
        )
    ]
    return replace(account, identities=theirs)


async def fetch_devices() -> list[Device]:
    """The account's linked devices, as Signal's servers list them."""
    return DEVICES.validate_python(await rest.devices())


# When each profile was asked for again last, by Signal ID, by time.monotonic
refetched: dict[str, float] = {}


async def with_fresh_profiles(account: Account) -> Account:
    """Ask again for the nameless by ID, which makes signal-cli fetch their
    profile now instead of after its six-hour cache, e.g. for someone who just
    joined a group; but not one asked for in the last six hours. Whoever
    can't be fetched stays as they were."""
    now = time.monotonic()
    for uuid in [u for u, at in refetched.items() if now - at >= REFETCH_AFTER]:
        del refetched[uuid]
    nameless = [
        c
        for c in account.recipients
        if c.uuid and not c.real_name and c.uuid not in refetched
    ][:MAX_PROFILES]
    refetched.update((c.uuid or "", now) for c in nameless)
    turns = asyncio.Semaphore(PROFILES_AT_ONCE)
    failed: list[Exception] = []

    async def refetch(contact: Contact) -> Contact:
        try:
            async with turns:
                return Contact.model_validate(await rest.recipient(contact.uuid or ""))
        except Exception as e:
            failed.append(e)
            return contact

    fresh = await asyncio.gather(*map(refetch, nameless))
    if failed:
        logger.warning(
            "Could not refresh %d profiles: %s", len(failed), describe(failed[0])
        )
    changed = {id(old): new for old, new in zip(nameless, fresh, strict=True)}
    recipients = [changed.get(id(c), c) for c in account.recipients]
    return replace(account, recipients=recipients)


def profile_lines(account: Account) -> list[str]:
    """E.g. ['+46700000000 · “Mybot” @mybot.01', '💬 Weather and photos']."""
    line = account.id
    if not (me := account.me):
        return [line]
    profile = me.profile or Profile()
    if name := full_name(profile.given_name, profile.lastname):
        line += f" · “{name}”"
    if me.username:
        line += f" @{me.username}"
    return [line, *([f"💬 {profile.about}"] if profile.about else [])]


def seen_day(seen: datetime, now: datetime) -> str:
    """'today', 'yesterday' or the date: Signal only keeps the day."""
    tz = get_settings().tz
    days = (now.astimezone(tz).date() - seen.astimezone(tz).date()).days
    if days < 1:
        return _("today")
    if days == 1:
        return _("yesterday")
    return f"{seen.astimezone(tz):%Y-%m-%d}"


def device_lines(devices: list[Device], now: datetime) -> list[str]:
    """A line each, e.g. '📟 #1 primary (seen today)'."""
    lines: list[str] = []
    for device in sorted(devices, key=lambda d: d.id):
        text = f"📟 #{device.id}"
        if device.id == 1:
            text += " " + _("primary")
        if device.name:
            text += f" {device.name}"
        if seen := device.last_seen:
            text += " " + _("(seen {day})").format(day=seen_day(seen, now))
        lines.append(text)
    return lines


def contact_lines(account: Account) -> list[str]:
    contacts, recipients = len(account.contacts), len(account.recipients)
    lines = [
        "👤 "
        + " · ".join(
            [
                ngettext("{count} contact", "{count} contacts", contacts).format(
                    count=contacts
                ),
                ngettext(
                    "{count} known recipient", "{count} known recipients", recipients
                ).format(count=recipients),
            ]
        )
    ]
    if blocked := [c.display_name for c in account.recipients if c.blocked]:
        lines.append("🚫 " + _("blocked: {who}").format(who=", ".join(sorted(blocked))))
    return lines


def identity_lines(account: Account, now: datetime) -> list[str]:
    identities = account.identities
    trusted = sum(i.status != UNTRUSTED for i in identities)
    verified = sum(i.status == VERIFIED for i in identities)
    line = "🔐 " + _("Safety numbers: {trusted} trusted ({verified} verified)").format(
        trusted=trusted, verified=verified
    )
    if untrusted := account.untrusted():
        line += " · " + _("{count} untrusted").format(count=len(untrusted))
    lines = [line]
    recent = sorted(
        account.name_of(i.number, i.uuid)
        for i in identities
        if (added := i.added_at) and now - added < RECENT
    )
    if recent:
        lines.append(
            "🆕 "
            + _("New or changed in the last week: {who}").format(who=", ".join(recent))
        )
    return lines


def group_lines(account: Account) -> list[str]:
    groups = [g for g in account.groups if g.member]
    admin = sum(any(account.is_me(a) for a in g.admins) for g in groups)
    members = {m for g in groups for m in g.members if not account.is_me(m)}
    lines = [
        "👥 "
        + " · ".join(
            [
                ngettext(
                    "{count} group (admin in {admin})",
                    "{count} groups (admin in {admin})",
                    len(groups),
                ).format(count=len(groups), admin=admin),
                ngettext(
                    "{count} other member", "{count} other members", len(members)
                ).format(count=len(members)),
            ]
        )
    ]
    more: list[str] = []
    if left := len(account.groups) - len(groups):
        more.append(_("{count} left").format(count=left))
    if invites := sum(len(g.pending_invites) for g in groups):
        more.append(
            ngettext(
                "{count} pending invite", "{count} pending invites", invites
            ).format(count=invites)
        )
    if more:
        lines.append(" · ".join(more))
    if requests := [g for g in groups if g.pending_requests]:
        waiting = ", ".join(
            f"{g.name or g.id[:14]} ({len(g.pending_requests)})" for g in requests
        )
        lines.append("🙋 " + _("Asking to join: {groups}").format(groups=waiting))
    return lines


def account_lines(account: Account) -> list[str]:
    """For /status: the account, a short line for each thing about it."""
    now = datetime.now(UTC)
    return [
        *profile_lines(account),
        *contact_lines(account),
        *identity_lines(account, now),
        *group_lines(account),
    ]
