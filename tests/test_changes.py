"""The admin page's history (changes.py): what each run did to which event, recorded by the sweep with fakes and by
the admin requests, kept bounded, and gathered by `admin status` (status.history_of). No network."""

import json

import pytest

from pa_bailar import changes, config, health, status, storage
from pa_bailar.changes import EventChange
from pa_bailar.commands import sweep as sweep_command
from pa_bailar.models import PostAnalysis
from pa_bailar.pipeline import RunStats, Sweep
from tests.factories import EVENT_DATE, event_id, make_image, media, stored
from tests.test_hide_event import sweep_with
from tests.test_sweep import CANCELLED, FakeExtractor, FakeInstagram, cancel, days_ago_date, event_post, post, run


@pytest.fixture(autouse=True)
def accounts_and_images(isolated_files, monkeypatch):
    """On top of the shared isolation (conftest.py): two accounts, images without the network, no discovery."""
    config.ACCOUNTS_FILE.write_text("academia\notra\n", encoding="utf-8")
    monkeypatch.setattr(config, "PRIVATE_DIR", isolated_files / "private")
    monkeypatch.setattr("pa_bailar.pipeline.common.download_image", lambda url: make_image())


def kinds(stats: RunStats) -> list[tuple[str, str, str | None]]:
    """(kind, event id, detail) of each change, as noted."""
    return [(item.kind, item.id, item.detail) for item in stats.changes.values()]


# ---------- what the sweep notes ----------


def test_a_new_event_is_noted_with_its_title_account_date_and_id():
    stats = run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    [item] = stats.changes.values()
    assert item == EventChange(kind="new", id=event_id("Social"), title="Social", account="academia", date=EVENT_DATE)
    record = health.record_of(stats, [])
    assert record.changes == [item] and record.change_counts == {"new": 1} and record.changes_left_out == 0


def test_another_post_of_an_event_on_the_site_is_merged_and_says_whose():
    details = {"title": "Social Timbera", "venue": "Casa Latina", "start_time": "21:00"}
    run(
        FakeInstagram({"academia": [post("own", days_ago=3)], "otra": []}),
        FakeExtractor({"own": event_post("own", **details)}),
    )
    instagram = FakeInstagram(
        {"academia": [post("own", days_ago=3), post("again", days_ago=1)], "otra": [post("shared")]}
    )
    analyses = {"again": event_post("again", **details), "shared": event_post("shared", **details)}
    stats = run(instagram, FakeExtractor(analyses))
    # One note per event: the latest (the other account's post came after the account's own).
    assert kinds(stats) == [("merged", event_id("Social Timbera"), "otra publicación de @otra")]


def test_a_second_post_of_an_event_added_in_the_same_run_leaves_it_new():
    instagram = FakeInstagram({"academia": [post("video", "VIDEO", days_ago=1), post("flyer", days_ago=3)], "otra": []})
    analyses = {
        "flyer": event_post("flyer", title="Social", start_time="20:00"),
        "video": event_post("video", title="Ven a bailar", same_as=event_id("Social")),
    }
    stats = run(instagram, FakeExtractor(analyses))
    assert kinds(stats) == [("new", event_id("Social"), None)]


def test_a_lighter_read_is_provisional_then_flash_corrects_or_confirms_it():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    lite = event_post("p1", title="Social de salsa", start_time="20:00", venue="Casa")
    first = run(instagram, FakeExtractor({"p1": lite}, flash_available=False))
    social = event_id("Social de salsa")
    assert [(item.kind, item.id) for item in first.changes.values()] == [("provisional", social)]

    flash = event_post("p1", title="Social de salsa", start_time="21:00", venue="Casa Latina")
    assert kinds(run(instagram, FakeExtractor({"p1": flash}))) == [
        ("corrected", social, "Flash cambió la hora y el lugar")
    ]


def test_flash_agreeing_with_a_lighter_read_is_noted_as_confirmed():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    same = event_post("p1", title="Social de salsa", start_time="20:00")
    run(instagram, FakeExtractor({"p1": same}, flash_available=False))
    assert kinds(run(instagram, FakeExtractor({"p1": same}))) == [
        ("reread", event_id("Social de salsa"), "Flash confirmó la lectura")
    ]


