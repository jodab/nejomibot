"""nejomibot-help, and help in the image: a short guide to the bot's
container, which every interactive shell there starts with (the image's
/etc/profile.d/nejomibot.sh). It imports nothing, so it shows at once.
"""

GUIDE = """\
nejomibot

  nejomibot-account       Signal account: status, setup, profile (--help)
  nejomibot-chat          The bot as in a direct chat; messages received (--help)
  nejomibot-timers        Timers (--help)
  nejomibot-healthcheck   Health check
  help                    This guide (also nejomibot-help)

  /data/config.toml       Settings (all of them: /app/config.example.toml)
  /data                   Data
  /photos                 Photo library, read-only

Logs, on the host: podman logs nejomibot, or journalctl -u nejomibot
Documentation: https://github.com/jodab/nejomibot#readme
"""


def main() -> None:
    print(GUIDE, end="")
