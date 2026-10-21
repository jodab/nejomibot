# Changelog

What changed from one version of nejomibot to the next, newest first, and
what to do when updating. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Added

- `/contacts` and `/trust` show each person's Signal username, as
  `@alice.42`, where signal-cli knows it, as `/contacts <n>` did already;
  elsewhere, a person without a known phone number shows by name and
  username, as `Alice (@alice.42)`. Signal doesn't share usernames, so
  signal-cli knows only those of people it found by them.

## 0.99.7 - 2026-10-21

### Added

- The bot looks up the phone numbers on its lists that signal-cli can't put
  a Signal ID to, once each: at a start, and as `/allow` adds one. Someone
  who doesn't share their number in Signal is known to signal-cli by their
  Signal ID alone, so their number on the allowed list could neither name
  them nor match their direct messages, which come without it: the bot
  ignored those. Signal now says whose each number is, unless its owner
  keeps it from being found by number, and signal-cli keeps the two
  together.
- Once it knows a name, the bot writes it after the `#` of the lines of
  `allowed.txt` and `admins.txt` that have none, so the files say who's who.

### Changed

- People show by name and phone number together where both are known, as
  `Alice (+46701234567)`, in `/allowed`, `/admins`, `/chats`, `/timers`,
  `/delete list`, `/delivery`, `/incoming`, and what `/msg` and `/run`
  answer; by the name the allowed list has after their `#` where signal-cli
  has none, `/chats` too.
- Timers, `/run` and specials can run what only shows something, wherever
  the admins post it: `/delivery`, `/chats`, `/allowed`, `/admins`,
  `/incoming`, `/dailypost preview`, and `/timers` and `/specials` alone. A
  timer at 08:15 can post `/delivery` to your own chat, say. What changes
  timers, specials, birthdays or who may use the bot, posts to other chats,
  or is each chat's own, they still can't.
- `/run` runs its commands as the admin who sent it, rather than as the
  first admin in the config, so numbers in it are theirs: `/run 1 /incoming
  4,9` forwards messages 4 and 9 of their own `/incoming` list to chat 1.

### Fixed

- A `/delete list` that a timer, `/run` or a special posted replaced the
  numbers of the list the first admin was shown last, so their next
  `/delete 3` could delete another message than the one they saw as 3. Such
  a list now leaves an admin's numbers as they were, for `/incoming` too.
- `/contacts` listed the bot's own safety number, under Only a safety
  number, and `/contacts`, `/trust` and `/status` counted it, verified.

## 0.99.6 - 2026-10-21

### Added

- `/delivery`, for the admins: whether the bot's latest messages arrived. It
  shows the `delivery_messages` (30) latest of those it sent in the last
  day, wherever they went, newest first, with how many in each chat got it
  and read it, from the delivery and read receipts their phones send.
- A warning in the log for a message nobody's phone confirmed in 10
  minutes: Signal took it, but it may not have arrived. At DEBUG, the log
  has how many each message reached by then.

### Updating

- The examples in `deploy/` pin a newer CI build of signal-cli-rest-api,
  `1792271041-ci` from 2026-10-17, still with signal-cli 0.14.9. Unlike the
  one before, it doesn't drop what reaches a websocket while it's busy with
  the message before, so `/delivery`'s counts are whole: put its digest in
  Quadlets or Compose files made from the examples.

## 0.99.5 - 2026-10-19

### Changed

- `/status` names the bot's time zone, `timezone`, on a line of its own, and
  its times go without it: the next timer run no longer says `CEST`.

## 0.99.4 - 2026-10-19

### Added

- Admins besides those in the config: the config's admins make someone an
  admin with `/admin add <who>`, and no longer with `/admin remove <n>`, by
  their number in `/admins`, which lists every admin. Those added may use
  every command but these two, and no command can take away what the
  config's admins may do. They're kept by Signal ID, which can't change
  hands as a phone number can, in `data_dir/admins.txt`, as the allowed
  list is; the notices still go to the config's admins alone.
- `/trust` alone lists everyone's safety numbers, numbered as `/contacts`
  numbers them, as the Signal apps show them, and whether each is verified;
  `/trust <who>` shows one's.
- Backups: every day at `backups_at` (04:00), and at a start if the latest
  is a day old, the bot backs up what it keeps in `data_dir`, with its
  config and the sample config, as `nejomibot-2026-10-19_0400.tar.zst`, into
  `data_dir/backups`, or `backups_dir`, keeping the newest `backups_kept`
  (30); none when nothing in the files has changed since the latest, and
  `backups = false` makes none at all. `/status` has a Backups check, and
  the health check pings say how many there are, how old the newest and the
  oldest are, and when the last was skipped as nothing changed.
