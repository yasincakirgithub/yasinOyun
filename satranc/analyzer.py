"""Stockfish pozisyon analizi.

Öncelik sırası:

1. **Yerel Stockfish** (varsa): ``chess.engine`` ile doğrudan çalışır. Ağ
   gecikmesi yoktur, bu yüzden bot hamleleri milisaniyeler içinde gelir.
2. **Uzak API** (chess-api.com): yerel engine bulunamazsa kullanılır. İstek
   kısa tutulur (düşük depth + maxThinkingTime) ki her hamlede hızlı cevap
   alınsın.

Dönen skorlar her zaman **beyaz bakış açısına** göre normalize edilir:
``cp`` centipawn (int), ``mate`` mat hamle sayısı (beyaz mat ediyorsa pozitif,
siyah mat ediyorsa negatif) veya ``None``.
"""

import json
import logging
import os
import shutil
import threading
from functools import lru_cache
from urllib import request

import chess
import chess.engine
from django.conf import settings

logger = logging.getLogger('satranc')

# Yerel engine süreci ve erişimi için kilit (python-chess engine'leri thread-safe
# değildir; inceleme paralel çalıştığı için analizleri sıraya alırız).
_engine_lock = threading.Lock()
_engine = None
_engine_path_cache = None


def _api_url():
    return getattr(settings, 'SATRANC_STOCKFISH_API_URL', 'https://chess-api.com/v1')


def _depth():
    return int(getattr(settings, 'SATRANC_STOCKFISH_DEPTH', 12))


def _thinking_time():
    return int(getattr(settings, 'SATRANC_STOCKFISH_THINKING_TIME', 50))


def _empty():
    return {
        'cp': None,
        'mate': None,
        'best': None,
        'win_chance': None,
        'depth': None,
        'continuation': [],
        'source': 'none',
    }


# ---------------------------------------------------------------------------
# Yerel Stockfish engine
# ---------------------------------------------------------------------------
def _find_engine():
    global _engine_path_cache
    if _engine_path_cache is not None:
        return _engine_path_cache or None

    candidates = [
        getattr(settings, 'SATRANC_STOCKFISH_PATH', ''),
        os.environ.get('SATRANC_STOCKFISH_PATH', ''),
        shutil.which('stockfish'),
        '/usr/bin/stockfish',
        '/usr/local/bin/stockfish',
        '/opt/homebrew/bin/stockfish',
    ]
    if not getattr(settings, 'SATRANC_LOCAL_ENGINE', True):
        candidates = []

    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            _engine_path_cache = candidate
            return candidate

    _engine_path_cache = ''
    return None


def local_engine_available():
    return bool(_find_engine())


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine

    path = _find_engine()
    if not path:
        return None

    try:
        engine = chess.engine.SimpleEngine.popen_uci(path)
        engine.configure({'Threads': 1, 'Hash': 32})
        _engine = engine
        logger.info('Yerel Stockfish engine kullanılıyor: %s', path)
        return engine
    except Exception as exc:  # pragma: no cover - kurulum/izin hatası
        logger.warning('Yerel Stockfish başlatılamadı (%s): %s', path, exc)
        _engine = None
        return None


def _analyze_local(fen, depth):
    if not local_engine_available():
        return None

    try:
        board = chess.Board(fen)
    except ValueError:
        return None

    with _engine_lock:
        engine = _get_engine()
        if engine is None:
            return None
        try:
            info = engine.analyse(board, chess.engine.Limit(depth=max(1, int(depth))))
        except chess.engine.EngineError as exc:
            logger.warning('Yerel engine hatası, yeniden başlatılıyor: %s', exc)
            _reset_engine()
            return None

    score = info.get('score')
    if score is None:
        return None
    white = score.pov(chess.WHITE)

    mate = white.mate()
    cp = None if mate is not None else white.score()

    pv = info.get('pv') or []
    continuation = [move.uci() for move in pv]
    best = continuation[0] if continuation else None

    reached_depth = info.get('depth')
    try:
        reached_depth = None if reached_depth is None else int(reached_depth)
    except (TypeError, ValueError):
        reached_depth = None

    win_chance = None
    if mate is not None:
        win_chance = 100.0 if mate > 0 else 0.0
    elif cp is not None:
        clamped = max(-1000, min(1000, cp))
        win_chance = round(
            50 + 50 * (2 / (1 + pow(2.718281828459045, -0.00368208 * clamped)) - 1),
            2,
        )

    return {
        'cp': cp,
        'mate': mate,
        'best': best,
        'win_chance': win_chance,
        'depth': reached_depth,
        'continuation': continuation,
        'source': 'local',
    }


