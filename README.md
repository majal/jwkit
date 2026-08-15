# jwkit

jwkit downloads and processes content from jw.org: Bible sign-language clips, music, periodicals, and video.

## Overview

New here? Jump to [Quick Install](#quick-install) — one command, no manual setup.

Each tool below has its own section covering what it does, what it needs, and the commands to try first. Full detail lives in `docs/<tool>.md`, linked from each section. Prefer to install things by hand, or hit something the quick install can't fix on its own? See [Your Local Setup](#your-local-setup).

## Table of Contents

- [Overview](#overview)
- [Quick Install](#quick-install)
- [Tools](#tools)
  - [`ffinpaint`](#ffinpaint)
  - [`ffrife`](#ffrife)
  - [`ffv`](#ffv)
  - [`jwdl`](#jwdl)
  - [`jwpl`](#jwpl)
  - [`jwvideo-mux`](#jwvideo-mux)
  - [`slverse`](#slverse)
- [Your Local Setup](#your-local-setup)
  - [Python](#python)
  - [Git](#git)
  - [Package Managers](#package-managers)
- [Contributing Docs](#contributing-docs)

## Quick Install

One command sets everything up: Python, `ffmpeg`, and jwkit itself, added to your terminal's `PATH` so `slverse`, `ffv`, `jwdl`, `jwpl`, `ffinpaint`, `ffrife`, and `jwvideo-mux` just work. No manual downloads, no separate setup steps.

**macOS or Linux** (Terminal):

```bash
curl -fsSL https://raw.githubusercontent.com/majal/jwkit/main/install.sh | bash
```

**Windows** (PowerShell):

```powershell
irm https://raw.githubusercontent.com/majal/jwkit/main/install.ps1 | iex
```

Then open a **new** terminal window and try:

```bash
slverse --help
jwdl list
jwpl --help
```

For the interactive setup (which sign languages you watch, cache size, etc.), run `slverse setup` once.

jwkit also updates itself automatically — once a day at most, and only when you actually run a command, so it never does anything in the background. `slverse setup` asks whether you want this on (it's on by default); turn it off any time by editing `auto_update = false` into `~/.config/jwkit/config.toml`. You can still update by hand with `jwkit-update` (installed alongside the tools), or by re-running the install command above — both are safe to repeat.

Output is colored by default on a real terminal (auto-disabled when piped/redirected, or when `NO_COLOR` is set). Every tool takes `--color`/`--no-color` for one run, or set `color_output = always`/`never` in `~/.config/jwkit/config.toml` to change the default everywhere.

To uninstall, run:

```bash
curl -fsSL https://raw.githubusercontent.com/majal/jwkit/main/uninstall.sh | bash
```

On Windows:

```powershell
irm https://raw.githubusercontent.com/majal/jwkit/main/uninstall.ps1 | iex
```

It removes the Quick Install copy and its PATH entry, plus only dependencies that Quick Install recorded as installing itself. It keeps this source checkout, all `~/.config/jwkit` settings/downloads, and dependencies that were already present. Older installs without a dependency record remain conservative and keep dependencies.

If a step needs your password (installing Homebrew on macOS, or `sudo` on Linux) or a Windows Store component (`winget`), that's your system's own installer asking, not jwkit. See [Your Local Setup](#your-local-setup) below if you'd rather do each step by hand, or if the quick install hits something it can't resolve on its own.

[↑ TOC](#table-of-contents)

## Tools

### [`ffinpaint`](./ffinpaint)

`ffinpaint` connects `slverse` to an explicitly user-installed E2FGVI-HQ temporal-inpainting checkout, preserving moving foreground where a static delogo blur cannot. It does not download or bundle the backend or model weights; E2FGVI-HQ is non-commercial-only.

Full docs: [docs/ffinpaint.md](docs/ffinpaint.md)

[↑ TOC](#table-of-contents)

### [`ffrife`](./ffrife)

`ffrife` interpolates any video to a higher frame rate using `rife-ncnn-vulkan`, a GPU-accelerated AI model that generates real in-between frames instead of just blending adjacent ones. It works on any local file or URL, JW-related or not — trim a section, add an `ffmpeg` filter, or retime the speed, all in a single pass. `slverse` uses it as a library for its own interpolation instead of duplicating the logic.

Full docs: [docs/ffrife.md](docs/ffrife.md)

[↑ TOC](#table-of-contents)

### [`ffv`](./ffv)

`ffv` preserves the original command name and compact `ffv <language> <reference>` muscle memory while delegating all lookup, playback, and encoding to `slverse`. It also keeps the familiar `any` and `all` selection modes without maintaining a second video engine.

Full docs: [docs/ffv.md](docs/ffv.md)

[↑ TOC](#table-of-contents)

### [`jwdl`](./jwdl)

`jwdl` downloads JW music, periodicals, and videos from jw.org, one folder per collection.

Full docs: [docs/jwdl.md](docs/jwdl.md)

[↑ TOC](#table-of-contents)

### [`jwpl`](./jwpl)

`jwpl` turns an ordered folder of pictures, videos, and audio into a JW Library `.jwlplaylist`, with configurable controller-facing titles and no JW Library UI work.

Full docs: [docs/jwpl.md](docs/jwpl.md)

[↑ TOC](#table-of-contents)

### [`jwvideo-mux`](./jwvideo-mux)

`jwvideo-mux` downloads a jw.org video and merges the language tracks you want into one file, so you get a single video with selectable audio and subtitles instead of a separate download per language.

Full docs: [docs/jwvideo-mux.md](docs/jwvideo-mux.md)

[↑ TOC](#table-of-contents)

### [`slverse`](./slverse)

`slverse` finds, extracts, and interpolates Sign Language Bible videos, verse by verse. It's the successor to the original [`ffv`](https://github.com/majal/maj-scripts-archive-2026/blob/master/SL/ffv), rebuilt around JW.org's own verse-marker data instead of manual timestamping. Run `slverse setup` for a guided walkthrough — pick your sign languages, cache size, and more.

Full docs: [docs/slverse.md](docs/slverse.md)

[↑ TOC](#table-of-contents)

## Your Local Setup

Most people should just use [Quick Install](#quick-install) above. This section is for doing each step by hand — useful if the quick install can't finish something automatically (e.g. no `winget` on an older Windows install) or you just prefer to see each piece go in yourself.

### [Python](https://www.python.org/downloads/)

Most tools in this repo are expected to use Python 3.

Check whether Python 3 is already available:

```bash
python3 --version
```

If not, install it with your platform's package manager (see [Package Managers](#package-managers) below), or the [official installer](https://www.python.org/downloads/).

[↑ TOC](#table-of-contents)

### [Git](https://git-scm.com/)

Check whether Git is already available:

```bash
git --version
```

Clone this repo:

```bash
git clone https://github.com/majal/jwkit.git
cd jwkit
```

Later, update your local copy from inside the repo folder:

```bash
git pull
```

[↑ TOC](#table-of-contents)

### Package Managers

#### [Homebrew](https://brew.sh/) (macOS)

```bash
brew install python
brew install ffmpeg
brew install git
```

#### [winget](https://learn.microsoft.com/windows/package-manager/winget/) and [Chocolatey](https://chocolatey.org/) (Windows)

```powershell
winget install Python.Python.3
winget install Gyan.FFmpeg
winget install Git.Git
```

[↑ TOC](#table-of-contents)

## Contributing Docs

Adding a new tool? Update this README alongside it so it stays easy to find — see [`AGENTS.md`](./AGENTS.md) for the full contributor rules and doc template.

For quick repo checks, run the lightweight test harness before or after changes:

```bash
python3 -m tests
```

[↑ TOC](#table-of-contents)
