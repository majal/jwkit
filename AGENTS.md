# AGENTS.md

Guidance for contributors and AI agents. Repo: `jwkit` -- tools for pulling/processing jw.org content: `slverse`
(Bible sign-language clips), `jwdl` (music/periodicals/video), `jwvideo-mux` (multi-language video mux), `ffrife`
(AI frame interpolation library). Split from `majal/maj-scripts` 2026-08-13. History, `jwdl video` vs `jwvideo-mux`
rationale, and full detail on the shared-module features below: `docs/contributor-reference.md`.

Template compliance: repo-template-standard.md v1.3.0 (reviewed 2026-10-10: item 11 n/a). Config-first/flag-parity and
modularity retrofits tracked in `ags/docs/reports/2026-08-31-cross-repo-standards-rollout-handoff.md`.

## Naming
No `jw` prefix by default (the repo scopes it). Don't rename `jwdl` or `jwvideo-mux`: `jwdl` has a live external caller.

## Configuration
- One config namespace: `~/.config/jwkit/<tool>/` (retired pre-jwkit paths are not read). New tools follow it from the start.
- Config-first: every persisted setting has a long CLI flag for a one-run override (short aliases for the common ones);
  keep config, CLI help, docs and tests in sync; never hardcode one operator's language order, paths or workflow.
  Positional ids and one-shot actions need no config.
- Canonical interface: `config list|get|set|path|edit|reset|diff|check`; tool-local TOML at
  `~/.config/jwkit/<tool>/config.toml`, shared settings at `~/.config/jwkit/config.toml`. Unix-style output/exit
  status, `$VISUAL` then `$EDITOR`, reject unknown keys/invalid values, `config check` is non-mutating. Reuse
  `_jwkit_common.py` helpers. Persist only overrides (`save_config` filters through `_jwkit_common.config_overrides`).
  When retiring a key/path, migrate active installs first, then remove the compat branch.

## Push cadence and rules
- **Commit is automatic** (operator-directed 2026-08-14): commit each verified change right away, narrow, one logical
  change per commit.
- **Push is deliberately batched, and a push to `main` IS the deploy**: `jwdl-weekly.service` /
  `slverse-sync-weekly.service` on `emeth4` fast-forward from `origin` before every unattended run. Push once you have
  verified a batch as a whole, when asked, or before ending a session; hold it if concrete follow-up is coming and
  nothing needs the fix live. Never push with unresolved errors or unpassed verification (leave a status note with
  the next step). Run `python3 -m tests` before pushing tool/test/README/AGENTS changes.
- Never force-push or rewrite history without the user's explicit go-ahead.

## Operational Notes
- **`jwdl` is called by a live systemd user timer on `emeth4`** (`~/.config/systemd/user/jwdl-weekly.service` + `.timer`,
  `jwdl all`, weekly). Coordinate changes to the music CLI surface (`jwdl <pub> [lang]`, `jwdl all`, `jwdl list`) with
  that unit in the same rollout; don't keep an obsolete CLI solely for the service.
- **`slverse` also has one** (`slverse-sync-weekly.service`, `slverse sync all`). Keep the unit source in the `bin` repo
  aligned with the deployed copy. When auditing live callers inspect `ExecStart=` across ALL
  `~/.config/systemd/user/*.service` and (`sudo`) `/etc/systemd/system/*.service`.
- Auto-update (default on) fast-forwards the checkout BEFORE these unattended jobs, so a bad push to `main` reaches the
  hosts on their next scheduled run with no review. Test before pushing.

## Shared-module contracts (`_jwkit_common.py`; detail in the reference doc)
- Auto-update: every tool calls `maybe_auto_update(jwkit_root)` right after `parse_args()`; fast-forward only; must never
  raise into a tool's real command (broad `except Exception: pass`).
- Overwrite handling: any tool writing a final output file calls `resolve_output_conflict(path, jwkit_config)` right before
  writing and honors its result (`None` = abort/skip); add `--on-exists`/`--on-exists-unattended`/`--overwrite-timeout`
  flags (pattern: `ffrife run`).
- Provenance: tools rendering media from a known source call `write_provenance(...)` and add
  `add_provenance_arguments(parser)`; embedding must not re-encode or damage the file (fall back to a sidecar if the
  remux can't be verified); never let a provenance problem fail a run whose video exists; `jwdl` and `jwvideo-mux`
  sources are deliberately not recorded (verbatim jw.org files, MD5 freshness checks).
- Installers (`install.sh`/`install.ps1`): idempotent (also the update mechanism); `install.ps1` is unverified on real
  Windows (extra care); both hardcode a `TOOLS`/`$Tools` list that must include every new tool, alphabetically.

## Agent Working Rules
- CLI/API tools before GUI/browser automation.
- Reports/audits/sweeps touching this repo go in `docs/reports/`, never a hosted `claude.ai` artifact, gist or
  pastebin unless the operator explicitly asks for a shareable link.
- **Public repo**: anything committed is world-readable; never store secrets, API keys or sensitive local state here
  (use OS-local config, env vars or home paths).
- Normal file edits inside this checkout are pre-approved. Still ask before escalated actions: destructive commands,
  writes outside this repo/writable roots, GUI/system-level actions, sandbox-blocked network commands.

## Local Memory
One shared store for every agent: `memory/`. Rules: `~/dig/ags/docs/memory-standard.md`; tool: `~/dig/ags/bin/memory-check`.
- Read `memory/MEMORY.md` (generated) first; open a topic only when its hook fits; else `memory-check find <kw>`.
- Record durable facts the same turn: search first, add/update a topic with a short `description`,
  `memory-check reindex`, commit. Never hand-edit `MEMORY.md`. Finished incidents: `status=resolved` +
  `memory-check archive`. Never store secrets, tokens or raw transcripts.

## When Adding A Tool (checklist; README/doc templates in `docs/contributor-reference.md`)
- add the tool file; README table of contents entry + short `## Tools` subsection (name, blurb, `Full docs:` link) +
  `docs/<tool>.md` full template with back-link; keep `## Tools` above Your Local Setup; `↑ TOC` consistently
- keep tool lists **alphabetical** everywhere (README TOC, `## Tools`, `TOOLS`/`$Tools` in `install.sh`/`install.ps1`);
  add the tool to both installers
- store config/state under `~/.config/jwkit/<tool>/` (migration helper when renaming/moving)
- if it has a live external caller (cron/systemd elsewhere), note it under Operational Notes and coordinate the migration
- call `maybe_auto_update(...)` after `parse_args()`; record provenance if rendering from a known source; call
  `resolve_output_conflict(...)` before writing a final output (plus the three flags)
- keep examples short, practical, copy-pasteable; tone practical and skimmable; keep README headings stable
