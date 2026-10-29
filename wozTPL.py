#!/usr/bin/env python3
"""woztpl.py - dependency-free Wii TPL texture converter for World of Zoo.

Converts GameCube / Wii TPL textures to TGA (32-bit BGRA) or DDS
(uncompressed 32-bit RGBA). Supports common TPL formats: I4, I8, IA4, IA8,
RGB565, RGB5A3, RGBA8, C4, C8, C14X2 and CMPR. Indexed formats require a
valid palette in the TPL. Multiple-image TPLs are written as name_0, name_1, ...

Examples:
  python woztpl.py texture.tpl
  python woztpl.py texture.tpl --format dds
  python woztpl.py WiiTextures/ --out Converted/ --format both
  python woztpl.py texture.tpl --info

Only Python 3 standard library is required. This tool converts image pixels;
it does not modify .pkg archives or game-specific texture references.
"""
from __future__ import annotations
import argparse, os, struct, sys
from pathlib import Path

MAGIC = 0x0020AF30
FMT = {0:'I4',1:'I8',2:'IA4',3:'IA8',4:'RGB565',5:'RGB5A3',6:'RGBA8',8:'C4',9:'C8',10:'C14X2',14:'CMPR'}

class TPLError(Exception): pass

def u16(b, o): return struct.unpack_from('>H', b, o)[0]
def u32(b, o): return struct.unpack_from('>I', b, o)[0]
def clamp8(x): return max(0, min(255, int(x)))
def expand3(x): return (x << 5) | (x << 2) | (x >> 1)
def expand4(x): return (x << 4) | x
def expand5(x): return (x << 3) | (x >> 2)
def expand6(x): return (x << 2) | (x >> 4)

def rgb565(v):
    return (expand5((v >> 11)&31), expand6((v >> 5)&63), expand5(v&31), 255)

def rgb5a3(v):
    if v & 0x8000:
        return (expand5((v>>10)&31), expand5((v>>5)&31), expand5(v&31), 255)
    return (expand4((v>>8)&15), expand4((v>>4)&15), expand4(v&15), expand3((v>>12)&7))

def palette_color(fmt, raw):
    if fmt == 0: # IA8: alpha byte, intensity byte
        a, i = raw[0], raw[1]; return (i, i, i, a)
    if fmt == 1: return rgb565(int.from_bytes(raw, 'big'))
    if fmt == 2: return rgb5a3(int.from_bytes(raw, 'big'))
    raise TPLError(f'unsupported palette format {fmt}')

def parse_tpl(data):
    if len(data) < 12 or u32(data, 0) != MAGIC:
        raise TPLError('not a standard Wii TPL file (magic 0x0020AF30 missing)')
    count = u32(data, 4); table = u32(data, 8)
    if count < 1 or count > 4096: raise TPLError(f'implausible texture count: {count}')
    if table + count*8 > len(data): raise TPLError('texture table is outside file bounds')
    items=[]
    for i in range(count):
        image_off, pal_off = struct.unpack_from('>II', data, table+i*8)
        if image_off + 0x24 > len(data): raise TPLError(f'texture {i}: image header outside file')
        h, w = struct.unpack_from('>HH', data, image_off)
        fmt = u32(data, image_off+4); image_data = u32(data, image_off+8)
        if not w or not h or w > 32768 or h > 32768: raise TPLError(f'texture {i}: invalid dimensions {w}x{h}')
        if image_data >= len(data): raise TPLError(f'texture {i}: image data offset outside file')
        palette=None
        if pal_off:
            if pal_off+12 > len(data): raise TPLError(f'texture {i}: palette header outside file')
            entries = u16(data, pal_off); pal_fmt = u32(data, pal_off+4); pal_data = u32(data, pal_off+8)
            if entries > 0 and pal_data + entries*2 <= len(data):
                palette=(pal_fmt, [palette_color(pal_fmt, data[pal_data+j*2:pal_data+j*2+2]) for j in range(entries)])
        items.append({'index':i,'width':w,'height':h,'format':fmt,'data_offset':image_data,'palette':palette})
    return items

