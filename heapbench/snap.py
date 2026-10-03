"""Heap snapshot: how much is held by tool-result strings, how many copies, and who retains them (S2)."""
import json, sys
from collections import Counter, defaultdict
snap = json.load(open(sys.argv[1]))
MARK = sys.argv[2] if len(sys.argv) > 2 else "신뢰 안 함"
meta = snap["snapshot"]["meta"]; nf = meta["node_fields"]; ef = meta["edge_fields"]
ntypes = meta["node_types"][0]; etypes = meta["edge_types"][0]
N, E, S = snap["nodes"], snap["edges"], snap["strings"]
NL, EL = len(nf), len(ef)
i_type, i_name, i_id, i_size, i_edges = nf.index("type"), nf.index("name"), nf.index("id"), nf.index("self_size"), nf.index("edge_count")
e_type, e_name, e_to = ef.index("type"), ef.index("name_or_index"), ef.index("to_node")
n = len(N) // NL
first_edge = [0] * (n + 1)
for k in range(n):
    first_edge[k + 1] = first_edge[k] + N[k * NL + i_edges] * EL
rev = defaultdict(list)                       # node -> [(retainer node, edge label)]
for k in range(n):
    for e in range(first_edge[k], first_edge[k + 1], EL):
        to = E[e + e_to] // NL
        et = etypes[E[e + e_type]]
        if et == "weak":
            continue
        lab = S[E[e + e_name]] if et in ("property", "internal", "shortcut", "context") else f"[{E[e + e_name]}]"
        rev[to].append((k, lab))
def tname(k): return ntypes[N[k * NL + i_type]]
def name(k): return S[N[k * NL + i_name]]
total = sum(N[k * NL + i_size] for k in range(n))
# strings that contain a tool result (our header) -- count and bytes, group by first 60 chars
hits = [k for k in range(n) if tname(k) in ("string", "concatenated string", "sliced string") and MARK in name(k)]
by_head = defaultdict(list)
for k in hits:
    by_head[name(k)[:80]].append(k)
held = sum(N[k * NL + i_size] for k in hits)
print(f"heap self size {total/2**20:.1f} MB · strings containing the tool-result mark: {len(hits)} · {held/2**20:.1f} MB")
copies = Counter(len(v) for v in by_head.values())
print(f"distinct results {len(by_head)} · copies per result: {dict(sorted(copies.items()))}")
# retaining paths: for the copies of one result, walk up retainers (prefer property edges) to a named owner
def path(k, depth=14):
    out, seen = [], {k}
    for _ in range(depth):
        rs = [r for r in rev.get(k, []) if r[0] not in seen]
        if not rs:
            break
        r = sorted(rs, key=lambda x: (x[1].startswith("["), tname(x[0]) in ("hidden", "code", "synthetic")))[0]
        out.append(f"{tname(r[0])}:{name(r[0])[:40]}.{r[1][:40]}")
        seen.add(r[0]); k = r[0]
        if tname(k) == "synthetic":
            break
    return out
sample = max(by_head.values(), key=len)
for k in sample[:12]:
    print(f"--- copy ({tname(k)}, {N[k * NL + i_size]} B)")
    for step in path(k):
        print("   <-", step)
# top constructors by self size
agg = Counter()
for k in range(n):
    agg[(tname(k), name(k)[:50] if tname(k) in ("object", "closure") else tname(k))] += N[k * NL + i_size]
print("top self size:")
for (t, nm), sz in agg.most_common(15):
    print(f"   {sz/2**20:7.1f} MB  {t}  {nm}")
