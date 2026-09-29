"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { pointsToNextTier } = require("../score");

test("pointsToNextTier reports the gap to 50 for bronze scores", () => {
  assert.equal(pointsToNextTier(0), 50);
  assert.equal(pointsToNextTier(49), 1);
});

test("pointsToNextTier reports the gap to 100 for silver scores", () => {
  assert.equal(pointsToNextTier(50), 50);
  assert.equal(pointsToNextTier(99), 1);
});

test("pointsToNextTier returns 0 at gold", () => {
  assert.equal(pointsToNextTier(100), 0);
  assert.equal(pointsToNextTier(150), 0);
});

test("pointsToNextTier rejects negative points", () => {
  assert.throws(() => pointsToNextTier(-1), RangeError);
});

test("pointsToNextTier rejects NaN", () => {
  assert.throws(() => pointsToNextTier(NaN), RangeError);
});

test("pointsToNextTier rejects infinite points", () => {
  assert.throws(() => pointsToNextTier(Infinity), RangeError);
  assert.throws(() => pointsToNextTier(-Infinity), RangeError);
});
