# jwkit — Claude Code entry point

This file exists only because Claude Code auto-loads `CLAUDE.md` by
convention. All actual instructions live in `AGENTS.md` (shared across every
agent that works in this repo — Codex, Antigravity/Gemini, or any future
agent) so there is one source of truth instead of per-agent forks that
drift apart.

Do not add Claude-specific instructions to this file. Add them to
`AGENTS.md` — if a rule matters, every agent needs it, not just this one.
That includes memory: this workspace's `memory/` folder is the one shared
memory store (see `AGENTS.md`'s "Local Memory" section) — do not keep
jwkit context in a Claude-only memory store instead.

@AGENTS.md
