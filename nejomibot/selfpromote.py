"""/selfpromote, for the admins: the bot itself, in a few serious words, under
its social preview picture: what it does, how it runs, and where its code
and container image are. In a direct chat it comes to the admin, to forward;
/run 1 /selfpromote posts it to chat 1 of /chats, as a timer can.
"""

import base64
from importlib.resources import files

from signalbot import DataMessageContext, SendMessage, TextMode

from .commands import Command, Handler, answer
from .i18n import _, languages
from .messages import escape

REPOSITORY = "https://github.com/jodab/nejomibot"
IMAGE = "https://hub.docker.com/r/jodab/nejomibot"
# Beside this file: the picture GitHub shows for the repository, from
# .github/social-preview.svg
PICTURE = "social-preview.png"


def promotion() -> SendMessage:
    """The bot, in a few words, under its picture. Styled."""
    picture = files(__package__).joinpath(PICTURE).read_bytes()
    encoded = base64.b64encode(picture).decode()
    paragraphs = [
        _(
            "Every morning it can post the day's holidays, birthdays and name "
            "days, the weather, and a photo from your own photo library. During "
            "the day, it answers commands for photos, the weather, reminders, "
            "shared lists and timers, in {count} languages."
        ).format(count=len(languages())),
        _(
            "It runs on your own server, as a container under Podman or Docker, "
            "on x86 and ARM, a Raspberry Pi included, in less than 100 MB of "
            "memory. It is open source, under the MIT license, and its code is "
            "written by AI, under its maintainer's guidance."
        ),
        "\n".join(
            [
                _("Source code and documentation: {url}").format(url=REPOSITORY),
                _("Container image: {url}").format(url=IMAGE),
            ]
        ),
    ]
    title = _("nejomibot, a Signal bot for family and friends")
    text = "\n\n".join([f"**{escape(title)}**", *map(escape, paragraphs)])
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
