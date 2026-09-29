"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const { tierProgressPercent } = require("../score");

test("tierProgressPercent reports progress within the current tier", () => {
  assert.equal(tierProgressPercent(0), 0);
  assert.equal(tierProgressPercent(25), 50);
  assert.equal(tierProgressPercent(49), 98);
  assert.equal(tierProgressPercent(50), 0);
  assert.equal(tierProgressPercent(75), 50);
  assert.equal(tierProgressPercent(99), 98);
});

test("tierProgressPercent returns 100 at gold", () => {
  assert.equal(tierProgressPercent(100), 100);
  assert.equal(tierProgressPercent(150), 100);
});

test("tierProgressPercent rejects negative points", () => {
  assert.throws(() => tierProgressPercent(-1), RangeError);
});

test("tierProgressPercent rejects NaN", () => {
  assert.throws(() => tierProgressPercent(NaN), RangeError);
});

test("tierProgressPercent rejects infinite points", () => {
  assert.throws(() => tierProgressPercent(Infinity), RangeError);
  assert.throws(() => tierProgressPercent(-Infinity), RangeError);
});
