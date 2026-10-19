"""Text styles: Signal's bold, italic, strikethrough, monospace and spoiler.

The bot sends them through signal-cli-rest-api's styled mode, which reads
marks in the text: **bold**, *italic*, ***both***, ~strikethrough~,
`monospace` and ||spoiler||, a \\ before a mark that should show as it is
(messages.escape()). A special's text keeps the styles an admin gives it in
Signal: marked() writes them as marks, which the specials file keeps.
"""

import re
from collections.abc import Iterable

from signalbot import TextStyle

from .messages import escape

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


def utf16_length(text: str) -> int:
    """The text's length as Signal counts it, in UTF-16 code units."""
    return len(text.encode("utf-16-le")) // 2


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
