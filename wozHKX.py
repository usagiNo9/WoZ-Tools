#!/usr/bin/env python3
"""wozhkx - convert World of Zoo Wii .hkx (Havok 6.0.0 packfile) files to the PC (little-endian) format.

  python wozhkx.py in.hkx out.hkx          one file
  python wozhkx.py WiiFolder PCFolder      every .hkx inside, same relative paths

Handles behavior graphs, character data, skeletons, animations (spline-compressed animation data is stored
little-endian on both platforms and is left untouched), ragdoll/physics data and animal model files (the Blue Fang
bfFastMeshBuffer vertex buffers are rebuilt in the PC layout: positions/normals grow from 3 to 4 floats, header
and data section are re-laid out). Class layouts come from the definitions embedded in the files plus a built-in
pool learned from your BigCat/Bear/Penguin files. Packed fixed-point vertex formats (props, habitats, editor models) are expanded to the PC float layout.
Files it cannot convert are reported and skipped - never half-converted.
"""
import sys, os, struct, json, zlib, base64

# ---------------- packfile parser ----------------
class Sec: pass
def parse(d):
    en = '>' if d[0x11]==0 else '<'   # placeholder; determined below
    # layout rules at 0x10: bytesInPointer, littleEndian, reusePadding, emptyBase
    ptr,little,reuse,empty = d[0x10],d[0x11],d[0x12],d[0x13]
    en = '<' if little else '>'
    u=lambda o:struct.unpack_from(en+'I',d,o)[0]
    h=dict(magic=(u(0),u(4)),usertag=u(8),version=u(12),layout=(ptr,little,reuse,empty),nsec=struct.unpack_from(en+'i',d,0x14)[0],
           contentsSec=u(0x18),contentsOff=u(0x1c),classSec=u(0x20),classOff=u(0x24),contentsVersion=d[0x28:0x38].split(b'\0')[0],flags=u(0x38))
    secs=[]
    for s in range(h['nsec']):
        o=0x40+s*0x30; x=Sec(); x.index=s
        x.name=d[o:o+19].split(b'\0')[0].decode()
        x.abs,x.local,x.glob,x.virt,x.exp,x.imp,x.end=struct.unpack_from(en+'7I',d,o+20)
        secs.append(x)
    for x in secs:
        x.data=d[x.abs:x.abs+x.local]
        def pairs(a,b,n):
            out=[];o=x.abs+a
            while o+4*n<=x.abs+b:
                v=struct.unpack_from(en+'%dI'%n,d,o)
                if v[0]==0xffffffff: break
                out.append(v); o+=4*n
            return out
        x.lfix=pairs(x.local,x.glob,2); x.gfix=pairs(x.glob,x.virt,3); x.vfix=pairs(x.virt,x.exp,3)
    return en,h,secs

# ---------------- converter ----------------

T_BOOL,T_CHAR,T_INT8,T_UINT8,T_INT16,T_UINT16,T_INT32,T_UINT32,T_INT64,T_UINT64,T_REAL,T_VECTOR4,T_QUAT,T_MATRIX3,T_ROT,T_QST,T_MATRIX4,T_TRANSFORM,T_ZERO,T_POINTER,T_FUNCPTR,T_ARRAY,T_INPLACE,T_ENUM,T_STRUCT,T_SIMPLEARRAY,T_HOMOARRAY,T_VARIANT,T_CSTRING,T_ULONG,T_FLAGS,T_HALF,T_STRINGPTR = 1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,19,20,21,22,23,24,25,26,27,28,29,30,31,32,33
FLOATS={T_VECTOR4:16,T_QUAT:16,T_MATRIX3:48,T_ROT:48,T_QST:48,T_MATRIX4:64,T_TRANSFORM:64}
SCALAR={T_BOOL:(1,1),T_CHAR:(1,1),T_INT8:(1,1),T_UINT8:(1,1),T_INT16:(2,2),T_UINT16:(2,2),T_HALF:(2,2),T_INT32:(4,4),T_UINT32:(4,4),T_REAL:(4,4),
        T_INT64:(8,8),T_UINT64:(8,8),T_POINTER:(4,4),T_FUNCPTR:(4,4),T_CSTRING:(4,4),T_STRINGPTR:(4,4),T_ULONG:(4,4)}
