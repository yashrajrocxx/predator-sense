# Predator Control

A small, native Linux utility to control the hardware of **Acer Predator PHN16-71**
laptops running the **Linuwu-Sense** kernel driver.

**This application requires Linuwu-Sense.** It is a user-space frontend only; it does
not install, replace, or modify any kernel driver.

---

## What it does

| Area | Features |
|------|----------|
| Fans | Set CPU/GPU fan percentage (0–100), auto, max. Read-back verification. |
| Thermal profile | Switch `quiet`, `balanced`, `performance` (etc.) via `platform_profile`. |
| Turbo | Maps to the `performance` thermal profile (the driver's turbo tier). |
| Battery | Read capacity/status, toggle the charge limiter and calibration. |
| Keyboard RGB | Full four-zone RGB control with a Qt Quick GUI: colors, brightness, effects, speed, direction. |
| Telemetry | Temperature and fan-RPM readout via hwmon. |
| Status | One-command snapshot of the whole system. |

## Supported hardware

* Acer Predator PHN16-71 (checked at install time)
* Requires kernel `linux-cachyos` with the `linuwu_sense` module loaded
  (PXDiv/Div-Linuwu-Sense driver)
* Requires the user to be a member of the `linuwu_sense` group
* Requires Python 3, PySide6, Qt 6, Qt Quick

## Architecture

```
CLI  ──┐
       ├── predator.py (backend: Fan/Profile/Battery/Keyboard/Telemetry)
GUI ───┘                    │
        QML ──► KeyboardBridge (qml/gui.py) ──► predator.py ──► sysfs ──► Linuwu-Sense
```

* Everything lives in `predator.py` plus a few QML files.
* The CLI and GUI share the same backend object — no duplicated hardware logic.
* The CLI never imports Qt; PySide6 is loaded lazily, only for `predator keyboard`.
* No daemon. The existing `linuwu_sense.service` handles state persistence at boot.

## Installation

```sh
git clone <repo> predator-control
cd predator-control
./install.sh
```

The installer is safe to run multiple times (idempotent). It will:

1. Verify the machine is an Acer Predator.
2. Verify Linuwu-Sense is loaded and its service is active.
3. Install runtime packages (`pyside6` via pacman/apt/dnf).
4. Copy the app to `/opt/predator-control`.
5. Create the `predator` launcher at `/usr/local/bin/predator`.
6. Ensure the `linuwu_sense` group exists and the current user is a member.
7. Write sysfs permission rules to `/etc/tmpfiles.d/predator-control.conf`.
8. Install a desktop entry.
9. Run read-only self-tests (never changes hardware state).

> If you were just added to the `linuwu_sense` group, **log out and back in**
> (or run `newgrp linuwu_sense`) before using the write commands.

Installation never changes your fan speeds, RGB, battery limit, profile, or turbo.

### Where things are installed

| Path | Purpose |
|------|---------|
| `/opt/predator-control/` | The application (Python backend + QML files) |
| `/usr/local/bin/predator` | Launcher symlink → the app. `/usr/local/bin` is already on the default `PATH`, so `predator` works from any terminal — **no shell-rc files are modified** |
| `/usr/share/applications/predator.desktop` | App (GUI) launcher for your desktop menu |
| `/etc/tmpfiles.d/predator-control.conf` | Permission rules (sysfs group access for the `linuwu_sense` group) |
| `/etc/sudoers.d/predator-control` | Password-less elevation rule for `linuwu_sense` members (writes only) |

You can run it straight from your clone too:

```sh
./predator.py status          # no install required for read commands
./predator.py keyboard        # GUI needs PySide6 installed
```

`install.sh` copies this whole directory into `/opt/predator-control`, so you
are free to delete the clone afterward — the installed app is self-contained.

## Uninstallation

```sh
predator uninstall        # asks for confirmation, then asks for sudo
predator uninstall --yes  # non-interactive
```

The uninstaller removes **only** the Predator Control application
(`/opt/predator-control`, the `/usr/local/bin/predator` launcher, the desktop
entry, the tmpfiles and sudoers rules). It **does not** touch `linuwu_sense`,
`linuwu_sense.service`, the kernel module, or any other system configuration.

A standalone `./uninstall.sh` is also included as a fallback; it simply calls
`predator uninstall --yes` when the app is functional.

## CLI usage

```
predator <command> [arguments]
```

### Help

```sh
predator                # top-level help
predator help
predator fans help
predator profile help
predator turbo help
predator battery help
predator keyboard help
```

### Fans

```sh
predator fans status    # show current fan mode and percentages
predator fans auto      # automatic fan control (0,0)
predator fans max       # maximum fan speed (100,100)
predator fans 50        # both fans at 50%
predator fans 50 70     # CPU 50%, GPU 70%
```

Values are integers 0–100. Invalid input is rejected with a clear error and
exit code 1. Every write is verified by reading the value back.

### Thermal profile

```sh
predator profile status
predator profile quiet      # quiet / eco
predator profile bal        # balanced
predator profile perf       # performance
predator profile turbo      # alias for performance
```

Available profiles are read from `/sys/firmware/acpi/platform_profile_choices`.
On this machine: `low-power`, `quiet`, `balanced`, `balanced-performance`, `performance`.
Some performance profiles are only available on AC power.

### Turbo

```sh
predator turbo status
predator turbo on       # = performance profile (turbo tier)
predator turbo off      # = balanced profile
```

Note: the physical turbo button also changes overclocking settings that are not
exposed to userspace by the driver; that capability cannot be toggled from here.

### Battery

```sh
predator battery status
predator battery limit 80      # enable charge limiter
predator battery limit 100     # disable charge limiter
predator battery limit on|off
predator battery calibration on|off
```

The driver's battery limiter is an on/off flag (it caps at 80%). Under the hood
`limit 80` / `limit on` enable the limiter; `limit 100` / `limit off` disable it.

### Keyboard GUI

```sh
predator keyboard          # open the keyboard RGB control window
predator keyboard status   # show current RGB state as text
predator keyboard --selftest-qml   # verify QML loads, then exit (no window)
```

The GUI provides:

* A four-zone keyboard visualization (click a zone to edit it)
* RGB color picker (sliders + hex field)
* Per-zone colors and brightness
* Global effects: Static, Breathing, Neon, Wave, Shifting, Zoom, Meteor, Twinkling
* Effect speed (0–9) and direction where the effect supports them

The GUI never resets the keyboard/fans/profile when it closes. Writes are only
sent when you press an Apply button — dragging a slider does not flood the sysfs
interface. Closing the window leaves the hardware exactly as configured.

### Telemetry and status

```sh
predator temps       # temperatures and fan RPM
predator status      # full system snapshot
predator self-test   # read-only hardware/driver verification (PASS/WARN/FAIL)
```

### Debugging

```sh
predator --debug ...
PREDATOR_DEBUG=1 predator ...
```

Debug mode prints the sysfs paths, values, and exceptions.

## Permissions

The app runs without `sudo` for everyday use:

* **Reads** work for any user (sysfs files are world-readable via tmpfiles).
* **Writes** work for members of the `linuwu_sense` group — and it works
  *immediately after install*, even if your current login predates joining the
  group:

  - If your session already has `linuwu_sense` active (fresh login), writes go
    directly through the group.
  - If your session is stale (you joined the group after logging in), the app
    automatically re-runs the write through password-less `sudo`. `sudo` reads
    `/etc/group` fresh, so it grants the write without a password and without a
    logout. The sudoers rule is scoped to the app only:
    `%linuwu_sense ALL=(root) NOPASSWD: /opt/predator-control/predator.py *`.
  - Non-members are rejected.

* The GUI never requires root and never prompts for a password. If a write
  needs elevation, it uses the same password-less rule behind the scenes.

Only `install.sh` / `uninstall` use `sudo` directly.

If a command still reports a permission error, check:

```sh
groups          # does your current session have the linuwu_sense group?
getent group linuwu_sense
```

If the group is listed in `/etc/group` but not in `groups`, the password-less
elevation handles it automatically — no logout needed.

## Persistence

Hardware state is persisted by the **Linuwu-Sense driver** (its `linuwu_sense.service`
restores fan/profile/RGB state at boot). Predator Control does not run a daemon and
does not duplicate that state. It simply writes the desired state through the driver.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Predator Control GUI initialized OK` never printed | PySide6 not installed → `sudo pacman -S pyside6` |
| `Permission denied ... linuwu_sense group` | Log out/in or `newgrp linuwu_sense` |
| `Linuwu-Sense driver not loaded` | Load the driver outside this project |
| `Predator PHN16-71` self-test FAIL on hardware | This app only supports the PHN16-71 |
| Profile write rejected on battery | Some performance profiles require AC power |

## Limitations

* Turbo beyond the thermal profile is not exposed by the driver to userspace.
* Effect speed/direction are ignored by the driver for some effects (Static, Breathing ignore speed and direction; Neon ignores color).
* Sensor labels are not provided by the driver; temp sensors are reported as Temp 1/2/3, fans as CPU fan/GPU fan based on driver convention.
* Auto fan curve is intentionally not implemented in v1 (manual fan control only).

## Exit codes

* `0` — success
* `1` — invalid input, write failure, permission denied, or driver unavailable
* `2` — argument parsing error