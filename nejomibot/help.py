"""/help: the commands the asker may use, a short line each, with an icon to
find them by, as Signal's bubbles are narrow. Everyone allowed sees the
everyday commands, and the admins' specials for everyone; an admin, in a
direct chat, the admin commands too, by name alone, so it all fits in one
bubble.

/help <command> shows a command's page: its line, then how to use it, with
examples, and more for the admins on some, in a direct chat. It takes a
command by any of its names, with or without its ., ! or /: /help photo,
/help .bild, an alias, or a shortcut, as an album's or a special's; and only
one the asker may use, as /help lists them.

A command shows by its name in the bot's language, if it has one, and with
its aliases: those the bot comes with, and those the config gives it; its
English name works in any language."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from signalbot import DataMessageContext

from . import access
from .commands import (
    ALIASES,
    COMMAND_START,
    Command,
    Handler,
    aliases,
    answer,
    argument,
    canonical,
)
from .config import as_command, get_settings
from .i18n import N_, SOURCE_LANGUAGE, _, language, names_of, prefixed, spoken
from .languages import another_language
from .messages import escape, short
from .specials import Parts, own_specials, summary
from .timers import example_date

# Between an example and what it does, on a page: '/list clear – …'
DASH = " – "


@dataclass(frozen=True)
class Entry:
    """A command in /help: its line, and its page."""

    icon: str
    name: str  # in English, as its handler takes it
    what: str  # what it does, in a few words, to translate
    # How to use it, to translate, a line each: an example and what it does,
    # as '/list clear – take everything off', shows the example in monospace
    page: str
    admins: str = ""  # more of it, for the admins in a direct chat


# Pages that several commands share

BIRTHDAYS = N_(
    "In a group, those of its people, the coming ones first. /today names "
    "them on the day."
)
BIRTHDAYS_FOR_ADMINS = N_(
    "In a direct chat, you see all of them, numbered, with where each shows."
)
ALLOWED = N_(
    "Who may use the everyday commands: people, in a direct chat with the "
    "bot, and groups, everyone in them.\n"
    "/allowed – the list, numbered\n"
    "/allow <who> – add someone, or a group the bot is in\n"
    "/disallow 2 – take number 2 off\n"
    "<who> is a number from /contacts, a phone number, a Signal ID, a "
    "group's ID or name, or someone's name."
)
ADMINS = N_(
    "Admins may use every command, the admin commands in a direct chat with "
    "the bot.\n"
    "/admins – who they are, numbered\n"
    "/admin add <who> – make someone an admin, with a welcome\n"
    "/admin add <who> <language> – and the bot speaks that language with "
    "them\n"
    "/admin remove 2 – number 2 is no longer one\n"
    "<who> is a number from /contacts, a phone number, a Signal ID or a "
    "name. Only the admins in the config can add and remove admins."
)
TIMERS = N_(
    "Timers run commands on a schedule and post their answers, such as a "
    "daily post.\n"
    "/timers – the timers, numbered\n"
    "/timer add 08:00 1,2 /today – every day at 08:00, to chats 1 and 2 of "
    "/chats\n"
    "/timer add mon-fri 07:30 /weather; /photo – on weekdays, to you\n"
    "/timer remove 2 – remove number 2\n"
    "/timer run 2 – run it now\n"
    "More ways to say when: 08:00,18:30 · sat,sun 10:00 · {date} 15:00, "
    "once · tomorrow 08:00 · every 2h or 30m, all in {zone} time."
)
RELAY = N_(
    "Post to other chats, by their numbers in /chats.\n"
    "/msg 1,2 Hello! – post a text to chats 1 and 2\n"
    "/run 1 /weather; /photo – post what the commands answer to chat 1\n"
    "/run runs what a timer can, as if you sent it here."
)
SPECIALS = N_(
    "Specials post texts and what other commands answer, in one go.\n"
    "/specials – yours\n"
    "/special add /morning Good morning! /today + /weather; /uniquephoto – a "
    "new one, or a change\n"
    "/special shortcuts /morning /gm – other names for it; - for none\n"
    "/special everyone /morning – for everyone allowed, groups too; /help "
    "lists it\n"
    "/special admins /morning – for the admins alone again\n"
    "/special remove /morning – remove it\n"
    "Parts are separated by ; or line breaks, and text before a command "
    "heads its answer. A + in place of a ; posts the parts on either side of "
    "it in one message. Text keeps the formatting you give it."
)
BIRTHDAY = N_(
    "/today names them in groups, on the day.\n"
    "/birthday add 1990-03-14 Alice – a contact's, in their groups, with the "
    "age\n"
    "/birthday add 03-14 Bob – without the year, no age\n"
    "/birthday add 05-01 1,2 Grandma – someone not on Signal, in chats 1 and "
    "2 of /chats; without numbers, in every group\n"
    "/birthday remove 2 – by its number in /birthdays\n"
    "/nameday add and /nameday remove work the same way. A contact must be "
    "saved by name, with /contacts add."
)
PROFILE = N_(
    "What everyone sees of the bot in Signal.\n"
    "/profile – the profile\n"
    "/name <name> – its name\n"
    "/about <text> – the text under its name\n"
    "/avatar – send a picture with this as its caption\n"
    "/username <name> – its username, and a link that starts a chat with it\n"
    "/about remove, /avatar remove and /username remove take them away. "
    "Signal adds a number to a username, as mybot.42, unless you give one."
)

# The everyday commands, in groups, as /help lists them
EVERYDAY = (
    (
        Entry(
            "📷",
            "/photo",
            N_("a random photo"),
            N_(
                "The caption says when and where it was taken.\n"
                "/photo – from every album\n"
                "/photo <album> – from that album\n"
                "/photo 2017 – one taken in 2017\n"
                "/photo 2017-05-14 – one taken that day\n"
                "/photo 2017-05-14 15:30 – the one taken closest to then\n"
                "/photo <album> 2017 – both\n"
                "Give a date as exactly as you like: a year, a month (2017-05), "
                "a day, an hour (2017-05-14 15) or a minute. If none was taken "
                "then, you get the nearest, and how far off it is. /albums "
                "lists the albums."
            ),
        ),
        Entry(
            "🆕",
            "/uniquephoto",
            N_("a photo not sent yet"),
            N_(
                "No photo comes twice until every photo has been sent; then a "
                "new round starts. It has the same caption as /photo.\n"
                "/uniquephoto – from every album\n"
                "/uniquephoto <album> – from that album, which has a round of "
                "its own"
            ),
        ),
        Entry(
            "🏞️",
            "/sphoto",
            N_("a photo without its caption"),
            N_(
                "Picked as /photo picks it, and sent alone, without a caption "
                "or heading.\n"
                "/sphoto – from every album\n"
                "/sphoto <album> – from that album\n"
                "/sphoto 2017-05-14 – one taken then, as /photo takes dates"
            ),
        ),
        Entry(
            "🎞️",
            "/onthisday",
            N_("this day, years ago"),
            N_(
                "A photo taken on this day in an earlier year, or else within "
                "three days of it, under a heading that says how many years "
                "ago.\n"
                "/onthisday – from every album\n"
                "/onthisday <album> – from that album"
            ),
        ),
        Entry(
            "📚",
            "/albums",
            N_("the albums"),
            N_(
                "How many photos each album has, from which years, and its "
                "shortcuts.\n"
                "/photo <album> – a photo from that album; every photo command "
                "takes one"
            ),
        ),
        Entry(
            "📂",
            "/cache",
            N_("how many photos, and how big"),
            N_(
                "How many photos there are, and how big, by file type, and how "
                "many albums.\n"
                "/cache – the whole library\n"
                "/cache <album> – that album"
            ),
        ),
    ),
    (
        Entry(
            "🌅",
            "/today",
            N_("the date, holidays and birthdays"),
            N_(
                "The date and time, the day's holidays, and in a group, its "
                "birthdays and name days."
            ),
            N_(
                "/today preview – what /today says in each chat\n"
                "/today preview {date} – on another day; tomorrow works too"
            ),
        ),
        Entry(
            "🌤️",
            "/weather",
            N_("the weather now"),
            N_(
                "From OpenWeatherMap, with the day's sunrise and sunset.\n"
                "/weather – in {city}\n"
                "/weather Helsinki – somewhere else\n"
                "/weather Springfield,US – the one in the US"
            ),
        ),
        Entry(
            "🌦️",
            "/forecast",
            N_("the weather today and tomorrow"),
            N_(
                "For each day, the worst weather, the lowest and highest "
                "temperatures, and the chance of rain or snow. Late in the "
                "evening, tomorrow and the day after.\n"
                "/forecast – in {city}\n"
                "/forecast Helsinki – somewhere else"
            ),
        ),
        Entry(
            "🕰️",
            "/info",
            N_("the time, and an exchange rate"),
            N_(
                "The current time in one or more places, and an exchange rate, "
                "as the bot's settings have them."
            ),
        ),
    ),
    (
        Entry(
            "🔔",
            "/remind",
            N_("reminders for this chat"),
            N_(
                "The bot posts each reminder in this chat when it's due, in "
                "{zone} time.\n"
                "/remind 18:00 Cake! – at the next 18:00\n"
                "/remind 30m Tea – in 30 minutes; 2h or 1h30m too\n"
                "/remind fri 17:00 Pizza! – on Friday; tomorrow works too\n"
                "/remind {date} 15:00 Presents – on that date\n"
                "/remind – the reminders here, numbered\n"
                "/remind remove 2 – remove number 2"
            ),
        ),
        Entry(
            "📝",
            "/list",
            N_("this chat's list"),
            N_(
                "A shared list, such as for shopping.\n"
                "/list – the list, numbered\n"
                "/list add milk, eggs – add things, separated by commas\n"
                "/list remove 2,5 – take numbers 2 and 5 off\n"
                "/list clear – take everything off"
            ),
        ),
        Entry(
            "🎂",
            "/birthdays",
            N_("the coming birthdays"),
            BIRTHDAYS,
            BIRTHDAYS_FOR_ADMINS,
        ),
        Entry(
            "🌸",
            "/namedays",
            N_("the coming name days"),
            BIRTHDAYS,
            BIRTHDAYS_FOR_ADMINS,
        ),
    ),
    (
        Entry(
            "🔮",
            "/fortune",
            N_("a fortune"),
            N_(
                "A random saying: a proverb, a quote or a joke.\n"
                "/fortune – from {library}\n"
                "/fortune all – from every library\n"
                "/fortune list – the libraries\n"
                "/fortune startrek – from that library"
            ),
        ),
        Entry(
            "🗣️",
            "/language",
            N_("the bot's language here"),
            N_(
                "A language is given by its code or its own name. In a group, "
                "only an admin can change it.\n"
                "/language – the languages, and the one spoken here\n"
                "/language {code} – {language} here\n"
                "/language default – the bot's own again"
            ),
            N_("/language 3,1 {code} – for chats 3 and 1 of /chats"),
        ),
        Entry(
            "🏓",
            "/ping",
            N_("is the bot there?"),
            N_("The bot answers pong!, with how long your message took to reach it."),
        ),
    ),
)
# /help ends the list, on a line of its own (more_text())
HELP = Entry(
    "❓",
    "/help",
    N_("the commands you can use"),
    N_("/help photo – more about /photo, and so on for every command"),
)
# The admin commands, as /help lists them for the admins: a line of names
# for each group, with its first one's icon
ADMIN = (
    (
        Entry(
            "🩺",
            "/status",
            N_("how the bot and the server are"),
            N_(
                "Two messages: the checks, the failed ones first, then the "
                "details: the bot, Signal, the network and the server."
            ),
        ),
        Entry(
            "📬",
            "/delivery",
            N_("whether the bot's messages arrived"),
            N_(
                "The bot's {count} latest messages, wherever it sent them, and "
                "how many in each chat got and read each one, as 📬 3/4 · 👀 2. "
                "⏳ means nobody has confirmed it yet, ⚠️ that nobody has in 10 "
                "minutes."
            ),
        ),
        Entry(
            "📥",
            "/incoming",
            N_("what people wrote to the bot"),
            N_(
                "The 50 latest messages people other than the admins sent the "
                "bot in direct chats.\n"
                "/incoming – the list, numbered\n"
                "/incoming 4,9 – forward those to you, in full"
            ),
        ),
        Entry(
            "↩️",
            "/delete",
            N_("delete the bot's messages"),
            N_(
                "For everyone, within a day of sending.\n"
                "/delete – the bot's latest message here, in groups too; again "
                "for the one before\n"
                "/delete list – its 50 latest messages, wherever it sent them, "
                "numbered\n"
                "/delete 2,5 – delete those"
            ),
        ),
        Entry(
            "📣",
            "/mention",
            N_("mention everyone in a group"),
            N_(
                "In a group, the bot mentions everyone but you and itself, which "
                "notifies them even if they've muted the group.\n"
                "/mention all – everyone\n"
                "/mention all Dinner's ready! – the text first, then everyone"
            ),
        ),
    ),
    (
        Entry("📋", "/allowed", N_("who may use the bot"), ALLOWED),
        Entry("➕", "/allow", N_("let someone, or a group, use the bot"), ALLOWED),
        Entry("➖", "/disallow", N_("take someone off the allowed list"), ALLOWED),
        Entry("👑", "/admins", N_("who the admins are"), ADMINS),
        Entry("🎖️", "/admin", N_("make someone an admin, or no longer"), ADMINS),
    ),
    (
        Entry(
            "👥",
            "/contacts",
            N_("who the bot knows"),
            N_(
                "Everyone the bot's Signal account knows, numbered, and whether "
                "each is verified.\n"
                "/contacts – everyone\n"
                "/contacts 3 – number 3 in full, with their safety number\n"
                "/contacts add 3 Alice – save number 3 as Alice, or rename them\n"
                "/contacts add @alice.42 Alice – someone new, by username or "
                "phone number\n"
                "In place of a number, you can give a phone number, a Signal ID "
                "or its start, or a name."
            ),
        ),
        Entry(
            "🔢",
            "/trust",
            N_("the safety numbers"),
            N_(
                "Numbered as /contacts numbers people, with whether each is "
                "verified.\n"
                "/trust – everyone's\n"
                "/trust 3 – number 3's\n"
                "/trust 3 <safety number> – mark it verified, once it matches "
                "the one on their phone"
            ),
        ),
    ),
    (
        Entry("⏰", "/timers", N_("what the bot runs on a schedule"), TIMERS),
        Entry("⏱️", "/timer", N_("add, remove or run a timer"), TIMERS),
        Entry(
            "🗨️",
            "/chats",
            N_("where timers can post"),
            N_(
                "Numbered: the groups the bot is in, then the people on the "
                "allowed list, then the admins. /timer add, /msg, /run, "
                "/language and /birthday add take these numbers."
            ),
        ),
        Entry("✉️", "/msg", N_("post a message to chats"), RELAY),
        Entry("▶️", "/run", N_("post commands' answers to chats"), RELAY),
        Entry(
            "📢",
            "/selfpromote",
            N_("the bot, in a few words, to share"),
            N_(
                "What the bot does, how it runs, and where its code and image "
                "are, under its picture.\n"
                "/selfpromote – here, to forward\n"
                "/run 1 /selfpromote – post it to chat 1"
            ),
        ),
    ),
    (
        Entry("✨", "/specials", N_("commands of your own"), SPECIALS),
        Entry("🧩", "/special", N_("make or change a special"), SPECIALS),
    ),
    (
        Entry("🎁", "/birthday", N_("add or remove a birthday"), BIRTHDAY),
        Entry("💐", "/nameday", N_("add or remove a name day"), BIRTHDAY),
        Entry(
            "📖",
            "/album",
            N_("an album, and the birth date for its ages"),
            N_(
                "/album <album> – the album: its photos, years, birth date and "
                "shortcuts\n"
                "/album <album> 2019-06-15 – captions show the age of who was "
                "born then\n"
                "/album <album> - – no age\n"
                "/album <album> shortcuts /alice – /alice is then /photo <album>\n"
                "/album <album> shortcuts - – none\n"
                "/albums lists the albums."
            ),
        ),
    ),
    (
        Entry("🪪", "/profile", N_("the bot's profile"), PROFILE),
        Entry("✏️", "/name", N_("the bot's name"), PROFILE),
        Entry("💬", "/about", N_("the bot's About text"), PROFILE),
        Entry("🖼️", "/avatar", N_("the bot's picture"), PROFILE),
        Entry("🔗", "/username", N_("the bot's username, and a link"), PROFILE),
    ),
)
EVERYDAY_ENTRIES = {entry.name: entry for group in EVERYDAY for entry in group}
ENTRIES = {
    **EVERYDAY_ENTRIES,
    HELP.name: HELP,
    **{entry.name: entry for group in ADMIN for entry in group},
}


def shown_name(command: str) -> str:
    """The command by its first name in the language, if it has one, as the
    bot shows commands (prefixed); one of two words, its subcommand too:
    /today preview as .idag förhandsvisa in Swedish."""
    first, space, second = command.partition(" ")
    name = next(iter(language().commands.get(first, [])), first)
    return prefixed(name + space + next(iter(language().words.get(second, [])), second))


def other_names(command: str, table: dict[str, str]) -> list[str]:
    """The command's aliases: the bot's own, then the config's, but those the
    config gives another command, as table, aliases()'s, has them."""
    names: dict[str, str] = {}  # each once, in any case
    for name in [*ALIASES.get(command, []), *get_settings().aliases.get(command, [])]:
        names.setdefault(name.casefold(), name)
    return [prefixed(name) for key, name in names.items() if table.get(key) == command]


