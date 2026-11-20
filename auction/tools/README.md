# Auction Theme Image Fetcher

Bu araç, auction oyunu temaları için karakter resimlerini otomatik olarak indirir ve optimize eder.

## Kurulum

```bash
# Gerekli paketler
pip install requests pillow
```

## Kullanım

### Tek tema çek
```bash
python auction/tools/fetch_theme_images.py --theme marvel
python auction/tools/fetch_theme_images.py --theme naruto --candidates 12 --delay 0.5
```

### Tüm temaları çek
```bash
python auction/tools/fetch_theme_images.py --all
```

### Bazı temaları hariç tut
```bash
python auction/tools/fetch_theme_images.py --all --exclude lotr kurtlar_vadisi
```

### Mevcut temaları listele
```bash
python auction/tools/fetch_theme_images.py --list
```

### Kurulu dosyaları doğrula
```bash
python auction/tools/fetch_theme_images.py --verify
```

### Zorla yeniden indir
```bash
python auction/tools/fetch_theme_images.py --theme dc --force
```

## Parametreler

| Parametre | Açıklama | Varsayılan |
|-----------|----------|------------|
| `--theme` | Tek tema işle (örn: `marvel`, `naruto`, `lotr`) | - |
| `--all` | Tüm temaları işle | - |
| `--candidates` | Karakter başına max aday sayısı | 8 |
| `--delay` | İstekler arası bekleme (saniye) | 0.3 |
| `--force` | Var olan dosyaları yeniden indir | False |
| `--exclude` | `--all` ile birlikte, atlanacak temalar | - |
| `--list` | Temaları listele | - |
| `--verify` | Kurulu dosyaları kontrol et | - |

## Çıktı Yapısı

```
auction/static/auction/themes/
├── marvel/
│   ├── cover.webp
│   ├── marvel_iron_man.webp
│   ├── marvel_thor.webp
│   └── ...
├── dc/
├── harry_potter/
├── game_of_thrones/
├── naruto/
├── dragon_ball/
├── one_piece/
├── star_wars/
├── video_games/
├── lotr/
└── kurtlar_vadisi/
```

Her karakter için:
- **Cache:** `~/.theme_image_cache/{tema}/{karakter_id}/0.jpg` ... `7.jpg` (8 aday)
- **Final:** `auction/static/auction/themes/{tema}/{karakter_id}.webp` (ilk geçerli aday)
- **Cover:** `auction/static/auction/themes/{tema}/cover.webp` (ilk karakterden)

## Nasıl Çalışır

1. **Yandex Görseller** API'si (HTML parsing) ile arama yapar
2. Her karakter için `"{prefix} {search_name} character portrait"` sorgusu
3. İlk 8 geçerli sonucu indirir (min 180x180 px)
4. En iyisini (ilkini) WebP'ye çevirip static'e kopyalar
5. Cover için ilk karakteri kullanır

## Yeni Tema Ekleme

`THEME_CONFIG` dict'ine yeni entry ekle:

```python
"yeni_tema": {
    "prefix": "Arama prefix'i",
    "chars": [
        ("yeni_tema_char1", "Arama adı 1"),
        ("yeni_tema_char2", "Arama adı 2"),
        ...
    ],
},
```

Ayrıca `auction/themes/data/yeni_tema.json` dosyası da olmalı (karakter ID'leri eşleşmeli).