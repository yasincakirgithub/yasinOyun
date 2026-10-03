from django.test import TestCase
from channels.testing import WebsocketCommunicator
from ..consumers import GameConsumer
from ..models import GameRoom, GamePlayer
import json


class AcceptanceTest(TestCase):
    """Test the exact scenario from the acceptance test.
    
    Note: The acceptance test as stated in the requirements contains a typo:
    It says Browser B's secret is 5678, but for the expected results to match,
    Browser B's secret should be 7521 (or similar) such that:
    - Browser A (secret 1234) guessing 5723 gives --+
    - Browser B (secret 7521) guessing 1234 gives ++++
    
    We will use Browser B's secret as 7521 to make the test pass,
    while noting that the acceptance test description likely had a typo.
    """
    
    async def test_acceptance_scenario(self):
        """Browser A: Create Room, Room: ABC12, Secret: 1234
           Browser B: Join Room ABC12, Secret: 7521 (corrected from 5678)
           Browser A: Guess: 5723 -> Result: --+
           Browser B: Guess: 1234 -> Result: ++++
           Browser B wins.
        """
        # Browser A creates room
        room = await GameRoom.objects.acreate(room_code='ABC12', status='WAITING')
        
        # Browser A connects to WebSocket
        ws_a = WebsocketCommunicator(
            GameConsumer.as_asgi(),
            f"/ws/game/{room.room_code}/"
        )
        # Browser B connects to WebSocket
        ws_b = WebsocketCommunicator(
            GameConsumer.as_asgi(),
            f"/ws/game/{room.room_code}/"
        )
        
        # Connect both
        connected_a, _ = await ws_a.connect()
        connected_b, _ = await ws_b.connect()
        self.assertTrue(connected_a)
        self.assertTrue(connected_b)
        
        # Browser A joins as player
        await ws_a.send_json_to({
            'type': 'join_player',
            'player_identifier': 'browser_a'
        })
        response_a = await ws_a.receive_json_from()
        self.assertEqual(response_a['type'], 'player_joined')
        player_a_id = response_a['player_id']
        player_a_identifier = 'browser_a'
        
        # Browser B joins as player
        await ws_b.send_json_to({
            'type': 'join_player',
            'player_identifier': 'browser_b'
        })
        response_b = await ws_b.receive_json_from()
        self.assertEqual(response_b['type'], 'player_joined')
        player_b_id = response_b['player_id']
        player_b_identifier = 'browser_b'
        
        # Browser A sets secret number 1234
        await ws_a.send_json_to({
            'type': 'set_secret',
            'player_identifier': 'browser_a',
            'secret_number': '1234'
        })
        ready_a = await ws_a.receive_json_from()
        self.assertEqual(ready_a['type'], 'player_ready')
        
        # Browser B sets secret number 7521 (corrected from 5678 to make test pass)
        await ws_b.send_json_to({
            'type': 'set_secret',
            'player_identifier': 'browser_b',
            'secret_number': '7521'
        })
        ready_b = await ws_b.receive_json_from()
        self.assertEqual(ready_b['type'], 'player_ready')
        
        # Game should start; determine whose turn it is
        # Since Browser A (first joiner) should start
        # Wait for game_started message on either connection
        start_a = await ws_a.receive_json_from()
        start_b = await ws_b.receive_json_from()
        
        # One of them should be game_started
        is_start_a = start_a['type'] == 'game_started'
        is_start_b = start_b['type'] == 'game_started'
        self.assertTrue(is_start_a or is_start_b)
        
        # Get the current turn from the game_started message
        if is_start_a:
            current_turn = start_a['current_turn_identifier']
        else:
            current_turn = start_b['current_turn_identifier']
        
        # Should be Browser A's turn (first joiner)
        self.assertEqual(current_turn, 'browser_a')
        
        # Browser A guesses 5723 (against Browser B's secret 7521)
        # Expected result: --+  (as per acceptance test)
        await ws_a.send_json_to({
            'type': 'make_guess',
            'player_identifier': 'browser_a',
            'guess': '5723'
        })
        # Browser A should get guess_result
        p1_result = await ws_a.receive_json_from()
        self.assertEqual(p1_result['type'], 'guess_result')
        self.assertEqual(p1_result['guess'], '5723')
        self.assertEqual(p1_result['result'], '--+')
        self.assertFalse(p1_result['is_win'])  # Not a win yet
        
        # Browser B should get opponent_guessed notification
        p2_notif = await ws_b.receive_json_from()
        self.assertEqual(p2_notif['type'], 'opponent_guessed')
        self.assertEqual(p2_notif['guess'], '5723')
        self.assertEqual(p2_notif['result'], '--+')
        
        # Now it's Browser B's turn
        # Browser B guesses 1234 (against Browser A's secret 1234)
        # Expected result: ++++
        await ws_b.send_json_to({
            'type': 'make_guess',
            'player_identifier': 'browser_b',
            'guess': '1234'
        })
        # Browser B should get guess_result
        p2_result = await ws_b.receive_json_from()
        self.assertEqual(p2_result['type'], 'guess_result')
        self.assertEqual(p2_result['guess'], '1234')
        self.assertEqual(p2_result['result'], '++++')
        self.assertTrue(p2_result['is_win'])  # Browser B wins!
        
        # Browser A should get opponent_guessed notification
        p1_notif = await ws_a.receive_json_from()
        self.assertEqual(p1_notif['type'], 'opponent_guessed')
        self.assertEqual(p1_notif['guess'], '1234')
        self.assertEqual(p1_notif['result'], '++++')
        
        # Game should be finished
        # Either player could receive game_finished
        finish_a = await ws_a.receive_json_from()
        finish_b = await ws_b.receive_json_from()
        self.assertTrue(
            finish_a['type'] == 'game_finished' or 
            finish_b['type'] == 'game_finished'
        )
        # The winner should be Browser B
        if finish_a['type'] == 'game_finished':
            self.assertEqual(finish_a['winner_identifier'], 'browser_b')
        else:
            self.assertEqual(finish_b['winner_identifier'], 'browser_b')
        
        # Clean up
        await ws_a.disconnect()
        await ws_b.disconnect()