def command_line(entry: Entry, table: dict[str, str] | None = None) -> str:
    """E.g. '📷 `.photo` – a random photo (.pic)': its aliases by table,
    aliases()'s, which a list of lines makes once. Styled."""
    line = f"{entry.icon} `{shown_name(entry.name)}`{DASH}{escape(_(entry.what))}"
    if names := other_names(entry.name, aliases() if table is None else table):
        line += f" ({escape(', '.join(names))})"
    return line


def names_line(entries: Sequence[Entry]) -> str:
    """E.g. '👥 `.contacts` `.trust`': commands by name alone, with the first
    one's icon. Styled."""
    return " ".join([entries[0].icon, *(f"`{shown_name(e.name)}`" for e in entries)])


def special_line(name: str, parts: Parts) -> str:
    """E.g. '✨ `.morning` – Good morning! .today + .weather (.gm)'. Styled."""
    line = f"✨ `{prefixed(name)}`{DASH}{escape(summary(parts))}"
    if shortcuts := own_specials.current().shortcuts.get(name):
        line += f" ({escape(', '.join(map(prefixed, shortcuts)))})"
    return line


def specials_section() -> str | None:
    """The admins' specials that everyone allowed may use, if any, a line
    each: what it posts, in short, and its shortcuts. Styled."""
    found = own_specials.current()
    lines = [
        special_line(name, parts)
        for name, parts in sorted(found.specials.items())
        if name in found.everyone
    ]
    return "\n".join([f"**{escape(_('Specials'))}**", *lines]) if lines else None


