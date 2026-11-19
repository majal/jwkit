# Verse-end source overrun (FSL Psalm 119:97)

Date: 2026-11-19
Scope: `slverse` end-of-verse window, `ffrife` RIFE output. Measured on the cached FSL 19_119 segment.
Status: label-based end detection implemented in `slverse` (`verse_end=label`, the default) and pushed (36e64e2); a follow-up fix (below) makes the cut exact. Delivered files untouched.

## Answer: was it 3 frames, or did RIFE add one?

Neither. The verse-97 marker runs about 9 frames (0.299 s) into verse 98 in the source. RIFE adds none of that: its output time base matches the trimmed source.

- Segment timing: the verse-97 window is absolute [169.779, 181.757], so local [0, 11.978] at 30000/1001 fps.
- Measured label reads (single-frame timestamp seeks, label crop `240:50:85:45`):
  - Segment frame 349 (11.6450 s) reads 97; frame 350 (11.6783 s) reads 98. (Earlier notes gave 11.6458 / 11.6792; those were seek targets, not frame times. A seek at 11.6792 lands on frame 351.)
- Overrun: 11.978 − 11.6783 = 0.2997 s, which is 9 frames (350 to 358) at 29.97 fps.

Earlier figures in this report (about 10 frames, a switch at frame 349 near 11.645 s, and RIFE doubling the overrun) were wrong. They came from multi-frame `select`+`tile` extraction, which gave wrong label reads, and from timestamp grabs read as frame boundaries. The per-frame measurement above replaces them.

## Both sides of the boundary are mistimed

The true boundary is absolute 181.458 s (169.779 + 11.679). Verse 97's marker ends 0.299 s late, at 181.757. Verse 98's marker starts at 181.758, which is also 0.299 s late, so the first 9 frames of verse 98 are not in its own clip. The windows do not overlap in marker time. Both markers sit on the same wrong boundary.

Caveat: the 98 start comes from the label read and the index, not from a separate measurement of verse 98's own clip.

## Follow-up: end-to-end check found a leak (fixed)

A real `ffv fsl Psalm 119:97 -fi` run after the first push still ended with 3 verse-98 output frames (703 frames; frame 700 a blend, 701 and 702 verse 98). The cut time was the scan's estimated frame time, 11.6792 s, about 1 ms after frame 350 (11.6783 s), so `-t` kept frame 350. The scan also estimated its frame grid from the seek point, which can sit a frame off the extract's grid, and the first fix attempt was misaligned by one frame twice (a negative first timestamp that a regex dropped; one extra logged timestamp). The shipped fix cuts at the midpoint between frames 349 and 350 from real timestamps, with a half-frame fallback when timestamps are missing.

After the fix: 701 frames, 11.683 s, and no output frame carries the verse-98 label. Trimming happens before RIFE; RIFE adds no source content (350 kept source frames give 701 frames at 60 fps).

The cached segment's frame counts are explained: 1028 real frames; the default constant-rate decode makes 1030 by duplicating across two timestamp gaps near the end (frames 1026 and 1027); the container header says 1037, which is stale.

Ledger: `source_changed` is now also set when the chapter's checksum differs from other windows of that chapter, and `previous_checksum` is kept on later runs.

## Follow-up 2: the head side, record reuse and a survey

Both ends of a verse are late. On FSL 19_119 the verse-97 marker starts 9 frames and ends 9 frames after the real label change, and verse 98 starts 10 frames late; the head scan of verse 98 lands on exactly the same instant as the tail scan of verse 97 (181.4407 s), two independent measurements of one cut. The fix is a head probe: it fetches `verse_end_search` seconds of source before the marker start, finds the label change there, and starts the clip at it. It is skipped when the caller trims the start itself (`-s`, `--window`), since those offsets are measured from the marker start. The first verse's reference label and chapter mark start at the new window start.

Why a detector change was needed: the first version used an absolute difference threshold of 12 taken from one example. A one-digit change such as 96 to 97 differs by only about 6, so it was missed. It now uses the step rule in the design above, and requires the new label in two frames.

