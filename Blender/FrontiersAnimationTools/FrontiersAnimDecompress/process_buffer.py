import bpy
import io
import ctypes


class Compressor:
    class BufferAndSize(ctypes.Structure):
        _fields_ = [("data", ctypes.POINTER(ctypes.c_ubyte)),
                    ("size", ctypes.c_size_t)]

    path = bpy.utils.user_resource('SCRIPTS', path='Addons\\FrontiersAnimationTools\\FrontiersAnimDecompress')
    name = "FrontiersAnimDecompress.dll"

    def __init__(self):
        self.dll = ctypes.CDLL(f"{self.path}\\{self.name}")
        self.dll.decompress.restype = self.BufferAndSize
        self.dll.compress.restype = self.BufferAndSize


def decompress(compressed_buffer):
    comp = Compressor()
    if len(compressed_buffer):
        decompressed_buffer_ptr = comp.dll.decompress(compressed_buffer)
        decompressed_stream = bytes(decompressed_buffer_ptr.data[:decompressed_buffer_ptr.size])
        decompressed_buffer = io.BytesIO(decompressed_stream)
        return decompressed_buffer
    else:
        return io.BytesIO()


def compress(uncompressed_buffer):
    comp = Compressor()
    if len(uncompressed_buffer):
        compressed_buffer_ptr = comp.dll.compress(uncompressed_buffer)
        compressed_stream = bytes(compressed_buffer_ptr.data[:compressed_buffer_ptr.size])
        compressed_buffer = io.BytesIO(compressed_stream)
        return compressed_buffer
    else:
        return io.BytesIO()
