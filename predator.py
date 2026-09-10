#!/usr/bin/env python3
"""
Predator Control - User-space frontend for Acer Predator PHN16-71
Requires: linuwu_sense kernel driver
"""

import argparse
import enum
import logging
import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Constants ──────────────────────────────────────────────────────────

DRIVER_BASE = Path("/sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi")
PREDATOR_SENSE = DRIVER_BASE / "predator_sense"
FOUR_ZONED_KB = DRIVER_BASE / "four_zoned_kb"
HWMON_BASE = DRIVER_BASE / "hwmon"
PLATFORM_PROFILE = Path("/sys/firmware/acpi/platform_profile")
PLATFORM_PROFILE_CHOICES = Path("/sys/firmware/acpi/platform_profile_choices")
BATTERY_CAPACITY = Path("/sys/class/power_supply/BAT1/capacity")
BATTERY_STATUS = Path("/sys/class/power_supply/BAT1/status")

FAN_SPEED = PREDATOR_SENSE / "fan_speed"
BATTERY_LIMITER = PREDATOR_SENSE / "battery_limiter"
BATTERY_CALIBRATION = PREDATOR_SENSE / "battery_calibration"
BOOT_ANIM_SOUND = PREDATOR_SENSE / "boot_animation_sound"
LCD_OVERRIDE = PREDATOR_SENSE / "lcd_override"
USB_CHARGING = PREDATOR_SENSE / "usb_charging"
BACKLIGHT_TIMEOUT = PREDATOR_SENSE / "backlight_timeout"
DRIVER_VERSION = PREDATOR_SENSE / "version"

FOUR_ZONE_MODE = FOUR_ZONED_KB / "four_zone_mode"
PER_ZONE_MODE = FOUR_ZONED_KB / "per_zone_mode"

DEBUG = os.environ.get("PREDATOR_DEBUG", "0") == "1"
logger = logging.getLogger("predator")

APP_ROOT = Path(__file__).resolve().parent

# ── Enums ──────────────────────────────────────────────────────────────

KB_EFFECTS = {
    0: "Static",
    1: "Breathing",
    2: "Neon",
    3: "Wave",
    4: "Shifting",
    5: "Zoom",
    6: "Meteor",
    7: "Twinkling",
}

KB_EFFECTS_BY_NAME = {v.lower(): k for k, v in KB_EFFECTS.items()}

PROFILE_MAP = {
    "quiet": "quiet",
    "bal": "balanced",
    "balanced": "balanced",
    "perf": "performance",
    "performance": "performance",
    "balanced-performance": "balanced-performance",
    "low-power": "low-power",
    "turbo": "performance",
}

PROFILE_SHORT_NAMES = {
    "low-power": "eco",
    "quiet": "quiet",
    "balanced": "balanced",
    "balanced-performance": "performance",
    "performance": "turbo",
}

USB_CHARGING_VALUES = {0: "Off", 10: "10%", 20: "20%", 30: "30%"}


# ── Dataclasses ────────────────────────────────────────────────────────

@dataclass
class FanState:
    cpu: int = 0
    gpu: int = 0
    available: bool = True

    @property
    def is_auto(self) -> bool:
        return self.available and self.cpu == 0 and self.gpu == 0

    @property
    def is_max(self) -> bool:
        return self.available and self.cpu == 100 and self.gpu == 100

    def __str__(self) -> str:
        if not self.available:
            return "N/A"
        if self.is_auto:
            return "Auto"
        if self.is_max:
            return "Max"
        return f"CPU={self.cpu}% GPU={self.gpu}%"


@dataclass
class ProfileState:
    current: str = "balanced"
    choices: list = field(default_factory=list)

    @property
    def short_name(self) -> str:
        return PROFILE_SHORT_NAMES.get(self.current, self.current)


@dataclass
class BatteryState:
    capacity: int = 0
    limiter_enabled: bool = False
    calibration_enabled: bool = False
    status: str = "Unknown"


@dataclass
class ZoneColor:
    zone1: str = "000000"
    zone2: str = "000000"
    zone3: str = "000000"
    zone4: str = "000000"
    brightness: int = 100

    def as_list(self) -> list:
        return [self.zone1, self.zone2, self.zone3, self.zone4]


@dataclass
class KeyboardState:
    mode: int = 0
    speed: int = 0
    brightness: int = 100
    direction: int = 0
    red: int = 0
    green: int = 0
    blue: int = 0
    per_zone: ZoneColor = field(default_factory=ZoneColor)
    available: bool = True

    @property
    def effect_name(self) -> str:
        return KB_EFFECTS.get(self.mode, f"Unknown({self.mode})")

    @property
    def hex_color(self) -> str:
        return f"{self.red:02x}{self.green:02x}{self.blue:02x}"


@dataclass
class Telemetry:
    fan1_rpm: int = 0
    fan2_rpm: int = 0
    temp1: int = 0
    temp2: int = 0
    temp3: int = 0
    fan1_label: str = "CPU fan"
    fan2_label: str = "GPU fan"
    temp1_label: str = "Temp 1"
    temp2_label: str = "Temp 2"
    temp3_label: str = "Temp 3"


