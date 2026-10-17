"""Manos procedurales (palma, dedos con tres falanges, unas, pulgar, muneca y manga de punto).

Una mano se describe con un dict de pose (ver POSES en nicole.py):
  wrist   punto de la muneca            F  direccion palma->dedos       N  normal del dorso
  side    +1/-1: lado de lat=FxN donde queda el pulgar
  curl    {dedo: (base, media, punta)} en grados, hacia la palma; splay {dedo: grados} abre los dedos
  thumb   dict(dir=direccion inicial del pulgar, up=hacia donde mira su una, curl=(base, punta))
  arm     puntos de la manga desde fuera de cuadro hasta la muneca
  rib     (opcional) relieve del punio acanalado; 0 = punio liso de camisa
Devuelve piezas en coordenadas de mundo; nicole.py las convierte en objetos hand.L/R con origen en la muneca.
"""
import math

import numpy as np

import character as C

FINGERS = ('index', 'middle', 'ring', 'pinky')
# largo total, radio y posicion del nudillo a lo ancho de la palma (1 = lado del pulgar)
FINGER = dict(index=(0.25, 0.047, 0.36), middle=(0.27, 0.049, 0.12), ring=(0.255, 0.046, -0.12),
              pinky=(0.2, 0.04, -0.35))
PHAL = (0.45, 0.3, 0.25)


def rot(v, axis, deg):
    """Rodrigues: gira v alrededor de axis (unitario) deg grados."""
    a = math.radians(deg)
    axis = C.unit(np.asarray(axis, float))
    v = np.asarray(v, float)
    return v * math.cos(a) + np.cross(axis, v) * math.sin(a) + axis * np.dot(axis, v) * (1 - math.cos(a))


def chain(base, d, u, lengths, curls, r0, r1, n=6):
    """Dedo: falanges que se doblan hacia -u (la palma). Devuelve (tubo, punta, direccion final, u final)."""
    pts, rad = [np.asarray(base, float)], [r0]
    total = sum(lengths)
    acc = 0.0
    for L, c in zip(lengths, curls):
        b = np.cross(d, u)
        d, u = rot(d, b, -c), rot(u, b, -c)
        for k in range(1, n + 1):
            pts.append(pts[-1] + d * L / n)
            acc += L / n
            knuckle = 0.05 * math.exp(-((k / n) ** 2) * 30)   # leve bulto en cada articulacion
            rad.append((r0 + (r1 - r0) * acc / total) * (1 + knuckle))
    P = C.smooth_path(np.array(pts), 2)
    # punta redondeada: casquete esferico al final
    tip = P[-1]
    s = np.linspace(0.25, 1.0, 5)
    P = np.concatenate([P, tip + d[None] * (r1 * s)[:, None]])
    rad = np.concatenate([rad, r1 * np.sqrt(np.maximum(1 - s ** 2, 0.0004))])
    tube = C.sweep(P, np.tile(u, (len(P), 1)), rad, rad * 0.86, 14)
    return tube, tip, d, u


def nail(tip, d, u, r):
    """Una suave: lamina abombada sobre el dorso de la ultima falange."""
    sp = C.sphere_part(1.0, 20, 10)
    lat = np.cross(d, u)
    v = sp.v * np.array([r * 0.72, r * 1.0, r * 0.22])
    center = tip - d * r * 0.75 + u * r * 0.72
    sp.v = center + v[:, 0:1] * lat + v[:, 1:2] * d + v[:, 2:3] * u
    return sp


def oriented_blob(center, ax, ay, az, sizes, expo=0.7, nu=40, nv=20):
    """Elipsoide con tendencia a caja redondeada (expo<1) orientado en (ax, ay, az)."""
    sp = C.sphere_part(1.0, nu, nv)
    d = np.sign(sp.v) * np.abs(sp.v) ** expo
    v = d * np.asarray(sizes)
    sp.v = np.asarray(center) + v[:, 0:1] * ax + v[:, 1:2] * ay + v[:, 2:3] * az
    return sp


