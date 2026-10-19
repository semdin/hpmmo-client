// libcurl transport (Linux, macOS) behind http.h - the counterpart of
// http_winhttp.cpp with the same contract: HTTPS with an SPKI pin or system
// trust, plain HTTP only for advisory documents, Range/resume, closed ranges
// that must be answered with 206, and cancellation through `progress`.
#include "http.h"

#include "common.h"
#include "sha256.h"

// The API is called through function pointers (see CurlApi), so curl.h's
// type-checking macros around curl_easy_setopt/getinfo must stay off.
#define CURL_DISABLE_TYPECHECK
#include <curl/curl.h>
#include <unistd.h>
#ifdef __linux__
#include <dlfcn.h>
#endif

#include <cstdio>
#include <type_traits>
#include <vector>

namespace hpmmo {

namespace {

// libcurl is loaded at run time on Linux: the launcher must start on any
// distribution, and every desktop ships libcurl.so.4 (or Debian/Ubuntu's
// libcurl-gnutls.so.4) configured for the system's own CA store. Linking it
// would pin the build host's soname and its ~30 dependencies. macOS always has
// /usr/lib/libcurl.4.dylib, so it links normally.
struct CurlApi {
    CURLcode (*global_init)(long) = nullptr;
    CURL* (*easy_init)() = nullptr;
    CURLcode (*easy_setopt)(CURL*, CURLoption, ...) = nullptr;
    CURLcode (*easy_perform)(CURL*) = nullptr;
    CURLcode (*easy_getinfo)(CURL*, CURLINFO, ...) = nullptr;
    void (*easy_cleanup)(CURL*) = nullptr;
    const char* (*easy_strerror)(CURLcode) = nullptr;
    bool ok = false;
    std::string error;
};

CurlApi LoadCurl() {
    CurlApi api;
#ifdef __linux__
    void* lib = nullptr;
    for (const char* name : {"libcurl.so.4", "libcurl-gnutls.so.4", "libcurl.so"}) {
        lib = dlopen(name, RTLD_NOW | RTLD_LOCAL);
        if (lib) break;
    }
    if (!lib) {
        api.error = "libcurl is not installed (install the curl / libcurl4 package)";
        return api;
    }
    auto sym = [&](auto& fn, const char* name) {
        fn = reinterpret_cast<std::remove_reference_t<decltype(fn)>>(dlsym(lib, name));
        if (!fn && api.error.empty()) api.error = std::string("libcurl lacks ") + name;
    };
    sym(api.global_init, "curl_global_init");
    sym(api.easy_init, "curl_easy_init");
    sym(api.easy_setopt, "curl_easy_setopt");
    sym(api.easy_perform, "curl_easy_perform");
    sym(api.easy_getinfo, "curl_easy_getinfo");
    sym(api.easy_cleanup, "curl_easy_cleanup");
    sym(api.easy_strerror, "curl_easy_strerror");
    api.ok = api.error.empty();
#else
    api.global_init = curl_global_init;
    api.easy_init = curl_easy_init;
    api.easy_setopt = curl_easy_setopt;
    api.easy_perform = curl_easy_perform;
    api.easy_getinfo = curl_easy_getinfo;
    api.easy_cleanup = curl_easy_cleanup;
    api.easy_strerror = curl_easy_strerror;
    api.ok = true;
#endif
    if (api.ok) api.global_init(CURL_GLOBAL_DEFAULT);
    return api;
}

const CurlApi& Curl() {
    static CurlApi api = LoadCurl();   // thread-safe initialisation
    return api;
}

std::string Base64Encode(const unsigned char* data, size_t len) {
    static const char* kAlphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    std::string out;
    for (size_t i = 0; i < len; i += 3) {
        uint32_t v = (uint32_t)data[i] << 16;
        if (i + 1 < len) v |= (uint32_t)data[i + 1] << 8;
        if (i + 2 < len) v |= data[i + 2];
        out.push_back(kAlphabet[(v >> 18) & 63]);
        out.push_back(kAlphabet[(v >> 12) & 63]);
        out.push_back(i + 1 < len ? kAlphabet[(v >> 6) & 63] : '=');
        out.push_back(i + 2 < len ? kAlphabet[v & 63] : '=');
    }
    return out;
}

struct Transfer {
    const HttpRequestOptions* opts = nullptr;
    FILE* file = nullptr;
    std::string* body = nullptr;
    uint64_t received = 0;
    uint64_t resumeBase = 0;   // bytes already on disk when a 206 resume is honoured
    bool tooLarge = false;
    bool writeFailed = false;
    bool cancelled = false;
    bool statusChecked = false;
    bool statusOk = false;
    CURL* curl = nullptr;
};

// Only the final response of a redirect chain may deliver a body; earlier ones
// (301/302) are swallowed by curl and never reach this callback.
bool AcceptStatus(Transfer& t) {
    if (t.statusChecked) return t.statusOk;
    t.statusChecked = true;
    long status = 0;
    Curl().easy_getinfo(t.curl, CURLINFO_RESPONSE_CODE, &status);
    t.statusOk = (status == 200 || status == 206) && !(t.opts->closedRange && status != 206);
    if (t.statusOk && t.file) {
        bool resumed = t.opts->resumeFrom > 0 && status == 206;
        t.resumeBase = resumed ? t.opts->resumeFrom : 0;
        // A 200 answer to a resume restarts the file from zero.
        if (!resumed) {
            if (ftruncate(fileno(t.file), 0) != 0 || fseeko(t.file, 0, SEEK_SET) != 0) t.writeFailed = true;
        } else if (fseeko(t.file, 0, SEEK_END) != 0) {
            t.writeFailed = true;
        }
    }
    return t.statusOk;
}

size_t OnData(char* ptr, size_t size, size_t nmemb, void* user) {
    Transfer& t = *static_cast<Transfer*>(user);
    size_t n = size * nmemb;
    if (!AcceptStatus(t)) return n;  // error bodies are discarded
    if (t.writeFailed) return 0;
    if (t.file && fwrite(ptr, 1, n, t.file) != n) {
        t.writeFailed = true;
        return 0;
    }
    if (t.body) {
        if (t.body->size() + n > t.opts->maxBodyBytes) {
            t.tooLarge = true;
            return 0;
        }
        t.body->append(ptr, n);
    }
    t.received += n;
    return n;
}

int OnProgress(void* user, curl_off_t dltotal, curl_off_t, curl_off_t, curl_off_t) {
    Transfer& t = *static_cast<Transfer*>(user);
    if (!t.opts->progress || !t.statusChecked || !t.statusOk) return 0;
    uint64_t total = dltotal > 0 ? (uint64_t)dltotal + t.resumeBase : 0;
    if (!t.opts->progress(t.received + t.resumeBase, total)) {
        t.cancelled = true;
        return 1;
    }
    return 0;
}

HttpOutcome RunRequest(const HttpRequestOptions& opts, const std::wstring* destFile, std::string* bodyOut,
                       bool requirePin) {
    HttpOutcome out;
    const CurlApi& api = Curl();
    if (!api.ok) {
        out.errorKind = "network";
        out.error = api.error;
        return out;
    }
    std::string url = WideToUtf8(opts.url);
    bool secure = url.rfind("https://", 0) == 0;
    bool plain = url.rfind("http://", 0) == 0;
    if (!secure && !(plain && opts.allowPlainHttp)) {
        out.errorKind = "config";
        out.error = plain ? "URL is not HTTPS" : "malformed URL";
        return out;
    }
    {
        size_t hostStart = url.find("://") + 3;
        size_t hostEnd = url.find_first_of("/?#", hostStart);
        if (url.substr(hostStart, hostEnd - hostStart).find('@') != std::string::npos) {
            out.errorKind = "config";
            out.error = "credentials are not allowed in URLs";
            return out;
        }
    }
    if (!secure || opts.systemTrust) requirePin = false;
    const bool checkPin = secure && !opts.systemTrust;
    if (requirePin && opts.pinnedSpkiHex.empty()) {
        out.errorKind = "config";
        out.error = "no pinned certificate configured";
        return out;
    }

    CURL* curl = api.easy_init();
    if (!curl) {
        out.errorKind = "network";
        out.error = "curl_easy_init failed";
        return out;
    }
    Transfer t;
    t.opts = &opts;
    t.body = bodyOut;
    t.curl = curl;
    if (destFile) {
        // "ab" keeps a partial file for a resume; AcceptStatus truncates on 200.
        t.file = OpenFileW(*destFile, L"ab");
        if (!t.file) {
            api.easy_cleanup(curl);
            out.errorKind = "network";
            out.error = "cannot open destination file";
            return out;
        }
    }

    char errbuf[CURL_ERROR_SIZE] = {0};
    api.easy_setopt(curl, CURLOPT_URL, url.c_str());
    api.easy_setopt(curl, CURLOPT_ERRORBUFFER, errbuf);
    api.easy_setopt(curl, CURLOPT_USERAGENT, "HPMMO-Launcher/3");
    api.easy_setopt(curl, CURLOPT_FOLLOWLOCATION, 1L);
    api.easy_setopt(curl, CURLOPT_MAXREDIRS, 10L);
    // Redirects may not downgrade an HTTPS request to HTTP.
#if LIBCURL_VERSION_NUM >= 0x075500
    api.easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS_STR, secure ? "https" : "http,https");
    api.easy_setopt(curl, CURLOPT_PROTOCOLS_STR, secure ? "https" : "http,https");
#else
    api.easy_setopt(curl, CURLOPT_REDIR_PROTOCOLS, secure ? CURLPROTO_HTTPS : (CURLPROTO_HTTP | CURLPROTO_HTTPS));
    api.easy_setopt(curl, CURLOPT_PROTOCOLS, secure ? CURLPROTO_HTTPS : (CURLPROTO_HTTP | CURLPROTO_HTTPS));
#endif
    api.easy_setopt(curl, CURLOPT_CONNECTTIMEOUT_MS, 10000L);
    // Equivalent of the WinHTTP receive timeout: abort when the transfer stalls.
    api.easy_setopt(curl, CURLOPT_LOW_SPEED_LIMIT, 1L);
    api.easy_setopt(curl, CURLOPT_LOW_SPEED_TIME, (long)((opts.receiveTimeoutMs + 999) / 1000));
    api.easy_setopt(curl, CURLOPT_NOSIGNAL, 1L);
    api.easy_setopt(curl, CURLOPT_WRITEFUNCTION, OnData);
    api.easy_setopt(curl, CURLOPT_WRITEDATA, &t);
    api.easy_setopt(curl, CURLOPT_XFERINFOFUNCTION, OnProgress);
    api.easy_setopt(curl, CURLOPT_XFERINFODATA, &t);
    api.easy_setopt(curl, CURLOPT_NOPROGRESS, 0L);
    api.easy_setopt(curl, CURLOPT_ACCEPT_ENCODING, "identity");

