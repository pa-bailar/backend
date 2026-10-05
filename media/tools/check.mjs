// `npm run check` (after tsc): every composition registers, and one still per video renders (its middle frame, quarter
// size) → out/check/<composition>.png in the media home. Uses the stills bundle (tools/stills.mjs), so a second run
// with nothing changed takes seconds. Exit code 1 when anything fails.
import { mkdir, readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { bundled } from "./stills.mjs";
import { MEDIA, OUT } from "./paths.mjs";

process.chdir(MEDIA); // Remotion keeps its browser in media/node_modules/.remotion
const { getCompositions, openBrowser, renderStill } = await import("@remotion/renderer");
const serveUrl = await bundled();
const browser = await openBrowser("chrome");
let failed = 0;
try {
  const compositions = await getCompositions(serveUrl, { puppeteerInstance: browser });
  console.log(`${compositions.length} compositions: ${compositions.map((c) => c.id).join(", ")}`);
  const dest = path.join(OUT, "check");
  await mkdir(dest, { recursive: true });
  // One still per video: the first of its video.json "renders".
  const first = [];
  for (const video of await readdir(path.join(MEDIA, "projects"))) {
    const settings = JSON.parse(await readFile(path.join(MEDIA, "projects", video, "video.json"), "utf8").catch(() => "{}"));
    const id = Object.values(settings.renders ?? {})[0];
    if (id && !compositions.some((c) => c.id === id)) {
      failed++;
      console.error(`FAIL ${video}: video.json renders ${id}, which isn't registered (src/Root.tsx)`);
    } else if (id) first.push(id);
  }
  for (const composition of compositions.filter((c) => first.includes(c.id))) {
    const output = path.join(dest, `${composition.id}.png`);
    try {
      await renderStill({
        serveUrl,
        composition,
        frame: Math.floor(composition.durationInFrames / 2),
        output,
        puppeteerInstance: browser,
        scale: 0.25,
        overwrite: true,
      });
      console.log(`ok   ${composition.id}: ${output.replaceAll("\\", "/")}`);
    } catch (error) {
      failed++;
      console.error(`FAIL ${composition.id}: ${error.message}`);
    }
  }
} finally {
  await browser.close({ silent: true });
}
process.exit(failed ? 1 : 0);
