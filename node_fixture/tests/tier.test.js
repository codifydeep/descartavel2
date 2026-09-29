"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { tierForScore } = require("../score");

test("tierForScore identifies bronze", () => {
  assert.equal(tierForScore(0), "bronze");
  assert.equal(tierForScore(49), "bronze");
});

test("tierForScore identifies silver", () => {
  assert.equal(tierForScore(50), "silver");
  assert.equal(tierForScore(99), "silver");
});

test("tierForScore identifies gold", () => {
  assert.equal(tierForScore(100), "gold");
});

test("tierForScore rejects negative points", () => {
  assert.throws(() => tierForScore(-1), RangeError);
});

test("tierForScore rejects NaN", () => {
  assert.throws(() => tierForScore(NaN), RangeError);
});

test("tierForScore rejects infinite points", () => {
  assert.throws(() => tierForScore(Infinity), RangeError);
  assert.throws(() => tierForScore(-Infinity), RangeError);
});
