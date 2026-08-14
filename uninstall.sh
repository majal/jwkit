#!/usr/bin/env bash
# Remove the jwkit copy installed by install.sh, without removing dependencies
# or jwkit's configuration and downloaded data.
#
#   curl -fsSL https://raw.githubusercontent.com/majal/jwkit/main/uninstall.sh | bash
set -euo pipefail

JWKIT_HOME="${JWKIT_HOME:-$HOME/.jwkit}"
MARKER="# jwkit PATH (added by jwkit's install.sh)"
TOOLS=(ffinpaint ffrife jwdl jwvideo-mux slverse)

die() { printf 'jwkit uninstall: %s\n' "$1" >&2; exit 1; }
note() { printf '%s\n' "$1"; }

safe_install_dir() {
    case "$JWKIT_HOME" in
        ""|/|"$HOME") die "refusing unsafe JWKIT_HOME: ${JWKIT_HOME:-<empty>}" ;;
    esac
}

is_installer_owned() {
    # The normal location is the legacy-safe target for installs made before
    # this uninstaller existed.  A custom path needs stronger evidence.
    [ "$JWKIT_HOME" = "$HOME/.jwkit" ] && return 0
    [ -f "$JWKIT_HOME/jwkit-update" ] || return 1
    local tool
    for tool in "${TOOLS[@]}"; do
        [ -f "$JWKIT_HOME/$tool" ] || return 1
    done
}

remove_recorded_dependencies() {
    local state_file="$1" manager dependency
    [ -f "$state_file" ] || return 0
    manager="$(awk -F= '$1 == "dependency_manager" { print $2; exit }' "$state_file")"
    case "$manager" in
        brew|apt-get|dnf|pacman|apk) ;;
        *) note "Kept dependencies: no recognized installer record."; return 0 ;;
    esac
    while IFS= read -r dependency; do
        [ -n "$dependency" ] || continue
        note "Removing installer-added dependency: $dependency"
        case "$manager" in
            brew) brew uninstall "$dependency" || note "Could not remove $dependency; leaving it installed." ;;
            apt-get) sudo apt-get remove -y "$dependency" || note "Could not remove $dependency; leaving it installed." ;;
            dnf) sudo dnf remove -y "$dependency" || note "Could not remove $dependency; leaving it installed." ;;
            pacman) sudo pacman -Rns --noconfirm "$dependency" || note "Could not remove $dependency; leaving it installed." ;;
            apk) sudo apk del "$dependency" || note "Could not remove $dependency; leaving it installed." ;;
        esac
    done < <(awk -F= '$1 == "dependency" { print $2 }' "$state_file")
}

remove_path_block() {
    local rc="$1" tmp
    [ -f "$rc" ] || return 0
    tmp="${rc}.jwkit-uninstall.$$"
    awk -v marker="$MARKER" '
        $0 == marker {
            if (getline next_line && next_line == "export PATH=\"" ENVIRON["JWKIT_HOME"] ":$PATH\"") next
            print $0
            if (next_line != "") print next_line
            next
        }
        { print }
    ' "$rc" >"$tmp"
    if ! cmp -s "$rc" "$tmp"; then
        mv "$tmp" "$rc"
        note "Removed jwkit from $rc"
    else
        rm -f "$tmp"
    fi
}

safe_install_dir
export JWKIT_HOME

if [ -e "$JWKIT_HOME" ] && ! is_installer_owned; then
    die "refusing to remove custom JWKIT_HOME without an installer footprint: $JWKIT_HOME"
fi

state_copy="$(mktemp "${TMPDIR:-/tmp}/jwkit-install-state.XXXXXX")"
if [ -f "$JWKIT_HOME/.jwkit-install-state" ]; then
    cp "$JWKIT_HOME/.jwkit-install-state" "$state_copy"
fi

for rc in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile" "$HOME/.bashrc"; do
    remove_path_block "$rc"
done

if [ -e "$JWKIT_HOME" ]; then
    rm -rf -- "$JWKIT_HOME"
    note "Removed installed jwkit copy at $JWKIT_HOME"
else
    note "No installed jwkit copy found at $JWKIT_HOME"
fi

remove_recorded_dependencies "$state_copy"
rm -f "$state_copy"
note "Kept all ~/.config/jwkit settings and downloads. Existing dependencies not recorded as installer-added were kept."
