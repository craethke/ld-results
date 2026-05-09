#!/usr/bin/env python3
"""
Ludum Dare Performance Analyzer — cody-raethke
================================================

Requirements:
    pip install requests matplotlib numpy

Run:
    python ld_analyzer.py
"""

import json
import sys
import time
import math
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
import re

try:
    import requests
except ImportError:
    sys.exit("Missing dependency: pip install requests matplotlib numpy")

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches
    from matplotlib.gridspec import GridSpec
    import numpy as np
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False
    print("Warning: matplotlib/numpy not found — charts will be skipped.")

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

USERNAME = "cody-raethke"
API_BASE = "https://api.ldjam.com/vx"

TARGET_EVENTS = [53, 54, 55, 56, 57, 58, 59]

CATEGORIES = [
    "overall",
    "fun",
    "innovation",
    "theme",
    "graphics",
    "audio",
    "humor",
    "mood",
]

CAT_LABELS = {
    "overall":    "Overall",
    "fun":        "Fun",
    "innovation": "Innovation",
    "theme":      "Theme",
    "graphics":   "Graphics",
    "audio":      "Audio",
    "humor":      "Humor",
    "mood":       "Mood",
}

CAT_COLORS = {
    "overall":    "#f97316",
    "fun":        "#ec4899",
    "innovation": "#a855f7",
    "theme":      "#3b82f6",
    "graphics":   "#10b981",
    "audio":      "#f59e0b",
    "humor":      "#ef4444",
    "mood":       "#6366f1",
}

EVENT_META = {
    53: {"date": "Apr 2023", "theme": "Delivery"},
    54: {"date": "Oct 2023", "theme": "Entire Game on One Screen"},
    55: {"date": "Apr 2024", "theme": "Summoning"},
    56: {"date": "Oct 2024", "theme": "Tiny Creatures"},
    57: {"date": "Apr 2025", "theme": "Depths"},
    58: {"date": "Oct 2025", "theme": "Collector"},
    59: {"date": "Apr 2026", "theme": "Signal"},
}

OUTPUT_DIR = Path(".")

# ─────────────────────────────────────────────
# HTTP SESSION
# ─────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 LD-analyzer/2.0",
    "Accept": "application/json",
})

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def api_get(path, params=None, retries=3):
    url = f"{API_BASE}{path}"

    for attempt in range(retries):
        try:
            r = SESSION.get(url, params=params, timeout=20)

            if r.status_code == 429:
                wait = 2 ** attempt
                print(f"  Rate limited, retrying in {wait}s...")
                time.sleep(wait)
                continue

            r.raise_for_status()
            return r.json()

        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                print(f"Request failed: {url}")
                raise e

            time.sleep(1)

    return {}

def safe_float(val, default=None):
    try:
        return float(val)
    except (TypeError, ValueError):
        return default

def extract_last_path_id(data):
    """
    Handle BOTH:
      "path": [1, 2, 3]
    and:
      "path": [{"id":1}, {"id":2}]
    """

    path = data.get("path")

    if isinstance(path, list) and path:
        last = path[-1]

        if isinstance(last, int):
            return last

        if isinstance(last, dict):
            return last.get("id")

    node = data.get("node")

    if isinstance(node, dict):
        return node.get("id")

    if isinstance(node, list) and node:
        if isinstance(node[0], dict):
            return node[0].get("id")

    return data.get("id")

def normalize_node_response(data):
    node = data.get("node")

    if isinstance(node, dict):
        return node

    if isinstance(node, list):
        return node[0] if node else {}

    return {}

# ─────────────────────────────────────────────
# USER LOOKUP
# ─────────────────────────────────────────────

def get_user_id(username):
    print(f"Looking up user: {username}")

    data = api_get(f"/node/walk/1/users/{username}")

    node_id = extract_last_path_id(data)

    print(f"  User node ID: {node_id}")

    return node_id

# ─────────────────────────────────────────────
# EVENT LOOKUP
# ─────────────────────────────────────────────

def get_event_node_by_path(ld_num):
    data = api_get(f"/node/walk/1/events/ludum-dare/{ld_num}")
    return extract_last_path_id(data)

# ─────────────────────────────────────────────
# GAME DISCOVERY
# ─────────────────────────────────────────────

def node_has_author(node, user_id):
    """
    Different API responses store authors differently.
    """

    uid = str(user_id)

    links = node.get("link", {})

    if isinstance(links, dict):
        authors = links.get("author", [])

        if not isinstance(authors, list):
            authors = [authors]

        if uid in [str(a) for a in authors]:
            return True

    meta = node.get("meta", {})

    for k, v in meta.items():
        if "author" in k.lower() and uid in str(v):
            return True

    return False

