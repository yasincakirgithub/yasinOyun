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
        sessionStorage.setItem(`recru:player:${roomCode}`, identifier);
    }

    function enterRoom(roomCode) {
        window.location.href = `/game/${roomCode}/`;
    }

    function createGame() {
        createBtn.textContent = 'Creating...';
        createBtn.disabled = true;

        fetch('/game/api/create/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        })
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                throw new Error(data.error || 'Unknown error');
            }
            const roomCode = data.room_code;

            // The creator also needs to become a player in the room.
            return fetch('/game/api/join/', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ room_code: roomCode }),
            })
            .then(response => response.json())
            .then(joinData => {
                if (!joinData.success) {
                    throw new Error(joinData.error || 'Could not take a seat in your own room');
                }
                storePlayer(roomCode, joinData.player_identifier);
                enterRoom(roomCode);
            });
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error creating room: ' + error.message);
            createBtn.textContent = 'CREATE GAME';
            createBtn.disabled = false;
        });
    }

    function joinGame() {
        const roomCode = roomCodeInput.value.trim().toUpperCase();
        if (!roomCode) {
            alert('Please enter a room code');
            return;
        }

        joinBtn.textContent = 'Joining...';
        joinBtn.disabled = true;

        fetch('/game/api/join/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ room_code: roomCode }),
        })
        .then(response => response.json())
        .then(data => {
            if (!data.success) {
                throw new Error(data.error || 'Unknown error');
            }
            storePlayer(roomCode, data.player_identifier);
            enterRoom(roomCode);
        })
        .catch(error => {
            console.error('Error:', error);
            alert('Error joining room: ' + error.message);
            joinBtn.textContent = 'JOIN GAME';
            joinBtn.disabled = false;
        });
    }
});
