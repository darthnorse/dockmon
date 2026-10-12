"""Passphrase-encrypted, chunked, authenticated backup file format.

Layout: a fixed header followed by AES-256-GCM chunks. The whole header is the
associated data of every chunk, so any header change fails authentication. The
nonce is an 8-byte random prefix plus a 32-bit big-endian chunk counter whose high
bit marks the final chunk; reordering, truncating or extending the stream
therefore fails too.
"""

import os
import struct
from dataclasses import dataclass
from typing import BinaryIO

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from backup.errors import BackupDecryptError, BackupFormatError

MAGIC = b"DMBAK"
FORMAT_VERSION = 1
HEADER_FORMAT = ">5sBBBB16s8sI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024
FINAL_FLAG = 0x80000000
MIN_PASSPHRASE_LENGTH = 8

# Bounds on header-supplied KDF parameters: a hostile file must not make us
# allocate much memory before the first authentication check.
MIN_N_LOG2, MAX_N_LOG2 = 10, 20
MAX_R, MAX_P = 16, 4
MAX_KDF_MEMORY = 256 * 1024 * 1024


@dataclass(frozen=True)
class KdfParams:
    n_log2: int = 17
    r: int = 8
    p: int = 1


DEFAULT_KDF = KdfParams()


def check_kdf(kdf: KdfParams) -> None:
    in_bounds = MIN_N_LOG2 <= kdf.n_log2 <= MAX_N_LOG2 and 1 <= kdf.r <= MAX_R and 1 <= kdf.p <= MAX_P
    if not in_bounds or 128 * kdf.r * 2**kdf.n_log2 > MAX_KDF_MEMORY:
        raise BackupFormatError("Backup uses unsupported key-derivation parameters")


def _derive_key(passphrase: str, salt: bytes, kdf: KdfParams) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**kdf.n_log2, r=kdf.r, p=kdf.p).derive(
        passphrase.encode("utf-8")
    )


def _nonce(prefix: bytes, counter: int, final: bool) -> bytes:
    if counter >= FINAL_FLAG:
        raise BackupFormatError("Backup exceeds the maximum number of chunks")
    return prefix + struct.pack(">I", counter | (FINAL_FLAG if final else 0))


def _read_exact(src: BinaryIO, size: int) -> bytes:
    parts = []
    remaining = size
    while remaining:
        block = src.read(remaining)
        if not block:
            break
        parts.append(block)
        remaining -= len(block)
    return b"".join(parts)


def encrypt_stream(
    src: BinaryIO,
    dst: BinaryIO,
    passphrase: str,
    kdf: KdfParams = DEFAULT_KDF,
    chunk_size: int = CHUNK_SIZE,
) -> None:
    if len(passphrase) < MIN_PASSPHRASE_LENGTH:
        raise ValueError(f"Passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters")
    if not 0 < chunk_size <= MAX_CHUNK_SIZE:
        raise ValueError("Invalid chunk size")
    check_kdf(kdf)

    salt = os.urandom(16)
    prefix = os.urandom(8)
    header = struct.pack(
        HEADER_FORMAT, MAGIC, FORMAT_VERSION, kdf.n_log2, kdf.r, kdf.p, salt, prefix, chunk_size
    )
    aead = AESGCM(_derive_key(passphrase, salt, kdf))
    dst.write(header)

    counter = 0
    current = _read_exact(src, chunk_size)
    while True:
        following = _read_exact(src, chunk_size)
        final = not following
        dst.write(aead.encrypt(_nonce(prefix, counter, final), current, header))
        if final:
            return
        current = following
        counter += 1


def decrypt_stream(src: BinaryIO, dst: BinaryIO, passphrase: str) -> None:
    """Decrypt into dst chunk by chunk.

    Verified plaintext is written as it is authenticated, so on any exception
    dst holds a partial stream and must be discarded by the caller.
    """
    header = _read_exact(src, HEADER_SIZE)
    if len(header) != HEADER_SIZE:
        raise BackupFormatError("Not a DockMon backup file")
    magic, version, n_log2, r, p, salt, prefix, chunk_size = struct.unpack(HEADER_FORMAT, header)
    if magic != MAGIC:
        raise BackupFormatError("Not a DockMon backup file")
    if version != FORMAT_VERSION:
        raise BackupFormatError(f"Unsupported backup format version {version}")
    kdf = KdfParams(n_log2, r, p)
    check_kdf(kdf)
    if not 0 < chunk_size <= MAX_CHUNK_SIZE:
        raise BackupFormatError("Backup uses an unsupported chunk size")

    aead = AESGCM(_derive_key(passphrase, salt, kdf))
    block_size = chunk_size + TAG_SIZE

    counter = 0
    current = _read_exact(src, block_size)
    while True:
        if len(current) < TAG_SIZE:
            raise BackupDecryptError("Backup file is truncated")
        following = _read_exact(src, block_size)
        final = not following
        if not final and len(current) != block_size:
            raise BackupDecryptError("Backup file is corrupted")
        try:
            dst.write(aead.decrypt(_nonce(prefix, counter, final), current, header))
        except InvalidTag:
            if counter == 0:
                raise BackupDecryptError("Wrong passphrase, or the backup file is corrupted") from None
            raise BackupDecryptError("Backup file is corrupted or truncated") from None
        if final:
            return
        current = following
        counter += 1
