# Token broker (Whoop API v2)

A small Cloudflare Worker that holds Whoop's rotating OAuth refresh token in KV and gives `coach sync` read-only
endpoints behind a static key. The free plan is enough (a daily sync is a few dozen requests). It stores tokens only,
never Whoop data; the coach doesn't commit Whoop data either (`docs/DECISIONS.md` 73).

| Endpoint | Upstream |
|---|---|
| `GET /v2/recovery`, `/v2/activity/sleep`, `/v2/cycle`, `/v2/activity/workout` | Whoop API v2 (`start`, `end`, `nextToken` passed through, `limit=25`) |
| `GET /health` | whether Whoop is connected (never token values) |
| `GET /privacy` | public privacy page for the app registration |
| `GET /auth/whoop/start?key=<BROKER_KEY>` | one-time browser sign-in (OAuth), stores the tokens |

Everything except `/auth/*` and `/privacy` needs the `X-Broker-Key` header. Non-GET requests and any other path are
refused. A failed refresh is never retried (the old refresh token may already be spent): the account is marked
`needs_reauth`, the coach's sync reports Whoop offline (the daily run carries on with readiness unscored), and you
re-run `/auth/whoop/start`.

Tests (no dependencies): `cd broker && npm test`.

Read WHOOP's API Terms before registering: they restrict permanent copies of WHOOP data and its use to develop AI
applications. The coach keeps no permanent copy; ask WHOOP (apisupport@whoop.com) about the AI question.

## 1. Pick the broker URL
Cloudflare dashboard -> **Workers & Pages**: choose your `workers.dev` subdomain if asked. The broker will live at
`https://coach-broker.<subdomain>.workers.dev`.

## 2. Create the Worker and its KV store (dashboard, works on an iPad)
1. **Workers & Pages -> Create -> Create Worker** ("Start with Hello World"), name `coach-broker`, **Deploy**.
2. **Edit code**: replace everything with `broker/src/index.js` from this repo (GitHub -> file -> **Raw** -> copy),
   then **Deploy**.
3. **Storage & Databases -> KV -> Create namespace** `coach-broker-tokens`.
4. Worker -> **Settings -> Bindings -> Add -> KV namespace**: variable name exactly `TOKENS`, that namespace.
5. Make the broker key: a 64-character random password from your password manager, **letters and digits only**.
   Worker -> **Settings -> Variables and Secrets -> Add**, type **Secret**, name `BROKER_KEY`.
6. Check `https://coach-broker.<subdomain>.workers.dev/privacy` shows the privacy text.

(Command-line alternative from a computer: `npx wrangler login`, `npx wrangler kv namespace create TOKENS` and paste
the id into `wrangler.toml`, `npx wrangler secret put <NAME>` for each secret, `npx wrangler deploy`.)

## 3. Register the Whoop app
developer-dashboard.whoop.com (sign in with your Whoop account) -> **Create App**:
- Name: anything (e.g. "Coach broker"). Contact email: yours.
- Privacy policy URL: `https://coach-broker.<subdomain>.workers.dev/privacy`
- Redirect URL: `https://coach-broker.<subdomain>.workers.dev/auth/whoop/callback`
- Scopes: `read:recovery`, `read:cycles`, `read:sleep`, `read:workout`, `read:profile`, `read:body_measurement`
  (`offline`, which returns the refresh token, is requested by the broker at sign-in).

Copy the **Client ID** and **Client Secret** into the Worker as secrets `WHOOP_CLIENT_ID` and `WHOOP_CLIENT_SECRET`
(nowhere else). The broker uses `https://api.prod.whoop.com/oauth/oauth2/{auth,token}` and `/developer/v2/...`; if
the developer portal shows different URLs, tell the coach (they are constants at the top of `src/index.js`).

## 4. Connect your account (once, in a browser)
Open `https://coach-broker.<subdomain>.workers.dev/auth/whoop/start?key=<BROKER_KEY>`, approve, and you should see
"whoop connected". (The key in that URL lands in your browser history; clear it afterwards if that matters to you.)

## 5. Point the coach at it
Tell the coach the Worker URL (never the key). It adds the host to the `coach` cloud environment, sets
`WHOOP_BROKER_URL` (not secret), and asks for `BROKER_KEY` through the secure credential form (sent as the
`X-Broker-Key` header by the environment's proxy). Then `coach sync --pretty` should show `whoop_daily` around 75 on
the first run and no Whoop errors.

## Limits
KV is not transactional: the refresh lock is a short-lived KV key, enough for one daily caller but not for many
concurrent ones. Keep the broker for the coach only. If a re-authorization is ever needed, `/health` shows
`needs_reauth: true`.
