# `slverse`

[← Back to README](../README.md#table-of-contents)

`slverse` is a unified tool for downloading, extracting, overlaying, and interpolating Sign Language Bible videos. It's not techie-only: `slverse setup` walks through the choices below with plain-language prompts and sane defaults.

## What It Does

- Fetches JW.org API metadata to track available Sign Language Bible videos (NWT) — including the per-verse timestamps JW.org already publishes, so it doesn't need to download a video just to find out where a verse starts.
- Extracts specific verses by streaming just the needed seconds directly from the source URL by default, so a one-verse pull doesn't cost a whole chapter's worth of disk space. Use `--cache` when you'd rather download the full chapter once and reuse it for more verses from the same chapter.
- Optionally applies translated text overlays for book names and chapter/verse numbers.
- Interpolates the extracted clip to 60fps for smoother sign language playback using `ffmpeg` (minterpolate or framerate) or `rife-ncnn-vulkan` (GPU-accelerated AI).
- `--slow`/`--fast` split the extracted verse into alternating normal/retimed sections at one or more boundary times, the same sectioned retiming the standalone `ffslow`/`fffast` tools do (`--slow` retimes the 2nd/4th/... section, `--fast` the 1st/3rd/...) - with `interpolation_engine = rife`, the retimed sections get RIFE-interpolated first via `ffrife` for smooth (not choppy) slow-motion.
- Syncs and extracts across your whole language list in parallel (`slverse sync all`, `slverse extract all "Rev 13:1, 2"`), instead of one language at a time.
- Refreshes your language index automatically, about once a day, whenever you run `extract`/`find`/`bulk` — no need to remember to run `sync` yourself. Skips silently if there's no internet, and never runs more than once a day even if the previous attempt failed or got interrupted.
- Maintains a local cache of downloaded full-chapter videos, capped by size with oldest-used chapters evicted first, so it can't quietly fill your disk.
- `slverse find <book> <chapter> <verse>` searches every language you've already synced for who has a given verse, without downloading anything. `<verse>` also accepts a range (`25-27`) or comma list (`1,3,5`). Default output is a compact ✅/❌ table grouped by language; `--verbose` shows the full URL + mpv command per match, and `--json` gives scripts a machine-readable array.
- `slverse bulk <lang>` precomputes whole chapters ahead of time (optionally interpolated to 60fps), for when you'd rather batch-process a language than extract on demand.
- Auto-detects a drawtext-capable `ffmpeg` build (looks for a `-full` variant before falling back to the stock formula), so overlays work without hand-picking a binary.

## Supported Platforms

- macOS
- Linux
- Windows

## Dependencies

- [Python](../README.md#python)
- `ffmpeg` (requires `freetype` and `fontconfig` support for text overlays — the stock Homebrew `ffmpeg` formula does not include these; `slverse setup` installs a build that does, and `slverse` auto-detects an existing `ffmpeg-full`-style build if you already have one)
- `rife-ncnn-vulkan` (optional, for ultra-fast GPU interpolation)
- `mpv` (optional, only for `slverse find --play`)

## Install / First Run Summary

Make the script executable:

```bash
chmod +x slverse
```

Run the interactive setup — it installs `ffmpeg`, asks which sign languages you watch, how much disk space to cache, which 60fps engine to use, and offers to add `slverse` to your `PATH`:

```bash
./slverse setup
```

Run it again on every machine you use `slverse` on — settings are per-machine, not synced.

Prefer to skip the questions and just install dependencies:

```bash
./slverse setup --non-interactive
```

You can also set individual options by hand at any time:

```bash
./slverse config set cache_max_gb 5
./slverse config set interpolation_engine rife
./slverse config set languages ASL,FSL,BVL,INI,SPE
```

## Common Usage Examples

Extract a specific verse (Revelation 13:1, 2 in FSL) and interpolate to 60fps:

```bash
./slverse extract FSL "Rev 13:1, 2" --interpolate
```

Do the same for every language in your configured list, in parallel:

```bash
./slverse extract all "Rev 13:1, 2" --interpolate
```

Pull a single verse without ever storing the full chapter on disk (this is the default, `--onthefly` is shown for clarity):

```bash
./slverse extract FSL "Rev 13:1" --onthefly
```

Download and keep the full chapter instead, so more verses from it are free to extract afterward:

```bash
./slverse extract FSL "Rev 13:1" --cache
```

Sync metadata (and verse timestamps) for your whole language list:

```bash
./slverse sync all
```

See who has already-synced coverage of a verse:

```bash
./slverse find Revelation 13 1
```

Check cache usage and clear it:

```bash
./slverse cache list
./slverse cache clean
```

Precompute a whole book range ahead of time, interpolated to 60fps:

```bash
./slverse bulk FSL --books 40-66 --interpolate
```

Extract a verse with the middle 2 seconds slowed to half speed (RIFE-smoothed if `interpolation_engine = rife`):

```bash
./slverse extract FSL "Rev 13:1" --write --slow 3 5
```

Same, but sped up 2.5x instead, with an explicit `--speed` (accepts a decimal, a fraction like `1/3`, or a percent like `150%`):

```bash
./slverse extract FSL "Rev 13:1" --write --fast 3 5 --speed 2.5
```

## Important Behavior / Defaults

- Global configuration is saved in `~/.config/maj-scripts/slverse/config.toml`. Sync state is split into a small `state.json` (sync timestamps, cached book-name lookups) plus one index file per synced language under `~/.config/maj-scripts/slverse/index/`, so it stays fast to load as you sync more languages.
- Extraction streams directly from the source URL by default (`extract_mode = onthefly`) and never touches the cache; pass `--cache` (or set `extract_mode = cache`) to download the full chapter instead. Cached chapters live in `~/.cache/slverse/`, capped at `cache_max_gb` (default 5 GB) with least-recently-used chapters removed first once the cap is hit.
- The tool uses lazy loading: it only downloads or streams a chapter when a specific verse extraction is requested, and only syncs metadata for the languages you've configured (default `ASL,FSL,BVL,INI,SPE`) unless you name others.
- Verse start/end times come from JW.org's own API metadata (backfilled into the local index on first use), not from probing a downloaded video file. Book-name lookups are cached per `api_language` too, instead of hitting jw.org on every extract.
- Encoding quality is configurable (`video_codec`, `video_crf`, `video_preset`) and defaults to `libx264 -crf 20 -preset slow`. This is intentionally *higher* quality than JW.org's own source encode (~1.07 Mbps H.264 Main@3.1 720p30, per a direct `ffprobe` of a sample video) rather than matching it bitrate-for-bitrate: overlays force a re-encode of an already-lossy source, and re-encoding a second generation at the source's own bitrate would compound visible compression loss. Since clips are short, the absolute file size stays small either way.
- Picks a drawtext-capable `ffmpeg` automatically: it prefers an `ffmpeg-full`-style build (or whatever `ffmpeg_binary`/`ffprobe_binary` you set explicitly) over the stock Homebrew `ffmpeg`, which doesn't include `freetype`/`fontconfig`.
- When applying overlays, the tool expects standard English abbreviations or full names (e.g., "Rev" or "Revelation") by default, or a plain book number.
- `extract`/`find`/`bulk` trigger a background-ish metadata refresh at most once every `auto_sync_interval_hours` (default 24), so verse availability stays current without ever running `slverse sync` by hand. Disable per-run with `--no-auto-sync`, or permanently with `./slverse config set auto_sync false`. A failed or offline attempt still resets the timer, so a bad connection doesn't retry (and pause) on every command for the rest of the day.
- `--slow`/`--fast` need `--write`/`-f` (no live preview for sectioned retiming); boundary times are seconds or `HH:MM:SS`, relative to the verse's own start, and must be strictly increasing and inside the verse's duration. `--speed` defaults to `0.5` for `--slow` and `3` for `--fast` if not given explicitly. Like the standalone `ffslow`/`fffast` tools, sectioned output is video-only (no audio) - the single-window path (without `--slow`/`--fast`) still keeps audio.

## Notes / Caveats

- `minterpolate` through `ffmpeg` is CPU-bound and very slow. Using `rife-ncnn-vulkan` is highly recommended for users with a dedicated GPU; `slverse setup` tells you exactly what to download for your OS.
- The default `--onthefly` mode seeks directly against the CDN URL, which is a byte-approximate seek over the network rather than a local frame-accurate one — fine for casual viewing, but use `--cache` if you need frame-exact boundaries or plan to pull several verses from the same chapter.
- `slverse` replaces the legacy `SL/ffv`, `SL/ffvdl`, `SL/sldl`, `SL/sldl_nwt`, `SL/sldl_nwt_info`, and `SL/sl_findlang` scripts, kept for reference only in git history and a local archive, not part of this public repo's working tree.

[↑ Back to README TOC](../README.md#table-of-contents)
