# LEVER — Phase G build plan
### Toward "most real-world PRs" · companion to `BUILD_PLAN_V3.md`

> **Status: PLAN ONLY — not implemented.**
> Goal: move Lever from "plain callables + heroes" to "most single-service backend
> logic PRs," while the trust gates (Symmetrist + differential + Assayer) get
> *stricter*, never looser.

> **Non-goal:** literally *every* PR. Distributed systems, live third-party
> services (payments, real IdPs), hardware, and uncontrollable races stay honest
> refusals (Degradation+). "Every PR" is asymptotic; we optimize the verified
> fraction and the usefulness of refusals.

---

## G0. Operating rules (unchanged from v2/v3)

1. Trust before theater. No verified badge without Symmetrist + differential agreement.
2. Every new stub / backend / harness template must be **pair-symmetric** (byte-identical across base/head except the imported module root).
3. Deterministic components (Scout, Triager, Symmetrist) never call an LLM.
4. Generated PR code is executed **only** in the sandbox, never on the host.
5. Publish the hit rate. Grow coverage and refusal quality together.

---

## G1. Multi-file / dependency-closure sandboxing (highest leverage)

**Problem:** the pipeline collapses a PR to one shared `.py` pair. Real PRs touch
many files and import a web of internal modules.

**Build**
- `domain/import_closure.py` — pure AST walk from the entry point over intra-repo
  imports, bounded by depth/node budget, producing a file set for each side.
- Extend `infra/checkout/dual_checkout.py` to stage the closure (or full package
  when small) into `/w/base` and `/w/head`.
- `infra/sandbox/` staging: tar-upload the closure subtree into e2b; run with the
  package importable (correct `sys.path` / package root).

**Done when**
- A multi-file fixture (new `fixtures/multifile_pkg/`) verifies end-to-end.
- Heroes 1–4 still green via the single-pair fast path.

**Risk / mitigation**
- Import graph explosion → depth + node cap, fall back to "primary pair + named
  missing modules" Degradation+ when the closure is too large.

---

## G2. Repo dependency install in the sandbox

**Problem:** most refusals are "needs a third-party import that isn't stubbable."

**Build**
- Detect and honor the repo's own manifest: `requirements.txt`, `pyproject.toml`
  (`poetry`/`uv`/`pip`), `setup.cfg`.
- Deterministic install step inside e2b (pinned, offline-cache where possible),
  timed and budgeted; failures degrade with the exact failing package named.
- Cache installed layers per `(repo, lockfile-hash)` to keep demo latency sane.

**Done when**
- A PR importing a common pure-Python third-party lib verifies without a stub.

**Risk / mitigation**
- Install latency / network → warm cache, hard timeout, Degradation+ on timeout.
- Symmetry: identical install into both base and head (same lock hash) — assert it.

---

## G3. Ephemeral real backends (kill the "needs a DB" wall)

**Problem:** DB/cache-touching code currently stubs or degrades.

**Build** `domain/stubs/backends/`
- Deterministic, seeded ephemeral **SQLite/Postgres/Redis** started inside the
  sandbox; same seed + same schema for base and head.
- Symmetrist extension: prove backend config + seed are byte-identical across the
  pair (a divergent seed is a hard fail, never a silent pass).
- Extractors read committed state / row counts as observables.

**Done when**
- A repository-pattern CRUD diff (new `fixtures/db_repo/`) verifies with a real
  seeded SQLite, and the Symmetrist proves seed symmetry.

**Non-goal:** external managed datastores; those remain refusals.

---

## G4. Framework test-client harnesses

**Problem:** Django/FastAPI/Flask views are `unscopable` today (live request object).

**Build** `domain/harness/frameworks/`
- Per-framework harness templates that drive the framework's **in-process test
  client** (no live server): FastAPI `TestClient`, Django test client, Flask test
  client.
- Scout upgrade: recognize a framework view/handler and route it to the matching
  template instead of the `unscopable` terminal.
- Observables from response status/body/headers, symmetric across base/head.

**Done when**
- A FastAPI route behavior-change PR verifies (new `fixtures/fastapi_route/`),
  and a genuinely un-clientable handler still degrades honestly.

