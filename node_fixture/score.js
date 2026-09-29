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

module.exports = { scoreLabel, tierForScore };
