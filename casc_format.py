"""CASC v1/v2/v3 reader for ComfyUI."""
from __future__ import annotations

import ctypes
import hashlib
import os
import struct
import zlib
from dataclasses import dataclass, field
from pathlib import Path


class CascError(RuntimeError):
    pass


class CascFormatError(CascError):
    pass


class CascIntegrityError(CascError):
    pass


@dataclass
class CascAsset:
    type: str
    slot: str
    file_name: str
    data: bytes
    sha256: bytes
    source_path: str = ""

    @property
    def sha256_hex(self) -> str:
        return self.sha256.hex()


@dataclass
class CascIdentity:
    name: str
    description: str
    tones: list[str] = field(default_factory=list)
    setting_images: dict[str, CascAsset] = field(default_factory=dict)
    general_images: list[CascAsset] = field(default_factory=list)
    detail_images: list[CascAsset] = field(default_factory=list)
    ref_audio: list[CascAsset] = field(default_factory=list)
    ref_video: list[CascAsset] = field(default_factory=list)
    private_lora: list[CascAsset] = field(default_factory=list)


@dataclass
class CascCharacter:
    name: str
    description: str
    author: str
    version: str
    license: str
    identities: list[CascIdentity]


SETTING_IMAGE_SLOTS = (
    "Portrait", "Front", "Left", "Right", "Rear", "Top", "Bottom",
    "LeftFronthalf", "RightFronthalf", "LeftRearHalf", "RightRearHalf",
)


def _u32(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 4 > len(data):
        raise CascFormatError("unexpected end of file while reading uint32")
    return struct.unpack_from(">I", data, offset)[0], offset + 4


def _i64(data: bytes, offset: int) -> tuple[int, int]:
    if offset + 8 > len(data):
        raise CascFormatError("unexpected end of file while reading int64")
    return struct.unpack_from(">q", data, offset)[0], offset + 8


class _QtReader:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def qstring(self) -> str:
        length, self.offset = _u32(self.data, self.offset)
        if length == 0xFFFFFFFF:
            return ""
        if length % 2 or self.offset + length > len(self.data):
            raise CascFormatError("invalid QString length")
        value = self.data[self.offset:self.offset + length].decode("utf-16-be")
        self.offset += length
        return value

    def qstring_list(self) -> list[str]:
        count, self.offset = _u32(self.data, self.offset)
        if count > 1_000_000:
            raise CascFormatError("QStringList is too large")
        return [self.qstring() for _ in range(count)]

    def qbytearray(self) -> bytes:
        length, self.offset = _u32(self.data, self.offset)
        if length == 0xFFFFFFFF:
            return b""
        if self.offset + length > len(self.data):
            raise CascFormatError("invalid QByteArray length")
        value = self.data[self.offset:self.offset + length]
        self.offset += length
        return value

    def asset(self, has_hash: bool) -> CascAsset:
        asset_type = self.qstring()
        slot = self.qstring()
        file_name = self.qstring()
        stored_hash = self.qbytearray() if has_hash else b""
        content = self.qbytearray()
        calculated_hash = hashlib.sha256(content).digest()
        if has_hash and stored_hash != calculated_hash:
            raise CascIntegrityError(f"SHA-256 mismatch: {file_name}")
        return CascAsset(asset_type, slot, file_name, content, calculated_hash)


def _qt_uncompress(data: bytes) -> bytes:
    if len(data) < 4:
        raise CascFormatError("compressed payload is too short")
    try:
        return zlib.decompress(data[4:])
    except zlib.error as exc:
        raise CascFormatError(f"Qt Deflate decompression failed: {exc}") from exc


def _lz4_block_decompress(data: bytes, expected_size: int) -> bytes:
    output = bytearray()
    cursor = 0
    while cursor < len(data):
        token = data[cursor]
        cursor += 1
        literal_length = token >> 4
        if literal_length == 15:
            while True:
                if cursor >= len(data):
                    raise CascFormatError("invalid LZ4 literal length")
                extra = data[cursor]
                cursor += 1
                literal_length += extra
                if extra != 255:
                    break
        if cursor + literal_length > len(data):
            raise CascFormatError("invalid LZ4 literal data")
        output.extend(data[cursor:cursor + literal_length])
        cursor += literal_length
        if cursor >= len(data):
            break
        if cursor + 2 > len(data):
            raise CascFormatError("invalid LZ4 match offset")
        match_offset = data[cursor] | (data[cursor + 1] << 8)
        cursor += 2
        if match_offset == 0 or match_offset > len(output):
            raise CascFormatError("invalid LZ4 match offset")
        match_length = token & 0x0F
        if match_length == 15:
            while True:
                if cursor >= len(data):
                    raise CascFormatError("invalid LZ4 match length")
                extra = data[cursor]
                cursor += 1
                match_length += extra
                if extra != 255:
                    break
        match_length += 4
        for _ in range(match_length):
            output.append(output[-match_offset])
    if expected_size >= 0 and len(output) != expected_size:
        raise CascFormatError(f"LZ4 size mismatch: expected {expected_size}, got {len(output)}")
    return bytes(output)


def _zstd_decompress(data: bytes, expected_size: int) -> bytes:
    try:
        import zstandard  # type: ignore
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=expected_size)
    except ImportError:
        pass
    candidates = [
        Path(__file__).with_name("native") / "libzstd.dll",
        Path(__file__).parents[1] / "zstd-v1.5.7-win64" / "dll" / "libzstd.dll",
    ]
    library = None
    for candidate in candidates:
        if candidate.exists():
            try:
                library = ctypes.CDLL(str(candidate))
                break
            except OSError:
                continue
    if library is None:
        raise CascFormatError("Zstandard support requires zstandard or libzstd.dll")
    library.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
    library.ZSTD_decompress.restype = ctypes.c_size_t
    library.ZSTD_isError.argtypes = [ctypes.c_size_t]
    library.ZSTD_isError.restype = ctypes.c_uint
    output = ctypes.create_string_buffer(expected_size)
    source = ctypes.create_string_buffer(data)
    size = library.ZSTD_decompress(output, expected_size, source, len(data))
    if library.ZSTD_isError(size):
        raise CascFormatError("Zstandard decompression failed")
    return output.raw[:size]


