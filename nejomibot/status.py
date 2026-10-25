"""/status and /test report on the bot, Signal, network and host.

Two messages, to fit Signal's narrow bubbles: first the checks, each of which
passes or fails, the failed ones first, with what went wrong; then the
details, a section each, in short lines. The checks start with the health
checks (health.py).
"""

import asyncio
import logging
import os
import re
import shutil
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from signalbot import About, DataMessageContext, SignalBot

from . import access, publicip, system
from .account import (
    Account,
    account_lines,
    device_lines,
    fetch_account,
)
from .commands import Command, Handler, answer
from .config import PHONE_NUMBER, get_settings
from .health import (
    STARTED,
    Check,
    CheckFailed,
    check_health,
    memory_check,
    run_check,
    up_since,
    version_lines,
)
from .i18n import _, format_duration, format_file_size, ngettext
from .info import fetch_rate
from .messages import arrival_delay, describe, escape, outbox
from .photos import by_album, scan_photos
from .timers import timekeeper
from .weather import UNITS, fetch_weather

logger = logging.getLogger(__name__)

DISK_FULL = 0.9  # fraction of the photo disk in use

type Section = tuple[str, str, list[str]]  # an icon, a title, and its lines


# Checks


async def check_groups(account: Awaitable[Account | Exception]) -> str:
    """The bot is still in every group on the allowed list, by the groups of
    the account, which /status reads once for all its checks."""
    if isinstance(found := await account, Exception):
        raise found
    member_of = {group.id for group in found.groups if group.member}
    allowed = {
        entry.id
        for entry in access.allowed_list.current().entries
        if access.is_group(entry.id)
    }
    if missing := allowed - member_of:
        names = ", ".join(sorted(f"{group[:14]}…" for group in missing))
        raise CheckFailed(_("not a member of {groups}").format(groups=names))
    return _("member of {count}, all {allowed} allowed").format(
        count=len(member_of), allowed=len(allowed)
    )


async def check_weather() -> str:
    _where, data = await fetch_weather()
    settings = get_settings()
    unit = UNITS.get(settings.weather_units, "°")
    return _("{temperature} in {city}").format(
        temperature=f"{round(data['main']['temp'])}{unit}", city=settings.weather_city
    )


async def check_rates(base: str, quote: str) -> str:
    """The rate as the API gives it now, as a check of whether it answers."""
    return f"1 {base} = {await fetch_rate(base, quote, fresh=True):.2f} {quote}"


async def check_photos() -> str:
    photos = await asyncio.to_thread(scan_photos)
    if not photos:
        raise CheckFailed(_("no photos in {dir}").format(dir=get_settings().photos_dir))
    text = ngettext("{count} photo", "{count} photos", len(photos)).format(
        count=len(photos)
    )
    if albums := len(by_album(photos).keys() - {None}):
        text += " " + ngettext("in {count} album", "in {count} albums", albums).format(
            count=albums
        )
    return text


def disk_check(path: Path) -> Check:
    name = _("Photo disk")
    try:
        usage = shutil.disk_usage(path)
    except OSError as e:
        return Check(name, ok=False, detail=str(e))
    if not usage.total:
        return Check(
            name, ok=False, detail=_("no size reported for {path}").format(path=path)
        )
    detail = _("{free} free of {total}").format(
        free=format_file_size(usage.free), total=format_file_size(usage.total)
    )
    return Check(name, ok=usage.used / usage.total < DISK_FULL, detail=detail)


def clock_check() -> Check:
    name = _("Clock")
    sync = system.clock_sync()
    if sync is None:
        return Check(name, ok=True, detail=_("unknown"))
    synchronized, max_error = sync
    if not synchronized:
        return Check(name, ok=False, detail=_("not synchronized (is NTP running?)"))
    detail = _("synchronized, max error {error} s").format(error=f"{max_error:.2f}")
    return Check(name, ok=True, detail=detail)


def blocked_check(name: str, account: Account) -> Check:
    if blocked := account.blocked_recipients(access.recipients()):
        detail = _("blocked: {who}").format(who=", ".join(blocked))
        return Check(name, ok=False, detail=detail)
    return Check(name, ok=True, detail=_("none blocked"))


