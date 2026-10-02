// WCAG 2.2 contrast check for every color pair the site uses, in both themes.
// Reads the tokens from src/styles/tokens.css, so it stays in sync with the design system.
// Usage: node scripts/check-contrast.mjs   (exits 1 if any pair fails; run by `npm run check`)

import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../src/styles/tokens.css", import.meta.url), "utf8");

// ---------- token resolution ----------

const declarations = new Map();
for (const [, name, value] of css.matchAll(/--([\w-]+):\s*([^;]+);/g)) {
  if (!declarations.has(name)) declarations.set(name, value.trim());
}

/** Resolve a token to a hex color for "light" or "dark". */
function resolve(token, theme, depth = 0) {
  if (depth > 10) throw new Error(`Token loop at --${token}`);
  const value = declarations.get(token);
  if (!value) throw new Error(`Unknown token --${token}`);
  const lightDark = value.match(/^light-dark\((.+),\s*(var\(--[\w-]+\)|#[0-9a-f]{3,8}|rgb\([^)]*\))\)$/i);
  if (lightDark) return resolveValue(theme === "light" ? lightDark[1] : lightDark[2], theme, depth);
  return resolveValue(value, theme, depth);
}

function resolveValue(value, theme, depth) {
  const reference = value.trim().match(/^var\(--([\w-]+)\)$/);
  if (reference) return resolve(reference[1], theme, depth + 1);
  if (/^#[0-9a-f]{6}$/i.test(value.trim())) return value.trim().toLowerCase();
  throw new Error(`Unsupported color value: ${value}`);
}

// ---------- WCAG math ----------

function channel(c) {
  const s = c / 255;
  return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

function rgb(hex) {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
}

function luminance(hex) {
  const [r, g, b] = rgb(hex).map(channel);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a, b) {
  const [l1, l2] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (l1 + 0.05) / (l2 + 0.05);
}

const MINIMUM = { text: 4.5, large: 3, ui: 3 };

// ---------- the pairs the components actually use ----------
// [what, foreground token, background token, kind]
// Not listed on purpose: --divider (decorative separators) and the stripes (brand motif).
const TYPES = ["social", "workshop", "concert", "festival", "competition", "show", "other"];
const PAIRS = [
  ["Body text on page", "text", "bg", "text"],
  ["Body text on cards / dialog", "text", "surface", "text"],
  ["Body text on callout", "text", "surface-sunken", "text"],
  ["Muted text on page (updated date, footer, inactive tabs and chips)", "text-muted", "bg", "text"],
  ["Muted text on cards (meta, styles, labels, caption)", "text-muted", "surface", "text"],
  ["Muted text on image well (no-flyer placeholder, large)", "text-muted", "surface-sunken", "large"],
  ["Italic accent on page (tagline)", "text-italic", "bg", "text"],
  ["Italic accent on dialog (subheading)", "text-italic", "surface", "text"],
  ["Logo on page (large)", "logo", "bg", "large"],
  ["Logo on page, 404 (large)", "logo", "bg", "large"],
  ["Accent text on cards (event time, 13px bold)", "accent", "surface", "text"],
  ["Primary button text", "on-action", "action", "text"],
  ["WhatsApp button text", "on-whatsapp", "whatsapp", "text"],
  ["Selected chip text", "chip-active-text", "chip-active-bg", "text"],
  ["Date sticker text", "sticker-text", "sticker-bg", "text"],
  ["Today number in calendar", "today-text", "today-bg", "text"],
  ["Calendar day number", "text", "surface", "text"],
  ["Past calendar day number (muted; past cells have no fill)", "text-muted", "bg", "text"],
  ...TYPES.map((t) => [`Type tag / calendar pill text on ${t}`, "on-type", `type-${t}`, "text"]),
  // Non-text (WCAG 1.4.11): boundaries and indicators people need to see.
  ["Card / chip / button outline on page", "border", "bg", "ui"],
  ["Card outline on card surface edge", "border", "surface", "ui"],
  ["Focus ring on page", "focus", "bg", "ui"],
  ["Focus ring on cards", "focus", "surface", "ui"],
  ["Active tab underline on page", "accent", "bg", "ui"],
  ["Selected calendar day border on cell", "accent", "surface", "ui"],
  ["Selected chip fill on page", "chip-active-bg", "bg", "ui"],
  ["Primary button fill on dialog", "action", "surface", "ui"],
  ["Calendar dot outline on day cell (fill color is decorative)", "border", "surface", "ui"],
];

// ---------- run ----------

let failures = 0;
for (const theme of ["light", "dark"]) {
  console.log(`\n${theme === "light" ? "Fania de día (light)" : "Noche Fania (dark)"}`);
  for (const [what, fgToken, bgToken, kind] of PAIRS) {
    const [fg, bg] = [resolve(fgToken, theme), resolve(bgToken, theme)];
    const ratio = contrast(fg, bg);
    const ok = ratio >= MINIMUM[kind];
    if (!ok) failures++;
    const mark = ok ? "ok  " : "FAIL";
    console.log(`  ${mark} ${ratio.toFixed(2).padStart(5)}:1 (min ${MINIMUM[kind]})  ${what}  [${fg} on ${bg}]`);
  }
}
console.log(failures ? `\n${failures} pair(s) below WCAG AA.` : "\nAll pairs meet WCAG AA.");
process.exit(failures ? 1 : 0);
