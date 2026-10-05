"""tools/publish.py against a fake Graph API: no network, no sleeping, no ffprobe."""

import json
from datetime import UTC, datetime, timedelta

import publish
import pytest

TOKEN = "EAAtest-SECRET-token-123"
IG = "17840000000000001"
ENV = {"PA_BAILAR_PUBLISH_ENABLED": "1", "META_ACCESS_TOKEN": TOKEN, "IG_USER_ID": IG}
T0 = datetime(2026, 10, 5, 18, 0, tzinfo=UTC)


class FakeGraph:
    """Answers by (method, a piece of the URL path); each route takes a list of answers (the last one repeats), where
    an answer is (status, body) or an exception to raise. Records every request."""

    def __init__(self, routes: dict[tuple[str, str], list]):
        self.routes = routes
        self.calls: list[tuple[str, str, dict, bytes | None]] = []

    def send(self, method, url, headers, body, timeout):
        self.calls.append((method, url, headers, body))
        path = url.split("?")[0]
        for (m, piece), answers in self.routes.items():
            if m == method and path.endswith(piece):
                answer = answers.pop(0) if len(answers) > 1 else answers[0]
                if isinstance(answer, BaseException):
                    raise answer
                return answer
        raise AssertionError(f"unexpected request {method} {url}")

    def paths(self) -> list[str]:
        return [f"{m} {u.split('?')[0].removeprefix(publish.GRAPH + '/')}" for m, u, _, _ in self.calls]


def quota(used=1, total=50):
    return [(200, {"data": [{"quota_usage": used, "config": {"quota_total": total, "quota_duration": 86400}}]})]


def happy(kind="reel", status=None):
    return {
        ("GET", f"{IG}/content_publishing_limit"): quota(),
        ("POST", f"{IG}/media"): [(200, {"id": "C1", "uri": "https://rupload.facebook.com/ig-api-upload/v26.0/C1"})],
        ("POST", "ig-api-upload/v26.0/C1"): [(200, {"success": True, "message": "Upload successful."})],
        ("GET", "/C1"): status or [(200, {"status_code": "FINISHED", "status": "Finished: Media has been uploaded"})],
        ("POST", f"{IG}/media_publish"): [(200, {"id": "M1"})],
        ("GET", "/M1"): [
            (
                200,
                {
                    "id": "M1",
                    "permalink": f"https://www.instagram.com/{kind}/abc/",
                    "timestamp": "2026-10-05T18:01:00+0000",
                    "media_product_type": "REELS" if kind == "reel" else "STORY",
                },
            )
        ],
    }


@pytest.fixture
def render(tmp_path):
    path = tmp_path / "teaser-v2-v2.5-reel.mp4"
    path.write_bytes(b"\x00\x00\x00\x18ftypisom" + b"video" * 100)
    return path


def go(job, fake, tmp_path, *, env=ENV, confirm=True, dry_run=False, check=True, out=None):
    lines: list[str] = [] if out is None else out
    entry = publish.run(
        job,
        confirm=confirm,
        dry_run=dry_run,
        env=env,
        http=fake,
        state_path=tmp_path / "publish_state.json",
        check=lambda path, kind: check,
        sleep=lambda s: None,
        now=lambda: T0,
        out=lines.append,
    )
    return entry, lines


def state(tmp_path) -> dict:
    return json.loads((tmp_path / "publish_state.json").read_text(encoding="utf-8"))


