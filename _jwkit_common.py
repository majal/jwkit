"""_jwkit_common - shared helpers used by every top-level jwkit tool
(slverse, ffrife, ffinpaint, jwdl, jwpl, jwvideo-mux), loaded as a sibling module the same
way slverse already loads ffrife (SourceFileLoader, not a real import,
since these are standalone shebang scripts rather than a package).

Currently just the on-run auto-update check. Not jw.org-specific and not
tied to any one tool, so new shared cross-tool concerns belong here too.
"""
import datetime
import json
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

JWKIT_CONFIG_DIR = Path.home() / ".config" / "jwkit"
JWKIT_CONFIG_FILE = JWKIT_CONFIG_DIR / "config.toml"
JWKIT_UPDATE_STATE_FILE = JWKIT_CONFIG_DIR / "update-state.json"

DEFAULT_JWKIT_CONFIG = {
    "auto_update": True,
    "auto_update_interval_hours": 24,
    "color_output": "auto",  # auto (color on a real terminal, off when piped/redirected or NO_COLOR is set), always, never
    "on_output_exists": "ask",  # ask, overwrite, rename, trash, fail - see resolve_output_conflict
    "on_output_exists_unattended": "rename",  # what "ask" falls back to with no TTY to prompt, a declined/timed-out prompt - never "ask" itself
    "overwrite_prompt_timeout": 20,  # seconds to wait for an "ask" answer before falling back to on_output_exists_unattended
}

_COLOR_CODES = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "cyan": "36"}


class Colorizer:
    """Shared across every jwkit tool - see resolve_color_enabled for how
    `enabled` gets decided (config, --color/--no-color, NO_COLOR, TTY).
    `c.green("text")` wraps in ANSI when enabled, returns `text` unchanged
    otherwise, so call sites never need an if/else of their own."""
    def __init__(self, enabled):
        self.enabled = enabled

    def _wrap(self, code, text):
        return f"\033[{code}m{text}\033[0m" if self.enabled else str(text)

    def bold(self, text): return self._wrap(_COLOR_CODES["bold"], text)
    def dim(self, text): return self._wrap(_COLOR_CODES["dim"], text)
    def red(self, text): return self._wrap(_COLOR_CODES["red"], text)
    def green(self, text): return self._wrap(_COLOR_CODES["green"], text)
    def yellow(self, text): return self._wrap(_COLOR_CODES["yellow"], text)
    def cyan(self, text): return self._wrap(_COLOR_CODES["cyan"], text)

    def header(self, text):
        """Bold cyan - a major pipeline-step announcement (Interpolating,
        Encoding, Downloading, ...), distinct from green/yellow/red's
        success/warning/error meaning. One spot to change the look."""
        return self.bold(self.cyan(text))


def resolve_color_enabled(jwkit_config, cli_override=None):
    """cli_override (True/False from --color/--no-color) wins outright.
    Otherwise jwkit_config's color_output: always/never are explicit;
    "auto" (the default) follows NO_COLOR (https://no-color.org - any
    non-empty value disables) and whether stdout is actually a terminal
    (never emit escape codes into a pipe, a redirected file, or a log)."""
    if cli_override is not None:
        return cli_override
    setting = str((jwkit_config or {}).get("color_output", "auto")).strip().lower()
    if setting in ("always", "true", "yes", "1", "on"):
        return True
    if setting in ("never", "false", "no", "0", "off"):
        return False
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


_ENCODER_LIST_CACHE = {}
_RESOLVED_ENCODER_CACHE = {}
_ENCODER_FALLBACK_WARNED = set()

_CODEC_TIERS = ["av1", "hevc", "h264"]
AUTO_CRF_BY_CODEC = {"h264": "20", "hevc": "23", "av1": "30"}
_HW_ENCODER_NAMES = {
    "nvenc": {"h264": "h264_nvenc", "hevc": "hevc_nvenc", "av1": "av1_nvenc"},
    "videotoolbox": {"h264": "h264_videotoolbox", "hevc": "hevc_videotoolbox", "av1": "av1_videotoolbox"},
    "qsv": {"h264": "h264_qsv", "hevc": "hevc_qsv", "av1": "av1_qsv"},
}
# libsvtav1 before libaom-av1: several times faster at comparable quality
# for the short clips these tools produce (see docs/slverse.md's codec
# comparison note).
_SW_ENCODER_NAMES = {"h264": ["libx264"], "hevc": ["libx265"], "av1": ["libsvtav1", "libaom-av1"]}


