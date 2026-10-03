#include "zip.h"

#include "common.h"
#include "inflate.h"
#include "sha256.h"

#include <set>
#include <vector>

namespace hpmmo {

namespace {

constexpr uint32_t kEocdSig = 0x06054b50;
constexpr uint32_t kZip64EocdSig = 0x06064b50;
constexpr uint32_t kZip64LocatorSig = 0x07064b50;
constexpr uint32_t kCentralSig = 0x02014b50;
constexpr uint32_t kLocalSig = 0x04034b50;
constexpr size_t kMaxEntries = 200000;
constexpr uint64_t kMaxTotalUncompressed = 16ull * 1024 * 1024 * 1024;
constexpr size_t kMaxNameLen = 4096;

uint16_t Rd16(const unsigned char* p) { return (uint16_t)(p[0] | (p[1] << 8)); }
uint32_t Rd32(const unsigned char* p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) | ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
uint64_t Rd64(const unsigned char* p) {
    return (uint64_t)Rd32(p) | ((uint64_t)Rd32(p + 4) << 32);
}

uint32_t* CrcTable() {
    static uint32_t table[256];
    static bool init = false;
    if (!init) {
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t c = i;
            for (int k = 0; k < 8; k++) c = (c & 1) ? 0xEDB88320u ^ (c >> 1) : (c >> 1);
            table[i] = c;
        }
        init = true;
    }
    return table;
}

// Streaming CRC-32 update on the raw running value: initialize with
// 0xFFFFFFFF, feed every chunk, then xor the result with 0xFFFFFFFF.
uint32_t CrcUpdate(uint32_t crc, const unsigned char* data, size_t len) {
    uint32_t* table = CrcTable();
    for (size_t i = 0; i < len; i++) crc = table[(crc ^ data[i]) & 0xFF] ^ (crc >> 8);
    return crc;
}

std::wstring LongPath(const std::wstring& p) {
    if (p.size() < 248) return p;
    if (p.compare(0, 4, L"\\\\?\\") == 0) return p;
    if (p.size() >= 2 && p[1] == L':') return L"\\\\?\\" + p;
    return p;
}

bool IsBadWindowsComponent(const std::string& part, std::string& reason) {
    if (part.empty()) {
        reason = "empty path component";
        return true;
    }
    if (part.size() > 255) {
        reason = "path component too long";
        return true;
    }
    if (part == "." || part == "..") {
        reason = "path traversal component";
        return true;
    }
    for (unsigned char c : part) {
        if (c < 0x20 || c == ':' || c == '<' || c == '>' || c == '"' || c == '|' || c == '?' ||
            c == '*' || c == '\\' || c == '/') {
            reason = "invalid character in entry name";
            return true;
        }
    }
    if (part.back() == '.' || part.back() == ' ') {
        reason = "component ends with a dot or space";
        return true;
    }
    // Reserved DOS device names (case-insensitive, extension-insensitive).
    std::string base = part;
    size_t dot = base.find('.');
    if (dot != std::string::npos) base = base.substr(0, dot);
    std::string lower;
    for (char c : base) lower.push_back((char)tolower((unsigned char)c));
    static const char* kReserved[] = {"con",  "prn",  "aux",  "nul",  "com1", "com2", "com3",
                                      "com4", "com5", "com6", "com7", "com8", "com9", "lpt1",
                                      "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8",
                                      "lpt9"};
    for (const char* r : kReserved) {
        if (lower == r) {
            reason = "reserved device name in entry";
            return true;
        }
    }
    return false;
}

// Validates and normalizes an archive entry name. Returns false and a reason
// when the name must be rejected.
bool ValidateEntryName(const std::string& raw, std::string& normalized, bool& isDir,
                       std::string& reason) {
    if (raw.empty() || raw.size() > kMaxNameLen) {
        reason = "entry name empty or too long";
        return false;
    }
    normalized.clear();
    normalized.reserve(raw.size());
    for (char c : raw) normalized.push_back(c == '\\' ? '/' : c);
    isDir = false;
    if (normalized.back() == '/') {
        isDir = true;
        normalized.pop_back();
    }
    if (normalized.empty()) {
        reason = "entry is the archive root";
        return false;
    }
    if (normalized[0] == '/') {
        reason = "absolute path in archive";
        return false;
    }
    if (normalized.size() >= 2 && normalized[1] == ':') {
        reason = "drive-qualified path in archive";
        return false;
    }
    size_t start = 0;
    while (true) {
        size_t slash = normalized.find('/', start);
        std::string part = normalized.substr(
            start, slash == std::string::npos ? std::string::npos : slash - start);
        if (IsBadWindowsComponent(part, reason)) return false;
        if (slash == std::string::npos) break;
        start = slash + 1;
    }
    if (normalized.size() > 30000) {
        reason = "entry path too long";
        return false;
    }
    return true;
}

class FileWriter {
public:
    ~FileWriter() { Close(); }
    bool Open(const std::wstring& path) {
        Close();
        h_ = CreateFileW(LongPath(path).c_str(), GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                         FILE_ATTRIBUTE_NORMAL, NULL);
        return h_ != INVALID_HANDLE_VALUE;
    }
    bool Write(const unsigned char* data, size_t len) {
        while (len > 0) {
            DWORD chunk = (DWORD)(len > (1u << 20) ? (1u << 20) : len);
            DWORD written = 0;
            if (!WriteFile(h_, data, chunk, &written, NULL) || written != chunk) return false;
            data += written;
            len -= written;
        }
        return true;
    }
    bool Close() {
        if (h_ != INVALID_HANDLE_VALUE) {
            FlushFileBuffers(h_);
            CloseHandle(h_);
            h_ = INVALID_HANDLE_VALUE;
        }
        return true;
    }

private:
    HANDLE h_ = INVALID_HANDLE_VALUE;
};

}  // namespace

