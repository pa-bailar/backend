"""The admin tools' logic: links, the inbox, `why`, adding posts and accounts. No network, no Gemini."""

from datetime import datetime

import pytest

from pa_bailar import config, inbox, links, public_post, storage, why
from pa_bailar.instagram import InstagramError
from pa_bailar.pipeline import AddPostError
from tests.factories import extracted, stored
from tests.test_sweep import FakeExtractor, FakeInstagram, event_post, post

NOW = datetime(2026, 10, 3, 10, 0, tzinfo=config.BOGOTA_TZ)
LINK = "https://www.instagram.com/p/p1/?igsh=abc"


def no_public_page(code):
    raise public_post.PublicPostError("su página pública no respondió")


@pytest.fixture(autouse=True)
def accounts(isolated_files, monkeypatch):
    monkeypatch.setattr("pa_bailar.pipeline.download_image", lambda url: b"")
    monkeypatch.setattr("pa_bailar.pipeline._download_images", lambda post: [])
    monkeypatch.setattr("pa_bailar.pipeline.public_post.fetch_public_post", no_public_page)  # never the network
    config.ACCOUNTS_FILE.write_text(
        "# Academies\nacademia\n\n# ----\n# Salsa bars: not swept\n# bar_salsero\n", encoding="utf-8"
    )


# ---------- links ----------


@pytest.mark.parametrize(
    ("url", "code", "account"),
    [
        ("https://www.instagram.com/p/Dd5JAAxjhg5/?igsh=x", "Dd5JAAxjhg5", None),
        ("instagram.com/reel/DeAvmXbuFUM/", "DeAvmXbuFUM", None),
        ("https://www.instagram.com/zafradance/p/Dd7ZDvZlo7o/", "Dd7ZDvZlo7o", "zafradance"),
        ("https://www.instagram.com/zafradance/", None, None),
        ("https://example.com/p/abc", None, None),
    ],
)
def test_post_links(url, code, account):
    assert links.post_code(url) == code
    assert links.account_in_link(url) == account


@pytest.mark.parametrize(
    ("text", "account"),
    [("@Academia", "academia"), ("academia.bog", "academia.bog"), ("https://instagram.com/iledanza/", "iledanza")],
)
def test_account_names(text, account):
    assert links.account_name(text) == account


# ---------- the inbox ----------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (LINK, inbox.Request("why", LINK)),
        (f"/agregar {LINK} @academia", inbox.Request("add-post", LINK, "academia")),
        (f"agrega este por favor, publícalo {LINK}", inbox.Request("add-post", LINK)),
        ("/cuenta @iledanza", inbox.Request("add-account", account="iledanza")),
        ("agregar cuenta https://www.instagram.com/iledanza/", inbox.Request("add-account", account="iledanza")),
        ("/estado", inbox.Request("status")),
        ("hola, ¿qué tal?", inbox.Request("help")),
        (
            f"### Acción\n\nAgregar\n\n### Enlace\n\n{LINK}\n\n### Cuenta\n\n_No response_",
            inbox.Request("add-post", LINK),
        ),
        (
            "### Acción\n\nAgregar cuenta\n\n### Enlace\n\n_No response_\n\n### Cuenta\n\n@nueva",
            inbox.Request("add-account", account="nueva"),
        ),  # fmt: skip
        ("### Acción\n\nRevisar\n\n### Enlace\n\n_No response_", inbox.Request("help")),
    ],
)
def test_the_inbox_understands_requests(text, expected):
    assert inbox.parse(text) == expected


# ---------- why ----------


def state(processed=None, history=None, account_state=None):
    files = {
        "processed_posts.json": processed or {},
        "run_history.json": history or [],
        "accounts.json": account_state or {},
    }
    return lambda name, default: files.get(name, default)


