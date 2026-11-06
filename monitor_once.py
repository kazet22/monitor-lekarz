#!/usr/bin/env python3
"""
Jednorazowe sprawdzenie wolnych terminow na ZnanyLekarz.pl (do GitHub Actions).
Harmonogram (co 10 min) zapewnia GitHub, a nie ten skrypt.
Temat powiadomien ntfy czytany jest ze zmiennej srodowiskowej NTFY_TOPIC (GitHub Secret).
"""

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

PROFILE_URL = "https://www.znanylekarz.pl/profil/kamil-kepa-2"
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
STATE_FILE = Path("state.json")
# Opcjonalnie: tylko terminy w tych godzinach, np. (15, 20) = 15:00-20:00. None = wszystkie.
ONLY_HOURS = None

TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


def log(msg: str) -> None:
    print(f"[{datetime.utcnow():%Y-%m-%d %H:%M:%S} UTC] {msg}", flush=True)


def notify(title: str, message: str) -> None:
    if not NTFY_TOPIC:
        log("Brak NTFY_TOPIC - nie wysylam powiadomienia.")
        return
    r = requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": title.encode("utf-8"),
            "Click": PROFILE_URL,
            "Priority": "high",
            "Tags": "calendar",
        },
        timeout=15,
    )
    log(f"Powiadomienie wyslane (HTTP {r.status_code}).")


def hour_ok(slot: str) -> bool:
    if ONLY_HOURS is None:
        return True
    return ONLY_HOURS[0] <= int(slot.split(":")[0]) < ONLY_HOURS[1]


def load_known() -> set[str]:
    try:
        return set(json.loads(STATE_FILE.read_text()))
    except Exception:
        return set()


def save_known(slots: set[str]) -> None:
    STATE_FILE.write_text(json.dumps(sorted(slots)))


def find_slots(page) -> set[str]:
    page.goto(PROFILE_URL, wait_until="domcontentloaded", timeout=60000)

    for label in ("Akceptuję", "Zgadzam się", "Akceptuj wszystkie", "Przejdź do serwisu"):
        try:
            page.get_by_role("button", name=re.compile(label, re.I)).first.click(timeout=2000)
            break
        except Exception:
            pass

    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except PWTimeout:
        pass
    page.wait_for_timeout(2000)

    title = (page.title() or "").lower()
    if any(x in title for x in ("just a moment", "access denied", "attention required", "403")):
        raise RuntimeError(f"Strona zablokowala dostep (tytul: {page.title()!r}).")

    slots = set()
    for el in page.locator("button, a, span, div").all():
        try:
            text = (el.inner_text(timeout=300) or "").strip()
        except Exception:
            continue
        if TIME_RE.match(text) and hour_ok(text):
            slots.add(text)
    return slots


def main() -> int:
    known = load_known()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="pl-PL",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            slots = find_slots(page)
        except Exception as e:
            log(f"BLAD: {e}")
            return 1
        finally:
            browser.close()

    new = slots - known
    if slots:
        log(f"Widoczne godziny: {sorted(slots)}")
    else:
        log("Brak wolnych terminow.")

    if new:
        notify(
            "Wolny termin u lekarza!",
            "Pojawily sie terminy: " + ", ".join(sorted(new)) + ". Kliknij i zarezerwuj.",
        )
    save_known(slots)
    return 0


if __name__ == "__main__":
    sys.exit(main())
