# LEVER — Final Build Specification
### OpenAI Build Week · Developer Tools track · v2.0 (build-ready)

> **Core claim, restated for the record:** the microworld executes the *real changed code* in a sandbox and differential-tests itself against the original code path. Every mechanism below exists to protect that claim. Any feature that weakens it is a bug, not a tradeoff.

---

## §0 — Locked Architecture

### 0.1 Roster

**Six agents.**

| # | Agent | One-sentence role |
|---|---|---|
| 1 | **Scout** | Determines what code the change actually reaches and what its dependencies are. |
| 2 | **Delta Analyst** | States the behavioral change and drafts the Interaction Spec. |
| 3 | **Harness Engineer** | Makes both versions executable in isolation. |
| 4 | **Fidelity Verifier** | Proves the harnesses preserve real semantics; hosts the Symmetrist check and the Assayer. |
| 5 | **Adversary** | Searches input space for maximum divergence. |
| 6 | **Synthesizer** | Renders the widget mechanically from the completed spec. |

Cartographer is dissolved into the Interaction Spec schema (§0.3) — the schema is what makes Synthesizer mechanical. Narrator is a prompt inside Synthesizer, not an agent.

**Four mandatory non-agent guardrails:** the Triager Gate (§0.4), the Symmetrist Check (§0.5), the Assayer (§0.6), and Rendering Fidelity (§0.7).

### 0.2 Resolved contradictions

**C-1 — Symmetrist vs. Assayer (seed determinism).**
*Conflict:* Symmetrist requires byte-identical seeds; Assayer requires observable variance across runs. A seeded deterministic harness has zero variance → confidence pinned at 1.0 forever.
*Resolution:* the invariant is **pairwise-within-replicate**, not global.

```
for i in 1..N:            # N = replicates
    seed_i = H(baseSeed, i)
    stubParams_i ~ Uncertainty(stubParamSpec)     # drawn once per replicate
    config(A, i) := { ...stubParams_i, seed: seed_i }
    config(B, i) := { ...stubParams_i, seed: seed_i }
    assert canonical(config(A,i)) ≡ canonical(config(B,i))   # Symmetrist
# Assayer measures variance ACROSS i, never within a pair.
```
A and B are byte-identical to each other within every replicate. Both vary across replicates. Symmetrist protects the comparison; the Assayer measures the model's sensitivity. No conflict.

**C-2 — "perturb dimensions that were NOT explicitly modeled."**
*Conflict:* you cannot perturb an unmodeled dimension. To perturb it you must model it; once modeled, it isn't unmodeled.
*Resolution:* what is actually perturbed is **stub parameter uncertainty**. When Harness Engineer stubs `db.query` at 5ms, it must also emit an uncertainty range for that choice (`5ms, plausible 2–20ms, log-uniform`). The Assayer samples that range. This is honest uncertainty propagation — *"how much does the answer depend on things I had to guess?"* — not a fiction about unmodeled physics.

**C-3 — variance ≠ confidence.**
*Conflict:* variance measures precision. A systematically biased stub yields low variance and high error.
*Resolution:* confidence is a product of three measured quantities (§0.6). Stability is one factor of three.

**C-4 — the Assayer vs. categorical observables.**
*Conflict:* `cv(o) = stdev_i / |mean_i|` is undefined for `pathTrace` (a categorical vector of branch decisions) and for `matrixCell` (boolean). No mean, no standard deviation → `stability_factor` undefined → `confidence` undefined → the `decision-tree` and `permission` packs can never produce a `FidelityReport`, and every run of Hero 3 and Hero 4 routes to graceful degradation.
*Resolution:* **two stability estimators, selected by observable kind** (§0.6). Numeric observables use the coefficient of variation. Categorical observables use the **instability rate** — the fraction of replicates deviating from the modal value. Both are bounded, both feed the identical `stability_factor` formula, and both answer the same question: how much does the answer wobble when the guesses are perturbed.

**C-5 — differential-testing a `pathTrace`.**
*Conflict:* the differential test compares harness output against the **real** code path. A `pathTrace` observable has nothing to compare against unless the real code path also emits branch traces.
*Resolution:* branch instrumentation is a **source transform over the checked-out tree**, not a property of the harness. It is applied identically to the harness invocation and to the reference invocation — same conditionals, same source-location tags. If the reference path cannot be instrumented (e.g., the only executable reference is a compiled artifact), `decision-tree` is **unavailable for that diff** and Delta Analyst selects another pack via the registry (§0.3).

**C-6 — an enum value for an unbuilt pack.**
*Conflict:* `decision-tree` ships in the `DomainPackId` enum but is near-term stretch (§7). If Delta Analyst selects it before the template exists, Synthesizer's `numeric-fn` fallback fails on arity — `numeric-fn` requires ≥1 *scalar* observable and a `pathTrace` is not one.
*Resolution:* a **pack registry** with an `enabled` flag. Delta Analyst's arity validator considers only enabled packs. Disabled packs are unselectable, so the fallback is never reached in a state it can't satisfy.

### 0.3 The Interaction Spec Schema

The single document that flows through the pipeline. Multiple agents own disjoint fields. **This schema is what makes Synthesizer a switch statement instead of a creative act.**

```typescript
type InteractionSpec = {
  specVersion: "2.0";
  changeId: string;                    // sha256(baseSha ‖ headSha ‖ scopeId)
  thesis: string;                      // one sentence, ≤140 chars
  domainPack: DomainPackId;            // DISCRIMINANT — selects the template
  knobs: Knob[];                       // 1..4  (hard cap 4; >4 is unreadable)
  observables: Observable[];           // 1..2  (hard cap 2)
  initialPosition: KnobPosition;       // written by Adversary
  surpriseMarker: SurpriseMarker | null;
  presets?: NamedPosition[];           // written by Adversary — top-K cached, zero new compute
  fidelity: FidelityReport;            // written by Fidelity Verifier
  provenance: Provenance;
};

type DomainPackId =
  | "rate-limiter"     // grammar: two overlaid timeseries curves
  | "state-machine"    // grammar: animated node graph, highlighted active state
  | "permission"       // grammar: access matrix, cells colored allow/deny
  | "decision-tree"    // grammar: one union tree, two highlighted paths
  | "numeric-fn";      // grammar: generic x→y curve  ← ALWAYS-SATISFIABLE FALLBACK

type Knob = {
  id: string;                          // stable; referenced by KnobPosition
  label: string;                       // "requests / sec"
  binding: ParamBinding;               // ← the contract to the harness
  type: "scalar" | "integer" | "enum" | "boolean";
  domain: { min: number; max: number; step: number } | { values: string[] };
  default: number | string | boolean;
  scale: "linear" | "log";
  unit: string | null;
  axisRole?: "x" | "y" | null;         // grid/curve packs map knobs to axes MECHANICALLY
};

// ParamBinding is the load-bearing type: it is how a UI control becomes a real argument.
type ParamBinding =
  | { kind: "argument"; fn: string; argIndex: number }   // positional arg of the entry fn
  | { kind: "config";   path: string }                   // dotted stub-config key, or a constructor/argument parameter introduced or changed by the diff; Symmetrist enforces environmental fakes byte-identically, while diff-justified real parameters may differ
  | { kind: "driver";   param: string };                 // workload driver param (e.g. "rps")

type Observable = {
  id: string;
  label: string;
  extractor: ObservableExtractor;
  render: "timeseries" | "scalar" | "histogram" | "matrixCell" | "nodeState" | "pathTrace";
  unit: string | null;
  compareMode: "overlay" | "delta" | "ratio";
};

type ObservableExtractor =
  | { kind: "returnValue"; path: string }                             // JSONPath into return
  | { kind: "counter";     name: string }                             // instrumented counter
  | { kind: "trace";       event: string; agg: "count"|"p50"|"p95"|"p99"|"max" }
  | { kind: "path";        instrumentation: "branch" };               // branch-decision vector

type KnobPosition = Record<string /*knobId*/, number | string | boolean>;

type NamedPosition = {
  position: KnobPosition;
  label: string;                       // MEASURED, never interpreted — see rule below
  divergence: number;
};

type SurpriseMarker = {
  position: KnobPosition;
  divergence: number;                  // normalized D(x), 0..1
  caption: string;                     // "new admits N× more than old"
};

type FidelityReport = {
  verdict: "verified" | "degraded";
  symmetrist: { passed: boolean; hashA: string; hashB: string; unjustifiedKeys: string[] };
  agreement:  { samples: number; matched: number; rate: number; tolerance: Tolerance };
  stability:  { replicates: number; perObservable: Record<string, StabilityEstimate> };
  coverage:   { samples: number; strategy: "sobol" | "grid" | "random" };
  confidence: number;                  // 0..1, derived — formula in §0.6
  band: "high" | "medium" | "low";
  degradeReason: string | null;        // human-readable; required if verdict==="degraded"
};

type StabilityEstimate =
  | { kind: "cv";        value: number }   // numeric observables
  | { kind: "instability"; value: number } // categorical observables — see §0.6 / C-4

type Tolerance =
  | { kind: "relative"; epsilon: number }   // |a−b| / max(|a|,|b|) ≤ ε
  | { kind: "absolute"; epsilon: number }
  | { kind: "exact" };                      // enums, booleans, matrix cells, path traces

type Provenance = {
  baseSha: string; headSha: string; repoUrl: string;
  generatedAt: string; modelIds: Record<string, string>;
  harnessSourceUri: string;            // the actual harness, downloadable — see "Receipt"
  forced?: boolean;                    // set when the user overrode a Triager SKIP
};
```

**The preset-label rule (permanent):** a preset label **may describe what was measured** and **must never assert what it means in the world.**

- ✅ *"340 rps, 3 tenants — measured divergence"* — earned by measurement
- ❌ *"Black Friday traffic"* — invented

Lever can prove what happens at 340 rps. It cannot prove that 340 rps *is* Black Friday. That is a claim about the world with no evidence behind it, and attaching it to a verified position lends it the verified badge's authority. `surpriseMarker` is already a named position whose name is earned; `presets` generalizes that mechanism and inherits its discipline.