def record(**fields):
    return {
        "account": "academia",
        "permalink": "https://www.instagram.com/p/p1/",
        "processed_at": "2026-10-02T21:05:00-05:00",
        "is_event_post": True,
        "reason": "Anuncia un social",
        "model": "gemini-3.8-flash",
        **fields,
    }


def test_why_finds_the_event_on_the_site():
    event = stored()
    storage.write_json(config.EVENTS_FILE, [event.model_dump(mode="json")])
    result = why.diagnose(LINK, read=state({"1": record(outcome="event", event_ids=[event.id])}), now=NOW)
    assert result.verdict == "Está en el sitio."
    assert result.events[0]["url"].endswith(f"/evento/{event.id}/")
    assert result.suggestion == "none"


@pytest.mark.parametrize(
    ("fields", "verdict_starts"),
    [
        ({"is_event_post": False, "outcome": "not_event", "reason": "Es un tutorial"}, "Si sí es un evento"),
        ({"outcome": "discarded", "detail": "recurrente"}, "Se descartó a propósito"),
        ({"outcome": "rejected", "reason": "rechazado por Gemini: 400"}, "Agregarla lo intenta de nuevo"),
        ({"outcome": "event", "event_ids": ["gone"]}, "No está en el sitio"),
    ],
)
def test_why_explains_what_became_of_an_analyzed_post(fields, verdict_starts):
    result = why.diagnose(LINK, read=state({"1": record(**fields)}), now=NOW)
    assert result.verdict.startswith(verdict_starts)
    assert result.suggestion == "add-post"


def test_why_says_when_an_event_was_removed_by_hand():
    removed = record(is_event_post=False, reason="Quitado a mano: taller de dibujo, no de baile.")
    result = why.diagnose(LINK, read=state({"1": removed}), now=NOW)
    assert result.verdict == "No está en el sitio a propósito." and result.suggestion == "none"


def test_why_needs_the_account_for_a_post_it_never_saw():
    assert "indica la @cuenta" in why.diagnose(LINK, read=state(), now=NOW).verdict


def test_why_says_when_the_account_isnt_swept():
    result = why.diagnose(LINK, "otra", read=state(), now=NOW)
    assert "no está en los barridos" in result.checks[0][1] and result.suggestion == "add-post"


def unseen(published: str, history=None, first_seen="2026-09-01", fetch=None, swept_at=None):
    instagram_post = {**post("p1"), "timestamp": published}
    account = {"first_seen": first_seen, "last_swept_at": swept_at}
    return why.diagnose(
        LINK,
        "academia",
        read=state(history=history, account_state={"academia": account} if first_seen else {}),
        fetch_posts=fetch or (lambda account: [instagram_post]),
        now=NOW,
    )


LAST_RUN = [{"finished_at": "2026-10-03T09:12:00-05:00", "pending": 0, "failed_accounts": []}]


def test_why_explains_a_post_the_sweeps_havent_seen():
    assert unseen("2026-10-03T15:00:00+0000", LAST_RUN).verdict.startswith("Se publicó después de la última lectura")
    assert unseen("2026-09-20T15:00:00+0000", LAST_RUN).verdict.startswith("Es de hace más de 7 días")
    assert unseen("2026-10-02T15:00:00+0000", LAST_RUN, first_seen=None).verdict.startswith("La cuenta se agregó")
    failed = [{**LAST_RUN[0], "failed_accounts": ["academia"]}]
    assert unseen("2026-10-02T15:00:00+0000", failed).verdict.startswith("La última vez que le tocó")


