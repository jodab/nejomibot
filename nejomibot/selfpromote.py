"""/selfpromote, for the admins: the bot by name, and where its code and its
container image are, on GitHub and Docker Hub, under its logo. In a
direct chat it comes to the admin, to forward; /run 1 /selfpromote posts it
to chat 1 of /chats, as a timer can.
"""

import base64
from importlib.resources import files

from signalbot import DataMessageContext, SendMessage, TextMode

from .commands import Command, Handler, answer
from .i18n import _
from .messages import escape

REPOSITORY = "https://github.com/jodab/nejomibot"
IMAGE = "https://hub.docker.com/r/jodab/nejomibot"
# Beside this file: the bot's logo, also the README's banner and the
# picture GitHub shows for the repository, rendered from .github/logo.svg by
# rsvg-convert -w 1280 -h 640
PICTURE = "logo.png"


def promotion() -> SendMessage:
    """The bot by name, and its links, under its picture. Styled."""
    picture = files(__package__).joinpath(PICTURE).read_bytes()
    encoded = base64.b64encode(picture).decode()
    title = _("nejomibot, a Signal bot for family and friends")
    links = "\n".join(
        [
            _("Source code and documentation: {url}").format(url=REPOSITORY),
            _("Container image: {url}").format(url=IMAGE),
        ]
    )
    text = f"**{escape(title)}**\n\n{escape(links)}"
    return SendMessage(
        text=text,
        text_mode=TextMode.STYLED,
        base64_attachments=[f"data:image/png;filename=nejomibot.png;base64,{encoded}"],
    )


class SelfPromote(Handler):
    """For the admins, in a direct chat, and for their timers and /run."""

    commands = (Command("/selfpromote"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, promotion)
