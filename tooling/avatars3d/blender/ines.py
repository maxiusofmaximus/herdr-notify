"""Ines (tester) en Blender/Cycles: coleta negra, camisa, auriculares con microfono.

Uso (desde la raiz del repo):
  blender -b --factory-startup -P tooling/avatars3d/blender/ines.py -- [--out DIR] [--expr a,b] [--quick]
       [--review] [--samples N] [--closeup] [--view yaw:cx:cz:alto[;...]]
Mismas salidas que nicole.py (ines-<expr>.png 512, -128, -64, -48, -32, tira y review/). Render, luz, camara,
cara, manos, rig y salida son comunes (studio.py); aqui van la spec, el pelo, la coleta y la ropa.
"""
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import character as C  # noqa: E402
import studio  # noqa: E402

L = C.lin
S = dict(
    # cabeza: ovalada, barbilla fina, nariz de boton
    head_w=0.94, head_front=0.9, head_back=0.98, head_top=1.03, head_bot=0.95, jaw_taper=0.29,
    head_bumps=[
        ((0.55, -0.75, -0.22), 0.045, 0.3, True),   # mejillas
        ((0.36, -0.92, -0.08), -0.05, 0.2, True),    # cuencas
        ((0.0, -1.0, -0.33), 0.07, 0.09, False),     # nariz
        ((0.0, -1.0, -0.42), 0.04, 0.07, False),     # punta redonda (boton)
        ((0.0, -1.0, -0.22), 0.01, 0.05, False),     # dorso
        ((0.08, -1.0, -0.44), 0.02, 0.05, True),     # aletas
        ((0.045, -1.0, -0.48), -0.012, 0.022, True),  # orificios
        ((0.0, -1.0, -0.5), -0.008, 0.04, False),    # surco bajo la nariz
        ((0.0, -0.85, -0.85), 0.05, 0.22, False),    # barbilla
        ((0.3, -0.9, 0.2), 0.028, 0.2, True),        # arco de la ceja
        ((0.24, -0.9, -0.56), -0.006, 0.07, True),   # comisuras (pliegue suave de sonrisa, edad)
    ],
    skin=L('#9c6440'), blush=L('#8a4a3a'), nose_tip=L('#8a5238'), blush_r=0.22, blush_a=0.22, nose_a=0.45,
    skin_mottle=0.3, skin_grain=0.35,  # piel lisa: menos mancha de color y menos grano que Nicole (SSS igual)
    nail=L('#a86f4c'),
    # ojos almendrados: mas estrechos que Nicole, iris castano oscuro
    eye_x=0.36, eye_z=-0.1, eye_r=0.2, eye_depth=0.75, eye_yaw=9.0, eye_tilt=4.0,
    iris_ang=0.7, pupil=0.4,
    sclera=L('#f3ebe4'), sclera_edge=L('#cbb5aa'), iris_in=L('#6b4a33'), iris_mid=L('#3b2a1f'),
    iris_out=L('#1b130e'), iris_ring=L('#0c0806'), iris_glow=L('#a58060'),
    catchlights=[(-0.36, 0.42, 0.05), (0.3, -0.22, 0.024)],
    lash_w=0.026, lash_flicks=[],
    lash=L('#1a1210'), lid_thick=0.018, crease_gap=13, crease_w=0.013, lid_fillet=0.09,
    # cejas finas y oscuras (mas estrechas que las de Nicole y Alfred)
    brow_pts=[(0.09, 0.2), (0.34, 0.27), (0.62, 0.23)], brow_w=0.04, brow=L('#2e2421'),
    brow_light=L('#4a3d38'), brow_dark=L('#120c0a'), brow_hair=0.0028, brow_hair_len=0.012,
    lip_up_h=0.022, lip_lo_h=0.034, lip_up_lift=0.014, lip_lo_lift=0.022,
    mouth_center=(0.0, -0.53), lip=L('#8e5444'), lipline=L('#3d211b'), cavity=L('#3a1212'),
    teeth=L('#fbf6ef'), tongue=L('#b8555c'),
    # pelo negro: casquete tirado hacia atras con raya al lado; la coleta cae por el hombro
    hair_axis_y=0.12, hair_base=L('#2e1f18'), hair_dark=L('#0d0908'), hair_spec=L('#7a665c'),
    hair_ramp=[(0.0, (0.6, 0.6, 0.62, 1)), (0.3, (0.85, 0.85, 0.85, 1)), (0.7, (1.0, 1.0, 1.0, 1)),
               (1.0, (1.1, 1.08, 1.06, 1))],
    hair_strand_ramp=[(0.0, (0.008, 0.0065, 0.006, 1)), (0.35, (0.02, 0.016, 0.014, 1)),
                      (0.8, (0.034, 0.025, 0.02, 1)), (1.0, (0.045, 0.032, 0.025, 1))],
    cap_off=0.014,
    # cuerpo: cuello y hombros, camisa de algodon en rojo apagado (acento del agente), auriculares negros
    neck_y=0.12, neck_r=0.34, neck_z=(-1.6, -0.55), torso_a=1.4, torso_b=0.8, torso_y=0.2, neck_ring_r=0.45,
    torso_zn=-1.22, torso_zs=-1.95, torso_zb=-3.6,
    shoulder_drop=0.42, shoulder_t0=(2.4, -0.5), shoulder_t1=(0.0, -1.0),
    shirt=L('#9e3a33'), cup=L('#3b3f49'), mic=L('#454953'), pad=L('#24262d'),
    collar_r=0.375, collar_z=(-1.34, -0.99),
    # indicadores (mismo sitio y escala que Nicole) en el color del agente
    accent=L('#c2413a'),
    indicator_root=(1.1, -1.2, 0.74), indicator_scale=1.15,
    icon_indicator=((0.6, -1.05, 0.8), 0.85), indicator_at=(0.0, 0.0, 0.0),
    sparkles=[(0.0, 0.0, 0.3), (-0.36, 0.26, 0.15), (0.3, -0.36, 0.14)],
    sweat_at=(-0.86, -0.62, 0.12),
    hand_scale=1.4, done_pose='peace', fuzz=0,
)

# misma gramatica que Nicole; Alfred algo mas sereno (parpado algo mas bajo en neutral, sonrisa contenida)
EXPR = {
    'neutral': dict(lid_up=38, lid_lo=-44, gaze=(0, -2), tilt=0, pupil=0.4,
                    brow={1: (0, 0, 0), -1: (0, 0, 0)},
                    mouth=dict(w=0.17, cl=0.03, cr=0.03, up=0.0, open=0.0)),
    'thinking': dict(lid_up=32, lid_lo=-34, gaze=(16, -18), tilt=0, pupil=0.38,
                     brow={1: (0.06, 0.11, 0.07), -1: (-0.035, -0.03, 0.0)},
                     mouth=dict(w=0.13, cl=-0.006, cr=0.02, up=0.0, open=0.0, shift=0.06, flat=True),
                     indicator='thinking'),
    'working': dict(lid_up=12, lid_lo=-26, gaze=(-20, 4), tilt=12, pupil=0.4,
                    brow={1: (-0.11, -0.03, 0.04), -1: (-0.11, -0.03, 0.04)},
                    mouth=dict(w=0.13, cl=-0.008, cr=-0.004, up=0.0, open=0.0, shift=-0.02, flat=True),
                    indicator='working'),
    'happy': dict(lid_up=16, lid_lo=16, gaze=(0, 0), tilt=0, pupil=0.4,
                  brow={1: (0.05, 0.07, 0.03), -1: (0.05, 0.07, 0.03)},
                  mouth=dict(w=0.22, cl=0.075, cr=0.075, up=-0.01, open=0.17, teeth=True, teeth_h=0.05,
                             tongue=True),
                  indicator='happy'),
    'error': dict(lid_up=47, lid_lo=-52, gaze=(0, 0), tilt=-6, pupil=0.26, iris=0.78,
                  brow={1: (0.1, 0.03, -0.03), -1: (0.1, 0.03, -0.03)},
                  mouth=dict(w=0.15, cl=-0.04, cr=-0.04, up=0.004, open=0.0, flat=True),
                  indicator='error'),
    'done': dict(lid_up=28, lid_lo=-30, gaze=(0, 0), tilt=0, pupil=0.42,
                 brow={1: (0.04, 0.05, 0.02), -1: (0.04, 0.05, 0.02)},
                 mouth=dict(w=0.21, cl=0.07, cr=0.07, up=-0.01, open=0.1, teeth=True, teeth_h=0.045),
                 indicator='done', hands=S['done_pose']),
}

