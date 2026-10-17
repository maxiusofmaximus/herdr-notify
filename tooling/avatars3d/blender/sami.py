"""Sami (Android) en Blender/Cycles: cara redonda, ojos entornados, pelo oscuro con raya lateral, sudadera verde con
capucha y auriculares inalambricos.

Uso (desde la raiz del repo):
  blender -b --factory-startup -P tooling/avatars3d/blender/sami.py -- [--out DIR] [--expr a,b] [--quick]
       [--review] [--samples N] [--closeup] [--view yaw:cx:cz:alto[;...]]
Mismas salidas que nicole.py (sami-<expr>.png 512, -128, -64, -48, -32, tira y review/). Render, luz, camara,
cara, manos, rig y salida son comunes (studio.py); aqui van la spec, el pelo y la ropa.
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
    # cabeza redonda (algo mas ancha que alta, mandibula corta), barbilla suave, nariz plana
    head_w=1.02, head_front=0.98, head_back=1.04, head_top=0.96, head_bot=0.92, jaw_taper=0.14,
    head_bumps=[
        ((0.55, -0.75, -0.22), 0.04, 0.3, True),     # mejillas (redondas)
        ((0.36, -0.92, -0.08), -0.03, 0.2, True),    # cuencas
        ((0.0, -1.0, -0.33), 0.02, 0.09, False),     # nariz plana (apenas un bulto)
        ((0.08, -1.0, -0.44), 0.012, 0.05, True),    # aletas
        ((0.0, -0.85, -0.85), 0.03, 0.22, False),    # barbilla
        ((0.3, -0.9, 0.2), 0.02, 0.2, True),         # arco de la ceja
        ((0.24, -0.9, -0.56), -0.006, 0.07, True),   # comisuras (sonrisa suave)
    ],
    skin=L('#DDA77E'), blush=L('#c98a78'), nose_tip=L('#c98a78'), blush_r=0.22, blush_a=0.28, nose_a=0.4,
    nail=L('#e6b596'),
    # ojos entornados: mas pequenos y con parpado alto, iris castano
    eye_x=0.36, eye_z=-0.1, eye_r=0.2, eye_depth=0.75, eye_yaw=9.0, eye_tilt=0.0,
    iris_ang=0.7, pupil=0.4,
    sclera=L('#f6efe8'), sclera_edge=L('#d9c6bd'), iris_in=L('#8a6444'), iris_mid=L('#5a3b24'),
    iris_out=L('#2a1a10'), iris_ring=L('#0d0805'), iris_glow=L('#c9a27e'),
    catchlights=[(-0.36, 0.42, 0.05), (0.3, -0.22, 0.024)],
    lash_w=0.03, lash_flicks=[],
    lash=L('#2a2224'), lid_thick=0.018, crease_gap=13, crease_w=0.013, lid_fillet=0.09,
    # cejas arqueadas, oscuras como el pelo
    brow_pts=[(0.09, 0.2), (0.34, 0.3), (0.62, 0.24)], brow_w=0.06, brow=L('#2b2632'),
    brow_light=L('#4a4456'), brow_dark=L('#15111c'), brow_hair=0.0032, brow_hair_len=0.016,
    lip_up_h=0.02, lip_lo_h=0.03, lip_up_lift=0.014, lip_lo_lift=0.022,
    mouth_center=(0.0, -0.53), lip=L('#b57262'), lipline=L('#5a2e26'), cavity=L('#3a1214'),
    teeth=L('#fbf6ef'), tongue=L('#d9646e'),
    # pelo oscuro con raya lateral: curvas de pelo (Principled Hair, melanina) sobre un casquete fino
    hair_melanin=(0.99, 0.95), hair_redness=(0.03, 0.1), hair_tint=(0.9, 0.88, 1.0, 1.0),
    hair_axis_y=0.12, hair_base=L('#1E1B2E'), hair_dark=L('#16131a'), hair_spec=L('#7d7673'),
    hair_ramp=[(0.0, (0.6, 0.6, 0.66, 1)), (0.3, (0.85, 0.85, 0.9, 1)), (0.7, (1.0, 0.98, 1.05, 1)),
               (1.0, (1.1, 1.08, 1.14, 1))],
    cap_off=0.014,
    # cuerpo: cuello corto y recio, trapecio, hombros caidos con deltoides y torso en V suave (ver build_body);
    # sudadera con capucha verde plegada al cuello y cordones claros
    neck_y=0.12, neck_r=0.42, neck_z=(-1.5, -0.6), torso_n=2.5, torso_y=0.16, torso_zn=-1.08, shoulder_drop=0.42,
    hoodie=L('#3F6212'), string=L('#d9d6cc'), hood_r=0.55, neck_hole=0.5, hood_z=(-1.4, -0.94),
    # indicadores en el acento del agente
    accent=L('#4D7F12'),
    indicator_root=(1.1, -1.2, 0.74), indicator_scale=1.15,
    icon_indicator=((0.6, -1.05, 0.8), 0.85), indicator_at=(0.0, 0.0, 0.0),
    sparkles=[(0.0, 0.0, 0.3), (-0.36, 0.26, 0.15), (0.3, -0.36, 0.14)],
    sweat_at=(-0.86, -0.62, 0.12),
    hand_scale=1.4, done_pose='peace', fuzz=0,
)

# misma gramatica que Nicole; Sami con parpado mas bajo (ojos entornados) y sonrisa contenida
EXPR = {
    'neutral': dict(lid_up=30, lid_lo=-38, gaze=(0, -2), tilt=0, pupil=0.4,
                    brow={1: (0, 0, 0), -1: (0, 0, 0)},
                    mouth=dict(w=0.17, cl=0.03, cr=0.03, up=0.0, open=0.0)),
    'thinking': dict(lid_up=26, lid_lo=-30, gaze=(16, -18), tilt=0, pupil=0.38,
                     brow={1: (0.06, 0.11, 0.07), -1: (-0.035, -0.03, 0.0)},
                     mouth=dict(w=0.14, cl=-0.008, cr=0.022, up=0.0, open=0.0, shift=0.06),
                     indicator='thinking'),
    'working': dict(lid_up=18, lid_lo=-26, gaze=(-20, 4), tilt=12, pupil=0.4,
                    brow={1: (-0.11, -0.03, 0.04), -1: (-0.11, -0.03, 0.04)},
                    mouth=dict(w=0.14, cl=-0.01, cr=-0.004, up=0.0, open=0.0, shift=-0.02),
                    indicator='working'),
    'happy': dict(lid_up=14, lid_lo=16, gaze=(0, 0), tilt=0, pupil=0.4,
                  brow={1: (0.05, 0.07, 0.03), -1: (0.05, 0.07, 0.03)},
                  mouth=dict(w=0.22, cl=0.075, cr=0.075, up=-0.01, open=0.17, teeth=True, teeth_h=0.05,
                             tongue=True),
                  indicator='happy'),
    'error': dict(lid_up=40, lid_lo=-46, gaze=(0, 0), tilt=-6, pupil=0.26, iris=0.78,
                  brow={1: (0.1, 0.03, -0.03), -1: (0.1, 0.03, -0.03)},
                  mouth=dict(w=0.15, cl=-0.05, cr=-0.05, up=0.0, open=0.0),
                  indicator='error'),
    'done': dict(lid_up=24, lid_lo=-28, gaze=(0, 0), tilt=0, pupil=0.42,
                 brow={1: (0.04, 0.05, 0.02), -1: (0.04, 0.05, 0.02)},
                 mouth=dict(w=0.21, cl=0.07, cr=0.07, up=-0.01, open=0.1, teeth=True, teeth_h=0.045),
                 indicator='done', hands=S['done_pose']),
}

# poses de mano (ver hands.py). .R = mano derecha del personaje (izquierda de la imagen); la manga es de la sudadera.
# done = V de paz (Sami es femenina, como Nicole); la otra pose (pulgar arriba) queda en review (done_alt).
# brazo que cuelga (lado +X): mano relajada que sale del punio hacia abajo, algo adelantada, palma hacia el muslo
REST = dict(wrist=(1.452, -0.409, -4.219), F=(0.1, -0.5, -1.0), N=(-1.0, 0.0, 0.0), side=1,
            curl=dict(index=(20, 25, 15), middle=(25, 30, 15), ring=(30, 30, 20), pinky=(30, 35, 20)),
            thumb=dict(dir=(-0.2, -1.0, -0.6), up=(-1, 0, 0), curl=(10, 10)), arm=[(1.33, 0.2, -3.0)])


def mirror_hand(h):
    """La misma pose en el otro lado (espejo en X)."""
    m = lambda v: tuple(np.asarray(v, float) * [-1, 1, 1])
    return dict(h, wrist=m(h['wrist']), F=m(h['F']), N=m(h['N']), side=-h['side'], arm=[m(a) for a in h['arm']],
                thumb=dict(h['thumb'], dir=m(h['thumb']['dir']), up=m(h['thumb']['up'])))


REST_R = mirror_hand(REST)
HAND_POSES = {
    # V de paz vertical junto a la mejilla (fuera de la cara, sin tapar el ojo), palma a camara; anular y menique
    # recogidos bajo el pulgar
    'peace': dict(R=dict(wrist=(-1.3, -0.95, -0.95), F=(-0.05, -0.1, 1.0), N=(0.0, 1.0, 0.0), side=-1,
                         curl=dict(index=(0, 4, 4), middle=(0, 4, 4), ring=(80, 95, 60), pinky=(85, 95, 60)),
                         splay=dict(index=15, middle=-11, ring=-4, pinky=-10),
                         thumb=dict(dir=(-0.75, -0.65, 0.3), up=(0.3, -1, 0.3), curl=(15, 20)),
                         arm=[(-1.75, -1.0, -2.9), (-1.5, -1.22, -1.65)]),
                  L=REST),
    # pulgar arriba junto a la barbilla (review): puno cerrado, pulgar vertical, antebrazo en diagonal hacia dentro
    'thumbs': dict(R=dict(wrist=(-1.02, -1.3, -0.98), F=(0.55, -0.35, 0.75), N=(-0.3, -0.9, -0.2), side=-1,
                          curl=dict(index=(88, 96, 70), middle=(90, 98, 70), ring=(90, 98, 70), pinky=(88, 96, 70)),
                          thumb=dict(dir=(-0.1, -0.15, 1.0), up=(-0.2, -1.0, 0.12), curl=(2, 4)),
                          arm=[(-1.85, -0.75, -3.0), (-1.6, -0.85, -1.95)], rib=0.0),
                   L=REST),
}
# codo del brazo que cuelga (lado +X, el otro en espejo); en las poses de mano el codo sale de la mano: antebrazo
# recto a lo largo de F (muneca recta), de FOREARM de largo
HANG_ELBOW = (1.33, 0.2, -3.0)
FOREARM = 1.45
REVIEW_EXPR = {'done_alt': dict(EXPR['done'], shape='done', hands='thumbs')}
ICON_CAM = {'peace': dict(height=3.15, center=(-0.22, -0.02)), 'thumbs': dict(height=3.0, center=(-0.12, -0.05))}



# ---------------------------------------------------------------- pelo
# Pelo con el sistema de pelo de Blender (misma tecnica que Alfred v6): objeto Hair Curves con ~3000 guias peinadas
# sobre el cuero cabelludo y Geometry Nodes con los nodos de pelo de Blender (procedural_hair_node_assets.blend):
# Duplicate (hijos) -> Clump (mechones agrupados) -> Noise -> Frizz -> perfil. Peinado de Sami: raya lateral a +X;
# el lado grande (-X) cae en diagonal sobre la frente (flequillo lateral) hacia la sien; el corto va hacia la oreja;
# coronilla y nuca hacia atras y abajo. Sombreado: Principled Hair BSDF (Chiang, melanina): casi negro, algo frio.
RAYA = 22.0                      # raya: a 22 grados de la vertical hacia +X (lado corto)
PART_X = math.sin(math.radians(RAYA))
HAIR_GUIDES = 3000
HAIR_PTS = 24
HAIR_GN = dict(children=22, child_radius=0.014, clump=0.6, clump_dist=0.05, tip_spread=0.003,
               noise=0.006, noise_scale=4.0, frizz=0.0015, radius=0.0019, tip_factor=0.05)
HAIR_NODE_ASSETS = ('Duplicate Hair Curves', 'Clump Hair Curves', 'Hair Curves Noise', 'Frizz Hair Curves',
                    'Set Hair Curve Profile')


def hairline_el(phi_deg):
    """Altura (elevacion, grados) del nacimiento del pelo por azimut: frente, entradas suaves, patilla, oreja, nuca."""
    k = [0, 30, 45, 58, 70, 78, 86, 98, 108, 120, 140, 180]
    e = [34, 32, 27, 18, -4, -10, 10, 13, 6, -18, -32, -38]
    return np.interp(np.abs(phi_deg), k, e)


def fringe_floor(phi_deg):
    """Hasta donde puede bajar el flequillo (elevacion, grados) delante del lado grande: por encima de las cejas."""
    return np.interp(phi_deg, [-75, -55, -30, 0, 25], [2, 8, 14, 20, 36])


def dir_angles(D):
    """Direcciones unitarias -> (azimut desde delante hacia +X, elevacion) en grados."""
    return np.degrees(np.arctan2(D[..., 0], -D[..., 1])), np.degrees(np.arcsin(np.clip(D[..., 2], -1, 1)))


def front_zone(D):
    """Peso de la zona del flequillo: delante y arriba, en el lado grande de la raya."""
    x, y, z = D[:, 0], D[:, 1], D[:, 2]
    return C.ss(-0.15, -0.6, y) * C.ss(0.15, 0.45, z) * C.ss(PART_X + 0.05, PART_X - 0.15, x)


def hair_flow(D):
    """Direccion tangente del peinado en D. Arriba, fuera de la raya (lado grande hacia -X, corto hacia +X); delante
    del lado grande, en diagonal hacia abajo y hacia la sien (flequillo); detras, hacia atras y abajo."""
    x, y, z = D[:, 0], D[:, 1], D[:, 2]
    phi, el = dir_angles(D)
    ap = np.abs(phi)
    top = C.ss(0.4, 0.85, z) * C.ss(0.55, -0.25, y)
    fr = front_zone(D)
    lat = np.where(x < PART_X, -0.55, 0.3) * np.maximum(top, fr)
    back = C.ss(-0.1, 0.55, y)
    g = np.stack([lat - 0.35 * fr, (1.0 - 0.95 * back) * (1 - fr), -0.3 - 1.2 * back - 0.45 * fr], -1)
    # sobre la oreja el pelo pasa por encima (algo hacia arriba); la patilla corta baja recta
    ear = C.ss(80, 88, ap) * C.ss(122, 110, ap) * C.ss(30, 16, el)
    g[:, 2] += 0.5 * ear
    sb = C.ss(56, 64, ap) * C.ss(84, 76, ap) * C.ss(16, 8, el)
    g = g * (1 - sb)[:, None] + np.array([0.0, 0.2, -1.0]) * sb[:, None]
    g -= D * np.sum(g * D, -1, keepdims=True)
    return C.unit(g)


def comb(D0, L):
    """Integra el campo de peinado desde cada raiz D0 una longitud L (unidades de cabeza) -> (HAIR_PTS, n, 3)."""
    n = HAIR_PTS
    out = np.empty((n,) + D0.shape)
    D = D0.copy()
    h = (L / (n - 1))[:, None]
    for k in range(n):
        out[k] = D
        D = C.unit(D + h * hair_flow(D))
    return out


def hair_guides(S, head_surf, ears_surf, rng):
    """Curvas guia: raices uniformes en la zona de pelo, cortas en lados y nuca, mas largas arriba y en el flequillo;
    volumen (tupe) junto a la raya y capas (la hebra sube con el camino recorrido). Lo que bajaria por debajo del
    nacimiento (o, en el flequillo, de fringe_floor) se acorta. -> lista de (n, 3)."""
    D = C.unit(rng.normal(size=(HAIR_GUIDES * 6, 3)))
    phi, el = dir_angles(D)
    D = D[el > hairline_el(phi) + 1.0][:HAIR_GUIDES]
    z, y = D[:, 2], D[:, 1]
    fr = front_zone(D)
    L = (0.34 + 0.32 * C.ss(0.2, 0.85, z) + 0.6 * fr) * rng.uniform(0.85, 1.1, len(D))
    P = comb(D, L)
    ph, e = dir_angles(P)
    floor = np.where((np.abs(ph) < 80) & (P[..., 1] < 0), np.minimum(hairline_el(ph), fringe_floor(ph)),
                     hairline_el(ph)) - 3.0
    below = e < floor
    first = np.where(below.any(0), below.argmax(0), HAIR_PTS - 1)
    L = np.maximum(L * first / (HAIR_PTS - 1), 0.06)
    P = comb(D, L)
    u = np.linspace(0, 1, HAIR_PTS)[:, None]
    s = u * L[None, :]
    vol = 0.2 * C.ss(0.5, 0.95, z) * C.ss(0.25, -0.7, y) + 0.07 * C.ss(0.2, 0.8, z)
    off = S['cap_off'] * 0.5 + 0.004 + 0.06 * s + vol[None, :] * C.ss(0, 0.3, u) * (1 - 0.6 * C.ss(0.3, 1.0, u))
    off[0] = -0.004
    X = C.head_points(P, S) + P * off[..., None]
    guides = []
    margin = S['cap_off'] * 0.5 + 0.004
    for i in range(X.shape[1]):
        g = X[:, i].copy()
        for _ in range(3):
            g = C.smooth_path(head_surf.push_out(g, margin), 2)
        g = head_surf.push_out(g, margin)
        # la guia que tropieza con la oreja se descarta (empujada se levantaria en vertical); las vecinas cubren
        if not np.allclose(ears_surf.push_out(g.copy(), 0.02), g):
            continue
        guides.append(g)
    return guides


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


def hair_nodes(mat, g=HAIR_GN):
    """Geometry Nodes del pelo: hijos alrededor de cada guia, mechones (clump), ruido, frizz y perfil afilado."""
    A = hair_node_assets()
    ng = bpy.data.node_groups.new('sami_hair', 'GeometryNodeTree')
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


def make_hair_curves(name, guides, mat, parent):
    cv = bpy.data.hair_curves.new(name)
    cv.add_curves([len(g) for g in guides])
    cv.position_data.foreach_set('vector', np.concatenate(guides).astype(np.float32).ravel())
    cv.materials.append(mat)
    ob = bpy.data.objects.new(name, cv)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    ob.modifiers.new('hair', 'NODES').node_group = hair_nodes(mat)
    return ob


def mat_hair_strands(S):
    """Principled Hair BSDF (Chiang, melanina): raiz casi negra, puntas algo menos oscuras, tinte frio muy leve
    (#1E1B2E) y brillo suave para que el pelo oscuro se lea con volumen."""
    nb = C.NB('hair_strands')
    info = nb.node('ShaderNodeHairInfo')
    h = nb.node('ShaderNodeBsdfHairPrincipled', model='CHIANG', parametrization='MELANIN')
    x = info.outputs['Intercept']
    nb.put(h.inputs['Melanin'], nb.maprange(x, 0.0, 1.0, *S['hair_melanin']))
    nb.put(h.inputs['Melanin Redness'], nb.maprange(x, 0.0, 1.0, *S['hair_redness']))
    h.inputs['Tint'].default_value = S['hair_tint']
    for k, v in (('Roughness', 0.34), ('Radial Roughness', 0.45), ('Coat', 0.12), ('IOR', 1.55),
                 ('Offset', math.radians(2.0)), ('Random Roughness', 0.2), ('Random Color', 0.06)):
        h.inputs[k].default_value = v
    nb.put(h.inputs['Random'], info.outputs['Random'])
    nb.nt.links.new(h.outputs[0], nb.out.inputs['Surface'])
    return nb.mat


def build_hair_cap(S):
    """Cuero cabelludo bajo las curvas: capa fina oscura (vetas en el sentido del peinado) del nacimiento a la
    coronilla, donde nacen las guias; el borde se funde a transparente (atributo capfade) para un nacimiento suave."""
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
    # mismo tono que la raiz de las hebras: lo que asome entre ellas se lee como sombra del pelo
    base = S['hair_base']
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


def build_ears(S, head_surf):
    out = []
    for s in (-1, 1):
        loc, nor = head_surf.ray((s * 3.0, 0.06, -0.17), (-s, 0.0, 0.0))
        ax = C.unit(np.array([s * 1.0, -0.35, 0.0]))      # grosor (hacia fuera y algo hacia delante)
        az = C.unit(np.array([0.0, 0.18, 1.0]))            # alto, inclinada hacia atras
        az = C.unit(az - ax * np.dot(az, ax))
        ay = np.cross(az, ax) * s
        sp = C.sphere_part(1.0, 40, 24)
        d = np.sign(sp.v) * np.abs(sp.v) ** 0.85
        sizes = np.array([0.055, 0.12, 0.19])
        lv = d * sizes
        # concha: hueco en la cara exterior dentro del borde (helix)
        dent = 0.05 * np.exp(-((lv[:, 1] + 0.01) / 0.065) ** 2 - ((lv[:, 2] + 0.02) / 0.11) ** 2) * (lv[:, 0] > 0)
        lv[:, 0] -= dent
        center = loc + ax * 0.03 + np.array([0.0, 0.02, 0.0])
        sp.v = center + lv[:, 0:1] * ax + lv[:, 1:2] * ay + lv[:, 2:3] * az
        if s < 0:
            sp.f = sp.f[:, ::-1]
        out.append(sp)
    return C.Part.join(out)




# ---------------------------------------------------------------- cuerpo
# Torso y mangas de la sudadera como UNA superficie: campo de distancia en una rejilla de voxeles con union suave de
# torso (pecho mas ancho que la cintura, trapecio que cae del cuello al hombro), deltoides y brazos (tubos de radio
# variable que nacen dentro del deltoides: sin costura de bola). Los pliegues son desplazamientos del campo y la malla
# sale de openvdb (convertToQuads). Hay una variante por pose de mano (cambia el brazo derecho); el izquierdo cuelga.
VOX = 0.022
BOX = ((-2.35, -1.65, -4.25), (2.35, 1.25, -0.55))
DELTOID = ((1.0, 0.17, -1.84), (0.29, 0.31, 0.35))     # centro y semiejes (+X; el otro en espejo)
ARM_ROOT = (0.84, 0.17, -1.74)                          # raiz del tubo del brazo (+X)
ARM_R = (0.27, 0.235, 0.17)                               # radio de la manga en hombro, codo y punio
CUFF_LEN, CUFF_R = 0.28, 0.2


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0.0, 1.0)
    return b * (1 - h) + a * h - k * h * (1 - h)


