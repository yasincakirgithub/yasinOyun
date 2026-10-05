// Amiral Battı - WebSocket ve arayüz yönetimi

class BattleshipGame {
    constructor() {
        this.roomCode = null;
        this.playerIdentifier = null;
        this.ws = null;

        this.gridSize = Number(document.body.dataset.gridSize) || 14;
        this.fleet = [];
        this.columns = 'ABCDEFGHIJKLMN';

        this.orientation = 'h';
        this.selectedShipId = null;
        this.placedShips = [];
        this.placementInitialized = false;
        this.selfReady = false;

        this.myShips = [];
        this.myShots = [];
        this.incomingShots = [];
        this.enemyShips = [];

        this.status = 'WAITING';
        this.currentTurnIdentifier = null;
        this.winnerIdentifier = null;
        this.gameOver = false;
        this.opponentConnected = false;

        // Ses
        this.audio = {
            background: null,
            hit: null,
            miss: null,
            musicVolume: 35,
            sfxVolume: 70,
            enabled: true,
        };

        // DOM
        this.placementSection = document.getElementById('placement');
        this.placementGrid = document.getElementById('placement-grid');
        this.shipTray = document.getElementById('ship-tray');
        this.rotateBtn = document.getElementById('rotate-btn');
        this.randomBtn = document.getElementById('random-btn');
        this.clearBtn = document.getElementById('clear-btn');
        this.confirmBtn = document.getElementById('confirm-btn');
        this.placementHint = document.getElementById('placement-hint');

        this.waitingSection = document.getElementById('waiting-opponent');

        this.gameArea = document.getElementById('game-area');
        this.ownGrid = document.getElementById('own-grid');
        this.enemyGrid = document.getElementById('enemy-grid');
        this.enemyNote = document.getElementById('enemy-note');
        this.mobileTurn = document.getElementById('mobile-turn');

        this.turnIndicator = document.getElementById('turn-indicator');
        this.opponentStatus = document.getElementById('opponent-status');
        this.opponentActivity = document.getElementById('opponent-activity');

        this.gameOverEl = document.getElementById('game-over');
        this.gameOverMessage = document.getElementById('game-over-message');
        this.gameOverDetail = document.getElementById('game-over-detail');
        this.playAgainBtn = document.getElementById('play-again-btn');

        this.copyRoomBtn = document.getElementById('copy-room-btn');
        this.toastEl = document.getElementById('toast');

        this.audioToggleBtn = document.getElementById('audio-toggle');
        this.musicVolumeInput = document.getElementById('music-volume');
        this.musicVolumeOutput = document.getElementById('music-volume-value');
        this.sfxVolumeInput = document.getElementById('sfx-volume');
        this.sfxVolumeOutput = document.getElementById('sfx-volume-value');

        this.toastTimer = null;
        this.audioUnlockBound = false;

        this.initAudio();
        this.bindEvents();
    }

    // ------------------------------------------------------------------
    // Kurulum
    // ------------------------------------------------------------------
    bindEvents() {
        this.rotateBtn.addEventListener('click', () => this.toggleOrientation());
        this.randomBtn.addEventListener('click', () => this.fillRandom());
        this.clearBtn.addEventListener('click', () => this.clearBoard());
        this.confirmBtn.addEventListener('click', () => this.confirmPlacement());
        this.playAgainBtn.addEventListener('click', () => this.restartGame());
        if (this.copyRoomBtn) {
            this.copyRoomBtn.addEventListener('click', () => this.copyRoomCode());
        }

        // Gemilerin nereye geleceğini önizle (imleç tahtada gezerken).
        this.placementGrid.addEventListener('mouseover', (event) => {
            const cell = event.target.closest('.cell');
            if (!cell) return;
            this.previewAt(Number(cell.dataset.row), Number(cell.dataset.col));
        });
        this.placementGrid.addEventListener('mouseleave', () => this.clearPreview());

        // Ses kontrolleri
        if (this.audioToggleBtn) {
            this.audioToggleBtn.addEventListener('click', () => this.toggleAudio());
        }
        if (this.musicVolumeInput) {
            this.musicVolumeInput.addEventListener('input', () => {
                this.setMusicVolume(Number(this.musicVolumeInput.value));
            });
        }
        if (this.sfxVolumeInput) {
            this.sfxVolumeInput.addEventListener('input', () => {
                this.setSfxVolume(Number(this.sfxVolumeInput.value));
            });
        }
    }

