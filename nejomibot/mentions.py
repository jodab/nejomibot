"""/mention all: the bot mentions everyone in a group but itself and whoever
asked, for the admins, in any group the bot is in. Signal notifies whoever
is mentioned even if they've muted the group, which other messages don't:

  /mention all                    📣, then everyone
  /mention all Dinner's ready!    📣 Dinner's ready!, then everyone

From anyone else, it's ignored. Timers, /run and specials may run it: each
group they post to gets its own people mentioned, and a direct chat the
text alone.

The bot keeps the mentions in what people write too, as in /remind's and
/list's texts (styles.written()), and a reminder in a group mentions whoever
asked for it.
"""

from signalbot import DataMessageContext, SignalBot

from .commands import Command, Edits, Handler, answer
from .i18n import _
from .messages import PerChat, collected, members
from .styles import mention


def usage() -> str:
    return _(
        "/mention all: mention everyone in the group but you and the bot, which "
        "notifies them even if they've muted it. A text after it comes first, "
        "as in /mention all Dinner's ready!"
    )


def post_text(said: str, others: list[str]) -> str:
    """📣 and what was said, then everyone mentioned."""
    line = _("📣 {text}").format(text=said) if said else "📣"
    return "\n".join([line, " ".join(map(mention, others))]) if others else line


def mention_all(bot: SignalBot, said: str, sender: set[str]) -> PerChat:
    """Each group's post, mentioning all in it but the sender; for a direct
    chat, what was said alone."""
    texts = {
        group.id: post_text(
            said, [m for m in members(bot, group.id) or [] if m not in sender]
        )
        for group in bot.groups
        if group.member
    }
    return PerChat(text=post_text(said, []) if said else "", texts=texts)


class Mention(Handler):
    """For the admins, in every chat (bot.handlers())."""

    commands = (Command("/mention", more=True, subcommands=("all",)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        words = (message.text or "").split(maxsplit=2)
        said = words[2].strip() if len(words) > 2 else ""
        sender = {who for who in (message.source_uuid, message.source_number) if who}

        def post() -> str | PerChat:
            # Not in a direct chat, but as a timer, /run or a special, whose
            # posts go to groups too
            alone = collected.get() is None and not message.is_group()
            if len(words) < 2 or words[1].casefold() != "all" or alone:
                return usage()
            return mention_all(context.bot, said, sender)

        await answer(context, post, edits=Edits.NOT_RUN)
