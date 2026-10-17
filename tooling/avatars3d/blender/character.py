"""Constructor parametrico de avatares de busto en Blender (todo por codigo, sin assets).

Piezas: cabeza (superficie analitica con rasgos por campos gaussianos), ojos con iris procedural,
parpados que giran, pestanas, cejas y boca reconstruidas por expresion, mechones de pelo como
tubos afilados con colision, gorro de punto acanalado, jersey con punto y trenza en geometria real,
bufanda de cuadros y los indicadores de estado. Los datos del personaje viven en un spec (nicole.py).
Coordenadas: Z arriba, la cara mira a -Y, +X es la derecha de la imagen.
"""
import colorsys
import math
import os

import bpy
import numpy as np
from mathutils import Euler, Vector
from mathutils.bvhtree import BVHTree

TAU = 2 * math.pi


# ---------------------------------------------------------------- utilidades

def lin(hexstr):
    """'#rrggbb' sRGB -> RGBA lineal (lo que esperan los nodos)."""
    c = [int(hexstr[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
    return (c[0], c[1], c[2], 1.0)


def ss(e0, e1, x):
    t = np.clip((np.asarray(x, float) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def unit(v):
    return v / (np.linalg.norm(v, axis=-1, keepdims=True) + 1e-12)


def grid_faces(nu, nv, closed_u=False, closed_v=False, flip=False):
    iu = np.arange(nu if closed_u else nu - 1)
    iv = np.arange(nv if closed_v else nv - 1)
    i, j = (a.ravel() for a in np.meshgrid(iu, iv, indexing='ij'))
    f = np.stack([i * nv + j, ((i + 1) % nu) * nv + j, ((i + 1) % nu) * nv + (j + 1) % nv, i * nv + (j + 1) % nv], 1)
    ci = np.stack([i, i + 1, i + 1, i], 1)
    cj = np.stack([j, j, j + 1, j + 1], 1)
    if flip:
        f, ci, cj = f[:, ::-1], ci[:, ::-1], cj[:, ::-1]
    return f, ci, cj


class Part:
    """Malla en arrays (verts, caras quad, uv por esquina, color por vertice) para concatenar antes de crearla."""

    def __init__(self, v, f, uv=None, col=None):
        self.v, self.f, self.uv, self.col = np.asarray(v, float).reshape(-1, 3), np.asarray(f), uv, col

    @staticmethod
    def join(parts):
        vs, fs, uvs, cols, off = [], [], [], [], 0
        for p in parts:
            vs.append(p.v)
            fs.append(p.f + off)
            uvs.append(p.uv if p.uv is not None else np.zeros(p.f.shape + (2,)))
            cols.append(p.col if p.col is not None else np.ones((len(p.v), 4)))
            off += len(p.v)
        return Part(np.concatenate(vs), np.concatenate(fs), np.concatenate(uvs), np.concatenate(cols))

    def mirrored_x(self):
        v = self.v.copy()
        v[:, 0] *= -1
        return Part(v, self.f[:, ::-1], None if self.uv is None else self.uv[:, ::-1], self.col)


def make_object(name, part, mat=None, parent=None, smooth=True, colors=False, colname='lockcol'):
    me = bpy.data.meshes.new(name)
    v = part.v.astype(np.float32)
    f = part.f.astype(np.int32)
    me.vertices.add(len(v))
    me.vertices.foreach_set('co', v.ravel())
    me.loops.add(f.size)
    me.loops.foreach_set('vertex_index', f.ravel())
    me.polygons.add(len(f))
    me.polygons.foreach_set('loop_start', np.arange(0, f.size, f.shape[1], dtype=np.int32))
    me.update(calc_edges=True)
    if part.uv is not None:
        me.uv_layers.new(name='UVMap').data.foreach_set('uv', np.asarray(part.uv, np.float32).ravel())
    if colors and part.col is not None:
        me.color_attributes.new(colname, 'FLOAT_COLOR', 'POINT').data.foreach_set(
            'color', np.asarray(part.col, np.float32).ravel())
    me.validate(clean_customdata=False)
    if smooth:
        me.shade_smooth()
    ob = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(ob)
    if mat:
        me.materials.append(mat)
    if parent:
        ob.parent = parent
    return ob


def add_shape_keys(ob, shapes):
    """Una shape key por expresion sobre la malla base (misma topologia): {nombre: Part}."""
    ob.shape_key_add(name='Basis', from_mix=False)
    for name, part in shapes.items():
        key = ob.shape_key_add(name=name, from_mix=False)
        key.data.foreach_set('co', part.v.astype(np.float32).ravel())
    return ob


def set_shape(ob, name):
    for key in ob.data.shape_keys.key_blocks[1:]:
        key.value = 1.0 if key.name == name else 0.0


def empty(name, parent=None, loc=(0, 0, 0), rot=(0, 0, 0)):
    ob = bpy.data.objects.new(name, None)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    ob.location = loc
    ob.rotation_euler = rot
    return ob


def sphere_part(radius=1.0, nu=48, nv=24, el0=-90.0, el1=90.0, ph0=-180.0, ph1=180.0):
    """Esfera (o casquete) parametrizada: phi=0 mira a -Y, normales hacia fuera."""
    closed = ph1 - ph0 >= 360
    ph = np.radians(np.linspace(ph0, ph1, nu, endpoint=not closed))
    el = np.radians(np.linspace(el0, el1, nv))
    P, E = np.meshgrid(ph, el, indexing='ij')
    d = np.stack([np.cos(E) * np.sin(P), -np.cos(E) * np.cos(P), np.sin(E)], -1)
    f, ci, cj = grid_faces(nu, nv, closed_u=closed)
    uv = np.stack([ci / max(nu - 1, 1), cj / (nv - 1)], -1)
    return Part(d.reshape(-1, 3) * radius, f, uv)


def sweep(P, O, w, h, na=16, closed=False, expo=2.0, mod=None, hoff=None):
    """Tubo de seccion superelipse a lo largo de P. O orienta el grosor (h) hacia fuera; w es el ancho.
    mod(i, th) multiplica el radio de la seccion; hoff(i, th) desplaza en la direccion del grosor."""
    P = np.asarray(P, float)
    n = len(P)
    if closed:
        T = np.roll(P, -1, 0) - np.roll(P, 1, 0)
    else:
        T = np.gradient(P, axis=0)
    T = unit(T)
    W = unit(np.cross(T, O))
    H = np.cross(W, T)
    th = np.linspace(0, TAU, na, endpoint=False)
    c, s = np.cos(th), np.sin(th)
    c = np.sign(c) * np.abs(c) ** (2 / expo)
    s = np.sign(s) * np.abs(s) ** (2 / expo)
    ii = np.arange(n)[:, None]
    m = mod(ii, th[None, :]) if mod else 1.0
    dw = np.asarray(w, float)[:, None] * c[None, :] * m
    dh = np.asarray(h, float)[:, None] * s[None, :] * m
    if hoff:
        dh = dh + hoff(ii, th[None, :])
    V = P[:, None, :] + dw[..., None] * W[:, None, :] + dh[..., None] * H[:, None, :]
    f, ci, cj = grid_faces(n, na, closed_u=closed, closed_v=True)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    if closed:
        arc = np.append(arc, arc[-1] + np.linalg.norm(P[0] - P[-1]))
    perim = np.linspace(0, 1, na + 1)
    uv = np.stack([arc[ci], perim[cj]], -1)
    part = Part(V.reshape(-1, 3), f, uv)
    mid = V[n // 2]
    part.perim = float(np.linalg.norm(np.roll(mid, -1, 0) - mid, axis=1).sum())
    return part


def smooth_path(P, it=3, keep_root=True):
    P = P.copy()
    for _ in range(it):
        Q = P.copy()
        Q[1:-1] = 0.5 * P[1:-1] + 0.25 * (P[:-2] + P[2:])
        if keep_root:
            Q[0] = P[0]
        P = Q
    return P


class Surface:
    """BVH sobre una malla en arrays para rayos y colision."""

    def __init__(self, part):
        self.part = part
        self.bvh = BVHTree.FromPolygons(part.v.tolist(), part.f.tolist())

    def ray(self, origin, direction):
        loc, nor, _, _ = self.bvh.ray_cast(Vector(origin), Vector(direction))
        return (None, None) if loc is None else (np.array(loc), np.array(nor))

    def front(self, x, z):
        return self.ray((x, -6.0, z), (0, 1, 0))

    def push_out(self, P, margin, start=1):
        for i in range(start, len(P)):
            loc, nor, _, dist = self.bvh.find_nearest(Vector(P[i]))
            if loc is None:
                continue
            m = margin[i] if np.ndim(margin) else margin
            if (Vector(P[i]) - loc).dot(nor) < 0 or dist < m:
                P[i] = np.array(loc + nor * m)
        return P


class Tube:
    """Colisionador analitico de un tubo de seccion eliptica (brazo de arm_sleeve): eje P con marco H/W y semiejes
    hh (H) y rr (W). push_out solo mueve los puntos de dentro, en su seccion, hasta el borde + margen (los extremos
    abiertos no empujan)."""

    def __init__(self, P, H, W, rr, hh, pad=0.05):
        self.P, self.H, self.W, self.rr, self.hh, self.pad = P, H, W, rr, hh, pad

    def mirrored_x(self):
        m = np.array([-1.0, 1.0, 1.0])
        return Tube(self.P * m, self.H * m, self.W * m, self.rr, self.hh, self.pad)

    def push_out(self, P, margin, start=1):
        P = np.array(P, float)
        for i in range(start, len(P)):
            j = int(np.linalg.norm(self.P - P[i], axis=1).argmin())
            if j == 0 or j == len(self.P) - 1:
                continue
            d = P[i] - self.P[j]
            a, b = d @ self.H[j], d @ self.W[j]
            m = (margin[i] if np.ndim(margin) else margin) + self.pad
            q = math.hypot(a / (self.hh[j] + m), b / (self.rr[j] + m))
            if q < 1:
                P[i] = P[i] + (a / max(q, 1e-3) - a) * self.H[j] + (b / max(q, 1e-3) - b) * self.W[j]
        return P


class Surfaces:
    """Varias superficies que se solapan (torso y brazos): push_out contra cada una por turnos; con la union la cara
    mas cercana de un punto metido en el brazo puede ser la del torso que queda dentro y no se empujaria.
    items: Part (-> Surface) u objetos con push_out (Tube)."""

    def __init__(self, items, rounds=2):
        self.surfs = [Surface(p) if isinstance(p, Part) else p for p in items]
        self.rounds = rounds

    def push_out(self, P, margin, start=1):
        for _ in range(self.rounds):
            for s in self.surfs:
                P = s.push_out(P, margin, start)
        return P


def orient_out(part, inside):
    """Deja las normales de un tubo cerrado hacia fuera (inside: un punto interior, p. ej. el eje)."""
    bvh = BVHTree.FromPolygons(part.v.tolist(), part.f.tolist())
    loc, nor, _, _ = bvh.find_nearest(Vector(inside))
    if loc is not None and (Vector(inside) - loc).dot(nor) > 0:
        part.f = part.f[:, ::-1].copy()
        if part.uv is not None:
            part.uv = part.uv[:, ::-1].copy()
    return part


def drape(V, surfs, axis_y, gap, per_ring=True, iters=4):
    """Cuelga una pieza por encima de otras (pelo sobre la bufanda) empujando solo hacia fuera del eje vertical
    (x=0, y=axis_y). V: (n, m, 3) con el indice 0 hacia abajo (anillos de un mechon o filas de un volumen).
    Lo que queda por debajo de un contacto sigue fuera (maximo acumulado hacia abajo), como una cortina, y por
    encima el empuje se desvanece suave. per_ring: cada anillo se mueve entero (mechones); si no, por vertice."""
    V = V.copy()
    n, m = V.shape[:2]
    for _ in range(iters):
        R = V * np.array([1.0, 1.0, 0.0]) - np.array([0.0, axis_y, 0.0])
        R = R / np.maximum(np.linalg.norm(R, axis=-1, keepdims=True), 1e-6)
        A = np.zeros((n, m))
        for surf in surfs:
            for i in range(n):
                for j in range(m):
                    p = Vector(V[i, j])
                    loc, nor, _, dist = surf.bvh.find_nearest(p)
                    if loc is None or dist > gap + 0.3:
                        continue
                    sd = (p - loc).dot(nor)
                    inside = sd < -0.5 * dist
                    if inside:
                        hit = surf.bvh.ray_cast(p, Vector(R[i, j]))[0]
                        a = (hit - p).length + gap if hit is not None else 0.0
                    elif dist < gap and sd >= 0:
                        a = gap - dist
                    else:
                        continue
                    A[i, j] = max(A[i, j], a)
        if A.max() < 1e-4:
            break
        if per_ring:
            A = np.repeat(A.max(1, keepdims=True), m, 1)
        A = np.maximum.accumulate(A, 0)
        for _ in range(4):
            E = np.concatenate([A[:1], A, A[-1:]], 0)
            B = 0.5 * A + 0.25 * (E[:-2] + E[2:])
            if not per_ring:
                E = np.concatenate([B[:, :1], B, B[:, -1:]], 1)
                B = 0.5 * B + 0.25 * (E[:, :-2] + E[:, 2:])
            A = np.maximum(A, B)
        if per_ring:
            C = V.mean(1)
            Rc = C * np.array([1.0, 1.0, 0.0]) - np.array([0.0, axis_y, 0.0])
            Rc = Rc / np.maximum(np.linalg.norm(Rc, axis=-1, keepdims=True), 1e-6)
            V += (A[:, :1] * Rc)[:, None, :]
        else:
            V += A[..., None] * R
    return V


def up_dir(V):
    return np.tile([0.0, 0.0, 1.0], (len(V), 1))


def radial_dir(axis_y):
    """Hacia fuera desde el eje vertical del cuello (x=0, y=axis_y)."""
    def f(V):
        d = V * np.array([1.0, 1.0, 0.0]) - np.array([0.0, axis_y, 0.0])
        return d / np.maximum(np.linalg.norm(d, axis=-1, keepdims=True), 1e-6)
    return f


def overlap_faces(a, b):
    """Pares (cara de a, cara de b) que se cruzan entre dos mallas (BVH overlap)."""
    ta = BVHTree.FromPolygons(a.v.tolist(), a.f.tolist())
    tb = BVHTree.FromPolygons(b.v.tolist(), b.f.tolist())
    return ta.overlap(tb)


def check_overlaps(pairs):
    """Chequeo de interpenetracion: imprime '[check] OK|AVISO a x b: N caras'. Devuelve cuantos pares fallan."""
    bad = 0
    for na_, a, nb_, b in pairs:
        hits = overlap_faces(a, b)
        k = len(hits)
        bad += k > 0
        where = ''
        if k:
            c = np.array([a.v[a.f[i]].mean(0) for i, _ in hits])
            where = ' en x[{:.2f},{:.2f}] y[{:.2f},{:.2f}] z[{:.2f},{:.2f}]'.format(
                *np.stack([c.min(0), c.max(0)], 1).ravel())
        print(f'[check] {"AVISO" if k else "OK"} {na_} x {nb_}: {k} caras{where}', flush=True)
    return bad


# ---------------------------------------------------------------- materiales

class NB:
    """Ayudante para montar arboles de nodos de sombreado en pocas lineas."""

    def __init__(self, name):
        self.mat = bpy.data.materials.new(name)
        self.mat.use_nodes = True
        self.nt = self.mat.node_tree
        self.nt.nodes.clear()
        self.out = self.nt.nodes.new('ShaderNodeOutputMaterial')

    def node(self, kind, **props):
        n = self.nt.nodes.new(kind)
        for k, v in props.items():
            setattr(n, k, v)
        return n

    def put(self, sock, val):
        if isinstance(val, bpy.types.NodeSocket):
            self.nt.links.new(val, sock)
        elif val is not None:
            sock.default_value = val

    def math(self, op, a, b=None, c=None, clamp=False):
        n = self.node('ShaderNodeMath', operation=op, use_clamp=clamp)
        for sock, v in zip(n.inputs, (a, b, c)):
            self.put(sock, v)
        return n.outputs[0]

    def vmath(self, op, a, b=None, scale=None):
        n = self.node('ShaderNodeVectorMath', operation=op)
        self.put(n.inputs[0], a)
        if b is not None:
            self.put(n.inputs[1], b)
        if scale is not None:
            self.put(n.inputs['Scale'], scale)
        return n.outputs['Value'] if op in ('DOT_PRODUCT', 'DISTANCE', 'LENGTH') else n.outputs['Vector']

    def maprange(self, x, a, b, c=0.0, d=1.0, interp='SMOOTHSTEP'):
        n = self.node('ShaderNodeMapRange', interpolation_type=interp, clamp=True)
        for name, v in (('Value', x), ('From Min', a), ('From Max', b), ('To Min', c), ('To Max', d)):
            self.put(n.inputs[name], v)
        return n.outputs['Result']

    def mix(self, fac, a, b, blend='MIX'):
        n = self.node('ShaderNodeMix', data_type='RGBA', blend_type=blend, clamp_result=True)
        socks = [s for s in n.inputs if s.type == 'RGBA']
        self.put(n.inputs['Factor'], fac)
        self.put(socks[0], a)
        self.put(socks[1], b)
        return [s for s in n.outputs if s.type == 'RGBA'][0]

    def ramp(self, x, stops):
        n = self.node('ShaderNodeValToRGB')
        el = n.color_ramp.elements
        while len(el) < len(stops):
            el.new(0.5)
        for e, (pos, col) in zip(el, stops):
            e.position, e.color = pos, col
        self.put(n.inputs['Fac'], x)
        return n.outputs['Color']

    def texco(self, obj=None):
        n = self.node('ShaderNodeTexCoord')
        if obj is not None:
            n.object = obj
        return n

    def uv_xy(self):
        tc = self.node('ShaderNodeTexCoord')
        sep = self.node('ShaderNodeSeparateXYZ')
        self.nt.links.new(tc.outputs['UV'], sep.inputs[0])
        return sep.outputs['X'], sep.outputs['Y'], tc.outputs['UV']

    def noise(self, vec, scale, detail=2.0, rough=0.5):
        n = self.node('ShaderNodeTexNoise')
        self.put(n.inputs['Vector'], vec)
        n.inputs['Scale'].default_value = scale
        n.inputs['Detail'].default_value = detail
        n.inputs['Roughness'].default_value = rough
        return n.outputs['Fac']

    def bump(self, height, strength, distance=0.02):
        n = self.node('ShaderNodeBump')
        self.put(n.inputs['Height'], height)
        n.inputs['Strength'].default_value = strength
        n.inputs['Distance'].default_value = distance
        return n.outputs['Normal']

    def principled(self, **inp):
        n = self.node('ShaderNodeBsdfPrincipled')
        for k, v in inp.items():
            self.put(n.inputs[k.replace('_', ' ')], v)
        self.nt.links.new(n.outputs[0], self.out.inputs['Surface'])
        return n

    def emission(self, color, strength):
        n = self.node('ShaderNodeEmission')
        n.inputs['Color'].default_value = color
        n.inputs['Strength'].default_value = strength
        self.nt.links.new(n.outputs[0], self.out.inputs['Surface'])


def mat_skin(S, head_obj, spots, sss=0.35, name='skin', sss_scale=0.08):
    """Piel con subsurface real; rubor y punta de nariz por distancia en coordenadas de la cabeza."""
    nb = NB(name)
    co = nb.texco(head_obj).outputs['Object']
    col = S['skin']
    for center, radius, tint, amount in spots:
        d = nb.vmath('DISTANCE', co, center)
        m = nb.maprange(d, radius, 0.0)
        col = nb.mix(nb.math('MULTIPLY', m, amount), col, tint)
    # micro-variacion de tono y poros muy sutiles (a 512 px apenas se intuyen; dan textura de piel al zoom)
    # skin_mottle / skin_grain (opcionales, 1.0 por defecto): atenuan la mancha de color y el grano de la piel
    mot, grain = S.get('skin_mottle', 1.0), S.get('skin_grain', 1.0)
    tone = nb.noise(co, 9.0, 3.0, 0.55)
    col = nb.mix(nb.math('MULTIPLY', nb.maprange(tone, 0.35, 0.65), 0.1 * mot), col, S['blush'])
    # rubor irregular: manchas suaves mas calidas y otras algo mas palidas
    warm = nb.noise(co, 4.0, 2.0, 0.5)
    col = nb.mix(nb.math('MULTIPLY', nb.maprange(warm, 0.5, 0.7), 0.08 * mot), col, S['blush'])
    col = nb.mix(nb.math('MULTIPLY', nb.maprange(warm, 0.45, 0.3), 0.05 * mot), col, (1.0, 0.93, 0.86, 1.0))
    fuzz = nb.noise(co, 60.0, 2.0)
    pores = nb.node('ShaderNodeTexVoronoi', feature='F1')
    nb.put(pores.inputs['Vector'], co)
    pores.inputs['Scale'].default_value = 420.0
    rough = nb.maprange(nb.noise(co, 25.0, 2.0), 0.3, 0.7, 0.4, 0.58)
    # micro-relieve en tres escalas: ondulacion suave (se ve a 512), grano y poros (al zoom)
    wave = nb.noise(co, 18.0, 3.0, 0.6)
    h = nb.math('ADD', nb.math('MULTIPLY', fuzz, 0.35 * grain), nb.math('MULTIPLY', pores.outputs['Distance'], 0.4 * grain))
    h = nb.math('ADD', h, nb.math('MULTIPLY', wave, 0.6))
    # SSS variable: zonas algo mas translucidas (mejillas, nariz) y otras mas opacas
    sssw = nb.maprange(nb.noise(co, 6.0, 2.0, 0.5), 0.35, 0.65, sss * 0.75, sss * 1.25)
    nb.principled(Base_Color=col, Roughness=rough, Subsurface_Weight=sssw, Subsurface_Radius=(1.0, 0.38, 0.22),
                  Subsurface_Scale=sss_scale, Coat_Weight=0.08, Coat_Roughness=0.35, Sheen_Weight=0.25,
                  Sheen_Roughness=0.4, Normal=nb.bump(h, 0.12, 0.006))
    return nb.mat


def mat_flat(name, color, rough=0.5, coat=0.0, sss=0.0, sheen=0.0, emit=None):
    nb = NB(name)
    if emit:
        nb.emission(color, emit)
    else:
        nb.principled(Base_Color=color, Roughness=rough, Coat_Weight=coat, Coat_Roughness=0.08,
                      Subsurface_Weight=sss, Subsurface_Radius=(1.0, 0.4, 0.3), Subsurface_Scale=0.03,
                      Sheen_Weight=sheen, Sheen_Roughness=0.3)
    return nb.mat


def mat_brow(S):
    """Ceja: pelos finos (franjas por la fase del atributo 'browcol'), raiz y borde algo mas claros y un borde
    que se deshilacha en pelos y se funde con la piel (transparencia), en vez de un corte limpio."""
    nb = NB('brow')
    attr = nb.node('ShaderNodeAttribute', attribute_name='browcol')
    sep = nb.node('ShaderNodeSeparateColor')
    nb.nt.links.new(attr.outputs['Color'], sep.inputs[0])
    t, edge, phase = sep.outputs[0], sep.outputs[1], sep.outputs[2]
    along = attr.outputs['Alpha']
    co = nb.texco().outputs['Object']
    phase = nb.math('ADD', phase, nb.math('MULTIPLY', nb.noise(co, 30.0, 1.0), 0.9))

    def layer(shift):
        # franja estrecha por pelo, cortada a lo largo en trazos que se afilan, desfasados por pelo
        ph = nb.math('ADD', phase, shift)
        idx = nb.math('FLOOR', ph)
        wn = nb.node('ShaderNodeTexWhiteNoise', noise_dimensions='1D')
        nb.put(wn.inputs['W'], nb.math('ADD', idx, shift * 17.0))
        across = nb.math('FRACT', ph)
        stripe = nb.math('MULTIPLY', nb.maprange(across, 0.15, 0.5), nb.maprange(across, 0.85, 0.5))
        seg = nb.math('FRACT', nb.math('ADD', along, wn.outputs['Value']))
        stroke = nb.math('MULTIPLY', nb.maprange(seg, 0.0, 0.2), nb.maprange(seg, 0.95, 0.45))
        return nb.math('MULTIPLY', stripe, stroke)

    hair = nb.math('MAXIMUM', layer(0.0), layer(0.5))
    # pieza suave (como la v3): el pelo solo se ve en la franja del borde; el cuerpo es un degradado liso,
    # mas claro y transparente en el inicio, mas oscuro en el centro y hacia la cola
    rim = nb.maprange(edge, 0.5, 0.88)
    hair_rim = nb.math('MULTIPLY', hair, rim)
    light = nb.math('MAXIMUM', nb.math('MULTIPLY', nb.maprange(t, 0.22, 0.0), 0.65),
                    nb.math('MULTIPLY', rim, 0.35))
    base = nb.mix(light, S['brow'], S['brow_light'])
    base = nb.mix(nb.math('MULTIPLY', nb.maprange(edge, 0.45, 0.0), nb.maprange(t, 0.1, 0.4)), base,
                  S['brow_dark'])
    col = nb.mix(nb.math('MULTIPLY', hair_rim, 0.25), base, S['brow_dark'])
    bsdf = nb.principled(Base_Color=col, Roughness=0.55, Sheen_Weight=0.25, Sheen_Roughness=0.35,
                         Normal=nb.bump(hair_rim, 0.06, 0.0015))
    # borde: pelos muy finos que apenas pasan del contorno (sin dientes) y fundido ancho; el inicio se funde con la piel
    reach = nb.math('SUBTRACT', edge, nb.math('MULTIPLY', hair, 0.09))
    alpha = nb.maprange(reach, 0.56, 0.97, 1.0, 0.0)
    root = nb.maprange(nb.math('SUBTRACT', t, nb.math('MULTIPLY', hair, 0.05)), 0.0, 0.12, 0.05, 1.0)
    alpha = nb.math('MULTIPLY', alpha, root)
    tr = nb.node('ShaderNodeBsdfTransparent')
    mix = nb.node('ShaderNodeMixShader')
    nb.put(mix.inputs[0], alpha)
    nb.nt.links.new(tr.outputs[0], mix.inputs[1])
    nb.nt.links.new(bsdf.outputs[0], mix.inputs[2])
    nb.nt.links.new(mix.outputs[0], nb.out.inputs['Surface'])
    return nb.mat


def mat_lip(S):
    """Labio: color calido que se funde con la piel en el borde (atributo 'lipfade'), brillo suave."""
    nb = NB('lip')
    attr = nb.node('ShaderNodeAttribute', attribute_name='lipfade')
    co = nb.texco().outputs['Object']
    lines = nb.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction='X', wave_profile='SIN')
    nb.put(lines.inputs['Vector'], co)
    lines.inputs['Scale'].default_value = 60.0
    lines.inputs['Distortion'].default_value = 2.0
    col = nb.mix(attr.outputs['Fac'], S['skin'], S['lip'])
    nb.principled(Base_Color=col, Roughness=0.3, Coat_Weight=0.35, Coat_Roughness=0.15, Subsurface_Weight=0.3,
                  Subsurface_Radius=(1.0, 0.4, 0.3), Subsurface_Scale=0.03,
                  Normal=nb.bump(lines.outputs['Fac'], 0.06, 0.004))
    return nb.mat


def mat_eye(S):
    """Esclerotica + iris degradado con anillo oscuro y pupila, todo por angulo desde el eje de mirada."""
    nb = NB('eye')
    co = nb.texco().outputs['Object']
    d = nb.vmath('NORMALIZE', co)
    cosang = nb.vmath('DOT_PRODUCT', d, (0.0, -1.0, 0.0))
    iris_size = nb.node('ShaderNodeValue', label='iris')
    iris_size.outputs[0].default_value = S['iris_ang']
    rr = nb.math('DIVIDE', nb.math('ARCCOSINE', cosang), iris_size.outputs[0])
    pupil = nb.node('ShaderNodeValue', label='pupil')
    pupil.outputs[0].default_value = S['pupil']
    nb.pupil_node = pupil
    sep = nb.node('ShaderNodeSeparateXYZ')
    nb.nt.links.new(d, sep.inputs[0])
    # degradado radial: centro calido, collarete claro, borde oscuro y anillo limbal ancho y suave
    iris = nb.ramp(rr, [(0.0, S['iris_in']), (0.42, S['iris_mid']), (0.74, S['iris_out']), (0.9, S['iris_ring']),
                        (1.0, S['iris_ring'])])
    collar = nb.math('MULTIPLY', nb.maprange(rr, 0.42, 0.52), nb.maprange(rr, 0.7, 0.55))
    iris = nb.mix(nb.math('MULTIPLY', collar, 0.35), iris, S['iris_glow'])
    glow = nb.math('MULTIPLY', nb.maprange(sep.outputs['Z'], 0.0, -0.45), nb.maprange(rr, 1.0, 0.35))
    iris = nb.mix(nb.math('MULTIPLY', glow, 0.75), iris, S['iris_glow'])
    # estrias radiales: ruido que solo depende del angulo alrededor del eje de mirada
    ang = nb.node('ShaderNodeCombineXYZ')
    nb.put(ang.inputs['X'], sep.outputs['X'])
    nb.put(ang.inputs['Y'], sep.outputs['Z'])
    radial = nb.vmath('NORMALIZE', ang.outputs[0])
    rad3 = nb.vmath('ADD', nb.vmath('SCALE', radial, scale=1.0), nb.vmath('SCALE', (0.0, 0.0, 1.0), scale=rr))
    fib = nb.noise(nb.vmath('MULTIPLY', rad3, (6.0, 6.0, 0.6)), 4.0, 4.0, 0.65)
    fibc = nb.maprange(fib, 0.35, 0.7)
    iris = nb.mix(nb.math('MULTIPLY', fibc, 0.45), iris, S['iris_glow'], 'OVERLAY')
    dark = nb.noise(nb.vmath('MULTIPLY', d, (1.0, 0.2, 1.0)), 22.0, 3.0, 0.6)
    iris = nb.mix(nb.math('MULTIPLY', dark, 0.25), iris, S['iris_out'], 'MULTIPLY')
    pm = nb.maprange(rr, nb.math('SUBTRACT', pupil.outputs[0], 0.03), nb.math('ADD', pupil.outputs[0], 0.015))
    iris = nb.mix(pm, (0.01, 0.006, 0.004, 1.0), iris)
    sclera = nb.mix(nb.maprange(cosang, 0.35, -0.2), S['sclera'], S['sclera_edge'])
    im = nb.maprange(rr, 1.02, 0.97)
    col = nb.mix(im, sclera, iris)
    nb.principled(Base_Color=col, Roughness=0.3, Coat_Weight=1.0, Coat_Roughness=0.02, Coat_IOR=1.45,
                  Subsurface_Weight=0.15, Subsurface_Radius=(1.0, 0.5, 0.4), Subsurface_Scale=0.02)
    return nb.mat, pupil, iris_size


def mat_hair(S):
    """Cabello: color por mechon (atributo lockcol) con degradado raiz oscura -> punta calida (alfa = t a lo largo),
    pelo fino a lo largo en bump y brillo anisotropico suave."""
    nb = NB('hair')
    attr = nb.node('ShaderNodeAttribute', attribute_name='lockcol')
    u, v, uvv = nb.uv_xy()
    # hair_ramp (opcional): multiplicador de color raiz -> punta (por defecto raiz oscura y punta calida)
    shade = nb.ramp(attr.outputs['Alpha'], S.get('hair_ramp', [(0.0, (0.4, 0.38, 0.38, 1)), (0.3, (0.72, 0.7, 0.7, 1)),
                                                            (0.7, (0.9, 0.84, 0.78, 1)), (1.0, (1.12, 0.98, 0.82, 1))]))
    col = nb.mix(1.0, attr.outputs['Color'], shade, 'MULTIPLY')
    # hebras finas: bandas a lo largo del mechon (u = longitud, v = contorno), un poco onduladas
    stri = nb.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction='Y', wave_profile='SIN')
    nb.put(stri.inputs['Vector'], uvv)
    stri.inputs['Scale'].default_value = 32.0
    stri.inputs['Distortion'].default_value = 1.2
    stri.inputs['Detail'].default_value = 3.0
    stri.inputs['Detail Scale'].default_value = 1.5
    col = nb.mix(nb.math('MULTIPLY', stri.outputs['Fac'], 0.1), col, S['hair_dark'])
    tan = nb.node('ShaderNodeTangent', direction_type='UV_MAP', uv_map='UVMap')
    # brillo contenido (pelo de peluche, no de plastico): anisotropia y specular bajos, sin coat
    nb.principled(Base_Color=col, Roughness=0.62, Anisotropic=0.4, Tangent=tan.outputs[0],
                  Specular_IOR_Level=0.18, Specular_Tint=S['hair_spec'], Sheen_Weight=0.12, Sheen_Tint=S['hair_spec'],
                  Sheen_Roughness=0.45, Subsurface_Weight=0.08, Subsurface_Radius=(1.0, 0.5, 0.3),
                  Subsurface_Scale=0.02, Normal=nb.bump(stri.outputs['Fac'], 0.12, 0.004))
    return nb.mat


def mat_wool(name, color, fuzz_scale=90.0, cavity=None):
    """Lana: sheen alto, rugosa, con microfibra en bump; el relieve del punto va en la geometria.
    cavity: atributo de vertice (0 hondo .. 1 alto) que oscurece los surcos para que las trenzas se lean con luz frontal."""
    nb = NB(name)
    co = nb.texco().outputs['Object']
    fz = nb.noise(co, fuzz_scale, 4.0, 0.7)
    var = nb.noise(co, 6.0, 2.0)
    c = nb.mix(nb.math('MULTIPLY', var, 0.25), color, (color[0] * 0.8, color[1] * 0.78, color[2] * 0.76, 1))
    if cavity:
        attr = nb.node('ShaderNodeAttribute', attribute_name=cavity)
        dark = (color[0] * 0.55, color[1] * 0.5, color[2] * 0.44, 1)
        c = nb.mix(nb.math('SUBTRACT', 1.0, attr.outputs['Fac']), c, dark)
    halo = nb.maprange(nb.noise(co, fuzz_scale * 0.25, 3.0, 0.6), 0.4, 0.7, 0.8, 1.0)
    nb.principled(Base_Color=c, Roughness=0.9, Specular_IOR_Level=0.25, Sheen_Weight=halo, Sheen_Roughness=0.6,
                  Sheen_Tint=(1, 1, 1, 1),
                  Subsurface_Weight=0.12, Subsurface_Radius=(1, 0.8, 0.6), Subsurface_Scale=0.02,
                  Normal=nb.bump(fz, 0.35, 0.01))
    return nb.mat


def mat_plaid(S):
    """Cuadros grandes (dos bandas cruzadas y su solape) con bordes suaves de lana y sarga fina."""
    nb = NB('plaid')
    u, v, uvv = nb.uv_xy()
    p = S['plaid_period']

    def band(x, period):
        f = nb.math('FRACT', nb.math('DIVIDE', x, period))
        tri = nb.math('ABSOLUTE', nb.math('SUBTRACT', f, 0.5))
        return nb.maprange(tri, 0.235, 0.265)

    bu = band(u, p)
    bv = band(nb.math('MULTIPLY', v, S['plaid_v_scale']), p)
    stripes = nb.math('ADD', bu, bv)
    col = nb.ramp(nb.math('MULTIPLY', stripes, 0.5),
                  [(0.0, S['plaid_base']), (0.5, S['plaid_mid']), (1.0, S['plaid_dark'])])
    thin = band(nb.math('ADD', u, p * 0.25), p * 0.5)
    line = nb.math('MULTIPLY', nb.maprange(thin, 0.9, 1.0), nb.math('SUBTRACT', 1.0, nb.math('MINIMUM', stripes, 1.0)))
    col = nb.mix(nb.math('MULTIPLY', line, 0.0), col, S['plaid_mid'])
    tw = nb.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction='DIAGONAL')
    nb.put(tw.inputs['Vector'], uvv)
    tw.inputs['Scale'].default_value = 40.0
    rows = nb.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction='X', wave_profile='SIN')
    nb.put(rows.inputs['Vector'], uvv)
    rows.inputs['Scale'].default_value = 9.0
    fz = nb.noise(uvv, 120.0, 4.0, 0.7)
    fib = nb.noise(nb.vmath('MULTIPLY', uvv, (2.0, 45.0, 1.0)), 6.0, 3.0, 0.6)
    fz = nb.math('ADD', fz, nb.math('MULTIPLY', nb.maprange(fib, 0.45, 0.75), 0.6))
    h = nb.math('ADD', nb.math('MULTIPLY', tw.outputs['Fac'], 0.4),
                nb.math('ADD', nb.math('MULTIPLY', rows.outputs['Fac'], 0.6), fz))
    nb.principled(Base_Color=col, Roughness=0.95, Specular_IOR_Level=0.2, Sheen_Weight=1.0, Sheen_Roughness=0.35,
                  Subsurface_Weight=0.1, Subsurface_Radius=(1, 0.7, 0.6), Subsurface_Scale=0.02,
                  Normal=nb.bump(h, 0.55, 0.01))
    return nb.mat


# ---------------------------------------------------------------- cabeza

def head_points(D, S):
    """Direcciones unitarias -> superficie de la cabeza (elipsoide + mandibula + rasgos gaussianos)."""
    x, y, z = D[..., 0], D[..., 1], D[..., 2]
    lower = ss(0.05, -1.0, z)
    X = x * S['head_w'] * (1 - S['jaw_taper'] * lower ** 1.2)
    Y = y * np.where(y < 0, S['head_front'], S['head_back']) * (1 - np.where(y > 0, 0.32, 0.03) * lower)
    Z = z * np.where(z > 0, S['head_top'], S['head_bot'])
    P = np.stack([X, Y, Z], -1)
    bump = np.zeros(x.shape)
    for (bx, by, bz), amp, sig, mirror in S['head_bumps']:
        for sx in ((-1, 1) if mirror else (1,)):
            c = np.array([bx * sx, by, bz])
            c /= np.linalg.norm(c)
            ang = np.arccos(np.clip(D @ c, -1, 1))
            bump += amp * np.exp(-(ang / sig) ** 2)
    return P + D * bump[..., None]


def build_head(S):
    nu, nv = 256, 180
    ph = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    el = np.linspace(-np.pi / 2, np.pi / 2, nv)
    P, E = np.meshgrid(ph, el, indexing='ij')
    D = np.stack([np.cos(E) * np.sin(P), -np.cos(E) * np.cos(P), np.sin(E)], -1)
    V = head_points(D, S)
    f, ci, cj = grid_faces(nu, nv, closed_u=True)
    return Part(V.reshape(-1, 3), f, np.stack([ci / nu, cj / (nv - 1)], -1))


# ---------------------------------------------------------------- ojos

def build_eye(S, s, center, mats, parent):
    re = S['eye_r']
    sock = empty(f'eye{s:+d}_socket', parent, center,
                 (0, math.radians(-s * S['eye_tilt']), math.radians(s * S['eye_yaw'])))
    ball = make_object(f'eye{s:+d}_ball', sphere_part(re, 64, 48), mats['eye'], sock)
    catches = []
    # reflejos: dos discos emisivos fijos al hueco (no giran con la mirada), solo visibles para camara
    for k, (dx, dz, r) in enumerate(S['catchlights']):
        d = Vector((dx, -1.0, dz)).normalized()
        cl = make_object(f'eye{s:+d}_catch{k}', sphere_part(1.0, 40, 20), mats['catch'], sock)
        cl.location = d * re * 1.03
        cl.rotation_mode = 'QUATERNION'
        cl.rotation_quaternion = d.to_track_quat('-Y', 'Z')
        cl.scale = (r, r * 0.15, r)
        catches.append(cl)
        for attr in ('visible_diffuse', 'visible_glossy', 'visible_transmission', 'visible_shadow',
                     'visible_volume_scatter'):
            setattr(cl, attr, False)
    lids, lidmesh = {}, {}
    rl = re * 1.06
    for which, (e0, e1) in (('up', (0.0, 90.0)), ('lo', (-90.0, 0.0))):
        piv = empty(f'eye{s:+d}_lid_{which}', sock)
        part = sphere_part(rl, 48, 20, e0, e1, -118, 118)
        edge_el = 0.0
        # borde redondeado del parpado
        ang = np.radians(np.linspace(-118, 118, 60))
        ring = np.stack([rl * np.sin(ang), -rl * np.cos(ang), np.full_like(ang, edge_el)], -1)
        # borde con grosor: mas grueso en el centro, afinado hacia los lagrimales
        tk = S['lid_thick'] * (0.55 + 0.45 * np.cos(ang * 0.75)) * (1.0 if which == 'up' else 0.8)
        rim = sweep(ring, ring / rl, tk, tk, 12)
        lid = Part.join([part, rim])
        if s < 0:
            lid = lid.mirrored_x()
        lidmesh[which] = make_object(f'eye{s:+d}_lidmesh_{which}', lid, mats['skin_local'], piv)
        if which == 'lo':
            # linea de agua: tubo fino y brillante sobre el borde interior del parpado inferior
            wa = np.radians(np.linspace(-100, 100, 50))
            rw = re * 1.005
            wl = np.stack([rw * np.sin(wa), -rw * np.cos(wa), np.full_like(wa, 0.004)], -1)
            ww = 0.006 * np.cos(wa * 0.85) + 0.002
            tear = sweep(wl, wl / rw, ww, ww * 0.7, 8)
            if s < 0:
                tear = tear.mirrored_x()
            make_object(f'eye{s:+d}_waterline', tear, mats['tear'], piv)
        lash = build_lash(S, rl, which)
        if s < 0:
            lash = lash.mirrored_x()
        make_object(f'eye{s:+d}_lash_{which}', lash, mats['lash'], piv)
        lids[which] = piv
    return dict(socket=sock, ball=ball, lids=lids, lidmesh=lidmesh, n_dome=48 * 20, rl=rl, s=s, catches=catches)


def conform_lids(eye, sock_mw, head_surf, poses, fillet=0.0):
    """Una shape key por expresion en cada parpado: la cupula se hunde justo bajo la piel donde el globo
    queda dentro de la cabeza, asi solo asoma el parpado sobre el ojo visible (sin disco alrededor).
    Con los ojos cerrados la cupula entra en la piel con un 'smooth min' de ancho `fillet` (cuenca esculpida:
    el parpado se funde con la mejilla y la frente en vez de marcar el borde circular del globo).
    poses: {expresion: (lid_up, lid_lo, tilt)}."""
    s, rl, n = eye['s'], eye['rl'], eye['n_dome']
    re = rl / 1.06
    center = np.array(sock_mw.translation)
    R3 = np.array(sock_mw.to_3x3())
    for which in ('up', 'lo'):
        ob = eye['lidmesh'][which]
        base = np.empty(len(ob.data.vertices) * 3, np.float32)
        ob.data.vertices.foreach_get('co', base)
        base = base.reshape(-1, 3)
        shapes = {}
        for name, (lid_up, lid_lo, tilt) in poses.items():
            k = fillet if lid_lo >= lid_up - 4 else 0.0
            ang = (-lid_up, tilt * s) if which == 'up' else (-lid_lo, tilt * s * 0.4)
            Rl = np.array(Euler((math.radians(ang[0]), math.radians(ang[1]), 0)).to_matrix())
            V = base.copy()
            dirs = unit((R3 @ Rl @ V[:n].T).T)
            for i, dv in enumerate(dirs):
                loc, _ = head_surf.ray(center, dv)
                d = np.linalg.norm(loc - center) if loc is not None else 9.0
                if k > 0 and d < 9.0:
                    # hueco parpado-piel suavizado hacia 0: la cupula baja tangente hasta la piel y se mete
                    g = rl - d
                    hh = max(k - abs(g), 0.0) / k
                    r = d + max(g, 0.0) + hh * hh * k * 0.25 - 0.004 - 0.015 * ss(-0.6 * k, -1.3 * k, g)
                else:
                    w = ss(re * 0.97, re * 1.05, d)
                    r = rl * (1 - w) + min(rl, d - 0.006) * w
                V[i] *= r / rl
            shapes[name] = Part(V, np.zeros((0, 4), int))
        add_shape_keys(ob, shapes)



def build_lash(S, rl, which):
    """Linea de pestanas sobre el borde del parpado y, arriba, tres pestanas en la esquina exterior."""
    if which == 'up':
        ang = np.radians(np.linspace(-70, 72, 40))
        t = (ang - ang[0]) / (ang[-1] - ang[0])
        r = rl + 0.008
        P = np.stack([r * np.sin(ang), -r * np.cos(ang), 0.006 + 0.004 * t], -1)
        O = unit(P * np.array([1, 1, 0]) + np.array([0, 0, 0.4]) * r)
        w = S['lash_w'] * (0.55 + 0.9 * t ** 1.5) * ss(0, 0.08, t)
        parts = [sweep(P, O, w, w * 0.8, 10)]
        for a, length, lift in S['lash_flicks']:
            a = math.radians(a)
            base = np.array([r * math.sin(a), -r * math.cos(a), 0.004])
            out = np.array([math.sin(a), -math.cos(a), 0.0])
            tt = np.linspace(0, 1, 10)[:, None]
            Q = base + out * length * tt + np.array([0.35, -0.2, lift]) * length * tt ** 1.6
            parts.append(sweep(Q, np.tile([0, -1, 0.3], (10, 1)), 0.016 * (1 - tt[:, 0]) + 0.002,
                               0.010 * (1 - tt[:, 0]) + 0.002, 8))
        return Part.join(parts)
    ang = np.radians(np.linspace(5, 62, 20))
    t = (ang - ang[0]) / (ang[-1] - ang[0])
    r = rl + 0.004
    P = np.stack([r * np.sin(ang), -r * np.cos(ang), np.full_like(ang, -0.004)], -1)
    w = 0.008 * np.sin(np.pi * t) + 0.002
    return sweep(P, unit(P), w, w * 0.6, 8)


def build_crease(S, s, sock_mw, head_surf, lid_up):
    """Surco del parpado superior: arco proyectado sobre la piel justo por encima del borde del parpado
    (en su pose neutra), como una arruga suave en relieve."""
    re = S['eye_r'] * 1.06
    el = math.radians(lid_up + S['crease_gap'])
    az = np.radians(np.linspace(-62, 74, 40))
    pts, nors = [], []
    for a in az:
        d = Vector((s * math.sin(a) * math.cos(el), -math.cos(a) * math.cos(el), math.sin(el)))
        q = sock_mw @ (d * re)
        loc, nor = head_surf.front(q.x, q.z)
        pts.append(loc + nor * 0.002)
        nors.append(nor)
    P, N = np.array(pts), np.array(nors)
    t = np.linspace(0, 1, len(az))
    w = S['crease_w'] * np.sin(np.pi * t) ** 0.8 + 0.001
    return sweep(P, N, w, w * 0.35, 10)


def pose_eye(eye, lid_up, lid_lo, gaze, tilt):
    s = eye['s']
    eye['ball'].rotation_euler = (math.radians(gaze[1]), 0, math.radians(gaze[0]))
    eye['lids']['up'].rotation_euler = (math.radians(-lid_up), math.radians(tilt * s), 0)
    eye['lids']['lo'].rotation_euler = (math.radians(-lid_lo), math.radians(tilt * s * 0.4), 0)


def pose_eye_bones(pose, eye, lid_up, lid_lo, gaze, tilt):
    """Igual que pose_eye pero sobre los huesos del rig (eye/lid_up/lid_lo .L/.R)."""
    s, b = eye['s'], eye['bones']
    pose[b['eye']].rotation_euler = (math.radians(gaze[1]), 0, math.radians(gaze[0]))
    pose[b['up']].rotation_euler = (math.radians(-lid_up), math.radians(tilt * s), 0)
    pose[b['lo']].rotation_euler = (math.radians(-lid_lo), math.radians(tilt * s * 0.4), 0)


# ---------------------------------------------------------------- cejas y boca (dependen de la expresion)

def brow_part(S, head_surf, s, dz):
    """Ceja continua pegada a la frente: una sola pieza afilada hacia la cola, sin mechones sueltos.
    El pelo fino, el degradado y el borde suave los pone mat_brow con el atributo 'browcol' por vertice:
    R = t a lo largo (0 = inicio), G = cercania al borde (0 centro, 1 borde), B = fase de los pelos (en pelos),
    A = posicion a lo largo de cada pelo (en largos de pelo); vertical al inicio, tumbados hacia la cola.
    dz = desplazamiento (interior, medio, exterior). Topologia fija para las shape keys."""
    (x0, z0), (x1, z1), (x2, z2) = S['brow_pts']
    n, na = 32, 16
    t = np.linspace(0, 1, n)
    xs = (1 - t) ** 2 * x0 + 2 * t * (1 - t) * x1 + t ** 2 * x2
    zb = (1 - t) ** 2 * z0 + 2 * t * (1 - t) * z1 + t ** 2 * z2
    zb = zb + dz[0] * (1 - t) ** 2 + dz[1] * 2 * t * (1 - t) + dz[2] * t ** 2
    pts, nors = [], []
    for x, z in zip(xs * s, zb):
        loc, nor = head_surf.front(x, z)
        pts.append(loc + nor * 0.013)
        nors.append(nor)
    P, N = np.array(pts), np.array(nors)
    # inicio ancho con remate redondeado (no romo) y cola fina
    w = S['brow_w'] * (1.0 - 0.72 * t ** 1.1) * (1 - 0.6 * ss(0.78, 1.0, t)) * np.sqrt(np.clip(1 - (1 - np.clip((t + 0.015) / 0.13, 0, 1)) ** 2, 0, 1))
    part = sweep(P, N, w + 0.002, w * 0.22 + 0.004, na, expo=2.4)
    th = np.linspace(0, TAU, na, endpoint=False)
    c = np.cos(th)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    # W = T x N apunta hacia abajo en el lado +1: 'up' es la distancia hacia arriba sobre la frente
    up = -s * c[None, :] * w[:, None]
    ang = np.radians(72 - 55 * t ** 0.8)[:, None]
    phase = (up * np.cos(ang) - arc[:, None] * np.sin(ang)) / S['brow_hair']
    along = (up * np.sin(ang) + arc[:, None] * np.cos(ang)) / S['brow_hair_len']
    edge = np.abs(np.sign(c) * np.abs(c) ** (2 / 2.4))[None, :] * np.ones((n, 1))
    part.col = np.stack([np.repeat(t, na), edge.ravel(), phase.ravel(), along.ravel()], -1)
    return part


def mouth_parts(S, head_surf, m):
    """Boca proyectada sobre la cara: hueco, dientes, lengua, linea y dos labios con volumen.
    La topologia es fija para todas las expresiones (las piezas que no se usan se colapsan), asi
    cada expresion es una shape key de la misma malla."""
    cx, cz = S['mouth_center']
    w = m['w']
    xs = np.linspace(-1, 1, 41)
    shift = m.get('shift', 0.0)
    cl, cr = m['cl'], m['cr']
    wave = m.get('wave', 0.0)
    opn = m['open'] if m['open'] > 0.005 else 0.0
    corner = cl * (1 - xs) / 2 + cr * (1 + xs) / 2
    up = corner + (m['up'] - (cl + cr) / 2) * (1 - xs ** 2) + wave * np.sin(3 * np.pi * xs) * (1 - xs ** 2)
    lo = up - opn * (1 - xs ** 2) ** 0.75 - wave * 1.6 * np.sin(3 * np.pi * xs + 0.4) * (1 - xs ** 2) * (opn > 0)
    X = cx + shift + xs * w
    t = (xs + 1) / 2
    taper = np.sin(np.pi * t) ** 0.6

    def proj(xv, zv, lift):
        out, nor = [], []
        for x, z, li in zip(xv, zv, np.broadcast_to(lift, np.shape(xv))):
            loc, n = head_surf.front(x, cz + z)
            out.append(loc + n * li)
            nor.append(n)
        return np.array(out), np.array(nor)

    def strip(top, bot, lift, rows=6, fade=None):
        grid = [proj(X, bot + (top - bot) * k / (rows - 1), lift(k / (rows - 1)) if callable(lift) else lift)[0]
                for k in range(rows)]
        G = np.stack(grid, 1)
        f, ci, cj = grid_faces(len(X), rows)
        part = Part(G.reshape(-1, 3), f, np.stack([ci / len(X), cj / rows], -1))
        if fade is not None:
            a = np.stack([fade(k / (rows - 1)) for k in range(rows)], 1).reshape(-1)
            part.col = np.stack([a, a, a, np.ones_like(a)], -1)
        return part

    parts = {}
    parts['cavity'] = strip(up, lo, 0.004)
    th = m.get('teeth_h', 0.05) * np.clip(1 - (xs / 0.82) ** 2, 0, 1) ** 0.5 * bool(m.get('teeth') and opn)
    th_lo = th * bool(m.get('teeth_lo'))
    parts['teeth'] = Part.join([strip(up, np.maximum(lo, up - th), 0.007), strip(np.minimum(up, lo + th_lo), lo, 0.007)])
    k = np.clip(1 - (xs / 0.75) ** 2, 0, 1) * bool(m.get('tongue') and opn)
    parts['tongue'] = strip(lo + opn * 0.45 * k, lo, 0.006)
    # labios: perfil de volumen p(q), q=0 en la linea de la boca y q=1 en el borde con la piel
    thin = (0.17 / w) ** 0.5
    vol = m.get('lips', 1.0)  # <1: labios casi planos (boca de linea sencilla)

    def bulge(q, amount):
        p = 0.3 * (1 - q) + 0.75 * np.sin(np.pi * q) ** 0.7
        return 0.0015 + amount * vol * p * taper ** 0.8

    def fade(q):
        return (1 - ss(0.72, 1.0, q)) * ss(0.0, 0.35, taper)

    base_up = up + (0.004 if opn else 0.0)
    base_lo = lo - (0.006 if opn else 0.0)
    bow = vol * S['lip_up_h'] * thin * (1 - xs ** 2) ** 0.55 * (1 - 0.4 * np.exp(-(xs / 0.12) ** 2)
                                                          + 0.22 * np.exp(-((np.abs(xs) - 0.3) / 0.14) ** 2))
    parts['lip_up'] = strip(base_up + bow, base_up, lambda r: bulge(r, S['lip_up_lift']), 8, fade)
    drop = vol * S['lip_lo_h'] * thin * (1 - xs ** 2) ** 0.7
    parts['lip_lo'] = strip(base_lo, base_lo - drop, lambda r: bulge(1 - r, S['lip_lo_lift']), 8,
                            lambda r: fade(1 - r))
    P_line, N_line = proj(X, base_up if opn else up, 0.25 * vol * S['lip_up_lift'] * taper ** 0.8)
    parts['line'] = sweep(P_line, N_line, 0.006 * taper + 0.002, 0.004 * taper + 0.0015, 10)
    # lengua fuera por un lado (colapsada si la expresion no la usa)
    side = m.get('tongue_out') or -1
    loc, n = head_surf.front(cx + shift + side * w * 0.55, cz + corner[0 if side < 0 else -1] - 0.03)
    tp = sphere_part(1.0, 24, 12)
    size = np.array([0.05, 0.03, 0.045]) if m.get('tongue_out') else np.full(3, 1e-4)
    tp.v = tp.v * size + loc + n * 0.02
    parts['tongue_out'] = tp
    return parts


# ---------------------------------------------------------------- pelo

def lock_path(p, head_r, y_ax, n=48):
    # len < 1: el mechon acaba antes sobre el mismo camino (largos distintos sin romper la envolvente comun)
    t = np.linspace(0, p.get('len', 1.0), n)
    z = p['z'] - p['drop'] * t ** p.get('ease', 1.2)
    phi = (p['phi'] + p.get('sweep', 0) * ss(0, p.get('sweep_end', 0.3), t)
           + p.get('drift', 0) * ss(0.35, 1.0, t)
           + p['wphi'] * np.sin(TAU * p['k'] * t + p['ph']) * t ** 0.8)
    r = np.empty(n)
    for i in range(n):
        rh = head_r(phi[i], z[i])
        rw = head_r(phi[i], 0.05)
        r[i] = rh if z[i] > 0.05 else max(rw, rh)
    # tuck: la raiz nace pegada a la cabeza (dentro del gorro) y gana volumen al salir por debajo del dobladillo
    tuck = 1 - p.get('tuck', 0.0) * (1 - ss(0.0, 0.2, t))
    # lift: separacion constante de la cabeza (capas de encima): la raiz ya pasa por fuera de la capa de abajo
    r = (r + p.get('lift', 0.0) + p['vol'] * (0.6 + 0.4 * t) * tuck + p.get('flare', 0.2) * ss(0.25, 1.0, t) ** 1.5
         + p['wr'] * np.sin(TAU * p['k'] * t + p['ph'] + 1.2) * ss(0.05, 0.4, t)
         + p.get('curl', 0.0) * ss(0.82, 1.0, t) ** 2)
    P = np.stack([r * np.sin(phi), y_ax - r * np.cos(phi), z], -1)
    return P, t


def lock_frame(P, t, p, y_ax):
    """Orientacion (hacia fuera del eje del pelo), ancho y grosor de un mechon a lo largo de su camino."""
    ctr = np.stack([np.zeros(len(P)), np.full(len(P), y_ax), np.minimum(P[:, 2], 0.25)], -1)
    O = unit(P - ctr)
    t = t / t[-1]
    t0 = p.get('tip0', 0.55)
    w = p['w'] * (0.8 + 0.35 * np.sin(np.pi * np.minimum(t * 1.5, 1))) * (1 - ss(t0, 1.0, t)) ** 0.75 + 0.004
    # wk: el ancho se estrecha y ensancha a lo largo (mechones menos regulares)
    w = w * (1 + p.get('wvar', 0.0) * np.sin(TAU * p.get('wk', 1.0) * t + p.get('wph', 0.0)) * ss(0.1, 0.4, t))
    h = p['h'] * (0.85 + 0.2 * np.sin(np.pi * t)) * (1 - ss(t0 + 0.1, 1.0, t)) ** 0.6 + 0.003
    h *= 1 - 0.7 * p.get('tuck', 0.0) * (1 - ss(0.0, 0.15, t))
    return O, w, h


def lock_strands(P, t, p, rng, y_ax, n):
    """Hebras: cintas finas apoyadas sobre la cara exterior del mechon que se abren un poco en la punta
    (rompen el aspecto de mechon macizo sin pagar el coste de pelo por particulas)."""
    O, w, h = lock_frame(P, t, p, y_ax)
    W = unit(np.cross(unit(np.gradient(P, axis=0)), O))
    out = []
    for a in np.clip(np.linspace(-0.8, 0.8, n) + rng.uniform(-0.12, 0.12, n), -0.9, 0.9):
        m = int(len(P) * rng.uniform(0.72, 1.0))
        tt = t[:m] / t[m - 1]
        side = (a * w[:m] + rng.uniform(-1, 1) * 0.06 * ss(0.45, 1.0, tt)
                + 0.01 * np.sin(TAU * rng.uniform(1.5, 3.5) * tt + rng.uniform(0, TAU)))
        lift = h[:m] * np.sqrt(1 - a * a) * 1.06 + 0.004 + 0.012 * ss(0.6, 1.0, tt) * rng.uniform(0, 1)
        Q = P[:m] + W[:m] * side[:, None] + O[:m] * lift[:, None]
        ws = rng.uniform(0.01, 0.022) * (1 - 0.75 * ss(0.55, 1.0, tt)) + 0.0015
        out.append(sweep(Q, O[:m], ws, ws * 0.3, 6))
    return out


def lock_part(P, t, p, rng, y_ax):
    """Mechon como pieza maciza. Con p['sub'] > 0 es un mechon agrupado (clump): la cara exterior lleva
    sub surcos a lo largo que se hacen mas hondos hacia la punta, como varios mechones finos pegados."""
    O, w, h = lock_frame(P, t, p, y_ax)
    k, ph = rng.integers(4, 7), rng.uniform(0, TAU)
    sub = p.get('sub', 0)
    hoff = None
    if sub:
        tn = t / t[-1]
        g = h * (0.3 + 0.2 * ss(0.2, 0.7, tn)) * (1 - ss(0.8, 1.0, tn)) * p.get('groove', 1.0)
        jit = rng.uniform(-0.25, 0.25)

        def hoff(i, th):
            cw = np.clip(np.cos(th) + jit * 0.3, -1, 1)
            dip = (0.5 + 0.5 * np.cos(np.pi * sub * (cw + 1))) ** 4
            sn = np.sin(th)
            return -g[i] * dip * (np.maximum(sn, 0) ** 0.5 + 0.4 * np.maximum(-sn, 0) ** 0.5)
    part = sweep(P, O, w, h, 24 if sub else 16, mod=lambda i, th: 1 + 0.05 * np.sin(k * th + ph), expo=p.get('expo', 2.2),
                 hoff=hoff)
    part.uv = part.uv.copy()
    part.uv[..., 0] = np.clip(part.uv[..., 0], 0, None)
    part.t = np.repeat(t, part.v.shape[0] // len(t))
    return part


def clear_over(P, surfs, y_ax, gap, half_w=0.0, slope=0.45, root=0.0):
    """Aparta el camino de un mechon por fuera de las piezas de abajo (bufanda) con la misma envolvente para todos
    los mechones vecinos: radio de la bufanda en cada azimut y altura + gap (en el centro y a +-half_w de lado),
    acumulado hacia la punta y con una rampa suave por encima del contacto. Asi la melena entera se abomba igual
    sobre la bufanda, sin escalones."""
    R = P * np.array([1.0, 1.0, 0.0]) - np.array([0.0, y_ax, 0.0])
    r = np.linalg.norm(R, axis=1)
    R = R / np.maximum(r[:, None], 1e-6)
    A = np.zeros(len(P))
    for i in range(len(P)):
        side = np.array([-R[i, 1], R[i, 0], 0.0])
        for off in (0.0, -half_w, half_w):
            d = unit(R[i] * r[i] + side * off)
            o = np.array([0.0, y_ax, P[i, 2]]) + d * 4.0
            for surf in surfs:
                loc, _ = surf.ray(o, -d)
                if loc is not None:
                    rs = math.hypot(loc[0], loc[1] - y_ax)
                    A[i] = max(A[i], rs + gap - r[i])
    if A.max() <= 0:
        return P
    if root > 0:
        A *= ss(0.0, root, np.linspace(0, 1, len(P)))
    A = np.maximum.accumulate(A)
    seg = np.concatenate([np.linalg.norm(np.diff(P, axis=0), axis=1), [0.0]])
    for i in range(len(P) - 2, -1, -1):
        A[i] = max(A[i], A[i + 1] - slope * seg[i])
    for _ in range(6):
        E = np.concatenate([A[:1], A, A[-1:]])
        A = np.maximum(A, 0.5 * A + 0.25 * (E[:-2] + E[2:]))
    return P + A[:, None] * R


def tuck_under(V, caps, y_ax, margin=0.03):
    """Mete por dentro del gorro cualquier vertice de pelo a la altura del gorro: rayo horizontal desde fuera hacia
    el eje contra caps (copa primero; si no la toca, la vuelta); si el pelo queda fuera, se lleva a rs - margin."""
    lo = min(c.part.v[:, 2].min() for c in caps)
    for i in np.nonzero(V[:, 2] > lo)[0]:
        R = np.array([V[i, 0], V[i, 1] - y_ax, 0.0])
        r = np.linalg.norm(R)
        if r < 1e-6:
            continue
        d = R / r
        for cap in caps:
            loc, _ = cap.ray(np.array([0.0, y_ax, V[i, 2]]) + d * 4.0, -d)
            if loc is not None:
                rs = math.hypot(loc[0], loc[1] - y_ax)
                if r > rs - margin:
                    V[i, :2] = np.array([0.0, y_ax]) + d[:2] * (rs - margin)
                break
    return V


def build_hair(S, locks, head_surf, collide, rng, cut_z, strands=0, drape_on=(), caps=()):
    """Mechones (y, con strands>0, esas hebras finas por mechon encima, mismo color con variacion).
    drape_on: Surfaces (piezas de bufanda) sobre las que los mechones caen sin atravesarlas."""
    y_ax = S['hair_axis_y']

    def head_r(phi, z):
        d = (math.sin(phi), -math.cos(phi), 0.0)
        loc, _ = head_surf.ray((d[0] * 4, y_ax + d[1] * 4, z), (-d[0], -d[1], 0.0))
        # rayo desde fuera hacia el eje: el primer impacto es la superficie exterior
        if loc is None:
            return 0.0
        return math.hypot(loc[0], loc[1] - y_ax)

    parts = []
    base = np.array(S['hair_base'][:3])
    # capas (p['layer']): cada capa se apoya por fuera de las anteriores con la misma envolvente que la bufanda
    below, layer = [], 0
    for p in locks:
        p = dict(p)
        if p.get('layer', 0) != layer:
            below.append(Surface(Part.join(parts)))
            layer = p['layer']
        if p.get('z') is None:
            p['z'] = cut_z(p['phi']) - p.get('under', 0.1)
        P, t = lock_path(p, head_r, y_ax)
        if below:
            P = clear_over(P, below, y_ax, p['h'] * 1.3, p['w'] * 0.95, root=0.25)
        if drape_on and P[:, 2].min() < -0.5:
            P = clear_over(P, drape_on, y_ax, p['h'] * 1.2 + 0.04, p['w'] * 0.9)
        margin = p['h'] * 1.1 + 0.02
        for _ in range(3):
            P = collide.push_out(P, margin)
            P = smooth_path(P, 2)
        part = lock_part(P, t, p, rng, y_ax)
        if drape_on and part.v[:, 2].min() < -0.5:
            V0 = part.v.reshape(len(P), -1, 3)
            V1 = drape(V0, drape_on, y_ax, 0.03, iters=8)
            if os.environ.get('HAIR_DEBUG'):
                print(f'[hair] phi {math.degrees(p["phi"]):.0f} drape max {np.abs(V1 - V0).max():.3f}', flush=True)
            part.v = V1.reshape(-1, 3)
            P = P + (V1 - V0).mean(1)
        # solo los de atras nacen dentro del gorro; en la sien la vuelta se curva y el recorte rasgaria la raiz
        if caps and math.cos(p['phi']) < -0.08:
            part.v = tuck_under(part.v.copy(), caps, y_ax)
        # tono por mechon: de castano frio y oscuro a miel calida y clara
        tone = rng.uniform(-1, 1)
        tint = base * (1 + 0.24 * tone) * np.array([1.0, 1 + 0.05 * tone + rng.uniform(-0.04, 0.04),
                                                    1 - 0.08 * tone + rng.uniform(-0.08, 0.04)])
        if os.environ.get('HAIR_DEBUG'):
            tint = np.array(colorsys.hsv_to_rgb(len(parts) * 0.13 % 1, 0.9, 0.6))
            print(f'[hair] phi {math.degrees(p["phi"]):.0f} layer {layer} bbox {part.v.min(0).round(2)} {part.v.max(0).round(2)} nan {np.isnan(part.v).any()}', flush=True)
        # alfa = t a lo largo del mechon (raiz oscura, punta calida en mat_hair)
        part.col = np.concatenate([np.tile(tint, (len(part.v), 1)), part.t[:, None]], 1)
        parts.append(part)
        n = strands if p['w'] > 0.05 else 0
        for st in lock_strands(P, t, p, rng, y_ax, n):
            st.col = np.tile(np.append(tint * rng.uniform(0.8, 1.3), 0.7), (len(st.v), 1))
            parts.append(st)
    return Part.join(parts)


def build_hair_shell(S, head_surf, cut_z, collide, drape_on=()):
    """Volumen trasero continuo para que no se vea fondo entre mechones."""
    y_ax = S['hair_axis_y']
    phis = np.radians(np.linspace(58, 302, 90))
    nz = 40
    rows = []
    for phi in phis:
        # shell_top: cuanto sube el volumen por encima del borde del gorro (queda oculto bajo la lana)
        z0 = cut_z(phi if phi <= np.pi else phi - TAU) - S.get('shell_top', 0.05)
        # hacia los lados (donde ya no hay mechones delante) el volumen sube y se pega a la cabeza, y el borde
        # inferior es irregular: asi no asoma como una placa oscura con canto recto sobre la bufanda
        deg = math.degrees(phi)
        e = ss(58, 120, deg) * ss(302, 240, deg)
        bottom = S['shell_bottom'] + (1 - e) * 0.55 + (0.07 * math.sin(phi * 11) + 0.1 * abs(math.sin(phi * 15))) * e
        zs = np.linspace(z0, bottom, nz)
        d = np.array([math.sin(phi), -math.cos(phi), 0.0])
        col = []
        for z in zs:
            loc, _ = head_surf.ray((d[0] * 4, y_ax + d[1] * 4, max(z, -0.6)), -d)
            r = math.hypot(loc[0], loc[1] - y_ax) if loc is not None else 0.9
            r = max(r, 0.95) + 0.03 + 0.25 * ss(-0.4, S['shell_bottom'], z) * (0.3 + 0.7 * e)
            col.append([r * d[0], y_ax + r * d[1], z])
        Q = np.array(col)
        Q = collide.push_out(Q, 0.04, start=0)
        if drape_on:
            Q = clear_over(Q, drape_on, y_ax, 0.07, 0.04)
        rows.append(Q)
    G = np.stack(rows, 0)
    if drape_on:
        # columnas vecinas suavizadas entre si (sin escalones) y un drape por anillo solo para el residuo
        for _ in range(3):
            G[1:-1] = 0.5 * G[1:-1] + 0.25 * (G[:-2] + G[2:])
        G = drape(G.transpose(1, 0, 2), drape_on, y_ax, 0.05, per_ring=False, iters=4).transpose(1, 0, 2)
    f, ci, cj = grid_faces(len(phis), nz, flip=True)
    uv = np.stack([cj / (nz - 1) * 2.4, ci / len(phis) * 6], -1)
    part = Part(G.reshape(-1, 3), f, uv)
    # color de pelo interior (algo mas oscuro, mismo degradado): si asoma entre mechones se lee como profundidad
    tz = np.tile(np.linspace(0.0, 0.55, nz), len(phis))
    part.col = np.concatenate([np.tile(np.array(S['hair_base'][:3]) * 0.55, (len(part.v), 1)), tz[:, None]], 1)
    return part


# ---------------------------------------------------------------- gorro

def beanie_dirs_cut(S, phis):
    """Elevacion del corte del gorro (plano inclinado z = z0 + k*y) para cada azimut."""
    lo = np.full(len(phis), -1.0)
    hi = np.full(len(phis), 1.4)
    for _ in range(40):
        mid = (lo + hi) / 2
        D = np.stack([np.cos(mid) * np.sin(phis), -np.cos(mid) * np.cos(phis), np.sin(mid)], -1)
        P = head_points(D, S)
        f = P[:, 2] - (S['cut_z0'] + S['cut_k'] * P[:, 1])
        hi = np.where(f > 0, mid, hi)
        lo = np.where(f > 0, lo, mid)
    return (lo + hi) / 2


def beanie_surface(S, D):
    P = head_points(D, S)
    slouch_dir = np.array(S['slouch_dir']) / np.linalg.norm(S['slouch_dir'])
    off = S['beanie_off'] + S['slouch'] * np.clip(D @ slouch_dir, 0, 1) ** 2.2
    return P + unit(P) * off[..., None], off


def build_beanie(S):
    nu, nv = 360, 90
    phis = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    el_cut = beanie_dirs_cut(S, phis)
    s = np.linspace(0, 1, nv)
    E = el_cut[:, None] - 0.04 + (np.pi / 2 - el_cut[:, None] + 0.04) * s[None, :] ** 0.9
    Pp = np.broadcast_to(phis[:, None], E.shape)
    D = np.stack([np.cos(E) * np.sin(Pp), -np.cos(E) * np.cos(Pp), np.sin(E)], -1)
    P, _ = beanie_surface(S, D)
    rib = (0.5 + 0.5 * np.cos(S['beanie_ribs'] * Pp)) ** 0.6
    fade = 1 - ss(0.55, 0.95, s)[None, :]
    row = 0.5 + 0.5 * np.cos(TAU * s * 26)
    disp = S['beanie_rib_depth'] * (rib * (0.75 + 0.25 * row) - 0.5) * fade
    P = P + unit(P) * disp[..., None]
    f, ci, cj = grid_faces(nu, nv, closed_u=True)
    body = Part(P.reshape(-1, 3), f, np.stack([ci / nu * 8, cj / nv * 3], -1))
    # dobladillo acanalado sobre la linea de corte
    Dc = np.stack([np.cos(el_cut) * np.sin(phis), -np.cos(el_cut) * np.cos(phis), np.sin(el_cut)], -1)
    C, _ = beanie_surface(S, Dc)
    C = C + unit(C * np.array([1, 1, 0.3])) * S['cuff_out']
    O = unit(C * np.array([1, 1, 0.25]))
    nr = S['cuff_ribs']
    cuff = sweep(C, O, np.full(nu, S['cuff_h']), np.full(nu, S['cuff_t']), 24, closed=True, expo=3.0,
                 hoff=lambda i, th: S['cuff_rib_depth'] * ((0.5 + 0.5 * np.cos(nr * TAU * i / nu)) ** 0.7 - 0.5)
                 * (np.sin(th) > -0.2))
    cut_line = dict(phis=phis, z=C[:, 2])
    return body, cuff, cut_line


# ---------------------------------------------------------------- torso con punto y trenza

def torso_grid(S):
    nphi, ns = 480, 280
    phis = np.radians(np.linspace(-180, 180, nphi, endpoint=False))
    A, B, n = S['torso_a'], S['torso_b'], 3.0
    sx, cy = np.sin(phis), -np.cos(phis)
    rs = (np.abs(sx / A) ** n + np.abs(cy / B) ** n) ** (-1 / n)
    outer = np.stack([rs * sx, S['torso_y'] + rs * cy], -1)
    neck = np.stack([S['neck_ring_r'] * sx, S['neck_y'] + S['neck_ring_r'] * cy], -1)
    # perfil (rho, z): hombro inclinado, redondeo y caida vertical
    zn, zs, fr, fz, zb = S['torso_zn'], S['torso_zs'], 0.42, 0.55, S['torso_zb']
    rho_c = np.linspace(0, 1 - fr, 60)
    q = rho_c / (1 - fr)
    cap = np.stack([rho_c, zn + (zs - zn) * (0.62 * q + 0.38 * q ** 3)], -1)
    a = np.linspace(np.pi / 2, 0, 30)[1:]
    fil = np.stack([1 - fr + fr * np.cos(a), zs - fz + fz * np.sin(a)], -1)
    wall_z = np.linspace(zs - fz, zb, 60)[1:]
    wall = np.stack([np.ones_like(wall_z), wall_z], -1)
    prof = np.concatenate([cap, fil, wall])
    seg = np.linalg.norm(np.diff(prof * np.array([1.4, 1.0]), axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    sp = np.interp(np.linspace(0, arc[-1], ns), arc, prof[:, 0])
    sz = np.interp(np.linspace(0, arc[-1], ns), arc, prof[:, 1])
    if 'torso_taper' in S:   # seccion que cambia con la altura: (z, a, b, dy) de arriba abajo (V pecho -> cintura)
        tz, ta, tb, tdy = np.array(S['torso_taper'], float).T
        Az, Bz, dy = (np.interp(-sz, -tz, t)[None, :] for t in (ta, tb, tdy))
        rs = (np.abs(sx[:, None] / Az) ** n + np.abs(cy[:, None] / Bz) ** n) ** (-1 / n)
        outer = np.stack([rs * sx[:, None], S['torso_y'] + dy + rs * cy[:, None]], -1)
        xy = neck[:, None, :] + (outer - neck[:, None, :]) * sp[None, :, None]
    else:
        xy = neck[:, None, :] + (outer - neck)[:, None, :] * sp[None, :, None]
    P = np.concatenate([xy, np.broadcast_to(sz[None, :, None], (nphi, ns, 1))], -1)
    return P


def grid_normals(P):
    du = np.gradient(P, axis=0)
    dv = np.gradient(P, axis=1)
    N = unit(np.cross(du, dv))
    return N


def knit_height(u, v, S):
    """Altura del punto: canalé grueso de barras + trenzas de dos cabos (centro y una a cada lado)."""
    col, row = S['knit_col'], S['knit_row']
    colp = (0.5 + 0.5 * np.cos(TAU * u / col)) ** 0.45
    bar = (0.5 + 0.5 * np.cos(TAU * v / row)) ** 0.5
    rib = S['knit_depth'] * colp * (0.62 + 0.38 * bar)
    P = S['cable_period']
    rw = S['cable_rope']
    rope_bar = 0.75 + 0.25 * (0.5 + 0.5 * np.cos(TAU * v / (row * 0.9)))
    h = rib
    for k, cu in enumerate(S.get('cable_u', (0.0,))):
        cw = S['cable_half'] * (1.0 if cu == 0 else 0.85)
        uu = u - cu
        au = np.abs(uu)
        ph = TAU * v / P + (0.0 if cu == 0 else np.pi * 0.5 * k)
        c1 = S['cable_amp'] * (1.0 if cu == 0 else 0.85) * np.sin(ph)
        top1 = ss(-0.25, 0.25, -np.cos(ph))
        h1 = np.sqrt(np.clip(1 - ((uu - c1) / rw) ** 2, 0, 1))
        h2 = np.sqrt(np.clip(1 - ((uu + c1) / rw) ** 2, 0, 1))
        cable = S['cable_depth'] * np.maximum(h1 * (0.78 + 0.22 * top1), h2 * (0.78 + 0.22 * (1 - top1))) * rope_bar
        groove = ss(cw - 0.02, cw + 0.03, au) * (1 - ss(cw + 0.05, cw + 0.09, au))
        inside = 1 - ss(cw - 0.03, cw + 0.0, au)
        h = cable * inside + h * (1 - inside) * (1 - groove * 0.9)
    return h


def build_torso(S):
    P = torso_grid(S)
    nphi, ns = P.shape[:2]
    N = grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    x, z = P[..., 0], P[..., 2]
    front = np.clip(-N[..., 1], 0, 1)
    bust = sum(np.exp(-(((x - sx * 0.46) / 0.34) ** 2 + ((z + 2.55) / 0.36) ** 2)) for sx in (-1, 1))
    P = P + N * (S['bust'] * bust * front)[..., None]
    if 'arm_x' in S:
        crease = np.exp(-((np.abs(x) - S['arm_x']) / 0.07) ** 2) * ss(-2.05, -2.4, z) * front
        P = P - N * (0.05 * crease)[..., None]
    if S.get('torso_folds'):   # el punto cuelga: ondas suaves bajo el pecho y tirones de la axila hacia el pecho
        ax = np.abs(x)
        drape = np.sin(x * 8.0 + 0.9 * np.sin(z * 2.1)) * ss(-2.2, -2.7, z)
        pull = np.sin((ax * 1.2 + z) * 12.0) * np.exp(-((ax - 0.78) / 0.18) ** 2) * ss(-1.75, -2.05, z) \
            * (1 - ss(-2.55, -2.85, z))
        P = P + N * (S['torso_folds'] * (drape + 0.6 * pull))[..., None]
    # coordenadas de punto: u = arco firmado desde el centro delantero, v = arco desde el cuello
    du = np.linalg.norm(np.diff(P, axis=0), axis=-1)
    u = np.concatenate([np.zeros((1, ns)), np.cumsum(du, 0)], 0)
    u = u - u[nphi // 2][None, :]
    dv = np.linalg.norm(np.diff(P, axis=1), axis=-1)
    v = np.concatenate([np.zeros((nphi, 1)), np.cumsum(dv, 1)], 1)
    N = grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    h = knit_height(u, v, S)
    seam = np.exp(-((np.abs(x) - S['arm_x'] + 0.07) / 0.016) ** 2) * ss(-1.85, -2.15, z) * front if 'arm_x' in S else 0.0
    h = h * (1 - 0.7 * seam) + 0.016 * seam * (0.65 + 0.35 * np.cos(TAU * v / 0.032))
    P = P + N * h[..., None]
    # cavidad para el material: surcos (alrededor y entre los cabos de las trenzas) oscuros, cimas claras
    cav = ss(0.0, S['cable_depth'] * 0.8, h).reshape(-1)
    col = np.stack([cav, cav, cav, np.ones_like(cav)], -1)
    f, ci, cj = grid_faces(nphi, ns, closed_u=True)
    ci = ci % nphi
    test = np.cross(P[1, ns // 2] - P[0, ns // 2], P[0, ns // 2 + 1] - P[0, ns // 2])
    flip = np.dot(test, N[0, ns // 2]) < 0
    if flip:
        f, ci, cj = f[:, ::-1], ci[:, ::-1], cj[:, ::-1]
    uv = np.stack([u[ci, cj], v[ci, cj]], -1)
    return Part(P.reshape(-1, 3), f, uv, col)


def build_collar(S):
    """Cuello alto acanalado del jersey (asoma bajo la bufanda)."""
    nu, nv = 240, 30
    th = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    zs = np.linspace(S['collar_z'][0], S['collar_z'][1], nv)
    T, Z = np.meshgrid(th, zs, indexing='ij')
    r = S['collar_r'] + 0.03 * ss(0.75, 1.0, (Z - zs[0]) / (zs[-1] - zs[0])) \
        + S['collar_rib'] * ((0.5 + 0.5 * np.cos(S['collar_ribs'] * T)) ** 0.6 - 0.5)
    P = np.stack([r * np.sin(T), S['neck_y'] - r * np.cos(T), Z], -1)
    f, ci, cj = grid_faces(nu, nv, closed_u=True)
    return Part(P.reshape(-1, 3), f, np.stack([ci / nu, cj / nv], -1))


def build_collar_rim(S, drop=0.09, nu=240, nv=28):
    """Borde vuelto del cuello alto: cierra el hueco entre el canale (collar_r + 0.03 arriba) y el cuello de la
    persona. Seccion: media rosca que sube desde la cara de fuera del collar, pasa por encima y baja pegada al
    cuello `drop` (sin piel ni hueco visible bajo el borde)."""
    top = S['collar_z'][1]
    ro, ri = S['collar_r'] + 0.03, S['neck_r'] + 0.006
    rm, a = (ro + ri) / 2, (ro - ri) / 2
    s = np.linspace(-0.15 * np.pi, np.pi, nv - 6)
    prof = [(rm + a * np.cos(x), top - 0.01 + 0.035 * np.sin(x), 0.5 + 0.5 * np.cos(x)) for x in s]
    prof += [(ri, top - 0.01 - drop * k / 6, 0.0) for k in range(1, 7)]
    R0, Zp, Wr = (np.array(c) for c in zip(*prof))
    th = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    T, J = np.meshgrid(th, np.arange(nv), indexing='ij')
    rib = S['collar_rib'] * ((0.5 + 0.5 * np.cos(S['collar_ribs'] * T)) ** 0.6 - 0.5)
    r = R0[J] + rib * (0.25 + 0.75 * Wr[J])
    P = np.stack([r * np.sin(T), S['neck_y'] - r * np.cos(T), Zp[J]], -1)
    f, ci, cj = grid_faces(nu, nv, closed_u=True)
    part = Part(P.reshape(-1, 3), f, np.stack([ci / nu, cj / nv], -1))
    return orient_out(part, (0.0, S['neck_y'] - rm, top - 0.01))


def build_neck(S):
    nu, nv = 64, 20
    th = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    zs = np.linspace(S['neck_z'][0], S['neck_z'][1], nv)
    T, Z = np.meshgrid(th, zs, indexing='ij')
    r = S['neck_r'] + 0.04 * ss(S['neck_z'][0] + 0.3, S['neck_z'][0], Z)
    P = np.stack([r * np.sin(T), S['neck_y'] - r * np.cos(T), Z], -1)
    f, ci, cj = grid_faces(nu, nv, closed_u=True)
    return Part(P.reshape(-1, 3), f, np.stack([ci / nu, cj / nv], -1))


# ---------------------------------------------------------------- brazo con manga de punto (un solo tubo)

def catmull(K, n=40):
    """Curva Catmull-Rom por los nudos K (n puntos por tramo)."""
    K = np.asarray(K, float)
    G = np.concatenate([2 * K[:1] - K[1:2], K, 2 * K[-1:] - K[-2:-1]])
    t = np.linspace(0, 1, n, endpoint=False)[:, None]
    out = [0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2 + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3)
           for p0, p1, p2, p3 in (G[i:i + 4] for i in range(len(K) - 1))]
    return np.concatenate(out + [K[-1:]])


def arm_sleeve(S, knots, radii, flat, elbow, cuff=None, na=120, ds=0.012):
    """Brazo de jersey como UN tubo: nace bajo el cuello alto, sigue el trapecio, envuelve el deltoides y baja por el
    brazo (codo en el nudo `elbow`) hasta la muneca. radii/flat por nudo (flat aplasta la seccion en vertical: trapecio
    ancho y bajo). Lleva el canale y una trenza por la linea de fuera, pliegues que se juntan en la cara interna del
    codo y, si cuff=(largo, radio), un punio acanalado mas estrecho con borde vuelto.
    -> (Part con cavidad del punto en col y .tube = colisionador Tube, trayectoria (n, 3))."""
    A = S['arm_sleeve']
    K = np.asarray(knots, float)
    Pd = catmull(K, 60)
    seg = np.linalg.norm(np.diff(Pd, axis=0), axis=1)
    arc_d = np.concatenate([[0], np.cumsum(seg)])
    L = arc_d[-1]
    n = max(int(L / ds), 8)
    arc = np.linspace(0, L, n)
    P = np.stack([np.interp(arc, arc_d, Pd[:, k]) for k in range(3)], -1)
    ka = arc_d[np.arange(len(K)) * 60]
    r = np.interp(arc, ka, radii)
    fl = np.interp(arc, ka, flat)
    for _ in range(30):    # radios suaves entre nudos (sin escalones)
        r[1:-1] = 0.5 * r[1:-1] + 0.25 * (r[:-2] + r[2:])
        fl[1:-1] = 0.5 * fl[1:-1] + 0.25 * (fl[:-2] + fl[2:])
    T = unit(np.gradient(P, axis=0))
    H = np.zeros_like(P)
    h = np.array(A.get('up', (0.0, 0.0, 1.0)), float)
    for i in range(n):            # marco de transporte paralelo: H arriba en el hombro y fuera en el brazo
        h = unit(h - T[i] * np.dot(h, T[i]))
        H[i] = h
    W = np.cross(T, H)
    th = np.linspace(-np.pi, np.pi, na, endpoint=False)
    c, sn = np.cos(th)[None, :], np.sin(th)[None, :]
    a_el = ka[elbow]
    # pliegues: anillos que se juntan en la cara interna del codo (hacia donde dobla) y fruncido junto al punio
    kv = np.gradient(T, axis=0)[min(int(a_el / L * (n - 1)), n - 1)]
    th_in = math.atan2(np.dot(kv, W[min(int(a_el / L * (n - 1)), n - 1)]),
                       np.dot(kv, H[min(int(a_el / L * (n - 1)), n - 1)]))
    bend = np.linalg.norm(kv) / ds
    av = arc[:, None]
    inner = 0.5 + 0.5 * np.cos(th[None, :] - th_in)
    wave = np.sin(av * TAU / A['fold_len'] + 1.3 * np.sin(2 * th[None, :] + av * 3.0))
    at_el = np.exp(-((av - a_el) / A['fold_el']) ** 2) * min(1.0, bend / 2.0 + 0.35)
    cl = (cuff[0] if cuff else 0.0)
    at_cf = np.exp(-((av - (L - cl - 0.15)) / 0.2) ** 2)
    drape = np.sin(3 * th[None, :] + av * 2.2) * ss(a_el - 0.9, a_el - 0.3, av) * (1 - ss(a_el, a_el + 0.4, av))
    fold = A['folds'] * (wave * (at_el * (0.35 + 0.65 * inner) + 0.6 * at_cf) + 0.35 * drape)
    if cuff:
        cu = ss(L - cl - 0.03, L - cl + 0.02, av)
        rr = r[:, None] * (1 - cu) + cuff[1] * cu
        fold = fold * (1 - cu) + cu * 0.02 * ((0.5 + 0.5 * np.cos(28 * th[None, :])) ** 0.6 - 0.5)
    else:
        rr = r[:, None]
    hh = rr * fl[:, None]
    Nrm = unit(c[..., None] * H[:, None] / np.maximum(fl, 0.2)[:, None, None] + sn[..., None] * W[:, None])
    V = P[:, None] + c[..., None] * hh[..., None] * H[:, None] + sn[..., None] * rr[..., None] * W[:, None]
    # punto: canale + trenza por la linea de fuera (u = 0 arriba en el hombro y fuera en el brazo)
    u = th[None, :] * np.sqrt(0.5 * (rr ** 2 + hh ** 2))
    knit = knit_height(u, np.broadcast_to(av, u.shape), {**S, 'cable_u': (0.0,), **A.get('knit', {})})
    if cuff:
        knit = knit * (1 - cu)
    disp = knit + fold
    V = V + Nrm * disp[..., None]
    f, ci, cj = grid_faces(n, na, closed_v=True)
    cav = ss(0.0, S['cable_depth'] * 0.8, knit).reshape(-1)
    col = np.stack([cav, cav, cav, np.ones_like(cav)], -1)
    parts = [orient_out(Part(V.reshape(-1, 3), f, np.stack([ci / n, cj / na], -1), col), P[n // 2])]  # caras fuera
    if cuff:   # borde vuelto del punio
        ring = P[-1] + (c.T * hh[-1, 0] * H[-1] + sn.T * rr[-1, 0] * W[-1]) * 1.0
        rim = sweep(ring, np.tile(T[-1], (na, 1)), np.full(na, 0.026), np.full(na, 0.026), 10, closed=True)
        rim.col = np.ones((len(rim.v), 4))
        parts.append(orient_out(rim, ring[0]))   # ring: eje del borde
    out = Part.join(parts)
    out.tube = Tube(P, H, W, rr.max(1), hh.max(1))
    return out, P


# ---------------------------------------------------------------- bufanda

def scarf_fringe(P, O, T, rng):
    """Flecos: hebras retorcidas que cuelgan del borde final de la cola."""
    tang = unit(P[-1] - P[-3])
    side = unit(np.cross(tang, O[-1]))
    out = []
    for k, a in enumerate(np.linspace(-0.92, 0.92, T.get('fringe', 11))):
        L = T.get('fringe_len', 0.16) * rng.uniform(0.8, 1.15)
        tt = np.linspace(0, 1, 9)[:, None]
        start = P[-1] - tang * 0.02 + side * a * T['w'] + O[-1] * rng.uniform(-0.3, 0.3) * T['t']
        sway = side * rng.uniform(-0.25, 0.25) + O[-1] * rng.uniform(-0.05, 0.25)
        Q = start + tang * L * tt + sway * L * tt ** 2
        r = 0.016 * (1 - 0.55 * tt[:, 0]) + 0.004
        out.append(sweep(Q, np.tile(O[-1], (9, 1)), r, r, 8,
                         mod=lambda i, th, ph=rng.uniform(0, TAU): 1 + 0.15 * np.sin(2 * th + i * 1.3 + ph)))
    return out


def _bezier(p0, p1, p2, p3, n):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def _resample(P, ds):
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    s = np.linspace(0, arc[-1], max(int(arc[-1] / ds), 4) + 1)
    return np.stack([np.interp(s, arc, P[:, k]) for k in range(3)], -1), s, arc


def scarf_cloth_start(S, body):
    """Posicion inicial de la bufanda (antes de la simulacion): una banda larga enrollada en espiral alrededor
    del cuello (vuelta interior alta y apretada, exterior mas abierta) con las dos puntas colgando por delante.
    En las vueltas la banda forma un cono alrededor del cuello (tilt) y en las puntas cuelga vertical mirando hacia
    delante. -> (V (n, m, 3), arco a lo largo (n,), posiciones a lo ancho (m,), peso de anclaje (n, m))."""
    C = S['scarf_cloth']
    ay = C['axis_y']
    sw = C['ends_at']
    Th = TAU + 2 * sw
    th = np.linspace(0, Th, 400)
    s = th / Th
    a = -sw + th
    r = C['r0'] + (C['r1'] - C['r0']) * s
    ry = r * (1 + C['front_slack'] * (0.5 + 0.5 * np.cos(a)) ** 2)
    # las vueltas bajan por delante (U) y suben por detras de la nuca
    z = C['z0'] + (C['z1'] - C['z0']) * s - C.get('front_drop', 0.0) * ((0.5 + 0.5 * np.cos(a)) ** 2 - 0.5)
    loop = np.stack([r * np.sin(a), ay - ry * np.cos(a), z], -1)
    t0, t1 = unit(loop[1] - loop[0]), unit(loop[-1] - loop[-2])
    ends = []
    for x, zb, at, tang in ((C['tail_x'][0], C['tail_z'][0], loop[0], -t0), (C['tail_x'][1], C['tail_z'][1], loop[-1], t1)):
        loc, _ = body.front(x, zb)
        b = np.array([x, (loc[1] if loc is not None else -0.8) - C['tail_off'], zb])
        # de la punta (abajo) a la vuelta: sube recta y gira suave hacia la tangente de la vuelta
        ends.append(_bezier(b, b + np.array([0, 0, 0.45]), at + tang * 0.35, at, 60))
    P = np.concatenate([ends[0][:-1], loop, ends[1][::-1][1:]])
    P, arc, _ = _resample(P, C['ds'])
    n = len(P)
    # peso de vuelta (1) frente a punta (0) a lo largo, para la curvatura de la seccion
    L1 = np.linalg.norm(np.diff(ends[0], axis=0), axis=1).sum()
    L2 = arc[-1] - np.linalg.norm(np.diff(ends[1], axis=0), axis=1).sum()
    wl = ss(L1 - 0.35, L1 + 0.15, arc) * ss(L2 + 0.35, L2 - 0.15, arc)
    T = unit(np.gradient(P, axis=0))
    R = unit(P * np.array([1.0, 1.0, 0.0]) - np.array([0.0, ay, 0.0]))
    # normal de la tela: en las vueltas inclinada tilt grados hacia arriba (banda en cono alrededor del cuello,
    # canto interior alto y pegado, exterior bajo y abierto) y hacia fuera en las puntas
    fr = 0.5 - 0.5 * (P[:, 1] - ay) / np.maximum(np.hypot(P[:, 0], P[:, 1] - ay), 1e-9)  # 1 delante, 0 detras
    tl = np.radians(C.get('tilt_back', C.get('tilt', 90.0)) + (C.get('tilt', 90.0) - C.get('tilt_back', C.get('tilt', 90.0))) * fr)[:, None]
    Nl = R * np.cos(tl) + np.array([0.0, 0.0, 1.0]) * np.sin(tl)
    Nt = (1 - wl)[:, None] * R + wl[:, None] * Nl
    Nn = unit(Nt - (Nt * T).sum(-1, keepdims=True) * T)
    B = unit(np.cross(T, Nn))
    m = C['cols']
    sj = np.linspace(-C['width'] / 2, C['width'] / 2, m)
    # los cantos se curvan un poco hacia abajo / hacia el pecho (k): la tela ya empieza a caer
    k = (C['k_tail'] + (C['k_loop'] - C['k_tail']) * wl)[:, None]
    V = P[:, None] + (np.sin(k * sj) / k)[..., None] * B[:, None] + ((np.cos(k * sj) - 1) / k)[..., None] * Nn[:, None]
    # anclaje (pin) de la parte de atras de las vueltas: la tela no resbala cuello abajo con el peso de las puntas
    back = -(P[:, 1] - ay) / np.maximum(np.hypot(P[:, 0], P[:, 1] - ay), 1e-9)
    pin = wl * ss(C.get('pin_from', 0.6), C.get('pin_from', 0.6) + 0.25, -back)
    # solo la mitad alta (canto pegado al cuello): el canto bajo cae libre sobre el jersey
    zr = V[..., 2] - V[..., 2].mean(1, keepdims=True)
    hi = ss(-0.05, 0.6, zr / np.maximum(np.abs(zr).max(1, keepdims=True), 1e-9))
    return V, arc, sj, pin[:, None] * hi


def simulate_cloth(V, colliders, C, frames, trace=None, pin=None):
    """Simula con el modificador Cloth de Blender la rejilla V (n, m, 3) cayendo por gravedad sobre colliders
    (lista de Part, con modificador Collision) y con auto-colision; devuelve la rejilla asentada (se aplica el
    resultado del ultimo fotograma y se borran los objetos temporales)."""
    n, m = V.shape[:2]
    f, ci, cj = grid_faces(n, m)
    band = make_object('_scarf_cloth', Part(V.reshape(-1, 3), f), smooth=False)
    temps = [band]
    for k, part in enumerate(colliders):
        ob = make_object(f'_scarf_coll{k}', part, smooth=False)
        ob.modifiers.new('collision', 'COLLISION')
        ob.collision.thickness_outer = C['coll_thick']
        ob.collision.cloth_friction = C['friction']
        ob.collision.damping = 0.5
        ob.collision.use_culling = False  # dos caras: no depende de hacia donde miren las normales de cada pieza
        temps.append(ob)
    cm = band.modifiers.new('cloth', 'CLOTH')
    cs = cm.settings
    if pin is not None and pin.max() > 0:
        vg = band.vertex_groups.new(name='pin')
        flat = pin.reshape(-1)
        for w in np.unique(np.round(flat[flat > 0], 3)):
            vg.add([int(i) for i in np.nonzero(np.isclose(np.round(flat, 3), w))[0]], float(w), 'REPLACE')
        cs.vertex_group_mass = 'pin'
        cs.pin_stiffness = C.get('pin_stiffness', 1.0)
    cs.quality = C['quality']
    cs.mass = C['mass']
    cs.air_damping = C['air_damping']
    cs.bending_model = 'ANGULAR'
    cs.tension_stiffness = cs.compression_stiffness = C['stretch']
    cs.shear_stiffness = C['shear']
    cs.bending_stiffness = C['bending']
    cs.tension_damping = cs.compression_damping = cs.shear_damping = 5.0
    cs.bending_damping = 0.5
    cc = cm.collision_settings
    cc.use_collision = True
    cc.distance_min = C['coll_dist']
    cc.collision_quality = 4
    cc.use_self_collision = True
    cc.self_distance_min = C['self_dist']
    cc.self_friction = C['friction']
    cm.point_cache.frame_start = 1
    cm.point_cache.frame_end = frames
    sc = bpy.context.scene
    sc.frame_start, sc.frame_end = 1, frames
    for fr in range(1, frames + 1):
        sc.frame_set(fr)
        if trace is not None and fr % 10 == 0:
            ev = band.evaluated_get(bpy.context.evaluated_depsgraph_get())
            me = ev.to_mesh()
            co = np.empty(len(me.vertices) * 3, np.float32)
            me.vertices.foreach_get('co', co)
            ev.to_mesh_clear()
            trace.append(co.reshape(n, m, 3).copy())
    dg = bpy.context.evaluated_depsgraph_get()
    ev = band.evaluated_get(dg)
    me = ev.to_mesh()
    out = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('co', out)
    ev.to_mesh_clear()
    sc.frame_set(1)
    for ob in temps:
        me = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(me)
    return out.reshape(n, m, 3).astype(float)


def thicken_band(V, arc, sj, t):
    """Tela simulada (rejilla n x m, superficie media) -> tubo plano cerrado de grosor t con cantos redondeados
    (seccion: cara exterior de ida y cara interior de vuelta). UV en unidades reales: u a lo largo, v a lo ancho."""
    n, m = V.shape[:2]
    Ga, Gb = np.gradient(V, axis=0), np.gradient(V, axis=1)
    Nv = unit(np.cross(Ga, Gb))
    u = np.linspace(-1, 1, m)
    h = t / 2 * (0.35 + 0.65 * np.sqrt(np.clip(1 - u ** 2, 0, 1)))
    top = V + Nv * h[None, :, None]
    bot = (V - Nv * h[None, :, None])[:, ::-1]
    W = np.concatenate([top, bot], 1)
    f, ci, cj = grid_faces(n, 2 * m, closed_v=True)
    vpos = sj - sj[0]
    vv = np.concatenate([vpos, vpos[::-1], vpos[:1]])
    # arco real a lo largo de la fila central (tras la simulacion)
    mid = V[:, m // 2]
    ua = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(mid, axis=0), axis=1))])
    uv = np.stack([ua[ci], vv[cj]], -1)
    part = Part(W.reshape(-1, 3), f, uv)
    return orient_out(part, V[n // 2, m // 2]), Nv


def separate_layers(V, top, under, gap, axis_y, iters=10, smooth=2):
    """La auto-colision de la simulacion trabaja con la superficie media (sin grosor): separa las filas `top`
    (vuelta de encima) de la superficie de las filas `under` al menos `gap` por el lado de fuera (lejos del eje
    del cuello y hacia arriba), con el desplazamiento suavizado para no dejar bultos. Solo actua donde las dos
    capas se tocan de verdad (a menos de 2.5 gap): no cruza capas que estan lejos."""
    V = V.copy()
    n, m = V.shape[:2]
    U = V[under[0]:under[1]]
    f, _, _ = grid_faces(len(U), m)
    tree = BVHTree.FromPolygons(U.reshape(-1, 3).tolist(), f.tolist())
    Nu = unit(np.cross(np.gradient(U, axis=0), np.gradient(U, axis=1))).reshape(-1, 3)
    out = unit(U.reshape(-1, 3) * np.array([1.0, 1.0, 0.0]) - np.array([0.0, axis_y, 0.0]) + np.array([0.0, 0.0, 0.7]))
    Nu *= np.sign((Nu * out).sum(-1, keepdims=True))
    for _ in range(iters):
        D = np.zeros((top[1] - top[0], m, 3))
        for i in range(top[0], top[1]):
            for j in range(m):
                hit = tree.find_nearest(V[i, j].tolist(), gap * 2.5)
                if hit[0] is None:
                    continue
                k = f[hit[2]][0]
                nrm = Nu[k]
                d = float(np.dot(V[i, j] - np.array(hit[0]), nrm))
                if d < gap:
                    D[i - top[0], j] = (gap - d) * nrm
        for _ in range(smooth):
            E = np.pad(D, ((1, 1), (1, 1), (0, 0)), mode='edge')
            D = (D * 4 + E[:-2, 1:-1] + E[2:, 1:-1] + E[1:-1, :-2] + E[1:-1, 2:]) / 8
        V[top[0]:top[1]] += D
    return V


def coarse_grid(part, shape, step):
    """Version ligera de una malla en rejilla (para colisionar en la simulacion): una de cada step filas/columnas."""
    G = part.v.reshape(shape + (3,))[::step[0], ::step[1]]
    f, _, _ = grid_faces(G.shape[0], G.shape[1], closed_u=True)
    return Part(G.reshape(-1, 3), f)


def refine_grid(V, arc, sj):
    """Dobla la resolucion de una rejilla (n, m, 3) con interpolacion cubica (-1, 9, 9, -1)/16 en ambos ejes."""
    def half(X, axis):
        X = np.moveaxis(X, axis, 0)
        E = np.concatenate([2 * X[:1] - X[1:2], X, 2 * X[-1:] - X[-2:-1]], 0)
        mid = (-E[:-3] + 9 * E[1:-2] + 9 * E[2:-1] - E[3:]) / 16
        out = np.empty((2 * len(X) - 1,) + X.shape[1:])
        out[0::2], out[1::2] = X, mid
        return np.moveaxis(out, 0, axis)
    lin = lambda a: np.concatenate([np.stack([a[:-1], 0.5 * (a[:-1] + a[1:])], 1).ravel(), a[-1:]])
    return half(half(V, 0), 1), lin(arc), lin(sj)


def build_scarf_cloth(S, colliders, body):
    """Bufanda por simulacion de tela: una banda de cuadros enrollada dos vueltas al cuello que cae por gravedad
    y colision (cabeza, jersey, cuello) hasta asentarse con pliegues reales; las puntas cuelgan con flecos.
    -> (bufanda, flecos[lista de hebras]); bufanda.checks = {nombre: Part} (tramos sin contacto directo entre
    si, para el chequeo de auto-interpenetracion)."""
    C = S['scarf_cloth']
    V0, arc, sj, pin = scarf_cloth_start(S, body)
    V = simulate_cloth(V0, colliders, C, C['frames'], pin=pin)
    n = len(V)
    for a, b in C.get('separate', ()):
        V = separate_layers(V, tuple(int(r * n) for r in a), tuple(int(r * n) for r in b), C['thick'] * 1.25, C['axis_y'])
    for _ in range(C.get('refine', 1)):
        V, arc, sj = refine_grid(V, arc, sj)
    scarf, Nv = thicken_band(V, arc, sj, C['thick'])
    n, m = V.shape[:2]
    rng = np.random.default_rng(5)
    fringe = []
    k = 6
    for rows in (np.arange(k)[::-1], np.arange(n - k, n)):
        T = dict(w=C['width'] / 2 * 0.92, t=C['thick'], fringe=C['fringe'], fringe_len=C['fringe_len'])
        fringe += scarf_fringe(V[rows, m // 2], Nv[rows, m // 2], T, rng)
    W = scarf.v.reshape(n, 2 * m, 3)
    fg = grid_faces
    checks = {}
    for name, (r0, r1) in C['check_spans'].items():
        i0, i1 = int(r0 * n), int(r1 * n)
        f, _, _ = fg(i1 - i0, 2 * m, closed_v=True)
        checks[name] = Part(W[i0:i1].reshape(-1, 3), f)
    scarf.checks = checks
    return scarf, fringe


# ---------------------------------------------------------------- indicadores de estado

def wool_fuzz(part, count, rng, center, length=(0.01, 0.03), radius=0.0011, outward=None):
    """Pelusa de lana: fibras cortas y rizadas (tubos triangulares de 4 puntos) repartidas por area sobre la
    malla y salidas hacia fuera; en la silueta dan el halo difuso del punto. Todo vectorizado.
    center(points) -> puntos interiores para orientar la normal hacia fuera."""
    v, f = part.v, part.f
    a, b, c = v[f[:, 0]], v[f[:, 1]], v[f[:, 2]]
    d = v[f[:, 3]] if f.shape[1] > 3 else c
    nrm = np.cross(c - a, d - b)
    area = np.linalg.norm(nrm, axis=1)
    fi = rng.choice(len(f), count, p=area / area.sum())
    uu, vv = rng.random((2, count, 1))
    base = (a[fi] * (1 - uu) + b[fi] * uu) * (1 - vv) + (d[fi] * (1 - uu) + c[fi] * uu) * vv
    n = unit(nrm[fi])
    n *= np.sign(np.einsum('ij,ij->i', n, base - center(base)))[:, None]
    if outward is not None:
        keep = outward(base, n)
        base, n = base[keep], n[keep]
    m = len(base)
    t1 = unit(np.cross(n, rng.normal(size=(m, 3))))
    t2 = np.cross(n, t1)
    L = rng.uniform(*length, (m, 1))
    k = np.linspace(0, 1, 4)[None, :, None]
    lean = rng.uniform(0.5, 1.4, (m, 1))
    bend = rng.normal(size=(m, 3)) * 0.35
    P = (base[:, None] - n[:, None] * 0.002 + (n * 0.75 + t1 * lean)[:, None] * L[:, None] * k
         + bend[:, None] * L[:, None] * k ** 2)
    th = np.array([0.0, TAU / 3, 2 * TAU / 3])
    r = radius * (1 - 0.6 * k)                                   # (1, 4, 1)
    off = (np.cos(th)[None, None, :, None] * t1[:, None, None] + np.sin(th)[None, None, :, None] * t2[:, None, None])
    V = P[:, :, None] + r[..., None] * off                      # (m, 4, 3, 3)
    tf, _, _ = grid_faces(4, 3, closed_v=True)
    F = (tf[None] + (np.arange(m) * 12)[:, None, None]).reshape(-1, 4)
    return Part(V.reshape(-1, 3), F)


def build_indicators(S, mats, parent):
    objs = {}
    x0, y0, z0 = S['indicator_at']
    # pensando: nube de burbujas + tres puntos
    cloud = []
    for dx, dz, r in ((0, 0, 0.26), (0.22, 0.05, 0.2), (-0.22, 0.04, 0.2), (0.1, 0.2, 0.2), (-0.1, -0.12, 0.17),
                      (0.14, -0.12, 0.17), (-0.2, -0.36, 0.08), (-0.26, -0.52, 0.05)):
        sp = sphere_part(r, 32, 16)
        sp.v = sp.v * np.array([1, 0.55, 1]) + np.array([x0 + dx, y0, z0 + dz])
        cloud.append(sp)
    # la estela (dos burbujitas) va aparte para poder ocultarla en el encuadre de icono
    bub = make_object('ind_thinking', Part.join(cloud[:-2]), mats['bubble'], parent)
    trail = make_object('ind_thinking_trail', Part.join(cloud[-2:]), mats['bubble'], bub)
    dots = []
    for k in (-1, 0, 1):
        sp = sphere_part(0.055, 20, 10)
        sp.v = sp.v + np.array([x0 + k * 0.15, y0 - 0.16, z0 + 0.03])
        dots.append(sp)
    dots_ob = make_object('ind_thinking_dots', Part.join(dots), mats['accent'], bub)
    objs['thinking'] = [bub, dots_ob, trail]
    # trabajando: spinner de carga, ocho bolas que crecen en sentido horario
    dots8 = []
    for k in range(8):
        a = math.pi / 2 - k * TAU / 8
        sp = sphere_part(0.035 + 0.075 * k / 7, 24, 12)
        sp.v = sp.v + np.array([x0 + 0.27 * math.cos(a), y0, z0 + 0.27 * math.sin(a)])
        dots8.append(sp)
    spin = make_object('ind_working', Part.join(dots8), mats['accent'], parent)
    objs['working'] = [spin]
    # error: insignia roja con "!" + gota de sudor
    disc = sphere_part(0.3, 48, 24)
    disc.v = disc.v * np.array([1, 0.35, 1]) + np.array([x0, y0, z0])
    badge = make_object('ind_error', disc, mats['error'], parent)
    bar = sweep(np.array([[x0, y0 - 0.1, z0 + 0.16], [x0, y0 - 0.1, z0 - 0.04]]), np.tile([0, -1, 0], (2, 1)),
                np.array([0.05, 0.035]), np.array([0.03, 0.025]), 16)
    dot = sphere_part(0.045, 20, 10)
    dot.v = dot.v * np.array([1, 0.6, 1]) + np.array([x0, y0 - 0.1, z0 - 0.14])
    mark = make_object('ind_error_mark', Part.join([bar, dot]), mats['white'], badge)
    dx, dy, dz = S['sweat_at']
    drop = sphere_part(1.0, 32, 20)
    v = drop.v
    zz = v[:, 2]
    pinch = np.where(zz > 0, 1 - 0.85 * np.clip(zz, 0, 1) ** 1.5, 1.0)
    drop.v = np.stack([v[:, 0] * pinch * 0.09, v[:, 1] * pinch * 0.06, zz * 0.13 + 0.05 * (zz > 0) * zz], -1) + np.array([dx, dy, dz])
    sweat = make_object('ind_error_sweat', drop, mats['sweat'], parent)
    objs['error'] = [badge, mark, sweat]
    # feliz: destellos de cuatro puntas
    sparks = []
    for (sx, sz, sc) in S['sparkles']:
        ang = np.linspace(0, TAU, 9)[:-1]
        star = []
        for k, aa in enumerate(ang):
            r = sc if k % 2 == 0 else sc * 0.28
            star.append([math.cos(aa) * r, math.sin(aa) * r])
        star = np.array(star)
        # estrella extruida con bisel: anillo + tapa central
        ring = np.concatenate([np.stack([star[:, 0], np.full(8, 0.0), star[:, 1]], -1)])
        nseg = 40
        tt = np.linspace(0, 8, nseg, endpoint=False)
        k0 = np.floor(tt).astype(int) % 8
        fr = (tt - np.floor(tt))[:, None]
        pts = ring[k0] * (1 - fr) + ring[(k0 + 1) % 8] * fr
        sp = sweep(pts + np.array([sx, y0, sz]), np.tile([0, -1, 0], (nseg, 1)), np.full(nseg, 0.02),
                   np.full(nseg, 0.03), 10, closed=True)
        fill = sphere_part(1.0, 32, 16)
        fv = fill.v
        ang_f = np.arctan2(fv[:, 2], fv[:, 0])
        rad = np.interp(ang_f % TAU, np.append(ang, TAU), np.append(np.where(np.arange(8) % 2 == 0, sc, sc * 0.28), sc))
        fill.v = np.stack([fv[:, 0] * rad, fv[:, 1] * 0.035, fv[:, 2] * rad], -1) + np.array([sx, y0, sz])
        sparks += [sp, fill]
    sparkle = make_object('ind_happy', Part.join(sparks), mats['spark'], parent)
    objs['happy'] = [sparkle]
    # hecho: insignia verde con un check blanco
    disc = sphere_part(0.3, 48, 24)
    disc.v = disc.v * np.array([1, 0.35, 1]) + np.array([x0, y0, z0])
    badge = make_object('ind_done', disc, mats['done'], parent)
    corner = np.array([[-0.14, 0.01], [-0.045, -0.09], [0.15, 0.12]])
    pts = np.concatenate([np.linspace(corner[0], corner[1], 8, endpoint=False), np.linspace(corner[1], corner[2], 12)])
    pts = smooth_path(pts, 1)
    path = np.stack([x0 + pts[:, 0], np.full(len(pts), y0 - 0.1), z0 + pts[:, 1]], -1)
    tick = sweep(path, np.tile([0, -1, 0], (len(path), 1)), np.full(len(path), 0.042), np.full(len(path), 0.03), 16)
    mark = make_object('ind_done_mark', tick, mats['white'], badge)
    objs['done'] = [badge, mark]
    return objs
