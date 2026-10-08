"""admin status: what it reads and how it says it, from fake state (no git, no network)."""

from datetime import datetime, timedelta

import pytest

from pa_bailar import config, status
from pa_bailar.gemini import daily_budget, quota_day

NOW = datetime(2026, 10, 2, 20, 15, tzinfo=config.BOGOTA_TZ)  # a Friday evening


@pytest.fixture(autouse=True)
def isolated(isolated_files, monkeypatch):
    """Shared isolation (conftest.py), two followed accounts, and no private/ discovery results."""
    monkeypatch.setattr(config, "PRIVATE_DIR", isolated_files / "private")
    config.ACCOUNTS_FILE.write_text("academia\nnueva\n", encoding="utf-8")
    return isolated_files


@pytest.mark.parametrize(
    ("now", "expected"),
    [
        (NOW, ["2026-10-02T21:00", "2026-10-03T06:30"]),
        (datetime(2026, 10, 3, 6, 30, tzinfo=config.BOGOTA_TZ), ["2026-10-03T21:00", "2026-10-04T06:30"]),
        (datetime(2026, 10, 3, 6, 0, tzinfo=config.BOGOTA_TZ), ["2026-10-03T06:30", "2026-10-03T21:00"]),
    ],
)
def test_next_sweeps_follow_the_schedule(now, expected):
    assert [moment.isoformat(timespec="minutes")[:16] for moment in status.next_sweeps(now)] == expected


def test_the_quota_resets_at_midnight_pacific_in_bogota_time():
    # October: Pacific daylight time (UTC-7), so midnight there is 2:00 a.m. in Bogotá (UTC-5)
    assert status.quota_reset(NOW).isoformat(timespec="minutes") == "2026-10-03T02:00-05:00"


def fake_state():
    files = {
        "run_history.json": [
            {"finished_at": "2026-10-02T09:12:00-05:00", "events_new": 2, "events_merged": 1, "pending": 0},
            {
                "finished_at": "2026-10-02T21:12:00-05:00",
                "events_new": 1,
                "events_merged": 0,
                "pending": 4,
                "rate_limited": True,
                "failed_accounts": ["academia"],
                "run_url": "https://example/run",
                "instagram_usage": 90,
                "instagram_usage_detail": {"call_count": 31, "total_cputime": 90, "total_time": 77},
            },
        ],
        "gemini_usage.json": {"day": quota_day(), "requests": {"gemini-3.5-flash-lite": 120, "gemini-3.8-flash": 18}},
        "accounts.json": {"academia": {"first_seen": "2026-09-01", "backfill_done": True}},
        "processed_posts.json": {"p1": {"provisional": True}, "p2": {"provisional": False}},
    }
    return lambda name, default: files.get(name, default)


def test_collect_reads_what_the_sweeps_record():
    result = status.collect(now=NOW, instagram=None, read=fake_state())

    assert [run["finished_at"][11:16] for run in result["sweeps"]["recent"]] == ["21:12", "09:12"]  # newest first
    models = {model["model"]: model for model in result["gemini"]["models"]}
    assert models["gemini-3.5-flash-lite"]["used"] == 120
    assert models["gemini-3.8-flash"] == {
        "model": "gemini-3.8-flash",
        "role": "extraction",
        "used": 18,
        "budget": daily_budget("gemini-3.8-flash"),
    }
    assert result["accounts"] == {"followed": 2, "first_sweep_pending": ["nueva"], "waiting": []}
    assert result["posts"] == {"recorded": 2, "provisional": 1}
    assert result["instagram"] is None


def test_usage_from_an_earlier_quota_day_counts_as_zero():
    old_usage = {"day": "2020-01-01", "requests": {"gemini-3.5-flash-lite": 400}}

    def read(name, default):
        return old_usage if name == "gemini_usage.json" else default

    result = status.collect(now=NOW, instagram=None, read=read)
    assert all(model["used"] == 0 for model in result["gemini"]["models"])


def test_the_text_says_it_in_spanish():
    result = status.collect(now=NOW, instagram=lambda: {"ok": True, "error": None}, read=fake_state())
    text = status.markdown(result)

    latest = (
        "- ⚠️ hoy 9:12 p. m.: 1 nuevos, 0 unidos, 4 en espera, Instagram 90%, límite de Instagram, 1 cuenta sin leer"
    )
    assert f"{latest} · [ver](https://example/run)" in text
    assert "- ✅ hoy 9:12 a. m.: 2 nuevos, 1 unidos" in text
    assert "Próximos: hoy 9:00 p. m. y mañana 6:30 a. m." in text
    assert "| `gemini-3.8-flash` | extraction | 18 (agotado) | 18 |" in text
    assert "La cuota se reinicia mañana 2:00 a. m." in text
    # The quota is the last sweep's highest reading, with Meta's measures, not the token check's (another counter).
    assert "- Token: funciona." in text
    quota = "Cuota de Instagram en el último barrido (hoy 9:12 p. m.): 90% (CPU 90%, tiempo 77%, llamadas 31%)."
    assert f"- {quota} Se detuvo ahí: las cuentas que faltaron van primero en el siguiente." in text
    assert "1 en su primer barrido (más profundo): @nueva" in text


