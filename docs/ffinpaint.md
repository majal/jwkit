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

**Verified 2026-08-14: E2FGVI-HQ does not currently install on Apple Silicon at all**, not just "runs slow on CPU." Its `mmcv-full==1.4.8` dependency (needed for the `ModulatedDeformConv2d` op its flow-completion/feature-propagation modules use) fails to compile against a modern PyTorch/clang toolchain - real errors, not a missing-package issue: `mmcv-full`'s C++ extension sources assume an old compiler/standard library (`std::optional`/`std::variant` unresolved against current PyTorch headers), and a plain `mmcv` (the unified successor package) hit the same wall. This was tried end to end on this machine (Apple M3, Python 3.12, current PyTorch, `pip`/`clang++` as of 2026-08-14): PyTorch+torchvision installed fine (~940MB), the E2FGVI-HQ repo clone (~76MB) and the `E2FGVI-HQ-CVPR22.pth` checkpoint (~157MB, Google Drive-hosted, no direct CDN link) both downloaded fine, but `mmcv-full` would not build, which blocks importing the model at all - inference was never reached, so no timing numbers exist for this machine. E2FGVI-HQ's own code also only checks `torch.cuda.is_available()` with no Apple `mps` fallback, so even a successful `mmcv-full` build would still run on CPU here, not the M3's GPU.

The practically-working path is close to upstream's own pinned `environment.yml` (Python 3.7, PyTorch 1.5.1, CUDA 10.1) or a reasonably modern Linux+CUDA machine where prebuilt `mmcv-full` wheels exist - not a from-scratch modern-toolchain install like the one tried here. Anyone revisiting this: check for prebuilt `mmcv-full`/`mmcv` wheels matching your actual CUDA+PyTorch versions first (openmmlab publishes a version-matched wheel index) rather than letting pip build from source, and don't assume Apple Silicon is viable at all without confirming a fix for the above.

`ffinpaint` neither downloads nor redistributes upstream code or weights. The occlusion detector's false-positive/false-negative rate is still unverified against a broad sample of real clips across multiple sign languages - it was tuned against the two ASL clips checked during design (see the proposal doc), not validated at scale.

[↑ Back to README TOC](../README.md#table-of-contents)