def build_hand(pose, scale=1.0, sleeve_fn=None):
    """-> dict(skin=Part, nails=Part, sleeve=Part, wrist=punto, path=eje de la manga).
    Si la pose trae `knots` (hombro -> codo) y hay sleeve_fn(knots, pose) -> (Part, eje), la manga es el brazo entero
    desde el hombro (C.arm_sleeve) en vez del tubo `arm`."""
    F, N = C.unit(np.asarray(pose['F'], float)), C.unit(np.asarray(pose['N'], float))
    N = C.unit(N - F * np.dot(N, F))
    lat = np.cross(F, N)
    side = pose['side']
    wrist = np.asarray(pose['wrist'], float)
    pw, pl, pt = 0.29 * scale, 0.28 * scale, 0.1 * scale
    center = wrist + F * pl * 0.55
    skin, nails = [], []
    skin.append(oriented_blob(center, lat, F, N, (pw / 2, pl / 2, pt / 2)))
    # base del pulgar (eminencia tenar) y muneca
    skin.append(oriented_blob(wrist + F * pl * 0.3 + lat * side * pw * 0.28 - N * pt * 0.15, lat, F, N,
                              (pw * 0.24, pl * 0.32, pt * 0.5), expo=0.9))
    wp = np.array([wrist - F * 0.22 * scale, wrist + F * 0.12 * scale])
    skin.append(C.sweep(np.linspace(wp[0], wp[1], 6), np.tile(N, (6, 1)), np.full(6, 0.105 * scale),
                        np.full(6, 0.07 * scale), 16))
    for name in FINGERS:
        length, r, x = FINGER[name]
        length *= scale
        r *= scale
        base = center + F * pl * (0.42 - 0.06 * (name == 'pinky')) + lat * side * x * pw + N * pt * 0.12
        d = rot(F, N, -side * pose.get('splay', {}).get(name, 0.0))
        tube, tip, dd, uu = chain(base, d, N, [length * p for p in PHAL], pose['curl'][name], r * 1.08, r * 0.86)
        skin.append(tube)
        nails.append(nail(tip, dd, uu, r * 0.86))
    th = pose['thumb']
    td, tu = C.unit(np.asarray(th['dir'], float)), C.unit(np.asarray(th['up'], float))
    tu = C.unit(tu - td * np.dot(tu, td))
    tbase = wrist + F * pl * 0.32 + lat * side * pw * 0.36 - N * pt * 0.1
    tube, tip, dd, uu = chain(tbase, td, tu, [0.14 * scale, 0.11 * scale], th['curl'], 0.056 * scale, 0.048 * scale)
    skin.append(tube)
    nails.append(nail(tip, dd, uu, 0.048 * scale))
    if sleeve_fn is not None and 'knots' in pose:
        sleeve, P = sleeve_fn(list(pose['knots']) + [wrist - F * 0.12 * scale], pose)
        return dict(skin=C.Part.join(skin), nails=C.Part.join(nails), sleeve=sleeve, wrist=wrist, path=P)
    # manga: tubo de punto que acaba en un punio acanalado algo mas estrecho, mas un borde enrollado
    A = np.asarray(pose['arm'], float)
    A = np.concatenate([A, [wrist - F * 0.12 * scale]])
    path = []
    for i in range(len(A) - 1):
        for t in np.linspace(0, 1, 12, endpoint=False):
            path.append(A[i] * (1 - t) + A[i + 1] * t)
    path.append(A[-1])
    P = C.smooth_path(np.array(path), 4)
    seg = np.linalg.norm(np.diff(P, axis=0), axis=1)
    arc = np.concatenate([[0], np.cumsum(seg)]) / seg.sum()
    cuff = C.ss(0.8, 0.86, arc)
    rad = (0.2 * (1 - cuff) + 0.15 * cuff) * scale
    O = np.tile(N, (len(P), 1))
    sleeve = C.sweep(P, O, rad, rad * 0.92, 48,
                     mod=lambda i, t: 1 + pose.get('rib', 0.045) * cuff[i] * np.cos(28 * t) + 0.02 * np.sin(5 * t + i * 0.3))
    T = C.unit(P[-1] - P[-2])
    ring = []
    for t in np.linspace(0, C.TAU, 48, endpoint=False):
        W = C.unit(np.cross(T, N))
        H = np.cross(W, T)
        ring.append(P[-1] + (W * math.cos(t) + H * math.sin(t) * 0.92) * rad[-1] * 1.02)
    rim = C.sweep(np.array(ring), np.tile(T, (48, 1)), np.full(48, 0.03 * scale), np.full(48, 0.03 * scale), 10,
                  closed=True)
    return dict(skin=C.Part.join(skin), nails=C.Part.join(nails), sleeve=C.Part.join([sleeve, rim]), wrist=wrist,
                path=P)
