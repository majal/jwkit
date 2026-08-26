# jwkit — Antigravity/Gemini entry point

This file exists only because Antigravity/Gemini tooling auto-loads
`GEMINI.md` by convention. All actual instructions live in `AGENTS.md`
(shared across every agent that works in this repo — Claude, Codex, or any
future agent) so there is one source of truth instead of per-agent forks
that drift apart.

Do not add Gemini-specific instructions to this file. Add them to
`AGENTS.md` — if a rule matters, every agent needs it, not just this one.
That includes memory: this workspace's `memory/` folder is the one shared
memory store (see `AGENTS.md`'s "Local Memory" section) — do not keep
jwkit context in a Gemini-only memory store instead.

@AGENTS.md
