import atexit
import logging
import sys

from django.apps import AppConfig

logger = logging.getLogger('satranc')


def _is_serving_process():
    argv = ' '.join(sys.argv)
    if 'uvicorn' in argv or 'daphne' in argv or 'gunicorn' in argv:
        return True
    return len(sys.argv) > 1 and sys.argv[1] == 'runserver'


class SatrancConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'satranc'
    verbose_name = 'Satranç'

    def ready(self):
        from . import analyzer

        atexit.register(analyzer.shutdown)

        if not _is_serving_process():
            return
        try:
            if analyzer.warmup():
                logger.info('Yerel Stockfish motoru hazır.')
        except Exception as exc:  # pragma: no cover - savunmaci
            logger.warning('Stockfish ısındırma başarısız: %s', exc)
