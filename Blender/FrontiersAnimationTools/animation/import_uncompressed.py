import bpy
from itertools import chain
from mathutils import Matrix, Quaternion, Vector
from struct import unpack
from .anim_common import *





def lerp_process(
        mask:        list[int],
        transforms:  list,
        frame_count: int
):
    """
    Inerpolates a track's transform values
    :param mask: List of frames where a keyframe is present
    :param transforms: List of transform values per frame
    :param frame_count: Total frames expected in the animation
    :return: None
    """
    num_masks = len(mask)
    if num_masks > 1:
        for i in range(num_masks - 1):
            cur_frame  = mask[i]
            next_frame = mask[i + 1]

            cur_trsfm = transforms[cur_frame]
            next_trsfm = transforms[next_frame]

            inter_range = next_frame - cur_frame
            inter_step = 1.0 / inter_range

            for j in range(inter_range - 1):
                inter_frame = cur_frame + j + 1
                factor = inter_step * (j + 1)
                if type(cur_trsfm) == Quaternion:
                    inter_trsfm = Quaternion.slerp(cur_trsfm, next_trsfm, factor)
                else:
                    inter_trsfm = Vector.lerp(cur_trsfm, next_trsfm, factor)

                transforms[inter_frame] = inter_trsfm

            if i == num_masks - 2 and next_frame < frame_count - 1:
                inter_range = frame_count - next_frame
                for j in range(inter_range - 1):
                    inter_frame = next_frame + j + 1
                    transforms[inter_frame] = next_trsfm.copy()

    elif num_masks == 1:
        cur_frame = mask[0]
        cur_trsfm = transforms[cur_frame]

        for frame in range(frame_count):
            transforms[frame] = cur_trsfm.copy()

    elif num_masks < 1:
        raise ValueError("Missing initial keyframe")






class UncompressedTransform:
    def __init__(
            self,
            arm_data:  ArmatureData,
            anim_data: PXDAnimData
    ):
        self.arm_data = arm_data
        self.anim_data = anim_data

        names = arm_data.bone_names
        frame_count = anim_data.frame_count
        self.key_masks  = {name:KeyMaskContainer() for name in names}
        self.transforms = {name:TransformContainer(frame_count) for name in names}

        self.read_stream()
        self.lerp_transforms()

    def read_stream(self):
        stream = self.anim_data.stream
        frame_count  = self.anim_data.frame_count
        track_count  = self.anim_data.track_count
        table_offset = self.anim_data.main_offset

        for track in range(track_count):
            stream.seek(table_offset + 0x48 * track)
            name = self.arm_data.bone_names[track]

            loc_count        = int.from_bytes(stream.read(8), byteorder='little')
            loc_frame_offset = int.from_bytes(stream.read(8), byteorder='little') + BINA_OFFSET
            loc_data_offset  = int.from_bytes(stream.read(8), byteorder='little') + BINA_OFFSET

            rot_count        = int.from_bytes(stream.read(8), byteorder='little')
            rot_frame_offset = int.from_bytes(stream.read(8), byteorder='little') + BINA_OFFSET
            rot_data_offset  = int.from_bytes(stream.read(8), byteorder='little') + BINA_OFFSET

            scl_count        = int.from_bytes(stream.read(8), byteorder='little')
            scl_frame_offset = int.from_bytes(stream.read(8), byteorder='little') + BINA_OFFSET
            scl_data_offset  = int.from_bytes(stream.read(8), byteorder='little') + BINA_OFFSET

            for i in range(loc_count):
                stream.seek(loc_frame_offset + 0x2 * i)
                tmp_frame = int.from_bytes(stream.read(2), byteorder='little')
                stream.seek(loc_data_offset + 0x10 * i)
                tmp_loc = unpack('<fff', stream.read(0xC))
                self.key_masks[name].loc.append(tmp_frame)
                self.transforms[name].loc[tmp_frame] = Vector(tmp_loc)

            for i in range(rot_count):
                stream.seek(rot_frame_offset + 0x2 * i)
                tmp_frame = int.from_bytes(stream.read(2), byteorder='little')
                stream.seek(rot_data_offset + 0x10 * i)
                tmp_rot = unpack('<ffff', stream.read(0x10))
                self.key_masks[name].rot.append(tmp_frame)
                self.transforms[name].rot[tmp_frame] = Quaternion(tmp_rot)

            for i in range(scl_count):
                stream.seek(scl_frame_offset + 0x2 * i)
                tmp_frame = int.from_bytes(stream.read(2), byteorder='little')
                stream.seek(scl_data_offset + 0x10 * i)
                tmp_scl = unpack('<fff', stream.read(0xC))
                self.key_masks[name].scl.append(tmp_frame)
                self.transforms[name].scl[tmp_frame] = Vector(tmp_scl)

    def lerp_transforms(self):
        """
        Create inbetween values of local transforms
        Needed for building an accurate world-space matrix, even if no keyframes will be inserted
        """
        track_count = self.arm_data.bone_count
        bone_names  = self.arm_data.bone_names

        for track in range(track_count):
            name = bone_names[track]
            key_mask  = self.key_masks[name]
            transform = self.transforms[name]
            frame_count = self.anim_data.frame_count

            lerp_process(sorted(key_mask.loc), transform.loc, frame_count)
            lerp_process(sorted(key_mask.rot), transform.rot, frame_count)
            lerp_process(sorted(key_mask.scl), transform.scl, frame_count)

    def check_transforms(self):
        """
        Checks if transforms are populated
        :return: True if all are populated, else False
        """
        frame_count = self.anim_data.frame_count
        for name in self.arm_data.bone_names:
            transform = self.transforms[name]
            for i, t in enumerate(chain(transform.loc, transform.rot, transform.scl)):
                if t is None:
                    if i > (2 * frame_count):
                        print(f"{name}, Scale, {i % frame_count}")
                    elif i > frame_count:
                        print(f"{name}, Rotation, {i % frame_count}")
                    else:
                        print(f"{name}, Location, {i}")

                    return False
        return True

    def make_matrix_map(self, frame):
        matrix_map_local = {}
        scale_map = {}

        bone_names = self.arm_data.bone_names
        for name in bone_names:
            transform = self.transforms[name]
            loc = transform.loc[frame]
            rot = transform.rot[frame]
            scl = transform.scl[frame]

            matrix = Matrix.LocRotScale(loc, rot, None)
            matrix_map_local[name] = matrix
            scale_map[name] = scl

        matrix_map_global = get_matrix_map_global(self.arm_data, matrix_map_local, scale_map)
        matrix_map_basis = get_matrix_map_basis(self.arm_data, matrix_map_global)

        return matrix_map_basis


    def make_key_map(self):
        pass
