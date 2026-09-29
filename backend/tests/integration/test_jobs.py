"""The durable job queue and worker on real Postgres (FOR UPDATE SKIP LOCKED, backoff,
timeouts, orphan reclaim, dedupe) and ingestion running on top of it."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update

from app.config import settings
from app.domains.ingestion.background import recover_stuck_ingestions
from app.domains.ingestion.jobs import INGEST_KIND, enqueue_ingestion
from app.domains.jobs.queue import PostgresJobQueue, backoff_seconds
from app.domains.jobs.setup import worker as ingestion_worker
from app.domains.jobs.worker import HandlerRegistry, JobHandler, PermanentJobError, Worker
from app.main import app
from app.models.job import Job
from tests.integration.test_upload_to_search import (  # noqa: F401  (env is a fixture)
    DB_URL,
    env,
    make_pdf,
    onboard,
    upload,
)

pytestmark = pytest.mark.skipif(not DB_URL, reason="TEST_DATABASE_URL not set")

queue = PostgresJobQueue()
KIND = "test_job"


@pytest.fixture
def fast_retries(monkeypatch):
    monkeypatch.setattr(settings, "JOB_RETRY_BASE_S", 0.05)
    monkeypatch.setattr(settings, "JOB_RETRY_MAX_S", 0.2)


@pytest.fixture
async def maker(env):  # noqa: F811
    m, _ = env
    yield m
    async with m() as s:  # test jobs are not tied to an organization: clean them up
        await s.execute(text("DELETE FROM jobs WHERE kind = :k"), {"k": KIND})
        await s.commit()


async def enqueue(maker, **kw):
    async with maker() as s:
        job = await queue.enqueue(s, KIND, kw.pop("payload", {}), **kw)
        await s.commit()
        return job.id


async def get(maker, job_id) -> Job:
    async with maker() as s:
        return (await s.execute(select(Job).where(Job.id == job_id))).scalar_one()


def make_worker(maker, run, on_dead=None, worker_id="w1") -> Worker:
    registry = HandlerRegistry()
    registry.register(KIND, JobHandler(run=run, on_dead=on_dead))
    return Worker(lambda: maker(), registry, worker_id=worker_id)


async def ok(job):
    return None


# --- queue -------------------------------------------------------------------------


def test_backoff_grows_exponentially_and_is_capped(monkeypatch):
    monkeypatch.setattr(settings, "JOB_RETRY_BASE_S", 5.0)
    monkeypatch.setattr(settings, "JOB_RETRY_MAX_S", 300.0)
    assert [backoff_seconds(n) for n in (1, 2, 3, 4)] == [5.0, 10.0, 20.0, 40.0]
    assert backoff_seconds(20) == 300.0


async def test_job_runs_once_and_succeeds(maker):
    job_id = await enqueue(maker, payload={"x": 1})
    seen = []

    async def run(job):
        seen.append(job.payload)

    w = make_worker(maker, run)
    assert await w.run_once() == "succeeded"
    assert await w.run_once() is None  # nothing left
    job = await get(maker, job_id)
    assert seen == [{"x": 1}] and job.status == "succeeded" and job.attempts == 1
    assert job.finished_at and job.locked_by is None


async def test_concurrent_workers_never_claim_the_same_job(maker):
    ids = [await enqueue(maker) for _ in range(2)]
    async with maker() as a, maker() as b:
        first = await queue.claim(a, "wa", kinds=[KIND])  # A's transaction stays open
        second = await queue.claim(b, "wb", kinds=[KIND])  # B must skip A's locked row
        assert len(first) == len(second) == 1
        assert {first[0].id, second[0].id} == set(ids)  # two different jobs, no blocking
        third = await queue.claim(b, "wb", kinds=[KIND])
        assert third == []  # nothing else claimable
        await a.commit()
        await b.commit()


async def test_many_workers_run_each_job_exactly_once(maker):
    ids = [await enqueue(maker, payload={"n": i}) for i in range(12)]
    ran: list[int] = []

    async def run(job):
        await asyncio.sleep(0.01)
        ran.append(job.payload["n"])

    workers = [make_worker(maker, run, worker_id=f"w{i}") for i in range(4)]
    await asyncio.gather(*(w.run_until_idle() for w in workers))
    assert sorted(ran) == list(range(12))  # each exactly once, none lost
    statuses = [(await get(maker, i)).status for i in ids]
    assert statuses == ["succeeded"] * 12


async def test_dedupe_returns_the_active_job_and_allows_a_new_one_afterwards(maker):
    a = await enqueue(maker, dedupe_key="doc:1")
    b = await enqueue(maker, dedupe_key="doc:1")
    other = await enqueue(maker, dedupe_key="doc:2")
    assert a == b and other != a
    async with maker() as s:
        n = (await s.execute(text("SELECT count(*) FROM jobs WHERE kind = :k"), {"k": KIND})).scalar()
    assert n == 2

    assert await make_worker(maker, ok).run_until_idle() == 2
    c = await enqueue(maker, dedupe_key="doc:1")  # finished jobs no longer block
    assert c != a


async def test_delayed_jobs_wait_until_due(maker):
    job_id = await enqueue(maker, delay_s=0.3)
    w = make_worker(maker, ok)
    assert await w.run_once() is None
    await asyncio.sleep(0.35)
    assert await w.run_once() == "succeeded"
    assert (await get(maker, job_id)).status == "succeeded"


async def test_run_job_claims_only_that_job(maker):
    a, b = await enqueue(maker), await enqueue(maker)
    w = make_worker(maker, ok)
    assert await w.run_job(b) == "succeeded"
    assert (await get(maker, a)).status == "queued"
    assert await w.run_job(b) is None  # already finished: not claimable again


async def test_jobs_of_unregistered_kinds_are_left_alone(maker):
    async with maker() as s:
        other = await queue.enqueue(s, "somebody_elses_kind", {})
        await s.commit()
    try:
        assert await make_worker(maker, ok).run_once() is None
        assert (await get(maker, other.id)).status == "queued"
    finally:
        async with maker() as s:
            await s.execute(text("DELETE FROM jobs WHERE id = :i"), {"i": other.id})
            await s.commit()


# --- failure handling ----------------------------------------------------------------


async def test_transient_failure_retries_with_backoff_then_succeeds(maker, fast_retries):
    job_id = await enqueue(maker)
    calls = []

    async def flaky(job):
        calls.append(job.attempts)
        if len(calls) == 1:
            raise RuntimeError("provider timeout")

    w = make_worker(maker, flaky)
    assert await w.run_once() == "queued"  # failed once: back in the queue
    job = await get(maker, job_id)
    assert job.attempts == 1 and job.last_error == "provider timeout"
    assert job.run_after > datetime.now(UTC)  # not runnable until the backoff elapses
    assert await w.run_once() is None
    await asyncio.sleep(0.1)
    assert await w.run_once() == "succeeded"
    job = await get(maker, job_id)
    assert calls == [1, 2] and job.attempts == 2 and job.last_error is None


async def test_retries_are_exhausted_then_dead_and_on_dead_runs_once(maker, fast_retries):
    job_id = await enqueue(maker, max_attempts=3)
    dead = []

    async def always_fails(job):
        raise RuntimeError("boom")

    async def on_dead(job, error):
        dead.append((job.attempts, error))

    w = make_worker(maker, always_fails, on_dead)
    statuses = []
    for _ in range(3):
        statuses.append(await w.run_once())
        await asyncio.sleep(0.25)
    assert statuses == ["queued", "queued", "dead"]
    assert dead == [(3, "boom")]  # finalized exactly once, after the last attempt
    assert (await get(maker, job_id)).status == "dead"
    assert await w.run_once() is None


async def test_permanent_errors_are_not_retried(maker, fast_retries):
    job_id = await enqueue(maker)
    dead = []

    async def bad_input(job):
        raise PermanentJobError("file is corrupt")

    async def on_dead(job, error):
        dead.append(error)

    assert await make_worker(maker, bad_input, on_dead).run_once() == "failed"
    job = await get(maker, job_id)
    assert job.status == "failed" and job.attempts == 1 and job.last_error == "file is corrupt"
    assert dead == ["file is corrupt"]


async def test_attempts_that_hang_are_cancelled_and_retried(maker, fast_retries, monkeypatch):
    monkeypatch.setattr(settings, "JOB_TIMEOUT_S", 0.05)
    job_id = await enqueue(maker)

    async def hangs(job):
        await asyncio.sleep(30)

    assert await make_worker(maker, hangs).run_once() == "queued"
    job = await get(maker, job_id)
    assert "timed out" in job.last_error and job.attempts == 1


async def test_a_failing_on_dead_hook_does_not_break_the_worker(maker):
    await enqueue(maker)
    await enqueue(maker)

    async def bad(job):
        raise PermanentJobError("x")

    async def explodes(job, error):
        raise RuntimeError("hook bug")

    w = make_worker(maker, bad, explodes)
    assert await w.run_until_idle() == 2  # both processed despite the hook failing


async def test_orphaned_running_jobs_are_reclaimed(maker, monkeypatch):
    monkeypatch.setattr(settings, "JOB_LOCK_TIMEOUT_S", 60.0)
    crashed, exhausted, alive = await enqueue(maker), await enqueue(maker), await enqueue(maker)
    old = datetime.now(UTC) - timedelta(hours=1)
    async with maker() as s:
        await s.execute(update(Job).where(Job.id == crashed).values(
            status="running", attempts=1, locked_at=old, locked_by="dead-worker"))
        await s.execute(update(Job).where(Job.id == exhausted).values(
            status="running", attempts=3, locked_at=old, locked_by="dead-worker"))
        await s.execute(update(Job).where(Job.id == alive).values(
            status="running", attempts=1, locked_at=datetime.now(UTC), locked_by="busy-worker"))
        await s.commit()
    async with maker() as s:
        assert await queue.reclaim_orphans(s) == 2
        await s.commit()
    assert (await get(maker, crashed)).status == "queued"
    assert (await get(maker, exhausted)).status == "dead"
    assert (await get(maker, alive)).status == "running"  # a live worker's job is untouched
    assert "worker lost" in (await get(maker, crashed)).last_error


async def test_run_forever_processes_jobs_and_stops_cleanly(maker, monkeypatch):
    monkeypatch.setattr(settings, "JOB_POLL_INTERVAL_S", 0.02)
    job_id = await enqueue(maker)
    w = make_worker(maker, ok)
    task = asyncio.create_task(w.run_forever())
    for _ in range(100):
        if (await get(maker, job_id)).status == "succeeded":
            break
        await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await get(maker, job_id)).status == "succeeded"


async def test_enqueue_is_transactional(maker):
    async with maker() as s:
        await queue.enqueue(s, KIND, {}, dedupe_key="rolled-back")
        await s.rollback()  # e.g. the document insert failed after the job was added
    async with maker() as s:
        n = (await s.execute(select(Job).where(Job.dedupe_key == "rolled-back"))).scalars().all()
    assert n == []


# --- ingestion on top of the queue ---------------------------------------------------


class FlakyEmbedder:
    """Fails the first N embed_texts calls (a provider outage), then works."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    async def embed_texts(self, texts):
        from tests.integration.test_upload_to_search import embed

        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("embedding provider unavailable")
        return [embed(t) for t in texts]

    async def embed_query(self, text_):
        from tests.integration.test_upload_to_search import embed

        return embed(text_)


