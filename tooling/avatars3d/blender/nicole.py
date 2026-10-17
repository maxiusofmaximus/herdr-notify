"""Nicole (disenadora) en Blender/Cycles: gorro violeta, bufanda de cuadros, jersey crema con trenza.

Uso (desde la raiz del repo):
  blender -b --factory-startup -P tooling/avatars3d/blender/nicole.py -- [--out DIR] [--expr a,b] [--quick]
       [--review] [--samples N] [--closeup] [--view yaw:cx:cz:alto[;...]]
Escribe <out>/nicole-<expr>.png (512), -128, -64, -48, -32 y, con --review, vistas giradas en review/ y la pose
de manos descartada para `done` (review/nicole-done_alt*.png).
--closeup (desarrollo) solo renderiza primeros planos de la cara: <out>/face-<expr>.png.
--view (desarrollo) solo renderiza encuadres libres (giro, centro x/z y alto en unidades): <out>/view-<expr>-<i>.png.
Render, luz, camara, cara, manos, rig y salida son comunes (studio.py); aqui van la spec, el pelo y la ropa.
"""
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import character as C  # noqa: E402
import studio  # noqa: E402

L = C.lin
S = dict(
    # cabeza
    head_w=0.97, head_front=0.9, head_back=0.98, head_top=1.0, head_bot=0.92, jaw_taper=0.38,
    head_bumps=[
        ((0.55, -0.75, -0.22), 0.06, 0.3, True),    # mejillas
        ((0.36, -0.92, -0.08), -0.055, 0.2, True),   # cuencas
        ((0.0, -1.0, -0.33), 0.075, 0.085, False),   # nariz
        ((0.0, -1.0, -0.42), 0.02, 0.06, False),     # punta de la nariz
        ((0.0, -1.0, -0.22), 0.012, 0.05, False),    # dorso
        ((0.08, -1.0, -0.44), 0.018, 0.045, True),   # aletas
        ((0.045, -1.0, -0.475), -0.014, 0.022, True),  # orificios (sombra bajo la punta)
        ((0.0, -1.0, -0.5), -0.008, 0.04, False),    # surco bajo la nariz
        ((0.0, -0.85, -0.85), 0.03, 0.22, False),    # barbilla
        ((0.3, -0.9, 0.2), 0.02, 0.2, True),         # arco de la ceja
    ],
    skin=L('#f6c8ae'), blush=L('#ee8f86'), nose_tip=L('#f0857c'),
    # ojos
    eye_x=0.37, eye_z=-0.1, eye_r=0.25, eye_depth=0.75, eye_yaw=9.0, eye_tilt=0.0,
    iris_ang=0.7, pupil=0.4,
    sclera=L('#fbf6f1'), sclera_edge=L('#e3cfca'), iris_in=L('#a8693a'), iris_mid=L('#6a381b'),
    iris_out=L('#3e1d0c'), iris_ring=L('#1a0a05'), iris_glow=L('#e7a35a'),
    catchlights=[(-0.36, 0.42, 0.05), (0.3, -0.22, 0.024)],
    lash_w=0.034, lash_flicks=[(48, 0.07, 0.25), (60, 0.085, 0.35), (71, 0.08, 0.5)],
    lash=L('#24120c'), lid_thick=0.016, crease_gap=14, crease_w=0.012, lid_fillet=0.09,
    # cejas y boca
    brow_pts=[(0.1, 0.185), (0.35, 0.285), (0.62, 0.22)], brow_w=0.05, brow=L('#4e2a1a'),
    brow_light=L('#7a4a30'), brow_dark=L('#2e170d'), brow_hair=0.0032, brow_hair_len=0.015,
    lip_up_h=0.03, lip_lo_h=0.045, lip_up_lift=0.02, lip_lo_lift=0.028,
    mouth_center=(0.0, -0.52), lip=L('#d47c78'), lipline=L('#6e2f2c'), cavity=L('#4a1418'),
    teeth=L('#fbf6ef'), tongue=L('#d9646e'),
    # pelo
    hair_axis_y=0.12, hair_base=L('#5c3824'), hair_dark=L('#2e160c'), hair_spec=L('#ffd9b0'),
    shell_bottom=-1.3, hair_strands=0,
    # gorro
    cut_z0=0.33, cut_k=-0.32, beanie_off=0.07, slouch=0.22, slouch_dir=(0.25, 0.55, 0.8),
    beanie_ribs=60, beanie_rib_depth=0.026, cuff_out=0.04, cuff_h=0.12, cuff_t=0.065, cuff_ribs=96,
    cuff_rib_depth=0.022, beanie=L('#6f4bb3'), fuzz=4000,
    # cuerpo
    neck_y=0.12, neck_r=0.36, neck_z=(-1.6, -0.55), collar_r=0.44, collar_z=(-1.55, -1.08), collar_rib=0.022,
    collar_ribs=60, torso_y=0.2, torso_zb=-3.6, bust=0.1,
    torso_a=1.62, torso_b=0.8, neck_ring_r=0.44, torso_zn=-1.22, torso_zs=-1.95,
    # cuerpo estilizado: seccion (z, a, b, dy) de arriba abajo -> trapecio bajo el cuello, pecho mas ancho que la
    # cintura (V suave); el jersey cuelga con pliegues suaves (torso_folds). Los brazos son tubos aparte (ARM_KNOTS)
    # que nacen bajo el cuello alto, cubren el hombro inclinado y redondean el deltoides.
    torso_taper=((-1.2, 1.05, 0.62, 0.0), (-1.95, 1.08, 0.7, -0.02), (-2.4, 1.02, 0.74, -0.05), (-3.0, 0.9, 0.7, -0.02),
                 (-3.6, 0.85, 0.66, 0.0)),
    torso_folds=0.02,
    arm_sleeve=dict(up=(0.0, 0.0, 1.0), folds=0.012, fold_len=0.22, fold_el=0.3,
                    knit=dict(cable_half=0.19, cable_rope=0.08, cable_amp=0.062, cable_depth=0.07)),
    knit_col=0.105, knit_row=0.066, knit_depth=0.04, cable_u=(0.0, -0.78, 0.78), cable_half=0.27, cable_amp=0.09, cable_rope=0.115,
    cable_period=0.5, cable_depth=0.095, sweater=L('#efe2c8'),
    # bufanda: banda de tela simulada (Cloth de Blender, ver C.build_scarf_cloth). Pose inicial: espiral de dos
    # vueltas en cono alrededor del cuello (r0 -> r1, z0 -> z1, mas bajas por delante: front_drop; inclinacion
    # tilt delante / tilt_back detras), nuca anclada por el canto alto (pin) y puntas colgando en tail_x/tail_z.
    # La gravedad y la colision (cabeza, jersey, cuello) hacen los pliegues; separate aparta las capas superpuestas.
    scarf_cloth=dict(axis_y=0.1, ends_at=0.5, r0=0.65, r1=0.8, z0=-0.98, z1=-1.15, front_slack=0.12, front_drop=0.13,
                     tilt=60.0, tilt_back=30.0, pin_from=-0.3, pin_stiffness=1.0,
                     tail_x=(-0.28, 0.3), tail_z=(-2.4, -2.3), tail_off=0.25, width=0.7, cols=15, ds=0.05,
                     k_loop=1.0, k_tail=0.5, thick=0.07, frames=90, quality=8, mass=0.5, air_damping=1.5,
                     stretch=40.0, shear=10.0, bending=8.0, friction=10.0, coll_thick=0.05, coll_dist=0.015,
                     self_dist=0.012, refine=1, fringe=11, fringe_len=0.15,
                     separate=[((0.53, 1.0), (0.0, 0.52)), ((0.88, 1.0), (0.53, 0.86))],
                     check_spans=dict(tail_R=(0.0, 0.12), loop_in=(0.16, 0.5), loop_out=(0.55, 0.86),
                                      tail_L=(0.9, 1.0))),
    plaid_period=0.56, plaid_v_scale=1.0, plaid_base=L('#efe3cb'), plaid_mid=L('#7d5ac2'), plaid_dark=L('#40287a'),
    # indicadores (coordenadas locales del ancla; escala grande para que se lea a 48 px)
    accent=L('#7a52d6'),
    indicator_root=(1.1, -1.2, 0.74), indicator_scale=1.15,
    icon_indicator=((0.6, -1.05, 0.8), 0.85), indicator_at=(0.0, 0.0, 0.0),
    sparkles=[(0.0, 0.0, 0.3), (-0.36, 0.26, 0.15), (0.3, -0.36, 0.14)],
    sweat_at=(-0.86, -0.62, 0.12),
    # manos (solo en `done`): escala sobre las medidas de hands.py y pose elegida (la otra va a review/)
    hand_scale=1.4, done_pose='peace',
)

