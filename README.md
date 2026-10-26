# nejomibot

> **Disclaimer:** This project began as a playground for teaching myself to
> make better use of Claude Code. Everything here was written by AI, under my
> guidance.

nejomibot is a self-hosted Signal bot for a family or a group of friends.
Every morning it can greet your groups with the day's holidays, birthdays and
name days, the weather, and a photo from your own photo library. Throughout
the day, it answers everyday commands for photos, the weather, reminders and
shared lists, and it runs whatever else you schedule. You run it on your own
machine, such as a home server or a Raspberry Pi, and manage it entirely from
Signal.

- 🌅 **A daily post** at the time you choose: the day's holidays, flag days
  and traditions in any of 35 countries, each group's birthdays and name
  days, the weather, and a photo of the day, never the same photo twice until
  every one has been shown.
- 📷 **Your photo library in Signal:** a random photo from all albums or just
  one, a photo from a given year, month, day or moment, and one taken on this
  day in an earlier year, each with when and where it was taken and, if you
  like, the age of the person in it.
- 🌦️ **The weather and more:** the current weather and a two-day forecast for
  any place, world clocks and an exchange rate, and proverbs, quotes and
  fortunes.
- 🔔 **Reminders and shared lists** for each chat, such as a shopping list for
  the whole family.
- ⏰ **Timers and commands of your own:** any command on a schedule, posted to
  the chats you choose, and your own commands that combine texts and other
  commands, such as a morning greeting, for the admins or for everyone.
- 🌍 **Nine languages:** English, Danish, Finnish, French, German, Greek,
  Norwegian, Spanish and Swedish, with each chat in its own language, and
  room for more: a new language takes two files and no code.
- 🔐 **Private by design:** only the people and groups you allow may use it,
  admins manage it from a direct chat, and by default, the log contains no
  phone numbers or message text.
- 🛠️ **Admin tools in Signal:** contacts and safety numbers, the bot's
  profile, posting to other chats, mentioning everyone in a group, deleting
  the bot's messages, delivery and read receipts, and the latest messages
  people have sent the bot; and all of it from a terminal on the server
  too, with files attached.
- 🩺 **Reliable and light:** health checks with alerts, notices to the admins,
  messages retried until they get through, and a small container image for
  x86 and ARM that runs in about 80 MB of memory.

