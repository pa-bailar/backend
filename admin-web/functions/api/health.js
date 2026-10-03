// GET /api/health: the server functions are deployed (Cloudflare Pages Functions, docs/ADMIN.md).
export function onRequestGet() {
  return Response.json({ ok: true });
}
