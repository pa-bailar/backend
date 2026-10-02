// URLs built from an event: flyer image, Google Calendar and WhatsApp share.

import type { DanceEvent, EventMedia } from "../types";
import { addDays } from "./dates";
import { formatLongDate, formatTime, placeLabel, priceSummary } from "./format";

const BASE_URL = import.meta.env.BASE_URL.replace(/\/?$/, "/");
const DEFAULT_DURATION_HOURS = 4; // socials often run past midnight

export function flyerUrl(media: EventMedia): string | null {
  return media.flyer ? `${BASE_URL}${media.flyer}` : null;
}

/** The main post: the one shown on the card and shared by default. */
export function mainMedia(event: DanceEvent): EventMedia {
  return event.media[0];
}

export function googleCalendarUrl(event: DanceEvent): string {
  const day = event.date.replaceAll("-", "");
  const nextDay = addDays(event.date, 1).replaceAll("-", "");
  let dates = `${day}/${nextDay}`; // all-day event when there's no start time

  if (event.start_time) {
    const startHour = Number(event.start_time.slice(0, 2));
    const endTime =
      event.end_time ??
      `${String((startHour + DEFAULT_DURATION_HOURS) % 24).padStart(2, "0")}:${event.start_time.slice(3)}`;
    const endDay = endTime <= event.start_time ? nextDay : day;
    dates = `${day}T${event.start_time.replace(":", "")}00/${endDay}T${endTime.replace(":", "")}00`;
  }

  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: event.title,
    dates,
    ctz: "America/Bogota",
    details: event.media.map((media) => media.permalink).join("\n"),
    location: [event.venue, event.address, "Bogotá"].filter(Boolean).join(", "),
  });
  return `https://calendar.google.com/calendar/render?${params}`;
}

/** Ready-to-send message for the WhatsApp groups. */
export function whatsappShareUrl(event: DanceEvent): string {
  const time = event.start_time ? ` · ${formatTime(event.start_time)}` : "";
  const lines = [
    `*${event.title}*`,
    `${formatLongDate(event.date)}${time}`,
    placeLabel(event),
    priceSummary(event),
    mainMedia(event).permalink,
  ];
  return `https://wa.me/?text=${encodeURIComponent(lines.filter(Boolean).join("\n"))}`;
}
