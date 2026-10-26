#!/usr/bin/env node
/**
 * DEV-ONLY mock API. Serves SYNTHETIC fixtures from web/mocks/ for
 * /api/portfolio/* and /api/disclosures, and proxies every other /api/* request
 * to the real backend. Lets the Portfolio and Disclosures layouts be checked
 * without an Avanza login or an Alpha Vantage key. Never point production at it.
 *
 *   npm run mock:api                                  # :8790 -> backend :8782
 *   MOCK_PORT=8790 MOCK_BACKEND=http://127.0.0.1:8782 npm run mock:api
 *   MOCK_SCENARIO=blocked      portfolio status = login cool-down, data calls 503
 *   MOCK_SCENARIO=unconfigured portfolio + disclosures behave as "not configured"
 *   MOCK_SCENARIO=signedout    status says not signed in; data calls then succeed (as if one login worked)
 *   MOCK_DELAY_MS=800          add latency to fixture responses (loading states)
 *
 * Then run Next with API_PROXY_TARGET=http://127.0.0.1:8790. No dependencies.
 */
import { createServer, request as httpRequest } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const PORT = Number(process.env.MOCK_PORT ?? 8790);
const BACKEND = new URL(process.env.MOCK_BACKEND ?? "http://127.0.0.1:8782");
const SCENARIO = process.env.MOCK_SCENARIO ?? "ok";
const DELAY = Number(process.env.MOCK_DELAY_MS ?? 0);
const MOCKS = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "mocks");

const PERIODS = new Set(["1d", "1w", "1m", "3m", "ytd", "1y", "3y", "all"]);
const DISC_TYPES = new Set(["congress", "insiders", "funds"]);

function send(res, status, body) {
  const text = JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Mock-Api": "1" });
  res.end(text);
}

async function fixture(res, rel) {
  try {
    const text = await readFile(path.join(MOCKS, rel), "utf8");
    if (DELAY) await new Promise((r) => setTimeout(r, DELAY));
    res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Mock-Api": "1" });
    res.end(text);
  } catch (e) {
    send(res, 500, { error: `mock fixture missing: ${rel} (${e.code ?? e.message})` });
  }
}

function blockedUntil() {
  return new Date(Date.now() + 23 * 60_000).toISOString();
}

async function portfolio(res, name, params) {
  if (SCENARIO === "unconfigured") {
    if (name === "status") return send(res, 200, { configured: false, authenticated: false, login_blocked_until: null, last_login_failure: null });
    return send(res, 503, { error: "Avanza is not configured (AVANZA_USERNAME / AVANZA_PASSWORD unset)" });
  }
  if (SCENARIO === "blocked") {
    const until = blockedUntil();
    if (name === "status")
      return send(res, 200, { configured: true, authenticated: false, login_blocked_until: until, last_login_failure: "step 1 HTTP 401 (mock)" });
    return send(res, 503, { error: "Avanza login failed: step 1 HTTP 401 (mock); next attempt allowed in 23 min" });
  }
  if (SCENARIO === "signedout" && name === "status")
    return send(res, 200, { configured: true, authenticated: false, login_blocked_until: null, last_login_failure: null });
  switch (name) {
    case "status":
    case "summary":
    case "positions":
    case "transactions":
    case "brief":
      return fixture(res, `portfolio/${name}.json`);
    case "performance": {
      const period = params.get("period") ?? "1m";
      if (!PERIODS.has(period)) return send(res, 400, { error: `period must be one of ${[...PERIODS].join(", ")}` });
      return fixture(res, `portfolio/performance-${period}.json`);
    }
    default:
      return send(res, 404, { error: `no mock for /api/portfolio/${name}` });
  }
}

function proxy(req, res) {
  const upstream = httpRequest(
    { hostname: BACKEND.hostname, port: BACKEND.port, path: req.url, method: req.method, headers: { ...req.headers, host: BACKEND.host } },
    (up) => {
      res.writeHead(up.statusCode ?? 502, up.headers);
      up.pipe(res);
    },
  );
  upstream.on("error", () => send(res, 502, { error: `mock-api: backend not reachable at ${BACKEND.origin}` }));
  req.pipe(upstream);
}

const server = createServer((req, res) => {
  const url = new URL(req.url ?? "/", `http://${req.headers.host ?? "localhost"}`);
  const p = url.pathname;
  const pf = p.match(/^\/api\/portfolio\/([a-z]+)$/);
  if (pf && req.method === "GET") return void portfolio(res, pf[1], url.searchParams);
  if (p === "/api/disclosures" && req.method === "GET") {
    const type = url.searchParams.get("type") ?? "congress";
    if (!DISC_TYPES.has(type)) return send(res, 400, { error: `type must be one of ${[...DISC_TYPES].join(", ")}` });
    if (SCENARIO === "unconfigured") return send(res, 503, { error: "ALPHAVANTAGE_API_KEY is not set", configured: false, type });
    return void fixture(res, `disclosures-${type}.json`);
  }
  if (p.startsWith("/api/")) return proxy(req, res);
  send(res, 404, { error: "mock-api only serves /api/*" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`mock-api on http://127.0.0.1:${PORT} · scenario=${SCENARIO} · proxy -> ${BACKEND.origin} · fixtures ${MOCKS}`);
});
