"""The sweep: fetch recent posts, analyze new ones with Gemini, store one-time events and their flyers.

Per account:
  - A new account gets a deeper first sweep (its last BACKFILL_POSTS posts from the last BACKFILL_DAYS
    days); once all of them are analyzed it joins the regular sweep (last DEFAULT_LOOKBACK_DAYS days).
  - Each new post is triaged by the light model; only posts that announce events are extracted by Flash.
  - Posts extracted provisionally (by a lighter model: Flash was out of quota or busy) are re-extracted with Flash
    when there's budget, after every account and the soonest events first; a Flash paused as busy is waited for
    once a run, time allowing, and what Flash changed in the lighter readings is counted (RunStats.upgrade_changes).
  - Posts that couldn't be analyzed (no quota left today, network errors) stay pending for the next run.
  - A post whose caption was edited since it was analyzed (e.g. the venue added) is analyzed again.
  - After MAX_RUN_MINUTES no new Gemini work starts; the rest waits for the next run.

After all accounts: events whose last day is older than EVENT_RETENTION_DAYS are archived, then every flyer no
event uses is removed.

The admin tools add one post by hand (`add_post`), or a story from its screenshots (`add_story`, stories.py), and
take a story or an event off the site again (`hide_story`, `hide_event`).

One class, `Sweep`, does all of it over one shared state, built from a module per part:
  common.py       run statistics, the clients' protocols, errors, flyers and media records
  base.py         SweepBase: the state, storing one analyzed post, one identity per post
  sweep.py        Sweep: the regular sweep (accounts whose turn it is, their posts, retention)
  manual_post.py  ManualPosts.add_post
  story_admin.py  StoryAdmin.add_story
  hiding.py       Hiding.hide_story and hide_event
"""

from .common import RETRYABLE_ERRORS, AccountStats, AddPostError, Extractor, PostSource, RunStats
from .hiding import HiddenFromSite, HiddenStory
from .manual_post import SETTLED_OUTCOMES, AddedPost
from .story_admin import AddedStory
from .sweep import Sweep, overdue_by_account, unproductive_accounts

__all__ = [
    "RETRYABLE_ERRORS",
    "SETTLED_OUTCOMES",
    "AccountStats",
    "AddPostError",
    "AddedPost",
    "AddedStory",
    "Extractor",
    "HiddenFromSite",
    "HiddenStory",
    "PostSource",
    "RunStats",
    "Sweep",
    "overdue_by_account",
    "unproductive_accounts",
]
