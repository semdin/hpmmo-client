// Raw DEFLATE decompressor, implemented from RFC 1951 (puff-style canonical
// Huffman decoding). Written for the launcher; no third-party code.
#include "inflate.h"

#include <cstring>
#include <vector>

namespace hpmmo {

namespace {

constexpr int kMaxBits = 15;
constexpr size_t kWindowSize = 32768;
constexpr size_t kFlushAt = 64 * 1024;
constexpr uint64_t kHardMaxOut = 1ull << 30;  // 1 GiB

struct Huffman {
    short count[kMaxBits + 1];
    short symbol[288];
};

bool BuildHuffman(Huffman& h, const short* lengths, int n, std::string& err) {
    for (int i = 0; i <= kMaxBits; i++) h.count[i] = 0;
    for (int i = 0; i < n; i++) {
        if (lengths[i] < 0 || lengths[i] > kMaxBits) {
            err = "invalid code length";
            return false;
        }
        h.count[lengths[i]]++;
    }
    if (h.count[0] == n) return true;  // no codes at all (unused distance tree)
    int left = 1;
    for (int len = 1; len <= kMaxBits; len++) {
        left <<= 1;
        left -= h.count[len];
        if (left < 0) {
            err = "over-subscribed Huffman code";
            return false;
        }
    }
    short offs[kMaxBits + 2];
    offs[1] = 0;
    for (int len = 1; len <= kMaxBits; len++) offs[len + 1] = (short)(offs[len] + h.count[len]);
    for (int i = 0; i < n; i++) {
        if (lengths[i] != 0) h.symbol[offs[lengths[i]]++] = (short)i;
    }
    return true;
}

class BitReader {
public:
    BitReader(const unsigned char* in, size_t len) : in_(in), len_(len) {}

    // n must be <= 24.
    bool Get(int n, unsigned int& out) {
        while (cnt_ < n) {
            if (pos_ >= len_) return false;
            bits_ |= (uint32_t)in_[pos_++] << cnt_;
            cnt_ += 8;
        }
        out = bits_ & ((1u << n) - 1);
        bits_ >>= n;
        cnt_ -= n;
        return true;
    }

    void AlignByte() {
        int drop = cnt_ & 7;
        bits_ >>= drop;
        cnt_ -= drop;
    }

    bool ReadByte(unsigned char& out) {
        if (cnt_ >= 8) {
            out = (unsigned char)(bits_ & 0xFF);
            bits_ >>= 8;
            cnt_ -= 8;
            return true;
        }
        if (pos_ >= len_) return false;
        out = in_[pos_++];
        return true;
    }

    bool ReadRaw(unsigned char* dst, size_t n) {
        while (n > 0 && cnt_ >= 8) {
            *dst++ = (unsigned char)(bits_ & 0xFF);
            bits_ >>= 8;
            cnt_ -= 8;
            n--;
        }
        if (n > 0) {
            if (len_ - pos_ < n) return false;
            memcpy(dst, in_ + pos_, n);
            pos_ += n;
        }
        return true;
    }

