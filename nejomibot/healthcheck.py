"""The container's health check, which the image's HEALTHCHECK runs as
nejomibot-healthcheck. It asks the running bot whether it works, and how its
latest health check went (health.py), prints the answer, and exits 0 if the
bot works, 1 if not, when restarting it could help. A bot that waits for
signal-cli-rest-api or its account works.

It asks over a Unix socket in Linux's abstract namespace, which is no file,
so nothing is written to disk. It imports nothing else of the bot's, so it
starts quickly.
"""

import socket
import sys

# The bot listens on it, in the network namespace it shares with
# signal-cli-rest-api
SOCKET = "\0nejomibot-health"
TIMEOUT = 5  # seconds: a bot this slow to answer isn't well


def ask() -> str:
    """The bot's answer. Raises OSError if there's none."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(TIMEOUT)
        connection.connect(SOCKET)
        chunks: list[bytes] = []
        while chunk := connection.recv(4096):
            chunks.append(chunk)
    return b"".join(chunks).decode()


def main() -> None:
    try:
        answer = ask()
    except OSError as e:
        print(
            f"FAILED: the bot doesn't answer ({e}). It's just starting, or it's "
            "stuck: its log may say which."
        )
        sys.exit(1)
    print(answer.rstrip("\n"))
    sys.exit(0 if answer.startswith("OK") else 1)
