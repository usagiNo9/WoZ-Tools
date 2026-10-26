#!/usr/bin/env python3
"""World of Zoo .pkg tool (PC little-endian / Wii big-endian containers).
  list    <pkg>
  extract <pkg> <outdir>        (writes files + _manifest.json)
  repack  <indir> <out.pkg> [--endian le|be] [--level N]
"""
import struct, zlib, binascii, os, sys, json

HDR_TYPES = 0x0c           # 8 type records of 40 bytes: u32 X, u32 id, char name[32]
ENT_SIZE  = 288

def header_size(d, e):
    """fixed header = 8 bytes + 40 bytes per resource type (8 types normally, 9 in some packages)"""
    return 8 + 40 * struct.unpack_from(e + 'I', d, 8)[0]

def _endian(d):
    return '>' if struct.unpack_from('>I', d, 0)[0] == 1 else '<'

def read_pkg(fn):
    d = open(fn, 'rb').read()
    e = _endian(d); u = lambda o: struct.unpack_from(e + 'I', d, o)[0]
    S = header_size(d, e); n = u(12); pos = S + n * ENT_SIZE + 8
    ents = []
    for i in range(n):
        o = S + i * ENT_SIZE
        csz, usz, crc_c, crc_u = (u(o + 272), u(o + 276), u(o + 280), u(o + 284))
        blk = d[pos:pos + csz]; pos += csz
        data = zlib.decompress(blk)
        assert len(data) == usz and binascii.crc32(data) == crc_u and binascii.crc32(blk) == crc_c, i
        ents.append(dict(idx=u(o), typ=u(o + 4), ord=u(o + 8),
                         pathbuf=d[o + 12:o + 272], data=data, blk=blk))
    return d, e, ents

def build_pkg(header_types, ents, endian, level=9, reuse_blocks=False, clean=False):
    """header_types: the fixed header template (in *target* endianness); the entry count is patched in.
    The last 4 bytes of every 260-byte path buffer hold the entry's data offset (sum of the compressed sizes
    before it), so they are recomputed here. clean=True also zero-fills the stale bytes after the path text."""
    E = endian
    out = bytearray(header_types)
    struct.pack_into(E + 'I', out, 12, len(ents))
    body = bytearray(); table = bytearray()
    for e in ents:
        blk = e['blk'] if reuse_blocks and 'blk' in e else zlib.compress(e['data'], level)
        pb = e['pathbuf']
        if clean: pb = pb[:256].split(b'\0')[0].ljust(256, b'\0')
        else: pb = pb[:256]
        pb += struct.pack(E + 'I', len(body))
        table += struct.pack(E + 'III', e['idx'], e['typ'], e['ord']) + pb
        table += struct.pack(E + 'IIII', len(blk), len(e['data']), binascii.crc32(blk), binascii.crc32(e['data']))
        body += blk
    gap = struct.pack(E + 'II', 1, struct.unpack_from(E + 'I', header_types, 8)[0])
    return bytes(out) + bytes(table) + gap + bytes(body)

def swap_header(hdr, src, dst):
    """convert the fixed header between endiannesses (u32 fields only; names untouched).
    Word 0 is a platform flag: 1 on Wii, 0 on PC (not an endian-swapped value)."""
    b = bytearray(hdr)
    nt = struct.unpack_from(src + 'I', b, 8)[0]
    def sw(o):
        v = struct.unpack_from(src + 'I', b, o)[0]; struct.pack_into(dst + 'I', b, o, v)
    for o in (4, 8, 12): sw(o)                      # word 12 doubles as type-record 0's first field
    sw(HDR_TYPES + 4)
    for k in range(1, nt):
        sw(HDR_TYPES + 40 * k); sw(HDR_TYPES + 40 * k + 4)
    struct.pack_into(dst + 'I', b, 0, 1 if dst == '>' else 0)
    return bytes(b)


# ---------------- command line ----------------
def _cli():
    import argparse, base64
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('list');    s.add_argument('pkg')
    s = sub.add_parser('extract'); s.add_argument('pkg'); s.add_argument('outdir')
    s = sub.add_parser('repack');  s.add_argument('indir'); s.add_argument('out')
    s.add_argument('--endian', choices=['le', 'be'], default=None, help='target format (default: same as extracted)')
    s.add_argument('--level', type=int, default=6)
    a = ap.parse_args()
    if a.cmd == 'list':
        d, e, ents = read_pkg(a.pkg)
        print('format:', 'Wii (big-endian)' if e == '>' else 'PC (little-endian)', '| entries:', len(ents))
        for i, x in enumerate(ents):
            print('%4d %9d  %s' % (i, len(x['data']), x['pathbuf'].split(b'\0')[0].decode('latin1')))
    elif a.cmd == 'extract':
        d, e, ents = read_pkg(a.pkg)
        os.makedirs(a.outdir, exist_ok=True)
        man = dict(endian=e, header=base64.b64encode(d[:header_size(d, e)]).decode(), entries=[])
        for x in ents:
            p = x['pathbuf'].split(b'\0')[0].decode('latin1')
            fp = os.path.join(a.outdir, 'files', p)
            os.makedirs(os.path.dirname(fp), exist_ok=True)
            open(fp, 'wb').write(x['data'])
            man['entries'].append(dict(idx=x['idx'], typ=x['typ'], ord=x['ord'], path=p,
                                       pathbuf=base64.b64encode(x['pathbuf']).decode()))
        json.dump(man, open(os.path.join(a.outdir, '_manifest.json'), 'w'), indent=1)
        print('extracted', len(ents), 'entries to', a.outdir)
    elif a.cmd == 'repack':
        man = json.load(open(os.path.join(a.indir, '_manifest.json')))
        src = '>' if man['endian'] == '>' else '<'
        dst = src if a.endian is None else ('>' if a.endian == 'be' else '<')
        hdr = base64.b64decode(man['header'])
        if dst != src: hdr = swap_header(hdr, src, dst)
        ents = []
        for m in man['entries']:
            ents.append(dict(idx=m['idx'], typ=m['typ'], ord=m['ord'], pathbuf=base64.b64decode(m['pathbuf']),
                             data=open(os.path.join(a.indir, 'files', m['path']), 'rb').read()))
        open(a.out, 'wb').write(build_pkg(hdr, ents, dst, level=a.level))
        print('wrote', a.out, '(%s, %d entries)' % ('BE' if dst == '>' else 'LE', len(ents)))

if __name__ == '__main__':
    _cli()
