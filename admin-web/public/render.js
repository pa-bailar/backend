// Pieces of the admin page that only turn data into HTML, kept apart from app.js (which needs the browser) so
// the tests can check them in Node (test/render.test.mjs). Everything that comes from the data is escaped.

/** Text made safe for HTML, in an element or an attribute. */
export const escapeHtml = (text) => String(text ?? "").replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);

/** Only http(s) links are linked (a link in the data could be anything). */
const safeLink = (link) => (/^https?:\/\//i.test(String(link ?? "")) ? String(link) : null);

/**
 * "Series nuevas": workshop series first published in the last two weeks (status.json's `new_series`,
 * pa_bailar/status.py new_series), each with its sessions, where it came from, its link on the site, and a one-tap
 * "Ocultar" (data-hide-event, handled in app.js: it opens a hide-event request). Empty when there are none.
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
