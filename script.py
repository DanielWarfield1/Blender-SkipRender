import os
import shutil
import subprocess
import sys
from argparse import ArgumentParser

import bpy


def parse_args():
    try:
        separator_index = sys.argv.index("--")
    except ValueError:
        raise Exception("no arguments supplied")

    parser = ArgumentParser(prog="Blender-SkipRender")
    parser.add_argument("-o", "--output")
    parser.add_argument("-t", "--temp")

    args = parser.parse_args(sys.argv[separator_index + 1 :])
    os.makedirs(os.path.dirname(os.path.realpath(args.output)), exist_ok=True)
    os.makedirs(args.temp, exist_ok=True)

    return args


scene = bpy.context.scene
args = parse_args()


def hash_frame():
    global scene
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


def render():
    global scene, args

    prev = (None, None)
    for i in range(scene.frame_start, scene.frame_end):
        scene.frame_set(i)
        current_path = os.path.join(args.temp, f"images/{i}.png")
        current_hash = hash_frame()

        if prev[0] != current_hash:
            prev = (current_hash, i)
            scene.render.filepath = current_path
            bpy.ops.render.render(write_still=True, scene=scene.name)
        else:
            shutil.copyfile(
                os.path.join(args.temp, f"images/{prev[1]}.png"),
                current_path,
            )


def stitch():
    global scene, args

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            os.path.join(args.temp, "audio.flac"),
            "-framerate",
            str(scene.render.fps),
            "-start_number",
            str(scene.frame_start),
            "-i",
            os.path.join(args.temp, "images/%d.png"),
            "-frames:v",
            str(scene.frame_end - scene.frame_start),
            args.output,
        ]
    )


bpy.ops.sound.mixdown(filepath=os.path.join(args.temp, "audio.flac"))
render()
stitch()
