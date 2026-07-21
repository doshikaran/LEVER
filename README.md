# LEVER

### Don't read the diff. Play it.

> **Category:** Education · Developer Tools
> **Built with:** OpenAI Codex + GPT‑5.6 · E2B sandboxes · FastAPI · React
> **One line:** Paste a GitHub PR → an 8‑agent pipeline checks out both versions, executes the *real changed code* in a sandbox, differential‑tests old vs. new, and hands you a playable game of the behavioral change - or refuses honestly when it cannot prove the toy.

It's 4:47pm. An agent hands you back a 640-line diff. You read every line. You understand the syntax. You have no idea what the system will do at 3am on Black Friday when one tenant hammers it at 400 requests a second because reading code and knowing its behavior are two different skills, and only one of them scales to how fast agents write code now.

**LEVER is the second skill, automated**. Paste a GitHub PR. An eight-agent pipeline checks out both versions, builds a byte-symmetric harness for each, and executes the real changed code - not a summary of it - inside an isolated sandbox. It differential-tests old against new across 128 sampled inputs, measures its own confidence from three independent quantities, and only then hands you a playable microworld: drag a knob, watch old and new diverge, live. If it can't prove the harness is faithful, it says so - specifically, with a reason and shows you nothing rather than something fake.

Every other tool in this space sells you a paragraph an LLM wrote about your diff. LEVER sells you a differential you can verify, because it ran.

![LEVER - a verified, playable microworld generated from a GitHub PR](docs/images/gallery/shot-02.png)

---

## Built with Codex

LEVER was built during OpenAI Build Week with **OpenAI Codex and GPT‑5.6** as active engineering collaborators throughout - not autocomplete, and not a single prompt that produced a finished product. The build ran as a strict, spec‑first process: each phase had to prove one specific fact was genuinely real, verified against live infrastructure, before the next phase was allowed to build on top of it. Codex worked inside that discipline for the entire build, across every phase.

### How Codex was used, concretely

**Scaffolding the eight‑agent pipeline against a locked schema.** Codex generated the initial implementations of all eight agents - Intake, Scout, Delta Analyst, Harness Engineer, Fidelity Verifier, Adversary, World Director, and Synthesizer - each one built against a schema we'd already locked before any code existed, so every agent's inputs and outputs were fixed contracts, not something negotiated after the fact.

**Catching real design defects, not just implementing what was asked.** Across the build, Codex found and fixed several problems that were genuine gaps in our own design, not simple bugs:

- A **confidence formula** whose normalization constant made it mathematically impossible to ever reach a "verified" result, even with perfect underlying data - found by actually running the numbers against a real case, not by re‑reading the formula, then fixed and reproven against that same case live.
- A **sandbox connection layer** that could silently hang forever after several real, repeated executions, with no error at all - diagnosed under genuine live load (not a unit test), then hardened with a clean connection lifecycle and an explicit timeout so failures are now always loud.
- A piece of **trust‑critical logic hardcoded to a single function shape** from our first reference case - when a second, differently‑shaped piece of code hit the same logic, it failed outright instead of degrading gracefully. Codex pulled the logic into a proper registry with per‑shape contracts, and proved the refactor changed nothing observable by checking the original case byte‑for‑byte before and after.
- A **byte‑identity safety check** that was silently using one shared allowance across every comparison instead of a distinct one per case - meaning it could never actually catch a real mismatch. Found in review, fixed with per‑comparison justification, and proven with a new test built specifically to exercise the exact failure it had been blind to.

**The generative Harness IR.** For code shapes the registry doesn't recognize, Codex helped design an intermediate representation (`domain/harness_ir.py`) and its deterministic renderer, including the routing logic that decides how categorical versus numeric inputs get bound - iterated specifically so generated harnesses stay schema‑validated and checkable, rather than free‑form code we'd have to trust blindly.

**Frontend microworlds.** The Arena, permission matrix, decision‑tree path walk, workflow stage, timeline scrubber, and later features - trading cards, the "Break the PR" challenge mode, receipt comparisons - were built with Codex end to end.

**Tests and hardening.** The full pytest and Vitest suites, every graceful‑degradation error path, and the regression tests built specifically around each defect above were co‑written with Codex - including tests deliberately constructed to fail on the exact bug being fixed, so the fix could be proven, not assumed.

### Where we made the key product and engineering decisions

- **The trust invariant.** Never render a playable result without a passing differential test against the real code, and refuse honestly otherwise. Every other decision below exists to defend this one.
- **Deterministic guardrails never call a model.** The Triager, Scout's static analysis, the byte‑identity check, the statistical confidence math, and the Synthesizer's rendering switch are pure functions, on purpose, because a trust guarantee can't depend on a model's mood.
- **Rendering Fidelity and the no‑fake refusal.** The decision that a silently rescaled chart axis is the same category of lie as an asymmetric test harness - and that an honest refusal is worth more than a confident‑looking fake.


**Codex Session IDs** - the threads where the majority of core functionality was built:

- `019f8090-a510-7e03-a4af-ea01089baa30`
- `019f7bb2-17b7-76f2-a7ed-2c50b090899c`

