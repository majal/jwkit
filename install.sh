#!/usr/bin/env bash
# jwkit installer for macOS and Linux.
#
#   curl -fsSL https://raw.githubusercontent.com/majal/jwkit/main/install.sh | bash
#
# Installs Python/ffmpeg/git if missing, downloads jwkit to ~/.jwkit, adds it
# to your shell PATH, and sets up a `jwkit-update` command. Safe to re-run -
# re-running this script (or `jwkit-update`) updates jwkit in place.
set -euo pipefail

JWKIT_HOME="${JWKIT_HOME:-$HOME/.jwkit}"
REPO_URL="https://github.com/majal/jwkit"
TARBALL_URL="${REPO_URL}/archive/refs/heads/main.tar.gz"
TOOLS=(slverse ffrife jwdl jwvideo-mux)

c_bold()   { printf '\033[1m%s\033[0m\n' "$1"; }
c_green()  { printf '\033[32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[33m%s\033[0m\n' "$1"; }
c_red()    { printf '\033[31m%s\033[0m\n' "$1" >&2; }
step()     { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

on_error() {
    c_red "Something went wrong partway through setup."
    c_red "You can re-run this installer any time - it's safe to repeat."
    c_red "If it keeps failing, please open an issue: ${REPO_URL}/issues"
}
trap on_error ERR

step "Setting up jwkit"

# --- Dependencies ---
ensure_macos_deps() {
    if ! command_exists brew; then
        step "Installing Homebrew (needed to install Python/ffmpeg on macOS)"
        c_yellow "Homebrew's own installer may ask for your Mac login password - that's expected."
        NONINTERACTIVE=1 /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        if [ -x /opt/homebrew/bin/brew ]; then eval "$(/opt/homebrew/bin/brew shellenv)"; fi
        if [ -x /usr/local/bin/brew ]; then eval "$(/usr/local/bin/brew shellenv)"; fi
    fi

    step "Checking Python, ffmpeg, git"
    local missing=()
    command_exists python3 || missing+=(python3)
    command_exists ffmpeg || missing+=(ffmpeg)
    command_exists git || missing+=(git)
    if [ "${#missing[@]}" -gt 0 ]; then
        c_yellow "Installing via Homebrew: ${missing[*]}"
        brew install "${missing[@]}"
    else
        c_green "Already have python3, ffmpeg, and git."
    fi
}

ensure_linux_deps() {
    step "Checking Python, ffmpeg, git"
    local missing=()
    command_exists python3 || missing+=(python3)
    command_exists ffmpeg || missing+=(ffmpeg)
    command_exists git || missing+=(git)

    if [ "${#missing[@]}" -eq 0 ]; then
        c_green "Already have python3, ffmpeg, and git."
        return
    fi

    c_yellow "Installing: ${missing[*]} (this needs your sudo password)"
    if command_exists apt-get; then
        sudo apt-get update -y
        sudo apt-get install -y "${missing[@]}"
    elif command_exists dnf; then
        sudo dnf install -y "${missing[@]}"
    elif command_exists pacman; then
        sudo pacman -Sy --noconfirm "${missing[@]}"
    elif command_exists apk; then
        sudo apk add "${missing[@]}"
    else
        c_red "Couldn't detect apt/dnf/pacman/apk. Please install manually: ${missing[*]}"
        c_red "Then re-run this installer."
        exit 1
    fi
}

os="$(uname -s)"
case "$os" in
    Darwin) ensure_macos_deps ;;
    Linux) ensure_linux_deps ;;
    *)
        c_red "jwkit's installer supports macOS and Linux. For Windows, use install.ps1 instead:"
        c_red "  irm https://raw.githubusercontent.com/majal/jwkit/main/install.ps1 | iex"
        exit 1
        ;;
esac

# --- Fetch jwkit ---
step "Getting jwkit"
if command_exists git; then
    if [ -d "$JWKIT_HOME/.git" ]; then
        c_yellow "Updating existing install at $JWKIT_HOME"
        git -C "$JWKIT_HOME" fetch -q origin main
        git -C "$JWKIT_HOME" reset -q --hard origin/main
    else
        rm -rf "$JWKIT_HOME"
        git clone -q "${REPO_URL}.git" "$JWKIT_HOME"
    fi
else
    rm -rf "$JWKIT_HOME"
    mkdir -p "$JWKIT_HOME"
    curl -fsSL "$TARBALL_URL" | tar -xz -C "$JWKIT_HOME" --strip-components=1
fi

for tool in "${TOOLS[@]}"; do
    [ -f "$JWKIT_HOME/$tool" ] && chmod +x "$JWKIT_HOME/$tool"
done
[ -f "$JWKIT_HOME/jwvideo-mux-shortcuts.sh" ] && chmod +x "$JWKIT_HOME/jwvideo-mux-shortcuts.sh"

# --- PATH ---
step "Adding jwkit to your PATH"
add_path_block() {
    local rc="$1"
    local marker="# jwkit PATH (added by jwkit's install.sh)"
    [ -f "$rc" ] || touch "$rc"
    if grep -qF "$marker" "$rc" 2>/dev/null; then
        return 0
    fi
    {
        echo ""
        echo "$marker"
        echo "export PATH=\"$JWKIT_HOME:\$PATH\""
    } >>"$rc"
    c_green "Added to $rc"
}

case "$(basename "${SHELL:-bash}")" in
    zsh)
        add_path_block "$HOME/.zshrc"
        ;;
    bash)
        add_path_block "$HOME/.bash_profile"
        add_path_block "$HOME/.bashrc"
        ;;
    *)
        add_path_block "$HOME/.profile"
        ;;
esac
export PATH="$JWKIT_HOME:$PATH"

# --- Update command ---
cat >"$JWKIT_HOME/jwkit-update" <<UPDATE
#!/usr/bin/env bash
set -euo pipefail
curl -fsSL https://raw.githubusercontent.com/majal/jwkit/main/install.sh | bash
UPDATE
chmod +x "$JWKIT_HOME/jwkit-update"

step "All set!"
c_green "jwkit is installed at $JWKIT_HOME"
echo ""
echo "Open a new terminal window (or run: source ~/.zshrc), then try:"
c_bold "  slverse --help"
c_bold "  jwdl list"
echo ""
echo "For the interactive setup (languages, cache size, etc.), run:"
c_bold "  slverse setup"
echo ""
echo "To update jwkit later, run:"
c_bold "  jwkit-update"
