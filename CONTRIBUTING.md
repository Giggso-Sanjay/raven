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
   - Skill count? `find skills -name SKILL.md | wc -l`. This is the same formula
     `plugin/make-plugin.sh` uses, but it runs without `zip` installed — the build
     script exits 127 on a machine without it, which is how 61 survived in 19 places.
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

Every command above works with no extra tooling. Do **not** make the authoritative
count depend on `make-plugin.sh` alone: it needs `zip`, which is absent on a default
Windows install, so the mandated check silently became unrunnable and no one noticed
the number was wrong.

Counts are also enforced at commit by `scripts/check-counts.py` (gate 7) — it recounts
from disk and fails if any tracked file disagrees. Do not hand-edit a count without
running it.

## Single source of truth

Some directories are intentionally the canonical source; their mirrors are built
from them, never edited directly:

- **Skills**: root `skills/` is canonical. The plugin build bundles it.
- **Scripts**: root `scripts/` is canonical. `raven-core/`, `.claude/scripts/` and
  `plugin/scripts/` are **symlink mirrors** of it (git mode `120000`), e.g.
  `.claude/scripts/push-gate.py -> ../../scripts/push-gate.py`. They are not copies
  and cannot drift, so there is nothing to keep in sync by hand — edit `scripts/`
  and every mirror follows. `scripts/check-engine-drift.py` (gate 1) enforces this
  and fails on any mirror entry that is a real file instead of a symlink.
  Note `raven-core/` is a *partial* mirror; the gate only checks entries that exist,
  so adding a script there is optional but adding it as a **copy** is not.
- **Commands**: `core/commands/` is canonical. The build bundles it.
- **Pre-commit hook**: `core/hooks/pre-commit` is the shipped source.

If you edit a guard/hook script, edit it in `scripts/` only — the mirrors are
symlinks and follow automatically. Then run `python scripts/check-all-gates.py --tests`
and confirm exit 0.

There is no ZIP to rebuild. `plugin/raven-plugin-v4.1.0.zip` was removed (2026-08-13):
it was a v4.1.0 artifact still tracked in a 5.0.0 repo, stale for many releases, while
the real distribution path is the marketplace clone. `make-plugin.sh` is kept for its
air-gap check (it aborts if enterprise scripts reach the bundle), not as a release step.

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
