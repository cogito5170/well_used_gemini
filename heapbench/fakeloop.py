"""Fake Gemini API that drives a long tool-calling session.
Each streamGenerateContent request = one model turn. Turn i returns a functionCall to TOOL with varying args,
until TURNS turns, then a final text. Logs: turn index, time, request body size, tool result chars seen."""
import json, sys, time, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
PORT, LOG = int(sys.argv[1]), sys.argv[2]
TURNS = int(os.environ.get("TURNS", "200"))
MODE = os.environ.get("MODE", "tool")          # tool | text
TOOL = os.environ.get("TOOL", "")
ARGS = json.loads(os.environ.get("ARGS_LIST", "[]"))
state = {"n": 0}
def log(d):
    with open(LOG, "a") as f: f.write(json.dumps(d) + "\n")
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json"):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self): self.send(200, json.dumps({"models": []}))
    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if "countTokens" in self.path: return self.send(200, json.dumps({"totalTokens": len(raw)//4}))
        body = json.loads(raw or b"{}")
        if "streamGenerateContent" not in self.path:      # utility calls (next speaker, etc.)
            log({"kind": "util", "path": self.path.split("?")[0], "t": time.time(), "bytes": len(raw)})
            return self.send(200, json.dumps({"candidates": [{"content": {"role": "model", "parts": [{"text": "{\"next_speaker\": \"user\", \"reasoning\": \"done\"}"}]}, "finishReason": "STOP"}]}))
        contents = body.get("contents") or []
        last = contents[-1] if contents else {}
        fr = [p for p in last.get("parts", []) if "functionResponse" in p]
        rchars = len(json.dumps(fr, ensure_ascii=False)) if fr else 0
        if state["n"] == 0:
            names = [d.get("name") for t in body.get("tools") or [] for d in t.get("functionDeclarations") or []]
            log({"kind": "tools", "names": names})
        i = state["n"]; state["n"] += 1
        if float(os.environ.get("DELAY", "0")) > 0:
            time.sleep(float(os.environ["DELAY"]))
        log({"kind": "turn", "i": i, "t": time.time(), "bytes": len(raw), "contents": len(contents), "result_chars": rchars})
        if MODE == "tool" and i < TURNS:
            args = ARGS[i % len(ARGS)] if ARGS else {}
            part = {"functionCall": {"name": TOOL, "args": args}}
        elif MODE == "text" and i < TURNS:
            part = {"text": "turn %d: " % i + "x" * int(os.environ.get("TEXT_CHARS", "2000"))}
        else:
            part = {"text": "DONE after %d turns" % i}
        resp = {"candidates": [{"content": {"role": "model", "parts": [part]}, "finishReason": "STOP"}], "modelVersion": "gemini-3-flash-preview",
                "usageMetadata": {"promptTokenCount": len(raw)//4, "candidatesTokenCount": 10, "totalTokenCount": len(raw)//4 + 10}}
        self.send(200, "data: " + json.dumps(resp) + "\n\n", "text/event-stream")
ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
