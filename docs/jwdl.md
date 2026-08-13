# `jwdl`

[← Back to README](../README.md#table-of-contents)

`jwdl` downloads official JW music (MP3), periodicals (PDF), and videos from jw.org into a local library, one folder per collection.

## What It Does

- Downloads JW music collections (Original Songs, "Sing Out Joyfully", soundtracks, International Music, etc.) via jw.org's public `pub-media` API.
- `jwdl periodicals` downloads the Watchtower Study Edition and the Life and Ministry Meeting Workbook as PDFs, fetching the current issue plus several months ahead — absorbed from the old standalone `jwget` script, but through the same modern, checksummed `pub-media` API `jwdl` already used for music (`jwget`'s legacy scrape endpoint didn't verify downloads at all). Two periodicals `jwget` also carried, Watchtower Public Edition (`wp`) and Awake! (`g`), are not included: jw.org's API 404s on both regardless of issue — they were discontinued as separate monthly periodicals years ago, so there was nothing left to port.
- `jwdl video` browses and downloads JW videos by category (Bible, Dramas, Music Videos, Children, Latest Videos, and more) via jw.org's `mediator` API — the same catalog jw.org's own site and apps browse. Picks a target resolution per video, falling back to the closest one available when your exact choice isn't offered for that particular video.
- Skips audio-description ("for the blind") narrated variants by default — those add spoken narration meant for listeners who can't see, which most people don't want mixed into a regular playlist. Pass `--include-audio-descriptions` to fetch them instead.
- Verifies every download against the checksum the API provides and retries transient failures with backoff.
- Skips tracks already on disk at the expected size, so re-running is fast and safe — designed to run unattended on a schedule (e.g. a weekly timer) to pick up newly released songs automatically.
- Downloads a handful of tracks in parallel per collection to keep runs quick without hammering the CDN.

## Supported Platforms

- macOS
- Linux
- Windows

## Dependencies

- [Python](../README.md#python) 3.8+ (standard library only — nothing extra to install)

## Install / First Run Summary

Make the script executable if your checkout did not preserve executable bits:

```bash
chmod +x jwdl
```

See what's available, then try a dry run before downloading anything:

```bash
./jwdl list
./jwdl osg --dry-run
```

## Common Usage Examples

Download one collection:

```bash
./jwdl osg
```

Download everything (safe to re-run — already-downloaded tracks are skipped):

```bash
./jwdl all
```

Download a non-English language:

```bash
./jwdl osg S
```

Preview what a run would fetch without downloading:

```bash
./jwdl all --dry-run
```

See what periodicals are available, then preview and download them:

```bash
./jwdl periodicals list
./jwdl periodicals w --dry-run
./jwdl periodicals all
```

Browse video categories from the top, then go into one and download it:

```bash
./jwdl video
./jwdl video VODBible
./jwdl video LatestVideos --dry-run
```

Download at a smaller resolution than the default:

```bash
./jwdl video LatestVideos --resolution 360p
```

## Important Behavior / Defaults

- Default destination is `~/Music/Watchtower Music/<collection>`; override it for every collection with `--base-dir`, or for a single pub with `--dir`. Periodicals default to `~/Documents/JW Periodicals/<publication>` and take the same `--base-dir`/`--dir` overrides.
- Default language is `E` (English); pass a language code as the second positional argument (e.g. `./jwdl osg S`, `./jwdl periodicals w S`).
- Audio-description tracks are excluded by default for music; use `--include-audio-descriptions` when you specifically want them.
- `jwdl periodicals` fetches the current issue plus 4 months ahead by default (`--months N` to change that); each issue is checked individually since future issues aren't published yet — those are counted as `not-yet-published`, not errors. Large-print editions are skipped by default; pass `--include-large-print` to also fetch them.
- `jwdl video` defaults to `720p`; if a specific video doesn't have that exact rendition, it picks the closest one at or below your target, or the smallest available if even that's too big. Videos default to `~/Videos/JW Videos/<category name>`.
- `jwdl video` with no category (or any category that's just a folder of subcategories, like `VideoOnDemand`) lists what's inside instead of trying to download nothing — keep going deeper (`jwdl video VODBible`, etc.) until you reach one that lists actual videos.
- `jwdl all` (music), `jwdl periodicals all`, and `jwdl video` are entirely separate commands — `all` never implicitly includes periodicals or video, so anything already scripting `jwdl all` keeps its exact original behavior.
- A config file at `~/.config/jwkit/jwdl/config.json` can add music pub codes jw.org releases later without touching the script (`{"pubs": {"newcode": "Folder Name"}}`), override `base_dir`/`workers`, or set `periodicals_base_dir`/`video_base_dir`.
- Downloads are written to a `.part` file and only renamed into place once the checksum matches, so an interrupted run never leaves a broken file sitting in the library.

## Notes / Caveats

- Music and periodicals rely on jw.org's public, unauthenticated `pub-media` API; if a pub code stops responding, jw.org has likely renamed or retired it — check `https://www.jw.org/en/library/music-songs/` for the current code and add it via the config file above.
- Video uses a different jw.org API (`mediator/v1/categories`, the same one jw.org's own site browses by) — unlike `pub-media`, it returns a real HTTP 404 for an unknown category instead of a 200 with an error payload.
- Filenames intentionally reproduce the naming used by years of prior downloads (curly quotes, `_` in place of `:`, etc.) so an existing library never ends up with a second, differently-named copy of a track it already has.
- `jwdl` has a live weekly caller on the `emeth4` host (systemd user timer running `jwdl all`) — see this repo's `AGENTS.md` Operational Notes before changing `jwdl`'s existing music CLI surface.

[↑ Back to README TOC](../README.md#table-of-contents)
