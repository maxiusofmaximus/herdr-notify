"""Alfred (orquestador, LEAD) en Blender/Cycles: pelo corto canoso con raya, camisa, chaleco y pajarita dorada.

Uso (desde la raiz del repo):
  blender -b --factory-startup -P tooling/avatars3d/blender/alfred.py -- [--out DIR] [--expr a,b] [--quick]
       [--review] [--samples N] [--closeup] [--view yaw:cx:cz:alto[;...]]
Mismas salidas que nicole.py (alfred-<expr>.png 512, -128, -64, -48, -32, tira y review/). Render, luz, camara,
cara, manos, rig y salida son comunes (studio.py); aqui van la spec, el pelo y la ropa.
"""
import math
import os
import sys

import bpy
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import character as C  # noqa: E402
import hands as H  # noqa: E402
import studio  # noqa: E402

L = C.lin
S = dict(
    # cabeza: ovalada (mas alta y estrecha que Nicole), barbilla algo mas marcada, nariz de boton
    head_w=0.94, head_front=0.9, head_back=0.98, head_top=1.03, head_bot=0.95, jaw_taper=0.29,
    head_bumps=[
        ((0.55, -0.75, -0.22), 0.06, 0.3, True),    # mejillas (mas marcadas: edad)
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
        ((0.17, -0.95, -0.4), -0.012, 0.03, True),   # surco nasogeniano (junto a la nariz)
        ((0.2, -0.92, -0.5), -0.01, 0.03, True),     # surco nasogeniano bajo
    ],
    skin=L('#f3cda8'), blush=L('#e39a85'), nose_tip=L('#e69a86'), blush_r=0.24, blush_a=0.32, nose_a=0.5,
    nail=L('#efc3aa'),
    # ojos: redondos, iris gris azulado, pestanas cortas sin rabillo
    eye_x=0.36, eye_z=-0.1, eye_r=0.24, eye_depth=0.75, eye_yaw=9.0, eye_tilt=0.0,
    iris_ang=0.7, pupil=0.4,
    sclera=L('#fbf6f1'), sclera_edge=L('#e3cfca'), iris_in=L('#8aa3b8'), iris_mid=L('#4a6680'),
    iris_out=L('#25384c'), iris_ring=L('#0d1620'), iris_glow=L('#b4cde0'),
    catchlights=[(-0.36, 0.42, 0.05), (0.3, -0.22, 0.024)],
    lash_w=0.026, lash_flicks=[],
    lash=L('#3a3330'), lid_thick=0.018, crease_gap=13, crease_w=0.013, lid_fillet=0.09,
    # cejas gruesas, suaves (forma v3 de Nicole) y grises algo mas oscuras que el pelo para que se lean
    brow_pts=[(0.09, 0.2), (0.34, 0.285), (0.62, 0.235)], brow_w=0.066, brow=L('#8f9298'),
    brow_light=L('#c3c6cb'), brow_dark=L('#666a71'), brow_hair=0.0032, brow_hair_len=0.016,
    lip_up_h=0.022, lip_lo_h=0.034, lip_up_lift=0.014, lip_lo_lift=0.022,
    mouth_center=(0.0, -0.53), lip=L('#c98e80'), lipline=L('#6a3a30'), cavity=L('#4a1418'),
    teeth=L('#fbf6ef'), tongue=L('#d9646e'),
    # pelo corto canoso: mechones agrupados (cinta) con raya al lado; casquete con borde fundido debajo
    hair_axis_y=0.12, hair_base=L('#9ca3af'), hair_dark=L('#50555d'), hair_spec=L('#f4f2ee'),
    hair_ramp=[(0.0, (0.56, 0.57, 0.6, 1)), (0.3, (0.8, 0.8, 0.82, 1)), (0.7, (0.97, 0.97, 0.96, 1)),
               (1.0, (1.08, 1.07, 1.04, 1))],
    # hebras (Principled Hair BSDF, color directo): raiz gris oscuro, plata y puntas claras algo calidas
    hair_strand_ramp=[(0.0, (0.07, 0.072, 0.08, 1)), (0.3, (0.24, 0.245, 0.26, 1)), (0.65, (0.38, 0.38, 0.385, 1)),
                      (1.0, (0.5, 0.47, 0.42, 1))],
    cap_off=0.014,
    # cuerpo: cuello y hombros de hombre, camisa blanca, chaleco gris marengo, pajarita dorada
    neck_y=0.12, neck_r=0.34, neck_z=(-1.6, -0.55), torso_zn=-1.25, torso_zb=-3.6,
    # pajarita: #B7791F algo desaturado y mas oscuro (tela tejida, no satin)
    shirt=L('#f3f0e8'), vest=L('#3a3d48'), vest_piping=L('#2a2c34'), bowtie=L('#9b6e2e'), brass=L('#c9a04a'),
    mono_off=0.1, mono_r=0.2, mono_chain_end=(-0.42, -0.6, -1.55),
    vest_off=0.045, vest_top_z=-1.3, vest_strap=0.08, vest_v_top=0.36, vest_v_z=-2.12,
    lapel_w=0.16, vest_arm_c=96.0, vest_arm_w=40.0, vest_arm_zb=-2.3,
    collar_r=0.375, collar_z=(-1.34, -0.99),
    # indicadores (mismo sitio y escala que Nicole) en el color del agente
    accent=L('#b7791f'),
    indicator_root=(1.1, -1.2, 0.74), indicator_scale=1.15,
    icon_indicator=((0.6, -1.05, 0.8), 0.85), indicator_at=(0.0, 0.0, 0.0),
    sparkles=[(0.0, 0.0, 0.3), (-0.36, 0.26, 0.15), (0.3, -0.36, 0.14)],
    sweat_at=(-0.86, -0.62, 0.12),
    hand_scale=1.4, done_pose='thumbs', fuzz=0,
)