def smax(a, b, k):
    return -smin(-a, -b, k)


def torso_sdf(S, X, Y, Z):
    """Torso: seccion superelipse cuyo ancho y fondo cambian con la altura (pecho > cintura, algo de busto) y tapa
    superior con la caida del trapecio; la union de tapa y pared redondea el hombro. Pliegues: caida bajo el pecho,
    diagonales desde la axila y el bolsillo canguro."""
    ax, dy = np.abs(X), Y - S['torso_y']
    zk = [-4.3, -3.0, -2.15, -1.6, -1.0]
    a = np.interp(Z, zk, [0.95, 0.86, 0.96, 0.93, 0.85])
    b = np.where(dy < 0, np.interp(Z, zk, [0.62, 0.6, 0.76, 0.64, 0.52]), np.interp(Z, zk, [0.62, 0.58, 0.66, 0.6, 0.5]))
    n = S['torso_n']
    r = ((ax / a) ** n + (np.abs(dy) / b) ** n) ** (1 / n)
    d = (r - 1) * np.minimum(a, b)
    top = S['torso_zn'] - S['shoulder_drop'] * C.ss(0.38, 1.1, ax) - 0.16 * (dy / 0.7) ** 2
    d = smax(d, Z - top, 0.24)
    d = smax(d, -4.2 - Z, 0.05)
    front = C.ss(0.1, -0.3, dy)
    drape = 0.016 * np.sin(ax * 8.5 + Z * 2.2) * C.ss(-1.95, -2.6, Z)
    pit = np.exp(-((ax - 0.82) / 0.24) ** 2 - ((Z + 2.08) / 0.3) ** 2) * front
    diag = 0.022 * np.sin(17 * (0.8 * ax - 0.6 * Z)) * pit
    pocket = (1 - C.ss(0.44, 0.52, ax)) * C.ss(-2.82, -2.76, Z) * (1 - C.ss(-2.2, -2.14, Z)) * front
    d = d - drape - diag - 0.018 * pocket
    # abertura del cuello (el cuello entra en ella y la capucha plegada la rodea)
    hole = np.maximum(np.hypot(X, Y - S['neck_y']) - S['neck_hole'], -1.65 - Z)
    return smax(d, -hole, 0.04)