# done = V de paz (como Sami y Nicole) con la mano derecha del personaje (izquierda de la imagen) junto a la mejilla;
# .R = mano derecha; la manga es de camisa (punio liso, rib=0). done_alt = corazon con las dos manos delante del pecho
REST = studio.REST
HAND_POSES = {
    # V vertical junto a la mejilla, fuera de la cara; palma a camara, anular y menique recogidos bajo el pulgar;
    # antebrazo recto a lo largo de F con el codo abajo, junto al costado
    'peace': dict(R=dict(wrist=(-1.22, -1.0, -0.72), F=(0.1, -0.2, 1.0), N=(0.0, 1.0, 0.0), side=-1,
                         curl=dict(index=(0, 4, 4), middle=(0, 4, 4), ring=(80, 95, 60), pinky=(85, 95, 60)),
                         splay=dict(index=15, middle=-11, ring=-4, pinky=-10),
                         thumb=dict(dir=(-0.75, -0.65, 0.3), up=(0.3, -1, 0.3), curl=(15, 20)),
                         arm=[(-1.75, -1.0, -2.9), (-1.5, -1.22, -1.65)], rib=0.0),
                  L=REST),
    # corazon delante del pecho: dedos curvados forman los lobulos y los pulgares la punta
    'heart': dict(R=dict(wrist=(-0.5, -1.38, -1.75), F=(0.5, 0.0, 1.0), N=(-1.0, -0.5, 0.0), side=1,
                         curl=dict(index=(45, 50, 35), middle=(45, 50, 35), ring=(45, 50, 35), pinky=(45, 50, 35)),
                         thumb=dict(dir=(0.9, -0.25, -0.65), up=(-0.4, -1.0, 0.2), curl=(5, 10)),
                         arm=[(-1.15, -1.2, -3.0), (-0.85, -1.62, -2.35)], rib=0.0),
                  L='mirror'),
}
_mouth_parts = C.mouth_parts


def flat_mouth_parts(S, head_surf, m):
    """Boca cerrada sencilla (flat=True: thinking/working/error): labios casi planos, sin volumen que sobresalga;
    solo se lee la linea."""
    if m.get('flat'):
        S = dict(S, lip_up_h=S['lip_up_h'] * 0.45, lip_lo_h=S['lip_lo_h'] * 0.45,
                 lip_up_lift=S['lip_up_lift'] * 0.2, lip_lo_lift=S['lip_lo_lift'] * 0.2)
    return _mouth_parts(S, head_surf, m)


C.mouth_parts = flat_mouth_parts
REVIEW_EXPR = {'done_alt': dict(EXPR['done'], shape='done', hands='heart')}
ICON_CAM = {'peace': dict(height=3.0, center=(-0.14, 0.0)), 'heart': dict(height=3.6, center=(0.0, -0.4))}


# ---------------------------------------------------------------- pelo
# Pelo con el sistema de pelo de Blender (como Alfred): objeto Hair Curves con curvas guia peinadas sobre el cuero
# cabelludo y un modificador de Geometry Nodes con los nodos de pelo que trae Blender
# (procedural_hair_node_assets.blend): Duplicate (hijos) -> Clump -> Noise -> Frizz -> perfil. Peinado tirado hacia
# atras: desde la raya al lado cada hebra va hacia la goma de la coleta (baja, detras de la oreja izquierda, +X).
# La coleta es otro objeto de curvas: un haz que sale de la goma, pasa sobre el hombro y cae por delante.
# Sombreado con Principled Hair BSDF (Chiang): negro con raiz mas oscura y puntas algo calidas.
RAYA = 22.0                      # raya: a 22 grados de la vertical hacia +X (lado corto)
PART_X = math.sin(math.radians(RAYA))
TIE_DIR = C.unit(np.array([0.5, 0.82, -0.3]))   # goma de la coleta: atras, abajo y hacia +X
HAIR_GUIDES = 2600
HAIR_PTS = 28
HAIR_GN = dict(children=14, child_radius=0.012, clump=0.5, clump_dist=0.04, tip_spread=0.002,
               noise=0.004, noise_scale=4.0, frizz=0.0012, radius=0.0016, tip_factor=0.25)
TAIL_GN = dict(children=18, child_radius=0.022, clump=0.6, clump_dist=0.06, tip_spread=0.012,
               noise=0.01, noise_scale=3.0, frizz=0.003, radius=0.0018, tip_factor=0.05)
HAIR_NODE_ASSETS = ('Duplicate Hair Curves', 'Clump Hair Curves', 'Hair Curves Noise', 'Frizz Hair Curves',
                    'Set Hair Curve Profile')


def hairline_el(phi_deg):
    """Altura (elevacion, grados) del nacimiento del pelo por azimut: frente, entradas suaves, patilla, oreja, nuca."""
    k = [0, 30, 45, 58, 70, 78, 86, 98, 108, 120, 140, 180]
    e = [34, 32, 27, 18, -4, -10, 10, 13, 6, -18, -32, -38]
    return np.interp(np.abs(phi_deg), k, e)


def dir_angles(D):
    """Direcciones unitarias -> (azimut desde delante hacia +X, elevacion) en grados."""
    return np.degrees(np.arctan2(D[..., 0], -D[..., 1])), np.degrees(np.arcsin(np.clip(D[..., 2], -1, 1)))


def hair_flow(D):
    """Direccion tangente del peinado en D: hacia la goma (TIE_DIR) y, delante y arriba, hacia fuera de la raya
    (el lado grande, -X, se abre en diagonal hacia la sien antes de ir hacia atras)."""
    x, y, z = D[:, 0], D[:, 1], D[:, 2]
    g = TIE_DIR[None, :] - D
    top = C.ss(0.35, 0.8, z) * C.ss(0.45, -0.35, y)
    g[:, 0] += np.where(x < PART_X, -0.9, 0.5) * top
    g -= D * np.sum(g * D, -1, keepdims=True)
    return C.unit(g)


def comb(D0, L):
    """Integra el campo de peinado desde cada raiz D0 una longitud L (radianes) -> (HAIR_PTS, n, 3)."""
    n = HAIR_PTS
    out = np.empty((n,) + D0.shape)
    D = D0.copy()
    h = (L / (n - 1))[:, None]
    for k in range(n):
        out[k] = D
        D = C.unit(D + h * hair_flow(D))
    return out


def hair_guides(S, head_surf, ears_surf, rng):
    """Curvas guia: raices uniformes en la zona de pelo; cada hebra se peina hasta cerca de la goma (se corta al
    llegar). Volumen suave arriba y delante (el pelo tirado hacia atras no va plano) que baja hacia la goma; cada hebra
    sube con el camino recorrido, asi las de delante pasan por encima de las de detras. -> lista de (n, 3)."""
    D = C.unit(rng.normal(size=(HAIR_GUIDES * 6, 3)))
    phi, el = dir_angles(D)
    D = D[el > hairline_el(phi) + 1.0][:HAIR_GUIDES]
    ang = np.arccos(np.clip(D @ TIE_DIR, -1, 1))
    L = np.maximum(ang * 1.25, 0.08)
    P = comb(D, L)
    # corta donde la hebra llega a la goma (angulo < 0.16 rad)
    near = np.arccos(np.clip(P @ TIE_DIR, -1, 1)) < 0.16
    first = np.where(near.any(0), near.argmax(0), HAIR_PTS - 1)
    L = np.maximum(L * first / (HAIR_PTS - 1), 0.06)
    P = comb(D, L)
    u = np.linspace(0, 1, HAIR_PTS)[:, None]
    s = u * L[None, :]
    z, y = D[:, 2], D[:, 1]
    vol = 0.1 * C.ss(0.4, 0.95, z) * C.ss(0.3, -0.6, y) + 0.05 * C.ss(0.1, 0.8, z)
    # cerca de la goma el pelo se recoge (baja hacia el cuero cabelludo)
    Pend = np.arccos(np.clip(P @ TIE_DIR, -1, 1))
    gather = C.ss(0.75, 0.2, Pend)
    off = S['cap_off'] * 0.5 + 0.004 + 0.03 * s + vol[None, :] * C.ss(0, 0.3, u) * (1 - 0.7 * gather)
    off[0] = -0.004
    X = C.head_points(P, S) + P * off[..., None]
    guides = []
    margin = S['cap_off'] * 0.5 + 0.004
    for i in range(X.shape[1]):
        g = X[:, i].copy()
        for _ in range(3):
            g = C.smooth_path(head_surf.push_out(g, margin), 2)
        g = head_surf.push_out(g, margin)
        if not np.allclose(ears_surf.push_out(g.copy(), 0.02), g):
            continue
        guides.append(g)
    return guides


