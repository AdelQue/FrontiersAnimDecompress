import bpy
import mathutils
import struct
import os
import io
from bpy_extras.io_utils import ExportHelper
from bpy.props import (BoolProperty,
                       FloatProperty,
                       StringProperty,
                       EnumProperty,
                       CollectionProperty
                       )
# from ..FrontiersAnimDecompress.process_buffer import compress


class FrontiersAnimExport(bpy.types.Operator, ExportHelper):
    bl_idname = "custom_export_anim.frontiers_anim"
    bl_label = "Export"
    bl_options = {'PRESET', 'UNDO'}
    filename_ext = ".outanim"
    filter_glob: StringProperty(
        default="*.outanim",
        options={'HIDDEN'},
    )
    filepath: StringProperty(subtype='FILE_PATH', )
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    bool_yx_skel: BoolProperty(
        name="Use YX Bone Orientation",
        description="Enable if your skeleton was reoriented for Blender's YX orientation instead of Frontiers' XZ",
        default=False,
    )

    bool_root_motion: BoolProperty(
        name="Export Root Motion",
        description="Enable to export the animation of the armature object as root motion",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        ui_scene_box = layout.box()
        ui_scene_box.label(text="Animation Settings", icon='ACTION')

        ui_root_row = ui_scene_box.row()
        ui_root_row.prop(self, "bool_root_motion", )

        ui_bone_box = layout.box()
        ui_bone_box.label(text="Armature Settings", icon='ARMATURE_DATA')

        ui_orientation_row = ui_bone_box.row()
        ui_orientation_row.prop(self, "bool_yx_skel", )

    def execute(self, context):
        arm_active = bpy.context.active_object
        scene_active = bpy.context.scene
        frame_active = scene_active.frame_current
        if not arm_active:
            raise ValueError("No active object. Please select an armature as your active object.")
        if arm_active.type != 'ARMATURE':
            raise TypeError(f"Active object \"{arm_active.name}\" is not an armature. Please select an armature.")

        for bone in arm_active.data.bones:
            bone.inherit_scale = 'ALIGNED'

        frame_rate = scene_active.render.fps / scene_active.render.fps_base
        frame_count = scene_active.frame_end - scene_active.frame_start + 1
        frame_time = (frame_count - 1) / frame_rate
        bone_count = len(arm_active.pose.bones)

        # for action
        buffer_main = io.BytesIO()
        buffer_root = io.BytesIO()

        buffer_main.write(struct.pack('<f', frame_time))
        buffer_main.write(struct.pack('<i', frame_count))
        buffer_main.write(struct.pack('<i', bone_count))
        # buffer_main.write(struct.pack('<i', 0))

        if self.bool_root_motion:
            buffer_root.write(struct.pack('<f', frame_time))
            buffer_root.write(struct.pack('<i', frame_count))
            # buffer_root.write(struct.pack('<i', 1))

        action_active = arm_active.animation_data.action
        for f in range(frame_count):
            scene_active.frame_set(scene_active.frame_start + f)

            # Build unscaled matrix map and separate scale map
            matrix_map_temp = {}
            scale_map_temp = {}
            for pbone in arm_active.pose.bones:
                tmp_loc, tmp_rot, tmp_scale = pbone.matrix.decompose()
                tmp_matrix = mathutils.Matrix.LocRotScale(tmp_loc, tmp_rot, mathutils.Vector((1.0, 1.0, 1.0)))
                matrix_map_temp.update({pbone.name: tmp_matrix})
                scale_map_temp.update({pbone.name: pbone.scale.copy()})  # normal scale is different from matrix scale

            # Negate unscaled parent matrices, write to file with actual scales
            for pbone in arm_active.pose.bones:
                if pbone.parent:
                    tmp_parent_matrix = matrix_map_temp[pbone.parent.name]
                    tmp_bone_length = pbone.length
                else:
                    tmp_parent_matrix = mathutils.Matrix()
                    tmp_bone_length = 0.0
                tmp_matrix = tmp_parent_matrix.inverted() @ matrix_map_temp[pbone.name]
                tmp_loc, tmp_rot, tmp_scale = tmp_matrix.decompose()
                tmp_scale = scale_map_temp[pbone.name]

                if self.bool_yx_skel:
                    if not pbone.parent:
                        tmp_rot @= mathutils.Quaternion((0.5, 0.5, 0.5, 0.5))  # Fix identity rotation
                    buffer_main.write(struct.pack('<ffff', tmp_rot[2], tmp_rot[3], tmp_rot[1], tmp_rot[0]))
                    buffer_main.write(struct.pack('<fff', tmp_loc[1], tmp_loc[2], tmp_loc[0]))
                    buffer_main.write(struct.pack('<f', tmp_bone_length * tmp_scale[1]))
                    buffer_main.write(struct.pack('<fff', tmp_scale[1], tmp_scale[2], tmp_scale[0]))
                    buffer_main.write(struct.pack('<f', 1.0))
                else:
                    buffer_main.write(struct.pack('<ffff', tmp_rot[1], tmp_rot[2], tmp_rot[3], tmp_rot[0]))
                    buffer_main.write(struct.pack('<fff', tmp_loc[0], tmp_loc[1], tmp_loc[2]))
                    buffer_main.write(struct.pack('<f', tmp_bone_length * tmp_scale[0]))
                    buffer_main.write(struct.pack('<fff', tmp_scale[0], tmp_scale[1], tmp_scale[2]))
                    buffer_main.write(struct.pack('<f', 1.0))

        with open(self.filepath, "wb") as file:
            file.write(buffer_main.getvalue())
        del buffer_main
        del buffer_root

        # main_buffer_compressed = compress(main_buffer)
        # del main_buffer

        # root_buffer_compressed = compress(root_buffer)
        # del root_buffer


        scene_active.frame_current = frame_active

        return{'FINISHED'}

    def menu_func_export(self, context):
        self.layout.operator(
            FrontiersAnimExport.bl_idname,
            text="Frontiers Uncompressed Animation (.outanim)",
            icon='ACTION'
        )
