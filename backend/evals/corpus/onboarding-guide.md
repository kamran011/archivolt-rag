# Onboarding Guide

**Version 3.2 — 2026-03-01**

## Welcome

This guide walks new team members through account setup, tool access, and the
first two weeks of onboarding at Acme Corp.

## Day 1: Account Setup

1. **Email and SSO** — IT will provision your corporate email. Use it to log in to
   all internal tools via Okta SSO. Do not use personal email for work systems.

2. **Laptop setup** — Run the bootstrap script at `https://it.acme.internal/setup`.
   It installs Homebrew, Git, Docker, and standard dev tooling. Estimated time: 20 minutes.

3. **Slack** — Join the #welcome and #engineering channels. Your manager will add
   you to project-specific channels by end of day.

4. **1Password** — Request access from IT. Store all credentials here; no passwords
   in Slack or plaintext files.

## Week 1: Learn the Codebase

- Clone the main repo: `git clone git@github.com:acme/platform.git`
- Read `docs/architecture.md` and `docs/data-model.md`
- Run the test suite with `make test` to confirm your environment is working
- Complete the security training module in the Learning Portal (mandatory, ~90 min)

## Week 2: First Contribution

- Pick a "good first issue" from the `#onboarding-issues` Jira project
- Open a PR against `main`; at least one approval is required to merge
- Join the weekly engineering all-hands (Thursdays at 10 AM PT)

## Probationary Period

The first **90 days** are a mutual evaluation period. Formal feedback is given at
the 30-, 60-, and 90-day marks by your direct manager.

## Key Contacts

| Role | Name | Slack |
|------|------|-------|
| Engineering Manager | Jordan Lee | @jordan |
| HR Business Partner | Taylor Kim | @taylor |
| IT Helpdesk | — | #it-help |
