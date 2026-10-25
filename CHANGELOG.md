# Changelog

All notable changes to nejomibot are documented in this file, newest first,
together with anything you need to do when updating. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## Unreleased

### Changed

- `/status` shows the bot's profile as `/profile` does, a line each for the
  name, the About, the username, the avatar, and the phone number or Signal
  ID, rather than an unlabeled line with the number or Signal ID, the name
  and the username.
- `/contacts` shows everyone in full, a line each for their profile name,
  username, phone number, Signal ID, About, groups, whether they're blocked
  and whether they're verified, with a blank line between people, rather
  than two short lines each without the Signal ID and the About.
  `/contacts <who>` shows the person the same way, then their safety number,
  and labels the Signal ID and the About as `/profile` does.
- The README, DOCKERHUB.md and config.example.toml say how to make someone
  without a phone number an admin: by their Signal ID, in `admins`.

## 0.99.27 - 2026-10-25

### Added

- `/help <command>`, as in `/help photo`: the command's page, with how to use
  it and examples, in the chat's language, for any command the sender may
  use. It takes the command by any of its names, with or without its period
  or slash, an alias, an album's shortcut or a special's name. Some pages
  say more to the admins, in a direct chat, such as `/today preview` on
  `/today`'s.
- `startup_notice`: set it to `false` to turn off the notice the admins get
  at each start.

### Changed

- `/help` is shorter and easier to read: a line for each everyday command,
  without what may follow it, in groups, then how to see a command's page.
  For the admins, in a direct chat, the admin commands follow by name, a line
  for each group, rather than a line for each way to use them and notes on
  what follows them, which are now on the commands' pages. The admins'
  `/help` is 32 lines rather than 73, and like everyone else's, it fits in
  one message in every language, rather than ending behind **Read more**.
- The welcome a new admin gets ends with how to see a command's page.
- The admins get the notice of a start at every start, as soon as the bot is
  ready, rather than at most once in ten minutes.

## 0.99.26 - 2026-10-25

### Changed

- The bot keeps when each photo was taken in `data_dir/photo-index.txt`, so
  a start reads only the photos added or changed since, rather than every
  photo: on a Raspberry Pi 4 that took 47 seconds for 7,671 photos at each
  start, and a `/photo` with a date, `/albums` or `/onthisday` sent
  meanwhile waited for it. The first start after the update still reads
  them all.

## 0.99.25 - 2026-10-25

### Added

- Accounts without a phone number, as Signal Login creates: give the
  account's Signal ID as `account`. signal-cli-rest-api supports them in the
  build that `deploy/` uses. `/status` and `/profile` warn while such an
  account has no username, since nobody can find it then, and
  `signal-account.sh` shows the account's Signal ID, skips the PIN and the
  phone number's privacy in `setup`, and warns before `unregister` that only
  the Recovery Key restores it. Restoring one with its Recovery Key takes
  signal-cli itself, as signal-cli-rest-api can't yet (see the README).
- The bot's profile in the configuration: `bot_name`, `bot_about`,
  `bot_avatar` and `bot_username`, which the bot sets as it starts. Once
  set, it keeps the profile in `data_dir/bot.txt`, with every change made
  with `/name`, `/about`, `/avatar`, `/username` or `signal-account.sh`. At
  each start it compares the account's profile with `bot.txt` and changes
  only what differs, so a new account gets the profile, and an edit of
  `bot.txt` is set. A username that Signal turns down gets the number
  Signal gives it.

### Changed

- The image is 10 to 14 MB smaller, as its compiled modules no longer carry
  debug information, which only debuggers read, and the bot uses about
  1.5 MB less memory while it runs.
- The bot reads when each photo was taken in the background as it starts,
  so the first `/photo` with a date, `/albums` or `/onthisday` after a start
  no longer waits for that.
- While the bot works on a command, it keeps showing that it is typing,
  as Signal's apps do, until the answer arrives, for two minutes at most:
  from the start for slower commands, as before, and now also for any other
  command that takes more than a second. Before, it showed this once, which
  Signal's apps show for 15 seconds at most.
- A command no longer waits for its read receipt and the typing indicator
  to be sent before it runs: they go while it runs, and its answer waits for
  them. On a Raspberry Pi, where each takes about 0.2 seconds, a slower
  command answers about a quarter of a second sooner.
- The log records each start's steps: the version, where the settings come
  from, when signal-cli-rest-api has the account, the number of reminders,
  when the bot is ready, and when reading when the photos were taken starts
  and ends; with `log_level = "DEBUG"`, the steps in between too.

## 0.99.24 - 2026-10-25

### Changed

- The image now uses Python 3.15.1 instead of 3.14.9, and running the bot
  from a checkout takes Python 3.15, which uv installs. The bot starts as
  fast as before and uses about 1.5 MB more memory. The images for amd64
  and arm64 are slightly smaller, and the one for arm/v7 is 7.7 MB larger.
- Dependencies: signalbot 2.2.0 and multidict 7.2.1.

## 0.99.23 - 2026-10-25

### Updating

- The bot no longer makes backups. Before updating, remove `backups`,
  `backups_at`, `backups_dir` and `backups_kept` from the configuration, if
  it has them: the bot doesn't start with a setting it doesn't know, and its
  log names the setting. A volume mounted for `backups_dir` is no longer
  needed. The backups already made stay in `data_dir/backups` or
  `backups_dir` until you delete them; to keep backing up, copy `data_dir`
  and the configuration file by other means.

### Removed

- The daily backups, their four settings, `/status`'s Backups check, and
  the backups' line in the startup notice and in the health check pings.
  The bot uses 0.3 MB less memory, or 1.9 MB less once a daily backup would
  have run, and the image is 0.17 MB smaller.

## 0.99.22 - 2026-10-24

### Updating

- An album without a birth date of its own no longer takes
  `photos_birth_date`, which now applies only to the photos in no album.
  Give such an album its birth date with `/album <album> <date>`.

### Changed

- An album has no birth date until `/album` sets one: `/albums`, `/album`
  and the captions showed `photos_birth_date` for an album without one.

## 0.99.21 - 2026-10-24

### Updating

- The image runs as user and group 1000, rather than 1001. With the Quadlet
  examples, whose data folder has `:U`, Podman hands the folder to the new
  user by itself. Otherwise, before updating, run `sudo chown -R 1000:1000
  data` (with rootless Podman, `podman unshare chown -R 1000:1000 data`), or
  keep the bot as 1001 with `user: "1001:1001"` in Compose, `User=1001` and
  `Group=1001` in a Quadlet, or `--user 1001:1001`. A rootless Quadlet with
  `UserNS=keep-id:uid=1001,gid=1001` takes `uid=1000,gid=1000` instead.