    // ------------------------------------------------------------------
    // Ses
    // ------------------------------------------------------------------
    initAudio() {
        this.audio.background = new Audio(document.body.dataset.audioBg);
        this.audio.background.loop = true;
        this.audio.background.preload = 'auto';

        this.audio.hit = new Audio(document.body.dataset.audioHit);
        this.audio.hit.preload = 'auto';

        this.audio.miss = new Audio(document.body.dataset.audioMiss);
        this.audio.miss.preload = 'auto';

        const settings = this.loadAudioSettings();
        this.audio.enabled = settings.enabled;
        this.audio.musicVolume = settings.musicVolume;
        this.audio.sfxVolume = settings.sfxVolume;

        if (this.musicVolumeInput) this.musicVolumeInput.value = this.audio.musicVolume;
        if (this.sfxVolumeInput) this.sfxVolumeInput.value = this.audio.sfxVolume;
        this.applyAudioVolumes();
        this.updateAudioToggleLabel();

        this.startBackgroundMusic();
    }

    loadAudioSettings() {
        const defaults = { enabled: true, musicVolume: 35, sfxVolume: 70 };
        try {
            const raw = localStorage.getItem('amiral:audio');
            if (raw) {
                return { ...defaults, ...JSON.parse(raw) };
            }
        } catch (err) {
            console.warn('Ses ayarları okunamadı', err);
        }
        return defaults;
    }

    saveAudioSettings() {
        try {
            localStorage.setItem('amiral:audio', JSON.stringify({
                enabled: this.audio.enabled,
                musicVolume: this.audio.musicVolume,
                sfxVolume: this.audio.sfxVolume,
            }));
        } catch (err) {
            console.warn('Ses ayarları kaydedilemedi', err);
        }
    }

    startBackgroundMusic() {
        if (!this.audio.enabled) return;
        const playPromise = this.audio.background.play();
        if (playPromise && typeof playPromise.catch === 'function') {
            playPromise.catch(() => {
                // Tarayıcı otomatik oynatmayı engelledi: ilk kullanıcı
                // etkileşiminde başlat.
                this.bindAudioUnlock();
            });
        }
    }

    bindAudioUnlock() {
        if (this.audioUnlockBound) return;
        this.audioUnlockBound = true;
        const unlock = () => {
            document.removeEventListener('pointerdown', unlock);
            document.removeEventListener('keydown', unlock);
            if (this.audio.enabled) {
                this.audio.background.play().catch(() => {});
            }
        };
        document.addEventListener('pointerdown', unlock);
        document.addEventListener('keydown', unlock);
    }

    applyAudioVolumes() {
        this.audio.background.volume = (this.audio.musicVolume / 100) * 0.9;
        this.audio.background.muted = !this.audio.enabled;
        this.audio.hit.volume = this.audio.sfxVolume / 100;
        this.audio.miss.volume = this.audio.sfxVolume / 100;
    }

    setMusicVolume(value) {
        this.audio.musicVolume = value;
        if (this.audio.enabled && this.audio.background.paused) {
            this.audio.background.play().catch(() => {});
        }
        this.applyAudioVolumes();
        this.updateVolumeOutputs();
        this.saveAudioSettings();
    }

    setSfxVolume(value) {
        this.audio.sfxVolume = value;
        this.applyAudioVolumes();
        this.updateVolumeOutputs();
        this.saveAudioSettings();
    }

    updateVolumeOutputs() {
        if (this.musicVolumeOutput) this.musicVolumeOutput.textContent = this.audio.musicVolume;
        if (this.sfxVolumeOutput) this.sfxVolumeOutput.textContent = this.audio.sfxVolume;
    }

