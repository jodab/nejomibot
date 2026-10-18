from pathlib import Path
from typing import Any, cast

import pytest
from helpers import ALICE, BOB, GROUP, ME
from signalbot import DataMessage, EditMessage, GroupInfo, SignalBot

from nejomibot import access
from nejomibot.access import HEADER, AllowedList, Entry, chat_id_of, parse, permits
from nejomibot.config import get_settings

ADMIN = "+46700000009"
# An admin who doesn't share their phone number
ADMIN_ID = "ad000000-0000-4000-8000-000000000009"
CAROL_ID = "0b7c1d2e-3f40-4a5b-8c6d-7e8f9a0b1c2d"
OTHER_GROUP = "group.b3RoZXI="


@pytest.fixture
def config(monkeypatch: pytest.MonkeyPatch) -> Path:
    """The admin in the config, and a group and Alice on the allowed list.
    Returns its file."""
    monkeypatch.setenv("NEJOMIBOT_ADMINS", f'["{ADMIN}", "{ADMIN_ID}"]')
    get_settings.cache_clear()
    path = get_settings().allowed_file
    path.write_text("\n".join([*HEADER, GROUP, ALICE, ""]))
    return path


def body(path: Path) -> list[str]:
    """The file's lines but the header the bot writes."""
    return path.read_text().splitlines()[len(HEADER) :]


@pytest.mark.parametrize(
    ("text", "chat_id"),
    [
        (ALICE, ALICE),
        (f" {GROUP} ", GROUP),
        (CAROL_ID.upper(), CAROL_ID),
        ("+4670", None),
        ("alice", None),
        ("group.", None),
        ("group.a b", None),
        (CAROL_ID[:-1], None),
    ],
)
def test_chat_id_of(text: str, chat_id: str | None) -> None:
    assert chat_id_of(text) == chat_id


def test_parse() -> None:
    assert parse(f"{ALICE}  # Alice # and more") == Entry(ALICE, "Alice # and more")
    assert parse(GROUP) == Entry(GROUP)
    assert parse("  # a comment") is None
    assert parse("") is None
    with pytest.raises(ValueError, match="isn't a phone number"):
        parse("alice  # Alice")


def test_a_note_is_one_line() -> None:
    assert Entry(ALICE, "Alice\nAnd  more").line == f"{ALICE}  # Alice And more"
    assert Entry(ALICE).line == ALICE


def test_made_empty() -> None:
    allowed = AllowedList().reread()
    assert allowed.entries == []
    assert get_settings().allowed_file.read_text().splitlines() == list(HEADER)


def test_hand_edits_are_kept(config: Path) -> None:
    config.write_text(
        "\n".join(
            [
                "# Family",
                f"{GROUP}  # the family group",
                f"{CAROL_ID.upper()}  # Carol",
                "",
                "alice",  # can't be read: kept, but no one
                f"{ALICE}  # a second time",
                f"{ALICE}",
            ]
        )
    )
    allowed = AllowedList()
    allowed.reread()
    assert allowed.entries == [
        Entry(GROUP, "the family group"),
        Entry(CAROL_ID, "Carol"),
        Entry(ALICE, "a second time"),
    ]
    assert allowed.broken == ["alice"]

    allowed.add(Entry(BOB, "Bob"))
    allowed.remove(ALICE)  # every line of hers
    assert config.read_text().splitlines() == [
        "# Family",
        f"{GROUP}  # the family group",
        f"{CAROL_ID.upper()}  # Carol",
        "",
        "alice",
        f"{BOB}  # Bob",
    ]
    assert [entry.id for entry in allowed.entries] == [GROUP, CAROL_ID, BOB]


def test_changes_by_hand_are_read_again(config: Path) -> None:
    allowed = AllowedList()
    allowed.reread()
    with config.open("a") as f:
        f.write(f"{BOB}\n")
    assert BOB in allowed.reread().ids


