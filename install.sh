#!/usr/bin/env bash
#
# Predator Control installer (user-space only)
# Installs the Predator Control app for Acer Predator PHN16-71.
# Does NOT install or modify the linuwu_sense kernel driver.
#
set -Eeuo pipefail

APP_NAME="Predator Control"
APP_DIR="/opt/predator-control"
BIN_LINK="/usr/local/bin/predator"
DESKTOP_FILE="/usr/share/applications/predator.desktop"
TMPFILES_FILE="/etc/tmpfiles.d/predator-control.conf"
DRIVER_BASE="/sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi"
STAGED=""

DIST="$(pwd)"

say() { printf '\033[1;32m%s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m%s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

# ── Stage 1: hardware check ──────────────────────────────────────────
check_hardware() {
    say "Checking hardware ..."
    local vendor product
    vendor=$(cat /sys/class/dmi/id/sys_vendor 2>/dev/null || true)
    product=$(cat /sys/class/dmi/id/product_name 2>/dev/null || true)
    echo "    Vendor:  ${vendor:-N/A}"
    echo "    Product: ${product:-N/A}"
    if [[ "$vendor" != "Acer" ]]; then
        die "This machine is not an Acer. Only supported on Acer Predator laptops."
    fi
    case "$product" in
        Predator*) ;;
        *) die "Model '$product' is not a recognized Predator. This app supports Predator laptops only." ;;
    esac
}

# ── Stage 2: driver check ────────────────────────────────────────────
check_driver() {
    say "Checking Linuwu-Sense driver ..."
    local ok=1
    [[ -d /sys/module/linuwu_sense ]] || { warn "    /sys/module/linuwu_sense not present"; ok=0; }
    [[ -d "$DRIVER_BASE/predator_sense" ]] || { warn "    predator_sense interface missing"; ok=0; }
    [[ -d "$DRIVER_BASE/four_zoned_kb" ]] || { warn "    four_zoned_kb interface missing"; ok=0; }

    if type modinfo >/dev/null 2>&1; then
        modinfo linuwu_sense >/dev/null 2>&1 || { warn "    modinfo linuwu_sense failed"; ok=0; }
    fi

    local active
    active=$(systemctl is-active linuwu_sense.service 2>/dev/null || echo "unknown")
    echo "    linuwu_sense.service: $active"
    if [[ "$active" != "active" ]]; then
        warn "    linuwu_sense.service is not active (expected: active)"
    fi

    if [[ $ok -eq 0 ]]; then
        die "Linuwu-Sense driver appears to be missing or incomplete."
    fi
    say "    Linuwu-Sense driver OK"
}

# ── Stage 3: install runtime packages ────────────────────────────────
detect_pm() {
    if type pacman >/dev/null 2>&1; then echo pacman; return; fi
    if type apt-get >/dev/null 2>&1; then echo apt; return; fi
    if type dnf >/dev/null 2>&1; then echo dnf; return; fi
    die "No supported package manager found."
}

install_packages() {
    say "Checking runtime dependencies ..."
    local pm pkgs=()
    pm=$(detect_pm)

    case "$pm" in
        pacman)
            [[ -n "$(pacman -Q pyside6 2>/dev/null)" ]] || pkgs+=(pyside6)
            ;;
        apt)
            if ! python3 -c "import PySide6" >/dev/null 2>&1; then
                pkgs+=(python3-pyside6.qtwidgets)
            fi
            ;;
        dnf)
            if ! python3 -c "import PySide6" >/dev/null 2>&1; then
                pkgs+=(python3-pyside6)
            fi
            ;;
    esac

    if [[ ${#pkgs[@]} -gt 0 ]]; then
        say "    Installing: ${pkgs[*]}"
        case "$pm" in
            pacman) sudo pacman -S --needed --noconfirm "${pkgs[@]}" ;;
            apt)    sudo apt-get install -y "${pkgs[@]}" ;;
            dnf)    sudo dnf install -y "${pkgs[@]}" ;;
        esac
    fi

    python3 -c "import PySide6" >/dev/null 2>&1 || {
        warn "    PySide6 import checks for missing bindings."
        python3 - <<'PY' 2>/dev/null || true
import importlib
for m in ("PySide6.QtCore","PySide6.QtGui","PySide6.QtQml","PySide6.QtQuick"):
    try:
        importlib.import_module(m)
        print("    ", m, "OK")
    except Exception as e:
        print("    ", m, "MISSING:", e)
PY
    }
    say "    Runtime dependencies OK"
}

