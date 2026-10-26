import pytest
from helpers import text_styles
from signalbot import TextStyle

from nejomibot.styles import marked, styles_of, typed, unmarked, utf16_length


def as_strings(found: list[TextStyle]) -> list[str]:
    """As signal-cli-rest-api's tests write them."""
    return [f"{s.start}:{s.length}:{s.style}" for s in found]


def test_utf16_length() -> None:
    assert utf16_length("ab") == 2
    assert utf16_length("👋🏾") == 4  # each a surrogate pair
    assert utf16_length("🗑️") == 3  # and a variation selector


def test_styles_of_each_character() -> None:
    text = "👋 Hi there"
    given = text_styles(text, ("Hi", "BOLD"), ("there", "ITALIC"))
    # A style the bot doesn't know is left out
    found = styles_of(text, [*given, TextStyle(start=0, length=2, style="NONE")])
    assert found == [
        frozenset(),
        frozenset(),
        frozenset({"BOLD"}),
        frozenset({"BOLD"}),
        frozenset(),
        *[frozenset({"ITALIC"})] * 5,
    ]
    assert styles_of("ab", None) == [frozenset(), frozenset()]


# signal-cli-rest-api's own tests (src/utils/textstyleparser_test.go), and
# how it reads marks that don't close, or that a \ makes text
@pytest.mark.parametrize(
    ("text", "plain", "found"),
    [
        ("*italic*", "italic", ["0:6:ITALIC"]),
        ("**bold**", "bold", ["0:4:BOLD"]),
        (
            "This is a **bold** and *italic* message",
            "This is a bold and italic message",
            ["10:4:BOLD", "19:6:ITALIC"],
        ),
        (
            "This is a ~strikethrough~ and a **bold** message",
            "This is a strikethrough and a bold message",
            ["10:13:STRIKETHROUGH", "30:4:BOLD"],
        ),
        ("This is a `monospace`", "This is a monospace", ["10:9:MONOSPACE"]),
        ("👋🏾**abcdefg**", "👋🏾abcdefg", ["4:7:BOLD"]),
        ("Test 👦🏿 via **signal** API", "Test 👦🏿 via signal API", ["14:6:BOLD"]),
        (
            "||this is a spoiler|| and another ||spoiler||",
            "this is a spoiler and another spoiler",
            ["0:17:SPOILER", "30:7:SPOILER"],
        ),
        (
            "||**this is a bold text inside a spoiler**||",
            "this is a bold text inside a spoiler",
            ["0:36:BOLD", "0:36:SPOILER"],
        ),
        ("\\*escaped text\\*", "*escaped text*", []),
        ("\\**escaped text\\**", "**escaped text**", []),
        ("\\`escaped text\\`", "`escaped text`", []),
        ("Test \\** \\* \\~ Escape", "Test ** * ~ Escape", []),
        ("***Bold Italic Text***", "Bold Italic Text", ["0:16:BOLD", "0:16:ITALIC"]),
        # A mark left open is dropped; a lone | and a \ before other text stay
        ("5 * 3", "5  3", []),
        ("a|b \\|| C:\\x", "a|b || C:\\x", []),
        # Stars go three at a time: these two never close
        ("*a **b***", "a b", []),
    ],
)
def test_unmarked_as_signal_cli_rest_api_reads(
    text: str, plain: str, found: list[str]
) -> None:
    result, styles = unmarked(text)
    assert (result, as_strings(styles)) == (plain, found)


