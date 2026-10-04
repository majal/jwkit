"""_jwkit_common - shared helpers used by every top-level jwkit tool
(slverse, ffrife, ffinpaint, jwdl, jwpl, jwvideo-mux), loaded as a sibling module the same
way slverse already loads ffrife (SourceFileLoader, not a real import,
since these are standalone shebang scripts rather than a package).

This is the canonical home for cross-tool configuration, update, output,
encoding, and progress behavior. It is not tied to any one tool.
"""
import base64
import datetime
import math
import json
import os
import platform
import queue
import re
import shlex
import shutil
import subprocess
import sys
import struct
import tempfile
import threading
import time
import uuid
import zlib
from pathlib import Path


CONFIG_ACTIONS = ("list", "get", "set", "path", "edit", "reset", "diff", "check")


def parse_time_seconds(value):
    """Parse SS.sss, MM:SS.sss, or HH:MM:SS.sss into seconds.

    Plain seconds may exceed 59. Colon forms use clock notation, so their
    minute and second fields must be below 60. Hours are intentionally
    unbounded for long media.
    """
    text = str(value).strip()
    parts = text.split(":")
    if not 1 <= len(parts) <= 3 or any(not part for part in parts):
        raise ValueError("must be SS.sss, MM:SS.sss, or HH:MM:SS.sss")
    try:
        numbers = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("must be SS.sss, MM:SS.sss, or HH:MM:SS.sss") from exc
    if any(not math.isfinite(number) or number < 0 for number in numbers):
        raise ValueError("must be a finite non-negative time")
    if len(numbers) > 1 and (numbers[-2] >= 60 or numbers[-1] >= 60):
        raise ValueError("minutes and seconds must be below 60 in clock notation")
    if len(numbers) == 1:
        return numbers[0]
    if len(numbers) == 2:
        return numbers[0] * 60 + numbers[1]
    return numbers[0] * 3600 + numbers[1] * 60 + numbers[2]


def parse_time_range(value):
    """Parse a time range while preserving legacy seconds-only ``A:B``.

    Because colons now belong inside clock timestamps, colon-bearing
    endpoints use ``START-END`` (for example ``1:02.5-2:03.75``). The old
    seconds-only ``3.5:10`` spelling remains accepted for compatibility.
    """
    text = str(value).strip()
    if "-" in text:
        if text.count("-") != 1:
            raise ValueError("must be START-END when either time contains a colon")
        start_text, end_text = text.split("-", 1)
    elif text.count(":") == 1:
        start_text, end_text = text.split(":", 1)
        if ":" in start_text or ":" in end_text:
            raise ValueError("must be START-END when either time contains a colon")
    else:
        raise ValueError("must be START-END; legacy seconds-only START:END is also accepted")
    start, end = parse_time_seconds(start_text), parse_time_seconds(end_text)
    if end <= start:
        raise ValueError("END must be greater than START")
    return start, end


def parse_auto_time_seconds(value):
    """Accept ``auto`` or normalize a human time to numeric seconds."""
    if str(value).strip().casefold() == "auto":
        return "auto"
    return f"{parse_time_seconds(value):g}"


def add_config_arguments(parser):
    """Give every jwkit tool the same config-management command surface."""
    parser.add_argument("action", choices=CONFIG_ACTIONS, nargs="?", default="list")
    parser.add_argument("key", nargs="?")
    parser.add_argument("value", nargs="?")


def parse_config_value(default, raw):
    if isinstance(default, bool):
        if str(raw).casefold() not in {"true", "false"}:
            raise ValueError("boolean value must be true or false")
        return str(raw).casefold() == "true"
    if isinstance(default, int):
        return int(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, list):
        return [part.strip() for part in str(raw).split(",") if part.strip()]
    return str(raw)


def format_config_value(value):
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    if isinstance(value, dict):
        return ",".join(f"{key}={item}" for key, item in sorted(value.items()))
    return str(value)


def run_config_command(
    *, tool, args, config, defaults, config_file, save_config,
    descriptions=None, parse_value=None, validate=None, check_extra=None,
):
    """Run the shared list/get/set/path/edit/reset/diff/check interface.

    Returns a process-style status code. Tool-specific parsers and validators
    remain injectable so sharing the operator interface does not erase useful
    type or domain validation.
    """
    descriptions = descriptions or {}
    parse_value = parse_value or (lambda key, raw: parse_config_value(defaults[key], raw))
    action, key, raw = args.action, args.key, args.value

    if action == "path":
        print(config_file)
        return 0
    if action == "edit":
        config_file = Path(config_file)
        if not config_file.exists():
            save_config(config)
        editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not editor:
            print(f"{tool}: set $VISUAL or $EDITOR to use 'config edit'", file=sys.stderr)
            return 2
        return subprocess.call([*shlex.split(editor), str(config_file)])
    if action in {"get", "set", "reset"}:
        if not key:
            print(f"{tool} config {action} requires KEY" + (" VALUE" if action == "set" else ""), file=sys.stderr)
            return 2
        if key not in defaults:
            print(f"{tool}: unknown config key: {key}", file=sys.stderr)
            return 2
    if action == "set":
        if raw is None:
            print(f"{tool} config set requires KEY VALUE", file=sys.stderr)
            return 2
        try:
            value = parse_value(key, raw)
        except (TypeError, ValueError) as exc:
            print(f"{tool}: invalid {key}: {exc}", file=sys.stderr)
            return 2
        if validate:
            error = validate(key, value)
            if error:
                print(f"{tool}: invalid {key}: {error}", file=sys.stderr)
                return 2
        config[key] = value
        save_config(config)
        print(f"Set {key} = {format_config_value(value)}")
        return 0
    if action == "reset":
        config[key] = defaults[key]
        save_config(config)
        print(f"Reset {key} = {format_config_value(defaults[key])}")
        return 0
    if action == "get":
        print(f"{key} = {format_config_value(config[key])}")
        if descriptions.get(key):
            print(f"  {descriptions[key]}")
        return 0
    if action == "diff":
        changed = [(key, config[key]) for key in defaults if config.get(key) != defaults[key]]
        if not changed:
            print("All settings use their defaults.")
        else:
            for changed_key, value in changed:
                print(f"{changed_key} = {format_config_value(value)}")
        return 0
    if action == "check":
        issues = []
        for unknown_key in sorted(set(config) - set(defaults)):
            issues.append(f"unknown config key: {unknown_key}")
        for check_key in defaults:
            if validate:
                error = validate(check_key, config.get(check_key))
                if error:
                    issues.append(f"{check_key}: {error}")
        if check_extra:
            issues.extend(check_extra(config))
        if issues:
            for issue in issues:
                print(f"ERROR: {issue}")
            return 2
        print(f"Configuration is valid: {config_file}")
        return 0
    for list_key in defaults:
        suffix = f"  # {descriptions[list_key]}" if descriptions.get(list_key) else ""
        print(f"{list_key} = {format_config_value(config[list_key])}{suffix}")
    return 0

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
    "provenance_mode": "embed",  # embed (inside the file), beside (<file>.jwkit.json), folder (in provenance_dir), none - see the Provenance records section
    "provenance_dir": "",  # for folder mode: one central folder; empty = a hidden .jwkit folder beside each file
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


