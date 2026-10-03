"""The admin tools' logic: links, the inbox, `why`, adding posts and accounts. No network, no Gemini."""

from datetime import datetime

import pytest

from pa_bailar import config, inbox, links, storage, why
from pa_bailar.instagram import InstagramError
from pa_bailar.pipeline import AddPostError
from tests.factories import extracted, stored
from tests.test_sweep import FakeExtractor, FakeInstagram, event_post, post

NOW = datetime(2026, 10, 3, 10, 0, tzinfo=config.BOGOTA_TZ)
LINK = "https://www.instagram.com/p/p1/?igsh=abc"


@pytest.fixture(autouse=True)
def accounts(isolated_files, monkeypatch):
    monkeypatch.setattr("pa_bailar.pipeline.download_image", lambda url: b"")
    monkeypatch.setattr("pa_bailar.pipeline._download_images", lambda post: [])
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


def unseen(published: str, history=None, first_seen="2026-09-01", fetch=None):
    instagram_post = {**post("p1"), "timestamp": published}
    return why.diagnose(
        LINK,
        "academia",
        read=state(history=history, account_state={"academia": {"first_seen": first_seen}} if first_seen else {}),
        fetch_posts=fetch or (lambda account: [instagram_post]),
        now=NOW,
    )


LAST_RUN = [{"finished_at": "2026-10-03T09:12:00-05:00", "pending": 0, "failed_accounts": []}]


def test_why_explains_a_post_the_sweeps_havent_seen():
    assert unseen("2026-10-03T15:00:00+0000", LAST_RUN).verdict.startswith("Se publicó después del último barrido")
    assert unseen("2026-09-20T15:00:00+0000", LAST_RUN).verdict.startswith("Es de hace más de 7 días")
    assert unseen("2026-10-02T15:00:00+0000", LAST_RUN, first_seen=None).verdict.startswith("La cuenta se agregó")
    failed = [{**LAST_RUN[0], "failed_accounts": ["academia"]}]
    assert unseen("2026-10-02T15:00:00+0000", failed).verdict == "El último barrido no pudo leer esta cuenta."


def test_why_says_when_the_post_isnt_among_the_accounts_latest():
    result = unseen("2026-10-02T15:00:00+0000", LAST_RUN, fetch=lambda account: [])
    assert result.verdict.startswith("¿Es una colaboración")


def test_why_text():
    text = why.markdown(why.diagnose(LINK, "otra", read=state(), now=NOW))
    assert text.startswith("**Ninguna publicación de esa cuenta se revisa.")
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
        ({"academia": []}, "academia", {}, "no está entre las últimas"),
        ({"academia": InstagramError("not visible")}, "academia", {}, "No pude leer @academia"),
        ({"academia": [post("p1")]}, None, {}, "Indica la @cuenta"),
        ({"academia": [post("p1")]}, "academia", {"out_of_quota": True}, "No queda cuota de Gemini"),
    ],
)
def test_add_post_says_why_it_couldnt(posts, account, extractor, message):
    with pytest.raises(AddPostError, match=message):
        sweep(posts, {}, **extractor).add_post(LINK, account)