@dataclass
class SystemStatus:
    fan: FanState = field(default_factory=FanState)
    profile: ProfileState = field(default_factory=ProfileState)
    battery: BatteryState = field(default_factory=BatteryState)
    keyboard: KeyboardState = field(default_factory=KeyboardState)
    telemetry: Telemetry = field(default_factory=Telemetry)
    driver_version: str = "N/A"


# ── Sysfs Abstraction ─────────────────────────────────────────────────

def read_sysfs(path: Path) -> Optional[str]:
    """Read a sysfs file. Returns None on error (silent unless debug)."""
    try:
        val = path.read_text().strip()
        if DEBUG:
            logger.debug("read %s = %s", path, val)
        return val
    except PermissionError:
        if DEBUG:
            logger.error("Permission denied: %s", path)
        return None
    except FileNotFoundError:
        if DEBUG:
            logger.error("File not found: %s", path)
        return None
    except OSError as e:
        if DEBUG:
            logger.error("OS error reading %s: %s", path, e)
        return None


def write_sysfs(path: Path, value: str) -> bool:
    """Write to a sysfs file. Returns True on success."""
    if not path.exists():
        print_error(f"Path not found: {path}")
        return False
    try:
        if DEBUG:
            logger.debug("write %s = %s", path, value)
        path.write_text(value)
        return True
    except PermissionError:
        print_error(f"Permission denied writing {path}. Are you in the linuwu_sense group?")
        return False
    except OSError as e:
        print_error(f"Error writing {path}: {e}")
        return False


def exists_sysfs(path: Path) -> bool:
    return path.exists()


def find_hwmon() -> Optional[Path]:
    """Find the linuwu_sense hwmon directory."""
    if not HWMON_BASE.exists():
        return None
    for entry in sorted(HWMON_BASE.iterdir()):
        if entry.name.startswith("hwmon") and entry.is_dir():
            name_file = entry / "name"
            if name_file.exists():
                name = read_sysfs(name_file)
                if name and "acer" in name.lower():
                    return entry
    return None


# ── Controllers ────────────────────────────────────────────────────────

class FanController:
    @staticmethod
    def get_state() -> FanState:
        val = read_sysfs(FAN_SPEED)
        if val is None:
            return FanState(available=False)
        try:
            parts = val.split(",")
            return FanState(cpu=int(parts[0]), gpu=int(parts[1]))
        except (ValueError, IndexError):
            return FanState(available=False)

    @staticmethod
    def set_fans(cpu: int, gpu: int) -> tuple[bool, FanState]:
        if not write_sysfs(FAN_SPEED, f"{cpu},{gpu}"):
            return False, FanState()
        actual = FanController.get_state()
        return actual.cpu == cpu and actual.gpu == gpu, actual

    @staticmethod
    def set_auto() -> tuple[bool, FanState]:
        return FanController.set_fans(0, 0)

    @staticmethod
    def set_max() -> tuple[bool, FanState]:
        return FanController.set_fans(100, 100)


class ProfileController:
    @staticmethod
    def get_choices() -> list:
        val = read_sysfs(PLATFORM_PROFILE_CHOICES)
        if val is None:
            return []
        return val.split()

    @staticmethod
    def get_state() -> ProfileState:
        current = read_sysfs(PLATFORM_PROFILE) or "unknown"
        choices = ProfileController.get_choices()
        return ProfileState(current=current, choices=choices)

    @staticmethod
    def set_profile(name: str) -> tuple[bool, ProfileState]:
        target = PROFILE_MAP.get(name.lower())
        if target is None:
            return False, ProfileState()
        if not write_sysfs(PLATFORM_PROFILE, target):
            return False, ProfileState()
        actual = ProfileController.get_state()
        return actual.current == target, actual


class BatteryController:
    @staticmethod
    def get_state() -> BatteryState:
        state = BatteryState()
        cap = read_sysfs(BATTERY_CAPACITY)
        if cap is not None:
            try:
                state.capacity = int(cap)
            except ValueError:
                pass
        limiter = read_sysfs(BATTERY_LIMITER)
        if limiter is not None:
            state.limiter_enabled = limiter.strip() == "1"
        cal = read_sysfs(BATTERY_CALIBRATION)
        if cal is not None:
            state.calibration_enabled = cal.strip() == "1"
        status_val = read_sysfs(BATTERY_STATUS)
        if status_val is not None:
            state.status = status_val
        return state

    @staticmethod
    def set_limiter(enabled: bool) -> tuple[bool, BatteryState]:
        val = "1" if enabled else "0"
        if not write_sysfs(BATTERY_LIMITER, val):
            return False, BatteryController.get_state()
        actual = BatteryController.get_state()
        return actual.limiter_enabled == enabled, actual

    @staticmethod
    def set_calibration(enabled: bool) -> tuple[bool, BatteryState]:
        val = "1" if enabled else "0"
        if not write_sysfs(BATTERY_CALIBRATION, val):
            return False, BatteryController.get_state()
        actual = BatteryController.get_state()
        return actual.calibration_enabled == enabled, actual


