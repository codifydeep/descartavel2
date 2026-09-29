"use strict";

function scoreLabel(points) {
  if (!Number.isFinite(points) || points < 0) {
    throw new RangeError("points must be a nonnegative finite number");
  }
  return points < 10 ? "novice" : "experienced";
}

module.exports = { scoreLabel };
