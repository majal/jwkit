# AGENTS.md

Guidance for future contributors and AI agents working in this repo.

Repo name: `jwkit`

## Purpose

`jwkit` holds tools for pulling and processing content from jw.org: Bible sign-language clips (`slverse`), music/periodicals/video (`jwdl`), multi-language video downloading and muxing (`jwvideo-mux`), and AI frame interpolation (`ffrife`, used as a library by `slverse` but not jw.org-specific itself).

Split out of [`majal/maj-scripts`](https://github.com/majal/maj-scripts) on 2026-08-13, once the jw.org-specific tools there outnumbered the general-purpose ones. `maj-scripts` keeps its own disparate utility scripts (`gmail-cleanup`, `whisper`, `wh`, `printing-mode`, `ubuntu-hibernate`, etc.); this repo is scoped to jw.org content tools only.

`jwget` (a legacy, unauthenticated bash periodicals scraper) was absorbed into `jwdl` as `jwdl periodicals` on the same day, then retired to `bin-archive-2026` — jw.org's modern `pub-media` API (checksummed, already used by `jwdl` for music) covers the periodicals that are still actually published; two of `jwget`'s four (`wp`, `g`) turned out to be discontinued jw.org-side years ago, not just stale locally.

`jwdl video` and `jwvideo-mux` both touch video but solve different problems, and that's intentional, not overlap to clean up: `jwdl video` bulk-downloads by category (Bible, Dramas, Latest Videos, ...) at one resolution, one language at a time - browsing jw.org's own catalog tree via its `mediator` API. `jwvideo-mux` downloads *one specific, already-known* video and merges multiple language audio/subtitle tracks into a single file. Reach for `jwdl video` to explore/bulk-fetch; reach for `jwvideo-mux` when you already have a docid/URL and want several languages muxed together.

## Naming

Tools here don't carry a `jw` prefix by default — the repo name already scopes them. `slverse` (sign-language verse extraction, formerly `jwsl`) follows this. `jwdl` and `jwvideo-mux` kept their existing names on the move rather than being renamed along with the repo split — don't rename them without explicit direction, since `jwdl` in particular has a live external caller (see Operational Notes below).

## Configuration

All tools share one config namespace, `~/.config/jwkit/<tool>/` (e.g. `~/.config/jwkit/slverse/`, `~/.config/jwkit/jwdl/`, `~/.config/jwkit/ffrife/`). Each tool auto-migrates its config on first run from wherever it used to live (pre-jwkit `~/.config/maj-scripts/<tool>/`, or `slverse`'s brief standalone `~/.config/slverse/` waypoint) — nothing is lost across a rename or the unification, including `ffrife`'s downloaded RIFE binary and `slverse`'s synced verse-marker index. New tools should follow this same `~/.config/jwkit/<tool>/` layout from the start rather than inventing their own.

Design tools config-first whenever behavior is reasonably user-customizable. Every persisted config setting must have a corresponding long CLI flag for a one-run override, and the most common flags should also have short aliases. Keep config, CLI help, docs, and tests in sync; do not hardcode one operator's language order, player layout, paths, or workflow preferences as universal behavior. Positional identifiers and intrinsically one-shot actions do not need persisted config merely for symmetry.

## Operational Notes

- **`jwdl` is called by a live systemd user timer on `emeth4`** (`~/.config/systemd/user/jwdl-weekly.service` + `.timer`, `ExecStart=... %h/MyFiles/Digitalis/jwkit/jwdl all`, weekly). Any change to `jwdl`'s existing music CLI surface (`jwdl <pub> [lang]`, `jwdl all`, `jwdl list`) must stay backward-compatible, or the service needs a coordinated update on that host first. `jwdl periodicals ...` is a fully separate command path added specifically to avoid touching that surface — keep it that way rather than folding periodicals into the same `pub`/`all` positional.
- **`slverse` is also called by a live systemd user timer on `emeth4`** (`~/.config/systemd/user/jwsl-sync-weekly.service` + `.timer` — the unit files keep the pre-rename `jwsl` name, only their `ExecStart` was updated to `%h/MyFiles/Digitalis/jwkit/slverse sync all`; renaming the unit files themselves was judged not worth the re-enable risk). This one was missed in the initial `jwsl`→`slverse`/`jwkit` split (2026-08-13) because the audit at the time only grepped for `jwdl`, not `jwsl` — found and fixed in a follow-up broader audit the same day. When auditing for live callers on a host, grep `ExecStart=` across **all** `~/.config/systemd/user/*.service` and (`sudo`) `/etc/systemd/system/*.service` for the tool's old **and** new name, not just the one you're actively changing.
- **Auto-update (see below) runs before these unattended jobs too.** `jwdl-weekly.service` and `jwsl-sync-weekly.service` both call a jwkit tool directly, so if auto-update is on (the default) that command will `git fetch`+fast-forward jwkit *before* doing its actual job, unattended, with nobody reviewing the diff first. Fast-forward-only means it can't silently discard anything, but it does mean a bad push to `main` reaches these hosts on their very next scheduled run. Test before pushing to `main`, same as always — this isn't a reason to relax that, just a reminder the blast radius includes unattended jobs, not only interactive users.

## Auto-Update (`_jwkit_common.py`)

Every tool calls `_jwkit_common.maybe_auto_update(jwkit_root)` right after its own `argparse.parse_args()` call (so `--help`/`-h` exits before ever reaching it — no network activity just to check usage). At most once every `auto_update_interval_hours` (default 24) on a *real* invocation, it does a `git fetch` + fast-forward-only merge of the jwkit checkout against `origin`'s default branch, controlled by the shared (not per-tool) `~/.config/jwkit/config.toml` (`auto_update = true/false`, on by default). The check-timestamp in `~/.config/jwkit/update-state.json` is written *before* attempting the update, so a bad connection doesn't retry — and pause a command — on every run for the rest of the day.

- `_jwkit_common.py` is loaded as a sibling module (`sys.path.insert(0, ...)` + `import _jwkit_common`) rather than via `SourceFileLoader`, unlike `ffrife` — it has a real `.py` extension so Python's normal import machinery can find it, `ffrife`/`jwdl` don't and need the loader dance.
- Fast-forward only, on purpose: it will never discard a local edit someone made to their own checkout, and never touches a tarball install (no `.git` present) — those rely on re-running `install.sh`/`install.ps1`/`jwkit-update` by hand.
- `slverse setup` is the one place a user is asked about this interactively (writes to the *shared* `~/.config/jwkit/config.toml` via `_jwkit_common.save_jwkit_config`, not to `slverse`'s own per-tool config) — `ffrife`/`jwdl`/`jwvideo-mux` don't duplicate the question, they just read whatever's already there (or the default, if nothing's been set yet).
- Never let this raise out into a tool's real command — the whole check is wrapped in a broad `except Exception: pass`. An update check must never be the reason someone's actual command fails.

## Installer (`install.sh` / `install.ps1`)

Root-level one-liner installers for non-technical users (`curl | bash` on macOS/Linux, `irm | iex` on Windows) — see the Quick Install section of `README.md`. They install missing dependencies (Python, `ffmpeg`, `git` via Homebrew/apt/dnf/pacman/winget), download jwkit to `~/.jwkit` (`%USERPROFILE%\.jwkit` on Windows), add it to `PATH`, and drop a `jwkit-update` command that re-runs the same script.

`uninstall.sh` / `uninstall.ps1` remove that installed copy and the matching PATH entry. They preserve the source checkout and `~/.config/jwkit` configuration/downloads. New installs record only dependencies that the installer itself added, allowing uninstalls to remove those without guessing about pre-existing dependencies; legacy installs without a record preserve dependencies.

- Both scripts hardcode a `TOOLS`/`$Tools` list of the top-level commands to make runnable (`ffinpaint`, `ffrife`, `ffv`, `jwdl`, `jwpl`, `jwvideo-mux`, `register-jwplay-launcher`, `slverse`). **Add new tools to that list in both scripts** when they're added to the repo, or the installer won't make them executable/shimmed.
- `install.sh` is tested locally by overriding `HOME` to a scratch directory (`HOME=/tmp/fake bash install.sh`) so it never touches a real shell profile during testing.
- `install.ps1` is **not verified on a real Windows machine** as of 2026-08-13 — it was written to the same patterns as `install.sh` (idempotent, guarded PATH edits, friendly error trap) but there was no Windows environment available to test it in. Treat changes to it with extra care and prefer a real Windows test before relying on it.
- Windows needs `.cmd` shims (`slverse.cmd`, etc.) alongside the actual scripts, since Windows doesn't run a `#!/usr/bin/env python3` shebang line directly the way macOS/Linux do — `install.sh` doesn't need this, since the scripts are already directly executable there once `chmod +x`'d.
- Both scripts are designed to be safe to re-run (used as the update mechanism) — don't add steps that aren't idempotent (e.g. that fail or duplicate on a second run) without guarding them.

## Public Repo And Secrets

This repository is public. Treat anything committed here as readable by others.

Do not store secrets, API keys, or other sensitive local state in this repo. Prefer OS-local config, environment variables, or user home paths outside the repo for secrets and machine-specific state.

## Agent Permission Rules

Normal file edits inside this repository checkout are pre-approved. Do not ask for user permission before creating or modifying files in this repo as part of the requested work.

Still ask for approval before escalated actions, including destructive commands, writes outside this repo or the configured writable roots, GUI/system-level actions, or network-dependent commands that the sandbox blocks.

## README Rules

When adding a new top-level tool to the repo:

1. Add the tool file.
2. Add the tool to the README table of contents.
3. Add a short subsection under `## Tools` (name, 1-3 sentence blurb, `Full docs:` link) — see Doc Template below.
4. Create `docs/<tool>.md` with the full template.
5. Keep the `## Tools` section above the shared Your Local Setup section.
6. End each major section with `↑ TOC`.

Do not add a new tool without updating the README.

## Test Rules

Run `python3 -m tests` before pushing changes that affect tools, tests, or README/AGENTS documentation.

## Commit And Push Rules

Commit is automatic (2026-08-14, operator-directed): once a change is good and verified, commit it right away so history captures every change and checkpoint. Don't ask first, and don't leave verified work sitting uncommitted "for later." Keep commits narrow — one logical change per commit, not batched unrelated edits.

Push is separate and intentionally batched, not automatic on every commit — see the auto-update note above (`jwdl-weekly.service`/`jwsl-sync-weekly.service` fast-forward from `origin/main` unattended, so a push reaches those hosts on their next scheduled run with nobody reviewing the diff first). Push when you've verified a batch of commits as a whole, when the user asks, or before ending a work session — not reflexively after each individual commit. Never push when there are unresolved errors or relevant verification has not passed. In those cases, leave a clear status note with the next step.

Never force-push or rewrite history without the user's explicit go-ahead.

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

## When Adding A Tool Checklist

- add the tool file
- update the README table of contents
- add the short tool subsection (name, blurb, `Full docs:` link) under `## Tools`
- create `docs/<tool>.md` with the full template and a back-link to the README TOC
- keep `## Tools` above Your Local Setup
- use `↑ TOC` consistently in README, and the back-link in `docs/<tool>.md`
- keep examples concise and copy-pasteable
- store config/state under `~/.config/jwkit/<tool>/` (see Configuration above), with a migration helper if you're renaming/moving an existing tool
- if the tool has a live external caller (cron/systemd elsewhere), note it under Operational Notes above and keep its CLI surface backward-compatible
- add the tool to the `TOOLS`/`$Tools` list in both `install.sh` and `install.ps1` (see Installer above) so the one-line installers pick it up
- wire in `_jwkit_common.maybe_auto_update(...)` right after `parse_args()` (see Auto-Update above) so the new tool participates in the shared update check
