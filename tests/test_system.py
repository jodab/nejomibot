from datetime import timedelta
from pathlib import Path

import pytest
from helpers import write

from nejomibot import system


def test_proc_fields(tmp_path: Path) -> None:
    write(tmp_path, "status", "Name:\tpython\nVmHWM:\t  2048 kB\nVmRSS: 1024 kB\n")
    assert system.proc_fields(tmp_path / "status") == {
        "VmHWM": 2 * 1024**2,
        "VmRSS": 1024**2,
    }


def test_proc_fields_missing_file(tmp_path: Path) -> None:
    assert system.proc_fields(tmp_path / "missing") == {}


def set_cgroup(root: Path, own: str, limits: dict[str, str]) -> None:
    write(root, "proc/self/cgroup", f"0::/{own}\n")
    (root / "sys/fs/cgroup" / own).mkdir(parents=True, exist_ok=True)
    for path, limit in limits.items():
        write(root, str(Path("sys/fs/cgroup", path, "memory.max")), limit)


def test_memory_limit_is_the_tightest(fake_system: Path) -> None:
    set_cgroup(
        fake_system,
        "system.slice/bot.service/container",
        {"system.slice": "max", "system.slice/bot.service": "500", "": "900"},
    )
    assert system.memory_limit() == 500


def test_memory_limit_in_own_namespace(fake_system: Path) -> None:
    set_cgroup(fake_system, "", {"": "536870912\n"})
    assert system.memory_limit() == 536870912


def test_memory_limit_outside_namespace(fake_system: Path) -> None:
    write(fake_system, "proc/self/cgroup", "0::/../libpod-abc.scope\n")
    write(fake_system, "sys/fs/cgroup/memory.max", "300")
    assert system.memory_limit() == 300


def test_memory_limit_unlimited(fake_system: Path) -> None:
    set_cgroup(fake_system, "user.slice", {"user.slice": "max"})
    assert system.memory_limit() is None


def test_hardware_model(fake_system: Path) -> None:
    write(fake_system, "sys/class/dmi/id/sys_vendor", "Dell Inc.\n")
    write(fake_system, "sys/class/dmi/id/product_name", "OptiPlex 7050\n")
    assert system.hardware_model() == "Dell Inc. OptiPlex 7050"


def test_hardware_model_falls_back_to_board(fake_system: Path) -> None:
    write(fake_system, "sys/class/dmi/id/sys_vendor", "System manufacturer\n")
    write(fake_system, "sys/class/dmi/id/product_name", "To Be Filled By O.E.M.\n")
    write(fake_system, "sys/class/dmi/id/board_vendor", "ASRock\n")
    write(fake_system, "sys/class/dmi/id/board_name", "J4105-ITX\n")
    assert system.hardware_model() == "ASRock J4105-ITX"


def test_hardware_model_of_a_board_without_dmi(fake_system: Path) -> None:
    write(
        fake_system,
        "proc/cpuinfo",
        "processor\t: 0\nBogoMIPS\t: 108.00\n\nModel\t\t: Raspberry Pi 4 Model B\n",
    )
    assert system.hardware_model() == "Raspberry Pi 4 Model B"
    assert system.cpu_model() is None


def test_cpuinfo_uses_first_cpu(fake_system: Path) -> None:
    write(
        fake_system,
        "proc/cpuinfo",
        "processor\t: 0\nmodel name\t: AMD Ryzen 9 5950X\nflags\t\t: fpu hypervisor\n"
        "\nprocessor\t: 1\nmodel name\t: other\nflags\t\t: fpu\n",
    )
    assert system.cpu_model() == "AMD Ryzen 9 5950X"
    assert system.is_virtual_machine()


def test_uptime_and_threads(fake_system: Path) -> None:
    write(fake_system, "proc/uptime", "266400.52 8000000.00\n")
    write(fake_system, "proc/loadavg", "1.02 1.26 1.16 2/834 327854\n")
    assert system.uptime() == timedelta(days=3, hours=2, seconds=0.52)
    assert system.host_threads() == 834


def test_pressure(fake_system: Path) -> None:
    write(
        fake_system,
        "proc/pressure/io",
        "some avg10=0.79 avg60=0.83 avg300=0.94 total=2118853456\n"
        "full avg10=0.79 avg60=0.82 avg300=0.91 total=2066690554\n",
    )
    assert system.pressure() == {"io": 0.83}


def add_sensor(root: Path, hwmon: str, driver: str, readings: dict[str, str]) -> None:
    write(root, f"sys/class/hwmon/{hwmon}/name", f"{driver}\n")
    for n, (label, millidegrees) in enumerate(readings.items(), start=1):
        if label:
            write(root, f"sys/class/hwmon/{hwmon}/temp{n}_label", f"{label}\n")
        write(root, f"sys/class/hwmon/{hwmon}/temp{n}_input", f"{millidegrees}\n")


def test_temperatures(fake_system: Path) -> None:
    add_sensor(
        fake_system, "hwmon0", "nvme", {"Composite": "31850", "Sensor 2": "48850"}
    )
    add_sensor(fake_system, "hwmon1", "nvme", {"Composite": "49850"})
    add_sensor(fake_system, "hwmon2", "k10temp", {"Tccd1": "39000", "Tctl": "40625"})
    add_sensor(fake_system, "hwmon3", "it8628", {"": "-128000"})
    assert system.temperatures() == {"NVMe": [31.85, 49.85], "CPU": [40.625]}


def test_temperatures_without_labels(fake_system: Path) -> None:
    add_sensor(fake_system, "hwmon0", "cpu_thermal", {"": "52582"})
    assert system.temperatures() == {"CPU": [52.582]}


def test_nameservers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, "resolv.conf", "search lan\nnameserver 10.89.0.1\nnameserver ::1\n")
    monkeypatch.setattr(system, "RESOLV_CONF", tmp_path / "resolv.conf")
    assert system.nameservers() == ["10.89.0.1", "::1"]


def test_clock_sync_reads_the_real_clock() -> None:
    sync = system.clock_sync()
    assert sync is None or (isinstance(sync[0], bool) and sync[1] >= 0)
