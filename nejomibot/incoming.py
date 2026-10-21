"""/incoming: what people write to the bot in direct chats, for the admins.

The bot keeps the 50 latest messages anyone but the admins sends it in a
direct chat, commands and strangers' too, with their formatting, in memory
only: a restart forgets them. One its sender deletes for everyone goes, as
does one that disappears, once its time is up; an edit replaces the message
it edits.

/incoming, for the admins in a direct chat, lists them, newest first,
numbered: when, from whom, and how each starts, with 📎 for attachments.
/incoming 4,9 forwards those two to the admin, each a message of its own, in
full: their text, as the bot doesn't fetch attachments; it says how many
there were. The numbers are those of the list the admin was shown last,
whatever comes in meanwhile, until they ask for the list again; a list a
timer, /run or a special posts doesn't change them. Timers and /run can run
it too, as /run 1 /incoming 4,9, which forwards those two to chat 1.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from signalbot import (
    DataMessage,
    DataMessageContext,
    DataMessageHandler,
    EditMessage,
    RemoteDelete,
    RemoteDeleteContext,
    RemoteDeleteHandler,
    SignalBot,
)

from . import access
from .access import is_admin
from .commands import Command, Handler, answer, numbers_in
from .config import get_settings
from .i18n import _, ngettext, when_text
from .messages import collected, escape, short
from .styles import bold, marked, styles_of, unmarked

KEPT = 50  # messages the bot keeps, and /incoming lists


@dataclass(frozen=True)
class Received:
    """A message someone sent the bot in a direct chat, as it is now."""

    sender: str  # their Signal ID, else their phone number
    timestamp: int  # by their clock, in ms: with sender, what Signal knows it by
    name: str  # as Signal gave it with the message, else their number or ID
    text: str  # in marks, for its formatting
    attachments: int  # a sticker too
    gone_at: datetime | None = None  # when it disappears, if it does
    number: str | None = None  # theirs, if the message came with it

    @property
    def at(self) -> datetime:
        return datetime.fromtimestamp(self.timestamp / 1000, UTC)


def sender_of(message: DataMessage | RemoteDelete) -> str:
    return message.source_uuid or message.source_number or ""


def attachments_of(message: DataMessage) -> int:
    """How many attachments the message has, a sticker as one."""
    return len(message.attachments or []) + bool(message.sticker)


def text_of(message: DataMessage) -> str:
    """The message's text in marks, with its formatting, if marks can say it."""
    text = message.text or ""
    if message.text_styles:
        return marked(text, styles_of(text, message.text_styles)) or escape(text)
    return escape(text)


