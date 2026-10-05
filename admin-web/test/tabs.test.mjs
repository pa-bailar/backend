// Tests for the admin page's tabs (public/tabs.js): which one opens, the keys, the markup. Node's own runner
// (the ci workflow runs them).

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { initialTab, tabAfterKey, tabFromHash, tabsHtml, TABS } from "../public/tabs.js";

describe("the tab that opens", () => {
  it("is Estadísticas on a first visit", () => {
    assert.equal(initialTab(), "estadisticas");
    assert.equal(initialTab({ hash: "", stored: null }), "estadisticas");
  });

  it("is the one picked last time", () => {
    assert.equal(initialTab({ stored: "herramientas" }), "herramientas");
    assert.equal(initialTab({ stored: "something-else" }), "estadisticas");
  });

  it("is the one the URL's hash names, over the remembered one", () => {
    assert.equal(initialTab({ hash: "#estadisticas", stored: "herramientas" }), "estadisticas");
    assert.equal(initialTab({ hash: "#Herramientas" }), "herramientas");
    assert.equal(initialTab({ hash: "#nope", stored: "herramientas" }), "herramientas");
  });

  it("is Herramientas when something was shared to the page, whatever else says", () => {
    assert.equal(initialTab({ shared: true, hash: "#estadisticas", stored: "estadisticas" }), "herramientas");
  });

  it("reads a hash with or without #, and nothing else", () => {
    assert.equal(tabFromHash("#herramientas"), "herramientas");
    assert.equal(tabFromHash("estadisticas"), "estadisticas");
    assert.equal(tabFromHash("#tools"), null);
    assert.equal(tabFromHash(undefined), null);
  });
});

describe("the keys", () => {
  it("move with the arrows, wrapping around, and jump with Home and End", () => {
    assert.equal(tabAfterKey("estadisticas", "ArrowRight"), "herramientas");
    assert.equal(tabAfterKey("herramientas", "ArrowRight"), "estadisticas");
    assert.equal(tabAfterKey("estadisticas", "ArrowLeft"), "herramientas");
    assert.equal(tabAfterKey("herramientas", "Home"), "estadisticas");
    assert.equal(tabAfterKey("estadisticas", "End"), "herramientas");
  });

  it("ignore the other keys", () => {
    assert.equal(tabAfterKey("estadisticas", "Enter"), null);
    assert.equal(tabAfterKey("estadisticas", "ArrowDown"), null);
  });
});

describe("the tabs' markup", () => {
  const html = tabsHtml("herramientas", { estadisticas: "<p>stats</p>", herramientas: "<p>tools</p>" });

  it("is an accessible tab list, one tab per panel", () => {
    assert.match(html, /role="tablist"/);
    assert.equal(html.match(/role="tab"/g).length, TABS.length);
    assert.equal(html.match(/role="tabpanel"/g).length, TABS.length);
    assert.match(html, /id="tab-estadisticas"[^>]*aria-controls="panel-estadisticas"[^>]*aria-selected="false" tabindex="-1">Estadísticas</);
    assert.match(html, /id="tab-herramientas"[^>]*aria-controls="panel-herramientas"[^>]*aria-selected="true" tabindex="0">Herramientas</);
    assert.match(html, /id="panel-herramientas" aria-labelledby="tab-herramientas"/);
  });

  it("shows only the selected panel, each with its content", () => {
    assert.match(html, /id="panel-estadisticas"[^>]* hidden><p>stats<\/p>/);
    assert.match(html, /id="panel-herramientas"[^>]*tabindex="0"><p>tools<\/p>/);
  });

  it("counts the new series on Herramientas, for screen readers too, and nothing when there are none", () => {
    const one = tabsHtml("estadisticas", {}, { herramientas: 1 });
    assert.match(one, /Herramientas <span class="tab__badge" aria-hidden="true">1<\/span><span class="visually-hidden"> \(1 serie nueva\)/);
    assert.match(tabsHtml("estadisticas", {}, { herramientas: 3 }), /\(3 series nuevas\)/);
    assert.doesNotMatch(tabsHtml("estadisticas", {}, { herramientas: 0 }), /tab__badge/);
  });
});
