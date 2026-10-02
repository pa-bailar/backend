"""Settings that must agree with each other (a typo would only show up mid-run)."""

from pa_bailar import config


def test_every_model_in_a_role_has_limits():
    for model in (*config.TRIAGE_MODELS, *config.EXTRACTION_MODELS, *config.PROVISIONAL_MODELS):
        assert model in config.MODEL_LIMITS, model


def test_forgotten_posts_can_never_be_fetched_again():
    assert config.PROCESSED_RETENTION_DAYS > config.BACKFILL_DAYS
    assert config.PROCESSED_RETENTION_DAYS > config.DEFAULT_LOOKBACK_DAYS


def test_today_is_bogota_time():
    assert config.now_bogota().utcoffset().total_seconds() == -5 * 3600