def tail_path(S):
    """Eje de la coleta (n, 3) y radio del haz: sale de la goma, baja por detras de la oreja, pasa sobre el hombro y
    cae por delante sobre el pecho."""
    G = C.head_points(TIE_DIR[None], S)[0] + TIE_DIR * 0.06
    ctrl = np.array([G, G + np.array([0.12, 0.06, -0.2]), (0.88, 0.62, -0.85), (1.02, 0.32, -1.3),
                     (1.02, -0.02, -1.55), (0.97, -0.3, -1.95), (0.92, -0.42, -2.45), (0.9, -0.44, -2.85)])
    s = np.linspace(0, 1, 64)
    k = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(ctrl, axis=0), axis=1))])
    k /= k[-1]
    P = np.stack([np.interp(s, k, ctrl[:, i]) for i in range(3)], -1)
    P = C.smooth_path(P, 6)
    r = np.interp(s, [0.0, 0.04, 0.12, 0.3, 0.7, 1.0], [0.07, 0.08, 0.13, 0.14, 0.11, 0.035])
    return P, r, s


def tail_guides(S, head_surf, body_surf, rng, n=520):
    """Guias de la coleta: raices en un disco en la goma; cada guia sigue el eje con su offset en el plano normal
    (escalado con el radio del haz) y ondas suaves por mechon que se abren hacia la punta."""
    P, r, s = tail_path(S)
    T = C.unit(np.gradient(P, axis=0))
    e1 = C.unit(np.cross(T, np.array([0.0, 0.0, 1.0])) + 1e-6)
    e2 = np.cross(T, e1)
    ang = rng.uniform(0, 2 * np.pi, n)
    rad = np.sqrt(rng.uniform(0, 1, n))
    guides = []
    for i in range(n):
        ph = rng.uniform(0, 2 * np.pi)
        wave = 0.05 * np.sin(2 * np.pi * 1.6 * s + ph) * C.ss(0.15, 0.6, s)
        a = ang[i] + 0.6 * np.sin(2 * np.pi * 0.8 * s + ph) * C.ss(0.2, 1.0, s)
        rr = rad[i] * r + wave * rad[i]
        g = P + rr[:, None] * (np.cos(a)[:, None] * e1 + np.sin(a)[:, None] * e2)
        g = g[: int(len(s) * rng.uniform(0.86, 1.0))]
        for _ in range(3):
            g = body_surf.push_out(g, 0.045)
            g = head_surf.push_out(g, S['cap_off'] + 0.01)
            g = C.smooth_path(g, 2)
        guides.append(g)
    return guides, P, r, s


def build_tie(P, r, s, at=0.05):
    """Goma de la coleta: anillo grueso (toro) alrededor del eje a la altura `at`."""
    j = int(at * (len(s) - 1))
    T = C.unit(P[j + 1] - P[j - 1])
    e1 = C.unit(np.cross(T, np.array([0.0, 0.0, 1.0])))
    e2 = np.cross(T, e1)
    th = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    rr = r[j] * 1.02 + 0.035
    ring = P[j] + rr * (np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2)
    return C.sweep(ring, np.tile(T, (48, 1)), np.full(48, 0.045), np.full(48, 0.038), 14, closed=True)


def hair_proxy(guides, w=0.004):
    """Cinta fina por guia (malla) para check_overlaps; el pelo de verdad son curvas."""
    vs, fs, base = [], [], 0
    for g in guides:
        T = C.unit(np.gradient(g, axis=0))
        side = C.unit(np.cross(T, C.unit(g - np.array([0.0, 0.0, 0.1])))) * w
        n = len(g)
        i = np.arange(n - 1)
        fs.append(np.stack([i, i + 1, n + i + 1, n + i], -1)[1:] + base)   # sin el tramo de raiz (va dentro)
        vs.append(np.concatenate([g - side, g + side]))
        base += 2 * n
    return C.Part(np.concatenate(vs), np.concatenate(fs))


def hair_node_assets():
    need = [n for n in HAIR_NODE_ASSETS if n not in bpy.data.node_groups]
    if need:
        for root in ('LOCAL', 'SYSTEM'):
            p = os.path.join(bpy.utils.resource_path(root), 'datafiles', 'assets', 'nodes',
                             'procedural_hair_node_assets.blend')
            if os.path.exists(p):
                break
        with bpy.data.libraries.load(p, link=False) as (_, dst):
            dst.node_groups = need
    return {n: bpy.data.node_groups[n] for n in HAIR_NODE_ASSETS}


