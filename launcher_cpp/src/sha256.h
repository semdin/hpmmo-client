// SHA-256 via the Windows CNG API (bcrypt.dll) - no vendored crypto here.
#pragma once

#include <cstdint>
#include <string>
#include <vector>

namespace hpmmo {

bool Sha256Buffer(const void* data, size_t len, unsigned char out[32]);
std::string Sha256Hex(const void* data, size_t len);
// Streams the file; returns false on I/O error. sizeOut gets the byte count.
bool Sha256File(const std::wstring& path, unsigned char out[32], uint64_t* sizeOut,
                std::string& err);
std::string Sha256FileHex(const std::wstring& path);

}  // namespace hpmmo
