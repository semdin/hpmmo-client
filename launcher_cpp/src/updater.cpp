#include "updater.h"

#include "http.h"
#include "sha256.h"
#include "zip.h"

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <map>
#include <thread>

extern "C" {
#include "ed25519.h"
}

namespace hpmmo {

namespace {

constexpr uint64_t kSpaceSlack = 64ull * 1024 * 1024;
constexpr size_t kMaxManifestBytes = 8u * 1024 * 1024;
constexpr size_t kMaxSignatureBytes = 4096;
constexpr size_t kMaxStatusBytes = 1u * 1024 * 1024;
constexpr int kDocAttempts = 3;
constexpr int kDownloadAttempts = 3;

std::string ToLowerAscii(const std::string& s) {
    std::string out = s;
    for (auto& c : out) c = (char)tolower((unsigned char)c);
    return out;
}

std::string ToLowerString(const std::string& s) { return ToLowerAscii(s); }

std::wstring ResolveInstallRoot(const CliOptions& cli, const AppConfig& cfg) {
    if (!cli.installRoot.empty()) return NormalizePath(cli.installRoot);
    if (!cfg.installRoot.empty()) return NormalizePath(cfg.installRoot);
    return NormalizePath(GetExeDir());
}

std::string JoinUrlBase(const std::wstring& baseIn, const std::string& rel) {
    if (rel.rfind("https://", 0) == 0 || rel.rfind("http://", 0) == 0) return rel;
    std::wstring base = baseIn;
    while (!base.empty() && (base.back() == L'/' || base.back() == L'\\')) base.pop_back();
    if (rel.empty()) return WideToUtf8(base);
    if (rel[0] == '/') {
        size_t scheme = base.find(L"://");
        size_t hostEnd = base.find(L'/', scheme == std::wstring::npos ? 0 : scheme + 3);
        std::wstring origin = hostEnd == std::wstring::npos ? base : base.substr(0, hostEnd);
        return WideToUtf8(origin) + rel;
    }
    return WideToUtf8(base) + "/" + rel;
}

std::string UrlExt(const std::string& url) {
    std::string path = url;
    size_t q = path.find_first_of("?#");
    if (q != std::string::npos) path = path.substr(0, q);
    size_t slash = path.find_last_of('/');
    std::string name = slash == std::string::npos ? path : path.substr(slash + 1);
    size_t dot = name.find_last_of('.');
    if (dot == std::string::npos || dot + 1 >= name.size()) return "";
    std::string ext = name.substr(dot + 1);
    if (ext.size() > 8) return "";
    for (char c : ext)
        if (!isalnum((unsigned char)c)) return "";
    return "." + ext;
}

bool IsZeroKey(const std::vector<unsigned char>& key) {
    for (auto b : key)
        if (b != 0) return false;
    return true;
}

bool SleepCancellable(std::atomic<bool>* cancel, int ms) {
    for (int waited = 0; waited < ms; waited += 100) {
        if (cancel && cancel->load()) return false;
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }
    return !(cancel && cancel->load());
}

bool LoadCurrentImpl(UpdaterContext& ctx, InstalledState& out);

// ------------------------------------------------------------------ context --

UpdaterContext MakeContext(const CliOptions& cli, AppConfig cfg) {
    UpdaterContext ctx;
    ctx.cli = cli;
    if (cli.channel.empty() && !cfg.releaseChannel.empty()) ctx.cli.channel = cfg.releaseChannel;
    ctx.cfg = cfg;
    ctx.paths.installRoot = ResolveInstallRoot(cli, cfg);
    ctx.paths.versionsDir = JoinPath(ctx.paths.installRoot, L"versions");
    ctx.paths.stagingDir = JoinPath(ctx.paths.installRoot, L"staging");
    ctx.paths.currentFile = JoinPath(ctx.paths.installRoot, L"current.json");
    ctx.paths.journalFile = JoinPath(ctx.paths.installRoot, L"pending_activation.json");
    ctx.paths.stateFile = JoinPath(ctx.paths.installRoot, L"launcher_state.json");
    ctx.paths.logFile = JoinPath(ctx.paths.installRoot, L"launcher.log");
    std::wstring userDir = !cli.userDataDir.empty() ? cli.userDataDir : cfg.userDataDir;
    ctx.paths.userDir = userDir.empty() ? JoinPath(ctx.paths.installRoot, L"user")
                                        : NormalizePath(userDir);
    ctx.releaseBase = !cli.releaseBase.empty() ? cli.releaseBase : cfg.releaseBaseUrl;
    ctx.statusUrl = !cli.statusUrl.empty() ? cli.statusUrl : cfg.statusUrl;
    if (ctx.statusUrl.empty() && !ctx.releaseBase.empty()) {
        ctx.statusUrl = Utf8ToWide(JoinUrlBase(ctx.releaseBase, "status.json"));
    }
    ctx.pinnedSpkiHex = ToLower(!cli.pinnedSpkiHex.empty() ? cli.pinnedSpkiHex : cfg.pinnedSpkiSha256);
    ctx.stagingQuotaBytes =
        cli.stagingQuota > 0 ? cli.stagingQuota : cfg.stagingQuotaBytes;
    ctx.pinnedKeyB64 = !cli.publicKeyB64.empty() ? WideToUtf8(cli.publicKeyB64)
                                                 : WideToUtf8(cfg.releasePublicKey);
    ctx.keyId = !cli.publicKeyId.empty() ? WideToUtf8(cli.publicKeyId)
               : !cfg.releasePublicKeyId.empty() ? WideToUtf8(cfg.releasePublicKeyId)
                                                 : kDefaultPinnedKeyId;
    // Resolve the active game executable.
    InstalledState cur;
    cur.present = false;
    if (LoadCurrentImpl(ctx, cur) && cur.present) {
        const wchar_t* candidates[] = {L"HPMMO.exe", L"HPMMO_Game.exe", L"game.exe", L"godot.exe"};
        if (!cfg.gameExeName.empty()) {
            std::wstring p = JoinPath(cur.dir, cfg.gameExeName);
            if (FileExists(p)) ctx.paths.gameExe = p;
        }
        if (ctx.paths.gameExe.empty()) {
            for (const wchar_t* c : candidates) {
                std::wstring p = JoinPath(cur.dir, c);
                if (FileExists(p)) {
                    ctx.paths.gameExe = p;
                    break;
                }
            }
        }
    }
    SetLogPath(ctx.paths.logFile);
    return ctx;
}

// ------------------------------------------------------------- manifest IO --

bool ParseArtifact(const JsonValue& v, Artifact& out);

bool ParseManifest(const std::string& raw, ReleaseManifest& m, std::string& err) {
    JsonValue root;
    if (!JsonValue::Parse(raw, root, err) || !root.isObject()) {
        err = err.empty() ? "manifest is not a JSON object" : ("manifest: " + err);
        return false;
    }
    m.channel = root.str("channel");
    m.clientVersion = root.str("client_version");
    m.minLauncherVersion = root.str("min_launcher_version");
    m.protocolVersion = root.str("protocol_version");
    m.protocolMin = root.str("protocol_min");
    m.protocolMax = root.str("protocol_max");
    m.contentVersion = root.str("content_version");
    m.contentSha256 = ToLowerString(root.str("content_sha256"));
    m.serverVersion = root.str("server_version");
    m.schemaVersion = root.str("schema_version");
    m.platform = root.str("platform");
    m.publishedAt = root.str("published_at");
    m.releaseNotes = root.str("release_notes");
    if (m.clientVersion.empty()) {
        err = "manifest is missing client_version";
        return false;
    }
    const auto* arts = root.arr("artifacts");
    if (!arts || arts->empty()) {
        err = "manifest has no artifacts";
        return false;
    }
    for (const auto& v : *arts) {
        Artifact a;
        if (!ParseArtifact(v, a)) {
            err = "manifest contains a malformed artifact entry";
            return false;
        }
        m.artifacts.push_back(a);
    }
    m.raw = raw;
    m.sha256 = Sha256Hex(raw.data(), raw.size());
    return true;
}

bool ParseArtifact(const JsonValue& v, Artifact& out) {
    if (!v.isObject()) return false;
    out.kind = v.str("kind");
    out.fromVersion = v.str("from_version", "");
    out.url = v.str("url");
    out.sha256 = ToLowerString(v.str("sha256"));
    out.size = (uint64_t)v.i64("size", 0);
    return !out.url.empty() && out.sha256.size() == 64;
}

bool VerifyManifestSignature(const std::string& keyB64, const std::string& raw,
                             const std::string& sigB64, std::string& err) {
    std::vector<unsigned char> key, sig;
    if (!Base64Decode(keyB64, key) || key.size() != 32 || IsZeroKey(key)) {
        err = "pinned release public key is missing or malformed";
        return false;
    }
    if (!Base64Decode(sigB64, sig) || sig.size() != 64) {
        err = "manifest signature is malformed";
        return false;
    }
    if (ed25519_verify(sig.data(), (const unsigned char*)raw.data(), raw.size(), key.data()) != 1) {
        err = "manifest signature verification failed";
        return false;
    }
    return true;
}

struct DocFetch {
    bool ok = false;
    std::string error;
    std::string kind;
    int status = 0;
};

DocFetch FetchDoc(UpdaterContext& ctx, const std::wstring& url, std::string& body, size_t maxBytes,
                  bool retry) {
    DocFetch res;
    int attempts = retry ? kDocAttempts : 1;
    for (int i = 0; i < attempts; i++) {
        if (ctx.cancel && ctx.cancel->load()) {
            res.kind = "cancel";
            res.error = "cancelled";
            return res;
        }
        HttpRequestOptions opts;
        opts.url = url;
        opts.pinnedSpkiHex = ctx.pinnedSpkiHex;
        opts.maxBodyBytes = maxBytes;
        HttpOutcome out = HttpGetToString(opts, body);
        res.status = out.status;
        if (out.ok) {
            res.ok = true;
            return res;
        }
        res.kind = out.errorKind;
        res.error = out.error;
        if (out.errorKind == "pin" || out.errorKind == "config" || out.errorKind == "cancel" ||
            out.errorKind == "http" || out.errorKind == "tls") {
            return res;
        }
        if (i + 1 < attempts && !SleepCancellable(ctx.cancel, 400 * (2 << i))) {
            res.kind = "cancel";
            res.error = "cancelled";
            return res;
        }
    }
    return res;
}

int CodeForDocError(const DocFetch& f) {
    if (f.kind == "pin" || f.kind == "tls") return kExitSignature;
    if (f.kind == "config") return kExitConfig;
    if (f.kind == "cancel") return kExitCancelled;
    return kExitNetwork;
}

bool FetchManifest(UpdaterContext& ctx, ReleaseManifest& m, std::string& message, int& code) {
    std::wstring url = Utf8ToWide(JoinUrlBase(ctx.releaseBase, "manifest.json"));
    std::string body;
    DocFetch f = FetchDoc(ctx, url, body, kMaxManifestBytes, true);
    if (!f.ok) {
        message = "manifest fetch failed: " + f.error;
        code = CodeForDocError(f);
        return false;
    }
    std::wstring sigUrl = Utf8ToWide(JoinUrlBase(ctx.releaseBase, "manifest.json.sig"));
    std::string sigBody;
    DocFetch sf = FetchDoc(ctx, sigUrl, sigBody, kMaxSignatureBytes, true);
    if (!sf.ok) {
        message = "manifest signature fetch failed: " + sf.error;
        code = CodeForDocError(sf);
        return false;
    }
    std::string err;
    if (!VerifyManifestSignature(ctx.pinnedKeyB64, body, Trim(sigBody), err)) {
        message = err;
        code = (err.find("public key") != std::string::npos) ? kExitConfig : kExitSignature;
        LogMsg("[Updater] " + err + " (key id " + ctx.keyId + ")");
        return false;
    }
    if (!ParseManifest(body, m, err)) {
        message = err;
        code = kExitIntegrity;
        return false;
    }
    if (!ctx.cli.channel.empty() && !m.channel.empty() &&
        ToLowerAscii(m.channel) != WideToUtf8(ToLower(ctx.cli.channel))) {
        message = "release channel mismatch: manifest is '" + m.channel + "', expected '" +
                  WideToUtf8(ctx.cli.channel) + "'";
        code = kExitConfig;
        return false;
    }
    if (!m.platform.empty() && ToLowerAscii(m.platform).find("win") == std::string::npos) {
        message = "release platform '" + m.platform + "' is not Windows";
        code = kExitProtocol;
        return false;
    }
    return true;
}

bool FetchStatus(UpdaterContext& ctx, StatusDoc& st, std::string& message) {
    if (ctx.statusUrl.empty()) {
        message = "no status URL configured";
        st.state = "UNKNOWN";
        return false;
    }
    std::string body;
    DocFetch f = FetchDoc(ctx, ctx.statusUrl, body, kMaxStatusBytes, true);
    if (!f.ok) {
        message = "status fetch failed: " + f.error;
        st.state = "OFFLINE";
        return false;
    }
    JsonValue root;
    std::string err;
    if (!JsonValue::Parse(body, root, err) || !root.isObject()) {
        message = "status document: " + err;
        st.state = "UNKNOWN";
        return false;
    }
    st.state = root.str("state", "UNKNOWN");
    for (auto& c : st.state) c = (char)toupper((unsigned char)c);
    st.release = root.str("release");
    st.previousRelease = root.str("previous_release");
    st.since = root.str("since");
    st.message = root.str("message");
    st.until = root.str("until");
    st.protocolVersion = root.str("protocol_version");
    return true;
}

// ------------------------------------------------------------ install state --

bool LoadCurrentImpl(UpdaterContext& ctx, InstalledState& out) {
    out = InstalledState{};
    if (!FileExists(ctx.paths.currentFile)) return true;
    std::string bytes;
    if (!ReadFileBytes(ctx.paths.currentFile, bytes, 1u << 20)) {
        LogMsg("[Updater] cannot read current.json");
        return false;
    }
    JsonValue root;
    std::string err;
    if (!JsonValue::Parse(bytes, root, err)) {
        LogMsg("[Updater] current.json is corrupt: " + err);
        return false;
    }
    out.present = true;
    out.version = root.str("version");
    out.previous = root.str("previous");
    out.activatedAt = root.str("activated_at");
    out.manifestSha256 = root.str("manifest_sha256");
    std::wstring rel = Utf8ToWide(root.str("dir"));
    out.dir = NormalizePath(JoinPath(ctx.paths.installRoot, rel));
    if (!PathStartsWithCI(out.dir, ctx.paths.versionsDir)) {
        LogMsg("[Updater] current.json points outside the versions directory");
        out.present = false;
        return false;
    }
    return true;
}

bool LoadInstallRecord(const std::wstring& versionDir, JsonValue& record, std::string& err) {
    std::wstring path = JoinPath(versionDir, L".install-record.json");
    if (!FileExists(path)) {
        err = "install record is missing";
        return false;
    }
    std::string bytes;
    if (!ReadFileBytes(path, bytes, 16u << 20)) {
        err = "install record is unreadable";
        return false;
    }
    if (!JsonValue::Parse(bytes, record, err) || !record.isObject()) {
        err = "install record is corrupt";
        return false;
    }
    return true;
}

struct VerifyResult {
    uint64_t checked = 0;
    uint64_t bytes = 0;
    std::vector<std::string> missing;
    std::vector<std::string> corrupt;
};

bool VerifyInstallFiles(const std::wstring& versionDir, const JsonValue& record, VerifyResult& out,
                        std::string& err) {
    const auto* files = record.arr("files");
    if (!files) {
        err = "install record has no file list";
        return false;
    }
    for (const auto& f : *files) {
        std::string rel = f.str("path");
        std::string want = ToLowerString(f.str("sha256"));
        int64_t wantSize = f.i64("size", -1);
        if (rel.empty() || want.size() != 64) {
            err = "install record contains a malformed file entry";
            return false;
        }
        std::string norm = rel;
        for (auto& c : norm)
            if (c == '\\') c = '/';
        if (norm[0] == '/' || norm.find("..") != std::string::npos ||
            (norm.size() >= 2 && norm[1] == ':')) {
            err = "install record contains an unsafe path";
            return false;
        }
        std::wstring wide = Utf8ToWide(norm);
        for (auto& c : wide)
            if (c == L'/') c = L'\\';
        std::wstring full = JoinPath(versionDir, wide);
        out.checked++;
        if (!FileExists(full)) {
            out.missing.push_back(norm);
            continue;
        }
        uint64_t size = FileSizeOrZero(full);
        if (wantSize >= 0 && size != (uint64_t)wantSize) {
            out.corrupt.push_back(norm);
            continue;
        }
        if (Sha256FileHex(full) != want) {
            out.corrupt.push_back(norm);
            continue;
        }
        out.bytes += size;
    }
    return true;
}

// ---------------------------------------------------------------- selection --

bool IsLauncherArtifact(const Artifact& a) { return a.kind == "launcher"; }

bool SelectInstallArtifact(const ReleaseManifest& m, const std::string& installedVersion,
                           Artifact& out, std::string& why) {
    const Artifact* best = nullptr;
    const Artifact* fallback = nullptr;
    for (const auto& a : m.artifacts) {
        if (IsLauncherArtifact(a)) continue;
        bool exact = !installedVersion.empty() && a.fromVersion == installedVersion;
        bool full = a.fromVersion.empty() || a.fromVersion == "any" || a.fromVersion == "*";
        if (exact) {
            best = &a;
            break;
        }
        if (full && !fallback) fallback = &a;
    }
    const Artifact* chosen = best ? best : fallback;
    if (!chosen) {
        why = installedVersion.empty()
                  ? "manifest has no full client package"
                  : "manifest has no package for installed version " + installedVersion +
                        " (only deltas for other versions)";
        return false;
    }
    out = *chosen;
    return true;
}

bool SelectLauncherArtifact(const ReleaseManifest& m, Artifact& out) {
    for (const auto& a : m.artifacts) {
        if (IsLauncherArtifact(a)) {
            out = a;
            return true;
        }
    }
    return false;
}

// -------------------------------------------------------------- protocol ----

std::string EffectiveServerProtocol(const ReleaseManifest& m, const StatusDoc& st) {
    if (!st.protocolVersion.empty()) return st.protocolVersion;
    return m.protocolVersion;
}

bool ProtocolCompatible(const ReleaseManifest& m, const StatusDoc& st, std::string& serverProto,
                        std::string& reason) {
    serverProto = EffectiveServerProtocol(m, st);
    if (serverProto.empty()) return true;
    std::string lo = m.protocolMin.empty() ? serverProto : m.protocolMin;
    std::string hi = m.protocolMax.empty() ? serverProto : m.protocolMax;
    if (!IsVersionString(serverProto) || !IsVersionString(lo) || !IsVersionString(hi)) {
        return true;
    }
    if (CompareVersions(serverProto, lo) < 0 || CompareVersions(serverProto, hi) > 0) {
        reason = "server protocol " + serverProto + " is outside this client's supported range [" +
                 lo + ", " + hi + "]";
        return false;
    }
    return true;
}

// ---------------------------------------------------------------- download --

bool CheckDiskSpace(UpdaterContext& ctx, uint64_t required, std::string& message) {
    uint64_t freeBytes = FreeDiskSpaceBytes(ctx.paths.installRoot);
    uint64_t available = freeBytes;
    if (ctx.stagingQuotaBytes > 0) {
        uint64_t used = DirSizeBytes(ctx.paths.stagingDir);
        uint64_t quotaLeft = ctx.stagingQuotaBytes > used ? ctx.stagingQuotaBytes - used : 0;
        available = std::min(available, quotaLeft);
    }
    if (required > available) {
        message = "insufficient disk space: need " + FormatU64(required) + " bytes, " +
                  FormatU64(available) + " available (disk free " + FormatU64(freeBytes) +
                  (ctx.stagingQuotaBytes ? ", staging quota " + FormatU64(ctx.stagingQuotaBytes)
                                         : "") +
                  ")";
        return false;
    }
    return true;
}

void ReportProgress(UpdaterContext& ctx, const wchar_t* phase, uint64_t done, uint64_t total) {
    if (!ctx.status) return;
    static int lastPct = -1;
    int pct = total ? (int)((done * 100) / total) : -1;
    if (pct == lastPct && pct != 100) return;
    lastPct = pct;
    std::wstring text = phase;
    if (pct >= 0) {
        text += L": %" + std::to_wstring(pct) + L" (" + FormatBytesW(done) + L" / " +
                FormatBytesW(total) + L")";
    }
    ctx.status(text);
}

bool DownloadArtifact(UpdaterContext& ctx, const Artifact& art, std::wstring& finalPath,
                      std::string& message, int& code) {
    std::string sha8 = art.sha256.substr(0, 8);
    std::string name =
        (art.kind.empty() ? "package" : art.kind) + std::string("-") + sha8 + UrlExt(art.url);
    finalPath = JoinPath(ctx.paths.stagingDir, Utf8ToWide(name));
    std::wstring partPath = finalPath + L".part";
    CreateDirs(ctx.paths.stagingDir);

    if (FileExists(finalPath)) {
        uint64_t size = FileSizeOrZero(finalPath);
        if (size == art.size && Sha256FileHex(finalPath) == art.sha256) {
            LogMsg("[Updater] artifact already downloaded: " + name);
            return true;
        }
        DeleteFileQuiet(finalPath);
    }

    std::wstring url = Utf8ToWide(JoinUrlBase(ctx.releaseBase, art.url));
    for (int attempt = 0; attempt < kDownloadAttempts; attempt++) {
        if (ctx.cancel && ctx.cancel->load()) {
            message = "cancelled";
            code = kExitCancelled;
            return false;
        }
        uint64_t have = FileSizeOrZero(partPath);
        if (have > art.size) {
            DeleteFileQuiet(partPath);
            have = 0;
        }
        if (have == art.size) {
            if (Sha256FileHex(partPath) == art.sha256) {
                if (!MoveFileExW(partPath.c_str(), finalPath.c_str(), MOVEFILE_REPLACE_EXISTING)) {
                    message = "cannot finalize the downloaded package";
                    code = kExitIntegrity;
                    return false;
                }
                return true;
            }
            DeleteFileQuiet(partPath);
            have = 0;
        }

        uint64_t remaining = art.size - have;
        std::string spaceMsg;
        if (!CheckDiskSpace(ctx, remaining + kSpaceSlack, spaceMsg)) {
            message = spaceMsg;
            code = kExitDiskSpace;
            return false;
        }

        HttpRequestOptions opts;
        opts.url = url;
        opts.resumeFrom = have;
        opts.pinnedSpkiHex = ctx.pinnedSpkiHex;
        opts.progress = [&](uint64_t done, uint64_t total) {
            if (ctx.cancel && ctx.cancel->load()) return false;
            ReportProgress(ctx, L"Downloading", done, art.size);
            (void)total;
            return true;
        };
        HttpOutcome out = HttpGetToFile(opts, partPath);
        if (out.ok) {
            uint64_t size = FileSizeOrZero(partPath);
            if (size != art.size) {
                message = "downloaded size mismatch: expected " + FormatU64(art.size) + ", got " +
                          FormatU64(size);
                DeleteFileQuiet(partPath);
                code = kExitIntegrity;
                return false;
            }
            std::string got = Sha256FileHex(partPath);
            if (got != art.sha256) {
                message = "downloaded package hash mismatch (expected " + art.sha256.substr(0, 16) +
                          "..., got " + got.substr(0, 16) + "...)";
                DeleteFileQuiet(partPath);
                code = kExitIntegrity;
                return false;
            }
            if (!MoveFileExW(partPath.c_str(), finalPath.c_str(), MOVEFILE_REPLACE_EXISTING)) {
                message = "cannot finalize the downloaded package";
                code = kExitIntegrity;
                return false;
            }
            return true;
        }

        if (out.errorKind == "cancel") {
            message = "cancelled";
            code = kExitCancelled;
            return false;
        }
        if (out.errorKind == "pin" || out.errorKind == "tls" || out.errorKind == "config") {
            message = "download rejected: " + out.error;
            code = (out.errorKind == "pin" || out.errorKind == "tls") ? kExitSignature : kExitConfig;
            return false;
        }
        if (out.errorKind == "range") {
            DeleteFileQuiet(partPath);
            message = out.error;
            code = kExitDownload;
            continue;
        }
        if (out.errorKind == "http") {
            message = "download failed: " + out.error;
            code = kExitDownload;
            return false;
        }
        message = "download interrupted: " + out.error;
        code = kExitDownload;
        if (attempt + 1 < kDownloadAttempts) {
            LogMsg("[Updater] retry " + std::to_string(attempt + 1) + ": " + message);
            if (!SleepCancellable(ctx.cancel, 500 * (2 << attempt))) {
                message = "cancelled";
                code = kExitCancelled;
                return false;
            }
        }
    }
    return false;
}

// ----------------------------------------------------------------- staging --

JsonValue ArtifactJson(const Artifact& a) {
    JsonValue v = JsonValue::Obj();
    v.set("kind", JsonValue::Str(a.kind));
    v.set("from_version", JsonValue::Str(a.fromVersion));
    v.set("url", JsonValue::Str(a.url));
    v.set("sha256", JsonValue::Str(a.sha256));
    v.set("size", JsonValue::Int((int64_t)a.size));
    return v;
}

std::string BuildRecordJson(const std::string& version, const ReleaseManifest& m,
                            const Artifact& art, const std::vector<ExtractedFile>& files) {
    JsonValue rec = JsonValue::Obj();
    rec.set("version", JsonValue::Str(version));
    rec.set("manifest_sha256", JsonValue::Str(m.sha256));
    rec.set("installed_at", JsonValue::Str(TimeNowIso8601Utc()));
    rec.set("protocol_version", JsonValue::Str(m.protocolVersion));
    rec.set("protocol_min", JsonValue::Str(m.protocolMin));
    rec.set("protocol_max", JsonValue::Str(m.protocolMax));
    rec.set("content_version", JsonValue::Str(m.contentVersion));
    rec.set("content_sha256", JsonValue::Str(m.contentSha256));
    JsonValue arts = JsonValue::Arr();
    arts.push(ArtifactJson(art));
    rec.set("artifacts", arts);

    std::map<std::string, const ExtractedFile*> byPath;
    for (const auto& f : files) byPath[f.relPath] = &f;
    JsonValue arr = JsonValue::Arr();
    for (const auto& kv : byPath) {
        JsonValue jf = JsonValue::Obj();
        jf.set("path", JsonValue::Str(kv.second->relPath));
        jf.set("size", JsonValue::Int((int64_t)kv.second->size));
        jf.set("sha256", JsonValue::Str(kv.second->sha256));
        arr.push(jf);
    }
    rec.set("files", arr);
    return rec.Dump() + "\n";
}

bool WriteJournal(UpdaterContext& ctx, const std::string& version, const std::wstring& stagedDir,
                  const std::string& previous, const std::string& manifestSha) {
    JsonValue j = JsonValue::Obj();
    j.set("target_version", JsonValue::Str(version));
    j.set("staged_dir", JsonValue::Str(WideToUtf8(stagedDir)));
    j.set("previous", JsonValue::Str(previous));
    j.set("manifest_sha256", JsonValue::Str(manifestSha));
    j.set("created_at", JsonValue::Str(TimeNowIso8601Utc()));
    if (!WriteFileAtomic(ctx.paths.journalFile, j.Dump() + "\n")) {
        LogMsg("[Updater] cannot write activation journal");
        return false;
    }
    return true;
}

bool IsGameRunningNowImpl(const UpdaterPaths& paths, const AppConfig& cfg,
                          std::vector<RunningProcess>* matches) {
    std::vector<std::wstring> names = cfg.gameProcessNames;
    if (!cfg.gameExeName.empty()) names.push_back(cfg.gameExeName);
    return IsGameRunning(paths.installRoot, names, matches);
}

bool ActivateFromStaged(UpdaterContext& ctx, const std::string& version,
                        const std::wstring& stagedDir, const std::string& previous,
                        const std::string& manifestSha, std::string& message, int& code) {
    std::vector<RunningProcess> running;
    if (IsGameRunningNowImpl(ctx.paths, ctx.cfg, &running)) {
        message = "the game is running (PID " +
                  std::to_string(running.empty() ? 0 : running[0].pid) +
                  "); close it before activating";
        code = kExitGameRunning;
        return false;
    }
    std::wstring finalDir = JoinPath(ctx.paths.versionsDir, Utf8ToWide(version));
    if (NormalizePath(stagedDir) != NormalizePath(finalDir)) {
        if (DirExists(finalDir)) {
            JsonValue rec;
            std::string err;
            VerifyResult vr;
            bool healthy = LoadInstallRecord(finalDir, rec, err) &&
                           VerifyInstallFiles(finalDir, rec, vr, err) && vr.missing.empty() &&
                           vr.corrupt.empty();
            if (!healthy) {
                LogMsg("[Updater] removing unhealthy existing version dir: " + WideToUtf8(finalDir));
                if (!RemoveDirRecursive(finalDir)) {
                    message = "cannot replace the existing version directory";
                    code = kExitIntegrity;
                    return false;
                }
            }
        }
        if (DirExists(finalDir)) {
            RemoveDirRecursive(stagedDir);
        } else if (!MoveFileExW(stagedDir.c_str(), finalDir.c_str(), 0)) {
            message = "cannot move the staged install into place (error " +
                      std::to_string(GetLastError()) + ")";
            code = kExitIntegrity;
            return false;
        }
    }
    JsonValue cur = JsonValue::Obj();
    cur.set("version", JsonValue::Str(version));
    cur.set("dir", JsonValue::Str("versions/" + version));
    cur.set("previous", JsonValue::Str(previous));
    cur.set("activated_at", JsonValue::Str(TimeNowIso8601Utc()));
    cur.set("manifest_sha256", JsonValue::Str(manifestSha));
    if (!WriteFileAtomic(ctx.paths.currentFile, cur.Dump() + "\n")) {
        message = "cannot write the active-version pointer";
        code = kExitIntegrity;
        return false;
    }
    DeleteFileQuiet(ctx.paths.journalFile);
    LogMsg("[Updater] activated version " + version + " (previous: '" + previous + "')");
    return true;
}

bool RecoverPendingActivation(UpdaterContext& ctx) {
    if (!FileExists(ctx.paths.journalFile)) return true;
    std::string bytes;
    JsonValue j;
    std::string err;
    if (!ReadFileBytes(ctx.paths.journalFile, bytes, 1u << 20) ||
        !JsonValue::Parse(bytes, j, err)) {
        LogMsg("[Updater] discarding unreadable activation journal");
        DeleteFileQuiet(ctx.paths.journalFile);
        return true;
    }
    std::string version = j.str("target_version");
    std::wstring staged = Utf8ToWide(j.str("staged_dir"));
    std::string previous = j.str("previous");
    std::string manifestSha = j.str("manifest_sha256");
    if (version.empty() || staged.empty()) {
        DeleteFileQuiet(ctx.paths.journalFile);
        return true;
    }
    InstalledState cur;
    LoadCurrentImpl(ctx, cur);
    if (cur.present && cur.version == version) {
        LogMsg("[Updater] activation journal already satisfied; clearing");
        DeleteFileQuiet(ctx.paths.journalFile);
        return true;
    }
    std::wstring finalDir = JoinPath(ctx.paths.versionsDir, Utf8ToWide(version));
    if (!DirExists(staged) && !DirExists(finalDir)) {
        LogMsg("[Updater] pending staged install is gone; clearing journal");
        DeleteFileQuiet(ctx.paths.journalFile);
        return true;
    }
    // The staged directory must carry a valid record for this release.
    std::wstring checkDir = DirExists(staged) ? staged : finalDir;
    JsonValue rec;
    VerifyResult vr;
    std::string verr;
    if (!LoadInstallRecord(checkDir, rec, verr) ||
        !VerifyInstallFiles(checkDir, rec, vr, verr) || !vr.missing.empty() || !vr.corrupt.empty()) {
        LogMsg("[Updater] interrupted staged install is unhealthy; discarding: " + verr);
        if (DirExists(staged)) RemoveDirRecursive(staged);
        DeleteFileQuiet(ctx.paths.journalFile);
        return true;
    }
    LogMsg("[Updater] completing interrupted activation of " + version);
    std::string message;
    int code = 0;
    if (!ActivateFromStaged(ctx, version, staged, previous, manifestSha, message, code)) {
        LogMsg("[Updater] recovery failed: " + message);
        return false;
    }
    return true;
}

// ------------------------------------------------------------------ errors --

std::string ErrorKindName(int code) {
    switch (code) {
        case kExitOk: return "ok";
        case kExitUsage: return "usage";
        case kExitConfig: return "config";
        case kExitNetwork: return "network";
        case kExitSignature: return "signature_or_pin";
        case kExitProtocol: return "protocol_incompatible";
        case kExitDownload: return "download_failed";
        case kExitDiskSpace: return "insufficient_disk_space";
        case kExitGameRunning: return "game_running";
        case kExitIntegrity: return "integrity_failure";
        case kExitMaintenance: return "maintenance";
        case kExitSelfUpdateDone: return "launcher_self_updated";
        case kExitSelfUpdateFailed: return "launcher_self_update_failed";
        case kExitLocalVerify: return "local_install_unhealthy";
        case kExitCancelled: return "cancelled";
        default: return "internal";
    }
}

CommandResult Fail(const char* command, int code, const std::string& message) {
    CommandResult r;
    r.code = code;
    JsonValue j = JsonValue::Obj();
    j.set("command", JsonValue::Str(command));
    j.set("ok", JsonValue::Bool(false));
    j.set("error_code", JsonValue::Int(code));
    j.set("error", JsonValue::Str(ErrorKindName(code)));
    j.set("message", JsonValue::Str(message));
    r.json = j.Dump();
    LogMsg(std::string("[Updater] ") + command + " failed (" + ErrorKindName(code) + "): " + message);
    return r;
}

void WriteStateCache(UpdaterContext& ctx, const StatusDoc& st, const ReleaseManifest& m,
                     const InstalledState& inst, bool manifestOk, const std::string& error) {
    JsonValue j = JsonValue::Obj();
    j.set("checked_at", JsonValue::Str(TimeNowIso8601Utc()));
    j.set("state", JsonValue::Str(st.state));
    j.set("message", JsonValue::Str(st.message));
    j.set("status_since", JsonValue::Str(st.since));
    j.set("status_until", JsonValue::Str(st.until));
    j.set("release_version", JsonValue::Str(m.clientVersion));
    j.set("server_version", JsonValue::Str(m.serverVersion));
    j.set("installed_version", JsonValue::Str(inst.version));
    j.set("manifest_ok", JsonValue::Bool(manifestOk));
    j.set("error", JsonValue::Str(error));
    WriteFileAtomic(ctx.paths.stateFile, j.Dump() + "\n");
}

bool SameVersion(const std::string& a, const std::string& b) {
    if (a.empty() || b.empty()) return false;
    return CompareVersions(a, b) == 0;
}

// ------------------------------------------------------------ self-update --

bool PerformSelfUpdate(UpdaterContext& ctx, const ReleaseManifest& m, std::string& message,
                       int& code) {
    Artifact art;
    if (!SelectLauncherArtifact(m, art)) {
        message = "launcher self-update required (min_launcher_version " + m.minLauncherVersion +
                  ") but the manifest has no 'launcher' artifact";
        code = kExitSelfUpdateFailed;
        return false;
    }
    std::string spaceMsg;
    if (!CheckDiskSpace(ctx, art.size + kSpaceSlack, spaceMsg)) {
        message = spaceMsg;
        code = kExitDiskSpace;
        return false;
    }
    std::wstring newExe;
    if (!DownloadArtifact(ctx, art, newExe, message, code)) return false;
    std::wstring ext = Utf8ToWide(UrlExt(art.url));
    if (EqualsCI(ext, L".zip")) {
        message = "launcher self-update artifact is a zip; only raw executables are supported";
        code = kExitSelfUpdateFailed;
        return false;
    }
    std::wstring target = GetExePath();
    std::wstring cmd = L"\"" + newExe + L"\" --self-update-swap " +
                       std::to_wstring(GetCurrentProcessId()) + L" \"" + target + L"\"";
    STARTUPINFOW si = {sizeof(si)};
    PROCESS_INFORMATION pi;
    std::vector<wchar_t> buf(cmd.begin(), cmd.end());
    buf.push_back(0);
    if (!CreateProcessW(newExe.c_str(), buf.data(), NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi)) {
        message = "cannot start the launcher update helper (error " +
                  std::to_string(GetLastError()) + ")";
        code = kExitSelfUpdateFailed;
        return false;
    }
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    message = "launcher self-update to " + m.clientVersion + " handed off to the update helper";
    code = kExitSelfUpdateDone;
    LogMsg("[Updater] " + message);
    return true;
}

// ----------------------------------------------------------------- repair ---

bool CopyFileAtomic(const std::wstring& src, const std::wstring& dst, std::string& err) {
    std::wstring tmp = dst + L".new";
    if (!CopyFileW(src.c_str(), tmp.c_str(), FALSE)) {
        err = "copy failed (" + std::to_string(GetLastError()) + ")";
        return false;
    }
    if (!MoveFileExW(tmp.c_str(), dst.c_str(), MOVEFILE_REPLACE_EXISTING)) {
        err = "replace failed (" + std::to_string(GetLastError()) + ")";
        DeleteFileQuiet(tmp);
        return false;
    }
    return true;
}

// The full update pipeline. verifyOnly/repair select the mode.
bool RunFetchAndCompare(UpdaterContext& ctx, ReleaseManifest& m, StatusDoc& st,
                        InstalledState& inst, CheckSummary* summary, std::string& message,
                        int& code) {
    LoadCurrentImpl(ctx, inst);
    if (!FetchManifest(ctx, m, message, code)) return false;
    std::string statusWarn;
    bool statusOk = FetchStatus(ctx, st, statusWarn);
    if (!statusOk) {
        LogMsg("[Updater] " + statusWarn + " (continuing with the manifest)");
        if (st.state.empty() || st.state == "UNKNOWN") st.state = "OFFLINE";
    }
    std::string serverProto, protoReason;
    bool protoOk = ProtocolCompatible(m, st, serverProto, protoReason);
    bool selfUpdate = !m.minLauncherVersion.empty() &&
                      CompareVersions(m.minLauncherVersion, kLauncherVersion) > 0;
    bool update = !inst.present || !SameVersion(inst.version, m.clientVersion);
    if (summary) {
        summary->ok = true;
        summary->state = st.state;
        summary->message = st.message;
        summary->releaseVersion = m.clientVersion;
        summary->previousRelease = st.previousRelease;
        summary->since = st.since;
        summary->until = st.until;
        summary->installedVersion = inst.version;
        summary->releaseNotes = m.releaseNotes;
        summary->channel = m.channel;
        summary->serverVersion = m.serverVersion;
        summary->updateAvailable = update;
        summary->updateRequired = update || selfUpdate;
        summary->maintenance = (st.state == "MAINTENANCE");
        summary->protocolOk = protoOk;
        summary->selfUpdateRequired = selfUpdate;
        summary->errorCode = kExitOk;
        if (!protoOk) {
            summary->error = protoReason;
            summary->errorCode = kExitProtocol;
        }
        std::vector<RunningProcess> running;
        summary->gameRunning = IsGameRunningNowImpl(ctx.paths, ctx.cfg, &running);
    }
    WriteStateCache(ctx, st, m, inst, true, "");
    (void)serverProto;
    (void)protoReason;
    return true;
}

CommandResult CheckImpl(UpdaterContext& ctx, CheckSummary* summary) {
    ReleaseManifest m;
    StatusDoc st;
    InstalledState inst;
    std::string message;
    int code = kExitOk;
    if (summary) *summary = CheckSummary{};
    // Completing an interrupted activation is idempotent and keeps every
    // command looking at the same state.
    RecoverPendingActivation(ctx);
    if (!RunFetchAndCompare(ctx, m, st, inst, summary, message, code)) {
        if (summary) {
            summary->ok = false;
            summary->error = message;
            summary->errorCode = code;
            if (summary->state.empty()) summary->state = "OFFLINE";
        }
        return Fail("check", code, message);
    }
    std::string serverProto, protoReason;
    bool protoOk = ProtocolCompatible(m, st, serverProto, protoReason);
    bool selfUpdate = !m.minLauncherVersion.empty() &&
                      CompareVersions(m.minLauncherVersion, kLauncherVersion) > 0;
    bool update = !inst.present || !SameVersion(inst.version, m.clientVersion);
    std::vector<RunningProcess> running;
    bool gameRunning = IsGameRunningNowImpl(ctx.paths, ctx.cfg, &running);

    JsonValue j = JsonValue::Obj();
    j.set("command", JsonValue::Str("check"));
    j.set("ok", JsonValue::Bool(true));
    j.set("state", JsonValue::Str(st.state));
    j.set("maintenance", JsonValue::Bool(st.state == "MAINTENANCE"));
    j.set("message", JsonValue::Str(st.message));
    j.set("since", JsonValue::Str(st.since));
    j.set("until", JsonValue::Str(st.until));
    j.set("release_version", JsonValue::Str(m.clientVersion));
    j.set("previous_release", JsonValue::Str(st.previousRelease));
    j.set("installed_version", JsonValue::Str(inst.version));
    j.set("update_available", JsonValue::Bool(update));
    j.set("update_required", JsonValue::Bool(update || selfUpdate));
    j.set("self_update_required", JsonValue::Bool(selfUpdate));
    j.set("protocol_ok", JsonValue::Bool(protoOk));
    j.set("server_protocol", JsonValue::Str(serverProto));
    j.set("protocol_min", JsonValue::Str(m.protocolMin));
    j.set("protocol_max", JsonValue::Str(m.protocolMax));
    j.set("channel", JsonValue::Str(m.channel));
    j.set("server_version", JsonValue::Str(m.serverVersion));
    j.set("schema_version", JsonValue::Str(m.schemaVersion));
    j.set("content_version", JsonValue::Str(m.contentVersion));
    j.set("release_notes", JsonValue::Str(m.releaseNotes));
    j.set("launcher_version", JsonValue::Str(kLauncherVersion));
    j.set("min_launcher_version", JsonValue::Str(m.minLauncherVersion));
    j.set("pinned_key_id", JsonValue::Str(ctx.keyId));
    j.set("game_running", JsonValue::Bool(gameRunning));
    j.set("install_root", JsonValue::Str(WideToUtf8(ctx.paths.installRoot)));
    j.set("manifest_sha256", JsonValue::Str(m.sha256));

    CommandResult r;
    r.json = j.Dump();
    r.code = kExitOk;
    if (!protoOk && summary) summary->errorCode = kExitProtocol;
    if (ctx.cli.forLaunch) {
        if (selfUpdate) {
            r.code = kExitSelfUpdateFailed;
        } else if (st.state == "MAINTENANCE") {
            r.code = kExitMaintenance;
        } else if (!protoOk) {
            r.code = kExitProtocol;
        }
    }
    return r;
}

CommandResult UpdateImpl(UpdaterContext& ctx, CheckSummary* summary) {
    if (summary) *summary = CheckSummary{};
    ReleaseManifest m;
    StatusDoc st;
    InstalledState inst;
    std::string message;
    int code = kExitOk;

    if (!RecoverPendingActivation(ctx)) {
        LogMsg("[Updater] pending activation could not be recovered; it will be redone");
    }
    if (!RunFetchAndCompare(ctx, m, st, inst, summary, message, code)) {
        return Fail("update", code, message);
    }
    std::string serverProto, protoReason;
    bool protoOk = ProtocolCompatible(m, st, serverProto, protoReason);
    bool selfUpdate = !m.minLauncherVersion.empty() &&
                      CompareVersions(m.minLauncherVersion, kLauncherVersion) > 0;

    if (selfUpdate) {
        int selfCode = kExitOk;
        if (!PerformSelfUpdate(ctx, m, message, selfCode)) {
            return Fail("update", selfCode, message);
        }
        CommandResult r;
        JsonValue j = JsonValue::Obj();
        j.set("command", JsonValue::Str("update"));
        j.set("ok", JsonValue::Bool(true));
        j.set("self_update", JsonValue::Bool(true));
        j.set("launcher_version", JsonValue::Str(kLauncherVersion));
        j.set("required_launcher_version", JsonValue::Str(m.minLauncherVersion));
        j.set("message", JsonValue::Str(message));
        r.json = j.Dump();
        r.code = kExitSelfUpdateDone;
        if (summary) {
            summary->ok = true;
            summary->selfUpdateRequired = true;
            summary->releaseVersion = m.clientVersion;
        }
        return r;
    }
    if (!protoOk) {
        if (summary) summary->errorCode = kExitProtocol;
        return Fail("update", kExitProtocol,
                    protoReason + " - refusing to install an incompatible build");
    }
    if (SameVersion(inst.version, m.clientVersion)) {
        CommandResult r;
        JsonValue j = JsonValue::Obj();
        j.set("command", JsonValue::Str("update"));
        j.set("ok", JsonValue::Bool(true));
        j.set("update_available", JsonValue::Bool(false));
        j.set("installed_version", JsonValue::Str(inst.version));
        j.set("release_version", JsonValue::Str(m.clientVersion));
        j.set("state", JsonValue::Str(st.state));
        r.json = j.Dump();
        return r;
    }

    Artifact art;
    std::string why;
    if (!SelectInstallArtifact(m, inst.version, art, why)) {
        return Fail("update", kExitIntegrity, why);
    }
    std::vector<RunningProcess> running;
    if (IsGameRunningNowImpl(ctx.paths, ctx.cfg, &running)) {
        std::string names;
        for (size_t i = 0; i < running.size() && i < 3; i++) {
            if (i) names += ", ";
            names += WideToUtf8(running[i].name) + " (PID " + std::to_string(running[i].pid) + ")";
        }
        return Fail("update", kExitGameRunning,
                    "the game is running (" + names +
                        "); close it before updating - nothing was written");
    }

    if (ctx.status) ctx.status(L"Downloading the new version...");
    std::wstring pkgPath;
    if (!DownloadArtifact(ctx, art, pkgPath, message, code)) {
        return Fail("update", code, message);
    }
    if (ctx.cli.stopAfter == "download" || ctx.cli.stopAfter == "verify") {
        CommandResult r;
        JsonValue j = JsonValue::Obj();
        j.set("command", JsonValue::Str("update"));
        j.set("ok", JsonValue::Bool(true));
        j.set("stage", JsonValue::Str(ctx.cli.stopAfter));
        j.set("package", JsonValue::Str(WideToUtf8(pkgPath)));
        j.set("from_version", JsonValue::Str(inst.version));
        j.set("to_version", JsonValue::Str(m.clientVersion));
        r.json = j.Dump();
        return r;
    }

    // Extraction: verify the staged installation before activation.
    if (ctx.status) ctx.status(L"Verifying and staging the update...");
    std::wstring tmpDir = JoinPath(ctx.paths.versionsDir, Utf8ToWide(m.clientVersion)) + L".tmp";
    if (!CreateDirs(ctx.paths.versionsDir)) {
        return Fail("update", kExitIntegrity, "cannot create the versions directory");
    }
    if (DirExists(tmpDir)) {
        JsonValue rec;
        VerifyResult vr;
        std::string verr;
        bool reusable = LoadInstallRecord(tmpDir, rec, verr) &&
                        ToLowerString(rec.str("manifest_sha256")) == m.sha256 &&
                        VerifyInstallFiles(tmpDir, rec, vr, verr) && vr.missing.empty() &&
                        vr.corrupt.empty();
        if (!reusable) {
            LogMsg("[Updater] discarding stale staging directory " + WideToUtf8(tmpDir));
            RemoveDirRecursive(tmpDir);
        }
    }
    if (!DirExists(tmpDir)) {
        ZipReader zip;
        std::string err;
        if (!zip.Open(pkgPath, err)) {
            return Fail("update", kExitIntegrity, "package is not a readable zip: " + err);
        }
        uint64_t uncompressed = 0;
        for (const auto& e : zip.entries()) uncompressed += e.uncompSize;
        std::string spaceMsg;
        if (!CheckDiskSpace(ctx, uncompressed + kSpaceSlack, spaceMsg)) {
            return Fail("update", kExitDiskSpace, spaceMsg);
        }
        if (!CreateDirs(tmpDir)) {
            return Fail("update", kExitIntegrity, "cannot create the staging directory");
        }
        std::vector<ExtractedFile> files;
        if (!zip.ExtractAll(tmpDir, files, err, [&]() { return ctx.cancel && ctx.cancel->load(); })) {
            RemoveDirRecursive(tmpDir);
            int c = err == "cancelled" ? kExitCancelled : kExitIntegrity;
            return Fail("update", c, "package extraction failed: " + err);
        }
        std::string recordJson = BuildRecordJson(m.clientVersion, m, art, files);
        if (!WriteFileAtomic(JoinPath(tmpDir, L".install-record.json"), recordJson)) {
            RemoveDirRecursive(tmpDir);
            return Fail("update", kExitIntegrity, "cannot write the install record");
        }
        JsonValue rec;
        VerifyResult vr;
        std::string verr;
        if (!LoadInstallRecord(tmpDir, rec, verr) ||
            !VerifyInstallFiles(tmpDir, rec, vr, verr) || !vr.missing.empty() || !vr.corrupt.empty()) {
            RemoveDirRecursive(tmpDir);
            return Fail("update", kExitIntegrity, "staged installation failed verification");
        }
    }
    if (!WriteJournal(ctx, m.clientVersion, tmpDir, inst.version, m.sha256)) {
        return Fail("update", kExitIntegrity, "cannot write the activation journal");
    }
    if (ctx.cli.stopAfter == "stage") {
        CommandResult r;
        JsonValue j = JsonValue::Obj();
        j.set("command", JsonValue::Str("update"));
        j.set("ok", JsonValue::Bool(true));
        j.set("stage", JsonValue::Str("stage"));
        j.set("staged_dir", JsonValue::Str(WideToUtf8(tmpDir)));
        j.set("to_version", JsonValue::Str(m.clientVersion));
        r.json = j.Dump();
        return r;
    }

    std::string activateMsg;
    int activateCode = kExitOk;
    if (!ActivateFromStaged(ctx, m.clientVersion, tmpDir, inst.version, m.sha256, activateMsg,
                            activateCode)) {
        return Fail("update", activateCode, activateMsg);
    }
    if (ctx.status) ctx.status(L"Update installed.");
    CommandResult r;
    JsonValue j = JsonValue::Obj();
    j.set("command", JsonValue::Str("update"));
    j.set("ok", JsonValue::Bool(true));
    j.set("update_available", JsonValue::Bool(true));
    j.set("from_version", JsonValue::Str(inst.version));
    j.set("to_version", JsonValue::Str(m.clientVersion));
    j.set("installed_version", JsonValue::Str(m.clientVersion));
    j.set("previous_version", JsonValue::Str(inst.version));
    j.set("state", JsonValue::Str(st.state));
    j.set("package", JsonValue::Str(WideToUtf8(pkgPath)));
    r.json = j.Dump();
    return r;
}

CommandResult VerifyImpl(UpdaterContext& ctx, bool forRepair) {
    InstalledState inst;
    LoadCurrentImpl(ctx, inst);
    if (!inst.present) {
        return Fail(forRepair ? "repair" : "verify", kExitLocalVerify,
                    "there is no active installation to check");
    }
    JsonValue rec;
    std::string err;
    VerifyResult vr;
    if (!LoadInstallRecord(inst.dir, rec, err) || !VerifyInstallFiles(inst.dir, rec, vr, err)) {
        return Fail(forRepair ? "repair" : "verify", kExitLocalVerify,
                    "cannot verify the active installation: " + err);
    }
    bool healthy = vr.missing.empty() && vr.corrupt.empty();
    JsonValue j = JsonValue::Obj();
    j.set("command", JsonValue::Str(forRepair ? "repair" : "verify"));
    j.set("ok", JsonValue::Bool(healthy));
    j.set("healthy", JsonValue::Bool(healthy));
    j.set("version", JsonValue::Str(inst.version));
    j.set("checked", JsonValue::Int((int64_t)vr.checked));
    JsonValue miss = JsonValue::Arr();
    for (const auto& m : vr.missing) miss.push(JsonValue::Str(m));
    j.set("missing", miss);
    JsonValue corrupt = JsonValue::Arr();
    for (const auto& c : vr.corrupt) corrupt.push(JsonValue::Str(c));
    j.set("corrupt", corrupt);
    CommandResult r;
    r.json = j.Dump();
    r.code = healthy ? kExitOk : kExitLocalVerify;
    return r;
}

CommandResult RepairImpl(UpdaterContext& ctx) {
    if (!RecoverPendingActivation(ctx)) {
        LogMsg("[Updater] pending activation could not be recovered; repair continues");
    }
    InstalledState inst;
    LoadCurrentImpl(ctx, inst);
    if (!inst.present) {
        return Fail("repair", kExitLocalVerify, "there is no active installation to repair");
    }
    JsonValue rec;
    std::string err;
    VerifyResult vr;
    if (!LoadInstallRecord(inst.dir, rec, err) || !VerifyInstallFiles(inst.dir, rec, vr, err)) {
        return Fail("repair", kExitLocalVerify,
                    "cannot verify the active installation (" + err + "); run --update");
    }
    if (vr.missing.empty() && vr.corrupt.empty()) {
        JsonValue j = JsonValue::Obj();
        j.set("command", JsonValue::Str("repair"));
        j.set("ok", JsonValue::Bool(true));
        j.set("healthy", JsonValue::Bool(true));
        j.set("version", JsonValue::Str(inst.version));
        j.set("repaired", JsonValue::Int(0));
        CommandResult r;
        r.json = j.Dump();
        return r;
    }
    LogMsg("[Updater] repair needed: " + std::to_string(vr.missing.size()) + " missing, " +
           std::to_string(vr.corrupt.size()) + " corrupt");

    ReleaseManifest m;
    StatusDoc st;
    CheckSummary tmp;
    std::string message;
    int code = kExitOk;
    if (!RunFetchAndCompare(ctx, m, st, inst, &tmp, message, code)) {
        return Fail("repair", code, message);
    }
    Artifact art;
    std::string why;
    if (!SelectInstallArtifact(m, inst.version, art, why)) {
        return Fail("repair", kExitLocalVerify, why + "; run --update");
    }
    std::vector<RunningProcess> running;
    if (IsGameRunningNowImpl(ctx.paths, ctx.cfg, &running)) {
        return Fail("repair", kExitGameRunning,
                    "the game is running; close it before repairing - nothing was written");
    }
    if (ctx.status) ctx.status(L"Downloading a clean copy for repair...");
    std::wstring pkgPath;
    if (!DownloadArtifact(ctx, art, pkgPath, message, code)) {
        return Fail("repair", code, message);
    }
    std::wstring repairDir = JoinPath(ctx.paths.versionsDir, Utf8ToWide(inst.version)) + L".repair";
    RemoveDirRecursive(repairDir);
    ZipReader zip;
    if (!zip.Open(pkgPath, err)) {
        return Fail("repair", kExitIntegrity, "package is not a readable zip: " + err);
    }
    std::vector<ExtractedFile> files;
    if (!zip.ExtractAll(repairDir, files, err, [&]() { return ctx.cancel && ctx.cancel->load(); })) {
        RemoveDirRecursive(repairDir);
        int c = err == "cancelled" ? kExitCancelled : kExitIntegrity;
        return Fail("repair", c, "repair extraction failed: " + err);
    }
    // Verify the fresh extraction against the trusted record before copying.
    JsonValue freshRec;
    VerifyResult freshVr;
    if (!LoadInstallRecord(repairDir, freshRec, err)) {
        // The archive does not carry a record (e.g. it is the same package that
        // produced the record): compare directly against the active record.
        const auto* wantFiles = rec.arr("files");
        if (!wantFiles) {
            RemoveDirRecursive(repairDir);
            return Fail("repair", kExitIntegrity, "trusted record has no file list");
        }
        for (const auto& f : *wantFiles) {
            std::string rel = f.str("path");
            std::wstring wide = Utf8ToWide(rel);
            for (auto& c : wide)
                if (c == L'/') c = L'\\';
            std::wstring full = JoinPath(repairDir, wide);
            if (!FileExists(full) || Sha256FileHex(full) != ToLowerString(f.str("sha256"))) {
                RemoveDirRecursive(repairDir);
                return Fail("repair", kExitIntegrity,
                            "the downloaded package does not match the install record");
            }
        }
    }

    // Replace missing/corrupt files (never touches user data).
    uint64_t repaired = 0;
    std::vector<std::string> failed;
    const auto* wantFiles = rec.arr("files");
    for (const auto& f : *wantFiles) {
        std::string rel = f.str("path");
        bool needed = std::find(vr.missing.begin(), vr.missing.end(), rel) != vr.missing.end() ||
                      std::find(vr.corrupt.begin(), vr.corrupt.end(), rel) != vr.corrupt.end();
        if (!needed) continue;
        std::wstring wide = Utf8ToWide(rel);
        for (auto& c : wide)
            if (c == L'/') c = L'\\';
        std::wstring src = JoinPath(repairDir, wide);
        std::wstring dst = JoinPath(inst.dir, wide);
        size_t slash = dst.find_last_of(L'\\');
        if (slash != std::wstring::npos && slash > 2) CreateDirs(dst.substr(0, slash));
        if (!CopyFileAtomic(src, dst, err)) {
            failed.push_back(rel + ": " + err);
            continue;
        }
        repaired++;
    }
    RemoveDirRecursive(repairDir);

    // Final verification pass.
    VerifyResult after;
    std::string afterErr;
    LoadInstallRecord(inst.dir, rec, afterErr);
    VerifyInstallFiles(inst.dir, rec, after, afterErr);
    bool healthy = after.missing.empty() && after.corrupt.empty() && failed.empty();
    JsonValue j = JsonValue::Obj();
    j.set("command", JsonValue::Str("repair"));
    j.set("ok", JsonValue::Bool(healthy));
    j.set("version", JsonValue::Str(inst.version));
    j.set("repaired", JsonValue::Int((int64_t)repaired));
    JsonValue miss = JsonValue::Arr();
    for (const auto& m2 : after.missing) miss.push(JsonValue::Str(m2));
    j.set("missing", miss);
    JsonValue corrupt = JsonValue::Arr();
    for (const auto& c2 : after.corrupt) corrupt.push(JsonValue::Str(c2));
    j.set("corrupt", corrupt);
    if (!failed.empty()) {
        JsonValue fails = JsonValue::Arr();
        for (const auto& f : failed) fails.push(JsonValue::Str(f));
        j.set("failed", fails);
    }
    CommandResult r;
    r.json = j.Dump();
    r.code = healthy ? kExitOk : kExitLocalVerify;
    return r;
}

void CleanStaging(UpdaterContext& ctx) {
    std::vector<std::wstring> files;
    std::string err;
    if (ListFilesRecursive(ctx.paths.stagingDir, files, err)) {
        for (const auto& f : files) {
            if (f.size() >= 5 && EqualsCI(f.substr(f.size() - 5), L".part")) {
                DeleteFileQuiet(JoinPath(ctx.paths.stagingDir, f));
            }
        }
    }
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(JoinPath(ctx.paths.versionsDir, L"*").c_str(), &fd);
    if (h != INVALID_HANDLE_VALUE) {
        do {
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
            std::wstring name = fd.cFileName;
            if (name == L"." || name == L"..") continue;
            if (name.size() > 4 && (EqualsCI(name.substr(name.size() - 4), L".tmp") ||
                                    EqualsCI(name.substr(name.size() - 7), L".repair"))) {
                RemoveDirRecursive(JoinPath(ctx.paths.versionsDir, name));
            }
        } while (FindNextFileW(h, &fd));
        FindClose(h);
    }
}

CommandResult PrintStateImpl(UpdaterContext& ctx) {
    InstalledState inst;
    LoadCurrentImpl(ctx, inst);
    JsonValue j = JsonValue::Obj();
    j.set("command", JsonValue::Str("print-state"));
    j.set("ok", JsonValue::Bool(true));
    j.set("launcher_version", JsonValue::Str(kLauncherVersion));
    j.set("install_root", JsonValue::Str(WideToUtf8(ctx.paths.installRoot)));
    j.set("user_data_dir", JsonValue::Str(WideToUtf8(ctx.paths.userDir)));
    j.set("staging_dir", JsonValue::Str(WideToUtf8(ctx.paths.stagingDir)));
    j.set("release_base", JsonValue::Str(WideToUtf8(ctx.releaseBase)));
    j.set("channel", JsonValue::Str(WideToUtf8(ToLower(ctx.cli.channel))));
    j.set("pinned_key_id", JsonValue::Str(ctx.keyId));
    j.set("installed_version", JsonValue::Str(inst.version));
    j.set("installed_dir", JsonValue::Str(WideToUtf8(inst.dir)));
    j.set("previous_version", JsonValue::Str(inst.previous));
    j.set("has_active_install", JsonValue::Bool(inst.present));
    j.set("pending_activation", JsonValue::Bool(FileExists(ctx.paths.journalFile)));
    j.set("game_running", JsonValue::Bool(IsGameRunningNowImpl(ctx.paths, ctx.cfg, nullptr)));
    std::string cache;
    if (ReadFileBytes(ctx.paths.stateFile, cache, 1u << 20)) {
        JsonValue cached;
        std::string err;
        if (JsonValue::Parse(cache, cached, err)) {
            j.set("last_check", cached);
        }
    }
    CommandResult r;
    r.json = j.Dump();
    return r;
}

}  // namespace

// --------------------------------------------------------------- public API --

UpdaterPaths ComputePaths(const CliOptions& cli, const AppConfig& cfg) {
    return MakeContext(cli, cfg).paths;
}

std::wstring ReleaseBaseUrl(const CliOptions& cli, const AppConfig& cfg) {
    return !cli.releaseBase.empty() ? cli.releaseBase : cfg.releaseBaseUrl;
}

std::wstring StatusUrl(const CliOptions& cli, const AppConfig& cfg) {
    if (!cli.statusUrl.empty()) return cli.statusUrl;
    if (!cfg.statusUrl.empty()) return cfg.statusUrl;
    std::wstring base = ReleaseBaseUrl(cli, cfg);
    if (base.empty()) return L"";
    return Utf8ToWide(JoinUrlBase(base, "status.json"));
}

CommandResult RunCliCommand(const CliOptions& opts) {
    AppConfig cfg = Config();
    if (!opts.configPath.empty()) LoadConfig(opts.configPath);
    cfg = Config();
    UpdaterContext ctx = MakeContext(opts, cfg);
    if (opts.cleanStaging) CleanStaging(ctx);
    if (!ctx.releaseBase.empty() && opts.command != "print-state") {
        // Surfaced in logs only; never printed as a credential.
        LogMsg("[Updater] command=" + opts.command + " install_root=" +
               WideToUtf8(ctx.paths.installRoot) + " release_base=" + WideToUtf8(ctx.releaseBase));
    }
    if (opts.command == "check") return CheckImpl(ctx, nullptr);
    if (opts.command == "update") return UpdateImpl(ctx, nullptr);
    if (opts.command == "repair") return RepairImpl(ctx);
    if (opts.command == "verify") return VerifyImpl(ctx, false);
    if (opts.command == "print-state") return PrintStateImpl(ctx);
    return Fail("unknown", kExitUsage, "unknown command '" + opts.command + "'");
}

CheckSummary DoCheck(const CliOptions& opts, AppConfig cfg, std::atomic<bool>* cancel,
                     const std::function<void(const std::wstring&)>& status) {
    UpdaterContext ctx = MakeContext(opts, cfg);
    ctx.cancel = cancel;
    ctx.status = status;
    ctx.interactive = true;
    CheckSummary summary;
    CheckImpl(ctx, &summary);
    return summary;
}

CommandResult DoUpdate(const CliOptions& opts, AppConfig cfg, std::atomic<bool>* cancel,
                       const std::function<void(const std::wstring&)>& status) {
    UpdaterContext ctx = MakeContext(opts, cfg);
    ctx.cancel = cancel;
    ctx.status = status;
    ctx.interactive = true;
    return UpdateImpl(ctx, nullptr);
}

CommandResult DoRepair(const CliOptions& opts, AppConfig cfg, std::atomic<bool>* cancel,
                       const std::function<void(const std::wstring&)>& status) {
    UpdaterContext ctx = MakeContext(opts, cfg);
    ctx.cancel = cancel;
    ctx.status = status;
    ctx.interactive = true;
    return RepairImpl(ctx);
}

bool IsGameRunningNow(const UpdaterPaths& paths, const AppConfig& cfg,
                      std::vector<RunningProcess>* matches) {
    return IsGameRunningNowImpl(paths, cfg, matches);
}

bool LaunchInstalledGame(const UpdaterPaths& paths, const AppConfig& cfg, bool solo,
                         const std::wstring& username, const std::wstring& ticket) {
    if (paths.gameExe.empty() || !FileExists(paths.gameExe)) return false;
    // No scene argument: the official Windows export templates are compiled with
    // `disable_path_overrides=yes`, and a packaged Godot binary aborts outright
    // ("Scene path was specified on the command line, but this Godot binary was
    // compiled without support for path overrides") before it ever opens a
    // window. The installed game's main scene is the main menu anyway, so the
    // argument bought nothing and cost every online launch (Release gates defect).
    std::wstring cmd = L"\"" + paths.gameExe + L"\"";
    std::vector<wchar_t> envBlock;
    LPVOID envPtr = NULL;
    DWORD flags = 0;
    if (solo) {
        cmd += L" --solo";
    } else {
        cmd += L" --user \"" + username + L"\" --ip \"" + cfg.serverIp + L"\" --port " +
               std::to_wstring(cfg.serverPort) + L" --autologin";
        std::vector<std::wstring> entries;
        LPWCH current = GetEnvironmentStringsW();
        if (current) {
            for (LPWCH p = current; *p; p += wcslen(p) + 1) {
                if (_wcsnicmp(p, L"HPMMO_TICKET=", 13) == 0) continue;
                if (_wcsnicmp(p, L"HPMMO_API_URL=", 14) == 0) continue;
                if (_wcsnicmp(p, L"HPMMO_USER_DIR=", 15) == 0) continue;
                entries.emplace_back(p);
            }
            FreeEnvironmentStringsW(current);
        }
        entries.push_back(L"HPMMO_API_URL=http://" + cfg.serverIp + L":" +
                          std::to_wstring(cfg.apiPort));
        entries.push_back(L"HPMMO_USER_DIR=" + paths.userDir);
        entries.push_back(L"HPMMO_TICKET=" + ticket);
        std::sort(entries.begin(), entries.end());
        for (const auto& entry : entries) {
            envBlock.insert(envBlock.end(), entry.begin(), entry.end());
            envBlock.push_back(L'\0');
        }
        envBlock.push_back(L'\0');
        envPtr = envBlock.data();
        flags = CREATE_UNICODE_ENVIRONMENT;
    }
    STARTUPINFOW si = {sizeof(si)};
    PROCESS_INFORMATION pi;
    std::vector<wchar_t> buf(cmd.begin(), cmd.end());
    buf.push_back(0);
    if (CreateProcessW(NULL, buf.data(), NULL, NULL, FALSE, flags, envPtr, NULL, &si, &pi)) {
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
        return true;
    }
    return false;
}

int RunSelfUpdateSwap(const std::string& pidStr, const std::wstring& target,
                      const std::wstring& newExe, bool relaunch) {
    DWORD pid = 0;
    try {
        pid = (DWORD)std::stoul(pidStr);
    } catch (...) {
        pid = 0;
    }
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(120);
    if (pid != 0) {
        while (IsProcessRunning(pid) && std::chrono::steady_clock::now() < deadline) {
            std::this_thread::sleep_for(std::chrono::milliseconds(250));
        }
    }
    if (NormalizePath(newExe) != NormalizePath(target)) {
        bool copied = false;
        while (std::chrono::steady_clock::now() < deadline) {
            std::wstring tmp = target + L".swapnew";
            DeleteFileQuiet(tmp);
            if (CopyFileW(newExe.c_str(), tmp.c_str(), FALSE) &&
                MoveFileExW(tmp.c_str(), target.c_str(), MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
                copied = true;
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(500));
        }
        if (!copied) {
            LogMsg("[Updater] self-update swap failed: target is still locked");
            return kExitSelfUpdateFailed;
        }
    }
    LogMsg("[Updater] launcher self-update applied to " + WideToUtf8(target));
    if (relaunch) {
        std::wstring cmd = L"\"" + target + L"\" --post-self-update";
        STARTUPINFOW si = {sizeof(si)};
        PROCESS_INFORMATION pi;
        std::vector<wchar_t> buf(cmd.begin(), cmd.end());
        buf.push_back(0);
        CreateProcessW(NULL, buf.data(), NULL, NULL, FALSE, 0, NULL, NULL, &si, &pi);
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
    }
    return kExitOk;
}

int RunPrintCertPin(const std::wstring& url) {
    std::string pin;
    HttpOutcome out = HttpProbeCertPin(url, pin);
    JsonValue j = JsonValue::Obj();
    j.set("ok", JsonValue::Bool(out.ok && !pin.empty()));
    j.set("cert_spki_sha256", JsonValue::Str(pin));
    if (!out.ok) {
        j.set("error", JsonValue::Str(out.error));
        j.set("error_kind", JsonValue::Str(out.errorKind));
    }
    printf("%s\n", j.Dump().c_str());
    fflush(stdout);
    return out.ok ? kExitOk : kExitNetwork;
}

}  // namespace hpmmo
