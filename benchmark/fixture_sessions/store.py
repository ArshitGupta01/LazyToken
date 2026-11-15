class SessionStore:
    def __init__(self, sessions):
        self.sessions = sessions

    def get(self, token):
        return self.sessions.get(token)
