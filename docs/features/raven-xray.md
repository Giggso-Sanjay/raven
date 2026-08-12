# raven-xray — the Code Map

**Status:** shipped · read-only tool, rebuilt automatically
**Script:** `scripts/raven-xray.py` (321 lines, pure stdlib)
**Written per** `CLAUDE.md` Rule A. Every claim below is verified against the code on disk.

---

## 1. What & why

**Comprehension debt** — nobody remembering what the AI wrote, or why. When code arrives faster
than anyone reads it, the question that matters is not "what does this function do" but
***"what breaks if I change it."*** raven-xray answers that from the CLI.

It parses Python with the stdlib `ast` module and stores a plain JSON symbol map. The non-choices
are deliberate, and stated in the tool's own docstring: *"Not a port of any external tool… no
tree-sitter, no native binary, no database."* Plain JSON is human-readable, diffable, grep-able, and
consistent with every other Raven store.

What it is **not**: a linter, a type checker, or a call graph you can trust for refactoring
automation. It is a *starting list to verify* — see §10.

---

## 2. Entry points

| Entry point | Purpose |
|---|---|
| `Stop` hook — `raven-xray.py --build --if-stale 15` | Automatic rebuild, throttled, async |
| `--build` | Rebuild the map now |
| `--if-stale MINUTES` | With `--build`: skip if the map is younger than N minutes (silent) |
| `--callers NAME` | Who calls this function/method? |
| `--callees NAME` | What does this function/method call? |
| `--impact NAME` | **Blast radius** — who is affected if this changes? |
| `--max-hops N` | Depth for `--impact` (default 3) |
| `--status` | Map stats as JSON |
| no args | argparse help |

Unknown flags are **warned about and ignored**, not fatal (`parse_known_args`, `:284`) — a
deliberate fail-soft choice, because this runs from a hook where a non-zero exit is expensive.

---

## 3. Hooks

| Event | Matcher | Script | Args | Sync | Timeout |
|---|---|---|---|---|---|
| `Stop` | `*` | `raven-xray.py` | `--build --if-stale 15` | async | — |

`Stop` fires at the **end of every turn**, not at session end. Without `--if-stale` the whole tree
would be re-parsed every turn; without `--build` the hook does nothing at all but print help — both
have happened (see §8).

---

## 4. Trigger conditions

**Rebuilds when:** `--build` is passed **and** either `--if-stale` is absent, or
`is_stale(minutes)` (`:199`) reports the stamp older than that many minutes.

**Files scanned:** every `*.py` under the project root (`iter_python_files`, `:56`), except these
directory names at any depth (`EXCLUDED_DIRS`, `:29`):

```
.git  __pycache__  node_modules  .venv  venv  env
.raven  dist  build  .mypy_cache  .pytest_cache
```

**Skipped individually:** any file whose `ast.parse` raises. The skip is announced on stderr and the
build continues — one unparseable file never fails the map.

**Root anchoring:** `find_project_root()` (`:35`) walks up from cwd to the nearest `.git`, falling
back to cwd. Same fix pattern as `9de4131` — a literal cwd-relative path breaks the moment a hook
runs from a nested directory.

---

## 5. Flow

1. `main()` (`:275`) — `--build` short-circuits everything else
2. `is_stale()` (`:199`) — compares `xray-stamp.json` mtime against `--if-stale`; fresh ⇒ silent return
3. `build_map()` (`:141`) — for each file, `parse_file()` (`:128`) walks the AST collecting
   function/class definitions and call sites
4. Node ids are built as `file:name:lineno` (`_node_id`, `:64`)
5. **Call edges resolved by unqualified name** (`:157-166`) — a `by_name` dict maps bare names to
   the *first* definition found. This is the single most important limitation; see §10
6. `write_map()` (`:181`) — writes `xray.json.tmp` then `replace()`s it into place, so a killed
   `Stop` hook cannot leave a half-written map. Stamp written alongside; summary to **stderr** (`:196`)
7. Queries: `load_map()` (`:211`) → `_indices()` (`:215`) builds caller/callee lookups →
   `query_callers` / `query_callees` / `query_impact`
8. `query_impact()` (`:252`) is a **breadth-first walk over callers**, bounded by `--max-hops` — the
   opposite direction from `--callees`

---

## 6. Files touched

| Path | Contents | Gitignored |
|---|---|---|
| `.raven/xray.json` | the map — `generated_at`, `scope`, `nodes`, `edges`, `files`, `imports` | yes |
| `.raven/xray-stamp.json` | stats + `--if-stale` timestamp source | yes |
| `.raven/xray.json.tmp` | transient; renamed atomically | yes |

### Schema

```json
"nodes": {
  "scripts\\raven-xray.py:build_map:141": {
    "name": "build_map", "type": "function",
    "file": "scripts\\raven-xray.py", "line": 141
  }
},
"edges": [
  { "src": "<node id>", "dst": "<node id>", "rel": "calls" }
]
```