    toggleAudio() {
        this.audio.enabled = !this.audio.enabled;
        if (this.audio.enabled) {
            this.audio.background.play().catch(() => {});
        } else {
            this.audio.background.pause();
        }
        this.applyAudioVolumes();
        this.updateAudioToggleLabel();
        this.saveAudioSettings();
    }

    updateAudioToggleLabel() {
        if (!this.audioToggleBtn) return;
        this.audioToggleBtn.textContent = this.audio.enabled ? 'Ses: Açık' : 'Ses: Kapalı';
        this.audioToggleBtn.classList.toggle('muted', !this.audio.enabled);
        this.audioToggleBtn.setAttribute('aria-pressed', String(this.audio.enabled));
    }

    playEffect(kind) {
        if (!this.audio.enabled || this.audio.sfxVolume <= 0) return;
        const source = kind === 'hit' ? this.audio.hit : this.audio.miss;
        if (!source) return;
        // Aynı anda birden çok çalabilmek için kısa bir kopya kullan.
        const sound = source.cloneNode();
        sound.volume = this.audio.sfxVolume / 100;
        sound.play().catch(() => {});
    }

    loadFleet() {
        const el = document.getElementById('fleet-data');
        if (el) {
            this.fleet = JSON.parse(el.textContent);
        }
    }

