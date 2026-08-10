# Factory Configuration
<!-- This file configures the Remote Factory for your project. -->
<!-- The factory reads this during Init mode and generates .factory/config.json from it. -->
<!-- Fill in each section below. -->

## Goal

Local-first coworking workspace where a user and an AI agent (Claude Code CLI) work side by side on the user's files — producing live artifacts, scheduled tasks, and MCP connector access — through a local web workspace served by FastAPI.

## Scope

### Modifiable
<!-- Files and directories the factory is allowed to create or edit. -->

- src/**/*.py
- cowork/**/*.py
- app/**/*.py
- tests/**/*.py
- eval/**
- static/**
- templates/**
- pyproject.toml
- CLAUDE.md
- AGENTS.md
- factory.md
- devlogs.md
- scripts/**

### Read-only
<!-- Files the factory may read but must never modify. -->

- specs/**
- docs/**

## Guards
<!-- Rules the factory must never violate. Checked before every commit. -->

- Do not delete or overwrite existing tests
- Do not modify files outside the declared scope
- Do not introduce secrets or credentials into the repository
- Do not modify spec files (specs/) — they are approved and read-only
- Do not modify research docs (docs/) — they are reference material

## Eval

### Command
<!-- The shell command the factory runs to score a change. -->

```bash
python eval/score.py
```

### Threshold
<!-- Minimum composite score (0.0-1.0) required to keep a change. -->

0.6

## Target Branch

main

## Project Eval
<!-- User-defined eval dimensions from eval_spec.json -->

- Start the dev server and confirm the landing page loads without errors
- Verify the main navigation links resolve to valid pages

## Eval Weights
<!-- Using defaults: 30% hygiene + 20% growth + 50% project eval -->

## Hypothesis Budget

- min_growth: 1
- max_new: 2

## Smoke Test
<!-- e2e smoke test command. Failure = mandatory revert. -->

```bash
python -c "import ast; import pathlib; [ast.parse(f.read_text()) for f in pathlib.Path('.').rglob('*.py') if '.factory' not in f.parts and '.venv' not in f.parts]"
```

## Test Timeout

600

## Constraints
<!-- Soft rules that guide behavior but don't block commits. -->

- Prefer small, incremental changes over large rewrites
- Each change should be accompanied by at least one test
- Follow the existing code style and conventions
- Stack is locked: Python 3.12+, SQLite (WAL), FastAPI + uvicorn + websockets, pydantic, loguru
- No new frameworks or libraries unless justified in a spec/PRD
- No Electron — UI is server-rendered/static assets served by FastAPI
- Type hints required on all Python code
