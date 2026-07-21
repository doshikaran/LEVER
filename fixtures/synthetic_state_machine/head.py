"""The head version: a pedestrian request at green now forces an early yellow."""


def next_state(current_state: str, event: str) -> str:
    transitions = {
        ("red", "timer"): "green",
        ("green", "timer"): "yellow",
        ("yellow", "timer"): "red",
        ("red", "pedestrian_request"): "red",
        ("green", "pedestrian_request"): "yellow",  # behavioral change
        ("yellow", "pedestrian_request"): "yellow",
    }
    return transitions.get((current_state, event), current_state)