    std::string range;
    if (opts.closedRange) {
        range = std::to_string(opts.resumeFrom) + "-" + std::to_string(opts.rangeLast);
    } else if (opts.resumeFrom > 0) {
        range = std::to_string(opts.resumeFrom) + "-";
    }
    if (!range.empty()) api.easy_setopt(curl, CURLOPT_RANGE, range.c_str());

    // Pinning: the SPKI pin is the authentication decision, so chain/name
    // validation is replaced by an exact public-key match (as on Windows).
    std::string pinOpt;
    if (checkPin) {
        api.easy_setopt(curl, CURLOPT_SSL_VERIFYPEER, 0L);
        api.easy_setopt(curl, CURLOPT_SSL_VERIFYHOST, 0L);
        std::vector<unsigned char> pinBytes;
        if (!opts.pinnedSpkiHex.empty() && HexToBytes(WideToUtf8(ToLower(opts.pinnedSpkiHex)), pinBytes) &&
            pinBytes.size() == 32) {
            pinOpt = "sha256//" + Base64Encode(pinBytes.data(), pinBytes.size());
            api.easy_setopt(curl, CURLOPT_PINNEDPUBLICKEY, pinOpt.c_str());
        } else if (requirePin) {
            if (t.file) fclose(t.file);
            api.easy_cleanup(curl);
            out.errorKind = "config";
            out.error = "pinned certificate is not a sha256 hex value";
            return out;
        }
    }

