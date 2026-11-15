#!/usr/bin/env python3
"""
Fast Fandom API image downloader - uses direct wiki API calls.
Run this script to download missing images.
"""

import json
import os
import time
import urllib.parse
from pathlib import Path

import requests
from PIL import Image

BASE_DIR = Path(__file__).parent
THEME_DIR = BASE_DIR / "auction" / "themes" / "data"
STATIC_BASE = BASE_DIR / "auction" / "static" / "auction" / "themes"

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}

FANDOM_DOMAINS = {
    "marvel": "marvel.fandom.com",
    "dc": "dc.fandom.com",
    "star_wars": "starwars.fandom.com",
    "lotr": "lotr.fandom.com",
    "harry_potter": "harrypotter.fandom.com",
    "game_of_thrones": "gameofthrones.fandom.com",
    "naruto": "naruto.fandom.com",
    "one_piece": "onepiece.fandom.com",
    "dragon_ball": "dragonball.fandom.com",
}

def download_image(url: str, dest: Path) -> bool:
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, stream=True)
        r.raise_for_status()
        temp = dest.with_suffix(".tmp")
        with open(temp, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        with Image.open(temp) as im:
            if im.mode in ("RGBA", "LA", "P"): pass
            elif im.mode != "RGB": im = im.convert("RGB")
            if max(im.size) > 600: im.thumbnail((600, 600), Image.Resampling.LANCZOS)
            im.save(dest, "WEBP", quality=85)
        temp.unlink(missing_ok=True)
        return True
    except Exception as e:
        print(f"  DL error: {e}")
        return False

def get_fandom_image(theme: str, char_name: str) -> str | None:
    """Get character image from Fandom wiki API."""
    domain = FANDOM_DOMAINS.get(theme)
    if not domain: return None
    
    try:
        # Search for the page
        search_url = f"https://{domain}/api.php?action=query&list=search&srsearch={urllib.parse.quote(char_name)}&format=json"
        r = requests.get(search_url, headers=HEADERS, timeout=8)
        data = r.json()
        results = data.get("query", {}).get("search", [])
        if not results: return None
        
        page_title = results[0]["title"]
        
        # Get images from page
        img_url = f"https://{domain}/api.php?action=query&prop=images&titles={urllib.parse.quote(page_title)}&format=json"
        r = requests.get(img_url, headers=HEADERS, timeout=8)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        
        for page in pages.values():
            for img in page.get("images", []):
                img_title = img["title"]
                # Prefer images matching character name
                if char_name.lower().replace(" ", "_") in img_title.lower():
                    # Get actual image URL
                    file_url = f"https://{domain}/api.php?action=query&titles={urllib.parse.quote(img_title)}&prop=imageinfo&iiprop=url&format=json"
                    r = requests.get(file_url, headers=HEADERS, timeout=8)
                    data = r.json()
                    for p in data.get("query", {}).get("pages", {}).values():
                        for ii in p.get("imageinfo", []):
                            return ii.get("url")
    except Exception:
        pass
    return None

def process_theme(theme_id: str):
    print(f"\n=== {theme_id} ===")
    data = json.load(open(THEME_DIR / f"{theme_id}.json"))
    static_dir = STATIC_BASE / theme_id
    static_dir.mkdir(parents=True, exist_ok=True)
    
    updated = False
    for char in data["characters"]:
        char_id = char["id"]
        char_name = char["name"]
        dest = static_dir / f"{char_id}.webp"
        
        if dest.exists():
            new_path = f"/static/auction/themes/{theme_id}/{char_id}.webp"
            if char.get("image") != new_path:
                char["image"] = new_path
                updated = True
            continue
        
        print(f"  {char_name}...", end=" ")
        url = get_fandom_image(theme_id, char_name)
        if url and download_image(url, dest):
            print("✓")
            char["image"] = f"/static/auction/themes/{theme_id}/{char_id}.webp"
            updated = True
        else:
            print("✗")
        time.sleep(0.5)
    
    if updated:
        with open(THEME_DIR / f"{theme_id}.json", "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    import sys
    theme = sys.argv[1] if len(sys.argv) > 1 else None
    if theme:
        process_theme(theme)
    else:
        for t in sorted(FANDOM_DOMAINS.keys()):
            process_theme(t)
            time.sleep(1)
