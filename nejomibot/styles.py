"""Text styles and mentions: Signal's bold, italic, strikethrough, monospace
and spoiler, and its @someone, which notifies them in a group they've muted.

The bot sends styles through signal-cli-rest-api's styled mode, which reads
marks in the text: **bold**, *italic*, ***both***, ~strikethrough~,
`monospace` and ||spoiler||, a \\ before a mark that should show as it is
(escape()). A special's text keeps the styles an admin gives it in Signal:
marked() writes them as marks, which the specials file keeps.

A message that mentions someone has a placeholder in its text where Signal's
apps show their name, and says whom it names. The bot writes a mention in
text as <@ID>, by Signal ID or phone number (mention()), as its files keep
it: what comes in has its mentions written so (written()), and what goes out
has each made a mention again (mentioned()).
"""

import re
from collections.abc import Iterable, Sequence

from signalbot import Mention, MessageMention, SendMessage, TextMode, TextStyle

from .config import PHONE_NUMBER, SIGNAL_ID

# Signal's styles and their marks, but bold and italic, which take stars
MARKS = {"STRIKETHROUGH": "~", "MONOSPACE": "`", "SPOILER": "||"}
STARRED = frozenset({"BOLD", "ITALIC"})
BOLD = frozenset({"BOLD"})
ITALIC = frozenset({"ITALIC"})
STYLES = STARRED | MARKS.keys()
STYLES_OF = {
    "*": ("ITALIC",),
    "**": ("BOLD",),
    "***": ("BOLD", "ITALIC"),
    **{mark: (style,) for style, mark in MARKS.items()},
}
# A mark, or one a \ makes text, as signal-cli-rest-api's textstyleparser.go
# reads them: stars up to three at a time
MARK = re.compile(r"\\(\*{1,3}|\|\|?|[~`])|(\*{1,3}|\|\||[~`])")

type Styles = list[frozenset[str]]  # of each character of a text

# What stands for a mention in a message's text
PLACEHOLDER = "￼"
# A mention, as the bot writes it in text
MENTION = re.compile(rf"<@({SIGNAL_ID.strip('^$')}|{PHONE_NUMBER.strip('^$')})>")


def escape(text: str) -> str:
    """Text that shows as is in a styled message."""
    return re.sub(r"([*`|~])", r"\\\1", text)


