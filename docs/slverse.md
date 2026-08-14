# `slverse`

[← Back to README](../README.md#table-of-contents)

`slverse` finds, extracts, overlays, and interpolates Sign Language Bible videos, verse by verse. It's the successor to the original [`ffv`](https://github.com/majal/maj-scripts-archive-2026/blob/master/SL/ffv), rebuilt around JW.org's own verse-marker data instead of manual timestamping. Run `slverse setup` for a guided walkthrough of the choices below — plain-language prompts, sane defaults.

## What It Does

- Fetches JW.org API metadata to track available Sign Language Bible videos (NWT) — including the per-verse timestamps JW.org already publishes, so it doesn't need to download a video just to find out where a verse starts.
- Extracts specific verses by streaming just the needed seconds directly from the source URL by default, so a one-verse pull doesn't cost a whole chapter's worth of disk space. Use `--cache` when you'd rather download the full chapter once and reuse it for more verses from the same chapter.
- Optionally applies translated text overlays for book names and chapter/verse numbers.
- Interpolates the extracted clip to 60fps for smoother sign language playback using `ffmpeg` (minterpolate or framerate) or `rife-ncnn-vulkan` (GPU-accelerated AI).
- `--slow`/`--fast` split the extracted verse into alternating normal/retimed sections at one or more boundary times, the same sectioned retiming the standalone `ffslow`/`fffast` tools do (`--slow` retimes the 2nd/4th/... section, `--fast` the 1st/3rd/...) - with `interpolation_engine = rife`, the retimed sections get RIFE-interpolated first via `ffrife` for smooth (not choppy) slow-motion.
- Syncs and extracts across your whole language list in parallel (`slverse sync all`, `slverse extract all "Rev 13:1, 2"`), instead of one language at a time.
- Refreshes your language index automatically, about once a day, whenever you run `extract`/`find`/`bulk` — no need to remember to run `sync` yourself. Skips silently if there's no internet, and never runs more than once a day even if the previous attempt failed or got interrupted.
- Maintains a local cache of downloaded full-chapter videos, capped by size with oldest-used chapters evicted first, so it can't quietly fill your disk.
- `slverse find <book> <chapter> <verse>` searches every language you've already synced for who has a given verse, without downloading anything. `<verse>` also accepts a range (`25-27`) or comma list (`1,3,5`). Default output is a compact ✅/❌ table grouped by language; `--verbose` shows the full URL + mpv command per match, and `--json` gives scripts a machine-readable array. `--play` streams every match with `mpv` - with more than one match, each opens windowed (not fullscreen) and paused, cascaded slightly so they don't stack exactly on top of each other, so you can unpause and review each language side by side; a single match still autoplays fullscreen as before. Every window is spawned non-blocking (macOS/Linux/Windows alike), so the command returns immediately instead of waiting on playback.
- `slverse bulk <lang>` precomputes whole chapters ahead of time (optionally interpolated to 60fps), for when you'd rather batch-process a language than extract on demand.
- Auto-detects a drawtext-capable `ffmpeg` build (looks for a `-full` variant before falling back to the stock formula), so overlays work without hand-picking a binary.
- Trims the trailing fade-out/copyright-endscreen off a chapter's or paragraph's last verse automatically (`trim_end_transition`, default on), using JW's own `endTransitionDuration` marker field rather than guessing from the video.
- Skips the verse-reference swap (delogo + replacement text) whenever the source and target sign languages already caption in the same spoken language (`sign_lang_ref_language`, e.g. ASL→FSL, both English) — only the small source-SL label still draws, so you're not covering an already-correct caption. Configurable per language pair, since which languages share a reference language isn't derivable from the sign-language code itself.
- Sizes the delogo box against the source video's *own* burned-in caption text (from JW's marker metadata), not the replacement text being drawn over it — a caption in a language whose words simply run wider than the replacement no longer leaves a visible sliver of the original.
- `-s`/`--offset-start` and `-e`/`--offset-end` (seconds, either sign) nudge the verse range's own start/end for a partial cut — e.g. `-s 5.302` to skip the first 5.302s and play to the natural end, or `-e -3` to end 3s early. Relative to the verse's own computed boundaries, not a raw seek into the whole file — the same `-s`/`-e` semantics the original `ffv` had.
- `--window START:END` is the compact form for one relative slice: `--window 3.567:10.003` keeps exactly that interval within the natural verse window.
- Output filenames compact contiguous verse ranges (`Rev_13_1-3_ASL.mp4`), include provenance/edit metadata, and carry seekable MP4 chapters for each included verse.
- `slverse inspect <file>` prints an output's duration, provenance, edit status, and verse chapters without requiring raw `ffprobe` commands.
- `--keep-end-transition` overrides `trim_end_transition` for one run (keeps the trailing fade/endscreen instead of cutting it); `--trim-mid-transitions` overrides `trim_mid_transitions` for one run (also cuts any paragraph transition in the *middle* of a multi-verse range, not just the trailing one — off by default, since a range spanning multiple paragraphs is normally meant to play through continuously). Automatically detects whether the source has an audio track at all (JW's own Sign Language videos usually don't) and only maps/re-encodes audio when there actually is one to concatenate.

