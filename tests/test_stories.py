"""Stories from screenshots (stories.py, Sweep.add_story / hide_story): ids and hashes, when a screenshot was
taken, dates worked out in code, crops, the account, and the whole flow with fake Instagram and Gemini."""

import io
import json
from datetime import date, datetime, timedelta

import pytest
from PIL import Image, ImageDraw

from pa_bailar import config, storage, stories
from pa_bailar.commands.sweep import added_story_markdown, hidden_story_markdown, load_screenshots
from pa_bailar.gemini import QuotaExhaustedError
from pa_bailar.instagram import InstagramError
from pa_bailar.merging import ordered_media
from pa_bailar.models import StoryAnalysis, StoryEvent, StoryImage
from pa_bailar.pipeline import AddPostError, Sweep
from pa_bailar.stories import Screenshot
from tests.factories import DETAILS, media, stored

BOGOTA = config.BOGOTA_TZ


def screenshot(seed: int = 1, header: str = "salsa.club 5 h", size: tuple[int, int] = (1080, 2280)) -> bytes:
    """A phone screenshot: a header, a flyer with shapes that depend on `seed`, a reply bar."""
    width, height = size
    picture = Image.new("RGB", size, (20, 20, 20))
    draw = ImageDraw.Draw(picture)
    draw.text((40, 30), header, fill="white")
    draw.rectangle((60, 300, width - 60, height - 300), fill=(200, 50 + seed * 20 % 200, 30))
    for step in range(6):
        x = (seed * 97 + step * 151) % (width - 300) + 60
        y = (seed * 53 + step * 233) % (height - 900) + 400
        draw.ellipse((x, y, x + 220, y + 160), fill=((seed * 40 + step * 30) % 255, 240, (step * 70) % 255))
    draw.rectangle((0, height - 160, width, height), fill=(40, 40, 40))
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG", quality=90)
    return buffer.getvalue()


def story_event(**fields) -> StoryEvent:
    base = {key: value for key, value in DETAILS.items() if key not in ("date", "end_date", "weekday", "is_recurring")}
    defaults = {
        "is_recurring": False,
        "weekly": False,
        "date_text": None,
        "day": None,
        "month": None,
        "year": None,
        "end_day": None,
        "end_month": None,
        "weekday": None,
        "relative_day": None,
        "image_index": 0,
        "same_as": None,
    }
    return StoryEvent(**(base | defaults | fields))


# ---------- ids and hashes ----------


def test_story_id_is_the_same_for_the_same_screenshots_in_any_order():
    a, b = screenshot(1), screenshot(2)
    assert stories.story_id([a, b]) == stories.story_id([b, a])
    assert stories.story_id([a]) != stories.story_id([b])
    assert stories.is_story_id(stories.story_id([a]))
    assert not stories.is_story_id("story-x")


def test_another_screenshot_of_the_same_story_hashes_close_and_another_story_far():
    first = stories.image_hash(screenshot(3, header="salsa.club 5 h"))
    again = stories.image_hash(screenshot(3, header="salsa.club 6 h"))  # an hour later: only the header changed
    other = stories.image_hash(screenshot(9))
    assert len(first) == 16
    assert stories.hash_distance(first, again) <= stories.HASH_DISTANCE
    assert stories.hash_distance(first, other) > stories.HASH_DISTANCE
    assert stories.same_story([other, first], [again])


# ---------- when ----------

NOW = datetime(2026, 10, 4, 20, 0, tzinfo=BOGOTA)


@pytest.mark.parametrize(
    "name",
    [
        "Screenshot_20261004-183012_Instagram.jpg",
        "Screenshot_2026-10-04-18-30-12-123_com.instagram.android.jpg",
        "Screenshot_20261004_183012.png",
    ],
)
def test_the_screenshot_time_comes_from_its_file_name(name):
    moment, source = stories.taken_at(Screenshot(b"", name, modified=1), NOW)
    assert moment == datetime(2026, 10, 4, 18, 30, 12, tzinfo=BOGOTA)
    assert source == "del nombre del archivo"


