// Subscribable calendar feed (/calendario.ics, iCalendar RFC 5545), rebuilt with the site every day.
// Subscribed calendars refresh on their own schedule (Google: every 12–24 h).

import type { APIRoute } from "astro";
import events from "../../../data/events.json";
import type { DanceEvent } from "../scripts/types";
import { formatTime, priceSummary } from "../scripts/lib/format";
import { eventPageUrl, eventTimes, locationText } from "../scripts/lib/links";

const HOST = new URL(import.meta.env.SITE ?? "https://pa-bailar.github.io").host;

/** Escape text values (backslash, semicolon, comma, newline). */
function text(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/;/g, "\\;").replace(/,/g, "\\,").replace(/\r?\n/g, "\\n");
}

/** Fold lines longer than 75 bytes, as the format requires (continuation lines start with a space). */
function fold(line: string): string {
  const bytes = new TextEncoder().encode(line);
  if (bytes.length <= 75) return line;
  const parts: string[] = [];
  let current = "";
  let size = 0;
  for (const char of line) {
    const charSize = new TextEncoder().encode(char).length;
    if (size + charSize > (parts.length ? 74 : 75)) {
      parts.push(current);
      current = "";
      size = 0;
    }
    current += char;
    size += charSize;
  }
  parts.push(current);
  return parts.join("\r\n ");
}

function eventLines(event: DanceEvent, stamp: string): string[] {
  const { start, end, allDay } = eventTimes(event);
  const when = allDay ? `;VALUE=DATE:` : `;TZID=America/Bogota:`;
  const details = [
    event.start_time ? `${formatTime(event.start_time)}` : "Hora por confirmar",
    priceSummary(event),
    `@${event.account}`,
    eventPageUrl(event),
  ].filter(Boolean);
  return [
    "BEGIN:VEVENT",
    `UID:${event.id}@${HOST}`,
    `DTSTAMP:${stamp}`,
    `DTSTART${when}${start}`,
    `DTEND${when}${end}`,
    `SUMMARY:${text(event.title)}`,
    `LOCATION:${text(locationText(event))}`,
    `DESCRIPTION:${text(details.join("\n"))}`,
    `URL:${eventPageUrl(event)}`,
    "END:VEVENT",
  ];
}

export const GET: APIRoute = () => {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+/, ""); // 20261002T110000Z
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    `PRODID:-//Pa' Bailar//${HOST}//ES`,
    "CALSCALE:GREGORIAN",
    "METHOD:PUBLISH",
    "X-WR-CALNAME:Pa' Bailar · Bogotá",
    "X-WR-CALDESC:Sociales y talleres de baile en Bogotá",
    "X-WR-TIMEZONE:America/Bogota",
    "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
    "X-PUBLISHED-TTL:PT12H",
    // Bogotá: UTC−5 all year, no daylight saving time.
    "BEGIN:VTIMEZONE",
    "TZID:America/Bogota",
    "BEGIN:STANDARD",
    "DTSTART:19700101T000000",
    "TZOFFSETFROM:-0500",
    "TZOFFSETTO:-0500",
    "TZNAME:-05",
    "END:STANDARD",
    "END:VTIMEZONE",
    ...(events as DanceEvent[]).flatMap((event) => eventLines(event, stamp)),
    "END:VCALENDAR",
  ];
  return new Response(lines.map(fold).join("\r\n") + "\r\n", {
    headers: { "Content-Type": "text/calendar; charset=utf-8" },
  });
};
