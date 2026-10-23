"""/today (or /day): the day's holidays, in the countries of the setting
holidays (holidays.py), and in a group, the birthdays and name days of those
it's for (birthdays.py), or that there's nothing special. For everyone
allowed. A timer posts it to every chat at once, each group with its own
birthdays, and on a day with nothing special, nothing, as do specials and
/run; with /weather and /uniquephoto after it, it's a daily post:
/timer add 08:00 1,2 /today; /weather; /uniquephoto.

/today preview, or /today preview 10-25, 2026-10-25 or tomorrow, shows an
admin what /today will say on that day, today if none is given, in each
group the bot is in and in a direct chat.
"""

import contextlib
from datetime import date, timedelta

from signalbot import DataMessageContext, SignalBot, TextMode

from . import birthdays
from .commands import Command, Handler, answer
from .config import get_settings
from .help import shown_name
from .holidays import days_on
from .i18n import _, weekday_and_day
from .messages import PerChat, collected, escape
from .timers import DAYS_FROM_NOW, in_language


async def day_message(bot: SignalBot, day: date | None = None) -> PerChat | None:
    """The day's holidays, in the countries of the setting holidays, and in
    a group, the birthdays and name days of those it's for: today's, or the
    day's; or that there's nothing special. Posted by a timer, a special or
    /run, a chat with nothing special gets nothing (messages.send()), and
    with nothing anywhere, there's no message. Styled."""
    day = day or birthdays.today()
    holidays = days_on(day, get_settings().holidays)
    greetings = await birthdays.greetings(bot, day)
    posted = collected.get() is not None
    if posted and not holidays and not any(greetings.values()):
        return None
    nothing = "" if posted else escape(_("Nothing special today."))
    return PerChat(
        text=escape("\n".join(holidays)) or nothing,
        texts={
            group: escape("\n".join([*holidays, *lines]))
            for group, lines in greetings.items()
        },
        text_mode=TextMode.STYLED,
    )


def preview_day(words: list[str], today: date) -> date | None:
    """The day /today preview is for: today, unless the words say which, as
    tomorrow, 10-25 (the next one) or 2026-10-25; None if they don't."""
    if not words:
        return today
    word = words[0].casefold()
    if len(words) > 1:
        return None
    if (ahead := in_language(DAYS_FROM_NOW).get(word)) is not None:
        return today + timedelta(days=ahead)
    if (found := birthdays.parse_date(word)) is None:
        return None
    year, month, day = found
    if year is not None:
        return date(year, month, day)
    for each in range(today.year, today.year + 5):  # 29 February, every 4th
        with contextlib.suppress(ValueError):
            if (next_one := date(each, month, day)) >= today:
                return next_one
    return None


async def preview(bot: SignalBot, words: list[str], today: date) -> str:
    """What /today will say on the day the words say, or today: in each
    group the bot is in, and in a direct chat. Styled."""
    if (day := preview_day(words, today)) is None:
        return escape(
            _("Which day? Such as 10-25, 2026-10-25 or tomorrow; none for today.")
        )
    settings = get_settings()
    holidays = days_on(day, settings.holidays)
    greetings = await birthdays.greetings(bot, day)
    groups = sorted(
        (group.name or f"{group.id[:14]}…", group.id)
        for group in bot.groups
        if group.member and (not settings.debug or group.id == settings.debug_group)
    )
    nothing = _("Nothing special.")
    title = _("👁️ {command} on {day}").format(
        command=shown_name("/today"), day=weekday_and_day(day)
    )
    parts = [f"**{escape(title)}**"]
    for name, group in groups:
        lines = "\n".join([*holidays, *greetings.get(group, [])]) or nothing
        parts.append(f"👥 **{escape(name)}**\n{escape(lines)}")
    lines = "\n".join(holidays) or nothing
    parts.append(f"👤 **{escape(_('In a direct chat'))}**\n{escape(lines)}")
    return "\n\n".join(parts)


class Today(Handler):
    """For everyone allowed, and for timers, which post them to every chat
    at once, each group with its own birthdays."""

    commands = (Command("/today"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot = context.bot
        await answer(context, lambda: day_message(bot), styled=True)


class TodayPreview(Handler):
    """For the admins, as it shows every group's birthdays. Timers may run
    it too, for the admins to have it posted somewhere."""

    commands = (Command("/today preview", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot = context.bot
        words = (context.message.text or "").split()
        today = birthdays.today()
        await answer(context, lambda: preview(bot, words[2:], today), styled=True)
