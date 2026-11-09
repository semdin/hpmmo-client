# Vendored dependency provenance

Pinned third-party sources for the release pipeline C++ launcher updater. Every file is
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
parsing and streaming DEFLATE decompression are implemented in-tree
(`src/zip.cpp`, `src/inflate.cpp`); release chunks are inflated with the
vendored libdeflate (section below).

## stb (Linux/macOS launcher UI, 2026-10-19)

| file | bytes | sha256 |
| --- | --- | --- |
| vendor/stb/stb_image.h | 283010 | 594c2fe35d49488b4382dbfaec8f98366defca819d916ac95becf3e75f4200b3 |
| vendor/stb/stb_image_write.h | 71221 | cbd5f0ad7a9cf4468affb36354a1d2338034f2c12473cf1a8e32053cb6914a05 |
| vendor/stb/stb_truetype.h | 199192 | ecd30b05e0dd4fea3a13c26810dd9e1992dc379049482c393d5a19e6b5090aab |

Source:
- nothings/stb, commit `a7d4c2175630e1ea5b6f8dd00ab96fed0b97b96d` (fetched 2026-10-19 from
  https://github.com/nothings/stb) - public domain / MIT dual license (the
  license text is at the end of each header). Used only by the SDL launcher UI:
  JPEG decode of the background, TrueType rasterisation, PNG screenshots.

## libdeflate (chunk inflate, 2026-11-09)

| file | bytes | sha256 |
| --- | --- | --- |
| vendor/libdeflate/COPYING | 1078 | 4ad69099cb4374836fd27583d9991e2838cd86b6e4666ab26b2d32582c91e73a |
| vendor/libdeflate/common_defs.h | 21815 | 0702970eb23da9bca3be9f31fe71824b2f88c4fbac55c59cee8d42cdaec63b63 |
| vendor/libdeflate/lib/arm/cpu_features.c | 6562 | c75efd51385cb7f5aa729d95a8f5b3888920fd3fc7e198554f69d1e0dad2f62c |
| vendor/libdeflate/lib/arm/cpu_features.h | 7107 | 0cff5c0110021dc8b18511e328f913f1bad21f31ad927497d1f428db4e6ed239 |
| vendor/libdeflate/lib/cpu_features_common.h | 2788 | f4eb0800558e9116dd14446ccfb9b1896f970aec6de42c18366a29bde73fd0da |
| vendor/libdeflate/lib/decompress_template.h | 25048 | ade3034c1d5c840cb31bd9738a015be804862a8dfce03c14ac2f5b3a826792b8 |
| vendor/libdeflate/lib/deflate_constants.h | 1747 | 72ea6e5f0abe53e781203e3f383603a765a768b860a09b3356be36bfd87c8af3 |
| vendor/libdeflate/lib/deflate_decompress.c | 49297 | bc16ab65325ce4ac14af830b2cf6c805770beab01fd2f09226dca3dfa3f8bb47 |
| vendor/libdeflate/lib/lib_common.h | 3624 | e7aa1f2750434e1019ffabda577dab0fdf5b95f010f6f20aa7e21323b3bcceea |
| vendor/libdeflate/lib/utils.c | 3425 | 3d4c9f6d488610d4d9ff314b2dc783e24079325b78af13d3ee37b18fcc0b0d8a |
| vendor/libdeflate/lib/x86/cpu_features.c | 6371 | 9ed976e4c66478e8b6a8856424816147a971f75894c66f03274ab8119074dde0 |
| vendor/libdeflate/lib/x86/cpu_features.h | 5696 | 7bfbea8cd8e801209771f2190f27bbd3d4e386ce13dd8401a2c276e5bccd1593 |
| vendor/libdeflate/lib/x86/decompress_impl.h | 2190 | 81ab9fd7d4723fdc7ae81dca82f817bcecb7baf5bdfffde0ccfbba70569ac2f1 |
| vendor/libdeflate/libdeflate.h | 17098 | 957cda6906c2be6c8978cf19779f1aad9dd121af1147a10e184b137db353678d |

Source:
- ebiggers/libdeflate, release v1.24 (https://github.com/ebiggers/libdeflate/archive/refs/tags/v1.24.tar.gz,
  tarball sha256 ad8d3723d0065c4723ab738be9723f2ff1cb0f1571e8bfcf0301ff9661f475e8, fetched
  2026-11-09) - MIT license (vendor/libdeflate/COPYING). Decompression only:
  `lib/deflate_decompress.c`, `lib/utils.c` and the x86/arm CPU feature probes with
  their headers; the compressors, gzip/zlib wrappers and checksums are not vendored.
  Used by `src/delta.cpp` to inflate downloaded release chunks straight into their
  known-size buffer (measured 719 MB/s against 117 MB/s for `src/inflate.cpp`, which
  still serves the streaming ZIP path).
