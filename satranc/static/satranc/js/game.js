// Satranç - WebSocket, tahta çizimi ve sürükle-bırak yönetimi

const FILES = 'abcdefgh';
const COLOR_NAMES = { w: 'Beyaz', b: 'Siyah' };

function pieceSvg(color, type) {
    const set = window.CHESS_PIECES || {};
    return (set[color] && set[color][type]) || '';
}

class ChessGame {
    constructor() {
        this.roomCode = null;
        this.playerIdentifier = null;
        this.ws = null;

        this.fen = null;
        this.turn = 'w';
        this.legalMoves = [];
        this.moves = [];
        this.status = 'WAITING';
        this.result = null;
        this.winnerColor = null;
        this.winnerIdentifier = null;
        this.players = [];
        this.check = false;
        this.myColor = null;

        this.selected = null;
        this.pendingPromotion = null;
        this.lastMove = null;
        this.drag = null;
        this.hoverSquare = null;
        this.gameOverDismissed = false;

        this.board = document.getElementById('board');
        this.rankLabels = document.getElementById('rank-labels');
        this.fileLabels = document.getElementById('file-labels');
        this.turnIndicator = document.getElementById('turn-indicator');
        this.checkIndicator = document.getElementById('check-indicator');
        this.moveList = document.getElementById('move-list');
        this.selfBar = document.getElementById('self-bar');
        this.opponentBar = document.getElementById('opponent-bar');
        this.selfName = document.getElementById('self-name');
        this.selfStatus = document.getElementById('self-status');
        this.opponentName = document.getElementById('opponent-name');
        this.opponentStatus = document.getElementById('opponent-status');
        this.copyRoomBtn = document.getElementById('copy-room-btn');
        this.playAgainBtn = document.getElementById('play-again-btn');
        this.rematchBtn = document.getElementById('rematch-btn');
        this.closeGameOverBtn = document.getElementById('close-game-over');
        this.promotionModal = document.getElementById('promotion');
        this.promotionButtons = document.querySelectorAll('.promotion-choices button');
        this.gameOverModal = document.getElementById('game-over');
        this.gameOverMessage = document.getElementById('game-over-message');
        this.gameOverDetail = document.getElementById('game-over-detail');
        this.toastEl = document.getElementById('toast');
        this.commentaryEl = document.getElementById('commentary');

        this.toastTimer = null;
        this.sounds = {};
        this.audioUnlocked = false;
        this.commentaryCtx = null;
        this.commentarySampleRate = 24000;
        this.nextCommentaryTime = 0;
        this.commentaryTimer = null;
        this.initAudio();
        this.bindEvents();
    }

    // ------------------------------------------------------------------
    // Ses
    // ------------------------------------------------------------------
    initAudio() {
        const sources = {
            move: document.body.dataset.audioMove,
            capture: document.body.dataset.audioCapture,
            check: document.body.dataset.audioCheck,
            rook: document.body.dataset.audioRook,
        };
        Object.entries(sources).forEach(([key, src]) => {
            if (!src) return;
            const audio = new Audio(src);
            audio.preload = 'auto';
            audio.volume = 0.7;
            this.sounds[key] = audio;
        });

        const unlock = () => {
            if (this.audioUnlocked) return;
            this.audioUnlocked = true;
            document.removeEventListener('pointerdown', unlock);
            document.removeEventListener('keydown', unlock);
        };
        document.addEventListener('pointerdown', unlock);
        document.addEventListener('keydown', unlock);
    }

    playMoveSound(move) {
        let key = 'move';
        const san = (move && move.san) || '';
        if (san.startsWith('O-O')) {
            key = 'rook';
        } else if (san.includes('x')) {
            key = 'capture';
        }
        if (this.check) {
            key = 'check';
        }

        const sound = this.sounds[key] || this.sounds.move;
        if (!sound) return;
        try {
            sound.currentTime = 0;
            const playPromise = sound.play();
            if (playPromise && typeof playPromise.catch === 'function') {
                playPromise.catch(() => {});
            }
        } catch (err) {
            console.warn('Hamle sesi çalınamadı', err);
        }
    }

