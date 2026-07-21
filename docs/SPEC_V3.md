# LEVER v3 — Win Spec
### OpenAI Hackathon · Developer Tools · v3.0 (product-ready ambition)

> **Core claim (unchanged, non-negotiable):**  
> Lever executes the *real changed code* in a sandbox and differential-tests the microworld against that code.  
> Agents may *propose* harnesses, knobs, and visuals. Only measured agreement may *authorize* a toy.  
> Any feature that weakens this claim is a bug, not a tradeoff.

> **v3 one-liner:**  
> Paste any GitHub PR → multi-agent construction builds a verified behavioral game in the browser → if it cannot prove fidelity, it refuses honestly and still leaves you something useful.

This document **extends** `SPEC.md` (v2.0). v2 remains the trust bible (Symmetrist, Assayer, Rendering Fidelity, graceful degradation). v3 changes *intake, generality, agency, and interaction* so Lever stops being a four-hero demo and becomes a deployable product judges can use on a live PR.

---

## §0 — Why v3 exists

### 0.1 What v2 already won intellectually

- Six-role pipeline with opposed Builder/Critic incentives
- Measured confidence, not model self-report
- Domain packs + Interaction Spec as mechanical rendering contract
- Honest degradation when unverifiable
- Hero diffs that prove the grammar works

### 0.2 What v2 loses as a product / hackathon demo

| Gap | Why it kills the live demo |
|---|---|
| Hardcoded `ENTRY_POINT_REGISTRY` (4 shapes) | Random PRs degrade immediately |
| No GitHub PR intake / dual checkout | Cannot show “paste a PR” |
| Frontend locked to Hero 1 absolute paths | Looks like a fixture player |
| Packs are visual, not “worlds” | Interaction feels like charts, not games |
| Generality unmeasured | Judges ask “does this work on *my* PR?” |

### 0.3 v3 product thesis

**Lever is the first PR review surface where understanding is a motor act *and* a verified claim.**

Competitors sell summaries. Lever sells a **playable differential**.  
v3 makes that differential **generatable for arbitrary Python PRs**, not only curated heroes.

### 0.4 Hackathon scoring strategy

| Judge axis | How v3 scores |
|---|---|
| **Novelty** | Verified microworlds from live PRs; agentic harness construction with a critic loop |
| **Technical depth** | Symmetrist + differential test + Assayer preserved; generative harness adds real difficulty |
| **Demo impact** | 90-second path: paste PR → search cloud fills → game mounts at surprise → drag → pin test |
| **Honesty / craft** | Visible refusals, confidence badges, receipt download — trust as UX |
| **Completeness** | Deployable web app, not a notebook |

**Win condition for the room:** a judge pastes a public Python PR (or one of three prepared “wild” PRs), gets either a playable verified world **or** a specific, impressive refusal with a manual test recipe — never a silent fake.

---

## §1 — Locked invariants (carry forward from v2)

These do not move:

1. **Harness A/B differ only by import root** (Symmetrist).
2. **No verified badge without differential agreement ≥ threshold.**
3. **Confidence = agreement × stability × coverage** (Assayer).
4. **Zero-anchored axes; divergence shown as a number; no auto-zoom drama** (Rendering Fidelity).
5. **Always-on divergence view:** same `KnobPosition` drives old and new.
6. **Preset labels describe measurements, never worldly fiction.**
7. **No toy on low confidence / unharnessable / no reference.**
8. **Deterministic components never call an LLM** (Triager, Scout static core, Symmetrist, Assayer math, Synthesizer template switch).

---

## §2 — v3 architecture overview

### 2.1 Roster (8 agents + 4 guardrails)

v2’s six remain. v3 adds two *intake/world* agents and upgrades Harness Engineer from registry lookup to generative construction.

| # | Agent | Role | LLM? |
|---|---|---|---|
| 0 | **Intake** | Resolve PR/ref/files → dual checkout + change manifest | No (API + git) |
| 1 | **Scout** | Entry points, reach set (depth ≤ 2), dependency ledger | No |
| 2 | **Delta Analyst** | Thesis, knobs, observables, **world genre** | Yes |
| 3 | **Harness Engineer** | **Generate** stubs + driver + `run(config,seed)` for *this* shape | Yes (code gen) + templates |
| 4 | **Fidelity Verifier** | Symmetrist → differential test → Assayer | No |
| 5 | **Adversary** | Max divergence / path divergence / unsafe reach | No |
| 6 | **World Director** | Choose interaction grammar + game affordances from genre + cache | Mostly mechanical; small LLM for captions |
| 7 | **Synthesizer** | Mount browser microworld from completed `InteractionSpec` + `WorldSpec` | No (switch/templates) |

