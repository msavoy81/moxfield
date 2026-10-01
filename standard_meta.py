#!/usr/bin/env python3
"""Aggregate the MTG Arena Standard BO1 metagame from AetherHub, cross-check
meta share against MTGGoldfish, and count the rare/mythic wildcards each
archetype needs.

Reuses fetch_scryfall_card() from card_lookup.py for Scryfall rarity lookups
instead of writing a new Scryfall client.
"""
import argparse
import csv
import os
import re
import sys
import time
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from card_lookup import fetch_scryfall_card
from fetch_deck import USER_AGENT

OUTPUT_DIR = os.path.expanduser("~/Documents/AI Projects/moxfield-exports")

TOP_N = 25

# https://magic.wizards.com/en/news/mtg-arena/reality-fracture-mastery-details
REALITY_FRACTURE_ARENA_RELEASE = date(2026, 9, 29)

MIN_REQUEST_INTERVAL = 3.0
_last_request = 0.0

AETHERHUB_BASE = "https://aetherhub.com"
AETHERHUB_META_URL = f"{AETHERHUB_BASE}/Metagame/Standard-BO1/"
GOLDFISH_META_URL = "https://www.mtggoldfish.com/metagame/standard"

BASIC_LAND_NAMES = {"Plains", "Island", "Swamp", "Mountain", "Forest", "Wastes"}

WIN_RATE_RE = re.compile(r"(\d+)%\s*Win Rate:\s*(\d+)\s*Wins\s*(\d+)\s*Losses")
BREAKDOWN_PCT_RE = re.compile(r"in\s*(\d+)%")


class BlockedError(Exception):
    """Raised when a site appears to be blocking us with a 403/captcha."""


def throttled_get(url):
    """GET url, waiting at least MIN_REQUEST_INTERVAL since the last request
    to either site this script talks to. Raises BlockedError on a 403 or an
    obvious bot-detection/captcha page instead of retrying or working around
    it."""
    global _last_request
    elapsed = time.monotonic() - _last_request
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html"}
    try:
        response = requests.get(url, headers=headers, timeout=20)
    finally:
        _last_request = time.monotonic()

    if response.status_code == 403:
        raise BlockedError(f"{url} returned HTTP 403 (bot detection)")

    lowered = response.text[:3000].lower()
    if response.status_code != 200 and (
        "captcha" in lowered or "checking your browser" in lowered or "cf-chl" in lowered
    ):
        raise BlockedError(f"{url} appears to be behind a captcha/bot-detection challenge")

    if response.status_code != 200:
        raise RuntimeError(f"{url} returned HTTP {response.status_code}")

    return response.text


def parse_relative_date(text, today):
    text = text.strip()
    if not text:
        return None
    if text.lower() == "today":
        return today
    if text.lower() == "yesterday":
        return today - timedelta(days=1)
    m = re.match(r"(\d+)\s+days?\s+ago", text, re.I)
    if m:
        return today - timedelta(days=int(m.group(1)))
    m = re.match(r"(\d+)\s+(hours?|minutes?)\s+ago", text, re.I)
    if m:
        return today
    return None


