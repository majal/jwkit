# `jwget`

[← Back to README](../README.md#table-of-contents)

`jwget` is a legacy (2016-2018-era) bash script that bulk-downloads jw.org **periodicals** — Watchtower (public and study editions), Awake! (`g`), and the Life and Ministry Meeting Workbook (`mwb`) — as PDF (or RTF) files, for the current month plus four months ahead.

## What It Does

- Loops over `wp`, `w`, `g`, and `mwb`, fetching each from jw.org's legacy `apps.jw.org/E_GETPUBMEDIALINKS` scrape endpoint.
- Downloads five months of issues per publication type (current month plus the next four) on every run.
- Writes into `~/Desktop/JWGet/<type>/`, one subfolder per publication type.
- Waits for connectivity (polls every 15 minutes) before starting, so it's safe to run unattended.
- Guards against overlapping runs with a `pgrep` instance check.

## Supported Platforms

- Linux / macOS with `bash` and `wget`

## Dependencies

- `bash`, `wget`
- Optional: `gzip`, `pgrep` (normally preinstalled on most Linux distros)

## Install / First Run Summary

Make the script executable if your checkout did not preserve executable bits:

```bash
chmod +x jwget
```

Edit the user options near the top of the script first — `DIRBASE`, `format`, and `LANG` are hardcoded, not CLI flags:

```bash
DIRBASE="$HOME/Desktop/JWGet"
format='PDF' # EPUB,MOBI,PDF,RTF,BRL - choose one
LANG='E'
```

Then run it:

```bash
./jwget
```

## Common Usage Examples

Run once, in the foreground:

```bash
./jwget
```

Run unattended (it already waits for connectivity and guards against overlapping runs):

```bash
nohup ./jwget &
```

## Important Behavior / Defaults

- No CLI arguments — every option (`DIRBASE`, `format`, `LANG`) is a variable near the top of the script that you edit directly.
- `format = "PDF"` deletes other existing filetypes in each publication's folder to keep it single-format (see the `ropts` comment in the script).
- Logging is disabled by default (`LOGFILE="/dev/null"`); point it at a real path to keep a run log.

## Notes / Caveats

- **This is old code.** The endpoint (`apps.jw.org/E_GETPUBMEDIALINKS`) and this script's structure date to 2016-2018, before jw.org's later site redesigns. Verify it still logs real downloads before relying on it — it has not been re-verified against the current site as part of this repo's split from `maj-scripts`.
- Unlike [`jwdl`](jwdl.md) (JW music via the modern, documented `pub-media` API with checksums and retries), `jwget` has no verification step and downloads everything on every run rather than skipping what you already have.
- No content overlap with `jwdl` — this downloads periodicals (PDF), `jwdl` downloads music (MP3).

[↑ Back to README TOC](../README.md#table-of-contents)
