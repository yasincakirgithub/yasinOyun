/*
 * FC Manager — canlı 3D maç sahası.
 *
 * The server owns the 90-minute timeline. This renderer turns every event
 * into a football beat: the ball is passed to the player involved, the player
 * carries it at his feet, and only then is the shot/cross/free-kick played.
 * Between scripted events a small possession engine keeps the ball with a
 * player — it never spins alone in empty grass.
 */
(function () {
    'use strict';

    var TAU = Math.PI * 2;

    var SLOT_LAYOUT = {
        gk: { x: 50, y: 88, role: 'GK' },
        lb: { x: 13, y: 69, role: 'DEF' },
        cb1: { x: 36, y: 73, role: 'DEF' },
        cb2: { x: 64, y: 73, role: 'DEF' },
        rb: { x: 87, y: 69, role: 'DEF' },
        cm1: { x: 24, y: 48, role: 'MID' },
        cm2: { x: 50, y: 53, role: 'MID' },
        cm3: { x: 76, y: 48, role: 'MID' },
        lw: { x: 17, y: 22, role: 'FWD' },
        st: { x: 50, y: 14, role: 'FWD' },
        rw: { x: 83, y: 22, role: 'FWD' }
    };

    var TEAM_COLORS = {
        home: { fill: '#22c55e', dark: '#15803d', light: '#bbf7d0', glow: 'rgba(34, 197, 94, 0.55)' },
        away: { fill: '#38bdf8', dark: '#0369a1', light: '#bae6fd', glow: 'rgba(56, 189, 248, 0.55)' }
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
    var pitchCache = null;

    var players = [];
    var photos = {};
    var ball = {
        x: 0.5, y: 0.5, z: 0,
        mode: 'spot',          // owned | pass | shot | loose | net | spot
        owner: null,
        target: null,
        dest: null,
        speed: 0.8,
        t: 0,
        duration: 0,
        arc: 0,
        onArrive: null,
        trail: []
    };
    var ballSpin = 0;
    var labelBoxes = [];

    var matchInfo = {
        homeName: 'Ev sahibi',
        awayName: 'Deplasman',
        score: [0, 0],
        minute: 0,
        phase: 'match'
    };
    var matchState = 'idle';    // idle | playing | halftime | ended | penalties
    var penaltyMode = false;
    var possession = 'home';
    var kickoffPlayer = null;
    var kickoffLockUntil = 0;
    var endedAt = 0;

    var ai = { nextDecision: 0 };
    var actionSeq = 0;
    var celebration = 0;
    var celebrationSide = null;
    var flash = 0;
    var flashColor = 'rgba(255, 255, 255, 0.5)';
    var shake = 0;
    var message = '';
    var messageSub = '';
    var messageTeam = '';
    var messagePhoto = '';
    var messageKind = 'info';
    var messageTimer = 0;
    var timers = [];
    var confetti = [];

    function clamp(value, low, high) {
        return Math.max(low, Math.min(high, value));
    }

    function initials(name) {
        var parts = String(name || '?').trim().split(/\s+/).slice(0, 2);
        return parts.map(function (part) { return part.charAt(0); }).join('').toUpperCase() || '?';
    }

    function shortName(name) {
        var label = String(name || '').trim();
        if (label.length > 17) label = label.slice(0, 16) + '…';
        return label || '?';
    }

    function shortTeam(name) {
        var label = String(name || '').trim();
        if (label.length > 11) label = label.slice(0, 10) + '…';
        return label || '—';
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

    function seededRandom(seed) {
        var value = seed >>> 0;
        return function () {
            value += 0x6d2b79f5;
            var t = value;
            t = Math.imul(t ^ (t >>> 15), t | 1);
            t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
            return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
        };
    }

    /* ------------------------------------------------------------------ */
    /* Photos                                                              */
    /* ------------------------------------------------------------------ */

    function photoFor(url) {
        if (!url) return null;
        var entry = photos[url];
        if (!entry) {
            entry = { image: new window.Image(), ready: false, failed: false };
            entry.image.decoding = 'async';
            entry.image.referrerPolicy = 'no-referrer';
            entry.image.addEventListener('load', function () {
                entry.ready = true;
                if (!running) draw();
            });
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

    /* ------------------------------------------------------------------ */
    /* Canvas + perspective projection                                     */
    /* ------------------------------------------------------------------ */

    function resize() {
        if (!canvas) return;
        var rect = canvas.getBoundingClientRect();
        var nextWidth = Math.max(320, Math.round(rect.width || canvas.clientWidth || 760));
        var nextHeight = Math.max(190, Math.round(nextWidth * 0.52));
        dpr = Math.min(2, window.devicePixelRatio || 1);
        width = nextWidth;
        height = nextHeight;
        canvas.width = Math.round(width * dpr);
        canvas.height = Math.round(height * dpr);
        if (ctx) ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        pitchCache = null;
        buildPitchCache();
    }

    function project(x, y) {
        var depth = clamp(y, 0, 1);
        var scale = 0.58 + depth * 0.46;
        var halfWidth = width * 0.455 * scale;
        return {
            x: width / 2 + (x - 0.5) * 2 * halfWidth,
            y: height * (0.115 + depth * 0.845),
            s: scale,
            depth: depth
        };
    }

    function projectRaw(x, y) {
        var depth = clamp(y, -0.075, 1.075);
        var scale = 0.58 + depth * 0.46;
        var halfWidth = width * 0.455 * scale;
        return {
            x: width / 2 + (x - 0.5) * 2 * halfWidth,
            y: height * (0.115 + depth * 0.845),
            s: scale,
            depth: depth
        };
    }

    /* ------------------------------------------------------------------ */
    /* Static stadium + pitch                                              */
    /* ------------------------------------------------------------------ */

    function buildPitchCache() {
        if (!ctx || !width || !height) return;
        var cache = document.createElement('canvas');
        cache.width = Math.max(1, Math.round(width * dpr));
        cache.height = Math.max(1, Math.round(height * dpr));
        var cacheCtx = cache.getContext('2d');
        cacheCtx.setTransform(dpr, 0, 0, dpr, 0, 0);
        var liveCtx = ctx;
        ctx = cacheCtx;
        drawStadium();
        drawPitch();
        ctx = liveCtx;
        pitchCache = cache;
    }

    function drawCrowdDots(clipPoints, seed, count) {
        ctx.save();
        ctx.beginPath();
        clipPoints.forEach(function (point, index) {
            if (index === 0) ctx.moveTo(point.x, point.y);
            else ctx.lineTo(point.x, point.y);
        });
        ctx.closePath();
        ctx.clip();
        var random = seededRandom(seed);
        for (var i = 0; i < count; i += 1) {
            var x = random() * width;
            var y = random() * height;
            var size = 1 + random() * 1.9;
            ctx.globalAlpha = 0.22 + random() * 0.5;
            ctx.fillStyle = random() > 0.55 ? '#dbeafe' : (random() > 0.5 ? '#fde68a' : '#a7f3d0');
            ctx.fillRect(x, y, size, size);
        }
        ctx.globalAlpha = 1;
        ctx.restore();
    }

    function drawStadium() {
        var sky = ctx.createLinearGradient(0, 0, 0, height);
        sky.addColorStop(0, '#020706');
        sky.addColorStop(0.46, '#06120c');
        sky.addColorStop(1, '#020806');
        ctx.fillStyle = sky;
        ctx.fillRect(0, 0, width, height);

        var farTop = project(0, 0).y;
        var nearBottom = project(0, 1).y;

        var upper = ctx.createLinearGradient(0, 0, 0, farTop + 5);
        upper.addColorStop(0, '#07110d');
        upper.addColorStop(0.55, '#0a1a13');
        upper.addColorStop(1, '#0c2418');
        ctx.fillStyle = upper;
        ctx.fillRect(0, 0, width, farTop + 6);

        var lower = ctx.createLinearGradient(0, nearBottom - 4, 0, height);
        lower.addColorStop(0, '#0a1b13');
        lower.addColorStop(1, '#030907');
        ctx.fillStyle = lower;
        ctx.fillRect(0, nearBottom - 4, width, height - nearBottom + 4);

        var leftStand = [
            { x: 0, y: 0 },
            project(0, 0),
            project(0, 1),
            { x: 0, y: height }
        ];
        var rightStand = [
            project(1, 0),
            { x: width, y: 0 },
            { x: width, y: height },
            project(1, 1)
        ];
        polygon(leftStand, '#08160f');
        polygon(rightStand, '#08160f');

        drawCrowdDots([
            { x: 0, y: 0 }, { x: width, y: 0 },
            project(1, 0), project(0, 0)
        ], 117, 260);
        drawCrowdDots([
            project(0, 1), project(1, 1),
            { x: width, y: height }, { x: 0, y: height }
        ], 231, 240);
        drawCrowdDots(leftStand, 311, 150);
        drawCrowdDots(rightStand, 419, 150);

        // Floodlight halos.
        [
            [width * 0.08, height * 0.02],
            [width * 0.92, height * 0.02],
            [width * 0.18, height * 0.2],
            [width * 0.82, height * 0.2]
        ].forEach(function (spot) {
            var glow = ctx.createRadialGradient(spot[0], spot[1], 2, spot[0], spot[1], width * 0.24);
            glow.addColorStop(0, 'rgba(226, 255, 239, 0.19)');
            glow.addColorStop(0.4, 'rgba(134, 239, 172, 0.055)');
            glow.addColorStop(1, 'rgba(134, 239, 172, 0)');
            ctx.fillStyle = glow;
            ctx.fillRect(0, 0, width, height);
        });

        // Advertising boards just outside the touchline.
        drawAdBoards(0);
        drawAdBoards(1);
    }

    function drawAdBoards(end) {
        var far = end === 0;
        var boardY = far ? -0.014 : 1.014;
        var innerY = far ? 0.001 : 0.999;
        var segments = 8;
        for (var i = 0; i < segments; i += 1) {
            var x0 = i / segments;
            var x1 = (i + 1) / segments;
            var top = projectRaw(x0, boardY);
            var top2 = projectRaw(x1, boardY);
            var bottom = projectRaw(x1, innerY);
            var bottom2 = projectRaw(x0, innerY);
            var fill = far
                ? (i % 2 ? 'rgba(15, 118, 110, 0.55)' : 'rgba(30, 41, 59, 0.66)')
                : (i % 2 ? 'rgba(30, 41, 59, 0.66)' : 'rgba(15, 118, 110, 0.55)');
            polygon([top, top2, bottom, bottom2], fill);
        }
    }

    function drawPitch() {
        polygon(
            [project(0, 0), project(1, 0), project(1, 1), project(0, 1)],
            '#0b5a30'
        );

        var bands = 14;
        for (var i = 0; i < bands; i += 1) {
            var y0 = i / bands;
            var y1 = (i + 1) / bands;
            polygon(
                [project(0, y0), project(1, y0), project(1, y1), project(0, y1)],
                i % 2 === 0 ? '#0f6838' : '#0c5b31'
            );
        }

        // Mowing light and subtle grass texture.
        var light = ctx.createRadialGradient(width / 2, height * 0.4, 8, width / 2, height * 0.58, width * 0.72);
        light.addColorStop(0, 'rgba(220, 252, 231, 0.10)');
        light.addColorStop(1, 'rgba(220, 252, 231, 0)');
        polygon([project(0, 0), project(1, 0), project(1, 1), project(0, 1)], light);

        var random = seededRandom(7331);
        ctx.save();
        polygon([project(0, 0), project(1, 0), project(1, 1), project(0, 1)], null);
        ctx.clip();
        for (var speck = 0; speck < 460; speck += 1) {
            var x = random() * width;
            var y = random() * height;
            ctx.globalAlpha = 0.045 + random() * 0.08;
            ctx.fillStyle = random() > 0.5 ? '#d1fae5' : '#052e16';
            ctx.fillRect(x, y, 1.3, 1.3);
        }
        ctx.globalAlpha = 1;
        ctx.restore();

        var chalk = 'rgba(248, 250, 252, 0.78)';
        var chalkSoft = 'rgba(248, 250, 252, 0.42)';

        polygon([project(0, 0), project(1, 0), project(1, 1), project(0, 1)], null, chalk, 1.9);

        line(project(0, 0.5), project(1, 0.5), chalk, 1.5);

        // Centre circle and spot.
        drawProjectedCircle(0.5, 0.5, 0.085, chalkSoft, 1.3);
        ctx.beginPath();
        var centre = project(0.5, 0.5);
        ctx.arc(centre.x, centre.y, 1.8 * centre.s, 0, TAU);
        ctx.fillStyle = chalkSoft;
        ctx.fill();

        [0, 1].forEach(function (end) {
            var boxNear = end === 1 ? 1 : 0.165;
            var boxFar = end === 1 ? 0.835 : 0;
            polygon([
                project(0.22, boxFar), project(0.78, boxFar),
                project(0.78, boxNear), project(0.22, boxNear)
            ], null, chalkSoft, 1.2);
            var smallNear = end === 1 ? 1 : 0.058;
            var smallFar = end === 1 ? 0.942 : 0;
            polygon([
                project(0.36, smallFar), project(0.64, smallFar),
                project(0.64, smallNear), project(0.36, smallNear)
            ], null, 'rgba(248, 250, 252, 0.30)', 1);

            var spotY = end === 1 ? 0.885 : 0.115;
            var spot = project(0.5, spotY);
            ctx.beginPath();
            ctx.arc(spot.x, spot.y, 1.9 * spot.s, 0, TAU);
            ctx.fillStyle = chalkSoft;
            ctx.fill();

            // Penalty arc outside the box.
            var arcStart = end === 0 ? 0 : Math.PI;
            var arcEnd = end === 0 ? Math.PI : TAU;
            drawProjectedArc(0.5, spotY, 0.095, arcStart, arcEnd, chalkSoft, 1.1);

            // Corner arcs.
            drawProjectedArc(0.015, end === 0 ? 0.015 : 0.985, 0.018, 0, TAU, 'rgba(248, 250, 252, 0.30)', 1);
            drawProjectedArc(0.985, end === 0 ? 0.015 : 0.985, 0.018, 0, TAU, 'rgba(248, 250, 252, 0.30)', 1);
        });

        drawGoal(0);
        drawGoal(1);

        // Vignette keeps the broadcast feel.
        var vignette = ctx.createRadialGradient(width / 2, height * 0.52, width * 0.28, width / 2, height * 0.52, width * 0.82);
        vignette.addColorStop(0, 'rgba(2, 6, 23, 0)');
        vignette.addColorStop(1, 'rgba(2, 6, 23, 0.34)');
        ctx.fillStyle = vignette;
        ctx.fillRect(0, 0, width, height);
    }

    function drawProjectedCircle(cx, cy, radius, color, lineWidth) {
        ctx.beginPath();
        for (var step = 0; step <= 56; step += 1) {
            var angle = (step / 56) * TAU;
            var point = project(cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius);
            if (step === 0) ctx.moveTo(point.x, point.y);
            else ctx.lineTo(point.x, point.y);
        }
        ctx.closePath();
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.stroke();
    }

    function drawProjectedArc(cx, cy, radius, startAngle, endAngle, color, lineWidth) {
        ctx.beginPath();
        var steps = 26;
        for (var step = 0; step <= steps; step += 1) {
            var angle = startAngle + ((endAngle - startAngle) * step) / steps;
            var point = project(cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius);
            if (step === 0) ctx.moveTo(point.x, point.y);
            else ctx.lineTo(point.x, point.y);
        }
        ctx.strokeStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.stroke();
    }

    function drawGoal(end) {
        var far = end === 0;
        var goalY = far ? 0 : 1;
        var leftFront = project(0.415, goalY);
        var rightFront = project(0.585, goalY);
        var backY = far ? -0.035 : 1.035;
        var leftBack = projectRaw(0.415, backY);
        var rightBack = projectRaw(0.585, backY);
        var postHeight = 18 * leftFront.s;
        var backPostHeight = 15 * leftBack.s;

        // Net shadow on the grass.
        ctx.save();
        ctx.globalAlpha = 0.25;
        polygon(
            [leftFront, rightFront, rightBack, leftBack],
            '#020617'
        );
        ctx.restore();

        // Net mesh.
        ctx.save();
        ctx.strokeStyle = 'rgba(248, 250, 252, 0.22)';
        ctx.lineWidth = 0.8;
        for (var i = 1; i < 8; i += 1) {
            var t = i / 8;
            line(
                { x: leftFront.x + (rightFront.x - leftFront.x) * t, y: leftFront.y - postHeight },
                { x: leftBack.x + (rightBack.x - leftBack.x) * t, y: leftBack.y - backPostHeight },
                'rgba(248, 250, 252, 0.18)', 0.8
            );
            line(
                { x: leftFront.x + (rightFront.x - leftFront.x) * t, y: leftFront.y },
                { x: leftFront.x + (rightFront.x - leftFront.x) * t, y: leftFront.y - postHeight },
                'rgba(248, 250, 252, 0.16)', 0.8
            );
        }
        for (var row = 1; row < 5; row += 1) {
            var rt = row / 5;
            line(
                { x: leftFront.x, y: leftFront.y - postHeight * rt },
                { x: rightFront.x, y: rightFront.y - postHeight * rt },
                'rgba(248, 250, 252, 0.14)', 0.7
            );
            line(
                { x: leftBack.x, y: leftBack.y - backPostHeight * rt },
                { x: rightBack.x, y: rightBack.y - backPostHeight * rt },
                'rgba(248, 250, 252, 0.10)', 0.7
            );
        }
        ctx.restore();

        // Frame.
        line(leftFront, { x: leftFront.x, y: leftFront.y - postHeight }, 'rgba(248, 250, 252, 0.94)', 2.1 * leftFront.s);
        line(rightFront, { x: rightFront.x, y: rightFront.y - postHeight }, 'rgba(248, 250, 252, 0.94)', 2.1 * leftFront.s);
        line(
            { x: leftFront.x, y: leftFront.y - postHeight },
            { x: rightFront.x, y: rightFront.y - postHeight },
            'rgba(248, 250, 252, 0.8)', 1.5 * leftFront.s
        );
        line(leftFront, leftBack, 'rgba(248, 250, 252, 0.55)', 1);
        line(rightFront, rightBack, 'rgba(248, 250, 252, 0.55)', 1);
    }

    /* ------------------------------------------------------------------ */
    /* Players                                                             */
    /* ------------------------------------------------------------------ */

    function addPlayer(team, slotKey, x, y, player) {
        var layout = SLOT_LAYOUT[slotKey] || { role: 'MID' };
        var role = layout.role;
        var maxSpeed = role === 'GK' ? 0.16 : role === 'DEF' ? 0.27 : role === 'MID' ? 0.31 : 0.35;
        players.push({
            team: team,
            slot: slotKey,
            role: role,
            baseX: x,
            baseY: y,
            x: x,
            y: y,
            vx: 0,
            vy: 0,
            targetX: x,
            targetY: y,
            facing: team === 'home' ? -Math.PI / 2 : Math.PI / 2,
            maxSpeed: maxSpeed,
            name: (player && player.name) || '',
            image: (player && player.image_url) || '',
            overall: (player && player.overall) || 0,
            position: (player && player.primary_position) || '',
            phase: Math.random() * TAU,
            runPhase: Math.random() * TAU
        });
    }

    function setMatch(match) {
        players = [];
        celebration = 0;
        celebrationSide = null;
        message = '';
        messageSub = '';
        messageTeam = '';
        messagePhoto = '';
        messageKind = 'info';
        messageTimer = 0;
        timers = [];
        confetti = [];
        flash = 0;
        shake = 0;
        ballSpin = 0;
        actionSeq += 1;
        matchState = 'idle';
        penaltyMode = false;
        possession = 'home';
        kickoffPlayer = null;
        kickoffLockUntil = 0;
        endedAt = 0;
        ball = {
            x: 0.5, y: 0.5, z: 0,
            mode: 'spot', owner: null, target: null, dest: null,
            speed: 0.8, t: 0, duration: 0, arc: 0,
            onArrive: null, trail: []
        };
        ai.nextDecision = 0;
        if (!match) return;

        matchInfo = {
            homeName: (match.home && match.home.name) || 'Ev sahibi',
            awayName: (match.away && match.away.name) || 'Deplasman',
            score: [0, 0],
            minute: 0,
            phase: 'match'
        };

        ['home', 'away'].forEach(function (side) {
            var snapshot = match[side] || {};
            var squad = snapshot.squad || {};
            Object.keys(squad).forEach(function (slot) {
                var layout = SLOT_LAYOUT[slot];
                if (!layout) return;
                var x = layout.x / 100;
                var y = layout.y / 100;
                if (side === 'away') {
                    x = 1 - x;
                    y = 1 - y;
                }
                addPlayer(side, slot, x, y, squad[slot]);
            });
        });
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

    function nearestPlayer(x, y, team, exclude) {
        var best = null;
        var bestGap = Infinity;
        players.forEach(function (player) {
            if (team && player.team !== team) return;
            if (exclude && player === exclude) return;
            var gap = Math.hypot(player.x - x, player.y - y);
            if (gap < bestGap) {
                bestGap = gap;
                best = player;
            }
        });
        return best;
    }

    function goalkeeperFor(team) {
        var keeper = null;
        players.forEach(function (player) {
            if (player.team === team && player.role === 'GK') keeper = player;
        });
        return keeper || nearestPlayer(0.5, team === 'home' ? 0.94 : 0.06, team);
    }

    function footPosition(player) {
        var facing = player.facing;
        return {
            x: clamp(player.x + Math.cos(facing) * 0.021, 0.01, 0.99),
            y: clamp(player.y + Math.sin(facing) * 0.019, 0.01, 0.99)
        };
    }

    function inPitch(player) {
        return players.indexOf(player) >= 0;
    }

    function drawShadow(x, y, radius, alpha) {
        ctx.beginPath();
        ctx.ellipse(x, y + radius * 0.14, radius * 1.18, radius * 0.42, 0, 0, TAU);
        ctx.fillStyle = 'rgba(0, 0, 0, ' + (alpha === undefined ? 0.34 : alpha) + ')';
        ctx.fill();
    }

    function drawName(player, projected, radius) {
        var colors = TEAM_COLORS[player.team] || TEAM_COLORS.home;
        var font = clamp(radius * 0.63, 6.2, 10.5);
        var label = shortName(player.name);
        ctx.font = '700 ' + font.toFixed(1) + 'px system-ui, -apple-system, sans-serif';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        var textWidth = ctx.measureText(label).width;
        var padX = 4.5;
        var boxWidth = textWidth + padX * 2 + 3;
        var boxHeight = font + 4.6;
        var baseTop = projected.y + radius * 0.42;
        var left = projected.x - boxWidth / 2;
        var top = baseTop;

        // Nudge the plate until it no longer covers another player's plate.
        // Names stay attached to their player (below, then above) instead of
        // piling up on the same pixels in crowded areas.
        for (var pass = 0; pass < 2; pass += 1) {
            var moved = true;
            var guard = 0;
            while (moved && guard < 7) {
                moved = false;
                guard += 1;
                for (var i = 0; i < labelBoxes.length; i += 1) {
                    var other = labelBoxes[i];
                    if (left < other.left + other.width + 2 &&
                        left + boxWidth + 2 > other.left &&
                        top < other.top + other.height + 1 &&
                        top + boxHeight + 1 > other.top) {
                        top = pass === 0
                            ? other.top + other.height + 2
                            : other.top - boxHeight - 2;
                        moved = true;
                    }
                }
            }
            if (top >= 3 && top + boxHeight <= height - 3) break;
            top = baseTop - radius - boxHeight - 3;
        }
        top = clamp(top, 3, Math.max(3, height - boxHeight - 3));
        labelBoxes.push({ left: left, top: top, width: boxWidth, height: boxHeight });

        ctx.fillStyle = 'rgba(2, 6, 23, 0.78)';
        roundRect(left, top, boxWidth, boxHeight, 3.4);
        ctx.fill();
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.10)';
        ctx.lineWidth = 0.7;
        ctx.stroke();
        ctx.fillStyle = colors.fill;
        roundRect(left, top, 2.4, boxHeight, 1.2);
        ctx.fill();
        ctx.fillStyle = colors.light;
        ctx.fillText(label, projected.x + 1, top + boxHeight / 2 + 0.4);
    }

    function drawPlayerName(player) {
        var projected = project(player.x, player.y);
        drawName(player, projected, 9.2 * projected.s);
    }

    function drawPlayer(player) {
        var projected = project(player.x, player.y);
        var colors = TEAM_COLORS[player.team] || TEAM_COLORS.home;
        var celebrating = celebration > 0 && celebrationSide === player.team;
        var bounce = celebrating
            ? Math.abs(Math.sin(time * 9 + player.phase)) * 5.5 * projected.s
            : 0;
        var radius = 9.2 * projected.s;
        var centerY = projected.y - radius * 0.98 - bounce;

        drawShadow(projected.x, projected.y, radius, celebrating ? 0.28 : 0.34);

        if (celebrating) {
            ctx.beginPath();
            ctx.arc(projected.x, centerY, radius * 1.55, 0, TAU);
            ctx.fillStyle = colors.glow;
            ctx.fill();
        }

        // Ball-carrier spotlight.
        if (ball.owner === player) {
            var pulse = 1 + Math.sin(time * 4.2) * 0.12;
            ctx.beginPath();
            ctx.arc(projected.x, projected.y, radius * 1.2 * pulse, 0, TAU);
            ctx.strokeStyle = colors.fill;
            ctx.lineWidth = Math.max(1, 1.3 * projected.s);
            ctx.stroke();
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
            ctx.font = '800 ' + Math.max(7, Math.round(radius * 0.88)) + 'px system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(initials(player.name), projected.x, centerY + 0.4);
        }

        // Two rings in club colours and a crisp white outline.
        ctx.beginPath();
        ctx.arc(projected.x, centerY, radius, 0, TAU);
        ctx.lineWidth = Math.max(1.4, 1.8 * projected.s);
        ctx.strokeStyle = 'rgba(248, 250, 252, 0.94)';
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(projected.x, centerY, radius * 0.86, 0, TAU);
        ctx.lineWidth = Math.max(1.1, 1.5 * projected.s);
        ctx.strokeStyle = colors.fill;
        ctx.stroke();

        // Possession chevron above the player.
        if (ball.owner === player) {
            var chevronY = centerY - radius - 7 * projected.s;
            ctx.beginPath();
            ctx.moveTo(projected.x - 4 * projected.s, chevronY - 3 * projected.s);
            ctx.lineTo(projected.x + 4 * projected.s, chevronY - 3 * projected.s);
            ctx.lineTo(projected.x, chevronY + 2 * projected.s);
            ctx.closePath();
            ctx.fillStyle = colors.fill;
            ctx.fill();
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
            ctx.lineWidth = 0.8;
            ctx.stroke();
        }
    }

    function drawBall() {
        var projected = project(ball.x, ball.y);
        var radius = Math.max(3.1, 4.9 * projected.s);
        var lift = ball.z * height * 2.1 + Math.sin(time * 4.6 + ballSpin) * 0.6 * projected.s;

        // Motion trail.
        if (ball.trail.length > 1) {
            for (var i = 0; i < ball.trail.length; i += 1) {
                var point = ball.trail[i];
                var fade = (i + 1) / ball.trail.length;
                var trailProjected = project(point.x, point.y);
                ctx.beginPath();
                ctx.arc(
                    trailProjected.x,
                    trailProjected.y - point.z * height * 2.1,
                    radius * 0.7 * fade,
                    0, TAU
                );
                ctx.fillStyle = 'rgba(248, 250, 252, ' + (0.06 + fade * 0.14) + ')';
                ctx.fill();
            }
        }

        drawShadow(projected.x, projected.y, radius * (1 + ball.z * 3), 0.26 - ball.z * 0.6);

        ctx.beginPath();
        ctx.arc(projected.x, projected.y - lift, radius, 0, TAU);
        ctx.fillStyle = '#f8fafc';
        ctx.fill();
        ctx.strokeStyle = 'rgba(15, 23, 42, 0.65)';
        ctx.lineWidth = Math.max(0.7, radius * 0.15);
        ctx.stroke();

        ctx.fillStyle = '#0f172a';
        for (var patch = 0; patch < 3; patch += 1) {
            var angle = ballSpin + patch * (TAU / 3);
            ctx.beginPath();
            ctx.arc(
                projected.x + Math.cos(angle) * radius * 0.42,
                projected.y - lift + Math.sin(angle) * radius * 0.34,
                radius * 0.18, 0, TAU
            );
            ctx.fill();
        }
    }

    /* ------------------------------------------------------------------ */
    /* Movement, possession and passing AI                                 */
    /* ------------------------------------------------------------------ */

    function directionFor(team) {
        return team === 'home' ? -1 : 1;
    }

    function attackingGoal(team) {
        return team === 'home' ? { x: 0.5, y: 0.01 } : { x: 0.5, y: 0.99 };
    }

    function targetFor(player) {
        var dir = directionFor(player.team);
        var inPossession = possession === player.team;
        var push = inPossession ? 1 : -0.34;
        var ballAdvance = clamp((ball.y - 0.5) * 2, -1, 1);

        if (player === ball.owner && matchState === 'playing' && celebration <= 0) {
            var goal = attackingGoal(player.team);
            var lead = 0.13;
            return {
                x: clamp(player.x + (goal.x - player.x) * lead, 0.05, 0.95),
                y: clamp(player.y + (goal.y - player.y) * lead, 0.04, 0.96)
            };
        }

        if (player.role === 'GK') {
            var keeperY = player.team === 'home' ? 0.94 : 0.06;
            if (Math.abs(ball.y - keeperY) < 0.22) keeperY = player.team === 'home' ? 0.90 : 0.10;
            return {
                x: clamp(0.5 + (ball.x - 0.5) * 0.34, 0.36, 0.64),
                y: keeperY
            };
        }

        var baseX = player.baseX;
        var baseY = player.baseY;
        var targetX = baseX;
        var targetY = baseY;

        if (player.role === 'DEF') {
            targetX = baseX * 0.8 + ball.x * 0.2;
            targetY = baseY + (ball.y - 0.5) * 0.2 + dir * 0.018 * push;
        } else if (player.role === 'MID') {
            targetX = baseX * 0.7 + ball.x * 0.3;
            targetY = baseY + (ball.y - 0.5) * 0.24 + dir * 0.035 * push;
        } else {
            var run = Math.sin(time * 0.55 + player.runPhase) * 0.028;
            targetX = baseX * 0.82 + ball.x * 0.18 + run;
            targetY = baseY + (ball.y - 0.5) * 0.22 + dir * 0.05 * push
                + Math.cos(time * 0.42 + player.phase) * 0.012;
        }

        // Wingers hug the touchline a little more when their team has the ball.
        if ((player.slot === 'lw' || player.slot === 'rw') && inPossession) {
            targetX += (baseX - 0.5) * 0.08;
        }

        // At kick-off both teams stay in their own half except the kicker.
        if (time < kickoffLockUntil && player !== kickoffPlayer) {
            if (player.team === 'home') targetY = Math.max(targetY, 0.53);
            else targetY = Math.min(targetY, 0.47);
        }

        // A small pressing step toward the ball when defending.
        if (!inPossession && player.role !== 'GK') {
            var press = clamp(1 - Math.hypot(player.x - ball.x, player.y - ball.y) / 0.34, 0, 1);
            targetX += (ball.x - player.x) * press * 0.15;
            targetY += (ball.y - player.y) * press * 0.12;
        }

        return {
            x: clamp(targetX, 0.045, 0.955),
            y: clamp(targetY, 0.035, 0.965)
        };
    }

    function movePlayers(dt) {
        players.forEach(function (player) {
            if (matchState === 'ended' && time - endedAt > 0.6) {
                player.vx *= Math.max(0, 1 - dt * 6);
                player.vy *= Math.max(0, 1 - dt * 6);
                player.x = clamp(player.x + player.vx * dt, 0.03, 0.97);
                player.y = clamp(player.y + player.vy * dt, 0.03, 0.97);
                return;
            }

            var target = targetFor(player);
            player.targetX = target.x;
            player.targetY = target.y;

            var dx = target.x - player.x;
            var dy = target.y - player.y;
            var distance = Math.hypot(dx, dy);
            var speed = 0;
            if (distance > 0.006) {
                speed = Math.min(player.maxSpeed, distance * 4.4);
            }
            var desiredVx = distance > 0.001 ? (dx / distance) * speed : 0;
            var desiredVy = distance > 0.001 ? (dy / distance) * speed : 0;
            var accel = 1 - Math.exp(-dt * 6.4);
            player.vx += (desiredVx - player.vx) * accel;
            player.vy += (desiredVy - player.vy) * accel;
            player.x = clamp(player.x + player.vx * dt, 0.03, 0.97);
            player.y = clamp(player.y + player.vy * dt, 0.03, 0.97);

            if (Math.hypot(player.vx, player.vy) > 0.014) {
                player.facing = Math.atan2(player.vy, player.vx);
            } else {
                player.facing = player.team === 'home' ? -Math.PI / 2 : Math.PI / 2;
            }
        });

        // Keep bodies from stacking on top of each other.
        for (var i = 0; i < players.length; i += 1) {
            for (var j = i + 1; j < players.length; j += 1) {
                var a = players[i];
                var b = players[j];
                var dx = b.x - a.x;
                var dy = b.y - a.y;
                var gap = Math.hypot(dx, dy);
                if (gap > 0.034 || gap < 0.0001) continue;
                var push = (0.034 - gap) * 0.55;
                var nx = dx / gap;
                var ny = dy / gap;
                a.x = clamp(a.x - nx * push, 0.03, 0.97);
                a.y = clamp(a.y - ny * push, 0.03, 0.97);
                b.x = clamp(b.x + nx * push, 0.03, 0.97);
                b.y = clamp(b.y + ny * push, 0.03, 0.97);
            }
        }
    }

    function setBallOwner(player) {
        if (!player) return;
        ball.mode = 'owned';
        ball.owner = player;
        ball.target = null;
        ball.dest = null;
        ball.onArrive = null;
        ball.t = 0;
        ball.duration = 0;
        ball.arc = 0;
        ball.z = 0;
        possession = player.team;
        ai.nextDecision = time + 0.9 + Math.random() * 1.25;
    }

    function passTo(target, options) {
        if (!target) return;
        var opts = options || {};
        if (ball.owner === target) {
            if (opts.onArrive) {
                var seq = actionSeq;
                schedule(opts.delay || 0.08, function () {
                    if (seq === actionSeq) opts.onArrive();
                });
            }
            return;
        }
        ball.mode = 'pass';
        ball.owner = null;
        ball.target = target;
        ball.dest = null;
        ball.speed = opts.speed || 0.86;
        ball.arc = opts.arc === undefined ? 0.008 : opts.arc;
        ball.t = 0;
        var targetFoot = footPosition(target);
        ball.duration = clamp(
            Math.hypot(targetFoot.x - ball.x, targetFoot.y - ball.y) / ball.speed,
            0.12,
            1.5
        );
        ball.onArrive = opts.onArrive || null;
        ball.trail = [];
        possession = target.team;
    }

    function shootTo(dest, options) {
        var opts = options || {};
        ball.mode = 'shot';
        ball.owner = null;
        ball.target = null;
        ball.dest = { x: clamp(dest.x, 0.01, 0.99), y: clamp(dest.y, 0.01, 0.99) };
        ball.speed = opts.speed || 1.55;
        ball.arc = opts.arc === undefined ? 0.016 : opts.arc;
        ball.t = 0;
        ball.duration = clamp(
            Math.hypot(ball.dest.x - ball.x, ball.dest.y - ball.y) / ball.speed,
            0.12,
            1.5
        );
        ball.onArrive = opts.onArrive || null;
        ball.trail = [];
    }

    function ballToSpot(x, y) {
        ball.mode = 'spot';
        ball.owner = null;
        ball.target = null;
        ball.dest = { x: x, y: y };
        ball.x = x;
        ball.y = y;
        ball.z = 0;
        ball.onArrive = null;
        ball.trail = [];
    }

    function updateBall(dt) {
        if (ball.owner && !inPitch(ball.owner)) {
            ball.owner = null;
            ball.mode = 'loose';
        }

        if (ball.mode === 'owned' && ball.owner) {
            var foot = footPosition(ball.owner);
            var glue = 1 - Math.exp(-dt * 17);
            ball.x += (foot.x - ball.x) * glue;
            ball.y += (foot.y - ball.y) * glue;
            ball.z += (0 - ball.z) * glue;
            var carrySpeed = Math.hypot(ball.owner.vx, ball.owner.vy);
            ballSpin += dt * (2.4 + carrySpeed * 13);
            pushTrail(0.42);
            return;
        }

        if (ball.mode === 'pass' && ball.target) {
            if (!inPitch(ball.target)) {
                ball.mode = 'loose';
                ball.target = null;
            } else {
                var targetFoot = footPosition(ball.target);
                ball.t += dt;
                var passDistance = Math.hypot(targetFoot.x - ball.x, targetFoot.y - ball.y);
                var passSpeed = Math.max(0.24, ball.speed);
                var passStep = passSpeed * dt;
                if (passDistance <= passStep + 0.008) {
                    ball.x = targetFoot.x;
                    ball.y = targetFoot.y;
                    ball.z = 0;
                    var arrived = ball.onArrive;
                    setBallOwner(ball.target);
                    if (arrived) arrived();
                } else {
                    ball.x += ((targetFoot.x - ball.x) / passDistance) * passStep;
                    ball.y += ((targetFoot.y - ball.y) / passDistance) * passStep;
                    var passProgress = clamp(ball.t / Math.max(0.12, ball.duration), 0, 1);
                    ball.z = Math.sin(passProgress * Math.PI) * ball.arc;
                    ballSpin += dt * 7;
                }
                pushTrail(0.75);
                return;
            }
        }

        if (ball.mode === 'shot' && ball.dest) {
            ball.t += dt;
            var shotDistance = Math.hypot(ball.dest.x - ball.x, ball.dest.y - ball.y);
            var shotStep = ball.speed * dt;
            if (shotDistance <= shotStep + 0.008) {
                ball.x = ball.dest.x;
                ball.y = ball.dest.y;
                ball.z = 0;
                var onArrive = ball.onArrive;
                ball.onArrive = null;
                if (onArrive) onArrive();
                else ball.mode = 'loose';
            } else {
                ball.x += ((ball.dest.x - ball.x) / shotDistance) * shotStep;
                ball.y += ((ball.dest.y - ball.y) / shotDistance) * shotStep;
                var shotProgress = clamp(ball.t / Math.max(0.12, ball.duration), 0, 1);
                ball.z = Math.sin(shotProgress * Math.PI) * ball.arc;
                ballSpin += dt * 12;
            }
            pushTrail(1);
            return;
        }

        if (ball.mode === 'spot' || ball.mode === 'net' || ball.mode === 'loose') {
            if (ball.mode === 'loose' && ball.dest) {
                var looseDistance = Math.hypot(ball.dest.x - ball.x, ball.dest.y - ball.y);
                if (looseDistance > 0.01) {
                    var looseStep = 0.7 * dt;
                    ball.x += ((ball.dest.x - ball.x) / looseDistance) * looseStep;
                    ball.y += ((ball.dest.y - ball.y) / looseDistance) * looseStep;
                    ball.z = Math.sin(clamp(looseDistance / 0.3, 0, 1) * Math.PI) * 0.005;
                } else {
                    ball.x = ball.dest.x;
                    ball.y = ball.dest.y;
                    ball.z = 0;
                }
            }
            pushTrail(0.25);
        }
    }

    function pushTrail(strength) {
        var last = ball.trail[ball.trail.length - 1];
        if (last && Math.hypot(last.x - ball.x, last.y - ball.y) < 0.008) return;
        ball.trail.push({ x: ball.x, y: ball.y, z: ball.z });
        if (ball.trail.length > 6) ball.trail.shift();
        if (strength > 0.5 && ball.trail.length > 6) ball.trail.shift();
    }

    function choosePassTarget(carrier) {
        var dir = directionFor(carrier.team);
        var candidates = [];
        players.forEach(function (player) {
            if (player === carrier || player.team !== carrier.team) return;
            if (carrier.role !== 'GK' && player.role === 'GK') return;
            var distance = Math.hypot(player.x - carrier.x, player.y - carrier.y);
            if (distance < 0.055 || distance > 0.42) return;
            var nearestOpponent = nearestPlayer(player.x, player.y, carrier.team === 'home' ? 'away' : 'home');
            var pressure = nearestOpponent
                ? Math.hypot(nearestOpponent.x - player.x, nearestOpponent.y - player.y)
                : 0.4;
            var forward = (player.y - carrier.y) * dir;
            var score = forward * 3.4 + pressure * 1.8 - Math.abs(distance - 0.2) * 1.4;
            if (carrier.role === 'GK' && player.role === 'DEF') score += 1.6;
            if (player.role === 'FWD') score += 0.35;
            candidates.push({ player: player, score: score });
        });
        if (!candidates.length) return null;
        candidates.sort(function (a, b) { return b.score - a.score; });
        var pool = candidates.slice(0, Math.min(4, candidates.length));
        return pool[Math.floor(Math.random() * pool.length)].player;
    }

    function runPossessionAI() {
        if (matchState !== 'playing' || penaltyMode || celebration > 0) return;
        if (time < kickoffLockUntil) return;

        if (!ball.owner) {
            if (ball.mode === 'spot' && time >= ai.nextDecision) {
                var player = nearestPlayer(ball.x, ball.y, null);
                if (player) setBallOwner(player);
                else ai.nextDecision = time + 0.8;
            }
            return;
        }
        if (time < ai.nextDecision) return;

        var carrier = ball.owner;
        var target = choosePassTarget(carrier);
        if (!target) {
            ai.nextDecision = time + 1;
            return;
        }
        passTo(target, {
            speed: 0.72 + Math.random() * 0.28,
            arc: 0.005 + Math.random() * 0.012
        });
    }

    /* ------------------------------------------------------------------ */
    /* Event beats                                                         */
    /* ------------------------------------------------------------------ */

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

    function guard(fn) {
        var seq = actionSeq;
        return function () {
            if (seq !== actionSeq) return;
            fn();
        };
    }

    function showMessage(text, sub, kind, seconds) {
        message = text;
        messageSub = sub || '';
        messageKind = kind || 'info';
        messageTimer = seconds || 1.4;
    }

    function spawnConfetti(side) {
        var colors = side === 'away'
            ? ['#7dd3fc', '#38bdf8', '#bae6fd', '#f8fafc']
            : ['#86efac', '#22c55e', '#bbf7d0', '#f8fafc'];
        for (var i = 0; i < 80; i += 1) {
            confetti.push({
                x: width / 2 + (Math.random() - 0.5) * width * 0.35,
                y: height * 0.26 + (Math.random() - 0.5) * height * 0.1,
                vx: (Math.random() - 0.5) * 160,
                vy: -40 - Math.random() * 150,
                gravity: 110 + Math.random() * 80,
                rot: Math.random() * TAU,
                vr: (Math.random() - 0.5) * 9,
                size: 3 + Math.random() * 4,
                color: colors[Math.floor(Math.random() * colors.length)],
                life: 1.4 + Math.random() * 1.4
            });
        }
    }

    function onEvent(event) {
        if (!event) return;
        actionSeq += 1;
        timers = [];

        if (event.score) matchInfo.score = [event.score[0], event.score[1]];
        if (event.phase === 'penalties') {
            matchInfo.minute = 'PEN';
            matchInfo.phase = 'penalties';
        } else {
            if (typeof event.minute === 'number') matchInfo.minute = event.minute;
            matchInfo.phase = 'match';
        }

        var side = event.side === 'away' ? 'away' : 'home';
        var player = findPlayer(side, event.player);

        if (event.type === 'kickoff') {
            matchState = 'playing';
            penaltyMode = false;
            celebration = 0;
            celebrationSide = null;
            flash = 0;
            kickoffPlayer = findPlayer(side, event.player) || nearestPlayer(0.5, 0.5, side);
            kickoffLockUntil = time + 1.15;
            possession = side;
            if (kickoffPlayer) {
                kickoffPlayer.x = 0.5;
                kickoffPlayer.y = side === 'home' ? 0.545 : 0.455;
                kickoffPlayer.vx = 0;
                kickoffPlayer.vy = 0;
                kickoffPlayer.facing = side === 'home' ? -Math.PI / 2 : Math.PI / 2;
            }
            ballToSpot(0.5, 0.5);
            if (kickoffPlayer) {
                passTo(kickoffPlayer, { speed: 0.74, arc: 0.003 });
            }
            showMessage('SANTRA', event.team || '', 'info', 1.4);
            ai.nextDecision = time + 1.9;
            return;
        }

        if (event.type === 'half') {
            matchState = 'halftime';
            penaltyMode = false;
            celebration = 0;
            celebrationSide = null;
            ballToSpot(0.5, 0.5);
            ball.mode = 'spot';
            showMessage('İLK YARI SONU', matchInfo.score[0] + ' - ' + matchInfo.score[1], 'info', 2.6);
            kickoffLockUntil = 0;
            return;
        }

        if (event.type === 'full') {
            matchState = 'ended';
            penaltyMode = false;
            endedAt = time;
            celebration = 0;
            celebrationSide = null;
            ai.nextDecision = Infinity;
            if (!ball.owner) ballToSpot(0.5, 0.5);
            showMessage('MAÇ SONU', matchInfo.score[0] + ' - ' + matchInfo.score[1], 'info', 3.2);
            return;
        }

        if (event.phase === 'penalties') {
            penaltyMode = true;
            matchState = 'penalties';
            celebration = 0;
            celebrationSide = null;
            var keeperSide = side === 'home' ? 'away' : 'home';
            var shooter = findPlayer(side, event.player) || nearestPlayer(0.5, 0.5, side);
            var keeper = goalkeeperFor(keeperSide);
            var goalY = side === 'home' ? 0 : 1;
            var spotY = side === 'home' ? 0.115 : 0.885;
            var runUpY = side === 'home' ? 0.21 : 0.79;
            if (shooter) {
                shooter.x = 0.5;
                shooter.y = runUpY;
                shooter.vx = 0;
                shooter.vy = 0;
                shooter.facing = side === 'home' ? -Math.PI / 2 : Math.PI / 2;
            }
            if (keeper) {
                keeper.x = 0.5;
                keeper.y = goalY === 0 ? 0.035 : 0.965;
                keeper.vx = 0;
                keeper.vy = 0;
            }
            ballToSpot(0.5, spotY);
            var scored = event.type === 'penalty_scored';
            showMessage(scored ? 'GOL!' : 'KAÇTI!', event.player || '', scored ? 'goal' : 'info', 1.7);
            if (scored) {
                celebration = 1.1;
                celebrationSide = side;
                spawnConfetti(side);
            }
            schedule(0.35, guard(function () {
                if (scored) {
                    shootTo({ x: 0.5 + (Math.random() - 0.5) * 0.12, y: goalY }, {
                        speed: 1.8,
                        arc: 0.012,
                        onArrive: function () {
                            ball.mode = 'net';
                            ball.z = 0;
                        }
                    });
                } else {
                    shootTo({
                        x: Math.random() < 0.5 ? 0.28 : 0.72,
                        y: goalY
                    }, {
                        speed: 1.7,
                        arc: 0.03,
                        onArrive: function () {
                            ball.mode = 'loose';
                            ball.owner = null;
                            ball.dest = keeper ? footPosition(keeper) : null;
                            schedule(0.55, guard(function () {
                                if (keeper) setBallOwner(keeper);
                            }));
                        }
                    });
                }
            }));
            return;
        }

        var goalSideY = side === 'home' ? 0.012 : 0.988;

        if (event.type === 'goal') {
            celebration = 1.9;
            celebrationSide = side;
            flash = 0.5;
            flashColor = side === 'home' ? 'rgba(134, 239, 172, 0.5)' : 'rgba(125, 211, 252, 0.5)';
            shake = 1;
            messagePhoto = player ? player.image : '';
            messageSub = event.player ? event.player : '';
            messageTeam = event.team || '';
            showMessage('GOL!', event.player || event.team || '', 'goal', 2.3);
            spawnConfetti(side);

            function finishGoal() {
                ball.mode = 'net';
                ball.owner = null;
                ball.z = 0;
                ball.trail = [];
            }

            function takeShot() {
                var goalX = 0.42 + Math.random() * 0.16;
                shootTo({ x: goalX, y: goalSideY }, {
                    speed: 1.72,
                    arc: 0.022,
                    onArrive: finishGoal
                });
            }

            if (player && ball.owner !== player) {
                passTo(player, {
                    speed: 1.02,
                    arc: 0.006,
                    onArrive: guard(function () {
                        schedule(0.12, guard(takeShot));
                    })
                });
            } else {
                schedule(0.16, guard(takeShot));
            }
            // Safety net for older timelines without a kick-off event.
            schedule(5.2, guard(function () {
                if (matchState === 'playing' && ceremonyIsIdle()) {
                    restartFromCentre(side === 'home' ? 'away' : 'home');
                }
            }));
            return;
        }

        if (event.type === 'save') {
            var keeper = findPlayer(side === 'home' ? 'away' : 'home', event.keeper)
                || goalkeeperFor(side === 'home' ? 'away' : 'home');
            showMessage('KURTARDI!', player ? player.name : '', 'info', 1.3);
            if (player && ball.owner !== player) {
                passTo(player, {
                    speed: 0.95,
                    arc: 0.006,
                    onArrive: guard(function () {
                        schedule(0.1, guard(function () {
                            shootTo(keeper ? footPosition(keeper) : { x: 0.5, y: goalSideY }, {
                                speed: 1.55,
                                arc: 0.018,
                                onArrive: function () {
                                    if (keeper) setBallOwner(keeper);
                                    else assignNearestToBall();
                                }
                            });
                        }));
                    })
                });
            } else {
                schedule(0.1, guard(function () {
                    shootTo(keeper ? footPosition(keeper) : { x: 0.5, y: goalSideY }, {
                        speed: 1.55,
                        arc: 0.018,
                        onArrive: function () {
                            if (keeper) setBallOwner(keeper);
                            else assignNearestToBall();
                        }
                    });
                }));
            }
            return;
        }

        if (event.type === 'miss') {
            var goalKeeper = goalkeeperFor(side === 'home' ? 'away' : 'home');
            showMessage('AUT', event.player || '', 'info', 1.2);
            var wideX = Math.random() < 0.5 ? 0.28 : 0.72;
            if (player && ball.owner !== player) {
                passTo(player, {
                    speed: 0.95,
                    arc: 0.006,
                    onArrive: guard(function () {
                        schedule(0.1, guard(function () {
                            shootTo({ x: wideX, y: goalSideY }, {
                                speed: 1.6,
                                arc: 0.03,
                                onArrive: function () {
                                    ball.mode = 'loose';
                                    ball.owner = null;
                                    ball.dest = goalKeeper ? footPosition(goalKeeper) : null;
                                    schedule(0.7, guard(function () {
                                        if (goalKeeper) setBallOwner(goalKeeper);
                                        else assignNearestToBall();
                                    }));
                                }
                            });
                        }));
                    })
                });
            } else {
                schedule(0.1, guard(function () {
                    shootTo({ x: wideX, y: goalSideY }, {
                        speed: 1.6,
                        arc: 0.03,
                        onArrive: function () {
                            ball.mode = 'loose';
                            ball.owner = null;
                            ball.dest = goalKeeper ? footPosition(goalKeeper) : null;
                            schedule(0.7, guard(function () {
                                if (goalKeeper) setBallOwner(goalKeeper);
                                else assignNearestToBall();
                            }));
                        }
                    });
                }));
            }
            return;
        }

        if (event.type === 'blocked') {
            var blocker = nearestPlayer(0.5, side === 'home' ? 0.16 : 0.84, side === 'home' ? 'away' : 'home');
            showMessage('BLOK!', event.player || '', 'info', 1.2);
            if (player && ball.owner !== player) {
                passTo(player, {
                    speed: 0.95,
                    arc: 0.006,
                    onArrive: guard(function () {
                        schedule(0.1, guard(function () {
                            shootTo(blocker ? footPosition(blocker) : { x: 0.5, y: goalSideY }, {
                                speed: 1.3,
                                arc: 0.012,
                                onArrive: function () {
                                    if (blocker) setBallOwner(blocker);
                                    else assignNearestToBall();
                                }
                            });
                        }));
                    })
                });
            } else {
                schedule(0.1, guard(function () {
                    shootTo(blocker ? footPosition(blocker) : { x: 0.5, y: goalSideY }, {
                        speed: 1.3,
                        arc: 0.012,
                        onArrive: function () {
                            if (blocker) setBallOwner(blocker);
                            else assignNearestToBall();
                        }
                    });
                }));
            }
            return;
        }

        if (event.type === 'woodwork') {
            showMessage('DİREK!', event.player || '', 'info', 1.3);
            var postX = Math.random() < 0.5 ? 0.41 : 0.59;
            if (player && ball.owner !== player) {
                passTo(player, {
                    speed: 0.95,
                    arc: 0.006,
                    onArrive: guard(function () {
                        schedule(0.1, guard(function () {
                            shootTo({ x: postX, y: goalSideY }, {
                                speed: 1.6,
                                arc: 0.025,
                                onArrive: function () {
                                    var lucky = nearestPlayer(ball.x, ball.y, null);
                                    if (lucky) setBallOwner(lucky);
                                    else assignNearestToBall();
                                }
                            });
                        }));
                    })
                });
            } else {
                schedule(0.1, guard(function () {
                    shootTo({ x: postX, y: goalSideY }, {
                        speed: 1.6,
                        arc: 0.025,
                        onArrive: function () {
                            var lucky = nearestPlayer(ball.x, ball.y, null);
                            if (lucky) setBallOwner(lucky);
                            else assignNearestToBall();
                        }
                    });
                }));
            }
            return;
        }

        if (event.type === 'corner') {
            var taker = player || nearestPlayer(0.5, goalSideY, side);
            var flagX = taker && taker.x < 0.5 ? 0.065 : 0.935;
            var cornerY = side === 'home' ? 0.035 : 0.965;
            showMessage('KORNER', event.team || '', 'info', 1.25);
            if (taker) {
                taker.x = flagX;
                taker.y = cornerY;
                taker.vx = 0;
                taker.vy = 0;
            }
            ballToSpot(flagX, cornerY);
            if (taker) {
                passTo(taker, { speed: 0.8, arc: 0.003 });
                schedule(0.95, guard(function () {
                    var boxX = 0.5 + (Math.random() - 0.5) * 0.16;
                    var boxY = side === 'home' ? 0.17 : 0.83;
                    var header = nearestPlayer(boxX, boxY, side, taker);
                    if (!header) header = nearestPlayer(0.5, boxY, side, taker);
                    if (header) {
                        passTo(header, {
                            speed: 1.05,
                            arc: 0.024,
                            onArrive: guard(function () {
                                ai.nextDecision = time + 1.15;
                            })
                        });
                    }
                }));
            }
            return;
        }

        if (event.type === 'foul' || event.type === 'yellow_card' || event.type === 'red_card' || event.type === 'offside') {
            if (event.type === 'yellow_card') {
                showMessage('SARI KART', event.player || '', 'yellow', 1.5);
            } else if (event.type === 'red_card') {
                showMessage('KIRMIZI KART', event.player || '', 'red', 1.7);
                flash = 0.28;
                flashColor = 'rgba(248, 113, 113, 0.36)';
            } else if (event.type === 'offside') {
                showMessage('OFSAYT', event.player || '', 'info', 1.3);
            } else {
                showMessage('FAUL', event.player || '', 'info', 1.2);
            }
            if (player) {
                if (ball.owner !== player) passTo(player, { speed: 0.92, arc: 0.005 });
                schedule(1.3, guard(function () {
                    if (matchState === 'playing') ai.nextDecision = time + 0.3;
                }));
            }
            return;
        }

        // Fallback: make sure the ball still reaches the player in the event.
        if (player) passTo(player, { speed: 0.94, arc: 0.006 });
        else assignNearestToBall();
    }

    function ceremonyIsIdle() {
        return ball.mode === 'net' || ball.mode === 'spot';
    }

    function assignNearestToBall() {
        var player = nearestPlayer(ball.x, ball.y, null);
        if (player) setBallOwner(player);
    }

    function restartFromCentre(side) {
        var kicker = nearestPlayer(0.5, 0.5, side);
        if (kicker) {
            kicker.x = 0.5;
            kicker.y = side === 'home' ? 0.545 : 0.455;
            kicker.vx = 0;
            kicker.vy = 0;
        }
        ballToSpot(0.5, 0.5);
        if (kicker) passTo(kicker, { speed: 0.74, arc: 0.003 });
        matchState = 'playing';
        penaltyMode = false;
        possession = side;
        kickoffLockUntil = time + 1.1;
        ai.nextDecision = time + 1.8;
        showMessage('SANTRA', '', 'info', 1.2);
    }

    /* ------------------------------------------------------------------ */
    /* Drawing loop                                                        */
    /* ------------------------------------------------------------------ */

    function drawScoreboard() {
        var boxW = Math.min(222, width * 0.52);
        var boxH = 27;
        var x = 12;
        var y = 10;
        ctx.save();
        ctx.fillStyle = 'rgba(2, 6, 23, 0.74)';
        roundRect(x, y, boxW, boxH, 6);
        ctx.fill();
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.14)';
        ctx.lineWidth = 0.9;
        ctx.stroke();

        var home = TEAM_COLORS.home;
        var away = TEAM_COLORS.away;
        ctx.beginPath();
        ctx.arc(x + 12, y + boxH / 2, 3.3, 0, TAU);
        ctx.fillStyle = home.fill;
        ctx.fill();
        ctx.beginPath();
        ctx.arc(x + boxW - 12, y + boxH / 2, 3.3, 0, TAU);
        ctx.fillStyle = away.fill;
        ctx.fill();

        ctx.font = '700 9.5px system-ui, -apple-system, sans-serif';
        ctx.textBaseline = 'middle';
        ctx.textAlign = 'left';
        ctx.fillStyle = home.light;
        ctx.fillText(shortTeam(matchInfo.homeName), x + 20, y + boxH / 2 + 0.3);
        ctx.textAlign = 'right';
        ctx.fillStyle = away.light;
        ctx.fillText(shortTeam(matchInfo.awayName), x + boxW - 20, y + boxH / 2 + 0.3);

        ctx.textAlign = 'center';
        ctx.font = '800 12.5px system-ui, sans-serif';
        ctx.fillStyle = '#f8fafc';
        ctx.fillText(matchInfo.score[0] + ' - ' + matchInfo.score[1], x + boxW / 2, y + boxH / 2 + 0.5);
        ctx.restore();

        var minuteLabel = matchInfo.minute === 'PEN' ? 'PEN' : matchInfo.minute + "'";
        ctx.save();
        ctx.font = '800 10px system-ui, sans-serif';
        var minuteW = ctx.measureText(minuteLabel).width + 16;
        var minuteX = width - minuteW - 12;
        ctx.fillStyle = 'rgba(2, 6, 23, 0.74)';
        roundRect(minuteX, y, minuteW, boxH, 6);
        ctx.fill();
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.14)';
        ctx.lineWidth = 0.9;
        ctx.stroke();
        ctx.fillStyle = matchInfo.minute === 'PEN' ? '#fcd34d' : '#86efac';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(minuteLabel, minuteX + minuteW / 2, y + boxH / 2 + 0.5);
        ctx.restore();
    }

    function drawMessage() {
        if (!message || messageTimer <= 0) return;
        var alpha = clamp(messageTimer, 0, 1);
        var isGoal = messageKind === 'goal';
        ctx.save();
        ctx.globalAlpha = alpha;

        if (isGoal) {
            var size = Math.round(Math.min(74, width * 0.088));
            var centerX = width / 2;
            var centerY = height * 0.36;
            var pulse = 1 + Math.sin(time * 9) * 0.018;
            ctx.translate(centerX, centerY);
            ctx.scale(pulse, pulse);
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.font = '900 ' + size + 'px system-ui, -apple-system, sans-serif';
            ctx.lineWidth = Math.max(3, size * 0.08);
            ctx.strokeStyle = 'rgba(2, 6, 23, 0.85)';
            ctx.strokeText('GOL!', 0, 0);
            var goalGradient = ctx.createLinearGradient(0, -size / 2, 0, size / 2);
            goalGradient.addColorStop(0, '#f8fafc');
            goalGradient.addColorStop(0.55, '#fde68a');
            goalGradient.addColorStop(1, '#f59e0b');
            ctx.fillStyle = goalGradient;
            ctx.fillText('GOL!', 0, 0);

            if (messageSub) {
                ctx.font = '800 ' + Math.round(size * 0.27) + 'px system-ui, sans-serif';
                var subWidth = ctx.measureText(messageSub).width;
                var subX = 0;
                var subY = size * 0.7;
                ctx.fillStyle = 'rgba(2, 6, 23, 0.78)';
                roundRect(subX - subWidth / 2 - 12, subY - size * 0.19, subWidth + 24, size * 0.38, size * 0.2);
                ctx.fill();
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.22)';
                ctx.lineWidth = 1;
                ctx.stroke();
                ctx.fillStyle = '#f8fafc';
                ctx.textAlign = 'center';
                ctx.textBaseline = 'middle';
                ctx.fillText(messageSub, subX, subY + 1);
            }
            ctx.restore();
            return;
        }

        var font = Math.round(Math.min(19, width * 0.025));
        ctx.font = '900 ' + font + 'px system-ui, sans-serif';
        var textWidth = ctx.measureText(message).width;
        var subWidth = messageSub ? ctx.measureText(messageSub).width : 0;
        var boxW = Math.max(textWidth, subWidth) + 28;
        var boxH = messageSub ? font + 22 : font + 13;
        var cx = width / 2;
        var cy = height * 0.115;
        var fill = messageKind === 'yellow'
            ? 'rgba(202, 138, 4, 0.9)'
            : messageKind === 'red'
                ? 'rgba(185, 28, 28, 0.9)'
                : 'rgba(2, 6, 23, 0.78)';
        ctx.fillStyle = fill;
        roundRect(cx - boxW / 2, cy - boxH / 2, boxW, boxH, boxH / 2);
        ctx.fill();
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.26)';
        ctx.lineWidth = 1;
        ctx.stroke();
        ctx.fillStyle = '#f8fafc';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillText(message, cx, cy + 1);
        if (messageSub) {
            ctx.font = '600 ' + Math.round(font * 0.6) + 'px system-ui, sans-serif';
            ctx.fillStyle = 'rgba(248, 250, 252, 0.72)';
            ctx.fillText(shortName(messageSub), cx, cy + font * 0.72);
        }
        ctx.restore();
    }

    function drawConfetti() {
        if (!confetti.length) return;
        confetti.forEach(function (particle) {
            ctx.save();
            ctx.globalAlpha = clamp(particle.life, 0, 1);
            ctx.translate(particle.x, particle.y);
            ctx.rotate(particle.rot);
            ctx.fillStyle = particle.color;
            ctx.fillRect(-particle.size / 2, -particle.size / 4, particle.size, particle.size / 2);
            ctx.restore();
        });
    }

    function draw() {
        if (!ctx) return;
        if (!pitchCache) buildPitchCache();
        ctx.clearRect(0, 0, width, height);
        if (pitchCache) ctx.drawImage(pitchCache, 0, 0, width, height);

        var shakeX = shake > 0 ? (Math.random() - 0.5) * shake * 9 : 0;
        var shakeY = shake > 0 ? (Math.random() - 0.5) * shake * 6 : 0;

        ctx.save();
        ctx.translate(shakeX, shakeY);

        var ordered = players.slice().sort(function (a, b) { return a.y - b.y; });
        var ballDrawn = false;
        labelBoxes = players.map(function (player) {
            var projected = project(player.x, player.y);
            var radius = 9.2 * projected.s;
            var centerY = projected.y - radius * 0.98;
            return {
                left: projected.x - radius,
                top: centerY - radius,
                width: radius * 2,
                height: radius * 2
            };
        });
        ordered.forEach(function (player) {
            if (!ballDrawn && player.y > ball.y) {
                drawBall();
                ballDrawn = true;
            }
            drawPlayer(player);
        });
        if (!ballDrawn) drawBall();

        // Plates render in a second pass so no body can hide a name.
        ordered.forEach(drawPlayerName);

        drawConfetti();
        drawScoreboard();
        drawMessage();
        ctx.restore();

        if (flash > 0) {
            ctx.fillStyle = flashColor;
            ctx.globalAlpha = clamp(flash, 0, 0.55);
            ctx.fillRect(0, 0, width, height);
            ctx.globalAlpha = 1;
        }
    }

    /* ------------------------------------------------------------------ */
    /* Main loop                                                           */
    /* ------------------------------------------------------------------ */

    function update(dt) {
        time += dt;
        runTimers();
        ballSpin += dt * 1.2;

        if (flash > 0) flash = Math.max(0, flash - dt * 1.6);
        if (messageTimer > 0) messageTimer = Math.max(0, messageTimer - dt);
        if (celebration > 0) celebration = Math.max(0, celebration - dt);
        if (shake > 0) shake = Math.max(0, shake - dt * 2.2);

        movePlayers(dt);
        updateBall(dt);
        runPossessionAI();

        confetti = confetti.filter(function (particle) {
            particle.life -= dt * 0.8;
            if (particle.life <= 0) return false;
            particle.vy += particle.gravity * dt;
            particle.x += particle.vx * dt;
            particle.y += particle.vy * dt;
            particle.rot += particle.vr * dt;
            return particle.y < height + 40;
        });
    }

    function frame(now) {
        if (!running) return;
        var dt = lastTime ? Math.min(0.05, (now - lastTime) / 1000) : 0.016;
        lastTime = now;
        update(dt);
        draw();
        raf = window.requestAnimationFrame(frame);
    }

    function start() {
        if (!canvas || !ctx) return;
        if (running) return;
        if (!width) resize();
        running = true;
        lastTime = 0;
        raf = window.requestAnimationFrame(frame);
    }

    function pause() {
        running = false;
        if (raf) window.cancelAnimationFrame(raf);
        raf = null;
    }

    function endMatch() {
        matchState = 'ended';
        penaltyMode = false;
        ai.nextDecision = Infinity;
        celebration = 0;
        celebrationSide = null;
        endedAt = time;
        if (!ball.owner) {
            ballToSpot(0.5, 0.5);
        }
        showMessage('MAÇ SONU', matchInfo.score[0] + ' - ' + matchInfo.score[1], 'info', 3);
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
        endMatch: endMatch,
        redraw: function () { resize(); draw(); },
        // Read-only view used by the photo/ball smoke tests.
        debugState: function () {
            return {
                ball: {
                    x: ball.x, y: ball.y, z: ball.z, mode: ball.mode,
                    owner: ball.owner ? ball.owner.name : null
                },
                matchState: matchState,
                message: message,
                messageTimer: messageTimer,
                photos: Object.keys(photos).reduce(function (acc, url) {
                    var entry = photos[url];
                    acc.total += 1;
                    if (entry.ready) acc.ready += 1;
                    if (entry.failed) acc.failed += 1;
                    return acc;
                }, { total: 0, ready: 0, failed: 0 }),
                playerImages: players.slice(0, 3).map(function (player) { return player.image; }),
                players: players.map(function (player) {
                    return {
                        x: player.x,
                        y: player.y,
                        team: player.team,
                        name: player.name,
                        role: player.role
                    };
                })
            };
        }
    };
})();
