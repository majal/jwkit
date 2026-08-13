# `jwvideo-mux`

[← Back to README](../README.md#table-of-contents)

`jwvideo-mux` is an automated media downloader and muxer for jw.org videos.

It downloads a jw.org video and merges the language tracks you want into one file, so you get a single video with selectable audio and subtitles instead of a separate download per language.

## What It Does

- Extracts a `docid` from a jw.org video URL, accepts it directly, or accepts an existing local video file.
- Traces the jw.org API to automatically download the necessary MP4 videos, MP3 audio, and VTT subtitle files for multiple requested languages.
- Intelligently merges multiple audio tracks (and their subtitles) into a single MKV file.
- Defaults to MKV as the export container, with an option to export to MP4.
- Embeds VTT subtitles directly into the video container.
- Offers to automatically install `ffmpeg` if not found.
- Has an optional cleanup flag to trash temporary source files after successful muxing.
- Can create single-stream audio/video files instead of merged ones, replacing the base track, which helps with platforms that play all audio streams simultaneously.
- If you include a language in both `--video` and `--audio` (e.g., `--video E --audio E,TG`), the script is smart enough to download the MP4 exactly once and map its video and audio streams seamlessly.
- **Sign Language:** If a language does not have an MP3 (common for sign languages), the script will automatically fall back to downloading its MP4 to use as the track source.

## Supported Platforms

- macOS
- Linux
- Windows

## Dependencies

- [Python](../README.md#python)
- `ffmpeg` must be installed and available on your PATH. The script offers to install it automatically if it is missing.

## Install / First Run Summary

Make the script executable if your checkout did not preserve executable bits:

```bash
chmod +x jwvideo-mux
```

For a simpler, double-click experience without using the command line, create a wrapper script as detailed in the [Friendly Launchers](../README.md#friendly-launchers) section.

## Common Usage Examples

Download and merge a video by URL using the default languages:

```bash
./jwvideo-mux "https://www.jw.org/finder?wtlocale=E&docid=502015752"
```

```bash
# Basic usage: English video with English, Tagalog, and Cebuano audio
./jwvideo-mux 502015752 -v E -a E,TG,CV
```

Download and merge specific languages (e.g., French base video with English, Spanish, and French audio), output to MP4, and clean up source files:

```bash
./jwvideo-mux 502015752 -v F -a E,S,F --container mp4 --cleanup
```

Produce separate, single-stream videos replacing the audio instead of merging them all into one:

```bash
./jwvideo-mux 502015752 -v E -a E,TG,CV,HV,SA --single-streams
```

Use a pre-downloaded local file:

```bash
./jwvideo-mux video_FSL_720p.mp4 -v FSL -a E,S
```

## Important Behavior / Defaults

- `-v, --video`: Comma-separated languages for video tracks (default: `E`)
- `-a, --audio`: Comma-separated languages for audio tracks (default: `E,TG,CV,HV,SA`)
- `-s, --subs`: Comma-separated languages for subtitles. If omitted, automatically fetches subtitles for all requested video and audio languages.
- `-r, --res`: Target video resolution (default: `720p`)
- `-c, --container`: Export container format, `mkv` or `mp4` (default: `mkv`). *Note: MKV is recommended for robust multi-track and native WebVTT subtitle support.*
- Spoken languages prefer downloading the much smaller MP3 files. Sign languages download the MP4 file to preserve the video track.
- Automatically tags audio and video streams with ISO 639-2 codes and display names.
- `--analyze-video-variants` compares selected video-language files without
  muxing or deleting media. It reports byte-identical video groups and only
  sustained, per-pair visual-difference *candidates*; candidates must be
  reviewed before using them for a space-saving split library. Each
  non-identical pair is classified as `exactly_same` (byte-identical),
  `visually_same` (SSIM and PSNR both agree there's no sustained difference —
  this is the classification for the common case of the same footage just
  encoded differently), `localized_candidates` (SSIM *and* PSNR both agree on
  the same sustained-drop range — a real, corroborated candidate), or
  `review_recommended` (the two metrics disagree; treated as "don't guess,
  ask a human"). Requiring two independent metrics to agree before calling
  something `localized_candidates` is a deliberate trade of a little recall
  for a lot less confidently-wrong output — a single metric (plain SSIM) was
  previously enough to misclassify same-content-different-encode video as
  different. A language whose video is only a different *resolution* than
  the reference (same aspect ratio — e.g. a lower-bitrate 960x540 encode of
  an otherwise 1280x720 talk, which jw.org publishes for some languages) is
  no longer skipped as incompatible: it's transparently scaled onto the
  reference's pixel grid for comparison, so real localized differences on a
  lower-res encode still get found automatically. It's a same-content-safe
  operation only because it's aspect-ratio-preserving; a real shape mismatch
  (letterboxed/pillarboxed) still requires the human-confirmed
  `--manual-overrides` + `--normalize-mismatched-aspect` path below, since
  that requires guessing a crop offset.
- `--variant-min-seconds` (default `1.5`) sets how long a similarity drop must
  hold before it counts as a candidate. Sub-second dips are almost always
  ordinary encoding jitter (a fast pan, a busy texture), not real localized
  content, so the default deliberately sits well above single-frame noise.
- `--dedupe-identical-video` keeps one video stream from each byte-identical
  group while retaining every requested audio and subtitle track. It is opt-in
  and uses an elementary-stream SHA-256 test, not a visual similarity guess.
- `--dedupe-visually-same` reuses the reference video for languages verified
  `exactly_same`/`visually_same` instead of muxing in their own video track.
  Because this relies on a heuristic rather than a byte-exact test, it prints
  the evidence and asks for confirmation before applying (skip the prompt
  with `--force`).
- `--adaptive-mpv-library` exports a space-saving mpv-oriented library instead
  of muxing: one shared common video-only file per stretch where every
  language matches the reference, one small video-only file per language
  wherever it was corroborated as actually different, full per-language audio
  and subtitles, a per-language mpv EDL presentation, and a `manifest.json`
  tying it together (source hashes, tool versions, cut points, and any mpv
  validation results). It never touches or deletes source files and always
  asks for confirmation before writing (skip with `--force`). If analysis
  finds no corroborated localized differences for any language, there's
  nothing to adapt, so it falls back automatically to an ordinary single-file
  mux with one shared video track (like `--dedupe-visually-same`) written
  directly to the output directory instead of building an unnecessary EDL
  library folder. Play a language with e.g. `mpv presentation-tg.edl
  --audio-file=audio-tg.mka --sub-file=subtitles-tg.srt`, or just
  double-click the generated `.jwplay` launcher file — no terminal needed.
  That launcher lands in the *output directory* (the unit root, one level up
  from the library folder) by default, named after the same
  `{docid}_{lang}_{res} (Title)` convention the source downloads and the
  classic single-file mux use (just the reference file's own name with the
  language field swapped for that launcher's language), so multiple videos
  in the same unit never collide; pass `--launchers-in-video-folder` to put
  it back inside the library folder instead (the old default). The library folder
  itself is just the video's own sanitized name — no `_adaptive-library`
  suffix. It, and every file in it, has any `:` (and other characters
  Windows/NTFS forbids) stripped from its name even if the source video's own
  filename has one — macOS Finder renders a literal `:` in a filename as `/`,
  which reads as a real path separator and is genuinely confusing to run
  into. Cut points are snapped **once, globally, to the reference video's own
  keyframes** and every segment then covers exactly that shared window, so
  all languages agree on where each boundary is. This exactness is the whole
  contract: a presentation interleaves common segments (from the reference)
  with localized clips (from a *different* file), so a segment covering even
  slightly more than its window replays content at the splice, and slightly
  less skips it. Consequently the reference is split in a single stream-copy
  pass with ffmpeg's segment muxer — the "main" video is never re-encoded,
  and this is much faster than one invocation per segment — while each
  localized clip (short by construction: a title card, a name plate) is
  re-encoded to land precisely on the shared boundary, since its own file
  generally has no keyframe there and a stream copy can only start on one.
  `manifest.json` reports how many clips this affected via
  `reencoded_segments`. Frame counts are pinned explicitly rather than left
  to a duration flag: with B-frames (universal in real jw.org H.264) a
  duration-bounded stream copy is bounded by *decode* order and drags in a
  frame or two past the requested end — which not only duplicates frames at
  the splice but makes the concatenated video longer than the source while
  the per-language audio stays full-length, drifting the two apart
  progressively (measured on real footage at roughly a second across a
  15-segment library). mpv validation spot-checks the start, the end, and a moment
  around every splice boundary rather than decoding the whole presentation
  front to back — headless mpv decode runs at roughly 2-3x realtime here, so
  a full decode of an hour-long talk could take 20-30 minutes just to
  validate; spot-checking catches the failure mode that actually matters (a
  bad splice) in a few seconds per checkpoint regardless of runtime. If a
  `--manual-overrides` entry confirms a real difference on a pair that's
  otherwise a different resolution (e.g. a pillarboxed remaster), the
  library still builds — mpv plays through a mid-presentation resolution
  change without erroring, but by default the manifest warns that the video
  window will visibly resize at that splice. Pass
  `--normalize-mismatched-aspect` to avoid that: it center-crops and
  re-encodes just that language's short localized clips to the reference's
  exact aspect ratio and resolution (e.g. a 16:9 insert cropped down to a 4:3
  reference), so mpv never has to resize mid-presentation. The shared
  common/reference segments are never touched by this — only the
  short, already-localized clips of the mismatched language(s) are
  re-encoded, at a balanced `libx264 -crf 20` (not stream-copied, since
  cropping/scaling requires decoding).
- `--scan-small-regions` (with `--region-count`, default `8`) additionally
  splits the frame into horizontal bands and compares each one, because a
  small graphic — a name plate, a lower-third caption — can be too small to
  move the whole-frame SSIM/PSNR average even though it's clearly visible.
  This is slower (one extra crop+compare pass per band, still just one
  decode) and it is *never* allowed to promote a comparison straight to
  `localized_candidates` on its own: real-footage calibration showed
  region-level SSIM and PSNR each independently miss real small differences
  on some clips and false-trigger on busy/detailed ones on others, so neither
  is trustworthy enough alone to auto-confirm. Instead it either bumps a
  `visually_same` verdict to `review_recommended` with the candidate's frame
  band, time window, and cross-language corroboration count attached, or — if
  the pair is already `localized_candidates` — records any extra window it
  finds outside the already-confirmed ones as `additional_region_windows`
  (useful context for planning an adaptive-library split, without touching
  the already-confident result).
- Duration mismatches beyond the usual tolerance aren't always a real
  problem: a video that ends by holding a static end-card/copyright screen
  for a different length per language will otherwise be rejected as
  `incompatible` even though the actual content is identical. `analyze-video-variants`
  now checks for a *trailing freeze* (via ffmpeg's `freezedetect`) on both
  languages — a final frame held with no motion all the way to end of file —
  and if both freeze around the same point, treats the pair as compatible,
  comparing only up to the shared freeze point. The held tail itself is
  never compared and simply falls back to the reference language when
  building an adaptive library. Look for `trailing_freeze_note` and
  `effective_duration` in a comparison's JSON to see when this kicked in.
- `--manual-overrides <path>` lets a human-audited TOML file (the same
  schema used for `_localization-audit/ground-truth.toml`: a list of talks,
  each with one or more videos identified by anchor filename, the languages
  they were checked against, and either `whole_video_same = true` or a list
  of timed `differences`) take precedence over automatic detection for local-
  file-mode SCE-layout input. It's matched by the exact talk-folder name and
  anchor filename, so one file can cover an entire library and gets reused
  across every invocation. A difference confirms a real `localized_candidates`
  window even if the detector missed it; one marked `fallback_ok = true`
  means "yes, this differs, but it's fine to just show the reference here"
  and gets subtracted back out of `intervals` even if the detector (or an
  earlier automatic pass) had already flagged it — useful for a closing
  credits card nobody needs translated. Auto detection and manual overrides
  are meant to work together: run the detector first, let a human resolve
  whatever it marks `review_recommended` or `incompatible`, and record the
  verdict in the overrides file so future runs on the same library don't
  need to ask again.

## Notes / Caveats

- JW Library currently plays all audio tracks simultaneously when given a multi-audio MP4 file. To avoid this when using JW Library, use the `--single-streams` flag.
- Trashing functionality using `--cleanup` simply unlinks (deletes) the downloaded files.

[↑ Back to README TOC](../README.md#table-of-contents)
