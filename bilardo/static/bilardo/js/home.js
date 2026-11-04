/* Bilardo ana sayfası — mod, hedef, isteka ve oda seçimi */
(function () {
    'use strict';

    const modes = JSON.parse(document.getElementById('bilardo-modes').textContent);
    const cues = JSON.parse(document.getElementById('bilardo-cues').textContent);
    const modeById = Object.fromEntries(modes.map((mode) => [mode.id, mode]));

    const playTabs = document.querySelectorAll('[data-play]');
    const modeChoices = document.querySelectorAll('[data-mode]');
    const targetRow = document.getElementById('target-row');
    const targetChoices = document.getElementById('target-choices');
    const modeDescription = document.getElementById('mode-description');
    const cueCards = document.querySelectorAll('[data-cue]');
    const levelChoices = document.querySelectorAll('[data-level]');
    const nameInput = document.getElementById('player-name');
    const roomInput = document.getElementById('room-code-input');
    const statusEl = document.getElementById('home-status');

    let selectedPlay = 'online';
    let selectedMode = (document.querySelector('[data-mode].selected') || modeChoices[0]).dataset.mode;
    let selectedTarget = Number((document.querySelector('[data-mode].selected') || modeChoices[0]).dataset.target);
    let selectedCue = (document.querySelector('[data-cue].selected') || cueCards[0]).dataset.cue;
    let selectedLevel = (document.querySelector('[data-level].selected') || levelChoices[1]).dataset.level;

    const storedName = localStorage.getItem('bilardo:name') || '';
    const storedCue = localStorage.getItem('bilardo:cue') || '';
    if (nameInput) nameInput.value = storedName;
    if (storedCue) {
        selectedCue = storedCue;
        cueCards.forEach((card) => card.classList.toggle('selected', card.dataset.cue === selectedCue));
    }

    function setStatus(message, type) {
        if (!statusEl) return;
        statusEl.textContent = message || '';
        statusEl.className = 'bilardo-status' + (type ? ' is-' + type : '');
    }

    function renderTargets() {
        const mode = modeById[selectedMode];
        if (!mode) return;
        modeDescription.textContent = mode.description;

        const targets = mode.targets || [mode.default_target];
        if (!targets.includes(selectedTarget)) selectedTarget = mode.default_target;

        targetChoices.innerHTML = '';
        targets.forEach((value) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'choice-chip' + (value === selectedTarget ? ' selected' : '');
            button.dataset.target = String(value);
            button.textContent = value === 1 ? 'Oyunu kazan' : value + ' sayı';
            button.addEventListener('click', () => {
                selectedTarget = value;
                targetChoices.querySelectorAll('.choice-chip').forEach((chip) => {
                    chip.classList.toggle('selected', Number(chip.dataset.target) === value);
                });
            });
            targetChoices.appendChild(button);
        });

        targetRow.classList.toggle('is-single', targets.length === 1);
    }

    playTabs.forEach((tab) => {
        tab.addEventListener('click', () => {
            selectedPlay = tab.dataset.play;
            playTabs.forEach((item) => item.classList.toggle('selected', item === tab));
            document.getElementById('panel-online').classList.toggle('hidden', selectedPlay !== 'online');
            document.getElementById('panel-bot').classList.toggle('hidden', selectedPlay !== 'bot');
            setStatus('');
        });
    });

    modeChoices.forEach((chip) => {
        chip.addEventListener('click', () => {
            selectedMode = chip.dataset.mode;
            selectedTarget = Number(chip.dataset.target);
            modeChoices.forEach((item) => item.classList.toggle('selected', item === chip));
            renderTargets();
        });
    });

    cueCards.forEach((card) => {
        card.addEventListener('click', () => {
            selectedCue = card.dataset.cue;
            cueCards.forEach((item) => item.classList.toggle('selected', item === card));
            localStorage.setItem('bilardo:cue', selectedCue);
        });
    });

    levelChoices.forEach((chip) => {
        chip.addEventListener('click', () => {
            selectedLevel = chip.dataset.level;
            levelChoices.forEach((item) => item.classList.toggle('selected', item === chip));
        });
    });

    function currentName(fallback) {
        const value = (nameInput.value || '').trim().slice(0, 30);
        if (value) localStorage.setItem('bilardo:name', value);
        return value || fallback;
    }

    async function postJson(url, payload) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest',
            },
            credentials: 'same-origin',
            body: JSON.stringify(payload),
        });
        let data = {};
        try {
            data = await response.json();
        } catch (err) {
            data = { success: false, error: 'Sunucu yanıtı okunamadı.' };
        }
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'İşlem tamamlanamadı.');
        }
        return data;
    }

    function roomStorageKey(code) {
        return 'bilardo:room:' + code.toUpperCase() + ':identifier';
    }

    async function createRoom() {
        setStatus('Oda kuruluyor...', 'info');
        try {
            const data = await postJson('/bilardo/api/create/', {
                mode: selectedMode,
                target: selectedTarget,
                cue: selectedCue,
                name: currentName('Oyuncu 1'),
            });
            localStorage.setItem(roomStorageKey(data.room_code), data.player_identifier);
            setStatus('Oda hazır. Yönlendiriliyorsun...', 'success');
            window.location.href = '/bilardo/oda/' + encodeURIComponent(data.room_code) + '/';
        } catch (err) {
            setStatus(err.message, 'error');
        }
    }

    async function joinRoom() {
        const code = (roomInput.value || '').trim().toUpperCase();
        if (!code) {
            setStatus('Oda kodu gir.', 'error');
            roomInput.focus();
            return;
        }
        setStatus('Odaya katılınıyor...', 'info');
        try {
            const identifier = localStorage.getItem(roomStorageKey(code)) || '';
            const data = await postJson('/bilardo/api/join/', {
                room_code: code,
                player_identifier: identifier,
                cue: selectedCue,
                name: currentName('Oyuncu 2'),
            });
            localStorage.setItem(roomStorageKey(data.room_code), data.player_identifier);
            setStatus('Odaya katıldın. Yönlendiriliyorsun...', 'success');
            window.location.href = '/bilardo/oda/' + encodeURIComponent(data.room_code) + '/';
        } catch (err) {
            setStatus(err.message, 'error');
        }
    }

    function startLocal(bot) {
        const params = new URLSearchParams({
            target: String(selectedTarget),
            cue: selectedCue,
        });
        if (bot) {
            params.set('bot', '1');
            params.set('level', selectedLevel);
        }
        window.location.href = '/bilardo/yerel/' + encodeURIComponent(selectedMode) + '/?' + params.toString();
    }

    document.getElementById('create-btn').addEventListener('click', createRoom);
    document.getElementById('join-btn').addEventListener('click', joinRoom);
    document.getElementById('bot-btn').addEventListener('click', () => startLocal(true));

    if (roomInput) {
        roomInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                joinRoom();
            }
        });
    }

    if (nameInput) {
        nameInput.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                if (selectedPlay === 'online') createRoom();
            }
        });
    }

    renderTargets();
})();
