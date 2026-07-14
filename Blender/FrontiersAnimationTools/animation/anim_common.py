import bpy
import io
import os
from typing import Optional, Union, List, Dict
from dataclasses import dataclass, field
from struct import unpack
from mathutils import Vector, Quaternion, Matrix
from ..helpers import *



SINE_RMS = 1 / math.sqrt(2)
ROOT_OBJ_ROTATE = Quaternion((SINE_RMS, SINE_RMS, 0.0, 0.0))
ROOT_BONE_ROTATE = Quaternion((0.5, -0.5, -0.5, -0.5))


@dataclass
class TransformContainer:
    count:  int
    loc: List[Optional[Union[None, Vector]]]     = field(init=False)
    rot: List[Optional[Union[None, Quaternion]]] = field(init=False)
    scl: List[Optional[Union[None, Vector]]]     = field(init=False)

    def __post_init__(self):
        self.loc = [None for _ in range(self.count)]
        self.rot = [None for _ in range(self.count)]
        self.scl = [None for _ in range(self.count)]


@dataclass
class KeyMaskContainer:
    loc: List[int] = field(default_factory=list)
    rot: List[int] = field(default_factory=list)
    scl: List[int] = field(default_factory=list)


class PXDAnimData:
    def __init__(self, filepath):

        with open(filepath, 'rb') as file:
            self.stream = io.BytesIO(file.read())
            stream = self.stream

        self.name = os.path.basename(filepath)
        for ext in [".outanim", ".anm", ".pxd"]:
            self.name = self.name.replace(ext, "")

        stream.seek(8)
        file_size = int.from_bytes(stream.read(4), byteorder='little')

        stream.seek(BINA_OFFSET)
        magic = stream.read(4)
        if magic != b'NAXP':
            self.error = f"Not a valid PXD animation file"
            return
        version = int.from_bytes(stream.read(4), byteorder='little')
        if version != 512:
            self.error = "Unsupported PXD version"
            return
        flag_additive   = int.from_bytes(stream.read(1), byteorder='little')
        flag_compressed = int.from_bytes(stream.read(1), byteorder='little')

        if flag_additive == 1:
            self.is_additive = True
        else:
            self.is_additive = False

        if flag_compressed == 8:
            self.is_compressed = True
        else:
            self.is_compressed = False

        stream.seek(0x58)
        self.duration = unpack('<f', stream.read(4))[0]
        self.frame_count = int.from_bytes(stream.read(4), byteorder='little')
        if self.duration != 0.0:
            self.frame_rate = (self.frame_count - 1) / self.duration
        else:
            self.frame_rate = 30.0
        self.track_count = int.from_bytes(stream.read(8), byteorder='little')
        self.main_offset = int.from_bytes(stream.read(8), byteorder='little')
        if self.main_offset:
            self.main_offset += BINA_OFFSET
        else:
            self.main_offset = None

        self.root_offset = int.from_bytes(stream.read(8), byteorder='little')
        if self.root_offset:
            self.root_offset += BINA_OFFSET

        # Animations compressed with old FrontiersAnimDecompress had non-existent root chunk offsets beyond EOF
        if (self.root_offset > (file_size - BINA_OFFSET)) or (not self.root_offset):
            self.root_offset = None

        stream.seek(0)
        self.error = None


class ArmatureData:
    def __init__(self, arm_obj):
        self.object = arm_obj
        self.pose_bones = arm_obj.pose.bones
        self.bone = self.pose_bones[0].bone
        self.bone_names = [pbone.name for pbone in self.pose_bones]
        self.bone_count = len(self.pose_bones)
        self.local_matrices = {pbone.name: pbone.bone.matrix_local for pbone in self.pose_bones}

        self.bone_parents = {}
        for pbone in self.pose_bones:
            if pbone.parent:
                self.bone_parents[pbone.name] = pbone.parent.name
            else:
                self.bone_parents[pbone.name] = None

        self.bone_children = {}
        for pbone in self.pose_bones:
            children = []
            if pbone.children:
                children = [child.name for child in pbone.children]
            self.bone_children[pbone.name] = children

        self.bone_paths = {}
        for pbone in self.pose_bones:
            path_loc = pbone.path_from_id("location")
            path_rot = pbone.path_from_id("rotation_quaternion")
            path_scl = pbone.path_from_id("scale")
            self.bone_paths[pbone.name] = [path_loc, path_rot, path_scl]

    def prepare_settings(self):
        self.object.rotation_mode = 'QUATERNION'
        for pbone in self.pose_bones:
            pbone.bone.inherit_scale = 'ALIGNED'
            pbone.rotation_mode = 'QUATERNION'


