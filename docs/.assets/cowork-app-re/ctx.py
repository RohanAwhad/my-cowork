import sys, re
path = "/tmp/claude-asar/app/.vite/build/index.js"
src = open(path, encoding="utf-8", errors="replace").read()
for pat in sys.argv[1:]:
    print("="*100)
    print("PATTERN:", pat)
    for m in re.finditer(re.escape(pat) if not pat.startswith("rx:") else pat[3:], src):
        s = max(0, m.start()-300); e = min(len(src), m.end()+300)
        print("---", m.start())
        print(src[s:e])
