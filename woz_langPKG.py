#!/usr/bin/env python3
"""
woz_langpkg.py - World of Zoo "Language*.pkg" tool (info / extract / pack / convert)

Container layout (reverse-engineered from LanguageBear.pkg [Wii, big-endian] and
LanguagePanda.pkg [PC, little-endian]; all ints use the file's endianness):

  0x00  u32 flag        (Wii sample = 1, PC sample = 0; meaning not confirmed)
  0x04  u32 zero
  0x08  u32 nTypes      (2: "raw", "PMap")
  0x0C  u32 nEntries    (4)
  0x10  nTypes  * 0x28  { u32 id; char name[32]; u32 one }
        nEntries* 0x120 { u32 index(1..n); char name[0x100]; u32 dataOffset (from end of tables); u32 compSize; u32 rawSize;
                          u32 crc32(compressed); u32 crc32(raw); u32 one; u32 one_or_two }
        then the zlib streams, back to back, in entry order.

Inner formats handled by 'convert':
  *.sbin : u16 BOM (FEFF=BE / FFFE=LE), u16 count, count * { char key[20]; u32 offset (in u16 units) },
           then the text blob: per string { u16 nChars; UTF-16 chars }, concatenated
  *.pmp  : "BFBINARY" PMap whose payload is a GUILocalizedTextFileList (list of UTF-16 names)
Anything else is byte-copied and reported, never silently guessed.
"""
import struct, sys, os, zlib, argparse

def pack_int(e, fmt, *v): return struct.pack(e + fmt, *v)

# ---------------------------------------------------------------- container
def read_pkg(path):
    d = open(path, 'rb').read()
    be = struct.unpack_from('>I', d, 8)[0] < 0x10000
    e = '>' if be else '<'
    flag, zero, nt, ne = struct.unpack_from(e + '4I', d, 0)
    p = 0x10
    types = []
    for _ in range(nt):
        tid = struct.unpack_from(e + 'I', d, p)[0]
        name = d[p+4:p+36].split(b'\0')[0]
        one = struct.unpack_from(e + 'I', d, p+36)[0]
        types.append((tid, name, one)); p += 0x28
    ents = []
    for _ in range(ne):
        idx = struct.unpack_from(e + 'I', d, p)[0]
        name = d[p+4:p+0x104].split(b'\0')[0].decode('latin1')
        doff, comp, raw, c1, c2, b, c = struct.unpack_from(e + '7I', d, p+0x104)
        ents.append(dict(idx=idx, name=name, doff=doff, comp=comp, raw=raw, crc_c=c1, crc_r=c2, b=b, c=c))
        p += 0x120
    off = p
    for en in ents:
        if en['doff'] != off - p: raise ValueError('data offset mismatch: ' + en['name'])
        blob = d[off:off+en['comp']]; off += en['comp']
        if zlib.crc32(blob) & 0xffffffff != en['crc_c']: raise ValueError('compressed CRC mismatch: ' + en['name'])
        data = zlib.decompress(blob)
        if len(data) != en['raw'] or zlib.crc32(data) & 0xffffffff != en['crc_r']:
            raise ValueError('raw size/CRC mismatch: ' + en['name'])
        en['data'] = data
    if off != len(d): print('warning: %d trailing bytes' % (len(d) - off), file=sys.stderr)
    return dict(be=be, flag=flag, zero=zero, types=types, ents=ents)

def write_pkg(path, pkg, be):
    e = '>' if be else '<'
    out = bytearray(pack_int(e, '4I', pkg['flag'], pkg['zero'], len(pkg['types']), len(pkg['ents'])))
    for tid, name, one in pkg['types']:
        out += pack_int(e, 'I', tid) + name.ljust(32, b'\0') + pack_int(e, 'I', one)
    blobs = []; doff = 0
    for en in pkg['ents']:
        blob = zlib.compress(en['data'], 6)          # level 6 reproduces the original PC blobs byte-for-byte
        blobs.append(blob)
        out += pack_int(e, 'I', en['idx']) + en['name'].encode('latin1').ljust(0x100, b'\0')[:0x100]
        out += pack_int(e, '7I', doff, len(blob), len(en['data']), zlib.crc32(blob) & 0xffffffff,
                        zlib.crc32(en['data']) & 0xffffffff, en['b'], en['c'])
        doff += len(blob)
    for b in blobs: out += b
    open(path, 'wb').write(out)

