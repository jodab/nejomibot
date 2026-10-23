"""/admins and /admin: who the admins are, and who else is one. For the
admins only, in direct chats.

The admins in the config may make others admins: /admin add <who>, who as
/allow takes someone (their number in /contacts, phone number, Signal ID or
name), and /admin remove <n>, by their number in /admins. Someone made an
admin gets a welcome, in a direct chat: that they are one, that /help lists
every command, and a few to start with, as /help shows them. It's in their
language, or in the one given after them, as /admin add 3 sv, which the bot
speaks with them from then on. The admins added
may use every command, as the config's may, but they can't add or remove
admins, and no command can take away what the config's admins may do. The
notices (notices.py) go to the config's admins alone.

The admins added are kept by Signal ID, as a phone number can change hands,
and a Signal ID can't: someone whose ID the bot doesn't know yet, as they've
never written to it nor been in a group with it, can't be added by phone
number. They're kept in data_dir/admins.txt, a Signal ID a line, which can
be changed by hand, as the allowed list can (access.py).
"""

import logging
import re

from signalbot import DataMessageContext, SendMessage, TextMode

from . import access, contacts
from .access import Entry, admin_list, allowed_list, is_group
from .account import Account, Contact, fetch_account, find_by_ids
from .allowed import entry_text, find_listed, name_of, typed_chat_id
from .commands import Command, Edits, Handler, answer, undo_with
from .config import SIGNAL_ID, get_settings
from .help import ADMIN, EVERYDAY, command_line, shown_name
from .i18n import _, chat_language, speaking
from .languages import language_named, named, set_language
from .messages import Outcome, escape, send, unreadable_text

logger = logging.getLogger(__name__)

CHANGES = ("add", "remove", "delete")  # what follows /admin
# What a new admin's welcome starts them with, as /help shows them
WELCOME_COMMANDS = (
    "/status",
    "/contacts",
    "/allowed",
    "/timers",
    "/specials",
    "/language",
)


def usage() -> str:
    return "\n".join(
        [
            _(
                "/admin add <who> [<language>]: make someone an admin, by their "
                "number in /contacts, phone number, Signal ID or name, and send "
                "them a welcome; with a language, such as sv, the bot speaks it "
                "with them"
            ),
            _("/admin remove <n>: no longer, by their number in /admins"),
            only_the_config_text(),
        ]
    )


def only_the_config_text() -> str:
    return _("Only the admins in the config add and remove admins.")


async def list_admins(context: DataMessageContext) -> str:
    """The config's admins, then those added, numbered. Styled."""
    added = admin_list.reread()
    names = await access.names(context.bot)
    in_config = get_settings().admins
    title = _("Admins ({count}):").format(count=len(in_config) + len(added.entries))
    lines = [
        f"{entry_text(Entry(admin), names, set())} · " + _("in the config")
        for admin in in_config
    ]
    lines += [
        f"{n} {entry_text(entry, names, set())}"
        for n, entry in enumerate(added.entries, start=1)
    ]
    lines += [
        "",
        _(
            "/admin add <who> adds one, /admin remove <n> removes one; only the "
            "admins in the config can."
        ),
    ]
    if added.broken:
        lines.append(unreadable_text(added.broken))
    return f"👑 **{escape(title)}**\n" + escape("\n".join(lines))


def find_person(
    context: DataMessageContext, account: Account, who: str
) -> Contact | str:
    """Whom /admin add means: someone the bot knows, by their number in
    /contacts, name, phone number or the start of their ID; or one by a
    phone number or Signal ID it doesn't know yet. Else why not."""
    chat_id = typed_chat_id(who)
    if chat_id and is_group(chat_id):
        name = next((g.name for g in account.groups if g.id == chat_id), chat_id)
        return _("{name} is a group: admins are people.").format(name=name)
    found = contacts.find_one(account, chat_id or who, contacts.listed_for(context))
    if not isinstance(found, str) or not chat_id:
        return found
    if re.match(SIGNAL_ID, chat_id):
        return Contact(uuid=chat_id)
    return Contact(number=chat_id)


def welcome_text(adder: str | None) -> str:
    """For someone just made an admin, in the language spoken: by whom, that
    /help lists every command, and a few to start with. Styled."""
    lines = [f"**👑 {escape(_('Welcome!'))}**"]
    if adder:
        made = _("{admin} has made you an admin of this bot.").format(admin=adder)
    else:
        made = _("You're an admin of this bot now.")
    start = _(
        "Here, in a direct chat with the bot, you may use every command: {help} "
        "lists them all, with what each takes. A few to start with:"
    ).format(help=shown_name("/help"))
    lines += [escape(made), "", escape(start)]
    lines += [
        command_line(next(line for line in EVERYDAY + ADMIN if line.name == name))
        for name in WELCOME_COMMANDS
    ]
    lines += ["", escape(_("Thank you for helping look after the bot."))]
    return "\n".join(lines)


