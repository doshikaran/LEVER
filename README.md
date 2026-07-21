# Lever

Lever turns a code diff into a **verified playable microworld**: it checks out base and head, builds a symmetric harness, differential-tests against real code in a sandbox, then lets you drag knobs — or refuses honestly when it cannot prove the toy.

## How to run

```bash
cd lever
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # if present; else project deps already in .venv
cp .env.example .env              # set OPENAI_API_KEY, E2B_API_KEY; optional GITHUB_TOKEN
chmod +x scripts/demo_up.sh
./scripts/demo_up.sh
```

Open the printed UI URL (default `http://127.0.0.1:5173`). Health: `GET http://127.0.0.1:8765/health`.

## What works / what refuses

| Works | Refuses (no fake toy) |
|---|---|
| Curated heroes 1–4, wild_synth, state-workflow demo chips | Live framework objects (Django/Flask request, etc.) |
| Public GitHub PR intake (`POST /prs`) when a shared `.py` pair exists | Raw diffs without repo context |
| Generative harness for plain callables not in the registry | Native / IdP / unverifiable deps after Loop A |
| Arena / matrix / path / workflow stages + Search fog | Anything without Symmetrist + differential agreement |
| Pin-as-test, permalink `/m/:changeId`, compose 2×2 demo | — |

## Live hit-rate

Run `python scripts/run_wild_corpus.py` and paste the JSON `hit_rate_verified_or_honest` here before demos.

**Last measured (unit corpus path):** `hit_rate_verified_or_honest = 1.0` (W1 generative IR, W2 hero fixture+genre, W3 Degradation+).

## Specs

- [`docs/SPEC.md`](docs/SPEC.md) — trust bible (Symmetrist, Assayer, packs)
- [`docs/SPEC_V3.md`](docs/SPEC_V3.md) — product direction
- [`docs/BUILD_PLAN_V3.md`](docs/BUILD_PLAN_V3.md) — phased build
- [`docs/WILD_CORPUS.md`](docs/WILD_CORPUS.md) — Wild Three
- [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) — 90s rehearsal
