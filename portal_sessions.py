"""Independent bounded web-portal sessions with separate CSRF tokens."""


class PortalSessions:
    def __init__(self, random_token, now_ms, timeout_ms=3600000, maximum=8):
        self.random_token = random_token
        self.now_ms = now_ms
        self.timeout_ms = max(1, int(timeout_ms))
        self.maximum = max(1, int(maximum))
        self._sessions = {}

    def create(self, identity):
        now = int(self.now_ms())
        self.expire(now)
        if len(self._sessions) >= self.maximum:
            oldest = min(
                self._sessions.values(), key=lambda item: item['last_seen_ms']
            )
            self._sessions.pop(oldest['id'], None)
        session_id = str(self.random_token())
        csrf = str(self.random_token())
        while not session_id or session_id in self._sessions or csrf == session_id:
            session_id = str(self.random_token())
            csrf = str(self.random_token())
        value = {
            'id': session_id,
            'csrf': csrf,
            'username': str(identity.get('username', '')),
            'role': str(identity.get('role', 'viewer')),
            'created_ms': now,
            'last_seen_ms': now,
        }
        self._sessions[session_id] = value
        return dict(value)

    def get(self, session_id, touch=True):
        now = int(self.now_ms())
        value = self._sessions.get(str(session_id))
        if not value:
            return None
        if now - int(value['last_seen_ms']) > self.timeout_ms:
            self._sessions.pop(str(session_id), None)
            return None
        if touch:
            value['last_seen_ms'] = now
        return dict(value)

    def verify_csrf(self, session_id, token):
        value = self.get(session_id, touch=False)
        return bool(value and value['csrf'] == str(token))

    def revoke(self, session_id):
        return self._sessions.pop(str(session_id), None) is not None

    def revoke_user(self, username):
        folded = str(username).lower()
        identifiers = [
            identifier for identifier, value in self._sessions.items()
            if str(value.get('username', '')).lower() == folded
        ]
        for identifier in identifiers:
            self._sessions.pop(identifier, None)
        return len(identifiers)

    def expire(self, now=None):
        now = int(self.now_ms() if now is None else now)
        expired = [
            identifier for identifier, value in self._sessions.items()
            if now - int(value['last_seen_ms']) > self.timeout_ms
        ]
        for identifier in expired:
            self._sessions.pop(identifier, None)
        return len(expired)

    def count(self):
        self.expire()
        return len(self._sessions)
