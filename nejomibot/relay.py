"""/msg and /run: the admins post to other chats, from a direct chat with the
bot. The chats are numbers from /chats, such as 1,2.

/msg 1,2 Hello! posts the text to chats 1 and 2, as the bot, with what
nejomibot-chat attaches to it, which may then do without a text. /run 1 /status
runs the commands as a timer does, as the admin would in a direct chat with the
bot, and posts their answers to the chats instead: /run 1,2 /weather; /photo.
Its numbers are the admin's, as in /run 1 /incoming 4,9, which forwards
messages 4 and 9 of their list to chat 1. Like a timer, /run can't run what
changes timers, specials, birthdays, albums or who may use the bot, posts to
chats of its own, or answers for its own chat, as /remind does. Each chat gets
its answers in its language, and all of them the same photo.

Both answer where they posted, and where it only waits to be sent, as Signal
can't be reached, or may not have arrived.
"""

import logging
import re
from collections.abc import Callable

from signalbot import DataMessage, DataMessageContext, SendMessage, SignalBot

from .commands import Command, Edits, Handler, answer
from .config import get_settings
from .i18n import _
from .messages import Outcome, send
from .timers import Chat, chats_numbered, check_commands, split_commands, timekeeper

logger = logging.getLogger(__name__)

# The command, its chats as one word, like 1,2, then the rest, if any: the
# text, or the commands. "1, 2 Hi" isn't taken as "2 Hi" to chat 1.
PARTS = re.compile(r"^\S+\s+(\d+(?:,\d+)*)(?:\s+(\S.*))?$", re.DOTALL)


def msg_usage() -> str:
    return _(
        "Send /msg <chats> <text>, e.g. /msg 1,2 Hello! The chats are numbers "
        "from /chats."
    )


def run_usage() -> str:
    return _(
        "Send /run <chats> <commands>, e.g. /run 1 /weather; /photo. The chats "
        "are numbers from /chats."
    )


def parse(text: str) -> tuple[list[int], str] | None:
    """'/msg 1,2 Hello' -> ([1, 2], 'Hello'), '/msg 1,2' -> ([1, 2], ''); None
    if there are no chats."""
    if not (match := PARTS.match(text.strip())):
        return None
    return [int(n) for n in match[1].split(",")], (match[2] or "").strip()


def attached(message: DataMessage) -> list[str]:
    """What came with the message, for signal-cli-rest-api to send on: what
    nejomibot-chat attached. Of what comes from Signal, the bot downloads
    nothing (bot.main)."""
    files: list[str] = []
    for each in message.attachments or []:
        if each.base64_content:
            name = f";filename={each.remote_filename}" if each.remote_filename else ""
            files.append(f"data:{each.content_type}{name};base64,{each.base64_content}")
    return files


# What became of the posts to each chat
type Outcomes = dict[Chat, list[Outcome]]


def outcomes_text(posted: str, outcomes: Outcomes) -> str:
    """What became of the posts: posted, a translated text with {chats}, for
    the chats that got them all; then the chats where some wait to be sent,
    and those some may not have reached."""

    def chats(fits: Callable[[list[Outcome]], bool]) -> str:
        return ", ".join(name for (_id, name), those in outcomes.items() if fits(those))

    sent = chats(lambda those: all(o is Outcome.SENT for o in those))
    waiting = chats(
        lambda those: Outcome.GIVE_UP not in those and any(o.waits for o in those)
    )
    lost = chats(lambda those: Outcome.GIVE_UP in those)
    lines: list[str] = []
    if sent:
        lines.append(posted.format(chats=sent))
    if waiting:
        hours = f"{get_settings().send_retry_hours:g}"
        lines.append(
            _("⏳ Not sent yet to {chats}: tried again for {hours} hours.").format(
                chats=waiting, hours=hours
            )
        )
    if lost:
        lines.append(_("⚠️ May not have reached {chats}.").format(chats=lost))
    return "\n".join(lines)


async def post_text(bot: SignalBot, message: DataMessage) -> str:
    """Post /msg's text to its chats, and what nejomibot-chat attached to it.
    What to answer."""
    files = attached(message)
    if (parsed := parse(message.text or "")) is None or not (parsed[1] or files):
        return msg_usage()
    numbers, text = parsed
    if isinstance(chats := await chats_numbered(bot, numbers), str):
        return chats
    post = SendMessage(text=text or None, base64_attachments=files or None)
    outcomes: Outcomes = {chat: [await send(bot, chat[0], post)] for chat in chats}
    return outcomes_text(_("✉️ Sent to {chats}."), outcomes)


async def post_answers(bot: SignalBot, message: DataMessage) -> str | None:
    """Run /run's commands, as the admin who sent it, and post their answers
    to its chats, each command's before the next runs. What to answer, if
    anything."""
    if (parsed := parse(message.text or "")) is None or not parsed[1]:
        return run_usage()
    numbers, rest = parsed
    if isinstance(commands := split_commands(rest), str):
        return commands
    if why_not := check_commands(commands):
        return why_not
    if isinstance(chats := await chats_numbered(bot, numbers), str):
        return chats
    # As a timer posts them: in each chat's language, the same photo in all
    posted = await timekeeper.post(
        commands, [chat_id for chat_id, _name in chats], message
    )
    outcomes: Outcomes = {chat: posted[chat[0]] for chat in chats}
    # Posted here, they speak for themselves
    sender = message.source_number or message.source_uuid
    if [chat_id for chat_id, _name in chats] == [sender]:
        return None
    return outcomes_text(_("▶️ Posted the answers to {chats}."), outcomes)


# They post to other chats, so neither timers nor edits run them


class Msg(Handler):
    commands = (Command("/msg", more=True, timers=False),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        # What it posted has gone out: an edit isn't run, and says so
        await answer(
            context, lambda: post_text(context.bot, message), edits=Edits.NOT_RUN
        )


class Run(Handler):
    commands = (Command("/run", more=True, timers=False),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        await answer(
            context, lambda: post_answers(context.bot, message), edits=Edits.NOT_RUN
        )
