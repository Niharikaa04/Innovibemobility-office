"""In-process rate limiter and response cache. Pure Python.
Cache keys ALWAYS include the user id AND role, so one user's (or role's) result can never be served to another.
Both are per worker process: with several workers each has its own counters/cache (documented limitation; a shared store needs approval)."""
import threading, time
from collections import OrderedDict, defaultdict, deque


class RateLimiter:
    def __init__(self, limit=60, window=60.0, clock=time.monotonic):
        self.limit, self.window, self.clock, self.hits, self.lock = limit, window, clock, defaultdict(deque), threading.Lock()
    def allow(self, key) -> bool:
        now = self.clock()
        with self.lock:
            q = self.hits[key]
            while q and now - q[0] >= self.window: q.popleft()
            if len(q) >= self.limit: return False
            q.append(now); return True


class TTLCache:
    def __init__(self, ttl=30.0, maxsize=256, clock=time.monotonic):
        self.ttl, self.maxsize, self.clock, self.d, self.lock = ttl, maxsize, clock, OrderedDict(), threading.Lock()
    @staticmethod
    def key(user_id, role, endpoint, *params): return (str(user_id), str(role), endpoint, tuple(params))
    def get(self, k):
        with self.lock:
            v = self.d.get(k)
            if not v: return None
            if self.clock() - v[0] > self.ttl: del self.d[k]; return None
            self.d.move_to_end(k); return v[1]
    def put(self, k, value):
        with self.lock:
            self.d[k] = (self.clock(), value); self.d.move_to_end(k)
            while len(self.d) > self.maxsize: self.d.popitem(last=False)
