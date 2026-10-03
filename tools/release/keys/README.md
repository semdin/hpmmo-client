# Release signing keys (HPMMO client updates)

The client release manifest is detached-signed with Ed25519. The launcher
downloads `manifest.json`, verifies its signature against a **pinned public
key**, and only then trusts the artifact hashes inside it. A hash from an
unsigned manifest proves nothing: the signature is what makes the manifest
authoritative.

## Custody rules

1. **The private key never lives in a repository.** It exists only in the
   secret store that feeds the release pipeline (GitHub secret
   `HPMMO_CLIENT_SIGNING_KEY`), plus whatever offline backup the project keeps.
   This directory contains documentation only; it has a `.gitignore` that
   refuses to stage key material. `gen_manifest.py` also refuses to sign with a
   key found inside a git working tree (`--allow-key-in-repo` exists for
   disposable test keys, nothing else).
2. **The public key is pinned in the launcher.** The launcher embeds the
   public key (or its fingerprint) at build time. It never fetches a key over
   the network: an update that could supply its own signing key is not an
   update, it is a remote code execution path.
3. **A key id travels with the signature.** `manifest.json.keyid` records the
   `key_id`, which is the SHA-256 of the key's DER SubjectPublicKeyInfo (SPKI).
   The launcher derives the same value from its pinned key and refuses a
   manifest whose key id does not match. `manifest.json.sig` itself stays
   exactly what the contract promises: one line of base64 holding the raw
   64-byte Ed25519 signature over the manifest bytes.

## Generating a key pair

```sh
openssl genpkey -algorithm ed25519 -out hpmmo-client-release.key.pem
openssl pkey -in hpmmo-client-release.key.pem -pubout -out hpmmo-client-release.pub.pem
# the key id (what travels in manifest.json.keyid):
openssl pkey -in hpmmo-client-release.pub.pem -pubin -outform DER \
  | openssl dgst -sha256
```

The private key file must be `chmod 600`, stored outside every checkout, and
readable only by the release pipeline. Only the `.pub.pem` may be committed or
shipped - and only through a reviewed change that updates the launcher's pin.

## What the pipeline does with it

`.github/workflows/client-release.yml`:

* fails closed at the first step when `HPMMO_CLIENT_SIGNING_KEY` is absent, so
  a manifest can never be published unsigned or signed by an ad-hoc key;
* writes the secret to `$RUNNER_TEMP` with mode 600 (never to the workspace,
  never into the artifact, never into a log);
* signs, then immediately verifies its own output (`gen_manifest.py --verify`)
  before anything is uploaded;
* publishes only through a job behind the `client-release` environment
  approval, and records the derived **public** key next to the published
  manifest so the pin change is visible and auditable.

## Rotation

1. Generate the new pair (above).
2. Ship a launcher release that pins the new public key **and** still accepts
   the old key id during the overlap window.
3. Add the new private key as the environment secret; re-publish the channel
   manifests with the new key (`client-release.yml`, manual dispatch).
4. After the launcher overlap window closes, remove the old key from the
   launcher's pin list and destroy the old private key.

A manifest signed by an unknown key id must be treated as hostile, not as a
prompt to fetch a new key.

## Custody record: the provisioned release key (2026-10-04)

The first real release key exists **only on the deployment host**, generated
there with `openssl genpkey -algorithm ed25519` and never copied off it. No key
material is in this repository, and none of the values below is secret.

| Item | Value |
| --- | --- |
| Private key | `/root/hpmmo-keys/release.key` (mode 600, directory mode 700) |
| Public key (PEM) | `/root/hpmmo-keys/release.pub.pem` (mode 644) |
| Launcher pin `release_public_key` (base64 of the raw 32-byte public key) | `esKd/SD57YU8pPbapFWLGgLpdldYYCE+eqNNG6uKyDI=` |
| Key id `release_public_key_id` = `sha256(DER SPKI)` | `b521bf434e299b1963781ec249a2882068a42d881ef86d8ee31c76f74458399b` |
| TLS release certificate SPKI pin `pinned_spki_sha256` | `703a2267c7b37414632dc23d628eca31df70029581b5d19603f5589902a78fae` |

The three public values are wired into `client/client_config.json`; the same
values are what `deploy/tls/make_cert.sh` and `manifest.json.keyid` print.

### Who holds it

* **Custodian: the project owner** - the only person with root on the
  deployment host (`ssh root@213.250.145.75`). The key file is readable by root
  alone; the host's SSH login is therefore release-signing access.
* A copy for CI (`HPMMO_CLIENT_SIGNING_KEY`, a GitHub Actions secret) is
  **not yet provisioned**. Until it is, releases are signed on the host by an
  operator (that is how the first release was published); `client-release.yml`
  fails closed without the secret, so CI cannot publish an unsigned manifest.
* The private key must never be printed, pasted into a chat, committed, or
  copied into an artifact, a log, or a CI workspace.

### Rotation

1. Generate the new pair **on the host**, outside every working tree:
   `openssl genpkey -algorithm ed25519 -out /root/hpmmo-keys/release-next.key`,
   then derive its pin and key id with the two commands at the top of this
   file.
2. Ship a launcher release that pins the **new** public key **and** still
   accepts the old key id during the overlap window (the launcher refuses a
   manifest whose key id does not match its pin; a manifest cannot introduce
   its own key).
3. Add the new private key as `HPMMO_CLIENT_SIGNING_KEY` (or sign on the host),
   re-publish every channel manifest with the new key, and record the new pin
   in `client/client_config.json` alongside `pinned_spki_sha256` changes.
4. After the overlap window closes, remove the old key from the launcher's pin
   list and destroy the old private key
   (`shred -u /root/hpmmo-keys/release.key` or delete the host volume).

### If the key is lost or suspected compromised

* **Lost, no evidence of use:** rotate as above; the old key can only sign
  manifests nothing trusts once the launcher pin changes. The TLS certificate
  is a *separate* key (see `deploy/tls/make_cert.sh`) and does not rotate with
  it.
* **Compromised:** treat every manifest signed under
  `key_id b521bf434e299b19...` from that moment as hostile. Generate a new
  pair, publish a new launcher that pins only the new key, re-sign the channel
  manifests, and rotate the TLS certificate too if host access - not just the
  key file - was involved (a new certificate means a new
  `pinned_spki_sha256` and a launcher release that carries it).
* A manifest signed by an unknown key id is **never** a reason to fetch a new
  key over the network: it is a hostile manifest to be refused.
