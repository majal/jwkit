#!/usr/bin/env bash
# Remove the jwkit copy installed by install.sh, without removing dependencies
# or jwkit's configuration and downloaded data.
#
#   curl -fsSL https://raw.githubusercontent.com/majal/jwkit/main/uninstall.sh | bash
set -euo pipefail

JWKIT_HOME="${JWKIT_HOME:-$HOME/.jwkit}"
MARKER="# jwkit PATH (added by jwkit's install.sh)"
TOOLS=(ffrife jwdl jwvideo-mux slverse)

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

for rc in "$HOME/.zshrc" "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile" "$HOME/.bashrc"; do
    remove_path_block "$rc"
done

if [ -e "$JWKIT_HOME" ]; then
    rm -rf -- "$JWKIT_HOME"
    note "Removed installed jwkit copy at $JWKIT_HOME"
else
    note "No installed jwkit copy found at $JWKIT_HOME"
fi

note "Kept Python, ffmpeg, git, and all ~/.config/jwkit settings and downloads."
