import { defineConfig } from "astro/config";

// Published on GitHub Pages at https://pa-bailar.github.io (repo pa-bailar/pa-bailar.github.io, served at the root).
// The backend writes events.json, meta.json and flyers/ into ../data, served as the site's public folder.
export default defineConfig({
  site: "https://pa-bailar.github.io",
  publicDir: "../data",
});