def parse_aetherhub_overview(html):
    soup = BeautifulSoup(html, "html.parser")
    archetypes = []

    for tbody in soup.find_all("tbody", class_="ae-tbody-deckrow"):
        rows = tbody.find_all("tr", class_="ae-deck-row")
        if len(rows) < 2:
            continue
        row1, row2 = rows[0], rows[1]

        title_td = row1.find("td", class_="ae-decktitle")
        if title_td is None or title_td.find("a") is None:
            continue
        name = title_td.get_text(strip=True)
        link = title_td.find("a")["href"]

        matches_td = row1.find("td", class_="ae-deckmatches")
        matches_text = matches_td.get_text(strip=True) if matches_td else ""
        matches = int(re.sub(r"\D", "", matches_text) or 0)

        rarities = {"common": 0, "uncommon": 0, "rare": 0, "mythic": 0}
        rarity_td = row1.find("td", class_="ae-deckrarity")
        if rarity_td:
            for icon in rarity_td.find_all("i"):
                classes = icon.get("class", [])
                rarity = next(
                    (c.replace("ss-", "") for c in classes
                     if c.startswith("ss-") and c not in ("ss", "ss-parl3")),
                    None,
                )
                if rarity not in rarities:
                    continue
                count_text = (icon.next_sibling or "").strip()
                rarities[rarity] = int(re.sub(r"\D", "", count_text) or 0)

        pct_span = row2.find("span", class_="percent-metagame")
        pct_text = pct_span.get_text(strip=True) if pct_span else ""
        meta_pct = float(pct_text.replace("% of Metagame", "").strip()) if pct_text else 0.0

        archetypes.append({
            "name": name,
            "url": AETHERHUB_BASE + link,
            "meta_pct": meta_pct,
            "matches": matches,
            "rarities": rarities,
            "colors": row1.get("data-color", ""),
        })

    archetypes.sort(key=lambda a: -a["meta_pct"])
    return archetypes


def parse_main_60(soup):
    """Return list of {qty, name, set, number, rarity, category} for the
    mainboard (not sideboard) table on an AetherHub deck page."""
    heading = soup.find("h5", string=re.compile(r"Main \d+ cards"))
    if heading is None:
        return []
    table = heading.find_next("table")
    if table is None:
        return []

    cards = []
    category = None
    for row in table.find_all("tr"):
        th = row.find("th")
        if th is not None:
            category = th.get_text(strip=True)
            continue

        link = row.find("a", class_="cardLink")
        if link is None:
            continue

        qty_container = link.find_parent("div", class_="hover-imglink")
        qty = 0
        if qty_container is not None and qty_container.contents:
            first = qty_container.contents[0]
            qty_text = str(first).strip()
            qty = int(qty_text) if qty_text.isdigit() else 0

        rarity = None
        for icon in row.find_all("i"):
            classes = icon.get("class", [])
            for c in classes:
                if c in ("ss-common", "ss-uncommon", "ss-rare", "ss-mythic"):
                    rarity = c.replace("ss-", "")

        cards.append({
            "qty": qty,
            "name": link.get("data-card-name", "").replace("’", "'"),
            "set": (link.get("data-card-set") or "").upper(),
            "number": link.get("data-card-number", ""),
            "rarity": rarity,
            "category": category,
        })

    return cards


def parse_variations(soup, today):
    header_text = soup.find(string=re.compile(r"deck variations"))
    if header_text is None:
        return []
    card_header = header_text.find_parent("div", class_="card-header")
    if card_header is None:
        return []
    table = card_header.find_next("table")
    if table is None:
        return []

    variations = []
    for row in table.find_all("tr"):
        link = row.find("a")
        if link is None:
            continue
        m = WIN_RATE_RE.search(link.get_text(strip=True))
        if not m:
            continue
        win_pct, wins, losses = int(m.group(1)), int(m.group(2)), int(m.group(3))

        tds = row.find_all("td")
        date_text = tds[-1].get_text(strip=True) if tds else ""
        variation_date = parse_relative_date(date_text, today)

        variations.append({
            "win_pct": win_pct,
            "wins": wins,
            "losses": losses,
            "date_text": date_text,
            "date": variation_date,
        })

    return variations


def parse_breakdown(soup):
    breakdown = {}
    container = soup.find("ul", id="cardbreakdown")
    if container is None:
        return breakdown
    for wrapper in container.find_all("div", class_="column-wrapper"):
        link = wrapper.find("a", class_="cardLink")
        footer = wrapper.find("span", class_="item-footer")
        if link is None or footer is None:
            continue
        name = link.get("data-card-name", "").replace("’", "'")
        m = BREAKDOWN_PCT_RE.search(footer.get_text())
        if m:
            breakdown[name] = int(m.group(1))
    return breakdown


def slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "archetype"


