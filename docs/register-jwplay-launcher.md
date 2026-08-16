# `register-jwplay-launcher`

[← Back to README](../README.md#table-of-contents)

## What It Does

One-time OS file-association setup so a `.jwplay` launcher file (written by [`jwvideo-mux`](jwvideo-mux.md)'s `--adaptive-mpv-library` mode) can be double-clicked to play a presentation instead of run from a terminal by hand.

## Supported Platforms

- macOS
- Linux
- Windows

## Dependencies

- macOS: [`duti`](https://github.com/moretension/duti) (`brew install duti`)
- Linux: `xdg-utils`, `shared-mime-info`, `desktop-file-utils` (already present on most desktop distros; `gio`, part of glib2, is used for a stronger verification step if available)
- Windows: none beyond Python itself

## Install / First Run Summary

Run it once after installing jwkit:

```bash
register-jwplay-launcher
```

Safe to re-run any time to reapply or repair the association (e.g. after a jwkit reinstall).

## Common Usage Examples

```bash
register-jwplay-launcher
register-jwplay-launcher --no-color
```

There's nothing to configure — it detects the OS and does the right thing.

## Important Behavior / Defaults

- **macOS**: declares a `.jwplay` UTI conforming to Apple's own `com.apple.terminal.shell-script` (the same UTI `.command` files use) via a tiny background-only "type declarer" app bundle written to `~/Applications/JWPlayLauncherType.app`, then sets `Terminal.app` as the actual handler via `duti`. The declarer app is never meant to be opened itself — `lsregister` just needs to see its `Info.plist` once to learn the UTI. Double-click opens Terminal and runs the launcher, which `exec`s `mpv`.
- **Linux**: registers a custom MIME type (a shared-mime-info XML package under `~/.local/share/mime/packages/`) plus a `.desktop` entry under `~/.local/share/applications/`, then sets it as the default via `xdg-mime`. Runs the launcher directly (no visible terminal window), since the launcher's own job is to open `mpv` — its own GUI window. `Exec` is wrapped in an explicit `/bin/sh -c` rather than a bare `%f` field code: GNOME's `gio`-based resolver (what Nautilus/Files actually uses) silently refuses to treat a bare field code as valid, even though `xdg-mime query` reports success either way — confirmed by testing against a real GNOME session, not just the CLI query tools.
- **Windows**: associates `.jwplay` with `cmd.exe` via the current user's registry hive (`HKEY_CURRENT_USER`), so double-click runs the launcher's batch commands. If Explorer doesn't pick it up immediately, sign out and back in, or restart `explorer.exe`.
- Prints a best-effort verification after registering (`duti -x` / `gio mime` / nothing to check on Windows). A CLI verification passing doesn't 100% guarantee a GUI double-click will behave identically — if in doubt, just try double-clicking a `.jwplay` file.

## Notes / Caveats

- Changes OS-level file-type-association state, not just something inside this repo or its config.
- The Linux `.desktop` entry deliberately avoids `Terminal=true`: not every terminal emulator supports the legacy `-e`-style invocation GNOME's `Terminal=true` key relies on (Warp does not, confirmed by testing), so registering with it can silently fail depending on the user's default terminal. Since the `.jwplay` script's own job is opening `mpv` — its own GUI window — a visible terminal isn't needed anyway.
- Windows registration is unverified on a real Windows machine — the registry keys follow the standard, documented `HKCU\Software\Classes` file-association pattern, but there's no Windows environment available to confirm double-click behavior end-to-end.

[↑ Back to README TOC](../README.md#table-of-contents)
