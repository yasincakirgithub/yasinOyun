(function () {
    'use strict';

    var body = document.body;
    var roomCode = (body.dataset.roomCode || '').toUpperCase();
    var roomExists = body.dataset.roomExists === '1';

    var TOKEN_KEY = 'fcmanager:session:' + roomCode;
    var SEAT_NAME_KEY = 'fcmanager:seatname:' + roomCode;
    var NAME_KEY = 'fcmanager:name';
    var MAX_SLOTS = 11;
    var MAX_PLAYERS = 2;

    var FALLBACK_SLOTS = [
        { key: 'gk', label: 'GK', role: 'GK', full: 'Kaleci', accept: ['GK'], x: 50, y: 88 },
        { key: 'lb', label: 'LB', role: 'DEF', full: 'Sol bek', accept: ['LB', 'LWB'], x: 13, y: 69 },
        { key: 'cb1', label: 'CB', role: 'DEF', full: 'Stoper', accept: ['CB'], x: 36, y: 73 },
        { key: 'cb2', label: 'CB', role: 'DEF', full: 'Stoper', accept: ['CB'], x: 64, y: 73 },
        { key: 'rb', label: 'RB', role: 'DEF', full: 'Sağ bek', accept: ['RB', 'RWB'], x: 87, y: 69 },
        { key: 'cm1', label: 'CM', role: 'MID', full: 'Orta saha', accept: ['CM', 'CDM', 'CAM', 'LCM', 'RCM', 'LDM', 'RDM', 'LAM', 'RAM'], x: 24, y: 48 },
        { key: 'cm2', label: 'CM', role: 'MID', full: 'Orta saha', accept: ['CM', 'CDM', 'CAM', 'LCM', 'RCM', 'LDM', 'RDM', 'LAM', 'RAM'], x: 50, y: 53 },
        { key: 'cm3', label: 'CM', role: 'MID', full: 'Orta saha', accept: ['CM', 'CDM', 'CAM', 'LCM', 'RCM', 'LDM', 'RDM', 'LAM', 'RAM'], x: 76, y: 48 },
        { key: 'lw', label: 'LW', role: 'FWD', full: 'Sol kanat', accept: ['LW', 'LM', 'LF'], x: 17, y: 22 },
        { key: 'st', label: 'ST', role: 'FWD', full: 'Santrfor', accept: ['ST', 'CF', 'LS', 'RS'], x: 50, y: 14 },
        { key: 'rw', label: 'RW', role: 'FWD', full: 'Sağ kanat', accept: ['RW', 'RM', 'RF'], x: 83, y: 22 }
    ];

    var state = null;
    var socket = null;
    var reconnectTimer = null;
    var pingTimer = null;
    var pollTimer = null;
    var reconnectDelay = 1000;
    var toastTimer = null;
    var stateRequestId = 0;
    var actionBusy = false;
    var selectedMarketId = null;
    var selectedSlot = null;
    var dragPayload = null;
    var confirmAction = null;
    var dismissedResultFor = '';
    var previousStatus = null;
    var previousMatchId = null;
    var lastMarketSignature = '';
    var lastPitchSignature = '';
    var lastChallengeSignature = '';
    var slotByKey = {};

    var marketFilters = { q: '', group: 'all', sort: 'rating', affordable: false };
    var marketPage = {
        items: [], total: 0, page: 0, pages: 0, hasMore: true, loading: false,
        loaded: false, requestId: 0
    };
    var marketTimer = null;
    var matchAnim = { id: null, timer: null, index: 0, done: false, started: false };

    var $ = function (id) { return document.getElementById(id); };
    var el = {
        loading: $('fc-loading'),
        loadingText: $('loading-text'),
        gate: $('fc-join-gate'),
        gateTitle: $('gate-title'),
        gateCopy: $('gate-copy'),
        gateName: $('gate-name'),
        gateError: $('gate-error'),
        gateJoin: $('gate-join-btn'),
        gateResume: $('gate-resume-btn'),
        lobby: $('fc-lobby'),
        lobbyCount: $('lobby-count'),
        lobbyStatus: $('lobby-status'),
        lobbyHost: $('lobby-host-badge'),
        lobbyPlayers: $('lobby-players'),
        lobbyStartHint: $('lobby-start-hint'),
        lobbyStartErrors: $('lobby-start-errors'),
        lobbyStart: $('lobby-start-btn'),
        lobbyCopy: $('lobby-copy-btn'),
        draft: $('fc-draft'),
        budgetEur: $('budget-eur'),
        budgetTry: $('budget-try'),
        budgetSpent: $('budget-spent'),
        budgetRemaining: $('budget-remaining'),
        budgetBar: $('budget-bar'),
        budgetPct: $('budget-pct'),
        youSide: $('you-side'),
        youName: $('you-name'),
        youLocked: $('you-locked-badge'),
        squadCount: $('squad-count'),
        challengeSummary: $('challenge-summary'),
        draftStatus: $('draft-status'),
        oppStatus: $('opp-status'),
        oppName: $('opp-name'),
        oppLocked: $('opp-locked'),
        oppSquadCount: $('opp-squad-count'),
        oppSpent: $('opp-spent'),
        oppChallenges: $('opp-challenges'),
        oppSquad: $('opp-squad'),
        marketCount: $('market-count'),
        marketSearch: $('market-search'),
        marketGroups: $('market-groups'),
        marketSort: $('market-sort'),
        marketAffordable: $('market-affordable'),
        marketHint: $('market-selected-hint'),
        marketList: $('market-list'),
        marketMore: $('market-more'),
        marketPanel: document.querySelector('.fc-market-panel'),
        pitchBadge: $('pitch-badge'),
        pitchSlots: $('pitch-slots'),
        pitchHint: $('pitch-hint'),
        clearSquad: $('clear-squad-btn'),
        autoSquad: $('auto-squad-btn'),
        challengeBadge: $('challenge-badge'),
        challengeList: $('challenge-list'),
        actionHint: $('action-hint'),
        lockBtn: $('lock-btn'),
        unlockBtn: $('unlock-btn'),
        startMatchBtn: $('start-match-btn'),
        hostHint: $('host-hint'),
        match: $('fc-match'),
        matchHomeName: $('match-home-name'),
        matchHomeSub: $('match-home-sub'),
        matchAwayName: $('match-away-name'),
        matchAwaySub: $('match-away-sub'),
        matchHomeScore: $('match-home-score'),
        matchAwayScore: $('match-away-score'),
        matchPen: $('match-pen'),
        matchMinute: $('match-minute'),
        matchPhase: $('match-phase'),
        matchProgress: $('match-progress'),
        matchEventCount: $('match-event-count'),
        matchCommentary: $('match-commentary'),
        matchStats: $('match-stats'),
        matchChallenges: $('match-challenges'),
        matchPitch3D: $('match-pitch3d'),
        matchSkip: $('match-skip-btn'),
        newSeason: $('new-season-btn'),
        toast: $('toast'),
        result: $('fc-result'),
        resultTitle: $('result-title'),
        resultCopy: $('result-copy'),
        resultScore: $('result-score'),
        resultMvp: $('result-mvp'),
        resultStats: $('result-stats'),
        resultClose: $('result-close'),
        resultNew: $('result-new'),
        confirm: $('fc-confirm'),
        confirmTitle: $('confirm-title'),
        confirmCopy: $('confirm-copy'),
        confirmCancel: $('confirm-cancel'),
        confirmLeave: $('confirm-leave'),
        connection: $('connection-pill'),
        leaveBtn: $('leave-btn'),
        copyCode: $('copy-code-btn'),
        shareBtn: $('share-btn')
    };

    function createEl(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function setText(node, text) {
        if (node) node.textContent = text === undefined || text === null ? '' : String(text);
    }

    function clearNode(node) {
        if (node) node.innerHTML = '';
    }

    function showToast(message, isError) {
        if (!el.toast) return;
        clearTimeout(toastTimer);
        el.toast.textContent = message;
        el.toast.classList.toggle('is-error', !!isError);
        el.toast.hidden = false;
        toastTimer = setTimeout(function () { el.toast.hidden = true; }, 4200);
    }

    function setConnection(status, label) {
        if (!el.connection) return;
        el.connection.classList.remove('is-online', 'is-offline', 'is-connecting');
        el.connection.classList.add('is-' + status);
        el.connection.textContent = label;
    }

    function initials(name) {
        var parts = String(name || '?').trim().split(/\s+/).slice(0, 2);
        return parts.map(function (part) { return part.charAt(0); }).join('').toUpperCase() || '?';
    }

    function trNumber(value, digits) {
        return Number(value || 0).toLocaleString('tr-TR', {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits
        });
    }

    function formatDecimal(value) {
        return trNumber(value, 1);
    }

    function formatCompact(value, symbol) {
        var abs = Math.abs(Number(value) || 0);
        if (abs >= 1000000000000) return symbol + trNumber(value / 1000000000000, 2).replace(',00', '') + ' tn';
        if (abs >= 1000000000) return symbol + trNumber(value / 1000000000, 2).replace(',00', '') + ' mlr';
        if (abs >= 1000000) return symbol + trNumber(value / 1000000, abs >= 100000000 ? 0 : 1) + ' mn';
        if (abs >= 1000) return symbol + trNumber(value / 1000, 0) + ' bin';
        return symbol + trNumber(value, 0);
    }

    function formatEur(value) { return formatCompact(value, '€'); }
    function formatTry(value) { return formatCompact(value, '₺'); }

    function sideLabel(side) {
        return side === 'away' ? 'DEP' : 'EV';
    }

    function roleOf(player) {
        var bucket = player && player.bucket;
        if (bucket === 'gk') return 'GK';
        if (bucket === 'cb' || bucket === 'lb' || bucket === 'rb') return 'DEF';
        if (bucket === 'cm' || bucket === 'cam') return 'MID';
        return 'FWD';
    }

    function slotAccepts(slot, player) {
        if (!slot || !player) return false;
        var accept = slot.accept || [];
        var positions = player.positions || [];
        for (var i = 0; i < positions.length; i += 1) {
            if (accept.indexOf(positions[i]) >= 0) return true;
        }
        return false;
    }

    function slotFor(key) {
        return slotByKey[key] || null;
    }

    function marketPlayer(id) {
        var wanted = String(id);
        var loaded = marketPage.items || [];
        for (var i = 0; i < loaded.length; i += 1) {
            if (String(loaded[i].id) === wanted) return loaded[i];
        }
        var market = (state && state.market) || [];
        for (var j = 0; j < market.length; j += 1) {
            if (String(market[j].id) === wanted) return market[j];
        }
        return null;
    }

    function currentPick(id) {
        var wanted = String(id);
        var picks = (state && state.market) || [];
        for (var i = 0; i < picks.length; i += 1) {
            if (String(picks[i].id) === wanted) return picks[i];
        }
        return null;
    }

    function pickedByOpponent(player) {
        var pick = currentPick(player && player.id);
        return !!(pick && pick.picked_by && !pick.picked_by_you);
    }

    function pickedByYou(player) {
        var pick = currentPick(player && player.id);
        return !!(pick && pick.picked_by_you);
    }

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
        sessionStorage.setItem(TOKEN_KEY, token);
        localStorage.setItem(TOKEN_KEY, token);
        if (displayName) {
            sessionStorage.setItem(SEAT_NAME_KEY, displayName);
            localStorage.setItem(SEAT_NAME_KEY, displayName);
        }
    }

    function clearToken(includeStored) {
        sessionStorage.removeItem(TOKEN_KEY);
        sessionStorage.removeItem(SEAT_NAME_KEY);
        if (includeStored !== false) {
            localStorage.removeItem(TOKEN_KEY);
            localStorage.removeItem(SEAT_NAME_KEY);
        }
    }

    function authHeaders() {
        var headers = { 'Content-Type': 'application/json' };
        var token = getToken() || getStoredToken();
        if (token) headers.Authorization = 'Bearer ' + token;
        return headers;
    }

    async function api(path, method, payload) {
        var response = await fetch(path, {
            method: method || 'GET',
            headers: authHeaders(),
            body: payload === undefined ? undefined : JSON.stringify(payload)
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
        return '/fcmanager/api/rooms/' + encodeURIComponent(roomCode) + '/' + path + '/';
    }

    function inviteUrl() {
        return window.location.origin + '/fcmanager/room/' + encodeURIComponent(roomCode) + '/';
    }

    function copyText(text, successMessage) {
        function fallback() {
            var area = document.createElement('textarea');
            area.value = text;
            area.setAttribute('readonly', 'readonly');
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            var ok = false;
            try { ok = document.execCommand('copy'); } catch (error) { ok = false; }
            document.body.removeChild(area);
            if (!ok) throw new Error('copy failed');
        }
        var task = (navigator.clipboard && window.isSecureContext)
            ? navigator.clipboard.writeText(text)
            : Promise.resolve().then(fallback);
        task.then(function () {
            showToast(successMessage || 'Kopyalandı.');
        }).catch(function () {
            showToast('Panoya kopyalanamadı. Adresi elle kopyalayabilirsin.', true);
        });
    }

    function showOnly(section) {
        el.loading.hidden = section !== 'loading';
        el.gate.hidden = section !== 'gate';
        el.lobby.hidden = section !== 'lobby';
        el.draft.hidden = section !== 'draft';
        el.match.hidden = section !== 'match';
    }

    function showLoading(text) {
        showOnly('loading');
        if (text) setText(el.loadingText, text);
    }

    function showGate(message) {
        showOnly('gate');
        var storedName = localStorage.getItem(NAME_KEY) || getStoredSeatName() || '';
        el.gateName.value = storedName;
        el.gateName.disabled = !roomExists;
        el.gateJoin.disabled = !roomExists;
        el.gateResume.hidden = !(roomExists && getStoredToken() && !getToken());
        el.gateResume.disabled = el.gateResume.hidden;
        if (!roomExists) {
            setText(el.gateTitle, 'Oda bulunamadı');
            setText(el.gateCopy, 'Bu kodla açılmış bir oda yok. Kodu kontrol et veya ana sayfadan yeni bir oda kur.');
        } else {
            setText(el.gateTitle, 'Odaya katıl');
        }
        if (message) {
            el.gateError.textContent = message;
            el.gateError.hidden = false;
        } else {
            el.gateError.hidden = true;
            el.gateError.textContent = '';
        }
        setConnection('connecting', 'Bağlanıyor…');
        if (roomExists) {
            try { el.gateName.focus(); } catch (error) { /* ignore */ }
        }
    }

    function gateError(message) {
        el.gateError.textContent = message || '';
        el.gateError.hidden = !message;
    }

    function applyState(next) {
        if (!next || !next.room || !next.you) return;

        var prevStatus = state && state.room ? state.room.status : null;
        var prevMatchId = state && state.match ? state.match.id : null;
        var status = next.room.status;

        if (prevStatus !== status || prevMatchId !== (next.match && next.match.id)) {
            selectedMarketId = null;
            selectedSlot = null;
            lastMarketSignature = '';
            lastPitchSignature = '';
            lastChallengeSignature = '';
            marketPage.items = [];
            marketPage.total = 0;
            marketPage.page = 0;
            marketPage.pages = 0;
            marketPage.hasMore = true;
            marketPage.loading = false;
            marketPage.loaded = false;
            marketPage.requestId += 1;
        }

        state = next;
        roomExists = true;
        slotByKey = {};
        var slots = state.slots && state.slots.length ? state.slots : FALLBACK_SLOTS;
        slots.forEach(function (slot) { slotByKey[slot.key] = slot; });

        if (selectedMarketId) {
            var picked = marketPlayer(selectedMarketId);
            if (!picked || pickedByOpponent(picked)) selectedMarketId = null;
        }
        if (selectedSlot && !slotByKey[selectedSlot]) selectedSlot = null;

        if (status === 'WAITING') {
            stopMatchAnimation();
            hideResult();
            el.newSeason.hidden = true;
            showOnly('lobby');
            renderLobby();
        } else if (status === 'DRAFT') {
            stopMatchAnimation();
            hideResult();
            el.newSeason.hidden = true;
            showOnly('draft');
            renderDraft();
            if (!marketPage.loaded && !marketPage.loading) loadMarket(true);
        } else if (status === 'FINISHED') {
            showOnly('match');
            renderMatch(state.match);
            if (window.FCMatch3D) window.FCMatch3D.start();
        } else {
            roomExists = false;
            showGate('Bu oda kapatılmış.');
        }

        if (prevStatus && prevStatus !== status) {
            if (status === 'DRAFT' && prevStatus === 'WAITING') {
                showToast('Sezon başladı! Bütçen ve ortak görevlerin hazır.');
            } else if (status === 'DRAFT' && prevStatus === 'FINISHED') {
                showToast('Yeni sezon açıldı. Transfer piyasası yenilendi.');
            } else if (status === 'WAITING') {
                showToast('Oda yeniden bekleme modunda.');
            }
        }

        previousStatus = status;
        previousMatchId = state.match ? state.match.id : null;
    }

    function renderLobby() {
        if (!state) return;
        var players = state.players || [];
        var you = state.you;
        var enough = players.length >= MAX_PLAYERS;
        var host = null;
        players.forEach(function (player) { if (player.is_host) host = player; });

        setText(el.lobbyCount, players.length + '/' + MAX_PLAYERS);
        setText(el.lobbyStatus, enough ? 'Sezon başlatılabilir' : 'Rakip bekleniyor');
        setText(el.lobbyHost, host ? 'Host: ' + host.name : 'Host: —');

        clearNode(el.lobbyPlayers);
        players.forEach(function (player) {
            var row = createEl('div', 'fc-lobby-player');
            var avatar = createEl('span', 'fc-lobby-avatar', initials(player.name));
            var main = createEl('div');
            var name = createEl('strong', '', player.name + (player.id === you.id ? ' (sen)' : ''));
            var small = createEl('small', '', player.side === 'home' ? 'Ev sahibi · EV' : 'Deplasman · DEP');
            main.appendChild(name);
            main.appendChild(small);
            var badge = createEl('span', 'fc-badge', player.is_host ? 'HOST' : (player.connected ? 'BAĞLI' : 'KOPUK'));
            if (player.connected) badge.classList.add('is-green');
            else badge.classList.add('is-red');
            row.appendChild(avatar);
            row.appendChild(main);
            row.appendChild(badge);
            el.lobbyPlayers.appendChild(row);
        });

        var errors = [];
        if (!enough) errors.push('Oyunu başlatmak için 2 menajer gerekli.');
        clearNode(el.lobbyStartErrors);
        errors.forEach(function (message) {
            el.lobbyStartErrors.appendChild(createEl('li', '', message));
        });
        el.lobbyStartErrors.hidden = errors.length === 0;

        if (!you.is_host) {
            setText(el.lobbyStartHint, 'Sezonu oda sahibi başlatacak. O da hazır olduğunda oyun açılır.');
        } else if (!enough) {
            setText(el.lobbyStartHint, 'Davet bağlantısını paylaş; ikinci menajer katıldığında başlatabilirsin.');
        } else {
            setText(el.lobbyStartHint, 'İki menajer de hazır. Sezonu başlatabilirsin.');
        }
        el.lobbyStart.disabled = actionBusy || !you.is_host || !enough;
    }

    function renderDraft() {
        if (!state || state.room.status !== 'DRAFT') return;
        var you = state.you;
        var budget = Number(state.room.budget_eur) || 0;
        var spent = Number(you.spent) || 0;
        var remaining = you.remaining === undefined || you.remaining === null
            ? Math.max(0, budget - spent)
            : Number(you.remaining);
        var pct = budget > 0 ? (spent / budget) * 100 : 0;

        setText(el.budgetEur, formatEur(budget));
        setText(el.budgetTry, '≈ ' + formatTry(state.room.budget_try));
        setText(el.budgetSpent, formatEur(spent));
        setText(el.budgetRemaining, formatEur(remaining));
        setText(el.budgetPct, '%' + Math.round(pct));
        if (el.budgetBar) {
            el.budgetBar.style.width = Math.min(100, Math.max(0, pct)) + '%';
            if (el.budgetBar.parentElement) {
                el.budgetBar.parentElement.classList.toggle('is-over', spent > budget);
            }
        }

        setText(el.youSide, sideLabel(you.side));
        setText(el.youName, you.name);
        setText(el.youLocked, you.locked ? 'Kadro kilitli' : 'Kadro açık');
        el.youLocked.classList.toggle('is-green', !!you.locked);
        setText(el.squadCount, (you.slots_filled || 0) + '/' + MAX_SLOTS);

        var challenges = you.challenges || [];
        var done = challenges.filter(function (challenge) { return challenge.satisfied; }).length;
        setText(el.challengeSummary, done + '/' + challenges.length);

        if (you.locked) setText(el.draftStatus, 'Kadro kilitli');
        else if (you.valid) setText(el.draftStatus, 'Kilitlemeye hazır');
        else setText(el.draftStatus, 'Kadro kuruluyor');

        renderOpponent();
        renderPitch();
        renderMarket();
        renderChallenges();
        renderActions();
    }

    function renderOpponent() {
        var opponent = state && state.opponent;
        if (!opponent) {
            setText(el.oppName, 'Rakip bekleniyor');
            setText(el.oppLocked, 'Kadro açık');
            setText(el.oppSquadCount, '0/' + MAX_SLOTS);
            setText(el.oppSpent, formatEur(0));
            el.oppStatus.textContent = 'YOK';
            el.oppStatus.classList.remove('is-green', 'is-red');
            clearNode(el.oppChallenges);
            clearNode(el.oppSquad);
            return;
        }

        setText(el.oppName, opponent.name);
        setText(el.oppLocked, opponent.locked ? 'Kadro kilitli' : 'Kadro açık');
        setText(el.oppSquadCount, (opponent.slots_filled || 0) + '/' + MAX_SLOTS);
        setText(el.oppSpent, formatEur(opponent.spent));
        setText(el.oppStatus, opponent.connected ? 'BAĞLI' : 'KOPUK');
        el.oppStatus.classList.toggle('is-green', !!opponent.connected);
        el.oppStatus.classList.toggle('is-red', !opponent.connected);

        clearNode(el.oppChallenges);
        (opponent.challenges || []).forEach(function (challenge) {
            var row = createEl('div', 'fc-opp-challenge' + (challenge.satisfied ? ' is-done' : ''));
            row.appendChild(createEl('i'));
            row.appendChild(createEl('span', '', challenge.label));
            el.oppChallenges.appendChild(row);
        });

        clearNode(el.oppSquad);
        var slots = state.slots && state.slots.length ? state.slots : FALLBACK_SLOTS;
        slots.forEach(function (slot) {
            var player = (opponent.squad || {})[slot.key];
            if (player) el.oppSquad.appendChild(createEl('span', 'fc-opp-pill', player.name));
        });
    }

    function challengePercent(challenge) {
        var current = Number(challenge.current) || 0;
        var target = Number(challenge.target) || 1;
        if (challenge.type === 'club_max' || challenge.type === 'nation_max' || challenge.type === 'age_avg_max') {
            if (current <= 0) return 0;
            return Math.min(100, Math.round((target / current) * 100));
        }
        return Math.min(100, Math.round((current / target) * 100));
    }

    function isMaxChallenge(challenge) {
        return challenge.type === 'club_max' || challenge.type === 'nation_max' || challenge.type === 'age_avg_max';
    }

    function renderChallenges() {
        if (!state) return;
        var you = state.you;
        var challenges = you.challenges || [];
        var signature = JSON.stringify({
            locked: you.locked,
            items: challenges.map(function (challenge) {
                return [challenge.id, challenge.current, challenge.satisfied];
            })
        });
        if (signature === lastChallengeSignature) {
            setText(el.challengeBadge, challenges.filter(function (c) { return c.satisfied; }).length + '/' + challenges.length);
            return;
        }
        lastChallengeSignature = signature;

        clearNode(el.challengeList);
        challenges.forEach(function (challenge) {
            var done = !!challenge.satisfied;
            var over = isMaxChallenge(challenge) && Number(challenge.current) > Number(challenge.target);
            var row = createEl('div', 'fc-challenge' + (done ? ' is-done' : (over || (you.locked && !done) ? ' is-miss' : '')));
            var head = createEl('div', 'fc-challenge-head');
            head.appendChild(createEl('span', 'fc-challenge-icon', challenge.icon || '•'));
            head.appendChild(createEl('span', 'fc-challenge-label', challenge.label));
            head.appendChild(createEl('span', 'fc-challenge-count', challenge.detail || (challenge.current + '/' + challenge.target)));
            row.appendChild(head);
            var bar = createEl('div', 'fc-challenge-bar');
            var fill = createEl('span');
            fill.style.width = challengePercent(challenge) + '%';
            bar.appendChild(fill);
            row.appendChild(bar);
            el.challengeList.appendChild(row);
        });

        setText(el.challengeBadge, challenges.filter(function (c) { return c.satisfied; }).length + '/' + challenges.length);
    }

    function renderActions() {
        if (!state || state.room.status !== 'DRAFT') return;
        var you = state.you;
        var opponent = state.opponent;
        var filled = Number(you.slots_filled) || 0;
        var budget = Number(state.room.budget_eur) || 0;
        var spent = Number(you.spent) || 0;
        var bothLocked = !!you.locked && !!(opponent && opponent.locked);
        var enoughPlayers = (state.players || []).length >= MAX_PLAYERS;

        el.lockBtn.hidden = !!you.locked;
        el.unlockBtn.hidden = !you.locked;
        el.lockBtn.disabled = actionBusy || !you.valid || !!you.locked;
        el.unlockBtn.disabled = actionBusy;
        el.autoSquad.disabled = actionBusy || !!you.locked;
        if (!actionBusy) setText(el.autoSquad, 'Otomatik kadro oluştur');
        el.clearSquad.disabled = actionBusy || !!you.locked || !filled;
        el.startMatchBtn.disabled = actionBusy || !you.is_host || !bothLocked || !enoughPlayers;

        if (you.locked) {
            setText(el.actionHint, 'Kadron kilitli. Rakibin de kilitlemesini bekliyorsun.');
        } else if (filled < MAX_SLOTS) {
            setText(el.actionHint, (MAX_SLOTS - filled) + ' mevki daha doldurmalısın.');
        } else if (spent > budget) {
            setText(el.actionHint, 'Kadro bütçeyi aşıyor. Pahalı bir oyuncuyu çıkarmalısın.');
        } else {
            setText(el.actionHint, 'Kadron hazır. Kilitle ve rakibini bekle.');
        }

        if (you.is_host) {
            if (bothLocked) setText(el.hostHint, 'İki kadro da kilitli. Maçı başlatabilirsin.');
            else if (you.locked) setText(el.hostHint, 'Rakibin kadrosunu kilitlemesini bekle.');
            else setText(el.hostHint, 'Önce kendi kadronu kilitle.');
        } else {
            setText(el.hostHint, 'Maçı oda sahibi başlatır. Kadronu kilitlemeyi unutma.');
        }
    }

    function marketUrl(page) {
        var params = [
            'q=' + encodeURIComponent(marketFilters.q || ''),
            'group=' + encodeURIComponent(marketFilters.group || 'all'),
            'sort=' + encodeURIComponent(marketFilters.sort || 'rating'),
            'page=' + page
        ];
        if (marketFilters.affordable) params.push('affordable=1');
        return roomApi('market') + '?' + params.join('&');
    }

    async function loadMarket(reset) {
        if (!state || state.room.status !== 'DRAFT') return;
        if (marketPage.loading && !reset) return;
        if (!reset && !marketPage.hasMore) return;

        var requestId = marketPage.requestId + 1;
        marketPage.requestId = requestId;
        marketPage.loading = true;
        if (reset) {
            marketPage.page = 0;
            marketPage.hasMore = true;
        }
        if (reset && !marketPage.items.length) {
            setText(el.marketCount, 'Aranıyor…');
        }
        if (el.marketMore) {
            el.marketMore.disabled = true;
            el.marketMore.hidden = false;
            setText(el.marketMore, 'YÜKLENİYOR…');
        }

        try {
            var data = await api(marketUrl((reset ? 0 : marketPage.page) + 1));
            if (requestId !== marketPage.requestId) return;
            marketPage.page = Number(data.page) || 1;
            marketPage.pages = Number(data.pages) || 1;
            marketPage.total = Number(data.total) || 0;
            marketPage.hasMore = !!data.has_more;
            marketPage.items = reset
                ? (data.players || [])
                : marketPage.items.concat(data.players || []);
            marketPage.loaded = true;
            lastMarketSignature = '';
            renderMarket();
        } catch (error) {
            if (requestId !== marketPage.requestId) return;
            if (error.status === 401 || error.code === 'auth_required' || error.code === 'invalid_session') {
                handleActionError(error);
                return;
            }
            if (!marketPage.items.length) {
                clearNode(el.marketList);
                el.marketList.appendChild(createEl(
                    'div', 'fc-market-empty',
                    error.message || 'Transfer piyasası yüklenemedi. Tekrar dene.'
                ));
            } else {
                showToast(error.message || 'Daha fazla oyuncu yüklenemedi.', true);
            }
        } finally {
            if (requestId === marketPage.requestId) {
                marketPage.loading = false;
                renderMarket();
            }
        }
    }

    function scheduleMarketSearch() {
        clearTimeout(marketTimer);
        marketTimer = setTimeout(function () { loadMarket(true); }, 280);
    }

    function renderMarket() {
        if (!state || state.room.status !== 'DRAFT') return;
        var items = marketPage.items || [];
        var picks = {};
        (state.market || []).forEach(function (pick) {
            picks[String(pick.id)] = pick;
        });

        var signature = JSON.stringify({
            filters: marketFilters,
            selectedMarketId: selectedMarketId,
            selectedSlot: selectedSlot,
            locked: state.you.locked,
            loading: marketPage.loading,
            total: marketPage.total,
            hasMore: marketPage.hasMore,
            items: items.map(function (player) {
                var pick = picks[String(player.id)];
                return [player.id, pick ? [pick.picked_by, pick.picked_by_you, pick.slot] : null];
            })
        });
        if (signature === lastMarketSignature) {
            if (el.marketMore) {
                el.marketMore.hidden = !marketPage.hasMore;
                el.marketMore.disabled = marketPage.loading || actionBusy;
                setText(el.marketMore, marketPage.loading ? 'YÜKLENİYOR…' : 'DAHA FAZLA OYUNCU');
            }
            return;
        }
        lastMarketSignature = signature;

        var scrollTop = el.marketList.scrollTop;
        setText(el.marketCount, trNumber(marketPage.total, 0) + ' oyuncu');
        clearNode(el.marketList);

        if (!items.length) {
            el.marketList.appendChild(createEl(
                'div', 'fc-market-empty',
                marketPage.loading
                    ? 'Oyuncular yükleniyor…'
                    : 'Bu filtrelerle oyuncu bulunamadı. Aramayı temizlemeyi dene.'
            ));
        }

        var selectedSlotData = selectedSlot ? slotFor(selectedSlot) : null;
        items.forEach(function (player) {
            var pick = picks[String(player.id)] || null;
            var opponentPicked = !!(pick && pick.picked_by && !pick.picked_by_you);
            var mine = !!(pick && pick.picked_by_you);
            var classes = ['fc-player-card'];
            if (opponentPicked) classes.push('is-picked');
            if (mine) classes.push('is-mine');
            if (String(selectedMarketId) === String(player.id)) classes.push('is-selected');
            if (selectedSlotData && !slotAccepts(selectedSlotData, player)) classes.push('is-incompatible');

            var card = createEl('div', classes.join(' '));
            card.dataset.marketId = player.id;
            card.setAttribute('role', 'button');
            card.setAttribute('tabindex', '0');
            card.setAttribute('aria-pressed', String(selectedMarketId) === String(player.id) ? 'true' : 'false');
            card.draggable = !opponentPicked && !state.you.locked;
            card.title = player.name + ' · ' + (player.primary_position || '') + ' · ' + formatEur(player.value_eur);

            var avatar = createEl('span', 'fc-avatar', initials(player.name));
            if (player.image_url && /^(?:https?:\/\/|\/)/i.test(player.image_url)) {
                var image = document.createElement('img');
                image.alt = '';
                image.loading = 'lazy';
                image.referrerPolicy = 'no-referrer';
                image.addEventListener('error', function () { image.remove(); });
                image.src = player.image_url;
                avatar.appendChild(image);
            }

            var main = createEl('div', 'fc-player-main');
            main.appendChild(createEl('div', 'fc-player-name', player.name));
            var subParts = [
                player.primary_position,
                player.nation_label || player.nationality,
                player.club
            ].filter(Boolean);
            main.appendChild(createEl('div', 'fc-player-sub', subParts.join(' · ')));
            var tags = createEl('div', 'fc-player-tags');
            tags.appendChild(createEl('span', 'fc-tag' + (Number(player.age) < 25 ? ' is-gold' : ''), player.age + ' yaş'));
            if (player.league_label) tags.appendChild(createEl('span', 'fc-tag is-green', player.league_label));
            main.appendChild(tags);

            var side = createEl('div', 'fc-player-side');
            side.appendChild(createEl('span', 'fc-rating' + (Number(player.overall) >= 85 ? ' is-elite' : ''), player.overall));
            side.appendChild(createEl('span', 'fc-value', formatEur(player.value_eur)));
            if (opponentPicked) {
                side.appendChild(createEl('span', 'fc-picked-label', 'RAKİPTE'));
            } else if (mine) {
                var slotData = pick && pick.slot ? slotFor(pick.slot) : null;
                side.appendChild(createEl('span', 'fc-picked-label is-mine', slotData ? 'SENDE · ' + slotData.label : 'SENDE'));
            }
            card.appendChild(avatar);
            card.appendChild(main);
            card.appendChild(side);
            el.marketList.appendChild(card);
        });

        if (el.marketMore) {
            el.marketMore.hidden = !marketPage.hasMore;
            el.marketMore.disabled = marketPage.loading || actionBusy;
            setText(el.marketMore, marketPage.loading ? 'YÜKLENİYOR…' : 'DAHA FAZLA OYUNCU');
        }

        el.marketList.scrollTop = scrollTop;
        renderSelectedHint();
    }

    function renderSelectedHint() {
        clearNode(el.marketHint);
        var player = selectedMarketId ? marketPlayer(selectedMarketId) : null;
        if (!player) {
            el.marketHint.hidden = true;
            selectedMarketId = null;
            return;
        }
        el.marketHint.hidden = false;
        el.marketHint.appendChild(createEl('span', '', player.name + ' seçildi · mevkiye tıkla veya sürükle'));
        var clear = createEl('button', '', 'TEMİZLE');
        clear.type = 'button';
        clear.addEventListener('click', function () {
            selectedMarketId = null;
            renderMarket();
            renderPitch();
        });
        el.marketHint.appendChild(clear);
    }

    function renderPitch() {
        if (!state || state.room.status !== 'DRAFT') return;
        var you = state.you;
        var squad = you.squad || {};
        var slots = state.slots && state.slots.length ? state.slots : FALLBACK_SLOTS;
        var signature = JSON.stringify({
            locked: you.locked,
            selectedSlot: selectedSlot,
            selectedMarketId: selectedMarketId,
            squad: slots.map(function (slot) {
                var player = squad[slot.key];
                return [slot.key, player ? player.id : null];
            })
        });
        if (signature === lastPitchSignature) return;
        lastPitchSignature = signature;

        clearNode(el.pitchSlots);
        var filled = 0;
        slots.forEach(function (slot) {
            var player = squad[slot.key];
            var wrapper = createEl('div', 'fc-slot');
            wrapper.dataset.slot = slot.key;
            wrapper.style.left = slot.x + '%';
            wrapper.style.top = slot.y + '%';
            if (selectedSlot === slot.key) wrapper.classList.add('is-selected');

            if (player) {
                filled += 1;
                var card = createEl('div', 'fc-slot-card');
                card.dataset.slot = slot.key;
                card.setAttribute('role', 'button');
                card.setAttribute('tabindex', '0');
                card.draggable = !you.locked;
                card.title = player.name + ' · ' + (player.primary_position || '') + ' · ' + formatEur(player.value_eur);
                card.appendChild(createEl('span', 'fc-slot-rating', player.overall));
                card.appendChild(createEl('span', 'fc-slot-name', player.name));
                card.appendChild(createEl('span', 'fc-slot-meta', (player.primary_position || '') + ' · ' + formatEur(player.value_eur)));
                if (!you.locked) {
                    var remove = createEl('button', 'fc-slot-remove', '×');
                    remove.type = 'button';
                    remove.dataset.slot = slot.key;
                    remove.setAttribute('aria-label', player.name + ' oyuncusunu kadrodan çıkar');
                    card.appendChild(remove);
                }
                wrapper.appendChild(card);
            } else {
                var empty = createEl('div', 'fc-slot-empty');
                empty.dataset.slot = slot.key;
                empty.setAttribute('role', 'button');
                empty.setAttribute('tabindex', '0');
                empty.title = slot.full + ' · ' + (slot.accept || []).join('/');
                empty.appendChild(createEl('strong', '', slot.label));
                empty.appendChild(createEl('small', '', 'Sürükle'));
                wrapper.appendChild(empty);
            }
            el.pitchSlots.appendChild(wrapper);
        });

        setText(el.pitchBadge, filled + '/' + MAX_SLOTS);
        if (you.locked) {
            setText(el.pitchHint, 'Kadron kilitli. Değişiklik yapmak için kilidi aç.');
        } else if (selectedMarketId) {
            var selected = marketPlayer(selectedMarketId);
            setText(el.pitchHint, (selected ? selected.name : 'Oyuncu') + ' seçildi · uygun bir mevkiye tıkla.');
        } else if (selectedSlot) {
            var selectedSlotData = slotFor(selectedSlot);
            setText(el.pitchHint, (selectedSlotData ? selectedSlotData.label : 'Mevki') + ' seçildi · takas için başka bir mevkiye tıkla.');
        } else {
            setText(el.pitchHint, 'Bir oyuncu kartını sürükle veya önce oyuncuya sonra mevkiye tıkla.');
        }
    }

    function currentDragInfo() {
        if (!dragPayload) return null;
        var parts = dragPayload.split(':');
        if (parts.length !== 2) return null;
        if (parts[0] === 'market') return { kind: 'market', id: parts[1] };
        if (parts[0] === 'slot') return { kind: 'slot', from: parts[1] };
        return null;
    }

    function dropReason(info, toKey) {
        if (!info) return 'Sürüklenen öğe okunamadı.';
        if (!state || state.room.status !== 'DRAFT') return 'Kadro kurma aşaması kapalı.';
        if (state.you.locked) return 'Kadron kilitli. Önce kilidi aç.';
        var toSlot = slotFor(toKey);
        if (!toSlot) return 'Geçersiz mevki.';

        if (info.kind === 'market') {
            var player = marketPlayer(info.id);
            if (!player) return 'Oyuncu bulunamadı.';
            if (pickedByOpponent(player)) return 'Bu oyuncu rakibinin kadrosunda.';
            if (!slotAccepts(toSlot, player)) return player.name + ' ' + toSlot.label + ' mevkisinde oynayamaz.';
            return '';
        }

        var moving = (state.you.squad || {})[info.from];
        var fromSlot = slotFor(info.from);
        if (!moving || !fromSlot) return 'Taşınacak oyuncu bulunamadı.';
        if (info.from === toKey) return '';
        if (!slotAccepts(toSlot, moving)) return moving.name + ' ' + toSlot.label + ' mevkisinde oynayamaz.';
        var target = (state.you.squad || {})[toKey];
        if (target && !slotAccepts(fromSlot, target)) {
            return target.name + ' ' + fromSlot.label + ' mevkisinde oynayamaz.';
        }
        return '';
    }

    function clearDragHighlights() {
        if (el.pitchSlots) {
            var slots = el.pitchSlots.querySelectorAll('.is-dragover, .is-invalid');
            for (var i = 0; i < slots.length; i += 1) {
                slots[i].classList.remove('is-dragover', 'is-invalid');
            }
        }
        if (el.marketPanel) el.marketPanel.classList.remove('is-dragover');
        if (el.marketList) {
            var cards = el.marketList.querySelectorAll('.is-dragging');
            for (var j = 0; j < cards.length; j += 1) cards[j].classList.remove('is-dragging');
        }
    }

    function handleSlotDrop(toKey) {
        var info = currentDragInfo();
        clearDragHighlights();
        dragPayload = null;
        if (!info) return;
        var reason = dropReason(info, toKey);
        if (reason) {
            showToast(reason, true);
            return;
        }
        if (info.kind === 'market') {
            pickPlayer(info.id, toKey);
        } else if (info.from !== toKey) {
            swapSlots(info.from, toKey);
        }
    }

    function handleMarketDrop() {
        var info = currentDragInfo();
        clearDragHighlights();
        dragPayload = null;
        if (info && info.kind === 'slot') removePick(info.from);
    }

    function onSlotClick(slotKey) {
        if (!state || state.room.status !== 'DRAFT') return;
        var you = state.you;
        if (you.locked) {
            showToast('Kadron kilitli. Değişiklik için önce kilidi aç.', true);
            return;
        }
        if (selectedMarketId) {
            pickPlayer(selectedMarketId, slotKey);
            return;
        }
        if (selectedSlot && selectedSlot !== slotKey) {
            var from = selectedSlot;
            selectedSlot = null;
            swapSlots(from, slotKey);
            return;
        }
        if (selectedSlot === slotKey) {
            selectedSlot = null;
            renderPitch();
            return;
        }
        var player = (you.squad || {})[slotKey];
        if (player) {
            selectedSlot = slotKey;
            renderPitch();
            return;
        }
        showToast('Önce transfer piyasasından bir oyuncu seç veya sürükle.');
    }

    function onMarketClick(marketId) {
        if (!state || state.room.status !== 'DRAFT') return;
        var player = marketPlayer(marketId);
        if (!player) return;
        if (pickedByOpponent(player)) {
            showToast('Bu oyuncu rakibinin kadrosunda.', true);
            return;
        }
        if (state.you.locked) {
            showToast('Kadron kilitli. Değişiklik için önce kilidi aç.', true);
            return;
        }
        if (selectedSlot) {
            var slot = selectedSlot;
            selectedSlot = null;
            pickPlayer(marketId, slot);
            return;
        }
        selectedMarketId = String(selectedMarketId) === String(player.id) ? null : player.id;
        renderMarket();
        renderPitch();
    }

    function pickPlayer(marketId, slotKey) {
        if (!state || state.room.status !== 'DRAFT') return;
        if (state.you.locked) {
            showToast('Kadron kilitli. Değişiklik için önce kilidi aç.', true);
            return;
        }
        var player = marketPlayer(marketId);
        var slot = slotFor(slotKey);
        if (!player || !slot) return;
        if (pickedByOpponent(player)) {
            showToast('Bu oyuncu rakibinin kadrosunda.', true);
            return;
        }
        if (!slotAccepts(slot, player)) {
            showToast(player.name + ' ' + slot.label + ' mevkisinde oynayamaz.', true);
            return;
        }
        var ownPick = currentPick(player.id);
        if (ownPick && ownPick.picked_by_you && ownPick.slot === slotKey) {
            selectedMarketId = null;
            selectedSlot = null;
            renderMarket();
            renderPitch();
            return;
        }
        selectedMarketId = null;
        selectedSlot = null;
        renderMarket();
        renderPitch();
        perform('pick', { player_id: player.id, slot: slotKey });
    }

    function removePick(slotKey) {
        if (!state || state.room.status !== 'DRAFT') return;
        if (state.you.locked) {
            showToast('Kadron kilitli. Değişiklik için önce kilidi aç.', true);
            return;
        }
        if (!(state.you.squad || {})[slotKey]) return;
        selectedMarketId = null;
        selectedSlot = null;
        renderMarket();
        renderPitch();
        perform('remove', { slot: slotKey });
    }

    function swapSlots(fromSlot, toSlot) {
        if (!state || state.room.status !== 'DRAFT' || fromSlot === toSlot) return;
        selectedMarketId = null;
        selectedSlot = null;
        renderMarket();
        renderPitch();
        perform('swap', { from_slot: fromSlot, to_slot: toSlot });
    }

    function setBusy(button, busy, text) {
        if (!button) return;
        button.disabled = busy;
        if (!button.dataset.label) button.dataset.label = button.textContent;
        button.textContent = busy ? text : button.dataset.label;
    }

    function handleActionError(error) {
        if (error.status === 401 || error.code === 'auth_required' || error.code === 'invalid_session') {
            clearToken(true);
            closeSocket();
            stopPolling();
            roomExists = true;
            showGate(error.message || 'Oturum sona erdi. Yeniden katılmalısın.');
            return;
        }
        showToast(error.message || 'İşlem tamamlanamadı.', true);
        if (error.status === 409 || error.code === 'player_taken' || error.code === 'stale_state') {
            pollState();
        }
    }

    async function perform(path, payload) {
        if (actionBusy) return null;
        actionBusy = true;
        stateRequestId += 1;
        if (state && state.room.status === 'DRAFT') renderActions();
        if (state && state.room.status === 'WAITING') renderLobby();
        try {
            var data = await api(roomApi(path), 'POST', payload || {});
            if (data.state) applyState(data.state);
            return data;
        } catch (error) {
            handleActionError(error);
            return null;
        } finally {
            actionBusy = false;
            if (state) {
                if (state.room.status === 'DRAFT') {
                    renderActions();
                    renderPitch();
                    renderMarket();
                } else if (state.room.status === 'WAITING') {
                    renderLobby();
                }
            }
        }
    }

    function requestStartDraft() { perform('start-draft', {}); }
    function requestLock() { perform('lock', {}); }
    function requestUnlock() { perform('unlock', {}); }
    function requestStartMatch() { perform('start-match', {}); }
    function requestNewSeason() { perform('new-season', {}); }

    function requestClearSquad() {
        if (!state || state.room.status !== 'DRAFT') return;
        if (!state.you.slots_filled) {
            showToast('Kadro zaten boş.');
            return;
        }
        openConfirm({
            title: 'Kadroyu temizle',
            copy: 'Kadrondaki 11 oyuncunun tamamı transfer piyasasına geri döner. Bu işlem geri alınamaz.',
            confirmLabel: 'Temizle',
            onConfirm: function () { perform('clear', {}); }
        });
    }

    function requestAutoSquad() {
        if (!state || state.room.status !== 'DRAFT' || actionBusy) return;
        if (state.you.locked) {
            showToast('Kadron kilitli. Önce kilidi aç.', true);
            return;
        }
        var run = function () {
            setText(el.autoSquad, 'KADRO KURULUYOR...');
            perform('auto-fill', {}).then(function (data) {
                if (data) showToast('Görevlere uygun kadro kuruldu.');
            });
        };
        if (state.you.slots_filled) {
            openConfirm({
                title: 'Otomatik kadro oluştur',
                copy: 'Görevlere ve bütçeye uygun yeni bir 11 kişilik kadro kurulacak. Mevcut seçimlerin değiştirilecek.',
                confirmLabel: 'Oluştur',
                onConfirm: run
            });
            return;
        }
        run();
    }

    function openConfirm(options) {
        confirmAction = options.onConfirm || null;
        setText(el.confirmTitle, options.title || 'Onayla');
        setText(el.confirmCopy, options.copy || '');
        setText(el.confirmLeave, options.confirmLabel || 'Onayla');
        el.confirm.hidden = false;
        try { el.confirmLeave.focus(); } catch (error) { /* ignore */ }
    }

    function closeConfirm() {
        el.confirm.hidden = true;
        confirmAction = null;
    }

    function requestLeave() {
        openConfirm({
            title: 'Odadan ayrıl',
            copy: 'Odadan ayrılmak istediğine emin misin? Devam eden sezon varsa rakibin etkilenebilir.',
            confirmLabel: 'Ayrıl',
            onConfirm: leaveRoom
        });
    }

    async function leaveRoom() {
        try {
            await api(roomApi('leave'), 'POST', {});
        } catch (error) {
            // Leaving is best-effort; the local session is cleared either way.
        }
        clearToken(true);
        closeSocket();
        stopPolling();
        window.location.href = '/fcmanager/';
    }

    async function submitJoin(useStored) {
        if (!roomExists) {
            gateError('Bu kodla açılmış bir oda yok.');
            return;
        }
        var displayName = el.gateName.value.trim().slice(0, 30);
        if (!displayName) {
            gateError('Odaya katılmak için bir menajer adı gir.');
            el.gateName.focus();
            return;
        }
        var resumeToken = getToken() || (useStored ? getStoredToken() : '');
        gateError('');
        setBusy(el.gateJoin, true, 'KATILINIYOR…');
        if (!el.gateResume.hidden) el.gateResume.disabled = true;
        try {
            var data;
            try {
                data = await api('/fcmanager/api/rooms/join/', 'POST', {
                    room_code: roomCode,
                    name: displayName,
                    session_token: resumeToken
                });
            } catch (error) {
                if (!resumeToken || (error.code !== 'invalid_session' && error.status !== 401)) throw error;
                clearToken(true);
                data = await api('/fcmanager/api/rooms/join/', 'POST', {
                    room_code: roomCode,
                    name: displayName,
                    session_token: ''
                });
            }
            storeToken(data.session_token, displayName);
            localStorage.setItem(NAME_KEY, displayName);
            applyState(data.state);
            connectSocket();
            startPolling();
        } catch (error) {
            if (error.code === 'room_not_found' || error.status === 404) {
                roomExists = false;
                showGate(error.message || 'Oda bulunamadı.');
            } else {
                gateError(error.message || 'Odaya katılınamadı.');
            }
        } finally {
            setBusy(el.gateJoin, false);
            if (roomExists) el.gateResume.disabled = el.gateResume.hidden;
        }
    }

    var bootRetries = 0;

    async function boot() {
        if (!roomCode) {
            window.location.href = '/fcmanager/';
            return;
        }
        if (!roomExists) {
            showGate('Bu kodla açılmış bir oda yok. Kodu kontrol et veya ana sayfadan yeni bir oda kur.');
            return;
        }
        if (!getToken()) {
            showGate('');
            return;
        }
        showLoading(bootRetries ? 'Bağlantı yeniden kuruluyor…' : 'Oda bilgileri alınıyor…');
        try {
            var data = await api(roomApi('state'));
            bootRetries = 0;
            applyState(data.state);
            connectSocket();
            startPolling();
        } catch (error) {
            if (error.status === 401 || error.status === 404 ||
                error.code === 'invalid_session' || error.code === 'room_not_found') {
                clearToken(true);
                if (error.status === 404 || error.code === 'room_not_found') roomExists = false;
                showGate(error.message || 'Oturum sona erdi. Yeniden katılmalısın.');
                return;
            }
            bootRetries += 1;
            if (bootRetries <= 4) {
                showLoading('Bağlantı kuruluyor… yeniden deneniyor');
                setTimeout(boot, 1200 + bootRetries * 600);
            } else {
                showGate('Oda bilgileri alınamadı. Bağlantını kontrol edip yeniden dene.');
            }
        }
    }

    async function refreshState() {
        var requestId = ++stateRequestId;
        var data = await api(roomApi('state'));
        if (requestId !== stateRequestId) return null;
        applyState(data.state);
        return data;
    }

    async function pollState() {
        if (document.hidden || !getToken() || actionBusy) return;
        try {
            await refreshState();
            if (!socket || socket.readyState !== WebSocket.OPEN) {
                setConnection('online', 'Senkron');
            }
        } catch (error) {
            if (error.status === 401 || error.status === 404 ||
                error.code === 'invalid_session' || error.code === 'room_not_found') {
                clearToken(true);
                closeSocket();
                stopPolling();
                if (error.status === 404 || error.code === 'room_not_found') roomExists = false;
                showGate(error.message || 'Oturum sona erdi. Yeniden katılmalısın.');
            }
        }
    }

    function startPolling() {
        if (pollTimer || !getToken()) return;
        pollTimer = setInterval(pollState, 3500);
        pollState();
    }

    function stopPolling() {
        clearInterval(pollTimer);
        pollTimer = null;
    }

    function sendSocket(payload) {
        if (!socket || socket.readyState !== WebSocket.OPEN) return;
        try { socket.send(JSON.stringify(payload)); } catch (error) { /* ignore */ }
    }

    function startPing() {
        clearInterval(pingTimer);
        pingTimer = setInterval(function () {
            sendSocket({ type: 'ping' });
        }, 25000);
    }

    function handleSocketMessage(raw) {
        var data;
        try { data = JSON.parse(raw); } catch (error) { return; }
        if (!data || !data.type) return;
        if (data.type === 'state') {
            applyState(data);
            setConnection('online', 'Canlı');
        } else if (data.type === 'auth_ok') {
            setConnection('online', 'Canlı');
        } else if (data.type === 'auth_required') {
            sendSocket({ type: 'authenticate', session_token: getToken() });
        } else if (data.type === 'error') {
            if (data.code === 'auth_failed' || data.code === 'invalid_session') {
                clearToken(true);
                closeSocket();
                stopPolling();
                roomExists = true;
                showGate(data.message || 'Oturum sona erdi. Yeniden katılmalısın.');
            } else if (data.code !== 'error') {
                showToast(data.message || 'Bağlantı hatası.', true);
            }
        }
    }

    function scheduleReconnect() {
        if (!getToken()) return;
        clearTimeout(reconnectTimer);
        var delay = reconnectDelay + Math.floor(Math.random() * 400);
        reconnectDelay = Math.min(12000, reconnectDelay * 1.7);
        reconnectTimer = setTimeout(connectSocket, delay);
    }

    function connectSocket() {
        if (!getToken()) return;
        if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
        var protocol = window.location.protocol === 'https:' ? 'wss://' : 'ws://';
        var ws;
        try {
            ws = new WebSocket(protocol + window.location.host + '/fcmanager/ws/room/' + encodeURIComponent(roomCode) + '/');
        } catch (error) {
            scheduleReconnect();
            return;
        }
        socket = ws;
        setConnection('connecting', 'Eşitleniyor…');
        ws.onopen = function () {
            if (socket !== ws) return;
            reconnectDelay = 1000;
            sendSocket({ type: 'authenticate', session_token: getToken() });
            setConnection('online', 'Canlı');
            startPing();
        };
        ws.onmessage = function (event) {
            if (socket !== ws) return;
            handleSocketMessage(event.data);
        };
        ws.onclose = function () {
            if (socket !== ws) return;
            socket = null;
            clearInterval(pingTimer);
            pingTimer = null;
            setConnection('offline', 'Senkron');
            scheduleReconnect();
        };
        ws.onerror = function () { /* handled by close */ };
    }

    function closeSocket() {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
        clearInterval(pingTimer);
        pingTimer = null;
        if (socket) {
            var ws = socket;
            socket = null;
            try { ws.close(); } catch (error) { /* ignore */ }
        }
    }

    function hideResult() {
        el.result.hidden = true;
    }

    function stopMatchAnimation() {
        if (matchAnim.timer) clearTimeout(matchAnim.timer);
        matchAnim = { id: null, timer: null, index: 0, done: false, started: false };
        if (window.FCMatch3D) window.FCMatch3D.pause();
    }

    function profileSub(profile) {
        if (!profile) return 'Kadro hazır';
        return 'Güç ' + formatDecimal(profile.strength) + ' · Ort. ' + formatDecimal(profile.overall);
    }

    function placeholder(node, text) {
        clearNode(node);
        if (node) node.appendChild(createEl('div', 'fc-commentary-empty', text));
    }

    function renderMatch(match) {
        if (!state) return;
        if (!match) {
            setText(el.matchHomeName, '—');
            setText(el.matchAwayName, '—');
            setText(el.matchHomeSub, '—');
            setText(el.matchAwaySub, '—');
            setText(el.matchHomeScore, '0');
            setText(el.matchAwayScore, '0');
            placeholder(el.matchCommentary, 'Maç verisi bulunamadı.');
            placeholder(el.matchStats, 'İstatistik yok.');
            placeholder(el.matchChallenges, 'Görev sonucu yok.');
            el.matchSkip.hidden = true;
            el.newSeason.hidden = true;
            return;
        }

        var home = match.home || {};
        var away = match.away || {};
        var profiles = (match.stats && match.stats.profiles) || {};
        setText(el.matchHomeName, home.name || 'Ev sahibi');
        setText(el.matchAwayName, away.name || 'Deplasman');
        setText(el.matchHomeSub, profileSub(profiles.home));
        setText(el.matchAwaySub, profileSub(profiles.away));

        if (matchAnim.id !== match.id) {
            dismissedResultFor = '';
            startMatchAnimation(match);
        } else if (matchAnim.done) {
            renderFinalMatch(match);
        } else if (!matchAnim.started) {
            startMatchAnimation(match);
        }
    }

    function resetMatchView() {
        setText(el.matchHomeScore, '0');
        setText(el.matchAwayScore, '0');
        setText(el.matchMinute, "0'");
        setText(el.matchPhase, 'Maç başlıyor');
        setText(el.matchEventCount, '0 olay');
        if (el.matchProgress) el.matchProgress.style.width = '0%';
        el.matchPen.hidden = true;
        el.matchPen.textContent = '';
        clearNode(el.matchCommentary);
        placeholder(el.matchStats, 'İstatistikler maç sonunda açılır.');
        placeholder(el.matchChallenges, 'Görev sonuçları maç sonunda açılır.');
        el.matchSkip.hidden = false;
        el.newSeason.hidden = true;
        hideResult();
    }

    function startMatchAnimation(match) {
        if (!match) return;
        if (matchAnim.timer) clearTimeout(matchAnim.timer);
        matchAnim = { id: match.id, timer: null, index: 0, done: false, started: true };
        resetMatchView();
        if (window.FCMatch3D) {
            window.FCMatch3D.setMatch(match);
            window.FCMatch3D.start();
        }
        var events = match.events || [];

        function step() {
            if (matchAnim.id !== match.id || matchAnim.done) return;
            if (matchAnim.index >= events.length) {
                finishMatchAnimation(match);
                return;
            }
            var event = events[matchAnim.index];
            matchAnim.index += 1;
            renderMatchEvent(event, match);
            var delay = delayFor(events, event);
            matchAnim.timer = setTimeout(step, delay);
        }

        step();
    }

    // The replay aims for about two minutes of viewing time. Each event gets
    // an equal share, with goals and period breaks taking a little longer.
    var REPLAY_TARGET_MS = 118000;
    var REPLAY_BASE_MIN = 2500;
    var REPLAY_BASE_MAX = 4200;

    function delayFor(events, event) {
        var count = Math.max(1, (events || []).length);
        var base = Math.min(REPLAY_BASE_MAX, Math.max(REPLAY_BASE_MIN, REPLAY_TARGET_MS / count));
        if (event.phase === 'penalties') return Math.round(Math.min(1900, base * 0.6));
        if (event.type === 'goal') return Math.round(base * 1.5);
        if (event.type === 'kickoff') return Math.round(base * 1.1);
        if (event.type === 'half') return Math.round(base * 1.2);
        if (event.type === 'full') return Math.round(base * 1.3);
        return Math.round(base);
    }

    var EVENT_ICONS = {
        goal: '⚽', save: '🧤', miss: '😮', corner: '🚩', card: '🟨',
        offside: '🚫', chance: '⚡', kickoff: '🏁', half: '⏸️', full: '⏹️',
        penalty_scored: '⚽', penalty_missed: '❌'
    };

    function eventClass(type) {
        if (type === 'goal') return ' is-goal';
        if (type === 'card') return ' is-card';
        if (type === 'half') return ' is-half';
        if (type === 'full') return ' is-full';
        if (type === 'penalty_scored') return ' is-penalty';
        if (type === 'penalty_missed') return ' is-penalty-missed';
        return '';
    }

    function renderMatchEvent(event, match) {
        if (window.FCMatch3D) window.FCMatch3D.onEvent(event);
        var row = createEl('div', 'fc-event' + eventClass(event.type));
        row.appendChild(createEl('span', 'fc-event-minute', event.phase === 'penalties' ? 'PEN' : event.minute + "'"));
        row.appendChild(createEl('span', 'fc-event-icon', EVENT_ICONS[event.type] || '•'));
        row.appendChild(createEl('span', 'fc-event-text', event.text || ''));
        el.matchCommentary.appendChild(row);
        el.matchCommentary.scrollTop = el.matchCommentary.scrollHeight;
        setText(el.matchEventCount, el.matchCommentary.children.length + ' olay');

        if (event.phase === 'penalties') {
            if (event.pen_score) {
                el.matchPen.hidden = false;
                setText(el.matchPen, 'Penaltılar ' + event.pen_score[0] + ' - ' + event.pen_score[1]);
            }
            setText(el.matchMinute, 'PEN');
            setText(el.matchPhase, 'Penaltılar');
            if (el.matchProgress) el.matchProgress.style.width = '100%';
            return;
        }

        if (event.score) {
            setText(el.matchHomeScore, event.score[0]);
            setText(el.matchAwayScore, event.score[1]);
        }
        var minute = Number(event.minute) || 0;
        setText(el.matchMinute, minute + "'");
        if (el.matchProgress) el.matchProgress.style.width = Math.min(100, (minute / 90) * 100) + '%';

        if (event.type === 'kickoff') setText(el.matchPhase, 'İlk yarı');
        else if (event.type === 'half') setText(el.matchPhase, 'İlk yarı sonu');
        else if (event.type === 'full') {
            setText(el.matchPhase, match.home_pen === null || match.home_pen === undefined ? 'Maç sonu' : 'Penaltılar');
        } else if (event.type === 'goal') setText(el.matchPhase, 'Gol!');
        else setText(el.matchPhase, minute > 45 ? 'İkinci yarı' : 'İlk yarı');
    }

    function finishMatchAnimation(match) {
        if (!match) return;
        if (matchAnim.timer) clearTimeout(matchAnim.timer);
        matchAnim.timer = null;
        var events = match.events || [];
        while (matchAnim.index < events.length) {
            var event = events[matchAnim.index];
            matchAnim.index += 1;
            renderMatchEvent(event, match);
        }
        matchAnim.done = true;
        renderFinalMatch(match);
    }

    function skipMatchAnimation(match) {
        if (!match) return;
        if (matchAnim.id !== match.id || !matchAnim.started) startMatchAnimation(match);
        finishMatchAnimation(match);
    }

    function renderFinalMatch(match) {
        if (!match) return;
        var hasPens = match.home_pen !== null && match.home_pen !== undefined;
        setText(el.matchHomeScore, match.home_score);
        setText(el.matchAwayScore, match.away_score);
        setText(el.matchMinute, hasPens ? 'PEN' : "90'");
        setText(el.matchPhase, 'Maç sonu');
        if (el.matchProgress) el.matchProgress.style.width = '100%';
        if (hasPens) {
            el.matchPen.hidden = false;
            setText(el.matchPen, 'Penaltılar ' + match.home_pen + ' - ' + match.away_pen);
        } else {
            el.matchPen.hidden = true;
        }

        if (!el.matchCommentary.children.length) {
            (match.events || []).forEach(function (event) { renderMatchEvent(event, match); });
            setText(el.matchHomeScore, match.home_score);
            setText(el.matchAwayScore, match.away_score);
        }
        setText(el.matchEventCount, (match.events || []).length + ' olay');
        renderMatchStats(match);
        renderMatchChallenges(match);
        el.matchSkip.hidden = true;
        el.newSeason.hidden = !state.you.is_host;
        el.resultNew.hidden = !state.you.is_host;
        showResult(match);
    }

    function statRow(label, homeText, awayText, homeValue, awayValue) {
        var row = createEl('div', 'fc-stat-row');
        var head = createEl('div', 'fc-stat-head');
        head.appendChild(createEl('strong', '', homeText));
        head.appendChild(createEl('span', '', label));
        head.appendChild(createEl('strong', '', awayText));
        row.appendChild(head);
        var bar = createEl('div', 'fc-stat-bar');
        var homeNumber = Number(homeValue) || 0;
        var awayNumber = Number(awayValue) || 0;
        var total = homeNumber + awayNumber;
        var homePct = total > 0 ? (homeNumber / total) * 100 : 50;
        var home = createEl('span', 'is-home');
        home.style.width = homePct + '%';
        var away = createEl('span', 'is-away');
        away.style.width = (100 - homePct) + '%';
        bar.appendChild(home);
        bar.appendChild(away);
        row.appendChild(bar);
        return row;
    }

    function renderMatchStats(match) {
        var stats = match.stats || {};
        var home = stats.home;
        var away = stats.away;
        if (!home || !away) {
            placeholder(el.matchStats, 'İstatistik yok.');
            return;
        }
        clearNode(el.matchStats);
        el.matchStats.appendChild(statRow('Topla oynama', home.possession + '%', away.possession + '%', home.possession, away.possession));
        el.matchStats.appendChild(statRow('Şut', home.shots, away.shots, home.shots, away.shots));
        el.matchStats.appendChild(statRow('İsabetli şut', home.on_target, away.on_target, home.on_target, away.on_target));
        el.matchStats.appendChild(statRow('xG', trNumber(home.xg, 2), trNumber(away.xg, 2), home.xg, away.xg));
        el.matchStats.appendChild(statRow('Korner', home.corners, away.corners, home.corners, away.corners));
        el.matchStats.appendChild(statRow('Faul', home.fouls, away.fouls, home.fouls, away.fouls));
        el.matchStats.appendChild(statRow('Sarı kart', home.yellow_cards, away.yellow_cards, home.yellow_cards, away.yellow_cards));
        el.matchStats.appendChild(statRow('Pas isabeti', home.pass_accuracy + '%', away.pass_accuracy + '%', home.pass_accuracy, away.pass_accuracy));
    }

    function renderMatchChallenges(match) {
        clearNode(el.matchChallenges);
        var sides = [
            { key: 'home', snapshot: match.home },
            { key: 'away', snapshot: match.away }
        ];
        sides.forEach(function (side) {
            var snapshot = side.snapshot || {};
            var challenges = snapshot.challenges || [];
            var block = createEl('div', 'fc-match-side-block');
            var head = createEl('h3');
            head.appendChild(createEl('span', '', snapshot.name || (side.key === 'home' ? 'Ev sahibi' : 'Deplasman')));
            var done = challenges.filter(function (challenge) { return challenge.satisfied; }).length;
            head.appendChild(createEl('span', '', done + '/' + challenges.length));
            block.appendChild(head);
            if (!challenges.length) {
                block.appendChild(createEl('div', 'fc-muted', 'Görev tanımı yok.'));
            } else {
                var list = createEl('ul');
                challenges.forEach(function (challenge) {
                    var item = createEl('li', challenge.satisfied ? 'is-done' : '');
                    item.appendChild(createEl('i'));
                    item.appendChild(createEl('span', '', challenge.label));
                    list.appendChild(item);
                });
                block.appendChild(list);
            }
            el.matchChallenges.appendChild(block);
        });
    }

    function showResult(match) {
        if (!match || dismissedResultFor === match.id || !state || !state.you) return;
        var wasHidden = el.result.hidden;
        var home = match.home || {};
        var away = match.away || {};
        var homeName = home.name || 'Ev sahibi';
        var awayName = away.name || 'Deplasman';
        var hasPens = match.home_pen !== null && match.home_pen !== undefined;
        var won = match.winner_side === state.you.side;
        var title = match.winner_side ? (won ? 'Kazandın!' : 'Kaybettin') : 'Berabere';

        setText(el.resultTitle, title);
        var copy = homeName + ' ' + match.home_score + ' - ' + match.away_score + ' ' + awayName;
        if (hasPens) copy += ' · Penaltılar ' + match.home_pen + ' - ' + match.away_pen;
        if (match.stats && match.stats.summary) copy += ' · ' + match.stats.summary;
        setText(el.resultCopy, copy);

        clearNode(el.resultScore);
        el.resultScore.appendChild(createEl('strong', '', match.home_score));
        el.resultScore.appendChild(createEl('span', '', ':'));
        el.resultScore.appendChild(createEl('strong', '', match.away_score));

        var mvp = match.mvp || {};
        if (mvp.name) {
            el.resultMvp.hidden = false;
            clearNode(el.resultMvp);
            el.resultMvp.appendChild(document.createTextNode('⭐ Maçın oyuncusu: '));
            el.resultMvp.appendChild(createEl('strong', '', mvp.name));
            var mvpMeta = [];
            if (mvp.team) mvpMeta.push(mvp.team);
            if (mvp.goals) mvpMeta.push(mvp.goals + ' gol');
            if (mvp.assists) mvpMeta.push(mvp.assists + ' asist');
            if (mvp.rating) mvpMeta.push('reyting ' + trNumber(mvp.rating, 1));
            if (mvpMeta.length) el.resultMvp.appendChild(document.createTextNode(' · ' + mvpMeta.join(' · ')));
        } else {
            el.resultMvp.hidden = true;
            clearNode(el.resultMvp);
        }

        clearNode(el.resultStats);
        var stats = match.stats || {};
        var homeStats = stats.home || {};
        var awayStats = stats.away || {};
        var rows = [
            ['Topla oynama', homeStats.possession + '%', awayStats.possession + '%'],
            ['Şut', homeStats.shots, awayStats.shots],
            ['İsabetli şut', homeStats.on_target, awayStats.on_target],
            ['xG', trNumber(homeStats.xg, 2), trNumber(awayStats.xg, 2)],
            ['Görev', (home.challenges || []).filter(function (c) { return c.satisfied; }).length + '/' + (home.challenges || []).length,
                (away.challenges || []).filter(function (c) { return c.satisfied; }).length + '/' + (away.challenges || []).length]
        ];
        rows.forEach(function (row) {
            var item = createEl('div', 'fc-result-stat');
            item.appendChild(createEl('span', '', row[0]));
            item.appendChild(createEl('strong', '', row[1] + ' – ' + row[2]));
            el.resultStats.appendChild(item);
        });

        el.resultNew.hidden = !state.you.is_host;
        el.result.hidden = false;
        if (wasHidden) {
            try { el.resultClose.focus(); } catch (error) { /* ignore */ }
        }
    }

    function closeResult() {
        el.result.hidden = true;
        if (state && state.match) dismissedResultFor = state.match.id;
    }

    function targetElement(event) {
        var target = event.target;
        if (!target) return null;
        return target.nodeType === 1 ? target : target.parentElement;
    }

    function bindEvents() {
        el.gateJoin.addEventListener('click', function () { submitJoin(false); });
        el.gateResume.addEventListener('click', function () { submitJoin(true); });
        el.gateName.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                event.preventDefault();
                submitJoin(false);
            }
        });

        el.lobbyStart.addEventListener('click', requestStartDraft);
        el.lobbyCopy.addEventListener('click', function () {
            copyText(inviteUrl(), 'Davet linki kopyalandı.');
        });
        el.copyCode.addEventListener('click', function () {
            copyText(roomCode, 'Oda kodu kopyalandı.');
        });
        el.shareBtn.addEventListener('click', function () {
            copyText(inviteUrl(), 'Davet linki kopyalandı.');
        });
        el.leaveBtn.addEventListener('click', requestLeave);

        el.lockBtn.addEventListener('click', requestLock);
        el.unlockBtn.addEventListener('click', requestUnlock);
        el.startMatchBtn.addEventListener('click', requestStartMatch);
        el.clearSquad.addEventListener('click', requestClearSquad);
        el.autoSquad.addEventListener('click', requestAutoSquad);

        el.marketSearch.addEventListener('input', function () {
            marketFilters.q = el.marketSearch.value || '';
            scheduleMarketSearch();
        });
        var chips = el.marketGroups.querySelectorAll('[data-group]');
        for (var i = 0; i < chips.length; i += 1) {
            chips[i].addEventListener('click', function () {
                marketFilters.group = this.dataset.group || 'all';
                var all = el.marketGroups.querySelectorAll('[data-group]');
                for (var j = 0; j < all.length; j += 1) {
                    all[j].classList.toggle('is-active', all[j] === this);
                }
                loadMarket(true);
            });
        }
        el.marketSort.addEventListener('change', function () {
            marketFilters.sort = el.marketSort.value;
            loadMarket(true);
        });
        el.marketAffordable.addEventListener('change', function () {
            marketFilters.affordable = !!el.marketAffordable.checked;
            loadMarket(true);
        });
        if (el.marketMore) {
            el.marketMore.addEventListener('click', function () { loadMarket(false); });
        }
        el.marketList.addEventListener('scroll', function () {
            if (marketPage.loading || !marketPage.hasMore) return;
            var list = el.marketList;
            if (list.scrollTop + list.clientHeight >= list.scrollHeight - 140) {
                loadMarket(false);
            }
        });

        el.pitchSlots.addEventListener('click', function (event) {
            var target = targetElement(event);
            if (!target) return;
            var remove = target.closest('.fc-slot-remove');
            if (remove) {
                event.stopPropagation();
                removePick(remove.dataset.slot);
                return;
            }
            var slot = target.closest('.fc-slot');
            if (slot) onSlotClick(slot.dataset.slot);
        });
        el.pitchSlots.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            var target = targetElement(event);
            if (!target || target.closest('.fc-slot-remove')) return;
            var slot = target.closest('.fc-slot');
            if (!slot) return;
            event.preventDefault();
            onSlotClick(slot.dataset.slot);
        });

        el.marketList.addEventListener('click', function (event) {
            var target = targetElement(event);
            if (!target) return;
            var card = target.closest('.fc-player-card');
            if (card) onMarketClick(card.dataset.marketId);
        });
        el.marketList.addEventListener('keydown', function (event) {
            if (event.key !== 'Enter' && event.key !== ' ') return;
            var target = targetElement(event);
            if (!target) return;
            var card = target.closest('.fc-player-card');
            if (!card) return;
            event.preventDefault();
            onMarketClick(card.dataset.marketId);
        });

        el.marketList.addEventListener('dragstart', function (event) {
            var target = targetElement(event);
            if (!target) return;
            var card = target.closest('.fc-player-card');
            if (!card) return;
            var player = marketPlayer(card.dataset.marketId);
            if (!player || !state || state.you.locked || pickedByOpponent(player)) {
                event.preventDefault();
                return;
            }
            dragPayload = 'market:' + player.id;
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                try { event.dataTransfer.setData('text/plain', dragPayload); } catch (error) { /* ignore */ }
            }
            card.classList.add('is-dragging');
        });
        el.marketList.addEventListener('dragend', function () {
            dragPayload = null;
            clearDragHighlights();
        });

        el.pitchSlots.addEventListener('dragstart', function (event) {
            var target = targetElement(event);
            if (!target) return;
            var card = target.closest('.fc-slot-card');
            if (!card) return;
            var slotKey = card.dataset.slot;
            if (!state || state.you.locked || !(state.you.squad || {})[slotKey]) {
                event.preventDefault();
                return;
            }
            dragPayload = 'slot:' + slotKey;
            if (event.dataTransfer) {
                event.dataTransfer.effectAllowed = 'move';
                try { event.dataTransfer.setData('text/plain', dragPayload); } catch (error) { /* ignore */ }
            }
            var wrapper = card.closest('.fc-slot');
            if (wrapper) wrapper.classList.add('is-dragging');
        });
        el.pitchSlots.addEventListener('dragend', function () {
            dragPayload = null;
            clearDragHighlights();
        });

        el.pitchSlots.addEventListener('dragover', function (event) {
            var target = targetElement(event);
            if (!target) return;
            var slot = target.closest('.fc-slot');
            if (!slot) return;
            event.preventDefault();
            var reason = dropReason(currentDragInfo(), slot.dataset.slot);
            if (event.dataTransfer) event.dataTransfer.dropEffect = reason ? 'none' : 'move';
            var highlighted = el.pitchSlots.querySelectorAll('.is-dragover, .is-invalid');
            for (var i = 0; i < highlighted.length; i += 1) {
                if (highlighted[i] !== slot) highlighted[i].classList.remove('is-dragover', 'is-invalid');
            }
            slot.classList.remove('is-dragover', 'is-invalid');
            slot.classList.add(reason ? 'is-invalid' : 'is-dragover');
        });
        el.pitchSlots.addEventListener('dragleave', function (event) {
            var target = targetElement(event);
            if (!target) return;
            var slot = target.closest('.fc-slot');
            if (!slot) return;
            if (!event.relatedTarget || !slot.contains(event.relatedTarget)) {
                slot.classList.remove('is-dragover', 'is-invalid');
            }
        });
        el.pitchSlots.addEventListener('drop', function (event) {
            var target = targetElement(event);
            if (!target) return;
            var slot = target.closest('.fc-slot');
            if (!slot) return;
            event.preventDefault();
            handleSlotDrop(slot.dataset.slot);
        });

        if (el.marketPanel) {
            el.marketPanel.addEventListener('dragover', function (event) {
                if (!dragPayload || dragPayload.indexOf('slot:') !== 0) return;
                event.preventDefault();
                if (event.dataTransfer) event.dataTransfer.dropEffect = 'move';
                el.marketPanel.classList.add('is-dragover');
            });
            el.marketPanel.addEventListener('dragleave', function (event) {
                if (!event.relatedTarget || !el.marketPanel.contains(event.relatedTarget)) {
                    el.marketPanel.classList.remove('is-dragover');
                }
            });
            el.marketPanel.addEventListener('drop', function (event) {
                if (!dragPayload || dragPayload.indexOf('slot:') !== 0) return;
                event.preventDefault();
                handleMarketDrop();
            });
        }

        el.matchSkip.addEventListener('click', function () {
            if (state && state.match) skipMatchAnimation(state.match);
        });
        el.newSeason.addEventListener('click', requestNewSeason);
        el.resultNew.addEventListener('click', requestNewSeason);
        el.resultClose.addEventListener('click', closeResult);

        el.confirmCancel.addEventListener('click', closeConfirm);
        el.confirmLeave.addEventListener('click', function () {
            var action = confirmAction;
            closeConfirm();
            if (action) action();
        });

        document.addEventListener('keydown', function (event) {
            if (event.key !== 'Escape') return;
            if (!el.confirm.hidden) {
                closeConfirm();
                return;
            }
            if (!el.result.hidden) closeResult();
        });
        document.addEventListener('dragend', function () {
            dragPayload = null;
            clearDragHighlights();
        });
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden && getToken()) pollState();
        });
    }

    bindEvents();
    if (window.FCMatch3D && el.matchPitch3D) window.FCMatch3D.mount(el.matchPitch3D);
    boot();
})();
