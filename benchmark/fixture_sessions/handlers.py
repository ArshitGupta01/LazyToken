from auth import authenticate


def primary(store, token, now):
    session = authenticate(store, token, now)
    return (200, session["user"]) if session else (401, "unauthorized")


def secondary(store, token, now):
    session = store.get(token)
    return (200, session["user"]) if session else (401, "unauthorized")
