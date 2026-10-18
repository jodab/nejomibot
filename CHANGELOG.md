# Changelog

What changed from one version of nejomibot to the next, newest first, and
what to do when updating. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 0.95.0 - 2026-10-18

### Updating

- The texts in `data_dir/specials.txt` are in signal-cli-rest-api's marks
  now, for their formatting: a `*`, `~` or `` ` `` typed in a special before
  this version formats it, or goes missing. Put a `\` before each in the
  file, or add the special again with `/special add`.

### Added

- The specials of your own keep the formatting you give their text in
  Signal: bold, italic, strikethrough, monospace and spoiler. The file keeps
  it as marks, `**bold**` and so on, which can be written by hand too. The
  bot turns down the few mixes signal-cli-rest-api can't send, such as bold
  and italic that meet inside a word, and says so.

### Changed

- "Photo of the day!", the daily post's caption, and "Proverb or quote of
  the day:", the daily quote's heading, are in bold.

## 0.94.1 - 2026-10-18

### Fixed

- 0.94.0's images were all built for amd64, and labelled amd64, arm64 and
  arm/v7, each with arm/v7's variant: Podman and Docker on amd64 find no
  image for themselves, and on ARM they'd get one that can't run. The
  release built them with Podman 4.9, which mixes platforms up when a stage
  names its own, as the Dockerfile's uv stage does. Releases build with
  Podman 5 now, and `tools/build-image.sh` runs each image before it pushes
  any, and stops unless each runs as its platform. If you pulled 0.94.0,
  or `latest` while it was 0.94.0, pull this version.

## 0.94.0 - 2026-10-18

### Added

- The image is built for linux/arm/v7 too, as signal-cli-rest-api is, so the
  bot runs on 32-bit ARM, such as older Raspberry Pis. Pillow and pillow-heif
  have no wheels there, so that image builds them against Debian's libraries,
  which makes the release's build longer; CI still builds linux/amd64 alone.
- The pings to `healthcheck_url` say what runs, as `/status` does, below how
  each check went: the versions of nejomibot, signalbot, Python and
  signal-cli-rest-api, how long the bot, and so its container, has been up,
  and the bot's memory, with its peak and the container's limit. They go as
  `text/plain; charset=utf-8`. signal-cli's version isn't known:
  signal-cli-rest-api doesn't say it.
- A setup guide, step by step, from nothing to the daily post: the README's
  Getting started, and [DOCKERHUB.md](DOCKERHUB.md), the same for the
  image's page on Docker Hub, which each release now puts there, with the
  repository's description.
- Each image a release pushes, to ghcr.io and Docker Hub, has signed build
  provenance: which workflow built it, from which commit.
  `gh attestation verify oci://docker.io/jodab/nejomibot:VERSION --repo jodab/nejomibot`
  checks it.

### Changed

- The examples in `deploy/` run the published image,
  `docker.io/jodab/nejomibot:latest`, instead of `localhost/nejomibot:latest`
  built on the machine. To run your own build, set `Image=` in
  `nejomibot.container`, or `image:` in `compose.yaml`, back to
  `localhost/nejomibot:latest`.
- The bot doesn't start unless it can write in `data_dir`, and says why:
  before, it ran without saving what it was told. If it stops with `Can't
  write in data_dir`, give the folder to the bot's user, uid 1001 (step 3 of
  Getting started).

### Fixed

