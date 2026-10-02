// Client-side rendering for the agenda: upcoming list, month calendar, filters and the event dialog.

type Price = { label: string; amount_cop: number; condition: string | null };
type AgendaEvent = {
  id: string;
  title: string;
  event_type: string;
  styles: string[];
  organizer: string | null;
  venue: string | null;
  address: string | null;
  area: string | null;
  date: string;
  start_time: string | null;
  end_time: string | null;
  prices: Price[];
  artists: string[];
  activities: string[];
  contact: string | null;
  confidence: string;
  doubts: string[];
  flyer: string | null;
  source: { account: string; permalink: string; caption: string | null };
};

const TYPE_LABELS: Record<string, string> = {
  social: "Social",
  workshop: "Taller",
  concert: "Concierto",
  festival: "Festival",
  competition: "Competencia",
  show: "Show",
  other: "Otro",
};

const BASE = import.meta.env.BASE_URL.replace(/\/?$/, "/");
const money = new Intl.NumberFormat("es-CO", { style: "currency", currency: "COP", maximumFractionDigits: 0 });
const dayFmt = new Intl.DateTimeFormat("es-CO", { weekday: "long", day: "numeric", month: "long" });
const shortFmt = new Intl.DateTimeFormat("es-CO", { weekday: "short", day: "numeric", month: "short" });
const monthFmt = new Intl.DateTimeFormat("es-CO", { month: "long", year: "numeric" });

let events: AgendaEvent[] = [];
const state = {
  view: "upcoming" as "upcoming" | "calendar",
  type: "all",
  style: "all",
  month: startOfMonth(new Date()),
  selectedDay: isoDate(new Date()),
};

// ---------- small helpers ----------

function $(id: string) {
  return document.getElementById(id)!;
}

