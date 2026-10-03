// The admin page's app icons (public/icons/*.png): the site's record (pa-bailar-web, pages/icons/[name].png.ts)
// on marigold instead of tomato, with a wrench badge, so it isn't mistaken for the site on the phone.
// Run: node admin-web/icons-src/make-icons.mjs (it uses sharp from the site's checkout next to this one).
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const sharp = createRequire(new URL("../../../pa-bailar-web/frontend/package.json", import.meta.url))("sharp");

const WINE = "#2A0F14"; // --wine-900
const RECORD = "#1E0A0E"; // --wine-950
const MARIGOLD = "#F2C12E"; // --marigold-400
const TOMATO = "#C8321C"; // --tomato-600

/** `recordShare`: the record's diameter as a share of the icon; `badge`: the wrench badge's center and radius. */
function iconSvg(recordShare, badge) {
  const r = 256 * recordShare;
  const grooves = [0.92, 0.82, 0.72, 0.62]
    .map((k) => `<circle cx="256" cy="256" r="${r * k}" fill="none" stroke="#fff" stroke-opacity="0.07" stroke-width="4"/>`)
    .join("");
  const scale = (badge.r * 1.15) / 24; // the wrench (Lucide, ISC) is drawn on a 24-unit grid
  const wrench = `<g transform="translate(${badge.c - 12 * scale} ${badge.c - 12 * scale}) scale(${scale})"
      fill="none" stroke="${MARIGOLD}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
      <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></g>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
    <rect width="512" height="512" fill="${MARIGOLD}"/>
    <circle cx="256" cy="256" r="${r}" fill="${RECORD}"/>
    ${grooves}
    <circle cx="256" cy="256" r="${r * 0.42}" fill="${TOMATO}"/>
    <circle cx="256" cy="256" r="${r * 0.1}" fill="${WINE}"/>
    <circle cx="${badge.c}" cy="${badge.c}" r="${badge.r + 12}" fill="${MARIGOLD}"/>
    <circle cx="${badge.c}" cy="${badge.c}" r="${badge.r}" fill="${WINE}"/>
    ${wrench}
  </svg>`;
}

const ICONS = {
  "192": { size: 192, recordShare: 0.82, badge: { c: 384, r: 92 } },
  "512": { size: 512, recordShare: 0.82, badge: { c: 384, r: 92 } },
  // Phones cut maskable icons to their own shape; only the middle 80% is sure to show.
  "maskable-512": { size: 512, recordShare: 0.66, badge: { c: 345, r: 64 } },
};

const out = new URL("../public/icons/", import.meta.url);
for (const [name, icon] of Object.entries(ICONS)) {
  await sharp(Buffer.from(iconSvg(icon.recordShare, icon.badge)))
    .resize(icon.size, icon.size)
    .png()
    .toFile(fileURLToPath(new URL(`${name}.png`, out)));
}
console.log("icons written");
