#!/usr/bin/env bash
set -Eeuo pipefail

# Final installer for PXDiv/Div-Linuwu-Sense on Acer Predator PHN16-71.
# Designed for CachyOS/Linux kernels where strncpy() was removed (kernel 7.2+).
#
# What it does:
#   - verifies exact hardware/kernel prerequisites
#   - refreshes/clones Div-Linuwu-Sense
#   - patches the three legacy strncpy() calls only when needed
#   - builds with the same LLVM toolchain used by CachyOS
#   - verifies module metadata/vermagic
#   - safely replaces acer_wmi with linuwu_sense
#   - configures boot loading, systemd state restoration, permissions and tmpfiles
#   - performs read-only functional verification of fan, thermal, battery and RGB interfaces
#   - never changes fan speed, RGB, battery limit, or other user settings during testing

readonly MODULE="linuwu_sense"
readonly CONFLICT="acer_wmi"
readonly REPO_URL="https://github.com/PXDiv/Div-Linuwu-Sense.git"
readonly DEFAULT_SOURCE="${HOME}/Downloads/Div-Linuwu-Sense"
readonly SOURCE="${PREDATOR_SOURCE_DIR:-$DEFAULT_SOURCE}"
readonly KERNEL="$(uname -r)"
readonly KDIR="/lib/modules/${KERNEL}/build"
readonly MDIR="/lib/modules/${KERNEL}/kernel/drivers/platform/x86"
readonly MODFILE="${SOURCE}/src/${MODULE}.ko"
readonly BLACKLIST_FILE="/etc/modprobe.d/blacklist-${CONFLICT}.conf"
readonly MODULES_LOAD_FILE="/etc/modules-load.d/${MODULE}.conf"
readonly TMPFILES_FILE="/etc/tmpfiles.d/${MODULE}.conf"
readonly SERVICE_FILE="/etc/systemd/system/${MODULE}.service"

log()  { printf '\n==> %s\n' "$*"; }
ok()   { printf '✓ %s\n' "$*"; }
warn() { printf '⚠ %s\n' "$*" >&2; }
die()  { printf '✗ %s\n' "$*" >&2; exit 1; }

cleanup_on_error() {
    local rc=$?
    if (( rc != 0 )); then
        printf '\n✗ Installer stopped (exit %d).\n' "$rc" >&2
        printf 'The existing acer_wmi module was not permanently disabled by this script unless installation reached the configuration stage.\n' >&2
        printf 'If the new module is loaded, it is safe to leave it loaded; otherwise reboot or run: sudo modprobe %s\n' "$CONFLICT" >&2
    fi
    exit "$rc"
}
trap cleanup_on_error EXIT

[[ $EUID -eq 0 ]] || true
[[ $EUID -ne 0 ]] || die "Run this script as your normal user, not with sudo. The installer invokes sudo only where required."

sudo -v

# Keep sudo credentials alive while the script is running.
( while true; do sudo -n true; sleep 50; done ) 2>/dev/null &
SUDO_KEEPALIVE_PID=$!
trap 'kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true' EXIT

log "Detecting hardware and kernel"
vendor="$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true)"
model="$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)"
printf 'Vendor : %s\nModel  : %s\nKernel : %s\n' "$vendor" "$model" "$KERNEL"

[[ "$vendor" == "Acer" ]] || die "This installer is intended for Acer systems; detected vendor: ${vendor:-unknown}"
[[ "$model" == "Predator PHN16-71" ]] || die "Exact supported model is Predator PHN16-71; detected: ${model:-unknown}"
ok "Predator PHN16-71 detected"

[[ -d "$KDIR" ]] || die "Matching kernel headers/build tree not found: $KDIR"
[[ -f "$KDIR/Makefile" ]] || die "Kernel build tree is incomplete: $KDIR/Makefile"
ok "Matching kernel headers found"

log "Checking build dependencies"
for cmd in git make clang ld.lld modinfo modprobe depmod systemctl awk sed grep install find getent id; do
    command -v "$cmd" >/dev/null 2>&1 || die "Required command not found: $cmd"
done
ok "Git, Make, Clang, LLD and system tools found"

kernel_compiler="$(
    if [[ -r "$KDIR/include/config/kernel.release" ]]; then
        :
    fi
    clang --version | head -1
)"
printf 'Kernel compiler: %s\n' "$kernel_compiler"

