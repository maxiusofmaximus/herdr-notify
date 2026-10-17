"""Bob (builder) en Blender/Cycles: casco de obra ambar, sudadera con capucha teal, cara cuadrada.

Uso (desde la raiz del repo):
  blender -b --factory-startup -P tooling/avatars3d/blender/bob.py -- [--out DIR] [--expr a,b] [--quick]
       [--samples N] [--closeup] [--view yaw:cx:cz:alto[;...]]
Escribe <out>/bob-<expr>.png (512), -128, -64, -48, -32 y, con --review, vistas giradas en review/.
--closeup (desarrollo) solo renderiza primeros planos de la cara: <out>/face-<expr>.png.
--view (desarrollo) solo renderiza encuadres libres: <out>/view-<expr>-<i>.png.
Estilo congelado de Nicole it.10 (carа/ojos/piel/materiales blandos, mechones agrupados, camara/luz/encuadre).
"""
import math
import os
import sys
import time

import bmesh
import bpy
from mathutils import Vector
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import character as C  # noqa: E402
import hands as H  # noqa: E402

L = C.lin

S = dict(
    # cabeza: cuadrada (poca convergencia de mandibula, ancha) con esquinas marcadas
    # (back/top >= 0.95: el pelo compartido tiene un suelo r>=0.95; por debajo se hunde en la cabeza)
    head_w=0.98, head_front=0.9, head_back=0.99, head_top=0.98, head_bot=0.9, jaw_taper=0.2,
    head_bumps=[
        ((0.6, -0.7, -0.26), 0.012, 0.22, True),    # pometos discretos (feedback 8: mejillas mas pequenas)
        ((0.58, -0.74, -0.52), -0.022, 0.17, True),  # leve hundido bajo el pometo
        ((0.72, -0.32, -0.62), 0.11, 0.17, True),   # angulo de la mandibula marcado (adulto, feedback 2/8 Bob)
        ((0.36, -0.92, -0.06), -0.05, 0.2, True),   # cuencas
        ((0.0, -1.0, -0.3), 0.04, 0.1, False),      # nariz plana y ancha (base)
        ((0.0, -1.0, -0.38), 0.014, 0.07, False),   # punta baja
        ((0.0, -1.0, -0.2), 0.01, 0.07, False),     # dorso sobrio
        ((0.1, -1.0, -0.4), 0.018, 0.05, True),     # aletas
        ((0.05, -1.0, -0.43), -0.013, 0.024, True),  # orificios
        ((0.0, -1.0, -0.47), -0.008, 0.04, False),  # surco bajo la nariz
        ((0.0, -0.85, -0.88), 0.035, 0.2, False),   # barbilla ancha
        ((0.3, -0.9, 0.2), 0.025, 0.2, True),       # arco de la ceja
    ],
    skin=L('#D9A07A'), blush=L('#C4785F'), nose_tip=L('#C98365'),
    # ojos redondos
    eye_x=0.37, eye_z=-0.1, eye_r=0.26, eye_depth=0.75, eye_yaw=9.0, eye_tilt=0.0,
    iris_ang=0.7, pupil=0.4,
    sclera=L('#FBF6F1'), sclera_edge=L('#DFC6B6'), iris_in=L('#8A5526'), iris_mid=L('#54300F'),
    iris_out=L('#2E1607'), iris_ring=L('#150903'), iris_glow=L('#C98A47'),
    catchlights=[(-0.36, 0.42, 0.05), (0.3, -0.22, 0.024)],
    lash_w=0.027, lash_flicks=[],
    lash=L('#1C120C'), lid_thick=0.016, crease_gap=10, crease_w=0.011, lid_fillet=0.09,
    # cejas gruesas y boca
    brow_pts=[(0.05, 0.2), (0.36, 0.3), (0.7, 0.245)], brow_w=0.095, brow=L('#2B1B14'),
    brow_light=L('#4A3226'), brow_dark=L('#17100B'), brow_hair=0.0032, brow_hair_len=0.015,
    lip_up_h=0.03, lip_lo_h=0.045, lip_up_lift=0.02, lip_lo_lift=0.028,
    mouth_center=(0.0, -0.55), lip=L('#B57164'), lipline=L('#5E322B'), cavity=L('#4A1418'),
    teeth=L('#FBF6EF'), tongue=L('#D9646E'),
    # pelo: Hair Curves nativo (guias + hijos por nodos), Principled Hair BSDF por melanina (raiz -> punta)
    hair_axis_y=0.1, hair_dark=L('#2A170D'), hair_melanin=(0.86, 0.62), hair_redness=(0.55, 0.85),
    # linea del pelo (grados desde la frente, z): frente alta bajo la visera, sienes, patilla, nuca
    hairline=[(0, 0.55), (30, 0.5), (50, 0.4), (70, 0.2), (88, -0.08), (110, -0.16), (150, -0.4), (180, -0.46)],
    hair_overhang=[(0, 0.34), (35, 0.28), (70, 0.16), (90, 0.12), (180, 0.12)],
    hair_root_above=0.32, hair_guides_fib=9000, hair_guide_pts=16, hair_vol=0.035, hair_wave=0.02,
    hair_wave_len=0.26, hair_hat_gap=0.012, hair_fill=0.85, hair_fill_max=0.12, hair_fill_below=0.28,
    hair_density=7000.0, hair_clump=0.55, hair_clump_dist=0.05, hair_radius=0.0028,
    # casco de obra: copa superelipsoide propia, cresta + 2 nervios, ala fina y visera frontal; Solidify + Bevel
    hat_a=1.0, hat_bf=0.97, hat_bb=1.08, hat_c=0.98, hat_e=0.75, hat_yc=0.08, hat_zc=0.12, hat_thick=0.035,
    rim_z0=0.45, rim_k=-0.11, crest_h=0.045, crest_w=0.12, rib_h=0.0, rib_x=0.42, rib_w=0.05,
    brim_w=0.06, brim_back=0.04, brim_tilt=0.18, brim_fillet=0.03, visor_w=0.26, visor_span=0.8,
    visor_tilt=0.12, visor_curl=0.04,
    hardhat=L('#FFDD00'),
    # cuerpo robusto: cuello corto y grueso; torso anatomico (trapecio, hombro, pecho > cintura) y brazos de una
    # pieza fundidos con el torso por SDF (union + redondeo), ver build_body
    neck_y=0.12, neck_r=0.54, neck_z=(-1.5, -0.52), collar_r=0.63, collar_z=(-1.32, -0.89), collar_rib=0.02,
    collar_top=-0.9, collar_base=0.14,
    collar_ribs=80, torso_y=0.22, neck_ring_r=0.69, torso_zn=-1.1,
    # pared del torso por niveles z (hombro, pecho, bajo pecho, cintura, cadera): semiancho, fondo delante/detras
    body_z=(-1.6, -2.1, -2.6, -3.2, -4.0), body_a=(1.32, 1.34, 1.28, 1.16, 1.13),
    body_bf=(0.76, 0.9, 0.9, 0.82, 0.8), body_bb=(0.8, 0.86, 0.84, 0.78, 0.76),
    shoulder_t0=(1.6, -0.3), shoulder_t1=(0.2, -1.0),
    body_voxel=0.011, body_fillet=24,
    knit_col=0.145, knit_row=0.12, knit_depth=0.024, cable_u=(), cable_period=0.5, cable_rope=0.115,
    cable_half=0.27, cable_amp=0.09, cable_depth=0.02, sweater=L('#138B75'),
    # capucha bajada detras del cuello (tubo por la nuca que se abomba en la espalda)
    hood_r0=0.8, hood_back=0.3, hood_z0=-1.06, hood_lift=0.0, hood_w0=0.15, hood_wb=0.28,
    hood_h0=0.11, hood_hb=0.18, hood_gap=0.035, fuzz=4000,
    strings_at=(0.25, -0.58, -1.06), string_color=L('#E8F5F0'),
    # indicadores (coordenadas locales del ancla; escala grande para que se lea a 48 px)
    indicator_root=(1.1, -1.2, 0.74), indicator_scale=1.15,
    icon_indicator=((0.6, -1.05, 0.8), 0.85), indicator_at=(0.0, 0.0, 0.0),
    sparkles=[(0.0, 0.0, 0.3), (-0.36, 0.26, 0.15), (0.3, -0.36, 0.14)],
    sweat_at=(-0.86, -0.62, 0.12),
    # manos (solo en `done`): pulgar arriba, mano derecha delante del pecho
    hand_scale=1.5, done_pose='thumbs',
)

# boca de linea (thinking/working/error): labios casi planos, sin volumen rosa; solo la linea cerrada
LINE_LIPS = dict(lip_up_h=0.007, lip_lo_h=0.01, lip_up_lift=0.003, lip_lo_lift=0.004)

