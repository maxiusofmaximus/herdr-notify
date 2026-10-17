"""Hugo (researcher) en Blender/Cycles: chaqueta, gafas, pelo canoso retraido.

Uso (desde la raiz del repo):
  blender -b --factory-startup -P tooling/avatars3d/blender/hugo.py -- [--out DIR] [--expr a,b] [--quick]
       [--review] [--samples N] [--closeup] [--view yaw:cx:cz:alto[;...]]
Escribe <out>/hugo-<expr>.png (512), -128, -64, -48, -32 y, con --review, vistas giradas en review/.
--closeup (desarrollo) solo renderiza primeros planos de la cara: <out>/face-<expr>.png.
--view (desarrollo) solo renderiza encuadres libres: <out>/view-<expr>-<i>.png.
"""
import math
import os
import sys
import time

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import character as C  # noqa: E402
import hands as H  # noqa: E402

L = C.lin

S = dict(
    # cabeza cuadrada de hombre mayor
    head_w=1.0, head_front=0.9, head_back=0.96, head_top=1.0, head_bot=0.93, jaw_taper=0.12,
    head_bumps=[
        ((0.72, -0.58, -0.42), 0.05, 0.26, True),     # esquina de la mandibula (cara cuadrada)
        ((0.5, -0.8, -0.18), 0.028, 0.2, True),      # pomo de la mejilla
        ((0.34, -0.92, -0.05), -0.04, 0.2, True),    # cuencas hundidas
        ((0.3, -0.93, -0.24), 0.02, 0.11, True),     # ojeras
        ((0.0, -1.0, -0.25), 0.03, 0.2, False),      # puente fino (bajo, donde apoyan las gafas)
        ((0.0, -1.0, -0.36), 0.024, 0.15, False),    # nariz pequena y fina (no cruza la montura)
        ((0.0, -1.0, -0.45), 0.018, 0.05, False),    # punta
        ((0.07, -1.0, -0.46), 0.012, 0.035, True),   # aletas
        ((0.04, -1.0, -0.49), -0.01, 0.018, True),   # orificios
        ((0.0, -1.0, -0.52), -0.008, 0.04, False),   # surco bajo la nariz
        ((0.3, -0.92, -0.55), -0.022, 0.13, True),   # nasolabial
        ((0.0, -0.86, -0.88), 0.04, 0.2, False),     # barbilla ancha
        ((0.28, -0.95, 0.12), 0.032, 0.22, True),   # arco supraorbitario
    ],
    skin=L('#f5d3b5'), blush=L('#e89884'), nose_tip=L('#e8907e'),
    # ojos entornados
    eye_x=0.35, eye_z=-0.11, eye_r=0.225, eye_depth=0.82, eye_yaw=8.0, eye_tilt=-3.0,
    iris_ang=0.72, pupil=0.4,
    sclera=L('#f7f2ec'), sclera_edge=L('#dccfc4'), iris_in=L('#8aa0b6'), iris_mid=L('#4a6a86'),
    iris_out=L('#2a3c50'), iris_ring=L('#141c28'), iris_glow=L('#b0c8e0'),
    catchlights=[(-0.36, 0.42, 0.05), (0.3, -0.22, 0.024)],
    lash_w=0.008, lash_flicks=[(50, 0.035, 0.12), (66, 0.04, 0.16)],
    lash=L('#2a2018'), lid_thick=0.02, crease_gap=12, crease_w=0.014, lid_fillet=0.09,
    # cejas gruesas canosas y boca de hombre mayor (labios mas finos)
    brow_pts=[(0.08, 0.26), (0.32, 0.3), (0.6, 0.26)], brow_w=0.1, brow=L('#5e5750'),
    brow_light=L('#8a8178'), brow_dark=L('#3a342e'), brow_hair=0.0036, brow_hair_len=0.016,
    lip_up_h=0.022, lip_lo_h=0.032, lip_up_lift=0.016, lip_lo_lift=0.022,
    mouth_center=(0.0, -0.55), lip=L('#b07a70'), lipline=L('#6e3a34'), cavity=L('#4a1818'),
    teeth=L('#f7f2e8'), tongue=L('#d06068'),
    # cuerpo: camisa + corbata azul del agente + chaqueta
    neck_y=0.12, neck_r=0.44, neck_z=(-1.6, -0.55),
    collar_r=0.5, collar_z=(-1.6, -1.0), collar_rib=0.0, collar_ribs=0,
    knit_col=0.09, knit_row=0.05, knit_depth=0.012, cable_u=(), cable_half=0.0, cable_amp=0.0,
    cable_rope=0.1, cable_period=0.5, cable_depth=0.0,
    shirt=L('#e8e4dc'), jacket=L('#334155'), tie=L('#1e5db3'), tie_dark=L('#163f8f'),
    metal=L('#c8ccd4'), frame=L('#2a2e34'),
    # indicadores (coordenadas locales del ancla; escala grande para que se lea a 48 px)
    indicator_root=(1.1, -1.2, 0.74), indicator_scale=1.15,
    icon_indicator=((0.6, -1.05, 0.8), 0.85), indicator_at=(0.0, 0.0, 0.0),
    sparkles=[(0.0, 0.0, 0.3), (-0.36, 0.26, 0.15), (0.3, -0.36, 0.14)],
    sweat_at=(-0.86, -0.62, 0.12),
    # manos (solo en `done`): pulgar arriba
    hand_scale=1.45, done_pose='thumbs',
)

# pelo canoso corto peinado hacia atras: sistema de pelo de Blender (Hair Curves). Guias peinadas en numpy sobre el
# cuero cabelludo, hijos por Interpolate Curves y despues clump, kink (curl) y ruido (frizz) con los nodos Essentials
# de pelo; shader Principled Hair BSDF (Chiang) con raiz oscura y puntas claras y calidas.
ESSENTIALS = os.path.join(os.path.dirname(bpy.app.binary_path), f'{bpy.app.version[0]}.{bpy.app.version[1]}',
                          'datafiles', 'assets', 'nodes', 'procedural_hair_node_assets.blend')
HAIR = dict(
    guides=3000, child_density=9000.0, seed=5, pts=14,
    # linea de nacimiento (z sobre la cabeza segun el angulo desde la frente): entradas en M a ~38 grados,
    # patillas delante de la oreja (~76-90) y nuca baja
    hairline=[(0, 0.5), (18, 0.58), (38, 0.74), (52, 0.56), (64, 0.3), (72, -0.05), (78, -0.34), (92, -0.34),
              (102, -0.12), (120, -0.3), (145, -0.5), (165, -0.64), (180, -0.72)],
    len_top=0.4, len_side=0.2, len_nape=0.05, vol_top=0.03, vol_side=0.075, vol_nape=0.006,
    root_r=0.0034, tip_r=0.0009,
    clump=dict(factor=0.65, shape=0.35, spread=0.006, dist=0.055),
    curl=dict(factor=0.35, radius=0.005, freq=3.0, start=0.3),
    frizz=dict(factor=0.2, dist=0.008),
    scalp=L('#4a4644'),
)


def hairline_z(deg):
    hl = HAIR['hairline']
    return np.interp(deg, [p[0] for p in hl], [p[1] for p in hl])


def dir_of(phi, el):
    return np.stack([np.cos(el) * np.sin(phi), -np.cos(el) * np.cos(phi), np.sin(el)], -1)


def build_scalp(S):
    """Cuero cabelludo bajo el pelo: superficie de nacimiento de los hijos (atributo hairdens = densidad, que se
    desvanece en la linea de pelo) y capa de color de pelo oscuro para que no asome piel entre las hebras."""
    nphi, nel = 180, 36
    phis = np.linspace(-np.pi, np.pi, nphi, endpoint=False)
    rows = []
    for phi in phis:
        target = hairline_z(abs(math.degrees(phi)))
        lo, hi = -1.0, 1.5
        for _ in range(30):
            mid = 0.5 * (lo + hi)
            if C.head_points(dir_of(phi, mid)[None], S)[0][2] > target:
                hi = mid
            else:
                lo = mid
        els = 0.5 * (lo + hi) + (1.5695 - 0.5 * (lo + hi)) * np.linspace(0, 1, nel) ** 1.4
        D = dir_of(np.full(nel, phi), els)
        rows.append(C.head_points(D, S) + D * 0.004)
    G = np.stack(rows, 0)
    f, _, _ = C.grid_faces(nphi, nel, closed_u=True)
    part = C.Part(G.reshape(-1, 3), f)
    part = C.orient_out(part, (0.0, 0.0, 0.0))
    u = np.tile(np.linspace(0.0, 1.0, nel), nphi)
    # densidad que se desvanece en la linea de pelo; en la nuca y bajo las sienes un fade mas largo
    zv = G.reshape(-1, 3)[:, 2]
    dens = C.ss(0.0, 0.1 + 0.18 * C.ss(0.1, -0.45, zv), u)
    # color: piel en el borde -> gris de pelo; alfa = densidad de hijos
    skin = np.array(S['skin'][:3])
    col = skin[None] + (np.array(HAIR['scalp'][:3]) - skin)[None] * C.ss(0.0, 0.08, u)[:, None]
    part.col = np.concatenate([col, dens[:, None]], 1)
    return part


