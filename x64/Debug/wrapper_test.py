import ctypes
import pathlib
import io
import struct


class Compressor:
    class BufferAndSize(ctypes.Structure):
        _fields_ = [("data", ctypes.POINTER(ctypes.c_ubyte)),
                    ("size", ctypes.c_size_t)]

    path = f"{pathlib.Path.cwd()}\\"
    name = "FrontiersAnimDecompress.dll"

    def __init__(self):
        self.dll = ctypes.CDLL(f"{self.path}\\{self.name}")
        self.dll.decompress.restype = self.BufferAndSize
        self.dll.compress.restype = self.BufferAndSize


def compress(uncompressed_buffer):
    comp = Compressor()
    compressed_buffer_ptr = comp.dll.compress(uncompressed_buffer)
    compressed_stream = bytes(compressed_buffer_ptr.data[:compressed_buffer_ptr.size])
    compressed_buffer = io.BytesIO(compressed_stream)
    return compressed_buffer


folder = f"{pathlib.Path.cwd()}\\"
filename = "TestOld.outanim"

with open(folder + filename, "rb") as file:
    buffer = file.read()

bytes_obj = compress(buffer)

magic = bytes_obj.read(4)
version = bytes_obj.read(4)
file_size = int.from_bytes(bytes_obj.read(4), byteorder='little')
print("NEW")
print(magic)
print(version)
print(file_size)
