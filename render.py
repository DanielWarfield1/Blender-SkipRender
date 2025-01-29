import os
import shutil

import bpy

from .hash import hash_frame


def render(scene, args):
    prev = (None, None)
    for i in range(scene.frame_start, scene.frame_end):
        scene.frame_set(i)
        current_path = os.path.join(args.temp, f"images/{i}.png")
        current_hash = hash_frame(scene)

        if prev[0] != current_hash:
            prev = (current_hash, i)
            scene.render.filepath = current_path
            bpy.ops.render.render(write_still=True, scene=scene.name)
        else:
            shutil.copyfile(
                os.path.join(args.temp, f"images/{prev[1]}.png"),
                current_path,
            )
