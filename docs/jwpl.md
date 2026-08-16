# jwpl

[← Back to README](../README.md#table-of-contents)

## What It Does

Creates JW Library `.jwlplaylist` archives from naturally sorted local media
without the JW Library UI. The archive keeps each source media file intact;
`jwpl` only generates thumbnails and writes JW Library's controller-facing
playlist labels.

## Supported Platforms

- macOS
- Linux
- Windows

## Dependencies

- Python 3.10 or newer
- `ffmpeg` and `ffprobe`

## Install / First Run Summary

Use jwkit's normal installer, then check the selection before creating your
first playlist:

```bash
jwpl create "/path/to/media" --dry-run
```

## Common Usage Examples

Preview natural-sort selection without writing:

```bash
jwpl create "/path/to/media" --dry-run
```

Create `media/media.jwlplaylist`:

```bash
jwpl create "/path/to/media"
```

Choose one language variant and an explicit name/output:

```bash
jwpl create "/path/to/media" \
  --name "Tuesday Service Talk - English" \
  --output "/tmp/tuesday-english.jwlplaylist" \
  --include "*.jpg" --include "*.mp4" \
  --exclude "*FSL-TG_*" --exclude "*FSL-CV_*" --exclude "*FSL-HV_*"
```

Inspect an existing or generated archive:

```bash
jwpl inspect talk.jwlplaylist
jwpl inspect talk.jwlplaylist --json
```

## Important Behavior / Defaults

`create --output` (not `--dry-run`) goes through the shared `on_output_exists` policy when the
target `.jwlplaylist` already exists (default: ask, with a non-interactive fallback for
cron/unattended runs - see the README's overwrite paragraph). Override for one run with
`--on-exists`/`--on-exists-unattended`/`--overwrite-timeout`.

A playlist is a DEFLATE-compressed ZIP containing:

- `manifest.json`
- `userData.db`, a SQLite user-data database
- UUID-named media and thumbnails
- `default_thumbnail.png`

The playlist name is a type-2 row in `Tag`; `TagMap.Position` holds playback
order. Local files are represented by `IndependentMedia` and
`PlaylistItemIndependentMediaMap`. This implementation emits schema 16, the
current schema found in JWLManager in July 2026.

Format research was checked against 19 local real-world playlist exports and
against [JWLManager](https://github.com/erykjj/jwlmanager), an MIT-licensed
open-source JW Library archive manager. The CLI does not require JWLManager or
copy its binary template at runtime.

See [jwpl-format-research.md](jwpl-format-research.md) for the
project watchlist and the verified iPad import/transcoding comparison.

The public defaults preserve each complete filename as the playlist label.
For presentation folders whose videos already have good embedded titles, use:

```bash
jwpl create "/path/to/media" --video-title-source metadata --number-titles
```

Videos then use their embedded title and pictures use their filename stem.
Both receive the filename's leading presentation number, normalized to the
width required by the largest number (`01` through `12`, `001` through `120`).
If a filename has no leading number, its natural-sort position is used. This
changes only JW Library's playlist label; it does not rewrite or remux media.

## Configuration

Create a starter per-directory file:

```bash
jwpl init "/path/to/media"
```

The file is `/path/to/media/jwlplaylist.toml`. Global defaults live at
`~/.config/jwkit/jwpl/config.toml` and can be managed like this:

```bash
jwpl config list
jwpl config get end_action
jwpl config set end_action 2
```

Precedence is built-in defaults, global config, directory config, then CLI.
Every setting has a matching `create` flag:

| TOML key | CLI flag | Default |
| --- | --- | --- |
| `recursive` | `--recursive` / `--no-recursive` | `false` |
| `include` | `--include` (repeatable) | `["*"]` |
| `exclude` | `--exclude` (repeatable) | generated playlists/config/noise |
| `end_action` | `--end-action` | `2` |
| `image_duration_seconds` | `--image-duration-seconds` | `4.0` |
| `thumbnail_size` | `--thumbnail-size` | `250` |
| `device_name` | `--device-name` | `jwpl` |
| `video_title_source` | `--video-title-source` | `filename` |
| `number_titles` | `--number-titles` / `--no-number-titles` | `false` |
| `ffmpeg` | `--ffmpeg` | `ffmpeg` |
| `ffprobe` | `--ffprobe` | `ffprobe` |

`name` and `output` may also be set in the directory TOML and overridden with
`--name` and `--output`.

## Notes / Caveats

- This creates playlists from local files. JW Library catalog references
  (publication key/language/track rows) are visible through `inspect`, but the
  CLI does not yet synthesize them from filenames.
- The current March English example selects the same 20 local logical items,
  in the same order, as the old export. The old export has a 21st catalog-only
  FSL song item.
- The iPad export stored malformed media hashes using bytewise hex without
  zero-padding. The CLI's `inspect` command now compares those stored values
  with actual archive-entry hashes without producing false mismatch
  conclusions.
- Schema, ZIP integrity, hashes, foreign keys, ordering, duration probing, and
  thumbnail generation are locally verified. The generated English playlist
  was imported and played successfully in JW Library on 2026-08-14. Broader
  platform/format testing is still useful.

[↑ Back to README TOC](../README.md#table-of-contents)
