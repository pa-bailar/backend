// Link-preview image of each event page (/og/<id>.jpg): its flyer as a small JPEG.
// Flyers are stored as WebP, which not every app shows in previews, and WhatsApp skips preview
// images over ~300 KB. Made at build time, so nothing extra is stored in the repository.

import { readFile } from "node:fs/promises";
import path from "node:path";
import type { APIRoute, GetStaticPaths } from "astro";
import sharp from "sharp";
import events from "../../../../data/events.json";
import type { DanceEvent } from "../../scripts/types";
import { mainMedia } from "../../scripts/lib/links";

const DATA_DIR = path.resolve(process.cwd(), "../data"); // the site's public folder (astro.config.mjs)
const PREVIEW_WIDTH = 600;

export const getStaticPaths: GetStaticPaths = () =>
  (events as DanceEvent[])
    .filter((event) => mainMedia(event).flyer)
    .map((event) => ({ params: { id: event.id }, props: { flyer: mainMedia(event).flyer } }));

export const GET: APIRoute = async ({ props }) => {
  const source = await readFile(path.join(DATA_DIR, props.flyer as string));
  const jpeg = await sharp(source)
    .resize({ width: PREVIEW_WIDTH, withoutEnlargement: true })
    .jpeg({ quality: 80, mozjpeg: true })
    .toBuffer();
  return new Response(new Uint8Array(jpeg), { headers: { "Content-Type": "image/jpeg" } });
};