def test_a_reel_goes_through_every_step_and_is_recorded(render, tmp_path):
    fake = FakeGraph(happy())
    job = publish.Job(render, "reel", caption="El link en mi perfil #salsa")
    entry, out = go(job, fake, tmp_path)
    assert fake.paths() == [
        f"GET {IG}/content_publishing_limit",
        f"POST {IG}/media",
        "POST https://rupload.facebook.com/ig-api-upload/v26.0/C1",
        "GET C1",  # polled until FINISHED
        "GET C1",  # right before publishing: still FINISHED (not expired)?
        f"POST {IG}/media_publish",
        "GET M1",
    ]
    create = json.loads(fake.calls[1][3])
    assert create == {
        "media_type": "REELS",
        "upload_type": "resumable",
        "share_to_feed": True,
        "caption": "El link en mi perfil #salsa",
    }
    upload = fake.calls[2][2]
    assert upload["Authorization"] == f"OAuth {TOKEN}" and upload["offset"] == "0"
    assert upload["file_size"] == str(render.stat().st_size) and fake.calls[2][3] == render.read_bytes()
    assert all(TOKEN not in url for _, url, _, _ in fake.calls)  # the token travels in a header only
    assert entry["status"] == "published" and entry["permalink"] == "https://www.instagram.com/reel/abc/"
    saved = state(tmp_path)["renders"]
    (key,) = saved
    assert key == f"{publish.sha256(render)}:{IG}:reel"
    assert saved[key]["container_id"] == "C1" and saved[key]["media_id"] == "M1" and saved[key]["attempts"] == 1
    assert [h["status"] for h in saved[key]["history"]] == [
        "new",
        "creating",
        "created",
        "uploaded",
        "finished",
        "publishing",
        "verifying",
        "published",
    ]
    assert any("published: https://www.instagram.com/reel/abc/" in line for line in out)


def test_a_story_has_no_caption_or_feed_and_takes_a_video_url(render, tmp_path):
    fake = FakeGraph(happy("story"))
    job = publish.Job(render, "story", video_url="https://example.org/story.mp4")
    entry, _ = go(job, fake, tmp_path)
    assert json.loads(fake.calls[1][3]) == {"media_type": "STORIES", "video_url": "https://example.org/story.mp4"}
    assert not any("rupload" in url for _, url, _, _ in fake.calls)  # Meta fetches the URL: nothing uploaded
    assert entry["status"] == "published"
    with pytest.raises(SystemExit, match="no caption"):
        publish.read_caption(render, "story")


def test_a_published_render_is_never_published_again(render, tmp_path):
    job = publish.Job(render, "reel")
    go(job, FakeGraph(happy()), tmp_path)
    again = FakeGraph({})  # any request would fail the test
    entry, out = go(job, again, tmp_path)
    assert again.calls == [] and entry["media_id"] == "M1"
    assert any("already published: https://www.instagram.com/reel/abc/" in line for line in out)


def test_a_container_in_progress_is_resumed_not_recreated(render, tmp_path):
    job = publish.Job(render, "reel")
    slow = [(200, {"status_code": "IN_PROGRESS", "status": "processing"})]
    with pytest.raises(SystemExit, match="still processing"):
        go(job, FakeGraph(happy(status=slow)), tmp_path)
    assert next(iter(state(tmp_path)["renders"].values()))["status"] == "uploaded"
    fake = FakeGraph(happy())
    entry, _ = go(job, fake, tmp_path)
    assert fake.paths()[0] == "GET C1"  # straight to polling the same container
    assert not any(p.endswith(f"{IG}/media") or "rupload" in p for p in fake.paths())
    assert entry["status"] == "published" and entry["container_id"] == "C1" and entry["attempts"] == 1


def test_an_error_status_fails_closed_with_the_error(render, tmp_path):
    error = [(200, {"status_code": "ERROR", "status": "Error: 2207026 unsupported video format"})]
    fake = FakeGraph(happy(status=error))
    with pytest.raises(SystemExit, match="ERROR: Error: 2207026"):
        go(publish.Job(render, "reel"), fake, tmp_path)
    assert not any("media_publish" in p for p in fake.paths())
    entry = next(iter(state(tmp_path)["renders"].values()))
    assert entry["status"] == "failed" and "2207026" in entry["error"]
    # The next run starts a new container (the failed one can't be published), counting the attempt.
    fake = FakeGraph(happy())
    entry, _ = go(publish.Job(render, "reel"), fake, tmp_path)
    assert entry["attempts"] == 2 and "2207026" in entry["previous_error"]


