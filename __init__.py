import os
import tempfile

import bpy

from .render import render
from .stitch import stitch

bl_info = {"name": "Blender-SkipRender", "blender": (2, 80, 0), "category": "Render"}
temp = tempfile.gettempdir()


def message(message="Message", title="Title", icon="INFO"):
    bpy.context.window_manager.popup_menu(
        lambda self, _: self.layout.label(text=message), title=title, icon=icon
    )


class SkipRenderOperator(bpy.types.Operator):
    bl_idname = "render.run_skip_render"
    bl_label = "Run SkipRender"

    temp: bpy.props.StringProperty(subtype="DIR_PATH", default=temp)
    output: bpy.props.StringProperty(
        subtype="FILE_PATH", default=os.path.join(temp, "output.mov")
    )

    def execute(self, context):
        bpy.ops.sound.mixdown(filepath=os.path.join(self.temp, "audio.flac"))
        render(context.scene, self)
        stitch(context.scene, self)
        message(f"Render Finished!\nSaved to {self.output}", "Blender-SkipRender")

        return {"FINISHED"}


class SkipRenderPanel(bpy.types.Panel):
    bl_idname = "RENDER_PT_skip_render"
    bl_label = "Skip Render"
    bl_space_type = "PROPERTIES"
    bl_region_type = "WINDOW"
    bl_context = "render"

    def draw(self, context):
        op_props = context.window_manager.operator_properties_last(
            "render.run_skip_render"
        )
        row = self.layout.row()
        row.prop(
            op_props,
            "temp",
        )
        row.prop(
            op_props,
            "output",
        )
        row.operator("render.run_skip_render", text="Run")


def register():
    bpy.utils.register_class(SkipRenderOperator)
    bpy.utils.register_class(SkipRenderPanel)


def unregister():
    bpy.utils.unregister_class(SkipRenderOperator)
    bpy.utils.unregister_class(SkipRenderPanel)


if __name__ == "__main__":
    register()
