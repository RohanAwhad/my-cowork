import sys, re

PATH = "/tmp/claude-asar/app/.vite/build/index.js"
data = open(PATH, encoding="utf-8", errors="replace").read()

def pretty(s, width=110):
    # split minified code on statement/arg boundaries for readability
    s = re.sub(r";", ";\n", s)
    s = re.sub(r"\{", "{\n", s)
    s = re.sub(r"\}", "\n}", s)
    out = []
    for line in s.split("\n"):
        while len(line) > width:
            idx = max(line.rfind(",", 0, width), line.rfind(" ", 0, width))
            if idx <= 0:
                idx = width
            out.append(line[:idx])
            line = line[idx:].lstrip(" ,")
        out.append(line)
    return "\n".join(out)

def show(off, ctx=400, label=None):
    lo = max(0, off - ctx)
    hi = min(len(data), off + ctx)
    print("=" * 100)
    print(f"OFFSET {off}  (ctx {lo}..{hi}, {hi-lo} chars)")
    if label:
        print(f"LABEL: {label}")
    print("-" * 100)
    print(pretty(data[lo:hi]))

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    ctx = 400
    if "-c" in sys.argv:
        ctx = int(sys.argv[sys.argv.index("-c") + 1])
    for a in args:
        if ":" in a and a.split(":")[0].isdigit():
            off, ctx2 = map(int, a.split(":"))
            show(off, ctx2)
        else:
            show(int(a), ctx)
