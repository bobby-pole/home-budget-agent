"""
backend/app/core/encryption.py

Symmetric authenticated encryption service for sensitive credentials at rest
(e.g., OAuth refresh tokens for store connections).

Specification & Security Notes:
- Cryptographic primitive: Fernet (cryptography.fernet).
- Specification: Fernet is an authenticated symmetric encryption design built upon:
  * AES-128 in CBC mode with PKCS7 padding for confidentiality.
  * HMAC with SHA-256 for message integrity and authenticity.
  * 32-byte key composed of 16-byte signing key and 16-byte encryption key (URL-safe base64).
  * Note: Fernet is explicitly AES-128-CBC + HMAC-SHA256, NOT AES-256.
- Master Key Sourcing:
  * Keys are loaded EXCLUSIVELY from environment variables.
  * Supported env vars:
    1) TOKEN_ENCRYPTION_KEY: Single Fernet key string (assigned default key ID 'v1').
    2) CONNECTION_ENCRYPTION_KEYS: JSON object mapping key IDs to Fernet keys,
       e.g. '{"v1": "...", "v2": "..."}' or comma-separated pairs 'v2:key2,v1:key1'.
    3) TOKEN_PRIMARY_KEY_ID: Designates the active key ID used for encrypting new data.
- Fail-Closed Behavior:
  * If no encryption keys are configured or if keys are malformed, encryption and
    decryption fail closed by raising EncryptionKeyError.
  * Plaintext tokens are NEVER stored in plaintext or logged.
- Key Rotation Support:
  * Allows registering multiple keys with distinct key IDs.
  * Decryption tries the specified key ID first, then falls back across configured keys.
  * 'reencrypt_if_needed' detects if a ciphertext was encrypted with an older key ID
    and re-encrypts it under the primary active key ID.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class EncryptionError(Exception):
    """Base exception for cryptographic operations."""


class EncryptionKeyError(EncryptionError):
    """Raised when encryption keys are missing, invalid, or unconfigured (fail-closed)."""


class DecryptionError(EncryptionError):
    """Raised when a ciphertext cannot be decrypted or authenticated with any known key."""


class TokenEncryptionService:
    """Manages authenticated encryption, decryption, and key rotation for tokens at rest."""

    def __init__(
        self,
        keys: Optional[dict[str, str]] = None,
        primary_key_id: Optional[str] = None,
    ) -> None:
        """
        Initialize with explicit keys or load from environment variables.

        :param keys: Optional mapping of key_id -> base64_fernet_key.
        :param primary_key_id: Key ID to use for all new encryptions.
        """
        self._keys: dict[str, Fernet] = {}
        self._key_strings: dict[str, str] = {}
        self._primary_key_id: Optional[str] = None

        if keys is not None:
            self._load_from_dict(keys, primary_key_id)
        else:
            self._load_from_env()

    def _load_from_dict(self, keys: dict[str, str], primary_key_id: Optional[str] = None) -> None:
        for kid, key_str in keys.items():
            kid_clean = str(kid).strip()
            key_clean = key_str.strip()
            if not kid_clean or not key_clean:
                continue
            try:
                # Validates 32-byte urlsafe base64 Fernet key
                fernet = Fernet(key_clean.encode("utf-8"))
                self._keys[kid_clean] = fernet
                self._key_strings[kid_clean] = key_clean
            except Exception as exc:
                raise EncryptionKeyError(f"Invalid cryptographic key format for key ID '{kid_clean}'") from exc

        if not self._keys:
            return

        if primary_key_id:
            if primary_key_id not in self._keys:
                raise EncryptionKeyError(
                    "Configured TOKEN_PRIMARY_KEY_ID does not exist in the available key set"
                )
            self._primary_key_id = primary_key_id
            return

        # Without an explicit primary ID, choose the highest version identifier.
        sorted_keys = sorted(self._keys.keys(), reverse=True)
        self._primary_key_id = sorted_keys[0]

    def _load_from_env(self) -> None:
        raw_multi = os.getenv("CONNECTION_ENCRYPTION_KEYS", "").strip()
        raw_single = os.getenv("TOKEN_ENCRYPTION_KEY", "").strip()
        env_primary_id = os.getenv("TOKEN_PRIMARY_KEY_ID", "").strip() or None

        keys_dict: dict[str, str] = {}

        if raw_multi:
            # Try parsing as JSON first
            if raw_multi.startswith("{"):
                try:
                    parsed = json.loads(raw_multi)
                    if isinstance(parsed, dict):
                        keys_dict = {str(k): str(v) for k, v in parsed.items()}
                except json.JSONDecodeError as exc:
                    raise EncryptionKeyError("CONNECTION_ENCRYPTION_KEYS is not valid JSON") from exc
            else:
                # Parse comma-separated key_id:key pairs
                for pair in raw_multi.split(","):
                    pair = pair.strip()
                    if not pair:
                        continue
                    if ":" not in pair:
                        raise EncryptionKeyError(
                            "Invalid CONNECTION_ENCRYPTION_KEYS format. Expected 'key_id:key_value' pairs"
                        )
                    k_id, k_val = pair.split(":", 1)
                    keys_dict[k_id.strip()] = k_val.strip()

        elif raw_single:
            keys_dict["v1"] = raw_single
            if not env_primary_id:
                env_primary_id = "v1"

        if keys_dict:
            self._load_from_dict(keys_dict, env_primary_id)

    @property
    def is_configured(self) -> bool:
        """Return True if at least one valid key is available."""
        return bool(self._keys and self._primary_key_id)

    @property
    def primary_key_id(self) -> str:
        if not self._primary_key_id:
            raise EncryptionKeyError("Token encryption master key is not configured (fail-closed)")
        return self._primary_key_id

    def encrypt(self, plaintext: str) -> tuple[str, str]:
        """
        Encrypt plaintext string using the active primary key.

        Returns:
            tuple of (ciphertext_str, key_id).

        Raises:
            EncryptionKeyError: If encryption keys are not configured (fail-closed).
        """
        if not self.is_configured or not self._primary_key_id:
            raise EncryptionKeyError("Token encryption master key is not configured (fail-closed)")

        if not isinstance(plaintext, str):
            raise TypeError("Plaintext must be a string")

        active_fernet = self._keys[self._primary_key_id]
        token_bytes = active_fernet.encrypt(plaintext.encode("utf-8"))
        return token_bytes.decode("utf-8"), self._primary_key_id

    def decrypt(self, ciphertext: str, key_id: Optional[str] = None) -> str:
        """
        Decrypt and authenticate ciphertext using the specified key_id,
        falling back to MultiFernet rotation across all configured keys.

        Returns:
            Decrypted plaintext string.

        Raises:
            EncryptionKeyError: If keys are not configured.
            DecryptionError: If ciphertext is corrupt, tampered, or cannot be decrypted.
        """
        if not self.is_configured:
            raise EncryptionKeyError("Token encryption master key is not configured (fail-closed)")

        if not ciphertext or not isinstance(ciphertext, str):
            raise DecryptionError("Ciphertext cannot be empty or non-string")

        ciphertext_bytes = ciphertext.strip().encode("utf-8")

        # 1. Try specified key first if provided and known
        if key_id and key_id in self._keys:
            try:
                decrypted = self._keys[key_id].decrypt(ciphertext_bytes)
                return decrypted.decode("utf-8")
            except (InvalidToken, ValueError):
                pass  # Fall through to multi-key rotation attempt

        # 2. Try all available keys starting with primary key
        ordered_fernets: list[Fernet] = []
        if self._primary_key_id and self._primary_key_id in self._keys:
            ordered_fernets.append(self._keys[self._primary_key_id])
        for kid, fernet in self._keys.items():
            if kid != self._primary_key_id:
                ordered_fernets.append(fernet)

        multi_fernet = MultiFernet(ordered_fernets)
        try:
            decrypted = multi_fernet.decrypt(ciphertext_bytes)
            return decrypted.decode("utf-8")
        except InvalidToken as exc:
            raise DecryptionError("Failed to decrypt token: authentication failed or unknown key") from exc

    def reencrypt_if_needed(self, ciphertext: str, current_key_id: Optional[str]) -> tuple[str, str, bool]:
        """
        Verify if the ciphertext was encrypted under the current primary key.
        If encrypted under an older key ID, decrypt and re-encrypt under the primary key.

        Returns:
            (ciphertext, key_id, did_reencrypt: bool)
        """
        if not self.is_configured or not self._primary_key_id:
            raise EncryptionKeyError("Token encryption master key is not configured (fail-closed)")

        if current_key_id == self._primary_key_id:
            return ciphertext, self._primary_key_id, False

        # Decrypt with previous key / fallback
        plaintext = self.decrypt(ciphertext, key_id=current_key_id)
        new_ciphertext, new_key_id = self.encrypt(plaintext)
        return new_ciphertext, new_key_id, True


_default_service: Optional[TokenEncryptionService] = None


def get_encryption_service(reload_env: bool = False) -> TokenEncryptionService:
    """Return the application-wide TokenEncryptionService singleton."""
    global _default_service
    if _default_service is None or reload_env:
        _default_service = TokenEncryptionService()
    return _default_service