def more_text() -> str:
    """How to see a command's page, as /help photo. Styled."""
    name = shown_name("/help")
    example = f"{name} {shown_name('/photo')[1:]}"  # photo, without its prefix
    return escape(
        _("Send {help} and a command for more about it, as {example}.")
    ).format(help=f"`{name}`", example=f"`{example}`")


def help_message(admin: bool) -> str:
    """The commands an admin may use in a direct chat, or else those anyone
    allowed may, the admins' specials for everyone too. Styled."""
    table = aliases()
    title = _("For everyone allowed") if admin else _("Commands")
    groups = ("\n".join(command_line(e, table) for e in group) for group in EVERYDAY)
    parts = [f"**{escape(title)}**\n" + "\n\n".join(groups)]
    if found := specials_section():
        parts.append(found)
    if admin:
        title = f"**{escape(_('Admins, in a direct chat'))}**"
        parts.append("\n".join([title, *map(names_line, ADMIN)]))
    parts.append(more_text())
    return "\n\n".join(parts)


def fields() -> dict[str, str]:
    """What the pages' {fields} stand for, as the bot is set up."""
    settings = get_settings()
    code = another_language()
    return {
        "zone": settings.timezone_city,
        "date": example_date(datetime.now(settings.tz).date()),
        "city": settings.weather_city_name or settings.weather_city,
        "library": settings.fortune_library,
        "count": str(settings.delivery_messages),
        "code": code,
        "language": names_of(code).name,
    }


