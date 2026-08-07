import sys
path = "/tmp/claude-asar/app/.vite/build/index.js"
src = open(path, encoding="utf-8", errors="replace").read()
pat = sys.argv[1]; before = int(sys.argv[2]) if len(sys.argv)>2 else 300
after = int(sys.argv[3]) if len(sys.argv)>3 else 6000
i = src.find(pat)
print(src[max(0,i-before):i+after])
