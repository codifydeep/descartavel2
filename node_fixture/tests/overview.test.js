"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { scoreOverview, scoreSummary, tierProgressPercent } = require("../score");

test("scoreOverview composes a bronze overview", () => {
  assert.deepEqual(scoreOverview(49), {
    tier: "bronze",
    pointsToNextTier: 1,
    tierProgressPercent: 98,
  });
});

test("scoreOverview composes the silver boundary", () => {
  assert.deepEqual(scoreOverview(50), {
    tier: "silver",
    pointsToNextTier: 50,
    tierProgressPercent: 0,
  });
});

test("scoreOverview composes a silver overview", () => {
  assert.deepEqual(scoreOverview(75), {
    tier: "silver",
    pointsToNextTier: 25,
    tierProgressPercent: 50,
  });
});

test("scoreOverview composes a gold overview", () => {
  assert.deepEqual(scoreOverview(100), {
    tier: "gold",
    pointsToNextTier: 0,
    tierProgressPercent: 100,
  });
});

test("scoreOverview rejects negative points", () => {
  assert.throws(() => scoreOverview(-1), RangeError);
});

test("scoreOverview rejects NaN", () => {
  assert.throws(() => scoreOverview(NaN), RangeError);
});

test("scoreOverview rejects infinite points", () => {
  assert.throws(() => scoreOverview(Infinity), RangeError);
  assert.throws(() => scoreOverview(-Infinity), RangeError);
});

test("scoreOverview composes the existing summary and percent functions", () => {
  for (const points of [0, 25, 49, 50, 75, 99, 100, 150]) {
    const overview = scoreOverview(points);
    const summary = scoreSummary(points);
    assert.equal(overview.tier, summary.tier);
    assert.equal(overview.pointsToNextTier, summary.pointsToNextTier);
    assert.equal(overview.tierProgressPercent, tierProgressPercent(points));
    assert.deepEqual(overview, {
      tier: summary.tier,
      pointsToNextTier: summary.pointsToNextTier,
      tierProgressPercent: tierProgressPercent(points),
    });
  }
});