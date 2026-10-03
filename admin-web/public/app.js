// The admin page in the browser: who's signed in, then the dashboard drawn from `admin status` (status.json,
// written by each sweep: pa_bailar/status.py). All data comes from the Worker (src/index.js), after GitHub
// sign-in; this file has none.

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
          <span>${model.used} / ${model.budget}${full ? ` <span class="warn">agotado</span>` : ""}</span></div>
        <div class="meter${full ? " full" : ""}"><i style="width:${share}%"></i></div></div>`;
    })
    .join("");
  const liteOnly = gemini.lite_only ? `<p class="small">Modo solo Flash-Lite activo (GEMINI_LITE_ONLY).</p>` : "";
  return `<section class="card"><h2>Gemini hoy</h2>${models}
    <p class="small muted">La cuota se reinicia ${when(gemini.resets_at)}</p>${liteOnly}</section>`;
}

function instagramCard(instagram) {
  if (!instagram) return "";
  const text = instagram.ok
    ? `<span class="ok">✓</span> El token funciona. Cuota de Instagram usada: ${instagram.app_usage_percent}%.`
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
  const firstSweep = pending.length
    ? `<p class="small" style="margin:12px 0 0">En su primer barrido (más profundo):</p>
       <div class="chips">${pending.map((account) => `<span>@${escapeHtml(account)}</span>`).join("")}</div>`
    : "";
  return `<section class="card"><h2>Cuentas y eventos</h2>
    <div class="facts">${facts.map(([number, label]) => `<div class="fact"><b>${number}</b>${escapeHtml(label)}</div>`).join("")}</div>
    ${firstSweep}</section>`;
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
      </div>
      <p class="small muted">Revisar dice si su evento está en el sitio y, si no, por qué. Agregar la lee y la publica.</p>
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

async function send(action, link, account) {
  const answer = document.getElementById("answer");
  answer.innerHTML = `<p class="muted">Enviando…</p>`;
  const response = await fetch("/api/requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, link, account }),
  });
  const result = await response.json().catch(() => ({ error: "Respuesta inválida." }));
  if (!response.ok) {
    answer.innerHTML = `<p class="warn">${escapeHtml(result.error ?? "No se pudo enviar.")}</p>`;
    return;
  }
  follow(result.number);
  loadRequests();
}

/** Show a request's answers, checking every few seconds until it's closed (answered). */
function follow(number) {
  clearTimeout(polling);
  const answer = document.getElementById("answer");
  const started = Date.now();
  const check = async () => {
    const response = await fetch(`/api/requests/${number}`);
    const request = await response.json().catch(() => null);
    if (!response.ok || !request) {
      answer.innerHTML = `<p class="warn">No se pudo leer el pedido #${number}.</p>`;
      return;
    }
    const answers = request.answers.map((item) => `<div class="answer">${markdown(item.body)}</div>`).join("");
    const waiting = request.state === "open" && Date.now() - started < POLL_LIMIT_MS;
    answer.innerHTML = `<div class="answer__head"><b>${escapeHtml(request.title)}</b>
        <a class="small" href="${escapeHtml(request.url)}" target="_blank" rel="noopener">#${request.number}</a></div>
      ${answers || ""}
      ${waiting ? `<p class="small muted">${answers ? "Sigue en curso…" : "Esperando la respuesta (un minuto o dos)…"}</p>` : ""}`;
    if (waiting) polling = setTimeout(check, POLL_MS);
    else loadRequests();
  };
  check();
}

async function loadRequests() {
  const list = document.getElementById("requests");
  const response = await fetch("/api/requests");
  const requests = response.ok ? await response.json() : null;
  if (!requests) {
    list.innerHTML = `<li class="warn">No se pudieron leer los pedidos.</li>`;
    return;
  }
  list.innerHTML = requests.length
    ? requests
        .map(
          (request) => `<li><button class="link" type="button" data-request="${request.number}">
            ${request.state === "open" ? "⏳" : "✓"} ${escapeHtml(request.title)}</button>
            <span class="small muted">${when(request.created_at)}</span></li>`,
        )
        .join("")
    : `<li class="muted">Todavía no hay pedidos.</li>`;
}

function initTools() {
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

function showDashboard(status) {
  main.innerHTML = [
    toolsCard(),
    sweepsCard(status.sweeps),
    geminiCard(status.gemini),
    instagramCard(status.instagram),
    accountsCard(status),
    `<p class="small muted">Datos del barrido de ${when(status.generated_at)}</p>`,
  ].join("");
  initTools();
}

function showMessage(html) {
  main.innerHTML = `<section class="card">${html}</section>`;
}

function showSignIn(note) {
  showMessage(`${note ? `<p>${escapeHtml(note)}</p>` : ""}
    <p>Esta página es solo para administrar Pa' Bailar.</p>
    <p><a class="button" href="/auth/login">Iniciar sesión con GitHub</a></p>`);
}

async function start() {
  const error = new URLSearchParams(location.search).get("error");
  if (error) history.replaceState(null, "", "/");

  const health = await fetch("/api/health").then((response) => response.json()).catch(() => null);
  if (!health) return showMessage(`<p>No se pudo contactar el servidor.</p>`);
  if (!health.configured) return showMessage(`<p>${MESSAGES.config}</p>`);

  const me = await fetch("/api/me");
  if (me.status === 401) return showSignIn(MESSAGES[error]);
  const { login } = await me.json();
  userLine.hidden = false;
  userLine.innerHTML = `@${escapeHtml(login)} · <a href="/auth/logout">Salir</a>`;

  const response = await fetch("/api/status");
  const status = await response.json().catch(() => ({ error: "Respuesta inválida." }));
  if (status.missing) return showMessage(`<p>Todavía no hay estado guardado: aparece después del próximo barrido.</p>`);
  if (!response.ok || status.error) return showMessage(`<p>${escapeHtml(status.error ?? "No se pudo leer el estado.")}</p>`);
  showDashboard(status);
}

start();
