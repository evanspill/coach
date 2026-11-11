// Runs the Worker against an in-memory KV and fake Whoop/Withings servers: `npm test` (no dependencies).
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

import worker from "../src/index.js";

const KEY = "k".repeat(40);
let kv, calls, env, refreshOk;

function makeKV() {
  const m = new Map();
  return {
    m,
    async get(k, type) {
      const v = m.get(k);
      return v === undefined ? null : type === "json" ? JSON.parse(v) : v;
    },
    async put(k, v) { m.set(k, v); },
    async delete(k) { m.delete(k); },
  };
}

beforeEach(() => {
  kv = makeKV();
  calls = [];
  refreshOk = true;
  env = {
    TOKENS: kv, BROKER_KEY: KEY,
    WHOOP_CLIENT_ID: "wid", WHOOP_CLIENT_SECRET: "wsec", WITHINGS_CLIENT_ID: "nid", WITHINGS_CLIENT_SECRET: "nsec",
  };
  globalThis.fetch = async (url, init = {}) => {
    const u = String(url);
    const body = init.body ? Object.fromEntries(new URLSearchParams(String(init.body))) : null;
    calls.push({ url: u, body, auth: init.headers?.authorization });
    if (u.startsWith("https://api.prod.whoop.com/oauth/oauth2/token")) {
      if (!refreshOk) return new Response("{}", { status: 400 });
      const n = calls.filter((c) => c.url.includes("oauth2/token")).length;
      return Response.json({ access_token: `wat${n}`, refresh_token: `wrt${n}`, expires_in: 3600 });
    }
    if (u.startsWith("https://api.prod.whoop.com/developer/v2/")) return Response.json({ records: [{ id: 1 }], next_token: null });
    if (u.startsWith("https://wbsapi.withings.net/v2/oauth2"))
      return Response.json({ status: 0, body: { access_token: "nat", refresh_token: "nrt2", expires_in: 10800 } });
    if (u.startsWith("https://wbsapi.withings.net/measure")) return Response.json({ status: 0, body: { measuregrps: [] } });
    return new Response("nope", { status: 404 });
  };
});

const get = (path, key = KEY) =>
  worker.fetch(new Request(`https://broker.example.workers.dev${path}`, { headers: key ? { "X-Broker-Key": key } : {} }), env);

test("data endpoints need the static key", async () => {
  assert.equal((await get("/v2/recovery", null)).status, 401);
  assert.equal((await get("/v2/recovery", "wrong")).status, 401);
});

test("read-only: anything but GET is refused", async () => {
  const r = await worker.fetch(new Request("https://b.example/v2/recovery", { method: "POST", headers: { "X-Broker-Key": KEY } }), env);
  assert.equal(r.status, 405);
});

test("OAuth start -> callback stores tokens; state is single-use", async () => {
  assert.equal((await get("/auth/whoop/start?key=bad", null)).status, 401);
  const start = await get(`/auth/whoop/start?key=${KEY}`, null);
  assert.equal(start.status, 302);
  const loc = new URL(start.headers.get("location"));
  assert.equal(loc.origin + loc.pathname, "https://api.prod.whoop.com/oauth/oauth2/auth");
  assert.match(loc.searchParams.get("scope"), /offline/);
  assert.equal(loc.searchParams.get("redirect_uri"), "https://broker.example.workers.dev/auth/whoop/callback");
  const state = loc.searchParams.get("state");
  const cb = await get(`/auth/whoop/callback?code=abc&state=${state}`, null);
  assert.equal(cb.status, 200);
  assert.equal((await kv.get("token:whoop", "json")).refresh_token, "wrt1");
  assert.equal((await get(`/auth/whoop/callback?code=abc&state=${state}`, null)).status, 400);
});

