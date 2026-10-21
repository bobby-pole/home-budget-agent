# Lidl Plus local feasibility result (#255)

Decision: **CONDITIONAL GO for local research only** (2026-10-21).

The owner reports interactive login, token exchange/refresh and 25/25 real receipts
mapping with zero sum difference. The currently retained local report contains
3/3 matching receipts. Provider responses in regression tests are mocked; they
do not prove target-VPS access, session endurance or final browser/mobile UX.

Canonical ADR: [hba-project-context](https://github.com/bobby-pole/hba-project-context/blob/main/strategy/poc-lidl-feasibility-report.md).

Outstanding deployment/endurance/login gate: [#264](https://github.com/bobby-pole/home-budget-agent/issues/264),
blocking [#260](https://github.com/bobby-pole/home-budget-agent/issues/260) and the family pilot.

The native-client access flow is unofficial. No provider-issued Rachownik client
registration, long-term session lifetime or provider approval is established.
Scheduling, concurrency-safe provenance and money precision remain #257, #193 and
#256 respectively. Automatic Biedronka integration needs separate evidence.

Tokens, encryption keys and raw purchase reports are excluded from this repository.
See [security/key management](SECURITY_KEY_MANAGEMENT.md) for the local session and
explicit per-user connection binding. Never copy the local `.env` or `scratch/`
contents into a pull request or public diagnostic bundle.
