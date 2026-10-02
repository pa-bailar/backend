"""Turn a short-lived Graph API Explorer token into a Page token that does not expire.

Only needed again if the token stops working (e.g. you changed your Facebook password).
Steps:
  1. Paste a NEW token from the Graph API Explorer into META_ACCESS_TOKEN in backend/.env.
  2. From the backend folder run:  .venv\\Scripts\\python tools\\refresh_token.py
The Page token is saved back into META_ACCESS_TOKEN.
"""

import os
import re
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

ENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV)
API = "https://graph.facebook.com/v26.0"
APP_ID = os.environ["META_APP_ID"]
APP_SECRET = os.environ["META_APP_SECRET"]
IG_USER_ID = os.environ["IG_USER_ID"]


def get(url: str, **params) -> dict:
    data = requests.get(url, params=params, timeout=30).json()
    if "error" in data:
        raise SystemExit(f"Meta error: {data['error'].get('message')}")
    return data


def save_token(token: str):
    text = ENV.read_text(encoding="utf-8")
    text = re.sub(r"^META_ACCESS_TOKEN=.*$", f"META_ACCESS_TOKEN={token}", text, flags=re.M)
    ENV.write_text(text, encoding="utf-8")


def expiry(token: str) -> str:
    info = get(f"{API}/debug_token", input_token=token, access_token=f"{APP_ID}|{APP_SECRET}")["data"]
    if not info.get("is_valid"):
        return "INVALID"
    expires = info.get("expires_at", 0)
    return "never" if expires == 0 else datetime.fromtimestamp(expires).strftime("%Y-%m-%d %H:%M")


def main():
    short_token = os.environ["META_ACCESS_TOKEN"]

    # 1. Short-lived token -> ~60-day user token
    long_token = get(
        f"{API}/oauth/access_token",
        grant_type="fb_exchange_token",
        client_id=APP_ID,
        client_secret=APP_SECRET,
        fb_exchange_token=short_token,
    )["access_token"]
    print(f"Long-lived user token: expires {expiry(long_token)}")

    # 2. Long-lived user token -> token of the Page linked to your Instagram
    pages = get(f"{API}/me/accounts", fields="name,access_token,instagram_business_account", access_token=long_token)["data"]
    page = next((p for p in pages if p.get("instagram_business_account", {}).get("id") == IG_USER_ID), None)
    if not page:
        raise SystemExit("Could not find the Page linked to your Instagram. Did you select it when generating the token?")
    page_token = page["access_token"]
    print(f"Page token for '{page['name']}': expires {expiry(page_token)}")

    # 3. Check the Page token works for Business Discovery
    check = requests.get(
        f"{API}/{IG_USER_ID}",
        params={"fields": "business_discovery.username(esferalatinaoficial){username}", "access_token": page_token},
        timeout=30,
    ).json()
    if "error" in check:
        print(f"The Page token can't use Business Discovery ({check['error'].get('message')}); saving the 60-day token.")
        save_token(long_token)
    else:
        save_token(page_token)
        print("Business Discovery works with the Page token. Saved to .env.")


if __name__ == "__main__":
    main()
