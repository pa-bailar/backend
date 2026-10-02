"""Turn a short-lived Graph API Explorer token into a Page token that does not expire.

Only needed again if the token stops working (e.g. you changed your Facebook password).
Steps:
  1. Paste a NEW token from the Graph API Explorer into META_ACCESS_TOKEN in backend/.env.
  2. From the backend folder run:  .venv\\Scripts\\python refresh_token.py
  3. Copy the new META_ACCESS_TOKEN into the GitHub secret of the same name.
"""

import re
from datetime import datetime
from typing import Any

import requests

from pabailar import config, storage
from pabailar.instagram import InstagramClient, InstagramError

APP_ID = config.require_env("META_APP_ID")
APP_SECRET = config.require_env("META_APP_SECRET")
IG_USER_ID = config.require_env("IG_USER_ID")


def graph_get(path: str, **params: Any) -> dict[str, Any]:
    response = requests.get(f"{config.GRAPH_API_URL}/{path}", params=params, timeout=config.HTTP_TIMEOUT_SECONDS)
    data = response.json()
    if "error" in data:
        raise SystemExit(f"Meta error: {data['error'].get('message')}")
    return data


def save_token(token: str) -> None:
    """Replace META_ACCESS_TOKEN in .env, or add the line if it isn't there."""
    line = f"META_ACCESS_TOKEN={token}"
    text = config.ENV_FILE.read_text(encoding="utf-8") if config.ENV_FILE.exists() else ""
    text, replaced = re.subn(r"^META_ACCESS_TOKEN=.*$", line, text, flags=re.MULTILINE)
    if not replaced:
        text = f"{text.rstrip()}\n{line}\n" if text.strip() else f"{line}\n"
    config.ENV_FILE.write_text(text, encoding="utf-8")


def describe_expiry(token: str) -> str:
    info = graph_get("debug_token", input_token=token, access_token=f"{APP_ID}|{APP_SECRET}")["data"]
    if not info.get("is_valid"):
        return "INVALID"
    expires_at = info.get("expires_at", 0)
    return "never" if expires_at == 0 else datetime.fromtimestamp(expires_at).strftime("%Y-%m-%d %H:%M")


def main() -> None:
    short_token = config.require_env("META_ACCESS_TOKEN")

    # 1. Short-lived token -> ~60-day user token
    long_token = graph_get(
        "oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=APP_ID,
        client_secret=APP_SECRET,
        fb_exchange_token=short_token,
    )["access_token"]
    print(f"Long-lived user token: expires {describe_expiry(long_token)}")

    # 2. Long-lived user token -> token of the Page linked to your Instagram
    pages = graph_get("me/accounts", fields="name,access_token,instagram_business_account", access_token=long_token)
    page = next(
        (p for p in pages["data"] if p.get("instagram_business_account", {}).get("id") == IG_USER_ID),
        None,
    )
    if not page:
        raise SystemExit(
            "Could not find the Page linked to your Instagram. Did you select it when generating the token?"
        )
    page_token = page["access_token"]
    print(f"Page token for '{page['name']}': expires {describe_expiry(page_token)}")

    # 3. Keep the Page token if it can use Business Discovery; otherwise fall back to the 60-day token.
    test_account = storage.read_accounts()[0]
    try:
        InstagramClient(page_token, IG_USER_ID).fetch_recent_posts(test_account)
    except InstagramError as error:
        print(f"The Page token can't use Business Discovery ({error}); saving the 60-day token.")
        save_token(long_token)
        return
    save_token(page_token)
    print(f"Business Discovery works with the Page token. Saved to {config.ENV_FILE}.")


if __name__ == "__main__":
    main()
