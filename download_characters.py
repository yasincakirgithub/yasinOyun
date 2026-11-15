#!/usr/bin/env python3
"""
Download character images for auction themes using multiple sources.
"""

import json
import os
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup
from PIL import Image

BASE_DIR = Path(__file__).parent
THEME_DIR = BASE_DIR / "auction" / "themes" / "data"
STATIC_BASE = BASE_DIR / "auction" / "static" / "auction" / "themes"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Known good image sources for different franchises
SOURCE_URLS = {
    "marvel": "https://marvel.fandom.com/wiki/{name}",
    "dc": "https://dc.fandom.com/wiki/{name}",
    "star_wars": "https://starwars.fandom.com/wiki/{name}",
    "lotr": "https://lotr.fandom.com/wiki/{name}",
    "harry_potter": "https://harrypotter.fandom.com/wiki/{name}",
    "game_of_thrones": "https://gameofthrones.fandom.com/wiki/{name}",
    "naruto": "https://naruto.fandom.com/wiki/{name}",
    "one_piece": "https://onepiece.fandom.com/wiki/{name}",
    "dragon_ball": "https://dragonball.fandom.com/wiki/{name}",
    "video_games": None,  # Various sources
}

SEARCH_URLS = {
    "ddg": "https://duckduckgo.com/html/?q={query}&iax=images&ia=images",
    "google": "https://www.google.com/search?q={query}&tbm=isch",
    "bing": "https://www.bing.com/images/search?q={query}",
}


def sanitize_filename(name: str) -> str:
    return re.sub(r'[^\w\-]', '_', name.lower())


def search_ddg_image(query: str) -> Optional[str]:
    """Search DuckDuckGo for an image and return the first image URL."""
    url = SEARCH_URLS["ddg"].format(query=urllib.parse.quote(query))
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Try multiple selectors for DDG
        for selector in ["img.tile--img__img", "img[class*='tile']", ".result__snippet img", ".image__img"]:
            for img in soup.select(selector):
                src = img.get("src") or img.get("data-src")
                if src and src.startswith("http") and not src.startswith("data:"):
                    return src
    except Exception as e:
        print(f"  DDG search error for '{query}': {e}")
    return None


def search_bing_image(query: str) -> Optional[str]:
    """Search Bing for an image."""
    url = SEARCH_URLS["bing"].format(query=urllib.parse.quote(query))
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Bing image results
        for img in soup.select("img.mimg, .iusc img"):
            src = img.get("src") or img.get("data-src") or img.get("m")
            if src and src.startswith("http"):
                return src
            # Sometimes data is in 'm' attribute as JSON
            if src and src.startswith("{"):
                try:
                    data = json.loads(src)
                    if data.get("murl"):
                        return data["murl"]
                except:
                    pass
    except Exception as e:
        print(f"  Bing search error for '{query}': {e}")
    return None


def download_image(url: str, dest_path: Path) -> bool:
    """Download and convert image to WebP."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        resp.raise_for_status()
        
        # Check content type
        content_type = resp.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            print(f"  Not an image: {content_type}")
            return False
        
        # Save to temp, then convert
        temp_path = dest_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        
        # Open with PIL, convert to WebP
        with Image.open(temp_path) as im:
            # Convert to RGB if needed
            if im.mode in ("RGBA", "LA", "P"):
                pass  # WebP supports transparency
            elif im.mode != "RGB":
                im = im.convert("RGB")
            
            # Resize to max 600px on longest side
            max_dim = 600
            if max(im.size) > max_dim:
                im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
            
            im.save(dest_path, "WEBP", quality=85, method=6)
        
        temp_path.unlink(missing_ok=True)
        return True
    except Exception as e:
        print(f"  Download error: {e}")
        return False


def process_theme(theme_file: Path):
    """Process a single theme file."""
    theme_id = theme_file.stem
    print(f"\n=== Processing {theme_id} ===")
    
    with open(theme_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    theme_static_dir = STATIC_BASE / theme_id
    theme_static_dir.mkdir(parents=True, exist_ok=True)
    
    updated = False
    for i, char in enumerate(data["characters"]):
        char_id = char["id"]
        char_name = char["name"]
        expected_path = theme_static_dir / f"{char_id}.webp"
        
        # Check if already exists
        if expected_path.exists():
            print(f"  ✓ {char_name} already exists")
            new_image_path = f"/static/auction/themes/{theme_id}/{char_id}.webp"
            if char.get("image") != new_image_path:
                char["image"] = new_image_path
                updated = True
            continue
        
        # Build search query
        search_query = f"{char_name} {theme_id.replace('_', ' ')} character portrait"
        print(f"  [{i+1}/{len(data['characters'])}] Searching: {search_query}")
        
        # Try DDG first
        img_url = search_ddg_image(search_query)
        
        # Fallback to Bing
        if not img_url:
            img_url = search_bing_image(search_query)
        
        if img_url:
            print(f"    Found: {img_url[:80]}...")
            if download_image(img_url, expected_path):
                print(f"    ✓ Downloaded: {char_name}")
                char["image"] = f"/static/auction/themes/{theme_id}/{char_id}.webp"
                updated = True
            else:
                print(f"    ✗ Failed to download: {char_name}")
        else:
            print(f"    ✗ No image found: {char_name}")
        
        # Be nice to search engines
        time.sleep(2)
    
    if updated:
        with open(theme_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Updated {theme_file}")


def main():
    print("Starting character image download...")
    theme_files = sorted(THEME_DIR.glob("*.json"))
    
    for theme_file in theme_files:
        process_theme(theme_file)
        time.sleep(3)  # Extra delay between themes
    
    print("\n=== Done ===")


if __name__ == "__main__":
    main()
