import bpy
import math
from mathutils import Quaternion


# Constants
SINE_RMS = 1 / math.sqrt(2)

ROOT_OBJ_ROTATE_IN = Quaternion((SINE_RMS, SINE_RMS, 0.0, 0.0))
ROOT_BONE_ROTATE_IN = Quaternion((0.5, -0.5, -0.5, -0.5))

BINA_OFFSET = 0x40


def is_version_at_least(major, minor) -> bool:
    if bpy.app.version[0] > major:
        return True
    elif bpy.app.version[0] == major and bpy.app.version[1] >= minor:
        return True
    return False


def read_zero_term_string(file) -> str:
    temp_bytes = []
    while True:
        b = file.read(1)
        if b is None or b[0] == 0:
            return bytes(temp_bytes).decode('utf-8')
        else:
            temp_bytes.append(b[0])


def hex_string(num: int) -> str:
    return str(hex(num)[:2] + hex(num)[2:].upper())


def align_bytes(stream, align_to: int, write=True):
    buffer_loc = stream.tell()
    if (align_to > 0) and (buffer_loc % align_to):
        pad = align_to - buffer_loc % align_to
        if write is True:
            stream.write((0).to_bytes(pad))
        else:
            stream.read(pad)
