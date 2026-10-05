// Game JavaScript - Handles WebSocket and UI interactions

class NumberGame {
    constructor() {
        this.roomCode = null;
        this.playerId = null;
        this.playerIdentifier = null;
        this.isPlayerOne = null; // true if we are player 1 (room creator)
        this.ws = null;
        this.secretNumber = null;
        this.isReady = false;
        this.isMyTurn = false;
        this.opponentConnected = false;
        this.gameOver = false;
        
        // DOM elements
        this.secretSetupDiv = document.getElementById('secret-setup');
        this.gameAreaDiv = document.getElementById('game-area');
        this.gameOverDiv = document.getElementById('game-over');
        this.secretInput = document.getElementById('secret-input');
        this.setSecretBtn = document.getElementById('set-secret-btn');
        this.guessInput = document.getElementById('guess-input');
        this.guessBtn = document.getElementById('guess-btn');
        this.turnIndicator = document.getElementById('turn-indicator');
        this.opponentStatus = document.getElementById('opponent-status');
        this.opponentActivity = document.getElementById('opponent-activity');
        this.guessList = document.getElementById('guess-list');
        this.gameOverMessage = document.getElementById('game-over-message');
        this.playAgainBtn = document.getElementById('play-again-btn');
        this.secretDisplay = document.querySelector('.secret-display');
        
        // Bind event listeners
        this.setSecretBtn.addEventListener('click', () => this.setSecret());
        this.guessBtn.addEventListener('click', () => this.makeGuess());
        this.playAgainBtn.addEventListener('click', () => this.resetGame());
        
        // Enter key handling
        this.secretInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.setSecret();
        });
        this.guessInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.makeGuess();
        });
        
        // Initialize UI
        this.initUI();
    }
    
    initUI() {
        this.updateTurnIndicator('waiting', 'Rakip bekleniyor...');
        this.updateOpponentStatus('disconnected', 'Rakibin katılması bekleniyor...');
        this.hideGameArea();
        this.hideGameOver();
    }
    
    // WebSocket connection
    connectToRoom(roomCode) {
        this.roomCode = roomCode.toUpperCase();

        // Reuse the identity created on the home page for this room (per tab).
        const storageKey = `sayi:player:${this.roomCode}`;
        this.playerIdentifier = sessionStorage.getItem(storageKey)
            || `guest_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
        sessionStorage.setItem(storageKey, this.playerIdentifier);

        const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${wsScheme}://${window.location.host}/sayi/ws/game/${this.roomCode}/`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            console.log('WebSocket connected, joining as', this.playerIdentifier);
            // The socket must be open before we can send the join message.
            this.joinAsPlayer(this.playerIdentifier);
        };
        
        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            this.handleWebSocketMessage(data);
        };
        
        this.ws.onclose = () => {
            console.log('WebSocket disconnected');
            this.updateOpponentStatus('disconnected', 'Rakip bağlantıyı kesti');
        };
        
        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }
    
    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'player_joined':
                this.handlePlayerJoined(data);
                break;
            case 'player_ready':
                this.handlePlayerReady(data);
                break;
            case 'game_started':
                this.handleGameStarted(data);
                break;
            case 'turn_changed':
                this.handleTurnChanged(data);
                break;
            case 'guess_result':
                // Direct response for the guess we just made
                this.handleGuessResult(data);
                break;
            case 'opponent_guessed':
                this.handleOpponentGuessed(data);
                break;
            case 'game_finished':
                this.handleGameFinished(data);
                break;
            case 'game_abandoned':
                this.handleGameAbandoned(data);
                break;
            case 'game_state':
                this.handleGameState(data);
                break;
            case 'error':
                this.showError(data.message);
                break;
            default:
                console.log('Unknown message type:', data.type);
        }
    }
    
    // Event handlers
    handlePlayerJoined(data) {
        console.log('Player joined:', data.player_identifier);
        // If this is us, store our player info
        if (data.player_identifier === this.playerIdentifier) {
            this.playerId = data.player_id;
            this.isPlayerOne = true; // First joiner is player 1
        } else {
            this.opponentConnected = true;
            this.updateOpponentStatus('connected', 'Rakip bağlandı');
        }
    }
    
    handlePlayerReady(data) {
        if (data.player_identifier === this.playerIdentifier) {
            this.isReady = true;
            this.secretInput.disabled = true;
            this.setSecretBtn.disabled = true;
            this.updateTurnIndicator('waiting', 'Rakibin sayısını girmesi bekleniyor...');
        } else if (this.opponentStatus) {
            this.opponentStatus.textContent = 'Rakip hazır!';
        }
        // Both-ready check is handled by the server via the game_started event.
    }
    
    handleGameStarted(data) {
        console.log('Game started');
        this.showGameArea();
        const isMyTurn = data.current_turn_identifier === this.playerIdentifier;
        this.isMyTurn = isMyTurn;
        this.updateTurnIndicator(
            isMyTurn ? 'your-turn' : 'opponent-turn',
            isMyTurn ? 'SIRA SENDE' : 'RAKİBİN SIRASI'
        );
        this.enableGuessInput(isMyTurn);
    }
    
    handleTurnChanged(data) {
        const isMyTurn = data.new_turn_identifier === this.playerIdentifier;
        this.updateTurnIndicator(
            isMyTurn ? 'your-turn' : 'opponent-turn',
            isMyTurn ? 'SIRA SENDE' : 'RAKİBİN SIRASI'
        );
        this.enableGuessInput(isMyTurn);
        this.isMyTurn = isMyTurn;
    }
    
    handleGuessResult(data) {
        // Result of our own guess: add it to our history.
        this.addGuessToHistory(data.guess, data.result);
    }
    
    handleOpponentGuessed(data) {
        // This event is broadcast to everyone; ignore our own guess
        // (it is already shown via the direct guess_result response).
        if (data.player_identifier === this.playerIdentifier) {
            return;
        }
        this.addOpponentGuessNotification(data.guess, data.result);
    }
    
    handleGameFinished(data) {
        this.gameOver = true;
        const isWinner = data.winner_identifier === this.playerIdentifier;
        this.showGameOver(isWinner);
        this.disableAllInput();
    }
    
    handleGameAbandoned(data) {
        this.showError(data.message);
        this.disableAllInput();
    }
    
    handleGameState(data) {
        console.log('Game state received:', data);
        this.roomCode = data.room_code;

        // Reflect opponent presence (they may have joined before we connected).
        const others = (data.players || []).filter(
            p => p.player_identifier !== this.playerIdentifier
        );
        if (others.length > 0) {
            this.opponentConnected = true;
            const opponentReady = others.some(p => p.ready);
            this.updateOpponentStatus(
                'connected',
                opponentReady ? 'Rakip hazır!' : 'Rakip bağlandı'
            );
        }

        if (data.status === 'IN_PROGRESS') {
            this.showGameArea();
            const isMyTurn = data.current_turn_identifier === this.playerIdentifier;
            this.isMyTurn = isMyTurn;
            this.updateTurnIndicator(
                isMyTurn ? 'your-turn' : 'opponent-turn',
                isMyTurn ? 'SIRA SENDE' : 'RAKİBİN SIRASI'
            );
            this.enableGuessInput(isMyTurn);
        }
    }
    
    // Game actions
    joinAsPlayer(playerIdentifier) {
        this.playerIdentifier = playerIdentifier;
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'join_player',
                player_identifier: this.playerIdentifier
            }));
        }
    }
    
    setSecret() {
        const secret = this.secretInput.value.trim();
        if (!secret) {
            this.showError('Lütfen bir gizli sayı gir');
            return;
        }
        
        // Validate client-side (will also be validated server-side)
        if (!/^\d{4}$/.test(secret)) {
            this.showError('Gizli sayı tam 4 basamaklı olmalı');
            return;
        }
        if (secret[0] === '0') {
            this.showError('Gizli sayı 0 ile başlayamaz');
            return;
        }
        if (new Set(secret.split('')).size !== 4) {
            this.showError('Gizli sayıdaki rakamlar birbirinden farklı olmalı');
            return;
        }
        
        this.secretNumber = secret;
        this.secretDisplay.textContent = secret;
        
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'set_secret',
                player_identifier: this.playerIdentifier,
                secret_number: secret
            }));
        }
        
        this.secretInput.disabled = true;
        this.setSecretBtn.disabled = true;
        this.isReady = true;
    }
    
    makeGuess() {
        if (!this.isMyTurn || this.gameOver) return;
        
        const guess = this.guessInput.value.trim();
        if (!guess) {
            this.showError('Lütfen bir tahmin gir');
            return;
        }
        
        // Validate client-side
        if (!/^\d{4}$/.test(guess)) {
            this.showError('Tahmin tam 4 basamaklı olmalı');
            return;
        }
        if (guess[0] === '0') {
            this.showError('Tahmin 0 ile başlayamaz');
            return;
        }
        if (new Set(guess.split('')).size !== 4) {
            this.showError('Tahminde rakamlar birbirinden farklı olmalı');
            return;
        }
        
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({
                type: 'make_guess',
                player_identifier: this.playerIdentifier,
                guess: guess
            }));
            
            // Disable input until we get response
            this.disableGuessInput();
        }
    }
    
    // UI Helper methods
    updateTurnIndicator(type, text) {
        this.turnIndicator.className = `turn-indicator ${type}`;
        this.turnIndicator.textContent = text;
    }
    
    updateOpponentStatus(type, text) {
        this.opponentStatus.className = `opponent-status ${type}`;
        this.opponentStatus.textContent = text;
    }
    
    showGameArea() {
        this.secretSetupDiv.classList.add('hidden');
        this.gameAreaDiv.classList.remove('hidden');
        this.gameAreaDiv.classList.add('visible');
    }
    
    hideGameArea() {
        this.gameAreaDiv.classList.add('hidden');
        this.gameAreaDiv.classList.remove('visible');
    }
    
    hideGameOver() {
        this.gameOverDiv.classList.add('hidden');
    }
    
    showGameOver(isWinner) {
        this.gameOverDiv.classList.remove('hidden');
        if (isWinner) {
            this.gameOverMessage.textContent = 'KAZANDIN!';
            this.gameOverMessage.style.color = '#27ae60';
        } else {
            this.gameOverMessage.textContent = 'KAYBETTİN!';
            this.gameOverMessage.style.color = '#e74c3c';
        }
    }
    
    enableGuessInput(enable) {
        this.guessInput.disabled = !enable;
        this.guessBtn.disabled = !enable;
        if (enable) {
            this.guessInput.focus();
        }
    }
    
    disableGuessInput() {
        this.guessInput.disabled = true;
        this.guessBtn.disabled = true;
    }
    
    disableAllInput() {
        this.secretInput.disabled = true;
        this.setSecretBtn.disabled = true;
        this.guessInput.disabled = true;
        this.guessBtn.disabled = true;
    }
    
    addGuessToHistory(guess, result) {
        const guessItem = document.createElement('div');
        guessItem.className = 'guess-item';
        
        const guessNumber = document.createElement('div');
        guessNumber.className = 'guess-number';
        guessNumber.textContent = guess;
        
        const guessResult = document.createElement('div');
        guessResult.className = `guess-result ${result.includes('+') ? 'plus' : ''} ${result.includes('-') ? 'minus' : ''}`;
        guessResult.textContent = result || ' ';
        
        guessItem.appendChild(guessNumber);
        guessItem.appendChild(guessResult);
        
        this.guessList.appendChild(guessItem);
        // Scroll to bottom
        this.guessList.scrollTop = this.guessList.scrollHeight;
    }
    
    addOpponentGuessNotification(guess, result) {
        console.log(`Rakip oynadı: ${guess} -> ${result}`);
        if (this.opponentActivity) {
            this.opponentActivity.textContent = `Rakip tahmin etti: ${guess} → ${result || 'eşleşme yok'}`;
        }
    }
    
    resetGame() {
        // In a real app, we'd send a reset request or create new room
        // For now, just reload the page
        window.location.reload();
    }
    
    showError(message) {
        alert(message); // Simple error display; could be improved
        console.error(message);
    }
    
    // Helper to simulate keypress for Enter (since we used wrong event name above)
    // Fixing the keypress handler
    initKeyPressHandlers() {
        this.secretInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.setSecret();
        });
        this.guessInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this.makeGuess();
        });
    }
}

// Initialize game when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.game = new NumberGame();

    // Room code is rendered on the page (server) or passed via ?room= query
    const urlParams = new URLSearchParams(window.location.search);
    const roomCode = document.body.dataset.roomCode || urlParams.get('room');
    if (roomCode) {
        // Identity + join is handled inside connectToRoom (on socket open).
        window.game.connectToRoom(roomCode);
    }
});

// Expose functions for HTML buttons to call (if needed)
function joinRoom(roomCode) {
    if (window.game) {
        window.game.connectToRoom(roomCode);
        const playerId = `player_${Date.now()}`;
        window.game.joinAsPlayer(playerId);
    }
}

function setSecretNumber() {
    if (window.game) {
        window.game.setSecret();
    }
}

function makeGuess() {
    if (window.game) {
        window.game.makeGuess();
    }
}