test("fresh access token is reused; no refresh", async () => {
  await kv.put("token:whoop", JSON.stringify({ access_token: "live", refresh_token: "r0", expires_at: Date.now() / 1000 + 3000 }));
  const r = await get("/v2/recovery?start=2026-11-10T00:00:00Z&end=2026-11-11T00:00:00Z&evil=1");
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { records: [{ id: 1 }], next_token: null });
  const up = calls.find((c) => c.url.includes("/developer/v2/recovery"));
  assert.equal(up.auth, "Bearer live");
  assert.ok(!up.url.includes("evil") && up.url.includes("limit=25"));
  assert.ok(!calls.some((c) => c.url.includes("oauth2/token")));
});

test("expired token refreshes once, stores the rotated refresh token, releases the lock", async () => {
  await kv.put("token:whoop", JSON.stringify({ access_token: "old", refresh_token: "r0", expires_at: 0 }));
  assert.equal((await get("/v2/cycle")).status, 200);
  const rc = calls.find((c) => c.url.includes("oauth2/token"));
  assert.deepEqual(rc.body, { client_id: "wid", client_secret: "wsec", grant_type: "refresh_token", refresh_token: "r0", scope: "offline" });
  const rec = await kv.get("token:whoop", "json");
  assert.equal(rec.refresh_token, "wrt1");
  assert.equal(await kv.get("lock:whoop"), null);
  assert.equal((await get("/v2/activity/sleep")).status, 200);
  assert.equal(calls.filter((c) => c.url.includes("oauth2/token")).length, 1);
});

test("failed refresh is not retried: marked needs_reauth, 502 until re-authorized", async () => {
  refreshOk = false;
  await kv.put("token:whoop", JSON.stringify({ access_token: "old", refresh_token: "r0", expires_at: 0 }));
  assert.equal((await get("/v2/recovery")).status, 502);
  assert.equal((await kv.get("token:whoop", "json")).needs_reauth, true);
  refreshOk = true;
  assert.equal((await get("/v2/recovery")).status, 502);
  assert.equal(calls.filter((c) => c.url.includes("oauth2/token")).length, 1);
  const h = await (await get("/health")).json();
  assert.deepEqual([h.whoop.connected, h.whoop.needs_reauth, h.withings.connected], [false, true, false]);
  assert.ok(!JSON.stringify(h).includes("r0"));
});

test("a held lock means 503 (no concurrent refresh)", async () => {
  await kv.put("token:whoop", JSON.stringify({ access_token: "old", refresh_token: "r0", expires_at: 0 }));
  await kv.put("lock:whoop", "1");
  assert.equal((await get("/v2/recovery")).status, 503);
  assert.ok(!calls.some((c) => c.url.includes("oauth2/token")));
});

test("withings measure: refresh via requesttoken, getmeas passthrough", async () => {
  await kv.put("token:withings", JSON.stringify({ access_token: "x", refresh_token: "nrt1", expires_at: 0 }));
  const r = await get("/withings/measure?meastypes=1,6,8&startdate=1&enddate=2");
  assert.equal(r.status, 200);
  assert.deepEqual(await r.json(), { status: 0, body: { measuregrps: [] } });
  const rc = calls.find((c) => c.url.includes("v2/oauth2"));
  assert.equal(rc.body.action, "requesttoken");
  const m = calls.find((c) => c.url.includes("/measure?"));
  assert.ok(m.url.includes("action=getmeas") && m.url.includes("category=1") && m.auth === "Bearer nat");
  assert.equal((await kv.get("token:withings", "json")).refresh_token, "nrt2");
});

test("unknown paths are 404 (only the read-only allowlist is proxied)", async () => {
  assert.equal((await get("/v2/user/profile/basic")).status, 404);
});

test("callback answers dashboard probes (HEAD, bare GET) with 200", async () => {
  const h = await worker.fetch(new Request("https://b.example/auth/withings/callback", { method: "HEAD" }), env);
  assert.equal(h.status, 200);
  assert.equal((await get("/auth/withings/callback", null)).status, 200);
  assert.equal((await get("/auth/withings/callback?state=x&error=access_denied", null)).status, 400);
});

test("privacy page is public plain text", async () => {
  const r = await get("/privacy", null);
  assert.equal(r.status, 200);
  assert.match(await r.text(), /stores no health data/);
});
