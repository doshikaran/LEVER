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
- Test command: pytest
- Domain code (domain/) must never import e2b or openai directly — only
  through the Protocol interfaces in domain/ports.py

## Full specification: 
- docs/SPEC.md — read the relevant section before implementing anything.

