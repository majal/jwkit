# jwkit-provenance

[← Back to README](../README.md#table-of-contents)

## What It Does

Every file a jwkit tool makes (`slverse`, `ffrife`, `jwvideo-mux`, `ffinpaint`) carries a **provenance record**: a JSON document with the exact command that rebuilds it, every input (name, size, jw.org's MD5, which jw.org publication/language/track the name points to, and - when an input has a record of its own, like an `ffrife` render - who made it and how), the settings that shaped it, the output's streams and a hash of its video/audio packets, the tool's git commit, and the ffmpeg/OS/Python versions. `jwkit-provenance` is the command line for those records:

- `record OUTPUT --tool NAME ...` writes one. Scripts in other repos call this after they write a file (`ffcut`, `fffast`, `ffslow`, `ffm60`, `fflang`, `ffsplitc.py`, `generate_html_colors_video` already do). If jwkit isn't installed they skip it silently.
- `show FILE...` prints it (`--json` for all of it, `--verify` to also check it still matches the file).
- `verify FILE...` exits 1 if a file's audio/video no longer matches its record (re-encoded or replaced since) or it has none.
- `move PATH... --to embed|beside|folder` relocates records without changing them.

## Where a record lives

The shared setting `provenance_mode` in `~/.config/jwkit/config.toml` (or `--provenance` on any tool for one run):

- `embed` (default): **inside the file.** Nothing to keep next to it, and it can't be separated from the video.
  - MP4/MOV/M4V/M4A: a self-describing `uuid` box appended after the media data. Nothing else in the file changes, so titles, chapters and cover art still show in Finder/QuickTime, and every player skips unknown boxes. (ffmpeg's own `-movflags +use_metadata_tags` is not used: it moves every MP4 tag into the `mdta` namespace, and AVFoundation then loses the title.)
  - Matroska/WebM: a native `jwkit_provenance` tag, written by a stream-copy remux that keeps start times and re-attaches cover art; it is checked (packet hash, duration, stream layout) before it replaces anything.
  - MP3/FLAC/Ogg/Opus: the same tag (an ID3 TXXX frame or a Vorbis comment), same check.
  - A record over 8 KB is stored zlib-compressed (`jwkit-z1:` prefix); readers accept both.
- `beside`: `<file>.jwkit.json` next to the file.
- `folder`: the same file in `provenance_dir` / `--provenance-dir`. Empty means a hidden `.jwkit` folder beside each file; an absolute path means one central folder (filenames carry a short hash of the media folder so they don't collide; moving the media breaks the link).
- `none`: no record.

A container that can't carry the record (AVI, WAV, TS, images, ...) or an embed that fails its check falls back to `beside` with a warning; the media file is never left altered.

## Supported Platforms

macOS, Linux, Windows (Windows is untested, like the installer).

## Dependencies

Python and `ffmpeg`/`ffprobe` (found on `PATH` or via each tool's own binary setting).

## Install / First Run Summary

Installed with the rest of jwkit (see the README's Quick Install). Scripts outside jwkit find it on `PATH` or in `~/dig/jwkit` / `~/MyFiles/Digitalis/jwkit`.

## Common Usage Examples

```bash
# What do I know about this file?
jwkit-provenance show "02 Luke_4_6_FSL_cut_rife.mp4" --verify

# Has anything changed since it was made? (exit 1 if so)
jwkit-provenance verify ~/Talks

# Fold old .jwkit.json sidecars into the videos (the sidecars go to the Trash)
jwkit-provenance move ~/Talks --to embed

# From a shell script that just wrote "$out" from "$in"
jwkit-provenance record "$out" --tool mytool --tool-file "$0" --source "$in" \
  --window 10-25.5 --command "mytool $in 10 25.5" --set speed=0.5
```

## Important Behavior / Defaults

- `record` never fails the script that called it: any problem is a warning and exit 0 (`--strict` to exit 1).
- An embedded record can't contain its own file hash; it carries `output.av_sha256`, a hash of the video/audio packets, which metadata edits don't change. Sidecars also carry the whole-file `sha256` and size.
- A rebuild keeps the previous build's commit and source MD5 in `history`.
- Records don't survive re-encoding, or a re-mux in another tool, only a straight copy of the file. `verify` tells you when that happened.
- `move` skips a sidecar whose media file changed since it was recorded unless `--force`.
- `jwdl` does not record: its downloads are byte-for-byte copies of jw.org's files, and embedding would change the file and break its MD5-based freshness check. The same goes for the sources `jwvideo-mux` downloads.

## Notes / Caveats

- Matroska and audio-tag embedding rewrites the file (to a temp file, then swaps it in), so it needs free space for a second copy and takes as long as a copy. MP4 embedding appends a few KB in place.
- `slverse inspect`, `slverse rebuild` and `slverse provenance` read the same records.

[↑ Back to README TOC](../README.md#table-of-contents)