The bot connects to Signal through
[signalbot](https://pypi.org/project/signalbot/), which in turn uses
[signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api) in
json-rpc mode. It is distributed as a container image for x86 and ARM, and
[Getting started](#getting-started) walks you through the setup step by step.

## Getting started

This guide takes you from nothing to a daily post in your Signal groups,
using Docker Compose and the published image, `docker.io/jodab/nejomibot`
(also available as `ghcr.io/jodab/nejomibot`). With Podman, type `podman`
wherever the guide says `docker` (`podman compose` requires podman-compose or
Docker Compose to be installed). If you use Podman with systemd, the
[Quadlets](#podman-quadlets) are a better fit, because they also restart a
container whose health check fails. [DOCKERHUB.md](DOCKERHUB.md) is the same
guide as it appears on Docker Hub.

### Prerequisites

1. **A Linux machine that is always on**, such as a home server, a Raspberry
   Pi with a 64-bit or 32-bit operating system, or a small cloud server, with
   [Docker](https://docs.docker.com/engine/install/) and its Compose plugin
   installed: `docker compose version` should print a version. The bot and
   signal-cli-rest-api together use about 450 MB of memory.
2. **A phone number for the bot alone.** It must be able to receive one text
   message or call with a verification code. Don't use your own number, or
   any number that is in use with Signal on a phone: registering it for the
   bot signs it out of Signal everywhere else. A cheap prepaid SIM card
   works, and a landline can receive the code as a voice call. Instead, the
   bot can also be linked to a phone with Signal, as Signal Desktop is, and
   use that phone's account ([Linking to a phone](#linking-to-a-phone)).
3. **Signal on your phone.** You will be the bot's admin.
4. **A free [OpenWeatherMap](https://openweathermap.org/) API key** for the
   weather, from [your API keys page](https://home.openweathermap.org/api_keys).
   A new key can take up to two hours to become active.
5. **Your photos** in a folder, as JPEG, PNG, GIF, WebP, AVIF or HEIC files,
   with or without subfolders.
6. **A web browser** on any computer or phone, to solve a captcha if Signal
   requires one when you register the number.

### Step 1: Create a folder for the bot

```sh
mkdir -p ~/nejomibot && cd ~/nejomibot
mkdir data photos signal
curl -fsSLO https://raw.githubusercontent.com/jodab/nejomibot/main/deploy/compose.yaml
```

`data` holds the bot's settings and everything it stores, `signal` holds the
Signal account, and `photos` holds your photos. Copy your photos into it, or
use your library where it is by changing `./photos:/photos:ro` in
[compose.yaml](deploy/compose.yaml) to its folder, for example
`/srv/photos:/photos:ro`. In the same file, change `TZ: Europe/Stockholm` to
your time zone, which sets the times shown in the log.

### Step 2: Write the settings

```sh
docker run --rm docker.io/jodab/nejomibot cat /app/config.example.toml > data/config.toml
nano data/config.toml
```

Fill in at least the following settings, keeping the quotes:

| Setting | Description | Example |
|---|---|---|
| `account` | The bot's phone number, or the Signal ID of [an account without one](#an-account-without-a-phone-number) | `"+46700000000"` |
| `admins` | Your phone number, which makes you the admin, or your Signal ID if you have no number (see [An account without a phone number](#an-account-without-a-phone-number)) | `["+46700000001"]` |
| `openweather_api_key` | Your OpenWeatherMap API key | `"0123456789abcdef..."` |
| `weather_city` | The city for the weather | `"Stockholm"` |
| `timezone` | Your time zone, used by the timers | `"Europe/Stockholm"` |
| `language` | The bot's language: `"en"` (English), `"da"` (Danish), `"de"` (German), `"el"` (Greek), `"es"` (Spanish), `"fi"` (Finnish), `"fr"` (French), `"nb"` (Norwegian) or `"sv"` (Swedish) | `"en"` |

Write phone numbers in international format: a `+`, the country code, then
the number without its leading 0, with no spaces. Leave `signal_service` as
it is, because the Compose file sets it. `clocks` and `exchange_rate` are
used by `/info`: change them, or delete those two lines.
[Configuration](#configuration) covers the other settings.

### Step 3: Set the folder ownership

The bot and signal-cli-rest-api both run as user 1000, so that user must own
both folders:

```sh
sudo chown -R 1000:1000 data signal && sudo chmod 700 data
```

With rootless Podman, use `podman unshare chown ...` and `podman unshare
chmod ...` instead. To run the bot as another user, give its user and group
in `compose.yaml`, as `user: "1001:1001"`, and have that user own `data`
instead. From now on, edit the settings with `sudo nano
data/config.toml` (or `podman unshare nano data/config.toml`). The bot only
reads the photos, but they must be readable by everyone (`chmod -R a+rX
photos`).

### Step 4: Start the bot

```sh
docker compose up -d
docker compose logs -f nejomibot
```

The bot waits for its Signal account, which you set up in the next step, and
its log says so:

```
WARNING nejomibot.bot: signal-cli-rest-api at signal:8080 has no account +46700000000 yet: register or link it with signal-account.sh setup. Waiting.
```

An earlier line saying that the bot can't reach signal-cli-rest-api is also
normal while signal-cli-rest-api starts. Press Ctrl+C to stop following the
log; the bot keeps running.

### Step 5: Register the bot's number

```sh
docker compose exec nejomibot signal-account.sh setup
```

If the bot isn't running, run the tool in a container of its own instead:
`docker compose run --rm nejomibot signal-account.sh setup`.

1. **Register or link?** Press Enter to choose `r`, register. To link the
   bot to a phone with Signal instead, type `l`, scan the QR code that the
   tool shows with that phone (in Signal, **Settings > Linked devices > Link
   a new device**), and continue with step 4. A linked bot has a few
   drawbacks, which [Linking to a phone](#linking-to-a-phone) describes.
2. **The captcha, if Signal requires one.** If Signal wants a captcha
   solved before it sends the code, the tool asks for it. Open
   [signalcaptchas.org/registration/generate.html](https://signalcaptchas.org/registration/generate.html)
   in a browser and solve the captcha. When **Open Signal** appears,
   right-click it (on a phone, press and hold it), copy the link, and paste
   it into the tool within about a minute. The link starts with
   `signalcaptcha://`.
3. **The code.** Enter the 6-digit code that Signal texts to the bot's
   number. If no code arrives within a minute, press Enter, and the tool asks
   Signal to send it again or to call with it. If Signal can't send a text
   message, the tool offers a call.
4. **Profile, username, PIN and privacy.** Press Enter to skip any of these.
   Do give the bot a **name**, or Signal shows its phone number instead, and
   set a **PIN** (answer `y`), which prevents anyone else from registering
   the number. A linked bot has the phone's profile, and the tool skips the
   PIN, which only the phone can set.

When the tool shows `== Done` followed by the account, the bot starts within
seconds, and its log shows `INFO nejomibot.bot: 0 timers, in
/data/timers.txt`. The tool can do much more: see [Setting up and managing
the Signal account](#setting-up-and-managing-the-signal-account).

### Step 6: Say hello

On your phone, start a new chat in Signal with the bot's number (tap the
pencil button, then **Find by phone number**) and send it `/help`. The bot
replies with the commands you may use. As its admin, you may use all of
them, but the admin commands only in this direct chat. `/help` and a
command, as in `/help timer`, explains that command, with examples. Every
command can start with a period instead of the slash, as in `.help`, which
phone keyboards have on their first page; the bot's replies show commands
that way.

### Step 7: Add the bot to your groups

1. In Signal on your phone, open a group, tap its name, tap **Add members**,
   and select the bot. Do this after the bot has replied to you, so that it
   joins right away. Before that, Signal may only invite it, and the bot
   doesn't accept invitations.
2. In your direct chat with the bot, allow the group by name, for example
   `/allow Family`. Everyone in the group can then use the everyday commands
   in that group.
3. Allow people the same way, for direct chats with the bot:
   `/allow +46700000002`.

`/allowed` shows the list ([more](#the-allowed-list)).

### Step 8: Schedule the daily post

Send the bot:

```
/chats
/timer add 08:00 1 /today; /weather; /uniquephoto
/timer run 1
```

`/chats` numbers the chats the bot can post to: its groups first, then the
people you have allowed, then you. `/timer add 08:00 1 /today; /weather;
/uniquephoto` posts to chat 1 at 08:00 every day, in your `timezone`: the
date and time with the day's holidays and birthdays, the weather, and a
photo, never the same photo twice until every photo has been sent. For
several chats, list them, as in `1,2`; you can also give days, as in
`mon-fri 07:30` ([more](#timers)). `/timer run 1` runs the timer right away,
so you can see that it works.

That's it: the bot is up and running. Possible next steps: get alerted when
the bot is down or its messages don't get through, with `healthcheck_url`
([how](#health-checks)); add birthdays, name days and your country's
holidays for `/today` ([how](#birthdays-name-days-and-holidays)); create
[specials](#specials) of your own, such as a daily post with the day and the
weather in one message and a heading above the photo, with a shorter name of
your choice; open a shell in the bot's container, which starts with a guide
to its tools (`docker compose exec nejomibot bash`); and set a profile
picture:

```sh
docker compose exec -T nejomibot signal-account.sh profile --avatar - < picture.jpg
```

To update the bot later, see [Updating](#updating).

### Troubleshooting

- **`Invalid configuration (config file: /data/config.toml):`** followed by
  a setting: correct that setting, then run `docker compose restart
  nejomibot`.
- **`Can't read the config file /data/config.toml: Permission denied`** or
  **`Can't write in data_dir /data: Permission denied`:** the `data` folder
  doesn't belong to the bot. Repeat step 3.
- **The bot doesn't reply:** its log must be past the `Waiting` line, and
  `admins` must contain your number in international format, or your Signal
  ID if you have no number. If both are correct, your Signal may be hiding
  your number from the bot, as it does when **Who can see my number** is set
  to **Nobody** in its privacy settings. The bot then knows you only by your
  Signal ID: `docker compose exec nejomibot signal-account.sh identities`
  lists everyone who has written to the bot, by name. Put the ID shown after
  your name, such as `0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e`, in `admins` in
  place of your number, and restart the bot.
- **A group is missing from `/chats`:** Signal only invited the bot. In the
  group's settings, under **Requests & invites**, revoke the invitation, and
  once the bot has replied to you, add it again.
- **`/weather` says `OpenWeatherMap answered with an error (401: Invalid API
  key...)`:** a new key takes up to two hours to become active. Check that
  the key is the one shown on your API keys page.
- **The captcha didn't work:** a captcha is valid for only about a minute.
  Solve a new one and paste it right away.
- **No code arrives:** press Enter when the tool asks for the code, and it
  asks Signal to send it again or to call. Signal's first text message
  sometimes never arrives, while the next one arrives at once.
- **With SELinux** (Fedora, RHEL), the containers may be denied access to
  their folders: add `:Z` to the data and signal volumes in compose.yaml,
  and `,z` to the photos volume (`./photos:/photos:ro,z`).

## Commands

Every command starts with a period or a slash, whichever is easier to type:
`.photo` and `/photo` are the same command, and phone keyboards have the
period on their first page. The bot shows commands with a period, unless
`command_prefix = "/"`. This guide writes them with a slash, as the bot's
files store them.

Everyday commands, for everyone the bot may talk to:

| Command | Reply |
|---|---|
| `/photo`, `/photo <album>` | A random photo from all albums, or from the album named, with the date it was taken, an age if one is set, and a map link (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/photo [<album>] <date>` | A photo taken at the time given, as precisely as you like: in `2017`, in `2017-05`, on `2017-05-14`, or between 15:00 and 16:00 that day with `2017-05-14 15`. It picks one at random, or if there is none, one from the nearest year, month, day or hour that has photos, and says how far off it is. Given to the minute, as in `/photo 2024-06-01 15:00`, it shows the photo taken closest to that moment |
| `/sphoto`, `/sphoto <album>`, `/sphoto [<album>] <date>` | A simple photo: picked as `/photo` picks it, and sent alone, without its caption or heading |
| `/uniquephoto`, `/uniquephoto <album>` | A photo not yet sent in the current round, with the same caption as `/photo`: no photo is sent twice until every photo has been sent, and then a new round starts. Each album has its own round, independent of the others (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/albums` | The albums, which are the folders of the photo library: how many photos each one has, the years they were taken, the birth date its captions count an age from, and its shortcuts |
| `/onthisday`, `/onthisday <album>` | A photo taken on this day in an earlier year, or failing that, within three days of it, from all albums or the album named, with the same caption as `/photo`, under a heading that says how many years ago (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/cache`, `/cache <album>` | The number and total size of the photos in the library, by file type, and how many albums there are; with an album, that album's photos |
| `/today`, `/day` | The date and time, then the day's holidays, and in a group, the birthdays and name days for that group; on a day with none of these, the date and time alone (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)) |
| `/weather`, `/weather <city>` | The current weather in `weather_city`, or in the city named, such as `/weather Helsinki`, under a bold heading, with the day's sunrise and sunset (see [The weather](#the-weather)) |
| `/forecast`, `/forecast <city>` | The weather today and tomorrow in the same place: each day's worst weather, its lowest and highest temperatures, and its chance of rain or snow (see [The weather](#the-weather)) |
| `/info`, `/time` | The current time in the places listed in `clocks`, and the `exchange_rate` |
| `/ping` | `pong!`, and how long the message took to arrive |
| `/fortune`, `/fortune <library>`, `/fortune all`, `/fortune list` | A random fortune from `fortune_library` (`fortunes_svenska` if it isn't set), from the library named, or from all libraries; `list` lists the libraries. The explanation of a proverb in `fortunes_svenska` is shown in italics |
| `/remind <when> <text>`, `/remind`, `/remind remove <n>` | A reminder, which the bot posts in the chat when it is due, such as `/remind tomorrow 08:00 Pick up Bob`. On its own, `/remind` lists the chat's reminders, numbered (see [Reminders and lists](#reminders-and-lists)) |
| `/list`, `/list add <things>`, `/list remove <n>,<n>`, `/list clear` | The chat's list, for example for shopping: `/list add milk, eggs` adds items, and `/list remove 2,5` removes them (see [Reminders and lists](#reminders-and-lists)) |
| `/birthdays` | In a group, the birthdays for that group, upcoming ones first; for admins in a direct chat, all birthdays, numbered (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)) |
| `/namedays` | The name days, listed the same way as `/birthdays` lists the birthdays |
| `/language`, `/language <language>`, `/language default` | The languages the bot speaks, and the one it speaks in this chat. Given a language, by its code or its own name, such as `sv` or `Svenska`, the bot speaks that language in this chat; `default` returns to the `language` setting. In a direct chat, the language is the sender's own choice; in a group, only an admin can change it (see [Languages](#languages)) |
| `/help`, `/help <command>` | The commands the sender may use, a short line each, and the [specials](#specials) the admins let everyone use; for an admin in a direct chat, the admin commands too, by name. `/help photo` explains one command, with examples, by any of its names (see [Help](#help)) |

Everyone the bot may talk to can also use the specials that the admins let
everyone use, with `/special everyone`: they are listed under Specials in
`/help`.

For admins, in a direct chat with the bot:

| Command | Reply |
|---|---|
| `/status`, `/test` | A health check in two messages: first the checks, failed ones first, then the details: the bot and its versions, Signal, the public IP addresses and ASN, the container, and the host |
| `/album <album>`, `/album <album> <date>`, `/album <album> -` | An album: how many photos it has, the years they were taken, the birth date its captions count an age from, and its shortcuts. With a date, such as `2019-06-15`, it sets that birth date; `-` removes it, so that its captions show no age (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/album <album> shortcuts <names>`, `/album <album> shortcuts -` | Other names for `/photo <album>`: `/album Alice shortcuts /alice` makes `/alice` mean `/photo Alice`, and `/alice 2017` mean `/photo Alice 2017`; `-` removes them. A shortcut starts with `/` or `.`: a plain word, which would make every message that starts with it a command, is taken with a `/` |
| `/today preview [<date>]` | What `/today` will say on a given day, such as `10-25`, `2026-10-25` or `tomorrow`, or today if no day is given, in each group the bot is in and in a direct chat |
| `/contacts`, `/safety`, `/contacts <who>` | Everyone the Signal account knows, numbered, each with their name, profile name, username, phone number, Signal ID, About, groups and whether they are verified; with `<who>`, one person, with their safety number too. `<who>` is the person's number in the list you were shown last by `/contacts` or `/trust`, their phone number, their Signal ID or its beginning, or their name (see [Contacts and safety numbers](#contacts-and-safety-numbers)) |
| `/contacts add <who> <name>` | Saves someone as a contact under that name, or renames them. `<who>` is as for `/contacts`; when it is a name, the longest beginning of the message that names someone is used. Someone the bot doesn't know yet can be added by phone number, or by Signal username, as `u:alice.42` or `@alice.42` |
| `/trust`, `/trust <who>` | Everyone's safety numbers, numbered as `/contacts` numbers them and laid out as the Signal apps show them, with whether each one is verified; with `<who>`, one person's |
| `/trust <who> <safety number>` | Marks a safety number as verified, after you have compared it with the one on the person's phone |
| `/allowed` | Who may use the everyday commands, numbered |
| `/allow <who>` | Lets someone use the everyday commands, or lets everyone in a group use them in that group. `<who>` is as for `/contacts`, or a group the bot is in, by name or group ID |
| `/disallow <n>` | Takes that permission away again, by the number shown in `/allowed` (or by phone number, ID or name) |
| `/admins` | The admins: those in the configuration, then those added, numbered |
| `/admin add <who>`, `/admin add <who> <language>`, `/admin remove <n>` | Makes someone an admin, with `<who>` as for `/contacts`, and sends them a welcome message in their language, or in the language given, such as `sv`, which the bot then uses with them; or removes an admin, by their number in `/admins`. Only the admins in the configuration can do this (see [Who may use what](#who-may-use-what)) |
| `/profile` | The bot's Signal profile: its name, About text, username and avatar |
| `/name <name>` | Changes the bot's name |
| `/about <text>`, `/about remove` | The About text shown under the bot's name |
| `/avatar` with a picture, `/avatar remove` | The bot's profile picture: send the picture with `/avatar` as its caption |
| `/username <name>`, `/username remove` | The bot's username, and a link that starts a chat with it |
| `/timers` | The timers: commands the bot runs on a schedule, such as the daily post |
| `/chats` | The chats that timers, `/msg` and `/run` can post to, numbered |
| `/language <chats> <language>` | Sets the language of the chats numbered in `/chats`, people or groups, such as `/language 3,1 sv`; `default` returns them to the configured language (see [Languages](#languages)) |
| `/timer add <when> [<chats>] <commands>` | Adds a timer, for example `/timer add mon-fri 07:30 1,2 /today; /weather; /uniquephoto` |
| `/timer remove <n>`, `/timer run <n>` | Removes a timer, or runs it now |
| `/specials` | Your own [specials](#specials): commands that post text and the answers of other commands |
| `/special add <name> <parts>` | Adds a special or changes one, for example `/special add /morning Good morning! /today + /weather; /uniquephoto` |
| `/special shortcuts <name> <names>`, `/special shortcuts <name> -` | Other names for a special: `/special shortcuts /morning /gm` makes `/gm` post the same as `/morning`; `-` removes them |
| `/special everyone <name>`, `/special admins <name>` | Lets everyone the bot may talk to use the special, in direct chats and in groups, where `/help` lists it; or the admins alone again (see [Specials](#specials)) |
| `/special remove <name>` | Removes a special, unless a timer runs it |
| `/msg <chats> <text>` | Posts the text to other chats, for example `/msg 1,2 Hello!` |
| `/run <chats> <commands>` | Runs commands and posts their answers to other chats, for example `/run 1 /status` |
| `/incoming`, `/incoming <n>,<n>` | The 50 latest messages that anyone other than the admins sent the bot in a direct chat, numbered: when, from whom, and how each one begins. `/incoming 4,9` forwards those two messages to you in full (see [Incoming messages](#incoming-messages)) |
| `/birthday add <date> [<chats>] <who>` | Adds a birthday: a contact's, found the way `/contacts` finds people, shown in the groups they are in; or the birthday of someone not on Signal, by name, shown in the groups numbered in `/chats`, or otherwise in every group. Given again on the same day, someone not on Signal shows in the groups given this time (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)) |
| `/nameday add <date> [<chats>] <who>` | Adds a name day, the same way as `/birthday add` |
| `/birthday remove <n>`, `/nameday remove <n>` | Removes one, by its number in the list that `/birthdays` or `/namedays` showed you last; `/birthday remove 2,5` removes several |
| `/delete list`, `/delete <n>,<n>` | The bot's 50 latest messages, wherever it sent them, numbered: when, where to, and how each one begins. `/delete 2,5,11` deletes those messages for everyone (see [Who may use what](#who-may-use-what)) |
| `/delivery` | Whether the bot's latest messages arrived: the 30 latest (`delivery_messages`), wherever it sent them, newest first, with how many people in each chat received and read each one (see [Delivery](#delivery)) |

For admins, in any chat, including groups:

| Command | Reply |
|---|---|
| `/delete` | Deletes the bot's latest message in the chat for everyone; sent again, it deletes the one before, and so on |
| `/mention all`, `/mention all <text>` | In a group, mentions everyone in it but you and the bot, which notifies them even if they have muted the group; a text, such as `/mention all Dinner's ready!`, comes first (see [Mentions](#mentions)) |

Commands can have other names: a few that the bot has always had (`/test`
for `/status`, `/time` for `/info`, `/safety` for `/contacts`, and `/day` for
`/today`), aliases from the configuration, and the names in each of the
bot's languages, which the bot accepts from anyone, whatever the chat's
language (see [Languages](#languages)). For example, `/väder` is `/weather`,
`/hjälp` is `/help`, `/påminn` is `/remind`, `/lista` is `/list`, and
`/idag` and `/dagen` are `/today`. `/help` shows the names in the chat's
language, as well as the aliases. An album's shortcuts, which admins set
with `/album`, are names for `/photo` with that album (see
[Photos and the daily post](#photos-and-the-daily-post)), and a special's,
set with `/special shortcuts`, are names for the special (see
[Specials](#specials)).

The words that follow a command to say what it should do, its subcommands,
have names in each language too. In Swedish, `lägg till` is `add`, `ta bort`
or `radera` is `remove`, `lista` is `list`, `töm` is `clear`, `kör` is
`run`, `alla` is `all`, `förhandsvisa` is `preview`, `standard` is
`default`, `genvägar` is `shortcuts`, and `för alla` and `för admins` are
`everyone` and `admins`, as in `/lista lägg till mjölk` or `/timer ta bort
3`. The English words work too, in any language.

### Help

`/help` lists the commands the sender may use, a short line each, in groups:
the photos, the day and the weather, reminders and lists, and the rest. Each
line gives the command's other names, the bot's own and the configuration's
aliases, after what it does. The [specials](#specials) the admins let
everyone use follow, and for an admin in a direct chat, the admin commands,
by name, a line for each group. It fits in one message, in every language.

`/help` and a command shows that command's page: its line, then how to use
it, with examples, and on some pages more for the admins, in a direct chat:

```
📝 .list – this chat's list
A shared list, such as for shopping.
.list – the list, numbered
.list add milk, eggs – add things, separated by commas
.list remove 2,5 – take numbers 2 and 5 off
.list clear – take everything off
```

The command can be given by any of its names, with or without its period
or slash: `/help list`, `/help .lista` or an alias. An album's shortcut
shows the page of `/photo`, after what the shortcut stands for, and a
special's name shows what the special posts. `/help` explains only the
commands the sender may use, as it lists them.

### Who may use what

The admins, meaning those listed in the `admins` setting and those they add,
may use every command: the everyday commands wherever those are allowed, and
the admin commands only in a direct chat with the bot, because those
commands show phone numbers and the server's addresses, or change the bot.
An admin is given by phone number, or by Signal ID if they have none or
don't share it. Everyone else may use the everyday commands only if they are on the
[allowed list](#the-allowed-list): as a contact, in a direct chat with the
bot, or as a member of an allowed group, in that group, together with the
[specials](#specials) the admins let everyone use. The bot doesn't reply to
anyone else.

So that nobody can run the bot into Signal's rate limits, the bot answers
each person at most `command_limit` commands (20 by default) in
`command_limit_minutes` (10): past that, it says once when it will answer
them again, and leaves their other commands unanswered until then. The
admins aren't limited, nor are the commands that timers, `/run` and
specials run (see [Signal's rate limits](#signals-rate-limits)).

When someone on the allowed list writes to the bot in a direct chat with
something that isn't a command, the bot greets them: "Hi, I'm Mybot, a bot.
Try /help for a list of commands. Contact Alice for more information." The
names are the bot's profile name and the first admin's name as the bot's
contacts have it (see `/contacts add`), or otherwise their profile name;
without a name, the greeting leaves that sentence out. Each person is
greeted at most once a day, so a thank-you after the greeting doesn't
prompt another one; a restart resets this. Commands are always answered as
usual, never with the greeting, but a mistyped command isn't a command, so
it is greeted. The admins, strangers, groups and edited messages are never
greeted.

The admins in the configuration can make other people admins, in a direct
chat with the bot: `/admin add <who>`, with `<who>` as `/contacts` accepts
it, and `/admin remove <n>`, by their number in `/admins`, which lists every
admin. A new admin receives a welcome message from the bot in a direct chat:
who made them an admin, that `/help` lists every command, a few commands to
start with, as `/help` shows them, and how to see more about any of them.
The welcome is in their language, or
in the language given after them, as in `/admin add 3 sv`, which the bot
then uses with them from then on. Added admins may use every command, as the
configuration's admins may, except that they can't add or remove admins,
and no command can take away what an admin in the configuration may do. The
[notices](#notices-to-the-admins) go only to the admins in the
configuration, timers run their commands as the first of them, and the
greeting names the first one. Added admins are stored by Signal ID, one per
line, in `data_dir/admins.txt`, which has the same format as the
[allowed list](#the-allowed-list) and can also be edited by hand; Signal
IDs are used because a phone number can change hands and a Signal ID
can't. As a result, someone the bot hasn't heard from yet, in a direct chat
or a group, can't be added by phone number, since the bot doesn't know
their Signal ID. A removed admin who is on the allowed list can still use
the everyday commands.

People who don't share their phone number on Signal are known only by their
ID. signal-cli-rest-api provides no way to remove someone from the contacts,
or to forget them, so the bot can't do that either.

The bot marks each command as read, in groups as well as in direct chats,
and shows that it is typing while it works on a command: from the start for
slower commands, and for any other once it has taken a second. It keeps
showing it, as Signal's apps do, until the answer arrives, for two minutes at
most. Both are best effort: if they fail, the answer still arrives.

Signal lets you edit a message for up to a day, and the bot treats an edited
command as if it had arrived instead of the original:

- A command that shows something or sets a value, such as `/weather` or
  `/name`, runs again.
- A command that adds or removes something replaces what the original did:
  the bot first undoes the original's effect, then runs the edit. So
  editing `/remind 18:00 Cake` to `/remind 19:00 Cake` leaves a single
  reminder, at 19:00, and editing `/list remove 2` to `/list remove 3` first
  puts item 2 back. This applies to `/remind`, `/list`, `/birthday`,
  `/nameday`, `/timer add` and `remove`, `/special add` and `remove`,
  `/allow`, `/disallow`, `/admin add` and `remove`, and `/contacts add`,
  which first restores the previous name; a contact it created remains,
  because the bot can't remove contacts.
- What the bot has posted or deleted can't be undone, so an edit of `/msg`,
  `/run`, `/timer run` or `/delete <n>` isn't run, and the bot says so. An
  edit of `/delete` on its own is silently ignored, because anything the bot
  posted in reply would be the next message to be deleted.

The bot remembers what each command did for a day, in memory only. After a
restart, an edit of a message sent before the restart isn't run, because
the bot can't tell what the original did, and the bot says so; send the
command again as a new message instead.

If the bot's account is also in use on another device, such as a phone that
the bot is [linked to](#linking-to-a-phone), a command typed there in a
direct chat looks to the bot as if the other person had sent it (signalbot
can't tell the two apart), so the bot treats it as that person's command,
admin commands included.

`/delete` works in every chat the bot is in, groups included, but only for
admins; from anyone else, it is ignored. It deletes the bot's latest message
in that chat for everyone, then the message before it on the next
`/delete`, and so on. It posts nothing when it succeeds, because anything it
posted would be the next message to go; it replies only when there is
nothing left to delete, or when the deletion failed (the message is then
kept, so you can try again). Signal deletes messages for everyone only
within a day of sending them, so the bot remembers what it sent for a day,
in memory: after a restart, `/delete` reaches only messages sent since then.

In a direct chat with the bot, `/delete list` shows its 50 latest messages,
wherever it sent them, to groups and people alike, newest first and
numbered: when, where to, and how each one begins, with 📷 for a photo.
`/delete 3` then deletes the third of them for everyone, `/delete 2,5,11`
deletes those three, and the bot says which messages it deleted. It deletes
them one at a time and stops at the first one it can't delete, for example
when Signal can't be reached, and says which ones it didn't attempt. The
numbers refer to the list you were shown last, whatever the bot sends in the
meantime, until you ask for the list again or the bot restarts; a list that
a timer, `/run` or a special posts doesn't change them. In a group,
`/delete` accepts nothing after it, because the list covers what was sent to
every chat.

When something fails, such as the weather service, the exchange rate service
or the photo library, the bot posts the error as `Something went wrong: ...`
instead of staying silent, in what timers post as well.

When a message can't be sent, because signal-cli-rest-api is down or the
server has no internet connection, the bot retries it for
`send_retry_hours` (3 by default) and adds a note that the message is late.
It retries after 10 seconds, then less and less often, at most every two
minutes, and immediately whenever another message goes to the same chat,
since that usually means Signal is back. While Signal rate-limits the bot,
it sends nothing at once, since every attempt would meet the limit, and many
could keep it in place: new messages wait too, as do read receipts and the
typing indicator, which aren't sent. The bot tries only the message that has
waited longest, after 2 minutes, then twice as long after each attempt, at
most `rate_limit_retry_minutes` (30) apart, and right away when an admin
sends a command, a minute after the last attempt at the soonest, since the
admin may just have lifted the limit. Once that message goes through, the
rest follow (see [Signal's rate limits](#signals-rate-limits)). Each chat
receives its messages in order. Messages older than the retry period are
dropped, and the chat is told how many once sending works again. Only
failures where the message was certainly not sent are retried:
signal-cli-rest-api couldn't be reached, or it answered with an error, which
it does when no recipient got the message, when Signal rate-limits the bot,
or when the request itself was invalid. A timeout or a dropped connection
may happen after Signal received the message, so those are only logged,
because a retry would post the message twice. `/status` shows how many
messages are waiting.

Waiting messages survive a restart: a message that has waited for half a
minute is saved in `data_dir/outbox`, one file per message, until it is sent
or dropped, and every waiting message is saved when the bot stops. Once the
bot has started again, it sends them, still with the note that they are
late. A short wait, such as while signal-cli-rest-api restarts, writes
nothing to disk.

### Delivery

Signal's apps confirm each message they receive with a delivery receipt, and
each message that is read with a read receipt, unless read receipts are
turned off in their settings. The bot keeps these receipts for the messages
it sent in the last day, in memory, so a restart forgets them. `/delivery`,
for admins in a direct chat, shows the bot's `delivery_messages` (30) latest
messages, wherever it sent them, newest first: when, where to, how each one
begins, and how many people in the chat received it and read it, as in
`📬 3/4 · 👀 2`. A message that nobody has confirmed yet shows ⏳, and after
10 minutes without any confirmation, ⚠️. The log records that as a warning
too: Signal accepted the message, but it may not have arrived. With
`log_level = "DEBUG"`, the log shows how many people each message reached
within those 10 minutes. The [health checks](#health-checks) fail when no
phone has confirmed three messages in a row within `unconfirmed_hours`.

A message longer than 2,000 bytes is sent the way Signal's apps send one:
signal-cli puts the beginning of the text in the message and the full text
in a text attachment, which the apps show behind **Read more**, so nothing
is cut off or rejected, and it stays a single message. A long message sent
to the bot also arrives in full:
signal-cli fetches its text even with `JSON_RPC_IGNORE_ATTACHMENTS=true`.

### The weather

`/weather` shows the current weather in `weather_city`, from OpenWeatherMap,
under a bold heading that names the place as `weather_city_name`, if that is
set. `/weather Helsinki` shows the weather in Helsinki, under a heading that
names the place OpenWeatherMap found, in the bot's language where
OpenWeatherMap has a name for it in that language, with its state or region
and country: "Weather in Helsinki, FI", or in Swedish "Vädret i Helsingfors,
FI".

OpenWeatherMap finds places by name, the best known first, and the bot takes
the first match: `/weather Stockholm` is Stockholm, SE, not Stockholm,
Maine, and `/weather Springfield` is Springfield, Illinois. A country code
([ISO 3166](https://en.wikipedia.org/wiki/ISO_3166-1_alpha-2)) after a comma
selects the country, and in the US, a state code selects the state:
`/weather Stockholm,US`, `/weather Springfield,MO,US`. A misspelled name may
still find a place, as `Stokholm` finds Stockholm, SE; the heading shows
which place it found.

The bot looks up each name only once, since places don't move, and keeps
each place's weather for 10 minutes, since OpenWeatherMap updates its data
every 10 minutes: when asked again sooner, by any name of the place, the bot
answers from what it has, without asking OpenWeatherMap. For places named
after `/weather`, it asks OpenWeatherMap at most `weather_calls_per_hour`
times an hour (10 by default), lookups included, so a new place takes two
calls; beyond that, it says when to try again. `weather_city` doesn't count
toward this limit, so `/weather` and `/forecast` on their own, and
`/status`, always get its weather.

The weather ends with the day's sunrise and sunset at the place, and the
daylight between them, in the place's own time, from the same answer from
OpenWeatherMap: `🌅 07:35 · 🌇 17:21 · 9 h 46 min of daylight`. Where the
sun doesn't both rise and set that day, this line is left out.

`/forecast` shows the weather today and tomorrow in `weather_city`, or in a
place named as for `/weather`, from OpenWeatherMap's three-hourly forecast.
For each day, it shows the worst weather between 06:00 and 21:00 local time
(a thunderstorm first, then snow, rain, drizzle, mist and the like, clouds,
and a clear sky last), the lowest and highest temperatures, and the highest
chance of rain or snow, if any. Late in the evening, once today has no
daytime left, it shows tomorrow and the day after. The bot keeps a place's
forecast for 30 minutes, and counts the calls for named places the same way
as for `/weather`:

```
Forecast for Stockholm
Today: 🌦️ Light rain
🌡️ 6 to 12°C · ☔ 80%
Tomorrow: ☁️ Overcast clouds
🌡️ 3 to 12°C · ☔ 20%
```

### Photos and the daily post

The daily post is a timer: `/timer add 08:00 1,2 /today; /weather;
/uniquephoto` posts at 08:00 in the bot's `timezone`, whatever the server's
own time zone, to chats 1 and 2 of `/chats`. It posts the date and time
with the day's holidays, and in a group, the birthdays and name days for
that group (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)),
then the weather under its bold heading, then a photo. Every chat gets the
same weather and the same photo. To have the day and the weather in one
message, and a heading above the photo, make the post a [special](#specials),
with "Photo of the day!" formatted in bold in Signal, and give it a shorter
name if you like:

```
/special add /dailypost /today + /weather; Photo of the day! /uniquephoto
/special shortcuts /dailypost /daily
/timer add 08:00 1,2 /dailypost
```

Each folder directly inside `photos_dir` is an album, named after the
folder, and its subfolders belong to it; photos directly in `photos_dir`
belong to no album, but are included among all photos. `/albums` lists the
albums. A command names an album in any letter case, by the longest album
name that the text after the command starts with, so names may contain
spaces: `/photo Alice and Bob`. Admins can give an album shortcuts, which
are other names for `/photo` with that album: `/album Alice shortcuts /alice
/al` makes `/alice` and `/al` mean `/photo Alice`, so `/alice 2017` means
`/photo Alice 2017`, and `/album Alice shortcuts -` removes them. A shortcut
is a single word that starts with `/` or `.`, and can't be a name the bot
already responds to: a command, an alias or a special. A plain word, which
would make every message that starts with it a command, is taken with a
`/`: `alice` becomes `/alice`, also in `albums.txt` from before 0.99.20.

`/uniquephoto` picks a random photo among those not yet sent in the current
round, and records it as sent; once every photo has been sent, a new round
begins. Each album has its own round: `/uniquephoto Alice` picks among
Alice's photos not yet sent, and once all of hers have been sent, her round
starts over. A photo sent in one round counts in the others too, and a
round that starts over leaves the others as they are, so no round sends a
photo twice: the daily post's `/uniquephoto` sends every photo once before
it starts over, whatever album rounds run in between. Anyone allowed may
use it, and each use takes up a photo of the round. `/photo` picks from all
photos, or from the album's, and neither it nor `/sphoto` nor `/onthisday`
counts toward the rounds. `/sphoto` picks as `/photo` does, and sends the
photo alone, without its caption or heading.

The library's round is listed in `data_dir/sent-photos.txt`, and the
albums' rounds in `data_dir/album-rounds.txt` (temporary files in debug
mode), by the photos' paths within the library, so rounds survive restarts.
Deleting `sent-photos.txt` starts the library's round over; removing an
album's lines from `album-rounds.txt` starts its round over.

`/photo 2017` shows a random photo taken in 2017, and you can be as precise
as you like: `/photo 2017-05` shows one taken in May 2017, `/photo
2017-05-14` one taken that day, and `/photo 2017-05-14 15` one taken between
15:00 and 16:00 that day. If there is none in that period, it shows one from
the nearest year, month, day or hour that has photos, under a heading that
says how far off it is, such as "Nearest to 2018: 1 year before". Given to
the minute, `/photo 2024-06-01 15:00` shows the photo taken closest to that
moment, in the bot's `timezone`, such as "Nearest to 2024-06-01 15:00: 8 min
before". With an album name first, as in `/photo Alice 2019-03-14`, it picks
from that album only. A photo that doesn't record when it was taken is never
the nearest, but can still be picked at random. The time a photo was taken
is the one its caption shows: the bot reads it for each photo, from the
file's header, in the background as it starts, and keeps it in memory, about
400 bytes per photo, and between starts in `data_dir/photo-index.txt`. A
start reads only the photos added or changed since; the bot also reads a
photo again when its file changes, and a photo added later when one of these
commands first needs it. Reading every photo, as the first start does, took
47 seconds for 7,671 photos on a Raspberry Pi 4, and until it has read them,
a `/photo` with a date, `/albums` or `/onthisday` waits for it. Deleting
`photo-index.txt` only makes the next start read every photo again, as does
a change of `timezone` or `photos_timezone`.

JPEG and the other formats are sent as they are. HEIC/HEIF photos are
converted to JPEG on the fly, with a warning in the log, since not every
Signal client can display them. It is better to convert them once and for
all with [tools/tidy-photos.sh](tools/tidy-photos.sh); then
`photos_heif = false` leaves HEIC/HEIF files out of the library and saves
the 3 MB or so of memory needed to open them.

The caption gives the time the photo was taken in the bot's `timezone`,
wherever it was taken. The EXIF DateTimeOriginal tag holds the local clock
time where the photo was taken, in the time zone of the offset saved with
it; without an offset, the photo is assumed to be from `photos_timezone`
(the bot's `timezone` if that isn't set). Some phones, however, save
DateTimeOriginal in UTC and CreateDate in local time, whatever offset they
record: a CreateDate that is a whole time zone away gives this away, and
tidy-photos.sh relies on the same sign. (tidy-photos.sh names files after
the local time, so a caption can differ from the file name by an hour or
two.)

A caption can also give an age. For an album of one child or pet growing
up, each photo can show how old they were when it was taken: give the album
their birth date, and the bot counts from it to the day the photo was
taken, as in "🎂 1 year, 2 months and 3 days", after `photos_age_emoji` (🎂
by default). `/album Alice 2019-06-15` sets an album's birth date, `/album
Alice -` removes it, and `/album Alice` shows the album. An album has no
birth date until you set one, and `photos_birth_date` is the birth date for
the photos in no album; without a birth date, captions show no age. Birth
dates are stored with the shortcuts in `data_dir/albums.txt`, one album per
line, and the file can be edited by hand: the bot reads it again when it
changes.

A photo with a GPS position links to where it was taken: on Google Maps, or
with `photos_map = "openstreetmap"`, as an OpenStreetMap short link, such as
`https://osm.org/go/0bC2KJ9q?m=`, which shows a marker at the spot.

`/onthisday` shows a photo taken on this day in an earlier year, with the
same caption as `/photo`, under "3 years ago today" in bold; if there is
none, it shows a photo taken within three days of the date, the nearest
first, under "3 years ago, around this day". `/onthisday Alice` picks from
that album only. Like `/photo`, it doesn't count toward the round.

### Reminders and lists

`/remind` is available to everyone allowed: it sets a reminder, which the
bot posts once, when it is due, in the chat where it was set; in a group,
for everyone in it:

```
/remind 18:00 Take the cake out     today, or tomorrow if 18:00 has passed
/remind 30m Call Bob                in 30 minutes; also 2h, 1h30m, in 2h
/remind tomorrow 08:00 Pick up Bob
/remind fri 17:00 Pizza!            the coming Friday
/remind 2026-12-24 15:00 Presents!
/remind                             the chat's reminders, numbered
/remind remove 2                    or 2,3
```

When a reminder is due, in the bot's `timezone`, the bot posts "⏰ Pick up
Bob" in the chat; in a group, "⏰ @Alice Pick up Bob", mentioning whoever set
it (see [Mentions](#mentions)). It checks at the start of every minute. A
chat can have at
most 20 reminders, at most a year ahead; for a weekly reminder, an admin can
set up a [timer](#timers). A reminder that fell due while the bot was down
is posted once the bot is back up, with a note that it is late; if it is
more than a day late, it is dropped. A group receives its reminders only
while the bot is a member. In Swedish, the command is `/påminn`, and
`om 30m` means `in 30m`.

`/list` keeps one list per chat, for example for shopping, which everyone in
a group shares:

```
/list                     the list, numbered
/list add milk, eggs      add items, separated by commas or line breaks
/list remove 2,5          remove items by their numbers
/list clear               remove everything
```

A list holds at most 100 items. In Swedish, the command is `/lista`.

Reminders and lists are stored in `data_dir/reminders.txt` and
`data_dir/lists.txt`, one per line, and the files can be edited by hand: the
bot reads them again when they change, and leaves comments and lines it
can't read as they are. A reminder's line also says who set it, by Signal ID
or phone number; a line without it is read too, as one whose reminder
mentions nobody. Timers, specials and `/run` can't run these commands,
because each chat's reminders and list are its own.

### Mentions

A mention, @ and a name in a group, notifies that person even if they have
muted the group, which no other message does. The bot keeps the mentions
that people type into its commands: `/remind 18:00 @Bob Call Grandma`
posts a reminder that mentions Bob, and an item added with `/list add`
shows the mention it was given. A reminder in a group also mentions whoever
set it. In its files, the bot writes a mention as `<@ID>`, by Signal ID or
phone number, and you can write one by hand the same way.

`/mention all` works in every group the bot is in, but only for admins;
from anyone else, it is ignored. The bot posts 📣, then a mention of
everyone in the group but you and itself; a text after the command comes
first, as in `/mention all Dinner's ready!`. Timers, specials and `/run` can
run it too: each group they post to gets its own members mentioned, and a
direct chat the text alone. In Swedish, the command is `/nämn alla`.

### Birthdays, name days and holidays

`/today` (or `/day`) describes the day: the date and time, in the bot's
`timezone`, then, in every chat, the day's holidays, flag days and
traditions in the countries named in `holidays`, by the codes below, such as
`holidays = ["SE", "GR"]` (none by default), each after its country's flag;
a day that two of the countries share is listed once, after both flags. In
a group, it also lists the birthdays and name days for that group:

```
📅 Saturday 6 June · 08:00
🇸🇪 National Day of Sweden · flag day
🎂 Alice turns 36 today!
🌸 Happy name day, Bob!
```

On a day with none of these, it shows the date and time alone.

- Sweden: its public holidays and their eves, its flag days
  ([förordning 1982:270](https://lagen.nu/1982:270)), the Sundays of Advent,
  and Shrove Tuesday, Valentine's Day, Walpurgis Night, Mother's Day,
  Father's Day and Lucia. The day of the Riksdag election, the second Sunday
  of September every fourth year, is a flag day; so is the day of the
  European Parliament election, but its date is set anew each time, so it
  isn't included.
- Greece: its public holidays, which follow the Orthodox Easter, as well as
  Tsiknopempti, Maundy Thursday, Holy Saturday, Valentine's Day, Mother's
  Day, Father's Day, Christmas Eve and New Year's Eve.
- The other countries: their public holidays, meaning those the whole
  country observes, each on its own date rather than on a substitute day off;
  Valentine's Day, Easter Sunday, Christmas Eve and New Year's Eve; and the
  days listed in the table. Mother's Day and Father's Day are included where
  the whole country observes them on the same day. Their names are in
  English, whatever language the bot speaks, except for the days they share
  with Sweden or Greece, which are translated.

| Code | Country | In addition to its public holidays |
|---|---|---|
| `AT` | Austria | Mother's and Father's Day, Advent, St Nicholas' Day |
| `AU` | Australia | Mother's and Father's Day, Remembrance Day |
| `BE` | Belgium | Mother's and Father's Day, St Nicholas' Day |
| `BG` | Bulgaria | Holidays that follow the Orthodox Easter |
| `CA` | Canada | The federal holidays; Mother's and Father's Day, St Patrick's Day, Halloween |
| `CH` | Switzerland | The holidays most cantons observe; Mother's and Father's Day, the Federal Day of Prayer, Advent, St Nicholas' Day |
| `CY` | Cyprus | Holidays that follow the Orthodox Easter; as in Greece, Tsiknopempti, Maundy Thursday, Holy Saturday, Mother's and Father's Day |
| `CZ` | Czechia | Mother's and Father's Day, Walpurgis Night |
| `DE` | Germany | Mother's and Father's Day (Ascension Day), Advent, St Nicholas' Day |
| `DK` | Denmark | Mother's and Father's Day, Constitution Day, Midsummer Eve, Advent |
| `EE` | Estonia | Mother's and Father's Day, Walpurgis Night, Midsummer Eve |
| `ES` | Spain | Mother's and Father's Day |
| `FI` | Finland | Mother's and Father's Day, Shrove Tuesday, Walpurgis Night, Advent |
| `FR` | France | Mother's and Father's Day, Shrove Tuesday |
| `GB` | United Kingdom | The bank holidays of England and Wales; Mother's and Father's Day, the patron saints' days, Shrove Tuesday, Halloween, Guy Fawkes Night, Remembrance Sunday |
| `GR` | Greece | See above |
| `HR` | Croatia | Mother's and Father's Day |
| `HU` | Hungary | Mother's and Father's Day |
| `IE` | Ireland | Mother's and Father's Day, Shrove Tuesday, Good Friday, Halloween |
| `IS` | Iceland | Mother's and Father's Day, Shrove Tuesday, Advent |
| `IT` | Italy | Mother's and Father's Day |
| `LT` | Lithuania | |
| `LU` | Luxembourg | St Nicholas' Day |
| `LV` | Latvia | Father's Day |
| `MT` | Malta | Mother's and Father's Day |
| `NL` | Netherlands | Mother's and Father's Day, Remembrance of the Dead, Liberation Day, Sinterklaas |
| `NO` | Norway | Mother's and Father's Day, Midsummer Eve, Advent |
| `NZ` | New Zealand | Mother's and Father's Day, Guy Fawkes Night |
| `PL` | Poland | Mother's and Father's Day, Fat Thursday, St Nicholas' Day |
| `PT` | Portugal | Mother's and Father's Day, Shrove Tuesday |
| `RO` | Romania | Holidays that follow the Orthodox Easter; Mother's and Father's Day |
| `SE` | Sweden | See above |
| `SI` | Slovenia | Mother's and Father's Day |
| `SK` | Slovakia | Mother's and Father's Day |
| `US` | United States | The federal holidays; Mother's and Father's Day, St Patrick's Day, Halloween |

The admins manage birthdays and name days in a direct chat with the bot:

```
/birthday add 1990-03-14 Alice       a contact; with the year, the age is shown
/birthday add 03-14 Bob              without the year, it isn't
/birthday add 1940-05-01 1 Grandma   someone not on Signal, shown in chat 1 of /chats
/birthday add 1940-05-01 Grandma     someone not on Signal, shown in every group
/nameday add 08-08 Alice
/birthday remove 2                   by its number in /birthdays
```

Someone on Signal is given the way `/contacts` accepts people, by name, phone
number or ID, and must be a contact saved under a name with `/contacts add
<who> <name>`. Their days show in the groups they are in, under their name
as the contacts have it at the time, so a rename takes effect. A contact has
one birthday and one name day: adding another replaces it. Someone not on
Signal is given by a name that no contact has, and their days show in the
groups given by their numbers in `/chats`, or otherwise in every group.
Given again on the same day, they show where the new one says instead:
after `/nameday add 08-08 Grandma`, which shows in every group,
`/nameday add 08-08 1,2 Grandma` shows it in chats 1 and 2 alone. The reply
says which of the two it took, so a mistyped contact name is easy to spot,
and after one for every group, how to choose the groups. Birthdays and name days never show in a direct chat. A birthday on
29 February is shown on the 28th in other years.

To see what `/today` will say on a day before it comes, admins can send
`/today preview 10-25` (in Swedish, `/idag förhandsvisa 10-25`), or
`/today preview` for today. It shows what `/today` says in each group the
bot is in, and in a direct chat.

`/birthdays` and `/namedays`, available to everyone allowed, list them,
upcoming ones first: in a group, those for that group; in a direct chat, for
admins, all of them, numbered, with where each person not on Signal is
shown. As with `/delete list`, `/birthday remove` and `/nameday remove` use
the numbers of the list you were shown last, whatever changes in the
meantime, until you ask for the list again or the bot restarts; if an entry
has been removed or changed since then, the reply names it. They are stored
in `data_dir/birthdays.txt`, one per line, with a contact's Signal ID and
phone number, and their name as it was saved, which is shown if the
contacts can't be read. Like the other files, it can be edited by hand.

### /status

`/status` replies in two messages, to fit Signal's narrow message bubbles.
The first lists the checks: how many passed (`✅ All 13 checks passed`, or
`❌ 2 of 13 checks failed`), the failed ones with what went wrong, then the
others, one short line each; a check that took a second or longer shows how
long it took. The second message has the details, a section for each, in
short lines:

- **Bot:** the versions of nejomibot, signalbot, Python and
  signal-cli-rest-api; its time zone, `timezone`, which all the times the bot
  shows are in, without it being repeated each time; its uptime; the next
  timer run; the messages waiting to be sent again; and how long the command
  took to arrive. signal-cli's version isn't included, because
  signal-cli-rest-api doesn't report it.
- **Signal account:** the profile, as `/profile` shows it, with the phone
  number or Signal ID; the contacts and who is blocked, the safety numbers (naming those that are new or have changed in
  the last week), the groups, and the linked devices.
- **Internet:** the public IPv4 and IPv6 addresses (from Cloudflare's
  `/cdn-cgi/trace`, requested over each), their reverse DNS names, and from
  [RIPEstat](https://stat.ripe.net/), the ASN, its holder, the announced
  prefix and the city. `IPv6 none (...)` means the container has no IPv6
  route, even if the host has one.
- **Container:** threads, open files, CPU time, local IP addresses and DNS
  servers.
- **Host:** hardware, CPU, kernel, uptime, load, pressure (the share of the
  last minute during which tasks waited for the CPU, memory or I/O), memory,
  swap, and CPU and NVMe temperatures. These are read from `/proc` and
  `/sys`, which describe the whole machine, so this works in the
  unprivileged container and still describes the server.

The checks, all performed live: the four [health checks](#health-checks)
(signal-cli-rest-api, the bot itself, Signal's servers through the account,
and the delivery of the bot's messages), then whether every safety number is
trusted, nobody the bot talks to is blocked, the bot is still in every group
on the allowed list, OpenWeatherMap and the exchange rate API (if
`exchange_rate` is set) respond, the photo library isn't empty, disk and
memory use are below 90% of their limits, and NTP keeps the clock
synchronized. A check that takes longer than 20 seconds fails.

### Incoming messages

The bot keeps the 50 latest messages that anyone other than the admins sends
it in a direct chat, commands and messages from strangers included, in
memory only: a restart forgets them. A message that its sender deletes for
everyone is removed from the bot too, as is a disappearing message once its
time is up, and an edit replaces the message it edits.

`/incoming`, for admins in a direct chat, lists these messages, newest first
and numbered: when, from whom (by their name in the account's contacts,
otherwise by their profile name, otherwise by their number), and how each
one begins, with 📎 for attachments. `/incoming 4,9` forwards messages 4 and
9 of the list to you, each as a message of its own, in full and with its
formatting, so you can read it in full or forward it on in Signal. Only the
text is forwarded, since the bot doesn't download attachments; it says how
many there were. As with `/delete list`, the numbers refer to the list you
were shown last; a list that a timer, `/run` or a special posts doesn't
change them. Timers and `/run` can run `/incoming` too: `/run 1 /incoming
4,9` forwards messages 4 and 9 of your list to chat 1. The latest messages
in every chat, groups included, are listed in [a
terminal](#the-bot-from-a-terminal) only.

### Contacts and safety numbers

`/contacts` lists everyone the bot's Signal account knows, numbered: first
its contacts, then everyone else it knows, such as the members of its
groups, then anyone it only has a safety number for. Each person is shown by
name, with everything the bot knows of them on a line each, in the way
`/profile` shows the bot: the name they gave themselves in Signal, where it
differs from the one in the contacts; their Signal username, such as
`@alice.42`, where signal-cli knows it; their phone number, or that they
don't share it; their Signal ID; their About; the groups they share with the
bot; whether they're blocked; and whether their safety number is verified.
The bot itself is neither listed nor counted, since its own safety number
isn't anyone's to compare. `/contacts <n>` shows one person the same way,
followed by their safety number. Signal doesn't share usernames: signal-cli
knows only the usernames of people it found by username, as
`/contacts add u:alice.42 Alice` does, so most people are shown without one.
`/trust` lists the same people under the same numbers, with their safety
numbers, shown as three rows of four groups of five digits, as the Signal
apps show them, and whether each is verified. A number from the list you
were shown last by either command stands for that person wherever a command
accepts `<who>`:

```
/contacts 3                  that person, with their safety number
/trust 3                     their safety number
/trust 3 12345 67890 ...     mark it verified, after comparing it with their phone
/contacts add 3 Bobby        save them as a contact under that name
/contacts add u:bob.42 Bob   someone new, by Signal username
/allow 3                     put them on the allowed list
/admin add 3                 make them an admin
```

As with `/delete list`, the numbers refer to the list you were shown last,
whatever changes in the meantime, until you ask for it again or the bot
restarts; each admin has their own numbering. A name, a phone number, or a
Signal ID or its beginning works too. To verify someone, compare the safety
number with the one their phone shows in their chat with the bot (tap the
bot's name, then **View safety number**), in person or on a call you trust,
then send it with `/trust`. `/birthday add` doesn't accept list numbers for
`<who>`, because numbers there refer to chats.

## Posting to other chats

`/msg` and `/run` let an admin post to other chats from a direct chat with
the bot. The chats are those numbered by `/chats`, given as a single word,
such as `1,2`:

```
/chats                                 the chats they can post to, numbered
/msg 1,2 Dinner at six!                the text, to chats 1 and 2
/run 1 /status                         the status, in chat 1
/run 1,3 /weather; /photo              the weather, then a photo
```

`/msg` posts the text as the bot. `/run` runs each command the way a timer
does, as you would in a direct chat with the bot, with numbers referring to
the lists you were shown, and posts its answers to the chats, one command
after the other; every chat gets the same photo. Like a timer, `/run` can't
change timers, specials, birthdays, albums or who may use the bot, can't
run `/msg` or `/run`, and can't run the commands that belong to each chat:
`/remind`, `/list`, `/birthdays` and `/namedays`. Be careful about what you
post where: `/status` shows phone numbers and the server's addresses to
everyone in the chat. Both commands reply with where they posted, and where
a message is only waiting to be sent (see
[Who may use what](#who-may-use-what)) or may not have arrived; when `/run`
posts to the admin's own chat, its answers speak for themselves. From [a
terminal](#the-bot-from-a-terminal), `/msg` also posts pictures and other
files.

## The bot from a terminal

`nejomibot-chat`, in the bot's image, lets you use the bot from a terminal
on the server, as the first admin in the configuration uses it in a direct
chat with the bot. You type a message, and the bot's answers appear in the
terminal instead of in Signal. Everything else happens as it would in that
direct chat: `/msg` and `/run` post to their chats, a reminder set with
`/remind` reaches that admin in Signal, and the lists that `/incoming`,
`/contacts` and `/delete list` number are numbered for that admin, so a
list shown in the terminal sets the numbers on their phone too, and the
other way round. No read receipt or typing indicator goes to Signal, since
no message came from there.

```sh
podman exec -it nejomibot nejomibot-chat                  # a chat: a line is a message
podman exec nejomibot nejomibot-chat /weather Helsinki    # one message, and its answers
echo "/msg 1 Dinner at six" | podman exec -i nejomibot nejomibot-chat
```

In the chat, each line is a message. A line that ends in `\` continues on
the next line, for a message of several lines, and Ctrl-D ends the chat.
Without a message on the command line and without a terminal, the tool
reads one message from standard input, all of it, which `podman exec -i`
passes on. Quote a message that has a `;` or other characters the shell
treats specially, as in `nejomibot-chat "/run 1 /weather; /photo"`. With
Compose, run `docker compose exec nejomibot nejomibot-chat`, with `-T` in
place of `-i` for standard input.

### Attaching files

`-a FILE` attaches a file to the message, and can be given more than once.
`-a -` attaches standard input: a single file, or several in a tar archive.
Standard input is the simplest way to get a file into the container:

```sh
podman exec -i nejomibot nejomibot-chat -a - "/msg 1,2 Look!" < photo.jpg
tar -c *.jpg | podman exec -i nejomibot nejomibot-chat -a - --to 1 Our trip
podman exec -i nejomibot nejomibot-chat -a - /avatar < logo.png
```

`/msg` posts the files with its text, or without one, as in `/msg 1,2`.
`--to CHATS` is short for `/msg CHATS`, followed by the text given on the
command line or on standard input, as in `echo "Dinner at six" | podman
exec -i nejomibot nejomibot-chat --to 1,2`. `/avatar` makes an attached
picture the bot's profile picture, which it can't do from Signal while
signal-cli doesn't keep attachments (see [The bot's
profile](#the-bots-profile)). The files can come to 25 MB together, as they
pass through the bot's memory on their way to Signal. Files that are
already in the container need no standard input, as in
`-a /photos/2024/IMG_1234.jpg` for a photo in the library.

### Messages the bot received

The bot keeps the 100 latest messages it receives, in every chat, those
from groups and from the admins included. It keeps them in memory only, as
for `/incoming`: a restart forgets them, an edit replaces the message it
edits, and a message that its sender deletes for everyone, or that
disappears, is removed. `--recent` lists them, oldest first, and
`--follow` shows each new one as it arrives, until you press Ctrl-C:

```sh
podman exec nejomibot nejomibot-chat --recent 20
podman exec nejomibot nejomibot-chat --recent 10 --follow
```

Each message is shown with when it was sent, in the bot's time zone, the
group or direct chat it was sent in, who sent it, and its text, with 📎 and
the number of its attachments. `/incoming` is unchanged: it lists only the
direct messages from people other than the admins.

By default, only the number of attachments is kept. With
`received_attachments = true` in the settings, each file is listed too, by
name, type and size, and `--save` saves it. The files stay with signal-cli,
which keeps them only when signal-cli-rest-api's container has
`JSON_RPC_IGNORE_ATTACHMENTS=false`. The bot keeps no copy of its own, only
where signal-cli keeps each file, so the setting costs no memory; it
fetches a file only to save it, and only one of up to 25 MB.

### Output for scripts

`--json` prints what the bot says as JSON, one object per line, for scripts
and `jq`. An answer has its `text`, its `styles` (Signal's text styles,
each with where it starts in the text and how long it is, in characters),
and its `files`, each with its `content_type`, `filename`, `size` and
contents in `base64`. A received message has `at`, `chat` (the group's ID,
or `null` in a direct chat), `chat_name`, `sender`, `sender_name`, `text`,
`styles`, `attachments` (how many), `files` and `edited`. `--save DIR`
saves the files in what the bot says to the folder `DIR`, readable only by
the bot's user, and shows where each one is instead; in JSON, `saved` takes
the place of `base64`:

```sh
podman exec nejomibot nejomibot-chat --json /photo | jq -r '.files[0].base64' | base64 -d > photo.jpg
podman exec nejomibot sh -c 'mkdir -p /data/saved && nejomibot-chat --save /data/saved /photo'
```

In a terminal, the answers show Signal's bold, italic, strikethrough and
spoilers as terminal styles, unless the `NO_COLOR` environment variable is
set. `nejomibot-chat` exits with 0 once the bot has answered, even with no
answer, as for a message that isn't a command; with 1 if it can't ask the
bot, or the bot refuses; and with 2 for options it doesn't take.

`nejomibot-chat` talks to the running bot over a local socket and needs no
setup. Only the bot's own user and root can use it, since any process in
the bot's network, which it shares with signal-cli-rest-api, can reach such
a socket. Outside a container, `uv run nejomibot-chat` in the bot's folder
reaches a bot started there with `uv run nejomibot`.

## The allowed list

Who may use the everyday commands, besides the admins, is set by a list
that the admins manage from a direct chat with the bot:

```
/allowed                  who is on the list, numbered, and the admins
/allow +46701234567       a phone number
/allow 3                  someone in /contacts, by their number there
/allow Alice              someone in /contacts, by name or the start of their ID
/allow Family             a group the bot is in, by name or by group ID
/disallow 3               by number in /allowed, or by phone number, ID or name
```

The list is stored in `data_dir/allowed.txt`, one phone number, Signal ID or
group ID per line, followed by a `#` and who it is:

```
group.abcd…=  # Family
+46701234567  # Alice
```

The file can also be edited by hand: the bot checks for changes every couple
of seconds, and leaves comments and lines it can't read as they are
(`/allowed` lists those). The file is written through a temporary file, so
the bot never reads a half-written list, and only the bot's user can read
it, because it contains phone numbers. The bot creates the file, empty, the
first time it runs; deleting it starts a new, empty list.

The commands won't allow the bot itself, allow someone twice, or disallow an
admin, who keeps every command whatever the list says. `/disallow` on a
group lists the timers that still post there, because timers post to their
chats regardless of who may use the bot.

### Names and phone numbers

The bot shows people by the name signal-cli has for them, or otherwise by
what the list has after their `#`, with their phone number where it is
known, as in `Alice (+46701234567)`, or otherwise with their Signal
username, as in `Alice (@alice.42)`. This applies to `/allowed`, `/admins`,
`/chats`, `/timers`, `/delete list`, `/delivery`, `/incoming`, and the
replies of `/msg` and `/run`.

signal-cli knows someone who doesn't share their number in Signal only by
their Signal ID, so a phone number on the list could neither show their name
nor match the messages they send the bot directly, which arrive without the
number. The bot therefore looks such numbers up, once each: at startup, for
every number on its lists that signal-cli doesn't know yet, and when
`/allow` adds one. Signal says whose number it is, unless its owner has
chosen not to be findable by number, and signal-cli then keeps the number
and the ID together, so the person's name shows, and their direct messages
match the list. Signal limits how many numbers an account may look up, so
the bot never asks about the same number twice in one run. Someone who
can't be found by number can be allowed by their Signal ID, through `/allow`
with their number in `/contacts`. Once the bot knows a name, it writes it
after the `#` of any line in its lists that has none, so the files show who
is who too.

## Timers

A timer runs bot commands on a schedule and posts their answers to one or
more chats, as the daily post does. Admins manage timers in a direct chat
with the bot:

```
/chats                                     the chats timers can post to, numbered
/timer add 08:00 1,2 /today; /weather; /uniquephoto   a daily post, to chats 1 and 2
/timer add mon-fri 07:30 1 /weather; /info to chat 1
/timer add tomorrow 18:00 1 /photo         once
/timer add every 2h /status                without chats: to you
/timers                                    the timers, with their next run
/timer remove 3
/timer run 3                               run it now, to try it
```

`/chats` numbers the groups the bot is in, by name, then the people on the
allowed list, then the admins, so a timer's chats are a few numbers that are
easy to type on a phone. `<when>` is a time (`08:00`, or `08:00,18:30`),
days and a time (`mon-fri 07:30`, `sat,sun 10:00`, `weekdays`, `weekends`),
a date and a time for a single run (`YYYY-MM-DD 15:00`, `tomorrow 08:00`),
or an interval such as `every 2h` (no shorter than 10 minutes), all in the
bot's `timezone`. The bot's language may add words of its own: in Swedish,
`mån-fre`, `vardagar`, `helger`, `imorgon` and `varje 2h`. The commands,
each with its `/`, are separated by `;`.

A timer runs each command once, as an admin would in a direct chat with the
bot. It can therefore run any command except those that change timers,
specials, birthdays, albums or who may use the bot, those that post to other
chats themselves (`/msg`, `/run`), those that belong to each chat
(`/remind`, `/list`, `/birthdays`, `/namedays`), and `/delete` and
`/contacts add`: run from a timer, `/delete` would delete the bot's latest
message in the first admin's direct chat, and a number, as in `/delete 3`
or `/contacts add 3 Bob`, would name whatever has it by the time the timer
runs. It posts each command's
answers to all the timer's chats before the next command runs: every chat
gets the same photo, and each group its own birthdays. Commands that only
show something can run, wherever the timer posts: `/delivery` at 08:15 to
your own chat, for example, or `/chats`, `/allowed`, `/admins`,
`/incoming`, `/today preview`, and `/timers` and `/specials` on their own
(with more after them, they change things). Timers can also run your own
[specials](#specials).

Timers are stored in `data_dir/timers.txt`, one per line, with fields
separated by `|`: the timer's number, when it runs, its chats (group IDs and
phone numbers, so only the bot's user can read the file), its commands by
their English names, and when it last ran or was added:

```
1 | daily 08:00 | group.abcd… group.efgh… | /today; /weather; /uniquephoto | 2026-10-13 08:00:01+02:00
```

The bot rereads the file within half a minute of a change, so it can be
changed while the bot runs: with `/timer`, by hand, or with
`nejomibot-timers`, which lists, adds and removes timers from a terminal.
`nejomibot-timers` uses the bot's own code, so it accepts what `/timer`
accepts and numbers the chats the way `/chats` does. It is included in the
bot's image:

```sh
podman exec nejomibot nejomibot-timers                     # the timers
podman exec nejomibot nejomibot-timers chats
podman exec nejomibot nejomibot-timers add "08:00" 1,2 "/today; /weather; /uniquephoto"
podman exec nejomibot nejomibot-timers --dry-run remove 3
```

Its chats are numbers from `chats`, or group IDs, phone numbers and Signal
IDs. It reads the bot's configuration the same way the bot does; outside the
container, run `uv run nejomibot-timers` in the bot's folder.

A line the bot can't read, such as one with an unknown command, is left as
it is, where it is, and logged, and so are comments. A line that runs a
special the bot can't read at the time, as after a mistake in
`specials.txt`, is read again once the special can be read. A run that fell due while the bot was down is made when
the bot starts again, up to an hour late, provided that it is later than the
timer's last run; a timer for a single date is removed once it has run.
Without a timers file, the bot starts with no timers.

## Specials

A special posts several things in one go, always in the same order: text,
and the answers of other commands. Admins create specials in a direct chat
with the bot, mostly for timers:

```
/special add /morning Good morning! /today + /weather; /uniquephoto
/special shortcuts /morning /gm            other names for it
/special add /bins The bins go out tonight!
/specials                                  your own specials
/timer add tue 18:00 1 /bins               a reminder, every Tuesday
/special everyone /morning                 for everyone allowed, groups too
/special admins /morning                   for the admins alone again
/special remove /bins
```

A special's parts are separated by `;` or line breaks. Text before a command
heads the command's answer, in the same message, with a blank line between
them: `Good morning! /weather` posts the weather under "Good morning!". Text
on its own is a message of its own. A `+` standing on its own, in place of
a `;`, puts the parts on either side of it in one message, with a blank line
between everything they post: `/today + /weather` posts the day with the
weather under it, and `/weather + Have a nice day!` posts the weather with a
line under it. A `+` inside a word, as in `C++` or `+4670000000`, is text.
As a result, a text, or what follows a command, such as an album name, can't
contain a `+` standing on its own, just as neither can contain a `;`. A
special's name is a single word that starts with `/` or `.` and isn't
already a command or an alias; `/special add` with the name of one of your
specials changes it. A special has at most five parts.

Admins can give a special shortcuts, which are other names for it:
`/special shortcuts /morning /gm` makes `/gm` post the same as `/morning`,
and `/special shortcuts /morning -` removes them. A special has at most five
shortcuts, each a single word that starts with `/` or `.` (a plain word is
taken with a `/`), that the bot doesn't already respond to. They stay with
the special when it changes, go when it is removed, and are listed after it
in `/specials`.

Text keeps the formatting you give it in Signal, as in any message: select
the words, then choose bold, italic, strikethrough, monospace or spoiler.
Characters you type are shown as typed, `*` and `~` included.
signal-cli-rest-api, which sends the formatting, can't express every
combination, so the bot rejects the few it can't: bold and italic that meet
inside a word, and a style that starts or ends right next to a `\` or `*`.

Two specials to start from, with their headings formatted in bold in Signal:
the [daily post](#photos-and-the-daily-post), with the day and the weather in
one message, then a photo under "Photo of the day!"; and a proverb or quote
from `fortunes_svenska`, the bot's own library, under "Proverb or quote of
the day:", with the explanation of a proverb in italics, as `/fortune` shows
it:

```
/special add /dailypost /today + /weather; Photo of the day! /uniquephoto
/special add /dailyquote Proverb or quote of the day: /fortune fortunes_svenska
```

A special runs its commands the way a timer does, as whoever sent it would
send them, and posts their answers one after the other: it can contain any
command a timer can, but not another of your specials. Specials are for
timers, `/run`, and admins in a direct chat. Editing the message that ran
one of your specials runs it again, since its commands change nothing; an
edit of `/special add`, `remove`, `everyone` or `admins` replaces what the
original did. A special that a timer runs can be changed, but not removed:
remove the timer first.

### Specials for everyone

`/special everyone /morning` lets everyone the bot may talk to use
`/morning`, wherever they may use the everyday commands, in direct chats and
in allowed groups; `/help` lists it for them under Specials, with what it
posts and its shortcuts. `/special admins /morning` makes it the admins'
alone again. A special for everyone runs its commands for whoever uses it,
as they would send them where they send it: `/today` in a group shows that
group's birthdays, and `/help` the everyday commands. An admin command in
it, such as `/contacts` or `/status`, would show what only the admins should
see, phone numbers and the server's addresses among them, or change the bot,
so the bot names those commands when you make the special one for everyone,
and when you change it while it is. Each use counts as one command toward
the sender's `command_limit` ([Who may use what](#who-may-use-what)).

Your specials are stored in `data_dir/specials.txt`, one per line: the name
and its shortcuts, then `(everyone)` for one that everyone may use, a `|`,
and the parts, separated by `;` or joined by `+`, with the commands by their
English names and the texts in signal-cli-rest-api's formatting marks:
`**bold**`, `*italic*`, `***both***`, `~strikethrough~`, `` `monospace` ``
and `||spoiler||`, with a `\` before any `*`, `~`, `` ` `` or `|` that
should show as it is:

```
/morning /gm (everyone) | **Good morning!** /today + /weather; /uniquephoto
```

The bot reads the file again when it changes, so it can also be edited by
hand; the bot leaves comments and lines it can't read as they are, and
`/specials` lists those lines.

## Languages

The bot's messages are written in English, and translated into Danish
(`da`), German (`de`), Greek (`el`), Spanish (`es`), Finnish (`fi`), French
(`fr`), Norwegian (`nb`) and Swedish (`sv`). The `language` setting selects
one by its code, which the bot uses wherever nobody has chosen another
language.

Each chat can have its own language. `/language sv` (in Swedish, `/språk`)
makes the bot speak Swedish in a direct chat with the sender, and in a
group, when an admin sends it, with everyone in the group;
`/language default` returns to the configured language. An admin can set the
language of other chats from a direct chat, by their numbers in `/chats`:
`/language 3,1 sv`. `/language` on its own lists the languages, and for an
admin, the chats that have a language of their own. The bot replies in the
chat's language and posts to the chat in it: the timers' posts, `/run`'s
posts, reminders, the greeting, and the notices to each admin. A timer that
posts to chats in two languages runs its commands once for each language,
so that every chat gets the same photo, each captioned in its own language,
and the round uses up only one photo. Each chat's language is stored in
`data_dir/languages.txt`, one per line, and the file can be edited by hand.
A special's texts stay as the admins wrote them, and the weather gives place
names in each chat's language when OpenWeatherMap has them.

Each language is two files in [nejomibot/locale](nejomibot/locale), where
the bot finds every language it has:

- `sv.po` translates the messages into Swedish, in gettext's format, which
  translation tools such as Poedit and Weblate open. Untranslated messages
  are shown in English.
- `sv.toml` holds the language's own name, `Svenska`, its names for
  commands, which work like the aliases in the configuration, its words for
  days and times in `/timer add`, and its words for subcommands, such as
  `lägg till` for `add`. Each command lists the subcommands it accepts, so
  only those are recognized, and only right after the command; the timers
  and specials files store them in English. The bot accepts every
  language's names and words from anyone, whatever the chat's language;
  `/help` shows those of the chat's language.

Day and month names also come from the translations, so the bot needs no
system locales installed. The fortune libraries aren't translated: each is
in its own language, and `fortune_library` sets the one that `/fortune` uses
when no library is named.

The image contains the translations compiled once, at build time, as
`sv.mo` and so on, which the bot reads with Python's built-in gettext in
place of the `.po` files. When it runs from a source checkout without `.mo`
files, the bot reads the `.po` files directly with polib, which is needed
only for development.

### Adding a language

A new language needs its two files and nothing else, as the bot finds them
by themselves. For Portuguese, by its code `pt`:

1. Run `tools/translations.sh pt` (it requires GNU gettext). It creates
   `pt.po` from `messages.pot`, the template of every message, with the
   language's plural forms, and `pt.toml` from `template.toml`, which lists
   every command and word. A translation tool can start `pt.po` from
   `messages.pot` just as well.
2. Translate the messages in `pt.po`. Keep each `{field}` as it is, and write
   commands with a `/`, by the names `pt.toml` gives them: the bot shows them
   with the `command_prefix`.
3. In `pt.toml`, give the language's own name, its names for the commands,
   each starting with `/`, and its words for days, times and subcommands.
   Leave a list empty where the English name serves, as for `/ping`.
4. Run `uv run pytest`. The tests check that every message is translated,
   with the same `{fields}` and the same commands, and that no name or word
   stands for two different things in any of the languages.

Then `language = "pt"`, or `/language pt` in a chat, makes the bot speak it.

After changing the bot's messages, run
[tools/translations.sh](tools/translations.sh) to update `messages.pot` and
every `.po` file: new messages are added untranslated, and changed ones are
marked as fuzzy. Translate those; until then, the tests fail and the bot
shows them in English. A new command goes in `template.toml` too, which a
test checks.

### Aliases

Other names for commands go in the configuration, as a table at its end:

```toml
[aliases]
"/photo" = ["/pic"]
"/weather" = ["/w"]
```

A message that starts with an alias is treated as if it started with the
command: `/pic` sends a photo, and with `"/fortune" = ["/f"]`, `/f startrek`
sends a Star Trek fortune. An alias is a single word that starts with `/`
(or a `.` in its place, as for any command). A plain word, such as `pic`,
would make every message that starts with it a command, so it is taken with
a `/`, as `/pic`, and the log says so at startup. The bot's own command
names, in English and in its other languages, all start with `/`. An alias
can't be a command's own name, and the bot won't start with an alias for a
command it doesn't have. Aliases in the configuration take precedence over
the language's names, and over the bot's own other names: `/test`, `/time`,
`/safety` and `/day`.

## The bot's profile

Admins change the bot's Signal profile from a direct chat with it:

- `/name Mybot` sets the name. signal-cli-rest-api can set only the given
  name, so a family name, if the profile has one, remains after it.
- `/about Weather and photos every morning` sets the About text shown under
  the name; `/about remove` clears it. An emoji before the About text stays
  as it is, because the bot can't set it.
- `/avatar`, as the caption of a picture, makes the picture the profile
  picture: turned upright, cropped to its central square, scaled to at most
  1024×1024 as Signal's Android app does, and stripped of metadata such as
  where it was taken. It is saved as a JPEG, or as a PNG when the picture has
  transparent areas, as a logo may. `/avatar remove` removes it.
- `/username mybot` sets a username. Signal adds a number to it, as in
  `mybot.42`, unless you give one. The reply includes a link that starts a
  chat with the bot without its phone number. `/username remove` removes it.
- `/profile` shows all of this; each command on its own shows its current
  value.

The limits are those of Signal's apps: a name of up to 128 bytes (a letter
such as å takes two bytes, an emoji four) and an About text of up to 140
characters.

signal-cli-rest-api sets the profile as a whole, and removes the avatar
unless the picture is sent along every time, so `/name` and `/about` send
the current picture back. When Signal rejects a username,
signal-cli-rest-api doesn't say why; most likely, the username is taken. For
`/avatar`, the bot fetches the picture from signal-cli-rest-api and deletes
it there once it has become the avatar. This requires signal-cli to keep the
pictures sent to the bot, which it doesn't with
`JSON_RPC_IGNORE_ATTACHMENTS=true` (the bot then says so); the account tool
described below can set the avatar from a file instead, and so can `/avatar`
with a picture attached in [a terminal](#the-bot-from-a-terminal).

The profile can also be set in the configuration, with `bot_name`,
`bot_about`, `bot_avatar` (a picture file, which the bot treats as `/avatar`
does) and `bot_username`, which the bot sets as it starts. Once set, the bot
keeps the profile in `data_dir/bot.txt`, a line for each part: `name`,
`about`, `username`, and `avatar`, a picture in the same folder followed by
its SHA-256. Every change made with `/name`, `/about`, `/avatar`,
`/username` or `signal-account.sh` goes there too, and from then on a
setting is used only for a part that `bot.txt` doesn't have. At each start,
the bot compares the account's profile, as signal-cli knows it, with
`bot.txt`, and changes only what differs: a new account, such as one
without a phone number, gets the bot's profile, and an edit of `bot.txt`
takes effect at the next start; otherwise nothing is sent to Signal. The
avatar is compared by the SHA-256 of the picture beside `bot.txt`, which
the bot records as it sets it. An empty `about`, `avatar` or `username`
line removes that part. When Signal turns down the username, for
example because the number given after the dot is taken, the bot asks for
the name alone and keeps the number Signal gives it.

## Health checks

Every `healthcheck_minutes` (5 by default), and as soon as signalbot is
ready after a start, the bot checks its health:

- **signal-cli-rest-api:** it responds, through signalbot, in json-rpc mode,
  and it is newer than 0.101 (see
  [Which signal-cli-rest-api](#which-signal-cli-rest-api)).
- **The bot:** signalbot has started, which it does once signal-cli-rest-api
  has the account, and no message has waited more than 15 minutes to be
  sent. If Signal rate-limits the bot, the check says so, and what lifts the
  limit. The check also fails in the round after a send fails in a way that
  leaves it unknown whether the message arrived, such as a timeout (the bot
  doesn't send such a message again, as it could then arrive twice), and in
  the round after a waiting message is dropped, once it has waited
  `send_retry_hours`.
- **Signal:** Signal's servers respond for the account. The bot asks
  signal-cli-rest-api for the account's linked devices, which signal-cli
  requests from Signal. This is the only request a health check makes of
  Signal.
- **Delivery:** the bot hears the [receipts](#delivery) that phones send for
  its messages, on a websocket to signal-cli-rest-api of its own; messages
  to the bot arrive the same way, on signalbot's. The check fails when the
  bot has been unable to hear them for longer than `healthcheck_minutes`, as
  messages to the bot may then be lost too. It also fails when no phone has
  confirmed three of the bot's messages in a row within `unconfirmed_hours`
  (12 by default, at most 24) of each being sent, nor any message sent after
  them: the messages may not arrive, or the receipts may not reach the bot.
  One or two unconfirmed messages don't fail it, as they may have gone to
  phones that are off. A message counts only if it went to someone, and if
  the bot has heard receipts ever since it was sent: when the connection
  fails, the count starts over.

A failed check is logged, with what failed, and `/status` starts with the
same four checks. To be alerted, set `healthcheck_url`, for example to a
check's ping URL at [healthchecks.io](https://healthchecks.io)
(`https://hc-ping.com/<uuid>`): after each round, the bot pings that URL if
every check passed, or the URL with `/fail` appended, along with what
failed. The service then alerts you in whichever cases you set it up for:
when a ping reports a failure, or when the pings stop, as they do when the
bot is down. Set the check's period to `healthcheck_minutes`, and allow some
grace time.

Each ping reports how each check went, followed by what is running, as
`/status` shows it: the versions of nejomibot, signalbot, Python and
signal-cli-rest-api; how long the bot has been up, and so its container,
since the bot is the container's process; and the bot's memory use, with its
peak and the container's limit, if there is one. healthchecks.io shows this
text with each ping in the check's log. signal-cli's version isn't included,
because signal-cli-rest-api doesn't report it.

### Notices to the admins

The bot tells the admins in the configuration directly, in a direct chat
with each of them, about things they would otherwise find out too late:

- **Each start.** That the bot is up, since when, and how long it took to
  become ready; after an update, the previous version; and after a crash, a
  kill or a power cut, that messages that had waited less than half a minute
  may have been lost. Then anything that needs their attention, such as
  lines in the bot's files that it can't read, which therefore have no
  effect, a clock that isn't synchronized, or messages still waiting to be
  sent; and finally, how the bot is doing: its timers and when the next one
  runs, its groups, allowed chats and admins, the photos, the clock, its
  memory use, signal-cli-rest-api's version, and where it runs:

  ```
  🟢 nejomibot 0.99.11 started
  Friday 23 October 09:46 · ready in 14 s

  🔄 Updated from 0.99.10
  ⚠️ timers.txt: 1 line the bot can't read, left as it is

  ⏰ 2 timers, the next Saturday 24 October 08:00
  👥 In 3 groups · 6 chats allowed · 1 admin
  📷 Photo library: 1151 photos
  🕐 Clock: synchronized, max error 0.02 s
  🧠 Bot memory: 74.1MB (peak 74.9MB)

  🔌 signal-cli-rest-api unset, json-rpc mode
  🐍 signalbot 2.1.3 · Python 3.14.0
  🖥️ Podman on bothost · aarch64
  ```

  Every start sends this notice, as soon as the bot is ready. To turn it
  off, set `startup_notice = false`; `/status` shows the same. The bot
  knows the previous run's version and whether it stopped cleanly from
  `data_dir/run.json`, which it writes when it starts and when it stops.
- **Signal rate-limits the bot.** When this begins, the notice says how to
  lift the limit: `signal-account.sh rate-limit --to <your number>`,
  followed by a captcha, and then any command to the bot, which has it try
  again at once. It is sent at most once every six hours, and tried only
  once, because while Signal rate-limits the bot, the notice may not get
  through either; the health check reports the limit too while messages are
  waiting, and so does the ping, if `healthcheck_url` is set.
- **A safety number changes.** signal-cli won't send messages to someone
  whose safety number has changed until the new one is trusted, so the
  admins are told whose number it is, so that they can compare it with
  `/trust <who>` and then trust it with `/trust <who> <safety number>`. The
  bot checks every `healthcheck_minutes`, which requires nothing of Signal's
  servers, and at startup, for changes since it last ran.

In debug mode, which starts afresh each time, every start is reported,
marked `🐞 Debug mode`, with no update or previous stop to report.

### The containers' health checks

A container's health check answers a different question: whether the
container works, and so whether restarting it could help. With the
[Quadlets](#podman-quadlets), Podman restarts a container whose check fails
three times in a row.

- **The bot's check**, built into its image: the bot responds within 5
  seconds, and the health checks above run on time, which they don't when
  the bot is stuck. What those checks find doesn't count: when Signal or
  signal-cli-rest-api fails, restarting the bot wouldn't help, and could lose
  the messages that have waited less than half a minute, which aren't on
  disk yet. Neither does waiting for signal-cli-rest-api or for the account,
  so a new installation isn't restarted while its account is being set up in
  the container. `podman exec nejomibot nejomibot-healthcheck` shows what the
  check found, and how the latest round of the checks above went. The bot
  answers over a socket in Linux's abstract namespace, which isn't a file,
  so nothing is written to disk.
- **signal-cli-rest-api's check:** the check in its image only queries the
  REST API, which keeps answering even while signal-cli behind it is stuck,
  so the Quadlet has it ask signal-cli for the accounts instead. This
  requires nothing of Signal's servers.

Both checks run every minute. Podman runs the first check as the container
starts, before the bot answers, and the next one a minute later, so
`podman ps` shows the bot as `(starting)` for a minute; failures during the
first minute don't count. Three failures in a row, over two to three
minutes, mark a container as `(unhealthy)`. The image can't specify what
happens then: with `HealthOnFailure=kill` in each Quadlet, Podman kills the
container, and systemd starts it again (`Restart=always`, after
`RestartSec=10`), restarting the bot together with signal-cli-rest-api. It
takes about three minutes from when a container stops working until it works
again. Docker doesn't restart unhealthy containers; `docker compose ps` only
shows their status.

A Quadlet can change any of the bot's health check settings, such as
`HealthInterval=` or `HealthRetries=`, and the others keep the image's
values; but a `HealthCmd=` replaces the image's interval, timeout, retries
and start period with Podman's defaults, which is why signal.container sets
an interval of its own. Each check appears as a line in the system journal,
as Podman's `health_status` event (`healthcheck_events = false` in
containers.conf turns these off), and signal-cli-rest-api's log has a line
for each of its checks, as it has for every request except its image's own
check.

## Setting up and managing the Signal account

[tools/signal-account.sh](tools/signal-account.sh) does everything
signal-cli-rest-api can do with the account itself: registering the number
or [linking signal-cli to a phone](#linking-to-a-phone), and managing the
profile, username, PIN, privacy, linked devices, safety numbers and rate
limits; `--help` lists it all. The tool is included in the bot's image,
where it finds signal-cli-rest-api and the account in the bot's
configuration, so it needs no options:

```sh
podman exec -it nejomibot signal-account.sh                 # status: account, profile, devices
podman exec -it nejomibot signal-account.sh setup           # register or link, then the rest
podman exec -it nejomibot signal-account.sh username mybot
podman exec -it nejomibot signal-account.sh --dry-run unregister  # what it would send; sends nothing
```

(With Compose, use `docker compose exec nejomibot signal-account.sh setup`.)
The tool also runs without the bot, for example before the bot's first
start, in a container of its own on signal-cli-rest-api's network, where it
finds signal-cli-rest-api at `127.0.0.1:8080` and the only account there, and
`setup` asks for the number. `--no-healthcheck` keeps the image's health
check, which asks the bot, from running in that container:

```sh
podman run --rm -it --no-healthcheck --network container:signal \
  docker.io/jodab/nejomibot signal-account.sh setup
```

With Compose, `docker compose run --rm nejomibot signal-account.sh setup`
does the same, with the bot's settings. A picture for the avatar is passed
on standard input, from wherever it is, since the container can't see your
files:

```sh
podman exec -i nejomibot signal-account.sh profile --avatar - < logo.png
```

The tool also runs on any machine with bash, curl and jq that can reach
signal-cli-rest-api; `--url` tells it where. That isn't needed with the
examples, where nothing but the bot can reach it.

The tool asks for confirmation before anything that can't be undone
(unregistering requires you to type the number), reads PINs only from the
terminal, and guides you through the captcha that Signal may require before
it sends a code, and through the call it makes when it can't send a text
message. It works around these limitations of signal-cli-rest-api:

- A profile update removes the avatar unless the avatar is sent along, so
  the tool fetches the current one and sends it back.
- The family name can't be changed, so a new `--name` comes with a warning
  that the family name stays.
- A rejected username comes back as "invalid signal-cli response", so the
  tool says what is most likely: the name is taken, or not allowed.
- In json-rpc mode, the trust mode is set by the container's
  `JSON_RPC_TRUST_NEW_IDENTITIES`, and the API's own setting is unused; the
  tool says so, rather than showing that setting.

When Signal rate-limits the bot, the bot logs it, but it can't present the
challenge that lifts the limit, because signalbot doesn't pass it on.
`signal-account.sh rate-limit --to +46701234567` sends that number a short
test message: if Signal is rate-limiting the bot, the response includes a
challenge, and the tool guides you through the captcha that lifts the limit.

### Linking to a phone

Instead of a number registered for it alone, the bot can use the account of
a phone with Signal, as a linked device of that phone, the way Signal
Desktop is. Choose `l` in `signal-account.sh setup`, or run
`signal-account.sh link`, and scan the QR code that the tool shows with the
phone: in Signal, **Settings > Linked devices > Link a new device**. The
bot then needs no number of its own, nor a verification code or captcha;
the account stays on the phone, and the phone shows the bot's chats. It is
also how
signal-cli-rest-api can use
[an account without a phone number](#an-account-without-a-phone-number).
Set `account` to the account's phone number, or its Signal ID; the tool
shows it once the bot is linked.

A linked bot has a few drawbacks:

- What is typed on the phone in a direct chat reaches the bot as if the
  other person had sent it, since signalbot can't tell the two apart: the
  bot runs a command typed there as theirs, with an admin's rights in a
  chat with an admin, and answers them. Other messages typed there can get
  them the bot's greeting, and `/incoming` lists them as theirs. In a
  group, a command typed on the phone runs as anyone's would. A phone kept
  for the bot's account avoids all of this.
- The phone has to come online at least once every 30 days; otherwise,
  Signal unlinks the bot, and only the phone can link it again.
- Only the phone can set the registration lock PIN and link other devices,
  so `setup` skips the PIN.

### An account without a phone number

Signal Login, in the beta of Signal for Android, creates a Signal account
without a phone number. Signal Android shows its Account Key, which is the
account's Signal ID, a UUID such as `0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e`,
and its Recovery Key, the only way to restore the account. The bot can use
such an account: set `account` to its Signal ID.

signal-cli-rest-api can link signal-cli to such an account
([Linking to a phone](#linking-to-a-phone)), but it can't restore one with
its Recovery Key yet. signal-cli itself can, with its
`register --recovery-key` command, run on signal-cli-rest-api's data while
signal-cli-rest-api is stopped; see
[signal-cli's documentation](https://github.com/AsamK/signal-cli/blob/master/man/signal-cli.1.adoc).

Nobody can find an account without a phone number unless it has a
username, so give it one, with `/username` or `signal-account.sh username`;
until then, `/status` and `/profile` warn. The registration lock PIN and
the privacy settings for the phone number don't apply to it, and
`signal-account.sh` skips them in `setup`.

People without a phone number can use the bot too. They find it by its
username, and you give the bot their Signal ID wherever it takes a person:
in `admins`, as in `admins = ["0f1e2d3c-4b5a-4968-8778-695a4b3c2d1e"]`, and
in `/allow` and `/admin add`. Signal Android shows a person's Signal ID as
their Account Key, and once they have written to the bot,
`signal-account.sh identities` lists it after their name. Upper or lower
case makes no difference.

## How the bot talks to Signal

Everything the bot does in Signal goes through signalbot wherever signalbot
supports it: receiving, sending, read receipts, typing indicators, deleting
messages, groups, naming a contact, and signal-cli-rest-api's version.
signalbot can't tell which accounts signal-cli has, list contacts or linked
devices, do anything with safety numbers or the bot's own profile and
username, fetch a single attachment, or receive the receipts for the bot's
messages. For those, the bot calls signal-cli-rest-api directly, in
[rest.py](nejomibot/rest.py), where each function says what signalbot
lacks. The receipts arrive on a websocket of the bot's own, alongside
signalbot's, since signal-cli-rest-api sends everything it receives to every
websocket. When signal-cli-rest-api or Signal changes, a newer signalbot
covers most of it, and rest.py is the one place to check for the rest.

signalbot doesn't pass on signal-cli-rest-api's error messages, only the
HTTP status, so an error from a send or a deletion is shown as that status,
such as `signal-cli-rest-api returned 400 Bad Request`; signal-cli-rest-api's
log has the details.

### Which signal-cli-rest-api

The bot requires a signal-cli-rest-api newer than 0.101, the latest release.
0.101 crashes when the answers to two requests arrive at the same time
([#885](https://github.com/bbernhard/signal-cli-rest-api/issues/885)),
writes every message it receives, in full, to its log
([#892](https://github.com/bbernhard/signal-cli-rest-api/issues/892)), and
in json-rpc-native mode, its signal-cli 0.14.8 can't list the account's
linked devices, which the health check does: the request never returns
([signal-cli#2119](https://github.com/AsamK/signal-cli/issues/2119)). Until
the next release, the examples in [deploy/](deploy) pin a CI build that has
the fixes, `1792710189-ci` from 2026-10-22, with signal-cli 0.14.9, by its
digest, since the tags of CI builds may not be kept. That build reports its
version as `unset`, which signalbot takes to mean a build newer than any
release. The signal-cli-rest-api health check fails on 0.101 or older.
0.101, and builds from before 2026-10-13, also drop what reaches a websocket
while it is still busy with the previous message: of a burst of receipts,
some can be lost, so `/delivery`'s counts can come out too low. The pinned
build fixes this.

Run it in `json-rpc` mode, as the examples do, where one signal-cli, on
Java, serves every request. Its `json-rpc-native` mode, with signal-cli
compiled to native code, starts faster and uses less memory, but it has had
bugs that `json-rpc` mode doesn't have, such as the linked devices above,
and it doesn't exist on 32-bit ARM, which has no native build. In `json-rpc`
mode, signal-cli-rest-api uses about 360 MB of memory on a Raspberry Pi 4,
and the bot about 90 MB.

### Signal's rate limits

Signal limits what an account may do in a given time, to fight spam, and
doesn't publish the limits it applies. Most are buckets: so many requests
at once, refilled at a steady rate. The defaults in Signal's server code
([RateLimiters.java](https://github.com/signalapp/Signal-Server/blob/main/service/src/main/java/org/whispersystems/textsecuregcm/limits/RateLimiters.java),
as of October 2026), which Signal can change for most of them while its
servers run, include:

| Requests | At once | Then |
|---|---|---|
| Messages to one person, unless sent with sealed sender | 60 | one more each second |
| Attachments uploaded, such as photos | 50, and 1 GiB | one more every 1.2 seconds, and about 1 MB a second |
| Profiles fetched | 4,320 | one more every 20 seconds |
| Keys fetched, to start a session with a new person or device | 6 | one more every 10 minutes |
| Usernames looked up | 100 | one more every 15 minutes |
| Captcha attempts, to lift a limit | 10 | one more every 144 minutes |
| Captchas solved | 2 | one more every 12 hours |

What bots meet most often is none of these, but Signal's spam checks, whose
rules aren't public: an account that sends a lot, in bursts, or to people
who haven't written to it, has to solve a captcha before it may send more.
signal-cli-rest-api then answers a send with 429, which the bot takes as a
rate limit. Waiting rarely lifts it; solving the captcha does
([how](#setting-up-and-managing-the-signal-account)).

The bot keeps well below these limits:

- It answers each person at most `command_limit` commands in
  `command_limit_minutes` (20 in 10 minutes), so that nobody can make it
  send in bulk. The admins aren't limited.
- While Signal rate-limits it, it sends nothing at once: messages wait,
  read receipts and the typing indicator aren't sent, and only the message
  that has waited longest is tried, after 2 minutes, then twice as long
  after each attempt, at most `rate_limit_retry_minutes` (30) apart. An
  admin's command has it try again at once, a minute after the last attempt
  at the soonest.
- It looks up each phone number at most once a run, asks again for the
  profile of someone without a name at most every six hours, and asks
  Signal's servers for the account's linked devices only for the health
  check, every `healthcheck_minutes` (5).

If you know more about the limits your account meets, you can tune the bot
with these settings: a lower `command_limit` or a longer
`command_limit_minutes` for a busy bot, a longer `rate_limit_retry_minutes`
for fewer attempts while it is limited, and a longer `healthcheck_minutes`
for fewer requests to Signal's servers. `send_retry_hours` (3) sets how long
a waiting message is kept before it is dropped.

## Configuration

Settings are read from `config.toml`, or from the file named by
`NEJOMIBOT_CONFIG`: `/data/config.toml` in the container, in the data
folder. Start from a copy of [config.example.toml](config.example.toml),
which describes every setting and is included in the image as
`/app/config.example.toml`:

```sh
podman run --rm docker.io/jodab/nejomibot cat /app/config.example.toml > config.toml
```

The file contains the API key and phone numbers, so it is kept out of git.

Any setting can also be given as an environment variable named
`NEJOMIBOT_<SETTING>`, which overrides the file, for example
`NEJOMIBOT_SIGNAL_SERVICE=127.0.0.1:8080` or
`NEJOMIBOT_ADMINS='["+46701234567"]'` (lists and tables in JSON). If the
environment provides every setting the bot needs, no file is required.

The configuration is validated at startup: a mistake stops the bot with a
message that names the setting that is wrong, and so do unknown settings and
aliases for commands that don't exist. So when an update renames or removes
a setting, the bot says which one, and won't start until the configuration
matches `config.example.toml`.

The bot only reads the photo library. What it is told and what it does (the
timers, the specials, the allowed list, the added admins, the reminders, the
lists, the birthdays and name days, the photos sent in the current rounds, the
messages waiting to be sent, and the version that ran last) it stores in
`data_dir` (`/data` in the container, next to the configuration file),
which must exist at startup. These files contain phone numbers, so only the
bot's user can read them. Each file is written in full through a temporary
file, which is safely on disk before it takes the old file's place, so
neither a crash nor a power cut can leave a file half-written.

### Debug mode

With `NEJOMIBOT_DEBUG=1`, the bot talks only to `debug_group` and the
admins. It keeps its list of sent photos, its allowed list, the added
admins, its timers, specials, reminders, lists and birthdays, and its
waiting messages in a private temporary folder instead of `data_dir`,
created anew at each start and removed when the bot stops: the allowed list
contains only `debug_group`, and there are no added admins, timers, specials
or birthdays of your own. `/chats` offers only `debug_group` and the admins,
so `/msg`, `/run` and timers can't reach anyone else. Use debug mode to test
changes without posting to anyone else, and `/timer add` to try out the
daily post. Stop the production bot first: two bots on the same Signal
account compete for incoming messages.

## Running it

The bot is a container image for linux/amd64, linux/arm64 and linux/arm/v7,
the same platforms as signal-cli-rest-api. Each release is published as
`docker.io/jodab/nejomibot` and `ghcr.io/jodab/nejomibot`, tagged with its
version and as `latest`, which the examples in [deploy/](deploy) use. To
build the image yourself, use [tools/build-image.sh](tools/build-image.sh),
which builds it with Podman: it runs the tests, the linter and the type
checker, then builds the three architectures (emulating those that differ
from the machine's own with QEMU) as `localhost/nejomibot:<version>` and
`:latest`, and with `--push`, pushes them to a registry, once for each
`--push`.

Since 0.94.0, the release workflow attests every image it pushes with signed
build provenance, kept on GitHub, which records the workflow that built the
image and the commit it was built from. To check it with the
[GitHub CLI](https://cli.github.com/), logged in:

```sh
gh attestation verify oci://docker.io/jodab/nejomibot:latest --repo jodab/nejomibot
```

The bot requires
[signal-cli-rest-api](https://github.com/bbernhard/signal-cli-rest-api)
newer than 0.101 ([which](#which-signal-cli-rest-api)), in json-rpc mode,
where the bot can reach it; how you run it is up to you.
signal-cli-rest-api has no authentication, so anyone who can reach it
controls the Signal account: don't publish its port beyond the machine. The
examples in [deploy/](deploy) run the two containers side by side, without
publishing it at all.

The bot runs as UID and GID 1000, or as the user and group the container
is given (`--user`; `User=` and `Group=` in a Quadlet; `user:` in Compose),
needs no capabilities, and writes only to `/data`, while its tools write to
`/tmp`. The examples run it that way: with
no capabilities, no new privileges and a read-only file system
(`DropCapability=ALL`, `NoNewPrivileges=true` and `ReadOnly=true` in the
Quadlet), and with an init process, which forwards SIGTERM and reaps what
the tools leave behind (`RunInit=true`). It uses two folders:

- `/photos`: the photo library, which the bot only reads, so it must be
  readable by everyone.
- `/data`: `config.toml` and everything the bot stores. It must belong to
  the bot's user: Podman's `:U` option sees to that; otherwise, run
  `chown 1000` on it, or with the bot's user, if you give it another.

Every interactive shell in the container, such as `podman exec -it nejomibot
sh` or `bash` (with Compose, `docker compose exec nejomibot sh`), starts with
a short guide to the bot's tools there: `nejomibot-chat`,
`nejomibot-healthcheck`, `nejomibot-timers` and `signal-account.sh`, what
each does and where it is, and where the bot keeps its files. `nejomibot-help.sh` shows the guide
again.

### A fresh install

[Getting started](#getting-started) walks through one with Compose. With
the Quadlets or `podman run` below, the steps are the same, with `podman exec
-it nejomibot` in place of `docker compose exec nejomibot`: put
`config.toml` in the data folder, start the bot, which waits for its account
(as its log shows), register or link the account with `signal-account.sh
setup` in the bot's container, then send `/help` from an admin's phone, and
use `/allow` and the timers. The account can also be set up before the bot
starts, with the tool in a container of its own
([how](#setting-up-and-managing-the-signal-account)).

### Podman Quadlets

[deploy/signal.container](deploy/signal.container) and
[deploy/nejomibot.container](deploy/nejomibot.container) are Quadlets for the
two containers. They go in `/etc/containers/systemd/`, or for a rootless
setup under a user account, in `~/.config/containers/systemd/`. Adjust the
folders to suit (`%h` is the user's home directory), and in a rootless
setup, give the bot `UserNS=keep-id:uid=1000,gid=1000` instead of `:U`, so
that the files in the data folder stay the user's. Then:

```sh
systemctl daemon-reload                  # systemctl --user ... for a user
systemctl start signal                   # and the bot with it
journalctl -u nejomibot -f
```

The bot shares signal-cli-rest-api's network (`Network=signal.container`),
so it reaches it at `127.0.0.1:8080`, and nothing else can. The bot stops
when signal-cli-rest-api stops, since its network goes with it, and starts
again with it. Each container is restarted when its health check fails
([how](#the-containers-health-checks)): that is what `HealthOnFailure=kill`
in each Quadlet does, since an image can't specify it, and for
signal-cli-rest-api, the Quadlet also has a better check. To reach
signal-cli-rest-api from elsewhere, for example with the account tool on
another machine, publish its port on the server's loopback interface only
(`PublishPort=127.0.0.1:8080:8080` in signal.container) and use `ssh -L`. In
a rootless setup, `loginctl enable-linger <user>` keeps the containers
running when the user isn't logged in.

### Docker Compose, podman-compose

[deploy/compose.yaml](deploy/compose.yaml) runs both containers, with the
bot reaching signal-cli-rest-api as `signal:8080`, next to the folders
`data`, `photos` and `signal`; [Getting started](#getting-started) uses it,
step by step. The bot and signal-cli-rest-api run as UID 1000, so their
folders must belong to that user, or the bot's to the user it's given
(`user:`). Docker
restarts a container that stops, but not one whose health check fails.

### podman run, docker run

With signal-cli-rest-api running as a container named `signal`, and the
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

Pull the new image and restart the bot: with Compose, `docker compose pull
&& docker compose up -d`; with the Quadlets, `podman pull
docker.io/jodab/nejomibot` and `systemctl restart nejomibot`.
[CHANGELOG.md](CHANGELOG.md) says what to do when updating, if anything. If
the configuration needs to change, the bot says what is wrong and stops, and
its log has the message. What the bot stores in the data folder stays as it
is. To choose when to update, use a version tag in place of `latest`.

The log (`journalctl -u nejomibot`, `docker compose logs nejomibot`) records
each start's steps: the version, where the settings come from, when
signal-cli-rest-api has the account, what the bot's files hold, when the bot
is ready, and how long reading when the photos were taken took; with
`log_level = "DEBUG"`, the steps in between too. It records the commands the
bot answers, by name, and the kind of chat, but not who sent them, what
followed the command's name, or whom messages go to;
`log_level = "DEBUG"` adds those. signalbot, which at the INFO level logs
every message the bot receives in full, and the other libraries log only
what goes wrong; signalbot's warning that a group message didn't reach
someone names that person, by number or ID. Each line of the log has the
date and time, the level, and the part of the bot it comes from.

## Development

The project uses [uv](https://docs.astral.sh/uv/). Python and all
dependencies are pinned in `.python-version` and `uv.lock`.

```sh
uv sync                                   # create .venv with all dependencies
cp config.example.toml config.toml        # then fill it in
ln -s /path/to/your/photos photos         # a copy of the photo library
NEJOMIBOT_PHOTOS_DIR=photos NEJOMIBOT_DEBUG=1 uv run nejomibot
# or outside debug mode, keeping the bot's data in data/
mkdir -m 700 data
NEJOMIBOT_PHOTOS_DIR=photos NEJOMIBOT_DATA_DIR=data uv run nejomibot

uv run pytest                             # tests
uv run ruff check                         # lint
uv run ruff format                        # format
uv run pyright                            # type check (strict)
tools/translations.sh                     # after changing the bot's messages
tools/build-image.sh                      # the image, for all three architectures
```

Running the bot requires a signal-cli-rest-api it can reach, set as
`signal_service`. The tests need none: they run signalbot against a
stand-in for it.

On GitHub, [CI](.github/workflows/ci.yml) runs the same checks, ShellCheck on
the tools, and the image build for every push and pull request, and
Dependabot proposes updates to the dependencies, the base images and the
actions. The [release workflow](.github/workflows/release.yml) publishes the
image to GitHub's registry, ghcr.io, when a release is published, and to
Docker Hub as well when the repository has the variable `DOCKERHUB_USERNAME`
and the secret `DOCKERHUB_TOKEN`; nothing else publishes it. It attests each
image's build provenance, and on Docker Hub, makes
[DOCKERHUB.md](DOCKERHUB.md) the image's page, for which the token needs
read, write and delete permissions. [tools/release.sh](tools/release.sh)
makes a release once CI has passed: it sets the version, dates the
changelog, creates a signed tag, and publishes the release on GitHub. For
now, it makes patch releases only: nejomibot stays on 0.99.x until 1.0.

## Layout

```
nejomibot/
  bot.py        entry point: the handlers, and who may use them
  config.py     the settings
  access.py     who may use the bot: the admins and the allowed list
  allowed.py    /allowed, /allow, /disallow
  admins.py     /admins, /admin: admins besides those in the configuration
  commands.py   commands: each handler's, by any of their names, and how they are answered
  i18n.py       translations, and how commands are shown: .photo or /photo
  locale/       the translations, a .po for each language's messages and a .toml for its names,
                and the templates a new language starts from: messages.pot and template.toml
  photos.py     /photo, /uniquephoto, /cache: photos with their dates, ages and locations; albums
  albums.py     /albums, /album: the albums, their birth dates and shortcuts
  onthisday.py  /onthisday: a photo from this day in an earlier year
  today.py      /today, /today preview: the day's holidays and birthdays
  specials.py   /specials, /special: several posts in one command
  messages.py   sending through signalbot, the outbox, and the wording of errors
  styles.py     Signal's text styles and mentions, as signal-cli-rest-api takes them
  mentions.py   /mention all: everyone in a group
  rest.py       what signalbot can't do: direct requests to signal-cli-rest-api
  client.py     the HTTP session for the bot's own requests
  receipts.py   read receipts and the typing indicator
  weather.py    /weather, /forecast: OpenWeatherMap
  info.py       /info: clocks and the exchange rate
  ping.py       /ping
  fortune.py    /fortune
  fortunes/     fortune libraries, from fortune-mod, and fortunes_svenska
  health.py     health checks, reported to healthcheck_url; answers the container's check
  healthcheck.py  the container's health check: asks the bot whether it works
  status.py     /status, /test: the health check and the details
  account.py    the Signal account: contacts, safety numbers, groups, devices
  contacts.py   /contacts, /trust: everyone known, numbered, with safety numbers
  profile.py    /profile, /name, /about, /avatar, /username
  delete.py     /delete: deletes the bot's latest messages, here or anywhere
  delivery.py   /delivery: whether they arrived, from the receipts that phones send
  incoming.py   /incoming: the latest messages people sent the bot
  greeting.py   the greeting for messages from the allowed list that aren't commands
  notices.py    notices to the admins: each start, a rate limit, safety numbers
  reminders.py  /remind: reminders, posted in their chat when due
  lists.py      /list: a list for each chat
  birthdays.py  /birthdays, /namedays, /birthday, /nameday: for /today
  holidays.py   the calendar's holidays, flag days and traditions
  timers.py     /timers, /chats, /timer: commands on a schedule, such as a daily post
  timers_cli.py nejomibot-timers: the timers from a terminal
  relay.py      /msg, /run: posting to other chats
  terminal.py   the bot's side of nejomibot-chat, and the messages it received
  chat_cli.py   nejomibot-chat: the bot from a terminal, as in a direct chat
  help.py       /help
  system.py     process, container and host facts from /proc and /sys
  publicip.py   public IPv4 and IPv6 addresses, ASN and location
  files.py      the files in data_dir: written privately, read again when changed
deploy/         examples: Podman Quadlets and a Compose file
tests/
tools/          build-image.sh: tests and builds the image, for x86 and ARM;
                nejomibot-help.sh: the guide a shell in the container starts with;
                nejomibot-profile.sh: shows it, whichever shell, and puts the tools on its PATH;
                release.sh: makes a release, and with it the image;
                signal-account.sh: sets up and manages the Signal account;
                tidy-photos.sh: converts, renames and deduplicates the photo library;
                translations.sh: brings the translations up to date, and starts new ones
.github/        CI, publishing the image on a release, and Dependabot
```

## License

nejomibot is licensed under the MIT License; see [LICENSE](LICENSE).
Releases up to and including 0.99.14 were licensed under the GNU General
Public License, version 3 or later, and remain under it.

The fortune libraries in `nejomibot/fortunes`, except `fortunes_svenska`,
come from [fortune-mod](https://github.com/shlomif/fortune-mod), as Debian
ships them, under fortune-mod's BSD license; see
[LICENSES/fortune-mod.txt](LICENSES/fortune-mod.txt). `fortunes_svenska` is
the bot's own: proverbs, and quotes from writers long dead, in its own
translations.
