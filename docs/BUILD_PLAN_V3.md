# LEVER v3 — Detailed Build Plan
### Companion to `SPEC_V3.md` · hackathon execution order

> Goal: turn Lever from a four-hero verified demo into a **paste-any-Python-PR → verified behavioral game** product, without breaking v2 trust invariants.  
> Strategy: ship vertical slices that are always demoable; never unlock UI gloss before generality + intake.

---

## 0. Operating rules

1. **Trust before theater.** No verified badge without Symmetrist + differential agreement.
2. **Registry is optional fast-path**, never a gate, starting Phase B.
3. **Every phase ends with a runnable demo script** and a regression check on Heroes 1–3.
4. **Measure hit rate** as soon as PR intake exists; put the number in README.
5. **Cut order if behind:** Composed → Prospective polish → Boss fight → Path theater polish → Session ledger → **never cut** intake, generative harness, verifier gate, Arena, degradation+.
6. Keep domain pure: no direct `e2b` / `openai` / `httpx` imports inside `domain/` (ports only).

### Suggested time boxes (adjust to remaining hackathon days)

| Phase | Focus | Suggested share of remaining time |
|---|---|---|
| A | PR intake + dual checkout | 15% |
| B | Generative harness (kill hard gate) | 30% |
| C | Frontend: PR-first + Search fog | 15% |
| D | Arena game + WorldSpec | 15% |
| E | Degradation+ + Wild Three + deploy | 15% |
| F | Polish / stretch | 10% |

If you only have **2–3 days**, do **A → B → C → E** and a minimal Arena (D-lite).

---

## Phase A — Real PR intake (foundation)

### A1. GitHub PR resolver
**Build**
- `infra/github/pr_resolver.py` implementing a port `PullRequestResolver`
- Input: PR URL → `{repoUrl, baseSha, headSha, title, changedFiles[]}`
- Support public repos first; private via `GITHUB_TOKEN` / App later

**API**
- `POST /prs` body `{ "url": "https://github.com/org/repo/pull/N" }` → `202 { changeId }`
- Reuse existing WebSocket `/ws/{changeId}` event protocol

**Done when**
- Unit tests with recorded GitHub fixtures (no network in CI)
- One live manual: resolve a known public PR

### A2. Dual checkout
**Build**
- `infra/checkout/dual_checkout.py`
- Materialize worktrees or shallow clones for base/head
- Prefer sparse checkout of changed files + import closure heuristic (start simple: full shallow clone if small; sparse later)

**Sandbox staging**
- Sync `/w/base` and `/w/head` into e2b (tar upload or `git` inside sandbox)
- Orchestrator receives paths like today’s file paths, but under checkout root

**Done when**
- Hero fixtures still run via local paths
- One public PR clones and Scout can read both trees

### A3. Wire orchestrator
**Change**
- `run_pipeline` accepts either local pair **or** `CheckoutHandle`
- Triager/Scout run over real multi-file trees (start: primary changed `.py` files; expand carefully)

**Done when**
- `scripts/run_pr_pipeline_live.py <pr_url>` prints terminal JSON

### A4. Frontend intake (minimal)
**Change `App.tsx`**
- Default UI: PR URL input + Submit
- Demo chips: Hero 1 / Hero 3 / (optional Hero 4)
- Remove hardcoded absolute Hero auto-start as the only path (keep as chip)

**Done when**
- Judge can paste URL or click demo without editing source

**Phase A exit demo**  
Paste PR → progress lines → either degrade (likely, until Phase B) or hero chip still works.

---

## Phase B — Generative harness (the win wedge)

This is the highest-leverage engineering. Protect calendar for it.

### B1. Stub Library v1
**Build** `domain/stubs/`
- `clock.py`, `random.py`, `http.py`, `db.py`, `fs.py`
- Each exports: install strategy + default uncertainty spec
- Central `stub_plan(ledger) -> StubPlan`

**Rules**
- native / IdP markers → `unharnessable` with named dep (keep current behavior)
- All stubs must be pair-symmetric under Symmetrist canonicalize

**Done when**
- Unit tests: stub plan for hero1/2/3 ledgers matches expectations

### B2. Harness IR (intermediate representation)
Before emitting Python source, emit structured IR:

```text
HarnessIR {
  entry, imports, stubs[], driver, knob_bindings[], extractors[], seed_policy
}
```

**Why:** LLM proposes IR (JSON schema), deterministic renderer emits source.  
Easier to Symmetrist-diff and safer than freeform code gen.

**Done when**
- Pydantic schema + validator
- Renderer produces runnable harness for Hero 1 IR without LLM

### B3. Registry becomes fast-path
**Change** `harness_engineer.py` / `entry_point_registry.py`
- If template matches → use it
- Else → `generate_harness_ir` + render
- Remove hard `NoHarnessTemplateRegistered` as terminal for all cases; only terminal after generative attempts exhausted

