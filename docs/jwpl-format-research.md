# JW Library playlist and backup research

Last checked: 2026-08-14.

## Projects to watch

- [JWLManager](https://github.com/erykjj/jwlmanager) — the most directly
  relevant project: active, MIT-licensed, cross-platform, and handles both
  `.jwlibrary` and `.jwlplaylist` import/export/merge. Its current blank
  playlist template is schema 16.
- [JW Notes Sync](https://github.com/DipandaAser/jw-notes-sync) — MIT-licensed
  TypeScript work on offline-first backup merging. Useful independent evidence
  about manifest/database validation and Android strictness.
- [library-merger / go-jwlm](https://github.com/AndreasSko/go-jwlm) — mature
  Go CLI for comparing and merging `.jwlibrary` backups. It is more focused on
  user-data merge correctness than playlist creation, but is valuable for
  schema evolution and comparison behavior.
- [GitHub's `jwlibrary` topic](https://github.com/topics/jwlibrary) — discovery
  feed for new tools. Most entries are narrow or inactive; review periodically
  rather than adopting them as dependencies automatically.
- [Official JW Library playlist help](https://www.jw.org/en/online-help/jw-library/use-playlists/)
  — authoritative UI semantics for Continue, Stop, Freeze, Repeat, trimming,
  sharing, and external-media import, though it does not document the archive
  schema.

This is a watchlist, not vendored code. `jwpl` remains self-contained.

## Import/transcoding experiment

Source: one schema-14 playlist exported from JW Library on iPad in March 2026,
compared with the 20 corresponding files still present beside it. Comparison
used archive order, byte hashes, `ffprobe`, decoded RGB frame hashes, and raw
copied elementary-stream hashes.

### Results

- All 15 JPEG source items in the archive are byte-identical to the current
  folder files. Dimensions and decoded pixels are also identical. JW Library
  did not transcode those images.
- Two short AV1 720p60 sign-language clips are byte-identical. JW Library did
  not remux or transcode them.
- Three longer AV1 720p60 clips changed as containers:
  - the AV1 video elementary streams are identical;
  - the source `mov_text` subtitle stream is absent from the exported playlist;
  - the AAC stereo 48 kHz stream has the same nominal bitrate and duration but
    different encoded packets and different decoded PCM, demonstrating audio
    re-encoding rather than a simple container copy;
  - the exported files are about 28-34 KB different in size.
- The closing H.264 song has an identical primary video elementary stream and
  no audio. Its file differs by only 38 bytes, consistent with container
  metadata/remuxing rather than video transcoding.
- Thumbnails are always separate, newly encoded JPEG assets. That thumbnail
  work should not be confused with transcoding the original item.

### Stored-hash anomaly

The iPad export's `IndependentMedia.Hash` values are not always standard
64-character hashes. Each SHA-256 byte was apparently converted to hex without
two-character zero-padding (`0a` became `a`, while `a0` stayed `a0`). This
explains why an initial string comparison falsely reported only 3 matches—the
3 matching digests happened to contain no byte below hexadecimal `10`.

JW Library successfully imports archives produced by this CLI with normal,
complete 64-character SHA-256 values. The CLI therefore keeps correct hashes
and its `inspect` command now reports stored and actual hashes separately,
including whether the old value matches after reproducing that bytewise
unpadded-hex encoding.

### Inference and next experiment

The evidence suggests an iPad import/export pipeline that preserves JPEGs,
copies compatible video bitstreams, drops subtitle streams, and may re-encode
AAC audio while remuxing the MP4. This is an inference from one playlist and
should not yet be generalized to Android or Windows.

A controlled matrix would answer the remaining questions: import small samples
covering H.264/AV1/HEVC, AAC/no-audio, subtitles/no-subtitles, JPEG/PNG, then
immediately export on iPad, Android, and Windows and run the same stream-level
comparison.