def test_an_expired_container_fails_closed(render, tmp_path):
    expired = [(200, {"status_code": "EXPIRED", "status": ""})]
    with pytest.raises(SystemExit, match="EXPIRED"):
        go(publish.Job(render, "reel"), FakeGraph(happy(status=expired)), tmp_path)


def test_a_used_up_quota_refuses_before_any_container(render, tmp_path):
    routes = happy()
    routes[("GET", f"{IG}/content_publishing_limit")] = quota(used=50, total=50)
    fake = FakeGraph(routes)
    with pytest.raises(SystemExit, match="quota is used up"):
        go(publish.Job(render, "reel"), fake, tmp_path)
    assert fake.paths() == [f"GET {IG}/content_publishing_limit"]


def test_a_lost_publish_answer_is_checked_and_never_posted_twice(render, tmp_path):
    routes = happy()
    routes[("POST", f"{IG}/media_publish")] = [publish.GraphError("connection reset", ambiguous=True)]
    published = [
        (200, {"status_code": "FINISHED"}),  # wait()
        (200, {"status_code": "FINISHED"}),  # publish(): still publishable
        (200, {"status_code": "PUBLISHED"}),  # reconcile(): it went out after all
    ]
    routes[("GET", "/C1")] = published
    recent = {
        "id": "M1",
        "timestamp": (T0 + timedelta(seconds=20)).strftime("%Y-%m-%dT%H:%M:%S+0000"),
        "media_product_type": "REELS",
        "caption": "Hola",
    }
    older = recent | {"id": "M0", "timestamp": "2026-10-01T10:00:00+0000"}
    routes[("GET", f"{IG}/media")] = [(200, {"data": [recent, older]})]
    fake = FakeGraph(routes)
    entry, out = go(publish.Job(render, "reel", caption="Hola"), fake, tmp_path)
    assert [p for p in fake.paths() if "media_publish" in p] == [f"POST {IG}/media_publish"]  # once
    assert entry["status"] == "published" and entry["media_id"] == "M1"
    assert any("found it among the recent posts" in line for line in out)


def test_a_lost_answer_that_did_not_post_publishes_once_more_only(render, tmp_path):
    routes = happy()
    lost = publish.GraphError("timed out", ambiguous=True)
    routes[("POST", f"{IG}/media_publish")] = [lost, (200, {"id": "M1"})]
    routes[("GET", f"{IG}/media")] = [(200, {"data": []})]  # nothing new on the account: it wasn't posted
    fake = FakeGraph(routes)
    entry, _ = go(publish.Job(render, "reel"), fake, tmp_path)
    assert [p for p in fake.paths() if "media_publish" in p] == [f"POST {IG}/media_publish"] * 2
    assert entry["status"] == "published"
    # Answers that keep getting lost: it stops after MAX_PUBLISH_TRIES, never a third call.
    (tmp_path / "publish_state.json").unlink()
    routes = happy()
    routes[("POST", f"{IG}/media_publish")] = [lost]
    routes[("GET", f"{IG}/media")] = [(200, {"data": []})]
    fake = FakeGraph(routes)
    with pytest.raises(SystemExit, match="keep getting lost"):
        go(publish.Job(render, "reel"), fake, tmp_path)
    assert len([p for p in fake.paths() if "media_publish" in p]) == publish.MAX_PUBLISH_TRIES


