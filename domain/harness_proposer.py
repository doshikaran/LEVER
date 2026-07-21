"""Optional LLM proposer that emits a validated HarnessIR for unknown shapes."""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from domain.harness_ir import HarnessIR, build_harness_ir
from domain.ports import LLMClient
from domain.schema import PartialInteractionSpec, ScopedChangeSet
from domain.stubs import StubPlan, stub_catalog_prompt, stub_plan


class HarnessProposer:
    """Asks the model for a HarnessIR, falling back to the deterministic builder."""

    def __init__(self, llm: LLMClient | None = None) -> None:
        self._llm = llm

    def propose(
        self,
        scoped_change_set: ScopedChangeSet,
        partial_spec: PartialInteractionSpec,
        *,
        repair_feedback: str | None = None,
    ) -> tuple[HarnessIR, StubPlan]:
        """Return IR + stub plan; prefer deterministic build, optionally refine via LLM."""
        plan = stub_plan(scoped_change_set.dependency_ledger)
        if plan.is_unharnessable:
            raise ValueError(plan.unharnessable_reason or "Change is unharnessable")

        deterministic_ir, plan = build_harness_ir(scoped_change_set, partial_spec, plan)
        if self._llm is None or repair_feedback is None:
            # Happy path: deterministic IR is the production default. The LLM is
            # reserved for explicit repair after a verifier divergence report.
            return deterministic_ir, plan

        schema = HarnessIR.model_json_schema()
        prompt = _prompt(scoped_change_set, partial_spec, plan, repair_feedback, deterministic_ir)
        try:
            raw = self._llm.complete(prompt, schema)
            proposed = HarnessIR.model_validate(raw)
            return proposed, plan
        except (ValidationError, ValueError, TypeError, KeyError):
            return deterministic_ir, plan


def _prompt(
    scoped_change_set: ScopedChangeSet,
    partial_spec: PartialInteractionSpec,
    plan: StubPlan,
    repair_feedback: str,
    seed_ir: HarnessIR,
) -> str:
    entry = scoped_change_set.entry_point
    assert entry is not None
    return (
        "You repair Lever harness plans. Return JSON matching the HarnessIR schema.\n"
        f"Entry point: {entry.fn} signature={entry.signature}\n"
        f"Partial spec: {json.dumps(partial_spec.model_dump(mode='json'), sort_keys=True)}\n"
        f"Stub catalog:\n{stub_catalog_prompt()}\n"
        f"Current stubs: {[stub.dependency for stub in plan.stubs]}\n"
        f"Seed IR: {json.dumps(seed_ir.model_dump(mode='json'), sort_keys=True)}\n"
        f"Verifier repair feedback: {repair_feedback}\n"
        "Keep A/B symmetry. Do not invent observable values.\n"
    )


__all__ = ["HarnessProposer"]
