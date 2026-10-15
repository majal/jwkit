# Contributor reference (full text)

Moved verbatim from `AGENTS.md` on 2026-10-15 (instruction-bloat trim). `AGENTS.md` keeps the
operative rules and the add-a-tool checklist; this file holds the repo purpose/history and the
detail for the shared-module features (auto-update, overwrite handling, provenance), the
installers, and the README/doc templates.

## Purpose

`jwkit` holds tools for pulling and processing content from jw.org: Bible sign-language clips (`slverse`), music/periodicals/video (`jwdl`), multi-language video downloading and muxing (`jwvideo-mux`), and AI frame interpolation (`ffrife`, used as a library by `slverse` but not jw.org-specific itself).

Split out of [`majal/maj-scripts`](https://github.com/majal/maj-scripts) on 2026-08-13, once the jw.org-specific tools there outnumbered the general-purpose ones. `maj-scripts` keeps its own disparate utility scripts (`gmail-cleanup`, `whisper`, `wh`, `printing-mode`, `ubuntu-hibernate`, etc.); this repo is scoped to jw.org content tools only.

`jwget` (a legacy, unauthenticated bash periodicals scraper) was absorbed into `jwdl` as `jwdl periodicals` on the same day, then retired to `bin-archive-2026` — jw.org's modern `pub-media` API (checksummed, already used by `jwdl` for music) covers the periodicals that are still actually published; two of `jwget`'s four (`wp`, `g`) turned out to be discontinued jw.org-side years ago, not just stale locally.

`jwdl video` and `jwvideo-mux` both touch video but solve different problems, and that's intentional, not overlap to clean up: `jwdl video` bulk-downloads by category (Bible, Dramas, Latest Videos, ...) at one resolution, one language at a time - browsing jw.org's own catalog tree via its `mediator` API. `jwvideo-mux` downloads *one specific, already-known* video and merges multiple language audio/subtitle tracks into a single file. Reach for `jwdl video` to explore/bulk-fetch; reach for `jwvideo-mux` when you already have a docid/URL and want several languages muxed together.

## Auto-Update (`_jwkit_common.py`)

Every tool calls `_jwkit_common.maybe_auto_update(jwkit_root)` right after its own `argparse.parse_args()` call (so `--help`/`-h` exits before ever reaching it — no network activity just to check usage). At most once every `auto_update_interval_hours` (default 24) on a *real* invocation, it does a `git fetch` + fast-forward-only merge of the jwkit checkout against `origin`'s default branch, controlled by the shared (not per-tool) `~/.config/jwkit/config.toml` (`auto_update = true/false`, on by default). The check-timestamp in `~/.config/jwkit/update-state.json` is written *before* attempting the update, so a bad connection doesn't retry — and pause a command — on every run for the rest of the day.

- `_jwkit_common.py` is loaded as a sibling module (`sys.path.insert(0, ...)` + `import _jwkit_common`) rather than via `SourceFileLoader`, unlike `ffrife` — it has a real `.py` extension so Python's normal import machinery can find it, `ffrife`/`jwdl` don't and need the loader dance.
- Fast-forward only, on purpose: it will never discard a local edit someone made to their own checkout, and never touches a tarball install (no `.git` present) — those rely on re-running `install.sh`/`install.ps1`/`jwkit-update` by hand.
- `slverse setup` is the one place a user is asked about this interactively (writes to the *shared* `~/.config/jwkit/config.toml` via `_jwkit_common.save_jwkit_config`, not to `slverse`'s own per-tool config) — `ffrife`/`jwdl`/`jwvideo-mux` don't duplicate the question, they just read whatever's already there (or the default, if nothing's been set yet).
- Never let this raise out into a tool's real command — the whole check is wrapped in a broad `except Exception: pass`. An update check must never be the reason someone's actual command fails.

## Overwrite Handling (`_jwkit_common.py`)

Every tool that writes a final output file calls `_jwkit_common.resolve_output_conflict(path, jwkit_config)` right before writing it, and uses whatever `Path` it returns (or aborts/skips if it returns `None`) instead of writing straight to the caller-supplied path. Controlled by the shared `~/.config/jwkit/config.toml` (`on_output_exists`, default `ask`; `on_output_exists_unattended`, default `rename`; `overwrite_prompt_timeout`, default 20 seconds) - not per-tool config, since this is a cross-cutting concern, same as `auto_update`/`color_output` above.

- `ask` only prompts when `sys.stdin.isatty()` - a cron/systemd invocation (see the unattended jobs noted under Operational Notes) has no TTY to prompt, so it silently falls through to `on_output_exists_unattended` instead. A prompt that goes unanswered for `overwrite_prompt_timeout` seconds (implemented via a daemon reader thread + `queue.Queue(timeout=...)`, since `input()` has no native cross-platform timeout) falls through the same way, as does an explicit "no" answer.
- `trash` moves the *existing* file to the real OS Trash/Recycle Bin (macOS: `osascript`/Finder delete; Linux: `gio trash`, falling back to a hand-written freedesktop.org trash-spec implementation; Windows: `ctypes` `SHFileOperationW`, unverified on a real machine - same caveat as `install.ps1` above) before the fresh write lands at the canonical path. A same-named collision already in the trash gets a datetime-tagged rename first, not silently clobbered.
- `rename` returns the first free `name (1).ext`, `name (2).ext`, ... sibling instead of touching the existing file.
- Add matching `--on-exists`/`--on-exists-unattended`/`--overwrite-timeout` flags to a new tool's own output-writing subcommand (see `ffrife run`'s `p_run.add_argument` calls for the pattern) so the shared config stays overridable per-run everywhere, not just in `~/.config/jwkit/config.toml`.
- Not every `path.exists()` check in these tools is a "real" overwrite scenario worth routing through this - see `slverse bulk`'s own `--overwrite` (a cache-hit skip for a rerunnable batch job) and `jwpl init`'s config-scaffold guard for two deliberate exceptions.

