// @ts-check
// Pieces of the admin page that only turn data into HTML, kept apart from app.js (which needs the browser) so
// the tests can check them in Node (test/render.test.mjs). Everything that comes from the data is escaped.

/**
 * One new workshop series, as status.json's `new_series` lists it (pa_bailar/status.py new_series).
 * @typedef {{ id: string, title: string, account: string, sessions: string, url?: string | null,
 *   sources?: { kind: string, link?: string | null }[] }} Series
 */

/**
 * Text made safe for HTML, in an element or an attribute.
 * @param {unknown} text
 */
export const escapeHtml = (text) => String(text ?? "").replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);

/**
 * Only http(s) links are linked (a link in the data could be anything).
 * @param {unknown} link
 * @returns {string | null}
 */
const safeLink = (link) => (/^https?:\/\//i.test(String(link ?? "")) ? String(link) : null);

/**
 * "Series nuevas": workshop series first published in the last two weeks (status.json's `new_series`,
 * pa_bailar/status.py new_series), each with its sessions, where it came from, its link on the site, and a one-tap
 * "Ocultar" (data-hide-event, handled in app.js: it opens a hide-event request). Empty when there are none.
 * @param {Series[] | null | undefined} series
 */
export function seriesCard(series) {
  if (!Array.isArray(series) || !series.length) return "";
  const items = series
    .map((item) => {
      const sources = (item.sources ?? [])
        .map((source) => {
          const link = safeLink(source.link);
          const label = source.kind === "story" ? "historia" : "publicación";
          return link ? `<a href="${escapeHtml(link)}" target="_blank" rel="noopener">${label}</a>` : "";
        })
        .filter(Boolean)
        .join(", ");
      const site = safeLink(item.url);
      const title = site
        ? `<a href="${escapeHtml(site)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>`
        : escapeHtml(item.title);
      return `<li class="series__item">
        <div><b>${title}</b> <span class="muted">@${escapeHtml(item.account)}</span></div>
        <div class="small">${escapeHtml(item.sessions)}${sources ? ` · de ${sources}` : ""}</div>
        <div class="tool__buttons"><button class="button button--outline" type="button"
          data-hide-event="${escapeHtml(item.id)}" data-title="${escapeHtml(item.title)}">Ocultar del sitio</button></div>
      </li>`;
    })
    .join("");
  return `<section class="card"><h2>Series nuevas</h2>
    <p class="small muted">Talleres en varias fechas publicados en las últimas dos semanas: revisa que estén bien.
      Ocultar los quita del sitio y los barridos no los vuelven a publicar.</p>
    <ul class="series">${items}</ul></section>`;
}

const WEEKDAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const SHORT_WEEKDAYS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];
const MONTHS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];

/**
 * A moment in Bogotá time, as the owner reads it: "hoy 9:00 p. m.", "ayer 9:12 a. m.", "sábado 4/10, 9:00 a. m.".
 * @param {string} iso
 * @param {Date} [now]
 */
export function when(iso, now = new Date()) {
  const bogota = (/** @type {Date} */ date) => new Date(date.toLocaleString("en-US", { timeZone: "America/Bogota" }));
  const moment = bogota(new Date(iso));
  const today = bogota(now);
  const hours = moment.getHours();
  const hour = `${hours % 12 || 12}:${String(moment.getMinutes()).padStart(2, "0")} ${hours < 12 ? "a. m." : "p. m."}`;
  const startOfDay = (/** @type {Date} */ date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((startOfDay(moment) - startOfDay(today)) / 86_400_000);
  if (days === 0) return `hoy ${hour}`;
  if (days === -1) return `ayer ${hour}`;
  if (days === 1) return `mañana ${hour}`;
  return `${WEEKDAYS[moment.getDay()]} ${moment.getDate()}/${moment.getMonth() + 1}, ${hour}`;
}

/**
 * An event's day, short: "2026-10-11" → "sáb 11 oct". Anything else, as it is (escaped by the caller).
 * @param {unknown} day
 */
export function shortDate(day) {
  const parts = String(day ?? "").match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!parts) return String(day ?? "");
  const date = new Date(Date.UTC(Number(parts[1]), Number(parts[2]) - 1, Number(parts[3])));
  return `${SHORT_WEEKDAYS[date.getUTCDay()]} ${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]}`;
}

