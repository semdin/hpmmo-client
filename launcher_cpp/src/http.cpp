#include "http.h"

#include "common.h"
#include "sha256.h"

#include <windows.h>
#include <winhttp.h>
#include <wincrypt.h>

#include <fcntl.h>
#include <io.h>
#include <stdio.h>

#include <vector>

namespace hpmmo {

namespace {

struct UrlParts {
    std::wstring host;
    std::wstring path;  // path + query
    WORD port = 0;
};

bool ParseHttpsUrl(const std::wstring& url, UrlParts& out, std::string& err) {
    out = UrlParts{};
    URL_COMPONENTS uc = {};
    uc.dwStructSize = sizeof(uc);
    wchar_t host[256] = {0};
    wchar_t path[4096] = {0};
    uc.lpszHostName = host;
    uc.dwHostNameLength = 255;
    uc.lpszUrlPath = path;
    uc.dwUrlPathLength = 4095;
    if (!WinHttpCrackUrl(url.c_str(), (DWORD)url.size(), 0, &uc)) {
        err = "malformed URL";
        return false;
    }
    if (uc.nScheme != INTERNET_SCHEME_HTTPS) {
        err = "URL is not HTTPS";
        return false;
    }
    if (uc.lpszUserName && uc.dwUserNameLength > 0) {
        err = "credentials are not allowed in URLs";
        return false;
    }
    out.host.assign(host, uc.dwHostNameLength);
    out.path.assign(path, uc.dwUrlPathLength);
    if (out.path.empty()) out.path = L"/";
    out.port = uc.nPort;
    if (uc.dwExtraInfoLength > 0 && uc.lpszExtraInfo) {
        out.path.append(uc.lpszExtraInfo, uc.dwExtraInfoLength);
    }
    return true;
}

std::string QueryServerCertPin(HINTERNET hRequest, std::string& err) {
    PCCERT_CONTEXT cert = nullptr;
    DWORD size = sizeof(cert);
    if (!WinHttpQueryOption(hRequest, WINHTTP_OPTION_SERVER_CERT_CONTEXT, &cert, &size) || !cert) {
        err = "server certificate unavailable";
        return "";
    }
    // Hash the DER-encoded SubjectPublicKeyInfo exactly as Python's
    // cryptography.dump_public_key / OpenSSL would emit it.
    const CERT_PUBLIC_KEY_INFO& spki = cert->pCertInfo->SubjectPublicKeyInfo;
    DWORD derSize = 0;
    std::string pin;
    if (!CryptEncodeObjectEx(X509_ASN_ENCODING, X509_PUBLIC_KEY_INFO, &spki, 0, NULL, NULL,
                             &derSize)) {
        err = "cannot encode server public key";
        CertFreeCertificateContext(cert);
        return "";
    }
    std::vector<unsigned char> der(derSize);
    if (!CryptEncodeObjectEx(X509_ASN_ENCODING, X509_PUBLIC_KEY_INFO, &spki, 0, NULL, der.data(),
                             &derSize)) {
        err = "cannot encode server public key";
        CertFreeCertificateContext(cert);
        return "";
    }
    unsigned char digest[32];
    if (Sha256Buffer(der.data(), derSize, digest)) {
        pin = HexLower(digest, 32);
    } else {
        err = "cannot hash server public key";
    }
    CertFreeCertificateContext(cert);
    return pin;
}

struct RequestHandles {
    HINTERNET session = NULL;
    HINTERNET connect = NULL;
    HINTERNET request = NULL;
    ~RequestHandles() {
        if (request) WinHttpCloseHandle(request);
        if (connect) WinHttpCloseHandle(connect);
        if (session) WinHttpCloseHandle(session);
    }
};

}  // namespace

static HttpOutcome RunRequest(const HttpRequestOptions& opts, std::wstring* destFile,
                              std::string* bodyOut, bool requirePin, bool readBody,
                              uint64_t* outExpectedTotal) {
    HttpOutcome out;
    UrlParts parts;
    if (!ParseHttpsUrl(opts.url, parts, out.error)) {
        out.errorKind = "config";
        return out;
    }
    if (requirePin && opts.pinnedSpkiHex.empty()) {
        out.errorKind = "config";
        out.error = "no pinned certificate configured";
        return out;
    }

    RequestHandles h;
    h.session = WinHttpOpen(L"HPMMO_Launcher/2.0", WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                            WINHTTP_NO_PROXY_NAME, WINHTTP_NO_PROXY_BYPASS, 0);
    if (!h.session) {
        out.errorKind = "network";
        out.error = "WinHttpOpen failed (" + std::to_string(GetLastError()) + ")";
        return out;
    }
    WinHttpSetTimeouts(h.session, 10000, 10000, 30000, opts.receiveTimeoutMs);

    h.connect = WinHttpConnect(h.session, parts.host.c_str(), parts.port, 0);
    if (!h.connect) {
        out.errorKind = "network";
        out.error = "cannot connect to host (" + std::to_string(GetLastError()) + ")";
        return out;
    }
    h.request = WinHttpOpenRequest(h.connect, L"GET", parts.path.c_str(), NULL,
                                   WINHTTP_NO_REFERER, WINHTTP_DEFAULT_ACCEPT_TYPES,
                                   WINHTTP_FLAG_SECURE);
    if (!h.request) {
        out.errorKind = "network";
        out.error = "cannot create request (" + std::to_string(GetLastError()) + ")";
        return out;
    }

    // Certificate handling: the pinned SPKI is the authentication decision, so
    // chain/name/expiry errors are tolerated and then replaced by an exact pin
    // comparison. Without a pin we refuse to talk to the server at all.
    DWORD secFlags = SECURITY_FLAG_IGNORE_UNKNOWN_CA | SECURITY_FLAG_IGNORE_CERT_CN_INVALID |
                     SECURITY_FLAG_IGNORE_CERT_DATE_INVALID |
                     SECURITY_FLAG_IGNORE_CERT_WRONG_USAGE;
    WinHttpSetOption(h.request, WINHTTP_OPTION_SECURITY_FLAGS, &secFlags, sizeof(secFlags));

    std::wstring headers;
    if (opts.resumeFrom > 0) {
        headers = L"Range: bytes=" + std::to_wstring(opts.resumeFrom) + L"-\r\n";
    }
    if (!WinHttpSendRequest(h.request, headers.empty() ? WINHTTP_NO_ADDITIONAL_HEADERS : headers.c_str(),
                            headers.empty() ? 0 : (DWORD)-1L, WINHTTP_NO_REQUEST_DATA, 0, 0, 0)) {
        DWORD e = GetLastError();
        out.errorKind = (e == ERROR_WINHTTP_SECURE_FAILURE) ? "tls" : "network";
        out.error = "request failed (" + std::to_string(e) + ")";
        return out;
    }
    if (!WinHttpReceiveResponse(h.request, NULL)) {
        DWORD e = GetLastError();
        out.errorKind = (e == ERROR_WINHTTP_SECURE_FAILURE) ? "tls" : "network";
        out.error = "no response (" + std::to_string(e) + ")";
        return out;
    }

    DWORD status = 0, size = sizeof(status);
    WinHttpQueryHeaders(h.request, WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                        WINHTTP_HEADER_NAME_BY_INDEX, &status, &size, WINHTTP_NO_HEADER_INDEX);
    out.status = (int)status;

    // Pin check before reading any body bytes.
    std::string pinErr;
    std::string observed = QueryServerCertPin(h.request, pinErr);
    out.certPinHex = observed;
    if (observed.empty()) {
        out.errorKind = "pin";
        out.error = pinErr;
        return out;
    }
    if (requirePin) {
        std::wstring expected = ToLower(opts.pinnedSpkiHex);
        if (expected != Utf8ToWide(observed)) {
            out.errorKind = "pin";
            out.error = "certificate pin mismatch (expected " + WideToUtf8(expected).substr(0, 16) +
                        "..., got " + observed.substr(0, 16) + "...)";
            return out;
        }
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
    if (!destFile && !bodyOut) {
        // Probe mode: the pin is the only piece of information we need.
        out.ok = true;
        return out;
    }
    out.resumed = (opts.resumeFrom > 0 && status == 206);
    uint64_t effectiveResume = out.resumed ? opts.resumeFrom : 0;

    // Content-Length (informational; the hash check is authoritative).
    uint64_t contentLength = 0;
    {
        DWORD lenSize = sizeof(contentLength);
        WinHttpQueryHeaders(h.request, WINHTTP_QUERY_CONTENT_LENGTH | WINHTTP_QUERY_FLAG_NUMBER,
                            WINHTTP_HEADER_NAME_BY_INDEX, &contentLength, &lenSize,
                            WINHTTP_NO_HEADER_INDEX);
    }
    if (outExpectedTotal) {
        *outExpectedTotal = contentLength ? contentLength + effectiveResume : 0;
    }

    FILE* f = nullptr;
    if (destFile) {
        f = _wfopen(destFile->c_str(), out.resumed ? L"ab" : L"wb");
        if (!f) {
            out.errorKind = "network";
            out.error = "cannot open destination file";
            return out;
        }
        if (!out.resumed) {
            // Truncate any stale partial data.
            _chsize_s(_fileno(f), 0);
        }
    }

    std::vector<unsigned char> buf(256 * 1024);
    uint64_t received = 0;
    bool failed = false;
    while (true) {
        DWORD avail = 0;
        if (!WinHttpQueryDataAvailable(h.request, &avail)) {
            out.errorKind = "network";
            out.error = "connection lost before the response completed";
            failed = true;
            break;
        }
        if (avail == 0) break;
        DWORD want = (DWORD)(avail > buf.size() ? buf.size() : avail);
        DWORD got = 0;
        if (!WinHttpReadData(h.request, buf.data(), want, &got)) {
            out.errorKind = "network";
            out.error = "download interrupted (" + std::to_string(GetLastError()) + ")";
            failed = true;
            break;
        }
        if (got == 0) break;
        received += got;
        if (f) {
            if (fwrite(buf.data(), 1, got, f) != got) {
                out.errorKind = "network";
                out.error = "cannot write to disk";
                failed = true;
                break;
            }
        }
        if (bodyOut) {
            if (bodyOut->size() + got > opts.maxBodyBytes) {
                out.errorKind = "http";
                out.error = "response exceeds the maximum expected size";
                failed = true;
                break;
            }
            bodyOut->append((const char*)buf.data(), got);
        }
        if (opts.progress &&
            !opts.progress(received + effectiveResume, contentLength ? contentLength + effectiveResume : 0)) {
            out.errorKind = "cancel";
            out.error = "cancelled";
            failed = true;
            break;
        }
    }
    if (f) {
        fflush(f);
        _commit(_fileno(f));
        fclose(f);
    }
    if (failed) return out;

    if (contentLength && received != contentLength) {
        out.errorKind = "network";
        out.error = "response was truncated (" + std::to_string(received) + " of " +
                    std::to_string(contentLength) + " bytes)";
        return out;
    }
    out.bytesWritten = received;
    out.ok = true;
    return out;
}

HttpOutcome HttpGetToString(const HttpRequestOptions& opts, std::string& bodyOut) {
    bodyOut.clear();
    return RunRequest(opts, nullptr, &bodyOut, true, true, nullptr);
}

HttpOutcome HttpGetToFile(const HttpRequestOptions& opts, const std::wstring& destPath) {
    std::wstring path = destPath;
    return RunRequest(opts, &path, nullptr, true, false, nullptr);
}

HttpOutcome HttpProbeCertPin(const std::wstring& url, std::string& pinHexOut) {
    pinHexOut.clear();
    HttpRequestOptions opts;
    opts.url = url;
    HttpOutcome out = RunRequest(opts, nullptr, nullptr, false, false, nullptr);
    pinHexOut = out.certPinHex;
    if (out.certPinHex.empty()) {
        out.ok = false;
        if (out.error.empty()) out.error = "no certificate observed";
    } else {
        out.ok = true;
    }
    return out;
}

}  // namespace hpmmo