    // ------------------------------------------------------------------
    // Sesli AI yorumu (WebSocket binary PCM akışı)
    // ------------------------------------------------------------------
    onCommentary(data) {
        this.commentarySampleRate = data.sample_rate || 24000;
        this.nextCommentaryTime = 0;
        this.showCommentary(data.text);
        if (this.commentaryEl) {
            this.commentaryEl.classList.add('speaking');
        }
    }

    onCommentaryEnd() {
        if (this.commentaryEl) {
            this.commentaryEl.classList.remove('speaking');
        }
    }

    showCommentary(text) {
        if (!this.commentaryEl || !text) return;
        this.commentaryEl.textContent = text;
        this.commentaryEl.classList.remove('hidden');
        if (this.commentaryTimer) {
            clearTimeout(this.commentaryTimer);
        }
        this.commentaryTimer = setTimeout(() => {
            this.commentaryEl.classList.add('hidden');
        }, 6000);
    }

    playCommentaryChunk(arrayBuffer) {
        const ctx = this.ensureCommentaryContext();
        if (!ctx) return;

        const view = new DataView(arrayBuffer);
        const samples = Math.floor(view.byteLength / 2);
        if (samples <= 0) return;

        const buffer = ctx.createBuffer(1, samples, this.commentarySampleRate);
        const channel = buffer.getChannelData(0);
        for (let i = 0; i < samples; i += 1) {
            channel[i] = view.getInt16(i * 2, true) / 32768;
        }

        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);

