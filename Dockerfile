# Pinned by digest, for builds that come out the same; Dependabot keeps the
# digests and versions current. uv is the building machine's own: it has no
# image for 32-bit ARM, and being statically linked it runs in any stage,
# natively, even where the rest is emulated.
FROM --platform=$BUILDPLATFORM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv

FROM docker.io/library/python:3.14-slim@sha256:0514bc76712d64f8bb48adcb95b1ab0d88c69fee95d62fe4c18ee948bee9b1e1 AS base

# tzdata lets TZ give local log timestamps; curl, jq and qrencode are for
# signal-account.sh. On 32-bit ARM, where Pillow and pillow-heif have no
# wheels, the libraries they're built against (the wheels bring their own).
# The bot's user and group are 1001 both. An interactive shell, as in podman
# exec -it nejomibot bash, starts with a short guide (tools/nejomibot-help.sh).
ARG TARGETARCH
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata curl jq qrencode \
    && if [ "$TARGETARCH" = arm ]; then \
        apt-get install -y --no-install-recommends libjpeg62-turbo libwebp7 \
            libwebpmux3 libwebpdemux2 libavif16 libheif1 libheif-plugin-libde265; \
    fi \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 1001 nejomibot \
    && useradd --system --uid 1001 --gid 1001 --no-create-home nejomibot \
    && echo 'if command -v nejomibot-help.sh >/dev/null; then nejomibot-help.sh; fi' \
        >> /etc/bash.bashrc

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/app/tools:/app/.venv/bin:$PATH \
    NEJOMIBOT_CONFIG=/data/config.toml

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
COPY nejomibot/locale/*.po locale/
RUN .venv/bin/python -c 'import pathlib, polib; \
    [polib.pofile(str(po)).save_as_mofile(str(po.with_suffix(".mo"))) \
     for po in pathlib.Path("locale").glob("*.po")]'

FROM uv-base AS build
# On 32-bit ARM, what building Pillow, pillow-heif and the smaller ones without
# wheels there takes: a compiler, the libraries' headers, and pkg-config to
# find them, left behind here
ARG TARGETARCH
RUN if [ "$TARGETARCH" = arm ]; then \
        apt-get update \
        && apt-get install -y --no-install-recommends gcc libc6-dev pkgconf \
            libjpeg62-turbo-dev zlib1g-dev libwebp-dev libavif-dev libheif-dev; \
    fi
# Dependencies first, so code changes don't reinstall them
RUN uv sync --locked --no-dev --no-install-project
COPY nejomibot/ nejomibot/
# The compiled translations, without what they're compiled from, nor the
# templates that new languages start from
COPY --from=translations /app/locale/*.mo nejomibot/locale/
RUN rm nejomibot/locale/*.po nejomibot/locale/messages.pot \
        nejomibot/locale/template.toml \
    && uv sync --locked --no-dev --no-editable


# The tests, lint and type check. tools/build-image.sh runs them first, once,
# and builds the image below only if they pass.
FROM uv-base AS test
RUN uv sync --locked --no-install-project
COPY nejomibot/ nejomibot/
COPY tests/ tests/
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
COPY config.example.toml ./
COPY tools/signal-account.sh tools/nejomibot-help.sh tools/

# The photos go in /photos, which the bot only reads, and config.toml in
# /data, where the bot keeps what it's told. By number, so a runtime can see
# it isn't root.
USER 1001:1001
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
