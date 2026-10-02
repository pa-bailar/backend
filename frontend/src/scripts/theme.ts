// Light ("Fania de día") / dark ("Noche Fania") theme switch.
// Default: the device setting. A choice made with the toggle is remembered in localStorage.
// The saved choice is applied before first paint by an inline script in BaseLayout.astro.

import { byId } from "./lib/dom";

type Theme = "light" | "dark";

const STORAGE_KEY = "theme";
const LABELS: Record<Theme, string> = { light: "Día", dark: "Noche" };
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");

function savedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === "light" || value === "dark" ? value : null;
  } catch {
    return null; // storage blocked (private mode, etc.)
  }
}

function activeTheme(): Theme {
  return savedTheme() ?? (darkQuery.matches ? "dark" : "light");
}

function applyTheme(theme: Theme, button: HTMLButtonElement) {
  const root = document.documentElement;
  if (savedTheme()) root.dataset.theme = theme;
  root.dataset.activeTheme = theme;
  const next: Theme = theme === "dark" ? "light" : "dark";
  button.querySelector(".theme-label")!.textContent = LABELS[next];
  button.setAttribute("aria-label", `Cambiar a tema ${LABELS[next].toLowerCase()}`);
}

export function initThemeToggle() {
  const button = byId<HTMLButtonElement>("theme-toggle");
  applyTheme(activeTheme(), button);

  button.addEventListener("click", () => {
    const next: Theme = activeTheme() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not persisted; still switch for this visit.
    }
    document.documentElement.dataset.theme = next;
    applyTheme(next, button);
  });

  // Follow the device setting live while the visitor hasn't chosen one.
  darkQuery.addEventListener("change", () => {
    if (!savedTheme()) applyTheme(activeTheme(), button);
  });
}
