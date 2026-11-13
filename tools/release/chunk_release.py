#!/usr/bin/env python3
"""Content-defined chunking for HPMMO client releases (delta updates).

Splits every file of an exported client build into content-defined chunks
(~256 KiB on average). A chunk's identity is its SHA-256, so the chunks of an
unchanged region are the same bytes in every release, wherever they move.

For a release it writes:
  content.json         every file of this version as a list of chunks, and where
                       each chunk can be downloaded:
                       [sha256, length, source index, offset, compressed length]
  chunks-<ver>.bin     only the chunks no release inside the source window
                       already published, each raw-DEFLATE compressed,
                       concatenated

`content.json` is listed (url + sha256 + size) in the signed manifest, so the
launcher trusts every chunk hash in it. The launcher builds the new version
from the chunks it already has on disk (the installed version's content.json)
plus HTTP Range requests for the missing ones - an update downloads only what
changed, never the whole package.

Source window (release_common.CHUNK_SOURCE_WINDOW, --source-window): a chunk
is referenced in an earlier release's bin only when that release is one of
the last N versions; a chunk whose source is older is packed again into this
release's chunks-<ver>.bin. The chain of releases a new install depends on is
therefore bounded: only the releases inside the window must be kept.

Usage:
  chunk_release.py --build-dir build/client --version 1.0.5 \\
      --download-base https://github.com/OWNER/REPO/releases/download/v1.0.5 \\
      [--previous content.json-of-the-previous-release] [--source-window 30] --out dist
"""

import argparse
import hashlib
import json
import mmap
import os
import struct
import sys
import zlib

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_common as rc  # noqa: E402

FORMAT = rc.CONTENT_INDEX_FORMAT
MIN_CHUNK = 64 * 1024
MAX_CHUNK = 1024 * 1024
MASK = (1 << 18) - 1          # cut probability 2^-18 -> ~256 KiB average
WINDOW = 18                   # only the last 18 bytes reach the masked bits


def _gear():
    table = []
    for i in range(256):
        table.append(struct.unpack("<Q", hashlib.sha256(b"hpmmo-gear-%d" % i).digest()[:8])[0])
    return np.array(table, dtype=np.uint64) & np.uint64(MASK)


GEAR = _gear()


BLOCK = 16 * 1024 * 1024      # bytes hashed at a time (~0.5 GB of buffers)


def _cut_candidates(arr: np.ndarray) -> np.ndarray:
    """Positions whose rolling gear hash has its masked bits clear.

    Hashed in BLOCK-sized slices with WINDOW - 1 bytes of overlap: the hash at
    byte i depends only on bytes i-WINDOW+1..i, so the result is identical to
    hashing the whole file at once - which cost ~24 bytes of RAM per byte of
    input and pushed a 600+ MB .pck past the release runner's memory."""
    n = len(arr)
    out = []
    for start in range(0, n, BLOCK):
        lead = min(start, WINDOW - 1)
        part = arr[start - lead: min(start + BLOCK, n)]
        gv = GEAR[part]
        m = len(part)
        h = np.zeros(m, dtype=np.uint64)
        for k in range(min(WINDOW, m)):
            h[k:] += gv[: m - k] << np.uint64(k)
        hits = np.nonzero((h[lead:] & np.uint64(MASK)) == 0)[0]
        out.append(hits + start)
    return np.concatenate(out) if out else np.zeros(0, dtype=np.int64)


def chunk_boundaries(data: bytes) -> list[tuple[int, int]]:
    """(offset, length) of every chunk. A cut follows byte i when the gear hash
    of the WINDOW bytes ending at i has its low 18 bits clear, at least
    MIN_CHUNK after the previous cut; MAX_CHUNK forces a cut."""
    n = len(data)
    if n == 0:
        return []
    candidates = _cut_candidates(np.frombuffer(data, dtype=np.uint8))
    out = []
    pos = 0
    while pos < n:
        lo = pos + MIN_CHUNK
        hi = min(pos + MAX_CHUNK, n)
        if hi - pos <= MIN_CHUNK:
            out.append((pos, hi - pos))
            break
        j = int(np.searchsorted(candidates, lo - 1))
        cut = int(candidates[j]) + 1 if j < len(candidates) and candidates[j] < hi else hi
        out.append((pos, cut - pos))
        pos = cut
    return out


