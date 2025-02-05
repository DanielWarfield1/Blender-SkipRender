import os
import shutil
import subprocess
import time
import datetime

import bpy

#############################
# Utility Functions
#############################

def detect_changing(epsilon=1e-8):
    """
    Detect differences in all F-Curves between the current frame and the previous frame.
    
    Returns:
      A set of tuples (data_name, data_path) for every F-Curve whose value differs 
      between the current frame and the previous frame.
    """
    scene = bpy.context.scene
    current_frame = scene.frame_current
    # When at the first frame, use it as its own "previous" frame.
    prev_frame = max(scene.frame_start, current_frame - 1)
    differences = set()
    
    # Loop over every action and its f-curves
    for action in bpy.data.actions:
        for fcurve in action.fcurves:
            val_curr = fcurve.evaluate(current_frame)
            val_prev = fcurve.evaluate(prev_frame)
            if abs(val_curr - val_prev) > epsilon:
                data_name = getattr(fcurve.id_data, "name", "(No ID)")
                data_path = fcurve.data_path
                differences.add((data_name, data_path))
    return differences


def simulate_skip_frames(scene):
    """
    Simulates the skip logic for the entire frame range using detect_changing.
    
    Returns:
      skip_list (list of bool): True if the frame is a duplicate.
      total_skip: Count of skipped frames.
      total_render: Count of unique frames.
    """
    original_frame = scene.frame_current

    skip_list = []
    start = scene.frame_start
    end = scene.frame_end

    if start > end:
        return [], 0, 0  # Invalid frame range

    # Process the first frame (cannot be skipped)
    scene.frame_set(start)
    prev_changed = detect_changing()
    skip_list.append(False)

    # Process remaining frames
    for frame in range(start + 1, end + 1):
        scene.frame_set(frame)
        changed = detect_changing()
        if changed == prev_changed:
            skip_list.append(True)
        else:
            skip_list.append(False)
        prev_changed = changed

    scene.frame_set(original_frame)
    total_skip = sum(skip_list)
    total_render = (end - start + 1) - total_skip
    return skip_list, total_skip, total_render


#############################
# Addon Info
#############################

bl_info = {
    "name": "Skip Renderer",
    "blender": (3, 0, 0),
    "category": "Render",
    "author": "Daniel Warfield (Modified by ChatGPT)",
    "description": "A renderer that analyzes F-Curves, approximates duplicate frames, and skips them.",
}


#############################
# Operators
#############################

# Global state for processing
_process_state = {
    "stop": False,
    "skip_list": [],
    "total_skip": 0,
    "total_render": 0,
    "skip_time_total": 0.0,
    "skip_count_done": 0,
    "render_time_total": 0.0,
    "render_count_done": 0,
    "last_rendered_path": None,
    "frame_folder": None,
    "extension": None,
    "ema_render_time": 0.0,  # Exponential moving average for render times
    "prev_changed": set(),
}


class PROCESS_OT_Sleek(bpy.types.Operator):
    bl_idname = "sleek.process"
    bl_label = "Process"
    bl_description = "Start processing with a progress update"

    def execute(self, context):
        global _process_state

        scene = context.scene
        _process_state["stop"] = False
        scene.sleek_progress = 0.0
        scene.sleek_running = True
        scene.sleek_eta = ""

        scene.i = scene.frame_start

        addon_name = __package__ if __package__ else __name__.split(".")[0]
        prefs = bpy.context.preferences.addons.get(addon_name)
        if not prefs:
            self.report({"ERROR"}, "Output directory not set")
            return {"CANCELLED"}
        prefs = prefs.preferences
        output_dir = os.path.join(bpy.path.abspath(prefs.output_dir), scene.name)
        os.makedirs(output_dir, exist_ok=True)

        # Optional: add audio mixdown
        try:
            bpy.ops.sound.mixdown(filepath=os.path.join(output_dir, "audio.flac"))
        except Exception as e:
            print(f"Audio mixdown error: {e}")

        # Analyze scene to determine which frames should be skipped.
        skip_list, total_skip, total_render = simulate_skip_frames(scene)
        _process_state["skip_list"] = skip_list
        _process_state["total_skip"] = total_skip
        _process_state["total_render"] = total_render

        # Initialize tracking variables
        _process_state["last_rendered_path"] = None
        _process_state["ema_render_time"] = 0.0  # Reset EMA
        _process_state["prev_changed"] = detect_changing()

        # Prepare image format and extension.
        render = scene.render
        formats = {
            "PNG": "png",
            "JPEG": "jpg",
            "BMP": "bmp",
            "TIFF": "tiff",
            "TARGA": "tga",
            "OPEN_EXR": "exr",
        }
        if render.image_settings.file_format not in formats:
            render.image_settings.file_format = "PNG"
        _process_state["extension"] = formats[render.image_settings.file_format]
        _process_state["frame_folder"] = os.path.join(output_dir, "images")
        os.makedirs(_process_state["frame_folder"], exist_ok=True)

        # Start processing via a timer.
        bpy.app.timers.register(process, first_interval=0.1)
        return {"FINISHED"}


