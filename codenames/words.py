"""Vocabulary generation, validation and curated fallback lists."""

from __future__ import annotations

import json
import random
import re
import unicodedata
from typing import Iterable

BOARD_SIZE = 25
MAX_WORD_LENGTH = 32

_TURKISH_MAP = str.maketrans({
    'ç': 'c', 'Ç': 'c', 'ğ': 'g', 'Ğ': 'g', 'ı': 'i', 'I': 'i', 'İ': 'i',
    'ö': 'o', 'Ö': 'o', 'ş': 's', 'Ş': 's', 'ü': 'u', 'Ü': 'u',
})

_WORD_RE = re.compile(r"^[A-Za-zÇĞİÖŞÜçğıöşü]+(?:[-'’][A-Za-zÇĞİÖŞÜçğıöşü]+)?$")
_EN_WORD_RE = re.compile(r"^[A-Za-z]+(?:[-'][A-Za-z]+)?$")

_BLOCKED = {
    'sex', 'seks', 'porn', 'porno', 'nazi', 'nazis', 'rape', 'tecavüz',
    'sik', 'amk', 'orospu', 'fuck', 'shit', 'bitch', 'idiot', 'salak',
}


class WordValidationError(ValueError):
    """Raised when generated vocabulary does not satisfy the board contract."""


def normalize_word(value: str) -> str:
    """Language-aware comparison key (case, accents and Turkish letters)."""
    text = unicodedata.normalize('NFKD', str(value or '')).casefold()
    text = ''.join(ch for ch in text if not unicodedata.combining(ch))
    text = text.translate(_TURKISH_MAP)
    return re.sub(r'[^a-z0-9]', '', text)


def display_word(value: str) -> str:
    text = unicodedata.normalize('NFC', str(value or '')).strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def _is_valid_language_word(word: str, language: str) -> bool:
    if not _WORD_RE.match(word):
        return False
    if language == 'en' and not _EN_WORD_RE.match(word):
        return False
    if normalize_word(word) in _BLOCKED:
        return False
    return True


def validate_word_list(raw_words: Iterable, language: str) -> list[str]:
    """Validate a model/fallback word list and return display-ready words.

    The function is intentionally strict: the caller retries on failure rather
    than silently patching a partially bad model response.
    """
    if language not in ('en', 'tr'):
        raise WordValidationError('unsupported_language')
    if not isinstance(raw_words, (list, tuple)):
        raise WordValidationError('words_not_list')
    if len(raw_words) != BOARD_SIZE:
        raise WordValidationError(f'expected_{BOARD_SIZE}_words_got_{len(raw_words)}')

    result: list[str] = []
    seen: set[str] = set()
    for item in raw_words:
        if not isinstance(item, str):
            raise WordValidationError('word_not_string')
        word = display_word(item)
        if not word:
            raise WordValidationError('empty_word')
        if len(word) > MAX_WORD_LENGTH:
            raise WordValidationError('word_too_long')
        if ' ' in word or '\n' in word or '\t' in word:
            raise WordValidationError('word_not_single_token')
        if not _is_valid_language_word(word, language):
            raise WordValidationError('invalid_word_characters')
        key = normalize_word(word)
        if not key or key in seen:
            raise WordValidationError('duplicate_word')
        seen.add(key)
        result.append(word)

    return result