def deflate_raw(data: bytes) -> bytes:
    c = zlib.compressobj(6, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def build(build_dir: str, version: str, download_base: str, previous: dict | None, out_dir: str,
          platform: str = rc.LEGACY_PLATFORM, window: int = rc.CHUNK_SOURCE_WINDOW) -> dict:
    known = {}   # sha256 -> (source url, offset, clen)
    aged = set()  # chunks whose published copy is older than the window
    if previous:
        sources = previous.get("sources", [])
        # The previous index carries its own references forward, so without
        # this filter a chunk kept pointing at the release that first
        # published it, however old (see release_common.CHUNK_SOURCE_WINDOW).
        usable = [rc.chunk_source_in_window(url, version, window) for url in sources]
        for f in previous.get("files", []):
            for digest, _length, src, offset, clen in f["chunks"]:
                if usable[src]:
                    known.setdefault(digest, (sources[src], offset, clen))
                else:
                    aged.add(digest)
        dropped = sorted({url.rsplit("/", 1)[-1] for url, ok in zip(sources, usable) if not ok})
        if dropped:
            print("[chunks] outside the %d-version source window, re-packed: %s" % (window, ", ".join(dropped)))

    bin_name = rc.chunks_bin_name(version, platform)
    bin_url = download_base.rstrip("/") + "/" + bin_name
    sources: list[str] = []
    source_ids: dict[str, int] = {}

    def source_id(url: str) -> int:
        if url not in source_ids:
            source_ids[url] = len(sources)
            sources.append(url)
        return source_ids[url]

    os.makedirs(out_dir, exist_ok=True)
    bin_path = os.path.join(out_dir, bin_name)
    written = {}
    files = []
    new_bytes = 0
    repacked_bytes = 0
    with open(bin_path, "wb") as blob:
        for root, _dirs, names in os.walk(build_dir):
            for name in names:
                full = os.path.join(root, name)
                rel = os.path.relpath(full, build_dir).replace(os.sep, "/")
                # Memory-mapped, not read: the three platforms are chunked in
                # parallel under the runner's 5 GB cap, and a 1 GB .pck held as
                # bytes per process does not fit beside the hashing buffers.
                with open(full, "rb") as handle:
                    size = os.fstat(handle.fileno()).st_size
                    data = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) if size else b""
                    try:
                        entry = {"path": rel, "size": size, "sha256": hashlib.sha256(data).hexdigest(), "chunks": []}
                        for offset, length in chunk_boundaries(data):
                            piece = data[offset:offset + length]
                            digest = hashlib.sha256(piece).hexdigest()
                            if digest in written:
                                url, off, clen = written[digest]
                            elif digest in known:
                                url, off, clen = known[digest]
                            else:
                                packed = deflate_raw(piece)
                                off = blob.tell()
                                blob.write(packed)
                                url, clen = bin_url, len(packed)
                                written[digest] = (url, off, clen)
                                new_bytes += clen
                                if digest in aged:
                                    repacked_bytes += clen
                            entry["chunks"].append([digest, length, source_id(url), off, clen])
                    finally:
                        if size:
                            data.close()
                files.append(entry)
    files.sort(key=lambda f: f["path"])
    if not written:
        os.remove(bin_path)
    doc = {"format": FORMAT, "client_version": version,
           "chunking": {"min": MIN_CHUNK, "mask_bits": 18, "max": MAX_CHUNK},
           "sources": sources, "files": files}
    with open(os.path.join(out_dir, rc.content_index_name(platform)), "w", encoding="utf-8", newline="\n") as handle:
        json.dump(doc, handle, separators=(",", ":"))
    total = sum(f["size"] for f in files)
    print("[chunks] %d files, %.1f MB; new chunks %d (%.1f MB compressed, %.1f MB of it re-packed) -> %s"
          % (len(files), total / 1e6, len(written), new_bytes / 1e6, repacked_bytes / 1e6,
             bin_name if written else "none"))
    print("[chunks] sources: %s" % ", ".join(url.rsplit("/", 1)[-1] for url in sources))
    return doc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--build-dir", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--download-base", required=True, help="URL the new chunks-<ver>.bin will live under")
    parser.add_argument("--previous", default="", help="content.json of the previous release (optional)")
    parser.add_argument("--out", default="dist")
    parser.add_argument("--platform", default=rc.LEGACY_PLATFORM,
                        help="names the outputs: content[-<platform>].json, chunks[-<platform>]-<ver>.bin")
    parser.add_argument("--source-window", type=int, default=rc.CHUNK_SOURCE_WINDOW,
                        help="reference chunks only in the bins of the last N versions, counting this one; "
                             "older ones are re-packed (default %(default)s, see release_common.py)")
    args = parser.parse_args(argv)
    rc.validate_platform(args.platform)
    try:
        rc.validate_version(args.version)
    except ValueError as exc:
        parser.error(str(exc))
    if args.source_window < 1:
        parser.error("--source-window must be at least 1")
    previous = None
    if args.previous and os.path.isfile(args.previous):
        with open(args.previous, encoding="utf-8") as handle:
            previous = json.load(handle)
        if previous.get("format") != FORMAT:
            print("[chunks] previous content.json has another format; starting fresh")
            previous = None
    build(args.build_dir, args.version, args.download_base, previous, args.out, args.platform, args.source_window)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
