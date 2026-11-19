(function () {
    'use strict';

    var body = document.body;
    var roomCode = (body.dataset.roomCode || '').toUpperCase();
    var roomExists = body.dataset.roomExists === '1';

    var TOKEN_KEY = 'auction:session:' + roomCode;
    var SEAT_NAME_KEY = 'auction:seatname:' + roomCode;
    var NAME_KEY = 'auction:name';
    var MAX_PLAYERS = 8;

    var state = null;
    var socket = null;
    var reconnectTimer = null;
    var pingTimer = null;
    var pollTimer = null;
    var reconnectDelay = 1000;
    var toastTimer = null;
    var stateRequestId = 0;
    var actionBusy = false;
    var previousStatus = null;
    var timerAnimationFrame = null;

    var $ = function (id) { return document.getElementById(id); };
    var el = {
        loading: $('auction-loading'),
        loadingText: $('loading-text'),
        gate: $('auction-join-gate'),
        gateTitle: $('gate-title'),
        gateCopy: $('gate-copy'),
        gateName: $('gate-name'),
        gateError: $('gate-error'),
        gateJoin: $('gate-join-btn'),
        gateResume: $('gate-resume-btn'),
        lobby: $('auction-lobby'),
        lobbyCount: $('lobby-count'),
        lobbyStatus: $('lobby-status'),
        lobbyHost: $('lobby-host-badge'),
        lobbyPlayers: $('lobby-players'),
        lobbyStartHint: $('lobby-start-hint'),
        lobbyStartErrors: $('lobby-start-errors'),
        lobbyStart: $('lobby-start-btn'),
        lobbyCopy: $('lobby-copy-btn'),
        lobbySettings: $('lobby-settings'),
        lobbyThemeSelect: $('lobby-theme-select'),
        arena: $('auction-arena'),
        progressCurrent: $('progress-current'),
        progressTotal: $('progress-total'),
        progressFill: $('progress-fill'),
        characterImage: $('character-image'),
        characterName: $('character-name'),
        characterDescription: $('character-description'),
        characterPower: $('character-power'),
        currentBid: $('current-bid'),
        highestBidder: $('highest-bidder'),
        timerValue: $('timer-value'),
        timerBarFill: $('timer-bar-fill'),
        timerExtended: $('timer-extended'),
        myBudget: $('my-budget'),
        customBid: $('custom-bid'),
        placeBidBtn: $('place-bid-btn'),
        bidHint: $('bid-hint'),
        playerList: $('player-list'),
        myCollection: $('my-collection'),
        activeSynergies: $('active-synergies'),
        incompleteSynergies: $('incomplete-synergies'),
        results: $('auction-results'),
        resultsWinner: $('results-winner'),
        finalRankings: $('final-rankings'),
        playAgainBtn: $('play-again-btn'),
        backToLobbyBtn: $('back-to-lobby-btn'),
        toast: $('auction-toast'),
        confirm: $('auction-confirm'),
        confirmTitle: $('confirm-title'),
        confirmCopy: $('confirm-copy'),
        confirmCancel: $('confirm-cancel'),
        confirmOk: $('confirm-ok'),
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

    // Focus preservation helpers
    var focusedElementBeforeRender = null;
    var focusedElementSelector = null;

    function saveFocus() {
        var active = document.activeElement;
        if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) {
            focusedElementBeforeRender = active;
            // Create a selector to find it again after render
            if (active.id) {
                focusedElementSelector = '#' + active.id;
            } else if (active.name) {
                focusedElementSelector = '[name="' + active.name + '"]';
            } else {
                focusedElementSelector = null;
            }
        } else {
            focusedElementBeforeRender = null;
            focusedElementSelector = null;
        }
    }

    function restoreFocus() {
        if (focusedElementSelector) {
            var el = document.querySelector(focusedElementSelector);
            if (el) {
                el.focus();
                // Restore cursor position for text-like inputs (not number - setSelectionRange not supported)
                if (el.type === 'text' || el.type === 'search' || el.type === 'email' || el.type === 'password') {
                    var len = el.value.length;
                    el.setSelectionRange(len, len);
                }
            }
        }
        focusedElementBeforeRender = null;
        focusedElementSelector = null;
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

    function statLine(label, value) {
        var line = document.createElement('span');
        line.appendChild(createEl('span', 'auction-stat-label', label + ':'));
        line.appendChild(document.createTextNode(' ' + value));
        return line;
    }

    function formatMoney(cents) {
        return '$' + (cents / 100).toFixed(2);
    }

    function formatMoneyCompact(cents) {
        var dollars = cents / 100;
        if (dollars >= 1000000) return '$' + (dollars / 1000000).toFixed(1) + 'M';
        if (dollars >= 1000) return '$' + (dollars / 1000).toFixed(1) + 'K';
        return '$' + dollars.toFixed(2);
    }

    function escapeXml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&apos;');
    }

    function themeColors() {
        var selected = state && state.theme_info ? state.theme_info.selected_theme : null;
        return {
            accent: (selected && selected.accent) || '#a855f7',
            accent2: (selected && selected.accent_2) || '#ec4899',
        };
    }

    // Robust, attractive fallback for character portraits when a theme has no
    // artwork yet. Real images still win whenever they are available.
    function characterPlaceholder(name, subtitle) {
        var colors = themeColors();
        var label = initials(name);
        var text = escapeXml(label);
        var sub = escapeXml(subtitle || '');
        
        // Theme-appropriate decorative elements
        var accent = colors.accent;
        var accent2 = colors.accent2;
        var isDark = true;
        
        var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="500" height="700" viewBox="0 0 500 700">'
            + '<defs>'
            + '<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
            + '<stop offset="0" stop-color="' + accent2 + '"/>'
            + '<stop offset="0.5" stop-color="' + accent + '"/>'
            + '<stop offset="1" stop-color="#0a0614"/>'
            + '</linearGradient>'
            + '<radialGradient id="vignette" cx="0.5" cy="0.3" r="0.8">'
            + '<stop offset="0" stop-color="#000000" stop-opacity="0"/>'
            + '<stop offset="1" stop-color="#000000" stop-opacity="0.6"/>'
            + '</radialGradient>'
            + '<filter id="glow" x="-50%" y="-50%" width="200%" height="200%">'
            + '<feGaussianBlur stdDeviation="8" result="coloredBlur"/>'
            + '<feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>'
            + '</filter>'
            + '</defs>'
            // Background gradient
            + '<rect width="500" height="700" fill="url(#bg)"/>'
            // Subtle pattern overlay
            + '<rect width="500" height="700" fill="url(#vignette)"/>'
            // Decorative top accent bar
            + '<rect x="0" y="0" width="500" height="6" fill="' + accent + '" opacity="0.8"/>'
            // Central character silhouette area
            + '<circle cx="250" cy="280" r="140" fill="#080410" fill-opacity="0.45" stroke="' + accent + '" stroke-opacity="0.3" stroke-width="2" filter="url(#glow)"/>'
            // Character initials
            + '<text x="250" y="310" text-anchor="middle" font-family="Georgia, serif" font-size="110" font-weight="700" fill="#ffffff" fill-opacity="0.92" letter-spacing="-2">' + text + '</text>'
            // Power badge
            + '<g transform="translate(250, 460)">'
            + '<rect x="-70" y="-18" width="140" height="36" rx="18" fill="' + accent + '" fill-opacity="0.25" stroke="' + accent + '" stroke-opacity="0.5" stroke-width="1.5"/>'
            + '<text x="0" y="6" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="14" font-weight="700" fill="' + accent + '" fill-opacity="0.95">' + sub + '</text>'
            + '</g>'
            // Theme watermark
            + '<text x="250" y="660" text-anchor="middle" font-family="system-ui, -apple-system, sans-serif" font-size="11" font-weight="600" letter-spacing="3" fill="#ffffff" fill-opacity="0.25">CHARACTER AUCTION</text>'
            + '</svg>';
        return 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
    }

    function characterImageSrc(char) {
        if (!char) return '';
        return char.image || characterPlaceholder(char.name, 'Güç ' + (char.power || '?'));
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
        return '/auction/api/rooms/' + encodeURIComponent(roomCode) + '/' + path + '/';
    }

    function inviteUrl() {
        return window.location.origin + '/auction/room/' + encodeURIComponent(roomCode) + '/';
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
        el.arena.hidden = section !== 'arena';
        el.results.hidden = section !== 'results';
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
        if (!next || !next.room || !next.me) return;

        var prevStatus = state && state.room ? state.room.status : null;
        var status = next.room.status;

        if (prevStatus !== status) {
            stateRequestId += 1;
        }

        state = next;
        roomExists = true;

        var selectedTheme = next.theme_info && next.theme_info.selected_theme;
        if (selectedTheme) {
            body.style.setProperty('--theme-accent', selectedTheme.accent || '#a855f7');
            body.style.setProperty('--theme-accent-2', selectedTheme.accent_2 || '#ec4899');
        }

        if (status === 'WAITING' || status === 'CONFIGURING') {
            stopTimerAnimation();
            hideResult();
            el.playAgainBtn.hidden = true;
            showOnly('lobby');
            renderLobby();
            renderSettings();
            renderThemeSelect();
        } else if (status === 'THEME_SELECT') {
            stopTimerAnimation();
            hideResult();
            el.playAgainBtn.hidden = true;
            showOnly('lobby');
            renderLobby();
            renderSettings();
            renderThemeSelect();
        } else if (status === 'AUCTION') {
            stopTimerAnimation();
            hideResult();
            el.playAgainBtn.hidden = true;
            showOnly('arena');
            renderArena();
            startTimerAnimation();
        } else if (status === 'FINISHED') {
            stopTimerAnimation();
            showOnly('results');
            renderResults();
            el.playAgainBtn.hidden = !(next.me && next.me.is_host);
        } else if (status === 'ABANDONED') {
            stopTimerAnimation();
            hideResult();
            roomExists = false;
            showGate('Oyun terk edildi.');
        } else {
            roomExists = false;
            showGate('Bu oda kapatılmış.');
        }

        if (prevStatus && prevStatus !== status) {
            if (status === 'AUCTION' && prevStatus === 'THEME_SELECT') {
                showToast('Açık artırma başladı!');
            } else if (status === 'FINISHED' && prevStatus === 'AUCTION') {
                showToast('Açık artırma tamamlandı!');
            } else if (status === 'WAITING') {
                showToast('Oda yeniden bekleme modunda.');
            }
        }

        previousStatus = status;
    }

    function renderLobby() {
        if (!state) return;
        saveFocus();
        var players = state.players || [];
        var me = state.me;
        var enough = players.length >= 2;
        var host = players.find(function (p) { return p.is_host; });
        var status = state.room.status;
        var lobbyEditable = status === 'WAITING' || status === 'CONFIGURING' || status === 'THEME_SELECT';

        setText(el.lobbyCount, players.length + '/' + MAX_PLAYERS);
        setText(el.lobbyStatus, !lobbyEditable
            ? 'Oyun tamamlandı'
            : (enough ? 'Oyun başlatılabilir' : 'Oyuncular bekleniyor'));
        setText(el.lobbyHost, host ? 'Host: ' + host.display_name : 'Host: —');

        clearNode(el.lobbyPlayers);
        players.forEach(function (player) {
            var row = createEl('div', 'auction-lobby-player');
            var avatar = createEl('span', 'auction-lobby-avatar', initials(player.display_name));
            var main = createEl('div');
            var name = createEl('strong', '', player.display_name + (player.id === me.id ? ' (sen)' : ''));
            var small = createEl('small', '', player.is_host ? 'Host' : 'Oyuncu');
            main.appendChild(name);
            main.appendChild(small);
            var badge = createEl('span', 'auction-badge', player.connected ? 'BAĞLI' : 'KOPUK');
            badge.classList.toggle('is-green', !!player.connected);
            badge.classList.toggle('is-red', !player.connected);
            row.appendChild(avatar);
            row.appendChild(main);
            row.appendChild(badge);
            el.lobbyPlayers.appendChild(row);
        });

        var errors = [];
        if (lobbyEditable) {
            if (!enough) errors.push('Oyunu başlatmak için en az 2 oyuncu gerekli.');
            if (me.is_host && !state.room.theme_id) errors.push('Önce bir tema seçilmeli.');
        }
        clearNode(el.lobbyStartErrors);
        errors.forEach(function (message) {
            el.lobbyStartErrors.appendChild(createEl('li', '', message));
        });
        el.lobbyStartErrors.hidden = errors.length === 0;

        if (!lobbyEditable) {
            setText(el.lobbyStartHint, 'Oyun tamamlandı. Yeni bir oyun için oda sahibi TEKRAR OYNA\'ya basmalı.');
        } else if (!me.is_host) {
            setText(el.lobbyStartHint, 'Oyunu oda sahibi başlatacak. Ayarlar ve tema seçimi onun tarafından yapılır.');
        } else if (!enough) {
            setText(el.lobbyStartHint, 'Davet bağlantısını paylaş; ikinci oyuncu katıldığında ayarları yapıp başlatabilirsin.');
        } else if (!state.room.theme_id) {
            setText(el.lobbyStartHint, 'Önce bir tema seçmelisin.');
        } else {
            setText(el.lobbyStartHint, 'Hazırsın. Oyunu başlatabilirsin.');
        }
        el.lobbyStart.disabled = actionBusy || !lobbyEditable || !me.is_host || !enough || !state.room.theme_id;
        restoreFocus();
    }

    function renderSettings() {
        if (!state || !el.lobbySettings) return;
        saveFocus();
        var room = state.room;
        var me = state.me;
        if (room.status !== 'WAITING' && room.status !== 'CONFIGURING' && room.status !== 'THEME_SELECT') {
            el.lobbySettings.innerHTML = '<p class="auction-muted">Oyun tamamlandı. Oda sahibi yeni oyun başlattığında ayarlar yeniden düzenlenebilir.</p>';
            restoreFocus();
            return;
        }
        if (!me.is_host) {
            el.lobbySettings.innerHTML = '<p class="auction-muted">Sadece oda sahibi ayarları değiştirebilir.</p>';
            restoreFocus();
            return;
        }

        var html = '';
        var settings = [
            { key: 'starting_budget', label: 'Başlangıç Bütçesi ($)', type: 'number', min: 1, step: 1, value: room.starting_budget / 100 },
            { key: 'starting_bid', label: 'Başlangıç Teklifi ($)', type: 'number', min: 1, step: 1, value: room.starting_bid / 100 },
            { key: 'character_count', label: 'Karakter Sayısı', type: 'number', min: 1, max: 50, step: 1, value: room.character_count },
            { key: 'max_characters_per_player', label: 'Oyuncu Başına Max Karakter (0=sınırsız)', type: 'number', min: 0, max: 50, step: 1, value: room.max_characters_per_player || 0 },
            { key: 'auction_duration', label: 'Açık Artırma Süresi (sn)', type: 'number', min: 5, max: 300, step: 5, value: room.auction_duration },
            { key: 'max_players', label: 'Maksimum Oyuncu', type: 'number', min: 2, max: MAX_PLAYERS, step: 1, value: room.max_players },
            { key: 'extension_threshold', label: 'Uzatma Eşiği (sn)', type: 'number', min: 1, max: 10, step: 1, value: room.extension_threshold },
            { key: 'extension_duration', label: 'Uzatma Süresi (sn)', type: 'number', min: 1, max: 30, step: 1, value: room.extension_duration },
        ];

        settings.forEach(function (s) {
            var inputId = 'setting-' + s.key;
            html += '<label class="auction-setting">'
                + '<span>' + s.label + '</span>'
                + '<input id="' + inputId + '" type="' + s.type + '" data-key="' + s.key + '" name="' + s.key + '" min="' + (s.min || '') + '" max="' + (s.max || '') + '" step="' + (s.step || 1) + '" value="' + s.value + '">'
                + '</label>';
        });

        el.lobbySettings.innerHTML = html;

        el.lobbySettings.querySelectorAll('input').forEach(function (input) {
            input.addEventListener('change', function () {
                var key = this.dataset.key;
                var value = this.type === 'number' ? parseFloat(this.value) : this.value;
                var payload = {}; payload[key] = value;
                if (key === 'starting_budget' || key === 'starting_bid') {
                    payload[key] = Math.round(value * 100);
                }
                requestUpdateSettings(payload);
            });
        });
        restoreFocus();
    }

    function renderThemeSelect() {
        if (!state || !el.lobbyThemeSelect) return;
        saveFocus();
        var room = state.room;
        var me = state.me;
        var themes = state.theme_info?.themes || [];
        var selectedTheme = state.theme_info?.selected_theme;

        var canSelect = me.is_host && (room.status === 'WAITING' || room.status === 'CONFIGURING' || room.status === 'THEME_SELECT');

        var html = '<div class="auction-theme-grid-small">';
        themes.forEach(function (theme) {
            var isSelected = selectedTheme && selectedTheme.id === theme.id;
            var accent = theme.accent || '#a855f7';
            var accent2 = theme.accent_2 || '#ec4899';
            html += '<button type="button" class="auction-theme-card-small' + (isSelected ? ' selected' : '') + '"'
                + ' data-theme-id="' + escapeXml(theme.id) + '"'
                + ' style="--theme-accent:' + escapeXml(accent) + ';--theme-accent-2:' + escapeXml(accent2) + '"'
                + ' aria-pressed="' + (isSelected ? 'true' : 'false') + '">';
            html += '<span class="auction-theme-cover">';
            html += '<span class="auction-theme-icon" aria-hidden="true">' + escapeXml(theme.icon || '★') + '</span>';
            html += '<span class="auction-theme-name">' + escapeXml(theme.name) + '</span>';
            html += '</span>';
            html += '<span class="auction-theme-meta"><span>' + theme.character_count + ' karakter</span><span class="auction-theme-count">' + (isSelected ? 'SEÇİLİ' : 'SEÇ') + '</span></span>';
            if (isSelected) html += '<span class="auction-checkmark" aria-hidden="true">✓</span>';
            html += '</button>';
        });
        html += '</div>';

        if (!canSelect) {
            html = '<p class="auction-muted auction-theme-locked">Tema seçimi oda sahibi tarafından yapılır.</p>' + html;
        }

        el.lobbyThemeSelect.innerHTML = html;

        if (canSelect) {
            el.lobbyThemeSelect.querySelectorAll('.auction-theme-card-small').forEach(function (card) {
                card.addEventListener('click', function () {
                    requestSelectTheme(this.dataset.themeId);
                });
            });
        }
        restoreFocus();
    }

    function renderArena() {
        if (!state) return;
        saveFocus();
        var me = state.me;
        var room = state.room;
        var auction = state.current_auction;

        setText(el.progressCurrent, room.current_character_index + 1);
        setText(el.progressTotal, auction?.total_auctions || room.character_count);
        if (el.progressFill && auction && auction.total_auctions) {
            var pct = (room.current_character_index + 1) / auction.total_auctions;
            el.progressFill.style.setProperty('--progress', Math.max(0, Math.min(1, pct)).toFixed(3));
        }

        renderPlayers();
        renderCharacterShowcase(auction);
        renderTimer(auction);
        renderBidSection();
        renderCollection();
        restoreFocus();
    }

    function renderPlayers() {
        if (!state || !el.playerList) return;
        saveFocus();
        var players = state.players || [];
        var me = state.me;
        var isAuctionActive = state.room.status === 'AUCTION';
        var isFinished = state.room.status === 'FINISHED';

        clearNode(el.playerList);
        players.forEach(function (player) {
            var card = createEl('div', 'auction-player-card' + (player.id === me.id ? ' is-me' : ''));
            var avatar = createEl('span', 'auction-player-avatar', initials(player.display_name));
            var info = createEl('div', 'auction-player-info');
            var nameRow = createEl('div', 'auction-player-name');
            nameRow.appendChild(createEl('span', '', player.display_name));
            if (player.is_host) nameRow.appendChild(createEl('span', 'auction-player-host', 'HOST'));
            if (player.id === me.id) nameRow.appendChild(createEl('span', 'auction-you-tag', 'SEN'));
            var stats = createEl('div', 'auction-player-stats');
            stats.appendChild(statLine('Bütçe', formatMoneyCompact(player.budget)));
            // Power hidden during active auction, shown only in final results
            if (!isAuctionActive || isFinished) {
                stats.appendChild(statLine('Güç', player.total_power));
            } else {
                stats.appendChild(statLine('Güç', '???'));
            }
            stats.appendChild(statLine('Karakter', (player.owned_characters && player.owned_characters.length) || 0));
            info.appendChild(nameRow);
            info.appendChild(stats);
            card.appendChild(avatar);
            card.appendChild(info);
            el.playerList.appendChild(card);
        });
        restoreFocus();
    }

    function renderCharacterShowcase(auction) {
        if (!auction || !auction.character) {
            setText(el.characterName, '—');
            setText(el.characterDescription, '—');
            setText(el.characterPower, '—');
            setText(el.currentBid, '$0.00');
            setText(el.highestBidder, '—');
            el.characterImage.src = '';
            el.characterImage.alt = '';
            return;
        }

        var char = auction.character;
        var currentBidder = auction.current_bidder;

        setText(el.characterName, char.name);
        setText(el.characterDescription, char.description);
        // Power hidden during auction - revealed in final results
        setText(el.characterPower, '???');
        setText(el.currentBid, formatMoney(auction.current_bid));
        setText(el.highestBidder, currentBidder ? currentBidder.name : '—');

        el.characterImage.onerror = function () {
            el.characterImage.onerror = null;
            el.characterImage.src = characterPlaceholder(char.name, '');
        };
        el.characterImage.alt = char.name;
        if (el.characterImage.dataset.charId !== char.id) {
            el.characterImage.dataset.charId = char.id;
            el.characterImage.src = characterImageSrc(char);
        }
    }

    function renderTimer(auction) {
        if (!auction || !auction.timer) {
            setText(el.timerValue, '--');
            if (el.timerBarFill) el.timerBarFill.style.transform = 'scaleX(0)';
            el.timerExtended.hidden = true;
            return;
        }

        var timer = auction.timer;
        var remaining = timer.remaining_seconds || 0;
        var duration = timer.duration || 20;

        setText(el.timerValue, remaining);

        if (el.timerBarFill) {
            var pct = Math.max(0, remaining / duration);
            el.timerBarFill.style.transform = 'scaleX(' + pct + ')';
            el.timerBarFill.classList.remove('warning', 'danger');
            if (pct <= 0.15) el.timerBarFill.classList.add('danger');
            else if (pct <= 0.3) el.timerBarFill.classList.add('warning');
        }

        el.timerExtended.hidden = !timer.extended;
    }

    function renderBidSection() {
        if (!state) return;
        saveFocus();
        var me = state.me;
        var auction = state.current_auction;
        var currentBid = (auction && auction.current_bid) || 0;
        var isHighest = !!(auction && auction.current_bidder && auction.current_bidder.id === me.id);
        var active = state.room.status === 'AUCTION' && !me.left;
        var minBid = currentBid + 100;

        setText(el.myBudget, formatMoney(me.budget));

        el.customBid.disabled = actionBusy || !active || isHighest;
        el.customBid.min = (minBid / 100).toFixed(2);
        el.customBid.step = '1';
        el.customBid.placeholder = isHighest ? 'En yüksek teklif sende' : 'Min: ' + formatMoney(minBid);

        var canPlace = active && !isHighest && me.budget >= minBid;
        el.placeBidBtn.disabled = actionBusy || !canPlace;

        document.querySelectorAll('.auction-bid-quick').forEach(function (button) {
            var increment = parseInt(button.dataset.amount, 10) || 0;
            var target = currentBid + increment;
            var affordable = active && !isHighest && target <= me.budget;
            button.disabled = actionBusy || !affordable;
            button.title = affordable
                ? formatMoney(target) + ' teklif ver'
                : (isHighest ? 'En yüksek teklif zaten sende' : 'Bu teklif için bütçen yetersiz');
        });

        if (!active) {
            setText(el.bidHint, 'Açık artırma şu anda aktif değil.');
        } else if (isHighest) {
            setText(el.bidHint, 'Şu an en yüksek teklif sende. Rakibin bekleniyor.');
        } else if (me.budget < minBid) {
            setText(el.bidHint, 'Teklif vermek için yeterli bütçen yok. Min: ' + formatMoney(minBid));
        } else {
            setText(el.bidHint, 'Teklifin mevcut en yüksek tekliften yüksek olmalı. Min: ' + formatMoney(minBid));
        }
        restoreFocus();
    }

    function renderCollection() {
        if (!state) return;
        saveFocus();
        var me = state.me;
        var themeId = state.room.theme_id;

        clearNode(el.myCollection);
        if (me.owned_details && me.owned_details.length) {
            me.owned_details.forEach(function (char) {
                var item = createEl('div', 'auction-collection-item');
                var img = document.createElement('img');
                img.alt = char.name;
                img.loading = 'lazy';
                img.addEventListener('error', function onImageError() {
                    img.removeEventListener('error', onImageError);
                    img.src = characterPlaceholder(char.name, '');
                });
                img.src = characterImageSrc(char);
                // Power hidden during auction - revealed in final results
                var power = createEl('span', 'auction-collection-power', '???');
                item.appendChild(img);
                item.appendChild(power);
                item.title = char.name;
                el.myCollection.appendChild(item);
            });
        } else {
            el.myCollection.appendChild(createEl('div', 'auction-empty-collection', 'Henüz karakterin yok'));
        }

        clearNode(el.activeSynergies);
        if (me.active_synergies && me.active_synergies.length) {
            me.active_synergies.forEach(function (synergy) {
                var item = createEl('div', 'auction-synergy-item');
                item.appendChild(createEl('span', 'auction-synergy-icon', '★'));
                var info = createEl('div', 'auction-synergy-info');
                info.appendChild(createEl('span', 'auction-synergy-name', synergy.name));
                info.appendChild(createEl('span', 'auction-synergy-desc', synergy.description));
                item.appendChild(info);
                item.appendChild(createEl('span', 'auction-synergy-bonus', '+' + synergy.bonus));
                el.activeSynergies.appendChild(item);
            });
        } else {
            el.activeSynergies.appendChild(createEl('div', 'auction-empty-synergy', 'Henüz aktif senarji yok'));
        }

        clearNode(el.incompleteSynergies);
        if (me.incomplete_synergies && me.incomplete_synergies.length) {
            me.incomplete_synergies.slice(0, 5).forEach(function (synergy) {
                var item = createEl('div', 'auction-synergy-item incomplete');
                item.appendChild(createEl('span', 'auction-synergy-icon', '☆'));
                var info = createEl('div', 'auction-synergy-info');
                info.appendChild(createEl('span', 'auction-synergy-name', synergy.name));
                var roster = (state.theme_info && state.theme_info.selected_theme && state.theme_info.selected_theme.characters) || [];
                var missingNames = synergy.missing.map(function (id) {
                    var char = roster.find(function (c) { return c.id === id; });
                    return char ? char.name : id;
                }).join(', ');
                info.appendChild(createEl('span', 'auction-synergy-desc', 'Eksik: ' + missingNames));
                item.appendChild(info);
                item.appendChild(createEl('span', 'auction-synergy-bonus',
                    '+' + synergy.bonus + (synergy.bonus_type === 'percentage' ? '%' : '')));
                el.incompleteSynergies.appendChild(item);
            });
        } else {
            el.incompleteSynergies.appendChild(createEl('div', 'auction-empty-synergy', 'Yaklaşan senarji yok'));
        }
        restoreFocus();
    }

    function renderResults() {
        if (!state || !state.result) return;
        var result = state.result;
        var me = state.me;

        var topRank = result.rankings.length ? result.rankings[0].rank : 1;
        var winners = result.rankings.filter(function (ranking) { return ranking.rank === topRank; });
        if (winners.length > 1) {
            setText(el.resultsWinner, 'BERABERE: ' + winners.map(function (w) { return w.name; }).join(' · '));
        } else if (winners.length === 1) {
            var winner = winners[0];
            var isMe = winner.player_id === me.id;
            setText(el.resultsWinner, (isMe ? '🎉 TEBRİKLER! KAZANDIN! 🎉' : winner.name + ' KAZANDI!'));
        }

        clearNode(el.finalRankings);
        result.rankings.forEach(function (ranking) {
            var item = createEl('div', 'auction-ranking-item rank-' + ranking.rank);
            var badge = createEl('span', 'auction-rank-badge' + (ranking.rank <= 3 ? ' rank-' + ranking.rank : ' rank-other'), ranking.rank);
            var info = createEl('div', 'auction-ranking-info');
            var nameRow = createEl('div', 'auction-ranking-name');
            nameRow.appendChild(createEl('span', '', ranking.name));
            if (ranking.player_id === me.id) {
                nameRow.appendChild(createEl('span', 'auction-you-tag', 'SEN'));
            }
            var stats = createEl('div', 'auction-ranking-stats');
            stats.appendChild(statLine('Güç', ranking.total_power));
            stats.appendChild(statLine('Karakter', ranking.character_count));
            stats.appendChild(statLine('Kalan', formatMoneyCompact(ranking.budget)));
            info.appendChild(nameRow);
            info.appendChild(stats);
            item.appendChild(badge);
            item.appendChild(info);
            el.finalRankings.appendChild(item);
        });
    }

    function startTimerAnimation() {
        stopTimerAnimation();
        function tick() {
            if (!state || state.room.status !== 'AUCTION') return;
            var auction = state.current_auction;
            if (auction && auction.timer && auction.timer.deadline) {
                var now = new Date();
                var deadline = new Date(auction.timer.deadline);
                var remaining = Math.max(0, Math.ceil((deadline - now) / 1000));
                var duration = auction.timer.duration || 20;
                setText(el.timerValue, remaining);
                if (el.timerBarFill) {
                    var pct = Math.max(0, remaining / duration);
                    el.timerBarFill.style.transform = 'scaleX(' + pct + ')';
                    el.timerBarFill.classList.remove('warning', 'danger');
                    if (pct <= 0.15) el.timerBarFill.classList.add('danger');
                    else if (pct <= 0.3) el.timerBarFill.classList.add('warning');
                }
                el.timerExtended.hidden = !auction.timer.extended;
            }
            timerAnimationFrame = requestAnimationFrame(tick);
        }
        tick();
    }

    function stopTimerAnimation() {
        if (timerAnimationFrame) {
            cancelAnimationFrame(timerAnimationFrame);
            timerAnimationFrame = null;
        }
    }

    function hideResult() {
        el.results.hidden = true;
        el.playAgainBtn.hidden = true;
    }

    async function requestUpdateSettings(settings) {
        if (actionBusy) return;
        actionBusy = true;
        try {
            var data = await api(roomApi('settings'), 'POST', { settings: settings });
            if (data.state) applyState(data.state);
        } catch (error) {
            handleActionError(error);
        } finally {
            actionBusy = false;
        }
    }

    async function requestSelectTheme(themeId) {
        if (actionBusy) return;
        actionBusy = true;
        try {
            var data = await api(roomApi('theme'), 'POST', { theme_id: themeId });
            if (data.state) applyState(data.state);
        } catch (error) {
            handleActionError(error);
        } finally {
            actionBusy = false;
        }
    }

    async function requestStartAuction() {
        if (actionBusy) return;
        actionBusy = true;
        try {
            var data = await api(roomApi('start'), 'POST', {});
            if (data.state) applyState(data.state);
        } catch (error) {
            handleActionError(error);
        } finally {
            actionBusy = false;
        }
    }

    async function requestBid(amount) {
        if (actionBusy) return;
        actionBusy = true;
        try {
            var data = await api(roomApi('bid'), 'POST', { amount: amount });
            if (data.state) applyState(data.state);
        } catch (error) {
            handleActionError(error);
        } finally {
            actionBusy = false;
        }
    }

    async function requestNewGame() {
        if (actionBusy) return;
        actionBusy = true;
        try {
            var data = await api(roomApi('new-game'), 'POST', {});
            if (data.state) applyState(data.state);
        } catch (error) {
            handleActionError(error);
        } finally {
            actionBusy = false;
        }
    }

    async function requestLeave() {
        if (actionBusy) return;
        actionBusy = true;
        try {
            await api(roomApi('leave'), 'POST', {});
            closeSocket();
            stopPolling();
            roomExists = true;
            showGate('Odadan ayrıldın.');
        } catch (error) {
            handleActionError(error);
        } finally {
            actionBusy = false;
        }
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
    }

    function connectSocket() {
        if (socket) return;
        var protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        var wsUrl = protocol + '//' + window.location.host + '/auction/ws/room/' + roomCode + '/';
        socket = new WebSocket(wsUrl);

        socket.onopen = function () {
            console.log('Auction WS connected');
            reconnectDelay = 1000;
            setConnection('online', 'Bağlı');
            var token = getToken() || getStoredToken();
            if (token) {
                socket.send(JSON.stringify({ type: 'authenticate', session_token: token }));
            }
        };

        socket.onmessage = function (event) {
            try {
                var data = JSON.parse(event.data);
                if (data.type === 'state') {
                    applyState(data);
                } else if (data.type === 'auth_required') {
                    var sessionToken = getToken() || getStoredToken();
                    if (sessionToken && socket && socket.readyState === WebSocket.OPEN) {
                        socket.send(JSON.stringify({ type: 'authenticate', session_token: sessionToken }));
                    }
                } else if (data.type === 'auth_ok') {
                    console.log('Auction WS auth ok');
                } else if (data.type === 'error') {
                    showToast(data.message, true);
                    if (data.code === 'auth_failed' || data.code === 'invalid_session') {
                        clearToken(true);
                        closeSocket();
                        stopPolling();
                        roomExists = true;
                        showGate(data.message);
                    }
                } else if (data.type === 'pong') {
                    // ok
                }
            } catch (e) {
                console.error('Auction WS message error', e);
            }
        };

        socket.onclose = function (event) {
            console.log('Auction WS closed', event.code);
            socket = null;
            if (event.code === 4401) {
                clearToken(true);
                stopPolling();
                roomExists = true;
                showGate('Oturum sona erdi. Yeniden katılmalısın.');
                return;
            }
            if (!getToken()) return;
            setConnection('connecting', 'Yedek bağlantı');
            startPolling();
            if (!reconnectTimer) {
                reconnectTimer = setTimeout(function () {
                    reconnectTimer = null;
                    connectSocket();
                }, reconnectDelay);
                reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
            }
        };

        socket.onerror = function (error) {
            console.error('Auction WS error', error);
        };
    }

    function closeSocket() {
        if (socket) {
            socket.close();
            socket = null;
        }
        if (reconnectTimer) {
            clearTimeout(reconnectTimer);
            reconnectTimer = null;
        }
        reconnectDelay = 1000;
    }

    async function loadState() {
        try {
            var data = await api(roomApi('state'), 'GET');
            if (data.state) {
                applyState(data.state);
                return true;
            }
            return false;
        } catch (error) {
            if (error.status === 401 || error.code === 'invalid_session' || error.code === 'auth_required') {
                clearToken(true);
                roomExists = true;
                showGate(error.message || 'Oturum sona erdi. Yeniden katılmalısın.');
                return false;
            }
            if (error.status === 404) {
                roomExists = false;
                showGate('Oda bulunamadı.');
                return false;
            }
            return false;
        }
    }

    function startPolling() {
        stopPolling();
        // Fallback when the WebSocket is unavailable: keep the room usable over
        // HTTP so lobby and auction state never get stuck on the loading screen.
        pollTimer = setInterval(function () {
            if (!getToken()) return;
            fetch(roomApi('state'), { headers: authHeaders() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (data) { if (data && data.state) applyState(data.state); })
                .catch(function () { /* ignore */ });
        }, 2500);
    }

    function stopPolling() {
        if (pollTimer) {
            clearInterval(pollTimer);
            pollTimer = null;
        }
    }

    async function initRetry() {
        if (!getToken()) return;
        showLoading('Sunucuya yeniden bağlanılıyor…');
        var loaded = await loadState();
        if (loaded) {
            connectSocket();
            startPolling();
        } else if (getToken()) {
            setTimeout(initRetry, Math.min(10000, reconnectDelay += 1000));
        }
    }

    async function init() {
        var token = getToken() || getStoredToken();

        if (roomExists && token) {
            showLoading('Oda bilgileri alınıyor…');
            var loaded = await loadState();
            if (loaded) {
                connectSocket();
                startPolling();
            } else if (getToken()) {
                setTimeout(initRetry, 2000);
            }
        } else {
            showGate();
        }

        // Event listeners
        el.gateJoin.addEventListener('click', function () { submitJoin(false); });
        el.gateResume.addEventListener('click', function () { submitJoin(true); });
        el.gateName.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') submitJoin(false);
        });
        el.lobbyStart.addEventListener('click', requestStartAuction);
        el.lobbyCopy.addEventListener('click', function () { copyText(inviteUrl(), 'Davet linki kopyalandı.'); });
        el.copyCode.addEventListener('click', function () { copyText(roomCode, 'Oda kodu kopyalandı.'); });
        el.shareBtn.addEventListener('click', function () { copyText(inviteUrl(), 'Davet linki kopyalandı.'); });
        el.leaveBtn.addEventListener('click', function () {
            openConfirm({
                title: 'Odadan ayrıl',
                copy: 'Odadan ayrılmak istediğine emin misin? Devam eden açık artırma varsa diğer oyuncular etkilenebilir.',
                confirmLabel: 'Ayrıl',
                onConfirm: requestLeave
            });
        });
        el.playAgainBtn.addEventListener('click', requestNewGame);
        el.backToLobbyBtn.addEventListener('click', function () {
            if (state && state.room.status === 'FINISHED') {
                showOnly('lobby');
                renderLobby();
            }
        });
        el.confirmCancel.addEventListener('click', closeConfirm);
        el.confirmOk.addEventListener('click', function () {
            if (confirmAction) {
                confirmAction();
                closeConfirm();
            }
        });

        // Bid quick buttons add their increment to the current highest bid.
        document.querySelectorAll('.auction-bid-quick').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var increment = parseInt(this.dataset.amount, 10);
                var currentBid = (state && state.current_auction && state.current_auction.current_bid) || 0;
                if (!increment) return;
                requestBid(currentBid + increment);
            });
        });

        // Custom bid is entered in dollars and converted to cents.
        el.placeBidBtn.addEventListener('click', function () {
            var dollars = parseFloat(String(el.customBid.value).replace(',', '.'));
            if (isNaN(dollars) || dollars <= 0) {
                showToast('Geçerli bir tutar gir.', true);
                return;
            }
            requestBid(Math.round(dollars * 100));
        });

        el.customBid.addEventListener('keydown', function (event) {
            if (event.key === 'Enter') {
                el.placeBidBtn.click();
            }
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                closeConfirm();
            }
        });
    }

    function submitJoin(rejoin) {
        var name = el.gateName.value.trim();
        if (!name) {
            gateError('Oyuncu adı gerekli.');
            return;
        }
        if (name.length > 30) {
            gateError('Ad en fazla 30 karakter olmalı.');
            return;
        }
        el.gateJoin.disabled = true;
        el.gateJoin.textContent = 'KATILIYOR...';
        gateError('');

        var token = rejoin ? getStoredToken() : '';
        api('/auction/api/rooms/join/', 'POST', { room_code: roomCode, name: name, session_token: token })
            .then(function (data) {
                storeToken(data.session_token, data.player_id);
                roomExists = true;
                connectSocket();
                startPolling();
                if (data.state) applyState(data.state);
            })
            .catch(function (error) {
                gateError(error.message || 'Katılma başarısız.');
            })
            .finally(function () {
                el.gateJoin.disabled = false;
                el.gateJoin.textContent = 'KATIL';
            });
    }

    function openConfirm(options) {
        confirmAction = options.onConfirm || null;
        setText(el.confirmTitle, options.title || 'Onayla');
        setText(el.confirmCopy, options.copy || '');
        setText(el.confirmOk, options.confirmLabel || 'Onayla');
        el.confirm.hidden = false;
        try { el.confirmOk.focus(); } catch (error) { /* ignore */ }
    }

    function closeConfirm() {
        el.confirm.hidden = true;
        confirmAction = null;
    }

    // Initialize
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();