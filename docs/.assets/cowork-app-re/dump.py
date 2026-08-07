import sys, json

PATH = "/tmp/claude-asar/app/.vite/build/index.js"
data = open(PATH, encoding="utf-8", errors="replace").read()
CTX = 300

terms = ["Cowork","cowork","local-agent","LocalAgent","lam_","claude-swift","SwiftVM","mcp__cowork","teleported"]
out = {}
for t in terms:
    occ = []
    start = 0
    while True:
        i = data.find(t, start)
        if i == -1: break
        occ.append(i)
        start = i + 1
    out[t] = occ

print(json.dumps(out))
