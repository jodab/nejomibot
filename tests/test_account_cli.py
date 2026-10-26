import asyncio
import base64
import hashlib
import io
import sys
from pathlib import Path
from typing import Any

import pytest
import segno
from aiohttp import web
from helpers import (
    ALICE,
    ALICE_ID,
    BOB,
    BOB_ID,
    CAROL_ID,
    ME,
    ME_ID,
    SAFETY_NUMBER,
    FakeApi,
    make_jpeg,
)

from nejomibot import account_cli, files, guide
from nejomibot.account_cli import Answer, joined, qr_code

# The bot's own entry, as signal-cli-rest-api gives it
MYSELF = {
    "number": ME,
    "uuid": ME_ID,
    "username": "mybot.01",
    "profile": {
        "given_name": "Mybot",
        "lastname": "",
        "about": "Hej",
        "has_avatar": True,
    },
}
AVATAR = b"\xff\xd8\xff the current avatar"
NEW_ID = "4e440000-0000-4000-8000-000000000005"


class Tool:
    """nejomibot-account against the fake signal-cli-rest-api, as main() runs
    it, in a thread of its own, as it blocks; and what it was asked."""

    def __init__(
        self, api: FakeApi, capsys: pytest.CaptureFixture[str], data: Path
    ) -> None:
        self.api = api
        self.capsys = capsys
        self.data = data
        self.answers: list[str] = []  # typed in, in turn
        self.secrets: list[str] = []
        self.out = self.err = ""

    async def __call__(self, *argv: str) -> int:
        """Its exit code; what it said goes in out and err."""

        def run() -> int:
            sys.argv = ["nejomibot-account", *argv]
            try:
                account_cli.main()
            except SystemExit as e:
                return e.code if isinstance(e.code, int) else 0
            return 0

        code = await asyncio.to_thread(run)
        said = self.capsys.readouterr()
        self.out, self.err = said.out, said.err
        return code

    def sent(self, method: str, path: str) -> list[Any]:
        return self.api.bodies(method, path)

    def changes(self) -> list[tuple[str, str]]:
        return [(r.method, r.path) for r in self.api.requests if r.method != "GET"]

    def bot_txt(self) -> list[str]:
        path = self.data / "bot.txt"
        if not path.exists():
            return []
        return [line for line in path.read_text().splitlines() if line[:1] != "#"]