# pelo: mechones agrupados (clumps) anchos con surcos (sub) y ondas en fase con los vecinos (ph sigue a phi), en dos
# capas solapadas que se abomban igual sobre la bufanda (clear_over); luego lados que enmarcan la cara y flequillo
LOCKS = []
rng0 = np.random.default_rng(7)
rng1 = np.random.default_rng(23)  # variacion por mechon (ancho, largo, onda, surcos): que no parezca peinado a peine


def clump(deg, **kw):
    # radio, grosor y onda iguales entre vecinos (si no, se atraviesan); varian ancho, borde, punta y largo
    phi = math.radians(deg + rng1.uniform(-2, 2))
    d = dict(phi=phi, ease=1.08, wphi=0.1, k=1.2, ph=1.6 * abs(phi) + rng0.uniform(-0.3, 0.3), vol=0.1, flare=0.3,
             wr=0.09, curl=0.07, w=rng1.uniform(0.17, 0.205), h=0.068, under=-0.04, sub=int(rng1.integers(2, 4)),
             groove=rng1.uniform(0.6, 1.0), tip0=rng1.uniform(0.6, 0.76), tuck=1.0, expo=3.0, wvar=0.14,
             wk=rng1.uniform(0.8, 1.6), wph=rng1.uniform(0, 6.28), len=rng1.uniform(0.84, 1.0))
    d.update(kw)
    return d