def lookup_rarity(name, cache, failed):
    if name in cache:
        return cache[name]
    try:
        card = fetch_scryfall_card(name)
        rarity = card.get("rarity")
    except (RuntimeError, requests.exceptions.RequestException) as e:
        failed.append((name, str(e)))
        rarity = None
    cache[name] = rarity
    return rarity


def write_arena_import(path, archetype_name, main_60):
    lines = [f"// {archetype_name}", "Deck"]
    for card in main_60:
        lines.append(f"{card['qty']} {card['name']} ({card['set']}) {card['number']}")
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def fetch_archetype_detail(archetype, today, page_cache, scryfall_cache, failed_lookups, blocked):
    """Fetch and parse an archetype's deck page, mutating `archetype` in
    place with main_60/variations/breakdown/wildcard counts. Reuses
    page_cache so an archetype found in both the top-N scan and the
    four/five-color scan is only fetched once."""
    if blocked["aetherhub"]:
        return

    if archetype["url"] in page_cache:
        soup = page_cache[archetype["url"]]
    else:
        try:
            html = throttled_get(archetype["url"])
        except BlockedError as e:
            print(f"BLOCKED: {e}")
            blocked["aetherhub"] = str(e)
            return
        soup = BeautifulSoup(html, "html.parser")
        page_cache[archetype["url"]] = soup

    main_60 = parse_main_60(soup)
    variations = parse_variations(soup, today)
    breakdown = parse_breakdown(soup)

    post_release = [
        v for v in variations
        if v["date"] is not None and v["date"] >= REALITY_FRACTURE_ARENA_RELEASE
    ]
    post_wins = sum(v["wins"] for v in post_release)
    post_losses = sum(v["losses"] for v in post_release)
    post_games = post_wins + post_losses
    post_win_rate = (post_wins / post_games * 100) if post_games else None

    all_wins = sum(v["wins"] for v in variations)
    all_losses = sum(v["losses"] for v in variations)
    all_games = all_wins + all_losses
    all_win_rate = (all_wins / all_games * 100) if all_games else None

    rares_needed = 0
    mythics_needed = 0
    for card in main_60:
        if card["name"] in BASIC_LAND_NAMES:
            card["scryfall_rarity"] = None
            continue
        rarity = lookup_rarity(card["name"], scryfall_cache, failed_lookups)
        card["scryfall_rarity"] = rarity
        if rarity == "rare":
            rares_needed += card["qty"]
        elif rarity == "mythic":
            mythics_needed += card["qty"]

    archetype["main_60"] = main_60
    archetype["variations"] = variations
    archetype["breakdown"] = breakdown
    archetype["all_variations_wins"] = all_wins
    archetype["all_variations_losses"] = all_losses
    archetype["all_variations_games"] = all_games
    archetype["all_variations_win_rate"] = all_win_rate
    archetype["post_release_wins"] = post_wins
    archetype["post_release_losses"] = post_losses
    archetype["post_release_games"] = post_games
    archetype["post_release_win_rate"] = post_win_rate
    archetype["rares_needed"] = rares_needed
    archetype["mythics_needed"] = mythics_needed


def parse_goldfish_overview(html):
    soup = BeautifulSoup(html, "html.parser")
    archetypes = []
    for tile in soup.find_all("div", class_="archetype-tile"):
        title_link = tile.find("span", class_="deck-price-online")
        title_link = title_link.find("a") if title_link else None
        if title_link is None:
            title_link = tile.find("a", href=re.compile(r"^/archetype/"))
        if title_link is None:
            continue
        name = title_link.get_text(strip=True)
        url = title_link["href"]
        if url.startswith("/"):
            url = "https://www.mtggoldfish.com" + url
        url = url.split("#")[0]

        stat = tile.find("div", class_="metagame-percentage")
        meta_pct, deck_count = 0.0, 0
        if stat is not None:
            value_div = stat.find("div", class_="archetype-tile-statistic-value")
            if value_div is not None:
                text = value_div.get_text(" ", strip=True)
                m = re.match(r"([\d.]+)%\s*\((\d+)\)", text)
                if m:
                    meta_pct = float(m.group(1))
                    deck_count = int(m.group(2))

        archetypes.append({
            "name": name,
            "url": url,
            "meta_pct": meta_pct,
            "deck_count": deck_count,
        })

    archetypes.sort(key=lambda a: -a["meta_pct"])
    return archetypes


