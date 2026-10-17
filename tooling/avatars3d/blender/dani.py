"""Dani (assets 3D) en Blender/Cycles: cara larga, ojos almendrados, gorro magenta de lana, camisa azul pizarra
y un cubo 3D que sostiene. Hombre joven, sereno y meticuloso; done = pulgar arriba.

Uso (desde la raiz del repo):
  blender -b --factory-startup -P tooling/avatars3d/blender/dani.py -- [--out DIR] [--expr a,b] [--quick]
       [--review] [--samples N] [--closeup] [--view yaw:cx:cz:alto[;...]]
Mismas salidas que nicole.py (dani-<expr>.png 512, -128, -64, -48, -32, tira y review/). Render, luz, camara,
cara, manos, rig y salida son comunes (studio.py); aqui van la spec, el pelo, la ropa y el cubo.
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
import studio  # noqa: E402

L = C.lin
S = dict(
    # cabeza: larga (alta y algo estrecha), barbilla definida, nariz de boton
    head_w=0.92, head_front=0.9, head_back=0.97, head_top=1.08, head_bot=1.0, jaw_taper=0.34,
    head_bumps=[
        ((0.55, -0.75, -0.22), 0.05, 0.3, True),     # mejillas
        ((0.36, -0.92, -0.08), -0.05, 0.2, True),     # cuencas
        ((0.0, -1.0, -0.33), 0.07, 0.085, False),     # nariz
        ((0.0, -1.0, -0.42), 0.025, 0.06, False),     # punta redonda (boton)
        ((0.0, -1.0, -0.22), 0.012, 0.05, False),     # dorso
        ((0.08, -1.0, -0.44), 0.018, 0.045, True),    # aletas
        ((0.045, -1.0, -0.475), -0.014, 0.022, True),  # orificios
        ((0.0, -1.0, -0.5), -0.008, 0.04, False),     # surco bajo la nariz
        ((0.0, -0.85, -0.85), 0.04, 0.22, False),     # barbilla
        ((0.3, -0.9, 0.2), 0.028, 0.2, True),         # arco de la ceja
    ],
    skin=L('#a5663f'), blush=L('#8f4a32'), nose_tip=L('#9a5538'), blush_r=0.24, blush_a=0.35, nose_a=0.6,
    nail=L('#c08a62'),
    # ojos: almendrados (ligeramente inclinados hacia arriba fuera), iris cafe oscuro
    eye_x=0.36, eye_z=-0.12, eye_r=0.24, eye_depth=0.78, eye_yaw=9.0, eye_tilt=7.0,
    iris_ang=0.7, pupil=0.4,
    sclera=L('#f7efe6'), sclera_edge=L('#d9c2ae'), iris_in=L('#7a4a28'), iris_mid=L('#4a2c14'),
    iris_out=L('#2a1608'), iris_ring=L('#140a04'), iris_glow=L('#c98a4a'),
    catchlights=[(-0.36, 0.42, 0.05), (0.3, -0.22, 0.024)],
    lash_w=0.026, lash_flicks=[],
    lash=L('#1a100c'), lid_thick=0.017, crease_gap=13, crease_w=0.013, lid_fillet=0.09,
    # cejas gruesas y suaves (forma v3), casi negras para contrastar con la piel
    brow_pts=[(0.09, 0.19), (0.34, 0.28), (0.62, 0.225)], brow_w=0.064, brow=L('#241510'),
    brow_light=L('#3e2618'), brow_dark=L('#120a06'), brow_hair=0.0032, brow_hair_len=0.015,
    lip_up_h=0.026, lip_lo_h=0.038, lip_up_lift=0.016, lip_lo_lift=0.024,
    mouth_center=(0.0, -0.56), lip=L('#8f4e42'), lipline=L('#4a2018'), cavity=L('#3a1410'),
    teeth=L('#f6efe2'), tongue=L('#c05a60'),
    # pelo: negro rizado y abundante; volumen trasero que cubre la coronilla bajo el gorro, flequillo, patillas
    # hasta la oreja y nuca. Raiz oscura y puntas mas calidas (hair_ramp)
    hair_axis_y=0.12, hair_base=L('#1c120e'), hair_dark=L('#0e0806'), hair_spec=L('#e0b48c'),
    hair_ramp=[(0.0, (0.5, 0.48, 0.48, 1)), (0.35, (0.8, 0.74, 0.7, 1)), (0.75, (1.0, 0.84, 0.66, 1)),
               (1.0, (1.18, 0.9, 0.62, 1))],
    shell_bottom=-1.3, shell_top=0.16, hair_strands=0,
    # gorro de lana magenta (mismo corte que Nicole, algo mas ceñido)
    cut_z0=0.36, cut_k=-0.34, beanie_off=0.06, slouch=0.16, slouch_dir=(0.25, 0.55, 0.8),
    beanie_ribs=60, beanie_rib_depth=0.026, cuff_out=0.04, cuff_h=0.12, cuff_t=0.065, cuff_ribs=96,
    cuff_rib_depth=0.022, beanie=L('#8c1548'), fuzz=2400,
    # cuerpo: jersey azul pizarra con botones y cuello corto acanalado (forma en BODY); cuello corto y recio
    neck_y=0.12, neck_r=0.37, neck_z=(-1.5, -0.55), collar_rib=0.012, collar_ribs=70,
    knit_col=0.05, knit_row=0.032, knit_depth=0.013, cable_u=(), cable_half=0.0, cable_amp=0.0, cable_rope=0.1,
    cable_period=0.5, cable_depth=0.02, shirt=L('#1e293b'), button=L('#334155'),
    # indicadores (mismo sitio y escala que Nicole) en el color del agente
    accent=L('#b0286a'),
    indicator_root=(1.1, -1.2, 0.74), indicator_scale=1.15,
    icon_indicator=((0.6, -1.05, 0.8), 0.85), indicator_at=(0.0, 0.0, 0.0),
    sparkles=[(0.0, 0.0, 0.3), (-0.36, 0.26, 0.15), (0.3, -0.36, 0.14)],
    sweat_at=(-0.86, -0.62, 0.12),
    hand_scale=1.4, done_pose='thumbs', fuzz_fuzz=0,
)

# misma gramatica que Nicole/Alfred: sereno, cejas gruesas marcadas al pensar y al error
EXPR = {
    'neutral': dict(lid_up=40, lid_lo=-44, gaze=(0, -2), tilt=0, pupil=0.4,
                    brow={1: (0, 0, 0), -1: (0, 0, 0)},
                    mouth=dict(w=0.17, cl=0.028, cr=0.028, up=0.0, open=0.0)),
    'thinking': dict(lid_up=32, lid_lo=-34, gaze=(16, -18), tilt=0, pupil=0.38,
                     brow={1: (0.07, 0.12, 0.08), -1: (-0.04, -0.035, 0.0)},
                     mouth=dict(w=0.15, cl=-0.004, cr=0.016, up=0.0, open=0.0, shift=0.04),
                     indicator='thinking'),
    'working': dict(lid_up=14, lid_lo=-26, gaze=(-20, 2), tilt=10, pupil=0.4,
                    brow={1: (-0.1, -0.03, 0.04), -1: (-0.1, -0.03, 0.04)},
                    mouth=dict(w=0.15, cl=0.0, cr=0.004, up=0.0, open=0.0),
                    indicator='working'),
    'happy': dict(lid_up=16, lid_lo=16, gaze=(0, 0), tilt=0, pupil=0.4,
                  brow={1: (0.05, 0.07, 0.03), -1: (0.05, 0.07, 0.03)},
                  mouth=dict(w=0.22, cl=0.075, cr=0.075, up=-0.01, open=0.17, teeth=True, teeth_h=0.05,
                             tongue=True),
                  indicator='happy'),
    'error': dict(lid_up=47, lid_lo=-52, gaze=(0, 0), tilt=-6, pupil=0.26, iris=0.78,
                  brow={1: (0.11, 0.035, -0.035), -1: (0.11, 0.035, -0.035)},
                  mouth=dict(w=0.16, cl=-0.03, cr=-0.03, up=0.004, open=0.0),
                  indicator='error'),
    'done': dict(lid_up=28, lid_lo=-30, gaze=(0, 0), tilt=0, pupil=0.42,
                 brow={1: (0.04, 0.05, 0.02), -1: (0.04, 0.05, 0.02)},
                 mouth=dict(w=0.21, cl=0.07, cr=0.07, up=-0.01, open=0.1, teeth=True, teeth_h=0.045),
                 indicator='done', hands=S['done_pose']),
}

# done = pulgar arriba junto a la cara (README, personaje masculino); el resto de estados en reposo, sin objetos.
# .R = mano derecha del personaje (izquierda de la imagen); manga de camisa (punio liso, rib=0)
REST = studio.REST
HAND_POSES = {
    # pulgar arriba junto a la mejilla, dentro del encuadre del icono (se lee en 48/32 px)
    'thumbs': dict(R=dict(wrist=(-0.98, -1.0, -0.5), F=(0.1, -0.3, 0.95), N=(-1.0, 0.0, 0.0), side=-1,
                          curl=dict(index=(88, 96, 70), middle=(90, 98, 70), ring=(90, 98, 70), pinky=(88, 96, 70)),
                          thumb=dict(dir=(0.0, 0.0, 1.0), up=(-0.6, -0.8, 0.0), curl=(0, 0)),
                          arm=[(-1.85, -0.75, -3.0), (-1.6, -0.85, -1.95)], rib=0.0),
                   L=REST),
    # pulgar arriba delante del pecho (solo review: done_alt)
    'thumbs_chest': dict(R=dict(wrist=(-0.95, -1.35, -1.85), F=(1.0, -0.2, 0.05), N=(0.0, -1.0, 0.15), side=1,
                                curl=dict(index=(88, 96, 70), middle=(90, 98, 70), ring=(90, 98, 70),
                                          pinky=(88, 96, 70)),
                                thumb=dict(dir=(0.1, -0.05, 1.0), up=(0.0, -1.0, 0.0), curl=(0, 0)),
                                arm=[(-1.5, -1.0, -3.1), (-1.3, -1.25, -2.3)], rib=0.0),
                         L=REST),
}
REVIEW_EXPR = {'done_alt': dict(EXPR['done'], shape='done', hands='thumbs_chest')}
ICON_CAM = {'thumbs': dict(height=2.9, center=(-0.14, 0.02)), 'thumbs_chest': dict(height=3.6, center=(0.0, -0.4))}


# ---------------------------------------------------------------- pelo: Hair Curves nativo de Blender
# Guias generadas sobre el cuero cabelludo (bajo el gorro y hasta la nuca), hijos con Geometry Nodes (Interpolate
# Curves, clump propio hacia su guia y los grupos de Blender Frizz + Set Hair Curve Profile) y Principled Hair BSDF;
# el rizo es una helice en cada guia, asi cada mechon forma un tirabuzon.
HAIR = dict(
    guides=900, guide_pts=96, children=46,       # hijos por guia (densidad = guias * hijos / area del cuero)
    # linea del pelo (azimut en grados -> z): frente bajo la vuelta, patilla delante de la oreja, encima de la oreja,
    # detras de la oreja y nuca; 'cut' = relativo al borde del gorro
    hairline=[(0, ('cut', -0.12)), (44, ('cut', -0.12)), (60, -0.3), (74, -0.24), (84, 0.06), (106, 0.08),
              (124, -0.42), (180, -0.6)],
    bang_deg=50, bang_tip=(0.3, 0.42),             # flequillo: azimut maximo y altura de las puntas (sobre las cejas)
    tip_z=(-1.16, -0.9),                         # resto: puntas a la altura del cuello
    lift=(0.025, 0.14), flare=0.07, inner=0.022,  # separacion de la cabeza (capas) y dentro del gorro
    clump=0.85, clump_shape=1.0, frizz=0.0008, radius=0.0045,
    # rizo en las guias (helice): radio y paso de vuelta; el flequillo, mas pequeno y cerrado
    curl_r=(0.036, 0.048), curl_period=(0.24, 0.3), bang_curl_r=0.02, bang_curl_period=0.16,
    seed=7,
)


def hair_scalp(S, head, cut_z):
    """Malla del cuero cabelludo (caras de la cabeza en la zona de pelo, algo hacia fuera): emisor de las guias y
    los hijos y capa oscura bajo el pelo, asi nunca se ve piel entre hebras."""
    y_ax = S['hair_axis_y']
    hl = HAIR['hairline']
    degs = np.array([d for d, _ in hl], float)

    def hairline(phi):
        a = abs(math.degrees(phi))
        zs = [cut_z(phi) + v[1] if isinstance(v, tuple) else v for _, v in hl]
        return float(np.interp(a, degs, zs))

    c = head.v[head.f].mean(1)
    phi = np.arctan2(c[:, 0], -(c[:, 1] - y_ax))
    keep = np.array([z > hairline(p) and z < cut_z(p) + 0.3 for p, z in zip(phi, c[:, 2])])
    f = head.f[keep]
    used = np.unique(f)
    remap = -np.ones(len(head.v), np.int64)
    remap[used] = np.arange(len(used))
    v = head.v[used]
    n = np.zeros_like(head.v)
    tri = head.v[head.f]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    for k in range(head.f.shape[1]):
        np.add.at(n, head.f[:, k], fn)
    n = C.unit(n[used])
    if np.mean(np.sum(n * (v - [0, y_ax, 0]), 1)) < 0:
        n = -n
    return C.Part(v + n * 0.004, remap[f]), hairline


def sample_faces(part, count, rng):
    """Puntos uniformes por area sobre una malla de quads/triangulos (cada quad = dos triangulos)."""
    f = part.f
    tris = [f[:, [0, 1, 2]]] + ([f[:, [0, 2, 3]]] if f.shape[1] == 4 else [])
    T = part.v[np.concatenate(tris)]
    area = 0.5 * np.linalg.norm(np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]), axis=1)
    idx = rng.choice(len(T), count, p=area / area.sum())
    u, w = rng.random(count), rng.random(count)
    flip = u + w > 1
    u[flip], w[flip] = 1 - u[flip], 1 - w[flip]
    t = T[idx]
    return t[:, 0] + (t[:, 1] - t[:, 0]) * u[:, None] + (t[:, 2] - t[:, 0]) * w[:, None], float(area.sum())


def hair_guides(S, roots, head_surf, collide, cut_z, hairline, rng):
    """Una guia por raiz: baja por la cabeza pegada (dentro del gorro), sale por debajo de la vuelta, gana volumen
    por capas (las raices mas altas van por fuera) y cae hasta el cuello con ondas amplias; el flequillo cae corto
    sobre la frente. El rizo, los mechones y el encrespado los ponen los nodos sobre los hijos."""
    y_ax = S['hair_axis_y']
    n = HAIR['guide_pts']
    t = np.linspace(0.0, 1.0, n)
    rmemo = {}

    def head_r(phi, z):
        key = (round(phi, 2), round(z, 2))
        if key not in rmemo:
            d = (math.sin(phi), -math.cos(phi))
            loc, _ = head_surf.ray((d[0] * 4, y_ax + d[1] * 4, z), (-d[0], -d[1], 0.0))
            rmemo[key] = math.hypot(loc[0], loc[1] - y_ax) if loc is not None else 0.0
        return rmemo[key]

    out = []
    for p in roots:
        phi0 = math.atan2(p[0], -(p[1] - y_ax))
        z0 = float(p[2])
        a = abs(math.degrees(phi0))
        side = 1.0 if phi0 >= 0 else -1.0
        cut = cut_z(phi0)
        hl = hairline(phi0)
        # capa: 0 en la linea del pelo, 1 en lo alto (dentro del gorro)
        layer = float(np.clip((z0 - hl) / max(cut + 0.3 - hl, 1e-3), 0, 1))
        bang = 1.0 - C.ss(HAIR['bang_deg'] - 8, HAIR['bang_deg'] + 8, a)
        tip = (bang * rng.uniform(*HAIR['bang_tip']) + (1 - bang) * rng.uniform(*HAIR['tip_z']))
        # los laterales y la nuca algo mas cortos hacia delante: contorno en U suave
        tip += (1 - bang) * 0.12 * (1 - C.ss(60, 150, a))
        z = z0 + (tip - z0) * t
        sweep = bang * side * rng.uniform(0.08, 0.2) * t ** 1.2 + (1 - bang) * side * 0.04 * C.ss(0.3, 1, t)
        wave_ph = 2.2 * phi0 + 0.6 * rng.standard_normal() * 0.3
        phi = phi0 + sweep + (1 - bang) * 0.035 * np.sin(math.tau * 1.6 * t + wave_ph) * t
        below = (cut - 0.075) - z                     # > 0 por debajo de la vuelta del gorro
        lift = (HAIR['lift'][0] + (HAIR['lift'][1] - HAIR['lift'][0]) * layer ** 0.8) * (1 - 0.65 * bang)
        off = (HAIR['inner'] * (0.6 + 0.4 * layer)
               + lift * C.ss(0.0, 0.22, below)
               + (1 - bang) * HAIR['flare'] * C.ss(0.0, 1.2, below) ** 1.4
               + (1 - bang) * 0.03 * np.sin(math.tau * 1.6 * t + wave_ph + 1.3) * C.ss(0.0, 0.3, below))
        r = np.empty(n)
        run = 0.0
        for i in range(n):
            rh = head_r(phi[i], max(z[i], -0.62))
            run = max(run, rh) if z[i] < 0.1 else rh   # bajo la oreja el pelo cuelga, no se mete hacia el cuello
            r[i] = run + off[i]
        P = np.stack([r * np.sin(phi), y_ax - r * np.cos(phi), z], -1)
        P[0] = p
        free = below > 0.0
        for _ in range(2):
            Q = collide.push_out(P.copy(), 0.016)
            P[free] = Q[free]
            P[1:-1] = 0.5 * P[1:-1] + 0.25 * (P[:-2] + P[2:])
            P[0] = p
        # rizo: helice alrededor del camino (empieza al salir del gorro); vecinos con fase propia, asi cada guia es
        # un tirabuzon y sus hijos lo siguen
        T = C.unit(np.gradient(P, axis=0))
        ctr = np.stack([np.zeros(n), np.full(n, y_ax), np.minimum(P[:, 2], 0.2)], -1)
        Nr = P - ctr
        Nr = C.unit(Nr - T * np.sum(Nr * T, 1)[:, None])
        B = np.cross(T, Nr)
        arc = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
        period = bang * HAIR['bang_curl_period'] + (1 - bang) * rng.uniform(*HAIR['curl_period'])
        rad = (bang * HAIR['bang_curl_r'] + (1 - bang) * rng.uniform(*HAIR['curl_r'])) * C.ss(0.0, 0.14, below)
        rad = rad * (0.55 + 0.45 * t)
        th = math.tau * arc / period + rng.uniform(0, math.tau)
        P = P + rad[:, None] * (np.cos(th)[:, None] * Nr + np.sin(th)[:, None] * B)
        Q = collide.push_out(P.copy(), 0.012)
        P[free] = Q[free]
        P[0] = p
        out.append(P)
    return np.array(out)


def mat_hair_curves(S):
    """Principled Hair BSDF (Chiang, melanina): raiz casi negra, puntas algo mas claras y calidas, brillo suave."""
    nb = C.NB('hair_strands')
    info = nb.node('ShaderNodeHairInfo')
    hb = nb.node('ShaderNodeBsdfHairPrincipled', parametrization='MELANIN', model='CHIANG')
    x = info.outputs['Intercept']
    nb.put(hb.inputs['Melanin'], nb.maprange(x, 0.0, 1.0, 0.995, 0.93, 'LINEAR'))
    nb.put(hb.inputs['Melanin Redness'], nb.maprange(x, 0.3, 1.0, 0.15, 0.45, 'SMOOTHSTEP'))
    hb.inputs['Tint'].default_value = (1.0, 0.92, 0.84, 1.0)
    hb.inputs['Roughness'].default_value = 0.38
    hb.inputs['Radial Roughness'].default_value = 0.45
    hb.inputs['Coat'].default_value = 0.12
    hb.inputs['Random Color'].default_value = 0.06
    hb.inputs['Random Roughness'].default_value = 0.15
    nb.put(hb.inputs['Random'], info.outputs['Random'])
    out = [n for n in nb.mat.node_tree.nodes if n.type == 'OUTPUT_MATERIAL'][0]
    nb.mat.node_tree.links.new(hb.outputs[0], out.inputs['Surface'])
    return nb.mat


def mat_scalp(S):
    nb = C.NB('hair_scalp')
    nb.principled(Base_Color=S['hair_dark'], Roughness=0.8, Specular_IOR_Level=0.1)
    return nb.mat


HAIR_ASSETS = ('Frizz Hair Curves', 'Set Hair Curve Profile')


def load_hair_assets():
    path = bpy.utils.system_resource('DATAFILES', path='assets/nodes/procedural_hair_node_assets.blend')
    if not path or not os.path.exists(path):
        path = os.path.join(os.path.dirname(bpy.app.binary_path), f'{bpy.app.version[0]}.{bpy.app.version[1]}',
                            'datafiles', 'assets', 'nodes', 'procedural_hair_node_assets.blend')
    with bpy.data.libraries.load(path, link=False) as (src, dst):
        dst.node_groups = [g for g in HAIR_ASSETS if g in src.node_groups]
    return {g.name: g for g in dst.node_groups}


def build_hair_curves(guides, scalp_ob, area, mat, root, quick=False):
    """Objeto Hair Curves con las guias y modificador de nodos: hijos interpolados sobre el cuero cabelludo,
    agrupados hacia su guia (que ya lleva el rizo), algo encrespados (frizz) y con grosor que se afina hacia la punta."""
    nc, npt = guides.shape[:2]
    cv = bpy.data.hair_curves.new('hair_curves')
    cv.add_curves([npt] * nc)
    cv.position_data.foreach_set('vector', guides.astype(np.float32).ravel())
    ob = bpy.data.objects.new('hair_curves', cv)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = root
    groups = load_hair_assets()
    ng = bpy.data.node_groups.new('dani_hair', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N, Lk = ng.nodes, ng.links
    gin, gout = N.new('NodeGroupInput'), N.new('NodeGroupOutput')
    info = N.new('GeometryNodeObjectInfo')
    info.transform_space = 'RELATIVE'
    info.inputs['Object'].default_value = scalp_ob
    dist = N.new('GeometryNodeDistributePointsOnFaces')
    dist.distribute_method = 'RANDOM'
    count = nc * HAIR['children'] * (0.5 if quick else 1.0)
    dist.inputs['Density'].default_value = count / area
    dist.inputs['Seed'].default_value = HAIR['seed']
    Lk.new(info.outputs['Geometry'], dist.inputs['Mesh'])
    interp = N.new('GeometryNodeInterpolateCurves')
    interp.inputs['Max Neighbors'].default_value = 1
    Lk.new(gin.outputs[0], interp.inputs['Guide Curves'])
    Lk.new(dist.outputs['Points'], interp.inputs['Points'])
    cur = interp.outputs['Curves']

    def group(name, **vals):
        nonlocal cur
        g = N.new('GeometryNodeGroup')
        g.node_tree = groups[name]
        for k, v in vals.items():
            g.inputs[k].default_value = v
        Lk.new(cur, g.inputs['Geometry'])
        cur = g.outputs['Geometry']

    # clump: cada hijo se acerca a su guia (la mas cercana) hacia la punta -> tirabuzones con cuerpo
    spar = N.new('GeometryNodeSplineParameter')
    samp = N.new('GeometryNodeSampleCurve')
    samp.use_all_curves = False
    Lk.new(gin.outputs[0], samp.inputs['Curves'])
    Lk.new(spar.outputs['Factor'], samp.inputs['Factor'])
    Lk.new(interp.outputs['Closest Index'], samp.inputs['Curve Index'])
    pos = N.new('GeometryNodeInputPosition')

    def math_(op, a, b, vec=False):
        m = N.new('ShaderNodeVectorMath' if vec else 'ShaderNodeMath')
        m.operation = op
        for i, x in enumerate((a, b)):
            if isinstance(x, bpy.types.NodeSocket):
                Lk.new(x, m.inputs[i if not (vec and op == 'SCALE' and i == 1) else 3])
            elif not vec:
                m.inputs[i].default_value = x
        return m.outputs[0] if not vec else m.outputs['Vector']

    k = math_('SUBTRACT', 1.0, math_('MULTIPLY', math_('POWER', spar.outputs['Factor'], HAIR['clump_shape']),
                                     HAIR['clump']))
    off = math_('SCALE', math_('SUBTRACT', pos.outputs['Position'], samp.outputs['Position'], True), k, True)
    setp = N.new('GeometryNodeSetPosition')
    Lk.new(cur, setp.inputs['Geometry'])
    Lk.new(math_('ADD', samp.outputs['Position'], off, True), setp.inputs['Position'])
    cur = setp.outputs['Geometry']
    group('Frizz Hair Curves', Factor=1.0, Distance=HAIR['frizz'], Shape=0.6)
    group('Set Hair Curve Profile', Radius=HAIR['radius'], Shape=0.35)
    sm = N.new('GeometryNodeSetMaterial')
    sm.inputs['Material'].default_value = mat
    Lk.new(cur, sm.inputs['Geometry'])
    Lk.new(sm.outputs['Geometry'], gout.inputs[0])
    mod = ob.modifiers.new('hair', 'NODES')
    mod.node_group = ng
    return ob


# ---------------------------------------------------------------- camisa y cubo
def mat_shirt(name, color):
    """Camisa: algodon mate con tejido fino y pelusilla tenue."""
    nb = C.NB(name)
    co = nb.texco().outputs['Object']
    weave = nb.noise(co, 280.0, 2.0, 0.5)
    var = nb.noise(co, 5.0, 2.0)
    c = nb.mix(nb.math('MULTIPLY', var, 0.12), color, (color[0] * 1.25, color[1] * 1.25, color[2] * 1.28, 1))
    nb.principled(Base_Color=c, Roughness=0.72, Specular_IOR_Level=0.28, Sheen_Weight=0.3, Sheen_Roughness=0.5,
                  Sheen_Tint=(0.75, 0.8, 0.95, 1), Normal=nb.bump(weave, 0.1, 0.003))
    return nb.mat


def dani_mats(S):
    return dict(
        beanie=C.mat_wool('beanie', S['beanie'], 110.0),
        beanie_fuzz=C.mat_wool('beanie_fuzz', S['beanie'], 140.0),
        shirt=mat_shirt('shirt', S['shirt']),
        button=C.mat_flat('button', S['button'], rough=0.35, coat=0.35),
    )


def build_shirt_buttons(surf):
    """Botones y tapeta sobre la linea central delantera del jersey (rayos contra la malla final)."""
    out = []
    for zb in (-1.55, -1.85, -2.15, -2.45):
        p0, n0 = surf.front(0.0, zb)
        if p0 is None:
            continue
        bt = C.sphere_part(1.0, 20, 10)
        bt.v = bt.v * 0.032
        bt.v[:, 1] *= 0.4
        bt.v = bt.v + p0 + n0 * 0.022
        out.append(bt)
    # tapeta: costura central en tubo fino
    hits = [surf.front(0.0, zc) for zc in np.linspace(-1.45, -2.8, 40)]
    E = np.array([p + n * 0.008 for p, n in hits if p is not None] or [[0, 0, -2.0], [0, 0, -2.1]])
    E = C.smooth_path(E, 2, keep_root=False)
    ctr = np.stack([np.zeros(len(E)), np.full(len(E), 0.15), E[:, 2]], -1)
    out.append(C.sweep(E, C.unit(E - ctr), np.full(len(E), 0.012), np.full(len(E), 0.01), 8))
    return C.Part.join(out)


# ---------------------------------------------------------------- cuerpo: torso, hombros y brazos de una pieza
# Volumenes simples (torso por secciones, cuello vuelto, deltoides y cada brazo como un tubo que nace del hombro)
# unidos con remesh de voxeles; un suavizado que solo rellena lo concavo redondea axilas y union brazo-hombro, y
# encima se graba el punto: canale vertical en el cuerpo y a lo largo de la manga, costura de hombro, pliegues en
# el codo y frunce sobre el punio. Una variante por pose del brazo derecho (reposo, pulgar, sostener el cubo).
BODY = dict(
    # torso: (z, semiancho, semifondo, centro y, exponente de la superelipse); hombros caidos (trapecio) y V suave
    sections=[(-1.04, 0.42, 0.38, 0.13, 2.2), (-1.16, 0.52, 0.43, 0.14, 2.3), (-1.3, 0.6, 0.48, 0.15, 2.4),
              (-1.46, 0.76, 0.56, 0.17, 2.5), (-1.62, 0.86, 0.62, 0.18, 2.55), (-1.8, 0.9, 0.65, 0.19, 2.6), (-1.95, 0.9, 0.68, 0.19, 2.7),
              (-2.3, 0.86, 0.7, 0.17, 2.7), (-2.75, 0.8, 0.66, 0.19, 2.7), (-3.25, 0.74, 0.61, 0.21, 2.7),
              (-4.0, 0.76, 0.6, 0.21, 2.7)],
    collar=(0.385, 0.49, -1.36, -0.99),        # cuello vuelto: radio interior, exterior, z de abajo y de arriba
    shoulder=(0.88, 0.2, -1.68),               # articulacion del hombro izquierdo (+X); el derecho es simetrico
    deltoid=(0.22, 0.26, 0.24),                # semiejes del deltoides (lateral, fondo, a lo largo del brazo)
    upper=1.05, fore=1.0,                      # largo de brazo y de antebrazo
    elbow_rest=(1.15, 0.27, -2.7), wrist_rest=(1.22, 0.12, -3.62),
    arm_r=(0.245, 0.222, 0.208, 0.214, 0.182),  # radio de la manga: hombro, medio brazo, codo, antebrazo, muneca
    seam=0.3,                                  # costura de la manga (arco desde el hombro)
    cuff_len=0.26, cuff_r=0.2,
    voxel=0.014,
)
ARM_POLE = {'thumbs': (-0.8, 0.1, -1.0), 'thumbs_chest': (-0.6, 0.6, -1.0)}   # hacia donde sale el codo


def smooth1d(x, it):
    x = np.asarray(x, float).copy()
    for _ in range(it):
        x[1:-1] = 0.5 * x[1:-1] + 0.25 * (x[:-2] + x[2:])
    return x


def capped_rings(R):
    """Malla cerrada de anillos R (n, na par, 3) con tapas en abanico de quads (dos sectores por quad)."""
    n, na = R.shape[:2]
    f, _, _ = C.grid_faces(n, na, closed_v=True)
    c0, c1 = n * na, n * na + 1
    j = np.arange(0, na, 2)
    j1, j2 = (j + 1) % na, (j + 2) % na
    cap0 = np.stack([np.full(len(j), c0), j2, j1, j], 1)
    cap1 = np.stack([np.full(len(j), c1), (n - 1) * na + j, (n - 1) * na + j1, (n - 1) * na + j2], 1)
    V = np.concatenate([R.reshape(-1, 3), R[0].mean(0)[None], R[-1].mean(0)[None]])
    Fq = np.concatenate([f, cap0, cap1])
    # normales hacia fuera (volumen con signo positivo); el remesh descarta los volumenes del reves
    a, b, c, d = (V[Fq[:, k]] for k in range(4))
    vol = np.sum(a * np.cross(b, c)) + np.sum(a * np.cross(c, d))
    return C.Part(V, Fq if vol > 0 else Fq[:, ::-1])


def torso_volume(B):
    sec = np.array(B['sections'])
    nz, nu = 110, 180
    zs = np.linspace(sec[0, 0], sec[-1, 0], nz)
    a, b, yc, n = (smooth1d(np.interp(-zs, -sec[:, 0], sec[:, k]), 8) for k in range(1, 5))
    th = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    sx, cy = np.sin(th)[None], -np.cos(th)[None]
    rs = (np.abs(sx) ** n[:, None] + np.abs(cy) ** n[:, None]) ** (-1 / n[:, None])
    front = np.clip(-cy, 0, 1) ** 2
    X = a[:, None] * rs * sx
    Y = yc[:, None] + b[:, None] * rs * cy - 0.035 * front * np.exp(-((zs + 2.15) / 0.45) ** 2)[:, None]
    Z = np.broadcast_to(zs[:, None], X.shape)
    return capped_rings(np.stack([X, Y, Z], -1))


def collar_volume(S, B):
    """Cuello vuelto como anillo grueso (hueco para el cuello), con el borde de arriba redondeado."""
    ri, ro, z0, z1 = B['collar']
    k = 0.04
    a = np.linspace(0, np.pi / 2, 8)
    prof = np.concatenate([
        np.stack([np.linspace(ri, ro, 6), np.full(6, z0)], -1)[:-1],
        np.stack([np.full(10, ro), np.linspace(z0, z1 - k, 10)], -1)[:-1],
        np.stack([ro - k + k * np.cos(a), z1 - k + k * np.sin(a)], -1)[:-1],
        np.stack([ri + k - k * np.cos(a[::-1]), z1 - k + k * np.sin(a[::-1])], -1)[1:-1],
        np.stack([np.full(10, ri), np.linspace(z1 - k, z0, 10)], -1)[:-1]])
    nu = 120
    th = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    P = np.stack([prof[:, None, 0] * np.sin(th)[None], S['neck_y'] - prof[:, None, 0] * np.cos(th)[None],
                  np.broadcast_to(prof[:, None, 1], (len(prof), nu))], -1)
    f, _, _ = C.grid_faces(len(prof), nu, closed_u=True, closed_v=True)
    return C.Part(P.reshape(-1, 3), f)


def solve_elbow(J, W, L1, L2, pole):
    """IK de dos huesos: codo entre hombro J y muneca W, hacia el lado de pole."""
    d = W - J
    dist = np.linalg.norm(d)
    u = d / dist
    dist = min(dist, (L1 + L2) * 0.999)
    a = (L1 ** 2 - L2 ** 2 + dist ** 2) / (2 * dist)
    h = math.sqrt(max(L1 ** 2 - a ** 2, 0.0))
    p = np.asarray(pole, float)
    p = C.unit(p - u * np.dot(p, u))
    return J + u * a + p * h


def arm_path(J, E, W_end, F):
    """Eje del brazo: hombro -> codo -> muneca, llegando a la muneca en la direccion de la mano."""
    ctrl = [J, E, W_end - F * 0.32, W_end]
    pts = []
    for i in range(len(ctrl) - 1):
        k = max(int(np.linalg.norm(ctrl[i + 1] - ctrl[i]) / 0.02), 2)
        for t in np.linspace(0, 1, k, endpoint=False):
            pts.append(ctrl[i] * (1 - t) + ctrl[i + 1] * t)
    pts.append(W_end)
    P = C.smooth_path(np.array(pts), 30)
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    # marco transportado (sin giros) para medir el angulo alrededor de la manga
    T = C.unit(np.gradient(P, axis=0))
    Wf = np.zeros_like(P)
    w = C.unit(np.cross(T[0], [0.0, -1.0, 0.0]) if abs(T[0][1]) < 0.9 else np.cross(T[0], [1.0, 0, 0]))
    for i in range(len(P)):
        w = C.unit(w - T[i] * np.dot(w, T[i]))
        Wf[i] = w
    Hf = np.cross(T, Wf)
    el = arc[int(np.argmin(np.linalg.norm(P - E, axis=1)))]
    return dict(P=P, arc=arc, T=T, W=Wf, H=Hf, elbow=el, J=J, E=E, end=W_end, F=F)


def arm_radius(B, A, arc):
    r = B['arm_r']
    el, L = A['elbow'], A['arc'][-1]
    return np.interp(arc, [0.0, 0.45 * el, el, el + 0.3 * (L - el), L], r)


def arm_volume(B, A):
    """Tubo del brazo hasta poco despues del arranque del punio (el punio va aparte, abierto)."""
    stop = A['arc'][-1] - B['cuff_len'] + 0.03
    m = A['arc'] <= stop
    P, arc, Wf, Hf = A['P'][m], A['arc'][m], A['W'][m], A['H'][m]
    r = arm_radius(B, A, arc)
    # arranque en cupula (no tapa plana): el hombro sale redondeado, sin canto de tubo
    phi = np.linspace(0.12, np.pi / 2, 12, endpoint=False)
    P = np.concatenate([P[0] - np.outer(np.cos(phi) * r[0] * 0.9, A['T'][0]), P])
    r = np.concatenate([np.sin(phi) * r[0], r])
    Wf, Hf = np.concatenate([np.repeat(Wf[:1], 12, 0), Wf]), np.concatenate([np.repeat(Hf[:1], 12, 0), Hf])
    na = 48
    th = np.linspace(0, C.TAU, na, endpoint=False)
    R = P[:, None] + r[:, None, None] * (np.cos(th)[None, :, None] * Wf[:, None] + np.sin(th)[None, :, None] * Hf[:, None])
    return capped_rings(R)


def deltoid_volume(B, A, side):
    J, E = A['J'], A['E']
    down = C.unit(J - E)
    az = C.unit(0.45 * np.array([0, 0, 1.0]) + 0.55 * down)
    ax = C.unit(np.array([side, 0, 0]) - az * az[0] * side)
    ay = np.cross(az, ax)
    c = J + np.array([-side * 0.03, 0.0, 0.0]) - down * 0.1
    sx, sy, sz = B['deltoid']
    return H.oriented_blob(c, ax, ay, az, (sx, sy, sz), expo=1.0, nu=48, nv=24)


def cuff_part(B, A, rib=0.035):
    """Punio de punto: tubo abierto algo mas ancho que la manga, con borde vuelto."""
    L = A['arc'][-1]
    m = A['arc'] >= L - B['cuff_len']
    P, Wf, Hf, T = A['P'][m], A['W'][m], A['H'][m], A['T'][m]
    t = np.linspace(0, 1, len(P))
    r = B['cuff_r'] * (1.0 - 0.04 * t)
    na = 72
    th = np.linspace(0, C.TAU, na, endpoint=False)
    rr = r[:, None] * (1 + rib * np.cos(36 * th)[None])
    R = P[:, None] + rr[..., None] * (np.cos(th)[None, :, None] * Wf[:, None] + np.sin(th)[None, :, None] * Hf[:, None])
    f, _, _ = C.grid_faces(len(P), na, closed_v=True)
    tube = C.Part(R.reshape(-1, 3), f)
    ring = P[-1] + r[-1] * 1.02 * (np.cos(th)[:, None] * Wf[-1] + np.sin(th)[:, None] * Hf[-1])
    rim = C.sweep(ring, np.tile(T[-1], (na, 1)), np.full(na, 0.028), np.full(na, 0.028), 10, closed=True)
    return C.Part.join([tube, rim])


def quad_normals(V, Fq):
    fn = np.cross(V[Fq[:, 2]] - V[Fq[:, 0]], V[Fq[:, 3]] - V[Fq[:, 1]])
    N = np.zeros_like(V)
    for k in range(4):
        np.add.at(N, Fq[:, k], fn)
    return C.unit(N)


def remesh_union(parts, voxel):
    """Une volumenes cerrados con remesh de voxeles -> (vertices, quads, aristas)."""
    ob = C.make_object('tmp_body', C.Part.join(parts), None, None, smooth=False)
    mod = ob.modifiers.new('remesh', 'REMESH')
    mod.mode, mod.voxel_size, mod.adaptivity = 'VOXEL', voxel, 0.0
    dg = bpy.context.evaluated_depsgraph_get()
    ev = ob.evaluated_get(dg)
    me = ev.to_mesh()
    V = np.empty(len(me.vertices) * 3, np.float32)
    me.vertices.foreach_get('co', V)
    nl = np.empty(len(me.polygons), np.int32)
    me.polygons.foreach_get('loop_total', nl)
    lv = np.empty(len(me.loops), np.int32)
    me.loops.foreach_get('vertex_index', lv)
    Ed = np.empty(len(me.edges) * 2, np.int32)
    me.edges.foreach_get('vertices', Ed)
    assert (nl == 4).all(), 'remesh: se esperaban solo quads'
    ev.to_mesh_clear()
    bpy.data.objects.remove(ob, do_unlink=True)
    return V.reshape(-1, 3).astype(float), lv.reshape(-1, 4), Ed.reshape(-1, 2)


def smooth_body(V, Fq, Ed, keep, taubin=6, fill=90):
    """Taubin (quita el escalonado del voxel sin encoger) y relleno de lo concavo: axilas y union brazo-hombro."""
    i, j = Ed[:, 0], Ed[:, 1]
    deg = np.bincount(np.r_[i, j], minlength=len(V)).astype(float)[:, None]

    def lap(V):
        Sm = np.zeros_like(V)
        for k in range(3):
            Sm[:, k] = np.bincount(i, V[j, k], len(V)) + np.bincount(j, V[i, k], len(V))
        return Sm / np.maximum(deg, 1) - V

    for _ in range(taubin):
        V = V + 0.5 * lap(V)
        V = V - 0.53 * lap(V)
    for _ in range(fill):
        Lp = lap(V)
        c = np.sum(Lp * quad_normals(V, Fq), 1)
        w = (np.clip(c / 0.003, 0, 1) * (1 - keep))[:, None]
        V = V + 0.6 * w * Lp
    return V


def body_knit(S, B, V, N, arms):
    """Relieve del punto + costuras + pliegues, en la direccion de la normal."""
    x, y, z = V[:, 0], V[:, 1], V[:, 2]
    # cuerpo: canale vertical (u alrededor del torso, v hacia abajo)
    u = np.arctan2(x, -(y - 0.17)) * 0.8
    v = -1.0 - z
    h = C.knit_height(u, v, S)
    # cuello vuelto: canale mas marcado alrededor del cuello
    ri, ro, z0, z1 = B['collar']
    rn = np.hypot(x, y - S['neck_y'])
    in_collar = (z > z0 - 0.01) & (rn < ro + 0.05)
    ang_n = np.arctan2(x, -(y - S['neck_y']))
    hc = S['collar_rib'] * 1.6 * ((0.5 + 0.5 * np.cos(S['collar_ribs'] * ang_n)) ** 0.6)
    h = np.where(in_collar, hc, h)
    # torso: pliegues suaves que bajan en diagonal desde la axila (delante y detras)
    ax = np.abs(x)
    g = np.exp(-((ax - 0.78) / 0.16) ** 2) * np.exp(-((z + 2.2) / 0.32) ** 2)
    h = h + 0.012 * g * np.sin(C.TAU * (0.7 * ax - z) / 0.17)
    for A in arms:
        P, arc = A['P'], A['arc']
        best = np.full(len(V), 1e9)
        idx = np.zeros(len(V), int)
        for s0 in range(0, len(V), 20000):
            d = np.linalg.norm(V[s0:s0 + 20000, None] - P[None], axis=-1)
            idx[s0:s0 + 20000] = d.argmin(1)
            best[s0:s0 + 20000] = d.min(1)
        a_ = arc[idx]
        e = best - arm_radius(B, A, a_)
        on = (e < 0.05) & (a_ > 0.04) & (idx < len(P) - 1)
        dv = V - P[idx]
        ang = np.arctan2(np.sum(dv * A['H'][idx], 1), np.sum(dv * A['W'][idx], 1))
        r = arm_radius(B, A, a_)
        ha = C.knit_height(ang * r, a_, S)
        # pliegues: en el codo (sobre todo por dentro, segun cuanto se doble) y frunce sobre el punio
        el, L = A['elbow'], arc[-1]
        bend = (1 + np.dot(C.unit(A['J'] - A['E']), C.unit(A['end'] - A['E']))) / 2   # 0 recto, 1 doblado
        inner = C.unit((A['J'] + A['end']) / 2 - A['E'])
        ie = int(np.argmin(np.abs(arc - el)))
        ang_in = math.atan2(np.dot(inner, A['H'][ie]), np.dot(inner, A['W'][ie]))
        side_w = 0.35 + 0.65 * np.clip(np.cos(ang - ang_in), 0, 1)
        ha = ha + (0.012 + 0.02 * bend) * np.exp(-((a_ - el) / 0.22) ** 2) * side_w \
            * np.sin(C.TAU * (a_ - el) / 0.11 + 0.9 * np.sin(2 * ang))
        ha = ha + 0.014 * C.ss(L - 0.6, L - B['cuff_len'], a_) * np.sin(C.TAU * a_ / 0.08 + 1.3 * np.cos(ang))
        # costura de hombro: surco fino con un pespunte leve
        ds = a_ - B['seam']
        seam = np.exp(-(ds / 0.012) ** 2) * (e < 0.06)
        ha = ha - 0.0 * seam
        h = np.where(on, ha, h)
    return V + N * h[:, None]


def build_body(S, B, arms, name, mat, root):
    """arms: [eje del brazo izquierdo, eje del derecho] -> (objeto, Part)."""
    t0 = time.time()
    parts = [torso_volume(B), collar_volume(S, B)]
    for A, side in zip(arms, (1, -1)):
        parts += [arm_volume(B, A), deltoid_volume(B, A, side)]
    V, Fq, Ed = remesh_union(parts, B['voxel'])
    ri, ro, z0, z1 = B['collar']
    keep = ((V[:, 2] > z0 - 0.06) & (np.hypot(V[:, 0], V[:, 1] - S['neck_y']) < ro + 0.06)).astype(float)
    V = smooth_body(V, Fq, Ed, keep)
    V = body_knit(S, B, V, quad_normals(V, Fq), arms)
    part = C.Part(V, Fq)
    ob = C.make_object(name, part, mat, root)
    print(f'[dani] {name}: {len(V)} vertices, {time.time() - t0:.1f}s, caja {V.min(0).round(2)} {V.max(0).round(2)}', flush=True)
    return ob, part


def rest_arm(B, side):
    m = np.array([side, 1.0, 1.0])
    J, E, W = (np.array(B[k]) * m for k in ('shoulder', 'elbow_rest', 'wrist_rest'))
    return arm_path(J, E, W, C.unit(W - E))


def posed_arm(S, B, pose, pole):
    """Brazo derecho que llega a la mano de la pose (la manga acaba donde la acababa hands.py)."""
    F = C.unit(np.asarray(pose['F'], float))
    W_end = np.asarray(pose['wrist'], float) - F * 0.12 * S['hand_scale']
    J = np.array(B['shoulder']) * np.array([-1.0, 1.0, 1.0])
    E = solve_elbow(J, W_end - F * 0.2, B['upper'], B['fore'] - 0.2, pole)
    return arm_path(J, E, W_end, F)


def build_ears(S, head_surf):
    out = []
    for s in (-1, 1):
        loc, nor = head_surf.ray((s * 3.0, 0.06, -0.17), (-s, 0.0, 0.0))
        ax = C.unit(np.array([s * 1.0, -0.35, 0.0]))
        az = C.unit(np.array([0.0, 0.18, 1.0]))
        az = C.unit(az - ax * np.dot(az, ax))
        ay = np.cross(az, ax) * s
        sp = C.sphere_part(1.0, 40, 24)
        d = np.sign(sp.v) * np.abs(sp.v) ** 0.85
        sizes = np.array([0.055, 0.12, 0.19])
        lv = d * sizes
        dent = 0.05 * np.exp(-((lv[:, 1] + 0.01) / 0.065) ** 2 - ((lv[:, 2] + 0.02) / 0.11) ** 2) * (lv[:, 0] > 0)
        lv[:, 0] -= dent
        center = loc + ax * 0.03 + np.array([0.0, 0.02, 0.0])
        sp.v = center + lv[:, 0:1] * ax + lv[:, 1:2] * ay + lv[:, 2:3] * az
        if s < 0:
            sp.f = sp.f[:, ::-1]
        out.append(sp)
    return C.Part.join(out)


def build(S):
    root = C.empty('dani')
    F = studio.build_face(S, EXPR, root, dani_mats)
    head, head_surf, skin, mats = F['head'], F['head_surf'], F['skin'], F['mats']
    ears = build_ears(S, head_surf)
    C.make_object('head_ears', ears, skin, root)

    body, cuff, cut_line = C.build_beanie(S)
    C.make_object('beanie', body, mats['beanie'], root)
    C.make_object('beanie_cuff', cuff, mats['beanie'], root)
    frng = np.random.default_rng(23)

    def axis_center(z0=None):
        def f(P):
            Q = np.zeros_like(P)
            Q[:, 1] = 0.1
            Q[:, 2] = P[:, 2] if z0 is None else np.minimum(P[:, 2], z0)
            return Q
        return f
    C.make_object('beanie_fuzz', C.Part.join([C.wool_fuzz(body, S['fuzz'] * 2, frng, axis_center(0.3)),
                                              C.wool_fuzz(cuff, S['fuzz'], frng, axis_center())]),
                  mats['beanie_fuzz'], root)
    cphi, cz = cut_line['phis'], cut_line['z']

    def cut_z(phi):
        return float(np.interp((phi + np.pi) % (2 * np.pi) - np.pi, cphi, cz, period=2 * np.pi))

    # jersey de una pieza (torso, cuello vuelto, hombros y brazos) en reposo y con el brazo derecho en cada pose
    arm_l, arm_r = rest_arm(BODY, 1), rest_arm(BODY, -1)
    shirt_ob, torso = build_body(S, BODY, [arm_l, arm_r], 'shirt', mats['shirt'], root)
    body_vars = {None: [shirt_ob] + [C.make_object(f'shirt_cuff.{s}', cuff_part(BODY, a), mats['shirt'], root)
                                     for s, a in (('L', arm_l), ('R', arm_r))]}
    posed = {}
    for pname, pose in HAND_POSES.items():
        tag = '' if pname == S['done_pose'] else f'_{pname}'
        a = posed_arm(S, BODY, pose['R'], ARM_POLE[pname])
        ob, part = build_body(S, BODY, [arm_l, a], f'shirt_{pname}', mats['shirt'], root)
        cuffs = [C.make_object(f'shirt_cuff{tag}.L', cuff_part(BODY, arm_l), mats['shirt'], root),
                 C.make_object(f'shirt_cuff{tag}.R', cuff_part(BODY, a), mats['shirt'], root)]
        body_vars[pname] = [ob] + cuffs
        posed[pname] = part
    C.make_object('shirt_buttons', build_shirt_buttons(C.Surface(torso)), mats['button'], root)
    C.make_object('neck', C.build_neck(S), skin, root)

    # pelo: Hair Curves (guias sobre el cuero cabelludo + hijos por nodos), cuero cabelludo oscuro debajo
    rng = np.random.default_rng(HAIR['seed'])
    t_h = time.time()
    scalp, hairline = hair_scalp(S, head, cut_z)
    scalp_ob = C.make_object('hair_scalp', scalp, mat_scalp(S), root)
    roots, area = sample_faces(scalp, HAIR['guides'], rng)
    neck = C.build_neck(S)
    collide = C.Surface(C.Part.join([head, ears, neck, torso]))
    guides = hair_guides(S, roots, head_surf, collide, cut_z, hairline, rng)
    hair_ob = build_hair_curves(guides, scalp_ob, area, mat_hair_curves(S), root, quick='--quick' in sys.argv)
    print(f'[dani] pelo: {len(guides)} guias, cuero {area:.2f} u2, {time.time() - t_h:.1f}s', flush=True)

    # manos (done: pulgar arriba; done_alt: pulgar delante del pecho)
    # las mangas de hands.py y la mano izquierda en reposo (fuera de cuadro) sobran: las mangas son parte del jersey
    hand_parts = []
    hands = studio.build_hands(S, HAND_POSES, mats, root, frng, mats['shirt'], None, hand_parts)
    for pname, objs in hands.items():
        drop = [ob for ob in objs if ob.name.startswith('sleeve') or ob.name.endswith('.L')]
        for ob in drop:
            objs.remove(ob)
        for ob in sorted(drop, key=lambda o: o.parent is None):   # hijas (unas) antes que la mano
            bpy.data.objects.remove(ob, do_unlink=True)
        objs += body_vars[pname]
    hands[None] = body_vars[None]

    # chequeo de interpenetracion: jersey contra cabeza, gorro y cuero cabelludo, y cada mano contra su jersey
    # (las hebras se apartan de cabeza, orejas, cuello y jersey al generar las guias)
    pairs = [('shirt', torso, 'head', head), ('beanie', body, 'head', head), ('beanie_cuff', cuff, 'head', head),
             ('beanie_cuff', cuff, 'ears', ears), ('hair_scalp', scalp, 'beanie', body),
             ('hair_scalp', scalp, 'beanie_cuff', cuff), ('hair_scalp', scalp, 'ears', ears)]
    hand_pose = {'hand' + ('' if p == S['done_pose'] else f'_{p}') + '.R': p for p in HAND_POSES}
    for hname, part in hand_parts:
        if hname in hand_pose:
            pname = hand_pose[hname]
            pairs += [(hname, part, f'shirt[{pname}]', posed[pname]), (hname, part, 'head', head)]
    C.check_overlaps(pairs)

    ind_root, ind = studio.build_indicator_set(S, mats)
    arm = studio.build_rig('dani', root, F['eyes'], HEAD_PARTS)
    # build_rig solo cuelga mallas del hueso head: el objeto de pelo (Curves) se cuelga aqui
    mw = hair_ob.matrix_world.copy()
    hair_ob.parent, hair_ob.parent_type, hair_ob.parent_bone = arm, 'BONE', 'head'
    bpy.context.view_layer.update()
    hair_ob.matrix_world = mw
    studio.organize(GROUPS)
    return dict(root=root, head_surf=head_surf, eyes=F['eyes'], mats=mats, pupil=F['pupil'], iris=F['iris'], ind=ind,
                ind_root=ind_root, brows=F['brows'], mouth=F['mouth'], arm=arm, hands=hands)


HEAD_PARTS = ('head', 'eye', 'brow', 'mouth', 'hair', 'beanie')
GROUPS = [('rig', ('dani', 'dani_rig')), ('eyes', ('eye',)), ('brows', ('brow',)), ('mouth', ('mouth_',)),
          ('hair', ('hair_',)), ('head', ('head', 'beanie')), ('hands', ('hand', 'nails', 'sleeve')),
          ('body', ('shirt', 'collar', 'neck')), ('indicators', ('ind',))]


studio.run('dani', S, EXPR, build, review_expr=REVIEW_EXPR, icon_cam=ICON_CAM)
