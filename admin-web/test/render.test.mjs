// Tests for the admin page's pure rendering (public/render.js), with Node's own runner (the ci workflow runs them).

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { escapeHtml, seriesCard } from "../public/render.js";

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
