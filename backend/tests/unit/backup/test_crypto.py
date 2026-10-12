import io
import struct

import pytest

from backup.crypto import (
    HEADER_SIZE,
    KdfParams,
    decrypt_stream,
    encrypt_stream,
)
from backup.errors import BackupDecryptError, BackupFormatError

PASSPHRASE = "correct horse battery staple"
FAST_KDF = KdfParams(n_log2=10, r=8, p=1)
CHUNK = 64
BLOCK = CHUNK + 16


def _encrypt(data: bytes, passphrase: str = PASSPHRASE, chunk_size: int = CHUNK) -> bytes:
    out = io.BytesIO()
    encrypt_stream(io.BytesIO(data), out, passphrase, kdf=FAST_KDF, chunk_size=chunk_size)
    return out.getvalue()


def _decrypt(blob: bytes, passphrase: str = PASSPHRASE) -> bytes:
    out = io.BytesIO()
    decrypt_stream(io.BytesIO(blob), out, passphrase)
    return out.getvalue()


@pytest.mark.parametrize("size", [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK, 3 * CHUNK + 5])
def test_round_trip(size):
    data = bytes(range(256)) * (size // 256 + 1)
    data = data[:size]
    assert _decrypt(_encrypt(data)) == data


def test_ciphertext_is_not_plaintext():
    data = b"registry-secret" * 20
    assert b"registry-secret" not in _encrypt(data)


def test_wrong_passphrase_rejected():
    with pytest.raises(BackupDecryptError):
        _decrypt(_encrypt(b"hello" * 50), passphrase="wrong passphrase!")


def test_short_passphrase_rejected_on_encrypt():
    with pytest.raises(ValueError):
        _encrypt(b"data", passphrase="short")


@pytest.mark.parametrize("position", range(HEADER_SIZE))
def test_any_header_byte_flip_rejected(position):
    blob = bytearray(_encrypt(b"x" * (2 * CHUNK)))
    blob[position] ^= 0x01
    with pytest.raises(BackupDecryptError):
        _decrypt(bytes(blob))


@pytest.mark.parametrize("offset", [0, BLOCK // 2, BLOCK - 1, BLOCK + 3, 2 * BLOCK + 1])
def test_body_byte_flip_rejected(offset):
    blob = bytearray(_encrypt(b"y" * (2 * CHUNK + 10)))
    blob[HEADER_SIZE + offset] ^= 0x80
    with pytest.raises(BackupDecryptError):
        _decrypt(bytes(blob))


def test_truncation_at_chunk_boundary_rejected():
    blob = _encrypt(b"z" * (3 * CHUNK))
    with pytest.raises(BackupDecryptError):
        _decrypt(blob[: HEADER_SIZE + 2 * BLOCK])


def test_truncation_mid_chunk_rejected():
    blob = _encrypt(b"z" * (3 * CHUNK))
    with pytest.raises(BackupDecryptError):
        _decrypt(blob[:-5])


def test_header_only_rejected():
    blob = _encrypt(b"z" * CHUNK)
    with pytest.raises(BackupDecryptError):
        _decrypt(blob[:HEADER_SIZE])


def test_appended_chunk_rejected():
    blob = _encrypt(b"q" * (2 * CHUNK + 1))
    first_chunk = blob[HEADER_SIZE : HEADER_SIZE + BLOCK]
    with pytest.raises(BackupDecryptError):
        _decrypt(blob + first_chunk)


def test_reordered_chunks_rejected():
    blob = _encrypt(bytes(range(200)) * 2)
    header, body = blob[:HEADER_SIZE], blob[HEADER_SIZE:]
    chunks = [body[i : i + BLOCK] for i in range(0, len(body), BLOCK)]
    chunks[0], chunks[1] = chunks[1], chunks[0]
    with pytest.raises(BackupDecryptError):
        _decrypt(header + b"".join(chunks))


def test_not_a_backup_rejected_as_format_error():
    with pytest.raises(BackupFormatError):
        _decrypt(b"PK\x03\x04 this is a zip file, not a backup" * 3)


def test_hostile_kdf_parameters_rejected_before_deriving():
    blob = bytearray(_encrypt(b"data"))
    blob[6] = 40  # n_log2: 2^40 scrypt would exhaust memory
    with pytest.raises(BackupFormatError):
        _decrypt(bytes(blob))


def test_hostile_chunk_size_rejected():
    blob = bytearray(_encrypt(b"data"))
    struct.pack_into(">I", blob, HEADER_SIZE - 4, 0xFFFFFFFF)
    with pytest.raises(BackupFormatError):
        _decrypt(bytes(blob))


def test_individually_valid_kdf_fields_over_memory_budget_rejected():
    blob = bytearray(_encrypt(b"data"))
    blob[6] = 18  # n_log2 within bounds...
    blob[7] = 16  # ...r within bounds, but 128 * 16 * 2^18 = 512 MiB of scrypt memory
    with pytest.raises(BackupFormatError):
        _decrypt(bytes(blob))


def test_encrypt_refuses_kdf_parameters_decrypt_would_reject():
    with pytest.raises(BackupFormatError):
        encrypt_stream(io.BytesIO(b"x"), io.BytesIO(), PASSPHRASE, kdf=KdfParams(n_log2=9, r=8, p=1))
