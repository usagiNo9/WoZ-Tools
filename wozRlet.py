#!/usr/bin/env python3
"""wozRlet.py - convert World of Zoo .rlet layer masks to ordinary PNG images and back, losslessly. Standard library only.

An .rlet is an 8-bit grayscale mask (0 = nothing, 255 = full; the appearance system uses it as the blend mask of one pattern or
body part, 512x512 in every animal; the low-resolution *_256 variants of the Wii are 256x256) stored top row first, run-length
coded. Converting to PNG and back reproduces the file byte for byte (checked on all 3033 .rlet files in the game packages).

  python wozRlet.py info       mask.rlet
  python wozRlet.py to-png     mask.rlet|FOLDER  OUTFOLDER                (folders are searched recursively)
  python wozRlet.py from-png   image.png|FOLDER  OUTFOLDER [--wii]        PNG in, .rlet out (PC little-endian unless --wii)
  python wozRlet.py pkg-export Package.pkg  OUTFOLDER                     every .rlet of a package as a PNG, same folder layout
  python wozRlet.py pkg-import Package.pkg  IMAGEFOLDER OUTFOLDER --tag NAME     put edited images back -> OUTFOLDER/<Package>_<NAME>.pkg
  python wozRlet.py sheet      Package.pkg  OUT.png [--cols 12] [--thumb 128]     contact sheet of all masks + OUT.txt (which is which)

Editing: open the image in any editor and keep it 8-bit grayscale and the same size; any RGB/palette image is converted to
gray (luminance). Pure black = 0 and pure white = 255 are the cheapest values; grays make soft edges.
The image must have the same size as the original (pkg-import refuses otherwise, unless --force). Row 0 = top, the same way up as
the colour layers (.tga) look in an image viewer. Wii files (big-endian) are read as well; they are written big-endian with --wii or
when pkg-import patches a Wii package.
"""
import sys, os, struct, zlib, argparse, re

HDR_TAIL = (2, 0, 255)

# ---------------------------------------------------------------- rlet
def rlet_decode(b):
    """-> (width, height, bytes of w*h pixels, endian)"""
    E = '<' if struct.unpack_from('<I', b, 0)[0] == 10 else '>'
    h = struct.unpack_from(E + '11I', b, 0)
    if h[0] != 10 or h[5] != 44: raise ValueError('not an .rlet file')
    W, H, size, dl = h[3], h[4], h[6], h[7]; body = b[44:44 + dl]; out = bytearray(); p = 0; n = len(body)
    while p < n:
        v = body[p]
        if v == 0 or v == 255: out += bytes([v]) * struct.unpack_from(E + 'I', body, p + 1)[0]; p += 5
        else: out.append(v); p += 1
    if len(out) != W * H: raise ValueError('decoded %d pixels, header says %dx%d' % (len(out), W, H))
    return W, H, bytes(out), E

def rlet_encode(px, W, H, E='<'):
    if len(px) != W * H: raise ValueError('pixel count mismatch')
    out = bytearray(); i = 0; n = len(px); pk = struct.Struct(E + 'I').pack
    while i < n:
        v = px[i]
        if v == 0 or v == 255:
            j = i + 1
            while j < n and px[j] == v: j += 1
            out += bytes([v]) + pk(j - i); i = j
        else: out.append(v); i += 1
    return struct.pack(E + '11I', 10, 1, 4, W, H, 44, W * H, len(out), *HDR_TAIL) + bytes(out)

# ---------------------------------------------------------------- PNG (8-bit gray out; any non-interlaced PNG in)
def png_write(path, W, H, px):
    raw = b''.join(b'\0' + px[y * W:(y + 1) * W] for y in range(H))
    def chunk(t, d): return struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', W, H, 8, 0, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))

def _lum(r, g, b): return (299 * r + 587 * g + 114 * b + 500) // 1000

