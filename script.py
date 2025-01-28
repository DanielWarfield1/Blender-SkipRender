import os
import shutil
import sys

import bpy


def hash_frame(objects):
    hashes = [
        "l1{:f}-l2{:f}-l3{:f}-r1{:f}-r2{:f}-r3{:f}-s1{:f}-s2{:f}-s3{:f}".format(
            *object.location, *object.rotation_euler, *object.scale
        )
        for object in objects
    ]

    return "".join(hashes)


def render(base_path, scene):
    prev = (None, None)
    for i in range(scene.frame_start, scene.frame_end):
        scene.frame_set(i)
        current_path = os.path.join(base_path, f"images/{i}.png")
        current_hash = hash_frame(scene.objects.values())

        if prev[0] != current_hash:
            prev = (current_hash, i)
            scene.render.filepath = current_path
            bpy.ops.render.render(write_still=True, scene=scene.name)
        else:
            shutil.copyfile(
                os.path.join(base_path, f"images/{prev[1]}.png"),
                current_path,
            )


def parse_args(expected):
    try:
        separator_index = sys.argv.index("--")
    except ValueError:
        raise Exception("no arguments supplied")

    args = sys.argv[separator_index + 1 :]
    assert len(args) >= expected, "expected more arguments"

    return args


args = parse_args(1)
base_path = args[0]
assert os.path.exists(base_path), "base path does not exist"

# audio
bpy.ops.sound.mixdown(filepath=os.path.join(base_path, "audio.flac"))

# rendering
scene = bpy.context.scene
render(base_path, scene)
