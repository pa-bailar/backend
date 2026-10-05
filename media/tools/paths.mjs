// Where things live, for the Node tools (tools/common.py is the Python twin).
import { createHash } from "node:crypto";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const MEDIA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
/** The media home (outside any checkout): cache/, public/<video>/, out/<video>/, archive/. */
export const HOME = process.env.PA_BAILAR_MEDIA_HOME || "D:\\AI\\pa-bailar-media";
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
