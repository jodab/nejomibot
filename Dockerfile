# Pinned by digest, for builds that come out the same; Dependabot keeps the
# digests and versions current. uv is the building machine's own: it has no
# image for 32-bit ARM, and being statically linked it runs in any stage,
# natively, even where the rest is emulated.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM docker.io/library/python:3.15-slim@sha256:533b0b2f9b5d46fd097091cf826f27902f1d6c3bca714b6dc74551356aa97a51 AS base

# tzdata lets TZ give local log timestamps. On 32-bit ARM, where Pillow and
# pillow-heif have no wheels, the libraries they're built against (the
# wheels bring their own). The bot and its tools are Python, and need no
# shell. The bot's user and group are 1000 both, unless the container is
# given others (--user; User= and Group= in a Quadlet; user: in Compose),
# which need no entry of their own here. Every interactive shell, as in
# podman exec -it nejomibot sh, or bash, starts with a short guide
# (nejomibot-help), through /etc/profile.d/nejomibot.sh, which the image gets
# below: bash reads it from /etc/bash.bashrc, and sh as $ENV.
ARG TARGETARCH
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && if [ "$TARGETARCH" = arm ]; then \
        apt-get install -y --no-install-recommends libjpeg62-turbo libwebp7 \
            libwebpmux3 libwebpdemux2 libavif16 libheif1 libheif-plugin-libde265; \
    fi \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 nejomibot \
    && useradd --uid 1000 --gid 1000 --no-create-home nejomibot \
    && echo '. /etc/profile.d/nejomibot.sh' >> /etc/bash.bashrc

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/.venv/bin:$PATH \
    NEJOMIBOT_CONFIG=/data/config.toml \
    ENV=/etc/profile.d/nejomibot.sh

WORKDIR /app


# Where uv makes the virtual environment; it stays behind, as does the code,
# which is installed into the environment
FROM base AS uv-base
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never
COPY pyproject.toml uv.lock .python-version README.md LICENSE ./
COPY LICENSES/ LICENSES/

# The translations, compiled once, here, rather than at every start: a .mo
# for each .po, by polib, from the lock; nothing else needs it
FROM uv-base AS translations
RUN uv sync --locked --only-group translations
COPY tools/compile-translations.py ./
COPY nejomibot/locale/*.po locale/
RUN .venv/bin/python compile-translations.py locale

FROM uv-base AS build
# strip, from binutils (below); on 32-bit ARM also what building Pillow,
# pillow-heif and the smaller ones without wheels there takes: a compiler, the
# libraries' headers, and pkg-config to find them. All left behind here.
ARG TARGETARCH
RUN apt-get update \
    && apt-get install -y --no-install-recommends binutils \
    && if [ "$TARGETARCH" = arm ]; then \
        apt-get install -y --no-install-recommends gcc libc6-dev pkgconf \
            libjpeg62-turbo-dev zlib1g-dev libwebp-dev libavif-dev libheif-dev; \
    fi
# Dependencies first, so code changes don't reinstall them. Their compiled
# modules and libraries are stripped as Debian strips its own (dh_strip's
# --strip-unneeded): what only a debugger reads, 10 to 14 MB of each image,
# goes. Then each must still load, as aiohttp, multidict, yarl and propcache
# would fall back to pure Python without a word if one didn't.
RUN uv sync --locked --no-dev --no-install-project \
    && find .venv -name '*.so*' -type f -exec strip --strip-unneeded {} + \
    && .venv/bin/python -c 'import ctypes, pathlib; \
        [ctypes.CDLL(str(lib)) for lib in pathlib.Path(".venv").rglob("*.so*") \
         if lib.is_file()]'
COPY nejomibot/ nejomibot/
# The compiled translations, which the wheel has in place of the .po files
# (wheel-exclude in pyproject.toml)
COPY --from=translations /app/locale/*.mo nejomibot/locale/
# The version the image is built as, which the bot reports (/status, its
# notices): pyproject.toml's from tools/build-image.sh, or a local build's,
# such as 0.99.37+g3fa91a0 (PEP 440). The lock was checked above, against
# pyproject.toml's version, so this install needn't check it again.
ARG VERSION=unknown
RUN if [ "$VERSION" != unknown ]; then uv version --frozen "$VERSION"; fi \
    && uv sync --frozen --no-dev --no-editable


# The tests, lint and type check. tools/build-image.sh runs them first, once,
# and builds the image below only if they pass.
FROM uv-base AS test
RUN uv sync --locked --no-install-project
COPY nejomibot/ nejomibot/
COPY tests/ tests/
COPY tools/compile-translations.py tools/
# The tests check README.md too, which uv-base has, as the page on Docker
# Hub and PyPI
RUN uv sync --locked \
    && ruff check \
    && ruff format --check \
    && pyright \
    && pytest -q -p no:cacheprovider


FROM base
ARG VERSION=unknown
LABEL org.opencontainers.image.title=nejomibot \
      org.opencontainers.image.description="A Signal bot for a family or a group of friends." \
      org.opencontainers.image.licenses=MIT \
      org.opencontainers.image.version=$VERSION
# Owned by root: the bot can read its code, not change it
COPY --from=build /app/.venv .venv
# Where the guide and the bot's errors say it is, as nejomibot
# --example-config prints it
COPY nejomibot/config.example.toml ./
COPY tools/nejomibot-profile.sh /etc/profile.d/nejomibot.sh
# The bytecode of the standard library's modules that the bot and its tools
# import: the base image has none, and PYTHONDONTWRITEBYTECODE keeps it from
# being written as they run, so each run compiled them anew. On a Raspberry
# Pi 4, nejomibot-timers imported in 4.7 s without it, 2.4 s with it. 5.7 MB,
# of the whole library's 22 MB. And help, as the guide is called too, where
# every PATH has it: a command of its own, as no shell's alias reaches
# podman exec nejomibot help.
RUN env -u PYTHONDONTWRITEBYTECODE python -c 'import concurrent.futures.thread, \
        readline, segno, nejomibot.account_cli, nejomibot.bot, nejomibot.chat_cli, \
        nejomibot.guide, nejomibot.healthcheck, nejomibot.timers_cli' \
    && ln -s /app/.venv/bin/nejomibot-help /usr/local/bin/help

# glibc gives each thread that allocates a memory arena of its own, up to 8
# per CPU (2 on 32-bit ARM), and each keeps what it has held. Two do for the
# bot, whose other threads are asyncio's workers (to_thread(), DNS lookups),
# and it keeps 1.5 MB less.
ENV MALLOC_ARENA_MAX=2

# The photos go in /photos, which the bot only reads, and config.toml in
# /data, where the bot keeps what it's told. By number, so a runtime can see
# it isn't root.
USER 1000:1000
CMD ["nejomibot"]

# Whether the bot works, so whether restarting it could help (see README).
# Every minute: three failures running, two to three minutes, make it
# unhealthy, and a new container is healthy after a minute, as Podman
# checks once as it starts, before the bot answers, and then not until the
# interval is up (it ignores --start-interval). Failures in the first minute
# don't count. What to do when it's unhealthy is up to the container runtime:
# Podman kills it with HealthOnFailure=kill in its Quadlet.
HEALTHCHECK --interval=60s --timeout=10s --start-period=1m --retries=3 \
    CMD ["nejomibot-healthcheck"]