# misma gramatica que Nicole; Alfred algo mas sereno (parpado algo mas bajo en neutral, sonrisa contenida)
EXPR = {
    'neutral': dict(lid_up=38, lid_lo=-44, gaze=(0, -2), tilt=0, pupil=0.4,
                    brow={1: (0, 0, 0), -1: (0, 0, 0)},
                    mouth=dict(w=0.17, cl=0.03, cr=0.03, up=0.0, open=0.0)),
    'thinking': dict(lid_up=32, lid_lo=-34, gaze=(16, -18), tilt=0, pupil=0.38,
                     brow={1: (0.06, 0.11, 0.07), -1: (-0.035, -0.03, 0.0)},
                     mouth=dict(w=0.1, cl=-0.006, cr=0.012, up=0.0, open=0.0, shift=0.06, lips=0.12),
                     indicator='thinking'),
    'working': dict(lid_up=12, lid_lo=-26, gaze=(-20, 4), tilt=12, pupil=0.4,
                    brow={1: (-0.11, -0.03, 0.04), -1: (-0.11, -0.03, 0.04)},
                    mouth=dict(w=0.1, cl=-0.004, cr=-0.004, up=0.0, open=0.0, shift=-0.02, lips=0.12),
                    indicator='working'),
    'happy': dict(lid_up=16, lid_lo=16, gaze=(0, 0), tilt=0, pupil=0.4,
                  brow={1: (0.05, 0.07, 0.03), -1: (0.05, 0.07, 0.03)},
                  mouth=dict(w=0.22, cl=0.075, cr=0.075, up=-0.01, open=0.17, teeth=True, teeth_h=0.05,
                             tongue=True),
                  indicator='happy'),
    'error': dict(lid_up=47, lid_lo=-52, gaze=(0, 0), tilt=-6, pupil=0.26, iris=0.78,
                  brow={1: (0.1, 0.03, -0.03), -1: (0.1, 0.03, -0.03)},
                  mouth=dict(w=0.14, cl=-0.03, cr=-0.03, up=0.006, open=0.0, lips=0.12),
                  indicator='error'),
    'done': dict(lid_up=28, lid_lo=-30, gaze=(0, 0), tilt=0, pupil=0.42,
                 brow={1: (0.04, 0.05, 0.02), -1: (0.04, 0.05, 0.02)},
                 mouth=dict(w=0.21, cl=0.07, cr=0.07, up=-0.01, open=0.1, teeth=True, teeth_h=0.045),
                 indicator='done', hands=S['done_pose']),
}

# done = pulgar arriba (README): puno con el dorso a camara, dedos a 85-100 grados y pulgar recto hacia arriba.
# .R = mano derecha del personaje (izquierda de la imagen); la manga es de camisa (punio liso, rib=0)
REST = studio.REST
HAND_POSES = {
    # junto a la cara, a la altura de la barbilla (se lee en 48 px)
    'thumbs': dict(R=dict(wrist=(-1.2, -1.15, -1.0), F=(0.35, -0.8, 0.45), N=(-1.0, 0.0, 0.0), side=-1,
                          curl=dict(index=(88, 96, 70), middle=(90, 98, 70), ring=(90, 98, 70), pinky=(88, 96, 70)),
                          thumb=dict(dir=(0.0, 0.0, 1.0), up=(-0.6, -0.8, 0.0), curl=(0, 0)),
                          arm=[(-1.85, -0.75, -3.0), (-1.6, -0.85, -1.95)], rib=0.0, pole=(0.5, 0.4, -1.3)),
                   L=REST),
    # delante del pecho, sobre el chaleco
    'thumbs_chest': dict(R=dict(wrist=(-0.5, -1.02, -2.02), F=(1.0, -0.2, 0.05), N=(0.0, -1.0, 0.15), side=-1,
                                curl=dict(index=(88, 96, 70), middle=(90, 98, 70), ring=(90, 98, 70),
                                          pinky=(88, 96, 70)),
                                thumb=dict(dir=(0.1, -0.05, 1.0), up=(0.0, -1.0, 0.0), curl=(0, 0)),
                                arm=[(-1.5, -1.0, -3.1), (-1.3, -1.25, -2.3)], rib=0.0,
                                pole=(0.5, 0.3, -1.4)),
                         L=REST),
}
REVIEW_EXPR = {'done_alt': dict(EXPR['done'], shape='done', hands='thumbs_chest')}
ICON_CAM = {'thumbs': dict(height=3.4, center=(-0.2, -0.26)),  # puno y punio enteros dentro del icono
            'thumbs_chest': dict(height=3.6, center=(0.0, -0.4))}


# ---------------------------------------------------------------- pelo
# Pelo con el sistema de pelo de Blender: objeto Hair Curves con ~3000 curvas guia peinadas sobre el cuero cabelludo
# (raices repartidas por la zona de pelo y crecidas siguiendo un campo de peinado: hacia atras desde la frente, raya al
# lado, abajo en la nuca) y un modificador de Geometry Nodes con los nodos de pelo que trae Blender
# (procedural_hair_node_assets.blend): Duplicate (hijos) -> Clump -> Noise (kink/ruido) -> Frizz -> perfil.
# Sombreado con Principled Hair BSDF (Chiang): raiz oscura, puntas claras y algo calidas.
RAYA = 22.0                      # raya: a 22 grados de la vertical hacia +X (lado corto)
PART_X = math.sin(math.radians(RAYA))
HAIR_GUIDES = 3000
HAIR_PTS = 24
HAIR_GN = dict(children=16, child_radius=0.013, clump=0.55, clump_dist=0.045, tip_spread=0.003,
               noise=0.006, noise_scale=4.0, frizz=0.0015, radius=0.0017, tip_factor=0.05)
HAIR_NODE_ASSETS = ('Duplicate Hair Curves', 'Clump Hair Curves', 'Hair Curves Noise', 'Frizz Hair Curves',
                    'Set Hair Curve Profile')


def hairline_el(phi_deg):
    """Altura (elevacion, grados) del nacimiento del pelo por azimut: frente, entradas, patilla corta, oreja, nuca."""
    k = [0, 22, 36, 48, 58, 70, 78, 84, 90, 100, 108, 120, 140, 180]
    e = [34, 33, 25, 22, 18, -2, -8, 14, 19, 20, 8, -18, -32, -38]
    return np.interp(np.abs(phi_deg), k, e)


def dir_angles(D):
    """Direcciones unitarias -> (azimut desde delante hacia +X, elevacion) en grados."""
    return np.degrees(np.arctan2(D[..., 0], -D[..., 1])), np.degrees(np.arcsin(np.clip(D[..., 2], -1, 1)))