def test_the_screenshot_time_falls_back_to_the_files_date_then_the_upload():
    modified = int(datetime(2026, 10, 3, 9, 0, tzinfo=BOGOTA).timestamp() * 1000)
    uploaded = int(datetime(2026, 10, 4, 19, 0, tzinfo=BOGOTA).timestamp() * 1000)
    assert stories.taken_at(Screenshot(b"", "IMG.jpg", modified, uploaded), NOW)[1] == "de la fecha del archivo"
    future = int((NOW + timedelta(days=2)).timestamp() * 1000)
    moment, source = stories.taken_at(Screenshot(b"", "Screenshot_20301004-183012.jpg", future, uploaded), NOW)
    assert (moment.hour, source) == (19, "de cuando se subió")
    assert stories.taken_at(Screenshot(b""), NOW) == (NOW, "de ahora: la captura no dice cuándo se tomó")


def test_story_age():
    assert stories.story_age("5 h") == timedelta(hours=5)
    assert stories.story_age("hace 32 min") == timedelta(minutes=32)
    assert stories.story_age("3 d") is None  # stories last a day
    assert stories.story_age(None) is None


# ---------- dates, worked out in code ----------

TAKEN = date(2026, 10, 4)  # a Sunday


def resolve(taken: date = TAKEN, today: date | None = None, **fields):
    return stories.resolve_date(story_event(**fields), taken, today or taken)


def test_a_day_and_month_without_year_is_the_next_one_on_or_after_the_screenshot():
    resolved = resolve(day=10, month=10, weekday="sábado")
    assert resolved.start == date(2026, 10, 10)
    assert resolved.year_inferred and not resolved.weekday_mismatch
    assert "año deducido" in resolved.notes
    assert resolve(day=2, month=1).start == date(2027, 1, 2)  # January after October: next year
    assert resolve(day=4, month=10).start == TAKEN  # the screenshot's own day


def test_the_weekday_settles_the_year_and_a_mismatch_is_flagged():
    december = date(2026, 12, 28)
    assert resolve(december, day=2, month=1, weekday="sáb").start == date(2027, 1, 2)  # 2 Jan 2027 is a Saturday
    wrong = resolve(day=10, month=10, weekday="viernes")
    assert wrong.start == date(2026, 10, 10)  # the numbers win
    assert wrong.weekday_mismatch
    assert any("viernes" in note for note in wrong.notes)


def test_a_printed_year_is_kept_even_when_past():
    assert resolve(day=1, month=10, year=2026).start == date(2026, 10, 1)


def test_relative_days_weekdays_and_weekly_nights():
    assert resolve(relative_day="hoy").start == TAKEN
    assert resolve(relative_day="mañana").start == date(2026, 10, 5)
    assert resolve(weekday="sábado").start == date(2026, 10, 10)
    # A weekly night shared on Sunday, read on Wednesday: the next Friday from today.
    weekly = resolve(today=date(2026, 10, 7), weekday="viernes", weekly=True)
    assert weekly.start == date(2026, 10, 9)
    assert any("semanal" in note for note in weekly.notes)
    assert resolve(day=12, weekday="lunes").start == date(2026, 10, 12)  # "lunes 12": the month worked out


def test_ranges_and_far_dates():
    congress = resolve(day=13, month=11, end_day=15, end_month=11)
    assert (congress.start, congress.end) == (date(2026, 11, 13), date(2026, 11, 15))
    across = resolve(day=30, month=10, end_day=2)
    assert across.end == date(2026, 11, 2)
    assert resolve(day=1, month=10, year=2026, end_day=30).end is None  # longer than MAX_EVENT_DAYS
    far = resolve(day=20, month=12)
    assert far.far_ahead and any("60 días" in note for note in far.notes)
    assert resolve().start is None  # no date printed


# ---------- crops ----------