def test_why_compares_with_the_accounts_own_turn():
    """Each account is read about once a day: the last run may not have read it."""
    morning = {
        "finished_at": "2026-10-03T09:12:00-05:00",
        "pending": 0,
        "failed_accounts": ["academia"],
        "read_accounts": [],
    }
    evening = {"finished_at": "2026-10-03T21:10:00-05:00", "pending": 0, "failed_accounts": [],
               "read_accounts": ["otra"]}  # fmt: skip
    # Posted at noon, after the account's reading in the morning but before the evening run (which didn't read it).
    after_its_turn = unseen("2026-10-03T17:00:00+0000", [morning, evening], swept_at="2026-10-03T09:05:00-05:00")
    assert after_its_turn.verdict.startswith("Se publicó después de la última lectura")
    # Posted before its reading, which failed: the evening run doesn't hide that.
    before = unseen("2026-10-02T15:00:00+0000", [morning, evening], swept_at="2026-10-03T09:05:00-05:00")
    assert before.verdict.startswith("La última vez que le tocó")


def test_why_says_when_the_post_isnt_among_the_accounts_latest():
    result = unseen("2026-10-02T15:00:00+0000", LAST_RUN, fetch=lambda account: [])
    assert result.verdict.startswith("Es antigua, o es una colaboración")


def test_why_text():
    text = why.markdown(why.diagnose(LINK, "otra", read=state(), now=NOW))
    assert text.startswith("**Esa cuenta no se revisa.")
    assert "❌ @otra no está en los barridos." in text and "**Agregar**" in text


# ---------- adding accounts and posts ----------


def test_accounts_added_by_hand_go_in_their_own_section_before_the_notes():
    assert storage.add_account("nueva") is True
    assert storage.add_account("otra_mas") is True
    assert storage.add_account("academia") is False
    text = config.ACCOUNTS_FILE.read_text(encoding="utf-8")
    assert text == (
        "# Academies\nacademia\n\n"
        f"{storage.ADDED_BY_ADMIN}\nnueva\notra_mas\n\n"
        "# ----\n# Salsa bars: not swept\n# bar_salsero\n"
    )
    assert storage.read_accounts() == ["academia", "nueva", "otra_mas"]


def sweep(posts_by_account, analyses, **extractor):
    from pa_bailar.pipeline import Sweep

    return Sweep(
        lookback_days=7, instagram=FakeInstagram(posts_by_account), extractor=FakeExtractor(analyses, **extractor)
    )


def test_add_post_publishes_a_post_without_triage():
    # Triage would say "not an event" (not_events): adding by hand skips it.
    added = sweep({"academia": [post("p1")]}, {"p1": event_post("p1")}, not_events={"p1"}).add_post(LINK, "academia")
    assert added.outcome == "event" and [e.title for e in added.events] == [extracted().title]
    assert storage.load_processed_posts()["p1"].outcome == "event"
    assert added.account_added is False


def test_add_post_adds_an_account_that_isnt_swept():
    added = sweep({"nueva": [post("p1")]}, {"p1": event_post("p1")}).add_post(LINK, "nueva")
    assert added.account_added is True and "nueva" in storage.read_accounts()
    assert storage.load_account_state()["nueva"].backfill_done is False  # its older posts load next sweep


@pytest.mark.parametrize(
    ("posts", "account", "extractor", "message"),
    [
        ({"academia": []}, "academia", {}, "No pude leer la publicación"),
        ({"academia": InstagramError("not visible", code=110)}, "academia", {}, "No pude leer la publicación"),
        ({"academia": [post("p1")]}, None, {}, "No pude leer la publicación"),
        ({"academia": [post("p1")]}, "academia", {"out_of_quota": True}, "No queda cuota de Gemini"),
    ],
)
def test_add_post_says_why_it_couldnt(posts, account, extractor, message):
    with pytest.raises(AddPostError, match=message):
        sweep(posts, {}, **extractor).add_post(LINK, account)


# ---------- the public page fallback (public_post.py) ----------


def public_page(author: str):
    def fetch(code):
        return author, {**post("public-p1"), "permalink": f"https://www.instagram.com/p/{code}/"}

    return fetch