class Unsupported(Exception): pass

def sw(buf,o,n):            # reverse n bytes at o
    buf[o:o+n]=buf[o:o+n][::-1]
def swn(buf,o,unit,count):
    for i in range(count): sw(buf,o+i*unit,unit)

class Classes:
    def __init__(s,en,secs):
        cls,typ=secs[0],secs[1]
        u32=lambda o:struct.unpack_from(en+'I',typ.data,o)[0]
        u16=lambda o:struct.unpack_from(en+'H',typ.data,o)[0]
        lf=dict(typ.lfix); gf={a:b for a,sec,b in typ.gfix if sec==1}
        cn=lambda off: cls.data[off:cls.data.index(b'\0',off)].decode()
        cstr=lambda o: typ.data[o:typ.data.index(b'\0',o)].decode()
        s.byoff={}; s.byname={}
        for a,si,co in typ.vfix:
            if cn(co)!='hkClass': continue
            i=dict(off=a,name=cstr(lf[a]),parent=gf.get(a+4),size=u32(a+8),nmem=u32(a+28),mem_off=lf.get(a+24),members=[])
            for k in range(i['nmem']):
                m=i['mem_off']+24*k
                i['members'].append(dict(name=cstr(lf[m]),cls=gf.get(m+4),type=typ.data[m+12],sub=typ.data[m+13],carr=u16(m+14),flags=u16(m+16),offset=u16(m+18)))
            s.byoff[a]=i; s.byname[i['name']]=i
        for i in s.byoff.values():
            i['parent_name']=s.byoff[i['parent']]['name'] if i['parent'] in s.byoff else None
            for m in i['members']: m['cls_name']=s.byoff[m['cls']]['name'] if m['cls'] in s.byoff else None
    def merge(s,other):
        """add class definitions known from another file (only names we do not have yet)"""
        for n,i in other.byname.items():
            if n not in s.byname: s.byname[n]=i
    def chain(s,name):
        out=[]; c=s.byname.get(name)
        while c is not None:
            out.append(c); c=s.byname.get(c['parent_name']) if c['parent_name'] else None
        return out[::-1]
    def members(s,name):
        ms=[]
        for c in s.chain(name): ms+=c['members']
        return ms