---

## 7. Config & state

There is none. No config file, no tunables beyond the CLI flags, no environment variables. The only
persistent state is the map and its stamp, both regenerable at any time by deleting them and running
`--build`.

Current map for this repo:

```json
{ "nodes": 620, "edges": 856, "files": 83,
  "scope": "python-only, static-import-resolution-only" }
```

---

## 8. Failure modes

| Condition | Behaviour |
|---|---|
| A file fails to parse | Skipped, noted on stderr, build continues |
| Map missing on a query | `raven-xray: no map built yet — run with --build first` on stderr, returns cleanly |
| `--status` with no stamp | `no stamp file — map never built` on stderr |
| Unknown flag | Warned on stderr, ignored — never fatal |
| Build killed mid-write | Atomic `.tmp` + `replace()` means the previous map survives intact |
| Hook wired without `--build` | **The map is never built at all** — the hook prints help and exits 0. Shipped for months (BUG-015: the exporter stripped every flag) |
| Hook wired without `--if-stale` | Full tree re-parsed every turn — the waste `b37f2ba` fixed |

### On a legacy Windows console

Listed in BUG-017's sweep, but **not actually exposed**, and the reason is worth recording so nobody
"fixes" it unnecessarily:

- the build summary and all warnings go to **stderr**, which Python gives `backslashreplace` by
  default — the arrow degrades to a literal `→` rather than raising
- the only non-ASCII on **stdout** is the em-dash in the `--impact` header, and cp1252 *does* encode
  U+2014

Verified: `PYTHONIOENCODING=cp1252 raven-xray.py --build` and `--impact` both exit 0 with output
intact.

### Windows checkout artifact

On a clone with `core.symlinks=false`, git materialises symlinks as text files holding a path, so
`ast.parse` rejects them:

```
xray: skipping raven-core\vault-load.py (parse error: invalid syntax (vault-load.py, line 1))
```

**26 such skips on this checkout.** Harmless — every one is a mirror whose canonical copy in
`scripts/` is parsed normally — but it makes the build noisy and can mask a genuine syntax error in
the same output.

---

## 9. How to verify

```bash
python3 scripts/raven-xray.py --build
python3 scripts/raven-xray.py --status
# expect JSON with non-zero nodes / edges / files

python3 scripts/raven-xray.py --callers build_graph
#   _load_or_build_graph  (scripts\dashboard.py:1442)
#   main                  (scripts\knowledge_graph.py:192)
#   test_golden_vault     (tests\test_knowledge_graph.py:35)

python3 scripts/raven-xray.py --impact find_project_root --max-hops 2
#   Impact of changing 'find_project_root' — 3 symbol(s) within 2 hop(s):
#     main                (scripts\session-start.py:613)
#     notify_status_line  (scripts\session-start.py:403)
#     write_model_env     (scripts\session-start.py:412)
```

### The break-it step (Rule C)

```bash
mv .raven/xray.json /tmp/ && python3 scripts/raven-xray.py --callers build_graph
# expect: "raven-xray: no map built yet — run with --build first"
python3 scripts/raven-xray.py --build      # recovers
```

Also confirm the hook keeps its flags — a silently flagless hook is how this feature died once:

```bash
python3 scripts/check-distribution-coverage.py
# expect PASS, and it compares ARGS, not just script names
```

---

## 10. Known limits

**Read these before trusting an answer.** They are stated in the tool's docstring and are not
theoretical — here is one visible in real output from this repo:

```bash
$ python3 scripts/raven-xray.py --callees build_map
now                (raven-core\registry\raven-register.py:33)     ← WRONG
iter_python_files  (scripts\raven-xray.py:56)
parse_file         (scripts\raven-xray.py:128)
```

`build_map` calls a local `now()`, but edges resolve on **unqualified name, first definition wins**,
so the resolver bound it to an unrelated `now()` in a different file.

| Limit | Consequence |
|---|---|
| **Python only** | No JS/TS/other languages. Frontend is invisible. |
| **Static imports only** | `importlib`, string dispatch and decorator-registered handlers are unresolved — `ast` alone cannot see them without executing the code |
| **Unqualified-name matching** | First definition wins; same-named functions across files produce **false edges** (above). Common names — `main`, `run`, `now`, `load` — are the worst offenders |
| **No class/instance awareness** | `self.foo()` and `Other.foo()` resolve to the same `foo` |
| **One map per project root** | No cross-repo / monorepo support |
| **Line numbers are a snapshot** | Node ids embed `lineno`; edit a file and ids shift until the next build |

**Treat `--impact` as a starting list to verify, not proof of completeness.** It over-reports on
common names and under-reports on dynamic dispatch — the two errors do not cancel out.

---

*Raven v5.0.0 — MIT — github.com/giggsoinc/raven*
