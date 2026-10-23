# DISCLAIMER
This project was created as a playground for teaching myself how to better use Claude Code, so everything you see here is entirely AI coded under my guidance.

# nejomibot

A Signal bot for a family or a group of friends. Every morning it can post
the weather and a photo from your photo library to a few Signal groups, and
it answers a handful of commands. It speaks English, Swedish or Greek, in each
chat the one chosen there, and other languages once they're translated.

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
| `language` | `"en"` for English, `"sv"` for Swedish, `"el"` for Greek | `"en"` |

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
   none comes within a minute, press Enter: the tool has Signal send it
   again, or call with it. If Signal can't send a text, the tool offers a
   call.
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
/timer add 08:00 1 /today; /weather; /uniquephoto
/timer run 1
```

`/chats` numbers the chats the bot can post to: its groups, then the people
allowed, then you. `/timer add 08:00 1 /today; /weather; /uniquephoto`
posts the day's holidays and birthdays, once there are some, the weather,
then a photo, none twice until every one has been sent, at 08:00 every day,
in your `timezone`, to chat 1; for more chats, `1,2`, and days work too, as
in `mon-fri 07:30` ([more](#timers)). `/timer run 1` posts it right away, to
see that it works.

That's it: the bot is up and running. Every day at 04:00 it backs up what it
keeps, and its settings, in `data/backups` ([more](#backups)). Next, perhaps:
warnings when it's down, with `healthcheck_url` ([how](#health-checks));
birthdays, name days and the holidays of your country, by its code, for
`/today` ([how](#birthdays-name-days-and-holidays)); [specials](#specials) of
your own, such as the daily post with a heading over its photo; and a
profile picture:

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
- **No code comes:** press Enter where the tool asks for it, and it has
  Signal send the code again, or call with it. Signal's first text
  sometimes never comes, while the next one does at once.
- **With SELinux** (Fedora, RHEL), the containers may be refused their
  folders: add `:Z` to the data and signal volumes in compose.yaml, and `,z`
  to the photos' (`./photos:/photos:ro,z`).

## Commands

The everyday commands, for everyone the bot may talk to:

| Command | Reply |
|---|---|
| `/photo`, `/photo <album>` | A random photo, from every album or the one named, with the date it was taken, an age if set, and a map link (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/photo [<album>] <date>` | A photo taken then, as exactly as you like: in `2017`, in `2017-05`, on `2017-05-14` or from 15 to 16 that day, `2017-05-14 15`, at random, or else in the nearest year, month, day or hour that has some, under how far off it is; to the minute, as `/photo 2024-06-01 15:00`, the one taken nearest that moment |
| `/uniquephoto`, `/uniquephoto <album>` | A photo not sent yet in this round, captioned as `/photo` captions it: none twice until every photo has been sent, then a new round starts; each album has a round of its own (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/albums` | The albums, the folders of the photo library: how many photos each has, the years they were taken in, the birth date its captions count an age from, and its shortcuts |
| `/onthisday`, `/onthisday <album>` | A photo taken on this day in an earlier year, or else within three days of it, from every album or the one named, captioned as `/photo` captions it, under how many years ago (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/cache`, `/cache <album>` | Number and size of photos in the library, by type, and how many albums it has; with an album, its photos' |
| `/today`, `/day` | The day's holidays, and in a group, the birthdays and name days of those in it; "Nothing special today." on a day without any, but nothing in what a timer, a special or `/run` posts (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)) |
| `/weather`, `/weather <city>` | Current weather in `weather_city`, or in the city named, such as `/weather Helsinki`, under its heading in bold, with the day's sunrise and sunset (see [The weather](#the-weather)) |
| `/forecast`, `/forecast <city>` | The weather today and tomorrow there: each day's worst weather, its lowest and highest temperature, and its chance of rain or snow (see [The weather](#the-weather)) |
| `/info`, `/time` | The time in the places in `clocks`, and the `exchange_rate` |
| `/ping` | `pong!` and how long the ping took to arrive |
| `/fortune`, `/fortune <library>`, `/fortune all`, `/fortune list` | A random fortune, from `fortune_library` (`fortunes_svenska` if not set), the library named, or every library; `list` names them. What explains a proverb of `fortunes_svenska` is in italics |
| `/remind <when> <text>`, `/remind`, `/remind remove <n>` | A reminder, which the bot posts in the chat when it's due, such as `/remind tomorrow 08:00 Pick up Bob`; alone, the chat's reminders, numbered (see [Reminders and lists](#reminders-and-lists)) |
| `/list`, `/list add <things>`, `/list remove <n>,<n>`, `/list clear` | The chat's list, such as for shopping: `/list add milk, eggs` puts things on it, `/list remove 2,5` takes them off (see [Reminders and lists](#reminders-and-lists)) |
| `/birthdays` | In a group, the birthdays of those it's for, the coming ones first; for the admins, in a direct chat, all of them, numbered (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)) |
| `/namedays` | The name days, as `/birthdays` lists the birthdays |
| `/language`, `/language <language>`, `/language default` | The languages the bot speaks, and the one it speaks here; with a language, by its code or its own name, such as `sv` or `Svenska`, it speaks that here, and `default` goes back to `language` in the configuration. In a direct chat it's the sender's own; a group's is an admin's to change (see [Languages](#languages)) |
| `/help` | The commands the asker may use, a line each |

For the admins, in a direct chat with the bot:

| Command | Reply |
|---|---|
| `/status`, `/test` | Health check, in two messages: the checks, failed ones first, then the details: the bot and its versions, Signal, public IPs and ASN, container, host |
| `/album <album>`, `/album <album> <date>`, `/album <album> -` | An album: how many photos, the years, the birth date its captions count an age from, and its shortcuts; with a date, such as `2019-06-15`, that birth date; `-` takes it away, so `photos_birth_date` counts again (see [Photos and the daily post](#photos-and-the-daily-post)) |
| `/album <album> shortcuts <names>`, `/album <album> shortcuts -` | Other names for `/photo <album>`: `/album Alice shortcuts /alice alice` makes `alice` `/photo Alice`, and `alice 2017` `/photo Alice 2017`; `-` takes them away |
| `/today preview [<date>]` | What `/today` will say on the day, such as `10-25`, `2026-10-25` or `tomorrow`, today without one: in each group the bot is in, and in a direct chat |
| `/contacts`, `/safety`, `/contacts <who>` | Everyone the Signal account knows, numbered, two short lines each, and whether they're verified; with `<who>`, one in full, with their safety number. `<who>` is their number in the list you were shown last, by `/contacts` or `/trust`, their phone number, ID or the start of it, or their name (see [Contacts and safety numbers](#contacts-and-safety-numbers)) |
| `/contacts add <who> <name>` | Make someone a contact by that name, or rename them; `<who>` as for `/contacts`, a name the longest start of the message that names someone. Someone the bot doesn't know yet can be added by phone number, or by Signal username, as `u:alice.42` or `@alice.42` |
| `/trust`, `/trust <who>` | Everyone's safety numbers, numbered as `/contacts` numbers them, as the Signal apps show them, and whether each is verified; with `<who>`, one's |
| `/trust <who> <safety number>` | Mark a safety number as verified, after comparing it with the one on their phone |
| `/allowed` | Who may use the everyday commands, numbered |
| `/allow <who>` | Let someone use them, or everyone in a group, there; `<who>` as for `/contacts`, or a group the bot is in, by name or group ID |
| `/disallow <n>` | Take that away again, by the number in `/allowed` (or by phone number, ID or name) |
| `/admins` | The admins: those in the configuration, then those added, numbered |
| `/admin add <who>`, `/admin remove <n>` | Make someone an admin, `<who>` as for `/contacts`, or no longer, by their number in `/admins`; for the admins in the configuration alone (see [Who may use what](#who-may-use-what)) |
| `/profile` | The bot's Signal profile: name, About, username, avatar |
| `/name <name>` | Change the bot's name |
| `/about <text>`, `/about remove` | The About text under its name |
| `/avatar` with a picture, `/avatar remove` | Its profile picture: send the picture with `/avatar` as its caption |
| `/username <name>`, `/username remove` | Its username, and a link that starts a chat with it |
| `/timers` | The timers: commands the bot runs on a schedule, such as the daily post |
| `/chats` | Where timers, `/msg` and `/run` can post, numbered |
| `/language <chats> <language>` | Give those chats of `/chats` a language, such as `/language 3,1 sv`, people or groups; `default` for the configuration's (see [Languages](#languages)) |
| `/timer add <when> [<chats>] <commands>` | A new timer, e.g. `/timer add mon-fri 07:30 1,2 /today; /weather; /uniquephoto` |
| `/timer remove <n>`, `/timer run <n>` | Remove a timer, or run it now |
| `/specials` | The [specials](#specials) of your own: commands that post text and what other commands answer |
| `/special add <name> <parts>` | A new special, or a change to one, e.g. `/special add /morning Good morning! /today; /weather; /uniquephoto` |
| `/special remove <name>` | Remove a special, unless a timer runs it |
| `/msg <chats> <text>` | Post the text to other chats, e.g. `/msg 1,2 Hello!` |
| `/run <chats> <commands>` | Run commands and post their answers to other chats, e.g. `/run 1 /status` |
| `/incoming`, `/incoming <n>,<n>` | The 50 latest messages anyone but the admins sent the bot in a direct chat, numbered: when, from whom, and how each starts; `/incoming 4,9` forwards those two to you in full (see [Incoming messages](#incoming-messages)) |
| `/birthday add <date> [<chats>] <who>` | A birthday: a contact's, as `/contacts` finds them, shown in the groups they're in; or someone's not on Signal, by name, shown in the groups `<chats>` numbers in `/chats`, or else in every group (see [Birthdays, name days and holidays](#birthdays-name-days-and-holidays)) |
| `/nameday add <date> [<chats>] <who>` | A name day, as `/birthday add` takes it |
| `/birthday remove <n>`, `/nameday remove <n>` | Remove one, by its number in the list `/birthdays` or `/namedays` showed you last; `/birthday remove 2,5` several |
| `/delete list`, `/delete <n>,<n>` | The bot's 50 latest messages, wherever it sent them, numbered: when, where to, and how each starts; `/delete 2,5,11` deletes those for everyone (see [Who may use what](#who-may-use-what)) |
| `/delivery` | Whether the bot's latest messages arrived: the 30 latest (`delivery_messages`), wherever it sent them, newest first, with how many in the chat got each and read it (see [Delivery](#delivery)) |

And for the admins in any chat, groups too:

| Command | Reply |
|---|---|
| `/delete` | Delete the bot's latest message in the chat, for everyone; sent again, the one before, and so on |

A command can have other names: a few it has had all along (`/test` for
`/status`, `/time` for `/info`, `/safety` for `/contacts`, `/day` for
`/today`), aliases from the configuration, and the names in each of the
bot's languages, which it takes from anyone, whatever the chat's language
(see [Languages](#languages)): `/väder` is `/weather`, `/hjälp` is `/help`,
`/påminn` is `/remind`, `/lista` is `/list`, and `/idag` and `/dagen` are
`/today`; `/help` shows the names of the language spoken in the chat, and
the aliases. An album's shortcuts, which the admins give it with `/album`,
are names for `/photo` with the album (see
[Photos and the daily post](#photos-and-the-daily-post)).
So do the words that follow a command to say what it does, its
subcommands: in Swedish, `lägg till` is `add`, `ta bort` or `radera`
`remove`, `lista` `list`, `töm` `clear`, `kör` `run`, `alla` `all`,
`förhandsvisa` `preview`, `standard` `default` and `genvägar` `shortcuts`,
as in `/lista lägg till mjölk` or
`/timer ta bort 3`. The English ones work too, in any language.

### Who may use what

The admins, `admins` in the configuration and those they add, may use every
command: the everyday ones wherever they're allowed, the admin commands only in a direct
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

The admins in the configuration may make others admins, in a direct chat
with the bot: `/admin add <who>`, who as `/contacts` takes them, and `/admin
remove <n>`, by their number in `/admins`, which lists every admin. Those
added may use every command, as the configuration's admins may, but they
can't add or remove admins, and no command can take away what an admin in
the configuration may do. The [notices](#notices-to-the-admins) go to the
configuration's admins alone, timers run their commands as the first of
them, and the greeting names the first. The admins added are kept by
Signal ID, as a phone number can change hands and a Signal ID can't, in
`data_dir/admins.txt`, a Signal ID a line, as the [allowed
list](#the-allowed-list) is kept: it can be changed by hand too. So someone
the bot hasn't heard from yet, in a direct chat or a group, can't be added
by phone number, as it doesn't know their Signal ID. A removed admin who's
on the allowed list may still use the everyday commands.

People who don't share their phone number on Signal are known only by their
ID. signal-cli-rest-api has no way to take someone out of the contacts, or to
forget them, so the bot can't either.

It marks each command as read, in groups as well as direct chats, and shows
itself typing while it works on the slower ones. Both are best effort: if they
fail, the answer still comes.

Signal lets a message be edited for a day, and the bot answers an edited
command as if it had come instead of the one it edits:

- A command that shows something, or sets a value, such as `/weather` or
  `/name`, runs again.
- One that adds or removes something takes the place of what it edits: what
  that did is undone first, then the edit runs. So editing `/remind 18:00
  Cake` to `/remind 19:00 Cake` leaves one reminder, at 19:00, and editing
  `/list remove 2` to `/list remove 3` puts 2 back first. That's `/remind`,
  `/list`, `/birthday`, `/nameday`, `/timer add` and `remove`, `/special add`
  and `remove`, `/allow`, `/disallow`, `/admin add` and `remove`, and
  `/contacts add`, which renames back first; a contact it made stays, as the bot can't take contacts out.
- What the bot posted, or deleted, can't be undone, so an edit of `/msg`,
  `/run`, `/timer run` or `/delete <n>` isn't run, and the bot says so. One
  of `/delete` alone is let be, quietly, as what it posted would be the next
  to go.

The bot keeps what each command did for a day, in memory only: after a
restart, an edit of a message from before isn't run, as the bot can't tell
what that did, and it says so; send the command anew instead.

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
the bot sends meanwhile, until you ask for it again, or the bot restarts; a
list a timer, `/run` or a special posts doesn't change them. In a group,
`/delete` takes nothing after it, as the list shows what went to every chat.

When something fails (the weather API, the exchange rate, the photo library),
the bot posts the error as `Something went wrong: ...` instead of staying
silent, in what timers post too.

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

### Delivery

Signal's apps confirm each message they get with a delivery receipt, and each
one read with a read receipt, unless read receipts are off in their settings.
The bot keeps them for what it sent in the last day, in memory, so a restart
forgets them. `/delivery`, for the admins in a direct chat, shows its
`delivery_messages` (30) latest messages, wherever it sent them, newest first:
when, where to, how each starts, and how many in the chat got it and read it,
as `📬 3/4 · 👀 2`. A message nobody has confirmed yet shows ⏳, and once nobody
has in 10 minutes, ⚠️; the log has that as a warning too, as Signal took the
message, but it may not have arrived. At `log_level = "DEBUG"`, the log has how
many each message reached in those 10 minutes.

A message longer than 2,000 bytes goes as Signal's apps send one: signal-cli
puts its start in the message and the whole text in a text attachment, which
the apps show with Read more, so nothing is cut off or refused, and it stays
one message. The admins' `/help` is one. A long message to the bot arrives
whole too: signal-cli fetches its text even with
`JSON_RPC_IGNORE_ATTACHMENTS=true`.

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
it says when to try again. `weather_city` isn't counted, so `/weather` and
`/forecast` alone, and `/status`, always get its weather.

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

The daily post is a timer: `/timer add 08:00 1,2 /today; /weather;
/uniquephoto` posts at 08:00 in the bot's `timezone`, whatever the server's
own time zone, to chats 1 and 2 of `/chats`, the day's holidays, and in a
group, the birthdays and name days of those it's for, if there are any (see
[Birthdays, name days and holidays](#birthdays-name-days-and-holidays)),
then the weather, under its heading in bold, then a photo. Every chat gets
the same weather and the same photo. For a heading over the photo, make the
post a [special](#specials), with "Photo of the day!" made bold in Signal:

```
/special add /dailypost /today; /weather; Photo of the day! /uniquephoto
/timer add 08:00 1,2 /dailypost
```

Each folder right in `photos_dir` is an album, named as the folder, its
subfolders part of it; photos right in `photos_dir` are in no album, but
among all photos. `/albums` lists them. A command names an album in any
case, as the longest start of what follows it, so names may have spaces:
`/photo Alice and Bob`. The admins can give an album shortcuts, other names
for `/photo` with it: `/album Alice shortcuts /alice alice` makes `/alice`
and `alice` `/photo Alice`, so `alice 2017` is `/photo Alice 2017`, and
`/album Alice shortcuts -` takes them away. A shortcut is a word, with or
without a `/` first, but not a name the bot answers to already: a command,
an alias or a special. One without a `/` is taken from any message that
starts with it, in a group too, as an alias in the configuration is.

`/uniquephoto` picks a photo at random among those not sent yet in this
round, and counts it; once every photo has been sent, a new round starts.
Each album has a round of its own: `/uniquephoto Alice` picks among Alice's
photos not sent yet, and once all of hers have been, her round starts over,
the others' as they were. Anyone allowed may send it, and each one uses up a
photo of the round. `/photo` picks from all photos, or the album's, and
neither it nor `/onthisday` counts toward the round. The sent photos are
listed in `data_dir/sent-photos.txt` (a temp file in debug mode), by their
paths in the library, so rounds survive restarts; deleting the file starts
them all over.

`/photo 2017` is a photo taken in 2017, at random, and as exactly as you
like, `/photo 2017-05` one taken in May 2017, `/photo 2017-05-14` one taken
that day, and `/photo 2017-05-14 15` one taken from 15:00 to 16:00 that
day; with none then, one taken in the nearest year, month, day or hour that
has some, under how far off it is, such as "Nearest to 2018: 1 year
before". To the minute, `/photo 2024-06-01 15:00` is the photo taken
nearest that moment, in the bot's `timezone`, such as "Nearest to
2024-06-01 15:00: 8 min before". With an album first, as `/photo Alice
2019-03-14`, from that album alone. A photo that doesn't say
when it was taken is never the nearest, but still comes at random. When each
photo was taken is as its caption has it: the bot reads it once for each
photo, from the file's header, and keeps it in memory, about 400 bytes a
photo, reading a photo again only when it changes. So the first `/photo`
with a date, `/albums` or `/onthisday` after a start takes longer: about
2.5 s for 7,600 photos on a desktop whose disk cache has them.

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
An album can have a birth date of its own, for whoever it's about:
`/album Alice 2019-06-15` sets it, `/album Alice -` takes it away again,
and `/album Alice` shows the album. They're kept in `data_dir/albums.txt`,
with the shortcuts, a line each, which can be changed by hand: the bot reads
it again when it changes. An album without one takes `photos_birth_date`.
A photo with a GPS position links to where it was taken: on Google Maps, or
with `photos_map = "openstreetmap"`, OpenStreetMap's short link, such as
`https://osm.org/go/0bC2KJ9q?m=`, which shows a marker there.

`/onthisday` is a photo taken on this day in an earlier year, captioned as
`/photo` captions it, under "3 years ago today" in bold; without one, a photo
taken within three days of the day, the nearest first, under "3 years ago,
around this day". `/onthisday Alice` picks from that album alone. Like
`/photo`, it doesn't count toward the round.

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

`/today` (or `/day`) names the day: in every chat, the day's holidays, flag
days and traditions in the countries of `holidays`, by their codes below,
such as `holidays = ["SE", "GR"]` (none by default), each after its
country's flag, a day two keep once, after both flags; and in a group, the
birthdays and name days of those it's for:

```
🇸🇪 National Day of Sweden · flag day
🎂 Alice turns 36 today!
🌸 Happy name day, Bob!
```

On a day with none of these, it says "Nothing special today.", but in what a
timer, a special or `/run` posts, nothing, so a daily post of `/today;
/weather` is the weather alone then.

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
- The others: their public holidays, those the whole country keeps, each on
  its own day, not on a day off in lieu; Valentine's Day, Easter Sunday,
  Christmas Eve and New Year's Eve; and what the table says. Mother's Day and
  Father's Day are there where the whole country keeps them on the same day.
  Their names are in English, in Swedish too, but those they share with
  Sweden or Greece.

| Code | Country | Besides its public holidays |
|---|---|---|
| `AT` | Austria | Mother's and Father's Day, Advent, St Nicholas' Day |
| `AU` | Australia | Mother's and Father's Day, Remembrance Day |
| `BE` | Belgium | Mother's and Father's Day, St Nicholas' Day |
| `BG` | Bulgaria | By the Orthodox Easter |
| `CA` | Canada | The federal holidays; Mother's and Father's Day, St Patrick's Day, Halloween |
| `CH` | Switzerland | Those most cantons keep; Mother's and Father's Day, the Federal Day of Prayer, Advent, St Nicholas' Day |
| `CY` | Cyprus | By the Orthodox Easter; as Greece's: Tsiknopempti, Maundy Thursday, Holy Saturday, Mother's and Father's Day |
| `CZ` | Czechia | Mother's and Father's Day, Walpurgis Night |
| `DE` | Germany | Mother's and Father's Day (Ascension Day), Advent, St Nicholas' Day |
| `DK` | Denmark | Mother's and Father's Day, Constitution Day, Midsummer Eve, Advent |
| `EE` | Estonia | Mother's and Father's Day, Walpurgis Night, Midsummer Eve |
| `ES` | Spain | Mother's and Father's Day |
| `FI` | Finland | Mother's and Father's Day, Shrove Tuesday, Walpurgis Night, Advent |
| `FR` | France | Mother's and Father's Day, Shrove Tuesday |
| `GB` | United Kingdom | England's and Wales's bank holidays; Mother's and Father's Day, the patron saints' days, Shrove Tuesday, Halloween, Guy Fawkes Night, Remembrance Sunday |
| `GR` | Greece | As above |
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
| `RO` | Romania | By the Orthodox Easter; Mother's and Father's Day |
| `SE` | Sweden | As above |
| `SI` | Slovenia | Mother's and Father's Day |
| `SK` | Slovakia | Mother's and Father's Day |
| `US` | United States | The federal holidays; Mother's and Father's Day, St Patrick's Day, Halloween |

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
`/chats`, or else in every group. The answer says
which, so a contact's name mistyped shows. Birthdays and name days never
show in a direct chat. A birthday on 29 February comes on the 28th in other
years.

To see what `/today` will say on a day, before it comes: `/today preview
10-25` (in Swedish, `/idag förhandsvisa 10-25`), or `/today preview` for
today, shows the admins what it says in each group the bot is in, and in a
direct chat.

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
has the checks: how many passed (`✅ All 13 checks passed`, or `❌ 2 of 13
checks failed`), the failed ones with what went wrong, then the rest, a short
line each; a check that took a second or more says how long. The second has
the details, a section each, in short lines:

- **Bot:** the versions of nejomibot, signalbot, Python and
  signal-cli-rest-api, its time zone, `timezone`, which the times the bot
  shows are in, without saying so each time, uptime, the next timer run,
  messages waiting to be sent again, how long the command took to arrive. signal-cli's version isn't
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
empty, disk and memory use are under 90% of their limits, NTP keeps the
clock synchronized, and the [backups](#backups) are made: the last didn't
fail, and the newest is less than two days old. A check that takes more than 20 seconds fails.

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
were shown last; a list a timer, `/run` or a special posts doesn't change
them. Timers and `/run` can run `/incoming` too: `/run 1 /incoming 4,9`
forwards messages 4 and 9 of your list to chat 1.

### Contacts and safety numbers

`/contacts` lists everyone the bot's Signal account knows, numbered: its
contacts, then everyone else it knows, as those in its groups, then anyone
it only has a safety number for, each by name, with their phone number, the
name they gave themselves in Signal (🪪) where it isn't the one in the
contacts, and their Signal username, such as `@alice.42`, where signal-cli
knows it; not the bot itself, whose own safety number is nobody's to
compare, nor counted. `/contacts <n>` shows them as `/profile` shows the
bot: profile name, username and number a line each. Signal doesn't share
usernames: signal-cli knows only those of the people it found by theirs, as
`/contacts add u:alice.42 Alice` does, so most show without one. `/trust` lists the same
people by the same numbers, with their safety numbers, three rows of four
groups of five digits, as the Signal apps show them, and whether each is
verified. A number from the list you were shown last, by either, stands for
that person wherever a command takes `<who>`:

```
/contacts 3                  them, in full
/trust 3                     their safety number
/trust 3 12345 67890 ...     marks it verified, once compared with their phone's
/contacts add 3 Bobby        a contact, by that name
/contacts add u:bob.42 Bob   someone new, by Signal username
/allow 3                     on the allowed list
/admin add 3                 an admin
```

As with `/delete list`, the numbers are those of the list you were shown
last, whatever changes meanwhile, until you ask for it again, or the bot
restarts; each admin has their own. A name, phone number, Signal ID or the
start of one works too. To verify someone, compare the safety number with
the one their phone shows in their chat with the bot (the bot's name, then
View safety number), in person or on a call you trust, then send it with
`/trust`. `/birthday add` takes no number for `<who>`, as numbers there are
chats.

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
you would in a direct chat with the bot, numbers in it by the lists you were
shown, and posts its answers to the chats, one command after the other;
every chat gets the same photo. Like a timer, `/run` can't change timers,
specials, birthdays, albums or who may use the bot, nor run `/msg` or `/run`, nor
what's each chat's own: `/remind`, `/list`, `/birthdays` and `/namedays`.
Mind what goes where: `/status` shows phone numbers and the
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
/allow 3                  someone in /contacts, by their number there
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
disallow an admin, who keeps every command whatever the list says. `/disallow` on a group says which timers still post
there, as timers post to their chats whoever may use the bot.

### Names and phone numbers

The bot shows people by the name signal-cli has for them, else by what the
list has after their `#`, with their phone number where it's known:
`Alice (+46701234567)`, else their Signal username, `Alice (@alice.42)`, in `/allowed`, `/admins`, `/chats`, `/timers`,
`/delete list`, `/delivery`, `/incoming`, and what `/msg` and `/run` answer.

Someone who doesn't share their number in Signal is known to signal-cli by
their Signal ID alone, so a number on the list could neither name them nor
match what they write to the bot directly, which comes without it. So the
bot looks such numbers up, once each: at a start, for every number on its
lists that signal-cli doesn't know yet, and as `/allow` adds one. Signal
says whose each number is, unless its owner keeps it from being found by
number, and signal-cli keeps the two together, so their name shows, and
their direct messages match the list. Signal limits how many numbers an
account looks up, so the bot never asks twice about a number in one run.
Someone who can't be found by number can be allowed by their Signal ID,
through `/allow` with their number in `/contacts`. Once the bot knows a
name, it writes it after the `#` of the lists' lines that have none, so the
files say who's who too.

## Timers

A timer runs bot commands on a schedule, and posts what they answer to one or
more chats, such as a daily post. The admins manage them in a direct chat
with the bot:

```
/chats                                     where timers can post, numbered
/timer add 08:00 1,2 /today; /weather; /uniquephoto   a daily post, to chats 1 and 2
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
bot, so it can run any command but those that change timers, specials,
birthdays, albums or who may use the bot, post to other chats themselves (`/msg`,
`/run`), or are each chat's own (`/remind`, `/list`, `/birthdays`,
`/namedays`), and posts its answers to all the timer's chats before the next
command runs: every chat gets the same photo, and each group the birthdays
of its own. What only shows something it can run, wherever it posts it:
`/delivery` at 08:15 to your own chat, say, or `/chats`, `/allowed`,
`/admins`, `/incoming`, `/today preview`, and `/timers` and `/specials`
alone, as with more after them they change things. It can run
[specials](#specials) of your own too.

Timers are kept in `data_dir/timers.txt`, a line each, its fields
separated by `|`: the timer's number, when, its chats (group IDs and phone
numbers, so only the bot's user may read the file), its commands by their
English names, and when it last ran, or was added:

```
1 | daily 08:00 | group.abcd… group.efgh… | /today; /weather; /uniquephoto | 2026-10-13 08:00:01+02:00
```

The bot rereads the file within half a minute of a change, so it can be
changed while the bot runs: with `/timer`, by hand, or with `nejomibot-timers`,
which lists, adds and removes timers from a terminal, through the bot's own
code, so it takes what `/timer` takes and numbers the chats as `/chats`
does. It's in the bot's image:

```sh
podman exec nejomibot nejomibot-timers                     # the timers
podman exec nejomibot nejomibot-timers chats
podman exec nejomibot nejomibot-timers add "08:00" 1,2 "/today; /weather; /uniquephoto"
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
and what other commands answer. The admins make them in a direct chat with
the bot, mostly for timers:

```
/special add /morning Good morning! /today; /weather; /uniquephoto
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

Two to start from, their headings made bold in Signal: the
[daily post](#photos-and-the-daily-post) with "Photo of the day!" over its
photo, and a proverb or quote from `fortunes_svenska`, the bot's own
library, under "Proverb or quote of the day:", what explains a proverb in
italics, as `/fortune` has it:

```
/special add /dailypost /today; /weather; Photo of the day! /uniquephoto
/special add /dailyquote Proverb or quote of the day: /fortune fortunes_svenska
```

A special runs its commands as a timer does, as an admin would in a direct
chat with the bot, and posts what they answer one after the other: it can
have any command a timer can, but not another special of your own. Specials
are for timers, `/run` and the admins in a direct chat. Editing a message
runs a special of your own again, as its commands change nothing; an edit
of `/special add` or `remove` takes the place of what it edits. A special a
timer runs can be changed, but not removed: remove the timer first.

The specials of your own are kept in `data_dir/specials.txt`, a line each:
the name, a `|`, and the parts, their commands by their English names, their
texts in signal-cli-rest-api's marks for the formatting: `**bold**`,
`*italic*`, `***both***`, `~strikethrough~`, `` `monospace` `` and
`||spoiler||`, with a `\` before a `*`, `~`, `` ` `` or `|` that shows as it
is:

```
/morning | **Good morning!** /today; /weather; /uniquephoto
```

The bot reads the file again when it changes, so it can be changed by hand
too, and leaves comments and lines it can't read as they are; `/specials`
lists those.

## Languages

The bot's messages are written in English. `language` in the configuration
picks a translation from [nejomibot/locale](nejomibot/locale), which it
speaks wherever nobody chose another.

Each chat can have a language of its own. `/language sv` (in Swedish
`/språk`) makes the bot speak Swedish in a direct chat with whoever sends
it, and in a group, sent by an admin, for everyone in it;
`/language default` goes back to the configuration's. An admin, in a
direct chat, can set others', by their numbers in `/chats`:
`/language 3,1 sv`. `/language` alone lists the languages, and for an
admin the chats that have one of their own. The bot answers in the chat's language, and posts to it in it:
the timers' posts, `/run`'s, reminders, the greeting and the notices to each
admin. A timer that posts to chats of two languages runs its commands once
in each, so every chat gets the same photo, each captioned in its language,
and the round uses up one. Each chat's language is kept in
`data_dir/languages.txt`, a line each, which can be changed by hand. A
special's texts stay as the admins wrote them, and the weather's names of
places come in each chat's language, when OpenWeatherMap has them.

- `sv.po` translates the messages into Swedish, and `el.po` into Greek, in
  gettext's format, which translation tools such as Poedit read.
  Untranslated messages show in English.
- `sv.toml` has the language's own name, `Svenska`, its names for commands,
  like the aliases in the configuration, its words for days and times in
  `/timer add`, and for subcommands, such as `lägg till` for `add`. A
  command lists the subcommands it takes, so only those are read, right
  after it; the timers and specials files keep them in English. The bot
  takes every language's names and words, from anyone, whatever the chat's
  language; `/help` shows those of the language spoken there.

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
"/weather" = ["/w"]
```

A message that starts with an alias is taken as if it started with its
command: `pic` sends a photo, `/f startrek` with `"/fortune" = ["/f"]` a
Star Trek fortune. An alias is one word, with or without `/`; without one,
like `pic`, it's taken from anyone allowed who writes just that word. The
bot's own names for commands, in English or its languages, all start with `/`.
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
the bot has been up, and so its container, as the bot is its process, the
bot's memory, with its peak and the container's limit, if there is one, and
the [backups](#backups): how many, and how old the newest and the oldest
are, or why the last failed. A failed backup doesn't make the ping a
`/fail`, as it isn't the bot's health; `/status`'s Backups check fails.
healthchecks.io shows it with each ping in the check's log. signal-cli's
version isn't there: signal-cli-rest-api doesn't say it.

### Notices to the admins

The bot tells the admins in the configuration itself, in a direct chat with
each, what they'd otherwise find out late:

- **Each start.** That it's up, since when, and how long it took to be
  ready; after an update, the version before; after a crash, a kill or a
  power cut, that messages that had waited less than half a minute may be
  lost. Then what needs their attention, such as lines of its files it
  can't read, which do nothing, a clock that isn't synchronized, or messages
  still waiting to be sent; then how it is: its timers and when the next
  runs, its groups, chats allowed and admins, the photos, the backups, the
  clock, its memory, signal-cli-rest-api's version, and where it runs:

  ```
  🟢 nejomibot 0.99.11 started
  Friday 23 October 09:46 · ready in 14 s

  🔄 Updated from 0.99.10
  ⚠️ timers.txt: 1 line the bot can't read, left as it is

  ⏰ 2 timers, the next Saturday 24 October 08:00
  👥 In 3 groups · 6 chats allowed · 1 admin
  📷 Photo library: 1151 photos
  💾 Backups: 12, the newest 5 h old, the oldest 12 d 5 h old
  🕐 Clock: synchronized, max error 0.02 s
  🧠 Bot memory: 74.1MB (peak 74.9MB)

  🔌 signal-cli-rest-api unset, json-rpc mode
  🐍 signalbot 2.1.3 · Python 3.14.0
  🖥️ Podman on bothost · aarch64
  ```

  Once in ten minutes at most, but after an update: a start sooner after
  the last one the admins heard of tells them once the ten minutes are up,
  so a crash loop can't flood them, nor run into Signal's rate limits; if
  the bot stops before then, the next start tells instead. It knows from
  `data_dir/run.json`, which it writes as it starts, as it tells, and as it
  stops.
- **Signal rate-limits the bot.** As it starts to, how to lift the limit:
  `signal-account.sh rate-limit --to <your number>`, and a captcha. Once in
  six hours at most, and tried once, as while Signal rate-limits the bot, it
  may not get through either; the health check says so too, while messages
  wait, and with `healthcheck_url`, so does the ping.
- **A safety number changes.** signal-cli won't send to someone whose safety
  number changed until it's trusted, so the admins hear whose, to compare it
  with `/trust <who>`, then trust it with `/trust <who> <safety number>`. The bot looks every `healthcheck_minutes`,
  which asks nothing of Signal's servers, and at a start, for changes since
  it last ran.

In debug mode, which starts anew each time, each start tells, marked as
`🐞 Debug mode`, with no update or stop before it to tell of.

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
with safety numbers or the bot's own profile and username, fetch one
attachment, or hear the receipts for the bot's messages, so for those the bot
asks signal-cli-rest-api itself: [rest.py](nejomibot/rest.py), each function
saying what signalbot lacks. The receipts come on a websocket of the bot's
own, beside signalbot's, as signal-cli-rest-api sends everything it receives
to each. When signal-cli-rest-api or Signal change, a newer signalbot covers
most of it, and rest.py is the one place to look at for the rest.

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
fixes, `1792271041-ci` from 2026-10-17, with signal-cli 0.14.9, by its digest,
as CI builds' tags may not be kept; it says `unset` for its version, which
signalbot takes as a build after a release.
The signal-cli-rest-api health check fails on 0.101 or older. 0.101, and
builds from before 2026-10-13, also drop what reaches a websocket while it's
busy with the message before: of a burst of receipts some can be lost, so
`/delivery`'s counts can come out low. The pinned build has that fixed.

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
timers, the specials, the allowed list, the admins added, the reminders, the
lists, the birthdays and name days, the photos sent this round, the messages waiting to
be sent and the version that ran last, it keeps in `data_dir` (`/data` in the
container, beside the config), which must be there at startup: those files
list phone numbers, so only the bot's user may read them. Each is written
whole, through a temp file that's on disk before it takes the file's place,
so neither a crash nor a power cut leaves one half written. Every night the
bot [backs them up](#backups) in `data_dir/backups`.

### Debug mode

With `NEJOMIBOT_DEBUG=1` the bot only talks to `debug_group`, and to the
admins, and keeps its list of photos sent, its allowed list, the admins
added, its timers, its specials, its reminders, lists and birthdays, and its
waiting messages in a temp folder of its own instead of `data_dir`, new at
each start and gone when it stops: the allowed list just `debug_group`, and
no admins added, timers, specials or birthdays of your own. `/chats` offers only
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

### Backups

Every day at `backups_at`, 04:00 by default, in `timezone`, the bot backs
up what it keeps in `data_dir`, with its config and `config.example.toml`,
into `backups_dir`, or `data_dir/backups` if that isn't set: a tar archive
compressed with Zstandard, named by when it was made, such as
`nejomibot-2026-10-19_0400.tar.zst`, which unpacks into a folder of the same
name. At a start it makes one at once if the latest is a day old or more,
as when the bot was down at `backups_at`. When nothing in the files has
changed since the latest backup, by what they say, whatever their times, it
makes none: the latest still has it all. A bot that posts a photo of the
day changes its list of photos sent daily, so it backs up daily. It keeps
the newest `backups_kept` (30 by default) and deletes the older ones;
anything else in the folder it leaves alone. `backups = false` makes none,
as when `data_dir` is backed up otherwise. A `backups_at` in the hour
daylight saving time skips or repeats (02:00 to 03:00 in most of Europe and
North America) comes an hour late on the day it starts, and twice on the
day it ends, the second likely finding nothing changed.

`backups_dir` may be a folder of its own, best on another disk: the bot's
user must be able to write in it, and in the container it must be mounted,
say `Volume=/mnt/backup/nejomibot:/backups:U` in the Quadlet and
`backups_dir = "/backups"`, as the rest is read-only. The log says what
each backup had, that nothing changed, or that one failed. `/status` has a
Backups check, which says how many there are, how old the newest and the
oldest are, and why the last was skipped, if it was (`the last skipped:
nothing changed`), and which fails when the last backup failed, or when the
backups haven't been current for two days: no backup made, nor found
needless; the [health check pings](#health-checks) say the same:

```
Backups: 30, the newest 2 d 6 h old, the oldest 41 d 6 h old; the last skipped: nothing changed
```

An archive has every file in `data_dir`, but `run.json`, which only says how
the bot last ran, and files over 10 MB, which aren't the bot's; and not the
messages waiting to be sent, which would go out again, late. The config is
in it wherever it is, and the sample config as the version that made the
backup has it. Only the bot's user may read the archives, as they list phone
numbers and the config has the API key. They're on the same disk as what
they back up, so copy them elsewhere too, with the rest of `data_dir`. In
debug mode there are none.

To restore, stop the bot, unpack a backup in the data folder, as the user
that owns it (root, or for a rootless Podman, yours), and copy back what's
needed with `cp -p`, which keeps the bot's user as its owner, then start the
bot again:

```sh
cd /srv/nejomibot/data
tar -xf backups/nejomibot-2026-10-19_0400.tar.zst   # GNU tar 1.31 or later, with zstd
cp -p nejomibot-2026-10-19_0400/birthdays.txt .
```

Without `zstd` on the host, `python3 -m tarfile -e <archive> .` unpacks it
with Python 3.14 or later; in the bot's container, `python -m tarfile -l
/data/backups/<archive>` lists what's in one.

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
  admins.py     /admins, /admin: admins besides those in the config
  commands.py   commands: each handler's, by any name, and how they're answered
  i18n.py       translations
  locale/       the translations: sv.po and el.po, the messages; sv.toml and el.toml, the names
  photos.py     /photo, /uniquephoto, /cache: photos with EXIF date, age, location; albums
  albums.py     /albums, /album: the albums, their birth dates and shortcuts
  onthisday.py  /onthisday: a photo from this day in an earlier year
  today.py      /today, /today preview: the day's holidays and birthdays
  specials.py   /specials, /special: several posts in one
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
  contacts.py   /contacts, /trust: everyone known, numbered, with safety numbers
  profile.py    /profile, /name, /about, /avatar, /username
  delete.py     /delete: delete the bot's latest messages, here or anywhere
  delivery.py   /delivery: whether they arrived, from the receipts phones send
  incoming.py   /incoming: the latest messages people sent the bot
  greeting.py   the greeting for the allowed list's messages that aren't commands
  notices.py    notices to the admins: each start, a rate limit, safety numbers
  reminders.py  /remind: reminders, posted in their chat when due
  lists.py      /list: a list for each chat
  birthdays.py  /birthdays, /namedays, /birthday, /nameday: for /today
  holidays.py   the calendar's holidays, flag days and traditions
  timers.py     /timers, /chats, /timer: commands on a schedule, a daily post
  timers_cli.py nejomibot-timers: the timers from a terminal
  relay.py      /msg, /run: post to other chats
  help.py       /help
  system.py     process, container and host facts from /proc and /sys
  publicip.py   public IPv4/IPv6 addresses, ASN and location
  files.py      the files in data_dir: written privately, read back when changed
  backups.py    the daily backup of data_dir and the config, in data_dir/backups
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