- Timers, `/run` and specials can't run `/delete`, other than `/delete
  list`, nor `/contacts add`. A timer or special with one of them is an
  unreadable line of its file from now on, left as it is, which the notice
  at the start names.

### Added

- Specials for everyone: `/special everyone <name>` lets everyone the bot
  may talk to use a special, in direct chats and in allowed groups, and
  `/help` lists it for them under Specials; `/special admins <name>` makes
  it the admins' alone again. Its commands run for whoever uses it, where
  they use it, and when it has admin commands, such as `/contacts`, the
  bot names them, as everyone who uses it then sees what they show.
  `specials.txt` marks such a special with `(everyone)` after its names.
- A limit on how many commands the bot answers each person: at most
  `command_limit` (20) in `command_limit_minutes` (10). Past that, the bot
  says once when it answers them again, and leaves their other commands
  unanswered until then. The admins aren't limited, nor what timers, `/run`
  and specials run.
- The README's "Signal's rate limits" describes what Signal limits, as far
  as its server's code tells, how the bot keeps below it, and which
  settings tune that.

### Changed

- While Signal rate-limits the bot, it sends nothing at once: new messages
  wait, read receipts and the typing indicator aren't sent, and only the
  message that has waited longest is tried, after 2 minutes, then twice as
  long after each try, at most `rate_limit_retry_minutes` (30) apart. A
  command from an admin, who may have just lifted the limit, has it try
  again at once, a minute after the last try at the soonest. Before, every
  new message was tried at once, and every half hour a message to each chat
  with messages waiting.
- `/contacts` asks again for the profile of someone without a name at most
  every six hours, rather than each time, as each asks Signal's servers.
- `/info` keeps the exchange rate until the exchange rate API's next daily
  update, so it answers at once; `/status` still asks the API.
- `/photo`, `/uniquephoto`, `/cache` and `/onthisday` list the photo library
  once rather than twice: `/uniquephoto` with an album takes 20 ms rather
  than 32 ms for 7,641 photos on a desktop. `/help` takes a tenth of the time
  it took.
- The bot's own websocket, for the delivery receipts, pings
  signal-cli-rest-api every 30 seconds, so a connection that died unnoticed
  is opened again.
- The log has the photos' paths at DEBUG, rather than INFO: an album is
  often named after someone.

### Fixed

- A timer that runs a special stayed off after a mistake in `specials.txt`
  was set right, until the timers file changed or the bot restarted. It is
  read again as soon as the special can be read.
- The timers file lost the comments written in it by hand, and moved the
  lines the bot couldn't read to its end, as each timer ran. Both stay as
  they are, where they are.

## 0.99.20 - 2026-10-24

### Updating

- Aliases and shortcuts start with `/` or `.`. A plain word made every
  message that starts with it a command, in groups too, so it is now taken
  with a `/`: `pic` is `/pic`, in the configuration's `aliases`, in
  `albums.txt` and in `specials.txt`, and the log says so at startup for
  the configuration's. Nothing needs editing, but type `.pic` or `/pic`
  where `pic` worked before. A plain word that is then a command's name,
  such as `photo` as an alias for `/weather`, stops the bot at startup, as
  any alias that is a command does, and the message names it.
- The albums' rounds of `/uniquephoto` are kept in
  `data_dir/album-rounds.txt`, apart from the library's in
  `sent-photos.txt`. The first `/uniquephoto` after the update starts the
  new file from what `sent-photos.txt` has of albums, so every round goes
  on where it was.
- Phone numbers are checked as E.164 numbers: a `+`, a country code that
  doesn't start with 0, and 7 to 15 digits in all. One outside that, which
  can't be a Signal number, stops the bot at startup in `account` or
  `admins`, and is an unreadable line on the allowed list.

### Added

- `/sphoto` (`/enkelbild` in Swedish): a simple photo, picked as `/photo`
  picks it, from every album or the one named, at random or by date, and
  sent alone, without its caption or heading.
- `signal_service` may be an IPv6 address in brackets, such as
  `[::1]:8080`, and the commands in `aliases` may start with `.`.

### Changed

- `/uniquephoto`'s rounds no longer disturb each other: when an album's
  round starts over, the library's round, as the daily post's
  `/uniquephoto` runs it, keeps the photos it has sent, so it never sends a
  photo twice before it has sent every one.
- The bot works out a message's aliases once, rather than in each of its 38
  handlers: on a Raspberry Pi 4, that saves 23 ms of CPU for each message
  it receives.
- The image has the bytecode of the standard library's modules that the
  bot imports, which the base image leaves out: on a Raspberry Pi 4, the
  bot starts and `nejomibot-timers` answers about 2 s sooner (its imports
  took 4.7 s, now 2.4 s), for 5.5 MB more in the image.
- A special's commands run as the admin who ran it, as `/run` runs its
  commands: numbers from lists, as in `/incoming 4`, are that admin's.
- An edit of `/admin add` isn't run once the welcome has gone out, which
  can't be taken back, and says so; the new admin was welcomed twice.
- `/status` reads the Signal groups once, not twice.
- The notice of a changed safety number names the person as `/contacts`
  finds them: by signal-cli's name, else by number or ID.
- `nejomibot-timers` stops after 60 s without an answer from
  signal-cli-rest-api, rather than after aiohttp's 5 minutes.
- The container's guide, `nejomibot-help.sh`, is shorter, and the account
  tool's help on containers more concise.

### Fixed

- `/cache` failed when a photo was removed while it counted them.
- `/photo <date> <time>` answered that no photo said when it was taken when
  the nearest photo couldn't be read; it now tries the next nearest.
- An empty photo library logged that no valid photo was found in 5
  attempts, when none was attempted.
- `config.example.toml` lists `/album`, `/incoming` and `/delivery` among
  the admin commands.

## 0.99.19 - 2026-10-24

### Added

- The setup guides show how to set up the Signal account without the bot
  running, as before its first start: `signal-account.sh` runs in a
  container of its own on signal-cli-rest-api's network, `podman run --rm
  -it --no-healthcheck --network container:signal docker.io/jodab/nejomibot
  signal-account.sh setup`, or with Compose, `docker compose run --rm
  nejomibot signal-account.sh setup`.

### Changed

- The photo commands list the library in less than half the time: on a
  Raspberry Pi 4 with 7,639 photos, `/uniquephoto` picks its photo in
  85 ms rather than 206 ms, and with an album, in 203 ms rather than 463 ms.
- Every interactive shell in the container starts with the guide to its
  tools, `sh` as well as `bash`, and login shells too.

### Fixed

- A login shell in the container, such as `sh -l` or `bash -l`, didn't find
  the bot's tools, since Debian's `/etc/profile` sets a PATH without them.

## 0.99.18 - 2026-10-24

### Updating

- The examples in `deploy/` pin a newer CI build of signal-cli-rest-api,
  `1792710189-ci` from 2026-10-22, still with signal-cli 0.14.9: it adds
  support for Signal accounts without a phone number, and lists the
  accounts with their Signal IDs, which the bot reads since 0.99.10. Put its
  digest in any Quadlets or Compose files you made from the examples.

### Added

- First steps toward running the bot on a Signal account without a phone
  number, which signal-cli-rest-api supports since its CI build
  `1792710189-ci`, though not yet in a release, and which hasn't been tried
  with a real account yet. The `account` setting, and `signal-account.sh
  --account`, take such an account's Signal ID, with or without its
  dashes, and `/profile` shows the Signal ID where it would show the
  number. Registering such an account, which takes its Recovery Key, isn't
  possible yet.

### Changed

- A special's text may contain a `|`, which `/special add` refused before:
  `/special add /menu Fish | chips /weather` posts "Fish | chips" with the
  weather. `specials.txt` keeps it as `\|`, as it keeps a typed `*`.

### Fixed

- Each stop of the bot logged an error with a traceback from the scheduler,
  as it cancelled the bot's listening for delivery receipts. That listening
  now runs as a task of its own, which stops without a word.

## 0.99.17 - 2026-10-24

### Updating

- The bot now shows commands with a period, as in `.photo`, which phone
  keyboards have on their first page (see Added). Commands with a slash work
  as before, and the bot's files keep them that way. To have the bot show
  them with a slash again, set `command_prefix = "/"`.
- `/weather` no longer starts with the date and time, which `/today` now
  shows: a timer or special that runs `/weather` without `/today` posts no
  date any more.
- The examples in `deploy/` now run signal-cli-rest-api in `json-rpc` mode
  rather than `json-rpc-native` (see Changed). To follow them, change `MODE`
  to `json-rpc` in your Quadlet or Compose file and restart
  signal-cli-rest-api; the Signal account's data works in either mode.

### Added

- Every command can start with a period in place of its slash: `.photo` is
  `/photo`, in a message, a timer, a special, `/run`, an alias or a
  shortcut. The new `command_prefix` setting sets how the bot shows
  commands: `"."`, the default, or `"/"`. `/help` ends with a note that
  either works.
- Shortcuts for specials: `/special shortcuts /dailypost /daily` makes
  `/daily` post the same as `/dailypost`, and `/special shortcuts
  /dailypost -` removes them. A special has at most five, `/specials` lists
  them, and `specials.txt` keeps them after the special's name.
- Danish, German, Spanish, Finnish, French and Norwegian, with their own
  names for the commands and their words for days, times and subcommands.
- Templates for new languages: `nejomibot/locale/messages.pot`, every
  message, and `template.toml`, every command and word, which
  `tools/translations.sh <code>` copies to start one. A new language takes
  its two files and no change to the code; the README's Languages section
  has the steps, and the tests now take languages with any number of plural
  forms.
- A shell in the bot's container, as in `podman exec -it nejomibot bash`,
  starts with a short guide to the bot's tools, where they are, and where
  the bot keeps its files. `nejomibot-help.sh` shows it again.

### Changed

- `/today` and `/day` always reply now, with the date and time in bold
  first, then the day's holidays, and in a group its birthdays and name
  days. On a day with none of these, they show the date and time alone,
  where before they said "Nothing special today." in a direct chat and
  nothing in a group.
- The birthday or name day of someone not on Signal, given again on the
  same day, now shows in the groups given this time, or in every group,
  instead of being added a second time: after `/nameday add 08-08 Grandma`,
  `/nameday add 08-08 1,2 Grandma` shows it in chats 1 and 2 alone. The reply
  to one shown in every group says how to choose the groups, and `/nameday`
  on its own now gives examples, as `/birthday` does.
- The examples in `deploy/` run signal-cli-rest-api in `json-rpc` mode,
  where signal-cli runs on Java: its native build has had bugs that the
  Java one hasn't, and 32-bit ARM has no native build. signal-cli-rest-api
  then takes about 360 MB of memory on a Raspberry Pi 4. The README and the
  Docker Hub page say so, and that the image runs on 32-bit ARM as well.

### Fixed

- The Swedish example timer in `/chats` ran `/dagenspost`, which no longer
  exists; it runs `/väder; /bild` now.

## 0.99.16 - 2026-10-24

### Updating

- A `+` standing on its own in a special now joins the parts on either side
  of it (see Added). If one of your specials has such a `+` in its text, or
  in what follows a command, such as an album name, the special posts
  differently from this release on: attach the `+` to a word, or write
  "plus" instead.

### Added

- In a special, a `+` in place of a `;` puts the parts on either side of it
  in one message, separated by a blank line. For example, `/special add
  /dailypost /today + /weather; Photo of the day! /uniquephoto` posts the
  day's holidays, and in a group its birthdays and name days, with the
  weather below them in one message, as `/today` showed them before 0.99.14,
  followed by the photo. Text can be joined too: `/weather + Have a nice
  day!` adds a line below the weather. A `+` inside a word, as in `C++`,
  remains text.

### Changed

- `/today` and `/day` no longer reply in a group on a day with nothing
  special; in a direct chat, they still say "Nothing special today.".
- The documentation has been rewritten to be clearer and easier to follow:
  the README, the Docker Hub page, this changelog and the to-do list.

## 0.99.15 - 2026-10-23

### Added

- A welcome message for new admins: `/admin add` sends the new admin, in a
  direct chat with the bot, a message saying who made them an admin, that
  `/help` lists every command, and a few commands to start with.
  `/admin add <who> <language>`, such as `/admin add 3 sv`, sets that
  language for them, which the bot then uses with them, and sends the
  welcome in it; without a language, the welcome is in their own language,
  or the bot's. The reply says whether the welcome was sent.

### Changed

- From this release on, nejomibot is licensed under the MIT License instead
  of the GNU General Public License, version 3 or later, which still applies
  to 0.99.14 and earlier releases. The fortune libraries from fortune-mod
  keep their BSD license. The package, and therefore the image, now includes
  the text of both licenses, as both licenses require.
- Dependencies: signalbot 2.1.3, python-dateutil 3.0.0, pydantic-settings
  2.16.1, websockets 17.3 and tzlocal 5.4.5. The image now uses Python
  3.14.9 and is built with uv 0.13.5.

## 0.99.14 - 2026-10-23

### Updating

- `/today` no longer posts the weather; `/weather` does. Add `/weather`
  after `/today` in your timers and specials, such as the daily post:
  `/today; /weather; /uniquephoto`. Right after updating, send `/special
  add` with the special's name and its new parts, or remove the timer and
  add it again; alternatively, edit `timers.txt` and `specials.txt` in
  `data_dir` by hand while the bot is stopped for the update. Until then,
  the daily post has no weather; adding `/weather` before the update would
  post the weather twice.
- An alias for `/photo` in the configuration that stands for an album, such
  as `"/photo" = ["/alice"]` for a library that was all Alice's, can now be
  the album's shortcut instead (see Added): remove it from the configuration
  first, because `/album` doesn't accept a name the bot already responds to.

### Added

- Album shortcuts, which admins can set: `/album Alice shortcuts /alice
  alice` makes `/alice` and `alice` other names for `/photo Alice`, so
  `alice 2017` means `/photo Alice 2017`; `/album Alice shortcuts -` removes
  them. A shortcut is a single word, with or without a leading `/`, but not
  a name the bot already responds to: a command, an alias or a special.
  `/albums` and `/album Alice` show them. They are stored in
  `data_dir/albums.txt`, with the birth dates. In Swedish, `genvägar`; in
  Greek, `συντομεύσεις`.
- `/photo` accepts a date as precise as you like: `/photo 2017` shows a
  photo taken in 2017, `/photo 2017-05` one from May 2017, and `/photo
  2017-05-14 15` one from between 15:00 and 16:00 that day. If there is none
  in that period, it picks from the nearest year, month or hour that has
  photos, as `/photo 2017-05-14` already did for days, and says how far off
  that is.

### Changed

- `/today` lists only the day's holidays, birthdays and name days, as `/day`
  did, and `/day` is now another name for it (in Swedish `/dagen`, in Greek
  `/ημέρα`). In what a timer, a special or `/run` posts, it is empty on a
  day with none of these, so `/today; /weather` then posts just the weather;
  when asked directly, it still says "Nothing special today.".

## 0.99.13 - 2026-10-23

### Updating

- `/photo new` is now `/uniquephoto` (in Swedish `/unikbild`, previously
  `/bild ny`). Before updating, change it in your timers and specials, such
  as the daily post: remove the timer or special and add it again with
  `/uniquephoto`, or edit `timers.txt` and `specials.txt` in `data_dir` by
  hand while the bot is stopped. A timer or special left with `/photo new`
  asks `/photo` for an album called "new", and posts that there is no such
  album instead of a photo.

### Added

- Albums: each folder directly inside the photo library (`photos_dir`) is an
  album, named after the folder, with its subfolders included. `/albums`
  lists them, with how many photos each one has, the years they were taken
  and the album's birth date. `/photo Alice` picks from the album Alice, as
  does `/onthisday Alice`, and `/cache Alice` counts its photos; without an
  album, each command uses every photo, in an album or not, as before. Album
  names are matched in any letter case, and may contain spaces.
- `/uniquephoto`, the round of photos not yet sent, which replaces `/photo
  new`; each album also has a round of its own: `/uniquephoto Alice` posts
  each of Alice's photos once, round after round, independently of the other
  rounds.
- `/photo 2024-06-01 15:00` shows the photo taken closest to that moment,
  under how far off it is; `/photo 2024-06-01` shows one taken that day, or
  failing that, on the nearest day that has photos; `/photo Alice
  2024-06-01` picks from that album.
- `/album <album> <date>`, for admins: a birth date for the album, from which
  its captions count an age, stored in `data_dir/albums.txt`. `/album
  <album> -` removes it, so that `photos_birth_date` applies to the album, as
  to every album without a birth date of its own; `/album <album>` shows the
  album.
- A language for each chat. `/language` (in Swedish `/språk`) lists the
  languages the bot speaks, and the one it speaks in the chat;
  `/language sv`, or `/language svenska`, makes it speak Swedish in a direct
  chat with the sender, and in a group, when an admin sends it, with
  everyone in the group; `/language default` returns to the `language`
  setting. In a direct chat, an admin can set the language of chats listed
  in `/chats`: `/language 3,1 sv`. The languages are stored in
  `data_dir/languages.txt`.
- The bot replies in each chat's language, and posts to the chat in that
  language: the timers' posts, `/run`'s posts, reminders, the greeting, the
  notices to each admin, and the note on a late message. A timer that posts
  to chats in two languages runs its commands once in each, with the same
  random picks, so every chat still gets the same photo, captioned in its
  own language, and the round uses up only one photo.
- Greek: `language = "el"`, or `/language el` for a chat, with Greek names
  for the commands, such as `/καιρός` and `/φωτογραφία`, and Greek words for
  days and subcommands, such as `δευ-παρ` and `πρόσθεσε`.

### Changed

- The bot accepts every language's command names, and its words for days,
  times and subcommands, from anyone, whatever the chat's language:
  `/väder` works in an English bot too. `/help` shows the names in the
  chat's language.
- The weather names a place in each chat's language, when OpenWeatherMap
  has a name for it in that language.
- `/status`, the startup notice and `/cache` show how many albums there are.
- The bot's notices and reports are worded more plainly and formally: the
  startup notice, the details of `/status` and the health checks,
  `/delivery`, the notes on late and dropped messages, and the warnings
  about rate limits, changed safety numbers and unreadable lines in its
  files, in English and Swedish.
- A `/uniquephoto` pick does its bookkeeping in a third of the time: 32 ms
  for 7,641 photos on a desktop computer.

### Removed

- `/photo new` (see Updating).

## 0.99.12 - 2026-10-23

### Fixed

- Registering with `signal-account.sh` could get stuck at the code, because
  Signal's first text message sometimes never arrives, and the tool had no
  way to request another. When the tool asks for the code, pressing Enter
  now asks Signal to send it again, or to call with it.

## 0.99.11 - 2026-10-23

### Added

- The admins are notified of each start, in a single message:
  `🟢 nejomibot 0.99.11 started`, when, and how long the bot took to become
  ready; then anything that needs their attention, such as an update, a
  stop that wasn't clean, unreadable lines in the bot's files (which have no
  effect), a clock that isn't synchronized, or messages still waiting to be
  sent; then how the bot is doing: its timers and the next run, its groups,
  allowed chats and admins, the photos, the backups, the clock, its memory
  use, signal-cli-rest-api's version, and where it runs. The notice is sent
  at most once every ten minutes, except after an update, so that a crash
  loop can't flood the admins: a start within that time is reported once
  the ten minutes are up. Debug mode sends it too, marked as such.

### Changed

- The notices of an update and of a stop that wasn't clean are now part of
  that message, instead of separate messages.

## 0.99.10 - 2026-10-23

### Updating

- `/dailypost` and `/dailyquote` have been removed: specials of your own can
  post the same, with their headings formatted in bold in Signal:
  `/special add /dailypost /today; Photo of the day! /photo new` and
  `/special add /dailyquote Proverb or quote of the day: /fortune
  fortunes_svenska`. Before updating, remove the timers that run them, and
  add them again afterwards; or give the specials those names, and restart
  the bot once you have added them. Until then, the bot can't read those
  timers, which post nothing, and `/timers` doesn't list them.
- A special of your own that runs `/dailypost` or `/dailyquote` can't be read
  either, because specials can't run each other: give it their parts
  instead, before updating.
- An alias for `/dailypost` or `/dailyquote` in the configuration's
  `[aliases]` prevents the bot from starting: remove it before updating.

### Added

- `/today`, for everyone allowed: the weather, with the day's holidays above
  it, and in a group, the birthdays and name days of its members, as the
  daily post showed them. `/day`: the same without the weather, or "Nothing
  special today."
- `/photo new`, for everyone allowed: a photo not yet sent in the current
  round, as the daily post's photo was, never the same photo twice until
  every photo has been sent. `/photo` stays as it was, and doesn't count
  toward the round.
- In Swedish: `/idag`, `/dagen` and `/bild ny`.

### Changed

- `/dailypost preview` is now `/today preview`; in Swedish,
  `/idag förhandsvisa`.

### Removed

- `/dailypost` and `/dailyquote`, which specials of your own can replace
  (see Updating), and their Swedish names `/dagenspost`, `/dagensbild` and
  `/dagenscitat`.

### Fixed

- With a signal-cli-rest-api build from 2026-10-22 or later, the bot waited
  forever for its account at startup ("has no account … yet"), and
  `signal-account.sh` treated the account as unregistered: those builds list
  the accounts with their Signal IDs, as `{"number": …, "aci": …}`, instead
  of by number alone. Both now read either format.

## 0.99.9 - 2026-10-23

### Added

- `/contacts add` accepts a Signal username, as `u:alice.42` or `@alice.42`,
  for someone the bot doesn't know yet: signal-cli finds them by it, and
  knows their username from then on, so it is shown. Signal doesn't share
  usernames, so this is how the bot learns one.
- `/contacts` and `/trust` show the name someone gave themselves in Signal,
  their profile name, as `🪪 Alice Berg`, next to the one in the contacts
  where the two differ: saving someone in the contacts under a name used to
  hide it.

### Changed

- `/contacts <n>` shows the profile name, username and number on separate
  lines, as `/profile` shows the bot's: `🪪 Profile name: …`,
  `🔗 Username: @…`, `📞 Number: …`.

## 0.99.8 - 2026-10-21

### Added

- `/contacts` and `/trust` show each person's Signal username, as
  `@alice.42`, where signal-cli knows it, as `/contacts <n>` already did;
  elsewhere, a person without a known phone number is shown by name and
  username, as `Alice (@alice.42)`. Signal doesn't share usernames, so
  signal-cli knows only those of people it found by username.

## 0.99.7 - 2026-10-21

### Added

- The bot looks up the phone numbers on its lists that signal-cli can't
  match to a Signal ID, once each: at startup, and when `/allow` adds one.
  signal-cli knows someone who doesn't share their number in Signal only by
  their Signal ID, so their number on the allowed list could neither show
  their name nor match their direct messages, which arrive without it: the
  bot ignored those messages. Signal now says whose each number is, unless
  its owner has chosen not to be findable by number, and signal-cli keeps
  the number and the ID together.
- Once it knows a name, the bot writes it after the `#` of any line in
  `allowed.txt` and `admins.txt` that has none, so the files show who is
  who.

