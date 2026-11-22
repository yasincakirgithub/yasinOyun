"""WebSocket tests for the Character Auction consumer."""

from __future__ import annotations

from channels.testing import WebsocketCommunicator
from django.test import TransactionTestCase

from config.asgi import application

from .helpers import started_room


async def receive_type(communicator, wanted, timeout=2, predicate=None):
    """Read messages until one with ``type == wanted`` (and predicate) arrives."""
    while True:
        message = await communicator.receive_json_from(timeout=timeout)
        if message.get("type") == wanted and (predicate is None or predicate(message)):
            return message


async def receive_state(communicator, predicate=None, timeout=2):
    return await receive_type(communicator, "state", timeout, predicate)


class AuctionWebSocketTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.room, players = started_room(
            character_ids=["marvel_iron_man", "marvel_thor"]
        )
        self.host_token = players[0][1]
        self.guest_token = players[1][1]
        self.host_id = str(players[0][0].pk)
        self.guest_id = str(players[1][0].pk)

    async def connect(self, room_code):
        communicator = WebsocketCommunicator(
            application, f"/ws/auction/room/{room_code}/"
        )
        communicator.scope["headers"] = [
            (b"origin", b"http://testserver"),
            (b"host", b"testserver"),
        ]
        connected, _ = await communicator.connect()
        return communicator, connected

    async def test_authentication_and_bid_broadcast(self):
        communicator, connected = await self.connect(self.room.room_code)
        self.assertTrue(connected)
        try:
            self.assertEqual(
                (await communicator.receive_json_from())["type"], "auth_required"
            )

            await communicator.send_json_to(
                {
                    "type": "authenticate",
                    "session_token": self.guest_token,
                }
            )
            auth_ok = await receive_type(communicator, "auth_ok")
            self.assertEqual(auth_ok["player_id"], self.guest_id)

            state = await receive_state(communicator)
            self.assertEqual(state["me"]["id"], self.guest_id)
            self.assertEqual(state["room"]["status"], "AUCTION")

            await communicator.send_json_to({"type": "bid", "amount": 150})
            state = await receive_state(
                communicator,
                predicate=lambda message: (
                    message["current_auction"]["current_bid"] == 150
                ),
            )
            self.assertEqual(state["current_auction"]["current_bid"], 150)
            self.assertEqual(
                state["current_auction"]["current_bidder"]["id"], self.guest_id
            )
        finally:
            await communicator.disconnect()

    async def test_get_state_requires_authentication(self):
        communicator, connected = await self.connect(self.room.room_code)
        self.assertTrue(connected)
        try:
            await communicator.receive_json_from()  # auth_required

            await communicator.send_json_to({"type": "get_state"})
            error = await communicator.receive_json_from()
            self.assertEqual(error["type"], "error")
            self.assertEqual(error["code"], "auth_required")

            await communicator.send_json_to(
                {
                    "type": "authenticate",
                    "session_token": "definitely-not-valid",
                }
            )
            error = await communicator.receive_json_from()
            self.assertEqual(error["type"], "error")
            self.assertEqual(error["code"], "auth_failed")
        finally:
            await communicator.disconnect()

    async def test_invalid_bid_returns_error_without_changing_state(self):
        communicator, connected = await self.connect(self.room.room_code)
        self.assertTrue(connected)
        try:
            await communicator.receive_json_from()
            await communicator.send_json_to(
                {
                    "type": "authenticate",
                    "session_token": self.host_token,
                }
            )
            await receive_type(communicator, "auth_ok")
            await receive_type(communicator, "state")

            await communicator.send_json_to({"type": "bid", "amount": 100})
            error = await receive_type(communicator, "error")
            self.assertEqual(error["code"], "bid_too_low")

            await communicator.send_json_to({"type": "get_state"})
            state = await receive_type(communicator, "state")
            self.assertEqual(state["current_auction"]["current_bid"], 100)
            self.assertIsNone(state["current_auction"]["current_bidder"])
        finally:
            await communicator.disconnect()
