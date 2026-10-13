import re, json, collections, difflib

LINE_KW = r"PIPE\s*LINES?|P/LINE|P/L\b|TRUNK\s*LINE|TRUNKLINE|T/L\b|DELIVERY\s*LINE|DELIVERY|D/L\b|FLOW\s*LINE|FLOWLINE|F/L\b|GAS\s*LINE|BULK\s*LINE|EXPORT\s*LINE|\bLINE\b|\bTNP\b|\bTFP\b|\bNCTL\b|\bTRANS\b"
OPS = r"\b(NEPL|NPDC|SPDC|NAOC|AGIP|SHELL|POOC|POOCN|CHEVRON|SEPLAT|HEIRS|NNPC|ERL|MPN|PPMC|NDWEST|OANDO|EROTON|AITEO)\b"
ALIAS = {'TEBIBADA': 'TEBIDABA', 'TIBEDABA': 'TEBIDABA', 'EOC': 'EBOCHA', 'TEB': 'TEBIDABA', 'CLOUGH': 'CLOUGH CREEK', 'CLOUGHCREEK': 'CLOUGH CREEK',
         'KOLOCREEK': 'KOLO CREEK', 'KOLO': 'KOLO CREEK', 'IMORIVER': 'IMO RIVER', 'PH': 'PORT HARCOURT',
         'PHC': 'PORT HARCOURT', 'BRASSTERMINAL': 'BRASS', 'BONNYTERMINAL': 'BONNY'}
SINGLE = [(r"\bTRANS[\s-]*NIGER\b|\bTNP\b", 'TRANS NIGER'), (r"\bTRANS[\s-]*FORCADOS\b|\bTFP\b", 'TRANS FORCADOS'),
          (r"\bTRANS[\s-]*ESCRAVOS\b", 'TRANS ESCRAVOS'), (r"\bTRANS[\s-]*RAMOS\b", 'TRANS RAMOS'),
          (r"\bNCTL\b|NEMBE CREEK TRUNK", 'NEMBE CREEK TRUNK LINE')]
SYS = {nm for _, nm in SINGLE}
QUOTES = {0x2019: "'", 0x2018: "'", 0x201d: '"', 0x201c: '"', 0x60: "'", 0x2013: '-', 0x2014: '-'}
CUT = r"\s*@|\s+AT\s+|\s+IN\s+|\s+NEAR\s+|\s+ALONG\s+|\s+AROUND\s+|\s+BEHIND\s+|\s+BY\s+|,|\.(?:\s|$)"
NOISE = r"\b(OLD|NEW|THE|ALONG|ROW|RIGHT OF WAY|GAS|OIL|CRUDE|NGL|EXPORT|BULK|TEST|MAIN|LEAK|LEAKAGE)\b"


def pre(s):
    s = s.upper().translate(QUOTES)
    s = re.sub(r"\([^)]*\)", ' ', s)
    s = re.sub(r"OB\s*[-/]\s*OB", 'OBOB', s)
    s = re.sub(r"^\s*\d+(\.\d+)?\s*(''|\"|'|INCH(ES)?\b|IN\b|;;|\?)*\s*", '', s)   # leading diameter
    s = re.sub(r"\b\d+(\.\d+)?\s*(''|\"|INCH(ES)?\b)\s*", ' ', s)                   # inline diameter
    return re.sub(r"\s+", ' ', s).strip()


def parse(corr, fac):
    """('two', (a, b)) | ('one', name) | ('sys', name) | (None, None)"""
    if not corr:
        return (None, None)
    s = pre(corr)
    m = re.search(LINE_KW, s)
    has_kw = m is not None
    head = s[:m.start()].strip() if m else s
    head = re.split(CUT, head)[0].strip()
    head = re.sub(OPS, ' ', head)
    head = re.sub(r"\bOML\s*\d+\b", ' ', head)
    head = re.sub(NOISE, ' ', head)
    head = re.sub(r"[^A-Z0-9/\-_= &]", ' ', head)
    head = re.sub(r"\s+", ' ', head).strip(' -/_=&')
    if not head or len(head) < 3 or re.fullmatch(r"[\d\s]+", head):
        for rx, nm in SINGLE:
            if re.search(rx, s):
                return ('sys', nm)
        return (None, None)
    parts = [p.strip() for p in re.split(r"\s*[-/_=]+\s*|\s+TO\s+", head) if p.strip()]
    if not has_kw and fac not in ('pl', 'bl', 'gl', 'fl'):
        return (None, None)
    if len(parts) >= 3:
        if sq(parts[0] + parts[1]) in ALIAS or parts[1] in ('CREEK', 'RIVER'):
            parts = [parts[0] + ' ' + parts[1]] + parts[2:]
    if len(parts) >= 3 and parts[-1] in ('CREEK', 'RIVER'):
        parts = parts[:-2] + [parts[-2] + ' ' + parts[-1]]
    if len(parts) >= 2:
        return ('two', (parts[0], ' '.join(parts[1:])))
    return ('one' if has_kw else 'maybe', parts[0])