def test_geminis_box_is_checked_and_padded():
    box = stories.checked_box([100, 50, 900, 950], 1000, 2000)
    assert box == (20, 140, 980, 1860)  # 3% padding
    assert stories.checked_box([0, 0, 1000, 1000], 1000, 2000) == (0, 0, 1000, 2000)  # kept inside
    assert stories.checked_box([100, 100, 150, 150], 1000, 2000) is None  # too small: a sticker
    assert stories.checked_box([0, 0, 1000, 60], 1000, 2000) is None  # too small and too wide
    assert stories.checked_box([500, 100, 400, 900], 1000, 2000) is None  # upside down
    assert stories.checked_box([0, 0, 1200, 900], 1000, 2000) is None  # out of range
    assert stories.checked_box(None, 1000, 2000) is None
    assert stories.fixed_box(1000, 2000) == (0, 240, 1000, 1760)


def test_crop_uses_the_box_or_the_fixed_crop():
    image = screenshot()
    good = stories.crop(image, [130, 50, 870, 950])
    assert good.from_gemini
    assert Image.open(io.BytesIO(good.image)).size[1] < 2280
    fallback = stories.crop(image, [10, 10, 20, 20])
    assert not fallback.from_gemini
    assert Image.open(io.BytesIO(fallback.image)).size == (1080, 1732)  # 12% off the top and the bottom


# ---------- the account ----------


def test_reading_the_account_name():
    assert stories.read_handle("@Salsa.Club") == ("salsa.club", False)
    assert stories.read_handle("salsa_cl…") == ("salsa_cl", True)
    assert stories.read_handle(None) == (None, False)
    known = ["salsa_club_bogota", "salsa_caleña_x", "otra"]
    assert stories.known_account("salsa_club", True, known) == "salsa_club_bogota"
    assert stories.known_account("salsa", True, known) is None  # more than one starts so
    assert stories.known_account("salsa_club_bogata", False, known) == "salsa_club_bogota"  # a letter misread


# ---------- the whole flow, with fakes ----------

EVENT_DAY = config.now_bogota().date() + timedelta(days=6)


class FakeInstagram:
    def __init__(self, readable: set[str]):
        self.readable = readable
        self.calls: list[str] = []

    def check_token(self) -> str:
        return "me"

    def fetch_recent_posts(self, account: str, limit: int = 10) -> list[dict]:
        self.calls.append(account)
        if account not in self.readable:
            raise InstagramError("not visible", code=110)
        return []


class FakeStoryExtractor:
    def __init__(self, analysis: StoryAnalysis | None = None, out_of_quota: bool = False):
        self.analysis = analysis
        self.out_of_quota = out_of_quota
        self.calls: list[dict] = []

    def can_analyze(self) -> bool:
        return True

    def can_extract_with_flash(self) -> bool:
        return True

    def requests_this_run(self) -> dict[str, int]:
        return {"fake-flash": len(self.calls)}

    def models_unavailable(self) -> list[str]:
        return []

    def extract_story(self, images, taken, account, notes, known_events):
        if self.out_of_quota:
            raise QuotaExhaustedError("no quota")
        self.calls.append({"images": len(images), "account": account, "notes": notes, "taken": taken})
        return self.analysis, "fake-flash", False


def analysis(events=None, **fields) -> StoryAnalysis:
    defaults = {
        "is_event_post": True,
        "reason": "anuncia una social",
        "account_in_image": "salsa.club",
        "reshared_from": None,
        "mentions_in_image": ["@dj.timba"],
        "location_sticker": "Galería Café Libro",
        "story_age": "2 h",
        "images": [StoryImage(index=0, content_box=[120, 40, 880, 960])],
        "events": events
        if events is not None
        else [
            story_event(
                title="Noche de Salsa", day=EVENT_DAY.day, month=EVENT_DAY.month, start_time="21:00", venue=None
            )
        ],
    }
    return StoryAnalysis(**(defaults | fields))


@pytest.fixture(autouse=True)
def accounts(isolated_files):
    config.ACCOUNTS_FILE.write_text("academia\n", encoding="utf-8")


def shots(*seeds: int) -> list[Screenshot]:
    return [Screenshot(screenshot(seed), f"Screenshot_{config.now_bogota():%Y%m%d-%H%M%S}.jpg") for seed in seeds]


def sweep(extractor, readable=("salsa.club",)) -> Sweep:
    return Sweep(lookback_days=7, instagram=FakeInstagram(set(readable)), extractor=extractor)