def utf16_length(text: str) -> int:
    """The text's length as Signal counts it, in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


def mention(who: str) -> str:
    """A mention of who, by Signal ID or phone number, as the bot writes it."""
    return f"<@{who}>"


def written(
    text: str, mentions: Sequence[Mention], styles: Sequence[TextStyle]
) -> tuple[str, list[TextStyle]]:
    """The text with its mentions written as mention() writes them, in place
    of what stands for them, and its styles moved with the text. Their
    places count UTF-16 code units: one that isn't between characters, or
    overlaps another, is left as it is."""
    index: dict[int, int] = {}  # of each character, by where it starts, and the end
    at = 0
    for i, char in enumerate(text):
        index[at] = i
        at += utf16_length(char)
    index[at] = len(text)
    changes: list[tuple[int, int, str]] = []  # where, from and to, and what goes there
    for each in sorted(mentions, key=lambda each: each.start):
        end = each.start + each.length
        who = (each.uuid or "").lower() or each.number  # as MENTION reads it
        clear = not changes or changes[-1][1] <= each.start
        if who and clear and {each.start, end} <= index.keys():
            changes.append((each.start, end, mention(who)))

    def moved(place: int) -> int:
        """Where a place in the text is once the mentions before it are written."""
        return place + sum(
            utf16_length(new) - (end - start)
            for start, end, new in changes
            if end <= place
        )

    parts: list[str] = []
    last = 0
    for start, end, new in changes:
        parts += [text[last : index[start]], new]
        last = index[end]
    moved_styles = [
        style.model_copy(
            update={
                "start": moved(style.start),
                "length": moved(style.start + style.length) - moved(style.start),
            }
        )
        for style in styles
    ]
    return "".join([*parts, text[last:]]), moved_styles


def mentioned(message: SendMessage) -> SendMessage:
    """The message with each mention in its text, as mention() writes it,
    made a mention, which Signal's apps show as @ and the name. A
    placeholder the text has of its own goes, as it would be taken for one."""
    if not message.text or not MENTION.search(message.text):
        return message
    whom: list[str] = []

    def placeholder(found: re.Match[str]) -> str:
        whom.append(found[1])
        return PLACEHOLDER

    text = MENTION.sub(placeholder, message.text.replace(PLACEHOLDER, ""))
    # Where they are once signal-cli-rest-api has read a styled text's marks
    shown = unmarked(text)[0] if message.text_mode == TextMode.STYLED else text
    starts: list[int] = []
    at = 0
    for char in shown:
        if char == PLACEHOLDER:
            starts.append(at)
        at += utf16_length(char)
    mentions = [
        MessageMention(author=who, start=start, length=1)
        for who, start in zip(whom, starts, strict=True)
    ]
    return message.model_copy(update={"text": text, "mentions": mentions})


def styles_of(text: str, ranges: Iterable[TextStyle] | None) -> Styles:
    """Each character's styles, from the ranges a message has, which count
    UTF-16 code units."""
    spans = [
        (r.start, r.start + r.length, r.style)
        for r in ranges or ()
        if r.style and r.style in STYLES
    ]
    found: Styles = []
    at = 0
    for char in text:
        found.append(frozenset(s for start, end, s in spans if start <= at < end))
        at += utf16_length(char)
    return found


def unmarked(text: str) -> tuple[str, list[TextStyle]]:
    """The text and its styles, as signal-cli-rest-api reads its marks: one
    closes the last one opened, if it's the same, else opens another; those
    left open are dropped."""
    plain: list[str] = []
    found: list[TextStyle] = []
    opened: list[tuple[str, int]] = []
    end = at = 0
    for mark in MARK.finditer(text):
        plain.append(text[end : mark.start()] + (mark[1] or ""))
        at += utf16_length(plain[-1])
        end = mark.end()
        if mark[1]:
            continue
        if opened and opened[-1][0] == mark[2]:
            start = opened.pop()[1]
            found += [
                TextStyle(start=start, length=at - start, style=style)
                for style in STYLES_OF[mark[2]]
            ]
        else:
            opened.append((mark[2], at))
    return "".join(plain) + text[end:], found


def marked(text: str, styles: Styles) -> str | None:
    """The text in marks for its characters' styles, the rest escaped; or
    None if marks can't say them, as where bold and italic meet inside a
    word. A space takes the bold and italic of the words on both sides if
    they agree, else none, which looks the same and keeps their stars apart."""
    wanted = list(styles)
    for space in re.finditer(r"\s+", text):
        start, end = space.span()
        before = wanted[start - 1] & STARRED if start else frozenset[str]()
        after = wanted[end] & STARRED if end < len(text) else frozenset[str]()
        for i in range(start, end):
            wanted[i] = wanted[i] - STARRED | (before if before == after else set())
    out: list[str] = []
    opened: list[str] = []  # the marks open, innermost last
    for char, here in zip([*text, ""], [*wanted, frozenset[str]()], strict=True):
        marks = [mark for style, mark in MARKS.items() if style in here]
        if stars := ("ITALIC" in here) + 2 * ("BOLD" in here):
            marks.append("*" * stars)
        kept = 0
        while kept < len(opened) and opened[kept] in marks:
            kept += 1
        new = [mark for mark in marks if mark not in opened[:kept]]
        out += [*reversed(opened[kept:]), *new, escape(char)]
        opened[kept:] = new
    result = "".join(out)
    plain, found = unmarked(result)
    return result if plain == text and styles_of(plain, found) == wanted else None


def bold(text: str) -> str:
    """The text in bold, in marks; as it is, if marks can't say that, as for
    text that ends in a *."""
    return marked(text, [BOLD] * len(text)) or escape(text)