class KeyboardController:
    @staticmethod
    def get_state() -> KeyboardState:
        state = KeyboardState(available=False)
        val = read_sysfs(FOUR_ZONE_MODE)
        if val is not None:
            state.available = True
            try:
                parts = val.split(",")
                state.mode = int(parts[0])
                state.speed = int(parts[1])
                state.brightness = int(parts[2])
                state.direction = int(parts[3])
                state.red = int(parts[4])
                state.green = int(parts[5])
                state.blue = int(parts[6])
            except (ValueError, IndexError):
                state.available = False
        pz = read_sysfs(PER_ZONE_MODE)
        if pz is not None:
            try:
                parts = pz.split(",")
                state.per_zone = ZoneColor(
                    zone1=parts[0],
                    zone2=parts[1],
                    zone3=parts[2],
                    zone4=parts[3],
                    brightness=int(parts[4]),
                )
            except (ValueError, IndexError):
                pass
        return state

    @staticmethod
    def set_four_zone_mode(
        mode: int, speed: int, brightness: int, direction: int,
        red: int, green: int, blue: int,
    ) -> bool:
        val = f"{mode},{speed},{brightness},{direction},{red},{green},{blue}"
        return write_sysfs(FOUR_ZONE_MODE, val)

    @staticmethod
    def set_per_zone(
        zone1: str, zone2: str, zone3: str, zone4: str, brightness: int,
    ) -> bool:
        val = f"{zone1},{zone2},{zone3},{zone4},{brightness}"
        return write_sysfs(PER_ZONE_MODE, val)

    @staticmethod
    def set_global_effect(effect_name: str, speed: int, brightness: int,
                          direction: int, color_hex: str) -> tuple[bool, KeyboardState]:
        mode = KB_EFFECTS_BY_NAME.get(effect_name.lower())
        if mode is None:
            return False, KeyboardController.get_state()
        try:
            r = int(color_hex[0:2], 16)
            g = int(color_hex[2:4], 16)
            b = int(color_hex[4:6], 16)
        except (ValueError, IndexError):
            return False, KeyboardController.get_state()
        ok = KeyboardController.set_four_zone_mode(mode, speed, brightness, direction, r, g, b)
        return ok, KeyboardController.get_state()

    @staticmethod
    def set_zone_colors(
        z1: str, z2: str, z3: str, z4: str, brightness: int,
    ) -> tuple[bool, KeyboardState]:
        ok = KeyboardController.set_per_zone(z1, z2, z3, z4, brightness)
        return ok, KeyboardController.get_state()


class TelemetryReader:
    @staticmethod
    def get_state() -> Telemetry:
        t = Telemetry()
        hwmon = find_hwmon()
        if hwmon is None:
            return t
        v = read_sysfs(hwmon / "fan1_input")
        if v is not None:
            try:
                t.fan1_rpm = int(v)
            except ValueError:
                pass
        v = read_sysfs(hwmon / "fan2_input")
        if v is not None:
            try:
                t.fan2_rpm = int(v)
            except ValueError:
                pass
        v = read_sysfs(hwmon / "temp1_input")
        if v is not None:
            try:
                t.temp1 = int(v) // 1000
            except ValueError:
                pass
        v = read_sysfs(hwmon / "temp2_input")
        if v is not None:
            try:
                t.temp2 = int(v) // 1000
            except ValueError:
                pass
        v = read_sysfs(hwmon / "temp3_input")
        if v is not None:
            try:
                t.temp3 = int(v) // 1000
            except ValueError:
                pass
        lbl = read_sysfs(hwmon / "temp1_label")
        if lbl:
            t.temp1_label = lbl
        lbl = read_sysfs(hwmon / "temp2_label")
        if lbl:
            t.temp2_label = lbl
        lbl = read_sysfs(hwmon / "temp3_label")
        if lbl:
            t.temp3_label = lbl
        lbl = read_sysfs(hwmon / "fan1_label")
        if lbl:
            t.fan1_label = lbl
        lbl = read_sysfs(hwmon / "fan2_label")
        if lbl:
            t.fan2_label = lbl
        return t


class StatusReader:
    @staticmethod
    def get_full() -> SystemStatus:
        s = SystemStatus()
        s.fan = FanController.get_state()
        s.profile = ProfileController.get_state()
        s.battery = BatteryController.get_state()
        s.keyboard = KeyboardController.get_state()
        s.telemetry = TelemetryReader.get_state()
        v = read_sysfs(DRIVER_VERSION)
        if v:
            s.driver_version = v
        return s


# ── Validation ─────────────────────────────────────────────────────────

def validate_fan_percent(value: str, label: str) -> int:
    """Validate and return a fan percentage 0-100."""
    try:
        val = int(value)
    except ValueError:
        print_error(f"{label} must be an integer between 0 and 100, got '{value}'")
        raise SystemExit(1)
    if val < 0 or val > 100:
        print_error(f"{label} must be between 0 and 100, got {val}")
        raise SystemExit(1)
    return val