# ---------------------------------------------------------------- inner formats
def swap_sbin(data):
    """Swap endianness of a .sbin string table (validated: offsets must be consistent, whole file consumed)."""
    if data[:2] == b'\xfe\xff': e_in, e_out, bom = '>', '<', b'\xff\xfe'
    elif data[:2] == b'\xff\xfe': e_in, e_out, bom = '<', '>', b'\xfe\xff'
    else: raise ValueError('sbin: unknown BOM')
    cnt = struct.unpack_from(e_in + 'H', data, 2)[0]
    out = bytearray(bom + struct.pack(e_out + 'H', cnt))
    blob = 4 + cnt * 24
    pos = 0                                   # running offset in u16 units
    for i in range(cnt):
        p = 4 + i * 24
        key = data[p:p+20]
        off = struct.unpack_from(e_in + 'I', data, p + 20)[0]
        if off != pos: raise ValueError('sbin: offset table inconsistent at entry %d' % i)
        out += key + struct.pack(e_out + 'I', off)
        n = struct.unpack_from(e_in + 'H', data, blob + 2 * pos)[0]
        pos += 1 + n
    if blob + 2 * pos != len(data): raise ValueError('sbin: text blob size mismatch')
    body = data[blob:]
    out += b''.join(body[i:i+2][::-1] for i in range(0, len(body), 2))   # prefixes and chars are all u16
    return bytes(out)

def swap_pmp(data):
    """Swap endianness of a BFBINARY GUILocalizedTextFileList PMap."""
    if data[:8] != b'BFBINARY': raise ValueError('pmp: not BFBINARY')
    ver_be = struct.unpack_from('>I', data, 8)[0]
    e_in = '>' if ver_be == 1 else '<'
    e_out = '<' if e_in == '>' else '>'
    p = 8
    out = bytearray(b'BFBINARY')
    def u32():
        nonlocal p
        v = struct.unpack_from(e_in + 'I', data, p)[0]; p += 4; return v
    def put32(v): out.extend(struct.pack(e_out + 'I', v))
    v = u32(); put32(v)                         # version
    n = u32(); put32(n); out += data[p:p+n]; p += n        # type name (ASCII)
    if data[8+4+4:8+4+4+n] != b'GUILocalizedTextFileList':
        raise ValueError('pmp: unsupported PMap type %r' % data[16:16+n])
    cnt = u32(); put32(cnt)
    out.append(data[p]); p += 1                 # 1-byte type tag
    n = u32(); put32(n); out += data[p:p+n]; p += n        # 'unicodestring'
    for _ in range(cnt):
        n = u32(); put32(n)
        txt = data[p:p+n]; p += n
        out += b''.join(txt[i:i+2][::-1] for i in range(0, len(txt), 2))
    if p != len(data): raise ValueError('pmp: %d unparsed bytes' % (len(data) - p))
    return bytes(out)

def convert_pkg(pkg, to_be):
    if pkg['be'] == to_be: raise ValueError('already in requested byte order')
    new = dict(pkg); new['ents'] = []
    new['flag'] = 1 if to_be else 0       # ASSUMPTION: copied from one Wii + one PC sample
    for en in pkg['ents']:
        en = dict(en)
        if en['name'].endswith('.sbin'): en['data'] = swap_sbin(en['data'])
        elif en['name'].endswith('.pmp'): en['data'] = swap_pmp(en['data'])
        else: print('warning: not converted (unknown type):', en['name'], file=sys.stderr)
        new['ents'].append(en)
    return new

# ---------------------------------------------------------------- CLI
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('info');    s.add_argument('pkg')
    s = sub.add_parser('extract'); s.add_argument('pkg'); s.add_argument('outdir')
    s = sub.add_parser('convert'); s.add_argument('pkg'); s.add_argument('out'); s.add_argument('--to', choices=['pc', 'wii'], default='pc')
    a = ap.parse_args()
    pkg = read_pkg(a.pkg)
    if a.cmd == 'info':
        print('byte order:', 'big-endian (Wii)' if pkg['be'] else 'little-endian (PC)', '| flag =', pkg['flag'])
        for en in pkg['ents']:
            print('%d  %-45s comp=%-6d raw=%-6d CRCs OK' % (en['idx'], en['name'], en['comp'], en['raw']))
    elif a.cmd == 'extract':
        for en in pkg['ents']:
            p = os.path.join(a.outdir, en['name'])
            os.makedirs(os.path.dirname(p), exist_ok=True); open(p, 'wb').write(en['data'])
        print('extracted', len(pkg['ents']), 'files to', a.outdir)
    else:
        to_be = a.to == 'wii'
        write_pkg(a.out, convert_pkg(pkg, to_be), to_be)
        print('wrote', a.out, '(', 'big' if to_be else 'little', 'endian )')

if __name__ == '__main__':
    main()
