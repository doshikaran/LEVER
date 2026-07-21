"""A minimal state machine: a traffic light that ignores a pedestrian-request event."""


def next_state(current_state: str, event: str) -> str:
    transitions = {
        ("red", "timer"): "green",
        ("green", "timer"): "yellow",
        ("yellow", "timer"): "red",
        ("red", "pedestrian_request"): "red",  # ignored in the base version
        ("green", "pedestrian_request"): "green",
        ("yellow", "pedestrian_request"): "yellow",
    }
    return transitions.get((current_state, event), current_state)
