# Vendored dependency provenance

Pinned third-party sources for the Phase 7 C++ launcher updater. Every file is
copied byte-for-byte from the upstream revision and hash-pinned here.

| file | bytes | sha256 |
| --- | --- | --- |
| vendor/ed25519/LICENSE | 874 | f68d76b9c1c2271422e55134ea94cf71f2ac3fc3ed6a7ec6b83a1a0538753214 |
| vendor/ed25519/ed25519.h | 1251 | 8b09800605ac592c1f7d6e701f3526f84156db15bbd68904d39ad398e7d7c8ce |
| vendor/ed25519/fe.c | 38843 | 71082937da43def6ecaf7811c23410bd8ea763969dfec67383f8129b12b1926d |
| vendor/ed25519/fe.h | 980 | 0476ae2ebb86978d1e0b9fbeb63dcddd7566d6b74806db47dda7688df74aaafb |
| vendor/ed25519/ge.c | 10373 | c3bb834817edea83d843828a75af19867b93144d15140eadfd9784d40cf11409 |
| vendor/ed25519/ge.h | 1683 | b16be2ea1731d9212933e7beeaef6882145fdcdaebdff9996efb5cf97faa2651 |
| vendor/ed25519/sc.c | 22867 | c1bdb840416b34e79ceb7472d1a4ac4b1407c47b4c982cad981c72142ef42407 |
| vendor/ed25519/sc.h | 267 | b0ef537b4d4dad7bd2910e2a663a02a7ac25b473511a929c3c609d82f9bdf87d |
| vendor/ed25519/sha512.c | 11088 | b34128b950036777c299943d624bd830a234a65932c394fdf455e4948258fb6d |
| vendor/ed25519/sha512.h | 489 | 647ed5784d4dcd682b9c42add2e39107582efb4df9e1362c8e5120613eb9a0ce |
| vendor/ed25519/fixedint.h | 2518 | 451fd529865e7fc69156f4cbe7c548857704ae4913768ad9ed7103656efdfc17 |
| vendor/ed25519/precomp_data.h | 97800 | c7d63a8b7ecd7bc6a3ac2b826a540a69dee0fc7e8bf3b00ef5dd98ce00a7c224 |
| vendor/ed25519/verify.c | 1367 | a2ca7197c5f6d193c9f526d432429dfb44a65853a7ec18e10a5761334bdcf48c |

Source:
- orlp/ed25519, commit `b1f19fab4aebe607805620d25a5e42566ce46a0e` (master,
  fetched 2026-10-04 from https://github.com/orlp/ed25519) - zlib-style
  permissive license (see vendor/ed25519/LICENSE; the upstream `license.txt` is
  kept verbatim as `LICENSE`). Public-key signature verification only:
  `verify.c` plus its `fe`/`ge`/`sc`/`sha512` dependencies. `keypair.c`,
  `sign.c`, `seed.c`, `add_scalar.c`, `key_exchange.c` and `test.c` are
  deliberately not vendored; the launcher never signs and therefore never
  needs a private key.

SHA-256 for artifact/manifest/certificate hashing is not vendored: it uses the
Windows CNG API (`bcrypt.dll`, `BCRYPT_SHA256_ALGORITHM`). ZIP container
parsing and DEFLATE decompression are implemented in-tree
(`src/zip.cpp`, `src/inflate.cpp`); Ed25519 is the only vendored third-party
code.
