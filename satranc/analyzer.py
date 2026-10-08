"""chess-api.com üzerinden Stockfish pozisyon analizi.

Yerel kurulum gerekmez; engine uzakta (Stockfish 18 NNUE) çalışır ve sonuç
JSON olarak döner. Böylece sunucuda ne bir binary ne de ağır bir engine süreci
barındırılır. İstek kısa tutulur (düşük depth + maxThinkingTime) ki her hamlede
hızlı cevap alınsın.

Dönen skorlar her zaman **beyaz bakış açısına** göre normalize edilir:
``cp`` centipawn (int), ``mate`` mat hamle sayısı (beyaz mat ediyorsa pozitif,
siyah mat ediyorsa negatif) veya ``None``.
"""

import json
import logging
from functools import lru_cache
from urllib import request

from django.conf import settings

logger = logging.getLogger('satranc')


def _api_url():
    return getattr(settings, 'SATRANC_STOCKFISH_API_URL', 'https://chess-api.com/v1')


def _depth():
    return int(getattr(settings, 'SATRANC_STOCKFISH_DEPTH', 12))


def _thinking_time():
    return int(getattr(settings, 'SATRANC_STOCKFISH_THINKING_TIME', 50))


def _empty():
    return {'cp': None, 'mate': None, 'best': None, 'source': 'none'}


def _analyze_uncached(fen):
    payload = json.dumps({
        'fen': fen,
        'depth': min(_depth(), 18),
        'maxThinkingTime': _thinking_time(),
    }).encode('utf-8')

    req = request.Request(
        _api_url(),
        data=payload,
        headers={
            'Content-Type': 'application/json',
            'User-Agent': 'oyunlar-satranc/1.0',
        },
        method='POST',
    )
    try:
        with request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8'))
    except Exception as exc:
        logger.warning('Satranç analiz API hatası: %s', exc)
        return _empty()

    # variants > 1 olduğunda liste dönebilir; ilk varyantı kullan.
    if isinstance(data, list):
        data = data[0] if data else {}
    if not isinstance(data, dict):
        return _empty()

    mate = data.get('mate')
    try:
        mate = None if mate is None else int(mate)
    except (TypeError, ValueError):
        mate = None

    cp = None
    centipawns = data.get('centipawns')
    if centipawns not in (None, ''):
        try:
            cp = int(centipawns)
        except (TypeError, ValueError):
            cp = None
    if cp is None:
        evaluation = data.get('eval')
        if evaluation is not None:
            try:
                # eval piyon birimindedir; centipawn'a çevir.
                cp = round(float(evaluation) * 100)
            except (TypeError, ValueError):
                cp = None

    best = data.get('move') or None
    return {'cp': cp, 'mate': mate, 'best': best, 'source': 'api'}


@lru_cache(maxsize=1024)
def _analyze_cached(fen):
    try:
        return _analyze_uncached(fen)
    except Exception as exc:  # pragma: no cover - beklenmedik durum
        logger.warning('Analiz yapılamadı: %s', exc)
        return _empty()


def analyze(fen):
    """Bir FEN için normalize edilmiş analiz döndürür.

    Sonuç: ``{'cp': int|None, 'mate': int|None, 'best': str|None, 'source': str}``
    """
    if not fen:
        return _empty()
    return dict(_analyze_cached(fen))


def clear_cache():
    _analyze_cached.cache_clear()
