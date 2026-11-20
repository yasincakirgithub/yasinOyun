#!/usr/bin/env python3
"""
Auction Game - Theme Character Image Fetcher
============================================
Bu script auction temaları için karakter resimlerini Yandex Görseller'den çeker,
WebP formatında optimize edip static klasörüne kaydeder.

Kullanım:
    python auction/tools/fetch_theme_images.py --theme marvel
    python auction/tools/fetch_theme_images.py --all
    python auction/tools/fetch_theme_images.py --theme naruto --candidates 12
    python auction/tools/fetch_theme_images.py --list
"""

from __future__ import annotations

import argparse
import html
import io
import json
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image

# -----------------------------------------------------------------------------
# KONFİGÜRASYON
# -----------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent.parent
THEME_DATA_DIR = BASE_DIR / "auction" / "themes" / "data"
STATIC_THEMES_DIR = BASE_DIR / "auction" / "static" / "auction" / "themes"
CACHE_DIR = BASE_DIR / ".theme_image_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}

# Yandex HTML'den image URL'lerini çıkarmak için regex
PATTERN = re.compile(
    r'"origUrl":"(?P<url>.*?)".*?"snippet":\{'
    r'"title":"(?P<title>.*?)","domain":"(?P<domain>.*?)"'
)

# Her tema için arama prefix'i ve karakter listesi (id, search_name)
THEME_CONFIG = {
    "marvel": {
        "prefix": "Marvel movie",
        "chars": [
            ("marvel_iron_man", "Iron Man Robert Downey Jr"),
            ("marvel_thor", "Thor Chris Hemsworth"),
            ("marvel_hulk", "Hulk Mark Ruffalo"),
            ("marvel_spider_man", "Spider-Man Tom Holland"),
            ("marvel_thanos", "Thanos Josh Brolin"),
            ("marvel_doctor_strange", "Doctor Strange Benedict Cumberbatch"),
            ("marvel_captain_america", "Captain America Chris Evans"),
            ("marvel_black_widow", "Black Widow Scarlett Johansson"),
            ("marvel_hawkeye", "Hawkeye Jeremy Renner"),
            ("marvel_loki", "Loki Tom Hiddleston"),
            ("marvel_black_panther", "Black Panther Chadwick Boseman"),
            ("marvel_captain_marvel", "Captain Marvel Brie Larson"),
            ("marvel_scarlet_witch", "Scarlet Witch Elizabeth Olsen"),
            ("marvel_vision", "Vision Paul Bettany"),
            ("marvel_ant_man", "Ant-Man Paul Rudd"),
            ("marvel_wasp", "Wasp Evangeline Lilly"),
            ("marvel_star_lord", "Star-Lord Chris Pratt"),
            ("marvel_gamora", "Gamora Zoe Saldana"),
            ("marvel_drax", "Drax Dave Bautista"),
            ("marvel_rocket", "Rocket Raccoon Bradley Cooper"),
            ("marvel_groot", "Groot Vin Diesel"),
            ("marvel_wong", "Wong Benedict Wong"),
            ("marvel_shang_chi", "Shang-Chi Simu Liu"),
            ("marvel_ms_marvel", "Ms. Marvel Iman Vellani"),
            ("marvel_she_hulk", "She-Hulk Tatiana Maslany"),
            ("marvel_moon_knight", "Moon Knight Oscar Isaac"),
            ("marvel_deadpool", "Deadpool Ryan Reynolds"),
            ("marvel_wolverine", "Wolverine Hugh Jackman"),
            ("marvel_magneto", "Magneto Ian McKellen Michael Fassbender"),
            ("marvel_professor_x", "Professor X Patrick Stewart James McAvoy"),
            ("marvel_mystique", "Mystique Jennifer Lawrence Rebecca Romijn"),
            ("marvel_venom", "Venom Tom Hardy"),
        ],
    },
    "dc": {
        "prefix": "DC movie",
        "chars": [
            ("dc_superman", "Superman Henry Cavill"),
            ("dc_batman", "Batman Christian Bale Robert Pattinson Ben Affleck"),
            ("dc_wonder_woman", "Wonder Woman Gal Gadot"),
            ("dc_flash", "Flash Ezra Miller Grant Gustin"),
            ("dc_aquaman", "Aquaman Jason Momoa"),
            ("dc_cyborg", "Cyborg Ray Fisher"),
            ("dc_green_lantern", "Green Lantern Ryan Reynolds"),
            ("dc_shazam", "Shazam Zachary Levi"),
            ("dc_black_adam", "Black Adam Dwayne Johnson"),
            ("dc_joker", "Joker Joaquin Phoenix Heath Ledger"),
            ("dc_harley_quinn", "Harley Quinn Margot Robbie"),
            ("dc_lex_luthor", "Lex Luthor Jesse Eisenberg"),
            ("dc_general_zod", "General Zod Michael Shannon"),
            ("dc_doomsday", "Doomsday"),
            ("dc_darkseid", "Darkseid"),
            ("dc_brainiac", "Brainiac"),
            ("dc_deathstroke", "Deathstroke"),
            ("dc_catwoman", "Catwoman Zoe Kravitz Anne Hathaway"),
            ("dc_bane", "Bane Tom Hardy"),
            ("dc_penguin", "Penguin Colin Farrell"),
            ("dc_riddler", "Riddler Paul Dano"),
            ("dc_scarecrow", "Scarecrow Cillian Murphy"),
            ("dc_poison_ivy", "Poison Ivy"),
            ("dc_mr_freeze", "Mr. Freeze"),
            ("dc_robin", "Robin Dick Grayson"),
            ("dc_nightwing", "Nightwing"),
            ("dc_batgirl", "Batgirl"),
            ("dc_supergirl", "Supergirl Melissa Benoist"),
        ],
    },
    "harry_potter": {
        "prefix": "Harry Potter movie",
        "chars": [
            ("hp_harry_potter", "Harry Potter Daniel Radcliffe"),
            ("hp_voldemort", "Lord Voldemort Ralph Fiennes"),
            ("hp_dumbledore", "Albus Dumbledore Richard Harris Michael Gambon"),
            ("hp_hermione", "Hermione Granger Emma Watson"),
            ("hp_ron", "Ron Weasley Rupert Grint"),
            ("hp_severus_snape", "Severus Snape Alan Rickman"),
            ("hp_sirius", "Sirius Black Gary Oldman"),
            ("hp_draco", "Draco Malfoy Tom Felton"),
            ("hp_hagrid", "Rubeus Hagrid Robbie Coltrane"),
            ("hp_luna", "Luna Lovegood Evanna Lynch"),
            ("hp_neville", "Neville Longbottom Matthew Lewis"),
            ("hp_bellatrix", "Bellatrix Lestrange Helena Bonham Carter"),
            ("hp_remus", "Remus Lupin David Thewlis"),
            ("hp_minerva", "Minerva McGonagall Maggie Smith"),
            ("hp_dobby", "Dobby"),
            ("hp_fred_george", "Fred George Weasley James Phelps Oliver Phelps"),
            ("hp_ginny", "Ginny Weasley Bonnie Wright"),
            ("hp_cho", "Cho Chang Katie Leung"),
            ("hp_cedric", "Cedric Diggory Robert Pattinson"),
            ("hp_flitwick", "Filius Flitwick Warwick Davis"),
            ("hp_mcgonagall", "Minerva McGonagall Maggie Smith"),
            ("hp_slughorn", "Horace Slughorn Jim Broadbent"),
            ("hp_molly", "Molly Weasley Julie Walters"),
            ("hp_arthur", "Arthur Weasley Mark Williams"),
        ],
    },
    "game_of_thrones": {
        "prefix": "Game of Thrones HBO",
        "chars": [
            ("got_jon_snow", "Jon Snow Kit Harington"),
            ("got_daenerys", "Daenerys Targaryen Emilia Clarke"),
            ("got_night_king", "Night King"),
            ("got_tyrion", "Tyrion Lannister Peter Dinklage"),
            ("got_cersei", "Cersei Lannister Lena Headey"),
            ("got_jaime", "Jaime Lannister Nikolaj Coster-Waldau"),
            ("got_sansa", "Sansa Stark Sophie Turner"),
            ("got_arya", "Arya Stark Maisie Williams"),
            ("got_bran", "Bran Stark Isaac Hempstead Wright"),
            ("got_hodor", "Hodor Kristian Nairn"),
            ("got_brienne", "Brienne of Tarth Gwendoline Christie"),
            ("got_jora", "Jorah Mormont Iain Glen"),
            ("got_davos", "Davos Seaworth Liam Cunningham"),
            ("got_tormund", "Tormund Giantsbane Kristofer Hivju"),
            ("got_samwell", "Samwell Tarly John Bradley"),
            ("got_jaqen", "Jaqen H'ghar Tom Wlaschiha"),
            ("got_obara", "Obara Sand Keisha Castle-Hughes"),
            ("got_ellaria", "Ellaria Sand Indira Varma"),
            ("got_missandei", "Missandei Nathalie Emmanuel"),
            ("got_grey_worm", "Grey Worm Jacob Anderson"),
            ("got_varys", "Varys Conleth Hill"),
            ("got_littlefinger", "Littlefinger Aidan Gillen"),
            ("got_roose", "Roose Bolton Michael McElhatton"),
            ("got_ramsey", "Ramsey Bolton Iwan Rheon"),
            ("got_stannis", "Stannis Baratheon Stephen Dillane"),
        ],
    },
    "naruto": {
        "prefix": "Naruto anime",
        "chars": [
            ("naruto_naruto", "Naruto Uzumaki"),
            ("naruto_sasuke", "Sasuke Uchiha"),
            ("naruto_madara", "Madara Uchiha"),
            ("naruto_kakashi", "Kakashi Hatake"),
            ("naruto_itachi", "Itachi Uchiha"),
            ("naruto_obito", "Obito Uchiha"),
            ("naruto_pain", "Pain Nagato"),
            ("naruto_jiraiya", "Jiraiya"),
            ("naruto_orochimaru", "Orochimaru"),
            ("naruto_tsunade", "Tsunade"),
            ("naruto_gaara", "Gaara"),
            ("naruto_minato", "Minato Namikaze"),
            ("naruto_hashirama", "Hashirama Senju"),
            ("naruto_tobirama", "Tobirama Senju"),
            ("naruto_hiruzen", "Hiruzen Sarutobi"),
            ("naruto_danzou", "Danzo Shimura"),
            ("naruto_kisame", "Kisame Hoshigaki"),
            ("naruto_deidara", "Deidara"),
            ("naruto_sasori", "Sasori"),
            ("naruto_hidan", "Hidan"),
            ("naruto_kakuzu", "Kakuzu"),
            ("naruto_konan", "Konan"),
            ("naruto_zetsu", "Zetsu"),
            ("naruto_karin", "Karin Uzumaki"),
            ("naruto_suigetsu", "Suigetsu Hozuki"),
            ("naruto_juugo", "Jugo"),
            ("naruto_kabuto", "Kabuto Yakushi"),
            ("naruto_yamato", "Yamato"),
        ],
    },
    "dragon_ball": {
        "prefix": "Dragon Ball anime",
        "chars": [
            ("db_goku", "Son Goku"),
            ("db_vegeta", "Vegeta"),
            ("db_frieza", "Frieza"),
            ("db_cell", "Cell"),
            ("db_majin_buu", "Majin Buu"),
            ("db_gohan", "Gohan"),
            ("db_piccolo", "Piccolo"),
            ("db_krillin", "Krillin"),
            ("db_android_18", "Android 18"),
            ("db_android_17", "Android 17"),
            ("db_trunks", "Trunks"),
            ("db_goten", "Goten"),
            ("db_bardock", "Bardock"),
            ("db_broly", "Broly"),
            ("db_gogeta", "Gogeta"),
            ("db_vegetto", "Vegito"),
            ("db_beerus", "Beerus"),
            ("db_whis", "Whis"),
            ("db_jiren", "Jiren"),
            ("db_hit", "Hit"),
            ("db_toppo", "Toppo"),
            ("db_goku_black", "Goku Black"),
            ("db_zamasu", "Zamasu"),
            ("db_tien", "Tien Shinhan"),
            ("db_yamcha", "Yamcha"),
            ("db_roshi", "Master Roshi"),
            ("db_shenron", "Shenron"),
        ],
    },
    "one_piece": {
        "prefix": "One Piece anime",
        "chars": [
            ("op_luffy", "Monkey D. Luffy"),
            ("op_zoro", "Roronoa Zoro"),
            ("op_shanks", "Shanks"),
            ("op_sanji", "Sanji"),
            ("op_nami", "Nami"),
            ("op_usopp", "Usopp"),
            ("op_chopper", "Tony Tony Chopper"),
            ("op_robin", "Nico Robin"),
            ("op_franky", "Franky"),
            ("op_brook", "Brook"),
            ("op_jinbe", "Jinbe"),
            ("op_ace", "Portgas D. Ace"),
            ("op_sabo", "Sabo"),
            ("op_whitebeard", "Whitebeard Edward Newgate"),
            ("op_kaido", "Kaido"),
            ("op_big_mom", "Big Mom Charlotte Linlin"),
            ("op_law", "Trafalgar Law"),
            ("op_kid", "Eustass Kid"),
            ("op_killer", "Killer"),
            ("op_drake", "X Drake"),
            ("op_hawkins", "Basil Hawkins"),
            ("op_apoo", "Scratchmen Apoo"),
            ("op_uki", "Urouge"),
            ("op_bonney", "Jewelry Bonney"),
            ("op_katakuri", "Charlotte Katakuri"),
            ("op_doflamingo", "Doflamingo"),
            ("op_crocodile", "Crocodile"),
            ("op_enel", "Enel"),
        ],
    },
    "star_wars": {
        "prefix": "Star Wars movie",
        "chars": [
            ("sw_darth_vader", "Darth Vader Anakin Skywalker"),
            ("sw_luke_skywalker", "Luke Skywalker Mark Hamill"),
            ("sw_yoda", "Yoda"),
            ("sw_obi_wan", "Obi-Wan Kenobi Ewan McGregor Alec Guinness"),
            ("sw_leia", "Princess Leia Carrie Fisher"),
            ("sw_han_solo", "Han Solo Harrison Ford"),
            ("sw_chewbacca", "Chewbacca"),
            ("sw_r2d2", "R2-D2"),
            ("sw_c3po", "C-3PO"),
            ("sw_palpatine", "Emperor Palpatine Ian McDiarmid"),
            ("sw_maul", "Darth Maul Ray Park"),
            ("sw_dooku", "Count Dooku Christopher Lee"),
            ("sw_grievous", "General Grievous"),
            ("sw_boba_fett", "Boba Fett Temuera Morrison"),
            ("sw_jango_fett", "Jango Fett Temuera Morrison"),
            ("sw_rey", "Rey Daisy Ridley"),
            ("sw_finn", "Finn John Boyega"),
            ("sw_poe", "Poe Dameron Oscar Isaac"),
            ("sw_kylo_ren", "Kylo Ren Adam Driver"),
            ("sw_hux", "General Hux Domhnall Gleeson"),
            ("sw_phasma", "Captain Phasma Gwendoline Christie"),
            ("sw_snoke", "Supreme Leader Snoke Andy Serkis"),
            ("sw_mandalorian", "The Mandalorian Din Djarin Pedro Pascal"),
            ("sw_grogu", "Grogu Baby Yoda"),
            ("sw_ahsoka", "Ahsoka Tano Rosario Dawson"),
            ("sw_kenobi", "Obi-Wan Kenobi Ewan McGregor"),
        ],
    },
    "video_games": {
        "prefix": "video game character",
        "chars": [
            ("vg_kratos", "Kratos God of War"),
            ("vg_master_chief", "Master Chief Halo"),
            ("vg_lara_croft", "Lara Croft Tomb Raider"),
            ("vg_mario", "Mario Nintendo"),
            ("vg_link", "Link Zelda"),
            ("vg_samus", "Samus Metroid"),
            ("vg_geralt", "Geralt The Witcher"),
            ("vg_ciri", "Ciri The Witcher"),
            ("vg_arthas", "Arthas Warcraft"),
            ("vg_illidan", "Illidan Warcraft"),
            ("vg_ezio", "Ezio Assassin's Creed"),
            ("vg_altair", "Altair Assassin's Creed"),
            ("vg_joel", "Joel The Last of Us"),
            ("vg_ellie", "Ellie The Last of Us"),
            ("vg_arthur", "Arthur Morgan Red Dead Redemption"),
            ("vg_john_marston", "John Marston Red Dead Redemption"),
            ("vg_cloud", "Cloud Strife Final Fantasy"),
            ("vg_sephiroth", "Sephiroth Final Fantasy"),
            ("vg_tifa", "Tifa Lockhart Final Fantasy"),
            ("vg_aerith", "Aerith Final Fantasy"),
            ("vg_dante", "Dante Devil May Cry"),
            ("vg_vergil", "Vergil Devil May Cry"),
            ("vg_ryu", "Ryu Street Fighter"),
            ("vg_ken", "Ken Street Fighter"),
            ("vg_chun_li", "Chun-Li Street Fighter"),
            ("vg_solid_snake", "Solid Snake Metal Gear"),
            ("vg_big_boss", "Big Boss Metal Gear"),
            ("vg_gordon_freeman", "Gordon Freeman Half-Life"),
            ("vg_doom_slayer", "Doom Slayer Doom"),
            ("vg_kirby", "Kirby Nintendo"),
        ],
    },
    "lotr": {
        "prefix": "Lord of the Rings movie",
        "chars": [
            ("lotr_gandalf", "Gandalf Ian McKellen"),
            ("lotr_sauron", "Sauron"),
            ("lotr_aragorn", "Aragorn Viggo Mortensen"),
            ("lotr_legolas", "Legolas Orlando Bloom"),
            ("lotr_frodo", "Frodo Baggins Elijah Wood"),
            ("lotr_sam", "Samwise Gamgee Sean Astin"),
            ("lotr_gimli", "Gimli"),
            ("lotr_saruman", "Saruman Ian Holm"),
            ("lotr_galadriel", "Galadriel Cate Blanchett"),
            ("lotr_boromir", "Boromir Sean Bean"),
            ("lotr_gollum", "Gollum Andy Serkis"),
            ("lotr_elrond", "Elrond Hugo Weaving"),
            ("lotr_theoden", "Theoden Bernard Hill"),
            ("lotr_eowyn", "Eowyn Miranda Otto"),
            ("lotr_faramir", "Faramir"),
            ("lotr_treebeard", "Treebeard John Noble"),
            ("lotr_witch_king", "Witch-king of Angmar"),
            ("lotr_balrog", "Balrog Durin's Bane"),
            ("lotr_tom_bombadil", "Tom Bombadil"),
            ("lotr_glorfindel", "Glorfindel"),
            ("lotr_haldir", "Haldir"),
            ("lotr_beregor", "Beregond"),
            ("lotr_halbarad", "Halbarad"),
            ("lotr_erkenbrand", "Erkenbrand"),
            ("lotr_grima", "Grima Wormtongue"),
        ],
    },
    "kurtlar_vadisi": {
        "prefix": "Kurtlar Vadisi dizisi",
        "chars": [
            ("kv_polat", "Polat Alemdar Necati Şaşmaz"),
            ("kv_memati", "Memati Baş Mehmet Özgür"),
            ("kv_abdulhey", "Abdülhey Çoban Kenan Çoban"),
            ("kv_aslan", "Aslan Akbey Uğur Polat"),
            ("kv_baron", "Baron Bülent Çetinaslan"),
            ("kv_cakir", "Çakır Erhan Ufak"),
            ("kv_canan", "Canan Şener Kökkaya"),
            ("kv_dogu", "Doğu Yıldırım Taner Ölmez"),
            ("kv_derya", "Derya Deniz Çakır"),
            ("kv_elif", "Elif Eylül Cansın Özyosun"),
            ("kv_ergin", "Ergin Ataman Serdar Orçin"),
            ("kv_erhan", "Erhan Ufak"),
            ("kv_halil", "Halil İbrahim Kurum"),
            ("kv_husrev", "Hüsrev Cengiz Küçükayvaz"),
            ("kv_iplikci", "İplikçi Necati Şaşmaz"),
            ("kv_kilic", "Kılıç Ali Ufuk Özkan"),
            ("kv_lazziya", "Laz Ziya Erkan Petekkaya"),
            ("kv_meral", "Meral Öztürk"),
            ("kv_nesrin", "Nesrin Cavit"),
            ("kv_nizamettin", "Nizamettin Güç"),
            ("kv_safiye", "Safiye Hande Subaşı"),
            ("kv_samuel", "Samuel"),
            ("kv_seyfo", "Seyfo"),
            ("kv_testere", "Testere Necati Şaşmaz"),
            ("kv_tombalaci", "Tombalacı"),
            ("kv_tuncay", "Tuncay"),
        ],
    },
    "attack_on_titan": {
        "prefix": "Attack on Titan anime",
        "chars": [
            ("aot_eren", "Eren Yeager"),
            ("aot_mikasa", "Mikasa Ackerman"),
            ("aot_armin", "Armin Arlert"),
            ("aot_levi", "Levi Ackerman"),
            ("aot_erwin", "Erwin Smith"),
            ("aot_hange", "Hange Zoe"),
            ("aot_reiner", "Reiner Braun"),
            ("aot_bertholdt", "Bertholdt Hoover"),
            ("aot_annie", "Annie Leonhart"),
            ("aot_jeaan", "Jean Kirstein"),
            ("aot_connie", "Connie Springer"),
            ("aot_sasha", "Sasha Blouse"),
            ("aot_historia", "Historia Reiss"),
            ("aot_yelena", "Yelena"),
            ("aot_floch", "Floch Forster"),
            ("aot_zeke", "Zeke Yeager"),
            ("aot_rod", "Rod Reiss"),
            ("aot_kenny", "Kenny Ackerman"),
            ("aot_marlowe", "Marlowe Freudenberg"),
            ("aot_hitch", "Hitch Dreyse"),
            ("aot_porco", "Porco Galliard"),
            ("aot_pieck", "Pieck Finger"),
            ("aot_colt", "Colt Grice"),
            ("aot_magath", "Theo Magath"),
            ("aot_kruger", "Eren Kruger"),
        ],
    },
    "demon_slayer": {
        "prefix": "Demon Slayer anime",
        "chars": [
            ("ds_tanjiro", "Tanjiro Kamado"),
            ("ds_nezuko", "Nezuko Kamado"),
            ("ds_zenitsu", "Zenitsu Agatsuma"),
            ("ds_inosuke", "Inosuke Hashibira"),
            ("ds_giyu", "Giyu Tomioka"),
            ("ds_shinobu", "Shinobu Kocho"),
            ("ds_kyojuro", "Kyojuro Rengoku"),
            ("ds_tengen", "Tengen Uzui"),
            ("ds_mitsuri", "Mitsuri Kanroji"),
            ("ds_muichiro", "Muichiro Tokito"),
            ("ds_gyomei", "Gyomei Himejima"),
            ("ds_sanemi", "Sanemi Shinazugawa"),
            ("ds_obi", "Obanai Iguro"),
            ("ds_kanao", "Kanao Tsuyuri"),
            ("ds_genya", "Genya Shinazugawa"),
            ("ds_muzan", "Muzan Kibutsuji"),
            ("ds_kokushibo", "Kokushibo"),
            ("ds_doma", "Doma"),
            ("ds_akaza", "Akaza"),
            ("ds_hantengu", "Hantengu"),
            ("ds_gyokko", "Gyokko"),
            ("ds_daki", "Daki"),
            ("ds_gyutaro", "Gyutaro"),
            ("ds_kaigaku", "Kaigaku"),
            ("ds_yoriichi", "Yoriichi Tsugikuni"),
        ],
    },
    "my_hero_academia": {
        "prefix": "My Hero Academia anime",
        "chars": [
            ("mha_deku", "Izuku Midoriya"),
            ("mha_bakugo", "Katsuki Bakugo"),
            ("mha_todoroki", "Shoto Todoroki"),
            ("mha_all_might", "All Might"),
            ("mha_endeavor", "Endeavor"),
            ("mha_hawks", "Hawks"),
            ("mha_best_jeanist", "Best Jeanist"),
            ("mha_erasure", "Eraser Head Aizawa"),
            ("mha_present_mic", "Present Mic"),
            ("mha_midnight", "Midnight"),
            ("mha_mirko", "Mirko"),
            ("mha_edgeshot", "Edgeshot"),
            ("mha_wash", "Wash"),
            ("mha_manual", "Manual"),
            ("mha_uravity", "Ochaco Uraraka"),
            ("mha_froppy", "Tsuyu Asui"),
            ("mha_idaten", "Tenya Iida"),
            ("mha_yaoyorozu", "Momo Yaoyorozu"),
            ("mha_kirishima", "Eijiro Kirishima"),
            ("mha_kaminari", "Denki Kaminari"),
            ("mha_mineta", "Minoru Mineta"),
            ("mha_ashido", "Mina Ashido"),
            ("mha_shoji", "Mezo Shoji"),
            ("mha_aoyama", "Yuga Aoyama"),
            ("mha_hagakure", "Torou Hagakure"),
            ("mha_shinsou", "Hitoshi Shinsou"),
            ("mha_monoma", "Neito Monoma"),
            ("mha_kendo", "Itsuka Kendo"),
        ],
    },
    "jujutsu_kaisen": {
        "prefix": "Jujutsu Kaisen anime",
        "chars": [
            ("jjk_yuji", "Yuji Itadori"),
            ("jjk_megumi", "Megumi Fushiguro"),
            ("jjk_nobara", "Nobara Kugisaki"),
            ("jjk_gojo", "Satoru Gojo"),
            ("jjk_geto", "Suguru Geto"),
            ("jjk_nanami", "Kento Nanami"),
            ("jjk_megumi_shoko", "Shoko Ieiri"),
            ("jjk_maki", "Maki Zenin"),
            ("jjk_toge", "Toge Inumaki"),
            ("jjk_panda", "Panda"),
            ("jjk_yuta", "Yuta Okkotsu"),
            ("jjk_miguel", "Miguel"),
            ("jjk_larue", "Larue"),
            ("jjk_choso", "Choso"),
            ("jjk_esou", "Esou"),
            ("jjk_kechizu", "Kechizu"),
            ("jjk_mahito", "Mahito"),
            ("jjk_jogo", "Jogo"),
            ("jjk_hanami", "Hanami"),
            ("jjk_dagon", "Dagon"),
            ("jjk_sukuna", "Ryomen Sukuna"),
            ("jjk_kenjaku", "Kenjaku"),
            ("jjk_urume", "Uraume"),
            ("jjk_higuruma", "Hiromi Higuruma"),
            ("jjk_kashimo", "Hajime Kashimo"),
        ],
    },
    "cyberpunk": {
        "prefix": "Cyberpunk 2077 Edgerunners",
        "chars": [
            ("cp_david", "David Martinez"),
            ("cp_lucy", "Lucy"),
            ("cp_maine", "Maine"),
            ("cp_dorio", "Dorio"),
            ("cp_kiwi", "Kiwi"),
            ("cp_rebecca", "Rebecca"),
            ("cp_pilar", "Pilar"),
            ("cp_falco", "Falco"),
            ("cp_v", "V"),
            ("cp_johnny", "Johnny Silverhand"),
            ("cp_panam", "Panam Palmer"),
            ("cp_judy", "Judy Alvarez"),
            ("cp_river", "River Ward"),
            ("cp_kerry", "Kerry Eurodyne"),
            ("cp_rogue", "Rogue Amendiares"),
            ("cp_alt", "Alt Cunningham"),
            ("cp_saburo", "Saburo Arasaka"),
            ("cp_hanako", "Hanako Arasaka"),
            ("cp_yorinobu", "Yorinobu Arasaka"),
            ("cp_takemura", "Goro Takemura"),
            ("cp_maiko", "Maiko"),
            ("cp_smasher", "Adam Smasher"),
            ("cp_dex", "Dexter DeShawn"),
            ("cp_t_bug", "T-Bug"),
            ("cp_viktor", "Viktor"),
        ],
    },
    "elden_ring": {
        "prefix": "Elden Ring game",
        "chars": [
            ("er_malenia", "Malenia Blade of Miquella"),
            ("er_radahn", "Starscourge Radahn"),
            ("er_rderick", "Godrick the Grafted"),
            ("er_rykard", "Rykard Lord of Blasphemy"),
            ("er_rennala", "Rennala Queen of the Full Moon"),
            ("er_mohg", "Mohg Lord of Blood"),
            ("er_morgott", "Morgott the Omen King"),
            ("er_miquella", "Miquella of the Haligtree"),
            ("er_radagon", "Radagon of the Golden Order"),
            ("er_marika", "Marika the Eternal"),
            ("er_gideon", "Gideon Ofnir"),
            ("er_fia", "Fia Deathbed Companion"),
            ("er_rhya", "Rya"),
            ("er_roger", "Rogier"),
            ("er_d", "D Hunter of the Dead"),
            ("er_nep", "Nepheli Loux"),
            ("er_kenneth", "Kenneth Haight"),
            ("er_jarren", "Jarren"),
            ("er_boc", "Boc the Seamster"),
            ("er_patches", "Patches"),
            ("er_alexander", "Iron Fist Alexander"),
            ("er_jar_bae", "Jar-Bairn"),
            ("er_millicent", "Millicent"),
            ("er_gowry", "Gowry"),
            ("er_tanith", "Tanith"),
        ],
    },
    "super_lig": {
        "prefix": "Turkish Super Lig football",
        "chars": [
            ("sl_galatasaray", "Galatasaray SK"),
            ("sl_fenerbahce", "Fenerbahçe SK"),
            ("sl_besiktas", "Beşiktaş JK"),
            ("sl_trabzonspor", "Trabzonspor"),
            ("sl_basaksehir", "İstanbul Başakşehir"),
            ("sl_hatayspor", "Hatayspor"),
            ("sl_kasimpasa", "Kasımpaşa SK"),
            ("sl_kayserispor", "Kayserispor"),
            ("sl_antalyaspor", "Antalyaspor"),
            ("sl_gaziantep", "Gaziantep FK"),
            ("sl_rize", "Çaykur Rizespor"),
            ("sl_sivasspor", "Sivasspor"),
            ("sl_alanyaspor", "Alanyaspor"),
            ("sl_konyaspor", "Konyaspor"),
            ("sl_samsunspor", "Samsunspor"),
            ("sl_pendikspor", "Pendikspor"),
            ("sl_anadolu", "Ankaragücü"),
            ("sl_fatihkaragumruk", "Fatih Karagümrük"),
            ("sl_umraniyespor", "Ümraniyespor"),
            ("sl_giresunspor", "Giresunspor"),
            ("sl_osmanlispor", "Osmanlıspor"),
            ("sl_akhisarspor", "Akhisarspor"),
            ("sl_balikesirspor", "Balıkesirspor"),
            ("sl_denizlispor", "Denizlispor"),
            ("sl_genclerbirligi", "Gençlerbirliği"),
            ("sl_eskisehirspor", "Eskişehirspor"),
            ("sl_mersin", "Mersin İdmanyurdu"),
            ("sl_adanaspor", "Adanaspor"),
        ],
    },
    "turk_influencers": {
        "prefix": "Turkish social media influencer",
        "chars": [
            ("ti_brutalcizim", "Brutal Çizim"),
            ("ti_ensar", "Ensar"),
            ("ti_yasin", "Yasin"),
            ("ti_berkcan", "Berkcan Güven"),
            ("ti_orhan", "Orhan Awatramani"),
            ("ti_elif", "Elif Şafak"),
            ("ti_burak", "Burak Özdemir (CZN Burak)"),
            ("ti_didem", "Didem Soydan"),
            ("ti_zeynep", "Zeynep Bastık"),
            ("ti_murat", "Murat Boz"),
            ("ti_hande", "Hande Erçel"),
            ("ti_kerem", "Kerem Bürsin"),
            ("ti_cemre", "Cemre Baysel"),
            ("ti_afra", "Afra Saraçoğlu"),
            ("ti_mert", "Mert Yazıcıoğlu"),
            ("ti_boran", "Boran Kuzum"),
            ("ti_alperen", "Alperen Duymaz"),
            ("ti_ugur", "Uğur Güneş"),
            ("ti_engin", "Engin Altan Düzyatan"),
            ("ti_burak_deniz", "Burak Deniz"),
            ("ti_alina", "Alina Boz"),
            ("ti_su", "Su Burcu Yazgı Coşkun"),
            ("ti_halit", "Halit Özgür Sarı"),
            ("ti_serkan", "Serkan Çayoğlu"),
            ("ti_alperen_duymaz", "Alperen Duymaz"),
        ],
    },
    "turk_youtubers": {
        "prefix": "Turkish YouTuber",
        "chars": [
            ("ty_murat", "Murat Cesur (MCT)"),
            ("ty_enes", "Enes Batur"),
            ("ty_berkay", "Berkay Öztürk"),
            ("ty_oguz", "Oğuzhan Uğur"),
            ("ty_boray", "Boray"),
            ("ty_kadir", "Kadir Döner"),
            ("ty_mete", "Mete Kök"),
            ("ty_cemre", "Cemre Baysel"),
            ("ty_alper", "Alper Rende"),
            ("ty_volkan", "Volkan"),
            ("ty_burak", "Burak Özdemir"),
            ("ty_orhan", "Orhan Awatramani"),
            ("ty_berkcan", "Berkcan Güven"),
            ("ti_yusuf", "Yusuf Aktaş"),
            ("ti_berk", "Berk Öztürk"),
            ("ti_emirhan", "Emirhan"),
            ("ti_oguzhan", "Oğuzhan Koç"),
            ("ti_emrah", "Emrah"),
            ("ti_burakcan", "Burakcan"),
            ("ti_berkayy", "Berkay Yıldız"),
            ("ti_cem", "Cem Yılmaz"),
            ("ti_ahmet", "Ahmet Çakar"),
            ("ti_onur", "Onur Öz"),
            ("ti_volkan_sahin", "Volkan Şahin"),
            ("ti_eren", "Eren Bülbül"),
            ("ti_mustafa", "Mustafa"),
            ("ti_selami", "Selami Şahin"),
            ("ty_berkcan_youtube", "Berkcan Güven (YouTube)"),
        ],
    },
}


