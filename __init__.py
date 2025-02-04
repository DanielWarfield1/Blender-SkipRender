import os
import shutil
import subprocess
import time
import datetime

import bpy

#############################
# Utility Functions
#############################

def detect_changing():
    """ Detect objects and materials that change between the previous and current frame. """
    scene = bpy.context.scene
    frame = scene.frame_current
    prev_frame = max(frame - 1, scene.frame_start)

    changed_objects = set()
    changed_materials = set()

    def process(value, name, kind):
        """ Checks if an f-curve exists with a non-zero slope. """
        if not (hasattr(value, "animation_data") and value.animation_data and value.animation_data.action):
            return

        for fcurve in value.animation_data.action.fcurves:
            if abs(fcurve.evaluate(frame) - fcurve.evaluate(prev_frame)) > 1e-8:
                (changed_objects if kind == "object" else changed_materials).add(name)
                break  # No need to check further curves for this entity

    for obj in scene.objects:
        process(obj, obj.name, "object")
        for modifier in obj.modifiers:
            process(modifier, obj.name, "object")
        for slot in obj.material_slots:
            if slot.material:
                process(slot.material, slot.material.name, "material")
                if slot.material.use_nodes and slot.material.node_tree:
                    process(slot.material.node_tree, slot.material.name, "material")

    return changed_objects, changed_materials