**Field write-ownership (no field has two writers):**

| Fields | Writer | Written when |
|---|---|---|
| `changeId`, `provenance` | Orchestrator | at ingestion |
| `thesis`, `domainPack`, `knobs` (incl. `axisRole`), `observables` | **Delta Analyst** | after Scout succeeds |
| `fidelity` | **Fidelity Verifier** | after verification completes |
| `initialPosition`, `surpriseMarker`, `presets` | **Adversary** | after search completes |
| *(reads all, writes none)* | **Synthesizer** | after spec is complete |

**Domain pack arity contracts** — Delta Analyst MUST satisfy the chosen pack's contract, or fall back to `numeric-fn`. Only packs with `enabled: true` in the registry are selectable (C-6).

| Pack | Requires | Template behavior |
|---|---|---|
| `rate-limiter` | ≥1 knob with `binding.kind === "driver"`; exactly 1 `timeseries` observable | Two overlaid curves (A solid, B dashed), shared axes, divergence region shaded |
| `state-machine` | ≥1 `enum` knob (the event); 1 `nodeState` observable | Two graphs side by side, active node highlighted, differing nodes ringed |
| `permission` | ≥2 `enum` knobs with `axisRole` set (`"x"` = subject, `"y"` = resource); 1 `matrixCell` observable | One matrix; cell shows A/B split-diagonal; flipped cells outlined |
| `decision-tree` | 2–4 knobs, **any mix of types** (enum/scalar/boolean); exactly 1 `pathTrace` observable | **One union tree.** See below. |
| `numeric-fn` | ≥1 `scalar` knob (`axisRole: "x"`); 1 `scalar` observable | Generic x→y, two curves. **Always satisfiable.** |

#### The `decision-tree` pack — full specification

**Template behavior — ONE union tree, never two.**
Nodes = predicates, labeled with source location. Edges = branch outcomes. The old path is highlighted in one color, the new path in another; the shared prefix appears in both. Nodes touched by neither path are **dimmed as "unreached."** The **fork point** — where the two paths first separate — is ringed.

Two side-by-side trees with different topologies is a spot-the-difference puzzle. That is precisely the cognitive work Lever exists to eliminate — it would be **worse than a text diff**, because at least a text diff aligns by line number. The union tree is not a stylistic preference; it is the only construction that doesn't defeat the product.

**Construction method — empirical, not static.**
The tree is **not** built from static control-flow analysis. Per-language CFG construction would violate Scout's contract (§2.1: deterministic, fast, no LLM) and is out of scope. Instead:

1. **Harness Engineer** adds a trace event at every conditional, tagged by source location, when instrumenting the harness (§2.3). Per C-5, the identical source transform is applied to the reference invocation.
2. The tree is **reconstructed from the paths actually taken** across the Adversary's cached evaluations — reusing the existing 128-point cache (§2.5). **Zero new compute for this step.**
3. **Node correspondence between old and new is derived from the diff itself**, not inferred. Predicates untouched by the diff share identical source locations and identical AST nodes — already in Scout's output (§2.1). Added and removed nodes *are* exactly what the diff shows. This is **ground truth, not approximate tree alignment.** Approximate alignment inside the trust boundary is the class of thing this product refuses.

**Interaction — clicking a leaf is a cached forward lookup.**
Each leaf holds the set of `KnobPosition`s that empirically landed there across the cached evaluations. Clicking jumps to one. This is **explicitly not** an inverse query (`f⁻¹(leaf)`), which is many-to-one, possibly empty (contradictory predicate conjunctions = dead code), and an SMT problem — ill-posed, and rejected on the same grounds as chart-drag (§1.8). It mirrors the Search Trace click-to-jump mechanism (§6.1) exactly.

**Divergence invariant enforcement.**
One union tree, **one shared `KnobPosition` driving both highlighted paths.** Never two trees. The always-on divergence view (§1.8) is enforced structurally here: there is only one tree, so there is only one input.

### 0.4 The Triager Gate

**Not an agent. No model call. Pure static, target ≤150ms.**

Signal, in order — first match wins:

```
1. Parse base and head with tree-sitter → AST_A, AST_B.
2. Normalize both: strip comments, strip whitespace/formatting nodes,
   canonicalize string quoting.
3. If AST_A ≡ AST_B                                 → SKIP  ("formatting only")
4. If AST_A ≡α AST_B  (alpha-equivalent: consistent
   identifier substitution, structure identical)     → SKIP  ("rename only")
5. If every changed file ∈ MANIFEST_FILES
   (package.json, requirements.txt, go.mod, …)       → SKIP  ("dependency bump")
6. If all AST edits are type-annotation nodes only   → SKIP  ("types only, no runtime effect")
7. behavioralEditCount := count of AST edits whose node kind ∈ BEHAVIORAL_KINDS
   BEHAVIORAL_KINDS = { control flow (if/while/for/match/return/raise/try),
                        binary & comparison operators, numeric/string literals,
                        call expressions, assignments to non-local state,
                        decorators/modifiers, async/await, concurrency primitives }
8. If behavioralEditCount == 0                       → SKIP  ("no behavioral edits found")
9. Else                                              → PROCEED
```

**Escape hatch:** every SKIP renders a one-line reason plus `Run anyway →`. Forcing proceed sets `provenance.forced = true` and bypasses steps 3–8. Without the escape hatch a false SKIP is unrecoverable and the user distrusts the gate.

**Without this gate:** the pipeline spends ~15s and real credits rendering two identical curves for a variable rename. Users learn the tool cries wolf and stop opening it. This is the cheapest feature in the system and one of the most load-bearing.

### 0.5 The Symmetrist Check

Runs **first** inside Fidelity Verifier — fail fast, before any expensive execution.

```python
def symmetrist(harnessA, harnessB, diff, replicate_i):
    cA = canonicalize(harnessA.stub_config, replicate_i)
    cB = canonicalize(harnessB.stub_config, replicate_i)

    keysA, keysB = set(cA), set(cB)
    sym_diff = keysA ^ keysB              # legitimate ONLY if the diff added/removed a dep
    justified = new_dependency_keys(diff) | removed_dependency_keys(diff)
    unjustified = sym_diff - justified
    if unjustified:
        return FAIL(unjustifiedKeys=sorted(unjustified))

    for k in keysA & keysB:               # every SHARED key must be byte-identical
        if sha256(cA[k]) != sha256(cB[k]):
            return FAIL(unjustifiedKeys=[k])

    return PASS(hashA=sha256(canon_bytes(cA)), hashB=sha256(canon_bytes(cB)))
```

`canonicalize` — **specified exactly, because "byte-identical" is meaningless without it:**
- keys sorted lexicographically, recursively
- floats formatted `repr`-style, 17 significant digits, no locale
- `seed` field set to `H(baseSeed, replicate_i)` — identical for A and B (C-1)
- all timestamps → the fixed epoch `0`
- serialize to canonical JSON (no whitespace), UTF-8, then hash

**The symmetric-difference clause is not a loophole — it's the real case.** If the diff introduces a Redis call, head's stub config legitimately has a `redis.*` key base cannot have. Demanding literal byte-identity would fail every dependency-adding diff, including Hero 1. Demanding it only over the *intersection*, with the *difference* attributable to the diff itself, is the correct invariant.

**Failure behavior:** returns to Harness Engineer as a retry (counts against the limit of 3), with `unjustifiedKeys` as the specific instruction for what to fix.

**Without this check:** Harness Engineer stubs DB latency at 5ms for base and 5.0ms parsed as a different float for head, or seeds the RNG differently. Curves diverge. Each harness individually passes fidelity against its own real code path. The demo lands. **The insight is fabricated and nothing in the system can tell.** This is the single most dangerous silent failure in Lever.

### 0.6 The Assayer

Lives inside Fidelity Verifier's output. **MVP: one overall confidence figure for the whole microworld.** Per-claim/per-observable confidence is explicitly out of scope.

**What gets perturbed** — only stub parameters that Harness Engineer had to *guess*, each declared with an uncertainty spec:

| Stub param class | Default | Uncertainty distribution |
|---|---|---|
| I/O latency (`db.*`, `http.*`) | 5 ms | log-uniform [2 ms, 20 ms] |
| Cold-cache probability | 0.0 | uniform [0.0, 0.3] |
| Clock resolution / tick granularity | 1 ms | discrete {0.1, 1, 10} ms |
| Scheduler interleaving seed | fixed | `H(baseSeed, i)` |
| Default return of unmodeled getters | type zero-value | {zero-value, empty, plausible-nonempty} |
| GC / pause injection | none | uniform [0, 5] ms per 100 ops |

If Harness Engineer stubbed nothing (fully pure change), the uncertainty set is empty → stability = 0 legitimately, and `stability_factor = 1`. That's correct: a pure function has no stub uncertainty to propagate.

**How many runs:** `N = 12` replicates. Rationale: CV estimates stabilize acceptably by ~10 samples at the tolerance bands used here [Guessing on the exact number — 12 is an affordable default; measure and tune during build], and 12 × 2 harnesses × ~9 knob positions ≈ 216 sandbox runs, which fits the credit budget. Replicates are embarrassingly parallel — fan out.

**How instability maps to the indicator — two estimators, selected by observable kind (C-4):**

```
NUMERIC observables  (render ∈ {timeseries, scalar, histogram}):
    cv(o) = stdev_i(value_i(o)) / |mean_i(value_i(o))|
    (if mean ≈ 0, use absolute stdev against the observable's declared unit scale)
    → StabilityEstimate { kind: "cv", value: cv(o) }

CATEGORICAL observables  (render ∈ {matrixCell, nodeState, pathTrace}):
    modal(o)      = most frequent value across replicates i
    instability(o) = 1 − count(modal(o)) / N
    → StabilityEstimate { kind: "instability", value: instability(o) }
```

Both estimators answer the same question — *how much does the answer wobble when I perturb the things I had to guess* — and both feed the identical downstream formula:

