// Event card used in the upcoming list and the calendar's day list.

import type { DanceEvent } from "../types";
import { escapeHtml } from "../lib/dom";
import { formatTime, placeLabel, priceSummary, stickerDate, typeLabel } from "../lib/format";
import { flyerUrl } from "../lib/links";

const MAX_STYLES_ON_CARD = 3;

export function eventCardHtml(event: DanceEvent): string {
  const flyer = flyerUrl(event);
  const image = flyer
    ? `<img src="${escapeHtml(flyer)}" alt="Flyer de ${escapeHtml(event.title)}" loading="lazy" decoding="async" />`
    : `<div class="no-flyer" aria-hidden="true">Pa'</div>`;
  const sticker = stickerDate(event.date);
  const time = formatTime(event.start_time);
  const place = placeLabel(event);
  const price = priceSummary(event);
  const styles = event.styles
    .slice(0, MAX_STYLES_ON_CARD)
    .map((style) => `<span class="tag">${escapeHtml(style)}</span>`)
    .join("");

  return `
    <article class="event-card">
      <button class="event-card__hit" data-event="${escapeHtml(event.id)}" aria-label="Ver detalles de ${escapeHtml(event.title)}">
        <div class="event-card__media">
          ${image}
          <span class="tag-type t-${escapeHtml(event.event_type)}">${typeLabel(event.event_type)}</span>
          <span class="date-sticker" aria-hidden="true"><b>${sticker.day}</b><small>${sticker.month}</small></span>
        </div>
        <div class="event-card__body">
          ${time ? `<p class="event-card__time">${time}</p>` : ""}
          <h3 class="event-card__title">${escapeHtml(event.title)}</h3>
          <p class="event-card__meta">@${escapeHtml(event.source.account)}</p>
          ${place ? `<p class="event-card__meta">${escapeHtml(place)}</p>` : ""}
          <div class="event-card__foot">
            ${price ? `<span class="event-card__price">${escapeHtml(price)}</span>` : ""}
            ${styles}
          </div>
        </div>
      </button>
    </article>`;
}

export function eventCardGridHtml(events: DanceEvent[]): string {
  return `<div class="card-grid">${events.map(eventCardHtml).join("")}</div>`;
}
