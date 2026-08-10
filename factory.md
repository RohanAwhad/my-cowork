# Factory Configuration — cowork

## Project
- **Name:** cowork
- **Description:** Local-first coworking workspace for Claude Code CLI
- **Language:** Python 3.12+
- **Framework:** FastAPI + uvicorn + websockets

## Target Branch
main

## Eval Command
```bash
python eval/score.py
```

## Eval Weights
- hygiene: 0.5
- growth: 0.5

## Modifiable Surfaces
- cowork/**/*.py
- tests/**/*.py
- eval/score.py
- pyproject.toml
- static/**/*
- factory.md

## Fixed Surfaces
- specs/**/*
- docs/**/*
- .factory/**/*

## Scope
All source code under `cowork/`, tests under `tests/`, eval harness under `eval/`, static assets under `static/`, and project config files at root.
