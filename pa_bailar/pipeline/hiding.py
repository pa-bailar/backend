"""Taking a story or an event off the site by hand (`sweep --hide-story`, `sweep --hide-event`: the admin tools'
"Ocultar historia" and "Ocultar")."""

import logging
from dataclasses import asdict, dataclass

from .. import config, storage, stories
from ..merging import detach_post
from ..models import HiddenEvent, StoredEvent
from .base import SweepBase
from .common import AddPostError

log = logging.getLogger(__name__)


@dataclass
class HiddenFromSite:
    """What hide_event did."""

    event: StoredEvent  # as it was on the site
    already: bool = False  # it was hidden before


@dataclass
class HiddenStory:
    """What hide_story did."""

    story_id: str
    account: str
    removed: list[StoredEvent]  # off the site
    kept: list[StoredEvent]  # still on the site: other posts announce them
    already: bool = False


class Hiding(SweepBase):
    def hide_story(self, story_id: str) -> HiddenStory:
        """Take a story added by hand off the site ("Ocultar historia"): its events lose it, and those only it
        announced disappear (with its flyer). Recorded as `hidden`; sharing the same screenshots again reads it
        again."""
        record = self.processed.get(story_id)
        if not stories.is_story_id(story_id) or record is None:
            raise AddPostError(f"No encontré la historia {story_id}: ¿se agregó hace más de 45 días?")
        if record.outcome == "hidden":
            return HiddenStory(story_id, record.account, [], [], already=True)
        affected = [event for event in self.events if any(media.post_id == story_id for media in event.media)]
        self.events = detach_post(self.events, story_id)
        remaining = {event.id for event in self.events}
        record.outcome = "hidden"
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self._save()
        storage.save_meta(asdict(self.stats))
        log.info("   %s hidden: %s event(s) affected", story_id, len(affected))
        return HiddenStory(
            story_id,
            record.account,
            removed=[event for event in affected if event.id not in remaining],
            kept=[event for event in self.events if event.id in {e.id for e in affected}],
        )

    def hide_event(self, event_id: str) -> HiddenFromSite:
        """Take any event off the site by hand ("Ocultar", e.g. a new workshop series that isn't right), whatever
        it came from (posts, stories). It's kept in state/hidden_events.json: the sweeps never publish it again from
        the same posts (a caption edit, an upgrade) nor from a later post of the same event (merging.matches_hidden);
        a genuinely new event is published as usual. Adding one of its posts by hand (Agregar, Volver a leer)
        publishes it again. Its posts' records lose it (`hidden` when it was all they announced)."""
        if event_id in self.hidden:
            return HiddenFromSite(self.hidden[event_id].event, already=True)
        event = next((item for item in self.events if item.id == event_id), None)
        if event is None:
            raise AddPostError(f"No encontré el evento `{event_id}` en el sitio: ¿ya pasó, o cambió de nombre?")
        self.events.remove(event)
        self.hidden[event_id] = HiddenEvent(hidden_at=config.now_bogota().isoformat(timespec="seconds"), event=event)
        for media in event.media:
            record = self.processed.get(media.post_id)
            if record is None:
                continue
            record.event_ids = [other for other in record.event_ids if other != event_id]
            if not record.event_ids:
                record.outcome, record.provisional = "hidden", False  # no upgrade for nothing
        self.stats.flyers_removed = storage.remove_unused_flyers(self.events)
        self._save()
        storage.save_meta(asdict(self.stats))
        log.info("   %s hidden by hand: %s", event_id, event.title)
        return HiddenFromSite(event)
