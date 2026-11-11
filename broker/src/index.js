// Whoop token broker (Cloudflare Worker + KV).
//
// Holds the rotating OAuth refresh token and exposes read-only GET endpoints for `coach sync`:
//   /v2/recovery  /v2/activity/sleep  /v2/cycle  /v2/activity/workout   -> Whoop API v2, response passed through
//   /health                                                            -> whether Whoop is connected (no tokens)
//   /privacy                                                           -> public privacy page for the app registration
// Every data call needs the static key in the `X-Broker-Key` header (the coach's cloud environment injects it as
// a network secret). One-time setup in a browser: /auth/whoop/start?key=<BROKER_KEY>.
//
// Token rules (refresh tokens rotate: once used, the old one is dead):
// - The access token is cached in KV and reused until 5 min before expiry, so a daily sync refreshes at most once.
// - A refresh takes a short KV lock; the new tokens are written to KV before the access token is used.
// - A failed refresh is never retried blindly: the account is marked `needs_reauth` and calls return 502 until
//   the athlete re-runs /auth/whoop/start.
// The broker stores no Whoop data, only the tokens.

const WHOOP = {
  authorize: "https://api.prod.whoop.com/oauth/oauth2/auth",
  token: "https://api.prod.whoop.com/oauth/oauth2/token",
  api: "https://api.prod.whoop.com/developer",
  scope: "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement",
};
const WHOOP_PATHS = new Set(["/v2/recovery", "/v2/activity/sleep", "/v2/cycle", "/v2/activity/workout"]);
const WHOOP_PARAMS = ["start", "end", "nextToken", "limit"];
const TOKEN_KEY = "token:whoop";
const LOCK_KEY = "lock:whoop";
const PRIVACY = `Privacy policy - personal coaching token broker

This service is used by one person to connect their own Whoop account to their own private training log. It is not
offered to anyone else.

What it stores: the OAuth access and refresh tokens for that account, in this service's private key-value store. It
stores no health data: recovery, sleep, cycle and workout data is passed through on request to the account owner's
own coaching tool and is not kept here.

Sharing: nothing is sold or shared with third parties.

Deletion: revoking the app in Whoop, or deleting this service, removes access; the stored tokens can be deleted at
any time by the account owner.
`;
const EARLY_REFRESH_S = 300;
const LOCK_TTL_S = 60; // KV's minimum TTL

const json = (status, body) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json", "cache-control": "no-store" },
  });

class BrokerError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function sameKey(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || !b) return false;
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let diff = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) diff |= (x[i] ?? 0) ^ (y[i] ?? 0);
  return diff === 0;
}

function randomState() {
  const b = crypto.getRandomValues(new Uint8Array(24));
  return [...b].map((v) => v.toString(16).padStart(2, "0")).join("");
}

const redirectUri = (url) => `${url.origin}/auth/whoop/callback`;
const nowS = () => Math.floor(Date.now() / 1000);

// ---------- token exchange ----------

async function whoopExchange(env, params) {
  const res = await fetch(WHOOP.token, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      client_id: env.WHOOP_CLIENT_ID,
      client_secret: env.WHOOP_CLIENT_SECRET,
      ...params,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || !body.access_token) throw new BrokerError(502, `whoop token endpoint: HTTP ${res.status}`);
  return {
    access_token: body.access_token,
    refresh_token: body.refresh_token,
    expires_at: nowS() + (body.expires_in ?? 3600),
  };
}

// ---------- token store ----------