class Conv:
    def __init__(s,d,db=None):
        s.d=d; s.en,s.h,s.secs=parse(d)
        if s.en!='>': raise Unsupported('not a big-endian packfile')
        if s.h['layout'][0]!=4: raise Unsupported('pointer size')
        s.out=bytearray(d); s.cls=Classes(s.en,s.secs); s.seen=set(); s.warn=[]
        if db is not None: s.cls.merge(db)
    def u32(s,sec,o): return struct.unpack_from('>I',sec.data,o)[0]   # reads ORIGINAL (unswapped) data
    def run(s):
        out=s.out; secs=s.secs
        for x in secs:
            x.lfd={a:b for a,b in x.lfix}
            x.starts=sorted(set([b for a,b in x.lfix]+[a for a,_,_ in x.vfix]))
        s.swap_types()
        s.swap_data()
        # classnames signatures
        c=secs[0]; i=0
        while i+5<=len(c.data) and c.data[i+4]==9:
            sw(out,c.abs+i,4); i=c.data.index(b'\0',i+5)+1
        # fixup tables (all u32), section headers, file header
        for x in secs:
            for a,b,n in ((x.local,x.glob,2),(x.glob,x.virt,3),(x.virt,x.exp,3)):
                for o in range(x.abs+a,x.abs+b,4): sw(out,o,4)
        for k in range(s.h['nsec']):
            o=0x40+k*0x30
            for j in range(7): sw(out,o+20+4*j,4)
        for o in (0,4,8,12,0x14,0x18,0x1c,0x20,0x24,0x38): sw(out,o,4)
        out[0x10:0x14]=bytes((4,1,0,1))
        return relayout_meshes(s,out) if True else bytes(out)
    # ---- __types__ (hkClass / hkClassEnum objects; layouts decoded from the data)
    def swap_class_object(s,sec,a):
        """hkClass object (48 bytes) with its member and enum arrays, stored in __types__ or __data__"""
        out=s.out; base=sec.abs
        swn(out,base+a,4,12)
        nmem=struct.unpack_from('>I',sec.data,a+28)[0]; mo=sec.lfd.get(a+24)
        for k in range(nmem):
            m=mo+24*k
            swn(out,base+m,4,3); swn(out,base+m+14,2,3); sw(out,base+m+20,4)
        ne=struct.unpack_from('>I',sec.data,a+20)[0]; eo=sec.lfd.get(a+16)
        for k in range(ne): s.swap_enum(sec,eo+20*k)
    def swap_types(s):
        typ=s.secs[1]; cls=s.secs[0]
        cn=lambda off: cls.data[off:cls.data.index(b'\0',off)].decode()
        for a,si,co in typ.vfix:
            nm=cn(co)
            if nm=='hkClass': s.swap_class_object(typ,a)
            elif nm=='hkClassEnum': s.swap_enum(typ,a)
            else: raise Unsupported('unexpected object in __types__: '+nm)
    def inline_class(s,sec,off):
        """read an hkClass object stored inside a data section (e.g. the vertex layout class of hkxVertexBuffer)"""
        nm='inline@%d'%off
        if nm in s.cls.byname: return nm
        u32=lambda o:struct.unpack_from('>I',sec.data,o)[0]; u16=lambda o:struct.unpack_from('>H',sec.data,o)[0]
        gf={a:(sc,b) for a,sc,b in sec.gfix}
        cstr=lambda o: sec.data[o:sec.data.index(b'\0',o)].decode()
        mo=sec.lfd.get(off+24); members=[]
        for k in range(u32(off+28)):
            m=mo+24*k; cref=gf.get(m+4); cname=None
            if cref is not None and cref[0]==sec.index: cname=s.inline_class(sec,cref[1])
            members.append(dict(name=cstr(sec.lfd[m]),cls=None,cls_name=cname,type=sec.data[m+12],sub=sec.data[m+13],carr=u16(m+14),flags=u16(m+16),offset=u16(m+18)))
        s.cls.byname[nm]=dict(off=off,name=nm,parent=None,parent_name=None,size=u32(off+8),nmem=len(members),mem_off=None,members=members)
        return nm
    def swap_enum(s,typ,a):
        out=s.out; base=typ.abs
        swn(out,base+a,4,5)
        ni=struct.unpack_from('>I',typ.data,a+8)[0]; io=typ.lfd.get(a+4)
        for k in range(ni): swn(out,base+io+8*k,4,2)       # items: int value + name pointer
    # ---- __data__
    def swap_data(s):
        dat=s.secs[2]; cls=s.secs[0]
        cn=lambda off: cls.data[off:cls.data.index(b'\0',off)].decode()
        for a,si,co in sorted(dat.vfix):
            nm=cn(co)
            if nm=='hkClass': s.swap_class_object(dat,a)
            elif nm=='hkClassEnum': s.swap_enum(dat,a)
            else: s.swap_struct(dat,a,nm)
    def elem_swap(s,sec,o,kind,clsoff,count):
        """swap `count` elements of a array whose element kind is `kind`"""
        out=s.out; base=sec.abs
        if kind==T_STRUCT:
            c=s.cls.byname.get(clsoff)
            if c is None: raise Unsupported('array element class missing: %s'%clsoff)
            for k in range(count): s.swap_struct(sec,o+k*c['size'],c['name'])
        elif kind in SCALAR:
            sz=SCALAR[kind][0]
            if sz>1: swn(out,base+o,sz,count)
        elif kind in FLOATS:
            swn(out,base+o,4,count*FLOATS[kind]//4)
        elif kind==T_VARIANT: swn(out,base+o,4,count*2)
        elif kind==0: pass
        else: raise Unsupported('array element kind %d'%kind)
    def swap_struct(s,sec,off,clsname):
        out=s.out; base=sec.abs
        cdef=s.cls.byname.get(clsname)
        if not cdef: raise Unsupported('class definition missing: '+clsname)
        if cdef.get('mask'):
            for i,ch in enumerate(cdef['mask']):
                if ch=='4': sw(out,base+off+4*i,4)
                elif ch=='2': sw(out,base+off+4*i,2); sw(out,base+off+4*i+2,2)
                elif ch=='a': sw(out,base+off+4*i,2)          # 16-bit value followed by two single bytes
            for srcoff,spec in PHYS_BLOCKS.get(clsname,[]):
                dst=sec.lfd.get(off+srcoff)
                cnt=struct.unpack_from('>I',sec.data,off+srcoff+4)[0]
                if dst is None or not cnt or (sec.index,dst) in s.seen: continue
                s.seen.add((sec.index,dst))
                if spec[0]=='w':
                    nxt=min([x for x in sec.starts if x>dst]+[len(sec.data)])
                    if spec[1]>1: swn(out,base+dst,spec[1],(nxt-dst)//spec[1])
                else:
                    _,stride,pat=spec
                    for e in range(cnt):
                        for i,ch in enumerate(pat):
                            o=base+dst+e*stride+4*i
                            if ch=='4': sw(out,o,4)
                            elif ch=='2': sw(out,o,2); sw(out,o+2,2)
            return
        ms=s.cls.members(clsname)
        for m in ms:
            t=m['type']; o=off+m['offset']; n=max(1,m['carr'])
            if t in SCALAR:
                sz=SCALAR[t][0]
                if sz>1: swn(out,base+o,sz,n)
                if m['name']=='inPackfile' and t==T_BOOL: out[base+o]=0     # loader flag: 1 in the Wii files, 0 in the PC files
            elif t in FLOATS: swn(out,base+o,4,n*FLOATS[t]//4)
            elif t in (T_ENUM,T_FLAGS):
                sz={3:1,4:1,5:2,6:2,7:4,8:4}.get(m['sub'],4)
                if sz>1: swn(out,base+o,sz,n)
            elif t==T_ZERO: pass
            elif t==T_VARIANT: swn(out,base+o,4,2)
            elif t==T_STRUCT:
                c=s.cls.byname.get(m['cls_name'])
                if c is None: raise Unsupported('struct class missing: %s (member %s)'%(m['cls_name'],m['name']))
                for k in range(n): s.swap_struct(sec,o+k*c['size'],c['name'])
            elif t in (T_ARRAY,T_SIMPLEARRAY):
                cnt_off=o+4
                cnt=struct.unpack_from('>I',sec.data,cnt_off)[0]
                if t==T_ARRAY: swn(out,base+o+4,4,2)
                else: sw(out,base+o+4,4)
                if t==T_ARRAY: cnt&=0x3fffffff
                dst=sec.lfd.get(o)
                if cnt and dst is not None and (sec.index,dst) not in s.seen:
                    s.seen.add((sec.index,dst)); s.elem_swap(sec,dst,m['sub'],m['cls_name'],cnt)
                elif cnt and dst is None: s.warn.append('array without fixup: %s.%s'%(clsname,m['name']))
            elif t==T_HOMOARRAY:
                # {hkClass* @0 (global fixup), data ptr @4 (local fixup), element count @8}
                cnt=struct.unpack_from('>I',sec.data,o+8)[0]
                swn(out,base+o,4,3)
                cref={a:(sc,b) for a,sc,b in sec.gfix}.get(o)
                dst=sec.lfd.get(o+4)
                if cnt and dst is not None and (sec.index,dst) not in s.seen:
                    if cref is None or cref[0]!=sec.index: raise Unsupported('homogeneous array without inline class (%s.%s)'%(clsname,m['name']))
                    s.seen.add((sec.index,dst)); inl=s.inline_class(sec,cref[1]); sz=s.cls.byname[inl]['size']
                    for k in range(cnt): s.swap_struct(sec,dst+k*sz,inl)
            else: raise Unsupported('member type %d (%s.%s)'%(t,clsname,m['name']))

# ---- Havok physics / ragdoll classes whose layouts were learned from Wii/PC file pairs (word masks) ----
#   mask per 4-byte word of the (16-byte padded) object: '4' = 32-bit value, '2' = two 16-bit values, '.' = unchanged
PHYS_MASKS = {
 'hkpBallAndSocketConstraintData':'....2...44444444a...',
 'bfSubMaterialIndex':'2...',
 'hkpConvexTranslateShape':'....4...444.',
 'hkpSphereShape':'....4...',
 'hkpBoxShape':'....4...4444',
 'hkpConvexTransformShape':'....4...444.444.444.444.',
 'hkpListShape':'.......44...44444444........',
 'hkpCapsuleShape':'....4...44444444',
 'hkpConvexVerticesShape':'....4...444.444..444.44.',
 'hkpMoppBvTreeShape':'................',
 'hkpMoppCode':'....4444.44.',
 'hkaRagdollInstance':'...44.44.44.',
 'hkaSkeletonMapper':'.....44.44.44...',
 'hkpRagdollConstraintData':'....2...444.444.444.....444.444.444.444.22..444.444.444.....a.4a.444a.444a.4442.',
 'hkpPositionConstraintMotor':'...444444...',
 'hkpLimitedHingeConstraintData':'....2...444.444.444.....444.444.444.444.222..a..a44422..',
 'hkpCylinderShape':'....444.4444444444444444',
 'hkpStiffSpringConstraintData':'....2...444..4..24..',
 'hkpSimpleMeshShape':'.......44.44..44....',
 'hkpPhysicsSystem':'...44.44..4..4......', 'hkpPhysicsData':'....44..',
 'hkxAnimatedFloat':'.4..', 'hkxAnimatedVector':'.4..', 'hkxAnimatedQuaternion':'.4..', 'hkxAnimatedMatrix':'.4..',
 'hkxSparselyAnimatedBool':'.4.4', 'hkxSparselyAnimatedInt':'.4.4', 'hkxSparselyAnimatedString':'.4.4', 'hkxMaterialEffect':'...4',
}
#   arrays referenced from those objects: (offset of the pointer field, ('w',width) | ('p',stride,per-word pattern)); count is the next word
PHYS_BLOCKS = {
 'hkaRagdollInstance':[(32,('w',4))],
 'hkaSkeletonMapper':[(16,('p',64,'2...'+'4'*11+'.')),(28,('p',112,'22..'+'4'*11+'.'+'4'*11+'.')),(40,('w',2))],
 'hkpConvexVerticesShape':[(64,('w',4)),(80,('w',4))],
 'hkpListShape':[(24,('w',4))],
 'hkpSimpleMeshShape':[(24,('w',4)),(36,('p',16,'4442'))],
 'hkxAnimatedFloat':[(0,('w',4))], 'hkxAnimatedVector':[(0,('w',4))], 'hkxAnimatedQuaternion':[(0,('w',4))], 'hkxAnimatedMatrix':[(0,('w',4))],
 'hkxSparselyAnimatedBool':[(0,('w',1)),(8,('w',4))], 'hkxSparselyAnimatedInt':[(0,('w',4)),(8,('w',4))], 'hkxSparselyAnimatedString':[(0,('w',4)),(8,('w',4))],
 'hkpPhysicsSystem':[(8,('w',4)),(20,('w',4))], 'hkpPhysicsData':[(12,('w',4))],
}

# ---- definitions for a few standard Havok scene classes that the packfiles do not describe themselves ----
def _mem(name,type_,offset,sub=0,cls=None,carr=0,flags=0):
    return dict(name=name,cls=None,cls_name=cls,type=type_,sub=sub,carr=carr,flags=flags,offset=offset)
def builtin_classes():
    d={}
    def add(name,parent,size,members): d[name]=dict(off=-1,name=name,parent=None,parent_name=parent,size=size,nmem=len(members),mem_off=None,members=members)
    add('bfFastMeshBuffer',None,16,[_mem('vertexData',T_SIMPLEARRAY,0,sub=T_UINT8),_mem('indices',T_SIMPLEARRAY,8,sub=T_UINT16)])
    for _n,_m in PHYS_MASKS.items(): add(_n,None,len(_m)*4,[]); d[_n]['mask']=_m
    return d

# ---------------- Blue Fang bfFastMeshBuffer (vertex buffers differ between Wii and PC) ----------------
import struct as _st
import bisect as _bisect
def _rev4(b): return b''.join(b[i:i+4][::-1] for i in range(0, len(b), 4))
def mesh_blob_wii_to_pc(v):
    """Float-stream vertex buffer: Wii header 288 bytes, PC header 272 bytes; position and normal streams grow from
    3 to 4 floats (w = 0.0); all other values are floats/ints (4-byte swap)."""
    w = lambda i: _st.unpack_from('>I', v, 4 * i)[0]
    nv = w(1)
    if w(2) != nv: raise Unsupported('mesh buffer: vertex count mismatch')
    slots = {}
    for s in range(9):
        rec = [w(3 + 6 * s + j) for j in range(6)]
        if any(rec[1:5]): slots[s] = rec
    sig = tuple((s, r[1], r[2], r[3], r[4]) for s, r in sorted(slots.items()))
    ok = {((0,12,3,4,1),(1,12,3,4,1),(6,32,8,4,1),(8,16,2,4,2)), ((0,12,3,4,1),(1,12,3,4,1),(6,32,8,4,1),(8,8,2,4,1))}
    if sig not in ok: raise Unsupported('bfFastMeshBuffer: packed/quantized vertex format not supported yet %s' % (sig[:3],))
    hdr_old = len(v) - sum(nv * r[1] for r in slots.values())
    if hdr_old != 288: raise Unsupported('mesh buffer: unexpected header size %d' % hdr_old)
    streams = {}
    for s, r in slots.items():
        a = hdr_old + r[0]; streams[s] = v[a:a + nv * r[1]]
    def vec3to4(b):
        out = bytearray()
        for i in range(nv): out += _rev4(b[12*i:12*i+12]) + b'\x00\x00\x00\x00'
        return bytes(out)
    new = {0: vec3to4(streams[0]), 1: vec3to4(streams[1]), 6: _rev4(streams[6]), 8: _rev4(streams[8])}
    hdr_new = 272; off = 0; recs = {}
    for s in (0, 1, 6, 8):
        stride = len(new[s]) // nv; r = slots[s]
        recs[s] = [off, stride, 4 if s in (0, 1) else r[2], r[3], r[4], 0]; off += len(new[s])
    total = hdr_new + off
    words = [total, nv, nv] + [0] * 65
    for s in range(9):
        if s in recs: words[3 + 6*s:9 + 6*s] = recs[s]
    words[57] = hdr_new - 228
    base = w(58)
    for s in range(9): words[58 + s] = (base + recs[s][0]) if s in recs else 0
    words[67] = 0xDDDDDDDD
    head = b''.join(_st.pack('<I', x) for x in words[:68])
    return head + new[0] + new[1] + new[6] + new[8]

def mesh_blob_packed_wii_to_pc(v):
    """Interleaved packed vertex buffer (Wii: 8/16-bit fixed-point attributes, 288-byte header) ->
    PC interleaved float vertices (32 or 36 bytes each, 272-byte header)."""
    w = lambda i: _st.unpack_from('>I', v, 4 * i)[0]
    nv = w(1)
    if w(2) != nv: raise Unsupported('mesh buffer: vertex count mismatch')
    recs = {}
    for s in range(9):
        r = [w(3 + 6*s + j) for j in range(6)]
        if any(r[1:5]):
            ex = _st.pack('>I', r[5]); recs[s] = dict(off=r[0], stride=r[1], comps=r[2], type=r[3], frac=ex[0], kind=ex[1])
    if set(recs) not in ({0, 1, 8}, {0, 1, 7, 8}): raise Unsupported('bfFastMeshBuffer: unknown vertex layout (slots %s)' % sorted(recs))
    S = recs[0]['stride']
    if any(r['stride'] != S for r in recs.values()): raise Unsupported('bfFastMeshBuffer: unexpected stream layout')
    hdr_old = len(v) - nv * S
    if hdr_old != 288: raise Unsupported('mesh buffer: unexpected header size %d' % hdr_old)
    comp = {4: ('>B', 1), 5: ('>H', 2), 6: ('>b', 1), 7: ('>h', 2)}     # component kind: 4=u8 5=u16 6=s8 7=s16 (fixed point, 'frac' fractional bits)
    def read(s, i):
        r = recs[s]; base = hdr_old + i * S + r['off']; out = []
        for c in range(r['comps']):
            if r['type'] == 4:                                 # plain 32-bit float (big-endian), no fixed-point scaling
                out.append(_st.unpack_from('>f', v, base + 4 * c)[0]); continue
            fmt = comp.get(r['kind'])
            if fmt is None or fmt[1] != r['type']: raise Unsupported('bfFastMeshBuffer: component kind %d/type %d' % (r['kind'], r['type']))
            out.append(_st.unpack_from(fmt[0], v, base + fmt[1] * c)[0] / float(1 << r['frac']))
        return out
    has7 = 7 in recs
    order = [0, 1] + ([7] if has7 else []) + [8]
    size = {0: 12, 1: 12, 7: 4, 8: 8}; offs = {}; o = 0
    for s in order: offs[s] = o; o += size[s]
    PS = o; body = bytearray()
    for i in range(nv):
        for s in order:
            if s == 7:                                    # packed RGBA color word -> BGRA
                r = recs[7]; b = v[hdr_old + i * S + r['off']: hdr_old + i * S + r['off'] + 4]; body += bytes((b[2], b[1], b[0], b[3]))
            else:
                vals = read(s, i); body += _st.pack('<%df' % len(vals), *vals)
    words = [272 + len(body), nv, nv] + [0] * 65
    for s in order: words[3 + 6*s:9 + 6*s] = [offs[s], PS, {0: 3, 1: 3, 7: 1, 8: 2}[s], 4, 1, 0]
    words[57] = 272 - 228
    base = w(58)
    for s in order: words[58 + s] = base + offs[s]
    words[67] = 0xDDDDDDDD
    return b''.join(_st.pack('<I', x) for x in words[:68]) + bytes(body)

def mesh_blob_wii_to_pc_any(v):
    w = lambda i: _st.unpack_from('>I', v, 4 * i)[0]
    slots = [s for s in range(9) if any(w(3 + 6*s + j) for j in range(1, 5))]
    if 6 in slots: return mesh_blob_wii_to_pc(v)          # float-stream layout (animal bodies)
    return mesh_blob_packed_wii_to_pc(v)                  # interleaved packed layout (props, habitats, editor models)

def relayout_meshes(conv, out):
    """replace each Wii vertex blob by its PC version and rebuild the __data__ section around the size changes"""
    dat = conv.secs[2]; cls = conv.secs[0]
    cn = lambda off: cls.data[off:cls.data.index(b'\0', off)].decode()
    lfd = {a: b for a, b in dat.lfix}
    metas = []
    for a, si, co in sorted(dat.vfix):
        if cn(co) != 'bfFastMeshBuffer': continue
        vptr = lfd[a]; vsz = _st.unpack_from('>I', dat.data, a + 4)[0]
        metas.append(dict(obj=a, vptr=vptr, vsz=vsz, new=mesh_blob_wii_to_pc_any(dat.data[vptr:vptr + vsz])))
    if not metas: return bytes(out)
    al = lambda n: (n + 15) // 16 * 16
    metas.sort(key=lambda m: m['vptr'])
    olddata = bytes(out[dat.abs:dat.abs + len(dat.data)])
    nd = bytearray(); pos = 0; shifts = []; cum = 0
    for m in metas:
        nd += olddata[pos:m['vptr']]
        newstart = len(nd); nd += m['new']; nd += b'\x00' * (al(len(m['new'])) - len(m['new']))
        oldnext = al(m['vptr'] + m['vsz'])
        cum = (newstart + al(len(m['new']))) - oldnext      # total shift for everything after this buffer
        shifts.append((oldnext, cum)); pos = oldnext
    nd += olddata[pos:]
    starts = [x[0] for x in shifts]; cums = [x[1] for x in shifts]
    def mp(o):
        i = _bisect.bisect_right(starts, o) - 1
        return o + (cums[i] if i >= 0 else 0)
    for m in metas: _st.pack_into('<I', nd, mp(m['obj']) + 4, len(m['new']))
    def tab(entries, size):
        b = bytearray()
        for e in entries: b += b''.join(_st.pack('<I', x) for x in e)
        if len(b) > size: raise Unsupported('fixup table overflow')
        return bytes(b) + b'\xff' * (size - len(b))
    L = tab([(mp(a), mp(b)) for a, b in dat.lfix], dat.glob - dat.local)
    G = tab([(mp(a), sec, (mp(b) if sec == 2 else b)) for a, sec, b in dat.gfix], dat.virt - dat.glob)
    V = tab([(mp(a), sec, b) for a, sec, b in dat.vfix], dat.exp - dat.virt)
    newlen = len(nd)
    res = bytearray(out[:dat.abs]) + nd + L + G + V + bytes(out[dat.abs + dat.exp:dat.abs + dat.end])
    o = 0x40 + 2 * 0x30 + 20
    vals = [newlen, newlen + (dat.glob - dat.local), newlen + (dat.virt - dat.local), newlen + (dat.exp - dat.local), newlen + (dat.imp - dat.local), newlen + (dat.end - dat.local)]
    for j, x in enumerate(vals): _st.pack_into('<I', res, o + 4 + 4 * j, x)    # fields after 'absolute start': local, global, virtual, exports, imports, end
    return bytes(res)

_CLASSDB_B64 = """
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
"""
def pooled_db():
    """built-in class definitions as a Classes-like object"""
    db = Classes.__new__(Classes); db.byname = {}; db.byoff = {}
    for n, i in json.loads(zlib.decompress(base64.b64decode(_CLASSDB_B64))).items():
        db.byname[n] = dict(off=-1, name=n, parent=None, parent_name=i['parent'], size=i['size'], nmem=len(i['members']), mem_off=None,
            members=[dict(name=m[0], type=m[1], sub=m[2], cls=None, cls_name=m[3], carr=m[4], flags=m[5], offset=m[6]) for m in i['members']])
    for n, i in builtin_classes().items(): db.byname.setdefault(n, i)
    return db

_DB = None
def convert(data):
    """Wii (big-endian) packfile bytes -> PC packfile bytes. Raises Unsupported if some class layout is unknown."""
    global _DB
    if _DB is None: _DB = pooled_db()
    return Conv(data, _DB).run()

def _main():
    if len(sys.argv) != 3: sys.exit(__doc__)
    src, dst = sys.argv[1], sys.argv[2]
    jobs = []
    if os.path.isdir(src):
        for r, _, fs in os.walk(src):
            for f in fs:
                if f.lower().endswith('.hkx'): p = os.path.join(r, f); jobs.append((p, os.path.join(dst, os.path.relpath(p, src))))
    else: jobs = [(src, dst)]
    ok = bad = 0
    for sp, dp in jobs:
        try: out = convert(open(sp, 'rb').read())
        except Exception as e: bad += 1; print('SKIPPED', sp, '-', e); continue
        os.makedirs(os.path.dirname(os.path.abspath(dp)), exist_ok=True); open(dp, 'wb').write(out); ok += 1
    print('converted %d file(s), skipped %d' % (ok, bad))

if __name__ == '__main__':
    _main()
