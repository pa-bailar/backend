// Shape of data/events.json. Mirrors the backend's Pydantic models (StoredEvent in backend/pabailar/models.py).

export type EventType = "social" | "workshop" | "concert" | "festival" | "competition" | "show" | "other";

export interface Price {
  label: string;
  amount_cop: number;
  condition: string | null;
}

export type MediaType = "IMAGE" | "CAROUSEL_ALBUM" | "VIDEO";

/** One Instagram post announcing the event. */
export interface EventMedia {
  post_id: string;
  permalink: string;
  media_type: MediaType;
  published: string;
  flyer: string | null; // path relative to the site root, e.g. "flyers/123-0.webp"
  caption: string | null;
}

export interface DanceEvent {
  id: string;
  title: string;
  event_type: EventType;
  is_recurring: boolean;
  styles: string[];
  organizer: string | null;
  venue: string | null;
  address: string | null;
  area: string | null;
  date: string; // YYYY-MM-DD
  weekday: string | null;
  start_time: string | null; // HH:MM, 24-hour
  end_time: string | null;
  prices: Price[];
  artists: string[];
  activities: string[];
  contact: string | null;
  confidence: "high" | "medium" | "low";
  doubts: string[];
  account: string;
  media: EventMedia[]; // main post first (images before videos); always at least one
}

export type View = "upcoming" | "calendar";

export interface AppState {
  view: View;
  typeFilter: EventType | "all";
  styleFilter: string;
  month: Date; // first day of the month shown in the calendar
  selectedDay: string; // YYYY-MM-DD
}