def grow_guides(S, rng):
    """Guias peinadas hacia atras que se apoyan sobre el craneo y ganan altura (volumen) a lo largo; en la nuca y
    las patillas caen hacia abajo. Devuelve (N, pts, 3) y la normal de la raiz."""
    H_ = HAIR
    cand = rng.normal(size=(H_['guides'] * 6, 3))
    cand /= np.linalg.norm(cand, axis=1, keepdims=True)
    P0 = C.head_points(cand, S)
    deg = np.degrees(np.abs(np.arctan2(cand[:, 0], -cand[:, 1])))
    keep = P0[:, 2] > hairline_z(deg) + 0.01
    D = cand[keep][:H_['guides']]
    n = len(D)
    x, y, z = D.T
    side = C.ss(0.45, 0.85, np.abs(x)) * C.ss(-0.35, 0.2, z)
    nape = C.ss(-0.1, -0.45, z)
    L_ = (H_['len_top'] + (H_['len_side'] - H_['len_top']) * C.ss(0.4, -0.1, z)
          + (H_['len_nape'] - H_['len_side']) * nape) * rng.uniform(0.85, 1.15, n)
    back = C.ss(0.25, 0.8, y)
    L_ *= 1.0 - 0.5 * back * C.ss(0.6, -0.1, z)
    vol = (H_['vol_top'] + (H_['vol_side'] - H_['vol_top']) * side * C.ss(-0.3, 0.15, z)
           + (H_['vol_nape'] - H_['vol_top']) * nape) \
        * (1.0 - 0.6 * back * C.ss(0.5, -0.2, z)) * rng.uniform(0.7, 1.3, n)
    # las puntas bajas se vuelven a pegar a la nuca (sin alero de cuenco)
    settle = C.ss(0.4, -0.2, z)
    # onda lateral suave por guia (fase y amplitud propias) para que no salgan rectas
    wph, wamp = rng.uniform(0, C.TAU, n), rng.uniform(0.0, 0.25, n)
    k = H_['pts']
    out = np.zeros((n, k, 3))
    Dk = D.copy()
    for i in range(k):
        t = i / (k - 1)
        h = 0.004 + vol * C.ss(0.0, 0.45, t) * (1.0 - 0.95 * settle * C.ss(0.4, 1.0, t))
        out[:, i] = C.head_points(Dk, S) + Dk * h[:, None]
        x, y, z = Dk.T
        # por detras del craneo el peinado gira hacia abajo (sin remolino en el polo trasero)
        down = np.maximum(C.ss(0.1, -0.3, z), C.ss(0.15, 0.75, y))
        g =np.stack([np.zeros(n), 1.0 - down, -(down + 0.35 * C.ss(0.45, 0.85, np.abs(x)) * (1 - down))], -1)
        g -= Dk * np.sum(g * Dk, 1, keepdims=True)
        g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-6)
        lat = np.cross(Dk, g)
        g = g + lat * (wamp * np.sin(wph + 6.0 * t))[:, None]
        g /= np.linalg.norm(g, axis=1, keepdims=True)
        r = np.linalg.norm(C.head_points(Dk, S), axis=1)
        Dk = Dk + g * (L_ / (k - 1) / r)[:, None]
        Dk /= np.linalg.norm(Dk, axis=1, keepdims=True)
    return out, D


def load_hair_nodes():
    names = ('Clump Hair Curves', 'Curl Hair Curves', 'Frizz Hair Curves')
    with bpy.data.libraries.load(ESSENTIALS, link=False) as (src, dst):
        dst.node_groups = [g for g in src.node_groups if g in names]
    return {g.name: g for g in dst.node_groups}