# capa 0 y capa 1 en los huecos (con la raiz algo separada: lift); dentro de cada capa los mechones no se tocan, asi
# solo se solapan mechones de capas distintas y clear_over los separa sin cruces
for deg in np.linspace(100, 260, 7):
    LOCKS.append(clump(deg, drop=1.9 + 0.1 * rng0.random()))
for deg in np.linspace(100, 260, 7)[:-1] + 80 / 6:
    LOCKS.append(clump(deg, drop=1.95 + 0.1 * rng0.random(), under=-0.02, layer=1, lift=0.07, w=0.235 + 0.02 * rng0.random()))
for side in (-1, 1):
    for k, deg in enumerate((88, 77, 67)):
        LOCKS.append(clump(side * deg, layer=1, drop=1.95 - 0.07 * k, ease=1.15, drift=side * 0.12, wphi=side * 0.06,
                           k=1.5, vol=0.11 + 0.01 * k, flare=0.34, wr=0.08, curl=0.07, w=0.19 + rng1.uniform(-0.02, 0.02),
                           h=0.064, under=0.03, lift=0.05))
    for k, deg in enumerate((60, 51)):
        LOCKS.append(clump(side * deg, layer=1, drop=1.9 - 0.12 * k, ease=1.25, drift=side * 0.18, wphi=side * 0.07, k=1.6,
                           vol=0.08, flare=0.45, wr=0.1, curl=0.1, w=0.17 - 0.02 * k, h=0.058, under=0.08, sub=2,
                           lift=0.03))
# flequillo (los ultimos N_BANGS mechones, objeto hair_bangs): mechoncitos sueltos con volumen y punta que salen de
# debajo del dobladillo, bajan en diagonal hacia la derecha de la imagen y rozan la frente sin llegar a las cejas
for k, (deg, drop, sw, w) in enumerate(((-34, 0.15, 0.2, 0.075), (-20, 0.16, 0.22, 0.09), (-6, 0.17, 0.22, 0.085),
                                        (8, 0.155, 0.21, 0.08), (21, 0.13, 0.18, 0.07))):
    LOCKS.append(dict(phi=math.radians(deg), drop=drop, ease=1.15, sweep=sw, sweep_end=1.0, wphi=0.015, k=0.7,
                      ph=1.0 + k, vol=0.07, flare=0.03, wr=0.012, curl=0.03, w=w, h=0.042, under=0.08, sub=1,
                      groove=0.8, tip0=0.38, expo=2.6, tuck=0.6))
