"""Head: reject path can recover to submitted (behavioral delta)."""


class OrderMachine:
    """Plain-data state machine — no live framework objects."""

    def __init__(self, start: str = "draft") -> None:
        self.state = start

    def apply(self, event: str) -> str:
        transitions = {
            ("draft", "submit"): "submitted",
            ("submitted", "approve"): "approved",
            ("submitted", "reject"): "rejected",
            ("rejected", "resubmit"): "submitted",
            ("approved", "ship"): "shipped",
        }
        self.state = transitions.get((self.state, event), self.state)
        return self.state
