# Contributing to Raven

Thanks for working on Raven. A few rules keep this project trustworthy.

## The Truth Rule (non-negotiable)

**No claim ships unless it is true of the code as it exists right now.**

Raven is a discipline tool. If our own docs overstate what we do, we have no
standing to enforce discipline on anyone else. A v3.4 audit found several
documented features that did not exist (live token meter, email notifications,
"always-on" guards) and a skill count that was wrong in four different
directions. That is the exact failure mode this rule exists to prevent.

Before you write a number, a capability, or a "Raven does X" claim:

1. **Verify it against the running code**, not memory and not an older doc.
   - Skill count? `find skills -name SKILL.md | wc -l`. `bash plugin/make-plugin.sh`
     reports the same number, but it calls `zip` and exits before printing anything
     on a machine without it — a default Windows install among them. That gap is how
     "61 skills" survived in 37 places while `skills/` held 62 (2026-08-13).
   - Guard/hook behavior? Read the script. Confirm it actually fires.
   - A feature? Run it. If it only half-works, say so.
2. **If it is not built, do not document it as built.** "On the roadmap" is fine
   — but mark it clearly, and remove the roadmap note the moment it ships.
3. **No "always-on" language** for things that fire conditionally. Say when they fire.

This is enforced in two places:
- **In-session**: `CLAUDE.md` Rule 5 ("NO DOCUMENTING FEATURES THAT DO NOT EXIST").
- **At commit**: the pre-commit truth-guard check (when `truth-guard.py` is present).

## Counts: always verify, never hardcode from memory

| Thing | How to get the real number |
|---|---|
| Skills shipped | `find skills -name SKILL.md \| wc -l` |
| Guard agents | `find agents -name '*.md' \| wc -l` |
| Slash commands | `find core/commands -name '*.md' \| wc -l` |
| Scripts bundled | the `make-plugin.sh` report's "N OSS scripts bundled" line |

Every command above needs nothing but the shell. Do not make the authoritative count
depend on `make-plugin.sh` alone — see the `zip` gap noted above.

Counts are enforced at commit by `scripts/ops/check-counts.py` (gate 7) — it recounts
from disk and fails if any tracked file disagrees. Do not hand-edit a count without
running it.

## Single source of truth

Some directories are intentionally the canonical source; their mirrors are built
from them, never edited directly:

- **Skills**: root `skills/` is canonical. The plugin build bundles it.
- **Scripts**: root `scripts/` (now organised into `routing/ guards/ memory/ session/
  ops/ dashboard/`) is canonical. `raven-core/`, `.claude/scripts/` and `plugin/scripts/`
  are **symlink mirrors** (git mode `120000`) — not copies, so there is nothing to keep
  in sync by hand. `scripts/ops/check-engine-drift.py` (gate 1) enforces this: it
  resolves each mirror entry against a canonical index built by basename across all of
  `scripts/**`, validates every symlink for its own sake (broken or absolute is a
  failure regardless of whether a canonical twin exists), and reports
  `AMBIGUOUS CANONICAL` if a basename exists at more than one path under `scripts/`.
  A 2026-08-13 audit found `plugin/scripts/session-start.py` shipped as a 651-line
  stale COPY that still auto-tiered Opus (Rule 8) while `scripts/session/session-start.py`
  was clean — the gate had not been checking `plugin/scripts` at all. Adding a script to a
  mirror as a copy instead of a symlink is exactly what that gate now catches.
- **Commands**: `core/commands/` is canonical. `commands/` and `plugin/commands/` are
  built COPIES, not symlinks — no gate currently checks them against `core/commands/`,
  so they can silently drift (found and fixed once, 2026-08-13: `commands/run-costs.md`
  was missing entirely, and `raven-debug.md` differed by two lines across the three
  copies). Diff all three before trusting any of them.
- **Pre-commit hook**: `core/hooks/pre-commit` is the shipped source.

If you edit a guard/hook script, edit it in `scripts/` only — the mirrors are symlinks
and follow automatically. If you edit anything under `core/commands/`, copy the change
into `commands/` and `plugin/commands/` by hand until those mirrors are symlinked too.
Then rebuild the plugin (`bash plugin/make-plugin.sh`) and commit the new ZIP — unlike
the 4.x line, **the ZIP here is live**: README points installs at
`plugin/raven-plugin-v{VERSION}.zip` directly. Run
`python scripts/ops/check-all-gates.py --tests` before committing either way.

## Deletions

Intentional deletions need the flag in the commit message:

```
git commit -m "chore: remove X [GUARD:ALLOW-DELETE]"
```

Note: with `git commit -m`, a pre-commit hook cannot read the message (git writes
it after pre-commit runs). Until that is fixed, pre-populate the message:

```
printf 'chore: remove X [GUARD:ALLOW-DELETE]\n' > .git/COMMIT_EDITMSG
git commit -F .git/COMMIT_EDITMSG
```

## Secrets

Never commit `.raven/manifest.secrets.json`, `.env`, or key files. The secret-scan
guard will block you — but don't rely on it; keep secrets out by habit.

---

MIT — [Giggso](https://giggso.com)