### Changed

- People are shown by name and phone number together where both are known,
  as `Alice (+46701234567)`, in `/allowed`, `/admins`, `/chats`, `/timers`,
  `/delete list`, `/delivery`, `/incoming`, and the replies of `/msg` and
  `/run`; where signal-cli has no name, by the name the allowed list has
  after their `#`, in `/chats` too.
- Timers, `/run` and specials can run commands that only show something,
  wherever the admins post them: `/delivery`, `/chats`, `/allowed`,
  `/admins`, `/incoming`, `/dailypost preview`, and `/timers` and
  `/specials` on their own. A timer at 08:15 can post `/delivery` to your
  own chat, for example. They still can't run commands that change timers,
  specials, birthdays or who may use the bot, that post to other chats, or
  that belong to each chat.
- `/run` runs its commands as the admin who sent it, instead of as the first
  admin in the configuration, so numbers in it are that admin's:
  `/run 1 /incoming 4,9` forwards messages 4 and 9 of their own `/incoming`
  list to chat 1.

### Fixed

- A `/delete list` posted by a timer, `/run` or a special replaced the
  numbers of the list that the first admin was shown last, so their next
  `/delete 3` could delete a different message from the one they saw as
  number 3. Such a list now leaves every admin's numbers as they were, and
  the same applies to `/incoming`.