N_BANGS = 5
# pelos sueltos: hebras finas que se escapan de la melena (dan silueta menos de plastico)
FLYAWAYS = []
for k in range(5):
    side = 1 if k % 2 else -1
    deg = side * rng0.uniform(75, 140)
    FLYAWAYS.append(dict(phi=math.radians(deg), drop=rng0.uniform(0.6, 1.3), ease=1.1, wphi=side * 0.04,
                         k=rng0.uniform(1.0, 2.0), ph=rng0.uniform(0, 6.28), vol=0.13, flare=rng0.uniform(0.2, 0.42),
                         wr=0.07, curl=0.06, w=0.01, h=0.007, under=rng0.uniform(0.0, 0.06), lift=0.09))


EXPR = {
    'neutral': dict(lid_up=42, lid_lo=-46, gaze=(0, -2), tilt=0, pupil=0.4,
                    brow={1: (0, 0, 0), -1: (0, 0, 0)},
                    mouth=dict(w=0.17, cl=0.024, cr=0.024, up=0.0, open=0.0)),
    'thinking': dict(lid_up=34, lid_lo=-34, gaze=(16, -18), tilt=0, pupil=0.38,
                     brow={1: (0.06, 0.11, 0.07), -1: (-0.035, -0.03, 0.0)},
                     mouth=dict(w=0.12, cl=-0.006, cr=0.014, up=0.0, open=0.0, shift=0.06, lips=0.3),
                     indicator='thinking'),
    'working': dict(lid_up=12, lid_lo=-26, gaze=(-20, 4), tilt=12, pupil=0.4,
                    brow={1: (-0.11, -0.03, 0.04), -1: (-0.11, -0.03, 0.04)},
                    mouth=dict(w=0.12, cl=-0.004, cr=-0.004, up=0.0, open=0.0, shift=-0.02, lips=0.3),
                    indicator='working'),
    'happy': dict(lid_up=16, lid_lo=16, gaze=(0, 0), tilt=0, pupil=0.4,
                  brow={1: (0.05, 0.07, 0.03), -1: (0.05, 0.07, 0.03)},
                  mouth=dict(w=0.22, cl=0.075, cr=0.075, up=-0.01, open=0.19, teeth=True, teeth_h=0.05,
                             tongue=True),
                  indicator='happy'),
    'error': dict(lid_up=47, lid_lo=-52, gaze=(0, 0), tilt=-6, pupil=0.26, iris=0.78,
                  brow={1: (0.1, 0.03, -0.03), -1: (0.1, 0.03, -0.03)},
                  mouth=dict(w=0.15, cl=-0.03, cr=-0.03, up=0.006, open=0.0, lips=0.3),
                  indicator='error'),
    'done': dict(lid_up=30, lid_lo=-30, gaze=(0, 0), tilt=0, pupil=0.42,
                 brow={1: (0.04, 0.05, 0.02), -1: (0.04, 0.05, 0.02)},
                 mouth=dict(w=0.21, cl=0.07, cr=0.07, up=-0.01, open=0.12, teeth=True, teeth_h=0.045),
                 indicator='done', hands=S['done_pose']),
}


# poses de mano para `done` (ver hands.py). .R = mano derecha del personaje (izquierda de la imagen).
# 'mirror' = la misma pose reflejada en X; None = mano en reposo fuera de cuadro.
REST = studio.REST
# brazo izquierdo (+x) como UN tubo: raiz bajo el cuello alto -> trapecio -> deltoides -> brazo -> codo -> muneca
# (fuera de cuadro). El derecho es su reflejo. Las poses de `done` reutilizan los tres primeros nudos (mismo hombro).
SHOULDER = [(0.28, 0.2, -1.42), (0.74, 0.2, -1.62), (1.12, 0.2, -1.88)]
SHOULDER_R, SHOULDER_F = [0.15, 0.2, 0.27], [0.5, 0.52, 0.9]
ARM = dict(knots=SHOULDER + [(1.24, 0.22, -2.25), (1.28, 0.26, -3.05), (1.25, 0.15, -3.85)],
           radii=SHOULDER_R + [0.27, 0.22, 0.19], flat=SHOULDER_F + [1.0, 1.0, 1.0], elbow=4)


