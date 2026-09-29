"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { scoreSummary, tierForScore, pointsToNextTier } = require("../score");

test("scoreSummary summarizes a bronze score", () => {
  assert.deepEqual(scoreSummary(49), { tier: "bronze", pointsToNextTier: 1 });
});

test("scoreSummary summarizes the silver boundary", () => {
  assert.deepEqual(scoreSummary(50), { tier: "silver", pointsToNextTier: 50 });
});

test("scoreSummary summarizes a silver score", () => {
  assert.deepEqual(scoreSummary(99), { tier: "silver", pointsToNextTier: 1 });
});

test("scoreSummary summarizes a gold score", () => {
  assert.deepEqual(scoreSummary(100), { tier: "gold", pointsToNextTier: 0 });
});

test("scoreSummary rejects negative points", () => {
  assert.throws(() => scoreSummary(-1), RangeError);
});

test("scoreSummary rejects NaN", () => {
  assert.throws(() => scoreSummary(NaN), RangeError);
});

test("scoreSummary rejects infinite points", () => {
  assert.throws(() => scoreSummary(Infinity), RangeError);
  assert.throws(() => scoreSummary(-Infinity), RangeError);
});

test("scoreSummary composes the existing tier and progress functions", () => {
  for (const points of [0, 25, 49, 50, 75, 99, 100, 150]) {
    const summary = scoreSummary(points);
    assert.equal(summary.tier, tierForScore(points));
    assert.equal(summary.pointsToNextTier, pointsToNextTier(points));
    assert.deepEqual(summary, {
      tier: tierForScore(points),
      pointsToNextTier: pointsToNextTier(points),
    });
  }
});