- `/contacts` listed the bot's own safety number, under "Only a safety
  number", and `/contacts`, `/trust` and `/status` counted it as verified.

## 0.99.6 - 2026-10-21

### Updating

- The examples in `deploy/` pin a newer CI build of signal-cli-rest-api,
  `1792271041-ci` from 2026-10-17, still with signal-cli 0.14.9. Unlike the
  previous build, it doesn't drop what reaches a websocket while it is busy
  with the previous message, so `/delivery`'s counts are complete: put its
  digest in any Quadlets or Compose files you made from the examples.

### Added

- `/delivery`, for admins: whether the bot's latest messages arrived. It
  shows the `delivery_messages` (30) latest of the messages it sent in the
  last day, wherever they went, newest first, with how many people in each
  chat received and read each one, based on the delivery and read receipts
  that their phones send.
- A warning in the log for a message that nobody's phone has confirmed
  within 10 minutes: Signal accepted it, but it may not have arrived. At the
  DEBUG level, the log shows how many people each message had reached by
  then.

## 0.99.5 - 2026-10-19

### Changed

- `/status` names the bot's time zone, `timezone`, on a line of its own, and
  its times are shown without it: the next timer run no longer says `CEST`.

## 0.99.4 - 2026-10-19

### Added

- Admins in addition to those in the configuration: the configuration's
  admins can make someone an admin with `/admin add <who>`, and remove them
  with `/admin remove <n>`, by their number in `/admins`, which lists every
  admin. Added admins can use every command except these two, and no command
  can take away what the configuration's admins may do. They are stored by
  Signal ID, which, unlike a phone number, can't change hands, in
  `data_dir/admins.txt`, in the same way as the allowed list; the notices
  still go only to the configuration's admins.
