// WinHTTP transport with SPKI certificate pinning (HTTPS only).
#pragma once

#include <cstdint>
#include <functional>
#include <string>

namespace hpmmo {

struct HttpOutcome {
    bool ok = false;
    int status = 0;             // HTTP status (0 when no response was received)
    std::string errorKind;      // network | pin | tls | cancel | http | config | range
    std::string error;          // human-readable detail
    std::string certPinHex;     // observed SPKI sha256 of the server certificate
    bool pinChecked = false;    // a pin was required and matched
    bool resumed = false;       // server honored a Range request
    uint64_t bytesWritten = 0;  // bytes written by this call
};

struct HttpRequestOptions {
    std::wstring url;
    uint64_t resumeFrom = 0;              // adds "Range: bytes=N-"
    std::wstring pinnedSpkiHex;           // required; fails closed when empty
    size_t maxBodyBytes = 32u << 20;      // memory responses only
    int receiveTimeoutMs = 30000;
    // (received total, expected total or 0) -> false cancels the transfer.
    std::function<bool(uint64_t, uint64_t)> progress;
};

// Fetches a small document into memory.
HttpOutcome HttpGetToString(const HttpRequestOptions& opts, std::string& bodyOut);

// Streams an artifact to destPath; resumes when opts.resumeFrom > 0 and the
// server answers 206. On a 200 answer the file is restarted from zero.
HttpOutcome HttpGetToFile(const HttpRequestOptions& opts, const std::wstring& destPath);

// Diagnostic helper: connects without a pin and returns the observed SPKI
// sha256. Used to bootstrap the pinned value; never used for verification.
HttpOutcome HttpProbeCertPin(const std::wstring& url, std::string& pinHexOut);

}  // namespace hpmmo
