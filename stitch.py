import os
import subprocess


def stitch(scene, args):
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
