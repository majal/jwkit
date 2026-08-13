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

## Important Behavior / Defaults

- Global configuration is saved in `~/.config/jwkit/ffrife/config.toml` (separate from `slverse`'s own config - `slverse` bridges its own `hardware_encoder`/`video_crf`/etc. into a call to `ffrife` rather than needing them kept in sync across two files by hand).
- `hardware_encoder` defaults to `cpu` (`libx264`). Measured directly on Apple Silicon: `videotoolbox` at a quality setting matching `crf 20` produced a file ~2.6x larger than `libx264 crf 20 preset slow` for immeasurably different quality (SSIM within 0.0003), with no meaningful speed advantage at short clip lengths.
- `ffrife <input> -o <output> ...` works without typing the `run` subcommand explicitly; `ffrife run <input> -o <output> ...` is equivalent.
- `--speed` under 1 slows down, over 1 speeds up. RIFE always exactly doubles frame count, so `--fps` should be set to 2x the source's actual frame rate when combining it with `--speed` (this is what `jwsl`'s `--slow` and `ffslow`'s `--rife` do automatically) - any other `--fps` value changes the output's actual duration, not just its smoothness.

## Notes / Caveats

- Downloading the actual RIFE release binary is a multi-MB transfer - if it stalls or times out in a constrained/sandboxed network environment, run `ffrife setup` from a normal terminal instead.
- The final merge (PNG frames back to video) is the only lossy re-encode; PNG extraction and RIFE itself are lossless intermediate steps.

[↑ Back to README TOC](../README.md#table-of-contents)
