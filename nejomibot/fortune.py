"""/fortune: a random fortune from the libraries in nejomibot/fortunes:
fortune_library (fortunes_svenska if not set), the one named (/fortune
startrek), or all of them (/fortune all). /fortune list names them.

fortunes_svenska is the bot's own: proverbs and quotes, some with a paragraph
under them that explains them, which shows in italics, and their source last.
"""

import asyncio
import logging
import re
from functools import cache
from pathlib import Path

from signalbot import DataMessageContext

from .commands import Command, Handler, answer, argument
from .config import get_settings
from .i18n import _
from .messages import chance, escape
from .styles import ITALIC, Styles, marked

logger = logging.getLogger(__name__)

FORTUNES_DIR = Path(__file__).parent / "fortunes"
LIST = "list"
ALL = "all"
OWN = "fortunes_svenska"
# In the bot's own library: what follows the first blank line, up to the
# source, a line of its own that starts with --
EXPLANATION = re.compile(r"\n\n(.+?)(?=\n[ \t]*--|\Z)", re.DOTALL)


def fortune_libraries(directory: Path) -> list[Path]:
    try:
        return sorted(
            (
                path
                for path in directory.iterdir()
                if path.is_file()
                and path.suffix.lower() != ".dat"
                and not path.name.startswith(".")
            ),
            key=lambda path: path.name.casefold(),
        )
    except OSError as e:
        logger.warning("Could not list fortune libraries: %r", e)
        return []


def fortune_text(lines: list[str]) -> str:
    """A fortune's lines as they are, the first one's indent too, without
    blank lines around them."""
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def read_fortunes(path: Path) -> tuple[str, ...]:
    """The fortunes in a library: the text between lines of just %."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as e:
        logger.warning("Could not read fortune library %s: %r", path, e)
        return ()

    fortunes: list[str] = []
    lines: list[str] = []
    for line in [*text.splitlines(), "%"]:
        if line != "%":
            lines.append(line)
            continue
        if fortune := fortune_text(lines):
            fortunes.append(fortune)
        lines = []
    return tuple(fortunes)


@cache
def counts(directory: Path) -> dict[str, int]:
    """How many fortunes each library has, by name. The libraries come with
    the bot, so they're counted once, which takes a moment; then let go, as
    all of them would take some megabytes. Blocking."""
    return {
        path.name: len(read_fortunes(path)) for path in fortune_libraries(directory)
    }


def pick(library: str) -> tuple[str, str]:
    """A fortune from the library, fortune_library if none, or from all of
    them, and the library it's from; or the libraries' names, or why there's
    no fortune, and no library. Blocking."""
    found = counts(FORTUNES_DIR)
    if library.casefold() == LIST:
        # A paragraph, which wraps in Signal's bubbles, rather than a long column
        return f"🔮 {_('Fortune libraries:')}\n" + " · ".join(found), ""
    if not library:
        # Every library, should the default one be missing, or all be set
        default = get_settings().fortune_library
        library = default if default in found else ALL
    if library.casefold() == ALL:
        if not any(found.values()):
            return _("No fortunes found."), ""
        # A library by its share of all the fortunes, so each is as likely
        name = chance().choices(list(found), weights=list(found.values()))[0]
    elif not (
        name := next((n for n in found if n.casefold() == library.casefold()), "")
    ):
        return _("Unknown fortune library. Use /fortune list to see the names."), ""
    if not (fortunes := read_fortunes(FORTUNES_DIR / name)):
        return _("No fortunes found."), ""
    return chance().choice(fortunes), name


def styled(text: str, library: str) -> str:
    """The text, styled: what explains a proverb of the bot's own library in
    italics, unless marks can't say that."""
    if library != OWN or not (explanation := EXPLANATION.search(text)):
        return escape(text)
    styles: Styles = [frozenset()] * len(text)
    start, end = explanation.span(1)
    styles[start:end] = [ITALIC] * (end - start)
    return marked(text, styles) or escape(text)


def fortune_answer(library: str) -> str:
    """What /fortune answers: a fortune from the library, or the libraries'
    names, or why there's no fortune. Styled. Blocking."""
    return styled(*pick(library))


class Fortune(Handler):
    commands = (Command("/fortune", more=True, subcommands=(LIST, ALL)),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        library = argument(context.message.text)
        await answer(
            context, lambda: asyncio.to_thread(fortune_answer, library), styled=True
        )