def ellipsoid_sdf(X, Y, Z, c, R):
    q = np.stack([(X - c[0]) / R[0], (Y - c[1]) / R[1], (Z - c[2]) / R[2]], -1)
    return (np.linalg.norm(q, axis=-1) - 1) * min(R)


def arm_path(S, pts):
    """Hombro -> codo -> fin de manga: polilinea suavizada con su radio por punto (ARM_R)."""
    path, rad = [], []
    for i in range(len(pts) - 1):
        for t in np.linspace(0, 1, 10, endpoint=False):
            path.append(pts[i] * (1 - t) + pts[i + 1] * t)
            rad.append(ARM_R[i] * (1 - t) + ARM_R[i + 1] * t)
    path.append(pts[-1])
    rad.append(ARM_R[-1])
    return C.smooth_path(np.array(path), 3), np.array(rad)


def arm_sdf(Q, P, R):
    """Tubo de radio variable por P (radios R) en los puntos Q (n, 3), con pliegues de tela: ondas suaves por toda la
    manga, anillos diagonales en el codo y fruncido sobre el punio."""
    best = np.full(len(Q), np.inf)
    idx, tt = np.zeros(len(Q), int), np.zeros(len(Q))
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    for i in range(len(P) - 1):
        ba = P[i + 1] - P[i]
        t = np.clip((Q - P[i]) @ ba / (ba @ ba), 0, 1)
        d = np.linalg.norm(Q - P[i] - t[:, None] * ba, axis=1) - (R[i] + t * (R[i + 1] - R[i]))
        m = d < best
        best[m], idx[m], tt[m] = d[m], i, t[m]
    T = C.unit(P[idx + 1] - P[idx])
    q = Q - (P[idx] + tt[:, None] * (P[idx + 1] - P[idx]))
    ref = C.unit(np.cross(T, np.array([0.0, -1.0, 0.0])))
    ang = np.arctan2(np.sum(q * np.cross(T, ref), 1), np.sum(q * ref, 1))
    s = arc[idx] + tt * seg[idx]
    u, se = s / arc[-1], arc[10]
    soft = (0.011 * C.ss(0.12, 0.3, u) * (1 - C.ss(0.8, 0.9, u)) * (0.6 + 0.4 * np.sin(3.1 * s + 1.7 * ang))
            * np.sin(2 * np.pi * s / 0.3 + 2.0 * ang + 0.8 * np.sin(4 * s)))
    elbow = (0.016 * np.exp(-((s - se) / 0.26) ** 2) * np.sin(2 * np.pi * s / 0.17 + 2.6 * ang + 0.9 * np.sin(5 * s))
             * (0.25 + 0.75 * np.maximum(np.cos(ang - 0.6), 0)))
    bunch = 0.012 * C.ss(0.62, 0.74, u) * (1 - C.ss(0.88, 0.94, u)) * np.sin(2 * np.pi * s / 0.13 + 1.8 * ang) * (0.4 + 0.6 * np.maximum(np.sin(ang + 1.0), 0))
    return best - soft - elbow - bunch


