// Tests for the admin page's pure rendering (public/render.js), with Node's own runner (the ci workflow runs them).

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { changesSummary, escapeHtml, historyCard, runLabel, seriesCard, shortDate, when } from "../public/render.js";

const SERIES = {
  id: "programa-intensivo-8-nov",
  title: "Programa intensivo",
  account: "salsa.club",
  sessions: "4 sesiones: 8, 22, 29 nov y 6 dic",
  url: "https://pa-bailar.github.io/evento/programa-intensivo-8-nov/",
  sources: [
    { kind: "post", link: "https://www.instagram.com/p/abc/" },
    { kind: "story", link: "https://www.instagram.com/salsa.club/" },
  ],
};

describe("the new series card", () => {
  it("shows each series with its sessions, sources, link and a hide button", () => {
    const html = seriesCard([SERIES]);
    assert.match(html, /<h2>Series nuevas<\/h2>/);
    assert.match(html, /4 sesiones: 8, 22, 29 nov y 6 dic/);
    assert.match(html, /@salsa\.club/);
    assert.match(html, /href="https:\/\/pa-bailar\.github\.io\/evento\/programa-intensivo-8-nov\/"/);
    assert.match(html, /<a href="https:\/\/www\.instagram\.com\/p\/abc\/"[^>]*>publicación<\/a>, <a [^>]*>historia<\/a>/);
    assert.match(html, /data-hide-event="programa-intensivo-8-nov"/);
  });

  it("is empty without series", () => {
    assert.equal(seriesCard([]), "");
    assert.equal(seriesCard(undefined), "");
  });

  it("escapes everything that comes from the data, and links only http(s)", () => {
    const evil = {
      ...SERIES,
      id: 'x" onclick="alert(1)',
      title: "<img src=x onerror=alert(1)>",
      account: "<b>a</b>",
      sessions: "<script>alert(1)</script>",
      url: "javascript:alert(1)",
      sources: [{ kind: "post", link: "javascript:alert(2)" }, { kind: "post", link: 'https://x.y/"><script>' }],
    };
    const html = seriesCard([evil]);
    assert.doesNotMatch(html, /<img|<script|<b>a|onclick="alert|javascript:/);
    assert.match(html, /data-hide-event="x&#34; onclick=&#34;alert\(1\)"/);
    assert.match(html, /&#60;img src=x onerror=alert\(1\)&#62;/);
    assert.match(html, /href="https:\/\/x\.y\/&#34;&#62;&#60;script&#62;"/);
  });

  it("escapes the five HTML characters", () => {
    assert.equal(escapeHtml(`<a href="x">'&'</a>`), "&#60;a href=&#34;x&#34;&#62;&#39;&#38;&#39;&#60;/a&#62;");
    assert.equal(escapeHtml(null), "");
  });
});

// ---------- the history (status.json's `history`: pa_bailar/status.py history_of) ----------

const NOW = new Date("2026-10-09T17:00:00-05:00");

const NEW_EVENT = {
  kind: "new",
  id: "social-de-salsa-11-oct",
  title: "Social de salsa",
  account: "lamecanica_original",
  date: "2026-10-11",
  detail: null,
  url: "https://pa-bailar.github.io/evento/social-de-salsa-11-oct/",
};

const MORNING = {
  kind: "sweep",
  slot: "06:30",
  finished_at: "2026-10-09T06:49:59-05:00",
  run_url: "https://github.com/pa-bailar/backend/actions/runs/1",
  changes: [
    NEW_EVENT,
    {
      ...NEW_EVENT,
      kind: "corrected",
      id: "taller",
      title: "Taller",
      detail: "Flash cambió la hora",
      url: "https://pa-bailar.github.io/evento/taller/",
    },
    { ...NEW_EVENT, kind: "cancelled", id: "rumba", title: "Rumba", url: "https://pa-bailar.github.io/evento/rumba/" },
  ],
  left_out: 0,
  counts: { cancelled: 1, new: 1, corrected: 1 },
};

describe("the history card", () => {
  it("is a collapsed section of runs, the newest open, each with what ran, when and its summary", () => {
    const old = {
      kind: "sweep",
      slot: "21:00",
      finished_at: "2026-10-08T21:20:00-05:00",
      changes: null,
      counts: { new: 2, merged: 1 },
    };
    const html = historyCard([MORNING, old], NOW);
    assert.match(html, /^<details class="card history">/);
    assert.match(html, /<h2>Historial<\/h2>/);
    assert.equal(html.match(/<details class="run" open>/g)?.length, 1);
    assert.equal(html.match(/<details class="run">/g)?.length, 1);
    assert.match(html, /Barrido de la mañana<\/span>\s*<span class="run__when">hoy 6:49 a\. m\.<\/span>/);
    assert.match(html, /1 cancelado · 1 nuevo · 1 corregido/);
    assert.match(html, /Barrido de la noche[\s\S]*ayer 9:20 p\. m\.[\s\S]*2 nuevos · 1 unido/);
  });

  it("lists each event with its label, title linked to the site, @account, day and what changed", () => {
    const html = historyCard([MORNING], NOW);
    assert.match(html, /<span class="tag tag--add">Nuevo<\/span>/);
    assert.match(html, /<span class="tag tag--fix">Corregido<\/span>/);
    assert.match(
      html,
      /<a class="change__title" href="https:\/\/pa-bailar\.github\.io\/evento\/social-de-salsa-11-oct\/"[^>]*>Social de salsa<\/a>/,
    );
    assert.match(html, /@lamecanica_original · dom 11 oct/);
    assert.match(html, /<span class="change__detail">Flash cambió la hora<\/span>/);
    assert.match(html, /href="https:\/\/github\.com\/pa-bailar\/backend\/actions\/runs\/1"[^>]*>ver en GitHub/);
  });

  it("doesn't link an event that left the site", () => {
    const html = historyCard([MORNING], NOW);
    assert.match(html, /tag--off">Cancelado<\/span>\s*<span class="change__body"><span class="change__title">Rumba</);
    assert.doesNotMatch(html, /evento\/rumba/);
  });

  it("says when a run is from before the history, changed nothing, left some out or couldn't run", () => {
    const old = { kind: "sweep", slot: null, finished_at: "2026-10-05T15:00:00-05:00", counts: { new: 3 } };
    assert.match(historyCard([old], NOW), /Barrido extra[\s\S]*3 nuevos[\s\S]*Sin detalle: es de antes del historial\./);
    const quiet = { ...MORNING, changes: [], counts: {} };
    assert.match(historyCard([quiet], NOW), /Sin cambios[\s\S]*Ningún evento cambió\./);
    assert.match(historyCard([{ ...MORNING, left_out: 12 }], NOW), /Y 12 más, solo contados\./);
    const failed = {
      kind: "hide_event",
      finished_at: MORNING.finished_at,
      target: "no-existe",
      error: "No encontré el evento",
      changes: [],
      counts: {},
    };
    const html = historyCard([failed], NOW);
    assert.match(html, /Ocultar evento[\s\S]*class="run__counts warn">No se pudo[\s\S]*⚠️ No encontré el evento/);
    assert.match(html, /<code>no-existe<\/code>/);
  });

  it("names the admin requests and links a post's request to the post", () => {
    const post = {
      kind: "post",
      finished_at: MORNING.finished_at,
      target: "https://www.instagram.com/p/abc/",
      changes: [NEW_EVENT],
      counts: { new: 1 },
    };
    const html = historyCard([post], NOW);
    assert.match(html, /Agregar publicación/);
    assert.match(html, /<a href="https:\/\/www\.instagram\.com\/p\/abc\/"[^>]*>la publicación<\/a>/);
    const hidden = { ...post, kind: "hide_event", target: NEW_EVENT.id, changes: [{ ...NEW_EVENT, kind: "hidden" }] };
    assert.doesNotMatch(historyCard([hidden], NOW), /<code>/); // the event is in the list already
    assert.equal(runLabel({ kind: "post_again", finished_at: "" }), "Volver a leer");
    assert.equal(runLabel({ kind: "story", finished_at: "" }), "Agregar historia");
    assert.equal(runLabel({ kind: "hide_story", finished_at: "" }), "Ocultar historia");
    assert.equal(runLabel({ kind: "__proto__", finished_at: "" }), "Pedido");
    assert.equal(runLabel({ kind: "sweep", slot: "13:00", finished_at: "" }), "Barrido de la tarde");
    assert.equal(runLabel({ kind: "sweep", slot: "03:00", finished_at: "" }), "Barrido de la madrugada"); // 9 Oct 2026
  });

  it("is empty without a history, and says so when it has none yet", () => {
    assert.equal(historyCard(undefined, NOW), "");
    assert.match(historyCard([], NOW), /Todavía no hay nada registrado/);
  });

  it("escapes everything that comes from the data, and links only http(s)", () => {
    const evil = {
      kind: "<script>",
      slot: "<b>",
      finished_at: MORNING.finished_at,
      run_url: "javascript:alert(1)",
      target: '"><img src=x onerror=alert(1)>',
      changes: [
        {
          kind: "<i>x</i>",
          id: 'x" onclick="alert(1)',
          title: "<img src=x onerror=alert(1)>",
          account: "<b>a</b>",
          date: "<script>alert(1)</script>",
          detail: "<u>u</u>",
          url: "javascript:alert(2)",
        },
        { ...NEW_EVENT, url: "javascript:alert(3)" },
      ],
      left_out: "<b>1</b>",
      counts: { new: "<b>" },
    };
    const html = historyCard([evil], NOW);
    assert.doesNotMatch(html, /<script|<img|<b>|<i>|<u>|onclick="|javascript:/);
    assert.match(html, /&#60;img src=x onerror=alert\(1\)&#62;/);
    assert.match(html, /<span class="tag tag--quiet">&#60;i&#62;x&#60;\/i&#62;<\/span>/);
    assert.match(html, /<span class="change__title">Social de salsa<\/span>/); // a bad link isn't linked
  });

  it("summarizes the counts in the order of what matters most", () => {
    assert.equal(
      changesSummary({ archived: 2, new: 3, merged: 1, flagged: 1 }),
      "1 por revisar · 3 nuevos · 1 unido · 2 archivados",
    );
    assert.equal(changesSummary({}), "Sin cambios");
    assert.equal(changesSummary(null), "Sin cambios");
  });

  it("dates events short and moments in Bogotá time", () => {
    assert.equal(shortDate("2026-10-11"), "dom 11 oct");
    assert.equal(shortDate("2026-12-31"), "jue 31 dic");
    assert.equal(shortDate("pronto"), "pronto");
    assert.equal(when("2026-10-09T02:30:00Z", NOW), "ayer 9:30 p. m."); // UTC, before Bogotá's midnight
    assert.equal(when("2026-10-04T09:00:00-05:00", NOW), "domingo 4/10, 9:00 a. m.");
  });
});