def process():
    global _process_state

    scene = bpy.context.scene

    if _process_state["stop"] or scene.i > scene.frame_end:
        scene.sleek_running = False
        return None

    # Timing for this frame.
    frame_start_time = time.monotonic()
    render_duration = 0.0
    save_duration = 0.0

    # Set the current frame and build the output file path.
    scene.frame_set(scene.i)
    current_filepath = os.path.join(
        _process_state["frame_folder"], f"{scene.i:04d}.{_process_state['extension']}"
    )
    scene.render.filepath = current_filepath

    # Use the new logic to check for changes.
    changed = detect_changing()

    # Compare with the previous frame’s differences.
    is_duplicate_frame = changed == _process_state.get("prev_changed", set())

    if is_duplicate_frame:
        print(f"Frame {scene.i}: Skipped (duplicate).")
        if _process_state["last_rendered_path"] and os.path.exists(_process_state["last_rendered_path"]):
            if current_filepath != _process_state["last_rendered_path"]:
                try:
                    copy_start = time.monotonic()
                    shutil.copyfile(_process_state["last_rendered_path"], current_filepath)
                    copy_duration = time.monotonic() - copy_start

                    _process_state["skip_time_total"] += copy_duration
                    _process_state["skip_count_done"] += 1
                except Exception as e:
                    print(f"Error copying file: {e}, rendering instead.")
                    render_start = time.monotonic()
                    bpy.ops.render.render(write_still=True, scene=scene.name)
                    render_duration = time.monotonic() - render_start

                    save_start = time.monotonic()
                    save_duration = time.monotonic() - save_start

                    _process_state["render_time_total"] += render_duration + save_duration
                    _process_state["render_count_done"] += 1
                    _process_state["last_rendered_path"] = current_filepath
        else:
            print("No previous frame to copy, rendering.")
            render_start = time.monotonic()
            bpy.ops.render.render(write_still=True, scene=scene.name)
            render_duration = time.monotonic() - render_start

            save_start = time.monotonic()
            save_duration = time.monotonic() - save_start

            _process_state["render_time_total"] += render_duration + save_duration
            _process_state["render_count_done"] += 1
            _process_state["last_rendered_path"] = current_filepath
    else:
        print(f"Frame {scene.i}: Rendering.")
        render_start = time.monotonic()
        bpy.ops.render.render(write_still=True, scene=scene.name)
        render_duration = time.monotonic() - render_start

        save_start = time.monotonic()
        save_duration = time.monotonic() - save_start

        _process_state["render_time_total"] += render_duration + save_duration
        _process_state["render_count_done"] += 1
        _process_state["last_rendered_path"] = current_filepath

    # Update the exponential moving average for render time.
    alpha = 0.3
    _process_state["ema_render_time"] = (
        alpha * (render_duration + save_duration) +
        (1 - alpha) * _process_state["ema_render_time"]
    )

    # Save the current differences for the next iteration.
    _process_state["prev_changed"] = changed

    # Estimate the remaining time.
    render_left = _process_state["total_render"] - _process_state["render_count_done"]
    skip_left = _process_state["total_skip"] - _process_state["skip_count_done"]

    avg_skip_time = (
        _process_state["skip_time_total"] / _process_state["skip_count_done"]
        if _process_state["skip_count_done"] > 0 else 0.0
    )
    avg_render_time = _process_state["ema_render_time"]

    eta_seconds = (render_left * avg_render_time) + (skip_left * avg_skip_time)
    scene.sleek_eta = str(datetime.timedelta(seconds=round(eta_seconds)))

    print(
        f"Frame {scene.i}: Render={render_duration:.2f}s, Save={save_duration:.2f}s, "
        f"EMA={_process_state['ema_render_time']:.2f}s, ETA={scene.sleek_eta}"
    )

    # Redraw the UI.
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()

    scene.i += 1

    total_frames = scene.frame_end - scene.frame_start + 1
    scene.sleek_progress = (scene.i - scene.frame_start) / total_frames if total_frames > 0 else 0.0

    return 0.1


class STOP_OT_Sleek(bpy.types.Operator):
    bl_idname = "sleek.stop"
    bl_label = "Stop"
    bl_description = "Stop the processing"

    def execute(self, context):
        global _process_state
        _process_state["stop"] = True
        context.scene.sleek_running = False
        return {"FINISHED"}


class OPENFOLDER_OT_Sleek(bpy.types.Operator):
    bl_idname = "sleek.open_folder"
    bl_label = "Open Folder"
    bl_description = "Open the saved file path in the OS file explorer"

    def execute(self, context):
        addon_name = __package__ if __package__ else __name__.split(".")[0]
        prefs = bpy.context.preferences.addons.get(addon_name)
        if prefs:
            prefs = prefs.preferences
            folder_path = os.path.dirname(bpy.path.abspath(prefs.output_dir))
            if os.path.exists(folder_path):
                if os.name == "nt":
                    os.startfile(folder_path)
                elif "darwin" in os.uname().sysname.lower():
                    subprocess.run(["open", folder_path])
                else:
                    subprocess.run(["xdg-open", folder_path])
        return {"FINISHED"}


