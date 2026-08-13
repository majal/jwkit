# jwkit

Tools for pulling and processing content from jw.org — Bible sign-language clips, music, videos, and periodicals. Split out of [`majal/maj-scripts`](https://github.com/majal/maj-scripts) into its own home now that the jw.org-specific tools outnumbered the general-purpose ones there.

## Overview

If you're just here to use a tool, start here. This README is the friendly map:

- Not sure where to start? Jump to [Quick Install](#quick-install) — one command, no manual setup.
- Each tool section tells you what it does, what it needs, and the safest first commands to try — full detail lives in `docs/<tool>.md`, linked from each section.
- Use [Your Local Setup](#your-local-setup) if you'd rather install things by hand, or the quick install needs troubleshooting.

## Table of Contents

- [Overview](#overview)
- [Quick Install](#quick-install)
- [Tools](#tools)
  - [`slverse`](#slverse)
  - [`ffrife`](#ffrife)
  - [`jwdl`](#jwdl)
  - [`jwvideo-mux`](#jwvideo-mux)
  - [`jwvideo-mux-shortcuts.sh`](#jwvideo-mux-shortcutssh)
- [Your Local Setup](#your-local-setup)
  - [Python](#python)
  - [Git](#git)
  - [Package Managers](#package-managers)
- [Contributing Docs](#contributing-docs)

## Quick Install

One command sets everything up: Python, `ffmpeg`, and jwkit itself, added to your terminal's `PATH` so `slverse`, `jwdl`, `ffrife`, and `jwvideo-mux` just work. No manual downloads, no separate setup steps.

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
```

For the interactive setup (which sign languages you watch, cache size, etc.), run `slverse setup` once.

To update jwkit later, run `jwkit-update` (installed alongside the tools) — or just re-run the install command above; it's safe to repeat.

If a step needs your password (installing Homebrew on macOS, or `sudo` on Linux) or a Windows Store component (`winget`), that's your system's own installer asking, not jwkit. See [Your Local Setup](#your-local-setup) below if you'd rather do each step by hand, or if the quick install hits something it can't resolve on its own.

[↑ TOC](#table-of-contents)

## Tools

### [`slverse`](./slverse)

`slverse` (formerly `jwsl`) is a unified tool for downloading, extracting, overlaying, and interpolating Sign Language Bible videos. It's not techie-only: `slverse setup` walks through the choices below with plain-language prompts and sane defaults.

Full docs: [docs/slverse.md](docs/slverse.md)

[↑ TOC](#table-of-contents)

### [`ffrife`](./ffrife)

`ffrife` is a standalone AI frame-interpolation tool built on `rife-ncnn-vulkan` (GPU-accelerated). It's not JW/Bible-specific — it takes any local file or remote URL, an optional trim window, an optional `ffmpeg -vf` filter chain, and an optional retime speed, and produces real AI-interpolated (not motion-blended) output at a target frame rate. `slverse` uses it as a library for its own `rife` interpolation engine instead of carrying a separate copy of this logic.

Full docs: [docs/ffrife.md](docs/ffrife.md)

[↑ TOC](#table-of-contents)

### [`jwdl`](./jwdl)

`jwdl` downloads official JW music (MP3) and periodicals (PDF: Watchtower, the meeting workbook) from jw.org into a local library, one folder per collection.

Full docs: [docs/jwdl.md](docs/jwdl.md)

[↑ TOC](#table-of-contents)

### [`jwvideo-mux`](./jwvideo-mux)

`jwvideo-mux` is an automated media downloader and muxer for jw.org videos.

Designed to be accessible for semi-techies, this script simplifies the otherwise complex process of downloading and merging multiple language tracks into a single video file.

Full docs: [docs/jwvideo-mux.md](docs/jwvideo-mux.md)

[↑ TOC](#table-of-contents)

### [`jwvideo-mux-shortcuts.sh`](./jwvideo-mux-shortcuts.sh)

`jwvideo-mux-shortcuts.sh` is a set of short shell functions that wrap `jwvideo-mux`'s most common commands for a local SCE-style video library, so you don't have to retype the same flags for every video.

Full docs: [docs/jwvideo-mux-shortcuts.md](docs/jwvideo-mux-shortcuts.md)

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

When new tools are added, keep this README as the main navigation page and update it alongside the tool so new additions stay easy to discover — see [`AGENTS.md`](./AGENTS.md) for the full contributor/agent rules and doc template this repo follows (same pattern as `maj-scripts`).

For quick repo checks, run the lightweight test harness before or after changes:

```bash
python3 -m tests
```

[↑ TOC](#table-of-contents)