def test_a_sweep_meta_stopped_below_our_limit_doesnt_say_it_stopped_there():
    """The bug hunt of 7 Oct 2026: Meta's rate-limit error stops a sweep too, at any reading."""
    quota = {"usage": 45, "detail": {"call_count": 45}, "stopped": True, "finished_at": NOW.isoformat(), "stop_at": 90}
    text = status.quota_line(quota, NOW)
    assert "45% (llamadas 45%). Meta lo frenó antes, con su propio límite" in text
    assert "Se detuvo ahí" not in text
    assert "Se detuvo ahí" in status.quota_line({**quota, "usage": 91}, NOW)


def test_what_flash_changed_in_lighter_reads_is_summed_and_said():
    runs = [
        {"finished_at": "2026-10-02T09:12:00-05:00", "upgrade_changes": {"compared": 5, "dropped": 0, "start_time": 1}},
        {"finished_at": "2026-10-02T21:12:00-05:00", "upgrade_changes": {"compared": 7, "dropped": 1, "styles": 3}},
        {"finished_at": "2026-10-03T09:12:00-05:00"},  # before runs recorded it
    ]
    result = status.collect(
        now=NOW, instagram=None, read=lambda name, default: runs if name == "run_history.json" else default
    )
    assert result["lighter_reads"] == {"compared": 12, "dropped": 1, "start_time": 1, "styles": 3}
    line = "Flash releyó 12 eventos que solo había leído un modelo más liviano: "
    assert line + "la hora en 1, los ritmos en 3, no mantuvo 1." in status.markdown(result)
    assert status.collect(now=NOW, instagram=None, read=lambda name, default: default)["lighter_reads"] is None


def test_every_field_an_upgrade_compares_has_its_name_for_the_owner():
    """_FIELD_NAMES says the audited fields (sweep.AUDITED_FIELDS) in Spanish: a field audited without a name here
    would be counted on every run and never shown."""
    from pa_bailar.pipeline.sweep import AUDITED_FIELDS

    assert set(status._FIELD_NAMES) == set(AUDITED_FIELDS)


def test_accounts_past_their_turn_by_more_than_a_sweep_are_waiting():
    late = (NOW.replace(hour=8) - timedelta(days=2)).isoformat()
    fresh = NOW.replace(hour=9).isoformat()
    states = {
        "academia": {"first_seen": "2026-09-01", "backfill_done": True, "last_swept_at": late},
        "nueva": {"first_seen": "2026-09-01", "backfill_done": True, "last_swept_at": fresh},
    }
    result = status.collect(
        now=NOW, instagram=None, read=lambda name, default: states if name == "accounts.json" else default
    )
    assert result["accounts"]["waiting"] == ["academia"]
    assert "⚠️ 1 esperando más de un barrido después de su turno: @academia" in status.markdown(result)


def test_an_account_whose_posts_never_become_events_isnt_waiting_on_its_every_other_day():
    """Its turn is every other day, as the sweep counts it (pipeline.unproductive_accounts, the owner, 8 Oct 2026)."""
    read_36_hours_ago = (NOW - timedelta(hours=36)).isoformat()  # daily: 16 h late; every other day: not yet
    states = {"academia": {"first_seen": "2026-09-01", "backfill_done": True, "last_swept_at": read_36_hours_ago}}
    record = {"account": "academia", "is_event_post": False, "outcome": "not_event"}
    processed = {f"p{n}": record for n in range(config.UNPRODUCTIVE_AFTER_POSTS)}
    files = {"accounts.json": states, "processed_posts.json": processed}
    result = status.collect(now=NOW, instagram=None, read=lambda name, default: files.get(name, default))
    assert result["accounts"]["waiting"] == []
    files["processed_posts.json"] = {**processed, "p0": {**record, "outcome": "event"}}  # one event: daily again
    result = status.collect(now=NOW, instagram=None, read=lambda name, default: files.get(name, default))
    assert result["accounts"]["waiting"] == ["academia"]


@pytest.mark.parametrize(
    ("hour", "minute", "label"),
    [(0, 5, "12:05 a. m."), (9, 0, "9:00 a. m."), (12, 30, "12:30 p. m."), (21, 0, "9:00 p. m.")],
)
def test_times_read_on_a_twelve_hour_clock(hour, minute, label):
    from pa_bailar.text import clock

    assert clock(datetime(2026, 10, 4, hour, minute, tzinfo=config.BOGOTA_TZ)) == label


@pytest.mark.parametrize(
    ("hhmm", "label"), [("00:05", "12:05 a. m."), ("09:00", "9:00 a. m."), ("21:30", "9:30 p. m.")]
)
def test_stored_times_read_on_the_same_clock(hhmm, label):
    from pa_bailar.text import clock, parse_hhmm

    assert clock(parse_hhmm(hhmm)) == label


@pytest.mark.parametrize("bad", ["9", "9:00:00", "25:00", "nueve"])
def test_a_time_that_isnt_hh_mm_is_refused(bad):
    from pa_bailar.text import parse_hhmm

    with pytest.raises(ValueError):
        parse_hhmm(bad)


def test_one_day_reads_with_its_weekday():
    from pa_bailar.text import day_label

    assert day_label("2026-10-10") == "sábado 10 oct 2026"