# x264/x265's named preset ladder, slowest (best compression) to fastest.
# This is the scale every jwkit tool's `video_preset`/`--preset` is written
# in, because it's the one users already know - but it is NOT what every
# encoder actually accepts, which is what preset_args below exists to
# reconcile.
PRESET_LADDER = ["placebo", "veryslow", "slower", "slow", "medium", "fast",
                 "faster", "veryfast", "superfast", "ultrafast"]
# SVT-AV1 takes a number 0-13 (lower = slower/better) and rejects every one
# of those names outright - `-preset medium` on libsvtav1 is not a slower
# encode, it's a hard ffmpeg failure ("Unable to parse preset option value",
# exit 234), which is why only the literal "slow" used to work: it was the
# single name special-cased into "6". Everything else silently blew up the
# whole run on the default codec.
_SVTAV1_PRESET_BY_NAME = {"placebo": 1, "veryslow": 2, "slower": 4, "slow": 6, "medium": 8,
                          "fast": 9, "faster": 10, "veryfast": 11, "superfast": 12, "ultrafast": 13}
# libaom-av1 has no -preset option at all; it spells the same idea
# -cpu-used 0-8.
_AOM_CPU_USED_BY_NAME = {"placebo": 0, "veryslow": 1, "slower": 2, "slow": 3, "medium": 4,
                         "fast": 5, "faster": 6, "veryfast": 7, "superfast": 8, "ultrafast": 8}
_PRESET_WARNED = set()


def _preset_number(preset):
    """`preset` as an int if it's written as a plain number, else None."""
    try:
        return int(str(preset).strip())
    except (TypeError, ValueError):
        return None


def _nearest_preset_name(number):
    """Nearest PRESET_LADDER name to an SVT-AV1-scale number (0-13) - the
    reverse of _SVTAV1_PRESET_BY_NAME, for handing a numeric `video_preset`
    to an encoder that only speaks names (nvenc, notably)."""
    return min(_SVTAV1_PRESET_BY_NAME, key=lambda name: abs(_SVTAV1_PRESET_BY_NAME[name] - number))


def _preset_notice(message):
    if message not in _PRESET_WARNED:
        _PRESET_WARNED.add(message)
        print(message)


def preset_args(vcodec, preset, notice=True):
    """The `-preset`-equivalent arguments for `vcodec`, translating between
    the named x264/x265 ladder every jwkit tool's config is written in and
    whatever scale this particular encoder actually accepts.

    Returns a list (possibly empty - videotoolbox has no speed/quality
    preset knob at all). An unrecognized value is dropped with a one-line
    notice rather than passed through to fail the encode, since a bad
    `video_preset` should cost a default-speed encode, not the whole run."""
    preset = str(preset).strip()
    number = _preset_number(preset)
    name = preset.lower() if number is None else None
    if name is not None and name not in _SVTAV1_PRESET_BY_NAME:
        name = None  # unknown word: handled per-encoder below

    if vcodec == "libsvtav1":
        if number is not None:
            return ["-preset", str(max(0, min(13, number)))]
        if name is None:
            if notice:
                _preset_notice(f"(video_preset={preset!r} isn't a preset libsvtav1 understands - using its default instead)")
            return []
        return ["-preset", str(_SVTAV1_PRESET_BY_NAME[name])]

    if vcodec == "libaom-av1":
        # -cpu-used, not -preset: libaom-av1 has no -preset option, so the
        # old pass-through didn't just pick the wrong speed here, it made
        # ffmpeg reject the option outright.
        if number is not None:
            return ["-cpu-used", str(max(0, min(8, number)))]
        if name is None:
            if notice:
                _preset_notice(f"(video_preset={preset!r} isn't a preset libaom-av1 understands - using its default instead)")
            return []
        return ["-cpu-used", str(_AOM_CPU_USED_BY_NAME[name])]

    if vcodec.endswith("_videotoolbox"):
        return []  # quality is -q:v only; no speed preset exists

    # libx264/libx265/nvenc/qsv all speak the named ladder. x264/x265 also
    # accept a bare number (an index into their own preset list), but nvenc
    # does not - normalize a numeric value (someone's AV1-scale setting,
    # reaching a fallback encoder) to the nearest name so it works on all
    # of them rather than only two.
    if number is not None:
        return ["-preset", _nearest_preset_name(number)]
    if name is None:
        # Not on the shared ladder, but x264/x265 have their own extra
        # names (e.g. tuned builds) - pass it through and let the encoder
        # be the judge, which is the historical behavior for these codecs.
        return ["-preset", preset]
    return ["-preset", name]


