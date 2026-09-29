"use strict";

const http = require("node:http");
const score = require("./score");

http.createServer((request, response) => {
  const url = new URL(request.url, "http://127.0.0.1");
  let body;
  try {
    if (url.pathname === "/health") {
      body = { status: "ok" };
    } else if (url.pathname === "/label" || url.pathname === "/tier") {
      const raw = url.searchParams.get("points");
      if (raw === null || raw.trim() === "") throw new RangeError("missing points");
      const points = Number(raw);
      const operation = url.pathname === "/label" ? score.scoreLabel : score.tierForScore;
      if (typeof operation !== "function") {
        response.writeHead(404).end();
        return;
      }
      body = { result: operation(points) };
    } else {
      response.writeHead(404).end();
      return;
    }
  } catch (error) {
    if (error instanceof RangeError || error instanceof TypeError) {
      response.writeHead(400).end();
      return;
    }
    throw error;
  }
  const bytes = Buffer.from(JSON.stringify({ ...body, source_sha: process.env.SOURCE_SHA }));
  response.writeHead(200, { "content-type": "application/json", "content-length": bytes.length });
  response.end(bytes);
}).listen(8080, "0.0.0.0");
