// Kim Bu? (Guess Who) - WebSocket client

class GuessWhoGame {
    constructor() {
        this.roomCode = null;
        this.playerIdentifier = null;
        this.ws = null;

        this.characters = {};
        this.characterOrder = [];
        this.status = null;
        this.currentTurnIdentifier = null;
        this.awaitingAnswer = false;
        this.questionOwnerIdentifier = null;
        this.selfCharacterId = null;
        this.selectedCharacterId = null;
        this.eliminated = new Set();
        this.accuseMode = false;
        this.gameOver = false;
        this.opponentConnected = false;

        this.dom = {
            turnIndicator: document.getElementById('turn-indicator'),
            opponentStatus: document.getElementById('opponent-status'),
            opponentActivity: document.getElementById('opponent-activity'),
            mySecret: document.getElementById('my-secret'),
            mySecretName: document.getElementById('my-secret-name'),
            mySecretImg: document.getElementById('my-secret-img'),
            chooser: document.getElementById('chooser'),
            chooserGrid: document.getElementById('chooser-grid'),
            confirmCharacterBtn: document.getElementById('confirm-character-btn'),
            waitingOpponent: document.getElementById('waiting-opponent'),
            gameArea: document.getElementById('game-area'),
            boardGrid: document.getElementById('board-grid'),
            clearEliminatedBtn: document.getElementById('clear-eliminated-btn'),
            chatLog: document.getElementById('chat-log'),
            chatInput: document.getElementById('chat-input'),
            chatSendBtn: document.getElementById('chat-send-btn'),
            askBtn: document.getElementById('ask-btn'),
            accuseBtn: document.getElementById('accuse-btn'),
            accuseHint: document.getElementById('accuse-hint'),
            answerBar: document.getElementById('answer-bar'),
            answerPrompt: document.getElementById('answer-prompt'),
            answerYes: document.getElementById('answer-yes'),
            answerNo: document.getElementById('answer-no'),
            gameOver: document.getElementById('game-over'),
            gameOverMessage: document.getElementById('game-over-message'),
            gameOverReveal: document.getElementById('game-over-reveal'),
            playAgainBtn: document.getElementById('play-again-btn'),
            copyRoomBtn: document.getElementById('copy-room-btn'),
            toast: document.getElementById('toast'),
            preview: document.getElementById('char-preview'),
            previewImg: document.getElementById('char-preview-img'),
            previewName: document.getElementById('char-preview-name'),
        };

        this.loadCharacters();
        this.bindEvents();
    }

    loadCharacters() {
        const dataEl = document.getElementById('characters-data');
        if (dataEl) {
            try {
                const list = JSON.parse(dataEl.textContent);
                list.forEach((c) => {
                    this.characters[c.id] = c;
                    this.characterOrder.push(c.id);
                });
            } catch (e) {
                console.error('Karakterler yüklenemedi', e);
            }
        }
    }

