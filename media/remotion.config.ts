// Render defaults for every video (CLI flags override them per render).
import path from "node:path";
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
Config.setOverwriteOutput(true);
Config.setCodec("h264");
Config.setPixelFormat("yuv420p");
// staticFile() reads each video's screens, flyers and audio from the media home (tools/paths.mjs, tools/common.py),
// not from the checkout: worktrees share it and removing one can't delete it. A relative PA_BAILAR_MEDIA_HOME is
// relative to the backend's root, as in the tools (the Remotion CLI runs from media/: render.py and npm scripts).
const home = process.env.PA_BAILAR_MEDIA_HOME;
Config.setPublicDir(path.join(home ? path.resolve(process.cwd(), "..", home) : "D:\\AI\\pa-bailar-media", "public"));
