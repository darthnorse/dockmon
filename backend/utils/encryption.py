"""
Encryption utilities for sensitive data storage.

Uses Fernet symmetric encryption to protect passwords and sensitive data.
The encryption key is stored in /app/data/encryption.key and auto-generated
on first use.

Security Note:
    This protects against database dumps/exports, but does NOT protect against
    full container compromise. If an attacker gains access to both the database
    AND the encryption key, they can decrypt the data.
"""

import os
import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

# Path to encryption key file
KEY_PATH = '/app/data/encryption.key'


def _get_or_create_key() -> bytes:
    """
    Load existing encryption key or generate a new one.

    The key is stored in /app/data/encryption.key. If the file doesn't exist,
    a new key is generated and saved.

    Returns:
        bytes: Fernet encryption key

    Raises:
        IOError: If key file cannot be read or created
    """
    if os.path.exists(KEY_PATH):
        try:
            with open(KEY_PATH, 'rb') as f:
                key = f.read()
                logger.debug(f"Loaded encryption key from {KEY_PATH}")
                return key
        except Exception as e:
            logger.error(f"Failed to read encryption key from {KEY_PATH}: {e}")
            raise IOError(f"Cannot read encryption key: {e}")

    # Generate new key
    try:
        key = Fernet.generate_key()

        # Ensure directory exists
        os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)

        # Write key with restrictive permissions
        with open(KEY_PATH, 'wb') as f:
            f.write(key)

        # Set file permissions to 600 (owner read/write only)
        os.chmod(KEY_PATH, 0o600)

        logger.info(f"Generated new encryption key at {KEY_PATH}")
        return key

    except Exception as e:
        logger.error(f"Failed to generate or save encryption key: {e}")
        raise IOError(f"Cannot create encryption key: {e}")


def encrypt_password(plaintext: str) -> str:
    """
    Encrypt a password for secure storage.

    Args:
        plaintext: Plain text password to encrypt

    Returns:
        str: Base64-encoded encrypted password

    Raises:
        ValueError: If plaintext is empty
        IOError: If encryption key cannot be loaded
    """
    if not plaintext:
        raise ValueError("Cannot encrypt empty password")

    try:
        key = _get_or_create_key()
        fernet = Fernet(key)
        encrypted_bytes = fernet.encrypt(plaintext.encode('utf-8'))
        encrypted_str = encrypted_bytes.decode('ascii')

        logger.debug("Password encrypted successfully")
        return encrypted_str

    except ValueError:
        raise
    except Exception as e:
        logger.error(f"Password encryption failed: {e}")
        raise IOError(f"Encryption failed: {e}")


def decrypt_password(encrypted: str) -> str:
    """
    Decrypt a password from storage.

    Args:
        encrypted: Base64-encoded encrypted password

    Returns:
        str: Decrypted plain text password

    Raises:
        ValueError: If encrypted string is invalid or cannot be decrypted
        IOError: If encryption key cannot be loaded
    """
    if not encrypted:
        raise ValueError("Cannot decrypt empty string")

    try:
        key = _get_or_create_key()
        fernet = Fernet(key)
        decrypted_bytes = fernet.decrypt(encrypted.encode('ascii'))
        plaintext = decrypted_bytes.decode('utf-8')

        logger.debug("Password decrypted successfully")
        return plaintext

    except InvalidToken:
        logger.error("Failed to decrypt password: invalid token (key mismatch or corrupted data)")
        raise ValueError("Cannot decrypt password: invalid encryption token")
    except Exception as e:
        logger.error(f"Password decryption failed: {e}")
        raise IOError(f"Decryption failed: {e}")


def test_encryption() -> bool:
    """
    Test encryption/decryption functionality.

    Useful for verifying the encryption key is working correctly.

    Returns:
        bool: True if encryption/decryption works, False otherwise
    """
    try:
        test_password = "test_password_12345"
        encrypted = encrypt_password(test_password)
        decrypted = decrypt_password(encrypted)

        if decrypted == test_password:
            logger.info("Encryption test passed")
            return True
        else:
            logger.error("Encryption test failed: decrypted value doesn't match")
            return False

    except Exception as e:
        logger.error(f"Encryption test failed: {e}")
        return False