def _reset_engine():
    global _engine
    if _engine is None:
        return
    try:
        _engine.quit()
    except Exception:  # pragma: no cover - savunmaci
        pass
    _engine = None


# ---------------------------------------------------------------------------
# Uzak API (chess-api.com) yedeği
# ---------------------------------------------------------------------------
def _analyze_remote(fen, depth=None, thinking_time=None):
    payload = json.dumps({
        'fen': fen,
        'depth': min(int(depth if depth is not None else _depth()), 18),
        'maxThinkingTime': int(
            thinking_time if thinking_time is not None else _thinking_time()
        ),
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

    # Uzak servis zaman zaman eşzamanlı isteklerde gecikebilir; bir kez yeniden dene.
    data = None
    last_exc = None
    for attempt, timeout in enumerate((4, 10)):
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            break
        except Exception as exc:
            last_exc = exc
            if attempt == 0:
                logger.info('Analiz isteği gecikti, yeniden deneniyor: %s', exc)
    if data is None:
        logger.warning('Satranç analiz API hatası: %s', last_exc)
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
    continuation = data.get('continuationArr') or []
    if not isinstance(continuation, list):
        continuation = []

    win_chance = data.get('winChance')
    try:
        win_chance = None if win_chance is None else float(win_chance)
    except (TypeError, ValueError):
        win_chance = None

    reached_depth = data.get('depth')
    try:
        reached_depth = None if reached_depth is None else int(reached_depth)
    except (TypeError, ValueError):
        reached_depth = None

    return {
        'cp': cp,
        'mate': mate,
        'best': best,
        'win_chance': win_chance,
        'depth': reached_depth,
        'continuation': [move for move in continuation if isinstance(move, str)],
        'source': 'api',
    }


def _analyze_uncached(fen, depth=None, thinking_time=None):
    depth = int(depth if depth is not None else _depth())
    local = _analyze_local(fen, depth)
    if local is not None:
        return local
    return _analyze_remote(fen, depth, thinking_time)


@lru_cache(maxsize=2048)
def _analyze_cached(fen, depth, thinking_time):
    try:
        return _analyze_uncached(fen, depth, thinking_time)
    except Exception as exc:  # pragma: no cover - beklenmedik durum
        logger.warning('Analiz yapılamadı: %s', exc)
        return _empty()


def analyze(fen):
    """Bir FEN için normalize edilmiş analiz döndürür."""
    if not fen:
        return _empty()
    return dict(_analyze_cached(fen, _depth(), _thinking_time()))


def analyze_position(fen, depth=None, thinking_time=None):
    """Belirli bir derinlik/süre ile analiz yapar (bot seviyeleri için)."""
    if not fen:
        return _empty()
    depth = int(depth if depth is not None else _depth())
    thinking_time = int(thinking_time if thinking_time is not None else _thinking_time())
    return dict(_analyze_cached(fen, depth, thinking_time))


def clear_cache():
    _analyze_cached.cache_clear()


def warmup():
    """Yerel engine'i önceden başlatır (ilk hamlede başlatma gecikmesi olmasın)."""
    if not local_engine_available():
        return False
    with _engine_lock:
        return _get_engine() is not None


def shutdown():
    """Yerel engine sürecini kapatır (worker kapanırken)."""
    with _engine_lock:
        _reset_engine()
