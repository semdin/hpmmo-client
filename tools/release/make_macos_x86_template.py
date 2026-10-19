#!/usr/bin/env python3
"""Builds an x86_64-only macOS export template from Godot's official one.

The official macos.zip only ships universal binaries, and Godot refuses a
universal (or arm64) export unless every texture is also imported as
ETC2/ASTC. The client is exported as x86_64 instead (Intel native, Apple
Silicon through Rosetta 2), from this template: identical to the official
archive, plus godot_macos_{release,debug}.x86_64 thinned out of the universal
binaries with llvm-lipo. Godot re-signs the binary (ad-hoc) at export.

usage: make_macos_x86_template.py <official macos.zip> <output.zip> [--lipo llvm-lipo-18]
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("template")
    parser.add_argument("output")
    parser.add_argument("--lipo", default=shutil.which("llvm-lipo") or shutil.which("llvm-lipo-18") or "llvm-lipo")
    args = parser.parse_args(argv)

    tmp_out = args.output + ".tmp"
    with zipfile.ZipFile(args.template) as src, zipfile.ZipFile(tmp_out, "w", zipfile.ZIP_DEFLATED) as dst, \
            tempfile.TemporaryDirectory() as work:
        thinned = 0
        for info in src.infolist():
            data = src.read(info.filename)
            dst.writestr(info, data)
            base = os.path.basename(info.filename)
            if not base.endswith(".universal"):
                continue
            fat = os.path.join(work, base)
            thin = fat[: -len(".universal")] + ".x86_64"
            with open(fat, "wb") as handle:
                handle.write(data)
            subprocess.run([args.lipo, "-thin", "x86_64", fat, "-output", thin], check=True)
            out = zipfile.ZipInfo(info.filename[: -len(".universal")] + ".x86_64", date_time=info.date_time)
            out.external_attr = (0o755 & 0xFFFF) << 16
            out.compress_type = zipfile.ZIP_DEFLATED
            with open(thin, "rb") as handle:
                dst.writestr(out, handle.read())
            print("thinned %s -> %s (%d bytes)" % (base, os.path.basename(thin), os.path.getsize(thin)))
            thinned += 1
        if thinned == 0:
            print("error: no universal binary in %s" % args.template, file=sys.stderr)
            return 1
    os.replace(tmp_out, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
