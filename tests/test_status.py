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
        (NOW, ["2026-10-02T21:00", "2026-10-03T09:00"]),
        (datetime(2026, 10, 3, 9, 0, tzinfo=config.BOGOTA_TZ), ["2026-10-03T21:00", "2026-10-04T09:00"]),
        (datetime(2026, 10, 3, 6, 0, tzinfo=config.BOGOTA_TZ), ["2026-10-03T09:00", "2026-10-03T21:00"]),
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
    result = status.collect(
        now=NOW, instagram=lambda: {"ok": True, "app_usage_percent": 12, "error": None}, read=fake_state()
    )
    text = status.markdown(result)

    latest = "- ⚠️ hoy 9:12 p. m.: 1 nuevos, 0 unidos, 4 en espera, límite de Instagram, 1 cuenta sin leer"
    assert f"{latest} · [ver](https://example/run)" in text
    assert "- ✅ hoy 9:12 a. m.: 2 nuevos, 1 unidos" in text
    assert "Próximos: hoy 9:00 p. m. y mañana 9:00 a. m." in text
    assert "| `gemini-3.8-flash` | extraction | 18 (agotado) | 18 |" in text
    assert "La cuota se reinicia mañana 2:00 a. m." in text
    assert "Cuota de Instagram usada: 12%" in text
    assert "1 en su primer barrido (más profundo): @nueva" in text


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
