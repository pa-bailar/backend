// Where things live, for the Node tools (tools/common.py is the Python twin).
import path from "node:path";
import { fileURLToPath } from "node:url";

export const MEDIA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
/** The media home (outside any checkout): cache/, public/<video>/, out/<video>/, archive/. */
export const HOME = process.env.PA_BAILAR_MEDIA_HOME || "D:\\AI\\pa-bailar-media";
export const OUT = path.join(HOME, "out");
export const PUBLIC = path.join(HOME, "public");
