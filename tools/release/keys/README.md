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
