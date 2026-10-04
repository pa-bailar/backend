"""Account discovery: reading the export, ranking, filtering and the report (no network)."""

import json
from datetime import datetime

import pytest

from pa_bailar import config, discovery
from pa_bailar.models import AccountClassification

HTML_EXPORT = """<main>
<div><h2>zafradance</h2><div><a target="_blank" href="https://www.instagram.com/_u/zafradance">x</a></div></div>
<div><h2>tia.maria</h2><div><a target="_blank" href="https://www.instagram.com/_u/tia.maria">x</a></div></div>
<div><h2>escuela_de_salsa</h2><div><a href="https://www.instagram.com/_u/escuela_de_salsa">x</a></div></div>
<div><a href="https://www.instagram.com/_u/zafradance">duplicate</a></div>
</main>"""

JSON_EXPORT = {
    "relationships_following": [
        {"title": "zafradance", "string_list_data": [{"href": "https://www.instagram.com/zafradance", "value": ""}]},
        {"title": "", "string_list_data": [{"href": "https://www.instagram.com/tia.maria", "value": "tia.maria"}]},
    ]
}


def classification(kind="academy", in_bogota="yes", events=True) -> AccountClassification:
    return AccountClassification(
        kind=kind, in_bogota=in_bogota, city=None, styles=["salsa"], announces_events=events, reason="r"
    )


def test_parse_html_export(tmp_path):
    path = tmp_path / "following.html"
    path.write_text(HTML_EXPORT, encoding="utf-8")
    assert discovery.parse_following(path) == ["zafradance", "tia.maria", "escuela_de_salsa"]


def test_parse_json_export(tmp_path):
    path = tmp_path / "following.json"
    path.write_text(json.dumps(JSON_EXPORT), encoding="utf-8")
    assert discovery.parse_following(path) == ["zafradance", "tia.maria"]


def test_dance_looking_usernames_go_first():
    assert discovery.by_likelihood(["tia.maria", "escuela_de_salsa", "zafradance"])[:2] == [
        "escuela_de_salsa",
        "zafradance",
    ]


def test_dance_hint_reads_name_bio_and_captions_without_accents():
    profile = {
        "username": "casa_x",
        "name": "Casa X",
        "biography": "Clases de BAILE en Chapinero",
        "media": {"data": [{"caption": "Este sábado social de bachata"}]},
    }
    assert discovery.profile_hint(profile) >= 3  # bail, clase, social, bachat
    assert discovery.profile_hint({"username": "abogados_col", "biography": "Derecho inmobiliario"}) == 0


def test_recommended_needs_an_event_source_not_outside_bogota():
    assert discovery.is_recommended(classification("academy", "yes"))
    assert discovery.is_recommended(classification("venue", "unknown"))
    assert not discovery.is_recommended(classification("academy", "no"))


def test_artists_are_recommended_when_they_announce_one_time_events():
    # A teacher's own workshops and intensives, an orchestra's or DJ's dance nights: sources of events.
    assert discovery.is_recommended(classification("teacher", "yes", events=True))
    assert discovery.is_recommended(classification("musician", "unknown", events=True))
    # Only videos and regular classes: not worth a daily Instagram call and a triage per post.
    assert not discovery.is_recommended(classification("teacher", "yes", events=False))
    assert not discovery.is_recommended(classification("musician", "yes", events=False))
    # Based elsewhere, even if they come to Bogotá now and then.
    assert not discovery.is_recommended(classification("teacher", "no", events=True))
    # Shops and media stay out, whatever they post.
    assert not discovery.is_recommended(classification("dance_other", "yes", events=True))


def test_report_lists_recommended_and_maybe_and_skips_existing_sources():
    cache = {
        "zafradance": discovery.DiscoveredAccount(
            username="zafradance", status="business", dance_hint=3, classification=classification()
        ),
        "nueva_academia": discovery.DiscoveredAccount(
            username="nueva_academia", status="business", dance_hint=2, classification=classification()
        ),
        "profe_juan": discovery.DiscoveredAccount(
            username="profe_juan", status="business", dance_hint=2, classification=classification("teacher")
        ),
        "profe_ana": discovery.DiscoveredAccount(
            username="profe_ana",
            status="business",
            dance_hint=2,
            classification=classification("teacher", events=False),
        ),
        "medellin_salsa": discovery.DiscoveredAccount(
            username="medellin_salsa", status="business", dance_hint=2, classification=classification("academy", "no")
        ),
        "tia.maria": discovery.DiscoveredAccount(username="tia.maria", status="personal"),
    }
    sections = discovery.report_sections(cache, already_followed={"zafradance"})
    assert [r.username for r in sections["recommended"]] == ["nueva_academia", "profe_juan"]
    assert [r.username for r in sections["maybe"]] == ["profe_ana"]
    report = discovery.report_markdown(cache, {"zafradance"}, total=10)
    assert "nueva_academia" in report and "medellin_salsa" not in report and "1 personal" in report


def test_cache_round_trip(tmp_path):
    cache = {"a": discovery.DiscoveredAccount(username="a", status="business", classification=classification())}
    path = tmp_path / "discovery.json"
    discovery.save_cache(path, cache)
    assert discovery.load_cache(path) == cache


@pytest.mark.parametrize(
    ("time", "quiet"),
    [
        ("07:59", False),  # more than an hour before the 9:00 sweep
        ("08:01", True),  # the hour before it: Meta counts calls over a rolling hour
        ("09:20", True),  # while it runs
        ("09:46", False),  # 45 minutes after it started
        ("20:30", True),
        ("21:46", False),
        ("15:00", False),
    ],
)
def test_discovery_keeps_clear_of_the_daily_sweep(time, quiet):
    hour, minute = map(int, time.split(":"))
    now = datetime(2026, 10, 2, hour, minute, tzinfo=config.BOGOTA_TZ)
    assert discovery.near_sweep(now) is quiet


def test_personal_accounts_are_rechecked_when_their_verdict_is_stale():
    def personal(name, checked_on=None):
        return discovery.DiscoveredAccount(username=name, status="personal", checked_on=checked_on)

    cache = {
        "tia.maria": personal("tia.maria"),  # never rechecked
        "dlivingstudio": personal("dlivingstudio", "2026-09-01"),  # stale
        "escuela_de_salsa": personal("escuela_de_salsa", "2026-10-01"),  # checked 3 days ago: not yet
        "zafradance": discovery.DiscoveredAccount(username="zafradance", status="business"),
    }
    due = discovery.recheck_candidates(cache, "2026-10-04")
    assert set(due) == {"tia.maria", "dlivingstudio"}
    assert due[0] == "dlivingstudio"  # dance-looking names first ("studio")
