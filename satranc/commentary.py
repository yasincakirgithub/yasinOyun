"""Önemli satranç anlarını tespit edip eğlenceli Türkçe yorum üretir.

Her hamlede konuşma üretilmez; mat riski artışı, mat fırsatı, büyük taktiksel
savrulmalar, şah, taş alma, terfi ve rok gibi "olay"larda yorum seçilir. Aynı
veya çok benzer yorumun art arda tetiklenmesini engellemek için
``CommentCooldown`` kullanılır.
"""

import random
import time

import chess

EVENT_MATE_DANGER = 'mate_danger'
EVENT_MATE_CHANCE = 'mate_chance'
EVENT_CHECK = 'check'
EVENT_PROMOTION = 'promotion'
EVENT_BIG_CAPTURE = 'big_capture'
EVENT_CASTLE = 'castle'
EVENT_BLUNDER = 'blunder'
EVENT_GREAT = 'great'
EVENT_WIN = 'win'
EVENT_LOSE = 'lose'
EVENT_GAME_START = 'game_start'

# Eşikler (centipawn). Biraz düşük tutuldu ki yorumlar daha sık tetiklensin.
BLUNDER_SWING = 150
GREAT_SWING = 150
# Kaç hamlede mat "yakın" sayılsın.
MATE_MAX_N = 4

_TEMPLATES = {
    EVENT_GAME_START: [
        '{white} ile {black} karşı karşıya! Oyun başladı, iyi şanslar reisler!',
        'Bakalım kim kazanacak: {white} mı {black} mı? Başlıyoruz!',
        'Tahtaya hoş geldiniz! {white} ve {black}, gösterin kendinizi!',
    ],
    EVENT_MATE_DANGER: [
        '{mover} kaç lan kaç! {opp} geliyooo!',
        'Uyan {mover}! {opp} matı kokladı, kaç kaç!',
        '{mover} kendine gel, {opp} geliyo! Kaç!',
        'Ey {mover}, tehlikedesin! {opp} matı kuruyor!',
    ],
    EVENT_MATE_CHANCE: [
        'Helal be, iyi gördün reis {mover}!',
        'Ooo reis {mover} matı buldu, helal!',
        'Yürü be {mover}, kim tutar seni!',
        'Reis {mover} düğümü çözdü, {opp} yandın!',
    ],
    EVENT_CHECK: [
        '{mover} şah çekti, {opp} dikkat et!',
        'Şah! {mover} baskıyı kurdu, {opp} panik!',
        'Ooo {mover} şah dedi, {opp} kaçacak yer arıyor!',
    ],
    EVENT_PROMOTION: [
        '{mover} piyonu vezire çevirdi, {opp} yandın!',
        'Ooo {mover} terfi etti, {opp} başın dertte!',
        'Helal {mover}, piyon vezir oldu!',
    ],
    EVENT_BIG_CAPTURE: [
        '{mover} büyük taşı aldı, {opp} bir taş eksik!',
        'Ooo {mover} avı yakaladı, {opp} üzüldü!',
        'Helal {mover}, {opp} taşını kaptırdı!',
    ],
    EVENT_CASTLE: [
        '{mover} rok yaptı, kalesi güvende!',
        'Ooo {mover} kaleyi güvene aldı, sağlam oynuyor!',
        '{mover} rok çekti, {opp} işin zor!',
    ],
    EVENT_BLUNDER: [
        'Ooo {mover}, o hamle olmadı! {opp} hemen affetmez!',
        'Yazık la {mover}, o taşı geri versene!',
        'Hoppala {mover}! {opp} aradığını buldu!',
        'Aman {mover}, bu hamle {opp} için hediye oldu!',
    ],
    EVENT_GREAT: [
        '{mover} reis naptın sen, taş gibi hamle!',
        'Helal olsun {mover}, rakibi dağıttın!',
        'Vay be {mover}, bu hamle şampiyonluk!',
        'Ooo {mover} adamsın! {opp} ne yapacağını şaşırdı!',
    ],
    EVENT_WIN: [
        'Şah mat! {mover} oyunu bitirdi, helal be!',
        'Bitti! Reis {mover} matı vurdu!',
        'Helal olsun {mover}, {opp} darmadağın!',
    ],
    EVENT_LOSE: [
        'Üzülme {mover}, bir dahaki sefere reis!',
        'Oldu olacak {mover}, {opp} bugün formda!',
        'Kısmet değilmiş {mover}, {opp} haketti!',
    ],
}


def move_flags(before_fen, uci):
    """(before_fen, uci) için hamlenin taktiksel özelliklerini döndürür."""
    flags = {
        'is_capture': False,
        'is_big_capture': False,
        'is_castling': False,
        'is_promotion': False,
        'gives_check': False,
    }
    if not before_fen or not uci:
        return flags
    try:
        board = chess.Board(before_fen)
        move = chess.Move.from_uci(uci)
    except (ValueError, AssertionError):
        return flags

    flags['is_capture'] = board.is_capture(move)
    flags['is_castling'] = board.is_castling(move)
    flags['is_promotion'] = move.promotion is not None
    try:
        flags['gives_check'] = board.gives_check(move)
    except Exception:  # pragma: no cover - savunmaci
        flags['gives_check'] = False

    if flags['is_capture']:
        captured = board.piece_at(move.to_square)
        if captured is not None and captured.piece_type in (chess.QUEEN, chess.ROOK):
            flags['is_big_capture'] = True

    return flags