def sleeve_end(S, hand):
    """Fin de la manga de una pose de mano (como hands.py: muneca - F*0.12*escala) y su eje."""
    F = C.unit(np.asarray(hand['F'], float))
    return np.asarray(hand['wrist'], float) - F * 0.12 * S['hand_scale'], F


def arm_points(S, side, hand, elbow):
    """Hombro (raiz dentro del torso, bajo el deltoides: la tapa del tubo queda enterrada) -> codo -> fin de la manga (algo dentro del punio)."""
    c = np.array(ARM_ROOT) * np.array([side, 1, 1])
    end, F = sleeve_end(S, hand)
    return [c, np.asarray(elbow, float), end - F * 0.2]


def taubin(v, f, it=4, lam=0.5, mu=-0.53):
    e = np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 3]], f[:, [3, 0]]])
    cnt = np.zeros(len(v))
    np.add.at(cnt, e[:, 0], 1)
    np.add.at(cnt, e[:, 1], 1)
    cnt = np.maximum(cnt, 1)[:, None]
    for _ in range(it):
        for k in (lam, mu):
            acc = np.zeros_like(v)
            np.add.at(acc, e[:, 0], v[e[:, 1]])
            np.add.at(acc, e[:, 1], v[e[:, 0]])
            v = v + k * (acc / cnt - v)
    return v