    size_t consumed() const { return pos_; }
    // The stream ends mid-byte; up to 7 buffered padding bits are fine, but a
    // whole unconsumed byte means there is trailing data after the stream.
    bool exhaustedCleanly() const { return pos_ == len_ && cnt_ < 8; }

private:
    const unsigned char* in_;
    size_t len_;
    size_t pos_ = 0;
    uint32_t bits_ = 0;
    int cnt_ = 0;
};

bool DecodeSymbol(BitReader& br, const Huffman& h, int& sym, std::string& err) {
    int code = 0, first = 0, index = 0;
    for (int len = 1; len <= kMaxBits; len++) {
        unsigned int bit;
        if (!br.Get(1, bit)) {
            err = "truncated stream";
            return false;
        }
        code |= (int)bit;
        int count = h.count[len];
        if (code - first < count) {
            sym = h.symbol[index + (code - first)];
            return true;
        }
        index += count;
        first = (first + count) << 1;
        code <<= 1;
    }
    err = "invalid Huffman code";
    return false;
}

bool BuildFixed(Huffman& lit, Huffman& dist, std::string& err) {
    short lengths[288];
    for (int i = 0; i < 144; i++) lengths[i] = 8;
    for (int i = 144; i < 256; i++) lengths[i] = 9;
    for (int i = 256; i < 280; i++) lengths[i] = 7;
    for (int i = 280; i < 288; i++) lengths[i] = 8;
    if (!BuildHuffman(lit, lengths, 288, err)) return false;
    for (int i = 0; i < 30; i++) lengths[i] = 5;
    return BuildHuffman(dist, lengths, 30, err);
}

bool BuildDynamic(BitReader& br, Huffman& lit, Huffman& dist, std::string& err) {
    static const int kOrder[19] = {16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15};
    unsigned int hlit, hdist, hclen;
    if (!br.Get(5, hlit) || !br.Get(5, hdist) || !br.Get(4, hclen)) {
        err = "truncated dynamic header";
        return false;
    }
    int nlen = (int)hlit + 257;
    int ndist = (int)hdist + 1;
    if (nlen > 286 || ndist > 30) {
        err = "too many dynamic codes";
        return false;
    }
    short clen[19] = {0};
    for (int i = 0; i < (int)hclen + 4; i++) {
        unsigned int v;
        if (!br.Get(3, v)) {
            err = "truncated code-length code";
            return false;
        }
        clen[kOrder[i]] = (short)v;
    }
    Huffman cl;
    if (!BuildHuffman(cl, clen, 19, err)) return false;

    short lengths[286 + 30] = {0};
    int total = nlen + ndist;
    int i = 0;
    while (i < total) {
        int sym;
        if (!DecodeSymbol(br, cl, sym, err)) return false;
        if (sym < 16) {
            lengths[i++] = (short)sym;
        } else if (sym == 16) {
            if (i == 0) {
                err = "repeat with no previous length";
                return false;
            }
            unsigned int rep;
            if (!br.Get(2, rep)) {
                err = "truncated repeat";
                return false;
            }
            short prev = lengths[i - 1];
            for (int r = 0; r < (int)rep + 3; r++) {
                if (i >= total) {
                    err = "repeat overruns table";
                    return false;
                }
                lengths[i++] = prev;
            }
        } else {
            int zeros = sym == 17 ? 3 : 11;
            unsigned int rep = 0;
            if (sym == 18) {
                if (!br.Get(7, rep)) {
                    err = "truncated repeat";
                    return false;
                }
            } else {
                if (!br.Get(3, rep)) {
                    err = "truncated repeat";
                    return false;
                }
            }
            zeros += (int)rep;
            for (int r = 0; r < zeros; r++) {
                if (i >= total) {
                    err = "zero repeat overruns table";
                    return false;
                }
                lengths[i++] = 0;
            }
        }
    }
    if (lengths[256] == 0) {
        err = "dynamic block has no end-of-block code";
        return false;
    }
    if (!BuildHuffman(lit, lengths, nlen, err)) return false;
    return BuildHuffman(dist, lengths + nlen, ndist, err);
}

const unsigned short kLenBase[29] = {3,  4,  5,  6,  7,  8,  9,  10, 11,  13,  15,  17,  19, 23, 27,
                                     31, 35, 43, 51, 59, 67, 83, 99, 115, 131, 163, 195, 227, 258};
const unsigned char kLenExtra[29] = {0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2,
                                     2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0};
const unsigned short kDistBase[30] = {1,    2,    3,    4,    5,    7,     9,     13,    17,    25,
                                      33,   49,   65,   97,   129,  193,   257,   385,   513,   769,
                                      1025, 1537, 2049, 3073, 4097, 6145,  8193,  12289, 16385, 24577};
const unsigned char kDistExtra[30] = {0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4,  4,  5,  5,  6,
                                      6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13, 13};

class Decoder {
public:
    Decoder(const unsigned char* in, size_t len, uint64_t maxOut, const InflateSink& sink)
        : br_(in, len), maxOut_(maxOut ? maxOut : kHardMaxOut), sink_(sink) {}

