# `ffinpaint`

[← Back to README](../README.md#table-of-contents)

## What It Does

`ffinpaint` is an optional bridge from `slverse` to a locally installed E2FGVI-HQ video-inpainting checkout. It removes a fixed caption mask while preserving moving foreground such as a signer’s hand.

## Supported Platforms

macOS, Linux, and Windows where the separately installed backend and its PyTorch dependencies work.

## Dependencies

- `ffmpeg` and `ffprobe`
- A separately installed [E2FGVI-HQ checkout](https://github.com/MCG-NKU/E2FGVI) and its model checkpoint. Upstream is CC BY-NC 4.0; use only where that license permits it.

## Install / First Run Summary

Install E2FGVI-HQ and its Python dependencies yourself, download its `E2FGVI-HQ-CVPR22.pth` weight, then register both paths:

```bash
./ffinpaint setup --root /path/to/E2FGVI --checkpoint /path/to/E2FGVI-HQ-CVPR22.pth
```

## Common Usage Examples

Run the bridge directly with a caption rectangle:

```bash
./ffinpaint run input.mp4 -o cleaned.mp4 --box 88,49,240,60
```

Enable selective use in `slverse`:

```bash
./slverse config set delogo_engine auto
```

## Important Behavior / Defaults

`slverse` defaults to `delogo_engine = blur`. With `auto`, it samples the caption box against its surrounding backdrop and only invokes the configured backend when it sees significant foreground-like variation. If no backend is configured, it safely keeps using blur unless `delogo_inpaint_fallback = error` is set.

Only the detected occlusion window actually goes to the AI backend, not the whole verse - the rest of the clip still gets the cheap blur, with the inpainted result composited on top only while it's active (`slverse`'s `extract_verse`, via `detect_delogo_occlusion`'s returned time range). `delogo_engine = inpaint` (forced, not `auto`) still runs the detector first to try to localize a window; it only falls back to inpainting the *entire* verse if nothing localizes. The mask handed to the backend is also smaller than the blur box itself (`shrink_box_for_inpaint` drops `delogo_width_pad`/`delogo_height_pad`'s extra safety margin, which inpainting doesn't need the way a static blur does) - less area and less time for the model to process, which matters a lot against a GPU-minutes-per-clip backend.

The unmodified upstream E2FGVI runner writes an MP4 itself, so its current integration has an intermediate encode before slverse draws the final caption. RIFE and inpainting intentionally do not compose yet; that waits for a backend with a supported PNG-output interface.

## Notes / Caveats

**No practical GPU path on Apple Silicon today.** E2FGVI-HQ's own code only checks `torch.cuda.is_available()`, with no Apple `mps` fallback - so on a Mac it always runs on CPU, however much VRAM the machine's GPU has. VideoToolbox's AV1 pattern doesn't apply here: this isn't about ffmpeg, it's PyTorch device selection inside the upstream runner itself, which `ffinpaint` doesn't (and, without patching upstream, can't) change. A CUDA GPU is the only currently-practical way to run this at real speed; CPU-only execution works but is expected to be far slower than a GPU pass, consistent with every published benchmark for this model being GPU-measured (see `docs/proposals/delogo-inpainting.md`'s research notes) - budget real time before enabling `auto`/`inpaint` as a default on a CPU-only machine, and measure your own footage before trusting the numbers here for a different one.

`ffinpaint` neither downloads nor redistributes upstream code or weights. The occlusion detector's false-positive/false-negative rate is still unverified against a broad sample of real clips across multiple sign languages - it was tuned against the two ASL clips checked during design (see the proposal doc), not validated at scale.

[↑ Back to README TOC](../README.md#table-of-contents)
