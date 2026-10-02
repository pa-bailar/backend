// Theme modes, like macOS "Auto":
//   auto  → "Fania de día" (light) from 6:00 to 17:59 and "Noche Fania" (dark) the rest of the day,
//           by the visitor's clock, switching on its own while the page is open
//   light → always light
//   dark  → always dark
// The toggle cycles auto → light → dark → auto; the choice is remembered (auto is the default).
// BaseLayout.astro has an inline copy of resolveTheme() that applies the theme before first paint;
// keep both in sync (DAY_START_HOUR, NIGHT_START_HOUR, THEME_COLORS).

import { byId } from "./lib/dom";

type Mode = "auto" | "light" | "dark";
type Theme = "light" | "dark";

const STORAGE_KEY = "theme";
const MODES: Mode[] = ["auto", "light", "dark"];
const DAY_START_HOUR = 6;
const NIGHT_START_HOUR = 18;
const RECHECK_MS = 60_000;
/** Browser UI color (address bar on phones) per theme: the page background token. */
const THEME_COLORS: Record<Theme, string> = { light: "#ECDDC6", dark: "#2A0F14" };
const MODE_LABELS: Record<Mode, string> = { auto: "Auto", light: "Día", dark: "Noche" };
const THEME_NAMES: Record<Theme, string> = { light: "día", dark: "noche" };

function savedMode(): Mode {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : "auto";
  } catch {
    return "auto"; // storage blocked (private mode, etc.)
  }
}

function saveMode(mode: Mode) {
  try {
    if (mode === "auto") localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, mode);
  } catch {
    // Not persisted; still applies for this visit.
  }
}

export function timeOfDayTheme(now = new Date()): Theme {
  const hour = now.getHours();
  return hour >= DAY_START_HOUR && hour < NIGHT_START_HOUR ? "light" : "dark";
}

function resolveTheme(mode: Mode): Theme {
  return mode === "auto" ? timeOfDayTheme() : mode;
}

function apply(mode: Mode, button: HTMLButtonElement) {
  const theme = resolveTheme(mode);
  const root = document.documentElement;
  root.dataset.theme = theme;
  root.dataset.themeMode = mode;
  document.querySelector<HTMLMetaElement>('meta[name="theme-color"]')?.setAttribute("content", THEME_COLORS[theme]);

  const next = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
  button.querySelector(".theme-label")!.textContent = MODE_LABELS[mode];
  const current = mode === "auto" ? `automático (ahora ${THEME_NAMES[theme]})` : THEME_NAMES[theme];
  button.setAttribute("aria-label", `Tema: ${current}. Cambiar a ${MODE_LABELS[next].toLowerCase()}`);
}

export function initThemeToggle() {
  const button = byId<HTMLButtonElement>("theme-toggle");
  let mode = savedMode();
  apply(mode, button);

  button.addEventListener("click", () => {
    mode = MODES[(MODES.indexOf(mode) + 1) % MODES.length];
    saveMode(mode);
    apply(mode, button);
  });

  // In auto mode, switch at 6:00 and 18:00 while the page stays open, and when coming back to it.
  const recheck = () => {
    if (mode === "auto") apply(mode, button);
  };
  setInterval(recheck, RECHECK_MS);
  document.addEventListener("visibilitychange", recheck);
}