@pytest.mark.parametrize(
    ("text", "styled", "marks"),
    [
        ("Good morning!", [("Good morning!", "BOLD")], "**Good morning!**"),
        ("Plain * ~ ` | \\ text", [], "Plain \\* \\~ \\` \\| \\ text"),
        (
            "Both at once",
            [("Both at once", "BOLD"), ("Both at once", "ITALIC")],
            "***Both at once***",
        ),
        # A space between bold and italic takes neither, so their stars are
        # apart; spaces between words of one style keep it
        (
            "All of this is important",
            [("All of this is important", "ITALIC"), ("important", "BOLD")],
            "*All of this is* ***important***",
        ),
        (
            "bold, then italic",
            [("bold,", "BOLD"), ("italic", "ITALIC")],
            "**bold,** then *italic*",
        ),
        # Others nest
        ("a b c", [("a b c", "STRIKETHROUGH"), ("b", "BOLD")], "~a **b** c~"),
        (
            "🗑️ Bins *now*",
            [("Bins", "MONOSPACE"), ("*now*", "SPOILER")],
            "🗑️ `Bins` ||\\*now\\*||",
        ),
        ("C:\\temp", [("C:\\temp", "BOLD")], "**C:\\temp**"),
    ],
)
def test_marked(text: str, styled: list[tuple[str, str]], marks: str) -> None:
    styles = styles_of(text, text_styles(text, *styled))
    assert marked(text, styles) == marks
    # As signal-cli-rest-api reads them: the text, and what's not space
    # styled as it was
    plain, found = unmarked(marks)
    assert plain == text
    visible = [i for i, char in enumerate(text) if not char.isspace()]
    assert [styles_of(plain, found)[i] for i in visible] == [styles[i] for i in visible]


@pytest.mark.parametrize(
    ("text", "styled"),
    [
        # Inside a word, bold and italic can't meet: **ab***cd* reads otherwise
        ("abcd", [("ab", "BOLD"), ("cd", "ITALIC")]),
        ("abcd", [("abcd", "ITALIC"), ("cd", "BOLD")]),
        # Nor can a style start or end right by a \ or *
        ("5*", [("5*", "BOLD")]),
        ("C:\\", [("C:\\", "BOLD")]),
        ("*a", [("a", "ITALIC")]),
    ],
)
def test_marks_can_t_say(text: str, styled: list[tuple[str, str]]) -> None:
    assert marked(text, styles_of(text, text_styles(text, *styled))) is None


@pytest.mark.parametrize(
    ("text", "plain", "found"),
    [
        (
            "Dinner at **six**, bring *cake*",
            "Dinner at six, bring cake",
            ["10:3:BOLD", "21:4:ITALIC"],
        ),
        ("(**note**)!", "(note)!", ["1:4:BOLD"]),
        (
            "~old~ `/photo` ||yes||",
            "old /photo yes",
            ["0:3:STRIKETHROUGH", "4:6:MONOSPACE", "11:3:SPOILER"],
        ),
        ("***both***", "both", ["0:4:BOLD", "0:4:ITALIC"]),
        # Stars close the innermost first, and split a run to do it
        ("**bold *and italic***", "bold and italic", ["5:10:ITALIC", "0:15:BOLD"]),
        ("***bold** italic*", "bold italic", ["0:4:BOLD", "0:11:ITALIC"]),
        ("***x*", "**x", ["2:1:ITALIC"]),
        # Where a pair closes, what opened inside it stays as it is
        ("**a ~b** c~", "a ~b c~", ["0:4:BOLD"]),
        # In UTF-16 code units, as Signal counts them
        ("😀 **x**", "😀 x", ["3:1:BOLD"]),
        # Marks that don't open at a word's start and close at a word's end
        # stay as they are, as do those with a \ before them
        ("Buy 2*3 screws", "Buy 2*3 screws", []),
        ("2*3*4", "2*3*4", []),
        ("Back in ~5 to ~10 min", "Back in ~5 to ~10 min", []),
        ("a || b", "a || b", []),
        ("un**believ**able", "un**believ**able", []),
        ("****", "****", []),
        ("\\*WAKE UP\\*", "*WAKE UP*", []),
        ("C:\\Users\\x", "C:\\Users\\x", []),
    ],
)
def test_typed(text: str, plain: str, found: list[str]) -> None:
    result, styles = typed(text)
    assert (result, as_strings(styles)) == (plain, found)