class ActionData:
    def __init__(self, arm_data: ArmatureData, pxd_data: PXDAnimData):
        self.arm_data = arm_data
        self.object = arm_data.object
        self.object.animation_data_create()
        self.action_name = pxd_data.name
        self.action = bpy.data.actions.new(self.action_name)
        self.action.use_frame_range = True
        self.fcurves = {}
        self.fcurves_root = None
        self.fc_container = self.get_fc_container(self.action)

        for name in arm_data.bone_names:
            path_loc, path_rot, path_scl = arm_data.bone_paths[name]

            fc_loc = [self.fc_container.fcurves.new(path_loc, index=i_loc) for i_loc in range(3)]
            fc_rot = [self.fc_container.fcurves.new(path_rot, index=i_rot) for i_rot in range(4)]
            fc_scl = [self.fc_container.fcurves.new(path_scl, index=i_scl) for i_scl in range(3)]

            for fc in fc_loc + fc_scl:
                fc.color_mode = 'AUTO_RGB'

            for fc in fc_rot:
                fc.color_mode = 'AUTO_YRGB'

            self.fcurves[name] = [fc_loc, fc_rot, fc_scl]

        self.object.animation_data.action = self.action

    def make_root_curves(self):
        fcurves = self.fc_container.fcurves

        if is_version_at_least(5, 0):
            fc_loc = [fcurves.ensure("location",            index=i_loc) for i_loc in range(3)]
            fc_rot = [fcurves.ensure("rotation_quaternion", index=i_rot) for i_rot in range(4)]
            fc_scl = [fcurves.ensure("scale",               index=i_scl) for i_scl in range(3)]

        else:
            fc_loc = [fcurves.find(data_path="location", index=i_loc) for i_loc in range(3)]
            for i_loc in range(3):
                if fc_loc[i_loc] is None:
                    fc_loc[i_loc] = fcurves.new("location", index=i_loc)

            fc_rot = [fcurves.find(data_path="rotation_quaternion", index=i_rot) for i_rot in range(4)]
            for i_rot in range(4):
                if fc_rot[i_rot] is None:
                    fc_rot[i_rot] = fcurves.new("rotation_quaternion", index=i_rot)

            fc_scl = [fcurves.find(data_path="scale", index=i_scl) for i_scl in range(3)]
            for i_scl in range(3):
                if fc_scl[i_scl] is None:
                    fc_scl[i_scl] = fcurves.new("scale", index=i_scl)

        for fc in fc_loc + fc_scl:
            fc.color_mode = 'AUTO_RGB'

        for fc in fc_rot:
            fc.color_mode = 'AUTO_YRGB'

        self.fcurves_root = [fc_loc, fc_rot, fc_scl]

    def get_fc_container(self, action):
        if is_version_at_least(4, 5):
            layer = action.layers.new("Layer")
            slot = action.slots.new(id_type='OBJECT', name=f"{self.object.name}")
            strip = layer.strips.new(type='KEYFRAME')
            channelbag = strip.channelbag(slot, ensure=True)
            return channelbag
        else:
            return action

    def create_np_array(self, track_count, frame_count, is_quat=False):
        # if is_quat:
        #     channels = 4
        # else:
        #     channels = 3
        # return np.empty((track_count, channels, frame_count*2), dtype=np.float32)
        pass

    def update_np_arrays(self, arm_data: ArmatureData, matrix_map_basis, frame):
        # frame_f = float(frame)
        # np_frame_i  = frame*2
        # np_val_i = np_frame_i+1
        #
        # for i in range(arm_data.bone_count):
        #     name = arm_data.bone_names[i]
        #     matrix = matrix_map_basis[name]
        #     loc, rot, scl = matrix.decompose()
        #
        #     for j, val in enumerate(loc):
        #         np_loc[i][j][np_frame_i] = frame_f
        #         np_loc[i][j][np_val_i] = val
        #
        #     for j, val in enumerate(rot):
        #         np_rot[i][j][np_frame_i] = frame_f
        #         np_rot[i][j][np_val_i] = val
        #
        #     for j, val in enumerate(scl):
        #         np_scl[i][j][np_frame_i] = frame_f
        #         np_scl[i][j][np_val_i] = val
        pass

    def add_kps_compressed(self, count):
        [fc.keyframe_points.add(count=count) for fc in self.fc_container.fcurves]

    def add_kps_uncompressed(self, key_masks: dict[KeyMaskContainer]):
        for name in self.arm_data.bone_names:
            fc_loc, fc_rot, fc_scl = self.fcurves[name]
            mask = key_masks[name]
            [fc.keyframe_points.add(count=len(mask.loc)) for fc in fc_loc]
            [fc.keyframe_points.add(count=len(mask.rot)) for fc in fc_rot]
            [fc.keyframe_points.add(count=len(mask.scl)) for fc in fc_scl]

    def update_curves(self):
        [fc.update() for fc in self.fc_container.fcurves]

    def make_points_linear(self):
        for fc in self.fc_container.fcurves:
            for kp in fc.keyframe_points:
                kp.interpolation = 'LINEAR'


