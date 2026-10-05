"""Start a new video: its folder, a brief, video.json, a composition on the kit and its line in src/Root.tsx.

  .venv/Scripts/python media/tools/new.py <video> [--title "Este finde"] [--duration 12] [--reel]
  → projects/<video>/README.md        the brief to fill in (goal, audience, where, length, deliverables)
    projects/<video>/video.json       version 1, the length, the Story deliverable (+ the Reel with --reel)
    projects/<video>/<Name>.tsx       VideoShell (paper, fade-in, grain; a Story never fades out), a page head
                                      (stripes + period title) and the EndCard under the sticker band
    src/Root.tsx                      the import and the element

A starting point that renders, not a template to fill: replace the page head with the video's own scenes. Names are
lower case with dashes ("este-finde"); the composition ids are <video>-story (and <video>-reel).
"""

import argparse
import json
import re
import shutil

from common import MEDIA

TSX = """// {title}: (one line on what it shows and why). Built from the kit (media/README.md): VideoShell
// (paper, fade-in, grain; a Story never fades out), the beat grid from video.json, the page head, and the EndCard
// under the sticker band. Replace the page head with the video's own scenes.
import React from "react";
import {{ AbsoluteFill, Composition, Folder }} from "remotion";
import {{
  AppIcon,
  assets,
  camera,
  type Cta,
  EndCard,
  FPS,
  gridOf,
  kick,
  PeriodTitle,
  Record,
  sec,
  sp,
  spinAngle,
  SPRING,
  Stripes,
  useScene,
  vertical,
  VideoShell,
}} from "../../src/kit";
import settings from "./video.json";

/** Files in the media home's public/{video}/ (screens, flyers, audio from the tools). */
export const file = assets("{video}");
const DURATION_S = settings.duration;
const {{ BEAT, beats, downbeats }} = gridOf(settings);
const END = sec(DURATION_S - 4); // the end card: the last 4 s
const SPOT = {{ x: 540, y: 820 }}; // the icon and the record

/** `blur` is the kit's render convention (render.py --draft turns it off). */
export const {name}: React.FC<{{ cta: Cta; blur?: boolean }}> = ({{ cta }}) => {{
  const {{ frame, t }} = useScene();
  const cam = camera(t, 0, DURATION_S, {{ zoom: 0.03, driftX: 8, driftY: -10 }});
  const pulse = kick(t, downbeats(0.5, DURATION_S));
  return (
    <VideoShell>
      {{frame < END ? (
        <AbsoluteFill style={{cam(0.6)}}>
          {{/* Low enough that the push-in never lifts it into the sticker band (y < 250). */}}
          <Stripes frame={{frame}} start={{2}} top={{276}} />
          <PeriodTitle
            frame={{frame}}
            start={{8}}
            exitAt={{END - 6}}
            size={{124}}
            top={{322}}
            pulse={{kick(t, [2 * BEAT])}}
          >
            {title}
          </PeriodTitle>
        </AbsoluteFill>
      ) : null}}
      {{frame >= END ? (
        <EndCard
          cta={{cta}}
          frame={{frame}}
          cam={{cam}}
          link={{END + 16}}
          bob={{kick(t, beats((END + 16) / FPS + 0.4, DURATION_S))}}
          stripesAt={{END}}
          name={{{{ at: END + 6, size: 150, step: 1.2, seed: "{video}" }}}}
          spot={{SPOT}}
          signoff={{{{ text: "Nos vemos bailando.", at: END + 22 }}}}
        >
          <AppIcon
            size={{420}}
            style={{{{
              left: SPOT.x - 210,
              top: SPOT.y - 210,
              scale: `${{(0.4 + 0.6 * sp(frame, END, SPRING.pop)) * (1 + 0.03 * pulse)}}`,
            }}}}
          />
          <Record
            size={{360}}
            angle={{spinAngle(t, END / FPS, 0.6)}}
            style={{{{
              position: "absolute",
              left: SPOT.x - 180,
              top: SPOT.y - 180,
              scale: `${{0.3 + 0.7 * sp(frame, END + 2, SPRING.weight)}}`,
            }}}}
          />
        </EndCard>
      ) : null}}
    </VideoShell>
  );
}};

export const {name}Video: React.FC = () => (
  <Folder name="{video}">
{compositions}  </Folder>
);
"""