**Demo video:** [youtube.com/watch?v=BRrqj8Npm6Y](https://www.youtube.com/watch?v=BRrqj8Npm6Y)

---

## Table of contents

- [Built with Codex](#built-with-codex)

1. [The problem](#1--the-problem)
2. [The solution](#2--the-solution)
3. [Why two tracks: Education + Developer Tools ](#3--why-two-tracks-developer-tools--education)
4. [Quick start (judges: test without rebuilding)](#4--quick-start)
5. [Architecture diagram](#5--architecture-diagram)
6. [How it works - end to end](#6--how-it-works--end-to-end)
7. [The agents (v2 six → v3 eight)](#7--the-agents-v2-six--v3-eight)
8. [The guardrails](#8--the-guardrails-the-trust-layer)
9. [Feature inventory (v2 → v3 → v3.1 interaction)](#9--feature-inventory)
10. [Domain packs & world genres](#10--domain-packs--world-genres)
11. [The hero corpus & the wild corpus](#11--the-hero-corpus--the-wild-corpus)
12. [Measured results](#12--measured-results)
13. [Tech stack](#13--tech-stack-complete)
14. [Installation & configuration](#14--installation--configuration)
15. [Known limitations](#15--known-limitations-stated-on-purpose)
16. [Screenshots](#16--screenshots)
17. [License](#17--license)

---

## 1 · The problem

Reviewing a pull request today means **reading two versions of code and simulating the difference in your head.** That mental simulation is exactly where bugs slip through:

- A rate limiter changes from a fixed window to a sliding window - *does it now admit 20× more traffic at high tenant counts?* You can't see it in the diff.
- A permission check moves from roles to attribute inheritance - *can a contractor now read the audit log across tenants?* One flipped boolean, invisible in text.
- A feature flag wraps existing pricing logic - *does the discount code silently never run for your beta cohort?* The diff looks fine.

Two tools try to help and both fall short:

- **AI PR summarizers** *describe* the change in prose. But a description is a claim with no evidence - and LLMs confidently narrate behavior that the code does not actually have.
- **Test suites** tell you *pass/fail* on the cases someone already thought of. They don't let you *feel* how behavior changes across the whole input space, and they say nothing about inputs no test covers.

The gap: **there is no tool that lets a reviewer interactively see, and trust, how a change alters real runtime behavior.**

## 2 · The solution

LEVER closes that gap with one hard commitment:

> **It executes the real changed code in a sandbox and differential‑tests the microworld against that code. Only measured agreement may authorize a playable toy. If it cannot prove fidelity, it refuses - and still leaves you something useful.**

Concretely, for a PR LEVER will:

1. **Check out both versions** (base and head) into isolated worktrees.
2. **Build a symmetric harness** - two runnable programs identical *byte‑for‑byte* except for which version of the code they import.
3. **Differential‑test** them against the real code across 128 low‑discrepancy sampled inputs.
4. **Measure confidence** from three independent quantities (agreement × stability × coverage) - never self‑reported by a model.
5. **Search** the input space for the point of maximum divergence - the "surprise."
6. **Render a game** (an arena of request particles, a permission matrix, a decision tree, a state workflow…) that opens *already showing the surprise*, and lets you drag knobs to watch old vs. new update live.
7. **Refuse honestly** if any step can't be verified - with a specific reason and a manual test recipe, never a fake.

The result is a **playable differential**: a small interactive world where the motion you see is downstream of a real, verified execution.

## 3 · Why two tracks: Developer Tools + Education

**Developer Tools** - LEVER is a PR‑review and behavioral‑diff tool for engineers: paste a PR, get a verified interactive model of what changed, pin a divergence as a regression test, share a permalink to a live microworld. It targets code review, regression discovery, and "behavioral merge conflict" detection between two PRs.

**Education** - the same engine is a powerful learning surface. Abstract CS concepts - rate limiting, exponential backoff with jitter, access‑control inheritance, finite‑state machines, feature‑flag branch logic - become **interactive, verified simulations** a student can *play with* rather than read about. Because every animation is provably tied to real executed code (not a hand‑waved teaching applet), learners build correct intuition. Instructors can turn any small code change into a "what does this actually do?" microworld, and the "Break the PR" mode gamifies finding where two implementations disagree. LEVER teaches the single most important review skill - *how a change to code changes behavior* - by making it a game.

## 4 · Quick start

> Judges can test LEVER without rebuilding it from scratch. Fastest path is a curated demo; you can also paste a real PR.

**Prerequisites:** Python 3.12, Node ≥ 20.19, an `OPENAI_API_KEY`, an `E2B_API_KEY` (sandbox execution), and optionally a `GITHUB_TOKEN` (private repos / higher rate limits).

```bash
cd LEVER
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill OPENAI_API_KEY, E2B_API_KEY, (optional) GITHUB_TOKEN

# Backend (do NOT use --reload; it restarts mid-analysis when checkouts appear)
.venv/bin/uvicorn interface.api:app --host 127.0.0.1 --port 8765

# Frontend (separate terminal)
cd frontend && npm install && npm run dev
```

Open the printed UI URL (default `http://127.0.0.1:5173`). Health check: `GET http://127.0.0.1:8765/health`.

**Two ways to try it:**

- **Curated demo (surefire):** click a Hero chip (e.g. *Hero 1 - rate limiter*). You'll get the full Arena microworld.
- **Real PR:** paste a **public GitHub PR whose diff modifies one self‑contained function that takes plain data** (ints/strings/enums - no live `db`/request/session objects). LEVER resolves it, checks out both commits, and renders the verified microworld - or an honest degradation.

> ⚠️ **Demo tip:** run the backend **without `uvicorn --reload`**. With reload on, the file watcher sees the PR checkout land under `data/checkouts/` and restarts the server mid‑run, killing the analysis. To keep reload while developing, scope it: `--reload-dir interface --reload-dir domain --reload-dir infra`.

## 5 · Architecture diagram

The trust pipeline - eight agents, four guardrails, two feedback loops, and the honest‑degradation exit:

```mermaid
flowchart TD
  U([PR URL / ref pair / demo chip]) --> I0

  subgraph S1[Intake]
    direction TB
    I0[Resolve PR to base and head SHAs] --> I1[Dual checkout<br/>base and head worktrees]
  end

  I1 --> G{Triager gate<br/>static ≤150ms<br/>skip formatting / rename / deps?}
  G -- Skip --> N1[Skip notice<br/>run anyway]
  N1 -. force .-> S0
  G -- Proceed --> S0

  subgraph S2[Scouting and spec]
    direction TB
    S0[Scout<br/>entry point · reach set depth ≤2 · dependency ledger] --> D1[Delta Analyst<br/>LLM · thesis · knobs · observables · world genre]
  end

  D1 --> H1[Harness Engineer<br/>LLM + templates<br/>stubs · driver · run config · seed registry]

  subgraph A[Verification loop · max 3 attempts]
    direction TB
    H1 --> V1[Fidelity Verifier]
    V1 --> M{Symmetrist<br/>A/B byte-identical?}
    M -- Fail --> H1
    M -- Pass --> X{Differential test<br/>Sobol K=128 vs real code<br/>agreement ≥ 0.85?}
    X -- Fail --> H1
    X -- Pass --> A1[Assayer<br/>12 replicates · confidence score]
  end

  A1 -- Low band --> GD([Graceful degradation<br/>specific reason · divergence samples · manual test recipe])
  A1 -- Verified --> A2

  subgraph B[Adversary and world build]
    direction TB
    A2[Adversary<br/>128 evals · max divergence · cache every point] --> W1[World Director<br/>genre to stage + affordances]
    W1 --> S3[Synthesizer<br/>switch on pack · enforce rendering fidelity]
    S3 --> W([Playable microworld])
  end

  A2 -- no divergence --> D1
  A2 -- inert twice --> INERT([Behaviorally inert<br/>a finding, not a fake])
  S0 -- unscopable --> GD
  W --> P[Play / inspect<br/>drag knobs · scrub timeline · click diff line<br/>pin-as-test · share permalink · trading card · duel]

  classDef guard fill:#fff7ed,stroke:#d97706,stroke-width:2px,color:#7c2d12;
  classDef nollm fill:#ecfdf5,stroke:#16a34a,stroke-width:2px,color:#14532d;
  classDef llm fill:#eff6ff,stroke:#2563eb,stroke-width:2px,color:#1e3a8a;
  classDef terminal fill:#fdf2f8,stroke:#db2777,stroke-width:2px,color:#831843;
  classDef source fill:#f8fafc,stroke:#64748b,stroke-width:1.5px,color:#0f172a;

  class G,M,X guard;
  class U,I0,I1,S0,V1,A1,A2,W1,S3,P source;
  class D1,H1 llm;
  class GD,INERT terminal;
  class W nollm;

  linkStyle default stroke:#94a3b8,stroke-width:1.5px;

```

**Reading the diagram:**
- **Green** = deterministic, (the trust‑critical parts must be reproducible).
- **Blue** = the only two steps that use an LLM (Delta Analyst proposes the spec; Harness Engineer proposes harness construction).
- **Orange** = the four guardrails that can veto a render.
- **Pink** = terminal honest outcomes (degradation or an "inert" finding) - both are legitimate answers, neither is a fake.
- **Loop A** (Harness Engineer ↔ Verifier) fixes a lying harness, escalating up to 3 attempts. 
- **Loop B** (Adversary → Delta Analyst) re‑picks knobs once if the change looks inert.

## 6 · How it works - end to end

Walking one PR through the pipeline:

1. **Intake** resolves the GitHub PR to `(repoUrl, baseSha, headSha)` and lists changed files (GitHub REST API).
2. **Dual checkout** materializes two worktrees, `/w/base` and `/w/head`, and selects the **primary Python pair** - one shared, modified, non‑test `.py` file that exists on both sides and takes plain data.
3. **Triager Gate** (pure static, tree‑sitter, ≤150ms) drops no‑op diffs (formatting, renames, dependency bumps, type‑only) with a *Run anyway* escape hatch. This is the cheapest, most load‑bearing feature - it stops the tool from "crying wolf."
4. **Scout** (deterministic) parses both trees, builds import + call graphs, computes the reachable set (bounded at depth 2), selects the entry point, and classifies every dependency as `pure | io | clock | random | network | db | native`.
5. **Delta Analyst** (GPT‑5.6, the one irreducibly‑LLM step) writes the **thesis** ("Old: fixed window. New: sliding window with per‑tenant burst"), the **knobs** (the controls you'll drag), the **observables** (what's measured), and the **world genre**.
6. **Harness Engineer** builds two runnable harnesses. A registry template is used as a *fast path* when the shape matches; otherwise it **generates a Harness IR** (an intermediate representation validated by schema, then rendered to source) using the versioned **Stub Library**. The two harnesses differ only by import root.
7. **Fidelity Verifier** runs, in order: the **Symmetrist** (proves the harnesses are byte‑identical except for justified diff‑introduced keys), the **differential test** (128 Sobol points, harness vs. *real* code, agreement rate), and the **Assayer** (12 replicates, perturbing only the stub parameters that had to be guessed, to measure stability). Confidence = `agreement × stability × coverage`.
8. **Adversary** searches for maximum divergence (64 explore + 64 exploit evaluations), caching every point - that cache doubles as the drag‑latency cache and the source for the decision‑tree reconstruction.
9. **World Director** maps the genre to a **stage** (arena, matrix, tree, workflow, curve) and **affordances** (particles, scrubber, fog, boss‑fight), writing structured `WorldSpec` fields.
10. **Synthesizer** mounts the browser microworld as a pure switch over the pack, enforcing Rendering Fidelity (zero‑anchored axes, divergence shown as a number, no auto‑zoom drama).
11. If anything unverifiable happens along the way → **Graceful Degradation+**: a specific reason, the sampled disagreements, and a manual test recipe. No toy.

## 7 · The agents

LEVER started as **six agents** with deliberately opposed incentives. We added **two more** (Intake and World Director) and upgrades the Harness Engineer from registry‑lookup to generative construction - the change that makes "any PR" possible.

| # | Agent |  One‑line role |
|---|---|---|
| 0 | **Intake** | Resolve PR/ref/files → dual checkout + change manifest |
| 1 | **Scout** | Entry point, reach set (depth ≤ 2), dependency ledger |
| 2 | **Delta Analyst** | Thesis, knobs, observables, world genre |
| 3 | **Harness Engineer** | Generate symmetric stubs + driver + `run(config,seed)` |
| 4 | **Fidelity Verifier** | Symmetrist → differential test → Assayer |
| 5 | **Adversary** | Search for maximum divergence; cache every point |
| 6 | **World Director** | Choose interaction grammar + game affordances |
| 7 | **Synthesizer** | Mount the browser microworld from the completed spec |

### 0 · Intake
- **What it does:** parses a GitHub PR URL to `(owner, repo, number)`, calls the GitHub REST API for base/head SHAs and the changed‑file list, then dual‑checks‑out both commits into worktrees and selects the primary Python pair.
- **Why:** without it, LEVER is a fixture player, not a product. This is the "paste a PR" capability.
- **Advantage:** turns LEVER from a four‑hero demo into something a judge can point at *their own* PR.

### 1 · Scout 
- **What it does:** tree‑sitter parse of both trees → import/call graph → reachable set (depth‑2 bounded) → entry‑point selection (outermost changed function callable with plain data) → dependency ledger with each dep classified.
- **Why:** the Harness Engineer needs to know *what to stub*; the Assayer needs the uncertainty of each stub. Both come from Scout.
- **Advantage:** deterministic and fast - on the critical path, so this step is reproducible and cheap. Fails *loudly* (`unscopable`) rather than producing a garbage harness.

### 2 · Delta Analyst 
- **What it does:** reads both source versions + the dependency ledger and drafts the `InteractionSpec`: `thesis`, `domainPack`/genre, `knobs`, `observables`. Constrained decoding to the schema; a validator checks the chosen pack's arity contract, falling back to the always‑satisfiable `numeric-fn` pack on violation.
- **Why:** deciding *what the change is about* and *what to let the user pull on* is a genuine act of understanding - the one place a model is essential.
- **Advantage:** everything downstream is analysis/execution/templating, so the LLM's creativity is contained to a single, schema‑bounded step. If this step is wrong, verification still prevents a *false* toy - it just may be about the wrong thing.

### 3 · Harness Engineer 
- **What it does:** makes both versions runnable in isolation. For known shapes it uses a registry template (fast, high confidence). For unknown shapes it **generates a Harness IR** (`domain/harness_ir.py`) - entry, imports, stubs, driver, knob bindings, extractors, seed policy - validated by a Pydantic schema and rendered to source deterministically. Stubs come from the versioned **Stub Library** (`domain/stubs/`), each emitting an uncertainty spec for the Assayer.
- **Why:** the v2 hardcoded `ENTRY_POINT_REGISTRY` was a *gate* - any unknown function degraded immediately. v3 makes the registry an *accelerator*, not a gate.
- **Advantage:** generality. LEVER can harness plain‑data callables it has never seen. The IR (LLM proposes JSON, deterministic renderer emits code) is safer and easier to Symmetrist‑diff than free‑form code generation, and model code is only ever executed inside the E2B sandbox - never on the host.

### 4 · Fidelity Verifier
- **What it does:** hosts the trust layer - **Symmetrist** (fail‑fast, no execution), then the **differential test** (128 Sobol points against real code), then the **Assayer** (12 replicates for stability). Emits the `FidelityReport` with a measured confidence and band.
- **Why:** this is *the* product. Without it, LEVER is an LLM narrating what it thinks code does.
- **Advantage:** it is deliberately a **separate agent from the Harness Engineer, with the opposite objective** - the Engineer's job is to make code run; the Verifier's only reward is catching the Engineer cheating. Collapsing them would mean asking one prompt to critique itself.

### 5 · Adversary
- **What it does:** searches the knob space for the input of maximum divergence - 64 Sobol "explore" evals + coordinate ascent from the top‑8 for 64 "exploit" evals, 128 total, all cached. Writes `initialPosition`, `surpriseMarker`, and up to 3 measured `presets`.
- **Why:** a toy that opens at a boring default is a sandbox the user must explore themselves (and won't). Opening *at the surprise* converts a sandbox into a bug report.
- **Advantage:** the search cache doubles as the **drag‑latency cache** (why the toy feels instant) and the corpus for the decision‑tree reconstruction - one search, three jobs.

### 6 · World Director
- **What it does:** maps the world genre + cached evaluations to a `WorldSpec` - `stage` (arena/matrix/tree/curve/workflow), `affordances` (particles, scrubber, fog, boss‑fight), and a *measured‑only* narration line.
- **Why:** to make packs feel like **games**, not charts, without letting creativity break trust. It writes structured fields under arity contracts, so the Synthesizer stays a switch statement.
- **Advantage:** delight that never fabricates - every animated pixel is downstream of a real `ObservationBundle`.

### 7 · Synthesizer
- **What it does:** mounts the microworld as a pure switch over the domain pack, generates knob controls per type, builds the chart/stage, and **enforces Rendering Fidelity**. Never fails hard - falls back to `numeric-fn`.
- **Why:** consistency. A mechanical renderer means microworlds look the same across runs, so users build intuition across them.
- **Advantage:** the schema (`InteractionSpec` + `WorldSpec`) is what makes rendering a deterministic act instead of a creative one - the reason this can be a *no‑LLM* step.

## 8 · The guardrails (the trust layer)

Four guardrails and one exit protocol. **These are the product; everything else is the interface to them.**

### Triager Gate *(static, ≤150ms)*
First‑match‑wins static classifier over the two ASTs: formatting‑only → SKIP; rename‑only (alpha‑equivalent) → SKIP; dependency‑manifest‑only → SKIP; type‑annotations‑only → SKIP; zero behavioral edits → SKIP; else PROCEED. Every SKIP renders a one‑line reason plus **Run anyway →**. *Without it, the pipeline spends ~15s and real credits rendering two identical curves for a variable rename, and users learn the tool cries wolf.*

### Symmetrist Check
Proves the two harnesses' stub configs are **byte‑identical** over their shared keys, allowing a symmetric difference only for keys the diff itself justifiably added/removed (e.g. head introduces a Redis call). Canonicalization is exactly specified (sorted keys, 17‑sig‑fig floats, seed = `H(baseSeed, i)`, timestamps → epoch 0, canonical JSON). *This catches the single most dangerous silent failure: a fabricated divergence caused by asymmetric stubs (5ms vs 5.0ms, different seeds) that would pass every other test.*

### Assayer *(12 replicates)*
Perturbs **only the stub parameters the Harness Engineer had to guess** (I/O latency, cache miss rate, clock granularity…), each declared with an uncertainty distribution, and measures how much the answer wobbles. Two estimators by observable kind - coefficient of variation for numeric, instability rate for categorical (matrix cells, node states, path traces). Feeds `stability_factor`. *A route that flips in 3 of 12 replicates isn't a route you should show someone - confidence collapses and the tool degrades.*

The confidence formula (a **product**, so any weak factor dominates):

```
agreement_rate   = matched / samples                       # differential test
stability_factor = clamp(1 − max_instability / 0.25, 0, 1) # Assayer
coverage_factor  = min(1, log(1 + samples) / log(1 + 256))

confidence = agreement_rate × stability_factor × coverage_factor
```

| Band | Range | UI |
|---|---|---|
| **high** | ≥ 0.85 | Solid curves, green "Verified" badge |
| **medium** | 0.60–0.85 | Error bands (numeric) / hatching (categorical), amber badge |
| **low** | < 0.60 | **Degrade - no toy shown** |

### Rendering Fidelity *(enforced on every render)*
1. **Y‑axis zero‑anchored** on every numeric render - never auto‑scaled to a divergence region.
2. **Divergence magnitude always shown as a number** in the pack's own units ("20× more", "1 of 12 cells flipped"), never implied by visual scale.
3. **Zoom is manual and explicitly labeled** - never automatic. *Auto‑scaling a 3% gap to fill the chart is the same class of lie as an asymmetric harness, one layer up the stack - and it would pass the other three guardrails because none of them look at the chart.*

### Graceful Degradation+ *(the exit that makes the rest believable)*
When Scout can't scope, the harness can't be built after 3 attempts, agreement stays < 0.85, confidence is low, or there's no executable reference - LEVER renders a **specific** `degradeReason` (named dependency, attempt count, failure mode), a **[Show me →]** divergence report, a plain explanation, and a **manual test recipe** (1–3 concrete inputs to try). **No toy is ever rendered.** *A tool that sometimes fabricates is worse than no tool, because it manufactures the exact false confidence LEVER exists to cure. The 5% where it says "I don't know" is what makes the 95% believable.*

## 9 · Feature inventory

### v2 - the trust foundation
| Feature | What it does | Why it matters |
|---|---|---|
| Diff intake (PR URL / ref pair / raw diff) | Resolve a change to base/head SHAs | The substrate for A/B comparison |
| Dual checkout | Materialize `/w/base` + `/w/head` | The entire product is a comparison |
| Triager Gate + force‑proceed | Drop no‑op diffs, recover from false skips | Don't waste credits; don't cry wolf |
| Scout dependency ledger | Classify every transitive dep | Tells the harness what to stub |
| Differential test vs. real code | 128 Sobol points, agreement rate | The core trust claim |
| Symmetrist / Assayer / Rendering Fidelity | The three guardrails above | Measured, not claimed, fidelity |
| Adversary search + surprise marker | Open the toy at the interesting case | Turns a sandbox into a bug report |
| Knob drag + always‑on divergence view | Old & new update together, < 150ms | "The aha" - understanding as a motor act |
| Escape hatch to code | Click a point → jump to the responsible line | Closes the loop from behavior back to code |
| The Receipt | Real stack trace + downloadable harness | A skeptic can verify the claim in one click |
| Pin‑as‑test | Write a regression test at the current position | Play → durable artifact |
| Graceful Degradation | Honest refusal, never a fake | The credibility engine |

### v3 - generality, agency, game feel
| Feature | What it does | Why it matters |
|---|---|---|
| **GitHub PR intake** (`POST /prs`) | Paste any public PR | "Does this work on *my* PR?" |
| **Generative Harness (IR + Stub Library)** | Harness unknown plain‑data callables | Kills the hardcoded 4‑shape gate |
| **World Director + WorldSpec** | Genre → stage + affordances | Packs become games, not charts |
| **Arena stage** | Request particles through old/new gates | Throughput/retry changes you can *watch* |
| **Search fog** | Live knob‑space point cloud during search | The demo visibly *computes* before the toy mounts |
| **Session ledger + permalink** (`/m/:changeId`) | List + reopen past microworlds | Shareable, durable review artifacts |
| **Degradation+** | Adds a manual test recipe + static notes | Refusal that still delivers value |
| **Construction budget** | Caps runs/LLM calls/wall‑clock | Demos never hang |
| **Composed 2×2 microworld** | base/A/B/AB, detects behavioral merge conflicts | Two green PRs that break *together* |
| **State‑workflow genre** | Finite‑state‑machine transitions | A fifth visual grammar |

### v3.1 - interaction & shareability (Phase H)
| Feature | What it does | Why it matters |
|---|---|---|
| **Time‑travel code review** | Scrub the timeline; diff lines that executed *this frame* light up | See exactly which code ran for each input |
| **Diff‑as‑controller** | Click a diff line → jump to the first frame that executed it | The diff becomes a joystick into the microworld |
| **"Break the PR" challenge** | Hide the answer; race the Adversary to find divergence | Gamifies review; great for teaching |
| **Microworld trading card** | One‑click PNG of thesis + confidence + surprise | A shareable social artifact (no deps) |
| **Receipt duel / twin microworld** | Two changes, one synced scrubber, head‑to‑head risk verdict | Compare two PRs on the same subsystem |

## 10 · Domain packs & world genres

Delta Analyst selects a **domain pack** (visual grammar); the World Director maps it to a **genre + stage**. `numeric-fn` is the always‑satisfiable fallback.

| Pack | Genre | Requires | Renders as |
|---|---|---|---|
| `rate-limiter` | throughput / retry‑storm | ≥1 driver knob; 1 timeseries observable | Two overlaid curves / **Arena** of request particles |
| `permission` | access‑matrix | ≥2 enum knobs with `axisRole`; 1 matrixCell | Tappable grid; flipped cells outlined |
| `decision-tree` | decision‑path | 2–4 mixed knobs; 1 pathTrace | One **union tree**; fork ringed, unreached dimmed |
| `state-machine` | state‑workflow | ≥1 enum (event); 1 nodeState | Node graph; active state highlighted |
| `numeric-fn` | numeric‑response | ≥1 scalar knob; 1 scalar observable | Generic x→y, two curves. **Always satisfiable.** |

## 11 · The hero corpus & the wild corpus

**Four curated heroes** - each exercises a *different* pack, proving the schema generalizes rather than that one demo was hand‑built:

- **Hero 1 - rate limiter:** fixed‑window → sliding‑window with per‑tenant burst. Surprise: at high tenant counts the new version admits ~20× more (tenant isolation). *Arena.*
- **Hero 2 - retry backoff:** exponential → exponential with full jitter. Surprise: without jitter, 100 clients self‑synchronize into a thundering herd (spiky vs. smooth p99). *Arena / spike theater.*
- **Hero 3 - permission check:** role‑based → attribute‑based with group inheritance. Surprise: a contractor can now read the audit log across tenants - one cell flips red→green. *Matrix.*
- **Hero 4 - feature flag:** flat `if`s → logic nested inside a flag gate. Surprise: for the beta cohort the pricing code never runs. *Decision tree.*


| ID | Source | Expected outcome |
|---|---|---|
| **W1** | `fixtures/wild_synth/` (unregistered function) | Verified via the **generative** harness - proves generality beyond the registry |
| **W2** | `fixtures/hero2/` | Verified throughput/retry Arena (retry loop visible in search fog) |
| **W3** | unscopable framework fixture | **Degradation+** - a live framework object → manual recipe, no fake |

## 12 · Measured results

LEVER tracks, on every run, which terminal outcome each change reaches: **verified (high/medium) · inert · unscopable · unharnessable · unverifiable**. Credibility over bluff - the honest number goes here.

**Reproduce:**
```bash
cd LEVER && source .venv/bin/activate
python scripts/run_wild_corpus.py     # prints a per‑fixture outcome table + hit rate
```

**Last measured (unit‑corpus path):** `hit_rate_verified_or_honest = 1.0` across the Wild Three - **W1** verified through the generative Harness IR, **W2** verified as a hero fixture + genre, **W3** correctly routed to Degradation+. That metric is deliberately defined as *"reached a verified microworld **or** an honest degradation"* - i.e. **it never produced a silent fake** on the corpus.

**Honest framing for arbitrary PRs.** LEVER targets **behavioral Python PRs with a plain‑data callable core**. It will *not* verify a change whose only modified functions require a live `db`/session/request object, or a change that is purely additive (no old behavior to diff against) - those degrade **by design**. This is the D(x)/framework‑boundary limit (see §16), and the degradation is a feature, not a crash. The raw verified‑fraction on arbitrary public PRs is bounded by that constraint; the value LEVER guarantees is that **it is never wrong about what it verified**.

### Automated test suite

LEVER ships **168 automated tests - all green** (130 backend + 38 frontend). The trust‑critical pieces are unit‑tested deterministically, so the guarantees hold in the *live* path, not just in prose. Judges can reproduce every number below in under two minutes.

**Backend - pytest**

| Metric | Value |
|---|---|
| Test files | **39** (32 for LEVER's own agents/guardrails/API + 7 hero fixture reference suites) |
| Tests collected | **130** |
| Result | **129 passed · 1 skipped** (~59s) |
| The 1 skip | a *live* E2B sandbox integration test, skipped on the offline unit path (runs only with `E2B_API_KEY` + network) |

What's covered and why:
- **Per‑agent tests** - `test_scout`, `test_delta_analyst`, `test_harness_engineer`, `test_generative_harness`, `test_fidelity_verifier`, `test_adversary`, `test_synthesizer`, `test_world_director`, `test_intake` - each agent's contract is pinned independently.
- **Guardrail tests** - `test_symmetrist` (byte‑identity invariant), `test_triager` (skip classification), `test_branch_instrumentation`, plus Assayer/Rendering‑Fidelity behavior - the *trust layer* is verified in isolation.
- **API tests** - `test_pr_intake_api`, `test_sessions_api`, `test_degradation_api`, `test_phase_ef_api`, `test_api` - the FastAPI edge and the "never render a fake" degradation path.
- **Infra adapters** - `test_pr_resolver` (GitHub), `test_dual_checkout`, `test_sqlite_adapter`, `test_openai_adapter`, `test_e2b_adapter*`.
- **Hero reference suites** - each hero fixture ships its own tests (`fixtures/hero1..4/tests`) that satisfy the executable‑reference precondition the Verifier requires.

**Frontend - Vitest + Testing Library (jsdom)**

| Metric | Value |
|---|---|
| Test files | **16** |
| Tests | **38 passed** (~8s) |

What's covered: component tests for every stage and interaction surface - `ArenaStage`, `UnionTree`, `PermissionMatrix`/matrix, `CodeDiff`, `ChallengePanel`, `ReceiptDuel`, `ComposedMicroworld`, `ObjectiveSelector`, `SearchTrace`, `SourceViewer`, and **`HonestChart` + `HonestChart.types`** (the zero‑anchored‑axis Rendering‑Fidelity guarantee) - plus App‑level flows (`App.search-trace`, `App.escape-hatch`, `App.degradation`).

**Reproduce (the proof):**
```bash
# Backend → 129 passed, 1 skipped
.venv/bin/python -m pytest -q --ignore=data --ignore=pinned_tests

# Frontend → 38 passed  (uses --environment jsdom via the npm script)
cd frontend && npm test
```

**Backend - 129 passed, 1 skipped:**

![Backend pytest results - 129 passed, 1 skipped](docs/images/tests-backend.png)

**Frontend - 38 passed:**

![Frontend Vitest results - 38 passed](docs/images/tests-frontend.png)

> Note: run the frontend suite via `npm test` (it sets `--environment jsdom`). A bare `vitest run` without that flag fails on `document is not defined` - a harness detail, not a product failure.

## 13 · Tech stack (complete)

**Backend (Python 3.12)**
- **FastAPI 0.139** + **uvicorn[standard] 0.51** - REST + WebSocket event stream (`/prs`, `/demos`, `/diffs/{id}`, `/sessions`, `/health`, `/ws/{changeId}`).
- **Pydantic 2.13** - the `InteractionSpec` / `WorldSpec` / Harness IR schemas that make rendering mechanical.
- **tree‑sitter 0.26** + **tree‑sitter‑python 0.25** - deterministic parsing for the Triager and Scout.
- **OpenAI 2.46 SDK** (GPT‑5.6) - the two LLM steps (Delta Analyst, Harness Engineer proposer), via a port so `domain/` never imports it directly.
- **E2B 2.34** - sandboxed execution of real checked‑out code and model‑generated harnesses (never on the host).
- **httpx 0.28** - GitHub REST for PR resolution.
- **numpy 2.5 / scipy 1.18** - Sobol low‑discrepancy sampling and the Assayer's statistics.
- **SQLite** (stdlib) - the durable session ledger.
- **pytest 9.1** - the test suite.

**Frontend (TypeScript, React 19)**
- **Vite 8** + **@vitejs/plugin-react** - dev server & build.
- **React 19** + **Zustand 5** - UI and the interactive knob/position store.
- **Recharts 3** - charts, imported through a single `HonestChart` boundary that enforces zero‑anchored axes.
- **Tailwind CSS 4** (`@tailwindcss/vite`) - styling.
- **Vitest 3** + **@testing-library/react** + **jsdom** - component tests.
- **oxlint** + **TypeScript 6** - linting & type checking.

**Architecture:** hexagonal - `domain/` is pure logic behind `Protocol` ports (`domain/ports.py`); adapters for OpenAI, E2B, GitHub, and SQLite live in `infra/`; `interface/api.py` is the FastAPI edge.

## 14 · Installation & configuration

**Supported platforms:** macOS and Linux (developed on macOS; the sandbox and toolchain are POSIX‑oriented).

**Required environment (`.env`):**
```
OPENAI_API_KEY=sk-...            # required - GPT‑5.6 for Delta Analyst & Harness proposer
E2B_API_KEY=e2b_...              # required - sandboxed execution
GITHUB_TOKEN=ghp_...             # optional - private repos / higher GitHub rate limits
LEVER_LLM_TIMEOUT_SECONDS=240    # optional - widen the LLM budget for large PRs
LEVER_SANDBOX_TEMPLATE=base      # optional - match the sandbox Python to the host
```

**Run:** see [Quick start](#4--quick-start). Backend on `:8765`, frontend on `:5173`. Do **not** use `uvicorn --reload` during analysis.

**Test:**
```bash
.venv/bin/python -m pytest -q --ignore=data --ignore=pinned_tests
cd frontend && npm test
```

## 15 · Known limitations (stated on purpose)

The house style is honest confidence over silent overreach. A stated blind spot is cheaper credibility than a hidden one.

- **D(x) blindness - LEVER measures what code returns, not how it got there.** A refactor that produces identical outputs by a different route reports as *behaviorally inert*, even if something structurally significant changed (e.g. a new dependency on a permission service). The `decision-tree` pack's path‑divergence objective partially mitigates this for that pack only; the general limit stands.
- **Framework/DB‑coupled changes degrade by design.** If the only changed functions need a live `db`/session/request object, LEVER refuses rather than faking one. (Ephemeral seeded backends and framework test‑client harnesses are the planned, unimplemented.)
- **Purely additive PRs have nothing to diff.** Differential testing needs a function present in *both* base and head; brand‑new functions have no "old" behavior to compare against.
- **Reach depth 2.** Second‑order effects beyond two hops are invisible; blast‑radius detection is excluded on soundness grounds (static analysis can't see dynamic dispatch/reflection/event buses).
- **No executable reference → no verification.** A repo with no runnable reference path routes to degradation.
- **Empirical, not proven, coverage.** "Never reached across 128 sampled inputs" is a measurement, not a proof of unreachability - and is labeled as such.

---

## 16 · Screenshots

A walk through the product, end to end. Every frame below is the real app - a
verified microworld built from an actual PR, never a mockup.

<!-- GALLERY:START - auto-generated from docs/images/gallery/. Do not hand-edit; re-run the gallery step. -->

<table>
<tr>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-01.png" alt="Paste a PR - the PR-first shell" /><br/>
<sub><b>1 · Paste a PR</b> - the PR-first shell. Drop a GitHub PR or launch a hero demo; every verified run is permalinked in the Session Ledger on the right.</sub>
</td>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-02.png" alt="Verified microworld - diff plus throughput arena" /><br/>
<sub><b>2 · A verified microworld</b> - the real diff on the left (executed lines glow per frame), a live throughput arena on the right, and the replay timeline below. Head admits 20× the traffic - a measured 94% divergence.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-03.png" alt="Interactive knobs and Break the PR challenge" /><br/>
<sub><b>3 · Play the change</b> - drag the knobs (RPS limit, burst, offered rate, tenant count) or flip on <b>Break the PR</b> to race the Adversary and find a diverging input yourself.</sub>
</td>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-04.png" alt="Adversary divergence search and prospective hypothesis" /><br/>
<sub><b>4 · Adversary &amp; hypotheses</b> - run a divergence search over measured inputs, or generate a <b>prospective candidate</b> from unwritten code and compare it against today's base.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-05.png" alt="State-workflow microworld" /><br/>
<sub><b>5 · State-workflow genre</b> - a task-status rule change rendered as an active node; base stays <code>done</code>, head now transitions to <code>in_progress</code> on reopen.</sub>
</td>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-06.png" alt="State-workflow categorical controls" /><br/>
<sub><b>6 · Categorical controls</b> - pick a status and an action. Enum knobs are bound as real value inputs, never faked as numeric loop counts.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-07.png" alt="Permission access matrix" /><br/>
<sub><b>7 · Permission matrix</b> - an attribute/group-inheritance change caught cell-by-cell: at the selected role×resource cell, base denies and head grants (<code>base=False, head=True</code>).</sub>
</td>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-08.png" alt="Decision path walk" /><br/>
<sub><b>8 · Decision path</b> - old and new fork at line <code>31:4</code>; the branch each version actually takes lights up as you scrub, so you see <em>why</em> outputs differ.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-09.png" alt="Honest degradation card" /><br/>
<sub><b>9 · Honest degradation</b> - when it can't prove fidelity, LEVER refuses to render a toy and hands you a plain explanation plus a manual test recipe instead of something fake.</sub>
</td>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-10.png" alt="Architecture diagram - intake and triage" /><br/>
<sub><b>10 · Under the hood (1/3)</b> - Intake resolves the PR to base/head SHAs and dual-checks out both worktrees; the deterministic Triager gate skips formatting / rename / dep-only noise before scouting.</sub>
</td>
</tr>
<tr>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-11.png" alt="Architecture diagram - verification loop" /><br/>
<sub><b>11 · Under the hood (2/3)</b> - the verification loop: the Harness Engineer builds a pair, the Symmetrist proves them byte-identical, and a Sobol K=128 differential test must hit ≥ 0.85 agreement against the real code before the Assayer scores confidence.</sub>
</td>
<td width="50%" valign="top">
<img src="docs/images/gallery/shot-12.png" alt="Architecture diagram - world build and outcomes" /><br/>
<sub><b>12 · Under the hood (3/3)</b> - only verified changes reach the Adversary, World Director, and Synthesizer that render a playable microworld; low-band or behaviorally-inert results branch to honest degradation instead.</sub>
</td>
</tr>
</table>

<!-- GALLERY:END -->

---

## 17 · License

Released under the **MIT License** - see [`LICENSE`](LICENSE). Per the hackathon rules the repository is **public with a license**; if kept private instead, share it with `testing@devpost.com` and `build-week-event@openai.com`.

---
