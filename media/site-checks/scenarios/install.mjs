// Installing on iPhone (site's views/installPrompt.ts, lib/installPlace.ts): Safari 26's sheet with its clip, which loads
// only when the sheet opens and stops when it closes, never stored by the service worker, only its poster with reduced
// motion; the buttons to tap and no written steps; the arrow at the bottom right (⋯); the footer's "Cómo instalar…"
// link, always there, even after "Ya la agregué". The "iphone" device is Safari 26 (its user agent says Version/26.x).
export default {
  name: "install",
  summary: "iPhone: the steps' clip loads only with the sheet and stops with it (poster only with reduced motion), the taps, the arrow, the footer's link after Ya la agregué",
  devices: ["iphone"],
  async run(ctx) {
    const { page, check } = ctx;
    const clips = [];
    page.on("request", (r) => {
      if (/\/install\/.+\.mp4/.test(r.url())) clips.push(r.url());
    });
    const sheet = () =>
      page.evaluate(() => {
        const video = document.getElementById("install-clip");
        const pointer = document.getElementById("install-pointer");
        return {
          open: document.getElementById("install-sheet").open,
          src: video.getAttribute("src") ?? "",
          poster: video.getAttribute("poster") ?? "",
          clipShown: !video.hidden && video.getBoundingClientRect().height > 0,
          taps: [...document.querySelectorAll("#install-taps li")].map((li) => li.textContent.trim()),
          writtenSteps: !document.getElementById("install-steps").hidden,
          pointer: pointer.hidden ? null : pointer.dataset.at,
          fits: (() => {
            const s = document.getElementById("install-sheet");
            return s.scrollHeight <= s.clientHeight + 1;
          })(),
        };
      });

    await ctx.goto("/");
    check("no clip loaded before the sheet opens", clips.length === 0, clips);

    await ctx.goto("/?instalar");
    let s = await sheet();
    check("?instalar opens the steps by themselves", s.open, s);
    check("Safari 26's clip and poster", /safari-26\.mp4$/.test(s.src) && /safari-26\.jpg$/.test(s.poster), s);
    check("the clip is shown", s.clipShown, s);
    check("the taps, in order", s.taps.join(" · ") === "Más, abajo a la derecha · Compartir · Ver más · Agregar a Inicio · Agregar", s.taps);
    check("no written steps", !s.writtenSteps, s);
    check("the arrow at the bottom right (⋯)", s.pointer === "bottom-right", s);
    check("everything fits without scrolling the sheet", s.fits, s);
    await ctx.shot("sheet");

    await ctx.tap('#install-sheet [data-close-sheet]');
    s = await sheet();
    check("closing the sheet drops the clip", !s.open && s.src === "", s);

    const stored = await page.evaluate(async () => {
      if (!("caches" in self)) return [];
      const urls = [];
      for (const name of await caches.keys()) for (const r of await (await caches.open(name)).keys()) urls.push(r.url);
      return urls.filter((u) => /\/install\//.test(u));
    });
    check("the service worker stores no clip", stored.length === 0, stored);

    // "Ya la agregué", then the footer's link still opens the steps
    await ctx.goto("/?instalar");
    await ctx.tap("#install-done");
    const banner = await page.evaluate(() => document.getElementById("install-banner").hidden);
    check("Ya la agregué hides the banner", banner);
    const howTo = page.locator("[data-install-howto]:not([hidden]) button");
    check("the footer's link stays", (await howTo.count()) === 1 && /iPhone/.test(await howTo.textContent()));
    await ctx.tap(howTo);
    s = await sheet();
    check("…and opens the steps", s.open && /safari-26\.mp4$/.test(s.src), s);
    await ctx.tap('#install-sheet [data-close-sheet]');

    // Reduced motion: the poster, no clip
    await page.emulateMedia({ reducedMotion: "reduce" });
    clips.length = 0;
    await ctx.tap(howTo);
    s = await sheet();
    check("reduced motion: the poster only", s.open && s.src === "" && /safari-26\.jpg$/.test(s.poster), s);
    check("reduced motion: no clip loaded", clips.length === 0, clips);
  },
};