        const now = ctx.currentTime;
        if (this.nextCommentaryTime < now) {
            this.nextCommentaryTime = now;
        }
        source.start(this.nextCommentaryTime);
        this.nextCommentaryTime += buffer.duration;
    }

    ensureCommentaryContext() {
        if (!this.commentaryCtx) {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (!Ctx) return null;
            this.commentaryCtx = new Ctx();
        }
        if (this.commentaryCtx.state === 'suspended') {
            this.commentaryCtx.resume().catch(() => {});
        }
        return this.commentaryCtx;
    }

    bindEvents() {
        if (this.copyRoomBtn) {
            this.copyRoomBtn.addEventListener('click', () => this.copyRoomCode());
        }
        this.playAgainBtn.addEventListener('click', () => this.restartGame());
        if (this.rematchBtn) {
            this.rematchBtn.addEventListener('click', () => this.restartGame());
        }
        if (this.closeGameOverBtn) {
            this.closeGameOverBtn.addEventListener('click', () => this.closeGameOver());
        }
        this.gameOverModal.addEventListener('click', (event) => {
            if (event.target === this.gameOverModal) {
                this.closeGameOver();
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') {
                this.closeGameOver();
                this.closePromotion();
            }
        });
        this.promotionModal.addEventListener('click', (event) => {
            if (event.target === this.promotionModal) {
                this.closePromotion();
            }
        });
        this.promotionButtons.forEach((btn) => {
            btn.addEventListener('click', () => this.completePromotion(btn.dataset.piece));
        });

        this.board.addEventListener('pointerdown', (event) => this.onPointerDown(event));
        window.addEventListener('pointermove', (event) => this.onPointerMove(event));
        window.addEventListener('pointerup', (event) => this.onPointerUp(event));
        window.addEventListener('pointercancel', () => this.cancelDrag());
    }

    // ------------------------------------------------------------------
    // Bağlantı
    // ------------------------------------------------------------------
    connectToRoom(roomCode) {
        this.roomCode = roomCode.toUpperCase();
        const storageKey = `satranc:player:${this.roomCode}`;
        this.playerIdentifier = sessionStorage.getItem(storageKey)
            || `guest_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
        sessionStorage.setItem(storageKey, this.playerIdentifier);
        this.playerName = sessionStorage.getItem('satranc:playerName') || 'Oyuncu';

        const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${wsScheme}://${window.location.host}/satranc/ws/game/${this.roomCode}/`;

        this.ws = new WebSocket(wsUrl);
        this.ws.binaryType = 'arraybuffer';

        this.ws.onopen = () => {
            this.ws.send(JSON.stringify({
                type: 'join_player',
                player_identifier: this.playerIdentifier,
                name: this.playerName,
            }));
        };

        this.ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                this.playCommentaryChunk(event.data);
                return;
            }
            let data;
            try {
                data = JSON.parse(event.data);
            } catch (err) {
                console.error('Geçersiz mesaj', err);
                return;
            }
            this.handleMessage(data);
        };

        this.ws.onclose = () => {
            this.updateOpponentStatus('Bağlantı koptu');
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket hatası:', error);
        };
    }

    send(payload) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(payload));
        }
    }

    handleMessage(data) {
        switch (data.type) {
            case 'game_state':
                this.applyState(data);
                break;
            case 'player_joined':
                if (data.player_identifier !== this.playerIdentifier) {
                    this.showToast('Rakip bağlandı.');
                }
                break;
            case 'game_abandoned':
                this.showToast(data.message, true);
                this.updateOpponentStatus(data.message);
                break;
            case 'commentary':
                this.onCommentary(data);
                break;
            case 'commentary_end':
                this.onCommentaryEnd();
                break;
            case 'error':
                this.showToast(data.message, true);
                break;
            default:
                console.log('Bilinmeyen mesaj tipi:', data.type);
        }
    }

    // ------------------------------------------------------------------
    // Durum
    // ------------------------------------------------------------------
    applyState(data) {
        const previousMoveCount = this.moves.length;

        this.fen = data.fen;
        this.turn = data.turn;
        this.legalMoves = data.legal_moves || [];
        this.moves = data.moves || [];
        this.status = data.status;
        this.result = data.result;
        this.winnerColor = data.winner_color;
        this.winnerIdentifier = data.winner_identifier;
        this.players = data.players || [];
        this.check = data.check;
        this.lastMove = this.moves.length ? this.moves[this.moves.length - 1].uci : null;

        this.myColor = this.resolveMyColor();

        if (this.moves.length > previousMoveCount) {
            const latestMove = this.moves[this.moves.length - 1];
            this.playMoveSound(latestMove);
            this.announceMove(latestMove);
        }

        this.selected = null;
        this.render();
    }

    resolveMyColor() {
        const me = this.players.find((p) => p.player_identifier === this.playerIdentifier);
        return me ? me.color : null;
    }

    announceMove(move) {
        if (move.color === this.myColor) {
            return;
        }
        this.showToast(`Rakip oynadı: ${move.san}`);
    }

    // ------------------------------------------------------------------
    // Çizim
    // ------------------------------------------------------------------
    render() {
        this.renderBoard();
        this.renderLabels();
        this.renderMoveList();
        this.renderPlayers();
        this.renderTurn();
        this.renderGameOver();
    }

    orientationColor() {
        return this.myColor === 'b' ? 'b' : 'w';
    }

    squareOrder() {
        const squares = [];
        const ranks = this.orientationColor() === 'w'
            ? [8, 7, 6, 5, 4, 3, 2, 1]
            : [1, 2, 3, 4, 5, 6, 7, 8];
        const files = this.orientationColor() === 'w'
            ? FILES.split('')
            : FILES.split('').reverse();

        ranks.forEach((rank) => {
            files.forEach((file) => squares.push(`${file}${rank}`));
        });
        return squares;
    }

    pieceMap() {
        const map = {};
        if (!this.fen) return map;
        const placement = this.fen.split(' ')[0];
        const rows = placement.split('/');
        rows.forEach((row, rowIndex) => {
            const rank = 8 - rowIndex;
            let fileIndex = 0;
            for (const ch of row) {
                if (/\d/.test(ch)) {
                    fileIndex += Number(ch);
                    continue;
                }
                const square = `${FILES[fileIndex]}${rank}`;
                map[square] = {
                    type: ch.toLowerCase(),
                    color: ch === ch.toUpperCase() ? 'w' : 'b',
                };
                fileIndex += 1;
            }
        });
        return map;
    }

    renderLabels() {
        if (!this.rankLabels || !this.fileLabels) return;
        const order = this.squareOrder();

        this.rankLabels.innerHTML = '';
        for (let row = 0; row < 8; row += 1) {
            const span = document.createElement('span');
            span.textContent = order[row * 8][1];
            this.rankLabels.appendChild(span);
        }

        this.fileLabels.innerHTML = '';
        for (let col = 0; col < 8; col += 1) {
            const span = document.createElement('span');
            span.textContent = order[56 + col][0];
            this.fileLabels.appendChild(span);
        }
    }

    renderBoard() {
        if (!this.board) return;

        const pieces = this.pieceMap();
        const order = this.squareOrder();
        const targets = this.targetSquares();
        const checkSquare = this.check ? this.kingSquare(this.turn) : null;
        const lastMoveSquares = this.lastMoveSquares();
        const interactive = this.isMyTurn();

        this.board.innerHTML = '';
        this.board.classList.toggle('locked', !interactive);

        order.forEach((square) => {
            const file = FILES.indexOf(square[0]);
            const rank = Number(square[1]);
            const isLight = (file + rank) % 2 === 1;

            const cell = document.createElement('div');
            cell.className = `square ${isLight ? 'light' : 'dark'}`;
            cell.dataset.square = square;

            if (lastMoveSquares.has(square)) cell.classList.add('last-move');
            if (square === checkSquare) cell.classList.add('in-check');
            if (square === this.selected) cell.classList.add('selected');
            if (square === this.hoverSquare) cell.classList.add('drop-hover');
            if (this.drag && square === this.drag.from) cell.classList.add('dragging-source');

            const target = targets.get(square);
            if (target) {
                cell.classList.add('target');
                if (target.capture) cell.classList.add('capture');
            }

            const piece = pieces[square];
            if (piece) {
                const span = document.createElement('span');
                span.className = `piece ${piece.color === 'w' ? 'white' : 'black'}`;
                span.innerHTML = pieceSvg(piece.color, piece.type);
                cell.appendChild(span);
            }

            this.board.appendChild(cell);
        });
    }

    renderMoveList() {
        if (!this.moveList) return;
        this.moveList.innerHTML = '';

        for (let i = 0; i < this.moves.length; i += 2) {
            const li = document.createElement('li');
            const number = document.createElement('span');
            number.className = 'move-no';
            number.textContent = `${i / 2 + 1}.`;
            li.appendChild(number);

            const white = document.createElement('span');
            white.className = 'san';
            white.textContent = this.moves[i] ? this.moves[i].san : '';
            li.appendChild(white);

            const black = document.createElement('span');
            black.className = 'san';
            black.textContent = this.moves[i + 1] ? this.moves[i + 1].san : '';
            li.appendChild(black);

            this.moveList.appendChild(li);
        }
        this.moveList.scrollTop = this.moveList.scrollHeight;
    }

    renderPlayers() {
        const me = this.players.find((p) => p.player_identifier === this.playerIdentifier);
        const opponent = this.players.find((p) => p.player_identifier !== this.playerIdentifier);

        if (this.myColor) {
            const myName = (me && me.name) || this.playerName || 'SEN';
            this.selfName.textContent = `${myName} (${COLOR_NAMES[this.myColor]})`;
        } else {
            this.selfName.textContent = 'İZLEYİCİ';
        }

        if (opponent) {
            const oppName = opponent.name || 'RAKİP';
            this.opponentName.textContent = `${oppName} (${COLOR_NAMES[opponent.color]})`;
            this.updateOpponentStatus('Bağlandı');
        } else {
            this.opponentName.textContent = 'RAKİP';
            this.updateOpponentStatus('Bekleniyor...');
        }

        this.selfBar.classList.toggle('active', this.isMyTurn() && this.status === 'IN_PROGRESS');
        this.opponentBar.classList.toggle(
            'active',
            this.status === 'IN_PROGRESS' && this.turn !== this.myColor
        );
    }

    renderTurn() {
        if (this.status === 'WAITING') {
            this.setTurnIndicator('waiting', 'Rakip bekleniyor...');
        } else if (this.status === 'IN_PROGRESS') {
            if (this.isMyTurn()) {
                this.setTurnIndicator('your-turn', 'SIRA SENDE');
            } else {
                this.setTurnIndicator('opponent-turn', 'RAKİBİN SIRASI');
            }
        } else if (this.status === 'FINISHED') {
            const text = this.result === '1/2-1/2'
                ? 'BERABERE'
                : (this.winnerColor === this.myColor ? 'KAZANDIN' : 'KAYBETTİN');
            this.setTurnIndicator('', text);
        } else {
            this.setTurnIndicator('waiting', 'Oyun bitti');
        }

        if (this.checkIndicator) {
            this.checkIndicator.classList.toggle(
                'hidden',
                !(this.check && this.status === 'IN_PROGRESS')
            );
        }
    }

    renderGameOver() {
        if (this.status !== 'FINISHED') {
            this.gameOverDismissed = false;
            this.gameOverModal.classList.add('hidden');
            this.playAgainBtn.classList.add('hidden');
            return;
        }

        if (this.gameOverDismissed) {
            this.gameOverModal.classList.add('hidden');
            this.playAgainBtn.classList.remove('hidden');
            return;
        }

        let message;
        let cls;
        if (this.result === '1/2-1/2') {
            message = 'BERABERE';
            cls = 'draw';
        } else if (this.winnerColor === this.myColor) {
            message = 'KAZANDIN!';
            cls = 'win';
        } else {
            message = 'KAYBETTİN!';
            cls = 'lose';
        }

        this.gameOverMessage.textContent = message;
        this.gameOverMessage.className = cls;

        let detail = 'Sonuç: ' + (this.result || '-');
        if (this.check) {
            detail = 'Mat!';
        } else if (this.result === '1/2-1/2') {
            detail = 'Oyun berabere bitti.';
        }
        this.gameOverDetail.textContent = detail;

        this.gameOverModal.classList.remove('hidden');
        this.playAgainBtn.classList.remove('hidden');
    }

    setTurnIndicator(type, text) {
        this.turnIndicator.className = `turn-indicator ${type}`.trim();
        this.turnIndicator.textContent = text;
    }

    updateOpponentStatus(text) {
        this.opponentStatus.textContent = text;
    }

    // ------------------------------------------------------------------
    // Hamle seçimi / sürükle-bırak
    // ------------------------------------------------------------------
    isMyTurn() {
        return this.status === 'IN_PROGRESS'
            && this.myColor !== null
            && this.turn === this.myColor;
    }

    kingSquare(color) {
        const pieces = this.pieceMap();
        for (const [square, piece] of Object.entries(pieces)) {
            if (piece.type === 'k' && piece.color === color) {
                return square;
            }
        }
        return null;
    }

    lastMoveSquares() {
        const set = new Set();
        if (!this.lastMove || this.lastMove.length < 4) return set;
        set.add(this.lastMove.slice(0, 2));
        set.add(this.lastMove.slice(2, 4));
        return set;
    }

    targetSquares() {
        const targets = new Map();
        if (!this.selected) return targets;

        const pieces = this.pieceMap();
        this.legalMoves
            .filter((uci) => uci.slice(0, 2) === this.selected)
            .forEach((uci) => {
                const to = uci.slice(2, 4);
                const capture = Boolean(pieces[to]);
                const existing = targets.get(to);
                targets.set(to, { capture: capture || (existing && existing.capture) });
            });
        return targets;
    }

    squareFromPoint(x, y) {
        const el = document.elementFromPoint(x, y);
        const cell = el && el.closest ? el.closest('.square') : null;
        return cell ? cell.dataset.square : null;
    }

    onPointerDown(event) {
        if (!this.isMyTurn() || !this.promotionModal.classList.contains('hidden')) {
            if (this.status === 'IN_PROGRESS' && !this.isMyTurn()) {
                this.showToast('Sıra sende değil.', true);
            }
            return;
        }

        const cell = event.target.closest('.square');
        if (!cell) return;
        event.preventDefault();

        const square = cell.dataset.square;
        const pieces = this.pieceMap();
        const piece = pieces[square];

        if (this.selected) {
            const targets = this.targetSquares();
            if (targets.has(square) && (!piece || piece.color !== this.myColor)) {
                this.tryMove(this.selected, square);
                return;
            }
        }

        if (piece && piece.color === this.myColor) {
            if (this.selected === square) {
                this.selected = null;
                this.renderBoard();
                return;
            }
            this.selected = square;
            this.renderBoard();
            this.startDrag(square, event);
            return;
        }

        this.selected = null;
        this.renderBoard();
    }

    startDrag(square, event) {
        const piece = this.pieceMap()[square];
        if (!piece) return;

        const cell = this.board.querySelector(`.square[data-square="${square}"]`);
        if (!cell) return;
        const rect = cell.getBoundingClientRect();

        const ghost = document.createElement('div');
        ghost.className = 'drag-piece';
        ghost.style.width = `${rect.width}px`;
        ghost.style.height = `${rect.height}px`;
        ghost.style.left = `${event.clientX}px`;
        ghost.style.top = `${event.clientY}px`;
        ghost.innerHTML = pieceSvg(piece.color, piece.type);
        document.body.appendChild(ghost);
        cell.classList.add('dragging-source');

        this.drag = { from: square, el: ghost };
    }

    onPointerMove(event) {
        if (!this.drag) return;

        this.drag.el.style.left = `${event.clientX}px`;
        this.drag.el.style.top = `${event.clientY}px`;

        const square = this.squareFromPoint(event.clientX, event.clientY);
        if (square !== this.hoverSquare) {
            this.hoverSquare = square;
            this.renderBoard();
        }
    }

    onPointerUp(event) {
        if (!this.drag) return;

        const from = this.drag.from;
        const square = this.squareFromPoint(event.clientX, event.clientY);
        const isTarget = square && square !== from && this.targetSquares().has(square);

        this.cleanupDrag();

        if (isTarget) {
            this.tryMove(from, square);
        } else {
            this.renderBoard();
        }
    }

    cancelDrag() {
        if (!this.drag) return;
        this.cleanupDrag();
        this.renderBoard();
    }

    cleanupDrag() {
        if (this.drag && this.drag.el && this.drag.el.parentNode) {
            this.drag.el.parentNode.removeChild(this.drag.el);
        }
        this.drag = null;
        this.hoverSquare = null;
    }

    tryMove(from, to) {
        const candidates = this.legalMoves.filter(
            (uci) => uci.slice(0, 2) === from && uci.slice(2, 4) === to
        );
        if (candidates.length === 0) {
            this.selected = null;
            this.renderBoard();
            return;
        }

        const promotions = candidates.filter((uci) => uci.length === 5);
        if (promotions.length > 0) {
            this.pendingPromotion = { from, to };
            const color = this.myColor || 'w';
            this.promotionButtons.forEach((btn) => {
                btn.innerHTML = pieceSvg(color, btn.dataset.piece);
            });
            this.promotionModal.classList.remove('hidden');
            return;
        }

        this.send({
            type: 'move',
            player_identifier: this.playerIdentifier,
            uci: candidates[0],
        });
        this.selected = null;
        this.renderBoard();
    }

    completePromotion(piece) {
        if (!this.pendingPromotion) return;
        const { from, to } = this.pendingPromotion;
        this.pendingPromotion = null;
        this.promotionModal.classList.add('hidden');
        this.send({
            type: 'move',
            player_identifier: this.playerIdentifier,
            uci: `${from}${to}${piece}`,
        });
        this.selected = null;
        this.renderBoard();
    }

    restartGame() {
        this.send({
            type: 'restart_game',
            player_identifier: this.playerIdentifier,
        });
    }

    closeGameOver() {
        if (this.status !== 'FINISHED') return;
        this.gameOverDismissed = true;
        this.gameOverModal.classList.add('hidden');
        this.playAgainBtn.classList.remove('hidden');
    }

    closePromotion() {
        if (!this.pendingPromotion) return;
        this.pendingPromotion = null;
        this.promotionModal.classList.add('hidden');
        this.renderBoard();
    }

    // ------------------------------------------------------------------
    // Yardımcılar
    // ------------------------------------------------------------------
    copyRoomCode() {
        const code = this.roomCode;
        const done = () => this.showToast('Oda kodu kopyalandı.');
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(code).then(done).catch(() => this.showToast(code));
        } else {
            this.showToast(code);
        }
    }

    showToast(message, isError) {
        if (!this.toastEl) return;
        this.toastEl.textContent = message;
        this.toastEl.classList.toggle('error', !!isError);
        this.toastEl.classList.remove('hidden');
        if (this.toastTimer) {
            clearTimeout(this.toastTimer);
        }
        this.toastTimer = setTimeout(() => {
            this.toastEl.classList.add('hidden');
        }, 2600);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const game = new ChessGame();
    window.game = game;

    const roomCode = document.body.dataset.roomCode;
    if (roomCode) {
        game.connectToRoom(roomCode);
    }
});
