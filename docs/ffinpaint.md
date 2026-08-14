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

The unmodified upstream E2FGVI runner writes an MP4 itself, so its current integration has an intermediate encode before slverse draws the final caption. RIFE and inpainting intentionally do not compose yet; that waits for a backend with a supported PNG-output interface.

## Notes / Caveats

GPU speed, VRAM needs, and detector accuracy need real-footage validation. `ffinpaint` neither downloads nor redistributes upstream code or weights.

[↑ Back to README TOC](../README.md#table-of-contents)
