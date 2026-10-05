// The admin page's server side (Cloudflare Worker, docs/ADMIN.md). Static files in public/ are served before
// this runs (they hold no data), so only these routes arrive here:
//   /auth/login      → GitHub's sign-in page for the pa-bailar-admin GitHub App
//   /auth/callback   ← GitHub sends the visitor back here; only ALLOWED_USER gets a session
//   /auth/logout     → ends the session
//   /api/health      {ok, configured}: is the Worker up, are the sign-in secrets set
//   /api/me          {login} of the session, 401 without one
//   /api/status      the latest `admin status` (status.json on the sweep-state branch), read with the session's
//                    GitHub token: the visitor's own access, limited to what the App may do (read the backend)
//   /api/requests    POST: a request to the admin tools (check, add or read again a post, add an account), opened as an
//                    issue in the admin inbox, which the admin workflow answers; GET: the latest requests
//   /api/requests/N  one request and its answers (the bot's comments)
//   /api/uploads     POST: a story screenshot (JPEG, shrunk in the browser) kept in KV for 7 days, for an
//                    "Agregar historia" request; GET: how many wait ("Capturas en espera")
//   /api/uploads/ID  GET, DELETE: one screenshot, for the sweep workflow only: GitHub Actions' identity token
//                    (OIDC) of this repository's daily-sweep workflow on main, no secret (verifyOidc)
//   /share           POST: Android's share menu (manifest.webmanifest) when public/sw.js isn't running yet: a
//                    link still works, images ask to share again
//
// The session is a cookie holding the GitHub token, encrypted (AES-GCM, key from SESSION_SECRET) so the browser
// can't read or change it. GitHub App user tokens expire after 8 hours; the refresh token renews them (it lasts
// 6 months) and each renewal sends a new cookie, so a sign-in ends after SESSION_DAYS without use. Logging out
// only deletes the cookie: revoking the App's access at GitHub, or a new SESSION_SECRET, ends it everywhere.
// Secrets (Cloudflare → the Worker → Settings → Variables and Secrets): GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET,
// SESSION_SECRET. Plain settings are in wrangler.jsonc ("vars").

const SESSION_COOKIE = "session";
const STATE_COOKIE = "oauth_state";
const SESSION_DAYS = 30;

// Story screenshots (docs/ADMIN.md, "Agregar historia"): in the UPLOADS KV namespace (wrangler.jsonc), stored as
// the browser sent them (no image work here: the Worker's CPU limit is 10 ms), deleted by the sweep once the
// story's event is published, and by KV after UPLOAD_TTL_SECONDS anyway.
const UPLOAD_PREFIX = "upload:";
const UPLOAD_TTL_SECONDS = 7 * 24 * 3600;
const UPLOAD_MAX_BYTES = 8 * 1024 * 1024; // a 1080 px JPEG is well under 1 MB
const UPLOAD_ID = /^[a-f0-9]{32}$/;
const MAX_STORY_IMAGES = 4;

// Security headers on every answer from here (JSON, redirects): none of them is a page, so the policy allows
// nothing. The static files get theirs, with the page's policy, from public/_headers.
const SECURITY_HEADERS = {
  "Content-Security-Policy": "default-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'",
  "X-Content-Type-Options": "nosniff",
  "X-Frame-Options": "DENY",
  "Referrer-Policy": "strict-origin-when-cross-origin",
  "Strict-Transport-Security": "max-age=31536000",
};

export default {
  async fetch(request, env) {
    const response = await route(request, env);
    for (const [name, value] of Object.entries(SECURITY_HEADERS)) response.headers.set(name, value);
    return response;
  },
};