def get_user_games(user_id):
    """
    Correct LDJam API way:
    returns all games by author directly.
    """

    data = api_get(
        f"/node/feed/{user_id}/authors/item/game",
        params={"limit": 100}
    )

    return data.get("feed", [])

def get_user_game_ids(user_id):
    data = api_get(
        f"/node/feed/{user_id}/authors/item/game",
        params={"limit": 100}
    )

    return [n["id"] for n in data.get("feed", []) if "id" in n]

def get_game_node(game_id):
    data = api_get(f"/node2/get/{game_id}")

    nodes = data.get("node", [])
    if isinstance(nodes, list) and nodes:
        return nodes[0]

    return {}

def game_belongs_to_event(game_node, ld_num):
    path = game_node.get("path", "")
    return f"/events/ludum-dare/{ld_num}/" in path

def find_game_in_event(user_id, event_node_id, ld_num):

    print(f"  Searching LD{ld_num}...")

    game_ids = get_user_game_ids(user_id)

    print(f"  Found {len(game_ids)} game IDs")

    for gid in game_ids:

        node = get_game_node(gid)

        if not node:
            continue

        if game_belongs_to_event(node, ld_num):
            return node

    return None


# ─────────────────────────────────────────────
# GRADES
# ─────────────────────────────────────────────

def get_game_grades(game_node_id):
    data = api_get(f"/node/get/{game_node_id}")
    node = normalize_node_response(data)
    return node.get("meta", {})

def parse_grades(node):
    """
    Correct LDJam VX format (node2/get)
    Uses 'magic.grade-XX-average/result'
    """

    grade_map = {
        "01": "overall",
        "02": "fun",
        "03": "innovation",
        "04": "theme",
        "05": "graphics",
        "06": "audio",
        "07": "humor",
        "08": "mood",
    }

    magic = node.get("magic", {}) or {}

    grades = {}

    for num, cat in grade_map.items():

        avg = magic.get(f"grade-{num}-average")
        result = magic.get(f"grade-{num}-result")

        if avg is None and result is None:
            continue

        grades[cat] = {
            "average": float(avg) if avg is not None else None,
            "result": int(result) if result is not None else None
        }

    return grades

# ─────────────────────────────────────────────
# EVENT STATS
# ─────────────────────────────────────────────

def get_event_stats(ld_num, event_node_id):

    data = api_get(f"/node/get/{event_node_id}")
    node = normalize_node_response(data)

    meta = node.get("meta", {})

    stats = {
        "total": safe_float(meta.get("item-count"), 0),
        "jam": safe_float(meta.get("item-jam-count"), 0),
        "compo": safe_float(meta.get("item-compo-count"), 0),
        "extra": safe_float(meta.get("item-extra-count"), 0),
    }

    # fallback values
    fallbacks = {
        53: {"total": 2308, "jam": 1624, "compo": 684, "extra": 0},
        54: {"total": 2000, "jam": 1400, "compo": 520, "extra": 80},
        55: {"total": 2194, "jam": 1543, "compo": 564, "extra": 87},
        56: {"total": 1800, "jam": 1270, "compo": 450, "extra": 80},
        57: {"total": 1566, "jam": 1100, "compo": 400, "extra": 66},
        58: {"total": 1390, "jam": 980, "compo": 350, "extra": 60},
        59: {"total": 1400, "jam": 980, "compo": 360, "extra": 60},
    }

    if stats["total"] < 100:
        stats = fallbacks.get(ld_num, stats)

    return stats

# ─────────────────────────────────────────────
# PERCENTILES
# ─────────────────────────────────────────────

def compute_percentile(place, total):

    if not place or not total:
        return None

    return round((1 - ((place - 1) / total)) * 100, 2)

# ─────────────────────────────────────────────
# SCRAPER
# ─────────────────────────────────────────────

