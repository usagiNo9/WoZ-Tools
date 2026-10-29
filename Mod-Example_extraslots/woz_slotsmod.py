#!/usr/bin/env python3
"""woz_slotsmod.py - change how many animals a World of Zoo (PC) habitat can hold.

TWO things decide the number of animal slots of a habitat, and BOTH must agree:
  1. SettingMaxAnimalSlotCount   in  environments/<habitat>/data/<habitat>setting.xml   (inside Loading4.pkg)
        the habitat's maximum number of slots (shipped values: Big Cat 3, Bear 3, Gazelle 4, Koala 4, Penguin pool 4 ...).
  2. AnimalSlotList              in  economy/animalslots/<habitat>slots.xml            (e.g. inside <Animal>Editor.pkg)
        one entry per slot: UnlockableID (e.g. BigCatSavannaSlot2), optional UnlockRequirement (the keeper-rank achievement
        that unlocks it, e.g. JuniorBigCatKeeper) and ParentID (e.g. BigCatSavannaSlots). No requirement = always available.
Changing only the slot list, or only the maximum, shows nothing new in game.  (Both files are BFBINARY; all string lengths and
the 4-byte count are written by this script, so a hand-edit typo - a wrong length prefix crashes the game - cannot happen.)

  python woz_slotsmod.py show   <file.xml | package.pkg>        slots file, or every slot file / maximum found in a package
  python woz_slotsmod.py maxslots IN.pkg OUTDIR --habitat BigCatSavanna --count 6 --tag maxslots6
  python woz_slotsmod.py slots    IN.pkg OUTDIR --habitat BigCatSavanna --family BigCat --count 6 --tag slots6free --free
  python woz_slotsmod.py all    GAMEFOLDER OUTDIR --count 6 --tag 6slots [--no-nurseries | --only-nurseries] [--free] [--ladder ...] [--recursive]
        EVERY habitat of EVERY package in GAMEFOLDER at once: all slot files (economy/animalslots/*) get COUNT slots and all
        SettingMaxAnimalSlotCount values become COUNT. Slot id prefix, parent and animal name are read from each existing file.
        --no-nurseries changes only the main enclosures (11 habitats); --only-nurseries only the 11 nurseries. Nursery files are
        recognised by 'nursery' in their path (nurseryplaypen*, nurserypaddock*, nurserypool ...).
        Put into GAMEFOLDER a copy of: Loading3Transient.pkg, Loading4.pkg and every <Animal>Editor.pkg / habitat package you have.
  python woz_slotsmod.py apply --setting-pkg Loading4.pkg --slots-pkg BigCatAnimalEditor.pkg --outdir OUT \\
                          --habitat BigCatSavanna --family BigCat --count 6 --tag 6slots [--free | --ladder Junior,Senior,...]

Output files are named  <package>_<tag>.pkg  (e.g. Loading4_6slots.pkg) so tests can be told apart without a checksum.
Slot ids are  <habitat>Slot1..N  with parent  <habitat>Slots.  Slot 1 never needs a rank.  Slots 2..N use --ladder in order
(default: Junior,Senior,Head,Master,Whisperer -> JuniorBigCatKeeper, SeniorBigCatKeeper, ...), or no requirement with --free.
Use --slots "ID[:REQ],ID[:REQ],..." instead of --habitat/--family/--count to spell the slots out yourself.
"""
import struct, sys, os, argparse, re

HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import wozPKG

DEFAULT_LADDER = 'Junior,Senior,Head,Master,Whisperer'
MAXKEY = b'SettingMaxAnimalSlotCount'

# ---------------------------------------------------------------- slots file (economy/animalslots/*.xml)
def _s(b): return struct.pack('<I', len(b)) + b

def build_slots(slots, parent):
    """slots = [(unlockableID, requirement or None)] -> BFBINARY bytes (PC)"""
    out = bytearray(b'BFBINARY' + struct.pack('<I', 1)); out += _s(b'AnimalSlotList')
    out += struct.pack('<IB', len(slots), 1) + _s(b'propertymap')
    for uid, req in slots:
        out += struct.pack('<I', 3 if req else 2) + _s(b'UnlockableID') + _s(uid.encode())
        if req: out += _s(b'UnlockRequirement') + _s(req.encode())
        out += _s(b'ParentID') + _s(parent.encode())
    return bytes(out)

