(function () {
    'use strict';

    var nameInput = document.getElementById('player-name');
    var roomInput = document.getElementById('room-code-input');
    var createBtn = document.getElementById('create-btn');
    var joinBtn = document.getElementById('join-btn');
    var errorBox = document.getElementById('home-error');

    var NAME_KEY = 'codenames:name';
    var TOKEN_PREFIX = 'codenames:session:';
    var SEAT_NAME_PREFIX = 'codenames:seatname:';

    nameInput.value = localStorage.getItem(NAME_KEY) || '';
    roomInput.value = (roomInput.value || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);

    function showError(message) {
        errorBox.textContent = message;
        errorBox.hidden = !message;
    }

    function name() {
        var value = nameInput.value.trim().slice(0, 30);
        if (!value) {
            showError('Odaya katılmak için bir görünen ad gir.');
            nameInput.focus();
            return '';
        }
        localStorage.setItem(NAME_KEY, value);
        return value;
    }

    function setBusy(button, busy, text) {
        button.disabled = busy;
        if (!button.dataset.label) button.dataset.label = button.textContent;
        button.textContent = busy ? text : button.dataset.label;
    }

    function storedSeat(roomCode) {
        return {
            token: sessionStorage.getItem(TOKEN_PREFIX + roomCode) ||
                localStorage.getItem(TOKEN_PREFIX + roomCode) || '',
            name: sessionStorage.getItem(SEAT_NAME_PREFIX + roomCode) ||
                localStorage.getItem(SEAT_NAME_PREFIX + roomCode) || '',
        };
    }

    function remember(roomCode, token, displayName) {
        if (token) {
            sessionStorage.setItem(TOKEN_PREFIX + roomCode, token);
            localStorage.setItem(TOKEN_PREFIX + roomCode, token);
        }
        if (displayName) {
            sessionStorage.setItem(SEAT_NAME_PREFIX + roomCode, displayName);
            localStorage.setItem(SEAT_NAME_PREFIX + roomCode, displayName);
        }
    }

    function clearSeat(roomCode) {
        sessionStorage.removeItem(TOKEN_PREFIX + roomCode);
        sessionStorage.removeItem(SEAT_NAME_PREFIX + roomCode);
        localStorage.removeItem(TOKEN_PREFIX + roomCode);
        localStorage.removeItem(SEAT_NAME_PREFIX + roomCode);
    }

    async function post(url, payload) {
        var response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
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

    function goToRoom(roomCode) {
        window.location.href = '/codenames/room/' + encodeURIComponent(roomCode) + '/';
    }

    createBtn.addEventListener('click', async function () {
        showError('');
        var displayName = name();
        if (!displayName) return;
        setBusy(createBtn, true, 'ODA KURULUYOR...');
        try {
            var room = await post('/codenames/api/rooms/', { name: displayName });
            remember(room.room_code, room.session_token, displayName);
            goToRoom(room.room_code);
        } catch (error) {
            showError(error.message);
            setBusy(createBtn, false);
        }
    });

    joinBtn.addEventListener('click', async function () {
        showError('');
        var displayName = name();
        if (!displayName) return;
        var roomCode = roomInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
        if (roomCode.length !== 6) {
            showError('Oda kodu 6 karakter olmalı.');
            roomInput.focus();
            return;
        }

        var seat = storedSeat(roomCode);
        var resumeToken = seat.token && seat.name === displayName ? seat.token : '';
        setBusy(joinBtn, true, 'KATILINIYOR...');

        try {
            var joined;
            try {
                joined = await post('/codenames/api/rooms/join/', {
                    room_code: roomCode,
                    name: displayName,
                    session_token: resumeToken,
                });
            } catch (error) {
                if (!resumeToken || (error.code !== 'invalid_session' && error.status !== 401)) {
                    throw error;
                }
                clearSeat(roomCode);
                joined = await post('/codenames/api/rooms/join/', {
                    room_code: roomCode,
                    name: displayName,
                    session_token: '',
                });
            }
            remember(roomCode, joined.session_token, displayName);
            goToRoom(roomCode);
        } catch (error) {
            showError(error.message);
            setBusy(joinBtn, false);
        }
    });

    roomInput.addEventListener('input', function () {
        roomInput.value = roomInput.value.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 6);
    });

    roomInput.addEventListener('keydown', function (event) {
        if (event.key === 'Enter') joinBtn.click();
    });
})();