def _decompress(data: bytes, compression: int, expected_size: int) -> bytes:
    if compression == 0:
        result = data
    elif compression == 1:
        result = _qt_uncompress(data)
    elif compression == 2:
        try:
            result = _qt_uncompress(data)
        except CascError:
            result = _lz4_block_decompress(data, expected_size)
    elif compression == 3:
        result = _zstd_decompress(data, expected_size)
    else:
        raise CascFormatError(f"unknown compression mode: {compression}")
    if expected_size >= 0 and len(result) != expected_size:
        raise CascFormatError(f"payload size mismatch: expected {expected_size}, got {len(result)}")
    return result


def _read_identity(reader: _QtReader, version: int) -> CascIdentity:
    identity = CascIdentity(reader.qstring(), reader.qstring(), reader.qstring_list())
    if version >= 2:
        image_count, reader.offset = _u32(reader.data, reader.offset)
        if image_count > len(SETTING_IMAGE_SLOTS):
            raise CascFormatError("too many settingImage entries")
        for _ in range(image_count):
            key = reader.qstring()
            identity.setting_images[key] = reader.asset(version >= 3)
    if version >= 3:
        groups = (identity.general_images, identity.detail_images, identity.ref_audio, identity.ref_video, identity.private_lora)
        for group in groups:
            count, reader.offset = _u32(reader.data, reader.offset)
            if count > 100_000:
                raise CascFormatError("too many assets")
            for _ in range(count):
                group.append(reader.asset(True))
    else:
        count, reader.offset = _u32(reader.data, reader.offset)
        if count > 100_000:
            raise CascFormatError("too many legacy assets")
        for _ in range(count):
            asset = reader.asset(False)
            if asset.type == "通用参考图": identity.general_images.append(asset)
            elif asset.type == "细节参考图": identity.detail_images.append(asset)
            elif asset.type == "音频": identity.ref_audio.append(asset)
            elif asset.type == "视频": identity.ref_video.append(asset)
            elif asset.type == "Lora": identity.private_lora.append(asset)
    return identity


def load_casc(path: str | os.PathLike[str], password: str = "") -> CascCharacter:
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise CascFormatError(f"CASC file not found: {file_path}")
    data = file_path.read_bytes()
    if len(data) < 4 or data[:4] != b"CASC":
        raise CascFormatError("not a CASC file")
    offset = 4
    if offset + 2 > len(data):
        raise CascFormatError("missing CASC version")
    version = struct.unpack_from(">H", data, offset)[0]
    offset += 2
    if version not in (1, 2, 3):
        raise CascFormatError(f"unsupported CASC version: {version}")
    if offset + 2 > len(data):
        raise CascFormatError("missing CASC flags")
    compression = data[offset]
    encrypted = data[offset + 1]
    offset += 2
    original_size, offset = _i64(data, offset)
    packed_length, offset = _u32(data, offset)
    if offset + packed_length > len(data):
        raise CascFormatError("packed payload exceeds file size")
    packed = data[offset:offset + packed_length]
    if encrypted:
        if not password:
            raise CascIntegrityError("CASC password is required")
        packed = _aes_decrypt(packed, password)
    raw = _decompress(packed, compression, original_size)
    reader = _QtReader(raw)
    character = CascCharacter(reader.qstring(), reader.qstring(), reader.qstring(), reader.qstring(), reader.qstring(), [])
    identity_count, reader.offset = _u32(raw, reader.offset)
    if identity_count > 1000:
        raise CascFormatError("too many identities")
    character.identities = [_read_identity(reader, version) for _ in range(identity_count)]
    for identity in character.identities:
        for asset in identity.setting_images.values(): asset.source_path = str(file_path)
        for group in (identity.general_images, identity.detail_images, identity.ref_audio, identity.ref_video, identity.private_lora):
            for asset in group: asset.source_path = str(file_path)
    return character