def _ffmpeg_encoders(ffmpeg_bin):
    if ffmpeg_bin not in _ENCODER_LIST_CACHE:
        try:
            result = subprocess.run([ffmpeg_bin, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=10)
            _ENCODER_LIST_CACHE[ffmpeg_bin] = result.stdout
        except Exception:
            _ENCODER_LIST_CACHE[ffmpeg_bin] = ""
    return _ENCODER_LIST_CACHE[ffmpeg_bin]


def ffmpeg_has_encoder(ffmpeg_bin, encoder_name):
    return encoder_name in _ffmpeg_encoders(ffmpeg_bin)


def resolve_video_encoder(ffmpeg_bin, hw, codec):
    """Walk the codec tier downward from `codec` (av1 -> hevc -> h264),
    trying the configured hardware encoder at each tier first and falling
    back to software - so "encode in av1" degrades gracefully on a
    machine/ffmpeg build that can't actually do av1 (e.g. Apple Silicon
    before M5 Pro/Max has no av1_videotoolbox - VideoToolbox's AV1 *decode*
    landed with A17 Pro/M3, but AV1 *encode* didn't until 2026's M5
    Pro/Max), instead of silently landing on h264 (the old behavior) or
    hard-failing. Never falls back UPWARD - requesting hevc never lands on
    av1. Returns (actual_codec, vcodec_name, used_hw); actual_codec differs
    from `codec` only when nothing at or below its tier was available.
    Cached per (ffmpeg_bin, hw, codec) - deterministic for one process, and
    this may be called once per language in a parallel multi-language run."""
    cache_key = (ffmpeg_bin, hw, codec)
    if cache_key in _RESOLVED_ENCODER_CACHE:
        return _RESOLVED_ENCODER_CACHE[cache_key]

    start = _CODEC_TIERS.index(codec) if codec in _CODEC_TIERS else len(_CODEC_TIERS) - 1
    resolved = None
    for tier_codec in _CODEC_TIERS[start:]:
        hw_name = _HW_ENCODER_NAMES.get(hw, {}).get(tier_codec)
        if hw_name and ffmpeg_has_encoder(ffmpeg_bin, hw_name):
            resolved = (tier_codec, hw_name, True)
            break
        sw_name = next((name for name in _SW_ENCODER_NAMES[tier_codec] if ffmpeg_has_encoder(ffmpeg_bin, name)), None)
        if sw_name:
            resolved = (tier_codec, sw_name, False)
            break
    if resolved is None:
        # Nothing detected at all (e.g. the -encoders probe itself failed) -
        # land on plain libx264 rather than ever leaving build_encode_args
        # with no -c:v.
        resolved = ("h264", "libx264", False)
    _RESOLVED_ENCODER_CACHE[cache_key] = resolved
    return resolved


def format_eta(eta_seconds):
    """'40s' rather than '0m 40s' - the minutes component only shows up
    once there actually is one. Shared by slverse's and ffrife's
    print_time_progress/print_count_progress (previously three copies of
    the same f-string, all with the same '0m 40s' wart)."""
    minutes, seconds = int(eta_seconds // 60), int(eta_seconds % 60)
    return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"


def nvenc_quality_from_crf(crf):
    # nvenc has no crf; -cq on the same 0-51 scale is the closest analogue.
    return crf


def videotoolbox_quality_from_crf(crf):
    # videotoolbox has no crf; -q:v is a 0-100 "higher is better" scale with
    # no fixed formula, so this is a rough inverse mapping, not an exact
    # match. A flat "100 - crf" keeps crf 20 at q:v 80, close to what
    # -crf 20 -preset slow actually looks like on libx264.
    try:
        crf_val = float(crf)
    except ValueError:
        crf_val = 20
    return max(1, min(100, round(100 - crf_val)))


def _encode_args_for(hw, codec, vcodec, used_hw, crf, preset):
    """The actual -c:v/... argument shape for one specific, already-resolved
    (hw, codec, vcodec) combo - factored out of build_encode_args so
    run_encoder_benchmark can build args for combos it's explicitly testing
    without going through resolve_video_encoder's fallback-chain logic."""
    if used_hw and hw == "nvenc":
        args = ["-c:v", vcodec, "-preset", preset, "-cq", str(nvenc_quality_from_crf(crf))]
    elif used_hw and hw == "videotoolbox":
        args = ["-c:v", vcodec, "-q:v", str(videotoolbox_quality_from_crf(crf))]
    elif used_hw and hw == "qsv":
        args = ["-c:v", vcodec, "-preset", preset, "-global_quality", str(crf)]
    else:
        args = ["-c:v", vcodec, "-crf", str(crf), "-preset", ("6" if codec == "av1" and preset == "slow" else preset)]
        if codec == "av1" and vcodec == "libsvtav1":
            args += ["-svtav1-params", "tune=0"]
    return args + ["-pix_fmt", "yuv420p", "-movflags", "+faststart"]


def build_encode_args(ffmpeg_bin, config, notice=True):
    """Shared by slverse and ffrife (identical encode-quality logic, kept in
    one place instead of two copies that could drift). `notice` prints a
    one-line, once-per-(ffmpeg_bin,hw,codec) heads-up when the requested
    codec wasn't actually available and something lower in the tier was
    used instead - silence it for callers that already show their own
    status (e.g. a caller printing per-language progress)."""
    hw = config.get("hardware_encoder", "cpu")
    requested_codec = config.get("video_codec", "av1")
    actual_codec, vcodec, used_hw = resolve_video_encoder(ffmpeg_bin, hw, requested_codec)

    warn_key = (ffmpeg_bin, hw, requested_codec)
    if notice and actual_codec != requested_codec and warn_key not in _ENCODER_FALLBACK_WARNED:
        _ENCODER_FALLBACK_WARNED.add(warn_key)
        print(f"({requested_codec} isn't available via hardware_encoder={hw} on this machine - encoding as {actual_codec} instead)")

    crf = config.get("video_crf", "auto")
    if str(crf).strip().lower() == "auto":
        crf = AUTO_CRF_BY_CODEC.get(actual_codec, "20")
    preset = config.get("video_preset", "slow")

    return _encode_args_for(hw, actual_codec, vcodec, used_hw, crf, preset)


def benchmark_candidates(ffmpeg_bin):
    """Every (hw, codec, vcodec, used_hw) combo actually listed by this
    ffmpeg build - the starting point for run_encoder_benchmark. A listed
    encoder isn't a guarantee it'll work (h264_nvenc can be compiled in
    without an NVIDIA GPU/driver actually present) - the benchmark itself
    is the real test; this only avoids wasting time on combos ffmpeg
    doesn't even know about."""
    combos = []
    for codec in _CODEC_TIERS:
        for name in _SW_ENCODER_NAMES[codec]:
            if ffmpeg_has_encoder(ffmpeg_bin, name):
                combos.append(("cpu", codec, name, False))
                break  # one software encoder per codec is enough (libsvtav1 over libaom-av1)
    for hw, codec_map in _HW_ENCODER_NAMES.items():
        for codec, name in codec_map.items():
            if ffmpeg_has_encoder(ffmpeg_bin, name):
                combos.append((hw, codec, name, True))
    return combos


def measure_ssim(ffmpeg_bin, encoded_path, reference_path):
    """SSIM of `encoded_path` against `reference_path` (expected lossless
    or near-lossless) via ffmpeg's own ssim filter - the same metric used
    to validate the fade-timing/codec-default work this benchmark
    generalizes. Returns None if the filter didn't produce a parseable
    score (e.g. mismatched resolution/duration)."""
    cmd = [ffmpeg_bin, "-hide_banner", "-i", str(encoded_path), "-i", str(reference_path),
           "-lavfi", "[0:v][1:v]ssim", "-f", "null", "-"]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except Exception:
        return None
    match = re.search(r"All:([\d.]+)", result.stderr)
    return float(match.group(1)) if match else None


def run_encoder_benchmark(ffmpeg_bin, sample_path, candidates=None, crf_map=None, preset="slow", log=None):
    """Time + size + SSIM (vs. a lossless re-encode of the sample itself)
    for every candidate (hw, codec, vcodec, used_hw) combo, at every crf
    value given for that codec - real numbers for real hardware (and real
    quality targets), rather than one machine's one-time manual benchmark
    baked in as everyone's default (see slverse's old detect_hardware_encoder
    docstring, which this generalizes). `log(message)` is called once per
    (candidate, crf) pair as it's tried, if given, for progress feedback on
    what can be a slow (tens of seconds to a few minutes) operation.

    crf_map values may be a single crf (the old shape, one point per codec)
    or a list (a sweep - e.g. {"av1": ["24", "27", "30"]} to see where the
    size/quality tradeoff actually bends for this content, instead of
    guessing at one fixed value).

    Returns a list of dicts: {hw, codec, vcodec, crf, ok, seconds,
    size_bytes, ssim, error}. A candidate that fails to encode at all (hw
    claimed but not actually usable - the real "is this GPU/driver actually
    there" test) gets ok=False and an error string instead of raising."""
    candidates = candidates if candidates is not None else benchmark_candidates(ffmpeg_bin)
    crf_map = crf_map or dict(AUTO_CRF_BY_CODEC)
    crf_map = {codec: (vals if isinstance(vals, (list, tuple)) else [vals]) for codec, vals in crf_map.items()}
    results = []
    with tempfile.TemporaryDirectory(prefix="jwkit-bench-") as tmp_dir:
        tmp = Path(tmp_dir)
        reference = tmp / "reference.mp4"
        subprocess.run(
            [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", str(sample_path),
             "-c:v", "libx264", "-crf", "0", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(reference)],
            check=True, timeout=120,
        )
        for hw, codec, vcodec, used_hw in candidates:
            for crf in crf_map.get(codec, ["23"]):
                if log:
                    log(f"{hw}/{codec} crf={crf} ({vcodec})...")
                args = _encode_args_for(hw, codec, vcodec, used_hw, crf, preset)
                output = tmp / f"{hw}_{codec}_{crf}.mp4"
                start = time.time()
                try:
                    subprocess.run(
                        [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-y", "-i", str(sample_path)] + args + [str(output)],
                        check=True, capture_output=True, timeout=300,
                    )
                except Exception as exc:
                    results.append({"hw": hw, "codec": codec, "vcodec": vcodec, "crf": crf, "ok": False,
                                     "seconds": None, "size_bytes": None, "ssim": None, "error": str(exc)})
                    continue
                seconds = time.time() - start
                size_bytes = output.stat().st_size if output.exists() else 0
                ssim = measure_ssim(ffmpeg_bin, output, reference) if size_bytes else None
                results.append({"hw": hw, "codec": codec, "vcodec": vcodec, "crf": crf, "ok": True,
                                 "seconds": seconds, "size_bytes": size_bytes, "ssim": ssim, "error": None})
    return results


def format_benchmark_table(results):
    """Human-readable table for run_encoder_benchmark's results, successes
    sorted smallest-file-first (what most people optimize for once quality
    clears a reasonable bar), failures listed after."""
    ok = sorted((r for r in results if r["ok"]), key=lambda r: r["size_bytes"])
    failed = [r for r in results if not r["ok"]]
    lines = [f"{'hw':<12} {'codec':<6} {'crf':>4} {'time':>8} {'size':>10} {'ssim':>8}"]
    for r in ok:
        crf = r.get("crf", "")
        lines.append(f"{r['hw']:<12} {r['codec']:<6} {crf:>4} {r['seconds']:>7.1f}s {r['size_bytes']/1e6:>8.2f}MB {r['ssim']:>8.4f}" if r["ssim"] is not None
                      else f"{r['hw']:<12} {r['codec']:<6} {crf:>4} {r['seconds']:>7.1f}s {r['size_bytes']/1e6:>8.2f}MB {'n/a':>8}")
    for r in failed:
        lines.append(f"{r['hw']:<12} {r['codec']:<6} {r.get('crf', ''):>4} {'unavailable':>8}   ({r['error'].splitlines()[0][:60]})")
    return "\n".join(lines)


def recommend_from_benchmark(results, ssim_floor=0.98, size_tolerance=0.15):
    """Smallest file among combos clearing ssim_floor (0.98 - broadly
    considered visually-lossless-to-very-high-quality territory), falling
    back to the highest-SSIM combo if none clear it - but the absolute
    smallest is a bad tiebreaker once several combos are already this
    close: a crf sweep across codecs routinely lands two candidates within
    a few % of the same tiny file size, and picking whichever is smaller by
    noise-level margins while ignoring that it took 3x longer to encode
    isn't actually a better recommendation. Among everything within
    size_tolerance (15%) of the smallest file, the fastest one wins
    instead. Returns a result dict or None if every candidate failed
    outright."""
    ok = [r for r in results if r["ok"] and r["ssim"] is not None]
    if not ok:
        return None
    above_floor = [r for r in ok if r["ssim"] >= ssim_floor]
    pool = above_floor or ok
    if not above_floor:
        return max(pool, key=lambda r: r["ssim"])
    smallest = min(r["size_bytes"] for r in pool)
    near_smallest = [r for r in pool if r["size_bytes"] <= smallest * (1 + size_tolerance)]
    return min(near_smallest, key=lambda r: r["seconds"])


class ProgressETA:
    """Small shared rolling-rate ETA estimator for jwkit progress displays."""
    def __init__(self, total, window_seconds=30.0, warmup_seconds=10.0):
        self.total = total
        self.window_seconds = window_seconds
        self.warmup_seconds = warmup_seconds
        self.samples = []

    def update(self, completed, now=None):
        now = time.time() if now is None else now
        self.samples.append((now, completed))
        self.samples = [sample for sample in self.samples if now - sample[0] <= self.window_seconds]
        if len(self.samples) < 2 or now - self.samples[0][0] < self.warmup_seconds or completed <= self.samples[0][1]:
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
            elif k == "color_output":
                config["color_output"] = v
            elif k == "auto_update_interval_hours":
                try:
                    config["auto_update_interval_hours"] = float(v)
                except ValueError:
                    pass
            elif k == "on_output_exists":
                config["on_output_exists"] = v
            elif k == "on_output_exists_unattended":
                config["on_output_exists_unattended"] = v
            elif k == "overwrite_prompt_timeout":
                try:
                    config["overwrite_prompt_timeout"] = float(v)
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
        f.write(f"color_output = {config.get('color_output', 'auto')}\n")
        f.write(f"on_output_exists = {config.get('on_output_exists', 'ask')}\n")
        f.write(f"on_output_exists_unattended = {config.get('on_output_exists_unattended', 'rename')}\n")
        f.write(f"overwrite_prompt_timeout = {config.get('overwrite_prompt_timeout', 20)}\n")


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


# --- Shared ffmpeg/ffprobe binary resolution ---
# A stock Homebrew `ffmpeg` doesn't include freetype/fontconfig (no
# drawtext), so slverse/ffrife prefer an `ffmpeg-full`-style build when one
# exists. Available here so any tool that shells out to ffmpeg/ffprobe -
# not just the ones with their own drawtext overlay - can resolve the same
# way instead of hardcoding a plain "ffmpeg"/"ffprobe" PATH lookup.
FFMPEG_FULL_KEG_PATHS = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffmpeg-full",
    "/usr/local/opt/ffmpeg-full/bin/ffmpeg-full",
]
FFPROBE_FULL_KEG_PATHS = [
    "/opt/homebrew/opt/ffmpeg-full/bin/ffprobe-full",
    "/usr/local/opt/ffmpeg-full/bin/ffprobe-full",
]

def command_exists(cmd):
    return shutil.which(cmd) is not None

def ffmpeg_has_filter(ffmpeg_bin, filter_name):
    try:
        result = subprocess.run([ffmpeg_bin, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=10)
        return filter_name in result.stdout
    except Exception:
        return False

def resolve_ffmpeg_binary(config, require_filter=None):
    """config's ffmpeg_binary override wins if it exists on PATH; otherwise
    prefers ffmpeg-full over the stock ffmpeg. Pass require_filter (e.g.
    "drawtext") to skip a candidate build that lacks it - omit it for tools
    that don't apply ffmpeg filters themselves."""
    override = config.get("ffmpeg_binary")
    if override and command_exists(override):
        return override
    candidates = [c for c in [
        shutil.which("ffmpeg-full"),
        *[p for p in FFMPEG_FULL_KEG_PATHS if os.path.exists(p)],
        shutil.which("ffmpeg"),
    ] if c]
    if require_filter:
        for c in candidates:
            if ffmpeg_has_filter(c, require_filter):
                return c
    return candidates[0] if candidates else "ffmpeg"

def resolve_ffprobe_binary(config):
    override = config.get("ffprobe_binary")
    if override and command_exists(override):
        return override
    candidates = [c for c in [
        shutil.which("ffprobe-full"),
        *[p for p in FFPROBE_FULL_KEG_PATHS if os.path.exists(p)],
        shutil.which("ffprobe"),
    ] if c]
    return candidates[0] if candidates else "ffprobe"


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


# --- Size parsing (cache caps, etc.) ---
_SIZE_UNITS = {
    "": 1, "b": 1,
    "k": 1000, "m": 1000 ** 2, "g": 1000 ** 3, "t": 1000 ** 4, "p": 1000 ** 5, "e": 1000 ** 6,
    "ki": 1024, "mi": 1024 ** 2, "gi": 1024 ** 3, "ti": 1024 ** 4, "pi": 1024 ** 5, "ei": 1024 ** 6,
}


def parse_size(value):
    """Unix-style size string -> bytes (int). Bare number is bytes; K/M/G/T/P/E
    are decimal SI (x1000 per step, e.g. '1G' = 1_000_000_000); Ki/Mi/Gi/Ti/Pi/Ei
    are binary IEC (x1024 per step, e.g. '1Gi' = 1_073_741_824) - case-insensitive."""
    s = str(value).strip()
    m = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*([A-Za-z]*)", s)
    if not m:
        raise ValueError(f"not a size: {value!r} (expected e.g. '500M', '5G', '2Gi', or a bare byte count)")
    number, unit = m.group(1), m.group(2).lower()
    if unit not in _SIZE_UNITS:
        raise ValueError(f"unrecognized size unit {unit!r} in {value!r} (expected one of: K M G T P E, or Ki Mi Gi Ti Pi Ei)")
    return int(float(number) * _SIZE_UNITS[unit])


# --- Output-overwrite handling ---
def _numbered_alternative(path):
    """The first path.with_name('name (N).ext') that doesn't already exist."""
    path = Path(path)
    stem, suffix, n = path.stem, path.suffix, 1
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def _datetime_tagged(path):
    tag = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    path = Path(path)
    return path.with_name(f"{path.stem} (trashed {tag}){path.suffix}")


def _prompt_yes_no_with_timeout(prompt, timeout):
    """input() has no native cross-platform timeout, so a reader thread does
    the blocking read and the main thread waits on it with a timeout - works
    the same on POSIX and Windows (unlike a select()-based approach, which
    only works with sockets on Windows). Returns True/False, or None on
    timeout. The reader thread is a daemon: if it times out, it's left
    blocked on stdin forever, but that's fine since the process moves on and
    exits soon after either way."""
    result = queue.Queue(maxsize=1)

    def _read():
        try:
            result.put(input(prompt))
        except Exception:
            result.put(None)

    threading.Thread(target=_read, daemon=True).start()
    try:
        answer = result.get(timeout=timeout)
    except queue.Empty:
        return None
    if answer is None:
        return None
    return str(answer).strip().lower() in ("y", "yes")


def _move_to_trash_macos(path):
    # Finder resolves POSIX files relative to its own process, not the
    # caller's cwd. Always hand it an absolute path. Pass that path as an
    # AppleScript argv item rather than interpolating it into source code so
    # quotes and backslashes in filenames remain literal.
    path = Path(path).resolve()
    trash_dir = Path.home() / ".Trash"
    if trash_dir.exists() and (trash_dir / path.name).exists():
        path = path.rename(_datetime_tagged(path))
    script = 'on run argv\n tell application "Finder" to delete (POSIX file (item 1 of argv))\nend run'
    result = subprocess.run(["osascript", "-e", script, str(path)], capture_output=True, text=True)
    if result.returncode == 0:
        return

    # Finder automation may be unavailable in SSH/headless sessions or
    # denied by macOS Automation privacy. ~/.Trash is the same per-user
    # destination, so fall back to a direct move instead of crashing the
    # real media command. Preserve Finder's error if even that fails.
    try:
        trash_dir.mkdir(parents=True, exist_ok=True)
        dest = trash_dir / path.name
        if dest.exists():
            dest = _datetime_tagged(dest)
        shutil.move(str(path), str(dest))
    except Exception as fallback_error:
        detail = (result.stderr or result.stdout or "unknown osascript error").strip()
        raise OSError(f"could not move {path} to Trash: Finder: {detail}; fallback: {fallback_error}") from fallback_error


def _move_to_trash_linux(path):
    path = Path(path).resolve()
    trash_files_dir = Path.home() / ".local" / "share" / "Trash" / "files"
    if trash_files_dir.exists() and (trash_files_dir / path.name).exists():
        path = path.rename(_datetime_tagged(path))
    if shutil.which("gio"):
        result = subprocess.run(["gio", "trash", str(path)], capture_output=True, text=True)
        if result.returncode == 0:
            return
        # gio can be installed but unusable in a headless/SSH session.
        # Continue into the freedesktop.org implementation below.
    # Minimal freedesktop.org trash-spec fallback for boxes without gio
    # (plausible on a headless server - see AGENTS.md's unattended jobs).
    trash_info_dir = Path.home() / ".local" / "share" / "Trash" / "info"
    trash_files_dir.mkdir(parents=True, exist_ok=True)
    trash_info_dir.mkdir(parents=True, exist_ok=True)
    dest = trash_files_dir / path.name
    n = 1
    while dest.exists():
        dest = trash_files_dir / f"{path.stem} ({n}){path.suffix}"
        n += 1
    deletion_date = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    (trash_info_dir / f"{dest.name}.trashinfo").write_text(
        f"[Trash Info]\nPath={path.resolve()}\nDeletionDate={deletion_date}\n"
    )
    shutil.move(str(path), str(dest))


def _move_to_trash_windows(path):
    """Windows' Recycle Bin doesn't expose a simple listable "does this name
    already exist" the way macOS/Linux trash directories do (obfuscated
    per-SID storage), so datetime-tag unconditionally rather than trying to
    detect a collision first. Unverified on a real Windows machine - same
    caveat as install.ps1 (see AGENTS.md)."""
    import ctypes

    path = Path(path).resolve()
    path = path.rename(_datetime_tagged(path))
    SHFileOperationW = ctypes.windll.shell32.SHFileOperationW

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", ctypes.c_void_p),
            ("wFunc", ctypes.c_uint),
            ("pFrom", ctypes.c_wchar_p),
            ("pTo", ctypes.c_wchar_p),
            ("fFlags", ctypes.c_uint16),
            ("fAnyOperationsAborted", ctypes.c_int),
            ("hNameMappings", ctypes.c_void_p),
            ("lpszProgressTitle", ctypes.c_wchar_p),
        ]

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    op = SHFILEOPSTRUCTW(
        hwnd=None, wFunc=FO_DELETE, pFrom=str(path) + "\0",
        pTo=None, fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION,
    )
    result = SHFileOperationW(ctypes.byref(op))
    if result != 0 or op.fAnyOperationsAborted:
        raise OSError(f"SHFileOperationW failed (code {result}, aborted={bool(op.fAnyOperationsAborted)}) trashing {path}")


def _move_to_trash(path):
    system = platform.system()
    if system == "Darwin":
        _move_to_trash_macos(path)
    elif system == "Linux":
        _move_to_trash_linux(path)
    elif system == "Windows":
        _move_to_trash_windows(path)
    else:
        raise OSError(f"no trash support for platform {system!r}")


_VALID_ON_OUTPUT_EXISTS = {"overwrite", "rename", "trash", "fail"}


def resolve_output_conflict(path, jwkit_config=None):
    """Applies on_output_exists's policy when `path` already exists. Returns
    the Path to actually write to (unchanged for overwrite/trash, a fresh
    numbered sibling for rename), or None if the caller should skip this
    write entirely (declined, or policy=fail).

    'ask' only prompts when stdin is a real TTY; a background/cron
    invocation (no TTY), a declined prompt, or a prompt that times out after
    overwrite_prompt_timeout seconds all fall back to
    on_output_exists_unattended instead of hanging or silently clobbering."""
    path = Path(path)
    if not path.exists():
        return path

    jwkit_config = jwkit_config if jwkit_config is not None else load_jwkit_config()
    policy = str(jwkit_config.get("on_output_exists", "ask")).strip().lower()

    if policy == "ask":
        timeout = jwkit_config.get("overwrite_prompt_timeout", 20)
        if sys.stdin.isatty():
            answer = _prompt_yes_no_with_timeout(f"{path.name} already exists. Overwrite? [y/N] ", timeout)
            if answer is True:
                return path
            if answer is None:
                print(f"(no answer within {timeout}s - falling back to on_output_exists_unattended)")
        policy = str(jwkit_config.get("on_output_exists_unattended", "rename")).strip().lower()

    if policy not in _VALID_ON_OUTPUT_EXISTS:
        raise ValueError(f"invalid on_output_exists/on_output_exists_unattended value {policy!r} (expected one of: {', '.join(sorted(_VALID_ON_OUTPUT_EXISTS))})")

    if policy == "overwrite":
        return path
    if policy == "rename":
        return _numbered_alternative(path)
    if policy == "trash":
        _move_to_trash(path)
        return path
    print(f"{path} already exists (on_output_exists=fail) - not overwriting.")
    return None