def test_changes_wait_for_the_next_look(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = AllowedList()
    allowed.current()
    with config.open("a") as f:
        f.write(f"{BOB}\n")
    # Looked at moments ago: not yet
    assert BOB not in allowed.current().ids
    monkeypatch.setattr(access, "REREAD", 0)
    assert BOB in allowed.current().ids


def test_a_deleted_file_is_made_again(config: Path) -> None:
    allowed = AllowedList()
    allowed.reread()
    allowed.add(Entry(BOB))
    config.unlink()
    assert allowed.reread().ids == set()
    assert config.exists()


def test_a_failed_write_changes_nothing(
    config: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    allowed = AllowedList()
    allowed.reread()
    before = config.read_text()

    def replace(self: Path, target: Any) -> Path:
        raise PermissionError("read-only")

    monkeypatch.setattr(Path, "replace", replace)
    with pytest.raises(PermissionError):
        allowed.add(Entry(BOB))
    assert allowed.ids == {GROUP, ALICE}
    assert config.read_text() == before
    assert not list(config.parent.glob("*.part"))


def test_without_a_folder_it_is_empty() -> None:
    # No data_dir: the file can't be made
    get_settings().data_dir.rmdir()
    allowed = AllowedList()
    assert allowed.reread().ids == set()
    assert allowed.reread().ids == set()  # and doesn't try again


def test_debug_mode_starts_with_the_debug_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NEJOMIBOT_DEBUG", "1")
    monkeypatch.setenv("NEJOMIBOT_DEBUG_GROUP", OTHER_GROUP)
    get_settings.cache_clear()
    allowed = AllowedList()
    allowed.start()
    assert allowed.ids == {OTHER_GROUP}
    assert get_settings().allowed_file.read_text().endswith(f"{OTHER_GROUP}\n")


class FakeGroups:
    """The bot's groups: GROUP and OTHER_GROUP, by the internal ID that
    messages from a group have."""

    def get_id(self, internal_id: str) -> str | None:
        return {"family": GROUP, "other": OTHER_GROUP}.get(internal_id)


class FakeBot:
    groups = FakeGroups()


def message(
    sender: str | None, *, uuid: str | None = None, group: str | None = None
) -> DataMessage:
    return DataMessage(
        server_delivered_timestamp=0,
        server_received_timestamp=0,
        timestamp=1,
        source_number=sender,
        source_uuid=uuid,
        group_info=GroupInfo.model_validate({"groupId": group, "revision": 1})
        if group
        else None,
        text="/ping",
    )


@pytest.mark.usefixtures("config")
@pytest.mark.parametrize(
    ("sent", "permitted"),
    [
        # Direct chats: the allowed and the admins
        (message(ALICE), True),
        (message(ADMIN), True),
        (message(BOB), False),
        (message(None, uuid=CAROL_ID), True),
        (message(None, uuid="someone-else"), False),
        (message(None, uuid=ADMIN_ID), True),
        # Groups: anyone in one on the list, admins too only there
        (message(BOB, group="family"), True),
        (message(ADMIN, group="other"), False),
        (message(ALICE, group="unknown"), False),
    ],
)
def test_permits(sent: DataMessage, permitted: bool) -> None:
    access.allowed_list.reread().add(Entry(CAROL_ID))
    assert permits(cast(SignalBot, FakeBot()), sent) is permitted


@pytest.mark.usefixtures("config")
def test_permits_edits_but_nothing_else() -> None:
    edit = EditMessage(**message(ALICE).model_dump(), target_sent_timestamp=0)
    assert permits(cast(SignalBot, FakeBot()), edit)
    assert not permits(cast(SignalBot, FakeBot()), object())


@pytest.mark.usefixtures("config")
def test_recipients() -> None:
    assert access.recipients() == sorted({GROUP, ALICE, ADMIN, ADMIN_ID})
    assert ME not in access.recipients()


def test_only_the_bot_may_read_the_file() -> None:
    # It lists phone numbers, as the config does, which is kept as private
    AllowedList().reread()
    path = get_settings().allowed_file
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)  # as tools or hands may leave it
    allowed = AllowedList()
    allowed.reread()
    allowed.add(Entry(BOB))
    assert path.stat().st_mode & 0o777 == 0o600
