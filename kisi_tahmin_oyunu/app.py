from flask import Flask, render_template, session
from flask_socketio import SocketIO, emit, join_room, leave_room
import random

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins="*")

# In-memory game state
games = {}

def generate_secret():
    digits = random.sample('0123456789', 4)
    return ''.join(digits)

def evaluate_guess(secret, guess):
    plus = sum(1 for i in range(4) if secret[i] == guess[i])
    minus = sum(1 for g in guess if g in secret) - plus
    return '+' * plus + '-' * minus

@app.route('/')
def index():
    return render_template('index.html')

@socketio.on('join')
def handle_join(data):
    room = data['room']
    join_room(room)
    if room not in games:
        games[room] = {
            'players': [],
            'secrets': {},
            'guesses': {},
            'turn': None,
            'started': False
        }
    game = games[room]
    if len(game['players']) < 2:
        game['players'].append(request.sid)
        if len(game['players']) == 2:
            # assign secrets
            for sid in game['players']:
                game['secrets'][sid] = generate_secret()
            game['turn'] = game['players'][0]
            game['started'] = True
            # notify both
            emit('game_start', {'your_sid': request.sid, 'opponent': game['players'][1] if request.sid == game['players'][0] else game['players'][0]}, room=room)
            emit('your_turn', {'turn': game['turn']}, room=room)
        else:
            emit('waiting', {'msg': 'Waiting for opponent...'})
    else:
        emit('error', {'msg': 'Room full'})

@socketio.on('guess')
def handle_guess(data):
    room = data['room']
    guess = data['guess']
    sid = request.sid
    game = games.get(room)
    if not game or not game['started']:
        emit('error', {'msg': 'Game not ready'})
        return
    if game['turn'] != sid:
        emit('error', {'msg': 'Not your turn'})
        return
    opponent = [p for p in game['players'] if p != sid][0]
    secret = game['secrets'][opponent]
    result = evaluate_guess(secret, guess)
    # store guess
    game['guesses'].setdefault(sid, []).append((guess, result))
    # switch turn
    game['turn'] = opponent
    # inform both
    emit('guess_result', {'guesser': sid, 'guess': guess, 'result': result}, room=room)
    emit('your_turn', {'turn': game['turn']}, room=room)
    # check win
    if result == '++++':
        emit('game_over', {'winner': sid, 'loser': opponent}, room=room)
        game['started'] = False

if __name__ == '__main__':
    socketio.run(app, debug=True)