#!/usr/bin/env python3
import re
import sys

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

DEFAULT_DECK_ID = "rAHH2XeO2USKMlAf2xxGJA"


def extract_deck_id(deck_id_or_url):
    match = re.search(r"moxfield\.com/decks/([^/?#]+)", deck_id_or_url)
    if match:
        return match.group(1)
    return deck_id_or_url


def get_moxfield_deck(deck_id_or_url):
    deck_id = extract_deck_id(deck_id_or_url)
    url = f"https://api.moxfield.com/v2/decks/all/{deck_id}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to reach Moxfield: {e}")

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to fetch deck {deck_id!r}: "
            f"HTTP {response.status_code} - {response.text}"
        )

    return response.json()


def lookup_commander_card_id(commander_name):
    url = "https://api2.moxfield.com/v3/cards/named"
    # No Content-Type header here: this endpoint tries to parse the request
    # body as JSON when the header is present, and fails on the empty GET body.
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    params = {
        "q": commander_name,
        "count": 10,
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to reach Moxfield: {e}")

    if response.status_code != 200:
        raise RuntimeError(
            f"Failed to look up commander {commander_name!r}: "
            f"HTTP {response.status_code} - {response.text}"
        )

    cards = response.json().get("cards") or []
    matches = [
        card
        for card in cards
        if card.get("name", "").lower() == commander_name.lower()
        and card.get("set_type") != "memorabilia"
    ]

    if not matches:
        raise RuntimeError(f"No commander found with name {commander_name!r}")

    return matches[0]["id"]


VALID_SORT_BY = ("updated", "likes", "views")


def search_decks(
    commander_name=None,
    fmt=None,
    theme=None,
    min_bracket=None,
    max_bracket=None,
    page_size=20,
    page_number=1,
    sort_by="updated",
):
    if sort_by not in VALID_SORT_BY:
        raise ValueError(
            f"Invalid sort_by {sort_by!r}: must be one of {VALID_SORT_BY}"
        )

    url = "https://api2.moxfield.com/v2/decks/search"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Content-Type": "application/json; charset=utf-8",
    }
    params = {
        "pageNumber": page_number,
        "pageSize": page_size,
        "sortType": sort_by,
        "sortDirection": "descending",
    }

    if commander_name is not None:
        params["commanderCardId"] = lookup_commander_card_id(commander_name)
    if fmt is not None:
        params["fmt"] = fmt
    if theme is not None:
        params["hubName"] = theme
    # Bracket doesn't apply to Standard, so skip it even if the caller passed one.
    if fmt != "standard":
        if min_bracket is not None:
            params["minBracket"] = min_bracket
        if max_bracket is not None:
            params["maxBracket"] = max_bracket

    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"Failed to reach Moxfield: {e}")

    if response.status_code != 200:
        target = f"commander {commander_name!r}" if commander_name else f"format {fmt!r}"
        raise RuntimeError(
            f"Failed to search decks for {target}: "
            f"HTTP {response.status_code} - {response.text}"
        )

    return response.json()


def print_search_results(results, commander_name=None):
    total_results = results.get("totalResults")
    total_pages = results.get("totalPages")
    page_number = results.get("pageNumber")
    page_size = results.get("pageSize")
    print(
        f"Found {total_results} decks across {total_pages} pages "
        f"(page {page_number} of {total_pages}, {page_size} per page)"
    )
    print()

    for deck in results["data"]:
        print(f"Name: {deck.get('name')}")
        print(f"Format: {deck.get('format')}")
        # The search endpoint never populates a deck's "commanders" field, so we
        # can only report the commander the search itself was scoped to.
        if commander_name:
            print(f"Commander(s): {commander_name}")
        print(f"Views: {deck.get('viewCount')}  Likes: {deck.get('likeCount')}")
        print(f"URL: https://moxfield.com/decks/{deck.get('publicId')}")
        print()


def print_deck(deck):
    print(f"Name: {deck.get('name')}")
    print(f"Format: {deck.get('format')}")

    commanders = deck.get("commanders") or {}
    if commanders:
        commander_names = ", ".join(
            card_entry.get("card", {}).get("name", "Unknown")
            for card_entry in commanders.values()
        )
        print(f"Commander(s): {commander_names}")
    else:
        print("Commander(s): None")

    print("\nMainboard:")
    mainboard = deck.get("mainboard") or {}
    for card_entry in mainboard.values():
        quantity = card_entry.get("quantity", 0)
        name = card_entry.get("card", {}).get("name", "Unknown")
        print(f"{quantity}x {name}")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--search":
        args = sys.argv[2:]

        commander_name = None
        if args and not args[0].startswith("--"):
            commander_name = args[0]
            args = args[1:]

        theme = None
        bracket = None
        fmt = None
        sort_by = "updated"
        i = 0
        while i < len(args):
            if args[i] == "--theme":
                theme = args[i + 1]
                i += 2
            elif args[i] == "--bracket":
                bracket = int(args[i + 1])
                i += 2
            elif args[i] == "--format":
                fmt = args[i + 1]
                i += 2
            elif args[i] == "--sort":
                sort_by = args[i + 1]
                i += 2
            else:
                i += 1

        results = search_decks(
            commander_name=commander_name,
            fmt=fmt,
            theme=theme,
            min_bracket=bracket,
            max_bracket=bracket,
            sort_by=sort_by,
        )
        print_search_results(results, commander_name=commander_name)
        return

    deck_id_or_url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DECK_ID
    deck = get_moxfield_deck(deck_id_or_url)
    print_deck(deck)


if __name__ == "__main__":
    main()
