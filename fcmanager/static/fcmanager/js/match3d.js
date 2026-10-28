/*
 * FC Manager — pseudo-3D match pitch.
 *
 * A small canvas renderer in the spirit of Haxball: photo discs for players,
 * a rolling ball, crisp white markings and a perspective pitch. The server
 * owns the timeline; this module only reacts to the events the replay engine
 * emits.
 *
 * Ball logic: an event never teleports the ball. It always travels to the
 * involved player first (so the viewer sees the ball reach him) and only then
 * shoots towards the goal / keeper / touchline.
 */
(function () {
    'use strict';

    var TAU = Math.PI * 2;

    var SLOT_LAYOUT = {
        gk: [50, 88],
        lb: [13, 69], cb1: [36, 73], cb2: [64, 73], rb: [87, 69],
        cm1: [24, 48], cm2: [50, 53], cm3: [76, 48],
        lw: [17, 22], st: [50, 14], rw: [83, 22]
    };

    var TEAM_COLORS = {
        home: { fill: '#22c55e', dark: '#15803d', glow: 'rgba(34, 197, 94, 0.5)', label: '#bbf7d0' },
        away: { fill: '#38bdf8', dark: '#0369a1', glow: 'rgba(56, 189, 248, 0.5)', label: '#bae6fd' }
    };

    var canvas = null;
    var ctx = null;
    var observer = null;
    var running = false;
    var raf = null;
    var lastTime = 0;
    var time = 0;
    var width = 0;
    var height = 0;
    var dpr = 1;

    var players = [];
    var photos = {};
    var ball = {
        x: 0.5, y: 0.5,
        tx: 0.5, ty: 0.5,
        queue: [],      // pending waypoints: {x, y, follow, speed, hold}
        hold: 0,        // small pause between waypoints
        owner: null,    // player the ball is glued to while nobody is passing
        bob: 0
    };
    var ballSpin = 0;
    var idleTimer = 2.5;
    var lastPass = null;
    var celebration = 0;
    var celebrationSide = null;
    var flash = 0;
    var flashColor = 'rgba(255, 255, 255, 0.5)';
    var message = '';
    var messageTimer = 0;
    var timers = [];

    function clamp(value, low, high) {
        return Math.max(low, Math.min(high, value));
    }

    function initials(name) {
        var parts = String(name || '?').trim().split(/\s+/).slice(0, 2);
        return parts.map(function (part) { return part.charAt(0); }).join('').toUpperCase() || '?';
    }

    function shortName(name) {
        var label = String(name || '').trim();
        if (label.length > 16) label = label.slice(0, 15) + '…';
        return label || '?';
    }

    function roundRect(x, y, w, h, r) {
        var radius = Math.min(r, w / 2, h / 2);
        if (ctx.roundRect) {
            ctx.beginPath();
            ctx.roundRect(x, y, w, h, radius);
            return;
        }
        ctx.beginPath();
        ctx.moveTo(x + radius, y);
        ctx.lineTo(x + w - radius, y);
        ctx.quadraticCurveTo(x + w, y, x + w, y + radius);
        ctx.lineTo(x + w, y + h - radius);
        ctx.quadraticCurveTo(x + w, y + h, x + w - radius, y + h);
        ctx.lineTo(x + radius, y + h);
        ctx.quadraticCurveTo(x, y + h, x, y + h - radius);
        ctx.lineTo(x, y + radius);
        ctx.quadraticCurveTo(x, y, x + radius, y);
        ctx.closePath();
    }

    /* Player photos come from the FC26 CDN link in the dataset. */
    function photoFor(url) {
        if (!url) return null;
        var entry = photos[url];
        if (!entry) {
            entry = { image: new window.Image(), ready: false, failed: false };
            entry.image.decoding = 'async';
            entry.image.referrerPolicy = 'no-referrer';
            entry.image.addEventListener('load', function () { entry.ready = true; });
            entry.image.addEventListener('error', function () { entry.failed = true; });
            entry.image.src = url;
            photos[url] = entry;
        }
        if (entry.ready) return entry;
        if (!entry.failed && entry.image.complete && entry.image.naturalWidth > 0) {
            entry.ready = true;
            return entry;
        }
        return entry.failed ? null : entry;
    }

    function drawCover(image, cx, cy, radius) {
        var size = radius * 2;
        var naturalWidth = image.naturalWidth;
        var naturalHeight = image.naturalHeight;
        if (!naturalWidth || !naturalHeight) return;
        var sourceSize = Math.min(naturalWidth, naturalHeight);
        var sx = (naturalWidth - sourceSize) / 2;
        var sy = (naturalHeight - sourceSize) / 2;
        ctx.drawImage(image, sx, sy, sourceSize, sourceSize, cx - radius, cy - radius, size, size);
    }

    function resize() {
        if (!canvas || !ctx) return;
        var rect = canvas.getBoundingClientRect();
        var nextWidth = Math.max(280, Math.round(rect.width || canvas.clientWidth || 640));
        var nextHeight = Math.max(180, Math.round(nextWidth * 0.52));
        dpr = Math.min(2, window.devicePixelRatio || 1);
        width = nextWidth;
        height = nextHeight;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    /*
     * Perspective projection. ``y`` 0 is the far goal line, 1 is the near one,
     * so players lower on the screen are larger — the classic 3D pitch look.
     */
    function project(x, y) {
        var depth = clamp(y, 0, 1);
        var scale = 0.6 + depth * 0.4;
        var halfWidth = width * 0.47 * scale;
        return {
            x: width / 2 + (x - 0.5) * 2 * halfWidth,
            y: height * (0.13 + depth * 0.82),
            s: scale
        };
    }

    function polygon(points, fill, stroke, lineWidth) {
        if (!points.length) return;
        ctx.beginPath();
        points.forEach(function (point, index) {
            if (index === 0) ctx.moveTo(point.x, point.y);
            else ctx.lineTo(point.x, point.y);
        });
        ctx.closePath();
        if (fill) {
            ctx.fillStyle = fill;
            ctx.fill();
        }
        if (stroke) {
            ctx.strokeStyle = stroke;
            ctx.lineWidth = lineWidth || 1;
            ctx.stroke();
        }
    }

    function line(a, b, color, lineWidth) {
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth || 1;
        ctx.stroke();
    }

    function drawPitch() {
        var sky = ctx.createLinearGradient(0, 0, 0, height);
        sky.addColorStop(0, '#07120d');
        sky.addColorStop(0.45, '#0a1a13');
        sky.addColorStop(1, '#0d2418');
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, width, height);

        // Grass stripes in perspective.
        var bands = 12;
        for (var i = 0; i < bands; i += 1) {
            var y0 = i / bands;
            var y1 = (i + 1) / bands;
            var fill = i % 2 === 0 ? '#14532d' : '#166534';
            polygon(
                [project(0, y0), project(1, y0), project(1, y1), project(0, y1)],
                fill
            );
        }

        // Soft light from above.
        var light = ctx.createRadialGradient(width / 2, height * 0.35, 10, width / 2, height * 0.5, width * 0.7);
        light.addColorStop(0, 'rgba(255, 255, 255, 0.12)');
        light.addColorStop(1, 'rgba(255, 255, 255, 0)');
        polygon([project(0, 0), project(1, 0), project(1, 1), project(0, 1)], light);

        var chalk = 'rgba(255, 255, 255, 0.72)';
        var chalkSoft = 'rgba(255, 255, 255, 0.42)';
        polygon([project(0, 0), project(1, 0), project(1, 1), project(0, 1)], null, chalk, 2);

        // Halfway line and centre circle.
        line(project(0, 0.5), project(1, 0.5), chalk, 1.6);
        ctx.beginPath();
        for (var step = 0; step <= 48; step += 1) {
            var angle = (step / 48) * TAU;
            var point = project(0.5 + Math.cos(angle) * 0.085, 0.5 + Math.sin(angle) * 0.085);
            if (step === 0) ctx.moveTo(point.x, point.y);
            else ctx.lineTo(point.x, point.y);
        }
        ctx.closePath();
        ctx.strokeStyle = chalkSoft;
        ctx.lineWidth = 1.4;
        ctx.stroke();

        // Penalty and six-yard boxes at both ends.
        [0, 1].forEach(function (end) {
            var near = end === 1;
            var boxNear = near ? 1 : 0.16;
            var boxFar = near ? 0.84 : 0;
            polygon([
                project(0.22, boxFar), project(0.78, boxFar),
                project(0.78, boxNear), project(0.22, boxNear)
            ], null, chalkSoft, 1.3);
            var smallNear = near ? 1 : 0.06;
            var smallFar = near ? 0.94 : 0;
            polygon([
                project(0.36, smallFar), project(0.64, smallFar),
                project(0.64, smallNear), project(0.36, smallNear)
            ], null, 'rgba(255, 255, 255, 0.3)', 1);
            // Penalty spot.
            var spot = project(0.5, near ? 0.82 : 0.18);
            ctx.beginPath();
            ctx.arc(spot.x, spot.y, 1.8 * spot.s, 0, TAU);
            ctx.fillStyle = chalkSoft;
            ctx.fill();
        });

        // Goals with a little height so they read as 3D.
        [0, 1].forEach(function (end) {
            var y = end === 1 ? 1 : 0;
            var left = project(0.435, y);
            var right = project(0.565, y);
            var postHeight = 18 * left.s;
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.82)';
            ctx.lineWidth = 2 * left.s;
            line2(left, postHeight);
            line2(right, postHeight);
            line(
                { x: left.x, y: left.y - postHeight },
                { x: right.x, y: right.y - postHeight },
                'rgba(255, 255, 255, 0.6)', 1.4 * left.s
            );
            // Net hint.
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.16)';
            ctx.lineWidth = 1;
            for (var net = 1; net < 6; net += 1) {
                var nx = left.x + ((right.x - left.x) * net) / 6;
                ctx.beginPath();
                ctx.moveTo(nx, left.y);
                ctx.lineTo(nx, left.y - postHeight);
                ctx.stroke();
            }
        });
    }

    function line2(point, postHeight) {
        ctx.beginPath();
        ctx.moveTo(point.x, point.y);
        ctx.lineTo(point.x, point.y - postHeight);
        ctx.stroke();
    }

    function drawShadow(x, y, radius) {
        ctx.beginPath();
        ctx.ellipse(x, y + radius * 0.16, radius * 1.16, radius * 0.44, 0, 0, TAU);
        ctx.fillStyle = 'rgba(0, 0, 0, 0.32)';
        ctx.fill();
    }

    function drawBall() {
        var projected = project(ball.x, ball.y);
        var radius = 5.4 * projected.s + Math.sin(ball.bob) * 0.9;
        var lift = 2.6 * projected.s + Math.sin(time * 5 + ball.bob) * 1.2;
        drawShadow(projected.x, projected.y, radius * 1.1);
        ctx.beginPath();
        ctx.arc(projected.x, projected.y - lift, radius, 0, TAU);
        ctx.fillStyle = '#f8fafc';
        ctx.fill();
        ctx.strokeStyle = 'rgba(15, 23, 42, 0.55)';
        ctx.lineWidth = 1;
        ctx.stroke();
        // Two pentagon-ish patches to sell the rotation.
        ctx.fillStyle = '#0f172a';
        for (var patch = 0; patch < 2; patch += 1) {
            var angle = ballSpin + patch * Math.PI;
            ctx.beginPath();
            ctx.arc(
                projected.x + Math.cos(angle) * radius * 0.38,
                projected.y - lift + Math.sin(angle) * radius * 0.3,
                radius * 0.21, 0, TAU
            );
            ctx.fill();
        }
    }

    function drawName(player, projected, radius) {
        var colors = TEAM_COLORS[player.team] || TEAM_COLORS.home;
        var font = clamp(radius * 0.72, 6.5, 11);
        var label = shortName(player.name);
        ctx.font = '700 ' + font.toFixed(1) + 'px system-ui, -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        var textWidth = ctx.measureText(label).width;
        var padX = 4;
        var boxWidth = textWidth + padX * 2 + 3;
        var boxHeight = font + 4.5;
        var top = projected.y + radius * 0.55;

        ctx.fillStyle = 'rgba(2, 6, 23, 0.66)';
        roundRect(projected.x - boxWidth / 2, top, boxWidth, boxHeight, 3);
        ctx.fill();
        ctx.fillStyle = colors.fill;
        roundRect(projected.x - boxWidth / 2, top, 2.2, boxHeight, 1.1);
        ctx.fill();
        ctx.fillStyle = colors.label;
        ctx.fillText(label, projected.x + 1, top + boxHeight / 2 + 0.4);
    }

    function drawPlayer(player) {
        var projected = project(player.x, player.y);
        var colors = TEAM_COLORS[player.team] || TEAM_COLORS.home;
        var bounce = celebration > 0 && celebrationSide === player.team
            ? Math.abs(Math.sin(time * 9 + player.phase)) * 5 * projected.s
            : 0;
        var radius = 8.6 * projected.s;
        var centerY = projected.y - radius * 0.95 - bounce;

        drawShadow(projected.x, projected.y, radius);

        if (celebration > 0 && celebrationSide === player.team) {
            ctx.beginPath();
            ctx.arc(projected.x, centerY, radius * 1.5, 0, TAU);
            ctx.fillStyle = colors.glow;
            ctx.fill();
        }

        var photo = photoFor(player.image);
        var hasPhoto = !!(photo && photo.ready);

        ctx.beginPath();
        ctx.arc(projected.x, centerY, radius, 0, TAU);
        ctx.fillStyle = hasPhoto ? colors.dark : colors.fill;
        ctx.fill();

        if (hasPhoto) {
            ctx.save();
            ctx.beginPath();
            ctx.arc(projected.x, centerY, radius, 0, TAU);
            ctx.clip();
            drawCover(photo.image, projected.x, centerY, radius);
            ctx.restore();
        } else {
            ctx.fillStyle = '#04121a';
            ctx.font = '700 ' + Math.max(7, Math.round(radius * 0.92)) + 'px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(initials(player.name), projected.x, centerY + 0.4);
        }

        // Team ring keeps both sides readable even with photos.
        ctx.beginPath();
        ctx.arc(projected.x, centerY, radius, 0, TAU);
        ctx.lineWidth = Math.max(1.4, 1.8 * projected.s);
        ctx.strokeStyle = '#f8fafc';
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(projected.x, centerY, radius * 0.86, 0, TAU);
        ctx.lineWidth = Math.max(1.2, 1.6 * projected.s);
        ctx.strokeStyle = colors.fill;
        ctx.stroke();

        drawName(player, projected, radius);
    }

    function drawOverlays() {
        if (!message || messageTimer <= 0) return;
        var alpha = clamp(messageTimer, 0, 1);
        var big = message === 'GOL!' || message === 'KAÇTI!';
        var size = Math.round(Math.min(big ? 58 : 38, width * (big ? 0.07 : 0.048)));
        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.font = '900 ' + size + 'px system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        var textWidth = ctx.measureText(message).width;
        var padX = size * 0.55;
        var padY = size * 0.3;
        var boxW = textWidth + padX * 2;
        var boxH = size + padY * 2;
        var cx = width / 2;
        var cy = height * 0.17;
        ctx.fillStyle = big ? 'rgba(22, 163, 74, 0.92)' : 'rgba(2, 6, 23, 0.74)';
        roundRect(cx - boxW / 2, cy - boxH / 2, boxW, boxH, boxH / 2);
        ctx.fill();
        ctx.strokeStyle = big ? 'rgba(187, 247, 208, 0.95)' : 'rgba(255, 255, 255, 0.28)';
        ctx.lineWidth = 2;
        ctx.stroke();
        ctx.fillStyle = '#f8fafc';
        ctx.fillText(message, cx, cy + 1);
        ctx.restore();
    }

    function draw() {
        if (!ctx) return;
        drawPitch();

        // Far players first so near discs overlap correctly.
        var ordered = players.slice().sort(function (a, b) { return a.y - b.y; });
        var ballDrawn = false;
        ordered.forEach(function (player) {
            if (!ballDrawn && player.y > ball.y) {
                drawBall();
                ballDrawn = true;
            }
            drawPlayer(player);
        });
        if (!ballDrawn) drawBall();

        if (flash > 0) {
            ctx.fillStyle = flashColor;
            ctx.globalAlpha = clamp(flash, 0, 0.55);
            ctx.fillRect(0, 0, width, height);
            ctx.globalAlpha = 1;
        }
        drawOverlays();
    }

    function currentTarget() {
        return ball.queue.length ? ball.queue[0] : null;
    }

    function update(dt) {
        time += dt;
        runTimers();
        ballSpin += dt * 2.4;
        ball.bob += dt * 5;

        if (flash > 0) flash = Math.max(0, flash - dt * 1.7);
        if (messageTimer > 0) messageTimer = Math.max(0, messageTimer - dt);
        if (celebration > 0) celebration = Math.max(0, celebration - dt);
        if (ball.hold > 0) ball.hold = Math.max(0, ball.hold - dt);

        players.forEach(function (player) {
            var dx = ball.x - player.baseX;
            var dy = ball.y - player.baseY;
            var distance = Math.sqrt(dx * dx + dy * dy);
            var pull = Math.max(0, 1 - distance / 0.3) * 0.09;
            var wobble = celebration > 0 && celebrationSide === player.team ? 0.02 : 0.012;
            player.x = clamp(
                player.baseX + Math.sin(time * player.speed + player.phase) * wobble + dx * pull,
                0.035, 0.965
            );
            player.y = clamp(
                player.baseY + Math.cos(time * player.speed * 0.78 + player.phase) * wobble * 0.7 + dy * pull,
                0.035, 0.965
            );
        });

        var target = currentTarget();
        if (target) {
            // The ball rides along with the player it was aimed at, so it
            // always lands on him instead of at a stale spot.
            if (target.follow) {
                target.x = clamp(target.follow.x, 0.03, 0.97);
                target.y = clamp(target.follow.y, 0.03, 0.97);
            }
        } else {
            // Nobody is passing: stay glued to the last player who had it so
            // the ball never drifts away into empty grass.
            if (ball.owner) {
                var glue = Math.min(1, dt * 8);
                ball.x += (ball.owner.x - ball.x) * glue;
                ball.y += (ball.owner.y - ball.y) * glue;
            }
            idleTimer -= dt;
            if (idleTimer <= 0 && celebration <= 0) {
                idleTimer = 1.5 + Math.random() * 1.4;
                idlePass();
                target = currentTarget();
            }
        }

        var ease = Math.min(1, dt * (target ? (target.speed || 3.4) : 2.4));
        ball.x += (ball.tx - ball.x) * ease;
        ball.y += (ball.ty - ball.y) * ease;

        if (target) {
            ball.tx = clamp(target.x, 0.03, 0.97);
            ball.ty = clamp(target.y, 0.03, 0.97);
            if (ball.hold <= 0) {
                var gap = Math.hypot(ball.tx - ball.x, ball.ty - ball.y);
                if (gap < 0.01) {
                    ball.x = ball.tx;
                    ball.y = ball.ty;
                    var reached = ball.queue.shift();
                    if (reached && reached.follow) ball.owner = reached.follow;
                    ball.hold = ball.queue.length ? (ball.queue[0].hold || 0.14) : 0.2;
                }
            }
        }
    }

    function frame(now) {
        if (!running) return;
        var dt = lastTime ? Math.min(0.05, (now - lastTime) / 1000) : 0.016;
        lastTime = now;
        update(dt);
        draw();
        raf = window.requestAnimationFrame(frame);
    }

    function addPlayer(team, x, y, player) {
        players.push({
            team: team,
            baseX: x,
            baseY: y,
            x: x,
            y: y,
            name: (player && player.name) || '',
            image: (player && player.image_url) || '',
            phase: Math.random() * TAU,
            speed: 1.1 + Math.random() * 0.9
        });
    }

    function setMatch(match) {
        players = [];
        celebration = 0;
        celebrationSide = null;
        message = '';
        messageTimer = 0;
        timers = [];
        lastPass = null;
        ball = {
            x: 0.5, y: 0.5, queue: [], hold: 0, owner: null,
            bob: 0, tx: 0.5, ty: 0.5
        };
        idleTimer = 2.2;
        if (!match) return;

        ['home', 'away'].forEach(function (side) {
            var snapshot = match[side] || {};
            var squad = snapshot.squad || {};
            Object.keys(squad).forEach(function (slot) {
                var layout = SLOT_LAYOUT[slot];
                if (!layout) return;
                var x = layout[0] / 100;
                var y = layout[1] / 100;
                if (side === 'away') {
                    x = 1 - x;
                    y = 1 - y;
                }
                addPlayer(side, x, y, squad[slot]);
            });
        });
    }

    function attackGoal(side) {
        return side === 'home' ? 0.02 : 0.98;
    }

    /* Tiny in-loop scheduler so a play can chain "goal -> santra" beats. */
    function schedule(delay, fn) {
        timers.push({ at: time + delay, fn: fn });
    }

    function runTimers() {
        if (!timers.length) return;
        var due = [];
        timers = timers.filter(function (entry) {
            if (entry.at <= time) {
                due.push(entry);
                return false;
            }
            return true;
        });
        due.forEach(function (entry) { entry.fn(); });
    }

    function findPlayer(team, name) {
        var exact = null;
        var nearest = null;
        var nearestGap = Infinity;
        players.forEach(function (player) {
            if (player.team !== team) return;
            if (name && player.name === name) exact = player;
            var gap = Math.hypot(player.x - ball.x, player.y - ball.y);
            if (gap < nearestGap) {
                nearestGap = gap;
                nearest = player;
            }
        });
        return exact || nearest;
    }

    function pushBall(waypoints) {
        ball.queue = (waypoints || []).filter(Boolean).map(function (point) {
            return {
                x: clamp(point.x, 0.03, 0.97),
                y: clamp(point.y, 0.03, 0.97),
                follow: point.follow || null,
                speed: point.speed || 3.4,
                hold: point.hold === undefined ? 0.14 : point.hold
            };
        });
        ball.hold = 0;
    }

    /* Waypoint 1: carry the ball onto the player involved in the event. */
    function toPlayer(side, name) {
        var player = findPlayer(side, name);
        if (!player) return null;
        return {
            x: player.x,
            y: player.y,
            follow: player,
            speed: 3.2,
            hold: 0.22
        };
    }

    function closestPlayer(x, y, exclude) {
        var best = null;
        var bestGap = Infinity;
        players.forEach(function (player) {
            if (exclude && player === exclude) return;
            var gap = Math.hypot(player.x - x, player.y - y);
            if (gap < bestGap) {
                bestGap = gap;
                best = player;
            }
        });
        return best;
    }

    /*
     * Every waypoint ends on a player, so the ball is never left sitting in
     * empty grass. ``follow`` keeps the target glued to a moving player.
     */
    function ontoPlayer(player, speed, hold) {
        if (!player) return null;
        return {
            x: player.x,
            y: player.y,
            follow: player,
            speed: speed || 3.4,
            hold: hold === undefined ? 0.18 : hold
        };
    }

    function ontoNearest(x, y, exclude, speed) {
        return ontoPlayer(closestPlayer(x, y, exclude), speed, 0.18);
    }

    function randomPlayer(exclude) {
        if (!players.length) return null;
        var pick = players[Math.floor(Math.random() * players.length)];
        var guard = 0;
        while ((pick === exclude || pick === lastPass) && guard < 8) {
            pick = players[Math.floor(Math.random() * players.length)];
            guard += 1;
        }
        return pick;
    }

    /* Idle possession: short passes between team-mates, never to open space. */
    function idlePass() {
        var target = randomPlayer(lastPass);
        if (!target) return;
        lastPass = target;
        pushBall([ontoPlayer(target, 2.4, 0.1)]);
    }

    function onEvent(event) {
        if (!event) return;
        // A new event supersedes any queued follow-up beat (e.g. a pending
        // "SANTRA" message from the previous goal).
        timers = [];
        if (event.type === 'kickoff') {
            // Santra: the ball returns to the centre spot and a player takes it.
            celebration = 0;
            celebrationSide = null;
            message = 'SANTRA';
            messageTimer = 1.6;
            idleTimer = 2;
            pushBall([
                { x: 0.5, y: 0.5, speed: 3.0, hold: 0.3 },
                ontoNearest(0.5, 0.5, null, 2.6),
            ]);
            return;
        }
        if (event.type === 'half' || event.type === 'full') {
            pushBall([
                { x: 0.5, y: 0.5, speed: 2.8, hold: 0.2 },
                ontoNearest(0.5, 0.5, null, 2.6),
            ]);
            message = event.type === 'full' ? 'MAÇ SONU' : 'İLK YARI';
            messageTimer = 2.4;
            return;
        }
        if (event.phase === 'penalties') {
            var penSide = event.side === 'away' ? 'away' : 'home';
            var penTowardFar = penSide === 'home';
            var spotY = penTowardFar ? 0.24 : 0.76;
            var scored = event.type === 'penalty_scored';
            var keeper = closestPlayer(0.5, penTowardFar ? 0.05 : 0.95, null);
            pushBall([
                toPlayer(penSide, event.player),
                { x: 0.5, y: spotY, speed: 3.6, hold: 0.35 },
                scored
                    ? { x: 0.5, y: penTowardFar ? 0.03 : 0.97, speed: 7.0, hold: 0.4 }
                    : {
                        x: penTowardFar ? 0.3 : 0.7,
                        y: penTowardFar ? 0.05 : 0.95,
                        speed: 6.4,
                        hold: 0.35
                    },
                scored ? ontoNearest(0.5, 0.5, null, 3.0) : ontoPlayer(keeper, 3.0),
            ]);
            message = scored ? 'GOL!' : 'KAÇTI!';
            messageTimer = 1.2;
            return;
        }

        var side = event.side === 'away' ? 'away' : 'home';
        var goalY = attackGoal(side);
        // Home attacks the far goal (top of the screen), away the near one.
        var towardFar = side === 'home';

        if (event.type === 'goal') {
            /*
             * Full goal beat: shoot, celebrate, walk the ball back to the
             * centre spot and let a player restart. Nothing is left in the net.
             */
            pushBall([
                toPlayer(side, event.player),
                { x: 0.5, y: goalY, speed: 7.4, hold: 0.45 },
                { x: 0.5, y: 0.5, speed: 3.6, hold: 0.35 },
                ontoNearest(0.5, 0.5, null, 2.8),
            ]);
            celebration = 2.0;
            celebrationSide = side;
            flash = 0.5;
            flashColor = side === 'home' ? 'rgba(134, 239, 172, 0.5)' : 'rgba(125, 211, 252, 0.5)';
            message = 'GOL!';
            messageTimer = 2.0;
            idleTimer = 2.4;
            schedule(2.0, function () {
                if (celebrationSide !== side) return;  // a newer event took over
                message = 'SANTRA';
                messageTimer = 1.5;
            });
            return;
        }

        if (event.type === 'save') {
            var savedY = towardFar ? 0.11 : 0.89;
            pushBall([
                toPlayer(side, event.player),
                { x: 0.5, y: savedY, speed: 6.6, hold: 0.15 },
                ontoNearest(0.5, savedY, null, 2.8),   // keeper collects the ball
            ]);
            idleTimer = 1.4;
            return;
        }

        if (event.type === 'miss') {
            var wideX = Math.random() < 0.5 ? 0.3 : 0.7;
            var outY = towardFar ? 0.06 : 0.94;
            pushBall([
                toPlayer(side, event.player),
                { x: wideX, y: outY, speed: 6.6, hold: 0.15 },
                ontoNearest(0.5, towardFar ? 0.12 : 0.88, null, 2.8),  // goal kick
            ]);
            idleTimer = 1.4;
            return;
        }

        if (event.type === 'chance') {
            var chanceX = 0.34 + Math.random() * 0.32;
            var chanceY = towardFar ? 0.2 : 0.8;
            pushBall([
                toPlayer(side, event.player),
                { x: chanceX, y: chanceY, speed: 5.6, hold: 0.15 },
                ontoNearest(chanceX, chanceY, null, 3.2),  // a team-mate picks it up
            ]);
            idleTimer = 1.4;
            return;
        }

        if (event.type === 'corner') {
            var taker = findPlayer(side, event.player);
            var flagX = taker && taker.x < 0.5 ? 0.06 : 0.94;
            pushBall([
                ontoPlayer(taker, 4.2, 0.15),
                { x: flagX, y: goalY, speed: 4.4, hold: 0.3 },
                ontoNearest(0.5, towardFar ? 0.24 : 0.76, null, 3.0),  // header in the box
            ]);
            idleTimer = 1.4;
            return;
        }

        if (event.type === 'card' || event.type === 'offside') {
            pushBall([toPlayer(side, event.player)]);
            idleTimer = 1.6;
            return;
        }

        pushBall([
            toPlayer(side, event.player),
            ontoNearest(ball.x, ball.y, findPlayer(side, event.player), 3.2),
        ]);
    }

    function start() {
        if (!canvas || !ctx) return;
        if (running) return;
        resize();
        running = true;
        lastTime = 0;
        raf = window.requestAnimationFrame(frame);
    }

    function pause() {
        running = false;
        if (raf) window.cancelAnimationFrame(raf);
        raf = null;
    }

    function mount(canvasElement) {
        canvas = canvasElement;
        if (!canvas) return;
        ctx = canvas.getContext('2d');
        if (window.ResizeObserver) {
            observer = new ResizeObserver(function () { resize(); draw(); });
            observer.observe(canvas);
        } else {
            window.addEventListener('resize', resize);
        }
        resize();
        draw();
    }

    window.FCMatch3D = {
        mount: mount,
        setMatch: setMatch,
        onEvent: onEvent,
        start: start,
        pause: pause,
        redraw: function () { resize(); draw(); },
        // Read-only view of the animation state (used by the photo/ball tests).
        debugState: function () {
            return {
                ball: { x: ball.x, y: ball.y, queue: ball.queue.length, owner: !!ball.owner },
                message: message,
                messageTimer: messageTimer,
                players: players.map(function (player) {
                    return { x: player.x, y: player.y, team: player.team };
                })
            };
        }
    };
})();
