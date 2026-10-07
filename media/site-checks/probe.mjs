// One-off debugging without writing a script: open the site, run actions in order, print the page's state after each
// (one line: lib.mjs snapshot), then the errors. Local only (README.md).
//
//   node media/site-checks/probe.mjs [--live | --url <u>] [--engine chrome|webkit] [--device desktop|phone|iphone]
//     [--size 1100x800] [--theme light|dark] [--now <iso>] [--fresh] [--path /calendario/] --do "<action>" …
//
// Actions: click:<selector>  tap:<selector>  key:<Key>[*n]  type:<text>  scroll:<y> (or +<dy>/-<dy>)  goto:<path>
//   back  forward  reload  wait:<ms>  eval:<js expression>  shot:<name>  snap (the full snapshot as JSON)
// A selector's first match is used; `card:<n>` is the n-th card of the visible view (0-based), `hit:<n>` its link.
import { back, cli, cards, forward, fmt, goto, key, open, shot, snapshot, tapOrClick, waitSettled } from "./lib.mjs";

const args = cli({ do: { type: "string", multiple: true }, path: { type: "string" } });
if (args.help || !args.do?.length) {
  console.log(
    "usage: probe.mjs [--live|--url u] [--engine e] [--device d] [--size WxH] [--theme t] [--now iso] [--fresh] [--path p] --do <action> …",
  );
  console.log("actions: click:<sel> tap:<sel> key:<Key>[*n] type:<text> scroll:<y|+dy|-dy> goto:<path> back forward");
  console.log("         reload wait:<ms> eval:<js> shot:<name> snap   (<sel>: CSS, or card:<n> / hit:<n>)");
  process.exit(args.help ? 0 : 1);
}

const engine = args.engines?.[0] ?? "chrome";
const device = args.devices?.[0] ?? "desktop";
const theme = args.themes?.[0] ?? "light";
const { page, errors, close } = await open({
  engine,
  device,
  theme,
  base: args.base,
  now: args.now,
  fresh: args.fresh,
  size: args.size,
});
const target = (sel) => {
  const m = sel.match(/^(card|hit):(\d+)$/);
  if (!m) return page.locator(sel).first();
  const card = cards(page).nth(Number(m[2]));
  return m[1] === "hit" ? card.locator("a.event-card__hit") : card;
};

let failed = false;
try {
  await goto(page, args.path ?? "/");
  console.log(`${engine}/${device}/${theme} ${args.base}`);
  console.log(`  ${"start".padEnd(24)} ${fmt(await snapshot(page))}`);
  for (const action of args.do) {
    const [, verb, rest = ""] = action.match(/^(\w+)(?::([\s\S]*))?$/) ?? [];
    let out = "";
    try {
      switch (verb) {
        case "click":
          await target(rest).click();
          await waitSettled(page);
          break;
        case "tap":
          await tapOrClick(page, target(rest));
          break;
        case "key": {
          const [k, n] = rest.split("*");
          await key(page, k, Number(n ?? 1));
          break;
        }
        case "type":
          await page.keyboard.type(rest, { delay: 20 });
          await waitSettled(page);
          break;
        case "scroll":
          await page.evaluate((v) => (/^[+-]/.test(v) ? scrollBy(0, Number(v)) : scrollTo(0, Number(v))), rest);
          await waitSettled(page);
          break;
        case "goto":
          await goto(page, rest);
          break;
        case "back":
          await back(page);
          break;
        case "forward":
          await forward(page);
          break;
        case "reload":
          await page.reload({ waitUntil: "load" });
          await waitSettled(page);
          break;
        case "wait":
          await page.waitForTimeout(Number(rest));
          break;
        case "eval":
          out = ` → ${JSON.stringify(await page.evaluate(rest))?.slice(0, 400)}`;
          break;
        case "shot":
          out = ` → ${await shot(page, rest || "probe")}`;
          break;
        case "snap":
          out = ` → ${JSON.stringify(await snapshot(page))}`;
          break;
        default:
          throw new Error(`unknown action "${action}"`);
      }
    } catch (e) {
      failed = true;
      out = ` ERROR ${e.message.split("\n")[0].slice(0, 160)}`;
    }
    const where = page.url().startsWith("http")
      ? fmt(await snapshot(page).catch(() => ({ url: page.url(), y: 0 })))
      : `left: ${page.url()}`;
    console.log(`  ${action.slice(0, 24).padEnd(24)} ${where}${out}`);
  }
} finally {
  console.log(errors.length ? `errors (${errors.length}):\n  ${errors.join("\n  ")}` : "errors: none");
  await close();
}
process.exit(failed ? 1 : 0);