def test_a_story_becomes_an_event_with_its_crop_and_the_profile_as_permalink():
    extractor = FakeStoryExtractor(analysis())
    added = sweep(extractor).add_story(shots(1, 2), notes="sábado")
    assert extractor.calls[0]["images"] == 2  # one request for every screenshot
    assert extractor.calls[0]["notes"] == "sábado"
    assert added.outcome == "event" and added.done
    assert (added.account, added.account_checked, added.account_added) == ("salsa.club", True, True)
    assert "salsa.club" in storage.read_accounts()

    [event] = storage.load_events()
    assert event.date == EVENT_DAY.isoformat()
    assert event.weekday == stories.WEEKDAYS[EVENT_DAY.weekday()]
    assert event.venue == "Galería Café Libro"  # from the location sticker
    assert event.account == "salsa.club"
    [story] = event.media
    assert story.media_type == "STORY"
    assert story.permalink == "https://www.instagram.com/salsa.club/"
    assert story.post_id == added.story_id and story.post_id.startswith("story-")
    assert story.caption is None
    assert story.flyer == f"flyers/{added.story_id}-0.webp"
    flyer = Image.open(config.DATA_DIR / story.flyer)
    assert flyer.size[0] / flyer.size[1] > 0.52  # the crop (about 0.57), not the whole screenshot (0.47)
    record = storage.load_processed_posts()[added.story_id]
    assert len(record.image_hashes) == 2 and not record.provisional

    receipt = added_story_markdown(added)
    assert f"/ocultar {added.story_id}" in receipt
    assert f"{config.SITE_URL}/flyers/{added.story_id}-0.webp" in receipt
    assert "leída del encabezado de la historia" in receipt
    assert "@dj.timba (no son la cuenta del evento)" in receipt
    assert "del nombre del archivo" in receipt


def test_the_same_screenshots_or_another_screenshot_of_the_story_arent_read_again():
    extractor = FakeStoryExtractor(analysis())
    first = sweep(extractor).add_story(shots(1))
    again = sweep(extractor).add_story(shots(1))
    assert again.unchanged and again.done and len(extractor.calls) == 1
    assert [event.id for event in again.events] == [event.id for event in first.events]
    later = [Screenshot(screenshot(1, header="salsa.club 3 h"), "Screenshot_x.jpg")]
    twin = sweep(extractor).add_story(later)
    assert twin.duplicate_of == first.story_id and len(extractor.calls) == 1
    assert "Ya está en el sitio" in added_story_markdown(twin)
    # With notes, it's read: whoever shares it says it's another story.
    sweep(extractor).add_story(later, notes="otra fecha")
    assert len(extractor.calls) == 2
    assert len(storage.load_events()) == 1  # and it merges into the same event anyway


def test_the_account_comes_from_the_request_then_a_reshared_post_then_the_header():
    extractor = FakeStoryExtractor(analysis(reshared_from="@la.orquesta"))
    added = sweep(extractor, readable=("la.orquesta", "salsa.club", "typed")).add_story(shots(1))
    assert added.account == "la.orquesta"
    typed = sweep(FakeStoryExtractor(analysis()), readable=()).add_story(shots(2), account="typed")
    assert (typed.account, typed.account_checked, typed.account_added) == ("typed", False, False)
    assert "typed" not in storage.read_accounts()  # the API can't read it: not swept


def test_a_cut_off_header_is_matched_to_a_known_account_or_asked_for():
    config.ACCOUNTS_FILE.write_text("salsa_club_bogota\n", encoding="utf-8")
    extractor = FakeStoryExtractor(analysis(account_in_image="salsa_club_b…"))
    added = sweep(extractor, readable=()).add_story(shots(1))
    assert added.account == "salsa_club_bogota" and "cuenta conocida" in added.account_source
    unknown = FakeStoryExtractor(analysis(account_in_image="zzz_unknown…"))
    with pytest.raises(AddPostError, match="escribiendo la @cuenta"):
        sweep(unknown, readable=()).add_story(shots(2))


