# `ffrife`

[← Back to README](../README.md#table-of-contents)

`ffrife` interpolates any video to a higher frame rate using `rife-ncnn-vulkan`, a GPU-accelerated AI model that generates real in-between frames instead of just blending adjacent ones. It works on any local file or URL, JW-related or not — trim a section, add an `ffmpeg` filter, or retime the speed, all in a single pass. `slverse` uses it as a library for its own interpolation (and its `--slow`/`--fast` sectioned retiming) instead of duplicating the logic, and the standalone `ffslow`'s `--rife` flag shells out to it too.

## What It Does

- Interpolates any video to a target frame rate (default 60fps) using `rife-ncnn-vulkan`'s real AI frame synthesis, not `ffmpeg`'s motion-blended `framerate`/`minterpolate` filters (which read as artificially smooth/slow-motion-ish - the "soap opera effect" - even though they don't change actual duration).
- Single-pass extraction: an optional trim window (`--start`/`--end`) and an optional `-vf` filter chain both get applied in the *same* frame-extraction pass, straight from the source. That avoids an extra lossy re-encode generation before RIFE ever sees the footage - the only lossy encode in the whole pipeline is the final merge.
- `--speed` retimes the output (decimal like `0.5`, fraction like `1/3`, or percent like `150%`) by folding `setpts`/`atempo` into that same merge (or fallback) encode - no separate retiming pass, and audio stays in sync with the retimed video.
- Falls back gracefully when RIFE isn't installed/configured (`rife_fallback_engine`: `none` keeps native fps with no artifact, or `framerate`/`minterpolate` for the blended look anyway), so callers don't have to special-case a missing binary.
- `ffrife setup` downloads and configures the right `rife-ncnn-vulkan` release for your platform automatically.
- Shows a minimal live progress bar for anything that's actually slow (RIFE itself has no built-in progress output, so this counts output frames against the expected total) - fast operations stay silent.

## Supported Platforms

- macOS
- Linux
- Windows

## Dependencies

- [Python](../README.md#python)
- `ffmpeg` (a `drawtext`/`delogo`-capable build if callers pass filters through `--vf` - see `jwsl`'s note on `ffmpeg-full`)
- `rife-ncnn-vulkan` (optional - `ffrife setup` downloads it; without it, falls back per `rife_fallback_engine`)

## Install / First Run Summary

Make the script executable:

```bash
chmod +x ffrife
```

Download and configure the RIFE binary for your platform:

```bash
./ffrife setup
```

## Common Usage Examples

Interpolate a whole local file to 60fps:

```bash
./ffrife input.mp4 -o output.mp4
```

Interpolate just a trimmed section, with a filter baked into the same pass:

```bash
./ffrife input.mp4 -o output.mp4 --start 10 --end 20 --vf "drawtext=text='Hello':fontcolor=white:x=10:y=10"
```

Interpolate directly from a remote URL:

```bash
./ffrife "https://example.com/video.mp4" -o output.mp4 --fps 60
```

Half-speed AI slow-motion, single pass:

```bash
./ffrife input.mp4 -o output.mp4 --speed 0.5
```

Use Apple VideoToolbox for this output only:

```bash
./ffrife input.mp4 -o output.mp4 --encoder videotoolbox --codec hevc
```

Time every video encoder this machine's ffmpeg build actually has against a real clip, and apply the recommendation:

```bash
./ffrife benchmark --sample your-clip.mp4 --apply
```

## Important Behavior / Defaults

- Global configuration is saved in `~/.config/jwkit/ffrife/config.toml` (separate from `slverse`'s own config - `slverse` bridges its own `hardware_encoder`/`video_crf`/etc. into a call to `ffrife` rather than needing them kept in sync across two files by hand).
- `hardware_encoder` defaults to `cpu` (`libx264`). Measured directly on Apple Silicon: `videotoolbox` at a quality setting matching `crf 20` produced a file ~2.6x larger than `libx264 crf 20 preset slow` for immeasurably different quality (SSIM within 0.0003), with no meaningful speed advantage at short clip lengths.
- `video_codec` defaults to `av1` (`libsvtav1` in software - no consumer Apple Silicon has AV1 *hardware encode* yet, that's landing with 2026's M5 Pro/Max; VideoToolbox's AV1 support through M4 is decode-only). Measured on a real 10s 720p clip on Apple M3, each codec at its own auto-crf (`h264`=20, `hevc`=23, `av1`=30) and `preset slow` (`preset 6` for `libsvtav1`, ffmpeg's own recommended AV1-equivalent):

  | codec | encoder | time | size | SSIM vs lossless |
  |---|---|---|---|---|
  | h264 | libx264 | 1.7s | 1.46 MB | 0.9979 |
  | hevc | libx265 | 7.0s | 0.79 MB | 0.9967 |
  | av1 | libsvtav1 | 2.2s | 0.61 MB | 0.9963 |

  AV1 via SVT-AV1 came out smallest *and* nearly as fast as h264 - hevc was both bigger and ~3x slower than av1 here, so there's no real case for hevc as a middle tier on this hardware. If `video_codec=av1` isn't actually encodable (no `libsvtav1`/`libaom-av1` in this ffmpeg build, and no hardware AV1 encoder for the configured `hardware_encoder`), it automatically falls back to `hevc`, then `h264` - never upward. AV2 (AOMedia's av1 successor, spec finalized May 2026) is not a real option yet: no ffmpeg encoder support and no shipping hardware decoders as of this writing.
- **This table is one machine's numbers, not a universal answer.** `hardware_encoder`/`video_codec` defaults are a reasonable starting point, not a claim that generalizes across GPU vendors/generations or content types - run `ffrife benchmark` (or `slverse benchmark`, same shared engine in `_jwkit_common.py`) to get real timed/sized/SSIM-measured results for the actual machine and content in question, including trying real GPU hardware encoders (nvenc, qsv) this doc was never measured against. A candidate encoder that's compiled into ffmpeg but has no matching driver/hardware present (e.g. `h264_nvenc` without an NVIDIA GPU) is tried and skipped gracefully, not assumed working from its mere presence in `ffmpeg -encoders`.
- `ffrife <input> -o <output> ...` works without typing the `run` subcommand explicitly; `ffrife run <input> -o <output> ...` is equivalent.
- `--encoder` (`cpu`, `videotoolbox`, `nvenc`, `qsv`), `--codec` (`h264`, `hevc`, `av1`), `--crf`, and `--preset` override encode configuration for one run without changing `config.toml`. Every other `config.toml` setting (`rife_binary_path`, `ffmpeg_binary`, `ffprobe_binary`) has a matching `--<dashed-key>` flag too - run `ffrife run --help` for the full list.
- `--speed` under 1 slows down, over 1 speeds up. RIFE always exactly doubles frame count, so `--fps` should be set to 2x the source's actual frame rate when combining it with `--speed` (this is what `jwsl`'s `--slow` and `ffslow`'s `--rife` do automatically) - any other `--fps` value changes the output's actual duration, not just its smoothness.

## Notes / Caveats

- Downloading the actual RIFE release binary is a multi-MB transfer - if it stalls or times out in a constrained/sandboxed network environment, run `ffrife setup` from a normal terminal instead.
- The final merge (PNG frames back to video) is the only lossy re-encode; PNG extraction and RIFE itself are lossless intermediate steps.

[↑ Back to README TOC](../README.md#table-of-contents)