# -----------------------------------------------------------------------------
# YARDIMCI FONKSİYONLAR
# -----------------------------------------------------------------------------


def search_images(session: requests.Session, query: str) -> list[dict[str, str]]:
    """Yandex Görseller'de arama yap, sonuç URL'lerini döndür."""
    response = session.get(
        "https://yandex.com/images/search",
        params={"text": query},
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    text = html.unescape(response.text)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for match in PATTERN.finditer(text):
        url = match.group("url").replace("\\/", "/")
        if url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "url": url,
                "title": match.group("title"),
                "domain": match.group("domain"),
            }
        )
    return results


def download_and_save(
    session: requests.Session, result: dict[str, str], path: Path
) -> tuple[int, int] | None:
    """Resmi indir, doğrula, JPEG olarak kaydet. (width, height) veya None döner."""
    try:
        response = session.get(result["url"], headers=HEADERS, timeout=25, allow_redirects=True)
        response.raise_for_status()
        image = Image.open(io.BytesIO(response.content))
        image.load()
        if image.width < 180 or image.height < 180:
            return None
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGB")
        image.thumbnail((900, 1200), Image.Resampling.LANCZOS)
        image.convert("RGB").save(path, "JPEG", quality=88, optimize=True)
        return image.width, image.height
    except Exception:
        return None