    bindEvents() {
        this.dom.confirmCharacterBtn.addEventListener('click', () => this.confirmCharacter());
        this.dom.chooserGrid.addEventListener('click', (e) => this.handleCharacterSelect(e));
        this.dom.boardGrid.addEventListener('click', (e) => this.handleBoardClick(e));

        this.dom.chatSendBtn.addEventListener('click', () => this.sendChat());
        this.dom.askBtn.addEventListener('click', () => this.askQuestion());
        this.dom.chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.sendChat();
        });

        this.dom.answerYes.addEventListener('click', () => this.answerQuestion('yes'));
        this.dom.answerNo.addEventListener('click', () => this.answerQuestion('no'));

        this.dom.accuseBtn.addEventListener('click', () => this.toggleAccuseMode());
        this.dom.clearEliminatedBtn.addEventListener('click', () => this.clearEliminated());
        this.dom.playAgainBtn.addEventListener('click', () => this.requestRestart());
        this.dom.copyRoomBtn.addEventListener('click', () => this.copyRoomCode());

        document.addEventListener('mouseover', (e) => this.handlePreviewOver(e));
        document.addEventListener('mousemove', (e) => this.handlePreviewMove(e));
        document.addEventListener('mouseout', (e) => this.handlePreviewOut(e));
    }

    // Enlarged character preview that follows the cursor on hover.
    handlePreviewOver(event) {
        const card = event.target.closest && event.target.closest('.char-card');
        if (!card || card === this._previewCard) return;
        this.showPreview(card);
    }

    handlePreviewMove(event) {
        if (this._previewCard) this.positionPreview(event.clientX, event.clientY);
    }

    handlePreviewOut(event) {
        const card = event.target.closest && event.target.closest('.char-card');
        if (!card) return;
        const to = event.relatedTarget;
        if (to && to.closest && to.closest('.char-card') === card) return;
        if (this._previewCard === card) this.hidePreview();
    }

    showPreview(card) {
        const img = card.querySelector('img');
        if (!img) return;
        this._previewCard = card;
        this.dom.previewImg.src = img.src;
        const nameEl = card.querySelector('.char-name');
        this.dom.previewName.textContent = nameEl ? nameEl.textContent : '';
        this.dom.preview.classList.remove('hidden');
    }

    positionPreview(x, y) {
        const el = this.dom.preview;
        const w = el.offsetWidth || 200;
        const h = el.offsetHeight || 260;
        let left = x + 20;
        if (left + w > window.innerWidth - 8) left = x - w - 20;
        if (left < 8) left = 8;
        let top = y - h / 2;
        top = Math.max(8, Math.min(top, window.innerHeight - h - 8));
        el.style.left = `${left}px`;
        el.style.top = `${top}px`;
    }

    hidePreview() {
        this._previewCard = null;
        this.dom.preview.classList.add('hidden');
    }

    // ------------------------------------------------------------------
    // Connection
    // ------------------------------------------------------------------
    connectToRoom(roomCode) {
        this.roomCode = roomCode.toUpperCase();
        this.dom.copyRoomBtn.dataset.code = this.roomCode;

        const storageKey = `recru:player:${this.roomCode}`;
        this.playerIdentifier = sessionStorage.getItem(storageKey)
            || `guest_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
        sessionStorage.setItem(storageKey, this.playerIdentifier);

        const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        this.ws = new WebSocket(`${wsScheme}://${window.location.host}/ws/game/${this.roomCode}/`);

        this.ws.onopen = () => {
            this.send({ type: 'join_player', player_identifier: this.playerIdentifier });
        };
        this.ws.onmessage = (event) => this.handleMessage(JSON.parse(event.data));
        this.ws.onclose = () => this.setOpponentStatus('disconnected', 'Bağlantı koptu');
        this.ws.onerror = (err) => console.error('WebSocket hatası', err);
    }

    send(payload) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify(payload));
        }
    }

    handleMessage(data) {
        switch (data.type) {
            case 'game_state': return this.handleGameState(data);
            case 'player_joined': return this.handlePlayerJoined(data);
            case 'player_ready': return this.handlePlayerReady(data);
            case 'game_started': return this.handleGameStarted(data);
            case 'turn_changed': return this.handleTurnChanged(data);
            case 'chat_message': return this.appendMessage(data.message);
            case 'accusation_result': return this.handleAccusationResult(data);
            case 'game_finished': return this.handleGameFinished(data);
            case 'room_reset': return this.handleRoomReset();
            case 'game_abandoned': return this.handleAbandoned(data);
            case 'error': return this.toast(data.message, true);
            default: console.log('Bilinmeyen mesaj', data);
        }
    }

    // ------------------------------------------------------------------
    // Server event handlers
    // ------------------------------------------------------------------
    handleGameState(data) {
        this.status = data.status;
        this.currentTurnIdentifier = data.current_turn_identifier;
        this.awaitingAnswer = data.awaiting_answer;
        this.questionOwnerIdentifier = data.question_owner_identifier;

        const players = data.players || [];
        const me = players.find((p) => p.player_identifier === this.playerIdentifier);
        const opponents = players.filter((p) => p.player_identifier !== this.playerIdentifier);

        if (me && me.character_id) {
            this.selfCharacterId = me.character_id;
            this.showMySecret();
        }
        if (me && Array.isArray(me.eliminated)) {
            this.eliminated = new Set(me.eliminated);
        }
        if (opponents.length > 0) {
            this.opponentConnected = true;
            const ready = opponents.some((p) => p.ready);
            this.setOpponentStatus('connected', ready ? 'Rakip hazır' : 'Rakip odada');
        }

        this.renderChat(data.messages || []);

        if (data.status === 'IN_PROGRESS' || data.status === 'FINISHED') {
            this.showGameArea();
            this.applyEliminated();
            this.updateTurnUi();
            if (data.status === 'FINISHED' && data.winner_identifier) {
                this.showGameOver(
                    data.winner_identifier === this.playerIdentifier,
                    this.buildReveal(data.players)
                );
            }
        } else if (data.status === 'CHOOSING') {
            if (this.selfCharacterId) {
                this.showWaitingOpponent();
            } else {
                this.showChooser();
            }
        }
    }

    handlePlayerJoined(data) {
        if (data.player_identifier === this.playerIdentifier) {
            return;
        }
        this.opponentConnected = true;
        this.setOpponentStatus('connected', 'Rakip odada');
        this.toast('Rakip odaya katıldı!');
        if (!this.selfCharacterId && this.status !== 'IN_PROGRESS') {
            this.showChooser();
        }
    }

    handlePlayerReady(data) {
        if (data.player_identifier === this.playerIdentifier) {
            this.selfCharacterId = data.character_id;
            this.showMySecret();
        } else {
            this.setOpponentStatus('connected', 'Rakip karakterini seçti');
        }
    }

    handleGameStarted(data) {
        this.status = 'IN_PROGRESS';
        this.currentTurnIdentifier = data.current_turn_identifier;
        this.showGameArea();
        this.updateTurnUi();
        this.toast('Oyun başladı!');
    }

    handleTurnChanged(data) {
        this.currentTurnIdentifier = data.current_turn_identifier;
        this.awaitingAnswer = data.awaiting_answer;
        this.questionOwnerIdentifier = data.question_owner_identifier;
        this.updateTurnUi();
    }

    handleAccusationResult(data) {
        // The authoritative result arrives via game_finished; nothing else needed.
        console.log('Tahmin sonucu', data);
    }

    handleGameFinished(data) {
        this.gameOver = true;
        this.status = 'FINISHED';
        const iWon = data.winner_identifier === this.playerIdentifier;
        this.showGameOver(iWon, data.reveal || {});
        this.updateTurnUi();
    }

    handleRoomReset() {
        this.gameOver = false;
        this.status = 'CHOOSING';
        this.currentTurnIdentifier = null;
        this.awaitingAnswer = false;
        this.questionOwnerIdentifier = null;
        this.selfCharacterId = null;
        this.selectedCharacterId = null;
        this.eliminated = new Set();
        this.accuseMode = false;
        this.dom.gameOver.classList.add('hidden');
        this.dom.gameArea.classList.add('hidden');
        this.dom.mySecret.classList.add('hidden');
        this.renderChat([]);
        this.applyEliminated();
        this.updateTurnUi();
        this.showChooser();
    }

    handleAbandoned(data) {
        this.gameOver = true;
        this.toast(data.message || 'Rakip oyundan ayrıldı.', true);
        this.updateTurnUi();
    }

    // ------------------------------------------------------------------
    // Character selection
    // ------------------------------------------------------------------
    handleCharacterSelect(event) {
        const card = event.target.closest('.char-card');
        if (!card) return;
        const id = card.dataset.characterId;
        this.selectedCharacterId = id;
        Array.from(this.dom.chooserGrid.querySelectorAll('.char-card')).forEach((el) => {
            el.classList.toggle('selected', el.dataset.characterId === id);
        });
        this.dom.confirmCharacterBtn.disabled = false;
    }

    confirmCharacter() {
        if (!this.selectedCharacterId) return;
        this.send({
            type: 'choose_character',
            player_identifier: this.playerIdentifier,
            character_id: this.selectedCharacterId,
        });
        this.selfCharacterId = this.selectedCharacterId;
        this.showMySecret();
        this.showWaitingOpponent();
    }

    showMySecret() {
        const character = this.characters[this.selfCharacterId];
        if (!character) return;
        this.dom.mySecretName.textContent = character.name;
        this.dom.mySecretImg.src = this.imageUrl(character.id);
        this.dom.mySecret.classList.remove('hidden');
    }

    // ------------------------------------------------------------------
    // Board
    // ------------------------------------------------------------------
    handleBoardClick(event) {
        const card = event.target.closest('.char-card');
        if (!card) return;
        const id = card.dataset.characterId;

        if (this.accuseMode) {
            this.confirmAccusation(id);
            return;
        }
        if (this.gameOver || this.status !== 'IN_PROGRESS') return;

        if (this.eliminated.has(id)) {
            this.eliminated.delete(id);
        } else {
            this.eliminated.add(id);
        }
        card.classList.toggle('eliminated', this.eliminated.has(id));
        this.persistEliminated();
    }

    applyEliminated() {
        Array.from(this.dom.boardGrid.querySelectorAll('.char-card')).forEach((el) => {
            el.classList.toggle('eliminated', this.eliminated.has(el.dataset.characterId));
        });
    }

    persistEliminated() {
        this.send({
            type: 'set_eliminated',
            player_identifier: this.playerIdentifier,
            eliminated: Array.from(this.eliminated),
        });
    }

    clearEliminated() {
        this.eliminated = new Set();
        this.applyEliminated();
        this.persistEliminated();
    }

    toggleAccuseMode() {
        if (!this.canAct()) return;
        this.accuseMode = !this.accuseMode;
        this.dom.boardGrid.classList.toggle('accuse-mode', this.accuseMode);
        this.dom.accuseBtn.classList.toggle('active', this.accuseMode);
        this.dom.accuseBtn.textContent = this.accuseMode ? 'İptal' : 'Tahmin Et';
        this.dom.accuseHint.textContent = this.accuseMode
            ? 'Tahmin etmek istediğin karaktere tıkla.'
            : 'Yanlış tahmin oyunu kaybettirir!';
    }

    confirmAccusation(characterId) {
        const character = this.characters[characterId];
        const name = character ? character.name : characterId;
        if (!window.confirm(`"${name}" karakterini tahmin ediyorsun. Yanlışsa oyunu kaybedersin. Emin misin?`)) {
            return;
        }
        this.send({
            type: 'make_accusation',
            player_identifier: this.playerIdentifier,
            character_id: characterId,
        });
        this.accuseMode = false;
        this.dom.boardGrid.classList.remove('accuse-mode');
        this.dom.accuseBtn.classList.remove('active');
        this.dom.accuseBtn.textContent = 'Tahmin Et';
    }

    // ------------------------------------------------------------------
    // Chat
    // ------------------------------------------------------------------
    sendChat() {
        const text = this.dom.chatInput.value.trim();
        if (!text) return;
        this.send({ type: 'send_chat', player_identifier: this.playerIdentifier, text });
        this.dom.chatInput.value = '';
    }

    askQuestion() {
        if (!this.canAct()) {
            this.toast('Şu anda soru soramazsın.', true);
            return;
        }
        const text = this.dom.chatInput.value.trim();
        if (!text) {
            this.toast('Sormak istediğin soruyu yaz.', true);
            return;
        }
        this.send({ type: 'ask_question', player_identifier: this.playerIdentifier, text });
        this.dom.chatInput.value = '';
    }

    answerQuestion(answer) {
        this.send({ type: 'answer_question', player_identifier: this.playerIdentifier, answer });
    }

    renderChat(messages) {
        this.dom.chatLog.innerHTML = '';
        messages.forEach((message) => this.appendMessage(message, true));
        this.scrollChat();
    }

    appendMessage(message, skipScroll) {
        const mine = message.sender_identifier === this.playerIdentifier;
        const el = document.createElement('div');
        el.className = `chat-msg kind-${message.kind} ${mine ? 'mine' : 'theirs'}`;

        const who = document.createElement('span');
        who.className = 'chat-who';
        if (message.kind === 'system') {
            who.textContent = '•';
        } else {
            who.textContent = mine ? 'Sen' : 'Rakip';
        }

        const bubble = document.createElement('div');
        bubble.className = 'chat-bubble';

        if (message.kind === 'question') {
            bubble.innerHTML = `<span class="q-label">Soru:</span> ${this.escape(message.text)}`;
        } else if (message.kind === 'answer') {
            bubble.innerHTML = `<span class="a-label">Cevap:</span> ${this.escape(message.text)}`;
            el.classList.add(message.answer === 'yes' ? 'answer-yes' : 'answer-no');
        } else {
            bubble.textContent = message.text;
        }

        el.appendChild(who);
        el.appendChild(bubble);
        this.dom.chatLog.appendChild(el);
        if (!skipScroll) this.scrollChat();
    }

    scrollChat() {
        this.dom.chatLog.scrollTop = this.dom.chatLog.scrollHeight;
    }

    // ------------------------------------------------------------------
    // UI state
    // ------------------------------------------------------------------
    isMyTurn() {
        return this.status === 'IN_PROGRESS'
            && this.currentTurnIdentifier === this.playerIdentifier
            && !this.gameOver;
    }

    canAct() {
        return this.isMyTurn() && !this.awaitingAnswer;
    }

    updateTurnUi() {
        const indicator = this.dom.turnIndicator;
        const askEnabled = this.canAct();
        this.dom.askBtn.disabled = !askEnabled;
        this.dom.accuseBtn.disabled = !askEnabled;

        const imAnswerer = this.awaitingAnswer
            && this.questionOwnerIdentifier
            && this.questionOwnerIdentifier !== this.playerIdentifier;

        if (this.status === 'FINISHED' || this.gameOver) {
            indicator.className = 'turn-indicator waiting';
            indicator.textContent = 'Oyun bitti';
        } else if (this.status !== 'IN_PROGRESS') {
            indicator.className = 'turn-indicator waiting';
            indicator.textContent = this.selfCharacterId ? 'Rakip bekleniyor...' : 'Karakter seç';
        } else if (this.awaitingAnswer && imAnswerer) {
            indicator.className = 'turn-indicator opponent-turn';
            indicator.textContent = 'RAKİP SORU SORDU';
        } else if (this.awaitingAnswer) {
            indicator.className = 'turn-indicator waiting';
            indicator.textContent = 'Cevap bekleniyor...';
        } else if (this.isMyTurn()) {
            indicator.className = 'turn-indicator your-turn';
            indicator.textContent = 'SIRA SENDE';
        } else {
            indicator.className = 'turn-indicator opponent-turn';
            indicator.textContent = 'RAKİBİN SIRASI';
        }

        this.updateAnswerBar(imAnswerer);
    }

    updateAnswerBar(show) {
        if (show) {
            this.dom.answerBar.classList.remove('hidden');
            const lastQuestion = this.lastQuestionText();
            this.dom.answerPrompt.textContent = lastQuestion
                ? `Soru: "${lastQuestion}"`
                : 'Rakip bir soru sordu:';
        } else {
            this.dom.answerBar.classList.add('hidden');
        }
    }

    lastQuestionText() {
        const questions = this.dom.chatLog.querySelectorAll('.chat-msg.kind-question .chat-bubble');
        if (!questions.length) return '';
        return questions[questions.length - 1].textContent.replace(/^Soru:\s*/, '');
    }

    showChooser() {
        this.dom.chooser.classList.remove('hidden');
        this.dom.waitingOpponent.classList.add('hidden');
    }

    showWaitingOpponent() {
        this.dom.chooser.classList.add('hidden');
        this.dom.waitingOpponent.classList.remove('hidden');
    }

    showGameArea() {
        this.dom.chooser.classList.add('hidden');
        this.dom.waitingOpponent.classList.add('hidden');
        this.dom.gameArea.classList.remove('hidden');
        this.dom.gameArea.classList.add('visible');
    }

    showGameOver(iWon, reveal) {
        this.dom.gameOver.classList.remove('hidden');
        this.dom.gameOverMessage.textContent = iWon ? 'KAZANDIN!' : 'KAYBETTİN!';
        this.dom.gameOverMessage.className = iWon ? 'win' : 'lose';

        const others = Object.entries(reveal).filter(([id]) => id !== this.playerIdentifier);
        this.dom.gameOverReveal.innerHTML = '';
        others.forEach(([, characterId]) => {
            const character = this.characters[characterId];
            if (!character) return;
            const wrap = document.createElement('div');
            wrap.className = 'reveal-card';
            wrap.innerHTML = `<img src="${this.imageUrl(character.id)}" alt="${character.name}">
                <span>Rakibin karakteri: <strong>${character.name}</strong></span>`;
            this.dom.gameOverReveal.appendChild(wrap);
        });
    }

    buildReveal(players) {
        const reveal = {};
        (players || []).forEach((p) => {
            if (p.character_id) reveal[p.player_identifier] = p.character_id;
        });
        return reveal;
    }

    setOpponentStatus(state, text) {
        this.dom.opponentStatus.className = `opponent-status ${state}`;
        this.dom.opponentStatus.textContent = text;
    }

    requestRestart() {
        this.send({ type: 'restart_game', player_identifier: this.playerIdentifier });
    }

    copyRoomCode() {
        const code = this.dom.copyRoomBtn.dataset.code || this.roomCode;
        navigator.clipboard?.writeText(code).then(
            () => this.toast('Oda kodu kopyalandı!'),
            () => this.toast(code)
        );
    }

    imageUrl(characterId) {
        const card = document.querySelector(`.char-card[data-character-id="${characterId}"] img`);
        return card ? card.src : '';
    }

    escape(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    toast(message, isError) {
        const el = this.dom.toast;
        el.textContent = message;
        el.className = `toast ${isError ? 'error' : ''}`;
        el.classList.remove('hidden');
        clearTimeout(this._toastTimer);
        this._toastTimer = setTimeout(() => el.classList.add('hidden'), 3200);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const roomCode = document.body.dataset.roomCode;
    const game = new GuessWhoGame();
    window.game = game;
    if (roomCode) {
        game.connectToRoom(roomCode);
    }
});
