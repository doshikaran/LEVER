# Lever — Agent Instructions

## What this is
Lever turns a code diff into a playable simulation. It executes the REAL
changed code in a sandbox and proves it isn't hallucinating the behavior
it shows. Phase 0 goal: prove one hand-constructed harness can pass a
differential test against real code in e2b. Nothing else matters yet.

## Non-negotiable invariants
- There are exactly SIX agents in the eventual system: Scout, Delta Analyst,
  Harness Engineer, Fidelity Verifier, Adversary, Synthesizer. Do not add a
  seventh without being told to.
- Deterministic components (Scout, Triager, Symmetrist) must never call an LLM.
  They are pure functions over parsed code. No exceptions.
- A harness pair (base version, head version) must differ ONLY in which
  version of the code they import. Everything else — stub config, seeds,
  clock values — must be byte-identical between the two.
- Never render or claim a simulation is verified without an actual passing
  differential test behind it. No silent fabrication, ever.
- Confidence in the harness is measured (agreement rate + variance across
  replicates), never self-reported by a model.

## Environment
- Python 3.12, venv at .venv/
- e2b API key in .env — read via python-dotenv, never hardcode it
- Optional `GITHUB_TOKEN` for private PRs / higher GitHub rate limits
- Test command: pytest
- Domain code (domain/) must never import e2b or openai directly — only
  through the Protocol interfaces in domain/ports.py

## Phase A intake (current)
- `POST /prs` with `{ "url": "https://github.com/org/repo/pull/N" }`
- `GET /demos` + `POST /demos/{heroId}/run` for curated fixtures
- `GET /health`
- Checkouts land under `data/checkouts/`
- Live script: `python scripts/run_pr_pipeline_live.py <pr_url>`

## Phase B generative harness
- Registry templates are a fast-path only (`domain/entry_point_registry.py`)
- Unknown entry points use `domain/harness_ir.py` + `domain/stubs/`
- Direct reference programs are generated beside harnesses; `tests/` is optional
- Synthetic unregistered fixture: `fixtures/wild_synth/`

## Phase C product UI
- `GET /sessions` lists persisted microworlds (SQLite ledger)
- Frontend route `/m/:changeId` hydrates from `GET /diffs/{changeId}`
- Share copies absolute permalink; receipt panel shows fidelity + genre
- Search fog streams during Adversary; pin works from rehydrated permalinks

## Phase D game stages
- `domain/world_director.py` emits `worldSpec` on every WidgetConfig
- Arena (`ArenaStage`) for throughput / retry-storm; `PermissionMatrix` for access-matrix
- UnionTree walk animation + boss celebrate only on empirical unsafe hits
- Evidence chart remains a toggle secondary view

## Phase E judge-proofing
- Degradation+ : `manualTestRecipe` + labeled `staticNotes` (still no toy)
- `docs/WILD_CORPUS.md` + `scripts/run_wild_corpus.py`
- Root `README.md`, `docs/DEMO_SCRIPT.md`, `scripts/demo_up.sh`

## Phase F stretch
- `GET /compose/demos/hero1` measured 2×2 composition
- `fixtures/state_workflow/` + synthesizer `state-machine` / WorkflowStage
- Scope cards on degrade from `proposedSpecs`
- Prospective hypothesis remains wired on the active base file

## Full specification:
- docs/SPEC.md — v2 trust bible (Symmetrist, Assayer, packs, agent contracts). Read before changing fidelity behavior.
- docs/SPEC_V3.md — hackathon win direction: real PRs, generative harnesses, game-like microworlds. Trust rules still defer to SPEC.md.
- docs/BUILD_PLAN_V3.md — phased build order for v3. Prefer this sequence over ad-hoc feature work.

