import bpy
import mathutils
import struct
import os
import io
from bpy_extras.io_utils import ImportHelper
from bpy.props import (BoolProperty,
                       FloatProperty,
                       StringProperty,
                       EnumProperty,
                       CollectionProperty
                       )
from ..FrontiersAnimDecompress.process_buffer import decompress

def get_matrix_map_global(obj, matrix_map_local, scale_map):
    # Get global matrix of raw bone tracks, which are relative to parent track's local space.
    # Location is assumed to be unaffected by scale. Parent bone scaling in Blender affects locations
    # of child bones, so final position and rotation matrices must be calculated without scale first.
    matrix_map_global = {}
    for pbone in obj.pose.bones:
        matrix = mathutils.Matrix()
        scale = scale_map[pbone.name].copy()

        # Get final transform matrix and scale separately
        for parent_bone in reversed(pbone.parent_recursive):
            if parent_bone.name in matrix_map_local:
                matrix @= matrix_map_local[parent_bone.name]
                scale *= scale_map[parent_bone.name]
        matrix @= matrix_map_local[pbone.name]

        # Substitute proper scale in matrix with unscaled bone transform
        tmp_loc, tmp_rot, tmp_scale = matrix.decompose()
        matrix = mathutils.Matrix.LocRotScale(tmp_loc, tmp_rot, scale)
        matrix_map_global.update({pbone.name: matrix})
    return matrix_map_global


def set_pose_matrices_global(obj, matrix_map_global, frame, keyframe_rules):
    # Update global positions without needing bpy.context.view_layer.update()
    # Based on example in Blender docs https://docs.blender.org/api/current/bpy.types.Bone.html#convert_local_to_pose
    def rec(pbone, parent_matrix):
        if pbone.name in matrix_map_global:
            # Compute and assign local matrix, using the new parent matrix
            matrix = matrix_map_global[pbone.name].copy()
            if pbone.parent:
                pbone.matrix_basis = pbone.bone.convert_local_to_pose(matrix,
                                                                      pbone.bone.matrix_local,
                                                                      parent_matrix=parent_matrix,
                                                                      parent_matrix_local=pbone.parent.bone.matrix_local,
                                                                      invert=True)
            else:
                pbone.matrix_basis = pbone.bone.convert_local_to_pose(matrix,
                                                                      pbone.bone.matrix_local,
                                                                      invert=True)
        else:
            # Compute the updated pose matrix from local and new parent matrix
            if pbone.parent:
                matrix = pbone.bone.convert_local_to_pose(pbone.matrix_basis,
                                                          pbone.bone.matrix_local,
                                                          parent_matrix=parent_matrix,
                                                          parent_matrix_local=pbone.parent.bone.matrix_local)
            else:
                matrix = pbone.bone.convert_local_to_pose(pbone.matrix_basis, pbone.bone.matrix_local)

        pbone.keyframe_insert('rotation_quaternion', frame=frame, options=keyframe_rules)
        pbone.keyframe_insert('location', frame=frame, options=keyframe_rules)
        pbone.keyframe_insert('scale', frame=frame, options=keyframe_rules)

        # Recursively process children, passing the new matrix through
        for child in pbone.children:
            rec(child, matrix)

    # Scan all bone trees from their roots
    for pbone in obj.pose.bones:
        if not pbone.parent:
            rec(pbone, None)


