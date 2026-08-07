import re, sys, json

PATH = "/tmp/claude-asar/app/.vite/build/index.js"
data = open(PATH, encoding="utf-8", errors="replace").read()
N = len(data)
print(f"file length: {N} chars")

terms = sys.argv[1:]
if not terms:
    terms = ["Cowork","cowork","local-agent","LocalAgent","lam_","vm_","VM","claude-swift",
             "SwiftVM","mountPath","installSdk","sessionStorageDir","getOutputsDir","knowledgeBase",
             "mcp-registry","mcp__cowork","dxt","MCPB","fileWatcher","FileSystemWatcher","outputs",
             "userSelectedFolders","sharedCwdPath","vmProcessName","sessionId","teleported",
             "permission","canUseTool","hooks","settings"]

for t in terms:
    occ = []
    start = 0
    while True:
        i = data.find(t, start)
        if i == -1: break
        occ.append(i)
        start = i + 1
    print(f"{t!r}: {len(occ)} occurrences")