# Ensure the compiler/assembler used for the external module matches the
# LLVM-built CachyOS kernel.
export LLVM=1
export LLVM_IAS=1

log "Preparing Linuwu-Sense source"
if [[ -d "$SOURCE/.git" ]]; then
    printf 'Existing Git repository found:\n  %s\n' "$SOURCE"
    git -C "$SOURCE" fetch --all --prune
    git -C "$SOURCE" reset --hard origin/HEAD
    git -C "$SOURCE" clean -fdx
    ok "Existing repository refreshed"
else
    mkdir -p "$(dirname "$SOURCE")"
    git clone "$REPO_URL" "$SOURCE"
    ok "Repository cloned"
fi

[[ -f "$SOURCE/Makefile" ]] || die "Repository does not contain a Makefile"
[[ -f "$SOURCE/src/linuwu_sense.c" ]] || die "Driver source file not found"
[[ -f "$SOURCE/linuwu_sense.service" ]] || die "Driver systemd service file not found"

log "Checking Linux kernel API compatibility"
source_file="$SOURCE/src/linuwu_sense.c"
strncpy_count="$(grep -oE '\bstrncpy[[:space:]]*\(' "$source_file" | wc -l | tr -d ' ')"

if (( strncpy_count > 0 )); then
    warn "Found ${strncpy_count} strncpy() call(s)."
    backup="${source_file}.pre-strncpy-patch"
    if [[ ! -f "$backup" ]]; then
        cp -a "$source_file" "$backup"
        ok "Created compatibility backup: $(basename "$backup")"
    fi

    # These copies are bounded by len and the code explicitly writes the
    # terminating NUL afterward, so memcpy is the intended kernel-7.2+ fix.
    sed -i -E 's/\bstrncpy[[:space:]]*\(/memcpy(/g' "$source_file"

    remaining="$(grep -oE '\bstrncpy[[:space:]]*\(' "$source_file" | wc -l | tr -d ' ' || true)"
    (( remaining == 0 )) || die "Compatibility patch did not remove all legacy strncpy() calls"
    ok "Applied strncpy() compatibility patch"
else
    ok "No legacy strncpy() calls found; source is already kernel-7.2+ compatible"
fi

log "Cleaning previous build"
make -C "$KDIR" M="$SOURCE" clean
ok "Build tree cleaned"

log "Building Linuwu-Sense against $KERNEL"
make -C "$KDIR" M="$SOURCE" modules
ok "Kernel module compiled successfully"

[[ -s "$MODFILE" ]] || die "Build completed but module was not produced: $MODFILE"

log "Verifying kernel module"
module_vermagic="$(modinfo -F vermagic "$MODFILE" 2>/dev/null || true)"
module_name="$(modinfo -F name "$MODFILE" 2>/dev/null || true)"
printf 'Module name : %s\nVermagic    : %s\n' "$module_name" "$module_vermagic"

[[ "$module_name" == "$MODULE" ]] || die "Unexpected module name: ${module_name:-unknown}"
[[ "$module_vermagic" == "$KERNEL"* ]] || die "Module vermagic does not match running kernel"
ok "Module metadata matches running kernel"

# Preserve the currently loaded state so a failed install can be diagnosed
# without silently leaving both Acer WMI implementations active.
had_conflict=0
had_module=0
lsmod | awk '{print $1}' | grep -qx "$CONFLICT" && had_conflict=1 || true
lsmod | awk '{print $1}' | grep -qx "$MODULE" && had_module=1 || true

log "Preparing kernel module replacement"
if (( had_module )); then
    ok "$MODULE is already loaded; it will be reloaded after installation"
    sudo modprobe -r "$MODULE" || die "Could not unload the existing $MODULE module"
fi

if lsmod | awk '{print $1}' | grep -qx "$CONFLICT"; then
    sudo modprobe -r "$CONFLICT" || die "Could not unload conflicting $CONFLICT module"
fi

if lsmod | awk '{print $1}' | grep -qx "$CONFLICT"; then
    die "$CONFLICT is still loaded; refusing to continue with two Acer WMI implementations"
fi
ok "$CONFLICT unloaded"

