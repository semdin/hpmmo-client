// Minimal, defensive ZIP reader for launcher packages.
#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace hpmmo {

struct ZipEntry {
    std::string name;
    uint16_t method = 0;
    uint16_t flags = 0;
    uint16_t versionMadeBy = 0;
    uint32_t crc32 = 0;
    uint64_t compSize = 0;
    uint64_t uncompSize = 0;
    uint64_t localOffset = 0;
    uint32_t externalAttr = 0;
};

struct ExtractedFile {
    std::string relPath;  // forward slashes
    uint64_t size = 0;
    std::string sha256;   // hex
};

class ZipReader {
public:
    ~ZipReader();
    bool Open(const std::wstring& path, std::string& err);
    const std::vector<ZipEntry>& entries() const { return entries_; }

    // Extracts all entries below destDir. Every name is validated (no absolute
    // paths, no "..", no symlinks, no NTFS ADS); every entry's CRC and
    // uncompressed size are verified. Returns the verified file list.
    bool ExtractAll(const std::wstring& destDir, std::vector<ExtractedFile>& files,
                    std::string& err, const std::function<bool()>& cancelled = {});

private:
    HANDLE file_ = INVALID_HANDLE_VALUE;
    HANDLE mapping_ = NULL;
    const unsigned char* data_ = nullptr;
    uint64_t size_ = 0;
    std::vector<ZipEntry> entries_;
};

}  // namespace hpmmo