def test_a_crash_during_publish_resumes_by_checking_first(render, tmp_path):
    job = publish.Job(render, "reel", caption="Hola")
    routes = happy()
    routes[("POST", f"{IG}/media_publish")] = [KeyboardInterrupt()]  # the process dies mid-call
    with pytest.raises(KeyboardInterrupt):
        go(job, FakeGraph(routes), tmp_path)
    assert next(iter(state(tmp_path)["renders"].values()))["status"] == "publishing"
    routes = happy(status=[(200, {"status_code": "PUBLISHED"})])
    item = {"id": "M9", "timestamp": "2026-10-05T18:00:30+0000", "media_product_type": "REELS", "caption": "Hola"}
    routes[("GET", f"{IG}/media")] = [(200, {"data": [item]})]
    routes[("GET", "/M9")] = [(200, {"id": "M9", "permalink": "https://www.instagram.com/reel/m9/"})]
    fake = FakeGraph(routes)
    entry, _ = go(job, fake, tmp_path)
    assert not any("media_publish" in p for p in fake.paths())
    assert entry["media_id"] == "M9" and entry["permalink"] == "https://www.instagram.com/reel/m9/"


def test_the_gate_refuses_without_the_flag_and_the_confirm_flag(render, tmp_path):
    job = publish.Job(render, "reel")
    fake = FakeGraph({})
    off = {k: v for k, v in ENV.items() if k != "PA_BAILAR_PUBLISH_ENABLED"}
    with pytest.raises(SystemExit, match="disabled"):
        go(job, fake, tmp_path, env=off)
    with pytest.raises(SystemExit, match="disabled"):
        go(job, fake, tmp_path, env=off | {"PA_BAILAR_PUBLISH_ENABLED": "true"})
    entry, out = go(job, fake, tmp_path, confirm=False)  # enabled, but no --confirm: a dry run
    assert entry is None and fake.calls == [] and "no --confirm" in out[0]
    assert not (tmp_path / "publish_state.json").exists()


def test_a_dry_run_makes_no_calls_and_redacts_the_token(render, tmp_path):
    fake = FakeGraph({})
    entry, out = go(publish.Job(render, "reel", caption="Hola"), fake, tmp_path, dry_run=True)
    text = "\n".join(out)
    assert entry is None and fake.calls == []
    assert "content_publishing_limit" in text and "media_publish" in text and "rupload.facebook.com" in text
    assert "Bearer ***" in text and "OAuth ***" in text and TOKEN not in text and IG not in text


def test_a_failing_preflight_refuses_before_anything(render, tmp_path):
    fake = FakeGraph({})
    with pytest.raises(SystemExit, match="pre-flight"):
        go(publish.Job(render, "reel"), fake, tmp_path, check=False)
    assert fake.calls == []


def test_the_token_never_reaches_the_output_or_the_state(render, tmp_path):
    routes = happy()
    echo = (400, {"error": {"message": f"Invalid token {TOKEN} in access_token={TOKEN}", "code": 190}})
    routes[("POST", f"{IG}/media_publish")] = [echo]
    out: list[str] = []
    with pytest.raises(SystemExit) as stop:
        go(publish.Job(render, "reel"), FakeGraph(routes), tmp_path, out=out)
    assert TOKEN not in str(stop.value) and "***" in str(stop.value)
    assert TOKEN not in "\n".join(out)
    raw = (tmp_path / "publish_state.json").read_text(encoding="utf-8")
    assert TOKEN not in raw
    # Meta refused it (a definite error): nothing was posted, the container stays ready to publish.
    assert json.loads(raw)["renders"].popitem()[1]["status"] == "finished"
    entry, out = go(publish.Job(render, "reel"), FakeGraph(happy()), tmp_path, out=[])
    assert entry["status"] == "published" and TOKEN not in (tmp_path / "publish_state.json").read_text("utf-8")


def test_captions_and_the_graph_version():
    assert publish.caption_problems("hola #salsa @pabailar") == []
    assert publish.caption_problems("x" * 2201) == ["2201 characters (at most 2200)"]
    assert publish.caption_problems(" ".join(f"#t{i}" for i in range(31))) == ["31 hashtags (at most 30)"]
    assert publish.kind_of("reel", None) == "reel" and publish.kind_of("voice-only", None) == "story"
    from pa_bailar import config

    assert config.GRAPH_API_URL == publish.GRAPH  # the same API version as the sweep
