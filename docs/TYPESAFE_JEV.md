# Using Jev (TypeSafe) in Ragix

Jev is TypeSafe's first public "System One" model: it answers **typed questions** about state
the application sends (text, images, app data) with **calibrated probabilities**. Question
types: Choice (pick among options), Noul (probability a statement is true), Score (levels you
describe), Box (locate something in an image). Docs: https://docs.typesafe.ai/llms.txt
(append `.md` to any page path for Markdown). API: https://api.typesafe.ai/openapi.json.

## Installed tooling (Claude Code)

```bash
claude plugin marketplace add typesafe-ai/skills
claude plugin install typesafe@typesafe-ai
# update
claude plugin marketplace update typesafe-ai
claude plugin update typesafe@typesafe-ai      # then restart or /reload-plugins
```

Invoke with `/typesafe:typesafe-ai`, or say "use the TypeSafe skill". Other agents:
`npx skills add typesafe-ai/skills --skill typesafe-ai`. Use one install method only. If the
agent invents request/response fields, the skill is stale: update it. The plugin is installed
at user scope, so a fresh cloud session must re-run the two install commands.

## Rules for any Jev code in this repo

1. **Judgments from Jev, decisions in code.** Ask Jev small, atomic questions ("does the
   passage state the refund window?"), then combine answers with thresholds/boolean logic in
   Python. Never ask "should we answer?" or "is the evidence sufficient?" directly.
2. **One judgment per question**, concrete and observable, phrased so *yes* is the true answer.
   Avoid "or"/"and" inside a question; avoid LLM-style preambles.
3. **Keep every question, option, criterion and threshold in ONE module** so humans can audit
   them. (Suggested: `backend/app/domains/retrieval/decisions/jev_questions.py`.)
4. **State = what a person would look at**: named fields, the question + the selected passages
   with titles, not raw IDs or the whole corpus. Include only relevant fields.
5. **Questions are answered independently**; put shared context in the state, referenced by path.
6. **Errors are errors, not answers.** A failed Jev call must never be treated as "no". In
   Ragix the Jev DecisionProvider falls back to the rules verdict and logs `jev_decision_failed`.
7. **API key stays server-side** (`TYPESAFE_API_KEY` env / `JEV_API_KEY` setting). Log the exact
   request payload for debugging, never the key.
8. Probe the live API with cheap representative, hard and negative cases before integrating;
   tune thresholds from results (too high → false negatives, too low → false positives). Use the
   highest-confidence option for Choice instead of thresholds when you just want the best one.

## Where Jev fits in Ragix

| Ragix area | Candidate Jev questions (Noul) | Decision stays in code |
|---|---|---|
| Evidence sufficiency (`retrieval/decisions/`) | "Do the passages state the requested fact?" per required term/requirement | coverage threshold, freshness/authority rules |
| Human escalation (V3) | "Does the user ask for a human?", "Does the user sound frustrated?" | trigger table + per-org rules |
| Query routing | "Does the question compare two things?", "Does it need current data?" | route selection |
| Claim verification | "Does passage N support claim M?" | rewrite-or-abstain policy |
| Conflict detection | "Do these two passages disagree on <fact>?" | resolver precedence |

## Current code state (read before changing it)

`backend/app/domains/retrieval/decisions/jev_provider.py` implements `DecisionProvider` for
`DECISION_PROVIDER=jev` using a **placeholder JSON contract written before the real API was
known**. It must be reworked to the real TypeSafe API (decompose sufficiency into Noul
questions, combine in code) per the rules above. Settings: `JEV_ENDPOINT`, `JEV_API_KEY`,
`JEV_TIMEOUT_S`. Fetch the current request/response schema from the OpenAPI spec or the
installed SDK (Python/JS pages under https://docs.typesafe.ai/go/) — do not guess fields.