def username_check(account: Account) -> list[Check]:
    """For an account without a phone number, its username: the only way
    anyone can find it on Signal."""
    me = account.me
    if re.match(PHONE_NUMBER, account.id) or (me is not None and me.number):
        return []
    name = _("Username")
    if me is not None and me.username:
        return [Check(name, ok=True, detail=f"@{me.username}")]
    detail = _("none, and without a phone number, nobody can find the bot")
    return [Check(name, ok=False, detail=detail)]


def account_checks(account: Account | Exception) -> list[Check]:
    """Everyone's safety number trusted, nobody the bot talks to blocked, and
    without a phone number, a username."""
    names = (_("Safety numbers"), _("Recipients"))
    if isinstance(account, Exception):
        return [Check(name, ok=False, detail=describe(account)) for name in names]
    untrusted = account.untrusted()
    return [
        Check(
            names[0],
            ok=not untrusted,
            detail=_("untrusted, so messages are not sent: {who}").format(
                who=", ".join(untrusted)
            )
            if untrusted
            else _("all trusted"),
        ),
        blocked_check(names[1], account),
        *username_check(account),
    ]


def system_checks() -> list[Check]:
    """Blocking: reads /proc and /sys."""
    return [disk_check(get_settings().photos_dir), memory_check(), clock_check()]


# Report


def bot_lines(about: About | None, message_delay: float) -> list[str]:
    """The bot's section: its versions, and its time zone, which the times
    the bot shows are in, without saying so each time."""
    settings = get_settings()
    lines = [
        *version_lines(about),
        _("Time zone {zone}").format(zone=settings.timezone),
        up_since(STARTED),
    ]
    if next_run := timekeeper.next_run():
        lines.append(
            _("Next timer run {time}").format(
                time=f"{next_run.astimezone(settings.tz):%Y-%m-%d %H:%M}"
            )
        )
    else:
        lines.append(_("No timer to run"))
    waiting = len(outbox)
    lines.append(
        ngettext(
            "{count} message queued for retry",
            "{count} messages queued for retry",
            waiting,
        ).format(count=waiting)
    )
    if settings.debug:
        lines.append(
            _("Debug mode: communicating with {group} only").format(
                group=settings.debug_group
            )
        )
    lines.append(
        _("Your message took {seconds} s to arrive").format(
            seconds=f"{message_delay:.1f}"
        )
    )
    return lines


def container_lines() -> list[str]:
    """Blocking: reads /proc and /sys."""
    engine = system.container_engine()
    cpu = os.times()
    hostname = os.uname().nodename
    if engine:
        where = _("In a {engine} container, hostname {hostname}").format(
            engine=engine, hostname=hostname
        )
    else:
        where = _("Not in a container, hostname {hostname}").format(hostname=hostname)
    process: list[str] = []
    if threads := system.thread_count():
        process.append(threads_text(threads))
    if files := system.open_files():
        process.append(
            ngettext("{count} open file", "{count} open files", files).format(
                count=files
            )
        )
    process.append(
        _("CPU time {duration}").format(
            duration=format_duration(timedelta(seconds=cpu.user + cpu.system))
        )
    )
    addresses = [
        ip for family in system.ROUTE_PROBES if (ip := system.local_ip(family))
    ]
    lines = [
        where,
        f"pid {os.getpid()} · uid {os.getuid()}",
        " · ".join(process),
        "IP " + (" · ".join(addresses) or _("none (no route to the internet)")),
    ]
    if servers := system.nameservers():
        lines.append(f"DNS {' · '.join(servers)}")
    return lines


def threads_text(count: int) -> str:
    return ngettext("{count} thread", "{count} threads", count).format(count=count)


