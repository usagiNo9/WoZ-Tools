#!/usr/bin/env python3
"""World of Zoo .dsc (BFBINARY) endian converter + parser used for verification.
   Format (all integers 32-bit): 'BFBINARY' + map body.
   map  = u32 count, count x (string key, value)         value type is implied by the engine (no tag)
   vec  = u32 count, u8 flag, string elementTypeName, count x element
   string = u32 byteLength + ASCII ; unicode string = u32 byteLength + UTF-16 ; scalars = 1/4/12/16 raw bytes
"""
import struct,re,sys
sys.setrecursionlimit(100000)
IDENT=re.compile(rb'^[A-Za-z0-9_.\-]+$')
class Fail(Exception): pass
VEC_ELEM={b'propertymap':'map',b'propertyvector':'vec',b'unicodestring':'wstr',b'vector3':'v3',b'vector2':'v2',b'propertypair':'pair',b'IntList':'arr4',b'FloatList':'arr4',
          b'int':'u4',b'float':'u4',b'uint':'u4',b'unsigned':'u4',b'bool':'b1',b'vector4':'v4',b'quaternion':'v4',b'color':'v4',b'matrix4':'m4',b'transform':'m4'}
END,KEY,ELEM,ANY='END','KEY','ELEM','ANY'
ARRAY_KEYS={b'VertDifs',b'VertIndices',b'PlayerIDList'}   # keys whose value is [u32 count][count x 4 bytes] (PlayerIDList: seen in scripts/settingmodebase.dsc, Crocodile nursery)
PRIOR=None   # {key: set(kinds)} learned from PC files; used to prune ambiguous value types

def kind_of(t):
    k=t[0]
    if k in ('c','f3'): return 'c%d'%len(t[1])
    return k

def rev4(b): return b''.join(b[i:i+4][::-1] for i in range(0,len(b),4))
def rev2(b): return b''.join(b[i:i+2][::-1] for i in range(0,len(b),2))
def rope(a,b): return (a,b)
def flat(r):
    out=[];st=[r]
    while st:
        x=st.pop()
        if isinstance(x,(bytes,bytearray)): out.append(bytes(x))
        else: st.append(x[1]); st.append(x[0])
    return b''.join(out)
def chain_list(c):
    items=[]
    while c: items.append(c[1]); c=c[0]
    items.reverse(); return items
def dedup(lst):
    seen={}
    for t in lst: seen.setdefault(t[0],t)
    return list(seen.values())