def test_past_events_arent_published_and_the_screenshots_are_kept():
    yesterday = config.now_bogota().date() - timedelta(days=1)
    extractor = FakeStoryExtractor(
        analysis(events=[story_event(title="Ayer", day=yesterday.day, month=yesterday.month, year=yesterday.year)])
    )
    added = sweep(extractor).add_story(shots(1))
    assert added.past == ["Ayer"] and not added.done
    assert storage.load_events() == []
    assert storage.load_processed_posts()[added.story_id].outcome == "discarded"
    assert "ya pasó" in added_story_markdown(added)


def test_no_quota_says_so_and_keeps_nothing():
    with pytest.raises(AddPostError, match="cuota"):
        sweep(FakeStoryExtractor(out_of_quota=True)).add_story(shots(1))
    assert storage.load_processed_posts() == {}


def test_a_story_of_an_event_already_posted_merges_and_goes_last():
    post = stored(
        "noche-de-salsa", account="salsa.club", date=EVENT_DAY.isoformat(), start_time="21:00", title="Noche de Salsa"
    )
    storage.save_events([post])
    added = sweep(FakeStoryExtractor(analysis())).add_story(shots(1))
    assert added.outcome == "merged"
    [event] = storage.load_events()
    assert [item.media_type for item in event.media] == ["IMAGE", "STORY"]


def test_stories_go_after_posts_and_videos():
    items = [
        media("s", "STORY", published="2026-10-03T12:00:00+0000"),
        media("v", "VIDEO", published="2026-10-02T12:00:00+0000"),
        media("p", "IMAGE", published="2026-10-01T12:00:00+0000"),
    ]
    assert [item.media_type for item in ordered_media(items)] == ["IMAGE", "VIDEO", "STORY"]


def test_hiding_a_story_takes_it_off_the_site_and_reading_it_again_works():
    extractor = FakeStoryExtractor(analysis())
    added = sweep(extractor).add_story(shots(1))
    hidden = sweep(extractor).hide_story(added.story_id)
    assert [event.title for event in hidden.removed] == ["Noche de Salsa"]
    assert storage.load_events() == []
    assert not list(config.FLYERS_DIR.glob("*.webp"))
    assert storage.load_processed_posts()[added.story_id].outcome == "hidden"
    assert "Oculté" in hidden_story_markdown(hidden)
    assert sweep(extractor).hide_story(added.story_id).already
    with pytest.raises(AddPostError):
        sweep(extractor).hide_story("story-0000000000000000")
    sweep(extractor).add_story(shots(1))  # the same screenshots again: read and published again
    assert len(extractor.calls) == 2 and len(storage.load_events()) == 1


def test_hiding_keeps_an_event_other_posts_announce():
    post = stored(
        "noche-de-salsa", account="salsa.club", date=EVENT_DAY.isoformat(), start_time="21:00", title="Noche de Salsa"
    )
    storage.save_events([post])
    added = sweep(FakeStoryExtractor(analysis())).add_story(shots(1))
    hidden = sweep(FakeStoryExtractor()).hide_story(added.story_id)
    assert [event.id for event in hidden.kept] == ["noche-de-salsa"]
    [event] = storage.load_events()
    assert [item.media_type for item in event.media] == ["IMAGE"]


def test_screenshots_are_loaded_with_their_metadata(tmp_path):
    (tmp_path / "a.jpg").write_bytes(b"jpeg")
    (tmp_path / "a.json").write_text(json.dumps({"name": "Screenshot_1.jpg", "modified": 5, "uploaded": "x"}))
    (tmp_path / "b.jpg").write_bytes(b"jpeg2")
    assert load_screenshots(["a", "b"], tmp_path) == [
        Screenshot(b"jpeg", "Screenshot_1.jpg", 5, None),
        Screenshot(b"jpeg2", "", None, None),
    ]


# ---------- the inbox: "Agregar historia" and "Ocultar historia" ----------

UPLOAD_A, UPLOAD_B = "0" * 31 + "a", "0" * 31 + "b"


def form(**fields: str) -> str:
    return "\n\n".join(f"### {name}\n\n{value}" for name, value in fields.items()) + "\n\n_Desde la página._"