def test_flash_finding_no_event_where_a_lighter_model_did_drops_it():
    instagram = FakeInstagram({"academia": [post("p1")], "otra": []})
    run(instagram, FakeExtractor({"p1": event_post("p1")}, flash_available=False))
    nothing = PostAnalysis(is_event_post=False, reason="Es un video de clase", events=[])
    stats = run(instagram, FakeExtractor({"p1": nothing}))
    assert kinds(stats) == [("dropped", event_id("Social"), "Flash no lo encontró al releer")]


def test_an_edited_caption_notes_what_changed():
    first = post("p1")
    run(FakeInstagram({"academia": [first], "otra": []}), FakeExtractor({"p1": event_post("p1", venue=None)}))
    edited = {**first, "caption": "Ahora con lugar"}
    stats = run(
        FakeInstagram({"academia": [edited], "otra": []}), FakeExtractor({"p1": event_post("p1", venue="Mambo")})
    )
    assert kinds(stats) == [("updated", event_id("Social"), "publicación editada: cambió el lugar")]


def test_a_cancelled_post_and_another_accounts_cancellation_are_noted():
    details = {"title": "Social Timbera", "venue": "Casa Latina", "start_time": "21:00"}
    own, shared = post("own", days_ago=3), post("shared", days_ago=2)
    analyses = {"own": event_post("own", **details), "shared": event_post("shared", **details)}
    run(FakeInstagram({"academia": [own], "otra": [shared]}), FakeExtractor(analyses))

    flagged = run(FakeInstagram({"academia": [own], "otra": [cancel(shared)]}), FakeExtractor({"shared": CANCELLED}))
    social = event_id("Social Timbera")
    assert kinds(flagged) == [("flagged", social, "@otra lo anunció cancelado o aplazado: revisar")]

    gone = run(FakeInstagram({"academia": [cancel(own)], "otra": []}), FakeExtractor({"own": CANCELLED}))
    assert kinds(gone) == [("cancelled", social, "la publicación dice que se canceló o se aplazó")]


def test_archived_and_merged_duplicates_are_noted():
    old = stored("old-0", posts=[media("old")], date=days_ago_date(config.EVENT_RETENTION_DAYS + 1))
    full = stored("salsoteca-dc-acere", posts=[media("carousel")], title="Salsoteca DC - Acere", address="Diagonal 20A")
    bare = stored("acere", posts=[media("video", "VIDEO")], title="Acere")
    storage.save_events([old, full, bare])
    stats = run(FakeInstagram({"academia": [], "otra": []}), FakeExtractor({}))
    assert kinds(stats) == [
        ("duplicate", "salsoteca-dc-acere", "unido con «Acere», el mismo evento"),
        ("archived", "old-0", f"terminó hace más de {config.EVENT_RETENTION_DAYS} días"),
    ]


