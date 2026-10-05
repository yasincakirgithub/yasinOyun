// Home page JavaScript

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
        sessionStorage.setItem(`sayi:player:${roomCode}`, identifier);
    }

    function enterRoom(roomCode) {
        window.location.href = `/sayi/${roomCode}/`;
    }

    function createGame() {
        createBtn.textContent = 'Oluşturuluyor...';
        createBtn.disabled = true;

        fetch('/sayi/api/create/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        })
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                throw new Error(data.error || 'Bilinmeyen hata');
            }
            const roomCode = data.room_code;

            // The creator also needs to become a player in the room.
            return fetch('/sayi/api/join/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_code: roomCode }),
            })
            .then(response => response.json())
            .then(joinData => {
                if (!joinData.success) {
                    throw new Error(joinData.error || 'Kendi odanda yer alınamadı');
                }
                storePlayer(roomCode, joinData.player_identifier);
                enterRoom(roomCode);
            });
        })
        .catch(error => {
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

        fetch('/sayi/api/join/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room_code: roomCode }),
        })
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                throw new Error(data.error || 'Bilinmeyen hata');
            }
            storePlayer(roomCode, data.player_identifier);
            enterRoom(roomCode);
        })
        .catch(error => {
            console.error('Hata:', error);
            alert('Oyuna katılınamadı: ' + error.message);
            joinBtn.textContent = 'KATIL';
            joinBtn.disabled = false;
        });
    }
});