# ── Stage 4: install app files (atomic) ──────────────────────────────
cleanup_staged() {
    [[ -n "$STAGED" && -d "$STAGED" ]] && rm -rf "$STAGED" || true
}

install_app() {
    say "Installing application files ..."

    STAGED=$(mktemp -d /tmp/predator-install.XXXXXX)
    trap cleanup_staged EXIT

    cp -r "$DIST/predator.py" "$DIST/qml" "$STAGED/"
    chmod 755 "$STAGED/predator.py"

    local qml_files
    qml_files=$(find "$STAGED/qml" -name '*.py' -o -name '*.qml' | wc -l)
    [[ "$qml_files" -ge 3 ]] || die "QML files missing in source tree."

    # Validate Python syntax before install
    python3 -m py_compile "$STAGED/predator.py" || die "predator.py failed syntax check"

    # Swap into place (safe: old install is only removed after new files verified)
    sudo mkdir -p "$APP_DIR"
    if [[ -d "$APP_DIR" && -e "$APP_DIR/predator.py" ]]; then
        sudo rm -rf "$APP_DIR.bak"
        sudo mv "$APP_DIR" "$APP_DIR.bak"
        sudo mkdir -p "$APP_DIR"
    fi
    sudo mv "$STAGED/predator.py" "$STAGED/qml" "$APP_DIR/"
    if [[ -d "$APP_DIR.bak" ]]; then
        sudo rm -rf "$APP_DIR.bak"
    fi
    sudo chown -R root:root "$APP_DIR"

    say "    Installed to $APP_DIR"
}

# ── Stage 5: launcher symlink ────────────────────────────────────────
install_launcher() {
    say "Installing 'predator' command ..."
    sudo ln -sfn "$APP_DIR/predator.py" "$BIN_LINK"
    sudo chmod 755 "$APP_DIR/predator.py"
    say "    $BIN_LINK -> $APP_DIR/predator.py"
}

# ── Stage 6: group & permissions ─────────────────────────────────────
setup_group() {
    say "Configuring permissions ..."

    if ! getent group linuwu_sense >/dev/null; then
        warn "    Creating group 'linuwu_sense'"
        sudo groupadd -r linuwu_sense || die "Failed to create group"
    fi

    local user
    user=$(id -un)
    if [[ -n "$user" && "$user" != "root" ]]; then
        if ! groups "$user" | tr ' ' '\n' | grep -qx linuwu_sense; then
            warn "    Adding user '$user' to group 'linuwu_sense'"
            sudo usermod -aG linuwu_sense "$user"
            USER_GROUP_ADDED=1
        fi
    fi
}

setup_tmpfiles() {
    # Apply chmod to sysfs nodes so the CLI can read without sudo.
    # Write access still requires linuwu_sense group membership.
    local rules
    rules=$(cat <<'EOF'
# Predator Control - read access to linuwu_sense sysfs nodes
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense/fan_speed 0664 root linuwu_sense -
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense/battery_limiter 0664 root linuwu_sense -
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense/battery_calibration 0664 root linuwu_sense -
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense/boot_animation_sound 0664 root linuwu_sense -
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense/lcd_override 0664 root linuwu_sense -
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense/usb_charging 0664 root linuwu_sense -
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/predator_sense/backlight_timeout 0664 root linuwu_sense -
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/four_zoned_kb/four_zone_mode 0664 root linuwu_sense -
m /sys/module/linuwu_sense/drivers/platform:acer-wmi/acer-wmi/four_zoned_kb/per_zone_mode 0664 root linuwu_sense -
m /sys/firmware/acpi/platform_profile 0664 root linuwu_sense -
EOF
)
    echo "$rules" | sudo tee "$TMPFILES_FILE" >/dev/null

    # Apply now (no-op for paths that don't exist)
    sudo systemd-tmpfiles --create "$TMPFILES_FILE" >/dev/null 2>&1 && {
        say "    tmpfiles rules applied"
    } || warn "    systemd-tmpfiles reported a warning (non-fatal)"
}

