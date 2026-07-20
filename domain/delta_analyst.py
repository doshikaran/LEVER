"""LLM-backed drafting and deterministic validation of a partial Interaction Spec."""

import json
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from domain.pack_registry import disabled_pack_error, enabled_arity_contracts
from domain.ports import LLMClient
from domain.schema import (
    ArgumentBinding,
    DomainPackId,
    InteractionSpec,
    Knob,
    NumericDomain,
    Observable,
    PartialInteractionSpec,
    ScopedChangeSet,
)


@dataclass(frozen=True)
class _ProposalValidationError(Exception):
    """A repairable proposal failure whose message is shown to the LLM once."""

    message: str

    def __str__(self) -> str:
        return self.message


class DeltaAnalyst:
    """Drafts the Delta Analyst-owned Interaction Spec fields through an LLM port."""

    def __init__(self, llm_client: LLMClient) -> None:
        self._llm_client = llm_client

    def analyze(
        self,
        scoped_change_set: ScopedChangeSet,
        source_base: str,
        source_head: str,
        compatibility_feedback: str | None = None,
    ) -> PartialInteractionSpec:
        """Return a validated partial spec, retrying one invalid LLM proposal once."""
        if scoped_change_set.entry_point is None:
            raise ValueError("Delta Analyst requires a ScopedChangeSet with an entry point")

        validation_error: str | None = None
        for attempt in range(2):
            response = self._llm_client.complete(
                _build_prompt(
                    scoped_change_set,
                    source_base,
                    source_head,
                    validation_error,
                    compatibility_feedback,
                ),
                PartialInteractionSpec.model_json_schema(),
            )
            try:
                return _validated_proposal(response)
            except _ProposalValidationError as error:
                if attempt == 0:
                    validation_error = str(error)

        return _numeric_fn_fallback(scoped_change_set)


def analyze_delta(
    llm_client: LLMClient,
    scoped_change_set: ScopedChangeSet,
    source_base: str,
    source_head: str,
    compatibility_feedback: str | None = None,
) -> PartialInteractionSpec:
    """Convenience entry point for drafting a partial Interaction Spec."""
    return DeltaAnalyst(llm_client).analyze(
        scoped_change_set, source_base, source_head, compatibility_feedback
    )


def _build_prompt(
    scoped_change_set: ScopedChangeSet,
    source_base: str,
    source_head: str,
    validation_error: str | None,
    compatibility_feedback: str | None = None,
) -> str:
    """Build the complete constrained-decoding prompt from the required inputs."""
    repair_instruction = ""
    if validation_error is not None:
        repair_instruction = (
            "\nYour previous proposal failed validation: "
            f"{validation_error}\nReturn a corrected proposal that satisfies the contract.\n"
        )
    compatibility_instruction = ""
    if compatibility_feedback is not None:
        compatibility_instruction = (
            "\nA previous proposal was schema-valid but the registered harness "
            "could not consume it:\n"
            f"{compatibility_feedback}\n"
            "Return a different valid InteractionSpec proposal that does not repeat "
            "that incompatibility.\n"
        )

    return f"""\
You are Lever's Delta Analyst. State the behavioral change and draft only the
InteractionSpec fields thesis, domainPack, knobs, and observables. Output a JSON
object matching the response schema exactly. Do not write a harness.

ScopedChangeSet:
{json.dumps(scoped_change_set.model_dump(mode='json'), indent=2, sort_keys=True)}

Dependency ledger:
{json.dumps(scoped_change_set.dependency_ledger.model_dump(mode='json'), indent=2, sort_keys=True)}

Scoped base source:
```python
{source_base}
```

Scoped head source:
```python
{source_head}
```

Full InteractionSpec JSON Schema:
{json.dumps(InteractionSpec.model_json_schema(), sort_keys=True)}

Enabled domain-pack arity contracts (only these packs are selectable):
{enabled_arity_contracts()}{repair_instruction}{compatibility_instruction}
"""


def _validated_proposal(response: dict) -> PartialInteractionSpec:
    """Parse a response and enforce its hard caps and pack-specific contract."""
    if not isinstance(response, dict):
        raise _ProposalValidationError("Proposal must be a JSON object.")

    try:
        thesis = response["thesis"]
        domain_pack = DomainPackId(response["domainPack"])
        raw_knobs = response["knobs"]
        raw_observables = response["observables"]
        if not isinstance(raw_knobs, list) or not isinstance(raw_observables, list):
            raise TypeError("knobs and observables must both be arrays")
        cap_error = _cap_error(raw_knobs, raw_observables)
        if cap_error is not None:
            raise _ProposalValidationError(cap_error)
        knobs = [Knob.model_validate(value) for value in raw_knobs]
        observables = [Observable.model_validate(value) for value in raw_observables]
        proposal = PartialInteractionSpec(
            thesis=thesis,
            domainPack=domain_pack,
            knobs=knobs,
            observables=observables,
        )
    except (KeyError, TypeError, ValueError, ValidationError) as error:
        raise _ProposalValidationError(f"Proposal is schema-invalid: {error}") from error

    contract_error = _arity_contract_error(proposal)
    if contract_error is not None:
        raise _ProposalValidationError(contract_error)
    return proposal


