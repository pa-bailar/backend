// @ts-check
// The admin page's two tabs (docs/ADMIN.md): "Estadísticas", what the last sweep left (read only), and
// "Herramientas", everything that changes something. Only the choices and the markup live here, without the
// browser, so the tests can check them in Node (test/tabs.test.mjs); app.js wires them to the page.

import { escapeHtml } from "./render.js";

export const TABS = [
  { id: "estadisticas", label: "Estadísticas" },
  { id: "herramientas", label: "Herramientas" },
];

/** Where the last tab picked is remembered (localStorage), for the next visit. */
export const TAB_KEY = "admin-tab";

const IDS = TABS.map((tab) => tab.id);

/**
 * The tab a URL hash names (#estadisticas, #herramientas), or null.
 * @param {unknown} hash
 * @returns {string | null}
 */
export function tabFromHash(hash) {
  const id = String(hash ?? "").replace(/^#/, "").toLowerCase();
  return IDS.includes(id) ? id : null;
}

/**
 * The tab to open: "Herramientas" when something was shared to the page (a link, story screenshots: they wait
 * there); else the one the URL's hash names; else the one picked last time; else the first.
 * @param {{ shared?: boolean, hash?: string, stored?: string | null }} [choices]
 * @returns {string}
 */
export function initialTab({ shared = false, hash = "", stored = null } = {}) {
  if (shared) return "herramientas";
  return tabFromHash(hash) ?? (stored && IDS.includes(stored) ? stored : IDS[0]);
}

/**
 * The tab a key moves to from `current` (←/→ wrap around, Home, End), or null for any other key.
 * @param {string} current
 * @param {string} key
 */
export function tabAfterKey(current, key) {
  const index = Math.max(0, IDS.indexOf(current));
  switch (key) {
    case "ArrowRight":
      return IDS[(index + 1) % IDS.length];
    case "ArrowLeft":
      return IDS[(index - 1 + IDS.length) % IDS.length];
    case "Home":
      return IDS[0];
    case "End":
      return IDS.at(-1);
    default:
      return null;
  }
}

/**
 * The tab bar and its panels, with `selected` open and the others hidden. `panels` is {id: html}; `badges` is
 * {id: number}, a count shown on a tab (new series waiting in Herramientas), nothing when 0.
 * @param {string} selected
 * @param {Record<string, string>} panels
 * @param {Record<string, number>} [badges]
 */
export function tabsHtml(selected, panels, badges = {}) {
  const tabs = TABS.map(({ id, label }) => {
    const on = id === selected;
    const count = Number(badges[id]) || 0;
    const badge = count
      ? ` <span class="tab__badge" aria-hidden="true">${count}</span><span class="visually-hidden"> (${count} ${count === 1 ? "serie nueva" : "series nuevas"})</span>`
      : "";
    return `<button class="tab" type="button" role="tab" id="tab-${id}" data-tab="${id}" aria-controls="panel-${id}"
      aria-selected="${on}" tabindex="${on ? 0 : -1}">${escapeHtml(label)}${badge}</button>`;
  }).join("");
  const sections = TABS.map(
    ({ id }) => `<div class="tabpanel" role="tabpanel" id="panel-${id}" aria-labelledby="tab-${id}" tabindex="0"${
      id === selected ? "" : " hidden"
    }>${panels[id] ?? ""}</div>`,
  ).join("");
  return `<div class="tabs" role="tablist" aria-label="Secciones">${tabs}</div>${sections}`;
}
