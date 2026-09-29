"""Wiring: the handler registry and the process-wide worker."""

from app.domains.ingestion.jobs import INGEST_KIND, ingestion_handler
from app.domains.jobs import sessions
from app.domains.jobs.worker import HandlerRegistry, Worker

registry = HandlerRegistry()
registry.register(INGEST_KIND, ingestion_handler)


def _session():
    return sessions.new_session()  # looked up per call so tests can patch the source


worker = Worker(_session, registry)