def validate_color_hex(value: str) -> str:
    """Validate a 6-digit hex color."""
    v = value.strip().lower().lstrip("#")
    if len(v) != 6:
        print_error(f"Color must be 6 hex digits, got '{value}'")
        raise SystemExit(1)
    try:
        int(v, 16)
    except ValueError:
        print_error(f"Color must be valid hexadecimal, got '{value}'")
        raise SystemExit(1)
    return v


def validate_brightness(value: str) -> int:
    """Validate brightness 0-100."""
    try:
        val = int(value)
    except ValueError:
        print_error(f"Brightness must be an integer between 0 and 100, got '{value}'")
        raise SystemExit(1)
    if val < 0 or val > 100:
        print_error(f"Brightness must be between 0 and 100, got {val}")
        raise SystemExit(1)
    return val


def validate_speed(value: str) -> int:
    """Validate effect speed 0-9."""
    try:
        val = int(value)
    except ValueError:
        print_error(f"Speed must be an integer between 0 and 9, got '{value}'")
        raise SystemExit(1)
    if val < 0 or val > 9:
        print_error(f"Speed must be between 0 and 9, got {val}")
        raise SystemExit(1)
    return val


def validate_direction(value: str) -> int:
    """Validate direction 0-2."""
    try:
        val = int(value)
    except ValueError:
        print_error(f"Direction must be an integer between 0 and 2, got '{value}'")
        raise SystemExit(1)
    if val < 0 or val > 2:
        print_error(f"Direction must be between 0 and 2, got {val}")
        raise SystemExit(1)
    return val


def validate_battery_limit(value: str) -> int:
    """Validate battery limit. Returns 0 (off) or 1 (on)."""
    try:
        val = int(value)
    except ValueError:
        print_error(f"Battery limit must be an integer, got '{value}'")
        raise SystemExit(1)
    if val < 0 or val > 100:
        print_error(f"Battery limit must be between 0 and 100, got {val}")
        raise SystemExit(1)
    if val == 100 or val == 0:
        return 0
    return 1


# ── Driver Check ───────────────────────────────────────────────────────

def check_driver() -> bool:
    if not DRIVER_BASE.exists():
        return False
    if not PREDATOR_SENSE.exists():
        return False
    return True


def check_permissions() -> bool:
    test_file = FAN_SPEED
    if not test_file.exists():
        return False
    try:
        test_file.read_text()
        return True
    except PermissionError:
        return False


# ── CLI Output ─────────────────────────────────────────────────────────

def print_error(msg: str):
    print(f"Error: {msg}", file=sys.stderr)


def print_fans_help():
    print(textwrap.dedent("""\
        Usage: predator fans <command>

        Commands:
          status          Show current fan speeds
          auto            Set fans to automatic control
          max             Set fans to maximum speed
          <percentage>    Set both fans to the same percentage
          <cpu> <gpu>     Set CPU and GPU fans separately
          help            Show this help

        Examples:
          predator fans status
          predator fans auto
          predator fans max
          predator fans 50
          predator fans 50 70

        Values must be integers between 0 and 100.
    """))


def print_profile_help():
    print(textwrap.dedent("""\
        Usage: predator profile <command>

        Commands:
          status          Show current thermal profile
          quiet           Set quiet/eco profile
          bal             Set balanced profile
          perf            Set performance profile
          turbo           Set turbo/performance profile
          help            Show this help

        The available profiles depend on your hardware and
        power state. Some profiles may only be available on AC power.
    """))


def print_turbo_help():
    print(textwrap.dedent("""\
        Usage: predator turbo <command>

        Commands:
          status          Show turbo mode status
          on              Enable turbo mode
          off             Disable turbo mode
          help            Show this help

        Note: This controls the thermal profile via platform_profile.
        The hardware turbo button additionally controls overclocking
        settings that cannot be modified from userspace.
    """))


def print_battery_help():
    print(textwrap.dedent("""\
        Usage: predator battery <command>

        Commands:
          status              Show battery status
          limit <value>       Enable or disable battery limiter
          calibration <value> Enable or disable battery calibration
          help                Show this help

        Battery limiter:
          0-99 or off   Disable battery limit
          100 or on     Enable battery limit (caps at 80%)

        Battery calibration:
          on            Start calibration
          off           Stop calibration
    """))


def print_keyboard_help():
    print(textwrap.dedent("""\
        Usage: predator keyboard <command>

        Commands:
          status      Show current keyboard RGB state
          (no args)   Launch the keyboard RGB GUI
          help        Show this help

        The GUI provides zone-based RGB control with:
          - 4 independent color zones
          - Effect selection (Static, Breathing, Neon, etc.)
          - Brightness and speed control
          - Color picker

        The GUI does not require root privileges.
    """))


# ── CLI Commands ───────────────────────────────────────────────────────

