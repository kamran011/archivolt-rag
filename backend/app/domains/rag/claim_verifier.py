import json
from dataclasses import dataclass, field

import structlog

from app.domains.rag.prompts import CLAIM_VERIFICATION_PROMPT
from app.domains.rag.schemas import ClaimVerification, VerificationStatus
from app.domains.retrieval.evidence import ContextAssembler
from app.domains.retrieval.schemas import RetrievedChunk
from app.providers.llm.base import LLMProvider

logger = structlog.get_logger()

_VALID_STATUS = {"supported", "partial", "unsupported"}


@dataclass
class VerificationOutcome:
    """Result of verifying an answer. `status` is 'unverified' when the verifier itself
    failed (LLM error / unparseable output) — callers must not treat that as a pass."""

    status: VerificationStatus
    claims: list[ClaimVerification] = field(default_factory=list)

    @property
    def unsupported_claims(self) -> list[ClaimVerification]:
        return [c for c in self.claims if c.status != "supported"]

    @property
    def supported_claims(self) -> list[ClaimVerification]:
        return [c for c in self.claims if c.status == "supported"]


def summarize_status(claims: list[ClaimVerification]) -> VerificationStatus:
    if not claims:
        return "unverified"
    supported = sum(1 for c in claims if c.status == "supported")
    if supported == len(claims):
        return "verified"
    if supported == 0 and not any(c.status == "partial" for c in claims):
        return "unsupported"
    return "partial"


class ClaimVerifier:
    async def verify(
        self,
        answer: str,
        chunks: list[RetrievedChunk],
        llm: LLMProvider,
    ) -> VerificationOutcome:
        if not chunks or not answer.strip():
            return VerificationOutcome(status="skipped")

        sources_text = ContextAssembler.format_with_citations(chunks)
        prompt = CLAIM_VERIFICATION_PROMPT.format(answer=answer, sources=sources_text)

        try:
            response = await llm.generate(
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=1024,
            )
        except Exception as e:
            logger.warning("claim_verification_failed", error=str(e))
            return VerificationOutcome(status="unverified")

        claims = self._parse_verifications(response.content)
        return VerificationOutcome(status=summarize_status(claims), claims=claims)

    async def verify_claims(
        self,
        answer: str,
        chunks: list[RetrievedChunk],
        llm: LLMProvider,
    ) -> list[ClaimVerification]:
        """Claims only. Prefer verify(), which distinguishes 'verifier failed' from
        'no claims'."""
        return (await self.verify(answer, chunks, llm)).claims

    def _parse_verifications(self, raw: str) -> list[ClaimVerification]:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                data = next(iter(data.values())) if data else []

            verifications = []
            for item in data:
                status = item.get("status")
                if status not in _VALID_STATUS:
                    # Older prompt shape: boolean "supported".
                    status = "supported" if bool(item["supported"]) else "unsupported"
                verifications.append(
                    ClaimVerification(
                        claim=item["claim"],
                        supported=status == "supported",
                        status=status,
                        supporting_sources=[int(s) for s in item.get("supporting_sources", [])],
                        confidence=float(item.get("confidence", 0.5)),
                    )
                )
            return verifications
        except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError) as e:
            logger.warning("claim_verification_parse_failed", error=str(e), raw=raw[:200])
            return []


claim_verifier = ClaimVerifier()
