"""HTTP API and page rendering tests for FC Manager."""

from __future__ import annotations

import json

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from fcmanager.data import SLOTS
from fcmanager.models import Participant, Room
from fcmanager.tests.helpers import available_candidates, fill_squad

IN_MEMORY = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
API = '/fcmanager/api/rooms/'


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class RoomApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def post(self, path, payload=None, token=''):
        headers = {}
        if token:
            headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.client.post(
            path,
            data=json.dumps(payload or {}),
            content_type='application/json',
            **headers,
        )

    def get(self, path, token=''):
        headers = {}
        if token:
            headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.client.get(path, **headers)

    def create(self, name='Host'):
        response = self.post(API, {'name': name})
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def join(self, room_code, name):
        return self.post(API + 'join/', {'room_code': room_code, 'name': name})

    def test_create_join_and_state(self):
        created = self.create()
        code = created['room_code']
        self.assertRegex(code, r'^[A-Z0-9]{6}$')
        self.assertGreater(len(created['session_token']), 20)

        joined = self.join(code, 'Guest')
        self.assertEqual(joined.status_code, 200, joined.content)
        token = joined.json()['session_token']

        state = self.get(API + code + '/state/', token)
        self.assertEqual(state.status_code, 200)
        payload = state.json()['state']
        self.assertEqual(payload['room']['status'], 'WAITING')
        self.assertEqual(len(payload['players']), 2)
        self.assertEqual(payload['you']['name'], 'Guest')
        self.assertEqual(payload['you']['side'], 'away')
        self.assertEqual(payload['market'], [])
        self.assertNotIn('session_token', json.dumps(payload))
        self.assertNotIn('session_token_hash', json.dumps(payload))

    def test_state_requires_valid_room_token(self):
        created = self.create()
        code = created['room_code']
        self.assertEqual(self.get(API + code + '/state/').status_code, 401)
        self.assertEqual(self.get(API + code + '/state/', 'invalid').status_code, 401)

    def test_room_code_isolation(self):
        first = self.create('Host A')
        second = self.create('Host B')
        response = self.get(API + second['room_code'] + '/state/', first['session_token'])
        self.assertEqual(response.status_code, 401)

    def test_start_draft_pick_swap_and_clear_api(self):
        created = self.create()
        code = created['room_code']
        token = created['session_token']
        self.assertEqual(self.join(code, 'Guest').status_code, 200)

        started = self.post(API + code + '/start-draft/', {}, token)
        self.assertEqual(started.status_code, 200, started.content)
        state = started.json()['state']
        self.assertEqual(state['room']['status'], 'DRAFT')
        self.assertEqual(len(state['market']), 80)
        self.assertEqual(len(state['slots']), len(SLOTS))

        room = Room.objects.get(room_code=code)
        gk = available_candidates(room, 'gk')[0]
        picked = self.post(
            API + code + '/pick/',
            {'player_id': gk.pk, 'slot': 'gk'},
            token,
        )
        self.assertEqual(picked.status_code, 200, picked.content)
        entry = next(item for item in picked.json()['state']['market'] if item['id'] == gk.pk)
        self.assertTrue(entry['picked_by_you'])
        self.assertEqual(entry['slot'], 'gk')

        swapped = self.post(
            API + code + '/swap/',
            {'from_slot': 'gk', 'to_slot': 'gk'},
            token,
        )
        self.assertEqual(swapped.status_code, 200, swapped.content)

        cleared = self.post(API + code + '/clear/', {}, token)
        self.assertEqual(cleared.status_code, 200, cleared.content)
        self.assertEqual(cleared.json()['state']['you']['slots_filled'], 0)

    def test_pick_validation_errors_are_json(self):
        created = self.create()
        code = created['room_code']
        token = created['session_token']
        self.join(code, 'Guest')
        self.post(API + code + '/start-draft/', {}, token)
        room = Room.objects.get(room_code=code)
        gk = available_candidates(room, 'gk')[0]

        wrong_slot = self.post(API + code + '/pick/', {'player_id': gk.pk, 'slot': 'st'}, token)
        self.assertEqual(wrong_slot.status_code, 400)
        self.assertEqual(wrong_slot.json()['code'], 'position_mismatch')

        bad_player = self.post(API + code + '/pick/', {'player_id': 999999, 'slot': 'gk'}, token)
        self.assertEqual(bad_player.status_code, 404)
        self.assertEqual(bad_player.json()['code'], 'player_not_found')

    def test_full_match_and_new_season_flow(self):
        created = self.create()
        code = created['room_code']
        host_token = created['session_token']
        guest = self.join(code, 'Guest').json()
        away_token = guest['session_token']

        started = self.post(API + code + '/start-draft/', {}, host_token)
        self.assertEqual(started.status_code, 200, started.content)

        room = Room.objects.get(room_code=code)
        host = Participant.objects.get(room=room, side='home')
        away = Participant.objects.get(room=room, side='away')
        fill_squad(room, host, lock=False)
        fill_squad(room, away, lock=False)

        host_locked = self.post(API + code + '/lock/', {}, host_token)
        self.assertEqual(host_locked.status_code, 200, host_locked.content)
        away_locked = self.post(API + code + '/lock/', {}, away_token)
        self.assertEqual(away_locked.status_code, 200, away_locked.content)

        match_response = self.post(API + code + '/start-match/', {}, host_token)
        self.assertEqual(match_response.status_code, 200, match_response.content)
        match_state = match_response.json()['state']
        self.assertEqual(match_state['room']['status'], 'FINISHED')
        self.assertIsNotNone(match_state['match'])
        self.assertTrue(match_state['match']['events'])
        self.assertIn('home', match_state['match'])
        self.assertIn('away', match_state['match'])
        self.assertIn('stats', match_state['match'])

        new_season = self.post(API + code + '/new-season/', {}, host_token)
        self.assertEqual(new_season.status_code, 200, new_season.content)
        reset = new_season.json()['state']
        self.assertEqual(reset['room']['status'], 'DRAFT')
        self.assertIsNone(reset['match'])
        self.assertEqual(reset['you']['slots_filled'], 0)
        self.assertEqual(reset['opponent']['slots_filled'], 0)
        self.assertEqual(len(reset['market']), 80)
        self.assertGreaterEqual(len(reset['room']['challenges']), 3)

    def test_host_only_actions(self):
        created = self.create()
        code = created['room_code']
        host_token = created['session_token']
        away_token = self.join(code, 'Guest').json()['session_token']

        self.assertEqual(self.post(API + code + '/start-draft/', {}, away_token).status_code, 403)
        self.assertEqual(self.post(API + code + '/start-draft/', {}, host_token).status_code, 200)

        room = Room.objects.get(room_code=code)
        host = Participant.objects.get(room=room, side='home')
        away = Participant.objects.get(room=room, side='away')
        fill_squad(room, host, lock=True)
        fill_squad(room, away, lock=True)

        self.assertEqual(self.post(API + code + '/start-match/', {}, away_token).status_code, 403)
        self.assertEqual(self.post(API + code + '/start-match/', {}, host_token).status_code, 200)
        self.assertEqual(self.post(API + code + '/new-season/', {}, away_token).status_code, 403)
        self.assertEqual(self.post(API + code + '/new-season/', {}, host_token).status_code, 200)

    def test_leave_api(self):
        created = self.create()
        code = created['room_code']
        token = created['session_token']
        self.join(code, 'Guest')
        response = self.post(API + code + '/leave/', {}, token)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.get(API + code + '/state/', token).status_code, 401)

    def test_invalid_json_and_methods(self):
        created = self.create()
        code = created['room_code']
        response = self.client.post(
            API + code + '/pick/',
            data='{not json',
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {created["session_token"]}',
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'invalid_json')
        self.assertEqual(self.get(API + code + '/start-draft/').status_code, 405)

    def test_create_rate_limit(self):
        for index in range(10):
            self.assertRegex(self.create(f'Host {index}')['room_code'], r'^[A-Z0-9]{6}$')
        limited = self.post(API, {'name': 'Too Many'})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()['code'], 'rate_limited')

    def test_health_and_pages_render(self):
        health = self.get('/fcmanager/health/')
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()['status'], 'ok')

        home = self.get('/fcmanager/')
        self.assertEqual(home.status_code, 200)
        self.assertIn('FC Manager', home.content.decode())

        created = self.create()
        page = self.get('/fcmanager/room/' + created['room_code'] + '/')
        self.assertEqual(page.status_code, 200)
        markup = page.content.decode()
        self.assertIn('fc-app', markup)
        self.assertIn('fc-market-panel', markup)
        self.assertIn('fc-result', markup)


@override_settings(CHANNEL_LAYERS=IN_MEMORY)
class PageInviteTests(TestCase):
    def test_invite_code_is_forwarded_to_the_home_page(self):
        response = self.client.get('/fcmanager/?oda=abc123')
        self.assertEqual(response.status_code, 200)
        self.assertIn('ABC123', response.content.decode())
