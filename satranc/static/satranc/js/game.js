// Satranç - WebSocket, tahta çizimi ve sürükle-bırak yönetimi

const FILES = 'abcdefgh';
const COLOR_NAMES = { w: 'Beyaz', b: 'Siyah' };
const CLASSIFICATION_LABELS = {
    best: 'En iyi',
    excellent: 'Mükemmel',
    good: 'İyi',
    inaccuracy: 'Yanlışlık',
    mistake: 'Hata',
    blunder: 'Vahim hata',
    unknown: 'Bilinmiyor',
};

const TERMINATION_LABELS = {
    checkmate: 'Mat',
    stalemate: 'Pat',
    insufficient: 'Yetersiz materyal',
    repetition: 'Üç tekrar',
    fifty: '50 hamle kuralı',
    timeout: 'Süre bitti',
    resign: 'Pes etti',
    agreement: 'Anlaşma',
    abandon: 'Terk edildi',
};

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
        this.initialFen = 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1';
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
        this.isBotGame = false;
        this.botColor = null;

        // null => canlı (en son pozisyon), 0..moves.length => o ply'deki pozisyon.
        this.viewIndex = null;
        this.review = null;
        this.reviewLoading = false;
        this.reviewRequestId = 0;

        // Saat (clock) durumu.
        this.timeControl = 0;
        this.increment = 0;
        this.clock = { w: 0, b: 0 };
        this.turnStartedAt = null;
        this.serverOffsetMs = 0;
        this.flagSent = false;

        // Bekleyen beraberlik teklifi ve oyunun bitiş nedeni.
        this.drawOfferBy = null;
        this.termination = null;

        // Ön hamle (premove): {from, to, promotion} veya null.
        this.premove = null;

        // Sunucu onayını beklemeden anında gösterilen (iyimser) hamle.
        this.optimisticFen = null;
        this.optimisticMove = null;
        this.optimisticUci = null;

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
        this.reviewBtn = document.getElementById('review-btn');
        this.reviewPanel = document.getElementById('review-panel');
        this.reviewLoadingEl = document.getElementById('review-loading');
        this.reviewSummaryEl = document.getElementById('review-summary');
        this.reviewDetailEl = document.getElementById('review-detail');
        this.navFirst = document.getElementById('nav-first');
        this.navPrev = document.getElementById('nav-prev');
        this.navNext = document.getElementById('nav-next');
        this.navLast = document.getElementById('nav-last');
        this.navPosition = document.getElementById('nav-position');
        this.opponentClock = document.getElementById('opponent-clock');
        this.selfClock = document.getElementById('self-clock');
        this.premoveIndicator = document.getElementById('premove-indicator');

        this.gameActions = document.getElementById('game-actions');
        this.drawBtn = document.getElementById('draw-btn');
        this.resignBtn = document.getElementById('resign-btn');
        this.drawOfferModal = document.getElementById('draw-offer');
        this.drawOfferText = document.getElementById('draw-offer-text');
        this.drawAcceptBtn = document.getElementById('draw-accept-btn');
        this.drawDeclineBtn = document.getElementById('draw-decline-btn');
        this.evalBar = document.getElementById('eval-bar');
        this.evalBarFill = document.getElementById('eval-bar-fill');
        this.evalBarText = document.getElementById('eval-bar-text');

        this.toastTimer = null;
        this.sounds = {};
        this.audioUnlocked = false;
        this.initAudio();
        this.bindEvents();
        this.clockTimer = setInterval(() => this.tickClock(), 100);
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
        if (this.reviewBtn) {
            this.reviewBtn.addEventListener('click', () => this.toggleReview());
        }
        if (this.navFirst) {
            this.navFirst.addEventListener('click', () => this.goToIndex(0));
            this.navPrev.addEventListener('click', () => this.stepHistory(-1));
            this.navNext.addEventListener('click', () => this.stepHistory(1));
            this.navLast.addEventListener('click', () => this.goLive());
        }
        if (this.moveList) {
            this.moveList.addEventListener('click', (event) => {
                const item = event.target.closest('[data-ply]');
                if (item) {
                    this.goToIndex(Number(item.dataset.ply));
                }
            });
        }
        document.addEventListener('keydown', (event) => this.onHistoryKeydown(event));
        this.promotionModal.addEventListener('click', (event) => {
            if (event.target === this.promotionModal) {
                this.closePromotion();
            }
        });
        this.promotionButtons.forEach((btn) => {
            btn.addEventListener('click', () => this.completePromotion(btn.dataset.piece));
        });

        if (this.resignBtn) {
            this.resignBtn.addEventListener('click', () => this.resignGame());
        }
        if (this.drawBtn) {
            this.drawBtn.addEventListener('click', () => this.offerDraw());
        }
        if (this.drawAcceptBtn) {
            this.drawAcceptBtn.addEventListener('click', () => this.respondDraw(true));
        }
        if (this.drawDeclineBtn) {
            this.drawDeclineBtn.addEventListener('click', () => this.respondDraw(false));
        }
        if (this.drawOfferModal) {
            this.drawOfferModal.addEventListener('click', (event) => {
                if (event.target === this.drawOfferModal) {
                    this.respondDraw(false);
                }
            });
        }

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
        this.playerName = sessionStorage.getItem('satranc:playerName') || '';

        const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${wsScheme}://${window.location.host}/satranc/ws/game/${this.roomCode}/`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.ws.send(JSON.stringify({
                type: 'join_player',
                player_identifier: this.playerIdentifier,
                name: this.playerName,
            }));
        };

        this.ws.onmessage = (event) => {
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
            this.clearOptimistic();
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
            case 'draw_offered':
                if (data.by === this.playerIdentifier) {
                    this.showToast('Beraberlik teklifi gönderildi.');
                } else if (this.myColor !== null) {
                    this.showDrawOffer();
                }
                break;
            case 'draw_declined':
                if (data.by !== this.playerIdentifier) {
                    this.showToast('Beraberlik teklifi reddedildi.', true);
                } else {
                    this.showToast('Beraberlik teklifini reddettin.');
                }
                break;
            case 'error':
                if (this.optimisticUci) {
                    // Reddedilen iyimser hamleyi geri al ve durumu tazele.
                    this.clearOptimistic();
                    this.send({ type: 'get_state', player_identifier: this.playerIdentifier });
                    this.render();
                }
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
        const wasLive = this.viewIndex === null;

        this.fen = data.fen;
        if (data.initial_fen) {
            this.initialFen = data.initial_fen;
        }
        this.turn = data.turn;
        this.legalMoves = data.legal_moves || [];
        this.moves = data.moves || [];
        this.status = data.status;
        this.result = data.result;
        this.winnerColor = data.winner_color;
        this.winnerIdentifier = data.winner_identifier;
        this.players = data.players || [];
        this.check = data.check;
        this.isBotGame = !!data.is_bot_game;
        this.botColor = data.bot_color || null;

        this.timeControl = data.time_control || 0;
        this.increment = data.increment || 0;
        this.clock.w = data.white_time_left || 0;
        this.clock.b = data.black_time_left || 0;
        this.drawOfferBy = data.draw_offer_by || null;
        this.termination = data.termination || null;
        if (data.server_time) {
            this.serverOffsetMs = Date.now() - Date.parse(data.server_time);
        }
        this.turnStartedAt = data.turn_started_at ? Date.parse(data.turn_started_at) : null;
        this.flagSent = false;

        this.myColor = this.resolveMyColor();

        if (this.moves.length > previousMoveCount) {
            const latestMove = this.moves[this.moves.length - 1];
            const isMyOptimistic = Boolean(this.optimisticUci)
                && latestMove
                && latestMove.uci === this.optimisticUci
                && latestMove.color === this.myColor;
            if (wasLive && !isMyOptimistic) {
                this.playMoveSound(latestMove);
                this.announceMove(latestMove);
            }
            if (!wasLive) {
                // Geçmişte gezinirken yeni hamle geldi: konum korunur.
                this.viewIndex = Math.min(this.viewIndex, this.moves.length);
            }
            if (this.review) {
                // Yeni hamle incelemeyi geçersiz kılar.
                this.review = null;
                this.reviewPanel.classList.add('hidden');
                this.reviewBtn.textContent = 'OYUN İNCELEMESİ';
            }
        }

        if (this.viewIndex !== null) {
            this.viewIndex = Math.min(this.viewIndex, this.moves.length);
        }

        if (this.status !== 'IN_PROGRESS') {
            this.premove = null;
            this.drawOfferBy = null;
        }

        this.clearOptimistic();
        this.selected = null;
        this.render();
        this.maybePlayPremove();
    }

    clearOptimistic() {
        this.optimisticFen = null;
        this.optimisticMove = null;
        this.optimisticUci = null;
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
        this.renderClocks();
        this.renderPremoveIndicator();
        this.renderGameActions();
        this.renderGameOver();
        this.renderNavigation();
        this.renderReview();
        this.renderEvalBar();
    }

    // ------------------------------------------------------------------
    // Oyun kontrolleri (pes / beraberlik teklifi)
    // ------------------------------------------------------------------
    renderGameActions() {
        if (!this.gameActions) return;
        const active = this.status === 'IN_PROGRESS' && this.myColor !== null;
        const canOffer = active && !this.isBotGame;
        const offerMine = this.drawOfferBy && this.drawOfferBy === this.playerIdentifier;

        if (this.resignBtn) {
            this.resignBtn.classList.toggle('hidden', !active);
            this.resignBtn.disabled = !active;
        }
        if (this.drawBtn) {
            this.drawBtn.classList.toggle('hidden', !canOffer);
            this.drawBtn.disabled = !canOffer || offerMine || Boolean(this.drawOfferBy);
            this.drawBtn.textContent = offerMine ? 'TEKLİF GÖNDERİLDİ' : 'BERABERLİK';
        }

        const showOffer = Boolean(this.drawOfferBy)
            && this.drawOfferBy !== this.playerIdentifier
            && this.myColor !== null
            && this.status === 'IN_PROGRESS';
        if (this.drawOfferModal) {
            this.drawOfferModal.classList.toggle('hidden', !showOffer);
        }
    }

    showDrawOffer() {
        if (this.drawOfferModal) {
            this.drawOfferModal.classList.remove('hidden');
        }
    }

    resignGame() {
        if (this.status !== 'IN_PROGRESS' || this.myColor === null) return;
        const ok = window.confirm('Pes etmek istediğine emin misin?');
        if (!ok) return;
        this.send({ type: 'resign', player_identifier: this.playerIdentifier });
    }

    offerDraw() {
        if (this.status !== 'IN_PROGRESS' || this.isBotGame) return;
        this.send({ type: 'draw_offer', player_identifier: this.playerIdentifier });
    }

    respondDraw(accept) {
        if (this.drawOfferModal) {
            this.drawOfferModal.classList.add('hidden');
        }
        this.send({
            type: accept ? 'draw_accept' : 'draw_decline',
            player_identifier: this.playerIdentifier,
        });
    }

    // ------------------------------------------------------------------
    // Hamle geçmişi ve inceleme
    // ------------------------------------------------------------------
    isLive() {
        return this.viewIndex === null;
    }

    currentIndex() {
        return this.isLive() ? this.moves.length : this.viewIndex;
    }

    displayFen() {
        if (this.isLive() && this.optimisticFen) {
            return this.optimisticFen;
        }
        const index = this.currentIndex();
        if (index <= 0) {
            return this.initialFen;
        }
        const move = this.moves[index - 1];
        return (move && move.fen_after) || this.fen;
    }

    displayLastMove() {
        const index = this.currentIndex();
        if (index <= 0) return null;
        const move = this.moves[index - 1];
        return move ? move.uci : null;
    }

    displayCheck() {
        const index = this.currentIndex();
        if (index <= 0) return false;
        const move = this.moves[index - 1];
        return !!(move && move.check);
    }

    goToIndex(index) {
        if (!this.moves.length) return;
        const clamped = Math.max(0, Math.min(index, this.moves.length));
        this.viewIndex = clamped >= this.moves.length ? null : clamped;
        this.selected = null;
        if (this.viewIndex !== null) {
            this.premove = null;
        }
        this.render();
    }

    stepHistory(delta) {
        const current = this.currentIndex();
        const next = current + delta;
        if (next >= this.moves.length) {
            this.goLive();
            return;
        }
        this.goToIndex(next);
    }

    goLive() {
        this.viewIndex = null;
        this.selected = null;
        this.render();
    }

    onHistoryKeydown(event) {
        if (this.promotionModal && !this.promotionModal.classList.contains('hidden')) return;
        if (this.gameOverModal && !this.gameOverModal.classList.contains('hidden')) return;
        const tag = (event.target && event.target.tagName) || '';
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
        if (event.key === 'ArrowLeft') {
            event.preventDefault();
            this.stepHistory(-1);
        } else if (event.key === 'ArrowRight') {
            event.preventDefault();
            this.stepHistory(1);
        } else if (event.key === 'Home') {
            event.preventDefault();
            this.goToIndex(0);
        } else if (event.key === 'End') {
            event.preventDefault();
            this.goLive();
        }
    }

    renderNavigation() {
        if (!this.navPosition) return;
        const total = this.moves.length;
        const index = this.currentIndex();
        const live = this.isLive();

        this.navPosition.textContent = live
            ? 'Canlı'
            : `${index}/${total}`;
        this.navPosition.classList.toggle('live', live);

        const atStart = index <= 0;
        const atEnd = live || index >= total;
        if (this.navFirst) {
            this.navFirst.disabled = atStart;
            this.navPrev.disabled = atStart;
            this.navNext.disabled = atEnd;
            this.navLast.disabled = atEnd;
        }
    }

    toggleReview() {
        if (this.review) {
            this.review = null;
            this.reviewPanel.classList.add('hidden');
            this.reviewBtn.textContent = 'OYUN İNCELEMESİ';
            return;
        }
        this.loadReview();
    }

    loadReview() {
        if (this.reviewLoading) return;
        if (!this.moves.length) {
            this.showToast('İncelenecek hamle yok.', true);
            return;
        }

        this.reviewLoading = true;
        this.reviewRequestId += 1;
        const requestId = this.reviewRequestId;

        this.reviewBtn.disabled = true;
        this.reviewBtn.textContent = 'İNCELENİYOR...';
        this.reviewPanel.classList.remove('hidden');
        this.reviewSummaryEl.classList.add('hidden');
        this.reviewDetailEl.classList.add('hidden');
        this.reviewLoadingEl.classList.remove('hidden');

        fetch(`/satranc/api/review/${this.roomCode}/`)
            .then((response) => response.json())
            .then((data) => {
                if (requestId !== this.reviewRequestId) return;
                if (!data.success) {
                    throw new Error(data.error || 'İnceleme yapılamadı');
                }
                this.review = data;
                this.reviewLoading = false;
                this.reviewLoadingEl.classList.add('hidden');
                this.reviewBtn.disabled = false;
                this.reviewBtn.textContent = 'İNCELEMEYİ KAPAT';
                this.renderReview();
                this.renderMoveList();
            })
            .catch((error) => {
                if (requestId !== this.reviewRequestId) return;
                console.error('İnceleme hatası:', error);
                this.reviewLoading = false;
                this.reviewLoadingEl.classList.add('hidden');
                this.reviewPanel.classList.add('hidden');
                this.reviewBtn.disabled = false;
                this.reviewBtn.textContent = 'OYUN İNCELEMESİ';
                this.showToast('Oyun incelemesi yapılamadı: ' + error.message, true);
            });
    }

    renderReview() {
        if (!this.reviewPanel || !this.reviewSummaryEl || !this.reviewDetailEl) return;
        if (!this.review) {
            this.reviewDetailEl.classList.add('hidden');
            return;
        }

        const summary = this.review.summary || {};
        const white = summary.w || {};
        const black = summary.b || {};

        const accuracyCell = (label, stat, color) => {
            const acc = stat.accuracy !== null && stat.accuracy !== undefined
                ? `${stat.accuracy}%`
                : '-';
            const counts = ['best', 'excellent', 'good', 'inaccuracy', 'mistake', 'blunder']
                .map((key) => {
                    const value = stat[key] || 0;
                    if (!value) return '';
                    const cls = key === 'best' ? 'excellent' : key;
                    return `<span class="grade-chip grade-${cls}" title="${
                        CLASSIFICATION_LABELS[key] || key
                    }">${value}</span>`;
                })
                .join('');
            return `
                <div class="review-accuracy">
                    <div class="review-side">${label} <span class="acc-value ${color}">${acc}</span></div>
                    <div class="review-counts">${counts}</div>
                </div>
            `;
        };

        this.reviewSummaryEl.innerHTML = accuracyCell('Beyaz', white, 'w')
            + accuracyCell('Siyah', black, 'b')
            + `<div class="review-depth">Derinlik: ${this.review.depth || '-'}</div>`;
        this.reviewSummaryEl.classList.remove('hidden');

        const index = this.currentIndex();
        const detail = index > 0 ? this.review.moves[index - 1] : null;
        if (detail) {
            const evalText = this.evalText(detail);
            const label = detail.classification_label || '';
            const cls = detail.classification || 'unknown';
            const lossText = detail.cp_loss !== null && detail.cp_loss !== undefined
                ? `${detail.cp_loss} cp`
                : '-';
            this.reviewDetailEl.innerHTML = `
                <div class="review-move-title">
                    ${detail.move_number}.${detail.color === 'w' ? '' : '..'} ${detail.san}
                    <span class="grade-badge grade-${cls}">${label}</span>
                </div>
                <div class="review-line">Değerlendirme: <strong>${evalText}</strong></div>
                <div class="review-line">Kayıp: <strong>${lossText}</strong> · Doğruluk: <strong>${
                    detail.accuracy !== null && detail.accuracy !== undefined ? detail.accuracy + '%' : '-'
                }</strong></div>
                <div class="review-line">En iyi hamle: <strong>${detail.best_san || '-'}</strong></div>
            `;
            this.reviewDetailEl.classList.remove('hidden');
        } else {
            this.reviewDetailEl.innerHTML = '<div class="review-line muted">İncelemek için bir hamleye tıkla.</div>';
            this.reviewDetailEl.classList.remove('hidden');
        }
    }

    renderEvalBar() {
        if (!this.evalBar || !this.evalBarFill || !this.evalBarText) return;
        if (!this.review) {
            this.evalBar.classList.add('hidden');
            return;
        }

        const index = this.currentIndex();
        let cp = 0;
        let mate = null;
        if (index > 0) {
            const detail = this.review.moves[index - 1];
            if (detail) {
                cp = detail.eval_after;
                mate = detail.mate_after;
            }
        }

        let whiteShare;
        let text;
        if (mate !== null && mate !== undefined) {
            whiteShare = mate > 0 ? 1 : 0;
            text = `M${Math.abs(mate)}`;
        } else if (cp === null || cp === undefined) {
            whiteShare = 0.5;
            text = '0.00';
        } else {
            const clamped = Math.max(-1000, Math.min(1000, cp));
            const win = 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * clamped)) - 1);
            whiteShare = win / 100;
            text = (cp > 0 ? '+' : '') + (cp / 100).toFixed(2);
        }

        const pct = Math.max(0, Math.min(100, whiteShare * 100));
        this.evalBarFill.style.width = `${pct}%`;
        this.evalBarText.textContent = text;
        this.evalBarText.classList.toggle('black-adv', whiteShare < 0.5);
        this.evalBar.classList.remove('hidden');
    }

    evalText(detail) {
        if (!detail) return '-';
        const fmt = (cp, mate, moverColor) => {
            if (mate !== null && mate !== undefined) {
                return `Mat ${mate > 0 ? '+' : ''}${mate}`;
            }
            if (cp === null || cp === undefined) return '-';
            const pawns = (cp / 100).toFixed(2);
            return (cp > 0 ? '+' : '') + pawns;
        };
        const cp = detail.eval_after;
        const mate = detail.mate_after;
        return fmt(cp, mate, detail.color);
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

    pieceMap(fen) {
        const map = {};
        const source = fen || this.displayFen();
        if (!source) return map;
        const placement = source.split(' ')[0];
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
        const premove = (this.isLive() && this.premove) ? this.premove : null;
        if (premove && pieces[premove.from]) {
            const moving = pieces[premove.from];
            delete pieces[premove.from];
            pieces[premove.to] = moving;
        }
        const order = this.squareOrder();
        const targets = this.targetSquares();
        const viewTurn = this.displayFen().split(' ')[1] || this.turn;
        const showCheck = !this.optimisticFen && this.displayCheck();
        const checkSquare = showCheck ? this.kingSquare(viewTurn) : null;
        const lastMoveSquares = this.lastMoveSquares();
        const interactive = this.isMyTurn() || this.canPremove();

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
            if (premove) {
                if (square === premove.from) cell.classList.add('premove');
                if (square === premove.to) cell.classList.add('premove', 'premove-to');
            }
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
        const current = this.currentIndex();

        const buildCell = (index, san) => {
            const span = document.createElement('span');
            span.className = 'san';
            const ply = index + 1;
            span.dataset.ply = String(ply);
            span.textContent = san || '';

            if (ply === current) {
                span.classList.add('active');
            }

            const reviewedMoves = this.review && this.review.moves;
            const reviewed = reviewedMoves ? reviewedMoves[ply - 1] : null;
            if (reviewed && reviewed.classification) {
                span.classList.add(`grade-${reviewed.classification}`);
                span.title = `${reviewed.classification_label} · Kayıp: ${
                    reviewed.cp_loss !== null && reviewed.cp_loss !== undefined
                        ? reviewed.cp_loss
                        : '-'
                } cp${reviewed.best_san ? ` · En iyi: ${reviewed.best_san}` : ''}`;
            }
            return span;
        };

        for (let i = 0; i < this.moves.length; i += 2) {
            const li = document.createElement('li');
            const number = document.createElement('span');
            number.className = 'move-no';
            number.textContent = `${i / 2 + 1}.`;
            li.appendChild(number);

            li.appendChild(
                buildCell(i, this.moves[i] ? this.moves[i].san : '')
            );
            if (this.moves[i + 1]) {
                li.appendChild(
                    buildCell(i + 1, this.moves[i + 1].san)
                );
            } else {
                const empty = document.createElement('span');
                empty.className = 'san empty';
                li.appendChild(empty);
            }

            this.moveList.appendChild(li);
        }

        if (this.isLive()) {
            this.moveList.scrollTop = this.moveList.scrollHeight;
        } else {
            const active = this.moveList.querySelector('.san.active');
            if (active && active.scrollIntoView) {
                active.scrollIntoView({ block: 'nearest' });
            }
        }
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
            if (!this.isLive()) {
                this.setTurnIndicator('', 'GEÇMİŞ İNCELENİYOR');
            } else if (this.isMyTurn()) {
                this.setTurnIndicator('your-turn', 'SIRA SENDE');
            } else if (this.isBotGame) {
                this.setTurnIndicator('opponent-turn', 'BOT DÜŞÜNÜYOR...');
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
                !(this.check && !this.optimisticFen && this.status === 'IN_PROGRESS')
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

        const reason = TERMINATION_LABELS[this.termination];
        let detail = 'Sonuç: ' + (this.result || '-');
        if (this.termination === 'checkmate') {
            detail = 'Mat!';
        } else if (reason) {
            detail = `${reason} · Sonuç: ${this.result || '-'}`;
        } else if (this.check) {
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
    // Saat (clock)
    // ------------------------------------------------------------------
    clockNow() {
        return Date.now() - this.serverOffsetMs;
    }

    remainingTime(color) {
        const stored = this.clock[color] || 0;
        if (!this.timeControl || this.status !== 'IN_PROGRESS') return stored;
        if (this.turn !== color || !this.turnStartedAt) return stored;
        const elapsed = (this.clockNow() - this.turnStartedAt) / 1000;
        return Math.max(0, stored - elapsed);
    }

    formatClock(seconds) {
        const total = Math.max(0, Math.ceil(seconds));
        const minutes = Math.floor(total / 60);
        const rest = total % 60;
        return `${minutes}:${String(rest).padStart(2, '0')}`;
    }

    renderClocks() {
        if (!this.selfClock || !this.opponentClock) return;
        if (!this.timeControl) {
            this.selfClock.classList.add('hidden');
            this.opponentClock.classList.add('hidden');
            return;
        }
        const bottom = this.orientationColor();
        const top = bottom === 'w' ? 'b' : 'w';
        this.selfClock.classList.remove('hidden');
        this.opponentClock.classList.remove('hidden');
        this.updateClockEl(this.selfClock, bottom);
        this.updateClockEl(this.opponentClock, top);
    }

    updateClockEl(el, color) {
        const remaining = this.remainingTime(color);
        el.textContent = this.formatClock(remaining);
        const running = this.status === 'IN_PROGRESS' && this.turn === color;
        el.classList.toggle('running', running);
        el.classList.toggle('low', this.status === 'IN_PROGRESS' && remaining <= 10);
    }

    tickClock() {
        if (!this.timeControl) return;
        this.renderClocks();
        if (this.status !== 'IN_PROGRESS' || !this.turn || this.flagSent) return;
        if (this.remainingTime(this.turn) <= 0) {
            this.flagSent = true;
            this.send({ type: 'flag', player_identifier: this.playerIdentifier });
        }
    }

    // ------------------------------------------------------------------
    // Ön hamle (premove)
    // ------------------------------------------------------------------
    canPremove() {
        return this.isLive()
            && this.status === 'IN_PROGRESS'
            && this.myColor !== null
            && this.turn !== this.myColor;
    }

    handlePremoveClick(square) {
        const pieces = this.pieceMap();
        const piece = pieces[square];

        if (this.selected) {
            const from = this.selected;
            if (from === square) {
                this.selected = null;
                this.render();
                return;
            }
            if (piece && piece.color === this.myColor) {
                this.selected = square;
                this.render();
                return;
            }
            const moving = pieces[from];
            const isPromo = moving && moving.type === 'p'
                && ((moving.color === 'w' && square[1] === '8')
                    || (moving.color === 'b' && square[1] === '1'));
            this.selected = null;
            if (isPromo) {
                this.pendingPromotion = { from, to: square, premove: true };
                const color = this.myColor || 'w';
                this.promotionButtons.forEach((btn) => {
                    btn.innerHTML = pieceSvg(color, btn.dataset.piece);
                });
                this.promotionModal.classList.remove('hidden');
            } else {
                this.premove = { from, to: square, promotion: null };
            }
            this.render();
            return;
        }

        if (piece && piece.color === this.myColor) {
            this.selected = square;
            this.render();
            return;
        }
        this.selected = null;
        this.render();
    }

    maybePlayPremove() {
        if (!this.premove || !this.isMyTurn()) return;
        const { from, to, promotion } = this.premove;
        const base = `${from}${to}`;
        let candidate = null;

        if (promotion) {
            const uci = base + promotion;
            if (this.legalMoves.includes(uci)) candidate = uci;
        } else if (this.legalMoves.includes(base)) {
            candidate = base;
        } else {
            // Terfi gerekiyorsa varsayılan olarak veziri dene.
            const queen = `${base}q`;
            if (this.legalMoves.includes(queen)) {
                candidate = queen;
            } else {
                candidate = this.legalMoves.find(
                    (m) => m.length === 5 && m.slice(0, 4) === base
                ) || null;
            }
        }

        if (candidate) {
            const promo = candidate.length === 5 ? candidate[4] : null;
            this.sendMove(from, to, promo);
        } else {
            this.premove = null;
            this.render();
            this.showToast('Ön hamle geçersiz.', true);
        }
    }

    renderPremoveIndicator() {
        if (!this.premoveIndicator) return;
        const active = !!this.premove
            && this.isLive()
            && this.status === 'IN_PROGRESS';
        this.premoveIndicator.classList.toggle('hidden', !active);
    }

    // ------------------------------------------------------------------
    // Hamle seçimi / sürükle-bırak
    // ------------------------------------------------------------------
    isMyTurn() {
        return this.isLive()
            && this.status === 'IN_PROGRESS'
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
        if (this.isLive() && this.optimisticMove) {
            set.add(this.optimisticMove.from);
            set.add(this.optimisticMove.to);
            return set;
        }
        const uci = this.displayLastMove();
        if (!uci || uci.length < 4) return set;
        set.add(uci.slice(0, 2));
        set.add(uci.slice(2, 4));
        return set;
    }

    targetSquares() {
        const targets = new Map();
        if (!this.selected || !this.isLive()) return targets;

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
        if (!this.promotionModal.classList.contains('hidden')) {
            return;
        }

        const cell = event.target.closest('.square');

        if (!this.isMyTurn()) {
            if (!this.isLive()) {
                this.goLive();
                return;
            }
            if (this.canPremove() && cell) {
                event.preventDefault();
                this.handlePremoveClick(cell.dataset.square);
                return;
            }
            if (this.status === 'IN_PROGRESS') {
                this.showToast('Sıra sende değil.', true);
            }
            return;
        }

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

    // ------------------------------------------------------------------
    // İyimser (optimistic) hamle — sunucu yanıtını beklemeden anında göster
    // ------------------------------------------------------------------
    sendMove(from, to, promotion) {
        let uci = `${from}${to}`;
        if (promotion) uci += promotion;
        this.applyOptimisticMove(from, to, promotion || null, uci);
        this.send({
            type: 'move',
            player_identifier: this.playerIdentifier,
            uci,
        });
    }

    applyOptimisticMove(from, to, promotion, uci) {
        const color = this.myColor;
        if (!color) return;
        const applied = this.computeFenAfter(from, to, promotion);
        if (!applied) return;

        if (this.timeControl) {
            this.clock[color] = this.remainingTime(color) + this.increment;
            this.turnStartedAt = this.clockNow();
        }

        this.optimisticFen = applied.fen;
        this.optimisticMove = { from, to };
        this.optimisticUci = uci;
        this.turn = color === 'w' ? 'b' : 'w';
        this.legalMoves = [];
        this.selected = null;
        this.premove = null;
        this.playOptimisticSound(applied);
        this.render();
    }

    playOptimisticSound(applied) {
        let key = 'move';
        if (applied.castling) key = 'rook';
        else if (applied.captured) key = 'capture';
        const sound = this.sounds[key] || this.sounds.move;
        if (!sound) return;
        try {
            sound.currentTime = 0;
            const promise = sound.play();
            if (promise && typeof promise.catch === 'function') promise.catch(() => {});
        } catch (err) {
            // ses çalınamazsa görmezden gel
        }
    }

    computeFenAfter(from, to, promotion) {
        if (!this.fen) return null;
        const parts = this.fen.split(' ');
        const rows = parts[0].split('/').map((row) => {
            const arr = [];
            for (const ch of row) {
                if (/\d/.test(ch)) {
                    for (let i = 0; i < Number(ch); i += 1) arr.push('');
                } else {
                    arr.push(ch);
                }
            }
            return arr;
        });

        const toRC = (sq) => [8 - Number(sq[1]), FILES.indexOf(sq[0])];
        const [fr, fc] = toRC(from);
        const [tr, tc] = toRC(to);
        const piece = rows[fr] && rows[fr][fc];
        if (!piece) return null;

        const lower = piece.toLowerCase();
        const isWhite = piece === piece.toUpperCase();
        const captured = Boolean(rows[tr] && rows[tr][tc]);
        const castling = lower === 'k' && Math.abs(fc - tc) === 2;

        if (lower === 'p' && fc !== tc && !captured) {
            rows[fr][tc] = '';
        }

        rows[tr][tc] = promotion ? (isWhite ? promotion.toUpperCase() : promotion) : piece;
        rows[fr][fc] = '';

        if (castling) {
            if (tc === 6) { rows[fr][5] = rows[fr][7]; rows[fr][7] = ''; }
            else if (tc === 2) { rows[fr][3] = rows[fr][0]; rows[fr][0] = ''; }
        }

        const placement = rows.map((row) => {
            let out = '';
            let empty = 0;
            row.forEach((ch) => {
                if (!ch) { empty += 1; }
                else { if (empty) { out += empty; empty = 0; } out += ch; }
            });
            if (empty) out += empty;
            return out;
        }).join('/');

        let rights = parts[2] === '-' ? '' : (parts[2] || '');
        const drop = (ch) => { rights = rights.replace(ch, ''); };
        if (piece === 'K') { drop('K'); drop('Q'); }
        if (piece === 'k') { drop('k'); drop('q'); }
        if (from === 'a1' || to === 'a1') drop('Q');
        if (from === 'h1' || to === 'h1') drop('K');
        if (from === 'a8' || to === 'a8') drop('q');
        if (from === 'h8' || to === 'h8') drop('k');
        if (!rights) rights = '-';

        let enPassant = '-';
        if (lower === 'p' && Math.abs(fr - tr) === 2) {
            enPassant = `${from[0]}${(Number(from[1]) + Number(to[1])) / 2}`;
        }

        const halfmove = (lower === 'p' || captured) ? 0 : (Number(parts[4]) || 0) + 1;
        const moverWhite = parts[1] === 'w';
        const fullmove = moverWhite ? (Number(parts[5]) || 1) : (Number(parts[5]) || 1) + 1;
        const nextTurn = moverWhite ? 'b' : 'w';

        return {
            fen: [placement, nextTurn, rights, enPassant, halfmove, fullmove].join(' '),
            captured,
            castling,
        };
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

        this.sendMove(from, to, null);
    }

    completePromotion(piece) {
        if (!this.pendingPromotion) return;
        const { from, to, premove } = this.pendingPromotion;
        this.pendingPromotion = null;
        this.promotionModal.classList.add('hidden');

        if (premove) {
            this.selected = null;
            this.premove = { from, to, promotion: piece };
            this.render();
            return;
        }

        this.sendMove(from, to, piece);
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
