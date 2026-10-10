"""Batched extraction in the sweep (config.EXTRACTION_BATCH_POSTS over 1; off by default, the owner, 9 Oct 2026).

The posts of one account that need an extraction (the triage passed them, or an edited post that had events) wait
in a batch after their triage, and are read together in one request (batching.py) when the batch is full, when the
next post's images wouldn't fit (config.EXTRACTION_BATCH_MAX_IMAGES), or when the account's posts are done. Each
post's answer is stored as a one-post reading would be: its own images and flyers, its record, the model that read it
and whether it's provisional. The safeguards: a post the answer leaves out (no answer for it, two, or an event citing
another post's image: batching.split_answer), and every post of a batch no model could read now, that Gemini refused
or that ran out of quota, is read again alone through the one-post path (`_extract_and_store`), with its own
fallbacks (the provisional models, the last resort) and its own errors: never dropped, and a post Gemini refuses is
recorded as rejected alone, not with its batch.
"""

import logging
from datetime import datetime

from .. import config
from ..batching import BatchItem, BatchReading
from ..gemini import QuotaExhaustedError
from ..instagram import Post
from .base import SweepBase
from .common import RETRYABLE_ERRORS

log = logging.getLogger(__name__)


class Batches(SweepBase):
    """The sweep's batch of posts waiting for a shared extraction request, per account."""

    _batch: list[BatchItem]

    def _extract_and_store(self, account: str, post: Post, published: datetime, images: list[bytes]) -> bool:
        """One post's extraction (Sweep's): False when it must be retried next run."""
        raise NotImplementedError

    def _out_of_time(self) -> bool:
        """Whether the run's time budget is used (Sweep's)."""
        raise NotImplementedError

    @staticmethod
    def _batching() -> bool:
        return config.EXTRACTION_BATCH_POSTS > 1

    def _queue_extraction(self, account: str, item: BatchItem) -> None:
        """Add a post to the account's batch, reading the batch first if the post's images wouldn't fit, and after
        if it's full."""
        images = sum(len(queued.images) for queued in self._batch)
        if self._batch and images + len(item.images) > config.EXTRACTION_BATCH_MAX_IMAGES:
            self._read_batch(account)
        self._batch.append(item)
        if len(self._batch) >= config.EXTRACTION_BATCH_POSTS:
            self._read_batch(account)

    def _read_batch(self, account: str) -> None:
        """Read the posts waiting in the batch, in one request, and store each; a post alone goes the one-post way."""
        items, self._batch = self._batch, []
        if len(items) == 1:
            self._counted(account, items[0], self._extract_and_store(account, *self._one(items[0])))
            return
        if not items:
            return
        if self._out_of_time():  # no request starts: they wait, as a post would
            for _ in items:
                self.stats.count(account, "pending")
            return
        reading = self._shared_reading(account, items)
        for index, item in enumerate(items):
            analysis = reading.analyses.get(index) if reading else None
            if reading is None or analysis is None:
                if reading is not None:
                    log.info("     %s read again alone: %s", item.post["permalink"], reading.left_out[index])
                self.stats.batch_rereads += 1
                stored = self._extract_and_store(account, *self._one(item))
            else:
                log.info("   %s (one request with %d posts)", item.post["permalink"], len(items))
                self.stats.batched_posts += 1
                stored = self._store_analysis(
                    account, item.post, item.images, analysis, reading.model, reading.provisional
                )
            self._counted(account, item, stored)

    def _shared_reading(self, account: str, items: list[BatchItem]) -> BatchReading | None:
        """The batch's request: its reading, or None when no model could give one (each post is then read alone)."""
        known = self._known_events(account, min(item.published for item in items))
        log.info("   reading %d posts in one request", len(items))
        try:
            reading = self.extractor.extract_batch(account, items, known)
        except QuotaExhaustedError as error:  # nothing was spent: alone, each may wait or reach the last resort
            log.info("     no quota for the shared request (%s): each post read alone", error)
            return None
        except RETRYABLE_ERRORS as error:  # busy, refused, unreadable: alone, each gets its own answer or error
            log.info("     the shared request failed (%s): each post read alone", error)
            return None
        self.stats.batch_requests += 1
        return reading

    @staticmethod
    def _one(item: BatchItem) -> tuple[Post, datetime, list[bytes]]:
        return item.post, item.published, item.images

    def _counted(self, account: str, item: BatchItem, stored: bool) -> None:
        """A post of a batch, read: pending when it must be retried next run, re-analyzed when it was read before."""
        if not stored:
            self.stats.count(account, "pending")
        elif item.reread:
            self.stats.reanalyzed += 1
