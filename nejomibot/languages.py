"""/language: which language the bot speaks in a chat, for everyone allowed.

  /language               the languages the bot has, and the one spoken here
  /language sv            Swedish here: in a direct chat, for whoever sends
                          it; in a group, for everyone in it, from an admin
  /language svenska       the same, by the language's own name
  /language default       the config's language here again
  /language 3,1 sv        for the admins, in a direct chat: for chats 3 and 1
                          of /chats, people or groups

The bot answers in the chat's language, and posts to it in it, the timers'
and /run's posts too (timers.Timekeeper.post). Each chat's own is kept in
data_dir/languages.txt (i18n.chat_languages): a group by its ID, a person
by their phone number or Signal ID, as /chats lists them.
"""

from signalbot import DataMessage, DataMessageContext

from .access import is_admin, is_group, sent_by
from .commands import Command, Edits, Handler, answer, argument, numbers_in, undo_with
from .config import get_settings
from .i18n import (
    ChatLanguage,
    _,
    chat_languages,
    every_word,
    languages,
    names_of,
    own_language,
    speaking,
    spoken,
)
from .messages import chat_id, escape
from .timers import chat_list, chats_numbered, people

DEFAULT = "default"  # after /language: the config's language


def language_named(text: str) -> str | None:
    """The code of the language the text names, by its code or its own
    name, in any case; None if it names none the bot has."""
    folded = text.casefold()
    return next(
        (
            code
            for code in languages()
            if folded in (code, names_of(code).name.casefold())
        ),
        None,
    )


def named(code: str) -> str:
    """E.g. 'Svenska (sv)'."""
    return f"{names_of(code).name} ({code})"


def is_default(text: str) -> bool:
    return text.casefold() in (word.casefold() for word in every_word(DEFAULT))


def own_ids(message: DataMessage) -> list[str]:
    """The sender's chat, as /chats lists them: by each of their phone number
    and Signal ID it has, or else as the message names them."""
    found = [person for person in people() if sent_by(message, [person])]
    return found or [message.source_number or message.source_uuid or ""]


def set_language(chats: list[str], code: str | None) -> None:
    """Give the chats the language, by its code, or with None, the config's;
    for an edit to undo. Raises OSError."""
    kept = chat_languages.current()
    old = [entry for entry in kept.entries if entry.chat in chats]
    change = kept.change(
        old, [ChatLanguage(chat, code) for chat in chats] if code else []
    )
    undo_with(lambda: kept.revert(change))


def another_language() -> str:
    """The code of a language other than the one spoken here, for an
    example."""
    return next((each for each in languages() if each != spoken()), spoken())


def usage() -> str:
    return _(
        "/language <language>: the bot speaks it here, as /language {code}; "
        "/language default: its own again."
    ).format(code=another_language())


async def listing(context: DataMessageContext) -> str:
    """The languages, the one spoken here marked; for an admin in a direct
    chat, the chats that have one of their own, too. Styled."""
    message = context.message
    here = spoken()  # this chat's, or the one a timer posts in
    lines = [f"🗣️ **{escape(_('Languages'))}**"]
    lines += [
        escape(f"{named(code)} ✓ {_('here')}" if code == here else named(code))
        for code in languages()
    ]
    lines.append(escape(usage()))
    if is_admin(message) and not message.is_group():
        own = [
            (n, chat, name, code)
            for n, (chat, name) in enumerate(await chat_list(context.bot), start=1)
            if (code := own_language(chat))
        ]
        if own:
            lines += ["", escape(_("Chats with a language of their own:"))]
            lines += [
                escape(f"{n} {'👥' if is_group(chat) else '👤'} {name}: {named(code)}")
                for n, chat, name, code in own
            ]
        lines.append(
            escape(_("/language <chats> <language>: for those chats of /chats."))
        )
    return "\n".join(lines)


def unknown(text: str) -> str:
    known = ", ".join(named(code) for code in languages())
    return _("The bot doesn't speak {text}: it speaks {languages}.").format(
        text=text, languages=known
    )


async def language_answer(context: DataMessageContext, words: list[str]) -> str:
    """What /language answers what follows it with. Styled."""
    if not words:
        return await listing(context)
    message = context.message
    wanted = words[-1]
    code = None if is_default(wanted) else language_named(wanted)
    if code is None and not is_default(wanted):
        return escape(unknown(wanted))
    if len(words) > 1:
        if (numbers := numbers_in(" ".join(words[:-1]))) is None:
            return escape(usage())
        if not is_admin(message) or message.is_group():
            return escape(
                _("Only the admins, in a direct chat, give chats of /chats a language.")
            )
        if isinstance(found := await chats_numbered(context.bot, numbers), str):
            return escape(found)
        set_language([chat for chat, _name in found], code)
        chats = ", ".join(name for _chat, name in found)
        if code is None:
            text = _("✅ The bot's own language for {chats} again: {language}.")
            return escape(
                text.format(chats=chats, language=named(get_settings().language))
            )
        return escape(
            _("✅ {language} for {chats}.").format(language=named(code), chats=chats)
        )
    if message.is_group():
        if not is_admin(message):
            return escape(_("Only an admin can change the language of a group."))
        chats = [chat_id(context)]
    else:
        chats = own_ids(message)
    set_language(chats, code)
    # Said in the language now spoken here
    with speaking(code or get_settings().language):
        if code is None:
            text = _("✅ The bot's own language here again: {language}.")
            return escape(text.format(language=named(get_settings().language)))
        return escape(_("✅ {language} here from now on.").format(language=named(code)))


class Language(Handler):
    everyday = True
    commands = (
        Command("/language"),
        # With more after it, it changes what chats get: timers mayn't
        Command("/language", more=True, timers=False, subcommands=(DEFAULT,)),
    )

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        words = argument(context.message.text).split()
        await answer(
            context,
            lambda: language_answer(context, words),
            edits=Edits.REPLACE if words else Edits.RUN_AGAIN,
            styled=True,
        )
