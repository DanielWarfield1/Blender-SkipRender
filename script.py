import os
import shutil
import subprocess
import sys

import bpy


def hash_frame(scene):
    slopes = []

    def process(value):
        if not (
            hasattr(value, "animation_data")
            and value.animation_data
            and value.animation_data.action
        ):
            return

        for fcurve in value.animation_data.action.fcurves:
            frame = scene.frame_current
            current = fcurve.evaluate(frame)
            next = fcurve.evaluate(frame + 1)
            slopes.append(next - current)

    for object in scene.objects:
        # object animations
        process(object)

        # modifier animations
        for modifier in object.modifiers:
            process(modifier)

        for slot in object.material_slots:
            if not slot.material:
                continue
            material = slot.material

            # material animations
            process(material)

            # node tree animations
            if material.use_nodes:
                process(material.node_tree)

    return " ".join([str(slope) for slope in slopes])


def render(base_path, scene):
    prev = (None, None)
    for i in range(scene.frame_start, scene.frame_end):
        scene.frame_set(i)
        current_path = os.path.join(base_path, f"images/{i}.png")
        current_hash = hash_frame(scene)

        if prev[0] != current_hash:
            prev = (current_hash, i)
            scene.render.filepath = current_path
            bpy.ops.render.render(write_still=True, scene=scene.name)
        else:
            shutil.copyfile(
                os.path.join(base_path, f"images/{prev[1]}.png"),
                current_path,
            )


def stitch(base_path, scene):
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            os.path.join(base_path, "audio.flac"),
            "-framerate",
            str(scene.render.fps),
            "-start_number",
            str(scene.frame_start),
            "-i",
            os.path.join(base_path, "images/%d.png"),
            "-frames:v",
            str(scene.frame_end - scene.frame_start),
            os.path.join(base_path, "output.mov"),
        ]
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

bpy.ops.sound.mixdown(filepath=os.path.join(base_path, "audio.flac"))

scene = bpy.context.scene
render(base_path, scene)

stitch(base_path, scene)
