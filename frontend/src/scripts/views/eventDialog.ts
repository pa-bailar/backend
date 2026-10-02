// Event detail dialog: big flyer, all details, prices and share actions.

import type { DanceEvent } from "../types";
import { byId, escapeHtml } from "../lib/dom";
import { formatLongDate, formatMoney, formatTime, placeLabel, typeLabel } from "../lib/format";
import { flyerUrl, googleCalendarUrl, whatsappShareUrl } from "../lib/links";

function detailRows(event: DanceEvent): [string, string][] {
  const time = [formatTime(event.start_time), formatTime(event.end_time)].filter(Boolean).join(" – ");
  const rows: [string, string][] = [
    ["Cuándo", `${formatLongDate(event.date)}${time ? ` · ${time}` : ""}`],
    ["Organiza", [event.organizer, `@${event.source.account}`].filter(Boolean).join(" · ")],
    ["Lugar", placeLabel(event) || "No indicado en el flyer"],
  ];
  if (event.artists.length) rows.push(["Con", event.artists.join(", ")]);
  if (event.activities.length) rows.push(["Incluye", event.activities.join(" · ")]);
  if (event.contact) rows.push(["Contacto", event.contact]);
  return rows;
}

function pricesHtml(event: DanceEvent): string {
  if (!event.prices.length) return "";
  const items = event.prices
    .map((price) => {
      const condition = price.condition ? ` <small>(${escapeHtml(price.condition)})</small>` : "";
      return `<li><span>${escapeHtml(price.label)}${condition}</span><b>${formatMoney(price.amount_cop)}</b></li>`;
    })
    .join("");
  return `<h3 class="event-dialog__subheading">Precios</h3><ul class="price-list">${items}</ul>`;
}

function dialogHtml(event: DanceEvent): string {
  const flyer = flyerUrl(event);
  const permalink = escapeHtml(event.source.permalink);
  const rows = detailRows(event)
    .map(([term, value]) => `<dt>${term}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
  const styles = event.styles.map((style) => `<span class="tag">${escapeHtml(style)}</span>`).join("");

  return `
    <button class="event-dialog__close" data-close-dialog aria-label="Cerrar">×</button>
    ${flyer ? `<a class="event-dialog__media" href="${permalink}" target="_blank" rel="noopener"><img src="${escapeHtml(flyer)}" alt="Flyer de ${escapeHtml(event.title)}" /></a>` : ""}
    <div class="event-dialog__info">
      <div class="stripes" aria-hidden="true"><i></i><i></i><i></i></div>
      <span class="tag-type t-${escapeHtml(event.event_type)}">${typeLabel(event.event_type)}</span>
      <h2 class="event-dialog__title" id="event-dialog-title">${escapeHtml(event.title)}</h2>
      <dl class="detail-list">${rows}</dl>
      ${pricesHtml(event)}
      ${styles ? `<div class="tag-list">${styles}</div>` : ""}
      <div class="event-dialog__actions">
        <a class="btn btn--primary" href="${permalink}" target="_blank" rel="noopener">Ver en Instagram</a>
        <a class="btn btn--whatsapp" href="${escapeHtml(whatsappShareUrl(event))}" target="_blank" rel="noopener">Compartir por WhatsApp</a>
        <a class="btn" href="${escapeHtml(googleCalendarUrl(event))}" target="_blank" rel="noopener">Agregar al calendario</a>
      </div>
      ${event.doubts.length ? `<p class="callout"><strong>Por confirmar:</strong> ${escapeHtml(event.doubts.join(" "))}</p>` : ""}
      ${event.source.caption ? `<details class="event-dialog__caption"><summary>Texto de la publicación</summary><p>${escapeHtml(event.source.caption)}</p></details>` : ""}
    </div>`;
}

export function openEventDialog(event: DanceEvent) {
  const dialog = byId<HTMLDialogElement>("event-dialog");
  byId("event-dialog-body").innerHTML = dialogHtml(event);
  dialog.showModal();
}

export function initEventDialog() {
  const dialog = byId<HTMLDialogElement>("event-dialog");
  dialog.addEventListener("click", (domEvent) => {
    const target = domEvent.target as HTMLElement;
    // Close on the × button or a click on the backdrop (the dialog element itself).
    if (target === dialog || target.closest("[data-close-dialog]")) dialog.close();
  });
}