def parse_slots(data):
    """-> ([(uid, req, parent)], endian); ValueError if this is not a plain slot list"""
    if data[:8] != b'BFBINARY': raise ValueError('not a BFBINARY file')
    E = '<' if struct.unpack_from('<I', data, 8)[0] < 0x10000 else '>'; p = 12
    def u32():
        nonlocal p; v = struct.unpack_from(E + 'I', data, p)[0]; p += 4; return v
    def string():
        nonlocal p; n = u32(); s = data[p:p + n].decode('latin1'); p += n; return s
    if struct.unpack_from(E + 'I', data, 8)[0] != 1 or string() != 'AnimalSlotList': raise ValueError('not an AnimalSlotList file')
    n = u32(); flag = data[p]; p += 1
    if flag != 1 or string() != 'propertymap': raise ValueError('unexpected vector header')
    res = []
    for _ in range(n):
        d = {}
        for _ in range(u32()): k = string(); d[k] = string()
        res.append((d.get('UnlockableID'), d.get('UnlockRequirement'), d.get('ParentID')))
    if p != len(data): raise ValueError('%d unparsed bytes at the end' % (len(data) - p))
    return res, E

def auto_slots(habitat, family, count, ladder, free):
    if count < 1: raise SystemExit('--count must be at least 1')
    ranks = [r.strip() for r in ladder.split(',') if r.strip()]
    if not free and count - 1 > len(ranks): raise SystemExit('%d slots need %d ranks in --ladder (it has %d); use --free or a longer ladder' % (count, count - 1, len(ranks)))
    slots = []
    for i in range(1, count + 1):
        req = None if (i == 1 or free) else '%s%sKeeper' % (ranks[i - 2], family)
        slots.append(('%sSlot%d' % (habitat, i), req))
    return slots, habitat + 'Slots'

def explicit_slots(arg, parent):
    out = []
    for item in arg.split(','):
        item = item.strip()
        if item: uid, _, req = item.partition(':'); out.append((uid.strip(), req.strip() or None))
    if not out or len(set(u for u, _ in out)) != len(out): raise SystemExit('--slots is empty or has a duplicate UnlockableID')
    return out, parent

# ---------------------------------------------------------------- habitat setting file (SettingMaxAnimalSlotCount)
def find_max(data):
    pat = struct.pack('<I', len(MAXKEY)) + MAXKEY
    hits = [m.end() for m in re.finditer(re.escape(pat), data)]
    if len(hits) != 1: raise ValueError('expected exactly one SettingMaxAnimalSlotCount, found %d' % len(hits))
    return hits[0], struct.unpack_from('<I', data, hits[0])[0]

def set_max(data, count):
    if not 1 <= count <= 64: raise SystemExit('--count must be between 1 and 64')
    pos, old = find_max(data)
    if not 1 <= old <= 64: raise ValueError('current value %d looks wrong; refusing to patch' % old)
    new = data[:pos] + struct.pack('<I', count) + data[pos + 4:]
    assert len(new) == len(data) and sum(a != b for a, b in zip(data, new)) <= 4
    try:                                                    # structural double check with the property-file parser when available
        import wozDSC
        _, tree = wozDSC.parse(new, '<'); assert wozDSC.serialize(tree) == new
    except ImportError: pass
    return new, old

# ---------------------------------------------------------------- packages
def load(path):
    d, e, ents = wozPKG.read_pkg(path)
    if e != '<': raise SystemExit('%s is not a PC (little-endian) package' % path)
    return d, e, ents
def name(x): return x['pathbuf'].split(b'\0')[0].decode('latin1')
def entry(ents, path):
    hit = [x for x in ents if name(x).lower() == path.lower()]
    if len(hit) != 1: raise SystemExit('entry %r not found (or ambiguous)' % path)
    return hit[0]
def write_pkg(d, e, ents, out):
    open(out, 'wb').write(wozPKG.build_pkg(d[:wozPKG.header_size(d, e)], ents, e, level=6))
