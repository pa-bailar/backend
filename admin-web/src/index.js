// The admin page's server side (Cloudflare Worker). Static files in public/ are served before this runs, so
// only what they don't cover arrives here: the API. The sign-in with GitHub will live here too (docs/ADMIN.md).

export default {
  async fetch(request) {
    const { pathname } = new URL(request.url);
    if (pathname === "/api/health") return Response.json({ ok: true });
    return new Response("Not found", { status: 404 });
  },
};