async function route(request, env) {
  const url = new URL(request.url);
  try {
    switch (url.pathname) {
      case "/api/health":
        return Response.json({ ok: true, configured: configured(env) });
      case "/auth/login":
        return login(url, env);
      case "/auth/callback":
        return await callback(request, url, env);
      case "/auth/logout":
        return redirect("/", clearCookie(SESSION_COOKIE));
      case "/share":
        return await shareWithoutServiceWorker(request);
      case "/api/me":
        return await withSession(request, env, (session) => Response.json({ login: session.login }));
      case "/api/status":
        return await withSession(request, env, (session) => readStatus(session, env));
      case "/api/requests":
        if (request.method === "POST") {
          if (request.headers.get("Origin") !== url.origin) return new Response("Forbidden", { status: 403 });
          return await withSession(request, env, (session) => createRequest(request, session, env));
        }
        return await withSession(request, env, (session) => listRequests(session, env));
      case "/api/uploads":
        if (request.method === "POST") {
          if (request.headers.get("Origin") !== url.origin) return new Response("Forbidden", { status: 403 });
          return await withSession(request, env, () => storeUpload(request, env));
        }
        return await withSession(request, env, () => countUploads(env));
      default: {
        const match = url.pathname.match(/^\/api\/requests\/(\d+)$/);
        if (match) return await withSession(request, env, (session) => readRequest(match[1], session, env));
        const upload = url.pathname.match(/^\/api\/uploads\/([a-f0-9]{32})$/);
        if (upload) return await sweepUpload(request, upload[1], env);
        return new Response("Not found", { status: 404 });
      }
    }
  } catch (error) {
    console.error(error);
    return Response.json({ error: "Algo falló en el servidor." }, { status: 500 });
  }
}

const configured = (env) => Boolean(env.GITHUB_CLIENT_ID && env.GITHUB_CLIENT_SECRET && env.SESSION_SECRET);

// ---------- sign-in with GitHub ----------

function login(url, env) {
  if (!configured(env)) return redirect("/?error=config");
  const state = crypto.randomUUID();
  const authorize = new URL("https://github.com/login/oauth/authorize");
  authorize.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
  authorize.searchParams.set("redirect_uri", `${url.origin}/auth/callback`);
  authorize.searchParams.set("state", state);
  return redirect(authorize.href, cookie(STATE_COOKIE, state, 600));
}

async function callback(request, url, env) {
  const state = readCookie(request, STATE_COOKIE);
  if (!configured(env) || !state || url.searchParams.get("state") !== state || !url.searchParams.get("code")) {
    return redirect("/?error=login", clearCookie(STATE_COOKIE));
  }
  const tokens = await githubTokens(env, { code: url.searchParams.get("code") });
  if (!tokens) return redirect("/?error=login", clearCookie(STATE_COOKIE));

  const user = await github("/user", tokens.access_token);
  if (!user.ok) return redirect("/?error=login", clearCookie(STATE_COOKIE));
  const { login: githubLogin } = await user.json();
  if (githubLogin !== env.ALLOWED_USER) return redirect("/?error=denied", clearCookie(STATE_COOKIE));

  const session = { login: githubLogin, ...tokens };
  return redirect("/", clearCookie(STATE_COOKIE), await sessionCookie(session, env));
}

/** Exchange a sign-in code, or a refresh token, for GitHub tokens. Null if GitHub says no. */
async function githubTokens(env, grant) {
  const body = new URLSearchParams({ client_id: env.GITHUB_CLIENT_ID, client_secret: env.GITHUB_CLIENT_SECRET });
  if (grant.code) body.set("code", grant.code);
  else {
    body.set("grant_type", "refresh_token");
    body.set("refresh_token", grant.refresh_token);
  }
  const response = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: { Accept: "application/json" },
    body,
  });
  const answer = await response.json();
  if (!response.ok || !answer.access_token) return null;
  return {
    access_token: answer.access_token,
    refresh_token: answer.refresh_token ?? null,
    // GitHub App tokens expire (8 h); without expiry (setting off), treat as long-lived.
    expires_at: answer.expires_in ? Date.now() + answer.expires_in * 1000 : null,
  };
}

