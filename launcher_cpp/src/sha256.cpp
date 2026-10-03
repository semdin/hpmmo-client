#include "sha256.h"

#include "common.h"

#include <bcrypt.h>
#include <windows.h>

namespace hpmmo {

namespace {

BCRYPT_ALG_HANDLE Sha256Alg() {
    static BCRYPT_ALG_HANDLE alg = NULL;
    static std::once_flag once;
    std::call_once(once, []() {
        if (BCryptOpenAlgorithmProvider(&alg, BCRYPT_SHA256_ALGORITHM, NULL, 0) != 0) {
            alg = NULL;
        }
    });
    return alg;
}

}  // namespace

bool Sha256Buffer(const void* data, size_t len, unsigned char out[32]) {
    BCRYPT_ALG_HANDLE alg = Sha256Alg();
    if (!alg) return false;
    BCRYPT_HASH_HANDLE hash = NULL;
    if (BCryptCreateHash(alg, &hash, NULL, 0, NULL, 0, 0) != 0) return false;
    bool ok = BCryptHashData(hash, (PUCHAR)data, (ULONG)len, 0) == 0;
    if (ok) ok = BCryptFinishHash(hash, out, 32, 0) == 0;
    BCryptDestroyHash(hash);
    return ok;
}

std::string Sha256Hex(const void* data, size_t len) {
    unsigned char digest[32];
    if (!Sha256Buffer(data, len, digest)) return "";
    return HexLower(digest, 32);
}

bool Sha256File(const std::wstring& path, unsigned char out[32], uint64_t* sizeOut,
                std::string& err) {
    if (sizeOut) *sizeOut = 0;
    BCRYPT_ALG_HANDLE alg = Sha256Alg();
    if (!alg) {
        err = "SHA-256 provider unavailable";
        return false;
    }
    HANDLE h = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL | FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        err = "cannot open file (" + std::to_string(GetLastError()) + ")";
        return false;
    }
    BCRYPT_HASH_HANDLE hash = NULL;
    if (BCryptCreateHash(alg, &hash, NULL, 0, NULL, 0, 0) != 0) {
        CloseHandle(h);
        err = "cannot create hash object";
        return false;
    }
    std::vector<unsigned char> buf(1 << 20);
    bool ok = true;
    uint64_t total = 0;
    while (true) {
        DWORD got = 0;
        if (!ReadFile(h, buf.data(), (DWORD)buf.size(), &got, NULL)) {
            err = "read failed (" + std::to_string(GetLastError()) + ")";
            ok = false;
            break;
        }
        if (got == 0) break;
        total += got;
        if (BCryptHashData(hash, buf.data(), got, 0) != 0) {
            err = "hash update failed";
            ok = false;
            break;
        }
    }
    if (ok && BCryptFinishHash(hash, out, 32, 0) != 0) {
        err = "hash finalize failed";
        ok = false;
    }
    BCryptDestroyHash(hash);
    CloseHandle(h);
    if (ok && sizeOut) *sizeOut = total;
    return ok;
}

std::string Sha256FileHex(const std::wstring& path) {
    unsigned char digest[32];
    std::string err;
    if (!Sha256File(path, digest, nullptr, err)) return "";
    return HexLower(digest, 32);
}

}  // namespace hpmmo
