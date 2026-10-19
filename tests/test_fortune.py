from pathlib import Path
from typing import cast

import pytest
from signalbot import DataMessage, DataMessageContext, SendMessage, SignalBot, TextMode

from nejomibot import commands, fortune
from nejomibot.config import get_settings
from nejomibot.fortune import OWN, Fortune, read_fortunes, styled


def context_of(text: str) -> DataMessageContext:
    message = DataMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=0,
        source="+46700000000",
        source_number="+46700000000",
        source_uuid="test-uuid",
        text=text,
    )
    return DataMessageContext(cast(SignalBot, None), message)


@pytest.fixture
def library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A library of one fortune, startrek, in a folder of its own."""
    (tmp_path / "startrek").write_text("A test fortune.", encoding="utf-8")
    monkeypatch.setattr(fortune, "FORTUNES_DIR", tmp_path)
    return tmp_path


async def answer_to(command: str, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    replies: list[str] = []

    async def mark_read(context: DataMessageContext) -> None:
        pass

    async def capture_reply(context: DataMessageContext, message: SendMessage) -> None:
        assert message.text is not None
        assert message.text_mode == TextMode.STYLED
        replies.append(message.text)

    monkeypatch.setattr(commands, "mark_read", mark_read)
    monkeypatch.setattr(commands, "reply", capture_reply)
    await Fortune().handle_data_message(context_of(command))
    return replies


@pytest.mark.usefixtures("library")
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("/fortune", "A test fortune."),
        ("/Fortune", "A test fortune."),
        ("/fortune list", "🔮 Fortune libraries:\nstartrek"),
        ("/fortune startrek", "A test fortune."),
        ("/fortune StarTrek", "A test fortune."),
        (
            "/fortune zippy",
            "Unknown fortune library. Use /fortune list to see the names.",
        ),
    ],
)
async def test_fortune_commands(
    monkeypatch: pytest.MonkeyPatch, command: str, expected: str
) -> None:
    assert await answer_to(command, monkeypatch) == [expected]


@pytest.mark.usefixtures("library")
@pytest.mark.parametrize("command", ["/fortunes", "fortune", "/fortune-list"])
async def test_not_a_fortune_command(
    monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    assert await answer_to(command, monkeypatch) == []


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("/fortune", "En spådom."),
        ("/fortune all", "A test fortune."),
        ("/fortune ALL", "A test fortune."),
        ("/fortune fortunes_svenska", "En spådom."),
    ],
)
async def test_default_library(
    library: Path, monkeypatch: pytest.MonkeyPatch, command: str, expected: str
) -> None:
    """fortunes_svenska by default; all of them on request, startrek's last."""
    (library / "fortunes_svenska").write_text("En spådom.", encoding="utf-8")

    def last(choices: list[str]) -> str:
        return choices[-1]

    def last_library(names: list[str], weights: list[int]) -> list[str]:
        return [names[-1]]

    monkeypatch.setattr(fortune.random, "choice", last)
    monkeypatch.setattr(fortune.random, "choices", last_library)
    assert await answer_to(command, monkeypatch) == [expected]


@pytest.mark.parametrize(
    ("command", "expected"),
    [("/fortune", "A test fortune."), ("/fortune fortunes_svenska", "En spådom.")],
)
async def test_fortune_library_is_the_default(
    library: Path, monkeypatch: pytest.MonkeyPatch, command: str, expected: str
) -> None:
    """fortune_library in place of fortunes_svenska; a library named still
    wins."""
    (library / "fortunes_svenska").write_text("En spådom.", encoding="utf-8")
    monkeypatch.setenv("NEJOMIBOT_FORTUNE_LIBRARY", "startrek")
    get_settings.cache_clear()
    assert await answer_to(command, monkeypatch) == [expected]


async def test_fortune_library_all(
    library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (library / "fortunes_svenska").write_text("En spådom.", encoding="utf-8")
    monkeypatch.setenv("NEJOMIBOT_FORTUNE_LIBRARY", "all")
    get_settings.cache_clear()
    chosen: list[list[str]] = []

    def choices(names: list[str], weights: list[int]) -> list[str]:
        chosen.append(names)
        return ["startrek"]

    monkeypatch.setattr(fortune.random, "choices", choices)
    assert await answer_to("/fortune", monkeypatch) == ["A test fortune."]
    assert chosen == [["fortunes_svenska", "startrek"]]


async def test_no_fortunes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fortune, "FORTUNES_DIR", tmp_path / "missing")
    assert await answer_to("/fortune", monkeypatch) == ["No fortunes found."]


