// Ana sayfa - oda oluşturma ve katılma

document.addEventListener('DOMContentLoaded', () => {
    const createBtn = document.getElementById('create-btn');
    const joinBtn = document.getElementById('join-btn');
    const roomCodeInput = document.getElementById('room-code-input');
    const nameInput = document.getElementById('player-name-input');

    createBtn.addEventListener('click', createGame);
    joinBtn.addEventListener('click', joinGame);
    roomCodeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') joinGame();
    });
    if (nameInput) {
        nameInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') joinGame();
        });
        nameInput.addEventListener('input', () => {
            const card = nameInput.closest('.name-card');
            if (card) card.classList.remove('invalid');
        });
    }

    function getPlayerName() {
        const value = (nameInput && nameInput.value || '').trim();
        const card = nameInput && nameInput.closest('.name-card');
        if (!value) {
            if (card) card.classList.add('invalid');
            if (nameInput) nameInput.focus();
            alert('Lütfen oyuna başlamadan önce adını gir.');
            return null;
        }
        if (card) card.classList.remove('invalid');
        sessionStorage.setItem('satranc:playerName', value);
        return value;
    }

    function storePlayer(roomCode, identifier) {
        sessionStorage.setItem(`satranc:player:${roomCode}`, identifier);
    }

    function enterRoom(roomCode) {
        window.location.href = `/satranc/${roomCode}/`;
    }

    function createGame() {
        const playerName = getPlayerName();
        if (!playerName) return;

        createBtn.textContent = 'Oluşturuluyor...';
        createBtn.disabled = true;

        fetch('/satranc/api/create/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
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
                body: JSON.stringify({ room_code: roomCode, name: playerName }),
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
            createBtn.textContent = 'OYUN KUR';
            createBtn.disabled = false;
        });
    }

    function joinGame() {
        const roomCode = roomCodeInput.value.trim().toUpperCase();
        if (!roomCode) {
            alert('Lütfen bir oda kodu gir.');
            return;
        }

        const playerName = getPlayerName();
        if (!playerName) return;

        joinBtn.textContent = 'Katılınıyor...';
        joinBtn.disabled = true;

        fetch('/satranc/api/join/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room_code: roomCode, name: playerName }),
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
