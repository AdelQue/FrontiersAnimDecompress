import sys
import bpy
import bmesh
import os
import io
import struct
import math
import mathutils
import binascii
from bpy.props import (BoolProperty,
                       FloatProperty,
                       StringProperty,
                       EnumProperty,
                       CollectionProperty
                       )
from bpy_extras.io_utils import ExportHelper


def utils_set_mode(mode):
    if bpy.ops.object.mode_set.poll():
        bpy.ops.object.mode_set(mode=mode, toggle=False)


def offset_table(offset):
    offset_bits_2 = "{0:b}".format(offset >> 2)
    print(offset_bits_2)
    if offset > 16384:
        offset_bits = '11'
        for x in range(30 - len(offset_bits_2)):
            offset_bits += '0'
    elif offset > 64:
        offset_bits = '10'
        for x in range(14 - len(offset_bits_2)):
            offset_bits += '0'
    else:
        offset_bits = '01'
        for x in range(6 - len(offset_bits_2)):
            offset_bits += '0'
    return offset_bits + offset_bits_2


class BoneTransform:
    def __init__(self, Bone):
        Mat = Bone.matrix_local
        if Bone.parent:
            Mat = Bone.parent.matrix_local.inverted() @ Bone.matrix_local
        self.pos = Mat.translation
        self.rot = Mat.to_quaternion()


class MoveArray:
    def __init__(self, Arm):
        self.parent_indices = []
        self.name = []
        self.transform = []
        for x in range(len(Arm.pose.bones)):
            if (Arm.pose.bones[x].parent):
                self.parent_indices.append(Arm.pose.bones.find(Arm.pose.bones[x].parent.name))
            else:
                self.parent_indices.append(65535)
            self.name.append(bytes(Arm.pose.bones[x].name, 'ascii') + b'\x00')
            self.transform.append(BoneTransform(Arm.pose.bones[x].bone))