def parse_model_json(content: str) -> list[str]:
    """Extract and schema-check the words array from a chat completion body."""
    text = (content or '').strip()
    if not text:
        raise WordValidationError('empty_response')
    if text.startswith('```'):
        text = re.sub(r'^```(?:json)?\s*', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\s*```$', '', text)
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1 or end <= start:
        raise WordValidationError('response_not_json')
    try:
        payload = json.loads(text[start:end + 1])
    except (TypeError, ValueError) as exc:
        raise WordValidationError('response_not_json') from exc
    if not isinstance(payload, dict):
        raise WordValidationError('response_not_object')
    if set(payload.keys()) != {'words'}:
        raise WordValidationError('unexpected_response_fields')
    words = payload.get('words')
    if not isinstance(words, list):
        raise WordValidationError('words_not_list')
    return words


def fallback_words(language: str, count: int = BOARD_SIZE) -> list[str]:
    """Pick a fresh random subset from the curated, language-specific pool."""
    pool = TURKISH_WORDS if language == 'tr' else ENGLISH_WORDS
    if count > len(pool):
        raise WordValidationError('fallback_pool_too_small')
    return random.sample(pool, count)


ENGLISH_WORDS = [
    'apple', 'anchor', 'bakery', 'balloon', 'basket', 'bicycle', 'blanket',
    'bottle', 'bridge', 'butterfly', 'camera', 'candle', 'carpet', 'castle',
    'cheese', 'circus', 'clock', 'cloud', 'coffee', 'compass', 'cookie',
    'crown', 'desert', 'diamond', 'dolphin', 'dragon', 'eagle', 'engine',
    'envelope', 'feather', 'festival', 'firefighter', 'forest', 'fountain',
    'garden', 'glacier', 'guitar', 'hammer', 'helmet', 'honey', 'hospital',
    'hotel', 'iceberg', 'insect', 'island', 'jacket', 'jungle', 'kettle',
    'keyboard', 'king', 'kitchen', 'ladder', 'lamp', 'lantern', 'lemon',
    'library', 'lighthouse', 'lion', 'lizard', 'magnet', 'marble', 'market',
    'meadow', 'medal', 'meteor', 'mirror', 'monkey', 'moon', 'mountain',
    'museum', 'mushroom', 'necklace', 'needle', 'nest', 'notebook', 'nurse',
    'ocean', 'onion', 'orchestra', 'oven', 'palace', 'parrot', 'passport',
    'peacock', 'pencil', 'pepper', 'piano', 'pilot', 'pillow', 'pirate',
    'planet', 'pocket', 'pumpkin', 'pyramid', 'queen', 'rabbit', 'rainbow',
    'river', 'robot', 'rocket', 'rose', 'saddle', 'sailor', 'sandal',
    'sandwich', 'satellite', 'school', 'scissors', 'shadow', 'ship', 'shoe',
    'shovel', 'silver', 'skeleton', 'snow', 'sofa', 'soldier', 'spider',
    'spoon', 'spring', 'squirrel', 'stadium', 'star', 'station', 'statue',
    'storm', 'strawberry', 'submarine', 'suitcase', 'sunset', 'surgeon',
    'swan', 'sword', 'table', 'telescope', 'temple', 'thunder', 'ticket',
    'tiger', 'tomato', 'tornado', 'tower', 'train', 'treasure', 'truck',
    'tunnel', 'turtle', 'umbrella', 'valley', 'vampire', 'vegetable',
    'village', 'violin', 'volcano', 'wagon', 'wallet', 'waterfall', 'whale',
    'wheel', 'window', 'wizard', 'wolf', 'workshop', 'yacht', 'zebra',
]

TURKISH_WORDS = [
    'ada', 'ağaç', 'ağaçkakan', 'akvaryum', 'anahtar', 'anket', 'armut',
    'asker', 'aslan', 'atölye', 'avukat', 'ayakkabı', 'ayna', 'ayı', 'badem',
    'bahçe', 'baklava', 'bal', 'balık', 'balina', 'balon', 'balkabağı',
    'basket', 'battaniye', 'bavul', 'bayrak', 'bebek', 'biber', 'bilezik',
    'bilet', 'bilye', 'bisiklet', 'böcek', 'bulut', 'buzul', 'büyücü',
    'ceket', 'cengel', 'cerrah', 'ceviz', 'ceylan', 'çadır', 'çakıl',
    'çanta', 'çapa', 'çayır', 'çekiç', 'çeşme', 'çikolata', 'çilek', 'çorap',
    'dağ', 'defter', 'denizaltı', 'denizci', 'denizfeneri', 'doktor',
    'domates', 'dondurma', 'düğün', 'ejderha', 'ekmek', 'elma', 'elmas',
    'eldiven', 'enginar', 'eyer', 'fabrika', 'fener', 'festival', 'fırtına',
    'fırın', 'fil', 'fotoğraf', 'gemi', 'gitar', 'gökkuşağı', 'göl',
    'gölge', 'güneş', 'gümüş', 'günbatımı', 'halı', 'hamak', 'harita',
    'hastane', 'hazine', 'hemşire', 'heykel', 'horoz', 'huni', 'ırmak',
    'iğne', 'iskelet', 'istasyon', 'itfaiyeci', 'kalabalık', 'kale', 'kalem',
    'kamera', 'kamyon', 'kaplan', 'kaplumbağa', 'kartal', 'kasırga', 'kaşık',
    'kavanoz', 'kavun', 'kayık', 'kazan', 'keçi', 'kelebek', 'keman',
    'kertenkele', 'kestane', 'kılıç', 'kırlangıç', 'kiraz', 'kitap', 'klavye',
    'kolye', 'koltuk', 'kumsal', 'korsan', 'köpek', 'köprü', 'köy', 'kral',
    'kraliçe', 'kuğu', 'kule', 'kum', 'kumbara', 'kurt', 'kutu', 'kütüphane',
    'lamba', 'liman', 'limon', 'madalya', 'makas', 'mantar', 'masa',
    'matara', 'maymun', 'mektup', 'merdiven', 'meteor', 'mıknatıs', 'mum',
    'mutfak', 'müze', 'nehir', 'nohut', 'okul', 'okyanus', 'okçu', 'ocak',
    'orkestra', 'otel', 'otobüs', 'oyuncak', 'örümcek', 'pamuk', 'pankart',
    'papağan', 'pasaport', 'patates', 'pazar', 'pencere', 'penguen',
    'peynir', 'pırasa', 'pilot', 'piramit', 'piyano', 'pizza', 'portakal',
    'posta', 'pusula', 'radyo', 'robot', 'roket', 'rüzgar', 'saat',
    'sabun', 'sahil', 'sakal', 'salıncak', 'salata', 'sandviç', 'sandalet',
    'sandalye', 'sarımsak', 'satranç', 'sebze', 'sepet', 'seramik', 'sincap',
    'sirk', 'soba', 'soğan', 'sokak', 'stadyum', 'sürahi', 'şapka', 'şato',
    'şelale', 'şemsiye', 'şişe', 'tabak', 'tavşan', 'tavuskuşu', 'tekerlek',
    'telefon', 'teleskop', 'tencere', 'terzi', 'tezgah', 'tiyatro', 'tornavida',
    'tren', 'tuğla', 'tünel', 'tüy', 'uçak', 'uydu', 'vadi', 'vagon',
    'vampir', 'vanilya', 'vazo', 'viyola', 'yağmur', 'yanardağ', 'yastık',
    'yat', 'yay', 'yelken', 'yemek', 'yengeç', 'yıldız', 'yılan', 'yoğurt',
    'yunus', 'yuva', 'zarf', 'zebra', 'zeytin', 'zil', 'zürafa',
    # Daha geniş günlük kelime havuzu: yiyecek, ev, doğa, hayvan, meslek ve kavramlar.
    'acı', 'adres', 'ahır', 'aile', 'ajanda', 'akarsu', 'akşam', 'alışveriş',
    'altın', 'ampul', 'ananas', 'apartman', 'araba', 'arı', 'armağan',
    'asansör', 'astronot', 'aşçı', 'atkı', 'avize', 'ayran', 'balkon',
    'bardak', 'baykuş', 'berber', 'bıçak', 'bodrum', 'buzdolabı', 'cüzdan',
    'çamaşır', 'çatal', 'çatı', 'çorba', 'çöl', 'dalga', 'dansçı', 'diş',
    'döner', 'duvar', 'eczane', 'eşek', 'fincan', 'flamingo', 'futbol',
    'galaksi', 'gazeteci', 'gözlük', 'gürültü', 'hakim', 'havaalanı', 'havlu',
    'hayal', 'hayvan', 'hostes', 'ilkbahar', 'incir', 'internet', 'kahve',
    'kapı', 'karpuz', 'karınca', 'kedi', 'kefir', 'kilise', 'kilit', 'koala',
    'koyun', 'köfte', 'kupa', 'kurabiye', 'kurbağa', 'lahmacun', 'lokum',
    'mağara', 'makarna', 'marangoz', 'martı', 'mimar', 'mutluluk', 'müzisyen',
    'nar', 'orman', 'ova', 'öğretmen', 'ördek', 'panda', 'park', 'pilav',
    'polis', 'reçel', 'ressam', 'restoran', 'salyangoz', 'sanat', 'savcı',
    'sessizlik', 'silgi', 'sinema', 'süpürge', 'şahin', 'şampuan', 'şarkıcı',
    'şeftali', 'şimşek', 'tabure', 'tarak', 'tarih', 'televizyon', 'tilki',
    'toka', 'turşu', 'ütü', 'üzüm', 'valiz', 'vişne', 'yazar', 'yıldırım',
]