def hair_flow(D):
    """Direccion tangente del peinado en D: hacia atras y algo abajo (en la nuca, abajo) y, delante y arriba, hacia
    fuera de la raya: el lado grande (-X) se abre en diagonal hacia la sien, el corto (+X) hacia la oreja."""
    x, y, z = D[:, 0], D[:, 1], D[:, 2]
    phi, el = dir_angles(D)
    ap = np.abs(phi)
    top = C.ss(0.4, 0.85, z) * C.ss(0.55, -0.25, y)
    lat = np.where(x < PART_X, -0.5, 0.25) * top
    # detras la componente hacia atras se apaga y manda la de abajo (sin sumidero en la nuca)
    back = C.ss(-0.1, 0.55, y)
    g = np.stack([lat, 1.0 - 0.95 * back, -0.3 - 1.2 * back], -1)
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
    """Curvas guia: raices uniformes en la zona de pelo, largo corto en lados y nuca y mas largo arriba, volumen
    (tupe) en la frente y capas: cada hebra sube con el camino recorrido, asi la que nace delante pasa por encima de
    las que nacen detras. Las que bajarian por debajo del nacimiento (nuca, patillas) se acortan. -> lista de (n, 3)."""
    D = C.unit(rng.normal(size=(HAIR_GUIDES * 6, 3)))
    phi, el = dir_angles(D)
    D = D[el > hairline_el(phi) + 1.0][:HAIR_GUIDES]
    z, y = D[:, 2], D[:, 1]
    L = (0.34 + 0.32 * C.ss(0.2, 0.85, z)) * rng.uniform(0.85, 1.1, len(D))
    # acorta lo que cruzaria el nacimiento (nuca, detras de la oreja, patilla)
    P = comb(D, L)
    ph, e = dir_angles(P)
    below = e < hairline_el(ph) - 3.0
    first = np.where(below.any(0), below.argmax(0), HAIR_PTS - 1)
    L = np.maximum(L * first / (HAIR_PTS - 1), 0.06)
    P = comb(D, L)
    u = np.linspace(0, 1, HAIR_PTS)[:, None]
    s = u * L[None, :]
    vol = 0.11 * C.ss(0.55, 0.95, z) * C.ss(0.2, -0.7, y) + 0.03 * C.ss(0.3, 0.8, z)
    # la raiz entra en el cuero cabelludo (no se ve el corte) y la hebra sale tumbada
    off = S['cap_off'] * 0.5 + 0.004 + 0.065 * s + vol[None, :] * C.ss(0, 0.3, u) * (1 - 0.6 * C.ss(0.3, 1.0, u))
    off[0] = -0.004
    X = C.head_points(P, S) + P * off[..., None]
    guides = []
    margin = S['cap_off'] * 0.5 + 0.004
    for i in range(X.shape[1]):
        g = X[:, i].copy()
        for _ in range(3):
            g = C.smooth_path(head_surf.push_out(g, margin), 2)
        g = head_surf.push_out(g, margin)
        # la guia que tropieza con la oreja se descarta (empujada se levanta en vertical); las vecinas cubren
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
    """Geometry Nodes del pelo: hijos alrededor de cada guia, mechones (clump), ondulacion y ruido, frizz y perfil
    (radio que se afila a la punta)."""
    A = hair_node_assets()
    ng = bpy.data.node_groups.new('alfred_hair', 'GeometryNodeTree')
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
    """Principled Hair BSDF (Chiang, color directo): degradado raiz-punta por Intercept, tono propio por hebra y
    brillo suave (rugosidad media, coat bajo)."""
    nb = C.NB('hair_strands')
    info = nb.node('ShaderNodeHairInfo')
    col = nb.ramp(info.outputs['Intercept'], S['hair_strand_ramp'])
    var = nb.ramp(info.outputs['Random'], [(0.0, (0.78, 0.78, 0.8, 1)), (1.0, (1.0, 1.0, 1.0, 1))])
    col = nb.mix(1.0, col, var, blend='MULTIPLY')
    h = nb.node('ShaderNodeBsdfHairPrincipled', model='CHIANG', parametrization='COLOR')
    nb.put(h.inputs['Color'], col)
    for k, v in (('Roughness', 0.32), ('Radial Roughness', 0.45), ('Coat', 0.05), ('IOR', 1.55),
                 ('Offset', math.radians(2.0)), ('Random Roughness', 0.25)):
        h.inputs[k].default_value = v
    nb.put(h.inputs['Random'], info.outputs['Random'])
    nb.nt.links.new(h.outputs[0], nb.out.inputs['Surface'])
    return nb.mat


