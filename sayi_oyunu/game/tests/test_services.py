from django.test import TestCase
from ..services import calculate_result, is_win, switch_turn
from ..models import GameRoom, GamePlayer


class CalculateResultTest(TestCase):
    def test_examples_from_requirements(self):
        """Test the exact examples provided in the requirements."""
        # secret=1234, guess=1234 -> result=++++
        self.assertEqual(calculate_result('1234', '1234'), '++++')
        # secret=1234, guess=4321 -> result=----
        self.assertEqual(calculate_result('1234', '4321'), '----')
        # secret=1234, guess=1325 -> result=+--
        self.assertEqual(calculate_result('1234', '1325'), '+--')
        # secret=1234, guess=5678 -> result=
        self.assertEqual(calculate_result('1234', '5678'), '')
        # secret=1234, guess=1243 -> result=++--
        self.assertEqual(calculate_result('1234', '1243'), '++--')

    def test_additional_cases(self):
        # Test skipping digits not in secret
        self.assertEqual(calculate_result('1234', '5678'), '')
        self.assertEqual(calculate_result('1234', '5623'), '--')  # 2 and 3 in secret, wrong pos
        self.assertEqual(calculate_result('1234', '2563'), '--')  # same
        # secret=1,2,3,4; guess=2,3,5,6
        # pos0: 2 vs 1 -> not match, but 2 in secret at pos1 -> -
        # pos1: 3 vs 2 -> not match, but 3 in secret at pos2 -> -
        # pos2: 5 not in secret -> skip
        # pos3: 6 not in secret -> skip
        # result: '--'
        self.assertEqual(calculate_result('1234', '2356'), '--')
        
        # Test with leading zero not allowed (but validation catches this)
        # We're testing the logic assuming valid input
        self.assertEqual(calculate_result('1023', '1023'), '++++')
        self.assertEqual(calculate_result('1023', '0123'), '--++')  # Let's verify:
        # secret=1,0,2,3; guess=0,1,2,3
        # pos0: 0 vs 1 -> not match, but 0 in secret at pos1 -> -
        # pos1: 1 vs 0 -> not match, but 1 in secret at pos0 -> -
        # pos2: 2 vs 2 -> match -> +
        # pos3: 3 vs 3 -> match -> +
        # result: '--++'
        self.assertEqual(calculate_result('1023', '0123'), '--++')
        
        # Test order of symbols matches guess order
        self.assertEqual(calculate_result('1234', '4321'), '----')  # all wrong pos
        self.assertEqual(calculate_result('1234', '1243'), '++--')  # first two correct, last two wrong pos


class IsWinTest(TestCase):
    def test_is_win(self):
        self.assertTrue(is_win('++++'))
        self.assertFalse(is_win('+++'))
        self.assertFalse(is_win('++--'))
        self.assertFalse(is_win(''))
        self.assertFalse(is_win('----'))
        
        # Win only when all four are +
        self.assertTrue(is_win('++++'))
        self.assertFalse(is_win('++-+'))  # This would be three + and one -, but our result string only shows + and - for digits in secret
        # Actually, if result is '++-+', that means four symbols: +,+,-,+ 
        # which would mean all four guessed digits are in secret, with three correct pos and one wrong pos
        # So not a win
        self.assertFalse(is_win('++-+'))


class SwitchTurnTest(TestCase):
    def test_switch_turn(self):
        room = GameRoom.objects.create(room_code='TEST12', status='WAITING')
        p1 = GamePlayer.objects.create(
            game_room=room,
            player_identifier='p1',
            secret_number='1234',
            ready=True,
            turn_order=1
        )
        p2 = GamePlayer.objects.create(
            game_room=room,
            player_identifier='p2',
            secret_number='5678',
            ready=True,
            turn_order=2
        )
        players = [p1, p2]
        self.assertEqual(switch_turn(p1, players), p2)
        self.assertEqual(switch_turn(p2, players), p1)