def outname(pkg, outdir, tag):
    if not tag: raise SystemExit('--tag is required (it becomes part of the file name: <package>_<tag>.pkg)')
    os.makedirs(outdir, exist_ok=True)
    stem = re.sub(r'_(PC|Wii)$', '', os.path.splitext(os.path.basename(pkg))[0], flags=re.I)     # BigCatAnimalEditor_PC.pkg -> BigCatAnimalEditor
    return os.path.join(outdir, '%s_%s.pkg' % (stem, tag))

def do_max(pkg, outdir, tag, habitat, count, entry_path=None):
    d, e, ents = load(pkg); h = habitat.lower()
    x = entry(ents, entry_path or 'environments/%s/data/%ssetting.xml' % (h, h))
    x['data'], old = set_max(x['data'], count); x.pop('blk', None)
    out = outname(pkg, outdir, tag); write_pkg(d, e, ents, out)
    print('%s: %s  SettingMaxAnimalSlotCount %d -> %d' % (os.path.basename(out), name(x), old, count)); return out

def do_slots(pkg, outdir, tag, habitat, slots, parent, entry_path=None):
    d, e, ents = load(pkg)
    x = entry(ents, entry_path or 'economy/animalslots/%sslots.xml' % habitat.lower())
    old, _ = parse_slots(x['data'])                         # refuse to touch anything that is not a slot list
    x['data'] = build_slots(slots, parent); x.pop('blk', None)
    out = outname(pkg, outdir, tag); write_pkg(d, e, ents, out)
    print('%s: %s  %d -> %d slot(s)' % (os.path.basename(out), name(x), len(old), len(slots)))
    for i, (u, r) in enumerate(slots, 1): print('   %d. %-28s %s' % (i, u, 'requires ' + r if r else 'always available'))
    return out

def do_show(path):
    if path.lower().endswith('.pkg'):
        d, e, ents = wozPKG.read_pkg(path)
        for x in ents:
            n = name(x)
            if n.startswith('economy/animalslots/') and wanted(n):
                try: res, _ = parse_slots(x['data']); print('%-62s %d slot(s): %s' % (n, len(res), ', '.join((u.replace('Slot', 'S') + (':' + r if r else '')) for u, r, _ in res)))
                except ValueError: pass
            try: pos, v = find_max(x['data']); print('%-62s SettingMaxAnimalSlotCount = %d' % (n, v))
            except ValueError: pass
    else:
        res, E = parse_slots(open(path, 'rb').read())
        print('%s endian, %d slot(s):' % ('little' if E == '<' else 'big', len(res)))
        for i, (u, r, pa) in enumerate(res, 1): print('  %d. %-30s requires: %-26s parent: %s' % (i, u, r or '(nothing, always available)', pa))


RANKS = ('Junior', 'Senior', 'Head', 'Master', 'Whisperer')

def derive(res):
    """(slot id prefix, parent id, animal family) of an existing slot list, e.g. ('BigCatSavanna','BigCatSavannaSlots','BigCat')"""
    m = re.match(r'^(.*)Slot1$', res[0][0] or '')
    if not m: return None
    fam = None
    for u, r, p in res:
        mm = re.match(r'^(?:%s)(.+)Keeper$' % '|'.join(RANKS), r or '')
        if mm: fam = mm.group(1); break
    return (m.group(1), res[0][2], fam) if fam else None

def is_nursery(path): return 'nursery' in path.lower()

