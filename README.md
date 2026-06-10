# Aviation MRO Job Watcher

An automated job-monitoring tool that watches global aerospace companies for senior engine operations and MRO (Maintenance, Repair & Overhaul) roles.

## What it does

This tool scrapes job boards and company career pages to surface roles suited to experienced aviation professionals in:

- Engine MRO management (shop managers, production leads, overhaul directors)
- Quality, compliance, and safety leadership in Part 145 / CAR 145 environments
- Technical services and engineering for powerplant / propulsion systems
- Regulatory and airworthiness roles (EASA, FAA, DGCA, GCAA, GACA)

It filters out junior, unrelated, and non-aviation roles so you only see what matters.

## Filter logic

Jobs pass through a 3-gate AND filter:

1. **Gate 1 — Title family**: The job title must include a seniority/domain term (manager, director, lead, MRO, overhaul, etc.)
2. **Gate 3 — Exclude**: The title must NOT contain junior or unrelated terms (technician, intern, software, pilot, etc.)
3. **Gate 2 — Engine domain**: The job description must contain at least 1 engine-specific term (GE90, CFM56, Part 145, etc.) AND at least 2 total domain hits

## Notifications

Matches are sent via Telegram message and/or Gmail email. Configure credentials in `.env` (copy from `.env.example`).

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate
pip install pytest requests pyyaml python-dotenv playwright
playwright install firefox
```

## Running tests

```bash
.venv\Scripts\activate
pytest tests/ -v
```

## Configuration

Edit `config.yaml` to tune keyword lists. Edit `.env` (copied from `.env.example`) to set notification credentials.