def build_hair_cap(S):
    """Cuero cabelludo bajo las curvas: capa fina gris oscuro (vetas en el sentido del peinado) del nacimiento a la
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
    # gris neutro como la raiz de las hebras: lo que asome entre ellas se lee como sombra, sin tinte azul
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


def mat_suit(name, color):
    """Pano de chaleco: espiga (bandas diagonales alternas) muy sutil, lana con sheen y brillo bajo."""
    nb = C.NB(name)
    co = nb.texco().outputs['Object']
    sep = nb.node('ShaderNodeSeparateXYZ')
    nb.nt.links.new(co, sep.inputs[0])
    x, z = sep.outputs['X'], sep.outputs['Z']
    col = nb.math('FRACT', nb.math('MULTIPLY', x, 9.0))
    sgn = nb.math('SIGN', nb.math('SUBTRACT', col, 0.5))
    diag = nb.math('ADD', nb.math('MULTIPLY', z, 1.0), nb.math('MULTIPLY', nb.math('MULTIPLY', x, sgn), 0.8))
    her = nb.math('SINE', nb.math('MULTIPLY', diag, 150.0))
    her = nb.maprange(her, -1.0, 1.0, 0.0, 1.0, 'LINEAR')
    fz = nb.noise(co, 120.0, 3.0, 0.6)
    var = nb.noise(co, 6.0, 2.0)
    c = nb.mix(nb.math('MULTIPLY', her, 0.12), color, (color[0] * 1.35, color[1] * 1.35, color[2] * 1.3, 1))
    c = nb.mix(nb.math('MULTIPLY', var, 0.2), c, (color[0] * 0.8, color[1] * 0.8, color[2] * 0.85, 1))
    h = nb.math('ADD', nb.math('MULTIPLY', her, 0.5), nb.math('MULTIPLY', fz, 0.5))
    nb.principled(Base_Color=c, Roughness=0.78, Specular_IOR_Level=0.3, Sheen_Weight=0.45, Sheen_Roughness=0.5,
                  Sheen_Tint=(0.8, 0.82, 0.9, 1), Normal=nb.bump(h, 0.25, 0.005))
    return nb.mat


def mat_tie(name, color):
    """Pajarita de tela: mate, con el tejido visible (ruido fino en bump y variacion de color), sin brillo de satin."""
    nb = C.NB(name)
    co = nb.texco().outputs['Object']
    weave = nb.noise(co, 220.0, 2.0, 0.5)
    var = nb.noise(co, 9.0, 2.0)
    c = nb.mix(nb.math('MULTIPLY', var, 0.18), color, (color[0] * 0.82, color[1] * 0.8, color[2] * 0.8, 1))
    nb.principled(Base_Color=c, Roughness=0.66, Specular_IOR_Level=0.25, Sheen_Weight=0.4, Sheen_Roughness=0.5,
                  Sheen_Tint=(1, 0.9, 0.7, 1), Normal=nb.bump(weave, 0.2, 0.004))
    return nb.mat


def mat_brass(name, color):
    nb = C.NB(name)
    nb.principled(Base_Color=color, Metallic=1.0, Roughness=0.32, Coat_Weight=0.2)
    return nb.mat


def alfred_mats(S):
    return dict(shirt=mat_cotton('shirt', S['shirt']), vest=mat_suit('vest', S['vest']),
                piping=mat_suit('vest_piping', S['vest_piping']), bowtie=mat_tie('bowtie', S['bowtie']),
                brass=mat_brass('brass', S['brass']), pearl=C.mat_flat('pearl', L('#f4efe6'), rough=0.25, coat=0.6),
                hair_cap=mat_hair_cap(S))


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


def weld(part, eps=1e-5):
    """Une vertices coincidentes (costuras entre tiras de una misma pieza)."""
    key = np.round(part.v / eps).astype(np.int64)
    _, first, inv = np.unique(key, axis=0, return_index=True, return_inverse=True)
    inv = inv.ravel()
    part.v = part.v[first]
    part.f = inv[part.f]
    if part.col is not None:
        part.col = part.col[first]
    return part


# Cuerpo estilizado: torso por campo implicito (union suave de un tronco de seccion superelipse, mas ancho en el pecho
# que en la cintura, con tapa redondeada, y dos trapecios del cuello al hombro). El deltoides y el brazo son la manga
# (build_arm), que nace dentro del hombro.
BODY = dict(
    yc=0.14,
    trunk_z=[-3.8, -3.2, -2.7, -2.2, -1.8, -1.45],
    trunk_a=[0.84, 0.8, 0.84, 0.9, 0.97, 0.9],
    trunk_b=[0.52, 0.52, 0.56, 0.6, 0.58, 0.52],
    trunk_top=-1.38, trunk_round=0.42, trunk_n=2.6,
    trap=((0.22, 0.13, -1.32), (1.0, 0.15, -1.68), 0.2),
    blend=0.18,
    ray_o=-2.0, ray_el=56.0, ray_tc=0.42,
)


def smin(a, b, k):
    h = np.clip(0.5 + 0.5 * (b - a) / k, 0, 1)
    return b * (1 - h) + a * h - k * h * (1 - h)


def body_field(p, B=BODY):
    """Campo implicito del torso (<0 dentro). La distancia lateral es radial desde el eje, suficiente para los rayos."""
    x, y, z = p[..., 0], p[..., 1] - B['yc'], p[..., 2]
    A = np.interp(z, B['trunk_z'], B['trunk_a'])
    Bb = np.interp(z, B['trunk_z'], B['trunk_b'])
    n = B['trunk_n']
    rho = ((np.abs(x) / A) ** n + (np.abs(y) / Bb) ** n) ** (1 / n)
    ds = np.hypot(x, y) * (1 - 1 / np.maximum(rho, 1e-6))
    rr = B['trunk_round']
    qx, qz = ds + rr, z - B['trunk_top'] + rr
    trunk = np.hypot(np.maximum(qx, 0), np.maximum(qz, 0)) + np.minimum(np.maximum(qx, qz), 0) - rr
    a, b, r = np.array(B['trap'][0]), np.array(B['trap'][1]), B['trap'][2]
    q = np.stack([np.abs(p[..., 0]), p[..., 1], p[..., 2]], -1)
    ab = b - a
    t = np.clip(((q - a) @ ab) / (ab @ ab), 0, 1)
    trap = np.linalg.norm(q - (a + t[..., None] * ab), axis=-1) - r
    return smin(trunk, trap, B['blend'])


def torso_grid_body(S, B=BODY, nphi=480, ns=280, steps=64, rmax=2.4):
    """Rejilla (azimut, fila) del torso: rayos desde un eje interior, inclinados arriba (base del cuello y hombros) y
    horizontales en la pared (filas de z constante, como espera build_vest); se toma el ultimo cruce del campo."""
    phis = np.radians(np.linspace(-180, 180, nphi, endpoint=False))
    t = np.linspace(0, 1, ns)
    tc = B['ray_tc']
    el = np.radians(B['ray_el']) * np.clip(1 - t / tc, 0, 1) ** 1.15
    oz = np.where(t < tc, B['ray_o'], B['ray_o'] + (t - tc) / (1 - tc) * (S['torso_zb'] - B['ray_o']))
    D = np.stack([np.sin(phis)[:, None] * np.cos(el)[None], -np.cos(phis)[:, None] * np.cos(el)[None],
                  np.broadcast_to(np.sin(el)[None], (nphi, ns))], -1)
    O = np.stack([np.zeros(ns), np.full(ns, B['yc']), oz], -1)[None]
    rs = np.linspace(0, rmax, steps)
    f = np.stack([body_field(O + D * r) for r in rs], -1)          # (nphi, ns, steps)
    inside = f < 0
    last = steps - 1 - np.argmax(inside[..., ::-1], -1)               # ultimo punto dentro
    lo, hi = rs[last], rs[np.minimum(last + 1, steps - 1)]
    for _ in range(24):
        mid = 0.5 * (lo + hi)
        m = body_field(O + D * mid[..., None]) < 0
        lo, hi = np.where(m, mid, lo), np.where(m, hi, mid)
    return O + D * (0.5 * (lo + hi))[..., None]


def shirt_grid(S):
    """Torso de la camisa (rejilla de torso_grid_body) con tapeta y pliegues suaves; -> (P, N) hacia fuera y la
    rejilla sin tapeta ni pliegues (base del chaleco)."""
    P = torso_grid_body(S)
    nphi, ns = P.shape[:2]
    # el escote de la camisa queda fuera del cuello (que se ensancha en la base)
    z0 = S['neck_z'][0]
    rn = S['neck_r'] + 0.04 * C.ss(z0 + 0.3, z0, P[..., 2]) + 0.02
    dx, dy = P[..., 0], P[..., 1] - S['neck_y']
    d = np.hypot(dx, dy)
    k = np.maximum(rn / np.maximum(d, 1e-6), 1.0) * (P[..., 2] > z0 - 0.1) + (P[..., 2] <= z0 - 0.1)
    P = P.copy()
    P[..., 0], P[..., 1] = dx * k, S['neck_y'] + dy * k
    N = C.grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    base = (P, N)
    x, z = P[..., 0], P[..., 2]
    front = np.clip(-N[..., 1], 0, 1)
    # tapeta de botones al centro (solo asoma en el pico del chaleco) y pliegues diagonales suaves bajo el hombro
    plack = (C.ss(0.085, 0.07, np.abs(x)) * 0.012 + np.exp(-((np.abs(x) - 0.075) / 0.008) ** 2) * 0.004) * front
    fold = 0.012 * np.sin(np.abs(x) * 9 + z * 6) * C.ss(0.7, 0.9, np.abs(x)) * C.ss(-1.6, -2.1, z)
    P = P + N * (plack + fold)[..., None]
    N = C.grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    return P, N, base


def row_at(P, phi_deg):
    """Puntos de una fila periodica (nphi, 3) en azimuts arbitrarios (interpolacion lineal)."""
    nphi = len(P)
    fi = (np.asarray(phi_deg) + 180.0) / 360.0 * nphi
    i0 = np.floor(fi).astype(int)
    w = (fi - i0)[..., None]
    return P[i0 % nphi] * (1 - w) + P[(i0 + 1) % nphi] * w


def build_vest(S, P, N):
    """Chaleco: la rejilla de la camisa desplazada hacia fuera (vest_off) y recortada por filas: escote en pico (de
    vest_v_top en el cuello a cerrar en vest_v_z) y sisas (de vest_arm_w grados alrededor de vest_arm_c) que se abren
    bajo el hombro con la parte de arriba redondeada. Ribete en tubo en todos los bordes y botones de laton."""
    nphi, ns = P.shape[:2]
    phis = np.linspace(-180, 180, nphi, endpoint=False)
    # tirones suaves de la tela: diagonales desde los botones hacia los costados y ondas en la cintura
    ax, z = np.abs(P[..., 0]), P[..., 2]
    front = np.clip(-N[..., 1], 0, 1)
    wr = (0.006 * np.sin((ax * 0.8 - z) * 13) * C.ss(0.12, 0.3, ax) * C.ss(-1.9, -2.3, z) * C.ss(-3.6, -3.1, z)
          * front + 0.005 * np.sin(z * 20 + ax * 3) * C.ss(0.5, 0.8, ax) * C.ss(-2.6, -3.0, z))
    Q = P + N * (S['vest_off'] + wr)[..., None]
    zr = Q[0, :, 2]
    s0 = int(np.argmax(zr < S['vest_top_z']))  # el escote trasero queda por debajo de la vuelta del cuello
    rows = list(range(s0, ns))
    # escote: x del borde del pico por fila -> azimut en la mitad delantera
    xV = S['vest_v_top'] * np.clip((zr - S['vest_v_z']) / (S['torso_zn'] - S['vest_v_z']), 0, 1) ** 1.1
    half = (phis >= 0) & (phis <= 90)
    # sisa: ovalo de la correa del hombro (s1) a vest_arm_zb (bajo la axila); por debajo el chaleco cierra el costado
    s1 = s0 + int(ns * S['vest_strap'])  # correa del hombro: la sisa se abre por debajo de la primera fila
    se = int(np.argmax(zr < S['vest_arm_zb']))
    sm, hs = 0.5 * (s1 + se), 0.5 * (se - s1)
    hw = S['vest_arm_w'] * np.sqrt(np.clip(1 - ((np.arange(ns) - sm) / hs) ** 2, 0, 1))
    n1, n2 = 48, 110
    cols, pvs = [], []
    for s in rows:
        xs = Q[half, s, 0]
        pv = float(np.interp(xV[s], xs, phis[half])) if xV[s] > 0 else 0.0
        pvs.append(pv)
        aF, aB = S['vest_arm_c'] - hw[s], S['vest_arm_c'] + hw[s]
        fl = np.linspace(pv, aF, n1)
        bk = np.linspace(aB, 360 - aB, n2)
        fr = np.linspace(360 - aF, 360 - pv, n1)
        ph = np.concatenate([fl, bk, fr])
        ph = (ph + 180) % 360 - 180
        cols.append(np.concatenate([row_at(Q[:, s], ph)]))
    G = np.stack(cols, 1)  # (n1+n2+n1, rows, 3)
    segs = [G[:n1], G[n1:n1 + n2], G[n1 + n2:]]
    parts = [grid_part(g, (6.0, 6.0)) for g in segs]
    body = weld(C.Part.join(parts))
    # solapas: tira sobre el pico, nula en el cierre y ancha arriba, con el doblez (borde del pico) levantado y el
    # canto exterior casi apoyado en el chaleco
    lap = [i for i, s in enumerate(rows) if xV[s] > 0]
    u = np.linspace(0, 1, 12)
    lift = 0.008 + 0.02 * (1 - u) ** 2
    lapels, lap_edges = [], []
    for sg in (1, -1):
        L = np.empty((len(lap), len(u), 3))
        for j, i in enumerate(lap):
            s = rows[i]
            t = (zr[s] - S['vest_v_z']) / (S['vest_top_z'] - S['vest_v_z'])
            w = S['lapel_w'] * C.ss(0.0, 0.35, t) * (1 - 0.45 * C.ss(0.75, 1.0, t))
            ph = sg * (pvs[i] + np.degrees(w / 0.6) * u)
            n = C.unit(row_at(N[:, s], ph))
            L[j] = row_at(Q[:, s], ph) + n * lift[:, None]
        lapels.append(grid_part(L, (6.0, 6.0)))
        lap_edges.append(L[:, -1])
    body = C.Part.join([body] + lapels)
    # ribetes: pico + centro, sisas (borde delantero y trasero unidos arriba), escote trasero y canto de las solapas
    r = 0.017
    edges = [G[0], G[-1][:int(np.argmax(xV[rows] <= 0)) + 2]]
    open_rows = np.nonzero(hw[rows] > 0)[0]
    ia, ib = int(open_rows[0]) - 1, int(open_rows[-1]) + 2
    for a, b in ((n1 - 1, n1), (n1 + n2 - 1, n1 + n2)):
        edges.append(np.concatenate([G[a][ia:ib][::-1], G[b][ia:ib]]))
    edges.append(np.concatenate([G[:n1, 0], G[n1:n1 + n2, 0], G[n1 + n2:, 0]]))
    piping = []
    for E, rr in [(E, r) for E in edges] + [(E, 0.011) for E in lap_edges]:
        E = C.smooth_path(np.asarray(E), 2, keep_root=False)
        ctr = np.stack([np.zeros(len(E)), np.full(len(E), 0.15), E[:, 2]], -1)
        piping.append(C.sweep(E, C.unit(E - ctr), np.full(len(E), rr), np.full(len(E), rr * 0.8), 10))
    # botones de laton bajo el pico (al centro, sobre el ribete)
    buttons = []
    for zb in (S['vest_v_z'] - 0.14, S['vest_v_z'] - 0.36):
        s = int(np.argmin(np.abs(zr - zb)))
        p0 = row_at(Q[:, s], np.array([0.0]))[0]
        n0 = N[nphi // 2, s]
        bt = C.sphere_part(1.0, 24, 12)
        bt.v = bt.v * np.array([0.045, 0.045, 0.045])
        bt.v[:, 1] *= 0.35
        bt.v = bt.v + p0 + n0 * 0.03
        buttons.append(bt)
    return body, C.Part.join(piping), C.Part.join(buttons), dict(xV=xV, zr=zr)


def build_shirt_buttons(S, P, N):
    nphi = len(P)
    zr = P[0, :, 2]
    out = []
    for zb in (-1.55, -1.82):
        s = int(np.argmin(np.abs(zr - zb)))
        p0 = P[nphi // 2, s]
        bt = C.sphere_part(1.0, 20, 10)
        bt.v = bt.v * 0.028
        bt.v[:, 1] *= 0.4
        bt.v = bt.v + p0 + N[nphi // 2, s] * 0.02
        out.append(bt)
    return C.Part.join(out)


def build_collar(S, coll):
    """Cuello de camisa: pie (banda) alrededor del cuello abierto delante, vuelta que cae hacia fuera con las puntas
    delante (a los lados de la pajarita), pliegue superior en tubo y canto de la vuelta."""
    y0, r0 = S['neck_y'], S['collar_r']
    zb, zt = S['collar_z']
    nu, nv = 200, 14
    ph = np.radians(np.linspace(13, 347, nu))
    # pie cerrado (sin hueco delante: la pajarita va encima)
    phc = np.radians(np.linspace(0, 360, nu, endpoint=False))
    zz = np.linspace(zb, zt, nv)
    Ph, Z = np.meshgrid(phc, zz, indexing='ij')
    R = r0 - 0.01 * (Z - zb) / (zt - zb)
    band = np.stack([R * np.sin(Ph), y0 - R * np.cos(Ph), Z], -1)
    band_p = grid_part(band, closed_u=True)
    # vuelta: filas desde el pliegue (t=0) hasta el canto (t=1); el borde delantero baja en diagonal hasta la punta
    nt = 22
    t = np.linspace(0, 1, nt)
    leaf = np.empty((nu, nt, 3))
    rt = r0 - 0.01 + 0.016
    for j, tt in enumerate(t):
        pf = 11 + 17 * tt
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
    for _ in range(3):
        flat = leaf.reshape(-1, 3)
        flat[:] = coll.push_out(flat, 0.022, start=0)
        leaf = flat.reshape(nu, nt, 3)
        leaf[1:-1] = 0.5 * leaf[1:-1] + 0.25 * (leaf[:-2] + leaf[2:])
        leaf[:, 1:-1] = 0.5 * leaf[:, 1:-1] + 0.25 * (leaf[:, :-2] + leaf[:, 2:])
    leaf = coll.push_out(leaf.reshape(-1, 3), 0.02, start=0).reshape(nu, nt, 3)
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


def build_yoke(S, shirt_surf, z_bot=-1.6, nv=12):
    """Pechera: del borde inferior del pie del cuello baja y sale hasta meterse en la camisa, asi el cuello de camisa
    conecta continuo con el pecho (sin piel ni hueco bajo la pajarita)."""
    y0, r0 = S['neck_y'], S['collar_r']
    zb = S['collar_z'][0]
    nu = 200
    ph = np.radians(np.linspace(0, 360, nu, endpoint=False))
    rb = np.empty(nu)
    for i, a in enumerate(ph):
        d = np.array([np.sin(a), -np.cos(a), 0.0])
        loc, _ = shirt_surf.ray((0.0, y0, z_bot), d)
        rb[i] = r0 if loc is None else max(np.hypot(loc[0], loc[1] - y0) - 0.012, r0)
    # detras se queda pegada al cuello (bajo el escote trasero del chaleco); delante sale hasta la camisa
    wf = C.ss(130.0, 80.0, np.abs((np.degrees(ph) + 180) % 360 - 180))
    rb = r0 + 0.02 + (rb - r0 - 0.02) * wf
    t = np.linspace(0, 1, nv)[None, :]
    e = C.ss(0, 1, t)
    R = r0 + (rb[:, None] - r0) * e
    Z = zb + 0.002 + (z_bot - zb - 0.002) * t
    Z = np.broadcast_to(Z, R.shape)
    G = np.stack([R * np.sin(ph)[:, None], y0 - R * np.cos(ph)[:, None], Z], -1)
    return grid_part(G, (4.0, 4.0), closed_u=True)


def build_bowtie_strap(zc=-1.13, yk=-0.43):
    """Cinta de la pajarita: del nudo hacia atras hasta meterse en el pie del cuello, por ambos lados."""
    parts = []
    for sx in (-1, 1):
        a = np.radians(14)
        P = np.array([(0.0, yk, zc), (sx * 0.06, -0.41, zc), (sx * 0.085, -0.33, zc),
                      (sx * 0.36 * np.sin(a), 0.12 - 0.36 * np.cos(a), zc)])
        P = C.smooth_path(np.concatenate([np.linspace(P[i], P[i + 1], 8, endpoint=False) for i in range(3)]
                                         + [P[-1:]]), 3)
        O = C.unit((P - np.array([0.0, 0.12, zc])) * np.array([1.0, 1.0, 0.0]))
        parts.append(C.sweep(P, O, np.full(len(P), 0.032), np.full(len(P), 0.008), 12))
    return C.Part.join(parts)


def build_bowtie(S):
    """Pajarita: dos alas abombadas que se estrechan hacia el nudo (pliegues en el grosor) y nudo central."""
    zc = -1.13
    yc = -0.455
    parts = []
    for sx in (-1, 1):
        n = 40
        t = np.linspace(0, 1, n)
        x = sx * (0.035 + 0.255 * t)
        P = np.stack([x, yc + 0.2 * x ** 2 + 0.01, zc + 0.012 * np.sin(np.pi * t) * sx * 0], -1)
        O = np.tile([0.0, -1.0, 0.0], (n, 1))
        # ancho vertical: estrecho en el nudo, ancho en el ala y punta redondeada
        w = 0.045 + 0.075 * C.ss(0.0, 0.7, t) ** 0.8
        tip = np.sqrt(np.clip(1 - ((t - 0.82) / 0.18).clip(0) ** 2, 1e-4, 1))  # punta cerrada (sin agujero)
        w = w * tip
        h = (0.03 + 0.012 * np.sin(np.pi * t)) * np.sqrt(tip)

        def hoff(i, th, t=t):
            # dos pliegues a lo largo del ala, mas hondos cerca del nudo
            c = np.cos(th)
            return -0.012 * (1 - t[i]) * (0.5 + 0.5 * np.cos(3 * np.pi * c)) * (np.sin(th) < 0) * 0 \
                - 0.01 * (1 - C.ss(0.0, 0.8, t[i])) * (0.5 + 0.5 * np.cos(2 * np.pi * c)) * np.maximum(-np.sin(th), 0)
        part = C.sweep(P, O, w, h, 32, expo=2.4, hoff=hoff)
        if sx < 0:
            part.f = part.f[:, ::-1]
            part.uv = part.uv[:, ::-1]
        parts.append(part)
    knot = C.sphere_part(1.0, 32, 16)
    v = np.sign(knot.v) * np.abs(knot.v) ** 0.8
    knot.v = v * np.array([0.05, 0.05, 0.062]) + np.array([0.0, yc - 0.012, zc])
    parts.append(knot)
    return C.Part.join(parts)


# brazo = manga de camisa continua: casquete del deltoides (nace dentro del hombro), brazo, codo, antebrazo y punio
ARM = dict(joint=(1.05, 0.14, -1.82), L1=0.9, L2=0.82, r_delt=0.26, r_up=0.21, r_elb=0.195, r_fore=0.185,
           r_cuff=0.165, cuff_len=0.17)
# brazo colgado (.L = +X; .R es su espejo), mano fuera de cuadro con la palma hacia el muslo
ARM_REST = dict(wrist=(1.38, -0.12, -3.62), F=(0.04, -0.12, -1.0), N=(1.0, 0.0, 0.0), side=1,
                curl=dict(index=(22, 28, 18), middle=(26, 30, 18), ring=(30, 32, 18), pinky=(34, 34, 18)),
                thumb=dict(dir=(-0.2, -1.0, -0.8), up=(1.0, -0.2, 0.0), curl=(10, 10)), arm=[(1.3, -0.1, -3.0)],
                rib=0.0, pole=(0.35, 0.5, 0.0))


def rmf(P, O0):
    """Marco sin giro a lo largo de P: O0 transportado (proyectado en el plano normal de cada tangente)."""
    T = C.unit(np.gradient(P, axis=0))
    O, o = np.empty_like(P), np.asarray(O0, float)
    for i in range(len(P)):
        o = C.unit(o - T[i] * np.dot(o, T[i]))
        O[i] = o
    return O


def ik_elbow(J, W, pole, L1, L2):
    """Codo de una cadena de dos huesos J-E-W en el plano que contiene el punto pole."""
    d = W - J
    D0 = np.linalg.norm(d)
    u = d / D0
    D = np.clip(D0, abs(L1 - L2) + 1e-3, L1 + L2 - 1e-3)
    a = (L1 ** 2 - L2 ** 2 + D ** 2) / (2 * D)
    h = math.sqrt(max(L1 ** 2 - a ** 2, 0.0))
    v = C.unit((pole - J) - u * np.dot(pole - J, u))
    return J + u * a + v * h


def build_arm(J, E, Wc, out, A=ARM):
    """Manga de camisa por el camino hombro J -> codo E -> final del punio Wc: un solo tubo con casquete redondo de
    deltoides arriba (sin costura de bola), radio que se afina hacia el codo, pliegues en codo y sobre el punio,
    punio liso con canto y gemelo. out: hacia donde mira el gemelo. -> (manga, gemelo)."""
    raw = np.concatenate([np.linspace(J, E, 40, endpoint=False), np.linspace(E, Wc, 40)])
    raw = C.smooth_path(raw, 12)
    seg = np.linalg.norm(np.diff(raw, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    Lt = arc[-1]
    a = np.linspace(0, Lt, 96)
    P = np.stack([np.interp(a, arc, raw[:, k]) for k in range(3)], -1)
    l1 = float(np.linalg.norm(E - J))
    cl = A['cuff_len']
    r = np.interp(a, [0, 0.1, 0.45, l1 - 0.1, l1 + 0.1, Lt - cl - 0.05, Lt - cl - 0.012, Lt - cl, Lt],
                  [A['r_delt'], A['r_delt'] * 0.97, A['r_up'], A['r_elb'], A['r_elb'], A['r_fore'], A['r_fore'],
                   A['r_cuff'], A['r_cuff']])
    # casquete del deltoides: media esfera sobre el arranque (hacia arriba y adentro)
    T0 = C.unit(P[1] - P[0])
    cs = np.linspace(1.0, 0.08, 12)
    cap = J - T0[None] * (A['r_delt'] * cs)[:, None]
    capr = A['r_delt'] * np.sqrt(np.maximum(1 - cs ** 2, 0.0))
    Pf = np.concatenate([cap, P])
    rf = np.concatenate([capr, r])
    af = np.concatenate([-A['r_delt'] * cs, a])
    O = rmf(Pf, out)
    # pliegues: rizos en el codo, fruncido sobre el punio y unos pocos diagonales en el brazo
    amp = (0.03 * np.exp(-((af - l1) / 0.16) ** 2) + 0.035 * np.exp(-((af - (Lt - cl - 0.07)) / 0.06) ** 2)
           + 0.012 * C.ss(0.35, 0.55, af)) * (af < Lt - cl)

    def mod(i, th):
        ai = af[i]
        return 1 + amp[i] * (0.6 * np.cos(3 * th + 9 * ai) + 0.4 * np.cos(5 * th - 13 * ai + 1.3))
    sleeve = C.sweep(Pf, O, rf, rf, 48, mod=mod)
    # canto del punio, costura donde empieza y gemelo
    T = C.unit(P[-1] - P[-2])
    ring = []
    for k, ak in ((len(P) - 1, Lt), (int(np.searchsorted(a, Lt - cl)), Lt - cl)):
        Tk = C.unit(P[min(k + 1, len(P) - 1)] - P[max(k - 1, 0)])
        W1 = C.unit(np.cross(Tk, O[len(cap) + k]))
        H1 = np.cross(W1, Tk)
        t = np.linspace(0, C.TAU, 48, endpoint=False)
        R = np.interp(ak, a, r) * 1.01
        loop = P[k] + (W1[None] * np.cos(t)[:, None] + H1[None] * np.sin(t)[:, None]) * R
        w = 0.016 if ak == Lt else 0.007
        ring.append(C.sweep(loop, np.tile(Tk, (48, 1)), np.full(48, w), np.full(48, w), 10, closed=True))
    kc = int(np.searchsorted(a, Lt - cl * 0.5))
    oc = C.unit(out - T * np.dot(out, T))
    link = C.sphere_part(1.0, 20, 10)
    v = link.v * np.array([0.04, 0.04, 0.04])
    Wl = C.unit(np.cross(T, oc))
    link.v = P[kc] + oc * (np.interp(a[kc], a, r) + 0.012) + v[:, 0:1] * T + v[:, 1:2] * Wl + v[:, 2:3] * oc * 0.4
    return C.Part.join([sleeve] + ring), link


def arm_for(pose, sx, scale):
    """Mano (hands.build_hand, sin su manga) y manga continua desde el hombro del lado sx para una pose."""
    h = H.build_hand(pose, scale)
    F = C.unit(np.asarray(pose['F'], float))
    W = np.asarray(pose['wrist'], float)
    J = np.array(ARM['joint']) * np.array([sx, 1, 1])
    Wc = W - F * 0.12 * scale
    pole = Wc - F * ARM['L2'] + np.asarray(pose.get('pole', (0.0, 0.0, 0.0)), float) * np.array([sx, 1, 1])
    E = ik_elbow(J, Wc, pole, ARM['L1'], ARM['L2'])
    out = C.unit(np.asarray(pose['N'], float))
    sleeve, link = build_arm(J, E, Wc, out)
    return h, sleeve, link


def build_arms(S, poses, mats, root, check):
    """Brazos colgados (hand_rest.*, sleeve_rest.*) y, por pose de HAND_POSES, el brazo derecho (.R, -X) levantado
    (hand[_<pose>].R, sleeve[_<pose>].R). El brazo derecho colgado solo se ve sin pose (clave None de rig['hands']).
    -> {pose | None: [objetos]}."""
    out = {None: []}

    def emit(tag, side, h, sleeve, link):
        w = h['wrist']
        for part in (h['skin'], h['nails']):
            part.v = part.v - w
        hand = C.make_object(f'hand{tag}.{side}', h['skin'], mats['skin'], root)
        C.make_object(f'nails{tag}.{side}', h['nails'], mats['nail'], hand)
        hand.location = w
        objs = [hand, C.make_object(f'sleeve{tag}.{side}', sleeve, mats['shirt'], root),
                C.make_object(f'cufflink{tag}.{side}', link, mats['brass'], root)]
        return objs + list(hand.children)

    for side, sx in (('L', 1), ('R', -1)):
        h, sleeve, link = arm_for(ARM_REST, 1, S['hand_scale'])
        if sx < 0:
            h = {k: (v.mirrored_x() if isinstance(v, C.Part) else v * np.array([-1, 1, 1])) for k, v in h.items()}
            sleeve, link = sleeve.mirrored_x(), link.mirrored_x()
        check.append((f'sleeve_rest.{side}', sleeve))
        objs = emit('_rest', side, h, sleeve, link)
        if sx < 0:
            out[None] += objs
    for pname, pose in poses.items():
        tag = '' if pname == S['done_pose'] else f'_{pname}'
        h, sleeve, link = arm_for(pose['R'], -1, S['hand_scale'])
        check += [(f'hand{tag}.R', C.Part(h['skin'].v.copy(), h['skin'].f)), (f'sleeve{tag}.R', sleeve)]
        out[pname] = emit(tag, 'R', h, sleeve, link)
    return out


def build_monocle(S, head_surf):
    """Monoculo en el ojo derecho del personaje (-X): aro fino dorado delante del ojo, sin tocar la ceja, y cadena
    que cae hasta el chaleco. -> (aro, cadena)."""
    loc, _ = head_surf.front(-S['eye_x'], S['eye_z'])
    c = loc + np.array([0.0, -1.0, 0.0]) * S['mono_off']
    R = S['mono_r']
    t = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    P = c + R * np.stack([np.cos(t), np.zeros_like(t), np.sin(t)], -1)
    O = np.tile([0.0, -1.0, 0.0], (len(t), 1))
    ring = C.sweep(P, O, np.full(len(t), 0.011), np.full(len(t), 0.011), 12, closed=True)
    # cadena: cuelga del aro (abajo, lado externo) y acaba en el chaleco, con una pequena comba
    n = 40
    u = np.linspace(0, 1, n)[:, None]
    A = c + np.array([0.0, 0.0, -R])
    B = np.array(S['mono_chain_end'])
    P2 = (1 - u) * A + u * B + np.array([0.0, -1.0, 0.0]) * 0.06 * np.sin(np.pi * u)
    O2 = np.tile([0.0, -1.0, 0.0], (n, 1))
    chain = C.sweep(P2, O2, np.full(n, 0.007), np.full(n, 0.007), 8, expo=2.0)
    return ring, chain


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


def build(S):
    root = C.empty('alfred')
    F = studio.build_face(S, EXPR, root, alfred_mats)
    head, head_surf, skin, mats = F['head'], F['head_surf'], F['skin'], F['mats']
    ears = build_ears(S, head_surf)
    C.make_object('head_ears', ears, skin, root)

    P, N, (P0, N0) = shirt_grid(S)
    shirt = grid_part(P, (4.0, 4.0), closed_u=True)
    C.make_object('shirt', shirt, mats['shirt'], root)
    C.make_object('shirt_buttons', build_shirt_buttons(S, P, N), mats['pearl'], root)
    C.make_object('neck', C.build_neck(S), skin, root)
    vest, piping, vbuttons, _ = build_vest(S, P0, N0)
    C.make_object('vest', vest, mats['vest'], root)
    C.make_object('vest_piping', piping, mats['piping'], root)
    C.make_object('vest_buttons', vbuttons, mats['brass'], root)
    collar = build_collar(S, C.Surface(C.Part.join([shirt, vest, piping])))
    C.make_object('collar', collar, mats['shirt'], root)
    yoke = build_yoke(S, C.Surface(shirt))
    C.make_object('collar_yoke', yoke, mats['shirt'], root)
    bowtie = build_bowtie(S)
    strap = build_bowtie_strap()
    C.make_object('bowtie', C.Part.join([bowtie, strap]), mats['bowtie'], root)
    mono_ring, mono_chain = build_monocle(S, head_surf)
    C.make_object('monocle', mono_ring, mats['brass'], root)
    C.make_object('monocle_chain', mono_chain, mats['brass'], root)

    rng = np.random.default_rng(11)
    cap = build_hair_cap(S)
    C.make_object('hair_cap', cap, mats['hair_cap'], root, colors=True, colname='capfade')
    guides = hair_guides(S, head_surf, C.Surface(ears), rng)
    hair_ob = make_hair_curves('hair_curves', guides, mat_hair_strands(S), root)
    locks = hair_proxy(guides)

    hand_parts = []
    hands = build_arms(S, HAND_POSES, mats, root, hand_parts)

    # chequeo de interpenetracion: ropa entre si, ropa contra cuello y cabeza, pelo contra orejas y manos contra todo
    neck = C.build_neck(S)
    cloth = dict(shirt=shirt, vest=vest, piping=C.Part.join([piping, vbuttons]), collar=collar, bowtie=bowtie, neck=neck,
                 head=head, ears=ears, hair_cap=cap, yoke=yoke, strap=strap, hair_locks=locks, monocle=mono_ring)
    pairs = [(a, cloth[a], b, cloth[b]) for a, b in (
        ('shirt', 'vest'), ('shirt', 'piping'), ('shirt', 'collar'), ('shirt', 'neck'), ('vest', 'collar'),
        ('piping', 'collar'), ('vest', 'neck'),
        ('collar', 'neck'), ('collar', 'head'), ('collar', 'bowtie'), ('bowtie', 'shirt'), ('bowtie', 'vest'), ('bowtie', 'piping'),
        ('bowtie', 'head'), ('yoke', 'neck'), ('yoke', 'vest'), ('yoke', 'piping'), ('yoke', 'bowtie'),
        ('strap', 'neck'), ('strap', 'head'), ('hair_locks', 'ears'), ('hair_cap', 'ears'), ('hair_locks', 'head'),
        ('hair_locks', 'collar'), ('monocle', 'head'), ('monocle', 'hair_locks'), ('monocle', 'ears'))]
    for hname, part in hand_parts:
        pairs += [(hname, part, b, cloth[b]) for b in ('vest', 'piping', 'collar', 'bowtie', 'neck', 'head', 'ears',
                                                       'hair_locks')]
    C.check_overlaps(pairs)

    ind_root, ind = studio.build_indicator_set(S, mats)
    arm = studio.build_rig('alfred', root, F['eyes'], HEAD_PARTS)
    # build_rig solo cuelga mallas del hueso head: el objeto de curvas se cuelga aqui
    mw = hair_ob.matrix_world.copy()
    hair_ob.parent, hair_ob.parent_type, hair_ob.parent_bone = arm, 'BONE', 'head'
    bpy.context.view_layer.update()
    hair_ob.matrix_world = mw
    studio.organize(GROUPS)
    return dict(root=root, head_surf=head_surf, eyes=F['eyes'], mats=mats, pupil=F['pupil'], iris=F['iris'], ind=ind,
                ind_root=ind_root, brows=F['brows'], mouth=F['mouth'], arm=arm, hands=hands)


HEAD_PARTS = ('head', 'eye', 'brow', 'mouth', 'hair')
GROUPS = [('rig', ('alfred', 'alfred_rig')), ('eyes', ('eye',)), ('brows', ('brow',)), ('mouth', ('mouth_',)),
          ('hair', ('hair_',)), ('head', ('head',)), ('hands', ('hand', 'nails', 'sleeve', 'cufflink')),
          ('body', ('shirt', 'vest', 'collar', 'bowtie', 'neck', 'monocle')), ('indicators', ('ind',))]


studio.run('alfred', S, EXPR, build, review_expr=REVIEW_EXPR, icon_cam=ICON_CAM)
