"""Sweep: the regular sweep (the accounts whose turn it is, their new and edited posts, retention, the run's
statistics), with the admin tools' operations mixed in (manual_post.py, story_admin.py, hiding.py)."""

import logging
import time
from dataclasses import asdict
from datetime import UTC, date, datetime, timedelta

from .. import config, links, storage
from ..account_options import AccountOptions, mentions_focus
from ..external import is_external
from ..gemini import GeminiKeyError, OutOfTimeError, QuotaExhaustedError, RejectedRequestError, UnreadableAnswerError
from ..instagram import InstagramError, Post, is_rate_limited, published_at, slide_count
from ..models import AccountState, ProcessedPost
from . import common
from .common import RETRYABLE_ERRORS, RunStats, caption_hash, clip_for, flyer_slide
from .hiding import Hiding
from .manual_post import ManualPosts
from .story_admin import StoryAdmin

log = logging.getLogger(__name__)


def hours_overdue(state: AccountState | None, now: datetime) -> float:
    """How long past its turn an account is (negative: not its turn yet). Never read: always due."""
    if state is None or state.last_swept_at is None:
        return float("inf")
    silent = (now.date() - date.fromisoformat(state.latest_post)).days if state.latest_post else 0
    if silent >= config.DORMANT_AFTER_DAYS:
        every = config.DORMANT_SWEEP_EVERY_HOURS
    elif silent >= config.QUIET_AFTER_DAYS:
        every = config.QUIET_SWEEP_EVERY_HOURS
    else:
        every = config.SWEEP_EVERY_HOURS
    return (now - datetime.fromisoformat(state.last_swept_at)).total_seconds() / 3600 - every


