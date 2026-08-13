# `jwvideo-mux-shortcuts.sh`

[← Back to README](../README.md#table-of-contents)

`jwvideo-mux-shortcuts.sh` is a set of short shell functions that wrap `jwvideo-mux`'s most common commands for a local SCE-style video library, so you don't have to retype the same flags for every video.

## What It Does

- Adds `jwvm-plan`, `jwvm-build`, `jwvm-mux`, `jwvm-relang`, and `jwvm-help` shell functions to your interactive shell.
- `jwvm-plan` runs `jwvideo-mux --analyze-video-variants` read-only, so you can see what a build would do before writing anything.
- `jwvm-build` builds (or force-rebuilds) the adaptive mpv library for a video, falling back to a plain single-file mux automatically when there's nothing to adapt.
- `jwvm-mux` runs the classic single-file multi-track mux directly.
- `jwvm-relang` changes the language set on an already-built library: it finds the existing library folder, asks for confirmation, deletes it, and rebuilds from scratch (`jwvideo-mux` has no incremental update mode, since changing languages can shift every segment boundary).
- All of the above automatically apply a corpus-wide `--manual-overrides` ground-truth file when one exists at the path in `JWVM_GROUND_TRUTH`, so a plain build can't accidentally skip a known correction.

## Supported Platforms

- macOS
- Linux

## Dependencies

- [`jwvideo-mux`](jwvideo-mux.md) (and everything it depends on)
- `bash`

## Install / First Run Summary

Source it from your shell rc:

```bash
source ~/dig/maj-scripts-vibe/jwvideo-mux-shortcuts.sh
```

Then, from inside a unit's base-language folder (usually `E/`), see what's available:

```bash
jwvm-help
```

## Common Usage Examples

See what a build would do without writing anything:

```bash
jwvm-plan some-video.mp4
```

Build the adaptive library with the default language set (`E,TG,CV,HV,SA`):

```bash
jwvm-build some-video.mp4
```

Build with a custom language set and an extra `jwvideo-mux` flag:

```bash
jwvm-build some-video.mp4 "E,TG,HV" --normalize-mismatched-aspect
```

Change the language set on a library you already built:

```bash
jwvm-relang some-video.mp4 "E,TG,CV,HV,SA,F"
```

## Important Behavior / Defaults

- Every function must be run with your shell's working directory set to the base-language folder (usually `E/`), and takes the video filename — not the full path — as its first argument.
- `langs` defaults to `E,TG,CV,HV,SA` for every function; pass it as the second argument to override.
- Assumes the "SCE Instructor/SCE Media/\<unit\>/" layout: `E/`, `TG/`, `HV/`, `CV/`, `SA/` sibling folders under a unit root, with the adaptive-library output and launchers written as siblings of those folders, not inside them.
- `JWVIDEOMUX` resolves to the `jwvideo-mux` script sitting next to this file, so the two stay paired wherever you check this repo out.

## Notes / Caveats

- `JWVM_GROUND_TRUTH` points at a human-audited overrides file outside this repo (private, corpus-specific data — not something a public script repo should ship). It's applied automatically when present and silently skipped when it isn't, so sourcing this file elsewhere, without that corpus, is safe — you just won't get the correction layer.
- `jwvm-relang` deletes the existing library folder before rebuilding; it asks for confirmation first, but there's no undo once you answer yes.

[↑ Back to README TOC](../README.md#table-of-contents)