**Guardrails (unchanged category):** Triager, Symmetrist, Assayer, Rendering Fidelity.  
**New soft guardrail:** **Construction Budget** — max wall-clock / sandbox runs / LLM calls per PR so demos never hang.

> **Why World Director is not a seventh “creative viz agent”:**  
> It writes structured `WorldSpec` fields under arity contracts. Synthesizer stays a switch. Creativity without schema is how microworlds become inconsistent and untrustworthy.

### 2.2 End-to-end flow (user-visible)

```
Paste PR URL
  → “Reading PR #412 — 9 files”
  → Triager (skip noise or Run anyway)
  → Scout scopes behavior(s); user picks if multi-scope
  → Delta drafts thesis + knobs + genre
  → Harness Agent proposes harness; Critic (Verifier) attacks it (≤3 loops)
  → Adversary search cloud paints live in the browser
  → Microworld mounts already at the surprise
  → User plays → Pin as test / Share permalink / Show receipt
```

Failure anywhere in verification → **Graceful Degradation+** (§7): explanation + sampled disagreements + **manual test recipe**, still no fake toy.

### 2.3 The Interaction Spec (v2) + World Spec (v3)

Keep `InteractionSpec` from v2 as the trust document.

Add:

```typescript
type WorldSpec = {
  genre: WorldGenre;
  stage: StageConfig;          // arena, matrix, tree, curve, workflow…
  affordances: Affordance[];   // particles, scrubber, fog-of-war, boss-fight…
  narrationLine: string;       // measured caption only
  playHints: string[];         // ≤3, from Adversary presets
};

type WorldGenre =
  | "throughput"       // requests / admits / congestion
  | "access-matrix"    // permission / policy
  | "decision-path"    // branch / feature-flag
  | "retry-storm"      // backoff / herd
  | "state-workflow"   // explicit state machine
  | "numeric-response" // fallback scalar curve
  | "queue-backlog"    // stretch
  | "cache-efficiency" // stretch
  | "custom";          // last resort → numeric-response renderer
```

**Genre → pack mapping (mechanical):**

| Genre | Primary pack / renderer |
|---|---|
| throughput | rate-limiter + **Arena overlay** |
| retry-storm | rate-limiter + **Spike theater** |
| access-matrix | permission matrix |
| decision-path | decision-tree union |
| state-workflow | state-machine |
| numeric-response / custom | numeric-fn |

---

## §3 — Generality: kill the hardcoded gate

### 3.1 Problem statement

v2 `ENTRY_POINT_REGISTRY` is a **hard gate**: unknown `EntryPoint.fn` → degrade.  
That is correct for a Phase-0 fidelity spike. It is fatal for “any PR.”

### 3.2 v3 rule

> **Registry is an accelerator, never a gate.**  
> If a registered template matches Scout’s entry point and Delta’s shape, use it (fast, high confidence).  
> Otherwise, **Harness Engineer generates** a harness from the stub library + entry signature + knob bindings.

### 3.3 Generative Harness Engineer contract

**Input:** `ScopedChangeSet`, `PartialInteractionSpec`, dual checkout paths.  
**Output:** `HarnessPair` identical in form to v2 (byte-symmetric except import root) + `uncertaintySpecs`.

**Generation procedure:**

1. Classify each ledger dep → stub from **Stub Library** (§3.4).
2. Emit driver for every `binding.kind === "driver"`.
3. Emit argument/config wiring for knobs.
4. Emit `run(config, seed) → ObservationBundle` with extractors.
5. If `decision-path` / `pathTrace`: apply branch instrumentation source transform to checkout + reference (v2 C-5).
6. Hand to Verifier. On failure, receive divergence report → revise (≤3).

**Allowed LLM use:** propose stub choices, driver loop structure, extractor paths.  
**Forbidden LLM use:** invent observable values; skip Symmetrist; claim verification.

### 3.4 Stub Library (versioned, measurable)

Ship a growing library — not one-off hero stubs:

| Kind | Default stub | Uncertainty |
|---|---|---|
| clock | simulated monotonic clock | tick granularity discrete |
| random | seeded RNG | seed already pair-symmetric |
| network/http | canned status/latency | log-uniform latency |
| db | in-memory dict / fixed rows | latency + miss rate |
| io/fs | temp sandbox FS | — |
| native | **refuse** unless allowlisted | — |
| live IdP / oauth | **refuse** | — |

