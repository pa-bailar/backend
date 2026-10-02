// Event detail: the flyer of each post announcing the event (tabs when there are several), all details,
// prices and actions. Pure HTML strings, so the same markup is used by the dialog (in the browser) and by
// each event's own page (pages/evento/[id].astro, at build time).

import type { DanceEvent, EventMedia } from "../types";
import { escapeHtml } from "../lib/dom";
import { formatLongDate, formatMoney, formatTime, mediaLabel, placeLabel, stylesLabel, typeLabel } from "../lib/format";
import { ICONS } from "../lib/icons";
import { flyerUrl, googleCalendarUrl, mapsUrl, whatsappShareUrl } from "../lib/links";

function toConfirm(text = "Por confirmar"): string {
  return `<span class="to-confirm">${text}</span>`;
}

/** [term, HTML value] rows. Missing details say "Por confirmar" right where they belong. */
function detailRows(event: DanceEvent): [string, string][] {
  const time = [formatTime(event.start_time), formatTime(event.end_time)].filter(Boolean).join(" – ");
  const when = `${escapeHtml(formatLongDate(event.date))} · ${time ? escapeHtml(time) : toConfirm("hora por confirmar")}`;
  const place = placeLabel(event);
  const maps = mapsUrl(event);
  const directions = maps
    ? ` <a class="inline-link" href="${escapeHtml(maps)}" target="_blank" rel="noopener" data-track="como-llegar">${ICONS.pin}Cómo llegar</a>`
    : "";

  const rows: [string, string][] = [
    ["Cuándo", when],
    ["Organiza", escapeHtml([event.organizer, `@${event.account}`].filter(Boolean).join(" · "))],
    ["Lugar", place ? `${escapeHtml(place)}${directions}` : toConfirm()],
  ];
  if (!event.prices.length) rows.push(["Precio", toConfirm()]);
  if (event.artists.length) rows.push(["Con", escapeHtml(event.artists.join(", "))]);
  if (event.activities.length) rows.push(["Incluye", escapeHtml(event.activities.join(" · "))]);
  if (event.contact) rows.push(["Contacto", escapeHtml(event.contact)]);
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
      ${isVideo ? `<span class="event-dialog__play">${ICONS.instagram}Ver video en Instagram</span>` : ""}
    </a>`;
}

/**
 * The detail's inner HTML. `selected` is the post shown. The title is an h1 on the event page and an h2
 * in the viewer, where each slide has its own `titleId`.
 */
export function eventDetailHtml(
  event: DanceEvent,
  selected: number,
  { headingLevel, titleId = "event-title" }: { headingLevel: 1 | 2; titleId?: string },
): string {
  const media = event.media[selected];
  const permalink = escapeHtml(media.permalink);
  const rows = detailRows(event)
    .map(([term, value]) => `<dt>${term}</dt><dd>${value}</dd>`)
    .join("");
  const styles = stylesLabel(event.styles);
  const heading = `h${headingLevel}`;
  const lowConfidence =
    event.confidence === "low"
      ? `<p class="callout">Algunos datos se leyeron del flyer con poca seguridad: confírmalos en la publicación.</p>`
      : "";

  return `
    <div class="event-dialog__visual">
      ${mediaTabsHtml(event, selected)}
      ${mediaHtml(event, media)}
    </div>
    <div class="event-dialog__info">
      <div class="stripes" aria-hidden="true"><i></i><i></i><i></i></div>
      <span class="tag-type t-${escapeHtml(event.event_type)}">${typeLabel(event.event_type)}</span>
      <${heading} class="event-dialog__title" id="${titleId}">${escapeHtml(event.title)}</${heading}>
      <dl class="detail-list">${rows}</dl>
      ${pricesHtml(event)}
      ${styles ? `<p class="style-list">${escapeHtml(styles)}</p>` : ""}
      ${lowConfidence}
      <div class="event-dialog__actions">
        <a class="btn btn--primary" href="${permalink}" target="_blank" rel="noopener" data-track="instagram">${ICONS.instagram}Ver en Instagram</a>
        <a class="btn btn--whatsapp" href="${escapeHtml(whatsappShareUrl(event))}" target="_blank" rel="noopener" data-track="whatsapp">${ICONS.whatsapp}Compartir por WhatsApp</a>
        <a class="btn" href="${escapeHtml(googleCalendarUrl(event))}" target="_blank" rel="noopener" data-track="calendario">${ICONS.calendar}Agregar al calendario</a>
      </div>
      ${media.caption ? `<details class="event-dialog__caption"><summary>Texto de la publicación</summary><p>${escapeHtml(media.caption)}</p></details>` : ""}
    </div>`;
}

/** Media tabs: re-render the detail with another post selected and keep focus on the chosen tab. */
export function handleMediaTabClick(
  container: HTMLElement,
  target: HTMLElement,
  renderSelected: (selected: number) => void,
): boolean {
  const tab = target.closest<HTMLElement>("[data-media-index]");
  if (!tab) return false;
  const index = tab.dataset.mediaIndex!;
  renderSelected(Number(index));
  container.querySelector<HTMLElement>(`[data-media-index="${index}"]`)?.focus();
  return true;
}
