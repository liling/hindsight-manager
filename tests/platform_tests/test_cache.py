import time
import uuid

from hindsight_manager.platform.cache import UserLRUCache


def test_cache_miss_returns_none():
    cache = UserLRUCache(capacity=10, ttl_seconds=60)
    assert cache.get(uuid.uuid4()) is None


def test_cache_hit_returns_value():
    cache = UserLRUCache(capacity=10, ttl_seconds=60)
    uid = uuid.uuid4()
    cache.set(uid, {"id": str(uid), "username": "alice"})
    assert cache.get(uid) == {"id": str(uid), "username": "alice"}


def test_cache_expiry_after_ttl():
    cache = UserLRUCache(capacity=10, ttl_seconds=1)
    uid = uuid.uuid4()
    cache.set(uid, {"id": str(uid)})
    time.sleep(1.1)
    assert cache.get(uid) is None


def test_cache_eviction_when_full():
    cache = UserLRUCache(capacity=2, ttl_seconds=60)
    u1, u2, u3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cache.set(u1, {})
    cache.set(u2, {})
    cache.set(u3, {})
    assert cache.get(u1) is None
    assert cache.get(u2) is not None
    assert cache.get(u3) is not None


def test_cache_batch_set():
    cache = UserLRUCache(capacity=10, ttl_seconds=60)
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    cache.batch_set([(u1, {"id": str(u1)}), (u2, {"id": str(u2)})])
    assert cache.get(u1) == {"id": str(u1)}
    assert cache.get(u2) == {"id": str(u2)}
