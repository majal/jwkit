# `ffv`

[← Back to README](../README.md#table-of-contents)

## What It Does

`ffv` is the compact launcher for `slverse`. It translates the concise invocation into `slverse extract` or `slverse find`; all media and configuration logic remains in `slverse`.

## Supported Platforms

- macOS
- Linux
- Windows

## Dependencies

- [`slverse`](slverse.md)

## Install / First Run Summary

Install jwkit normally, then configure `slverse` once with `slverse setup`.

## Common Usage Examples

```bash
ffv FSL Rev 21:1-3
ffv any 1 Sa-mu-en 2:12-17
ffv all Ge 10:2 -p
```

Every `slverse extract` option works in the normal and `any` forms. Use `slverse extract --help` for the complete list.
Options are passed through unchanged, so newly added `slverse extract` flags work without an `ffv` update. In the `all` form, put options after the complete Bible reference; the option tail is forwarded intact to `slverse find`.

In particular, `ffv ... -e TIME` passes `-e` through as `slverse extract --trim-end TIME`: it removes that duration from the natural verse window's tail. It is intentionally different from `ffrife --end`, which names an absolute source timestamp. Both accept `SS.sss`, `MM:SS.sss`, or `HH:MM:SS.sss`.

## Important Behavior / Defaults

- `ffv <lang> ...` delegates to `slverse extract <lang> ...`.
- `ffv any ...` tries `slverse`'s configured `languages` in order and stops at the first available verse.
- `ffv all ...` delegates to `slverse find`; use `-p`/`--play` to open matching previews.
- `ffv config ...` delegates to `slverse config ...`, including `path`, `edit`, `reset`, `diff`, and `check`.
- Configuration belongs to `slverse`, so the launcher cannot drift into a second set of defaults.

## Notes / Caveats

This launcher intentionally does not reproduce the original local-video-cache implementation. `slverse` uses JW.org verse-marker metadata and is the sole maintained extraction engine.

[↑ Back to README TOC](../README.md#table-of-contents)
