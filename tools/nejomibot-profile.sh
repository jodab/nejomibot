# shellcheck shell=sh
# nejomibot-profile.sh - what an interactive shell in the bot's container
# starts with, whichever shell it is: the image has it as
# /etc/profile.d/nejomibot.sh, so a login shell reads it from /etc/profile,
# bash from /etc/bash.bashrc, and sh, which reads neither, as the file that
# the image's ENV names. Plain sh: the bot's commands are Python's, and none
# of them needs a shell, this file's only for one opened by hand.

# A login shell's /etc/profile sets a PATH without the bot's commands
case :$PATH: in
*:/app/.venv/bin:*) ;;
*) PATH=/app/.venv/bin:$PATH ;;
esac

case $- in
*i*)
  # help is the guide, as in podman exec nejomibot help, where bash's own
  # help would hide the image's
  alias help=nejomibot-help
  # The guide, once, though a login shell reads this file twice
  if [ -z "${nejomibot_guide_shown-}" ]; then
    nejomibot_guide_shown=1
    nejomibot-help
  fi
  ;;
esac
