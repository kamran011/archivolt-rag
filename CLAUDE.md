# Ragix – notes for Claude

- Roadmap and versioning rules: `RAGIX_ROADMAP.md` (implement the current version only).
- Backend tests: `cd backend && uv run pytest` with the dummy env vars from
  `.github/workflows/ci.yml`; tiktoken needs network on first import.
- Using Jev / TypeSafe (typed probabilistic judgments): read `docs/TYPESAFE_JEV.md` first and
  use the `/typesafe:typesafe-ai` skill. Do not guess Jev API fields; check the live docs.
