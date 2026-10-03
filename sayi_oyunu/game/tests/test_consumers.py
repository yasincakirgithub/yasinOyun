from django.test import TestCase
from channels.testing import WebsocketCommunicator
from ..consumers import GameConsumer
from ..models import GameRoom, GamePlayer
import json


class GameConsumerTest(TestCase):
    async def test_connect_and_disconnect(self):
        """Test that a player can connect and disconnect."""
        # Create a room
        room = await GameRoom.objects.acreate(room_code='TEST12', status='WAITING')
        
        communicator = WebsocketCommunicator(
            GameConsumer.as_asgi(),
            f"/ws/game/{room.room_code}/"
        )
        connected, subprotocol = await communicator.connect()
        self.assertTrue(connected)
        
        # Send a join player message
        await communicator.send_json_to({
            'type': 'join_player',
            'player_identifier': 'test_player_123'
        })
        
        # Receive the player_joined message
        response = await communicator.receive_json_from()
        self.assertEqual(response['type'], 'player_joined')
        self.assertEqual(response['player_identifier'], 'test_player_123')
        
        await communicator.disconnect()
        self.assertTrue(True)  # If we got here without exception, pass

    async def test_full_game_flow(self):
        """Test a complete game flow via WebSocket."""
        # Create room
        room = await GameRoom.objects.acreate(room_code='GAME12', status='WAITING')
        
        # Two players connect
        p1 = WebsocketCommunicator(
            GameConsumer.as_asgi(),
            f"/ws/game/{room.room_code}/"
        )
        p2 = WebsocketCommunicator(
            GameConsumer.as_asgi(),
            f"/ws/game/{room.room_code}/"
        )
        
        # Connect both
        p1_connected, _ = await p1.connect()
        p2_connected, _ = await p2.connect()
        self.assertTrue(p1_connected)
        self.assertTrue(p2_connected)
        
        # Player 1 joins
        await p1.send_json_to({
            'type': 'join_player',
            'player_identifier': 'player1'
        })
        p1_response = await p1.receive_json_from()
        self.assertEqual(p1_response['type'], 'player_joined')
        p1_id = p1_response['player_id']
        
        # Player 2 joins
        await p2.send_json_to({
            'type': 'join_player',
            'player_identifier': 'player2'
        })
        p2_response = await p2.receive_json_from()
        self.assertEqual(p2_response['type'], 'player_joined')
        p2_id = p2_response['player_id']
        
        # Set secrets
        await p1.send_json_to({
            'type': 'set_secret',
            'player_identifier': 'player1',
            'secret_number': '1234'
        })
        p1_ready = await p1.receive_json_from()
        self.assertEqual(p1_ready['type'], 'player_ready')
        
        await p2.send_json_to({
            'type': 'set_secret',
            'player_identifier': 'player2',
            'secret_number': '5678'
        })
        p2_ready = await p2.receive_json_from()
        self.assertEqual(p2_ready['type'], 'player_ready')
        
        # Game should start
        # Either player could receive game_started
        p1_game_start = await p1.receive_json_from()
        p2_game_start = await p2.receive_json_from()
        # One of them should be game_started
        self.assertTrue(
            p1_game_start['type'] == 'game_started' or 
            p2_game_start['type'] == 'game_started'
        )
        
        # Determine whose turn it is (should be player 1 as first joiner)
        # For simplicity, we'll just test that we can make a guess
        # Make a guess from player 1
        await p1.send_json_to({
            'type': 'make_guess',
            'player_identifier': 'player1',
            'guess': '5678'  # guess player 2's number
        })
        # Player 1 should get guess_result
        p1_result = await p1.receive_json_from()
        self.assertEqual(p1_result['type'], 'guess_result')
        self.assertEqual(p1_result['guess'], '5678')
        # 5678 vs 5678 should be ++++
        self.assertEqual(p1_result['result'], '++++')
        self.assertTrue(p1_result['is_win'])
        
        # Clean up
        await p1.disconnect()
        await p2.disconnect()