# AGENTS.md

Guidance for future contributors and AI agents working in this repo.

Repo name: `jwkit`

## Purpose

`jwkit` holds tools for pulling and processing content from jw.org: Bible sign-language clips (`slverse`), music and periodicals (`jwdl`), videos (`jwvideo-mux`), and AI frame interpolation (`ffrife`, used as a library by `slverse` but not jw.org-specific itself).

Split out of [`majal/maj-scripts`](https://github.com/majal/maj-scripts) on 2026-08-13, once the jw.org-specific tools there outnumbered the general-purpose ones. `maj-scripts` keeps its own disparate utility scripts (`gmail-cleanup`, `whisper`, `wh`, `printing-mode`, `ubuntu-hibernate`, etc.); this repo is scoped to jw.org content tools only.

`jwget` (a legacy, unauthenticated bash periodicals scraper) was absorbed into `jwdl` as `jwdl periodicals` on the same day, then retired to `bin-archive-2026` — jw.org's modern `pub-media` API (checksummed, already used by `jwdl` for music) covers the periodicals that are still actually published; two of `jwget`'s four (`wp`, `g`) turned out to be discontinued jw.org-side years ago, not just stale locally.

## Naming

Tools here don't carry a `jw` prefix by default — the repo name already scopes them. `slverse` (sign-language verse extraction, formerly `jwsl`) follows this. `jwdl` and `jwvideo-mux` kept their existing names on the move rather than being renamed along with the repo split — don't rename them without explicit direction, since `jwdl` in particular has a live external caller (see Operational Notes below).

## Configuration

All tools share one config namespace, `~/.config/jwkit/<tool>/` (e.g. `~/.config/jwkit/slverse/`, `~/.config/jwkit/jwdl/`, `~/.config/jwkit/ffrife/`). Each tool auto-migrates its config on first run from wherever it used to live (pre-jwkit `~/.config/maj-scripts/<tool>/`, or `slverse`'s brief standalone `~/.config/slverse/` waypoint) — nothing is lost across a rename or the unification, including `ffrife`'s downloaded RIFE binary and `slverse`'s synced verse-marker index. New tools should follow this same `~/.config/jwkit/<tool>/` layout from the start rather than inventing their own.

## Operational Notes

- **`jwdl` is called by a live systemd user timer on `emeth4`** (`~/.config/systemd/user/jwdl-weekly.service` + `.timer`, `ExecStart=... %h/MyFiles/Digitalis/jwkit/jwdl all`, weekly). Any change to `jwdl`'s existing music CLI surface (`jwdl <pub> [lang]`, `jwdl all`, `jwdl list`) must stay backward-compatible, or the service needs a coordinated update on that host first. `jwdl periodicals ...` is a fully separate command path added specifically to avoid touching that surface — keep it that way rather than folding periodicals into the same `pub`/`all` positional.

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

When an agent completes requested repo changes and is confident the work is ready, commit and push them unless the user explicitly asks not to.

Do not push when there are unresolved errors or relevant verification has not passed. In those cases, leave a clear status note with the next step.

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

Doc filename: `docs/<tool-name>.md`, stripping a trailing `.sh` if the tool has one (e.g. `jwvideo-mux-shortcuts.sh` → `docs/jwvideo-mux-shortcuts.md`).

Keep examples short, practical, and copy-pasteable.

## Tone Rules

Same spirit as `maj-scripts`: practical and skimmable, a light touch is fine, but don't let it make setup instructions vague. Prefer friendly, calm wording in user-facing tool output too.

## Heading And TOC Rules

- Keep README headings stable and predictable so anchors remain valid.
- Prefer `## Tools` as the parent section and `### <tool-name>` for each tool.
- Prefer `### [<tool-name>](./<tool-file>)` when the tool file lives at the repo root.
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