# la bufanda se simula sobre el torso de hombro conico anterior (lecho liso, sin el relieve de los brazos); el
# chequeo de interpenetracion la compara despues con el jersey y los brazos reales
SCARF_BED = {k: v for k, v in S.items() if k != 'torso_taper' and k != 'torso_folds'}
SCARF_BED.update(torso_a=1.72, torso_b=0.82, torso_zs=-1.95, arm_x=1.25)


def mx(K):
    return [(-x, y, z) for x, y, z in K]


HAND_POSES = {
    # V de paz junto a la mejilla, palma a camara; anular y menique recogidos bajo el pulgar
    'peace': dict(R=dict(wrist=(-1.05, -1.25, -0.35), F=(-0.2, -0.1, 1.0), N=(0.0, 1.0, 0.0), side=-1,
                         curl=dict(index=(0, 4, 4), middle=(0, 4, 4), ring=(80, 95, 60), pinky=(85, 95, 60)),
                         splay=dict(index=15, middle=-11, ring=-4, pinky=-10),
                         thumb=dict(dir=(-0.75, -0.65, 0.3), up=(0.3, -1, 0.3), curl=(15, 20)),
                         arm=[(-1.65, -0.95, -2.5), (-1.4, -1.22, -1.35)],
                         knots=mx(SHOULDER) + [(-1.45, -0.2, -2.3), (-1.65, -0.95, -2.5), (-1.4, -1.22, -1.35)],
                         radii=SHOULDER_R + [0.27, 0.23, 0.21, 0.19], flat=SHOULDER_F + [1, 1, 1, 1], elbow=4),
                  L=REST),
    # corazon delante del pecho: dedos curvados forman los lobulos y los pulgares la punta
    'heart': dict(R=dict(wrist=(-0.5, -1.5, -1.7), F=(0.5, 0.0, 1.0), N=(-1.0, -0.5, 0.0), side=1,
                         curl=dict(index=(45, 50, 35), middle=(45, 50, 35), ring=(45, 50, 35), pinky=(45, 50, 35)),
                         thumb=dict(dir=(0.9, -0.25, -0.65), up=(-0.4, -1.0, 0.2), curl=(5, 10)),
                         arm=[(-1.15, -1.2, -3.0), (-0.85, -1.62, -2.35)],
                         knots=mx(SHOULDER) + [(-1.4, -0.15, -2.3), (-1.32, -0.95, -2.95), (-0.85, -1.62, -2.35)],
                         radii=SHOULDER_R + [0.27, 0.23, 0.21, 0.19], flat=SHOULDER_F + [1, 1, 1, 1], elbow=4),
                  L='mirror'),
}
# expresiones que solo se renderizan para revisar (no entran en la tira): misma cara, la otra pose de manos
REVIEW_EXPR = {'done_alt': dict(EXPR['done'], shape='done', hands=next(k for k in HAND_POSES if k != S['done_pose']),
)}
# encuadre de icono por pose de manos: un poco mas abierto para que la mano entre en 48 px
ICON_CAM = {'peace': dict(height=3.0, center=(-0.28, 0.0)), 'heart': dict(height=3.6, center=(0.0, -0.4))}



def nicole_mats(S):
    return dict(
        beanie=C.mat_wool('beanie', S['beanie'], 110.0),
        sweater=C.mat_wool('sweater', S['sweater'], 120.0),
        sweater_knit=C.mat_wool('sweater_knit', S['sweater'], 120.0, cavity='knitcav'),
        plaid=C.mat_plaid(S),
        fringe_a=C.mat_wool('fringe_a', S['plaid_base'], 140.0),
        fringe_b=C.mat_wool('fringe_b', S['plaid_mid'], 140.0),
        beanie_fuzz=C.mat_wool('beanie_fuzz', tuple(c * 1.15 for c in S['beanie'][:3]) + (1,), 140.0),
        sweater_fuzz=C.mat_wool('sweater_fuzz', S['sweater'], 140.0),
        scarf_fuzz=C.mat_wool('scarf_fuzz', tuple(0.5 * a + 0.5 * b for a, b in zip(S['plaid_base'][:3],
                                                                                     S['plaid_mid'][:3])) + (1,), 140.0),
    )


