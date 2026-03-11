"""
Shared Argon2id password hasher instance.

All modules that need password hashing should import `ph` from here
to avoid duplicate PasswordHasher instances with potentially different configs.
"""

from argon2 import PasswordHasher

ph = PasswordHasher(
    time_cost=2,        # Number of iterations
    memory_cost=65536,  # 64 MB memory
    parallelism=1,      # Number of threads
    hash_len=32,        # Hash length in bytes
    salt_len=16,        # Salt length in bytes
)
