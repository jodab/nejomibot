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
in json-rpc mode. It comes as a container image, for x86 and ARM:
[Getting started](#getting-started) sets it up, step by step.

## Getting started

From nothing to the daily post in your Signal groups, with Docker Compose
and the published image, `docker.io/jodab/nejomibot` (the same is at
`ghcr.io/jodab/nejomibot`). With Podman, type `podman` where this says
`docker` (`podman compose` needs podman-compose or Docker Compose
installed); with Podman and systemd, the [Quadlets](#podman-quadlets) are a
better fit, as they also restart a container whose health check fails.
[DOCKERHUB.md](DOCKERHUB.md) is this guide as Docker Hub shows it.

### What you need

1. **A Linux machine that stays on**, such as a home server, a Raspberry Pi
   with a 64-bit system, or a small cloud server, with
   [Docker](https://docs.docker.com/engine/install/) and its Compose plugin:
   `docker compose version` should answer.
2. **A phone number for the bot, of its own.** It has to receive one text
   message or call, with a code. Not your own number, nor one that's in use
   with Signal on a phone: registering it for the bot signs it out of Signal
   everywhere else. A cheap prepaid SIM card will do; a landline can take the
   code as a call.
3. **Signal on your phone.** You'll be the bot's admin.
4. **A free [OpenWeatherMap](https://openweathermap.org/) API key**, for the
   weather, from [your API keys](https://home.openweathermap.org/api_keys). A
   new key can take up to two hours to start working.
5. **Your photos**, in a folder: JPEG, PNG, GIF, WebP, AVIF or HEIC, in
   subfolders or not.
6. **A web browser**, on any computer or phone, for the captcha Signal asks
   for when you register the number.

### Step 1: Make a folder for the bot

```sh
mkdir -p ~/nejomibot && cd ~/nejomibot
mkdir data photos signal
curl -fsSLO https://raw.githubusercontent.com/jodab/nejomibot/main/deploy/compose.yaml
```

`data` is for the bot's settings and what it keeps, `signal` for the Signal
account, and `photos` for your photos: copy them in, or use your library
where it is, by changing `./photos:/photos:ro` in
[compose.yaml](deploy/compose.yaml) to its folder, such as
`/srv/photos:/photos:ro`. There, also change `TZ: Europe/Stockholm` to your
time zone, for the times in the log.

### Step 2: Write the settings

```sh
docker run --rm docker.io/jodab/nejomibot cat /app/config.example.toml > data/config.toml
nano data/config.toml
```

Fill in at least these, keeping the quotes:

| Setting | What it is | Example |
|---|---|---|
| `account` | The bot's phone number | `"+46700000000"` |
| `admins` | Your phone number: you'll be the admin | `["+46700000001"]` |
| `openweather_api_key` | Your OpenWeatherMap key | `"0123456789abcdef..."` |
| `weather_city` | The city for the weather | `"Stockholm"` |
| `timezone` | Your time zone, for the timers | `"Europe/Stockholm"` |
| `language` | `"en"` for English, `"sv"` for Swedish | `"en"` |

Phone numbers go in international format: `+`, the country code, then the
number without its first 0, and no spaces. Leave `signal_service` as it is:
the Compose file sets it. `clocks` and `exchange_rate` are for `/info`:
change them, or delete those two lines. [Configuration](#configuration) has
the rest.

### Step 3: Hand the folders over

The bot runs as user 1001, and signal-cli-rest-api as user 1000, so each must
own its folder:

```sh
sudo chown -R 1001:1001 data && sudo chmod 700 data
sudo chown -R 1000:1000 signal
```

With rootless Podman, `podman unshare chown ...` and `podman unshare chmod
...` instead. From now on, edit the settings with `sudo nano
data/config.toml` (`podman unshare nano data/config.toml`). The bot only
reads the photos, which must be readable by everyone (`chmod -R a+rX
photos`).

### Step 4: Start it

```sh
docker compose up -d
docker compose logs -f nejomibot
```

The bot waits for its Signal account, which you set up next, and its log
says so:

```
WARNING nejomibot.bot: signal-cli-rest-api at signal:8080 has no account +46700000000 yet: register or link it with signal-account.sh setup. Waiting.
```

A line before it saying it can't reach signal-cli-rest-api is fine too, while
that starts. Ctrl+C stops watching the log; the bot keeps running.

### Step 5: Register the bot's number

```sh
docker compose exec nejomibot signal-account.sh setup
```

1. **Register or link?** Press Enter, for `r`: register. Don't link it to a
   phone: it would take what you type there in a direct chat as the other
   person's ([why](#who-may-use-what)).
2. **The captcha.** Open
   [signalcaptchas.org/registration/generate.html](https://signalcaptchas.org/registration/generate.html)
   in a browser and solve it. When **Open Signal** shows, right-click it (on a
   phone, press and hold it), copy the link, and paste it into the tool
   within a minute or so: it starts with `signalcaptcha://`.
3. **The code.** Type in the 6 digits Signal texts the bot's number. If
   Signal can't send a text, the tool offers a call.
4. **Profile, username, PIN and privacy.** Enter skips any of them. Do give
   the bot a **name**, or Signal shows its number; and a **PIN** (`y`), which
   stops anyone else from registering the number.

Once the tool shows `== Done`, and the account under it, the bot starts
within seconds, and its log has `INFO nejomibot.bot: 0 timers, in
/data/timers.txt`. The tool does much more:
see [Setting up and managing the Signal
account](#setting-up-and-managing-the-signal-account).

### Step 6: Say hello

On your phone, start a new chat in Signal with the bot's number (the pencil
button, then **Find by phone number**), and send it `/help`. It answers with
the commands you may use: as its admin, all of them, the admin commands in
this direct chat only.

### Step 7: Add the bot to your groups

1. In Signal on your phone, open a group, tap its name, then **Add members**,
   and pick the bot. Do it after the bot has answered you: then it joins at
   once. Before that, Signal may only invite it, and the bot doesn't take up
   invitations.
2. In your direct chat with the bot, allow the group by its name, such as
   `/allow Family`: everyone in it may use the everyday commands there.
3. Allow people the same way, for a direct chat with the bot:
   `/allow +46700000002`.

`/allowed` shows the list ([more](#the-allowed-list)).

### Step 8: Schedule the daily post

Send the bot:

```
/chats
/timer add 08:00 1 /dailypost
/timer run 1
```

`/chats` numbers the chats the bot can post to: its groups, then the people
allowed, then you. `/timer add 08:00 1 /dailypost` posts the weather and the
photo of the day at 08:00 every day, in your `timezone`, to chat 1; for more
chats, `1,2`, and days work too, as in `mon-fri 07:30` ([more](#timers)).
`/timer run 1` posts it right away, to see that it works.

That's it: the bot is up and running. Next, perhaps: warnings when it's
down, with `healthcheck_url` ([how](#health-checks)); birthdays, name days
and holidays atop the daily post
([how](#birthdays-name-days-and-holidays)); [specials](#specials) of your
own; and a profile picture:

```sh
docker compose exec -T nejomibot signal-account.sh profile --avatar - < picture.jpg
```

To update it later, see [Updating](#updating).

### If something's wrong

- **`Invalid configuration (config file: /data/config.toml):`** and a
  setting: fix that setting, then `docker compose restart nejomibot`.
- **`Can't read the config file /data/config.toml: Permission denied`, or
  `Can't write in data_dir /data: Permission denied`:** the `data` folder
  isn't the bot's: do step 3 again.
- **The bot doesn't answer you:** its log must be past `Waiting`, and
  `admins` must have your number in international format. If both are so,
  your Signal may not show your number to the bot, as when *Who can see my
  number* is *Nobody* in its privacy settings. Then the bot knows you by your
  Signal ID: `docker compose exec nejomibot signal-account.sh identities`
  lists who has written to it, by name. Put the ID after yours, such as
  `0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e`, in `admins` in place of your
  number, and restart the bot.
- **A group isn't in `/chats`:** Signal only invited the bot. In the group's
  settings, under **Requests & invites**, revoke its invite; once the bot has
  answered you, add it again.
- **`/weather` says `OpenWeatherMap answered with an error (401: Invalid API
  key...)`:** a new key takes up to two hours to work; check it's the one on
  your API keys page.
- **The captcha didn't work:** it's only good for a minute or so: solve a
  new one, and paste it right away.
- **With SELinux** (Fedora, RHEL), the containers may be refused their
  folders: add `:Z` to the data and signal volumes in compose.yaml, and `,z`
  to the photos' (`./photos:/photos:ro,z`).

## Commands

The everyday commands, for everyone the bot may talk to:

| Command | Reply |
|---|---|
| `/photo` | A random photo with the date it was taken, an age if set, and a map link |
| `/onthisday` | A photo taken on this day in an earlier year, or else within three days of it, captioned as `/photo` captions it, under how many years ago (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/cache` | Number and size of photos in the library |
| `/weather`, `/weather <city>` | Current weather in `weather_city`, or in the city named, such as `/weather Helsinki`, under its heading in bold, with the day's sunrise and sunset (see [The weather](#the-weather)) |
| `/forecast`, `/forecast <city>` | The weather today and tomorrow there: each day's worst weather, its lowest and highest temperature, and its chance of rain or snow (see [The weather](#the-weather)) |
| `/info`, `/time` | The time in the places in `clocks`, and the `exchange_rate` |
| `/ping` | `pong!` and how long the ping took to arrive |
| `/fortune`, `/fortune <library>`, `/fortune all`, `/fortune list` | A random fortune, from `fortune_library` (`fortunes_svenska` if not set), the library named, or every library; `list` names them. What explains a proverb of `fortunes_svenska` is in italics |
| `/remind <when> <text>`, `/remind`, `/remind remove <n>` | A reminder, which the bot posts in the chat when it's due, such as `/remind tomorrow 08:00 Pick up Bob`; alone, the chat's reminders, numbered (see [Reminders and lists](#reminders-and-lists)) |
| `/list`, `/list add <things>`, `/list remove <n>,<n>`, `/list clear` | The chat's list, such as for shopping: `/list add milk, eggs` puts things on it, `/list remove 2,5` takes them off (see [Reminders and lists](#reminders-and-lists)) |
| `/birthdays` | In a group, the birthdays of those it's for, the coming ones first; for the admins, in a direct chat, all of them, numbered (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)) |
| `/namedays` | The name days, as `/birthdays` lists the birthdays |
| `/help` | The commands the asker may use, a line each |

For the admins, in a direct chat with the bot:

| Command | Reply |
|---|---|
| `/status`, `/test` | Health check, in two messages: the checks, failed ones first, then the details: the bot and its versions, Signal, public IPs and ASN, container, host |
| `/dailypost` | The daily post, as a timer posts it: the weather, then the photo of the day (it uses up a photo of the round) |
| `/dailyquote` | The daily quote, as a timer posts it: a proverb or quote from `fortunes_svenska`, headed "Proverb or quote of the day:" in bold, what explains a proverb in italics |
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
| `/incoming`, `/incoming <n>,<n>` | The 50 latest messages anyone but the admins sent the bot in a direct chat, numbered: when, from whom, and how each starts; `/incoming 4,9` forwards those two to you in full (see [Incoming messages](#incoming-messages)) |
| `/birthday add <date> [<chats>] <who>` | A birthday: a contact's, as `/contacts` finds them, shown in the groups they're in; or someone's not on Signal, by name, shown in the groups `<chats>` numbers in `/chats`, or else in every group (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)) |
| `/nameday add <date> [<chats>] <who>` | A name day, as `/birthday add` takes it |
| `/birthday remove <n>`, `/nameday remove <n>` | Remove one, by its number in the list `/birthdays` or `/namedays` showed you last; `/birthday remove 2,5` several |
| `/delete list`, `/delete <n>,<n>` | The bot's 50 latest messages, wherever it sent them, numbered: when, where to, and how each starts; `/delete 2,5,11` deletes those for everyone (see [Who may use what](#who-may-use-what)) |

And for the admins in any chat, groups too:

| Command | Reply |
|---|---|
| `/delete` | Delete the bot's latest message in the chat, for everyone; sent again, the one before, and so on |

A command can have other names: a few it has had all along (`/test` for
`/status`, `/time` for `/info`, `/safety` for `/contacts`), aliases from the
configuration, and the names in the bot's language (see
[Languages](#languages)). With
`language = "sv"`, `/väder` is `/weather`, `/hjälp` is `/help`,
`/påminn` is `/remind`, `/lista` is `/list`, `/dagensbild` is `/dailypost`
and `/dagenscitat` is `/dailyquote`; `/help` shows every name a command has.

### Who may use what

The admins, `admins` in the configuration, may use every command: the
everyday ones wherever they're allowed, the admin commands only in a direct
chat with the bot, as they show phone numbers and the server's addresses, or
change the bot. An admin is given by phone number, or by Signal ID for one who
doesn't share their number. Everyone else may use the everyday commands if
they're on the [allowed list](#the-allowed-list): a contact, in a direct chat
with the bot, or a group, where everyone in it may use them, there. The bot
answers nobody else.

Someone on the allowed list who writes to the bot in a direct chat, but no
command, is greeted: "Hi, I'm Mybot, a bot. Try /help for a list of
commands. Contact Alice for more information." The names are the bot's
profile name and the first admin's name, as the bot's contacts have it
(`/contacts add`), else their profile name; without one, the greeting does
without it. It comes once a day at most for each person, so a thank-you
after it isn't greeted again, and a restart forgets who was. Commands are
answered as ever, never with the greeting; a mistyped one isn't a command,
so it's greeted. The admins, strangers and groups aren't, nor edits.

Admins are only ever set in the configuration, so no command can take away
what an admin may do, or make someone an admin.

People who don't share their phone number on Signal are known only by their
ID. signal-cli-rest-api has no way to take someone out of the contacts, or to
forget them, so the bot can't either.

It marks each command as read, in groups as well as direct chats, and shows
itself typing while it works on the slower ones. Both are best effort: if they
fail, the answer still comes. Editing a message runs its command again, except
for those that change things or post elsewhere: `/delete` (but `/delete
list`), `/contacts add`, `/allow`, `/disallow`, `/timer`, `/special`, `/msg`,
`/run`, `/remind` and `/list` (but alone, which list), `/birthday`,
`/nameday` and the specials of your own.

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

In a direct chat with the bot, `/delete list` shows its 50 latest messages,
wherever it sent them, groups and people alike, newest first and numbered:
when, where to, and how each starts, with 📷 for a photo. `/delete 3` then
deletes the third of them for everyone, `/delete 2,5,11` those three, and
the bot says which it deleted. It deletes them one after the other, and
stops at one it can't, as when Signal can't be reached, saying which it
didn't try. The numbers are those of the list you were shown last, whatever
the bot sends meanwhile, until you ask for it again, or the bot restarts. In
a group, `/delete` takes nothing after it, as the list shows what went to
every chat.

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

### The weather

`/weather` is the weather now in `weather_city`, from OpenWeatherMap, under a
heading in bold that names it `weather_city_name`, if set. `/weather
Helsinki` is the weather in Helsinki, under a heading that names the place
OpenWeatherMap found, in the bot's language where OpenWeatherMap has the name
in it, with its state or region and country: "Weather in Helsinki, FI", or
in Swedish "Vädret i Helsingfors, FI".

OpenWeatherMap finds places by name, the best known first, and the bot takes
the first: `/weather Stockholm` is Stockholm, SE, not Stockholm, Maine, and
`/weather Springfield` is Springfield, Illinois. A country code
([ISO 3166](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2)) after a comma
picks the country, and in the US a state code the state: `/weather
Stockholm,US`, `/weather Springfield,MO,US`. A misspelt name may still find a
place, as `Stokholm` finds Stockholm, SE: the heading shows which it was.

The bot looks a name up once, as places don't move, and keeps each place's
weather for 10 minutes, as OpenWeatherMap's changes every 10 minutes: asked
again sooner, by any name of the place, it answers with what it has, without
asking OpenWeatherMap. About places named after `/weather`, it asks
OpenWeatherMap at most `weather_calls_per_hour` times an hour (10 by
default), finding them included, so a new place takes two calls; past that,
it says when to try again. `weather_city` isn't counted, so `/weather` alone,
the daily post and `/status` always get its weather.

The weather ends with the day's sunrise and sunset there, and the daylight
between, in the place's own time, from the same answer of OpenWeatherMap's:
`🌅 07:35 · 🌇 17:21 · 9 h 46 min of daylight`; where the sun doesn't both
rise and set that day, there's none.

`/forecast` is the weather today and tomorrow, in `weather_city` or a place
named as `/weather` takes it, from OpenWeatherMap's forecast for every three
hours: for each day, the worst weather from 06:00 to 21:00 there (a
thunderstorm, then snow, rain, drizzle, mist and the like, clouds, and a
clear sky last), the lowest and highest temperature, and the highest chance
of rain or snow, if any. Late in the evening, once today has no daytime
left, it's tomorrow and the day after. The bot keeps a place's forecast for
30 minutes, and counts the calls for places named as `/weather` does:

```
Forecast for Stockholm
Today: 🌦️ Light rain
🌡️ 6 to 12°C · ☔ 80%
Tomorrow: ☁️ Overcast clouds
🌡️ 3 to 12°C · ☔ 20%
```

### Photos and the daily post

`/dailypost` is the daily post: the weather, under its heading in bold, then
the photo of the day, captioned "Photo of the day!" in bold. Atop the
weather go the day's holidays, and in a group, the birthdays and name days
of those it's for (see
[Birthdays, name days and holidays](#birthdays-name-days-and-holidays)).
It's for timers: `/timer add 08:00 1,2
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

`/onthisday` is a photo taken on this day in an earlier year, captioned as
`/photo` captions it, under "3 years ago today" in bold; without one, a photo
taken within three days of the day, the nearest first, under "3 years ago,
around this day". Like `/photo`, it doesn't count toward the round. When
each photo was taken is as its caption has it, in the bot's `timezone`: the
bot reads it once for each photo, from the file's header, and keeps it in
memory, about 300 bytes a photo, reading a photo again only when it changes.
So the first `/onthisday` after a start takes longer: 0.2 s for 1150 photos
on a desktop whose disk cache has them.

### Reminders and lists

`/remind` is for everyone allowed: a reminder the bot posts once, when it's
due, in the chat it was asked for in, a group's for everyone in it:

```
/remind 18:00 Take the cake out     today, or tomorrow if 18:00 has been
/remind 30m Call Bob                in 30 minutes; also 2h, 1h30m, in 2h
/remind tomorrow 08:00 Pick up Bob
/remind fri 17:00 Pizza!            the coming Friday
/remind 2026-12-24 15:00 Presents!
/remind                             the chat's reminders, numbered
/remind remove 2                    or 2,3
```

When one is due, in the bot's `timezone`, the bot posts "⏰ Pick up Bob" in
the chat; it looks at the start of every minute. A chat has at most 20, a
year ahead at most; for one every week, an admin's [timer](#timers) does it.
One due while the bot was down comes once it's up, with a note that it's
late; more than a day late, it's dropped. A group gets its reminders only
while the bot is in it. In Swedish, `/påminn`, and `om 30m` for `in 30m`.

`/list` is a list for each chat, such as for shopping, which everyone in a
group shares:

```
/list                     the list, numbered
/list add milk, eggs      put things on it, separated by commas or line breaks
/list remove 2,5          take those off, by their numbers
/list clear               take everything off
```

A list has at most 100 things. In Swedish, `/lista`.

They're kept in `data_dir/reminders.txt` and `data_dir/lists.txt`, a line
each, which can be changed by hand: the bot reads them again when they
change, and leaves comments and lines it can't read as they are. Timers,
specials and `/run` can't run them, as they're each chat's own.

### Birthdays, name days and holidays

The daily post names the day atop the weather. In every chat, the day's
holidays, flag days and traditions in the countries of `holidays` (`SE` for
Sweden, `GR` for Greece; none by default), each after its country's flag, a
day both keep once, after both flags; and in a group, the birthdays and name
days of those it's for:

```
🇸🇪 National Day of Sweden · flag day
🎂 Alice turns 36 today!
🌸 Happy name day, Bob!

Weather in Stockholm
...
```

- Sweden: its public holidays and their eves, its flag days
  ([förordning 1982:270](https://lagen.nu/1982:270)), the Sundays of Advent,
  and Shrove Tuesday, Valentine's Day, Walpurgis Night, Mother's Day,
  Father's Day and Lucia. The day of the election to the Riksdag, the second
  Sunday of September every fourth year, is a flag day; so is the day of the
  election to the European Parliament, but its date is set anew each time,
  so it isn't there.
- Greece: its public holidays, by the Orthodox Easter, and Tsiknopempti,
  Maundy Thursday, Holy Saturday, Valentine's Day, Mother's Day, Father's
  Day, Christmas Eve and New Year's Eve.

The admins keep the birthdays and name days, in a direct chat with the bot:

```
/birthday add 1990-03-14 Alice       a contact; with the year, the age shows
/birthday add 03-14 Bob              without the year, it doesn't
/birthday add 1940-05-01 1 Grandma   someone not on Signal, in chat 1 of /chats
/birthday add 1940-05-01 Grandma     someone not on Signal, in every group
/nameday add 08-08 Alice
/birthday remove 2                   by its number in /birthdays
```

Someone on Signal is given as `/contacts` takes them, by name, phone number
or ID, and must be a contact saved by name, with `/contacts add <who>
<name>`: theirs show in the groups they're in, by that name, as the contacts
have it at the time, so a rename shows. A contact has one birthday and one
name day: adding another changes it. Someone not on Signal is given by a
name no contact has: theirs show in the groups given, by their numbers in
`/chats`, or else in every group the daily post goes to. The answer says
which, so a contact's name mistyped shows. Birthdays and name days never
show in a direct chat. A birthday on 29 February comes on the 28th in other
years.

`/birthdays` and `/namedays`, for everyone allowed, list them, the coming
ones first: in a group, those it gets; in a direct chat, for the admins, all
of them, numbered, with where someone not on Signal shows. As with `/delete
list`, `/birthday remove` and `/nameday remove` take the numbers of the list
you were shown last, whatever changes meanwhile, until you ask for it again,
or the bot restarts; one removed or changed since is named. They're kept in
`data_dir/birthdays.txt`, a line each, with a contact's Signal ID and phone
number, and their name as it was saved, which shows if the contacts can't be
read. It can be changed by hand, as the other files.

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

### Incoming messages

The bot keeps the 50 latest messages that anyone but the admins sends it in
a direct chat, commands too, and strangers' as well, in memory only: a
restart forgets them. A message its sender deletes for everyone goes from
the bot too, as a disappearing message does once its time is up, and an edit
replaces the message it edits.

`/incoming`, for the admins in a direct chat, lists them, newest first and
numbered: when, from whom, by their name in the account's contacts, else on
their profile, else their number, and how each starts, with 📎 for
attachments. `/incoming 4,9` forwards messages 4 and 9 of the list to you,
each a message of its own, in full and with its formatting, to read whole,
or forward on in Signal. Only their text, as the bot doesn't fetch
attachments: it says how many there were. As with `/delete list`, the numbers are those of the list you
were shown last. Timers and `/run` can't run `/incoming`, as they'd post
what people wrote to others.

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
timer, `/run` can't manage timers, specials, birthdays or who may use the
bot, nor run `/msg` or `/run`, nor what's each chat's own: `/remind`,
`/list`, `/birthdays` and `/namedays`. Mind what goes where: `/status` shows phone numbers and the
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
bot, so it can run any command but those that manage timers, specials,
birthdays or the allowed list, post to other chats themselves (`/msg`,
`/run`), or are each chat's own (`/remind`, `/list`, `/birthdays`,
`/namedays`), and posts its answers to all the timer's chats before the next
command runs: every chat gets the same photo, and each group the birthdays
of its own. It can run [specials](#specials) of your own too.

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
quote from `fortunes_svenska`, headed "Proverb or quote of the day:" in
bold, what explains a proverb in italics. The admins make their own in a
direct chat with the bot, mostly for timers:

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

Text keeps the formatting you give it in Signal, as in any message: select
the words, then bold, italic, strikethrough, monospace or spoiler. What you
type shows as typed, `*` and `~` too. signal-cli-rest-api, which sends the
formatting, can't say every mix, so the bot turns down the few it can't:
bold and italic that meet inside a word, and a style that starts or ends
right by a `\` or `*`.

A special runs its commands as a timer does, as an admin would in a direct
chat with the bot, and posts what they answer one after the other: it can
have any command a timer can, `/dailypost` and `/dailyquote` too, but not
another special of your own. Like those two, specials are for timers, `/run`
and the admins in a direct chat. Editing a message doesn't run a special of
your own again, as its commands may change something. A special a timer runs
can be changed, but not removed: remove the timer first.

The specials of your own are kept in `data_dir/specials.txt`, a line each:
the name, a `|`, and the parts, their commands by their English names, their
texts in signal-cli-rest-api's marks for the formatting: `**bold**`,
`*italic*`, `***both***`, `~strikethrough~`, `` `monospace` `` and
`||spoiler||`, with a `\` before a `*`, `~`, `` ` `` or `|` that shows as it
is:

```
/morning | **Good morning!** /weather; /dailyquote
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
language, and `fortune_library` sets the one `/fortune` picks from when none
is named.

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
language's, and over the bot's own: `/test`, `/time` and `/safety`.

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
  has the account, and no message has waited more than 15 minutes to be sent;
  if Signal rate-limits the bot, it says so, and what lifts the limit.
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

Each ping says how each check went, then what runs, as `/status` does: the
versions of nejomibot, signalbot, Python and signal-cli-rest-api, how long
the bot has been up, and so its container, as the bot is its process, and
the bot's memory, with its peak and the container's limit, if there is one.
healthchecks.io shows it with each ping in the check's log. signal-cli's
version isn't there: signal-cli-rest-api doesn't say it.

### Notices to the admins

The bot tells the admins itself, in a direct chat with each, what they'd
otherwise find out late:

- **An update, or a stop that wasn't clean.** After an update, the versions:
  `🔄 Updated: nejomibot 0.98.0 → 0.99.0.`; after a crash, a kill or a power
  cut, that it's up again, since when it had run, and that messages that had
  waited less than half a minute may be lost. It knows from
  `data_dir/run.json`, which it writes as it starts, and as it stops.
- **Signal rate-limits the bot.** As it starts to, how to lift the limit:
  `signal-account.sh rate-limit --to <your number>`, and a captcha. Once in
  six hours at most, and tried once, as while Signal rate-limits the bot, it
  may not get through either; the health check says so too, while messages
  wait, and with `healthcheck_url`, so does the ping.
- **A safety number changes.** signal-cli won't send to someone whose safety
  number changed until it's trusted, so the admins hear whose, to compare it
  with `/contacts`, then `/trust`. The bot looks every `healthcheck_minutes`,
  which asks nothing of Signal's servers, and at a start, for changes since
  it last ran.

In debug mode, which starts anew each time, there's no update or stop to
tell of.

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
podman run --rm docker.io/jodab/nejomibot cat /app/config.example.toml > config.toml
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
timers, the specials, the allowed list, the reminders, the lists, the
birthdays and name days, the photos sent this round, the messages waiting to
be sent and the version that ran last, it keeps in `data_dir` (`/data` in the
container, beside the config), which must be there at startup: those files
list phone numbers, so only the bot's user may read them. Each is written
whole, through a temp file that's on disk before it takes the file's place,
so neither a crash nor a power cut leaves one half written.

### Debug mode

With `NEJOMIBOT_DEBUG=1` the bot only talks to `debug_group`, and to the
admins, and keeps its list of photos sent, its allowed list, its timers, its
specials, its reminders, lists and birthdays, and its waiting messages in a
temp folder of its own instead of `data_dir`, new at each start and gone
when it stops: the allowed list just `debug_group`, and no timers, specials
or birthdays of your own. `/chats` offers only
`debug_group` and the admins, so `/msg`, `/run` and timers can't reach anyone
else. Use it to test changes without posting to anyone else, and `/timer add`
to try the daily post. Stop the production bot first: two bots on the same
Signal account compete for incoming messages.

## Running it

The bot is a container image, for linux/amd64, linux/arm64 and linux/arm/v7,
the same as signal-cli-rest-api. Each release is published as
`docker.io/jodab/nejomibot` and `ghcr.io/jodab/nejomibot`, tagged with its
version and `latest`, which the examples in [deploy/](deploy) use. To build
it yourself, [tools/build-image.sh](tools/build-image.sh) builds it with
Podman: it runs the tests, lint and type check, then builds the three
architectures (those that aren't the machine's emulated with QEMU) as
`localhost/nejomibot:<version>` and `:latest`, and with `--push` pushes them
to a registry, once for each `--push`.

The release workflow attests each image it pushes, after 0.93.5: signed
build provenance, which says which workflow built it, from which commit,
kept on GitHub. With the [GitHub CLI](https://cli.github.com/), logged in:

```sh
gh attestation verify oci://docker.io/jodab/nejomibot:latest --repo jodab/nejomibot
```

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

[Getting started](#getting-started) walks through one with Compose. With the
Quadlets or `podman run` below, the steps are the same, with `podman exec -it
nejomibot` where it has `docker compose exec nejomibot`: `config.toml` in the
data folder, the bot started, which waits for its account in its log, the
account registered with `signal-account.sh setup` in the bot's container,
then `/help` from an admin's phone, `/allow`, and the timers.

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
signal-cli-rest-api as `signal:8080`, beside the folders `data`, `photos` and
`signal`; [Getting started](#getting-started) uses it, step by step.
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
  docker.io/jodab/nejomibot
```

### Updating

Get the new image and restart the bot: with Compose, `docker compose pull &&
docker compose up -d`; with the Quadlets, `podman pull
docker.io/jodab/nejomibot` and `systemctl restart nejomibot`.
[CHANGELOG.md](CHANGELOG.md) says what to do when updating, if anything. If
the configuration needs changing, the bot says what's wrong and stops, and
its log has the message. What the bot keeps in the data folder stays as it
is. To choose when to update, use a version's tag in place of `latest`.

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
tools/build-image.sh                      # the image, for all three architectures
```

Running it needs a signal-cli-rest-api it can reach, as `signal_service`.
The tests need none: they run signalbot against a stand-in for it.

On GitHub, [CI](.github/workflows/ci.yml) runs the same checks, ShellCheck on
the tools, and the image build, for each push and pull request, and
Dependabot proposes new versions of the dependencies, the base images and the
actions. [Release](.github/workflows/release.yml) publishes the image to
GitHub's registry, ghcr.io, when a release is published, and to Docker Hub
as well when the repository has the variable `DOCKERHUB_USERNAME` and the
secret `DOCKERHUB_TOKEN`; nothing else does. It attests each image's build
provenance, and on Docker Hub makes [DOCKERHUB.md](DOCKERHUB.md) the image's
page, for which the token must be allowed to read, write and delete.
[tools/release.sh](tools/release.sh) makes a release once CI has passed:
the version, the changelog, a signed tag, and the release on GitHub. For
now, it makes patch releases only: nejomibot stays on 0.99.x until 1.0.

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
  onthisday.py  /onthisday: a photo from this day in an earlier year
  specials.py   /dailypost, /dailyquote, /specials, /special: several posts in one
  messages.py   sending, through signalbot, the outbox, and the wording of errors
  styles.py     Signal's text styles, as signal-cli-rest-api's marks
  rest.py       what signalbot can't do: asking signal-cli-rest-api itself
  client.py     the HTTP session for what the bot asks itself
  receipts.py   read receipts and the typing indicator
  weather.py    /weather, /forecast: OpenWeatherMap
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
  delete.py     /delete: delete the bot's latest messages, here or anywhere
  incoming.py   /incoming: the latest messages people sent the bot
  greeting.py   the greeting for the allowed list's messages that aren't commands
  notices.py    notices to the admins: an update, a crash, a rate limit, safety numbers
  reminders.py  /remind: reminders, posted in their chat when due
  lists.py      /list: a list for each chat
  birthdays.py  /birthdays, /namedays, /birthday, /nameday: for the daily post
  holidays.py   the calendar's holidays, flag days and traditions
  timers.py     /timers, /chats, /timer: commands on a schedule, the daily post
  timers_cli.py nejomibot-timers: the timers from a terminal
  relay.py      /msg, /run: post to other chats
  help.py       /help
  system.py     process, container and host facts from /proc and /sys
  publicip.py   public IPv4/IPv6 addresses, ASN and location
  files.py      the files in data_dir: written privately, read back when changed
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
