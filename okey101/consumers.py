import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import services
from .models import MAX_PLAYERS, MIN_PLAYERS, GamePlayer, GameRoom, TableMeld

logger = logging.getLogger(__name__)


class GameConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_code = self.scope['url_route']['kwargs']['room_code'].upper()
        self.room_group_name = f'okey101_game_{self.room_code}'
        self.player_identifier = None

        await self.channel_layer.group_add(self.room_group_name, self.channel_name)
        await self.accept()
        logger.info('101 Okey WebSocket connected for room %s', self.room_code)
        await self.send_room_state()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.room_group_name, self.channel_name)
        if self.player_identifier:
            await self.mark_disconnected()
            await self.broadcast_state()
        logger.info('101 Okey WebSocket disconnected for room %s (%s)', self.room_code, close_code)

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except json.JSONDecodeError:
            await self.send_error('Geçersiz veri gönderildi.')
            return

        message_type = data.get('type')
        handlers = {
            'join_player': self.handle_join_player,
            'start_game': self.handle_start_game,
            'next_round': self.handle_next_round,
            'restart_game': self.handle_restart_game,
            'get_state': self.handle_get_state,
            'draw_stock': self.handle_draw_stock,
            'take_discard': self.handle_take_discard,
            'return_discard': self.handle_return_discard,
            'open_hand': self.handle_open_hand,
            'auto_open': self.handle_auto_open,
            'lay_melds': self.handle_lay_melds,
            'process_tile': self.handle_process_tile,
            'discard_tile': self.handle_discard_tile,
        }
        handler = handlers.get(message_type)
        if not handler:
            await self.send_error(f'Bilinmeyen mesaj tipi: {message_type}')
            return

        try:
            await handler(data)
        except Exception as exc:
            logger.exception('Error handling %s: %s', message_type, exc)
            await self.send_error(str(exc))

    def _identifier(self, data):
        return data.get('player_identifier') or self.player_identifier

    async def handle_join_player(self, data):
        identifier = self._identifier(data)
        if not identifier:
            await self.send_error('Oyuncu kimliği gerekli.')
            return

        name = (data.get('name') or '').strip()[:30]
        result = await self.get_or_create_player(identifier, name)
        if result.get('error'):
            await self.send_error(result['error'])
            return

        self.player_identifier = identifier
        await self.broadcast_state()

    async def handle_start_game(self, data):
        result = await self.start_round(self._identifier(data))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_next_round(self, data):
        result = await self.next_round(self._identifier(data))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_restart_game(self, data):
        result = await self.restart_game(self._identifier(data))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_get_state(self, data):
        await self.send_room_state()

    async def handle_draw_stock(self, data):
        result = await self.draw_stock(self._identifier(data))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_take_discard(self, data):
        result = await self.take_discard(self._identifier(data))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_return_discard(self, data):
        result = await self.return_discard(self._identifier(data))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_open_hand(self, data):
        result = await self.open_hand(self._identifier(data), data.get('melds'))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_auto_open(self, data):
        result = await self.auto_open(self._identifier(data))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_lay_melds(self, data):
        result = await self.lay_melds(self._identifier(data), data.get('melds'))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_process_tile(self, data):
        result = await self.process_tile(
            self._identifier(data), data.get('tile_id'), data.get('meld_id')
        )
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def handle_discard_tile(self, data):
        result = await self.discard_tile(self._identifier(data), data.get('tile_id'))
        if result.get('error'):
            await self.send_error(result['error'])
            return
        await self.broadcast_state()

    async def broadcast_state(self):
        await self.channel_layer.group_send(
            self.room_group_name,
            {'type': 'state_changed'},
        )

    async def state_changed(self, event):
        await self.send_room_state()

    async def send_error(self, message):
        await self.send(text_data=json.dumps({'type': 'error', 'message': message}))

    async def send_room_state(self):
        state = await self.build_room_state()
        if state is None:
            await self.send_error('Oda bulunamadı.')
            return
        await self.send(text_data=json.dumps(state))

    def _locked_room(self):
        return (
            GameRoom.objects.select_for_update()
            .filter(room_code=self.room_code)
            .first()
        )

    def _turn_validation(self, room, identifier):
        if not identifier:
            return None, 'Oyuncu kimliği gerekli.'
        player = room.players.filter(player_identifier=identifier).first()
        if not player:
            return None, 'Oyuncu bulunamadı.'
        if room.status != 'IN_PROGRESS':
            return None, 'Oyun şu anda oynanmıyor.'
        if room.current_seat != player.seat:
            return None, 'Sıra sende değil.'
        return player, None

    @database_sync_to_async
    def get_or_create_player(self, identifier, name):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}

            player = room.players.filter(player_identifier=identifier).first()
            if player:
                fields = ['connected']
                player.connected = True
                if name and player.name != name:
                    player.name = name
                    fields.append('name')
                player.save(update_fields=fields)
                return {'ok': True}

            if room.status != 'WAITING':
                return {'error': 'Bu oyun başladı, yeni oyuncu katılamaz.'}
            if GamePlayer.objects.filter(player_identifier=identifier).exists():
                return {'error': 'Bu oyuncu kimliği başka bir odada kullanılıyor.'}
            if room.players.count() >= MAX_PLAYERS:
                return {'error': 'Oda dolu.'}

            used_seats = set(room.players.values_list('seat', flat=True))
            seat = next((value for value in range(MAX_PLAYERS) if value not in used_seats), None)
            if seat is None:
                return {'error': 'Oda dolu.'}

            GamePlayer.objects.create(
                game_room=room,
                player_identifier=identifier,
                name=name,
                seat=seat,
                hand=[],
            )
            if not room.creator_identifier:
                GameRoom.objects.filter(
                    pk=room.pk,
                    creator_identifier='',
                ).update(creator_identifier=identifier)
            return {'ok': True}

    def _begin_round(self, room, players):
        seats = [player.seat for player in players]
        starter = seats[(room.round_number - 1) % len(seats)]
        hands, stock, indicator, okey = services.deal_round(seats, starter)

        room.stock = stock
        room.discard_pile = []
        room.indicator = indicator
        room.okey = okey
        room.current_seat = starter
        room.turn_has_drawn = True
        room.turn_taken_discard = False
        room.turn_taken_tile_id = ''
        room.turn_start_opened = False
        room.points_threshold = services.OPENING_POINTS
        room.pairs_threshold = services.OPENING_PAIRS
        room.status = 'IN_PROGRESS'
        room.winner = None
        room.finished_at = None
        if not room.started_at:
            room.started_at = timezone.now()
        room.save()

        room.melds.all().delete()
        for player in players:
            player.hand = hands[player.seat]
            player.opened = False
            player.route = ''
            player.round_score = 0
            player.penalty = 0
            player.save(update_fields=[
                'hand', 'opened', 'route', 'round_score', 'penalty',
            ])

    @database_sync_to_async
    def start_round(self, identifier):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            if not room.players.filter(player_identifier=identifier).exists():
                return {'error': 'Oyuncu bulunamadı.'}
            if room.status not in ('WAITING', 'ROUND_END'):
                return {'error': 'Oyun zaten başladı.'}

            players = list(room.players.order_by('seat'))
            if len(players) != MIN_PLAYERS:
                return {'error': f'Oyun {MIN_PLAYERS} oyuncuyla başlar.'}
            host_identifier = room.creator_identifier or players[0].player_identifier
            if identifier != host_identifier:
                return {'error': 'Oyunu sadece oda kurucusu başlatabilir.'}

            if room.status == 'ROUND_END':
                if room.round_number >= room.total_rounds:
                    return self._finish_game_locked(room, players)
                room.round_number += 1
            else:
                room.round_number = 1
                room.round_results = []
                if not room.started_at:
                    room.started_at = timezone.now()

            self._begin_round(room, players)
            return {'ok': True}

    @database_sync_to_async
    def next_round(self, identifier):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            if not room.players.filter(player_identifier=identifier).exists():
                return {'error': 'Oyuncu bulunamadı.'}

            players = list(room.players.order_by('seat'))
            if len(players) != MIN_PLAYERS:
                return {'error': f'Oyun {MIN_PLAYERS} oyuncuyla başlar.'}
            host_identifier = room.creator_identifier or players[0].player_identifier
            if identifier != host_identifier:
                return {'error': 'Sıradaki eli sadece oda kurucusu başlatabilir.'}

            if room.status == 'WAITING':
                room.round_number = 1
                room.round_results = []
                self._begin_round(room, players)
                return {'ok': True}
            if room.status != 'ROUND_END':
                return {'error': 'El henüz bitmedi.'}
            if room.round_number >= room.total_rounds:
                return self._finish_game_locked(room, players)

            room.round_number += 1
            self._begin_round(room, players)
            return {'ok': True}

    def _finish_game_locked(self, room, players):
        if room.mode == 'pairs':
            team_totals = {
                team: sum(
                    player.total_score
                    for player in players
                    if services.team_for_seat(player.seat) == team
                )
                for team in ('A', 'B')
            }
            winning_team = min(team_totals, key=lambda team: (team_totals[team], team))
            ranked = sorted(
                (
                    player for player in players
                    if services.team_for_seat(player.seat) == winning_team
                ),
                key=lambda player: (player.total_score, player.seat),
            )
        else:
            ranked = sorted(players, key=lambda player: (player.total_score, player.seat))
        room.status = 'FINISHED'
        room.winner = ranked[0] if ranked else None
        room.finished_at = timezone.now()
        room.current_seat = None
        room.turn_has_drawn = False
        room.turn_taken_discard = False
        room.turn_taken_tile_id = ''
        room.save()
        return {'ok': True}

    @database_sync_to_async
    def restart_game(self, identifier):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            if not room.players.filter(player_identifier=identifier).exists():
                return {'error': 'Oyuncu bulunamadı.'}

            players = list(room.players.order_by('seat'))
            host_identifier = room.creator_identifier or (
                players[0].player_identifier if players else ''
            )
            if identifier != host_identifier:
                return {'error': 'Oyunu sadece oda kurucusu yeniden başlatabilir.'}
            room.melds.all().delete()
            for player in players:
                player.hand = []
                player.opened = False
                player.route = ''
                player.total_score = 0
                player.round_score = 0
                player.penalty = 0
                player.save(update_fields=[
                    'hand', 'opened', 'route', 'total_score', 'round_score', 'penalty',
                ])

            room.round_number = 1
            room.round_results = []
            room.winner = None
            room.stock = []
            room.discard_pile = []
            room.indicator = None
            room.okey = None
            room.current_seat = None
            room.turn_has_drawn = False
            room.turn_taken_discard = False
            room.turn_taken_tile_id = ''
            room.turn_start_opened = False
            room.started_at = None
            room.finished_at = None

            if len(players) == MIN_PLAYERS:
                self._begin_round(room, players)
            else:
                room.status = 'WAITING'
                room.save()
            return {'ok': True}

    @database_sync_to_async
    def draw_stock(self, identifier):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            player, error = self._turn_validation(room, identifier)
            if error:
                return {'error': error}
            if room.turn_has_drawn:
                return {'error': 'Bu turda zaten taş çektin.'}

            if not room.stock:
                players = list(room.players.order_by('seat'))
                self._finish_round_locked(room, players, None, 1, 'stock_empty', {})
                return {'ok': True}

            tile = room.stock.pop()
            player.hand.append(tile)
            services.sort_hand(player.hand)
            player.save(update_fields=['hand'])
            room.turn_has_drawn = True
            room.turn_taken_discard = False
            room.turn_taken_tile_id = ''
            room.save(update_fields=[
                'stock', 'turn_has_drawn', 'turn_taken_discard', 'turn_taken_tile_id', 'updated_at',
            ])
            return {'ok': True}

    def _tile_extends_table(self, room, tile):
        for meld in room.melds.all():
            if services.can_extend_meld(meld.kind, meld.tiles, tile, room.okey):
                return True
        return False

    @database_sync_to_async
    def take_discard(self, identifier):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            player, error = self._turn_validation(room, identifier)
            if error:
                return {'error': error}
            if room.turn_has_drawn:
                return {'error': 'Bu turda zaten taş çektin.'}
            if not room.discard_pile:
                return {'error': 'Atılan taş yok.'}

            tile = room.discard_pile[-1]
            room.discard_pile = room.discard_pile[:-1]
            player.hand.append(tile)
            services.sort_hand(player.hand)
            player.save(update_fields=['hand'])
            room.turn_has_drawn = True
            room.turn_taken_discard = True
            room.turn_taken_tile_id = tile['id']
            room.save(update_fields=[
                'discard_pile', 'turn_has_drawn', 'turn_taken_discard',
                'turn_taken_tile_id', 'updated_at',
            ])
            return {'ok': True}

    @database_sync_to_async
    def return_discard(self, identifier):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            player, error = self._turn_validation(room, identifier)
            if error:
                return {'error': error}
            if not room.turn_has_drawn:
                return {'error': 'Geri koymak için önce taş çekmelisin.'}
            if not room.turn_taken_discard or not room.turn_taken_tile_id:
                return {'error': 'Geri koyulacak atılan taş yok.'}

            tile = next(
                (item for item in player.hand if item['id'] == room.turn_taken_tile_id),
                None,
            )
            if not tile:
                return {'error': 'Aldığın taş artık elinde değil.'}

            player.hand = [
                item for item in player.hand
                if item['id'] != room.turn_taken_tile_id
            ]
            player.save(update_fields=['hand'])
            room.discard_pile = list(room.discard_pile) + [tile]
            room.turn_has_drawn = False
            room.turn_taken_discard = False
            room.turn_taken_tile_id = ''
            room.save(update_fields=[
                'discard_pile', 'turn_has_drawn', 'turn_taken_discard',
                'turn_taken_tile_id', 'updated_at',
            ])
            return {'ok': True}

    def _commit_open(self, room, player, result):
        used = set()
        for evaluation in result['evaluations']:
            tiles = evaluation['ordered']
            TableMeld.objects.create(
                game_room=room,
                owner=player,
                kind=evaluation['kind'],
                tiles=tiles,
                score=evaluation['score'],
            )
            used.update(tile['id'] for tile in tiles)

        player.hand = [tile for tile in player.hand if tile['id'] not in used]
        player.opened = True
        player.route = result['route']
        player.save(update_fields=['hand', 'opened', 'route'])

        if result['route'] == 'points':
            room.points_threshold = max(room.points_threshold, result['total'] + 1)
        else:
            room.pairs_threshold = max(room.pairs_threshold, result['pairs'] + 1)
        room.save(update_fields=['points_threshold', 'pairs_threshold', 'updated_at'])

    @database_sync_to_async
    def open_hand(self, identifier, meld_groups):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            player, error = self._turn_validation(room, identifier)
            if error:
                return {'error': error}
            if not room.turn_has_drawn:
                return {'error': 'Önce taş çekmelisin.'}
            if player.opened:
                return {'error': 'Elini zaten açtın.'}

            tiles_by_id = {tile['id']: tile for tile in player.hand}
            result, error = services.validate_melds(
                tiles_by_id,
                meld_groups,
                room.okey,
                room.points_threshold,
                room.pairs_threshold,
            )
            if error:
                return {'error': error}

            used = {
                tile['id']
                for evaluation in result['evaluations']
                for tile in evaluation['ordered']
            }
            if len(used) >= len(player.hand):
                return {'error': 'Açılışta atacak en az bir taşın kalmalı.'}
            if room.turn_taken_tile_id and room.turn_taken_tile_id not in used:
                return {'error': 'Atılan taştan aldığın taşı açılışta kullanmalısın.'}

            self._commit_open(room, player, result)
            return {'ok': True}

    @database_sync_to_async
    def auto_open(self, identifier):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            player, error = self._turn_validation(room, identifier)
            if error:
                return {'error': error}
            if not room.turn_has_drawn:
                return {'error': 'Önce taş çekmelisin.'}
            if player.opened:
                return {'error': 'Elini zaten açtın.'}

            opening = services.best_opening(
                player.hand,
                room.okey,
                room.points_threshold,
                room.pairs_threshold,
                required_tile_id=room.turn_taken_tile_id or None,
            )
            if not opening:
                return {'error': 'Elin açılmaya uygun değil.'}

            tiles_by_id = {tile['id']: tile for tile in player.hand}
            result, error = services.validate_melds(
                tiles_by_id,
                opening['melds'],
                room.okey,
                room.points_threshold,
                room.pairs_threshold,
            )
            if error:
                return {'error': error}

            used = {
                tile['id']
                for evaluation in result['evaluations']
                for tile in evaluation['ordered']
            }
            if len(used) >= len(player.hand):
                return {'error': 'Açılışta atacak en az bir taşın kalmalı.'}
            if room.turn_taken_tile_id and room.turn_taken_tile_id not in used:
                return {'error': 'Atılan taştan aldığın taşı açılışta kullanmalısın.'}

            self._commit_open(room, player, result)
            return {'ok': True}

    @database_sync_to_async
    def lay_melds(self, identifier, meld_groups):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            player, error = self._turn_validation(room, identifier)
            if error:
                return {'error': error}
            if not room.turn_has_drawn:
                return {'error': 'Önce taş çekmelisin.'}
            if not player.opened:
                return {'error': 'Önce elini açmalısın.'}
            if not isinstance(meld_groups, list) or not meld_groups:
                return {'error': 'En az bir per seçmelisin.'}

            tiles_by_id = {tile['id']: tile for tile in player.hand}
            used = set()
            evaluations = []
            pairs_available = room.players.filter(opened=True, route='pairs').exists()
            for group in meld_groups:
                if not isinstance(group, list) or len(group) < 2:
                    return {'error': 'Per en az iki taştan oluşmalı.'}
                if any(tile_id not in tiles_by_id for tile_id in group):
                    return {'error': 'Perde elinde olmayan bir taş var.'}
                if used & set(group):
                    return {'error': 'Aynı taş birden fazla perde kullanılamaz.'}
                evaluation = services.evaluate_meld(
                    [tiles_by_id[tile_id] for tile_id in group], room.okey
                )
                if not evaluation:
                    return {'error': 'Seçilen taşlar geçerli bir per oluşturmuyor.'}
                if player.route == 'pairs' and evaluation['kind'] != 'pair':
                    return {'error': 'Çiftle açan oyuncu sadece çift koyabilir.'}
                if evaluation['kind'] == 'pair' and player.route == 'points':
                    if not pairs_available:
                        return {'error': 'Çift açan bir oyuncu yokken puan rotasında çift koyamazsın.'}
                used.update(group)
                evaluations.append(evaluation)

            if len(used) >= len(player.hand):
                return {'error': 'Atacak en az bir taşın kalmalı.'}

            for evaluation in evaluations:
                TableMeld.objects.create(
                    game_room=room,
                    owner=player,
                    kind=evaluation['kind'],
                    tiles=evaluation['ordered'],
                    score=evaluation['score'],
                )
            player.hand = [tile for tile in player.hand if tile['id'] not in used]
            player.save(update_fields=['hand'])
            return {'ok': True}

    @database_sync_to_async
    def process_tile(self, identifier, tile_id, meld_id):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            player, error = self._turn_validation(room, identifier)
            if error:
                return {'error': error}
            if not room.turn_has_drawn:
                return {'error': 'Önce taş çekmelisin.'}
            if not player.opened:
                return {'error': 'İşlemek için önce elini açmalısın.'}
            if player.route == 'pairs':
                return {'error': 'Çiftle açan oyuncu seri/grup işleyemez.'}

            tile = next((item for item in player.hand if item['id'] == tile_id), None)
            if not tile:
                return {'error': 'Taş elinde değil.'}

            try:
                meld = room.melds.filter(id=meld_id).first()
            except (TypeError, ValidationError, ValueError):
                return {'error': 'Per bulunamadı.'}
            if not meld:
                return {'error': 'Per bulunamadı.'}
            if meld.kind == 'pair':
                return {'error': 'Çiftlere taş işlenemez.'}

            evaluation = services.can_extend_meld(meld.kind, meld.tiles, tile, room.okey)
            if not evaluation:
                return {'error': 'Bu taş bu pere eklenemiyor.'}

            meld.tiles = evaluation['ordered']
            meld.score = evaluation['score']
            meld.save(update_fields=['tiles', 'score'])
            player.hand = [item for item in player.hand if item['id'] != tile_id]
            player.save(update_fields=['hand'])
            return {'ok': True}

    @database_sync_to_async
    def discard_tile(self, identifier, tile_id):
        with transaction.atomic():
            room = self._locked_room()
            if not room:
                return {'error': 'Oda bulunamadı.'}
            player, error = self._turn_validation(room, identifier)
            if error:
                return {'error': error}
            if not room.turn_has_drawn:
                return {'error': 'Önce taş çekmelisin.'}

            tile = next((item for item in player.hand if item['id'] == tile_id), None)
            if not tile:
                return {'error': 'Taş elinde değil.'}

            if room.turn_taken_tile_id:
                if any(item['id'] == room.turn_taken_tile_id for item in player.hand):
                    return {'error': 'Atılan taştan aldığın taşı kullanmadan atamazsın.'}

            remaining_after = [item for item in player.hand if item['id'] != tile_id]
            finish = not remaining_after

            penalty = 0
            if room.penalties_enabled and not finish:
                if services.is_wild(tile, room.okey) or self._tile_extends_table(room, tile):
                    penalty = services.WILD_HAND_VALUE
                    player.penalty += penalty

            player.hand = remaining_after
            player.save(update_fields=['hand', 'penalty'])
            room.discard_pile = list(room.discard_pile) + [tile]

            if finish:
                elden = not room.turn_start_opened
                okey_discard = bool(services.is_wild(tile, room.okey))
                pairs_finish = player.route == 'pairs'
                multiplier = services.round_multiplier(
                    elden=elden,
                    okey_discard=okey_discard,
                    pairs_finish=pairs_finish,
                )
                if not room.multipliers_enabled:
                    multiplier = 1
                players = list(room.players.order_by('seat'))
                self._finish_round_locked(
                    room,
                    players,
                    player.seat,
                    multiplier,
                    'finish',
                    {
                        'elden': elden,
                        'okey_discard': okey_discard,
                        'pairs_finish': pairs_finish,
                        'last_tile': tile,
                    },
                )
                return {'ok': True}

            players = list(room.players.order_by('seat'))
            seats = [item.seat for item in players]
            room.current_seat = services.next_seat(seats, player.seat)
            room.turn_has_drawn = False
            room.turn_taken_discard = False
            room.turn_taken_tile_id = ''
            next_player = next(
                (item for item in players if item.seat == room.current_seat),
                None,
            )
            room.turn_start_opened = bool(next_player and next_player.opened)

            if not room.stock:
                self._finish_round_locked(room, players, None, 1, 'stock_empty', {})
                return {'ok': True}

            room.save()
            return {'ok': True}

    def _finish_round_locked(self, room, players, winner_seat, multiplier, reason, details):
        players_data = [
            {
                'seat': player.seat,
                'name': player.name,
                'opened': player.opened,
                'route': player.route,
                'hand': player.hand,
                'okey': room.okey,
                'penalty': player.penalty,
            }
            for player in players
        ]
        if not room.multipliers_enabled:
            multiplier = 1
        scores = services.score_round(
            players_data,
            winner_seat,
            multiplier,
            {
                'penalties_enabled': room.penalties_enabled,
                'multipliers_enabled': room.multipliers_enabled,
            },
        )
        team_totals = {}
        if room.mode == 'pairs':
            team_totals = {
                team: sum(
                    entry['score']
                    for entry in scores
                    if services.team_for_seat(entry['seat']) == team
                )
                for team in ('A', 'B')
            }
        by_seat = {player.seat: player for player in players}
        for entry in scores:
            player = by_seat.get(entry['seat'])
            if not player:
                continue
            player.round_score = entry['score']
            player.total_score += entry['score']
            player.save(update_fields=['round_score', 'total_score'])

        winner = by_seat.get(winner_seat) if winner_seat is not None else None
        results = list(room.round_results or [])
        results.append({
            'round': room.round_number,
            'reason': reason,
            'winner_seat': winner_seat,
            'winner_name': winner.name if winner else '',
            'multiplier': multiplier,
            'penalties_enabled': room.penalties_enabled,
            'multipliers_enabled': room.multipliers_enabled,
            'team_totals': team_totals,
            'elden': bool(details.get('elden')),
            'okey_discard': bool(details.get('okey_discard')),
            'pairs_finish': bool(details.get('pairs_finish')),
            'last_tile': details.get('last_tile'),
            'scores': scores,
        })

        room.status = 'ROUND_END'
        room.round_results = results
        room.winner = winner
        room.current_seat = None
        room.turn_has_drawn = False
        room.turn_taken_discard = False
        room.turn_taken_tile_id = ''
        room.save()

    @database_sync_to_async
    def mark_disconnected(self):
        GamePlayer.objects.filter(
            game_room__room_code=self.room_code,
            player_identifier=self.player_identifier,
        ).update(connected=False)

    @database_sync_to_async
    def build_room_state(self):
        room = (
            GameRoom.objects.select_related('winner')
            .prefetch_related('players', 'melds__owner')
            .filter(room_code=self.room_code)
            .first()
        )
        if not room:
            return None

        players = sorted(room.players.all(), key=lambda player: player.seat)
        identifier = self.player_identifier
        me = next((player for player in players if player.player_identifier == identifier), None)
        host_identifier = room.creator_identifier or (
            players[0].player_identifier if players else ''
        )
        is_host = bool(me and me.player_identifier == host_identifier)
        reveal_hands = room.status in ('ROUND_END', 'FINISHED')
        melds = list(room.melds.all())

        last_result = (room.round_results or [])[-1] if room.round_results else None

        return {
            'type': 'game_state',
            'room_code': room.room_code,
            'status': room.status,
            'mode': room.mode,
            'penalties_enabled': room.penalties_enabled,
            'multipliers_enabled': room.multipliers_enabled,
            'round_number': room.round_number,
            'total_rounds': room.total_rounds,
            'points_threshold': room.points_threshold,
            'pairs_threshold': room.pairs_threshold,
            'current_seat': room.current_seat,
            'current_identifier': (
                next(
                    (player.player_identifier for player in players if player.seat == room.current_seat),
                    None,
                )
            ),
            'turn_has_drawn': room.turn_has_drawn,
            'turn_taken_discard': room.turn_taken_discard,
            'turn_taken_tile_id': room.turn_taken_tile_id,
            'turn_start_opened': room.turn_start_opened,
            'stock_count': len(room.stock or []),
            'discard_count': len(room.discard_pile or []),
            'last_discard': (room.discard_pile or [None])[-1],
            'indicator': room.indicator,
            'okey': room.okey,
            'me': (
                {
                    'player_identifier': me.player_identifier,
                    'name': me.name,
                    'seat': me.seat,
                    'hand': me.hand,
                    'hand_value': services.hand_value(me.hand, room.okey),
                    'opened': me.opened,
                    'route': me.route,
                    'team': services.team_for_seat(me.seat) if room.mode == 'pairs' else None,
                    'total_score': me.total_score,
                    'round_score': me.round_score,
                    'penalty': me.penalty,
                }
                if me else None
            ),
            'players': [
                {
                    'player_identifier': player.player_identifier,
                    'name': player.name,
                    'seat': player.seat,
                    'opened': player.opened,
                    'route': player.route,
                    'team': services.team_for_seat(player.seat) if room.mode == 'pairs' else None,
                    'tile_count': len(player.hand or []),
                    'hand': list(player.hand or []) if reveal_hands else None,
                    'total_score': player.total_score,
                    'round_score': player.round_score,
                    'penalty': player.penalty,
                    'connected': player.connected,
                    'is_me': player.player_identifier == identifier,
                    'is_host': player.player_identifier == host_identifier,
                }
                for player in players
            ],
            'melds': [
                {
                    'id': str(meld.id),
                    'kind': meld.kind,
                    'tiles': meld.tiles,
                    'score': meld.score,
                    'owner_identifier': meld.owner.player_identifier,
                    'owner_name': meld.owner.name,
                    'owner_seat': meld.owner.seat,
                }
                for meld in melds
            ],
            'winner_identifier': room.winner.player_identifier if room.winner else None,
            'winner_name': room.winner.name if room.winner else '',
            'winner_team': (
                services.team_for_seat(room.winner.seat)
                if room.winner and room.mode == 'pairs'
                else None
            ),
            'team_totals': (
                {
                    team: sum(
                        player.total_score
                        for player in players
                        if services.team_for_seat(player.seat) == team
                    )
                    for team in ('A', 'B')
                }
                if room.mode == 'pairs'
                else {}
            ),
            'round_results': room.round_results,
            'last_result': last_result,
            'can_start': (
                room.status == 'WAITING'
                and len(players) == MIN_PLAYERS
                and is_host
            ),
            'is_host': is_host,
            'host_identifier': host_identifier,
            'min_players': MIN_PLAYERS,
            'max_players': MAX_PLAYERS,
            'server_time': timezone.now().isoformat(),
        }
