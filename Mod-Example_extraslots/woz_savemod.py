#!/usr/bin/env python3
"""woz_savemod.py - inspect and edit the unlock lists of a World of Zoo save file (ZooInfo2). Standalone, instant, no parser.

Why: slots (and other unlockables) are only granted by EVENTS (reaching a keeper rank, buying something). A save that is already
past that point never evaluates new unlockables, so a slot added to the game data stays locked on it. The save keeps the ids of
the unlocked things in `UnlockData` (and the ones still flagged "new" in `NewList`). This tool adds/removes ids there.

  python woz_savemod.py show   ZooInfo2
  python woz_savemod.py slots  ZooInfo2 OUTFOLDER --tag slots6 --count 6 --all                  every habitat: <habitat>Slot2..6
  python woz_savemod.py slots  ZooInfo2 OUTFOLDER --tag main6  --count 6 --all --no-nurseries   only the 11 main enclosures (or --only-nurseries)
  python woz_savemod.py slots  ZooInfo2 OUTFOLDER --tag bigcat6 --count 6 --habitat BigCatSavanna,BearForest
  python woz_savemod.py unlock ZooInfo2 OUTFOLDER --tag x --ids BigCatSavannaSlot4,BigCatSavannaSlot5
  python woz_savemod.py lock   ZooInfo2 OUTFOLDER --tag y --ids BigCatSavannaSlot4              take ids out again

The result is a NEW file  OUTFOLDER/ZooInfo2_<tag>  (the input is never modified); rename it to ZooInfo2 to use it.
Instead of OUTFOLDER + --tag you can also give a plain new file name as OUT.  --new also puts the ids in NewList (shown as new).
Slot 1 is always available and never listed.  ALWAYS keep a copy of your original save, and close the game first.

How it works (verified): the file is a 28-byte prefix ('BF01' ..., u32 at offset 20 = used length - 24), then blocks
[u16 type][u32 size][u32 1][BFBINARY map of size-4 bytes], then zero padding up to the fixed file size. UnlockData is a vector
[u32 count][u8 1][type name 'Identifier'][count x (u32 length + text)]: ids are appended/removed there, the count is updated,
and the block size, the length field in the prefix and the padding are fixed. Nothing else in the file is touched.
"""
import sys, os, struct, argparse, re

PREFIX = 28
# slot id prefixes of every habitat in the game (taken from the 22 slot files in Loading3Transient.pkg); ids are <prefix>Slot2..N
HABITATS = ['AntelopeNursery', 'AntelopeSavanna', 'BearForest', 'BigCatSavanna', 'CrocodileCoastal', 'ElephantGrassland',
            'GiraffeSavanna', 'HorseSavanna', 'KoalaForest', 'NurseryCrocodile', 'NurseryKoala', 'NurseryPaddockElephant',
            'NurseryPaddockGiraffe', 'NurseryPaddockHorse', 'NurseryPlaypenBear', 'NurseryPlaypenBigCat', 'NurseryPlaypenPanda',
            'NurseryPlaypenPenguin', 'NurserySmallMonkey', 'PandaForest', 'PenguinPool', 'SmallMonkeyJungle']

def u32(b, p): return struct.unpack_from('<I', b, p)[0]

def split(data):
    """-> (prefix bytes, [(type, payload)], used length)"""
    if data[:4] != b'BF01': raise SystemExit('not a World of Zoo save (missing BF01)')
    pos = PREFIX; blocks = []
    while pos + 18 <= len(data):
        t, size, one = struct.unpack_from('<HII', data, pos)
        if one != 1 or size < 4 or data[pos + 10:pos + 18] != b'BFBINARY': break
        blocks.append((t, data[pos + 10:pos + 6 + size])); pos += 6 + size
    if not blocks: raise SystemExit('no blocks found')
    if any(data[pos:]): raise SystemExit('unexpected non-zero data after the last block (offset %d)' % pos)
    if u32(data, 20) != pos - 24: raise SystemExit('length field does not match the blocks; unknown save layout')
    return data[:PREFIX], blocks, pos

def join(prefix, blocks, total):
    body = b''.join(struct.pack('<HII', t, len(p) + 4, 1) + p for t, p in blocks)
    used = PREFIX + len(body)
    if used > total: raise SystemExit('edited save would be %d bytes longer than the original file; refusing' % (used - total))
    pre = bytearray(prefix); struct.pack_into('<I', pre, 20, used - 24)
    return bytes(pre) + body + b'\0' * (total - used)

def find_vec(payload, key):
    """-> (count position, first element position, end position, [ids]) of the vector stored under `key`, or None.
    Candidates are validated by walking every element; exactly one valid candidate is required."""
    pat = struct.pack('<I', len(key)) + key; found = []
    for m in re.finditer(re.escape(pat), payload):
        p = m.end()
        try:
            count = u32(payload, p); flag = payload[p + 4]; tl = u32(payload, p + 5)
            if flag != 1 or tl > 64 or count > 100000: continue
            tn = payload[p + 9:p + 9 + tl]
            if not tn.isalpha(): continue
            q = p + 9 + tl; first = q; ids = []
            for _ in range(count):
                n = u32(payload, q); s = payload[q + 4:q + 4 + n]
                if n == 0 or n > 128 or not all(32 <= c < 127 for c in s): raise ValueError
                ids.append(s.decode('ascii')); q += 4 + n
            found.append((p, first, q, ids))
        except (ValueError, struct.error, IndexError): continue
    if len(found) > 1: raise SystemExit('ambiguous: %d candidate lists for %s' % (len(found), key.decode()))
    return found[0] if found else None

def enc(ids): return b''.join(struct.pack('<I', len(i)) + i.encode('ascii') for i in ids)

