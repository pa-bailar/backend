// Render defaults for every video (CLI flags override them per render).
import path from "node:path";
import { Config } from "@remotion/cli/config";

Config.setVideoImageFormat("jpeg");
Config.setJpegQuality(92);
Config.setOverwriteOutput(true);
Config.setCodec("h264");
Config.setPixelFormat("yuv420p");
// staticFile() reads each video's screens, flyers and audio from the media home (tools/paths.mjs, tools/common.py),
// not from the checkout: worktrees share it and removing one can't delete it.
Config.setPublicDir(path.join(process.env.PA_BAILAR_MEDIA_HOME || "D:\\AI\\pa-bailar-media", "public"));
