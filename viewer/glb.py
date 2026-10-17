"""GLB (binary glTF 2.0) container reader.

Kept intentionally small and dependency-free (numpy only): the JSON tree,
the BIN chunk, accessor decoding (tight or interleaved layouts) and embedded
image extraction. Everything the T-Rex viewer needs, nothing else.
"""

from __future__ import annotations

import json
import struct
from pathlib import Path

import numpy as np

GLB_MAGIC = 0x46546C67
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

_COMPONENT_DTYPE = {
    5120: np.int8,
    5121: np.uint8,
    5122: np.int16,
    5123: np.uint16,
    5125: np.uint32,
    5126: np.float32,
}

_TYPE_WIDTH = {
    'SCALAR': 1, 'VEC2': 2, 'VEC3': 3, 'VEC4': 4,
    'MAT2': 4, 'MAT3': 9, 'MAT4': 16,
}


class GlbError(Exception):
    """Raised when a file is not a readable GLB."""


class Glb:
    """A parsed GLB file: ``.gltf`` (JSON tree) and ``.binary`` (BIN chunk)."""

    def __init__(self, path):
        self.path = Path(path)
        raw = self.path.read_bytes()
        if len(raw) < 12:
            raise GlbError('file too small to be a GLB')
        magic, version, length = struct.unpack_from('<III', raw, 0)
        if magic != GLB_MAGIC:
            raise GlbError('bad GLB magic (not a binary glTF file)')
        if version != 2:
            raise GlbError(f'unsupported GLB container version {version}')
        offset = 12
        json_chunk = None
        bin_chunk = b''
        while offset < min(length, len(raw)):
            chunk_length, chunk_type = struct.unpack_from('<II', raw, offset)
            data = raw[offset + 8:offset + 8 + chunk_length]
            if chunk_type == CHUNK_JSON:
                json_chunk = data
            elif chunk_type == CHUNK_BIN:
                bin_chunk = data
            offset += 8 + chunk_length
        if json_chunk is None:
            raise GlbError('GLB has no JSON chunk')
        self.gltf = json.loads(json_chunk)
        self.binary = bin_chunk

    def accessor(self, index):
        """Decode accessor ``index`` into a numpy array (natural dtype)."""
        accessor = self.gltf['accessors'][index]
        view = self.gltf['bufferViews'][accessor['bufferView']]
        dtype = np.dtype(_COMPONENT_DTYPE[accessor['componentType']])
        width = _TYPE_WIDTH[accessor['type']]
        count = accessor['count']
        item_bytes = dtype.itemsize * width
        stride = view.get('byteStride') or item_bytes
        start = view.get('byteOffset', 0) + accessor.get('byteOffset', 0)
        if stride == item_bytes:
            flat = np.frombuffer(self.binary, dtype=dtype,
                                 count=count * width, offset=start)
            array = flat.reshape(count, width).copy()
        else:  # interleaved layout
            array = np.zeros((count, width), dtype=dtype)
            for i in range(count):
                array[i] = np.frombuffer(self.binary, dtype=dtype, count=width,
                                         offset=start + i * stride)
        return array

    def image_bytes(self, index):
        """Extract an embedded image as raw file bytes (PNG)."""
        image = self.gltf['images'][index]
        if 'bufferView' not in image:
            raise GlbError(f'image {index} is not embedded in the GLB')
        view = self.gltf['bufferViews'][image['bufferView']]
        start = view.get('byteOffset', 0)
        return bytes(self.binary[start:start + view['byteLength']])