def png_read(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n': raise ValueError('not a PNG')
    p = 8; idat = b''; plte = None; trns = None
    while p < len(data):
        n, t = struct.unpack_from('>I4s', data, p); body = data[p + 8:p + 8 + n]; p += 12 + n
        if t == b'IHDR': W, H, bd, ct, _, _, il = struct.unpack('>IIBBBBB', body)
        elif t == b'PLTE': plte = body
        elif t == b'IDAT': idat += body
    if il: raise ValueError('interlaced PNG: save it again without interlacing')
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]; bits = bd * ch; stride = (W * bits + 7) // 8; bpp = max(1, bits // 8)
    raw = zlib.decompress(idat); rows = []; prev = bytearray(stride); q = 0
    for y in range(H):
        f = raw[q]; cur = bytearray(raw[q + 1:q + 1 + stride]); q += 1 + stride
        if f == 1:
            for i in range(bpp, stride): cur[i] = (cur[i] + cur[i - bpp]) & 255
        elif f == 2:
            for i in range(stride): cur[i] = (cur[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride): cur[i] = (cur[i] + ((cur[i - bpp] if i >= bpp else 0) + prev[i]) // 2) & 255
        elif f == 4:
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0; b = prev[i]; c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                cur[i] = (cur[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(cur); prev = cur
    out = bytearray()
    for cur in rows:
        if bd == 8:
            if ct == 0: out += cur
            elif ct == 2: out += bytes(_lum(cur[i], cur[i + 1], cur[i + 2]) for i in range(0, 3 * W, 3))
            elif ct == 3: out += bytes(_lum(*plte[3 * v:3 * v + 3]) for v in cur)
            elif ct == 4: out += cur[0::2]
            else: out += bytes(_lum(cur[i], cur[i + 1], cur[i + 2]) for i in range(0, 4 * W, 4))
        elif bd == 16:
            s = bytes(cur[0::2])                                   # high byte of every 16-bit sample
            if ct == 0: out += s
            elif ct == 2: out += bytes(_lum(s[i], s[i + 1], s[i + 2]) for i in range(0, 3 * W, 3))
            elif ct == 4: out += s[0::2]
            else: out += bytes(_lum(s[i], s[i + 1], s[i + 2]) for i in range(0, 4 * W, 4))
        else:                                                      # 1, 2, 4 bit gray or palette
            vals = []
            for byte in cur:
                for k in range(8 // bd - 1, -1, -1): vals.append((byte >> (k * bd)) & ((1 << bd) - 1))
            vals = vals[:W]
            if ct == 0: out += bytes(v * 255 // ((1 << bd) - 1) for v in vals)
            else: out += bytes(_lum(*plte[3 * v:3 * v + 3]) for v in vals)
    return W, H, bytes(out)

def image_read(path): return png_read(open(path, 'rb').read())

# ---------------------------------------------------------------- helpers
def files_under(root, exts):
    if not os.path.exists(root): raise SystemExit('not found: %s' % root)
    if os.path.isfile(root): return [(root, os.path.basename(root))]
    out = []
    for r, _, fs in os.walk(root):
        for f in sorted(fs):
            if f.lower().endswith(exts): out.append((os.path.join(r, f), os.path.relpath(os.path.join(r, f), root)))
    return out

def swap_ext(rel, ext): return os.path.splitext(rel)[0] + ext

def write_image(path, W, H, px):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True); png_write(path, W, H, px)

def load_pkg(path):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import wozPKG
    d, e, ents = wozPKG.read_pkg(path); return wozPKG, d, e, ents

def name(x): return x['pathbuf'].split(b'\0')[0].decode('latin1')

# ---------------------------------------------------------------- commands
def cmd_info(a):
    b = open(a.file, 'rb').read(); W, H, px, E = rlet_decode(b)
    vals = sorted(set(px)); nz = sum(1 for v in px if v)
    print('%s: %dx%d, %s-endian (%s), %d bytes' % (os.path.basename(a.file), W, H, 'little' if E == '<' else 'big', 'PC' if E == '<' else 'Wii', len(b)))
    print('values: %d distinct (min %d, max %d); non-zero pixels %.1f%%; fully white %.1f%%' % (len(vals), vals[0], vals[-1], 100 * nz / len(px), 100 * px.count(255) / len(px)))
    print('re-encodes byte-identical:', rlet_encode(px, W, H, E) == b)

def cmd_to_png(a):
    n = 0
    for src, rel in files_under(a.src, ('.rlet',)):
        W, H, px, E = rlet_decode(open(src, 'rb').read()); write_image(os.path.join(a.out, swap_ext(rel, '.png')), W, H, px); n += 1
    if not n: raise SystemExit('no .rlet files found in %s' % a.src)
    print('%d mask(s) converted -> %s' % (n, a.out))

def cmd_from_png(a):
    n = 0; E = '>' if a.wii else '<'
    for src, rel in files_under(a.src, ('.png',)):
        W, H, px = image_read(src); dst = os.path.join(a.out, swap_ext(rel, '.rlet')); os.makedirs(os.path.dirname(dst) or '.', exist_ok=True)
        open(dst, 'wb').write(rlet_encode(px, W, H, E)); n += 1
        if (W, H) not in ((512, 512), (256, 256)): print('   note: %s is %dx%d (the game uses 512x512)' % (rel, W, H))
    if not n: raise SystemExit('no .png files found in %s' % a.src)
    print('%d image(s) converted -> %s' % (n, a.out))

def cmd_pkg_export(a):
    wp, d, e, ents = load_pkg(a.pkg); n = 0
    for x in ents:
        nm = name(x)
        if nm.lower().endswith('.rlet'):
            W, H, px, _ = rlet_decode(x['data']); write_image(os.path.join(a.out, swap_ext(nm, '.png')), W, H, px); n += 1
    print('%d mask(s) exported to %s (same folder layout as inside the package)' % (n, a.out))

def cmd_pkg_import(a):
    wp, d, e, ents = load_pkg(a.pkg); rl = {name(x).lower(): x for x in ents if name(x).lower().endswith('.rlet')}
    by_base = {}
    for k in rl: by_base.setdefault(os.path.basename(k), []).append(k)
    changed = 0; same = 0
    for src, rel in files_under(a.images, ('.png',)):
        key = swap_ext(rel.replace('\\', '/'), '.rlet').lower()
        if key not in rl:
            cand = by_base.get(os.path.basename(key), [])
            if len(cand) != 1: print('   skipped %s (no matching .rlet in the package%s)' % (rel, ', ambiguous name' if len(cand) > 1 else '')); continue
            key = cand[0]
        x = rl[key]; W0, H0, _, _ = rlet_decode(x['data']); W, H, px = image_read(src)
        if (W, H) != (W0, H0) and not a.force: print('   REFUSED %s: image is %dx%d, the mask is %dx%d (use --force to resize the mask)' % (rel, W, H, W0, H0)); continue
        new = rlet_encode(px, W, H, e)
        if new == x['data']: same += 1; continue
        x['data'] = new; x.pop('blk', None); changed += 1; print('   replaced', name(x))
    if not changed: print('nothing changed (%d image(s) identical to the package masks); no file written' % same); return
    stem = re.sub(r'_(PC|Wii)$', '', os.path.splitext(os.path.basename(a.pkg))[0], flags=re.I); os.makedirs(a.out, exist_ok=True)
    out = os.path.join(a.out, '%s_%s.pkg' % (stem, a.tag)); open(out, 'wb').write(wp.build_pkg(d[:wp.header_size(d, e)], ents, e, level=6))
    print('%d mask(s) replaced (%d unchanged) -> %s' % (changed, same, out))

def cmd_sheet(a):
    wp, d, e, ents = load_pkg(a.pkg); items = []
    for x in ents:
        if name(x).lower().endswith('.rlet'): items.append((name(x), rlet_decode(x['data'])))
    if not items: raise SystemExit('no .rlet files in this package')
    t = a.thumb; cols = a.cols; rows = (len(items) + cols - 1) // cols; W, H = cols * t, rows * t; img = bytearray(b'\x30' * (W * H)); lines = []
    for idx, (nm, (w, h, px, _)) in enumerate(items):
        fx, fy = max(1, w // t), max(1, h // t); ox, oy = (idx % cols) * t, (idx // cols) * t
        for ty in range(min(t, h // fy)):
            srows = [px[(ty * fy + k) * w:(ty * fy + k + 1) * w] for k in range(fy)]
            line = bytes(sum(sum(r[tx * fx:(tx + 1) * fx]) for r in srows) // (fx * fy) for tx in range(min(t, w // fx)))
            img[(oy + ty) * W + ox:(oy + ty) * W + ox + len(line)] = line
        lines.append('%3d  row %d col %d  %s' % (idx + 1, idx // cols + 1, idx % cols + 1, nm))
    for c in range(cols + 1):                                              # faint grid so the cells can be told apart
        for y in range(H): img[y * W + min(c * t, W - 1)] = 0x5a
    for r in range(rows + 1):
        yy = min(r * t, H - 1); img[yy * W:(yy + 1) * W] = bytes(max(v, 0x5a) if i % 4 else 0x5a for i, v in enumerate(img[yy * W:(yy + 1) * W]))
    png_write(a.out, W, H, bytes(img)); open(os.path.splitext(a.out)[0] + '.txt', 'w').write('\n'.join(lines) + '\n')
    print('%d masks -> %s (%dx%d, %d columns) and %s' % (len(items), a.out, W, H, cols, os.path.splitext(a.out)[0] + '.txt'))

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('info'); s.add_argument('file')
    s = sub.add_parser('to-png'); s.add_argument('src'); s.add_argument('out')
    s = sub.add_parser('from-png'); s.add_argument('src'); s.add_argument('out'); s.add_argument('--wii', action='store_true')
    s = sub.add_parser('pkg-export'); s.add_argument('pkg'); s.add_argument('out')
    s = sub.add_parser('pkg-import'); s.add_argument('pkg'); s.add_argument('images'); s.add_argument('out'); s.add_argument('--tag', required=True); s.add_argument('--force', action='store_true')
    s = sub.add_parser('sheet'); s.add_argument('pkg'); s.add_argument('out'); s.add_argument('--cols', type=int, default=12); s.add_argument('--thumb', type=int, default=128)
    a = ap.parse_args()
    {'info': cmd_info, 'to-png': cmd_to_png, 'from-png': cmd_from_png, 'pkg-export': cmd_pkg_export, 'pkg-import': cmd_pkg_import, 'sheet': cmd_sheet}[a.cmd](a)

if __name__ == '__main__': main()