/** Runs `handler` with a valid session (renewing the GitHub token when it's about to expire), or answers 401. */
async function withSession(request, env, handler) {
  let session = configured(env) ? await readSession(request, env) : null;
  if (!session || session.login !== env.ALLOWED_USER) {
    return Response.json({ error: "Inicia sesión." }, { status: 401 });
  }
  let renewed = null;
  if (session.expires_at && session.expires_at - Date.now() < 60_000) {
    const tokens = session.refresh_token ? await githubTokens(env, { refresh_token: session.refresh_token }) : null;
    if (!tokens) return Response.json({ error: "La sesión venció: inicia sesión de nuevo." }, { status: 401 });
    session = { ...session, ...tokens };
    renewed = await sessionCookie(session, env);
  }
  const response = await handler(session);
  if (renewed) response.headers.append("Set-Cookie", renewed);
  return response;
}

// ---------- data ----------

async function readStatus(session, env) {
  const path = `/repos/${env.REPO}/contents/status.json?ref=${encodeURIComponent(env.STATE_BRANCH)}`;
  const response = await github(path, session.access_token, "application/vnd.github.raw+json");
  if (response.status === 404) return Response.json({ missing: true });
  if (!response.ok) return githubError(response, " al leer el estado");
  return new Response(await response.text(), {
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store" },
  });
}

// ---------- requests: issues in the admin inbox (.github/workflows/admin.yml answers them) ----------

