# Verse-end source overrun (FSL Psalm 119:97)

Date: 2026-11-19
Scope: `slverse` end-of-verse window, `ffrife` RIFE output. Measured on the cached FSL 19_119 segment.
Status: study and design only. No code changed. Delivered files untouched.

## Answer: was it 3 frames, or did RIFE add one?

Neither. The overrun is about 10 source frames (0.333 s), it is in the source, and RIFE added nothing.

- Index marker for verse 97: start 00:02:49.779, duration 11.978 s, so the window ends at segment time 11.978 s (about frame 359 at 30000/1001).
- Visible label change in the source (single-frame timestamp grabs, label crop `240:50:85:45`):
  - 11.60 s: 97, 11.64 s: 97, 11.67 s: 98, 11.70 s: 98, 11.73 s: 98, 11.77 s: 98.
  - The switch is at source frame 349 (about 11.645 s). Frames 349–358 show verse 98 and sit inside the 97 window.
  - Overrun = 11.978 − 11.645 ≈ 0.333 s ≈ 10 frames.
- RIFE output (60/1, 719 frames, uncut): 11.60, 11.63, 11.65 s read 97; 11.67, 11.69, 11.72 s read 98.
  - The output switch is at about 11.66 s, within one output frame (1/60 s) of the source switch.
  - The output duration matches the source window: 719 frames / 60 ≈ 11.98 s. RIFE 2× preserved the time base and reproduced the source's 98 content.

So the 0.333 s the user trimmed is exactly the source's marker overrun. The fix belongs in how we pick the end of the window, not in RIFE.

## Why the earlier numbers were wrong

Earlier summaries cited a 9-frame overrun, "RIFE doubled it", and "frame 349 = 97". None of those held. Multi-frame `select` + `tile` extraction produced wrong label reads, and frame-index grabs disagreed with timestamp grabs. Timestamp seeks (`-ss` before `-i`, single frame, `-frames:v 1`) on the cached segment are the reliable method for this check.

## Design options

| Option | Detection | Cost | Quality | Verdict |
|---|---|---|---|---|
| A. Marker only (today) | none | free | Fails when the marker overruns (this case) | Keep as the upper bound only |
| B. Fixed trim (user's manual 0.333 s) | none | free | Fits one case; wrong for others | Reject as a rule |
| C. Label change scan (last digit) in the last ~1.5 s before marker end | decode a small crop of ~45 frames, compare last-digit ink to the window's baseline | small: decode of a crop, no RIFE re-run to detect | Exact to one source frame | Recommended primary |
| D. Visible-boundary detection by signer/clothing | colour or motion | more code | Not needed; the label is the reliable cue | Reject |

Recommended design (option C with marker as upper bound):

1. Compute the marker end as today; it is an upper bound and is never extended.
2. Scan the last ~1.5 s before the marker end, decoding a single crop of the verse label region. Take the window's first-frame ink as the baseline for the current verse.
3. The first frame whose last-digit ink departs from the baseline (threshold from the 97 → 98 ink step, about 233 → 282) is the verse boundary. End the window there, using output-side `-t` (exact, per 609a490 / 6b8d1fa).
4. If no change is found, fall back to the marker end and log that the boundary was not confirmed.
5. Log each adjustment (verse, marker end, label boundary, frames removed) so overruns can be counted across the library.
6. RIFE stays as is; its output time base already matches the trimmed source.

Cost: the scan decodes about 45 frames of a small crop per verse. That is far cheaper than RIFE, which dominates the run. Quality: exact to one source frame in this case, and it cannot extend past the marker.

## Proposed config and flags (not implemented)

Per AGENTS.md (config-first): `verse_end` with values `label` (default, marker fallback), `marker`, `off`.
- Config: `~/.config/jwkit/slverse/config.toml` key `verse_end`.
- CLI: `--verse-end {label,marker,off}`.
- Keep config, CLI help, docs and tests in sync. Tests use the cached FSL segment and skip when it is absent.

## Open questions

- Is the overrun constant or per-verse? A survey of cached FSL, SPE and ASL segments with the same detector (dry run, no encoding) is still needed.
- Frame-count discrepancy in the cached segment (ffprobe 1037 total frames; earlier partial reads 1028 and 1030). It does not change the 97 boundary, but it should be reconciled before the test asserts frame counts.
- The pacing-dependent test `FfrifeLongRunTest.test_chunks_assemble_exact_target_and_resume` fails under CPU load and passes alone. Not addressed here.
- SPE 119:97 may carry a similar overrun (SPE 98 marker start ≈ 11.491 s segment-relative). Not checked; not to be changed without the user's go-ahead.

## Delivered files

`Psalms_119_97_FSL_cut_rife.mp4` (701 frames, 11.683 s, 60/1) already has the 0.333 s trimmed. Not re-verified frame by frame here, and not replaced.
