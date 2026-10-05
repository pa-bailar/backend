// The admin page in the browser: who's signed in, then the dashboard drawn from `admin status` (status.json,
// written by each sweep: pa_bailar/status.py). All data comes from the Worker (src/index.js), after GitHub
// sign-in; this file has none. A post shared to the installed page (Android's share menu) fills in the tools;
// story screenshots shared to it (received by sw.js) or picked here go to "Agregar desde una historia".

import { escapeHtml, seriesCard } from "./render.js";

const main = document.getElementById("main");
const userLine = document.getElementById("user");
const WEEKDAYS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
const ROLES = { triage: "filtro", extraction: "extracción", provisional: "provisional", discovery: "descubrimiento" };
const MESSAGES = {
  config: "Falta configurar el inicio de sesión: los secretos de GitHub en Cloudflare (docs/ADMIN.md).",
  login: "No se pudo iniciar sesión con GitHub. Intenta de nuevo.",
  denied: "Esa cuenta de GitHub no tiene acceso a esta página.",
};


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
      // A published story's flyer (its receipt), only from the site: the page's CSP allows no other images.
      .replace(
        /!\[([^\]]*)\]\((https:\/\/pa-bailar\.github\.io\/[\w./-]+\.webp)\)/g,
        '<img class="answer__image" src="$2" alt="$1" loading="lazy" />',
      )
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
    <form id="story-form" class="tool">
      <h3 class="tool__title">Agregar desde una historia</h3>
      <p class="small muted">Toma captura de pantalla de la historia y compártela con PB Admin, o elígela aquí. Hasta
        ${STORY_MAX} capturas de la misma historia.</p>
      <div class="shots" id="story-shots"></div>
      <label class="button button--outline file-button">Elegir capturas
        <input id="story-files" class="file-button__input" type="file" accept="image/*" multiple /></label>
      <label for="story-account">@cuenta <span class="muted">(opcional: se lee de la imagen)</span></label>
      <input id="story-account" type="text" placeholder="@academia" autocapitalize="none" autocomplete="off" />
      <label for="story-notes">Notas <span class="muted">(opcional, no se publican)</span></label>
      <textarea id="story-notes" rows="2" maxlength="500" placeholder="sábado 12, Galería Café Libro"></textarea>
      <div class="tool__buttons">
        <button class="button" type="submit" id="story-send">Agregar desde historia</button>
      </div>
      <p class="small muted">Si la historia comparte una publicación (se ve su tarjeta), mejor toca la tarjeta y comparte
        la publicación: trae su enlace, una imagen mejor y el texto.</p>
      <p class="small muted" id="uploads-waiting" hidden></p>
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

