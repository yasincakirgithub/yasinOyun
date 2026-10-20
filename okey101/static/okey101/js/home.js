document.addEventListener('DOMContentLoaded', () => {
    const createBtn = document.getElementById('create-btn');
    const joinBtn = document.getElementById('join-btn');
    const roomCodeInput = document.getElementById('room-code-input');
    const nameInput = document.getElementById('player-name');
    const roundSelect = document.getElementById('round-count');
    const modeSelect = document.getElementById('game-mode');
    const penaltiesToggle = document.getElementById('penalties-enabled');
    const multipliersToggle = document.getElementById('multipliers-enabled');

    nameInput.value = localStorage.getItem('okey101:name') || '';

    function playerName() {
        const value = nameInput.value.trim().slice(0, 30);
        localStorage.setItem('okey101:name', value);
        return value;
    }

    function storePlayer(roomCode, identifier) {
        sessionStorage.setItem(`okey101:player:${roomCode}`, identifier);
    }

    function enterRoom(roomCode) {
        window.location.href = `/101-okey/${roomCode}/`;
    }

    async function postJson(url, payload) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'İstek başarısız oldu.');
        }
        return data;
    }

    async function createGame() {
        createBtn.disabled = true;
        createBtn.textContent = 'Oluşturuluyor...';
        try {
            const name = playerName();
            const room = await postJson('/101-okey/api/create/', {
                total_rounds: Number(roundSelect.value),
                mode: modeSelect.value,
                penalties_enabled: penaltiesToggle.checked,
                multipliers_enabled: multipliersToggle.checked,
            });
            const join = await postJson('/101-okey/api/join/', {
                room_code: room.room_code,
                name,
            });
            storePlayer(room.room_code, join.player_identifier);
            enterRoom(room.room_code);
        } catch (error) {
            alert('Oda kurulamadı: ' + error.message);
            createBtn.disabled = false;
            createBtn.textContent = 'ODA KUR';
        }
    }

    async function joinGame() {
        const roomCode = roomCodeInput.value.trim().toUpperCase();
        if (!roomCode) {
            alert('Oda kodu gerekli.');
            roomCodeInput.focus();
            return;
        }

        joinBtn.disabled = true;
        joinBtn.textContent = 'Katılınıyor...';
        try {
            const name = playerName();
            const existing = sessionStorage.getItem(`okey101:player:${roomCode}`);
            const join = await postJson('/101-okey/api/join/', {
                room_code: roomCode,
                name,
                player_identifier: existing || undefined,
            });
            storePlayer(roomCode, join.player_identifier);
            enterRoom(roomCode);
        } catch (error) {
            alert('Odaya katılınamadı: ' + error.message);
            joinBtn.disabled = false;
            joinBtn.textContent = 'KATIL';
        }
    }

    createBtn.addEventListener('click', createGame);
    joinBtn.addEventListener('click', joinGame);
    roomCodeInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') joinGame();
    });
    roomCodeInput.addEventListener('input', () => {
        roomCodeInput.value = roomCodeInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '');
    });
});
