// The canvas and the brand's design tokens for video. Colors come from pa-bailar-web/frontend/src/styles/tokens.css,
// the light theme "Fania de día" (the owner prefers it for video). Values that only one video uses belong in its
// own folder (projects/<name>/), not here.
import type React from "react";

/** Instagram Stories and Reels: 1080×1920 at 30 fps. */
export const FPS = 30;
export const WIDTH = 1080;
export const HEIGHT = 1920;

/**
 * Safe zones (Instagram's UI covers the rest): no text above `top` (progress bar, account) or below `bottom` (reply
 * bar, link sticker, Reel caption), nor closer than `side` to the edges. Images may run into them; words never do.
 */
export const SAFE = { top: 250, bottom: HEIGHT - 340, side: 80 };

/** Seconds → frames (rounded). */
export const sec = (s: number, fps = FPS) => Math.round(s * fps);

export const C = {
  // Surfaces: aged offset paper
  paper: "#ecddc6", // --bg (cream-150)
  card: "#f7eddc", // --surface (cream-75)
  sunken: "#e2d1b6", // cream-250
  cream50: "#fff8ec",
  cream300: "#d9c6aa", // --divider, --period-shadow
  // Text
  wine950: "#1e0a0e",
  wine900: "#2a0f14", // --text
  wine500: "#6e2a33", // --text-italic
  cocoa500: "#6e4a44", // --text-muted
  // Brand
  tomato700: "#b02a17", // --period-title
  tomato600: "#c8321c", // --logo, --accent, --sticker-bg, the app icon
  orange600: "#e8791c",
  marigold600: "#e9b021",
  marigold400: "#f2c12e", // the record label
  // A phone (a device, not the page)
  bezel: "#1e1617",
  bezelEdge: "#3a2f2e",
};

/** The 70s triple stripe, --stripe-1..3 in light. */
export const STRIPES = [C.tomato600, C.orange600, C.marigold600];

export const FONT = {
  display: "Shrikhand",
  serif: "Bodoni Moda",
  sans: "Instrument Sans",
  emoji: "'Segoe UI Emoji', 'Noto Color Emoji', 'Apple Color Emoji', sans-serif",
};

/**
 * Type presets at 1080 wide. The serif uses a small optical size and weight 600: Bodoni Moda's display cut has
 * 1–2 px hairlines that vanish under grain and H.264's chroma subsampling.
 */
export const TYPE = {
  /** Titles and the wordmark (112–168 px), with the site's period-heading offset shadow. */
  display: (size: number, color = C.wine900, shadow = C.cream300): React.CSSProperties => ({
    fontFamily: FONT.display,
    fontSize: size,
    lineHeight: 1.06,
    color,
    textShadow: `${size >= 160 ? 8 : 6}px ${size >= 160 ? 8 : 6}px 0 ${shadow}`,
  }),
  /** The second line of a thought, a tagline, a sign-off (64–76 px). */
  serif: (size: number, color = C.wine500): React.CSSProperties => ({
    fontFamily: FONT.serif,
    fontStyle: "italic",
    fontWeight: 600,
    fontVariationSettings: "'opsz' 18",
    fontSize: size,
    color,
  }),
  /** Calls to action and UI-like labels (~64 px). */
  sans: (size: number, color = C.wine900): React.CSSProperties => ({
    fontFamily: FONT.sans,
    fontWeight: 600,
    fontSize: size,
    color,
  }),
};
