import math, statistics, collections
KX, KY = 111.32 * math.cos(math.radians(5.2)), 110.57


def trace(pts):
    P = [(lon * KX, lat * KY) for lat, lon in pts]
    for _ in range(2):
        cx, cy = statistics.median(p[0] for p in P), statistics.median(p[1] for p in P)
        d = sorted(math.hypot(p[0] - cx, p[1] - cy) for p in P)
        lim = max(8.0, 3.5 * d[int(len(d) * .75)])
        P = [p for p in P if math.hypot(p[0] - cx, p[1] - cy) <= lim]
    n = len(P)
    if n < 6:
        return None
    mx, my = sum(p[0] for p in P) / n, sum(p[1] for p in P) / n
    sxx = sum((p[0] - mx) ** 2 for p in P); syy = sum((p[1] - my) ** 2 for p in P)
    sxy = sum((p[0] - mx) * (p[1] - my) for p in P)
    th = .5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(th), math.sin(th)
    T = [((p[0] - mx) * ux + (p[1] - my) * uy, p) for p in P]
    need = 1 if n < 15 else 2
    bins = collections.defaultdict(list)
    for t, p in T:
        bins[math.floor(t / 3.0)].append(p)
    V = []
    for b in sorted(bins):
        if len(bins[b]) >= need:
            V.append((statistics.median(p[0] for p in bins[b]), statistics.median(p[1] for p in bins[b])))
    # keep the longest unbroken run: a gap of more than 12 km means the points are not one line
    runs, cur = [], [V[0]] if V else []
    for a, b in zip(V, V[1:]):
        if math.hypot(b[0] - a[0], b[1] - a[1]) > 12.0:
            runs.append(cur); cur = []
        cur.append(b)
    runs.append(cur)
    V = max(runs, key=len)
    if len(V) < 2:
        return None
    perp = sorted(abs(-(p[0] - mx) * uy + (p[1] - my) * ux) for p in P)
    if perp[int(len(perp) * .75)] > 6.0:   # too scattered to be one corridor
        return None
    if len(V) > 3:  # light smoothing so bin-to-bin scatter does not inflate the length
        V = [V[0]] + [((V[i - 1][0] + 2 * V[i][0] + V[i + 1][0]) / 4, (V[i - 1][1] + 2 * V[i][1] + V[i + 1][1]) / 4)
                      for i in range(1, len(V) - 1)] + [V[-1]]
    km = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(V, V[1:]))
    if km < 1.0:
        return None
    return [[round(v[1] / KY, 4), round(v[0] / KX, 4)] for v in V], round(km, 1)


