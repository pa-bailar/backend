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
//
// The session is a cookie holding the GitHub token, encrypted (AES-GCM, key from SESSION_SECRET) so the browser
// can't read or change it. GitHub App user tokens expire after 8 hours; the refresh token renews them (it lasts
// 6 months), so a sign-in lasts until the cookie does (SESSION_DAYS).
// Secrets (Cloudflare → the Worker → Settings → Variables and Secrets): GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET,
// SESSION_SECRET. Plain settings are in wrangler.jsonc ("vars").

const SESSION_COOKIE = "session";
const STATE_COOKIE = "oauth_state";
const SESSION_DAYS = 30;

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
      default: {
        const match = url.pathname.match(/^\/api\/requests\/(\d+)$/);
        if (match) return await withSession(request, env, (session) => readRequest(match[1], session, env));
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
const ACTIONS = {
  why: "Revisar",
  "add-post": "Agregar",
  "add-post-again": "Volver a leer",
  "add-account": "Agregar cuenta",
  status: "Estado",
};
const POST_ACTIONS = new Set(["why", "add-post", "add-post-again"]); // the ones that need a post link

/** POST {action, link?, account?} → an issue written like the inbox's form (pa_bailar/inbox.py reads it). */
async function createRequest(request, session, env) {
  const { action, link = "", account = "" } = (await request.json().catch(() => null)) ?? {};
  const cleanLink = String(link).trim();
  const cleanAccount = String(account).trim().replace(/^@/, "");
  if (!Object.hasOwn(ACTIONS, action)) return Response.json({ error: "Acción desconocida." }, { status: 400 });
  if (POST_ACTIONS.has(action) && !POST_LINK.test(cleanLink)) {
    return Response.json({ error: "Pega el enlace de una publicación de Instagram (instagram.com/p/…)." }, { status: 400 });
  }
  if (cleanAccount && !ACCOUNT.test(cleanAccount)) {
    return Response.json({ error: "Esa @cuenta no es válida." }, { status: 400 });
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

function redirect(location, ...cookies) {
  const headers = new Headers({ Location: location, "Cache-Control": "no-store" });
  for (const value of cookies) headers.append("Set-Cookie", value);
  return new Response(null, { status: 302, headers });
}

function base64url(bytes) {
  return btoa(String.fromCharCode(...bytes)).replaceAll("+", "-").replaceAll("/", "_").replaceAll("=", "");
}

function fromBase64url(text) {
  const plain = atob(text.replaceAll("-", "+").replaceAll("_", "/"));
  return Uint8Array.from(plain, (char) => char.charCodeAt(0));
}