```
max_instability = max over o of estimate(o).value
stability_factor = clamp(1 − max_instability / CV_MAX, 0, 1),     CV_MAX = 0.25
agreement_rate   = matched / samples                              # from the differential test
coverage_factor  = min(1, log(1 + samples) / log(1 + 256))

confidence = agreement_rate × stability_factor × coverage_factor
```

**Correction:** the differential test uses `K = 128` Sobol points (`m = 7`); the original `K = 64` / `256` pairing capped a perfect run at ~0.752 confidence and could never reach the `high` band.

A path that flips route in 3 of 12 replicates scores `instability = 0.25` → `stability_factor = 0` → confidence collapses → graceful degradation. That is the correct behavior: **a route that isn't stable under stub uncertainty is not a route you should show someone.**

**Why the product, not an average:** these are conjunctive requirements. A harness that agrees perfectly but is wildly unstable is not trustworthy, and averaging would hide that. Any factor near zero must dominate. [Design decision, not a derived fact.]

**Bands and their consequences:**

| Band | Range | UI | Consequence |
|---|---|---|---|
| `high` | ≥ 0.85 | Solid curves, green "Verified" badge | Normal |
| `medium` | 0.60 – 0.85 | Curves rendered **with error bands** sized to the estimate; amber badge. For categorical packs: unstable cells/nodes/edges are **hatched**, not shaded. | Shown, with visible uncertainty |
| `low` | < 0.60 | — | **Degrade path (§1.10). No toy is shown.** |

The `medium` band is why the Assayer exists: without it, everything between "certainly right" and "certainly wrong" gets either falsely promoted or needlessly discarded. Error bands make the uncertainty *visible in the same gesture* as the insight — the user drags and sees the bands widen exactly where the model is guessing.

### 0.7 Rendering Fidelity — the fourth guardrail

The Symmetrist protects the harness. The differential test protects the semantics. The Assayer protects the confidence. **Rendering Fidelity protects the picture** — and until v2.0, nothing in this spec audited the rendering layer at all.

**Why this belongs in the same trust category as the other three, stated plainly:** if old = 100ms and new = 103ms at the point of maximum divergence in the entire input space, auto-scaling the y-axis so that 3% gap fills the chart is **the y-axis truncation deception** — manufacturing drama from a negligible effect. Lever would be refusing to fabricate a simulation and then fabricating significance with an axis range. **That is the same class of lie as an asymmetric harness, one layer up the stack.** It would pass the Symmetrist, pass the differential test, and pass the Assayer, because none of them look at the chart.

**The rules:**

1. **Y-axis is zero-anchored by default** on every render with a continuous numeric axis (`timeseries`, `scalar`, `histogram`). No automatic scaling to a divergence region, ever. *(Not applicable to `matrixCell`, `nodeState`, `pathTrace` — categorical renders have no scale to truncate.)*
2. **The divergence magnitude is always displayed as a number** alongside any chart — `surpriseMarker.divergence`, rendered in the pack's own units (*"N× more"*, *"8× p99 spike"*, *"1 of 12 cells flipped"*, *"3 of 7 predicates diverged"*). **Never implied by visual scale alone.** The number is the evidence; the chart is the illustration.
3. **Zoom is a manual, explicitly-labeled user action only** — a `zoom to the difference` control. Never automatic, never silent. The user must know when they have left the honest frame.

Rule 2 applies to all five packs. Rules 1 and 3 apply wherever there is a scale.

**This guardrail is not cuttable** (§7).

---

## PART 1 — Complete Feature Inventory (MVP)

### 1.1 Ingestion

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Diff Intake — Codex hand-off** | User types `lever` in a Codex session. A line appears under the agent's summary: *"Reading the change — N files."* No window opens yet. | User command in Codex session | Codex session context (worktree path, HEAD, base ref) | The primary path. Without it, Lever is a separate destination the user must remember to visit; adoption dies. |
| **Diff Intake — PR URL** | User pastes `https://github.com/org/repo/pull/N`. Resolves to (baseSha, headSha). | Paste + Enter in web UI | Network access, repo read perms | No async/review-time use; no permalink sharing loop. |
| **Diff Intake — git ref pair** | `lever abc123..def456` | CLI invocation | Local repo | Can't inspect arbitrary history; Ghost-of-Releases and Session Ledger re-runs become impossible. |
| **Diff Intake — raw diff** | User pastes unified diff text. | Paste into intake box | — | **Degraded by design:** with no repo, Scout cannot build a dependency map and Verifier has no real code path. Routes straight to §1.10 with reason *"no repository context — cannot verify."* This intake exists to *explain why it can't work*, not to work. |
| **Repo Context Loader** | Progress line: *"Reading the change — 9 files."* | Immediately after any intake resolves to (baseSha, headSha, repoUrl) | Intake | Nothing downstream exists. Both checkouts are the substrate. |
| **Dual Checkout** | Invisible. Two working trees materialize in the sandbox: `/w/base`, `/w/head`. | Repo Context Loader success | Sandbox runtime, repo access | **No A/B comparison is possible.** This is not an optimization; the entire product is a comparison. |
| **Change Scoping** | If the diff bundles unrelated behaviors: *"This change does three things. Which one do you want to feel?"* — three cards, each with a one-line thesis. User clicks one. | Delta Analyst returns >1 independent behavioral cluster | Delta Analyst (first pass), Scout | One toy about three behaviors is mud. The user learns nothing and blames the tool. |
| **Scope memory** | Chosen `scopeId` persists; re-running the same PR reopens the same scope. | Scope selection | Session Ledger | User re-picks every time; friction compounds. |

### 1.2 Triage

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Triager Gate** | Either silent (PROCEED, pipeline continues) or a single line: *"This looks like a rename — no behavioral change to play with. **Run anyway →**"* | Dual Checkout complete | tree-sitter grammars for the repo's languages | Wasted compute; worse, boring microworlds train users to ignore Lever. |
| **Force-proceed** | Clicking `Run anyway` starts the full pipeline. | User click on a SKIP notice | Triager Gate | A false SKIP becomes unrecoverable and the gate becomes an adversary. |
| **Skip reason** | The specific rule that fired, in plain words ("formatting only", "dependency bump"). | SKIP verdict | Triager Gate | An unexplained refusal reads as a failure, not a judgment. |

### 1.3 Analysis

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Scout: dependency mapping** | Progress: *"Nine files touched, one behavior changed: request admission."* | Triager verdict = PROCEED | Dual Checkout, tree-sitter | Harness Engineer has no dependency ledger and cannot know what to stub. |
| **Scout: entry-point selection** | Invisible. Picks the outermost changed function callable with plain data. | During Scout | Call graph | Without a callable entry there is nothing to harness; must fail loudly here rather than silently later. |
| **Scout: dependency ledger** | Invisible. Every transitive dep classified `pure \| io \| clock \| random \| network \| db \| native`. | During Scout | Import + call graph | Harness Engineer stubs blind; stub uncertainty specs (§0.6) can't be generated. |
| **Delta Analyst: behavioral thesis** | One sentence at the top of the panel: *"Old: fixed window. New: sliding window with per-tenant burst."* | Scout emits non-empty ScopedChangeSet | Scout output, both source texts | The user has no frame for what they're about to play with. Also: this line is the free giveaway that competitors sell as their whole product. |
| **Delta Analyst: spec draft** | Invisible. Writes `thesis`, `domainPack`, `knobs` (incl. `axisRole`), `observables`. | Same as above | Scout output, pack registry | No spec → Synthesizer has nothing to switch on. |
| **Domain pack selection** | Determines the visual grammar the user will see. | Delta Analyst, after thesis | Pack arity contracts + `enabled` registry (§0.3, C-6) | Generic viz for everything; Lever looks like a chart library. |
| **Progressive disclosure during wait** | Four lines stream in order over ~11s: files touched → behavior identified → old vs new → *"Building you something to pull on…"* | Each pipeline stage completing | All upstream stages | A spinner. The wait is the most under-designed moment in every AI product; here it's where we hand over the summary for free and signal that summaries aren't the point. |

### 1.4 Harnessing

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Stub generation (both versions)** | Invisible. Generates stubs for every non-pure dep in the ledger. | Spec draft has ≥1 knob AND ≥1 observable | Dependency ledger, spec draft (knobs must be parameterizable) | Real code doesn't run standalone. Lever works only on pure functions, i.e., on nothing real. |
| **Uncertainty spec emission** | Invisible. Each stub emits `{default, distribution}` per §0.6. | During stub generation | Stub generation | The Assayer has nothing to perturb → confidence is unmeasurable → the whole trust story collapses to a claim. |
| **Driver generation** | Invisible. A workload driver that accepts knob params and invokes the entry function. Shared by A and B. | After stub generation | Spec `knobs[].binding` | `binding.kind === "driver"` knobs have nothing to bind to; the rate-limiter pack becomes unusable. |
| **Branch instrumentation** | Invisible. Trace event at every conditional, tagged by source location — applied as a source transform to **both** the harness and the reference invocation (C-5). | `domainPack === "decision-tree"` | Scout's AST output | The tree pack has no `pathTrace` to extract and no reference to differential-test against. |
| **Harness pair emission** | Invisible. `harness.py`/`harness.ts` exposing `run(config, seed) → ObservationBundle`, one importing `/w/base`, one `/w/head`, **identical in every other byte**. | After driver generation | Dual checkout | — |
| **Symmetrist Check** | Invisible when passing. On failure: retry (§2.3). | Harness pair emitted | §0.5 | Fabricated divergence passes every other test. See §0.5. |

