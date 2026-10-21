import json

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from codenames import services
from codenames.models import GamePlayer, GameRoom
from codenames.tests.helpers import create_room_with_players, start_room
from codenames.utils import origin_is_allowed

IN_MEMORY = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}
API = '/codenames/api/rooms/'


@override_settings(CHANNEL_LAYERS=IN_MEMORY, DEEPSEEK_API_KEY='')
class RoomApiTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def post(self, path, payload=None, token=''):
        headers = {}
        if token:
            headers['HTTP_AUTHORIZATION'] = f'Bearer {token}'
        return self.client.post(path, data=json.dumps(payload or {}), content_type='application/json', **headers)

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
        room_code = created['room_code']
        self.assertGreater(len(created['session_token']), 20)
        joined = self.join(room_code, 'Guest')
        self.assertEqual(joined.status_code, 200, joined.content)
        token = joined.json()['session_token']
        state = self.get(API + room_code + '/state/', token)
        self.assertEqual(state.status_code, 200)
        payload = state.json()['state']
        self.assertEqual(payload['room']['player_count'], 2)
        self.assertEqual(len(payload['players']), 2)
        self.assertEqual(payload['me']['display_name'], 'Guest')
        self.assertNotIn('session_token', json.dumps(payload))
        self.assertNotIn('session_token_hash', json.dumps(payload))

    def test_state_requires_valid_room_token(self):
        created = self.create()
        self.assertEqual(self.get(API + created['room_code'] + '/state/').status_code, 401)
        self.assertEqual(self.get(API + created['room_code'] + '/state/', 'invalid').status_code, 401)

    def test_room_code_isolation(self):
        room_a = self.create('Host A')
        room_b = self.create('Host B')
        response = self.get(API + room_b['room_code'] + '/state/', room_a['session_token'])
        self.assertEqual(response.status_code, 401)

    def test_reconnect_reuses_identity(self):
        created = self.create()
        response = self.post(API + 'join/', {
            'room_code': created['room_code'],
            'name': 'Host',
            'session_token': created['session_token'],
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['rejoined'])
        self.assertEqual(GameRoom.objects.get(room_code=created['room_code']).players.count(), 1)

    def test_capacity_and_duplicate_name(self):
        created = self.create()
        code = created['room_code']
        for index in range(9):
            response = self.join(code, f'P{index}')
            self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(self.join(code, 'P9').status_code, 409)
        self.assertEqual(GameRoom.objects.get(room_code=code).players.count(), 10)
        self.assertEqual(self.join(code, 'P1').status_code, 409)

    def test_host_only_settings_and_roles(self):
        created = self.create()
        code = created['room_code']
        guest = self.join(code, 'Guest').json()
        response = self.post(API + code + '/settings/', {'timer_seconds': 60}, guest['session_token'])
        self.assertEqual(response.status_code, 403)
        response = self.post(API + code + '/settings/', {'timer_seconds': 60, 'language': 'en'}, created['session_token'])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()['state']['room']['settings']['timer_seconds'], 60)
        self.assertEqual(response.json()['state']['room']['language'], 'en')

    def test_start_requires_roles_and_min_players(self):
        created = self.create()
        code = created['room_code']
        self.join(code, 'Guest')
        response = self.post(API + code + '/start/', {}, created['session_token'])
        self.assertEqual(response.status_code, 400)
        self.assertIn('4 oyuncu', response.json()['error'])

        self.join(code, 'Guest 2')
        self.join(code, 'Guest 3')
        members = GamePlayer.objects.filter(room__room_code=code)
        assignments = [
            {'player_id': str(member.pk), 'team': 'red', 'role': 'operative'}
            for member in members
        ]
        assigned = self.post(API + code + '/assign-roles/', {'assignments': assignments}, created['session_token'])
        self.assertEqual(assigned.status_code, 200, assigned.content)
        response = self.post(API + code + '/start/', {}, created['session_token'])
        self.assertEqual(response.status_code, 400)
        self.assertIn('spymaster', response.json()['error'].lower())

    def test_clue_guess_and_end_turn_api(self):
        created = self.create()
        code = created['room_code']
        tokens = [created['session_token']]
        for index in range(3):
            tokens.append(self.join(code, f'P{index}').json()['session_token'])
        self.post(API + code + '/settings/', {'starting_team': 'red'}, created['session_token'])
        self.post(API + code + '/assign-roles/', {'auto': True}, created['session_token'])
        started = self.post(API + code + '/start/', {}, created['session_token'])
        self.assertEqual(started.status_code, 200, started.content)
        spy_board = started.json()['state']['session']['board']
        target = next(card for card in spy_board if card['category'] == 'red')

        clue = self.post(API + code + '/clue/', {'word': 'zzzzclue', 'number': 2}, created['session_token'])
        self.assertEqual(clue.status_code, 200, clue.content)
        self.assertEqual(clue.json()['state']['session']['clue']['word'], 'zzzzclue')

        red_op_token = tokens[2]
        guess = self.post(API + code + '/guess/', {'position': target['position']}, red_op_token)
        self.assertEqual(guess.status_code, 200, guess.content)
        self.assertEqual(guess.json()['result']['category'], 'red')

        passed = self.post(API + code + '/end-turn/', {}, red_op_token)
        self.assertEqual(passed.status_code, 200, passed.content)
        self.assertEqual(passed.json()['state']['session']['current_team'], 'blue')

    def test_player_can_choose_own_team_and_role(self):
        created = self.create()
        code = created['room_code']
        first = self.join(code, 'First').json()
        second = self.join(code, 'Second').json()

        state = self.get(API + code + '/state/', second['session_token']).json()['state']
        self.assertTrue(state['permissions']['can_choose_role'])

        occupied = self.post(
            API + code + '/preference/',
            {'team': 'blue', 'role': 'spymaster'},
            second['session_token'],
        )
        self.assertEqual(occupied.status_code, 409, occupied.content)
        self.assertEqual(occupied.json()['code'], 'spymaster_taken')

        released = self.post(
            API + code + '/preference/',
            {'team': 'blue', 'role': 'operative'},
            first['session_token'],
        )
        self.assertEqual(released.status_code, 200, released.content)

        chosen = self.post(
            API + code + '/preference/',
            {'team': 'blue', 'role': 'spymaster'},
            second['session_token'],
        )
        self.assertEqual(chosen.status_code, 200, chosen.content)
        self.assertEqual(chosen.json()['state']['me']['team'], 'blue')
        self.assertEqual(chosen.json()['state']['me']['role'], 'spymaster')

    def test_preference_is_locked_after_start(self):
        room, host, host_token, entries = create_room_with_players(4, language='en')
        start_room(room, host)
        response = self.post(
            API + room.room_code + '/preference/',
            {'team': 'blue', 'role': 'operative'},
            entries[1][1],
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['code'], 'game_started')

    def test_guess_history_groups_each_clue_with_revealed_words(self):
        room, host, host_token, entries = create_room_with_players(4, language='en')
        start_room(room, host)
        operative_token = entries[2][1]
        board = self.get(API + room.room_code + '/state/', host_token).json()['state']['session']['board']
        targets = [card for card in board if card['category'] == 'red'][:2]

        clue = self.post(
            API + room.room_code + '/clue/',
            {'word': 'zzzzclue', 'number': 2},
            host_token,
        )
        self.assertEqual(clue.status_code, 200, clue.content)
        for target in targets:
            guess = self.post(
                API + room.room_code + '/guess/',
                {'position': target['position']},
                operative_token,
            )
            self.assertEqual(guess.status_code, 200, guess.content)

        state = self.get(API + room.room_code + '/state/', operative_token).json()['state']
        history = state['guess_history']
        self.assertEqual(len(history), 1)
        group = history[0]
        self.assertEqual(group['turn'], 1)
        self.assertEqual(group['team'], 'red')
        self.assertEqual(group['clue'], 'zzzzclue')
        self.assertEqual([guess['word'] for guess in group['guesses']], [t['word'] for t in targets])
        self.assertTrue(all(guess['category'] == 'red' for guess in group['guesses']))
        self.assertTrue(all(guess['display_name'] for guess in group['guesses']))

    def test_auto_assign_and_start(self):
        created = self.create()
        code = created['room_code']
        tokens = [created['session_token']]
        for index in range(3):
            tokens.append(self.join(code, f'P{index}').json()['session_token'])
        settings = self.post(API + code + '/settings/', {'starting_team': 'red'}, created['session_token'])
        self.assertEqual(settings.status_code, 200, settings.content)
        response = self.post(API + code + '/assign-roles/', {'auto': True}, created['session_token'])
        self.assertEqual(response.status_code, 200, response.content)
        response = self.post(API + code + '/start/', {}, created['session_token'])
        self.assertEqual(response.status_code, 200, response.content)
        payload = response.json()['state']
        self.assertEqual(payload['room']['status'], 'IN_PROGRESS')
        self.assertEqual(len(payload['session']['board']), 25)
        self.assertEqual(payload['session']['remaining'], {'red': 9, 'blue': 8})
        second = self.post(API + code + '/start/', {}, created['session_token'])
        self.assertEqual(second.status_code, 400)

    def test_operative_api_never_leaks_unrevealed_categories(self):
        room, host, host_token, entries = create_room_with_players(4, language='en')
        start_room(room, host)
        operative_token = entries[2][1]
        response = self.get(API + room.room_code + '/state/', operative_token)
        self.assertEqual(response.status_code, 200)
        board = response.json()['state']['session']['board']
        self.assertTrue(all(card['category'] is None for card in board))
        spymaster_response = self.get(API + room.room_code + '/state/', host_token)
        spy_board = spymaster_response.json()['state']['session']['board']
        self.assertTrue(all(card['category'] for card in spy_board))

    def test_leave_transfers_host(self):
        room, host, host_token, entries = create_room_with_players(4, language='en')
        response = self.post(API + room.room_code + '/leave/', {}, host_token)
        self.assertEqual(response.status_code, 200)
        room.refresh_from_db()
        self.assertIsNotNone(room.host_id)
        self.assertNotEqual(room.host_id, host.pk)
        invalid = self.get(API + room.room_code + '/state/', host_token)
        self.assertEqual(invalid.status_code, 401)

    def test_chat_api(self):
        created = self.create()
        code = created['room_code']
        response = self.post(API + code + '/chat/', {'text': '  merhaba   takım  '}, created['session_token'])
        self.assertEqual(response.status_code, 200, response.content)
        messages = response.json()['state']['messages']
        self.assertEqual(messages[-1]['text'], 'merhaba takım')
        self.assertEqual(messages[-1]['display_name'], 'Host')

    def test_health(self):
        response = self.get('/healthz/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'ok')

    def test_home_and_room_pages_render(self):
        home = self.get('/codenames/')
        self.assertEqual(home.status_code, 200)
        content = home.content.decode()
        self.assertIn('ODA KUR', content)
        self.assertIn('Oyuna Katıl', content)
        created = self.create()
        page = self.get('/codenames/room/' + created['room_code'] + '/')
        self.assertEqual(page.status_code, 200)
        markup = page.content.decode()
        self.assertIn('cn-board', markup)
        self.assertIn('cn-clue-form', markup)
        self.assertIn('aria-live', markup)
        self.assertIn('cn-gameover', markup)
        self.assertIn('word-source', markup)


@override_settings(ALLOWED_HOSTS=['example.com'], CSRF_TRUSTED_ORIGINS=[], DEBUG=False)
class OriginTests(TestCase):
    def test_same_host_origin_is_allowed(self):
        self.assertTrue(origin_is_allowed('http://192.168.1.50:8000', '192.168.1.50:8000'))
        self.assertTrue(origin_is_allowed('https://example.com', 'example.com'))
        self.assertFalse(origin_is_allowed('https://evil.example', 'example.com'))
        self.assertFalse(origin_is_allowed('not-a-url', 'example.com'))
