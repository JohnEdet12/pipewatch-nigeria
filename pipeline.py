"""PipeWatch data pipeline: NOSDRA Oil Spill Monitor feed -> cleaned spills -> data.json for the dashboard.

Steps: download the official bulk feed, keep confirmed/reviewed 2015+ records with plausible Niger Delta
coordinates, remove duplicates, name the line at each spill, snap spills to OpenStreetMap pipeline
segments (<= 5 km, within 3 km) and write one JSON bundle the page loads.
"""
import collections, datetime, gzip, hashlib, json, math, re, sys, urllib.request
from pathlib import Path

import names
import traces

HERE = Path(__file__).resolve().parent
STATIC = HERE / 'static'
FEED_URL = 'https://oilspillmonitor.ng/api/spill-data.php?dataset=nosdra&format=json'
OVERPASS_URL = 'https://overpass-api.de/api/interpreter'
OVERPASS_Q = '[out:json][timeout:180];way["man_made"="pipeline"](4.0,4.5,7.2,9.0);out tags geom;'
UA = 'PipeWatchNigeria/1.0 (pipeline patrol dashboard)'
MIN_YEAR = 2015
BBOX = (3.9, 4.3, 7.3, 9.1)          # lat0, lon0, lat1, lon1: the Niger Delta study area
KX, KY = 111.32 * math.cos(math.radians(5.2)), 110.57
SNAP_KM, SEG_KM = 3.0, 5.0