def cmd_fans(args):
    if not check_driver():
        print_error("Linuwu-Sense driver not loaded.")
        raise SystemExit(1)

    if not args or args[0] == "help":
        print_fans_help()
        return

    subcmd = args[0].lower()

    if subcmd == "status":
        state = FanController.get_state()
        if not state.available:
            print("Fan mode:  N/A (unable to read fan state)")
            print("CPU fan:   N/A")
            print("GPU fan:   N/A")
            return
        print(f"Fan mode:  {state}")
        print(f"CPU fan:   {state.cpu}%")
        print(f"GPU fan:   {state.gpu}%")
        return

    if subcmd == "auto":
        ok, state = FanController.set_auto()
        if ok:
            print("Fans set to automatic.")
        else:
            print_error("Failed to set fans to auto.")
            raise SystemExit(1)
        return

    if subcmd == "max":
        ok, state = FanController.set_max()
        if ok:
            print("Fans set to maximum.")
        else:
            print_error("Failed to set fans to max.")
            raise SystemExit(1)
        return

    if len(args) == 1:
        cpu = validate_fan_percent(args[0], "Fan percentage")
        gpu = cpu
    elif len(args) == 2:
        cpu = validate_fan_percent(args[0], "CPU fan percentage")
        gpu = validate_fan_percent(args[1], "GPU fan percentage")
    else:
        print_error("Too many arguments.")
        print_fans_help()
        raise SystemExit(1)

    ok, state = FanController.set_fans(cpu, gpu)
    if ok:
        print(f"Fans set: CPU={state.cpu}% GPU={state.gpu}%")
    else:
        print_error("Failed to set fan speeds.")
        raise SystemExit(1)


def cmd_profile(args):
    if not check_driver():
        print_error("Linuwu-Sense driver not loaded.")
        raise SystemExit(1)

    if not args or args[0] == "help":
        print_profile_help()
        return

    subcmd = args[0].lower()

    if subcmd == "status":
        state = ProfileController.get_state()
        print(f"Profile:    {state.short_name} ({state.current})")
        print(f"Available:  {', '.join(state.choices)}")
        return

    ok, state = ProfileController.set_profile(subcmd)
    if ok:
        print(f"Profile set: {state.short_name} ({state.current})")
    else:
        choices = ProfileController.get_choices()
        print_error(f"Failed to set profile '{subcmd}'.")
        if choices:
            print(f"Available profiles: {', '.join(choices)}")
        raise SystemExit(1)


def cmd_turbo(args):
    if not check_driver():
        print_error("Linuwu-Sense driver not loaded.")
        raise SystemExit(1)

    if not args or args[0] == "help":
        print_turbo_help()
        return

    subcmd = args[0].lower()

    if subcmd == "status":
        state = ProfileController.get_state()
        is_turbo = state.current == "performance"
        print(f"Turbo:      {'On' if is_turbo else 'Off'}")
        print(f"Profile:    {state.current}")
        return

    if subcmd == "on":
        ok, state = ProfileController.set_profile("performance")
        if ok:
            print("Turbo enabled (profile: performance).")
        else:
            print_error("Failed to enable turbo.")
            raise SystemExit(1)
        return

    if subcmd == "off":
        ok, state = ProfileController.set_profile("balanced")
        if ok:
            print("Turbo disabled (profile: balanced).")
        else:
            print_error("Failed to disable turbo.")
            raise SystemExit(1)
        return

    print_error(f"Unknown turbo command: '{subcmd}'")
    print_turbo_help()
    raise SystemExit(1)


def cmd_battery(args):
    if not check_driver():
        print_error("Linuwu-Sense driver not loaded.")
        raise SystemExit(1)

    if not args or args[0] == "help":
        print_battery_help()
        return

    subcmd = args[0].lower()

    if subcmd == "status":
        state = BatteryController.get_state()
        print(f"Battery:      {state.capacity}%")
        print(f"Status:       {state.status}")
        print(f"Limiter:      {'Enabled' if state.limiter_enabled else 'Disabled'}")
        print(f"Calibration:  {'Active' if state.calibration_enabled else 'Inactive'}")
        return

    if subcmd == "limit":
        if len(args) < 2:
            print_error("Missing value. Use 'on', 'off', or a percentage.")
            raise SystemExit(1)
        val = args[1].lower()
        if val in ("on", "enable", "1", "80"):
            enabled = True
        elif val in ("off", "disable", "0", "100"):
            enabled = False
        else:
            enabled = validate_battery_limit(args[1]) == 1
        ok, state = BatteryController.set_limiter(enabled)
        if ok:
            status = "Enabled" if state.limiter_enabled else "Disabled"
            print(f"Battery limiter: {status}")
        else:
            print_error("Failed to set battery limiter.")
            raise SystemExit(1)
        return

    if subcmd == "calibration":
        if len(args) < 2:
            print_error("Missing value. Use 'on' or 'off'.")
            raise SystemExit(1)
        val = args[1].lower()
        if val in ("on", "enable", "1"):
            enabled = True
        elif val in ("off", "disable", "0"):
            enabled = False
        else:
            print_error(f"Invalid calibration value: '{val}'. Use 'on' or 'off'.")
            raise SystemExit(1)
        ok, state = BatteryController.set_calibration(enabled)
        if ok:
            status = "Active" if state.calibration_enabled else "Inactive"
            print(f"Battery calibration: {status}")
        else:
            print_error("Failed to set battery calibration.")
            raise SystemExit(1)
        return

    print_error(f"Unknown battery command: '{subcmd}'")
    print_battery_help()
    raise SystemExit(1)


