/* ==========================================================================
   Bilardo fizik motoru
   Sabit zaman adımlı, deterministik ve canvas'tan bağımsız çalışır.
   ========================================================================== */
(function (global) {
    'use strict';

    const CONST = {
        W: 240,
        H: 120,
        R: 2.7,
        POCKET_R: 5.35,
        RAIL: 12,
        STEP: 1 / 480,
        MIN_SPEED: 1.4,
        MAX_SPEED: 900,
        CUSHION_BOUNCE: 0.90,
        BALL_BOUNCE: 0.95,
        CURVE: 30,
        SPIN_DECAY: 0.85,
        HEAD_X: 60,
        FOOT_X: 180,
        CENTER_Y: 60,
        RACK_SPACING: 5.4,
        POCKETS: [
            { x: 0, y: 0, corner: true },
            { x: 120, y: 0, corner: false },
            { x: 240, y: 0, corner: true },
            { x: 0, y: 120, corner: true },
            { x: 120, y: 120, corner: false },
            { x: 240, y: 120, corner: true },
        ],
    };

    const BALL_COLORS = {
        1: '#f5c542', 2: '#2f80ed', 3: '#eb5757', 4: '#9b51e0',
        5: '#f2994a', 6: '#27ae60', 7: '#8e3b3b', 8: '#1f2937',
        9: '#f5c542', 10: '#2f80ed', 11: '#eb5757', 12: '#9b51e0',
        13: '#f2994a', 14: '#27ae60', 15: '#8e3b3b',
    };

    const RACK_ROW = CONST.RACK_SPACING * Math.sqrt(3) / 2;

    function makeBall(id, x, y, options) {
        const opts = options || {};
        return {
            id,
            number: id,
            x,
            y,
            color: opts.color || BALL_COLORS[id] || '#e2e8f0',
            stripe: !!opts.stripe,
            type: opts.type || 'object',
            pocketed: false,
            vx: 0,
            vy: 0,
            spinX: 0,
            spinY: 0,
            r: CONST.R,
        };
    }

    function triangleBalls(numbers) {
        const balls = [];
        let index = 0;
        for (let row = 0; row < 5; row += 1) {
            const count = row + 1;
            const x = CONST.FOOT_X + row * RACK_ROW;
            for (let slot = 0; slot < count; slot += 1) {
                const y = CONST.CENTER_Y + (slot - (count - 1) / 2) * CONST.RACK_SPACING;
                const number = numbers[index];
                balls.push(makeBall(number, x, y, { stripe: number > 8 }));
                index += 1;
            }
        }
        return balls;
    }

    function diamondBalls(numbers) {
        const balls = [];
        let index = 0;
        [1, 2, 3, 2, 1].forEach((count, row) => {
            const x = CONST.FOOT_X + row * RACK_ROW;
            for (let slot = 0; slot < count; slot += 1) {
                const y = CONST.CENTER_Y + (slot - (count - 1) / 2) * CONST.RACK_SPACING;
                balls.push(makeBall(numbers[index], x, y, { stripe: numbers[index] > 8 }));
                index += 1;
            }
        });
        return balls;
    }

    function initialBalls(mode) {
        const cue = makeBall(0, CONST.HEAD_X, CONST.CENTER_Y, {
            type: 'cue',
            color: '#f8fafc',
        });

        if (mode === 'three_cushion') {
            return [
                cue,
                makeBall(1, CONST.FOOT_X, CONST.CENTER_Y, { color: '#eb5757' }),
                makeBall(2, CONST.W / 2, CONST.CENTER_Y, { color: '#f5c542' }),
            ];
        }

        if (mode === 'nine_ball') {
            return [cue].concat(diamondBalls([1, 2, 3, 4, 9, 5, 6, 7, 8]));
        }

        const rack = [1, 9, 2, 3, 8, 10, 11, 4, 12, 5, 6, 13, 7, 14, 15];
        return [cue].concat(triangleBalls(rack));
    }

    function createInitialState(mode, target, breaker) {
        const seat = breaker === 1 ? 1 : 0;
        return {
            mode,
            target,
            breaker: seat,
            balls: initialBalls(mode),
            scores: [0, 0],
            turn: seat,
            ball_in_hand: false,
            break: true,
            groups: [null, null],
            winner: null,
            shot_count: 0,
            message: 'Oyun başladı. İlk vuruşu yap.',
            last_shot: null,
            history: [],
        };
    }

    function cloneState(state) {
        return JSON.parse(JSON.stringify(state));
    }

    class World {
        constructor(state, options) {
            const opts = options || {};
            this.mode = state.mode;
            this.pocketsEnabled = opts.pockets !== undefined ? opts.pockets : state.mode !== 'three_cushion';
            this.onEvent = opts.onEvent || null;
            this.balls = (state.balls || []).map((ball) => ({
                id: ball.id,
                number: ball.number,
                x: Number(ball.x) || 0,
                y: Number(ball.y) || 0,
                color: ball.color,
                stripe: !!ball.stripe,
                type: ball.type,
                pocketed: !!ball.pocketed,
                vx: 0,
                vy: 0,
                spinX: 0,
                spinY: 0,
                r: CONST.R,
                _lastCushion: -10,
            }));
            this.time = 0;
            this.running = false;
            this.events = this._emptyEvents();
            this._pairCooldowns = {};
            this._shotParams = null;
        }

        _emptyEvents() {
            return {
                cueObjectHits: [],
                cushions: [],
                pockets: [],
                ballHits: [],
                firstObjectHit: null,
                firstObjectHitTime: null,
                shot: null,
            };
        }

        getCueBall() {
            return this.balls.find((ball) => ball.id === 0) || null;
        }

        activeBalls() {
            return this.balls.filter((ball) => !ball.pocketed);
        }

        shoot(params) {
            const cue = this.getCueBall();
            if (!cue) return false;

            if (params.cueX !== undefined && params.cueY !== undefined) {
                cue.x = Number(params.cueX);
                cue.y = Number(params.cueY);
                cue.pocketed = false;
            }

            let vx = Number(params.vx) || 0;
            let vy = Number(params.vy) || 0;
            if ((!vx && !vy) && params.angle !== undefined) {
                const speed = Number(params.speed) || 0;
                vx = Math.cos(params.angle) * speed;
                vy = Math.sin(params.angle) * speed;
            }

            const speed = Math.hypot(vx, vy);
            if (speed < 1) return false;

            const cueStats = params.cueStats || { power: 0.6, spin: 0.6, control: 0.6 };
            const spinFactor = 0.72 + (Number(cueStats.spin) || 0.6) * 0.55;

            cue.vx = vx;
            cue.vy = vy;
            cue.spinX = (Number(params.spinX) || 0) * spinFactor;
            cue.spinY = (Number(params.spinY) || 0) * spinFactor;

            this.time = 0;
            this.running = true;
            this.events = this._emptyEvents();
            this.events.shot = {
                angle: Number(params.angle) || 0,
                power: Number(params.power) || 0,
                spinX: Number(params.spinX) || 0,
                spinY: Number(params.spinY) || 0,
                cueStats,
            };
            this._pairCooldowns = {};
            return true;
        }

        step(dt) {
            if (!this.running) return;
            this.time += dt;

            const balls = this.balls;
            for (let i = 0; i < balls.length; i += 1) {
                const ball = balls[i];
                if (ball.pocketed) continue;

                let speed = Math.hypot(ball.vx, ball.vy);
                if (speed > 0) {
                    // Yuvarlanma sürtünmesi: hız düştükçe daha yumuşak yavaşlar.
                    const decel = 22 + speed * 0.045;
                    const nextSpeed = Math.max(0, speed - decel * dt);
                    const scale = nextSpeed / speed;
                    ball.vx *= scale;
                    ball.vy *= scale;
                    speed = nextSpeed;

                    // Yan falso topun yörüngesini hafifçe kıvırır.
                    if (Math.abs(ball.spinX) > 0.02 && speed > 6) {
                        const px = -ball.vy / speed;
                        const py = ball.vx / speed;
                        const curve = ball.spinX * CONST.CURVE;
                        ball.vx += px * curve * dt;
                        ball.vy += py * curve * dt;
                    }

                    ball.spinX *= Math.exp(-CONST.SPIN_DECAY * dt);
                    ball.spinY *= Math.exp(-CONST.SPIN_DECAY * dt);

                    if (speed < CONST.MIN_SPEED) {
                        ball.vx = 0;
                        ball.vy = 0;
                    }
                }

                ball.x += ball.vx * dt;
                ball.y += ball.vy * dt;
            }

            // Delikler bantlardan önce kontrol edilir.
            for (let i = 0; i < balls.length; i += 1) {
                this._checkPocket(balls[i]);
            }

            for (let i = 0; i < balls.length; i += 1) {
                this._checkCushion(balls[i]);
            }

            // Top-top çarpışmalarını iki geçişte çöz.
            for (let pass = 0; pass < 2; pass += 1) {
                for (let i = 0; i < balls.length; i += 1) {
                    if (balls[i].pocketed) continue;
                    for (let j = i + 1; j < balls.length; j += 1) {
                        if (balls[j].pocketed) continue;
                        this._collideBalls(balls[i], balls[j]);
                    }
                }
            }

            let moving = false;
            for (let i = 0; i < balls.length; i += 1) {
                if (balls[i].pocketed) continue;
                if (Math.hypot(balls[i].vx, balls[i].vy) > CONST.MIN_SPEED) {
                    moving = true;
                    break;
                }
            }
            if (!moving) {
                for (let i = 0; i < balls.length; i += 1) {
                    if (!balls[i].pocketed) {
                        balls[i].vx = 0;
                        balls[i].vy = 0;
                        balls[i].spinX = 0;
                        balls[i].spinY = 0;
                    }
                }
                this.running = false;
            }
        }

        _checkPocket(ball) {
            if (!this.pocketsEnabled || ball.pocketed) return;
            for (let i = 0; i < CONST.POCKETS.length; i += 1) {
                const pocket = CONST.POCKETS[i];
                const dx = ball.x - pocket.x;
                const dy = ball.y - pocket.y;
                if (dx * dx + dy * dy <= CONST.POCKET_R * CONST.POCKET_R) {
                    ball.pocketed = true;
                    ball.vx = 0;
                    ball.vy = 0;
                    ball.spinX = 0;
                    ball.spinY = 0;
                    this.events.pockets.push({ ballId: ball.id, t: this.time });
                    this._emit('pocket', ball.id);
                    return;
                }
            }
        }

        _checkCushion(ball) {
            if (ball.pocketed) return;
            let hitX = false;
            let hitY = false;
            let intensity = 0;

            if (ball.x < CONST.R) {
                ball.x = CONST.R;
                if (ball.vx < 0) {
                    intensity = Math.abs(ball.vx);
                    ball.vx = -ball.vx * CONST.CUSHION_BOUNCE;
                    ball.vy += ball.spinX * Math.abs(ball.vx) * 0.18;
                    ball.vx *= 0.985;
                    hitX = true;
                }
            } else if (ball.x > CONST.W - CONST.R) {
                ball.x = CONST.W - CONST.R;
                if (ball.vx > 0) {
                    intensity = Math.abs(ball.vx);
                    ball.vx = -ball.vx * CONST.CUSHION_BOUNCE;
                    ball.vy -= ball.spinX * Math.abs(ball.vx) * 0.18;
                    ball.vx *= 0.985;
                    hitX = true;
                }
            }

            if (ball.y < CONST.R) {
                ball.y = CONST.R;
                if (ball.vy < 0) {
                    intensity = Math.max(intensity, Math.abs(ball.vy));
                    ball.vy = -ball.vy * CONST.CUSHION_BOUNCE;
                    ball.vx += ball.spinX * Math.abs(ball.vy) * 0.18;
                    ball.vy *= 0.985;
                    hitY = true;
                }
            } else if (ball.y > CONST.H - CONST.R) {
                ball.y = CONST.H - CONST.R;
                if (ball.vy > 0) {
                    intensity = Math.max(intensity, Math.abs(ball.vy));
                    ball.vy = -ball.vy * CONST.CUSHION_BOUNCE;
                    ball.vx -= ball.spinX * Math.abs(ball.vy) * 0.18;
                    ball.vy *= 0.985;
                    hitY = true;
                }
            }

            if ((hitX || hitY) && intensity > 5) {
                ball.spinX *= 0.72;
                ball.spinY *= 0.86;
                if (this.time - ball._lastCushion > 0.055) {
                    ball._lastCushion = this.time;
                    this.events.cushions.push({ ballId: ball.id, t: this.time });
                    this._emit('cushion', intensity);
                }
            }
        }

        _collideBalls(a, b) {
            let dx = b.x - a.x;
            let dy = b.y - a.y;
            const minDist = a.r + b.r;
            let dist2 = dx * dx + dy * dy;
            if (dist2 >= minDist * minDist || dist2 === 0) return;

            let dist = Math.sqrt(dist2);
            if (dist === 0) {
                dx = 0.01;
                dy = 0;
                dist = 0.01;
            }
            const nx = dx / dist;
            const ny = dy / dist;
            const overlap = minDist - dist;
            a.x -= nx * overlap * 0.5;
            a.y -= ny * overlap * 0.5;
            b.x += nx * overlap * 0.5;
            b.y += ny * overlap * 0.5;

            const rel = (a.vx - b.vx) * nx + (a.vy - b.vy) * ny;
            if (rel <= 0) return;

            const impulse = -(1 + CONST.BALL_BOUNCE) * rel * 0.5;
            const preCueVx = a.id === 0 ? a.vx : b.vx;
            const preCueVy = a.id === 0 ? a.vy : b.vy;

            a.vx += impulse * nx;
            a.vy += impulse * ny;
            b.vx -= impulse * nx;
            b.vy -= impulse * ny;

            const cue = a.id === 0 ? a : (b.id === 0 ? b : null);
            if (cue) {
                const preSpeed = Math.hypot(preCueVx, preCueVy);
                if (preSpeed > 0.2) {
                    const dirx = preCueVx / preSpeed;
                    const diry = preCueVy / preSpeed;
                    cue.vx += dirx * cue.spinY * 62;
                    cue.vy += diry * cue.spinY * 62;
                    cue.vx += -diry * cue.spinX * 28;
                    cue.vy += dirx * cue.spinX * 28;
                }
                cue.spinX *= 0.55;
                cue.spinY *= 0.35;
            }

            const key = a.id < b.id ? a.id + ':' + b.id : b.id + ':' + a.id;
            const last = this._pairCooldowns[key] || -10;
            if (this.time - last > 0.045) {
                this._pairCooldowns[key] = this.time;
                this.events.ballHits.push({ a: a.id, b: b.id, t: this.time });
                if (cue) {
                    const objectBall = cue === a ? b : a;
                    if (objectBall.id !== 0) {
                        this.events.cueObjectHits.push({ objectId: objectBall.id, t: this.time });
                        if (this.events.firstObjectHit === null) {
                            this.events.firstObjectHit = objectBall.id;
                            this.events.firstObjectHitTime = this.time;
                        }
                    }
                }
                this._emit('ball', Math.abs(rel));
            }
        }

        _emit(type, value) {
            if (typeof this.onEvent === 'function') {
                this.onEvent(type, value);
            }
        }
    }

    function predictShot(world, angle, maxDist) {
        const cue = world.getCueBall();
        if (!cue || cue.pocketed) return null;

        const dx = Math.cos(angle);
        const dy = Math.sin(angle);
        const limit = maxDist || 520;

        let bestT = limit;
        let hitBall = null;

        const balls = world.balls;
        for (let i = 0; i < balls.length; i += 1) {
            const ball = balls[i];
            if (ball.pocketed || ball.id === cue.id) continue;
            const ox = ball.x - cue.x;
            const oy = ball.y - cue.y;
            const proj = ox * dx + oy * dy;
            if (proj <= 0) continue;
            const perp2 = ox * ox + oy * oy - proj * proj;
            const rr = (cue.r + ball.r) * (cue.r + ball.r);
            if (perp2 > rr) continue;
            const t = proj - Math.sqrt(Math.max(0, rr - perp2));
            if (t > 0.001 && t < bestT) {
                bestT = t;
                hitBall = ball;
            }
        }

        let cushion = null;
        let cushionT = Infinity;
        const bounds = [
            { value: CONST.R, axis: 'x', normal: { x: 1, y: 0 }, name: 'left' },
            { value: CONST.W - CONST.R, axis: 'x', normal: { x: -1, y: 0 }, name: 'right' },
            { value: CONST.R, axis: 'y', normal: { x: 0, y: 1 }, name: 'top' },
            { value: CONST.H - CONST.R, axis: 'y', normal: { x: 0, y: -1 }, name: 'bottom' },
        ];

        bounds.forEach((bound) => {
            const dir = bound.axis === 'x' ? dx : dy;
            if (Math.abs(dir) < 1e-6) return;
            const origin = bound.axis === 'x' ? cue.x : cue.y;
            const t = (bound.value - origin) / dir;
            if (t <= 0.001 || t >= cushionT) return;
            const other = bound.axis === 'x' ? cue.y + dy * t : cue.x + dx * t;
            if (other < CONST.R || other > (bound.axis === 'x' ? CONST.H - CONST.R : CONST.W - CONST.R)) {
                return;
            }
            cushionT = t;
            cushion = bound;
        });

        if (cushion && cushionT < bestT) {
            const end = { x: cue.x + dx * cushionT, y: cue.y + dy * cushionT };
            const dot = dx * cushion.normal.x + dy * cushion.normal.y;
            const rx = dx - 2 * dot * cushion.normal.x;
            const ry = dy - 2 * dot * cushion.normal.y;
            return {
                end,
                hitBall: null,
                ghost: null,
                cushion,
                reflection: { x: rx, y: ry },
                distance: cushionT,
            };
        }

        const end = { x: cue.x + dx * bestT, y: cue.y + dy * bestT };
        if (!hitBall) {
            return { end, hitBall: null, ghost: null, cushion: null, reflection: null, distance: bestT };
        }

        const objectDir = {
            x: hitBall.x - end.x,
            y: hitBall.y - end.y,
        };
        const objectLen = Math.hypot(objectDir.x, objectDir.y) || 1;
        objectDir.x /= objectLen;
        objectDir.y /= objectLen;

        return {
            end,
            hitBall,
            ghost: end,
            objectDir,
            cushion: null,
            reflection: null,
            distance: bestT,
        };
    }

    global.BilardoPhysics = {
        CONST,
        World,
        createInitialState,
        cloneState,
        predictShot,
        initialBalls,
        makeBall,
        RACK_ROW,
        BALL_COLORS,
    };
})(window);
