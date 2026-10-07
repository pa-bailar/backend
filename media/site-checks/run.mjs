// The site checks (README.md): scenarios in scenarios/*.mjs, each run on every engine × device × theme asked for, one
// after the other. Prints one line per run and only the failures; --verbose prints every step. Exit code 1 on any
// failure. Local only: never in GitHub Actions (the owner, 6 Oct 2026).
//
//   node media/site-checks/run.mjs [scenario…|all] [--live | --url <u>] [--engine chrome,webkit]
//     [--device desktop,phone,iphone] [--size 1100x800] [--theme light,dark] [--now <iso>] [--fresh] [--shots]
//     [--verbose]
//
// Defaults: the local preview (http://localhost:4322/), chrome, each scenario's own devices, light.
import { readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import * as lib from "./lib.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const RUN_TIMEOUT = 240_000; // a whole run; each step has lib.STEP_TIMEOUT

const scenarios = [];
for (const file of (await readdir(path.join(HERE, "scenarios"))).filter((f) => f.endsWith(".mjs")).sort()) {
  scenarios.push((await import(pathToFileURL(path.join(HERE, "scenarios", file)).href)).default);
}

const args = lib.cli();
if (args.help) {
  console.log(
    "usage: run.mjs [scenario…|all] [--live|--url u] [--engine e,…] [--device d,…] [--size WxH] [--theme t,…] [--now iso] [--fresh] [--shots] [--verbose]",
  );
  for (const s of scenarios) console.log(`  ${s.name.padEnd(12)} [${s.devices.join(",")}] ${s.summary}`);
  process.exit(0);
}
const names = args.positionals.flatMap((n) => n.split(",")).filter((n) => n && n !== "all");
const unknown = names.filter((n) => !scenarios.some((s) => s.name === n));
if (unknown.length) {
  console.error(`unknown scenario: ${unknown.join(", ")} (have: ${scenarios.map((s) => s.name).join(", ")})`);
  process.exit(2);
}

let failed = 0;
let runs = 0;
for (const scenario of scenarios.filter((s) => !names.length || names.includes(s.name))) {
  for (const engine of args.engines ?? ["chrome"]) {
    for (const device of args.devices ?? scenario.devices) {
      for (const theme of args.themes ?? ["light"]) {
        runs++;
        const label = `${scenario.name} ${engine}/${device}/${theme}`;
        if (args.verbose) console.log(`== ${label}`);
        const r = lib.recorder({ echo: args.verbose });
        let session;
        let skipped = null;
        let timer;
        try {
          session = await lib.open({
            engine,
            device,
            theme,
            base: args.base,
            now: args.now,
            size: args.size,
            fresh: args.fresh,
          });
          const { page } = session;
          const ctx = {
            page,
            engine,
            device,
            theme,
            base: args.base,
            errors: session.errors,
            touch: lib.isTouch(page),
            check: r.check,
            skip: r.skip,
            log: r.log,
            snap: () => lib.snapshot(page),
            /** The snapshot, logged under `label`. */
            step: async (label) => {
              const s = await lib.snapshot(page);
              r.log(label, s);
              return s;
            },
            goto: (where) => lib.goto(page, where),
            tap: (target) => lib.tapOrClick(page, target),
            key: (k, n) => lib.key(page, k, n),
            back: () => lib.back(page),
            forward: () => lib.forward(page),
            settle: (max) => lib.waitSettled(page, max),
            cards: () => lib.cards(page),
            shot: (name) =>
              args.shots ? lib.shot(page, `${scenario.name}-${engine}-${device}-${theme}-${name}`) : null,
          };
          await Promise.race([
            scenario.run(ctx),
            new Promise((_, reject) => {
              timer = setTimeout(() => reject(new Error(`timed out after ${RUN_TIMEOUT / 1000} s`)), RUN_TIMEOUT);
            }),
          ]);
          r.check("no page errors", session.errors.length === 0, session.errors.join(" | "));
        } catch (e) {
          if (e instanceof lib.Skip) skipped = e.message;
          else {
            r.check("ran to the end", false, `${e.message.split("\n")[0]}`);
            if (session?.errors.length) r.check("no page errors", false, session.errors.join(" | "));
          }
        } finally {
          clearTimeout(timer);
          await session?.close();
        }
        const { checks, fails, skips } = r.result;
        const skipNote = skips.length ? ` (skipped: ${skips.join("; ")})` : "";
        if (skipped) console.log(`SKIP ${label}: ${skipped}`);
        else if (fails.length) {
          failed++;
          console.log(`FAIL ${label} ${fails.length}/${checks} checks${skipNote}`);
          for (const f of fails) console.log(`  ${f}`);
        } else console.log(`OK   ${label} ${checks} checks${skipNote}`);
      }
    }
  }
}
console.log(`${runs} runs, ${failed} failed (${args.base})`);
process.exit(failed ? 1 : 0);