def decode_texture(data, t):
    w,h,fmt,off=t['width'],t['height'],t['format'],t['data_offset']
    if fmt not in FMT: raise TPLError(f"texture {t['index']}: unsupported TPL pixel format {fmt}")
    pixels=[(0,0,0,0)]*(w*h)
    def put(x,y,c):
        if x<w and y<h: pixels[y*w+x]=c
    def need(pos,n):
        if pos+n>len(data): raise TPLError(f"texture {t['index']}: truncated pixel data at 0x{pos:X} (need {n} bytes)")
    def intensity(i,a=255): return (i,i,i,a)
    def tile_iter(tw,th,bs):
        pos=off
        for ty in range(0,h,th):
            for tx in range(0,w,tw):
                need(pos,bs); yield tx,ty,pos; pos+=bs
    if fmt == 0: # I4, 8x8 tile, 32 bytes
        for tx,ty,p in tile_iter(8,8,32):
            for j in range(32):
                b=data[p+j]
                for half,nib in enumerate((b>>4,b&15)):
                    k=j*2+half; put(tx+(k%8),ty+(k//8),intensity(expand4(nib)))
    elif fmt == 1: # I8, 8x4 tile
        for tx,ty,p in tile_iter(8,4,32):
            for k in range(32): put(tx+k%8,ty+k//8,intensity(data[p+k]))
    elif fmt == 2: # IA4, 8x4 tile: alpha high nibble, intensity low
        for tx,ty,p in tile_iter(8,4,32):
            for k in range(32):
                b=data[p+k]; put(tx+k%8,ty+k//8,intensity(expand4(b&15),expand4(b>>4)))
    elif fmt == 3: # IA8, 4x4 tile: alpha then intensity
        for tx,ty,p in tile_iter(4,4,32):
            for k in range(16): put(tx+k%4,ty+k//4,intensity(data[p+k*2+1],data[p+k*2]))
    elif fmt in (4,5): # RGB565 / RGB5A3, 4x4 tile
        dec=rgb565 if fmt==4 else rgb5a3
        for tx,ty,p in tile_iter(4,4,32):
            for k in range(16): put(tx+k%4,ty+k//4,dec(u16(data,p+k*2)))
    elif fmt == 6: # RGBA8, 4x4 tile, AR plane then GB plane
        for tx,ty,p in tile_iter(4,4,64):
            for k in range(16):
                a,r=data[p+k*2:p+k*2+2]
                g,b=data[p+32+k*2:p+32+k*2+2]
                put(tx+k%4,ty+k//4,(r,g,b,a))
    elif fmt in (8,9,10): # indexed C4/C8/C14X2
        if not t['palette']: raise TPLError(f"texture {t['index']}: indexed format {FMT[fmt]} has no usable palette")
        _,pal=t['palette']
        if fmt==8:
            for tx,ty,p in tile_iter(8,8,32):
                for j in range(32):
                    b=data[p+j]
                    for half,nib in enumerate((b>>4,b&15)):
                        k=j*2+half; idx=nib
                        if idx>=len(pal): raise TPLError('C4 palette index out of range')
                        put(tx+k%8,ty+k//8,pal[idx])
        elif fmt==9:
            for tx,ty,p in tile_iter(8,4,32):
                for k in range(32):
                    idx=data[p+k]
                    if idx>=len(pal): raise TPLError('C8 palette index out of range')
                    put(tx+k%8,ty+k//8,pal[idx])
        else:
            for tx,ty,p in tile_iter(4,4,32):
                for k in range(16):
                    idx=u16(data,p+k*2)&0x3fff
                    if idx>=len(pal): raise TPLError('C14X2 palette index out of range')
                    put(tx+k%4,ty+k//4,pal[idx])
    elif fmt == 14: # CMPR, 8x8 macrotiles containing four DXT1-like 4x4 blocks
        for tx,ty,p in tile_iter(8,8,32):
            for sub in range(4):
                bx=tx+(sub%2)*4; by=ty+(sub//2)*4; q=p+sub*8
                c0=u16(data,q); c1=u16(data,q+2); bits=int.from_bytes(data[q+4:q+8],'big')
                a=rgb565(c0); b=rgb565(c1)
                if c0>c1:
                    c2=tuple((2*a[j]+b[j])//3 for j in range(3))+(255,)
                    c3=tuple((a[j]+2*b[j])//3 for j in range(3))+(255,)
                else:
                    c2=tuple((a[j]+b[j])//2 for j in range(3))+(255,); c3=(0,0,0,0)
                colors=(a,b,c2,c3)
                for k in range(16):
                    idx=(bits>>(30-2*k))&3; put(bx+k%4,by+k//4,colors[idx])
    return pixels

def write_tga(path,w,h,pixels):
    # Uncompressed true-colour TGA, 32-bit BGRA, top-left origin.
    header=struct.pack('<BBBHHBHHHHBB',0,0,2,0,0,0,0,0,w,h,32,0x28)
    with open(path,'wb') as f:
        f.write(header)
        for r,g,b,a in pixels: f.write(bytes((b,g,r,a)))

def write_dds(path,w,h,pixels):
    # Legacy DDS with uncompressed 32-bit RGBA masks; pixels written BGRA for masks.
    flags=0x0000100F # CAPS|HEIGHT|WIDTH|PITCH|PIXELFORMAT
    pitch=w*4
    pf=struct.pack('<IIIIIIII',32,0x41,0,32,0x00FF0000,0x0000FF00,0x000000FF,0xFF000000)
    header=struct.pack('<IIIIIII',124,flags,h,w,pitch,0,0)+b'\0'*44+pf+struct.pack('<IIIII',0x1000,0,0,0,0)
    if len(header)!=124: raise AssertionError(f'DDS header length {len(header)}')
    with open(path,'wb') as f:
        f.write(b'DDS '+header)
        for r,g,b,a in pixels: f.write(bytes((b,g,r,a)))

# ---------------------------------------------------------------------------------------------
# Additions for World of Zoo PC packages
# ---------------------------------------------------------------------------------------------
def tga_bytes(w,h,pixels):
    """uncompressed 32-bit TGA laid out like the PC game's own files: bottom-left origin, rows stored bottom to top"""
    header=struct.pack('<BBBHHBHHHHBB',0,0,2,0,0,0,0,0,w,h,32,0x08)
    rows=[pixels[y*w:(y+1)*w] for y in range(h-1,-1,-1)]
    return header+b''.join(bytes((b,g,r,a)) for row in rows for r,g,b,a in row)+b'\0'*8+b'TRUEVISION-XFILE.\0'   # same footer as the PC files

def _tga_rle_rows(rows):
    """TGA RLE, one run-length stream per row (the PC files do this): packets of up to 128 pixels"""
    out=bytearray()
    for seq in rows:
        i=0; n=len(seq)
        while i<n:
            j=i+1
            while j<n and j-i<128 and seq[j]==seq[i]: j+=1
            if j-i>=2:
                out.append(0x80|(j-i-1)); out+=seq[i]; i=j
            else:
                k=i
                while k<n and k-i<128 and not (k+1<n and seq[k]==seq[k+1]): k+=1
                if k==i: k=i+1
                out.append(k-i-1)
                for t in range(i,k): out+=seq[t]
                i=k
    return bytes(out)

def is_colour_layer(stem):
    """True for the opaque colour-layer images the texture generator reads (bigcat_base_colorlayer_0101, bear_base_basecolor_0101 ...).
    The PC game keeps masks and maps (*_alpha, *_dirty, bodymap, sensitivity, templates) as 32-bit, so those are left alone."""
    n=stem.lower()
    return not (n.endswith('_dirty') or n.endswith('_alpha') or any(k in n for k in ('bodymap','sensitivity','template','dirt')))

def tga_bytes_pc(w,h,pixels,rle=True):
    """TGA the way the PC game's own colour-layer files are: 24-bit (descriptor 0, no alpha - callers pass fully opaque images only),
    bottom-left origin, RLE-compressed (type 10) unless rle=False (type 2), same footer.
    NOTE: converted Bear/Penguin stayed uniformly gray while their opaque colour layers were 32-bit raw TGAs; with 24-bit RLE layers
    (what Big Cat ships) colours and patterns work in game. Panda ships 24-bit raw layers, so both 24-bit forms are native."""
    opaque=all(px[3]==255 for px in pixels); bpp=24 if opaque else 32
    def enc(px): return bytes((px[2],px[1],px[0])) if opaque else bytes((px[2],px[1],px[0],px[3]))
    rows=[[enc(px) for px in pixels[y*w:(y+1)*w]] for y in range(h-1,-1,-1)]
    header=struct.pack('<BBBHHBHHHHBB',0,0,10 if rle else 2,0,0,0,0,0,w,h,bpp,0 if opaque else 0x08)
    body=_tga_rle_rows(rows) if rle else b''.join(b''.join(r) for r in rows)
    return header+body+b'\0'*8+b'TRUEVISION-XFILE.\0'

def mip_chain(w,h,pixels):
    """box-filtered mip levels, from the full-size image down to 1x1 (list of (w,h,pixels))"""
    levels=[(w,h,pixels)]
    while w>1 or h>1:
        nw,nh=max(1,w//2),max(1,h//2); src=levels[-1][2]; out=[]
        for y in range(nh):
            y0=min(h-1,2*y); y1=min(h-1,2*y+1)
            for x in range(nw):
                x0=min(w-1,2*x); x1=min(w-1,2*x+1)
                p=(src[y0*w+x0],src[y0*w+x1],src[y1*w+x0],src[y1*w+x1])
                out.append(tuple((p[0][c]+p[1][c]+p[2][c]+p[3][c]+2)//4 for c in range(4)))
        w,h=nw,nh; levels.append((w,h,out))
    return levels

def dds_rgba_bytes(w,h,pixels,mips=True):
    """uncompressed 32-bit DDS (BGRA masks), with a full mip chain unless mips=False"""
    levels=mip_chain(w,h,pixels) if mips else [(w,h,pixels)]
    flags=0x0000100F | (0x20000 if len(levels)>1 else 0)
    pf=struct.pack('<IIIIIIII',32,0x41,0,32,0x00FF0000,0x0000FF00,0x000000FF,0xFF000000)
    caps=0x1000 | (0x400008 if len(levels)>1 else 0)
    header=struct.pack('<IIIIIII',124,flags,h,w,w*4,0,len(levels) if len(levels)>1 else 0)+b'\0'*44+pf+struct.pack('<IIIII',caps,0,0,0,0)
    body=b''.join(b''.join(bytes((b,g,r,a)) for r,g,b,a in px) for _,_,px in levels)
    return b'DDS '+header+body

def cmpr_to_dxt1_blocks(data,t):
    """lossless repack of a GameCube CMPR image: 8x8 tiles of four 4x4 blocks -> plain raster-order DXT1 blocks"""
    w,h,off=t['width'],t['height'],t['data_offset']
    bw,bh=(w+3)//4,(h+3)//4; blocks=[b'\0'*8]*(bw*bh); pos=off
    for ty in range(0,h,8):
        for tx in range(0,w,8):
            if pos+32>len(data): raise TPLError('truncated CMPR data')
            for sub in range(4):
                bx=tx//4+(sub%2); by=ty//4+(sub//2); q=pos+sub*8
                c0=data[q:q+2][::-1]; c1=data[q+2:q+4][::-1]          # big-endian RGB565 -> little-endian
                rows=bytearray()
                for r in range(4):                                     # index bits: MSB-first in the Wii, LSB-first in DXT1
                    v=data[q+4+r]; rows.append(((v>>6)&3)|(((v>>4)&3)<<2)|(((v>>2)&3)<<4)|((v&3)<<6))
                if bx<bw and by<bh: blocks[by*bw+bx]=bytes(c0)+bytes(c1)+bytes(rows)
            pos+=32
    return b''.join(blocks)

def dds_dxt1_bytes(w,h,blocks):
    flags=0x00081007                      # CAPS|HEIGHT|WIDTH|PIXELFORMAT|LINEARSIZE
    pf=struct.pack('<II4sIIIII',32,4,b'DXT1',0,0,0,0,0)
    header=struct.pack('<IIIIIII',124,flags,h,w,len(blocks),0,0)+b'\0'*44+pf+struct.pack('<IIIII',0x1000,0,0,0,0)
    return b'DDS '+header+blocks

def solid_dxt1_dds(size,rgb):
    """size x size DXT1 DDS with a full mip chain, every pixel the same colour"""
    r,g,b=rgb; c=((r>>3)<<11)|((g>>2)<<5)|(b>>3)
    block=struct.pack('<HHI',c,c,0)
    levels=[]; n=size
    while True:
        levels.append(max(1,n//4)*max(1,n//4)*8)
        if n==1: break
        n//=2
    flags=0x00081007|0x20000
    pf=struct.pack('<II4sIIIII',32,4,b'DXT1',0,0,0,0,0)
    header=struct.pack('<IIIIIII',124,flags,size,size,levels[0],0,len(levels))+b'\0'*44+pf+struct.pack('<IIIII',0x1000|0x400008,0,0,0,0)
    return b'DDS '+header+b''.join(block*(lv//8) for lv in levels)

def pc_extension(fmt_name,stem,path=''):
    """which file type the PC packages use for a Wii texture: RGBA8 images and the *_dirty masks are TGA, everything else DDS
    (particle textures are always DDS)"""
    if 'particles' in path.lower().replace('\\','/').split('/'): return 'dds'
    return 'tga' if (fmt_name=='RGBA8' or stem.lower().endswith('_dirty')) else 'dds'

def tpl_to_pc(data,stem,dds_mode='rgba',mips=True,path='',placeholder_size=1024,placeholder_rgb=(128,128,128),tga_style='pc',tga_rle=True):
    """convert the first image of a TPL to (extension, bytes) in the form the PC packages use"""
    t=parse_tpl(data)[0]; fmt=FMT.get(t['format'],'?'); ext=pc_extension(fmt,stem,path)
    if placeholder_size and fmt=='CMPR' and t['width']<=4 and t['height']<=4:   # 4x4 stand-in painted over at run time on the Wii
        return 'dds',solid_dxt1_dds(placeholder_size,placeholder_rgb)
    if ext=='tga':
        px=decode_texture(data,t)
        if tga_style!='legacy' and is_colour_layer(stem) and all(q[3]==255 for q in px):
            return 'tga',tga_bytes_pc(t['width'],t['height'],px,tga_rle)    # opaque colour layers: 24-bit like the PC files (verified in game)
        return 'tga',tga_bytes(t['width'],t['height'],px)                    # masks, dirt maps, body/sensitivity maps: unchanged 32-bit raw
    if dds_mode=='dxt1' and fmt=='CMPR' and t['width']%8==0 and t['height']%8==0:
        return 'dds',dds_dxt1_bytes(t['width'],t['height'],cmpr_to_dxt1_blocks(data,t))
    return 'dds',dds_rgba_bytes(t['width'],t['height'],decode_texture(data,t),mips)


def convert_file(src, out_dir, out_format, info_only=False):
    data=Path(src).read_bytes(); textures=parse_tpl(data)
    if info_only:
        for t in textures:
            print(f"{src}: texture {t['index']}: {t['width']}x{t['height']} {FMT.get(t['format'], 'UNKNOWN('+str(t['format'])+')')} offset=0x{t['data_offset']:X}" + (f" palette={len(t['palette'][1])}" if t['palette'] else ''))
        return 0
    base=Path(src).stem
    Path(out_dir).mkdir(parents=True,exist_ok=True)
    errors=0
    for t in textures:
        name=base if len(textures)==1 else f'{base}_{t["index"]}'
        try: pixels=decode_texture(data,t)
        except TPLError as e: print(f'ERROR: {src}: {e}',file=sys.stderr); errors+=1; continue
        outputs=[]
        if out_format in ('tga','both'): outputs.append(('tga',write_tga))
        if out_format in ('dds','both'): outputs.append(('dds',write_dds))
        for ext,writer in outputs:
            dst=Path(out_dir)/(name+'.'+ext)
            writer(dst,t['width'],t['height'],pixels)
            print(f'Wrote {dst} ({t["width"]}x{t["height"]} {FMT[t["format"]]})')
    return 1 if errors else 0

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('input',help='.tpl file or directory to scan recursively')
    ap.add_argument('--out','-o',default='converted_textures',help='output directory (default: converted_textures)')
    ap.add_argument('--format',choices=('tga','dds','both'),default='tga',help='output format (default: tga)')
    ap.add_argument('--info',action='store_true',help='list dimensions and formats without converting')
    ap.add_argument('--recursive',action='store_true',help='recursively scan input directory (default behavior for directories)')
    a=ap.parse_args(); src=Path(a.input)
    if not src.exists(): ap.error(f'input does not exist: {src}')
    if src.is_file():
        try: return convert_file(str(src),a.out,a.format,a.info)
        except (TPLError,struct.error) as e: print(f'ERROR: {e}',file=sys.stderr); return 2
    files=sorted(p for p in src.rglob('*') if p.is_file() and p.suffix.lower()=='.tpl')
    if not files: print(f'No .tpl files found in {src}',file=sys.stderr); return 1
    failures=0
    for p in files:
        rel=p.relative_to(src).with_suffix('')
        outdir=Path(a.out)/rel.parent
        try: failures += convert_file(str(p),str(outdir),a.format,a.info)
        except (TPLError,struct.error,OSError) as e: print(f'ERROR: {p}: {e}',file=sys.stderr); failures+=1
    print(f'Finished: {len(files)} TPL file(s), {failures} file(s) with errors.')
    return 1 if failures else 0

if __name__=='__main__': raise SystemExit(main())