def sq(x):
    return x.replace(' ', '')


def alias(x):
    x = re.sub(r"\s+", ' ', x).strip()
    return ALIAS.get(sq(x), x)


def lev1(a, b):
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    if len(a) > len(b):
        a, b = b, a
    return any(a == b[:i] + b[i + 1:] for i in range(len(b)))


ACR = {'UPS', 'GTS', 'NLNG', 'LNG', 'QIT', 'BRT', 'CPF', 'MWOG', 'UPIL', 'NGC', 'ELPS', 'LACT'}


def cap(s):
    return ' '.join(w if (re.search(r"\d", w) or w in ACR) else w.capitalize() for w in s.split(' '))


def build(records):
    """Adds r['line'] (display name or None) and r['line_two'] to every record."""
    parsed = [parse(r['asset_corridor'], r['facility_code']) for r in records]
    ep = collections.Counter()
    disp = {}
    for k, p in parsed:
        if k == 'two':
            for e in p:
                a = alias(e)
                ep[sq(a)] += 1
                disp.setdefault(sq(a), collections.Counter())[a] += 1
    names = sorted(ep, key=lambda x: -ep[x])
    canon = {}
    for a in names:
        best = None
        for b in names:
            if ep[b] < 5 * ep[a] or ep[b] < 10:
                break
            if b == a or canon.get(b, b) != b:
                continue
            if re.sub(r"\D", '', a) != re.sub(r"\D", '', b):
                continue
            r = difflib.SequenceMatcher(None, a, b).ratio()
            if (len(a) >= 4 and (r >= 0.8 or lev1(a, b))) or (len(a) == 3 and r >= 0.85):
                score = r + (0.05 if a[0] == b[0] else 0)
                if best is None or score > best[0]:
                    best = (score, b)
        canon[a] = best[1] if best else a

    def ce(e):
        k = sq(alias(e))
        return canon.get(k, k)

    big = {e for e in ep if canon[e] == e and ep[e] >= 10}
    out = []
    for k, p in parsed:
        if k in ('one', 'maybe'):
            toks = p.split(' ')
            for i in range(1, len(toks)):
                a, b = ce(' '.join(toks[:i])), ce(' '.join(toks[i:]))
                if a in big and b in big and a != b:
                    k, p = 'two', (' '.join(toks[:i]), ' '.join(toks[i:]))
                    break
        if k == 'maybe':
            k, p = None, None
        out.append((k, p))
    order = collections.Counter()
    keys = []
    for k, p in out:
        if k == 'two':
            a, b = ce(p[0]), ce(p[1])
            if a == b:
                keys.append(('one', a))
                continue
            order[(a, b)] += 1
            keys.append(('two', tuple(sorted((a, b)))))
        elif k == 'one':
            keys.append(('one', sq(p)))
        elif k == 'sys':
            keys.append(('sys', p))
        else:
            keys.append(None)
    one_disp = {}
    for (k, p), key in zip(out, keys):
        if key and key[0] == 'one' and k == 'one':
            one_disp.setdefault(key[1], collections.Counter())[p] += 1

    def show(e):
        d = disp.get(e)
        return cap(d.most_common(1)[0][0] if d else e)

    label = {}
    for key in set(k for k in keys if k):
        if key[0] == 'two':
            a, b = key[1]
            if order[(b, a)] > order[(a, b)]:
                a, b = b, a
            label[key] = show(a) + '–' + show(b)
        elif key[0] == 'sys':
            label[key] = cap(key[1])
        else:
            d = one_disp.get(key[1])
            label[key] = cap(d.most_common(1)[0][0]) if d else show(key[1])
    for r, key in zip(records, keys):
        r['line'] = label[key] if key else None
        r['line_two'] = bool(key and key[0] in ('two', 'sys'))
    return {a: b for a, b in canon.items() if a != b}, ep