class FrontiersAnimImport(bpy.types.Operator, ImportHelper):
    bl_idname = "import_anim.frontiers_anim"
    bl_label = "Import"
    bl_description = "Imports compressed Sonic Frontiers animation"
    bl_options = {'PRESET', 'UNDO'}
    filename_ext = ".pxd"
    filter_glob: StringProperty(
        default="*.pxd",
        options={'HIDDEN'},
    )
    filepath: StringProperty(subtype='FILE_PATH', )
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    bool_yx_skel: BoolProperty(
        name="Use YX Bone Orientation",
        description="Enable if your skeleton was reoriented for Blender's YX orientation instead of Frontiers' XZ",
        default=False,
    )

    bool_keyframe_needed: BoolProperty(
        name="Insert Needed Keyframes Only",
        description="Refrains from inserting keyframes if values are exact same as previous frame",
        default=False,
    )

    loop_check: EnumProperty(
        items=[
            ("loop_auto", "Auto", "Copy first frame to last if \"_loop\" is in the file name", 1),
            ("loop_yes", "Yes", "Always copy the first frame to the last frame", 2),
            ("loop_no", "No", "Import file contents like normal", 3),
        ],
        name="Loop",
        description="For animations that get messed up from being recompressed and decompressed multiple times "
                    "(not great for animations with 360 rotations)",
        default="loop_no",
    )

    def __init__(self):
        self.bool_skel_conv = False
        self.bool_is_loop = False

    def draw(self, context):
        layout = self.layout
        ui_scene_box = layout.box()
        ui_scene_box.label(text="Animation Settings", icon='ACTION')

        ui_scene_row_loop = ui_scene_box.row()
        ui_scene_row_loop.label(text="Fix Loop:")
        ui_scene_row_loop.prop(self, "loop_check", text="")

        ui_scene_row_needed = ui_scene_box.row()
        ui_scene_row_needed.prop(self, "bool_keyframe_needed", )

        ui_bone_box = layout.box()
        ui_bone_box.label(text="Armature Settings", icon='ARMATURE_DATA')

        ui_orientation_row = ui_bone_box.row()
        ui_orientation_row.prop(self, "bool_yx_skel", )

    @classmethod
    def poll(cls, context):
        obj = bpy.context.active_object
        if obj and obj.type == 'ARMATURE':
            return True
        else:
            return False

    def execute(self, context):
        arm_active = bpy.context.active_object
        if not arm_active:
            self.report({'INFO'}, f"No active armature. Please select an armature.")
            return {'CANCELLED'}
        if arm_active.type != 'ARMATURE':
            self.report({'INFO'}, f"Active object \"{arm_active.name}\" is not an armature. Please select an armature.")
            return {'CANCELLED'}

        bone_count = len(arm_active.pose.bones)
        scene_active = bpy.context.scene
        for bone in arm_active.data.bones:
            bone.inherit_scale = 'ALIGNED'

        print("Importing animations...")
        for i, file in enumerate(self.files):
            # print(f"{i + 1} / {len(self.files)}")
            anim_file = open(os.path.join(os.path.dirname(self.filepath), file.name), "rb")
            if not self.anim_check(anim_file):
                return {'CANCELLED'}

            anim_file.seek(4, 0)
            file_size = int.from_bytes(anim_file.read(4), byteorder='little')
            anim_file.seek(0x58, 0)

            anim_file.seek(0x80, 0)
            main_buffer_length = int.from_bytes(anim_file.read(4), byteorder='little')
            anim_file.seek(0x80, 0)
            main_buffer_compressed = anim_file.read(main_buffer_length)
            main_buffer = decompress(main_buffer_compressed)
            del main_buffer_compressed

            anim_file.seek(0x70, 0)
            root_buffer_offset = int.from_bytes(anim_file.read(8), byteorder='little')

            # Animations compressed with old FrontiersAnimDecompress.exe had non-existent root chunk offsets beyond EOF
            if 0 < root_buffer_offset < file_size:
                anim_file.seek(root_buffer_offset + 0x40, 0)
                root_buffer_length = int.from_bytes(anim_file.read(4), byteorder='little')
                anim_file.seek(root_buffer_offset + 0x40, 0)
                root_buffer_compressed = anim_file.read(root_buffer_length)
                root_buffer = decompress(root_buffer_compressed)
                del root_buffer_compressed

            anim_file.close()
            del anim_file

            frame_time = struct.unpack('<f', main_buffer.read(0x4))[0]
            frame_rate = struct.unpack('<f', main_buffer.read(0x4))[0]
            frame_count = int.from_bytes(main_buffer.read(4), byteorder='little')
            track_count = int.from_bytes(main_buffer.read(4), byteorder='little')

            if bone_count != track_count:
                self.report(
                    {'WARNING'},
                    f"Bone count of \"{arm_active.data.name}\" ({bone_count}) does not match track count of \"{file.name}\" ({track_count}). Results may not turn out as expected."
                )

            anim_name = file.name
            for ext in [".outanim", ".anm", ".pxd"]:
                anim_name = anim_name.replace(ext, "")

            keyframe_rules = set()
            if self.loop_check == "loop_yes":
                self.bool_is_loop = True
            elif self.loop_check == "loop_auto" and "_loop" in anim_name:
                self.bool_is_loop = True
            else:
                self.bool_is_loop = False
            if self.bool_is_loop:
                keyframe_rules.add('INSERTKEY_CYCLE_AWARE')

            arm_active.animation_data_create()
            action_active = bpy.data.actions.new(anim_name)
            arm_active.animation_data.action = action_active

            # frame_rate = (frame_count - 1) / frame_time
            scene_active.render.fps = int(round(frame_rate))
            scene_active.render.fps_base = scene_active.render.fps / frame_rate
            scene_active.frame_start = 0
            scene_active.frame_end = frame_count - 1

            action_active.use_frame_range = True
            action_active.frame_start = 0
            action_active.frame_end = frame_count - 1
            if self.bool_is_loop:
                action_active.use_cyclic = True

            action_active["pxd_export"] = True
            action_active["pxd_fps"] = frame_rate

            for frame in range(frame_count):
                if self.bool_is_loop and frame == frame_count - 1:
                    main_buffer.seek(0x10)
                else:
                    main_buffer.seek(0x10 + 0x30 * track_count * frame)

                matrix_map_local = {}
                scale_map = {}

                for i in range(bone_count):
                    pbone = arm_active.pose.bones[i]
                    if i not in range(track_count):
                        matrix_map_local.update({pbone.name: mathutils.Matrix()})
                        scale_map.update({pbone.name: mathutils.Vector((1.0, 1.0, 1.0))})
                    else:
                        if self.bool_yx_skel:
                            qz, qx, qy, qw = struct.unpack('<ffff', main_buffer.read(0x10))
                            pz, px, py = struct.unpack('<fff', main_buffer.read(0xC))
                            main_buffer.read(4)  # Float: Bone length
                            sz, sx, sy = struct.unpack('<fff', main_buffer.read(0xC))
                            main_buffer.read(4)  # Float: 1.0
                        else:
                            qx, qy, qz, qw = struct.unpack('<ffff', main_buffer.read(0x10))
                            px, py, pz = struct.unpack('<fff', main_buffer.read(0xC))
                            main_buffer.read(4)  # Float: Bone length
                            sx, sy, sz = struct.unpack('<fff', main_buffer.read(0xC))
                            main_buffer.read(4)  # Float: 1.0

                        # Keep location and rotation separate from scale in order to calculate proper global matrix
                        tmp_loc = mathutils.Vector((px, py, pz))
                        tmp_rot = mathutils.Quaternion((qw, qx, qy, qz))
                        matrix = mathutils.Matrix.LocRotScale(tmp_loc, tmp_rot, mathutils.Vector((1.0, 1.0, 1.0)))
                        matrix_map_local.update({pbone.name: matrix})

                        if (sx, sy, sz) != (0.0, 0.0, 0.0):
                            tmp_scale = mathutils.Vector((sx, sy, sz))
                        else:
                            tmp_scale = mathutils.Vector((1.0, 1.0, 1.0))
                        scale_map.update({pbone.name: tmp_scale})

                matrix_map_global = get_matrix_map_global(arm_active, matrix_map_local, scale_map)
                set_pose_matrices_global(arm_active, matrix_map_global, frame, keyframe_rules)

        return {'FINISHED'}

    def anim_check(self, file):
        file.seek(0x40, 0)
        magic = file.read(4)
        version = int.from_bytes(file.read(4), byteorder='little')
        compressed = int.from_bytes(file.read(4), byteorder='little')
        if magic != b'NAXP':
            self.report({'ERROR'}, "Not a valid PXD animation file")
            return False
        if version != 512:
            self.report({'ERROR'}, "Wrong PXD version")
            return False
        if compressed != 2048:
            self.report({'ERROR'}, "PXD animation is uncompressed")
            return False
        file.seek(0, 0)
        return True

    def menu_func_import(self, context):
        self.layout.operator(
            FrontiersAnimImport.bl_idname,
            text="Frontiers Compressed Animation (.anm.pxd)",
            icon='ACTION',
        )

# Untested function, theoretical scribble for numpy index lookup for parents
'''
def get_parent(obj):
    matrix_map = []
    matrix_map_final = mathutils.Matrix():

    def get_map_recursive(bone, mat_map, mat_map_final):
        if bone.parent:
            mat_map.append(bone.matrix.copy())
            get_map_recursive(bone.parent, mat_map, mat_map_final)
        else:
            for mat in mat_map:
                mat_map_final[bone.name] @= mat

    for pbone in obj.pose.bones:
        get_map_recursive(pbone, matrix_map, matrix_map_final)

    return matrix_map_final
'''