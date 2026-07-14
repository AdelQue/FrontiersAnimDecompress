from __future__ import annotations
import bpy
import math
import os
import numpy as np
from struct import unpack
from bpy_extras.io_utils import ImportHelper
from mathutils import Quaternion, Matrix, Vector
from bpy.props import (BoolProperty,
                       StringProperty,
                       EnumProperty,
                       CollectionProperty
                       )

from ..FrontiersAnimDecompress.process_buffer import decompress
from .console_output import BatchProgress
from ..helpers import *
from .anim_common import *
from .import_uncompressed import UncompressedTransform

BINA_OFFSET = 0x40


class FrontiersAnimImport(bpy.types.Operator, ImportHelper):
    bl_idname = "import_anim.frontiers_anim"
    bl_label = "Import"
    bl_description = "Imports compressed Hedgehog Engine 2 PXD animation"
    bl_options = {'PRESET', 'UNDO'}
    filename_ext = ".anm.pxd"
    filter_glob: StringProperty(
        default="*.anm.pxd",
        options={'HIDDEN'},
    )
    filepath: StringProperty(subtype='FILE_PATH', )
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    bool_yx_skel: BoolProperty(
        name="Use YX Bone Orientation",
        description="Enable if your skeleton was reoriented for Blender's YX orientation instead of HE2's XZ",
        default=True,
    )

    bool_root_motion: BoolProperty(
        name="Import Root Motion",
        description="Import root motion animation onto skeleton object's transform",
        default=True,
    )

    bool_keyframe_needed: BoolProperty(
        name="Insert Needed Keyframes Only",
        description="Refrains from inserting keyframes if values are exact same as previous frame (not working)",
        default=False,
    )

    enum_loop_check: EnumProperty(
        items=[
            ("loop_auto", "Auto", "Pad the animation if \"_loop\" is in the file name", 1),
            ("loop_yes", "Yes", "Force pad the animation", 2),
            ("loop_no", "No", "Import file contents like normal", 3),
        ],
        name="Pad loop",
        description="(NOTE: Does not work on uncompressed animations)\n"
                    "(NOTE: May or may not cause issues with 360deg rotations)\n\n"
                    "Imports the animation with copies of the animation before and after the export range. Useful for advanced users trying to do things like smoothly looping physics animations",
        default="loop_no",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bool_skel_conv = False
        self.frame_count_loop = 0
        self.pad_loop = False

    def draw(self, context):
        layout = self.layout
        ui_scene_box = layout.box()
        ui_scene_box.label(text="Animation Settings", icon='ACTION')

        ui_scene_row_loop = ui_scene_box.row()
        ui_scene_row_loop.label(text="Pad Loop:")
        ui_scene_row_loop.prop(self, "enum_loop_check", text="")

        ui_scene_row_root_motion = ui_scene_box.row()
        ui_scene_row_root_motion.prop(self, "bool_root_motion", )

        # Currently not working as expected, meant to only insert keyframes if local transform is different
        # ui_scene_row_needed = ui_scene_box.row()
        # ui_scene_row_needed.prop(self, "bool_keyframe_needed")

        ui_bone_box = layout.box()
        ui_bone_box.label(text="Armature Settings", icon='ARMATURE_DATA')

        ui_orientation_row = ui_bone_box.row()
        ui_orientation_row.prop(self, "bool_yx_skel", )

    @classmethod
    def poll(cls, context):
        obj = context.active_object
        if obj and obj.type == 'ARMATURE':
            return True
        else:
            return False

    def execute(self, context):
        # Scene check and setup
        arm_active = context.active_object
        scene_active = context.scene

        if not arm_active:
            self.report({'INFO'}, f"No active armature. Please select an armature.")
            return {'CANCELLED'}
        if arm_active.type != 'ARMATURE':
            self.report({'INFO'}, f"Active object \"{arm_active.name}\" is not an armature. Please select an armature.")
            return {'CANCELLED'}

        arm_data = ArmatureData(arm_active)
        arm_data.prepare_settings()

        # Status logging
        self.progress = BatchProgress(self, num_items=len(self.files), method='IMPORT')

        for f, file in enumerate(self.files):
            # Begin import
            filepath = os.path.join(os.path.dirname(self.filepath), file.name)
            anim_param = PXDAnimData(filepath)
            anim_file = anim_param.stream

            self.progress.update_frame_count(anim_param.frame_count)
            self.progress.resume(frame_num=-1, name=file.name, item_num=f)

            if (not anim_param) or anim_param.error:
                self.progress.update_error(name=file.name, error=anim_param.error)
                continue

            scene_active.render.fps = int(round(anim_param.frame_rate))

            if anim_param.frame_rate != 0.0:
                scene_active.render.fps_base = scene_active.render.fps / anim_param.frame_rate # in case calculated frame rate ends up as non-integer value
            else:
                scene_active.render.fps_base = 1.0

            if arm_data.bone_count != anim_param.track_count:
                self.report(
                    {'WARNING'},
                    f"Bone count of \"{arm_active.data.name}\" ({arm_data.bone_count}) does not match track count of \"{file.name}\" ({anim_param.track_count}). Results may not turn out as expected."
                )

            action_data = ActionData(arm_data, anim_param)
            action_active = action_data.action

            if self.enum_loop_check == "loop_yes" or (self.enum_loop_check == "loop_auto" and "_loop" in anim_param.name):
                self.pad_loop = True

            # frame_count_loop used ubiquitously in case of padding
            if self.pad_loop and anim_param.is_compressed:
                self.frame_count_loop = 3 * (anim_param.frame_count - 1) + 1
                # Weird Blender behavior requires this to be set later
                # action_active.frame_start = anim_param.frame_count - 1
                # action_active.frame_end = self.frame_count_loop - anim_param.frame_count
                action_active.use_cyclic = True
            else:
                self.frame_count_loop = anim_param.frame_count
                scene_active.frame_start = action_active.frame_start = 0
                scene_active.frame_end = action_active.frame_end = self.frame_count_loop - 1

            action_active.pxd_export = True
            action_active.pxd_fps = anim_param.frame_rate
            action_active.pxd_root = self.bool_root_motion
            action_active.pxd_compress = anim_param.is_compressed
            action_active.pxd_additive = anim_param.is_additive

            if anim_param.is_compressed:
                import_action = self.import_compressed(arm_data, action_data, anim_file, anim_param)
            else:
                unc_data = UncompressedTransform(arm_data, anim_param)
                import_action = self.import_uncompressed(arm_data, action_data, anim_param, unc_data)
            anim_file.close()
            del anim_file
            if not import_action:
                self.progress.update_error(error=f"{file.name} compressed animation import couldn't be processed. File skipped.")
                continue

            # Keyframes become invisible if this is set earlier than anim import.
            if self.pad_loop and anim_param.is_compressed:
                scene_active.frame_start = action_active.frame_start = anim_param.frame_count - 1
                scene_active.frame_end = action_active.frame_end = self.frame_count_loop - anim_param.frame_count

        self.progress.finish()
        return {'FINISHED'}

    def import_compressed(self,
                          arm_data: ArmatureData,
                          action_data: ActionData,
                          anim_file,
                          anim_data):


        frame_count = anim_data.frame_count
        track_count = anim_data.track_count
        main_offset = anim_data.main_offset
        root_offset = anim_data.root_offset

        arm_active   = arm_data.object
        bone_names   = arm_data.bone_names
        bone_parents = arm_data.bone_parents
        bone_count   = arm_data.bone_count


        anim_file.seek(main_offset)
        main_buffer_length = int.from_bytes(anim_file.read(4), byteorder='little')
        anim_file.seek(main_offset)
        main_buffer_compressed = anim_file.read(main_buffer_length)
        main_buffer = decompress(main_buffer_compressed)

        if not len(main_buffer.getvalue()):
            self.progress.update_error(error=f"{anim_data.name} buffer failed to initialize. File skipped.")
            return False
        del main_buffer_compressed

        if self.bool_root_motion and (root_offset is not None):
            anim_file.seek(root_offset, 0)
            root_buffer_length = int.from_bytes(anim_file.read(4), byteorder='little')
            anim_file.seek(root_offset, 0)
            root_buffer_compressed = anim_file.read(root_buffer_length)
            root_buffer = decompress(root_buffer_compressed)
            if not len(root_buffer.getvalue()):
                self.report({'WARNING'},f"{anim_data.name} root buffer failed to initialize. Importing without root motion.")
                root_buffer = None
            del root_buffer_compressed
        else:
            root_buffer = None

        # Nice for sanity check, but not necessary
        duration_acl = unpack('<f', main_buffer.read(0x4))[0]
        frame_rate_acl = unpack('<f', main_buffer.read(0x4))[0]
        frame_count_acl = int.from_bytes(main_buffer.read(4), byteorder='little')
        track_count_acl = int.from_bytes(main_buffer.read(4), byteorder='little')

        # +1 for potential root motion
        np_loc = np.empty((track_count+1, 3, self.frame_count_loop*2), dtype=np.float32)
        np_rot = np.empty((track_count+1, 4, self.frame_count_loop*2), dtype=np.float32)
        np_scl = np.empty((track_count+1, 3, self.frame_count_loop*2), dtype=np.float32)
        root_i = track_count

        for frame in range(self.frame_count_loop):
            # self.progress.resume(frame_num=frame)
            if self.pad_loop:
                main_buffer.seek(0x10 + (0x30 * track_count * (frame % (frame_count - 1))))
            else:
                main_buffer.seek(0x10 + (0x30 * track_count * frame))

            matrix_map_local = {}
            scale_map = {}

            for i in range(bone_count):
                name = arm_data.bone_names[i]
                if i in range(track_count):
                    r0, r1, r2, r3 = unpack('<ffff', main_buffer.read(0x10))
                    p0, p1, p2, __ = unpack('<ffff', main_buffer.read(0x10))
                    s0, s1, s2, __ = unpack('<ffff', main_buffer.read(0x10))

                    if self.bool_yx_skel:
                        tmp_rot = Quaternion((r3, r2, r0, r1))
                        tmp_loc = Vector((p2, p0, p1))
                        if not arm_data.bone_parents[name]:
                            tmp_rot @= ROOT_BONE_ROTATE
                    else:
                        tmp_rot = Quaternion((r3, r0, r1, r2))
                        tmp_loc = Vector((p0, p1, p2))

                    matrix = Matrix.LocRotScale(tmp_loc, tmp_rot, None)
                    matrix_map_local[name] = matrix

                    if (s0, s1, s2) != (0.0, 0.0, 0.0):
                        if self.bool_yx_skel:
                            tmp_scale = Vector((s2, s0, s1))
                        else:
                            tmp_scale = Vector((s0, s1, s2))
                    else:
                        tmp_scale = Vector((1.0, 1.0, 1.0))

                    scale_map[name] = tmp_scale

                else:
                    matrix_map_local[name] = Matrix()
                    scale_map[name] = Vector((1.0, 1.0, 1.0))

            matrix_map_global = get_matrix_map_global(arm_data, matrix_map_local, scale_map)
            matrix_map_basis = get_matrix_map_basis(arm_data, matrix_map_global)

            frame_f = float(frame)
            np_frame_i  = frame*2
            np_val_i = np_frame_i+1
            for i in range(track_count):
                name = bone_names[i]
                mat = matrix_map_basis[name]
                loc, rot, scl = mat.decompose()

                for j, val in enumerate(loc):
                    np_loc[i][j][np_frame_i] = frame_f
                    np_loc[i][j][np_val_i] = val

                for j, val in enumerate(rot):
                    np_rot[i][j][np_frame_i] = frame_f
                    np_rot[i][j][np_val_i] = val

                for j, val in enumerate(scl):
                    np_scl[i][j][np_frame_i] = frame_f
                    np_scl[i][j][np_val_i] = val

            ### TODO ###

            if root_buffer:
                action_data.make_root_curves()

                if self.pad_loop:
                    root_buffer.seek(0x10 + (0x30 * (frame % (frame_count - 1))))
                else:
                    root_buffer.seek(0x10 + (0x30 * frame))

                r0, r1, r2, r3 = unpack('<ffff', root_buffer.read(0x10))
                p0, p1, p2, __ = unpack('<ffff', root_buffer.read(0x10))
                s0, s1, s2, __ = unpack('<ffff', root_buffer.read(0x10))

                rot = ROOT_OBJ_ROTATE.copy()
                rot @= Quaternion((r3, r0, r1, r2))
                loc = Vector((p0, -p2, p1))
                if (s0, s1, s2) != (0.0, 0.0, 0.0):
                    scl = Vector((s0, s1, s2))
                else:
                    scl = Vector((1.0, 1.0, 1.0))

                for j, val in enumerate(loc):
                    np_loc[root_i][j][np_frame_i] = frame_f
                    np_loc[root_i][j][np_val_i] = val

                for j, val in enumerate(rot):
                    np_rot[root_i][j][np_frame_i] = frame_f
                    np_rot[root_i][j][np_val_i] = val

                for j, val in enumerate(scl):
                    np_scl[root_i][j][np_frame_i] = frame_f
                    np_scl[root_i][j][np_val_i] = val

            elif self.bool_root_motion and not root_buffer:
                self.report({'INFO'}, "No root motion chunk found.")

        action_data.add_kps_compressed(self.frame_count_loop)

        for i in range(track_count):
            name = bone_names[i]
            fc_loc, fc_rot, fc_scl = action_data.fcurves[name]
            [fc.keyframe_points.foreach_set('co', np_loc[i][j]) for j, fc in enumerate(fc_loc)]
            [fc.keyframe_points.foreach_set('co', np_rot[i][j]) for j, fc in enumerate(fc_rot)]
            [fc.keyframe_points.foreach_set('co', np_scl[i][j]) for j, fc in enumerate(fc_scl)]

        if action_data.fcurves_root:
            fc_loc, fc_rot, fc_scl = action_data.fcurves_root
            [fc.keyframe_points.foreach_set('co', np_loc[root_i][j]) for j, fc in enumerate(fc_loc)]
            [fc.keyframe_points.foreach_set('co', np_rot[root_i][j]) for j, fc in enumerate(fc_rot)]
            [fc.keyframe_points.foreach_set('co', np_scl[root_i][j]) for j, fc in enumerate(fc_scl)]

        action_data.update_curves()

        return True

    def import_uncompressed(
            self,
            arm_data: ArmatureData,
            action_data: ActionData,
            anim_data,
            uncompressed_data):   # TODO

        arm_active   = arm_data.object
        frame_count  = anim_data.frame_count
        track_count  = anim_data.track_count
        main_offset  = anim_data.main_offset
        root_offset  = anim_data.root_offset
        bone_names   = arm_data.bone_names
        bone_parents = arm_data.bone_parents
        bone_count   = arm_data.bone_count

        # +1 for potential root motion
        np_loc = np.empty((track_count + 1, 3, self.frame_count_loop * 2), dtype=np.float32)
        np_rot = np.empty((track_count + 1, 4, self.frame_count_loop * 2), dtype=np.float32)
        np_scl = np.empty((track_count + 1, 3, self.frame_count_loop * 2), dtype=np.float32)
        root_i = track_count



        for frame in range(self.frame_count_loop):

            matrix_map_basis = uncompressed_data.make_matrix_map(frame)

            frame_f = float(frame)
            np_frame_i = frame * 2
            np_val_i = np_frame_i + 1
            for i in range(track_count):
                name = bone_names[i]
                mat = matrix_map_basis[name]
                loc, rot, scl = mat.decompose()

                for j, val in enumerate(loc):
                    np_loc[i][j][np_frame_i] = frame_f
                    np_loc[i][j][np_val_i] = val

                for j, val in enumerate(rot):
                    np_rot[i][j][np_frame_i] = frame_f
                    np_rot[i][j][np_val_i] = val

                for j, val in enumerate(scl):
                    np_scl[i][j][np_frame_i] = frame_f
                    np_scl[i][j][np_val_i] = val

        action_data.add_kps_compressed(self.frame_count_loop)

        for i in range(track_count):
            name = bone_names[i]
            fc_loc, fc_rot, fc_scl = action_data.fcurves[name]
            [fc.keyframe_points.foreach_set('co', np_loc[i][j]) for j, fc in enumerate(fc_loc)]
            [fc.keyframe_points.foreach_set('co', np_rot[i][j]) for j, fc in enumerate(fc_rot)]
            [fc.keyframe_points.foreach_set('co', np_scl[i][j]) for j, fc in enumerate(fc_scl)]

        if action_data.fcurves_root:
            fc_loc, fc_rot, fc_scl = action_data.fcurves_root
            [fc.keyframe_points.foreach_set('co', np_loc[root_i][j]) for j, fc in enumerate(fc_loc)]
            [fc.keyframe_points.foreach_set('co', np_rot[root_i][j]) for j, fc in enumerate(fc_rot)]
            [fc.keyframe_points.foreach_set('co', np_scl[root_i][j]) for j, fc in enumerate(fc_scl)]

        action_data.update_curves()

        return True

    def menu_func_import(self, context):
        self.layout.operator(
            FrontiersAnimImport.bl_idname,
            text="Hedgehog Engine 2 Animation (.anm.pxd)",
            icon='ACTION',
        )
