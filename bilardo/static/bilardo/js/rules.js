/* ==========================================================================
   Bilardo kuralları — 3 Bant, 8 Top, 9 Top ve Düz Bilardo
   ========================================================================== */
(function (global) {
    'use strict';

    const P = global.BilardoPhysics;
    const CONST = P.CONST;

    function clone(value) {
        return JSON.parse(JSON.stringify(value));
    }

    function groupOf(ball) {
        if (!ball || ball.number === 0 || ball.number === 8) return null;
        return ball.number < 8 ? 'solids' : 'stripes';
    }

    function otherGroup(group) {
        return group === 'solids' ? 'stripes' : 'solids';
    }

    function remainingGroup(balls, group) {
        if (!group) return 0;
        return balls.filter((ball) => !ball.pocketed && groupOf(ball) === group).length;
    }

    function lowestBall(balls) {
        const active = balls.filter((ball) => !ball.pocketed && ball.id !== 0);
        if (!active.length) return null;
        return active.reduce((lowest, ball) => (ball.number < lowest.number ? ball : lowest), active[0]);
    }

    function freeSpot(balls, preferredX, preferredY, ignoreId) {
        const x0 = preferredX === undefined ? CONST.FOOT_X : preferredX;
        const y0 = preferredY === undefined ? CONST.CENTER_Y : preferredY;
        const candidates = [{ x: x0, y: y0 }];
        for (let step = 1; step <= 30; step += 1) {
            candidates.push({ x: x0 - step * CONST.RACK_SPACING, y: y0 });
            candidates.push({ x: x0 + step * CONST.RACK_SPACING, y: y0 });
            candidates.push({ x: x0, y: y0 + step * CONST.RACK_SPACING });
            candidates.push({ x: x0, y: y0 - step * CONST.RACK_SPACING });
            candidates.push({ x: x0 - step * CONST.RACK_SPACING, y: y0 + step * CONST.RACK_SPACING });
            candidates.push({ x: x0 + step * CONST.RACK_SPACING, y: y0 - step * CONST.RACK_SPACING });
        }
        for (let i = 0; i < candidates.length; i += 1) {
            const candidate = candidates[i];
            const x = Math.min(Math.max(candidate.x, CONST.R), CONST.W - CONST.R);
            const y = Math.min(Math.max(candidate.y, CONST.R), CONST.H - CONST.R);
            let free = true;
            for (let j = 0; j < balls.length; j += 1) {
                const ball = balls[j];
                if (ball.pocketed || ball.id === ignoreId) continue;
                const dx = ball.x - x;
                const dy = ball.y - y;
                if (dx * dx + dy * dy < (CONST.R * 2.08) * (CONST.R * 2.08)) {
                    free = false;
                    break;
                }
            }
            if (free) return { x, y };
        }
        return { x: x0, y: y0 };
    }

    function respotBall(state, ballId) {
        const ball = state.balls.find((item) => item.id === ballId);
        if (!ball) return;
        const spot = freeSpot(state.balls, CONST.FOOT_X, CONST.CENTER_Y, ballId);
        ball.x = spot.x;
        ball.y = spot.y;
        ball.pocketed = false;
    }

    function resetCueBall(state) {
        const cue = state.balls.find((ball) => ball.id === 0);
        if (!cue) return;
        const spot = freeSpot(state.balls, CONST.HEAD_X, CONST.CENTER_Y, 0);
        cue.x = spot.x;
        cue.y = spot.y;
        cue.pocketed = false;
    }

    function rerackStraight(state) {
        const objects = state.balls.filter((ball) => ball.id !== 0);
        if (!objects.length || objects.some((ball) => !ball.pocketed)) return false;

        const order = [1, 9, 2, 3, 8, 10, 11, 4, 12, 5, 6, 13, 7, 14, 15];
        const rowGap = CONST.RACK_SPACING * Math.sqrt(3) / 2;
        let index = 0;
        for (let row = 0; row < 5; row += 1) {
            const count = row + 1;
            const x = CONST.FOOT_X + row * rowGap;
            for (let slot = 0; slot < count; slot += 1) {
                const ball = state.balls.find((item) => item.id === order[index]);
                index += 1;
                if (!ball) continue;
                ball.x = x;
                ball.y = CONST.CENTER_Y + (slot - (count - 1) / 2) * CONST.RACK_SPACING;
                ball.pocketed = false;
            }
        }

        const cue = state.balls.find((ball) => ball.id === 0);
        if (cue && !cue.pocketed) {
            const overlaps = state.balls.some((ball) => {
                if (ball.id === 0 || ball.pocketed) return false;
                return Math.hypot(ball.x - cue.x, ball.y - cue.y) < CONST.R * 2.05;
            });
            if (overlaps) {
                const spot = freeSpot(state.balls, CONST.HEAD_X, CONST.CENTER_Y, 0);
                cue.x = spot.x;
                cue.y = spot.y;
            }
        }
        return true;
    }

    function uniquePocketed(events) {
        const seen = new Set();
        const ids = [];
        (events.pockets || []).forEach((event) => {
            if (!seen.has(event.ballId)) {
                seen.add(event.ballId);
                ids.push(event.ballId);
            }
        });
        return ids;
    }

    function finishState(state, shooterSeat, result) {
        state.break = false;
        state.shot_count = (state.shot_count || 0) + 1;
        state.message = result.message;
        state.last_shot = {
            seat: shooterSeat,
            message: result.message,
            foul: !!result.foul,
            pocketed: result.pocketed || [],
        };
        if (!Array.isArray(state.history)) state.history = [];
        state.history.push(state.last_shot);
        if (state.history.length > 30) state.history = state.history.slice(-30);
        if (result.winner === 0 || result.winner === 1) {
            state.winner = result.winner;
            state.turn = result.winner;
            state.scores[result.winner] = Math.max(state.scores[result.winner] || 0, state.target || 1);
        }
        return state;
    }

    function evaluateThreeCushion(state, world, shooterSeat) {
        const next = clone(state);
        next.balls = world.balls.map((ball) => ({
            id: ball.id,
            number: ball.number,
            x: ball.x,
            y: ball.y,
            color: ball.color,
            stripe: ball.stripe,
            type: ball.type,
            pocketed: ball.pocketed,
        }));

        const events = world.events;
        const hits = [];
        (events.cueObjectHits || []).forEach((hit) => {
            if (!hits.some((item) => item.objectId === hit.objectId)) {
                hits.push(hit);
            }
        });

        let valid = false;
        let cushionsBeforeSecond = 0;
        if (hits.length >= 2) {
            const secondTime = hits[1].t;
            cushionsBeforeSecond = (events.cushions || []).filter(
                (cushion) => cushion.ballId === 0 && cushion.t < secondTime
            ).length;
            valid = cushionsBeforeSecond >= 3;
        }

        const result = {
            foul: !valid,
            pocketed: [],
            continueTurn: valid,
            winner: null,
            message: '',
        };

        if (valid) {
            next.scores[shooterSeat] = (next.scores[shooterSeat] || 0) + 1;
            next.turn = shooterSeat;
            result.message = 'Harika! 3 bant tamamlandı, +1 sayı.';
            if (next.scores[shooterSeat] >= (next.target || 1)) {
                result.winner = shooterSeat;
                result.message = 'Hedef sayıya ulaştın. Oyunu kazandın!';
            }
        } else {
            next.turn = 1 - shooterSeat;
            const touched = hits.length;
            if (touched < 2) {
                result.message = 'Geçersiz vuruş: iki hedef topa da dokunmalısın.';
            } else {
                result.message = 'Geçersiz vuruş: ikinci topa dokunmadan önce 3 bant gerekli.';
            }
        }

        return finishState(next, shooterSeat, result);
    }

    function evaluateEightBall(state, world, shooterSeat) {
        const next = clone(state);
        next.balls = world.balls.map((ball) => ({
            id: ball.id,
            number: ball.number,
            x: ball.x,
            y: ball.y,
            color: ball.color,
            stripe: ball.stripe,
            type: ball.type,
            pocketed: ball.pocketed,
        }));

        const events = world.events;
        const pocketed = uniquePocketed(events);
        const cuePocketed = pocketed.includes(0);
        const objectPocketed = pocketed.filter((id) => id !== 0);
        const firstHit = events.firstObjectHit;
        const firstTime = events.firstObjectHitTime;
        const anyRailAfter = (events.cushions || []).some(
            (cushion) => firstTime !== null && cushion.t >= firstTime - 0.001
        ) || objectPocketed.length > 0;

        const isBreak = !!state.break;
        const myGroup = state.groups ? state.groups[shooterSeat] : null;
        const oppSeat = 1 - shooterSeat;
        const openTable = !state.groups || (!state.groups[0] && !state.groups[1]);
        const firstBall = firstHit !== null
            ? state.balls.find((ball) => ball.id === firstHit)
            : null;
        const ownRemainingBefore = myGroup ? remainingGroup(state.balls, myGroup) : 0;
        const eightPocketed = objectPocketed.includes(8);

        let foul = false;
        let reason = '';

        if (firstHit === null) {
            foul = true;
            reason = 'Hiçbir topa temas etmedin.';
        } else if (firstHit === 8) {
            if (isBreak) {
                foul = true;
                reason = 'İlk vuruşta 8 topa ilk temas edilemez.';
            } else if (!myGroup || ownRemainingBefore > 0) {
                foul = true;
                reason = '8 topa erken temas ettin.';
            }
        } else if (openTable) {
            // Açık masada 8 dışında herhangi bir topa ilk temas serbest.
        } else if (myGroup && groupOf(firstBall) !== myGroup) {
            foul = true;
            reason = 'Önce kendi grubundan bir topa temas etmelisin.';
        }

        if (cuePocketed) {
            foul = true;
            reason = reason || 'İsteka topu deliğe düştü.';
        }

        if (firstHit !== null && !anyRailAfter) {
            foul = true;
            reason = reason || 'Temas sonrası hiçbir top banda çarpmadı.';
        }

        const eightWasLegal = !isBreak
            && myGroup
            && ownRemainingBefore === 0
            && firstHit === 8
            && !cuePocketed;

        let winner = null;

        if (eightPocketed) {
            if (isBreak) {
                respotBall(next, 8);
                if (cuePocketed) {
                    foul = true;
                    reason = reason || 'İsteka topu deliğe düştü.';
                }
            } else if (eightWasLegal) {
                winner = shooterSeat;
            } else {
                winner = oppSeat;
                reason = '8 top erken düştü. Rakibin kazandı.';
            }
        }

        if (winner !== null) {
            next.scores[winner] = 1;
            next.turn = winner;
            const result = {
                foul: false,
                pocketed: objectPocketed,
                continueTurn: false,
                winner,
                message: winner === shooterSeat
                    ? '8 topu deliğe soktun. Oyunu kazandın!'
                    : reason || 'Rakibin kazandı.',
            };
            return finishState(next, shooterSeat, result);
        }

        if (foul) {
            next.turn = oppSeat;
            next.ball_in_hand = true;
            resetCueBall(next);
            return finishState(next, shooterSeat, {
                foul: true,
                pocketed: objectPocketed,
                continueTurn: false,
                winner: null,
                message: 'Faul: ' + (reason || 'Sıra rakibe geçti.'),
            });
        }

        // Grup ataması: açık masada ilk deliğe giren topun grubu oyuncunun olur.
        if (!isBreak && openTable) {
            const firstPocketedObject = (events.pockets || [])
                .map((event) => state.balls.find((ball) => ball.id === event.ballId))
                .find((ball) => ball && ball.id !== 0 && ball.id !== 8);
            if (firstPocketedObject) {
                const assigned = groupOf(firstPocketedObject);
                next.groups = [null, null];
                next.groups[shooterSeat] = assigned;
                next.groups[oppSeat] = otherGroup(assigned);
            }
        }

        const activeGroup = next.groups ? next.groups[shooterSeat] : null;
        let scoredOwn = false;
        if (activeGroup) {
            scoredOwn = objectPocketed.some((id) => {
                const ball = next.balls.find((item) => item.id === id);
                return groupOf(ball) === activeGroup;
            });
        } else if (!isBreak) {
            scoredOwn = objectPocketed.some((id) => id !== 8);
        } else {
            scoredOwn = objectPocketed.some((id) => id !== 8);
        }

        next.ball_in_hand = false;
        if (scoredOwn) {
            next.turn = shooterSeat;
            return finishState(next, shooterSeat, {
                foul: false,
                pocketed: objectPocketed,
                continueTurn: true,
                winner: null,
                message: objectPocketed.length > 1
                    ? 'Topları deliğe soktun. Sıra sende devam ediyor.'
                    : 'Güzel vuruş! Sıra sende.',
            });
        }

        next.turn = oppSeat;
        return finishState(next, shooterSeat, {
            foul: false,
            pocketed: objectPocketed,
            continueTurn: false,
            winner: null,
            message: objectPocketed.length
                ? 'Top düştü ama sıra rakibe geçti.'
                : 'Top düşmedi. Sıra rakibe geçti.',
        });
    }

    function evaluateNineBall(state, world, shooterSeat) {
        const next = clone(state);
        next.balls = world.balls.map((ball) => ({
            id: ball.id,
            number: ball.number,
            x: ball.x,
            y: ball.y,
            color: ball.color,
            stripe: ball.stripe,
            type: ball.type,
            pocketed: ball.pocketed,
        }));

        const events = world.events;
        const pocketed = uniquePocketed(events);
        const cuePocketed = pocketed.includes(0);
        const objectPocketed = pocketed.filter((id) => id !== 0);
        const firstHit = events.firstObjectHit;
        const firstTime = events.firstObjectHitTime;
        const anyRailAfter = (events.cushions || []).some(
            (cushion) => firstTime !== null && cushion.t >= firstTime - 0.001
        ) || objectPocketed.length > 0;

        const lowest = lowestBall(state.balls);
        const firstBall = firstHit !== null
            ? state.balls.find((ball) => ball.id === firstHit)
            : null;
        const oppSeat = 1 - shooterSeat;
        const ninePocketed = objectPocketed.includes(9);

        let foul = false;
        let reason = '';

        if (firstHit === null) {
            foul = true;
            reason = 'Hiçbir topa temas etmedin.';
        } else if (!lowest || firstBall.number !== lowest.number) {
            foul = true;
            reason = lowest
                ? 'Önce ' + lowest.number + ' numaralı topa temas etmeliydin.'
                : 'Masadaki en küçük topa temas etmelisin.';
        }
        if (cuePocketed) {
            foul = true;
            reason = reason || 'İsteka topu deliğe düştü.';
        }
        if (firstHit !== null && !anyRailAfter) {
            foul = true;
            reason = reason || 'Temas sonrası top banda çarpmadı.';
        }

        if (ninePocketed) {
            if (foul) {
                respotBall(next, 9);
                next.turn = oppSeat;
                next.ball_in_hand = true;
                resetCueBall(next);
                return finishState(next, shooterSeat, {
                    foul: true,
                    pocketed: objectPocketed,
                    continueTurn: false,
                    winner: null,
                    message: 'Faul: 9 top yeniden yerleştirildi. Sıra rakibe geçti.',
                });
            }
            next.scores[shooterSeat] = 1;
            next.turn = shooterSeat;
            return finishState(next, shooterSeat, {
                foul: false,
                pocketed: objectPocketed,
                continueTurn: false,
                winner: shooterSeat,
                message: '9 topu deliğe soktun. Oyunu kazandın!',
            });
        }

        if (foul) {
            next.turn = oppSeat;
            next.ball_in_hand = true;
            resetCueBall(next);
            return finishState(next, shooterSeat, {
                foul: true,
                pocketed: objectPocketed,
                continueTurn: false,
                winner: null,
                message: 'Faul: ' + (reason || 'Sıra rakibe geçti.'),
            });
        }

        next.ball_in_hand = false;
        if (objectPocketed.length > 0) {
            next.turn = shooterSeat;
            return finishState(next, shooterSeat, {
                foul: false,
                pocketed: objectPocketed,
                continueTurn: true,
                winner: null,
                message: 'Top deliğe girdi. Sıra sende.',
            });
        }

        next.turn = oppSeat;
        return finishState(next, shooterSeat, {
            foul: false,
            pocketed: [],
            continueTurn: false,
            winner: null,
            message: 'Top düşmedi. Sıra rakibe geçti.',
        });
    }

    function evaluateStraight(state, world, shooterSeat) {
        const next = clone(state);
        next.balls = world.balls.map((ball) => ({
            id: ball.id,
            number: ball.number,
            x: ball.x,
            y: ball.y,
            color: ball.color,
            stripe: ball.stripe,
            type: ball.type,
            pocketed: ball.pocketed,
        }));

        const events = world.events;
        const pocketed = uniquePocketed(events);
        const cuePocketed = pocketed.includes(0);
        const objectPocketed = pocketed.filter((id) => id !== 0);
        const firstHit = events.firstObjectHit;
        const firstTime = events.firstObjectHitTime;
        const anyRailAfter = (events.cushions || []).some(
            (cushion) => firstTime !== null && cushion.t >= firstTime - 0.001
        ) || objectPocketed.length > 0;
        const oppSeat = 1 - shooterSeat;

        let foul = false;
        let reason = '';
        if (firstHit === null) {
            foul = true;
            reason = 'Hiçbir topa temas etmedin.';
        }
        if (cuePocketed) {
            foul = true;
            reason = reason || 'İsteka topu deliğe düştü.';
        }
        if (firstHit !== null && !anyRailAfter) {
            foul = true;
            reason = reason || 'Temas sonrası top banda çarpmadı.';
        }

        if (foul) {
            objectPocketed.forEach((id) => respotBall(next, id));
            next.turn = oppSeat;
            next.ball_in_hand = true;
            resetCueBall(next);
            return finishState(next, shooterSeat, {
                foul: true,
                pocketed: objectPocketed,
                continueTurn: false,
                winner: null,
                message: 'Faul: ' + (reason || 'Toplar yeniden yerleştirildi.'),
            });
        }

        const points = objectPocketed.length;
        next.scores[shooterSeat] = (next.scores[shooterSeat] || 0) + points;
        next.ball_in_hand = false;

        if (next.scores[shooterSeat] >= (next.target || 1)) {
            next.turn = shooterSeat;
            return finishState(next, shooterSeat, {
                foul: false,
                pocketed: objectPocketed,
                continueTurn: false,
                winner: shooterSeat,
                message: 'Hedef puana ulaştın. Oyunu kazandın!',
            });
        }

        if (points > 0) {
            next.turn = shooterSeat;
            const reracked = rerackStraight(next);
            return finishState(next, shooterSeat, {
                foul: false,
                pocketed: objectPocketed,
                continueTurn: true,
                winner: null,
                message: reracked
                    ? points + ' top deliğe girdi. +' + points + ' sayı. Masa yeniden dizildi, sıra sende.'
                    : (points > 1
                        ? points + ' top deliğe girdi. +' + points + ' sayı, sıra sende.'
                        : 'Top deliğe girdi. +1 sayı, sıra sende.'),
            });
        }

        next.turn = oppSeat;
        return finishState(next, shooterSeat, {
            foul: false,
            pocketed: [],
            continueTurn: false,
            winner: null,
            message: 'Top düşmedi. Sıra rakibe geçti.',
        });
    }

    function evaluateShot(options) {
        const state = options.state;
        const world = options.world;
        const shooterSeat = options.shooterSeat;
        switch (state.mode) {
            case 'three_cushion':
                return evaluateThreeCushion(state, world, shooterSeat);
            case 'eight_ball':
                return evaluateEightBall(state, world, shooterSeat);
            case 'nine_ball':
                return evaluateNineBall(state, world, shooterSeat);
            case 'straight':
            default:
                return evaluateStraight(state, world, shooterSeat);
        }
    }

    global.BilardoRules = {
        evaluateShot,
        groupOf,
        remainingGroup,
        lowestBall,
        freeSpot,
    };
})(window);
