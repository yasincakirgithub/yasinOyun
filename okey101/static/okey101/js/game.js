(() => {
    const body = document.body;
    const roomCode = (body.dataset.roomCode || '').toUpperCase();
    const maxPlayers = Number(body.dataset.maxPlayers || 4);
    const storageKey = `okey101:player:${roomCode}`;
    const nameKey = 'okey101:name';

    const COLOR_NAMES = { r: 'Kırmızı', y: 'Sarı', b: 'Mavi', k: 'Siyah' };
    const KIND_NAMES = { run: 'Seri', group: 'Grup', pair: 'Çift' };
    const STATUS_LABELS = {
        WAITING: 'Oyuncu bekleniyor',
        IN_PROGRESS: 'Devam ediyor',
        ROUND_END: 'El bitti',
        FINISHED: 'Oyun bitti',
        ABANDONED: 'Terk edildi',
    };

    let identifier = sessionStorage.getItem(storageKey) || '';
    const playerName = localStorage.getItem(nameKey) || '';
    let socket = null;
    let reconnectTimer = null;
    let reconnectDelay = 2000;
    let shouldReconnect = true;
    let state = null;
    let selection = new Set();
    let rackGroups = [];
    let lastPhaseKey = '';
    let toastTimer = null;
    let dragState = null;
    let suppressClickUntil = 0;
    const DRAG_THRESHOLD = 7;

    const el = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function isWild(tile) {
        if (!tile) return false;
        if (tile.fake) return true;
        if (!state || !state.okey) return false;
        return tile.color === state.okey.color && Number(tile.number) === Number(state.okey.number);
    }

    function tileHtml(tile, options = {}) {
        if (!tile) return '';
        const {
            selected = false,
            size = '',
            extra = '',
            staticMode = false,
            indicator = false,
            okey = false,
            drag = false,
        } = options;
        const color = tile.fake ? 'fake' : (tile.color || 'k');
        const classes = ['tile', `tile-${color}`];
        if (size) classes.push(size);
        if (staticMode) classes.push('tile-static');
        if (selected) classes.push('selected');
        if (isWild(tile) || okey) classes.push('is-wild');
        if (indicator) classes.push('is-indicator');
        if (okey) classes.push('is-okey');
        if (extra) classes.push(extra);

        const colorName = tile.fake ? 'Sahte okey' : (COLOR_NAMES[tile.color] || 'Taş');
        const label = tile.fake ? 'Sahte okey' : `${colorName} ${tile.number}`;
        const mark = tile.fake ? '' : (okey ? 'OKEY' : (isWild(tile) ? '★' : ''));
        const tag = staticMode ? 'span' : 'button';
        let attrs = staticMode ? '' : ` type="button" data-tile-id="${escapeHtml(tile.id)}"`;
        if (drag) attrs += ` data-drag-tile="${escapeHtml(tile.id)}"`;

        return `<${tag} class="${classes.join(' ')}"${attrs} title="${escapeHtml(label)}">`
            + `<span class="tile-number">${tile.fake ? '★' : escapeHtml(tile.number)}</span>`
            + `<span class="tile-mark">${mark}</span>`
            + `</${tag}>`;
    }

    function isMyTurn() {
        return Boolean(
            state
            && state.me
            && state.status === 'IN_PROGRESS'
            && Number(state.current_seat) === Number(state.me.seat)
        );
    }

    function currentPlayer() {
        if (!state) return null;
        return state.players.find((player) => Number(player.seat) === Number(state.current_seat)) || null;
    }

    function playerLabel(player) {
        if (!player) return '';
        return player.name || `Oyuncu ${Number(player.seat) + 1}`;
    }

    let rackGroupSeq = 0;

    function newRackGroupId() {
        rackGroupSeq += 1;
        return `rack-${Date.now()}-${rackGroupSeq}`;
    }

    function findRackGroup(groupId) {
        return rackGroups.find((group) => group.id === groupId) || null;
    }

    function rackMeldGroups() {
        return rackGroups
            .filter((group) => group.tiles.length >= 2)
            .map((group) => group.tiles);
    }

    function resetRackGroups() {
        const hand = state && state.me ? state.me.hand : [];
        rackGroups = hand.map((tile) => ({
            id: newRackGroupId(),
            tiles: [tile.id],
        }));
    }

    function reconcileRackGroups() {
        if (!state || !state.me) {
            rackGroups = [];
            selection = new Set();
            return;
        }
        const handIds = new Set(state.me.hand.map((tile) => tile.id));
        const used = new Set();
        const next = [];
        rackGroups.forEach((group) => {
            const tiles = [];
            group.tiles.forEach((tileId) => {
                if (handIds.has(tileId) && !used.has(tileId)) {
                    used.add(tileId);
                    tiles.push(tileId);
                }
            });
            if (tiles.length) next.push({ ...group, tiles });
        });
        state.me.hand.forEach((tile) => {
            if (!used.has(tile.id)) {
                next.push({ id: newRackGroupId(), tiles: [tile.id] });
            }
        });
        rackGroups = next;
        selection = new Set([...selection].filter((tileId) => handIds.has(tileId)));
    }

    function rackInsertIndex(x, y = null) {
        const entries = [...document.querySelectorAll('#my-hand .rack-group')].map((node, index) => {
            const rect = node.getBoundingClientRect();
            return {
                index,
                top: rect.top,
                bottom: rect.bottom,
                center: rect.left + rect.width / 2,
            };
        });
        if (!entries.length) return 0;

        const rows = [];
        entries.forEach((entry) => {
            let row = rows.find((item) => Math.abs(item.top - entry.top) < 6);
            if (!row) {
                row = { top: entry.top, bottom: entry.bottom, items: [] };
                rows.push(row);
            }
            row.top = Math.min(row.top, entry.top);
            row.bottom = Math.max(row.bottom, entry.bottom);
            row.items.push(entry);
        });
        rows.sort((a, b) => a.top - b.top);

        let row = rows[0];
        if (Number.isFinite(y)) {
            let best = Infinity;
            rows.forEach((candidate) => {
                const distance = y < candidate.top
                    ? candidate.top - y
                    : (y > candidate.bottom ? y - candidate.bottom : 0);
                if (distance < best) {
                    best = distance;
                    row = candidate;
                }
            });
        }

        for (const item of row.items) {
            if (x < item.center) return item.index;
        }
        return row.items[row.items.length - 1].index + 1;
    }

    function tileById(tileId) {
        if (!state || !state.me) return null;
        return state.me.hand.find((tile) => tile.id === tileId) || null;
    }

    function showToast(message, success = false) {
        const toast = el('toast');
        if (!toast) return;
        toast.textContent = message;
        toast.classList.toggle('success', success);
        toast.classList.remove('hidden');
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => toast.classList.add('hidden'), 4200);
    }

    function setConnection(mode) {
        const bar = el('connection-bar');
        if (!bar) return;
        bar.classList.remove('online', 'offline');
        if (mode === 'online') {
            bar.textContent = 'Bağlı';
            bar.classList.add('online');
        } else if (mode === 'offline') {
            bar.textContent = 'Bağlantı kesildi — yeniden bağlanılıyor...';
            bar.classList.add('offline');
        } else {
            bar.textContent = 'Bağlanıyor...';
        }
    }

    async function ensureIdentity() {
        if (identifier) return;
        try {
            const response = await fetch('/101-okey/api/join/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_code: roomCode, name: playerName }),
            });
            const data = await response.json().catch(() => ({}));
            if (response.ok && data.success) {
                identifier = data.player_identifier;
                sessionStorage.setItem(storageKey, identifier);
            } else {
                showToast(data.error || 'Odaya katılınamadı; izleyici olarak bağlanıyorsun.');
            }
        } catch (error) {
            showToast('Odaya katılınamadı; izleyici olarak bağlanıyorsun.');
        }
    }

    function connect() {
        if (!shouldReconnect) return;
        clearTimeout(reconnectTimer);
        setConnection('connecting');

        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const url = `${protocol}://${window.location.host}/101-okey/ws/game/${encodeURIComponent(roomCode)}/`;
        socket = new WebSocket(url);

        socket.addEventListener('open', () => {
            reconnectDelay = 2000;
            setConnection('online');
            if (identifier) {
                send('join_player', { name: playerName });
            } else {
                send('get_state');
            }
        });

        socket.addEventListener('message', (event) => {
            let message;
            try {
                message = JSON.parse(event.data);
            } catch (error) {
                return;
            }
            if (message.type === 'game_state') {
                handleState(message);
            } else if (message.type === 'error') {
                showToast(message.message || 'Bir hata oluştu.');
            }
        });

        socket.addEventListener('close', () => {
            setConnection('offline');
            if (shouldReconnect) {
                reconnectTimer = setTimeout(connect, reconnectDelay);
                reconnectDelay = Math.min(reconnectDelay * 1.6, 12000);
            }
        });

        socket.addEventListener('error', () => setConnection('offline'));
    }

    function send(type, payload = {}) {
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            showToast('Bağlantı kurulamadı. Lütfen bekle.');
            return false;
        }
        socket.send(JSON.stringify({
            type,
            player_identifier: identifier || undefined,
            ...payload,
        }));
        return true;
    }

    function handleState(nextState) {
        const phaseKey = `${nextState.status}:${nextState.round_number}`;
        const phaseChanged = phaseKey !== lastPhaseKey;
        lastPhaseKey = phaseKey;
        state = nextState;
        if (phaseChanged) {
            selection = new Set();
            resetRackGroups();
        } else {
            reconcileRackGroups();
        }
        render();
    }

    function render() {
        if (!state) return;
        renderStatus();
        renderTurnBanner();
        renderPlayers();
        renderTable();
        renderMelds();
        renderMeta();
        renderHand();
        renderProcessTargets();
        renderBoxes();
        updateActions();
        renderHint();
    }

    function renderStatus() {
        el('round-info').textContent = `${state.round_number} / ${state.total_rounds}`;
        el('points-threshold').textContent = state.points_threshold;
        el('pairs-threshold').textContent = state.pairs_threshold;
        el('stock-count').textContent = state.stock_count;
        el('stock-pile-count').textContent = state.stock_count;
    }

    function renderTurnBanner() {
        const banner = el('turn-banner');
        let text = '';
        if (state.status === 'WAITING') {
            text = `Oyuncular bekleniyor (${state.players.length}/${maxPlayers}) — ${state.min_players} oyuncu gerekli`;
        } else if (state.status === 'IN_PROGRESS') {
            if (!state.me) {
                text = 'İzleyici modundasın.';
            } else if (isMyTurn()) {
                text = state.turn_has_drawn
                    ? 'Sıra sende: per aç, taş işle veya taş at.'
                    : 'Sıra sende: desteden çek veya son atılanı al.';
            } else {
                text = `${playerLabel(currentPlayer())} oynuyor...`;
            }
        } else if (state.status === 'ROUND_END') {
            text = `El ${state.round_number} bitti.`;
        } else if (state.status === 'FINISHED') {
            text = 'Oyun bitti.';
        } else {
            text = STATUS_LABELS[state.status] || state.status;
        }
        banner.textContent = text;
        banner.classList.toggle('mine', isMyTurn());
    }

    function renderPlayers() {
        const bySeat = new Map();
        state.players.forEach((player) => bySeat.set(Number(player.seat), player));

        const html = [];
        for (let seat = 0; seat < maxPlayers; seat += 1) {
            const player = bySeat.get(seat);
            if (!player) {
                html.push('<div class="player-card empty">Boş koltuk</div>');
                continue;
            }
            const isTurn = state.status === 'IN_PROGRESS' && Number(state.current_seat) === seat;
            const classes = ['player-card'];
            if (player.is_me) classes.push('me');
            if (isTurn) classes.push('active');
            const name = escapeHtml(playerLabel(player));
            const opened = player.opened
                ? `<span class="opened">${player.route === 'pairs' ? 'Çift açtı' : 'Açtı'}</span>`
                : '<span class="closed">Kapalı</span>';
            const host = player.is_host
                ? '<span class="pc-host">Kurucu</span>'
                : '';
            const team = state.mode === 'pairs' && player.team
                ? `<span class="pc-team">Takım ${escapeHtml(player.team)}</span>`
                : '';
            const connected = player.connected
                ? ''
                : '<span class="gone">Bağlantı yok</span>';
            html.push(`
                <div class="${classes.join(' ')}">
                    <div class="pc-top">
                        <span class="pc-name">${name}${player.is_me ? ' (sen)' : ''}</span>
                        <span class="pc-seat">${seat + 1}</span>
                    </div>
                    <div class="pc-stats">
                        <span><b>${player.tile_count}</b> taş</span>
                        <span><b>${player.total_score}</b> puan</span>
                    </div>
                    <div class="pc-badges">${host}${team}${opened}${connected}</div>
                </div>
            `);
        }
        el('players-strip').innerHTML = html.join('');
    }

    function renderTable() {
        const indicatorZone = el('indicator-zone');
        indicatorZone.innerHTML = state.indicator
            ? tileHtml(state.indicator, { size: 'tile-small', staticMode: true, indicator: true })
            : '<span class="empty-note">—</span>';

        const okeyZone = el('okey-zone');
        okeyZone.innerHTML = state.okey
            ? tileHtml(
                { id: 'okey-display', color: state.okey.color, number: state.okey.number, fake: false },
                { size: 'tile-small', staticMode: true, okey: true }
            )
            : '<span class="empty-note">—</span>';

        el('discard-top').innerHTML = state.last_discard
            ? tileHtml(state.last_discard, { size: 'tile-small', staticMode: true })
            : '<span class="empty-note">Boş</span>';
    }

    function canProcessMeld(meld) {
        return Boolean(
            state.me
            && state.me.opened
            && state.me.route !== 'pairs'
            && meld.kind !== 'pair'
            && isMyTurn()
            && state.turn_has_drawn
            && selection.size === 1
        );
    }

    function renderMelds() {
        const container = el('melds');
        el('melds-count').textContent = `${state.melds.length} per`;
        if (!state.melds.length) {
            container.innerHTML = '<p class="empty-note">Henüz per açılmadı.</p>';
            return;
        }

        container.innerHTML = state.melds.map((meld) => {
            const processable = canProcessMeld(meld);
            const classes = ['meld'];
            if (processable) classes.push('can-process');
            const dropAttr = meld.kind === 'pair' ? '' : ' data-drop-zone="meld"';
            const owner = escapeHtml(meld.owner_name || `Oyuncu ${Number(meld.owner_seat) + 1}`);
            const tiles = meld.tiles.map((tile) => tileHtml(tile, {
                size: 'tile-mini',
                staticMode: true,
            })).join('');
            return `
                <div class="${classes.join(' ')}"${dropAttr} data-meld-id="${escapeHtml(meld.id)}" title="${processable ? 'Seçili taşı bu pere işle' : 'Taşı bu pere sürükleyerek işle'}">
                    <div class="meld-head">
                        <span class="meld-owner">${owner}</span>
                        <span class="meld-kind">${KIND_NAMES[meld.kind] || meld.kind}</span>
                        <span class="meld-score">${meld.score}p</span>
                    </div>
                    <div class="meld-tiles">${tiles}</div>
                </div>
            `;
        }).join('');
    }

    function renderMeta() {
        const meta = el('my-meta');
        if (!state.me) {
            meta.textContent = 'İzleyici';
            return;
        }
        const me = state.me;
        const route = me.opened ? (me.route === 'pairs' ? 'Çift' : 'Puan') : 'Kapalı';
        const parts = [
            `${playerLabel(me)}`,
            `${state.me.hand.length} taş`,
            `${me.hand_value} puan`,
            route,
        ];
        const groupCount = rackMeldGroups().length;
        if (groupCount) parts.push(`${groupCount} grup`);
        if (me.penalty) parts.push(`+${me.penalty} ceza`);
        meta.textContent = parts.join(' · ');
    }

    function renderHand() {
        const container = el('my-hand');
        if (!state.me) {
            container.innerHTML = '<p class="empty-note">İzleyici modundasın; elini göremezsin.</p>';
            return;
        }
        if (state.status === 'WAITING') {
            container.innerHTML = '<p class="empty-note">Taşlar oyun başlayınca dağıtılacak.</p>';
            return;
        }
        if (!rackGroups.length) {
            container.innerHTML = '<p class="empty-note">Elinde taş kalmadı.</p>';
            return;
        }
        container.innerHTML = rackGroups.map((group) => {
            const isMeld = group.tiles.length > 1;
            const tiles = group.tiles.map((tileId) => {
                const tile = tileById(tileId);
                if (!tile) return '';
                return `
                    <span class="rack-tile-wrap" data-drag-rack-tile="${escapeHtml(tileId)}"
                          data-rack-group-id="${escapeHtml(group.id)}"
                          data-rack-tile-id="${escapeHtml(tileId)}">
                        ${tileHtml(tile, {
                            selected: selection.has(tileId),
                            drag: true,
                        })}
                    </span>
                `;
            }).join('');
            return `
                <div class="rack-group${isMeld ? ' is-meld' : ''}"
                     data-rack-group-id="${escapeHtml(group.id)}"
                     data-drop-zone="rack-group">
                    ${isMeld ? `
                        <button class="rack-group-handle" type="button"
                                data-drag-rack-group="${escapeHtml(group.id)}"
                                title="Peri sürükle: masaya koy veya istekada taşı"
                                aria-label="Peri sürükle">⋮⋮</button>
                    ` : ''}
                    <div class="rack-group-tiles">${tiles}</div>
                </div>
            `;
        }).join('');
    }

    function renderProcessTargets() {
        const select = el('process-target');
        const previous = select.value;
        const targets = state.melds.filter((meld) => meld.kind !== 'pair');

        if (!targets.length) {
            select.innerHTML = '<option value="">İşlenecek per yok</option>';
            return;
        }

        select.innerHTML = targets.map((meld) => {
            const owner = meld.owner_name || `Oyuncu ${Number(meld.owner_seat) + 1}`;
            const label = `${owner} · ${KIND_NAMES[meld.kind] || meld.kind} · ${meld.score}p`;
            return `<option value="${escapeHtml(meld.id)}">${escapeHtml(label)}</option>`;
        }).join('');

        if (targets.some((meld) => meld.id === previous)) {
            select.value = previous;
        } else {
            select.selectedIndex = 0;
        }
    }

    function renderBoxes() {
        const waiting = state.status === 'WAITING';
        const roundEnd = state.status === 'ROUND_END';
        const finished = state.status === 'FINISHED';

        el('waiting-box').classList.toggle('hidden', !waiting);
        el('round-box').classList.toggle('hidden', !roundEnd);
        el('finished-box').classList.toggle('hidden', !finished);

        if (waiting) {
            const count = state.players.length;
            if (count < state.min_players) {
                el('waiting-text').textContent = `${count}/${maxPlayers} oyuncu hazır. Oyun ${state.min_players} oyuncuyla başlar.`;
            } else if (!state.is_host) {
                el('waiting-text').textContent = `${count}/${maxPlayers} oyuncu hazır. Oda kurucusunun oyunu başlatması bekleniyor.`;
            } else {
                el('waiting-text').textContent = `${count}/${maxPlayers} oyuncu hazır. Oyunu başlatabilirsin.`;
            }
            el('start-btn').classList.toggle('hidden', !state.is_host);
            el('start-btn').disabled = !state.can_start || !state.me;
        }

        if (roundEnd) {
            renderRoundSummary();
            const lastRound = state.round_number >= state.total_rounds;
            el('round-box-title').textContent = `El ${state.round_number} bitti`;
            el('next-round-btn').textContent = lastRound ? 'OYUNU BİTİR' : 'SONRAKİ EL';
            el('next-round-btn').disabled = !state.me || !state.is_host;
            el('next-round-btn').classList.toggle('hidden', !state.is_host);
            el('round-host-note').classList.toggle('hidden', Boolean(state.is_host));
        }

        if (finished) {
            renderFinished();
            el('restart-btn').disabled = !state.me || !state.is_host;
            el('restart-btn').classList.toggle('hidden', !state.is_host);
            el('finished-host-note').classList.toggle('hidden', Boolean(state.is_host));
        }
    }

    function renderRoundSummary() {
        const summary = el('round-summary');
        const result = state.last_result;
        if (!result) {
            summary.innerHTML = '<p class="empty-note">El özeti yok.</p>';
            return;
        }

        const badges = [];
        const multipliersOn = result.multipliers_enabled !== false;
        const penaltiesOn = result.penalties_enabled !== false;
        if (!penaltiesOn) badges.push('Cezasız');
        if (!multipliersOn) badges.push('Katlamasız');
        if (multipliersOn) {
            if (result.elden) badges.push('Elden bitiş ×2');
            if (result.okey_discard) badges.push('Okey atarak bitiş ×2');
            if (result.pairs_finish) badges.push('Çiftle bitiş ×2');
            if (result.multiplier > 1) badges.push(`Toplam çarpan ×${result.multiplier}`);
        }
        if (result.team_totals && Object.keys(result.team_totals).length) {
            badges.push(`Takım A: ${result.team_totals.A} · Takım B: ${result.team_totals.B}`);
        }
        if (result.reason === 'stock_empty') badges.push('Deste bitti');

        const rows = result.scores.map((score) => {
            const negative = score.score < 0;
            const detail = score.opened
                ? `${score.route === 'pairs' ? 'Çift' : 'Puan'} · elde ${score.hand_value}`
                : 'Açmadı';
            return `
                <div class="round-row">
                    <span>${escapeHtml(score.name)}</span>
                    <span class="panel-note">${detail}${score.penalty ? ` · +${score.penalty} ceza` : ''}</span>
                    <span class="score ${negative ? 'negative' : 'positive'}">${score.score > 0 ? '+' : ''}${score.score}</span>
                </div>
            `;
        }).join('');

        summary.innerHTML = `
            <div class="round-meta">${badges.map((badge) => `<span class="badge">${badge}</span>`).join('')}</div>
            <div class="round-row head">
                <span>Oyuncu</span>
                <span>Durum</span>
                <span class="score">Puan</span>
            </div>
            ${rows}
        `;
    }

    function renderFinished() {
        const teamMode = state.mode === 'pairs' && state.team_totals
            && Object.keys(state.team_totals).length > 0;
        const winner = state.players.find((player) => player.player_identifier === state.winner_identifier);

        if (teamMode && state.winner_team) {
            const members = state.players
                .filter((player) => player.team === state.winner_team)
                .map((player) => playerLabel(player))
                .join(' & ');
            el('finished-winner').textContent =
                `Kazanan: Takım ${state.winner_team} — ${members} (${state.team_totals[state.winner_team]} puan)`;
        } else {
            el('finished-winner').textContent = winner
                ? `Kazanan: ${playerLabel(winner)} (${winner.total_score} puan)`
                : 'Kazanan belirlenemedi.';
        }

        const ranked = [...state.players].sort((a, b) => {
            if (teamMode) {
                const diff = state.team_totals[a.team] - state.team_totals[b.team];
                if (diff !== 0) return diff;
            }
            return a.total_score - b.total_score;
        });
        el('final-standings').innerHTML = ranked.map((player, index) => {
            const team = teamMode && player.team ? `Takım ${escapeHtml(player.team)} · ` : '';
            return `
                <div class="standing-row ${index === 0 ? 'first' : ''}">
                    <span class="standing-rank">${index + 1}</span>
                    <span>${team}${escapeHtml(playerLabel(player))}${player.is_me ? ' (sen)' : ''}</span>
                    <span class="standing-score">${player.total_score}</span>
                </div>
            `;
        }).join('');
    }

    function updateActions() {
        const inProgress = state.status === 'IN_PROGRESS';
        const mine = isMyTurn();
        const drawn = Boolean(state.turn_has_drawn);
        const me = state.me;
        const opened = Boolean(me && me.opened);
        const canAct = inProgress && mine;
        const processTarget = el('process-target');
        const hasTarget = Boolean(processTarget.value);

        const takenInHand = Boolean(
            me
            && state.turn_taken_tile_id
            && me.hand.some((tile) => tile.id === state.turn_taken_tile_id)
        );

        el('draw-btn').disabled = !(canAct && !drawn);
        el('take-btn').disabled = !(canAct && !drawn && state.discard_count > 0);
        el('return-btn').disabled = !(
            canAct && drawn && state.turn_taken_discard && takenInHand
        );
        el('open-btn').disabled = !(
            canAct && drawn && me && !opened && rackMeldGroups().length > 0
        );
        el('auto-open-btn').disabled = !(canAct && drawn && me && !opened);
        el('discard-btn').disabled = !(canAct && drawn && selection.size === 1);
        el('process-btn').disabled = !(
            canAct
            && drawn
            && opened
            && me.route !== 'pairs'
            && selection.size === 1
            && hasTarget
        );

        el('stock-pile').disabled = !(canAct && !drawn);
        el('discard-pile').disabled = !(canAct && !drawn && state.discard_count > 0);

        processTarget.disabled = !(canAct && drawn && opened && me.route !== 'pairs' && hasTarget);
    }

    function renderHint() {
        let hint = '';
        if (!state.me) {
            hint = 'İzleyici modundasın.';
        } else if (state.status === 'WAITING') {
            hint = 'Oyunun başlaması bekleniyor.';
        } else if (state.status === 'ROUND_END') {
            hint = 'El bitti; sonuçları inceleyip sonraki ele geçebilirsin.';
        } else if (state.status === 'FINISHED') {
            hint = 'Oyun bitti.';
        } else if (!isMyTurn()) {
            hint = `Sıra ${playerLabel(currentPlayer())} oyuncusunda.`;
        } else if (!state.turn_has_drawn) {
            hint = 'Destedeki taşı eline sürükle veya son atılan taşı al.';
        } else if (
            state.turn_taken_discard
            && state.turn_taken_tile_id
            && state.me.hand.some((tile) => tile.id === state.turn_taken_tile_id)
        ) {
            hint = 'Atılan taşı kullanabilirsin; kullanmayacaksan “Atılanı Geri Koy” ile iade et.';
        } else if (!state.me.opened) {
            hint = 'Taşları istekada grupla; hazır olunca Elini Aç.';
        } else {
            hint = 'Grupları tutamaçtan masaya sürükle; taşları masadaki perlere bırakarak işle.';
            if (selection.size === 1 && state.melds.some((meld) => meld.kind !== 'pair')) {
                hint += ' Seçili taşı işlemek için masadaki bir pere tıkla.';
            }
        }
        el('action-hint').textContent = hint;
    }

    function moveRackTile(tileId, options = {}) {
        const {
            sourceGroupId,
            targetGroupId = null,
            targetTileId = '',
            insertIndex = null,
        } = options;
        const source = findRackGroup(sourceGroupId);
        const target = targetGroupId ? findRackGroup(targetGroupId) : null;
        if (!source) return;
        if (target === source && targetTileId === tileId) return;

        const sourceIndex = source.tiles.indexOf(tileId);
        if (sourceIndex < 0) return;
        source.tiles.splice(sourceIndex, 1);

        if (target) {
            let targetIndex = target.tiles.length;
            if (targetTileId) {
                const found = target.tiles.indexOf(targetTileId);
                if (found >= 0) targetIndex = found;
            }
            target.tiles.splice(targetIndex, 0, tileId);
            if (!source.tiles.length && source !== target) {
                rackGroups = rackGroups.filter((group) => group !== source);
            }
        } else {
            let targetIndex = insertIndex === null ? rackGroups.length : insertIndex;
            if (!source.tiles.length) {
                const emptyIndex = rackGroups.indexOf(source);
                if (emptyIndex >= 0) {
                    rackGroups.splice(emptyIndex, 1);
                    if (emptyIndex < targetIndex) targetIndex -= 1;
                }
            }
            targetIndex = Math.max(0, Math.min(targetIndex, rackGroups.length));
            rackGroups.splice(targetIndex, 0, {
                id: newRackGroupId(),
                tiles: [tileId],
            });
        }

        selection.delete(tileId);
        render();
    }

    function moveRackGroup(groupId, options = {}) {
        const { targetGroupId = null, insertIndex = null } = options;
        const sourceIndex = rackGroups.findIndex((group) => group.id === groupId);
        if (sourceIndex < 0) return;
        const group = rackGroups[sourceIndex];

        let targetIndex = insertIndex === null ? rackGroups.length : insertIndex;
        if (targetGroupId) {
            if (targetGroupId === groupId) return;
            const found = rackGroups.findIndex((item) => item.id === targetGroupId);
            if (found >= 0) targetIndex = found;
        }
        if (targetIndex === sourceIndex || targetIndex === sourceIndex + 1) return;

        rackGroups.splice(sourceIndex, 1);
        if (targetIndex > sourceIndex) targetIndex -= 1;
        targetIndex = Math.max(0, Math.min(targetIndex, rackGroups.length));
        rackGroups.splice(targetIndex, 0, group);
        render();
    }

    function openRack() {
        if (!isMyTurn()) {
            showToast('Sıra sende değil.');
            return;
        }
        if (!state.turn_has_drawn) {
            showToast('Elini açmadan önce taş çekmelisin.');
            return;
        }
        const groups = rackMeldGroups();
        if (!groups.length) {
            showToast('Önce istekada en az iki taştan oluşan perler oluştur.');
            return;
        }
        if (state.turn_taken_discard && state.turn_taken_tile_id) {
            const used = new Set(groups.flat());
            const takenInHand = state.me.hand.some(
                (tile) => tile.id === state.turn_taken_tile_id
            );
            if (takenInHand && !used.has(state.turn_taken_tile_id)) {
                showToast('Aldığın atılan taşı açılışta kullanmalı veya geri koymalısın.');
                return;
            }
        }
        send('open_hand', { melds: groups });
    }

    function layRackGroup(groupId) {
        const group = findRackGroup(groupId);
        if (!group || group.tiles.length < 2) {
            showToast('Masaya koymak için en az iki taşı grupla.');
            return;
        }
        if (!isMyTurn()) {
            showToast('Sıra sende değil.');
            return;
        }
        if (!state.turn_has_drawn) {
            showToast('Per koymadan önce taş çekmelisin.');
            return;
        }
        if (!state.me || !state.me.opened) {
            showToast('Perleri masaya koymak için önce elini aç.');
            return;
        }
        send('lay_melds', { melds: [group.tiles] });
    }

    function processSelected(meldId = null) {
        if (selection.size !== 1) return;
        if (!state.me || !state.me.opened || state.me.route === 'pairs') return;
        const target = meldId || el('process-target').value;
        if (!target) {
            showToast('İşlenecek per seç.');
            return;
        }
        const [tileId] = [...selection];
        send('process_tile', { tile_id: tileId, meld_id: target });
    }

    function findDropZone(x, y) {
        const target = document.elementFromPoint(x, y);
        if (!target) return null;
        return target.closest('[data-drop-zone]');
    }

    function dropAllowed(sourceType, zone) {
        if (!zone) return false;
        if (sourceType === 'stock') return ['hand', 'rack'].includes(zone);
        if (sourceType === 'rack-group') {
            return ['rack', 'rack-group', 'felt', 'table'].includes(zone);
        }
        return ['rack', 'rack-group', 'discard', 'meld'].includes(zone);
    }

    function clearDropHighlight() {
        document.querySelectorAll('.drop-hover').forEach((node) => node.classList.remove('drop-hover'));
    }

    function updateDropHighlight(target) {
        clearDropHighlight();
        if (target && dropAllowed(dragState.sourceType, target.dataset.dropZone)) {
            target.classList.add('drop-hover');
        }
    }

    function activateDrag(event) {
        const { sourceEl, sourceType } = dragState;
        const ghost = document.createElement('div');
        ghost.className = 'drag-ghost';
        if (sourceType === 'stock') {
            ghost.classList.add('drag-ghost-stock');
            ghost.innerHTML = '<span class="ghost-card">101</span>';
        } else if (sourceType === 'rack-group') {
            const clone = sourceEl.cloneNode(true);
            clone.removeAttribute('style');
            clone.removeAttribute('data-drop-zone');
            clone.removeAttribute('data-rack-group-id');
            clone.classList.add('drag-ghost-rack-group');
            clone.querySelectorAll('[data-drag-rack-group], [data-drag-rack-tile], [data-rack-tile-id]')
                .forEach((node) => {
                    node.removeAttribute('data-drag-rack-group');
                    node.removeAttribute('data-drag-rack-tile');
                    node.removeAttribute('data-rack-tile-id');
                });
            clone.setAttribute('aria-hidden', 'true');
            ghost.appendChild(clone);
        } else {
            const clone = sourceEl.cloneNode(true);
            clone.classList.remove('selected');
            clone.removeAttribute('data-drag-rack-tile');
            clone.removeAttribute('data-rack-tile-id');
            clone.removeAttribute('data-rack-group-id');
            clone.setAttribute('aria-hidden', 'true');
            ghost.appendChild(clone);
        }
        ghost.style.left = `${event.clientX}px`;
        ghost.style.top = `${event.clientY}px`;
        document.body.appendChild(ghost);
        document.body.classList.add('is-dragging', sourceType === 'stock' ? 'drag-stock' : 'drag-tile');
        sourceEl.classList.add('dragging-source');
        dragState.active = true;
        dragState.ghost = ghost;
    }

    function movePointerDrag(event) {
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        if (!dragState.active) {
            const distance = Math.hypot(
                event.clientX - dragState.startX,
                event.clientY - dragState.startY
            );
            if (distance < DRAG_THRESHOLD) return;
            activateDrag(event);
        }
        if (event.cancelable) event.preventDefault();
        dragState.ghost.style.left = `${event.clientX}px`;
        dragState.ghost.style.top = `${event.clientY}px`;
        updateDropHighlight(findDropZone(event.clientX, event.clientY));
    }

    function cleanupDrag() {
        if (!dragState) return;
        if (dragState.ghost) dragState.ghost.remove();
        if (dragState.sourceEl) dragState.sourceEl.classList.remove('dragging-source');
        document.body.classList.remove('is-dragging', 'drag-tile', 'drag-stock');
        clearDropHighlight();
        document.removeEventListener('pointermove', movePointerDrag);
        document.removeEventListener('pointerup', endPointerDrag);
        document.removeEventListener('pointercancel', cancelPointerDrag);
        dragState = null;
    }

    function endPointerDrag(event) {
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        const active = dragState.active;
        const target = active ? findDropZone(event.clientX, event.clientY) : null;
        const dropElement = active ? document.elementFromPoint(event.clientX, event.clientY) : null;
        const dropTile = dropElement
            ? dropElement.closest('#my-hand [data-rack-tile-id]')
            : null;
        const source = {
            ...dragState,
            dropTileId: dropTile ? dropTile.dataset.rackTileId : '',
            dropGroupId: dropTile ? dropTile.dataset.rackGroupId : '',
            rackIndex: active ? rackInsertIndex(event.clientX, event.clientY) : null,
            dropX: event.clientX,
            dropY: event.clientY,
        };
        cleanupDrag();
        if (!active) return;
        suppressClickUntil = Date.now() + 250;
        if (target && dropAllowed(source.sourceType, target.dataset.dropZone)) {
            performDrop(source, target);
        }
    }

    function cancelPointerDrag(event) {
        if (!dragState || event.pointerId !== dragState.pointerId) return;
        cleanupDrag();
    }

    function beginPointerDrag(event) {
        if (event.button !== undefined && event.button !== 0) return;
        const rackTile = event.target.closest('#my-hand [data-drag-rack-tile]');
        const stock = event.target.closest('[data-drag-source="stock"]');
        const groupHandle = event.target.closest('#my-hand [data-drag-rack-group]');
        if (!rackTile && !stock && !groupHandle) return;
        if (!state) return;
        if (stock && stock.disabled) return;
        if ((rackTile || groupHandle) && !isMyTurn()) return;

        let sourceEl = rackTile || stock;
        let sourceType = rackTile ? 'rack-tile' : 'stock';
        let tileId = rackTile ? rackTile.dataset.rackTileId : '';
        let groupId = rackTile ? rackTile.dataset.rackGroupId : '';

        if (groupHandle) {
            sourceEl = groupHandle.closest('.rack-group');
            sourceType = 'rack-group';
            tileId = '';
            groupId = groupHandle.dataset.dragRackGroup;
        }

        dragState = {
            sourceEl,
            sourceType,
            tileId,
            groupId,
            startX: event.clientX,
            startY: event.clientY,
            pointerId: event.pointerId,
            active: false,
            ghost: null,
        };
        document.addEventListener('pointermove', movePointerDrag, { passive: false });
        document.addEventListener('pointerup', endPointerDrag);
        document.addEventListener('pointercancel', cancelPointerDrag);
    }

    function discardDraggedTile(tileId) {
        if (!isMyTurn()) {
            showToast('Sıra sende değil.');
            return;
        }
        if (!state.turn_has_drawn) {
            showToast('Taş atmadan önce taş çekmelisin.');
            return;
        }
        send('discard_tile', { tile_id: tileId });
    }

    function processDraggedTile(tileId, meldId) {
        if (!isMyTurn()) {
            showToast('Sıra sende değil.');
            return;
        }
        if (!state.me || !state.me.opened) {
            showToast('Masadaki perlere taş işlemek için önce elini açmalısın.');
            return;
        }
        if (state.me.route === 'pairs') {
            showToast('Çiftle açan oyuncu seri/grup işleyemez.');
            return;
        }
        if (!state.turn_has_drawn) {
            showToast('Taş işlemeden önce taş çekmelisin.');
            return;
        }
        const meld = state.melds.find((item) => item.id === meldId);
        if (!meld || meld.kind === 'pair') {
            showToast('Bu pere taş işlenemiyor.');
            return;
        }
        send('process_tile', { tile_id: tileId, meld_id: meldId });
    }

    function performDrop(source, target) {
        const zone = target.dataset.dropZone;
        if (source.sourceType === 'stock') {
            if (!isMyTurn()) {
                showToast('Desteden taş çekmek için sıranın gelmesini bekle.');
                return;
            }
            if (state.turn_has_drawn) {
                showToast('Bu turda zaten taş çektin.');
                return;
            }
            send('draw_stock');
            return;
        }

        if (source.sourceType === 'rack-group') {
            if (zone === 'felt' || zone === 'table') {
                layRackGroup(source.groupId);
                return;
            }
            if (zone === 'rack-group' && target.dataset.rackGroupId) {
                moveRackGroup(source.groupId, {
                    targetGroupId: target.dataset.rackGroupId,
                });
                return;
            }
            if (zone === 'rack') {
                moveRackGroup(source.groupId, { insertIndex: source.rackIndex });
            }
            return;
        }

        const tileId = source.tileId;
        if (!tileId || !tileById(tileId)) {
            showToast('Taş artık elinde değil.');
            return;
        }

        if (zone === 'discard') {
            discardDraggedTile(tileId);
            return;
        }
        if (zone === 'meld') {
            processDraggedTile(tileId, target.dataset.meldId);
            return;
        }
        if (zone === 'rack-group') {
            moveRackTile(tileId, {
                sourceGroupId: source.groupId,
                targetGroupId: target.dataset.rackGroupId,
                targetTileId: source.dropTileId,
            });
            return;
        }
        if (zone === 'rack') {
            moveRackTile(tileId, {
                sourceGroupId: source.groupId,
                insertIndex: source.rackIndex,
            });
        }
    }

    function bindEvents() {
        document.addEventListener('click', (event) => {
            if (Date.now() < suppressClickUntil) {
                event.preventDefault();
                event.stopPropagation();
            }
        }, true);
        document.addEventListener('pointerdown', beginPointerDrag);

        el('copy-room-btn').addEventListener('click', async () => {
            try {
                await navigator.clipboard.writeText(roomCode);
                showToast('Oda kodu kopyalandı.', true);
            } catch (error) {
                showToast(`Oda kodu: ${roomCode}`);
            }
        });

        el('rules-btn').addEventListener('click', () => el('rules-modal').classList.remove('hidden'));
        el('rules-close').addEventListener('click', () => el('rules-modal').classList.add('hidden'));
        el('rules-modal').addEventListener('click', (event) => {
            if (event.target === el('rules-modal')) el('rules-modal').classList.add('hidden');
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') el('rules-modal').classList.add('hidden');
        });

        el('start-btn').addEventListener('click', () => send('start_game'));
        el('next-round-btn').addEventListener('click', () => send('next_round'));
        el('restart-btn').addEventListener('click', () => send('restart_game'));

        el('draw-btn').addEventListener('click', () => send('draw_stock'));
        el('stock-pile').addEventListener('click', () => send('draw_stock'));
        el('take-btn').addEventListener('click', () => send('take_discard'));
        el('return-btn').addEventListener('click', () => send('return_discard'));
        el('discard-pile').addEventListener('click', () => send('take_discard'));

        el('open-btn').addEventListener('click', openRack);
        el('auto-open-btn').addEventListener('click', () => send('auto_open'));
        el('process-btn').addEventListener('click', processSelected);
        el('process-target').addEventListener('change', render);
        el('discard-btn').addEventListener('click', () => {
            if (selection.size !== 1) return;
            const [tileId] = [...selection];
            send('discard_tile', { tile_id: tileId });
        });

        el('my-hand').addEventListener('click', (event) => {
            const tile = event.target.closest('[data-tile-id]');
            if (!tile) return;
            const tileId = tile.dataset.tileId;
            if (!isMyTurn()) {
                showToast('Sıra sende değil.');
                return;
            }
            if (selection.has(tileId)) selection.delete(tileId);
            else selection.add(tileId);
            render();
        });

        el('melds').addEventListener('click', (event) => {
            const meldEl = event.target.closest('[data-meld-id]');
            if (!meldEl) return;
            const meld = state.melds.find((item) => item.id === meldEl.dataset.meldId);
            if (!meld || !canProcessMeld(meld)) return;
            processSelected(meld.id);
        });

        window.addEventListener('beforeunload', () => {
            shouldReconnect = false;
            clearTimeout(reconnectTimer);
            if (socket) socket.close();
        });
    }

    async function init() {
        bindEvents();
        await ensureIdentity();
        connect();
    }

    init();
})();