Every stub emits `{default, distribution}` for the Assayer.

### 3.5 Executable reference for arbitrary repos

v2 required a nearby `tests/` folder at the API edge. v3 widens:

**Reference strategies (first success wins):**

1. **Direct reference program** — call the same entry with the same knob-derived inputs (preferred; heroes already do this).
2. **Discovered tests** — pytest node ids that import the entry (optional boost).
3. **Harness-as-reference fallback** — *forbidden for verification*. If only the harness can run, verdict = degraded.

If none → degrade: *“no executable reference — nothing to check against.”*

### 3.6 Language scope for hackathon v3

**MVP win scope: Python.**  
Declare multi-language as post-hackathon. Depth in one language beats shallow pretence in five.

**Honest coverage claim for README / judges:**

> Lever v3 targets behavioral Python PRs with a plain-data callable core.  
> We measure hit rate on a public corpus. We refuse when we cannot verify.

---

## §4 — Intake: real PRs

### 4.1 Supported intakes (priority order)

| Intake | Behavior |
|---|---|
| **GitHub PR URL** | Resolve base/head SHAs; clone/sparse-checkout changed paths + imports; dual trees |
| **GitHub compare / SHAs** | Same as PR without PR metadata |
| **Local base/head file or directory pair** | Dev / offline / demos |
| **Raw diff** | Always degrade+manual recipe (explain why) |
| **Hero chips** | Curated demos only — not the default path |

### 4.2 Dual checkout

Materialize `/w/base` and `/w/head` in the sandbox (or host worktrees synced into sandbox).  
All execution reads from these trees. No “simulate against pasted snippet alone” for verified mode.

### 4.3 Auth for deploy

- Public repos: unauthenticated git clone or GitHub API  
- Private repos: GitHub App installation token  
- Frontend never sees provider secrets

### 4.4 Change scoping (keep v2)

If Delta/Scout finds >1 independent behavioral cluster → cards: *“Which behavior do you want to feel?”*

---

## §5 — More agentic, without becoming theater

### 5.1 What “agentic” means in Lever

Not six chatbots debating.  
**Tool-using roles with opposed objectives and shared evidence.**

### 5.2 Tool surface (domain ports)

| Tool | Who uses it |
|---|---|
| `resolve_pr(url)` | Intake |
| `checkout(base, head)` | Intake |
| `parse_and_scope(trees)` | Scout / Triager |
| `propose_spec(scope)` | Delta |
| `propose_harness(scope, spec)` | Harness Engineer |
| `symmetrist_check(pair)` | Verifier |
| `run_differential(pair, K)` | Verifier |
| `assay(pair, N)` | Verifier |
| `search_divergence(pair, objective)` | Adversary |
| `emit_world(spec, cache)` | World Director / Synthesizer |
| `pin_test(position)` | API |
| `receipt(harness_uri)` | API |

### 5.3 Construction loop (the demo of agency)

Visible in UI as a short evidence stream (not anthropomorphic debate):

```
Harness attempt 1 — stubbed clock+db
Symmetrist PASS
Differential 97/128 — fail on boundary rps=1
Harness attempt 2 — widen stubs; seed random
Differential 128/128 PASS
Assayer confidence 0.91 (high)
Adversary exploring…
```

Judges see **compute and critique**, not vibes.

### 5.4 Construction Budget (new)

Per PR defaults (tunable):

- ≤ 3 harness revisions  
- ≤ 1 Delta kickback for dead knobs  
- ≤ 128 Adversary evals  
- ≤ 12 Assayer replicates  
- soft wall clock ≤ 90s for demo path (stream partials early)

On budget exhaustion → degrade with partial evidence, not a hung spinner.

---

## §6 — Game-like interaction (still honest)

### 6.1 Design law

Every pixel of motion is downstream of a real `ObservationBundle` (or a cached one from Adversary search).  
Animation is **illustration of measurement**, never a substitute for it.

### 6.2 Microworld modes (ship for win demo)

#### A. Arena (throughput / retry)
- Requests as particles enter a gate
- Old vs new gates side-by-side, **same arrival process**
- Admits glow; rejects fade
- Surprisemarker pulses the critical RPS/tenant region
- Optional scrubber: replay one simulated second

#### B. Matrix (access)
- Full-bleed permission grid (axes = enum knobs)
- Cells split-diagonal A/B; flipped cells outlined
- Toggle secondary knobs (e.g. sameTenant)
- Click cell = set position (already v2)