# ---------------------------------------------------------------- download
def http_get(url, data=None, timeout=180):
    req = urllib.request.Request(url, data=data, headers={'User-Agent': UA, 'Accept': '*/*', 'Accept-Encoding': 'gzip'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    if body[:2] == b'\x1f\x8b':
        body = gzip.decompress(body)
    return body


def fetch_feed():
    rows = json.loads(http_get(FEED_URL).decode('utf8'))
    if not isinstance(rows, list) or len(rows) < 1000:
        raise ValueError('NOSDRA feed returned an unexpected payload')
    return rows


def fetch_osm():
    import urllib.parse
    body = http_get(OVERPASS_URL, data=urllib.parse.urlencode({'data': OVERPASS_Q}).encode())
    d = json.loads(body.decode('utf8'))
    if len(d.get('elements', [])) < 100:
        raise ValueError('Overpass returned too few pipeline ways')
    return d


# ---------------------------------------------------------------- cleaning
def _num(v):
    if v is None:
        return None
    s = str(v).strip().replace(',', '')
    if not s:
        return None
    if s.upper() in ('NIL', 'NILL', 'NONE', 'ZERO'):
        return 0.0
    m = re.match(r'^-?\d+(\.\d+)?', s)
    return float(m.group(0)) if m else None


def _date(v):
    s = str(v or '')[:10]
    try:
        datetime.date.fromisoformat(s)
        return s
    except ValueError:
        return None


def _operator_map():
    m = {}
    for canon, raws in json.loads((STATIC / 'operators.json').read_text(encoding='utf8')).items():
        for raw in raws:
            m[raw.strip().upper()] = canon
    return m


def _state_finder():
    feats = json.loads((STATIC / 'base.json').read_text(encoding='utf8'))['states']['features']
    polys = []
    for f in feats:
        g = f['geometry']
        for rings in ([g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']):
            ring = rings[0]
            xs, ys = [p[0] for p in ring], [p[1] for p in ring]
            polys.append((f['properties']['name'], ring, min(xs), min(ys), max(xs), max(ys)))

    def inside(x, y, ring):
        c = False
        j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi, xj, yj = ring[i][0], ring[i][1], ring[j][0], ring[j][1]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                c = not c
            j = i
        return c

    def find(lat, lon):
        for nm, ring, x0, y0, x1, y1 in polys:
            if x0 <= lon <= x1 and y0 <= lat <= y1 and inside(lon, lat, ring):
                return nm
        best, bn = 1e9, 'Unknown'          # offshore or on a generalised border: nearest state
        for nm, ring, x0, y0, x1, y1 in polys:
            if lon < x0 - 1 or lon > x1 + 1 or lat < y0 - 1 or lat > y1 + 1:
                continue
            d = min((p[0] - lon) ** 2 + (p[1] - lat) ** 2 for p in ring)
            if d < best:
                best, bn = d, nm
        return bn
    return find


def clean(feed):
    """NOSDRA feed rows -> analysis-ready spill dicts (confirmed/reviewed, de-duplicated, plausible coordinates)."""
    opmap, state_of = _operator_map(), _state_finder()
    today = datetime.date.today().isoformat()
    cand = []
    for r in feed:
        d = _date(r.get('incidentdate'))
        if not d or int(d[:4]) < MIN_YEAR or d > today:
            continue
        if (r.get('status') or '').strip().lower() not in ('confirmed', 'reviewed'):
            continue
        lat, lon = _num(r.get('latitude')), _num(r.get('longitude'))
        if lat is None or lon is None or not (BBOX[0] <= lat <= BBOX[2] and BBOX[1] <= lon <= BBOX[3]):
            continue
        raw_op = (r.get('company') or '').strip()
        site = re.sub(r'\s+', ' ', (r.get('sitelocationname') or '').upper()).strip()
        m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(?:''|\"|’’|”|INCH)", site)
        qty = _num(r.get('estimatedquantity'))
        upd = re.findall(r'\d{4}-\d{2}-\d{2}', str(r.get('lastupdatedby') or ''))
        cand.append({
            'spill_id': int(r['id']), 'incident_number': re.sub(r'[\s.]+$', '', (r.get('incidentnumber') or '').strip().upper()),
            'status': r['status'].strip().lower(), 'updated': max(upd) if upd else '',
            'incident_date': d, 'operator': opmap.get(raw_op.upper(), raw_op or 'Unknown'),
            'cause_code': (r.get('cause') or '').strip().lower() or 'ytd',
            'facility_code': (r.get('typeoffacility') or '').strip().lower() or 'oth',
            'lga': re.sub(r'\s+', ' ', (r.get('lga') or '').replace('-', ' ')).strip() or None,
            'site_name_clean': site, 'asset_corridor': site,
            'pipe_diameter_in': float(m.group(1)) if m and 2 <= float(m.group(1)) <= 60 else None,
            'latitude': lat, 'longitude': lon, 'qty_bbl': qty,
            'is_non_leak': 1 if (r.get('contaminant') or '').strip().lower() == 'no' or qty == 0 else 0,
            'jiv_mltry': 1 if 'mltry' in (r.get('jivpresent') or '') else 0,
        })
    # duplicates: same incident number + date, or same operator + date + point + quantity. Keep best status, latest update.
    cand.sort(key=lambda c: (c['status'] != 'confirmed', c['updated']), reverse=False)
    cand.sort(key=lambda c: (0 if c['status'] == 'confirmed' else 1, [-ord(ch) for ch in c['updated']]))
    seen, out = set(), []
    for c in cand:
        k1 = ('n', c['incident_number'], c['incident_date']) if c['incident_number'] else None
        k2 = ('p', c['operator'], c['incident_date'], round(c['latitude'], 5), round(c['longitude'], 5), c['qty_bbl'])
        if (k1 and k1 in seen) or k2 in seen:
            continue
        if k1:
            seen.add(k1)
        seen.add(k2)
        c['state'] = state_of(c['latitude'], c['longitude'])
        out.append(c)
    out.sort(key=lambda c: c['spill_id'])
    return out


# ---------------------------------------------------------------- OSM pipelines
def _dp(pts, tol):
    if len(pts) < 3:
        return pts
    a, b = pts[0], pts[-1]
    dx, dy = b[0] - a[0], b[1] - a[1]
    L = math.hypot(dx, dy) or 1e-12
    best, bi = 0, 0
    for i in range(1, len(pts) - 1):
        d = abs((pts[i][0] - a[0]) * dy - (pts[i][1] - a[1]) * dx) / L
        if d > best:
            best, bi = d, i
    if best <= tol:
        return [a, b]
    return _dp(pts[:bi + 1], tol)[:-1] + _dp(pts[bi:], tol)


def _cut(g, n):
    seglen = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(g, g[1:])]
    total = sum(seglen)
    if n <= 1 or total == 0:
        return [g]
    step, out, cur, acc, target = total / n, [], [g[0]], 0.0, total / n
    for (a, b), L in zip(zip(g, g[1:]), seglen):
        while L > 0 and acc + L >= target - 1e-9 and len(out) < n - 1:
            t = (target - acc) / L
            p = (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            cur.append(p); out.append(cur); cur = [p]
            a, L, acc, target = p, L - (target - acc), target, target + step
        cur.append(b); acc += L
    out.append(cur)
    return out


def osm_segments(osm):
    sys.setrecursionlimit(20000)
    segs = []
    for e in osm['elements']:
        tg = e.get('tags', {})
        if tg.get('substance') == 'water' or tg.get('location') == 'roof' or len(e.get('geometry', [])) < 2:
            continue
        g = _dp([(p['lon'] * KX, p['lat'] * KY) for p in e['geometry']], 0.008)
        total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(g, g[1:]))
        if total < 0.05:
            continue
        sub = {'oil': 1, 'gas': 2}.get(tg.get('substance'), 0)
        for piece in _cut(g, math.ceil(total / SEG_KM)):
            km = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(piece, piece[1:]))
            segs.append({'sub': sub, 'name': tg.get('name') or '', 'g': piece, 'km': km})
    return segs


# ---------------------------------------------------------------- bundle
def build(rows, osm, feed_count):
    names.build(rows)

    def index(vals):
        c = collections.Counter(v for v in vals if v)
        lst = [k for k, _ in c.most_common()]
        return lst, {k: i for i, k in enumerate(lst)}

    ops, opi = index(r['operator'] for r in rows)
    lines, linei = index(r['line'] for r in rows)
    lgas, lgai = index(r['lga'] for r in rows)
    states, statei = index(r['state'] for r in rows)

    segs = osm_segments(osm)
    G = collections.defaultdict(list)
    for si, s in enumerate(segs):
        for a, b in zip(s['g'], s['g'][1:]):
            for gx in range(int(min(a[0], b[0]) // 3) - 1, int(max(a[0], b[0]) // 3) + 2):
                for gy in range(int(min(a[1], b[1]) // 3) - 1, int(max(a[1], b[1]) // 3) + 2):
                    G[(gx, gy)].append((a, b, si))

    def snap(x, y):
        best, bi = SNAP_KM, -1
        for a, b, si in G.get((int(x // 3), int(y // 3)), ()):
            dx, dy = b[0] - a[0], b[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0 if L2 == 0 else max(0, min(1, ((x - a[0]) * dx + (y - a[1]) * dy) / L2))
            d = math.hypot(x - a[0] - t * dx, y - a[1] - t * dy)
            if d <= best:
                best, bi = d, si
        return bi

    for r in rows:
        r['seg'] = snap(r['longitude'] * KX, r['latitude'] * KY)

    by_line = collections.defaultdict(list)
    for r in rows:
        if r['line']:
            by_line[r['line']].append(r)

    def dia_of(rr):
        d = collections.Counter(r['pipe_diameter_in'] for r in rr if r['pipe_diameter_in']).most_common(1)
        return d[0][0] if d else None

    routes, approx = {}, {}
    for nm, rr in by_line.items():
        if len(rr) < 5:
            continue
        c = collections.Counter(r['seg'] for r in rr if r['seg'] >= 0)
        snapped = sum(c.values())
        ss = sorted(s for s, n in c.items() if n >= max(2, math.ceil(0.02 * snapped)))
        if snapped / len(rr) >= 0.5 and ss:
            routes[linei[nm]] = {'s': ss, 'km': round(sum(segs[s]['km'] for s in ss), 1), 'dia': dia_of(rr)}
        elif len(rr) >= 6:      # not mapped in OSM: approximate trace through the line's own spill sites
            t = traces.trace([(r['latitude'], r['longitude']) for r in rr])
            if t:
                approx[linei[nm]] = {'t': t[0], 'km': t[1], 'dia': dia_of(rr)}

    out_rows = []
    for r in rows:
        q = r['qty_bbl']
        out_rows.append([r['spill_id'], r['incident_date'], r['cause_code'], opi.get(r['operator'], -1), r['facility_code'],
                         statei.get(r['state'], -1), lgai.get(r['lga'], -1), linei.get(r['line'], -1),
                         round(r['latitude'], 4), round(r['longitude'], 4), None if q is None else round(q, 2),
                         r['site_name_clean'], r['is_non_leak'], r['jiv_mltry'], r['seg']])
    sab = [r for r in rows if r['cause_code'] == 'sab']
    base = json.loads((STATIC / 'base.json').read_text(encoding='utf8'))
    version = hashlib.sha1(json.dumps(out_rows, separators=(',', ':')).encode()).hexdigest()[:12]
    return {'meta': {'records': len(rows), 'raw': feed_count, 'min_date': min(r['incident_date'] for r in rows),
                     'max_date': max(r['incident_date'] for r in rows), 'osm_km': round(sum(s['km'] for s in segs)),
                     'osm_segs': len(segs), 'osm_near': sum(1 for r in sab if r['seg'] >= 0), 'sab': len(sab),
                     'named_sab': sum(1 for r in sab if r['line']), 'routes': len(routes), 'version': version,
                     'synced_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                     'latest': [r['spill_id'] for r in sorted(rows, key=lambda r: r['incident_date'])[-1:]]},
            'ops': ops, 'lines': lines, 'lgas': lgas, 'states': states, 'rows': out_rows, 'routes': routes,
            'approx': approx,
            'segs': [[s['sub'], s['name'], round(s['km'], 2), [[round(p[1] / KY, 5), round(p[0] / KX, 5)] for p in s['g']]] for s in segs],
            'geo_states': base['states'], 'geo_rivers': base['rivers']}


def run(feed=None, refresh_osm=False):
    """Download (unless feed is given), clean, build and write data.json. Returns the bundle's meta."""
    feed = feed or fetch_feed()
    osm_p = STATIC / 'osm_pipelines.json'
    if refresh_osm or not osm_p.exists():
        try:
            osm_p.write_text(json.dumps(fetch_osm()), encoding='utf8')
        except Exception as e:                       # keep the cached copy if Overpass is busy
            if not osm_p.exists():
                raise
            print('OSM refresh skipped:', e)
    rows = clean(feed)
    data = build(rows, json.loads(osm_p.read_text(encoding='utf8')), len(feed))
    tmp = HERE / 'data.json.tmp'
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')), encoding='utf8')
    tmp.replace(HERE / 'data.json')
    return data['meta']


if __name__ == '__main__':
    src = json.loads(Path(sys.argv[1]).read_text(encoding='utf8')) if len(sys.argv) > 1 else None
    print(json.dumps(run(src, refresh_osm='--osm' in sys.argv), indent=1))
