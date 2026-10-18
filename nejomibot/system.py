"""Facts about this process, its container and the host, from /proc and /sys.

All of it is readable in an unprivileged container. /proc and /sys mostly show
the whole machine, so in the container they still describe the host. Each
function returns None (or nothing) when its source is missing, e.g. outside
Linux or in a VM without temperature sensors.
"""

import ctypes
import os
import socket
from datetime import timedelta
from pathlib import Path

PROC = Path("/proc")
SYS = Path("/sys")
CONTAINERENV = Path("/run/.containerenv")  # podman creates it in every container
RESOLV_CONF = Path("/etc/resolv.conf")
# Public addresses to look up the route to the internet with (Cloudflare DNS)
ROUTE_PROBES = {socket.AF_INET: "1.1.1.1", socket.AF_INET6: "2606:4700:4700::1111"}

# Temperature sensors worth showing: hwmon driver -> (part, label of the reading).
# Others (motherboard chips, ACPI zones) are often wrong. SATA drives (drivetemp)
# are left out because reading them can delay a disk's spin-down.
SENSORS = {
    "k10temp": ("CPU", "Tctl"),
    "zenpower": ("CPU", "Tdie"),
    "coretemp": ("CPU", "Package id 0"),
    "cpu_thermal": ("CPU", None),
    "nvme": ("NVMe", "Composite"),
}
# DMI fill-ins for "no value"
NO_VALUE = {
    "",
    "default string",
    "not applicable",
    "none",
    "o.e.m.",
    "system manufacturer",
    "system product name",
    "to be filled by o.e.m.",
}
TIME_ERROR = 5  # adjtimex() state: clock not synchronized


def read(path: Path) -> str | None:
    try:
        return path.read_text()
    except OSError:
        return None


def proc_fields(path: Path) -> dict[str, int]:
    """The 'Name: 1234 kB' lines of /proc/meminfo or /proc/*/status, in bytes."""
    fields: dict[str, int] = {}
    for line in (read(path) or "").splitlines():
        name, _, value = line.partition(":")
        number, _, unit = value.strip().partition(" ")
        if unit == "kB" and number.isdigit():
            fields[name] = int(number) * 1024
    return fields


# Process and container


def memory_limit() -> int | None:
    """The tightest cgroup v2 memory limit on this process, if it has one."""
    root = SYS / "fs/cgroup"
    own = next(
        (
            line.removeprefix("0::/")
            for line in (read(PROC / "self/cgroup") or "").splitlines()
            if line.startswith("0::/")
        ),
        "",
    )
    # A path outside our cgroup namespace shows up with '..'; start at its root
    path = root if ".." in own else root / own
    limits: list[int] = []
    while True:
        value = (read(path / "memory.max") or "").strip()
        if value.isdigit():
            limits.append(int(value))
        if path == root:
            return min(limits, default=None)
        path = path.parent


def container_engine() -> str | None:
    """'podman' (or whatever the engine says) when running in a container."""
    # Lowercase by convention; podman sets it in every container
    engine = os.environ.get("container")  # noqa: SIM112
    return engine or ("podman" if CONTAINERENV.exists() else None)


def count_entries(path: Path) -> int | None:
    try:
        return sum(1 for _ in path.iterdir())
    except OSError:
        return None


def thread_count() -> int | None:
    return count_entries(PROC / "self/task")


def open_files() -> int | None:
    return count_entries(PROC / "self/fd")


def local_ip(family: socket.AddressFamily) -> str | None:
    """The address this container reaches the internet from, in this family."""
    try:
        with socket.socket(family, socket.SOCK_DGRAM) as udp:
            udp.connect((ROUTE_PROBES[family], 53))  # picks a route; sends nothing
            return str(udp.getsockname()[0])
    except OSError:
        return None


def nameservers() -> list[str]:
    return [
        line.split()[1]
        for line in (read(RESOLV_CONF) or "").splitlines()
        if line.startswith("nameserver") and len(line.split()) > 1
    ]