### 1.5 Verification

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Differential test vs. real code** | Invisible when passing. | Symmetrist PASS | Harness pair, **an executable reference path** (see precondition below) | Lever becomes an LLM narrating what it thinks the code does. This is the product. |
| **Sobol sampling** | Invisible. `K = 128` low-discrepancy points over knob space. | Start of differential test | Knob domains | Uniform random leaves gaps at small K; gaps are where stubs break. |
| **Assayer variance measurement** | Invisible. 12 replicates per §0.6, using the estimator matching each observable's kind. | Agreement computed | Uncertainty specs | Confidence pinned at 1.0 forever (C-1); categorical packs unbuildable (C-4). |
| **Confidence computation** | Renders as a badge: *"Verified — matched real behavior on 123/128 sampled inputs."* | Assayer complete | Agreement + stability + coverage | Users have no way to check; trust becomes a claim rather than a measurement. |
| **Error bands / hatching (medium band)** | Numeric: curves render with shaded bands. Categorical: unstable cells/nodes/edges hatched. | `band === "medium"` | Assayer per-observable estimate | Uncertain results look identical to certain ones. |
| **The Receipt** | Click *"Show me the receipt"* → the actual stack trace with real function frames, plus a download link to the generated harness. | User click on the confidence badge | `provenance.harnessSourceUri` | A skeptical engineer cannot check the claim in one click, so they don't believe it, so they don't use it. |
| **Retry loop → Harness Engineer** | Invisible. Max 3 (§2.4). | Symmetrist FAIL, or `agreement_rate < 0.85` | Divergence report | One bad stub kills an otherwise-recoverable microworld. |
| **Retry exhaustion → degrade** | Routes to §1.10. | 3rd retry fails | §1.10 | **Silent fabrication.** Non-negotiable. |

> **Hard precondition, stated plainly:** the differential test requires *some executable reference* — the repo's own test suite, or a callable entry with plausible inputs. **A repo with no runnable reference has no ground truth and Lever cannot verify anything in it.** Such repos route to §1.10 with reason *"no executable reference — I have nothing to check myself against."* All four hero diffs (Part 3) ship with tests specifically to satisfy this. For `decision-tree` diffs the reference must additionally be **instrumentable** (C-5).

### 1.6 Exploration

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Adversary search** | Invisible in MVP (visible in stretch — §6.1). | `fidelity.verdict === "verified"` | Verified harness pair | The toy opens at a default position where nothing interesting happens; the user has to find the insight themselves and usually won't. |
| **Initial position** | The toy **opens already showing the interesting case** — slider at 340, not 0. | Search complete | Search result | See above. This single behavior converts a sandbox into a bug report. |
| **Surprise marker** | A pulsing marker on the canvas + one line: *"Watch what happens as you cross 340."* | Search complete, `divergence > ε` | `surpriseMarker` | Users don't know where to look. |
| **Presets** | Up to 3 chips above the knob panel — the top-K cached positions by `D(x)`, each labeled with its **measured** properties (§0.3). One click jumps there. | Search complete | `presets` (zero new compute — points already cached) | Users find one insight and stop; the other interesting regions of the space go unvisited. |
| **"No divergence found"** | *"This change is behaviorally inert under the inputs I could model. Here's what I varied."* — **presented as a finding, not a failure.** | `max D(x) < ε` after kickback (§2.5) | Adversary | A genuinely valuable answer is thrown away as an error. See also Part 4. |

### 1.7 Rendering

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Template selection** | Determines what the user sees. **A switch on `domainPack`. No creative judgment.** | Spec complete (all fields written) | §0.3 arity contracts | This is why Cartographer was dissolved. Without the schema, Synthesizer improvises and microworlds are inconsistent between runs — users can't build intuition across them. |
| **Knob control generation** | Sliders/fields/toggles/chips/grids, generated from `knobs[]` per §1.8. | Template selected | `knobs[]`, `axisRole` | — |
| **Chart generation** | From `observables[].render` + `compareMode`. | Template selected | `observables[]` | — |
| **Rendering Fidelity enforcement** | Zero-anchored axes; divergence magnitude rendered as a number; zoom only on explicit user action. | Every render | §0.7 | A chart that silently exaggerates a 3% effect — the same lie as an asymmetric harness, one layer up. |
| **Confidence rendering** | Badge; error bands or hatching if medium. | Template selected | `fidelity` | Uncertainty invisible. |
| **Panel mount** | A panel slides in beside the terminal. Not a chat. **A canvas with knobs.** | Widget generated | — | A chat window would contradict the product's own thesis in its own UI: understanding here is a motor act, not a reading act. |

### 1.8 Interaction

**Controls per knob type — final:**

| Knob type | Control |
|---|---|
| `scalar` / `integer` | **Slider + numeric input field, always paired.** The slider is the gesture; the field is for precision, accessibility, and typing `340` on stage. |
| `boolean` | **Toggle switch.** Never a 0/1 slider — that is a defect, not a design choice. |
| `enum` | **Clickable chips by default.** A dropdown hides the option space behind a click; chips show it, which matters when a viewer must grasp the knob's range instantly. |
| `enum`, when `domainPack === "permission"` | **Tappable grid**, with `axisRole` mapping knobs to grid axes mechanically. The matrix axes *are* the two enum knobs — dropdowns beside the matrix are a redundant, strictly worse representation of the same space. Tapping a cell *is* setting `(subject, resource)`. |

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Knob drag** | User drags; both harnesses execute; both curves update. Target < 150ms per position (memoized). | `pointerdown` + `pointermove` on a control | Live sandbox session | **This is the aha.** No drag, no product. |
| **Position memoization** | Invisible. Every evaluated `KnobPosition → ObservationBundle` is cached (the Adversary already populated ~128 of them). | Every evaluation | Adversary search results | Drag latency becomes a round-trip per pixel; the gesture dies. |
| **Divergence view (always on)** | Old and new **always rendered together, at the same `KnobPosition`.** Never one alone, never at different positions. | Widget mount | Both harnesses | A toy of only the new behavior is a demo. The comparison *is* the review. |
| **Surprise marker render** | Pulsing marker at `surpriseMarker.position` + caption. | Widget mount, if non-null | §1.6 | — |
| **Preset chips** | Up to 3 chips; click jumps to that cached position. | Widget mount, if `presets` non-empty | §1.6 | — |
| **Escape hatch to code** | Click any point on the canvas → editor jumps to the responsible line. | `click` on canvas | Trace attribution from the harness run at that position | Lever becomes a lovely dead end. The loop from *behavior* back to *code* is what makes it a dev tool rather than a toy. |
| **Leaf click (tree pack)** | Click a leaf → jumps to a `KnobPosition` that empirically landed there. | `click` on a leaf node | Cached evaluations | — |
| **Knob reset** | "Back to the interesting bit" restores `initialPosition`. | User click | `initialPosition` | Users wander off the insight and can't find their way back. |
| **Manual zoom** | An explicit `zoom to the difference` control. | User click | §0.7 | — |

**Rejected interactions — permanent design record, not open questions:**

| Rejected | Reason |
|---|---|
| **Point-drag directly on a chart** (outside `numeric-fn`) | **Category error.** Direct manipulation is legitimate iff the rendered space *is* knob space. In `rate-limiter` the x-axis is *time*, not a knob — `rps` is a parameter of the whole run, not a coordinate on the curve. There is no `rps` "at" a point. Same for `state-machine` (nodes are states, not events), `permission` (already handled by the grid), and `decision-tree` (the tree is code space). `numeric-fn` passes the test, but it is the *fallback* pack — building the headline interaction for the degraded case is backwards. |
| **Two-cursor comparative gesture** | **Breaks the same invariant as an asymmetric harness — rejected on principle, permanently.** Lever's claim is *same input, different code*. The Symmetrist enforces that in the harness; the always-on divergence view enforces it in the UI. A gesture letting "before" and "after" sit at different knob positions produces a difference **not attributable to the diff**, rendered in the exact visual language that says "this difference is the diff." It would pass every check in the system, because none of them look at the interaction layer. |
| **Voice control** | **Contradicts the core thesis.** Lever's argument is that understanding is a motor act, not a linguistic one — *stop reading, start pulling*. Replacing the pull with a spoken command reinstalls language as the interface, which is the thing we removed. The real accessibility need underneath is served by the numeric field + keyboard/ARIA, which are free and don't fail in noisy shared offices or for users who can't speak. |
| **Inverse chart query, in general** | **Ill-posed in every pack except direct knob-space packs.** `f⁻¹(target)` is many-to-one, possibly empty, and properly an SMT problem. Where the want is legitimate ("touch the picture, not the panel"), it is served by **forward lookups over cached points** — Search Trace click-to-jump (§6.1) and tree leaf-click (§0.3). |

### 1.9 Output & Session

