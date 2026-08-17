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
- Runs long jobs as bounded, resumable chunks with a cooldown between them. The default `1:1:1` RIFE worker layout also avoids the upstream binary's more aggressive `1:2:2` processing default.
- Processes folders, quoted wildcards, and newline-delimited file lists sequentially with `ffrife batch` (`bulk` is an alias), isolating per-file failures and printing a final summary.

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

Process every video in a folder (recursively) without running multiple GPU jobs at once:

```bash
./ffrife batch ./incoming -r -O ./interpolated
```

Quoted wildcards and explicit lists work too:

```bash
./ffrife batch "clips/*.mp4" --glob "more/**/*.mkv" --list jobs.txt -r -O ./done
```

Use a cooler one-run profile, or disable chunking for a short job:

```bash
./ffrife input.mp4 -o output.mp4 -j 1:1:1 -c 600 --cooldown 30
./ffrife input.mp4 -o output.mp4 -c 0
```

Interrupted runs resume automatically when the same input, output, and interpolation options are used. To opt out for one run:

```bash
./ffrife input.mp4 -o output.mp4 --no-resume
```

Time every video encoder this machine's ffmpeg build actually has against a real clip, and apply the recommendation:

```bash
./ffrife benchmark --sample your-clip.mp4 --apply
```

## Important Behavior / Defaults