def do_all(folder, outdir, count, tag, ladder, free, recursive, scope='both'):
    def wanted(path): return scope == 'both' or (is_nursery(path) == (scope == 'nurseries'))
    pkgs = []
    for root, _, files in os.walk(folder):
        pkgs += [os.path.join(root, f) for f in sorted(files) if f.lower().endswith('.pkg')]
        if not recursive: break
    if not pkgs: raise SystemExit('no .pkg files in %s' % folder)
    done = skipped = 0; ids = []
    for pk in pkgs:
        try: d, e, ents = wozPKG.read_pkg(pk)
        except Exception: continue                                   # not a normal package (language pack ...)
        if e != '<': continue
        lines = []
        for x in ents:
            n = name(x)
            if n.startswith('economy/animalslots/') and wanted(n):
                try: res, _ = parse_slots(x['data'])
                except ValueError: continue
                dv = derive(res)
                if not dv: lines.append('   SKIPPED %s (cannot derive the animal name from its requirements)' % n); skipped += 1; continue
                pre, parent, fam = dv; slots, _ = auto_slots(pre, fam, count, ladder, free)
                x['data'] = build_slots(slots, parent); x.pop('blk', None); ids += [u for u, _ in slots[1:]]
                lines.append('   slots   %-48s %d -> %d   (%sSlot2..%d, animal %s)' % (n.split('/')[-1], len(res), count, pre, count, fam))
            elif n.endswith('setting.xml') and n.startswith('environments/') and wanted(n):
                try: new, old = set_max(x['data'], count)
                except ValueError: continue
                if new != x['data']: x['data'] = new; x.pop('blk', None); lines.append('   maximum %-48s %d -> %d' % (n.split('/')[-1], old, count))
        if lines:
            out = outname(pk, outdir, tag); write_pkg(d, e, ents, out); done += 1
            print('%s  (from %s)' % (os.path.basename(out), os.path.basename(pk))); print('\n'.join(lines))
    print('\n%d package(s) written to %s%s' % (done, outdir, '; %d file(s) skipped' % skipped if skipped else ''))
    print('Copy them into the game folder (keep the originals!). Existing saves also need the new slot ids unlocked: woz_savemod.py slots ... --all')

def slot_args(a):
    if a.slots: return explicit_slots(a.slots, a.parent or (a.habitat + 'Slots' if a.habitat else None))
    if not (a.habitat and a.family and a.count): raise SystemExit('give --habitat, --family and --count (or --slots)')
    return auto_slots(a.habitat, a.family, a.count, a.ladder, a.free)

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    def common(s, need_slots):
        s.add_argument('--habitat', required=not need_slots and False); s.add_argument('--tag', required=True)
        if need_slots:
            s.add_argument('--family'); s.add_argument('--count', type=int); s.add_argument('--ladder', default=DEFAULT_LADDER)
            s.add_argument('--free', action='store_true', help='no slot needs a keeper rank'); s.add_argument('--slots'); s.add_argument('--parent')
    s = sub.add_parser('show'); s.add_argument('path')
    s = sub.add_parser('maxslots'); s.add_argument('pkg'); s.add_argument('outdir'); common(s, False); s.add_argument('--count', type=int, required=True); s.add_argument('--entry')
    s = sub.add_parser('slots'); s.add_argument('pkg'); s.add_argument('outdir'); common(s, True); s.add_argument('--entry')
    s = sub.add_parser('all'); s.add_argument('folder'); s.add_argument('outdir'); s.add_argument('--count', type=int, required=True); s.add_argument('--tag', required=True)
    s.add_argument('--ladder', default=DEFAULT_LADDER); s.add_argument('--free', action='store_true'); s.add_argument('--recursive', action='store_true')
    g = s.add_mutually_exclusive_group(); g.add_argument('--no-nurseries', action='store_true', help='main enclosures only'); g.add_argument('--only-nurseries', action='store_true')
    s = sub.add_parser('apply'); s.add_argument('--setting-pkg', required=True); s.add_argument('--slots-pkg', required=True); s.add_argument('--outdir', required=True); common(s, True)
    s.add_argument('--setting-entry'); s.add_argument('--slots-entry')
    a = ap.parse_args()
    if a.cmd == 'show': do_show(a.path)
    elif a.cmd == 'all': do_all(a.folder, a.outdir, a.count, a.tag, a.ladder, a.free, a.recursive, 'main' if a.no_nurseries else 'nurseries' if a.only_nurseries else 'both')
    elif a.cmd == 'maxslots':
        if not (a.habitat or a.entry): raise SystemExit('give --habitat (or --entry)')
        do_max(a.pkg, a.outdir, a.tag, a.habitat or '', a.count, a.entry)
    elif a.cmd == 'slots':
        slots, parent = slot_args(a); do_slots(a.pkg, a.outdir, a.tag, a.habitat or '', slots, parent, a.entry)
    else:
        slots, parent = slot_args(a)
        do_max(a.setting_pkg, a.outdir, a.tag, a.habitat, len(slots), a.setting_entry)
        do_slots(a.slots_pkg, a.outdir, a.tag, a.habitat, slots, parent, a.slots_entry)

if __name__ == '__main__': main()