## Provenance Records (`_jwkit_common.py`)

A tool that renders a media file from a known source records how it was made - source URL/MD5, settings, exact rebuild command, tool commit - with `_jwkit_common.write_provenance(output, record, jwkit_config, ffmpeg=...)` (see `slverse`'s `write_extract_provenance`, `ffrife`'s `write_run_provenance`). Where it lives is the shared `provenance_mode` (`embed` default, `beside`, `folder`, `none`) plus `provenance_dir`; add `_jwkit_common.add_provenance_arguments(parser)` for the matching `--provenance`/`--provenance-dir` flags and fold them in with `apply_provenance_overrides`. `slverse provenance` / `jwkit-provenance move` move existing records between places; `locate_provenance`/`read_provenance` find one wherever it is. Tools build records with `base_record`/`record_output`/`describe_file` (inputs get their md5, jw.org name parse, and `made_by` when they carry a record). Scripts in other repos (bash or Python) call the `jwkit-provenance record` CLI instead of importing anything: `bin`'s `lib/jwkit-record.sh` and `maj-scripts`' `ffcut` already do, as a soft dependency that does nothing when jwkit isn't installed. Writers that deliberately don't record: `jwdl` and the sources `jwvideo-mux` downloads (verbatim copies of jw.org's files - embedding would change them and break their MD5 freshness checks).

- **Embedded means no re-encode, and no collateral damage.** MP4/MOV/M4A get a trailing `uuid` box appended in place (never ffmpeg's `-movflags +use_metadata_tags`: it moves every MP4 tag into `mdta`, and AVFoundation then loses the title). Matroska and MP3/FLAC/Ogg/Opus get a global tag through a stream-copy remux that must reproduce the original: `-avoid_negative_ts disabled` (ffmpeg's default shifts start times) and cover art re-attached with `-attach` (`-map 0` silently turns it into a plain video track). The remux is verified (packet hash, duration, stream layout) before it replaces anything, and an embed that can't be verified falls back to a sidecar rather than altering the file.
- An embedded record can't contain the file's own hash; it carries `output.av_sha256` (video/audio packet hash) instead.
- Never let a provenance problem fail a run whose video already exists.

## Installer (`install.sh` / `install.ps1`)

Root-level one-liner installers for non-technical users (`curl | bash` on macOS/Linux, `irm | iex` on Windows) — see the Quick Install section of `README.md`. They install missing dependencies (Python, `ffmpeg`, `git` via Homebrew/apt/dnf/pacman/winget), download jwkit to `~/.jwkit` (`%USERPROFILE%\.jwkit` on Windows), add it to `PATH`, and drop a `jwkit-update` command that re-runs the same script.

`uninstall.sh` / `uninstall.ps1` remove that installed copy and the matching PATH entry. They preserve the source checkout and `~/.config/jwkit` configuration/downloads. New installs record only dependencies that the installer itself added, allowing uninstalls to remove those without guessing about pre-existing dependencies; legacy installs without a record preserve dependencies.

- Both scripts hardcode a `TOOLS`/`$Tools` list of the top-level commands to make runnable (`ffinpaint`, `ffrife`, `ffv`, `jwdl`, `jwpl`, `jwvideo-mux`, `register-jwplay-launcher`, `slverse`). **Add new tools to that list in both scripts** when they're added to the repo, or the installer won't make them executable/shimmed.
- `install.sh` is tested locally by overriding `HOME` to a scratch directory (`HOME=/tmp/fake bash install.sh`) so it never touches a real shell profile during testing.
- `install.ps1` is **not verified on a real Windows machine** as of 2026-08-13 — it was written to the same patterns as `install.sh` (idempotent, guarded PATH edits, friendly error trap) but there was no Windows environment available to test it in. Treat changes to it with extra care and prefer a real Windows test before relying on it.
- Windows needs `.cmd` shims (`slverse.cmd`, etc.) alongside the actual scripts, since Windows doesn't run a `#!/usr/bin/env python3` shebang line directly the way macOS/Linux do — `install.sh` doesn't need this, since the scripts are already directly executable there once `chmod +x`'d.
- Both scripts are designed to be safe to re-run (used as the update mechanism) — don't add steps that aren't idempotent (e.g. that fail or duplicate on a second run) without guarding them.

## README Rules

When adding a new top-level tool to the repo:

1. Add the tool file.
2. Add the tool to the README table of contents.
3. Add a short subsection under `## Tools` (name, 1-3 sentence blurb, `Full docs:` link) — see Doc Template below.
4. Create `docs/<tool>.md` with the full template.
5. Keep the `## Tools` section above the shared Your Local Setup section.
6. End each major section with `↑ TOC`.

Do not add a new tool without updating the README.

## Doc Template

Full per-tool docs live in `docs/<tool>.md`, not inline in `README.md` — this repo started with the split already applied (see `maj-scripts`' Growth Rule for the history of why).

**README section** (short):
1. Tool name — heading links directly to the tool file.
2. A short (1-3 sentence) description.
3. A `Full docs: [docs/<tool>.md](docs/<tool>.md)` link.
4. `↑ TOC`.

**`docs/<tool>.md`** (full):
1. `# <tool>` title, then `[← Back to README](../README.md#table-of-contents)`.
2. `## What It Does`
3. `## Supported Platforms`
4. `## Dependencies`
5. `## Install / First Run Summary`
6. `## Common Usage Examples`
7. `## Important Behavior / Defaults`
8. `## Notes / Caveats`
9. `[↑ Back to README TOC](../README.md#table-of-contents)` at the end.

Doc filename: `docs/<tool-name>.md`, stripping a trailing `.sh` if the tool has one.

Keep examples short, practical, and copy-pasteable.

## Tone Rules

Same spirit as `maj-scripts`: practical and skimmable, a light touch is fine, but don't let it make setup instructions vague. Prefer friendly, calm wording in user-facing tool output too.

## Heading And TOC Rules

- Keep README headings stable and predictable so anchors remain valid.
- Prefer `## Tools` as the parent section and `### <tool-name>` for each tool.
- Prefer `### [<tool-name>](./<tool-file>)` when the tool file lives at the repo root.
- Keep the tool list **alphabetical** everywhere it appears: the README TOC, the `## Tools` section itself, and the `TOOLS`/`$Tools` arrays in `install.sh`/`install.ps1`. Insert new tools in alphabetical position rather than appending them at the end.
- Use `↑ TOC` for major sections and primary subsections.
- If a new shared subsection is added, it must also be added to the README TOC in the same order it appears in the file.
