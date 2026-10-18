"""Liveness check: /ping answers pong!, with how long the ping took to arrive."""

from signalbot import DataMessageContext

from .commands import Command, Handler, answer
from .i18n import _
from .messages import arrival_delay


def pong_text(delay: float) -> str:
    return _("pong! Your ping took {seconds} s to arrive").format(
        seconds=f"{delay:.1f}"
    )


class Ping(Handler):
    commands = (Command("/ping"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        delay = arrival_delay(context)  # before the read receipt
        await answer(context, lambda: pong_text(delay))