## What It Doesn't Do (Yet)

- **Lossless inpaint + RIFE relay.** Optional E2FGVI-HQ inpainting is available through [`ffinpaint`](ffinpaint.md), but the unmodified upstream runner emits MP4, so it cannot yet share RIFE's lossless PNG relay. The integration is opt-in because E2FGVI-HQ is CC BY-NC 4.0 and needs a separately installed GPU/PyTorch checkout.

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

Run the interactive setup — it installs `ffmpeg`, asks which sign languages you watch, how much disk space to cache, which 60fps engine to use, whether to add `slverse` to your `PATH`, and whether to keep jwkit itself updated automatically (on by default; every jwkit tool checks for updates at most once a day, only when you actually run one, never in the background):

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

## Configuration

Nearly every behavior is a config key, not a fixed default meant for one setup. `./slverse config list` prints every key, its current value, and a one-line description; `./slverse config get <key>` prints just one, description included. A few worth knowing about beyond the obvious cache/encode ones:

| Key | Default | What it's for |
| --- | --- | --- |
| `trim_end_transition` | `true` | Cut the trailing fade-out/copyright-endscreen off a chapter's/paragraph's last verse. `--keep-end-transition` overrides for one run. |
| `trim_mid_transitions` | `false` | Also cut paragraph transitions in the *middle* of a multi-verse range (a jump cut, straight to the next paragraph's first kept frame). Off by default — a range spanning multiple paragraphs is normally meant to play through as one continuous scene. `--trim-mid-transitions` overrides for one run. |
| `sign_lang_ref_language` | `ASL=en,FSL=en,BVL=es,SPE=es,INI=id` | Which spoken language each sign language's burned-in caption is actually written in — used to skip the reference-swap when source and target already match. Add an entry for any other language you use; an unlisted one always gets the full overlay. |
| `show_source_lang_label` | `true` | The small "which SL this came from" label under the reference — independent of `overlay_source_label_alpha`, which only controls its opacity. |
| `mpv_show_osc` | `true` | mpv's on-screen controller that appears on mouse movement, for every mpv window `slverse` opens. `slverse` always passes `--no-config` to mpv (for reproducibility across machines), so a personal `mpv.conf` that already disables this doesn't apply — set `false` here instead to match a "nothing shows on hover" setup. This is a per-user preference, not something worth defaulting off for everyone. |
| `delogo_width_pad` / `delogo_height_pad` | `10` / `10` | Extra px of safety margin beyond the auto-measured source caption size. |
| `delogo_engine` | `blur` | `blur` is the normal fast filter; `auto` detects likely foreground occlusion and calls configured `ffinpaint`; `inpaint` always tries it. |
| `font_family` / `font_weight_main` / `font_weight_estimator` | `noto-sans-display` / `600` / `400` | Overlay typography — see `FONT_FAMILIES` in the script for the other Google Fonts options. |
| `download_max_attempts` / `download_retry_backoff` | `3` / `2` | Retry behavior for chapter/font downloads. |

Config lives in `~/.config/jwkit/slverse/config.toml`, one `key = "value"` per line — hand-editable or via `config set`; neither path validates the key name, so check `config list` if a setting doesn't seem to be taking effect (a typo just creates an unused key rather than erroring).

## Common Usage Examples

Extract a specific verse (Revelation 13:1, 2 in FSL) and interpolate to 60fps:

```bash
./slverse extract FSL "Rev 13:1, 2" --interpolate
```

Use Apple VideoToolbox and HEVC for one extraction, without changing saved configuration:

```bash
./slverse extract FSL "Rev 13:1, 2" --write --encoder videotoolbox --codec hevc
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

- Global configuration is saved in `~/.config/jwkit/slverse/config.toml`. Sync state is split into a small `state.json` (sync timestamps, cached book-name lookups) plus one index file per synced language under `~/.config/jwkit/slverse/index/`, so it stays fast to load as you sync more languages.
- jwkit itself checks for updates automatically at most once a day, only when you run a real command (never `--help`, never in the background) — see [Quick Install](../README.md#quick-install). Controlled by the shared `auto_update` setting in `~/.config/jwkit/config.toml`, not this tool's own config.
- Extraction downloads a verified chapter once and reuses it by default (`extract_mode = cache`). Cached chapters live in `~/.cache/slverse/`, capped at `cache_max_gb` (default 5 GB) with least-recently-used chapters removed first once the cap is hit. Pass `--onthefly` only when you explicitly want to stream without caching.
- The tool uses lazy loading: it only downloads or streams a chapter when a specific verse extraction is requested, and only syncs metadata for the languages you've configured (default `ASL,FSL,BVL,INI,SPE`) unless you name others.
- Verse start/end times come from JW.org's own API metadata (backfilled into the local index on first use), not from probing a downloaded video file. Book-name lookups are cached per `api_language` too, instead of hitting jw.org on every extract.
- Encoding quality is configurable (`video_codec`, `video_crf`, `video_preset`) and defaults to `libx264 -crf 20 -preset slow`. This is intentionally *higher* quality than JW.org's own source encode (~1.07 Mbps H.264 Main@3.1 720p30, per a direct `ffprobe` of a sample video) rather than matching it bitrate-for-bitrate: overlays force a re-encode of an already-lossy source, and re-encoding a second generation at the source's own bitrate would compound visible compression loss. Since clips are short, the absolute file size stays small either way.
- Picks a drawtext-capable `ffmpeg` automatically: it prefers an `ffmpeg-full`-style build (or whatever `ffmpeg_binary`/`ffprobe_binary` you set explicitly) over the stock Homebrew `ffmpeg`, which doesn't include `freetype`/`fontconfig`.
- When applying overlays, the tool expects standard English abbreviations or full names (e.g., "Rev" or "Revelation") by default, or a plain book number.
- `extract`/`find`/`bulk` trigger a metadata refresh at most once every `auto_sync_interval_hours` (default 24), so verse availability stays current without ever running `slverse sync` by hand. By default (`auto_sync_background = true`) this refresh runs as a detached background process and never blocks the command that triggered it; set `./slverse config set auto_sync_background false` to sync inline and block instead. Disable the refresh entirely per-run with `--no-auto-sync`, or permanently with `./slverse config set auto_sync false`. A failed or offline attempt still resets the timer, so a bad connection doesn't retry (and pause) on every command for the rest of the day.
- `--slow`/`--fast` need `--write`/`-f` (no live preview for sectioned retiming); boundary times are seconds or `HH:MM:SS`, relative to the verse's own start, and must be strictly increasing and inside the verse's duration. `--speed` defaults to `0.5` for `--slow` and `3` for `--fast` if not given explicitly. Like the standalone `ffslow`/`fffast` tools, sectioned output is video-only (no audio) - the single-window path (without `--slow`/`--fast`) still keeps audio.
- Preview mode (`extract` without `--write`) defaults to `preview_source = cache`: it downloads the chapter once (if not already cached under `cache_dir`, from a prior `--cache` extract, a `bulk` run, or an earlier preview) and plays that local copy from then on, so previewing more verses from the same chapter costs no further bandwidth. The "Previewing:" line shows the local path being played; a `Source:` line under it has the remote URL too, in case you want to swap it in yourself. Set `./slverse config set preview_source remote` to always stream straight from the URL instead and never touch disk.
- Both preview players (`ffplay` by default, `mpv` with `--play`/`-m`) stay open on the last frame once playback ends instead of closing themselves, so you can seek back and review the clip; close the window yourself when you're done.
- `find --play`'s multi-language preview windows are sized via `preview_window_size` (default `65%` of screen size, aspect preserved, via mpv's `--autofit`) when previewing more than one language at once; a single match still autoplays fullscreen.
- A multi-verse extraction can show more than one distinct source caption in sequence (each verse advances its own marker's label, e.g. "Psalm 16:10" then "Psalm 16:11") - the delogo box is sized to whichever is widest/tallest across the whole window, so it stays correctly sized throughout rather than only for the first verse.

## Notes / Caveats

- `minterpolate` through `ffmpeg` is CPU-bound and very slow. Using `rife-ncnn-vulkan` is highly recommended for users with a dedicated GPU; `slverse setup` tells you exactly what to download for your OS.
- The default `--onthefly` mode seeks directly against the CDN URL, which is a byte-approximate seek over the network rather than a local frame-accurate one — fine for casual viewing, but use `--cache` if you need frame-exact boundaries or plan to pull several verses from the same chapter.
- `slverse` replaces the legacy `SL/ffv`, `SL/ffvdl`, `SL/sldl`, `SL/sldl_nwt`, `SL/sldl_nwt_info`, and `SL/sl_findlang` scripts, kept for reference only in git history and a local archive, not part of this public repo's working tree.

[↑ Back to README TOC](../README.md#table-of-contents)