// The whole value is one post link (a slash, a query like ?igsh=… and a #fragment allowed, no spaces or new
// lines): it goes into the issue's body, which the inbox reads line by line.
const POST_LINK = /^https?:\/\/(www\.|m\.)?instagram\.com\/([\w.]+\/)?(p|reel|reels|tv)\/[\w-]+\/?(\?[^\s#]*)?(#\S*)?$/i;
const ACCOUNT = /^[A-Za-z0-9._]{1,30}$/; // tested without its "@"
const STORY_ID = /^story-[a-f0-9]{16}$/; // a story published from screenshots (pa_bailar/stories.py)
// An event's id on the site (pa_bailar/ids.py; pa_bailar/inbox.py EVENT_ID): lowercase words joined by hyphens.
const EVENT_ID = /^[a-z0-9]+(-[a-z0-9]+)*$/;
const EVENT_ID_MAX = 120;
const NOTES_MAX = 500;
const ACTIONS = {
  why: "Revisar",
  "add-post": "Agregar",
  "add-post-again": "Volver a leer",
  "add-account": "Agregar cuenta",
  status: "Estado",
  "add-story": "Agregar historia",
  "hide-story": "Ocultar historia",
  "hide-event": "Ocultar evento",
};
const POST_ACTIONS = new Set(["why", "add-post", "add-post-again"]); // the ones that need a post link

/**
 * POST {action, link?, account?, images?, notes?, story?} → an issue written like the inbox's form
 * (pa_bailar/inbox.py reads it). "add-story" takes the ids of screenshots uploaded first (/api/uploads) and
 * optional notes; "hide-story" a published story's id (story-…), from the answer to an "add-story"; "hide-event"
 * an event's id on the site (the status' new series list: "Ocultar del sitio").
 */
async function createRequest(request, session, env) {
  const fields = (await request.json().catch(() => null)) ?? {};
  const { action, link = "", account = "" } = fields;
  const cleanLink = String(link).trim();
  const cleanAccount = String(account).trim().replace(/^@/, "");
  if (!Object.hasOwn(ACTIONS, action)) return Response.json({ error: "Acción desconocida." }, { status: 400 });
  if (cleanAccount && !ACCOUNT.test(cleanAccount)) {
    return Response.json({ error: "Esa @cuenta no es válida." }, { status: 400 });
  }
  if (action === "add-story" || action === "hide-story") {
    return createStoryRequest(action, fields, cleanAccount, session, env);
  }
  if (action === "hide-event") return createHideEventRequest(fields, session, env);
  if (POST_ACTIONS.has(action) && !POST_LINK.test(cleanLink)) {
    return Response.json({ error: "Pega el enlace de una publicación de Instagram (instagram.com/p/…)." }, { status: 400 });
  }
  if (action === "add-account" && !cleanAccount) {
    return Response.json({ error: "Escribe la @cuenta a agregar." }, { status: 400 });
  }
  const subject = action === "add-account" ? `@${cleanAccount}` : cleanLink;
  const body = [
    `### Acción\n\n${ACTIONS[action]}`,
    `### Enlace\n\n${POST_ACTIONS.has(action) ? cleanLink : "_No response_"}`,
    `### Cuenta\n\n${cleanAccount ? `@${cleanAccount}` : "_No response_"}`,
    "_Desde la página de administración._",
  ].join("\n\n");
  const response = await github(`/repos/${env.REPO}/issues`, session.access_token, undefined, {
    method: "POST",
    body: JSON.stringify({ title: `${ACTIONS[action]}${subject ? `: ${subject}` : ""}`, body, labels: ["admin"] }),
  });
  if (!response.ok) return githubError(response, " al crear el pedido");
  const issue = await response.json();
  return Response.json({ number: issue.number, url: issue.html_url });
}

/** "Ocultar evento": take one event off the site (its id), whatever it came from. */
async function createHideEventRequest(fields, session, env) {
  const event = String(fields.event ?? "").trim();
  if (event.length > EVENT_ID_MAX || !EVENT_ID.test(event)) {
    return Response.json({ error: "Ese evento no es válido." }, { status: 400 });
  }
  const body = [`### Acción\n\n${ACTIONS["hide-event"]}`, `### Evento\n\n${event}`, "_Desde la página de administración._"];
  const response = await github(`/repos/${env.REPO}/issues`, session.access_token, undefined, {
    method: "POST",
    body: JSON.stringify({ title: `${ACTIONS["hide-event"]}: ${event}`, body: body.join("\n\n"), labels: ["admin"] }),
  });
  if (!response.ok) return githubError(response, " al crear el pedido");
  const issue = await response.json();
  return Response.json({ number: issue.number, url: issue.html_url });
}

/** "Agregar historia" (the uploaded screenshots' ids, @cuenta and notes) or "Ocultar historia" (its id). */
async function createStoryRequest(action, fields, account, session, env) {
  let title;
  let body;
  if (action === "add-story") {
    const images = Array.isArray(fields.images) ? [...new Set(fields.images.map(String))] : [];
    if (!images.length || images.length > MAX_STORY_IMAGES || !images.every((id) => UPLOAD_ID.test(id))) {
      return Response.json({ error: `Elige de 1 a ${MAX_STORY_IMAGES} capturas.` }, { status: 400 });
    }
    // One line: the inbox reads the issue's fields by their "### " headings.
    const notes = String(fields.notes ?? "").replace(/\s+/g, " ").trim().slice(0, NOTES_MAX);
    const count = images.length === 1 ? "1 captura" : `${images.length} capturas`;
    title = `${ACTIONS[action]}: ${account ? `@${account}` : count}`;
    body = [
      `### Acción\n\n${ACTIONS[action]}`,
      `### Capturas\n\n${images.join(" ")}`,
      `### Cuenta\n\n${account ? `@${account}` : "_No response_"}`,
      `### Notas\n\n${notes || "_No response_"}`,
    ];
  } else {
    const story = String(fields.story ?? "").trim();
    if (!STORY_ID.test(story)) return Response.json({ error: "Esa historia no es válida." }, { status: 400 });
    title = `${ACTIONS[action]}: ${story}`;
    body = [`### Acción\n\n${ACTIONS[action]}`, `### Historia\n\n${story}`];
  }
  const text = [...body, "_Desde la página de administración._"].join("\n\n");
  const response = await github(`/repos/${env.REPO}/issues`, session.access_token, undefined, {
    method: "POST",
    body: JSON.stringify({ title, body: text, labels: ["admin"] }),
  });
  if (!response.ok) return githubError(response, " al crear el pedido");
  const issue = await response.json();
  return Response.json({ number: issue.number, url: issue.html_url });
}

// ---------- story screenshots: uploads (KV) ----------

const noUploads = () => Response.json({ error: "Falta configurar el almacenamiento de capturas (KV)." }, { status: 503 });
const tooBig = () => Response.json({ error: "La captura es demasiado grande." }, { status: 413 });

/** POST a JPEG (the page shrinks it first) → {id}. Its file name and date go along as headers, for the sweep. */
async function storeUpload(request, env) {
  if (!env.UPLOADS) return noUploads();
  if (request.headers.get("Content-Type") !== "image/jpeg") {
    return Response.json({ error: "La captura debe llegar como JPEG." }, { status: 415 });
  }
  if (Number(request.headers.get("Content-Length") ?? 0) > UPLOAD_MAX_BYTES) return tooBig();
  const bytes = await request.arrayBuffer();
  if (bytes.byteLength > UPLOAD_MAX_BYTES) return tooBig();
  const start = new Uint8Array(bytes, 0, Math.min(3, bytes.byteLength));
  if (start.length < 3 || start[0] !== 0xff || start[1] !== 0xd8 || start[2] !== 0xff) {
    return Response.json({ error: "Eso no es una imagen JPEG." }, { status: 415 });
  }
  let name = "";
  try {
    name = decodeURIComponent(request.headers.get("X-File-Name") ?? "").slice(0, 120);
  } catch {}
  const modified = Number(request.headers.get("X-File-Modified"));
  const metadata = { name, modified: Number.isFinite(modified) && modified > 0 ? modified : null, uploaded: Date.now() };
  const id = [...crypto.getRandomValues(new Uint8Array(16))].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  await env.UPLOADS.put(UPLOAD_PREFIX + id, bytes, { expirationTtl: UPLOAD_TTL_SECONDS, metadata });
  return Response.json({ id }, { status: 201 });
}

/** How many screenshots wait in KV (not yet published, or expiring): "Capturas en espera". */
async function countUploads(env) {
  if (!env.UPLOADS) return noUploads();
  const listed = await env.UPLOADS.list({ prefix: UPLOAD_PREFIX });
  return Response.json(
    { waiting: listed.keys.length, more: !listed.list_complete },
    { headers: { "Cache-Control": "no-store" } },
  );
}

/** GET (the image, its metadata in X-Upload-Meta) or DELETE one screenshot: only for the sweep workflow. */
async function sweepUpload(request, id, env) {
  if (!env.UPLOADS) return noUploads();
  if (!["GET", "DELETE"].includes(request.method)) return new Response("Method not allowed", { status: 405 });
  if (!(await verifyOidc(request, env))) return Response.json({ error: "Unauthorized" }, { status: 401 });
  const key = UPLOAD_PREFIX + id;
  if (request.method === "DELETE") {
    await env.UPLOADS.delete(key);
    return new Response(null, { status: 204 });
  }
  const { value, metadata } = await env.UPLOADS.getWithMetadata(key, { type: "arrayBuffer" });
  if (value === null) return Response.json({ error: "Not found" }, { status: 404 });
  return new Response(value, {
    headers: {
      "Content-Type": "image/jpeg",
      "Cache-Control": "no-store",
      "X-Upload-Meta": encodeURIComponent(JSON.stringify(metadata ?? {})),
    },
  });
}

// ---------- GitHub Actions' identity token (OIDC) ----------

const OIDC_ISSUER = "https://token.actions.githubusercontent.com";
const JWKS_REFRESH_MS = 60 * 60 * 1000;
let jwks = { keys: new Map(), fetchedAt: 0 }; // kept while this Worker instance lives: few fetches, little CPU

/**
 * The claims of a valid identity token from this repository's daily-sweep workflow on main, else null: signed
 * by GitHub (RS256, its published keys), for this Worker (aud: OIDC_AUDIENCE), not expired.
 * https://docs.github.com/en/actions/reference/security/oidc
 */
export async function verifyOidc(request, env, now = Date.now()) {
  const token = (request.headers.get("Authorization") ?? "").match(/^Bearer ([\w-]+\.[\w-]+\.[\w-]+)$/)?.[1];
  if (!token || !env.OIDC_AUDIENCE) return null;
  const [headerPart, payloadPart, signaturePart] = token.split(".");
  let header;
  let claims;
  try {
    header = JSON.parse(new TextDecoder().decode(fromBase64url(headerPart)));
    claims = JSON.parse(new TextDecoder().decode(fromBase64url(payloadPart)));
  } catch {
    return null;
  }
  const seconds = now / 1000;
  const audiences = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  const ok =
    header.alg === "RS256" &&
    typeof header.kid === "string" &&
    claims.iss === OIDC_ISSUER &&
    audiences.includes(env.OIDC_AUDIENCE) &&
    typeof claims.exp === "number" &&
    claims.exp > seconds &&
    (claims.nbf === undefined || claims.nbf <= seconds + 60) &&
    claims.repository === env.REPO &&
    claims.ref === "refs/heads/main" &&
    String(claims.workflow_ref ?? "").startsWith(`${env.REPO}/.github/workflows/daily-sweep.yml@`);
  if (!ok) return null;
  const key = await signingKey(header.kid, now);
  if (!key) return null;
  try {
    const signed = new TextEncoder().encode(`${headerPart}.${payloadPart}`);
    const valid = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, fromBase64url(signaturePart), signed);
    return valid ? claims : null;
  } catch {
    return null;
  }
}

/** GitHub's public key with this id: fetched (and cached by Cloudflare for an hour) when unknown or old. */
async function signingKey(kid, now) {
  const fresh = now - jwks.fetchedAt < JWKS_REFRESH_MS;
  if (fresh && jwks.keys.has(kid)) return jwks.keys.get(kid);
  if (now - jwks.fetchedAt < 60_000) return null; // just fetched: an unknown key stays unknown for a minute
  const response = await fetch(`${OIDC_ISSUER}/.well-known/jwks`, { cf: { cacheTtl: 3600, cacheEverything: true } });
  if (!response.ok) return null;
  const { keys = [] } = await response.json();
  const imported = new Map();
  for (const jwk of keys) {
    if (jwk.kty !== "RSA" || !jwk.kid) continue;
    const key = await crypto.subtle.importKey(
      "jwk",
      { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    imported.set(jwk.kid, key);
  }
  jwks = { keys: imported, fetchedAt: now };
  return imported.get(kid) ?? null;
}

/** Forget the cached keys (tests). */
export function resetJwksCache() {
  jwks = { keys: new Map(), fetchedAt: 0 };
}

// ---------- the share menu without the service worker ----------

/**
 * Android posts what's shared to /share (manifest.webmanifest); public/sw.js normally answers it in the browser.
 * When the service worker isn't running yet (the first share after installing), it arrives here: a link (a few
 * text fields) goes on to the page as before; images are too big to handle here, so the page asks to share again.
 */
async function shareWithoutServiceWorker(request) {
  if (request.method !== "POST") return redirect("/");
  const length = Number(request.headers.get("Content-Length") ?? Number.POSITIVE_INFINITY);
  if (length <= 64 * 1024) {
    const form = await request.formData().catch(() => null);
    const values = form ? [...form.values()] : [];
    if (values.length && values.every((value) => typeof value === "string")) {
      const params = new URLSearchParams();
      for (const name of ["title", "text", "url"]) {
        const value = form.get(name);
        if (typeof value === "string" && value.trim()) params.set(name, value.slice(0, 2000));
      }
      if (params.size) return redirect(`/?${params}`, 303);
    }
  }
  return redirect("/?share=retry", 303);
}

/** The latest admin requests (open and answered). */
async function listRequests(session, env) {
  const path = `/repos/${env.REPO}/issues?labels=admin&state=all&per_page=8&sort=created&direction=desc`;
  const response = await github(path, session.access_token);
  if (!response.ok) return githubError(response, " al leer los pedidos");
  const issues = await response.json();
  return Response.json(
    issues.map((issue) => ({
      number: issue.number,
      title: issue.title,
      state: issue.state,
      created_at: issue.created_at,
      url: issue.html_url,
    })),
  );
}

/** One request: its state and the answers (comments). */
async function readRequest(number, session, env) {
  const [issueResponse, commentsResponse] = await Promise.all([
    github(`/repos/${env.REPO}/issues/${number}`, session.access_token),
    github(`/repos/${env.REPO}/issues/${number}/comments?per_page=50`, session.access_token),
  ]);
  if (!issueResponse.ok || !commentsResponse.ok) {
    return githubError(issueResponse.ok ? commentsResponse : issueResponse, " al leer el pedido");
  }
  const issue = await issueResponse.json();
  if (!issue.labels?.some((label) => label.name === "admin")) {
    return Response.json({ error: "Ese no es un pedido de administración." }, { status: 404 });
  }
  const comments = await commentsResponse.json();
  return Response.json(
    {
      number: issue.number,
      title: issue.title,
      state: issue.state,
      url: issue.html_url,
      answers: comments
        .filter((comment) => comment.user?.type === "Bot")
        .map((comment) => ({ body: comment.body, created_at: comment.created_at })),
    },
    { headers: { "Cache-Control": "no-store" } },
  );
}

/** GitHub said no: 401 when it turned the session's token down (access revoked), so the page asks to sign in. */
function githubError(response, doing) {
  if (response.status === 401) {
    return Response.json({ error: "GitHub no aceptó la sesión: inicia sesión de nuevo." }, { status: 401 });
  }
  return Response.json({ error: `GitHub respondió ${response.status}${doing}.` }, { status: 502 });
}

function github(path, token, accept = "application/vnd.github+json", init = {}) {
  return fetch(`https://api.github.com${path}`, {
    ...init,
    headers: {
      Accept: accept,
      Authorization: `Bearer ${token}`,
      "User-Agent": "pa-bailar-admin",
      "X-GitHub-Api-Version": "2022-11-28",
      ...(init.body ? { "Content-Type": "application/json" } : {}),
    },
  });
}

// ---------- the encrypted session cookie ----------

async function key(env) {
  const secret = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(env.SESSION_SECRET));
  return crypto.subtle.importKey("raw", secret, "AES-GCM", false, ["encrypt", "decrypt"]);
}

async function sessionCookie(session, env) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = new TextEncoder().encode(JSON.stringify(session));
  const sealed = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, await key(env), data));
  return cookie(SESSION_COOKIE, base64url(new Uint8Array([...iv, ...sealed])), SESSION_DAYS * 24 * 3600);
}