function esc(text: string | null | undefined): string {
  return (text ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

function parseDate(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(y, m - 1, d);
}

function isoDate(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function startOfMonth(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

function capitalize(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function formatTime(t: string | null): string {
  if (!t) return "";
  const [h, m] = t.split(":").map(Number);
  const suffix = h >= 12 ? "p. m." : "a. m.";
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${suffix}`;
}

function dayLabel(iso: string): string {
  const today = isoDate(new Date());
  const tomorrow = isoDate(new Date(Date.now() + 86400000));
  const label = capitalize(dayFmt.format(parseDate(iso)));
  if (iso === today) return `Hoy · ${label}`;
  if (iso === tomorrow) return `Mañana · ${label}`;
  return label;
}

function priceSummary(e: AgendaEvent): string {
  if (!e.prices.length) return "";
  const min = Math.min(...e.prices.map((p) => p.amount_cop));
  return min === 0 ? "Gratis" : e.prices.length > 1 ? `Desde ${money.format(min)}` : money.format(min);
}

function place(e: AgendaEvent): string {
  return [e.venue && e.venue !== e.organizer ? e.venue : null, e.address, e.area].filter(Boolean).join(" · ");
}

function matchesFilters(e: AgendaEvent): boolean {
  return (state.type === "all" || e.event_type === state.type) && (state.style === "all" || e.styles.includes(state.style));
}

// ---------- rendering ----------

function cardHtml(e: AgendaEvent, showDate = false): string {
  const when = [showDate ? capitalize(shortFmt.format(parseDate(e.date))) : null, formatTime(e.start_time)]
    .filter(Boolean)
    .join(" · ");
  const flyer = e.flyer
    ? `<img src="${BASE}${esc(e.flyer)}" alt="Flyer de ${esc(e.title)}" loading="lazy" decoding="async" />`
    : `<div class="no-flyer">💃</div>`;
  return `
    <article class="card">
      <button class="card-hit" data-event="${esc(e.id)}" aria-label="Ver detalles de ${esc(e.title)}">
        <div class="card-img">${flyer}<span class="badge t-${esc(e.event_type)}">${TYPE_LABELS[e.event_type] ?? e.event_type}</span></div>
        <div class="card-body">
          ${when ? `<p class="card-when">${esc(when)}</p>` : ""}
          <h3>${esc(e.title)}</h3>
          <p class="card-org">@${esc(e.source.account)}</p>
          ${place(e) ? `<p class="card-place">${esc(place(e))}</p>` : ""}
          <div class="card-foot">
            ${priceSummary(e) ? `<span class="price">${esc(priceSummary(e))}</span>` : ""}
            ${e.styles.slice(0, 3).map((s) => `<span class="tag">${esc(s)}</span>`).join("")}
          </div>
        </div>
      </button>
    </article>`;
}

function renderUpcoming() {
  const today = isoDate(new Date());
  const upcoming = events.filter((e) => e.date >= today && matchesFilters(e));
  const el = $("view-upcoming");
  if (!upcoming.length) {
    el.innerHTML = `<div class="empty"><p>No hay eventos próximos con estos filtros.</p><p>Prueba otro filtro o revisa el calendario.</p></div>`;
    return;
  }
  const byDay = new Map<string, AgendaEvent[]>();
  for (const e of upcoming) byDay.set(e.date, [...(byDay.get(e.date) ?? []), e]);
  el.innerHTML = [...byDay.entries()]
    .map(([day, list]) => `
      <section class="day">
        <h2 class="day-title">${esc(dayLabel(day))}</h2>
        <div class="cards">${list.map((e) => cardHtml(e)).join("")}</div>
      </section>`)
    .join("");
}

function renderCalendar() {
  const month = state.month;
  $("cal-title").textContent = capitalize(monthFmt.format(month));
  const today = isoDate(new Date());
  const filtered = events.filter(matchesFilters);
  const byDay = new Map<string, AgendaEvent[]>();
  for (const e of filtered) byDay.set(e.date, [...(byDay.get(e.date) ?? []), e]);

  const offset = (month.getDay() + 6) % 7; // weeks start on Monday
  const daysInMonth = new Date(month.getFullYear(), month.getMonth() + 1, 0).getDate();
  const cells: string[] = ["L", "M", "M", "J", "V", "S", "D"].map((d) => `<div class="cal-wd" aria-hidden="true">${d}</div>`);
  for (let i = 0; i < offset; i++) cells.push(`<div class="cal-cell empty-cell"></div>`);

  for (let d = 1; d <= daysInMonth; d++) {
    const iso = isoDate(new Date(month.getFullYear(), month.getMonth(), d));
    const list = byDay.get(iso) ?? [];
    const classes = ["cal-cell", iso < today ? "past" : "", iso === today ? "today" : "", iso === state.selectedDay ? "selected" : "", list.length ? "has-events" : ""];
    const pills = list
      .slice(0, 3)
      .map((e) => `<span class="pill t-${esc(e.event_type)}">${esc(e.title)}</span>`)
      .join("");
    const more = list.length > 3 ? `<span class="more">+${list.length - 3}</span>` : "";
    const dots = list.map((e) => `<i class="dot t-${esc(e.event_type)}"></i>`).join("");
    const label = `${d}${list.length ? `, ${list.length} evento${list.length > 1 ? "s" : ""}` : ""}`;
    cells.push(`
      <button class="${classes.join(" ")}" data-day="${iso}" aria-label="${label}" aria-pressed="${iso === state.selectedDay}">
        <span class="num">${d}</span>
        <span class="pills">${pills}${more}</span>
        <span class="dots">${dots}</span>
      </button>`);
  }
  $("cal-grid").innerHTML = cells.join("");

  const dayEvents = byDay.get(state.selectedDay) ?? [];
  $("cal-day").innerHTML = `
    <h2 class="day-title">${esc(dayLabel(state.selectedDay))}</h2>
    ${dayEvents.length ? `<div class="cards">${dayEvents.map((e) => cardHtml(e)).join("")}</div>` : `<p class="muted">No hay eventos este día.</p>`}`;
}

function renderFilters() {
  const types = [...new Set(events.map((e) => e.event_type))];
  const styles = [...new Set(events.flatMap((e) => e.styles))].sort();
  const chip = (group: string, value: string, label: string, active: boolean) =>
    `<button class="chip ${group === "type" && value !== "all" ? `t-${value}` : ""}" data-${group}="${esc(value)}" aria-pressed="${active}">${esc(label)}</button>`;
  $("type-filters").innerHTML =
    chip("type", "all", "Todo", state.type === "all") +
    types.map((t) => chip("type", t, TYPE_LABELS[t] ?? t, state.type === t)).join("");
  $("style-filters").innerHTML =
    chip("style", "all", "Todos los ritmos", state.style === "all") +
    styles.map((s) => chip("style", s, capitalize(s), state.style === s)).join("");
}

function render() {
  renderFilters();
  $("view-upcoming").hidden = state.view !== "upcoming";
  $("view-calendar").hidden = state.view !== "calendar";
  document.querySelectorAll<HTMLButtonElement>(".tab").forEach((t) => t.setAttribute("aria-selected", String(t.dataset.view === state.view)));
  if (state.view === "upcoming") renderUpcoming();
  else renderCalendar();
}

// ---------- event dialog ----------

function googleCalendarUrl(e: AgendaEvent): string {
  const day = e.date.replace(/-/g, "");
  const nextDay = isoDate(new Date(parseDate(e.date).getTime() + 86400000)).replace(/-/g, "");
  let dates = `${day}/${nextDay}`;
  if (e.start_time) {
    // Without an end time, assume 4 hours. Socials often end after midnight.
    const endTime = e.end_time ?? `${String((Number(e.start_time.slice(0, 2)) + 4) % 24).padStart(2, "0")}:${e.start_time.slice(3)}`;
    const endDay = endTime <= e.start_time ? nextDay : day;
    dates = `${day}T${e.start_time.replace(":", "")}00/${endDay}T${endTime.replace(":", "")}00`;
  }
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: e.title,
    dates,
    ctz: "America/Bogota",
    details: `${e.source.permalink}`,
    location: [e.venue, e.address, "Bogotá"].filter(Boolean).join(", "),
  });
  return `https://calendar.google.com/calendar/render?${params}`;
}

function whatsappUrl(e: AgendaEvent): string {
  const lines = [
    `💃 ${e.title}`,
    `📅 ${capitalize(dayFmt.format(parseDate(e.date)))}${e.start_time ? ` · ${formatTime(e.start_time)}` : ""}`,
    place(e) ? `📍 ${place(e)}` : "",
    priceSummary(e) ? `💵 ${priceSummary(e)}` : "",
    `ℹ️ ${e.source.permalink}`,
  ];
  return `https://wa.me/?text=${encodeURIComponent(lines.filter(Boolean).join("\n"))}`;
}

function openEvent(id: string) {
  const e = events.find((x) => x.id === id);
  if (!e) return;
  const time = [formatTime(e.start_time), e.end_time ? formatTime(e.end_time) : ""].filter(Boolean).join(" – ");
  const rows: [string, string][] = [
    ["Cuándo", `${capitalize(dayFmt.format(parseDate(e.date)))}${time ? ` · ${time}` : ""}`],
    ["Organiza", `${e.organizer ?? ""} (@${e.source.account})`],
    ["Lugar", place(e) || "No indicado en el flyer"],
    ...(e.artists.length ? [["Con", e.artists.join(", ")] as [string, string]] : []),
    ...(e.activities.length ? [["Incluye", e.activities.join(" · ")] as [string, string]] : []),
    ...(e.contact ? [["Contacto", e.contact] as [string, string]] : []),
  ];
  $("dlg-body").innerHTML = `
    <button class="close" id="dlg-close" aria-label="Cerrar">✕</button>
    ${e.flyer ? `<a class="dlg-img" href="${esc(e.source.permalink)}" target="_blank" rel="noopener"><img src="${BASE}${esc(e.flyer)}" alt="Flyer de ${esc(e.title)}" /></a>` : ""}
    <div class="dlg-info">
      <span class="badge t-${esc(e.event_type)}">${TYPE_LABELS[e.event_type] ?? e.event_type}</span>
      <h2 id="dlg-title">${esc(e.title)}</h2>
      <dl>${rows.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
      ${e.prices.length ? `
        <h3>Precios</h3>
        <ul class="prices">${e.prices
          .map((p) => `<li><span>${esc(p.label)}${p.condition ? ` <small>(${esc(p.condition)})</small>` : ""}</span><b>${p.amount_cop ? money.format(p.amount_cop) : "Gratis"}</b></li>`)
          .join("")}</ul>` : ""}
      ${e.styles.length ? `<div class="card-foot">${e.styles.map((s) => `<span class="tag">${esc(s)}</span>`).join("")}</div>` : ""}
      <div class="actions">
        <a class="btn primary" href="${esc(e.source.permalink)}" target="_blank" rel="noopener">Ver en Instagram</a>
        <a class="btn whatsapp" href="${esc(whatsappUrl(e))}" target="_blank" rel="noopener">Compartir por WhatsApp</a>
        <a class="btn" href="${esc(googleCalendarUrl(e))}" target="_blank" rel="noopener">Agregar al calendario</a>
      </div>
      ${e.doubts.length ? `<p class="note">⚠️ Datos por confirmar: ${esc(e.doubts.join(" "))}</p>` : ""}
      ${e.source.caption ? `<details><summary>Texto de la publicación</summary><p class="caption">${esc(e.source.caption)}</p></details>` : ""}
    </div>`;
  const dialog = $("event-dialog") as HTMLDialogElement;
  dialog.showModal();
  $("dlg-close").addEventListener("click", () => dialog.close());
}

// ---------- wiring ----------

export function start() {
  events = JSON.parse($("events-data").textContent || "[]");

  document.addEventListener("click", (ev) => {
    const target = ev.target as HTMLElement;
    const btn = target.closest<HTMLElement>("[data-view],[data-type],[data-style],[data-day],[data-event]");
    if (!btn) return;
    if (btn.dataset.view) state.view = btn.dataset.view as typeof state.view;
    else if (btn.dataset.type) state.type = btn.dataset.type;
    else if (btn.dataset.style) state.style = btn.dataset.style;
    else if (btn.dataset.day) state.selectedDay = btn.dataset.day;
    else if (btn.dataset.event) return openEvent(btn.dataset.event);
    render();
  });

  $("cal-prev").addEventListener("click", () => {
    state.month = new Date(state.month.getFullYear(), state.month.getMonth() - 1, 1);
    render();
  });
  $("cal-next").addEventListener("click", () => {
    state.month = new Date(state.month.getFullYear(), state.month.getMonth() + 1, 1);
    render();
  });
  $("cal-today").addEventListener("click", () => {
    state.month = startOfMonth(new Date());
    state.selectedDay = isoDate(new Date());
    render();
  });

  // Close the dialog when clicking the dark backdrop.
  const dialog = $("event-dialog") as HTMLDialogElement;
  dialog.addEventListener("click", (ev) => {
    if (ev.target === dialog) dialog.close();
  });

  render();
}
