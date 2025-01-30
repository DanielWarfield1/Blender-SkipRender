import os
import shutil
import subprocess

import bpy

from .hash import hash_frame

bl_info = {
    "name": "Sleek Addon",
    "blender": (3, 0, 0),
    "category": "Render",
    "author": "Daniel Warfield",
    "description": "A sleek addon with processing, progress, stop button, and file persistence",
}


# Addon Preferences for storing persistent data
class SleekAddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    output_dir: bpy.props.StringProperty(
        name="Output Directory",
        description="Select an output directory",
        subtype="DIR_PATH",
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "output_dir")


prev = (None, None)


class PROCESS_OT_Sleek(bpy.types.Operator):
    bl_idname = "sleek.process"
    bl_label = "Process"
    bl_description = "Start processing with a progress update"

    _stop = False
    _progress = 0

    def execute(self, context):
        scene = context.scene
        PROCESS_OT_Sleek._stop = False
        PROCESS_OT_Sleek._progress = 0
        scene.sleek_progress = 0.0
        scene.sleek_running = True

        scene.i = scene.frame_start

        addon_name = __package__ if __package__ else __name__.split(".")[0]
        prefs = bpy.context.preferences.addons.get(addon_name)
        if not prefs:
            self.report({"ERROR"}, "Output directory not set")
            return {"CANCELLED"}
        prefs = prefs.preferences
        output_dir = os.path.join(bpy.path.abspath(prefs.output_dir), scene.name)
        # @WARNING
        # os.rmdir(output_dir)
        os.makedirs(output_dir, exist_ok=True)

        def process():
            global prev
            # cancel check
            if PROCESS_OT_Sleek._stop or scene.i > scene.frame_end:
                scene.sleek_running = False
                for window in bpy.context.window_manager.windows:
                    for area in window.screen.areas:
                        if area.type == "PROPERTIES":
                            area.tag_redraw()
                return None

            # options and validation
            scene.sleek_progress = 1 - ((scene.frame_end - scene.frame_start) / scene.i)
            scene.frame_set(scene.i)
            formats = {
                "PNG": "png",
                "JPEG": "jpg",
                "BMP": "bmp",
                "TIFF": "tiff",
                "TARGA": "tga",
                "OPEN_EXR": "exr",
            }

            render = scene.render
            if render.image_settings.file_format not in formats.keys():
                render.image_settings.file_format = formats.keys()[0]

            render.filepath = os.path.join(
                output_dir,
                f"images/{scene.i}.{formats[render.image_settings.file_format]}",
            )

            # actual rendering
            current_hash = hash_frame(scene)
            if prev[0] != current_hash:
                prev = (current_hash, render.filepath)
                bpy.ops.render.render(write_still=True, scene=scene.name)
            else:
                shutil.copyfile(
                    prev[1],
                    render.filepath,
                )

            # redraw
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == "PROPERTIES":
                        area.tag_redraw()

            scene.i += 1
            return 0.1

        bpy.ops.sound.mixdown(filepath=os.path.join(output_dir, "audio.flac"))
        bpy.app.timers.register(process, first_interval=0.1)
        return {"FINISHED"}


# stop processing op
class STOP_OT_Sleek(bpy.types.Operator):
    bl_idname = "sleek.stop"
    bl_label = "Stop"
    bl_description = "Stop the processing"

    def execute(self, context):
        PROCESS_OT_Sleek._stop = True
        context.scene.sleek_running = False
        return {"FINISHED"}


# open folder op(?)
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


# panel (render properties)
class PANEL_PT_Sleek(bpy.types.Panel):
    bl_label = "Sleek Addon"
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

        if context.scene.sleek_running:
            layout.operator("sleek.stop", icon="CANCEL")
            layout.label(text=f"Progress: {int(context.scene.sleek_progress * 100)}%")
        else:
            layout.operator("sleek.process", icon="PLAY")

        if prefs and prefs.output_dir:
            layout.operator("sleek.open_folder", icon="FILE_FOLDER")


# registration
def register():
    bpy.utils.register_class(SleekAddonPreferences)
    bpy.utils.register_class(PROCESS_OT_Sleek)
    bpy.utils.register_class(STOP_OT_Sleek)
    bpy.utils.register_class(OPENFOLDER_OT_Sleek)
    bpy.utils.register_class(PANEL_PT_Sleek)

    bpy.types.Scene.sleek_progress = bpy.props.FloatProperty(
        name="Progress", min=0.0, max=1.0, default=0.0
    )
    bpy.types.Scene.sleek_running = bpy.props.BoolProperty(default=False)
    bpy.types.Scene.i = bpy.props.IntProperty(default=0)


def unregister():
    bpy.utils.unregister_class(SleekAddonPreferences)
    bpy.utils.unregister_class(PROCESS_OT_Sleek)
    bpy.utils.unregister_class(STOP_OT_Sleek)
    bpy.utils.unregister_class(OPENFOLDER_OT_Sleek)
    bpy.utils.unregister_class(PANEL_PT_Sleek)

    del bpy.types.Scene.sleek_progress
    del bpy.types.Scene.sleek_running


if __name__ == "__main__":
    register()
