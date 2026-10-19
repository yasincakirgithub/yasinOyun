// Ana sayfa - oda oluşturma ve katılma

document.addEventListener('DOMContentLoaded', () => {
    const createBtn = document.getElementById('create-btn');
    const joinBtn = document.getElementById('join-btn');
    const createBotBtn = document.getElementById('create-bot-btn');
    const botLevelSelect = document.getElementById('bot-level');
    const colorChoices = document.getElementById('color-choices');
    const timeChoices = document.getElementById('time-choices');
    const modeTabs = document.getElementById('mode-tabs');
    const modeHuman = document.getElementById('mode-human');
    const modeBot = document.getElementById('mode-bot');
    const roomCodeInput = document.getElementById('room-code-input');

    let botColor = 'w';
    let timeControl = 600;
    let increment = 0;

    if (timeChoices) {
        const initial = timeChoices.querySelector('.choice-chip.selected')
            || timeChoices.querySelector('.choice-chip');
        if (initial) {
            timeControl = Number(initial.dataset.time);
            increment = Number(initial.dataset.increment || 0);
        }
        timeChoices.addEventListener('click', (event) => {
            const btn = event.target.closest('.choice-chip');
            if (!btn) return;
            timeControl = Number(btn.dataset.time);
            increment = Number(btn.dataset.increment || 0);
            timeChoices.querySelectorAll('.choice-chip').forEach((el) => {
                el.classList.toggle('selected', el === btn);
            });
        });
    }

    if (modeTabs) {
        modeTabs.addEventListener('click', (event) => {
            const tab = event.target.closest('.mode-tab');
            if (!tab) return;
            const mode = tab.dataset.mode;
            modeTabs.querySelectorAll('.mode-tab').forEach((el) => {
                el.classList.toggle('selected', el === tab);
            });
            if (modeHuman) modeHuman.classList.toggle('hidden', mode !== 'human');
            if (modeBot) modeBot.classList.toggle('hidden', mode !== 'bot');
        });
    }

    createBtn.addEventListener('click', createGame);
    joinBtn.addEventListener('click', joinGame);
    if (createBotBtn) {
        createBotBtn.addEventListener('click', createBotGame);
    }
    if (colorChoices) {
        colorChoices.addEventListener('click', (event) => {
            const btn = event.target.closest('.choice-chip');
            if (!btn || !btn.dataset.color) return;
            botColor = btn.dataset.color;
            colorChoices.querySelectorAll('.choice-chip').forEach((el) => {
                el.classList.toggle('selected', el === btn);
            });
        });
    }
    roomCodeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') joinGame();
    });

    function storePlayer(roomCode, identifier) {
        sessionStorage.setItem(`satranc:player:${roomCode}`, identifier);
    }

    function enterRoom(roomCode) {
        window.location.href = `/satranc/${roomCode}/`;
    }

    function createGame() {
        createBtn.textContent = 'Oluşturuluyor...';
        createBtn.disabled = true;

        fetch('/satranc/api/create/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ time_control: timeControl, increment }),
        })
        .then((response) => response.json())
        .then((data) => {
            if (!data.success) {
                throw new Error(data.error || 'Bilinmeyen hata');
            }
            const roomCode = data.room_code;

            return fetch('/satranc/api/join/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_code: roomCode }),
            })
            .then((response) => response.json())
            .then((joinData) => {
                if (!joinData.success) {
                    throw new Error(joinData.error || 'Odaya katılınamadı');
                }
                storePlayer(roomCode, joinData.player_identifier);
                enterRoom(roomCode);
            });
        })
        .catch((error) => {
            console.error('Hata:', error);
            alert('Oyun kurulamadı: ' + error.message);
            createBtn.textContent = 'ODA KUR';
            createBtn.disabled = false;
        });
    }

    function createBotGame() {
        const level = botLevelSelect ? Number(botLevelSelect.value) : 4;
        createBotBtn.textContent = 'Hazırlanıyor...';
        createBotBtn.disabled = true;

        fetch('/satranc/api/create-bot/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                level,
                color: botColor,
                time_control: timeControl,
                increment,
            }),
        })
        .then((response) => response.json())
        .then((data) => {
            if (!data.success) {
                throw new Error(data.error || 'Bot oyunu kurulamadı');
            }
            storePlayer(data.room_code, data.player_identifier);
            enterRoom(data.room_code);
        })
        .catch((error) => {
            console.error('Hata:', error);
            alert('Bot oyunu kurulamadı: ' + error.message);
            createBotBtn.textContent = 'BOTA KARŞI OYNA';
            createBotBtn.disabled = false;
        });
    }

    function joinGame() {
        const roomCode = roomCodeInput.value.trim().toUpperCase();
        if (!roomCode) {
            alert('Lütfen bir oda kodu gir.');
            return;
        }

        joinBtn.textContent = 'Katılınıyor...';
        joinBtn.disabled = true;

        fetch('/satranc/api/join/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room_code: roomCode }),
        })
        .then((response) => response.json())
        .then((data) => {
            if (!data.success) {
                throw new Error(data.error || 'Bilinmeyen hata');
            }
            storePlayer(roomCode, data.player_identifier);
            enterRoom(roomCode);
        })
        .catch((error) => {
            console.error('Hata:', error);
            alert('Oyuna katılınamadı: ' + error.message);
            joinBtn.textContent = 'KATIL';
            joinBtn.disabled = false;
        });
    }
});