#### C. Path theater (decision-tree)
- One union tree; fork ringed; unreached dimmed
- Leaf click → cached forward lookup
- Optional “walk” animation along old vs new path under shared inputs

#### D. Search fog (all genres)
- During Adversary: knob-space point cloud (v2 stretch → **MVP in v3**)
- Color by divergence; click jumps
- This is the “game map” of the change

#### E. Boss fight (security objective)
- User declares unsafe predicate
- Adversary searches boundary-weighted inputs
- Win toast only if unsafe state **actually observed**

### 6.3 Rejected forever (still)

- Two-cursor different positions  
- Auto y-axis drama  
- Inverse SMT “find input for this pixel” as primary UX  
- Voice-first replacing knobs  
- Worldly preset names (“Black Friday”)

### 6.4 Browser UX shell (deployable)

- Landing: paste PR + “Try a demo PR” chips  
- Live run view: progress → search fog → microworld  
- Side panel: knobs, presets, confidence, receipt, pin  
- Session ledger: prior `changeId`s  
- Permalink `/m/:changeId`  
- Mobile: readable degradation + thesis; play primary on desktop

---

## §7 — Graceful Degradation+

When verification fails, v3 still delivers value:

1. Specific `degradeReason` (named dep / attempt count / failure mode)  
2. `[Show me →]` divergence samples  
3. Plain explanation from thesis  
4. **Manual test recipe** — 1–3 concrete inputs Delta/Adversary would have tried  
5. Optional **path sketch** from static diff (labeled *unverified*)  
6. **Never** a verified toy

This is a feature. Competitors die by fabricating the 5%.

---

## §8 — Hero corpus + wild corpus

### 8.1 Keep heroes 1–4

They remain regression fixtures and demo chips. Registry templates may remain as fast-paths for them.

### 8.2 Add “Wild Three” (hackathon must-ship)

Three public Python PRs (or prepared mirrors) chosen for:

1. Mostly-pure core → likely verified arena/matrix  
2. Stub-heavy but harnessable → medium band with error bands  
3. Unharnessable / no reference → showcase Degradation+

Judges see the full honesty spectrum in <3 minutes.

### 8.3 Hit-rate dashboard (internal)

Track on every run: verified high / medium / inert / unscopable / unharnessable / unverifiable.  
Publish the number in README. Credibility > bluff.

---

## §9 — Explicit non-goals (hackathon)

Do not build during the win push:

- Full multi-language parity  
- Production incident diagnosis pivot  
- Mid-session freeform NL harness edits without re-verify  
- Blast-radius beyond Scout depth 2  
- Auto-merge / CI gating as primary surface  
- Composed 2×2 microworlds unless Tier A–C are solid (nice stretch only)

---

## §10 — Success criteria (definition of done for v3 win build)

### Must (demo-blocking)

- [ ] Paste public GitHub PR URL → dual checkout → pipeline runs  
- [ ] Unknown entry shapes can generate harnesses (registry not required)  
- [ ] Verifier still gates the toy  
- [ ] Search fog streams live  
- [ ] At least two game genres feel distinct (Arena + Matrix or Arena + Path)  
- [ ] Degradation+ never shows a fake verified badge  
- [ ] Heroes 1–3 still pass as regression  
- [ ] Deployed URL works for judges (or reliable localhost script <2 min)

### Should

- [ ] Permalink + session ledger  
- [ ] Pin-as-test  
- [ ] Boss-fight objective UI  
- [ ] Wild Three corpus documented  

### Nice

- [ ] Prospective mode on arbitrary base file from a PR checkout  
- [ ] Composed microworlds  

---

## §11 — Relationship to SPEC.md v2

| Topic | Authority |
|---|---|
| Symmetrist, Assayer, tolerances, confidence formula | **v2 SPEC.md** |
| Pack arity contracts, InteractionSpec fields | **v2**, extended by WorldSpec here |
| Agent retry loops A/B | **v2**, harness generation upgraded here |
| PR intake, stub library, World Director, Arena UX | **v3 (this doc)** |
| Build sequencing | **`BUILD_PLAN_V3.md`** |

If v2 and v3 conflict on trust: **v2 wins.**  
If v2 and v3 conflict on generality/UX: **v3 wins.**

---

## §12 — The sentence to remember

**v3 does not make Lever more magical by inventing behavior.**  
**It makes Lever more agentic by inventing *how to run and prove* behavior — for PRs nobody hand-wrote a template for — and more delightful by turning those proofs into games you can play.**
