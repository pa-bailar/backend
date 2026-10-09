---
name: media-clean
description: Clean up Pa' Bailar's video working files (old renders, drafts, stills, sheets, comparisons, voice auditions, takes and music downloads no video uses) with media/tools/clean.py, to the Recycle Bin. Use it whenever the owner approves a cut, a voice or a track, at the end of any video session, and when the owner asks to clean up media.
---

# Clean up media

Every video session leaves versions behind: renders of each cut, keyframe sheets, comparisons, stills, voice
auditions and takes, music downloads that weren't picked. The owner doesn't want them left there (8 Oct 2026: "you
create several versions of voice or video, and then just leave them there"). This is the closing step of every video
session (the `teaser` skill's last step), not an occasional chore.

## When

- The owner approved a cut (keep it; earlier cuts go), a voice take (the auditions and other takes go) or a track (the
  other downloads go).
- A video session ends, whatever state it's in.
- The owner asks.

## How

1. **Archive what was posted first.** When a version was posted, copy its renders and `public/<video>/` into the
   media home's `archive/<video>/v<version>/` (the `teaser` skill, rule 5): the cleaner never touches `archive/`.
2. **List:** `.venv/Scripts/python media/tools/clean.py` (from the backend root). It looks at:
   - the media home's `out/`: older versions of each deliverable, drafts, keyframe sheets, comparisons, scratch
     folders (`stills…/`, `music-…/`, `auditions/`, the stills bundles), the mix's intermediate WAVs, orphaned
     `-unversioned-` cuts and logs;
   - the media home's `public/<video>/`: the stray `.flyers-<pid>` folders a stopped `events.py` left (never a
     `.flyers-old-<pid>`: a failed swap parks the video's current flyers there);
   - the media home's `cache/tts` and `cache/music`: takes and tracks no `projects/*/video.json` uses (its lines, its
     one take, its bed). In use means any video.json of this checkout, of every other worktree and of every local
     branch (the home is shared). While one of them can't be read, the cache isn't listed at all and a warning names
     the file: fix it (or finish the edit) and list again;
   - old copies in the checkout and the first teaser project.
3. **Read the list before recycling.** Nothing in use may be on it: each deliverable's latest render, the take a video
   uses (an approved audition must be in the cache under the video's key first: `media/AUDIO.md`, rule 9), the bed.
   If something in use is listed, fix the tool, not the list.
4. **Recycle:** `clean.py --yes` moves them to the Recycle Bin (restorable; never deleted for good: items a bin
   can't hold are skipped with a message).
5. **What the cleaner can't know:** a deliverable the owner dropped (the puente teaser's Reel, once "this won't be a
   reel") keeps its last render: recycle it by hand (the same Recycle Bin, never a delete). A video that's done
   (posted and past its shelf life, or dropped) goes whole with `clean.py --retire <video>` then `--yes`: its `out/`,
   `public/` and `archive/` in the media home, and the takes and music only it uses; the project stays in git. The
   owner retired teaser-v2 and este-finde on 8 Oct 2026: once a video is past its shelf life, offer to retire it.
6. **Report** in one line: how many items and MB went to the Recycle Bin, and what stays (the latest renders, by name).