| Feature | User-facing behavior | Trigger | Depends on | Breaks without it |
|---|---|---|---|---|
| **Pin-as-test** | Click *"Pin this"* → a regression test at the current `KnobPosition` is written to the branch, asserting the *current* observable values within `tolerance`. | User click | Current position, harness driver | The insight evaporates when the tab closes. This is the leverage payoff: play → artifact. |
| **Permalink** | Copy link. It renders the live microworld when opened in Lever's own viewer. Inline rendering inside a GitHub PR comment is not possible — GitHub's Markdown sanitizer escapes `<iframe>` tags into visible literal text rather than rendering or stripping them (confirmed via GFM's Markdown API). The workflow is: paste the permalink as a plain link in the PR comment; the reviewer clicks through to Lever's viewer. | User click "Share" | Session persistence, `changeId` | Understanding stays in one head. Review remains two people describing different mental models in prose. |
| **Session Ledger** | Sidebar list of every microworld generated, keyed to `(repo, changeId, commit)`. | Every widget mount | `changeId` | No re-run six months later; no drift detection; every stretch feature that needs history is impossible. |
| **Ledger re-run** | Click a past entry → regenerates against current HEAD, showing whether behavior drifted. | User click on ledger entry | Ledger, full pipeline | — |

### 1.10 Graceful Degradation

**Trigger:** any of —
- Scout: `unscopable` (no entry point callable with plain data)
- Harness Engineer: `unharnessable` after 3 retries (live IdP, native extension, unstubable dep)
- Fidelity Verifier: `agreement_rate < 0.85` after 3 retries
- Fidelity Verifier: `confidence < 0.60` (low band)
- Verifier precondition: no executable reference path (or, for `decision-tree`, no instrumentable one — C-5)
- Intake: raw diff with no repo context

**Behavior — the exact rendered output:**

> **I couldn't build a faithful model of this change.**
> The auth path depends on a live identity provider I can't stub without changing what it does. I tried three approaches; all three diverged from real behavior on sampled inputs. **[Show me →]**
> Here's a plain explanation instead — and here's the one input I'd manually test.

**Requirements:**
1. `degradeReason` is **mandatory and specific**. Never "something went wrong." Name the dependency, name the count of attempts, name the failure mode.
2. **[Show me →]** expands the actual divergence report: the sampled inputs where harness and real code disagreed, with both values.
3. The plain-language explanation is generated from Delta Analyst's `thesis` + scoped code — i.e., we fall back to exactly what our competitors ship, and we say so implicitly by calling it the consolation prize.
4. **No toy is rendered. Ever. Under any circumstance.**

**Why this is worth more than any feature in Part 5:** a tool that sometimes fabricates is worse than no tool, because it manufactures confidence — the exact disease Lever exists to cure. The 5% where we say "I don't know" is what makes the 95% believable. Every competitor in this space will die by fabricating in the 5%.

---

## PART 2 — Complete Agent Specification

### 2.1 Scout

| | |
|---|---|
| **Role** | Determines what code the change actually reaches and classifies its dependencies. |
| **Trigger** | Triager Gate returns `PROCEED` (or user force-proceeds) **and** Dual Checkout has materialized both trees. |
| **Input** | `{ baseSha, headSha, workBase: "/w/base", workHead: "/w/head", scopeId?: string }` — from Orchestrator. |
| **Output** | `ScopedChangeSet { entryPoint: {file, fn, signature}, changedNodes: AstNodeRef[], dependencyLedger: DepEntry[], reachDepth: number }` → **Delta Analyst**, **Harness Engineer**, and (for node correspondence) **Synthesizer**. |
| **Internal process** | (1) tree-sitter parse both trees. (2) Build static import graph + call graph. (3) Compute reachable set from changed nodes, **bounded at depth 2** — a deliberate scope limit, not an oversight; deeper reach is the excluded blast-radius feature. (4) Select entry point: the outermost changed function whose signature accepts plain data (primitives, dicts, dataclasses) rather than live framework objects. (5) Walk transitive deps of the entry point; classify each as `pure \| io \| clock \| random \| network \| db \| native`. |
| **Failure** | No entry point callable with plain data → emit `unscopable` with the specific reason (e.g., *"the change is inside a Django view requiring a live request object"*). **Surfaces to user via §1.10.** Not caught downstream — this must fail here, loudly, rather than producing a garbage harness. |
| **Retry** | None. Scout is deterministic static analysis; a retry would produce the same answer. |

**Model needs:** none. This is tree-sitter and graph traversal. Deliberately no LLM — Scout sits on the critical path and must be fast and deterministic. **The `decision-tree` pack adds no Scout capability:** node correspondence is derived from Scout's existing AST/source-location output (§0.3).

### 2.2 Delta Analyst

| | |
|---|---|
| **Role** | States the behavioral change and drafts the Interaction Spec. |
| **Trigger** | Scout emits a non-empty `ScopedChangeSet`. |
| **Input** | `{ scopedChangeSet, sourceBase: string, sourceHead: string, dependencyLedger, packRegistry }` — from Scout + config. |
| **Output** | Partial `InteractionSpec { thesis, domainPack, knobs (incl. axisRole), observables }` → **Harness Engineer** (needs `knobs` to know what must be parameterizable, and `domainPack` to know whether to branch-instrument) and **Synthesizer**. Optionally `clusters: BehavioralCluster[]` if >1 independent behavior → triggers **Change Scoping** (§1.1). |
| **Internal process** | GPT-5.6, large context. Prompt = scoped source (both versions) + dependency ledger + the `InteractionSpec` schema + the arity contracts of **enabled packs only** (C-6). Constrained decoding to the schema. Pack selection: the model proposes; a **validator** checks the proposed pack's arity contract — including `axisRole` presence where the pack requires it — against the proposed knobs/observables. On violation, **fall back to `numeric-fn`** rather than re-prompting (fallback is cheaper than a round trip and `numeric-fn` is always satisfiable). Hard caps enforced post-hoc: ≤4 knobs, ≤2 observables. |
| **Failure** | Schema-invalid output → one re-prompt with the validator error → then `numeric-fn` with a single scalar knob (`axisRole: "x"`). Trivial/uninteresting knobs → **not caught here.** Caught downstream by the Adversary's "no divergence found" kickback (§2.5). |
| **Retry** | 1 re-prompt on schema violation. Then fallback. |

**This is the one irreducibly-LLM step in the pipeline.** Everything else is analysis, execution, search, or templating. Worth being honest about: if this step is bad, the microworld is about the wrong thing, and no amount of verification downstream will save it — verification proves the toy is *faithful*, not that it's *interesting*.

### 2.3 Harness Engineer

| | |
|---|---|
| **Role** | Makes both versions executable in isolation without changing their observable semantics. |
| **Trigger** | Spec draft contains ≥1 knob AND ≥1 observable. |
| **Input** | `{ scopedChangeSet, dependencyLedger, knobs, observables, domainPack }` — from Scout + Delta Analyst. |
| **Output** | `HarnessPair { harnessA: {source, entryModule: "/w/base"}, harnessB: {...entryModule: "/w/head"}, stubConfigSchema, uncertaintySpecs }` → **Fidelity Verifier**. |
| **Internal process** | (1) For each non-`pure` dep in the ledger, generate a stub + its **uncertainty spec** (§0.6). (2) Generate a **workload driver** parameterized by every knob with `binding.kind === "driver"`. (3) **If `domainPack === "decision-tree"`:** apply branch instrumentation — a trace event at every conditional, tagged by source location — as a **source transform over the checked-out tree**, applied identically to the harness and the reference invocation (C-5). (4) Emit `run(config, seed) → ObservationBundle` — instrumented to extract each `observable.extractor`. (5) Emit **A and B as byte-identical files differing only in the import root.** Mechanism: a single templated harness with the module path as a parameter — makes symmetry structural rather than aspirational. |
| **Failure** | Cannot stub a dep (live IdP, native ext, hardware) → emit `unharnessable` with the specific dep named → **§1.10**. Cannot instrument the reference path when `decision-tree` is selected → report to Delta Analyst for pack re-selection (C-5); if no other pack fits, → **§1.10**. |
| **Retry (the loop)** | **Max 3 attempts.** What changes per attempt: <br>• **Attempt 1** — minimal stubbing: stub only `network`, `db`, `native`. Leave `clock`/`random` real. <br>• **Attempt 2** — triggered by Verifier's divergence report: additionally stub every dep the report implicates, plus `clock` and `random` (seeded). <br>• **Attempt 3** — reduce scope: re-target the harness to the *innermost* changed function (smaller surface, fewer deps), and widen `tolerance` from `relative ε=0.01` to `relative ε=0.05`. <br>**Exhausted → §1.10**, with `degradeReason` naming all three attempts and why each failed. |

### 2.4 Fidelity Verifier

| | |
|---|---|
| **Role** | Proves the harnesses preserve real semantics; produces the calibrated confidence figure. |
| **Trigger** | `HarnessPair` emitted by Harness Engineer. |
| **Input** | `{ harnessPair, referencePath, knobDomains, tolerance }` — from Harness Engineer + Scout. |
| **Output** | `FidelityReport` (written into the spec) → **Adversary** (if verified) or **§1.10** (if degraded). |
| **Internal process, in order** | **(a) Symmetrist** (§0.5) — fail fast, no execution. <br>**(b) Differential test** — Sobol-sample `K=128` points (`m=7`) over knob space. At each: run `harnessA` and the **real base code path**; compare each observable within `tolerance`. Same for `harnessB` vs real head. Categorical observables (`matrixCell`, `nodeState`, `pathTrace`) use `tolerance: { kind: "exact" }`. `agreement_rate = matched/samples`. <br>**(c) Assayer** (§0.6) — `N=12` replicates, stub params drawn from uncertainty specs, seeds `H(baseSeed, i)`, identical within each A/B pair. Compute the estimator matching each observable's kind (C-4). <br>**(d) Confidence** — `agreement × stability × coverage`; assign band. |
| **Why Sobol** | At K=128 over a 3–4 dimensional knob space, uniform random leaves clumps and voids. Stub infidelity concentrates at **boundaries**, which is exactly where voids fall. Low-discrepancy sequences cover the space evenly at small K. [Certain — this is the standard property of quasi-random sequences.] |
| **Failure** | Symmetrist FAIL → return to Harness Engineer with `unjustifiedKeys` (counts as a retry). `agreement_rate < 0.85` → return to Harness Engineer with a **divergence report** (the specific inputs and the two disagreeing values) (counts as a retry). `confidence < 0.60` after a verified agreement → **no retry** (the harness is faithful; the *model* is just uncertain) → **§1.10** with reason *"I can build a model of this, but it depends too heavily on things I had to guess."* |
| **Retry** | Shares Harness Engineer's budget of 3 (§2.3). |

**The structural point, restated because it is the architecture:** Harness Engineer and Fidelity Verifier **must be separate agents with opposed objectives.** Not for modularity. A single agent asked to both make the code run *and* certify it didn't cheat has already committed to the stub; asking it to critique the stub is asking it to critique itself. The Verifier's only reward is finding the lie. **Collapsing these two into one prompt fails for a structural reason, not a cosmetic one** — which is the test every other agent in this system must also pass, and which is why there are six and not ten.

### 2.5 Adversary

| | |
|---|---|
| **Role** | Finds the input where old and new diverge most. |
| **Trigger** | `fidelity.verdict === "verified"`. |
| **Input** | `{ harnessPair, knobDomains, observables, objective }`. |
| **Output** | `{ initialPosition, surpriseMarker, presets, searchTrace: TracePoint[] }` → **Synthesizer** (spec fields), or `no_divergence` → kickback to **Delta Analyst**. |
| **Objectives (a parameterized value, not new machinery)** | • `max_divergence` **(default)** — `D(x) = normalized_distance(obs_A(x), obs_B(x))`, normalized per observable by its observed range. <br>• `max_path_divergence` — **Hamming distance over the branch-decision vector.** Used with `decision-tree`. <br>• `reach_unsafe_state` — see §6.4. |
| **Internal process** | **Phase 1 (explore):** 64 Sobol points, evaluated in parallel. <br>**Phase 2 (exploit):** take the top-8 by objective, run bounded coordinate ascent from each (step-halving, max 8 evals per seed) → **64 further evals.** <br>**Budget: 128 evaluations total, hard cap.** All evaluations are independent → fan out across sandbox workers. Every evaluated point is cached and handed to §1.8 memoization — **the search doubles as the drag-latency cache**, which is why the toy is instant. It is also the corpus from which the `decision-tree` pack reconstructs its tree (§0.3) — zero additional compute. <br>**Presets:** top-3 cached positions by objective, labeled with **measured** properties only (§0.3). |
| **Failure** | `max D(x) < ε` (ε = 0.02 normalized) → **kickback to Delta Analyst**: "these knobs are dead, pick different ones." **Bounded at 1 kickback.** On the second failure → render *"This change is behaviorally inert under the inputs I could model"* (§1.6) — **a finding, not an error.** See Part 4 for what this finding does and does not mean. |
| **Retry** | 1 kickback to Delta Analyst. |

**Note the dual use, because it's the elegant part:** the Adversary's hunt for *"where do old and new diverge"* is mechanically the same search as the Verifier's need for *"where might my harness be lying"* — both want the boundaries. One search, two jobs. [Design intent; the MVP runs them sequentially, so the reuse is one-directional — Adversary consumes the Verifier's verdict, not vice versa.]

