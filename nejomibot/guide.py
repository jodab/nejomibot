"""nejomibot-help, and help in the image: a short guide to the bot's tools,
which every interactive shell in the image starts with (its
/etc/profile.d/nejomibot.sh), and where the image keeps what they use.
Installed elsewhere, as from PyPI, it says where the settings are instead.
It imports only pathlib, so it shows at once.
"""

from pathlib import Path

# What only the image has, and its guide names
EXAMPLE = Path("/app/config.example.toml")

TOOLS = """\
  nejomibot-account       Signal account: status, setup, profile (--help)
  nejomibot-chat          The bot as in a direct chat; messages received (--help)
  nejomibot-timers        Timers (--help)
  nejomibot-healthcheck   Health check
"""
DOCUMENTATION = "Documentation: https://github.com/jodab/nejomibot#readme\n"

IN_IMAGE = f"""\
nejomibot

{TOOLS}\
  help                    This guide (also nejomibot-help)

  /data/config.toml       Settings (all of them: {EXAMPLE})
  /data                   Data
  /photos                 Photo library, read-only

Logs, on the host: podman logs nejomibot, or journalctl -u nejomibot
{DOCUMENTATION}"""

ELSEWHERE = f"""\
nejomibot

  nejomibot               The bot
{TOOLS}\
  nejomibot-help          This guide

  ./config.toml           Settings, unless NEJOMIBOT_CONFIG names another file

All the settings: nejomibot --example-config
{DOCUMENTATION}"""


def main() -> None:
    print(IN_IMAGE if EXAMPLE.is_file() else ELSEWHERE, end="")