def sdf_mesh(Fd, lo):
    import openvdb
    g = openvdb.FloatGrid(1.0)
    g.copyFromArray(np.ascontiguousarray(Fd, np.float32))
    pts, quads = g.convertToQuads(0.0)
    f = quads.astype(np.int64)
    return C.Part(taubin(np.asarray(lo) + pts.astype(float) * VOX, f), f)


def build_cuff(S, hand):
    """Punio acanalado y borde enrollado al final de la manga (el tubo de la manga acaba dentro)."""
    end, F = sleeve_end(S, hand)
    N = np.asarray(hand['N'], float)
    N = C.unit(N - F * np.dot(N, F))
    P = end + F[None] * np.linspace(-CUFF_LEN, 0, 8)[:, None]
    rad = np.full(8, CUFF_R)
    band = C.sweep(P, np.tile(N, (8, 1)), rad, rad * 0.95, 64, mod=lambda i, t: 1 + 0.045 * np.cos(28 * t))
    ring = []
    W = C.unit(np.cross(F, N))
    H = np.cross(W, F)
    for t in np.linspace(0, C.TAU, 48, endpoint=False):
        ring.append(end + (W * math.cos(t) + H * math.sin(t) * 0.95) * CUFF_R * 1.03)
    rim = C.sweep(np.array(ring), np.tile(F, (48, 1)), np.full(48, 0.035), np.full(48, 0.035), 10, closed=True)
    return C.Part.join([band, rim])


