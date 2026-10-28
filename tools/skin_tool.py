# -*- coding: utf-8 -*-
"""skin_tool.py - make images game-ready for the Deathcraft Zombies Enhanced mod.

Self contained: the VTF encoder/decoder, the VPK packer/unpacker and the model
previewer are all implemented here. Nothing is imported from other tools.

Requires: Python 3, pillow, numpy  (pip install pillow numpy)

Commands
    list / skins / png2vtf / newskin / vtf2png / assign / copy-model /
    preview / check / pack / install / extract
"""
import argparse
import os
import re
import shutil
import struct
import sys
import zlib

import numpy as np
from PIL import Image

# --------------------------------------------------------------------------
# VTF
# --------------------------------------------------------------------------
FLAG_EIGHTBITALPHA = 0x2000
FMT_BGRA8888 = 0
FMT_BGR888 = 3
FMT_DXT1 = 13
FMT_DXT5 = 15
FMT_NAMES = {0: 'BGRA8888', 3: 'BGR888', 13: 'DXT1', 15: 'DXT5'}


def _rgb565(v):
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return ((r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2))


def _quant565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def _color_palette(c0, c1):
    p0 = _rgb565(c0)
    p1 = _rgb565(c1)
    if c0 > c1:
        p2 = tuple((2 * p0[i] + p1[i]) // 3 for i in range(3))
        p3 = tuple((p0[i] + 2 * p1[i]) // 3 for i in range(3))
    else:
        p2 = tuple((p0[i] + p1[i]) // 2 for i in range(3))
        p3 = (0, 0, 0)
    return [p0, p1, p2, p3]


def _alpha_palette(a0, a1):
    if a0 > a1:
        return [a0, a1] + [((7 - i) * a0 + i * a1) // 7 for i in range(1, 7)]
    return [a0, a1] + [((5 - i) * a0 + i * a1) // 5 for i in range(1, 5)] + [0, 255]


def encode_bc1(block):
    """block: (4,4,4) uint8 -> 8 bytes (DXT1 colour block)."""
    rgb = block[..., :3].astype(np.int32)
    flat = rgb.reshape(-1, 3)
    mn = flat.min(0)
    mx = flat.max(0)
    if (mn == mx).all():
        c0 = _quant565(*mx)
        return struct.pack('<HHI', c0, c0, 0)
    c0 = _quant565(*mx)
    c1 = _quant565(*mn)
    if c0 < c1:
        c0, c1 = c1, c0
    pal = _color_palette(c0, c1)
    bits = 0
    for i in range(16):
        px = flat[i]
        best, bi = 1 << 30, 0
        for k, p in enumerate(pal):
            d = (px[0] - p[0]) ** 2 + (px[1] - p[1]) ** 2 + (px[2] - p[2]) ** 2
            if d < best:
                best, bi = d, k
        bits |= bi << (2 * i)
    return struct.pack('<HHI', c0, c1, bits)


def encode_bc4(block):
    """alpha block (4,4) uint8 -> 8 bytes (DXT5 alpha)."""
    flat = block.reshape(-1).astype(np.int32)
    a0 = int(flat.max())
    a1 = int(flat.min())
    if a0 == a1:
        return bytes([a0, a1]) + bytes(6)
    pal = _alpha_palette(a0, a1)
    bits = 0
    for i in range(16):
        a = flat[i]
        best, bi = 1 << 30, 0
        for k, p in enumerate(pal):
            d = abs(a - p)
            if d < best:
                best, bi = d, k
        bits |= bi << (3 * i)
    out = bytes([a0, a1])
    out += bits.to_bytes(6, 'little')
    return out


def encode_dxt1(img):
    h, w = img.shape[:2]
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            block = img[by:by + 4, bx:bx + 4]
            if block.shape[0] < 4 or block.shape[1] < 4:
                pad = np.zeros((4, 4, 4), np.uint8)
                pad[:block.shape[0], :block.shape[1]] = block
                block = pad
            out += encode_bc1(block)
    return bytes(out)


def encode_dxt5(img):
    h, w = img.shape[:2]
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            block = img[by:by + 4, bx:bx + 4]
            if block.shape[0] < 4 or block.shape[1] < 4:
                pad = np.zeros((4, 4, 4), np.uint8)
                pad[:block.shape[0], :block.shape[1]] = block
                block = pad
            out += encode_bc4(block[..., 3])
            out += encode_bc1(block)
    return bytes(out)


def decode_dxt1(data, w, h):
    img = np.zeros((h, w, 4), np.uint8)
    img[..., 3] = 255
    o = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            c0, c1, bits = struct.unpack_from('<HHI', data, o)
            o += 8
            pal = _color_palette(c0, c1)
            for i in range(16):
                y = by + i // 4
                x = bx + i % 4
                if y < h and x < w:
                    img[y, x, :3] = pal[(bits >> (2 * i)) & 3]
    return img


def decode_dxt5(data, w, h):
    img = np.zeros((h, w, 4), np.uint8)
    o = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            a0, a1 = data[o], data[o + 1]
            abits = int.from_bytes(data[o + 2:o + 8], 'little')
            c0, c1, bits = struct.unpack_from('<HHI', data, o + 8)
            o += 16
            apal = _alpha_palette(a0, a1)
            pal = _color_palette(c0, c1)
            for i in range(16):
                y = by + i // 4
                x = bx + i % 4
                if y < h and x < w:
                    img[y, x, :3] = pal[(bits >> (2 * i)) & 3]
                    img[y, x, 3] = apal[(abits >> (3 * i)) & 7]
    return img


def _mip_sizes(w, h, fmt, levels):
    sizes = []
    ww, hh = w, h
    for _ in range(levels):
        if fmt in (FMT_DXT1, FMT_DXT5):
            sizes.append(max(1, (ww + 3) // 4) * max(1, (hh + 3) // 4) * (8 if fmt == FMT_DXT1 else 16))
        elif fmt == FMT_BGR888:
            sizes.append(ww * hh * 3)
        else:
            sizes.append(ww * hh * 4)
        ww = max(1, ww // 2)
        hh = max(1, hh // 2)
    return sizes


def mip_chain(img):
    out = [img]
    im = Image.fromarray(img, 'RGBA')
    w, h = im.size
    while w > 1 or h > 1:
        w = max(1, w // 2)
        h = max(1, h // 2)
        im = im.resize((w, h), Image.BOX)
        out.append(np.array(im))
    return out


def num_mip_levels(w, h):
    return int(np.floor(np.log2(max(w, h)))) + 1


def save_vtf(path, img, fmt_pref='auto'):
    """img: (h,w,4) uint8 -> writes a 7.2 VTF.

    Note: VTF stores the mip chain smallest first and mip 0 last.
    """
    h, w = img.shape[:2]
    if w % 4 or h % 4:
        raise SystemExit('image size must be multiples of 4 (got %dx%d)' % (w, h))
    has_alpha = bool((img[..., 3] < 255).any())
    if fmt_pref == 'dxt5':
        fmt = FMT_DXT5
    elif fmt_pref == 'dxt1':
        fmt = FMT_DXT1
    else:
        fmt = FMT_DXT1 if not has_alpha else FMT_DXT5
    mips = mip_chain(img)
    data = bytearray()
    for m in reversed(mips):
        data += encode_dxt1(m) if fmt == FMT_DXT1 else encode_dxt5(m)
    flags = 0 if fmt == FMT_DXT1 else FLAG_EIGHTBITALPHA
    ref = img[..., :3].reshape(-1, 3).mean(0) / 255.0
    hdr = bytearray(80)
    hdr[0:4] = b'VTF\0'
    struct.pack_into('<ii', hdr, 4, 7, 2)
    struct.pack_into('<i', hdr, 12, 80)
    struct.pack_into('<HH', hdr, 16, w, h)
    struct.pack_into('<I', hdr, 20, flags)
    struct.pack_into('<HH', hdr, 24, 1, 0)
    struct.pack_into('<3f', hdr, 32, float(ref[0]), float(ref[1]), float(ref[2]))
    struct.pack_into('<f', hdr, 48, 1.0)
    struct.pack_into('<i', hdr, 52, fmt)
    hdr[56] = len(mips)
    struct.pack_into('<i', hdr, 57, -1)
    hdr[61] = 0
    hdr[62] = 0
    struct.pack_into('<H', hdr, 63, 1)
    with open(path, 'wb') as f:
        f.write(bytes(hdr))
        f.write(bytes(data))
    return fmt, len(mips), len(hdr) + len(data)


def load_vtf(path):
    """Returns (h,w,4) uint8 of mip 0."""
    d = open(path, 'rb').read()
    if d[:4] not in (b'VTF\0', b'VTF\x00'):
        raise SystemExit('not a VTF: %s' % path)
    w, h = struct.unpack_from('<HH', d, 16)
    fmt = struct.unpack_from('<i', d, 52)[0]
    start = struct.unpack_from('<i', d, 12)[0]
    levels = d[56] or 1
    sizes = _mip_sizes(w, h, fmt, levels)
    off = start + sum(sizes) - sizes[0]          # mip 0 sits at the end of the chain
    if off < start:
        off = start
    if fmt == FMT_DXT5:
        return decode_dxt5(d[off:], w, h)
    if fmt == FMT_DXT1:
        return decode_dxt1(d[off:], w, h)
    if fmt == FMT_BGRA8888:
        a = np.frombuffer(d, np.uint8, count=w * h * 4, offset=off).reshape(h, w, 4)
        return a[..., [2, 1, 0, 3]].copy()
    if fmt == 4:  # RGBA8888
        return np.frombuffer(d, np.uint8, count=w * h * 4, offset=off).reshape(h, w, 4).copy()
    if fmt == FMT_BGR888:
        a = np.frombuffer(d, np.uint8, count=w * h * 3, offset=off).reshape(h, w, 3)
        out = np.dstack([a[..., 2], a[..., 1], a[..., 0], np.full((h, w), 255, np.uint8)])
        return out
    raise SystemExit('unsupported VTF format %d (%s) in %s' % (fmt, FMT_NAMES.get(fmt, '?'), path))


def vtf_info(path):
    d = open(path, 'rb').read()
    w, h = struct.unpack_from('<HH', d, 16)
    fmt = struct.unpack_from('<i', d, 52)[0]
    return w, h, fmt, d[56]


# --------------------------------------------------------------------------
# VPK
# --------------------------------------------------------------------------
VPK_SIG = 0x55AA1234
VPK_EMBEDDED = 0x7FFF


def _vpk_split(rel):
    rel = rel.replace('\\', '/').lstrip('/')
    folder = os.path.dirname(rel) or ' '
    base = os.path.basename(rel)
    if '.' in base and not base.startswith('.'):
        name, ext = base.rsplit('.', 1)
    else:
        name, ext = base, ' '
    return folder, name, ext or ' '


def vpk_pack(src_dir, out_path):
    groups = {}
    for root, _dirs, files in os.walk(src_dir):
        for fn in files:
            full = os.path.join(root, fn)
            rel = os.path.relpath(full, src_dir)
            folder, name, ext = _vpk_split(rel)
            groups.setdefault((ext, folder), []).append((name, full))
    tree = bytearray()
    data = bytearray()
    count = 0
    for ext in sorted({k[0] for k in groups}):
        tree += ext.encode('utf-8') + b'\x00'
        for folder in sorted({k[1] for k in groups if k[0] == ext}):
            tree += folder.encode('utf-8') + b'\x00'
            for name, path in sorted(groups[(ext, folder)]):
                content = open(path, 'rb').read()
                tree += name.encode('utf-8') + b'\x00'
                tree += struct.pack('<IHHII', zlib.crc32(content) & 0xFFFFFFFF, 0, VPK_EMBEDDED,
                                    len(data), len(content))
                tree += b'\xff\xff'
                data += content
                count += 1
            tree += b'\x00'
        tree += b'\x00'
    tree += b'\x00'
    with open(out_path, 'wb') as f:
        f.write(struct.pack('<III', VPK_SIG, 1, len(tree)))
        f.write(bytes(tree))
        f.write(bytes(data))
    return count, len(tree), len(data)


def vpk_extract(vpk_path, out_dir):
    d = open(vpk_path, 'rb').read()
    sig, version, tree_size = struct.unpack_from('<III', d, 0)
    if sig != VPK_SIG:
        raise SystemExit('not a VPK: %s' % vpk_path)
    hs = 12 if version == 1 else 28
    tree = d[hs:hs + tree_size]
    base = hs + tree_size
    pos = 0
    n = 0

    def cstr(buf, p):
        e = buf.find(b'\x00', p)
        return buf[p:e].decode('utf-8', 'replace'), e + 1

    while True:
        ext, pos = cstr(tree, pos)
        if not ext:
            break
        while True:
            folder, pos = cstr(tree, pos)
            if not folder:
                break
            while True:
                name, pos = cstr(tree, pos)
                if not name:
                    break
                crc, preload_len, archive, off, length = struct.unpack_from('<IHHII', tree, pos)
                pos += 16
                if pos + 2 <= len(tree) and tree[pos] == 0xFF and tree[pos + 1] == 0xFF:
                    pos += 2
                preload = tree[pos:pos + preload_len]
                pos += preload_len
                if archive == VPK_EMBEDDED:
                    payload = d[base + off:base + off + length]
                else:
                    part = os.path.join(os.path.dirname(vpk_path), 'pak01_%03d.vpk' % archive)
                    with open(part, 'rb') as f:
                        f.seek(off)
                        payload = f.read(length)
                rel = os.path.join(folder if folder != ' ' else '', name + ('.' + ext if ext != ' ' else ''))
                dst = os.path.join(out_dir, rel)
                os.makedirs(os.path.dirname(dst) or out_dir, exist_ok=True)
                with open(dst, 'wb') as f:
                    f.write(preload + payload)
                n += 1
    return n


# --------------------------------------------------------------------------
# studio model helpers
# --------------------------------------------------------------------------
HEADER_KEYS = ['numbones', 'boneindex', 'numbonecontrollers', 'bonecontrollerindex',
               'numhitboxsets', 'hitboxsetindex', 'numlocalanim', 'localanimindex',
               'numlocalseq', 'localseqindex', 'activitylistversion', 'eventsindexed',
               'numtextures', 'textureindex', 'numcdtextures', 'cdtextureindex',
               'numskinref', 'numskinfamilies', 'skinindex', 'numbodyparts', 'bodypartindex',
               'numlocalattachments', 'localattachmentindex', 'numlocalnodes', 'localnodeindex',
               'localnodenameindex', 'numflexdesc', 'flexdescindex', 'numflexcontrollers',
               'flexcontrollerindex', 'numflexrules', 'flexruleindex', 'numikchains',
               'ikchainindex', 'nummouths', 'mouthindex', 'numlocalposeparameters',
               'localposeparamindex', 'surfacepropindex', 'keyvalueindex', 'keyvaluesize',
               'numlocalikautoplaylocks', 'localikautoplaylockindex']


def hdr_offsets(d):
    off = 76 + 4 + 12 * 6 + 4
    h = {}
    for k in HEADER_KEYS:
        h[k] = struct.unpack_from('<i', d, off)[0]
        off += 4
    return h


def model_skin(d):
    h = hdr_offsets(d)
    if h['numtextures'] < 1:
        return None
    ti = h['textureindex']
    off = ti + struct.unpack_from('<i', d, ti)[0]
    return d[off:off + 128].split(b'\0')[0].decode('ascii', 'replace')


def set_model_skin(d, name):
    """Point the model at another material; the string is appended to the file so
    any length works (the texture struct only stores an offset)."""
    h = hdr_offsets(d)
    ti = h['textureindex']
    off = len(d)
    d += name.encode('ascii') + b'\0'
    struct.pack_into('<i', d, ti, off - ti)
    struct.pack_into('<i', d, 76, len(d))
    return d


# --------------------------------------------------------------------------
# model renderer
# --------------------------------------------------------------------------
def read_vvd(path):
    d = open(path, 'rb').read()
    lods = struct.unpack_from('<8i', d, 16)
    numFixups, fixupStart, vertStart, tanStart = struct.unpack_from('<iiii', d, 48)
    n = lods[0]
    verts = np.zeros((n, 3), np.float32)
    norms = np.zeros((n, 3), np.float32)
    uvs = np.zeros((n, 2), np.float32)
    for i in range(n):
        o = vertStart + i * 48
        verts[i] = struct.unpack_from('<3f', d, o + 16)
        norms[i] = struct.unpack_from('<3f', d, o + 28)
        uvs[i] = struct.unpack_from('<2f', d, o + 40)
    return verts, norms, uvs


def read_vtx(path, num_verts):
    d = open(path, 'rb').read()
    n = len(d)
    for off in range(36, 400):
        try:
            nv, vo, ni, io, ns, so = struct.unpack_from('<6i', d, off)
        except struct.error:
            break
        if nv != num_verts or ni <= 0 or ni % 3 or io <= 0:
            continue
        vs = off + vo
        ix = off + io
        if vs + nv * 9 > n or ix + ni * 2 > n:
            continue
        remap = np.array([struct.unpack_from('<H', d, vs + i * 9 + 4)[0] for i in range(nv)], np.int32)
        if remap.max() >= num_verts:
            continue
        ind = np.frombuffer(d, dtype='<u2', count=ni, offset=ix).astype(np.int32)
        return remap[ind].reshape(-1, 3)
    return np.zeros((0, 3), np.int32)


def render_model(verts, norms, uvs, tris, tex, size=(400, 500), yaw=55.0, ss=2, bg=(0.95, 0.95, 0.96)):
    W, H = size[0] * ss, size[1] * ss
    ang = np.radians(yaw)
    cy, sy = np.cos(ang), np.sin(ang)
    Rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]], np.float32)
    p = verts @ Rz.T
    nrm = norms @ Rz.T
    sx, sz, depth = p[:, 1], p[:, 2], -p[:, 0]
    span = max(float(sx.max() - sx.min()), float(sz.max() - sz.min())) * 1.10
    cx, cz = (sx.min() + sx.max()) / 2, (sz.min() + sz.max()) / 2
    s = min(W, H) / span
    px = (sx - cx) * s + W / 2
    py = H / 2 - (sz - cz) * s
    color = np.empty((H, W, 3), np.float32)
    color[:] = bg
    zbuf = np.full((H, W), 1e9, np.float32)
    light = np.array([0.40, 0.50, 0.75], np.float32)
    light /= np.linalg.norm(light)
    for tri in tris:
        x0, x1, x2 = px[tri]
        y0, y1, y2 = py[tri]
        z0, z1, z2 = depth[tri]
        uv0, uv1, uv2 = uvs[tri]
        xmin = max(0, int(np.floor(min(x0, x1, x2))))
        xmax = min(W - 1, int(np.ceil(max(x0, x1, x2))))
        ymin = max(0, int(np.floor(min(y0, y1, y2))))
        ymax = min(H - 1, int(np.ceil(max(y0, y1, y2))))
        if xmax < xmin or ymax < ymin:
            continue
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if abs(area) < 1e-7:
            continue
        X, Y = np.meshgrid(np.arange(xmin, xmax + 1) + 0.5, np.arange(ymin, ymax + 1) + 0.5)
        w0 = ((x1 - X) * (y2 - Y) - (x2 - X) * (y1 - Y)) / area
        w1 = ((x2 - X) * (y0 - Y) - (x0 - X) * (y2 - Y)) / area
        w2 = 1.0 - w0 - w1
        mask = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        if not mask.any():
            continue
        z = w0 * z0 + w1 * z1 + w2 * z2
        sub = zbuf[ymin:ymax + 1, xmin:xmax + 1]
        keep = mask & (z < sub - 1e-5)
        if not keep.any():
            continue
        u = w0 * uv0[0] + w1 * uv1[0] + w2 * uv2[0]
        v = w0 * uv0[1] + w1 * uv1[1] + w2 * uv2[1]
        tx = np.mod((u * tex.shape[1]).astype(np.int32), tex.shape[1])
        ty = np.mod((v * tex.shape[0]).astype(np.int32), tex.shape[0])
        samp = tex[ty, tx]
        keep = keep & (samp[..., 3] > 127)
        if not keep.any():
            continue
        rgb = samp[..., :3].astype(np.float32) / 255.0
        nn = (w0[..., None] * nrm[tri[0]] + w1[..., None] * nrm[tri[1]] + w2[..., None] * nrm[tri[2]])
        nn /= np.maximum(np.linalg.norm(nn, axis=-1, keepdims=True), 1e-6)
        shade = 0.74 + 0.30 * np.clip((nn * light).sum(-1), 0, None)
        sub[keep] = z[keep]
        csub = color[ymin:ymax + 1, xmin:xmax + 1]
        csub[keep] = np.clip(rgb * shade[..., None], 0, 1)[keep]
    img = Image.fromarray((np.clip(color, 0, 1) * 255).astype(np.uint8), 'RGB')
    return img.resize(size, Image.LANCZOS) if ss != 1 else img


# --------------------------------------------------------------------------
# population scripts
# --------------------------------------------------------------------------
SPECIAL = {'common_male_ceda', 'common_male_ceda_l4d1', 'common_male_riot', 'common_male_riot_l4d1',
           'common_male_clown', 'common_male_jimmy', 'common_male_mud', 'common_male_mud_l4d1',
           'common_male_fallen_survivor', 'common_male_fallen_survivor_l4d1'}

VMT_TEMPLATE = '''"VertexLitGeneric"
{{
       "$basetexture" "models\\infected\\zombie\\{name}"
\t"$nocull" 1
\t"$alphatest" 1
\t"$halflambert" 1
\t"$model" 1
$allowdiffusemodulation 0
$blendtintbybasealpha 0
\t
\t"$phong" "1"
\t"$phongexponent" "15"
\t"$phongboost" "7"
\t"$phongfresnelranges"\t"[0.04 0.4 0.5]"

vertexlitgeneric_dx8
{{
$envmaptint "[.05 .03 .01]"
$envmap env_cubemap
\t$envmapmask "models\\infected\\zombie\\{name}"
}}
vertexlitgeneric_HDR_dx8
{{
$envmaptint "[.22 .12 .07]"
$envmap env_cubemap
\t$envmapmask "models\\infected\\zombie\\{name}"
}}
$halflambert 1
$phong 0
"GPU>=2?$phong" 1
}}
'''


def parse_population(text):
    sections, cur, depth = [], None, 0
    for line in text.splitlines():
        s = line.strip()
        if cur is None:
            m = re.match(r'^([A-Za-z0-9_]+)\s*$', s)
            if m and m.group(1) != 'Population':
                cur = [m.group(1), []]
            continue
        if s == '{':
            depth += 1
        elif s == '}':
            depth -= 1
            if depth == 0:
                sections.append((cur[0], cur[1]))
                cur = None
        elif depth == 1:
            m = re.match(r'^([A-Za-z0-9_]+)\s+(\d+)$', s)
            if m:
                cur[1].append((m.group(1), int(m.group(2))))
    return sections


def write_population(path, sections):
    lines = ['Population', '{']
    for name, entries in sections:
        lines.append('\t' + name)
        lines.append('\t{')
        for m, p in entries:
            lines.append('\t\t%-34s\t%d' % (m, p))
        lines.append('\t}')
        lines.append('')
    lines.append('}')
    open(path, 'w', encoding='utf-8', newline='\r\n').write('\n'.join(lines))


def insert_variant(entries, model, weight):
    fixed = [(m, p) for m, p in entries if m.lower() in SPECIAL]
    flex = [(m, p) for m, p in entries if m.lower() not in SPECIAL and m.lower() != model.lower()]
    budget = 100 - sum(p for _, p in fixed) - weight
    total = sum(p for _, p in flex)
    if total <= 0 or budget <= 0:
        return entries
    scaled = [(m, max(1, int(round(p * budget / total)))) for m, p in flex]
    diff = budget - sum(p for _, p in scaled)
    i = 0
    while diff != 0 and scaled:
        k = i % len(scaled)
        if diff > 0 or scaled[k][1] > 1:
            scaled[k] = (scaled[k][0], scaled[k][1] + (1 if diff > 0 else -1))
            diff += -1 if diff > 0 else 1
        i += 1
        if i > 1000:
            break
    return fixed + scaled + [(model, weight)]


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
DEFAULT_MOD = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Deathcraft Zombies Enhanced')


def md(mod):
    mod = os.path.abspath(mod)
    if not os.path.isdir(os.path.join(mod, 'models', 'infected')):
        raise SystemExit('not a mod folder: %s' % mod)
    return (os.path.join(mod, 'models', 'infected'),
            os.path.join(mod, 'materials', 'models', 'infected', 'zombie'),
            os.path.join(mod, 'scripts'))


def model_paths(mod, model):
    models_dir = md(mod)[0]
    base = model[:-4] if model.lower().endswith('.mdl') else model
    return base, {ext: os.path.join(models_dir, base + ext) for ext in ('.mdl', '.vvd', '.dx90.vtx')}


def cmd_list(args):
    models_dir = md(args.mod)[0]
    rows = []
    for f in sorted(os.listdir(models_dir)):
        if not f.endswith('.mdl') or not f.startswith('common_'):
            continue
        d = bytearray(open(os.path.join(models_dir, f), 'rb').read())
        skin = model_skin(d) or '(none)'
        kind = 'special' if f[:-4] in SPECIAL or f[:-4].endswith(('_gold', '_iron', '_chain')) else 'normal'
        rows.append((f[:-4], skin, kind))
    for name, skin, kind in rows:
        print('%-40s %-26s %s' % (name, skin, kind))
    print('\n%d common infected models' % len(rows))


def cmd_skins(args):
    mat = md(args.mod)[1]
    names = sorted(os.path.splitext(f)[0] for f in os.listdir(mat) if f.lower().endswith('.vtf'))
    for s in names:
        w, h, fmt, mips = vtf_info(os.path.join(mat, s + '.vtf'))
        has_vmt = os.path.exists(os.path.join(mat, s + '.vmt'))
        print('%-26s %-11s %-7s %s' % (s, '%dx%d' % (w, h), FMT_NAMES.get(fmt, fmt),
                                        'vmt ok' if has_vmt else 'VMT MISSING'))
    print('\n%d skins' % len(names))


def cmd_png2vtf(args):
    mat = md(args.mod)[1]
    im = Image.open(args.image).convert('RGBA')
    w, h = im.size
    if w < args.size:
        k = max(1, int(np.ceil(args.size / float(w))))
        im = im.resize((w * k, h * k), Image.NEAREST)
    if im.size[0] % 4 or im.size[1] % 4:
        raise SystemExit('image must be a multiple of 4 pixels (got %dx%d)' % im.size)
    arr = np.array(im)
    if args.format == 'dxt1' and (arr[..., 3] < 255).any():
        print('warning: the image has transparency but --format dxt1 drops alpha (use auto or dxt5)')
    dst = os.path.join(mat, args.name + '.vtf')
    fmt, mips, total = save_vtf(dst, arr, args.format)
    print('%s  %dx%d  %s  %d mips  %.1f KB' % (args.name + '.vtf', im.size[0], im.size[1],
                                               FMT_NAMES.get(fmt), mips, total / 1024.0))
    vmt = os.path.join(mat, args.name + '.vmt')
    if not os.path.exists(vmt):
        open(vmt, 'w', encoding='utf-8').write(VMT_TEMPLATE.format(name=args.name))
        print('created %s.vmt' % args.name)


IMG_EXT = ('.png', '.tga', '.bmp', '.jpg', '.jpeg', '.gif', '.webp')


def safe_name(stem):
    """Model materials are referenced with simple ASCII names."""
    out = ''.join(c if (c.isascii() and (c.isalnum() or c in ' _-.')) else '_' for c in stem)
    out = re.sub(r'_+', '_', out).strip(' _')
    return out


def collect_images(folder, recursive=True):
    found = []
    if recursive:
        for root, _dirs, files in os.walk(folder):
            for fn in sorted(files):
                if fn.lower().endswith(IMG_EXT):
                    found.append(os.path.join(root, fn))
    else:
        for fn in sorted(os.listdir(folder)):
            p = os.path.join(folder, fn)
            if os.path.isfile(p) and fn.lower().endswith(IMG_EXT):
                found.append(p)
    return found


def cmd_batch(args):
    """Convert a whole folder of images into the standard materials tree."""
    src = os.path.abspath(args.folder)
    if not os.path.isdir(src):
        raise SystemExit('not a folder: %s' % src)
    if args.out:
        mat = os.path.join(os.path.abspath(args.out), 'materials', 'models', 'infected', 'zombie') \
            if not args.flat else os.path.abspath(args.out)
    else:
        mat = md(args.mod)[1]
    if not args.dry_run:
        os.makedirs(mat, exist_ok=True)

    files = collect_images(src, recursive=not args.no_recursive)
    if not files:
        raise SystemExit('no images found in %s' % src)
    print('%d image(s) -> %s' % (len(files), mat))
    print('%-30s %-30s %-11s %-6s %s' % ('source', 'skin name', 'size', 'fmt', 'KB'))

    used, renames, ok, skipped = set(), [], 0, []
    for path in files:
        stem = os.path.splitext(os.path.basename(path))[0]
        name = safe_name(stem)
        if not name:
            name = 'skin_%03d' % (len(used) + 1)
        if name != stem:
            renames.append((os.path.relpath(path, src), name))
        base = name
        n = 2
        while name.lower() in used:
            name = '%s_%d' % (base, n)
            n += 1
        used.add(name.lower())

        dst = os.path.join(mat, name + '.vtf')
        if args.dry_run is False and os.path.exists(dst) and not args.overwrite:
            skipped.append((path, 'exists (use --overwrite)'))
            continue
        try:
            im = Image.open(path).convert('RGBA')
        except Exception as exc:
            skipped.append((path, 'cannot open: %s' % exc))
            continue
        w, h = im.size
        if w % 4 or h % 4:
            skipped.append((path, 'size %dx%d is not a multiple of 4 (use 64x32)' % (w, h)))
            continue
        if w < args.size:
            k = max(1, int(np.ceil(args.size / float(w))))
            im = im.resize((w * k, h * k), Image.NEAREST)
        if args.dry_run:
            print('%-30s %-30s %-11s %-6s %s' % (os.path.basename(path), name,
                                                  '%dx%d' % im.size, args.format, '-'))
            ok += 1
            continue
        if args.format == 'dxt1' and (np.array(im)[..., 3] < 255).any():
            print('  warning: %s has transparency but --format dxt1 drops alpha' % os.path.basename(path))
        fmt, mips, total = save_vtf(dst, np.array(im), args.format)
        vmt = os.path.join(mat, name + '.vmt')
        if not args.no_vmt and (args.overwrite or not os.path.exists(vmt)):
            open(vmt, 'w', encoding='utf-8').write(VMT_TEMPLATE.format(name=name))
        print('%-30s %-30s %-11s %-6s %.1f' % (os.path.basename(path), name,
                                               '%dx%d' % im.size, FMT_NAMES.get(fmt, fmt), total / 1024.0))
        ok += 1

    print('\nconverted %d, skipped %d' % (ok, len(skipped)))
    for path, why in skipped:
        print('  skip %s (%s)' % (os.path.basename(path), why))
    if ok and not args.dry_run:
        print('note: these skins are not attached to any model yet. '
              'Run "attach" to attach them all at once, '
              'or "assign"/"copy-model" for a single one.')
    if renames and not args.dry_run:
        note = os.path.join(mat, '_renamed.txt')
        with open(note, 'w', encoding='utf-8') as f:
            for a, b in renames:
                f.write('%s -> %s\n' % (a, b))
        print('some names were sanitised, see %s' % note)


def cmd_export(args):
    """Batch export every skin (or only used ones) to PNG."""
    mat = md(args.mod)[1]
    out = os.path.abspath(args.out) if args.out else os.path.join(os.getcwd(), 'skins_png')
    os.makedirs(out, exist_ok=True)
    used = None
    if args.used_only:
        models_dir = md(args.mod)[0]
        used = set()
        for f in os.listdir(models_dir):
            if f.endswith('.mdl') and f.startswith('common_'):
                skin = model_skin(bytearray(open(os.path.join(models_dir, f), 'rb').read()))
                if skin:
                    used.add(skin.lower())
    n = 0
    for f in sorted(os.listdir(mat)):
        if not f.lower().endswith('.vtf'):
            continue
        name = os.path.splitext(f)[0]
        if used is not None and name.lower() not in used:
            continue
        arr = load_vtf(os.path.join(mat, f))
        Image.fromarray(arr, 'RGBA').save(os.path.join(out, name + '.png'))
        n += 1
    print('exported %d skin(s) to %s' % (n, out))


VAR_SUFFIX = re.compile(r'_(alt|gold|iron|chain|holiday|hivis|tvjli|helmet|leather|worn|v\d+)$')


def model_vertex_count(path):
    """vertex count lives in the .vvd header, not in the .mdl"""
    d = open(path[:-4] + '.vvd', 'rb').read()
    return struct.unpack_from('<i', d, 16)[0]


def skin_has_hat(path):
    """True if the skin paints the helmet/hat layer (upper-right quadrant)."""
    arr = load_vtf(path)
    h, w = arr.shape[:2]
    hat = arr[0:int(h * 0.5), int(w * 0.5):]
    return bool((hat[..., 3] > 127).any())


def unused_skins(mod):
    models_dir, mat, _scripts = md(mod)
    used = set()
    for f in os.listdir(models_dir):
        if f.endswith('.mdl') and f.startswith('common_'):
            skin = model_skin(bytearray(open(os.path.join(models_dir, f), 'rb').read()))
            if skin:
                used.add(skin.lower())
    out = []
    for f in sorted(os.listdir(mat)):
        if f.lower().endswith('.vtf') and os.path.splitext(f)[0].lower() not in used:
            out.append(os.path.splitext(f)[0])
    return out


def candidate_bases(mod):
    """Models that can host a new variant, most frequently spawned first."""
    models_dir, _mat, scripts = md(mod)
    hits = {}
    for path in sorted(p for p in os.listdir(scripts) if p.startswith('population') and p.endswith('.txt')):
        for _name, entries in parse_population(open(os.path.join(scripts, path), encoding='utf-8', errors='replace').read()):
            for m, _perc in entries:
                hits[m.lower()] = hits.get(m.lower(), 0) + 1
    low, high = [], []
    for f in sorted(os.listdir(models_dir)):
        if not f.endswith('.mdl') or not f.startswith('common_'):
            continue
        name = f[:-4]
        if name in SPECIAL or VAR_SUFFIX.search(name):
            continue
        n = model_vertex_count(os.path.join(models_dir, f))
        if n == 288:
            high.append(name)
        elif n == 264:
            low.append(name)
    low.sort(key=lambda m: -hits.get(m.lower(), 0))
    high.sort(key=lambda m: -hits.get(m.lower(), 0))
    return low, high


def cmd_attach(args):
    """Attach every unused skin to a model (as a new variant, or by replacing)."""
    models_dir = md(args.mod)[0]
    low, high = candidate_bases(args.mod)
    skins = args.skins or unused_skins(args.mod)
    if not skins:
        print('no unused skins - nothing to attach')
        return 0
    print('%d skin(s) to attach, mode = %s' % (len(skins), 'replace' if args.replace else 'new variant'))
    print('%-26s %-40s %-6s %s' % ('skin', 'model', 'verts', 'note'))
    li = hi = 0
    done, failed = 0, []
    for skin in skins:
        mat = md(args.mod)[1]
        if not os.path.exists(os.path.join(mat, skin + '.vtf')):
            failed.append((skin, 'no vtf'))
            continue
        try:
            hat = skin_has_hat(os.path.join(mat, skin + '.vtf'))
        except SystemExit as exc:
            failed.append((skin, str(exc)))
            continue
        pool = high if hat else low
        if not pool:
            failed.append((skin, 'no suitable base model'))
            continue
        base = pool[(hi if hat else li) % len(pool)]
        if hat:
            hi += 1
        else:
            li += 1
        if args.replace:
            d = bytearray(open(os.path.join(models_dir, base + '.mdl'), 'rb').read())
            old = model_skin(d)
            if not args.dry_run:
                open(os.path.join(models_dir, base + '.mdl'), 'wb').write(bytes(set_model_skin(d, skin)))
            print('%-26s %-40s %-6s %s -> %s' % (skin, base, model_vertex_count(
                os.path.join(models_dir, base + '.mdl')), old, skin))
            done += 1
            continue
        new = '%s_%s' % (base, re.sub(r'[^a-z0-9]+', '', skin.lower()))[:52]
        new = new.rstrip('_')
        if not new:
            failed.append((skin, 'cannot build a model name'))
            continue
        if os.path.exists(os.path.join(models_dir, new + '.mdl')):
            failed.append((skin, 'model %s already exists' % new))
            continue
        print('%-26s %-40s %-6s %s%%' % (skin, new, model_vertex_count(os.path.join(models_dir, base + '.mdl')),
                                         args.weight))
        if args.dry_run:
            done += 1
            continue
        for ext in ('.mdl', '.vvd', '.dx90.vtx'):
            shutil.copy2(os.path.join(models_dir, base + ext), os.path.join(models_dir, new + ext))
        phy = os.path.join(models_dir, new + '.phy')
        if os.path.exists(phy):
            os.remove(phy)
        d = bytearray(open(os.path.join(models_dir, new + '.mdl'), 'rb').read())
        d[12:76] = b'\0' * 64
        nm = ('infected/%s.mdl' % new).encode('ascii')[:63]
        d[12:12 + len(nm)] = nm
        open(os.path.join(models_dir, new + '.mdl'), 'wb').write(bytes(set_model_skin(d, skin)))
        scripts = md(args.mod)[2]
        for path in sorted(p for p in os.listdir(scripts) if p.startswith('population') and p.endswith('.txt')):
            full = os.path.join(scripts, path)
            sections = parse_population(open(full, encoding='utf-8', errors='replace').read())
            out, n = [], 0
            for name, entries in sections:
                ents = list(entries)
                names = {m.lower() for m, _ in ents}
                if base.lower() in names and new.lower() not in names:
                    ents = insert_variant(ents, new, args.weight)
                    n += 1
                out.append((name, ents))
            if n:
                write_population(full, out)
        done += 1
    print('\nattached %d, failed %d' % (done, len(failed)))
    for skin, why in failed:
        print('  %s: %s' % (skin, why))
    if done and not args.dry_run and not args.replace:
        print('run "check" and "pack" afterwards.')
    return 0


def cmd_vtf2png(args):
    mat = md(args.mod)[1]
    arr = load_vtf(os.path.join(mat, args.name + '.vtf'))
    out = args.out or os.path.join(os.getcwd(), args.name + '.png')
    Image.fromarray(arr, 'RGBA').save(out)
    print('exported', out, '%dx%d' % (arr.shape[1], arr.shape[0]))


def cmd_assign(args):
    base, files = model_paths(args.mod, args.model)
    if not os.path.exists(files['.mdl']):
        raise SystemExit('model not found: %s' % files['.mdl'])
    mat = md(args.mod)[1]
    if not args.force:
        for ext in ('.vmt', '.vtf'):
            p = os.path.join(mat, args.skin + ext)
            if not os.path.exists(p):
                raise SystemExit('skin not found: %s (use --force to skip this check)' % p)
    d = bytearray(open(files['.mdl'], 'rb').read())
    old = model_skin(d)
    open(files['.mdl'], 'wb').write(bytes(set_model_skin(d, args.skin)))
    print('%s: %s -> %s' % (base, old, args.skin))


def cmd_copy_model(args):
    src_base, src_files = model_paths(args.mod, args.source)
    dst_base, dst_files = model_paths(args.mod, args.new)
    for ext in ('.mdl', '.vvd', '.dx90.vtx'):
        if not os.path.exists(src_files[ext]):
            raise SystemExit('source model missing %s' % src_files[ext])
        shutil.copy2(src_files[ext], dst_files[ext])
    phy = os.path.join(os.path.dirname(dst_files['.mdl']), dst_base + '.phy')
    if os.path.exists(phy):
        os.remove(phy)
    d = bytearray(open(dst_files['.mdl'], 'rb').read())
    d[12:76] = b'\0' * 64
    nm = ('infected/%s.mdl' % dst_base).encode('ascii')[:63]
    d[12:12 + len(nm)] = nm
    open(dst_files['.mdl'], 'wb').write(bytes(set_model_skin(d, args.skin)))
    print('copied %s -> %s (skin %s)' % (src_base, dst_base, args.skin))
    scripts = md(args.mod)[2]
    total = 0
    for path in sorted(p for p in os.listdir(scripts) if p.startswith('population') and p.endswith('.txt')):
        full = os.path.join(scripts, path)
        sections = parse_population(open(full, encoding='utf-8', errors='replace').read())
        out, n = [], 0
        for name, entries in sections:
            ents = list(entries)
            names = {m.lower() for m, _ in ents}
            if src_base.lower() in names and dst_base.lower() not in names:
                ents = insert_variant(ents, dst_base, args.weight)
                n += 1
            out.append((name, ents))
        if n:
            write_population(full, out)
            total += n
    print('population: inserted in %d sections at %d%%' % (total, args.weight))
    print('tip: copy a 288-vertex model if the skin has a helmet layer.')


def cmd_preview(args):
    base, files = model_paths(args.mod, args.model)
    mat = md(args.mod)[1]
    d = bytearray(open(files['.mdl'], 'rb').read())
    skin = model_skin(d)
    tex = load_vtf(os.path.join(mat, skin + '.vtf'))
    v, n, uv = read_vvd(files['.vvd'])
    tris = read_vtx(files['.dx90.vtx'], len(v))
    if not len(tris):
        raise SystemExit('cannot parse the model mesh')
    img = render_model(v, n, uv, tris, tex, size=(args.width, args.height), yaw=args.yaw)
    out = args.out or os.path.join(os.getcwd(), base + '_preview.png')
    img.save(out)
    print('preview saved:', out, '(skin %s)' % skin)


def cmd_check(args):
    models_dir, mat, scripts = md(args.mod)
    mats = {os.path.splitext(f)[0].lower() for f in os.listdir(mat) if f.lower().endswith('.vmt')}
    vtfs = {os.path.splitext(f)[0].lower() for f in os.listdir(mat) if f.lower().endswith('.vtf')}
    use, problems = {}, []
    models = [f[:-4] for f in sorted(os.listdir(models_dir)) if f.endswith('.mdl') and f.startswith('common_')]
    for m in models:
        d = bytearray(open(os.path.join(models_dir, m + '.mdl'), 'rb').read())
        if struct.unpack_from('<i', d, 76)[0] != len(d):
            problems.append('%s: header length != file size' % m)
        skin = model_skin(d)
        if skin is None:
            problems.append('%s: no material' % m)
            continue
        use.setdefault(skin.lower(), []).append(m)
        if skin.lower() not in mats:
            problems.append('%s: missing %s.vmt' % (m, skin))
        if skin.lower() not in vtfs:
            problems.append('%s: missing %s.vtf' % (m, skin))
    for skin, ms in use.items():
        sp = [m for m in ms if m in SPECIAL]
        no = [m for m in ms if m not in SPECIAL]
        if sp and no:
            problems.append('skin %s used by both special(%s) and normal(%s)' % (skin, ','.join(sp), ','.join(no)))
    for skin in sorted(vtfs - set(use)):
        problems.append('skin %s is not used by any model' % skin)
    if [f for f in os.listdir(models_dir) if f.endswith('.phy')]:
        problems.append('.phy files found - they make ragdolls twist, delete them')
    for path in sorted(p for p in os.listdir(scripts) if p.startswith('population') and p.endswith('.txt')):
        for name, ents in parse_population(open(os.path.join(scripts, path), encoding='utf-8', errors='replace').read()):
            if sum(p for _, p in ents) != 100:
                problems.append('%s / %s: percentages do not add up to 100' % (path, name))
            for m, _ in ents:
                if m.lower().startswith('common_') and m.lower() not in {x.lower() for x in models}:
                    problems.append('%s: unknown model %s' % (path, m))
    print('%d models, %d skins, %d in use' % (len(models), len(vtfs), len(use)))
    if problems:
        print('\n%d problem(s):' % len(problems))
        for p in problems:
            print('  -', p)
        return 1
    print('all checks passed')
    return 0


def cmd_pack(args):
    mod = os.path.abspath(args.mod)
    out = args.out or os.path.join(os.path.dirname(mod), os.path.basename(mod) + '.vpk')
    count, tsize, dsize = vpk_pack(mod, out)
    print('packed %d file(s) -> %s (tree %d, data %d)' % (count, out, tsize, dsize))


def cmd_install(args):
    mod = os.path.abspath(args.mod)
    vpk = args.vpk or os.path.join(os.path.dirname(mod), os.path.basename(mod) + '.vpk')
    if not os.path.exists(vpk):
        raise SystemExit('vpk not found: %s (run pack first)' % vpk)
    shutil.copy2(vpk, args.addons)
    print('copied to', os.path.join(args.addons, os.path.basename(vpk)))


def cmd_extract(args):
    out = args.out or os.path.join(os.getcwd(), os.path.splitext(os.path.basename(args.vpk))[0])
    n = vpk_extract(args.vpk, out)
    print('extracted %d entries to %s' % (n, out))


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Deathcraft Zombies Enhanced skin tool (self contained)',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='examples:\n'
               '  python skin_tool.py list\n'
               '  python skin_tool.py newskin my_zombie.png shirt10zom\n'
               '  python skin_tool.py assign common_male01 shirt10zom\n'
               '  python skin_tool.py preview common_male01\n'
               '  python skin_tool.py check\n'
               '  python skin_tool.py pack\n')
    ap.add_argument('--mod', default=DEFAULT_MOD, help='mod folder (default: ../Deathcraft Zombies Enhanced)')
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--mod', default=argparse.SUPPRESS, help='mod folder (before or after the command)')
    sub = ap.add_subparsers(dest='cmd', required=True)

    p = sub.add_parser('list', parents=[common], help='list every model and the skin it uses')
    p.set_defaults(func=cmd_list)

    p = sub.add_parser('skins', parents=[common], help='list every skin file and its size')
    p.set_defaults(func=cmd_skins)

    p = sub.add_parser('png2vtf', parents=[common], help='convert an image into a mod VTF (+VMT)')
    p.add_argument('image')
    p.add_argument('name', help='skin name, becomes <name>.vtf / <name>.vmt')
    p.add_argument('--size', type=int, default=512, help='minimum width, default 512')
    p.add_argument('--format', choices=['auto', 'dxt5', 'dxt1'], default='auto')
    p.set_defaults(func=cmd_png2vtf)

    p = sub.add_parser('newskin', parents=[common], help='same as png2vtf')
    p.add_argument('image')
    p.add_argument('name')
    p.add_argument('--size', type=int, default=512)
    p.add_argument('--format', choices=['auto', 'dxt5', 'dxt1'], default='auto')
    p.set_defaults(func=cmd_png2vtf)

    p = sub.add_parser('vtf2png', parents=[common], help='export a skin to PNG')
    p.add_argument('name')
    p.add_argument('out', nargs='?')
    p.set_defaults(func=cmd_vtf2png)

    p = sub.add_parser('batch', parents=[common],
                       help='convert a whole folder of images into the standard materials tree')
    p.add_argument('folder', help='folder with the skin images')
    p.add_argument('out', nargs='?', help='output root (default: write into the mod)')
    p.add_argument('--size', type=int, default=512, help='minimum width, default 512')
    p.add_argument('--format', choices=['auto', 'dxt5', 'dxt1'], default='auto')
    p.add_argument('--no-vmt', action='store_true', help='do not create .vmt files')
    p.add_argument('--no-recursive', action='store_true', help='only the top folder')
    p.add_argument('--overwrite', action='store_true', help='overwrite existing files')
    p.add_argument('--flat', action='store_true', help='write straight into the output folder')
    p.add_argument('--dry-run', action='store_true', help='only list what would be done')
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser('export', parents=[common], help='export all skins to PNG (batch)')
    p.add_argument('out', nargs='?')
    p.add_argument('--used-only', action='store_true', help='only skins that a model uses')
    p.set_defaults(func=cmd_export)

    p = sub.add_parser('attach', parents=[common],
                       help='attach every unused skin to a model (batch assign / batch variant)')
    p.add_argument('skins', nargs='*', help='only these skin names (default: all unused skins)')
    p.add_argument('--weight', type=int, default=4, help='spawn chance for new variants, default 4')
    p.add_argument('--replace', action='store_true',
                   help='replace the base model skin instead of creating a variant')
    p.add_argument('--dry-run', action='store_true', help='only show the plan')
    p.set_defaults(func=cmd_attach)

    p = sub.add_parser('assign', parents=[common], help='point a model at another skin')
    p.add_argument('model', help='model name, e.g. common_male01')
    p.add_argument('skin', help='skin name (file name in materials, no extension)')
    p.add_argument('--force', action='store_true', help='write even if the skin files are missing')
    p.set_defaults(func=cmd_assign)

    p = sub.add_parser('copy-model', parents=[common], help='duplicate a model as a new variant')
    p.add_argument('source')
    p.add_argument('new')
    p.add_argument('skin')
    p.add_argument('--weight', type=int, default=4, help='spawn chance in percent, default 4')
    p.set_defaults(func=cmd_copy_model)

    p = sub.add_parser('preview', parents=[common], help='render a preview of a model')
    p.add_argument('model')
    p.add_argument('out', nargs='?')
    p.add_argument('--width', type=int, default=400)
    p.add_argument('--height', type=int, default=500)
    p.add_argument('--yaw', type=float, default=55.0)
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser('check', parents=[common], help='validate skins, materials and population files')
    p.set_defaults(func=cmd_check)

    p = sub.add_parser('pack', parents=[common], help='build the VPK from the mod folder')
    p.add_argument('out', nargs='?')
    p.set_defaults(func=cmd_pack)

    p = sub.add_parser('install', parents=[common], help='copy the VPK into the game addons folder')
    p.add_argument('addons')
    p.add_argument('vpk', nargs='?')
    p.set_defaults(func=cmd_install)

    p = sub.add_parser('extract', parents=[common], help='unpack a VPK')
    p.add_argument('vpk')
    p.add_argument('out', nargs='?')
    p.set_defaults(func=cmd_extract)

    args = ap.parse_args(argv)
    return args.func(args) or 0


if __name__ == '__main__':
    sys.exit(main())