/** Open a request ({action, link?, account?, images?, notes?, story?, event?}) and follow it. True when it went. */
async function send(request) {
  if (sending) return false;
  sending = true;
  setAnswer(`<p class="muted">Enviando…</p>`);
  const result = await getJson("/api/requests", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  sending = false;
  if (!result?.ok) {
    const error = result ? result.data?.error ?? "No se pudo enviar." : "No se pudo enviar: revisa la conexión.";
    setAnswer(`<p class="warn">${escapeHtml(error)}</p>`);
    return false;
  }
  follow(result.data.number);
  loadRequests();
  return true;
}

/** The answer area, rewritten only when it changes: it's a live region, and each rewrite is read out again. */
let shownAnswer = null;
function setAnswer(html) {
  if (html === shownAnswer) return;
  shownAnswer = html;
  const answer = document.getElementById("answer");
  answer.innerHTML = html;
  // A story's flyer is on the site only once its data is published (a few minutes): until then, no broken image.
  answer.querySelectorAll("img").forEach((image) => image.addEventListener("error", () => image.remove(), { once: true }));
}

const HIDE_COMMAND = /\/ocultar (story-[a-f0-9]{16})/; // in the answer to a story: undo it (pa_bailar/stories.py)

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
    // A story published from screenshots: one button takes it off the site again ("Ocultar historia").
    const story = request.answers.map((item) => item.body.match(HIDE_COMMAND)?.[1]).filter(Boolean).at(-1);
    const undo = story && !open
      ? `<div class="tool__buttons"><button class="button button--outline" type="button" data-hide="${escapeHtml(story)}">Ocultar del sitio (deshacer)</button></div>`
      : "";
    setAnswer(`<div class="answer__head"><b>${escapeHtml(request.title)}</b>
        <a class="small" href="${escapeHtml(request.url)}" target="_blank" rel="noopener">#${escapeHtml(request.number)}</a></div>
      ${answers}${undo}
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
    const link = document.getElementById("post-link").value;
    send({ action, link, account: document.getElementById("post-account").value });
  });
  document.getElementById("account-form").addEventListener("submit", (event) => {
    event.preventDefault();
    send({ action: "add-account", account: document.getElementById("new-account").value });
  });
  document.getElementById("requests").addEventListener("click", (event) => {
    const button = event.target.closest("[data-request]");
    if (button) follow(button.dataset.request);
  });
  document.getElementById("answer").addEventListener("click", (event) => {
    const button = event.target.closest("[data-hide]");
    if (button && confirm("¿Quitar del sitio lo que se publicó desde esta historia?")) {
      send({ action: "hide-story", story: button.dataset.hide });
    }
  });
  initStoryForm();
  loadRequests();
}

// ---------- a story: screenshots shared here (sw.js) or picked, shrunk here, uploaded, then one request ----------

const STORY_CACHE = "shared-images"; // also sw.js's: shared and picked screenshots wait here, even across a sign-in
const STORY_MAX = 4;
const STORY_MAX_AGE_MS = 24 * 60 * 60 * 1000;
const STORY_WIDTH = 1080; // Instagram's story width: more only makes the upload bigger
const STATUS_BAR = 0.06; // of a phone screenshot's width: Android's status bar (24 dp), cut off before uploading
const STORY_ACCOUNT_KEY = "shared-story-account";
let shots = []; // {key, file, url, uploaded}: what's waiting to be sent, in order

async function storyCache() {
  try {
    return "caches" in window ? await caches.open(STORY_CACHE) : null;
  } catch {
    return null; // storage blocked: the screenshots then live only while the page is open
  }
}

/** The screenshots waiting in this browser (shared or picked earlier), oldest first; expired ones are dropped. */
async function loadShots() {
  const cache = await storyCache();
  if (!cache) return;
  const loaded = [];
  for (const request of await cache.keys()) {
    const response = await cache.match(request);
    const at = Number(response?.headers.get("X-At"));
    if (!response || !(Date.now() - at < STORY_MAX_AGE_MS)) {
      await cache.delete(request);
      continue;
    }
    let name = "";
    try {
      name = decodeURIComponent(response.headers.get("X-Name") ?? "");
    } catch {}
    const modified = Number(response.headers.get("X-Modified")) || at;
    const blob = await response.blob();
    const file = new File([blob], name || "captura", { type: blob.type || "image/jpeg", lastModified: modified });
    loaded.push({ key: request.url, file, url: URL.createObjectURL(file), uploaded: null });
  }
  shots.forEach((shot) => URL.revokeObjectURL(shot.url));
  shots = loaded.slice(-STORY_MAX);
}

/** Picked screenshots join the waiting ones (kept like shared ones, so a sign-in doesn't lose them). */
async function addShots(files) {
  const cache = await storyCache();
  const at = Date.now();
  for (const [index, file] of [...files].entries()) {
    if (!file.type.startsWith("image/")) continue;
    let key = null;
    if (cache) {
      key = new URL(`/shared/${at}-${index}`, location.origin).href;
      const headers = {
        "Content-Type": file.type,
        "X-Name": encodeURIComponent(file.name),
        "X-Modified": String(file.lastModified || ""),
        "X-At": String(at),
      };
      await cache.put(key, new Response(file, { headers })).catch(() => (key = null));
    }
    shots.push({ key, file, url: URL.createObjectURL(file), uploaded: null });
  }
  while (shots.length > STORY_MAX) await removeShot(0);
}

async function removeShot(index) {
  const [shot] = shots.splice(index, 1);
  if (!shot) return;
  URL.revokeObjectURL(shot.url);
  const cache = shot.key ? await storyCache() : null;
  await cache?.delete(shot.key);
}

function renderShots() {
  const list = document.getElementById("story-shots");
  list.innerHTML = shots
    .map(
      (shot, index) => `<figure class="shot"><img src="${escapeHtml(shot.url)}" alt="Captura ${index + 1}" />
        <button class="shot__remove" type="button" data-remove="${index}" aria-label="Quitar la captura ${index + 1}"></button></figure>`,
    )
    .join("");
  list.hidden = !shots.length;
}

/** Decode a screenshot (createImageBitmap, or an <img> where it can't, e.g. HEIC on older Safari). */
async function decode(file) {
  if ("createImageBitmap" in window) {
    try {
      return await createImageBitmap(file);
    } catch {}
  }
  const image = new Image();
  image.src = URL.createObjectURL(file);
  try {
    await image.decode();
    return image;
  } finally {
    URL.revokeObjectURL(image.src);
  }
}

/** Shrink to STORY_WIDTH, cut a phone screenshot's status bar (notifications), and re-encode as JPEG (which
 * also drops the photo's metadata). The file's own name and date were read before, for when it was taken. */
async function prepareShot(file) {
  const picture = await decode(file);
  const sourceWidth = picture.width;
  const sourceHeight = picture.height;
  const cut = sourceHeight / sourceWidth >= 1.9 ? Math.round(sourceWidth * STATUS_BAR) : 0;
  const scale = Math.min(1, STORY_WIDTH / sourceWidth);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(sourceWidth * scale);
  canvas.height = Math.round((sourceHeight - cut) * scale);
  const context = canvas.getContext("2d");
  context.fillStyle = "#ffffff"; // a transparent PNG becomes white, not black
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.drawImage(picture, 0, cut, sourceWidth, sourceHeight - cut, 0, 0, canvas.width, canvas.height);
  picture.close?.();
  const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", 0.86));
  if (!blob) throw new Error("No se pudo preparar la captura en este navegador.");
  return blob;
}

/** Upload one screenshot (once: a retry reuses its id) → its id. */
async function uploadShot(shot) {
  if (shot.uploaded) return shot.uploaded;
  const body = await prepareShot(shot.file);
  let response;
  try {
    response = await fetch("/api/uploads", {
      method: "POST",
      headers: {
        "Content-Type": "image/jpeg",
        "X-File-Name": encodeURIComponent(shot.file.name.slice(0, 120)),
        "X-File-Modified": String(shot.file.lastModified || ""),
      },
      body,
    });
  } catch {
    throw new Error("No se pudo subir la captura: revisa la conexión.");
  }
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) throw new Error("La sesión venció: recarga la página e inicia sesión (las capturas quedan guardadas aquí).");
  if (!response.ok) throw new Error(data.error ?? `El servidor respondió ${response.status} al subir la captura.`);
  shot.uploaded = data.id;
  return data.id;
}

let preparing = false;

async function sendStory() {
  if (preparing || sending) return;
  if (!shots.length) {
    setAnswer(`<p class="warn">Elige o comparte al menos una captura de la historia.</p>`);
    return;
  }
  preparing = true;
  const button = document.getElementById("story-send");
  button.disabled = true;
  const images = [];
  try {
    for (const [index, shot] of shots.entries()) {
      setAnswer(`<p class="muted">Subiendo captura ${index + 1} de ${shots.length}…</p>`);
      images.push(await uploadShot(shot));
    }
  } catch (error) {
    setAnswer(`<p class="warn">${escapeHtml(error.message)}</p>`);
    return;
  } finally {
    preparing = false;
    button.disabled = false;
  }
  const account = document.getElementById("story-account");
  const notes = document.getElementById("story-notes");
  if (await send({ action: "add-story", images, account: account.value, notes: notes.value })) {
    while (shots.length) await removeShot(0);
    renderShots();
    account.value = "";
    notes.value = "";
    try {
      localStorage.removeItem(STORY_ACCOUNT_KEY);
    } catch {}
    loadWaiting();
  }
}

/** "Capturas en espera": screenshots uploaded and not yet published (or expiring), from the Worker. */
async function loadWaiting() {
  const line = document.getElementById("uploads-waiting");
  const result = await getJson("/api/uploads");
  if (!line) return;
  line.hidden = !result?.ok;
  if (result?.ok) {
    const { waiting, more } = result.data;
    line.textContent = `Capturas en espera: ${waiting}${more ? "+" : ""} (se borran al publicarse su evento, o solas a los 7 días).`;
  }
}

function initStoryForm() {
  const form = document.getElementById("story-form");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendStory();
  });
  document.getElementById("story-files").addEventListener("change", async (event) => {
    await addShots(event.target.files);
    event.target.value = ""; // the same file can be picked again
    renderShots();
  });
  document.getElementById("story-shots").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-remove]");
    if (!button) return;
    await removeShot(Number(button.dataset.remove));
    renderShots();
  });
  const account = storyAccount();
  if (account) document.getElementById("story-account").value = `@${account}`;
  renderShots();
  loadWaiting();
}

// ---------- a post shared from Instagram (Android's share menu: manifest.webmanifest's share_target) ----------

const SHARED_KEY = "shared-post";
const SHARED_MAX_AGE_MS = 30 * 60 * 1000;
const INSTAGRAM_POST = /https?:\/\/(?:www\.|m\.)?instagram\.com\/(?:[\w.]+\/)?(?:p|reel|reels|tv)\/[\w-]+\/?/i;
const INSTAGRAM_STORY = /https?:\/\/(?:www\.|m\.)?instagram\.com\/stories\/([A-Za-z0-9._]{1,30})\//i;
let sharedFallback = null; // when the browser's storage is blocked
let storyAccountFallback = null;

/**
 * Keep a shared post's link (Android sends it as ?text= or ?url=), so it survives the GitHub sign-in.
 * "post"; "story" for a story's link (only its account is kept, for its screenshot: a link alone can't be read);
 * "other" when what was shared is neither (a profile); null when nothing was.
 */
function keepSharedLink(params) {
  const text = ["url", "text", "link"].map((name) => params.get(name) ?? "").join(" ");
  if (!text.trim()) return null;
  const link = text.match(INSTAGRAM_POST)?.[0]; // without Instagram's tracking (?igsh=…)
  const story = text.match(INSTAGRAM_STORY)?.[1];
  if (!link && story) {
    storyAccountFallback = story.toLowerCase();
    try {
      localStorage.setItem(STORY_ACCOUNT_KEY, JSON.stringify({ account: storyAccountFallback, at: Date.now() }));
    } catch {}
    return "story";
  }
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

/** The account of a story whose link was shared in the last 30 minutes (its screenshot comes next), or null. */
function storyAccount() {
  try {
    const kept = JSON.parse(localStorage.getItem(STORY_ACCOUNT_KEY) ?? "null");
    if (kept && Date.now() - kept.at < SHARED_MAX_AGE_MS) return kept.account;
  } catch {}
  return storyAccountFallback;
}

function useSharedLink(shared, share) {
  const link = takeSharedLink();
  const form = document.getElementById("post-form");
  const storyForm = document.getElementById("story-form");
  const note = (target, html) => {
    const place = target.querySelector(".tool__title"); // the story form: under its title
    (place ?? target).insertAdjacentHTML(place ? "afterend" : "afterbegin", `<p class="shared">📎 ${html}</p>`);
  };
  if (link) {
    document.getElementById("post-link").value = link;
    note(form, "Enlace recibido: elige <b>Revisar</b>, <b>Agregar</b> o <b>Volver a leer</b>.");
  } else if (shared === "story") {
    note(
      storyForm,
      `Enlace de una historia de @${escapeHtml(storyAccount())}: un enlace solo no se puede leer. Toma captura de la
        historia y compártela con PB Admin (o elígela aquí): la @cuenta queda puesta 30 minutos.`,
    );
  } else if (shared === "other") {
    note(form, "Lo que compartiste no es el enlace de una publicación (instagram.com/p/… o /reel/…) ni de una historia.");
  }
  if (share === "images") note(storyForm, "Capturas recibidas: revisa la @cuenta y las notas, y toca <b>Agregar desde historia</b>.");
  if (share === "retry") note(storyForm, "No llegó lo que compartiste (PB Admin aún no estaba lista): vuelve a compartirlo.");
  // After the fonts load, which moves what's above it.
  if (shared === "story" || share) document.fonts.ready.then(() => storyForm.scrollIntoView({ block: "start" }));
}

/** The status cards from status.json, or a note when there's none: the tools above work without it. */
function statusCards(result) {
  const status = result?.data;
  if (!result) return card(`<p>No se pudo leer el estado: revisa la conexión.</p>`);
  if (status?.missing) return card(`<p>Todavía no hay estado guardado: aparece después del próximo barrido.</p>`);
  if (!result.ok || status?.error) return card(`<p>${escapeHtml(status?.error ?? "No se pudo leer el estado.")}</p>`);
  try {
    return [
      seriesCard(status.new_series), // first: it may need a tap
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

async function showDashboard(cards, shared, share) {
  await loadShots(); // before drawing: the tools show the screenshots waiting
  main.innerHTML = toolsCard() + cards;
  // The meters' fill, set here: the Content Security Policy (public/_headers) blocks style="" in the HTML.
  main.querySelectorAll(".meter i[data-share]").forEach((bar) => (bar.style.width = `${bar.dataset.share}%`));
  initTools();
  // "Series nuevas" (render.js): one tap hides a series from the site, through the same requests as the tools.
  main.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-hide-event]");
    if (!button || !confirm(`¿Quitar “${button.dataset.title}” del sitio? Los barridos no lo vuelven a publicar.`)) return;
    if (await send({ action: "hide-event", event: button.dataset.hideEvent })) {
      button.disabled = true;
      document.getElementById("answer").scrollIntoView({ block: "center" });
    }
  });
  useSharedLink(shared, share);
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
  // Receives what Android's share menu sends (manifest.webmanifest): story screenshots and links.
  navigator.serviceWorker?.register("/sw.js").catch(() => {});
  const params = new URLSearchParams(location.search);
  const error = params.get("error");
  const shared = keepSharedLink(params);
  const share = ["images", "retry"].includes(params.get("share")) ? params.get("share") : null;
  if (error || shared || params.has("share")) history.replaceState(null, "", "/");

  const health = await getJson("/api/health");
  if (!health?.ok) return showMessage(`<p>No se pudo contactar el servidor.</p>`);
  if (!health.data.configured) return showMessage(`<p>${MESSAGES.config}</p>`);

  const me = await getJson("/api/me");
  if (me?.status === 401) {
    const kept = {
      post: "Inicia sesión para usar el enlace que compartiste.",
      story: "Inicia sesión: la @cuenta de la historia queda guardada 30 minutos.",
    }[shared];
    const images = share === "images" ? "Inicia sesión para agregar las capturas que compartiste (quedan guardadas aquí)." : "";
    const note = Object.hasOwn(MESSAGES, error) ? MESSAGES[error] : "";
    return showSignIn(note || kept || images);
  }
  if (!me?.ok) return showMessage(`<p>No se pudo contactar el servidor.</p>`);
  userLine.hidden = false;
  userLine.innerHTML = `@${escapeHtml(me.data.login)} · <a href="/auth/logout">Salir</a>`;

  const status = await getJson("/api/status");
  // GitHub turned the session's token down (the App's access was revoked): sign in again.
  if (status?.status === 401) return showSignIn(status.data?.error);
  await showDashboard(statusCards(status), shared, share);
}

start();