EXPR = {
    'neutral': dict(lid_up=33, lid_lo=-46, gaze=(0, -2), tilt=0, pupil=0.4,
                    brow={1: (0, 0, 0), -1: (0, 0, 0)},
                    mouth=dict(w=0.17, cl=0.024, cr=0.024, up=0.0, open=0.0)),
    'thinking': dict(lid_up=28, lid_lo=-34, gaze=(16, -18), tilt=0, pupil=0.38,
                     brow={1: (0.06, 0.11, 0.07), -1: (-0.035, -0.03, 0.0)},
                     mouth=dict(w=0.1, cl=-0.004, cr=0.012, up=0.0, open=0.0, shift=0.06), lips=LINE_LIPS,
                     indicator='thinking'),
    'working': dict(lid_up=12, lid_lo=-26, gaze=(-20, 4), tilt=12, pupil=0.4,
                    brow={1: (-0.11, -0.03, 0.04), -1: (-0.11, -0.03, 0.04)},
                    mouth=dict(w=0.1, cl=-0.006, cr=-0.006, up=0.0, open=0.0, shift=-0.02), lips=LINE_LIPS,
                    indicator='working'),
    'happy': dict(lid_up=16, lid_lo=16, gaze=(0, 0), tilt=0, pupil=0.4,
                  brow={1: (0.05, 0.07, 0.03), -1: (0.05, 0.07, 0.03)},
                  mouth=dict(w=0.22, cl=0.075, cr=0.075, up=-0.01, open=0.19, teeth=True, teeth_h=0.05,
                             tongue=True),
                  indicator='happy'),
    'error': dict(lid_up=37, lid_lo=-52, gaze=(0, 0), tilt=-6, pupil=0.26, iris=0.78,
                  brow={1: (0.1, 0.03, -0.03), -1: (0.1, 0.03, -0.03)},
                  mouth=dict(w=0.13, cl=-0.03, cr=-0.03, up=0.0, open=0.0), lips=LINE_LIPS,
                  indicator='error'),
    'done': dict(lid_up=28, lid_lo=-30, gaze=(0, 0), tilt=0, pupil=0.42,
                 brow={1: (0.04, 0.05, 0.02), -1: (0.04, 0.05, 0.02)},
                 mouth=dict(w=0.21, cl=0.07, cr=0.07, up=-0.01, open=0.12, teeth=True, teeth_h=0.045),
                 indicator='done', hands=S['done_pose']),
}


# brazos: eje de la manga por puntos de control (x, y, z, radio) desde dentro del torso (bajo el trapecio) por el
# deltoides, codo y antebrazo hasta el punio. Coordenadas del brazo izquierdo (x > 0); el derecho se refleja.
ARM_REST = [(0.84, 0.24, -1.48, 0.2), (1.3, 0.25, -1.8, 0.31), (1.52, 0.3, -2.4, 0.285), (1.64, 0.32, -3.15, 0.255),
            (1.66, 0.2, -3.85, 0.235), (1.64, 0.1, -4.35, 0.21)]
# poses de mano para `done` (ver hands.py). .R = mano derecha del personaje (izquierda de la imagen).
# Solo se construyen las manos de los brazos levantados; los brazos en reposo acaban fuera de cuadro.
HAND_POSES = {
    # pulgar arriba (feedback 8/9): codo junto al costado (fuera del icono), antebrazo recto en diagonal hasta que el
    # puno queda junto a la mejilla, como el done de Alfred, para que se lea a 48/32 px; muneca recta (F sigue al
    # antebrazo); puno de perfil con los dedos apilados hacia camara y el pulgar vertical, como el emoji
    'thumbs': dict(R=dict(wrist=(-1.24, -1.12, -0.82), F=(0.185, -0.329, 0.926), N=(-1.0, 0.0, 0.0), side=-1,
                          curl=dict(index=(90, 95, 88), middle=(94, 98, 90), ring=(96, 100, 92), pinky=(100, 102, 95)),
                          splay=dict(index=-4, middle=0, ring=4, pinky=8),
                          thumb=dict(dir=(0.0, -0.15, 1.0), up=(-0.6, -0.8, 0.0), curl=(0, 2)),
                          arm=[(-0.84, 0.24, -1.48, 0.2), (-1.3, 0.24, -1.8, 0.31), (-1.5, 0.02, -2.25, 0.285),
                               (-1.6, -0.48, -2.62, 0.265), (-1.438, -0.768, -1.81, 0.24),
                               (-1.247, -1.107, -0.857, 0.2)]),  # punio ceñido justo bajo el puno
                   L=None),
}
# encuadre de icono: un poco mas abierto para que el pulgar y el puño entren a 48 px
ICON_CAM = {'thumbs': dict(height=3.05, center=(-0.16, -0.06))}


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
    sc.render.film_transparent = True
    sc.cycles_curves.shape = 'THICK'                   # pelo como cilindros 3D, no cintas
    sc.cycles_curves.subdivisions = 3
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


class HardHat:
    """Casco de obra con forma propia (no copia la cabeza): copa superelipsoide (flancos casi verticales y techo
    redondeado; mas corta delante que detras), cresta central con dos nervios, borde plano inclinado
    (rim_z0 + rim_k * y), ala fina alrededor y visera frontal. La superficie es una lamina; el grosor y el canto
    redondo los ponen los modificadores Solidify + Bevel nativos de Blender."""

    def __init__(self, S):
        self.S = S
        self.thick = S['hat_thick']

    def R(self, phi):
        S = self.S
        B = np.where(np.cos(phi) > 0, S['hat_bf'], S['hat_bb'])
        return 1.0 / np.sqrt((np.sin(phi) / S['hat_a']) ** 2 + (np.cos(phi) / B) ** 2)

    def at(self, phi, th):
        """phi: 0 = frente (-Y); th: elevacion de la copa (pi/2 = techo) -> puntos (..., 3)."""
        S = self.S
        rho = self.R(phi) * np.clip(np.cos(th), 0, None) ** S['hat_e']
        return np.stack([rho * np.sin(phi), S['hat_yc'] - rho * np.cos(phi),
                         S['hat_zc'] + S['hat_c'] * np.sin(th)], -1)

    def rim_th(self, phi):
        S = self.S
        lo, hi = np.full(phi.shape, -0.9), np.full(phi.shape, 1.3)
        for _ in range(40):
            mid = (lo + hi) / 2
            P = self.at(phi, mid)
            f = P[..., 2] - (S['rim_z0'] + S['rim_k'] * P[..., 1])
            hi, lo = np.where(f > 0, mid, hi), np.where(f > 0, lo, mid)
        return (lo + hi) / 2

    def inner_rho(self, phi, z):
        """Radio horizontal de la cara interior de la copa a esa altura (bajo el borde: el del borde)."""
        S = self.S
        th = np.arcsin(np.clip((z - S['hat_zc']) / S['hat_c'], -1, 1))
        th = np.maximum(th, self.rim_th(phi))
        return self.R(phi) * np.cos(th) ** S['hat_e'] - self.thick

    def rim_z(self, phi):
        return self.at(phi, self.rim_th(phi))[..., 2]

    def build(self, nu=320, nd=90, nf=8, nb=10):
        S = self.S
        phis = np.linspace(-np.pi, np.pi, nu, endpoint=False)
        th0 = self.rim_th(phis)
        t = np.linspace(0, 1, nd)
        TH = th0[:, None] + (np.pi / 2 - th0[:, None]) * t[None, :]
        PH = np.broadcast_to(phis[:, None], TH.shape)
        P = self.at(PH, TH)
        # cresta central (de delante a detras por el techo) y dos nervios laterales, mueren antes del borde
        # (desplazamiento vertical: coherente en el polo de la malla, sin abolladuras junto a la cresta)
        x = P[..., 0]
        fade = C.ss(0.0, 0.45, TH - th0[:, None])
        crest = (S['crest_h'] * np.exp(-(x / S['crest_w']) ** 2)
                 + S['rib_h'] * np.exp(-((np.abs(x) - S['rib_x']) / S['rib_w']) ** 2)) * fade
        P = P.copy()
        P[..., 2] += crest
        # borde: chaflan redondo (fillet) de la pared hacia fuera y luego el ala; visera ancha delante
        rim = P[:, 0]
        dn = C.unit(P[:, 0] - P[:, 1])
        front = np.exp(-(phis / S['visor_span']) ** 4)
        back = np.exp(-((np.abs(phis) - np.pi) / 0.7) ** 2)
        horiz = C.unit(np.stack([np.sin(phis), -np.cos(phis), np.zeros(nu)], -1))
        out = C.unit(horiz + np.array([0, 0, -1.0]) * (S['brim_tilt'] + S['visor_tilt'] * front)[:, None])
        rf = S['brim_fillet']
        al = np.linspace(np.pi / 2, 0, nf, endpoint=False)[::-1]          # (0, pi/2]
        Fil = rim[:, None] + rf * (np.sin(al)[None, :, None] * dn[:, None] + (1 - np.cos(al))[None, :, None]
                                   * out[:, None])
        bw = S['brim_w'] + S['visor_w'] * front + S['brim_back'] * back
        u = np.linspace(0, 1, nb + 1)[1:]
        Bri = Fil[:, -1][:, None] + out[:, None] * (bw[:, None] * u[None, :])[..., None]
        # la visera se curva un poco hacia abajo en la punta (como una gorra), no es una tabla
        Bri[..., 2] -= (S['visor_curl'] * front)[:, None] * u[None, :] ** 2
        G = np.concatenate([Bri[:, ::-1], Fil[:, ::-1], P], 1)
        f, ci, cj = C.grid_faces(nu, G.shape[1], closed_u=True)
        return C.Part(G.reshape(-1, 3), f)


def mat_plastic(name, color):
    """Plastico inyectado brillante: base amarilla, barniz fino y un leve 'piel de naranja' en el relieve."""
    nb = C.NB(name)
    tc = nb.texco()
    n = nb.noise(tc.outputs['Object'], 38.0, 2.0, 0.5)
    nb.principled(Base_Color=color, Roughness=0.35, Specular_IOR_Level=0.5, Coat_Weight=0.35, Coat_Roughness=0.06,
                  Coat_IOR=1.5, Normal=nb.bump(n, 0.02, 0.01))
    return nb.mat


def mat_hair_bsdf(S):
    """Principled Hair BSDF (Chiang, melanina): raiz oscura -> puntas mas claras y calidas, brillo suave."""
    nb = C.NB('hair_curves')
    info = nb.node('ShaderNodeHairInfo')
    h = nb.node('ShaderNodeBsdfHairPrincipled')
    h.model = 'CHIANG'
    h.parametrization = 'MELANIN'
    nb.put(h.inputs['Melanin'], nb.maprange(info.outputs['Intercept'], 0.0, 1.0, *S['hair_melanin']))
    nb.put(h.inputs['Melanin Redness'], nb.maprange(info.outputs['Intercept'], 0.0, 1.0, *S['hair_redness']))
    for k, v in (('Roughness', 0.34), ('Radial Roughness', 0.42), ('Coat', 0.08), ('IOR', 1.55),
                 ('Random Color', 0.12), ('Random Roughness', 0.15)):
        h.inputs[k].default_value = v
    nb.nt.links.new(h.outputs[0], nb.out.inputs['Surface'])
    return nb.mat