def _encode_args_for(hw, codec, vcodec, used_hw, crf, preset):
    """The actual -c:v/... argument shape for one specific, already-resolved
    (hw, codec, vcodec) combo - factored out of build_encode_args so
    run_encoder_benchmark can build args for combos it's explicitly testing
    without going through resolve_video_encoder's fallback-chain logic."""
    speed = preset_args(vcodec, preset)
    if used_hw and hw == "nvenc":
        args = ["-c:v", vcodec] + speed + ["-cq", str(nvenc_quality_from_crf(crf))]
    elif used_hw and hw == "videotoolbox":
        args = ["-c:v", vcodec, "-q:v", str(videotoolbox_quality_from_crf(crf))]
    elif used_hw and hw == "qsv":
        args = ["-c:v", vcodec] + speed + ["-global_quality", str(crf)]
    else:
        args = ["-c:v", vcodec, "-crf", str(crf)] + speed
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
            elif k in ("provenance_mode", "provenance_dir"):
                config[k] = v
            elif k == "overwrite_prompt_timeout":
                try:
                    config["overwrite_prompt_timeout"] = parse_time_seconds(v)
                except ValueError:
                    pass
    except OSError:
        pass
    return config


def _config_value_text(value):
    return ("true" if value else "false") if isinstance(value, bool) else str(value).strip()


def config_overrides(config, defaults, skip=()):
    """The part of `config` worth writing back to disk: every key whose value
    differs from `defaults`, plus keys `defaults` doesn't know (kept so
    `config check` can report them instead of them vanishing silently).
    Runtime-only keys (a leading underscore, or anything in `skip`) are
    never persisted.

    Every tool saves through this rather than dumping its whole merged
    config: a full dump pins each default as it stood the day the file was
    first written, so an improved default never reaches an existing install
    (seen in practice with ffrife's scene-detection defaults)."""
    return {key: value for key, value in config.items()
            if not str(key).startswith("_") and key not in skip
            and (key not in defaults or not _config_values_equal(value, defaults[key]))}


def _config_values_equal(value, default):
    """Equal as config values: "true" == True, and "24" == 24 == 24.0 (a
    loader that parses numbers must not make every default look changed)."""
    left, right = _config_value_text(value), _config_value_text(default)
    if left == right:
        return True
    if isinstance(value, bool) or isinstance(default, bool):
        return False
    try:
        return float(left) == float(right)
    except ValueError:
        return False


def save_jwkit_config(config):
    JWKIT_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    known = {key: config.get(key, default) for key, default in DEFAULT_JWKIT_CONFIG.items()}
    with open(JWKIT_CONFIG_FILE, "w") as f:
        for key, value in config_overrides(known, DEFAULT_JWKIT_CONFIG).items():
            f.write(f"{key} = {_config_value_text(value)}\n")


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


# ---------------------------------------------------------------------------
# Provenance records
#
# The record of *how* a file was made (exact command, source URL + jw.org's
# own MD5 for the source, tool commit, interpolation engine) is a JSON
# document. `provenance_mode` (shared config / `--provenance`) picks where it
# lives:
#
#   embed   (default) inside the media file itself, so it can't be separated
#           from the video. MP4/MOV/M4V get a self-describing top-level `uuid`
#           box appended after the media data (no remux, nothing else in the
#           file changes; every player skips unknown boxes). Matroska/WebM get
#           a native global tag, `jwkit_provenance`, via a stream-copy remux;
#           MP3/FLAC/Ogg/Opus get the same tag (an ID3 TXXX frame / a Vorbis
#           comment). Every remux is verified (packet hash, duration, stream
#           layout) before it replaces the file. Other containers (AVI, WAV,
#           TS, images, ...) fall back to `beside`.
#           Why not ffmpeg's `-movflags +use_metadata_tags`: it moves *all* MP4
#           tags into the `mdta` namespace, which hides the title/comment in
#           Finder/QuickTime/AVFoundation.
#   beside  `<name>.<ext>.jwkit.json` next to the media file.
#   folder  the same file kept in `provenance_dir`: a hidden `.jwkit` folder
#           beside the media when that is empty, else one central folder.
#   none    nothing is recorded.
#
# A container that can't carry the record (or an embed that fails) falls back
# to `beside` rather than losing it. A record bigger than
# PROVENANCE_COMPRESS_OVER is stored as zlib+base64 (`jwkit-z1:` prefix);
# readers accept both forms. An embedded record can't hold the output's own
# file hash (it would change the file), so it carries `output.av_sha256`, the
# hash of the video/audio packets, which metadata edits don't change.
# `slverse rebuild` reads these to re-create a clip and to notice that jw.org
# replaced its source; other tools can write the same schema.
# ---------------------------------------------------------------------------

JWKIT_REPO_URL = "https://github.com/majal/jwkit"
PROVENANCE_SUFFIX = ".jwkit.json"
PROVENANCE_SCHEMA = "jwkit-provenance/1"
PROVENANCE_MODES = ("embed", "beside", "folder", "none")
PROVENANCE_TAG = "jwkit_provenance"
PROVENANCE_FOLDER_NAME = ".jwkit"
PROVENANCE_COMPRESS_OVER = 8192
PROVENANCE_BOX_UUID = uuid.uuid5(uuid.NAMESPACE_URL, JWKIT_REPO_URL + "/provenance").bytes
_COMPRESSED_PREFIX = "jwkit-z1:"
_ISO_EXTENSIONS = {".mp4", ".m4v", ".mov", ".m4a"}
_MATROSKA_EXTENSIONS = {".mkv", ".mka", ".webm"}
_TAG_EXTENSIONS = {".mp3", ".flac", ".ogg", ".oga", ".opus"}
MEDIA_EXTENSIONS = tuple(sorted(_ISO_EXTENSIONS | _MATROSKA_EXTENSIONS | _TAG_EXTENSIONS))
_COMMIT_CACHE = {}


def tool_advert(tool):
    """One line crediting the tool, safe for an MP4 `comment` tag."""
    return f"Made with {tool} - {JWKIT_REPO_URL}/blob/main/{tool}"


