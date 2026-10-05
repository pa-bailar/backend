// The site's three faces (Google Fonts, OFL), committed in media/fonts/ and bundled with the code (imports, not
// staticFile: the public folder is the media home, outside the checkout), so renders don't depend on the network.
// Importing this module once (any video's root component does) loads them.
import { loadFont } from "@remotion/fonts";
import { staticFile } from "remotion";
import bodoni from "../../fonts/BodoniModa-Italic[opsz,wght].ttf";
import instrument from "../../fonts/InstrumentSans[wdth,wght].ttf";
import shrikhand from "../../fonts/Shrikhand-Regular.ttf";
import { FONT } from "./tokens";

export const fontsReady = Promise.all([
  loadFont({ family: FONT.display, url: shrikhand, weight: "400" }),
  loadFont({ family: FONT.serif, url: bodoni, style: "italic", weight: "400 900" }),
  loadFont({ family: FONT.sans, url: instrument, weight: "400 700" }),
]);

/** A video's files live in the media home's public/<video>/ (written by the tools): `const file = assets("teaser-v2")`. */
export const assets = (video: string) => (path: string) => staticFile(`${video}/${path}`);
