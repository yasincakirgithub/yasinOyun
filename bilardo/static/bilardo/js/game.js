/* ==========================================================================
   Bilardo oyun ekranı — canvas, fizik, kurallar, online oda ve bot
   ========================================================================== */
(function () {
    'use strict';

    const P = window.BilardoPhysics;
    const RULES = window.BilardoRules;
    const CONST = P.CONST;
    const body = document.body;

    const isOnline = body.dataset.online === '1';
    const isLocal = body.dataset.local === '1';
    const isBot = body.dataset.bot === '1';
    const botLevel = body.dataset.botLevel || 'normal';
    const gameMode = body.dataset.mode || 'three_cushion';
    const gameTarget = Number(body.dataset.target) || 10;
    const roomCode = (body.dataset.roomCode || '').toUpperCase();
    const defaultCue = body.dataset.defaultCue || 'klasik';

    const cues = JSON.parse(document.getElementById('bilardo-cues').textContent);
    const cueById = Object.fromEntries(cues.map((cue) => [cue.id, cue]));

    const canvas = document.getElementById('table-canvas');
    const ctx = canvas.getContext('2d');
    const canvasWrap = document.getElementById('canvas-wrap');

    const els = {
        waitingOverlay: document.getElementById('waiting-overlay'),
        connectionOverlay: document.getElementById('connection-overlay'),
        connectionMessage: document.getElementById('connection-message'),
        connectionStatus: document.getElementById('connection-status'),
        waitingRoomCode: document.getElementById('waiting-room-code'),
        playerCards: [document.getElementById('player-card-0'), document.getElementById('player-card-1')],
        playerNames: [document.getElementById('player-name-0'), document.getElementById('player-name-1')],
        playerMetas: [document.getElementById('player-meta-0'), document.getElementById('player-meta-1')],
        playerScores: [document.getElementById('player-score-0'), document.getElementById('player-score-1')],
        turnLabel: document.getElementById('turn-label'),
        targetLabel: document.getElementById('target-label'),
        breakLabel: document.getElementById('break-label'),
        powerFill: document.getElementById('power-fill'),
        powerValue: document.getElementById('power-value'),
        shootBtn: document.getElementById('shoot-btn'),
        tableHint: document.getElementById('table-hint'),
        spinWidget: document.getElementById('spin-widget'),
        spinBall: document.getElementById('spin-ball'),
        spinDot: document.getElementById('spin-dot'),
        spinX: document.getElementById('spin-x'),
        spinY: document.getElementById('spin-y'),
        cueName: document.getElementById('cue-name'),
        cueChip: document.getElementById('cue-chip'),
        cuePreview: document.getElementById('cue-preview'),
        cueStats: document.getElementById('cue-stats'),
        shotHistory: document.getElementById('shot-history'),
        shotToast: document.getElementById('shot-toast'),
        emoteLog: document.getElementById('emote-log'),
        guideToggle: document.getElementById('guide-toggle'),
        soundToggle: document.getElementById('sound-toggle'),
        gameOverModal: document.getElementById('game-over-modal'),
        gameOverKicker: document.getElementById('game-over-kicker'),
        gameOverTitle: document.getElementById('game-over-title'),
        gameOverMessage: document.getElementById('game-over-message'),
        gameOverScore: document.getElementById('game-over-score'),
        rematchBtn: document.getElementById('rematch-btn'),
        helpModal: document.getElementById('help-modal'),
        toastContainer: document.getElementById('toast-container'),
    };

    let state = null;
    let world = null;
    let players = [];
    let mySeat = isLocal ? 0 : null;
    let myIdentifier = null;
    let myCue = defaultCue;

    let angle = 0;
    let power = 0;
    let charging = false;
    let chargeStartedAt = 0;
    let spinX = 0;
    let spinY = 0;
    let cuePlaced = false;
    let pointer = { x: CONST.W / 2, y: CONST.H / 2, inside: false };

    let shotInProgress = false;
    let shotStartState = null;
    let shotShooterSeat = null;
    let pendingShotId = null;
    let pendingState = null;
    // Kendi vuruşumuzun sunucudan gelen yayını, yerel simülasyon bittikten
    // sonra ulaşabilir. Bu kimlikleri saklayıp vuruşu ikinci kez oynatmayız.
    const finishedShotIds = new Set();

    let socket = null;
    let reconnectTimer = null;
    let intentionalClose = false;
    let joined = false;
    let pingTimer = null;
    let botTimer = null;

    let layout = { width: 264, height: 144, scale: 1, dpr: 1 };
    let accumulator = 0;
    let lastFrame = 0;
    let lastBallSound = 0;
    let lastCushionSound = 0;
    let toastTimer = null;

    let soundEnabled = localStorage.getItem('bilardo:sound') !== 'off';
    let guideEnabled = localStorage.getItem('bilardo:guide') !== 'off';
    let audioCtx = null;

    const emoteMessages = [];

    // ------------------------------------------------------------------
    // Yardımcılar
    // ------------------------------------------------------------------
    function seatName(seat) {
        const player = players.find((item) => item.seat === seat);
        if (player && player.name) return player.name;
        if (isBot && seat === 1) return 'Bilardo Botu';
        return seat === 0 ? 'Oyuncu 1' : 'Oyuncu 2';
    }

    function currentCue() {
        return cueById[myCue] || cues[0];
    }

    function uuid() {
        if (window.crypto && typeof window.crypto.randomUUID === 'function') {
            return window.crypto.randomUUID();
        }
        return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
            const value = Math.random() * 16 | 0;
            const digit = char === 'x' ? value : (value & 0x3 | 0x8);
            return digit.toString(16);
        });
    }

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function showToast(message, type) {
        if (!els.toastContainer) return;
        const toast = document.createElement('div');
        toast.className = 'bilardo-toast' + (type ? ' is-' + type : '');
        toast.textContent = message;
        els.toastContainer.appendChild(toast);
        window.setTimeout(() => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateY(8px)';
            toast.style.transition = 'opacity .2s ease, transform .2s ease';
            window.setTimeout(() => toast.remove(), 220);
        }, 3400);
    }

    function showShotToast(message, type) {
        if (!els.shotToast) return;
        els.shotToast.textContent = message;
        els.shotToast.className = 'shot-toast is-visible' + (type ? ' is-' + type : '');
        window.clearTimeout(toastTimer);
        toastTimer = window.setTimeout(() => {
            els.shotToast.classList.remove('is-visible');
        }, 3200);
    }

    function setConnectionStatus(text, kind) {
        if (!els.connectionStatus) return;
        const label = els.connectionStatus.querySelector('span');
        if (label) label.textContent = text;
        els.connectionStatus.classList.toggle('is-online', kind === 'online');
        els.connectionStatus.classList.toggle('is-offline', kind === 'offline');
    }

    function showConnectionOverlay(message) {
        if (!els.connectionOverlay) return;
        if (els.connectionMessage) els.connectionMessage.textContent = message;
        els.connectionOverlay.classList.remove('hidden');
    }

    function hideConnectionOverlay() {
        if (els.connectionOverlay) els.connectionOverlay.classList.add('hidden');
    }

    function updateWaitingOverlay() {
        if (!els.waitingOverlay) return;
        const waiting = isOnline && (!joined || !state || state.winner !== null ? false : players.length < 2);
        els.waitingOverlay.classList.toggle('hidden', !waiting);
    }

    function placementNeeded() {
        return !!state && !!state.ball_in_hand && !cuePlaced;
    }

    function canShoot() {
        if (!state || state.winner !== null || shotInProgress) return false;
        if (isOnline && mySeat === null) return false;
        if (isOnline && state.turn !== mySeat) return false;
        if (isBot && state.turn === 1) return false;
        if (placementNeeded()) return false;
        return true;
    }

    function isMyTurn() {
        if (isLocal) return !isBot || state.turn === 0;
        return state.turn === mySeat;
    }

    // ------------------------------------------------------------------
    // Canvas ölçüleri
    // ------------------------------------------------------------------
    function resizeCanvas() {
        const rect = canvas.getBoundingClientRect();
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const width = Math.max(1, Math.round(rect.width * dpr));
        const height = Math.max(1, Math.round(rect.height * dpr));
        if (canvas.width !== width || canvas.height !== height) {
            canvas.width = width;
            canvas.height = height;
        }
        layout = {
            width: rect.width,
            height: rect.height,
            scale: rect.width / (CONST.W + CONST.RAIL * 2),
            dpr,
        };
    }

    function eventToWorld(event) {
        const rect = canvas.getBoundingClientRect();
        const x = ((event.clientX - rect.left) / rect.width) * (CONST.W + CONST.RAIL * 2) - CONST.RAIL;
        const y = ((event.clientY - rect.top) / rect.height) * (CONST.H + CONST.RAIL * 2) - CONST.RAIL;
        return { x, y };
    }

    function insideTable(x, y) {
        return x >= CONST.R && x <= CONST.W - CONST.R && y >= CONST.R && y <= CONST.H - CONST.R;
    }

    function canPlaceCueAt(x, y) {
        if (!state || !insideTable(x, y)) return false;
        const balls = state.balls || [];
        for (let i = 0; i < balls.length; i += 1) {
            const ball = balls[i];
            if (ball.id === 0 || ball.pocketed) continue;
            const dx = ball.x - x;
            const dy = ball.y - y;
            if (dx * dx + dy * dy < (CONST.R * 2.08) * (CONST.R * 2.08)) return false;
        }
        return true;
    }

    // ------------------------------------------------------------------
    // Durum yönetimi
    // ------------------------------------------------------------------
    function setState(nextState, options) {
        const opts = options || {};
        state = nextState;
        world = new P.World(state, {
            pockets: state.mode !== 'three_cushion',
            onEvent: handleSoundEvent,
        });
        if (!opts.keepPlacement) cuePlaced = false;
        if (state.ball_in_hand) cuePlaced = false;
        updateUI();
        updateWaitingOverlay();
        if (state.winner !== null && state.winner !== undefined) {
            showGameOver();
        }
    }

    function updateUI() {
        if (!state) return;
        updatePlayersUI();
        updateScoreboard();
        updateCueUI();
        updatePowerUI();
        updateHistory();
        updateControls();
        updateWaitingOverlay();
    }

    function updatePlayersUI() {
        for (let seat = 0; seat < 2; seat += 1) {
            const nameEl = els.playerNames[seat];
            if (!nameEl) continue;
            nameEl.textContent = seatName(seat);
        }
    }

    function updateScoreboard() {
        const modeName = {
            three_cushion: '3 Bant',
            eight_ball: '8 Top',
            nine_ball: '9 Top',
            straight: 'Düz Bilardo',
        }[state.mode] || 'Bilardo';

        if (els.targetLabel) {
            if (state.mode === 'three_cushion' || state.mode === 'straight') {
                els.targetLabel.textContent = modeName + ' · Hedef ' + state.target + ' sayı';
            } else {
                els.targetLabel.textContent = modeName + ' · Hedef ' + (state.mode === 'eight_ball' ? '8 top' : '9 top');
            }
        }

        for (let seat = 0; seat < 2; seat += 1) {
            const card = els.playerCards[seat];
            const meta = els.playerMetas[seat];
            const score = els.playerScores[seat];
            if (!card) continue;

            const isTurn = state.turn === seat && state.winner === null;
            card.classList.toggle('is-active', isTurn);
            card.classList.toggle('is-winner', state.winner === seat);

            const points = state.scores ? state.scores[seat] || 0 : 0;
            score.textContent = String(points);

            const parts = [];
            if (state.winner === seat) {
                parts.push('Kazandı');
            } else if (state.winner !== null) {
                parts.push('Oyun bitti');
            } else if (isTurn) {
                parts.push(isOnline ? (seat === mySeat ? 'Sıra sende' : 'Sıra onda') : 'Sıra sende');
            } else {
                parts.push('Bekliyor');
            }

            if (state.mode === 'eight_ball' && state.groups) {
                const group = state.groups[seat];
                if (group) {
                    const remaining = RULES.remainingGroup(state.balls, group);
                    parts.push((group === 'solids' ? 'Düz' : 'Çizgili') + ' · ' + remaining + ' top');
                } else {
                    parts.push('Grup açık');
                }
            } else if (state.mode === 'nine_ball') {
                const remaining = state.balls.filter((ball) => !ball.pocketed && ball.id !== 0).length;
                parts.push(remaining + ' top kaldı');
            } else {
                parts.push(points + '/' + state.target);
            }

            if (meta) meta.textContent = parts.join(' · ');
        }

        if (els.turnLabel) {
            if (state.winner !== null) {
                els.turnLabel.textContent = 'Oyun bitti';
            } else if (isOnline && players.length < 2) {
                els.turnLabel.textContent = 'Rakip bekleniyor';
            } else {
                els.turnLabel.textContent = 'Sıra: ' + seatName(state.turn);
            }
        }

        if (els.breakLabel) {
            els.breakLabel.textContent = state.break ? 'İlk vuruş' : (state.shot_count || 0) + '. vuruş';
        }
    }

    function updateCueUI() {
        const cue = currentCue();
        if (!cue) return;
        if (els.cueName) els.cueName.textContent = cue.name;
        if (els.cueChip) els.cueChip.textContent = cue.subtitle;
        if (els.cuePreview) {
            els.cuePreview.style.setProperty('--cue-color', cue.color);
            els.cuePreview.style.setProperty('--cue-accent', cue.accent);
        }
        if (els.cueStats) {
            els.cueStats.innerHTML = '';
            [
                ['Güç', cue.power],
                ['Falso', cue.spin],
                ['Kontrol', cue.control],
            ].forEach(([label, value]) => {
                const row = document.createElement('span');
                const em = document.createElement('em');
                em.textContent = label;
                const bar = document.createElement('i');
                bar.style.setProperty('--v', value);
                row.appendChild(em);
                row.appendChild(bar);
                els.cueStats.appendChild(row);
            });
        }
    }

    function updatePowerUI() {
        const percent = Math.round(power * 100);
        if (els.powerFill) els.powerFill.style.width = percent + '%';
        if (els.powerValue) els.powerValue.textContent = percent + '%';
    }

    function updateHistory() {
        if (!els.shotHistory) return;
        els.shotHistory.innerHTML = '';
        const history = (state && Array.isArray(state.history)) ? state.history.slice(-12).reverse() : [];
        if (!history.length) {
            const empty = document.createElement('li');
            empty.className = 'history-empty';
            empty.textContent = 'Henüz vuruş yok.';
            els.shotHistory.appendChild(empty);
            return;
        }
        history.forEach((entry) => {
            const item = document.createElement('li');
            if (entry.foul) item.classList.add('is-foul');
            const strong = document.createElement('strong');
            strong.textContent = seatName(entry.seat) + ': ';
            item.appendChild(strong);
            item.appendChild(document.createTextNode(entry.message || ''));
            els.shotHistory.appendChild(item);
        });
    }

    function updateControls() {
        const enabled = canShoot();
        if (els.shootBtn) {
            els.shootBtn.disabled = !enabled;
            if (state && state.winner !== null) {
                els.shootBtn.textContent = 'OYUN BİTTİ';
            } else if (shotInProgress) {
                els.shootBtn.textContent = 'VURUŞ...';
            } else if (isOnline && state && state.turn !== mySeat) {
                els.shootBtn.textContent = 'RAKİBİN SIRASI';
            } else if (isBot && state && state.turn === 1) {
                els.shootBtn.textContent = 'BOT DÜŞÜNÜYOR';
            } else if (placementNeeded()) {
                els.shootBtn.textContent = 'TOPU YERLEŞTİR';
            } else {
                els.shootBtn.textContent = 'BASILI TUT & BIRAK';
            }
        }

        if (els.tableHint) {
            if (!state) {
                els.tableHint.textContent = 'Masa hazırlanıyor...';
            } else if (state.winner !== null) {
                els.tableHint.textContent = 'Oyun bitti. Yeni oyun için Yeniden Oyna butonuna bas.';
            } else if (isOnline && players.length < 2) {
                els.tableHint.textContent = 'Rakip bekleniyor. Oda kodunu paylaş.';
            } else if (isOnline && state.turn !== mySeat) {
                els.tableHint.textContent = 'Rakibin sırası. Vuruşunu izle.';
            } else if (isBot && state.turn === 1) {
                els.tableHint.textContent = 'Bot nişan alıyor...';
            } else if (placementNeeded()) {
                els.tableHint.textContent = 'İsteka topu elinde: masada uygun bir yere tıkla.';
            } else if (charging) {
                els.tableHint.textContent = 'Güç doluyor... Bırakınca vurursun.';
            } else {
                els.tableHint.textContent = 'Nişan almak için fareyi masada gezdir. Vuruş gücü için basılı tut, bırakınca vurursun.';
            }
        }

        canvasWrap.classList.toggle('is-placing', placementNeeded());
        canvasWrap.classList.toggle('is-charging', charging);
    }

    // ------------------------------------------------------------------
    // Falso widget
    // ------------------------------------------------------------------
    function updateSpinUI() {
        if (els.spinDot) {
            els.spinDot.style.transform = 'translate(calc(-50% + ' + (spinX * 46) + '%), calc(-50% + ' + (-spinY * 46) + '%))';
        }
        if (els.spinX) els.spinX.textContent = String(Math.round(spinX * 100));
        if (els.spinY) els.spinY.textContent = String(Math.round(spinY * 100));
        if (els.spinWidget) {
            els.spinWidget.setAttribute('aria-valuenow', String(Math.round(spinY * 100)));
        }
    }

    function setSpinFromPointer(event) {
        const rect = els.spinBall.getBoundingClientRect();
        let nx = (event.clientX - rect.left - rect.width / 2) / (rect.width / 2);
        let ny = (event.clientY - rect.top - rect.height / 2) / (rect.height / 2);
        const len = Math.hypot(nx, ny);
        const max = 0.92;
        if (len > max) {
            nx = (nx / len) * max;
            ny = (ny / len) * max;
        }
        spinX = Math.max(-1, Math.min(1, nx));
        spinY = Math.max(-1, Math.min(1, -ny));
        updateSpinUI();
    }

    function resetSpin() {
        spinX = 0;
        spinY = 0;
        updateSpinUI();
    }

    // ------------------------------------------------------------------
    // Vuruş
    // ------------------------------------------------------------------
    function buildShotParams() {
        const cue = currentCue();
        const maxSpeed = 500 + cue.power * 300;
        const speed = maxSpeed * Math.max(0.06, power);
        const vx = Math.cos(angle) * speed;
        const vy = Math.sin(angle) * speed;
        const params = {
            angle,
            power: Math.max(0.06, power),
            spinX,
            spinY,
            vx,
            vy,
            speed,
            cueId: cue.id,
            cueStats: {
                power: cue.power,
                spin: cue.spin,
                control: cue.control,
            },
        };
        if (state.ball_in_hand && cuePlaced) {
            const cueBall = world.getCueBall();
            params.cueX = cueBall.x;
            params.cueY = cueBall.y;
        }
        return params;
    }

    function startCharge() {
        if (!canShoot() || charging) return;
        ensureAudio();
        charging = true;
        chargeStartedAt = performance.now();
        power = 0;
        updatePowerUI();
        updateControls();
    }

    function releaseShot() {
        if (!charging) return;
        charging = false;
        const finalPower = Math.max(0.07, power);
        power = finalPower;
        updatePowerUI();
        updateControls();

        const params = buildShotParams();
        power = 0;
        updatePowerUI();

        playCueSound(finalPower);

        if (isOnline) {
            const shotId = uuid();
            pendingShotId = shotId;
            send({ type: 'shoot', params, shot_id: shotId });
            beginSimulation(params, mySeat, shotId);
        } else {
            beginSimulation(params, state.turn, null);
        }
    }

    function beginSimulation(params, shooterSeat, shotId) {
        const preState = clone(state);
        if (params.cueX !== undefined && params.cueY !== undefined) {
            const cueBall = preState.balls.find((ball) => ball.id === 0);
            if (cueBall) {
                cueBall.x = params.cueX;
                cueBall.y = params.cueY;
                cueBall.pocketed = false;
            }
        }
        shotStartState = preState;
        shotShooterSeat = shooterSeat;
        shotInProgress = true;
        pendingShotId = shotId || pendingShotId;
        cuePlaced = false;
        accumulator = 0;

        world = new P.World(preState, {
            pockets: preState.mode !== 'three_cushion',
            onEvent: handleSoundEvent,
        });
        if (!world.shoot(params)) {
            shotInProgress = false;
            shotStartState = null;
            shotShooterSeat = null;
            pendingShotId = null;
            showToast('Vuruş başlatılamadı.', 'error');
            updateControls();
            return;
        }
        updateControls();
        updateWaitingOverlay();
    }

    function finishSimulation() {
        if (!shotStartState) {
            shotInProgress = false;
            return;
        }
        const nextState = RULES.evaluateShot({
            state: shotStartState,
            world,
            shooterSeat: shotShooterSeat,
            params: world.events.shot || {},
        });

        const result = nextState.last_shot || {};
        const wasMine = isOnline ? shotShooterSeat === mySeat : true;
        const shotId = pendingShotId;
        shotInProgress = false;

        if (isOnline && wasMine) {
            send({
                type: 'settle',
                shot_id: shotId,
                state: nextState,
                result: {
                    message: result.message || nextState.message,
                    foul: !!result.foul,
                },
            });
            if (shotId) {
                finishedShotIds.add(shotId);
                if (finishedShotIds.size > 20) {
                    finishedShotIds.delete(finishedShotIds.values().next().value);
                }
            }
            pendingShotId = null;
        }

        let finalState = nextState;
        if (pendingState) {
            finalState = pendingState;
            pendingState = null;
        }

        shotStartState = null;
        shotShooterSeat = null;
        setState(finalState);
        showShotToast(result.message || nextState.message, result.foul ? 'foul' : (nextState.winner !== null ? 'success' : ''));

        if (finalState.winner !== null && finalState.winner !== undefined) {
            playWinSound();
        } else if (isBot && finalState.turn === 1) {
            scheduleBotShot();
        }
    }

    // ------------------------------------------------------------------
    // Yerleştirme
    // ------------------------------------------------------------------
    function placeCueBallAt(x, y) {
        if (!canPlaceCueAt(x, y)) {
            showToast('Buraya yerleştiremezsin: başka bir topla çakışıyor.', 'error');
            return false;
        }
        const cueBall = world.getCueBall();
        if (!cueBall) return false;
        cueBall.x = x;
        cueBall.y = y;
        cueBall.pocketed = false;
        const stateCue = state.balls.find((ball) => ball.id === 0);
        if (stateCue) {
            stateCue.x = x;
            stateCue.y = y;
            stateCue.pocketed = false;
        }
        cuePlaced = true;
        if (isLocal) {
            state.ball_in_hand = false;
        }
        updateControls();
        showToast('Top yerleştirildi. Nişan alıp vurabilirsin.', 'success');
        return true;
    }

    // ------------------------------------------------------------------
    // Bot
    // ------------------------------------------------------------------
    function scheduleBotShot() {
        window.clearTimeout(botTimer);
        botTimer = window.setTimeout(() => {
            if (!state || state.winner !== null || shotInProgress || state.turn !== 1) return;
            botShoot();
        }, 750);
    }

    function lineClear(a, b, balls, excludeIds) {
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const len2 = dx * dx + dy * dy;
        if (len2 < 0.001) return true;
        for (let i = 0; i < balls.length; i += 1) {
            const ball = balls[i];
            if (ball.pocketed || excludeIds.includes(ball.id)) continue;
            let t = ((ball.x - a.x) * dx + (ball.y - a.y) * dy) / len2;
            t = Math.max(0, Math.min(1, t));
            const px = a.x + dx * t;
            const py = a.y + dy * t;
            const ddx = ball.x - px;
            const ddy = ball.y - py;
            if (ddx * ddx + ddy * ddy < (CONST.R * 2.02) * (CONST.R * 2.02)) return false;
        }
        return true;
    }

    function botCandidates() {
        const balls = state.balls.filter((ball) => !ball.pocketed && ball.id !== 0);
        if (state.mode === 'nine_ball') {
            const lowest = RULES.lowestBall(state.balls);
            return lowest ? [lowest] : balls;
        }
        if (state.mode === 'eight_ball') {
            const group = state.groups ? state.groups[1] : null;
            if (group) {
                const remaining = balls.filter((ball) => RULES.groupOf(ball) === group);
                if (remaining.length) return remaining;
                return balls.filter((ball) => ball.id === 8);
            }
            return balls.filter((ball) => ball.id !== 8);
        }
        return balls;
    }

    function botShoot() {
        if (!state || state.winner !== null || shotInProgress) return;
        const cueBall = state.balls.find((ball) => ball.id === 0);
        if (!cueBall) return;

        let cueX = cueBall.x;
        let cueY = cueBall.y;
        let ballInHand = false;
        if (state.ball_in_hand) {
            const spot = RULES.freeSpot(state.balls, CONST.HEAD_X, CONST.CENTER_Y, 0);
            cueX = spot.x;
            cueY = spot.y;
            ballInHand = true;
        }

        const candidates = botCandidates();
        let best = null;

        if (state.mode !== 'three_cushion') {
            candidates.forEach((target) => {
                CONST.POCKETS.forEach((pocket) => {
                    const dx = pocket.x - target.x;
                    const dy = pocket.y - target.y;
                    const dist = Math.hypot(dx, dy) || 1;
                    const ghost = {
                        x: target.x - (dx / dist) * CONST.R * 2,
                        y: target.y - (dy / dist) * CONST.R * 2,
                    };
                    const cuePoint = { x: cueX, y: cueY };
                    if (!lineClear(cuePoint, ghost, state.balls, [0, target.id])) return;
                    if (!lineClear(target, pocket, state.balls, [target.id])) return;
                    const cueDist = Math.hypot(ghost.x - cueX, ghost.y - cueY);
                    const pocketDist = dist;
                    const score = cueDist + pocketDist * 0.55;
                    if (!best || score < best.score) {
                        best = { target, ghost, score, cueDist, pocketDist };
                    }
                });
            });
        }

        let aimX;
        let aimY;
        if (best) {
            aimX = best.ghost.x;
            aimY = best.ghost.y;
        } else if (candidates.length) {
            const target = candidates[Math.floor(Math.random() * candidates.length)];
            aimX = target.x;
            aimY = target.y;
        } else {
            aimX = CONST.W / 2;
            aimY = CONST.H / 2;
        }

        const baseAngle = Math.atan2(aimY - cueY, aimX - cueX);
        const errorByLevel = { kolay: 0.085, normal: 0.035, zor: 0.012 };
        const error = (Math.random() * 2 - 1) * (errorByLevel[botLevel] || 0.035);
        const shotAngle = baseAngle + error;

        const distance = Math.hypot(aimX - cueX, aimY - cueY);
        let shotPower = 0.42 + Math.min(0.45, distance / 460);
        if (state.mode === 'three_cushion') shotPower = 0.58 + Math.random() * 0.22;
        shotPower += (Math.random() * 2 - 1) * 0.06;
        shotPower = Math.max(0.22, Math.min(0.92, shotPower));

        const cue = currentCue();
        const maxSpeed = 500 + cue.power * 300;
        const speed = maxSpeed * shotPower;
        const params = {
            angle: shotAngle,
            power: shotPower,
            spinX: (Math.random() * 2 - 1) * 0.22,
            spinY: state.mode === 'three_cushion' ? (Math.random() * 2 - 1) * 0.25 : (Math.random() * 2 - 1) * 0.18,
            vx: Math.cos(shotAngle) * speed,
            vy: Math.sin(shotAngle) * speed,
            speed,
            cueId: cue.id,
            cueStats: { power: cue.power, spin: cue.spin, control: cue.control },
        };
        if (ballInHand) {
            params.cueX = cueX;
            params.cueY = cueY;
        }

        playCueSound(shotPower);
        beginSimulation(params, 1, null);
    }

    // ------------------------------------------------------------------
    // Online
    // ------------------------------------------------------------------
    function identifierKey() {
        return 'bilardo:room:' + roomCode + ':identifier';
    }

    function connect() {
        if (!isOnline || !roomCode) return;
        intentionalClose = false;
        setConnectionStatus('Bağlanıyor...', '');
        showConnectionOverlay('Odaya bağlanılıyor...');

        const protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        socket = new WebSocket(protocol + window.location.host + '/bilardo/ws/game/' + encodeURIComponent(roomCode) + '/');

        socket.addEventListener('open', () => {
            setConnectionStatus('Bağlı', 'online');
            const name = localStorage.getItem('bilardo:name') || (mySeat === 0 ? 'Oyuncu 1' : 'Oyuncu 2');
            send({
                type: 'join_player',
                player_identifier: myIdentifier,
                name,
                cue: myCue || defaultCue,
            });
            startPing();
        });

        socket.addEventListener('message', (event) => {
            let data;
            try {
                data = JSON.parse(event.data);
            } catch (err) {
                return;
            }
            handleServerMessage(data);
        });

        socket.addEventListener('close', () => {
            stopPing();
            if (intentionalClose) return;
            setConnectionStatus('Bağlantı koptu', 'offline');
            showConnectionOverlay('Bağlantı koptu. Yeniden bağlanılıyor...');
            if (reconnectTimer) window.clearTimeout(reconnectTimer);
            reconnectTimer = window.setTimeout(connect, 2200);
        });

        socket.addEventListener('error', () => {
            setConnectionStatus('Bağlantı hatası', 'offline');
        });
    }

    function send(payload) {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify(payload));
        }
    }

    function startPing() {
        stopPing();
        pingTimer = window.setInterval(() => {
            send({ type: 'ping', time: Date.now() });
        }, 25000);
    }

    function stopPing() {
        if (pingTimer) {
            window.clearInterval(pingTimer);
            pingTimer = null;
        }
    }

    function handleServerMessage(data) {
        switch (data.type) {
            case 'connected':
                setConnectionStatus('Bağlı', 'online');
                break;
            case 'joined':
                joined = true;
                mySeat = data.seat;
                players = data.players || [];
                myCue = (players.find((player) => player.seat === mySeat) || {}).cue || defaultCue;
                hideConnectionOverlay();
                setConnectionStatus('Bağlı', 'online');
                setState(data.state);
                updateWaitingOverlay();
                break;
            case 'players_update':
                players = data.players || [];
                updateUI();
                updateWaitingOverlay();
                break;
            case 'presence':
                if (data.seat !== mySeat) {
                    showToast(data.online ? seatName(data.seat) + ' bağlandı.' : seatName(data.seat) + ' bağlantısı koptu.', data.online ? 'success' : 'error');
                }
                break;
            case 'shot':
                if (data.seat === mySeat) {
                    if (shotInProgress) {
                        // Sunucu kendi vuruşumuzun kimliğini yayınlar; settle
                        // mesajında bu kimliği kullanmalıyız.
                        pendingShotId = data.shot_id;
                        return;
                    }
                    if (finishedShotIds.has(data.shot_id)) {
                        // Yerel simülasyon bitti, aynı vuruşu tekrar oynatma.
                        return;
                    }
                }
                if (shotInProgress) {
                    pendingState = data.state;
                    return;
                }
                players = players.length ? players : [];
                setState(data.state);
                beginSimulation(data.params, data.seat, data.shot_id);
                break;
            case 'state_update':
                if (shotInProgress) {
                    pendingState = data.state;
                    return;
                }
                if (data.state) {
                    setState(data.state);
                }
                if (data.result && data.result.message) {
                    showShotToast(data.result.message, data.result.foul ? 'foul' : '');
                }
                if (data.winner_seat !== null && data.winner_seat !== undefined) {
                    playWinSound();
                }
                break;
            case 'game_over':
                if (data.state) setState(data.state);
                showGameOver();
                break;
            case 'room_reset':
                players = data.players || players;
                pendingState = null;
                shotInProgress = false;
                hideGameOver();
                setState(data.state);
                showToast('Yeni oyun başladı.', 'success');
                if (isBot && state.turn === 1) scheduleBotShot();
                break;
            case 'emote':
                appendEmote(data.name || seatName(data.seat), data.text);
                break;
            case 'error':
                showToast(data.message || 'Bir hata oluştu.', 'error');
                if (shotInProgress && shotShooterSeat === mySeat) {
                    shotInProgress = false;
                    shotStartState = null;
                    shotShooterSeat = null;
                    pendingShotId = null;
                    send({ type: 'get_state' });
                    updateControls();
                }
                if (!joined && data.message && data.message.toLowerCase().includes('dolu')) {
                    showConnectionOverlay('Oda dolu. Yeni bir oda kur veya başka bir kod dene.');
                }
                break;
            case 'pong':
                break;
            default:
                break;
        }
    }

    // ------------------------------------------------------------------
    // Oyun sonu / yeniden oyna
    // ------------------------------------------------------------------
    function showGameOver() {
        if (!state || state.winner === null || state.winner === undefined) return;
        const winner = state.winner;
        const winnerName = seatName(winner);
        if (els.gameOverKicker) {
            els.gameOverKicker.textContent = (state.mode === 'three_cushion' ? '3 Bant' : state.mode === 'eight_ball' ? '8 Top' : state.mode === 'nine_ball' ? '9 Top' : 'Düz Bilardo') + ' bitti';
        }
        if (els.gameOverTitle) els.gameOverTitle.textContent = winnerName + ' kazandı!';
        if (els.gameOverMessage) els.gameOverMessage.textContent = state.message || 'Tebrikler!';
        if (els.gameOverScore) {
            els.gameOverScore.innerHTML = '';
            for (let seat = 0; seat < 2; seat += 1) {
                const span = document.createElement('span');
                span.textContent = String(state.scores ? state.scores[seat] || 0 : 0);
                const small = document.createElement('small');
                small.textContent = seatName(seat);
                span.appendChild(small);
                els.gameOverScore.appendChild(span);
            }
        }
        if (els.gameOverModal) els.gameOverModal.classList.remove('hidden');
    }

    function hideGameOver() {
        if (els.gameOverModal) els.gameOverModal.classList.add('hidden');
    }

    function requestRematch() {
        hideGameOver();
        if (isOnline) {
            send({ type: 'rematch' });
            showToast('Yeniden oyun isteği gönderildi.', 'success');
            return;
        }
        const previousBreaker = state ? (state.breaker || 0) : 0;
        const nextBreaker = 1 - previousBreaker;
        const fresh = P.createInitialState(gameMode, gameTarget, nextBreaker);
        players = [
            { name: 'Oyuncu 1', seat: 0, cue: myCue },
            { name: isBot ? 'Bilardo Botu' : 'Oyuncu 2', seat: 1, cue: myCue },
        ];
        mySeat = 0;
        resetSpin();
        power = 0;
        updatePowerUI();
        setState(fresh);
        if (isBot && fresh.turn === 1) scheduleBotShot();
    }

    // ------------------------------------------------------------------
    // Emote
    // ------------------------------------------------------------------
    function appendEmote(name, text) {
        emoteMessages.push({ name, text });
        if (emoteMessages.length > 12) emoteMessages.shift();
        if (!els.emoteLog) return;
        els.emoteLog.innerHTML = '';
        emoteMessages.slice(-8).forEach((entry) => {
            const row = document.createElement('span');
            const strong = document.createElement('strong');
            strong.textContent = entry.name + ': ';
            row.appendChild(strong);
            row.appendChild(document.createTextNode(entry.text));
            els.emoteLog.appendChild(row);
        });
        els.emoteLog.scrollTop = els.emoteLog.scrollHeight;
    }

    function sendEmote(text) {
        if (isOnline) {
            send({ type: 'emote', text });
        } else {
            appendEmote(seatName(0), text);
        }
    }

    // ------------------------------------------------------------------
    // Ses
    // ------------------------------------------------------------------
    function ensureAudio() {
        if (!audioCtx) {
            const Ctx = window.AudioContext || window.webkitAudioContext;
            if (Ctx) audioCtx = new Ctx();
        }
        if (audioCtx && audioCtx.state === 'suspended') audioCtx.resume();
    }

    function tone(freq, duration, type, volume, slideTo) {
        if (!soundEnabled) return;
        ensureAudio();
        if (!audioCtx) return;
        const now = audioCtx.currentTime;
        const osc = audioCtx.createOscillator();
        const gain = audioCtx.createGain();
        osc.type = type || 'sine';
        osc.frequency.setValueAtTime(freq, now);
        if (slideTo) osc.frequency.exponentialRampToValueAtTime(slideTo, now + duration);
        gain.gain.setValueAtTime(Math.max(0.0001, volume), now);
        gain.gain.exponentialRampToValueAtTime(0.0001, now + duration);
        osc.connect(gain).connect(audioCtx.destination);
        osc.start(now);
        osc.stop(now + duration);
    }

    function playCueSound(powerValue) {
        if (!soundEnabled) return;
        tone(95 + powerValue * 35, 0.09, 'square', 0.08 + powerValue * 0.06);
        tone(1500, 0.025, 'triangle', 0.035);
    }

    function playWinSound() {
        if (!soundEnabled) return;
        [523, 659, 784, 1047].forEach((freq, index) => {
            window.setTimeout(() => tone(freq, 0.22, 'sine', 0.09), index * 130);
        });
    }

    function handleSoundEvent(type, value) {
        if (!soundEnabled) return;
        const now = performance.now();
        if (type === 'ball') {
            if (now - lastBallSound < 30) return;
            lastBallSound = now;
            const volume = Math.min(0.14, 0.025 + (value || 0) / 9000);
            tone(700 + Math.random() * 350, 0.045, 'triangle', volume);
        } else if (type === 'cushion') {
            if (now - lastCushionSound < 55) return;
            lastCushionSound = now;
            tone(150, 0.075, 'sine', Math.min(0.08, 0.02 + (value || 0) / 12000));
        } else if (type === 'pocket') {
            tone(310, 0.18, 'sine', 0.10, 90);
        }
    }

    // ------------------------------------------------------------------
    // Çizim
    // ------------------------------------------------------------------
    function roundRect(context, x, y, width, height, radius) {
        const r = Math.min(radius, width / 2, height / 2);
        context.beginPath();
        context.moveTo(x + r, y);
        context.arcTo(x + width, y, x + width, y + height, r);
        context.arcTo(x + width, y + height, x, y + height, r);
        context.arcTo(x, y + height, x, y, r);
        context.arcTo(x, y, x + width, y, r);
        context.closePath();
    }

    function shade(hex, amount) {
        const clean = hex.replace('#', '');
        const num = parseInt(clean.length === 3
            ? clean.split('').map((c) => c + c).join('')
            : clean, 16);
        let r = (num >> 16) + amount;
        let g = ((num >> 8) & 0xff) + amount;
        let b = (num & 0xff) + amount;
        r = Math.max(0, Math.min(255, r));
        g = Math.max(0, Math.min(255, g));
        b = Math.max(0, Math.min(255, b));
        return 'rgb(' + r + ',' + g + ',' + b + ')';
    }

    function drawTable() {
        const totalW = CONST.W + CONST.RAIL * 2;
        const totalH = CONST.H + CONST.RAIL * 2;

        ctx.save();
        ctx.shadowColor = 'rgba(0,0,0,.55)';
        ctx.shadowBlur = 10;
        ctx.shadowOffsetY = 5;
        const railGrad = ctx.createLinearGradient(0, 0, 0, totalH);
        railGrad.addColorStop(0, '#8a5430');
        railGrad.addColorStop(0.16, '#5e351c');
        railGrad.addColorStop(0.6, '#3d2112');
        railGrad.addColorStop(1, '#24130b');
        roundRect(ctx, 0, 0, totalW, totalH, 10);
        ctx.fillStyle = railGrad;
        ctx.fill();
        ctx.restore();

        ctx.save();
        roundRect(ctx, 1.5, 1.5, totalW - 3, totalH - 3, 9);
        ctx.strokeStyle = 'rgba(233, 180, 120, .25)';
        ctx.lineWidth = 0.5;
        ctx.stroke();
        ctx.restore();

        // Kumaş
        ctx.save();
        const felt = ctx.createRadialGradient(
            CONST.RAIL + CONST.W * 0.5,
            CONST.RAIL + CONST.H * 0.42,
            4,
            CONST.RAIL + CONST.W * 0.5,
            CONST.RAIL + CONST.H * 0.5,
            CONST.W * 0.65
        );
        felt.addColorStop(0, '#1f9b74');
        felt.addColorStop(0.6, '#137a5c');
        felt.addColorStop(1, '#0a4d3c');
        roundRect(ctx, CONST.RAIL, CONST.RAIL, CONST.W, CONST.H, 3);
        ctx.fillStyle = felt;
        ctx.fill();
        ctx.clip();
        const light = ctx.createLinearGradient(CONST.RAIL, CONST.RAIL, CONST.RAIL + CONST.W, CONST.RAIL + CONST.H);
        light.addColorStop(0, 'rgba(255,255,255,.12)');
        light.addColorStop(0.35, 'rgba(255,255,255,0)');
        light.addColorStop(1, 'rgba(0,0,0,.18)');
        ctx.fillStyle = light;
        ctx.fillRect(CONST.RAIL, CONST.RAIL, CONST.W, CONST.H);
        ctx.restore();

        // Başlangıç çizgisi ve noktalar
        ctx.save();
        ctx.strokeStyle = 'rgba(220, 255, 244, .13)';
        ctx.lineWidth = 0.35;
        ctx.setLineDash([2.5, 4]);
        ctx.beginPath();
        ctx.moveTo(CONST.RAIL + CONST.HEAD_X, CONST.RAIL + 2);
        ctx.lineTo(CONST.RAIL + CONST.HEAD_X, CONST.RAIL + CONST.H - 2);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.fillStyle = 'rgba(220,255,244,.22)';
        ctx.beginPath();
        ctx.arc(CONST.RAIL + CONST.FOOT_X, CONST.RAIL + CONST.CENTER_Y, 0.65, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(CONST.RAIL + CONST.HEAD_X, CONST.RAIL + CONST.CENTER_Y, 0.55, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        // Delikler (3 Bant masasında delik yoktur)
        if (state.mode !== 'three_cushion') {
            CONST.POCKETS.forEach((pocket) => {
                const x = CONST.RAIL + pocket.x;
                const y = CONST.RAIL + pocket.y;
                const radius = pocket.corner ? 6.1 : 5.6;
                ctx.save();
                ctx.beginPath();
                ctx.arc(x, y, radius + 1.2, 0, Math.PI * 2);
                ctx.fillStyle = 'rgba(7, 15, 13, .8)';
                ctx.fill();
                ctx.beginPath();
                ctx.arc(x, y, radius, 0, Math.PI * 2);
                ctx.fillStyle = '#03110c';
                ctx.fill();
                ctx.strokeStyle = 'rgba(220, 180, 120, .28)';
                ctx.lineWidth = 0.55;
                ctx.stroke();
                ctx.restore();
            });
        }

        // Bant elmasları
        ctx.save();
        ctx.fillStyle = 'rgba(245, 222, 179, .7)';
        const diamondY = CONST.RAIL / 2;
        for (let i = 1; i < 8; i += 1) {
            if (i === 4) continue;
            const x = CONST.RAIL + (CONST.W * i) / 8;
            drawDiamond(x, diamondY);
            drawDiamond(x, totalH - diamondY);
        }
        const diamondX = CONST.RAIL / 2;
        for (let i = 1; i < 4; i += 1) {
            const y = CONST.RAIL + (CONST.H * i) / 4;
            drawDiamond(diamondX, y);
            drawDiamond(totalW - diamondX, y);
        }
        ctx.restore();

        // Hafif masa logosu
        ctx.save();
        ctx.fillStyle = 'rgba(240, 255, 250, .035)';
        ctx.font = 'bold 8px Inter, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText('BILARDO', CONST.RAIL + CONST.W / 2, CONST.RAIL + CONST.H / 2 + 1);
        ctx.restore();
    }

    function drawDiamond(x, y) {
        ctx.beginPath();
        ctx.moveTo(x, y - 1.1);
        ctx.lineTo(x + 1.4, y);
        ctx.lineTo(x, y + 1.1);
        ctx.lineTo(x - 1.4, y);
        ctx.closePath();
        ctx.fill();
    }

    function drawBall(ball) {
        if (ball.pocketed) return;
        const x = CONST.RAIL + ball.x;
        const y = CONST.RAIL + ball.y;
        const r = CONST.R;
        const isCue = ball.id === 0;

        ctx.save();
        ctx.shadowColor = 'rgba(0,0,0,.55)';
        ctx.shadowBlur = 2.5;
        ctx.shadowOffsetY = 1.4;

        if (ball.stripe) {
            ctx.beginPath();
            ctx.arc(x, y, r, 0, Math.PI * 2);
            ctx.fillStyle = '#f7f8fb';
            ctx.fill();
            ctx.save();
            ctx.beginPath();
            ctx.arc(x, y, r, 0, Math.PI * 2);
            ctx.clip();
            ctx.fillStyle = ball.color;
            ctx.fillRect(x - r, y - r * 0.46, r * 2, r * 0.92);
            ctx.restore();
        } else {
            const gradient = ctx.createRadialGradient(
                x - r * 0.36, y - r * 0.42, r * 0.08,
                x, y, r
            );
            if (isCue) {
                gradient.addColorStop(0, '#ffffff');
                gradient.addColorStop(0.55, '#f1f5f9');
                gradient.addColorStop(1, '#9aa8ba');
            } else {
                gradient.addColorStop(0, '#ffffff');
                gradient.addColorStop(0.16, ball.color);
                gradient.addColorStop(1, shade(ball.color, -58));
            }
            ctx.beginPath();
            ctx.arc(x, y, r, 0, Math.PI * 2);
            ctx.fillStyle = gradient;
            ctx.fill();
        }

        ctx.shadowColor = 'transparent';

        // Parlaklık
        ctx.beginPath();
        ctx.ellipse(x - r * 0.32, y - r * 0.4, r * 0.24, r * 0.16, -0.6, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(255,255,255,.5)';
        ctx.fill();

        if (isCue) {
            ctx.beginPath();
            ctx.arc(x + r * 0.28, y - r * 0.18, r * 0.12, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(220, 38, 38, .8)';
            ctx.fill();
        } else if (state.mode !== 'three_cushion') {
            ctx.beginPath();
            ctx.arc(x, y, r * 0.53, 0, Math.PI * 2);
            ctx.fillStyle = 'rgba(255,255,255,.94)';
            ctx.fill();
            ctx.fillStyle = '#111827';
            ctx.font = 'bold ' + (r * 0.78) + 'px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(String(ball.number), x, y + r * 0.03);
        }

        // Falso noktası (sadece isteka topu ve sıra bizdeyken)
        if (isCue && canShoot() && !shotInProgress) {
            ctx.beginPath();
            ctx.arc(
                x + spinX * r * 0.52,
                y - spinY * r * 0.52,
                r * 0.13,
                0,
                Math.PI * 2
            );
            ctx.fillStyle = 'rgba(239, 68, 68, .9)';
            ctx.fill();
        }

        ctx.restore();
    }

    function drawAim() {
        if (!world || !state || state.winner !== null || shotInProgress) return;
        const cue = world.getCueBall();
        if (!cue || cue.pocketed) return;

        if (placementNeeded()) {
            if (pointer.inside) {
                const valid = canPlaceCueAt(pointer.x, pointer.y);
                ctx.save();
                ctx.beginPath();
                ctx.arc(CONST.RAIL + pointer.x, CONST.RAIL + pointer.y, CONST.R, 0, Math.PI * 2);
                ctx.fillStyle = valid ? 'rgba(52, 211, 153, .25)' : 'rgba(239, 68, 68, .2)';
                ctx.fill();
                ctx.setLineDash([1.2, 1.4]);
                ctx.strokeStyle = valid ? 'rgba(110, 231, 183, .95)' : 'rgba(248, 113, 113, .9)';
                ctx.lineWidth = 0.45;
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.restore();
            }
            return;
        }

        if (!canShoot() || !guideEnabled) {
            drawCueStick(cue);
            return;
        }

        const prediction = P.predictShot(world, angle, 560);
        if (prediction) {
            ctx.save();
            ctx.setLineDash([2.2, 3.2]);
            ctx.strokeStyle = charging ? 'rgba(250, 204, 21, .75)' : 'rgba(255,255,255,.5)';
            ctx.lineWidth = 0.34;
            ctx.beginPath();
            ctx.moveTo(CONST.RAIL + cue.x, CONST.RAIL + cue.y);
            ctx.lineTo(CONST.RAIL + prediction.end.x, CONST.RAIL + prediction.end.y);
            ctx.stroke();
            ctx.setLineDash([]);

            if (prediction.hitBall) {
                ctx.beginPath();
                ctx.arc(CONST.RAIL + prediction.end.x, CONST.RAIL + prediction.end.y, CONST.R, 0, Math.PI * 2);
                ctx.setLineDash([1, 1.4]);
                ctx.strokeStyle = 'rgba(255,255,255,.72)';
                ctx.lineWidth = 0.32;
                ctx.stroke();
                ctx.setLineDash([]);

                const targetX = CONST.RAIL + prediction.hitBall.x;
                const targetY = CONST.RAIL + prediction.hitBall.y;
                ctx.beginPath();
                ctx.arc(targetX, targetY, CONST.R + 0.55, 0, Math.PI * 2);
                ctx.strokeStyle = 'rgba(250, 204, 21, .75)';
                ctx.lineWidth = 0.38;
                ctx.stroke();

                const lineLength = 46;
                ctx.beginPath();
                ctx.moveTo(targetX, targetY);
                ctx.lineTo(
                    targetX + prediction.objectDir.x * lineLength,
                    targetY + prediction.objectDir.y * lineLength
                );
                ctx.strokeStyle = 'rgba(250, 204, 21, .65)';
                ctx.lineWidth = 0.42;
                ctx.stroke();
            } else if (prediction.cushion) {
                const lineLength = 48;
                ctx.beginPath();
                ctx.moveTo(CONST.RAIL + prediction.end.x, CONST.RAIL + prediction.end.y);
                ctx.lineTo(
                    CONST.RAIL + prediction.end.x + prediction.reflection.x * lineLength,
                    CONST.RAIL + prediction.end.y + prediction.reflection.y * lineLength
                );
                ctx.strokeStyle = 'rgba(125, 211, 252, .6)';
                ctx.lineWidth = 0.36;
                ctx.stroke();
            }
            ctx.restore();
        }

        drawCueStick(cue);
    }

    function drawCueStick(cueBall) {
        if (!canShoot() && !charging) return;
        const pull = 1.4 + power * 8;
        const tipX = cueBall.x - Math.cos(angle) * (CONST.R + pull);
        const tipY = cueBall.y - Math.sin(angle) * (CONST.R + pull);
        const buttX = tipX - Math.cos(angle) * 78;
        const buttY = tipY - Math.sin(angle) * 78;
        const cue = currentCue();

        ctx.save();
        ctx.lineCap = 'round';
        ctx.shadowColor = 'rgba(0,0,0,.5)';
        ctx.shadowBlur = 3;
        ctx.shadowOffsetY = 1.5;
        const grad = ctx.createLinearGradient(
            CONST.RAIL + tipX, CONST.RAIL + tipY,
            CONST.RAIL + buttX, CONST.RAIL + buttY
        );
        grad.addColorStop(0, '#e8f6ff');
        grad.addColorStop(0.06, '#67e8f9');
        grad.addColorStop(0.13, '#d9b06b');
        grad.addColorStop(0.3, cue.color);
        grad.addColorStop(1, '#2a160c');
        ctx.strokeStyle = grad;
        ctx.lineWidth = 2.2;
        ctx.beginPath();
        ctx.moveTo(CONST.RAIL + tipX, CONST.RAIL + tipY);
        ctx.lineTo(CONST.RAIL + buttX, CONST.RAIL + buttY);
        ctx.stroke();
        ctx.shadowColor = 'transparent';
        ctx.lineWidth = 0.65;
        ctx.strokeStyle = 'rgba(255,255,255,.22)';
        ctx.beginPath();
        ctx.moveTo(CONST.RAIL + tipX, CONST.RAIL + tipY - 0.35);
        ctx.lineTo(CONST.RAIL + buttX, CONST.RAIL + buttY - 0.35);
        ctx.stroke();
        ctx.restore();

        if (charging) {
            ctx.save();
            ctx.beginPath();
            ctx.arc(
                CONST.RAIL + cueBall.x,
                CONST.RAIL + cueBall.y,
                CONST.R + 3.2,
                -Math.PI / 2,
                -Math.PI / 2 + Math.PI * 2 * power
            );
            ctx.strokeStyle = power > 0.72 ? '#f97316' : power > 0.42 ? '#facc15' : '#34d399';
            ctx.lineWidth = 1.1;
            ctx.lineCap = 'round';
            ctx.stroke();
            ctx.restore();
        }
    }

    function render() {
        if (!state) return;
        const dpr = layout.dpr || 1;
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, layout.width, layout.height);

        const scale = layout.scale;
        ctx.save();
        ctx.scale(scale, scale);

        drawTable();

        const balls = world ? world.balls : state.balls;
        balls.forEach((ball) => drawBall(ball));
        drawAim();

        ctx.restore();
    }

    // ------------------------------------------------------------------
    // Oyun döngüsü
    // ------------------------------------------------------------------
    function frame(timestamp) {
        if (!lastFrame) lastFrame = timestamp;
        let dt = (timestamp - lastFrame) / 1000;
        lastFrame = timestamp;
        if (dt > 0.06) dt = 0.06;

        if (world && world.running) {
            accumulator += dt;
            let steps = 0;
            while (accumulator >= CONST.STEP && steps < 600) {
                world.step(CONST.STEP);
                accumulator -= CONST.STEP;
                steps += 1;
            }
            if (!world.running) {
                finishSimulation();
            }
        } else if (charging) {
            power = Math.min(1, (performance.now() - chargeStartedAt) / 1150);
            updatePowerUI();
            updateControls();
        }

        render();
        window.requestAnimationFrame(frame);
    }

    // ------------------------------------------------------------------
    // Olaylar
    // ------------------------------------------------------------------
    function bindEvents() {
        window.addEventListener('resize', resizeCanvas);
        if (window.ResizeObserver) {
            new ResizeObserver(resizeCanvas).observe(canvasWrap);
        }

        canvas.addEventListener('contextmenu', (event) => event.preventDefault());

        canvas.addEventListener('pointermove', (event) => {
            if (!state) return;
            const point = eventToWorld(event);
            pointer = { x: point.x, y: point.y, inside: true };
            if (placementNeeded()) return;
            const cue = world ? world.getCueBall() : null;
            if (!cue) return;
            if (canShoot() || charging) {
                angle = Math.atan2(point.y - cue.y, point.x - cue.x);
            }
        });

        canvas.addEventListener('pointerleave', () => {
            pointer.inside = false;
        });

        canvas.addEventListener('pointerdown', (event) => {
            if (event.button !== undefined && event.button !== 0) return;
            ensureAudio();
            if (!state || state.winner !== null || shotInProgress) return;

            const point = eventToWorld(event);
            pointer = { x: point.x, y: point.y, inside: true };

            if (placementNeeded()) {
                placeCueBallAt(point.x, point.y);
                return;
            }

            if (!canShoot()) return;
            const cue = world ? world.getCueBall() : null;
            if (cue) angle = Math.atan2(point.y - cue.y, point.x - cue.x);
            if (canvas.setPointerCapture) {
                try { canvas.setPointerCapture(event.pointerId); } catch (err) { /* ignore */ }
            }
            startCharge();
        });

        window.addEventListener('pointerup', () => {
            if (charging) releaseShot();
        });

        window.addEventListener('keydown', (event) => {
            const tag = (event.target && event.target.tagName) || '';
            if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

            if (event.code === 'Space') {
                event.preventDefault();
                if (!event.repeat) startCharge();
            } else if (event.key === 'w' || event.key === 'W') {
                spinY = Math.min(1, spinY + 0.08);
                updateSpinUI();
            } else if (event.key === 's' || event.key === 'S') {
                spinY = Math.max(-1, spinY - 0.08);
                updateSpinUI();
            } else if (event.key === 'a' || event.key === 'A') {
                spinX = Math.max(-1, spinX - 0.08);
                updateSpinUI();
            } else if (event.key === 'd' || event.key === 'D') {
                spinX = Math.min(1, spinX + 0.08);
                updateSpinUI();
            } else if (event.key === 'r' || event.key === 'R') {
                resetSpin();
            } else if (event.key === 'g' || event.key === 'G') {
                els.guideToggle.checked = !els.guideToggle.checked;
                guideEnabled = els.guideToggle.checked;
                localStorage.setItem('bilardo:guide', guideEnabled ? 'on' : 'off');
            } else if (event.key === 'm' || event.key === 'M') {
                els.soundToggle.checked = !els.soundToggle.checked;
                soundEnabled = els.soundToggle.checked;
                localStorage.setItem('bilardo:sound', soundEnabled ? 'on' : 'off');
            } else if (event.key === 'ArrowLeft' && canShoot()) {
                event.preventDefault();
                angle -= 0.012;
            } else if (event.key === 'ArrowRight' && canShoot()) {
                event.preventDefault();
                angle += 0.012;
            }
        });

        window.addEventListener('keyup', (event) => {
            if (event.code === 'Space' && charging) {
                event.preventDefault();
                releaseShot();
            }
        });

        // Falso widget
        if (els.spinWidget) {
            const startSpin = (event) => {
                ensureAudio();
                if (els.spinBall.setPointerCapture) {
                    try { els.spinBall.setPointerCapture(event.pointerId); } catch (err) { /* ignore */ }
                }
                setSpinFromPointer(event);
            };
            els.spinWidget.addEventListener('pointerdown', (event) => {
                event.preventDefault();
                startSpin(event);
            });
            els.spinWidget.addEventListener('pointermove', (event) => {
                if (event.buttons) setSpinFromPointer(event);
            });
            els.spinWidget.addEventListener('pointerup', (event) => {
                setSpinFromPointer(event);
            });
            els.spinWidget.addEventListener('keydown', (event) => {
                if (event.key === 'ArrowLeft') { spinX = Math.max(-1, spinX - 0.08); updateSpinUI(); }
                if (event.key === 'ArrowRight') { spinX = Math.min(1, spinX + 0.08); updateSpinUI(); }
                if (event.key === 'ArrowUp') { spinY = Math.min(1, spinY + 0.08); updateSpinUI(); }
                if (event.key === 'ArrowDown') { spinY = Math.max(-1, spinY - 0.08); updateSpinUI(); }
            });
        }

        // Butonlar
        if (els.shootBtn) {
            els.shootBtn.addEventListener('pointerdown', (event) => {
                event.preventDefault();
                if (!canShoot()) return;
                if (els.shootBtn.setPointerCapture) {
                    try { els.shootBtn.setPointerCapture(event.pointerId); } catch (err) { /* ignore */ }
                }
                startCharge();
            });
            els.shootBtn.addEventListener('pointerup', (event) => {
                event.preventDefault();
                if (charging) releaseShot();
            });
        }

        document.getElementById('spin-reset-btn').addEventListener('click', resetSpin);
        document.getElementById('spin-reset').addEventListener('click', resetSpin);

        if (els.guideToggle) {
            els.guideToggle.checked = guideEnabled;
            els.guideToggle.addEventListener('change', () => {
                guideEnabled = els.guideToggle.checked;
                localStorage.setItem('bilardo:guide', guideEnabled ? 'on' : 'off');
            });
        }

        if (els.soundToggle) {
            els.soundToggle.checked = soundEnabled;
            els.soundToggle.addEventListener('change', () => {
                soundEnabled = els.soundToggle.checked;
                localStorage.setItem('bilardo:sound', soundEnabled ? 'on' : 'off');
                if (soundEnabled) {
                    ensureAudio();
                    tone(880, 0.08, 'sine', 0.05);
                }
            });
        }

        document.getElementById('help-btn').addEventListener('click', () => els.helpModal.classList.remove('hidden'));
        document.getElementById('help-close-btn').addEventListener('click', () => els.helpModal.classList.add('hidden'));
        els.helpModal.addEventListener('click', (event) => {
            if (event.target === els.helpModal) els.helpModal.classList.add('hidden');
        });

        if (els.rematchBtn) els.rematchBtn.addEventListener('click', requestRematch);

        const copyButtons = [document.getElementById('copy-room-btn'), document.getElementById('waiting-copy-btn')];
        copyButtons.forEach((button) => {
            if (!button) return;
            button.addEventListener('click', () => copyRoomCode());
        });

        document.getElementById('fullscreen-btn').addEventListener('click', () => {
            if (document.fullscreenElement) {
                document.exitFullscreen().catch(() => {});
            } else if (canvasWrap.requestFullscreen) {
                canvasWrap.requestFullscreen().catch(() => showToast('Tam ekran başlatılamadı.', 'error'));
            }
        });

        document.querySelectorAll('[data-emote]').forEach((button) => {
            button.addEventListener('click', () => sendEmote(button.dataset.emote));
        });

        window.addEventListener('beforeunload', () => {
            intentionalClose = true;
            if (socket) socket.close();
        });
    }

    function copyRoomCode() {
        if (!roomCode) return;
        const text = roomCode;
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(
                () => showToast('Oda kodu kopyalandı.', 'success'),
                () => showToast('Oda kodu: ' + text, '')
            );
        } else {
            showToast('Oda kodu: ' + text, '');
        }
    }

    // ------------------------------------------------------------------
    // Başlangıç
    // ------------------------------------------------------------------
    function init() {
        resizeCanvas();
        bindEvents();
        updateSpinUI();
        setConnectionStatus(isOnline ? 'Bağlanıyor...' : 'Hazır', isOnline ? '' : 'online');

        if (isOnline) {
            myIdentifier = localStorage.getItem(identifierKey());
            if (!myIdentifier) {
                myIdentifier = uuid();
                localStorage.setItem(identifierKey(), myIdentifier);
            }
            myCue = localStorage.getItem('bilardo:cue') || defaultCue;
            connect();
            els.waitingOverlay.classList.remove('hidden');
            if (els.waitingRoomCode) els.waitingRoomCode.textContent = roomCode;
        } else {
            const selectedCue = localStorage.getItem('bilardo:cue') || defaultCue;
            myCue = selectedCue;
            players = [
                { name: 'Oyuncu 1', seat: 0, cue: selectedCue },
                { name: isBot ? 'Bilardo Botu' : 'Oyuncu 2', seat: 1, cue: selectedCue },
            ];
            mySeat = 0;
            const initial = P.createInitialState(gameMode, gameTarget, 0);
            setState(initial);
            els.waitingOverlay.classList.add('hidden');
            if (isBot && initial.turn === 1) scheduleBotShot();
        }

        window.requestAnimationFrame(frame);
    }

    init();
})();