@pytest.mark.usefixtures("library", "swedish")
async def test_in_swedish(monkeypatch: pytest.MonkeyPatch) -> None:
    assert await answer_to("/fortune list", monkeypatch) == [
        "🔮 Spådomsbibliotek:\nstartrek"
    ]


def test_read_fortunes_keeps_them_as_they_are(tmp_path: Path) -> None:
    path = tmp_path / "art"
    path.write_text(
        "\n".join(
            [
                "",
                "   /\\_/\\",  # the indent of the first line is part of the art
                "  ( o.o )",
                "",
                "%",
                "%",  # nothing between: no fortune
                "100%% sure",  # not a separator, nor anything special
                "\t\t-- Someone   ",
                "%",
                "The last, without a % after it",
            ]
        ),
        encoding="utf-8",
    )
    assert read_fortunes(path) == (
        "   /\\_/\\\n  ( o.o )",
        "100%% sure\n\t\t-- Someone",
        "The last, without a % after it",
    )


def test_read_fortunes_of_a_broken_file(tmp_path: Path) -> None:
    path = tmp_path / "broken"
    path.write_bytes(b"\xff\xfe not UTF-8")
    assert read_fortunes(path) == ()


def test_libraries_skip_dat_and_hidden_files(tmp_path: Path) -> None:
    for name in ["b", "A", "c.dat", ".hidden"]:
        (tmp_path / name).write_text("x\n%\n", encoding="utf-8")
    assert [path.name for path in fortune.fortune_libraries(tmp_path)] == ["A", "b"]


def test_every_library_that_comes_with_the_bot_can_be_read() -> None:
    found = fortune.counts(fortune.FORTUNES_DIR)
    assert found
    assert all(found.values()), [name for name, count in found.items() if not count]


def test_all_gives_each_fortune_the_same_chance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A library by its share of the fortunes, then one of its fortunes
    (tmp_path / "one").write_text("Only one.", encoding="utf-8")
    (tmp_path / "three").write_text("A\n%\nB\n%\nC", encoding="utf-8")
    monkeypatch.setattr(fortune, "FORTUNES_DIR", tmp_path)
    chosen: list[tuple[list[str], list[int]]] = []

    def choices(names: list[str], weights: list[int]) -> list[str]:
        chosen.append((names, weights))
        return ["three"]

    monkeypatch.setattr(fortune.random, "choices", choices)
    assert fortune.fortune_answer("all") in ("A", "B", "C")
    assert chosen == [(["one", "three"], [1, 3])]


@pytest.mark.parametrize(
    ("text", "library", "shown"),
    [
        # What explains a proverb of the bot's own, in italics; its source not
        (
            "Känn dig själv.\n\nStod i Delfi.\n\t\t-- Grekiskt ordspråk",
            OWN,
            "Känn dig själv.\n\n*Stod i Delfi.*\n\t\t-- Grekiskt ordspråk",
        ),
        (
            "All hjärna finns inte i ett huvud.\n\nFråga andra.",
            OWN,
            "All hjärna finns inte i ett huvud.\n\n*Fråga andra.*",
        ),
        ("Vad är svårt?\n\t\t-- Thales", OWN, "Vad är svårt?\n\t\t-- Thales"),
        ("Alla goda ting är tre.", OWN, "Alla goda ting är tre."),
        # Marks show as they are
        ("A *star*.\n\nAnd ~more~.", OWN, "A \\*star\\*.\n\n*And \\~more\\~.*"),
        # In other libraries, a paragraph is just that
        ("A *star*.\n\nAnd ~more~.", "startrek", "A \\*star\\*.\n\nAnd \\~more\\~."),
        # Italics that marks can't say: as it is
        ("Saying.\n\nEnds in a star*", OWN, "Saying.\n\nEnds in a star\\*"),
    ],
)
def test_styled(text: str, library: str, shown: str) -> None:
    assert styled(text, library) == shown


async def test_the_bots_own_in_italics(
    library: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (library / OWN).write_text("Alla är vi barn i början.\n\nAlla har varit nybörjare.")
    assert await answer_to("/fortune", monkeypatch) == [
        "Alla är vi barn i början.\n\n*Alla har varit nybörjare.*"
    ]
