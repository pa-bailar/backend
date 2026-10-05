// The admin page's service worker (docs/ADMIN.md): it only receives what Android's share menu sends to the
// installed page (manifest.webmanifest's share_target posts it to /share). Nothing else goes through it: no
// offline copy, so the page is always the deployed one.
//   - Images (story screenshots, up to MAX_FILES): kept in this browser's Cache Storage (SHARED_CACHE), where
//     app.js picks them up, also after signing in again. They never leave the phone until "Agregar desde historia".
//   - A link or text: passed on to the page as ?title=&text=&url= (app.js reads them as it always did).
// Without this worker running (the first share after installing), /share reaches the Worker (src/index.js),
// which passes links on and asks to share images again.

const SHARED_CACHE = "shared-images";
const MAX_FILES = 4; // patterns.js's MAX_SCREENSHOTS (a classic script can't import it): test/patterns.test.mjs
const IMAGE_NAME = /\.(jpe?g|png|webp|heic|heif|gif)$/i;

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method === "POST" && url.origin === self.location.origin && url.pathname === "/share") {
    event.respondWith(receiveShare(event.request));
  }
});

const page = (query) => Response.redirect(new URL(`/?${query}`, self.location.origin).href, 303);

async function receiveShare(request) {
  let form;
  try {
    form = await request.formData();
  } catch {
    return page("share=retry");
  }
  const params = new URLSearchParams();
  for (const name of ["title", "text", "url"]) {
    const value = form.get(name);
    if (typeof value === "string" && value.trim()) params.set(name, value.slice(0, 2000));
  }
  const files = form
    .getAll("images")
    .filter((file) => file instanceof File && (file.type.startsWith("image/") || IMAGE_NAME.test(file.name)));
  if (files.length) {
    try {
      await keep(files);
      params.set("share", "images");
    } catch {
      params.set("share", "retry");
    }
  }
  return page(params.toString());
}

/** Add the shared images to the ones already waiting (a story shared one screenshot at a time), newest MAX_FILES. */
async function keep(files) {
  const cache = await caches.open(SHARED_CACHE);
  const at = Date.now();
  await Promise.all(
    files.slice(0, MAX_FILES).map((file, index) =>
      cache.put(
        `/shared/${at}-${index}`,
        new Response(file, {
          headers: {
            "Content-Type": file.type || "image/jpeg",
            "X-Name": encodeURIComponent(file.name || ""),
            "X-Modified": String(file.lastModified || ""),
            "X-At": String(at),
          },
        }),
      ),
    ),
  );
  const keys = await cache.keys(); // in insertion order: oldest first
  await Promise.all(keys.slice(0, Math.max(0, keys.length - MAX_FILES)).map((key) => cache.delete(key)));
}