def hair_nodes(name, mat, g):
    """Geometry Nodes del pelo: hijos alrededor de cada guia, mechones (clump), ondulacion y ruido, frizz y perfil
    (radio que se afila a la punta)."""
    A = hair_node_assets()
    ng = bpy.data.node_groups.new(name, 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    prev = ng.nodes.new('NodeGroupInput').outputs[0]

    def step(group, **inp):
        nonlocal prev
        n = ng.nodes.new('GeometryNodeGroup')
        n.node_tree = A[group]
        for k, v in inp.items():
            n.inputs[k.replace('_', ' ')].default_value = v
        ng.links.new(prev, n.inputs[0])
        prev = n.outputs[0]

    step('Duplicate Hair Curves', Amount=g['children'], Radius=g['child_radius'], Distribution_Shape=0.3, Seed=5)
    step('Clump Hair Curves', Factor=g['clump'], Shape=0.6, Tip_Spread=g['tip_spread'], Guide_Distance=g['clump_dist'],
         Existing_Guide_Map=False, Preserve_Length=True, Seed=7)
    step('Hair Curves Noise', Distance=g['noise'], Scale=g['noise_scale'], Scale_along_Curve=1.5, Shape=0.6,
         Offset_per_Curve=0.5, Preserve_Length=True, Seed=9)
    step('Frizz Hair Curves', Distance=g['frizz'], Factor=0.5, Seed=13)
    step('Set Hair Curve Profile', Radius=g['radius'], Shape=0.6, Factor_Min=g['tip_factor'], Factor_Max=1.0)
    sm = ng.nodes.new('GeometryNodeSetMaterial')
    sm.inputs['Material'].default_value = mat
    ng.links.new(prev, sm.inputs['Geometry'])
    ng.links.new(sm.outputs[0], ng.nodes.new('NodeGroupOutput').inputs[0])
    return ng


def make_hair_curves(name, guides, mat, parent, g):
    cv = bpy.data.hair_curves.new(name)
    cv.add_curves([len(c) for c in guides])
    cv.position_data.foreach_set('vector', np.concatenate(guides).astype(np.float32).ravel())
    cv.materials.append(mat)
    ob = bpy.data.objects.new(name, cv)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    ob.modifiers.new('hair', 'NODES').node_group = hair_nodes(name, mat, g)
    return ob


def mat_hair_strands(S):
    """Principled Hair BSDF (Chiang, color directo): degradado raiz-punta por Intercept, tono propio por hebra y
    brillo suave (negro con reflejo frio en la cutícula, puntas algo calidas)."""
    nb = C.NB('hair_strands')
    info = nb.node('ShaderNodeHairInfo')
    col = nb.ramp(info.outputs['Intercept'], S['hair_strand_ramp'])
    var = nb.ramp(info.outputs['Random'], [(0.0, (0.7, 0.7, 0.7, 1)), (1.0, (1.15, 1.1, 1.05, 1))])
    col = nb.mix(1.0, col, var, blend='MULTIPLY')
    h = nb.node('ShaderNodeBsdfHairPrincipled', model='CHIANG', parametrization='COLOR')
    nb.put(h.inputs['Color'], col)
    for k, v in (('Roughness', 0.3), ('Radial Roughness', 0.4), ('Coat', 0.12), ('IOR', 1.55),
                 ('Offset', math.radians(2.0)), ('Random Roughness', 0.25)):
        h.inputs[k].default_value = v
    nb.put(h.inputs['Random'], info.outputs['Random'])
    nb.nt.links.new(h.outputs[0], nb.out.inputs['Surface'])
    return nb.mat


def build_hair_cap(S):
    """Cuero cabelludo bajo las curvas: capa fina del color de la raiz (vetas en el sentido del peinado) desde el
    nacimiento hasta la coronilla; el borde se funde a transparente (atributo capfade) para un nacimiento suave."""
    nu, nv = 256, 64
    phi = np.linspace(-180, 180, nu, endpoint=False)
    t = np.linspace(0, 1, nv)
    el0 = hairline_el(phi)
    E = el0[:, None] + (89.0 - el0[:, None]) * t[None, :] ** 1.3
    P, El = np.radians(phi)[:, None] * np.ones((1, nv)), np.radians(E)
    D = np.stack([np.cos(El) * np.sin(P), -np.cos(El) * np.cos(P), np.sin(El)], -1)
    V = C.head_points(D, S) + D * (S['cap_off'] * 0.5)
    f, ci, cj = C.grid_faces(nu, nv, closed_u=True, flip=True)
    ci = ci % nu
    uv = np.stack([ci / nu * 12.0, cj / (nv - 1) * 3.0], -1)
    part = C.Part(V.reshape(-1, 3), f, uv)
    fade = np.tile(C.ss(0.0, 0.1, t), nu)
    part.col = np.stack([fade, fade, fade, np.ones_like(fade)], -1)
    return part


def mat_hair_cap(S):
    nb = C.NB('hair_cap')
    attr = nb.node('ShaderNodeAttribute', attribute_name='capfade')
    u, v, uvv = nb.uv_xy()
    stri = nb.node('ShaderNodeTexWave', wave_type='BANDS', bands_direction='X', wave_profile='SIN')
    nb.put(stri.inputs['Vector'], uvv)
    stri.inputs['Scale'].default_value = 60.0
    stri.inputs['Distortion'].default_value = 2.0
    stri.inputs['Detail'].default_value = 3.0
    # tono cercano al de los mechones: entre mechon y mechon asoma pelo corto, no un hueco oscuro
    base = S['hair_strand_ramp'][1][1]
    col = nb.mix(nb.math('MULTIPLY', stri.outputs['Fac'], 0.3), base, tuple(c * 0.6 for c in base[:3]) + (1,))
    bsdf = nb.principled(Base_Color=col, Roughness=0.7, Specular_IOR_Level=0.15, Sheen_Weight=0.15,
                         Sheen_Tint=S['hair_spec'], Normal=nb.bump(stri.outputs['Fac'], 0.15, 0.004))
    tr = nb.node('ShaderNodeBsdfTransparent')
    mix = nb.node('ShaderNodeMixShader')
    nb.nt.links.new(nb.math('POWER', attr.outputs['Fac'], 1.5), mix.inputs['Fac'])
    nb.nt.links.new(tr.outputs[0], mix.inputs[1])
    nb.nt.links.new(bsdf.outputs[0], mix.inputs[2])
    nb.nt.links.new(mix.outputs[0], nb.out.inputs['Surface'])
    return nb.mat


# ---------------------------------------------------------------- ropa

def mat_cotton(name, color):
    """Algodon: mate, sheen suave y un tejido fino en bump."""
    nb = C.NB(name)
    co = nb.texco().outputs['Object']
    weave = nb.noise(co, 260.0, 2.0, 0.5)
    var = nb.noise(co, 5.0, 2.0)
    c = nb.mix(nb.math('MULTIPLY', var, 0.12), color, (color[0] * 0.9, color[1] * 0.9, color[2] * 0.92, 1))
    nb.principled(Base_Color=c, Roughness=0.72, Specular_IOR_Level=0.3, Sheen_Weight=0.35, Sheen_Roughness=0.5,
                  Subsurface_Weight=0.1, Subsurface_Radius=(1, 0.9, 0.8), Subsurface_Scale=0.02,
                  Normal=nb.bump(weave, 0.12, 0.004))
    return nb.mat


def mat_cup(name, color):
    """Auriculares: plastico mate con un punto de brillo (la carcasa del auricular)."""
    return C.mat_flat(name, color, rough=0.42, coat=0.25)


def ines_mats(S):
    return dict(shirt=mat_cotton('shirt', S['shirt']), pearl=C.mat_flat('pearl', L('#f4efe6'), rough=0.25, coat=0.6),
                hair_cap=mat_hair_cap(S), cup=mat_cup('headset', S['cup']), mic=mat_cup('mic', S['mic']),
                pad=C.mat_flat('headset_pad', S['pad'], rough=0.75, coat=0.0),
                accent=mat_cup('accent', S['accent']))


def grid_part(P, uv_scale=(1.0, 1.0), closed_u=False):
    """Malla de una rejilla (nu, nv, 3) con normales hacia fuera (eje del cuerpo) y uv por arco."""
    nu, nv = P.shape[:2]
    f, ci, cj = C.grid_faces(nu, nv, closed_u=closed_u)
    ci = ci % nu
    du = np.linalg.norm(np.diff(P, axis=0), axis=-1)
    u = np.concatenate([np.zeros((1, nv)), np.cumsum(du, 0)], 0)
    dv = np.linalg.norm(np.diff(P, axis=1), axis=-1)
    v = np.concatenate([np.zeros((nu, 1)), np.cumsum(dv, 1)], 1)
    uv = np.stack([u[ci, cj] * uv_scale[0], v[ci, cj] * uv_scale[1]], -1)
    part = C.Part(P.reshape(-1, 3), f, uv)
    return C.orient_out(part, (0.0, 0.15, float(P[..., 2].mean())))


# ---------------------------------------------------------------- cuerpo
# Torso y brazos en una sola superficie implicita (distancia con signo, combinada con uniones suaves): columna del
# pecho de seccion eliptica que cambia con la altura (pecho mas ancho que la cintura), trapecios (conos redondeados
# del cuello al hombro: hombro caido), deltoides, busto y omoplatos suaves, y cada brazo en dos tramos
# (hombro-codo-muneca) fundido con el deltoides: un solo tubo continuo, sin bola ni costura. Se maila con surface
# nets, se proyecta a la superficie y se relaja; los pliegues de la tela (codo, brazo, axila, cintura) y la tapeta
# van como desplazamiento por la normal. Hay una variante por pose de mano (brazos caidos y brazo levantado).
BODY_LO, BODY_HI, BODY_H = np.array([-2.3, -1.6, -4.3]), np.array([2.3, 1.1, -0.75]), 0.022
TZ = np.array([-4.3, -3.6, -3.0, -2.5, -2.1, -1.75, -1.5, -1.28])      # alturas de la columna (de abajo arriba)
TA = np.array([0.84, 0.82, 0.8, 0.88, 0.93, 0.9, 0.76, 0.55])          # semiancho
TB = np.array([0.55, 0.54, 0.52, 0.56, 0.58, 0.55, 0.48, 0.38])       # semifondo
TY = 0.13
SHOULDER = np.array([1.12, 0.1, -1.98])
HANG = dict(E=(1.3, 0.2, -3.1), W=(1.36, 0.02, -4.2))


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b + (a - b) * h - k * h * (1 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def sd_ellipsoid(Q, c, r):
    p = (Q - c) / r
    k0 = np.linalg.norm(p, axis=-1)
    k1 = np.linalg.norm(p / r, axis=-1)
    return k0 * (k0 - 1) / np.maximum(k1, 1e-6)


def seg_t(Q, a, b):
    ba = b - a
    t = np.clip(((Q - a) @ ba) / (ba @ ba), 0, 1)
    return t, np.linalg.norm(Q - (a + t[:, None] * ba), axis=-1)


def sd_path(Q, P, r):
    """Tubo de radio variable r (n,) a lo largo de la polilinea P (n, 3): minimo de conos redondeados."""
    d = np.full(len(Q), 1e9)
    for i in range(len(P) - 1):
        t, dd = seg_t(Q, P[i], P[i + 1])
        d = np.minimum(d, dd - (r[i] + (r[i + 1] - r[i]) * t))
    return d


def arm_paths(pose):
    """Brazo de un lado como polilineas: (eje hombro-codo-punta (n, 3), radios (n,), arco del codo, punio)
    pose: None (caido) o dict(sx, E, Wc, F) con la punta Wc del antebrazo y la direccion de la mano F."""
    sx = pose['sx']
    S0 = SHOULDER * np.array([sx, 1, 1])
    E, W, F = np.asarray(pose['E'], float), np.asarray(pose['W'], float), pose.get('F')
    up = np.linspace(S0, E, 9)
    # antebrazo recto (codo-muneca); la mano sigue su eje (HAND_POSES F ~ direccion del antebrazo)
    fo = np.linspace(E, W, 11 if F is None else 13)[1:]
    P = np.concatenate([up, fo])
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    le = arc[8]
    s = np.clip((arc - le) / (arc[-1] - le), 0, 1)
    r = np.where(arc <= le, np.interp(arc, [0, le], [0.245, 0.205]), 0.2 - 0.04 * s)
    return P, r, arc, le


def arm_poses(hand):
    """Brazos por variante: hand None (los dos caidos) o el nombre de una pose de HAND_POSES (brazo derecho)."""
    out = [dict(sx=1, **HANG)]
    if hand is None:
        return out + [dict(sx=-1, E=(-1.3, 0.2, -3.1), W=(-1.36, 0.02, -4.2))]
    h = HAND_POSES[hand]['R']
    F = C.unit(np.asarray(h['F'], float))
    Wc = np.asarray(h['wrist'], float) - F * 0.17
    raised = dict(sx=-1, E=ARM_ELBOW[hand], W=Wc, F=F, solid=0.7)
    if HAND_POSES[hand]['L'] == 'mirror':
        m = np.array([-1.0, 1.0, 1.0])
        out = [dict(sx=1, E=np.asarray(ARM_ELBOW[hand]) * m, W=Wc * m, F=F * m, solid=0.7)]
    return out + [raised]


NECK_HOLE, NECK_HOLE_Z = 0.41, -1.72     # escote: radio y fondo (lo tapa entero el pie del cuello de la camisa)
COLLAR_ZB = -1.62                          # el pie del cuello baja hasta aqui (dentro de la camisa)
ARM_ELBOW = {'peace': (-1.36, -0.72, -2.11), 'heart': (-1.35, -0.45, -2.95)}   # F de la mano = eje del antebrazo


def body_sdf(Q, arms):
    x, y, z = Q[:, 0], Q[:, 1] - TY, Q[:, 2]
    a, b = np.interp(z, TZ, TA), np.interp(z, TZ, TB)
    k = np.sqrt((x / a) ** 2 + (y / b) ** 2)
    g = np.sqrt((x / a ** 2) ** 2 + (y / b ** 2) ** 2)
    d = k * (k - 1) / np.maximum(g, 1e-6)
    d = smax(d, z - TZ[-1], 0.3)
    d = np.maximum(d, -4.25 - z)
    for sx in (-1, 1):
        t, dd = seg_t(Q, np.array([sx * 0.25, 0.14, -1.46]), np.array([sx * 0.98, 0.11, -1.74]))
        d = smin(d, dd - (0.2 + 0.04 * t), 0.15)
        d = smin(d, sd_ellipsoid(Q, np.array([sx * 0.36, -0.3, -2.3]), np.array([0.3, 0.24, 0.27])), 0.18)
        d = smin(d, sd_ellipsoid(Q, np.array([sx * 0.48, 0.5, -2.05]), np.array([0.32, 0.16, 0.36])), 0.15)
    kz = 0.04 + 0.16 * C.ss(-2.4, -2.0, z)
    for pose in arms:
        P, r, arc, le = arm_paths(pose)
        if pose.get('solid'):
            keep = arc <= le + (arc[-1] - le) * pose['solid']
            P, r = P[keep], r[keep]
        da = sd_path(Q, P, r)
        dirr = C.unit(P[1] - P[0])
        dl = sd_ellipsoid(Q, P[0] + dirr * 0.05 + np.array([pose['sx'] * -0.02, 0, 0.06]), np.array([0.27, 0.31, 0.34]))
        da = smin(da, dl, 0.15)
        d = smin(d, da, kz)
    # escote: hueco alrededor del cuello (lo tapa el cuello de la camisa)
    hole = np.maximum(np.hypot(Q[:, 0], Q[:, 1] - S['neck_y']) - NECK_HOLE, NECK_HOLE_Z - z)
    return smax(d, -hole, 0.07)


def eval_chunks(fn, Q, n=400000):
    return np.concatenate([fn(Q[i:i + n]) for i in range(0, len(Q), n)])


def surface_nets(fn, lo, hi, h):
    """Malla de cuads de la isosuperficie fn = 0 (surface nets: un vertice por celda que corta, en la media de los
    cruces de sus aristas; un cuad por arista que corta, orientado hacia fuera)."""
    n = (np.ceil((hi - lo) / h)).astype(int) + 1
    ax_ = [lo[i] + h * np.arange(n[i]) for i in range(3)]
    F = np.empty(n, np.float32)
    for i0 in range(0, n[0], 12):
        X, Y, Z = np.meshgrid(ax_[0][i0:i0 + 12], ax_[1], ax_[2], indexing='ij')
        F[i0:i0 + 12] = fn(np.stack([X, Y, Z], -1).reshape(-1, 3)).reshape(X.shape)
    nc = n - 1
    ncell = int(np.prod(nc))
    acc = np.zeros((ncell, 3))
    cnt = np.zeros(ncell)
    edges = []
    for ax in range(3):
        s0 = [slice(None)] * 3
        s1 = [slice(None)] * 3
        s0[ax], s1[ax] = slice(0, -1), slice(1, None)
        f0, f1 = F[tuple(s0)], F[tuple(s1)]
        e = (f0 < 0) != (f1 < 0)
        idx = np.argwhere(e)
        a0, a1 = f0[e].astype(float), f1[e].astype(float)
        p = lo + idx * h
        p[:, ax] += a0 / (a0 - a1) * h
        b, c = (ax + 1) % 3, (ax + 2) % 3
        cells = []
        for ob, oc in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            ci = idx.copy()
            ci[:, b] += ob
            ci[:, c] += oc
            ok = (ci >= 0).all(1) & (ci < nc).all(1)
            lin = np.where(ok, np.ravel_multi_index(np.clip(ci, 0, nc - 1).T, nc), -1)
            cells.append(lin)
            for j in range(3):
                acc[:, j] += np.bincount(lin[ok], p[ok, j], ncell)
            cnt += np.bincount(lin[ok], None, ncell)
        cells = np.stack(cells, 1)
        good = (cells >= 0).all(1)
        q = cells[good]
        flip = a0[good] >= 0
        q[flip] = q[flip, ::-1]
        edges.append(q)
    used = cnt > 0
    vid = np.full(ncell, -1, np.int64)
    vid[used] = np.arange(used.sum())
    V = acc[used] / cnt[used, None]
    return C.Part(V, vid[np.concatenate(edges)])


def sdf_grad(fn, V, e=0.004):
    g = np.stack([fn(V + d) - fn(V - d) for d in np.eye(3) * e], -1) / (2 * e)
    return g


def project(fn, V, it=3):
    for _ in range(it):
        g = sdf_grad(fn, V)
        V = V - (fn(V) / np.maximum((g * g).sum(1), 1e-6))[:, None] * g
    return V


def relax(part, fn, rounds=3):
    f = part.f
    a = np.concatenate([f[:, 0], f[:, 1], f[:, 2], f[:, 3]])
    b = np.concatenate([f[:, 1], f[:, 2], f[:, 3], f[:, 0]])
    n = len(part.v)
    deg = np.bincount(a, None, n) + np.bincount(b, None, n)
    V = part.v
    for _ in range(rounds):
        avg = np.stack([np.bincount(a, V[b, j], n) + np.bincount(b, V[a, j], n) for j in range(3)], -1)
        V = V + 0.5 * (avg / np.maximum(deg, 1)[:, None] - V)
        V = project(fn, V, 2)
    part.v = V
    return part


def arm_frame(P, V):
    """Para cada vertice: arco a lo largo del brazo, distancia al eje y angulo alrededor (marco sin giro)."""
    Pd = np.concatenate([np.linspace(P[i], P[i + 1], 6, endpoint=False) for i in range(len(P) - 1)] + [P[-1:]])
    arc = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(Pd, axis=0), axis=1))])
    T = C.unit(np.gradient(Pd, axis=0))
    e1 = C.unit(np.cross(T, np.array([0.0, -1.0, 0.3])))
    e2 = np.cross(T, e1)
    j = np.empty(len(V), int)
    dist = np.empty(len(V))
    for i0 in range(0, len(V), 20000):
        D = np.linalg.norm(V[i0:i0 + 20000, None] - Pd[None], axis=-1)
        j[i0:i0 + 20000] = D.argmin(1)
        dist[i0:i0 + 20000] = D.min(1)
    R = V - Pd[j]
    th = np.arctan2((R * e2[j]).sum(1), (R * e1[j]).sum(1))
    return arc[j], dist, th, arc[-1]