def simulate_skip_frames(scene):
    """
    Simulates the skip logic for the entire frame range using `detect_changing()`

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
    prev_changed_objects, prev_changed_materials = detect_changing()
    skip_list.append(False)

    # Process remaining frames
    for frame in range(start + 1, end + 1):
        scene.frame_set(frame)
        changed_objects, changed_materials = detect_changing()

        if changed_objects == prev_changed_objects and changed_materials == prev_changed_materials:
            skip_list.append(True)
        else:
            skip_list.append(False)

        prev_changed_objects, prev_changed_materials = changed_objects, changed_materials

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
    "author": "Daniel Warfield",
    "description": "A renderer that analyzes f-curves, approximates duplicate frames, and skips them.",
}


#############################
# Operators
#############################

# Global variables to store state
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
    "ema_render_time": 0.0,  # Initialize EMA for render times
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

        # Analyze scene to determine which frames should be skipped
        skip_list, total_skip, total_render = simulate_skip_frames(scene)
        _process_state["skip_list"] = skip_list
        _process_state["total_skip"] = total_skip
        _process_state["total_render"] = total_render

        # Initialize tracking variables
        _process_state["last_rendered_path"] = None
        _process_state["ema_render_time"] = 0.0  # Reset EMA

        # Prepare formats and extension
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

        # Start processing
        bpy.app.timers.register(process, first_interval=0.1)
        return {"FINISHED"}


def process():
    global _process_state

    scene = bpy.context.scene

    if _process_state["stop"] or scene.i > scene.frame_end:
        scene.sleek_running = False
        return None

    # Start timing the ENTIRE frame process
    frame_start_time = time.monotonic()

    # Initialize timing variables to avoid unbound errors
    render_duration = 0.0
    save_duration = 0.0

    # Set current frame and generate file path
    scene.frame_set(scene.i)
    current_filepath = os.path.join(_process_state["frame_folder"], f"{scene.i:04d}.{_process_state['extension']}")
    scene.render.filepath = current_filepath

    # Detect changes for current frame
    changed_objects, changed_materials = detect_changing()

    # Check if current frame is a duplicate
    is_duplicate_frame = (
        changed_objects == _process_state.get("prev_changed_objects", set()) and
        changed_materials == _process_state.get("prev_changed_materials", set())
    )

    if is_duplicate_frame:
        print(f"Frame {scene.i}: Skipped (duplicate).")
        if _process_state["last_rendered_path"] and os.path.exists(_process_state["last_rendered_path"]):
            if current_filepath != _process_state["last_rendered_path"]:
                try:
                    # Time file copy operation
                    copy_start = time.monotonic()
                    shutil.copyfile(_process_state["last_rendered_path"], current_filepath)
                    copy_duration = time.monotonic() - copy_start

                    # Update timing stats for skip
                    _process_state["skip_time_total"] += copy_duration
                    _process_state["skip_count_done"] += 1
                except Exception as e:
                    print(f"Error copying file: {e}, rendering instead.")
                    # Fallback to rendering if copy fails
                    render_start = time.monotonic()
                    bpy.ops.render.render(write_still=True, scene=scene.name)
                    render_duration = time.monotonic() - render_start

                    # Time file save operation
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

            # Time file save operation
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

        # Time file save operation
        save_start = time.monotonic()
        save_duration = time.monotonic() - save_start

        _process_state["render_time_total"] += render_duration + save_duration
        _process_state["render_count_done"] += 1
        _process_state["last_rendered_path"] = current_filepath

    # Calculate EMA (Exponential Moving Average) for render times
    alpha = 0.3  # Weight for recent frames (30%)
    _process_state["ema_render_time"] = (
        alpha * (render_duration + save_duration) +
        (1 - alpha) * _process_state["ema_render_time"]
    )

    # Update previous frame data for next iteration
    _process_state["prev_changed_objects"] = changed_objects
    _process_state["prev_changed_materials"] = changed_materials

    # Calculate ETA using EMA
    render_left = _process_state["total_render"] - _process_state["render_count_done"]
    skip_left = _process_state["total_skip"] - _process_state["skip_count_done"]

    avg_skip_time = (
        _process_state["skip_time_total"] / _process_state["skip_count_done"]
        if _process_state["skip_count_done"] > 0 else 0.0
    )
    avg_render_time = _process_state["ema_render_time"]

    eta_seconds = (render_left * avg_render_time) + (skip_left * avg_skip_time)
    scene.sleek_eta = str(datetime.timedelta(seconds=round(eta_seconds)))

    # Debugging output
    print(
        f"Frame {scene.i}: "
        f"Render={render_duration:.2f}s, "
        f"Save={save_duration:.2f}s, "
        f"EMA={_process_state['ema_render_time']:.2f}s, "
        f"ETA={scene.sleek_eta}"
    )

        # Redraw UI
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == "PROPERTIES":
                area.tag_redraw()

    scene.i += 1

    # Update progress
    total_frames = scene.frame_end - scene.frame_start + 1
    if total_frames > 0:
        scene.sleek_progress = (scene.i - scene.frame_start) / total_frames
    else:
        scene.sleek_progress = 0.0

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
                    os.startfile(folder_path)  # Windows
                elif "darwin" in os.uname().sysname.lower():  # macOS
                    subprocess.run(["open", folder_path])
                else:  # Linux
                    subprocess.run(["xdg-open", folder_path])
        return {"FINISHED"}


class ANALYZE_OT_Playhead(bpy.types.Operator):
    bl_idname = "sleek.analyze_playhead"
    bl_label = "Analyze Playhead"
    bl_description = "Show which objects/materials are non-static at the current frame"

    def execute(self, context):
        scene = context.scene
        changed_objects, changed_materials = detect_changing()

        lines = []
        if not changed_objects and not changed_materials:
            lines.append("No animated objects or materials at this frame.")
        else:
            lines.append(f"Frame {scene.frame_current} Analysis:")
            lines.append("")
            if changed_objects:
                lines.append("Objects with active animation:")
                for obj_name in sorted(changed_objects):
                    lines.append(f"  - {obj_name}")
                lines.append("")
            if changed_materials:
                lines.append("Materials with active animation:")
                for mat_name in sorted(changed_materials):
                    lines.append(f"  - {mat_name}")

        def draw_popup(self, _context):
            for line in lines:
                self.layout.label(text=line)

        bpy.context.window_manager.popup_menu(
            draw_func=draw_popup,
            title="Analysis Results",
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

        # First frame cannot be skipped
        scene.frame_set(start)
        prev_changed_objects, prev_changed_materials = detect_changing()

        for frame in range(start + 1, end + 1):
            scene.frame_set(frame)
            changed_objects, changed_materials = detect_changing()

            if changed_objects == prev_changed_objects and changed_materials == prev_changed_materials:
                duplicates += 1

            prev_changed_objects, prev_changed_materials = changed_objects, changed_materials

        scene.frame_set(original_frame)  # Restore original frame

        duplicates_pct = (duplicates / (total_frames - 1)) * 100.0  # First frame cannot be skipped

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
    bpy.utils.register_class(SleekAddonPreferences)
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