def jwkit_commit(root):
    """Short commit of the checkout the running tool came from, '+dirty'
    when it has uncommitted edits, or 'unknown' for a tarball install."""
    root = str(root)
    if root not in _COMMIT_CACHE:
        try:
            head = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"], capture_output=True, text=True, timeout=10)
            dirty = subprocess.run(["git", "-C", root, "status", "--porcelain", "--untracked-files=no"], capture_output=True, text=True, timeout=10)
            commit = head.stdout.strip() or "unknown"
            if commit != "unknown" and dirty.stdout.strip():
                commit += "+dirty"
        except (OSError, subprocess.SubprocessError):
            commit = "unknown"
        _COMMIT_CACHE[root] = commit
    return _COMMIT_CACHE[root]


def file_digest(path, algorithm="sha256"):
    import hashlib
    digest = hashlib.new(algorithm)
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def media_packets_digest(path, ffmpeg=None):
    """sha256 over the video + audio packets only (`ffmpeg -c copy -f hash`),
    so it survives any metadata/box edit. None when it can't be computed."""
    try:
        result = subprocess.run(
            [ffmpeg or shutil.which("ffmpeg") or "ffmpeg", "-v", "error", "-nostdin", "-i", str(path),
             "-map", "0:v?", "-map", "0:a?", "-c", "copy", "-f", "hash", "-hash", "sha256", "-"],
            capture_output=True, text=True, timeout=3600)
    except (OSError, subprocess.SubprocessError):
        return None
    line = result.stdout.strip()
    return line.split("=", 1)[1] if result.returncode == 0 and line.startswith("SHA256=") else None


# -- record <-> text ---------------------------------------------------------

def encode_provenance(record):
    """Compact JSON text; zlib+base64 behind a `jwkit-z1:` prefix when large."""
    text = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    if len(text.encode("utf-8")) > PROVENANCE_COMPRESS_OVER:
        text = _COMPRESSED_PREFIX + base64.b64encode(zlib.compress(text.encode("utf-8"), 9)).decode("ascii")
    return text


def decode_provenance(text):
    """The record dict for text from encode_provenance (or a pretty-printed
    sidecar), or None when it isn't a jwkit provenance record."""
    try:
        text = text.strip()
        if text.startswith(_COMPRESSED_PREFIX):
            text = zlib.decompress(base64.b64decode(text[len(_COMPRESSED_PREFIX):])).decode("utf-8")
        record = json.loads(text)
    except (ValueError, TypeError, OSError, zlib.error):
        return None
    return record if isinstance(record, dict) and str(record.get("schema", "")).startswith("jwkit-provenance/") else None


# -- MP4 / MOV: a trailing `uuid` box ---------------------------------------

def _iso_boxes(handle, size):
    """Top-level (offset, size, type, header_size) boxes of an ISO-BMFF file.
    Raises ValueError for anything that isn't a clean box chain ending exactly
    at EOF (so appending a box is safe)."""
    position, first = 0, True
    while position < size:
        handle.seek(position)
        header = handle.read(16)
        if len(header) < 8:
            raise ValueError("truncated box header")
        box_size, kind = struct.unpack(">I4s", header[:8])
        header_size = 8
        if box_size == 1:
            if len(header) < 16:
                raise ValueError("truncated box header")
            box_size, header_size = struct.unpack(">Q", header[8:16])[0], 16
        elif box_size == 0:
            raise ValueError("open-ended box")
        if box_size < header_size or position + box_size > size:
            raise ValueError("malformed box")
        if first and kind not in (b"ftyp", b"moov", b"mdat", b"wide", b"free", b"skip", b"pnot"):
            raise ValueError("not an ISO-BMFF file")
        first = False
        yield position, box_size, kind, header_size
        position += box_size


def _iso_find_record(path):
    size = Path(path).stat().st_size
    with open(path, "rb") as handle:
        found = None
        for position, box_size, kind, header_size in _iso_boxes(handle, size):
            if kind == b"uuid" and box_size >= header_size + 16:
                handle.seek(position + header_size)
                if handle.read(16) == PROVENANCE_BOX_UUID:
                    found = (position, box_size, header_size)
        if found is None:
            return None
        position, box_size, header_size = found
        handle.seek(position + header_size + 16)
        return handle.read(box_size - header_size - 16).decode("utf-8", "replace")


def _iso_write_record(path, text):
    """Replace (or add) our trailing uuid box; text=None just removes it."""
    path = Path(path)
    size = path.stat().st_size
    with open(path, "rb") as handle:
        ours = []
        for position, box_size, kind, header_size in _iso_boxes(handle, size):
            if kind == b"uuid" and box_size >= header_size + 16:
                handle.seek(position + header_size)
                if handle.read(16) == PROVENANCE_BOX_UUID:
                    ours.append((position, box_size))
    new_box = b""
    if text is not None:
        payload = text.encode("utf-8")
        new_box = struct.pack(">I4s", 8 + 16 + len(payload), b"uuid") + PROVENANCE_BOX_UUID + payload
    if not ours:
        if new_box:
            with open(path, "r+b") as handle:
                handle.seek(0, 2)
                try:
                    handle.write(new_box)
                    handle.flush()
                    os.fsync(handle.fileno())
                except OSError:
                    handle.truncate(size)
                    raise
        return
    tail_start = ours[0][0]
    if size - tail_start == sum(box_size for _, box_size in ours):  # ours are the file's last boxes
        with open(path, "r+b") as handle:
            handle.truncate(tail_start)
            handle.seek(0, 2)
            handle.write(new_box)
        return
    tmp = path.with_name(path.name + ".jwkit-tmp")  # something was appended after our box: rewrite without it
    try:
        with open(path, "rb") as src, open(tmp, "wb") as dst:
            cursor = 0
            for position, box_size in ours:
                src.seek(cursor)
                shutil.copyfileobj(_limited(src, position - cursor), dst)
                cursor = position + box_size
            src.seek(cursor)
            shutil.copyfileobj(src, dst)
            dst.write(new_box)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class _limited:
    def __init__(self, handle, remaining):
        self.handle, self.remaining = handle, remaining

    def read(self, count=-1):
        count = self.remaining if count is None or count < 0 else min(count, self.remaining)
        data = self.handle.read(count)
        self.remaining -= len(data)
        return data


