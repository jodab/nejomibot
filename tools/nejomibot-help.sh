#!/usr/bin/env bash
# nejomibot-help.sh - a short guide to the bot's container: its commands, where
# they are, and the bot's files.
#
# Every interactive shell in the image starts with it, whichever shell it is
# (tools/nejomibot-profile.sh), so that podman exec -it nejomibot sh, or bash,
# or docker compose exec nejomibot sh, starts with it; scripts, and sh -c,
# don't show it. From the host: podman exec nejomibot nejomibot-help.sh.
#
# Usage: nejomibot-help.sh

set -euo pipefail

cat <<'EOF'
nejomibot's container: the bot runs here as its main process, unless the
container was started for another command, as with podman run --rm.

  nejomibot-healthcheck     Whether the bot works, and how its latest health
                            check went.
  nejomibot-timers          The timers, as /timers, /chats and /timer have them
                            in Signal: nejomibot-timers --help.
  signal-account.sh         The Signal account: its status, setup, profile,
                            username and more: signal-account.sh --help.
  nejomibot                 The bot itself, which runs already in the bot's own
                            container: a second one would compete with it for
                            messages. To restart the bot, restart its
                            container from the host.
  nejomibot-help.sh         This guide.

The commands are in /app/.venv/bin and /app/tools, both on the PATH.

  /data/config.toml         The settings, read as the bot starts.
  /data                     What the bot keeps: timers.txt, specials.txt,
                            allowed.txt and more, and backups/.
  /photos                   The photo library, which the bot only reads.
  /app/config.example.toml  Every setting, explained.

The bot's log is the container's: on the host, podman logs nejomibot,
journalctl -u nejomibot or docker compose logs nejomibot.
Documentation: https://github.com/jodab/nejomibot#readme
EOF
