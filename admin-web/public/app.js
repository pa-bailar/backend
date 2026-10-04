// The admin page in the browser: who's signed in, then the dashboard drawn from `admin status` (status.json,
// written by each sweep: pa_bailar/status.py). All data comes from the Worker (src/index.js), after GitHub
// sign-in; this file has none. A post shared to the installed page (Android's share menu) fills in the tools.

const main = document.getElementById("main");
const userLine = document.getElementById("user");
const WEEKDAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const ROLES = { triage: "filtro", extraction: "extracción", provisional: "provisional", discovery: "descubrimiento" };
const MESSAGES = {
  config: "Falta configurar el inicio de sesión: los secretos de GitHub en Cloudflare (docs/ADMIN.md).",
  login: "No se pudo iniciar sesión con GitHub. Intenta de nuevo.",
  denied: "Esa cuenta de GitHub no tiene acceso a esta página.",
};

const escapeHtml = (text) =>
  String(text ?? "").replace(/[&<>"']/g, (char) => `&#${char.charCodeAt(0)};`);

/** Bogotá time: "hoy 9:00 p. m.", "ayer 9:12 a. m.", "sábado 4/10, 9:00 a. m.". */
function when(iso) {
  const bogota = (date) => new Date(date.toLocaleString("en-US", { timeZone: "America/Bogota" }));
  const moment = bogota(new Date(iso));
  const today = bogota(new Date());
  const hours = moment.getHours();
  const hour = `${hours % 12 || 12}:${String(moment.getMinutes()).padStart(2, "0")} ${hours < 12 ? "a. m." : "p. m."}`;
  const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
  const days = Math.round((startOfDay(moment) - startOfDay(today)) / 86_400_000);
  if (days === 0) return `hoy ${hour}`;
  if (days === -1) return `ayer ${hour}`;
  if (days === 1) return `mañana ${hour}`;
  return `${WEEKDAYS[moment.getDay()]} ${moment.getDate()}/${moment.getMonth() + 1}, ${hour}`;
}

const count = (number, one, many) => (number ? `${number} ${number === 1 ? one : many}` : "");

function runItem(run) {
  const problems = [
    run.rate_limited && "límite de Instagram",
    run.out_of_time && "sin tiempo",
    count(run.failed_accounts?.length ?? 0, "cuenta sin leer", "cuentas sin leer"),
    count(run.post_errors ?? 0, "error", "errores"),
  ].filter(Boolean);
  const parts = [
    `${run.events_new ?? 0} nuevos`,
    `${run.events_merged ?? 0} unidos`,
    count(run.pending ?? 0, "en espera", "en espera"),
    count(run.provisional ?? 0, "provisional", "provisionales"),
    run.instagram_usage ? `Instagram ${run.instagram_usage}%` : "",
    ...problems,
  ].filter(Boolean);
  const mark = problems.length ? `<span class="warn" title="Con problemas">⚠️</span>` : `<span class="ok" title="Bien">✅</span>`;
  const link = run.run_url ? ` · <a href="${escapeHtml(run.run_url)}" target="_blank" rel="noopener">ver</a>` : "";
  return `<li>${mark} <span class="when">${when(run.finished_at)}</span>: ${escapeHtml(parts.join(", "))}${link}</li>`;
}

function sweepsCard(sweeps) {
  const runs = sweeps.recent.length
    ? `<ul class="runs">${sweeps.recent.map(runItem).join("")}</ul>`
    : `<p class="muted">Todavía no hay barridos registrados.</p>`;
  return `<section class="card"><h2>Barridos</h2>${runs}
    <p class="small muted">Próximos: ${sweeps.next.map(when).join(" y ")}</p></section>`;
}

function geminiCard(gemini) {
  const models = gemini.models
    .map((model) => {
      const share = model.budget ? Math.min(100, Math.round((model.used / model.budget) * 100)) : 100;
      const full = model.used >= model.budget;
      const roles = model.role.split(", ").map((role) => ROLES[role] ?? role).join(", ");
      return `<div class="model">
        <div class="model__row"><span><code>${escapeHtml(model.model)}</code> <span class="muted">${escapeHtml(roles)}</span></span>
          <span>${escapeHtml(model.used)} / ${escapeHtml(model.budget)}${full ? ` <span class="warn">agotado</span>` : ""}</span></div>
        <div class="meter${full ? " full" : ""}"><i data-share="${escapeHtml(share)}"></i></div></div>`;
    })
    .join("");
  const liteOnly = gemini.lite_only ? `<p class="small">Modo solo Flash-Lite activo (GEMINI_LITE_ONLY).</p>` : "";
  return `<section class="card"><h2>Gemini hoy</h2>${models}
    <p class="small muted">La cuota se reinicia ${when(gemini.resets_at)}</p>${liteOnly}</section>`;
}

function instagramCard(instagram) {
  if (!instagram) return "";
  const text = instagram.ok
    ? `<span class="ok">✓</span> El token funciona. Cuota de Instagram usada: ${escapeHtml(instagram.app_usage_percent)}%.`
    : `<span class="warn">⚠️</span> El token no funciona: ${escapeHtml(instagram.error)}`;
  return `<section class="card"><h2>Instagram</h2><p>${text}</p></section>`;
}

function accountsCard(status) {
  const { accounts, posts, events, discovery } = status;
  const facts = [
    [accounts.followed, "cuentas en los barridos"],
    events && [events.upcoming, "eventos próximos en el sitio"],
    events?.low_confidence && [events.low_confidence, "con datos dudosos"],
    posts.provisional && [posts.provisional, "provisionales, a releer con Flash"],
    discovery && [discovery.checked, `cuentas revisadas por descubrimiento (${discovery.classified} clasificadas)`],
  ].filter(Boolean);
  const pending = accounts.first_sweep_pending;
  const waiting = accounts.waiting ?? [];
  const late = waiting.length
    ? `<p class="small warn chips-title">⚠️ Esperando más de un barrido después de su turno:</p>
       <div class="chips">${waiting.map((account) => `<span>@${escapeHtml(account)}</span>`).join("")}</div>`
    : "";
  const firstSweep = pending.length
    ? `<p class="small chips-title">En su primer barrido (más profundo):</p>
       <div class="chips">${pending.map((account) => `<span>@${escapeHtml(account)}</span>`).join("")}</div>`
    : "";
  return `<section class="card"><h2>Cuentas y eventos</h2>
    <div class="facts">${facts.map(([number, label]) => `<div class="fact"><b>${escapeHtml(number)}</b>${escapeHtml(label)}</div>`).join("")}</div>
    ${firstSweep}${late}</section>`;
}

// ---------- the tools: requests to the admin inbox (issues the admin workflow answers) ----------

const POLL_MS = 5000;
const POLL_LIMIT_MS = 15 * 60 * 1000; // adding a post waits for its turn after a running sweep
let polling = null;

/** The answers are Markdown from the backend: bold, links, `code`, and "- " lists. Escaped first. */
function markdown(text) {
  const inline = (line) =>
    escapeHtml(line)
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  const html = [];
  let list = false;
  for (const line of text.split(/\r?\n/)) {
    const item = line.match(/^\s*-\s+(.*)$/);
    if (item && !list) html.push("<ul>");
    if (!item && list) html.push("</ul>");
    list = Boolean(item);
    if (item) html.push(`<li>${inline(item[1])}</li>`);
    else if (line.trim().startsWith("|")) html.push(`<p class="small">${inline(line)}</p>`);
    else if (line.trim()) html.push(`<p>${inline(line)}</p>`);
  }
  if (list) html.push("</ul>");
  return html.join("");
}

function toolsCard() {
  return `<section class="card" id="tools"><h2>Revisar o agregar un evento</h2>
    <form id="post-form" class="tool">
      <label for="post-link">Enlace de la publicación de Instagram</label>
      <input id="post-link" type="url" inputmode="url" placeholder="https://www.instagram.com/p/…" required />
      <label for="post-account">@cuenta <span class="muted">(si el enlace no la trae)</span></label>
      <input id="post-account" type="text" placeholder="@academia" autocapitalize="none" autocomplete="off" />
      <div class="tool__buttons">
        <button class="button" type="submit" data-action="why">Revisar</button>
        <button class="button button--outline" type="submit" data-action="add-post">Agregar</button>
        <button class="button button--outline" type="submit" data-action="add-post-again">Volver a leer</button>
      </div>
      <p class="small muted">Revisar dice si su evento está en el sitio y, si no, por qué. Agregar la lee y la publica.
        Volver a leer la lee otra vez aunque ya se haya leído (si su evento quedó con datos equivocados).</p>
    </form>
    <form id="account-form" class="tool">
      <label for="new-account">Agregar una cuenta a los barridos</label>
      <div class="tool__row">
        <input id="new-account" type="text" placeholder="@academia" autocapitalize="none" autocomplete="off" required />
        <button class="button button--outline" type="submit">Agregar cuenta</button>
      </div>
    </form>
    <div id="answer" aria-live="polite"></div>
    <h3>Pedidos recientes</h3>
    <ul class="requests" id="requests"><li class="muted">Cargando…</li></ul>
  </section>`;
}

/** Fetch JSON from the Worker; null when offline or the answer isn't JSON. */
async function getJson(url, init) {
  try {
    const response = await fetch(url, init);
    return { ok: response.ok, status: response.status, data: await response.json() };
  } catch {
    return null;
  }
}

let sending = false; // a double tap would open the same request twice

async function send(action, link, account) {
  if (sending) return;
  sending = true;
  setAnswer(`<p class="muted">Enviando…</p>`);
  const result = await getJson("/api/requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, link, account }),
  });
  sending = false;
  if (!result?.ok) {
    const error = result ? result.data?.error ?? "No se pudo enviar." : "No se pudo enviar: revisa la conexión.";
    setAnswer(`<p class="warn">${escapeHtml(error)}</p>`);
    return;
  }
  follow(result.data.number);
  loadRequests();
}

/** The answer area, rewritten only when it changes: it's a live region, and each rewrite is read out again. */
let shownAnswer = null;
function setAnswer(html) {
  if (html === shownAnswer) return;
  shownAnswer = html;
  document.getElementById("answer").innerHTML = html;
}

/** Show a request's answers, checking every few seconds until it's closed (answered). */
let following = 0; // which follow() is current: a check still on its way for an earlier one is dropped
function follow(number) {
  clearTimeout(polling);
  const current = ++following;
  const started = Date.now();
  const check = async () => {
    const result = await getJson(`/api/requests/${number}`);
    if (current !== following) return;
    const inTime = Date.now() - started < POLL_LIMIT_MS;
    if (!result) {
      // Offline for a moment (a phone between networks): try again, keeping what's shown.
      if (inTime) polling = setTimeout(check, POLL_MS);
      else setAnswer(`<p class="warn">No se pudo leer el pedido #${escapeHtml(number)}: revisa la conexión.</p>`);
      return;
    }
    const request = result.data;
    if (!result.ok || !request?.answers) {
      setAnswer(`<p class="warn">No se pudo leer el pedido #${escapeHtml(number)}.</p>`);
      return;
    }
    const answers = request.answers.map((item) => `<div class="answer">${markdown(item.body)}</div>`).join("");
    const open = request.state === "open";
    let note = "";
    if (open && !inTime) note = "Sigue en curso: tócalo en Pedidos recientes más tarde para ver la respuesta.";
    else if (open) note = answers ? "Sigue en curso…" : "Esperando la respuesta (un minuto o dos)…";
    setAnswer(`<div class="answer__head"><b>${escapeHtml(request.title)}</b>
        <a class="small" href="${escapeHtml(request.url)}" target="_blank" rel="noopener">#${escapeHtml(request.number)}</a></div>
      ${answers}
      ${note ? `<p class="small muted">${note}</p>` : ""}`);
    if (open && inTime) polling = setTimeout(check, POLL_MS);
    else loadRequests();
  };
  check();
}

async function loadRequests() {
  const list = document.getElementById("requests");
  const result = await getJson("/api/requests");
  const requests = result?.ok && Array.isArray(result.data) ? result.data : null;
  if (!requests) {
    list.innerHTML = `<li class="warn">No se pudieron leer los pedidos.</li>`;
    return;
  }
  list.innerHTML = requests.length
    ? requests
        .map(
          (request) => `<li><button class="link" type="button" data-request="${escapeHtml(request.number)}">
            ${request.state === "open" ? "⏳" : "✓"} ${escapeHtml(request.title)}</button>
            <span class="small muted">${when(request.created_at)}</span></li>`,
        )
        .join("")
    : `<li class="muted">Todavía no hay pedidos.</li>`;
}

function initTools() {
  shownAnswer = null; // a new, empty answer area
  let action = "why";
  const postForm = document.getElementById("post-form");
  postForm.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (button) action = button.dataset.action;
  });
  postForm.addEventListener("submit", (event) => {
    event.preventDefault();
    send(action, document.getElementById("post-link").value, document.getElementById("post-account").value);
  });
  document.getElementById("account-form").addEventListener("submit", (event) => {
    event.preventDefault();
    send("add-account", "", document.getElementById("new-account").value);
  });
  document.getElementById("requests").addEventListener("click", (event) => {
    const button = event.target.closest("[data-request]");
    if (button) follow(button.dataset.request);
  });
  loadRequests();
}

