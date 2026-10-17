"""Conan (reviewer, seguridad) en Blender/Cycles: cara larga y ojos entornados, boina de lana gris tweed u oliva con pelo castano
en mechones debajo, chaqueta en #334155 y camisa. Lupa en el indicador de trabajo.

Uso (desde la raiz del repo):
  blender -b --factory-startup -P tooling/avatars3d/blender/conan.py -- [--out DIR] [--expr a,b] [--quick]
       [--review] [--samples N] [--closeup] [--view yaw:cx:cz:alto[;...]]
Mismas salidas que alfred.py (conan-<expr>.png 512, -128, -64, -48, -32, tira y review/). Render, luz, camara,
cara, manos, rig y salida son comunes (studio.py); aqui van la spec, el sombrero y la ropa.
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
    # cabeza: proporcion normal (algo mas corta y ancha), mandibula estrecha y nariz larga
    head_w=0.88, head_front=0.98, head_back=0.98, head_top=1.0, head_bot=0.79, jaw_taper=0.16,
    head_bumps=[
        ((0.55, -0.75, -0.22), 0.03, 0.3, True),     # mejillas magras
        ((0.36, -0.92, -0.08), -0.045, 0.2, True),   # cuencas
        ((0.0, -1.0, -0.38), 0.12, 0.085, False),    # nariz larga (puente y punta)
        ((0.0, -1.0, -0.5), 0.02, 0.05, False),      # punta
        ((0.0, -1.0, -0.22), 0.012, 0.05, False),    # dorso
        ((0.08, -1.0, -0.46), 0.016, 0.045, True),   # aletas
        ((0.045, -1.0, -0.5), -0.012, 0.022, True),  # orificios
        ((0.0, -1.0, -0.56), -0.008, 0.04, False),   # surco bajo la nariz
        ((0.0, -0.85, -0.9), 0.04, 0.22, False),     # barbilla
        ((0.3, -0.9, 0.2), 0.02, 0.2, True),         # arco de la ceja
        ((0.24, -0.9, -0.56), -0.006, 0.07, True),   # comisuras
    ],
    skin=L('#f0cfae'), blush=L('#ee8f86'), nose_tip=L('#e8a090'), blush_r=0.26, blush_a=0.5, nose_a=0.6,
    nail=L('#f2cbb0'),
    # ojos: almendrados y algo estrechos, iris gris verdoso
    eye_x=0.37, eye_z=-0.08, eye_r=0.25, eye_depth=0.75, eye_yaw=9.0, eye_tilt=0.0,
    iris_ang=0.7, pupil=0.4,
    sclera=L('#f7f1ea'), sclera_edge=L('#dccbc4'), iris_in=L('#9bb0a4'), iris_mid=L('#5b7266'),
    iris_out=L('#2c3b33'), iris_ring=L('#111a16'), iris_glow=L('#e6efe9'),
    catchlights=[(-0.36, 0.42, 0.05), (0.3, -0.22, 0.024)],
    lash_w=0.024, lash_flicks=[], lash=L('#2e2a28'), lid_thick=0.018, crease_gap=13, crease_w=0.013, lid_fillet=0.09,
    # cejas finas (pelo fino y poco espesor), mas oscuras que el tono de piel
    brow_pts=[(0.1, 0.19), (0.34, 0.25), (0.6, 0.22)], brow_w=0.05, brow=L('#3b3a42'),
    brow_light=L('#8d9097'), brow_dark=L('#333238'), brow_hair=0.0028, brow_hair_len=0.014,
    lip_up_h=0.02, lip_lo_h=0.03, lip_up_lift=0.012, lip_lo_lift=0.02,
    mouth_center=(0.0, -0.53), lip=L('#c08a7c'), lipline=L('#5e3530'), cavity=L('#4a1418'),
    teeth=L('#fbf6ef'), tongue=L('#d9646e'),
    # pelo castano con hair curves de Blender: guias + hijos (hair_children por guia), Principled Hair por melanina
    # (raiz -> punta), puntas algo mas calidas (hair_tip_tint)
    hair_axis_y=0.12, hair_base=L('#7a5538'), hair_dark=L('#3a2a20'), hair_spec=L('#a08070'),
    hair_guides=3000, hair_children=16, hair_radius=0.002, hair_melanin=(0.82, 0.55), hair_redness=0.62,
    hair_tip_tint=(1.0, 0.86, 0.72, 1),
    # cuello corto y grueso con base de trapecio (neck_flare); torso en V suave: pecho torso_a, cintura estrechada
    # waist_taper entre waist_z; linea de hombro inclinada (trapecio) del cuello a la punta del hombro en zs - drop
    neck_y=0.12, neck_r=0.39, neck_flare=0.1, neck_z=(-1.6, -0.55), torso_a=1.0, torso_b=0.74, torso_y=0.2,
    neck_ring_r=0.5, torso_zn=-1.15, torso_zs=-2.01, torso_zb=-3.6, torso_n=2.5,
    shoulder_drop=0.06, shoulder_t0=(0.45, -1.0), shoulder_t1=(0.15, -1.0),
    waist_taper=0.16, waist_z=(-2.1, -3.3), chest=0.07, back=0.06,
    # brazos: un tubo continuo de manga que nace dentro del hombro (arm_root), deltoides redondeado (arm_deltoid),
    # codo, antebrazo y punio; arm_r = radios en esos puntos de control
    arm_root=(0.45, 0.18, -1.6), arm_deltoid=(0.92, 0.18, -1.92),
    arm_r=(0.2, 0.265, 0.255, 0.23, 0.23, 0.2),
    shirt=L('#f1efea'), vest=L('#334155'), vest_piping=L('#252f3f'), brass=L('#c9b48a'), pearl=L('#f4efe6'),
    # chaqueta: cierre en V estrecha, cerrada por los lados (sin sisas: hombro y manga de la misma pieza)
    vest_off=0.05, vest_top_z=-1.31, vest_strap=0.08, vest_v_top=0.2, vest_v_z=-1.95, vest_arm_c=98.0, vest_arm_w=0.0,
    collar_r=0.41, collar_z=(-1.25, -0.87),
    # boina de lana oliva simulada con Cloth: banda inclinada (beret_band_el) a beret_band_off de la cabeza, disco de
    # radio beret_r desplazado (beret_shift) e inclinado (beret_tilt) hacia +X; beret_bend = rigidez de flexion
    hat=L('#4a5034'), hat_band=L('#33382a'), beret_r=1.08, beret_shift=0.16, beret_tilt=0.22, beret_lift=0.16,
    beret_thick=0.1, beret_dome=0.06, beret_band_off=0.075, beret_proxy_off=0.065, beret_bend=12.0, beret_frames=40,
    wool_fuzz=14000, cap_off=0.012,
    # indicadores en el color de acento del agente
    accent=L('#334155'),
    lupa_at=(0.24, 0.0, -1.6), lupa_r=0.19,
    indicator_root=(1.1, -1.2, 0.74), indicator_scale=1.15,
    icon_indicator=((0.6, -1.05, 0.8), 0.85), indicator_at=(0.0, 0.0, 0.0),
    sparkles=[(0.0, 0.0, 0.3), (-0.36, 0.26, 0.15), (0.3, -0.36, 0.14)],
    sweat_at=(-0.86, -0.62, 0.12),
    hand_scale=1.4, done_pose='thumbs', fuzz=0,
)

# gramatica de Nicole/Alfred; Conan entorna los ojos (parpado alto bajo en neutral) y cuida el ceno
EXPR = {
    'neutral': dict(lid_up=6, lid_lo=-34, gaze=(0, -2), tilt=0, pupil=0.4,
                    brow={1: (0, 0, 0), -1: (0, 0, 0)},
                    mouth=dict(w=0.15, cl=0.01, cr=0.01, up=0.0, open=0.0)),
    'thinking': dict(lid_up=20, lid_lo=-30, gaze=(16, -18), tilt=0, pupil=0.38,
                     brow={1: (0.06, 0.11, 0.07), -1: (-0.035, -0.03, 0.0)},
                     mouth=dict(w=0.11, cl=-0.012, cr=0.034, up=0.0, open=0.0, shift=0.08),
                     indicator='thinking'),
    'working': dict(lid_up=10, lid_lo=-24, gaze=(-20, 4), tilt=12, pupil=0.4,
                    brow={1: (-0.11, -0.03, 0.04), -1: (-0.11, -0.03, 0.04)},
                    mouth=dict(w=0.11, cl=-0.012, cr=-0.006, up=0.0, open=0.0, shift=-0.02),
                    indicator='working'),
    'happy': dict(lid_up=14, lid_lo=16, gaze=(0, 0), tilt=0, pupil=0.4,
                  brow={1: (0.05, 0.07, 0.03), -1: (0.05, 0.07, 0.03)},
                  mouth=dict(w=0.2, cl=0.07, cr=0.07, up=-0.01, open=0.15, teeth=True, teeth_h=0.05,
                             tongue=True),
                  indicator='happy'),
    'error': dict(lid_up=40, lid_lo=-50, gaze=(0, 0), tilt=-6, pupil=0.26, iris=0.78,
                  brow={1: (0.1, 0.03, -0.03), -1: (0.1, 0.03, -0.03)},
                  mouth=dict(w=0.14, cl=-0.03, cr=-0.03, up=0.0, open=0.0),
                  indicator='error'),
    'done': dict(lid_up=22, lid_lo=-30, gaze=(0, 0), tilt=0, pupil=0.42,
                 brow={1: (0.04, 0.05, 0.02), -1: (0.04, 0.05, 0.02)},
                 mouth=dict(w=0.19, cl=0.06, cr=0.06, up=-0.01, open=0.1, teeth=True, teeth_h=0.045),
                 indicator='done', hands=S['done_pose']),
}

# done = pulgar arriba (README): puno con el dorso a camara, dedos a 85-100 grados y pulgar recto hacia arriba.
# .R = mano derecha del personaje (izquierda de la imagen); la manga es de la chaqueta: un tubo continuo desde el hombro
# (arm_sleeve) con el codo en 'elbow' (la manga de hands.py se sustituye)
REST = studio.REST
HAND_POSES = {
    # junto a la mejilla, dentro del encuadre del icono (se lee en 48/32 px); codo junto al costado
    'thumbs': dict(R=dict(wrist=(-1.15, -1.05, -0.72), F=(0.3, -0.88, 0.2), N=(-1.0, 0.0, 0.0), side=-1,
                          curl=dict(index=(88, 96, 70), middle=(90, 98, 70), ring=(90, 98, 70), pinky=(88, 96, 70)),
                          thumb=dict(dir=(0.0, 0.0, 1.0), up=(-0.6, -0.8, 0.0), curl=(0, 0)),
                          arm=[(-1.85, -0.75, -3.0), (-1.6, -0.85, -1.95)], rib=0.0, elbow=(-1.58, -0.72, -2.2)),
                   L=REST),
    # delante del pecho, sobre la chaqueta
    'thumbs_chest': dict(R=dict(wrist=(-0.95, -1.12, -1.9), F=(1.0, -0.2, 0.05), N=(0.0, -1.0, 0.15), side=1,
                                curl=dict(index=(88, 96, 70), middle=(90, 98, 70), ring=(90, 98, 70),
                                          pinky=(88, 96, 70)),
                                thumb=dict(dir=(0.1, -0.05, 1.0), up=(0.0, -1.0, 0.0), curl=(0, 0)),
                                arm=[(-1.5, -1.0, -3.1), (-1.3, -1.25, -2.3)], rib=0.0,
                                elbow=(-1.5, -0.5, -2.8)),
                         L=REST),
}
REVIEW_EXPR = {'done_alt': dict(EXPR['done'], shape='done', hands='thumbs_chest')}
ICON_CAM = {'thumbs': dict(height=3.2, center=(-0.12, -0.1)), 'thumbs_chest': dict(height=3.6, center=(0.0, -0.4))}


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

def mat_felt(name, color):
    """Lana de boina: mate (roughness 1), sheen alto y suave (pelusilla), fibra fina en bump y jaspeado de dos tonos
    (lana cardada)."""
    nb = C.NB(name)
    co = nb.texco().outputs['Object']
    fib = nb.noise(co, 380.0, 4.0, 0.7)
    mote = nb.noise(co, 22.0, 5.0, 0.6)
    heather = nb.noise(co, 140.0, 2.0, 0.5)
    c = nb.mix(nb.math('MULTIPLY', mote, 0.35), (color[0] * 0.85, color[1] * 0.85, color[2] * 0.85, 1),
               (color[0] * 1.2, color[1] * 1.2, color[2] * 1.15, 1))
    c = nb.mix(nb.math('MULTIPLY', heather, 0.18), c, (color[0] * 1.25, color[1] * 1.22, color[2] * 1.15, 1))
    h = nb.math('ADD', nb.math('MULTIPLY', fib, 0.7), nb.math('MULTIPLY', heather, 0.3))
    nb.principled(Base_Color=c, Roughness=1.0, Specular_IOR_Level=0.04, Sheen_Weight=0.45, Sheen_Roughness=0.45,
                  Sheen_Tint=(min(1, color[0] * 3), min(1, color[1] * 3), min(1, color[2] * 3), 1),
                  Normal=nb.bump(h, 0.6, 0.008))
    return nb.mat


def mat_fuzz(name, color):
    nb = C.NB(name)
    nb.principled(Base_Color=(color[0] * 1.1, color[1] * 1.1, color[2] * 1.05, 1), Roughness=1.0,
                  Specular_IOR_Level=0.0, Sheen_Weight=0.5)
    return nb.mat


def mat_brass(name, color):
    nb = C.NB(name)
    nb.principled(Base_Color=color, Metallic=1.0, Roughness=0.32, Coat_Weight=0.2)
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


def torso_grid_smooth(S):
    """Como C.torso_grid (misma planta y rejilla) pero con un perfil de hombro continuo: una curva de Hermite que sale
    del cuello con caida suave y llega vertical a la pared, sin el escalon de pecho que deja el empalme casquete/filete
    (en Nicole lo tapa la bufanda; en Alfred se veria en el chaleco)."""
    nphi, ns = 480, 280
    phis = np.radians(np.linspace(-180, 180, nphi, endpoint=False))
    A, B, n = S['torso_a'], S['torso_b'], S['torso_n']
    sx, cy = np.sin(phis), -np.cos(phis)
    rs = (np.abs(sx / A) ** n + np.abs(cy / B) ** n) ** (-1 / n)
    outer = np.stack([rs * sx, S['torso_y'] + rs * cy], -1)
    neck = np.stack([S['neck_ring_r'] * sx, S['neck_y'] + S['neck_ring_r'] * cy], -1)
    zn, zw, zb = S['torso_zn'], S['torso_zs'] - S['shoulder_drop'], S['torso_zb']
    t = np.linspace(0, 1, 120)[:, None]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    m0, m1 = np.array(S['shoulder_t0']), np.array(S['shoulder_t1'])
    cap = h00 * np.array([0.0, zn]) + h10 * m0 + h01 * np.array([1.0, zw]) + h11 * m1
    wall_z = np.linspace(zw, zb, 60)[1:]
    prof = np.concatenate([cap, np.stack([np.ones_like(wall_z), wall_z], -1)])
    seg = np.linalg.norm(np.diff(prof * np.array([1.4, 1.0]), axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    sp = np.interp(np.linspace(0, arc[-1], ns), arc, prof[:, 0])
    sz = np.interp(np.linspace(0, arc[-1], ns), arc, prof[:, 1])
    xy = neck[:, None, :] + (outer - neck)[:, None, :] * sp[None, :, None]
    return np.concatenate([xy, np.broadcast_to(sz[None, :, None], (nphi, ns, 1))], -1)


def shirt_grid(S):
    """Torso de la camisa (rejilla de torso_grid_smooth) con tapeta y pliegues suaves; -> (P, N) hacia fuera."""
    P = torso_grid_smooth(S)
    nphi, ns = P.shape[:2]
    N = C.grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    # V suave: el pecho conserva el ancho y la cintura se estrecha; volumen de pecho delante y de omoplatos detras
    x, z = P[..., 0], P[..., 2]
    front, back = np.clip(-N[..., 1], 0, 1), np.clip(N[..., 1], 0, 1)
    P[..., 0] *= 1 - S['waist_taper'] * C.ss(S['waist_z'][0], S['waist_z'][1], z)
    # pecho como un plano ancho y alto (no dos montes): se lee masculino al recorte de icono
    pec = np.exp(-((z + 1.95) / 0.5) ** 2) * np.exp(-(x / 0.85) ** 4)
    blade = np.exp(-((z + 2.15) / 0.45) ** 2) * np.exp(-((np.abs(x) - 0.45) / 0.35) ** 2)
    P = P + N * (S['chest'] * pec * front + S['back'] * blade * back)[..., None]
    N = C.grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    x, z = P[..., 0], P[..., 2]
    front = np.clip(-N[..., 1], 0, 1)
    # tapeta de botones al centro (solo asoma en el pico del chaleco) y pliegues diagonales suaves bajo el hombro
    plack = (C.ss(0.085, 0.07, np.abs(x)) * 0.012 + np.exp(-((np.abs(x) - 0.075) / 0.008) ** 2) * 0.004) * front
    fold = 0.012 * np.sin(np.abs(x) * 9 + z * 6) * C.ss(0.75, 0.95, np.abs(x)) * C.ss(-1.6, -2.1, z)
    P = P + N * (plack + fold)[..., None]
    N = C.grid_normals(P)
    if np.dot(N[nphi // 2, ns // 2], [0, -1, 0]) < 0:
        N = -N
    return P, N


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
    Q = P + N * S['vest_off']
    zr = Q[0, :, 2]
    s0 = int(np.argmax(zr < S['vest_top_z']))  # el escote trasero queda por debajo de la vuelta del cuello
    rows = list(range(s0, ns))
    # escote: x del borde del pico por fila -> azimut en la mitad delantera
    xV = S['vest_v_top'] * np.clip((zr - S['vest_v_z']) / (S['torso_zn'] - S['vest_v_z']), 0, 1) ** 1.1
    half = (phis >= 0) & (phis <= 90)
    # sisa: arranca en la fila de la correa del hombro y se abre con forma redondeada
    rho = np.linspace(0, 1, ns)
    s1 = s0 + int(ns * S['vest_strap'])  # correa del hombro: la sisa se abre por debajo de la primera fila
    ds = int(ns * 0.08)
    hw = S['vest_arm_w'] * np.sqrt(np.clip((np.arange(ns) - s1) / ds, 0, 1)) * (1 - 0.0 * rho)
    n1, n2 = 48, 110
    cols = []
    for s in rows:
        xs = Q[half, s, 0]
        pv = float(np.interp(xV[s], xs, phis[half])) if xV[s] > 0 else 0.0
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
    # ribetes: pico + centro, sisas (borde delantero y trasero unidos arriba) y escote trasero
    r = 0.017
    edges = [G[0], G[-1][:int(np.argmax(xV[rows] <= 0)) + 2]]
    ia = int(np.argmax(hw[rows] > 0))
    for a, b in ((n1 - 1, n1), (n1 + n2 - 1, n1 + n2)) if S['vest_arm_w'] > 0 else ():
        edges.append(np.concatenate([G[a][ia:][::-1], G[b][ia:]]))
    edges.append(np.concatenate([G[:n1, 0], G[n1:n1 + n2, 0], G[n1 + n2:, 0]]))
    piping = []
    for E in edges:
        E = C.smooth_path(np.asarray(E), 2, keep_root=False)
        ctr = np.stack([np.zeros(len(E)), np.full(len(E), 0.15), E[:, 2]], -1)
        piping.append(C.sweep(E, C.unit(E - ctr), np.full(len(E), r), np.full(len(E), r * 0.8), 10))
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
    ph = np.radians(np.linspace(0.4, 359.6, nu))
    zz = np.linspace(zb, zt, nv)
    Ph, Z = np.meshgrid(ph, zz, indexing='ij')
    R = r0 - 0.01 * (Z - zb) / (zt - zb)
    band = np.stack([R * np.sin(Ph), y0 - R * np.cos(Ph), Z], -1)
    band_p = grid_part(band)
    # vuelta: filas desde el pliegue (t=0) hasta el canto (t=1); el borde delantero baja en diagonal hasta la punta
    nt = 22
    t = np.linspace(0, 1, nt)
    leaf = np.empty((nu, nt, 3))
    rt = r0 - 0.01 + 0.016
    for j, tt in enumerate(t):
        pf = 4 + 22 * tt
        p = np.radians(np.linspace(pf, 360 - pf, nu))
        d = np.minimum(np.degrees(p), 360 - np.degrees(p))
        # canto: punta delante (z bajo, mas fuera) y detras recto a media altura del pie
        point = np.exp(-((d - 26) / 16) ** 2)
        z_edge = zb + 0.08 - 0.1 * point
        r_edge = r0 + 0.12 + 0.06 * point
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

# ---------------------------------------------------------------- boina y pelo
# Pelo con el sistema de pelo de Blender: objeto Curves (hair curves) con guias generadas sobre el cuero cabelludo y los
# grupos de nodos de pelo que trae Blender (procedural_hair_node_assets: Attach -> Interpolate -> Clump -> Frizz ->
# Noise -> Set Hair Curve Profile) para los hijos; sombreado con Principled Hair BSDF (Chiang, melanina).
# Boina: simulacion de tela (Cloth) de un disco de lana sujeto por la banda, que cae con la gravedad sobre un proxy de
# colision (cabeza + volumen del pelo), y despues Solidify + Subdivision y pelusilla de fibras cortas.

def hairline_el(phi_deg):
    """Altura (elevacion, grados) del nacimiento del pelo por azimut: frente, entradas suaves, patilla, oreja, nuca."""
    k = [0, 30, 45, 58, 70, 78, 86, 98, 108, 120, 140, 180]
    e = [34, 32, 27, 18, -4, -10, 10, 13, 6, -18, -32, -38]
    return np.interp(np.abs(phi_deg), k, e)


def hat_dirs(phi_deg, el_deg):
    p, e = np.radians(phi_deg), np.radians(el_deg)
    return np.stack([np.cos(e) * np.sin(p), -np.cos(e) * np.cos(p), np.sin(e)], -1)


def build_hair_cap(S):
    """Cuero cabelludo (superficie de las guias y de los hijos): de la linea del pelo a la coronilla, con el borde
    fundido a transparente (atributo capfade) y el color de raiz; asi nunca se ve piel entre mechones."""
    nu, nv = 192, 48
    phi = np.linspace(-180, 180, nu, endpoint=False)
    t = np.linspace(0, 1, nv)
    el0 = hairline_el(phi)
    E = el0[:, None] + (89.0 - el0[:, None]) * t[None, :] ** 1.3
    D = hat_dirs(phi[:, None], E)
    V = C.head_points(D, S) + D * S['cap_off']
    f, ci, cj = C.grid_faces(nu, nv, closed_u=True, flip=True)
    ci = ci % nu
    uv = np.stack([ci / nu, cj / (nv - 1)], -1)
    part = C.Part(V.reshape(-1, 3), f, uv)
    fade = np.tile(C.ss(0.0, 0.06, t), nu)
    part.col = np.stack([fade, fade, fade, np.ones_like(fade)], -1)
    return part


def mat_hair_cap(S):
    nb = C.NB('hair_cap')
    attr = nb.node('ShaderNodeAttribute', attribute_name='capfade')
    base = tuple(c * 0.45 for c in S['hair_base'][:3]) + (1,)
    bsdf = nb.principled(Base_Color=base, Roughness=0.8, Specular_IOR_Level=0.1)
    tr = nb.node('ShaderNodeBsdfTransparent')
    mix = nb.node('ShaderNodeMixShader')
    nb.nt.links.new(attr.outputs['Fac'], mix.inputs['Fac'])
    nb.nt.links.new(tr.outputs[0], mix.inputs[1])
    nb.nt.links.new(bsdf.outputs[0], mix.inputs[2])
    nb.nt.links.new(mix.outputs[0], nb.out.inputs['Surface'])
    return nb.mat


def mat_hair_curves(S):
    """Principled Hair BSDF (Chiang) por melanina: raiz oscura (mas melanina) y puntas mas claras y calidas (Intercept
    del Hair Info), variacion por hebra (Random Color/Roughness) y brillo suave."""
    m = bpy.data.materials.new('hair_strands')
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new('ShaderNodeOutputMaterial')
    hb = nt.nodes.new('ShaderNodeBsdfHairPrincipled')
    hb.model, hb.parametrization = 'CHIANG', 'MELANIN'
    info = nt.nodes.new('ShaderNodeHairInfo')
    mr = nt.nodes.new('ShaderNodeMapRange')
    mr.inputs['To Min'].default_value, mr.inputs['To Max'].default_value = S['hair_melanin']
    nt.links.new(info.outputs['Intercept'], mr.inputs['Value'])
    nt.links.new(mr.outputs[0], hb.inputs['Melanin'])
    tint = nt.nodes.new('ShaderNodeMix')
    tint.data_type = 'RGBA'
    tint.inputs['A'].default_value = (1.0, 1.0, 1.0, 1)
    tint.inputs['B'].default_value = S['hair_tip_tint']
    nt.links.new(info.outputs['Intercept'], tint.inputs['Factor'])
    nt.links.new(tint.outputs['Result'], hb.inputs['Tint'])
    hb.inputs['Melanin Redness'].default_value = S['hair_redness']
    hb.inputs['Roughness'].default_value = 0.36
    hb.inputs['Radial Roughness'].default_value = 0.4
    hb.inputs['Coat'].default_value = 0.08
    hb.inputs['Random Color'].default_value = 0.15
    hb.inputs['Random Roughness'].default_value = 0.12
    nt.links.new(hb.outputs[0], out.inputs['Surface'])
    return m


HAIR_ASSETS = ('Attach Hair Curves to Surface', 'Interpolate Hair Curves', 'Clump Hair Curves',
               'Frizz Hair Curves', 'Hair Curves Noise', 'Set Hair Curve Profile')


def load_hair_assets():
    path = os.path.join(bpy.utils.system_resource('DATAFILES'), 'assets', 'nodes', 'procedural_hair_node_assets.blend')
    missing = [n for n in HAIR_ASSETS if n not in bpy.data.node_groups]
    if missing:
        with bpy.data.libraries.load(path) as (_, dst):
            dst.node_groups = missing


def gn(ob, group, **vals):
    """Modificador de nodos con un grupo de pelo de Blender; vals por nombre de entrada (espacios como '_')."""
    m = ob.modifiers.new(group, 'NODES')
    m.node_group = bpy.data.node_groups[group]
    ids = {i.name: i.identifier for i in m.node_group.interface.items_tree if getattr(i, 'in_out', None) == 'INPUT'}
    for k, v in vals.items():
        getattr(m.properties.inputs, ids[k.replace('_', ' ')]).value = v
    return m


def hair_guides(S, head_surf, rng):
    """Guias de pelo corto peinado: raices repartidas por igual sobre el cuero cabelludo; cada guia baja por la
    superficie hacia la linea del pelo (flequillo cruzado hacia la derecha del personaje, lados hacia atras), se separa
    del craneo con volumen en la raiz y se apoya en la punta. Todas llegan hasta el nacimiento (las capas que acaban a media
    cabeza se leen como escalones al interpolar los hijos); en la nuca acaban algo por encima (corto). -> (k, n, 3)."""
    k, n = S['hair_guides'], 16
    phi0 = rng.uniform(-180, 180, k)
    h0 = hairline_el(phi0)
    s0, s1 = np.sin(np.radians(h0)), np.sin(np.radians(88.0))
    el0 = np.degrees(np.arcsin(rng.uniform(s0, s1)))
    t = np.linspace(0, 1, n)[None, :]
    a = np.abs(phi0)
    front = C.ss(55, 20, a)                                      # 1 en la frente
    back = C.ss(100, 150, a)
    side = (1 - front) * (1 - back)
    # direccion: hacia abajo por el meridiano, el flequillo barre hacia -X y los lados algo hacia la nuca
    sweep = -22 * front + np.sign(phi0) * 10 * (1 - front) * (1 - back) + rng.normal(0, 3, k)
    phi = phi0[:, None] + sweep[:, None] * t ** 1.3 + rng.uniform(-2, 2, k)[:, None] * np.sin(np.pi * t)
    # todas las guias llegan hasta su propio limite (repartido bajo el nacimiento): sin linea de corte recta
    over = (6 * front + 3 * side + 3 * back) * rng.uniform(0.0, 1.0, k)
    lim = hairline_el(phi) + (10 * back - over)[:, None]
    span = el0 - lim[:, -1]
    el = el0[:, None] - np.maximum(span, 4.0)[:, None] * t
    D = hat_dirs(phi, el)
    vol = rng.uniform(0.012, 0.026, k)[:, None]
    off = S['cap_off'] + 0.006 + vol * C.ss(0.0, 0.3, t) * (1 - 0.75 * C.ss(0.35, 1.0, t))
    P = C.head_points(D, S) + D * off[..., None]
    for g in range(k):
        P[g] = head_surf.push_out(P[g], S['cap_off'] + 0.006, start=0)
    return P


def build_hair_curves(S, scalp_ob, head_surf, mat, rng):
    """Objeto Curves 'hair_strands' (guias) con los modificadores de pelo de Blender que generan los hijos."""
    load_hair_assets()
    G = hair_guides(S, head_surf, rng)
    k, n = G.shape[:2]
    crv = bpy.data.hair_curves.new('hair_strands')
    crv.add_curves([n] * k)
    crv.position_data.foreach_set('vector', G.reshape(-1).astype(np.float32))
    ob = bpy.data.objects.new('hair_strands', crv)
    bpy.context.scene.collection.objects.link(ob)
    crv.materials.append(mat)
    scalp_ob.add_rest_position_attribute = True
    crv.surface, crv.surface_uv_map = scalp_ob, 'UVMap'
    area = sum(p.area for p in scalp_ob.data.polygons)
    gn(ob, 'Attach Hair Curves to Surface', Surface_Object=scalp_ob)
    gn(ob, 'Interpolate Hair Curves', Density=k * S['hair_children'] / area, Interpolation_Guides=4, Seed=3)
    gn(ob, 'Clump Hair Curves', Factor=0.3, Shape=0.35, Tip_Spread=0.004, Guide_Distance=0.04, Seed=5)
    gn(ob, 'Frizz Hair Curves', Factor=0.25, Distance=0.006, Shape=0.6, Seed=7)
    gn(ob, 'Hair Curves Noise', Factor=0.4, Distance=0.008, Scale=6.0, Seed=9)
    gn(ob, 'Set Hair Curve Profile', Radius=S['hair_radius'], Shape=-0.4)
    ob.parent = scalp_ob
    return ob


# boina: disco de lana. Malla por azimut (nu) y filas: banda (sujeta), debajo (de la banda al canto) y copa (del canto
# al centro). La banda va en un plano inclinado (mas baja en +X); el disco es mas ancho que la cabeza y se desplaza
# hacia +X, asi la simulacion lo deja caido hacia ese lado.

def beret_band_el(phi_deg):
    p = np.radians(phi_deg)
    return 33 + 9 * np.cos(p) - 7 * np.sin(p)


def build_beret_sim(S, frames):
    """Simula la boina con Cloth (pin en la banda, colision con un proxy de cabeza + pelo). -> (Part, rows, nu)."""
    nu = 144
    phi = np.linspace(-180, 180, nu, endpoint=False)
    th = np.radians(phi)
    Db = hat_dirs(phi, beret_band_el(phi))
    band = C.head_points(Db, S) + Db * S['beret_band_off']
    up = C.unit(np.array([S['beret_tilt'], 0.0, 1.0]))
    c = np.array([S['beret_shift'], 0.02, S['head_top']]) + up * S['beret_lift']
    ex = C.unit(np.cross([0.0, 1.0, 0.0], up))
    ey = np.cross(up, ex)
    rad = np.sin(th)[:, None] * ex - np.cos(th)[:, None] * ey          # sin -> +X, cos -> delante (-Y)
    R = S['beret_r']
    rim = c - up * S['beret_thick'] + rad * R
    n_under, n_top = 9, 22
    rows = []
    for j in range(n_under):                          # banda -> canto: sale casi en horizontal y se abomba
        s = j / (n_under - 1)
        p = band + (rim - band) * s
        p = p - up * (0.06 * np.sin(np.pi * s))
        rows.append(p)
    for j in range(1, n_top + 1):                     # canto -> centro de la copa (abombada)
        s = j / n_top
        r = R * (1 - s) + 0.03 * s
        h = S['beret_thick'] * np.sin(np.pi / 2 * min(1.0, s * 3)) + S['beret_dome'] * np.sin(np.pi / 2 * s)
        rows.append(c - up * S['beret_thick'] + rad * r + up * h)
    P = np.stack(rows, 1)                             # (nu, nrows, 3)
    nr = P.shape[1]
    f, ci, cj = C.grid_faces(nu, nr, closed_u=True)
    ci = ci % nu
    part = C.Part(P.reshape(-1, 3), f, np.stack([ci / nu * 6.0, cj / (nr - 1) * 3.0], -1))
    part = C.orient_out(part, (0.0, 0.0, S['head_top'] * 0.6))

    sc = bpy.context.scene
    ob = C.make_object('beret_sim', part)
    vg = ob.vertex_groups.new(name='pin')
    idx = [i * nr + j for i in range(nu) for j in (0, 1)]
    vg.add(idx, 1.0, 'REPLACE')
    cl = ob.modifiers.new('cloth', 'CLOTH')
    st = cl.settings
    st.quality, st.mass = 8, 0.2
    st.tension_stiffness = st.compression_stiffness = st.shear_stiffness = 12.0
    st.bending_stiffness = S['beret_bend']
    st.air_damping = 3.0
    st.vertex_group_mass = 'pin'
    cs = cl.collision_settings
    cs.distance_min = 0.012
    cs.use_self_collision = True
    cs.self_distance_min = 0.01
    cl.point_cache.frame_start, cl.point_cache.frame_end = 1, frames
    # proxy de colision: cabeza mas el volumen del pelo
    nU, nV = 96, 48
    pp, ee = np.meshgrid(np.linspace(-180, 180, nU, endpoint=False), np.linspace(-80, 89, nV), indexing='ij')
    Dp = hat_dirs(pp, ee)
    proxy = C.Part((C.head_points(Dp, S) + Dp * S['beret_proxy_off']).reshape(-1, 3),
                   C.grid_faces(nU, nV, closed_u=True)[0] % (nU * nV))
    pob = C.make_object('beret_proxy', proxy)
    pob.modifiers.new('col', 'COLLISION')
    pob.collision.thickness_outer = 0.01
    sc.frame_start, sc.frame_end = 1, frames
    for fr in range(1, frames + 1):
        sc.frame_set(fr)
    ev = ob.evaluated_get(bpy.context.evaluated_depsgraph_get())
    V = np.array([v.co[:] for v in ev.data.vertices])
    sc.frame_set(1)
    for o in (ob, pob):
        bpy.data.objects.remove(o, do_unlink=True)
    part.v = V
    return part, nr, nu


def build_beret(S, root, mats):
    """-> (copa, banda, rabito) como Part (para el chequeo BVH); crea los objetos hat_*."""
    part, nr, nu = build_beret_sim(S, S['beret_frames'])
    P = part.v.reshape(nu, nr, 3)
    dome = C.Part(part.v, part.f, part.uv)
    ob = C.make_object('hat_beret', dome, mats['hat'], root)
    so = ob.modifiers.new('solid', 'SOLIDIFY')
    so.thickness, so.offset = 0.03, 1.0
    sd = ob.modifiers.new('subd', 'SUBSURF')
    sd.levels = sd.render_levels = 1
    # banda: canto enrollado en la boca de la boina (tubo sobre la fila 0)
    ring = P[:, 0]
    ctr = ring.mean(0)
    O = C.unit(ring - ctr)
    bandp = C.sweep(ring + O * 0.012, O, np.full(nu, 0.022), np.full(nu, 0.026), 12, closed=True)
    C.make_object('hat_band', bandp, mats['hat_band'], root)
    # rabito en el centro de la copa, siguiendo la normal de la ultima fila
    top = P[:, -1].mean(0)
    nrm = C.unit(top - ctr)
    path = np.array([top + nrm * 0.035, top + nrm * 0.05 + np.array([0.012, 0, 0]),
                     top + nrm * 0.075 + np.array([0.035, 0, -0.005])])
    path = C.smooth_path(path, 2)
    stem = C.sweep(path, np.tile([0.0, -1.0, 0.0], (len(path), 1)), np.linspace(0.02, 0.011, len(path)),
                   np.linspace(0.02, 0.011, len(path)), 10)
    C.make_object('hat_stem', stem, mats['hat'], root)
    build_wool_fuzz(S, dome, ob, mats)
    return dome, bandp, stem


def build_wool_fuzz(S, dome, beret_ob, mats):
    """Pelusilla de lana: fibras cortas (curves) repartidas por la cara exterior de la boina."""
    rng = np.random.default_rng(5)
    V, F = dome.v, dome.f
    a, b, c = V[F[:, 0]], V[F[:, 1]], V[F[:, 2]]
    d = V[F[:, 3]] if F.shape[1] > 3 else c
    area = 0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1) + 0.5 * np.linalg.norm(np.cross(c - a, d - a), axis=1)
    k = S['wool_fuzz']
    fi = rng.choice(len(F), k, p=area / area.sum())
    u, v = rng.uniform(size=(2, k, 1))
    p = (a[fi] * (1 - u) + b[fi] * u) * (1 - v) + (d[fi] * (1 - u) + c[fi] * u) * v
    nrm = C.unit(np.cross(c[fi] - a[fi], d[fi] - b[fi]))
    p = p + nrm * 0.03                                       # fuera del solidify (offset 1: crece por fuera)
    dirn = C.unit(nrm + rng.normal(0, 0.9, (k, 3)))
    ln = rng.uniform(0.004, 0.011, (k, 1))
    pts = np.stack([p, p + dirn * ln * 0.5 + rng.normal(0, 0.002, (k, 3)), p + dirn * ln], 1)
    crv = bpy.data.hair_curves.new('hat_fuzz')
    crv.add_curves([3] * k)
    crv.position_data.foreach_set('vector', pts.reshape(-1).astype(np.float32))
    ob = bpy.data.objects.new('hat_fuzz', crv)
    bpy.context.scene.collection.objects.link(ob)
    crv.materials.append(mats['hat_fuzz'])
    gn(ob, 'Set Hair Curve Profile', Radius=0.0011, Shape=-0.5)
    ob.parent = beret_ob


def conan_mats(S):
    return dict(shirt=mat_cotton('shirt', S['shirt']), vest=mat_suit('jacket', S['vest']),
                piping=mat_suit('jacket_piping', S['vest_piping']), brass=mat_brass('brass', S['brass']),
                pearl=C.mat_flat('pearl', S['pearl'], rough=0.25, coat=0.6),
                hat=mat_felt('beret', S['hat']), hat_band=mat_felt('beret_band', S['hat_band']),
                hat_fuzz=mat_fuzz('beret_fuzz', S['hat']), hair_cap=mat_hair_cap(S), hair_strands=mat_hair_curves(S),
                lupa_glass=C.mat_flat('lupa_glass', L('#dfe8ee'), rough=0.05, coat=1.0))


def build_neck(S):
    """Cuello corto y grueso que se ensancha abajo hacia el trapecio (la base queda bajo el cuello de la camisa)."""
    nu, nv = 64, 24
    th = np.linspace(-np.pi, np.pi, nu, endpoint=False)
    z0, z1 = S['neck_z']
    zs = np.linspace(z0, z1, nv)
    T, Z = np.meshgrid(th, zs, indexing='ij')
    # base de trapecio: mas ancha a los lados que delante/detras
    r = S['neck_r'] + S['neck_flare'] * C.ss(-1.25, -1.55, Z) * (0.6 + 0.4 * np.sin(T) ** 2)
    P = np.stack([r * np.sin(T), S['neck_y'] - r * np.cos(T), Z], -1)
    f, ci, cj = C.grid_faces(nu, nv, closed_u=True)
    return C.Part(P.reshape(-1, 3), f, np.stack([ci / nu, cj / nv], -1))


def catmull(A, sub):
    """Curva Catmull-Rom por los puntos de control A (k, d), sub muestras por tramo."""
    A = np.asarray(A, float)
    E = np.concatenate([[2 * A[0] - A[1]], A, [2 * A[-1] - A[-2]]])
    out = []
    for i in range(1, len(E) - 2):
        p0, p1, p2, p3 = E[i - 1], E[i], E[i + 1], E[i + 2]
        for t in np.linspace(0, 1, sub, endpoint=False):
            out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                              + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    out.append(A[-1])
    return np.array(out)


def arm_sleeve(ctrl, radii, elbow, inner, sub=28, cuff=True):
    """Manga de la chaqueta como UN tubo continuo: nace dentro del torso (ctrl[0]), dobla sobre el hombro formando el
    deltoides (ctrl[1]) y baja por brazo, codo (ctrl[elbow]) y antebrazo hasta el punio. Pliegues de tela: arrugas en
    abanico en la cara interna del codo (inner = direccion), ondas suaves de caida a lo largo y punio con canale."""
    Q = catmull(np.concatenate([np.asarray(ctrl, float), np.asarray(radii, float)[:, None]], 1), sub)
    Q[:, 3] = C.smooth_path(Q[:, 3:], 6)[:, 0]
    P, rad = Q[:, :3], Q[:, 3]
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    L, ae = arc[-1], arc[elbow * sub]
    T = C.unit(np.gradient(P, axis=0))
    inner = np.asarray(inner, float)
    O = C.unit(np.cross(T, np.cross(inner, T)) + 1e-6)  # theta = pi/2 apunta a 'inner'
    O = np.where(np.linalg.norm(np.cross(inner, T), axis=1)[:, None] < 1e-3, [0.0, -1.0, 0.0], O)
    band = C.ss(L - 0.24, L - 0.2, arc) if cuff else np.zeros_like(arc)
    rad = rad * (1 + 0.07 * band)
    hang = C.ss(0.35, 0.8, arc)  # sin pliegues sobre el hombro

    def mod(i, th):
        a = arc[i]
        side = np.clip(np.sin(th), 0, 1) ** 1.5  # cara interna del codo
        el = np.exp(-((a - ae) / 0.28) ** 2)
        wr = 0.06 * el * side * np.sin(math.tau * a / 0.13 + 1.6 * np.cos(th))
        # pliegues de caida en helice suave (mas marcados en la cara interna, bajo la axila)
        drape = (0.028 * np.sin(2 * th + math.tau * a / 0.5 + 0.8) * (0.55 + 0.45 * np.sin(th))
                 + 0.012 * np.sin(5 * th - math.tau * a / 0.3)) * hang[i] * (1 - band[i])
        rib = 0.025 * band[i] * (0.5 + 0.5 * np.cos(36 * th) - 0.5)
        return 1 + wr + drape + rib

    W = C.unit(np.cross(T, O))
    sleeve = C.sweep(P, np.cross(W, T), rad, rad * 0.94, 64, mod=mod)
    parts = [sleeve]
    if cuff:
        t = T[-1]
        w = C.unit(np.cross(t, O[-1]))
        h = np.cross(w, t)
        th = np.linspace(0, math.tau, 64, endpoint=False)
        ring = P[-1] + (np.outer(np.cos(th), w) + np.outer(np.sin(th), h) * 0.94) * rad[-1] * 1.0
        parts.append(C.sweep(ring, np.tile(t, (64, 1)), np.full(64, 0.035), np.full(64, 0.035), 10, closed=True))
    return C.Part.join(parts), P


def arm_ctrl(S, s, elbow, wrist):
    """Puntos de control de un brazo del lado s (+1 izquierda del personaje): raiz, deltoides, mitad del brazo, codo,
    mitad del antebrazo y punio."""
    sx = np.array([s, 1.0, 1.0])
    root, dl = np.array(S['arm_root']) * sx, np.array(S['arm_deltoid']) * sx
    elbow, wrist = np.asarray(elbow, float), np.asarray(wrist, float)
    up = dl + (elbow - dl) * 0.45 + np.array([s * 0.08, 0.0, 0.0])
    fore = elbow + (wrist - elbow) * 0.45
    return np.array([root, dl, up, elbow, fore, wrist])


def build_lapels(S, torso_surf, root, mats):
    """Solapas: dos tiras que bajan desde el cuello y enmarcan el escote en V de la chaqueta."""
    def front_pt(x, z, off=0.03):
        loc, nor = torso_surf.front(x, z)
        return (loc + nor * off) if loc is not None else np.array([x, -0.9, z])

    parts = []
    for s in (-1, 1):
        path = np.array([front_pt(s * 0.2, -1.36), front_pt(s * 0.32, -1.6), front_pt(s * 0.4, -1.82),
                         front_pt(s * 0.48, -2.05)])
        path = C.smooth_path(path, 3)
        O = np.tile(np.array([0.0, -1.0, 0.0]), (len(path), 1))
        parts.append(C.sweep(path, O, np.linspace(0.045, 0.065, len(path)), np.full(len(path), 0.012), 10))
    C.make_object('lapels', C.Part.join(parts), mats['vest'], root)


def build_lupa_chest(S, jacket, root, mats):
    """Lupa grande colgada de dos cordones sobre el pecho: se ve en todos los estados y no tapa la cara."""
    V = jacket.v

    def front_pt(x, z, off=0.03):
        """Punto delante de la chaqueta en (x, z): el vertice mas adelantado de la columna (y minimo)."""
        m = (np.abs(V[:, 0] - x) < 0.02) & (np.abs(V[:, 2] - z) < 0.02)
        y = V[m, 1].min() if m.any() else -0.9
        return np.array([x, y - off, z])

    lx, _, lz = S['lupa_at']
    lc = front_pt(lx, lz, 0.06)
    r = S['lupa_r']
    a = np.linspace(0, C.TAU, 48, endpoint=False)
    # el aro sigue la curvatura del pecho (cada punto se proyecta sobre la chaqueta)
    fr = np.array([front_pt(lx + r * np.cos(t), lz + r * np.sin(t), 0.05) for t in a])
    frame = C.sweep(fr, np.tile([0, -1, 0], (48, 1)), np.full(48, 0.022), np.full(48, 0.02), 12, closed=True)
    glass = C.sphere_part(1.0, 32, 16)
    glass.v = glass.v * np.array([r * 0.9, 0.014, r * 0.9]) + lc
    hp = front_pt(lx, lz - r, 0.04)
    handle = C.sweep(np.array([hp, hp + np.array([0.03, -0.05, -0.24])]), np.tile([0, -1, 0], (2, 1)),
                     np.array([0.026, 0.022]), np.array([0.024, 0.02]), 10)
    cords = []
    for s in (-1, 1):
        a0 = front_pt(s * 0.26, -1.32, 0.04)
        a1 = front_pt(s * 0.16, -1.75, 0.05)
        top = lc + np.array([s * r * 0.55, 0.0, r * 0.75])
        path = C.smooth_path(np.array([a0, a1, top]), 4)
        cords.append(C.sweep(path, np.tile([0, -1, 0], (len(path), 1)), np.full(len(path), 0.008),
                             np.full(len(path), 0.008), 8))
    C.make_object('lupa', C.Part.join([frame, handle]), mats['brass'], root)
    C.make_object('lupa_glass', glass, mats['lupa_glass'], root)
    C.make_object('lupa_cord', C.Part.join(cords), mats['piping'], root)


def build(S):
    root = C.empty('conan')
    F = studio.build_face(S, EXPR, root, conan_mats)
    head, head_surf, skin, mats = F['head'], F['head_surf'], F['skin'], F['mats']

    P, N = shirt_grid(S)
    shirt = grid_part(P, (4.0, 4.0), closed_u=True)
    C.make_object('shirt', shirt, mats['shirt'], root)
    C.make_object('shirt_buttons', build_shirt_buttons(S, P, N), mats['pearl'], root)
    neck = build_neck(S)
    C.make_object('neck', neck, skin, root)
    jacket, piping, jbuttons, _ = build_vest(S, P, N)
    C.make_object('jacket', jacket, mats['vest'], root)
    C.make_object('jacket_piping', piping, mats['piping'], root)
    C.make_object('jacket_buttons', jbuttons, mats['brass'], root)
    torso_surf = C.Surface(jacket)
    build_lapels(S, torso_surf, root, mats)
    build_lupa_chest(S, jacket, root, mats)
    collar = build_collar(S, C.Surface(C.Part.join([shirt, jacket, piping])))
    C.make_object('collar', collar, mats['shirt'], root)
    rng = np.random.default_rng(11)
    cap = build_hair_cap(S)
    scalp = C.make_object('hair_cap', cap, mats['hair_cap'], root, colors=True, colname='capfade')
    build_hair_curves(S, scalp, head_surf, mats['hair_strands'], rng)
    dome, band, stem = build_beret(S, root, mats)

    hand_parts = []
    frng = np.random.default_rng(23)
    hands = studio.build_hands(S, HAND_POSES, mats, root, frng, mats['vest'], None, hand_parts)
    # brazos: mangas continuas desde el hombro. El derecho cuelga salvo cuando la mano esta en pose (clave None de
    # hands: visible en las expresiones sin 'hands'); en cada pose la manga de hands.py se cambia por la del brazo
    arm_parts = []
    for s, name in ((1, 'arm.L'), (-1, 'arm.R')):
        ctrl = arm_ctrl(S, s, (s * 1.2, 0.3, -2.95), (s * 1.14, 0.0, -4.05))
        part, _ = arm_sleeve(ctrl, S['arm_r'], 3, (ctrl[1] + ctrl[-1]) / 2 - ctrl[3])
        ob = C.make_object(name, part, mats['vest'], root)
        arm_parts.append((name, part))
        if s < 0:
            hands[None] = [ob]
    for pname, objs in hands.items():
        if pname is None:
            continue
        spec = HAND_POSES[pname]['R']
        tag = '' if pname == S['done_pose'] else f'_{pname}'
        fw = C.unit(np.asarray(spec['F'], float))
        end = np.asarray(spec['wrist'], float) - fw * 0.12 * S['hand_scale']
        ctrl = arm_ctrl(S, -1, spec['elbow'], end)
        part, _ = arm_sleeve(ctrl, S['arm_r'], 3, (ctrl[1] + ctrl[-1]) / 2 - ctrl[3])
        # fuera la manga de hands.py y la mano en reposo (.L): el brazo izquierdo estatico ya la sustituye
        for nm in (f'sleeve{tag}.R', f'nails{tag}.L', f'hand{tag}.L', f'sleeve{tag}.L'):
            old = bpy.data.objects[nm]
            objs.remove(old)
            bpy.data.objects.remove(old)
        objs.append(C.make_object(f'sleeve_arm{tag}.R', part, mats['vest'], root))
        hand_parts[:] = [hp for hp in hand_parts if hp[0] != f'sleeve{tag}.R'] + [(f'sleeve_arm{tag}.R', part)]

    # chequeo de interpenetracion: ropa entre si, ropa contra cuello y cabeza, gorro contra cabeza, cuello y ropa,
    # y manos contra todo. (Tapa y orejeras se solapan a proposito: no se comprueban entre si.)
    cloth = dict(shirt=shirt, jacket=jacket, piping=C.Part.join([piping, jbuttons]), collar=collar, neck=neck,
                 head=head, hat_beret=dome, hat_band=band, hat_stem=stem, hair_cap=cap)
    pairs = [(a, cloth[a], b, cloth[b]) for a, b in (
        ('shirt', 'jacket'), ('shirt', 'piping'), ('shirt', 'collar'), ('shirt', 'neck'), ('jacket', 'collar'),
        ('piping', 'collar'), ('jacket', 'neck'), ('collar', 'neck'), ('collar', 'head'),
        ('hat_beret', 'head'), ('hat_band', 'head'), ('hat_stem', 'hat_beret'), ('hat_beret', 'neck'),
        ('hat_band', 'collar'), ('hair_cap', 'hat_beret'), ('hair_cap', 'hat_band'), ('hair_cap', 'head'))]
    # las mangas nacen dentro del hombro (costura de la sisa): no se comprueban contra camisa y chaqueta
    for hname, part in hand_parts + arm_parts:
        sl = hname.startswith(('sleeve_arm', 'arm'))
        pairs += [(hname, part, b, cloth[b]) for b in ('shirt', 'jacket', 'piping', 'collar', 'head', 'hat_beret')
                  if not (sl and b in ('shirt', 'jacket'))]
    C.check_overlaps(pairs)

    ind_root, ind = studio.build_indicator_set(S, mats)
    arm = studio.build_rig('conan', root, F['eyes'], HEAD_PARTS)
    studio.organize(GROUPS)
    return dict(root=root, head_surf=head_surf, eyes=F['eyes'], mats=mats, pupil=F['pupil'], iris=F['iris'], ind=ind,
                ind_root=ind_root, brows=F['brows'], mouth=F['mouth'], arm=arm, hands=hands)


HEAD_PARTS = ('head', 'eye', 'brow', 'mouth', 'hair', 'hat')
GROUPS = [('rig', ('conan', 'conan_rig')), ('eyes', ('eye',)), ('brows', ('brow',)), ('mouth', ('mouth_',)),
          ('hair', ('hair_',)), ('hat', ('hat_',)), ('head', ('head',)), ('hands', ('hand', 'nails', 'sleeve')), ('arms', ('arm',)),
          ('body', ('shirt', 'jacket', 'collar', 'neck', 'lapels', 'lupa')), ('indicators', ('ind',))]


studio.run('conan', S, EXPR, build, review_expr=REVIEW_EXPR, icon_cam=ICON_CAM)
