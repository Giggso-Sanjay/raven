# Dashboard cost drift — root cause & fix (2026-08-21)

## Symptom

- Dashboard "Spend — 30d" tile showed `$0` for this repo while the user
  recalled seeing `$13.09` elsewhere.
- Session-end banner (`📊 Session meters: ... · $0.01 · ...`) stayed flat
  at `$0.01` across an entire long session (45K+ tokens, 640+ calls).

## Investigation

Two separate things were checked and both turned out to share one root cause.

### 1. Dashboard shell vs legacy view — not actually disagreeing

`scripts/dashboard/core.py`'s `main()` computes one `metrics` dict via
`aggregate()` and passes the *same* object to both the new shell
(`render.py` → `dashboard/index.html`) and the legacy detailed view
(`core.py` → `dashboard/legacy.html`). Checked both built files directly —
neither contained `$13.09` at the time of investigation; both agreed on
`$0`. The two-dashboard split (introduced in `b8c11c1`) was real technical
debt (duplicated rendering logic, an unfinished shell with no project-hash
routing at all), but it was not the source of the cost discrepancy itself.

**Decision:** per user instruction, `dashboard.html`'s redirect stub and
`project_dashboard_uri()` now point at `dashboard/legacy.html` again as the
primary view. The shell (`index.html`) is no longer the default; the
per-project `#{project}` hash-routing filter (added earlier this session)
now targets `legacy.html`'s existing `openCodeTree()` switcher.

### 2. The real bug — `user_work` always reads back as 0

`.raven/.model-session.json` tracks two buckets:

- `raven_overhead` — Raven's own routing/classifier subprocess calls
  (`triage-router`, `architect-router`), written by `model-router.py` with
  an explicit `--source raven_overhead` flag.
- `user_work` — meant to be the real conversation (this session, actual
  Claude responses), populated by `scripts/session/token-meter-write.py`
  parsing the Stop-hook transcript.

`token-meter-write.py` additionally tried to re-classify each transcript
message as `raven_code` vs `user_work` using `is_raven_code()` — a heuristic
that flagged any tool call whose bash command or file path contained the
substring `.raven/`, `raven-`, or `.claude/scripts/`.

**This project is named `raven`.** Its own manifest lives at
`.raven/manifest.json`, its skills live in `skills/raven-*`, its core
scripts live in `raven-core/`. Nearly every real tool call in a genuine
working session on this repo touches a path containing "raven" — so
`is_raven_code()` returned `True` for effectively 100% of real messages.
Every real turn got folded into `raven_overhead` instead of `user_work`,
which is why `user_work.tokens`/`cost_usd` read `0` no matter how long the
session ran, and why the session-meter banner only ever showed the tiny,
separately-tracked router-classifier cost (`$0.01`) instead of the actual
session cost.

This is a self-referential classification bug: the heuristic that exists to
tell "Raven's internal bookkeeping" apart from "the user's actual work"
cannot function inside a project whose own name and directory convention is
"raven" — every legitimate action looks like Raven-internal activity to a
naive substring match.

## Fix

`scripts/session/token-meter-write.py`:

- Removed `is_raven_code()` and its call site. Every transcript-derived
  turn now attributes unconditionally to `user_work` — the transcript
  *is* the real conversation; there was never a need to re-derive Raven's
  own overhead from it, since `model-router.py` already tracks that
  overhead correctly and separately (its classifier calls aren't part of
  this transcript at all — they're distinct subprocess invocations).
- `write_session_json()`'s merge step no longer folds a (now permanently
  empty) `raven_code` bucket into `raven_overhead`.

## Why this wasn't caught earlier

The two-writer merge bug (`model-router.py` vs `token-meter-write.py` both
touching `.model-session.json`) had already been diagnosed and fixed once
before (see the read-merge-write comment history in both files) — but that
fix addressed *file-clobbering*, not *misclassification*. The
misclassification bug produced a value that looked plausible (a small,
nonzero, slowly-growing number) rather than an obvious error, so it passed
casual inspection for a long time.

## Recommendation — surface this class of drift automatically

The user's ask: this kind of drift should show up in logs/Obsidian
automatically, not require a manual "why is my cost $0" investigation.
Concretely:

- `obsidian-log.py` / `knowledge-extract.py` (Stop hook, async) should flag
  when `user_work.tokens == 0` for a session with `raven_overhead.calls`
  in the hundreds — that ratio is itself a strong drift signal and could be
  a one-line heuristic check appended to the existing session note.
- `token-guard.py`'s threshold checks (25/50/75/90%) are meaningless while
  `user_work.cost_usd` stays at 0 — worth a sanity check there too: if
  `raven_overhead.calls > 100` and `user_work.calls == 0`, warn instead of
  silently reporting "under threshold."

Not implemented in this pass — flagged as a follow-up, since it's a new
guard/heuristic rather than a bug fix.

## Files changed

- `scripts/session/token-meter-write.py` — removed `is_raven_code()`
  misclassification; transcript usage now always attributes to `user_work`.
- `scripts/dashboard/render.py` — redirect stub points at `legacy.html`.
- `scripts/memory/vault_common.py` — `project_dashboard_uri()` points at
  `legacy.html#{project}`.
