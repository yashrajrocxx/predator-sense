#!/usr/bin/env bash
#
# Predator Control uninstaller
# Removes ONLY the user-space Predator Control application.
# Does NOT touch linuwu_sense, acer_wmi, kernel modules, or system config.
#
# Preferred path: `predator uninstall` (integrated, asks for confirmation).
# This script is a fallback for when the app cannot run.
#
set -Eeuo pipefail

APP_DIR="/opt/predator-control"
BIN_LINK="/usr/local/bin/predator"
DESKTOP_FILE="/usr/share/applications/predator.desktop"
TMPFILES_FILE="/etc/tmpfiles.d/predator-control.conf"

say() { printf '\033[1;32m%s\033[0m\n' "$*"; }
die() { printf '\033[1;31mError: %s\033[0m\n' "$*" >&2; exit 1; }

# Safety: verify a path belongs to this app before deleting.
check_app_path() {
    local path="$1"
    [[ -e "$path" || -L "$path" ]] || return 1
    echo "$path" | grep -qx '/opt/predator-control\|/usr/local/bin/predator\|/usr/share/applications/predator.desktop\|/etc/tmpfiles.d/predator-control.conf' \
        || die "Refusing to delete unrecognized path: $path"
    return 0
}

fallback_uninstall() {
    echo "Uninstalling Predator Control (user-space app only) ..."
    echo "The linuwu_sense driver and its service are left untouched."
    for p in "$APP_DIR" "$BIN_LINK" "$DESKTOP_FILE" "$TMPFILES_FILE"; do
        if check_app_path "$p"; then
            sudo rm -rf "$p"
            say "    Removed: $p"
        fi
    done
    echo ""
    say "Done."
    say "If you also want to remove the driver itself, uninstall Linuwu-Sense separately."
}

main() {
    if command -v predator >/dev/null 2>&1 && predator help >/dev/null 2>&1; then
        say "Using integrated uninstaller (predator uninstall --yes)."
        predator uninstall --yes || fallback_uninstall
    else
        fallback_uninstall
    fi
}

main "$@"