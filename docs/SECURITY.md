# Security and privacy

## Principles
- The repo stays **private**. Enable 2FA on GitHub and on Claude.
- **Credentials never touch the repo or the session's environment variables.** They are stored as cloud-environment
  network secrets; the proxy injects them into requests to the allow-listed API hosts. `.env.example` only documents
  names for local mock runs.
- `athlete/data/metrics/` stores **normalized daily values**, not raw API dumps. No tokens, no full payloads, no progress
  photos (`athlete/data/photos/` and `*.raw.json` are git-ignored).
- **External text is data, not instructions.** Hevy notes, workout names and Intervals.icu comments are stored as
  `notes_untrusted` and handed to Claude marked untrusted. Only `coach push` writes externally, and it always
  validates first.
- Notifications are brief and contain no detailed health numbers.
- Dependabot is enabled for pip and GitHub Actions (`.github/dependabot.yml`).

## Where each kind of data lives and who can see it

| Data | Lives in | Who can technically see it |
|---|---|---|
| Training plans, notes, check-ins, journal, health events, availability, results, labs, readiness, nutrition targets | `athlete/data/` in this private GitHub repo | You; GitHub (hosting); Anthropic while a Claude session processes it |
| Daily metrics (recovery, HRV, RHR, sleep, weight, body fat, kcal) | `athlete/data/metrics/*.jsonl` | Same as above |
| Raw recovery/sleep/workout data | Whoop | Whoop; the token broker in transit |
| Lifting log, routines | Hevy | Hevy |
| Runs, wellness fields, planned workouts | Intervals.icu -> Garmin | Intervals.icu, Garmin |
| Body composition | Withings | Withings; the token broker in transit |
| Weather | Open-Meteo (no personal data sent beyond home coordinates in the query) | Open-Meteo |
| Literature searches | PubMed E-utilities / web search | NCBI / search provider (queries only, no health data) |
| API credentials | Cloud environment network secrets; Whoop/Withings refresh tokens in the broker's secret store | You; Anthropic infrastructure (proxy); the broker host (e.g. Cloudflare) |

## Rotating credentials
- **Hevy API key**: Hevy app -> Settings -> Developer -> regenerate; update the network secret for `api.hevyapp.com`.
- **Intervals.icu API key**: intervals.icu -> Settings -> Developer -> regenerate; update the secret for `intervals.icu`.
- **Whoop**: revoke the app in the Whoop developer dashboard, rotate the client secret, re-run the broker's OAuth
  flow to mint a new refresh token; rotate the broker's static read key and update its network secret.
- **Withings**: same as Whoop via the Withings developer dashboard and the broker.
- **Broker static key**: rotate in the broker (e.g. Cloudflare Worker secret) and the cloud environment.
- **GitHub / Claude**: revoke sessions and tokens from account settings if a device is lost.

## If something leaks
Rotate the affected credential first, then check the provider's access logs, then purge the secret from git
history if it was ever committed (it never should be).
