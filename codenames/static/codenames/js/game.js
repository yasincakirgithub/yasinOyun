(function () {
    'use strict';

    var body = document.body;
    var roomCode = (body.dataset.roomCode || '').toUpperCase();
    var roomExists = body.dataset.roomExists === '1';
    var TOKEN_KEY = 'codenames:session:' + roomCode;
    var SEAT_NAME_KEY = 'codenames:seatname:' + roomCode;
    var NAME_KEY = 'codenames:name';

    var state = null;
    var socket = null;
    var reconnectTimer = null;
    var pingTimer = null;
    var pollTimer = null;
    var reconnectDelay = 1000;
    var clockTimer = null;
    var serverOffset = 0;
    var boardSignature = '';
    var dismissedOverlayFor = '';
    var pendingGuess = null;
    var toastTimer = null;

    var $ = function (id) { return document.getElementById(id); };
    var el = {
        loading: $('cn-loading'),
        loadingText: $('loading-text'),
        gate: $('cn-join-gate'),
        gateTitle: $('gate-title'),
        gateCopy: $('gate-copy'),
        gateName: $('gate-name'),
        gateError: $('gate-error'),
        gateJoin: $('gate-join-btn'),
        gateResume: $('gate-resume-btn'),
        lobby: $('cn-lobby'),
        lobbyCount: $('lobby-count'),
        lobbyStatus: $('lobby-status'),
        lobbyLanguage: $('lobby-language'),
        lobbyHost: $('lobby-host-badge'),
        lobbyPlayers: $('lobby-players'),
        startBtn: $('start-btn'),
        startCopy: $('start-copy'),
        startErrors: $('start-errors'),
        autoAssign: $('auto-assign-btn'),
        copyInvite: $('copy-invite-btn'),
        settingsForm: $('settings-form'),
        settingsNote: $('settings-note'),
        setLanguage: $('set-language'),
        setStarting: $('set-starting'),
        setTimer: $('set-timer'),
        setMin: $('set-min'),
        setZero: $('set-zero'),
        setExtra: $('set-extra'),
        game: $('cn-game'),
        redScore: $('red-score'),
        blueScore: $('blue-score'),
        redCard: $('red-score-card'),
        blueCard: $('blue-score-card'),
        turnNumber: $('turn-number'),
        turnCard: $('turn-card'),
        turnLabel: $('turn-label'),
        turnMessage: $('turn-message'),
        timerLabel: $('timer-label'),
        wordSource: $('word-source'),
        historyCount: $('guess-history-count'),
        guessHistory: $('guess-history'),
        clueDisplay: $('clue-display'),
        clueHint: $('clue-hint'),
        clueForm: $('clue-form'),
        clueWord: $('clue-word'),
        clueNumber: $('clue-number'),
        endTurn: $('end-turn-btn'),
        board: $('board'),
        boardStatus: $('board-status'),
        spyLegend: $('spy-legend'),
        sideCount: $('side-count'),
        gamePlayers: $('game-players'),
        gameover: $('cn-gameover'),
        overlayTitle: $('overlay-title'),
        overlayReason: $('overlay-reason'),
        overlayScores: $('overlay-scores'),
        overlayClose: $('overlay-close'),
        overlayNew: $('overlay-new'),
        connection: $('connection-pill'),
        toast: $('toast'),
        confirmModal: $('confirm-modal'),
        confirmLeave: $('confirm-leave'),
        confirmCancel: $('confirm-cancel'),
    };

    function getToken() {
        return sessionStorage.getItem(TOKEN_KEY) || '';
    }

    function getStoredToken() {
        return localStorage.getItem(TOKEN_KEY) || '';
    }

    function getStoredSeatName() {
        return localStorage.getItem(SEAT_NAME_KEY) || '';
    }

    function storeToken(token, displayName) {
        if (!token) return;
        localStorage.setItem(TOKEN_KEY, token);
        sessionStorage.setItem(TOKEN_KEY, token);
        if (displayName) {
            localStorage.setItem(SEAT_NAME_KEY, displayName);
            sessionStorage.setItem(SEAT_NAME_KEY, displayName);
        }
    }

    function clearToken() {
        var token = getToken();
        sessionStorage.removeItem(TOKEN_KEY);
        sessionStorage.removeItem(SEAT_NAME_KEY);
        if (!token || localStorage.getItem(TOKEN_KEY) === token) {
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(SEAT_NAME_KEY);
        }
    }

    function createEl(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function showToast(message, info) {
        clearTimeout(toastTimer);
        el.toast.textContent = message;
        el.toast.classList.toggle('is-info', !!info);
        el.toast.hidden = false;
        toastTimer = setTimeout(function () { el.toast.hidden = true; }, 4000);
    }

    function setConnection(status, label) {
        el.connection.classList.remove('is-online', 'is-offline', 'is-connecting');
        el.connection.classList.add('is-' + status);
        el.connection.textContent = label;
    }

    function showLoading(text) {
        el.loading.hidden = false;
        el.gate.hidden = true;
        el.lobby.hidden = true;
        el.game.hidden = true;
        if (text) el.loadingText.textContent = text;
    }

    function showJoinGate(message) {
        el.loading.hidden = true;
        el.lobby.hidden = true;
        el.game.hidden = true;
        el.gameover.hidden = true;
        el.gate.hidden = false;
        el.gateName.value = localStorage.getItem(NAME_KEY) || '';
        el.gateError.hidden = true;
        el.gateError.textContent = '';
        if (!roomExists) {
            el.gateTitle.textContent = 'Oda bulunamadı';
            el.gateCopy.textContent = 'Bu kodla açılmış bir oda yok. Kodu kontrol et veya yeni bir oda kur.';
            el.gateName.disabled = true;
            el.gateJoin.disabled = true;
        }
        var canResume = roomExists && !getToken() && !!getStoredToken();
        el.gateResume.hidden = !canResume;
        el.gateResume.disabled = !canResume;
        if (message) {
            el.gateError.textContent = message;
            el.gateError.hidden = false;
        }
        el.gateName.focus();
    }

    function authHeaders(extra) {
        var headers = Object.assign({ 'Content-Type': 'application/json' }, extra || {});
        var token = getToken();
        if (token) headers.Authorization = 'Bearer ' + token;
        return headers;
    }

    async function api(path, method, payload) {
        var response = await fetch(path, {
            method: method || 'GET',
            headers: authHeaders(),
            body: payload === undefined ? undefined : JSON.stringify(payload),
        });
        var data = await response.json().catch(function () { return {}; });
        if (!response.ok || !data.success) {
            var error = new Error(data.error || 'İstek tamamlanamadı.');
            error.code = data.code || '';
            error.status = response.status;
            throw error;
        }
        return data;
    }

    function roomApi(path) {
        return '/codenames/api/rooms/' + encodeURIComponent(roomCode) + '/' + path + '/';
    }

    async function refreshState() {
        var data = await api(roomApi('state'));
        applyState(data.state);
        return data;
    }

    async function postAction(path, payload) {
        var data = await api(roomApi(path), 'POST', payload || {});
        if (data.state) applyState(data.state);
        return data;
    }

    function handleActionError(error) {
        if (error.status === 401 || error.code === 'auth_failed' || error.code === 'invalid_session') {
            clearToken();
            showJoinGate(error.message || 'Oturum sona erdi. Yeniden katılmalısın.');
            stopPolling();
            return;
        }
        showToast(error.message || 'İşlem tamamlanamadı.');
        if (error.code === 'turn_expired' || error.code === 'stale_state' || error.status === 409) {
            pollState();
        }
    }

    async function pollState() {
        if (document.hidden || !getToken()) return;
        try {
            await refreshState();
        } catch (error) {
            if (error.status === 401 || error.status === 404 ||
                error.code === 'auth_failed' || error.code === 'invalid_session') {
                clearToken();
                showJoinGate(error.message || 'Oturum sona erdi. Yeniden katılmalısın.');
                stopPolling();
            }
        }
    }

    function startPolling() {
        if (pollTimer || !getToken()) return;
        pollTimer = setInterval(pollState, 3000);
    }

    function stopPolling() {
        clearInterval(pollTimer);
        pollTimer = null;
    }

    async function loadState() {
        try {
            var data = await api('/codenames/api/rooms/' + encodeURIComponent(roomCode) + '/state/');
            applyState(data.state);
            return true;
        } catch (error) {
            if (error.status === 401 || error.status === 404) {
                clearToken();
                showJoinGate(error.message);
                return false;
            }
            showLoading('Sunucuya ulaşılamadı. Yeniden deneniyor…');
            return false;
        }
    }

    async function init() {
        bindEvents();
        clockTimer = setInterval(updateClock, 500);

        if (!roomExists) {
            showJoinGate();
            return;
        }
        if (!getToken()) {
            showJoinGate();
            return;
        }
        showLoading('Oda bilgileri alınıyor…');
        var ok = await loadState();
        if (ok) connectSocket();
        else if (!getToken()) {
            showJoinGate();
        } else {
            setTimeout(function () { initRetry(); }, 2000);
        }
    }

    async function initRetry() {
        if (!getToken()) return;
        showLoading('Sunucuya yeniden bağlanılıyor…');
        var ok = await loadState();
        if (ok) connectSocket();
        else if (getToken()) setTimeout(initRetry, Math.min(10000, reconnectDelay += 1000));
    }

    function bindEvents() {
        el.gateJoin.addEventListener('click', joinFromGate);
        el.gateResume.addEventListener('click', resumeSession);
        el.gateName.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') joinFromGate();
        });
        el.startBtn.addEventListener('click', startGame);
        el.autoAssign.addEventListener('click', autoAssign);
        el.settingsForm.addEventListener('change', saveSettings);
        el.clueForm.addEventListener('submit', submitClue);
        el.endTurn.addEventListener('click', endTurnAction);
        el.overlayClose.addEventListener('click', function () {
            if (state && state.session) dismissedOverlayFor = state.session.id;
            el.gameover.hidden = true;
        });
        el.overlayNew.addEventListener('click', newGame);
        $('copy-code-btn').addEventListener('click', function () { copyText(roomCode, 'Oda kodu kopyalandı.'); });
        $('share-btn').addEventListener('click', copyInvite);
        el.copyInvite.addEventListener('click', copyInvite);
        $('leave-btn').addEventListener('click', function () { el.confirmModal.hidden = false; });
        el.confirmCancel.addEventListener('click', function () { el.confirmModal.hidden = true; });
        el.confirmLeave.addEventListener('click', leaveRoom);

        document.querySelectorAll('.js-chat-form').forEach(function (form) {
            form.addEventListener('submit', function (event) {
                event.preventDefault();
                var input = form.querySelector('.js-chat-input');
                var text = (input.value || '').trim();
                if (!text) return;
                sendChat(text, input);
            });
        });

        document.querySelectorAll('.cn-tab').forEach(function (tab) {
            tab.addEventListener('click', function () {
                var name = tab.dataset.tab;
                document.querySelectorAll('.cn-tab').forEach(function (other) {
                    var active = other === tab;
                    other.classList.toggle('is-active', active);
                    other.setAttribute('aria-selected', active ? 'true' : 'false');
                });
                document.querySelectorAll('[data-panel="chat"]').forEach(function (panel) {
                    panel.hidden = name !== 'chat';
                });
                document.querySelectorAll('[data-panel="events"]').forEach(function (panel) {
                    panel.hidden = name !== 'events';
                });
            });
        });

        document.addEventListener('visibilitychange', function () {
            if (document.hidden || !getToken()) return;
            if (!socket || socket.readyState > WebSocket.OPEN) {
                reconnectDelay = 1000;
                connectSocket();
            } else if (socket.readyState === WebSocket.OPEN) {
                sendSocket({ type: 'get_state' });
            }
        });
    }

    async function joinFromGate() {
        var name = (el.gateName.value || '').trim().slice(0, 30);
        if (!name) {
            el.gateError.textContent = 'Görünen adını gir.';
            el.gateError.hidden = false;
            el.gateName.focus();
            return;
        }
        var token = getToken();
        if (!token && getStoredToken() && getStoredSeatName() === name) {
            token = getStoredToken();
        }
        localStorage.setItem(NAME_KEY, name);
        el.gateJoin.disabled = true;
        el.gateJoin.textContent = name && token ? 'GİRİŞ YAPILIYOR…' : 'KATILINIYOR…';
        try {
            var response = await fetch('/codenames/api/rooms/join/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    room_code: roomCode,
                    name: name,
                    session_token: token,
                }),
            });
            var data = await response.json().catch(function () { return {}; });
            if (!response.ok || !data.success) {
                var error = new Error(data.error || 'Odaya katılınamadı.');
                error.status = response.status;
                error.code = data.code || '';
                throw error;
            }
            storeToken(data.session_token, name);
            if (data.state) applyState(data.state);
            el.gate.hidden = true;
            connectSocket();
        } catch (error) {
            if (error.status === 401 || error.status === 404) clearToken();
            el.gateError.textContent = error.message;
            el.gateError.hidden = false;
        } finally {
            el.gateJoin.disabled = false;
            el.gateJoin.textContent = 'KATIL';
        }
    }

    async function resumeSession() {
        var token = getStoredToken();
        if (!token) {
            showJoinGate();
            return;
        }
        var seatName = getStoredSeatName();
        sessionStorage.setItem(TOKEN_KEY, token);
        if (seatName) sessionStorage.setItem(SEAT_NAME_KEY, seatName);
        el.gateResume.disabled = true;
        showLoading('Oturum doğrulanıyor…');
        var ok = await loadState();
        if (ok) {
            connectSocket();
        } else if (!getToken()) {
            showJoinGate();
        } else {
            setTimeout(initRetry, 2000);
        }
    }

    function connectSocket() {
        var token = getToken();
        if (!token) return;
        if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
        clearTimeout(reconnectTimer);
        setConnection('connecting', 'Bağlanıyor…');
        var protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        var ws = new WebSocket(protocol + window.location.host + '/codenames/ws/room/' + encodeURIComponent(roomCode) + '/');
        socket = ws;

        ws.onopen = function () {
            if (socket !== ws) return;
            clearInterval(pingTimer);
            pingTimer = setInterval(function () {
                if (socket && socket.readyState === WebSocket.OPEN) sendSocket({ type: 'ping' });
            }, 25000);
        };

        ws.onmessage = function (event) {
            if (socket !== ws) return;
            var message;
            try { message = JSON.parse(event.data); } catch (error) { return; }
            handleMessage(message);
        };

        ws.onclose = function (event) {
            if (socket !== ws) return;
            socket = null;
            clearInterval(pingTimer);
            if (event.code === 4401) {
                clearToken();
                stopPolling();
                showJoinGate('Oturum sona erdi. Yeniden katılmalısın.');
                return;
            }
            if (event.code === 4403) {
                setConnection('connecting', 'Yedek bağlantı');
                startPolling();
                showToast('Canlı bağlantı reddedildi; yedek moda geçildi.');
                return;
            }
            pendingGuess = null;
            boardSignature = '';
            if (state) render();
            setConnection('connecting', 'Yedek bağlantı');
            startPolling();
            scheduleReconnect();
        };

        ws.onerror = function () {
            if (socket !== ws) return;
            setConnection('offline', 'Bağlantı hatası');
        };
    }

    function scheduleReconnect() {
        clearTimeout(reconnectTimer);
        if (!getToken()) return;
        var delay = reconnectDelay + Math.floor(Math.random() * 500);
        reconnectDelay = Math.min(12000, reconnectDelay * 1.7);
        reconnectTimer = setTimeout(connectSocket, delay);
    }

    function handleMessage(message) {
        if (!message || typeof message.type !== 'string') return;
        if (message.type === 'auth_required') {
            if (getToken()) sendSocket({ type: 'authenticate', session_token: getToken() });
            return;
        }
        if (message.type === 'auth_ok') {
            reconnectDelay = 1000;
            stopPolling();
            setConnection('online', 'Bağlı');
            sendSocket({ type: 'get_state' });
            return;
        }
        if (message.type === 'state') {
            setConnection('online', 'Bağlı');
            applyState(message);
            return;
        }
        if (message.type === 'pong') return;
        if (message.type === 'error') {
            if (message.code === 'auth_failed' || message.code === 'invalid_session') {
                clearToken();
                stopPolling();
                showJoinGate(message.message);
                return;
            }
            if (pendingGuess !== null) {
                pendingGuess = null;
                boardSignature = '';
                if (state) render();
            }
            showToast(message.message || 'Bir hata oluştu.');
            if (message.code === 'turn_expired') {
                setTimeout(function () { sendSocket({ type: 'get_state' }); }, 250);
            }
        }
    }

    function sendSocket(payload) {
        if (!socket || socket.readyState !== WebSocket.OPEN) return false;
        socket.send(JSON.stringify(payload));
        return true;
    }

    async function sendChat(text, input) {
        if (sendSocket({ type: 'chat', text: text })) {
            input.value = '';
            return;
        }
        try {
            await postAction('chat', { text: text });
            input.value = '';
        } catch (error) {
            handleActionError(error);
        }
    }

    function applyState(next) {
        if (!next || next.type !== 'state') return;
        state = next;
        serverOffset = new Date(next.server_time).getTime() - Date.now();
        render();
        if (el.loading.hidden === false) el.loading.hidden = true;
    }

    function render() {
        if (!state) return;
        if (state.me) {
            localStorage.setItem(NAME_KEY, state.me.display_name);
            var currentToken = getToken();
            sessionStorage.setItem(SEAT_NAME_KEY, state.me.display_name);
            if (currentToken && localStorage.getItem(TOKEN_KEY) === currentToken) {
                localStorage.setItem(SEAT_NAME_KEY, state.me.display_name);
            }
        }
        renderChat();
        renderEvents();
        renderGuessHistory();

        if (!state.session && state.room.status === 'STARTING') {
            showLoading('Yapay zekâ yeni kelimeler üretiyor…');
            return;
        }
        if (!state.session) {
            el.loading.hidden = true;
            el.game.hidden = true;
            el.gameover.hidden = true;
            el.lobby.hidden = false;
            renderLobby();
            return;
        }
        el.loading.hidden = true;
        el.lobby.hidden = true;
        el.gate.hidden = true;
        el.game.hidden = false;
        renderGame();
        renderOverlay();
        updateClock();
    }

    function teamLabel(team) {
        return team === 'red' ? 'Kırmızı' : 'Mavi';
    }

    function roleLabel(role) {
        return role === 'spymaster' ? 'Spymaster' : 'Operative';
    }

    function statusLabel(status) {
        return {
            WAITING: 'Oyuncu bekleniyor',
            STARTING: 'Tahta hazırlanıyor',
            IN_PROGRESS: 'Oyun devam ediyor',
            FINISHED: 'Oyun bitti',
            ABANDONED: 'Oyun durduruldu',
        }[status] || status;
    }

    // ------------------------------------------------------------------
    // Lobby
    // ------------------------------------------------------------------
    function renderLobby() {
        var room = state.room;
        var me = state.me;
        var players = state.players || [];
        el.lobbyCount.textContent = room.player_count + '/' + room.max_players;
        el.lobbyStatus.textContent = statusLabel(room.status);
        el.lobbyLanguage.textContent = room.language === 'en' ? 'English' : 'Türkçe';
        var host = players.filter(function (player) { return player.is_host; })[0];
        el.lobbyHost.textContent = 'Host: ' + (host ? host.display_name : '—');

        renderPlayerList(el.lobbyPlayers, players, true);

        el.autoAssign.disabled = !state.permissions.can_assign;
        el.startBtn.disabled = !state.permissions.can_start;
        el.startBtn.textContent = state.permissions.can_start ? 'OYUNU BAŞLAT' : 'BAŞLATMAK İÇİN HAZIR DEĞİL';
        el.startCopy.textContent = room.player_count + '/' + room.min_players +
            ' oyuncu · Her takımda 1 spymaster ve en az 1 operative gerekli.';

        var errors = state.start_errors || [];
        el.startErrors.textContent = '';
        el.startErrors.hidden = errors.length === 0;
        errors.forEach(function (error) {
            el.startErrors.appendChild(createEl('li', '', error));
        });

        el.setLanguage.value = room.language;
        el.setStarting.value = room.settings.starting_team;
        el.setTimer.value = String(room.settings.timer_seconds);
        el.setMin.value = String(room.settings.min_players);
        el.setZero.checked = !!room.settings.allow_zero_clue;
        el.setExtra.checked = !!room.settings.extra_guess;
        var canEdit = state.permissions.is_host && room.status === 'WAITING';
        [el.setLanguage, el.setStarting, el.setTimer, el.setMin, el.setZero, el.setExtra].forEach(function (field) {
            field.disabled = !canEdit;
        });
        el.settingsNote.hidden = state.permissions.is_host;

        if (me) {
            if (me.team === 'red' || me.team === 'blue') {
                body.dataset.myTeam = me.team;
            }
            body.dataset.myRole = me.role;
        }
    }

    function renderPlayerList(container, players, withControls) {
        container.textContent = '';
        if (!players.length) {
            container.appendChild(createEl('p', 'cn-chat-empty', 'Henüz oyuncu yok.'));
            return;
        }
        players.forEach(function (player) {
            var row = createEl('div', 'cn-player-row' + (state.me && player.id === state.me.id ? ' is-me' : ''));
            var main = createEl('div', 'cn-player-main');
            main.appendChild(createEl('span', 'cn-team-dot is-' + player.team));
            var text = createEl('div');
            var nameLine = createEl('div', 'cn-player-name', player.display_name);
            text.appendChild(nameLine);
            var sub = createEl('div', 'cn-player-sub');
            sub.appendChild(createEl('span', 'cn-online-dot' + (player.connected ? '' : ' is-offline')));
            sub.appendChild(createEl('span', 'cn-muted', player.connected ? 'Bağlı' : 'Çevrimdışı'));
            sub.appendChild(createEl('span', 'cn-role-badge is-' + player.role, roleLabel(player.role)));
            if (player.is_host) sub.appendChild(createEl('span', 'cn-host-badge', 'HOST'));
            if (state.me && player.id === state.me.id) sub.appendChild(createEl('span', 'cn-muted', 'sen'));
            text.appendChild(sub);
            main.appendChild(text);
            row.appendChild(main);

            var isMe = !!(state.me && player.id === state.me.id);
            var canManage = withControls && state.permissions.can_assign;
            var canChooseSelf = withControls && isMe && state.permissions.can_choose_role;
            if (canManage || canChooseSelf) {
                var controls = createEl('div', 'cn-assign-controls');
                controls.title = canManage ? 'Takım ve rolü düzenle' : 'Kendi takım ve rolünü seç';
                controls.appendChild(buildSelect(player, 'team', [
                    { value: 'red', label: 'Kırmızı' },
                    { value: 'blue', label: 'Mavi' },
                ], canChooseSelf && !canManage));
                controls.appendChild(buildSelect(player, 'role', [
                    { value: 'operative', label: 'Operative' },
                    { value: 'spymaster', label: 'Spymaster' },
                ], canChooseSelf && !canManage));
                row.appendChild(controls);
            } else {
                row.appendChild(createEl('span', 'cn-role-badge is-' + player.role, roleLabel(player.role)));
            }
            container.appendChild(row);
        });
    }

    function buildSelect(player, field, options, selfService) {
        var select = document.createElement('select');
        select.setAttribute('aria-label', player.display_name + ' ' + (field === 'team' ? 'takımı' : 'rolü'));
        options.forEach(function (option) {
            var node = document.createElement('option');
            node.value = option.value;
            node.textContent = option.label;
            select.appendChild(node);
        });
        select.value = player[field];
        select.addEventListener('change', function () {
            if (selfService) {
                changePreference(field, select.value);
            } else {
                changeAssignment(player, field, select.value);
            }
        });
        return select;
    }

    async function changePreference(field, value) {
        if (!state.me) return;
        var team = field === 'team' ? value : state.me.team;
        var role = field === 'role' ? value : state.me.role;
        try {
            var data = await api(roomApi('preference'), 'POST', { team: team, role: role });
            if (data.state) applyState(data.state);
        } catch (error) {
            showToast(error.message);
            render();
        }
    }

    async function changeAssignment(player, field, value) {
        var assignments = [];
        if (field === 'role' && value === 'spymaster') {
            (state.players || []).forEach(function (other) {
                if (other.id !== player.id && other.team === player.team && other.role === 'spymaster') {
                    assignments.push({ player_id: other.id, team: other.team, role: 'operative' });
                }
            });
        }
        var target = { player_id: player.id };
        target.team = field === 'team' ? value : player.team;
        target.role = field === 'role' ? value : player.role;
        assignments.push(target);
        try {
            var data = await api('/codenames/api/rooms/' + encodeURIComponent(roomCode) + '/assign-roles/', 'POST', { assignments: assignments });
            if (data.state) applyState(data.state);
        } catch (error) {
            showToast(error.message);
            render();
        }
    }

    async function autoAssign() {
        el.autoAssign.disabled = true;
        try {
            var data = await api('/codenames/api/rooms/' + encodeURIComponent(roomCode) + '/assign-roles/', 'POST', { auto: true });
            if (data.state) applyState(data.state);
            showToast('Takımlar dengeli şekilde dağıtıldı.', true);
        } catch (error) {
            showToast(error.message);
        } finally {
            el.autoAssign.disabled = !(state && state.permissions.can_assign);
        }
    }

    async function saveSettings() {
        if (!state || !state.permissions.is_host || state.room.status !== 'WAITING') return;
        var payload = {
            language: el.setLanguage.value,
            timer_seconds: Number(el.setTimer.value),
            starting_team: el.setStarting.value,
            min_players: Number(el.setMin.value),
            allow_zero_clue: el.setZero.checked,
            extra_guess: el.setExtra.checked,
        };
        try {
            var data = await api('/codenames/api/rooms/' + encodeURIComponent(roomCode) + '/settings/', 'POST', payload);
            if (data.state) applyState(data.state);
            showToast('Ayarlar kaydedildi.', true);
        } catch (error) {
            showToast(error.message);
            renderLobby();
        }
    }

    async function startGame() {
        if (!state || !state.permissions.can_start) return;
        el.startBtn.disabled = true;
        el.startBtn.textContent = 'KELİMELER ÜRETİLİYOR…';
        showLoading('Yapay zekâ 25 yeni kelime üretiyor…');
        try {
            var data = await api('/codenames/api/rooms/' + encodeURIComponent(roomCode) + '/start/', 'POST', {});
            if (data.state) applyState(data.state);
        } catch (error) {
            showToast(error.message);
            el.loading.hidden = true;
            if (state) render();
        } finally {
            if (state) render();
        }
    }

    // ------------------------------------------------------------------
    // Game
    // ------------------------------------------------------------------
    function renderGame() {
        var session = state.session;
        var remaining = session.remaining || { red: 0, blue: 0 };
        el.redScore.textContent = remaining.red;
        el.blueScore.textContent = remaining.blue;
        el.redCard.classList.toggle('is-active', session.current_team === 'red' && session.status === 'IN_PROGRESS');
        el.blueCard.classList.toggle('is-active', session.current_team === 'blue' && session.status === 'IN_PROGRESS');
        el.turnCard.classList.toggle('is-red', session.current_team === 'red');
        el.turnCard.classList.toggle('is-blue', session.current_team === 'blue');
        el.turnNumber.textContent = 'Tur ' + session.current_turn;
        el.turnLabel.textContent = teamLabel(session.current_team) + ' takım';
        el.turnMessage.textContent = turnMessage(session);
        el.sideCount.textContent = state.room.player_count + '/' + state.room.max_players;

        var source = session.word_source || '';
        el.wordSource.hidden = !source;
        el.wordSource.className = 'cn-source-badge ' + (source === 'deepseek' ? 'is-ai' : 'is-local');
        el.wordSource.textContent = source === 'deepseek' ? 'DeepSeek kelimeleri' : 'Yerel kelime havuzu';
        el.wordSource.title = source === 'deepseek'
            ? 'Bu tahtadaki kelimeler DeepSeek API ile üretildi.'
            : 'DeepSeek anahtarı yok veya yanıt geçersizdi; kelimeler yerel havuzdan seçildi.';

        if (session.clue) {
            el.clueDisplay.textContent = '“' + session.clue.word + '” · ' + session.clue.number;
            el.clueHint.textContent = 'En fazla ' + session.max_guesses + ' tahmin hakkı · ' + session.guesses_used + ' kullanıldı.';
        } else {
            el.clueDisplay.textContent = 'Henüz ipucu yok';
            el.clueHint.textContent = session.status === 'IN_PROGRESS'
                ? teamLabel(session.current_team) + ' spymaster’ı ipucu verecek.'
                : 'Oyun sona erdi.';
        }

        var me = state.me;
        var canClue = state.permissions.can_clue;
        el.clueForm.hidden = !canClue;
        el.endTurn.hidden = !state.permissions.can_end_turn;
        if (canClue) {
            var zeroAllowed = !!(state.room.settings && state.room.settings.allow_zero_clue);
            el.clueNumber.min = zeroAllowed ? '0' : '1';
            el.clueNumber.max = '9';
            if (!zeroAllowed && el.clueNumber.value === '0') el.clueNumber.value = '1';
        }

        renderPlayerList(el.gamePlayers, state.players || [], false);
        renderBoard(session);
        renderOverlay();

        el.spyLegend.hidden = !(me && me.role === 'spymaster') && session.status === 'IN_PROGRESS';
        if (session.status !== 'IN_PROGRESS') el.spyLegend.hidden = false;

        body.dataset.myTeam = me ? me.team : '';
        body.dataset.myRole = me ? me.role : '';
    }

    function turnMessage(session) {
        if (session.status === 'FINISHED' || session.status === 'ABANDONED') return 'Oyun tamamlandı.';
        var me = state.me;
        if (!me) return '';
        if (me.team !== session.current_team) return 'Sıra rakip takımda.';
        if (me.role === 'spymaster') {
            return session.clue ? 'Operatiflerin tahmin etmesini bekle.' : 'İpucu verme sırası sende.';
        }
        return session.clue ? 'Tahmin et veya turu bitir.' : 'Spymaster’ının ipucunu bekle.';
    }

    function categoryMeta(category) {
        return {
            red: { icon: '●', label: 'Kırmızı' },
            blue: { icon: '▲', label: 'Mavi' },
            neutral: { icon: '○', label: 'Nötr' },
            assassin: { icon: '✕', label: 'Suikastçı' },
        }[category] || null;
    }

    function renderBoard(session) {
        var me = state.me;
        var signature = JSON.stringify({
            team: session.current_team,
            status: session.status,
            role: me ? me.role : '',
            canGuess: state.permissions.can_guess,
            board: session.board.map(function (word) {
                return [word.position, word.word, word.revealed, word.category];
            }),
        });
        if (signature === boardSignature && pendingGuess === null) return;
        boardSignature = signature;
        el.board.textContent = '';
        var canGuess = state.permissions.can_guess && session.status === 'IN_PROGRESS';
        var showCategories = (me && me.role === 'spymaster') || session.status === 'FINISHED' || session.status === 'ABANDONED';

        session.board.forEach(function (word) {
            var meta = word.category ? categoryMeta(word.category) : null;
            var classes = ['cn-tile'];
            if (word.revealed) classes.push('is-revealed');
            if (!word.revealed && word.category) classes.push('is-spy');
            if (word.category) classes.push('is-' + word.category);
            if (canGuess && !word.revealed) classes.push('is-clickable');
            else if (!canGuess) classes.push('is-disabled');
            if (pendingGuess === word.position) classes.push('is-pending');

            var button = document.createElement('button');
            button.type = 'button';
            button.className = classes.join(' ');
            button.setAttribute('role', 'gridcell');
            button.disabled = !canGuess || word.revealed;
            var aria = word.word;
            if (showCategories && meta) aria += ', ' + meta.label;
            if (word.revealed) aria += ', açıldı';
            button.setAttribute('aria-label', aria);

            if (meta && (word.revealed || (me && me.role === 'spymaster'))) {
                var cat = createEl('span', 'cn-tile-cat');
                cat.appendChild(createEl('span', 'cn-cat-icon', meta.icon));
                cat.appendChild(document.createTextNode(meta.label));
                button.appendChild(cat);
            }
            button.appendChild(createEl('span', 'cn-tile-word', word.word));
            if (canGuess && !word.revealed) {
                button.addEventListener('click', function () { guess(word.position, button); });
            }
            el.board.appendChild(button);
        });

        if (session.status === 'IN_PROGRESS') {
            if (canGuess) el.boardStatus.textContent = 'Bir kelimeye tıkla. Nötr veya rakip kelime turu bitirir; suikastçı oyunu kaybettirir.';
            else if (me && me.role === 'spymaster' && me.team === session.current_team) el.boardStatus.textContent = 'Spymaster tahtası: gizli renkler yalnızca sende görünür.';
            else if (me && me.team === session.current_team) el.boardStatus.textContent = 'Spymaster’ın ipucunu bekliyorsun.';
            else el.boardStatus.textContent = 'Rakip takımın sırası.';
        } else {
            el.boardStatus.textContent = 'Tüm tahta açıldı.';
        }
        pendingGuess = null;
    }

    async function guess(position, button) {
        if (pendingGuess !== null) return;
        pendingGuess = position;
        button.classList.add('is-pending');
        button.disabled = true;
        if (sendSocket({ type: 'guess', position: position })) return;
        try {
            await postAction('guess', { position: position });
        } catch (error) {
            pendingGuess = null;
            boardSignature = '';
            if (state) render();
            handleActionError(error);
        }
    }

    async function endTurnAction() {
        if (sendSocket({ type: 'end_turn' })) return;
        try {
            await postAction('end-turn');
        } catch (error) {
            handleActionError(error);
        }
    }

    async function submitClue(event) {
        event.preventDefault();
        var word = (el.clueWord.value || '').trim();
        var number = Number(el.clueNumber.value);
        if (!word) {
            showToast('Bir ipucu kelimesi gir.');
            el.clueWord.focus();
            return;
        }
        if (/\s/.test(word)) {
            showToast('İpucu tek kelime olmalı.');
            el.clueWord.focus();
            return;
        }
        if (!Number.isInteger(number) || number < 0 || number > 9) {
            showToast('İpucu sayısı 0–9 arasında olmalı.');
            el.clueNumber.focus();
            return;
        }
        var zeroAllowed = !!(state && state.room.settings && state.room.settings.allow_zero_clue);
        if (number === 0 && !zeroAllowed) {
            showToast('Sıfır ipucu bu odada kapalı.');
            el.clueNumber.focus();
            return;
        }
        if (sendSocket({ type: 'clue', word: word, number: number })) {
            el.clueWord.value = '';
            return;
        }
        try {
            await postAction('clue', { word: word, number: number });
            el.clueWord.value = '';
        } catch (error) {
            handleActionError(error);
        }
    }

    function renderOverlay() {
        var session = state.session;
        if (!session) { el.gameover.hidden = true; return; }
        var finished = session.status === 'FINISHED' || session.status === 'ABANDONED';
        if (!finished) { el.gameover.hidden = true; return; }
        if (dismissedOverlayFor === session.id) { el.gameover.hidden = true; return; }

        el.gameover.hidden = false;
        if (session.winner) {
            el.overlayTitle.textContent = teamLabel(session.winner) + ' takım kazandı!';
        } else {
            el.overlayTitle.textContent = 'Oyun durduruldu';
        }
        el.overlayReason.textContent = reasonLabel(session.end_reason);
        el.overlayScores.textContent = '';
        ['red', 'blue'].forEach(function (team) {
            var card = createEl('div');
            card.appendChild(createEl('span', '', teamLabel(team)));
            card.appendChild(createEl('strong', 'is-' + team, String(session.remaining[team])));
            card.appendChild(createEl('span', '', 'ajan kaldı'));
            el.overlayScores.appendChild(card);
        });
        el.overlayNew.hidden = !state.permissions.can_new_game;
    }

    function reasonLabel(reason) {
        return {
            assassin: 'Suikastçı açıldı. Açan takım oyunu kaybetti.',
            agents: 'Takım tüm ajanlarını açtı.',
            opponent_agents: 'Rakip takımın tüm ajanları açıldı.',
            spymaster_left: 'Bir spymaster odadan ayrıldığı için oyun durduruldu.',
            operative_left: 'Bir takımda operative kalmadığı için oyun durduruldu.',
            room_empty: 'Odada oyuncu kalmadı.',
            timeout: 'Süre doldu.',
        }[reason] || 'Oyun tamamlandı.';
    }

    async function newGame() {
        el.overlayNew.disabled = true;
        try {
            var data = await api('/codenames/api/rooms/' + encodeURIComponent(roomCode) + '/new-game/', 'POST', {});
            dismissedOverlayFor = '';
            if (data.state) applyState(data.state);
        } catch (error) {
            showToast(error.message);
        } finally {
            el.overlayNew.disabled = false;
        }
    }

    // ------------------------------------------------------------------
    // Chat / events / clock
    // ------------------------------------------------------------------
    function renderChat() {
        var messages = state.messages || [];
        document.querySelectorAll('.js-chat-list').forEach(function (list) {
            list.textContent = '';
            if (!messages.length) {
                list.appendChild(createEl('p', 'cn-chat-empty', 'Henüz mesaj yok. Sohbeti sen başlat.'));
                return;
            }
            messages.forEach(function (message) {
                var row = createEl('div', 'cn-chat-row' + (message.kind === 'system' ? ' is-system' : ''));
                var meta = createEl('div', 'cn-chat-meta');
                if (message.kind === 'system') {
                    meta.appendChild(createEl('span', 'cn-chat-name', 'Sistem'));
                } else {
                    if (message.team) meta.appendChild(createEl('span', 'cn-team-dot is-' + message.team));
                    meta.appendChild(createEl('span', 'cn-chat-name', message.display_name || 'Oyuncu'));
                    meta.appendChild(createEl('span', '', roleLabel(message.role)));
                }
                meta.appendChild(createEl('time', '', formatTime(message.created_at)));
                row.appendChild(meta);
                row.appendChild(createEl('div', 'cn-chat-text', message.text));
                list.appendChild(row);
            });
            list.scrollTop = list.scrollHeight;
        });
    }

    function renderEvents() {
        var container = document.querySelector('.cn-events-list');
        if (!container) return;
        container.textContent = '';
        var events = state.events || [];
        if (!events.length) {
            container.appendChild(createEl('p', 'cn-chat-empty', 'Henüz olay yok.'));
            return;
        }
        events.slice().reverse().forEach(function (event) {
            var row = createEl('div', 'cn-event-row');
            row.appendChild(createEl('time', '', formatTime(event.created_at)));
            row.appendChild(createEl('p', '', event.message));
            container.appendChild(row);
        });
    }

    function renderGuessHistory() {
        if (!el.guessHistory || !el.historyCount) return;
        var history = state.guess_history || [];
        el.historyCount.textContent = history.length + ' tur';
        el.guessHistory.textContent = '';
        if (!history.length) {
            el.guessHistory.appendChild(createEl('p', 'cn-chat-empty', 'Henüz tahmin geçmişi yok.'));
            return;
        }
        history.slice().reverse().forEach(function (item) {
            var group = createEl('div', 'cn-history-group is-' + (item.team || 'neutral'));
            var head = createEl('div', 'cn-history-head');
            head.appendChild(createEl('span', 'cn-history-turn', 'Tur ' + item.turn));
            head.appendChild(createEl('span', 'cn-history-team', teamLabel(item.team)));
            group.appendChild(head);

            var clue = createEl('div', 'cn-history-clue');
            clue.appendChild(createEl('strong', '', '“' + (item.clue || '—') + '”'));
            if (item.number !== null && item.number !== undefined) {
                clue.appendChild(createEl('span', 'cn-history-number', ' · ' + item.number));
            }
            group.appendChild(clue);

            var guesses = createEl('div', 'cn-history-guesses');
            (item.guesses || []).forEach(function (guess) {
                var meta = categoryMeta(guess.category) || { icon: '·', label: 'Bilinmiyor' };
                var chip = createEl('span', 'cn-history-word is-' + (guess.category || 'neutral'));
                chip.appendChild(createEl('span', 'cn-cat-icon', meta.icon));
                chip.appendChild(createEl('span', '', guess.word));
                chip.title = (guess.display_name ? guess.display_name + ' · ' : '') + meta.label;
                guesses.appendChild(chip);
            });
            if (!(item.guesses || []).length) {
                guesses.appendChild(createEl('span', 'cn-history-empty', 'Tahmin yapılmadı.'));
            }
            group.appendChild(guesses);

            var endLabel = historyEndLabel(item.end_reason);
            if (endLabel) group.appendChild(createEl('span', 'cn-history-end', endLabel));
            el.guessHistory.appendChild(group);
        });
    }

    function historyEndLabel(reason) {
        return {
            timeout: 'Süre doldu',
            voluntary: 'Pas geçildi',
            neutral: 'Nötr kelime açıldı',
            opponent: 'Rakip ajan açıldı',
            guess_limit: 'Tahmin hakkı bitti',
        }[reason] || '';
    }

    function formatTime(value) {
        if (!value) return '';
        try {
            return new Date(value).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' });
        } catch (error) {
            return '';
        }
    }

    function updateClock() {
        if (!state || !state.session) {
            if (el.timerLabel) el.timerLabel.textContent = 'Süre kapalı';
            return;
        }
        var session = state.session;
        if (session.status !== 'IN_PROGRESS') {
            el.timerLabel.textContent = 'Oyun bitti';
            el.timerLabel.classList.remove('is-urgent');
            return;
        }
        var timer = session.timer || {};
        if (!timer.deadline) {
            el.timerLabel.textContent = 'Süre kapalı';
            el.timerLabel.classList.remove('is-urgent');
            return;
        }
        var deadline = new Date(timer.deadline).getTime();
        var remaining = Math.max(0, Math.ceil((deadline - (Date.now() + serverOffset)) / 1000));
        el.timerLabel.textContent = remaining + ' sn';
        el.timerLabel.classList.toggle('is-urgent', remaining <= 10);
    }

    // ------------------------------------------------------------------
    // Misc actions
    // ------------------------------------------------------------------
    async function copyText(text, message) {
        try {
            await navigator.clipboard.writeText(text);
            showToast(message || 'Kopyalandı.', true);
        } catch (error) {
            showToast('Kopyalanamadı. Tarayıcı izni gerekli olabilir.');
        }
    }

    function copyInvite() {
        var url = window.location.origin + '/codenames/room/' + roomCode + '/';
        copyText(url, 'Davet bağlantısı kopyalandı.');
    }

    async function leaveRoom() {
        el.confirmLeave.disabled = true;
        try {
            await api('/codenames/api/rooms/' + encodeURIComponent(roomCode) + '/leave/', 'POST', {});
            clearToken();
            window.location.href = '/codenames/';
        } catch (error) {
            showToast(error.message);
            el.confirmLeave.disabled = false;
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
