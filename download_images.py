#!/usr/bin/env python3
"""
Download character images for auction themes.
Uses DuckDuckGo HTML scraping to find character images.
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

DDG_IMAGE_URL = "https://duckduckgo.com/html/?q={query}&iax=images&ia=images"


def sanitize_filename(name: str) -> str:
    """Convert character name to safe filename."""
    return re.sub(r'[^\w\-]', '_', name.lower())


def search_ddg_image(query: str) -> Optional[str]:
    """Search DuckDuckGo for an image and return the first image URL."""
    url = DDG_IMAGE_URL.format(query=urllib.parse.quote(query))
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # DuckDuckGo image results are in .tile--img__img or similar
        for img in soup.select("img.tile--img__img, img[class*='tile']"):
            src = img.get("src") or img.get("data-src")
            if src and src.startswith("http"):
                return src
        # Fallback: any image in results
        for img in soup.select(".result__snippet img, .image__img"):
            src = img.get("src") or img.get("data-src")
            if src and src.startswith("http"):
                return src
    except Exception as e:
        print(f"  Search error for '{query}': {e}")
    return None


def download_image(url: str, dest_path: Path) -> bool:
    """Download and convert image to WebP."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        resp.raise_for_status()
        
        # Save to temp, then convert
        temp_path = dest_path.with_suffix(".tmp")
        with open(temp_path, "wb") as f:
            for chunk in resp.iter_content(8192):
                f.write(chunk)
        
        # Open with PIL, convert to WebP, resize if needed
        with Image.open(temp_path) as im:
            # Convert to RGB if needed (WebP doesn't support all modes)
            if im.mode in ("RGBA", "LA", "P"):
                # Keep transparency for WebP
                pass
            elif im.mode != "RGB":
                im = im.convert("RGB")
            
            # Resize to max 600px on longest side for performance
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
    for char in data["characters"]:
        char_id = char["id"]
        char_name = char["name"]
        expected_path = theme_static_dir / f"{char_id}.webp"
        
        # Check if already exists
        if expected_path.exists():
            print(f"  ✓ {char_name} already exists")
            # Update JSON to use relative static path
            new_image_path = f"/static/auction/themes/{theme_id}/{char_id}.webp"
            if char.get("image") != new_image_path:
                char["image"] = new_image_path
                updated = True
            continue
        
        # Search for image
        search_query = f"{char_name} {theme_id.replace('_', ' ')} character"
        print(f"  Searching: {search_query}")
        img_url = search_ddg_image(search_query)
        
        if img_url:
            print(f"  Found: {img_url[:80]}...")
            if download_image(img_url, expected_path):
                print(f"  ✓ Downloaded: {char_name}")
                char["image"] = f"/static/auction/themes/{theme_id}/{char_id}.webp"
                updated = True
            else:
                print(f"  ✗ Failed to download: {char_name}")
        else:
            print(f"  ✗ No image found: {char_name}")
        
        # Be nice to DDG
        time.sleep(1.5)
    
    if updated:
        with open(theme_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Updated {theme_file}")


def main():
    print("Starting character image download...")
    theme_files = sorted(THEME_DIR.glob("*.json"))
    
    for theme_file in theme_files:
        process_theme(theme_file)
        time.sleep(2)  # Extra delay between themes
    
    print("\n=== Done ===")


if __name__ == "__main__":
    main()