**Done when**
- Unknown function with plain-data args can produce a harness pair candidate

### B4. LLM harness proposer
**Build**
- Prompt: scoped source (base+head), ledger, knobs, Stub Library catalog, HarnessIR schema
- Constrained decoding / JSON schema
- One repair pass using Verifier divergence report

**Safety**
- Sandbox-execute only; never `eval` on host
- AST allowlist optional: reject imports outside stub + target module

**Done when**
- At least one non-hero synthetic fixture (new file under `fixtures/wild_synth/`) verifies end-to-end

### B5. Reference strategy upgrade
**Change** API `_executable_reference_path` + Verifier
- Prefer direct reference program generated alongside harness (same inputs)
- `tests/` directory becomes optional boost, not sole gate
- No reference → degrade reason preserved

**Done when**
- PR without `tests/` but with plain callable can still verify via direct reference

### B6. Regression
- Heroes 1–3 live or recorded still pass
- New unit tests for IR renderer + stub plan
- Orchestrator loop A still max 3

**Phase B exit demo**  
Synthetic unknown function (not in registry) → verified microworld.  
Then retry a small public pure-Python PR.

---

## Phase C — Product UI for strangers

### C1. PR-first shell
- Landing copy: one sentence thesis of Lever + paste box
- Progress list (existing)
- Confidence badge + receipt (existing API hooks)
- Error / degrade panel prominent

### C2. Search fog as MVP (promote v2 stretch)
- Stream `search_trace` events (already in API)
- Always show during Adversary for verified path
- Click → jump position (already)

**Done when**
- Demo visibly “computes” before the toy mounts

### C3. Session ledger + permalink
- `GET /sessions` list from SQLite
- Route `/m/:changeId` loads persisted terminal payload
- Share button copies absolute URL

### C4. Pin-as-test
- Keep existing pin; ensure works for PR checkouts (write under workspace `pinned_tests/` or user-specified)

**Phase C exit demo**  
Paste PR → fog fills → toy mounts → share link reopen.

---

## Phase D — Game-like worlds (honest delight)

### D1. WorldSpec plumbing
- Extend synthesizer output with `worldSpec` / `stage` / `affordances`
- Delta Analyst (or World Director) selects `WorldGenre` under enabled registry
- Fallback `numeric-response` always available

### D2. Arena renderer (throughput / retry) — **priority visual**
**Build** `frontend/src/components/ArenaStage.tsx`
- Particle requests; shared arrival seed; old/new gates
- Bind counts to real observations each position
- Surprisemarker + numeric divergence caption (Rendering Fidelity)

**Done when**
- Hero 1 and Hero 2 feel like games, not only bar/line charts
- Chart can remain as secondary “evidence” view toggle

### D3. Matrix + Path polish
- Permission grid already exists — full-bleed, keyboard accessible
- UnionTree: walk animation optional; fork ring clear

### D4. Boss fight UI
- ObjectiveSelector already present — wire copy + empty states
- Only celebrate on empirical unsafe hit

**Phase D exit demo**  
Hero 1 Arena + one wild verified PR Arena in the same session.

**D-lite (if time-crunched)**  
Keep HonestChart but add particle burst on divergence + stronger surprise marker; defer full Arena.

---

## Phase E — Honesty, corpus, deploy (judge-proofing)

### E1. Degradation+
Extend degrade payload + `DegradationPanel`:
- manual test recipe (1–3 inputs)
- optional unverified static notes clearly labeled
- still no toy

### E2. Wild Three
Document in `docs/WILD_CORPUS.md` (create when selected):
| ID | PR / mirror | Expected outcome |
|---|---|---|
| W1 | … | verified high/medium |
| W2 | … | medium / retry loop visible |
| W3 | … | degrade+ showcase |

Add script `scripts/run_wild_corpus.py` that prints a hit-rate table.

### E3. README for judges
- What Lever is (1 paragraph)
- How to run (<10 lines)
- What works / what refuses
- Live hit-rate number
- Link to `SPEC.md` + `SPEC_V3.md`

### E4. Deploy
Pick one:
- Railway / Fly / Render API + static frontend, **or**
- `./scripts/demo_up.sh` that starts API+Vite and opens browser

**Requirements**
- Env: `OPENAI_API_KEY`, `E2B_API_KEY`, optional `GITHUB_TOKEN`
- CORS locked to demo origin
- Healthcheck `GET /health`

### E5. Demo script (rehearse)
**90-second path**
1. Hero chip Arena (surefire wow)
2. Paste Wild W1 PR (generality)
3. Drag to surprise / click fog point
4. Show receipt
5. Paste W3 → degrade+ (trust)

**Phase E exit**  
Another person can run the demo from README cold.

