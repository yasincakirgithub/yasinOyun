"""HTTP API and page rendering tests for the Character Auction game."""

from __future__ import annotations

import json
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from auction import services
from auction.models import AuctionRoom

from .helpers import started_room


class AuctionApiTestCase(TestCase):
    def setUp(self):
        # The rate limiter is process-global and would leak between tests.
        patcher = mock.patch('auction.views.allow_rate', return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        from auction.utils import _rate_limit_cache
        _rate_limit_cache.clear()

    def post(self, path, payload, token=None):
        headers = {}
        if token:
            headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.client.post(
            path,
            data=json.dumps(payload),
            content_type='application/json',
            **headers,
        )

    def get(self, path, token=None):
        headers = {}
        if token:
            headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.client.get(path, **headers)

    def create_room(self, name='Host'):
        response = self.post('/auction/api/rooms/', {'name': name})
        self.assertEqual(response.status_code, 201, response.content)
        payload = response.json()
        return payload['room_code'], payload['session_token']

    def join_room(self, room_code, name='Guest'):
        response = self.post(
            '/auction/api/rooms/join/',
            {'room_code': room_code, 'name': name},
        )
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()
        return payload['session_token'], payload


class RoomApiTests(AuctionApiTestCase):
    def test_create_join_and_read_state(self):
        room_code, host_token = self.create_room('Host')
        self.assertRegex(room_code, r'^[A-Z0-9]{6}$')

        response = self.get(f'/auction/api/rooms/{room_code}/state/', host_token)
        self.assertEqual(response.status_code, 200)
        state = response.json()['state']
        self.assertEqual(state['room']['status'], 'WAITING')
        self.assertEqual(state['me']['display_name'], 'Host')
        self.assertTrue(state['permissions']['is_host'])
        self.assertEqual(len(state['theme_info']['themes']), 10)

        guest_token, payload = self.join_room(room_code, 'Guest')
        self.assertFalse(payload['rejoined'])
        self.assertEqual(len(payload['state']['players']), 2)

        response = self.get(f'/auction/api/rooms/{room_code}/state/', guest_token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['state']['players']), 2)

    def test_state_requires_a_valid_session(self):
        room_code, host_token = self.create_room('Host')

        response = self.get(f'/auction/api/rooms/{room_code}/state/')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'auth_required')

        response = self.get(f'/auction/api/rooms/{room_code}/state/', 'bogus')
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'invalid_session')

        response = self.get('/auction/api/rooms/NOPE00/state/', host_token)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'invalid_session')

    def test_settings_theme_and_start_flow(self):
        room_code, host_token = self.create_room('Host')
        guest_token, _ = self.join_room(room_code, 'Guest')

        response = self.post(
            f'/auction/api/rooms/{room_code}/settings/',
            {'settings': {'character_count': 3}},
            guest_token,
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'host_only')

        response = self.post(
            f'/auction/api/rooms/{room_code}/settings/',
            {'settings': {'character_count': 3}},
            host_token,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['state']['room']['character_count'], 3)

        response = self.post(
            f'/auction/api/rooms/{room_code}/theme/',
            {'theme_id': 'unknown-theme'},
            host_token,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_theme')

        response = self.post(
            f'/auction/api/rooms/{room_code}/theme/',
            {'theme_id': 'naruto'},
            host_token,
        )
        self.assertEqual(response.status_code, 200)
        state = response.json()['state']
        self.assertEqual(state['room']['status'], 'THEME_SELECT')
        self.assertEqual(state['theme_info']['selected_theme']['id'], 'naruto')
        self.assertGreaterEqual(
            len(state['theme_info']['selected_theme']['synergies']), 5
        )
        self.assertTrue(state['theme_info']['selected_theme']['characters'])

        response = self.post(
            f'/auction/api/rooms/{room_code}/start/', {}, guest_token
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'host_only')

        response = self.post(
            f'/auction/api/rooms/{room_code}/start/', {}, host_token
        )
        self.assertEqual(response.status_code, 200)
        state = response.json()['state']
        self.assertEqual(state['room']['status'], 'AUCTION')
        self.assertEqual(state['current_auction']['total_auctions'], 3)
        self.assertEqual(state['current_auction']['auction_number'], 1)
        self.assertIsNotNone(state['current_auction']['character']['name'])


class BidApiTests(AuctionApiTestCase):
    def setUp(self):
        super().setUp()
        self.room, players = started_room(
            character_ids=['marvel_iron_man', 'marvel_thor']
        )
        self.host_token = players[0][1]
        self.guest_token = players[1][1]
        self.room_code = self.room.room_code

    def test_bid_updates_state_and_validation_errors(self):
        response = self.post(
            f'/auction/api/rooms/{self.room_code}/bid/',
            {'amount': 150},
            self.guest_token,
        )
        self.assertEqual(response.status_code, 200)
        auction = response.json()['state']['current_auction']
        self.assertEqual(auction['current_bid'], 150)
        self.assertEqual(auction['current_bidder']['name'], 'Guest')

        response = self.post(
            f'/auction/api/rooms/{self.room_code}/bid/',
            {'amount': 200},
            self.guest_token,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'bid_against_self')

        response = self.post(
            f'/auction/api/rooms/{self.room_code}/bid/',
            {'amount': 150},
            self.host_token,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'bid_too_low')

        response = self.post(
            f'/auction/api/rooms/{self.room_code}/bid/',
            {'amount': 5000},
            self.host_token,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'insufficient_budget')

        response = self.post(
            f'/auction/api/rooms/{self.room_code}/bid/',
            {},
            self.host_token,
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'amount_required')

    def test_quick_bid_increment_targets_are_available(self):
        response = self.post(
            f'/auction/api/rooms/{self.room_code}/bid/',
            {'amount': 1100},
            self.guest_token,
        )
        self.assertEqual(response.status_code, 200)
        auction = response.json()['state']['current_auction']
        self.assertEqual(auction['current_bid'], 1100)
        self.assertEqual(auction['current_bidder']['id'], str(self.room.players.get(display_name='Guest').pk))

    def test_state_request_processes_expired_auction(self):
        AuctionRoom.objects.filter(pk=self.room.pk).update(
            auction_deadline=timezone.now() - timedelta(seconds=1)
        )

        response = self.get(
            f'/auction/api/rooms/{self.room_code}/state/', self.guest_token
        )
        self.assertEqual(response.status_code, 200)
        state = response.json()['state']
        self.assertEqual(state['room']['current_character_index'], 1)
        self.assertEqual(state['current_auction']['auction_number'], 2)

    def test_new_game_requires_finished_room_and_host(self):
        response = self.post(
            f'/auction/api/rooms/{self.room_code}/new-game/', {}, self.host_token
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'game_not_finished')

        AuctionRoom.objects.filter(pk=self.room.pk).update(
            status='AUCTION',
            current_character_index=len(self.room.get_auction_characters()),
            current_highest_bidder=None,
            auction_deadline=timezone.now() - timedelta(seconds=1),
        )
        response = self.get(
            f'/auction/api/rooms/{self.room_code}/state/', self.host_token
        )
        self.assertEqual(response.json()['state']['room']['status'], 'FINISHED')

        response = self.post(
            f'/auction/api/rooms/{self.room_code}/new-game/', {}, self.guest_token
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['code'], 'host_only')

        response = self.post(
            f'/auction/api/rooms/{self.room_code}/new-game/', {}, self.host_token
        )
        self.assertEqual(response.status_code, 200)
        state = response.json()['state']
        self.assertEqual(state['room']['status'], 'WAITING')
        self.assertEqual(state['room']['theme_id'], '')
        self.assertEqual(state['me']['budget'], state['room']['starting_budget'])
        self.assertEqual(state['me']['owned_characters'], [])


class PageRenderingTests(TestCase):
    def test_home_page_uses_shared_platform_layout(self):
        response = self.client.get('/auction/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'site-nav')
        self.assertContains(response, 'game-container')
        self.assertContains(response, 'Character Auction')
        self.assertContains(response, 'ODA KUR')
        self.assertContains(response, 'KATIL')

    def test_game_room_page_flags_missing_and_existing_rooms(self):
        response = self.client.get('/auction/room/NOPE00/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-room-exists="0"')

        room, _ = started_room(character_ids=['marvel_iron_man', 'marvel_thor'])
        response = self.client.get(f'/auction/room/{room.room_code}/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-room-exists="1"')
        self.assertContains(response, room.room_code)
