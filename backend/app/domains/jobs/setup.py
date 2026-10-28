"""Wiring: the handler registry and the process-wide worker."""

from app.domains.escalation.notify import escalation_notify_handler
from app.domains.escalation.service import NOTIFY_KIND
from app.domains.evals.jobs import eval_handler
from app.domains.evals.service import EVAL_KIND
from app.domains.ingestion.jobs import INGEST_KIND, ingestion_handler
from app.domains.jobs import sessions
from app.domains.jobs.worker import HandlerRegistry, Worker

registry = HandlerRegistry()
registry.register(INGEST_KIND, ingestion_handler)
registry.register(EVAL_KIND, eval_handler)
registry.register(NOTIFY_KIND, escalation_notify_handler)


def _session():
    return sessions.new_session()  # looked up per call so tests can patch the source


worker = Worker(_session, registry)