### 2.6 Synthesizer

| | |
|---|---|
| **Role** | Renders the widget mechanically from the completed spec. |
| **Trigger** | `InteractionSpec` is complete: `thesis`, `domainPack`, `knobs`, `observables`, `fidelity`, `initialPosition` all written. |
| **Input** | Complete `InteractionSpec` + live sandbox session handles for both harnesses + Scout's AST/source-location output (for tree node correspondence). |
| **Output** | A rendered widget (HTML/JS) bound to the live session + a `Narrator` line. → the user. |
| **Internal process** | **A switch statement over `domainPack`.** Select template → generate knob controls per §1.8 (using `axisRole` to map the `permission` grid axes mechanically) → generate chart from `observables[].render` and `compareMode` → **enforce Rendering Fidelity (§0.7)** → set initial state from `initialPosition` → render `surpriseMarker` and `presets` → render confidence badge and, if `band === "medium"`, error bands (numeric) or hatching (categorical). <br>**Union-tree template (`decision-tree`):** lay out the union of both paths as one tree; source node correspondence from Scout's existing diff/AST output — **no new Scout capability required**; highlight old and new paths; dim unreached nodes; ring the fork point. <br>**The Narrator line** is a single small-model call over `surpriseMarker.caption` — a prompt, not an agent. |
| **Failure** | Unknown or disabled `domainPack` → cannot occur: Delta Analyst selects only from enabled packs (C-6). Any other template failure → fall back to `numeric-fn`. **Never fails hard.** |
| **Retry** | None. Failure is impossible by the fallback contract. |

---

## PART 3 — The Curated Hero Diffs

**Selection criteria, applied to all:** (a) ships with a test suite → satisfies the executable-reference precondition; (b) a mostly-pure core → harnessable with few stubs → high Assayer confidence; (c) clean, legible divergence; (d) **each exercises a different domain pack**, proving the schema generalizes rather than that we hand-built one demo.

### Hero 1 — Rate limiter: fixed-window → sliding-window with per-tenant burst

