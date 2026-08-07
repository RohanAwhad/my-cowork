#!/usr/bin/env python3
"""Factory eval harness for cowork project.

Scores hygiene and growth dimensions, outputs JSON to stdout.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or PROJECT_ROOT)


def score_tests() -> float:
    """Run pytest, score based on exit code."""
    result = _run([sys.executable, "-m", "pytest", "--tb=short", "-q"])
    if result.returncode == 0:
        return 1.0
    if result.returncode == 5:
        return 0.0
    return 0.2


def score_lint() -> float:
    """Run ruff check, score based on findings."""
    result = _run([sys.executable, "-m", "ruff", "check", "."])
    if result.returncode == 0:
        return 1.0
    lines = [line for line in result.stdout.strip().splitlines() if line.strip()]
    error_count = len(lines)
    if error_count <= 2:
        return 0.8
    if error_count <= 10:
        return 0.5
    return 0.2


def score_type_check() -> float:
    """Run mypy, score based on findings."""
    result = _run([sys.executable, "-m", "mypy", "cowork/", "--ignore-missing-imports"])
    if result.returncode == 0:
        return 1.0
    error_lines = [line for line in result.stdout.splitlines() if ": error:" in line]
    error_count = len(error_lines)
    if error_count <= 2:
        return 0.8
    if error_count <= 10:
        return 0.5
    return 0.2


def score_coverage() -> float:
    """Score test coverage by checking if tests exist and cover key modules."""
    test_dir = PROJECT_ROOT / "tests"
    if not test_dir.exists():
        return 0.0
    test_files = list(test_dir.glob("test_*.py"))
    if not test_files:
        return 0.0
    src_modules = list((PROJECT_ROOT / "cowork").glob("*.py"))
    src_modules = [m for m in src_modules if m.name != "__init__.py"]
    if not src_modules:
        return 0.0
    tested_names = {f.stem.replace("test_", "") for f in test_files}
    src_names = {m.stem for m in src_modules}
    covered = tested_names & src_names
    return min(1.0, len(covered) / max(1, len(src_names)))


def score_config_parser() -> float:
    """Check if config module is importable and defines expected paths."""
    try:
        from cowork.config import DATA_ROOT, DB_PATH, SESSIONS_DIR

        if DATA_ROOT and DB_PATH and SESSIONS_DIR:
            return 1.0
    except ImportError:
        pass
    return 0.0


def score_architecture() -> float:
    """Check if key module files exist with content."""
    expected = [
        "cowork/__init__.py",
        "cowork/models.py",
        "cowork/config.py",
        "cowork/logging_config.py",
    ]
    found = 0
    for path_str in expected:
        p = PROJECT_ROOT / path_str
        if p.exists() and p.stat().st_size > 10:
            found += 1
    return found / len(expected)


def score_capability_surface() -> float:
    """Score based on how many major components are implemented."""
    components = [
        "cowork/models.py",
        "cowork/config.py",
        "cowork/logging_config.py",
        "cowork/storage.py",
        "cowork/runner_adapter.py",
        "cowork/session_manager.py",
        "cowork/event_bus.py",
        "cowork/workspace_server.py",
        "cowork/artifact_watcher.py",
        "cowork/permission_gate.py",
        "cowork/scheduler_engine.py",
        "cowork/connector_registry.py",
    ]
    found = 0
    for path_str in components:
        p = PROJECT_ROOT / path_str
        if p.exists() and p.stat().st_size > 100:
            found += 1
    return found / len(components)


def score_experiment_diversity() -> float:
    """Score based on variety of test types."""
    test_dir = PROJECT_ROOT / "tests"
    if not test_dir.exists():
        return 0.0
    test_files = list(test_dir.glob("test_*.py"))
    return min(1.0, len(test_files) / 6)


def score_observability() -> float:
    """Score based on logging infrastructure presence."""
    log_config = PROJECT_ROOT / "cowork" / "logging_config.py"
    if not log_config.exists():
        return 0.0
    content = log_config.read_text()
    checks = [
        "loguru" in content,
        "LOGGING_LEVEL" in content or "log_level" in content.lower(),
        "InterceptHandler" in content,
        "enqueue" in content,
    ]
    return sum(checks) / len(checks)


def score_research_grounding() -> float:
    """Score based on spec and docs presence."""
    specs = PROJECT_ROOT / "specs"
    if not specs.exists():
        return 0.0
    spec_files = list(specs.glob("*.md"))
    return min(1.0, len(spec_files) / 5)


def score_factory_effectiveness() -> float:
    """Score based on factory config and eval presence."""
    factory_md = PROJECT_ROOT / "factory.md"
    eval_score = PROJECT_ROOT / "eval" / "score.py"
    score = 0.0
    if factory_md.exists() and factory_md.stat().st_size > 50:
        score += 0.5
    if eval_score.exists() and eval_score.stat().st_size > 100:
        score += 0.5
    return score


def main() -> None:
    hygiene = {
        "tests": score_tests(),
        "lint": score_lint(),
        "type_check": score_type_check(),
        "coverage": score_coverage(),
        "config_parser": score_config_parser(),
        "architecture": score_architecture(),
    }
    growth = {
        "capability_surface": score_capability_surface(),
        "experiment_diversity": score_experiment_diversity(),
        "observability": score_observability(),
        "research_grounding": score_research_grounding(),
        "factory_effectiveness": score_factory_effectiveness(),
    }

    hygiene_avg = sum(hygiene.values()) / len(hygiene) if hygiene else 0.0
    growth_avg = sum(growth.values()) / len(growth) if growth else 0.0
    composite = 0.5 * hygiene_avg + 0.5 * growth_avg

    result = {
        "composite": round(composite, 4),
        "hygiene": {k: round(v, 4) for k, v in hygiene.items()},
        "hygiene_avg": round(hygiene_avg, 4),
        "growth": {k: round(v, 4) for k, v in growth.items()},
        "growth_avg": round(growth_avg, 4),
    }

    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