async def welcome(
    context: DataMessageContext, account: Account, uuid: str, ids: set[str]
) -> str:
    """Send someone just made an admin, by their Signal ID, a welcome, in
    their language; what became of it."""
    message = context.message
    adder = find_by_ids(
        account.recipient_by_id, message.source_number, message.source_uuid
    )
    code = chat_language(*ids)
    with speaking(code):
        text = welcome_text(adder.real_name if adder else None)
    outcome = await send(
        context.bot, uuid, SendMessage(text=text, text_mode=TextMode.STYLED)
    )
    language = named(code)
    if outcome is Outcome.SENT:
        return _("A welcome went to them, in {language}.").format(language=language)
    if outcome.waits:
        return _("A welcome to them, in {language}, waits to be sent.").format(
            language=language
        )
    return _("The welcome to them couldn't be sent.")


def with_language(text: str) -> tuple[str, str | None]:
    """Whom /admin add names, and the language after them, by its code, if
    the text ends with one, as in Bob sv or 3 Svenska."""
    words = text.split()
    if len(words) > 1 and (code := language_named(words[-1])):
        return " ".join(words[:-1]), code
    return text, None


async def add(context: DataMessageContext, text: str) -> str:
    who, code = with_language(text)
    if not who:
        return usage()
    account = await fetch_account(context.bot)
    if isinstance(found := find_person(context, account, who), str):
        return found
    settings = get_settings()
    name = contacts.heading_of(account, found)
    ids = {each for each in (found.uuid, contacts.number_of(account, found)) if each}
    if settings.account in ids or account.is_me(found.uuid or ""):
        return _("That's the bot itself.")
    if ids & set(settings.admins):
        return _("{name} is an admin in the config already.").format(name=name)
    if not found.uuid:
        return _(
            "The bot doesn't know the Signal ID of {name} yet, by which admins "
            "are kept: once they've written to it, it does."
        ).format(name=name)
    added = admin_list.reread()
    if found.uuid in added.ids:
        return _("{name} is an admin already.").format(name=name)
    if len(added.entries) >= access.MAX_ENTRIES:
        return _("The list is full: {count} at most.").format(count=access.MAX_ENTRIES)
    entry = Entry(found.uuid, name)
    admin_list.add(entry)
    undo_with(lambda: admin_list.remove(entry.id))
    logger.info("Made someone an admin")
    logger.debug("Made %s an admin", entry.line)
    lines = [
        _("👑 {name} is an admin now, and may use every command.").format(name=name)
    ]
    if code:
        set_language(sorted(ids), code)
        lines.append(
            _("The bot speaks {language} with them from now on.").format(
                language=named(code)
            )
        )
    lines.append(await welcome(context, account, found.uuid, ids))
    return "\n".join(lines)


async def remove(context: DataMessageContext, who: str) -> str:
    if not who:
        return usage()
    names = await access.names(context.bot)
    account = await fetch_account(context.bot)
    typed = typed_chat_id(who)
    # A phone number, as the Signal ID of whoever has it, as the list keeps them
    person = find_by_ids(account.recipient_by_id, typed, None) if typed else None
    listed = person.uuid if person and person.uuid else who
    if isinstance(found := find_listed(admin_list, "/admins", listed, names), str):
        in_config = get_settings().admins
        config_names = {names.get(admin, admin).casefold() for admin in in_config}
        if typed in in_config or who.casefold() in config_names:
            return _(
                "{who} is an admin in the config, which no command changes."
            ).format(who=who)
        return found
    gone = admin_list.remove(found.id)
    undo_with(lambda: admin_list.restore(gone))
    logger.info("Took someone off the admins")
    logger.debug("Took %s off the admins", found.line)
    text = _("🗑️ {name} is no longer an admin.").format(name=name_of(found, names))
    # The allowed list keeps people by phone number, else by Signal ID
    them = find_by_ids(account.recipient_by_id, None, found.id) or Contact()
    if {found.id, them.number} & allowed_list.current().ids:
        text += "\n" + _("They're on /allowed, so may still use the everyday commands.")
    return text


async def admin_answer(context: DataMessageContext, action: str, who: str) -> str:
    """What to answer /admin, for the config's admins alone."""
    if action not in CHANGES:
        return usage()
    if not access.is_config_admin(context.message):
        return only_the_config_text()
    if action == "add":
        return await add(context, who)
    return await remove(context, who)


# Who the admins are. Timers may run /admins, which only lists, but not
# /admin, which changes who they are. An edit runs /admins again; an edit of
# /admin add or remove takes the place of what it edits, which is undone
# first.


class Admins(Handler):
    commands = (Command("/admins"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        await answer(context, lambda: list_admins(context), styled=True)


class Admin(Handler):
    commands = (Command("/admin", more=True, timers=False, subcommands=CHANGES),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        words = (context.message.text or "").split()
        action = words[1].casefold() if len(words) > 1 else ""
        who = " ".join(words[2:])
        await answer(
            context,
            lambda: admin_answer(context, action, who),
            edits=Edits.REPLACE if action in CHANGES else Edits.RUN_AGAIN,
        )