def test_a_personal_accounts_post_is_read_from_its_public_page(monkeypatch):
    monkeypatch.setattr("pa_bailar.pipeline.public_post.fetch_public_post", public_page("personal"))
    not_visible = InstagramError("Invalid user id", code=110)
    added = sweep({"personal": not_visible}, {"public-p1": event_post("public-p1")}).add_post(LINK, "personal")
    assert added.public and not added.readable and added.outcome == "event"
    assert "personal" not in storage.read_accounts()  # the API can't read it: it can't be swept


def test_the_public_page_names_the_author_when_the_link_doesnt(monkeypatch):
    monkeypatch.setattr("pa_bailar.pipeline.public_post.fetch_public_post", public_page("academia"))
    added = sweep({"academia": [post("p1")]}, {"p1": event_post("p1")}).add_post(LINK)
    assert added.account == "academia" and not added.public  # found through the API, once the author is known


def test_a_collaboration_is_its_authors_post(monkeypatch):
    monkeypatch.setattr("pa_bailar.pipeline.public_post.fetch_public_post", public_page("organizador"))
    added = sweep({"academia": [], "organizador": []}, {"public-p1": event_post("public-p1")}).add_post(
        LINK, "academia"
    )
    assert added.account == "organizador" and added.public and added.outcome == "event"


def test_reading_a_real_embed_page():
    page = (
        '<div class="UsernameText">levelupbfc</div><img class="EmbeddedMediaImage" alt="" '
        'src="https://cdn.example/flyer.jpg?a=1&amp;b=2"/><div class="Caption">levelupbfc<br/><br/>BACHATEROS, '
        'prepárense &amp; vengan<br/>En noviembre llega un congreso<div class="CaptionComments"></div></div>'
    )
    author, found = public_post.parse_embed("Dc_Jsv6R6Wu", page)
    assert author == "levelupbfc" and found["media_type"] == "IMAGE"
    assert found["media_url"] == "https://cdn.example/flyer.jpg?a=1&b=2"
    assert found["caption"].startswith("BACHATEROS, prepárense & vengan\nEn noviembre")
    with pytest.raises(public_post.PublicPostError):
        public_post.parse_embed("x", "<html>Instagram</html>")  # the empty page plain scripts get


def test_why_finds_the_author_on_the_public_page():
    result = why.diagnose(LINK, read=state(), author_of=lambda code: "otra", now=NOW)
    assert result.account == "otra" and "no está en los barridos" in result.checks[0][1]


def test_why_explains_a_collaboration():
    result = unseen_with_author("organizador")
    assert "La publicó @organizador, en colaboración con @academia." in [text for _, text in result.checks]


def test_why_explains_an_account_the_api_cant_read():
    def not_visible(account):
        raise InstagramError("Invalid user id", code=110)

    result = why.diagnose(LINK, "academia", read=state(), fetch_posts=not_visible, now=NOW)
    assert "cuenta personal o privada" in result.checks[-1][1] and "página pública" in result.verdict


def unseen_with_author(author):
    return why.diagnose(
        LINK, "academia", read=state(), fetch_posts=lambda account: [], author_of=lambda code: author, now=NOW
    )


# ---------- one post, one identity; Gemini only when it can change something ----------

RATE_LIMITED = InstagramError("Application request limit reached", code=4)


def test_adding_an_unchanged_post_again_spends_no_gemini_request():
    sweep({"academia": [post("p1")]}, {"p1": event_post("p1")}).add_post(LINK, "academia")
    again = sweep({"academia": [post("p1")]}, {})
    added = again.add_post(LINK, "academia")
    assert added.unchanged and added.outcome == "event" and len(added.events) == 1
    assert again.extractor.extracted_posts == []


def test_an_edited_caption_is_read_again():
    sweep({"academia": [post("p1")]}, {"p1": event_post("p1")}).add_post(LINK, "academia")
    edited = {**post("p1"), "caption": "Cambio de lugar: ahora en Casa Latina"}
    again = sweep({"academia": [edited]}, {"p1": event_post("p1", venue="Casa Latina")})
    added = again.add_post(LINK, "academia")
    assert not added.unchanged and again.extractor.extracted_posts == ["p1"]
    assert added.events[0].venue == "Casa Latina"