**The change:** `admit(tenantId, now) -> bool` replaces a fixed 1-second counter bucket with a sliding-window log plus a per-tenant burst allowance. ~40 lines across `admission.py` and `window.py`. The head version adds a `burstAllowance` config key (legitimately in Symmetrist's symmetric difference — §0.5).

**Domain pack:** `rate-limiter`.
**Knobs:** `rps` (driver, 1–1000, log, `axisRole: null`), `tenants` (driver, integer 1–16), `burst` (config, 0–200).
**Observable:** `admitted/sec`, timeseries, overlay.

**Why chosen:** rate limiters are the canonical shape — everyone reads a throughput curve instantly, and the divergence is large, monotone-ish, and therefore reliably renderable. Deps are `clock` only → one stub → tight Assayer variance → high confidence band.

**The surprise marker:** At high tenant counts, the old version admits only up to the configured limit in one shared global window, regardless of how many tenants make requests. The new version gives each tenant an isolated window, so it can admit up to `limit × tenants`; the surprise marker is the large gap that isolation creates, not the burst path. The shared burst pool has a minor inverted effect in the observed implementation — it suppresses head admissions relative to its intended per-tenant behavior rather than inflating them. Caption: *"new admits about 20× more than old"* — rendered as a number per §0.7, on a zero-anchored axis. Clicking the divergence point escape-hatches to the tenant-window admission check. **This is a real bug, found by dragging, in code nobody read.** It is the demo.

### Hero 2 — Retry backoff: exponential → exponential with full jitter

**The change:** `next_delay(attempt)` goes from `base * 2**attempt` to `random.uniform(0, base * 2**attempt)`. ~8 lines. The driver simulates 100 concurrent clients.

**Domain pack:** `rate-limiter` (timeseries grammar).
**Knobs:** `clients` (driver, 1–200), `failureRate` (driver, 0.0–1.0), `maxRetries` (driver, 1–10).
**Observable:** `p99 completion time`, timeseries, overlay.

**Why chosen:** the visual is instantly legible and **counterintuitive** — the best kind of demo. Without jitter, all 100 clients retry at the same instants and self-synchronize into a thundering herd: the p99 curve is **violently spiky**, with towers at each retry boundary. With full jitter it's **smooth**. Spiky-vs-smooth needs no explanation; it lands pre-verbally. The random stream is seeded symmetrically and time is simulated → no live clock or scheduler to model and no stub uncertainty.

**The surprise marker:** `clients=100, failureRate=0.7, maxRetries=6`. Old p99 spikes to ~8× the new one at the third retry boundary. Caption: *"without jitter, all 100 clients retry at the same instant"* — magnitude stated numerically per §0.7.

### Hero 3 — Permission check: role-based → attribute-based with group inheritance

**The change:** `can(subject, action, resource) -> bool` moves from a flat role table to attribute matching with transitive group inheritance. ~60 lines.

**Domain pack:** `permission` (access matrix grammar).
**Knobs:** `role` (enum: viewer/editor/admin/contractor, **`axisRole: "x"`**), `resource` (enum: doc/billing/audit-log/settings, **`axisRole: "y"`**), `sameTenant` (boolean).
**Observable:** `allow/deny`, matrixCell, compareMode `delta`.

**Why chosen:** a **third visual grammar** — a matrix, not a curve — which is the proof that the domain-pack schema generalizes. Fully pure (no stubs at all) → `stability_factor = 1` legitimately → the confidence badge reads high for a *structural* reason, which is worth showing. And permission changes are exactly the place where *"the code reads fine and the behavior is a breach"* lives.

**Interaction note:** the matrix **is** the knob panel (§1.8). `axisRole` maps `role` and `resource` to the grid axes mechanically; `sameTenant` renders as a toggle beside it. No dropdowns.

**The surprise marker:** `role=contractor, resource=audit-log, sameTenant=false`. Old: **deny**. New: **allow** — a contractor inherits through a group that transitively grants audit-log read across tenants. **One cell flips red → green.** Caption: *"contractors can now read the audit log across tenants — 1 of 12 cells flipped"*. No curve, no reading, no ambiguity: a cell changed color and it's a security hole.

### Hero 4 — Feature flag with nested cohort conditions *(requires the `decision-tree` pack — near-term stretch, §7)*

**The change:** `should_apply_discount(user, cart, now) -> Decimal`. **Old:** a flat sequence of independent `if` checks — cohort, cart value, date window — each independently able to grant a discount. **New:** the entire logic nested inside a flag gate, with cohort checked *inside the canary branch only*. ~30 lines.

**Domain pack:** `decision-tree`.
**Knobs:** `cohort` (enum: control/beta/internal), `flagState` (enum: off/canary/on), `cartValue` (scalar, 0–500). Three knobs, mixed types — **no other pack takes this shape.**
**Observable:** `pathTrace` (extractor `{ kind: "path", instrumentation: "branch" }`).

**The surprise marker:** `flagState=canary, cohort=beta, cartValue=200`. Old walks **four predicates deep** and returns a 10% discount. New **stops at node 1** — the flag gate — returns 0, and **never reads cohort at all.** Three nodes dimmed as unreached. Caption: *"3 of 7 predicates diverged; 3 nodes never reached"*.

**Why this hero specifically justifies the pack:** the divergence here is **structural, not quantitative.** No curve and no matrix can express *"the code that computes your pricing never ran for this cohort."* The dimmed subtree is a fact about code that **has no rendering in any of the other four packs.** The demo line is: *"you shipped the new pricing logic, and for your entire beta cohort, the code that computes it never runs."*

**None of Heroes 1–3 should be reassigned to this pack.** Honestly, per hero:
- **Hero 1 (rate limiter):** the aha is *about 20× more admitted throughput at high tenant counts, caused by tenant isolation* — **magnitude, not route.** A tree is strictly worse.
- **Hero 2 (retry backoff):** the aha is *spiky vs. smooth* — **magnitude.** A tree is strictly worse.
- **Hero 3 (permission):** the genuine near-miss, since inheritance *is* a cascade. But the matrix answers *"what changed"* — one cell flips red→green, legible pre-verbally in a 3-minute video — and the tree answers *"why."* The **escape hatch to code (§1.8) already serves "why."** Matrix stays.

### The honesty clause — arbitrary diffs

**The hero diffs are the only diffs guaranteed to work flawlessly live.** That is stated plainly here and must be stated plainly in the README.

A user submitting an arbitrary outside diff experiences one of five outcomes, all designed:

| Outcome | What they see |
|---|---|
| **Verified, high** | A normal microworld. The full experience. |
| **Verified, medium** | The microworld **with error bands or hatching** and an amber badge. Honest, still useful. |
| **Inert** | *"This change is behaviorally inert under the inputs I could model."* A finding — with the caveat in Part 4. |
| **Unscopable / unharnessable** | §1.10 with the specific dependency named. |
| **Unverifiable** (no tests, no reference path) | §1.10: *"no executable reference — I have nothing to check myself against."* |

**Expected hit rate for arbitrary diffs: unmeasured, and I decline to guess.** [Guessing — the instinct is that it is low for MVP, likely well under half, dominated by the unharnessable and unverifiable paths.] **Measure it during build and put the real number in the README.** A tool that says *"works on 30% of diffs, refuses honestly on the rest"* is credible. A tool that implies it works on everything and degrades silently is the thing we're replacing.

---

## PART 4 — Known Limitations

Stated permanently, in README-facing language. This section exists because the house style is **graceful degradation and honest confidence reporting rather than silent overreach** — and a stated blind spot is cheaper credibility than a hidden one.

### 4.1 D(x) blindness — Lever measures what the code returns, not how it got there

The Adversary's default objective, `max_divergence`, measures **distance between observable outputs only.** A refactor that changes *how* an output is produced while producing **identical outputs today** reports as `D(x) = 0` — **behaviorally inert** — even when something structurally significant changed.

Concretely:

```python
# old
def can_deploy(user, env):
    if user.is_admin: return True
    if user.team == env.owner_team: return True
    return False

# new
def can_deploy(user, env):
    if user.has_permission("deploy", env): return True   # internally checks admin
    return False
```

Every observable matches at every knob position. `D(x) = 0` across the entire space. Lever reports *"behaviorally inert."*

Something did happen: the new version now depends on a permission service being reachable. Same answer today, a new failure mode tomorrow.

**README language:**

> *Lever measures divergence in what the code returns, not in how it got there. A refactor that produces identical outputs by a different route will report as behaviorally inert. That's a real limit of the approach, stated on purpose.*

**Partial mitigation, not a solution:** the `decision-tree` pack's `max_path_divergence` objective (§2.5) measures Hamming distance over the branch-decision vector rather than observable distance, and therefore **does** catch same-output-different-route — **but only for diffs scoped to that pack.** The general `D(x)` blindness remains true for `rate-limiter`, `state-machine`, `permission`, and `numeric-fn`. **Do not overclaim this as solved.**

### 4.2 Scope bounds, restated as limitations

- **Reach depth 2** (§2.1). Second-order effects beyond that are invisible. Blast-radius detection is excluded (§6.5) on soundness grounds: static analysis structurally cannot see dynamic dispatch, reflection, or event buses, and an unsound version would lie.
- **No executable reference → no verification** (§1.5). Most repos in the wild will hit this.
- **Empirical, not proven, tree coverage** (§0.3). *"Never reached across 128 sampled inputs"* is a measurement, not a proof of unreachability. Labeled as such in the UI.
- Delta Analyst's thesis is generated from static diff analysis before Adversary searches the behavior space — it is a hypothesis, not a verified claim, and may describe a mechanism that turns out to be a minor contributor (or entirely absent) once Adversary's search completes. For pinned hero diffs, the thesis is hand-verified against the empirical surpriseMarker before freezing. For arbitrary live diffs, this reconciliation does not yet happen — the thesis and the surprise-marker caption should be read as two independent signals, not a single confirmed narrative, until a future version cross-validates them.

---

## PART 5 — End-to-End Trigger Map

A literal build checklist. Every step: **what fires**, **what caused it**, **state after**.

| # | Fires | Caused by | State after |
|---|---|---|---|
| 1 | **Diff Intake** | User types `lever` in a Codex session (or pastes a PR URL / ref pair / raw diff) | `{repoUrl, baseSha, headSha}` resolved. If raw diff with no repo → **jump to step 47** |
| 2 | **Progress line** | Intake resolved | User sees *"Reading the change — 9 files."* |
| 3 | **Dual Checkout** | Intake resolved | `/w/base` and `/w/head` materialized in sandbox |
| 4 | **Orchestrator** writes `changeId`, `provenance` | Checkout complete | Empty `InteractionSpec` exists |
| 5 | **Triager Gate** | Checkout complete | Verdict `PROCEED` or `SKIP` |
| 6 | If `SKIP` → **Skip notice + `Run anyway →`** | Triager verdict | User sees the reason. **Terminal unless step 7** |
| 7 | If user clicks `Run anyway` → force-proceed | User click | `provenance.forced = true`; continue to 8 |
| 8 | **Scout** | Triager `PROCEED` (or forced) | Running |
| 9 | Scout: parse + import/call graph | Step 8 | Graphs built |
| 10 | Scout: reachable set, depth ≤ 2 | Step 9 | `changedNodes` scoped |
| 11 | Scout: entry-point selection | Step 10 | `entryPoint` or `unscopable` |
| 12 | If `unscopable` → **jump to step 47** | Step 11 failed | — |
| 13 | Scout: dependency ledger | Step 11 | `dependencyLedger` classified |
| 14 | Scout emits `ScopedChangeSet` | Step 13 | Available to Delta Analyst + Harness Engineer + Synthesizer |
| 15 | **Delta Analyst** | Step 14, non-empty | Running (GPT-5.6, large context) |
| 16 | Delta Analyst: thesis + spec draft | Step 15 | `{thesis, domainPack, knobs, observables}` proposed |
| 17 | Pack arity validator (enabled packs only; checks `axisRole` where required) | Step 16 | Valid, or → `numeric-fn` fallback |
| 18 | Hard caps enforced (≤4 knobs, ≤2 observables) | Step 17 | Spec draft written |
| 19 | If >1 behavioral cluster → **Change Scoping** cards | Step 16 | **Blocks on user click**; sets `scopeId`; **loop to step 8** with scope |
| 20 | **Thesis line renders** | Step 18 | User sees *"Old: fixed window. New: sliding window…"* |
| 21 | **Harness Engineer**, attempt = 1 | Spec draft has ≥1 knob AND ≥1 observable | Running |
| 22 | HE: stub generation + uncertainty specs | Step 21 | Stubs + `uncertaintySpecs` |
| 23 | HE: driver generation | Step 22 | Driver bound to `driver`-kind knobs |
| 23a | HE: **branch instrumentation** (harness **and** reference) | Step 23, **if** `domainPack === "decision-tree"` | Both invocations emit source-tagged branch traces. If reference is not instrumentable → back to step 15 for pack re-selection (C-5) |
| 24 | HE: emit `HarnessPair` (templated; import root is the only variable) | Step 23/23a | `harnessA`, `harnessB` |
| 25 | If `unharnessable` → **jump to step 47** | Step 22 or 24 failed | — |
| 26 | **Fidelity Verifier** | Step 24 | Running |
| 27 | **Symmetrist Check** | Step 26 | PASS / FAIL |
| 28 | If FAIL → **↺ LOOP A: back to step 21**, attempt += 1, with `unjustifiedKeys` | Step 27 FAIL | If attempt > 3 → **step 47** |
| 29 | **Differential test**: Sobol K=128 (`m=7`), A vs real base, B vs real head (categorical → `tolerance: exact`) | Step 27 PASS | `agreement_rate` |
| 30 | If no executable reference exists → **jump to step 47** | Step 29 precondition | — |
| 31 | If `agreement_rate < 0.85` → **↺ LOOP A: back to step 21**, attempt += 1, with divergence report | Step 29 | If attempt > 3 → **step 47** |
| 32 | **Assayer**: N=12 replicates; per-observable estimator by kind (cv \| instability) | Step 29 pass | `StabilityEstimate` per observable |
| 33 | **Confidence** = agreement × stability × coverage; assign band | Step 32 | `FidelityReport` written into spec |
| 34 | If `band === "low"` → **jump to step 47** (no retry — harness is faithful, model is uncertain) | Step 33 | — |
| 35 | **Adversary** | `verdict === "verified"` | Running; objective = `max_path_divergence` if tree pack, else `max_divergence` |
| 36 | Adversary Phase 1: 64 Sobol evals, parallel | Step 35 | objective evaluated at 64 points; **all cached** |
| 37 | Adversary Phase 2: coordinate ascent from top-8, ≤64 evals | Step 36 | 128 points total cached |
| 38 | If `max D < ε` → **↺ LOOP B: back to step 15** (Delta Analyst, "pick different knobs"), kickback = 1 | Step 37 | If kickback > 1 → **step 45** |
| 39 | Adversary writes `initialPosition`, `surpriseMarker`, `presets` (top-3, measured labels only) | Step 37 | **`InteractionSpec` is now complete** |
| 40 | **Synthesizer** | Step 39 (all fields written) | Running |
| 41 | Template selection — switch on `domainPack` | Step 40 | Template chosen |
| 41a | **Union-tree construction** from cached path traces; node correspondence from Scout's AST output | Step 41, **if** `domainPack === "decision-tree"` | Tree laid out; unreached nodes marked |
| 42 | Generate knobs (§1.8), chart, confidence badge, error bands/hatching if medium | Step 41/41a | Widget built |
| 42a | **Rendering Fidelity enforcement** (§0.7): zero-anchor axes, magnitude as number, zoom manual-only | Step 42 | Chart cannot silently exaggerate |
| 43 | **Panel mounts** beside the terminal | Step 42a | Canvas visible, **knobs pre-set to `initialPosition`** |
| 44 | **Narrator line** renders | Step 43 | *"Watch what happens as you cross 340."* **← READY** |
| 45 | *(Inert path)* **"Behaviorally inert"** notice | Step 38, kickback exhausted | Terminal. A finding, not an error — see Part 4.1 for what it does *not* mean |
| 46 | — | — | — |
| 47 | **↯ GRACEFUL DEGRADATION** | Steps 1, 12, 25, 28, 30, 31, 34 | Plain explanation + specific `degradeReason` + `[Show me →]` divergence report. **No toy rendered. Terminal.** |
| 48 | **User drags a knob** | `pointermove` on a control | Cache hit (Adversary populated it) or fresh sandbox eval; **both curves update <150ms** |
| 49 | **Divergence view updates** | Step 48 | Two curves, always together, same `KnobPosition` |
| 50 | **User clicks a canvas point** → **Escape hatch** | `click` | Editor jumps to the responsible line |
| 50a | **User clicks a tree leaf** → cached forward lookup | `click` on leaf | Knobs jump to a `KnobPosition` that empirically landed there |
| 51 | **User clicks "Show me the receipt"** | `click` on badge | Real stack trace + harness download |
| 51a | **User clicks a preset chip** | `click` | Knobs jump to that cached position |
| 52 | **User clicks "Pin this"** | `click` | Regression test at current `KnobPosition` written to branch |
| 53 | **User clicks "Share"** | `click` | Permalink copied as a plain link; opens the live microworld in Lever's own viewer, not inline in a GitHub PR comment |
| 54 | **Session Ledger** entry written | Step 43 | Keyed `(repo, changeId, commit)` |

**The two loops, isolated:**
- **↺ LOOP A** — Harness Engineer ↔ Fidelity Verifier. Re-enters at **step 21**. Triggered by step 28 (Symmetrist FAIL) or step 31 (agreement < 0.85). **Max 3 attempts**, escalating strategy per §2.3. Exhausted → **step 47**.
- **↺ LOOP B** — Adversary → Delta Analyst. Re-enters at **step 15**. Triggered by step 38 (`max D < ε`). **Max 1 kickback.** Exhausted → **step 45** (inert finding, *not* degradation — the pipeline worked; the change is genuinely boring, subject to Part 4.1).

*(Step 23a's pack re-selection also re-enters at step 15, but is not a counted loop — it is a one-shot pack downgrade.)*

---

## PART 6 — Near-Term Stretch (post-MVP only)

### 6.1 The Search Trace

**Behavior:** during the ~4s Adversary phase, the panel shows a **point cloud in knob-space** filling in live — each dot a real evaluated `KnobPosition`, colored by objective value, the cloud visibly condensing around the hot divergence region. Phase 1's Sobol points scatter evenly; Phase 2's coordinate-ascent points visibly *march* toward the peak. **Clicking any point jumps the knobs there** — a cached forward lookup, never an inverse query (§1.8).

**Trigger:** `fidelity.verdict === "verified"` → Adversary starts → each `TracePoint` streams to the panel as it lands.
**Depends on:** Adversary emitting `searchTrace` incrementally rather than at completion (a streaming change, not a new capability).

**Explicitly NOT framed as "two agents debating."** What happens under the hood is a sampling loop with a comparator. Dressing a numerical procedure in a debate costume is exactly the anthropomorphizing a technical judge will catch and hold against you. The honest version is better: it is a real-time rendering of a real search, it is beautiful, and **it visibly shows the compute** — which is precisely what Technological Implementation scores. You don't claim depth; you display it.

### 6.2 Prospective Mode

**Behavior:** the user types a hypothesis in plain language — *"what if we changed the retry backoff to exponential?"* — instead of pointing at a diff. Codex generates 3 candidate implementations. Lever harnesses and simulates **code that does not yet exist**. All three candidates render on one canvas, plus the current behavior. The user drags, compares, **then decides what to write.**

**Trigger:** user submits a hypothesis in the intake box (a new entry point, not a new pipeline).
**Depends on:** the entire existing pipeline, unchanged, with a Codex generation step spliced in at ingestion. **Zero new agents.**

**How the fidelity claim changes — and this must be visually enforced:**

| | Normal microworld | Prospective microworld |
|---|---|---|
| Claim | *"This is what your code does."* | *"This is what **this candidate** does."* |
| Verified against | The real base/head code path | The **generated** candidate only |
| What's proven | The harness preserves your code's semantics | The harness preserves the candidate's semantics |
| What's **not** proven | — | That the candidate is what you'd have written |
| UI | Solid curves, green **Verified** badge | **Dashed curves**, blue **Prospective** badge, and the words *"unwritten code"* in the header |

This is a **different type**, not a weaker instance of the same type. Rendering the two identically would silently break the trust contract while appearing to extend the product — the single most dangerous thing in Part 6.

### 6.3 Composed Microworlds

**Behavior:** the user selects two related diffs (typically two open PRs on the same subsystem). Lever builds **four harnesses** — `base`, `A`, `B`, `AB` — and renders a 2×2. Effects are not additive, so `AB` must actually be executed, not inferred from A and B.

**Trigger:** user selects a second `changeId` from the Session Ledger while a microworld is open.
**Depends on:** Session Ledger (§1.9), 4× harness generation, 4× verification (each pair Symmetrist-checked independently).

**What the UI shows when an interaction effect is detected:**

> ⚠️ **Behavioral merge conflict.**
> PR #412 is fine on its own. PR #418 is fine on its own. **Together, at 200 rps, they admit 4× the configured limit.**
> Git reports no conflict — these branches don't touch the same lines.

Detection: interaction exists iff `|obs(AB) − (obs(A) + obs(B) − obs(base))| > tolerance` — the deviation from additivity, which is exactly what a 2×2 factorial measures. [Certain — this is the definition of an interaction effect.]

**Why this matters:** *"you have a behavioral merge conflict"* describes a real thing that ruins real weekends, and it currently **has no name and no detector.** Two branches, zero textual conflict, git perfectly happy, behaviors jointly broken while each is individually fine.

### 6.4 Security Objective Swap

**Behavior:** a dropdown on the Adversary's objective. Default `max_divergence`. Alternative: `reach_unsafe_state` — the user declares an unsafe predicate over observables (`admitted > limit`, `can(contractor, audit-log) == allow`), and the Adversary searches for **any** input reaching it, in either version.

**Trigger:** user changes the objective selector → Adversary re-runs (128 evals, ~4s).
**Depends on:** the Adversary's objective already being a parameter of the search rather than a hardcoded constant — **this is a refactor, not a feature**, and it ships in the MVP even though the UI ships later. `max_path_divergence` (§2.5) is the second value in the same slot.

**The one real addition — the fuzzing prior:** the default sampler draws *plausible* inputs (that's what makes the divergence demo legible). Security needs *implausible* ones — malformed, boundary, adversarial: empty strings, `-1`, `MAX_INT`, unicode, nulls, oversized payloads. Swapping the objective must also swap the **sampler's prior** from plausible-uniform to boundary-weighted. Same search machinery, different distribution.

### 6.5 The `decision-tree` pack

Accepted as legitimate (§0.3), **not MVP.** Attempt only after all core agents and Heroes 1–3 are solid.

**Cost, stated honestly:** this is *not* the `axisRole` tier (one optional field). It is:
- branch instrumentation in Harness Engineer, **per language** (§2.3) — the variable, and the risk
- union-tree layout in Synthesizer (§2.6)
- node-correspondence wiring from Scout's existing output (§0.3)
- the `max_path_divergence` objective (§2.5) — cheap; the objective slot already exists
- Hero 4 itself (§3)

Estimate: **1.5–2 focused days** [Guessing; the per-language instrumentation dominates]. With the schedule as it stands, that is the entire remaining margin.

### Explicitly excluded — do not build, do not revisit

- **Blast-radius / dynamic dependency detection** beyond Scout's depth-2 static analysis. *Excluded on soundness:* static analysis structurally cannot see dynamic dispatch, reflection, DI containers, or event buses. An unsound version would confidently lie about scope. See Part 4.2.
- **Mid-session natural-language harness modification** (open-ended *"what if this ran during a deploy"*). *Excluded on scope:* answering it requires modifying the harness **and re-verifying** mid-session. Skipping the re-verify silently drops the guarantee through the friendliest-looking door in the product.
- **Non-engineer-facing simplified interfaces.** *Excluded on principle:* mapping code-level knobs to product-level concepts ("Black Friday traffic") is necessarily ungrounded — see the preset-label rule (§0.3).
- **Any pivot toward runtime production-incident diagnosis.**
- **Two-cursor gestures, voice control, inverse chart queries, point-drag outside `numeric-fn`** — see §1.8.

---

## PART 7 — Build Order

*(The only opinion in this document.)*

1. **Steps 1–4, 8–14, 21–24** — intake → checkout → Scout → a harness that runs at all, on Hero 1 only.
2. **Steps 26–34** — Verifier + Symmetrist + Assayer. **This is the fidelity test and it is the go/no-go.** If a Hero-1 microworld cannot execute the real changed code and prove it, Lever does not exist and no amount of Part 6 saves it.
3. **Steps 35–44** — Adversary + Synthesizer, `rate-limiter` pack only. Includes **Rendering Fidelity (§0.7)** — it is not a polish item; it ships with the first chart.
4. **Step 47** — Graceful Degradation. Before Heroes 2 and 3. It is more load-bearing than either.
5. **Heroes 2 and 3** — proves the schema generalizes. Hero 3 brings `axisRole` and the permission grid.
6. **Steps 48–54** — interaction (§1.8 controls), receipt, presets, pin, share.
7. **Part 6**, in the order listed, only if 1–6 are solid. The `decision-tree` pack (§6.5) and Hero 4 come **last**.

**Cut order if behind:**
**`decision-tree` pack + Hero 4** → Hero 3 → Hero 2 → Pin-as-test → Permalink → Escape hatch → Session Ledger.

**Never cut — the four guardrails:**
**the Symmetrist Check (§0.5), the differential test (§1.5), the Assayer (§0.6), Rendering Fidelity (§0.7)** — and **Graceful Degradation (§1.10)**, which is the thing that fires when they do their job.

Those are the product. Everything else is the interface to them.