@pytest.fixture
async def ingest(env, monkeypatch, fast_retries):  # noqa: F811
    _, orgs = env
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        h, kb = await onboard(c, orgs, uuid.uuid4(), f"jobs-{uuid.uuid4().hex[:6]}")
        yield {"c": c, "h": h, "kb": kb, "env": env, "monkeypatch": monkeypatch}


async def doc_state(w, doc_id):
    r = await w["c"].get(f"/api/v1/knowledge-bases/{w['kb']}/documents/{doc_id}", headers=w["h"])
    st = await w["c"].get(f"/api/v1/ingestion/documents/{doc_id}/status", headers=w["h"])
    return r.json(), st.json()


async def test_upload_creates_the_job_with_the_document_and_it_succeeds(ingest):
    doc_id = await upload(ingest["c"], ingest["h"], ingest["kb"], "a.pdf",
                          make_pdf({"T": "hello world text"}))
    doc, status = await doc_state(ingest, doc_id)
    assert doc["status"] == "ready"
    assert status["job_status"] == "succeeded" and status["attempts"] == 1
    assert status["progress_message"] is None


async def test_transient_provider_failure_is_retried_and_the_document_recovers(ingest):
    flaky = FlakyEmbedder(failures=1)
    ingest["monkeypatch"].setattr(
        "app.domains.ingestion.service.get_embedding_provider", lambda m: flaky
    )
    doc_id = await upload(ingest["c"], ingest["h"], ingest["kb"], "a.pdf",
                          make_pdf({"T": "hello world text"}))

    # First attempt failed transiently: the document is NOT failed, it is waiting to retry.
    doc, status = await doc_state(ingest, doc_id)
    assert doc["status"] != "failed", doc
    assert status["job_status"] == "queued" and status["attempts"] == 1
    assert status["progress_message"] == "retrying (attempt 2 of 3)"

    await asyncio.sleep(0.1)
    assert await ingestion_worker.run_until_idle() >= 1
    doc, status = await doc_state(ingest, doc_id)
    assert doc["status"] == "ready" and doc["chunk_count"] >= 1
    assert status["job_status"] == "succeeded" and status["attempts"] == 2
    assert flaky.calls == 2


