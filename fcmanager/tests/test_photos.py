"""Local player photos: download cache, URL choice and the photo endpoint.

The FC26 CDN requires a ``sofifa.com`` Referer, which a browser cannot send,
so the game downloads the faces (``fcmanager/download_player.py``) and serves
them from ``/fcmanager/photos/<player_id>.png``. These tests cover that path.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase

from fcmanager import data, services
from fcmanager.models import MarketPlayer, Player

PNG_1PX = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='
)
CDN = 'https://cdn.sofifa.net/players/000/123/26_120.png'


class PhotoDirectoryMixin:
    """Point ``data.PLAYER_IMAGE_DIR`` at a throwaway folder."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.photo_dir = Path(tmp.name)
        patcher = mock.patch.object(data, 'PLAYER_IMAGE_DIR', self.photo_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        data.clear_photo_cache()
        self.addCleanup(data.clear_photo_cache)

    def save_photo(self, player_id) -> Path:
        path = self.photo_dir / f'{player_id}.png'
        path.write_bytes(PNG_1PX)
        data.clear_photo_cache()
        return path


class PhotoUrlTests(PhotoDirectoryMixin, SimpleTestCase):
    def test_falls_back_to_the_cdn_link_when_nothing_is_downloaded(self):
        self.assertEqual(data.photo_url(123, CDN), CDN)

    def test_falls_back_to_an_empty_string_without_a_cdn_link(self):
        self.assertEqual(data.photo_url(123), '')

    def test_prefers_the_downloaded_file(self):
        self.save_photo(123)
        self.assertEqual(data.photo_url(123, CDN), '/fcmanager/photos/123.png')

    def test_with_photo_returns_a_copy(self):
        self.save_photo(9)
        original = {'player_id': 9, 'image_url': CDN}
        updated = data.with_photo(original)
        self.assertEqual(updated['image_url'], '/fcmanager/photos/9.png')
        self.assertEqual(original['image_url'], CDN)

    def test_with_photo_keeps_the_original_dict_when_already_local(self):
        player = {'player_id': 9, 'image_url': CDN}
        self.assertIs(data.with_photo(player), player)

    def test_player_to_dict_uses_the_local_photo(self):
        self.save_photo(77)
        player = Player(player_id=77, name='Test Oyuncu', image_url=CDN)
        self.assertEqual(player.to_dict()['image_url'], '/fcmanager/photos/77.png')

    def test_serialize_market_player_uses_the_local_photo(self):
        self.save_photo(88)
        market_player = MarketPlayer(
            player_id=88,
            data={'player_id': 88, 'name': 'Test', 'image_url': CDN},
        )
        self.assertEqual(
            services.serialize_market_player(market_player)['image_url'],
            '/fcmanager/photos/88.png',
        )


class PhotoViewTests(PhotoDirectoryMixin, SimpleTestCase):
    def test_serves_the_downloaded_image_with_long_cache(self):
        self.save_photo(42)
        response = self.client.get('/fcmanager/photos/42.png')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertIn('immutable', response['Cache-Control'])
        self.assertEqual(b''.join(response.streaming_content), PNG_1PX)

    def test_missing_photo_returns_404(self):
        response = self.client.get('/fcmanager/photos/43.png')
        self.assertEqual(response.status_code, 404)