def scrape_all():

    print("\n" + "=" * 60)
    print("Ludum Dare Performance Analyzer")
    print("=" * 60)

    user_id = get_user_id(USERNAME)

    if not user_id:
        sys.exit("Could not resolve user ID")

    results = []

    for ld_num in TARGET_EVENTS:

        print(f"\n── LD{ld_num} ─────────────────────────────────")

        event_node_id = get_event_node_by_path(ld_num)

        if not event_node_id:
            print("  Could not resolve event node")
            continue

        print(f"  Event node: {event_node_id}")

        stats = get_event_stats(ld_num, event_node_id)

        game_node = find_game_in_event(user_id, event_node_id, ld_num)

        if not game_node:
            print("  No game found")
            results.append({
                "ld": ld_num,
                "error": "game not found",
            })
            continue

        game_id = game_node.get("id")
        game_name = game_node.get("name", "Unknown")
        game_path = game_node.get("path", "")
        subtype = game_node.get("subtype", "jam")

        print(f"  Found: {game_name}")

        meta = get_game_grades(game_id)

        if not meta:
            meta = game_node.get("meta", {})

        grades = parse_grades(game_node)

        if subtype == "compo":
            total_for_pct = int(stats["compo"] or stats["total"])
        elif subtype == "extra":
            total_for_pct = int(stats["extra"] or stats["total"])
        else:
            total_for_pct = int(stats["jam"] or stats["total"])

        ratings = {}

        for cat in CATEGORIES:

            g = grades.get(cat, {})

            place = g.get("result")
            avg = g.get("average")
            given = g.get("given")

            percentile = compute_percentile(place, total_for_pct)

            ratings[cat] = {
                "place": int(place) if place else None,
                "avg": round(avg, 4) if avg else None,
                "ratings_received": int(given) if given else None,
                "percentile": percentile,
            }

        results.append({
            "ld": ld_num,
            "date": EVENT_META[ld_num]["date"],
            "theme": EVENT_META[ld_num]["theme"],
            "game_name": game_name,
            "game_url": f"https://ldjam.com{game_path}" if game_path else None,
            "category": subtype,
            "event_stats": stats,
            "total_for_percentile": total_for_pct,
            "ratings": ratings,
        })

        print(f"  Parsed {len([x for x in ratings.values() if x['avg'] is not None])} categories")

        time.sleep(0.4)

    return results

# ─────────────────────────────────────────────
# CHARTS
# ─────────────────────────────────────────────

def make_charts(results, output_path="ld_performance.png"):

    if not HAS_MATPLOTLIB:
        return

    games = [
        r for r in results
        if r.get("ratings", {}).get("overall", {}).get("avg")
    ]

    if not games:
        print("No rating data found")
        return

    labels = [f"LD{g['ld']}" for g in games]

    fig = plt.figure(figsize=(16, 10), facecolor="#090909")
    ax = fig.add_subplot(111)

    ax.set_facecolor("#111111")

    x = np.arange(len(games))

    overall = [
        g["ratings"]["overall"]["avg"]
        for g in games
    ]

    ax.plot(
        x,
        overall,
        linewidth=2.5,
        marker="o",
        color=CAT_COLORS["overall"],
    )

    for xi, yi in zip(x, overall):
        ax.annotate(
            f"{yi:.2f}",
            (xi, yi),
            textcoords="offset points",
            xytext=(0, 10),
            ha="center",
            color="white",
        )

    ax.set_xticks(x)
    ax.set_xticklabels(labels)

    ax.set_ylim(0, 5)

    ax.set_title(
        f"Ludum Dare Ratings — @{USERNAME}",
        color="white",
        fontsize=16,
    )

    ax.set_ylabel("Average Rating", color="white")

    ax.tick_params(colors="#cccccc")

    out = OUTPUT_DIR / output_path

    plt.savefig(out, dpi=150, bbox_inches="tight")
    plt.close()

    print(f"Chart saved: {out}")

# ─────────────────────────────────────────────
# LLM PROMPT
# ─────────────────────────────────────────────

def build_llm_prompt(results):

    return f"""
Analyze this developer's Ludum Dare history.

Username: {USERNAME}

Data:
{json.dumps(results, indent=2)}

Write:
1. Overall trend
2. Strongest categories
3. Weakest categories
4. Most improved areas
5. Best performing game
6. Advice for future Ludum Dare events

Use specific numbers and percentiles.
"""

# ─────────────────────────────────────────────
# OUTPUT
# ─────────────────────────────────────────────

def save_json(results, path="ld_data.json"):

    out = OUTPUT_DIR / path

    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"Saved JSON: {out}")

def save_prompt(prompt, path="ld_llm_prompt.txt"):

    out = OUTPUT_DIR / path

    with open(out, "w", encoding="utf-8") as f:
        f.write(prompt)

    print(f"Saved prompt: {out}")

# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():

    print(f"Started: {datetime.now()}")

    results = scrape_all()

    save_json(results)

    if HAS_MATPLOTLIB:
        make_charts(results)

    prompt = build_llm_prompt(results)

    save_prompt(prompt)

    print("\nSummary:\n")

    for r in results:

        if "error" in r:
            print(f"LD{r['ld']}: {r['error']}")
            continue

        overall = r["ratings"]["overall"]

        if overall["avg"] is None:
            print(f"LD{r['ld']}: no ratings")
            continue

        print(
            f"LD{r['ld']} | "
            f"{r['game_name']} | "
            f"avg {overall['avg']:.3f} | "
            f"#{overall['place']} | "
            f"p{overall['percentile']}"
        )

    print("\nDone.")

if __name__ == "__main__":
    main()
