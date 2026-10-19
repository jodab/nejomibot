"""A greeting for those on the allowed list who write to the bot in a direct
chat, but no command: who the bot is, that /help lists the commands, and whom
to ask, the first admin. The names are as signal-cli knows them: the bot's
profile name, and the admin's name in the contacts (/contacts add), else
their profile name; without one, the greeting does without it.

Once a day at most for each person, so a thank-you after it isn't greeted
again; a restart forgets who was greeted. Commands are answered as ever, and
never with the greeting. The admins, strangers and groups aren't greeted,
nor edits, nor Signal's notes of a new disappearing time and the like.
"""

import logging
import time
from collections.abc import Callable

from signalbot import (
    DataMessage,
    DataMessageContext,
    DataMessageHandler,
    EditMessage,
    SendMessage,
    SignalBot,
)

from . import access
from .commands import canonical, known
from .config import get_settings
from .help import shown_name
from .i18n import _
from .incoming import attachments_of, sender_of
from .messages import reply
from .receipts import mark_read

logger = logging.getLogger(__name__)

AGAIN = 24 * 60 * 60  # seconds before someone is greeted again


async def greeting(bot: SignalBot) -> str:
    """Who the bot is, /help, and whom to ask, by the names signal-cli knows."""
    settings = get_settings()
    names = await access.names(bot)
    me = names.get(settings.account)
    admin = names.get(settings.admins[0]) if settings.admins else None
    return " ".join(
        [
            _("Hi, I'm {name}, a bot.").format(name=me) if me else _("Hi, I'm a bot."),
            _("Try {help} for a list of commands.").format(help=shown_name("/help")),
            _("Contact {admin} for more information.").format(admin=admin)
            if admin
            else _("Contact the bot's admin for more information."),
        ]
    )


class Greeter(DataMessageHandler):
    """Greets those on the allowed list who write in a direct chat, but no
    command, once a day."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._greeted: dict[str, float] = {}  # when, by whom

    async def handle_data_message(self, context: DataMessageContext) -> None:
        message = context.message
        if not self.greets(context.bot, message):
            return
        logger.info("Greeted someone in a direct chat")
        logger.debug("Greeted %s", sender_of(message))
        await mark_read(context)
        await reply(context, SendMessage(text=await greeting(context.bot)))

    def greets(self, bot: SignalBot, message: DataMessage) -> bool:
        """Whether to greet the sender, who then isn't for a day: someone on
        the allowed list, in a direct chat, who wrote something, but no
        command, and wasn't greeted in the last day."""
        if (
            message.is_group()
            or isinstance(message, EditMessage)
            or access.is_admin(message)
            or not access.permits(bot, message)
            or not (message.text or attachments_of(message))
            or known(canonical(message.text or ""))
        ):
            return False
        now = self._clock()
        self._greeted = {
            who: at for who, at in self._greeted.items() if now - at < AGAIN
        }
        if (sender := sender_of(message)) in self._greeted:
            return False
        self._greeted[sender] = now
        return True


greeter = Greeter()