// ---------- a post shared from Instagram (Android's share menu: manifest.webmanifest's share_target) ----------

const SHARED_KEY = "shared-post";
const SHARED_MAX_AGE_MS = 30 * 60 * 1000;
const INSTAGRAM_POST = /https?:\/\/(?:www\.|m\.)?instagram\.com\/(?:[\w.]+\/)?(?:p|reel|reels|tv)\/[\w-]+\/?/i;
let sharedFallback = null; // when the browser's storage is blocked

/**
 * Keep a shared post's link (Android sends it as ?text= or ?url=), so it survives the GitHub sign-in.
 * "post", "other" when what was shared isn't a post's link (a profile, a story), or null when nothing was.
 */
function keepSharedLink(params) {
  const text = ["url", "text", "link"].map((name) => params.get(name) ?? "").join(" ");
  if (!text.trim()) return null;
  const link = text.match(INSTAGRAM_POST)?.[0]; // without Instagram's tracking (?igsh=…)
  if (!link) return "other";
  sharedFallback = link;
  try {
    localStorage.setItem(SHARED_KEY, JSON.stringify({ link, at: Date.now() }));
  } catch {}
  return "post";
}

/** The shared link waiting to be used, once. */
function takeSharedLink() {
  let link = sharedFallback;
  try {
    const kept = JSON.parse(localStorage.getItem(SHARED_KEY) ?? "null");
    localStorage.removeItem(SHARED_KEY);
    if (kept && Date.now() - kept.at < SHARED_MAX_AGE_MS) link = kept.link;
  } catch {}
  sharedFallback = null;
  return link;
}