class Sweep(ManualPosts, StoryAdmin, Hiding):
    """The sweep (`run`) and the admin tools' operations (`add_post`, `add_story`, `hide_story`, `hide_event`), over
    one shared state (SweepBase)."""

    def run(self) -> RunStats:
        try:
            username = self.instagram.check_token()
        except InstagramError as error:
            raise SystemExit(
                f"Instagram token invalid ({error}). Generate a new one, run `python -m pa_bailar refresh-token` "
                "and update META_ACCESS_TOKEN (.env and the GitHub secret)."
            ) from error
        log.info("Instagram token OK (@%s)", username)

        due = self._due_accounts()
        self.stats.due_accounts = due
        share = self._share_per_run()
        if len(due) > share:
            log.info("%s accounts' turn: %s this run, the rest first next run", len(due), share)
        for account in due[:share]:
            usage = getattr(self.instagram, "app_usage_percent", 0)
            if usage >= config.INSTAGRAM_USAGE_STOP:
                log.warning("Instagram quota %s%% used: the remaining accounts wait for the next run", usage)
                self.rate_limited = True
                break
            if self.rate_limited:
                log.warning("Instagram rate limit reached: the remaining accounts wait for the next run")
                break
            if self._out_of_time():  # no Gemini work would start: they wait, first next run (_due_accounts)
                break
            self.stats.accounts += 1
            try:
                self._process_account(account)
            except GeminiKeyError as error:  # every post would fail: stop, and let the run fail loudly
                raise SystemExit(
                    f"Gemini API key doesn't work ({error}). Create a new key in Google AI Studio and update "
                    "GEMINI_API_KEY (.env and the GitHub secret)."
                ) from error
            except Exception:  # unexpected (e.g. a malformed answer): lose this account's run, not everyone's
                log.exception("   unexpected error with @%s, continuing with the next account", account)
                self.stats.count(account, "errors")

        self._apply_retention()
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self.stats.gemini_requests = self.extractor.requests_this_run()
        self.stats.models_unavailable = self.extractor.models_unavailable()
        self.stats.external = self.extractor.external_report()
        self.stats.rate_limited = self.rate_limited
        self.stats.instagram_usage = getattr(self.instagram, "app_usage_percent", 0)
        self.stats.out_of_time = self.time_up_logged
        storage.save_account_state(self.accounts)
        storage.save_meta(asdict(self.stats))
        return self.stats

    def _share_per_run(self) -> int:
        """How many accounts one sweep reads: its share of the day's sweeps, plus a margin for late ones."""
        if self.all_accounts:
            return len(storage.read_accounts())
        runs_per_day = max(1, len(config.SWEEP_TIMES))
        return -(-len(storage.read_accounts()) // runs_per_day) + config.EXTRA_ACCOUNTS_PER_RUN

    def _hours_overdue(self, account: str, now: datetime) -> float:
        return hours_overdue(self.accounts.get(account), now)

    def _due_accounts(self) -> list[str]:
        """The accounts whose turn it is, in reading order: accounts in their regular sweep before new ones (a
        new account's first, deeper sweep can take days of quota), and within each, those that waited longest
        first. So an account a sweep didn't reach (its share, Instagram's limit) is first next time."""
        now = config.now_bogota()
        followed = storage.read_accounts()
        due = followed if self.all_accounts else [a for a in followed if self._hours_overdue(a, now) >= 0]

        def is_new(account: str) -> bool:
            state = self.accounts.get(account)
            return state is None or not state.backfill_done

        return sorted(due, key=lambda account: (is_new(account), -self._hours_overdue(account, now)))

    def _apply_retention(self) -> None:
        """Archive long-past events (storage.archive_events) and forget old analyzed posts, so the site's data and
        flyers don't grow forever. Their full flyers and clips go with the unused ones (remove_unused_flyers)."""
        now = config.now_bogota()
        oldest_date = (now - timedelta(days=config.EVENT_RETENTION_DAYS)).date().isoformat()
        kept = [event for event in self.events if not event.last_day or event.last_day >= oldest_date]
        expired = [event for event in self.events if event not in kept]
        self.stats.events_expired = storage.archive_events(expired) if expired else 0
        self.events = kept
        past = [key for key, item in self.hidden.items() if (item.event.last_day or "") < oldest_date]
        for key in past:  # long past: no post of it will be read again
            del self.hidden[key]

        # Never forget a post the lookback could still fetch (e.g. a manual run with --days 60).
        keep_days = max(config.PROCESSED_RETENTION_DAYS, self.lookback.days + 1)
        oldest_record = now - timedelta(days=keep_days)
        old = [pid for pid, rec in self.processed.items() if datetime.fromisoformat(rec.processed_at) < oldest_record]
        for post_id in old:
            del self.processed[post_id]
        self.stats.processed_forgotten = len(old)

        if self.stats.events_expired or old or past:
            log.info(
                "Retention: %s past events archived, %s old post records forgotten", self.stats.events_expired, len(old)
            )
            self._save()

    # ---------- per account ----------

    def _process_account(self, account: str) -> None:
        state = self.accounts.setdefault(account, AccountState(first_seen=config.now_bogota().date().isoformat()))
        if self._is_bar(account) and not state.backfill_done:
            state.backfill_done = True  # a bar's old posts are past nights: no deeper first sweep (account_options)
        backfill = not state.backfill_done
        account_stats = self.stats.account(account)
        account_stats.backfill = backfill
        log.info("== @%s%s", account, " (new account: deeper first sweep)" if backfill else "")

        posts = self._fetch_posts(account, state, backfill)
        if posts is None:
            return
        if posts:
            account_stats.latest_post = config.bogota_date(max(published_at(p) for p in posts)).isoformat()
            state.latest_post = account_stats.latest_post
        window = timedelta(days=config.BACKFILL_DAYS) if backfill else self.lookback
        cutoff = datetime.now(UTC) - window
        # Oldest first, so a flyer is usually stored before the video or reminder that follows it.
        for post in sorted(posts, key=lambda p: p["timestamp"]):
            published = published_at(post)
            if published >= cutoff:
                self._read_post(account, post, published)
        fetched = {post["id"] for post in posts}  # a post no longer fetched is never read again
        state.unreadable = {post_id: runs for post_id, runs in state.unreadable.items() if post_id in fetched}

        self._complete_media(posts)
        # Read: its turn is over, unless posts wait (Gemini's quota, time): then it's due again next run.
        if account_stats.pending == 0:
            state.last_swept_at = config.now_bogota().isoformat(timespec="seconds")
        if backfill and account_stats.pending == 0:
            state.backfill_done = True
            log.info("   first sweep complete: from now on, regular sweep")
        storage.save_account_state(self.accounts)

    def _fetch_posts(self, account: str, state: AccountState, backfill: bool) -> list[Post] | None:
        """The account's latest posts (more for its first, deeper sweep). None when Instagram couldn't give them:
        its turn is over, unless Instagram's rate limit stopped it."""
        try:
            limit = config.BACKFILL_POSTS if backfill else config.POSTS_PER_ACCOUNT
            return self.instagram.fetch_recent_posts(account, limit=limit)
        except InstagramError as error:
            log.error("   could not fetch posts: %s", error)
            self.rate_limited = is_rate_limited(error)
            if not self.rate_limited:
                state.last_swept_at = config.now_bogota().isoformat(timespec="seconds")  # tried: its turn is over
            self.stats.count(account, "errors")
            self.stats.account(account).fetch_failed = True
            return None

    def _read_post(self, account: str, post: Post, published: datetime) -> None:
        """One post within the window: analyzed if it's new, again if its caption was edited, with Flash if it was
        read provisionally; nothing if it's known and unchanged."""
        record = self.processed.get(post["id"]) or self._adopt_public_record(post)
        post_hash = caption_hash(post)
        if record is None:
            log.info("   %s %-14s %s", f"{published:%Y-%m-%d}", post["media_type"], post["permalink"])
            if self._out_of_time() or not self._analyze_new_post(account, post, published):
                self.stats.count(account, "pending")
        elif record.caption_hash is None:
            record.caption_hash = post_hash  # analyzed before captions were fingerprinted
            self._save()
        elif record.caption_hash != post_hash:
            if self._out_of_time():
                self.stats.count(account, "pending")  # still edited next run: the account stays due, read then
                return
            log.info("   %s caption edited, analyzing again %s", f"{published:%Y-%m-%d}", post["permalink"])
            # A post that had events skips the filter: the extraction decides again, and takes its old
            # events off the site if it no longer announces them ("CANCELADO"). Others go through the
            # filter as usual (Flash-Lite), keeping Flash's small quota for events.
            # Records from before outcomes were kept (outcome None) had events if Gemini said so.
            had_events = record.outcome in ("event", "merged") or (record.outcome is None and record.is_event_post)
            if self._analyze_new_post(account, post, published, triage=not had_events):
                self.stats.reanalyzed += 1
            else:  # no quota or time left, or an error: the account stays due, so the edit ("CANCELADO") is read soon
                self.stats.count(account, "pending")
        elif record.provisional and self.extractor.can_upgrade() and not self._out_of_time():
            log.info("   %s upgrading provisional analysis %s", f"{published:%Y-%m-%d}", post["permalink"])
            self._upgrade_post(account, post, published)

    def _adopt_public_record(self, post: Post) -> ProcessedPost | None:
        """A post added by hand from its public page, now among the account's posts: the same post, not a new
        one (no second Gemini request). It's analyzed again only if its caption changed since."""
        code = links.post_code(post["permalink"])
        known_id = self._record_id(code, public_only=True) if code else None
        if known_id is None:
            return None
        self._rename_post(known_id, post["id"])
        record = self.processed[post["id"]]
        if self._same_caption(post):
            record.caption_hash = caption_hash(post)  # the API's spacing from now on
        return record

    def _complete_media(self, posts: list[Post]) -> None:
        """Add what posts stored before clips and slide counts existed are missing, from their fresh copy
        (Instagram's video links expire, so only posts just fetched can get a clip)."""
        by_id = {post["id"]: post for post in posts}
        changed = False
        for event in self.events:
            for media in event.media:
                post = by_id.get(media.post_id)
                if post is None:
                    continue
                if media.slides is None and (slides := slide_count(post)):
                    media.slides, changed = slides, True
                needs_clip = media.preview is None and media.flyer and media.media_type != "IMAGE"
                if needs_clip and media.flyer and (preview := clip_for(post, flyer_slide(media.flyer))):
                    media.preview, changed = preview, True
        if changed:
            self._save()

    def _out_of_time(self) -> bool:
        """True once the run has used its time budget (MAX_RUN_MINUTES): start no more Gemini work."""
        over = time.monotonic() - self.started >= config.MAX_RUN_MINUTES * 60
        if over and not self.time_up_logged:
            log.warning("Run time budget used (%s min): the rest waits for the next run", config.MAX_RUN_MINUTES)
            self.time_up_logged = True
        return over

    # ---------- per post ----------

    def _analyze_new_post(self, account: str, post: Post, published: datetime, triage: bool = True) -> bool:
        """Triage, then extract if it's an event (`triage=False`: extract directly). False when the post must be
        retried next run."""
        # A post that had events (triage=False) is read again whatever its caption says now ("CANCELADO").
        if triage and self._outside_focus(account, post):
            return True
        if not self.extractor.can_analyze():
            return False  # no quota left today: it waits (no download, not an error)
        try:
            images = common.download_images(post)  # through the module: tests replace it
        except OSError as error:
            return self._retry_later(account, f"could not download images: {error}")

        verdict, triage_model = None, None
        if triage:
            try:
                verdict, triage_model = self.extractor.triage(
                    account, post, published, images, rules=self._rules(account, post["id"])
                )
            except QuotaExhaustedError as error:
                if isinstance(error, OutOfTimeError) or self.extractor.can_extract_with_flash():
                    # Flash-Lite out of today's quota: wait for it rather than spend Flash's small one on every post.
                    log.info("     waits for the next run (triage): %s", error)
                    return False
                # Flash is out too, so the extraction is the last resort's: it decides alone. Never a last-resort
                # triage: its "no" would be final, and Groq's tokens a minute don't fit a triage and an extraction.
                log.info("     Flash-Lite and Flash out of quota: extracting directly (the last resort)")
            except RETRYABLE_ERRORS as error:
                # Triage unavailable: let the extraction decide on its own.
                log.info("     triage unavailable (%s), extracting directly", error)

        if verdict is not None and not verdict.is_event_post:
            self._record_not_event(account, post, verdict.reason, triage_model or "-")
            return True
        return self._extract_and_store(account, post, published, images)

    def _extract_and_store(self, account: str, post: Post, published: datetime, images: list[bytes]) -> bool:
        """Extract a post's events and store them. False when it must be retried next run."""
        try:
            known = self._known_events(account, published)
            analysis, model, provisional = self.extractor.extract(
                account, post, published, images, known, rules=self._rules(account, post["id"])
            )
        except RejectedRequestError as error:
            # Gemini refuses this post itself (e.g. an image it can't read, an answer too long): retrying would spend
            # quota on every run and keep a new account's first sweep from ever finishing. Record it and move on.
            log.warning("     Gemini rejected the post, skipping it: %s", error)
            return self._record_rejected(account, post, f"rechazado por Gemini: {error}")
        except QuotaExhaustedError as error:
            log.info("     waits for the next run: %s", error)
            return False
        except UnreadableAnswerError as error:
            runs = self._unreadable_run(account, post["id"])
            if runs < config.UNREADABLE_RUNS:
                return self._retry_later(account, f"{error} (run {runs} of {config.UNREADABLE_RUNS})")
            log.warning("     no valid answer on %s runs, giving the post up: %s", runs, error)
            reason = f"rechazado: Gemini no dio una respuesta válida en {runs} corridas"
            return self._record_rejected(account, post, reason)
        except RETRYABLE_ERRORS as error:
            return self._retry_later(account, str(error))

        return self._store_analysis(account, post, images, analysis, model, provisional)

    def _record_rejected(self, account: str, post: Post, reason: str) -> bool:
        """A post Gemini can't read, recorded so it isn't retried (an error of the run, not pending)."""
        self.stats.count(account, "errors")
        self._record_processed(account, post, False, reason, "-", provisional=False)
        self._set_outcome(post, "rejected")
        self._save()
        return True

    def _unreadable_run(self, account: str, post_id: str) -> int:
        """Count one more run on which no model gave valid JSON for this post: how many so far (config.UNREADABLE_RUNS
        gives it up). Kept in the account's state (AccountState.unreadable), cleared once the post is recorded."""
        state = self.accounts.setdefault(account, AccountState(first_seen=config.now_bogota().date().isoformat()))
        state.unreadable[post_id] = state.unreadable.get(post_id, 0) + 1
        storage.save_account_state(self.accounts)
        return state.unreadable[post_id]

    def _outside_focus(self, account: str, post: Post) -> bool:
        """An account limited to some styles (accounts.txt `solo:`, account_options): a post whose caption names
        none of them is recorded as no event before any Gemini request (free). Read again if its caption is edited;
        a post added by hand isn't filtered."""
        focus = self.options.get(account, AccountOptions()).focus
        if self._by_hand(post["id"]) or mentions_focus(post.get("caption"), focus):
            return False
        reason = f"no menciona {' ni '.join(focus)} (la cuenta es solo para esos estilos)"
        self._record_not_event(account, post, reason, "-")
        return True

    def _upgrade_post(self, account: str, post: Post, published: datetime) -> None:
        """Re-extract a provisional post with Flash; keep the provisional result if that fails. A post the last
        resort read without a triage (Flash-Lite was out) and found no event in goes through the triage first, as a
        new post would: Flash is spent on it only if Flash-Lite says it's an event."""
        record = self.processed[post["id"]]
        try:
            images = common.download_images(post)
            if record.outcome == "not_event" and is_external(record.model):
                verdict, triage_model = self.extractor.triage(
                    account, post, published, images, rules=self._rules(account, post["id"])
                )
                if not verdict.is_event_post:
                    self._record_processed(account, post, False, verdict.reason, triage_model, provisional=False)
                    self._set_outcome(post, "not_event")
                    self._save()
                    self.stats.upgraded += 1
                    log.info("     not an event (triage): %s", verdict.reason)
                    return
            known = self._known_events(account, published)
            analysis, model, _ = self.extractor.extract(
                account, post, published, images, known, allow_provisional=False, rules=self._rules(account, post["id"])
            )
        except RejectedRequestError as error:
            log.warning("     Gemini rejected the upgrade, keeping the provisional analysis: %s", error)
            self.processed[post["id"]].provisional = False  # stop retrying it
            self._save()
            return
        except UnreadableAnswerError as error:
            if (runs := self._unreadable_run(account, post["id"])) < config.UNREADABLE_RUNS:
                log.info("     upgrade postponed (run %s of %s): %s", runs, config.UNREADABLE_RUNS, error)
                return
            log.warning("     no valid answer on %s runs, keeping the provisional analysis: %s", runs, error)
            self.processed[post["id"]].provisional = False  # stop spending Flash's quota on it
            self.accounts[account].unreadable.pop(post["id"], None)
            self._save()
            return
        except RETRYABLE_ERRORS as error:
            log.info("     upgrade postponed: %s", error)
            return
        if self._store_analysis(account, post, images, analysis, model, provisional=False, count_as_new=False):
            self.stats.upgraded += 1