- `/trust` on its own lists everyone's safety numbers, numbered as
  `/contacts` numbers them and laid out as the Signal apps show them, with
  whether each is verified; `/trust <who>` shows one person's.
- Backups: every day at `backups_at` (04:00), and at startup if the latest
  backup is a day old, the bot backs up what it stores in `data_dir`,
  together with its configuration file and the sample configuration, as
  `nejomibot-2026-10-19_0400.tar.zst`, into `data_dir/backups` or
  `backups_dir`, keeping the newest `backups_kept` (30). It makes no backup
  when nothing in the files has changed since the latest one, and
  `backups = false` turns backups off entirely. `/status` has a Backups
  check, and the health check pings say how many backups there are, how old
  the newest and oldest are, and when the last one was skipped because
  nothing had changed.
- Holidays for 33 more countries, by their codes in `holidays`, such as `GB`
  or `US`: the rest of the European Union, Norway, Iceland, Switzerland, the
  United Kingdom, the United States, Canada, Australia and New Zealand.
  These include their public holidays, Valentine's Day, Easter Sunday,
  Christmas Eve and New Year's Eve, Mother's Day and Father's Day where the
  whole country observes them on the same day, and some traditions of their
  own. Their names are in English, even in Swedish, except for the days
  they share with Sweden or Greece.

