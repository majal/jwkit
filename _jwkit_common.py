"""_jwkit_common - shared helpers used by every top-level jwkit tool
(slverse, ffrife, jwdl, jwvideo-mux), loaded as a sibling module the same
way slverse already loads ffrife (SourceFileLoader, not a real import,
since these are standalone shebang scripts rather than a package).

Currently just the on-run auto-update check. Not jw.org-specific and not
tied to any one tool, so new shared cross-tool concerns belong here too.
"""
import json
import subprocess
import time
from pathlib import Path

JWKIT_CONFIG_DIR = Path.home() / ".config" / "jwkit"
JWKIT_CONFIG_FILE = JWKIT_CONFIG_DIR / "config.toml"
JWKIT_UPDATE_STATE_FILE = JWKIT_CONFIG_DIR / "update-state.json"

DEFAULT_JWKIT_CONFIG = {
    "auto_update": True,
    "auto_update_interval_hours": 24,
}


class ProgressETA:
    """Small shared rolling-rate ETA estimator for jwkit progress displays."""
    def __init__(self, total, window_seconds=30.0):
        self.total = total
        self.window_seconds = window_seconds
        self.samples = []

    def update(self, completed, now=None):
        now = time.time() if now is None else now
        self.samples.append((now, completed))
        self.samples = [sample for sample in self.samples if now - sample[0] <= self.window_seconds]
        if len(self.samples) < 2 or completed <= self.samples[0][1]:
            return None
        elapsed = now - self.samples[0][0]
        if elapsed <= 0:
            return None
        rate = (completed - self.samples[0][1]) / elapsed
        return max(0.0, (self.total - completed) / rate) if rate > 0 else None


def load_jwkit_config():
    """The shared, repo-wide jwkit config - separate from each tool's own
    ~/.config/jwkit/<tool>/config.*, since auto_update applies to the
    whole install, not any one tool."""
    config = dict(DEFAULT_JWKIT_CONFIG)
    if not JWKIT_CONFIG_FILE.exists():
        return config
    try:
        for line in JWKIT_CONFIG_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k == "auto_update":
                config["auto_update"] = v.lower() in ("true", "1", "yes")
            elif k == "auto_update_interval_hours":
                try:
                    config["auto_update_interval_hours"] = float(v)
                except ValueError:
                    pass
    except OSError:
        pass
    return config


def save_jwkit_config(config):
    JWKIT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(JWKIT_CONFIG_FILE, "w") as f:
        f.write(f"auto_update = {'true' if config.get('auto_update', True) else 'false'}\n")
        f.write(f"auto_update_interval_hours = {config.get('auto_update_interval_hours', 24)}\n")


def _read_last_checked():
    if not JWKIT_UPDATE_STATE_FILE.exists():
        return 0.0
    try:
        return float(json.loads(JWKIT_UPDATE_STATE_FILE.read_text()).get("last_checked", 0.0))
    except (OSError, ValueError, json.JSONDecodeError):
        return 0.0


def _write_last_checked(when):
    JWKIT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    JWKIT_UPDATE_STATE_FILE.write_text(json.dumps({"last_checked": when}))


def _git_fast_forward_update(root):
    """Only ever fast-forwards - never discards a local edit someone made
    to their own checkout. Returns a short status string for the "updated"
    message, or None if nothing changed (already current, offline, or a
    real code change means it can't fast-forward)."""
    subprocess.run(
        ["git", "-C", str(root), "fetch", "-q", "origin"],
        timeout=8, check=True, capture_output=True,
    )
    local = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        timeout=5, check=True, capture_output=True, text=True,
    ).stdout.strip()

    remote_ref = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "origin/HEAD"],
        timeout=5, capture_output=True, text=True,
    )
    if remote_ref.returncode != 0:
        remote_ref = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "origin/main"],
            timeout=5, check=True, capture_output=True, text=True,
        )
    remote = remote_ref.stdout.strip()

    if local == remote:
        return None

    merged = subprocess.run(
        ["git", "-C", str(root), "merge", "--ff-only", remote],
        timeout=8, capture_output=True, text=True,
    )
    if merged.returncode != 0:
        return None  # local edits or a history rewrite - don't force it, just skip quietly

    return f"{local[:7]} -> {remote[:7]}"


def maybe_auto_update(jwkit_root):
    """Call once, early, from each tool's main(). Checks at most once every
    auto_update_interval_hours (default 24) - resets the timer up front
    even on failure, so a bad connection doesn't retry (and pause) on
    every command for the rest of the day. Never raises: an update check
    must never break the actual command someone is trying to run."""
    try:
        config = load_jwkit_config()
        if not config.get("auto_update", True):
            return

        now = time.time()
        interval_seconds = config.get("auto_update_interval_hours", 24) * 3600
        if now - _read_last_checked() < interval_seconds:
            return
        _write_last_checked(now)

        if not (Path(jwkit_root) / ".git").exists():
            return  # tarball install (no git) - run install.sh/install.ps1 again, or jwkit-update, to refresh

        status = _git_fast_forward_update(jwkit_root)
        if status:
            print(f"jwkit updated ({status}) - takes effect next run.")
            print(f"(To turn this off: run 'slverse setup' again, or set auto_update = false in {JWKIT_CONFIG_FILE})")
    except Exception:
        pass