# Host


def cpuinfo() -> dict[str, str]:
    """The fields of /proc/cpuinfo, as given for the first CPU."""
    fields: dict[str, str] = {}
    for line in (read(PROC / "cpuinfo") or "").splitlines():
        name, sep, value = line.partition(":")
        if sep:
            fields.setdefault(name.strip(), value.strip())
    return fields


def cpu_model() -> str | None:
    return cpuinfo().get("model name")


def hardware_model() -> str | None:
    """E.g. 'Dell Inc. OptiPlex 7050' or 'QEMU Standard PC (Q35 + ICH9, 2009)'."""
    dmi = SYS / "class/dmi/id"

    def value(name: str) -> str:
        text = (read(dmi / name) or "").strip()
        return "" if text.lower() in NO_VALUE else text

    vendor, product = value("sys_vendor"), value("product_name")
    if not product:
        vendor, product = value("board_vendor"), value("board_name")
    if not product:
        return cpuinfo().get("Model")  # Raspberry Pi and other boards
    return product if product.startswith(vendor) else f"{vendor} {product}".strip()


def is_virtual_machine() -> bool:
    return "hypervisor" in cpuinfo().get("flags", "").split()


def uptime() -> timedelta | None:
    text = read(PROC / "uptime")
    return timedelta(seconds=float(text.split()[0])) if text else None


def host_threads() -> int | None:
    """All threads on the host, from /proc/loadavg ('0.52 0.58 0.59 2/834 1234')."""
    fields = (read(PROC / "loadavg") or "").split()
    total = fields[3].partition("/")[2] if len(fields) > 3 else ""
    return int(total) if total.isdigit() else None


def pressure() -> dict[str, float]:
    """Share of the last minute some tasks waited for cpu, memory and io, in %."""
    found: dict[str, float] = {}
    for resource in ("cpu", "memory", "io"):
        some = (read(PROC / "pressure" / resource) or "").partition("\n")[0]
        for field in some.split()[1:]:
            name, _, value = field.partition("=")
            if name == "avg60":
                found[resource] = float(value)
    return found


def temperatures() -> dict[str, list[float]]:
    """°C of the sensors in SENSORS, by part, e.g. {'CPU': [41.4], 'NVMe': [32.9]}."""
    found: dict[str, list[float]] = {}
    for hwmon in sorted((SYS / "class/hwmon").glob("hwmon*")):
        driver = (read(hwmon / "name") or "").strip()
        if driver not in SENSORS:
            continue
        part, label = SENSORS[driver]
        for reading in sorted(hwmon.glob("temp*_input")):
            label_path = reading.with_name(reading.name.replace("_input", "_label"))
            if label is not None and (read(label_path) or "").strip() != label:
                continue
            value = (read(reading) or "").strip()
            if value.lstrip("-").isdigit():
                found.setdefault(part, []).append(int(value) / 1000)
            break
    return found


class Timex(ctypes.Structure):
    """struct timex from <sys/timex.h>, up to the fields read here."""

    _fields_ = (
        ("modes", ctypes.c_uint),
        ("offset", ctypes.c_long),
        ("freq", ctypes.c_long),
        ("maxerror", ctypes.c_long),
        ("esterror", ctypes.c_long),
        ("status", ctypes.c_int),
        ("rest", ctypes.c_byte * 512),  # more than the remaining fields need
    )


def clock_sync() -> tuple[bool, float] | None:
    """Whether NTP has synchronized the clock, and its maximum error in seconds.

    adjtimex() with no modes set only reads, so it needs no privileges.
    """
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        timex = Timex()
        state: int = libc.adjtimex(ctypes.byref(timex))
    except OSError, AttributeError:
        return None
    if state < 0:
        return None
    return state != TIME_ERROR, timex.maxerror / 1_000_000