def hair_node_tree(scalp_ob, mat):
    """Hijos interpolados entre guias sobre el cuero cabelludo + clump, kink, ruido, grosor raiz->punta."""
    ess = load_hair_nodes()
    ng = bpy.data.node_groups.new('hugo_hair', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N, Lk = ng.nodes, ng.links

    def node(kind, **kw):
        nd = N.new(kind)
        for k_, v in kw.items():
            setattr(nd, k_, v)
        return nd

    gi, go = node('NodeGroupInput'), node('NodeGroupOutput')
    oi = node('GeometryNodeObjectInfo', transform_space='RELATIVE')
    oi.inputs['Object'].default_value = scalp_ob
    dens = node('GeometryNodeInputNamedAttribute', data_type='FLOAT_COLOR')
    dens.inputs['Name'].default_value = 'scalpcol'
    sep = node('FunctionNodeSeparateColor')
    Lk.new(dens.outputs['Attribute'], sep.inputs['Color'])
    dist = node('GeometryNodeDistributePointsOnFaces', distribute_method='POISSON')
    Lk.new(oi.outputs['Geometry'], dist.inputs['Mesh'])
    dist.inputs['Density Max'].default_value = HAIR['child_density']
    dist.inputs['Seed'].default_value = HAIR['seed']
    Lk.new(sep.outputs['Alpha'], dist.inputs['Density Factor'])
    up = node('GeometryNodeInputNamedAttribute', data_type='FLOAT_VECTOR')
    up.inputs['Name'].default_value = 'up'
    ic = node('GeometryNodeInterpolateCurves')
    Lk.new(gi.outputs[0], ic.inputs['Guide Curves'])
    Lk.new(up.outputs['Attribute'], ic.inputs['Guide Up'])
    Lk.new(dist.outputs['Points'], ic.inputs['Points'])
    Lk.new(dist.outputs['Normal'], ic.inputs['Point Up'])
    ic.inputs['Max Neighbors'].default_value = 4
    join = node('GeometryNodeJoinGeometry')
    Lk.new(ic.outputs['Curves'], join.inputs[0])
    Lk.new(gi.outputs[0], join.inputs[0])
    cur = join.outputs[0]

    def group(name, **vals):
        nonlocal cur
        g = node('GeometryNodeGroup')
        g.node_tree = ess[name]
        for k_, v in vals.items():
            g.inputs[k_].default_value = v
        Lk.new(cur, g.inputs['Geometry'])
        cur = g.outputs['Geometry']

    cl, cu, fr = HAIR['clump'], HAIR['curl'], HAIR['frizz']
    group('Clump Hair Curves', **{'Factor': cl['factor'], 'Shape': cl['shape'], 'Tip Spread': cl['spread'],
                                  'Existing Guide Map': False, 'Guide Distance': cl['dist'], 'Preserve Length': True,
                                  'Seed': 3})
    group('Curl Hair Curves', **{'Factor': cu['factor'], 'Radius': cu['radius'], 'Frequency': cu['freq'],
                                 'Curl Start': cu['start'], 'Existing Guide Map': False,
                                 'Guide Distance': cl['dist'], 'Seed': 4})
    group('Frizz Hair Curves', **{'Factor': fr['factor'], 'Distance': fr['dist'], 'Seed': 6})
    sp = node('GeometryNodeSplineParameter')
    mr = node('ShaderNodeMapRange')
    Lk.new(sp.outputs['Factor'], mr.inputs['Value'])
    mr.inputs['To Min'].default_value = HAIR['root_r']
    mr.inputs['To Max'].default_value = HAIR['tip_r']
    rad = node('GeometryNodeSetCurveRadius')
    Lk.new(cur, rad.inputs['Curve'])
    Lk.new(mr.outputs['Result'], rad.inputs['Radius'])
    sm = node('GeometryNodeSetMaterial')
    sm.inputs['Material'].default_value = mat
    Lk.new(rad.outputs['Curve'], sm.inputs['Geometry'])
    Lk.new(sm.outputs['Geometry'], go.inputs[0])
    return ng


def mat_hair_curves(S):
    """Principled Hair BSDF (Chiang, melanina): raiz mas oscura, puntas claras con tinte calido; ~1/5 de hebras
    mas oscuras para el gris sal y pimienta; brillo suave (rugosidad media, sin coat)."""
    m = bpy.data.materials.new('hair_curves')
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    N, Lk = nt.nodes, nt.links
    info = N.new('ShaderNodeHairInfo')
    bsdf = N.new('ShaderNodeBsdfHairPrincipled')
    bsdf.model = 'CHIANG'
    bsdf.parametrization = 'COLOR'
    # gris: color directo (la melanina baja amarillea). Raiz gris oscuro -> gris claro -> punta clara calida
    ramp = N.new('ShaderNodeValToRGB')
    Lk.new(info.outputs['Intercept'], ramp.inputs['Fac'])
    els = ramp.color_ramp.elements
    els[0].position, els[0].color = 0.0, (0.06, 0.058, 0.057, 1.0)
    els[1].position, els[1].color = 1.0, (0.5, 0.46, 0.4, 1.0)
    els.new(0.25).color = (0.2, 0.2, 0.205, 1.0)
    els.new(0.65).color = (0.36, 0.355, 0.35, 1.0)
    # ~1/4 de hebras mas oscuras (sal y pimienta)
    dark = N.new('ShaderNodeMath')
    dark.operation = 'GREATER_THAN'
    Lk.new(info.outputs['Random'], dark.inputs[0])
    dark.inputs[1].default_value = 0.76
    shade = N.new('ShaderNodeMapRange')
    Lk.new(dark.outputs[0], shade.inputs['Value'])
    shade.inputs['To Min'].default_value = 1.0
    shade.inputs['To Max'].default_value = 0.45
    mul = N.new('ShaderNodeMix')
    mul.data_type = 'RGBA'
    mul.blend_type = 'MULTIPLY'
    mul.inputs['Factor'].default_value = 1.0
    Lk.new(ramp.outputs['Color'], mul.inputs[6])
    Lk.new(shade.outputs['Result'], mul.inputs[7])
    Lk.new(mul.outputs[2], bsdf.inputs['Color'])
    for k_, v in (('Roughness', 0.42), ('Radial Roughness', 0.6), ('Coat', 0.02),
                  ('Random Roughness', 0.2)):
        bsdf.inputs[k_].default_value = v
    out = N.new('ShaderNodeOutputMaterial')
    Lk.new(bsdf.outputs[0], out.inputs['Surface'])
    return m


def mat_scalp():
    m = bpy.data.materials.new('hair_scalp')
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    a = m.node_tree.nodes.new('ShaderNodeAttribute')
    a.attribute_name = 'scalpcol'
    m.node_tree.links.new(a.outputs['Color'], b.inputs['Base Color'])
    b.inputs['Roughness'].default_value = 0.75
    return m


def build_hair_curves(S, root):
    rng = np.random.default_rng(HAIR['seed'])
    scalp = build_scalp(S)
    scalp_ob = C.make_object('hair_scalp', scalp, mat_scalp(), root, colors=True, colname='scalpcol')
    G, D = grow_guides(S, rng)
    n, k = G.shape[:2]
    cv = bpy.data.hair_curves.new('hair_curves')
    cv.add_curves([k] * n)
    cv.position_data.foreach_set('vector', G.astype(np.float32).ravel())
    cv.attributes.new('up', 'FLOAT_VECTOR', 'CURVE').data.foreach_set('vector', D.astype(np.float32).ravel())
    mat = mat_hair_curves(S)
    cv.materials.append(mat)
    ob = bpy.data.objects.new('hair_curves', cv)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = root
    mod = ob.modifiers.new('hair', 'NODES')
    mod.node_group = hair_node_tree(scalp_ob, mat)
    print(f'[hugo] pelo: {n} guias', flush=True)
    return scalp, ob


EXPR = {
    'neutral': dict(lid_up=26, lid_lo=-34, gaze=(0, -2), tilt=0, pupil=0.4,
                    brow={1: (0, 0, 0), -1: (0, 0, 0)},
                    mouth=dict(w=0.19, cl=0.02, cr=0.02, up=0.0, open=0.0)),
    'thinking': dict(lid_up=22, lid_lo=-28, gaze=(16, -16), tilt=0, pupil=0.38,
                     brow={1: (0.06, 0.1, 0.06), -1: (-0.03, -0.03, 0.0)},
                     mouth=dict(w=0.13, cl=-0.012, cr=0.03, up=0.0, open=0.0, shift=0.07), lips=0.22,
                     indicator='thinking'),
    'working': dict(lid_up=10, lid_lo=-24, gaze=(-20, 4), tilt=10, pupil=0.4,
                    brow={1: (-0.1, -0.03, 0.04), -1: (-0.1, -0.03, 0.04)},
                    mouth=dict(w=0.13, cl=-0.016, cr=-0.006, up=0.0, open=0.0, shift=-0.02), lips=0.22,
                    indicator='working'),
    'happy': dict(lid_up=14, lid_lo=12, gaze=(0, 0), tilt=0, pupil=0.4,
                  brow={1: (0.05, 0.06, 0.03), -1: (0.05, 0.06, 0.03)},
                  mouth=dict(w=0.22, cl=0.07, cr=0.07, up=-0.01, open=0.17, teeth=True, teeth_h=0.045,
                             tongue=True),
                  indicator='happy'),
    'error': dict(lid_up=38, lid_lo=-42, gaze=(0, 0), tilt=-6, pupil=0.26, iris=0.78,
                  brow={1: (0.1, 0.03, -0.03), -1: (0.1, 0.03, -0.03)},
                  mouth=dict(w=0.16, cl=-0.03, cr=-0.03, up=0.0, open=0.0), lips=0.22,
                  indicator='error'),
    'done': dict(lid_up=28, lid_lo=-30, gaze=(0, 0), tilt=0, pupil=0.42,
                 brow={1: (0.04, 0.05, 0.02), -1: (0.04, 0.05, 0.02)},
                 mouth=dict(w=0.2, cl=0.065, cr=0.065, up=-0.01, open=0.11, teeth=True, teeth_h=0.04),
                 indicator='done', hands=S['done_pose']),
}


# poses de mano. .R = mano derecha del personaje (izquierda de la imagen).
# idle (todos los estados salvo done): brazos colgando, manos fuera de cuadro; .R usa la misma pose en espejo
REST = dict(wrist=(1.48, 0.05, -4.2), F=(0, 0, -1), N=(1, 0, 0), side=1,
            curl=dict(index=(30, 30, 20), middle=(30, 30, 20), ring=(30, 30, 20), pinky=(30, 30, 20)),
            thumb=dict(dir=(0, -1, -0.5), up=(0, 0, -1), curl=(10, 10)), pole=(0.3, 1.0, 0.0))
# pulgar arriba (FEEDBACK9, como el done de Alfred/Bob): mano DERECHA del personaje (izquierda de la imagen) junto a
# la mejilla, codo abajo junto al costado y antebrazo largo y recto casi vertical. F es la direccion codo->muneca que
# da el IK de arm_path (resuelta por punto fijo), asi la muneca sigue recta; puno de perfil y pulgar vertical
THUMBS = dict(wrist=(-1.3, -1.2, -0.95), F=(0.227, -0.248, 0.942), N=(-0.974, -0.058, 0.22), side=-1,
              curl=dict(index=(88, 96, 70), middle=(90, 98, 70), ring=(90, 98, 70), pinky=(88, 96, 70)),
              thumb=dict(dir=(0.0, 0.0, 1.0), up=(-0.6, -0.8, 0.0), curl=(0, 0)),
              pole=(0.4, -0.2, -1.0), cuff=-0.1)
# variante (review/done_alt): punio algo mas alto y metido hacia la cara
THUMBS_OUT = dict(THUMBS, wrist=(-1.2, -1.2, -0.9), F=(0.231, -0.208, 0.95), N=(-0.973, -0.049, 0.225),
                  pole=(0.3, 0.0, -1.0))
HAND_POSES = {
    'thumbs': dict(R=THUMBS, L=REST),
    'thumbs_out': dict(R=THUMBS_OUT, L=REST),
    'rest': dict(R=REST, L=REST),
}
REVIEW_EXPR = {'done_alt': dict(EXPR['done'], shape='done', hands='thumbs_out')}
ALL_EXPR = {**EXPR, **REVIEW_EXPR}
# encuadre del icono por expresion: done algo mas abierto y desplazado para que el puno entre entero
ICON_CAM = {'done': dict(height=3.6, center=(-0.18, -0.3)),
            'done_alt': dict(height=3.6, center=(-0.18, -0.3))}


def parse_args():
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    a = dict(out=None, expr=list(EXPR), quick=False, review=False, samples=None, closeup=False, view=None)
    i = 0
    while i < len(argv):
        k = argv[i]
        if k == '--out':
            a['out'] = argv[i + 1]
            i += 1
        elif k == '--expr':
            a['expr'] = argv[i + 1].split(',')
            i += 1
        elif k == '--samples':
            a['samples'] = int(argv[i + 1])
            i += 1
        elif k == '--quick':
            a['quick'] = True
        elif k == '--review':
            a['review'] = True
        elif k == '--closeup':
            a['closeup'] = True
        elif k == '--view':
            a['view'] = [tuple(float(x) for x in v.split(':')) for v in argv[i + 1].split(';')]
            i += 1
        i += 1
    return a


def setup_render(quick, samples):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    prefs = bpy.context.preferences.addons['cycles'].preferences
    for kind in ('OPTIX', 'CUDA'):
        try:
            prefs.compute_device_type = kind
            prefs.get_devices()
            devs = [d for d in prefs.devices if d.type == kind]
            if devs:
                for d in prefs.devices:
                    d.use = d.type == kind
                sc.cycles.device = 'GPU'
                break
        except TypeError:
            continue
    res = 768 if quick else 1536
    sc.render.resolution_x = sc.render.resolution_y = res
    sc.render.resolution_percentage = 100
    sc.cycles.samples = samples or (64 if quick else 384)
    sc.cycles.use_denoising = True
    sc.cycles.denoiser = 'OPENIMAGEDENOISE'
    sc.cycles.max_bounces = 10
    sc.cycles.diffuse_bounces = 4
    sc.cycles.glossy_bounces = 4
    sc.cycles.transparent_max_bounces = 8
    sc.cycles_curves.shape = 'THICK'
    sc.cycles_curves.subdivisions = 3
    sc.render.film_transparent = True
    sc.render.filter_size = 1.2
    sc.render.image_settings.file_format = 'PNG'
    sc.render.image_settings.color_mode = 'RGBA'
    sc.render.image_settings.color_depth = '16'
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.exposure = 0.15
    world = bpy.data.worlds.new('studio')
    world.use_nodes = True
    bg = world.node_tree.nodes['Background']
    bg.inputs['Color'].default_value = L('#5a4a40')
    bg.inputs['Strength'].default_value = 0.35
    sc.world = world


def add_light(name, kind, loc, target, energy, color, size):
    ld = bpy.data.lights.new(name, kind)
    ld.energy = energy
    ld.color = color[:3]
    if kind == 'AREA':
        ld.shape = 'DISK'
        ld.size = size
    else:
        ld.shadow_soft_size = size
    ob = bpy.data.objects.new(name, ld)
    bpy.context.scene.collection.objects.link(ob)
    ob.location = loc
    d = C.Vector(target) - C.Vector(loc)
    ob.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()
    return ob


def setup_lights_camera():
    add_light('key', 'AREA', (-5.5, -7.0, 4.5), (0, 0, -0.3), 2800, L('#fff1e2'), 5.0)
    add_light('fill', 'AREA', (7.0, -6.0, 0.5), (0, 0, -0.6), 1000, L('#e6ecff'), 6.0)
    add_light('rim_l', 'AREA', (-5.0, 6.0, 3.5), (0, 0, 0), 1800, L('#fff1dc'), 3.0)
    add_light('rim_r', 'AREA', (5.0, 6.0, 2.5), (0, 0, -0.5), 1500, L('#ffe4d0'), 3.0)
    add_light('bounce', 'AREA', (0.0, -5.0, -5.0), (0, 0, -1.2), 350, L('#ffd8b8'), 6.0)
    cd = bpy.data.cameras.new('cam')
    cd.lens = 85
    cd.sensor_width = 36
    cam = bpy.data.objects.new('cam', cd)
    bpy.context.scene.collection.objects.link(cam)
    bpy.context.scene.camera = cam
    return cam


def aim_camera(cam, yaw_deg=0.0, height=4.0, center=(0.0, -0.5), pitch_deg=4.0):
    cd = cam.data
    fov = 2 * math.atan(cd.sensor_width / 2 / cd.lens)
    dist = height / 2 / math.tan(fov / 2) * 1.0
    yaw, pitch = math.radians(yaw_deg), math.radians(pitch_deg)
    cx, cz = center
    target = C.Vector((cx, 0.1, cz))
    off = C.Vector((math.sin(yaw) * math.cos(pitch), -math.cos(yaw) * math.cos(pitch), math.sin(pitch))) * dist
    cam.location = target + off
    cam.rotation_euler = (-off).to_track_quat('-Z', 'Y').to_euler()


def mat_glass(name):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    b.inputs['Base Color'].default_value = (0.92, 0.96, 1.0, 1.0)
    b.inputs['Roughness'].default_value = 0.09
    b.inputs['Transmission Weight'].default_value = 1.0
    b.inputs['IOR'].default_value = 1.45
    return m


def build_glasses(S, head_surf, root, mats):
    """Gafas de montura fina: dos aros, puente y varillas hacia las orejas; cristales transparentes."""
    rx, rz = 0.31, 0.27
    rims, lenses = [], []
    centers = []
    for s in (-1, 1):
        x = s * (S['eye_x'] + 0.02)
        loc, nor = head_surf.front(x, S['eye_z'] - 0.02)
        c = loc + nor * 0.09
        centers.append(c)
        n = np.array([0.0, -1.0, 0.0])
        # aro: circulo en el plano perpendicular a la mirada
        a = np.linspace(0, C.TAU, 48, endpoint=False)
        squash = 0.92
        P = np.stack([c[0] + rx * np.cos(a), np.full(48, c[1]), c[2] + rx * squash * np.sin(a)], -1)
        rims.append(C.sweep(P, np.tile(n, (48, 1)), np.full(48, 0.009), np.full(48, 0.008), 12, closed=True))
        sp = C.sphere_part(1.0, 32, 16)
        sp.v = sp.v * np.array([rx * 0.94, 0.012, rx * squash * 0.94]) + c
        lenses.append(sp)
    c0, c1 = centers
    mid = (c0 + c1) / 2
    a = np.linspace(0, 1, 12)
    bridge = np.stack([mid[0] + (c1[0] - c0[0]) * 0.5 * np.sin(np.pi * a) * 0,
                       np.full(12, mid[1] - 0.01 * np.sin(np.pi * a)),
                       mid[2] + 0.04 * np.sin(np.pi * a)], -1)
    bridge[:, 0] = np.linspace(c0[0] + rx * 0.85, c1[0] - rx * 0.85, 12)
    rims.append(C.sweep(bridge, np.tile([0, -1, 0], (12, 1)), np.full(12, 0.009), np.full(12, 0.008), 10))
    # varillas: del borde exterior de cada aro, detras de la oreja
    for c, s in zip(centers, (-1, 1)):
        pts = np.array([[c[0] + s * rx * 0.98, c[1] + 0.02, c[2] + 0.04],
                        [s * 0.82, -0.05, c[2] + 0.06],
                        [s * 0.9, 0.12, c[2] - 0.02],
                        [s * 0.88, 0.28, c[2] - 0.16]])
        pts = C.smooth_path(pts, 3)
        ts = np.linspace(0, 1, len(pts))
        rims.append(C.sweep(pts, np.tile([0, -1, 0], (len(pts), 1)), 0.009 - 0.003 * ts, 0.008 - 0.002 * ts, 10))
    ob = C.make_object('glasses_frame', C.Part.join(rims), mats['frame'], root)
    C.make_object('glasses_lens', C.Part.join(lenses), mats['glass'], root)
    return ob


# cuerpo estilizado: torso como union suave (SDF) de pecho, abdomen, espalda, trapecios inclinados y deltoides;
# se muestrea por rayos desde un centro (rejilla phi x theta como el torso de character.py) y lleva el punto de
# la chaqueta y pliegues de tela. Los brazos son un solo tubo hombro-codo-muneca que nace dentro del deltoide.
BODY = dict(
    chest=((0.0, 0.1, -2.0), (1.03, 0.68, 0.82)),
    belly=((0.0, 0.12, -3.22), (0.86, 0.62, 1.15)),
    back=((0.0, 0.28, -1.75), (0.86, 0.5, 0.58)),
    trap=((0.18, 0.2, -1.34), (0.92, 0.18, -1.52), 0.19),
    delt=((1.06, 0.14, -1.77), (0.25, 0.29, 0.3)),
    blend=0.22, center=(0.0, 0.15, -2.4),
    joint=(1.12, 0.14, -1.8), upper=0.27, fore=0.245, cuff=0.215, neck_hole=0.545,
)


def sd_ellipsoid(P, c, r):
    r = np.asarray(r)
    return (np.linalg.norm((P - np.asarray(c)) / r, axis=-1) - 1.0) * r.min()


def sd_capsule(P, a, b, r):
    a, b = np.asarray(a), np.asarray(b)
    pa, ba = P - a, b - a
    h = np.clip(np.sum(pa * ba, -1) / ba.dot(ba), 0, 1)
    return np.linalg.norm(pa - ba * h[..., None], axis=-1) - r


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


def torso_sdf(P):
    B = BODY
    d = smin(sd_ellipsoid(P, *B['chest']), sd_ellipsoid(P, *B['belly']), 0.35)
    d = smin(d, sd_ellipsoid(P, *B['back']), B['blend'])
    for s in (-1, 1):
        m = np.array([s, 1, 1])
        a, b, r = B['trap']
        d = smin(d, sd_capsule(P, np.array(a) * m, np.array(b) * m, r), B['blend'])
        c, rr = B['delt']
        d = smin(d, sd_ellipsoid(P, np.array(c) * m, rr), 0.16)
    return d


def torso_grid_sdf(nphi=640, nth=720):
    """Superficie del torso: por cada direccion, ultimo cruce del SDF a lo largo del rayo desde el centro."""
    c0 = np.array(BODY['center'])
    phis = np.radians(np.linspace(-180, 180, nphi, endpoint=False))
    ths = np.radians(np.linspace(4, 176, nth))
    ts = np.linspace(0.0, 3.2, 321)
    P = np.zeros((nphi, nth, 3))
    for j, th in enumerate(ths):
        D = np.stack([np.sin(phis) * np.sin(th), -np.cos(phis) * np.sin(th), np.full(nphi, np.cos(th))], -1)
        Q = c0 + D[:, None] * ts[None, :, None]
        sd = torso_sdf(Q)
        inside = sd < 0
        last = (len(ts) - 1) - np.argmax(inside[:, ::-1], axis=1)
        last = np.clip(last, 0, len(ts) - 2)
        i = np.arange(nphi)
        s0, s1 = sd[i, last], sd[i, last + 1]
        # regula falsi sobre el SDF real (la interpolacion lineal sola deja anillos de sombreado)
        ta, tb = ts[last], ts[last + 1]
        for _ in range(6):
            t = ta + (tb - ta) * np.clip(-s0 / np.maximum(s1 - s0, 1e-12), 0.02, 0.98)
            st = torso_sdf(c0 + D * t[:, None])
            neg = st < 0
            ta, s0 = np.where(neg, t, ta), np.where(neg, st, s0)
            tb, s1 = np.where(neg, tb, t), np.where(neg, s1, st)
        P[:, j] = c0 + D * t[:, None]
    return P


def cloth_folds(P):
    """Pliegues de tela (altura sobre la normal): tirones diagonales desde la axila hacia el centro, delante y detras,
    y arrugas suaves de la cintura."""
    x, y, z = P[..., 0], P[..., 1], P[..., 2]
    ax = np.abs(x)
    h = np.zeros_like(x)
    # coordenada perpendicular a la diagonal axila -> centro del pecho
    dx, dz = ax - 0.92, z + 2.25
    along = (dx * -0.55 + dz * -0.83)
    across = dx * 0.83 - dz * 0.55
    env = np.exp(-(along / 0.38) ** 2 - (across / 0.3) ** 2) * C.ss(0.3, 0.75, ax)
    h += 0.012 * env * np.sin(C.TAU * across / 0.24 + 0.6)
    waist = np.exp(-((z + 3.05) / 0.28) ** 2)
    h += 0.008 * waist * np.sin(C.TAU * (z + 0.08 * np.sin(3.0 * x)) / 0.14) * C.ss(0.2, 0.7, ax)
    return h


def build_body_torso(S):
    P = torso_grid_sdf()
    nphi, ns = P.shape[:2]
    N = C.grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    P = P + N * cloth_folds(P)[..., None]
    # coordenadas de punto: u = arco firmado desde el centro delantero, v = altura
    du = np.linalg.norm(np.diff(P, axis=0), axis=-1)
    u = np.concatenate([np.zeros((1, ns)), np.cumsum(du, 0)], 0)
    u = u - u[nphi // 2][None, :]
    # cada fila tiene otro perimetro: con el arco tal cual los canales de la espalda siguen curvas de nivel
    # (rombos concentricos). Fraccion de vuelta x perimetro fijo, redondeado a un numero entero de canales
    circ = du.sum(0) + np.linalg.norm(P[0] - P[-1], axis=-1)
    col = S['knit_col']
    ref = round(float(np.median(circ)) / col) * col
    u = (u / circ[None, :]) * ref
    # filas de punto horizontales: con el arco por meridiano las vueltas se curvan y dan rombos en la espalda
    v = -P[..., 2]
    N = C.grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    P = P + N * C.knit_height(u, v, S)[..., None]
    f, ci, cj = C.grid_faces(nphi, ns, closed_u=True)
    ci = ci % nphi
    test = np.cross(P[1, ns // 2] - P[0, ns // 2], P[0, ns // 2 + 1] - P[0, ns // 2])
    if np.dot(test, N[0, ns // 2]) < 0:
        f, ci, cj = f[:, ::-1], ci[:, ::-1], cj[:, ::-1]
    # hueco del cuello: fuera las caras dentro del radio de los cuellos (asoman por el sin cruzar el torso)
    V = P.reshape(-1, 3)
    rh = np.hypot(V[:, 0], V[:, 1] - S['neck_y'])
    drop = ((rh < BODY['neck_hole']) & (V[:, 2] > -1.55))[f].any(1)
    keep = ~drop
    return C.Part(V, f[keep], np.stack([u[ci, cj], v[ci, cj]], -1)[keep])


def two_bone(J, W, a, b, pole):
    """Codo para un brazo de longitudes a (hombro-codo) y b (codo-muneca) con el codo hacia `pole`."""
    J, W, pole = (np.asarray(v, float) for v in (J, W, pole))
    d = W - J
    L_ = np.linalg.norm(d)
    L_ = min(L_, (a + b) * 0.999)
    u = d / np.linalg.norm(d)
    x = (a * a - b * b + L_ * L_) / (2 * L_)
    hgt = math.sqrt(max(a * a - x * x, 0.0))
    p = C.unit(pole - u * np.dot(pole, u))
    return J + u * x + p * hgt


def arm_path(spec, side, scale):
    """Eje de la manga: dentro del deltoide -> hombro -> codo -> muneca, con la ultima parte girada hacia F."""
    B = BODY
    m = np.array([side, 1, 1])
    J = np.array(B['joint']) * m
    F = C.unit(np.asarray(spec['F'], float))
    end = np.asarray(spec['wrist'], float) - F * spec.get('cuff', 0.12) * scale
    pre = end - F * 0.3
    E = two_bone(J, pre, 1.18, 1.12, np.asarray(spec.get('pole', (0.4, 0.3, -1.0))) * m)
    A = [J + np.array([-0.2 * side, 0.0, 0.12]), J, E, pre, end]
    path = []
    for i in range(len(A) - 1):
        n = 6 if i == 0 else 16
        for t in np.linspace(0, 1, n, endpoint=False):
            path.append(A[i] * (1 - t) + A[i + 1] * t)
    path.append(A[-1])
    P = C.smooth_path(np.array(path), 6)
    P[-1] = end
    # remuestreo uniforme y denso (el punto de la manga necesita ~4 muestras por fila)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    s_ = np.linspace(0, arc[-1], max(int(arc[-1] / 0.011), 40))
    P = np.stack([np.interp(s_, arc, P[:, k]) for k in range(3)], -1)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    iE = int(np.argmin(np.linalg.norm(P - E, axis=1)))
    return P, arc, arc[iE], E


def build_sleeve(S, spec, side, scale, rng):
    """Manga ajustada al brazo: deltoide redondo arriba, codo con pliegues de compresion, antebrazo que se
    estrecha, punio acanalado y borde. -> (Part manga, Part para chequeo sin el tramo del hombro, eje)."""
    B = BODY
    P, arc, aE, E = arm_path(spec, side, scale)
    n = len(P)
    tot = arc[-1]
    t = arc / tot
    tE = aE / tot
    cuff = C.ss(0.86, 0.9, t)
    rad = np.interp(t, [0.0, 0.1, 0.3, tE, 0.86, 1.0],
                    [B['upper'] * 1.18, B['upper'] * 1.12, B['upper'], B['upper'] * 0.93, B['fore'], B['fore']])
    rad = rad * (1 - cuff) + B['cuff'] * cuff
    # plano del codo (para poner los pliegues en la cara interior)
    T = C.unit(np.gradient(P, axis=0))
    O = np.tile(C.unit(np.array([side * 0.6, 0.5, -0.6])), (n, 1))
    ph = rng.uniform(0, C.TAU, 3)
    elbow = np.exp(-((arc - aE) / 0.22) ** 2)

    def mod(i, th):
        ii = i[:, 0]
        a_ = arc[ii][:, None]
        tt = t[ii][:, None]
        # pliegues: anillos ondulados de compresion en el codo, tirones diagonales en el brazo, flojedad abajo
        ring = 0.05 * elbow[ii][:, None] * (0.5 + 0.5 * np.cos(th - np.pi)) * np.sin(C.TAU * a_ / 0.13 + ph[0]
                                                                                       + 0.8 * np.sin(th))
        diag = 0.022 * np.sin(2 * th + C.TAU * a_ / 0.55 + ph[1]) * (1 - cuff[ii][:, None])
        slack = 0.03 * np.sin(3 * th + ph[2] + 4 * tt) * C.ss(0.15, 0.4, tt) * (1 - C.ss(0.6, 0.85, tt))
        rib = 0.045 * cuff[ii][:, None] * np.cos(28 * th)
        r_ = rad[ii][:, None]
        knit = C.knit_height(th * r_, a_, S) / r_ * (1 - cuff[ii][:, None])
        return 1 + ring + diag + slack + rib + knit

    sleeve = C.sweep(P, O, rad, rad * 0.94, 160, mod=mod)
    Tl = T[-1]
    W = C.unit(np.cross(Tl, O[-1]))
    Hh = np.cross(W, Tl)
    th = np.linspace(0, C.TAU, 64, endpoint=False)
    ring = P[-1] + (np.cos(th)[:, None] * W + 0.94 * np.sin(th)[:, None] * Hh) * rad[-1] * 1.03
    rim = C.sweep(ring, np.tile(Tl, (64, 1)), np.full(64, 0.028), np.full(64, 0.028), 10, closed=True)
    # tramo para el chequeo de interpenetracion: desde medio brazo (el hombro entra a proposito en el torso)
    k = int(np.searchsorted(t, 0.4))
    chk = C.sweep(P[k:], O[k:], rad[k:], rad[k:] * 0.94, 32, mod=lambda i, th: mod(i + k, th))
    return C.Part.join([sleeve, rim]), chk, P


# cuellos como perfiles (r, z) de revolucion alrededor del eje del cuello: el borde de arriba se dobla hacia dentro
# hasta tocar el cuello (sin hueco oscuro ni piel debajo) y el del jersey baja ensanchandose dentro del torso
COLLAR_SHIRT = [(0.446, -1.14), (0.446, -1.03), (0.45, -0.99), (0.468, -0.968), (0.49, -0.972),
                (0.504, -0.995), (0.509, -1.05), (0.512, -1.35)]
COLLAR_JACKET = [(0.516, -1.16), (0.516, -1.1), (0.523, -1.066), (0.542, -1.05), (0.562, -1.058),
                 (0.574, -1.085), (0.58, -1.18), (0.588, -1.3), (0.615, -1.45), (0.645, -1.6), (0.655, -1.72)]


def revolve(S, prof, nu=240, it=3):
    """Superficie de revolucion de un perfil (r, z) suavizado con Chaikin alrededor del eje del cuello."""
    Q = np.asarray(prof, float)
    for _ in range(it):
        A, B = Q[:-1], Q[1:]
        Q = np.concatenate([Q[:1], np.stack([0.75 * A + 0.25 * B, 0.25 * A + 0.75 * B], 1).reshape(-1, 2), Q[-1:]])
    th = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    R, Z = Q[None, :, 0], Q[None, :, 1]
    T = th[:, None]
    P = np.stack(np.broadcast_arrays(R * np.sin(T), S['neck_y'] - R * np.cos(T), Z), -1)
    f, ci, cj = C.grid_faces(nu, len(Q), closed_u=True)
    return C.Part(P.reshape(-1, 3), f, np.stack([ci / nu, cj / len(Q)], -1))


def build_lapels(S, torso_surf, root, mats):
    """Solapas de la chaqueta: dos tiras que bajan desde el cuello hasta el pecho con muesca."""
    def front_pt(x, z, off=0.03):
        loc, nor = torso_surf.front(x, z)
        return (loc + nor * off) if loc is not None else np.array([x, -0.9, z])

    parts = []
    for s in (-1, 1):
        path = np.array([front_pt(s * 0.22, -1.6, 0.03), front_pt(s * 0.3, -1.76, 0.035),
                         front_pt(s * 0.38, -1.93, 0.035), front_pt(s * 0.46, -2.13, 0.035)])
        path = C.smooth_path(path, 3)
        O = np.tile(np.array([0.0, -1.0, 0.0]), (len(path), 1))
        parts.append(C.sweep(path, O, np.linspace(0.045, 0.065, len(path)), np.full(len(path), 0.012), 10))
    C.make_object('lapels', C.Part.join(parts), mats['jacket'], root)


def build_tie(S, torso_surf, root, mats):
    """Corbata azul del agente proyectada sobre el pecho."""
    def front_pt(x, z, off=0.03):
        loc, nor = torso_surf.front(x, z)
        return (loc + nor * off) if loc is not None else np.array([x, -0.9, z])

    # corbata: nudo + hoja que se ensancha y remata en punta
    knot_c = front_pt(0.0, -1.66, 0.04)
    zs = np.linspace(-1.7, -2.8, 26)
    P = np.array([front_pt(0.0, z, 0.045) for z in zs])
    O = np.tile(np.array([0.0, -1.0, 0.0]), (len(P), 1))
    t = np.linspace(0, 1, len(P))
    w = 0.055 + 0.075 * np.clip((t - 0.08) / 0.35, 0, 1) * (1 - 0.85 * np.clip((t - 0.8) / 0.2, 0, 1)) + 0.001
    blade = C.sweep(P, O, w, np.full(len(P), 0.018), 12, expo=3.0)
    knot = C.sphere_part(1.0, 24, 12)
    knot.v = knot.v * np.array([0.07, 0.035, 0.06]) + knot_c
    return C.make_object('tie', C.Part.join([knot, blade]), mats['tie'], root)


def build(S):
    t0 = time.time()
    root = C.empty('hugo')
    head = C.build_head(S)
    head_surf = C.Surface(head)
    head_ob = C.make_object('head', head, None, root)
    spots = []
    for sx in (-1, 1):
        d = np.array([0.55 * sx, -0.78, -0.3])
        d /= np.linalg.norm(d)
        spots.append((tuple(C.head_points(d[None], S)[0]), 0.24, S['blush'], 0.35))
    nd = np.array([0.0, -1.0, -0.4])
    nd /= np.linalg.norm(nd)
    spots.append((tuple(C.head_points(nd[None], S)[0] + nd * 0.08), 0.14, S['nose_tip'], 0.7))
    skin = C.mat_skin(S, head_ob, spots)
    skin_lid = C.mat_skin(S, head_ob, spots, sss=0.12, name='skin_lid', sss_scale=0.04)
    head_ob.data.materials.append(skin)
    eye_mat, pupil, iris = C.mat_eye(S)
    mats = dict(
        eye=eye_mat, skin_local=skin_lid,
        catch=C.mat_flat('catch', (1, 1, 1, 1), emit=7.0),
        lash=C.mat_flat('lash', S['lash'], rough=0.4, coat=0.2),
        brow=C.mat_brow(S),
        lip=C.mat_lip(S),
        tear=C.mat_flat('tear', L('#f6e4e0'), rough=0.03, coat=1.0, sss=0.2),
        crease=C.mat_flat('crease', tuple(c * 0.78 for c in S['skin'][:3]) + (1,), rough=0.5, sss=0.2),
        lipline=C.mat_flat('lipline', S['lipline'], rough=0.5),
        cavity=C.mat_flat('cavity', S['cavity'], rough=0.7),
        teeth=C.mat_flat('teeth', S['teeth'], rough=0.25, coat=0.4, sss=0.2),
        tongue=C.mat_flat('tongue', S['tongue'], rough=0.35, coat=0.3, sss=0.35),
        shirt=C.mat_wool('shirt', S['shirt'], 130.0),
        jacket=C.mat_wool('jacket', S['jacket'], 110.0),
        jacket_fuzz=C.mat_wool('jacket_fuzz', S['jacket'], 140.0),
        tie=C.mat_flat('tie', S['tie'], rough=0.35, coat=0.3),
        metal=C.mat_flat('metal', S['metal'], rough=0.2, coat=0.7),
        frame=C.mat_flat('frame', S['frame'], rough=0.35, coat=0.4),
        glass=mat_glass('glass'),
        bubble=C.mat_flat('bubble', L('#ffffff'), rough=0.3, coat=0.6, sss=0.3),
        accent=C.mat_flat('accent', L('#1e5db3'), rough=0.3, coat=0.6),
        error=C.mat_flat('error', L('#e3383a'), rough=0.3, coat=0.6),
        white=C.mat_flat('white', L('#ffffff'), rough=0.3),
        sweat=C.mat_flat('sweat', L('#9fd4ff'), rough=0.05, coat=1.0, sss=0.4),
        spark=C.mat_flat('spark', L('#ffc93d'), rough=0.25, coat=0.6),
        done=C.mat_flat('done', L('#2fb36b'), rough=0.3, coat=0.6),
        nail=C.mat_flat('nail', L('#e8b8a8'), rough=0.18, coat=0.9, sss=0.3),
        skin=skin,
    )
    eyes = []
    neutral = EXPR['neutral']
    for s in (-1, 1):
        loc, nor = head_surf.front(s * S['eye_x'], S['eye_z'])
        center = loc + np.array([0.0, 1.0, 0.0]) * S['eye_r'] * S['eye_depth']
        eye = C.build_eye(S, s, tuple(center), mats, root)
        eyes.append(eye)
        bpy.context.view_layer.update()
        C.conform_lids(eye, eye['socket'].matrix_world, head_surf,
                       {n: (e['lid_up'], e['lid_lo'], e['tilt']) for n, e in EXPR.items()}, S['lid_fillet'])
        C.make_object(f'eye{s:+d}_crease', C.build_crease(S, s, eye['socket'].matrix_world, head_surf,
                                                          neutral['lid_up']), mats['crease'], root)
    brows = {}
    for s in (-1, 1):
        shapes = {n: C.brow_part(S, head_surf, s, e['brow'][s]) for n, e in EXPR.items()}
        brows[s] = C.add_shape_keys(C.make_object(f'brow{s:+d}', shapes['neutral'], mats['brow'], root,
                                                  colors=True, colname='browcol'), shapes)

    def lips_s(k):
        return dict(S, **{key: S[key] * k for key in ('lip_up_h', 'lip_lo_h', 'lip_up_lift', 'lip_lo_lift')})
    # labios finos en las bocas cerradas (thinking/working/error): solo la linea, sin volumen rosa
    mouth_shapes = {n: C.mouth_parts(lips_s(e.get('lips', 1.0)), head_surf, e['mouth']) for n, e in EXPR.items()}
    mouth = []
    for key, mat in (('cavity', 'cavity'), ('teeth', 'teeth'), ('tongue', 'tongue'), ('tongue_out', 'tongue'),
                     ('line', 'lipline')):
        shapes = {n: m[key] for n, m in mouth_shapes.items()}
        mouth.append(C.add_shape_keys(C.make_object(f'mouth_{key}', shapes['neutral'], mats[mat], root), shapes))
    lips = {n: C.Part.join([m['lip_up'], m['lip_lo']]) for n, m in mouth_shapes.items()}
    mouth.append(C.add_shape_keys(C.make_object('mouth_lips', lips['neutral'], mats['lip'], root, colors=True,
                                                colname='lipfade'), lips))

    build_glasses(S, head_surf, root, mats)

    torso = build_body_torso(S)
    C.make_object('jacket', torso, mats['jacket'], root)
    torso_surf = C.Surface(torso)
    shirt_collar = C.orient_out(revolve(S, COLLAR_SHIRT), (0.0, S['neck_y'], -1.1))
    C.make_object('collar_shirt', shirt_collar, mats['shirt'], root)
    jacket_collar = C.orient_out(revolve(S, COLLAR_JACKET), (0.0, S['neck_y'], -1.3))
    C.make_object('collar_jacket', jacket_collar, mats['jacket'], root)
    # para el chequeo solo cuenta el tramo visible: la falda del cuello entra a proposito en el torso
    jacket_collar_chk = C.orient_out(revolve(S, [q for q in COLLAR_JACKET if q[1] > -1.14]), (0.0, S['neck_y'], -1.1))
    frng = np.random.default_rng(23)

    def axis_center(z0=None):
        def f(P):
            Q = np.zeros_like(P)
            Q[:, 1] = 0.1
            Q[:, 2] = P[:, 2] if z0 is None else np.minimum(P[:, 2], z0)
            return Q
        return f
    C.make_object('jacket_fuzz', C.Part.join([C.wool_fuzz(torso, S['fuzz'] * 2 if 'fuzz' in S else 3000, frng,
                                                          axis_center()),
                                              C.wool_fuzz(jacket_collar, 800, frng, axis_center())]),
                  mats['jacket_fuzz'], root)
    C.make_object('neck', C.build_neck(S), skin, root)
    build_tie(S, torso_surf, root, mats)
    build_lapels(S, torso_surf, root, mats)
    body_coll = [C.Surface(C.Part.join([head, torso])), C.Surface(shirt_collar), C.Surface(jacket_collar)]

    scalp, _ = build_hair_curves(S, root)

    hand_parts = []
    hands = build_hands(S, mats, root, frng, hand_parts)

    cloth = dict(jacket=torso, collar_shirt=shirt_collar, collar_jacket=jacket_collar_chk, hair_scalp=scalp)
    names = list(cloth)
    pairs = [(a, cloth[a], b, cloth[b]) for i, a in enumerate(names) for b in names[i + 1:]]
    for hname, part in hand_parts:
        pairs += [(hname, part, b, cloth[b]) for b in names]
    C.check_overlaps(pairs)

    ind_root = C.empty('indicators', None, S['indicator_root'])
    ind_root.scale = (S['indicator_scale'],) * 3
    sw = np.array(S['sweat_at'])
    S2 = dict(S, sweat_at=tuple((sw - np.array(S['indicator_root'])) / S['indicator_scale']))
    ind = C.build_indicators(S2, mats, ind_root)
    arm = build_rig(root, eyes)
    organize()
    print(f'[hugo] escena construida en {time.time() - t0:.1f}s', flush=True)
    return dict(root=root, head_surf=head_surf, eyes=eyes, mats=mats, pupil=pupil, iris=iris, ind=ind,
                ind_root=ind_root, brows=brows, mouth=mouth, arm=arm, hands=hands)


def build_hands(S, mats, root, rng, check=None):
    """hand.L/R (piel, origen en la muneca) con sus unas como hijas y la manga sleeve.* con pelusa.
    La pose S['done_pose'] se llama hand.* -> {pose: [objetos]}."""
    out = {}
    for pname, pose in HAND_POSES.items():
        tag = '' if pname == S['done_pose'] else f'_{pname}'
        objs = []
        for side in ('R', 'L'):
            spec, mirror = pose[side], False
            if isinstance(spec, tuple):
                spec, mirror = spec[1], True
            elif spec == 'mirror':
                spec, mirror = pose['R'], True
            elif spec is REST and side == 'R':
                mirror = True
            # la manga de hands.py se descarta: la de Hugo nace en el hombro (build_sleeve)
            F = C.unit(np.asarray(spec['F'], float))
            h = H.build_hand(dict(spec, arm=[np.asarray(spec['wrist'], float) - F * 0.6]), S['hand_scale'])
            sl, chk, path = build_sleeve(S, spec, 1 if spec['wrist'][0] > 0 else -1, S['hand_scale'], rng)
            h.update(sleeve=sl, path=path)
            if mirror:
                h = {k: (v.mirrored_x() if isinstance(v, C.Part) else v * np.array([-1, 1, 1])) for k, v in h.items()}
                chk = chk.mirrored_x()
            path = h['path']

            def nearest(P, path=path):
                d = np.linalg.norm(P[:, None] - path[None], axis=-1)
                return path[d.argmin(1)]
            fuzz = C.wool_fuzz(h['sleeve'], S['fuzz'] // 2 if 'fuzz' in S else 600, rng, nearest)
            w = h['wrist']
            if check is not None:
                check += [(f'hand{tag}.{side}', C.Part(h['skin'].v.copy(), h['skin'].f)),
                          (f'sleeve{tag}.{side}', chk)]
            for part in (h['skin'], h['nails'], h['sleeve'], fuzz):
                part.v = part.v - w
            hand = C.make_object(f'hand{tag}.{side}', h['skin'], mats['skin'], root)
            nails = C.make_object(f'nails{tag}.{side}', h['nails'], mats['nail'], hand)
            sleeve = C.make_object(f'sleeve{tag}.{side}', h['sleeve'], mats['jacket'], root)
            sfuzz = C.make_object(f'sleeve_fuzz{tag}.{side}', fuzz, mats['jacket_fuzz'], sleeve)
            for ob in (hand, sleeve):
                ob.location = w
            objs += [hand, nails, sleeve, sfuzz]
        out[pname] = objs
    return out


HEAD_PARTS = ('head', 'eye', 'brow', 'mouth', 'hair', 'glasses')
GROUPS = [('rig', ('hugo', 'hugo_rig')), ('eyes', ('eye',)), ('brows', ('brow',)), ('mouth', ('mouth_',)),
          ('hair', ('hair_',)), ('head', ('head', 'glasses')),
          ('hands', ('hand', 'nails', 'sleeve')),
          ('body', ('jacket', 'collar', 'shirt', 'tie', 'neck')),
          ('indicators', ('ind',))]


def build_rig(root, eyes):
    """Armature 'hugo_rig': hueso head (cabeza, cara, pelo, gafas) y, colgando de el, eye.L/R y
    lid_up/lid_lo.L/R. .L = izquierda del personaje (+X)."""
    vl = bpy.context.view_layer
    vl.update()
    data = bpy.data.armatures.new('hugo_rig')
    arm = bpy.data.objects.new('hugo_rig', data)
    bpy.context.scene.collection.objects.link(arm)
    arm.parent = root
    vl.objects.active = arm
    bpy.ops.object.mode_set(mode='EDIT')
    hb = data.edit_bones.new('head')
    hb.head, hb.tail = (0.0, 0.1, -0.85), (0.0, 0.1, 0.45)
    plan = []
    for eye in eyes:
        side = '.L' if eye['s'] > 0 else '.R'
        eye['bones'] = dict(eye=f'eye{side}', up=f'lid_up{side}', lo=f'lid_lo{side}')
        for key, ob in (('eye', eye['socket']), ('up', eye['lids']['up']), ('lo', eye['lids']['lo'])):
            b = data.edit_bones.new(eye['bones'][key])
            b.head, b.tail = (0, 0, 0), (0, 0.1, 0)
            b.matrix = ob.matrix_world.copy()
            b.parent = hb
            plan.append(ob)
    bpy.ops.object.mode_set(mode='OBJECT')
    for pb in arm.pose.bones:
        pb.rotation_mode = 'XYZ'
    vl.update()

    def to_bone(ob, bone):
        mw = ob.matrix_world.copy()
        ob.parent, ob.parent_type, ob.parent_bone = arm, 'BONE', bone
        vl.update()
        ob.matrix_world = mw

    for eye in eyes:
        to_bone(eye['ball'], eye['bones']['eye'])
        for cl in eye['catches']:
            to_bone(cl, 'head')
        for which in ('up', 'lo'):
            for ch in list(eye['lids'][which].children):
                to_bone(ch, eye['bones'][which])
    for ob in list(root.children):
        if ob.type in ('MESH', 'CURVES') and ob.name.startswith(HEAD_PARTS):
            to_bone(ob, 'head')
    for ob in plan:
        bpy.data.objects.remove(ob, do_unlink=True)
    vl.update()
    return arm


def organize():
    sc = bpy.context.scene
    for ob in list(sc.collection.objects):
        for gname, prefixes in GROUPS:
            if ob.name in prefixes or (gname != 'rig' and ob.name.startswith(prefixes)):
                coll = bpy.data.collections.get(gname)
                if coll is None:
                    coll = bpy.data.collections.new(gname)
                    sc.collection.children.link(coll)
                coll.objects.link(ob)
                sc.collection.objects.unlink(ob)
                break


def set_expression(rig, name):
    e = ALL_EXPR[name]
    shape = e.get('shape', name)
    rig['pupil'].outputs[0].default_value = e['pupil']
    rig['iris'].outputs[0].default_value = S['iris_ang'] * e.get('iris', 1.0)
    pose = rig['arm'].pose.bones
    for eye in rig['eyes']:
        C.pose_eye_bones(pose, eye, e['lid_up'], e['lid_lo'], e['gaze'], e['tilt'])
        for cl in eye['catches']:
            cl.hide_render = e['lid_lo'] >= e['lid_up'] - 4
    lids = [eye['lidmesh'][w] for eye in rig['eyes'] for w in ('up', 'lo')]
    for ob in list(rig['brows'].values()) + rig['mouth'] + lids:
        C.set_shape(ob, shape)
    for k, objs in rig['ind'].items():
        for ob in objs:
            ob.hide_render = k != e.get('indicator')
    for k, objs in rig['hands'].items():
        for ob in objs:
            ob.hide_render = k != e.get('hands', 'rest')
    bpy.context.view_layer.update()


def save_png(arr, path):
    h, w = arr.shape[:2]
    img = bpy.data.images.new('tmp_out', w, h, alpha=True)
    img.pixels.foreach_set(np.ascontiguousarray(arr, np.float32).ravel())
    img.filepath_raw = path
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def load_png(path):
    img = bpy.data.images.load(path)
    w, h = img.size
    a = np.empty(w * h * 4, np.float32)
    img.pixels.foreach_get(a)
    bpy.data.images.remove(img)
    return a.reshape(h, w, 4)


def downscale(a, size):
    f = a.shape[0] // size
    assert f * size == a.shape[0], (a.shape, size)
    pm = a.copy()
    pm[..., :3] *= pm[..., 3:4]
    pm = pm[:size * f, :size * f].reshape(size, f, size, f, 4).mean((1, 3))
    al = pm[..., 3:4]
    pm[..., :3] = np.where(al > 1e-5, pm[..., :3] / np.maximum(al, 1e-5), 0)
    return pm


def strip(icons, names, sizes, gap=8):
    w = len(names) * (max(sizes) + gap) - gap
    h = sum(sizes) + gap * (len(sizes) - 1)
    canvas = np.zeros((h, w, 4), np.float32)
    top = 0
    for size in sizes:
        for i, name in enumerate(names):
            x = i * (max(sizes) + gap) + (max(sizes) - size) // 2
            y = h - top - size
            canvas[y:y + size, x:x + size] = icons[(name, size)]
        top += size + gap
    return canvas


def main():
    a = parse_args()
    out = a['out'] or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'assets', 'agents3d')
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    setup_render(a['quick'], a['samples'])
    cam = setup_lights_camera()
    rig = build(S)
    sc = bpy.context.scene
    sizes = (512, 128, 64, 48, 32) if not a['quick'] else (768, 128, 48)
    icons = {}
    if a['closeup']:
        for name in a['expr']:
            set_expression(rig, name)
            aim_camera(cam, yaw_deg=-8.0, height=1.7, center=(0.0, -0.15))
            sc.render.filepath = os.path.join(out, f'face-{name}.png')
            bpy.ops.render.render(write_still=True)
        return
    if a['view']:
        for name in a['expr']:
            set_expression(rig, name)
            for k, (yaw, cx, cz, h) in enumerate(a['view']):
                aim_camera(cam, yaw_deg=yaw, height=h, center=(cx, cz))
                sc.render.filepath = os.path.join(out, f'view-{name}-{k}.png')
                bpy.ops.render.render(write_still=True)
        return

    def shoot(name, dest, big_sizes, icon_sizes):
        set_expression(rig, name)
        aim_camera(cam, yaw_deg=-8.0)
        raw = os.path.join(dest, f'_raw-{name}.png')
        sc.render.filepath = raw
        t = time.time()
        bpy.ops.render.render(write_still=True)
        print(f'[hugo] {name}: render {time.time() - t:.1f}s', flush=True)
        big = load_png(raw)
        for size in big_sizes:
            suffix = '' if size in (512, 768) else f'-{size}'
            save_png(downscale(big, size), os.path.join(dest, f'hugo-{name}{suffix}.png'))
        loc, scale = rig['ind_root'].location.copy(), rig['ind_root'].scale.copy()
        rig['ind_root'].location, rig['ind_root'].scale = S['icon_indicator'][0], (S['icon_indicator'][1],) * 3
        trail = bpy.data.objects['ind_thinking_trail']
        trail_hidden = trail.hide_render
        trail.hide_render = True
        aim_camera(cam, yaw_deg=-8.0, **ICON_CAM.get(name, dict(height=2.75, center=(0.0, 0.08))))
        res, spp = sc.render.resolution_x, sc.cycles.samples
        sc.render.resolution_x = sc.render.resolution_y = 768
        sc.cycles.samples = min(spp, 128)
        bpy.ops.render.render(write_still=True)
        sc.render.resolution_x = sc.render.resolution_y = res
        sc.cycles.samples = spp
        trail.hide_render = trail_hidden
        big = load_png(raw)
        for size in icon_sizes:
            icons[(name, size)] = downscale(big, size)
            save_png(icons[(name, size)], os.path.join(dest, f'hugo-{name}-{size}.png'))
        rig['ind_root'].location, rig['ind_root'].scale = loc, scale
        os.remove(raw)

    for name in a['expr']:
        shoot(name, out, sizes[:2], sizes[2:])
    if not a['quick'] and len(a['expr']) == len(EXPR):
        save_png(strip(icons, a['expr'], sizes[2:]), os.path.join(out, 'hugo-strip.png'))
    if a['review']:
        rev = os.path.join(out, 'review')
        os.makedirs(rev, exist_ok=True)
        set_expression(rig, 'neutral')
        for yaw in (-40, 40, 90, 180):
            aim_camera(cam, yaw_deg=yaw)
            raw = os.path.join(rev, '_raw.png')
            sc.render.filepath = raw
            bpy.ops.render.render(write_still=True)
            save_png(downscale(load_png(raw), 256 if a['quick'] else 512),
                     os.path.join(rev, f'hugo-angle-{yaw}.png'))
            os.remove(raw)
        for name in REVIEW_EXPR:
            shoot(name, rev, sizes[:2], sizes[2:-1])


main()