### Changed

- `/contacts` numbers everyone, and a number from it, or from `/trust`,
  stands for that person in `/contacts <who>`, `/contacts add`, `/trust`,
  `/allow` and `/admin add`: it refers to the list you were shown last, as
  with `/delete list`, until you request the list again.
- `/allowed` lists every admin, and `/chats` includes the added admins.

## 0.99.3 - 2026-10-19

### Changed

- Subcommands in the bot's language: in Swedish, `lägg till` for `add`,
  `ta bort` or `radera` for `remove`, `lista` for `list`, `töm` for `clear`,
  `kör` for `run`, `alla` for `all` and `förhandsvisa` for `preview`, as in
  `/lista lägg till mjölk` or `/timer ta bort 3`. `/hjälp` and the Swedish
  messages show them, and the English words work too.
- In Swedish, `/dailypost` is now `/dagenspost`; `/dagensbild` still works.

## 0.99.2 - 2026-10-19

### Added

- `/dailypost preview`, for admins in a direct chat: what the daily post
  will say above the weather on a given day, such as `/dailypost preview
  10-25`, `2026-10-25` or `tomorrow`, or today if no day is given, in each
  group the bot is in and in a direct chat, without posting anything else or
  using up a photo. In Swedish, `/dagensbild preview`.

### Changed

- Edits of commands that add or remove something now work: the edit
  replaces what it edits, which is undone first. Editing `/remind 18:00
  Cake` to `/remind 19:00 Cake` leaves a single reminder, at 19:00. This
  applies to `/remind`, `/list`, `/birthday`, `/nameday`, `/timer add` and
  `remove`, `/special add` and `remove`, `/allow`, `/disallow` and
  `/contacts add`. Edits of `/msg`, `/run`, `/timer run` and `/delete <n>`,
  whose posts and deletions can't be undone, aren't run, and the bot says
  so, as it does for an edit of a message from before a restart. The
  admins' own specials run again when edited, as `/dailypost` does.

## 0.99.1 - 2026-10-19

### Changed

- `/birthdays` and `/namedays` number the admins' list in the order shown,
  upcoming ones first, starting from 1. `/birthday remove` and `/nameday
  remove` use the numbers of the list the admin was shown last, as `/delete`
  and `/incoming` do: after a restart, request the list again first.
- `tools/release.sh` makes only patch releases for now: nejomibot stays on
  0.99.x until 1.0. A minor or major release stops with an error.

## 0.99.0 - 2026-10-19

### Updating

- For holidays in the daily post, set `holidays`, for example
  `holidays = ["SE", "GR"]`; see config.example.toml.

### Added

- Birthdays and name days in the daily post, above the weather, in the
  groups of the people they belong to: "🎂 Alice turns 36 today!", "🌸 Happy
  name day, Bob!". The admins manage them in a direct chat with the bot:
  `/birthday add 1990-03-14 Alice` for a contact, found as `/contacts` finds
  people and saved under a name, shown in the groups they are in under their
  name in the contacts; `/birthday add 1940-05-01 1 Grandma` for someone not
  on Signal, shown in the groups given by their numbers in `/chats`, or
  without them, in every group; `/nameday add 08-08 Alice`; and
  `/birthday remove 2`. They never show in a direct chat. `/birthdays` and
  `/namedays`, for everyone allowed, list them, upcoming ones first: in a
  group, that group's; for admins in a direct chat, all of them, numbered.
  They are stored in `data_dir/birthdays.txt`. In Swedish: `/födelsedag`,
  `/födelsedagar`, `/namnsdag` and `/namnsdagar`.
- `holidays`, empty by default: the daily post lists the day's holidays,
  flag days and traditions in these countries above the weather, `SE` for
  Sweden and `GR` for Greece, each after its flag: "🇸🇪 National Day of
  Sweden · flag day".
- `/remind`, for everyone allowed: a reminder that the bot posts once, in
  the chat, when it is due: `/remind 18:00 Take the cake out`,
  `/remind 30m Call Bob`, `/remind tomorrow 08:00 Pick up Bob`,
  `/remind fri 17:00 Pizza!`. `/remind` on its own lists the chat's
  reminders, and `/remind remove 2` removes one. They are stored in
  `data_dir/reminders.txt`. In Swedish, `/påminn`, and `om 30m`.
- `/list`, for everyone allowed: a list for each chat, for example for
  shopping: `/list add milk, eggs`, `/list remove 2,5`, `/list clear`. Lists
  are stored in `data_dir/lists.txt`. In Swedish, `/lista`.
- `/forecast` and `/forecast <city>`: the weather today and tomorrow, from
  OpenWeatherMap's forecast: each day's worst daytime weather, its lowest
  and highest temperatures, and its chance of rain or snow. Forecasts are
  kept for 30 minutes, and a named place counts toward
  `weather_calls_per_hour`. In Swedish, `/prognos`.
- `/onthisday`: a photo taken on this day in an earlier year, or failing
  that, within three days of it, under "3 years ago today". In Swedish,
  `/dennadag`.
- Notices to the admins, in a direct chat: after an update, the versions;
  after a stop that wasn't clean, that the bot is up again; when Signal
  starts rate-limiting the bot, how to lift the limit; and when someone's
  safety number changes, whose, because the bot can't send to them until
  the new number is trusted. The bot records which version ran last in
  `data_dir/run.json`.

### Changed

- `/weather` ends with the day's sunrise, sunset and daylight, in the
  place's own time: "🌅 07:35 · 🌇 17:21 · 9 h 46 min of daylight". So does
  the weather in the daily post.
- Timers, specials and `/run` now name the command they can't run: "Timers,
  specials and /run can't run /msg." They can't run `/remind`, `/list`,
  `/birthdays`, `/namedays`, `/birthday` or `/nameday` either.
- The bot's health check reports when Signal rate-limits the bot, and what
  lifts the limit, while messages are waiting.

## 0.98.0 - 2026-10-19

### Added

- A greeting for people on the allowed list who write to the bot in a
  direct chat without sending a command: "Hi, I'm Mybot, a bot. Try /help
  for a list of commands. Contact Alice for more information.", with the
  bot's profile name and the first admin's name as the bot's contacts have
  it. Each person is greeted at most once a day; commands are always
  answered as usual, never with the greeting.
- `/weather <city>`, such as `/weather Helsinki`: the weather in the place
  named, under a heading that names the place OpenWeatherMap found, in the
  bot's language where it has the name, with its state or region and
  country: "Weather in Springfield, Illinois, US". A country code selects
  among places with the same name: `/weather Stockholm,US`,
  `/weather Springfield,MO,US`. In Swedish, `/väder <ort>`.