- The holidays of 33 more countries for the daily post, by their codes in
  `holidays`, such as `GB` or `US`: the rest of the European Union, Norway,
  Iceland, Switzerland, the United Kingdom, the United States, Canada,
  Australia and New Zealand. Their public holidays, Valentine's Day, Easter
  Sunday, Christmas Eve and New Year's Eve, Mother's Day and Father's Day
  where they have one day for them, and some traditions of their own. Their
  names are in English, in Swedish too, but those they share with Sweden or
  Greece.

### Changed

- `/contacts` numbers everyone, and a number from it, or from `/trust`,
  stands for that person in `/contacts <who>`, `/contacts add`, `/trust`,
  `/allow` and `/admin add`: the number in the list you were shown last, as
  with `/delete list`, until you ask for it again.
- `/allowed` names every admin, and `/chats` offers the admins added.

## 0.99.3 - 2026-10-19

### Changed

- Subcommands in the bot's language: in Swedish, `lägg till` for `add`, `ta
  bort` or `radera` for `remove`, `lista` for `list`, `töm` for `clear`,
  `kör` for `run`, `alla` for `all` and `förhandsvisa` for `preview`, as in
  `/lista lägg till mjölk` or `/timer ta bort 3`. `/hjälp` and the Swedish
  messages show them, and the English ones work too.
- In Swedish, `/dailypost` is `/dagenspost`; `/dagensbild` still works.

## 0.99.2 - 2026-10-19

### Added

- `/dailypost preview`, for the admins in a direct chat: what the daily post
  will say atop the weather on a day, such as `/dailypost preview 10-25`,
  `2026-10-25` or `tomorrow`, today without one, in each group the bot is in
  and in a direct chat, without posting anything else or using up a photo.
  In Swedish, `/dagensbild preview`.

### Changed

- Edits of commands that add or remove something now work: the edit takes
  the place of what it edits, which is undone first. Editing `/remind 18:00
  Cake` to `/remind 19:00 Cake` leaves one reminder, at 19:00. That's
  `/remind`, `/list`, `/birthday`, `/nameday`, `/timer add` and `remove`,
  `/special add` and `remove`, `/allow`, `/disallow` and `/contacts add`.
  Edits of `/msg`, `/run`, `/timer run` and `/delete <n>`, whose posts and
  deletions can't be undone, aren't run, and the bot says so, as it does for
  an edit of a message from before a restart. The admins' own specials run
  again when edited, as `/dailypost` does.

## 0.99.1 - 2026-10-19

### Changed

- `/birthdays` and `/namedays` number the admins' list as it's shown, the
  coming ones first, from 1. `/birthday remove` and `/nameday remove` take
  the numbers of the list the admin was shown last, as `/delete` and
  `/incoming` do: after a restart, send the list again first.
- `tools/release.sh` makes patch releases only, for now: nejomibot stays on
  0.99.x until 1.0. A minor or major release stops with an error.

## 0.99.0 - 2026-10-19

### Added

- Birthdays and name days in the daily post, atop the weather, in the groups
  of those they're for: "🎂 Alice turns 36 today!", "🌸 Happy name day,
  Bob!". The admins keep them, in a direct chat with the bot: `/birthday add
  1990-03-14 Alice` for a contact, as `/contacts` finds them, saved by name,
  shown in the groups they're in by their name in the contacts; `/birthday
  add 1940-05-01 1 Grandma` for someone not on Signal, in the groups given by
  their numbers in `/chats`, or without them, in every group; `/nameday add
  08-08 Alice`; `/birthday remove 2`. Never in a direct chat. `/birthdays` and
  `/namedays`, for everyone allowed, list them, the coming ones first: in a
  group, its own; for the admins, in a direct chat, all of them, numbered.
  Kept in `data_dir/birthdays.txt`. In Swedish, `/födelsedag`,
  `/födelsedagar`, `/namnsdag`, `/namnsdagar`.
- `holidays`, none by default: the daily post names the day's holidays, flag
  days and traditions of these countries atop the weather, `SE` for Sweden
  and `GR` for Greece, each after its flag: "🇸🇪 National Day of Sweden ·
  flag day".
- `/remind`, for everyone allowed: a reminder the bot posts in the chat when
  it's due, once: `/remind 18:00 Take the cake out`, `/remind 30m Call Bob`,
  `/remind tomorrow 08:00 Pick up Bob`, `/remind fri 17:00 Pizza!`.
  `/remind` alone lists the chat's, and `/remind remove 2` removes one. Kept
  in `data_dir/reminders.txt`. In Swedish, `/påminn`, and `om 30m`.
- `/list`, for everyone allowed: a list for each chat, such as for shopping:
  `/list add milk, eggs`, `/list remove 2,5`, `/list clear`. Kept in
  `data_dir/lists.txt`. In Swedish, `/lista`.
- `/forecast`, `/forecast <city>`: the weather today and tomorrow, from
  OpenWeatherMap's forecast: each day's worst weather in the daytime, its
  lowest and highest temperature, and its chance of rain or snow. Kept for
  30 minutes; a place named counts toward `weather_calls_per_hour`. In
  Swedish, `/prognos`.
- `/onthisday`: a photo taken on this day in an earlier year, or else within
  three days of it, under "3 years ago today". In Swedish, `/dennadag`.
- Notices to the admins, in a direct chat: after an update, the versions;
  after a stop that wasn't clean, that the bot is up again; when Signal
  starts rate-limiting the bot, how to lift the limit; and when someone's
  safety number changes, whose, as the bot can't send to them until it's
  trusted. The bot keeps which version ran last in `data_dir/run.json`.

### Changed

- `/weather` ends with the day's sunrise, sunset and daylight, in the
  place's own time: "🌅 07:35 · 🌇 17:21 · 9 h 46 min of daylight". So does
  the daily post's weather.
- What timers, specials and `/run` can't run, they now name: "Timers,
  specials and /run can't run /msg." They can't run `/remind`, `/list`,
  `/birthdays`, `/namedays`, `/birthday` or `/nameday` either.
- The bot's health check says when Signal rate-limits the bot, and what
  lifts the limit, while messages wait.

### Updating

- For holidays in the daily post, set `holidays`, such as `holidays = ["SE",
  "GR"]`; see config.example.toml.

## 0.98.0 - 2026-10-19

### Added

- A greeting for those on the allowed list who write to the bot in a direct
  chat, but no command: "Hi, I'm Mybot, a bot. Try /help for a list of
  commands. Contact Alice for more information.", with the bot's profile
  name and the first admin's name as the bot's contacts have it. Once a day
  at most for each person; commands are answered as ever, never with it.
- `/weather <city>`, such as `/weather Helsinki`: the weather in the place
  named, under a heading that names the place OpenWeatherMap found, in the
  bot's language where it has the name, with its state or region and
  country: "Weather in Springfield, Illinois, US". A country code picks among
  places of a name: `/weather Stockholm,US`, `/weather Springfield,MO,US`.
  In Swedish, `/väder <ort>`.
- `weather_calls_per_hour`, 10 by default: the most the bot asks
  OpenWeatherMap about places named in an hour, finding them included; past
  that, `/weather <city>` says when to try again. `weather_city` isn't
  counted, so `/weather` alone and the daily post always get the weather.

### Changed

- The bot keeps each place's weather for 10 minutes, as OpenWeatherMap's
  changes every 10 minutes: `/weather`, the daily post and `/status` answer
  with it when asked again sooner, without asking OpenWeatherMap.

## 0.97.1 - 2026-10-19

### Changed

- `/delete list` shows the bot's 50 latest messages, not 20, and `/incoming`
  keeps and lists the 50 latest messages to the bot.
- `/delete` deletes several of the list at once: `/delete 2,5,11`. It stops
  at one it can't delete, as when Signal can't be reached, and says which it
  didn't try.

## 0.97.0 - 2026-10-19

### Added

- `/delete list`, for the admins in a direct chat: the bot's 20 latest
  messages, wherever it sent them, numbered, with when, where to and how
  each starts. `/delete <n>` deletes one of them for everyone, and says
  which. The numbers are those of the list the admin was shown last.
- `/incoming`, for the admins in a direct chat: the 20 latest messages
  anyone but the admins sent the bot in a direct chat, commands too,
  numbered, with when, from whom and how each starts; `/incoming 4,9`
  forwards those two to the admin in full, their text, as the bot doesn't
  fetch attachments. They're kept in memory only, and go when their sender
  deletes them or they disappear. In Swedish, `/inkorg`. Timers and `/run`
  can't run it.

### Changed

- `/help` shows the names some commands have had all along, `/test` for
  `/status`, `/time` for `/info` and `/safety` for `/contacts`, after them,
  as it does the configuration's aliases, which show on a command's first
  line only. They're aliases now, so the configuration's aliases win over
  them, as over the language's: a configuration with one of them as an alias
  stopped the bot.
- The weather's heading, "Weather in Stockholm", is in bold, in `/weather`
  and the daily post; what explains a proverb of `fortunes_svenska`, the
  paragraph under it, is in italics, in `/fortune` and `/dailyquote`.

## 0.96.0 - 2026-10-18

### Added

- `fortune_library`, the library `/fortune` picks from when none is named:
  `fortunes_svenska` if not set, as before, or another that `/fortune list`
  names, or `all` for every one of them. `/dailyquote` stays with
  `fortunes_svenska`.

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
