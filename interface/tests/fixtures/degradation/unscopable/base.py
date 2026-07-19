class FlaskRequest:
    """A stand-in for a framework request object."""

    user: str


def authorize(request: FlaskRequest) -> bool:
    return request.user == "admin"
