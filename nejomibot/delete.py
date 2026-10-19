"""/delete: delete the bot's messages, for everyone. Only for the admins.

/delete, in any chat, groups too, deletes the bot's latest message there.
Sent again, it deletes the one before, and so on.

/delete list, in a direct chat, shows the bot's 50 latest messages,
wherever it sent them, numbered: when, where, and how each starts. /delete 3
deletes one of them, /delete 2,5,11 several, one after the other, until one
can't be. The numbers are those of the list the admin was shown last,
whatever the bot sends meanwhile, until they ask for the list again.

Signal only deletes messages for everyone within a day of sending them, and
the bot only knows what it has sent since it started.
"""

import logging
from datetime import UTC, datetime

from signalbot import DataMessageContext, SentMessage, SignalBot

from . import access
from .access import is_admin
from .commands import Command, Edits, Handler, answer, numbers_in
from .config import get_settings
from .i18n import _, when_text
from .messages import (
    DELETABLE_FOR,
    Sent,
    SentLog,
    chats_of,
    error_text,
    escape,
    log_failure,
    outbox,
    short,
)
from .styles import unmarked

logger = logging.getLogger(__name__)

LISTED = 50  # messages /delete list shows

# The messages each admin was shown last, by who they are, and their lines
# in the list: /delete <n> takes the numbers from there. Only in memory, so
# after a restart, the list again.
shown: dict[str, list[tuple[Sent, str]]] = {}


async def remote_delete(bot: SignalBot, sent: Sent) -> None:
    """Delete the message for everyone in its chat."""
    message = SentMessage(recipient=sent.chat, timestamp=sent.timestamp)
    await bot.messages.remote_delete(message)


def nothing_text(since: datetime, now: datetime) -> str:
    if now - since < DELETABLE_FOR:
        started = since.astimezone(get_settings().tz)
        return _(
            "Nothing left to delete here since the bot started, at {time}."
        ).format(time=f"{started:%Y-%m-%d %H:%M}")
    return _(
        "Nothing left to delete here from the last day: Signal only deletes "
        "messages for everyone within a day."
    )


async def delete_latest(bot: SignalBot, log: SentLog, chats: set[str]) -> str | None:
    """Delete the bot's latest message in the chat. None once it's deleted,
    else what went wrong."""
    if not (sent := log.pop(chats)):
        return nothing_text(log.since, datetime.now(UTC))
    return await delete_sent(bot, log, sent)


async def delete_sent(bot: SignalBot, log: SentLog, sent: Sent) -> str | None:
    """Delete the message, taken out of the log. None once it's deleted, else
    what went wrong, and it's back in the log, for another try."""
    try:
        await remote_delete(bot, sent)
    except Exception as e:
        log_failure(logger, f"Deleting message {sent.timestamp}", e)
        log.add(sent)
        return error_text(e)
    logger.info("Deleted message %d", sent.timestamp)
    return None


# The list, and its numbers


def start_text(sent: Sent) -> str:
    """How the message starts, as it shows, cut short; 📷 if it's a photo."""
    text = short(unmarked(sent.start)[0] if sent.styled else sent.start)
    return f"📷 {text}".rstrip() if sent.photo else text


def entry_text(number: int, sent: Sent, now: datetime, names: dict[str, str]) -> str:
    """E.g. '3 · 07:42 · 👤 Alice · pong! Your ping took…'."""
    icon = "👥" if access.is_group(sent.chat) else "👤"
    where = f"{icon} {names.get(sent.chat, sent.chat)}"
    return f"{number} · {when_text(sent.at, now)} · {where} · {start_text(sent)}"


def nothing_sent_text(since: datetime, now: datetime) -> str:
    if now - since < DELETABLE_FOR:
        started = since.astimezone(get_settings().tz)
        return _("The bot has sent nothing since it started, at {time}.").format(
            time=f"{started:%Y-%m-%d %H:%M}"
        )
    return _(
        "The bot has sent nothing in the last day, and Signal only deletes "
        "messages for everyone within a day."
    )


