# Session service

Sessions are stored by token. Their optional `expires_at` field is a timezone-aware UTC datetime. Handlers return a status and a message. `now` is supplied by the caller as a timezone-aware UTC datetime.