def cmd_keyboard(args):
    if not check_driver():
        print_error("Linuwu-Sense driver not loaded.")
        raise SystemExit(1)

    if args and args[0] == "--selftest-qml":
        launch_gui(selftest=True)
        return

    if args and args[0] == "--apply-mode":
        try:
            vals = [int(v) for v in args[1:8]]
        except ValueError:
            print_error("Invalid values for --apply-mode.")
            raise SystemExit(1)
        if len(vals) != 7:
            print_error("--apply-mode requires 7 values: mode speed brightness direction r g b")
            raise SystemExit(1)
        ok = KeyboardController.set_four_zone_mode(*vals)
        raise SystemExit(0 if ok else 1)

    if args and args[0] == "--apply-zones":
        vals = args[1:6]
        if len(vals) != 5:
            print_error("--apply-zones requires 5 values: c1 c2 c3 c4 brightness")
            raise SystemExit(1)
        try:
            brightness = int(vals[4])
        except ValueError:
            print_error(f"Invalid brightness: {vals[4]}")
            raise SystemExit(1)
        ok = KeyboardController.set_per_zone(vals[0], vals[1], vals[2], vals[3], brightness)
        raise SystemExit(0 if ok else 1)

    if args and args[0] == "help":
        print_keyboard_help()
        return

    if args and args[0] == "status":
        state = KeyboardController.get_state()
        if not state.available:
            print("Keyboard RGB: N/A (unable to read state)")
            print("Check that you are in the linuwu_sense group.")
            return
        print(f"Effect:     {state.effect_name}")
        print(f"Speed:      {state.speed}")
        print(f"Brightness: {state.brightness}%")
        print(f"Direction:  {state.direction}")
        print(f"Color:      #{state.hex_color}")
        print()
        print("Per-zone colors:")
        for i, c in enumerate(state.per_zone.as_list(), 1):
            print(f"  Zone {i}:   #{c}")
        print(f"  Brightness: {state.per_zone.brightness}%")
        return

    launch_gui()


def cmd_temps(args):
    if not check_driver():
        print_error("Linuwu-Sense driver not loaded.")
        raise SystemExit(1)

    t = TelemetryReader.get_state()
    print(f"{t.temp1_label}:  {t.temp1}°C")
    print(f"{t.temp2_label}:  {t.temp2}°C")
    print(f"{t.temp3_label}:  {t.temp3}°C")
    print()
    print(f"{t.fan1_label}:  {t.fan1_rpm} RPM")
    print(f"{t.fan2_label}:  {t.fan2_rpm} RPM")


def cmd_status(args):
    if not check_driver():
        print_error("Linuwu-Sense driver not loaded.")
        raise SystemExit(1)

    s = StatusReader.get_full()
    print(f"Predator PHN16-71")
    print(f"{'─' * 35}")
    print()
    print(f"Profile       {s.profile.short_name} ({s.profile.current})")
    turbo_str = "On" if s.profile.current == "performance" else "Off"
    print(f"Turbo         {turbo_str}")
    print()
    print(f"CPU           {s.telemetry.temp1}°C")
    print(f"GPU           {s.telemetry.temp2}°C")
    print()
    print(f"CPU fan       {s.telemetry.fan1_rpm} RPM")
    print(f"GPU fan       {s.telemetry.fan2_rpm} RPM")
    print()
    print(f"Fan mode      {s.fan}")
    print()
    print(f"Battery       {s.battery.capacity}%")
    limit_str = "Enabled" if s.battery.limiter_enabled else "Disabled"
    print(f"Limit         {limit_str}")
    print()
    kb_effect = s.keyboard.effect_name if s.keyboard.available else "N/A"
    kb_brightness = f"{s.keyboard.brightness}%" if s.keyboard.available else "N/A"
    print(f"Keyboard      {kb_effect}")
    print(f"Brightness    {kb_brightness}")


