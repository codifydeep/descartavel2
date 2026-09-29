"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { scoreLabel } = require("../score");

test("scoreLabel identifies a novice", () => {
  assert.equal(scoreLabel(0), "novice");
  assert.equal(scoreLabel(9), "novice");
});

test("scoreLabel identifies an experienced player", () => {
  assert.equal(scoreLabel(10), "experienced");
});

test("scoreLabel rejects invalid points", () => {
  assert.throws(() => scoreLabel(-1), RangeError);
  assert.throws(() => scoreLabel(Infinity), RangeError);
});
