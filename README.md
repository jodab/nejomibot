# DISCLAIMER
This project was created as a playground for teaching myself how to better use Claude Code, so everything you see here is entirely AI coded under my guidance.

# nejomibot

A Signal bot for a family or a group of friends. Every morning it can post
the weather and a photo from your photo library to a few Signal groups, and
it answers a handful of commands. It speaks English or Swedish, and other
languages once they're translated.

It talks to Signal through
[signalbot](https://pypi.org/project/signalbot/), and so through
[signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)
in json-rpc mode. It comes as a container image, for x86 and ARM; see
[Running it](#running-it).

## Commands

The everyday commands, for everyone the bot may talk to:

| Command | Reply |
|---|---|
| `/photo` | A random photo with the date it was taken, an age if set, and a map link |
| `/cache` | Number and size of photos in the library |
| `/weather` | Current weather in `weather_city` |
| `/info`, `/time` | The time in the places in `clocks`, and the `exchange_rate` |
| `/ping` | `pong!` and how long the ping took to arrive |
| `/fortune`, `/fortune <library>`, `/fortune all`, `/fortune list` | A random fortune, from `fortunes_svenska`, the library named, or every library; `list` names them |
| `/help` | The commands the asker may use, a line each |

For the admins, in a direct chat with the bot:

| Command | Reply |
|---|---|
| `/status`, `/test` | Health check, in two messages: the checks, failed ones first, then the details: the bot and its versions, Signal, public IPs and ASN, container, host |
| `/dailypost` | The daily post, as a timer posts it: the weather, then the photo of the day (it uses up a photo of the round) |
| `/dailyquote` | The daily quote, as a timer posts it: a proverb or quote from `fortunes_svenska`, headed "Proverb or quote of the day:" |
| `/contacts`, `/safety`, `/contacts <who>` | Everyone the Signal account knows, two short lines each, and whether they're verified; with `<who>`, one in full, with their safety number |
| `/contacts add <who> <name>` | Make someone a contact by that name, or rename them; `<who>` is their phone number, ID or the start of it, or their name: the longest start of the message that names someone. Someone the bot doesn't know yet can be added by phone number |
| `/trust <name, number or ID> <safety number>` | Mark a safety number as verified, after comparing it with the one on their phone |
| `/allowed` | Who may use the everyday commands, numbered |
| `/allow <who>` | Let someone use them, or everyone in a group, there |
| `/disallow <n>` | Take that away again, by the number in `/allowed` (or by phone number, ID or name) |
| `/profile` | The bot's Signal profile: name, About, username, avatar |
| `/name <name>` | Change the bot's name |
| `/about <text>`, `/about remove` | The About text under its name |
| `/avatar` with a picture, `/avatar remove` | Its profile picture: send the picture with `/avatar` as its caption |
| `/username <name>`, `/username remove` | Its username, and a link that starts a chat with it |
| `/timers` | The timers: commands the bot runs on a schedule, such as the daily post |
| `/chats` | Where timers, `/msg` and `/run` can post, numbered |
| `/timer add <when> [<chats>] <commands>` | A new timer, e.g. `/timer add mon-fri 07:30 1,2 /dailypost` |
| `/timer remove <n>`, `/timer run <n>` | Remove a timer, or run it now |
| `/specials` | The [specials](#specials) of your own: commands that post text and what other commands answer |
| `/special add <name> <parts>` | A new special, or a change to one, e.g. `/special add /morning Good morning! /weather; /dailyquote` |
| `/special remove <name>` | Remove a special, unless a timer runs it |
| `/msg <chats> <text>` | Post the text to other chats, e.g. `/msg 1,2 Hello!` |
| `/run <chats> <commands>` | Run commands and post their answers to other chats, e.g. `/run 1 /status` |

And for the admins in any chat, groups too:

| Command | Reply |
|---|---|
| `/delete` | Delete the bot's latest message in the chat, for everyone; sent again, the one before, and so on |

A command can have other names: aliases from the configuration, and the
names in the bot's language (see [Languages](#languages)). With
`language = "sv"`, `/väder` is `/weather`, `/hjälp` is `/help`,
`/dagensbild` is `/dailypost` and `/dagenscitat` is `/dailyquote`; `/help`
shows every name a command has.

### Who may use what

The admins, `admins` in the configuration, may use every command: the
everyday ones wherever they're allowed, the admin commands only in a direct
chat with the bot, as they show phone numbers and the server's addresses, or
change the bot. An admin is given by phone number, or by Signal ID for one who
doesn't share their number. Everyone else may use the everyday commands if
they're on the [allowed list](#the-allowed-list): a contact, in a direct chat
with the bot, or a group, where everyone in it may use them, there. The bot
answers nobody else.

Admins are only ever set in the configuration, so no command can take away
what an admin may do, or make someone an admin.

People who don't share their phone number on Signal are known only by their
ID. signal-cli-rest-api has no way to take someone out of the contacts, or to
forget them, so the bot can't either.

It marks each command as read, in groups as well as direct chats, and shows
itself typing while it works on the slower ones. Both are best effort: if they
fail, the answer still comes. Editing a message runs its command again, except
for those that change things or post elsewhere: `/delete`, `/contacts add`,
`/allow`, `/disallow`, `/timer`, `/special`, `/msg`, `/run` and the specials
of your own.

The bot needs a number of its own, registered for it. If its number is also
signed in on a phone, as when signal-cli is linked to that phone, a command
typed on the phone in a direct chat looks to the bot as if the other person
sent it (signalbot can't tell them apart), so the admin commands would act on
it as theirs. [signal-account.sh](#setting-up-and-managing-the-signal-account)
warns before it links.

`/delete` works in every chat the bot is in, groups included, but only for
the admins; from anyone else it's ignored. It deletes the bot's latest
message in that chat for everyone, then the one before on the next
`/delete`, and so on. It posts nothing when it works, as anything it posted
would be the next to go; it only answers when there's nothing left to delete,
or when the delete failed (that message is kept, to try again). Signal only
deletes messages for everyone within a day of sending them, so the bot
remembers what it sent for a day, in memory: after a restart, `/delete` only
reaches what was sent since.

When something fails (the weather API, the exchange rate, the photo library),
the bot posts the error as `Something went wrong: ...` instead of staying
silent, in the daily post too.

When a message can't be sent, because signal-cli-rest-api is down or the server
has no internet, it is tried again for `send_retry_hours` (3 by default), with a
note that it's late: after 10 seconds, then less and less often, every two
minutes at most, and right away whenever another message goes to the same chat,
as that usually means Signal is back. While Signal rate-limits the bot, the
waiting messages are tried every half hour instead, as trying more often can
keep the limit in place, until a message goes out. Each chat gets its messages
in order. Older messages are dropped, and the chat is told how many once
sending works again. Only failures where the message surely wasn't sent are
retried: signal-cli-rest-api couldn't be reached, or answered with an error,
which it does when no recipient got the message, when Signal rate-limits the
bot, or when the request itself was wrong. A timeout or a dropped connection
may come after Signal got the message, so those are only logged, as a retry
would post it twice. `/status` shows how many messages are waiting.

Waiting messages outlast a restart: one that has waited half a minute is kept
in `data_dir/outbox`, a file each, until it's sent or dropped, and every one
waiting is kept as the bot stops. Once it's started again, the bot sends them,
still with the note that they're late. A short wait, as while
signal-cli-rest-api restarts, writes nothing.

### Photos and the daily post

`/dailypost` is the daily post: the weather, then the photo of the day,
captioned "Photo of the day!". It's for timers: `/timer add 08:00 1,2
/dailypost` posts it at 08:00 in the bot's `timezone`, whatever the server's
own time zone, to chats 1 and 2 of `/chats`. It sends the same weather and the
same photo to every chat. The photo is picked at random among those it hasn't
sent yet in this round; once every photo has been sent, a new round starts.
Besides timers, only the admins may run it, in a direct chat, as each run uses
a photo up. `/photo` picks from all photos and doesn't count toward the
round.
The sent photos are listed in `data_dir/sent-photos.txt` (a temp file in
debug mode), so rounds survive restarts; deleting the file starts over.
JPEG and the other formats are sent as they are; HEIC/HEIF photos are
converted to JPEG on the fly with a warning in the log, since not every Signal
client shows them. Better convert them for good with
[tools/tidy-photos.sh](tools/tidy-photos.sh); then `photos_heif = false`
leaves HEIC/HEIF out of the library, and saves the 3 MB or so of memory it
takes to open them.

The caption gives the time the photo was taken in the bot's `timezone`,
wherever it was taken. The EXIF DateTimeOriginal is the time on the clock
there, in the zone of the offset saved with it; without one, the photo is
taken to be from `photos_timezone` (the bot's `timezone` if not set). But some
phones save DateTimeOriginal in UTC and CreateDate in local time, whatever
offset they give: a CreateDate a time zone away tells, as in tidy-photos.sh.
(tidy-photos.sh names the files after the local time, so a caption can be an
hour or two off the file name.) With `photos_birth_date`, the caption also
gives the age of who's in the photos on the day, after `photos_age_emoji`.
A photo with a GPS position links to where it was taken: on Google Maps, or
with `photos_map = "openstreetmap"`, OpenStreetMap's short link, such as
`https://osm.org/go/0bC2KJ9q?m=`, which shows a marker there.

### /status

`/status` answers in two messages, to fit Signal's narrow bubbles. The first
has the checks: how many passed (`✅ All 12 checks passed`, or `❌ 2 of 12
checks failed`), the failed ones with what went wrong, then the rest, a short
line each; a check that took a second or more says how long. The second has
the details, a section each, in short lines:

- **Bot:** the versions of nejomibot, signalbot, Python and
  signal-cli-rest-api, uptime, the next timer run, messages waiting to be sent
  again, how long the command took to arrive. signal-cli's version isn't
  there: signal-cli-rest-api doesn't say it.
- **Signal account:** number and profile, contacts and who's blocked, safety
  numbers (naming those new or changed in the last week), groups, and linked
  devices.
- **Internet:** the public IPv4 and IPv6 address (from Cloudflare's
  `/cdn-cgi/trace`, asked over each), its reverse DNS name, and from
  [RIPEstat](https://stat.ripe.net/) the ASN, its holder, the announced prefix and
  the city. `IPv6 none (...)` means the container has no IPv6 route, even if the
  host has one.
- **Container:** threads, open files, CPU time, local IPs and DNS servers.
- **Host:** hardware, CPU, kernel, uptime, load, pressure (share of the last minute
  tasks waited for CPU, memory or IO), memory, swap, and CPU and NVMe
  temperatures. Read from `/proc` and `/sys`, which show the whole machine, so it
  works in the unprivileged container and still describes the server.

The checks, all live: the three [health checks](#health-checks)
(signal-cli-rest-api, the bot itself, and Signal's servers with the account),
then that every safety number is trusted, nobody the bot talks to is blocked,
the bot is still in every group on the allowed list, OpenWeatherMap and the
exchange rate API (if `exchange_rate` is set) answer, the photo library isn't
empty, disk and memory use are under 90% of their limits, and NTP keeps the
clock synchronized. A check that takes more than 20 seconds fails.

## Posting to other chats

`/msg` and `/run` let an admin post to other chats from a direct chat with the
bot, to the chats numbered by `/chats`, given as one word, like `1,2`:

```
/chats                                 where they can post, numbered
/msg 1,2 Dinner at six!                the text, to chats 1 and 2
/run 1 /status                         the status, in chat 1
/run 1,3 /weather; /photo              the weather, then a photo
```

`/msg` posts the text as the bot. `/run` runs each command as a timer does, as
an admin would in a direct chat with the bot, and posts its answers to the
chats, one command after the other; every chat gets the same photo. Like a
timer, `/run` can't manage timers, specials or who may use the bot, nor run
`/msg` or `/run`. Mind what goes where: `/status` shows phone numbers and the
server's addresses to everyone in the chat. Both answer with where they
posted, and where it only waits to be sent (see
[Who may use what](#who-may-use-what)) or may not have arrived; `/run`
posting to the admin's own chat speaks for itself.

## The allowed list

Who may use the everyday commands, besides the admins, is a list the admins
change from a direct chat with the bot:

```
/allowed                  who's on it, numbered, and the admins
/allow +46701234567       a phone number
/allow Alice              someone in /contacts, by name or the start of their ID
/allow Family             a group the bot is in, by name, or by its group ID
/disallow 3               by its number in /allowed, or its number, ID or name
```

The list is kept in `data_dir/allowed.txt`, a phone number, Signal ID or
group ID a line, and after a `#` who that is:

```
group.abcd…=  # Family
+46701234567  # Alice
```

It can be changed by hand too: the bot looks for changes every couple of
seconds, and leaves comments and lines it can't read as they are (`/allowed`
names those). It's written through a temp file, so the bot never reads half
of it, and only the bot's user may read it, as it lists phone numbers. The
bot starts the file, empty, the first time it runs; deleting it starts it
anew.

What the commands won't do: allow the bot itself, allow someone twice, or
disallow an admin, who are in the configuration and keep every command
whatever the list says. `/disallow` on a group says which timers still post
there, as timers post to their chats whoever may use the bot.

## Timers

A timer runs bot commands on a schedule, and posts what they answer to one or
more chats; the daily post is one. The admins manage them in a direct chat
with the bot:

```
/chats                                     where timers can post, numbered
/timer add 08:00 1,2 /dailypost            the daily post, to chats 1 and 2
/timer add 08:05 1 /dailyquote             the daily quote, to chat 1
/timer add mon-fri 07:30 1 /weather; /info to chat 1
/timer add tomorrow 18:00 1 /photo         once
/timer add every 2h /status                without chats, to you
/timers                                    the timers, with their next run
/timer remove 3
/timer run 3                               now, to try it
```

`/chats` numbers the groups the bot is in, by name, then the people on the
allowed list, then the admins, so a timer's chats are a few numbers, easy to
type on a phone. `<when>` is a time (`08:00`, or `08:00,18:30`), days and a
time (`mon-fri 07:30`, `sat,sun 10:00`, `weekdays`, `weekends`), a date and
a time for once (`YYYY-MM-DD 15:00`, `tomorrow 08:00`), or `every 2h` (every
10 minutes at most), in the bot's `timezone`. The bot's language may add its
own words: in Swedish `mån-fre`, `vardagar`, `helger`, `imorgon`, `varje 2h`.
The commands, each with its `/`, are separated by `;`.

A timer runs each command once, as an admin would in a direct chat with the
bot, so it can run any command but those that manage timers, specials or the
allowed list, or post to other chats themselves (`/msg`, `/run`), and posts
its answers to all the timer's chats before the next command runs: every chat
gets the same photo. It can run [specials](#specials) of your own too.

Timers are kept in `data_dir/timers.txt`, a line each, its fields
separated by `|`: the timer's number, when, its chats (group IDs and phone
numbers, so only the bot's user may read the file), its commands by their
English names, and when it last ran, or was added:

```
1 | daily 08:00 | group.abcd… group.efgh… | /dailypost | 2026-10-13 08:00:01+02:00
```

The bot rereads the file within half a minute of a change, so it can be
changed while the bot runs: with `/timer`, by hand, or with `nejomibot-timers`,
which lists, adds and removes timers from a terminal, through the bot's own
code, so it takes what `/timer` takes and numbers the chats as `/chats`
does. It's in the bot's image:

```sh
podman exec nejomibot nejomibot-timers                     # the timers
podman exec nejomibot nejomibot-timers chats
podman exec nejomibot nejomibot-timers add "08:00" 1,2 /dailypost
podman exec nejomibot nejomibot-timers --dry-run remove 3
```

Its chats are numbers from `chats`, or group IDs, phone numbers and Signal
IDs. It reads the bot's configuration as the bot does; outside the container,
`uv run nejomibot-timers` in the bot's folder.

A line the bot can't read, such as one with a command it doesn't know, is
left as it is, and logged. A run due while the bot was down is made when it
starts again, up to an hour late, as long as it's later than the timer's last
run; a timer for a date goes once it has run. Without a timers file the bot
starts with none.

## Specials

A special posts several things in one go, always in the same order: text,
and what other commands answer. Two come with the bot: `/dailypost`, the
[daily post](#photos-and-the-daily-post), and `/dailyquote`, a proverb or
quote from `fortunes_svenska`, headed "Proverb or quote of the day:". The
admins make their own in a direct chat with the bot, mostly for timers:

```
/special add /morning Good morning! /weather; /dailyquote
/special add /bins The bins go out tonight!
/specials                                  the specials of your own
/timer add tue 18:00 1 /bins               a reminder, every Tuesday
/special remove /bins
```

A special's parts are separated by `;` or line breaks. Text before a command
heads what the command answers, in the same message, a blank line between:
`Good morning! /weather` posts the weather under "Good morning!". Text alone
is a message of its own. The name is a word that starts with `/`, and isn't
a command or an alias; `/special add` with the name of one you have changes
it. A special has up to five parts.

A special runs its commands as a timer does, as an admin would in a direct
chat with the bot, and posts what they answer one after the other: it can
have any command a timer can, `/dailypost` and `/dailyquote` too, but not
another special of your own. Like those two, specials are for timers, `/run`
and the admins in a direct chat. Editing a message doesn't run a special of
your own again, as its commands may change something. A special a timer runs
can be changed, but not removed: remove the timer first.

The specials of your own are kept in `data_dir/specials.txt`, a line each:
the name, a `|`, and the parts, their commands by their English names:

```
/morning | Good morning! /weather; /dailyquote
```

The bot reads the file again when it changes, so it can be changed by hand
too, and leaves comments and lines it can't read as they are; `/specials`
lists those.

## Languages

The bot's messages are written in English. `language` in the configuration
picks a translation from [nejomibot/locale](nejomibot/locale):

- `sv.po` translates the messages, in gettext's format, which translation
  tools such as Poedit read. Untranslated messages show in English.
- `sv.toml` has the language's names for commands, like the aliases in the
  configuration, and its words for days and times in `/timer add`.

Day and month names come from the translations too, so the bot needs no
locales installed. The fortune libraries aren't translated: each is in its own
language.

After changing the bot's messages, [tools/translations.sh](tools/translations.sh)
(GNU gettext) brings every `.po` file up to date: new messages come in
untranslated, changed ones marked fuzzy. Translate those, and the tests check
that every message is translated, with the same `{fields}`. For a new
language, `tools/translations.sh de` starts `de.po`; copy `sv.toml` to
`de.toml` for its names.

The image has the translations compiled, once, as it's built: `sv.mo`, which
the bot reads with Python's own gettext, in place of `sv.po`. Run from a
checkout, without `.mo` files, it reads the `.po` files themselves, with
polib, which only development needs.

### Aliases

Other names for commands go in the configuration, as a table at its end:

```toml
[aliases]
"/photo" = ["/pic", "pic"]
"/dailypost" = ["/morning"]
```

A message that starts with an alias is taken as if it started with its
command: `pic` sends a photo, `/f startrek` with `"/fortune" = ["/f"]` a
Star Trek fortune. An alias is one word, with or without `/`; without one,
like `pic`, it's taken from anyone allowed who writes just that word. The
bot's own names for commands, in English or its language, all start with `/`.
An alias can't be a command's own name, and the bot won't start with an
alias for a command it doesn't have. The configuration's aliases win over the
language's.

## The bot's profile

The admins change the bot's Signal profile from a direct chat with it:

- `/name Mybot` sets the name. signal-cli-rest-api can only set the given
  name, so a family name, if the profile has one, stays after it.
- `/about Weather and photos every morning` sets the About text under the
  name; `remove` clears it. An emoji before it stays as it is: the bot can't
  set it.
- `/avatar`, as the caption of a picture, makes it the profile picture:
  upright, its middle square, at most 1024×1024 as Signal's Android app makes
  them, without the photo's metadata such as where it was taken. It's a JPEG,
  or a PNG when the picture has see-through parts, as a logo may.
  `/avatar remove` removes it.
- `/username mybot` sets a username. Signal adds a number to it, as in
  `mybot.42`, unless one is given. The answer has a link that starts a chat
  with the bot without its phone number. `/username remove` removes it.
- `/profile` shows it all; each command alone shows what it's set to now.

The limits are those of Signal's apps: a name of up to 128 bytes (letters such
as å take two, emoji four) and an About of up to 140 characters.

signal-cli-rest-api sets the profile as a whole, and removes the avatar unless
the picture is sent along every time, so `/name` and `/about` send the current
one back. When Signal turns a username down, signal-cli-rest-api doesn't say
why; most likely it's taken. For `/avatar`, the bot fetches the picture from
signal-cli-rest-api, and deletes it there once it's the avatar. That needs
signal-cli to keep the pictures sent to the bot, which it doesn't with
`JSON_RPC_IGNORE_ATTACHMENTS=true` (then the bot says so); the account tool
below sets the avatar from a file instead.

## Health checks

Every `healthcheck_minutes` (5 by default), and as soon as signalbot is ready
after a start, the bot checks its health:

- **signal-cli-rest-api:** it answers, through signalbot, in json-rpc mode,
  and is later than 0.101 (see
  [Which signal-cli-rest-api](#which-signal-cli-rest-api)).
- **The bot:** signalbot has started, which it does once signal-cli-rest-api
  has the account, and no message has waited more than 15 minutes to be sent.
- **Signal:** Signal's servers answer for the account: the bot asks
  signal-cli-rest-api for the account's linked devices, which signal-cli asks
  Signal for. That's the one thing a health check asks of Signal.

A failed check is logged, saying what failed, and `/status` starts with the
same three checks. To be warned, set `healthcheck_url`, such as a check's
ping URL at [healthchecks.io](https://healthchecks.io)
(`https://hc-ping.com/<uuid>`): the bot pings the URL after each check when
all passed, or the URL with `/fail`, with what failed. The service warns
either way you set it to: when a ping says something failed, or when the
pings stop, as they do when the bot is down. Set the check's period to
`healthcheck_minutes`, and give it some grace.

### The containers' health checks

A container's health check asks something else: whether it works, so
whether restarting it could help. With the [Quadlets](#podman-quadlets),
Podman restarts a container whose check fails three times running.

- **The bot's**, in its image: the bot answers within 5 seconds, and the
  checks above run on time, as they don't when it's stuck. What they find
  doesn't count: when Signal or signal-cli-rest-api fails, restarting the bot
  wouldn't help, and could lose the messages that have waited less than half
  a minute, which aren't on disk yet. Nor does waiting for
  signal-cli-rest-api or the account, so a new install isn't restarted while
  the account is set up in its container.
  `podman exec nejomibot nejomibot-healthcheck` says what it found, and how
  the latest check above went. The bot answers over a socket in Linux's
  abstract namespace, which is no file, so nothing is written to disk.
- **signal-cli-rest-api's**: its image's only asks the REST API, which
  answers while signal-cli behind it is stuck, so the Quadlet has it ask
  signal-cli for the accounts instead. That asks nothing of Signal's
  servers.

Both run every minute. Podman checks once as a container starts, before the
bot answers, and then a minute later, so the bot shows `(starting)` in
`podman ps` for a minute; failures in the first minute don't count. Three
failures running, two to three minutes, make a container `(unhealthy)`. The
image can't say what happens then: with `HealthOnFailure=kill` in each
Quadlet, Podman kills the container, and systemd starts it again
(`Restart=always`, after `RestartSec=10`), and the bot with
signal-cli-rest-api. From when a container stops working to when it works
again takes about three minutes. Docker doesn't restart unhealthy
containers; `docker compose ps` only shows them.

A Quadlet can change any of the bot's settings, such as `HealthInterval=` or
`HealthRetries=`, and the rest stay as in the image; but a `HealthCmd=`
drops the image's interval, timeout, retries and start period for Podman's
own, so signal.container gives its own interval. Each check is a line in
the system journal, Podman's `health_status` event (`healthcheck_events =
false` in containers.conf turns them off), and signal-cli-rest-api's log has
a line for each of its checks, as for every request but its image's own
check.

## Setting up and managing the Signal account

[tools/signal-account.sh](tools/signal-account.sh) does everything
signal-cli-rest-api can with the account itself: registering the number or
linking signal-cli to a phone, the profile, username, PIN, privacy, linked
devices, safety numbers and rate limits; `--help` lists it all. The bot needs
a number of its own, registered: linked to a phone, it would take commands
typed on that phone as the other person's, so the tool warns before it
links. It's in the
bot's image, where it finds signal-cli-rest-api and the account in the bot's
configuration, so it needs no options:

```sh
podman exec -it nejomibot signal-account.sh                 # status: account, profile, devices
podman exec -it nejomibot signal-account.sh setup           # register or link, then the rest
podman exec -it nejomibot signal-account.sh username mybot
podman exec -it nejomibot signal-account.sh --dry-run unregister  # what it would send; sends nothing
```

(`docker compose exec nejomibot signal-account.sh setup` with Compose.)
A picture for the avatar goes in on standard input, from wherever it is, as
the container can't see your files:

```sh
podman exec -i nejomibot signal-account.sh profile --avatar - < logo.png
```

The tool also runs on any machine with bash, curl and jq that reaches
signal-cli-rest-api: `--url` says where. That's not needed with the
examples, where nothing but the bot reaches it.

It asks before anything that can't be undone (unregistering wants the number
typed), takes PINs only from the terminal, and walks through the captcha Signal
may want before it sends a code, or the call it makes when it can't send an
SMS. It works around what signal-cli-rest-api can't do:

- A profile update removes the avatar unless it's sent along, so the tool
  fetches the current one and sends it back.
- The family name can't be changed, so a new `--name` warns that it stays.
- A refused username comes back as "invalid signal-cli response", so the tool
  says what's most likely: taken, or not allowed.
- In json-rpc mode the trust mode is the container's
  `JSON_RPC_TRUST_NEW_IDENTITIES`, and the API's own setting is unused; the
  tool says so rather than showing that setting.

When Signal rate-limits the bot, it logs that it does, but it can't give the
challenge that lifts the limit, as signalbot doesn't pass it on.
`signal-account.sh rate-limit --to +46701234567` sends that number a short
test message: if Signal rate-limits the bot, it gives a challenge, and the
tool walks through the captcha that lifts the limit.

## How the bot talks to Signal

Everything the bot does in Signal goes through signalbot where signalbot can
do it: receiving, sending, read receipts, typing, deleting messages, groups,
naming a contact, and signal-cli-rest-api's version. signalbot can't say
which accounts signal-cli has, list contacts or linked devices, do anything
with safety numbers or the bot's own profile and username, or fetch one
attachment, so for those the bot asks signal-cli-rest-api itself:
[rest.py](nejomibot/rest.py), each function saying what signalbot lacks. When
signal-cli-rest-api or Signal change, a newer signalbot covers most of it, and
rest.py is the one place to look at for the rest.

signalbot doesn't pass on signal-cli-rest-api's error messages, only the HTTP
status, so an error from a send or a delete is shown as that, such as
`signal-cli-rest-api answered 400 Bad Request`; signal-cli-rest-api's log has
the details.

### Which signal-cli-rest-api

The bot needs a signal-cli-rest-api later than 0.101, the latest release.
0.101 crashes when the answers to two requests arrive together
([#885](https://github.com/bbernhard/signal-cli-rest-api/issues/885)), writes
every message it receives, in full, to its log
([#892](https://github.com/bbernhard/signal-cli-rest-api/issues/892)), and in
json-rpc-native mode its signal-cli 0.14.8 can't list the account's linked
devices, which the health check does: the request never comes back
([signal-cli#2119](https://github.com/AsamK/signal-cli/issues/2119)). Until
the next release, the examples in [deploy/](deploy) pin a CI build with the
fixes, `1791633879-ci` from 2026-10-10, with signal-cli 0.14.9, by its digest,
as CI builds' tags may not be kept; it says `unset` for its version, which
signalbot takes as a build after a release.
The signal-cli-rest-api health check fails on 0.101 or older.

## Configuration

Settings are read from `config.toml`, or the file named by `NEJOMIBOT_CONFIG`:
`/data/config.toml` in the container, in the data folder. Copy
[config.example.toml](config.example.toml) to start: it describes every
setting, and it's in the image as `/app/config.example.toml`:

```sh
podman run --rm localhost/nejomibot cat /app/config.example.toml > config.toml
```

The file holds the API key and phone numbers, so it is not in git.

Any setting can be given as an environment variable named
`NEJOMIBOT_<SETTING>`, overriding the file, for example
`NEJOMIBOT_SIGNAL_SERVICE=127.0.0.1:8080` or `NEJOMIBOT_ADMINS='["+46701234567"]'`
(lists and tables as JSON). With every setting the bot needs in the
environment, there need be no file.

The configuration is checked at startup; mistakes stop the bot with a message
saying which setting is wrong, as do unknown settings and aliases. So when an
update renames or removes a setting, the bot says which, and won't start until
the configuration is changed to match `config.example.toml`.

The bot only reads the photo library. What it's told and what it does, the
timers, the specials, the allowed list, the photos sent this round and the
messages waiting to be sent, it keeps in `data_dir` (`/data` in the
container, beside the config), which must be there at startup: those files
list phone numbers, so only the bot's user may read them. Each is written
whole, through a temp file that's on disk before it takes the file's place,
so neither a crash nor a power cut leaves one half written.

### Debug mode

With `NEJOMIBOT_DEBUG=1` the bot only talks to `debug_group`, and to the
admins, and keeps its list of photos sent, its allowed list, its timers, its
specials and its waiting messages in a temp folder of its own instead of
`data_dir`, new at each start and gone when it stops: the allowed list just
`debug_group`, and no timers or specials of your own. `/chats` offers only
`debug_group` and the admins, so `/msg`, `/run` and timers can't reach anyone
else. Use it to test changes without posting to anyone else, and `/timer add`
to try the daily post. Stop the production bot first: two bots on the same
Signal account compete for incoming messages.

## Running it

The bot is a container image, for linux/amd64 and linux/arm64.
[tools/build-image.sh](tools/build-image.sh) builds it with Podman: it runs
the tests, lint and type check, then builds both architectures (the other one
emulated with QEMU) as `localhost/nejomibot:<version>` and `:latest`, and
with `--push` pushes them to a registry, once for each `--push`.

It needs [signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)
later than 0.101 ([which](#which-signal-cli-rest-api)), in json-rpc mode,
where the bot can reach it; how is up to you.
signal-cli-rest-api has no authentication, so anyone who reaches it controls
the Signal account: don't publish its port beyond the machine. The examples in
[deploy/](deploy) run the two side by side, without publishing it at all.

The bot runs as uid and gid 1001, needs no capabilities, and writes only to
`/data`, and its tools to `/tmp`. The examples run it so: no capabilities,
no new privileges, a read-only file system (`DropCapability=ALL`,
`NoNewPrivileges=true` and `ReadOnly=true` in the Quadlet), and an init
process, which passes SIGTERM on and reaps what the tools leave
(`RunInit=true`). It has two folders:

- `/photos`: the photo library, which it only reads, so it must be readable
  by all.
- `/data`: `config.toml`, and what the bot keeps. It must belong to the bot's
  user: Podman's `:U` sees to that, else `chown 1001` it.

### A fresh install

1. Run signal-cli-rest-api, and note where the bot reaches it, as host:port.
   It runs as uid 1000, which must own the folder it keeps the account in.
2. Make the data folder, and `config.toml` in it from the example; give
   `signal_service` that host:port, and `account` the bot's phone number.
3. Start the bot. With no account yet in signal-cli-rest-api, it says so in
   its log, and waits.
4. Register the bot's number with the account tool in the bot's container:
   `podman exec -it nejomibot signal-account.sh setup`. The bot starts within
   seconds. It needs a number of its own: linked to a phone, it would take
   commands typed on the phone as the other person's.
5. Message the bot `/help` from an admin's phone, then `/allow` the people and
   groups it's for, and add timers, such as the daily post.

### Podman Quadlets

[deploy/signal.container](deploy/signal.container) and
[deploy/nejomibot.container](deploy/nejomibot.container) are Quadlets for
both. They go in `/etc/containers/systemd/`, or for a user, rootless, in
`~/.config/containers/systemd/`; change the folders to suit (`%h` is the
user's home), and for a user give the bot `UserNS=keep-id:uid=1001,gid=1001`
instead of `:U`, so the files in the data folder stay the user's. Then:

```sh
systemctl daemon-reload                  # systemctl --user ... for a user
systemctl start signal                   # and the bot with it
journalctl -u nejomibot -f
```

The bot shares signal-cli-rest-api's network (`Network=signal.container`), so
it reaches it on `127.0.0.1:8080`, and nothing else can. It stops when
signal-cli-rest-api does, as its network goes with it, and starts again with
it. Either is restarted when its health check fails
([how](#the-containers-health-checks)): that's `HealthOnFailure=kill` in
each, as an image can't say it, and for signal-cli-rest-api a better check.
To reach signal-cli-rest-api from elsewhere, say with the account tool on
another machine, publish its port on the server's loopback only
(`PublishPort=127.0.0.1:8080:8080` in signal.container) and use `ssh -L`.
For a user, `loginctl enable-linger <user>` keeps them running when the user
isn't logged in.

### Docker Compose, podman-compose

[deploy/compose.yaml](deploy/compose.yaml) runs both, the bot reaching
signal-cli-rest-api as `signal:8080`:

```sh
mkdir data photos signal
sudo chown 1001 data && sudo chown 1000 signal    # rootless Podman: podman unshare chown ...
# config.toml in data/, the photos in photos/
docker compose up -d
docker compose exec nejomibot signal-account.sh setup
```

signal-cli-rest-api runs as uid 1000, so its folder must be that user's, as
the bot's must be uid 1001's. Docker restarts a container that stops, but
not one whose health check fails.

### podman run, docker run

With signal-cli-rest-api running as a container called `signal`, and the
whole configuration in the environment:

```sh
podman run -d --name nejomibot --network container:signal \
  --init --read-only --cap-drop=ALL --security-opt=no-new-privileges \
  -v /srv/nejomibot/photos:/photos:ro -v /srv/nejomibot/data:/data:U \
  -e NEJOMIBOT_SIGNAL_SERVICE=127.0.0.1:8080 \
  -e NEJOMIBOT_ACCOUNT=+46700000000 \
  -e NEJOMIBOT_ADMINS='["+46700000001"]' \
  -e NEJOMIBOT_OPENWEATHER_API_KEY=... -e NEJOMIBOT_WEATHER_CITY=Stockholm \
  localhost/nejomibot
```

### Updating

Get the new image and restart the bot (`systemctl restart nejomibot`, or
`docker compose up -d`). If the configuration needs changing, the bot says
what's wrong and stops, and its log has the message. What the bot keeps in the
data folder stays as it is.

The log (`journalctl -u nejomibot`, `docker compose logs nejomibot`) has the
commands the bot answers, by name, and the kind of chat, but not who sent
them, what follows the name, or whom messages go to: `log_level = "DEBUG"`
adds those. signalbot, which at INFO logs every message the bot receives in
full, and the other libraries only log what goes wrong; signalbot's warning
that a group message didn't reach someone names them, by number or ID. Each
line has the date and time, the level and the part of the bot it's from.

## Development

Uses [uv](https://docs.astral.sh/uv/). Python and all dependencies are pinned
in `.python-version` and `uv.lock`.

```sh
uv sync                                   # create .venv with all dependencies
cp config.example.toml config.toml        # and fill in
ln -s /path/to/your/photos photos         # a copy of the photo library
NEJOMIBOT_PHOTOS_DIR=photos NEJOMIBOT_DEBUG=1 uv run nejomibot
# or not in debug mode, keeping what the bot's told in data/
mkdir -m 700 data
NEJOMIBOT_PHOTOS_DIR=photos NEJOMIBOT_DATA_DIR=data uv run nejomibot

uv run pytest                             # tests
uv run ruff check                         # lint
uv run ruff format                        # format
uv run pyright                            # type check (strict)
tools/translations.sh                     # after changing the bot's messages
tools/build-image.sh                      # the image, for both architectures
```

Running it needs a signal-cli-rest-api it can reach, as `signal_service`.
The tests need none: they run signalbot against a stand-in for it.

On GitHub, [CI](.github/workflows/ci.yml) runs the same checks, ShellCheck on
the tools, and the image build, for each push and pull request, and
Dependabot proposes new versions of the dependencies, the base images and the
actions. [Release](.github/workflows/release.yml) publishes the image to
GitHub's registry, ghcr.io, when a release is published, and to Docker Hub
as well when the repository has the variable `DOCKERHUB_USERNAME` and the
secret `DOCKERHUB_TOKEN`; nothing else does.
[tools/release.sh](tools/release.sh) makes a release once CI has passed:
the version, the changelog, a signed tag, and the release on GitHub.

## Layout

```
nejomibot/
  bot.py        entry point: handlers, and who may use them
  config.py     settings
  access.py     who may use the bot: the admins, and the allowed list
  allowed.py    /allowed, /allow, /disallow
  commands.py   commands: each handler's, by any name, and how they're answered
  i18n.py       translations
  locale/       the translations: sv.po, the messages; sv.toml, the names
  photos.py     /photo, /cache: random photo with EXIF date, age, location
  specials.py   /dailypost, /dailyquote, /specials, /special: several posts in one
  messages.py   sending, through signalbot, the outbox, and the wording of errors
  rest.py       what signalbot can't do: asking signal-cli-rest-api itself
  client.py     the HTTP session for what the bot asks itself
  receipts.py   read receipts and the typing indicator
  weather.py    /weather: OpenWeatherMap
  info.py       /info: clocks and exchange rate
  ping.py       /ping
  fortune.py    /fortune
  fortunes/     fortune libraries, from fortune-mod, and fortunes_svenska
  health.py     health checks, reported to healthcheck_url; answers the container
  healthcheck.py  the container's health check: asks the bot whether it works
  status.py     /status, /test: health check and details
  account.py    the Signal account: contacts, safety numbers, groups, devices
  contacts.py   /contacts, /trust: everyone known, with safety numbers
  profile.py    /profile, /name, /about, /avatar, /username
  delete.py     /delete: delete the bot's latest messages
  timers.py     /timers, /chats, /timer: commands on a schedule, the daily post
  timers_cli.py nejomibot-timers: the timers from a terminal
  relay.py      /msg, /run: post to other chats
  help.py       /help
  system.py     process, container and host facts from /proc and /sys
  publicip.py   public IPv4/IPv6 addresses, ASN and location
  files.py      writing the files in data_dir, privately
deploy/         examples: Podman Quadlets, and a Compose file
tests/
tools/          build-image.sh: test and build the image, for x86 and ARM;
                release.sh: make a release, and with it the image;
                signal-account.sh: set up and manage the Signal account;
                tidy-photos.sh: convert, rename and dedupe the photo library;
                translations.sh: bring the translations up to date
.github/        CI, publishing the image on a release, Dependabot
```

## License

nejomibot is free software: you can redistribute and change it under the
terms of the GNU General Public License, version 3 or (at your option) any
later version. See [LICENSE](LICENSE).

The fortune libraries in `nejomibot/fortunes`, but `fortunes_svenska`, come
from [fortune-mod](https://github.com/shlomif/fortune-mod), as Debian ships
them, under its BSD license: see
[LICENSES/fortune-mod.txt](LICENSES/fortune-mod.txt). `fortunes_svenska` is
the bot's own: proverbs, and quotes from writers long dead, in translations
of its own.