def format_win_rate(win_rate):
    return f"{win_rate:.1f}" if win_rate is not None else ""


def deck_id(url):
    m = re.search(r"-(\d+)/?$", url)
    return m.group(1) if m else ""


def read_previous_urls(path):
    with open(path, newline="") as f:
        return {row["aetherhub_url"] for row in csv.DictReader(f)}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", default="",
                        help="label added to the CSV filenames, e.g. v2 -> standard_bo1_meta_v2_DATE.csv")
    parser.add_argument("--previous-csv",
                        help="meta CSV from an earlier run; skip Arena import files for archetypes already in it")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    today = date.today()
    date_stamp = today.isoformat()
    tag = f"{args.tag}_" if args.tag else ""
    previous_urls = read_previous_urls(args.previous_csv) if args.previous_csv else set()
    blocked = {"aetherhub": None, "goldfish": None}
    created_files = []

    print(f"=== Step 2a: AetherHub Standard BO1 metagame overview ({AETHERHUB_META_URL}) ===")
    try:
        overview_html = throttled_get(AETHERHUB_META_URL)
    except BlockedError as e:
        print(f"BLOCKED: {e}")
        blocked["aetherhub"] = str(e)
        overview_html = None

    all_archetypes = parse_aetherhub_overview(overview_html) if overview_html else []
    print(f"Parsed {len(all_archetypes)} archetype rows from AetherHub.")

    top_archetypes = all_archetypes[:TOP_N]
    for a in top_archetypes:
        print(f"  {a['meta_pct']:5.2f}%  {a['name']:20s} matches={a['matches']:6d}  {a['rarities']}  {a['url']}")

    four_five_color = [a for a in all_archetypes if len(a["colors"]) >= 4]
    print(f"\nFour/five-color archetypes found in AetherHub data: {len(four_five_color)}")
    for a in four_five_color:
        print(f"  {a['meta_pct']:5.2f}%  {a['name']:20s} colors={a['colors']}  {a['url']}")

    print(f"\n=== Step 2b/2c/2d: fetching each top-{TOP_N} deck page ===")
    page_cache = {}
    scryfall_cache = {}
    failed_lookups = []

    for i, archetype in enumerate(top_archetypes, 1):
        print(f"[{i}/{len(top_archetypes)}] Fetching {archetype['name']} ({archetype['url']})")
        fetch_archetype_detail(archetype, today, page_cache, scryfall_cache, failed_lookups, blocked)
        if blocked["aetherhub"]:
            break

    for archetype in four_five_color:
        if archetype["url"] not in page_cache and not blocked["aetherhub"]:
            print(f"Fetching four/five-color archetype {archetype['name']} ({archetype['url']})")
            fetch_archetype_detail(archetype, today, page_cache, scryfall_cache, failed_lookups, blocked)

    if failed_lookups:
        print(f"\n{len(failed_lookups)} Scryfall lookups failed:")
        for name, err in failed_lookups:
            print(f"  {name}: {err}")

    print("\n=== Step 2f: writing per-archetype summary CSV and Arena import files ===")
    csv_path = os.path.join(OUTPUT_DIR, f"standard_bo1_meta_{tag}{date_stamp}.csv")
    fieldnames = [
        "archetype", "aetherhub_url", "meta_share_pct", "match_count",
        "all_variations_win_rate_pct", "all_variations_games",
        "all_variations_wins", "all_variations_losses",
        "post_release_win_rate_pct", "post_release_games",
        "post_release_wins", "post_release_losses",
        "commons", "uncommons", "rares", "mythics",
        "rares_needed", "mythics_needed",
    ]
    fetched = [a for a in top_archetypes if "main_60" in a]
    # Highest all-variations win rate first; archetypes with no games last.
    fetched.sort(key=lambda a: (a["all_variations_win_rate"] is None,
                                -(a["all_variations_win_rate"] or 0)))
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for archetype in fetched:
            writer.writerow({
                "archetype": archetype["name"],
                "aetherhub_url": archetype["url"],
                "meta_share_pct": archetype["meta_pct"],
                "match_count": archetype["matches"],
                "all_variations_win_rate_pct": format_win_rate(archetype["all_variations_win_rate"]),
                "all_variations_games": archetype["all_variations_games"],
                "all_variations_wins": archetype["all_variations_wins"],
                "all_variations_losses": archetype["all_variations_losses"],
                "post_release_win_rate_pct": format_win_rate(archetype["post_release_win_rate"]),
                "post_release_games": archetype["post_release_games"],
                "post_release_wins": archetype["post_release_wins"],
                "post_release_losses": archetype["post_release_losses"],
                "commons": archetype["rarities"]["common"],
                "uncommons": archetype["rarities"]["uncommon"],
                "rares": archetype["rarities"]["rare"],
                "mythics": archetype["rarities"]["mythic"],
                "rares_needed": archetype["rares_needed"],
                "mythics_needed": archetype["mythics_needed"],
            })

            if archetype["url"] in previous_urls:
                continue
            # Name by AetherHub deck ID so files stay stable across runs and
            # never overwrite an earlier run's slug-numbered files.
            slug = f"{slugify(archetype['name'])}-{deck_id(archetype['url'])}"
            txt_path = os.path.join(OUTPUT_DIR, f"standard_bo1_{slug}_{date_stamp}.txt")
            write_arena_import(txt_path, archetype["name"], archetype["main_60"])
            created_files.append(txt_path)

    created_files.append(csv_path)
    print(f"Wrote {csv_path}")

    print(f"\n=== Step 3: MTGGoldfish cross-check ({GOLDFISH_META_URL}) ===")
    try:
        goldfish_html = throttled_get(GOLDFISH_META_URL)
        goldfish_archetypes = parse_goldfish_overview(goldfish_html)[:TOP_N]
        for a in goldfish_archetypes:
            print(f"  {a['meta_pct']:5.2f}%  {a['name']:25s} decks={a['deck_count']:4d}  {a['url']}")

        goldfish_csv = os.path.join(OUTPUT_DIR, f"standard_goldfish_{tag}{date_stamp}.csv")
        with open(goldfish_csv, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["archetype", "url", "meta_share_pct", "deck_count"])
            writer.writeheader()
            for a in goldfish_archetypes:
                writer.writerow({
                    "archetype": a["name"],
                    "url": a["url"],
                    "meta_share_pct": a["meta_pct"],
                    "deck_count": a["deck_count"],
                })
        created_files.append(goldfish_csv)
        print(f"Wrote {goldfish_csv}")
    except BlockedError as e:
        print(f"BLOCKED: {e}")
        blocked["goldfish"] = str(e)

    print("\n=== Step 4: four/five-color archetypes (full main 60) ===")
    for archetype in four_five_color:
        if "main_60" not in archetype:
            print(f"{archetype['name']} ({archetype['url']}): not fetched (blocked or skipped)")
            continue
        print(f"\n{archetype['name']} — colors={archetype['colors']} — {archetype['meta_pct']}% of meta — {archetype['url']}")
        for card in archetype["main_60"]:
            print(f"  {card['qty']}x {card['name']} ({card['set']}) {card['number']} [{card['scryfall_rarity']}]")

    print("\n=== Summary ===")
    if blocked["aetherhub"]:
        print(f"AetherHub was blocked partway through: {blocked['aetherhub']}")
    if blocked["goldfish"]:
        print(f"MTGGoldfish was blocked: {blocked['goldfish']}")
    print("Files created:")
    for path in created_files:
        print(f"  {path}")


if __name__ == "__main__":
    main()