def build_body(S, poses):
    """-> {None: Part (los dos brazos cuelgan), pose: Part (brazo derecho de la pose)}; cada una con sus punios."""
    lo, hi = np.array(BOX[0]), np.array(BOX[1])
    shape = tuple(int(round(k)) + 1 for k in (hi - lo) / VOX)
    X, Y, Z = np.meshgrid(*(lo[k] + VOX * np.arange(shape[k]) for k in range(3)), indexing='ij')
    base = torso_sdf(S, X, Y, Z)
    for s in (-1, 1):
        c = np.array(DELTOID[0]) * np.array([s, 1, 1])
        base = smin(base, ellipsoid_sdf(X, Y, Z, c, DELTOID[1]), 0.28)
    G = np.stack([X, Y, Z], -1)
    del X, Y, Z

    def add_arm(Fd, side, hand, elbow):
        P, R = arm_path(S, arm_points(S, side, hand, elbow))
        a = np.floor((P.min(0) - 0.5 - lo) / VOX).astype(int).clip(0)
        b = np.ceil((P.max(0) + 0.5 - lo) / VOX).astype(int).clip(None, np.array(shape) - 1) + 1
        sub = G[a[0]:b[0], a[1]:b[1], a[2]:b[2]]
        d = arm_sdf(sub.reshape(-1, 3), P, R).reshape(sub.shape[:3])
        # union suave solo junto al hombro: el antebrazo que pasa cerca del pecho no se pega a el
        k = 0.02 + 0.14 * C.ss(0.6, 0.2, np.linalg.norm(sub - P[0], axis=-1))
        Fd[a[0]:b[0], a[1]:b[1], a[2]:b[2]] = smin(Fd[a[0]:b[0], a[1]:b[1], a[2]:b[2]], d, k)
        return Fd

    left = add_arm(base, 1, REST, HANG_ELBOW)
    out = {}
    for pname, hand in [(None, REST_R)] + [(k, v['R']) for k, v in poses.items()]:
        if pname is None:
            elbow = np.array(HANG_ELBOW) * [-1, 1, 1]
        else:
            end, F = sleeve_end(S, hand)
            elbow = end - F * FOREARM
        Fd = add_arm(left.copy(), -1, hand, elbow)
        body = sdf_mesh(Fd, lo)
        cuffs = [build_cuff(S, hand), build_cuff(S, REST)]
        out[pname] = (body, C.Part.join(cuffs), sleeve_end(S, hand)[0])
    return out


