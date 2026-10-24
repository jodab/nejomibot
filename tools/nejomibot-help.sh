#!/usr/bin/env bash
# nejomibot-help.sh - a short guide to the bot's container.
#
# Every interactive shell in the image shows it (tools/nejomibot-profile.sh);
# scripts and sh -c don't. From the host: podman exec nejomibot nejomibot-help.sh
#
# Usage: nejomibot-help.sh

set -euo pipefail

cat <<'EOF'
nejomibot

  signal-account.sh       Signal account: status, setup, profile (--help)
  nejomibot-timers        Timers (--help)
  nejomibot-healthcheck   Health check
  nejomibot-help.sh       This guide

  /data/config.toml       Settings (all of them: /app/config.example.toml)
  /data                   Data and backups
  /photos                 Photo library, read-only

Logs, on the host: podman logs nejomibot, or journalctl -u nejomibot
Documentation: https://github.com/jodab/nejomibot#readme
EOF
