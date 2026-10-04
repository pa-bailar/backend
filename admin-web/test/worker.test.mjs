// Tests for the admin page's Worker (src/index.js) with Node's own runner: `node --test admin-web/test/`
// (the ci workflow runs them). No network: GitHub's API and its OIDC keys are fakes, KV is an in-memory map.

import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import worker, { resetJwksCache } from "../src/index.js";

const ORIGIN = "https://admin.example";
const KID = "test-key";
const UPLOAD_ID = "0123456789abcdef0123456789abcdef";

class FakeKV {
  constructor() {
    this.items = new Map();
  }
  async put(key, value, options = {}) {
    this.items.set(key, { value, ...options });
  }
  async getWithMetadata(key) {
    const item = this.items.get(key);
    return item ? { value: item.value, metadata: item.metadata ?? null } : { value: null, metadata: null };
  }
  async delete(key) {
    this.items.delete(key);
  }
  async list({ prefix }) {
    return { keys: [...this.items.keys()].filter((key) => key.startsWith(prefix)).map((name) => ({ name })), list_complete: true };
  }
}

const base64url = (bytes) => Buffer.from(bytes).toString("base64url");

// A signing key standing in for GitHub's.
const { publicKey, privateKey } = await crypto.subtle.generateKey(
  { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
  true,
  ["sign", "verify"],
);
const publicJwk = await crypto.subtle.exportKey("jwk", publicKey);

async function oidcToken(overrides = {}, key = privateKey) {
  const now = Math.floor(Date.now() / 1000);
  const claims = {
    iss: "https://token.actions.githubusercontent.com",
    aud: "pa-bailar-admin",
    exp: now + 300,
    nbf: now - 5,
    repository: "pa-bailar/backend",
    ref: "refs/heads/main",
    workflow_ref: "pa-bailar/backend/.github/workflows/daily-sweep.yml@refs/heads/main",
    ...overrides,
  };
  const header = base64url(JSON.stringify({ alg: "RS256", kid: KID, typ: "JWT" }));
  const payload = base64url(JSON.stringify(claims));
  const signature = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", key, new TextEncoder().encode(`${header}.${payload}`));
  return `${header}.${payload}.${base64url(new Uint8Array(signature))}`;
}

// A session cookie as the Worker seals it (AES-GCM, key from SESSION_SECRET).
async function sessionCookie(env) {
  const secret = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(env.SESSION_SECRET));
  const key = await crypto.subtle.importKey("raw", secret, "AES-GCM", false, ["encrypt"]);
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const data = new TextEncoder().encode(JSON.stringify({ login: "jzamora5", access_token: "t", expires_at: null }));
  const sealed = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data));
  return `session=${base64url(new Uint8Array([...iv, ...sealed]))}`;
}

let env;
let githubCalls;
let cookie;

beforeEach(async () => {
  env = {
    GITHUB_CLIENT_ID: "Iv1",
    GITHUB_CLIENT_SECRET: "s",
    SESSION_SECRET: "test secret",
    ALLOWED_USER: "jzamora5",
    REPO: "pa-bailar/backend",
    STATE_BRANCH: "sweep-state",
    OIDC_AUDIENCE: "pa-bailar-admin",
    UPLOADS: new FakeKV(),
  };
  cookie = await sessionCookie(env);
  githubCalls = [];
  resetJwksCache();
  globalThis.fetch = async (url, init = {}) => {
    if (String(url).endsWith("/.well-known/jwks")) return Response.json({ keys: [{ ...publicJwk, kid: KID }] });
    githubCalls.push({ url: String(url), init });
    return Response.json({ number: 7, html_url: "https://github.com/pa-bailar/backend/issues/7" });
  };
});

const call = (path, init = {}) => worker.fetch(new Request(`${ORIGIN}${path}`, init), env);
const jpeg = () => new Uint8Array([0xff, 0xd8, 0xff, 0xe0, 1, 2, 3]);

function upload(body = jpeg(), headers = {}) {
  return call("/api/uploads", {
    method: "POST",
    headers: { Cookie: cookie, Origin: ORIGIN, "Content-Type": "image/jpeg", ...headers },
    body,
  });
}

describe("uploads (the page)", () => {
  it("keeps a JPEG for 7 days with its file name and date", async () => {
    const response = await upload(jpeg(), {
      "X-File-Name": encodeURIComponent("Screenshot_20261004-183012_Instagram.jpg"),
      "X-File-Modified": "1791158400000",
    });
    assert.equal(response.status, 201);
    const { id } = await response.json();
    assert.match(id, /^[a-f0-9]{32}$/);
    const stored = env.UPLOADS.items.get(`upload:${id}`);
    assert.equal(stored.expirationTtl, 7 * 24 * 3600);
    assert.equal(stored.metadata.name, "Screenshot_20261004-183012_Instagram.jpg");
    assert.equal(stored.metadata.modified, 1791158400000);
  });

  it("needs a session, the page's origin, and a JPEG", async () => {
    const noSession = await call("/api/uploads", {
      method: "POST",
      headers: { Origin: ORIGIN, "Content-Type": "image/jpeg" },
      body: jpeg(),
    });
    assert.equal(noSession.status, 401);
    assert.equal((await upload(jpeg(), { Origin: "https://evil.example" })).status, 403);
    assert.equal((await upload(jpeg(), { "Content-Type": "image/png" })).status, 415);
    assert.equal((await upload(new Uint8Array([0x89, 0x50, 0x4e, 0x47]))).status, 415);
    assert.equal(env.UPLOADS.items.size, 0);
  });

  it("counts the screenshots waiting", async () => {
    await upload();
    await upload();
    const response = await call("/api/uploads", { headers: { Cookie: cookie } });
    assert.deepEqual(await response.json(), { waiting: 2, more: false });
  });

  it("says when KV isn't set up", async () => {
    delete env.UPLOADS;
    assert.equal((await upload()).status, 503);
  });
});