---

## Phase F — Stretch (only if A–E green)

| Item | Note |
|---|---|
| Prospective on PR file | Already partially built |
| Composed 2×2 | Fix mechanical AB combine + per-pair Symmetrist first |
| State-workflow genre | Needs real harnessable fixture |
| Multi-scope cards UX | If Scout clusters work |
| Private repo GitHub App | Only if judges need it |

> **Phase G (planned, not implemented):** toward "most real-world PRs" —
> import-closure sandboxing, repo dependency install, ephemeral seeded backends,
> framework test-client harnesses, type-driven inputs. See
> [`BUILD_PLAN_PHASE_G.md`](BUILD_PLAN_PHASE_G.md).

---

## Workstream ownership (if splitting)

| Owner focus | Phases |
|---|---|
| Backend / agents | A2–A3, B, E1 |
| Infra / deploy | A1, E4, health/secrets |
| Frontend | A4, C, D |
| Demo / corpus / README | E2, E3, E5 |

If solo: sequence **A1→A2→B1→B2→B3→A4→B4→C2→D2/D-lite→E**.

---

## File-level change map (expected)

### New
- `docs/SPEC_V3.md` ✅
- `docs/BUILD_PLAN_V3.md` ✅
- `docs/WILD_CORPUS.md` (Phase E)
- `domain/stubs/*`
- `domain/harness_ir.py`
- `domain/world_director.py` (or synthesizer extension)
- `infra/github/*`
- `infra/checkout/*`
- `frontend/src/components/ArenaStage.tsx`
- `frontend/src/components/PrIntake.tsx`
- `scripts/run_pr_pipeline_live.py`
- `scripts/run_wild_corpus.py`
- `scripts/demo_up.sh`

### Major edits
- `domain/harness_engineer.py` — generative path
- `domain/entry_point_registry.py` — fast-path only
- `domain/orchestrator.py` — checkout handle + budgets
- `domain/delta_analyst.py` — genre field
- `domain/fidelity_verifier.py` — direct reference default
- `interface/api.py` — `/prs`, `/health`, `/sessions`, reference gate relax
- `frontend/src/App.tsx` — PR-first shell
- `AGENTS.md` / root README — v3 instructions

### Do not destabilize
- `domain/symmetrist.py`
- Assayer math / confidence bands
- Rendering Fidelity rules in charts
- Graceful degradation “no toy” invariant

---

## Test plan (per phase)

| Phase | Must pass |
|---|---|
| A | Mock PR resolve tests; checkout temp dir tests; heroes via local paths |
| B | IR renderer hero1; synthetic unknown entry verifies with FakeSandbox; heroes regression |
| C | Vitest: intake form, fog click, permalink load fixture |
| D | Arena binds to observation numbers; fidelity zero-anchor still tested |
| E | Degradation+ panel tests; wild corpus script exits 0 on fixtures |

CI default: `pytest -m "not integration"` + `npm test`.  
Live: marked `integration`, run manually before demo.

---

## Risk register

| Risk | Mitigation |
|---|---|
| LLM harness gen is flaky | IR schema + repair loop + registry fast-path for demos |
| e2b latency blows 90s | Stream progress early; warm sandbox; cut Assayer N in demo profile |
| Arbitrary PRs mostly degrade | Wild Three includes a proud degrade; measure & show hit rate |
| Scope creep into multi-language | Explicit non-goal; Python only |
| Generative code escapes sandbox | Execute only in e2b; no host exec of model code |
| Judges only see heroes | Demo script forces a wild PR second |

---

## Daily checklist (copy into notes)

- [ ] Heroes 1–3 still green on unit path
- [ ] One new generality proof (unknown shape or real PR)
- [ ] Demo script rehearsed once
- [ ] README commands still accurate
- [ ] No verified UI path without fidelity verdict

---

## Definition of “strong win candidate”

You can walk on stage and say:

1. **Claim:** We don’t summarize PRs — we run them and prove the toy.  
2. **Proof live:** Paste a PR you didn’t hand-tune → harness construction loop visible → playable Arena/Matrix **or** precise refusal.  
3. **Depth:** Symmetrist + differential + Assayer still on.  
4. **Taste:** Search fog + game stage + pin/receipt.  
5. **Honesty:** Hit rate published; Degradation+ is part of the demo.

If those five land, Lever is no longer “hardcoded heroes with a fancy pipeline.”  
It is the agentic, verified PR microworld product the v2 SPEC was aiming at.

---

## Immediate next action (start here)

1. Implement **A1+A2** (PR resolve + dual checkout) behind `/prs`.  
2. Implement **B1+B2+B3** (stub library + Harness IR + registry fast-path).  
3. Only then invest in Arena visuals.

That order maximizes chance of winning: **generality + trust first, game feel second.**
