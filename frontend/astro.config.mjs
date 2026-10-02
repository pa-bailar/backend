import { defineConfig } from "astro/config";

// The backend writes events.json and flyers/ into ../data, which is served as the site's public folder.
export default defineConfig({
  publicDir: "../data",
});
