#!/usr/bin/env python3
"""
Fast character image downloader using DuckDuckGo lite and direct Fandom URLs.
"""

import json
import os
import re
import time
import urllib.parse
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from PIL import Image

BASE_DIR = Path(__file__).parent
THEME_DIR = BASE_DIR / "auction" / "themes" / "data"
STATIC_BASE = BASE_DIR / "auction" / "static" / "auction" / "themes"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# Fandom domains for each theme
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
    "video_games": None,
}

def sanitize(name: str) -> str:
    return re.sub(r'[^\w\-]', '_', name.lower())

def try_fandom_image(theme: str, char_id: str, char_name: str) -> str | None:
    """Try to get image from Fandom wiki directly."""
    domain = FANDOM_DOMAINS.get(theme)
    if not domain:
        return None
    
    # Try multiple URL patterns
    name_encoded = urllib.parse.quote(char_name.replace(" ", "_"))
    urls = [
        f"https://{domain}/wiki/{name_encoded}",
        f"https://{domain}/wiki/{char_id}",
        f"https://{domain}/api.php?action=query&prop=images&titles={name_encoded}&format=json",
    ]
    
    for url in urls:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=8)
            if resp.status_code == 200:
                if "api.php" in url:
                    data = resp.json()
                    pages = data.get("query", {}).get("pages", {})
                    for page in pages.values():
                        for img in page.get("images", []):
                            if char_name.lower().replace(" ", "_") in img.get("title", "").lower():
                                # Get the actual image URL
                                img_title = img["title"].replace("File:", "")
                                img_url = f"https://{domain}/api.php?action=query&titles=File:{urllib.parse.quote(img_title)}&prop=imageinfo&iiprop=url&format=json"
                                img_resp = requests.get(img_url, headers=HEADERS, timeout=5)
                                if img_resp.status_code == 200:
                                    img_data = img_resp.json()
                                    for p in img_data.get("query", {}).get("pages", {}).values():
                                        for ii in p.get("imageinfo", []):
                                            return ii.get("url")
                else:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    # Look for infobox image or main image
                    for selector in [".infobox-image img", ".pi-image-thumbnail img", "figure.pi-item img", "img.pi-image-thumbnail"]:
                        img = soup.select_one(selector)
                        if img and img.get("src"):
                            src = img["src"]
                            if src.startswith("//"):
                                src = "https:" + src
                            if src.startswith("http"):
                                return src
        except Exception:
            continue
    return None


def try_ddg_lite(query: str) -> str | None:
    """Use DuckDuckGo lite (HTML) for faster results."""
    url = f"https://duckduckgo.com/html/?q={urllib.parse.quote(query)}&iax=images&ia=images"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        soup = BeautifulSoup(resp.text, "html.parser")
        for img in soup.select("img.tile--img__img, .result__snippet img, .image__img"):
            src = img.get("src") or img.get("data-src")
            if src and src.startswith("http") and not src.startswith("data:"):
                return src
    except Exception:
        pass
    return None


def download_image(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12, stream=True)
        resp.raise_for_status()
        temp = dest.with_suffix(".tmp")
        with open(temp, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        with Image.open(temp) as im:
            if im.mode in ("RGBA", "LA", "P"):
                pass
            elif im.mode != "RGB":
                im = im.convert("RGB")
            max_dim = 600
            if max(im.size) > max_dim:
                im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            im.save(dest, "WEBP", quality=85, method=6)
        temp.unlink(missing_ok=True)
        return True
    except Exception as e:
        print(f"    DL error: {e}")
        return False


def process_theme(theme_file: Path):
    theme_id = theme_file.stem
    print(f"\n=== {theme_id} ===")
    
    with open(theme_file) as f:
        data = json.load(f)
    
    static_dir = STATIC_BASE / theme_id
    static_dir.mkdir(parents=True, exist_ok=True)
    
    updated = False
    for i, char in enumerate(data["characters"]):
        char_id = char["id"]
        char_name = char["name"]
        dest = static_dir / f"{char_id}.webp"
        
        if dest.exists():
            new_path = f"/static/auction/themes/{theme_id}/{char_id}.webp"
            if char.get("image") != new_path:
                char["image"] = new_path
                updated = True
            continue
        
        print(f"  [{i+1}/{len(data['characters'])}] {char_name}")
        
        # Try Fandom first for known franchises
        img_url = None
        if theme_id in FANDOM_DOMAINS:
            img_url = try_fandom_image(theme_id, char_id, char_name)
            if img_url:
                print(f"    Fandom: {img_url[:60]}...")
        
        # Fallback to DDG
        if not img_url:
            query = f"{char_name} {theme_id.replace('_', ' ')} character"
            img_url = try_ddg_lite(query)
            if img_url:
                print(f"    DDG: {img_url[:60]}...")
        
        if img_url and download_image(img_url, dest):
            print(f"    ✓ Saved")
            char["image"] = f"/static/auction/themes/{theme_id}/{char_id}.webp"
            updated = True
        else:
            print(f"    ✗ Failed")
        
        time.sleep(1)  # Rate limit
    
    if updated:
        with open(theme_file, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Updated JSON")


def main():
    for theme_file in sorted(THEME_DIR.glob("*.json")):
        process_theme(theme_file)
        time.sleep(2)

if __name__ == "__main__":
    main()
