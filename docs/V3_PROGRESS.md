# V3 progress (branch `v3`)

Work for V3 (Corrective + Agentic RAG, see `RAGIX_ROADMAP.md`) happens on branch `v3`,
cut from `main`. Merge to `main` when the human-handoff feature is complete.

## Done (committed on `v3`)

Human handoff / escalation, backend complete and tested:
- `backend/app/models/escalation.py` + migration `supabase/migrations/20261027120000_escalations.sql`
  (RLS: owners/admins only; at most one open escalation per conversation).
  **The migration must be applied to Supabase before deploying this branch.**
- `backend/app/domains/escalation/`
  - `settings.py`: per-org rules in `organizations.settings["escalation"]`
    (enabled, triggers `user_request|frustration|abstain`, emails, Slack webhook URL,
    customer message). Validated on save and on use; Slack URL must be a
    `https://hooks.slack.com/services/` webhook. Disabled by default.
  - `detector.py`: "asks for a human" and "frustrated" judged by Jev (two Nouls, one
    request) with rules as fallback when Jev is off, failing, or unsure (0.3-0.7);
    `abstain` reuses the existing abstention decision. Config: `ESCALATION_USE_JEV`.
  - `service.py`: `maybe_escalate()` creates the escalation and enqueues an
    `escalation_notify` job in the same transaction; never fails the chat turn.
  - `notify.py`: job handler sending Slack + email (Resend), HTML-escaped transcript,
    link to `/dashboard/escalations?id=...`; per-channel delivery result stored; retried
    when every configured channel fails.
  - `router.py` (`/api/v1/escalations`, owners/admins): `GET/PUT /settings`, `GET /`,
    `GET /{id}` (with transcript), `POST /{id}/resolve`.
- Chat integration (`domains/chat/service.py`): both normal and streaming paths call
  `maybe_escalate()` after saving the answer; streaming emits a `{"type": "handoff", ...}`
  event after `done`; the handoff is also stored in the message's `retrieval_metadata`.
- Frontend: `handoff` stream event handled in `hooks/useChat.ts`, notice rendered in
  `components/chat/MessageBubble.tsx` (also restored when reopening a conversation);
  `api.put`, `Handoff`/`EscalationSettings`/`EscalationSummary`/`EscalationDetail` types in
  `lib/types.ts`.
- Tests: `tests/test_escalation.py` (unit) and `tests/integration/test_escalation_flow.py`
  (end to end against Postgres). Full suite: 715 passed.

## Remaining for human handoff

1. Settings UI: a "Human handoff" section in `apps/web/src/app/dashboard/settings/page.tsx`
   (owners/admins) using `GET/PUT /api/v1/escalations/settings`: enable toggle, trigger
   checkboxes, notification emails, Slack webhook URL, customer message.
   Note: the web-search toggle PATCHes org settings with a merge
   (`{**org.settings, **data.settings}`), so it does not wipe `escalation`.
2. Inbox page: `apps/web/src/app/dashboard/escalations/page.tsx` (+ `layout.tsx` with
   metadata, like `debug/`): list open/resolved, detail with transcript and delivery
   status, Resolve button; handle the `?id=` query param used by notification links.
   Add an `adminOnly` "Escalations" item to `NAV_ITEMS` in `components/layout/Sidebar.tsx`.
3. Run `npm run lint` and `npm run build` in `apps/web`.
4. Roadmap: mark "Human escalation" built in `RAGIX_ROADMAP.md` (V3 section).

## Remaining V3 items (roadmap), suggested order

1. Formal memory/retention guardrails (conversation data lifecycle, retention limits).
2. Answer reproducibility: store pinned model version and a prompt-template hash per trace.
3. Action tiering + human-approval workflow for write-capable agent tools.
4. Deeper prompt-injection defenses and security testing.
5. Multi-hop retrieval, Self-RAG-style reflection, knowledge-strip decomposition.
6. Agent workflow/report generation; Redis agent/workflow state.