class FrontiersSkeletonExport(bpy.types.Operator, ExportHelper):
    bl_idname = "custom_export_skeleton.frontiers_skel"
    bl_label = "export"
    filename_ext = ".pxd"
    filter_glob: StringProperty(
        default="*.pxd",
        options={'HIDDEN'},
    )
    filepath: StringProperty(subtype='FILE_PATH', )
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    use_yx_orientation: BoolProperty(
        name="Use YX Bone Orientation",
        description="If your skeleton was imported from XZ to YX to function better in Blender, use this option to switch bones back from YX to XZ (important for in-game IK)",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        uiBoneBox = layout.box()
        uiBoneBox.label(text="Armature Settings", icon="ARMATURE_DATA")
        uiBoneBox.prop(self, "use_yx_orientation")

    def execute(self, context):
        Arm = bpy.context.active_object
        Scene = bpy.context.scene
        if not Arm:
            raise ValueError("No active object. Please select an armature as your active object.")
        if Arm.type != 'ARMATURE':
            raise TypeError(f"Active object \"{Arm.name}\" is not an armature. Please select an armature.")

        buffer = io.BytesIO()

        magic = bytes('KSXP', 'ascii')
        buffer.write(magic)
        buffer.write(struct.pack('<i', 512))
        Array = MoveArray(Arm)

        ParentOffset = 104
        Null = 0

        buffer.write(ParentOffset.to_bytes(8, 'little'))
        buffer.write(len(Arm.pose.bones).to_bytes(8, 'little'))
        buffer.write(len(Arm.pose.bones).to_bytes(8, 'little'))
        buffer.write(Null.to_bytes(8, 'little'))

        NameOffset = ParentOffset + (len(Arm.pose.bones) + 1) * 2
        if NameOffset % 0x10 != 0:
            NameOffset += 0x10 - NameOffset % 0x10

        buffer.write(NameOffset.to_bytes(8, 'little'))
        buffer.write(len(Arm.pose.bones).to_bytes(8, 'little'))
        buffer.write(len(Arm.pose.bones).to_bytes(8, 'little'))
        buffer.write(Null.to_bytes(8, 'little'))

        MatrixOffset = NameOffset + len(Arm.pose.bones) * 0x10

        buffer.write(MatrixOffset.to_bytes(8, 'little'))
        buffer.write(len(Arm.pose.bones).to_bytes(8, 'little'))
        buffer.write(len(Arm.pose.bones).to_bytes(8, 'little'))
        buffer.write(Null.to_bytes(8, 'little'))

        for x in range(len(Arm.pose.bones)):
            ParentIndex = Array.parent_indices[x].to_bytes(2, 'little')
            buffer.write(ParentIndex)

        if buffer.tell() % 0x10 != 0:
            for x in range(0x10 - buffer.tell() % 0x10):
                buffer.write(Null.to_bytes(1, 'little'))

        NameDataOffset = MatrixOffset + len(Arm.pose.bones) * 0x30

        for x in range(len(Arm.pose.bones)):
            buffer.write(NameDataOffset.to_bytes(16, 'little'))
            NameDataOffset += len(Array.name[x])

        for x in range(len(Arm.pose.bones)):
            if self.use_yx_orientation:
                if not Arm.pose.bones[x].parent:
                    Array.transform[x].rot @= mathutils.Quaternion((0.5, 0.5, 0.5, 0.5))
                buffer.write(struct.pack('<f', Array.transform[x].pos[1]))
                buffer.write(struct.pack('<f', Array.transform[x].pos[2]))
                buffer.write(struct.pack('<f', Array.transform[x].pos[0]))
                buffer.write(struct.pack('<f', 0))
                buffer.write(struct.pack('<f', Array.transform[x].rot[2]))
                buffer.write(struct.pack('<f', Array.transform[x].rot[3]))
                buffer.write(struct.pack('<f', Array.transform[x].rot[1]))
                buffer.write(struct.pack('<f', Array.transform[x].rot[0]))
            else:
                buffer.write(struct.pack('<f', Array.transform[x].pos[0]))
                buffer.write(struct.pack('<f', Array.transform[x].pos[1]))
                buffer.write(struct.pack('<f', Array.transform[x].pos[2]))
                buffer.write(struct.pack('<f', 0))
                buffer.write(struct.pack('<f', Array.transform[x].rot[1]))
                buffer.write(struct.pack('<f', Array.transform[x].rot[2]))
                buffer.write(struct.pack('<f', Array.transform[x].rot[3]))
                buffer.write(struct.pack('<f', Array.transform[x].rot[0]))

            buffer.write(struct.pack('<f', 1))
            buffer.write(struct.pack('<f', 1))
            buffer.write(struct.pack('<f', 1))
            buffer.write(struct.pack('<f', 0))

        StringTableSize = 0

        for x in range(len(Arm.pose.bones)):
            buffer.write(Array.name[x])
            StringTableSize += len(Array.name[x])

        if buffer.tell() % 4 != 0:
            for x in range(4 - buffer.tell() % 4):
                buffer.write(Null.to_bytes(1, 'little'))
                StringTableSize += 1

        OffsetTableSize = 0

        bit = 66
        buffer.write(bit.to_bytes(1, 'little'))
        bit = 72
        buffer.write(bit.to_bytes(1, 'little'))
        buffer.write(bit.to_bytes(1, 'little'))

        OffsetTableSize += 3

        name_offset_bits = offset_table(NameOffset - ParentOffset + 0x20)
        name_offset_buffer = bytearray()
        index = 0
        while index < len(name_offset_bits):
            name_offset_buffer.append(int(name_offset_bits[index:index + 8], 2))
            index += 8

        OffsetTableSize += len(name_offset_buffer)

        buffer.write(name_offset_buffer)

        inbyte = 68
        for x in range(len(Arm.pose.bones) - 1):
            buffer.write(inbyte.to_bytes(1, 'little'))
            OffsetTableSize += 1

        buffer.write(Null.to_bytes(1, 'little'))
        OffsetTableSize += 1

        if buffer.tell() % 4 != 0:
            for x in range(4 - buffer.tell() % 4):
                buffer.write(Null.to_bytes(1, 'little'))
                OffsetTableSize += 1

        with open(self.filepath, "wb") as CurFile:
            buffer_size = buffer.getbuffer().nbytes

            bin_magic = bytes('BINA210L', 'ascii')
            CurFile.write(bin_magic)
            CurFile.write(struct.pack('<i', buffer_size + 0x40))
            CurFile.write(struct.pack('<i', 1))

            data_magic = bytes('DATA', 'ascii')
            CurFile.write(data_magic)
            CurFile.write(struct.pack('<i', buffer_size + 0x30))
            CurFile.write(struct.pack('<i', MatrixOffset + len(Arm.pose.bones) * 0x30))
            CurFile.write(struct.pack('<i', StringTableSize))
            CurFile.write(struct.pack('<i', OffsetTableSize))
            CurFile.write(struct.pack('<i', 0x18))
            CurFile.write(Null.to_bytes(24, 'little'))
            CurFile.write(buffer.getvalue())

        return {'FINISHED'}

    def menu_func_export(self, context):
        self.layout.operator(
            FrontiersSkeletonExport.bl_idname,
            text="Frontiers Skeleton (.skl.pxd)",
            icon='ARMATURE_DATA'
        )