class Conv:
    """src = '>' (Wii) or '<' (PC). Produces bytes in the opposite endianness plus a canonical tree."""
    def __init__(s,b,src,nodup=False,use_prior=True,loose=False):
        s.loose=loose; s.use_prior=use_prior; s.nodup=nodup; s.b=b; s.src=src; s.dst='<' if src=='>' else '>'; s.memo={}
    def u32(s,p): return struct.unpack_from(s.src+'I',s.b,p)[0] if p+4<=len(s.b) else None
    def p32(s,v): return struct.pack(s.dst+'I',v)
    def sw(s,p,n):
        raw=s.b[p:p+n]; return rev4(raw)           # bytes in destination order
    def norm4(s,raw): return raw if s.src=='>' else rev4(raw)   # canonical = big-endian
    def key_at(s,p):
        L=s.u32(p)
        if L is None or not 1<=L<=100 or p+4+L>len(s.b): return None
        k=s.b[p+4:p+4+L]; return k if IDENT.match(k) else None
    def ok(s,q,f):
        if f==END: return q==len(s.b)
        if f==KEY: return s.key_at(q) is not None
        if f==ELEM:
            n=s.u32(q); return n is not None and (n==0 or s.key_at(q+4) is not None)
        return True
    def memo_call(s,name,p,f,fn):
        k=(name,p,f)
        if k not in s.memo: s.memo[k]=list(fn(p,f))
        return s.memo[k]
    # primitives -> (q, out, tree)
    def str8(s,p):
        L=s.u32(p)
        if L is None or L>100000 or p+4+L>len(s.b): return
        d=s.b[p+4:p+4+L]
        if L and not all(32<=c<127 or c in (9,10,13) for c in d): return
        yield p+4+L, s.p32(L)+d, ('s',d)
    def wstr(s,p):
        L=s.u32(p)
        if L is None or L%2 or L>200000 or p+4+L>len(s.b): return
        d=s.b[p+4:p+4+L]
        if L and d[0 if s.src=='>' else 1]!=0: return
        yield p+4+L, s.p32(L)+rev2(d), ('w',d if s.src=='>' else rev2(d))
    def b1(s,p):
        if p<len(s.b) and s.b[p] in (0,1): yield p+1,s.b[p:p+1],('b',s.b[p:p+1])
    def u4(s,p):
        if p+4<=len(s.b): yield p+4,s.sw(p,4),('u',s.norm4(s.b[p:p+4]))
    def c16(s,p):
        if p+16<=len(s.b): yield p+16,s.sw(p,16),('c',s.norm4(s.b[p:p+16]))
    def arr4(s,p):
        n=s.u32(p)
        if n is None or n*4>len(s.b)-p-4: return
        yield p+4+4*n, s.p32(n)+rev4(s.b[p+4:p+4+4*n]), ('a4',s.b[p+4:p+4+4*n] if s.src=='>' else rev4(s.b[p+4:p+4+4*n]))
    def v2(s,p):
        if p+8<=len(s.b): yield p+8,s.sw(p,8),('c',s.norm4(s.b[p:p+8]))
    def v4(s,p):
        if p+16<=len(s.b): yield p+16,s.sw(p,16),('c',s.norm4(s.b[p:p+16]))
    def m4(s,p):
        if p+64<=len(s.b): yield p+64,s.sw(p,64),('c',s.norm4(s.b[p:p+64]))   # 4x4 float transform
    def v3(s,p):
        if p+12<=len(s.b): yield p+12,s.sw(p,12),('f3',s.norm4(s.b[p:p+12]))
    def typed(s,q,tn,f):
        """one value whose type is named by tn (as used for vector elements)"""
        kind=VEC_ELEM.get(tn,'tok')
        if kind=='map': return s.map_(q,f)
        if kind=='vec': return s.vec(q,f)
        if kind=='wstr': return s.wstr(q)
        if kind=='v2': return s.v2(q)
        if kind=='v3': return s.v3(q)
        if kind=='v4': return s.v4(q)
        if kind=='m4': return s.m4(q)
        if kind=='arr4': return s.arr4(q)
        if kind=='u4': return s.u4(q)
        if kind=='b1': return s.b1(q)
        return (list(s.str8(q))+list(s.wstr(q))+list(s.map_(q,f))) or list(s.u4(q))
    def pair(s,q,f):
        """propertypair element: [type name][value of that type] then [key][value] (like one map entry)"""
        out=[]
        for q1,o1,_ in s.str8(q):
            tn=o1[4:]
            if not IDENT.match(tn): continue
            for q2,o2,t2 in s.typed(q1,tn,KEY):
                k=s.key_at(q2)
                if k is None: continue
                q3=q2+4+len(k)
                for q4,o4,t4 in s.value(q3,f,k):
                    out.append((q4,rope(rope(rope(o1,o2),s.p32(len(k))+k),o4),('pair',tn,t2,k,t4)))
        return dedup(out)
    def map_(s,p,f): return s.memo_call('map',p,f,s._map)
    def _map(s,p,f):
        n=s.u32(p)
        if n is None or n>5000: return
        cur=[(p+4,s.p32(n),None,frozenset())]
        for i in range(n):
            last=(i==n-1); nxt=[]; fl=f if last else KEY
            for q,out,tr,ks in cur:
                k=s.key_at(q)
                if k is None or (s.nodup and k in ks): continue      # a map never repeats a key
                q2=q+4+len(k); o2=rope(out,s.p32(len(k))+k); ks2=ks|{k}
                for q3,o3,t3 in s.value(q2,fl,k): nxt.append((q3,rope(o2,o3),(tr,(k,t3)),ks2))
            cur=dedup(nxt)
            if not cur: return
        for q,o,tr,ks in cur:
            if s.ok(q,f): yield q,o,('m',tr)
    def vec(s,p,f): return s.memo_call('vec',p,f,s._vec)
    def _vec(s,p,f):
        # [u32 count][u8 flag] ; flag 1 = homogeneous: one type-name string, then elements
        #                       ; flag 0 = each element is preceded by its own type-name string
        n=s.u32(p)
        if n is None or n>100000 or p+5>len(s.b) or s.b[p+4] not in (0,1): return
        flag=s.b[p+4]; head=s.p32(n)+s.b[p+4:p+5]
        if n*(1 if flag else 8)>len(s.b)-p: return
        if flag:
            starts=[]
            for q,o,_ in s.str8(p+5):
                if IDENT.match(o[4:]): starts.append((q,head+o,o[4:]))
        else: starts=[(p+5,head,None)]
        for q0,h0,tn0 in starts:
            cur=[(q0,h0,None)]
            for i in range(n):
                last=(i==n-1); nxt=[]
                for q1,o1,t1 in cur:
                    tn=tn0; qe=q1; oe=o1
                    if tn is None:                      # heterogeneous: read this element's type name
                        got=list(s.str8(q1))
                        if not got or not IDENT.match(got[0][1][4:]): continue
                        qe=got[0][0]; oe=rope(o1,got[0][1]); tn=got[0][1][4:]
                    kind=VEC_ELEM.get(tn,'tok')
                    if kind=='pair': it=s.pair(qe,f if last else KEY)
                    elif kind=='map': it=s.map_(qe,f if last else (ELEM if flag else KEY))
                    elif kind=='vec': it=s.vec(qe,f if last else ANY)
                    elif kind=='wstr': it=s.wstr(qe)
                    elif kind=='v3': it=s.v3(qe)
                    elif kind=='v2': it=s.v2(qe)
                    elif kind=='v4': it=s.v4(qe)
                    elif kind=='m4': it=s.m4(qe)
                    elif kind=='u4': it=s.u4(qe)
                    elif kind=='arr4': it=s.arr4(qe)
                    elif kind=='b1': it=s.b1(qe)
                    else: it=(list(s.str8(qe))+list(s.wstr(qe))+list(s.map_(qe,f if last else (ELEM if flag else KEY)))) or list(s.u4(qe))   # string tokens / enums, resource paths (wide), or structs (XMLRef)
                    for q2,o2,t2 in it: nxt.append((q2,rope(oe,o2),(t1,(tn,t2))))
                cur=dedup(nxt)
                if not cur: break
            else:
                for q1,o1,t1 in cur:
                    if s.ok(q1,f): yield q1,o1,('v',tn0,t1)
    def value(s,p,f,key=None):
        res=list(s.vec(p,f))
        for fn in (s.str8,s.wstr,s.u4,s.b1,s.v2,s.v3,s.v4,s.m4):
            for t in fn(p):
                if s.ok(t[0],f): res.append(t)
        res+=list(s.map_(p,f))
        if key in ARRAY_KEYS or (s.loose and (PRIOR is None or key not in PRIOR)): res+=[t for t in s.arr4(p) if s.ok(t[0],f)]   # loose = last-resort pass: unknown keys may hold a bare [count][count x 4 bytes] array
        # a fixed-size numeric blob must not swallow something that looks like a key (guards against spurious 8/12/16/64-byte matches)
        res=[t for t in res if not (t[2][0] in ('c','f3') and any(s.key_at(o) is not None for o in range(p+1,t[0]-4)))]
        if s.use_prior and PRIOR is not None and key in PRIOR:
            keep=[t for t in res if kind_of(t[2]) in PRIOR[key]]
            if keep: res=keep
        return dedup(res)

