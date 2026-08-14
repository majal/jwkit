# Proposal: AI video inpainting as a `delogo` alternative in `slverse`

**Status:** design only, not implemented. Written as a cold-start handoff — read this end to end before touching code, it has the research and the decisions already made so you don't have to re-derive them.

**Context for whoever picks this up:** this was designed in a live conversation with the repo owner where I (a prior Claude Code session) verified everything empirically against real JW.org content before writing this doc — pulled real API metadata, downloaded real clips, extracted real frames, ran real `ffprobe`/`ffmpeg` commands. Where a claim below says "confirmed," it means I actually watched the frames or ran the command, not that I'm inferring from general knowledge. Where I couldn't verify something (mainly: E2FGVI-HQ's exact license, and VRAM/speed numbers on real 720p JW content for either tool), I've said so explicitly — don't present those as more certain than they are.

## The problem

[`slverse`](../../slverse) extracts Bible verses from JW.org's Sign Language videos and overlays a replacement verse-reference (delogo-blur the source's own burned-in caption, draw the correct one on top — see `build_overlay_filter` in `slverse`). `delogo` is ffmpeg's static-rectangle blur filter: it has zero motion-awareness, so when an ASL signer's hand passes in front of the caption box, the hand gets blurred along with the caption underneath it. This looks bad and is the one visible defect left in the overlay pipeline (everything else — accurate caption sizing, verse-reference-language skipping, fade/endscreen trimming — was already fixed in this session; see `slverse`'s git log for `2026-08-14`).

The repo owner's own framing, which the design below follows exactly: hand-occlusion probably doesn't happen on most clips, so don't pay AI-inpainting cost by default — detect whether `delogo` would actually fail on a *given* clip, and only reach for inpainting on that one.

## Research findings (verified 2026-08-14)

Two real candidates were investigated: **ProPainter** and **E2FGVI-HQ**. Both are legitimate, actively-cited video-inpainting research tools, not vaporware.

### ProPainter ([sczhou/ProPainter](https://github.com/sczhou/ProPainter), ICCV 2023)

- **VRAM:** 25GB (fp16) / 28GB (fp32) at 720p with the default 80-frame chunk size. 8GB(fp16)/13GB(fp32) at 480p. Comfortably fits consumer GPUs only around 320×240 or smaller without tuning. Our clips are 1280×720 (JW's own `720P` label) — **25GB is a real blocker** for most consumer cards (a 24GB RTX 4090 is *just* under; most people have 8–16GB).
  - Reducible via `--fp16`, smaller `--resize_ratio`/`--width`/`--height`, smaller `--neighbor_length`, larger `--ref_stride` — but each of those is a quality/VRAM tradeoff, not a free win.
- **Speed:** minutes per clip, not seconds. RAFT optical flow computation (`--raft_iter`, default 20) adds real latency on top of the inpainting network itself.
- **CLI:** `python inference_propainter.py --video <path> --mask <path>`. The mask can be **a single static image applied to every frame** — this matches our use case exactly, since the delogo box is a fixed rectangle for the whole clip. Weights (`ProPainter.pth`, `recurrent_flow_completion.pth`, `raft-things.pth`) auto-download on first run.
- **License: non-commercial S-Lab license.** This matters — confirm the repo owner is fine with that constraint before shipping, especially since JW.org content redistribution already has its own separate considerations this proposal doesn't attempt to resolve.
- Not independently verified against a real JW clip in this session (no GPU available in the sandbox this was designed in) — the CLI shape and VRAM numbers above are from the project's own README/docs, not from a live test run.

### E2FGVI / E2FGVI-HQ ([MCG-NJU/E2FGVI](https://github.com/MCG-NJU/E2FGVI), CVPR 2022)

- Base **E2FGVI** forces the input down to a fixed 432×240 — too low-res for our 720p output without an extra upscale pass afterward (itself a quality-losing step). **Not a good fit as-is.**
- **E2FGVI-HQ** is the variant to use: preserves native resolution, and `--set_size --width 1280 --height 720` explicitly targets our output size.
- **Speed:** the paper reports 0.12s/frame on a 2017 Titan XP (~12GB VRAM) at the base model's 432×240 resolution — "~15× faster than prior flow-based methods." **No published number exists for HQ at 720p specifically** — it will be meaningfully slower than that headline figure at full resolution, but the underlying architecture (a single flow-guided propagation network) is lighter than ProPainter's propagation-plus-Transformer design, so it should land somewhere between "fast" and ProPainter's "minutes."
- **CLI:** `python test.py --model e2fgvi_hq --video <path> --mask <path> --ckpt release_model/E2FGVI-HQ-CVPR22.pth --set_size --width 1280 --height 720`. Mask argument is `required=True` — same static-image-mask approach should work, matching ProPainter's usage (not independently confirmed for E2FGVI-HQ specifically — verify against the actual repo before relying on it).
- **License: not confirmed.** I could not get a clean answer via web search in the session that produced this doc. **Check `github.com/MCG-NJU/E2FGVI`'s LICENSE file directly before building on this** — don't assume it's more permissive than ProPainter's just because I couldn't pin it down.

### Bottom line

**Neither tool is "cheap."** Both are real GPU jobs at minutes-or-tens-of-seconds scale, nowhere near `delogo`'s near-zero cost (a trivial per-frame pixel blur). So "just always run inpainting" is not viable — the detect-then-selectively-inpaint design below is the right shape, not a compromise.

## The cheap part: detecting whether `delogo` would actually fail

This is the one piece I *did* verify empirically and it's genuinely easy: JW's Sign Language videos are shot against a **flat, near-uniform dark gray backdrop** with zero texture, confirmed by pulling and visually inspecting real frames from a Psalm 16:11 (ASL) and a Revelation 13 (ASL) clip in this session. A signer's hand crossing through the delogo box (skin tone, high contrast against flat gray) is a strong, trivially-detectable color deviation.

Proposed detector (`delogo_engine = "auto"`, see below):

1. Sample a handful of frames across the delogo box's active time window (every ~0.5–1s is plenty — this doesn't need every frame).
2. For each sampled frame, crop to the delogo box region (`build_overlay_filter` already computes this box's x/y/w/h).
3. Compare the box's own pixels against a reference sampled from *immediately outside* the box in the *same frame* (not a hardcoded gray value — this makes it robust to per-video lighting/backdrop variation without needing to hand-tune a color constant).
4. If enough pixels inside the box deviate significantly from that local reference, flag "occlusion detected" for this clip.
5. No new dependency needed — `ffmpeg` frame extraction + either `ImageMagick` (already a soft dependency, see `measure_text_size` in `slverse` for the existing pattern of shelling out to it) or a plain pixel comparison covers this. Sub-second cost, cheap enough to run by default on every extraction.

This hasn't been implemented or tested — it's a specific, scoped starting point, not a vague idea. Build it as a standalone function first (e.g. `detect_delogo_occlusion(source, box, start_time, end_time) -> bool`) and unit-test it against the same real clips referenced below before wiring it into the extraction pipeline.

## Recommended design

### 1. New config surface (mirrors existing `interpolation_engine`/`hardware_encoder` patterns in `slverse`'s `DEFAULT_CONFIG`)

```python
"delogo_engine": "blur",          # blur (current default, near-zero cost) | inpaint (always use the AI engine) | auto (cheap-detect first, inpaint only if delogo would actually fail)
"delogo_inpaint_backend": "e2fgvi-hq",  # e2fgvi-hq | propainter - which engine "inpaint"/"auto" delegates to
"delogo_inpaint_fallback": "blur",      # what to do if the configured backend isn't installed - matches ffrife's rife_fallback_engine pattern
```

Add corresponding `CONFIG_HELP` entries (see `slverse`'s existing `CONFIG_HELP` dict — every `DEFAULT_CONFIG` key must have one, and `SlverseConfigCommandTest.test_every_default_config_key_is_documented` in `tests/test_slverse.py` enforces this at test time, so you can't skip it).

### 2. Sibling-tool architecture, following `ffrife`'s established pattern exactly

`slverse` already delegates AI frame interpolation to a sibling tool (`ffrife`, loaded lazily via `load_ffrife()` in `slverse` — only imported when `interpolation_engine = rife` is actually used, so the dependency never loads for people who don't use it). Do the same here: a new sibling tool, something like `ffinpaint` (matching the repo's no-`jw`-prefix naming convention — see [`AGENTS.md`](../../AGENTS.md)'s Naming section), with its own config namespace at `~/.config/jwkit/ffinpaint/` (see `AGENTS.md`'s Configuration section for the shared-namespace convention every jwkit tool follows), its own `setup` flow for downloading/locating the chosen backend, and a small `interpolate`-style entry point `slverse` calls into — mirroring `ffrife.interpolate(source, output_file, config, start=..., end=..., vf=..., fps=...)`'s existing shape.

Two backends behind one interface, user picks which to install (exactly the "let the user decide which to install, just like rife" requirement) — `ffinpaint setup` should ask which backend (or neither) the same way `slverse setup` already asks about `interpolation_engine`.

### 3. Single encode pass — this composes with the existing pipeline, doesn't add a second lossy generation

Both inpainting tools take PNG-frame-sequence-in, PNG-frame-sequence-out (confirmed from their CLI shapes above) — **exactly the same shape RIFE already uses** (see `ffrife.interpolate`: PNG extraction and RIFE itself are lossless, only the final merge encode is lossy — this is already documented in `extract_verse`'s own docstring in `slverse`).

So when a clip needs *both* inpainting and 60fps interpolation, chain them on the same lossless PNG relay:

```
extract frames (lossless) → inpaint (PNG→PNG, lossless) → RIFE if requested (PNG→PNG, lossless, doubles frame count) → ONE final lossy encode
```

This doesn't require inventing new plumbing — `extract_verse` in `slverse` already branches on `engine == "rife"` to hand off to `ffrife`; the natural extension is for `ffrife.interpolate` (or a shared helper both `ffrife` and `ffinpaint` call into) to accept an *already-extracted* PNG directory as an alternative to extracting from the source itself, so the two tools can hand frames to each other without a video re-encode in between. Check `ffrife.py`'s actual PNG extraction code before assuming this refactor is trivial — it may need its own small interface change to support "frames already extracted" as an entry point.

### 4. Rollout order

1. Build and unit-test `detect_delogo_occlusion` standalone (no AI dependency, pure `ffmpeg`+`ImageMagick`/pixel-math) — this is useful on its own even before any inpainting backend exists, e.g. as a `slverse extract --write` warning ("hand may cross the delogo box in this clip") without doing anything about it yet.
2. Stand up `ffinpaint` with **E2FGVI-HQ only** first — lighter, native-resolution-capable, no confirmed license blocker (though: *verify the license yourself before writing this sentence into user-facing docs* — I couldn't).
3. Wire `delogo_engine = auto` end to end for that one backend, verify live against a real ASL clip with an actual hand-crossing occlusion (the repo owner mentioned Psalm 16:11 ASL has this issue — start there, same clip already used to verify the fade/endscreen-trim work in this session's git history).
4. Add ProPainter as a second opt-in backend once E2FGVI-HQ's integration pattern is proven out, with the non-commercial-license caveat surfaced clearly in `slverse setup`'s interactive flow and in `docs/slverse.md`.

## Open questions / risks for whoever builds this

- **E2FGVI-HQ's license is unconfirmed.** Check `github.com/MCG-NJU/E2FGVI/blob/master/LICENSE` (or equivalent) directly before committing to it as the "safer" default over ProPainter.
- **No GPU was available in the session that wrote this proposal** — none of the VRAM/speed numbers above were verified against real 720p JW footage, only against the projects' own published figures (which were themselves measured on different content/resolutions). Budget real time to benchmark both against an actual JW clip before finalizing which one ships as the default `auto`-mode backend.
- **The occlusion detector's false-positive/false-negative rate is unknown** until it's actually built and run against a decent sample of real clips across multiple sign languages (backdrop color/lighting may not be as uniform in every JW SL production as it was in the two ASL clips checked in this session).
- **Weights auto-download size** wasn't checked for either tool — confirm this before assuming `ffinpaint setup` can behave like `ffrife setup`'s existing "download on demand" flow without surprising someone on a slow connection.

## Reference material

- [ProPainter GitHub](https://github.com/sczhou/ProPainter) / [inference script](https://github.com/sczhou/ProPainter/blob/main/inference_propainter.py)
- [E2FGVI GitHub](https://github.com/MCG-NJU/E2FGVI)
- Existing `slverse` code to read before starting: `build_overlay_filter`, `extract_verse`, `has_audio_stream` (added 2026-08-14, same audio-presence-probing pattern will likely be needed again for inpainting's own PNG→video merge step), and the whole of `ffrife.py` as the architectural template.
- `tests/test_slverse.py`'s existing test classes for `build_overlay_filter`/`extract_verse` show the mocking patterns already established in this repo (stub `subprocess.Popen`/`run_ffmpeg` via `mock.patch.object` + `addCleanup`, **never assign directly to `self.slverse.subprocess.Popen`** — that mutates the real global `subprocess` module and silently breaks unrelated tests elsewhere in the suite; this exact mistake was made and caught in this session, see `SlverseLaunchMpvTest`'s `setUp` docstring for the postmortem).