    bool Run(uint64_t& outSize, std::string& err) {
        bool last = false;
        while (!last) {
            unsigned int b;
            if (!br_.Get(1, b)) return Fail("truncated stream", err);
            last = b != 0;
            unsigned int type;
            if (!br_.Get(2, type)) return Fail("truncated stream", err);
            if (type == 0) {
                if (!Stored(err)) return false;
            } else if (type == 1) {
                Huffman lit, dist;
                if (!BuildFixed(lit, dist, err)) return false;
                if (!Codes(lit, dist, err)) return false;
            } else if (type == 2) {
                Huffman lit, dist;
                if (!BuildDynamic(br_, lit, dist, err)) return false;
                if (!Codes(lit, dist, err)) return false;
            } else {
                return Fail("invalid block type", err);
            }
        }
        outSize = outSize_;
        if (!Flush(err)) return false;
        if (!br_.exhaustedCleanly()) {
            return Fail("trailing bytes after DEFLATE stream", err);
        }
        return true;
    }

private:
    bool Fail(const std::string& what, std::string& err) {
        err = what;
        return false;
    }

    bool Emit(unsigned char c, std::string& err) {
        if (outSize_ + 1 > maxOut_) return Fail("output exceeds declared size", err);
        window_[wpos_++ & (kWindowSize - 1)] = c;
        buf_.push_back(c);
        outSize_++;
        if (buf_.size() >= kFlushAt) return Flush(err);
        return true;
    }

    bool Flush(std::string& err) {
        if (!buf_.empty()) {
            if (!sink_(buf_.data(), buf_.size())) return Fail("output sink aborted", err);
            buf_.clear();
        }
        return true;
    }

    bool Copy(unsigned int len, unsigned int dist, std::string& err) {
        if (dist == 0 || dist > kWindowSize) return Fail("invalid back-reference distance", err);
        if ((uint64_t)dist > outSize_) return Fail("back-reference before output start", err);
        for (unsigned int i = 0; i < len; i++) {
            unsigned char c = window_[(wpos_ - dist) & (kWindowSize - 1)];
            if (!Emit(c, err)) return false;
        }
        return true;
    }

    bool Stored(std::string& err) {
        br_.AlignByte();
        unsigned char lenb[4];
        if (!br_.ReadRaw(lenb, 4)) return Fail("truncated stored block header", err);
        unsigned int len = lenb[0] | ((unsigned int)lenb[1] << 8);
        unsigned int nlen = lenb[2] | ((unsigned int)lenb[3] << 8);
        if ((len ^ 0xFFFF) != nlen) return Fail("stored block length mismatch", err);
        for (unsigned int i = 0; i < len; i++) {
            unsigned char c;
            if (!br_.ReadByte(c)) return Fail("truncated stored block", err);
            if (!Emit(c, err)) return false;
        }
        total_ = outSize_;
        return true;
    }

    bool Codes(const Huffman& lit, const Huffman& dist, std::string& err) {
        while (true) {
            int sym;
            if (!DecodeSymbol(br_, lit, sym, err)) return false;
            if (sym < 256) {
                if (!Emit((unsigned char)sym, err)) return false;
            } else if (sym == 256) {
                total_ = outSize_;
                return true;
            } else {
                int li = sym - 257;
                if (li >= 29) return Fail("invalid length code", err);
                unsigned int extra = 0;
                if (kLenExtra[li] && !br_.Get(kLenExtra[li], extra)) {
                    return Fail("truncated length extra bits", err);
                }
                unsigned int len = kLenBase[li] + extra;
                int dsym;
                if (!DecodeSymbol(br_, dist, dsym, err)) return false;
                if (dsym >= 30) return Fail("invalid distance code", err);
                extra = 0;
                if (kDistExtra[dsym] && !br_.Get(kDistExtra[dsym], extra)) {
                    return Fail("truncated distance extra bits", err);
                }
                unsigned int d = kDistBase[dsym] + extra;
                if (!Copy(len, d, err)) return false;
            }
        }
    }

    BitReader br_;
    uint64_t maxOut_;
    const InflateSink& sink_;
    unsigned char window_[kWindowSize] = {0};
    size_t wpos_ = 0;
    uint64_t outSize_ = 0;
    uint64_t total_ = 0;
    std::vector<unsigned char> buf_;
};

}  // namespace

bool InflateDecompress(const unsigned char* in, size_t inLen, uint64_t maxOut,
                       const InflateSink& sink, uint64_t* outSize, std::string& err) {
    if (!in && inLen > 0) {
        err = "null input";
        return false;
    }
    Decoder d(in, inLen, maxOut, sink);
    uint64_t produced = 0;
    if (!d.Run(produced, err)) return false;
    if (outSize) *outSize = produced;
    return true;
}

}  // namespace hpmmo