def shirt_folds(V, N, arms):
    """Desplazamiento de la tela por la normal: pliegues en espiral en el codo, arrastre diagonal en el brazo,
    tirones del busto hacia la axila, ondas suaves en la cintura y la tapeta de botones delante."""
    x, y, z = V[:, 0], V[:, 1], V[:, 2]
    disp = np.zeros(len(V))
    on_arm = np.zeros(len(V))
    for pose in arms:
        P, r, arc0, le = arm_paths(pose)
        ell, dist, th, total = arm_frame(P, V)
        w = C.ss(0.36, 0.28, dist) * C.ss(0.1, 0.3, ell)
        on_arm = np.maximum(on_arm, w)
        bent = pose.get('F') is not None
        elb = np.exp(-((ell - le) / (0.24 if bent else 0.18)) ** 2)
        disp += w * elb * (0.05 if bent else 0.026) * np.sin(3 * th + 15 * ell + pose['sx'])
        drag = C.ss(0.25, 0.45, ell) * C.ss(le - 0.1, le - 0.3, ell)
        disp += w * drag * 0.03 * np.sin(2 * th - 10 * ell * pose['sx'])
        fore = C.ss(le + 0.15, le + 0.35, ell)
        disp += w * fore * 0.012 * np.sin(2 * th + 9 * ell)
    body = 1 - on_arm
    ax_ = np.abs(x)
    front = np.clip(-N[:, 1], 0, 1)
    u = (ax_ - 0.36) * 0.62 + (z + 2.3) * 0.78        # perpendicular a la linea busto-axila
    v = (ax_ - 0.36) * 0.78 - (z + 2.3) * 0.62
    pull = C.ss(-0.05, 0.1, v) * C.ss(0.75, 0.5, v) * C.ss(0.35, 0.1, np.abs(u))
    disp += body * front * pull * 0.03 * np.sin(u * 30)
    disp += body * C.ss(-2.75, -2.95, z) * C.ss(-3.6, -3.3, z) * 0.016 * np.sin(z * 24 + 2.5 * np.sin(x * 3))
    # caida de la tela: pliegues verticales suaves bajo el pecho y en la espalda
    disp += body * C.ss(-2.5, -2.9, z) * 0.018 * np.sin(x * 13 + 1.3 * np.sin(z * 4)) * (1 - 0.5 * front)
    plack = C.ss(0.12, 0.085, ax_) * C.ss(-1.4, -1.5, z) * C.ss(0.3, 0.6, front)
    disp += body * plack * 0.016
    return disp


