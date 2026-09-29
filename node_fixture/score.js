"use strict";

function scoreLabel(points) {
  if (!Number.isFinite(points) || points < 0) {
    throw new RangeError("points must be a nonnegative finite number");
  }
  return points < 10 ? "novice" : "experienced";
}

function tierForScore(points) {
  if (!Number.isFinite(points) || points < 0) {
    throw new RangeError("points must be a nonnegative finite number");
  }
  if (points >= 100) return "gold";
  return points >= 50 ? "silver" : "bronze";
}

function pointsToNextTier(points) {
  if (!Number.isFinite(points) || points < 0) {
    throw new RangeError("points must be a nonnegative finite number");
  }
  if (points >= 100) return 0;
  return (points >= 50 ? 100 : 50) - points;
}

function tierProgressPercent(points) {
  if (!Number.isFinite(points) || points < 0) {
    throw new RangeError("points must be a nonnegative finite number");
  }
  if (points >= 100) return 100;
  return (points % 50) * 2;
}

function scoreSummary(points) {
  return {
    tier: tierForScore(points),
    pointsToNextTier: pointsToNextTier(points),
  };
}

module.exports = { scoreLabel, tierForScore, pointsToNextTier, tierProgressPercent, scoreSummary };
