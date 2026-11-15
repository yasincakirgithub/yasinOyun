#!/usr/bin/env python3
"""
Bulk character image downloader using Fandom API with concurrent requests.
Much faster than sequential scraping.
"""

import json
import os
import sys
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    "video_games": None,
}

# Character name overrides for better wiki matching
NAME_OVERRIDES = {
    "marvel": {
        "Spider-Man": "Spider-Man (Peter Parker)",
        "Spider-Man (Miles Morales)": "Miles Morales",
        "Captain America": "Captain America (Steve Rogers)",
        "Iron Man": "Iron Man (Tony Stark)",
        "Thor": "Thor Odinson",
        "Hulk": "Hulk (Bruce Banner)",
        "Doctor Strange": "Doctor Strange (Stephen Strange)",
        "Black Panther": "Black Panther (T'Challa)",
        "Captain Marvel": "Captain Marvel (Carol Danvers)",
        "Scarlet Witch": "Scarlet Witch (Wanda Maximoff)",
        "Vision": "Vision (Marvel Comics)",
        "Ant-Man": "Ant-Man (Scott Lang)",
        "The Wasp": "Wasp (Nadia van Dyne)",
        "Black Widow": "Black Widow (Natasha Romanoff)",
        "Hawkeye": "Hawkeye (Clint Barton)",
        "Winter Soldier": "Winter Soldier (Bucky Barnes)",
        "Falcon": "Falcon (Sam Wilson)",
        "War Machine": "War Machine (James Rhodes)",
        "Venom": "Venom (Eddie Brock)",
        "Carnage": "Carnage (Cletus Kasady)",
        "Deadpool": "Deadpool (Wade Wilson)",
        "Wolverine": "Wolverine (Logan)",
        "Magneto": "Magneto (Max Eisenhardt)",
        "Professor X": "Professor X (Charles Xavier)",
        "Phoenix (Jean Grey)": "Jean Grey",
        "Silver Surfer": "Silver Surfer (Norrin Radd)",
        "Galactus": "Galan",
        "Odin": "Odin Borson",
        "She-Hulk": "She-Hulk (Jennifer Walters)",
        "Abomination": "Abomination (Emil Blonsky)",
    },
    "dc": {
        "Superman": "Superman (Clark Kent)",
        "Batman": "Batman (Bruce Wayne)",
        "Wonder Woman": "Wonder Woman (Diana Prince)",
        "Flash": "Flash (Barry Allen)",
        "Darkseid": "Darkseid (Uxas)",
        "Joker": "Joker (DC Comics)",
        "Aquaman": "Aquaman (Arthur Curry)",
        "Green Lantern": "Green Lantern (Hal Jordan)",
        "Cyborg": "Cyborg (Victor Stone)",
        "Shazam": "Shazam (Billy Batson)",
        "Supergirl": "Supergirl (Kara Zor-El)",
        "Martian Manhunter": "Martian Manhunter (J'onn J'onzz)",
        "Green Arrow": "Green Arrow (Oliver Queen)",
        "Black Canary": "Black Canary (Dinah Lance)",
        "Hawkman": "Hawkman (Carter Hall)",
        "Zatanna": "Zatanna Zatara",
        "Constantine": "John Constantine",
        "Lex Luthor": "Lex Luthor (Alexander Luthor)",
        "Brainiac": "Brainiac (Vril Dox)",
        "Sinestro": "Thaal Sinestro",
        "Black Adam": "Black Adam (Teth-Adam)",
        "Reverse Flash": "Reverse-Flash (Eobard Thawne)",
        "Deathstroke": "Deathstroke (Slade Wilson)",
        "Harley Quinn": "Harley Quinn (Harleen Quinzel)",
        "Catwoman": "Catwoman (Selina Kyle)",
        "Ra's al Ghul": "Ra's al Ghul",
        "General Zod": "General Zod (Dru-Zod)",
        "Star Sapphire (Carol Ferris)": "Carol Ferris",
    },
    "harry_potter": {
        "Lord Voldemort": "Tom Riddle",
        "Albus Dumbledore": "Albus Dumbledore",
        "Severus Snape": "Severus Snape",
        "Hermione Granger": "Hermione Granger",
        "Gellert Grindelwald": "Gellert Grindelwald",
        "Bellatrix Lestrange": "Bellatrix Lestrange",
        "Minerva McGonagall": "Minerva McGonagall",
        "Sirius Black": "Sirius Black",
        "Remus Lupin": "Remus Lupin",
        "James Potter": "James Potter I",
        "Lily Potter": "Lily Potter",
        "Molly Weasley": "Molly Weasley",
        "Arthur Weasley": "Arthur Weasley",
    },
    "lotr": {
        "Gandalf": "Gandalf",
        "Sauron": "Sauron",
        "Aragorn": "Aragorn II Elessar",
        "Legolas": "Legolas Greenleaf",
        "Frodo Baggins": "Frodo Baggins",
        "Samwise Gamgee": "Samwise Gamgee",
        "Gimli": "Gimli",
        "Saruman": "Saruman",
        "Galadriel": "Galadriel",
        "Boromir": "Boromir",
        "Gollum": "Gollum",
        "Elrond": "Elrond",
        "Théoden": "Théoden",
        "Éowyn": "Éowyn",
        "Faramir": "Faramir",
        "Treebeard": "Treebeard",
        "Shelob": "Shelob",
        "Witch-king of Angmar": "Witch-king of Angmar",
        "Balrog": "Durin's Bane",
        "Tom Bombadil": "Tom Bombadil",
        "Bilbo Baggins": "Bilbo Baggins",
        "Merry Brandybuck": "Meriadoc Brandybuck",
        "Pippin Took": "Peregrin Took",
        "Denethor": "Denethor II",
        "Grima Wormtongue": "Gríma Wormtongue",
    },
    "game_of_thrones": {
        "Jon Snow": "Jon Snow",
        "Daenerys Targaryen": "Daenerys Targaryen",
        "Night King": "Night King",
        "Arya Stark": "Arya Stark",
        "Tyrion Lannister": "Tyrion Lannister",
        "Cersei Lannister": "Cersei Lannister",
        "Jaime Lannister": "Jaime Lannister",
        "Sansa Stark": "Sansa Stark",
        "Bran Stark": "Bran Stark",
        "Robb Stark": "Robb Stark",
        "Jorah Mormont": "Jorah Mormont",
        "Brienne of Tarth": "Brienne of Tarth",
        "The Hound (Sandor Clegane)": "Sandor Clegane",
        "The Mountain (Gregor Clegane)": "Gregor Clegane",
        "Samwell Tarly": "Samwell Tarly",
        "Davos Seaworth": "Davos Seaworth",
        "Petyr Baelish": "Petyr Baelish",
        "Varys": "Varys",
        "Melisandre": "Melisandre",
        "Tormund Giantsbane": "Tormund Giantsbane",
        "Oberyn Martell": "Oberyn Martell",
        "Ramsay Bolton": "Ramsay Bolton",
        "Theon Greyjoy": "Theon Greyjoy",
        "Joffrey Baratheon": "Joffrey Baratheon",
        "Stannis Baratheon": "Stannis Baratheon",
        "Robert Baratheon": "Robert Baratheon",
        "Ned Stark": "Eddard Stark",
    },
    "naruto": {
        "Naruto Uzumaki": "Naruto Uzumaki",
        "Sasuke Uchiha": "Sasuke Uchiha",
        "Madara Uchiha": "Madara Uchiha",
        "Hashirama Senju": "Hashirama Senju",
        "Itachi Uchiha": "Itachi Uchiha",
        "Kakashi Hatake": "Kakashi Hatake",
        "Pain (Nagato)": "Nagato",
        "Minato Namikaze": "Minato Namikaze",
        "Obito Uchiha": "Obito Uchiha",
        "Jiraiya": "Jiraiya",
        "Tsunade Senju": "Tsunade",
        "Orochimaru": "Orochimaru",
        "Sakura Haruno": "Sakura Haruno",
        "Shikamaru Nara": "Shikamaru Nara",
        "Gaara": "Gaara",
        "Rock Lee": "Rock Lee",
        "Might Guy": "Might Guy",
        "Killer B": "Killer B",
        "Kisame Hoshigaki": "Kisame Hoshigaki",
        "Deidara": "Deidara",
        "Sasori": "Sasori",
        "Hidan": "Hidan",
        "Kakuzu": "Kakuzu",
        "Konan": "Konan",
        "Kabuto Yakushi": "Kabuto Yakushi",
    },
    "one_piece": {
        "Monkey D. Luffy": "Monkey D. Luffy",
        "Roronoa Zoro": "Roronoa Zoro",
        "Nami": "Nami (One Piece)",
        "Usopp": "Usopp",
        "Sanji": "Vinsmoke Sanji",
        "Tony Tony Chopper": "Tony Tony Chopper",
        "Nico Robin": "Nico Robin",
        "Franky": "Franky (One Piece)",
        "Brook": "Brook (One Piece)",
        "Jinbe": "Jinbe",
        "Portgas D. Ace": "Portgas D. Ace",
        "Sabo": "Sabo (One Piece)",
        "Trafalgar Law": "Trafalgar D. Water Law",
        "Eustass Kid": "Eustass Kid",
        "Boa Hancock": "Boa Hancock",
        "Shanks": "Shanks (One Piece)",
        "Whitebeard": "Edward Newgate",
        "Kaido": "Kaido",
        "Big Mom": "Charlotte Linlin",
        "Blackbeard": "Marshall D. Teach",
        "Dracule Mihawk": "Dracule Mihawk",
        "Buggy": "Buggy the Clown",
        "Crocodile": "Crocodile (One Piece)",
        "Doflamingo": "Donquixote Doflamingo",
        "Katakuri": "Charlotte Katakuri",
        "Yamato": "Yamato (One Piece)",
    },
    "dragon_ball": {
        "Son Goku": "Goku",
        "Vegeta": "Vegeta (Dragon Ball)",
        "Frieza": "Frieza",
        "Cell": "Cell (Dragon Ball)",
        "Majin Buu": "Majin Buu",
        "Piccolo": "Piccolo Jr.",
        "Gohan": "Gohan",
        "Future Trunks": "Future Trunks",
        "Android 18": "Android 18",
        "Android 17": "Android 17",
        "Krillin": "Krillin",
        "Master Roshi": "Master Roshi",
        "Tien Shinhan": "Tien Shinhan",
        "Yamcha": "Yamcha",
        "Bulma": "Bulma",
        "Chi-Chi": "Chi-Chi",
        "Videl": "Videl",
        "Goten": "Goten",
        "Trunks": "Trunks (Dragon Ball)",
        "Gogeta": "Gogeta",
        "Vegito": "Vegito",
        "Beerus": "Beerus",
        "Whis": "Whis",
        "Jiren": "Jiren",
        "Broly": "Broly (Dragon Ball Super)",
        "Bardock": "Bardock",
        "King Vegeta": "King Vegeta",
    },
    "star_wars": {
        "Luke Skywalker": "Luke Skywalker",
        "Darth Vader": "Darth Vader",
        "Princess Leia": "Leia Organa",
        "Han Solo": "Han Solo",
        "Obi-Wan Kenobi": "Obi-Wan Kenobi",
        "Yoda": "Yoda",
        "Emperor Palpatine": "Sheev Palpatine",
        "Darth Maul": "Darth Maul",
        "Count Dooku": "Count Dooku",
        "General Grievous": "Grievous",
        "Mace Windu": "Mace Windu",
        "Qui-Gon Jinn": "Qui-Gon Jinn",
        "Anakin Skywalker": "Anakin Skywalker",
        "Padmé Amidala": "Padmé Amidala",
        "Ahsoka Tano": "Ahsoka Tano",
        "Captain Rex": "Rex (Clone Trooper)",
        "Chewbacca": "Chewbacca",
        "C-3PO": "C-3PO",
        "R2-D2": "R2-D2",
        "Lando Calrissian": "Lando Calrissian",
        "Boba Fett": "Boba Fett",
        "Jango Fett": "Jango Fett",
        "Kylo Ren": "Kylo Ren",
        "Rey": "Rey (Star Wars)",
        "Finn": "Finn (Star Wars)",
        "Poe Dameron": "Poe Dameron",
        "BB-8": "BB-8",
    },
    "video_games": {
        "Mario": "Mario",
        "Link": "Link (The Legend of Zelda)",
        "Samus Aran": "Samus Aran",
        "Kratos": "Kratos (God of War)",
        "Master Chief": "Master Chief",
        "Lara Croft": "Lara Croft",
        "Geralt of Rivia": "Geralt of Rivia",
        "Aloy": "Aloy (Horizon Zero Dawn)",
        "Arthur Morgan": "Arthur Morgan",
        "Joel Miller": "Joel Miller",
        "Ellie": "Ellie (The Last of Us)",
        "Nathan Drake": "Nathan Drake",
        "Kassandra": "Kassandra (Assassin's Creed)",
        "Ezio Auditore": "Ezio Auditore",
        "Solid Snake": "Solid Snake",
        "Big Boss": "Big Boss (Metal Gear)",
        "Dante": "Dante (Devil May Cry)",
        "Bayonetta": "Bayonetta",
        "Ryu": "Ryu (Street Fighter)",
        "Chun-Li": "Chun-Li",
        "Pikachu": "Pikachu",
        "Charizard": "Charizard",
        "Mewtwo": "Mewtwo",
        "Kirby": "Kirby",
        "Donkey Kong": "Donkey Kong",
        "Fox McCloud": "Fox McCloud",
        "Captain Falcon": "Captain Falcon",
        "Ness": "Ness (EarthBound)",
        "Lucas": "Lucas (Mother 3)",
    },
    "lotr": {
        "Gimli": "Gimli (Middle-earth)",
    },
    "game_of_thrones": {
        "Bran Stark": "Bran Stark (Game of Thrones)",
    },
    "naruto": {
        "Madara Uchiha": "Madara Uchiha",
        "Itachi Uchiha": "Itachi Uchiha",
        "Kakashi Hatake": "Kakashi Hatake",
        "Neji Hyūga": "Neji Hyuga",
        "Hinata Hyūga": "Hinata Hyuga",
        "Kabuto Yakushi": "Kabuto Yakushi",
    },
    "dragon_ball": {
        "Future Trunks": "Future Trunks (Dragon Ball)",
    },
    "star_wars": {
        "Obi-Wan Kenobi": "Obi-Wan Kenobi",
    },
}


