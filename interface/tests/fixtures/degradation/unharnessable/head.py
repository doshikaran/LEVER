import idp


def authorize(user_id: str) -> bool:
    return idp.verify(user_id) is True