async def test_exhausted_retries_fail_the_document_with_a_useful_message(ingest):
    ingest["monkeypatch"].setattr(
        "app.domains.ingestion.service.get_embedding_provider", lambda m: FlakyEmbedder(99)
    )
    doc_id = await upload(ingest["c"], ingest["h"], ingest["kb"], "a.pdf",
                          make_pdf({"T": "hello world text"}))
    for _ in range(4):
        await asyncio.sleep(0.3)
        await ingestion_worker.run_until_idle()
    doc, status = await doc_state(ingest, doc_id)
    assert doc["status"] == "failed"
    assert "embedding provider unavailable" in doc["error_message"]
    assert "after 3 attempts" in doc["error_message"]
    assert status["job_status"] == "dead" and status["attempts"] == 3


async def test_a_corrupt_file_fails_immediately_without_retries(ingest):
    doc_id = await upload(ingest["c"], ingest["h"], ingest["kb"], "bad.pdf",
                          b"%PDF-1.4\n" + b"\x01garbage" * 50)
    doc, status = await doc_state(ingest, doc_id)
    assert doc["status"] == "failed" and doc["error_message"]
    assert status["job_status"] == "failed" and status["attempts"] == 1  # not retried


async def test_asking_twice_while_a_job_is_active_does_not_start_a_second(ingest):
    doc_id = await upload(ingest["c"], ingest["h"], ingest["kb"], "a.pdf",
                          make_pdf({"T": "hello world text"}))
    maker = ingest["env"][0]
    org = uuid.UUID(ingest["h"]["X-Organization-Id"])
    async with maker() as s:
        first = await enqueue_ingestion(s, org, uuid.UUID(doc_id), reprocess=True)
        again = await enqueue_ingestion(s, org, uuid.UUID(doc_id), reprocess=True)
        await s.commit()
    assert first.id == again.id


