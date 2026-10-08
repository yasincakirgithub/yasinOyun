"""ElevenLabs ile Türkçe metinden sese.

Üretilen ses **hiçbir yere yazılmaz** (ne dosya, ne S3, ne DB). ElevenLabs'in
streaming uç noktasından 16-bit PCM olarak okunur ve doğrudan ham bayt
parçaları halinde döndürülür; böylece WebSocket üzerinden binary gönderilebilir.

API anahtarı ``ELEVENLABS_API_KEY`` ortam değişkeninden alınır. Anahtar yoksa
veya istek başarısız olursa sessizce vazgeçilir (yorum metni yine gösterilir).
"""

import json
import logging
from urllib import error, request

from django.conf import settings

logger = logging.getLogger('satranc')

# Okuma parça boyutu (~0.34 sn @ 24 kHz, 16-bit mono).
_READ_SIZE = 16384


def api_key():
    return getattr(settings, 'ELEVENLABS_API_KEY', '') or ''


def is_available():
    return bool(api_key())


def sample_rate():
    return int(getattr(settings, 'SATRANC_TTS_SAMPLE_RATE', 24000))


def _output_format():
    return getattr(settings, 'ELEVENLABS_OUTPUT_FORMAT', 'pcm_24000')


def stream_audio(text, sample_rate=None):
    """Metni 16-bit little-endian mono PCM parçaları olarak üretir.

    Hiçbir dosya oluşturulmaz. Bu üretici blocking olduğu için tüketiciden
    bağımsız bir thread'de çalıştırılmalıdır (bkz. ``consumers``).
    """
    key = api_key()
    if not key or not text:
        return

    voice_id = getattr(settings, 'ELEVENLABS_VOICE_ID', '21m00Tcm4TlvDq8ikWAM')
    model_id = getattr(settings, 'ELEVENLABS_MODEL_ID', 'eleven_flash_v2_5')
    base_url = getattr(
        settings, 'ELEVENLABS_BASE_URL', 'https://api.elevenlabs.io/v1'
    ).rstrip('/')
    url = f'{base_url}/text-to-speech/{voice_id}/stream?output_format={_output_format()}'

    # Konuşma hızını API'nin izin verdiği aralığa sıkıştır (0.7 - 1.2).
    speed = float(getattr(settings, 'ELEVENLABS_SPEED', 0.9))
    speed = max(0.7, min(1.2, speed))

    payload = json.dumps({
        'text': text,
        'model_id': model_id,
        'voice_settings': {
            'stability': 0.4,
            'similarity_boost': 0.8,
            'style': 0.3,
            'use_speaker_boost': True,
            'speed': speed,
        },
    }).encode('utf-8')

    req = request.Request(
        url,
        data=payload,
        headers={
            'xi-api-key': key,
            'Content-Type': 'application/json',
            'Accept': 'audio/pcm',
        },
        method='POST',
    )

    try:
        with request.urlopen(req, timeout=20) as resp:
            while True:
                chunk = resp.read(_READ_SIZE)
                if not chunk:
                    break
                yield chunk
    except error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8', 'ignore')[:200]
        except Exception:  # pragma: no cover - savunmaci
            pass
        logger.warning('ElevenLabs TTS HTTP %s: %s', exc.code, detail)
    except Exception as exc:  # pragma: no cover - ag hatasi
        logger.warning('ElevenLabs TTS hatası: %s', exc)
