import json, sys, bisect
def load(name):
    turns = [json.loads(l) for l in open(f"{name}/api.log") if '"turn"' in l]
    heap = [json.loads(l) for l in open(f"{name}/heap.log")]
    heap = [h for h in heap if "heap" in h]
    from collections import Counter
    main = Counter(h["pid"] for h in heap if h["heap"] > 0).most_common()
    # the CLI relaunches itself: keep the process whose heap is largest (the real session)
    big = max({h["pid"] for h in heap}, key=lambda p: max(x["heap"] for x in heap if x["pid"] == p))
    heap = [h for h in heap if h["pid"] == big]
    ht = [h["t"] for h in heap]
    rows = []
    for tr in turns:
        j = bisect.bisect_left(ht, tr["t"])          # first heap sample at/after this request
        if j < len(heap):
            rows.append((tr["i"], heap[j]["heap"] / 2**20, heap[j]["rss"] / 2**20, tr["bytes"] / 2**10, tr["result_chars"]))
    return rows
def slope(xs, ys):
    n = len(xs); mx, my = sum(xs) / n, sum(ys) / n
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
for name in sys.argv[1:]:
    r = load(name)
    if len(r) < 10:
        print(name, "too few", len(r)); continue
    xs = [a[0] for a in r]; hs = [a[1] for a in r]; req = [a[3] for a in r]
    tail = r[len(r) // 5:]                     # skip warm-up
    s = slope([a[0] for a in tail], [a[1] for a in tail])
    rc = [a[4] for a in r if a[4]]
    print(f"{name}: turns {len(r)} · heap {hs[0]:.0f} -> {hs[-1]:.0f} MB · slope {s*1000:.1f} KB/turn · "
          f"request {req[0]:.0f} -> {req[-1]:.0f} KB · tool result median {sorted(rc)[len(rc)//2] if rc else 0} chars")
    for a in r[::max(1, len(r)//6)]:
        print(f"   turn {a[0]:4d}  heap {a[1]:7.1f} MB  rss {a[2]:7.1f} MB  request {a[3]:8.1f} KB")
