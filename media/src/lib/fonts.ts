// The site's three faces (Google Fonts, OFL), loaded from public/fonts so renders don't depend on the network.
// Importing this module once (any video's root component does) loads them.
import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";
import { FONT } from "./tokens";

export const fontsReady = Promise.all([
  loadFont({ family: FONT.display, url: staticFile("fonts/Shrikhand-Regular.ttf"), weight: "400" }),
  loadFont({
    family: FONT.serif,
    url: staticFile("fonts/BodoniModa-Italic[opsz,wght].ttf"),
    style: "italic",
    weight: "400 900",
  }),
  loadFont({ family: FONT.sans, url: staticFile("fonts/InstrumentSans[wdth,wght].ttf"), weight: "400 700" }),
]);

/** A video's files live in public/<video>/ (written by the tools): `const file = assets("teaser-v2")`. */
export const assets = (video: string) => (path: string) => staticFile(`${video}/${path}`);