/**
 * One change in a run, as status.json's `history` lists it (pa_bailar/status.py history_of, changes.py).
 * @typedef {{ kind: string, id: string, title: string, account: string, date?: string | null,
 *   detail?: string | null, url?: string | null }} Change
 * One run in the history: a sweep (its `slot`, "06:30" or "21:00", or none: an extra one) or an admin request.
 * `changes` is null for a run recorded before they were kept ("sin detalle").
 * @typedef {{ kind: string, slot?: string | null, finished_at: string, run_url?: string | null,
 *   target?: string | null, error?: string | null, changes?: Change[] | null, left_out?: number,
 *   counts?: Record<string, number> }} HistoryRun
 */

/**
 * What can happen to an event (changes.py ChangeKind), in the order a run's summary lists them: its label, the
 * summary's words (one, many) and its color (`tone`). `onSite`: the event is on the site after it, so it's linked.
 * @type {Record<string, { label: string, one: string, many: string, tone: string, onSite: boolean }>}
 */
export const CHANGE_KINDS = {
  cancelled: { label: "Cancelado", one: "cancelado", many: "cancelados", tone: "off", onSite: false },
  flagged: { label: "Revisar", one: "por revisar", many: "por revisar", tone: "wait", onSite: true },
  hidden: { label: "Oculto", one: "oculto", many: "ocultos", tone: "off", onSite: false },
  restored: { label: "Restaurado", one: "restaurado", many: "restaurados", tone: "add", onSite: true },
  new: { label: "Nuevo", one: "nuevo", many: "nuevos", tone: "add", onSite: true },
  provisional: { label: "Provisional", one: "provisional", many: "provisionales", tone: "wait", onSite: true },
  corrected: { label: "Corregido", one: "corregido", many: "corregidos", tone: "fix", onSite: true },
  updated: { label: "Actualizado", one: "actualizado", many: "actualizados", tone: "fix", onSite: true },
  dropped: { label: "Quitado", one: "quitado", many: "quitados", tone: "off", onSite: false },
  merged: { label: "Unido", one: "unido", many: "unidos", tone: "merge", onSite: true },
  duplicate: { label: "Duplicado", one: "duplicado unido", many: "duplicados unidos", tone: "merge", onSite: true },
  kept_hidden: { label: "Sigue oculto", one: "sigue oculto", many: "siguen ocultos", tone: "quiet", onSite: false },
  reread: { label: "Releído", one: "releído", many: "releídos", tone: "quiet", onSite: true },
  archived: { label: "Archivado", one: "archivado", many: "archivados", tone: "quiet", onSite: false },
};

/**
 * The admin requests that run in the sweep workflow (changes.py AdminAction).
 * @type {Record<string, string>}
 */
const REQUESTS = {
  post: "Agregar publicación",
  post_again: "Volver a leer",
  story: "Agregar historia",
  hide_event: "Ocultar evento",
  hide_story: "Ocultar historia",
};

/**
 * What ran: "Barrido de la madrugada" (the 3:00 sweep), "Barrido de la mañana" (6:30), "Barrido de la noche" (21:00),
 * "Barrido extra" (by hand),
 * or the admin request ("Agregar publicación"…).
 * @param {HistoryRun} run
 */
export function runLabel(run) {
  if (run.kind !== "sweep") return Object.hasOwn(REQUESTS, run.kind) ? REQUESTS[run.kind] : "Pedido";
  const hour = Number(String(run.slot ?? "").split(":")[0]);
  if (!run.slot || Number.isNaN(hour)) return "Barrido extra";
  if (hour < 5) return "Barrido de la madrugada";
  return hour < 12 ? "Barrido de la mañana" : hour < 18 ? "Barrido de la tarde" : "Barrido de la noche";
}

/**
 * A run's summary: "3 nuevos · 2 unidos · 1 corregido", in CHANGE_KINDS' order; "Sin cambios" when none.
 * @param {Record<string, number> | null | undefined} counts
 */
