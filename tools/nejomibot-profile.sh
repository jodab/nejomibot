# shellcheck shell=sh
# nejomibot-profile.sh - what a shell in the bot's container starts with,
# whichever shell it is: the image has it as /etc/profile.d/nejomibot.sh, so
# a login shell reads it from /etc/profile, bash from /etc/bash.bashrc, and
# sh, which reads neither, as the file that the image's ENV names.

# A login shell's /etc/profile sets a PATH without the bot's commands
case :$PATH: in
*:/app/tools:*) ;;
*) PATH=/app/tools:/app/.venv/bin:$PATH ;;
esac

# The guide in an interactive shell, once, though a login shell reads this
# file twice
case $- in
*i*)
	if [ -z "${nejomibot_guide_shown-}" ]; then
		nejomibot_guide_shown=1
		nejomibot-help.sh
	fi
	;;
esac