class ANALYZE_OT_Playhead(bpy.types.Operator):
    bl_idname = "sleek.analyze_playhead"
    bl_label = "Analyze Playhead"
    bl_description = "Show F-Curve differences for the current frame"

    def execute(self, context):
        scene = context.scene
        diffs = detect_changing()

        lines = []
        if not diffs:
            lines.append("No changed F-Curves at this frame.")
        else:
            lines.append(f"Frame {scene.frame_current} F-Curve Analysis:")
            lines.append("")
            lines.append("Changed F-Curves:")
            for data_name, data_path in sorted(diffs):
                lines.append(f" - {data_name} : {data_path}")

        def draw_popup(self, _context):
            for line in lines:
                self.layout.label(text=line)

        bpy.context.window_manager.popup_menu(
            draw_func=draw_popup,
            title="F-Curve Frame Analysis",
            icon='INFO'
        )
        return {"FINISHED"}


class ANALYZE_SCENE_OT_Sleek(bpy.types.Operator):
    bl_idname = "sleek.analyze_scene"
    bl_label = "Analyze Full Scene"
    bl_description = "Check entire scene for duplicate frames and show percentage in a popup."

    def execute(self, context):
        scene = context.scene
        start = scene.frame_start
        end = scene.frame_end
        total_frames = end - start + 1

        duplicates = 0
        original_frame = scene.frame_current

        scene.frame_set(start)
        prev_changed = detect_changing()

        for frame in range(start + 1, end + 1):
            scene.frame_set(frame)
            changed = detect_changing()
            if changed == prev_changed:
                duplicates += 1
            prev_changed = changed

        scene.frame_set(original_frame)

        duplicates_pct = (duplicates / (total_frames - 1)) * 100.0 if total_frames > 1 else 0.0

        lines = [
            f"Analyzed frames {start} to {end}",
            f"Total frames: {total_frames}",
            f"Duplicate frames: {duplicates} ({duplicates_pct:.2f}%)"
        ]

        def draw_popup(self, _context):
            for line in lines:
                self.layout.label(text=line)

        bpy.context.window_manager.popup_menu(
            draw_func=draw_popup,
            title="Scene Analysis",
            icon='INFO'
        )
        return {"FINISHED"}


#############################
# Panel
#############################

class PANEL_PT_Sleek(bpy.types.Panel):
    bl_label = "Skip Renderer"
    bl_idname = "PANEL_PT_sleek"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        layout = self.layout
        addon_name = __package__ if __package__ else __name__.split(".")[0]
        prefs = bpy.context.preferences.addons.get(addon_name)

        if prefs:
            prefs = prefs.preferences
            layout.prop(prefs, "output_dir")
        else:
            layout.label(text="(Addon Preferences Not Loaded)", icon="ERROR")

        row = layout.row(align=True)
        row.operator("sleek.analyze_playhead", icon="VIEWZOOM")
        row.operator("sleek.analyze_scene", icon="SCENE_DATA")

        if context.scene.sleek_running:
            layout.operator("sleek.stop", icon="CANCEL")
            percent = int(context.scene.sleek_progress * 100)
            layout.label(text=f"Progress: {percent}% (ETA: {context.scene.sleek_eta})")
        else:
            layout.operator("sleek.process", icon="PLAY")

        if prefs and prefs.output_dir:
            layout.operator("sleek.open_folder", icon="FILE_FOLDER")


#############################
# Registration
#############################

def register():
    bpy.utils.register_class(SleekAddonPreferences)  # Assumes you have this class defined in your preferences.
    bpy.utils.register_class(PROCESS_OT_Sleek)
    bpy.utils.register_class(STOP_OT_Sleek)
    bpy.utils.register_class(OPENFOLDER_OT_Sleek)
    bpy.utils.register_class(ANALYZE_OT_Playhead)
    bpy.utils.register_class(ANALYZE_SCENE_OT_Sleek)
    bpy.utils.register_class(PANEL_PT_Sleek)

    bpy.types.Scene.sleek_progress = bpy.props.FloatProperty(
        name="Progress", min=0.0, max=1.0, default=0.0
    )
    bpy.types.Scene.sleek_running = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.sleek_eta = bpy.props.StringProperty(default="")
    bpy.types.Scene.i = bpy.props.IntProperty(default=0)


def unregister():
    bpy.utils.unregister_class(SleekAddonPreferences)
    bpy.utils.unregister_class(PROCESS_OT_Sleek)
    bpy.utils.unregister_class(STOP_OT_Sleek)
    bpy.utils.unregister_class(OPENFOLDER_OT_Sleek)
    bpy.utils.unregister_class(ANALYZE_OT_Playhead)
    bpy.utils.unregister_class(ANALYZE_SCENE_OT_Sleek)
    bpy.utils.unregister_class(PANEL_PT_Sleek)

    del bpy.types.Scene.sleek_progress
    del bpy.types.Scene.sleek_running
    del bpy.types.Scene.sleek_eta
    del bpy.types.Scene.i


if __name__ == "__main__":
    register()
