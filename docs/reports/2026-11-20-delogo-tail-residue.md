# Caption residue in the last frames of a BVL RIFE clip (Proverbs 2:11)

Date: 2026-11-20
Scope: `slverse` overlay/delogo path and `ffrife` RIFE + `output_vf` path. Measured on the delivered `02 Proverbs_2_11_BVL_rife.mp4` (AV1, 1280x720, 28.733 s, 60 fps target) and a re-run of caption detection on its local source.
Status: fixed on the code side, verified on the BVL clip. Delivered file untouched.

## Result (2026-11-20)

- Fix: delogo now runs before RIFE (`vf`), so RIFE never sees the source caption. Committed in e827b6e. `output_vf` is part of the ffrife job signature (106a153).
- Verification: rendered the source tail (186–192.2 s) through `ffrife.interpolate` with RIFE (372 frames, RIFE binary, not the fallback) at three settings:
  - no delogo: the caption is visible in the RIFE output, so the probe works;
  - delogo at the old box (w=218, right edge x=315): flat background (~72) in x 300–322 in every frame, including even frames;
  - delogo at the box +4 px (w=222, right edge x=319): also flat, no gain over the old box.
- Decision: the right-edge widen (item 1) was tried and reverted. With delogo before RIFE it is not needed on this clip, and it would have widened every detected box. Reverting it is the safer default.
- Not checked: a second BVL clip (the report asked for two clips before changing a default). If residue shows up on another clip, reintroduce a right-only pad in the detected branch of `build_overlay_filter`.
- Tests: `python3 -m tests` 831 OK. The slverse suite is 253 OK.

## Answer

The residue is a RIFE ghost of the source caption's right edge, in the interpolated (even) output frames only. The `delogo` box is too tight on the right side, so the ghost lands just outside it and `delogo` never touches it. Confidence: high on where the residue is (frame parity, columns), medium on the exact mechanism (RIFE spreading the edge is inferred from the pattern, not reproduced in isolation).

## What the frames show

- Source frames: the caption element is bright at x 312-315 only at the clip end (about t = 191.9 s). Beyond x 315 the background is flat (about 72).
- Output frames, last 7 (f_01 to f_07): f_01, f_03, f_05, f_06, f_07 are clean (flat 71-73 in x 312-319). Replacement "1" renders cleanly in all of them.
- f_02 and f_04 (interpolated, even) show 88-91 at x 312-315, fading to 72 by x 318-319. That dim band sits just right of the replacement "1".
- So the artifact is: parity-specific (even frames only), at the right edge of the delogo box, and extends about 4 px past it.

## Why it happens

Order in the pipeline: `slverse` passes the overlay (including `delogo`) as `output_vf`. `ffrife` applies `output_vf` after RIFE, per frame (`ffrife` ~3472 for the ffmpeg fallback, ~3527 for the RIFE stream, ~3070 per streamed segment). So `delogo` runs on RIFE output, not on the source.

1. Source caption element sits at x 312-315 at the clip end. It is inside the delogo box (box covers x 98-315).
2. RIFE generates even frames by blending and warping the source frames around them. The bright edge is smeared a few px right, into x 316-319.
3. `delogo` on the output replaces pixels inside the box using border pixels. The smear at 316-319 is outside the box, so it survives.
4. Odd frames are source-timed, so there is no smear and they are clean. That matches the parity pattern.

Supporting evidence:
- Detected box for this clip is (100, 57, 214, 24) from `detect_caption_box`. The delogo box is x=98 y=55 w=218 h=28, so the right edge is at x=315. The estimated box would extend further (`ESTIMATOR_MARGIN = 5` on each side plus `delogo_width_pad`).
- On a clean source frame, the detected box shows faint vertical striping inside it. The estimated box is flat. The detected box is tight enough to leave source edge detail in place.

Not confirmed: that RIFE is the spreader. A direct test would be to render a short clip ending on this caption with `output_vf` disabled and compare even frames. I did not run it.

Hypothesis ruled out: that the unblurred source is carried past the verse window by RIFE. `output_vf` has no time `enable`, so it applies to every frame in every path, and the replacement caption is clean.

## Production path

Production detection runs on a local source (`extract_verse` at `slverse` ~3601 and ~3621 uses `local_path` from `resolve_cached_source` unless extract mode is `onthefly` or the preview source is remote). So the detected box branch (`build_overlay_filter` ~1583-1590) is what runs in normal use, not the estimated one. The tight box is the default outcome.

## Related risks found while reading (not the cause here)

- `ffrife` `resume` defaults to `"true"` (DEFAULT_CONFIG line 126). Durable work dirs are keyed by `_job_signature(source, output_file, options)` (~2571). The `options` dict in `interpolate` (~3510) includes `vf` but not `output_vf`. Changing the delogo box or any `output_vf` setting for the same source and output path therefore reuses segments already encoded with the old `output_vf`. Not reproduced; read from code.
- The resume shortcut in `render_rife_frames` (~3242) returns an existing `video.mkv` without reapplying `output_vf`. Same stale-output risk, same trigger.
- `verse_end_ledger.json` records the verse-end markers and label settings, but not the delogo box or branch. A cached result can't be checked for the overlay settings it was made with.

## Options to prevent recurrence

Ranked by effort and risk. Items 1 and 2 are the smallest.

1. **Widen the right side of the detected box.** Raise `delogo_width_pad` (default 2) to about 6, or apply a right-only extra pad in the detected branch. Covers the 316-319 smear. Low risk; may cover a few px of background on other clips. Verify on this clip and one other BVL clip before changing the default.
2. **Use a fixed margin on detected boxes.** Apply `ESTIMATOR_MARGIN`-style padding to the detected branch as well. Same effect as item 1, slightly bigger coverage on all sides.
3. **Run `delogo` before RIFE.** Pass the overlay as `vf` (pre-RIFE) instead of `output_vf`. RIFE then never sees the source caption, so there is nothing to smear. Biggest change: it affects every frame's input and the RIFE cost is unchanged. Needs a test on a full clip, and it may interact with the cut handling that sits on source timing.
4. **Add `output_vf` to the job signature.** In `interpolate` (~3510), include `output_vf` in `options`. Any overlay change then starts fresh work instead of reusing segments. Small, safe. Recommended regardless of the others.
5. **Reapply `output_vf` on the resume shortcut** (~3242), or refuse to reuse a joined `video.mkv` when `output_vf` differs from the one it was built with. Pairs with item 4.
6. **Make detection work for URL sources.** `detect_caption_box` returns None for http(s) sources, so those jobs fall back to the estimated box. Only relevant if `onthefly` is used on a shared clip.

Suggested order: item 4 and item 5 (correctness of resume), then item 1 (visible fix), then test item 3 separately if the residue shows up on more clips.

## Checks not done

- No render with `output_vf` disabled alone, so the RIFE-spread mechanism is inferred from the fix's effect, not isolated.
- The second BVL clip is not checked.
- The resume-staleness risks (items 4 and 5) were from reading code; item 4 is fixed in 106a153, item 5 is not done.
