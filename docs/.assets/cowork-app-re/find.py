import sys, re
path = "/tmp/claude-asar/app/.vite/build/index.js"
src = open(path, encoding="utf-8", errors="replace").read()
pat = sys.argv[1]
matches = [m.start() for m in re.finditer(pat, src)]
print(f"{pat}: {len(matches)} matches")
for i in matches[:int(sys.argv[2]) if len(sys.argv)>2 else 10]:
    print("---", i)
    print(src[max(0,i-250):i+250])
    print()
