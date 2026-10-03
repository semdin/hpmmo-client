// Raw DEFLATE (RFC 1951) decompressor. No external dependencies.
#pragma once

#include <cstdint>
#include <cstddef>
#include <functional>
#include <string>

namespace hpmmo {

using InflateSink = std::function<bool(const unsigned char* data, size_t len)>;

// Decompresses a complete raw DEFLATE stream held in memory. `maxOut` bounds
// the output (0 = 1 GiB hard cap); the sink returns false to abort. On success
// the whole input span must have been consumed.
bool InflateDecompress(const unsigned char* in, size_t inLen, uint64_t maxOut,
                       const InflateSink& sink, uint64_t* outSize, std::string& err);

}  // namespace hpmmo