def build_body(hand):
    """Camisa (torso y mangas) de una variante de brazos -> (Part, sdf, brazos)."""
    arms = arm_poses(hand)

    def fn(Q):
        return eval_chunks(lambda q: body_sdf(q, arms), Q)
    part = surface_nets(fn, BODY_LO, BODY_HI, BODY_H)
    part.v = project(fn, part.v)
    part = relax(part, fn)
    N = C.unit(sdf_grad(fn, part.v))
    part.v = part.v + N * shirt_folds(part.v, N, arms)[:, None]
    return part, fn, arms


def build_cuff(pose):
    """Punio abierto del brazo levantado: tubo de tela que cubre el final del antebrazo (que acaba dentro) y deja
    ver la muneca, con su canto redondeado."""
    P, r, arc, le = arm_paths(pose)
    s = (arc - le) / (arc[-1] - le)
    keep = s >= 0.56
    P, s, r = P[keep], s[keep], r[keep]
    t = np.linspace(0, 1, 40)
    k = np.linspace(0, 1, len(P))
    Q = np.stack([np.interp(t, k, P[:, i]) for i in range(3)], -1)
    ss_ = np.interp(t, k, s)
    rr = np.interp(ss_, [0.56, 0.6, 0.68, 1.0], [0.0, 0.0, 1.0, 1.0])
    rad = (0.2 - 0.04 * ss_ + 0.022) * (1 - rr) + 0.225 * rr
    O = np.tile(C.unit(np.cross(Q[-1] - Q[0], [0.0, 0.0, 1.0])), (40, 1))
    tubep = C.sweep(Q, O, rad, rad, 40)
    T = C.unit(Q[-1] - Q[-2])
    e1 = C.unit(np.cross(T, [0.0, 0.0, 1.0]))
    e2 = np.cross(T, e1)
    th = np.linspace(0, 2 * np.pi, 40, endpoint=False)
    ring = Q[-1] + rad[-1] * (np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2)
    rim = C.sweep(ring, np.tile(T, (40, 1)), np.full(40, 0.016), np.full(40, 0.016), 10, closed=True)
    # costura del punio: un anillo fino a 0.12 del canto
    j = int(np.searchsorted(np.cumsum(np.r_[0, np.linalg.norm(np.diff(Q[::-1], axis=0), axis=1)]), 0.13))
    q = Q[-1 - j]
    seam = C.sweep(q + (rad[-1 - j] + 0.002) * (np.cos(th)[:, None] * e1 + np.sin(th)[:, None] * e2),
                   np.tile(T, (40, 1)), np.full(40, 0.008), np.full(40, 0.008), 8, closed=True)
    return C.Part.join([tubep, rim, seam])


def build_neck(S):
    """Cuello (como C.build_neck), algo mas ancho en la base; lo rodea entero el pie del cuello de la camisa."""
    nu, nv = 64, 24
    th = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    zs = np.linspace(S['neck_z'][0], S['neck_z'][1], nv)
    T, Z = np.meshgrid(th, zs, indexing='ij')
    r = S['neck_r'] + 0.03 * C.ss(-1.3, -1.6, Z)
    P = np.stack([r * np.sin(T), S['neck_y'] - r * np.cos(T), Z], -1)
    f, ci, cj = C.grid_faces(nu, nv, closed_u=True)
    return C.Part(P.reshape(-1, 3), f, np.stack([ci / nu, cj / nv], -1))


def build_shirt_buttons(surf):
    out = []
    for zb in (-1.8, -2.1, -2.4, -2.7):
        loc, nor = surf.ray((0.0, -3.0, zb), (0.0, 1.0, 0.0))
        bt = C.sphere_part(1.0, 20, 10)
        bt.v = bt.v * np.array([0.042, 0.016, 0.042]) + loc + nor * 0.012
        out.append(bt)
    return C.Part.join(out)


def build_collar(S, coll):
    """Cuello de camisa: pie (banda) cerrado alrededor del cuello, vuelta que cae hacia fuera con las puntas
    delante (a los lados de la pajarita), pliegue superior en tubo y canto de la vuelta."""
    y0, r0 = S['neck_y'], S['collar_r']
    zb, zt = S['collar_z']
    nu, nv = 200, 18
    ph = np.radians(np.linspace(2, 358, nu))
    # pie cerrado delante (camisa abotonada arriba) que baja dentro del escote y se abre hasta casi su borde:
    # sin hueco entre el pie, el cuello y el pecho
    zz = np.linspace(COLLAR_ZB, zt, nv)
    Ph, Z = np.meshgrid(np.linspace(0, 2 * np.pi, nu, endpoint=False), zz, indexing='ij')
    R = r0 - 0.01 * np.clip((Z - zb) / (zt - zb), 0, 1) + (NECK_HOLE - 0.024 - r0) * C.ss(zb + 0.04, COLLAR_ZB + 0.06, Z)
    band = np.stack([R * np.sin(Ph), y0 - R * np.cos(Ph), Z], -1)
    band_p = grid_part(band, closed_u=True)
    # vuelta: filas desde el pliegue (t=0) hasta el canto (t=1); el borde delantero baja en diagonal hasta la punta
    nt = 22
    t = np.linspace(0, 1, nt)
    leaf = np.empty((nu, nt, 3))
    rt = r0 - 0.01 + 0.016
    for j, tt in enumerate(t):
        pf = 0.6 + 2.0 * tt
        p = np.radians(np.linspace(pf, 360 - pf, nu))
        d = np.minimum(np.degrees(p), 360 - np.degrees(p))
        # canto: punta delante (z bajo, mas fuera) y detras recto a media altura del pie
        point = np.exp(-((d - 26) / 16) ** 2)
        z_edge = -1.2 - 0.2 * point
        r_edge = 0.48 + 0.06 * point
        ease = C.ss(0, 1, tt) * 0.6 + tt * 0.4
        r = rt + (r_edge - rt) * ease + 0.03 * np.sin(np.pi * tt)
        z = zt + 0.006 + (z_edge - zt) * ease
        leaf[:, j] = np.stack([r * np.sin(p), y0 - r * np.cos(p), z], -1)
    # la vuelta cae sobre la camisa: hacia el canto se baja hasta apoyarse en el pecho, hombros y espalda
    for i in range(nu):
        for j in range(nt):
            w = C.ss(0.3, 1.0, t[j])
            loc, nor = coll.ray(leaf[i, j] + np.array([0.0, 0.0, 0.4]), (0.0, 0.0, -1.0))
            if w > 0 and loc is not None:
                target = loc + nor * 0.016
                if target[2] < leaf[i, j, 2]:
                    leaf[i, j] += (target - leaf[i, j]) * w
    for _ in range(3):
        flat = leaf.reshape(-1, 3)
        flat[:] = coll.push_out(flat, 0.016, start=0)
        leaf = flat.reshape(nu, nt, 3)
        leaf[1:-1] = 0.5 * leaf[1:-1] + 0.25 * (leaf[:-2] + leaf[2:])
        leaf[:, 1:-1] = 0.5 * leaf[:, 1:-1] + 0.25 * (leaf[:, :-2] + leaf[:, 2:])
    leaf = coll.push_out(leaf.reshape(-1, 3), 0.015, start=0).reshape(nu, nt, 3)
    leaf_p = grid_part(leaf)
    # pliegue de arriba y canto (borde inferior + bordes delanteros) en tubos finos
    fold = np.stack([(rt - 0.004) * np.sin(ph), y0 - (rt - 0.004) * np.cos(ph), np.full(nu, zt + 0.002)], -1)
    edge = np.concatenate([leaf[0], leaf[1:, -1], leaf[-1, ::-1][1:]])
    edge = C.smooth_path(edge, 2, keep_root=False)
    tubes = []
    for E, w in ((fold, 0.012), (edge, 0.009)):
        ctr = np.stack([np.zeros(len(E)), np.full(len(E), y0), E[:, 2]], -1)
        tubes.append(C.sweep(E, C.unit(E - ctr), np.full(len(E), w), np.full(len(E), w), 8))
    return C.Part.join([band_p, leaf_p] + tubes)


