// Where things live, for the Node tools (tools/common.py is the Python twin).
import path from "node:path";
import { fileURLToPath } from "node:url";

export const MEDIA = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const OUT = path.join(MEDIA, "out");
export const PUBLIC = path.join(MEDIA, "public");
