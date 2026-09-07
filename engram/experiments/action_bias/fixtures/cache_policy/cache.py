class Cache:
    def __init__(self, ttl_seconds=60):
        self.ttl_seconds = ttl_seconds
        self.values = {}

    def get(self, key, now):
        value, stored_at = self.values[key]
        if now - stored_at > self.ttl_seconds:
            return None
        return value