Survey of the cached segments (172 verse windows, FSL, SPE, ASL, BVL, INI; scan only, nothing encoded): the markers lag by 1 to 2 frames in most confirmed cases, and by 4 to 10 frames in a few (FSL 19_119 9 to 10, FSL 21_4 verse 9 4, SPE 49_5 verse 29 6). Two of those were checked by eye: SPE Ephesians 5:29 to 5:30 and FSL Ecclesiastes 4:9 to 4:10 flip exactly at the detected frame. Most windows show no confirmed change, usually because the label is steady or the scan is unsure, and then the marker is kept. A wider label crop (85,45,560,50) confirmed fewer cuts than the default (6 against 18 on the tail), so the default stays tight; a long book name can hide the verse number and needs a per-run crop.

Record reuse: a confirmed decision is reused on a later run with the same checksum, settings and algorithm version (`algo` in the entry), without scanning.

## Delivered file

`Psalms_119_97_FSL_cut_rife.mp4` (701 frames, 11.683 s, 60/1) was cut by 0.333 s, about 10 source frames. That is one frame more than the 9-frame overrun, so it ends about one source frame before verse 98 begins. The file is no longer at that path (checked 2026-11-19), so it could not be re-verified; its tail may hold a verse-98 frame or lack the last verse-97 frame, depending on the cut. Not replaced. Regenerating it needs the user's approval.

## Design

Label-based end detection, with the marker as an upper bound:

1. Compute the marker end as before. It is never extended.
2. Scan the `verse_end_search` seconds (default 1.5) before the marker end, decoding only the verse-number label crop. Frame 0 of the scan is the baseline for the current verse.
3. The verse change is the one big jump between neighbouring label frames: the label is a static graphic, so inside a verse neighbours match (difference about 0), while a verse change is at least 3 grey levels (97 to 98 about 30, 96 to 97 about 6) and at least 3 times any other neighbour difference away from it. An occlusion (two jumps) or a fade is unconfirmed, and so is a change seen in only one frame. The cut goes midway between that frame and the one before it, using the frames' real timestamps (`showinfo`, `-fps_mode passthrough`). End the window there with output-side `-t`, which is exact (609a490 and 6b8d1fa).
4. If no change is found, or the tail is unstable, keep the marker end and log it as unconfirmed.
5. Each decision is recorded in `~/.config/jwkit/slverse/verse_end_ledger.json`, keyed per verse window with the source checksum, the settings, the boundary, and the frames cut. A changed checksum sets `source_changed`.
6. Trimming happens before RIFE, so RIFE processes fewer frames. The scan costs about 45 small-crop frames per verse, far less than RIFE.

Option comparison (why this design):

| Option | Detection | Cost | Quality | Verdict |
|---|---|---|---|---|
| A. Marker only (old) | none | free | fails when the marker overruns | kept as the upper bound only |
| B. Fixed trim (manual 0.333 s) | none | free | fits one case only | rejected as a rule |
| C. Label-change scan before marker end | small crop decode | low | exact to one source frame | implemented |
| D. Signer or clothing detection | colour or motion | more code | not needed; the label is reliable | rejected |

## Config and flags

Config keys in `~/.config/jwkit/slverse/config.toml` (`verse_end_search` now covers both ends), each with a one-run flag on `extract`:

- `verse_end` = `label` (default) or `off`. Flag: `--verse-end {label,off}`. `marker` was considered and dropped as redundant with `off`.
- `verse_end_search` = `1.5` seconds. Flag: `--verse-end-search`.
- `verse_label_crop` = `85,45,240,50`. Flag: `--verse-label-crop`.

`slverse --help` does not list these. They appear under `slverse extract --help`.

## Open questions

- Is the lag constant or per verse? The survey above says it varies: mostly 1 to 2 frames, 9 to 10 on FSL 19_119.
- Verse-98 head: done (follow-up 2). `overlay_fade_outs` needed no change: it works from the window's start and end.
- A hand or occlusion across the label could read as a label change. The stability check and the ledger reduce this risk; they do not remove it.
- SPE 119:97 may carry a similar overrun. Not checked and not changed.
- `FfrifeLongRunTest.test_chunks_assemble_exact_target_and_resume` is timing-sensitive and fails under CPU load. Not addressed here.
