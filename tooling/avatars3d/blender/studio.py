"""Estudio comun de los avatares 3D (Blender/Cycles): render, luces y camara, cara (piel, ojos, cejas, boca), manos,
rig, expresiones y salida (512/128/64/48/32, tira y vistas de review).

Cada personaje (nicole.py, alfred.py) define su spec S, EXPR, poses de mano y la funcion que construye pelo y ropa;
studio.run() hace el resto con la misma luz, camara y encuadre para todos, asi los avatares forman un conjunto.
Uso desde un personaje: studio.run('nombre', S, EXPR, build, review_expr=..., icon_cam=...).
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

# mano en reposo fuera de cuadro (la que no hace el gesto de `done`)
REST = dict(wrist=(1.45, -0.55, -3.5), F=(0, 0, 1), N=(1, 0, 0), side=1,
            curl=dict(index=(30, 30, 20), middle=(30, 30, 20), ring=(30, 30, 20), pinky=(30, 30, 20)),
            thumb=dict(dir=(0, -1, 0.5), up=(0, 0, 1), curl=(10, 10)), arm=[(1.45, -0.55, -4.6)])


def parse_args(expr_names):
    argv = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    a = dict(out=None, expr=list(expr_names), quick=False, review=False, samples=None, closeup=False, view=None)
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


def build_face(S, EXPR, root, extra_mats):
    """Cabeza con piel (rubor y punta de nariz), ojos con parpados por expresion, cejas y boca con una shape key por
    expresion y los materiales comunes (cara, pelo, indicadores en el color de acento S['accent'], manos).
    extra_mats: funcion S -> {nombre: material} con los materiales propios del personaje (ropa).
    -> dict(head, head_surf, skin, mats, eyes, brows, mouth, pupil, iris)."""
    head = C.build_head(S)
    head_surf = C.Surface(head)
    head_ob = C.make_object('head', head, None, root)
    spots = []
    for sx in (-1, 1):
        d = np.array([0.55 * sx, -0.78, -0.3])
        d /= np.linalg.norm(d)
        spots.append((tuple(C.head_points(d[None], S)[0]), S.get('blush_r', 0.26), S['blush'], S.get('blush_a', 0.55)))
    nd = np.array([0.0, -1.0, -0.36])
    nd /= np.linalg.norm(nd)
    spots.append((tuple(C.head_points(nd[None], S)[0] + nd * 0.07), 0.13, S['nose_tip'], S.get('nose_a', 0.85)))
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
        hair=C.mat_hair(S),
    )
    mats.update(extra_mats(S))
    mats.update(
        bubble=C.mat_flat('bubble', L('#ffffff'), rough=0.3, coat=0.6, sss=0.3),
        accent=C.mat_flat('accent', S['accent'], rough=0.3, coat=0.6),
        error=C.mat_flat('error', L('#e3383a'), rough=0.3, coat=0.6),
        white=C.mat_flat('white', L('#ffffff'), rough=0.3),
        sweat=C.mat_flat('sweat', L('#9fd4ff'), rough=0.05, coat=1.0, sss=0.4),
        spark=C.mat_flat('spark', L('#ffc93d'), rough=0.25, coat=0.6),
        done=C.mat_flat('done', L('#2fb36b'), rough=0.3, coat=0.6),
        nail=C.mat_flat('nail', S.get('nail', L('#f3c6bd')), rough=0.18, coat=0.9, sss=0.3),
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
    mouth_shapes = {n: C.mouth_parts(S, head_surf, e['mouth']) for n, e in EXPR.items()}
    mouth = []
    for key, mat in (('cavity', 'cavity'), ('teeth', 'teeth'), ('tongue', 'tongue'), ('tongue_out', 'tongue'),
                     ('line', 'lipline')):
        shapes = {n: m[key] for n, m in mouth_shapes.items()}
        mouth.append(C.add_shape_keys(C.make_object(f'mouth_{key}', shapes['neutral'], mats[mat], root), shapes))
    lips = {n: C.Part.join([m['lip_up'], m['lip_lo']]) for n, m in mouth_shapes.items()}
    mouth.append(C.add_shape_keys(C.make_object('mouth_lips', lips['neutral'], mats['lip'], root, colors=True,
                                                colname='lipfade'), lips))
    return dict(head=head, head_surf=head_surf, skin=skin, mats=mats, eyes=eyes, brows=brows, mouth=mouth,
                pupil=pupil, iris=iris)


def build_hands(S, poses, mats, root, rng, sleeve_mat, fuzz_mat=None, check=None, sleeve_fn=None):
    """hand.L/R (piel, origen en la muneca) con sus unas (nails.*) como hijas y la manga sleeve.* (con pelusa si hay
    fuzz_mat). La pose S['done_pose'] se llama hand.*; las otras hand_<pose>.* (solo para review). -> {pose: [objetos]}.
    poses: {nombre: dict(R=pose, L=pose | 'mirror' | REST)} (ver hands.py). sleeve_fn: brazo entero desde el hombro
    para las poses con `knots` (ver hands.build_hand); su manga lleva la cavidad del punto (atributo knitcav)."""
    out = {}
    for pname, pose in poses.items():
        tag = '' if pname == S['done_pose'] else f'_{pname}'
        objs = []
        for side in ('R', 'L'):
            spec, mirror = pose[side], False
            if spec == 'mirror':
                spec, mirror = pose['R'], True
            h = H.build_hand(spec, S['hand_scale'], sleeve_fn)
            if mirror:
                h = {k: (v.mirrored_x() if isinstance(v, C.Part) else v * np.array([-1, 1, 1])) for k, v in h.items()}
            path = h['path']

            def nearest(P, path=path[::max(1, len(path) // 120)]):
                d = np.linalg.norm(P[:, None] - path[None], axis=-1)
                return path[d.argmin(1)]
            fuzz = C.wool_fuzz(h['sleeve'], S['fuzz'] // 2, rng, nearest) if fuzz_mat else None
            w = h['wrist']
            if check is not None and spec is not REST:
                check += [(f'hand{tag}.{side}', C.Part(h['skin'].v.copy(), h['skin'].f)),
                          (f'sleeve{tag}.{side}', C.Part(h['sleeve'].v.copy(), h['sleeve'].f))]
            for part in (h['skin'], h['nails'], h['sleeve'], fuzz):
                if part is not None:
                    part.v = part.v - w
            hand = C.make_object(f'hand{tag}.{side}', h['skin'], mats['skin'], root)
            nails = C.make_object(f'nails{tag}.{side}', h['nails'], mats['nail'], hand)
            sleeve = C.make_object(f'sleeve{tag}.{side}', h['sleeve'], sleeve_mat, root,
                                   colors=sleeve_fn is not None and 'knots' in spec, colname='knitcav')
            objs += [hand, nails, sleeve]
            if fuzz is not None:
                objs.append(C.make_object(f'sleeve_fuzz{tag}.{side}', fuzz, fuzz_mat, sleeve))
            for ob in (hand, sleeve):
                ob.location = w
        out[pname] = objs
    return out


def build_indicator_set(S, mats):
    """Indicadores de estado (pensando, trabajando, error, feliz, hecho) bajo un ancla escalable."""
    ind_root = C.empty('indicators', None, S['indicator_root'])
    ind_root.scale = (S['indicator_scale'],) * 3
    sw = np.array(S['sweat_at'])
    S2 = dict(S, sweat_at=tuple((sw - np.array(S['indicator_root'])) / S['indicator_scale']))
    return ind_root, C.build_indicators(S2, mats, ind_root)


def build_rig(name, root, eyes, head_parts):
    """Armature '<name>_rig': hueso head (cabeza, cara, pelo y lo que lleve en la cabeza) y, colgando de el, eye.L/R
    (globo) y lid_up/lid_lo.L/R (parpados). Sustituye a los empties de construccion: la pose de cada hueso equivale a
    la rotacion local que tenia su empty. .L = izquierda del personaje (+X)."""
    vl = bpy.context.view_layer
    vl.update()
    data = bpy.data.armatures.new(f'{name}_rig')
    arm = bpy.data.objects.new(f'{name}_rig', data)
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
        if ob.type == 'MESH' and ob.name.startswith(head_parts):
            to_bone(ob, 'head')
    for ob in plan:
        bpy.data.objects.remove(ob, do_unlink=True)
    vl.update()
    return arm


def organize(groups):
    """Una coleccion por grupo para encontrar las piezas rapido al rigear o animar."""
    sc = bpy.context.scene
    for ob in list(sc.collection.objects):
        for gname, prefixes in groups:
            if ob.name in prefixes or (gname != 'rig' and ob.name.startswith(prefixes)):
                coll = bpy.data.collections.get(gname)
                if coll is None:
                    coll = bpy.data.collections.new(gname)
                    sc.collection.children.link(coll)
                coll.objects.link(ob)
                sc.collection.objects.unlink(ob)
                break


def set_expression(rig, name):
    e = rig['expr'][name]
    shape = e.get('shape', name)
    rig['pupil'].outputs[0].default_value = e['pupil']
    rig['iris'].outputs[0].default_value = rig['S']['iris_ang'] * e.get('iris', 1.0)
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
            ob.hide_render = k != e.get('hands')
    for ob, poses in rig.get('rest_arms', ()):   # brazo en reposo oculto cuando su lado esta posado
        ob.hide_render = e.get('hands') in poses
        for ch in ob.children:
            ch.hide_render = ob.hide_render
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


def run(name, S, EXPR, build, review_expr=None, icon_cam=None):
    """Construye la escena (build(S) -> rig dict) y escribe <out>/<name>-<expr>.png (512), -128, -64, -48, -32,
    <name>-strip.png y, con --review, review/<name>-<expr de review>*.png y review/<name>-angle-<grados>.png.
    --closeup: primeros planos de la cara (<out>/face-<expr>.png); --view yaw:cx:cz:alto[;...]: encuadres libres
    (<out>/view-<expr>-<i>.png); <NAME>_HIDE=prefijo,prefijo oculta piezas en --view."""
    review_expr = review_expr or {}
    icon_cam = icon_cam or {}
    a = parse_args(EXPR)
    out = a['out'] or os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'assets', 'agents3d')
    out = os.path.abspath(out)
    os.makedirs(out, exist_ok=True)
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    setup_render(a['quick'], a['samples'])
    cam = setup_lights_camera()
    t0 = time.time()
    rig = build(S)
    rig.update(S=S, expr={**EXPR, **review_expr})
    print(f'[{name}] escena construida en {time.time() - t0:.1f}s', flush=True)
    sc = bpy.context.scene
    sizes = (512, 128, 64, 48, 32) if not a['quick'] else (768, 128, 48)
    icons = {}
    if a['closeup']:
        for ex in a['expr']:
            set_expression(rig, ex)
            aim_camera(cam, yaw_deg=-8.0, height=1.7, center=(0.0, -0.15))
            sc.render.filepath = os.path.join(out, f'face-{ex}.png')
            bpy.ops.render.render(write_still=True)
        return
    if a['view']:
        hide = os.environ.get(f'{name.upper()}_HIDE', '').split(',')
        for ob in bpy.data.objects:
            if any(ob.name.startswith(h) for h in hide if h):
                ob.hide_render = True
        for ex in a['expr']:
            set_expression(rig, ex)
            for k, (yaw, cx, cz, h) in enumerate(a['view']):
                aim_camera(cam, yaw_deg=yaw, height=h, center=(cx, cz))
                sc.render.filepath = os.path.join(out, f'view-{ex}-{k}.png')
                bpy.ops.render.render(write_still=True)
        return

    def shoot(ex, dest, big_sizes, icon_sizes):
        """Encuadre de busto (512/128) y pasada de icono de cabeza (64/48/32) de una expresion."""
        e = rig['expr'][ex]
        set_expression(rig, ex)
        aim_camera(cam, yaw_deg=-8.0)
        raw = os.path.join(dest, f'_raw-{ex}.png')
        sc.render.filepath = raw
        t = time.time()
        bpy.ops.render.render(write_still=True)
        print(f'[{name}] {ex}: render {time.time() - t:.1f}s', flush=True)
        big = load_png(raw)
        for size in big_sizes:
            suffix = '' if size in (512, 768) else f'-{size}'
            save_png(downscale(big, size), os.path.join(dest, f'{name}-{ex}{suffix}.png'))
        # iconos 64/48/32: encuadre cerrado de cabeza con el indicador como insignia en la esquina
        loc, scale = rig['ind_root'].location.copy(), rig['ind_root'].scale.copy()
        rig['ind_root'].location, rig['ind_root'].scale = S['icon_indicator'][0], (S['icon_indicator'][1],) * 3
        trail = bpy.data.objects['ind_thinking_trail']
        trail_hidden = trail.hide_render
        trail.hide_render = True
        aim_camera(cam, yaw_deg=-8.0, **icon_cam.get(e.get('hands'), dict(height=2.75, center=(0.0, 0.08))))
        # para 64 px o menos basta 768 px con menos muestras (factores enteros: 12, 16, 24)
        res, spp = sc.render.resolution_x, sc.cycles.samples
        sc.render.resolution_x = sc.render.resolution_y = 768
        sc.cycles.samples = min(spp, 128)
        bpy.ops.render.render(write_still=True)
        sc.render.resolution_x = sc.render.resolution_y = res
        sc.cycles.samples = spp
        trail.hide_render = trail_hidden
        big = load_png(raw)
        for size in icon_sizes:
            icons[(ex, size)] = downscale(big, size)
            save_png(icons[(ex, size)], os.path.join(dest, f'{name}-{ex}-{size}.png'))
        rig['ind_root'].location, rig['ind_root'].scale = loc, scale
        os.remove(raw)

    for ex in a['expr']:
        shoot(ex, out, sizes[:2], sizes[2:])
    if not a['quick'] and len(a['expr']) == len(EXPR):
        save_png(strip(icons, a['expr'], sizes[2:]), os.path.join(out, f'{name}-strip.png'))
    if a['review']:
        rev = os.path.join(out, 'review')
        os.makedirs(rev, exist_ok=True)
        for ex in review_expr:
            shoot(ex, rev, sizes[:2], (48,) if a['quick'] else (64, 48))
        set_expression(rig, 'neutral')
        for yaw in (-40, 40, 90, 180):
            aim_camera(cam, yaw_deg=yaw)
            raw = os.path.join(rev, '_raw.png')
            sc.render.filepath = raw
            bpy.ops.render.render(write_still=True)
            save_png(downscale(load_png(raw), 256 if a['quick'] else 512),
                     os.path.join(rev, f'{name}-angle-{yaw}.png'))
            os.remove(raw)