- `weather_calls_per_hour`, 10 by default: the maximum number of requests
  the bot makes to OpenWeatherMap about named places in an hour, lookups
  included; beyond that, `/weather <city>` says when to try again.
  `weather_city` doesn't count, so `/weather` on its own and the daily post
  always get the weather.

### Changed

- The bot keeps each place's weather for 10 minutes, since OpenWeatherMap
  updates its data every 10 minutes: `/weather`, the daily post and
  `/status` answer from it when asked again sooner, without asking
  OpenWeatherMap.

## 0.97.1 - 2026-10-19

### Changed

- `/delete list` shows the bot's 50 latest messages instead of 20, and
  `/incoming` keeps and lists the 50 latest messages sent to the bot.
- `/delete` can delete several messages from the list at once:
  `/delete 2,5,11`. It stops at the first one it can't delete, for example
  when Signal can't be reached, and says which ones it didn't attempt.

## 0.97.0 - 2026-10-19

### Added

- `/delete list`, for admins in a direct chat: the bot's 20 latest
  messages, wherever it sent them, numbered, with when, where to and how
  each one begins. `/delete <n>` deletes one of them for everyone, and says
  which. The numbers refer to the list the admin was shown last.
- `/incoming`, for admins in a direct chat: the 20 latest messages that
  anyone other than the admins sent the bot in a direct chat, commands
  included, numbered, with when, from whom and how each one begins;
  `/incoming 4,9` forwards those two to the admin in full, as text only,
  since the bot doesn't download attachments. They are kept in memory only,
  and are removed when their sender deletes them or when they disappear. In
  Swedish, `/inkorg`. Timers and `/run` can't run it.

### Changed

- `/help` shows the names that some commands have always had, `/test` for
  `/status`, `/time` for `/info` and `/safety` for `/contacts`, after the
  commands, as it shows the configuration's aliases, which appear on a
  command's first line only. These names are now aliases, so the
  configuration's aliases take precedence over them, as over the language's
  names: previously, a configuration that used one of them as an alias
  stopped the bot.
- The weather's heading, "Weather in Stockholm", is in bold, in `/weather`
  and the daily post; the explanation of a proverb in `fortunes_svenska`,
  the paragraph below it, is in italics, in `/fortune` and `/dailyquote`.

## 0.96.0 - 2026-10-18

### Added

- `fortune_library`, the library `/fortune` uses when none is named:
  `fortunes_svenska` if it isn't set, as before, another library that
  `/fortune list` lists, or `all` for every library. `/dailyquote` keeps
  using `fortunes_svenska`.

## 0.95.0 - 2026-10-18

### Updating

- The texts in `data_dir/specials.txt` are now in signal-cli-rest-api's
  formatting marks: a `*`, `~` or `` ` `` typed in a special before this
  version now formats the text, or disappears. Put a `\` before each one in
  the file, or add the special again with `/special add`.

### Added

- Your own specials keep the formatting you give their text in Signal:
  bold, italic, strikethrough, monospace and spoiler. The file stores it as
  marks, such as `**bold**`, which can also be written by hand. The bot
  rejects the few combinations that signal-cli-rest-api can't send, such as
  bold and italic that meet inside a word, and says so.

### Changed

- "Photo of the day!", the daily post's caption, and "Proverb or quote of
  the day:", the daily quote's heading, are in bold.

## 0.94.1 - 2026-10-18

### Fixed

- 0.94.0's images were all built for amd64, yet labeled amd64, arm64 and
  arm/v7, each with arm/v7's variant: Podman and Docker on amd64 found no
  image for themselves, and on ARM they would get one that can't run. The
  release built them with Podman 4.9, which mixes up platforms when a build
  stage names its own platform, as the Dockerfile's uv stage does. Releases
  are now built with Podman 5, and `tools/build-image.sh` runs each image
  before it pushes any, and stops unless each one runs as its platform. If
  you pulled 0.94.0, or `latest` while it was 0.94.0, pull this version.

## 0.94.0 - 2026-10-18

### Added

- The image is also built for linux/arm/v7, as signal-cli-rest-api is, so
  the bot runs on 32-bit ARM, such as older Raspberry Pis. Pillow and
  pillow-heif have no wheels for that platform, so its image builds them
  against Debian's libraries, which makes the release build take longer; CI
  still builds linux/amd64 only.
- The pings to `healthcheck_url` say what is running, as `/status` does,
  below how each check went: the versions of nejomibot, signalbot, Python
  and signal-cli-rest-api, how long the bot, and therefore its container,
  has been up, and the bot's memory use, with its peak and the container's
  limit. They are sent as `text/plain; charset=utf-8`. signal-cli's version
  isn't known, because signal-cli-rest-api doesn't report it.
- A step-by-step setup guide, from nothing to the daily post: the README's
  Getting started, and [DOCKERHUB.md](DOCKERHUB.md), the same guide for the
  image's page on Docker Hub, which each release now publishes there, along
  with the repository's description.
- Every image a release pushes, to ghcr.io and Docker Hub, has signed build
  provenance: which workflow built it, and from which commit.
  `gh attestation verify oci://docker.io/jodab/nejomibot:VERSION --repo jodab/nejomibot`
  checks it.

### Changed

- The examples in `deploy/` run the published image,
  `docker.io/jodab/nejomibot:latest`, instead of `localhost/nejomibot:latest`
  built on the machine. To run your own build, set `Image=` in
  `nejomibot.container`, or `image:` in `compose.yaml`, back to
  `localhost/nejomibot:latest`.
- The bot doesn't start unless it can write to `data_dir`, and says why:
  previously, it ran without saving what it was told. If it stops with
  `Can't write in data_dir`, give the folder to the bot's user, UID 1001
  (step 3 of Getting started).

### Fixed