async def test_reprocess_endpoint_runs_through_the_queue(ingest):
    doc_id = await upload(ingest["c"], ingest["h"], ingest["kb"], "a.pdf",
                          make_pdf({"T": "hello world text"}))
    r = await ingest["c"].post(f"/api/v1/ingestion/documents/{doc_id}/reprocess",
                               headers=ingest["h"])
    assert r.status_code == 202 and r.json()["job_id"]
    doc, status = await doc_state(ingest, doc_id)
    assert doc["status"] == "ready" and status["job_status"] == "succeeded"


async def test_stuck_document_recovery_leaves_documents_with_an_active_job_alone(ingest):
    maker = ingest["env"][0]
    org = uuid.UUID(ingest["h"]["X-Organization-Id"])
    waiting = await upload(ingest["c"], ingest["h"], ingest["kb"], "w.pdf",
                           make_pdf({"T": "waiting doc"}))
    orphan = await upload(ingest["c"], ingest["h"], ingest["kb"], "o.pdf",
                          make_pdf({"T": "orphan doc"}))
    long_ago = datetime.now(UTC) - timedelta(hours=3)
    async with maker() as s:
        # `waiting`: mid-ingestion, its job is queued (e.g. behind a backlog or retrying).
        await s.execute(text("UPDATE jobs SET status='queued', finished_at=NULL "
                             "WHERE dedupe_key = :k"), {"k": f"doc:{waiting}"})
        for d in (waiting, orphan):
            await s.execute(text("UPDATE documents SET status='embedding', updated_at=:t "
                                 "WHERE id = :i"), {"t": long_ago, "i": d})
        await s.commit()
    assert org
    assert await recover_stuck_ingestions(older_than_minutes=30) >= 1
    w_doc, _ = await doc_state(ingest, waiting)
    o_doc, _ = await doc_state(ingest, orphan)
    assert w_doc["status"] == "embedding"  # still owned by a live job
    assert o_doc["status"] == "failed"  # no job: genuinely orphaned


async def test_ingestion_job_kind_is_registered_with_the_shared_worker():
    assert INGEST_KIND in ingestion_worker.registry.kinds()