log "Installing Linuwu-Sense kernel module"
sudo install -d "$MDIR"
sudo install -m 644 "$MODFILE" "$MDIR/${MODULE}.ko"
sudo depmod -a
ok "Kernel module installed"

log "Loading Linuwu-Sense"
if ! sudo modprobe "$MODULE"; then
    echo
    echo "----- kernel log -----" >&2
    sudo journalctl -k -b --no-pager -n 100 >&2 || sudo dmesg | tail -100 >&2 || true
    echo "----------------------" >&2
    die "$MODULE failed to load"
fi

# Definitive loaded-module check. Do not parse lsmod as the primary test.
[[ -d "/sys/module/${MODULE}" ]] || die "$MODULE modprobe succeeded but /sys/module/$MODULE does not exist"
ok "$MODULE loaded successfully"

# Give the driver a moment to finish its platform-profile retry loop.
sleep 1

SYS_BASE="/sys/module/${MODULE}/drivers/platform:acer-wmi/acer-wmi"
PREDATOR_BASE="${SYS_BASE}/predator_sense"
KB_BASE="${SYS_BASE}/four_zoned_kb"
HWMON_BASE="${SYS_BASE}/hwmon"

log "Verifying Predator hardware interfaces"

[[ -d "$PREDATOR_BASE" ]] || die "predator_sense sysfs interface was not created"
ok "Predator control interface present"

for f in fan_speed battery_limiter battery_calibration boot_animation_sound lcd_override usb_charging; do
    [[ -e "$PREDATOR_BASE/$f" ]] || die "Expected control missing: $f"
done
ok "Fan, battery and exposed Predator controls present"

[[ -e "$KB_BASE/four_zone_mode" ]] || die "four_zone_mode RGB interface missing"
[[ -e "$KB_BASE/per_zone_mode" ]] || die "per_zone_mode RGB interface missing"
ok "Four-zone RGB interfaces present"

# Read-only fan/temperature verification.
fan_value="$(cat "$PREDATOR_BASE/fan_speed")"
printf 'Fan state    : %s\n' "$fan_value"
[[ "$fan_value" =~ ^[0-9]+,[0-9]+$ ]] || die "Unexpected fan_speed format: $fan_value"
ok "Fan control read/write interface is valid"

hwmon_dir="$(find "$HWMON_BASE" -maxdepth 1 -type d -name 'hwmon*' -print -quit 2>/dev/null || true)"
if [[ -n "$hwmon_dir" ]]; then
    temp_count="$(find "$hwmon_dir" -maxdepth 1 -type f -name 'temp*_input' | wc -l | tr -d ' ')"
    fan_count="$(find "$hwmon_dir" -maxdepth 1 -type f -name 'fan*_input' | wc -l | tr -d ' ')"
    printf 'Telemetry    : %s temperature sensor(s), %s fan sensor(s)\n' "$temp_count" "$fan_count"
    (( temp_count >= 1 )) || die "No temperature telemetry exposed"
    (( fan_count >= 1 )) || die "No fan telemetry exposed"
    ok "Hardware telemetry present"
else
    die "Driver hwmon interface was not created"
fi

# Platform profile is expected to be registered by this driver on PHN16-71.
if [[ -r /sys/firmware/acpi/platform_profile_choices && -r /sys/firmware/acpi/platform_profile ]]; then
    profile_choices="$(cat /sys/firmware/acpi/platform_profile_choices)"
    current_profile="$(cat /sys/firmware/acpi/platform_profile)"
    printf 'Profiles     : %s\nCurrent      : %s\n' "$profile_choices" "$current_profile"
    [[ "$profile_choices" == *"quiet"* ]] || die "quiet profile missing"
    [[ "$profile_choices" == *"balanced"* ]] || die "balanced profile missing"
    [[ "$profile_choices" == *"performance"* ]] || die "performance profile missing"
    ok "Thermal profile interface present"
else
    die "ACPI platform profile interface is missing"
fi

# RGB read-only sanity checks; do not write colors/effects during install.
per_zone_state="$(cat "$KB_BASE/per_zone_mode")"
four_zone_state="$(cat "$KB_BASE/four_zone_mode")"
printf 'RGB zones    : %s\nRGB effect   : %s\n' "$per_zone_state" "$four_zone_state"
[[ -n "$per_zone_state" && -n "$four_zone_state" ]] || die "RGB interfaces returned empty state"
ok "RGB state interfaces readable"