def _cap_error(knobs: list[Any], observables: list[Any]) -> str | None:
    """Return the first exceeded display cap as a corrective LLM instruction."""
    if len(knobs) > 4:
        return (
            f"you proposed {len(knobs)} knobs, the maximum is 4 — "
            "select only the most behaviorally relevant."
        )
    if len(observables) > 2:
        return (
            f"you proposed {len(observables)} observables, the maximum is 2 — "
            "select only the most behaviorally relevant."
        )
    return None


def _arity_contract_error(proposal: PartialInteractionSpec) -> str | None:
    """Return the specific arity violation for a proposal, or None when valid."""
    knobs = proposal.knobs
    observables = proposal.observables
    pack = proposal.domainPack
    availability_error = disabled_pack_error(pack)
    if availability_error is not None:
        return availability_error

    if pack is DomainPackId.RATE_LIMITER:
        if not any(knob.binding.kind == "driver" for knob in knobs):
            return "rate-limiter requires at least one knob with binding.kind 'driver'."
        if not _exactly_one_render(observables, "timeseries"):
            return "rate-limiter requires exactly one timeseries observable."
        return _axes_must_be_absent(knobs, "rate-limiter")

    if pack is DomainPackId.STATE_MACHINE:
        if not any(knob.type == "enum" for knob in knobs):
            return "state-machine requires at least one enum event knob."
        if not _exactly_one_render(observables, "nodeState"):
            return "state-machine requires exactly one nodeState observable."
        return _axes_must_be_absent(knobs, "state-machine")

    if pack is DomainPackId.PERMISSION:
        enum_knobs = [knob for knob in knobs if knob.type == "enum"]
        if len(enum_knobs) < 2:
            return "permission requires at least two enum knobs."
        x_knobs = [knob for knob in knobs if knob.axisRole == "x"]
        y_knobs = [knob for knob in knobs if knob.axisRole == "y"]
        if len(x_knobs) != 1 or x_knobs[0].type != "enum":
            return "permission requires exactly one enum knob with axisRole 'x'."
        if len(y_knobs) != 1 or y_knobs[0].type != "enum":
            return "permission requires exactly one enum knob with axisRole 'y'."
        if not _exactly_one_render(observables, "matrixCell"):
            return "permission requires exactly one matrixCell observable."
        return None

    if pack is DomainPackId.DECISION_TREE:
        if not 2 <= len(knobs) <= 4:
            return "decision-tree requires between two and four knobs."
        if not _exactly_one_render(observables, "pathTrace"):
            return "decision-tree requires exactly one pathTrace observable."
        return _axes_must_be_absent(knobs, "decision-tree")

    if pack is DomainPackId.NUMERIC_FN:
        if not any(knob.type == "scalar" and knob.axisRole == "x" for knob in knobs):
            return "numeric-fn requires at least one scalar knob with axisRole 'x'."
        if not _exactly_one_render(observables, "scalar"):
            return "numeric-fn requires exactly one scalar observable."
        return None

    return f"Unsupported domain pack: {pack.value}."


def _exactly_one_render(observables: list[Observable], render: str) -> bool:
    """Require one total observable with the renderer required by the pack."""
    return len(observables) == 1 and observables[0].render == render


def _axes_must_be_absent(knobs: list[Knob], pack: str) -> str | None:
    """Reject axis roles for packs whose templates do not use axes."""
    axis_knobs = [knob.id for knob in knobs if knob.axisRole is not None]
    if axis_knobs:
        return f"{pack} forbids axisRole; found it on {', '.join(axis_knobs)}."
    return None


def _numeric_fn_fallback(scoped_change_set: ScopedChangeSet) -> PartialInteractionSpec:
    """Create the always-satisfiable numeric fallback after both attempts fail."""
    entry_point = scoped_change_set.entry_point
    if entry_point is None:
        raise ValueError("numeric-fn fallback requires an entry point")

    parameter_name, arg_index = _first_entry_parameter(entry_point.signature)
    return PartialInteractionSpec(
        thesis=f"Behavioral change in {entry_point.fn}.",
        domainPack=DomainPackId.NUMERIC_FN,
        knobs=[
            Knob(
                id=parameter_name,
                label=parameter_name.replace("_", " "),
                binding=ArgumentBinding(
                    kind="argument",
                    fn=entry_point.fn,
                    argIndex=arg_index,
                ),
                type="scalar",
                domain=NumericDomain(min=0, max=100, step=1),
                default=0,
                scale="linear",
                unit=None,
                axisRole="x",
            )
        ],
        observables=[
            Observable(
                id="return_value",
                label="return value",
                extractor={"kind": "returnValue", "path": "$"},
                render="scalar",
                unit=None,
                compareMode="delta",
            )
        ],
    )


def numeric_fn_fallback(scoped_change_set: ScopedChangeSet) -> PartialInteractionSpec:
    """Expose the schema-level numeric fallback to orchestrator recovery paths."""
    return _numeric_fn_fallback(scoped_change_set)


def _first_entry_parameter(signature: str) -> tuple[str, int]:
    """Find the first caller-supplied parameter, skipping an implicit self or cls."""
    start = signature.find("(")
    end = signature.rfind(")")
    if start == -1 or end <= start:
        return "input", 0

    parameters = signature[start + 1 : end].split(",")
    argument_index = 0
    for parameter in parameters:
        name = parameter.strip().lstrip("*").split(":", 1)[0].split("=", 1)[0].strip()
        if not name or name in {"self", "cls"}:
            continue
        return name, argument_index
    return "input", 0