def parse(b,src):
    if b[:8]!=b'BFBINARY': raise Fail('bad magic')
    res=Conv(b,src).map_(8,END)
    if not res and PRIOR is not None: res=Conv(b,src,use_prior=False).map_(8,END)   # prior too strict for this file
    if not res: res=Conv(b,src,use_prior=False,loose=True).map_(8,END)   # last resort: allow bare counted arrays for keys never seen in PC data
    if not res: raise Fail('could not parse')
    q,out,tree=res[0]
    return b'BFBINARY'+flat(out), tree

def convert(b,src='>'):
    return parse(b,src)[0]

def canon(t):
    k=t[0]
    if k=='m': return ('m',tuple(sorted(((kk,canon(v)) for kk,v in chain_list(t[1])),key=repr)))
    if k=='v': return ('v',t[1],tuple((tn,canon(sub)) for tn,sub in chain_list(t[2])))
    if k=='pair': return ('pair',t[1],canon(t[2]),t[3],canon(t[4]))
    return t


# ---------- tree -> bytes (little-endian target) and key-order handling ----------
def _p(v): return struct.pack('<I',v)
def serialize(t):
    """Serialize a tree produced by parse() (canonical big-endian leaves) to little-endian bytes."""
    out=bytearray()
    def w(t):
        k=t[0]
        if k=='s': out.extend(_p(len(t[1]))); out.extend(t[1])
        elif k=='w': out.extend(_p(len(t[1]))); out.extend(rev2(t[1]))
        elif k=='b': out.extend(t[1])
        elif k in ('u','c','f3'): out.extend(rev4(t[1]))
        elif k=='a4': out.extend(_p(len(t[1])//4)); out.extend(rev4(t[1]))
        elif k=='pair':
            _,tn1,t2,key,t4=t
            out.extend(_p(len(tn1))); out.extend(tn1); w(t2); out.extend(_p(len(key))); out.extend(key); w(t4)
        elif k=='m':
            ents=chain_list(t[1]); out.extend(_p(len(ents)))
            for key,val in ents: out.extend(_p(len(key))); out.extend(key); w(val)
        elif k=='v':
            els=chain_list(t[2]); out.extend(_p(len(els)))
            if t[1] is None: out.extend(b'\x00')
            else: out.extend(b'\x01'); out.extend(_p(len(t[1]))); out.extend(t[1])
            for tn,sub in els:
                if t[1] is None: out.extend(_p(len(tn))); out.extend(tn)
                w(sub)
        else: raise Fail('cannot serialize '+str(k))
    w(t); return b'BFBINARY'+bytes(out)

def _collect(t,acc):
    if t[0]=='m':
        ents=chain_list(t[1]); acc.append(tuple(k for k,_ in ents))
        for _,v in ents: _collect(v,acc)
    elif t[0]=='v':
        for _,sub in chain_list(t[2]): _collect(sub,acc)
    elif t[0]=='pair':
        _collect(t[2],acc); _collect(t[4],acc)

def learn_prior(trees,min_share=0.2):
    """key -> set of value kinds seen for that key in (trusted) PC trees; rare kinds are treated as noise."""
    import collections
    cnt=collections.defaultdict(collections.Counter)
    def walk(t):
        if t[0]=='m':
            for k,v in chain_list(t[1]): cnt[k][kind_of(v)]+=1; walk(v)
        elif t[0]=='v':
            for _,sub in chain_list(t[2]): walk(sub)
        elif t[0]=='pair':
            cnt[t[3]][kind_of(t[4])]+=1; walk(t[2]); walk(t[4])
    for t in trees: walk(t)
    return {k:{x for x,c in v.items() if c>=min_share*max(v.values())} for k,v in cnt.items()}

def build_table(trees):
    """trees: parsed PC (little-endian) trees. Returns {'sets':{frozenset:order}, 'rank':{key:int}}."""
    orders=[]
    for t in trees: _collect(t,orders)
    sets={}
    for o in orders: sets[frozenset(o)]=o
    # global rank from pairwise precedence (topological order)
    import collections
    g=collections.defaultdict(set); keys=set(); indeg=collections.Counter()
    for o in sets.values():
        keys.update(o)
        for a in range(len(o)):
            for b in range(a+1,len(o)):
                if o[b] not in g[o[a]]: g[o[a]].add(o[b]); indeg[o[b]]+=1
    q=sorted(k for k in keys if indeg[k]==0); rank={}
    while q:
        a=q.pop(0); rank[a]=len(rank)
        for b in sorted(g[a]):
            indeg[b]-=1
            if indeg[b]==0: q.append(b)
    for k in keys: rank.setdefault(k,len(rank))   # (only reached if sources conflict)
    return dict(sets=sets,rank=rank)

def reorder(t,table,stats=None):
    """Return tree with every map's entries put into the PC order given by table."""
    k=t[0]
    if k=='m':
        ents=[(key,reorder(v,table,stats)) for key,v in chain_list(t[1])]
        ks=frozenset(key for key,_ in ents)
        if ks in table['sets']:
            order={key:i for i,key in enumerate(table['sets'][ks])}
            ents.sort(key=lambda e:order[e[0]]); how='exact'
        elif all(key in table['rank'] for key,_ in ents):
            ents.sort(key=lambda e:table['rank'][e[0]]); how='ranked'
        else: how='unknown'
        if stats is not None: stats[how]=stats.get(how,0)+1
        c=None
        for e in ents: c=(c,e)
        return ('m',c)
    if k=='v':
        c=None
        for tn,sub in chain_list(t[2]): c=(c,(tn,reorder(sub,table,stats)))
        return ('v',t[1],c)
    if k=='pair': return ('pair',t[1],reorder(t[2],table,stats),t[3],reorder(t[4],table,stats))
    return t


# ---- built-in knowledge of which value kind each key holds, learned from the PC files (disambiguates nesting) ----
_PRIOR_B64 = """
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
"""
def _default_prior():
    import json, zlib, base64
    return {k.encode('latin1'): set(v) for k, v in json.loads(zlib.decompress(base64.b64decode(_PRIOR_B64))).items()}
PRIOR = _default_prior()


def convert_checked(b):
    """Wii->PC with a self-check: re-parse the output as little-endian and require the same content tree."""
    out,tree=parse(b,'>')
    out2,tree2=parse(out,'<')
    if canon(tree)!=canon(tree2) or len(out)!=len(b):
        raise Fail('self-check failed (output does not re-parse to the same content)')
    return out

BF_EXT=('.dsc','.pmp','.xml')
RLET_EXT=('.rlet',)
def is_bfbinary(name,data):
    return name.lower().endswith(tuple(e.encode() for e in BF_EXT)) and data[:8]==b'BFBINARY'

def _read_pkg_entries(fn):
    """Minimal World of Zoo .pkg reader (no other module needed). Yields (path, data, endian)."""
    import zlib
    d=open(fn,'rb').read()
    e='>' if struct.unpack_from('>I',d,0)[0]==1 else '<'
    u=lambda o:struct.unpack_from(e+'I',d,o)[0]
    S=8+40*u(8); n=u(12); pos=S+n*288+8      # header = 8 bytes + 40 per resource type
    for i in range(n):
        o=S+i*288
        name=d[o+12:o+272].split(b'\0')[0]
        csz=u(o+272); data=zlib.decompress(d[pos:pos+csz]); pos+=csz
        yield name,data,e

def rlet_swap(w,src='>'):
    """.rlet = run-length coded 8-bit image: 11-word header (word 5 = header size), then a byte stream where a
    0x00 or 0xFF byte is a run marker followed by a 32-bit run length; every other byte is a literal sample."""
    u=lambda o:struct.unpack_from(src+'I',w,o)[0]
    hdr=u(20)
    if hdr<24 or hdr>len(w) or hdr%4: raise Fail('not an rlet file')
    out=bytearray(b''.join(w[i:i+4][::-1] for i in range(0,hdr,4)))
    i=hdr; n=len(w)
    while i<n:
        b=w[i]
        if b in (0,255):
            if i+5>n: raise Fail('truncated run')
            out.append(b); out+=w[i+1:i+5][::-1]; i+=5
        else: out.append(b); i+=1
    return bytes(out)

def _load_reference(paths):
    """Raw bytes of PC reference .dsc files from PC .pkg files and/or folders / single files."""
    import os
    blobs=[]
    for p in paths:
        if os.path.isdir(p):
            for r,_,fs in os.walk(p):
                for f in fs:
                    if f.lower().endswith(BF_EXT):
                        d=open(os.path.join(r,f),'rb').read()
                        if d[:8]==b'BFBINARY': blobs.append(d)
        elif p.lower().endswith('.pkg'):
            for name,data,endian in _read_pkg_entries(p):
                if endian!='<': raise Fail(p+' is not a PC (little-endian) package')
                if is_bfbinary(name,data): blobs.append(data)
        else: blobs.append(open(p,'rb').read())
    return blobs

def learn_reference(blobs,passes=3):
    """Parse the PC reference files, learning key->value-kind priors (which disambiguate nesting) and the PC entry order."""
    global PRIOR
    PRIOR=None
    trees=[parse(b,'<')[1] for b in blobs]
    for _ in range(passes):
        PRIOR=learn_prior(trees)
        trees=[parse(b,'<')[1] for b in blobs]
    return build_table(trees)

def _main():
    import os,argparse,json
    ap=argparse.ArgumentParser(description='Convert World of Zoo data files from Wii (big-endian) to PC (little-endian): binary .dsc/.pmp/.xml property files and .rlet images. '
        'Map entries are written in the PC engine\'s order, learned from PC reference files.')
    ap.add_argument('src',help='a .dsc/.pmp/.xml file, or a folder (every BFBINARY .dsc/.pmp/.xml inside is converted; text files are left alone)')
    ap.add_argument('dst',help='output file or folder (may equal src to convert in place)')
    ap.add_argument('--ref',nargs='+',default=[],help='PC reference: PC .pkg files and/or folders of PC .dsc files (more animals = better coverage)')
    ap.add_argument('--table',help='load/save the learned order table (JSON); loaded if it exists, otherwise written after building from --ref')
    a=ap.parse_args()
    table=None
    if a.table and os.path.exists(a.table) and not a.ref:
        j=json.load(open(a.table))
        table=dict(sets={frozenset(k.encode('latin1') for k in o):tuple(k.encode('latin1') for k in o) for o in j['sets']},
                   rank={k.encode('latin1'):v for k,v in j['rank'].items()})
        global PRIOR
        PRIOR={k.encode('latin1'):set(v) for k,v in j.get('prior',{}).items()} or None
    elif a.ref:
        table=learn_reference(_load_reference(a.ref))
        print('learned PC order from reference: %d key sets, %d distinct keys'%(len(table['sets']),len(table['rank'])))
        if a.table:
            json.dump(dict(sets=[[k.decode('latin1') for k in o] for o in table['sets'].values()],
                           rank={k.decode('latin1'):v for k,v in table['rank'].items()},
                           prior={k.decode('latin1'):sorted(v) for k,v in PRIOR.items()}),open(a.table,'w'))
    else:
        print('note: no --ref/--table given: entries keep their Wii order (tested fine in the PC game).')
    jobs=[]
    if os.path.isdir(a.src):
        for r,_,fs in os.walk(a.src):
            for f in fs:
                p=os.path.join(r,f)
                if f.lower().endswith(RLET_EXT): jobs.append((p,os.path.join(a.dst,os.path.relpath(p,a.src))))
                elif f.lower().endswith(BF_EXT) and open(p,'rb').read(8)==b'BFBINARY': jobs.append((p,os.path.join(a.dst,os.path.relpath(p,a.src))))
    else: jobs=[(a.src,a.dst)]
    ok=bad=0; unsure=[]
    for sp,dp in jobs:
        b=open(sp,'rb').read()
        if sp.lower().endswith(RLET_EXT):
            try:
                out=rlet_swap(b)
                if rlet_swap(out,'<')!=b: raise Fail('self-check failed')
            except Exception as e: bad+=1; print('FAILED',sp,'-',e); continue
            os.makedirs(os.path.dirname(os.path.abspath(dp)),exist_ok=True); open(dp,'wb').write(out); ok+=1; continue
        try:
            out,tree=parse(b,'>'); st={}
            if table: tree=reorder(tree,table,st); out=serialize(tree)
            _,t2=parse(out,'<')
            if canon(t2)!=canon(tree) or len(out)!=len(b): raise Fail('self-check failed (output does not re-parse to the same content)')
        except Exception as e:
            bad+=1; print('FAILED',sp,'-',e); continue
        if table and st.get('unknown'): unsure.append((sp,st['unknown']))
        os.makedirs(os.path.dirname(os.path.abspath(dp)),exist_ok=True)
        open(dp,'wb').write(out); ok+=1
    print('converted %d file(s), %d failed'%(ok,bad))
    if unsure:
        print('%d file(s) contain maps whose key combination is not in the reference (kept in Wii order - may misbehave):'%len(unsure))
        for p,n in unsure[:40]: print('   %s (%d map(s))'%(p,n))

if __name__=='__main__':
    _main()
