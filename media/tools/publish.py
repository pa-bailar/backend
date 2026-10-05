"""Publish a render to Instagram through Meta's official Graph API (Instagram API with Facebook Login). DISABLED:
nothing reaches Meta unless the environment has PA_BAILAR_PUBLISH_ENABLED=1 *and* --confirm is given.

  .venv/Scripts/python media/tools/publish.py <video> <deliverable> [--story | --reel] [--caption-file <txt>]
        [--no-feed] [--thumb-offset <ms>] [--video-url <url>] [--dry-run] [--confirm]

  --dry-run (the default without --confirm) prints every request it would make, the token redacted, and calls
  nothing. --story / --reel: the kind (default: "reel" in the deliverable's name). --caption-file: a Reel's caption
  (UTF-8; at most 2,200 characters, 30 hashtags, 20 @ tags). --no-feed: the Reel in the Reels tab only (default: Feed
  too). --thumb-offset: the cover frame in ms (cover.py's --at). --video-url: instead of uploading the file, Meta
  fetches it from this public URL (it must serve exactly this render).

The steps, each writing publish_state.json in the media home before and after it, so a crash anywhere resumes:
  1. preflight.py --api on the render: refuses on a failure.
  2. idempotency: the state is keyed by the render's sha256 + the account + the kind. A render already published is
     never published again (it prints where it is); a container already made is resumed (polled), not made again.
  3. GET /<ig>/content_publishing_limit: refuses when the quota is used up (no container is made).
  4. POST /<ig>/media: media_type REELS (caption, share_to_feed, thumb_offset) or STORIES (no caption: the API can't
     add stickers, so a Story with a link sticker stays a manual post), upload_type=resumable (or video_url).
  5. the file to rupload.facebook.com/ig-api-upload/<version>/<container> (Authorization: OAuth, offset 0, file_size).
  6. GET /<container>?fields=status_code,status with backoff (5 s up to a minute apart, about 5 minutes in all, as Meta
     advises) until FINISHED; ERROR or EXPIRED stops with the error (fail closed); still IN_PROGRESS: run it again.
  7. POST /<ig>/media_publish creation_id=<container>.
  8. GET /<media>?fields=id,permalink,timestamp,media_product_type: marked published.
An ambiguous publish answer (a dropped connection, a 5xx) is checked against the container (PUBLISHED?) and the
account's recent media before any retry: never two posts.

Credentials: PA_BAILAR_PUBLISH_TOKEN if set (a token only for publishing), else META_ACCESS_TOKEN (the sweep's); and
IG_USER_ID; from the environment or the backend's .env (common.load_env). The token travels in an Authorization header
(never in a URL), and is never printed or stored. The app needs instagram_basic, instagram_content_publish and
pages_read_engagement (Facebook Login for Business; resumable upload needs it). README.md "Publishing (disabled)".
Standard library only.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from common import HOME, load_env, shown, video

# The backend's config.GRAPH_API_URL (a test keeps them equal); the account uses Facebook Login: graph.facebook.com.
GRAPH_VERSION = "v26.0"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
RUPLOAD = f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}"
STATE = HOME / "publish_state.json"
ENABLE = "PA_BAILAR_PUBLISH_ENABLED"
# Seconds between status checks: about 5 minutes in all (Meta: "once per minute, for no more than 5 minutes").
POLL = (5, 10, 15, 30, 60, 60, 60, 60)
CAPTION = {"chars": 2200, "hashtags": 30, "mentions": 20}  # the IG User Media reference
RECENT_SLACK = timedelta(minutes=5)  # how far before the publish request a recent post may be ours (clock skew)
MAX_PUBLISH_TRIES = 2  # media_publish calls per run; a second only after checking the first didn't post
TIMEOUT = 60
UPLOAD_TIMEOUT = 600


class GraphError(RuntimeError):
    """Meta answered with an error (`ambiguous` False), or the answer was lost (a dropped connection, a 5xx)."""

    def __init__(self, message: str, code: int | None = None, ambiguous: bool = False):
        super().__init__(message)
        self.code = code
        self.ambiguous = ambiguous


class Http(Protocol):
    def send(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, dict[str, Any]]: ...


class UrllibHttp:
    """The real HTTP layer (urllib): (status, JSON body). A lost answer raises GraphError(ambiguous=True)."""

    def send(
        self, method: str, url: str, headers: dict[str, str], body: bytes | None, timeout: float
    ) -> tuple[int, dict[str, Any]]:
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # https only: graph and rupload
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as error:
            status, raw = error.code, error.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
            raise GraphError(f"no answer from {urllib.parse.urlsplit(url).netloc}: {error}", ambiguous=True) from error
        try:
            payload = json.loads(raw or b"{}")
        except ValueError:
            payload = {"_raw": raw[:200].decode("utf-8", "replace")}
        return status, payload if isinstance(payload, dict) else {"data": payload}


def redact(text: str, secrets: list[str]) -> str:
    """Text without the token (and any access_token=… a Graph URL might quote)."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return re.sub(r"(access_token=)[^&\s'\"]+", r"\1***", text)


class Graph:
    """Graph API calls with the token in a header; every request is printed first, redacted."""

    def __init__(self, http: Http, token: str, ig_user_id: str, out: Callable[[str], None] = print):
        self.http, self.token, self.ig, self.out = http, token, ig_user_id, out

    def call(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        body: dict[str, Any] | None = None,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = TIMEOUT,
    ) -> dict[str, Any]:
        url = path if path.startswith("https://") else f"{GRAPH}/{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        sent = {"Authorization": f"Bearer {self.token}", **(headers or {})}
        payload = data
        if body is not None:
            sent["Content-Type"] = "application/json"
            payload = json.dumps(body).encode()
        self.out(redact(f"→ {describe(method, url, body, data, sent)}", [self.token]))
        try:
            status, answer = self.http.send(method, url, sent, payload, timeout)
        except GraphError as error:
            raise GraphError(redact(str(error), [self.token]), error.code, error.ambiguous) from None
        if "error" in answer:
            err = answer["error"] if isinstance(answer["error"], dict) else {"message": str(answer["error"])}
            message = redact(str(err.get("error_user_msg") or err.get("message") or "unknown error"), [self.token])
            raise GraphError(message, err.get("code"), ambiguous=status >= 500)
        if status >= 400:
            raise GraphError(
                f"HTTP {status}: {redact(json.dumps(answer)[:200], [self.token])}", ambiguous=status >= 500
            )
        return answer


def describe(method: str, url: str, body: dict | None, data: bytes | None, headers: dict[str, str]) -> str:
    """One request as a line, headers that matter included (redact() takes the token out)."""
    shown_headers = {k: v for k, v in headers.items() if k not in ("Content-Type",)}
    line = f"{method} {url}"
    if body is not None:
        line += f" {json.dumps(body, ensure_ascii=False)}"
    if data is not None:
        line += f" <the file, {len(data)} bytes>"
    return line + f"  [{', '.join(f'{k}: {v}' for k, v in shown_headers.items())}]"


# ---------- the job and its state ----------


@dataclass
class Job:
    path: Path
    kind: str  # "reel" or "story"
    caption: str = ""
    share_to_feed: bool = True
    thumb_offset: int | None = None
    video_url: str | None = None

    @property
    def media_type(self) -> str:
        return "REELS" if self.kind == "reel" else "STORIES"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def caption_problems(text: str) -> list[str]:
    """What the API would refuse in a caption (the IG User Media reference)."""
    out = []
    if len(text) > CAPTION["chars"]:
        out.append(f"{len(text)} characters (at most {CAPTION['chars']})")
    if (n := len(re.findall(r"#\w", text))) > CAPTION["hashtags"]:
        out.append(f"{n} hashtags (at most {CAPTION['hashtags']})")
    if (n := len(re.findall(r"@\w", text))) > CAPTION["mentions"]:
        out.append(f"{n} @ tags (at most {CAPTION['mentions']})")
    return out


def now_utc() -> datetime:
    return datetime.now(UTC)


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse_time(text: str) -> datetime:
    """The Graph API's "2026-10-01T23:56:57+0000", or our own ISO stamps."""
    return datetime.fromisoformat(re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", text))


class State:
    """publish_state.json: {"renders": {"<sha256>:<account>:<kind>": entry}}, written whole (temp file, replace)."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"version": 1, "renders": {}}
        )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(self.data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, self.path)

    def entry(self, key: str) -> dict[str, Any] | None:
        return self.data["renders"].get(key)

    def put(self, key: str, entry: dict[str, Any]) -> None:
        self.data["renders"][key] = entry

    def media_ids(self, but: str) -> set[str]:
        """Media already claimed by other renders (a recent post that's theirs isn't ours)."""
        return {e["media_id"] for k, e in self.data["renders"].items() if k != but and e.get("media_id")}


def state_key(digest: str, account: str, kind: str) -> str:
    return f"{digest}:{account}:{kind}"


# ---------- the publisher ----------


class Refused(SystemExit):
    """Stopped on purpose (a gate, the quota, a failed container): nothing more was sent."""


class Publisher:
    """Runs a job from wherever its state left off: new → creating → created → uploaded → finished → publishing →
    verifying → published (or failed). Every transition is saved before the next call."""

    def __init__(
        self,
        graph: Graph,
        state: State,
        job: Job,
        digest: str,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = now_utc,
        out: Callable[[str], None] = print,
    ):
        self.g, self.state, self.job, self.sleep, self.now, self.out = graph, state, job, sleep, now, out
        self.key = state_key(digest, graph.ig, job.kind)
        self.digest = digest
        self.tries = 0

    # -- state --

    def mark(self, entry: dict[str, Any], status: str, **fields: Any) -> dict[str, Any]:
        entry.update(fields, status=status, updated=stamp(self.now()))
        entry.setdefault("history", []).append({"at": entry["updated"], "status": status})
        self.state.put(self.key, entry)
        self.state.save()
        return entry

    def start(self) -> dict[str, Any]:
        entry = self.state.entry(self.key)
        if entry is not None and entry["status"] != "failed":
            return entry
        fresh = {
            "file": self.job.path.name,
            "sha256": self.digest,
            "account": self.g.ig,
            "kind": self.job.kind,
            "created": stamp(self.now()),
            "attempts": (entry or {}).get("attempts", 0),
            "history": (entry or {}).get("history", []),
        }
        if entry is not None:
            fresh["previous_error"] = entry.get("error")
        return self.mark(fresh, "new")

    def run(self) -> dict[str, Any]:
        entry = self.start()
        steps: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
            "new": self.create,
            "creating": self.create,  # a crash mid-call: the container id was lost; an orphan expires in 24 h
            "created": self.upload,
            "uploaded": self.wait,
            "finished": self.publish,
            "publishing": self.reconcile,
            "verifying": self.verify,
        }
        if entry["status"] == "published":
            self.out(f"already published: {entry.get('permalink') or entry.get('media_id')} ({entry.get('timestamp')})")
            return entry
        self.out(f"{self.job.path.name} ({self.job.kind}): {entry['status']}")
        while entry["status"] != "published":
            entry = steps[entry["status"]](entry)
        self.out(f"published: {entry.get('permalink') or entry.get('media_id')} ({entry.get('timestamp')})")
        return entry

    def fail(self, entry: dict[str, Any], error: str) -> None:
        self.mark(entry, "failed", error=error)
        raise Refused(f"failed: {error} (state: {shown(self.state.path)}; run again for a new container)")

    # -- steps --

    def quota(self) -> None:
        answer = self.g.call("GET", f"{self.g.ig}/content_publishing_limit", params={"fields": "config,quota_usage"})
        row = (answer.get("data") or [{}])[0]
        used, total = row.get("quota_usage"), (row.get("config") or {}).get("quota_total")
        if not isinstance(used, int) or not isinstance(total, int):
            raise Refused(f"refusing: content_publishing_limit gave no quota_usage/quota_total ({answer})")
        hours = (row.get("config") or {}).get("quota_duration", 86400) / 3600
        self.out(f"  publishing quota: {used} of {total} in {hours:.0f} h")
        if used >= total:
            raise Refused(f"refusing: the publishing quota is used up ({used} of {total} in {hours:.0f} h)")

    def create(self, entry: dict[str, Any]) -> dict[str, Any]:
        self.quota()
        params: dict[str, Any] = {"media_type": self.job.media_type}
        if self.job.video_url:
            params["video_url"] = self.job.video_url
        else:
            params["upload_type"] = "resumable"
        if self.job.kind == "reel":
            params["share_to_feed"] = self.job.share_to_feed
            if self.job.caption:
                params["caption"] = self.job.caption
            if self.job.thumb_offset is not None:
                params["thumb_offset"] = self.job.thumb_offset
        entry = self.mark(entry, "creating", attempts=entry.get("attempts", 0) + 1)
        answer = self.g.call("POST", f"{self.g.ig}/media", body=params)
        container = str(answer.get("id") or "")
        if not container:
            self.fail(entry, f"container creation answered without an id: {answer}")
        status = "uploaded" if self.job.video_url else "created"
        return self.mark(entry, status, container_id=container, upload_uri=answer.get("uri"))

    def upload(self, entry: dict[str, Any]) -> dict[str, Any]:
        data = self.job.path.read_bytes()
        url = entry.get("upload_uri") or f"{RUPLOAD}/{entry['container_id']}"
        headers = {"Authorization": f"OAuth {self.g.token}", "offset": "0", "file_size": str(len(data))}
        answer = self.g.call("POST", url, data=data, headers=headers, timeout=UPLOAD_TIMEOUT)
        if answer.get("success") is not True:
            raise Refused(f"upload not confirmed: {answer} (run again: it uploads again to the same container)")
        return self.mark(entry, "uploaded")

    def status(self, entry: dict[str, Any]) -> tuple[str, str]:
        answer = self.g.call("GET", entry["container_id"], params={"fields": "status_code,status"})
        return str(answer.get("status_code") or ""), str(answer.get("status") or "")

    def settle(self, entry: dict[str, Any], code: str, detail: str) -> dict[str, Any] | None:
        """The next state for a container status, or None while it's still processing."""
        if code == "FINISHED":
            return self.mark(entry, "finished")
        if code == "PUBLISHED":
            return self.mark(entry, "publishing", publish_requested=entry.get("publish_requested") or entry["created"])
        if code in ("ERROR", "EXPIRED"):
            self.fail(entry, f"container {entry['container_id']} {code}: {detail or 'no detail'}")
        return None

    def wait(self, entry: dict[str, Any]) -> dict[str, Any]:
        for pause in (0, *POLL):
            self.sleep(pause)
            code, detail = self.status(entry)
            if (done := self.settle(entry, code, detail)) is not None:
                return done
            self.out(f"  {code or 'no status'}: {detail}")
        raise Refused(f"container {entry['container_id']} still processing after ~5 min: run again to resume")

    def publish(self, entry: dict[str, Any]) -> dict[str, Any]:
        # The container may have expired (24 h) or been published since the state was saved.
        code, detail = self.status(entry)
        if code != "FINISHED":
            return self.settle(entry, code, detail) or self.mark(entry, "uploaded")
        if self.tries >= MAX_PUBLISH_TRIES:
            raise Refused("publish answers keep getting lost: stopping (run again later; it checks before retrying)")
        self.tries += 1
        entry = self.mark(entry, "publishing", publish_requested=stamp(self.now()))
        try:
            answer = self.g.call("POST", f"{self.g.ig}/media_publish", body={"creation_id": entry["container_id"]})
        except GraphError as error:
            if error.ambiguous:
                self.out(f"  the publish answer was lost ({error}): checking before anything else")
                return self.reconcile(entry)
            self.mark(entry, "finished", error=str(error))  # Meta refused it: nothing was posted
            raise Refused(f"media_publish refused: {error}") from None
        if not answer.get("id"):
            self.out(f"  media_publish answered without an id ({answer}): checking before anything else")
            return self.reconcile(entry)
        return self.mark(entry, "verifying", media_id=str(answer["id"]))

    def reconcile(self, entry: dict[str, Any]) -> dict[str, Any]:
        """After a lost publish answer (or a crash during one): was it posted? Never publish twice."""
        code, detail = self.status(entry)
        media = self.find_recent(entry)
        if media:
            self.out(f"  found it among the recent posts: {media}")
            return self.mark(entry, "verifying", media_id=media)
        if code == "PUBLISHED":
            # Posted, but not (yet) in the recent list: stop rather than guess.
            raise Refused(f"container {entry['container_id']} is PUBLISHED but its post isn't listed yet: run again")
        if code == "FINISHED":
            return self.mark(entry, "finished")  # not posted: publish may run again (MAX_PUBLISH_TRIES per run)
        return self.settle(entry, code, detail) or self.mark(entry, "uploaded")

    def find_recent(self, entry: dict[str, Any]) -> str | None:
        """Our post among the account's recent ones: published since the request (less a slack for clocks), the same
        kind, and for a Reel the same caption; not one another render already claimed."""
        edge = "media" if self.job.kind == "reel" else "stories"
        fields = "id,timestamp,media_product_type" + (",caption" if self.job.kind == "reel" else "")
        answer = self.g.call("GET", f"{self.g.ig}/{edge}", params={"fields": fields, "limit": 10})
        since = parse_time(entry.get("publish_requested") or entry["created"]) - RECENT_SLACK
        taken = self.state.media_ids(self.key)
        product = "REELS" if self.job.kind == "reel" else "STORY"
        for item in answer.get("data", []):
            if item.get("id") in taken or item.get("media_product_type") != product:
                continue
            if "timestamp" not in item or parse_time(item["timestamp"]) < since:
                continue
            if self.job.kind == "reel" and (item.get("caption") or "").strip() != self.job.caption.strip():
                continue
            return str(item["id"])
        return None

    def verify(self, entry: dict[str, Any]) -> dict[str, Any]:
        answer = self.g.call("GET", entry["media_id"], params={"fields": "id,permalink,timestamp,media_product_type"})
        return self.mark(
            entry,
            "published",
            permalink=answer.get("permalink"),
            timestamp=answer.get("timestamp"),
            media_product_type=answer.get("media_product_type"),
            error=None,
        )


# ---------- the dry run ----------


def plan(job: Job, entry: dict[str, Any] | None, size: int, ig_set: bool, token_set: bool) -> list[str]:
    """The requests a confirmed run would make from this state, with placeholders and the token as ***."""
    ig = "<IG_USER_ID>"
    auth = "[Authorization: Bearer ***]"
    status = (entry or {}).get("status", "new")
    if status == "published":
        return [f"nothing: already published ({(entry or {}).get('permalink') or (entry or {}).get('media_id')})"]
    container = (entry or {}).get("container_id") or "<container id>"
    lines = [
        f"credentials: IG_USER_ID {'set' if ig_set else 'MISSING'}, token {'set' if token_set else 'MISSING'}",
        f"state: {status}" + (f" (container {container})" if entry and entry.get("container_id") else ""),
    ]
    if status in ("new", "creating", "failed"):
        params: dict[str, Any] = {"media_type": job.media_type}
        params |= {"video_url": job.video_url} if job.video_url else {"upload_type": "resumable"}
        if job.kind == "reel":
            params["share_to_feed"] = job.share_to_feed
            if job.caption:
                params["caption"] = job.caption
            if job.thumb_offset is not None:
                params["thumb_offset"] = job.thumb_offset
        lines += [
            f"GET {GRAPH}/{ig}/content_publishing_limit?fields=config%2Cquota_usage  {auth}",
            f"POST {GRAPH}/{ig}/media {json.dumps(params, ensure_ascii=False)}  {auth}",
        ]
    if status in ("new", "creating", "failed", "created") and not job.video_url:
        lines.append(
            f"POST {RUPLOAD}/{container} <the file, {size} bytes>  [Authorization: OAuth ***, offset: 0, "
            f"file_size: {size}]"
        )
    lines += [
        f"GET {GRAPH}/{container}?fields=status_code%2Cstatus  {auth}  (until FINISHED: 5 s, then up to a minute "
        "apart, ~5 min)",
        f'POST {GRAPH}/{ig}/media_publish {{"creation_id": "{container}"}}  {auth}',
        f"GET {GRAPH}/<media id>?fields=id%2Cpermalink%2Ctimestamp%2Cmedia_product_type  {auth}",
    ]
    return lines


# ---------- entry point ----------


def credentials(env: dict[str, str]) -> tuple[str, str]:
    token = (env.get("PA_BAILAR_PUBLISH_TOKEN") or env.get("META_ACCESS_TOKEN") or "").strip()
    ig = (env.get("IG_USER_ID") or "").strip()
    return token, ig


def kind_of(name: str, flag: str | None) -> str:
    return flag or ("reel" if "reel" in name.lower() else "story")


def read_caption(path: Path | None, kind: str) -> str:
    if path is None:
        return ""
    if kind == "story":
        raise SystemExit("a Story takes no caption through the API: drop --caption-file")
    text = path.read_text(encoding="utf-8-sig").strip()  # -sig: Notepad's byte order mark isn't caption
    if problems := caption_problems(text):
        raise SystemExit(f"the caption won't pass: {', '.join(problems)}")
    return text


def run(
    job: Job,
    *,
    confirm: bool,
    dry_run: bool,
    env: dict[str, str],
    http: Http | None = None,
    state_path: Path = STATE,
    check: Callable[[Path, str], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], datetime] = now_utc,
    out: Callable[[str], None] = print,
) -> dict[str, Any] | None:
    """The whole flow behind the gate. Returns the state entry (None for a dry run)."""
    live = confirm and not dry_run
    if live and env.get(ENABLE, "").strip() != "1":
        raise Refused(f"refusing: publishing is disabled ({ENABLE}=1 isn't set). README.md: Publishing (disabled)")
    if check is None:
        import preflight

        check = lambda path, kind: preflight.check(path, kind, api=True)  # noqa: E731
    if not check(job.path, job.kind):
        raise Refused("refusing: the render fails Instagram's pre-flight (above)")
    digest = sha256(job.path)
    token, ig = credentials(env)
    state = State(state_path)
    if not live:
        entry = state.entry(state_key(digest, ig, job.kind)) if ig else None
        why = "--dry-run" if dry_run else "no --confirm"
        out(f"dry run ({why}): nothing is sent. A confirmed run would make these requests:")
        for line in plan(job, entry, job.path.stat().st_size, bool(ig), bool(token)):
            out(f"  {redact(line, [token])}")
        return None
    if not token or not ig:
        names = (("META_ACCESS_TOKEN (or PA_BAILAR_PUBLISH_TOKEN)", token), ("IG_USER_ID", ig))
        missing = [name for name, value in names if not value]
        raise Refused(f"refusing: {' and '.join(missing)} not set (the backend's .env or the environment)")
    graph = Graph(http or UrllibHttp(), token, ig, out=out)
    try:
        return Publisher(graph, state, job, digest, sleep=sleep, now=now, out=out).run()
    except GraphError as error:
        raise Refused(f"stopped: {error} (state kept in {shown(state_path)}; run again to resume)") from None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video")
    parser.add_argument("deliverable")
    kind = parser.add_mutually_exclusive_group()
    kind.add_argument("--story", dest="kind", action="store_const", const="story")
    kind.add_argument("--reel", dest="kind", action="store_const", const="reel")
    parser.add_argument("--caption-file", type=Path)
    parser.add_argument("--no-feed", action="store_true", help="a Reel in the Reels tab only")
    parser.add_argument("--thumb-offset", type=int, help="the cover frame, in ms")
    parser.add_argument("--video-url", help="a public URL serving exactly this render (instead of uploading it)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    v = video(args.video)
    if args.deliverable not in v.settings["renders"]:
        raise SystemExit(f"unknown deliverable {args.deliverable}: video.json has {list(v.settings['renders'])}")
    path = v.render(args.deliverable)
    if not path.exists():
        raise SystemExit(f"no {shown(path)}: render it first (render.py {args.video} {args.deliverable})")
    kind = kind_of(args.deliverable, args.kind)
    if args.video_url and not args.video_url.startswith("https://"):
        raise SystemExit("--video-url must be an https:// URL Meta can fetch")
    job = Job(path, kind, read_caption(args.caption_file, kind), not args.no_feed, args.thumb_offset, args.video_url)
    load_env()
    run(job, confirm=args.confirm, dry_run=args.dry_run, env=dict(os.environ))


if __name__ == "__main__":
    try:
        main()
    except Refused as stop:
        print(stop, file=sys.stderr)
        raise SystemExit(1) from None