- Global configuration is saved in `~/.config/jwkit/ffrife/config.toml` (separate from `slverse`'s own config - `slverse` bridges its own `hardware_encoder`/`video_crf`/etc. into a call to `ffrife` rather than needing them kept in sync across two files by hand).
- Long-run defaults are `rife_threads=1:1:1`, `rife_gpu=auto`, `chunk_frames=1200`, `cooldown_seconds=15`, and `resume=true`. Set any persistently with `ffrife config set KEY VALUE`; override them with `-j`/`--rife-threads`, `--rife-gpu`, `-c`/`--chunk-frames`, `--cooldown`, and `--resume`/`--no-resume`.
- Chunks overlap by one source frame, and the duplicate endpoint is removed during assembly. This preserves continuity across the boundary while still producing the exact requested total frame count.
- Resume state is stored in a hidden directory beside the output, named after the output plus a signature of the source and interpolation settings. Extraction and each completed RIFE chunk are recorded atomically. Successful jobs remove the state automatically unless `--keep-work` is used; interrupted or failed jobs retain it and print its location.
- `rife_gpu=cpu` maps to RIFE device `-1`. This avoids GPU use but is not necessarily cooler overall; it can shift sustained load to the CPU. `auto` normally gives the best efficiency on Apple Silicon.
- Batch mode accepts files, directories, quoted shell patterns, repeatable `--glob` patterns, and repeatable `--list` files. Blank/comment lines in list files are ignored, relative entries resolve beside the list, duplicates are removed, unsupported extensions are ignored, and processing is deliberately sequential. The default output template is `{stem}_rife{suffix}`; customize it with `--output-name` using `{stem}`, `{suffix}`, and `{name}`.
- Batch failures do not discard other queued work. Use `--fail-fast` when the first failure should stop the queue. Existing outputs use the same shared `--on-exists` policy as single-file runs.
- `hardware_encoder` defaults to `cpu` (`libx264`). Measured directly on Apple Silicon: `videotoolbox` at a quality setting matching `crf 20` produced a file ~2.6x larger than `libx264 crf 20 preset slow` for immeasurably different quality (SSIM within 0.0003), with no meaningful speed advantage at short clip lengths.
- `video_codec` defaults to `av1` (`libsvtav1` in software - no consumer Apple Silicon has AV1 *hardware encode* yet, that's landing with 2026's M5 Pro/Max; VideoToolbox's AV1 support through M4 is decode-only). Confirmed with a full `benchmark` crf sweep (3 crf values per codec, real ASL footage, Apple M3):

  | codec | encoder | crf | time | size | SSIM vs lossless |
  |---|---|---|---|---|---|
  | hevc | libx265 | 26 | 4.5s | 0.40 MB | 0.9961 |
  | av1 | libsvtav1 | 30 | 1.5s | 0.45 MB | 0.9963 |
  | av1 | libsvtav1 | 27 | 1.5s | 0.54 MB | 0.9965 |
  | hevc | libx265 | 23 | 5.1s | 0.58 MB | 0.9966 |
  | h264 | libx264 | 20 | 1.3s | 1.17 MB | 0.9978 |

  (full 15-row sweep, every hw/codec/crf this machine's ffmpeg supports, via `slverse benchmark`/`ffrife benchmark`). hevc's smallest crf (26) edges out av1's by ~12% - but takes 3x longer to encode for it and scores *lower* SSIM, which is why `recommend_from_benchmark` treats anything within 15% of the smallest file as a tie and picks the fastest among them (av1) rather than chasing noise-level size differences. If `video_codec=av1` isn't actually encodable (no `libsvtav1`/`libaom-av1` in this ffmpeg build, and no hardware AV1 encoder for the configured `hardware_encoder`), it automatically falls back to `hevc`, then `h264` - never upward. AV2 (AOMedia's av1 successor, spec finalized May 2026) is not a real option yet: no ffmpeg encoder support and no shipping hardware decoders as of this writing.
- **This table is one machine's numbers, not a universal answer.** `hardware_encoder`/`video_codec`/`video_crf` defaults are a reasonable starting point, not a claim that generalizes across GPU vendors/generations or content types - run `ffrife benchmark` (or `slverse benchmark`, same shared engine in `_jwkit_common.py`) to get real timed/sized/SSIM-measured results for the actual machine and content in question, including trying real GPU hardware encoders (nvenc, qsv) this doc was never measured against. A candidate encoder that's compiled into ffmpeg but has no matching driver/hardware present (e.g. `h264_nvenc` without an NVIDIA GPU) is tried and skipped gracefully, not assumed working from its mere presence in `ffmpeg -encoders`. `benchmark` sweeps 3 crf values per codec by default (`--quick` tests just one, faster but coarser); `--apply` saves the winning `hardware_encoder`/`video_codec`, and `video_crf` too - as `auto` rather than the literal number when the winner is just that codec's own normal default, so it stays correctly adaptive if the codec later changes.
- `ffrife <input> -o <output> ...` works without typing the `run` subcommand explicitly; `ffrife run <input> -o <output> ...` is equivalent.
- `--encoder` (`cpu`, `videotoolbox`, `nvenc`, `qsv`), `--codec` (`h264`, `hevc`, `av1`), `--crf`, and `--preset` override encode configuration for one run without changing `config.toml`. Every other `config.toml` setting (`rife_binary_path`, `rife_model`, `ffmpeg_binary`, `ffprobe_binary`) has a matching `--<dashed-key>` flag too - run `ffrife run --help` for the full list.
- `--fps` is the real, exact output frame rate: `interpolate()` probes the source's actual frame rate and computes the exact RIFE `-n` frame count needed to hit `--fps` at the source's original duration - so `--fps 60` produces a genuine flat 60fps output (not a source-fps-multiple like 59.94) with no speed change, and this works for any ratio (e.g. 24fps source → 60fps output, a 2.5x ratio), not just an exact doubling. It also accepts a source-relative spec instead of a literal number: `--fps 2x`/`--fps 2.5x` (a multiple of the source's own fps) or `--fps 150%` - resolved the same way, against the probed source fps.
- `rife_model` (default `rife-v4.6`) must be an arbitrary-timestep-capable model - only `rife-v4`/`rife-v4.6` support the explicit `-n`/-`m` combination `interpolate()` always uses; older bundled models (`rife-v2.3`, `rife-v3.1`, `rife-HD`, `rife-UHD`, `rife-anime`, etc.) reject it. `ffrife setup` prunes every model directory except the configured one after download (the release bundles ~450MB across ~10 models; only the configured one is kept, ~11MB).
- `ffrife setup` re-checks an already-configured RIFE install against this: it smoke-tests the configured binary+model with a couple of throwaway synthetic frames, and if that install predates the always-pass-`-n`/`-m` behavior above (or was pointed at an incompatible model), it explains why and offers to download+install a fresh release instead of just reporting "already configured."
- `--speed` under 1 slows down, over 1 speeds up. RIFE generates the final retimed frame count directly (for example, half speed produces twice as many synthesized frames) rather than stretching timestamps and duplicating frames; the result still needs only the final merge encode.
- `-o`/`--output` goes through the shared overwrite-conflict handling (`on_output_exists`/`--on-exists`, etc. - see the README's Output is colored.../overwrite paragraph) before `interpolate()` ever runs, same as every other jwkit tool.

## Notes / Caveats

- Downloading the actual RIFE release binary is a multi-MB transfer - if it stalls or times out in a constrained/sandboxed network environment, run `ffrife setup` from a normal terminal instead.
- The final merge (PNG frames back to video) is the only lossy re-encode; PNG extraction and RIFE itself are lossless intermediate steps.
- Intermediate PNGs can consume substantial disk space. They are required for lossless resume and are cleaned after success; check the printed hidden work-directory path after an interrupted job if space is tight.
- Cooling is time-based rather than temperature-based because portable, permission-free temperature telemetry is not consistently available across macOS, Linux, and Windows. The operating system remains responsible for hardware thermal throttling.

[↑ Back to README TOC](../README.md#table-of-contents)