class Inbox(DataMessageHandler, RemoteDeleteHandler):
    """The latest messages anyone but the admins sent the bot in a direct chat,
    oldest first. Only in memory."""

    def __init__(self, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self._now = now
        self._kept: list[Received] = []
        self.since = now()

    async def handle_data_message(self, context: DataMessageContext) -> None:
        self.keep(context.message)

    async def handle_remote_delete(self, context: RemoteDeleteContext) -> None:
        """Its sender deleted it for everyone."""
        self.forget(sender_of(context.message), context.message.timestamp)

    def keep(self, message: DataMessage) -> None:
        """Keep the message, if it's one to keep: in a direct chat, not from an
        admin, with text or attachments, unlike Signal's notes of a new profile
        key or disappearing time. An edit replaces what it edits, in its place."""
        if message.is_group() or is_admin(message):
            return
        attachments = attachments_of(message)
        if not (message.text or attachments):
            return
        sender = sender_of(message)
        timestamp = message.timestamp
        if isinstance(message, EditMessage):
            timestamp = message.target_sent_timestamp
        seconds = message.expires_in_seconds
        received = Received(
            sender,
            timestamp,
            message.source_name or message.source_number or sender,
            text_of(message),
            attachments,
            self._now() + timedelta(seconds=seconds) if seconds else None,
            message.source_number,
        )
        for i, kept in enumerate(self._kept):
            if (kept.sender, kept.timestamp) == (sender, timestamp):
                self._kept[i] = received
                return
        self._kept.append(received)
        del self._kept[:-KEPT]

    def forget(self, sender: str, timestamp: int) -> None:
        self._kept = [
            kept
            for kept in self._kept
            if (kept.sender, kept.timestamp) != (sender, timestamp)
        ]

    def latest(self) -> list[Received]:
        """The messages kept, newest first."""
        self._forget_gone()
        return self._kept[::-1]

    def find(self, sender: str, timestamp: int) -> Received | None:
        """The message as it is now, if it's still kept."""
        self._forget_gone()
        return next(
            (k for k in self._kept if (k.sender, k.timestamp) == (sender, timestamp)),
            None,
        )

    def _forget_gone(self) -> None:
        """Forget the messages that have disappeared."""
        now = self._now()
        self._kept = [k for k in self._kept if k.gone_at is None or k.gone_at > now]


inbox = Inbox()

# The messages each admin was shown last, by who they are, and the names they
# were shown with: /incoming <n> takes the numbers from there. Only in memory,
# so after a restart, the list again.
shown: dict[str, list[tuple[Received, str]]] = {}


def entry_text(number: int, received: Received, name: str, now: datetime) -> str:
    """E.g. '4 · 08:14 · Alice · Hej! Vem är det på…'."""
    start = short(unmarked(received.text)[0])
    if received.attachments:
        start = f"📎 {start}".rstrip()
    return f"{number} · {when_text(received.at, now)} · {name} · {start}"


async def list_incoming(bot: SignalBot, who: str) -> str:
    """The messages kept, newest first, numbered for who to forward some of
    them; or that there are none. Styled."""
    latest = inbox.latest()
    names = await access.names(bot) if latest else access.Names()
    rows = [
        (received, names.of(received.number or received.sender, received.name))
        for received in latest
    ]
    # Not for a timer, /run or a special, which show it to others
    if collected.get() is None:
        shown[who] = rows
    if not rows:
        since = inbox.since.astimezone(get_settings().tz)
        return escape(
            _("No messages kept since the bot started, at {time}.").format(
                time=f"{since:%Y-%m-%d %H:%M}"
            )
        )
    now = datetime.now(UTC)
    lines = [
        entry_text(n, received, name, now) for n, (received, name) in enumerate(rows, 1)
    ]
    title = _("Incoming messages, newest first:")
    hint = _("/incoming <n> forwards one to you, in full; /incoming 4,9 several.")
    return f"📥 **{escape(title)}**\n" + escape("\n".join([*lines, "", hint]))


def forward_text(received: Received, name: str, now: datetime) -> str:
    """The message in full, under who sent it and when. Styled."""
    lines = [f"↪️ {bold(name)} · {escape(when_text(received.at, now))}"]
    if received.text:
        lines.append(received.text)
    if count := received.attachments:
        note = ngettext(
            "📎 and an attachment, which the bot can't forward",
            "📎 and {count} attachments, which the bot can't forward",
            count,
        )
        lines.append(escape(note.format(count=count)))
    return "\n".join(lines)


def forwards(who: str, numbers: list[int]) -> list[str] | str:
    """The messages of those numbers in the list who was shown last, each in
    full, as they are now; or why not. Styled."""
    listed = shown.get(who)
    if listed is None:
        return escape(_("Which ones? Send /incoming first, for their numbers."))
    if wrong := [n for n in numbers if not 1 <= n <= len(listed)]:
        return escape(
            _("There's no message {n}: /incoming numbers them.").format(n=wrong[0])
        )
    now = datetime.now(UTC)
    found: list[str] = []
    for n in numbers:
        was, name = listed[n - 1]
        if (received := inbox.find(was.sender, was.timestamp)) is None:
            gone = _("Message {n} is gone: its sender deleted it, or it disappeared.")
            found.append(escape(gone.format(n=n)))
        else:
            found.append(forward_text(received, name, now))
    return found


def usage() -> str:
    return "\n".join(
        [
            _("/incoming: the latest messages people sent the bot, numbered"),
            _("/incoming <n>: forward one to you, in full; /incoming 4,9 several"),
        ]
    )


class Incoming(Handler):
    """For the admins only: it shows what others wrote, where they choose,
    their timers and /run too."""

    commands = (Command("/incoming", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        bot = context.bot
        who = message.source_uuid or message.source_number or ""
        rest = (message.text or "").split(maxsplit=1)[1:]
        if not rest:
            await answer(context, lambda: list_incoming(bot, who), styled=True)
        elif (numbers := numbers_in(rest[0])) is not None:
            await answer(context, lambda: forwards(who, numbers), styled=True)
        else:
            await answer(context, usage)