---

## G5. Type-driven input synthesis + multi-pass repair

**Problem:** generative IR handles plain-data + construct-then-call; complex typed
args block harness generation, and the proposer gets only one repair pass.

**Build**
- Input synthesizers from annotations / dataclasses / Pydantic models / enums,
  producing valid constructed arguments for knobs.
- Fixture inference: read the repo's `conftest.py` / factory-boy / fixtures to
  reuse real input builders instead of guessing.
- Multi-pass repair loop (bounded, e.g. ≤3) feeding the **Fidelity Verifier
  divergence report** back into the proposer.
- Optional AST allowlist tightening for executed generated code.

**Done when**
- An entry point taking a Pydantic model verifies via synthesized inputs.
- Repair loop raises hit rate on the wild corpus without weakening any gate.

---

## G6. Nondeterminism control (only what we can control)

**Build**
- Virtual clock + seeded RNG already exist for heroes — generalize as first-class
  stubs applied symmetrically.
- Recorded/replayed network for deterministic outbound calls (record once, replay
  identically to base and head); anything unrecordable → refusal.
- Seeded scheduler for simple threaded/async cases; true races stay refusals.

**Done when**
- A time- or random-dependent diff verifies deterministically; an uncontrollable
  race degrades with a named reason.

---

## G7. Trust scaling (hard constraint, runs through all of G)

- Symmetrist proofs for **every** new stub/backend/framework harness.
- Assayer bands unchanged; no new path may emit a verified badge without them.
- Always-visible hit rate + Degradation+ remain part of the product, not a footnote.

**Done when**
- `scripts/run_wild_corpus.py` expands to a real public-PR corpus and prints a
  hit-rate table; README shows the live number.

---

## Feasibility tiers (honest)

| Tier | Feasible? | Phase G item |
|---|---|---|
| Plain callables / pure logic | Done (v3) | — |
| Multi-file internal-dep diffs | Yes | G1 |
| Third-party pure-Python deps | Yes | G2 |
| DB / cache / repository diffs | Yes | G3 |
| Framework request/handler diffs | Yes | G4 |
| Complex typed inputs | Yes | G5 |
| Time/random/replayable network | Partial | G6 |
| Distributed / live 3rd-party / hardware | **No** (refuse) | n/a |
| Non-Python | Out of scope for G | — |

---

## Suggested sequence (max verified-fraction per unit effort)

1. **G1** import-closure + staging (unlocks the most PRs).
2. **G2** repo dependency install (removes the biggest refusal class).
3. **G4** one framework test-client (FastAPI) + **G3** seeded SQLite.
4. **G5** type-driven inputs + multi-pass repair (raises hit rate on reachable PRs).
5. **G6** nondeterminism control where safe.
6. Measure on a real public-PR corpus; let the number drive the rest.

---

## New / changed files (expected — not yet created)

### New
- `domain/import_closure.py`
- `domain/stubs/backends/*`
- `domain/harness/frameworks/*`
- `fixtures/multifile_pkg/`, `fixtures/db_repo/`, `fixtures/fastapi_route/`
- corpus expansion in `scripts/run_wild_corpus.py`

### Major edits
- `infra/checkout/dual_checkout.py` — closure staging
- `infra/sandbox/*` — subtree upload + dependency install
- `domain/scout.py` — framework/view recognition, richer scoping
- `domain/harness_engineer.py` / `domain/harness_ir.py` — typed inputs, multi-pass repair
- `domain/symmetrist.py` — symmetry proofs for backends/frameworks (extend carefully)
- `interface/api.py` — larger checkouts, install/status progress events

### Do not destabilize
- `domain/symmetrist.py` invariants, Assayer math, Rendering-Fidelity rules,
  the "no toy on degrade" invariant.

---

## Definition of done for Phase G

You can paste a **real, un-hand-tuned single-service backend PR** (multi-file,
internal deps, maybe a DB or a framework route) and get either a **verified
playable microworld** or a **precise Degradation+** — with the published hit rate
going up and every trust gate still enforced.