def convert_to_webp(src: Path, dst: Path) -> tuple[int, int] | None:
    """JPEG'i WebP'ye çevir."""
    try:
        im = Image.open(src).convert("RGB")
        im.save(dst, "WEBP", quality=88, method=6)
        return im.width, im.height
    except Exception:
        return None


def create_cover(src: Path, dst: Path, max_w: int = 1200, max_h: int = 1600) -> bool:
    """Cover resmi oluştur."""
    try:
        im = Image.open(src).convert("RGB")
        im.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        im.save(dst, "WEBP", quality=88, method=6)
        return True
    except Exception:
        return False


def load_json_theme(theme_id: str) -> dict | None:
    """JSON dosyasından tema verisini oku."""
    path = THEME_DATA_DIR / f"{theme_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def get_chars_from_json(theme_id: str) -> list[tuple[str, str]]:
    """JSON'dan karakter (id, name) listesini al."""
    data = load_json_theme(theme_id)
    if not data:
        return []
    return [(c["id"], c["name"]) for c in data.get("characters", [])]


# -----------------------------------------------------------------------------
# ANA İŞLEM
# -----------------------------------------------------------------------------


def process_theme(
    theme_id: str,
    session: requests.Session,
    max_candidates: int = 8,
    delay: float = 0.3,
    force: bool = False,
) -> dict[str, list[Path]]:
    """Tek bir tema için tüm karakter resimlerini çek ve kaydet."""
    config = THEME_CONFIG.get(theme_id)
    if not config:
        print(f"❌ Bilinmeyen tema: {theme_id}")
        return {}

    # JSON'dan karakterleri al (kaynak doğruluk için)
    json_chars = get_chars_from_json(theme_id)
    if json_chars:
        chars = json_chars
        # Config'deki search_name'leri JSON sırasına göre eşleştir
        search_map = dict(config["chars"])
        chars = [(cid, search_map.get(cid, name)) for cid, name in chars]
    else:
        chars = config["chars"]

    prefix = config["prefix"]
    theme_cache = CACHE_DIR / theme_id
    theme_cache.mkdir(parents=True, exist_ok=True)

    target_dir = STATIC_THEMES_DIR / theme_id
    target_dir.mkdir(parents=True, exist_ok=True)

    all_candidates: dict[str, list[Path]] = {}
    manifest: dict[str, list[dict]] = {}

    print(f"\n{'='*60}")
    print(f"  THEME: {theme_id.upper()}  ({len(chars)} characters)")
    print(f"{'='*60}")

    for pos, (cid, search_name) in enumerate(chars, 1):
        # Zaten var mı kontrol et
        final_webp = target_dir / f"{cid}.webp"
        if final_webp.exists() and not force:
            print(f"  [{pos:02}/{len(chars)}] {cid}: ✓ already exists, skipping")
            all_candidates[cid] = [final_webp]
            continue

        folder = theme_cache / cid
        folder.mkdir(parents=True, exist_ok=True)

        query = f"{prefix} {search_name} character portrait"
        try:
            results = search_images(session, query)
        except Exception as exc:
            print(f"  [{pos:02}/{len(chars)}] {cid}: SEARCH ERROR {exc}")
            results = []

        saved: list[Path] = []
        details: list[dict] = []
        for result in results:
            if len(saved) >= max_candidates:
                break
            path = folder / f"{len(saved)}.jpg"
            size = download_and_save(session, result, path)
            if size:
                saved.append(path)
                details.append({**result, "file": str(path), "size": size})
        all_candidates[cid] = saved
        manifest[cid] = details
        print(f"  [{pos:02}/{len(chars)}] {cid} ({search_name}): {len(saved)} candidates")
        time.sleep(delay)

    # Manifest kaydet
    (theme_cache / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # En iyi adayları WebP olarak static'e kur
    print(f"  Installing best candidates to {target_dir}...")
    for cid, cand_list in all_candidates.items():
        if not cand_list:
            print(f"    ⚠️  MISSING {cid}")
            continue
        src = cand_list[0]
        dst = target_dir / f"{cid}.webp"
        size = convert_to_webp(src, dst)
        if size:
            print(f"    ✓ {cid} {size[0]}x{size[1]}")
        else:
            print(f"    ❌ FAILED {cid}")

    # Cover oluştur
    first_cid = chars[0][0] if chars else None
    if first_cid and all_candidates.get(first_cid):
        cover_src = all_candidates[first_cid][0]
        cover_dst = target_dir / "cover.webp"
        if create_cover(cover_src, cover_dst):
            print(f"    ✓ COVER created")
        else:
            print(f"    ⚠️  COVER failed")

    return all_candidates


def process_all_themes(
    session: requests.Session,
    max_candidates: int = 8,
    delay: float = 0.3,
    force: bool = False,
    exclude: list[str] | None = None,
) -> None:
    """Tüm temaları sırayla işle."""
    exclude = exclude or []
    for theme_id in THEME_CONFIG:
        if theme_id in exclude:
            print(f"\n⏭️  Skipping {theme_id} (excluded)")
            continue
        process_theme(theme_id, session, max_candidates, delay, force)


def verify_installation() -> None:
    """Kurulu resimleri doğrula."""
    print("\n🔍 Verifying installation...")
    for theme_id in THEME_CONFIG:
        target_dir = STATIC_THEMES_DIR / theme_id
        if not target_dir.exists():
            print(f"  {theme_id}: ❌ NO DIRECTORY")
            continue
        webp_files = list(target_dir.glob("*.webp"))
        json_chars = get_chars_from_json(theme_id)
        expected = len(json_chars) + 1 if json_chars else "?"
        status = "✓" if len(webp_files) >= expected else "⚠️"
        print(f"  {theme_id:20} {status} {len(webp_files)} files (expected ~{expected})")


# -----------------------------------------------------------------------------
# CLI
# -----------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Auction tema karakter resimlerini çek ve kaydet",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Örnekler:
  %(prog)s --theme marvel
  %(prog)s --all
  %(prog)s --theme naruto --candidates 12 --delay 0.5
  %(prog)s --list
  %(prog)s --verify
        """,
    )
    parser.add_argument("--theme", help="İşlenecek tek tema (örn: marvel)")
    parser.add_argument("--all", action="store_true", help="Tüm temaları işle")
    parser.add_argument("--list", action="store_true", help="Mevcut temaları listele")
    parser.add_argument("--verify", action="store_true", help="Kurulu resimleri doğrula")
    parser.add_argument("--candidates", type=int, default=8, help="Karakter başına max aday sayısı (default: 8)")
    parser.add_argument("--delay", type=float, default=0.3, help="İstekler arası bekleme saniyesi (default: 0.3)")
    parser.add_argument("--force", action="store_true", help="Var olan dosyaları yeniden indir")
    parser.add_argument("--exclude", nargs="+", help="Atlanacak temalar (--all ile kullanılır)")

    args = parser.parse_args()

    if args.list:
        print("Mevcut temalar:")
        for tid, cfg in THEME_CONFIG.items():
            json_chars = get_chars_from_json(tid)
            print(f"  {tid:20} {len(cfg['chars']):2d} chars (config) | {len(json_chars):2d} chars (JSON)")
        return

    if args.verify:
        verify_installation()
        return

    if not args.theme and not args.all:
        parser.error("Either --theme or --all is required (or --list/--verify)")

    session = requests.Session()

    if args.theme:
        if args.theme not in THEME_CONFIG:
            print(f"❌ Unknown theme: {args.theme}")
            print(f"Available: {', '.join(sorted(THEME_CONFIG))}")
            sys.exit(1)
        process_theme(args.theme, session, args.candidates, args.delay, args.force)
    else:
        process_all_themes(session, args.candidates, args.delay, args.force, args.exclude)

    print("\n✅ Done!")


if __name__ == "__main__":
    main()