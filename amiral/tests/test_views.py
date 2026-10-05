import json

from django.test import TestCase
from django.urls import reverse

from ..models import GameRoom


class ViewTest(TestCase):
    def test_home(self):
        response = self.client.get(reverse('amiral:home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Amiral Battı')

    def test_create_room(self):
        response = self.client.post(
            reverse('amiral:api_create_room'),
            data=json.dumps({}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(len(data['room_code']), 6)

    def test_join_room_success(self):
        create = self.client.post(
            reverse('amiral:api_create_room'),
            data=json.dumps({}),
            content_type='application/json',
        )
        room_code = json.loads(create.content)['room_code']

        response = self.client.post(
            reverse('amiral:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['room_status'], 'PLACING')

    def test_join_room_not_found(self):
        response = self.client.post(
            reverse('amiral:api_join_room'),
            data=json.dumps({'room_code': 'YOK123'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(json.loads(response.content)['success'])

    def test_join_room_full(self):
        create = self.client.post(reverse('amiral:api_create_room'))
        room_code = json.loads(create.content)['room_code']

        for _ in range(2):
            self.client.post(
                reverse('amiral:api_join_room'),
                data=json.dumps({'room_code': room_code}),
                content_type='application/json',
            )

        response = self.client.post(
            reverse('amiral:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('Oda dolu', json.loads(response.content)['error'])

    def test_game_room_renders(self):
        room = GameRoom.objects.create(room_code='ROOM12', status='WAITING')
        response = self.client.get(reverse('amiral:game_room', args=[room.room_code]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ROOM12')
        self.assertContains(response, 'placement-grid')