# -- Matroska / WebM / tag-capable audio: a global tag ------------------------

def _ffmpeg_bin(ffmpeg):
    return ffmpeg or shutil.which("ffmpeg") or "ffmpeg"


def _ffprobe_bin(ffprobe):
    return ffprobe or shutil.which("ffprobe") or "ffprobe"


def container_kind(path):
    """How `path` can carry an embedded record: "iso" (MP4 family: a uuid
    box), "matroska" (Matroska/WebM: a global tag, cover art preserved),
    "tags" (audio containers with free-form tags: MP3/FLAC/Ogg/Opus), or None
    (anything else, e.g. AVI/WAV/TS/images - those get a sidecar)."""
    suffix = Path(path).suffix.lower()
    if suffix in _ISO_EXTENSIONS:
        return "iso"
    if suffix in _MATROSKA_EXTENSIONS:
        return "matroska"
    if suffix in _TAG_EXTENSIONS:
        return "tags"
    return None


def _probe_json(path, ffprobe=None, *args):
    result = subprocess.run([_ffprobe_bin(ffprobe), "-v", "error", *args, "-of", "json", str(path)],
                            capture_output=True, text=True, timeout=300)
    return json.loads(result.stdout or "{}")


def _tag_text(path, ffprobe=None):
    """The embedded tag's text. Vorbis comments (Ogg/Opus) surface as stream
    tags rather than format tags, so both are searched."""
    try:
        info = _probe_json(path, ffprobe, "-show_entries", "format_tags:stream_tags")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    candidates = [info.get("format", {}).get("tags", {})] + [stream.get("tags", {}) for stream in info.get("streams", [])]
    for tags in candidates:
        for key, value in (tags or {}).items():
            if key.lower() == PROVENANCE_TAG:
                return value
    return None


def _stream_layout(path, ffprobe=None):
    """(format duration, sorted per-stream signature, attached-picture streams)
    for a file: what a faithful stream-copy remux must leave unchanged."""
    info = _probe_json(path, ffprobe, "-show_entries",
                       "format=duration:stream=index,codec_type,codec_name,start_time:stream_disposition=attached_pic:stream_tags")
    streams, pictures = [], []
    for stream in info.get("streams", []):
        tags = {key.lower(): value for key, value in (stream.get("tags") or {}).items()}
        attached = bool((stream.get("disposition") or {}).get("attached_pic"))
        start = stream.get("start_time")
        streams.append((stream.get("codec_type"), stream.get("codec_name"), f"{float(start):.3f}" if start not in (None, "N/A") else None, attached))
        if attached:
            pictures.append((stream["index"], tags.get("filename") or "cover", tags.get("mimetype") or "image/png"))
    duration = info.get("format", {}).get("duration")
    return (float(duration) if duration not in (None, "N/A") else None), sorted(streams, key=str), pictures


def _layouts_match(before, after):
    (d1, s1, _), (d2, s2, _) = before, after
    if s1 != s2:
        return False
    return d1 is None or d2 is None or abs(d1 - d2) <= 0.02


def _remux_write_tag(path, text, ffmpeg=None, ffprobe=None, verify=True):
    """Stream-copy remux that sets (text) or clears (None) the global tag.

    ffmpeg's defaults aren't a faithful copy of a Matroska file, so this
    corrects two: `-avoid_negative_ts disabled` keeps stream start times, and
    an attached picture (cover art, which `-map 0` would turn into a plain
    video track) is pulled out and re-attached with `-attach`, the way
    jwvideo-mux wrote it. Unless verify=False, the audio/video packet hash,
    duration and per-stream layout must match the original or nothing is
    replaced."""
    path = Path(path)
    ffmpeg = _ffmpeg_bin(ffmpeg)
    matroska = container_kind(path) == "matroska"
    tmp = path.with_name(f"{path.stem}.jwkit-tmp{path.suffix}")
    before = media_packets_digest(path, ffmpeg)
    layout = _stream_layout(path, ffprobe)
    pictures = layout[2] if matroska else []
    scratch = Path(tempfile.mkdtemp(prefix="jwkit-art-"))
    try:
        command = [ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(path)]
        maps, extras = ["-map", "0"], []
        for number, (index, filename, mime) in enumerate(pictures):
            art = scratch / f"art{number}"
            grabbed = subprocess.run([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", str(path), "-map", f"0:{index}", "-c", "copy", "-frames:v", "1", "-f", "image2", str(art)],
                                     capture_output=True, text=True, timeout=300)
            if grabbed.returncode != 0 or not art.exists():
                raise RuntimeError(f"couldn't extract the cover art (stream {index})")
            command += ["-attach", str(art)]
            maps += ["-map", f"-0:{index}"]
            extras += [f"-metadata:s:t:{number}", f"mimetype={mime}", f"-metadata:s:t:{number}", f"filename={filename}"]
        command += maps + ["-c", "copy", "-avoid_negative_ts", "disabled", "-map_metadata", "0", "-map_chapters", "0"] + extras
        command += ["-metadata", f"{PROVENANCE_TAG}={text or ''}"]
        if container_kind(path) == "tags":  # Vorbis comments live on the stream: a stale copy there would win over the new global tag
            command += ["-metadata:s:a:0", f"{PROVENANCE_TAG}={text or ''}"]
        command.append(str(tmp))
        result = subprocess.run(command, capture_output=True, text=True, timeout=7200)
        if result.returncode != 0 or not tmp.exists():
            raise RuntimeError((result.stderr or "ffmpeg remux failed").strip().splitlines()[-1])
        if verify:
            if before is not None and media_packets_digest(tmp, ffmpeg) != before:
                raise RuntimeError("remuxed streams differ from the original")
            if not _layouts_match(layout, _stream_layout(tmp, ffprobe)):
                raise RuntimeError("remuxed duration or stream layout differs from the original")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
        shutil.rmtree(scratch, ignore_errors=True)


def _embedded_text(path, ffprobe=None):
    kind = container_kind(path)
    if kind == "iso":
        return _iso_find_record(path)
    if kind in ("matroska", "tags"):
        return _tag_text(path, ffprobe)
    return None


def _embed_text(path, text, ffmpeg=None, ffprobe=None):
    """Write (text) or clear (None) the embedded record; ValueError if the
    container can't carry one."""
    kind = container_kind(path)
    if kind == "iso":
        _iso_write_record(path, text)
    elif kind in ("matroska", "tags"):
        _remux_write_tag(path, text, ffmpeg, ffprobe)
    else:
        raise ValueError(f"{Path(path).suffix or 'this'} container can't carry an embedded record")


# -- what a record says about the output -------------------------------------

_ENVIRONMENT_CACHE = {}


def environment_info(ffmpeg=None):
    """Versions that shaped the output: ffmpeg, OS, Python (no hostnames)."""
    ffmpeg = _ffmpeg_bin(ffmpeg)
    if ffmpeg not in _ENVIRONMENT_CACHE:
        version = None
        try:
            first = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, timeout=30).stdout.splitlines()[0]
            version = first.split()[2] if first.startswith("ffmpeg version") else first
        except (OSError, subprocess.SubprocessError, IndexError):
            pass
        _ENVIRONMENT_CACHE[ffmpeg] = {"ffmpeg": version, "platform": f"{platform.system()} {platform.release()} {platform.machine()}",
                                      "python": platform.python_version()}
    return dict(_ENVIRONMENT_CACHE[ffmpeg])