def test_a_post_the_filter_called_not_an_event_is_read_when_added():
    from pa_bailar.models import ProcessedPost

    filtered = ProcessedPost(**record(is_event_post=False, outcome="not_event"), caption_hash=None)
    storage.save_processed_posts({"p1": filtered})
    added = sweep({"academia": [post("p1")]}, {"p1": event_post("p1")}).add_post(LINK, "academia")
    assert not added.unchanged and added.outcome == "event"


def test_a_post_added_from_its_public_page_is_the_same_post_for_the_sweeps(monkeypatch):
    from tests.test_sweep import FakeExtractor, FakeInstagram, run

    monkeypatch.setattr("pa_bailar.pipeline.public_post.fetch_public_post", public_page("academia"))
    added = sweep({"academia": RATE_LIMITED}, {"public-p1": event_post("public-p1")}).add_post(LINK, "academia")
    assert added.public and "public-p1" in storage.load_processed_posts()

    extractor = FakeExtractor({})  # no prepared answers: any Gemini request would fail the test
    run(FakeInstagram({"academia": [post("p1")]}), extractor)
    assert extractor.extracted_posts == []
    assert set(storage.load_processed_posts()) == {"p1"}  # under the API's id from now on
    [event] = storage.load_events()
    assert [media.post_id for media in event.media] == ["p1"]  # one post: its flyer isn't added twice


def test_a_post_read_through_the_api_keeps_its_id_when_read_from_its_public_page(monkeypatch):
    sweep({"academia": [post("p1")]}, {"p1": event_post("p1")}).add_post(LINK, "academia")
    monkeypatch.setattr("pa_bailar.pipeline.public_post.fetch_public_post", public_page("academia"))
    again = sweep({"academia": RATE_LIMITED}, {})
    added = again.add_post(LINK, "academia")
    assert added.public and added.unchanged and again.extractor.extracted_posts == []
    assert set(storage.load_processed_posts()) == {"p1"}


def test_the_answer_says_an_unchanged_post_wasnt_read_again():
    from pa_bailar.commands.sweep import added_post_markdown

    sweep({"academia": [post("p1")]}, {"p1": event_post("p1")}).add_post(LINK, "academia")
    answer = added_post_markdown(sweep({"academia": [post("p1")]}, {}).add_post(LINK, "academia"))
    assert "no gasté cuota de Gemini" in answer and "Ya está en el sitio" in answer and "Publiqué" not in answer


def test_the_inbox_takes_only_the_link_from_the_form_field():
    body = f"### Acción\n\nRevisar\n\n### Enlace\n\n{LINK}\naction=add-account\n\n### Cuenta\n\n_No response_"
    assert inbox.parse(body) == inbox.Request("why", LINK)


def test_the_public_page_gives_the_posts_real_date_and_only_numeric_ids():
    import json

    def page(media_id):
        media = {
            "id": media_id,
            "owner": {"username": "levelupbfc"},
            "__typename": "GraphImage",
            "display_url": "https://cdn.example/flyer.jpg",
            "taken_at_timestamp": 1790000000,
            "edge_media_to_caption": {"edges": [{"node": {"text": "Congreso"}}]},
        }
        context = json.dumps(json.dumps({"gql_data": {"shortcode_media": media}}))[1:-1]
        return f'<script>{{"contextJSON":"{context}"}}</script>'

    _, found = public_post.parse_embed("Dc_Jsv6R6Wu", page("3741"))
    assert found["id"] == "public-3741" and found["timestamp"].startswith("2026-09-21")
    with pytest.raises(public_post.PublicPostError):
        public_post.parse_embed("Dc_Jsv6R6Wu", page("../../evil"))  # it names files: digits only