def get_matrix_map_global(
        arm_data: ArmatureData,
        matrix_map_local,
        scale_map):
    """
    Get global matrix of raw bone tracks, which are relative to parent track's local space.
    In HE2, scales are inhereted from parents, but locations are not--unlike Blender where scale
    affects locations. We calculate the global location and rotation matrices by multiplying the
    local matrices from the root to the current bone, *then* insert the final scale at the end.
    :param arm_data: Preprocessed armature and bone relationship info -- for speed
    :param matrix_map_local: Dictonary of each bone's local transform matrix, relative to its parent.
    The scale component of these matrices should be 1.0 across the board
    :param scale_map: Dictonary of each bone's local scale vector
    :return: Dictonary of each bone's global transform matrix.
    """
    bone_names = arm_data.bone_names
    bone_parents = arm_data.bone_parents
    bone_children = arm_data.bone_children

    matrix_map_global = {name : Matrix() for name in bone_names}

    # Recursively multiply matrices (and scales) leading up to each bone
    def rec(name, parent_name):

        matrix = matrix_map_global[name]
        if parent_name:
            matrix @= matrix_map_global[parent_name]
            scale_map[name] *= scale_map[parent_name]

        matrix @= matrix_map_local[name]

        if bone_children[name]:
            for child in bone_children[name]:
                rec(child, name)

    for name in bone_names:
        if not bone_parents[name]:
            rec(name, None)

    # Then finally apply scales, as all locations are now final
    for name in bone_names:
        matrix = matrix_map_global[name]
        scale = scale_map[name]
        matrix @= Matrix.Diagonal(scale).to_4x4()

    return matrix_map_global


def get_matrix_map_basis(
        arm_data: ArmatureData,
        matrix_map_global,
        ):
    """
    Once global matrices of all bones are obtained, we can now go back and recalculate the pose bone's matrix_basis,
    which will be its local transforms as a matrix. Constructing this
    :param arm_data: Preprocessed armature and bone relationship info -- for speed
    :param matrix_map_global: Dictonary of each bone's global transform matrix
    :return: Dictonary of each bone's basis transform matrix--another local matrix, but one that is compatible with
    Blender's assumption of scale affecting location
    """

    bone_names = arm_data.bone_names
    bone_parents = arm_data.bone_parents
    bone_children = arm_data.bone_children
    local_matrices = arm_data.local_matrices
    pose_bones = arm_data.pose_bones
    bone = arm_data.bone
    matrix_map_basis = {}

    # Calculate local matrices from global
    # Based on example in Blender docs:
    # https://docs.blender.org/api/current/bpy.types.Bone.html#bpy.types.Bone.convert_local_to_pose
    def rec(name, parent_matrix):
        parent_name = bone_parents[name]
        matrix_local = local_matrices[name]
        if bone_parents[name]:
            parent_matrix_local = local_matrices[parent_name]
        else:
            parent_matrix_local = Matrix()

        if name in matrix_map_global:
            # Compute and assign local matrix, using the new parent matrix
            matrix = matrix_map_global[name]
            if bone_parents[name]:
                matrix_out = bone.convert_local_to_pose( matrix,
                                              matrix_local,
                                              parent_matrix=parent_matrix,
                                              parent_matrix_local=parent_matrix_local,
                                              invert=True )

            else:
                matrix_out = bone.convert_local_to_pose( matrix,
                                                      matrix_local,
                                                      invert=True)

        # If a keyframe isn't present
        else:
            # Compute the updated pose matrix from local and new parent matrix
            matrix_basis = pose_bones[name].matrix_basis
            if bone_parents[name]:
                matrix = bone.convert_local_to_pose(matrix_basis,
                                                          matrix_local,
                                                          parent_matrix=parent_matrix,
                                                          parent_matrix_local=parent_matrix_local)
            else:
                matrix = bone.convert_local_to_pose(matrix_basis, matrix_local)

        matrix_map_basis[name] = matrix_out

        # Recursively process children, passing the new matrix through
        if bone_children[name]:
            for child in bone_children[name]:
                rec(child, matrix)

    # Scan all bone trees from their roots
    for name in bone_names:
        if not bone_parents[name]:
            rec(name, None)

    return matrix_map_basis