COMPOSITION = """    <Composition
      id="{video}-{deliverable}"
      component={{{name}}}
      {{...vertical(settings)}}
      defaultProps={{{{ cta: "{cta}" as const, blur: true }}}}
    />
"""

README = """# {title}

Started {{date}} with `tools/new.py`. Fill in the brief before the script.

- **Goal:** what the video should make someone do.
- **Audience:** who sees it, where (Story, Reel), and when it's posted.
- **Length:** {duration:g} s. **Deliverables:** {deliverables}.
- **Material:** real screens (`tools/capture.mjs`), events (`tools/events.py`), voice (`video.json` "voice"), music.
- **Shelf life:** the last day the screens or events are true.

## Make

From the backend root: `.venv/Scripts/python media/tools/make.py {video} --draft`, then `make.py {video}` for the
owner (render, keyframe sheet, sticker-band check, side-by-side with the previous version). Bump `version` in
`video.json` for each cut the owner sees.
"""


def pascal(name: str) -> str:
    return "".join(part.capitalize() for part in name.split("-"))


def register(root: str, video: str, name: str) -> str:
    """src/Root.tsx with the video's import (after the last project import) and element (before the closing `</>`).
    Idempotent: what's there already isn't added again. Raises ValueError when Root.tsx lacks its anchors."""
    line = f'import {{ {name}Video }} from "../projects/{video}/{name}";\n'
    if line not in root:
        imports = list(re.finditer(r'^import .* from "\.\./projects/.*";\n', root, re.MULTILINE))
        at = imports[-1].end() if imports else root.index("\n", root.index('import "./lib/fonts";')) + 1
        root = root[:at] + line + root[at:]
    element = f"<{name}Video />"
    if element not in root:
        close = root.rindex("  </>")
        root = root[:close] + f"    {element}\n" + root[close:]
    return root


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("--title")
    parser.add_argument("--duration", type=float, default=12.0)
    parser.add_argument("--reel", action="store_true", help="also a Reel deliverable (cta: Link en mi perfil)")
    args = parser.parse_args()
    video = args.video
    if not re.fullmatch(r"[a-z][a-z0-9]*(-[a-z0-9]+)*", video):
        raise SystemExit(f"'{video}': lower case letters, digits and dashes (e.g. este-finde)")
    folder = MEDIA / "projects" / video
    if folder.exists():
        raise SystemExit(f"{folder} exists already")
    name = pascal(video)
    title = args.title or video.replace("-", " ").capitalize()
    renders = {"story": f"{video}-story"} | ({"reel": f"{video}-reel"} if args.reel else {})
    settings = {
        "title": f"{title}: (what it is, in a line)",
        "version": "1",
        "fps": 30,
        "duration": args.duration,
        "sticker_band": {"deliverables": ["story"], "allow": []},
        "renders": renders,
    }
    compositions = "".join(
        COMPOSITION.format(video=video, deliverable=d, name=name, cta="reel" if d == "reel" else "story")
        for d in renders
    )
    from datetime import date

    # Root.tsx's new text first (it may lack its anchors): nothing is written until it's known.
    root = MEDIA / "src" / "Root.tsx"
    try:
        registered = register(root.read_text(encoding="utf-8"), video, name)
    except ValueError as error:
        raise SystemExit(f"src/Root.tsx: can't find where to register the video ({error}); nothing written") from None
    readme = README.format(title=title, duration=args.duration, deliverables=", ".join(renders), video=video)
    readme = readme.replace("{date}", date.today().isoformat())
    files = {
        "video.json": json.dumps(settings, indent=2) + "\n",
        f"{name}.tsx": TSX.format(title=title, video=video, name=name, compositions=compositions),
        "README.md": readme,
    }
    try:
        (folder / "data").mkdir(parents=True)
        for file, text in files.items():
            (folder / file).write_text(text, encoding="utf-8", newline="\n")
        root.write_text(registered, encoding="utf-8", newline="\n")
    except OSError:
        shutil.rmtree(folder, ignore_errors=True)  # only the folder made here (it didn't exist): no half a video
        raise
    print(f"projects/{video}/: README.md, video.json, {name}.tsx; src/Root.tsx registers {name}Video")
    print(f"next: write the brief, then node media/tools/stills.mjs {video} --at 1,{args.duration - 1:g}")


if __name__ == "__main__":
    main()
