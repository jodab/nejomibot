"""/help: the commands the asker may use, a short line each, with an icon to
find them by, as Signal's bubbles are narrow. Everyone allowed sees the
everyday commands; an admin, in a direct chat, all of them.

A command shows by its name in the bot's language, if it has one, and with
its aliases: those the bot comes with, and those the config gives it; its
English name works in any language."""

from dataclasses import dataclass
from datetime import datetime

from signalbot import DataMessageContext

from . import access
from .commands import ALIASES, Command, Handler, aliases, answer
from .config import get_settings
from .i18n import N_, SOURCE_LANGUAGE, _, language
from .messages import escape
from .timers import example_date


@dataclass(frozen=True)
class Line:
    """A command's line in /help."""

    icon: str
    name: str  # in English, as its handler takes it
    what: str  # what it does, in a few words, to translate
    args: str = ""  # what follows it, to translate


EVERYDAY = [
    Line("📷", "/photo", N_("a random photo")),
    Line("📂", "/cache", N_("how many photos, and how big")),
    Line("🌤️", "/weather", N_("the weather now")),
    Line("🕰️", "/info", N_("the time, and an exchange rate")),
    Line("🏓", "/ping", N_("is the bot there?")),
    Line("🔮", "/fortune", N_("a fortune"), N_("[<library>|all|list]")),
    Line("❓", "/help", N_("these commands")),
]
ADMIN = [
    Line("🩺", "/status", N_("how the bot and the server are")),
    Line("🌅", "/dailypost", N_("the daily post, here")),
    Line("📜", "/dailyquote", N_("the daily quote, here")),
    Line("👥", "/contacts", N_("who the bot knows"), N_("[<who>]")),
    Line("📇", "/contacts", N_("add a contact, or rename"), N_("add <who> <name>")),
    Line("🔐", "/trust", N_("mark as verified"), N_("<who> <safety number>")),
    Line("📋", "/allowed", N_("who may use the bot")),
    Line("➕", "/allow", N_("put someone, or a group, on that list"), N_("<who>")),
    Line("➖", "/disallow", N_("take someone off it"), N_("<n>")),
    Line("🪪", "/profile", N_("the bot's profile")),
    Line("✏️", "/name", N_("its name"), N_("<name>")),
    Line("💬", "/about", N_("its About text"), N_("<text>")),
    Line("🖼️", "/avatar", N_("its picture: send one with this as its caption")),
    Line("🔗", "/username", N_("its username, and a link"), N_("<name>")),
    Line("⏰", "/timers", N_("what it runs on a schedule")),
    Line("🗨️", "/chats", N_("where timers can post")),
    Line("⏱️", "/timer", N_("a new timer"), N_("add <when> [<chats>] <commands>")),
    Line("⚙️", "/timer", N_("remove one, or run it now"), N_("remove <n> · run <n>")),
    Line("✨", "/specials", N_("commands of your own")),
    Line("🧩", "/special", N_("a new one, or a change"), N_("add <name> <parts>")),
    Line("🗑️", "/special", N_("remove one"), N_("remove <name>")),
    Line("✉️", "/msg", N_("post a message to chats"), N_("<chats> <text>")),
    Line("▶️", "/run", N_("post commands' answers to chats"), N_("<chats> <commands>")),
    Line("📥", "/incoming", N_("messages people sent it; forward some"), N_("[<n>,…]")),
    Line(
        "📤",
        "/delete",
        N_("its latest messages anywhere; delete some"),
        N_("list · <n>,…"),
    ),
]
ANYWHERE = [
    Line("↩️", "/delete", N_("delete its latest message here")),
]


def shown_name(command: str) -> str:
    """The command by its first name in the language, if it has one."""
    return next(iter(language().commands.get(command, [])), command)


def other_names(command: str) -> list[str]:
    """The command's aliases: the bot's own, then the config's, but those the
    config gives another command."""
    table = aliases()
    names = [*ALIASES.get(command, []), *get_settings().aliases.get(command, [])]
    return [name for name in names if table[name.casefold()] == command]


def command_line(command: Line) -> str:
    """E.g. '📷 `/photo` – a random photo (/pic)': the aliases on the
    command's first line only. Styled."""
    usage = shown_name(command.name)
    if command.args:
        usage += f" {_(command.args)}"
    line = f"{command.icon} `{usage}` – {escape(_(command.what))}"
    lines = EVERYDAY + ADMIN + ANYWHERE
    first = next(each for each in lines if each.name == command.name)
    if first is command and (names := other_names(command.name)):
        line += f" ({escape(', '.join(names))})"
    return line


def section(title: str, commands: list[Line]) -> str:
    return "\n".join([f"**{escape(title)}**", *map(command_line, commands)])


def notes() -> list[str]:
    """What goes in the <> of the admins' commands, a line each."""
    settings = get_settings()
    zone = settings.timezone.rsplit("/", 1)[-1].replace("_", " ")
    date = example_date(datetime.now(settings.tz).date())
    return [
        _("<who> – a name, number or ID, as /contacts shows; /allow takes groups too"),
        _("<n> – a number from /allowed, /timers, /delete list or /incoming"),
        _(
            "<when> – 08:00 · mon-fri 07:30 · {date} 15:00 · tomorrow 08:00 · "
            "every 2h, in {zone} time"
        ).format(date=date, zone=zone),
        _("<chats> – numbers from /chats, like 1,2; a timer without them posts to you"),
        _(
            "<parts> – text and commands, separated by ;, e.g. Good morning! "
            "/weather; /dailyquote"
        ),
        _("remove – after /about, /avatar or /username, takes it away"),
    ]


def help_message(admin: bool) -> str:
    """The commands an admin may use in a direct chat, or else those anyone
    allowed may. Styled."""
    if admin:
        allowed = len(access.allowed_list.current().entries)
        parts = [
            section(
                _("For everyone allowed ({count})").format(count=allowed), EVERYDAY
            ),
            section(_("Admins, in a direct chat"), ADMIN),
            section(_("Admins, in any chat"), ANYWHERE),
            escape("\n".join(notes())),
        ]
    else:
        parts = [section(_("Commands"), EVERYDAY)]
    if get_settings().language != SOURCE_LANGUAGE:
        parts.append(escape(_("Every command takes its English name too.")))
    return "\n\n".join(parts)


class Help(Handler):
    commands = (Command("/help"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        message = context.message
        admin = access.is_admin(message) and message.is_private()
        await answer(context, lambda: help_message(admin), styled=True)