@pytest.fixture
def tool(
    signal_api: FakeApi,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Tool:
    """The tool, with the bot's account as the fake has it, its avatar
    included, and with no terminal unless a test says so."""
    signal_api.responses[f"/v1/contacts/{ME}/{ME}?all"] = MYSELF
    signal_api.responses["/v1/configuration"] = {"logging": {"Level": "info"}}
    signal_api.responses[f"/v1/configuration/{ME}/settings"] = {
        "trust_mode": "on-first-use"
    }

    async def avatar(request: web.Request) -> web.Response:
        return web.Response(body=AVATAR, content_type="image/jpeg")

    signal_api.route("GET", f"/v1/contacts/{ME}/{ME}/avatar", avatar)
    made = Tool(signal_api, capsys, tmp_path / "data")
    monkeypatch.setattr(account_cli, "interactive", lambda: False)

    def typed(prompt: str = "") -> str:
        return made.answers.pop(0)

    monkeypatch.setattr("builtins.input", typed)

    def secret(prompt: str) -> str:
        return made.secrets.pop(0)

    monkeypatch.setattr(account_cli, "getpass", secret)
    return made


@pytest.fixture
def at_terminal(tool: Tool, monkeypatch: pytest.MonkeyPatch) -> None:
    """As with a terminal: after tool, which has none."""
    monkeypatch.setattr(account_cli, "interactive", lambda: True)


def answering(api: FakeApi, method: str, path: str, *answers: tuple[int, Any]) -> None:
    """The route answers with these, in turn, the last one from then on."""
    left = list(answers)

    async def handle(request: web.Request) -> web.Response:
        status, body = left.pop(0) if len(left) > 1 else left[0]
        return web.json_response(body, status=status)

    api.route(method, path, handle)


# The account, and what it is


async def test_status(tool: Tool) -> None:
    assert await tool("status") == 0
    lines = tool.out.splitlines()
    assert lines[0].startswith("signal-cli-rest-api unset, json-rpc mode, at http://")
    assert f"Account      {ME} (signal-cli has 1)" in lines
    assert f"Signal ID    {ME_ID}" in lines
    assert "Name         Mybot" in lines
    assert "Username     @mybot.01" in lines
    assert "Avatar       yes" in lines
    assert lines[-4].startswith("#1   primary  (no name)")
    assert lines[-3].startswith("#2   linked   signal-cli")
    assert lines[-1] == "Safety numbers: 3, 1 verified, 1 untrusted"
    # It only asks
    assert tool.changes() == []


async def test_status_as_json(tool: Tool) -> None:
    assert await tool("--json") == 0
    found = account_cli.json.loads(tool.out)
    assert (found["account"], found["accounts"]) == (ME, [ME])
    assert found["me"]["username"] == "mybot.01"
    assert len(found["devices"]) == 2


async def test_the_only_account(
    tool: Tool, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("NEJOMIBOT_ACCOUNT")
    assert await tool("-v", "accounts") == 0
    assert tool.out == f"{ME}\n"
    # As signal-cli-rest-api before its numberless support listed them
    signal_api.responses["/v1/accounts"] = [ME, NEW_ID]
    assert await tool("status") == 1
    assert f"signal-cli has 2 accounts, so choose one with --account: {ME} " in tool.err


async def test_an_account_signal_cli_doesnt_have(tool: Tool) -> None:
    assert await tool("-a", ALICE, "status") == 1
    assert tool.err == (
        f"ERROR: {ALICE} isn't registered in signal-cli at {tool_url(tool)}, which "
        f"has {ME}: run setup, or register or link.\n"
    )


def tool_url(tool: Tool) -> str:
    return tool.out.split(" at ")[-1].strip() if " at " in tool.out else _url()


def _url() -> str:
    return "http://" + account_cli.os.environ["NEJOMIBOT_SIGNAL_SERVICE"]


async def test_an_account_without_a_number(tool: Tool, signal_api: FakeApi) -> None:
    signal_api.responses["/v1/accounts"] = [{"number": "", "aci": ME_ID}]
    me = {**MYSELF, "number": "", "username": ""}
    signal_api.responses[f"/v1/contacts/{ME_ID}/{ME_ID}?all"] = me
    signal_api.responses[f"/v1/devices/{ME_ID}"] = []
    signal_api.responses[f"/v1/identities/{ME_ID}"] = []
    # Its ID, in upper case and without dashes, as Signal Login shows it
    upper = ME_ID.replace("-", "").upper()
    assert await tool("-a", upper, "status") == 0
    assert f"Account      {ME_ID}, without a phone number (signal-cli has 1)" in (
        tool.out.splitlines()
    )
    assert "No username: without a phone number, nobody can find" in tool.err


async def test_about_accounts_and_log_level(tool: Tool) -> None:
    assert await tool("about") == 0
    assert tool.out.splitlines()[:3] == [
        "Version      unset (build 2)",
        "Mode         json-rpc",
        "API versions v1, v2",
    ]
    assert await tool("log-level") == 0
    assert tool.out == "Log level    info\n"
    assert await tool("log-level", "debug") == 0
    assert tool.sent("POST", "/v1/configuration") == [{"logging": {"Level": "debug"}}]
    assert await tool("log-level", "loud") == 2


async def test_trust_mode(tool: Tool) -> None:
    assert await tool("trust-mode") == 0
    assert "JSON_RPC_TRUST_NEW_IDENTITIES sets it" in tool.out
    assert await tool("trust-mode", "always") == 1
    assert "JSON_RPC_TRUST_NEW_IDENTITIES=always, and a restart" in tool.err
    assert tool.changes() == []


async def test_unreachable(tool: Tool) -> None:
    assert await tool("-u", "127.0.0.1:1", "about") == 1
    assert tool.err == (
        "ERROR: No answer from signal-cli-rest-api at http://127.0.0.1:1: "
        "Connection refused. Is it running, and there? --url says where\n"
    )


async def test_settings_from_the_config_file(
    tool: Tool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = account_cli.os.environ["NEJOMIBOT_SIGNAL_SERVICE"]
    monkeypatch.delenv("NEJOMIBOT_SIGNAL_SERVICE")
    monkeypatch.delenv("NEJOMIBOT_ACCOUNT")
    config = tmp_path / "config.toml"
    config.write_text(f'signal_service = "{service}"\naccount = "{ME}"\n')
    assert await tool("-c", str(config), "accounts") == 0
    assert tool.out == f"{ME}\n"
    config.write_text("account = \n")
    assert await tool("-c", str(config), "-u", service, "accounts") == 0
    assert tool.err.startswith(f"WARNING: Can't read the bot's config {config} (")


# The profile


async def test_profile(tool: Tool) -> None:
    assert await tool("profile") == 0
    assert tool.out.splitlines() == [
        "Name         Mybot",
        "About        Hej",
        "Avatar       yes",
        "Username     @mybot.01",
        "(signal-cli-rest-api doesn't show the emoji before About)",
    ]


async def test_new_name_keeps_the_avatar(tool: Tool) -> None:
    assert await tool("profile", "--name", "Nejomi") == 0
    [sent] = tool.sent("PUT", f"/v1/profiles/{ME}")
    assert sent == {
        "name": "Nejomi",
        "base64_avatar": base64.b64encode(AVATAR).decode(),
    }
    assert tool.out.startswith("Profile changed.\n")
    # Where the bot keeps its profile, which it sets at each start
    assert tool.bot_txt() == ["name Nejomi"]


async def test_about_may_start_with_a_dash(tool: Tool) -> None:
    assert await tool("profile", "--about", "-- the bot --") == 0
    [sent] = tool.sent("PUT", f"/v1/profiles/{ME}")
    assert (sent["name"], sent["about"]) == ("Mybot", "-- the bot --")
    assert tool.bot_txt() == ["name Mybot", "about -- the bot --"]
    assert await tool("profile", "--no-about") == 0
    assert tool.sent("PUT", f"/v1/profiles/{ME}")[-1]["about"] == ""
    assert tool.bot_txt() == ["name Mybot", "about"]


async def test_a_new_avatar(tool: Tool, tmp_path: Path) -> None:
    picture = make_jpeg(tmp_path / "logo.jpg")
    assert await tool("profile", "--avatar", str(picture)) == 0
    [sent] = tool.sent("PUT", f"/v1/profiles/{ME}")
    avatar = base64.b64decode(sent["base64_avatar"])
    assert avatar.startswith(b"\xff\xd8\xff") and avatar != picture.read_bytes()
    kept = tool.data / "bot-avatar.jpg"
    assert kept.read_bytes() == avatar
    assert tool.bot_txt() == [
        "name Mybot",
        f"avatar bot-avatar.jpg {hashlib.sha256(avatar).hexdigest()}",
    ]
    assert await tool("profile", "--no-avatar") == 0
    assert "base64_avatar" not in tool.sent("PUT", f"/v1/profiles/{ME}")[-1]
    assert not kept.exists()
    assert tool.bot_txt()[-1] == "avatar"


async def test_avatar_from_standard_input(
    tool: Tool, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = make_jpeg(tmp_path / "logo.jpg").read_bytes()
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(data)))
    assert await tool("profile", "--avatar", "-") == 0
    assert "base64_avatar" in tool.sent("PUT", f"/v1/profiles/{ME}")[0]


async def test_what_isnt_a_picture(tool: Tool, tmp_path: Path) -> None:
    (tmp_path / "notes.txt").write_text("hello")
    assert await tool("profile", "--avatar", str(tmp_path / "notes.txt")) == 1
    assert "isn't a picture the bot can read" in tool.err
    assert await tool("profile", "--avatar", str(tmp_path / "gone.jpg")) == 1
    assert "Can't read the picture" in tool.err
    assert tool.changes() == []


async def test_a_family_name_stays(tool: Tool, signal_api: FakeApi) -> None:
    family = {**MYSELF, "profile": {"given_name": "Mybot", "lastname": "Berg"}}
    signal_api.responses[f"/v1/contacts/{ME}/{ME}?all"] = family
    # Asked first, which takes a terminal
    assert await tool("profile", "--name", "Nejomi") == 1
    assert "There's no terminal to ask on: give --yes to go ahead." in tool.err
    assert await tool("--yes", "profile", "--name", "Nejomi") == 0
    assert '"Nejomi Berg"' in tool.err


@pytest.mark.parametrize(
    ("args", "error"),
    [
        (["--name", "x" * 129], "A name holds at most 128 bytes"),
        (["--about", "y" * 141], "About holds at most 140 characters"),
        (["--about", "😀" * 129], "About holds at most 512 bytes"),
        (["--name", ""], "--name needs the name (see --help)"),
        (["--about", "x", "--no-about"], "not allowed with argument"),
    ],
)
async def test_profile_refused(tool: Tool, args: list[str], error: str) -> None:
    assert await tool("profile", *args) in (1, 2)
    assert error in tool.err
    assert tool.changes() == []


async def test_dry_run(tool: Tool) -> None:
    assert await tool("profile", "--name", "Nejomi", "--dry-run") == 0
    assert tool.out.splitlines() == [
        f"Would send: PUT {_url()}/v1/profiles/%2B46700000000",
        f'With: {{"name":"Nejomi","base64_avatar":"({len(base64.b64encode(AVATAR))} '
        'characters)"}',
        "Dry run: nothing has been sent.",
    ]
    assert tool.changes() == []
    assert tool.bot_txt() == []


async def test_username(tool: Tool, signal_api: FakeApi) -> None:
    assert await tool("username") == 0
    assert tool.out == "Username     @mybot.01\n"
    answering(
        signal_api,
        "POST",
        f"/v1/accounts/{ME}/username",
        (200, {"username": "nejomi.42", "username_link": "https://signal.me/#eu/x"}),
    )
    assert await tool("username", "@nejomi") == 0
    assert tool.sent("POST", f"/v1/accounts/{ME}/username") == [{"username": "nejomi"}]
    assert tool.out.splitlines() == [
        "Username     @nejomi.42",
        "Link         https://signal.me/#eu/x (it starts a chat)",
    ]
    assert tool.bot_txt() == ["username nejomi.42"]
    assert await tool("--yes", "username", "--remove") == 0
    assert ("DELETE", f"/v1/accounts/{ME}/username") in tool.changes()
    assert tool.bot_txt() == ["username"]


async def test_username_taken(tool: Tool, signal_api: FakeApi) -> None:
    path = f"/v1/accounts/{ME}/username"
    answering(signal_api, "POST", path, (400, {"error": "invalid signal-cli response"}))
    assert await tool("username", "taken") == 1
    assert "Signal turned down taken, and signal-cli-rest-api doesn't say why" in (
        tool.err
    )
    assert await tool("username", "1abc") == 1
    assert "1abc can't be a Signal username" in tool.err
    assert tool.bot_txt() == []


@pytest.mark.usefixtures("at_terminal")
async def test_pin(tool: Tool) -> None:
    tool.secrets = ["2468", "2468"]
    assert await tool("-v", "pin") == 0
    assert tool.sent("POST", f"/v1/accounts/{ME}/pin") == [{"pin": "2468"}]
    # Never shown, nor in the shell's history
    assert "2468" not in tool.out + tool.err
    assert '{"pin":"(hidden)"}' in tool.err
    tool.secrets = ["2468", "1357"]
    assert await tool("pin") == 1
    assert "The two PINs differ" in tool.err
    assert await tool("pin", "2468") == 2
    assert "pin takes no PIN" in tool.err


async def test_privacy(tool: Tool) -> None:
    assert await tool("privacy") == 0
    assert "privacy --number-seen-by everyone|nobody" in tool.out
    assert await tool("privacy", "--number-seen-by", "nobody") == 0
    assert tool.sent("PUT", f"/v1/accounts/{ME}/settings") == [{"share_number": False}]
    assert await tool("privacy", "--findable-by-number", "maybe") == 2


# Registering and linking


async def test_register_needs_a_captcha(tool: Tool, signal_api: FakeApi) -> None:
    answering(
        signal_api,
        "POST",
        f"/v1/register/{ALICE}",
        (400, {"error": "Captcha required for verification"}),
    )
    assert await tool("-a", ALICE, "register") == 1
    assert "solve it at https://signalcaptchas.org/registration/generate.html" in (
        tool.err
    )
    assert await tool("-a", ALICE, "register", "--captcha", "signalcaptcha://x") == 1
    assert tool.sent("POST", f"/v1/register/{ALICE}")[-1] == {
        "use_voice": False,
        "captcha": "signalcaptcha://x",
    }


async def test_register_has_signal_call(
    tool: Tool, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(account_cli, "SMS_WAIT", 0)
    answering(
        signal_api,
        "POST",
        f"/v1/register/{ALICE}",
        (400, {"error": "Couldn't use SMS verification"}),
        (201, None),
    )
    assert await tool("--yes", "-a", ALICE, "register") == 0
    assert [
        sent["use_voice"] for sent in tool.sent("POST", f"/v1/register/{ALICE}")
    ] == [
        False,
        True,
    ]
    assert f"Signal is calling {ALICE} with the code." in tool.out
    assert "Then: nejomibot-account verify CODE" in tool.out


async def test_verify(tool: Tool, signal_api: FakeApi) -> None:
    assert await tool("-a", ALICE, "verify", "123-456") == 0
    assert tool.sent("POST", f"/v1/register/{ALICE}/verify/123456") == [{}]
    assert await tool("-a", ALICE, "verify", "12345") == 1
    assert "A Signal code has 6 digits" in tool.err
    path = f"/v1/register/{ALICE}/verify/654321"
    answering(
        signal_api, "POST", path, (400, {"error": "Account is locked with a pin"})
    )
    assert await tool("-a", ALICE, "verify", "654321") == 1
    assert "run verify again, with --pin" in tool.err


@pytest.mark.usefixtures("at_terminal")
async def test_verify_with_the_pin(tool: Tool, signal_api: FakeApi) -> None:
    path = f"/v1/register/{ALICE}/verify/654321"
    answering(
        signal_api,
        "POST",
        path,
        (400, {"error": "Account is locked with a pin"}),
        (201, None),
    )
    tool.secrets = ["2468"]
    assert await tool("-a", ALICE, "verify", "654321") == 0
    assert tool.sent("POST", path) == [{}, {"pin": "2468"}]
    assert f"{ALICE} is registered." in tool.out


async def test_link(
    tool: Tool, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(account_cli, "LINK_POLL", 0)
    link = "sgnl://linkdevice?uuid=abc&pub_key=xyz"
    answering(signal_api, "GET", "/v1/qrcodelink/raw", (200, {"device_link_uri": link}))
    answering(
        signal_api,
        "GET",
        "/v1/accounts",
        (200, [{"number": ME, "aci": ME_ID}]),
        (200, [{"number": ME, "aci": ME_ID}]),
        (200, [{"number": ME, "aci": ME_ID}, {"number": BOB, "aci": BOB_ID}]),
    )
    assert await tool("link", "Bot laptop") == 0
    [asked] = [r for r in signal_api.requests if r.path == "/v1/qrcodelink/raw"]
    assert asked.query == {"device_name": "Bot laptop"}
    assert f'Linked: signal-cli has {BOB} now, as the device "Bot laptop".' in tool.out
    assert "\x1b[" in tool.out  # the QR code


def test_the_qr_code_is_the_link() -> None:
    """Read back, the terminal's blocks are the QR code's modules, black on
    white: two rows a line, the upper in the block's color."""
    link = "sgnl://linkdevice?uuid=abc&pub_key=xyz"
    drawn = qr_code(link).splitlines()
    rows: list[list[bool]] = []
    for line in drawn:
        cells = line.removesuffix("\x1b[0m").split("▀")[:-1]
        upper = [cell.endswith(("[30;40m", "[30;107m")) for cell in cells]
        lower = [cell.endswith(("[30;40m", "[97;40m")) for cell in cells]
        rows += [upper, lower]
    expected = [
        [bool(cell) for cell in row]
        for row in segno.make_qr(link).matrix_iter(border=4)
    ]
    assert rows[: len(expected)] == expected
    # With the quiet zone, white, all round
    assert not any(rows[0]) and not any(row[0] for row in rows)


# Devices, safety numbers, and more


async def test_devices(tool: Tool) -> None:
    assert await tool("devices") == 0
    assert tool.out.splitlines()[0].startswith("#1   primary  (no name)")
    assert await tool("devices", "add", "https://example.com") == 1
    assert "That isn't a device link" in tool.err
    assert await tool("devices", "add", "sgnl://linkdevice?uuid=a&pub_key=b") == 0
    assert tool.sent("POST", f"/v1/devices/{ME}") == [
        {"uri": "sgnl://linkdevice?uuid=a&pub_key=b"}
    ]
    assert await tool("devices", "remove", "1") == 1
    assert "Device 1 is the primary device" in tool.err
    assert await tool("devices", "remove", "7") == 1
    assert "There's no device 7" in tool.err
    assert await tool("devices", "remove", "two") == 2
    assert await tool("--yes", "devices", "remove", "2") == 0
    assert ("DELETE", f"/v1/devices/{ME}/2") in tool.changes()
    assert await tool("devices", "sync") == 0
    assert ("POST", f"/v1/contacts/{ME}/sync") in tool.changes()


async def test_identities(tool: Tool) -> None:
    assert await tool("identities") == 0
    groups = [SAFETY_NUMBER[i : i + 5] for i in range(0, 60, 5)]
    assert tool.out.split("\n\n")[0].splitlines() == [
        f"Alice, {ALICE}, {ALICE_ID}",
        "  verified",
        "  " + " ".join(groups[:4]),
        "  " + " ".join(groups[4:8]),
        "  " + " ".join(groups[8:]),
    ]
    assert f"Bob Berg, {BOB}, {BOB_ID}\n  UNTRUSTED: changed, and not trusted yet" in (
        tool.out
    )
    assert f"{CAROL_ID}\n  trusted, not verified" in tool.out


async def test_trust(tool: Tool) -> None:
    assert await tool("trust", BOB, SAFETY_NUMBER[:30], SAFETY_NUMBER[30:]) == 0
    path = f"/v1/identities/{ME}/trust/{BOB}"
    assert tool.sent("PUT", path) == [{"verified_safety_number": SAFETY_NUMBER}]
    assert await tool("trust", BOB, "123") == 1
    assert "A safety number has 60 digits, and that's 3." in tool.err
    assert await tool("trust", BOB) == 2
    assert await tool("--yes", "trust", BOB, "--unverified") == 0
    assert tool.sent("PUT", path)[-1] == {"trust_all_known_keys": True}


async def test_search(tool: Tool, signal_api: FakeApi) -> None:
    asked: list[list[str]] = []

    async def search(request: web.Request) -> web.Response:
        asked.append(request.query.getall("numbers"))
        found = [
            {"number": ALICE, "registered": True},
            {"number": BOB, "registered": False},
        ]
        return web.json_response(found)

    signal_api.route("GET", f"/v1/search/{ME}", search)
    assert await tool("search", ALICE, BOB) == 0
    assert tool.out == f"{ALICE}  on Signal\n{BOB}  not on Signal\n"
    assert asked == [[ALICE, BOB]]
    assert await tool("search", "0701234567") == 1
    assert "Not a phone number in international format: 0701234567" in tool.err


@pytest.mark.usefixtures("at_terminal")
async def test_rate_limit(
    tool: Tool, signal_api: FakeApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened_pages: list[str] = []

    def _open_page(url: str) -> None:
        opened_pages.append(url)

    monkeypatch.setattr(account_cli, "open_page", _open_page)
    answering(signal_api, "POST", "/v2/send", (429, {"challenge_tokens": ["t0k3n"]}))
    tool.answers = ["not it", "signalcaptcha://solved"]
    assert await tool("rate-limit", "--to", ALICE) == 0
    path = f"/v1/accounts/{ME}/rate-limit-challenge"
    assert tool.sent("POST", path) == [
        {"challenge_token": "t0k3n", "captcha": "signalcaptcha://solved"}
    ]
    assert opened_pages == [account_cli.CHALLENGE_CAPTCHA]
    assert "That isn't it: the link starts with signalcaptcha://" in tool.out
    assert "Rate limit lifted" in tool.out


async def test_not_rate_limited(tool: Tool) -> None:
    assert await tool("rate-limit", "--to", ALICE) == 0
    assert "so the account isn't rate-limited" in tool.out
    assert await tool("rate-limit") == 2
    assert await tool("rate-limit", "t0k3n", "--to", ALICE) == 2


@pytest.mark.usefixtures("at_terminal")
async def test_unregister_wants_the_account_typed(tool: Tool) -> None:
    tool.answers = ["yes"]
    assert await tool("unregister") == 1
    assert "Nothing has been changed." in tool.err
    tool.answers = [ME]
    assert await tool("unregister", "--delete-local-data") == 0
    assert tool.sent("POST", f"/v1/unregister/{ME}") == [
        {"delete_account": False, "delete_local_data": True}
    ]


async def test_delete_local_data(tool: Tool) -> None:
    assert await tool("delete-local-data") == 1
    assert "There's no terminal to ask on" in tool.err
    assert await tool("--yes", "-a", ALICE, "delete-local-data") == 0
    assert tool.sent("DELETE", f"/v1/devices/{ALICE}/local-data") == [
        {"ignore_registered": False}
    ]


async def test_failures_say_what_signal_cli_rest_api_said(
    tool: Tool, signal_api: FakeApi
) -> None:
    answering(signal_api, "POST", f"/v1/contacts/{ME}/sync", (500, {"error": "boom"}))
    assert await tool("devices", "sync") == 1
    assert tool.err == "ERROR: Signal didn't take the contacts: boom (HTTP 500)\n"


@pytest.mark.parametrize(
    ("argv", "error"),
    [
        (["frobnicate"], "invalid choice: 'frobnicate'"),
        (["profile", "--about"], "argument --about: expected one argument"),
        (["devices", "add"], "devices add needs the device's link"),
        (["devices", "list", "now"], "devices list takes no more arguments"),
        (["username", "x", "--remove"], "Give a username, or --remove, not both"),
    ],
)
async def test_wrong_commands(tool: Tool, argv: list[str], error: str) -> None:
    assert await tool(*argv) == 2
    assert tool.err.startswith("ERROR: ") and error in tool.err
    assert tool.err.endswith(" (see --help)\n")


@pytest.mark.parametrize("argv", [["--help"], ["help"], ["status", "-h"]])
async def test_help(tool: Tool, argv: list[str]) -> None:
    assert await tool(*argv) == 0
    assert tool.out.startswith("nejomibot-account: set up and look after")
    assert tool.api.requests == []


def test_options_take_values_that_start_with_a_dash() -> None:
    assert joined(["profile", "--about", "-x", "-a", ME, "--", "--name", "y"]) == [
        "profile",
        "--about=-x",
        f"--account={ME}",
        "--",
        "--name",
        "y",
    ]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (b'{"error": "Invalid captcha given"}', "Invalid captcha given"),
        (b"Internal Server Error\n", "Internal Server Error"),
        (b"", "no reason given"),
    ],
)
def test_the_errors_answers_give(body: bytes, error: str) -> None:
    assert Answer(500, body).error() == error


def test_root_keeps_files_the_bots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Written as root, as with podman exec --user 0, a file stays its
    owner's, or a new one its folder's, so the bot can read it still."""
    owned: list[tuple[int, int]] = []

    def fchown(fd: int, uid: int, gid: int) -> None:
        owned.append((uid, gid))

    monkeypatch.setattr(files.os, "geteuid", lambda: 0)
    monkeypatch.setattr(files.os, "fchown", fchown)
    path = tmp_path / "bot.txt"
    files.write_privately(path, "new\n")
    path.write_text("old\n")
    files.write_privately(path, "newer\n")
    folder, file = tmp_path.stat(), path.stat()
    assert owned == [(folder.st_uid, folder.st_gid), (file.st_uid, file.st_gid)]
    assert path.read_text() == "newer\n"


def test_guide(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The image's, where its example config is, and another elsewhere
    example = tmp_path / "config.example.toml"
    monkeypatch.setattr(guide, "EXAMPLE", example)
    guide.main()
    assert capsys.readouterr().out == guide.ELSEWHERE
    example.touch()
    guide.main()
    assert capsys.readouterr().out == guide.IN_IMAGE
    for shown in (guide.IN_IMAGE, guide.ELSEWHERE):
        # Commands only, none of them a script
        assert ".sh" not in shown
        assert "nejomibot-account" in shown
