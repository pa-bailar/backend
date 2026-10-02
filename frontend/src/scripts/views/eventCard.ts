// Event card used in the upcoming list and the calendar's day list.
// The title is the button; its ::after stretches over the whole card, so the card is one big
// click target without putting headings and paragraphs inside a <button> (invalid HTML).

import type { DanceEvent } from "../types";
import { escapeHtml } from "../lib/dom";
import {
  cardWhenLabel,
  placeLabel,
  postCountLabel,
  priceSummary,
  stickerDate,
  stylesLabel,
  typeLabel,
} from "../lib/format";
import { flyerUrl, mainMedia } from "../lib/links";

const MAX_STYLES_ON_CARD = 3;

function isFree(event: DanceEvent): boolean {
  return event.prices.length > 0 && event.prices.every((price) => price.amount_cop === 0);
}

export function eventCardHtml(event: DanceEvent): string {
  const flyer = flyerUrl(mainMedia(event));
  const postCount =
    event.media.length > 1 ? `<span class="media-count">${postCountLabel(event.media.length)}</span>` : "";
  const image = flyer
    ? `<img src="${escapeHtml(flyer)}" alt="" loading="lazy" decoding="async" />`
    : `<div class="no-flyer" aria-hidden="true">Pa'</div>`;
  const sticker = stickerDate(event.date);
  const when = cardWhenLabel(event);
  const place = placeLabel(event);
  const price = priceSummary(event);
  const styles = stylesLabel(event.styles, MAX_STYLES_ON_CARD);

  return `
    <article class="event-card">
      <div class="event-card__media">
        ${image}
        <span class="tag-type t-${escapeHtml(event.event_type)}">${typeLabel(event.event_type)}</span>
        ${postCount}
        <span class="date-sticker" aria-hidden="true"><b>${sticker.day}</b><small>${sticker.month}</small></span>
      </div>
      <div class="event-card__body">
        <p class="event-card__time">${escapeHtml(when)}</p>
        <h3 class="event-card__title">
          <button class="event-card__hit" data-event="${escapeHtml(event.id)}">${escapeHtml(event.title)}</button>
        </h3>
        <p class="event-card__meta">
          <button class="event-card__account" data-account="${escapeHtml(event.account)}" aria-label="Ver solo eventos de @${escapeHtml(event.account)}">@${escapeHtml(event.account)}</button>
        </p>
        ${place ? `<p class="event-card__meta">${escapeHtml(place)}</p>` : ""}
        <div class="event-card__foot">
          ${price ? `<span class="event-card__price${isFree(event) ? " event-card__price--free" : ""}">${escapeHtml(price)}</span>` : ""}
          ${styles ? `<span class="style-list">${escapeHtml(styles)}</span>` : ""}
        </div>
      </div>
    </article>`;
}

export function eventCardGridHtml(events: DanceEvent[]): string {
  return `<div class="card-grid">${events.map(eventCardHtml).join("")}</div>`;
}
