# Secrets Vault

A light, robust secrets store built into the console (no extra container).

- **Multiple vaults** — create as many named vaults as you need (e.g. `default`,
  `work`), each **independently encrypted, unlocked and sealed**. Manage them all
  from the vault panel's tabs at `localhost:8080`.
- **Project-scoped secrets** — inside a vault, every secret has a **scope**:
  `global` (all projects) or a **project name**. So `work:webapp/DB_URL` is the
  `DB_URL` for project `webapp` in the `work` vault.

## How it's secure (envelope encryption — "one data key, many locks")

- A random 256-bit **Data Encryption Key (DEK)** encrypts every secret value
  (AES-256-GCM). The DEK is **never stored in plaintext** — only held in the
  console process's memory while unlocked.
- The DEK is wrapped independently by multiple **key slots** — *any one* unlocks:
  - **passphrase** — your project master key (Argon2id-hardened)
  - **access codes** — extra unlock codes you add/revoke (one per laptop/teammate)
  - **recovery key** — shown once at setup; the *never-locked-out* guarantee
  - **auto-unseal** — optional machine key file for unattended restarts
- **Sealed** = DEK not in memory, nothing readable. **Unlock** with any credential.
- Storage is the existing Postgres (`vault_*` tables). Verified: values are
  ciphertext at rest, wrong credentials are rejected (401), and the recovery key
  restores access if you forget the passphrase *and* your codes.

## Using it (console)

Open the **🔐 Secrets Vault** panel at the top of the console:

1. **Set up** — enter a project passphrase → **save the one-time recovery key**.
2. **Add secrets** — name, value, scope (local/global).
3. **Reveal / copy / rotate / delete**, add **access codes**, change passphrase,
   toggle **auto-unlock on restart** (off by default = you unlock after each boot).
4. **Lock** re-seals it when you step away.

## Using it from other projects (CLI/API)

`cli/openml-secret` is pure-stdlib — symlink it onto your PATH:

```bash
ln -s "$(pwd)/cli/openml-secret" /usr/local/bin/openml-secret

openml-secret vaults                                          # list vaults
openml-secret set DB_URL postgres://… --vault work --scope webapp
openml-secret get DB_URL             --vault work --scope webapp
openml-secret list                   --vault work --scope webapp
```

`--vault` defaults to `default`, `--scope` to `global`. If the target vault is
sealed, pass an access code (or set `OPENML_VAULT_CODE`):

```bash
openml-secret get OPENAI_API_KEY --vault work --code <access-code>
```

Any project on your machine reads **global** secrets this way — one encrypted
source of truth, no plaintext `.env` scattered around. The API lives at
`http://localhost:8080/api/vault/*` (localhost-bound).

## "What if I forget the passphrase AND lose the recovery key?"

Honest answer: with no valid credential and auto-unlock off, secrets are
**cryptographically unrecoverable** — there is no backdoor (that's the security
guarantee). So the vault gives you layered nets so you never reach that point:

1. **Recovery key** — the built-in net for a forgotten passphrase (shown once at
   setup; store it in your password manager).
2. **Multiple access codes** — add one per device; losing one is harmless.
3. **Auto-unlock (personal mode)** — turn it on and the machine's key file
   unseals the vault automatically; on your own Mac you're effectively never
   locked out. (Trade-off: the key lives on disk.)
4. **Encrypted backup** — *Download encrypted backup* seals all secret values
   under a separate backup password you choose. Keep it offline; it restores on
   any machine even after total DB loss or a forgotten passphrase:
   *set a new passphrase → Restore → paste the backup + its password.* Verified
   end-to-end (reset → new passphrase → restore → secrets back).
5. **Reset (last resort)** — the *Reset the vault* link on the unlock screen
   wipes everything and starts fresh. You lose the stored secrets, but since a
   secrets manager holds *copies*, you can re-add them from their source.

The one thing nothing can recover: a forgotten passphrase **and** a lost
recovery key **and** no access codes **and** no backup **and** auto-unlock off.
Keep the recovery key or a backup and you're safe.

## Notes / trade-offs

- **Localhost trust:** once unlocked, any localhost caller can read (fine for a
  personal machine; the console is bound to `127.0.0.1`).
- **Auto-unseal** stores a key file in the `vault` volume — convenient across
  reboots, but the key lives on disk (secrets are then effectively unencrypted at
  rest to anyone who can read it). Off by default; the console now warns on enable
  and shows a persistent banner while it's on.
- **CSRF/DNS-rebind guard** — the vault API (like all mutating console routes)
  rejects cross-origin browser writes and rebound hostnames, so a malicious page
  you visit can't drive the vault even though it's unauthenticated on localhost.
- Secrets survive restarts (encrypted in Postgres); the vault **re-seals** on
  restart unless auto-unseal is on.