def _pov(analysis, color):
    """Analizi verilen rengin bakış açısına çevirir.

    Dönen: ``{'cp': int|None, 'mate': int|None}``. ``mate`` oyuncu lehine ise
    pozitif (mat ediyor), aleyhine ise negatif (mat oluyor).
    """
    sign = 1 if color == 'w' else -1
    mate = analysis.get('mate')
    cp = analysis.get('cp')
    return {
        'mate': None if mate is None else mate * sign,
        'cp': None if cp is None else cp * sign,
    }


def _approx_cp(pov):
    """Mat skorlarını da karşılaştırılabilir centipawn'a çevirir."""
    if pov.get('mate') is not None:
        return (100000 - abs(pov['mate']) * 1000) * (1 if pov['mate'] > 0 else -1)
    return pov.get('cp')


def _mate_got_closer(before_mate, after_mate):
    """Oyuncu mat olmaya yaklaştı mı? (negatif değerler: mat oluyor)"""
    if after_mate is None or after_mate >= 0:
        return False
    if before_mate is None or before_mate >= 0:
        return True
    return abs(after_mate) < abs(before_mate)


def _mate_improved(before_mate, after_mate):
    """Oyuncunun mat etme şansı arttı mı? (pozitif değerler: mat ediyor)"""
    if after_mate is None or after_mate <= 0:
        return False
    if before_mate is None or before_mate <= 0:
        return True
    return abs(after_mate) < abs(before_mate)


def pick_comment(before, after, mover_color, mover_name, opponent_name,
                 game_over=False, winner_color=None, flags=None):
    """(event, text) döndürür veya yorum gerekmiyorsa ``None``."""
    mover = mover_name or 'Oyuncu'
    opp = opponent_name or 'Rakip'
    flags = flags or {}

    if game_over:
        if winner_color == mover_color:
            event = EVENT_WIN
        elif winner_color is None:
            return None
        else:
            event = EVENT_LOSE
        return event, _render(event, mover, opp)

    m_before = _pov(before, mover_color)
    m_after = _pov(after, mover_color)

    # 1) Mat riski belirgin şekilde arttı.
    if (
        m_after['mate'] is not None
        and m_after['mate'] < 0
        and abs(m_after['mate']) <= MATE_MAX_N
        and _mate_got_closer(m_before['mate'], m_after['mate'])
    ):
        return EVENT_MATE_DANGER, _render(EVENT_MATE_DANGER, mover, opp)

    # 2) Oyuncu mat etmeye ciddi yaklaştı.
    if (
        m_after['mate'] is not None
        and m_after['mate'] > 0
        and abs(m_after['mate']) <= MATE_MAX_N
        and _mate_improved(m_before['mate'], m_after['mate'])
    ):
        return EVENT_MATE_CHANCE, _render(EVENT_MATE_CHANCE, mover, opp)

    # 3) Taktiksel/kısa olaylar.
    if flags.get('is_promotion'):
        return EVENT_PROMOTION, _render(EVENT_PROMOTION, mover, opp)
    if flags.get('is_big_capture'):
        return EVENT_BIG_CAPTURE, _render(EVENT_BIG_CAPTURE, mover, opp)
    if flags.get('gives_check'):
        return EVENT_CHECK, _render(EVENT_CHECK, mover, opp)
    if flags.get('is_castling'):
        return EVENT_CASTLE, _render(EVENT_CASTLE, mover, opp)

    # 4) Büyük değerlendirme savrulmaları.
    cp_before = _approx_cp(m_before)
    cp_after = _approx_cp(m_after)
    if cp_before is None or cp_after is None:
        return None

    swing = cp_after - cp_before
    if swing <= -BLUNDER_SWING:
        return EVENT_BLUNDER, _render(EVENT_BLUNDER, mover, opp)
    if swing >= GREAT_SWING:
        return EVENT_GREAT, _render(EVENT_GREAT, mover, opp)

    return None


def game_start_text(white_name, black_name):
    white = white_name or 'Beyaz'
    black = black_name or 'Siyah'
    return _render(EVENT_GAME_START, white, black)


def _render(event, mover, opp, exclude=None):
    options = _TEMPLATES.get(event) or []
    if not options:
        return ''
    choices = [t for t in options if t != exclude] or options
    template = random.choice(choices)
    return template.format(mover=mover, opp=opp, white=mover, black=opp)


class CommentCooldown:
    """Aynı/benzer yorumların art arda tetiklenmesini engeller."""

    def __init__(self, min_interval=7.0, event_interval=20.0):
        self.min_interval = max(0.0, float(min_interval))
        self.event_interval = max(0.0, float(event_interval))
        self._last_time = 0.0
        self._last_event = None
        self._event_time = {}
        self._last_text = None
        self._text_time = 0.0

    def allow(self, event, text, now=None):
        now = time.monotonic() if now is None else now
        if now - self._last_time < self.min_interval:
            return False
        if now - self._event_time.get(event, float('-inf')) < self.event_interval:
            return False
        if text and text == self._last_text and now - self._text_time < self.event_interval:
            return False
        return True

    def mark(self, event, text, now=None):
        now = time.monotonic() if now is None else now
        self._last_time = now
        self._last_event = event
        self._event_time[event] = now
        self._last_text = text
        self._text_time = now

    def reset(self):
        self._last_time = 0.0
        self._last_event = None
        self._event_time = {}
        self._last_text = None
        self._text_time = 0.0