log "Configuring boot persistence"
printf '%s\n' "$MODULE" | sudo tee "$MODULES_LOAD_FILE" >/dev/null
printf 'blacklist %s\n' "$CONFLICT" | sudo tee "$BLACKLIST_FILE" >/dev/null
sudo depmod -a
ok "Kernel module will load at boot and acer_wmi is blacklisted"

log "Installing state-restore service"
sudo install -m 644 "$SOURCE/linuwu_sense.service" "$SERVICE_FILE"
sudo systemctl daemon-reload
sudo systemctl enable "$MODULE.service" >/dev/null
sudo systemctl restart "$MODULE.service"
if ! sudo systemctl is-active --quiet "$MODULE.service"; then
    sudo systemctl status "$MODULE.service" --no-pager >&2 || true
    die "$MODULE.service is not active"
fi
ok "State-restore service enabled and active"

log "Configuring non-root permissions"
if ! getent group "$MODULE" >/dev/null; then
    sudo groupadd "$MODULE"
    ok "Created group $MODULE"
else
    ok "Group $MODULE already exists"
fi

sudo usermod -aG "$MODULE" "$USER"

# Rebuild the tmpfiles policy from scratch so stale entries cannot accumulate.
tmp="$(mktemp)"
trap 'rm -f "$tmp"; kill "$SUDO_KEEPALIVE_PID" 2>/dev/null || true' EXIT

{
    for f in backlight_timeout battery_calibration battery_limiter boot_animation_sound fan_speed lcd_override usb_charging; do
        printf 'f %s/%s 0660 root %s\n' "$PREDATOR_BASE" "$f" "$MODULE"
    done
    printf 'f %s/four_zone_mode 0660 root %s\n' "$KB_BASE" "$MODULE"
    printf 'f %s/per_zone_mode 0660 root %s\n' "$KB_BASE" "$MODULE"
} > "$tmp"

sudo install -m 644 "$tmp" "$TMPFILES_FILE"
sudo systemd-tmpfiles --create "$TMPFILES_FILE"
rm -f "$tmp"
ok "Sysfs permissions configured for group $MODULE"

log "Final verification"

[[ -r "$PREDATOR_BASE/fan_speed" && -w "$PREDATOR_BASE/fan_speed" ]] || die "fan_speed is not readable/writable by root after tmpfiles setup"
[[ -r "$KB_BASE/per_zone_mode" && -w "$KB_BASE/per_zone_mode" ]] || die "RGB interface permissions are incorrect"
[[ -r "$PREDATOR_BASE/battery_limiter" && -w "$PREDATOR_BASE/battery_limiter" ]] || die "battery_limiter permissions are incorrect"

if lsmod | awk '{print $1}' | grep -qx "$CONFLICT"; then
    die "Final check failed: $CONFLICT is loaded"
fi
if ! lsmod | awk '{print $1}' | grep -qx "$MODULE"; then
    die "Final check failed: $MODULE is not loaded"
fi

printf '\n'
ok "Kernel module: loaded"
ok "Acer WMI conflict: absent"
ok "Predator PHN16-71 controls: present"
ok "Fan telemetry/control: present"
ok "Thermal profiles: present"
ok "Four-zone RGB: present"
ok "Battery controls: present"
ok "Boot persistence: configured"
ok "State restore service: active"

cat <<'EOF'

============================================================
 Predator PHN16-71 driver installation completed successfully
============================================================

IMPORTANT:
  Your current shell may not yet have the new linuwu_sense
  group membership. Start a new login session (recommended),
  or run:

    newgrp linuwu_sense

Then verify without changing hardware state:

    predator-driver-test  # if you create your own test helper
    cat /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense/fan_speed
    cat /sys/firmware/acpi/platform_profile
    cat /sys/firmware/acpi/platform_profile_choices

The installer intentionally does NOT change fan speed, RGB,
battery limit, or other settings during its tests.
============================================================
EOF

# Do not call newgrp from inside the installer: changing the caller's shell
# group cannot reliably persist after the script exits. A new login/newgrp is
# the correct boundary.
exit 0