def cmd_selftest(args):
    if not args or args[0] != "--no-write":
        pass

    print("Predator Control self-test")
    print()

    def check(label, fn):
        try:
            result = fn()
            if result:
                print(f"  PASS  {label}")
            else:
                print(f"  FAIL  {label}")
        except Exception as e:
            print(f"  FAIL  {label}: {e}")

    def check_warn(label, fn):
        try:
            result = fn()
            if result:
                print(f"  PASS  {label}")
            else:
                print(f"  WARN  {label}")
        except Exception as e:
            print(f"  WARN  {label}: {e}")

    print("Hardware")
    check("Acer Predator PHN16-71", lambda: "Acer" in (read_sysfs(Path("/sys/class/dmi/id/sys_vendor")) or "") and "Predator" in (read_sysfs(Path("/sys/class/dmi/id/product_name")) or ""))
    print()

    print("Driver")
    check("linuwu_sense loaded", lambda: DRIVER_BASE.exists())
    check_warn("linuwu_sense.service active", lambda: "active" in os.popen("systemctl is-active linuwu_sense.service 2>/dev/null").read().strip())
    print()

    print("Fan interface")
    check("fan_speed readable", lambda: read_sysfs(FAN_SPEED) is not None)
    print()

    print("Thermal profiles")
    check("platform_profile readable", lambda: read_sysfs(PLATFORM_PROFILE) is not None)
    check("platform_profile_choices readable", lambda: read_sysfs(PLATFORM_PROFILE_CHOICES) is not None)
    print()

    print("Battery interface")
    check("battery_limiter readable", lambda: read_sysfs(BATTERY_LIMITER) is not None)
    check("battery_calibration readable", lambda: read_sysfs(BATTERY_CALIBRATION) is not None)
    print()

    print("RGB interface")
    check("four_zone_mode readable", lambda: read_sysfs(FOUR_ZONE_MODE) is not None)
    check("per_zone_mode readable", lambda: read_sysfs(PER_ZONE_MODE) is not None)
    print()

    print("Telemetry")
    hwmon = find_hwmon()
    check("hwmon device found", lambda: hwmon is not None)
    if hwmon:
        check("fan sensors", lambda: (hwmon / "fan1_input").exists())
        check("temp sensors", lambda: (hwmon / "temp1_input").exists())
    print()

    print("Permissions")
    check("sysfs access", lambda: check_permissions())


# ── GUI Launch ─────────────────────────────────────────────────────────

def launch_gui(selftest: bool = False):
    qml_dir = APP_ROOT / "qml"
    gui_main = qml_dir / "gui.py"
    if not gui_main.exists():
        print_error("GUI module not found: qml/gui.py")
        raise SystemExit(1)

    sys.path.insert(0, str(qml_dir))

    try:
        import gui
    except ImportError as e:
        print_error(f"Failed to import GUI module: {e}")
        print_error("PySide6 is required. Install with: sudo pacman -S pyside6")
        raise SystemExit(1)

    gui.main(selftest=selftest)


# ── Uninstall ──────────────────────────────────────────────────────────

# Exact paths this app owns. Removing anything else is a bug.
APP_INSTALLABLE_PATHS = [
    "/opt/predator-control",
    "/usr/local/bin/predator",
    "/usr/share/applications/predator.desktop",
    "/etc/tmpfiles.d/predator-control.conf",
    "/etc/sudoers.d/predator-control",
]

SUDOERS_FILE = Path("/etc/sudoers.d/predator-control")
_PRIV_ENV = "PREDATOR_ELEVATED"
PRIV_COMMANDS = frozenset(["fans", "profile", "turbo", "battery"])


def _needs_privilege(cmd: str, args) -> bool:
    """True when a command writes hardware state and must run as root."""
    if cmd not in PRIV_COMMANDS:
        return False
    if not args:
        return False
    return args[0] not in ("status", "help")


def _session_has_linuwu_sense_group() -> bool:
    """True when this process already has linuwu_sense among its groups
    (fresh login). No escalation is needed in that case."""
    try:
        import grp
        gid = grp.getgrnam("linuwu_sense").gr_gid
    except KeyError:
        return False
    return gid == os.getegid() or gid in os.getgroups()


def _run_elevated(args_list) -> None:
    """Re-run this command via password-less sudo (exits with its code).

    sudo re-reads /etc/group on every invocation, so members of
    linuwu_sense with a stale session (joined the group after login)
    can write immediately, with no logout or newgrp needed.
    """
    if os.geteuid() == 0:
        return
    if os.environ.get(_PRIV_ENV) == "1":
        return
    if _session_has_linuwu_sense_group():
        return
    env = dict(os.environ)
    env[_PRIV_ENV] = "1"
    script = str(APP_ROOT / "predator.py")
    try:
        probe = subprocess.run(["sudo", "-n", "-l", script],
                               capture_output=True, text=True)
        if probe.returncode != 0:
            return
        r = subprocess.run(["sudo", "-n", script, *args_list], env=env)
    except OSError:
        raise SystemExit(1)
    raise SystemExit(r.returncode)


def _uninstall_paths(paths: list[Path]) -> tuple[bool, list[str]]:
    """Remove the given paths (privileged). Returns (ok, failures)."""
    if os.geteuid() == 0:
        for p in paths:
            try:
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink(missing_ok=True)
            except OSError as e:
                return False, [f"{p}: {e}"]
        return True, []
    else:
        cmd = ["sudo", "rm", "-rf", *[str(p) for p in paths]]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            print_error("sudo is required for uninstall.")
            return False, ["sudo not found"]
        if r.returncode != 0:
            return False, [r.stderr.strip() or "sudo rm failed"]
        return True, []


def _print_uninstall_help():
    print(textwrap.dedent("""\
        Usage: predator uninstall

        Removes the Predator Control application (this app) completely.
        Will ask for confirmation, then use sudo to remove:

          /opt/predator-control
          /usr/local/bin/predator
          /usr/share/applications/predator.desktop
          /etc/tmpfiles.d/predator-control.conf

        It does NOT touch linuwu_sense, the kernel module, or the
        linuwu_sense.service.

        Options:
          predator uninstall         ask for confirmation
          predator uninstall --yes   uninstall without asking
    """))


