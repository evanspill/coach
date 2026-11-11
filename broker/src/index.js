// Whoop + Withings token broker (Cloudflare Worker + KV).
//
// Holds the rotating OAuth refresh tokens and exposes read-only GET endpoints for `coach sync`:
//   /v2/recovery  /v2/activity/sleep  /v2/cycle  /v2/activity/workout   -> Whoop API v2, response passed through
//   /withings/measure                                                  -> Withings getmeas, response passed through
//   /health                                                            -> which providers are connected (no tokens)
// Every data call needs the static key in the `X-Broker-Key` header (the coach's cloud environment injects it as
// a network secret). One-time setup in a browser: /auth/<whoop|withings>/start?key=<BROKER_KEY>.
//
// Token rules (refresh tokens rotate: once used, the old one is dead):
// - The access token is cached in KV and reused until 5 min before expiry, so a daily sync refreshes at most once.
// - A refresh takes a short KV lock; the new tokens are written to KV before the access token is used.
// - A failed refresh is never retried blindly: the provider is marked `needs_reauth` and calls return 502 until
//   the athlete re-runs /auth/<provider>/start.

const WHOOP = {
  authorize: "https://api.prod.whoop.com/oauth/oauth2/auth",
  token: "https://api.prod.whoop.com/oauth/oauth2/token",
  api: "https://api.prod.whoop.com/developer",
  scope: "offline read:recovery read:cycles read:sleep read:workout read:profile read:body_measurement",
};
const WITHINGS = {
  authorize: "https://account.withings.com/oauth2_user/authorize2",
  token: "https://wbsapi.withings.net/v2/oauth2",
  measure: "https://wbsapi.withings.net/measure",
  scope: "user.metrics",
};
const WHOOP_PATHS = new Set(["/v2/recovery", "/v2/activity/sleep", "/v2/cycle", "/v2/activity/workout"]);
const WHOOP_PARAMS = ["start", "end", "nextToken", "limit"];
const WITHINGS_PARAMS = ["meastypes", "startdate", "enddate", "lastupdate", "category"];
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

function redirectUri(url, provider) {
  return `${url.origin}/auth/${provider}/callback`;
}

const nowS = () => Math.floor(Date.now() / 1000);

// ---------- provider token exchanges ----------

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
  return { access_token: body.access_token, refresh_token: body.refresh_token, expires_at: nowS() + (body.expires_in ?? 3600) };
}

