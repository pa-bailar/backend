// Event detail dialog: the flyer of each post announcing the event (tabs when there are several),
// all details, prices and share actions.

import type { DanceEvent, EventMedia } from "../types";
import { byId, escapeHtml } from "../lib/dom";
import { formatLongDate, formatMoney, formatTime, mediaLabel, placeLabel, stylesLabel, typeLabel } from "../lib/format";
import { flyerUrl, googleCalendarUrl, whatsappShareUrl } from "../lib/links";

let currentEvent: DanceEvent | null = null;

function detailRows(event: DanceEvent): [string, string][] {
  const time = [formatTime(event.start_time), formatTime(event.end_time)].filter(Boolean).join(" – ");
  const rows: [string, string][] = [
    ["Cuándo", `${formatLongDate(event.date)}${time ? ` · ${time}` : ""}`],
    ["Organiza", [event.organizer, `@${event.account}`].filter(Boolean).join(" · ")],
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

/** Tabs to switch between the posts that announce this event. Hidden when there's only one. */
function mediaTabsHtml(event: DanceEvent, selected: number): string {
  if (event.media.length < 2) return "";
  const tabs = event.media
    .map(
      (media, index) => `
        <button class="media-tabs__tab" role="tab" data-media-index="${index}" aria-selected="${index === selected}">
          ${mediaLabel(media.media_type)}
        </button>`,
    )
    .join("");
  return `<div class="media-tabs" role="tablist" aria-label="Publicaciones de este evento">${tabs}</div>`;
}

function mediaHtml(event: DanceEvent, media: EventMedia): string {
  const flyer = flyerUrl(media);
  if (!flyer) return "";
  const isVideo = media.media_type === "VIDEO";
  return `
    <a class="event-dialog__media" href="${escapeHtml(media.permalink)}" target="_blank" rel="noopener">
      <img src="${escapeHtml(flyer)}" alt="${isVideo ? "Video" : "Flyer"} de ${escapeHtml(event.title)}" />
      ${isVideo ? `<span class="event-dialog__play">Ver video en Instagram</span>` : ""}
    </a>`;
}

function dialogHtml(event: DanceEvent, selected: number): string {
  const media = event.media[selected];
  const permalink = escapeHtml(media.permalink);
  const rows = detailRows(event)
    .map(([term, value]) => `<dt>${term}</dt><dd>${escapeHtml(value)}</dd>`)
    .join("");
  const styles = stylesLabel(event.styles);

  return `
    <button class="event-dialog__close" data-close-dialog aria-label="Cerrar">×</button>
    <div class="event-dialog__visual">
      ${mediaTabsHtml(event, selected)}
      ${mediaHtml(event, media)}
    </div>
    <div class="event-dialog__info">
      <div class="stripes" aria-hidden="true"><i></i><i></i><i></i></div>
      <span class="tag-type t-${escapeHtml(event.event_type)}">${typeLabel(event.event_type)}</span>
      <h2 class="event-dialog__title" id="event-dialog-title">${escapeHtml(event.title)}</h2>
      <dl class="detail-list">${rows}</dl>
      ${pricesHtml(event)}
      ${styles ? `<p class="style-list">${escapeHtml(styles)}</p>` : ""}
      <div class="event-dialog__actions">
        <a class="btn btn--primary" href="${permalink}" target="_blank" rel="noopener">Ver en Instagram</a>
        <a class="btn btn--whatsapp" href="${escapeHtml(whatsappShareUrl(event))}" target="_blank" rel="noopener">Compartir por WhatsApp</a>
        <a class="btn" href="${escapeHtml(googleCalendarUrl(event))}" target="_blank" rel="noopener">Agregar al calendario</a>
      </div>
      ${event.doubts.length ? `<p class="callout"><strong>Por confirmar:</strong> ${escapeHtml(event.doubts.join(" "))}</p>` : ""}
      ${media.caption ? `<details class="event-dialog__caption"><summary>Texto de la publicación</summary><p>${escapeHtml(media.caption)}</p></details>` : ""}
    </div>`;
}

function render(selected: number) {
  if (currentEvent) byId("event-dialog-body").innerHTML = dialogHtml(currentEvent, selected);
}

export function openEventDialog(event: DanceEvent) {
  currentEvent = event;
  render(0);
  byId<HTMLDialogElement>("event-dialog").showModal();
}

export function initEventDialog() {
  const dialog = byId<HTMLDialogElement>("event-dialog");
  dialog.addEventListener("click", (domEvent) => {
    const target = domEvent.target as HTMLElement;
    const tab = target.closest<HTMLElement>("[data-media-index]");
    if (tab) {
      render(Number(tab.dataset.mediaIndex));
      byId("event-dialog-body").querySelector<HTMLElement>(`[data-media-index="${tab.dataset.mediaIndex}"]`)?.focus();
      return;
    }
    // Close on the × button or a click on the backdrop (the dialog element itself).
    if (target === dialog || target.closest("[data-close-dialog]")) dialog.close();
  });
}
