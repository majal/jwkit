# `jwdl`

[← Back to README](../README.md#table-of-contents)

`jwdl` downloads official JW music (MP3) publications from jw.org into a local library, one folder per collection.

## What It Does

- Downloads JW music collections (Original Songs, "Sing Out Joyfully", soundtracks, International Music, etc.) via jw.org's public `pub-media` API.
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

## Important Behavior / Defaults

- Default destination is `~/Music/Watchtower Music/<collection>`; override it for every collection with `--base-dir`, or for a single pub with `--dir`.
- Default language is `E` (English); pass a language code as the second positional argument (e.g. `./jwdl osg S`).
- Audio-description tracks are excluded by default; use `--include-audio-descriptions` when you specifically want them.
- A config file at `~/.config/maj-scripts/jwdl/config.json` can add pub codes jw.org releases later without touching the script (`{"pubs": {"newcode": "Folder Name"}}`) and can override `base_dir` or `workers`.
- Downloads are written to a `.part` file and only renamed into place once the checksum matches, so an interrupted run never leaves a broken track sitting in the library.

## Notes / Caveats

- Relies on jw.org's public, unauthenticated `pub-media` API; if a pub code stops responding, jw.org has likely renamed or retired it — check `https://www.jw.org/en/library/music-songs/` for the current code and add it via the config file above.
- Filenames intentionally reproduce the naming used by years of prior downloads (curly quotes, `_` in place of `:`, etc.) so an existing library never ends up with a second, differently-named copy of a track it already has.

[↑ Back to README TOC](../README.md#table-of-contents)
