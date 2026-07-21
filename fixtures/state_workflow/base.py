"""Minimal harnessable order-state machine for the state-workflow genre."""


class OrderMachine:
    """Plain-data state machine — no live framework objects."""

    def __init__(self, start: str = "draft") -> None:
        self.state = start

    def apply(self, event: str) -> str:
        transitions = {
            ("draft", "submit"): "submitted",
            ("submitted", "approve"): "approved",
            ("submitted", "reject"): "rejected",
            ("approved", "ship"): "shipped",
        }
        self.state = transitions.get((self.state, event), self.state)
        return self.state
