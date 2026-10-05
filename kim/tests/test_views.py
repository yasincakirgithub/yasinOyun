import json

from django.test import TestCase
from django.urls import reverse

from ..models import GameRoom


class ViewTest(TestCase):
    def test_create_room(self):
        response = self.client.post(
            reverse('kim:api_create_room'),
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertIn('room_code', data)
        self.assertEqual(len(data['room_code']), 6)

    def test_join_room_success(self):
        create_response = self.client.post(
            reverse('kim:api_create_room'),
            data=json.dumps({}),
            content_type='application/json',
        )
        room_code = json.loads(create_response.content)['room_code']

        response = self.client.post(
            reverse('kim:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['room_status'], 'CHOOSING')
        self.assertIn('player_identifier', data)

    def test_join_room_not_found(self):
        response = self.client.post(
            reverse('kim:api_join_room'),
            data=json.dumps({'room_code': 'NOPE00'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(json.loads(response.content)['success'])

    def test_join_room_full(self):
        create_response = self.client.post(
            reverse('kim:api_create_room'),
            data=json.dumps({}),
            content_type='application/json',
        )
        room_code = json.loads(create_response.content)['room_code']

        self.client.post(
            reverse('kim:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json',
        )
        response = self.client.post(
            reverse('kim:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            reverse('kim:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('dolu', json.loads(response.content)['error'])

    def test_get_room_state(self):
        room = GameRoom.objects.create(room_code='STATE1', status='CHOOSING')
        response = self.client.get(reverse('kim:api_get_room_state', args=['STATE1']))
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['room_code'], 'STATE1')
        self.assertEqual(data['status'], 'CHOOSING')

    def test_game_room_page_renders_characters(self):
        GameRoom.objects.create(room_code='PAGE01', status='WAITING')
        response = self.client.get(reverse('kim:game_room', args=['PAGE01']))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'characters-data')