- A config file the bot can't read stops it with `Can't read the config
  file`, and why, such as a folder it can't open. It said the file wasn't
  there, and went on without it, so settings in the file seemed missing.

## 0.93.5 - 2026-10-18

### Added

- `tools/release.sh patch|minor|major` makes a release: it moves the
  version up, dates the changelog, commits, tags and pushes that, and
  publishes the release on GitHub, which builds and pushes the image. It
  releases only what CI has passed on, and can be run again after a
  failure.

## 0.93.4 - 2026-10-18

### Added

- The release publishes the image to Docker Hub too, as
  `docker.io/USER/nejomibot`, when the repository has the variable
  `DOCKERHUB_USERNAME` and the secret `DOCKERHUB_TOKEN`.
  `tools/build-image.sh` takes `--push` more than once, building once for
  every registry.

## 0.93.2 - 2026-10-18

### Added

- `LICENSES/fortune-mod.txt`: fortune-mod's license, which the fortune
  libraries from it come under.

### Fixed

- The README, the Dockerfile and `deploy/signal.container` said the
  containers' health checks run every 20 seconds; they run every minute.

## 0.93.1 - 2026-10-18

### Changed

- CI builds the image for linux/amd64 alone; the release still builds both.
  `tools/build-image.sh --platforms LIST` chooses what it builds.

## 0.93.0 - 2026-10-18

### Updating

- `tools/timers.sh` is gone: `nejomibot-timers`, in the image, does what it
  did, through the bot's own code: `podman exec nejomibot nejomibot-timers`,
  `... chats`, `... add "08:00" 1,2 /dailypost`, `... remove 3`.
- The image's group is 1001, as its user is (it was 999). With Podman's `:U`,
  or `UserNS=keep-id:uid=1001,gid=1001`, there's nothing to do.
- The deploy examples now drop every capability, forbid new privileges, run
  read-only and with an init process, and pin signal-cli-rest-api's CI build
  by digest: copy those lines to Quadlets or Compose files made from them.
- The log looks different: each line has the date, the level and the part of
  the bot, and says which command and what kind of chat, not who or what
  else; `log_level = "DEBUG"` shows the rest.
- New settings, all optional: `log_level`, `photos_map` and `photos_heif`
  (see config.example.toml).
- The bot no longer answers the plain words `weather`, `info`, `väder` and
  `vader`: to keep one, add it to the config's aliases, such as
  `"/weather" = ["weather"]`.

### Added

- `/dailyquote`, the daily quote, as `/dailypost` is the daily post: a proverb
  or quote from `fortunes_svenska`, headed "Proverb or quote of the day:"
  (`/dagenscitat` in Swedish).
- Specials of the admins' own: commands that post text and what other
  commands answer, always in the same order, such as `/special add /morning
  Good morning! /weather; /dailyquote`, for timers, `/run` and the admins.
  `/specials` lists them; they're kept in `data_dir/specials.txt`.
- Messages waiting to be sent outlast a restart: one that has waited half a
  minute is kept in `data_dir/outbox`, and all of them as the bot stops.
- `/msg` and `/run` say where a message only waits to be sent, or may not
  have arrived.
- `photos_map = "openstreetmap"`: captions link to OpenStreetMap, with its
  short links.
- `photos_heif = false` leaves HEIC/HEIF photos out, which saves about 3 MB of
  memory.
- `log_level`, for how much the bot logs.
- `nejomibot-timers`, the timers from a terminal.
- CI, a release workflow that publishes the image to ghcr.io when a release is
  published, and Dependabot, on GitHub.

### Changed

- `fortunes_svenska`, the library `/fortune` picks from by default, has 1000
  proverbs and quotes in Swedish instead of jokes translated from fortune-mod's
  `fortunes`: Swedish proverbs and wellerisms, Greek ones from Delphi to today,
  proverbs from other countries and quotes from writers long dead, with a line
  explaining the less known ones. `fortunes` is still there, in English.
- The weather is asked for by the city's coordinates, which OpenWeatherMap's
  geocoding gives once, as it no longer develops its weather by city name.
- The exchange rate comes from ExchangeRate-API's current open endpoint, and
  its errors say what went wrong.
- While Signal rate-limits the bot, waiting messages are tried every half hour
  instead of every two minutes, until a message goes out.
- The example date in `/help` and the `/timer` usage is always to come.
- The image is smaller, 232 MB instead of 323 MB: it has neither uv nor a
  second copy of the code, and phonenumberslite instead of phonenumbers,
  without the 41 MB of place names, carriers and time zones signalbot never
  reads. Its base images are pinned by digest.
- The containers' health checks: the image's runs every minute, and three
  failures running make the container unhealthy, rather than one every five
  minutes. The Quadlets have Podman kill an unhealthy container, for systemd
  to start again (`HealthOnFailure=kill`), and signal.container checks
  signal-cli itself, not just the REST API in front of it.
- The bot takes less memory: the fortunes aren't kept in memory once used,
  EXIF is read by Pillow, without exifread, and HEIF support is loaded when
  first needed.
- The translations are compiled as the image is built, not at every start;
  polib is no longer in the image.
- The files in `data_dir` are synced to disk before they replace the old ones.
- Debug mode keeps its files in a private temp folder, new at each start.
- Editing `/allowed` runs it again, as for other commands that only show
  something; `/allow` and `/disallow` still need a new message.
- Timers, specials and `/run` say they can't *manage* timers, specials or who
  may use the bot, rather than change them, as that covers `/chats` and
  `/allowed` too, which only list.
- signalbot 2.1.0, Pillow 13.0 (with security fixes), pydantic 2.14 and
  pydantic-settings 2.16.

### Removed

- The plain words `weather` and `info` (and in Swedish `väder` and `vader`)
  for `/weather` and `/info`: the bot's own names for commands all start
  with `/`. The config's aliases may still be plain words.

### Fixed

- The OpenWeatherMap API key could end up in a chat and the log, through the
  text of some network errors, which has the URL.
- The health checks, and looking for changes to the timers, were skipped when
  the bot was a moment late, and two skipped health checks restarted the
  container.
- Two daily posts at once could pick the same photo.
- A new timer could take the number of a line in the timers file the bot
  couldn't read.
- The list of photos sent is UTF-8, and only the bot's user may read it, as
  the other files.
- `/contacts` on an account that knows many people: profiles are asked for
  four at a time, at most fifty for each command, and lookups don't slow
  down with the account's size.
- When the bot stops, its own work is stopped too, and the messages waiting
  are kept.

### Security

- At the default log level, the log has no phone numbers, group IDs or
  message text.
- `signal-account.sh` warns before linking signal-cli to a phone: the bot
  would then take commands typed on the phone as the other person's.

## 0.92.0 - 2026-10-17

### Updating

- The bot is a container image, for x86 and ARM, with `config.toml` in its
  data folder: `/data/config.toml`. `deploy/` has Quadlet and Compose
  examples; `deploy.sh`, the git hook, the pod and its network are gone.
- Settings: `phone_number` is now `account`, `status_contacts` is `admins`;
  `allowed_contacts`, `allowed_groups`, `signal_cli_daemon` and
  `signal_one_request_at_a_time` are gone (who may use the bot is the allowed
  list, changed with `/allow`); `signal_service` is required. The bot says
  which setting is wrong and won't start until the configuration matches
  `config.example.toml`.
- signal-cli-rest-api must be a build after 0.101.

### Added

- `/msg` and `/run` post a message, or commands' answers, to other chats.
- Health checks every `healthcheck_minutes`, pinged to `healthcheck_url`, and
  the image's own health check.
- `/status` shows the versions of nejomibot, signalbot and
  signal-cli-rest-api.

### Removed

- `/forget`, `/contacts remove` and `/emoji`, as signal-cli-rest-api can't do
  them.