function useSharedLink(shared) {
  const link = takeSharedLink();
  const form = document.getElementById("post-form");
  if (link) {
    document.getElementById("post-link").value = link;
    form.insertAdjacentHTML("afterbegin", `<p class="shared">📎 Enlace recibido: elige <b>Revisar</b>, <b>Agregar</b> o <b>Volver a leer</b>.</p>`);
  } else if (shared === "other") {
    form.insertAdjacentHTML("afterbegin", `<p class="shared">📎 Lo que compartiste no es el enlace de una publicación (instagram.com/p/… o /reel/…).</p>`);
  }
}

/** The status cards from status.json, or a note when there's none: the tools above work without it. */
function statusCards(result) {
  const status = result?.data;
  if (!result) return card(`<p>No se pudo leer el estado: revisa la conexión.</p>`);
  if (status?.missing) return card(`<p>Todavía no hay estado guardado: aparece después del próximo barrido.</p>`);
  if (!result.ok || status?.error) return card(`<p>${escapeHtml(status?.error ?? "No se pudo leer el estado.")}</p>`);
  try {
    return [
      sweepsCard(status.sweeps),
      geminiCard(status.gemini),
      instagramCard(status.instagram),
      accountsCard(status),
      `<p class="small muted">Datos del barrido de ${when(status.generated_at)}</p>`,
    ].join("");
  } catch (error) {
    console.error(error); // status.json changed shape (pa_bailar/status.py)
    return card(`<p>No se pudo mostrar el estado.</p>`);
  }
}