def media_summary(path, ffprobe=None):
    """Compact description of a media file: format, duration, and each stream."""
    try:
        info = _probe_json(path, ffprobe, "-show_entries",
                           "format=format_name,duration,bit_rate:stream=codec_type,codec_name,width,height,avg_frame_rate,channels,sample_rate:stream_tags=language,title")
    except (OSError, subprocess.SubprocessError, ValueError):
        return {}
    summary = {}
    fmt = info.get("format", {})
    if fmt.get("format_name"):
        summary["format"] = fmt["format_name"]
    if fmt.get("duration") not in (None, "N/A"):
        summary["duration"] = round(float(fmt["duration"]), 3)
    streams = []
    for stream in info.get("streams", []):
        item = {"type": stream.get("codec_type"), "codec": stream.get("codec_name")}
        tags = {key.lower(): value for key, value in (stream.get("tags") or {}).items()}
        if stream.get("codec_type") == "video":
            item["size"] = f"{stream.get('width')}x{stream.get('height')}"
            rate = stream.get("avg_frame_rate", "0/0")
            try:
                num, den = rate.split("/")
                if float(den):
                    item["fps"] = round(float(num) / float(den), 3)
            except ValueError:
                pass
        elif stream.get("codec_type") == "audio":
            item.update({key: stream[key] for key in ("channels", "sample_rate") if stream.get(key)})
        for key in ("language", "title"):
            if tags.get(key):
                item[key] = tags[key]
        streams.append(item)
    if streams:
        summary["streams"] = streams
    return summary


# -- source / record helpers for the tools -----------------------------------

JW_MEDIA_NAME = re.compile(r"^(?:\d+(?:-opt)?\s+)?(?:.*?\s-\s)?(?P<pub>[A-Za-z0-9-]+)_(?P<lang>[A-Z]+)_(?P<track>\d+)_r(?P<res>\d+)P(?![A-Za-z0-9])")


def command_line(tool, argv):
    return " ".join([tool] + [shlex.quote(str(item)) for item in argv])


def describe_file(path, jwkit_config=None, ffprobe=None, hash_input=True):
    """A record entry for a file a tool read: name, size, md5 (jw.org publishes
    md5s for its media, so a later check can tell whether it replaced the
    file), the jw.org publication/language/track when the name follows jw.org's
    pattern, and - when that file carries a provenance record of its own - who
    made it and how (`made_by`), so chains (ffrife -> jwvideo-mux) stay traceable."""
    path = Path(path)
    entry = {"file": path.name, "path": str(path.resolve())}
    try:
        entry["size"] = path.stat().st_size
        if hash_input:
            entry["checksum"], entry["checksum_algorithm"] = file_digest(path, "md5"), "md5"
    except OSError:
        pass
    named = JW_MEDIA_NAME.match(path.name)
    if named:
        entry["jw_org"] = {"publication": named["pub"], "language": named["lang"], "track": int(named["track"]), "resolution": f"{named['res']}p"}
    try:
        upstream = read_provenance(path, jwkit_config, ffprobe)
    except Exception:  # noqa: BLE001 - a broken input record must not stop the output's own
        upstream = None
    if upstream:
        entry["made_by"] = {"tool": upstream.get("tool"), "tool_commit": upstream.get("tool_commit"),
                            "created_at": upstream.get("created_at"), "command": (upstream.get("rebuild") or {}).get("command"),
                            "source_checksum": (upstream.get("source") or {}).get("checksum")}
    return entry


def base_record(tool, root, argv, **fields):
    """The common skeleton of a record: tool identity (name, commit, URL),
    the command that reproduces the output, plus the tool-specific fields."""
    record = {
        "tool": tool,
        "tool_commit": jwkit_commit(root),
        "tool_url": f"{JWKIT_REPO_URL}/blob/main/{tool}",
        "rebuild": {"argv": [str(item) for item in argv], "command": command_line(tool, argv)},
        "advert": tool_advert(tool),
    }
    record.update(fields)
    return record


def record_output(output, tool, root, argv, jwkit_config=None, args=None, ffmpeg=None, ffprobe=None, previous=None, warn=None, **fields):
    """Best-effort: record how `output` was made (see the section header for
    where it goes). Never raises - a provenance problem must not fail a run
    whose output already exists. Returns where it went, or None."""
    try:
        config = dict(jwkit_config) if jwkit_config is not None else load_jwkit_config()
        if args is not None:
            apply_provenance_overrides(config, args)
        if not Path(output).is_file():
            return None
        return write_provenance(output, base_record(tool, root, argv, **fields), config, ffmpeg=ffmpeg, ffprobe=ffprobe, previous=previous)
    except Exception as error:  # noqa: BLE001 - see docstring
        message = f"(could not record provenance for {output}: {error})"
        (warn or (lambda text: print(text, file=sys.stderr)))(message)
        return None