async function withingsExchange(env, params) {
  const res = await fetch(WITHINGS.token, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({
      action: "requesttoken",
      client_id: env.WITHINGS_CLIENT_ID,
      client_secret: env.WITHINGS_CLIENT_SECRET,
      ...params,
    }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.status !== 0 || !body.body?.access_token)
    throw new BrokerError(502, `withings token endpoint: status ${body.status ?? res.status}`);
  const b = body.body;
  return { access_token: b.access_token, refresh_token: b.refresh_token, expires_at: nowS() + (b.expires_in ?? 10800) };
}

const PROVIDERS = {
  whoop: {
    authorizeUrl: (env, url, state) =>
      `${WHOOP.authorize}?${new URLSearchParams({
        response_type: "code",
        client_id: env.WHOOP_CLIENT_ID,
        redirect_uri: redirectUri(url, "whoop"),
        scope: WHOOP.scope,
        state,
      })}`,
    fromCode: (env, url, code) =>
      whoopExchange(env, { grant_type: "authorization_code", code, redirect_uri: redirectUri(url, "whoop") }),
    refresh: (env, rt) => whoopExchange(env, { grant_type: "refresh_token", refresh_token: rt, scope: "offline" }),
  },
  withings: {
    authorizeUrl: (env, url, state) =>
      `${WITHINGS.authorize}?${new URLSearchParams({
        response_type: "code",
        client_id: env.WITHINGS_CLIENT_ID,
        redirect_uri: redirectUri(url, "withings"),
        scope: WITHINGS.scope,
        state,
      })}`,
    fromCode: (env, url, code) =>
      withingsExchange(env, { grant_type: "authorization_code", code, redirect_uri: redirectUri(url, "withings") }),
    refresh: (env, rt) => withingsExchange(env, { grant_type: "refresh_token", refresh_token: rt }),
  },
};

// ---------- token store ----------

async function accessToken(env, provider) {
  const rec = await env.TOKENS.get(`token:${provider}`, "json");
  if (!rec) throw new BrokerError(502, `${provider} not connected: open /auth/${provider}/start`);
  if (rec.needs_reauth) throw new BrokerError(502, `${provider} needs re-authorization: open /auth/${provider}/start`);
  if (rec.expires_at - EARLY_REFRESH_S > nowS()) return rec.access_token;

  const lockKey = `lock:${provider}`;
  if (await env.TOKENS.get(lockKey)) throw new BrokerError(503, `${provider} token refresh in progress, retry shortly`);
  await env.TOKENS.put(lockKey, "1", { expirationTtl: LOCK_TTL_S });
  try {
    let fresh;
    try {
      fresh = await PROVIDERS[provider].refresh(env, rec.refresh_token);
    } catch (e) {
      // The old refresh token may already be spent: never retry it; ask for a re-authorization instead.
      await env.TOKENS.put(`token:${provider}`, JSON.stringify({ ...rec, needs_reauth: true, error: String(e.message) }));
      throw e;
    }
    // Rotation: keep the new refresh token (fall back to the old one only if the provider didn't send one).
    const next = { ...fresh, refresh_token: fresh.refresh_token || rec.refresh_token, updated: new Date().toISOString() };
    await env.TOKENS.put(`token:${provider}`, JSON.stringify(next));
    return next.access_token;
  } finally {
    await env.TOKENS.delete(lockKey);
  }
}

function pick(searchParams, allowed) {
  const out = new URLSearchParams();
  for (const k of allowed) if (searchParams.has(k)) out.set(k, searchParams.get(k));
  return out;
}

async function passthrough(res, label) {
  const text = await res.text();
  if (!res.ok) throw new BrokerError(502, `${label}: upstream HTTP ${res.status}`);
  return new Response(text, { status: 200, headers: { "content-type": "application/json", "cache-control": "no-store" } });
}

// ---------- routes ----------

async function handleAuth(env, url, provider, step) {
  const p = PROVIDERS[provider];
  if (!p) return json(404, { error: "unknown provider" });
  if (step === "start") {
    if (!sameKey(url.searchParams.get("key"), env.BROKER_KEY)) return json(401, { error: "bad key" });
    const state = randomState();
    await env.TOKENS.put(`state:${state}`, provider, { expirationTtl: 600 });
    return Response.redirect(p.authorizeUrl(env, url, state), 302);
  }
  if (step === "callback") {
    const state = url.searchParams.get("state") || "";
    const code = url.searchParams.get("code");
    if (url.searchParams.get("error")) return json(400, { error: `authorization refused: ${url.searchParams.get("error")}` });
    if (!code || (await env.TOKENS.get(`state:${state}`)) !== provider) return json(400, { error: "invalid or expired state" });
    await env.TOKENS.delete(`state:${state}`);
    const rec = await p.fromCode(env, url, code);
    await env.TOKENS.put(`token:${provider}`, JSON.stringify({ ...rec, updated: new Date().toISOString() }));
    return new Response(`${provider} connected. You can close this tab.`, { headers: { "content-type": "text/plain" } });
  }
  return json(404, { error: "not found" });
}

async function route(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const auth = path.match(/^\/auth\/(whoop|withings)\/(start|callback)$/);
  // Developer dashboards may probe the callback URL when it is registered: answer HEAD / a bare GET with 200.
  if (auth && auth[2] === "callback" && (request.method === "HEAD" || !url.searchParams.has("state")))
    return new Response(request.method === "HEAD" ? null : "callback ready", { status: 200 });
  if (request.method !== "GET") return json(405, { error: "read-only broker: GET only" });
  if (auth) return handleAuth(env, url, auth[1], auth[2]);

  if (!sameKey(request.headers.get("X-Broker-Key"), env.BROKER_KEY)) return json(401, { error: "bad key" });

  if (path === "/health") {
    const out = {};
    for (const p of Object.keys(PROVIDERS)) {
      const rec = await env.TOKENS.get(`token:${p}`, "json");
      out[p] = rec
        ? { connected: !rec.needs_reauth, needs_reauth: !!rec.needs_reauth, access_expires_at: rec.expires_at, updated: rec.updated }
        : { connected: false };
    }
    return json(200, out);
  }
  if (WHOOP_PATHS.has(path)) {
    const token = await accessToken(env, "whoop");
    const q = pick(url.searchParams, WHOOP_PARAMS);
    if (!q.has("limit")) q.set("limit", "25");
    const res = await fetch(`${WHOOP.api}${path}?${q}`, { headers: { authorization: `Bearer ${token}` } });
    return passthrough(res, "whoop");
  }
  if (path === "/withings/measure") {
    const token = await accessToken(env, "withings");
    const q = pick(url.searchParams, WITHINGS_PARAMS);
    q.set("action", "getmeas");
    if (!q.has("category")) q.set("category", "1"); // real measurements, not objectives
    const res = await fetch(`${WITHINGS.measure}?${q}`, { headers: { authorization: `Bearer ${token}` } });
    const text = await res.text();
    const body = JSON.parse(text || "{}");
    if (!res.ok || body.status !== 0) throw new BrokerError(502, `withings: status ${body.status ?? res.status}`);
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
