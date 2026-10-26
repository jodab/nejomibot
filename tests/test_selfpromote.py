import base64
from importlib.resources import files
from typing import cast

import pytest
from helpers import ALICE, message_from
from signalbot import DataMessageContext, SendMessage, SignalBot, TextMode

from nejomibot.selfpromote import IMAGE, REPOSITORY, SelfPromote
from nejomibot.styles import unmarked
from nejomibot.timers import check_commands

PICTURE = files("nejomibot").joinpath("logo.png").read_bytes()


async def promoted(text: str, answers: list[SendMessage]) -> SendMessage:
    await SelfPromote().handle_data_message(
        DataMessageContext(cast(SignalBot, None), message_from(ALICE, text))
    )
    [answer] = answers
    return answer


async def test_the_bot_by_name_and_its_links(answers: list[SendMessage]) -> None:
    answer = await promoted("/selfpromote", answers)
    assert answer.text_mode == TextMode.STYLED
    text, styles = unmarked(answer.text or "")
    title = "nejomibot, a Signal bot for family and friends"
    assert text == (
        f"{title}\n\n"
        f"Source code and documentation: {REPOSITORY}\nContainer image: {IMAGE}"
    )
    assert [(s.start, s.length, s.style) for s in styles] == [(0, len(title), "BOLD")]
    # Under the picture GitHub shows for the repository
    [picture] = answer.base64_attachments or []
    header, _comma, data = picture.partition(",")
    assert header == "data:image/png;filename=nejomibot.png;base64"
    assert base64.b64decode(data) == PICTURE
    assert PICTURE.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.usefixtures("swedish")
async def test_in_swedish(answers: list[SendMessage]) -> None:
    answer = await promoted("/självreklam", answers)
    text, _styles = unmarked(answer.text or "")
    assert text.startswith("nejomibot, en Signal-bot för familj och vänner\n\n")
    assert text.endswith(f"Containeravbildning: {IMAGE}")


def test_timers_and_run_may_post_it() -> None:
    assert check_commands(["/selfpromote"]) is None
