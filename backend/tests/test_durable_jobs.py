import threading
import time

import pytest

from backend.durable_jobs import DurableJobQueue


def make_queue(tmp_path, **kwargs):
    return DurableJobQueue(str(tmp_path / "jobs.sqlite3"), **kwargs)


def test_initial_generation_completion_is_done(tmp_path):
    queue = make_queue(tmp_path)
    job = queue.enqueue("once", {"revision": 1})
    claimed = queue.claim("worker")
    assert queue.complete(job.id, claimed.lease_token)
    assert queue.get(job.id).status == "done"


def test_new_generation_during_lease_is_requeued_with_latest_payload(tmp_path):
    queue = make_queue(tmp_path)
    job = queue.enqueue("changed", {"revision": 1})
    claimed = queue.claim("worker")
    queue.enqueue("changed", {"revision": 2})
    assert claimed.payload == {"revision": 1}
    assert queue.complete(job.id, claimed.lease_token)
    next_claim = queue.claim("worker")
    assert next_claim.payload == {"revision": 2}
    assert queue.complete(job.id, next_claim.lease_token)
    assert queue.get(job.id).status == "done"


def test_repeated_expired_leases_dead_letter_and_new_payload_recovers(tmp_path):
    queue = make_queue(tmp_path, max_attempts=2, base_retry_seconds=0)
    job = queue.enqueue("crash", {"revision": 1})
    assert queue.claim("crashing", lease_seconds=0.01)
    time.sleep(0.03)
    assert queue.claim("crashing", lease_seconds=0.01)
    time.sleep(0.03)
    assert queue.claim("crashing", lease_seconds=1) is None
    assert queue.get(job.id).status == "dead"
    recovered = queue.enqueue("crash", {"revision": 2})
    assert recovered.status == "queued"
    assert recovered.attempts == 0
    assert queue.claim("worker").payload == {"revision": 2}


def test_enqueue_coalesces_revision_without_resetting_active_job(tmp_path):
    queue = make_queue(tmp_path)
    first = queue.enqueue("account:1", {"revision": 1})
    claimed = queue.claim("worker", lease_seconds=30)
    assert claimed.id == first.id
    updated = queue.enqueue("account:1", {"revision": 2})
    assert updated.id == first.id
    assert updated.generation == first.generation + 1
    assert queue.get(first.id).lease_token == claimed.lease_token
    assert queue.complete(claimed.id, claimed.lease_token)
    assert queue.get(first.id).status == "queued"


def test_expired_lease_reclaim_fences_old_worker_and_generation_requeues(tmp_path):
    queue = make_queue(tmp_path)
    job = queue.enqueue("task", {"x": 1})
    old = queue.claim("old", lease_seconds=0.01)
    time.sleep(0.03)
    fresh = queue.claim("new", lease_seconds=30)
    assert fresh.id == job.id
    assert old.lease_token != fresh.lease_token
    assert not queue.complete(job.id, old.lease_token)
    assert queue.complete(job.id, fresh.lease_token)


def test_failed_jobs_retry_with_bound_then_dead_letter(tmp_path):
    queue = make_queue(tmp_path, max_attempts=2, base_retry_seconds=0)
    job = queue.enqueue("retry", {})
    one = queue.claim("w", lease_seconds=10)
    assert queue.fail(job.id, one.lease_token, "temporary")
    two = queue.claim("w", lease_seconds=10)
    assert two.attempts == 2
    assert queue.fail(job.id, two.lease_token, "permanent")
    assert queue.get(job.id).status == "dead"


def test_concurrent_workers_claim_each_job_once(tmp_path):
    queue = make_queue(tmp_path)
    for i in range(30):
        queue.enqueue(f"job:{i}", {"i": i})
    claimed = []
    lock = threading.Lock()

    def worker(n):
        local = make_queue(tmp_path)
        while True:
            job = local.claim(str(n), lease_seconds=20)
            if job is None:
                return
            with lock:
                claimed.append(job.id)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(claimed) == len(set(claimed)) == 30


def test_restart_recovers_queued_and_expired_claim(tmp_path):
    queue = make_queue(tmp_path)
    queued = queue.enqueue("queued", {"a": 1})
    lease = queue.enqueue("leased", {"b": 2})
    queue.claim("crashed", lease_seconds=0.01)
    time.sleep(0.03)
    restarted = make_queue(tmp_path)
    ids = {restarted.claim("restarted", lease_seconds=10).id,
           restarted.claim("restarted", lease_seconds=10).id}
    assert ids == {queued.id, lease.id}


def test_renewal_and_invalid_token_are_fenced(tmp_path):
    queue = make_queue(tmp_path)
    job = queue.enqueue("renew", {})
    lease = queue.claim("w", lease_seconds=1)
    assert queue.renew(job.id, "wrong", lease_seconds=5) is False
    assert queue.renew(job.id, lease.lease_token, lease_seconds=5) is True
    assert not queue.complete(job.id, "wrong")
    assert queue.complete(job.id, lease.lease_token)