function showDashboard(cards, shared) {
  main.innerHTML = toolsCard() + cards;
  // The meters' fill, set here: the Content Security Policy (public/_headers) blocks style="" in the HTML.
  main.querySelectorAll(".meter i[data-share]").forEach((bar) => (bar.style.width = `${bar.dataset.share}%`));
  initTools();
  useSharedLink(shared);
}

const card = (html) => `<section class="card">${html}</section>`;

function showMessage(html) {
  main.innerHTML = card(html);
}

function showSignIn(note) {
  showMessage(`${note ? `<p>${escapeHtml(note)}</p>` : ""}
    <p>Esta página es solo para administrar Pa' Bailar.</p>
    <p><a class="button" href="/auth/login">Iniciar sesión con GitHub</a></p>`);
}

async function start() {
  const params = new URLSearchParams(location.search);
  const error = params.get("error");
  const shared = keepSharedLink(params);
  if (error || shared) history.replaceState(null, "", "/");

  const health = await getJson("/api/health");
  if (!health?.ok) return showMessage(`<p>No se pudo contactar el servidor.</p>`);
  if (!health.data.configured) return showMessage(`<p>${MESSAGES.config}</p>`);

  const me = await getJson("/api/me");
  if (me?.status === 401) {
    const note = Object.hasOwn(MESSAGES, error) ? MESSAGES[error] : "";
    return showSignIn(note || (shared === "post" ? "Inicia sesión para usar el enlace que compartiste." : ""));
  }
  if (!me?.ok) return showMessage(`<p>No se pudo contactar el servidor.</p>`);
  userLine.hidden = false;
  userLine.innerHTML = `@${escapeHtml(me.data.login)} · <a href="/auth/logout">Salir</a>`;

  const status = await getJson("/api/status");
  // GitHub turned the session's token down (the App's access was revoked): sign in again.
  if (status?.status === 401) return showSignIn(status.data?.error);
  showDashboard(statusCards(status), shared);
}

start();