def get_wiki_name(theme: str, char_name: str) -> str:
    """Get the wiki-friendly name for a character."""
    if theme in NAME_OVERRIDES and char_name in NAME_OVERRIDES[theme]:
        return NAME_OVERRIDES[theme][char_name]
    return char_name


def get_fandom_image_url(theme: str, char_name: str) -> str | None:
    """Get character image URL from Fandom wiki API - prefers character portraits."""
    domain = FANDOM_DOMAINS.get(theme)
    if not domain:
        return None
    
    wiki_name = get_wiki_name(theme, char_name)
    
    try:
        # Step 1: Search for the page
        search_url = f"https://{domain}/api.php?action=query&list=search&srsearch={urllib.parse.quote(wiki_name)}&srlimit=1&format=json"
        r = requests.get(search_url, headers=HEADERS, timeout=8)
        data = r.json()
        results = data.get("query", {}).get("search", [])
        if not results:
            return None
        
        page_title = results[0]["title"]
        
        # Step 2: Get page images with more details
        img_url = f"https://{domain}/api.php?action=query&prop=images&titles={urllib.parse.quote(page_title)}&imlimit=50&format=json"
        r = requests.get(img_url, headers=HEADERS, timeout=8)
        data = r.json()
        pages = data.get("query", {}).get("pages", {})
        
        # Collect candidate images
        candidates = []
        for page in pages.values():
            for img in page.get("images", []):
                img_title = img["title"]
                # Skip non-image files
                if not any(img_title.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                    continue
                # Skip obvious non-portraits
                skip_terms = ['symbol', 'logo', 'icon', 'flag', 'map', 'seal', 'emblem', 'crest', 'banner', 'sign', 'button', 'ui', 'menu', 'achievement', 'trophy', 'medal', 'coin', 'stamp', 'watermark', 'background', 'pattern', 'texture', 'silhouette', 'outline', 'sketch', 'concept', 'promo', 'wallpaper', 'screenshot', 'scan', 'official_art', 'key_visual', 'keyart', 'render_', '_render', 'model_', '_model', '3d_', '_3d', 'chibi', 'sd_', '_sd', 'mini_', '_mini']
                img_lower = img_title.lower()
                if any(term in img_lower for term in skip_terms):
                    continue
                # Prefer images with character name
                name_match = wiki_name.lower().replace(" ", "_") in img_lower
                # Prefer portrait-like terms
                portrait_terms = ['portrait', 'character', 'render', 'profile', 'face', 'headshot', 'bust', 'artwork', 'illustration', 'official', 'model']
                portrait_score = sum(1 for term in portrait_terms if term in img_lower)
                candidates.append((img_title, name_match, portrait_score))
        
        # Sort: prefer name matches, then portrait terms
        candidates.sort(key=lambda x: (x[1], x[2]), reverse=True)
        
        # Try top candidates
        for img_title, _, _ in candidates[:10]:
            file_url = f"https://{domain}/api.php?action=query&titles={urllib.parse.quote(img_title)}&prop=imageinfo&iiprop=url|size&iiurlwidth=600&format=json"
            r = requests.get(file_url, headers=HEADERS, timeout=8)
            data = r.json()
            for p in data.get("query", {}).get("pages", {}).values():
                for ii in p.get("imageinfo", []):
                    url = ii.get("url")
                    # Prefer larger images (character portraits are usually bigger)
                    width = ii.get("width", 0)
                    height = ii.get("height", 0)
                    if url and width > 100 and height > 100:
                        return url
        
        # Fallback: try to get the page's main image (pageimage)
        page_img_url = f"https://{domain}/api.php?action=query&prop=pageimages&titles={urllib.parse.quote(page_title)}&piprop=original&format=json"
        r = requests.get(page_img_url, headers=HEADERS, timeout=8)
        data = r.json()
        for p in data.get("query", {}).get("pages", {}).values():
            if "original" in p:
                return p["original"]["source"]
        
    except Exception as e:
        print(f"    API error for {char_name}: {e}")
    return None


def download_image(url: str, dest: Path) -> bool:
    temp = dest.with_suffix(".tmp")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15, stream=True)
        r.raise_for_status()
        
        # Check content type
        content_type = r.headers.get("content-type", "")
        if not content_type.startswith("image/"):
            print(f"    Not an image: {content_type} for {url[:60]}...")
            return False
        
        # Download to temp
        with open(temp, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        
        # Verify it's a valid image and convert
        try:
            with Image.open(temp) as im:
                im.verify()  # Verify it's a valid image
        except Exception:
            print(f"    Invalid image file from {url[:60]}...")
            temp.unlink(missing_ok=True)
            return False
        
        # Re-open for processing (verify closes the file)
        with Image.open(temp) as im:
            # Handle various modes
            if im.mode in ("RGBA", "LA"):
                # Keep transparency for WebP
                pass
            elif im.mode == "P":
                im = im.convert("RGBA")
            elif im.mode not in ("RGB", "RGBA"):
                im = im.convert("RGB")
            
            if max(im.size) > 600:
                im.thumbnail((600, 600), Image.Resampling.LANCZOS)
            
            im.save(dest, "WEBP", quality=85, method=6)
        
        temp.unlink(missing_ok=True)
        return True
    except Exception as e:
        print(f"    Download failed for {url[:60]}...: {e}")
        temp.unlink(missing_ok=True)
        return False


def process_character(args):
    """Process a single character - for thread pool."""
    theme_id, char, static_dir = args
    char_id = char["id"]
    char_name = char["name"]
    dest = static_dir / f"{char_id}.webp"
    
    if dest.exists():
        return (char_id, True, "exists")
    
    url = get_fandom_image_url(theme_id, char_name)
    if url and download_image(url, dest):
        return (char_id, True, url)
    return (char_id, False, "failed")


def process_theme(theme_id: str, max_workers: int = 4):
    """Process a theme with concurrent downloads."""
    print(f"\n=== {theme_id} ===")
    
    with open(THEME_DIR / f"{theme_id}.json") as f:
        data = json.load(f)
    
    static_dir = STATIC_BASE / theme_id
    static_dir.mkdir(parents=True, exist_ok=True)
    
    # Prepare args for thread pool
    args_list = [(theme_id, char, static_dir) for char in data["characters"]]
    
    updated = False
    success = 0
    failed = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_character, args): args[1]["id"] for args in args_list}
        
        for future in as_completed(futures):
            char_id, ok, info = future.result()
            char = next(c for c in data["characters"] if c["id"] == char_id)
            if ok:
                if info != "exists":
                    print(f"  ✓ {char['name']}")
                    char["image"] = f"/static/auction/themes/{theme_id}/{char_id}.webp"
                    updated = True
                success += 1
            else:
                print(f"  ✗ {char['name']}")
                failed.append(char['name'])
    
    if updated:
        with open(THEME_DIR / f"{theme_id}.json", "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Updated JSON")
    
    print(f"  Result: {success}/{len(data['characters'])} downloaded")
    return success, failed


def main():
    import sys
    theme = sys.argv[1] if len(sys.argv) > 1 else None
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 4
    
    if theme:
        process_theme(theme, workers)
    else:
        for t in sorted(FANDOM_DOMAINS.keys()):
            process_theme(t, workers)
            time.sleep(1)


if __name__ == "__main__":
    main()
