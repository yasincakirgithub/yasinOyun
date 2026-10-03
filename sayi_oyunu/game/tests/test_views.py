from django.test import TestCase
from django.urls import reverse
import json
from ..models import GameRoom, GamePlayer


class ViewTest(TestCase):
    def test_create_room(self):
        response = self.client.post(
            reverse('game:api_create_room'),
            data=json.dumps({}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertIn('room_code', data)
        self.assertEqual(len(data['room_code']), 6)  # default length

    def test_join_room_success(self):
        # First create a room
        create_response = self.client.post(
            reverse('game:api_create_room'),
            data=json.dumps({}),
            content_type='application/json'
        )
        create_data = json.loads(create_response.content)
        room_code = create_data['room_code']
        
        # Now join it
        response = self.client.post(
            reverse('game:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['room_status'], 'SETTING_NUMBERS')  # First player made it WAITING, second makes it SETTING_NUMBERS

    def test_join_room_not_found(self):
        response = self.client.post(
            reverse('game:api_join_room'),
            data=json.dumps({'room_code': 'INVALID'}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 404)
        data = json.loads(response.content)
        self.assertFalse(data['success'])

    def test_join_room_full(self):
        # Create room
        create_response = self.client.post(
            reverse('game:api_create_room'),
            data=json.dumps({}),
            content_type='application/json'
        )
        create_data = json.loads(create_response.content)
        room_code = create_data['room_code']
        
        # First player joins
        self.client.post(
            reverse('game:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json'
        )
        # Second player joins
        response = self.client.post(
            reverse('game:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['room_status'], 'SETTING_NUMBERS')
        
        # Third player tries to join - should fail
        response = self.client.post(
            reverse('game:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)  # Bad request
        data = json.loads(response.content)
        self.assertFalse(data['success'])
        self.assertIn('Room is full', data['error'])

    def test_set_secret(self):
        # Create room and join as player
        create_response = self.client.post(
            reverse('game:api_create_room'),
            data=json.dumps({}),
            content_type='application/json'
        )
        create_data = json.loads(create_response.content)
        room_code = create_data['room_code']
        
        join_response = self.client.post(
            reverse('game:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json'
        )
        join_data = json.loads(join_response.content)
        player_id = join_data['player_id']
        
        # Set secret
        response = self.client.post(
            reverse('game:api_set_secret'),
            data=json.dumps({
                'player_id': player_id,
                'secret_number': '1234'
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        self.assertEqual(data['room_status'], 'SETTING_NUMBERS')  # Still waiting for second player
        
        # Try invalid secret
        response = self.client.post(
            reverse('game:api_set_secret'),
            data=json.dumps({
                'player_id': player_id,
                'secret_number': '0123'  # leading zero
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        data = json.loads(response.content)
        self.assertFalse(data['success'])

    def test_make_guess(self):
        # Setup: create room, two players join, set secrets
        create_response = self.client.post(
            reverse('game:api_create_room'),
            data=json.dumps({}),
            content_type='application/json'
        )
        create_data = json.loads(create_response.content)
        room_code = create_data['room_code']
        
        # Player 1 joins
        p1_join = self.client.post(
            reverse('game:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json'
        )
        p1_data = json.loads(p1_join.content)
        p1_id = p1_data['player_id']
        
        # Player 2 joins
        p2_join = self.client.post(
            reverse('game:api_join_room'),
            data=json.dumps({'room_code': room_code}),
            content_type='application/json'
        )
        p2_data = json.loads(p2_join.content)
        p2_id = p2_data['player_id']
        
        # Set secrets
        self.client.post(
            reverse('game:api_set_secret'),
            data=json.dumps({
                'player_id': p1_id,
                'secret_number': '1234'
            }),
            content_type='application/json'
        )
        self.client.post(
            reverse('game:api_set_secret'),
            data=json.dumps({
                'player_id': p2_id,
                'secret_number': '5678'
            }),
            content_type='application/json'
        )
        
        # Now player 1 makes a guess (should be their turn if they are player 1)
        response = self.client.post(
            reverse('game:api_make_guess'),
            data=json.dumps({
                'player_id': p1_id,
                'guess': '5678'  # guess opponent's number
            }),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertTrue(data['success'])
        # Guess 5678 vs secret 5678 should be ++++
        self.assertEqual(data['result'], '++++')
        self.assertTrue(data['is_win'])