# -- sidecar locations -------------------------------------------------------

def provenance_settings(jwkit_config=None):
    """(mode, dir) from the shared config, with a bad mode falling back to embed."""
    config = jwkit_config if jwkit_config is not None else load_jwkit_config()
    mode = str(config.get("provenance_mode", "embed")).strip().lower()
    if mode not in PROVENANCE_MODES:
        print(f"(invalid provenance_mode {mode!r} - expected one of: {', '.join(PROVENANCE_MODES)}; using embed)", file=sys.stderr)
        mode = "embed"
    return mode, str(config.get("provenance_dir", "") or "").strip()


def apply_provenance_overrides(jwkit_config, args):
    """Fold --provenance / --provenance-dir into a shared-config dict."""
    for arg_name, key in (("provenance", "provenance_mode"), ("provenance_dir", "provenance_dir")):
        value = getattr(args, arg_name, None)
        if value is not None:
            jwkit_config[key] = value
    return jwkit_config


def add_provenance_arguments(parser):
    parser.add_argument("--provenance", choices=PROVENANCE_MODES, help="Where to record how the output was made, for this run: embed (inside the file), beside (<file>.jwkit.json), folder (in --provenance-dir), none. Default: provenance_mode in ~/.config/jwkit/config.toml (embed)")
    parser.add_argument("--provenance-dir", help="Folder for --provenance folder (default: a hidden .jwkit folder beside each file)")


def provenance_path(media_path, mode="beside", directory=""):
    """Where the sidecar for `media_path` lives in `beside`/`folder` mode."""
    media_path = Path(media_path)
    name = media_path.name + PROVENANCE_SUFFIX
    if mode != "folder":
        return media_path.with_name(name)
    if not directory:
        return media_path.parent / PROVENANCE_FOLDER_NAME / name
    import hashlib
    where = hashlib.sha1(str(media_path.resolve().parent).encode("utf-8")).hexdigest()[:8]
    return Path(directory).expanduser() / f"{media_path.name}.{where}{PROVENANCE_SUFFIX}"


def _read_sidecar(path):
    try:
        return decode_provenance(Path(path).read_text(encoding="utf-8"))
    except OSError:
        return None


def locate_provenance(media_path, jwkit_config=None, ffprobe=None):
    """(record, where) for a media file: `where` is "embedded" or the sidecar
    Path. Looks inside the file first, then beside it, then the configured
    folder. A path ending in .jwkit.json is read as the sidecar itself."""
    path = Path(media_path)
    if path.name.endswith(PROVENANCE_SUFFIX):
        record = _read_sidecar(path)
        return (record, path) if record else (None, None)
    try:
        text = _embedded_text(path, ffprobe)
    except (OSError, ValueError):
        text = None
    record = decode_provenance(text) if text else None
    if record:
        return record, "embedded"
    _, directory = provenance_settings(jwkit_config)
    for candidate in (provenance_path(path), provenance_path(path, "folder", ""), provenance_path(path, "folder", directory)):
        record = _read_sidecar(candidate)
        if record:
            return record, candidate
    return None, None


def read_provenance(media_path, jwkit_config=None, ffprobe=None):
    """The provenance record for a media file (or a sidecar path), or None."""
    return locate_provenance(media_path, jwkit_config, ffprobe)[0]


def verify_provenance(media_path, record=None, where=None, jwkit_config=None, ffmpeg=None, ffprobe=None):
    """Does the record still describe this file? "match" (the audio/video
    packet hash, or the sidecar's whole-file hash, agrees), "changed" (it
    doesn't - the file was re-encoded or replaced since), or "unknown" (the
    record carries nothing to compare)."""
    if record is None:
        record, where = locate_provenance(media_path, jwkit_config, ffprobe)
    output = (record or {}).get("output") or {}
    packets = output.get("av_sha256")
    if packets:
        return "match" if media_packets_digest(media_path, ffmpeg) == packets else "changed"
    if output.get("sha256"):
        return "match" if file_digest(media_path) == output["sha256"] else "changed"
    return "unknown"


def _output_fields(media_path, embedded, ffmpeg, ffprobe):
    media_path = Path(media_path)
    output = {"file": media_path.name}
    output.update(media_summary(media_path, ffprobe))
    packets = media_packets_digest(media_path, ffmpeg)
    if packets:
        output["av_sha256"] = packets
    if not embedded:
        output["size"] = media_path.stat().st_size
        output["sha256"] = file_digest(media_path)
    return output


def _store(media_path, record, mode, directory, ffmpeg, ffprobe=None):
    """Put an already-built record where `mode` says; returns (mode_used, where).
    An embed that can't happen falls back to a sidecar beside the file."""
    media_path = Path(media_path)
    if mode == "embed":
        try:
            record = dict(record, output=_output_fields(media_path, True, ffmpeg, ffprobe))
            _embed_text(media_path, encode_provenance(record), ffmpeg, ffprobe)
            return "embed", "embedded"
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print(f"(couldn't embed the provenance record in {media_path.name}: {error}; writing it beside the file instead)", file=sys.stderr)
            mode = "beside"
    record = dict(record, output=_output_fields(media_path, False, ffmpeg, ffprobe))
    path = provenance_path(media_path, mode, directory)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return mode, path


def _trash_sidecar(path):
    _move_to_trash(path)
    parent = Path(path).parent
    if parent.name == PROVENANCE_FOLDER_NAME:
        try:
            parent.rmdir()  # only succeeds when empty
        except OSError:
            pass


def _drop_stale_sidecars(media_path, keep, directory):
    """Send leftover sidecars (a previous build's, another mode's) to the Trash."""
    for candidate in {provenance_path(media_path), provenance_path(media_path, "folder", ""), provenance_path(media_path, "folder", directory)}:
        if candidate != keep and candidate.exists():
            _trash_sidecar(candidate)