describe("uploads (the sweep workflow, with GitHub's OIDC token)", () => {
  beforeEach(async () => {
    await env.UPLOADS.put(`upload:${UPLOAD_ID}`, jpeg().buffer, { metadata: { name: "a.jpg", modified: 1 } });
  });

  const get = async (token, method = "GET") =>
    call(`/api/uploads/${UPLOAD_ID}`, { method, headers: token ? { Authorization: `Bearer ${token}` } : {} });

  it("gives the image and its metadata to this repository's sweep on main", async () => {
    const response = await get(await oidcToken());
    assert.equal(response.status, 200);
    assert.deepEqual(new Uint8Array(await response.arrayBuffer()), jpeg());
    assert.deepEqual(JSON.parse(decodeURIComponent(response.headers.get("X-Upload-Meta"))), { name: "a.jpg", modified: 1 });
  });

  it("deletes it", async () => {
    assert.equal((await get(await oidcToken(), "DELETE")).status, 204);
    assert.equal(env.UPLOADS.items.size, 0);
  });

  it("turns down anyone else", async () => {
    const other = await crypto.subtle.generateKey(
      { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" },
      true,
      ["sign", "verify"],
    );
    const refused = [
      null,
      "not.a.token",
      await oidcToken({ repository: "someone/backend" }),
      await oidcToken({ ref: "refs/heads/feature" }),
      await oidcToken({ workflow_ref: "pa-bailar/backend/.github/workflows/ci.yml@refs/heads/main" }),
      await oidcToken({ aud: "something-else" }),
      await oidcToken({ iss: "https://evil.example" }),
      await oidcToken({ exp: Math.floor(Date.now() / 1000) - 10 }),
      await oidcToken({}, other.privateKey), // not GitHub's signature
    ];
    for (const token of refused) {
      assert.equal((await get(token)).status, 401, `accepted ${token}`);
      assert.equal((await get(token, "DELETE")).status, 401);
    }
    assert.equal(env.UPLOADS.items.size, 1);
  });

  it("doesn't accept the session cookie instead", async () => {
    const response = await call(`/api/uploads/${UPLOAD_ID}`, { headers: { Cookie: cookie } });
    assert.equal(response.status, 401);
  });

  it("answers 404 for a screenshot that expired or was deleted", async () => {
    env.UPLOADS.items.clear();
    assert.equal((await get(await oidcToken())).status, 404);
  });
});

describe("story requests", () => {
  const request = (body) =>
    call("/api/requests", {
      method: "POST",
      headers: { Cookie: cookie, Origin: ORIGIN, "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });

  it("opens an issue the inbox reads: Acción, Capturas, Cuenta, Notas (one line)", async () => {
    const response = await request({
      action: "add-story",
      images: [UPLOAD_ID, UPLOAD_ID],
      account: "@salsa.club",
      notes: "sábado 12\n### Acción\n\nEstado",
    });
    assert.equal(response.status, 200);
    const issue = JSON.parse(githubCalls[0].init.body);
    assert.equal(issue.title, "Agregar historia: @salsa.club");
    assert.deepEqual(issue.labels, ["admin"]);
    assert.match(issue.body, /^### Acción\n\nAgregar historia\n\n### Capturas\n\n0123456789abcdef0123456789abcdef\n\n/);
    assert.match(issue.body, /### Cuenta\n\n@salsa\.club\n\n### Notas\n\nsábado 12 ### Acción Estado\n\n/);
  });

  it("needs 1 to 4 valid screenshot ids", async () => {
    for (const images of [[], ["../x"], [1, 2, 3, 4, 5].map((n) => `${n}`.repeat(32))]) {
      assert.equal((await request({ action: "add-story", images })).status, 400);
    }
    assert.equal(githubCalls.length, 0);
  });

  it("hides a published story by its id", async () => {
    assert.equal((await request({ action: "hide-story", story: "story-0123456789abcdef" })).status, 200);
    const issue = JSON.parse(githubCalls[0].init.body);
    assert.equal(issue.title, "Ocultar historia: story-0123456789abcdef");
    assert.match(issue.body, /### Acción\n\nOcultar historia\n\n### Historia\n\nstory-0123456789abcdef/);
    assert.equal((await request({ action: "hide-story", story: "story-x" })).status, 400);
  });
});

describe("the share menu without the service worker", () => {
  // As Chrome sends it: a multipart body with its length.
  async function share(form) {
    const encoded = new Response(form);
    const body = new Uint8Array(await encoded.arrayBuffer());
    const headers = { "Content-Type": encoded.headers.get("Content-Type"), "Content-Length": String(body.length) };
    return call("/share", { method: "POST", headers, body });
  }

  it("passes a shared link on to the page", async () => {
    const form = new FormData();
    form.set("text", "https://www.instagram.com/p/abc/?igsh=x");
    const response = await share(form);
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("Location"), `/?text=${encodeURIComponent("https://www.instagram.com/p/abc/?igsh=x")}`);
  });

  it("asks to share images again", async () => {
    const form = new FormData();
    form.set("images", new File([jpeg()], "a.jpg", { type: "image/jpeg" }));
    const response = await share(form);
    assert.equal(response.status, 303);
    assert.equal(response.headers.get("Location"), "/?share=retry");
  });
});