def mat_scalp(S):
    """Cuero cabelludo tintado del color de la raiz (atributo scalpfade = 1 dentro, 0 en la linea del pelo):
    entre hebras no se ve piel clara."""
    nb = C.NB('hair_scalp')
    a = nb.node('ShaderNodeAttribute', attribute_name='scalpfade')
    nb.principled(Base_Color=S['hair_dark'], Roughness=0.75, Alpha=a.outputs['Fac'])
    return nb.mat


# ---------------------------------------------------------------- pelo (Hair Curves nativo)

HAIR_ASSETS = ('Clump Hair Curves', 'Hair Curves Noise', 'Frizz Hair Curves', 'Shrinkwrap Hair Curves',
               'Set Hair Curve Profile')


def hairline(phi):
    """Altura (z) de la linea del pelo por azimut (0 = frente): frente alta, sienes, patilla, nuca."""
    a = np.degrees(np.abs((phi + np.pi) % (2 * np.pi) - np.pi))
    return np.interp(a, *zip(*S['hairline']))


def hair_phi(P):
    return np.arctan2(P[..., 0], -(P[..., 1] - S['hair_axis_y']))


def build_scalp(S, head, hat):
    """Zona con pelo: caras de la cabeza entre la linea del pelo y algo por encima del borde del casco,
    un pelin por fuera de la piel. -> Part con color (scalpfade) para el tinte y la densidad."""
    V = head.v
    phi = hair_phi(V)
    hl = hairline(phi)
    keep = (V[:, 2] > hl - 0.03) & (V[:, 2] < hat.rim_z(phi) + S['hair_root_above'])
    fk = keep[head.f].all(1)
    f = head.f[fk]
    used = np.unique(f)
    remap = -np.ones(len(V), int)
    remap[used] = np.arange(len(used))
    nrm = C.unit(V[used] - np.array([0, S['hair_axis_y'], 0]))
    v = V[used] + nrm * 0.004
    fade = C.ss(-0.02, 0.07, V[used, 2] - hl[used])
    col = np.stack([fade, fade, fade, np.ones_like(fade)], -1)
    return C.Part(v, remap[f], col=col)


def build_guides(S, head_surf, hat, rng):
    """Curvas guia (raiz en el cuero cabelludo, peinado hacia abajo pegado a la cabeza con volumen, onda suave
    coherente entre vecinas). Bajo el borde del casco el pelo se ahueca hasta rozar la copa por dentro, asi el
    casco asienta sobre una masa de pelo. -> (puntos (n, k, 3), up (n, 3))."""
    n_dir, k = S['hair_guides_fib'], S['hair_guide_pts']
    i = np.arange(n_dir) + 0.5
    zz = 1 - 2 * i / n_dir
    az = np.pi * (1 + 5 ** 0.5) * i
    D = np.stack([np.sqrt(1 - zz ** 2) * np.cos(az), np.sqrt(1 - zz ** 2) * np.sin(az), zz], -1)
    P0 = C.head_points(D, S)
    phi = hair_phi(P0)
    keep = (P0[:, 2] > hairline(phi) + 0.01) & (P0[:, 2] < hat.rim_z(phi) + S['hair_root_above'])
    P0, phi = P0[keep], phi[keep]
    n = len(P0)
    a = np.degrees(np.abs(phi))
    hl = hairline(phi)
    over = np.interp(a, *zip(*S['hair_overhang']))
    L = np.clip((P0[:, 2] - hl) * 1.05 + over, 0.14, 0.62) * rng.uniform(0.85, 1.12, n)
    # direccion de peinado: abajo; flequillo algo barrido a un lado, sienes y patillas un poco hacia atras
    comb = np.zeros((n, 3))
    comb[:, 2] = -1.0
    fr = np.exp(-(a / 40) ** 2)
    comb[:, 0] += 0.3 * fr
    comb[:, 1] += 0.35 * np.exp(-((a - 85) / 30) ** 2)
    vol = S['hair_vol'] * rng.uniform(0.8, 1.2, n)
    G = np.zeros((n, k, 3))
    up = np.zeros((n, 3))
    s = np.linspace(0, 1, k)
    for g in range(n):
        p = P0[g].copy()
        loc, nor, _, _ = head_surf.bvh.find_nearest(C.Vector(p))
        nor = np.array(nor)
        up[g] = nor
        G[g, 0] = np.array(loc) + nor * 0.004
        ds = L[g] / (k - 1)
        for j in range(1, k):
            t = comb[g] - comb[g].dot(nor) * nor
            q = G[g, j - 1] + C.unit(t) * ds
            loc, nor, _, _ = head_surf.bvh.find_nearest(C.Vector(q))
            nor = np.array(nor)
            h = 0.004 + vol[g] * C.ss(0.0, 0.3, s[j]) * (1 - 0.35 * C.ss(0.7, 1.0, s[j]))
            G[g, j] = np.array(loc) + nor * h
    # onda suave: desplazamiento lateral (perpendicular al peinado sobre la piel), fase coherente por zona
    T = np.gradient(G, axis=1)
    Nn = C.unit(G - np.array([0, S['hair_axis_y'], 0]))
    Bn = C.unit(np.cross(T, Nn))
    arc = np.concatenate([np.zeros((n, 1)), np.cumsum(np.linalg.norm(np.diff(G, axis=1), axis=-1), 1)], 1)
    ph = 9.0 * P0[:, 2] + 2.0 * phi + rng.uniform(-0.6, 0.6, n)
    amp = S['hair_wave'] * rng.uniform(0.7, 1.3, n)
    w = amp[:, None] * np.sin(2 * np.pi * arc / S['hair_wave_len'] + ph[:, None]) * C.ss(0.0, 0.25, s)[None]
    G = G + Bn * w[..., None] + Nn * (0.4 * w * np.cos(ph)[:, None])[..., None]
    # bajo el borde del casco: ahueca el pelo hasta casi tocar la copa por dentro (y nunca la atraviesa)
    gphi = hair_phi(G)
    gz = G[..., 2]
    ax = np.array([0, S['hat_yc'], 0])
    rel = G - ax
    rho = np.hypot(rel[..., 0], rel[..., 1])
    rin = hat.inner_rho(gphi, gz) - S['hair_hat_gap']
    rz = hat.rim_z(gphi)
    fill = C.ss(rz - S['hair_fill_below'], rz - 0.02, gz) * (1 - C.ss(rz + 0.05, rz + 0.3, gz))
    target = np.where(rin > rho, rho + np.minimum(rin - rho, S['hair_fill_max']) * fill * S['hair_fill'], rho)
    above = gz > rz - 0.06
    target = np.where(above, np.minimum(target, rin), target)
    hor = rel.copy()
    hor[..., 2] = 0
    hor = C.unit(hor)
    G = G + hor * (target - rho)[..., None]
    for g in range(n):
        G[g] = head_surf.push_out(G[g], 0.006)
    return G, up


