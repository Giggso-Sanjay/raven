"""The shipped plugin must never auto-tier Opus or Fable (Rule 8).

Found 2026-08-13: plugin/scripts/session-start.py was a 651-line stale copy of the
750-line canonical and still carried

    "tiers": {"claude-haiku-4-5": "low", "claude-sonnet-4-5": "medium",
              "claude-opus-4-5": "high"}

with complex_pick = pick(high, medium_pick) selecting it. The repo's canonical file
was clean, so the source looked compliant while every INSTALL auto-picked Opus on
COMPLEX prompts. The drift gate said PASS because plugin/scripts was not in its
MIRRORS list at all.

Rule 8 is a property of what SHIPS, not of what is committed to scripts/. These tests
check the shipped surface.
"""
import importlib.util
import pathlib
import subprocess

_ROOT = pathlib.Path(__file__).parent.parent
CANONICAL = _ROOT / "scripts"
MIRRORS = [_ROOT / "raven-core", _ROOT / ".claude" / "scripts", _ROOT / "plugin" / "scripts"]
SYMLINK_MODE = "120000"
BANNED = ("opus", "fable")


def _index_modes():
    """git index modes — on Windows (core.symlinks=false) a symlink is a regular file
    whose content is the target, so is_symlink() lies."""
    out = subprocess.run(["git", "ls-files", "-s"], cwd=_ROOT, capture_output=True,
                         text=True, encoding="utf-8", errors="replace")
    modes = {}
    for line in out.stdout.splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if parts:
            modes[path.strip()] = parts[0]
    return modes


def _load(path):
    spec = importlib.util.spec_from_file_location("mod", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_canonical_never_auto_tiers_opus_or_fable():
    m = _load(CANONICAL / "session" / "session-start.py")
    offenders = [(p, mod) for p, cfg in m.CLOUD_PROVIDERS.items()
                 for mod in cfg.get("tiers", {})
                 if any(b in mod.lower() for b in BANNED)]
    assert not offenders, f"Rule 8: auto-tiered {offenders}"


def test_complex_tier_never_resolves_to_opus_or_fable():
    """The tier table could be clean while the fallback chain still reaches Opus."""
    m = _load(CANONICAL / "session" / "session-start.py")
    for provider, cfg in m.CLOUD_PROVIDERS.items():
        routing = m.build_routing([{"provider": provider, "tiers": cfg.get("tiers", {})}])
        for tier, target in routing.items():
            assert not any(b in target.lower() for b in BANNED), \
                f"Rule 8: {provider} {tier} -> {target}"


def test_shipped_session_start_cannot_diverge_from_canonical():
    """A symlink, or byte-identical. A drifting copy is how the hole appeared."""
    modes = _index_modes()
    shipped = _ROOT / "plugin" / "scripts" / "session-start.py"
    canon = CANONICAL / "session" / "session-start.py"
    rel = shipped.relative_to(_ROOT).as_posix()
    if modes.get(rel) == SYMLINK_MODE:
        target = shipped.read_text(encoding="utf-8").strip()
        assert not target.startswith("/"), f"absolute symlink: {target}"
        assert (shipped.parent / target).resolve() == canon.resolve(), \
            f"symlink points elsewhere: {target}"
    else:
        assert shipped.read_bytes() == canon.read_bytes(), \
            "shipped session-start.py is a drifting copy of the canonical"


def test_no_mirror_holds_an_absolute_symlink():
    """Seven plugin/scripts entries pointed into /Users/giggso/... — broken in every
    clone but the author's, and invisible to the gate because the canonical-exists
    check ran first."""
    modes = _index_modes()
    bad = []
    for mirror in MIRRORS:
        if not mirror.is_dir():
            continue
        for entry in sorted(mirror.rglob("*.py")):
            rel = entry.relative_to(_ROOT).as_posix()
            if modes.get(rel) != SYMLINK_MODE:
                continue
            target = entry.read_text(encoding="utf-8", errors="replace").strip()
            if target.startswith("/") or pathlib.PurePosixPath(target).is_absolute():
                bad.append(f"{rel} -> {target}")
    assert not bad, "absolute symlinks: " + "; ".join(bad)


def test_no_mirror_holds_a_broken_symlink():
    modes = _index_modes()
    bad = []
    for mirror in MIRRORS:
        if not mirror.is_dir():
            continue
        for entry in sorted(mirror.rglob("*.py")):
            rel = entry.relative_to(_ROOT).as_posix()
            if modes.get(rel) != SYMLINK_MODE:
                continue
            target = entry.read_text(encoding="utf-8", errors="replace").strip()
            if target.startswith("/"):
                continue  # covered by the absolute test
            if not (entry.parent / target).resolve().exists():
                bad.append(f"{rel} -> {target}")
    assert not bad, "broken symlinks: " + "; ".join(bad)
