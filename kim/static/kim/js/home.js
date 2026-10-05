// Ana sayfa - oda oluşturma ve katılma

document.addEventListener('DOMContentLoaded', () => {
    const createBtn = document.getElementById('create-btn');
    const joinBtn = document.getElementById('join-btn');
    const roomCodeInput = document.getElementById('room-code-input');

    createBtn.addEventListener('click', createGame);
    joinBtn.addEventListener('click', joinGame);
    roomCodeInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') joinGame();
    });

    function storePlayer(roomCode, identifier) {
        sessionStorage.setItem(`kim:player:${roomCode}`, identifier);
    }

    function enterRoom(roomCode) {
        window.location.href = `/kim-bu/${roomCode}/`;
    }

    function createGame() {
        createBtn.textContent = 'Oluşturuluyor...';
        createBtn.disabled = true;

        fetch('/kim-bu/api/create/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        })
        .then((response) => response.json())
        .then((data) => {
            if (!data.success) {
                throw new Error(data.error || 'Bilinmeyen hata');
            }
            const roomCode = data.room_code;

            return fetch('/kim-bu/api/join/', {
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

        joinBtn.textContent = 'Katılınıyor...';
        joinBtn.disabled = true;

        fetch('/kim-bu/api/join/', {
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