def build_ears(S, head_surf):
    """-> (orejas, {lado: (centro, eje hacia fuera)})."""
    out, frames = [], {}
    for s in (-1, 1):
        loc, nor = head_surf.ray((s * 3.0, 0.06, -0.17), (-s, 0.0, 0.0))
        ax = C.unit(np.array([s * 1.0, -0.15, 0.0]))      # grosor (hacia fuera, pegada a la cabeza: no asoma tras el casco)
        az = C.unit(np.array([0.0, 0.18, 1.0]))            # alto, inclinada hacia atras
        az = C.unit(az - ax * np.dot(az, ax))
        ay = np.cross(az, ax) * s
        sp = C.sphere_part(1.0, 40, 24)
        d = np.sign(sp.v) * np.abs(sp.v) ** 0.85
        sizes = np.array([0.055, 0.12, 0.19])
        if s > 0:     # la oreja del casco queda tapada por la almohadilla: mas pequenia y plana, no asoma por detras
            sizes = np.array([0.045, 0.09, 0.15])
        lv = d * sizes
        # concha: hueco en la cara exterior dentro del borde (helix)
        dent = 0.05 * np.exp(-((lv[:, 1] + 0.01) / 0.065) ** 2 - ((lv[:, 2] + 0.02) / 0.11) ** 2) * (lv[:, 0] > 0)
        lv[:, 0] -= dent
        center = loc + ax * 0.03 + np.array([0.0, 0.02, 0.0])
        frames[s] = (center, ax)
        sp.v = center + lv[:, 0:1] * ax + lv[:, 1:2] * ay + lv[:, 2:3] * az
        if s < 0:
            sp.f = sp.f[:, ::-1]
        out.append(sp)
    return C.Part.join(out), frames


def tube(P, r, nu=20):
    """Tubo a lo largo de la polilinea P (n, 3) con radio r (escalar o por punto); anillos en el orden de grid_faces."""
    n = len(P)
    r = np.broadcast_to(np.asarray(r, dtype=float), (n,))
    T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    ref = np.tile([0.0, 0.0, 1.0], (n, 1))
    ref[np.abs(T[:, 2]) > 0.9] = [1.0, 0.0, 0.0]
    e1 = np.cross(T, ref)
    e1 /= np.linalg.norm(e1, axis=1, keepdims=True)
    e2 = np.cross(T, e1)
    th = np.linspace(0, 2 * np.pi, nu, endpoint=False)[:, None, None]
    V = P[None] + r[None, :, None] * (np.cos(th) * e1[None] + np.sin(th) * e2[None])
    f, ci, cj = C.grid_faces(nu, n, closed_u=True, flip=True)
    uv = np.stack([ci % nu / nu * 4.0, cj / (n - 1) * 8.0], -1)
    return C.Part(V.reshape(-1, 3), f, uv)


def disc(c, A, e1, e2, r, h, expo=4.0, nu=48, nv=16):
    """Disco de cantos redondeados (superelipsoide) centrado en c: eje A (grosor h), radios r=(r1, r2) en e1, e2."""
    sp = C.sphere_part(1.0, nu, nv)
    # perfil superelipse (radio en el plano, grosor): caras casi planas y canto redondeado
    rho = np.linalg.norm(sp.v[:, 0:2], axis=1)
    q = sp.v[:, 2]
    k = rho ** (2.0 / expo) / np.maximum(rho, 1e-9)
    t = np.sign(q) * np.abs(q) ** (2.0 / expo)
    sp.v = c + (sp.v[:, 0:1] * k[:, None] * r[0]) * e1 + (sp.v[:, 1:2] * k[:, None] * r[1]) * e2 + t[:, None] * h * A
    if np.dot(np.cross(e1, e2), A) < 0:
        sp.f = sp.f[:, ::-1]
    return sp


def headset_frames(S, ear_frames):
    """Por lado: centro de la oreja, eje hacia fuera A, horizontal e1 (hacia atras), vertical e2."""
    out = {}
    for s, (center, ax) in ear_frames.items():
        A = C.unit(np.array([s * 1.0, -0.12, 0.0]))
        e2 = np.array([0.0, 0.0, 1.0])
        e1 = C.unit(np.cross(e2, A)) * s
        out[s] = dict(ear=center, A=A, e1=e1, e2=e2)
    return out


def build_headset(S, head_surf, hair_surf, ear_frames):
    """Diadema de call center monoaural (pieza rigida de plastico, no se ciñe al pelo): arco fino que pasa por
    encima de la cabeza y solo toca el pelo arriba, un casco redondo con almohadilla firme sobre la oreja +X (lado
    del micro), un apoyo pequenio contra la sien del otro lado y un brazo de microfono fino y curvo hasta la boca.
    -> (arco, carcasa, almohadilla y apoyo, brazo, microfono)."""
    fr = headset_frames(S, ear_frames)
    f = fr[1]
    A, e1, e2 = f['A'], f['e1'], f['e2']
    pad_c = f['ear'] + A * 0.105 + e1 * 0.03 - e2 * 0.015
    pad = disc(pad_c, A, e1, e2, (0.2, 0.235), 0.042, expo=2.6)
    shell_c = pad_c + A * 0.07
    shell = [disc(shell_c, A, e1, e2, (0.185, 0.215), 0.04, expo=3.2),
             disc(shell_c + A * 0.035, A, e1, e2, (0.11, 0.125), 0.014, expo=3.0)]
    # apoyo del otro lado: almohadilla ovalada pequenia contra la sien, encima de la oreja
    g = fr[-1]
    loc, nor = None, None
    for surf in (hair_surf, head_surf):
        l_, n_ = surf.ray(g['ear'] + np.array([-2.5, 0.0, 0.3]), (1.0, 0.0, 0.0))
        if l_ is not None and (loc is None or l_[0] < loc[0]):
            loc, nor = l_, n_
    gA = C.unit(np.asarray(nor))
    ge2 = C.unit(np.array([0.0, 0.0, 1.0]) - gA * gA[2])
    ge1 = np.cross(ge2, gA)
    stab_c = loc + gA * 0.034
    stab_c = head_surf.push_out(stab_c[None], 0.05, start=0)[0]
    stab = disc(stab_c, gA, ge1, ge2, (0.07, 0.1), 0.026, expo=2.4)
    stab_top = stab_c + gA * 0.012 + ge2 * 0.08
    cup_top = shell_c + e2 * 0.2

    # arco rigido: envolvente convexa del perfil de pelo y cabeza en el plano de los dos extremos (curva lisa, sin
    # copiar los mechones); solo toca arriba, en la coronilla, y a los lados se separa un poco como un muelle
    c = np.array([0.0, 0.5 * (cup_top[1] + stab_top[1]), max(cup_top[2], stab_top[2]) + 0.12])
    phi = np.linspace(-np.pi / 2, np.pi / 2, 91)
    D = np.stack([np.sin(phi), np.zeros_like(phi), np.cos(phi)], -1)

    def outer(D):
        best = 0.0
        for dy in (-0.05, -0.025, 0.0, 0.025, 0.05):
            o = c + np.array([0.0, dy, 0.0])
            for surf in (hair_surf, head_surf):
                loc, _ = surf.ray(o + D * 3.0, -D)
                if loc is not None:
                    best = max(best, np.dot(loc - o, D))
        return best
    gap = 0.02 + 0.006 + 0.03 * np.abs(np.sin(phi)) ** 3       # radio del tubo + holgura (mas a los lados)
    rmin = np.array([outer(d) for d in D]) + gap
    xz = np.stack([rmin * np.sin(phi), rmin * np.cos(phi)], -1)
    # envolvente convexa (cadena superior, de -X a +X) y remuestreo por longitud
    hull = []
    for p in xz:
        while len(hull) >= 2 and cross2(hull[-1] - hull[-2], p - hull[-2]) >= 0:
            hull.pop()
        hull.append(p)
    hull = np.array(hull)
    L = np.r_[0, np.cumsum(np.linalg.norm(np.diff(hull, axis=0), axis=1))]
    t = np.linspace(0, L[-1], 80)
    hull = np.stack([np.interp(t, L, hull[:, 0]), np.interp(t, L, hull[:, 1])], -1)
    for _ in range(4):
        hull[1:-1] = 0.5 * hull[1:-1] + 0.25 * (hull[:-2] + hull[2:])
    arc = c + np.stack([hull[:, 0], np.zeros(len(hull)), hull[:, 1]], -1)
    # el suavizado puede meter la curva un pelo hacia dentro: se vuelve a sacar por los rayos
    Dh = C.unit(arc - c)
    rh = np.array([outer(d) for d in Dh]) + 0.026
    rad = np.linalg.norm(arc - c, axis=1)
    arc = c + Dh * np.maximum(rad, rh)[:, None]
    # tramos rectos: del arco baja vertical a la rotula del casco (+X) y al apoyo (-X)
    left = np.linspace(stab_top, arc[0], 8)[:-1]
    right = np.linspace(arc[-1], cup_top, 8)[1:]
    P = C.smooth_path(np.vstack([left, arc, right]), 2)
    P[0], P[-1] = stab_top, cup_top
    band = [tube(P, 0.02, nu=14)]
    # rotula sobre el casco y tope del lado del apoyo
    band.append(disc(cup_top - e2 * 0.01, e1, A, e2, (0.034, 0.034), 0.05, expo=2.4))
    band.append(disc(stab_top, ge1, gA, ge2, (0.03, 0.03), 0.04, expo=2.4))

    # brazo del microfono: sale de la parte delantera-baja del casco, curva fina por delante de la mejilla
    root = shell_c - e1 * 0.14 - e2 * 0.1 + A * 0.02
    B = np.array([root, root + np.array([-0.02, -0.28, -0.14]), (0.62, -0.92, -0.56), (0.32, -1.1, -0.66)])
    sm = np.linspace(0, 1, 40)
    kk = np.linspace(0, 1, len(B))
    Q = np.stack([np.interp(sm, kk, B[:, i]) for i in range(3)], -1)
    Q = C.smooth_path(Q, 4)
    for _ in range(3):
        Q[1:] = head_surf.push_out(Q[1:], 0.045)
        Q = C.smooth_path(Q, 2)
    Q[0] = root
    swivel = C.sphere_part(1.0, 20, 12)
    swivel.v = root + swivel.v * 0.032
    boom = C.Part.join([tube(Q, 0.012, nu=12), swivel])
    T = C.unit(Q[-1] - Q[-2])
    mic = disc(Q[-1] + T * 0.02, T, *_perp(T), (0.032, 0.032), 0.045, expo=2.0)
    return C.Part.join(band), C.Part.join(shell), C.Part.join([pad, stab]), boom, mic