# ---------------------------------------------------------------- ropa y accesorios

def sami_mats(S):
    return dict(hoodie=mat_cotton('hoodie', S['hoodie']), string=C.mat_flat('string', S['string'], rough=0.45, coat=0.1),
                earbud=C.mat_flat('earbud', L('#f4f4f6'), rough=0.2, coat=0.8),
                hair_cap=mat_hair_cap(S))


def build_hood(S, body):
    """Capucha plegada como rodete alrededor del cuello (asentada con push_out contra el cuerpo) y dos cordones que
    caen por delante."""
    coll = C.Surface(body)
    nu, nv = 200, 14
    ph = np.radians(np.linspace(-180, 180, nu, endpoint=False))
    t = np.linspace(0, 1, nv)
    Ph, T = np.meshgrid(ph, t, indexing='ij')
    # de la tapa del cuerpo sube y se cierra contra el cuello (sin hueco entre capucha y cuello)
    R = S['hood_r'] * (1 - T ** 2) + (S['neck_r'] + 0.025) * T ** 2 + 0.05 * np.sin(np.pi * T)
    # el borde inferior se asienta sobre la tapa del cuerpo (rayo hacia abajo por columna)
    z0 = np.array([coll.ray((S['hood_r'] * math.sin(p), S['neck_y'] - S['hood_r'] * math.cos(p), 0.0),
                            (0.0, 0.0, -1.0))[0][2] + 0.012 for p in ph])[:, None]
    Z = z0 + (S['hood_z'][1] - z0) * T
    rim = np.stack([R * np.sin(Ph), S['neck_y'] - R * np.cos(Ph), Z], -1)
    rim_p = grid_part(rim, (4.0, 4.0), closed_u=True)
    strings = []
    y_front = S['neck_y'] - S['hood_r'] - 0.03
    for s in (-1, 1):
        E = np.stack([np.full(12, s * 0.1), np.full(12, y_front), np.linspace(S['hood_z'][0], -1.95, 12)], -1)
        E = coll.push_out(E, 0.03, start=0)
        E = C.smooth_path(np.asarray(E), 2, keep_root=False)
        ctr = np.stack([np.zeros(len(E)), np.full(len(E), S['neck_y']), E[:, 2]], -1)
        strings.append(C.sweep(E, C.unit(E - ctr), np.full(len(E), 0.012), np.full(len(E), 0.012), 8))
    return rim_p, C.Part.join(strings)


def build_earbuds(S, head_surf):
    """Auriculares: una capsula blanca en cada oido, asomando por delante de la oreja (mismo anclaje que las orejas)."""
    out = []
    for s in (-1, 1):
        loc, nor = head_surf.ray((s * 3.0, 0.06, -0.17), (-s, 0.0, 0.0))
        sp = C.sphere_part(1.0, 24, 14)
        sp.v = sp.v * 0.05 + loc + np.asarray(nor) * 0.035
        out.append(sp)
    return C.Part.join(out)


