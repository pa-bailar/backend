// Where things live, for the Node tools (tools/common.py is the Python twin).
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const MEDIA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
/**
 * PA_BAILAR_MEDIA_HOME as a path: a relative one is relative to the backend's root (media/'s parent), whatever the
 * working folder, as tools/common.py media_home() and remotion.config.ts resolve it.
 */
export const mediaHome = (raw) => (raw ? path.resolve(MEDIA, "..", raw) : "D:\\AI\\pa-bailar-media");
/** The media home (outside any checkout): cache/, public/<video>/, out/<video>/, archive/. */
export const HOME = mediaHome(process.env.PA_BAILAR_MEDIA_HOME);
export const OUT = path.join(HOME, "out");
export const PUBLIC = path.join(HOME, "public");

/**
 * The stills bundle's folder for one checkout's media/: out/.bundle-<8 hex of its path>. Worktrees share the home, so
 * one shared folder raced (one checkout's bundle replaced another's mid-render).
 */
export function bundleDir(media = MEDIA) {
  const id = createHash("sha256").update(path.resolve(media).toLowerCase()).digest("hex").slice(0, 8);
  return path.join(OUT, `.bundle-${id}`);
}