def page_lines(text: str) -> list[str]:
    """A page's lines, translated and filled in, an example's in monospace.
    Styled."""
    lines: list[str] = []
    for line in _(text).format(**fields()).splitlines():
        example, dash, does = line.partition(DASH)
        if dash and COMMAND_START.match(example):
            lines.append(f"`{escape(example)}`{dash}{escape(does)}")
        else:
            lines.append(escape(line))
    return lines


def hints() -> list[str]:
    """What /help's page says of every command's names."""
    found = [_("Commands start with ., ! or /, whichever is easier to type.")]
    if spoken() != SOURCE_LANGUAGE:
        found.append(_("Every command takes its English name too."))
    return found


def page(entry: Entry, admin: bool, table: dict[str, str]) -> str:
    """/help <command>: its line, then how to use it, and more for an admin
    in a direct chat, on some. Styled."""
    lines = [command_line(entry, table), *page_lines(entry.page)]
    if admin and entry.admins:
        lines += page_lines(entry.admins)
    if entry is HELP:
        lines += map(escape, hints())
    return "\n".join(lines)


def help_for(word: str, admin: bool) -> str:
    """/help <command>: the page of the command the word names, by any of its
    names, if the asker may use it; else that there's none. Styled."""
    table = aliases()
    asked = as_command(word)
    command, _space, rest = canonical(asked).partition(" ")
    command = command.lower()
    lines: list[str] = []
    if rest:  # a shortcut for a command and more, as an album's for /photo
        lines.append(
            escape(_("{shortcut} is short for {command}.")).format(
                shortcut=f"`{escape(prefixed(asked))}`",
                command=f"`{escape(prefixed(f'{command} {rest}'))}`",
            )
        )
    entry = ENTRIES.get(command)
    if entry and (admin or entry.name in EVERYDAY_ENTRIES or entry is HELP):
        return "\n".join([*lines, page(entry, admin, table)])
    found = own_specials.current()
    if (parts := found.specials.get(command)) and (admin or command in found.everyone):
        what = _("An admin's own command: it posts these, in order.")
        return "\n".join([*lines, special_line(command, parts), escape(what)])
    return escape(
        _("There's no command {name} here. {help} lists those you can use.").format(
            name=short(prefixed(asked)), help=shown_name("/help")
        )
    )


class Help(Handler):
    everyday = True
    commands = (Command("/help", more=True),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        admin = access.is_admin(message) and message.is_private()
        word = next(iter(argument(message.text).split()), "")
        await answer(
            context,
            lambda: help_for(word, admin) if word else help_message(admin),
            styled=True,
        )
