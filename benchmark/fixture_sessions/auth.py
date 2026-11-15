def authenticate(store, token, now):
    session = store.get(token)
    if session is None:
        return None
    return session
