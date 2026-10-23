"""/today: the weather in weather_city, as /weather has it, with the day's
holidays atop it, in the countries of the setting holidays (holidays.py),
and in a group, the birthdays and name days of those it's for
(birthdays.py). /day: the same, without the weather, or that there's
nothing special. For everyone allowed. A timer posts them to every chat at
once, each group with its own birthdays; /today with /photo new after it is
a daily post: /timer add 08:00 1,2 /today; /photo new.

/today preview, or /today preview 10-25, 2026-10-25 or tomorrow, shows an
admin what /today will say atop the weather on that day, today if none is
given, in each group the bot is in and in a direct chat.
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
from .messages import PerChat, escape
from .timers import DAYS_FROM_NOW, in_language
from .weather import weather_message


def atop(lines: list[str], text: str) -> str:
    """The lines, styled, over the styled text, a blank line between, as far
    as there are any."""
    return "\n\n".join(part for part in (escape("\n".join(lines)), text) if part)


async def day_message(
    bot: SignalBot, under: str = "", day: date | None = None
) -> PerChat:
    """The day's holidays, in the countries of the setting holidays, and in
    a group, the birthdays and name days of those it's for, atop the text
    under, if any: today's, or the day's; or that there's nothing special.
    Styled."""
    day = day or birthdays.today()
    holidays = days_on(day, get_settings().holidays)
    greetings = await birthdays.greetings(bot, day)
    return PerChat(
        text=atop(holidays, under) or escape(_("Nothing special today.")),
        texts={
            group: atop([*holidays, *lines], under)
            for group, lines in greetings.items()
        },
        text_mode=TextMode.STYLED,
    )


async def today_message(bot: SignalBot, day: date | None = None) -> PerChat:
    """The weather, with the day atop it. Styled."""
    return await day_message(bot, await weather_message(), day)


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
    """What /today will say atop the weather on the day the words say, or
    today: in each group the bot is in, and in a direct chat. Styled."""
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
    nothing = _("Nothing atop the weather.")
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

    commands = (Command("/today"), Command("/day"))

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot = context.bot
        if command.name == "/day":
            await answer(context, lambda: day_message(bot), styled=True)
        else:
            await answer(context, lambda: today_message(bot), slow=True, styled=True)


class TodayPreview(Handler):
    """For the admins, as it shows every group's birthdays. Timers may run
    it too, for the admins to have it posted somewhere."""

    commands = (Command("/today preview", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        bot = context.bot
        words = (context.message.text or "").split()
        today = birthdays.today()
        await answer(context, lambda: preview(bot, words[2:], today), styled=True)
