// Static server rooted at the repo top so /ui and /video are both
// reachable (the ui/serve.mjs roots at ui/ only). Zero dependencies.
//   node video/serve.mjs [port]
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));
const port = Number(process.argv[2] ?? 8451);
const types = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json",
  ".svg": "image/svg+xml",
};

createServer(async (req, res) => {
  try {
    const path = decodeURIComponent(new URL(req.url, "http://x").pathname);
    const rel = normalize(path === "/" ? "ui/index.html" : path.slice(1));
    if (rel.startsWith("..")) throw new Error("forbidden");
    const body = await readFile(join(root, rel));
    res.writeHead(200, { "content-type": types[extname(rel)] ?? "application/octet-stream" });
    res.end(body);
  } catch {
    res.writeHead(404);
    res.end("not found");
  }
}).listen(port, "127.0.0.1", () => {
  console.log(`capture server → http://localhost:${port}`);
});
