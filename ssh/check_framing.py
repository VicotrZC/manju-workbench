"""客观核验机位覆盖范围：每个机位实际能看到多宽的世界，以及关键布景是否在画面内。
运行： /root/blender/blender -b -P /root/check_framing.py
"""
import math
import os
import sys

sys.argv = ['blender']
_src = open('/root/previs_scene1.py').read()
exec(_src.rsplit('\nmain()', 1)[0])

clean()
build()

from bpy_extras.object_utils import world_to_camera_view  # noqa: E402

KEY = ['COOP_ROOF', 'COOP_BACK', 'CAGE_0', 'CAGE_3', 'FENCE_0', 'FENCE_RAIL', 'WALL',
       'HOUSE_A', 'BEAM_0', 'CHEN_HEAD', 'ZHAO_HEAD', 'SACK']

import bpy  # noqa: E402

print('\n===== 机位覆盖核验 =====')
for name, loc, aim, lens, end, shake, length, note in SHOTS:
    add_cam(name, loc, aim, lens, end_loc=end, shake=shake)
    cam = bpy.data.objects[name]
    bpy.context.scene.camera = cam
    bpy.context.view_layer.update()

    cd = cam.data
    if cd.sensor_fit == 'VERTICAL':
        sh = cd.sensor_height
        sw = sh * RES[0] / RES[1]
    else:
        sw = cd.sensor_width
        sh = sw * RES[1] / RES[0]
    fov_h = 2 * math.degrees(math.atan(sw / (2 * cd.lens)))
    fov_v = 2 * math.degrees(math.atan(sh / (2 * cd.lens)))
    target = bpy.data.objects[aim].location
    cam_pos = cam.matrix_world.translation
    dist = (target - cam_pos).length
    cov_h = 2 * dist * math.tan(math.radians(fov_h / 2))
    cov_v = 2 * dist * math.tan(math.radians(fov_v / 2))
    print(f'\n--- {name}  lens={cd.lens}mm  {note}')
    print(f'    到注视点 {dist:.2f}m  横向FOV {fov_h:.1f}° 纵向FOV {fov_v:.1f}°  '
          f'该处可见宽 {cov_h:.2f}m 高 {cov_v:.2f}m')

    inside = []
    outside = []
    for k in KEY:
        ob = bpy.data.objects.get(k)
        if not ob:
            continue
        co = world_to_camera_view(bpy.context.scene, cam, ob.matrix_world.translation)
        ok = 0 <= co.x <= 1 and 0 <= co.y <= 1 and co.z > 0
        (inside if ok else outside).append(f'{k}({co.x:.2f})')
    print(f'    画面内: {", ".join(inside) if inside else "无"}')
    print(f'    画面外: {", ".join(outside) if outside else "无"}')