def cross2(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _perp(T):
    e1 = C.unit(np.cross(T, [0.0, 0.0, 1.0]))
    return e1, np.cross(T, e1)


def build(S):
    root = C.empty('ines')
    F = studio.build_face(S, EXPR, root, ines_mats)
    head, head_surf, skin, mats = F['head'], F['head_surf'], F['skin'], F['mats']
    ears, ear_frames = build_ears(S, head_surf)
    C.make_object('head_ears', ears, skin, root)

    # camisa: una variante de torso y mangas por pose de manos (rig['hands']: la clave None se ve sin manos)
    bodies, cuffs = {}, {}
    for hand in (None,) + tuple(HAND_POSES):
        part, fn, arms = build_body(hand)
        bodies[hand] = part
        cuffs[hand] = [build_cuff(p) for p in arms if p.get('F') is not None]
    shirt = bodies[None]
    shirt_surf = C.Surface(shirt)
    C.make_object('neck', build_neck(S), skin, root)
    buttons = build_shirt_buttons(shirt_surf)
    C.make_object('shirt_buttons', buttons, mats['pearl'], root)
    collar = build_collar(S, shirt_surf)
    C.make_object('collar', collar, mats['shirt'], root)
    body_obs = {}
    for hand, part in bodies.items():
        tag = '' if hand is None else f'_{hand}'
        obs = [C.make_object(f'shirt{tag}', part, mats['shirt'], root)]
        obs += [C.make_object(f'shirt_cuff{tag}', c, mats['shirt'], root) for c in cuffs[hand]]
        body_obs[hand] = obs

    # pelo: cuero cabelludo (malla) y curvas de pelo peinadas hacia la goma; coleta en curvas aparte con su goma
    rng = np.random.default_rng(11)
    cap = build_hair_cap(S)
    C.make_object('hair_cap', cap, mats['hair_cap'], root, colors=True, colname='capfade')
    guides = hair_guides(S, head_surf, C.Surface(ears), rng)
    tguides, TP, TR, TS = tail_guides(S, head_surf, shirt_surf, rng)
    tie = build_tie(TP, TR, TS)
    C.make_object('hair_tie', tie, mats['accent'], root)
    strands = mat_hair_strands(S)
    hair_obs = [make_hair_curves('hair_curves', guides, strands, root, HAIR_GN),
                make_hair_curves('hair_tail', tguides, strands, root, TAIL_GN)]
    locks, tail = hair_proxy(guides), hair_proxy(tguides)
    print(f'[hair] {len(guides)} guias + {len(tguides)} de coleta', flush=True)
    band, cups, pads, boom, mic = build_headset(S, head_surf, C.Surface(C.Part.join([cap, locks])), ear_frames)
    C.make_object('headset_band', band, mats['cup'], root)
    C.make_object('headset_cups', cups, mats['cup'], root)
    C.make_object('headset_pads', pads, mats['pad'], root)
    C.make_object('headset_boom', boom, mats['mic'], root)
    C.make_object('headset_mic', mic, mats['mic'], root)

    hand_parts = []
    frng = np.random.default_rng(23)
    hands = studio.build_hands(S, HAND_POSES, mats, root, frng, mats['shirt'], None, hand_parts)
    # las mangas de hands.py sobran: el brazo es parte de la camisa (y el punio, build_cuff)
    for k, objs in hands.items():
        for ob in [o for o in objs if o.name.startswith('sleeve')]:
            objs.remove(ob)
            bpy.data.objects.remove(ob)
        objs += body_obs[k]
    hands[None] = body_obs[None]
    hand_parts = [(n, p) for n, p in hand_parts if not n.startswith('sleeve')]

    # chequeo de interpenetracion: ropa contra cuello y cabeza, pelo y auriculares contra orejas y cabeza, manos
    # contra su camisa y todo lo demas
    neck = build_neck(S)
    cloth = dict(shirt=shirt, collar=collar, neck=neck, head=head, ears=ears, hair_cap=cap, hair_locks=locks,
                 hair_tail=tail, tie=tie, band=band, cups=cups, pads=pads, boom=boom, mic=mic, buttons=buttons)
    pairs = [(a, cloth[a], b, cloth[b]) for a, b in (
        ('shirt', 'neck'), ('shirt', 'collar'), ('collar', 'neck'), ('collar', 'head'), ('shirt', 'head'), ('shirt', 'cups'),
        ('buttons', 'collar'), ('hair_locks', 'ears'), ('hair_cap', 'ears'), ('hair_locks', 'head'),
        ('hair_locks', 'collar'), ('hair_tail', 'shirt'), ('hair_tail', 'collar'), ('hair_tail', 'head'),
        ('tie', 'head'), ('tie', 'ears'), ('band', 'hair_cap'), ('band', 'head'), ('band', 'ears'),
        ('band', 'hair_tail'), ('cups', 'ears'), ('cups', 'head'), ('cups', 'hair_locks'), ('pads', 'ears'),
        ('pads', 'head'), ('pads', 'hair_locks'), ('pads', 'hair_cap'), ('cups', 'hair_tail'), ('pads', 'hair_tail'),
        ('boom', 'head'), ('mic', 'head'), ('boom', 'ears'), ('boom', 'hair_locks'))]
    for hand in HAND_POSES:
        bp = bodies[hand]
        htag = 'hand' if hand == S['done_pose'] else f'hand_{hand}'
        pairs += [(f'shirt_{hand}', bp, b, cloth[b]) for b in ('neck', 'head', 'collar', 'hair_tail', 'cups')]
        for c in cuffs[hand]:
            pairs += [(f'cuff_{hand}', c, 'shirt', bp)]
            for hname, part in hand_parts:
                if hname.split('.')[0] == htag:
                    pairs += [(hname, part, f'cuff_{hand}', c)]
        for hname, part in hand_parts:
            if hname.split('.')[0] == htag:
                pairs += [(hname, part, f'shirt_{hand}', bp)]
                pairs += [(hname, part, b, cloth[b]) for b in ('collar', 'head', 'ears', 'hair_locks', 'hair_tail',
                                                               'cups', 'boom', 'buttons')]
    C.check_overlaps(pairs)

    ind_root, ind = studio.build_indicator_set(S, mats)
    arm = studio.build_rig('ines', root, F['eyes'], HEAD_PARTS)
    for ob in hair_obs:
        mw = ob.matrix_world.copy()
        ob.parent, ob.parent_type, ob.parent_bone = arm, 'BONE', 'head'
        bpy.context.view_layer.update()
        ob.matrix_world = mw
    studio.organize(GROUPS)
    return dict(root=root, head_surf=head_surf, eyes=F['eyes'], mats=mats, pupil=F['pupil'], iris=F['iris'], ind=ind,
                ind_root=ind_root, brows=F['brows'], mouth=F['mouth'], arm=arm, hands=hands)


HEAD_PARTS = ('head', 'eye', 'brow', 'mouth', 'hair')
GROUPS = [('rig', ('ines', 'ines_rig')), ('eyes', ('eye',)), ('brows', ('brow',)), ('mouth', ('mouth_',)),
          ('hair', ('hair_',)), ('head', ('head',)), ('hands', ('hand', 'nails')),
          ('body', ('shirt', 'collar', 'neck')), ('headset', ('headset',)), ('indicators', ('ind',))]


studio.run('ines', S, EXPR, build, review_expr=REVIEW_EXPR, icon_cam=ICON_CAM)
