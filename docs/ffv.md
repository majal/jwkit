# `ffv`

[← Back to README](../README.md#table-of-contents)

## What It Does

`ffv` is a thin compatibility launcher for the original command name. It translates the old compact invocation into `slverse extract` or `slverse find`; all media and configuration logic remains in `slverse`.

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

## Important Behavior / Defaults

- `ffv <lang> ...` delegates to `slverse extract <lang> ...`.
- `ffv any ...` tries `slverse`'s configured `languages` in order and stops at the first available verse.
- `ffv all ...` delegates to `slverse find`; `-p` and `-m` are accepted as aliases for `--play`.
- Configuration belongs to `slverse`, so the launcher cannot drift into a second set of defaults.

## Notes / Caveats

This launcher intentionally does not reproduce the original local-video-cache implementation. `slverse` uses JW.org verse-marker metadata and is the sole maintained extraction engine.

[↑ Back to README TOC](../README.md#table-of-contents)
