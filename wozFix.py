#!/usr/bin/env python3
"""wozfix.py - optional, OFF-BY-DEFAULT fixes for converted World of Zoo (PC, little-endian) .hkx files.
They are not part of the plain Wii->PC conversion: they work around differences in how the PC engine treats the converted
Penguin data, found by in-game testing. Both only touch one specific file and return the data unchanged if it does not match.

  penguin_hold_fix(data, dx=-0.06)   actors/penguinjackass/model/penguinjackass_adult_m.hkx
        moves the scene node 'Mouth_Attach_Point' (where held toys/food attach) back along the beak by 0.06 model units;
        held items then sit closer to the beak of baby and adult Penguins ("variant B", tested in game).
  nursery_mopp_bypass(data)          environments/nurserypool/model/nurserypool.hkx
        the rigid bodies Proxy_RB_Ground and Proxy_RB_Boundaries point at their shape list directly instead of through the
        MOPP tree (the converted MOPP trees of the Penguin nursery make walls/slopes leak on PC: "N1", tested in game).
        Only two pointers in the fixup table change; nothing else in the file is touched.
Usage: python wozfix.py in.hkx out.hkx hold|nursery        (or use wozconvert.py --penguin-hold-fix / --penguin-nursery-fix)
"""
import struct, sys

HOLD_PATH = 'actors/penguinjackass/model/penguinjackass_adult_m.hkx'
NURSERY_PATH = 'environments/nurserypool/model/nurserypool.hkx'

class FixError(Exception): pass

def _sections(d):
    secs = []
    for i in range(3):
        o = 0x40 + 0x30 * i
        secs.append(struct.unpack_from('<7I', d, o + 20))   # abs start, local, global, virtual, exports, imports, end
    return secs

def _scan(d):
    """-> (data section tuple, [(offset, class name)] sorted, local table entries [(pos, src, dst)], global entries [(pos, src, dst)])"""
    cn, ty, dat = _sections(d)
    names = {}; p = cn[0]; end = cn[0] + cn[1]
    while p < end and d[p + 4] == 9:
        q = d.index(b'\0', p + 5); names[p + 5 - cn[0]] = d[p + 5:q].decode('latin1'); p = q + 1
    objs = []
    for q in range(dat[0] + dat[3], dat[0] + dat[4], 12):
        if q + 12 > len(d): break
        a, s, b = struct.unpack_from('<III', d, q)
        if a == 0xFFFFFFFF: break
        objs.append((a, names.get(b, '?')))
    objs.sort()
    loc = []
    for q in range(dat[0] + dat[1], dat[0] + dat[2], 8):
        if q + 8 > len(d): break
        s, t = struct.unpack_from('<II', d, q)
        if s == 0xFFFFFFFF: break
        loc.append((q, s, t))
    glo = []
    for q in range(dat[0] + dat[2], dat[0] + dat[3], 12):
        if q + 12 > len(d): break
        s, sec, t = struct.unpack_from('<III', d, q)
        if s == 0xFFFFFFFF: break
        glo.append((q, s, t))
    return dat, objs, loc, glo

def _cstr(d, base, off):
    o = base + off; return d[o:d.index(b'\0', o)].decode('latin1')

def penguin_hold_fix(data, dx=-0.06):
    d = bytearray(data)
    try: dat, objs, loc, glo = _scan(bytes(d))
    except Exception as ex: raise FixError('cannot read the hkx structure: %s' % ex)
    base = dat[0]; L = {}
    for q, s, t in loc: L[s] = t
    for q, s, t in glo: L.setdefault(s, t)
    done = 0
    for a, n in objs:
        if n != 'hkxNode' or (a + 8) not in L: continue
        if _cstr(bytes(d), base, L[a + 8]) != 'Mouth_Attach_Point': continue
        cnt = struct.unpack_from('<I', d, base + a + 24)[0]; t = L[a + 20]
        for k in range(cnt):
            o = base + t + 64 * k + 48                  # translation row of the 4x4 node matrix
            x, y, z = struct.unpack_from('<3f', d, o)
            if not (0.10 < x < 0.13): raise FixError('unexpected Mouth_Attach_Point position %.4f (already patched, or a different model)' % x)
            struct.pack_into('<f', d, o, x + dx); done += 1
    if not done: raise FixError("node 'Mouth_Attach_Point' not found")
    return bytes(d), '%d keyframe(s) of Mouth_Attach_Point moved %+.3f along the beak' % (done, dx)

def nursery_mopp_bypass(data, bodies=('Proxy_RB_Ground', 'Proxy_RB_Boundaries')):
    d = bytearray(data)
    try: dat, objs, loc, glo = _scan(bytes(d))
    except Exception as ex: raise FixError('cannot read the hkx structure: %s' % ex)
    base = dat[0]; L = {}
    for q, s, t in loc: L[s] = t
    for q, s, t in glo: L.setdefault(s, t)
    cls = dict(objs); order = [a for a, _ in objs]; end = dat[4]
    ext = {a: (order[i + 1] if i + 1 < len(order) else end) for i, a in enumerate(order)}
    def inside(a): return sorted(s for s in L if a <= s < ext[a])
    log = []
    for b in [a for a in order if cls[a] == 'hkpRigidBody']:
        nm = None
        for s in inside(b):
            try:
                x = _cstr(bytes(d), base, L[s])
                if x.startswith('Proxy_RB_'): nm = x; break
            except Exception: pass
        if nm not in bodies: continue
        mopp = [(s - b, L[s]) for s in inside(b) if cls.get(L[s]) == 'hkpMoppBvTreeShape']
        if len(mopp) != 1: raise FixError('%s: expected one MOPP pointer, found %d' % (nm, len(mopp)))
        off, mt = mopp[0]
        lst = [L[s] for s in inside(mt) if cls.get(L[s]) == 'hkpListShape']
        if len(lst) != 1: raise FixError('%s: MOPP tree has no single list shape child' % nm)
        pos = [q + 4 for q, s, t in loc if s == b + off and t == mt] or [q + 8 for q, s, t in glo if s == b + off and t == mt]
        if len(pos) != 1: raise FixError('%s: shape pointer fixup not found' % nm)
        struct.pack_into('<I', d, pos[0], lst[0]); log.append('%s: MOPP -> list shape' % nm)
    if len(log) != len(bodies): raise FixError('expected rigid bodies %s, patched %d (already patched, or a different file)' % (', '.join(bodies), len(log)))
    return bytes(d), '; '.join(log)

FIXES = {'hold': (HOLD_PATH, penguin_hold_fix), 'nursery': (NURSERY_PATH, nursery_mopp_bypass)}

if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[3] not in FIXES: print(__doc__); sys.exit(1)
    out, msg = FIXES[sys.argv[3]][1](open(sys.argv[1], 'rb').read()); open(sys.argv[2], 'wb').write(out); print(msg)