def hair_object(S, G, up, scalp_ob, head_ob, mat, parent):
    """Objeto Curves con las guias + modificador de nodos: Distribute Points on Faces (cuero cabelludo) ->
    Interpolate Curves (hijos de las guias) -> Clump / Noise / Frizz Hair Curves -> Shrinkwrap contra la cabeza
    -> Set Hair Curve Profile -> material. Guias y nodos son nativos de Blender 5.2 (assets de pelo)."""
    n, k = G.shape[:2]
    cv = bpy.data.hair_curves.new('hair_curves')
    cv.add_curves([k] * n)
    cv.position_data.foreach_set('vector', G.astype(np.float32).ravel())
    cv.attributes.new('up', 'FLOAT_VECTOR', 'CURVE').data.foreach_set('vector', up.astype(np.float32).ravel())
    cv.materials.append(mat)
    ob = bpy.data.objects.new('hair_curves', cv)
    bpy.context.scene.collection.objects.link(ob)
    ob.parent = parent
    lib = bpy.utils.resource_path('LOCAL') + '/datafiles/assets/nodes/procedural_hair_node_assets.blend'
    with bpy.data.libraries.load(lib) as (src, dst):
        dst.node_groups = [g for g in HAIR_ASSETS if g not in bpy.data.node_groups]
    ng = bpy.data.node_groups.new('bob_hair', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    N, Lk = ng.nodes, ng.links
    gin, gout = N.new('NodeGroupInput'), N.new('NodeGroupOutput')

    def node(kind, **inp):
        nd = N.new(kind)
        for key, v in inp.items():
            if isinstance(v, bpy.types.NodeSocket):
                Lk.new(v, nd.inputs[key])
            else:
                nd.inputs[key].default_value = v
        return nd

    def group(name, geo, **inp):
        nd = N.new('GeometryNodeGroup')
        nd.node_tree = bpy.data.node_groups[name]
        Lk.new(geo, nd.inputs['Geometry'])
        for key, v in inp.items():
            if isinstance(v, bpy.types.NodeSocket):
                Lk.new(v, nd.inputs[key])
            else:
                nd.inputs[key].default_value = v
        return nd.outputs['Geometry']

    oi = N.new('GeometryNodeObjectInfo')
    oi.transform_space = 'RELATIVE'
    oi.inputs['Object'].default_value = scalp_ob
    fade = node('GeometryNodeInputNamedAttribute')
    fade.data_type = 'FLOAT'
    fade.inputs['Name'].default_value = 'scalpfade'
    dist = node('GeometryNodeDistributePointsOnFaces', Mesh=oi.outputs['Geometry'], Density=S['hair_density'],
                Seed=3)
    pw = N.new('ShaderNodeMath')
    pw.operation = 'POWER'
    Lk.new(fade.outputs['Attribute'], pw.inputs[0])
    pw.inputs[1].default_value = 0.6
    Lk.new(pw.outputs[0], next(x for x in dist.inputs if x.name == 'Density Factor'))
    gup = node('GeometryNodeInputNamedAttribute')
    gup.data_type = 'FLOAT_VECTOR'
    gup.inputs['Name'].default_value = 'up'
    it = node('GeometryNodeInterpolateCurves', **{'Guide Curves': gin.outputs[0], 'Guide Up': gup.outputs['Attribute'],
                                                  'Points': dist.outputs['Points'], 'Point Up': dist.outputs['Normal'],
                                                  'Max Neighbors': 5})
    geo = it.outputs['Curves']
    geo = group('Clump Hair Curves', geo, Factor=S['hair_clump'], Shape=0.35, **{
        'Tip Spread': 0.004, 'Existing Guide Map': False, 'Guide Distance': S['hair_clump_dist'], 'Seed': 5})
    geo = group('Hair Curves Noise', geo, Factor=1.0, Distance=0.007, Scale=6.0, Shape=0.6,
                **{'Scale along Curve': 2.0, 'Seed': 2})
    geo = group('Frizz Hair Curves', geo, Factor=1.0, Distance=0.0025, Shape=0.8, Seed=4)
    geo = group('Shrinkwrap Hair Curves', geo, Surface=head_ob, Factor=1.0, **{'Offset Distance': 0.006,
                                                                                'Above Surface': 0.0,
                                                                                'Lock Roots': True})
    geo = group('Set Hair Curve Profile', geo, Radius=S['hair_radius'], Shape=0.25)
    sm = node('GeometryNodeSetMaterial', Geometry=geo)
    sm.inputs['Material'].default_value = mat
    Lk.new(sm.outputs['Geometry'], gout.inputs[0])
    mod = ob.modifiers.new('hair', 'NODES')
    mod.node_group = ng
    return ob


def build_hood(S, surfs, ground):
    """Capucha bajada: tubo blando alrededor de la nuca que se abomba en la espalda y remata junto al cuello.
    surfs: Surface de lo que tiene debajo (cabeza, torso, cuello); el centro se aparta con margen por punto.
    ground: Surface del torso; la capucha se apoya sobre el trapecio (cae con la linea del hombro)."""
    n = 220
    t = np.linspace(0, 1, n)
    phi = np.radians(46 + 268 * t)                      # de delante-dcha por la nuca a delante-izda
    dw = (phi + np.pi) % (2 * np.pi) - np.pi            # 0 en la espalda
    back = np.exp(-(dw / 1.05) ** 2)
    r = S['hood_r0'] + S['hood_back'] * back
    z = np.full(n, S['hood_z0'])
    P = np.stack([r * np.sin(phi), S['neck_y'] - r * np.cos(phi), z], -1)
    O = C.unit(np.stack([np.sin(phi), -np.cos(phi), 0.3 * back], -1))
    taper = (0.3 + 0.7 * C.ss(0.0, 0.14, t) * C.ss(1.0, 0.86, t)) * (1 + 0.04 * np.sin(4 * phi))
    w = (S['hood_w0'] + S['hood_wb'] * back) * taper    # alto del tubo (vertical a la espalda)
    h = (S['hood_h0'] + S['hood_hb'] * back) * taper    # grosor (radial)
    for i in range(n):
        loc, _ = ground.ray((P[i, 0], P[i, 1], 1.0), (0.0, 0.0, -1.0))
        if loc is not None and loc[2] > z[i] - 0.35:
            P[i, 2] = min(z[i], loc[2] + w[i] * 0.8 + 0.04)
    P = C.smooth_path(P, 3, keep_root=False)
    for _ in range(3):
        # sobre el torso la seccion es una elipse (w en vertical, h en radial): margen segun la normal
        for i in range(n):
            loc, nor, _, dist = ground.bvh.find_nearest(Vector(P[i]))
            if loc is None:
                continue
            nor = np.array(nor)
            m = np.hypot(w[i] * nor[2], h[i] * np.hypot(nor[0], nor[1])) + S['hood_gap'] + 0.05
            if np.dot(P[i] - np.array(loc), nor) < m:
                P[i] = np.array(loc) + nor * m
        P = C.smooth_path(P, 4, keep_root=False)
    head_surf, collar_surf = surfs
    P = head_surf.push_out(P, h + S['hood_gap'] + 0.03)
    P = C.smooth_path(P, 2, keep_root=False)
    # costura con el cuello del jersey: el borde interior del tubo apoya en la abertura del cuello (medio tubo
    # metido en el canale) y los remates delanteros entran del todo en el, sin bolas ni puntas sueltas
    e = 1 - C.ss(0.0, 0.12, t) * C.ss(1.0, 0.88, t)
    for i in range(n):
        d = np.array([P[i, 0], P[i, 1] - S['neck_y'], 0.0])
        rho = np.linalg.norm(d)
        d /= rho
        loc, _ = collar_surf.ray((0.0, S['neck_y'], P[i, 2]), tuple(d))
        if loc is None:
            continue
        rc = np.hypot(loc[0], loc[1] - S['neck_y'])
        target = max(rho, rc + 0.5 * h[i]) * (1 - e[i]) + (rc - h[i] - 0.015) * e[i]
        P[i, :2] = np.array([0.0, S['neck_y']]) + d[:2] * target
    P = C.smooth_path(P, 2, keep_root=False)
    part = C.sweep(P, O, w, h, 40, expo=2.5,
                   hoff=lambda i, th, k=phi: 0.01 * np.sin(5 * th + 3 * k[:, None])
                   + 0.006 * np.sin(9 * th - 5 * k[:, None]))
    return part


def build_collar(S, G):
    """Cuello alto de canale (feedback 8): arriba se enrolla y entra dentro del cuello (sin hueco cuello-jersey) y
    abajo se abre como un embudo que se mete bajo la superficie del torso (sin hueco jersey-torso). Perfil por
    angulo: labio interior -> remate enrollado -> cuello recto -> abertura hasta el torso.
    G: rejilla del torso (body_torso_grid), cuyos anillos comparten angulo con el cuello."""
    nu = G.shape[0]
    th = np.radians(np.linspace(-180, 180, nu, endpoint=False))
    rn, zt = S['neck_r'], S['collar_top']
    seg = np.linalg.norm(np.diff(G, axis=1), axis=2)
    arc = np.concatenate([np.zeros((nu, 1)), np.cumsum(seg, 1)], 1)
    rings = []
    for k in range(nu):
        # base: sobre el trapecio a collar_base del anillo del cuello, hundida bajo la superficie del torso
        j = int(np.searchsorted(arc[k], S['collar_base']))
        du = G[(k + 1) % nu, j] - G[k - 1, j]
        ds = G[k, j + 1] - G[k, j - 1]
        n = C.unit(np.cross(du, ds))
        out = np.array([np.sin(th[k]), -np.cos(th[k]), 0.0])
        if np.dot(n, out) + n[2] < 0:
            n = -n
        b = G[k, j] - n * 0.045
        rb, zb = np.hypot(b[0], b[1] - S['neck_y']), b[2]
        top = [(rn - 0.035, zt - 0.08), (rn - 0.012, zt - 0.02), (rn + 0.008, zt + 0.012), (rn + 0.035, zt + 0.01),
               (rn + 0.052, zt - 0.025), (rn + 0.056, zt - 0.08)]
        # el embudo pasa por fuera del borde del torso (anillo del cuello) y luego entra bajo su superficie
        R = G[k, 0]
        rq, zq = np.hypot(R[0], R[1] - S['neck_y']) + 0.035, R[2] + 0.01
        p0, p1, p2 = np.array([rn + 0.056, zt - 0.1]), np.array([rn + 0.062, zq + 0.04]), np.array([rq, zq])
        q = np.linspace(0, 1, 16)[1:, None]
        flare = (1 - q) ** 2 * p0 + 2 * q * (1 - q) * p1 + q ** 2 * p2
        q = np.linspace(0, 1, 10)[1:, None]
        flare = np.concatenate([p0[None], flare, p2 + (np.array([rb, zb]) - p2) * q])
        prof = np.concatenate([np.array(top), flare])
        rings.append(np.stack([out[0] * prof[:, 0], S['neck_y'] + out[1] * prof[:, 0], prof[:, 1]], -1))
    P = np.stack(rings, 0)
    nv = P.shape[1]
    # canale: relieve radial en la cara exterior (desde el remate hacia abajo, se apaga al entrar en el torso)
    rib = S['collar_rib'] * ((0.5 + 0.5 * np.cos(S['collar_ribs'] * th)) ** 0.6 - 0.5)
    k = np.concatenate([np.zeros(3), C.ss(0.0, 1.0, np.linspace(0, 1, 3)),
                        1 - 0.7 * C.ss(0.6, 1.0, np.linspace(0, 1, 25))])
    rad = np.stack([np.sin(th), -np.cos(th), np.zeros(nu)], -1)
    P = P + rad[:, None, :] * (rib[:, None] * k[None, :])[..., None]
    f, ci, cj = C.grid_faces(nu, nv, closed_u=True)
    return C.Part(P.reshape(-1, 3), f, np.stack([ci / nu, cj / nv], -1))


def build_strings(S, surfs):
    """Cordones de la capucha: dos cuerdas que caen del cuello sobre el pecho con su piolín en la punta."""
    x0, y0, z0 = S['strings_at']
    parts = []
    for side in (-1, 1):
        # la raiz nace dentro del cuello del jersey (sale de la tela, sin punta suelta)
        loc, _ = surfs[-1].ray((side * x0, -3.0, z0), (0.0, 1.0, 0.0))
        if loc is not None:
            y0 = loc[1] + 0.025
        ctrl = np.array([(side * x0, y0, z0), (side * (x0 + 0.03), y0 - 0.22, z0 - 0.34),
                         (side * (x0 - 0.02), y0 - 0.38, z0 - 0.62), (side * (x0 - 0.05), y0 - 0.45, z0 - 0.82)])
        tt = np.linspace(0, 1, 60)
        P = np.stack([np.interp(tt, np.linspace(0, 1, len(ctrl)), ctrl[:, k]) for k in range(3)], -1)
        P = C.smooth_path(P, 4)
        for _ in range(3):
            P = surfs[0].push_out(P, 0.028)
            # el cuello del jersey es una lamina doblada (parte hundida bajo el torso): se aparta por delante con
            # un rayo, no por el punto mas cercano, para que el cordon no se pegue a la cara interior
            # y el cordon cae apoyado en el pecho (antes flotaba): se pega a lo que tenga delante
            for i in range(1, len(P)):
                ys = [loc[1] for loc, _ in (s.ray((P[i, 0], -3.0, P[i, 2]), (0.0, 1.0, 0.0)) for s in surfs)
                      if loc is not None]
                if ys:
                    P[i, 1] = min(ys) - 0.045    # por encima del relieve del canale
            P = C.smooth_path(P, 2, keep_root=False)
        O = np.tile([0.0, -1.0, 0.0], (len(P), 1))
        rad = np.full(len(P), 0.017)
        parts.append(C.sweep(P, O, rad, rad, 10))
        tip = P[-1]
        ag = C.sphere_part(1.0, 20, 10)
        ag.v = ag.v * np.array([0.03, 0.03, 0.055]) + tip - C.unit(P[-1] - P[-3]) * 0.03
        parts.append(ag)
    return C.Part.join(parts)


# ---------------------------------------------------------------- cuerpo: torso anatomico + brazos de una pieza

def body_torso_grid(S):
    """Rejilla (nphi, ns, 3) del torso: anillo del cuello -> trapecio inclinado (Hermite) -> pared cuya planta
    (superelipse con fondo distinto delante/detras) cambia con z: hombro, pecho mas ancho, cintura (V suave)."""
    nphi, ns = 360, 240
    phis = np.radians(np.linspace(-180, 180, nphi, endpoint=False))
    sx, cy = np.sin(phis), -np.cos(phis)
    zk = np.array(S['body_z'])
    zf = np.linspace(zk[0], zk[-1], 200)

    def level(key):
        v = np.interp(-zf, -zk, np.array(S[key]))
        for _ in range(30):
            v[1:-1] = 0.5 * v[1:-1] + 0.25 * (v[:-2] + v[2:])
        return lambda z: np.interp(-np.asarray(z), -zf, v)
    fa, ff, fb = level('body_a'), level('body_bf'), level('body_bb')

    def outer(z):
        A, B = fa(z), np.where(cy < 0, ff(z), fb(z))
        n = 2.6
        rs = (np.abs(sx / A) ** n + np.abs(cy / B) ** n) ** (-1 / n)
        return np.stack([rs * sx, S['torso_y'] + rs * cy], -1)
    neck = np.stack([S['neck_ring_r'] * sx, S['neck_y'] + S['neck_ring_r'] * cy], -1)
    zn, zw, zb = S['torso_zn'], zk[0], zk[-1]
    t = np.linspace(0, 1, 120)[:, None]
    h00, h10, h01, h11 = 2 * t**3 - 3 * t**2 + 1, t**3 - 2 * t**2 + t, -2 * t**3 + 3 * t**2, t**3 - t**2
    cap = h00 * np.array([0.0, zn]) + h10 * np.array(S['shoulder_t0']) + h01 * np.array([1.0, zw]) \
        + h11 * np.array(S['shoulder_t1'])
    wall_z = np.linspace(zw, zb, 120)[1:]
    prof = np.concatenate([cap, np.stack([np.ones_like(wall_z), wall_z], -1)])
    seg = np.linalg.norm(np.diff(prof * np.array([1.0, 1.0]), axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    sp = np.interp(np.linspace(0, arc[-1], ns), arc, prof[:, 0])
    sz = np.interp(np.linspace(0, arc[-1], ns), arc, prof[:, 1])
    P = np.zeros((nphi, ns, 3))
    for j in range(ns):
        o = outer(min(sz[j], zw))
        P[:, j, :2] = neck + (o - neck) * sp[j]
        P[:, j, 2] = sz[j]
    return P


def arm_path(ctrl, n=160):
    """Eje suave (Catmull-Rom) y radio de un brazo a partir de sus puntos de control (x, y, z, r)."""
    Q = np.asarray(ctrl, float)
    Q = np.concatenate([2 * Q[:1] - Q[1:2], Q, 2 * Q[-1:] - Q[-2:-1]])
    out = []
    for i in range(1, len(Q) - 2):
        p0, p1, p2, p3 = Q[i - 1], Q[i], Q[i + 1], Q[i + 2]
        for t in np.linspace(0, 1, 40, endpoint=False):
            out.append(0.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t ** 2
                              + (3 * p1 - p0 - 3 * p2 + p3) * t ** 3))
    out.append(Q[-2])
    out = np.array(out)
    seg = np.linalg.norm(np.diff(out[:, :3], axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)])
    s = np.linspace(0, arc[-1], n)
    R = np.stack([np.interp(s, arc, out[:, k]) for k in range(4)], -1)
    return R[:, :3], R[:, 3], s


def closed_tube(P, rad, na=48, cap_rings=8):
    """Tubo cerrado con casquetes redondeados (para el SDF): -> (verts, faces) en listas."""
    T = C.unit(np.gradient(P, axis=0))
    ref = np.array([0.0, 0.0, 1.0])
    W = C.unit(np.cross(T, np.where(np.abs(T[:, 2:3]) > 0.9, [1.0, 0, 0], ref)))
    Hh = np.cross(W, T)
    th = np.linspace(0, C.TAU, na, endpoint=False)
    rings = [P[i] + rad[i] * (np.cos(th)[:, None] * W[i] + np.sin(th)[:, None] * Hh[i]) for i in range(len(P))]
    a = np.linspace(0, np.pi / 2, cap_rings + 1)[1:-1]
    start = [P[0] - T[0] * rad[0] * np.sin(x) + rad[0] * np.cos(x) * (np.cos(th)[:, None] * W[0]
             + np.sin(th)[:, None] * Hh[0]) for x in a[::-1]]
    end = [P[-1] + T[-1] * rad[-1] * np.sin(x) + rad[-1] * np.cos(x) * (np.cos(th)[:, None] * W[-1]
           + np.sin(th)[:, None] * Hh[-1]) for x in a]
    rings = start + rings + end
    V = np.concatenate(rings + [[P[0] - T[0] * rad[0]], [P[-1] + T[-1] * rad[-1]]])
    nr = len(rings)
    faces = [(i * na + k, i * na + (k + 1) % na, (i + 1) * na + (k + 1) % na, (i + 1) * na + k)
             for i in range(nr - 1) for k in range(na)]
    p0, p1 = nr * na, nr * na + 1
    faces += [(p0, (k + 1) % na, k) for k in range(na)]
    faces += [(p1, (nr - 1) * na + k, (nr - 1) * na + (k + 1) % na) for k in range(na)]
    return V, faces


def closed_torso(P):
    nphi, ns = P.shape[:2]
    V = np.concatenate([P.reshape(-1, 3), [[0.0, P[:, 0, 1].mean(), P[0, 0, 2]],
                                            [0.0, P[:, -1, 1].mean(), P[0, -1, 2]]]])
    f, _, _ = C.grid_faces(nphi, ns, closed_u=True)
    faces = [tuple(x) for x in f.tolist()]
    p0, p1 = nphi * ns, nphi * ns + 1
    faces += [(p0, ((i + 1) % nphi) * ns, i * ns) for i in range(nphi)]
    faces += [(p1, i * ns + ns - 1, ((i + 1) % nphi) * ns + ns - 1) for i in range(nphi)]
    return V, faces


def sdf_union(pieces, voxel, fillet):
    """Une mallas cerradas en una sola superficie (Mesh to SDF Grid -> union -> SDF Fillet -> Grid to Mesh):
    el brazo sale del hombro sin costura de bola y la axila queda redondeada. -> Part de triangulos.
    El nodo Mesh to SDF Grid devuelve una rejilla vacia con voxeles por debajo de ~0.035 (Blender 5.2), asi que se
    trabaja a escala k (voxel efectivo 0.05) y se deshace al leer."""
    k_sc = 0.05 / voxel
    objs = []
    for k, (V, faces) in enumerate(pieces):
        me = bpy.data.meshes.new(f'_sdf{k}')
        me.from_pydata((np.asarray(V) * k_sc).tolist(), [], faces)
        ob = bpy.data.objects.new(f'_sdf{k}', me)
        bpy.context.scene.collection.objects.link(ob)
        objs.append(ob)
    host = bpy.data.objects.new('_sdf_host', bpy.data.meshes.new('_sdf_host'))
    bpy.context.scene.collection.objects.link(host)
    ng = bpy.data.node_groups.new('_sdf_union', 'GeometryNodeTree')
    ng.interface.new_socket('Geometry', in_out='OUTPUT', socket_type='NodeSocketGeometry')
    out = ng.nodes.new('NodeGroupOutput')
    boo = ng.nodes.new('GeometryNodeSDFGridBoolean')
    boo.operation = 'UNION'
    for k, ob in enumerate(objs):
        info = ng.nodes.new('GeometryNodeObjectInfo')
        info.inputs['Object'].default_value = ob
        sdf = ng.nodes.new('GeometryNodeMeshToSDFGrid')
        sdf.inputs['Voxel Size'].default_value = voxel * k_sc
        sdf.inputs['Band Width'].default_value = 4
        ng.links.new(info.outputs['Geometry'], sdf.inputs['Mesh'])
        ng.links.new(sdf.outputs['SDF Grid'], next(i for i in boo.inputs if i.enabled and i.is_multi_input))
    fil = ng.nodes.new('GeometryNodeSDFGridFillet')
    fil.inputs['Iterations'].default_value = fillet
    g2m = ng.nodes.new('GeometryNodeGridToMesh')
    ng.links.new(boo.outputs['Grid'], fil.inputs['Grid'])
    ng.links.new(fil.outputs['Grid'], g2m.inputs['Grid'])
    ng.links.new(g2m.outputs['Mesh'], out.inputs[0])
    host.modifiers.new('sdf', 'NODES').node_group = ng
    bpy.context.view_layer.update()
    ev = host.evaluated_get(bpy.context.evaluated_depsgraph_get())
    me = ev.to_mesh()
    me.calc_loop_triangles()
    v = np.zeros(len(me.vertices) * 3)
    me.vertices.foreach_get('co', v)
    f = np.zeros(len(me.loop_triangles) * 3, np.int64)
    me.loop_triangles.foreach_get('vertices', f)
    ev.to_mesh_clear()
    for ob in objs + [host]:
        me = ob.data
        bpy.data.objects.remove(ob)
        bpy.data.meshes.remove(me)
    bpy.data.node_groups.remove(ng)
    return C.Part(v.reshape(-1, 3) / k_sc, f.reshape(-1, 3))


def vertex_normals(part):
    v, f = part.v, part.f
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    return C.unit(n)


def arm_coords(V, P, rad, arc, chunk=20000):
    """Para cada vertice: distancia con signo al tubo del brazo, posicion a lo largo (arco), angulo alrededor
    (marco fijo por tramo) e indice del punto del eje mas cercano."""
    T = C.unit(np.gradient(P, axis=0))
    W = C.unit(np.cross(T, [0.0, 0.0, 1.0]) + np.cross(T, [0.0, 1.0, 0.0]) * 1e-3)
    Hh = np.cross(W, T)
    d, s, th, idx = (np.zeros(len(V)) for _ in range(4))
    for a in range(0, len(V), chunk):
        X = V[a:a + chunk]
        dd = np.linalg.norm(X[:, None] - P[None], axis=-1) - rad[None]
        i = dd.argmin(1)
        r = X - P[i]
        d[a:a + chunk] = dd[np.arange(len(X)), i]
        s[a:a + chunk] = arc[i] + np.einsum('ij,ij->i', r, T[i])
        th[a:a + chunk] = np.arctan2(np.einsum('ij,ij->i', r, Hh[i]), np.einsum('ij,ij->i', r, W[i]))
        idx[a:a + chunk] = i
    return d, s, th, idx.astype(int)


def build_body(S, arms):
    """Torso + brazos (lista de (sx, ctrl)) en una sola malla de punto. -> (Part con color de cavidad, info de
    brazos para la pelusa). Relieve: canale vertical en el torso, canale a lo largo de la manga, costura de sisa,
    pliegues de tela en el codo y sobre el punio, y punio acanalado."""
    G = body_torso_grid(S)
    nphi, ns = G.shape[:2]
    pieces = [closed_torso(G)]
    info = []
    for sx, ctrl in arms:
        c = np.asarray(ctrl, float) * np.array([sx, 1, 1, 1]) if sx else np.asarray(ctrl, float)
        P, rad, arc = arm_path(c)
        pieces.append(closed_tube(P, rad))
        info.append((P, rad, arc))
    body = sdf_union(pieces, S['body_voxel'], S['body_fillet'])
    V = body.v
    N = vertex_normals(body)
    if np.dot(N[np.argmin(V[:, 1])], [0, -1, 0]) < 0:
        body.f = body.f[:, ::-1]
        N = -N
    # torso: coordenadas de punto (u alrededor desde el centro delantero, v desde el cuello) por proyeccion
    # u por angulo (columnas verticales y numero entero de columnas: sin rombos ni costura en la espalda)
    ru = round(C.TAU * 1.1 / S['knit_col']) * S['knit_col'] / C.TAU
    u = np.tile(((np.arange(nphi) - nphi // 2) * C.TAU / nphi * ru)[:, None], (1, ns))
    du = np.full((nphi, ns), C.TAU / nphi * ru)
    dv = np.linalg.norm(np.diff(G, axis=1), axis=-1)
    v = np.concatenate([np.zeros((nphi, 1)), np.cumsum(dv, 1)], 1)
    f, _, _ = C.grid_faces(nphi, ns, closed_u=True)
    bvh = C.BVHTree.FromPolygons(G.reshape(-1, 3).tolist(), f.tolist())
    loc, fi, dT = np.zeros((len(V), 3)), np.zeros(len(V), int), np.zeros(len(V))
    for k, p in enumerate(V.tolist()):
        lc, _, fi[k], dT[k] = bvh.find_nearest(p)
        loc[k] = lc
    i, j = np.divmod(fi, ns - 1)
    i1 = (i + 1) % nphi
    e1, e2 = G[i1, j] - G[i, j], G[i, j + 1] - G[i, j]
    q = loc - G[i, j]
    g11, g12, g22 = (np.einsum('ij,ij->i', a, b) for a, b in ((e1, e1), (e1, e2), (e2, e2)))
    det = g11 * g22 - g12 * g12 + 1e-12
    b1, b2 = np.einsum('ij,ij->i', q, e1), np.einsum('ij,ij->i', q, e2)
    a1, a2 = (g22 * b1 - g12 * b2) / det, (g11 * b2 - g12 * b1) / det
    uT = u[i, j] + a1 * du[i, j]
    vT = v[i, j] + a2 * (v[i, j + 1] - v[i, j])
    knit_torso = C.knit_height(uT, vT, S)
    # mangas: canale a lo largo, pliegues y punio; peso por cercania al tubo frente al torso
    wsum = np.zeros(len(V))
    hs = np.zeros(len(V))
    seam = np.zeros(len(V))
    for P, rad, arc in info:
        dA, s, th, idx = arm_coords(V, P, rad, arc)
        w = C.ss(-0.03, 0.03, dT - dA) * (dA < 0.12)
        L = arc[-1]
        r = rad[idx]
        hk = C.knit_height(th * r, s, S)
        # pliegues: hacia dentro del codo (lado concavo) segun lo doblado que este el brazo, anillos blandos
        # que se arrugan sobre el punio y dos pliegues largos que caen de la axila
        bend = np.zeros(len(P))
        bvec = np.zeros_like(P)
        for i in range(4, len(P) - 4):
            m = 0.5 * (P[i - 4] + P[i + 4]) - P[i]
            bend[i] = np.linalg.norm(m)
            bvec[i] = m / (bend[i] + 1e-9)
        kb = int(bend.argmax())
        se = arc[kb]
        rv = C.unit(V - P[idx])
        inner = C.ss(-0.1, 0.7, rv @ bvec[kb])
        amp = np.clip(bend[kb] / 0.06, 0.25, 1.0)
        elbow = 0.032 * amp * np.cos(C.TAU * (s - se) / 0.15 + 0.6 * np.sin(2 * th)) \
            * np.exp(-((s - se) / 0.3) ** 2) * (0.35 + 0.65 * inner)
        bunch = 0.022 * np.sin(C.TAU * (s - L) / 0.12 + 0.8 * np.sin(th + 1.3)) \
            * C.ss(L - 0.75, L - 0.45, s) * C.ss(L - 0.2, L - 0.3, s)
        drape = 0.014 * np.cos(2 * th - 2.2 * s) * C.ss(0.35, 0.7, s) * C.ss(se - 0.1, se - 0.4, s)
        cuff = C.ss(L - 0.32, L - 0.26, s)
        hk = hk * (1 - cuff) + cuff * (0.022 * (0.5 + 0.5 * np.cos(30 * th)) ** 0.6 - 0.012)
        hs += w * (hk + elbow + bunch + drape)
        wsum += w
        seam = np.maximum(seam, np.exp(-((dT - dA) / 0.016) ** 2) * (dA < 0.08) * C.ss(0.2, 0.5, s))
    wsum = np.clip(wsum, 0, 1)
    h = knit_torso * (1 - wsum) + hs
    h = h * (1 - 0.7 * seam) + 0.016 * seam * (0.65 + 0.35 * np.cos(C.TAU * (vT + uT) / 0.032))
    body.v = V + N * h[:, None]
    cav = C.ss(0.0, S['cable_depth'] * 0.8, h)
    body.col = np.stack([cav, cav, cav, np.ones_like(cav)], -1)
    # tapa del cuello: se abre dentro del cuello alto (que la tapa por fuera) para no atravesarlo
    rr = np.hypot(V[:, 0], V[:, 1] - S['neck_y'])
    lid = (rr < S['collar_r'] + S['collar_rib'] + 0.02) & (V[:, 2] > S['torso_zn'] - 0.25)
    body.f = body.f[~lid[body.f].all(1)]
    return compact(body), info


def compact(body):
    used = np.unique(body.f)
    remap = -np.ones(len(body.v), int)
    remap[used] = np.arange(len(used))
    body.v, body.col, body.f = body.v[used], body.col[used], remap[body.f]
    return body


def open_cuff(body, info, hand_info):
    """Abre el punio del brazo con mano (la mano entra en la manga) y le pone un borde enrollado."""
    rims = []
    for P, rad, arc in info:
        if not any(np.linalg.norm(P[-1] - w) < 0.6 for w in hand_info):
            continue
        T = C.unit(P[-1] - P[-4])
        cut = P[-1] - T * 0.02
        bad = ((body.v - cut) @ T > 0) & (np.linalg.norm(body.v - P[-1], axis=1) < rad[-1] + 0.15)
        keep = ~bad[body.f].any(1)
        body.f = body.f[keep]
        ring = []
        for t in np.linspace(0, C.TAU, 48, endpoint=False):
            W = C.unit(np.cross(T, [0.0, 0.0, 1.0]))
            Hh = np.cross(W, T)
            ring.append(cut + (W * math.cos(t) + Hh * math.sin(t)) * (rad[-1] + 0.01))
        rims.append(C.sweep(np.array(ring), np.tile(T, (48, 1)), np.full(48, 0.04), np.full(48, 0.04), 12,
                            closed=True))
    return compact(body), (C.Part.join(rims) if rims else None)


def body_center(info):
    """Centro interior para orientar la pelusa: eje del brazo mas cercano o eje del torso."""
    def f(X):
        Q = np.zeros_like(X)
        Q[:, 1] = 0.12
        Q[:, 2] = X[:, 2]
        best = np.full(len(X), 1e9)
        for P, rad, _ in info:
            dd = np.linalg.norm(X[:, None] - P[None], axis=-1) - rad[None]
            i = dd.argmin(1)
            m = dd[np.arange(len(X)), i]
            sel = (m < 0.1) & (m < best)
            Q[sel], best[sel] = P[i[sel]], m[sel]
        return Q
    return f


def build(S):
    t0 = time.time()
    root = C.empty('bob')
    head = C.build_head(S)
    head_surf = C.Surface(head)
    head_ob = C.make_object('head', head, None, root)
    spots = []
    for sx in (-1, 1):
        d = np.array([0.58 * sx, -0.74, -0.32])
        d /= np.linalg.norm(d)
        spots.append((tuple(C.head_points(d[None], S)[0]), 0.24, S['blush'], 0.3))
    nd = np.array([0.0, -1.0, -0.34])
    nd /= np.linalg.norm(nd)
    spots.append((tuple(C.head_points(nd[None], S)[0] + nd * 0.05), 0.14, S['nose_tip'], 0.5))
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
        hair=mat_hair_bsdf(S),
        scalp=mat_scalp(S),
        hardhat=mat_plastic('hardhat', S['hardhat']),
        hoodie=C.mat_wool('hoodie', S['sweater'], 120.0),
        hoodie_knit=C.mat_wool('hoodie_knit', S['sweater'], 120.0, cavity='knitcav'),
        hoodie_fuzz=C.mat_wool('hoodie_fuzz', tuple(c * 1.1 for c in S['sweater'][:3]) + (1,), 140.0),
        string=C.mat_flat('string', S['string_color'], rough=0.6, sheen=0.3),
        bubble=C.mat_flat('bubble', L('#ffffff'), rough=0.3, coat=0.6, sss=0.3),
        accent=C.mat_flat('accent', L('#0F7F6C'), rough=0.3, coat=0.6),
        error=C.mat_flat('error', L('#e3383a'), rough=0.3, coat=0.6),
        white=C.mat_flat('white', L('#ffffff'), rough=0.3),
        sweat=C.mat_flat('sweat', L('#9fd4ff'), rough=0.05, coat=1.0, sss=0.4),
        spark=C.mat_flat('spark', L('#ffc93d'), rough=0.25, coat=0.6),
        done=C.mat_flat('done', L('#2fb36b'), rough=0.3, coat=0.6),
        nail=C.mat_flat('nail', L('#E0AF8C'), rough=0.18, coat=0.9, sss=0.3),
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
    # cejas y boca: una malla por pieza con la expresion neutra como Basis y una shape key por expresion
    brows = {}
    for s in (-1, 1):
        shapes = {n: C.brow_part(S, head_surf, s, e['brow'][s]) for n, e in EXPR.items()}
        brows[s] = C.add_shape_keys(C.make_object(f'brow{s:+d}', shapes['neutral'], mats['brow'], root,
                                                  colors=True, colname='browcol'), shapes)
    mouth_shapes = {n: C.mouth_parts(dict(S, **e.get('lips', {})), head_surf, e['mouth']) for n, e in EXPR.items()}
    mouth = []
    for key, mat in (('cavity', 'cavity'), ('teeth', 'teeth'), ('tongue', 'tongue'), ('tongue_out', 'tongue'),
                     ('line', 'lipline')):
        shapes = {n: m[key] for n, m in mouth_shapes.items()}
        mouth.append(C.add_shape_keys(C.make_object(f'mouth_{key}', shapes['neutral'], mats[mat], root), shapes))
    lips = {n: C.Part.join([m['lip_up'], m['lip_lo']]) for n, m in mouth_shapes.items()}
    mouth.append(C.add_shape_keys(C.make_object('mouth_lips', lips['neutral'], mats['lip'], root, colors=True,
                                                colname='lipfade'), lips))

    hh = HardHat(S)
    hat = hh.build()
    hat_ob = C.make_object('hardhat', hat, mats['hardhat'], root)
    bm = bmesh.new()
    bm.from_mesh(hat_ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)       # cierra el polo de la copa
    bm.normal_update()
    top = max(bm.faces, key=lambda fc: fc.calc_center_median().z)
    if top.normal.z < 0:
        bmesh.ops.reverse_faces(bm, faces=bm.faces)
    bm.to_mesh(hat_ob.data)
    bm.free()
    hat_ob.data.shade_smooth()
    sol = hat_ob.modifiers.new('grosor', 'SOLIDIFY')
    sol.thickness, sol.offset, sol.use_even_offset, sol.use_rim = hh.thick, -1.0, True, True
    bev = hat_ob.modifiers.new('canto', 'BEVEL')
    bev.limit_method, bev.angle_limit, bev.width, bev.segments = 'ANGLE', math.radians(70), 0.01, 3
    hat_ob.modifiers.new('suave', 'WEIGHTED_NORMAL').keep_sharp = False
    # holgura cabeza-copa (el pelo necesita sitio debajo)
    hv = head.v[(head.v[:, 2] > hh.rim_z(hair_phi(head.v)) - 0.02)]
    gap = hh.inner_rho(hair_phi(hv), hv[:, 2]) - np.hypot(hv[:, 0], hv[:, 1] - S['hat_yc'])
    print(f'[bob] holgura cabeza-casco min {gap.min():.3f} media {gap.mean():.3f}', flush=True)

    frng = np.random.default_rng(23)

    def axis_center(z0=None):
        def f(P):
            Q = np.zeros_like(P)
            Q[:, 1] = 0.12
            Q[:, 2] = P[:, 2] if z0 is None else np.minimum(P[:, 2], z0)
            return Q
        return f

    # sudadera: una malla por postura de brazos (reposo; y una por pose de manos con su brazo levantado)
    tb = time.time()
    torso, info = build_body(S, [(-1, ARM_REST), (1, ARM_REST)])
    body_ob = C.make_object('hoodie', torso, mats['hoodie_knit'], root, colors=True, colname='knitcav')
    C.make_object('hoodie_fuzz', C.wool_fuzz(torso, S['fuzz'] * 4, frng, body_center(info)), mats['hoodie_fuzz'],
                  body_ob)
    bodies, body_parts = {None: [body_ob]}, {}
    for pname, pose in HAND_POSES.items():
        arms = [(0, pose[sd]['arm']) if pose.get(sd) else (sx, ARM_REST) for sd, sx in (('R', -1), ('L', 1))]
        part, pinfo = build_body(S, arms)
        part, rim = open_cuff(part, pinfo, [np.array(pose[sd]['wrist']) for sd in 'RL' if pose.get(sd)])
        ob = C.make_object(f'hoodie_{pname}', part, mats['hoodie_knit'], root, colors=True, colname='knitcav')
        C.make_object(f'hoodie_fuzz_{pname}', C.wool_fuzz(part, S['fuzz'] * 4, frng, body_center(pinfo)),
                      mats['hoodie_fuzz'], ob)
        bodies[pname] = [ob, ob.children[0]]
        if rim is not None:
            bodies[pname].append(C.make_object(f'hoodie_cuff_{pname}', rim, mats['hoodie'], root))
        body_parts[pname] = part
    bodies[None].append(body_ob.children[0])
    print(f'[bob] cuerpo (torso + brazos SDF): {len(torso.v)} vertices, {time.time() - tb:.1f}s', flush=True)
    G = body_torso_grid(S)
    gf, _, _ = C.grid_faces(*G.shape[:2], closed_u=True)
    ground = C.Part(G.reshape(-1, 3), gf)
    ground = C.orient_out(ground, (0.0, S['torso_y'], -2.5))
    collar = C.orient_out(build_collar(S, G), (0.0, S['neck_y'], -1.2))
    C.make_object('collar', collar, mats['hoodie'], root)
    C.make_object('neck', C.build_neck(S), skin, root)
    hood = build_hood(S, [head_surf, C.Surface(collar)], C.Surface(ground))
    C.make_object('hood', hood, mats['hoodie'], root)
    strings = build_strings(S, [C.Surface(torso), C.Surface(collar)])
    C.make_object('strings', strings, mats['string'], root)
    C.make_object('hood_fuzz', C.Part.join([C.wool_fuzz(collar, S['fuzz'] // 2, frng, axis_center()),
                                            C.wool_fuzz(hood, S['fuzz'] * 2, frng, axis_center())]),
                  mats['hoodie_fuzz'], root)

    # pelo: sistema Hair Curves de Blender (guias + hijos por nodos) con Principled Hair BSDF
    scalp = build_scalp(S, head, hh)
    scalp_ob = C.make_object('hair_scalp', scalp, mats['scalp'], root, colors=True, colname='scalpfade')
    G, up = build_guides(S, head_surf, hh, np.random.default_rng(11))
    hair_ob = hair_object(S, G, up, scalp_ob, head_ob, mats['hair'], root)
    bpy.context.view_layer.update()
    ev = hair_ob.evaluated_get(bpy.context.evaluated_depsgraph_get()).data
    print(f'[bob] pelo: {len(G)} guias, {len(ev.curves)} curvas tras los nodos', flush=True)

    hand_parts = []
    hands = build_hands(S, mats, root, hand_parts)
    for k, objs in bodies.items():
        hands.setdefault(k, []).extend(objs)

    # chequeo automatico de interpenetracion entre piezas de tela (y pelo/manos/casco contra la tela)
    cloth = dict(hoodie=torso, collar=collar, hood=hood, strings=strings, hardhat=hat)
    names = list(cloth)
    # el cuello del jersey entra a proposito en el torso y recibe los remates de la capucha: no se comprueba ahi
    sewn = {('hoodie', 'collar'), ('collar', 'hood')}
    pairs = [(a, cloth[a], b, cloth[b]) for i, a in enumerate(names) for b in names[i + 1:] if (a, b) not in sewn]
    pairs.append(('hardhat', hat, 'head', head))
    pairs.append(('collar', collar, 'head', head))
    for pname, part in body_parts.items():
        pairs += [(f'hoodie_{pname}', part, b, cloth[b]) for b in names if b not in ('hoodie', 'collar')]
    for hname, part in hand_parts:
        pairs += [(hname, part, b, cloth[b]) for b in names if b != 'hoodie']
        pairs += [(hname, part, f'hoodie_{k}', bp) for k, bp in body_parts.items()]
    C.check_overlaps(pairs)

    ind_root = C.empty('indicators', None, S['indicator_root'])
    ind_root.scale = (S['indicator_scale'],) * 3
    sw = np.array(S['sweat_at'])
    S2 = dict(S, sweat_at=tuple((sw - np.array(S['indicator_root'])) / S['indicator_scale']))
    ind = C.build_indicators(S2, mats, ind_root)
    arm = build_rig(root, eyes)
    organize()
    print(f'[bob] escena construida en {time.time() - t0:.1f}s', flush=True)
    return dict(root=root, head_surf=head_surf, eyes=eyes, mats=mats, pupil=pupil, iris=iris, ind=ind,
                ind_root=ind_root, brows=brows, mouth=mouth, arm=arm, hands=hands)


def build_hands(S, mats, root, check=None):
    """hand{tag}.R/L (piel, origen en la muneca) con sus unas (nails.*) como hijas, solo para los lados con brazo
    levantado; la manga es parte de la sudadera de esa pose (build_body). La pose S['done_pose'] se llama hand.*
    -> {pose: [objetos]}."""
    out = {}
    for pname, pose in HAND_POSES.items():
        tag = '' if pname == S['done_pose'] else f'_{pname}'
        objs = []
        for side in ('R', 'L'):
            spec = pose.get(side)
            if not spec:
                continue
            h = H.build_hand(dict(spec, arm=[p[:3] for p in spec['arm']]), S['hand_scale'])
            w = h['wrist']
            if check is not None:
                check.append((f'hand{tag}.{side}', C.Part(h['skin'].v.copy(), h['skin'].f)))
            for part in (h['skin'], h['nails']):
                part.v = part.v - w
            hand = C.make_object(f'hand{tag}.{side}', h['skin'], mats['skin'], root)
            nails = C.make_object(f'nails{tag}.{side}', h['nails'], mats['nail'], hand)
            hand.location = w
            objs += [hand, nails]
        out[pname] = objs
    return out


HEAD_PARTS = ('head', 'eye', 'brow', 'mouth', 'hair', 'hardhat')
GROUPS = [('rig', ('bob', 'bob_rig')), ('eyes', ('eye',)), ('brows', ('brow',)), ('mouth', ('mouth_',)),
          ('hair', ('hair_',)), ('head', ('head', 'hardhat')), ('hands', ('hand', 'nails', 'sleeve')),
          ('body', ('hoodie', 'collar', 'neck', 'hood', 'strings')),
          ('indicators', ('ind',))]


def build_rig(root, eyes):
    """Armature 'bob_rig': hueso head (cabeza, cara, pelo, casco) y, colgando de el, eye.L/R y
    lid_up/lid_lo.L/R. .L = izquierda del personaje (+X)."""
    vl = bpy.context.view_layer
    vl.update()
    data = bpy.data.armatures.new('bob_rig')
    arm = bpy.data.objects.new('bob_rig', data)
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
        for cl in eye['catches']:                # los reflejos siguen a la cabeza, no a la mirada
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
    """Una coleccion por grupo para encontrar las piezas rapido al rigear o animar."""
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
    e = EXPR[name]
    rig['pupil'].outputs[0].default_value = e['pupil']
    rig['iris'].outputs[0].default_value = S['iris_ang'] * e.get('iris', 1.0)
    pose = rig['arm'].pose.bones
    for eye in rig['eyes']:
        C.pose_eye_bones(pose, eye, e['lid_up'], e['lid_lo'], e['gaze'], e['tilt'])
        for cl, (dx, dz, r) in zip(eye['catches'], S['catchlights']):
            # un reflejo que queda bajo el parpado superior no debe asomar por encima de las pestanas
            el = math.degrees(math.atan2(dz, math.hypot(dx, 1.0))) - math.degrees(r / S['eye_r']) * 0.5
            cl.hide_render = e['lid_lo'] >= e['lid_up'] - 4 or el > e['lid_up'] - 2
    lids = [eye['lidmesh'][w] for eye in rig['eyes'] for w in ('up', 'lo')]
    for ob in list(rig['brows'].values()) + rig['mouth'] + lids:
        C.set_shape(ob, name)
    for k, objs in rig['ind'].items():
        for ob in objs:
            ob.hide_render = k != e.get('indicator')
    for k, objs in rig['hands'].items():
        for ob in objs:
            ob.hide_render = k != e.get('hands')
    bpy.context.view_layer.update()


def save_png(arr, path):
    """arr: (h, w, 4) float 0..1, fila 0 = abajo (convencion de Blender)."""
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
    """Caja con alfa premultiplicado (factor entero) para que los bordes no se ensucien."""
    f = a.shape[0] // size
    assert f * size == a.shape[0], (a.shape, size)
    pm = a.copy()
    pm[..., :3] *= pm[..., 3:4]
    pm = pm[:size * f, :size * f].reshape(size, f, size, f, 4).mean((1, 3))
    al = pm[..., 3:4]
    pm[..., :3] = np.where(al > 1e-5, pm[..., :3] / np.maximum(al, 1e-5), 0)
    return pm


def strip(icons, names, sizes, gap=8):
    """Tira transparente: una fila por tamano (64, 48, 32) con las expresiones en orden."""
    w = len(names) * (max(sizes) + gap) - gap
    h = sum(sizes) + gap * (len(sizes) - 1)
    canvas = np.zeros((h, w, 4), np.float32)
    top = 0
    for size in sizes:
        for i, name in enumerate(names):
            x = i * (max(sizes) + gap) + (max(sizes) - size) // 2
            y = h - top - size  # las filas de Blender van de abajo arriba
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
        # BOB_HIDE=prefijo,prefijo: oculta piezas en las vistas de depuracion
        for ob in bpy.data.objects:
            if any(ob.name.startswith(h) for h in os.environ.get('BOB_HIDE', '').split(',') if h):
                ob.hide_render = True
        for name in a['expr']:
            set_expression(rig, name)
            for k, (yaw, cx, cz, h) in enumerate(a['view']):
                aim_camera(cam, yaw_deg=yaw, height=h, center=(cx, cz))
                sc.render.filepath = os.path.join(out, f'view-{name}-{k}.png')
                bpy.ops.render.render(write_still=True)
        return

    def shoot(name, dest, big_sizes, icon_sizes):
        """Encuadre de busto (512/128) y pasada de icono de cabeza (64/48/32) de una expresion."""
        e = EXPR[name]
        set_expression(rig, name)
        aim_camera(cam, yaw_deg=-8.0)
        raw = os.path.join(dest, f'_raw-{name}.png')
        sc.render.filepath = raw
        t = time.time()
        bpy.ops.render.render(write_still=True)
        print(f'[bob] {name}: render {time.time() - t:.1f}s', flush=True)
        big = load_png(raw)
        for size in big_sizes:
            suffix = '' if size in (512, 768) else f'-{size}'
            save_png(downscale(big, size), os.path.join(dest, f'bob-{name}{suffix}.png'))
        # iconos 64/48/32: encuadre cerrado de cabeza con el indicador como insignia en la esquina
        loc, scale = rig['ind_root'].location.copy(), rig['ind_root'].scale.copy()
        rig['ind_root'].location, rig['ind_root'].scale = S['icon_indicator'][0], (S['icon_indicator'][1],) * 3
        trail = bpy.data.objects['ind_thinking_trail']
        trail_hidden = trail.hide_render
        trail.hide_render = True
        aim_camera(cam, yaw_deg=-8.0, **ICON_CAM.get(e.get('hands'), dict(height=2.75, center=(0.0, 0.08))))
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
            save_png(icons[(name, size)], os.path.join(dest, f'bob-{name}-{size}.png'))
        rig['ind_root'].location, rig['ind_root'].scale = loc, scale
        os.remove(raw)

    for name in a['expr']:
        shoot(name, out, sizes[:2], sizes[2:])
    if not a['quick'] and len(a['expr']) == len(EXPR):
        save_png(strip(icons, a['expr'], sizes[2:]), os.path.join(out, 'bob-strip.png'))
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
                     os.path.join(rev, f'bob-angle-{yaw}.png'))
            os.remove(raw)


main()
