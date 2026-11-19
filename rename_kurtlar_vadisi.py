#!/usr/bin/env python3
"""
Kurtlar Vadisi fotoğraflarını JSON'daki karakter ID'lerine göre yeniden adlandırır.
Beklenen format: kv_<id>.webp (örn: kv_polat.webp)
"""

import os
import json
import shutil
from pathlib import Path
from urllib.parse import unquote

# Yollar
THEME_DIR = Path("/Users/siudigital/Desktop/oyunlar/auction/static/auction/themes/kurtlar_vadisi")
JSON_PATH = Path("/Users/siudigital/Desktop/oyunlar/auction/themes/data/kurtlar_vadisi.json")

# JSON'dan karakter ID -> dosya adı haritası
with open(JSON_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

# JSON'daki image yollarından ID'leri çıkar
expected_files = {}
for char in data["characters"]:
    # image: "/static/auction/themes/kurtlar_vadisi/kv_polat.webp"
    img_path = char["image"]
    filename = Path(img_path).name  # kv_polat.webp
    char_id = char["id"]  # kv_polat
    expected_files[char_id] = filename

print(f"JSON'da {len(expected_files)} karakter var:")
for k, v in expected_files.items():
    print(f"  {k} -> {v}")

# Mevcut dosyaları listele
current_files = [f for f in THEME_DIR.iterdir() if f.is_file()]
print(f"\nMevcut {len(current_files)} dosya:")
for f in current_files:
    print(f"  {f.name}")

# Eşleştirme haritası (mevcut dosya -> hedef kv_ dosya adı)
# Manuel eşleştirme yapıyoruz çünkü dosya isimleri tutarsız
mapping = {
    # JSON ID -> (mevcut dosya adı, yeni uzantı)
    "kv_polat": ("Polat_Alemdar.webp", ".webp"),
    "kv_memati": ("Memati_Kurtlar_vadisi_pusu.jpg", ".webp"),
    "kv_baron": ("KarahanliShot.webp", ".webp"),
    "kv_aslan": ("AslanAkbey.webp", ".webp"),
    "kv_cakir": ("Cakir-4.webp", ".webp"),
    "kv_abdulhey": ("Abdu\u0308lhey_C\u0327oban_karakteri.jpg", ".webp"),  # NFC normalize
    "kv_elif": ("elif.jpeg", ".webp"),
    "kv_dogu": ("Dogu-66.webp", ".webp"),
    "kv_seyfo": ("HaloDayi.webp", ".webp"),  # Nihat_Nikerel.jpg de aynı karakter, bunu atla
    "kv_lazziya": ("I\u0307stemi_Betil.jpg", ".webp"),  # İstemi Betil = Laz Ziya oyuncusu
    "kv_safiye": ("Safiye_Karahnl%3F.webp", ".webp"),
    "kv_nergiz": ("Nergiskarahanli.webp", ".webp"),
    "kv_erhan": ("Gullu.webp", ".webp"),
    "kv_kilic": ("K%3Fl%3F%3F.webp", ".webp"),  # URL decode: K?l??? -> Kılıç
    "kv_nesrin": ("Nesrin.webp", ".webp"),
    "kv_testere": ("NecmiShot.webp", ".webp"),
    "kv_derya": ("Derya.webp", ".webp"),
    "kv_husrev": ("HusrevAga.webp", ".webp"),
    "kv_meral": ("meral.jpeg", ".webp"),
    "kv_canan": ("CananCavan.webp", ".webp"),
    "kv_samuel": ("VanunuShot.webp", ".webp"),
    "kv_nizamettin": ("Nizamettin-30.webp", ".webp"),
    "kv_tombalaci": ("Tombalaci-31.webp", ".webp"),
    "kv_tuncay": ("TuncayTemizlik.webp", ".webp"),
    "kv_iplikci": ("IplikciNedim.webp", ".webp"),
    "kv_halil": (None, ".webp"),  # Dosya yok - halil için dosya eksik
}

# Silinecek generic dosyalar
to_delete = ["images.jpeg", "images (1).jpeg", "Nihat_Nikerel.jpg"]  # Nihat_Nikerel = HaloDayi duplicate

print("\n--- İşlemler ---")

# 1. Generic dosyaları sil
for fname in to_delete:
    fpath = THEME_DIR / fname
    if fpath.exists():
        fpath.unlink()
        print(f"Silindi: {fname}")
    else:
        print(f"Bulunamadı (zaten silinmiş?): {fname}")

# 2. Dosyaları yeniden adlandır
for char_id, (src_name, new_ext) in mapping.items():
    if src_name is None:
        print(f"UYARI: {char_id} için kaynak dosya yok!")
        continue
    
    src_path = THEME_DIR / src_name
    # NFC normalize et (Türkçe karakter sorunu için)
    import unicodedata
    src_name_nfc = unicodedata.normalize("NFC", src_name)
    src_path_nfc = THEME_DIR / src_name_nfc
    
    if not src_path.exists() and not src_path_nfc.exists():
        print(f"UYARI: Kaynak dosya bulunamadı: {src_name}")
        continue
    
    actual_src = src_path if src_path.exists() else src_path_nfc
    target_name = expected_files[char_id]  # kv_polat.webp
    target_path = THEME_DIR / target_name
    
    if actual_src == target_path:
        print(f"Zaten doğru isimde: {target_name}")
        continue
    
    if target_path.exists():
        print(f"Hedef zaten var, atlanıyor: {target_name}")
        continue
    
    # Uzantıyı .webp yap (hedef zaten .webp)
    shutil.move(str(actual_src), str(target_path))
    print(f"Yeniden adlandırıldı: {actual_src.name} -> {target_name}")

# 3. Sonuç listele
print("\n--- Son durum ---")
final_files = sorted([f.name for f in THEME_DIR.iterdir() if f.is_file()])
for f in final_files:
    print(f"  {f}")

print(f"\nToplam {len(final_files)} dosya kaldı.")
print(f"Beklenen: {len(expected_files)} dosya")

# Eksikleri bildir
missing = set(expected_files.values()) - set(final_files)
if missing:
    print(f"\nEKSİK DOSYALAR ({len(missing)}):")
    for m in sorted(missing):
        print(f"  {m}")
else:
    print("\nTüm dosyalar hazır!")