    CURLcode rc = api.easy_perform(curl);
    long status = 0;
    api.easy_getinfo(curl, CURLINFO_RESPONSE_CODE, &status);
    out.status = (int)status;
    curl_off_t contentLength = -1;
    api.easy_getinfo(curl, CURLINFO_CONTENT_LENGTH_DOWNLOAD_T, &contentLength);
    api.easy_cleanup(curl);
    if (t.file) {
        fflush(t.file);
        fsync(fileno(t.file));
        fclose(t.file);
    }

    if (rc == CURLE_SSL_PINNEDPUBKEYNOTMATCH) {
        out.errorKind = "pin";
        out.error = "certificate pin mismatch";
        return out;
    }
    if (t.cancelled || rc == CURLE_ABORTED_BY_CALLBACK) {
        out.errorKind = "cancel";
        out.error = "cancelled";
        return out;
    }
    if (t.tooLarge) {
        out.errorKind = "http";
        out.error = "response exceeds the maximum expected size";
        return out;
    }
    if (t.writeFailed) {
        out.errorKind = "network";
        out.error = "cannot write to disk";
        return out;
    }
    if (rc != CURLE_OK && status == 0) {
        bool tls = rc == CURLE_SSL_CONNECT_ERROR || rc == CURLE_PEER_FAILED_VERIFICATION ||
                   rc == CURLE_SSL_CACERT_BADFILE || rc == CURLE_SSL_CERTPROBLEM;
        out.errorKind = tls ? "tls" : "network";
        out.error = std::string("request failed (") + (errbuf[0] ? errbuf : api.easy_strerror(rc)) + ")";
        return out;
    }
    if (checkPin && requirePin) {
        // curl only gets here when the key matched.
        out.certPinHex = WideToUtf8(ToLower(opts.pinnedSpkiHex));
        out.pinChecked = true;
    }
    if (status == 416) {
        out.errorKind = "range";
        out.error = "server rejected the resume range";
        return out;
    }
    if (status != 200 && status != 206) {
        out.errorKind = "http";
        out.error = "HTTP " + std::to_string(status);
        return out;
    }
    if (opts.closedRange && status != 206) {
        out.errorKind = "range";
        out.error = "the server does not honour byte ranges (HTTP " + std::to_string(status) + ")";
        return out;
    }
    if (rc != CURLE_OK) {
        out.errorKind = "network";
        out.error = rc == CURLE_PARTIAL_FILE ? "response was truncated"
                                             : std::string("download interrupted (") +
                                                   (errbuf[0] ? errbuf : api.easy_strerror(rc)) + ")";
        return out;
    }
    out.resumed = opts.resumeFrom > 0 && status == 206;
    if (contentLength > 0 && t.received != (uint64_t)contentLength) {
        out.errorKind = "network";
        out.error = "response was truncated (" + std::to_string(t.received) + " of " +
                    std::to_string((uint64_t)contentLength) + " bytes)";
        return out;
    }
    out.bytesWritten = t.received;
    out.ok = true;
    return out;
}

}  // namespace

HttpOutcome HttpGetToString(const HttpRequestOptions& opts, std::string& bodyOut) {
    bodyOut.clear();
    return RunRequest(opts, nullptr, &bodyOut, true);
}

HttpOutcome HttpGetToFile(const HttpRequestOptions& opts, const std::wstring& destPath) {
    return RunRequest(opts, &destPath, nullptr, true);
}

// Bootstrapping a pin needs the raw certificate, which libcurl does not expose
// portably; operators run this helper with the Windows build.
HttpOutcome HttpProbeCertPin(const std::wstring&, std::string& pinHexOut) {
    pinHexOut.clear();
    HttpOutcome out;
    out.errorKind = "config";
    out.error = "certificate pin probing is only available in the Windows build";
    return out;
}

}  // namespace hpmmo