async function readSession(request, env) {
  const value = readCookie(request, SESSION_COOKIE);
  if (!value) return null;
  try {
    const bytes = fromBase64url(value);
    const opened = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: bytes.slice(0, 12) },
      await key(env),
      bytes.slice(12),
    );
    return JSON.parse(new TextDecoder().decode(opened));
  } catch {
    return null; // tampered, or sealed with an older SESSION_SECRET
  }
}

// ---------- small helpers ----------

function cookie(name, value, maxAge) {
  return `${name}=${value}; Path=/; HttpOnly; Secure; SameSite=Lax; Max-Age=${maxAge}`;
}

const clearCookie = (name) => cookie(name, "", 0);

function readCookie(request, name) {
  const header = request.headers.get("Cookie") ?? "";
  const match = header.split(/;\s*/).find((part) => part.startsWith(`${name}=`));
  return match ? match.slice(name.length + 1) : null;
}

/** A redirect (302, or the status given second) that may set cookies. */
function redirect(location, ...rest) {
  const status = typeof rest[0] === "number" ? rest.shift() : 302;
  const headers = new Headers({ Location: location, "Cache-Control": "no-store" });
  for (const value of rest) headers.append("Set-Cookie", value);
  return new Response(null, { status, headers });
}

function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function fromBase64url(text) {
  const padded = text + "=".repeat((4 - (text.length % 4)) % 4);
  const plain = atob(padded.replaceAll("-", "+").replaceAll("_", "/"));
  return Uint8Array.from(plain, (char) => char.charCodeAt(0));
}
