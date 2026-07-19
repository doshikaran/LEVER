import idp


def authorize(user_id: str) -> bool:
    return bool(idp.verify(user_id))