    // ------------------------------------------------------------------
    // Bağlantı
    // ------------------------------------------------------------------
    connectToRoom(roomCode) {
        this.roomCode = roomCode.toUpperCase();
        const storageKey = `amiral:player:${this.roomCode}`;
        this.playerIdentifier = sessionStorage.getItem(storageKey)
            || `guest_${Date.now()}_${Math.floor(Math.random() * 100000)}`;
        sessionStorage.setItem(storageKey, this.playerIdentifier);

        const wsScheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${wsScheme}://${window.location.host}/amiral/ws/game/${this.roomCode}/`;

        this.ws = new WebSocket(wsUrl);

        this.ws.onopen = () => {
            this.ws.send(JSON.stringify({
                type: 'join_player',
                player_identifier: this.playerIdentifier,
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
            this.updateOpponentStatus('disconnected', 'Rakip bağlantıyı kesti');
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
                this.handlePlayerJoined(data);
                break;
            case 'player_ready':
                if (data.player_identifier !== this.playerIdentifier) {
                    this.updateOpponentStatus('connected', 'Rakip hazır!');
                }
                break;
            case 'game_started':
                this.handleGameStarted(data);
                break;
            case 'turn_changed':
                this.currentTurnIdentifier = data.current_turn_identifier;
                this.updateTurnUI();
                break;
            case 'shot_result':
                this.handleShotResult(data);
                break;
            case 'game_finished':
                this.handleGameFinished(data);
                break;
            case 'room_reset':
                this.handleRoomReset();
                break;
            case 'game_abandoned':
                this.showToast(data.message, true);
                this.updateOpponentStatus('disconnected', data.message);
                break;
            case 'error':
                this.showToast(data.message, true);
                break;
            default:
                console.log('Bilinmeyen mesaj tipi:', data.type);
        }
    }

    // ------------------------------------------------------------------
    // Durum uygulama
    // ------------------------------------------------------------------
    applyState(data) {
        this.status = data.status;
        this.gridSize = data.grid_size || this.gridSize;
        this.currentTurnIdentifier = data.current_turn_identifier;
        this.winnerIdentifier = data.winner_identifier;
        this.myShots = data.my_shots || [];
        this.incomingShots = data.incoming_shots || [];
        this.enemyShips = data.enemy_ships || [];

        if (data.my_ships && data.my_ships.length) {
            this.myShips = data.my_ships;
        }

        const players = data.players || [];
        const me = players.find((p) => p.player_identifier === this.playerIdentifier);
        const opponents = players.filter((p) => p.player_identifier !== this.playerIdentifier);

        this.selfReady = !!(me && me.ready);

        if (opponents.length > 0) {
            this.opponentConnected = true;
            const anyReady = opponents.some((p) => p.ready);
            this.updateOpponentStatus('connected', anyReady ? 'Rakip hazır!' : 'Rakip bağlandı');
        } else {
            this.updateOpponentStatus('disconnected', 'Rakibin katılması bekleniyor...');
        }

        if (this.status === 'FINISHED') {
            this.placementSection.classList.add('hidden');
            this.waitingSection.classList.add('hidden');
            this.showGameArea();
            this.showGameOver();
        } else if (this.status === 'IN_PROGRESS') {
            this.placementSection.classList.add('hidden');
            this.waitingSection.classList.add('hidden');
            this.showGameArea();
        } else if (this.selfReady) {
            this.placementSection.classList.add('hidden');
            this.gameArea.classList.add('hidden');
            this.waitingSection.classList.remove('hidden');
            this.updateTurnIndicator('waiting', 'Rakibin yerleştirmesi bekleniyor...');
        } else {
            this.showPlacement();
        }

        this.updateTurnUI();
    }

    showPlacement() {
        this.waitingSection.classList.add('hidden');
        this.gameArea.classList.add('hidden');
        this.placementSection.classList.remove('hidden');
        this.updateTurnIndicator('waiting', 'Gemilerini yerleştir');

        if (!this.placementInitialized) {
            this.placementInitialized = true;
            this.buildPlacementGrid();
            this.buildShipTray();
            this.updateRotateButton();
            this.updatePlacementControls();
        }
    }

    showGameStartedFrom(data) {
        this.status = 'IN_PROGRESS';
        this.currentTurnIdentifier = data.current_turn_identifier;
        this.placementSection.classList.add('hidden');
        this.waitingSection.classList.add('hidden');
        this.showGameArea();
    }

    handlePlayerJoined(data) {
        if (data.player_identifier === this.playerIdentifier) {
            return;
        }
        this.opponentConnected = true;
        this.updateOpponentStatus('connected', 'Rakip bağlandı');
    }

    handleGameStarted(data) {
        this.showGameStartedFrom(data);
        this.updateTurnUI();
    }

    showGameArea() {
        this.gameArea.classList.remove('hidden');
        this.gameArea.classList.add('visible');
        this.renderOwnBoard();
        this.renderEnemyBoard();
    }

    // ------------------------------------------------------------------
    // Yerleştirme
    // ------------------------------------------------------------------
    buildPlacementGrid() {
        this.buildBoard(this.placementGrid, (row, col) => this.onPlacementCellClick(row, col), true);
    }

    buildShipTray() {
        this.shipTray.innerHTML = '';
        this.fleet.forEach((ship) => {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'ship-btn';
            btn.dataset.shipId = ship.id;
            btn.dataset.size = ship.size;

            const label = document.createElement('span');
            label.textContent = `${ship.name} (${ship.size})`;

            const dots = document.createElement('span');
            dots.className = 'ship-dots';
            for (let i = 0; i < ship.size; i += 1) {
                const dot = document.createElement('i');
                dots.appendChild(dot);
            }

            btn.appendChild(label);
            btn.appendChild(dots);
            btn.addEventListener('click', () => this.selectShip(ship.id));
            this.shipTray.appendChild(btn);
        });
        this.refreshTrayState();
    }

    selectShip(shipId) {
        this.selectedShipId = this.selectedShipId === shipId ? null : shipId;
        this.refreshTrayState();
        this.updatePlacementControls();
    }

    isShipPlaced(shipId) {
        return this.placedShips.some((s) => s.id === shipId);
    }

    refreshTrayState() {
        [...this.shipTray.children].forEach((btn) => {
            const id = btn.dataset.shipId;
            btn.classList.toggle('selected', id === this.selectedShipId);
            btn.classList.toggle('placed', this.isShipPlaced(id));
        });
    }

    toggleOrientation() {
        this.orientation = this.orientation === 'h' ? 'v' : 'h';
        this.updateRotateButton();
    }

    updateRotateButton() {
        this.rotateBtn.textContent = this.orientation === 'h' ? 'Yön: Yatay' : 'Yön: Dikey';
    }

    onPlacementCellClick(row, col) {
        if (this.selectedShipId) {
            const result = this.tryPlace(this.selectedShipId, row, col);
            if (result.error) {
                this.showToast(result.error, true);
                return;
            }
            if (this.isShipPlaced(this.selectedShipId)) {
                this.selectedShipId = null;
            }
            this.renderPlacement();
            return;
        }

        // Gemiyi kaldır
        const ship = this.placedShips.find((s) => this.covers(s, row, col));
        if (ship) {
            this.placedShips = this.placedShips.filter((s) => s.id !== ship.id);
            this.renderPlacement();
        }
    }

    covers(ship, row, col) {
        return ship.cells.some(([r, c]) => r === row && c === col);
    }

    computeCells(ship, row, col, orientation) {
        const cells = [];
        for (let i = 0; i < ship.size; i += 1) {
            const r = orientation === 'v' ? row + i : row;
            const c = orientation === 'h' ? col + i : col;
            if (r >= this.gridSize || c >= this.gridSize) {
                return null;
            }
            cells.push([r, c]);
        }
        return cells;
    }

    overlaps(cells, ignoreShipId) {
        const occupied = new Set();
        this.placedShips
            .filter((s) => s.id !== ignoreShipId)
            .forEach((s) => s.cells.forEach(([r, c]) => occupied.add(`${r},${c}`)));
        return cells.some(([r, c]) => occupied.has(`${r},${c}`));
    }

    tryPlace(shipId, row, col) {
        const ship = this.fleet.find((s) => s.id === shipId);
        if (!ship) {
            return { error: 'Gemi bulunamadı.' };
        }

        const cells = this.computeCells(ship, row, col, this.orientation);
        if (!cells) {
            return { error: 'Gemi buraya sığmıyor.' };
        }
        if (this.overlaps(cells, shipId)) {
            return { error: 'Gemiler üst üste binemez.' };
        }

        this.placedShips = this.placedShips.filter((s) => s.id !== shipId);
        this.placedShips.push({
            id: ship.id,
            name: ship.name,
            size: ship.size,
            cells,
        });
        return { ok: true };
    }

    fillRandom() {
        this.placedShips = this.randomBoard();
        this.selectedShipId = null;
        this.renderPlacement();
    }

    clearBoard() {
        this.placedShips = [];
        this.selectedShipId = null;
        this.renderPlacement();
    }

    randomBoard() {
        const ships = [];
        const occupied = new Set();
        const rand = (n) => Math.floor(Math.random() * n);

        for (const ship of this.fleet) {
            let placed = false;
            let guard = 0;
            while (!placed && guard < 1000) {
                guard += 1;
                const horizontal = Math.random() < 0.5;
                let cells;
                if (horizontal) {
                    const row = rand(this.gridSize);
                    const col = rand(this.gridSize - ship.size + 1);
                    cells = Array.from({ length: ship.size }, (_, i) => [row, col + i]);
                } else {
                    const row = rand(this.gridSize - ship.size + 1);
                    const col = rand(this.gridSize);
                    cells = Array.from({ length: ship.size }, (_, i) => [row + i, col]);
                }
                if (cells.some(([r, c]) => occupied.has(`${r},${c}`))) {
                    continue;
                }
                cells.forEach(([r, c]) => occupied.add(`${r},${c}`));
                ships.push({ id: ship.id, name: ship.name, size: ship.size, cells });
                placed = true;
            }
        }
        return ships;
    }

    renderPlacement() {
        this.buildBoard(this.placementGrid, (row, col) => this.onPlacementCellClick(row, col), true);
        this.paintPlacement();
        this.refreshTrayState();
        this.updatePlacementControls();
    }

    paintPlacement() {
        this.placedShips.forEach((ship) => {
            ship.cells.forEach(([r, c]) => {
                const cell = this.cellEl(this.placementGrid, r, c);
                if (!cell) return;
                cell.classList.add('ship', `ship-size-${ship.size}`);
                if (this.selectedShipId === ship.id) {
                    cell.classList.add('moving');
                }
            });
        });
    }

    previewAt(row, col) {
        this.clearPreview();
        if (!this.selectedShipId) return;
        const ship = this.fleet.find((s) => s.id === this.selectedShipId);
        if (!ship) return;

        const cells = this.computeCells(ship, row, col, this.orientation);
        const valid = cells && !this.overlaps(cells, ship.id);
        const anchor = cells || [ [row, col] ];
        anchor.forEach(([r, c]) => {
            const cell = this.cellEl(this.placementGrid, r, c);
            if (cell) {
                cell.classList.add(valid ? 'preview-ok' : 'preview-bad');
            }
        });
    }

    clearPreview() {
        this.placementGrid
            .querySelectorAll('.preview-ok, .preview-bad')
            .forEach((cell) => cell.classList.remove('preview-ok', 'preview-bad'));
    }

    updatePlacementControls() {
        const total = this.fleet.length;
        const placedCount = this.placedShips.length;
        this.confirmBtn.disabled = placedCount < total;
        if (placedCount < total) {
            this.placementHint.textContent = `${placedCount}/${total} gemi yerleştirildi.`;
        } else {
            this.placementHint.textContent = 'Hazırsın! Yerleştirmeyi bitir.';
        }
    }

    confirmPlacement() {
        if (this.placedShips.length < this.fleet.length) {
            this.showToast('Önce tüm gemileri yerleştir.', true);
            return;
        }
        const ships = this.placedShips.map((s) => ({
            id: s.id,
            cells: s.cells,
        }));
        this.myShips = this.placedShips.map((s) => ({
            id: s.id,
            name: s.name,
            size: s.size,
            cells: s.cells,
        }));
        this.send({
            type: 'place_ships',
            player_identifier: this.playerIdentifier,
            ships,
        });
        this.selfReady = true;
        this.placementSection.classList.add('hidden');
        this.waitingSection.classList.remove('hidden');
        this.updateTurnIndicator('waiting', 'Rakibin yerleştirmesi bekleniyor...');
    }

    // ------------------------------------------------------------------
    // Tahta çizimi
    // ------------------------------------------------------------------
    buildBoard(container, onClick, placing) {
        container.innerHTML = '';
        container.classList.toggle('placing', !!placing);
        container.style.gridTemplateColumns =
            `var(--board-label-w, 1.4rem) repeat(${this.gridSize}, 1fr)`;

        const corner = document.createElement('div');
        corner.className = 'board-corner';
        container.appendChild(corner);

        for (let c = 0; c < this.gridSize; c += 1) {
            const label = document.createElement('div');
            label.className = 'col-label';
            label.textContent = this.columns[c] || c;
            container.appendChild(label);
        }

        for (let r = 0; r < this.gridSize; r += 1) {
            const rowLabel = document.createElement('div');
            rowLabel.className = 'row-label';
            rowLabel.textContent = r + 1;
            container.appendChild(rowLabel);

            for (let c = 0; c < this.gridSize; c += 1) {
                const cell = document.createElement('button');
                cell.type = 'button';
                cell.className = 'cell';
                cell.dataset.row = r;
                cell.dataset.col = c;
                if (onClick) {
                    cell.addEventListener('click', () => onClick(r, c));
                }
                container.appendChild(cell);
            }
        }
    }

    cellEl(container, row, col) {
        return container.querySelector(`.cell[data-row="${row}"][data-col="${col}"]`);
    }

    buildShipMap(ships) {
        const map = new Map();
        (ships || []).forEach((ship) => {
            (ship.cells || []).forEach(([r, c]) => {
                map.set(`${r},${c}`, ship);
            });
        });
        return map;
    }

    shipsSunk(ships, shots) {
        const shotSet = new Set(shots.map((s) => `${s.row},${s.col}`));
        const sunk = new Set();
        (ships || []).forEach((ship) => {
            const cells = (ship.cells || []).map(([r, c]) => `${r},${c}`);
            if (cells.length && cells.every((key) => shotSet.has(key))) {
                sunk.add(ship.id);
            }
        });
        return sunk;
    }

    renderOwnBoard() {
        if (!this.ownGrid) return;
        this.buildBoard(this.ownGrid, null, false);

        const shipMap = this.buildShipMap(this.myShips);
        const shotMap = new Map(this.incomingShots.map((s) => [`${s.row},${s.col}`, s]));
        const sunkIds = this.shipsSunk(this.myShips, this.incomingShots);

        for (let r = 0; r < this.gridSize; r += 1) {
            for (let c = 0; c < this.gridSize; c += 1) {
                const cell = this.cellEl(this.ownGrid, r, c);
                if (!cell) continue;
                const key = `${r},${c}`;
                const ship = shipMap.get(key);
                if (ship) {
                    cell.classList.add('ship', `ship-size-${ship.size}`);
                    if (sunkIds.has(ship.id)) {
                        cell.classList.add('sunk');
                    }
                }
                const shot = shotMap.get(key);
                if (shot) {
                    cell.classList.add('shot', shot.hit ? 'hit' : 'miss');
                }
            }
        }
    }

    renderEnemyBoard() {
        if (!this.enemyGrid) return;
        this.buildBoard(this.enemyGrid, (row, col) => this.onEnemyCellClick(row, col), false);

        const myTurn = this.status === 'IN_PROGRESS'
            && !this.gameOver
            && this.currentTurnIdentifier === this.playerIdentifier;
        this.enemyGrid.classList.toggle('playable', myTurn);

        const shotMap = new Map(this.myShots.map((s) => [`${s.row},${s.col}`, s]));
        const enemyShipMap = this.buildShipMap(this.enemyShips);
        const sunkIds = this.shipsSunk(this.enemyShips, this.myShots);

        for (let r = 0; r < this.gridSize; r += 1) {
            for (let c = 0; c < this.gridSize; c += 1) {
                const cell = this.cellEl(this.enemyGrid, r, c);
                if (!cell) continue;
                const key = `${r},${c}`;

                if (this.enemyShips.length) {
                    const ship = enemyShipMap.get(key);
                    if (ship) {
                        cell.classList.add('ship', `ship-size-${ship.size}`);
                        if (sunkIds.has(ship.id)) {
                            cell.classList.add('sunk');
                        }
                    }
                }

                const shot = shotMap.get(key);
                if (shot) {
                    cell.classList.add('shot', shot.hit ? 'hit' : 'miss');
                }
            }
        }

        if (this.enemyNote) {
            this.enemyNote.textContent = myTurn ? 'Ateş etmek için tıkla' : 'Sıra rakipte';
        }
    }

    onEnemyCellClick(row, col) {
        if (this.gameOver || this.status !== 'IN_PROGRESS') {
            return;
        }
        if (this.currentTurnIdentifier !== this.playerIdentifier) {
            this.showToast('Sıra sende değil.', true);
            return;
        }
        if (this.myShots.some((s) => s.row === row && s.col === col)) {
            return;
        }
        this.send({
            type: 'fire',
            player_identifier: this.playerIdentifier,
            row,
            col,
        });
    }

    // ------------------------------------------------------------------
    // Olay işleyicileri
    // ------------------------------------------------------------------
    handleShotResult(data) {
        const entry = { row: data.row, col: data.col, hit: data.hit };
        if (data.shooter_identifier === this.playerIdentifier) {
            this.myShots.push(entry);
            if (data.hit) {
                const label = data.sunk
                    ? `Vuruş! ${data.sunk} battı.`
                    : 'Vuruş! Tekrar ateş edebilirsin.';
                this.showToast(label);
                this.lastActivity = `Vurduğun kare: ${this.label(data.row, data.col)}`;
            } else {
                this.showToast('Iskaladın.');
                this.lastActivity = `Iskaladığın kare: ${this.label(data.row, data.col)}`;
            }
        } else {
            this.incomingShots.push(entry);
            this.opponentActivity.textContent = data.hit
                ? `Rakip seni vurdu: ${this.label(data.row, data.col)}`
                : `Rakip ıskaladı: ${this.label(data.row, data.col)}`;
        }

        this.renderOwnBoard();
        this.renderEnemyBoard();

        // Vuruş / karavana ses efekti.
        this.playEffect(data.hit ? 'hit' : 'miss');

        if (data.shooter_identifier === this.playerIdentifier && data.hit) {
            const cell = this.cellEl(this.enemyGrid, data.row, data.col);
            if (cell) {
                cell.classList.add('boom');
            }
        }
    }

    handleGameFinished(data) {
        this.gameOver = true;
        this.status = 'FINISHED';
        this.winnerIdentifier = data.winner_identifier;
        this.enemyShips = data.reveal ? this.extractEnemyShips(data.reveal) : this.enemyShips;
        this.renderOwnBoard();
        this.renderEnemyBoard();
        this.showGameOver();
        this.disableBoard();
    }

    extractEnemyShips(reveal) {
        const key = Object.keys(reveal || {}).find((k) => k !== this.playerIdentifier);
        if (key) {
            return reveal[key] || [];
        }
        return this.enemyShips;
    }

    handleRoomReset() {
        this.gameOver = false;
        this.status = 'PLACING';
        this.winnerIdentifier = null;
        this.currentTurnIdentifier = null;
        this.selfReady = false;
        this.placedShips = [];
        this.selectedShipId = null;
        this.myShips = [];
        this.myShots = [];
        this.incomingShots = [];
        this.enemyShips = [];
        this.placementInitialized = false;

        this.gameOverEl.classList.add('hidden');
        this.gameArea.classList.add('hidden');
        this.gameArea.classList.remove('visible');
        this.showPlacement();
        this.updateTurnIndicator('waiting', 'Gemilerini yerleştir');
    }

    showGameOver() {
        this.gameOverEl.classList.remove('hidden');
        const won = this.winnerIdentifier === this.playerIdentifier;
        this.gameOverMessage.textContent = won ? 'KAZANDIN!' : 'KAYBETTİN!';
        this.gameOverMessage.className = won ? 'win' : 'lose';
        this.gameOverDetail.textContent = won
            ? 'Rakibin tüm filosu battı!'
            : 'Tüm gemilerin batırıldı.';
    }

    disableBoard() {
        if (this.enemyGrid) {
            this.enemyGrid.classList.remove('playable');
        }
    }

    restartGame() {
        this.send({
            type: 'restart_game',
            player_identifier: this.playerIdentifier,
        });
    }

    // ------------------------------------------------------------------
    // Arayüz yardımcıları
    // ------------------------------------------------------------------
    updateTurnUI() {
        if (this.status === 'IN_PROGRESS' && !this.gameOver) {
            const myTurn = this.currentTurnIdentifier === this.playerIdentifier;
            const text = myTurn ? 'SIRA SENDE' : 'RAKİBİN SIRASI';
            this.updateTurnIndicator(myTurn ? 'your-turn' : 'opponent-turn', text);
            if (this.mobileTurn) {
                this.mobileTurn.textContent = myTurn ? 'Sıra sende' : 'Sıra rakipte';
                this.mobileTurn.className = `mobile-turn ${myTurn ? 'your-turn' : 'opponent-turn'}`;
            }
            this.renderEnemyBoard();
        }
    }

    updateTurnIndicator(type, text) {
        this.turnIndicator.className = `turn-indicator ${type}`;
        this.turnIndicator.textContent = text;
        if (this.mobileTurn) {
            this.mobileTurn.textContent = text;
            this.mobileTurn.className = `mobile-turn ${type}`;
        }
    }

    updateOpponentStatus(type, text) {
        this.opponentStatus.className = `opponent-status ${type}`;
        this.opponentStatus.textContent = text;
    }

    label(row, col) {
        return `${this.columns[col] || col}${row + 1}`;
    }

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
    const game = new BattleshipGame();
    game.loadFleet();
    window.game = game;

    const roomCode = document.body.dataset.roomCode;
    if (roomCode) {
        game.connectToRoom(roomCode);
    }
});