def test_hiding_keeping_hidden_and_publishing_again_by_hand_are_noted():
    p1 = post("p1", days_ago=3)
    run(FakeInstagram({"academia": [p1], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    social = event_id("Social")

    hiding = sweep_with([p1], {})
    hiding.hide_event(social)
    assert kinds(hiding.stats) == [("hidden", social, "oculto a mano: los barridos no lo vuelven a publicar")]

    edited = {**p1, "caption": "caption editado"}
    kept = run(FakeInstagram({"academia": [edited], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    assert kinds(kept) == [("kept_hidden", social, "oculto a mano: no se volvió a publicar")]

    again = sweep_with([edited], {"p1": event_post("p1")})
    again.add_post("https://www.instagram.com/p/p1/", "academia")
    assert kinds(again.stats) == [("restored", social, "oculto antes, publicado de nuevo a mano")]


def test_the_site_data_doesnt_carry_the_changes():
    run(FakeInstagram({"academia": [post("p1")], "otra": []}), FakeExtractor({"p1": event_post("p1")}))
    meta = json.loads(config.META_FILE.read_text(encoding="utf-8"))
    assert meta["stats"]["events_new"] == 1 and "changes" not in meta["stats"]


# ---------- one change per event, bounded ----------


def change(kind: str, event: str) -> EventChange:
    return EventChange(kind=kind, id=event, title=event, account="academia")


def test_a_new_event_read_again_in_the_same_run_stays_new_and_gone_shows_gone():
    noted: dict[str, EventChange] = {}
    changes.noted(noted, change("provisional", "a"))
    changes.noted(noted, change("corrected", "a").model_copy(update={"detail": "Flash cambió la hora"}))
    changes.noted(noted, change("new", "b"))
    changes.noted(noted, change("merged", "b"))
    changes.noted(noted, change("new", "c"))
    changes.noted(noted, change("dropped", "c"))
    assert [(item.kind, item.id, item.detail) for item in noted.values()] == [
        ("new", "a", "Flash cambió la hora"),
        ("new", "b", None),
        ("dropped", "c", None),
    ]


def test_the_most_telling_changes_are_kept_first_and_the_rest_counted():
    every = [change("archived", "old"), change("reread", "r"), change("new", "n1"), change("cancelled", "x")]
    every += [change("new", "n2")]
    kept, left_out = changes.bounded(every, limit=3)
    assert [item.id for item in kept] == ["x", "n1", "n2"] and left_out == 2
    assert changes.counts(every) == {"cancelled": 1, "new": 2, "reread": 1, "archived": 1}


def test_a_run_record_keeps_at_most_the_cap_and_counts_them_all(monkeypatch):
    monkeypatch.setattr(config, "RUN_CHANGES_KEPT", 2)
    stats = RunStats()
    for name in ("a", "b", "c"):
        stats.note("new", stored(name))
    record = health.record_of(stats, [])
    assert [item.id for item in record.changes or []] == ["a", "b"]
    assert (record.changes_left_out, record.change_counts) == (1, {"new": 3})


def test_only_the_latest_runs_keep_their_list_of_changes(monkeypatch):
    monkeypatch.setattr(config, "CHANGES_KEPT_RUNS", 2)
    stats = RunStats()
    stats.note("new", stored("a"))
    health.save_history([health.record_of(stats, []) for _ in range(3)])
    saved = health.load_history()
    assert [run.changes is None for run in saved] == [True, False, False]
    assert all(run.change_counts == {"new": 1} for run in saved)


def test_every_kind_has_its_place_in_the_order():
    from typing import get_args

    assert set(changes.KIND_ORDER) == set(get_args(changes.ChangeKind))


@pytest.mark.parametrize(
    ("fields", "label"),
    [
        (["venue"], "cambió el lugar"),
        (["start_time", "venue"], "cambió la hora y el lugar"),
        (["date", "start_time", "venue"], "cambió la fecha, la hora y el lugar"),
    ],
)
def test_what_changed_reads_as_a_sentence(fields, label):
    assert changes.fields_label(fields) == label


# ---------- the admin requests ----------


@pytest.fixture
def fake_sweeps(monkeypatch):
    """The commands' Sweep, with fakes: one post of one event."""
    p1 = post("p1", days_ago=3)
    monkeypatch.setattr(sweep_command, "run_url", lambda: "https://github.com/x/actions/runs/1")
    monkeypatch.setattr(
        sweep_command,
        "Sweep",
        lambda lookback_days: Sweep(
            lookback_days=lookback_days,
            instagram=FakeInstagram({"academia": [p1], "otra": []}),
            extractor=FakeExtractor({"p1": event_post("p1")}),
        ),
    )


def test_an_admin_request_records_what_it_changed_or_why_it_couldnt(fake_sweeps):
    sweep_command.add_post("https://www.instagram.com/p/p1/", "academia")
    sweep_command.hide_event("no-existe")
    added, failed = changes.load_admin_runs()
    assert (added.action, added.target, added.error) == ("post", "https://www.instagram.com/p/p1/", None)
    assert [(item.kind, item.id) for item in added.changes] == [("new", event_id("Social"))]
    assert added.run_url == "https://github.com/x/actions/runs/1" and added.change_counts == {"new": 1}
    assert (failed.action, failed.target, failed.changes) == ("hide_event", "no-existe", [])
    assert failed.error and "No encontré el evento" in failed.error


def test_only_the_latest_admin_requests_are_kept(monkeypatch):
    monkeypatch.setattr(config, "ADMIN_RUNS_KEPT", 2)
    for target in ("a", "b", "c"):
        changes.record_admin_run("hide_event", target, [])
    assert [run.target for run in changes.load_admin_runs()] == ["b", "c"]


# ---------- admin status: the history ----------


def sweep_run(finished_at: str, **fields) -> dict:
    return {"finished_at": finished_at, "events_new": 0, "events_merged": 0, **fields}


def test_the_history_mixes_sweeps_and_requests_newest_first():
    new = {"kind": "new", "id": "social-11-oct", "title": "Social", "account": "academia", "date": "2026-10-11"}
    runs = [
        sweep_run("2026-10-08T06:49:00-05:00", events_new=2, events_merged=1),  # before the changes were kept
        sweep_run("2026-10-08T21:20:00-05:00", changes=[new], change_counts={"new": 1}),
        sweep_run("2026-10-09T15:02:00-05:00", changes=[], change_counts={}),  # started by hand
    ]
    admin_runs = [
        {
            "finished_at": "2026-10-09T10:00:00-05:00",
            "action": "hide_event",
            "target": "social-11-oct",
            "changes": [{**new, "kind": "hidden"}],
            "change_counts": {"hidden": 1},
        }
    ]
    items = status.history_of(runs, admin_runs)
    assert [(item["kind"], item["slot"]) for item in items] == [
        ("sweep", None),
        ("hide_event", None),
        ("sweep", "21:00"),
        ("sweep", "06:30"),
    ]
    assert items[0]["changes"] == [] and items[0]["counts"] == {}
    assert items[1]["target"] == "social-11-oct" and items[1]["counts"] == {"hidden": 1}
    assert items[2]["changes"][0]["url"] == "https://pa-bailar.github.io/evento/social-11-oct/"
    assert items[3]["changes"] is None and items[3]["counts"] == {"new": 2, "merged": 1}  # "sin detalle"


def test_the_history_shows_the_latest_runs_only():
    runs = [sweep_run(f"2026-10-0{day}T06:50:00-05:00") for day in range(1, 10)]
    admin = [{"finished_at": f"2026-10-0{day}T12:00:00-05:00", "action": "post"} for day in range(1, 10)]
    items = status.history_of(runs, admin)
    assert len(items) == status.HISTORY_ITEMS and items[0]["finished_at"].startswith("2026-10-09T12")


@pytest.mark.parametrize(
    ("finished_at", "slot"),
    [
        ("2026-10-09T06:49:59-05:00", "06:30"),
        ("2026-10-09T21:31:00-05:00", "21:00"),
        ("2026-10-09T11:49:00Z", "06:30"),  # UTC, as GitHub might write it: 6:49 in Bogotá
        ("2026-10-09T15:00:00-05:00", None),
        ("2026-10-09T06:10:00-05:00", None),  # before the morning's time
    ],
)
def test_a_sweep_is_the_scheduled_one_it_ended_after(finished_at, slot):
    assert status.sweep_slot(finished_at) == slot


def test_the_status_carries_the_history_and_the_recent_sweeps_without_their_lists():
    item = {"kind": "new", "id": "a", "title": "A", "account": "academia"}
    files = {
        "run_history.json": [sweep_run("2026-10-09T06:49:00-05:00", changes=[item], change_counts={"new": 1})],
        "admin_runs.json": [{"finished_at": "2026-10-09T10:00:00-05:00", "action": "story", "changes": []}],
    }
    result = status.collect(instagram=None, read=lambda name, default: files.get(name, default))
    assert [entry["kind"] for entry in result["history"]] == ["story", "sweep"]
    assert "changes" not in result["sweeps"]["recent"][0]