async def list_sent(bot: SignalBot, log: SentLog, who: str) -> str:
    """The bot's latest messages, wherever it sent them, newest first,
    numbered for who to delete one of them; or that there are none. Styled."""
    now = datetime.now(UTC)
    latest = log.latest(LISTED)
    names = await access.names(bot) if latest else {}
    lines = [entry_text(n, sent, now, names) for n, sent in enumerate(latest, 1)]
    shown[who] = list(zip(latest, lines, strict=True))
    if not lines:
        return escape(nothing_sent_text(log.since, now))
    title = _("The bot's latest messages, newest first:")
    hint = _("/delete <n> deletes one for everyone; /delete 2,5,11 several.")
    return f"📤 **{escape(title)}**\n" + escape("\n".join([*lines, "", hint]))


async def delete_listed(
    bot: SignalBot, log: SentLog, who: str, numbers: list[int]
) -> str:
    """Delete the messages of those numbers in the list who was shown last,
    one after the other, until one can't be, as when Signal can't be
    reached, where the rest would fail too; say which, and why not. Styled."""
    listed = shown.get(who)
    if listed is None:
        return escape(_("Which ones? Send /delete list first, for their numbers."))
    if wrong := [n for n in numbers if not 1 <= n <= len(listed)]:
        return escape(
            _("There's no message {n}: /delete list numbers them.").format(n=wrong[0])
        )
    deleted: list[str] = []
    notes: list[str] = []
    for i, n in enumerate(numbers):
        sent, line = listed[n - 1]
        if not log.take(sent):
            gone = _(
                "Message {n} is gone already: deleted, or too old for Signal to delete."
            )
            notes.append(gone.format(n=n))
        elif error := await delete_sent(bot, log, sent):
            notes.append(error)
            if rest := numbers[i + 1 :]:
                left = _("Not tried after that: {numbers}")
                notes.append(left.format(numbers=", ".join(map(str, rest))))
            break
        else:
            deleted.append(line)
    parts: list[str] = []
    if deleted:
        parts.append(f"🗑️ **{escape(_('Deleted'))}**\n" + escape("\n".join(deleted)))
    if notes:
        parts.append(escape("\n".join(notes)))
    return "\n\n".join(parts)


def usage() -> str:
    return "\n".join(
        [
            _("/delete: delete the bot's latest message here, for everyone"),
            _("/delete list: its latest messages, wherever it sent them"),
            _("/delete <n>: delete one of those for everyone; /delete 2,5,11 several"),
        ]
    )


class Delete(Handler):
    commands = (Command("/delete", more=True, subcommands=("list",)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        # signalbot only checks who sent it in direct chats
        if not is_admin(message):
            logger.info("Ignored /delete from someone not an admin")
            return
        bot, log = context.bot, outbox.sent
        words = (message.text or "").split()
        if len(words) == 1:
            # Deleted is reply enough: anything posted would be the next to
            # go. A deletion can't be undone, so an edit is let be, quietly.
            chats = chats_of(context)
            await answer(
                context, lambda: delete_latest(bot, log, chats), edits=Edits.IGNORE
            )
            return
        if message.is_group():
            # Not in groups: the list shows what the bot sent to every chat
            logger.info("Ignored /delete with more than its name in a group")
            return
        who = message.source_uuid or message.source_number or ""
        rest = (message.text or "").split(maxsplit=1)[1]
        if rest.strip().casefold() == "list":
            await answer(context, lambda: list_sent(bot, log, who), styled=True)
        elif (picked := numbers_in(rest)) is not None:
            await answer(
                context,
                lambda: delete_listed(bot, log, who, picked),
                edits=Edits.NOT_RUN,
                styled=True,
            )
        else:
            await answer(context, usage)
