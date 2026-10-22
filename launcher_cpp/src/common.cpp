#include "common.h"

#include "json.h"

#include <cctype>
#include <cstdio>
#include <cstring>
#include <cwchar>
#include <cwctype>
#include <mutex>

namespace hpmmo {

// ---------------------------------------------------------------- strings --

std::wstring ToLower(std::wstring s) {
    for (auto& c : s) c = (wchar_t)towlower(c);
    return s;
}

bool EqualsCI(const std::wstring& a, const std::wstring& b) {
    return ToLower(a) == ToLower(b);
}

bool PathStartsWithCI(const std::wstring& path, const std::wstring& prefix) {
    std::wstring p = NormalizePath(path);
    std::wstring q = NormalizePath(prefix);
    std::wstring pl = ToLower(p), ql = ToLower(q);
    if (pl.size() < ql.size()) return false;
    if (pl.compare(0, ql.size(), ql) != 0) return false;
    if (pl.size() == ql.size()) return true;
    return pl[ql.size()] == L'\\' || pl[ql.size()] == L'/';
}

std::string HexLower(const unsigned char* data, size_t len) {
    static const char* kHex = "0123456789abcdef";
    std::string out;
    out.reserve(len * 2);
    for (size_t i = 0; i < len; i++) {
        out.push_back(kHex[data[i] >> 4]);
        out.push_back(kHex[data[i] & 0xF]);
    }
    return out;
}

bool HexToBytes(const std::string& hex, std::vector<unsigned char>& out) {
    out.clear();
    if (hex.size() % 2 != 0) return false;
    auto nib = [](char c) -> int {
        if (c >= '0' && c <= '9') return c - '0';
        if (c >= 'a' && c <= 'f') return c - 'a' + 10;
        if (c >= 'A' && c <= 'F') return c - 'A' + 10;
        return -1;
    };
    for (size_t i = 0; i < hex.size(); i += 2) {
        int hi = nib(hex[i]), lo = nib(hex[i + 1]);
        if (hi < 0 || lo < 0) return false;
        out.push_back((unsigned char)((hi << 4) | lo));
    }
    return true;
}

std::string Trim(const std::string& s) {
    size_t a = 0, b = s.size();
    while (a < b && (unsigned char)s[a] <= ' ') a++;
    while (b > a && (unsigned char)s[b - 1] <= ' ') b--;
    return s.substr(a, b - a);
}

std::string FormatU64(uint64_t v) {
    char buf[32];
    snprintf(buf, sizeof(buf), "%llu", (unsigned long long)v);
    return buf;
}

std::wstring FormatBytesW(uint64_t v) {
    wchar_t buf[64];
    if (v >= 1024ull * 1024 * 1024) {
        swprintf(buf, 64, L"%.2f GB", (double)v / (1024.0 * 1024 * 1024));
    } else if (v >= 1024ull * 1024) {
        swprintf(buf, 64, L"%.1f MB", (double)v / (1024.0 * 1024));
    } else if (v >= 1024) {
        swprintf(buf, 64, L"%.1f KB", (double)v / 1024.0);
    } else {
        swprintf(buf, 64, L"%llu B", (unsigned long long)v);
    }
    return buf;
}

// ------------------------------------------------------------------ paths --
std::wstring JoinPath(const std::wstring& a, const std::wstring& b) {
    if (a.empty()) return b;
    if (b.empty()) return a;
    std::wstring out = a;
    if (out.back() != L'\\' && out.back() != L'/') out.push_back(kPathSep);
    out += b;
    return out;
}


std::wstring GetExeDir() {
    std::wstring p = GetExePath();
    size_t pos = p.find_last_of(L"\\/");
    return pos == std::wstring::npos ? L"." : p.substr(0, pos);
}


// ------------------------------------------------------------------ version --
namespace {
struct VersionParts {
    std::vector<long long> nums;
    std::string pre;
};

bool ParseVersion(const std::string& s, VersionParts& out) {
    out = VersionParts{};
    if (s.empty() || s.size() > 128) return false;
    std::string core = s;
    size_t dash = core.find('-');
    if (dash != std::string::npos) {
        out.pre = core.substr(dash + 1);
        core = core.substr(0, dash);
    }
    size_t start = 0;
    while (true) {
        size_t dot = core.find('.', start);
        std::string part = core.substr(start, dot == std::string::npos ? std::string::npos
                                                                       : dot - start);
        if (part.empty() || part.size() > 18) return false;
        for (char c : part)
            if (c < '0' || c > '9') return false;
        out.nums.push_back(std::stoll(part));
        if (dot == std::string::npos) break;
        start = dot + 1;
    }
    return true;
}
}  // namespace

int CompareVersions(const std::string& a, const std::string& b) {
    VersionParts pa, pb;
    bool oka = ParseVersion(a, pa);
    bool okb = ParseVersion(b, pb);
    if (!oka || !okb) {
        // Unparseable versions compare byte-wise (deterministic, never equal-crash).
        if (a == b) return 0;
        return a < b ? -1 : 1;
    }
    size_t n = pa.nums.size() > pb.nums.size() ? pa.nums.size() : pb.nums.size();
    for (size_t i = 0; i < n; i++) {
        long long va = i < pa.nums.size() ? pa.nums[i] : 0;
        long long vb = i < pb.nums.size() ? pb.nums[i] : 0;
        if (va != vb) return va < vb ? -1 : 1;
    }
    if (pa.pre == pb.pre) return 0;
    if (pa.pre.empty()) return 1;   // release > pre-release
    if (pb.pre.empty()) return -1;
    // Numeric-aware comparison of pre-release identifiers.
    size_t i = 0, j = 0;
    while (i < pa.pre.size() && j < pb.pre.size()) {
        if (isdigit((unsigned char)pa.pre[i]) && isdigit((unsigned char)pb.pre[j])) {
            size_t i2 = i, j2 = j;
            while (i2 < pa.pre.size() && isdigit((unsigned char)pa.pre[i2])) i2++;
            while (j2 < pb.pre.size() && isdigit((unsigned char)pb.pre[j2])) j2++;
            long long va = std::stoll(pa.pre.substr(i, i2 - i));
            long long vb = std::stoll(pb.pre.substr(j, j2 - j));
            if (va != vb) return va < vb ? -1 : 1;
            i = i2;
            j = j2;
        } else {
            char ca = pa.pre[i], cb = pb.pre[j];
            if (ca != cb) return ca < cb ? -1 : 1;
            i++;
            j++;
        }
    }
    if (i == pa.pre.size() && j == pb.pre.size()) return 0;
    return i == pa.pre.size() ? -1 : 1;
}

bool IsVersionString(const std::string& s) {
    VersionParts p;
    return ParseVersion(s, p);
}

// -------------------------------------------------------------------- time --

std::string FormatDuration(int64_t seconds) {
    if (seconds < 0) seconds = 0;
    char buf[64];
    int64_t h = seconds / 3600;
    int64_t m = (seconds % 3600) / 60;
    if (h > 0) {
        snprintf(buf, sizeof(buf), "%lldh %lldm", (long long)h, (long long)m);
    } else if (m > 0) {
        snprintf(buf, sizeof(buf), "%lldm", (long long)m);
    } else {
        snprintf(buf, sizeof(buf), "%llds", (long long)seconds);
    }
    return buf;
}



bool IsGameRunning(const std::wstring& installRoot,
                   const std::vector<std::wstring>& extraNames,
                   std::vector<RunningProcess>* matches) {
    uint32_t self = CurrentProcessId();
    std::wstring versionsPrefix = JoinPath(CanonicalPath(installRoot), L"versions");
    std::vector<RunningProcess> found;
    for (const auto& p : SnapshotProcesses()) {
        if (p.pid == self || p.pid == 0) continue;
        bool hit = false;
        if (!p.imagePath.empty()) {
            if (PathStartsWithCI(CanonicalPath(p.imagePath), versionsPrefix)) hit = true;
        }
        if (!hit) {
            for (const auto& n : extraNames) {
                if (!n.empty() && EqualsCI(p.name, n)) {
                    hit = true;
                    break;
                }
            }
        }
        if (hit) found.push_back(p);
    }
    if (matches) *matches = found;
    return !found.empty();
}

// ------------------------------------------------------------------- config --
namespace {
AppConfig g_config;
std::wstring g_configPath;
JsonValue g_configExtra;  // unknown keys from the file, preserved on save
bool g_configExtraValid = false;
}  // namespace

AppConfig& Config() { return g_config; }

std::wstring DefaultConfigPath() {
    std::wstring exeDir = GetExeDir();
    std::wstring candidates[] = {
        JoinPath(exeDir, L"client_config.json"),
        L"client_config.json",
        std::wstring(L"..") + kPathSep + L"client_config.json",
    };
    for (const auto& c : candidates) {
        if (FileExists(c)) return NormalizePath(c);
    }
    return JoinPath(exeDir, L"client_config.json");
}

std::wstring LastLoadedConfigPath() { return g_configPath; }

bool LoadConfig(const std::wstring& explicitPath) {
    std::wstring path = explicitPath.empty() ? DefaultConfigPath() : explicitPath;
    std::string bytes;
    if (!FileExists(path)) {
        g_configPath = explicitPath;
        return false;
    }
    g_configPath = NormalizePath(path);
    SetLogPath(JoinPath(GetExeDir(), L"launcher.log"));
    if (!ReadFileBytes(path, bytes, 4u * 1024 * 1024)) return false;

    JsonValue root;
    std::string err;
    if (!JsonValue::Parse(bytes, root, err) || !root.isObject()) {
        LogMsg("[Config] parse failed: " + err);
        return false;
    }

    auto s = [&](const char* key, std::wstring& dst) {
        std::string v = root.str(key);
        if (!v.empty()) dst = Utf8ToWide(v);
    };
    s("server_ip", g_config.serverIp);
    if (root.i64("server_port", 0) > 0) g_config.serverPort = (int)root.i64("server_port", 7777);
    if (root.i64("api_port", 0) > 0) g_config.apiPort = (int)root.i64("api_port", 8081);
    // The first host (213.250.145.75) was retired on 2026-10-19; installs that
    // saved it in client_config.json follow the built-in default instead.
    if (g_config.serverIp == L"213.250.145.75") g_config.serverIp = AppConfig().serverIp;
    if (root.has("api_url")) g_config.apiUrl = Utf8ToWide(root.str("api_url"));
    s("last_username", g_config.lastUsername);
    if (root.has("remember_me")) g_config.rememberMe = root.boolean("remember_me", true);

    s("release_base_url", g_config.releaseBaseUrl);
    s("status_url", g_config.statusUrl);
    if (g_config.statusUrl.find(L"213.250.145.75") != std::wstring::npos) g_config.statusUrl.clear();
    // A saved plain-HTTP status URL of the live host follows the TLS default.
    if (g_config.statusUrl == L"http://185.118.141.74:8081/api/status") g_config.statusUrl.clear();
    s("release_public_key", g_config.releasePublicKey);
    s("release_public_key_id", g_config.releasePublicKeyId);
    s("release_channel", g_config.releaseChannel);
    s("pinned_spki_sha256", g_config.pinnedSpkiSha256);
    s("install_root", g_config.installRoot);
    s("user_data_dir", g_config.userDataDir);
    s("game_exe_name", g_config.gameExeName);
    if (root.i64("staging_quota_bytes", 0) > 0) {
        g_config.stagingQuotaBytes = (uint64_t)root.i64("staging_quota_bytes", 0);
    }
    g_config.gameProcessNames.clear();
    if (const auto* names = root.arr("game_process_names")) {
        for (const auto& v : *names)
            if (v.isString() && !v.asString().empty())
                g_config.gameProcessNames.push_back(Utf8ToWide(v.asString()));
    }

    // Remember the raw object so SaveConfig can preserve unknown keys.
    g_configExtra = root;
    g_configExtraValid = true;
    return true;
}

std::wstring ApiBaseUrl(const AppConfig& cfg) {
    std::wstring url = cfg.apiUrl;
    while (!url.empty() && (url.back() == L'/' || url.back() == L' ')) url.pop_back();
    // The built-in URL belongs to the built-in host: a config that names
    // another server (local or LAN play) talks to that server directly.
    const bool builtIn = url == HPMMO_DEFAULT_API_URL;
    if (!url.empty() && (!builtIn || cfg.serverIp == AppConfig().serverIp)) return url;
    return L"http://" + cfg.serverIp + L":" + std::to_wstring(cfg.apiPort);
}

bool SaveConfig(const std::wstring& explicitPath) {
    std::wstring path = explicitPath;
    if (path.empty()) path = g_configPath;
    if (path.empty()) path = DefaultConfigPath();

    JsonValue root = g_configExtraValid && g_configExtra.isObject() ? g_configExtra : JsonValue::Obj();
    root.set("server_ip", JsonValue::Str(WideToUtf8(g_config.serverIp)));
    root.set("server_port", JsonValue::Int(g_config.serverPort));
    root.set("api_port", JsonValue::Int(g_config.apiPort));
    root.set("api_url", JsonValue::Str(WideToUtf8(g_config.apiUrl)));
    root.set("last_username", JsonValue::Str(WideToUtf8(g_config.lastUsername)));
    root.set("remember_me", JsonValue::Bool(g_config.rememberMe));
    auto putStr = [&](const char* key, const std::wstring& v) {
        if (v.empty()) {
            root.set(key, JsonValue::Str(""));
        } else {
            root.set(key, JsonValue::Str(WideToUtf8(v)));
        }
    };
    putStr("release_base_url", g_config.releaseBaseUrl);
    putStr("status_url", g_config.statusUrl);
    putStr("release_public_key", g_config.releasePublicKey);
    putStr("release_public_key_id", g_config.releasePublicKeyId);
    putStr("release_channel", g_config.releaseChannel);
    putStr("pinned_spki_sha256", g_config.pinnedSpkiSha256);
    putStr("install_root", g_config.installRoot);
    putStr("user_data_dir", g_config.userDataDir);
    putStr("game_exe_name", g_config.gameExeName);
    root.set("staging_quota_bytes", JsonValue::Int((int64_t)g_config.stagingQuotaBytes));
    JsonValue names = JsonValue::Arr();
    for (const auto& n : g_config.gameProcessNames) names.push(JsonValue::Str(WideToUtf8(n)));
    root.set("game_process_names", names);

    return WriteFileAtomic(path, root.Dump() + "\n");
}

// ------------------------------------------------------------ base64 decoding --
bool Base64Decode(const std::string& in, std::vector<unsigned char>& out) {
    out.clear();
    auto val = [](char c) -> int {
        if (c >= 'A' && c <= 'Z') return c - 'A';
        if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52;
        if (c == '+') return 62;
        if (c == '/') return 63;
        return -1;
    };
    int buf = 0, bits = 0;
    size_t pad = 0;
    for (char c : in) {
        if (c == '\r' || c == '\n' || c == ' ' || c == '\t') continue;
        if (c == '=') {
            pad++;
            continue;
        }
        if (pad) return false;  // data after padding
        int v = val(c);
        if (v < 0) return false;
        buf = (buf << 6) | v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back((unsigned char)((buf >> bits) & 0xFF));
        }
    }
    // Leftover bits must be zero padding.
    if (bits >= 6) return false;
    if (bits > 0 && (buf & ((1 << bits) - 1)) != 0) return false;
    return !out.empty();
}

}  // namespace hpmmo