def cmd_uninstall(args):
    if args and args[0] in ("help", "--help", "-h"):
        _print_uninstall_help()
        return

    print("Predator Control uninstall")
    print("This will remove the Predator Control application only.")
    print("The Linuwu-Sense driver and its service are left untouched.")
    print()
    for p in APP_INSTALLABLE_PATHS:
        print(f"  {p}")

    if not (args and args[0] == "--yes"):
        try:
            answer = input("\nUninstall Predator Control? [y/N] ").strip().lower()
        except EOFError:
            print()
            print("Aborted.")
            raise SystemExit(0)
        if answer not in ("y", "yes"):
            print("Aborted.")
            raise SystemExit(0)

    existing = [Path(p) for p in APP_INSTALLABLE_PATHS if Path(p).exists() or Path(p).is_symlink()]
    if not existing:
        print("Nothing installed to remove.")
        raise SystemExit(0)

    ok, failures = _uninstall_paths(existing)
    if not ok:
        for f in failures:
            print_error(f"Failed to remove: {f}")
        raise SystemExit(1)

    for p in existing:
        if not p.exists():
            print(f"  Removed: {p}")
        else:
            print(f"  Left behind: {p}")
            ok = False
    if not ok:
        raise SystemExit(1)

    print()
    print("Predator Control has been uninstalled.")
    print("Linuwu-Sense driver remains active.")


# ── Main CLI ───────────────────────────────────────────────────────────

def main():
    global DEBUG

    args_list = sys.argv[1:]

    if "--debug" in args_list:
        DEBUG = True
        logging.basicConfig(level=logging.DEBUG)
        args_list.remove("--debug")

    if DEBUG:
        logging.basicConfig(level=logging.DEBUG)

    parser = argparse.ArgumentParser(
        prog="predator",
        description="Predator Control - Acer Predator PHN16-71 hardware control",
        add_help=False,
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("help", help="Show help")
    sub.add_parser("status", help="Show complete system status")
    sub.add_parser("temps", help="Show temperature and fan telemetry")
    sub.add_parser("self-test", help="Run hardware self-test (read-only)")
    uninstall_p = sub.add_parser("uninstall", help="Uninstall Predator Control (asks for sudo)")
    uninstall_p.add_argument("args", nargs="*")
    uninstall_p.add_argument("--yes", action="store_true",
                             help="uninstall without asking for confirmation")

    fans_p = sub.add_parser("fans", help="Control CPU/GPU fans")
    fans_p.add_argument("args", nargs="*")

    profile_p = sub.add_parser("profile", help="Control thermal profile")
    profile_p.add_argument("args", nargs="*")

    turbo_p = sub.add_parser("turbo", help="Control turbo mode")
    turbo_p.add_argument("args", nargs="*")

    battery_p = sub.add_parser("battery", help="Battery controls")
    battery_p.add_argument("args", nargs="*")

    keyboard_p = sub.add_parser("keyboard", help="Keyboard RGB controls")
    keyboard_p.add_argument("--selftest-qml", action="store_true",
                            help="Verify QML loads, then exit (no window)")
    keyboard_p.add_argument("--apply-mode", nargs=7, metavar="V",
                            help="(privileged) write four-zone mode parameters")
    keyboard_p.add_argument("--apply-zones", nargs=5, metavar="V",
                            help="(privileged) write per-zone colors")
    keyboard_p.add_argument("args", nargs="*")

    parsed = parser.parse_args(args_list)

    if parsed.command is None or parsed.command == "help":
        print(textwrap.dedent("""\
            Predator Control

            Usage:
              predator <command> [arguments]

            Commands:
              fans       Control CPU/GPU fans
              profile    Control thermal profile
              turbo      Control turbo mode
              battery    Battery controls
              keyboard   Keyboard RGB controls
              temps      Temperature telemetry
              status     Complete system status
              self-test  Run hardware self-test
              uninstall  Uninstall this app (asks for sudo)
              help       Show help
        """))
        return

    cmd_map = {
        "fans": cmd_fans,
        "profile": cmd_profile,
        "turbo": cmd_turbo,
        "battery": cmd_battery,
        "keyboard": cmd_keyboard,
        "temps": cmd_temps,
        "status": cmd_status,
        "self-test": cmd_selftest,
        "uninstall": cmd_uninstall,
    }

    handler = cmd_map.get(parsed.command)
    if handler:
        args = list(parsed.args) if hasattr(parsed, "args") else []
        if getattr(parsed, "selftest_qml", False):
            args = ["--selftest-qml"] + args
        if getattr(parsed, "apply_mode", None):
            args = ["--apply-mode"] + list(parsed.apply_mode)
        if getattr(parsed, "apply_zones", None):
            args = ["--apply-zones"] + list(parsed.apply_zones)
        if getattr(parsed, "yes", False):
            args = ["--yes"] + args
        if handler and _needs_privilege(parsed.command, args):
            _run_elevated(args_list)
        handler(args)
    else:
        print_error(f"Unknown command: '{parsed.command}'")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