def set_vec(payload, key, ids):
    p, first, end, old = find_vec(payload, key)
    new = payload[:p] + struct.pack('<I', len(ids)) + payload[p + 4:first] + enc(ids) + payload[end:]
    assert find_vec(new, key)[3] == list(ids)
    return new

def edit(data, add, remove, mark_new):
    prefix, blocks, used = split(data)
    hit = [n for n, (t, p) in enumerate(blocks) if find_vec(p, b'UnlockData')]
    if len(hit) != 1: raise SystemExit('could not find the UnlockData list in this save (found in %d blocks)' % len(hit))
    n = hit[0]; payload = blocks[n][1]
    for key in (b'UnlockData', b'NewList'):
        v = find_vec(payload, key)
        if v is None:
            if key == b'NewList' and not (mark_new or remove): continue
            raise SystemExit('this save has no %s list' % key.decode())
        cur = v[3]; new = [i for i in cur if i not in remove]
        if key == b'UnlockData' or mark_new: new += [i for i in add if i not in new]
        if new != cur: payload = set_vec(payload, key, new)
    blocks[n] = (blocks[n][0], payload)
    return join(prefix, blocks, len(data)), n

def outpath(inp, out, tag):
    if tag or os.path.isdir(out) or out.endswith(('/', '\\')):
        if not tag: raise SystemExit('give --tag when OUT is a folder (file becomes %s_<tag>)' % os.path.basename(inp))
        os.makedirs(out, exist_ok=True); return os.path.join(out, '%s_%s' % (os.path.basename(inp), tag))
    if os.path.abspath(out) == os.path.abspath(inp): raise SystemExit('refusing to overwrite the input save')
    return out

def show(path):
    data = open(path, 'rb').read(); prefix, blocks, used = split(data)
    print('%s: %d bytes, %d blocks, %d bytes used' % (os.path.basename(path), len(data), len(blocks), used))
    for n, (t, p) in enumerate(blocks): print('  block %d: type %2d, %6d bytes' % (n, t, len(p)))
    for n, (t, p) in enumerate(blocks):
        ranks = []
        for m in re.finditer(re.escape(struct.pack('<I', 9) + b'SettingID'), p):
            q = m.end(); ln = u32(p, q); sid = p[q + 4:q + 4 + ln].decode('latin1', 'replace')
            r = p.find(struct.pack('<I', 9) + b'RankIndex', q, q + 600)
            if r > 0: ranks.append((sid, u32(p, r + 13)))
        if ranks:
            print('\nhabitat rank index (SettingID: RankIndex)  [read by pattern]:')
            for sid, ri in ranks: print('   %-28s %d' % (sid, ri))
        v = find_vec(p, b'UnlockData')
        if v:
            nl = find_vec(p, b'NewList'); ids = v[3]
            slots = sorted(i for i in ids if re.search(r'Slot\d+$', i))
            print('\nUnlockData: %d ids; NewList: %d ids' % (len(ids), len(nl[3]) if nl else 0))
            print('unlocked slots (%d):' % len(slots), ', '.join(slots) or '(none)')

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    s = sub.add_parser('show'); s.add_argument('save')
    for c in ('slots', 'unlock', 'lock'):
        s = sub.add_parser(c); s.add_argument('save'); s.add_argument('out'); s.add_argument('--tag'); s.add_argument('--new', action='store_true')
        if c == 'slots':
            s.add_argument('--habitat', help='comma separated slot id prefixes, e.g. BigCatSavanna,BearForest'); s.add_argument('--all', action='store_true', help='all %d habitats' % len(HABITATS))
            g = s.add_mutually_exclusive_group(); g.add_argument('--no-nurseries', action='store_true', help='with --all: main enclosures only'); g.add_argument('--only-nurseries', action='store_true', help='with --all: nurseries only')
            s.add_argument('--count', type=int, required=True)
        else: s.add_argument('--ids', required=True)
    a = ap.parse_args()
    if a.cmd == 'show': show(a.save); return
    data = open(a.save, 'rb').read()
    if a.cmd == 'slots':
        if a.count < 2: raise SystemExit('--count must be at least 2 (slot 1 is always available)')
        pool = [h for h in HABITATS if not (a.no_nurseries and 'nursery' in h.lower()) and not (a.only_nurseries and 'nursery' not in h.lower())]
        hs = pool if a.all else [h.strip() for h in (a.habitat or '').split(',') if h.strip()]
        if not hs: raise SystemExit('give --all or --habitat NAME[,NAME...]')
        ids = ['%sSlot%d' % (h, i) for h in hs for i in range(2, a.count + 1)]
    else: ids = [i.strip() for i in a.ids.split(',') if i.strip()]
    if not ids: raise SystemExit('no ids given')
    prefix, blocks, _ = split(data); cur = [i for t, p in blocks for i in (find_vec(p, b'UnlockData') or (0, 0, 0, []))[3]]
    new, n = edit(data, [] if a.cmd == 'lock' else ids, set(ids) if a.cmd == 'lock' else set(), a.new)
    out = outpath(a.save, a.out, a.tag); open(out, 'wb').write(new)
    changed = [i for i in ids if (i in cur) == (a.cmd == 'lock')]
    print('%s: %s %d id(s)%s' % (os.path.basename(out), 'removed' if a.cmd == 'lock' else 'added to UnlockData:', len(changed), (' - ' + ', '.join(changed)) if len(changed) <= 8 else ''))
    if len(ids) - len(changed): print('   %d already %s, left as is' % (len(ids) - len(changed), 'absent' if a.cmd == 'lock' else 'unlocked'))
    print('   file size unchanged (%d bytes); only block %d changed' % (len(new), n))

if __name__ == '__main__': main()
