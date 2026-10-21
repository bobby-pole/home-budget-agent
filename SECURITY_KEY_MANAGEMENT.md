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
* **Plaintext Invariant**: Plaintext tokens are **never** persisted to SQLite, exposed in API request or response payloads, printed to application logs, or passed to browser code. The public lifecycle API creates only credential-free authorization placeholders.

---

## 2. Required Environment Variables

Master encryption keys must be sourced **exclusively from environment variables** on the server. **Never commit key values to Git, Dockerfiles, or unencrypted backup artifacts.**

| Variable Name | Required | Description |
|---|---|---|
| `TOKEN_ENCRYPTION_KEY` | Optional (if single-key mode) | URL-safe base64-encoded 32-byte Fernet key used as default active key `v1`. |
| `CONNECTION_ENCRYPTION_KEYS` | Optional (if multi-key rotation mode) | JSON dictionary mapping key identifiers to keys, e.g. `{"v1":"...", "v2":"..."}` or comma-separated pairs `v2:key2,v1:key1`. |
| `TOKEN_PRIMARY_KEY_ID` | Optional | Specifies the active key identifier used for all new encryption operations (e.g. `v2`). If set, it must name a configured key or the service fails closed. |

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
* **Connection State**: If a worker cannot load a key, the connection transitions to `reauth_required` with `ENCRYPTION_KEY_MISSING`; if ciphertext authentication fails, it uses `TOKEN_DECRYPTION_FAILED`. Ciphertexts are retained for a possible key restore but are never retried as active credentials.
* **Zero Plaintext in Dumps**: SQLite database dumps contain only ciphertext strings and `encryption_key_id` metadata. Plaintext tokens never appear in `.sql` dumps or raw file backups.

---

## 5. Disconnect & Revocation Procedure

When a user initiates a disconnect action via the UI or `POST /api/connections/{id}/disconnect`:
1. **Atomic Local Erasure**: The stored `encrypted_refresh_token` and `encryption_key_id` columns are set to `NULL` within an atomic database transaction.
2. **Status Transition**: The connection status transitions to `disconnected`.
3. **Revocation Neutrality**:
   * A future adapter may invoke an official, authorized provider revocation endpoint. #258 does not implement such an adapter and therefore never claims remote revocation.
   * If remote provider revocation is unavailable (Phase 1 Web MVP), the system explicitly records `last_error_code="PROVIDER_REVOCATION_UNAVAILABLE"` and returns `revocation_status="provider_revocation_unavailable"`.
   * The UI and API **never** falsely claim that tokens were revoked on third-party merchant servers when no such revocation occurred.

---

## 6. Prohibition of Secrets in Backups, Logs, Git, and Browser Storage

The following strict prohibitions apply to all contributors and automated agents:
1. **No Secrets in Logs**: Never log request bodies, response payloads, authorization codes, refresh tokens, access tokens, or full exception stack traces containing user PII.
2. **No Secrets in Git**: Master keys, test keys, and real user credentials are strictly forbidden from Git commits and tracked files.
3. **No Secrets in Browser Storage or Requests**: Client-side tokens for external store merchants must never be passed to browser code, stored in `localStorage`, `sessionStorage`, or IndexedDB, or accepted by public lifecycle request bodies.
4. **No Plaintext in DB**: All external credentials in database tables must be encrypted prior to persistence.

---

## 7. Architecture Boundary: Phase 1 Web MVP vs. Future Phase 2 Local-First

* **Phase 1 Web MVP (Current)**:
  * Server-side envelope encryption at rest via environment master keys.
  * Centralized privacy-first handling with normalized domain models (`CanonicalReceipt`, `CanonicalItem`).
  * Manual and on-demand trigger mechanisms.
  * The public web lifecycle starts in `reauth_required`; only a future approved server-side adapter callback may call the internal authorization-completion boundary.
* **Phase 2 Local-First / Mobile (Future)**:
  * Secure credential storage moved to user device hardware enclaves (iOS Keychain, Android KeyStore / SecureStore).
  * Direct device-to-merchant communication without intermediate server-side token retention.
  * End-to-end encrypted synchronization with the user's private household database.


## 8. Local Lidl research session

The CLI reads explicitly configured keys from the environment or the root `.env`.
It never supplies a default encryption key. `scratch/lidl_poc_session.json` contains
only a version, key identifier and Fernet ciphertext; tokens and the optional
connection binding are encrypted together. Writes use an atomic replacement with
0600 permissions. `migrate-session` encrypts a legacy plaintext file in place,
without contacting Lidl or changing application connections. Keep the encryption
key when restoring the session; losing it requires another login.

A research login without a target does not modify the application database.
To bind a login to one application connection, provide all three positive IDs:

```sh
backend/.venv/bin/python scripts/poc_lidl_auth.py login \
  --connection-id <connection-id> --budget-id <budget-id> --user-id <user-id>
```

The script checks membership, owner and provider before authorization and again
before storing credentials. Refresh retains this encrypted binding and updates
only that connection. A response without a replacement refresh token retains
the previous token. No command assigns credentials to every Lidl connection.

The local key-rotation rollback artifact in `data/backups/*.sql.encrypted.json`
contains an encrypted SQL dump: decrypt `ciphertext` with the key named by `key_id`
to recover SQL for a separate restore database. It is not a plaintext SQLite file.