ZipReader::~ZipReader() {
    if (data_) UnmapViewOfFile(data_);
    if (mapping_) CloseHandle(mapping_);
    if (file_ != INVALID_HANDLE_VALUE) CloseHandle(file_);
}

bool ZipReader::Open(const std::wstring& path, std::string& err) {
    entries_.clear();
    file_ = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                        FILE_ATTRIBUTE_NORMAL, NULL);
    if (file_ == INVALID_HANDLE_VALUE) {
        err = "cannot open archive";
        return false;
    }
    LARGE_INTEGER li;
    if (!GetFileSizeEx(file_, &li) || li.QuadPart < 22) {
        err = "archive too small";
        return false;
    }
    size_ = (uint64_t)li.QuadPart;
    mapping_ = CreateFileMappingW(file_, NULL, PAGE_READONLY, 0, 0, NULL);
    if (!mapping_) {
        err = "cannot map archive";
        return false;
    }
    data_ = (const unsigned char*)MapViewOfFile(mapping_, FILE_MAP_READ, 0, 0, 0);
    if (!data_) {
        err = "cannot map archive";
        return false;
    }

    // Locate the end-of-central-directory record.
    size_t back = (size_t)(size_ < 65557 + 22 ? size_ : 65557 + 22);
    int64_t eocd = -1;
    for (size_t i = back; i >= 22; i--) {
        size_t off = (size_t)(size_ - i);
        if (off + 22 > size_) continue;
        if (Rd32(data_ + off) != kEocdSig) continue;
        uint16_t commentLen = Rd16(data_ + off + 20);
        if (off + 22 + commentLen == size_) {
            eocd = (int64_t)off;
            break;
        }
    }
    if (eocd < 0) {
        err = "end of central directory not found";
        return false;
    }
    const unsigned char* e = data_ + eocd;
    uint64_t entriesTotal = Rd16(e + 10);
    uint64_t cdSize = Rd32(e + 12);
    uint64_t cdOffset = Rd32(e + 16);
    if (entriesTotal == 0xFFFF || cdSize == 0xFFFFFFFF || cdOffset == 0xFFFFFFFF) {
        // Zip64: locator sits immediately before the EOCD.
        if (eocd < 20 || Rd32(data_ + eocd - 20) != kZip64LocatorSig) {
            err = "zip64 locator missing";
            return false;
        }
        uint64_t z64off = Rd64(data_ + eocd - 20 + 8);
        if (z64off + 56 > size_ || Rd32(data_ + z64off) != kZip64EocdSig) {
            err = "zip64 end of central directory not found";
            return false;
        }
        entriesTotal = Rd64(data_ + z64off + 32);
        cdSize = Rd64(data_ + z64off + 40);
        cdOffset = Rd64(data_ + z64off + 48);
    }
    if (entriesTotal > kMaxEntries) {
        err = "archive has too many entries";
        return false;
    }
    if (cdOffset + cdSize > size_ || cdOffset > size_) {
        err = "central directory out of bounds";
        return false;
    }

    uint64_t pos = cdOffset;
    for (uint64_t i = 0; i < entriesTotal; i++) {
        if (pos + 46 > size_ || Rd32(data_ + pos) != kCentralSig) {
            err = "bad central directory entry";
            return false;
        }
        const unsigned char* c = data_ + pos;
        ZipEntry ent;
        ent.versionMadeBy = Rd16(c + 4);
        ent.flags = Rd16(c + 8);
        ent.method = Rd16(c + 10);
        ent.crc32 = Rd32(c + 16);
        ent.compSize = Rd32(c + 20);
        ent.uncompSize = Rd32(c + 24);
        uint16_t nameLen = Rd16(c + 28);
        uint16_t extraLen = Rd16(c + 30);
        uint16_t commentLen = Rd16(c + 32);
        ent.externalAttr = Rd32(c + 38);
        ent.localOffset = Rd32(c + 42);
        if (pos + 46 + nameLen + extraLen + commentLen > size_) {
            err = "central directory entry out of bounds";
            return false;
        }
        ent.name.assign((const char*)c + 46, nameLen);
        // Zip64 extra field.
        const unsigned char* x = c + 46 + nameLen;
        size_t xleft = extraLen;
        while (xleft >= 4) {
            uint16_t id = Rd16(x), len = Rd16(x + 2);
            if (xleft < 4 + (size_t)len) break;
            if (id == 0x0001) {
                const unsigned char* f = x + 4;
                size_t fleft = len;
                if (ent.uncompSize == 0xFFFFFFFF && fleft >= 8) {
                    ent.uncompSize = Rd64(f);
                    f += 8;
                    fleft -= 8;
                }
                if (ent.compSize == 0xFFFFFFFF && fleft >= 8) {
                    ent.compSize = Rd64(f);
                    f += 8;
                    fleft -= 8;
                }
                if (ent.localOffset == 0xFFFFFFFF && fleft >= 8) {
                    ent.localOffset = Rd64(f);
                    f += 8;
                    fleft -= 8;
                }
            }
            x += 4 + len;
            xleft -= 4 + (size_t)len;
        }
        entries_.push_back(std::move(ent));
        pos += 46 + nameLen + extraLen + commentLen;
    }
    return true;
}