def write_provenance(media_path, record, jwkit_config=None, ffmpeg=None, previous=None, ffprobe=None):
    """Record how `media_path` was made, in the configured place (see the
    section header). Adds the schema, timestamp, environment, and the output's
    summary and hashes. If a record already exists (a rebuild; or `previous`,
    for a file that was moved aside first), its identifying fields move to
    `history` so the chain of builds stays visible. Returns where it went
    ("embedded" or a Path), or None for mode none."""
    media_path = Path(media_path)
    mode, directory = provenance_settings(jwkit_config)
    if mode == "none":
        return None
    previous = previous or read_provenance(media_path, jwkit_config, ffprobe)
    record = dict(record)
    if previous:
        history = list(previous.get("history", []))
        history.append({
            "created_at": previous.get("created_at"),
            "tool_commit": previous.get("tool_commit"),
            "source_checksum": (previous.get("source") or {}).get("checksum"),
            "output_sha256": (previous.get("output") or {}).get("sha256") or (previous.get("output") or {}).get("av_sha256"),
        })
        record["history"] = history
    record["schema"] = PROVENANCE_SCHEMA
    record["created_at"] = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    record.setdefault("environment", environment_info(ffmpeg))
    mode_used, where = _store(media_path, record, mode, directory, ffmpeg, ffprobe)
    _drop_stale_sidecars(media_path, where if where != "embedded" else None, directory)
    return where


def relocate_provenance(media_path, mode, jwkit_config=None, ffmpeg=None, ffprobe=None, force=False, dry_run=False):
    """Move an existing record to `mode`'s place without touching its content,
    then remove it from where it was (sidecars go to the Trash; an embedded
    record is cleared). Returns (status, where): "moved", "already", "none"
    (no record found), "changed" (the file differs from what a sidecar
    recorded - skipped unless force), "failed", "unsupported" (the container can't carry an embedded
    record), or, with dry_run, "would move"."""
    media_path = Path(media_path)
    if mode not in PROVENANCE_MODES or mode == "none":
        raise ValueError(f"cannot move a record to mode {mode!r}")
    _, directory = provenance_settings(jwkit_config)
    record, where = locate_provenance(media_path, jwkit_config, ffprobe)
    if record is None:
        return "none", None
    target = "embedded" if mode == "embed" else provenance_path(media_path, mode, directory)
    if where == target:
        return "already", where
    recorded = (record.get("output") or {}).get("sha256")
    if where != "embedded" and recorded and not force and file_digest(media_path) != recorded:
        return "changed", where
    if dry_run:
        return "would move", where
    if where == "embedded":  # clear it first, so the sidecar's file hash describes the finished file
        try:
            _embed_text(media_path, None, ffmpeg, ffprobe)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
            print(f"(couldn't clear the embedded record in {media_path.name}: {error})", file=sys.stderr)
            return "failed", where
    mode_used, new_where = _store(media_path, record, mode, directory, ffmpeg, ffprobe)
    if mode == "embed" and mode_used != "embed" and where != "embedded":
        return "unsupported", where  # _store already wrote/kept the sidecar beside the file
    if where == "embedded" and mode_used != mode:  # the sidecar couldn't be written either way: put the record back
        _store(media_path, record, "embed", directory, ffmpeg, ffprobe)
        return "failed", where
    if where != "embedded" and Path(where).exists() and new_where != where:
        _trash_sidecar(where)
    return "moved", new_where


def iter_media_files(paths):
    """Media files named by `paths`: files as given (a .jwkit.json sidecar
    stands for its media file), folders searched recursively."""
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.suffix.lower() in MEDIA_EXTENSIONS and not p.name.startswith("."))
        else:
            yield path.with_name(path.name[:-len(PROVENANCE_SUFFIX)]) if path.name.endswith(PROVENANCE_SUFFIX) else path


def describe_provenance(record, where):
    """Human-readable lines for a record (used by `inspect`/`show`)."""
    source = record.get("source") or {}
    lines = [f"Provenance: {'embedded in the file' if where == 'embedded' else f'sidecar {where}'}",
             f"  built {record.get('created_at')} by {record.get('tool')} {record.get('tool_commit')}"]
    if source.get("url") or source.get("checksum"):
        lines.append(f"  source: {source.get('url') or source.get('file')} (md5 {source.get('checksum')})")
    for entry in record.get("inputs") or []:
        if isinstance(entry, dict):
            role = ", ".join(entry.get("roles") or []) or "input"
            lines.append(f"  input [{role}]: {entry.get('file')} (md5 {entry.get('checksum')})" + (f" <- {entry['made_by'].get('tool')} {entry['made_by'].get('tool_commit')}" if entry.get("made_by") else ""))
    lines.append(f"  rebuild: {(record.get('rebuild') or {}).get('command')}")
    return lines


def move_provenance(paths, mode, jwkit_config=None, ffmpeg=None, ffprobe=None, force=False, dry_run=False, color=None, out=print):
    """Shared by `slverse provenance` and `jwkit-provenance move`. Returns an
    exit status (1 when anything failed or was skipped as changed)."""
    color = color or Colorizer(False)
    counts = {}
    labels = {"moved": color.green("moved"), "already": "already there", "none": "no record", "changed": color.yellow("file changed since it was recorded (use --force)"),
              "failed": color.red("FAILED"), "would move": "would move", "unsupported": color.yellow("container can't embed - kept as a sidecar")}
    for media in iter_media_files(paths):
        if not media.is_file():
            out(color.yellow(f"{media}: media file not found"))
            continue
        status, _ = relocate_provenance(media, mode, jwkit_config, ffmpeg=ffmpeg, ffprobe=ffprobe, force=force, dry_run=dry_run)
        counts[status] = counts.get(status, 0) + 1
        if status != "already":
            out(f"{labels[status]}  {media}")
    out(("\n" + ", ".join(f"{count} {status}" for status, count in sorted(counts.items()))) if counts else "No media files found.")
    return 1 if counts.get("failed") or counts.get("changed") else 0