setup_sudoers() {
    # Password-less elevation for linuwu_sense members ONLY.
    # sudo re-reads /etc/group fresh, so this works even when the
    # current login predates joining the group (no logout needed).
    local sudoers
    sudoers="/etc/sudoers.d/predator-control"
    echo "    Installing sudoers rule: %linuwu_sense NOPASSWD: predator.py"
    printf '%s\n' \
        "# Predator Control: password-less write commands for linuwu_sense members" \
        "%linuwu_sense ALL=(root) NOPASSWD: /opt/predator-control/predator.py *" \
        | sudo tee "$sudoers" >/dev/null
    sudo chmod 0440 "$sudoers"
    sudo chown root:root "$sudoers"
    if sudo visudo -cf "$sudoers" >/dev/null 2>&1; then
        say "    sudoers rule OK"
    else
        warn "    visudo rejected the sudoers rule; removing it"
        sudo rm -f "$sudoers"
        test -f /etc/sudoers && sudo visudo -c >/dev/null 2>&1 || true
    fi
}

# ── Stage 7: desktop entry ───────────────────────────────────────────
install_desktop() {
    say "Installing desktop entry ..."
    sudo cp "$DIST/predator.desktop" "$DESKTOP_FILE"
    sudo chmod 644 "$DESKTOP_FILE"
    say "    $DESKTOP_FILE"
}

# ── Stage 8: verification ────────────────────────────────────────────
verify() {
    say "Verifying installation ..."

    [[ -x "$APP_DIR/predator.py" ]] || die "predator.py not executable in $APP_DIR"
    [[ -L "$BIN_LINK" && -e "$BIN_LINK" ]] || die "'predator' launcher not installed"
    [[ -f "$DESKTOP_FILE" ]] || warn "Desktop entry missing"

    local fail=0
    python3 -c "import PySide6" >/dev/null 2>&1 || { warn "PySide6 import failed"; fail=1; }

    echo ""
    say "CLI self-test:"
    local cmd
    for cmd in help "fans status" "temps" "battery status" "profile status" "keyboard status" "status" "self-test"; do
        echo "--- predator $cmd ---"
        python3 "$APP_DIR/predator.py" $cmd 2>&1 || true
        echo ""
    done

    # GUI initialization check (never leaves a window open)
    if [[ -z "${DISPLAY:-}" && -z "${WAYLAND_DISPLAY:-}" ]]; then
        echo "No display available - skipping interactive GUI test (this is OK in headless installs)."
    else
        echo "--- GUI initialization check ---"
        if timeout 20 python3 "$APP_DIR/predator.py" keyboard --selftest-qml 2>&1; then
            say "    GUI loads OK"
        else
            warn "    GUI could not initialize (if headless, this is expected)"
        fi
    fi

    if [[ ${USER_GROUP_ADDED:-0} -eq 1 ]]; then
        echo ""
        warn "You were added to the 'linuwu_sense' group."
        warn "Write commands already work via password-less sudo."
        warn "Log out and back in (or run: newgrp linuwu_sense) to make the"
        warn "group effective permanently in your session."
    fi
}

# ── main ─────────────────────────────────────────────────────────────
main() {
    USER_GROUP_ADDED=0
    check_hardware
    check_driver
    install_packages
    install_app
    install_launcher
    setup_group
    setup_tmpfiles
    setup_sudoers
    install_desktop
    verify
    echo ""
    say "Installation complete."
    echo ""
    say "Try:  predator status        -- full system status"
    say "      predator keyboard      -- keyboard RGB GUI"
    say "      predator help          -- all commands"
}

main "$@"