def build(S):
    root = C.empty('sami')
    F = studio.build_face(S, EXPR, root, sami_mats)
    head, head_surf, skin, mats = F['head'], F['head_surf'], F['skin'], F['mats']
    ears = build_ears(S, head_surf)
    C.make_object('head_ears', ears, skin, root)
    earbuds = build_earbuds(S, head_surf)
    C.make_object('earbuds', earbuds, mats['earbud'], root)

    # cuerpo: una variante por pose de mano (None = brazos colgando); el resto de la ropa se ajusta a la de None
    bodies = build_body(S, HAND_POSES)
    body = bodies[None][0]
    rim, strings = build_hood(S, body)
    C.make_object('hood_rim', rim, mats['hoodie'], root)
    C.make_object('hood_strings', strings, mats['string'], root)
    neck = C.build_neck(S)
    C.make_object('neck', neck, skin, root)

    rng = np.random.default_rng(11)
    cap = build_hair_cap(S)
    C.make_object('hair_cap', cap, mats['hair_cap'], root, colors=True, colname='capfade')
    guides = hair_guides(S, head_surf, C.Surface(ears), rng)
    hair_ob = make_hair_curves('hair_curves', guides, mat_hair_strands(S), root)
    locks = hair_proxy(guides)

    hand_parts = []
    frng = np.random.default_rng(23)
    hands = studio.build_hands(S, HAND_POSES, mats, root, frng, mats['hoodie'], None, hand_parts)
    # estados sin gesto: las dos manos relajadas al final de las mangas que cuelgan (se ven en las vistas de review)
    hands[None] = studio.build_hands(S, {'idle': dict(R=REST_R, L=REST)}, mats, root, frng, mats['hoodie'])['idle']
    # las mangas son las del cuerpo: fuera las de build_hands
    for objs in hands.values():
        for ob in [o for o in objs if o.name.startswith('sleeve')]:
            objs.remove(ob)
            bpy.data.objects.remove(ob)
    hand_parts = [(n, p) for n, p in hand_parts if n.startswith('hand')]
    for pname, (bp, cuffs, _) in bodies.items():
        ob = C.make_object('hoodie' if pname is None else f'hoodie_{pname}', C.Part.join([bp, cuffs]), mats['hoodie'],
                           root)
        hands.setdefault(pname, []).append(ob)

    # chequeo de interpenetracion: cuerpo (cada variante), capucha, cordones, cuello, cabeza, orejas y pelo; manos
    # contra todo menos la punta de las mangas (la muneca entra en el punio)
    cloth = dict(hoodie=body, rim=rim, strings=strings, neck=neck, head=head, ears=ears, hair_cap=cap, hair_locks=locks)
    pairs = [(a, cloth[a], b, cloth[b]) for a, b in (
        ('rim', 'neck'), ('rim', 'hoodie'), ('rim', 'head'), ('rim', 'hair_locks'), ('strings', 'hoodie'),
        ('strings', 'rim'), ('hair_locks', 'ears'), ('hair_cap', 'ears'), ('hair_locks', 'head'),
        ('hair_locks', 'hoodie'))]
    others = ('rim', 'strings', 'neck', 'head', 'ears', 'hair_locks')
    for pname, (bp, cuffs, end) in bodies.items():
        tag = 'none' if pname is None else pname
        pairs += [(f'hoodie_{tag}', bp, b, cloth[b]) for b in others if pname is not None or b != 'rim']
        pairs += [(f'cuffs_{tag}', cuffs, b, cloth[b]) for b in others]
        if pname is None:
            continue
        fc = bp.v[bp.f].mean(1)
        keep = np.minimum(np.linalg.norm(fc - end, axis=1), np.linalg.norm(fc - sleeve_end(S, REST)[0], axis=1)) > 0.5
        cut = C.Part(bp.v, bp.f[keep])
        hn = 'hand' if pname == S['done_pose'] else f'hand_{pname}'
        for hname, part in hand_parts:
            if hname.split('.')[0] == hn:
                pairs += [(hname, part, f'hoodie_{tag}', cut)] + [(hname, part, b, cloth[b]) for b in others]
    C.check_overlaps(pairs)

    ind_root, ind = studio.build_indicator_set(S, mats)
    arm = studio.build_rig('sami', root, F['eyes'], HEAD_PARTS)
    # build_rig solo cuelga mallas del hueso head: el objeto de curvas se cuelga aqui
    mw = hair_ob.matrix_world.copy()
    hair_ob.parent, hair_ob.parent_type, hair_ob.parent_bone = arm, 'BONE', 'head'
    bpy.context.view_layer.update()
    hair_ob.matrix_world = mw
    studio.organize(GROUPS)
    return dict(root=root, head_surf=head_surf, eyes=F['eyes'], mats=mats, pupil=F['pupil'], iris=F['iris'], ind=ind,
                ind_root=ind_root, brows=F['brows'], mouth=F['mouth'], arm=arm, hands=hands)


HEAD_PARTS = ('head', 'eye', 'brow', 'mouth', 'hair')
GROUPS = [('rig', ('sami', 'sami_rig')), ('eyes', ('eye',)), ('brows', ('brow',)), ('mouth', ('mouth_',)),
          ('hair', ('hair_',)), ('head', ('head',)), ('hands', ('hand', 'nails')),
          ('body', ('hoodie', 'hood', 'neck')), ('audio', ('earbud',)), ('indicators', ('ind',))]


studio.run('sami', S, EXPR, build, review_expr=REVIEW_EXPR, icon_cam=ICON_CAM)
