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
TOOLS=(ffinpaint ffrife jwdl jwpl jwvideo-mux slverse)
INSTALLED_DEPENDENCIES=()
DEPENDENCY_MANAGER=""

c_bold()   { printf '\033[1m%s\033[0m\n' "$1"; }
c_green()  { printf '\033[32m%s\033[0m\n' "$1"; }
c_yellow() { printf '\033[33m%s\033[0m\n' "$1"; }
c_red()    { printf '\033[31m%s\033[0m\n' "$1" >&2; }
step()     { printf '\n\033[1m==> %s\033[0m\n' "$1"; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

safe_install_dir() {
    case "$JWKIT_HOME" in
        ""|/|"$HOME")
            c_red "Refusing unsafe JWKIT_HOME: ${JWKIT_HOME:-<empty>}"
            exit 1
            ;;
    esac
}

on_error() {
    c_red "Something went wrong partway through setup."
    c_red "You can re-run this installer any time - it's safe to repeat."
    c_red "If it keeps failing, please open an issue: ${REPO_URL}/issues"
}
trap on_error ERR

step "Setting up jwkit"
safe_install_dir

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
        DEPENDENCY_MANAGER="brew"
        INSTALLED_DEPENDENCIES+=("${missing[@]}")
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
        DEPENDENCY_MANAGER="apt-get"
    elif command_exists dnf; then
        sudo dnf install -y "${missing[@]}"
        DEPENDENCY_MANAGER="dnf"
    elif command_exists pacman; then
        sudo pacman -Sy --noconfirm "${missing[@]}"
        DEPENDENCY_MANAGER="pacman"
    elif command_exists apk; then
        sudo apk add "${missing[@]}"
        DEPENDENCY_MANAGER="apk"
    else
        c_red "Couldn't detect apt/dnf/pacman/apk. Please install manually: ${missing[*]}"
        c_red "Then re-run this installer."
        exit 1
    fi
    INSTALLED_DEPENDENCIES+=("${missing[@]}")
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
        # Named explicitly rather than relying only on .gitignore: an
        # existing install whose checked-out .gitignore predates a given
        # installer-generated file (as .jwkit-install-state did until this
        # fix) would otherwise see it as an untracked "local change" and
        # never update again to PICK UP that .gitignore fix - the exact bug
        # this line fixes. Keep this list and .gitignore in sync.
        untracked_files="$(git -C "$JWKIT_HOME" ls-files --others --exclude-standard | grep -vE '^(jwkit-update|\.jwkit-install-state)$' || true)"
        if ! git -C "$JWKIT_HOME" diff --quiet ||
           ! git -C "$JWKIT_HOME" diff --cached --quiet ||
           [ -n "$untracked_files" ]; then
            c_yellow "Local changes found; leaving the existing install untouched."
            c_yellow "Commit, stash, or remove them, then run jwkit-update again."
        elif ! git -C "$JWKIT_HOME" merge --ff-only origin/main; then
            c_yellow "Could not fast-forward the existing install; leaving it untouched."
            c_yellow "Resolve its Git state, then run jwkit-update again."
        fi
    else
        if [ -e "$JWKIT_HOME" ]; then
            c_red "Install path exists but is not a jwkit Git checkout: $JWKIT_HOME"
            c_red "Choose an empty JWKIT_HOME or move the existing directory yourself."
            exit 1
        fi
        git clone -q "${REPO_URL}.git" "$JWKIT_HOME"
    fi
else
    if [ -e "$JWKIT_HOME" ]; then
        c_red "Install path already exists and Git is unavailable: $JWKIT_HOME"
        c_red "Install Git, or choose an empty JWKIT_HOME."
        exit 1
    fi
    mkdir -p "$JWKIT_HOME"
    curl -fsSL "$TARBALL_URL" | tar -xz -C "$JWKIT_HOME" --strip-components=1
fi

for tool in "${TOOLS[@]}"; do
    [ -f "$JWKIT_HOME/$tool" ] && chmod +x "$JWKIT_HOME/$tool"
done

# Record only packages this installer added.  This lets uninstall.sh clean up a
# standalone install without guessing whether an existing dependency is used
# by another project.  Keep prior entries when an install is re-run.
if [ -n "$DEPENDENCY_MANAGER" ] && [ "${#INSTALLED_DEPENDENCIES[@]}" -gt 0 ]; then
    state_file="$JWKIT_HOME/.jwkit-install-state"
    state_tmp="${state_file}.tmp.$$"
    {
        [ -f "$state_file" ] && cat "$state_file"
        printf 'dependency_manager=%s\n' "$DEPENDENCY_MANAGER"
        printf 'dependency=%s\n' "${INSTALLED_DEPENDENCIES[@]}"
    } | awk '!seen[$0]++' >"$state_tmp"
    mv "$state_tmp" "$state_file"
fi

# --- PATH ---
step "Adding jwkit to your PATH"
add_path_block() {
    local rc="$1"
    local marker="# jwkit PATH (added by jwkit's install.sh)"
    [ -f "$rc" ] || touch "$rc"
    if grep -qF "$marker" "$rc" 2>/dev/null ||
       grep -qF "$JWKIT_HOME" "$rc" 2>/dev/null; then
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
        # Bash reads only the first existing login file.  Do not create a
        # .bash_profile when .profile already owns the user's login setup.
        login_rc=""
        for login_rc in "$HOME/.bash_profile" "$HOME/.bash_login" "$HOME/.profile"; do
            if [ -e "$login_rc" ]; then
                add_path_block "$login_rc"
                break
            fi
        done
        if [ -z "$login_rc" ] || [ ! -e "$login_rc" ]; then
            add_path_block "$HOME/.profile"
        fi
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
echo "Open a new terminal window, then try:"
c_bold "  slverse --help"
c_bold "  jwdl list"
echo ""
echo "For the interactive setup (languages, cache size, etc.), run:"
c_bold "  slverse setup"
echo ""
echo "To update jwkit later, run:"
c_bold "  jwkit-update"