- A configuration file the bot can't read stops it with `Can't read the
  config file`, and the reason, such as a folder it can't open. Previously,
  it said the file didn't exist and carried on without it, so settings in
  the file seemed to be missing.

## 0.93.5 - 2026-10-18

### Added

- `tools/release.sh patch|minor|major` makes a release: it raises the
  version, dates the changelog, commits, tags and pushes the result, and
  publishes the release on GitHub, which builds and pushes the image. It
  releases only what CI has passed, and can be run again after a failure.

## 0.93.4 - 2026-10-18

### Added

- Releases also publish the image to Docker Hub, as
  `docker.io/USER/nejomibot`, when the repository has the variable
  `DOCKERHUB_USERNAME` and the secret `DOCKERHUB_TOKEN`.
  `tools/build-image.sh` accepts `--push` more than once, building once for
  each registry.

## 0.93.2 - 2026-10-18

### Added

- `LICENSES/fortune-mod.txt`: fortune-mod's license, which covers the
  fortune libraries taken from it.

### Fixed

- The README, the Dockerfile and `deploy/signal.container` said that the
  containers' health checks run every 20 seconds; they run every minute.

## 0.93.1 - 2026-10-18

### Changed

- CI builds the image for linux/amd64 only; releases still build both
  platforms. `tools/build-image.sh --platforms LIST` selects what it builds.

## 0.93.0 - 2026-10-18

### Updating

- `tools/timers.sh` has been removed: `nejomibot-timers`, in the image, does
  what it did, using the bot's own code: `podman exec nejomibot
  nejomibot-timers`, `... chats`, `... add "08:00" 1,2 /dailypost`,
  `... remove 3`.
- The image's group is now 1001, the same as its user (it was 999). With
  Podman's `:U`, or `UserNS=keep-id:uid=1001,gid=1001`, there is nothing to
  do.
- The deploy examples now drop every capability, forbid new privileges, run
  with a read-only file system and an init process, and pin
  signal-cli-rest-api's CI build by digest: copy those lines to any
  Quadlets or Compose files you made from them.
- The log looks different: each line has the date, the level and the part
  of the bot it comes from, and says which command ran and in what kind of
  chat, but not who sent it or anything else; `log_level = "DEBUG"` shows
  the rest.
- New settings, all optional: `log_level`, `photos_map` and `photos_heif`
  (see config.example.toml).
- The bot no longer responds to the plain words `weather`, `info`, `väder`
  and `vader`: to keep one, add it to the configuration's aliases, for
  example `"/weather" = ["weather"]`.

### Added

- `/dailyquote`, the daily quote, as `/dailypost` is the daily post: a
  proverb or quote from `fortunes_svenska`, under the heading "Proverb or
  quote of the day:" (`/dagenscitat` in Swedish).
- The admins' own specials: commands that post text and the answers of
  other commands, always in the same order, such as `/special add /morning
  Good morning! /weather; /dailyquote`, for timers, `/run` and the admins.
  `/specials` lists them; they are stored in `data_dir/specials.txt`.
- Messages waiting to be sent survive a restart: a message that has waited
  for half a minute is saved in `data_dir/outbox`, and all waiting messages
  are saved when the bot stops.
- `/msg` and `/run` say where a message is only waiting to be sent, or may
  not have arrived.
- `photos_map = "openstreetmap"`: captions link to OpenStreetMap, with its
  short links.
- `photos_heif = false` leaves HEIC/HEIF photos out, which saves about 3 MB
  of memory.
- `log_level`, for how much the bot logs.
- `nejomibot-timers`, for managing the timers from a terminal.
- On GitHub: CI, a release workflow that publishes the image to ghcr.io when
  a release is published, and Dependabot.

### Changed

- `fortunes_svenska`, the library `/fortune` uses by default, now has 1,000
  proverbs and quotes in Swedish instead of jokes translated from
  fortune-mod's `fortunes`: Swedish proverbs and wellerisms, Greek proverbs
  from Delphi to the present day, proverbs from other countries, and quotes
  from writers long dead, with a line explaining the less familiar ones.
  `fortunes` is still available, in English.
- The weather is requested by the city's coordinates, which OpenWeatherMap's
  geocoding provides once, since OpenWeatherMap has deprecated requests by
  city name.
- The exchange rate comes from ExchangeRate-API's current open endpoint,
  and its errors say what went wrong.
- While Signal rate-limits the bot, waiting messages are retried every half
  hour instead of every two minutes, until a message goes through.
- The example date in `/help` and in the `/timer` usage text is always in
  the future.
- The image is smaller, 232 MB instead of 323 MB: it contains neither uv nor
  a second copy of the code, and has phonenumberslite instead of
  phonenumbers, without the 41 MB of place names, carriers and time zones
  that signalbot never reads. Its base images are pinned by digest.
- The containers' health checks: the image's check runs every minute, and
  three failures in a row mark the container as unhealthy, instead of a
  single failure every five minutes. The Quadlets have Podman kill an
  unhealthy container, for systemd to start again (`HealthOnFailure=kill`),
  and signal.container checks signal-cli itself, not just the REST API in
  front of it.
- The bot uses less memory: fortunes aren't kept in memory once used, EXIF
  data is read by Pillow, without exifread, and HEIF support is loaded only
  when first needed.
- The translations are compiled when the image is built, not at every
  start; polib is no longer in the image.
- The files in `data_dir` are synced to disk before they replace the old
  ones.
- Debug mode keeps its files in a private temporary folder, created anew at
  each start.
- Editing `/allowed` runs it again, as for other commands that only show
  something; `/allow` and `/disallow` still require a new message.
- Timers, specials and `/run` say that they can't *manage* timers, specials
  or who may use the bot, rather than *change* them, since that also covers
  `/chats` and `/allowed`, which only list.
- signalbot 2.1.0, Pillow 13.0 (with security fixes), pydantic 2.14 and
  pydantic-settings 2.16.

### Removed

- The plain words `weather` and `info` (and in Swedish, `väder` and
  `vader`) for `/weather` and `/info`: the bot's own command names all start
  with `/`. Aliases in the configuration can still be plain words.

### Fixed

- The OpenWeatherMap API key could end up in a chat and in the log, through
  the text of some network errors, which contains the URL.
- The health checks, and the checks for changes to the timers, were skipped
  when the bot was a moment late, and two skipped health checks restarted
  the container.
- Two daily posts at the same moment could pick the same photo.
- A new timer could take the number of a line in the timers file that the
  bot couldn't read.
- The list of sent photos is now UTF-8, and readable only by the bot's
  user, like the other files.
- `/contacts` on an account that knows many people: profiles are requested
  four at a time, at most fifty per command, and lookups no longer slow down
  as the account grows.
- When the bot stops, its own background work stops too, and the waiting
  messages are kept.

### Security

- At the default log level, the log contains no phone numbers, group IDs or
  message text.
- `signal-account.sh` warns before linking signal-cli to a phone: the bot
  would then treat commands typed on that phone as coming from the other
  person.

## 0.92.0 - 2026-10-17

### Updating

- The bot is now a container image, for x86 and ARM, with `config.toml` in
  its data folder: `/data/config.toml`. `deploy/` has Quadlet and Compose
  examples; `deploy.sh`, the git hook, the pod and its network have been
  removed.
- Settings: `phone_number` is now `account`, and `status_contacts` is now
  `admins`; `allowed_contacts`, `allowed_groups`, `signal_cli_daemon` and
  `signal_one_request_at_a_time` have been removed (who may use the bot is
  now the allowed list, managed with `/allow`); `signal_service` is
  required. The bot says which setting is wrong, and won't start until the
  configuration matches `config.example.toml`.
- signal-cli-rest-api must be a build newer than 0.101.

### Added

- `/msg` and `/run` post a message, or the answers of commands, to other
  chats.
- Health checks every `healthcheck_minutes`, pinged to `healthcheck_url`,
  and the image's own health check.
- `/status` shows the versions of nejomibot, signalbot and
  signal-cli-rest-api.

### Removed

- `/forget`, `/contacts remove` and `/emoji`, because signal-cli-rest-api
  can't support them.
