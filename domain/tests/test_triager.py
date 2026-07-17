"""Focused fixtures for the deterministic Triager Gate rule sequence."""

from dataclasses import dataclass

import pytest

from domain.triager import TriageVerdict, triage


@dataclass(frozen=True)
class TriagePair:
    """A minimal base/head pair and its expected deterministic verdict."""

    base: str
    head: str
    changed_files: list[str]
    expected: TriageVerdict


@pytest.fixture(
    params=[
        pytest.param(
            TriagePair(
                base="value = 1\n",
                head="value=1  # equivalent formatting\n",
                changed_files=["app.py"],
                expected=TriageVerdict(False, "formatting only"),
            ),
            id="rule-1-parse-and-rule-3-formatting",
        ),
        pytest.param(
            TriagePair(
                base="message = 'ready'\n",
                head='message = "ready"\n',
                changed_files=["app.py"],
                expected=TriageVerdict(False, "formatting only"),
            ),
            id="rule-2-canonical-string-quoting",
        ),
        pytest.param(
            TriagePair(
                base="def double(value):\n    return value * 2\n",
                head="def double(total):\n    return total * 2\n",
                changed_files=["app.py"],
                expected=TriageVerdict(False, "rename only"),
            ),
            id="rule-4-alpha-equivalent-rename",
        ),
        pytest.param(
            TriagePair(
                base='{"dependencies": {"example": "1.0.0"}}\n',
                head='{"dependencies": {"example": "2.0.0"}}\n',
                changed_files=["package.json", "requirements.txt"],
                expected=TriageVerdict(False, "dependency bump"),
            ),
            id="rule-5-manifest-only",
        ),
        pytest.param(
            TriagePair(
                base="def render(value: int) -> str:\n    return str(value)\n",
                head="def render(value: float) -> bytes:\n    return str(value)\n",
                changed_files=["app.py"],
                expected=TriageVerdict(False, "types only, no runtime effect"),
            ),
            id="rule-6-type-annotations-only",
        ),
        pytest.param(
            TriagePair(
                base="from legacy import client\n",
                head="import replacement\n",
                changed_files=["app.py"],
                expected=TriageVerdict(False, "no behavioral edits found"),
            ),
            id="rule-8-no-behavioral-edits",
        ),
        pytest.param(
            TriagePair(
                base="def total():\n    return 1\n",
                head="def total():\n    return 2\n",
                changed_files=["app.py"],
                expected=TriageVerdict(True),
            ),
            id="rule-7-numeric-literal-behavioral-edit",
        ),
        pytest.param(
            TriagePair(
                base="def publish(item):\n    return item\n",
                head="def publish(item):\n    return send(item)\n",
                changed_files=["app.py"],
                expected=TriageVerdict(True),
            ),
            id="rule-7-call-expression-behavioral-edit",
        ),
        pytest.param(
            TriagePair(
                base="def allowed(value):\n    return value > 10\n",
                head="def allowed(value):\n    return value >= 10\n",
                changed_files=["app.py"],
                expected=TriageVerdict(True),
            ),
            id="rule-9-proceed-real-behavioral-change",
        ),
    ]
)
def triage_pair(request: pytest.FixtureRequest) -> TriagePair:
    """Provide one minimal base/head fixture pair for each gate rule."""
    return request.param


def test_triage_rule_sequence(triage_pair: TriagePair) -> None:
    """Each pair reaches its expected first matching gate rule."""
    assert triage(
        triage_pair.base,
        triage_pair.head,
        triage_pair.changed_files,
    ) == triage_pair.expected
