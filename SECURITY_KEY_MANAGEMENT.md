# Security & Key Management Policy (Issue #258)

This document specifies the cryptographic policy, key management lifecycle, failure modes, and security invariants for external receipt provider connections in **Rachownik**.

---

## 1. Cryptographic Primitive & Specification

Sensitive external tokens at rest (e.g., OAuth refresh tokens for store receipt ingestion) are encrypted using authenticated symmetric encryption via **Fernet** (`cryptography.fernet`).

### Specification Notes:
* **Primitive**: Fernet uses **128-bit AES in CBC mode** with PKCS7 padding for data confidentiality.
* **Authentication**: **HMAC with SHA-256** for message integrity and authenticity verification.
* **Key Derivation & Structure**: 32-byte key (composed of 16-byte signing key and 16-byte encryption key), encoded as URL-safe base64.
* **Standard Clarification**: Fernet is explicitly **AES-128-CBC + HMAC-SHA256**, not AES-256.
* **Plaintext Invariant**: Plaintext tokens are **never** persisted to SQLite, **never** exposed over API response payloads (`has_token: bool` is returned instead), **never** printed to application logs, and **never** stored in browser `localStorage` or session state.

---

## 2. Required Environment Variables

Master encryption keys must be sourced **exclusively from environment variables** on the server. **Never commit key values to Git, Dockerfiles, or unencrypted backup artifacts.**

| Variable Name | Required | Description |
|---|---|---|
| `TOKEN_ENCRYPTION_KEY` | Optional (if single-key mode) | URL-safe base64-encoded 32-byte Fernet key used as default active key `v1`. |
| `CONNECTION_ENCRYPTION_KEYS` | Optional (if multi-key rotation mode) | JSON dictionary mapping key identifiers to keys, e.g. `{"v1":"...", "v2":"..."}` or comma-separated pairs `v2:key2,v1:key1`. |
| `TOKEN_PRIMARY_KEY_ID` | Optional | Specifies the active key identifier used for all new encryption operations (e.g. `v2`). |

> **Security Rule**: Do not place sample secrets or default fallback keys in codebase configuration or `.env.example`.

---

## 3. Key Rotation Procedure

Rachownik supports zero-downtime key rotation without requiring simultaneous mass database rewrites.

### Step-by-Step Rotation:
1. **Generate New Key**: Generate a fresh 32-byte URL-safe base64 key using `cryptography.fernet.Fernet.generate_key()`.
2. **Update Environment**:
   * Add the new key to `CONNECTION_ENCRYPTION_KEYS` with a new key identifier (e.g. `v2`).
   * Retain existing key(s) (e.g. `v1`) in `CONNECTION_ENCRYPTION_KEYS`.
   * Set `TOKEN_PRIMARY_KEY_ID="v2"`.
3. **Restart Application / Worker**: Deploy the updated configuration.
   * **New credentials**: Automatically encrypted with `v2`.
   * **Existing credentials**: Decrypted using `v1` (fallback key lookup or MultiFernet rotation).
4. **Opportunistic Re-encryption**:
   * When any connection record is read or processed by the sync pipeline (`ConnectionService.get_decrypted_token`), the service automatically detects that the ciphertext was encrypted under `v1` and re-encrypts it under active key `v2`.
5. **Retire Old Key**:
   * Once all rows have been migrated or updated, remove `v1` from `CONNECTION_ENCRYPTION_KEYS`.

---

## 4. Restore Behavior on Fresh Server (Fail-Closed)

If a SQLite database backup is restored to a new server without the corresponding master encryption key:
* **Fail-Closed Guarantee**: The encryption service strictly refuses to decrypt corrupted, missing, or mismatched keys, raising `EncryptionKeyError` or `DecryptionError`.
* **Application Integrity**: The application continues to operate for budgeting, manual transactions, and existing cached data.
* **Connection State**: External connections will transition to `reauth_required` or `sync_error` (`ENCRYPTION_KEY_MISSING`). Stored ciphertexts cannot be decrypted by unauthorized parties holding only the database dump.
* **Zero Plaintext in Dumps**: SQLite database dumps contain only ciphertext strings and `encryption_key_id` metadata. Plaintext tokens never appear in `.sql` dumps or raw file backups.

---

## 5. Disconnect & Revocation Procedure

When a user initiates a disconnect action via the UI or `POST /api/connections/{id}/disconnect`:
1. **Atomic Local Erasure**: The stored `encrypted_refresh_token` and `encryption_key_id` columns are set to `NULL` within an atomic database transaction.
2. **Status Transition**: The connection status transitions to `disconnected`.
3. **Revocation Neutrality**:
   * If an external provider supports an official, authorized revocation endpoint, it is invoked via an isolated adapter interface.
   * If remote provider revocation is unavailable (Phase 1 Web MVP), the system explicitly records `last_error_code="PROVIDER_REVOCATION_UNAVAILABLE"` and returns `revocation_status="provider_revocation_unavailable"`.
   * The UI and API **never** falsely claim that tokens were revoked on third-party merchant servers when no such revocation occurred.

---

## 6. Prohibition of Secrets in Backups, Logs, Git, and Browser Storage

The following strict prohibitions apply to all contributors and automated agents:
1. **No Secrets in Logs**: Never log request bodies, response payloads, authorization codes, refresh tokens, access tokens, or full exception stack traces containing user PII.
2. **No Secrets in Git**: Master keys, test keys, and real user credentials are strictly forbidden from Git commits and tracked files.
3. **No Secrets in Browser Storage**: Client-side tokens for external store merchants must never be passed to the browser or stored in `localStorage`, `sessionStorage`, or IndexedDB.
4. **No Plaintext in DB**: All external credentials in database tables must be encrypted prior to persistence.

---

## 7. Architecture Boundary: Phase 1 Web MVP vs. Future Phase 2 Local-First

* **Phase 1 Web MVP (Current)**:
  * Server-side envelope encryption at rest via environment master keys.
  * Centralized privacy-first handling with normalized domain models (`CanonicalReceipt`, `CanonicalItem`).
  * Manual and on-demand trigger mechanisms.
  * Explicit user consent and data scope transparency in UI.
* **Phase 2 Local-First / Mobile (Future)**:
  * Secure credential storage moved to user device hardware enclaves (iOS Keychain, Android KeyStore / SecureStore).
  * Direct device-to-merchant communication without intermediate server-side token retention.
  * End-to-end encrypted synchronization with the user's private household database.