async function accessToken(env) {
  const rec = await env.TOKENS.get(TOKEN_KEY, "json");
  if (!rec) throw new BrokerError(502, "whoop not connected: open /auth/whoop/start");
  if (rec.needs_reauth) throw new BrokerError(502, "whoop needs re-authorization: open /auth/whoop/start");
  if (rec.expires_at - EARLY_REFRESH_S > nowS()) return rec.access_token;

  if (await env.TOKENS.get(LOCK_KEY)) throw new BrokerError(503, "whoop token refresh in progress, retry shortly");
  await env.TOKENS.put(LOCK_KEY, "1", { expirationTtl: LOCK_TTL_S });
  try {
    let fresh;
    try {
      fresh = await whoopExchange(env, { grant_type: "refresh_token", refresh_token: rec.refresh_token, scope: "offline" });
    } catch (e) {
      // The old refresh token may already be spent: never retry it; ask for a re-authorization instead.
      await env.TOKENS.put(TOKEN_KEY, JSON.stringify({ ...rec, needs_reauth: true, error: String(e.message) }));
      throw e;
    }
    // Rotation: keep the new refresh token (fall back to the old one only if Whoop didn't send one).
    const next = { ...fresh, refresh_token: fresh.refresh_token || rec.refresh_token, updated: new Date().toISOString() };
    await env.TOKENS.put(TOKEN_KEY, JSON.stringify(next));
    return next.access_token;
  } finally {
    await env.TOKENS.delete(LOCK_KEY);
  }
}

// ---------- routes ----------

async function handleAuth(env, url, step) {
  if (step === "start") {
    if (!sameKey(url.searchParams.get("key"), env.BROKER_KEY)) return json(401, { error: "bad key" });
    const state = randomState();
    await env.TOKENS.put(`state:${state}`, "whoop", { expirationTtl: 600 });
    const q = new URLSearchParams({
      response_type: "code",
      client_id: env.WHOOP_CLIENT_ID,
      redirect_uri: redirectUri(url),
      scope: WHOOP.scope,
      state,
    });
    return Response.redirect(`${WHOOP.authorize}?${q}`, 302);
  }
  // callback
  const state = url.searchParams.get("state") || "";
  const code = url.searchParams.get("code");
  if (url.searchParams.get("error")) return json(400, { error: `authorization refused: ${url.searchParams.get("error")}` });
  if (!code || (await env.TOKENS.get(`state:${state}`)) !== "whoop") return json(400, { error: "invalid or expired state" });
  await env.TOKENS.delete(`state:${state}`);
  const rec = await whoopExchange(env, { grant_type: "authorization_code", code, redirect_uri: redirectUri(url) });
  await env.TOKENS.put(TOKEN_KEY, JSON.stringify({ ...rec, updated: new Date().toISOString() }));
  return new Response("whoop connected. You can close this tab.", { headers: { "content-type": "text/plain" } });
}

async function route(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const auth = path.match(/^\/auth\/whoop\/(start|callback)$/);
  // Developer dashboards may probe the callback URL when it is registered: answer HEAD / a bare GET with 200.
  if (auth && auth[1] === "callback" && (request.method === "HEAD" || !url.searchParams.has("state")))
    return new Response(request.method === "HEAD" ? null : "callback ready", { status: 200 });
  if (request.method !== "GET") return json(405, { error: "read-only broker: GET only" });
  if (path === "/privacy") return new Response(PRIVACY, { headers: { "content-type": "text/plain; charset=utf-8" } });
  if (auth) return handleAuth(env, url, auth[1]);

  if (!sameKey(request.headers.get("X-Broker-Key"), env.BROKER_KEY)) return json(401, { error: "bad key" });

  if (path === "/health") {
    const rec = await env.TOKENS.get(TOKEN_KEY, "json");
    return json(200, {
      whoop: rec
        ? { connected: !rec.needs_reauth, needs_reauth: !!rec.needs_reauth, access_expires_at: rec.expires_at, updated: rec.updated }
        : { connected: false },
    });
  }
  if (WHOOP_PATHS.has(path)) {
    const token = await accessToken(env);
    const q = new URLSearchParams();
    for (const k of WHOOP_PARAMS) if (url.searchParams.has(k)) q.set(k, url.searchParams.get(k));
    if (!q.has("limit")) q.set("limit", "25");
    const res = await fetch(`${WHOOP.api}${path}?${q}`, { headers: { authorization: `Bearer ${token}` } });
    const text = await res.text();
    if (!res.ok) throw new BrokerError(502, `whoop: upstream HTTP ${res.status}`);
    return new Response(text, { headers: { "content-type": "application/json", "cache-control": "no-store" } });
  }
  return json(404, { error: "not found" });
}

export default {
  async fetch(request, env) {
    try {
      return await route(request, env);
    } catch (e) {
      if (e instanceof BrokerError) return json(e.status, { error: e.message });
      return json(500, { error: "broker error" });
    }
  },
};
