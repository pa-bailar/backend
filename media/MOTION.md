# Motion

The rules every video starts from, written for teaser v2 (`projects/teaser-v2`) and approved by the owner on
4 October 2026 ("smoothness improved a lot"). Scene numbers below are that teaser's. Break a rule on purpose,
not by default.

The owner on v1: "some of the movements, like when the events are appearing, feel a bit stiff… add a bit more
dynamism". v1 moved everything with one 12-frame bezier "rise", started one thing per beat, held still
between moves, and hard-cut every scene. Each move was correct; together they read as a slide deck. v2 keeps
the site's visual language and its ONE motion system, but makes it physical.

## What the research says

- **Disney's principles carry over to UI and motion graphics**: slow in/out, follow-through and overlapping
  action (the parts of a group don't start and stop together: image first, then title), arcs instead of
  straight lines, secondary action, anticipation, and squash and stretch used lightly to show weight
  ([IxDF, Tremosa, updated Apr 2026](https://ixdf.org/literature/article/ui-animation-how-to-apply-disney-s-12-principles-of-animation-to-ui-design);
  [Dribbble, Disney principles in UI](https://dribbble.com/stories/2020/07/27/disney-principles-of-animation-ui-interactions)).
- **Springs beat fixed curves for entrances**: a spring (mass, damping, stiffness) has momentum and settles
  on its own, with a small overshoot; higher damping removes the bounce, lower mass makes it faster
  ([Motion docs](https://motion.dev/docs/spring); [Remotion `spring()`](https://www.remotion.dev/docs/spring);
  [`measureSpring()`](https://www.remotion.dev/docs/measure-spring)). Google moved Material 3 Expressive
  (2025) from cubic-bezier tweens to springs, in "fast / default / slow" spatial and effects families
  ([M3 motion](https://m3.material.io/styles/motion/overview/how-it-works)).
- **Stagger with overlap**: offsets shorter than the animation itself (0.1–0.2 s) so moves overlap; waiting
  for each to finish is what reads as stiff ([Webflow University on sequencing](https://university.webflow.com/course-lesson/interactions-animations-sequencing-timing)).
- **Camera**: slow push-ins, parallax between clearly separated layers kept subtle so text stays readable,
  whip pans whose motion blur hides the cut, match cuts
  ([getimg.ai, camera moves](https://getimg.ai/blog/7-camera-movements-that-make-ai-video-look-cinematic);
  [journalism.co.uk, in-camera transitions](https://www.journalism.co.uk/5-in-camera-video-transitions-to-make-your-social-content-more-engaging/)).
- **Motion blur**: 180° shutter is the natural look; more samples smooth it
  ([PremiumBeat](https://www.premiumbeat.com/blog/motion-blur-premiere-pro/); [Remotion motion blur](https://www.remotion.dev/docs/motion-blur)).
- **Beat sync**: cut and accent on musical moments, but not on every beat: always the downbeat gets
  predictable ([Filmdaft, editing to the beat](https://filmdaft.com/how-to-edit-video-clips-to-the-beat-of-music-the-easy-way/)).
- **Claude Code + Remotion in 2026**: linear `interpolate()` with no easing reads as robotic; use `spring()`
  for anything with weight, stagger entries by a few frames, overlap scenes instead of cutting
  ([mcp.directory Remotion skill guide, Jun 2026](https://mcp.directory/blog/claude-remotion-skill-guide);
  [mejba.me, Apr 2026](https://www.mejba.me/blog/claude-code-remotion-youtube-motion-graphics);
  [growthexe, Jul 2026](https://growthexe.substack.com/p/everything-claude-code-remotion-can)). A July 2026
  r/ClaudeAI thread on an Opus + Remotion "Apple-style launch video" got "this is just a powerpoint": flat
  timing and no depth are what people notice
  ([snapshot](https://reddit.sentinel-team.org/posts/1ukmxl0/snapshots/2026-07-03T03%3A00%3A16.73148Z)).
  The 2026 write-ups agree the agent executes taste it's given and doesn't invent it, so these rules are
  written down here and implemented once, in `src/lib/motion.ts`.

## The rules v2 applies

1. **Springs, not curves, for things arriving.** The configs, measured (`src/lib/motion.ts`):

   | Spring | mass / damping / stiffness | Overshoot, settle | Used for |
   |---|---|---|---|
   | `snap` | 0.7 / 14 / 170 | ~7%, 13 f | text, titles, UI, the default "rise" |
   | `sheet` | 0.8 / 18 / 200 | ~4%, 13 f | the site's sheet, the menu |
   | `weight` | 1.1 / 12 / 120 | ~14%, ~24 f | flyers landing, the record, the sticker's flight |
   | `pop` | 0.6 / 9 / 180 | ~22%, 19 f | the sticker, the app icon, the highlight frame |
   | `thumb` | 0.9 / 15 / 120 | ~2% | a scroll let go by a thumb |
   | `whip` | 0.6 / 20 / 320 | ~3% | whip pans (`whip()` in `src/lib/transitions.ts`) |

   Exits still use a curve, accelerating out (`Easing.in(cubic)`, 6 frames): things leave faster than they
   arrive.
2. **"Rise" is still the one entrance**, now a `snap` spring with a touch of stretch along the move while it's
   fast (squash and stretch at ≤5%).
3. **Kinetic type follows the voice word by word** (scene 1, the wordmark letter by letter, scene 4), each word
   2–3 frames before it's said, with a small tilt that settles (follow-through).
4. **Irregular staggers**: deterministic jitter of ±1–2 frames (`jit()`), so piles and letters aren't a metronome.
5. **Weight**: flyers are tossed on arcs (x and y on different springs), drop toward the table (scale 1.22 →
   1 with a bounce), their shadow tightening as they land, and each landing nudges the ones below (secondary
   action).
6. **Anticipation before big moves**: the outgoing scene leans 22 px the other way before a whip; the sticker
   squashes before it launches.
7. **Follow-through on stops**: whips, scrolls and the highlight frame overshoot a little and settle back.
8. **Never still**: every scene has a slow camera push-in (3–6%) and drift, with parallax (titles at 0.5–0.6 of
   the camera move, the pile at 1.25); the record keeps spinning (and spins *up* like a platter when it
   appears); the sticker sways on the beat.
9. **Beat accents on downbeats only, one element at a time**: "este finde?" (2.45 s), the record (4.90), the
   period title (7.35, 9.80, 12.24), the icon (19.59); the arrow bobs on every beat at the end.
10. **Motivated transitions instead of hard cuts**: an iris out of the record's spot (1→2), a vertical whip pan
    (2→3), the list and the detail as ONE continuous phone shot (v1 cut between them), a horizontal whip
    (3→4), a match cut from the round "Gratis" sticker to the spinning record (4→5).
11. **Motion blur on fast moves only** (tosses, whips, the sticker's flight, the flicks): the frame is rendered
    at 8–16 moments across a 180° shutter and averaged with normal blending. `@remotion/motion-blur` was tried
    first: `HtmlInCanvasMotionBlur` adds samples with "lighter" blending, which lifted the paper ~8 levels
    (8-bit) on every blurred frame (a visible flicker) and blacked out the background on one scroll frame, so
    the `Shutter` (`src/lib/blur.tsx`) does the same averaging with `<Freeze>` and opacity 1/(i+1). The scroll's
    blur is done inside the phone the same way (only the list image is resampled). Full render: ~1 min.
12. **Stories: fade in, no fade-out (the owner, 5 Oct 2026).** The first frames ease in from the paper (8 frames); the last frame holds on the end card, with
    the arrow still bobbing, so the Story loops into the next one without a dip to blank.
13. **A real thumb** (the bar's hiding below is how the site worked until 4 October 2026; it no longer hides): a touch disc that arrives on an arc, presses (shrinks, a ring ripples), drags while
    pressed, lifts; the list glides after each flick and settles a hair past the stop; the site's sticky bar
    hides while scrolling down and comes back on the settle, as on the site.