def test_the_inbox_reads_a_story_from_the_pages_form():
    from pa_bailar import inbox

    body = form(
        Acción="Agregar historia",
        Capturas=f"{UPLOAD_A} {UPLOAD_B} {UPLOAD_A}",
        Cuenta="@Salsa.Club",
        Notas="sábado 12 con @dj.timba",
    )
    assert inbox.parse(body) == inbox.Request(
        "add-story", account="salsa.club", images=(UPLOAD_A, UPLOAD_B), notes="sábado 12 con @dj.timba"
    )
    # No account typed: an @ in the notes is a hint, not the story's account.
    body = form(Acción="Agregar historia", Capturas=UPLOAD_A, Cuenta="_No response_", Notas="con @dj.timba")
    assert inbox.parse(body).account is None
    assert inbox.parse(form(Acción="Agregar historia", Capturas="nada", Cuenta="_No response_")).action == "help"
    hide = form(Acción="Ocultar historia", Historia="story-0123456789abcdef")
    assert inbox.parse(hide) == inbox.Request("hide-story", story="story-0123456789abcdef")
    assert inbox.parse(form(Acción="Ocultar historia", Historia="story-x")).action == "help"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"/historia {UPLOAD_A} @salsa.club sábado 12", ("add-story", (UPLOAD_A,), "salsa.club", "sábado 12")),
        (f"/Historia {UPLOAD_A} {UPLOAD_B}", ("add-story", (UPLOAD_A, UPLOAD_B), None, None)),
        ("/historia", ("help", (), None, None)),
        ("/ocultar story-0123456789abcdef", ("hide-story", (), None, None)),
        (f"otra historia {UPLOAD_A}", ("help", (), None, None)),  # words, not the command
    ],
)
def test_the_inbox_reads_story_commands(text, expected):
    from pa_bailar import inbox

    request = inbox.parse(text)
    assert (request.action, request.images, request.account, request.notes) == expected
    assert inbox.is_request(text) == text.startswith("/")


def test_the_inbox_passes_a_story_on_to_the_sweep(monkeypatch, tmp_path):
    from pa_bailar.commands import admin

    monkeypatch.setattr(admin.sweep_state, "refresh", lambda: True)
    outputs, reply = tmp_path / "outputs", tmp_path / "reply.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    monkeypatch.setenv("INBOX_REPLY", str(reply))
    monkeypatch.setenv("ISSUE_TITLE", "Agregar historia: 2 capturas")
    monkeypatch.setenv(
        "ISSUE_BODY",
        form(Acción="Agregar historia", Capturas=f"{UPLOAD_A} {UPLOAD_B}", Cuenta="_No response_", Notas="sábado\n12"),
    )
    monkeypatch.delenv("COMMENT_BODY", raising=False)
    monkeypatch.setenv("ADMIN_ISSUE", "true")
    admin.main(["inbox"])
    written = outputs.read_text(encoding="utf-8")
    assert "action=add-story\n" in written and f"images={UPLOAD_A} {UPLOAD_B}\n" in written
    assert "notes=sábado 12\n" in written and "done=false\n" in written
    assert "las 2 capturas" in reply.read_text(encoding="utf-8")


def test_the_sweep_command_writes_the_answer_and_whether_to_delete_the_screenshots(monkeypatch, tmp_path):
    from pa_bailar.commands import sweep as command

    folder = tmp_path / "stories"
    folder.mkdir()
    (folder / f"{UPLOAD_A}.jpg").write_bytes(screenshot(4))
    extractor = FakeStoryExtractor(analysis())
    monkeypatch.setattr(command, "Sweep", lambda lookback_days: sweep(extractor))
    report, outputs = tmp_path / "report.md", tmp_path / "outputs"
    monkeypatch.setenv("ADMIN_REPORT_FILE", str(report))
    monkeypatch.setenv("GITHUB_OUTPUT", str(outputs))
    command.main(["--story", UPLOAD_A, "--story-dir", str(folder), "--notes=-sábado"])
    assert extractor.calls[0]["notes"] == "-sábado"
    assert "story_done=true" in outputs.read_text(encoding="utf-8")
    assert "/ocultar story-" in report.read_text(encoding="utf-8")
