"""/list: a list for each chat, such as for shopping, for everyone allowed:

  /list                    the chat's list, numbered
  /list add milk, eggs     things to put on it, separated by commas or lines
  /list remove 2,5         take those off, by their numbers
  /list clear              take everything off

A chat's list has at most 100 things. The lists are kept in
data_dir/lists.txt, a line for each thing, which can be changed by hand: the
bot reads it again when it changes, and leaves comments and lines it can't
read as they are.
"""

import re
from dataclasses import dataclass

from signalbot import DataMessageContext

from .access import chat_id_of
from .commands import Command, Edits, Handler, answer, numbers_in, undo_with
from .files import KeptLines
from .i18n import _, ngettext
from .messages import chat_id, chats_of, escape

MAX_ITEMS = 100
MAX_ITEM = 200

HEADER = (
    "# nejomibot's lists, a line for each thing on them:",
    "#   chat | thing",
    "# The chat is a group ID, phone number or Signal ID. Changed with /list in",
    "# Signal, or by hand: the bot reads it again when it changes, and leaves",
    "# comments and lines it can't read as they are.",
)


@dataclass(frozen=True)
class Item:
    chat: str  # a group.… ID, phone number or Signal ID
    text: str


def parse_line(line: str) -> Item:
    """A line of the file. Raises ValueError."""
    chat, _bar, text = (field.strip() for field in line.partition("|"))
    if (where := chat_id_of(chat)) is None or not text:
        raise ValueError("no chat, or nothing on the list")
    return Item(where, text)


def line_of(item: Item) -> str:
    return f"{item.chat} | {item.text}"


kept = KeptLines("lists.txt", HEADER, parse_line, line_of)


def usage() -> str:
    return "\n".join(
        [
            _("/list add <things>: put things on the list, e.g. /list add milk, eggs"),
            _("/list remove <n>,…: take them off, by their numbers"),
            _("/list clear: take everything off"),
        ]
    )


def items(chats: set[str]) -> list[Item]:
    """The chat's list."""
    return [item for item in kept.current().entries if item.chat in chats]


def list_text(chats: set[str]) -> str:
    """The chat's list, numbered. Styled."""
    if not (found := items(chats)):
        return escape(_("📝 The list is empty.") + f"\n\n{usage()}")
    title = ngettext(
        "📝 The list: {count} thing", "📝 The list: {count} things", len(found)
    ).format(count=len(found))
    lines = [f"{n} {item.text}" for n, item in enumerate(found, start=1)]
    return f"**{escape(title)}**\n" + escape("\n".join(lines))


def add_items(chat: str, chats: set[str], text: str) -> str:
    """Put the things in the text on the list, then show it; or say why
    not. Styled."""
    things = [" ".join(part.split()) for part in re.split(r"[,;\n]", text)]
    if not (things := [thing for thing in things if thing]):
        return escape(usage())
    if any(len(thing) > MAX_ITEM for thing in things):
        return escape(
            _("A thing on the list has at most {count} characters.").format(
                count=MAX_ITEM
            )
        )
    if len(items(chats)) + len(things) > MAX_ITEMS:
        return escape(
            _("A list has at most {count} things: take some off first.").format(
                count=MAX_ITEMS
            )
        )
    change = kept.add(*(Item(chat, thing) for thing in things))
    undo_with(lambda: kept.revert(change))
    return list_text(chats)


def remove_items(chats: set[str], text: str) -> str:
    """Take the things with these numbers off the list, then show it; or say
    why not. Styled."""
    if not (numbers := numbers_in(text)):
        return escape(_("Which? Give their numbers, as /list shows."))
    found = items(chats)
    if wrong := [n for n in numbers if not 1 <= n <= len(found)]:
        return escape(_("There's no {n} on the list.").format(n=wrong[0]))
    gone = [found[n - 1] for n in numbers]
    change = kept.remove(gone)
    undo_with(lambda: kept.revert(change))
    removed = _("🗑️ Took off: {things}").format(
        things=", ".join(item.text for item in gone)
    )
    return f"{escape(removed)}\n\n{list_text(chats)}"


def clear(chats: set[str]) -> str:
    """Styled."""
    if found := items(chats):
        change = kept.remove(found)
        undo_with(lambda: kept.revert(change))
    return escape(_("🗑️ The list is empty now."))


def list_answer(context: DataMessageContext, text: str) -> str:
    """What to answer /list. Styled."""
    chats = chats_of(context)
    words = text.split(maxsplit=2)
    action = words[1].casefold() if len(words) > 1 else ""
    rest = words[2] if len(words) > 2 else ""
    if not action:
        return list_text(chats)
    if action == "add":
        return add_items(chat_id(context), chats, rest)
    if action in ("remove", "delete"):
        return remove_items(chats, rest)
    if action == "clear":
        return clear(chats)
    return escape(usage())


class Lists(Handler):
    commands = (Command("/list", more=True, timers=False),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        text = context.message.text or ""
        await answer(
            context,
            lambda: list_answer(context, text),
            # Showing it runs again; an edit of one that changes it takes
            # its place
            edits=Edits.RUN_AGAIN if len(text.split()) == 1 else Edits.REPLACE,
            styled=True,
        )
