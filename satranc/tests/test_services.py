import chess
from django.test import TestCase

from .. import services


class ServicesTest(TestCase):
    def test_legal_moves_at_start(self):
        self.assertEqual(len(services.legal_moves(chess.STARTING_FEN)), 20)

    def test_turn_color(self):
        self.assertEqual(services.turn_color(chess.STARTING_FEN), 'w')

    def test_apply_move(self):
        result = services.apply_move(chess.STARTING_FEN, 'e2e4')
        self.assertNotIn('error', result)
        self.assertEqual(result['san'], 'e4')
        self.assertEqual(result['turn'], 'b')
        self.assertFalse(result['game_over'])
        self.assertFalse(result['check'])

    def test_illegal_move(self):
        result = services.apply_move(chess.STARTING_FEN, 'e2e5')
        self.assertIn('error', result)

    def test_invalid_format(self):
        result = services.apply_move(chess.STARTING_FEN, 'zzzz')
        self.assertIn('error', result)

    def test_checkmate_detection(self):
        fen = chess.STARTING_FEN
        for uci in ['f2f3', 'e7e5', 'g2g4', 'd8h4']:
            result = services.apply_move(fen, uci)
            self.assertNotIn('error', result)
            fen = result['fen']

        self.assertTrue(result['game_over'])
        self.assertEqual(result['result'], '0-1')
        self.assertEqual(result['winner_color'], 'b')
        self.assertEqual(result['termination'], 'CHECKMATE')
        self.assertTrue(result['check'])

    def test_promotion(self):
        fen = '7k/P7/8/8/8/8/8/K7 w - - 0 1'
        result = services.apply_move(fen, 'a7a8q')
        self.assertNotIn('error', result)
        self.assertIn('a8=Q', result['san'])
