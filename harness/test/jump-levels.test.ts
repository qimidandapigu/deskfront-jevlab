import test from 'node:test';
import assert from 'node:assert/strict';
import { JUMP_LEVELS } from '../src/games/jump/levels.js';
import { actor, progress, replayActions, verifyLevel } from '../src/games/jump/engine.js';

for (const {id, name, level} of JUMP_LEVELS) {
  test(`jump level ${id}: ${name} has a replayable, death-free solution`, () => {
    const result = verifyLevel(level);
    assert.equal(result.verified, true, result.reason);
    assert.ok(result.actions);
    const replay = replayActions(level, actor(level.spawn), progress(), result.actions);
    assert.equal(replay.actor.dead, false);
    assert.equal(replay.progress.won, true);
  });
}