def host_lines() -> list[str]:
    """Blocking: reads /proc and /sys."""
    uname = os.uname()
    lines: list[str] = []
    if model := system.hardware_model():
        if system.is_virtual_machine():
            model += " " + _("(virtual machine)")
        lines.append(model)
    lines += [
        ngettext(
            "{cpu}, {count} CPU", "{cpu}, {count} CPUs", os.cpu_count() or 0
        ).format(cpu=system.cpu_model() or uname.machine, count=os.cpu_count()),
        f"{uname.sysname} {uname.release} {uname.machine}",
    ]
    if uptime := system.uptime():
        lines.append(up_since(datetime.now(UTC) - uptime))
    load = _("Load {load}").format(
        load=" ".join(f"{load:.2f}" for load in os.getloadavg())
    )
    if threads := system.host_threads():
        load += f" · {threads_text(threads)}"
    lines.append(load)
    if pressure := system.pressure():
        waits = " · ".join(f"{name} {pct:.1f}%" for name, pct in pressure.items())
        lines.append(_("Waiting (last minute): {waits}").format(waits=waits))
    meminfo = system.proc_fields(system.PROC / "meminfo")
    if "MemTotal" in meminfo and "MemAvailable" in meminfo:
        lines.append(
            _("Memory {available} available of {total}").format(
                available=format_file_size(meminfo["MemAvailable"]),
                total=format_file_size(meminfo["MemTotal"]),
            )
        )
        if swap := meminfo.get("SwapTotal"):
            used = swap - meminfo.get("SwapFree", swap)
            lines.append(
                _("Swap {used} used of {total}").format(
                    used=format_file_size(used), total=format_file_size(swap)
                )
            )
    if temps := system.temperatures():
        lines.append(
            "🌡️ "
            + " · ".join(
                f"{part} {'/'.join(f'{t:.0f}' for t in values)}°C"
                for part, values in temps.items()
            )
        )
    return lines


def checks_text(checks: list[Check]) -> str:
    """The first message: how many checks passed, those that failed with what
    went wrong, then those that passed, a short line each. Styled."""
    failed = [check for check in checks if not check.ok]
    if failed:
        summary = _("❌ {failed} of {count} checks failed").format(
            failed=len(failed), count=len(checks)
        )
    else:
        summary = _("✅ All {count} checks passed").format(count=len(checks))
    parts = [f"🩺 **{escape(_('Status'))}**\n{escape(summary)}"]
    if failed:
        parts.append(
            "\n".join(f"❌ **{escape(c.name)}**\n{escape(c.shown)}" for c in failed)
        )
    if passed := [check for check in checks if check.ok]:
        parts.append("\n".join(escape(f"✅ {c.name} · {c.shown}") for c in passed))
    return "\n\n".join(parts)


def details_text(sections: list[Section]) -> str:
    """The second message: a section each for the bot, Signal and the
    machine, under its icon and title. Styled."""
    return "\n\n".join(
        f"{icon} **{escape(title)}**\n" + escape("\n".join(lines))
        for icon, title, lines in sections
        if lines
    )


async def account_or_error(bot: SignalBot) -> Account | Exception:
    try:
        return await fetch_account(bot)
    except Exception as e:
        logger.warning("Could not read the Signal account: %s", describe(e))
        return e


async def status_messages(bot: SignalBot, message_delay: float) -> list[str]:
    # Read once, for the account's checks and lines and the groups check,
    # which a timeout of its own doesn't cancel (shield)
    account_read = asyncio.ensure_future(account_or_error(bot))
    # gather() starts both groups at once
    info = asyncio.gather(
        publicip.internet_lines(),
        asyncio.to_thread(container_lines),
        asyncio.to_thread(host_lines),
    )
    remote: list[Awaitable[Check]] = [
        run_check(
            _("Signal groups"), lambda: check_groups(asyncio.shield(account_read))
        ),
        run_check("OpenWeatherMap", check_weather),
    ]
    if pair := get_settings().exchange_rate:
        remote.append(run_check(_("Exchange rates"), lambda: check_rates(*pair)))
    remote.append(run_check(_("Photo library"), check_photos))
    health, others, local = await asyncio.gather(
        check_health(bot), asyncio.gather(*remote), asyncio.to_thread(system_checks)
    )
    internet, container, host = await info
    account = await account_read
    checks = [*health.checks, *account_checks(account), *others, *local]
    signal_lines = [
        *([] if isinstance(account, Exception) else account_lines(account)),
        *device_lines(health.devices, datetime.now(UTC)),
    ]
    sections: list[Section] = [
        ("🤖", _("Bot"), bot_lines(health.about, message_delay)),
        ("📱", _("Signal account"), signal_lines),
        ("🌐", _("Internet"), internet),
        ("📦", _("Container"), container),
        ("🖥️", _("Host"), host),
    ]
    return [checks_text(checks), details_text(sections)]


class Status(Handler):
    commands = (Command("/status"),)

    async def handle(self, context: DataMessageContext, command: Command) -> None:
        delay = arrival_delay(context)  # before the read receipt
        await answer(
            context,
            lambda: status_messages(context.bot, delay),
            slow=True,
            styled=True,
        )