def _gf_mul(a: int, b: int) -> int:
    result = 0
    for _ in range(8):
        if b & 1:
            result ^= a
        high = a & 0x80
        a = (a << 1) & 0xFF
        if high:
            a ^= 0x1B
        b >>= 1
    return result


def _gf_pow(value: int, exponent: int) -> int:
    result = 1
    while exponent:
        if exponent & 1:
            result = _gf_mul(result, value)
        value = _gf_mul(value, value)
        exponent >>= 1
    return result


def _rotl8(value: int, shift: int) -> int:
    return ((value << shift) | (value >> (8 - shift))) & 0xFF


def _make_sboxes() -> tuple[bytes, bytes]:
    sbox = []
    inverse = [0] * 256
    for value in range(256):
        inverse_value = 0 if value == 0 else _gf_pow(value, 254)
        substituted = inverse_value ^ _rotl8(inverse_value, 1) ^ _rotl8(inverse_value, 2) ^ _rotl8(inverse_value, 3) ^ _rotl8(inverse_value, 4) ^ 0x63
        sbox.append(substituted)
        inverse[substituted] = value
    return bytes(sbox), bytes(inverse)


_SBOX, _INV_SBOX = _make_sboxes()


class _AES256:
    def __init__(self, key: bytes):
        if len(key) != 32:
            raise ValueError("AES-256 requires a 32-byte key")
        self.round_keys = self._expand_key(key)

    @staticmethod
    def _expand_key(key: bytes) -> list[bytes]:
        words = [list(key[index:index + 4]) for index in range(0, 32, 4)]
        rcon = 1
        while len(words) < 60:
            temp = words[-1][:]
            if len(words) % 8 == 0:
                temp = temp[1:] + temp[:1]
                temp = [_SBOX[item] for item in temp]
                temp[0] ^= rcon
                rcon = _gf_mul(rcon, 2)
            elif len(words) % 8 == 4:
                temp = [_SBOX[item] for item in temp]
            words.append([left ^ right for left, right in zip(words[-8], temp)])
        return [bytes(sum(words[index:index + 4], [])) for index in range(0, 60, 4)]

    @staticmethod
    def _add_round_key(state: list[int], key: bytes) -> None:
        for index, value in enumerate(key):
            state[index] ^= value

    @staticmethod
    def _inv_shift_rows(state: list[int]) -> None:
        original = state[:]
        for row in range(4):
            for column in range(4):
                state[4 * column + row] = original[4 * ((column - row) % 4) + row]

    @staticmethod
    def _inv_sub_bytes(state: list[int]) -> None:
        for index, value in enumerate(state):
            state[index] = _INV_SBOX[value]

    @staticmethod
    def _inv_mix_columns(state: list[int]) -> None:
        for column in range(4):
            offset = column * 4
            a0, a1, a2, a3 = state[offset:offset + 4]
            state[offset] = _gf_mul(a0, 14) ^ _gf_mul(a1, 11) ^ _gf_mul(a2, 13) ^ _gf_mul(a3, 9)
            state[offset + 1] = _gf_mul(a0, 9) ^ _gf_mul(a1, 14) ^ _gf_mul(a2, 11) ^ _gf_mul(a3, 13)
            state[offset + 2] = _gf_mul(a0, 13) ^ _gf_mul(a1, 9) ^ _gf_mul(a2, 14) ^ _gf_mul(a3, 11)
            state[offset + 3] = _gf_mul(a0, 11) ^ _gf_mul(a1, 13) ^ _gf_mul(a2, 9) ^ _gf_mul(a3, 14)

    def decrypt_block(self, block: bytes) -> bytes:
        if len(block) != 16:
            raise ValueError("AES block must be 16 bytes")
        state = list(block)
        self._add_round_key(state, self.round_keys[14])
        for round_index in range(13, 0, -1):
            self._inv_shift_rows(state)
            self._inv_sub_bytes(state)
            self._add_round_key(state, self.round_keys[round_index])
            self._inv_mix_columns(state)
        self._inv_shift_rows(state)
        self._inv_sub_bytes(state)
        self._add_round_key(state, self.round_keys[0])
        return bytes(state)

    def cbc_decrypt(self, data: bytes, iv: bytes) -> bytes:
        if len(iv) != 16 or len(data) % 16:
            raise ValueError("invalid AES-CBC input")
        output = bytearray()
        previous = iv
        for offset in range(0, len(data), 16):
            encrypted = data[offset:offset + 16]
            decrypted = self.decrypt_block(encrypted)
            output.extend(left ^ right for left, right in zip(decrypted, previous))
            previous = encrypted
        return bytes(output)


def _aes_decrypt(data: bytes, password: str) -> bytes:
    key = hashlib.sha256(password.encode("utf-8")).digest()
    if not data or len(data) % 16:
        raise CascFormatError("AES payload length is invalid")
    plain = _AES256(key).cbc_decrypt(data, b"\x00" * 16)
    padding = plain[-1]
    if padding < 1 or padding > 16 or plain[-padding:] != bytes([padding]) * padding:
        raise CascIntegrityError("AES password is incorrect or payload is damaged")
    return plain[:-padding]