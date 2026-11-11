# Token broker (Whoop API v2 + Withings)

A small Cloudflare Worker that holds the rotating OAuth refresh tokens in KV and gives `coach sync` read-only
endpoints behind a static key. Free plan is enough (a daily sync is a few dozen requests).

| Endpoint | Upstream |
|---|---|
| `GET /v2/recovery`, `/v2/activity/sleep`, `/v2/cycle`, `/v2/activity/workout` | Whoop API v2 (`start`, `end`, `nextToken` passed through, `limit=25`) |
| `GET /withings/measure` | Withings `measure?action=getmeas&category=1` (`meastypes`, `startdate`, `enddate`) |
| `GET /health` | which providers are connected (never token values) |
| `GET /auth/<whoop\|withings>/start?key=<BROKER_KEY>` | one-time browser sign-in (OAuth), stores the tokens |

Everything except `/auth/*` needs the `X-Broker-Key` header. Non-GET requests and any other path are refused.
A failed refresh is never retried (the old refresh token may already be spent): the provider is marked
`needs_reauth`, the coach's sync reports Whoop offline (the daily run carries on with readiness unscored), and you
re-run `/auth/<provider>/start`.

Tests (no dependencies): `cd broker && npm test`.

## 1. Pick the broker URL

Your Worker will live at `https://coach-broker.<your-subdomain>.workers.dev`. Find `<your-subdomain>` in the
Cloudflare dashboard -> Workers & Pages (right-hand side, "Subdomain"); set one if you have none. The two callback
URLs below use it.

## 2. Register the apps

**Whoop** (developer-dashboard.whoop.com, sign in with your Whoop account):
1. Create a team if asked, then **Create App**.
2. Name: anything (e.g. "Coach broker"). Contact email: yours. Privacy policy URL: any page you control (required field).
3. Redirect URL: `https://coach-broker.<your-subdomain>.workers.dev/auth/whoop/callback`
4. Scopes: `read:recovery`, `read:cycles`, `read:sleep`, `read:workout`, `read:profile`, `read:body_measurement`.
   (`offline`, which returns the refresh token, is requested by the broker at sign-in.)
5. Copy the **Client ID** and **Client Secret** (they go into Cloudflare in step 3, nowhere else).

**Withings** (developer.withings.com -> Developer Dashboard, sign in with your Withings account):
1. **Create an application** -> Public API integration. Target environment: Development is fine for one user.
2. Application name/description: anything. Callback URL:
   `https://coach-broker.<your-subdomain>.workers.dev/auth/withings/callback`
   (deploy step 3 first if the dashboard wants the URL to answer; it does once deployed).
3. Copy the **Client ID** and **Consumer Secret**.

Check when registering: the broker uses Whoop `https://api.prod.whoop.com/oauth/oauth2/{auth,token}` and
`/developer/v2/...`, and Withings `https://account.withings.com/oauth2_user/authorize2`,
`https://wbsapi.withings.net/v2/oauth2` (`action=requesttoken`) and `/measure` (scope `user.metrics`). If either
developer portal shows different URLs, tell the coach; they are constants at the top of `src/index.js`.

## 3. Deploy (from a computer with Node.js 18+)

```bash
git clone <this repo> && cd coach/broker
npx wrangler login                                  # opens Cloudflare in the browser
npx wrangler kv namespace create TOKENS             # prints an id: paste it into wrangler.toml
openssl rand -hex 32                                # this is BROKER_KEY: keep it in your password manager
npx wrangler secret put BROKER_KEY                  # paste it
npx wrangler secret put WHOOP_CLIENT_ID
npx wrangler secret put WHOOP_CLIENT_SECRET
npx wrangler secret put WITHINGS_CLIENT_ID
npx wrangler secret put WITHINGS_CLIENT_SECRET
npx wrangler deploy                                 # prints https://coach-broker.<subdomain>.workers.dev
```

Secrets go only into Cloudflare (`wrangler secret put` prompts for them); never into `wrangler.toml`, chat or the repo.
Commit the KV namespace id in `wrangler.toml` (it is not a secret).

## 4. Connect your accounts (once, in a browser)

Open, signed in to each service:
- `https://coach-broker.<subdomain>.workers.dev/auth/whoop/start?key=<BROKER_KEY>` -> approve -> "whoop connected"
- `https://coach-broker.<subdomain>.workers.dev/auth/withings/start?key=<BROKER_KEY>` -> approve -> "withings connected"

(The key in that URL ends up in your browser history; clear it afterwards if that matters to you.)

## 5. Point the coach at it

Tell the coach the Worker URL. It will add the host to the `coach` cloud environment, set `WHOOP_BROKER_URL`
(not secret), and ask for `BROKER_KEY` through the secure credential form (sent as the `X-Broker-Key` header by the
environment's proxy). Then `coach sync --pretty` should show non-zero `whoop_daily` and no Whoop/Withings errors.

## Limits

KV is not transactional: the refresh lock is a short-lived KV key, enough for one daily sync but not for many
concurrent callers. Keep the broker for the coach only. If a re-authorization is ever needed, `/health` shows
`needs_reauth: true`.
