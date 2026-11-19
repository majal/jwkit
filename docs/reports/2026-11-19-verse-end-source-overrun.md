# Verse-end source overrun (FSL Psalm 119:97)

Date: 2026-11-19
Scope: `slverse` end-of-verse window, `ffrife` RIFE output. Measured on the cached FSL 19_119 segment.
Status: label-based end detection implemented in `slverse` (`verse_end=label`, the default). Uncommitted at the time of writing. Delivered files untouched.

## Answer: was it 3 frames, or did RIFE add one?

Neither. The verse-97 marker runs about 9 frames (0.299 s) into verse 98 in the source. RIFE adds none of that: its output time base matches the trimmed source.

- Segment timing: the verse-97 window is absolute [169.779, 181.757], so local [0, 11.978] at 30000/1001 fps.
- Measured label reads (single-frame timestamp seeks, label crop `240:50:85:45`):
  - Verse 97 reads 97 up to local 11.6458 s (segment frame 349).
  - Verse 98 reads 98 from local 11.6792 s (segment frame 350).
- Overrun: 11.978 − 11.679 = 0.299 s, which is 9 frames at 29.97 fps.

Earlier figures in this report (about 10 frames, a switch at frame 349 near 11.645 s, and RIFE doubling the overrun) were wrong. They came from multi-frame `select`+`tile` extraction, which gave wrong label reads, and from timestamp grabs read as frame boundaries. The per-frame measurement above replaces them.

## Both sides of the boundary are mistimed

The true boundary is absolute 181.458 s (169.779 + 11.679). Verse 97's marker ends 0.299 s late, at 181.757. Verse 98's marker starts at 181.758, which is also 0.299 s late, so the first 9 frames of verse 98 are not in its own clip. The windows do not overlap in marker time. Both markers sit on the same wrong boundary.

Caveat: the 98 start comes from the label read and the index, not from a separate measurement of verse 98's own clip.

## Delivered file

`Psalms_119_97_FSL_cut_rife.mp4` (701 frames, 11.683 s, 60/1) was cut by 0.333 s, about 10 source frames. That is one frame more than the 9-frame overrun, so it ends about one source frame before verse 98 begins. Not re-verified frame by frame here, and not replaced. Regenerating it needs the user's approval.

## Design

Label-based end detection, with the marker as an upper bound:

1. Compute the marker end as before. It is never extended.
2. Scan the `verse_end_search` seconds (default 1.5) before the marker end, decoding only the verse-number label crop. Frame 0 of the scan is the baseline for the current verse.
3. The first frame whose label differs from the baseline by more than 12 mean absolute difference is the boundary. End the window there with output-side `-t`, which is exact (609a490 and 6b8d1fa).
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

Config keys in `~/.config/jwkit/slverse/config.toml`, each with a one-run flag on `extract`:

- `verse_end` = `label` (default) or `off`. Flag: `--verse-end {label,off}`. `marker` was considered and dropped as redundant with `off`.
- `verse_end_search` = `1.5` seconds. Flag: `--verse-end-search`.
- `verse_label_crop` = `85,45,240,50`. Flag: `--verse-label-crop`.

`slverse --help` does not list these. They appear under `slverse extract --help`.

## Open questions

- Is the overrun constant or per verse? A dry-run survey of cached FSL, SPE and ASL segments with the detector (no encoding) is still needed.
- Frame-count discrepancy in the cached segment (ffprobe 1037 total frames; earlier partial reads 1028 and 1030). It does not change the 97 boundary but should be reconciled before a test asserts frame counts.
- Verse-98 head: the fix needs a pre-roll fetch margin in `resolve_cached_source` and `download_segment`, plus remaps of `verse_reference_windows`, `overlay_fade_outs` and `add_verse_chapters`. Not started; needs approval.
- A hand or occlusion across the label could read as a label change. The stability check and the ledger reduce this risk; they do not remove it.
- SPE 119:97 may carry a similar overrun. Not checked and not changed.
- `FfrifeLongRunTest.test_chunks_assemble_exact_target_and_resume` is timing-sensitive and fails under CPU load. Not addressed here.