bool ZipReader::ExtractAll(const std::wstring& destDir, std::vector<ExtractedFile>& files,
                           std::string& err, const std::function<bool()>& cancelled) {
    files.clear();
    std::wstring destNorm = NormalizePath(destDir);
    if (destNorm.empty() || !CreateDirs(destNorm)) {
        err = "cannot create extraction directory";
        return false;
    }
    std::set<std::string> seen;
    uint64_t totalOut = 0;
    for (const auto& ent : entries_) {
        if (cancelled && cancelled()) {
            err = "cancelled";
            return false;
        }
        if (ent.flags & 0x1) {
            err = "archive entry is encrypted";
            return false;
        }
        if (ent.flags & 0x40) {
            err = "archive uses strong encryption";
            return false;
        }
        if (ent.method != 0 && ent.method != 8) {
            err = "unsupported compression method";
            return false;
        }
        // Reject symlinks and special files. The UNIX mode lives in the high
        // 16 bits of external attributes; a nonzero file type other than a
        // regular file is refused even when the host system byte says MS-DOS.
        {
            uint32_t kind = (ent.externalAttr >> 16) & 0xF000;
            if (kind == 0xA000 || kind == 0x2000 || kind == 0x6000 || kind == 0x1000) {
                err = "archive contains a symlink or special file";
                return false;
            }
        }
        if (ent.externalAttr & 0x400) {  // FILE_ATTRIBUTE_REPARSE_POINT
            err = "archive entry is a reparse point";
            return false;
        }

        std::string normalized;
        bool isDir = false;
        std::string reason;
        if (!ValidateEntryName(ent.name, normalized, isDir, reason)) {
            err = "unsafe archive entry '" + ent.name + "': " + reason;
            return false;
        }
        std::string lower = normalized;
        for (auto& c : lower) c = (char)tolower((unsigned char)c);
        if (!seen.insert(lower).second) {
            err = "duplicate archive entry '" + normalized + "'";
            return false;
        }

        std::wstring rel = Utf8ToWide(normalized);
        for (auto& c : rel)
            if (c == L'/') c = L'\\';
        std::wstring target = JoinPath(destNorm, rel);
        std::wstring targetNorm = NormalizePath(target);
        if (!PathStartsWithCI(targetNorm, destNorm)) {
            err = "archive entry escapes the target directory";
            return false;
        }

        if (isDir) {
            if (!CreateDirs(targetNorm)) {
                err = "cannot create directory '" + normalized + "'";
                return false;
            }
            continue;
        }

        if (ent.uncompSize > kMaxTotalUncompressed - totalOut) {
            err = "archive uncompressed size limit exceeded";
            return false;
        }
        totalOut += ent.uncompSize;
        if (ent.compSize > size_ || ent.localOffset > size_ ||
            ent.localOffset + 30 > size_ || ent.compSize > size_ - ent.localOffset) {
            err = "archive entry data out of bounds";
            return false;
        }
        const unsigned char* lh = data_ + ent.localOffset;
        if (Rd32(lh) != kLocalSig) {
            err = "bad local file header";
            return false;
        }
        uint16_t lnameLen = Rd16(lh + 26);
        uint16_t lextraLen = Rd16(lh + 28);
        uint64_t dataOff = ent.localOffset + 30 + lnameLen + lextraLen;
        if (dataOff > size_ || ent.compSize > size_ - dataOff) {
            err = "archive entry data out of bounds";
            return false;
        }

        size_t slash = targetNorm.find_last_of(L'\\');
        if (slash != std::wstring::npos && slash > 2) {
            if (!CreateDirs(targetNorm.substr(0, slash))) {
                err = "cannot create parent directory for '" + normalized + "'";
                return false;
            }
        }

        FileWriter writer;
        uint32_t crc = 0xFFFFFFFFu;
        uint64_t produced = 0;
        bool ok = writer.Open(targetNorm);
        if (!ok) {
            err = "cannot create file '" + normalized + "'";
            return false;
        }
        if (ent.method == 0) {
            const unsigned char* p = data_ + dataOff;
            size_t left = (size_t)ent.compSize;
            while (left > 0 && ok) {
                size_t chunk = left > (1u << 20) ? (1u << 20) : left;
                ok = writer.Write(p, chunk);
                crc = CrcUpdate(crc, p, chunk);
                p += chunk;
                left -= chunk;
            }
            produced = ent.compSize;
        } else {
            std::string ierr;
            uint64_t outSize = 0;
            ok = InflateDecompress(data_ + dataOff, (size_t)ent.compSize, ent.uncompSize,
                                   [&](const unsigned char* d, size_t n) {
                                       crc = CrcUpdate(crc, d, n);
                                       return writer.Write(d, n);
                                   },
                                   &outSize, ierr);
            if (!ok) {
                err = "bad compressed data in '" + normalized + "': " + ierr;
                return false;
            }
            produced = outSize;
        }
        writer.Close();
        if (!ok || produced != ent.uncompSize) {
            err = "unpacked size mismatch in '" + normalized + "'";
            return false;
        }
        crc ^= 0xFFFFFFFFu;
        if (crc != ent.crc32) {
            err = "CRC mismatch in '" + normalized + "'";
            return false;
        }

        ExtractedFile f;
        f.relPath = normalized;
        f.size = produced;
        std::string herr;
        unsigned char digest[32];
        if (!Sha256File(targetNorm, digest, &f.size, herr)) {
            err = "cannot hash extracted '" + normalized + "': " + herr;
            return false;
        }
        f.sha256 = HexLower(digest, 32);
        files.push_back(std::move(f));
    }
    return true;
}

}  // namespace hpmmo