export function changesSummary(counts) {
  const parts = Object.entries(CHANGE_KINDS)
    .filter(([kind]) => Number(counts?.[kind]) > 0)
    .map(([kind, words]) => {
      const number = Number(counts?.[kind]);
      return `${number} ${number === 1 ? words.one : words.many}`;
    });
  return parts.length ? parts.join(" · ") : "Sin cambios";
}

/** @param {Change} item */
function changeItem(item) {
  const kind = Object.hasOwn(CHANGE_KINDS, item.kind) ? CHANGE_KINDS[item.kind] : null;
  const label = kind ? kind.label : item.kind;
  const link = kind?.onSite ? safeLink(item.url) : null;
  const title = link
    ? `<a class="change__title" href="${escapeHtml(link)}" target="_blank" rel="noopener">${escapeHtml(item.title)}</a>`
    : `<span class="change__title">${escapeHtml(item.title)}</span>`;
  const meta = [`@${escapeHtml(item.account)}`, item.date ? escapeHtml(shortDate(item.date)) : ""].filter(Boolean);
  const detail = item.detail ? `<span class="change__detail">${escapeHtml(item.detail)}</span>` : "";
  return `<li class="change">
      <span class="tag tag--${kind ? kind.tone : "quiet"}">${escapeHtml(label)}</span>
      <span class="change__body">${title}<span class="change__meta">${meta.join(" · ")}</span>${detail}</span>
    </li>`;
}

/**
 * One run, collapsible: what ran, when and its summary; open, what it did to which event.
 * @param {HistoryRun} run
 * @param {boolean} open
 * @param {Date} now
 */
function historyRun(run, open, now) {
  const summary = run.error ? "No se pudo" : changesSummary(run.counts);
  let body;
  if (run.error) body = `<p class="small warn">⚠️ ${escapeHtml(run.error)}</p>`;
  else if (!Array.isArray(run.changes)) body = `<p class="small muted">Sin detalle: es de antes del historial.</p>`;
  else if (!run.changes.length) body = `<p class="small muted">Ningún evento cambió.</p>`;
  else body = `<ul class="changes">${run.changes.map(changeItem).join("")}</ul>`;
  const leftOut = Number(run.left_out) > 0 ? `<p class="small muted">Y ${escapeHtml(run.left_out)} más, solo contados.</p>` : "";
  // What a request was about: a post's link; an event's or a story's id only when no change already names it.
  const target = safeLink(run.target);
  const named = !target && run.target && !run.changes?.length;
  const links = [
    target ? `<a href="${escapeHtml(target)}" target="_blank" rel="noopener">la publicación</a>` : "",
    named ? `<code>${escapeHtml(run.target)}</code>` : "",
    safeLink(run.run_url) ? `<a href="${escapeHtml(run.run_url)}" target="_blank" rel="noopener">ver en GitHub</a>` : "",
  ].filter(Boolean);
  const footer = links.length ? `<p class="run__links small muted">${links.join(" · ")}</p>` : "";
  return `<details class="run"${open ? " open" : ""}>
    <summary class="run__summary">
      <span class="run__what">${escapeHtml(runLabel(run))}</span>
      <span class="run__when">${escapeHtml(when(run.finished_at, now))}</span>
      <span class="run__counts${run.error ? " warn" : ""}">${escapeHtml(summary)}</span>
    </summary>
    <div class="run__body">${body}${leftOut}${footer}</div>
  </details>`;
}

/**
 * "Historial": the latest sweeps and admin requests (status.json's `history`), newest first, each a collapsible
 * row (native <details>: no script) that opens to what happened to which event. The section itself is collapsed
 * until opened; inside it, the newest run is open. Empty when status.json has no history (older backends).
 * @param {HistoryRun[] | null | undefined} history
 * @param {Date} [now]
 */
export function historyCard(history, now = new Date()) {
  if (!Array.isArray(history)) return "";
  const runs = history.length
    ? history.map((run, index) => historyRun(run, index === 0, now)).join("")
    : `<p class="small muted">Todavía no hay nada registrado: aparece después del próximo barrido.</p>`;
  return `<details class="card history">
    <summary class="history__summary"><h2>Historial</h2>
      <span class="small muted">Qué pasó con cada evento en los últimos barridos y pedidos</span></summary>
    <div class="history__runs">${runs}</div>
  </details>`;
}
