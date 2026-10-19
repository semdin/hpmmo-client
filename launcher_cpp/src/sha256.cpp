#include "sha256.h"

#include "common.h"

#ifdef _WIN32

#include <windows.h>
#include <bcrypt.h>

#include <mutex>

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

#else  // !_WIN32: portable SHA-256 (FIPS 180-4), no system crypto needed.

#include <cstring>

namespace hpmmo {

namespace {

const uint32_t kK[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};

inline uint32_t Rotr(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

struct Sha256Ctx {
    uint32_t h[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                     0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    unsigned char block[64];
    size_t used = 0;
    uint64_t total = 0;

    void Compress(const unsigned char* b) {
        uint32_t w[64];
        for (int i = 0; i < 16; i++)
            w[i] = ((uint32_t)b[i * 4] << 24) | ((uint32_t)b[i * 4 + 1] << 16) |
                   ((uint32_t)b[i * 4 + 2] << 8) | (uint32_t)b[i * 4 + 3];
        for (int i = 16; i < 64; i++) {
            uint32_t s0 = Rotr(w[i - 15], 7) ^ Rotr(w[i - 15], 18) ^ (w[i - 15] >> 3);
            uint32_t s1 = Rotr(w[i - 2], 17) ^ Rotr(w[i - 2], 19) ^ (w[i - 2] >> 10);
            w[i] = w[i - 16] + s0 + w[i - 7] + s1;
        }
        uint32_t a = h[0], bb = h[1], c = h[2], d = h[3], e = h[4], f = h[5], g = h[6], hh = h[7];
        for (int i = 0; i < 64; i++) {
            uint32_t t1 = hh + (Rotr(e, 6) ^ Rotr(e, 11) ^ Rotr(e, 25)) + ((e & f) ^ (~e & g)) + kK[i] + w[i];
            uint32_t t2 = (Rotr(a, 2) ^ Rotr(a, 13) ^ Rotr(a, 22)) + ((a & bb) ^ (a & c) ^ (bb & c));
            hh = g;
            g = f;
            f = e;
            e = d + t1;
            d = c;
            c = bb;
            bb = a;
            a = t1 + t2;
        }
        h[0] += a; h[1] += bb; h[2] += c; h[3] += d;
        h[4] += e; h[5] += f; h[6] += g; h[7] += hh;
    }

    void Update(const unsigned char* p, size_t len) {
        total += len;
        if (used) {
            size_t take = 64 - used < len ? 64 - used : len;
            memcpy(block + used, p, take);
            used += take;
            p += take;
            len -= take;
            if (used == 64) {
                Compress(block);
                used = 0;
            }
        }
        while (len >= 64) {
            Compress(p);
            p += 64;
            len -= 64;
        }
        if (len) {
            memcpy(block, p, len);
            used = len;
        }
    }

    void Final(unsigned char out[32]) {
        uint64_t bits = total * 8;
        unsigned char pad = 0x80;
        Update(&pad, 1);
        unsigned char zero = 0;
        while (used != 56) Update(&zero, 1);
        unsigned char len[8];
        for (int i = 0; i < 8; i++) len[i] = (unsigned char)(bits >> (56 - 8 * i));
        Update(len, 8);
        for (int i = 0; i < 8; i++) {
            out[i * 4] = (unsigned char)(h[i] >> 24);
            out[i * 4 + 1] = (unsigned char)(h[i] >> 16);
            out[i * 4 + 2] = (unsigned char)(h[i] >> 8);
            out[i * 4 + 3] = (unsigned char)h[i];
        }
    }
};

}  // namespace

bool Sha256Buffer(const void* data, size_t len, unsigned char out[32]) {
    Sha256Ctx ctx;
    ctx.Update((const unsigned char*)data, len);
    ctx.Final(out);
    return true;
}

std::string Sha256Hex(const void* data, size_t len) {
    unsigned char digest[32];
    Sha256Buffer(data, len, digest);
    return HexLower(digest, 32);
}

bool Sha256File(const std::wstring& path, unsigned char out[32], uint64_t* sizeOut,
                std::string& err) {
    if (sizeOut) *sizeOut = 0;
    FILE* f = OpenFileW(path, L"rb");
    if (!f) {
        err = "cannot open file (" + std::to_string(LastErrorCode()) + ")";
        return false;
    }
    Sha256Ctx ctx;
    std::vector<unsigned char> buf(1 << 20);
    size_t got;
    while ((got = fread(buf.data(), 1, buf.size(), f)) > 0) ctx.Update(buf.data(), got);
    bool ok = !ferror(f);
    if (!ok) err = "read failed (" + std::to_string(LastErrorCode()) + ")";
    fclose(f);
    if (!ok) return false;
    uint64_t size = ctx.total;  // Final() feeds the padding through Update()
    ctx.Final(out);
    if (sizeOut) *sizeOut = size;
    return true;
}

std::string Sha256FileHex(const std::wstring& path) {
    unsigned char digest[32];
    std::string err;
    if (!Sha256File(path, digest, nullptr, err)) return "";
    return HexLower(digest, 32);
}

}  // namespace hpmmo

#endif  // _WIN32
