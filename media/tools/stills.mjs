// Fast stills: bundle the project once (reused while nothing it reads has changed), open one browser, and render as
// many frames as you ask for. For looking at a few moments of a video, or comparing them before and after a change.
//
//   node media/tools/stills.mjs <video> [deliverable] --at 1.5,f300,c4:link,c4:link:1,c4 [--scale 0.5] [--no-blur]
//        [--out <folder>]
//   → out/<video>/frames/<deliverable>-<frame>.png (or --out), one per time, and their paths printed
//
// Times: seconds (1.5), a frame (f300), a line's start (c4) or a word's start (c4:link, the nth with c4:link:1), from
// the video's data/timing.json (the same lookups as makeTiming() in src/lib/timing.ts). The deliverable is one of
// video.json's "renders" (default: the first). The bundle lives in out/.bundle/ with a key of every file it reads
// (src/, projects/, the public files): a second run with nothing changed starts rendering in a second or two.
import { createHash } from "node:crypto";
import { existsSync } from "node:fs";
import { mkdir, readdir, readFile, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { arg, flag, positionals } from "./capture.mjs";
import { MEDIA, OUT, PUBLIC } from "./paths.mjs";

/** Every file under `dir` (recursively), skipping node_modules. */
async function files(dir) {
  if (!existsSync(dir)) return [];
  const out = [];
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    if (entry.name === "node_modules") continue;
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...(await files(full)));
    else out.push(full);
  }
  return out;
}

/** A key over the paths, sizes and mtimes of everything the bundle reads. */
async function sourceKey() {
  const hash = createHash("sha256");
  const all = [
    ...(await files(path.join(MEDIA, "src"))),
    ...(await files(path.join(MEDIA, "projects"))),
    ...(await files(PUBLIC)),
    path.join(MEDIA, "package-lock.json"),
    path.join(MEDIA, "brand.json"),
    ...(await files(path.join(MEDIA, "fonts"))),
  ];
  for (const f of all.sort()) {
    const s = await stat(f).catch(() => null);
    if (s) hash.update(`${f}|${s.size}|${s.mtimeMs}\n`);
  }
  return hash.digest("hex").slice(0, 16);
}

/** The bundle's folder: the cached one when its key matches, else a fresh bundle. */
export async function bundled() {
  const dir = path.join(OUT, ".bundle");
  const key = await sourceKey();
  const keyFile = path.join(dir, "key.txt");
  if ((await readFile(keyFile, "utf8").catch(() => "")) === key && existsSync(path.join(dir, "index.html"))) {
    return dir;
  }
  const { bundle } = await import("@remotion/bundler");
  await rm(dir, { recursive: true, force: true });
  const t0 = Date.now();
  await bundle({ entryPoint: path.join(MEDIA, "src", "index.ts"), outDir: dir, publicDir: PUBLIC });
  await writeFile(keyFile, key);
  console.log(`   bundled in ${((Date.now() - t0) / 1000).toFixed(1)} s`);
  return dir;
}

const norm = (s) =>
  s
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z']/g, "");

/** "1.5" → seconds, "f300" → frame, "c4" → a line's start, "c4:link[:n]" → a word's start; returns the frame. */
export function frameAt(spec, fps, timing) {
  if (/^f\d+$/.test(spec)) return Number(spec.slice(1));
  if (/^\d+(\.\d+)?$/.test(spec)) return Math.round(Number(spec) * fps);
  const [id, word, nth = "0"] = spec.split(":");
  const line = timing?.lines.find((l) => l.id === id);
  if (!line) throw new Error(`no line "${id}" in data/timing.json (times are seconds, f<frame>, <line> or <line>:<word>)`);
  if (!word) return Math.round(line.start * fps);
  const hit = line.words.filter((w) => norm(w.word) === norm(word))[Number(nth)];
  if (!hit) throw new Error(`no word "${word}" (#${nth}) in ${id}`);
  return Math.round(hit.start * fps);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [video, wanted] = positionals(["at", "scale", "out"]);
  const at = arg("at");
  if (!video || !at) {
    console.error("usage: node media/tools/stills.mjs <video> [deliverable] --at 1.5,f300,c4:link [--scale 0.5] [--no-blur] [--out dir]");
    process.exit(1);
  }
  const folder = path.join(MEDIA, "projects", video);
  const settings = JSON.parse(await readFile(path.join(folder, "video.json"), "utf8"));
  const deliverable = wanted ?? Object.keys(settings.renders)[0];
  const id = settings.renders[deliverable];
  if (!id) throw new Error(`no deliverable "${deliverable}": video.json has ${Object.keys(settings.renders).join(", ")}`);
  const timing = JSON.parse(await readFile(path.join(folder, "data", "timing.json"), "utf8").catch(() => "null"));
  const outDir = arg("out") ? path.resolve(arg("out")) : path.join(OUT, video, "frames");
  // From media/: Remotion keeps its browser in the working folder's node_modules/.remotion.
  process.chdir(MEDIA);
  const { openBrowser, renderStill, selectComposition } = await import("@remotion/renderer");
  const serveUrl = await bundled();
  const browser = await openBrowser("chrome");
  try {
    const inputProps = flag("no-blur") ? { blur: false } : {};
    const composition = await selectComposition({ serveUrl, id, inputProps, puppeteerInstance: browser });
    const dest = outDir;
    await mkdir(dest, { recursive: true });
    for (const spec of at.split(",")) {
      const frame = Math.min(frameAt(spec.trim(), composition.fps, timing), composition.durationInFrames - 1);
      const output = path.join(dest, `${deliverable}-${String(frame).padStart(4, "0")}.png`);
      await renderStill({
        serveUrl,
        composition,
        frame,
        output,
        inputProps,
        puppeteerInstance: browser,
        scale: Number(arg("scale", 1)),
        overwrite: true,
      });
      console.log(output.replaceAll("\\", "/"));
    }
  } finally {
    await browser.close({ silent: true });
  }
}