def build(S):
    root = C.empty('nicole')
    F = studio.build_face(S, EXPR, root, nicole_mats)
    head, head_surf, skin, mats = F['head'], F['head_surf'], F['skin'], F['mats']

    body, cuff, cut_line = C.build_beanie(S)
    C.make_object('beanie', C.Part.join([body]), mats['beanie'], root)
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

    torso = C.build_torso(S)
    C.make_object('sweater', torso, mats['sweater_knit'], root, colors=True, colname='knitcav')
    collar = C.orient_out(C.build_collar(S), (0.0, S['neck_y'], sum(S['collar_z']) / 2))
    collar_rim = C.build_collar_rim(S)   # borde vuelto: sin hueco entre el cuello alto y el cuello
    C.make_object('collar', C.Part.join([collar, collar_rim]), mats['sweater'], root)
    C.make_object('sweater_fuzz', C.Part.join([C.wool_fuzz(torso, S['fuzz'] * 3, frng, axis_center()),
                                               C.wool_fuzz(collar, S['fuzz'] // 2, frng, axis_center())]),
                  mats['sweater_fuzz'], root)
    C.make_object('neck', C.build_neck(S), skin, root)

    def sleeve_fn(K, pose):
        return C.arm_sleeve(S, K, pose['radii'], pose['flat'], pose['elbow'], cuff=(0.22, 0.19))
    arm_L, arm_P = sleeve_fn(ARM['knots'], ARM)
    arm_R = arm_L.mirrored_x()
    arm_objs = []
    for k, a, path in (('L', arm_L, arm_P), ('R', arm_R, arm_P * np.array([-1, 1, 1]))):
        ob = C.make_object(f'arm.{k}', a, mats['sweater_knit'], root, colors=True, colname='knitcav')
        # pelusa hacia fuera del eje del brazo
        C.make_object(f'arm_fuzz.{k}', C.wool_fuzz(a, S['fuzz'], frng, lambda P, A=path[::3]: A[
            np.linalg.norm(P[:, None] - A[None], axis=-1).argmin(1)]), mats['sweater_fuzz'], ob)
        arm_objs.append(ob)
    torso_arms = C.Part.join([torso, arm_L, arm_R])
    # el pelo cae sobre el hombro de todos los brazos (reposo y posados): mismos nudos hasta el brazo, sin antebrazo
    shoulders = [C.arm_sleeve(S, p['knots'][:4], p['radii'][:4], p['flat'][:4], 3)[0].tube for p in
                 (pose['R'] for pose in HAND_POSES.values())]
    shoulders += [sh.mirrored_x() for sh, pose in zip(shoulders, HAND_POSES.values()) if pose['L'] == 'mirror']
    body_coll = [C.Surface(C.Part.join([head, torso_arms])), C.Surface(collar)]
    # colisionadores ligeros para la simulacion (la tela queda por fuera del relieve del punto con coll_thick)
    colliders = [C.coarse_grid(head, (256, 180), (4, 3)), C.coarse_grid(C.build_torso(SCARF_BED), (480, 280), (6, 4)), collar,
                 C.build_neck(S)]
    scarf, fringe = C.build_scarf_cloth(S, colliders, body_coll[0])
    C.make_object('scarf', scarf, mats['plaid'], root)
    C.make_object('scarf_fringe_a', C.Part.join(fringe[0::2]), mats['fringe_a'], root)
    C.make_object('scarf_fringe_b', C.Part.join(fringe[1::2]), mats['fringe_b'], root)
    # pelusa de la bufanda: corta y de un tono intermedio entre los hilos para que no raye los cuadros
    C.make_object('scarf_fuzz', C.wool_fuzz(scarf, S['fuzz'] * 2, frng, axis_center(), length=(0.008, 0.022)),
                  mats['scarf_fuzz'], root)
    hair_coll = C.Surfaces([C.Part.join([head, torso, scarf]), arm_L.tube, arm_L.tube.mirrored_x()] + shoulders)
    scarf_surfs = [C.Surface(scarf)]
    rng = np.random.default_rng(11)
    # volumen y mechones solo esquivan cabeza y jersey; sobre la bufanda los aparta clear_over (envolvente comun)
    lock_coll = C.Surfaces([C.Part.join([head, torso]), arm_L.tube, arm_L.tube.mirrored_x()] + shoulders)
    caps = (C.Surface(body), C.Surface(cuff))  # el pelo nace por dentro del gorro
    shell = C.build_hair_shell(S, head_surf, cut_z, lock_coll, scarf_surfs)
    C.make_object('hair_shell', shell, mats['hair'], root, colors=True)
    locks = C.build_hair(S, LOCKS[:-N_BANGS], head_surf, lock_coll, rng, cut_z, S['hair_strands'], scarf_surfs,
                          caps=caps)
    C.make_object('hair_locks', locks, mats['hair'], root, colors=True)
    C.make_object('hair_flyaways', C.build_hair(S, FLYAWAYS, head_surf, hair_coll, rng, cut_z, caps=caps), mats['hair'],
                  root, colors=True)
    C.make_object('hair_bangs', C.build_hair(S, LOCKS[-N_BANGS:], head_surf, hair_coll, rng, cut_z,
                                             S['hair_strands'] // 2), mats['hair'], root, colors=True)

    hand_parts = []
    hands = studio.build_hands(S, HAND_POSES, mats, root, frng, mats['sweater_knit'], mats['sweater_fuzz'], hand_parts,
                               sleeve_fn)

    # chequeo automatico de interpenetracion entre piezas de tela (y pelo/manos contra la tela)
    cloth = dict(scarf.checks, sweater=torso_arms, collar=C.Part.join([collar, collar_rim]), hair_shell=shell, hair_locks=locks)
    names = list(scarf.checks)
    pairs = [(a, cloth[a], b, cloth[b]) for i, a in enumerate(names) for b in names[i + 1:]]
    pairs += [(a, cloth[a], b, cloth[b]) for a in names for b in ('sweater', 'collar', 'hair_shell', 'hair_locks')]
    for hname, part in hand_parts:
        # el brazo posado nace dentro del jersey como los de reposo (costura de la sisa): solo contra bufanda y pelo
        pairs += [(hname, part, b, cloth[b]) for b in names + ['hair_shell', 'hair_locks']]
    arms = C.Part.join([arm_L, arm_R])
    pairs += [('arms', arms, b, cloth[b]) for b in ('hair_shell', 'hair_locks')]
    C.check_overlaps(pairs)

    ind_root, ind = studio.build_indicator_set(S, mats)
    arm = studio.build_rig('nicole', root, F['eyes'], HEAD_PARTS)
    studio.organize(GROUPS)
    return dict(root=root, head_surf=head_surf, eyes=F['eyes'], mats=mats, pupil=F['pupil'], iris=F['iris'], ind=ind,
                ind_root=ind_root, brows=F['brows'], mouth=F['mouth'], arm=arm, hands=hands,
                rest_arms=[(arm_objs[1], {'peace', 'heart'}), (arm_objs[0], {'heart'})])


HEAD_PARTS = ('head', 'eye', 'brow', 'mouth', 'hair', 'beanie')
GROUPS = [('rig', ('nicole', 'nicole_rig')), ('eyes', ('eye',)), ('brows', ('brow',)), ('mouth', ('mouth_',)),
          ('hair', ('hair_',)), ('head', ('head', 'beanie')), ('hands', ('hand', 'nails', 'sleeve')), ('body', ('sweater', 'collar', 'neck', 'scarf', 'arm.', 'arm_fuzz')),
          ('indicators', ('ind',))]


studio.run('nicole', S, EXPR, build, review_expr=REVIEW_EXPR, icon_cam=ICON_CAM)
