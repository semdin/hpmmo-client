#include "common.h"

#include "json.h"

#include <tlhelp32.h>

#include <cstdio>
#include <cstring>
#include <mutex>

namespace hpmmo {

// ---------------------------------------------------------------- strings --
std::wstring Utf8ToWide(const std::string& str) {
    if (str.empty()) return L"";
    int size = MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), NULL, 0);
    if (size <= 0) return L"";
    std::wstring wstr(size, 0);
    MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), &wstr[0], size);
    return wstr;
}

std::string WideToUtf8(const std::wstring& wstr) {
    if (wstr.empty()) return "";
    int size = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), NULL, 0, NULL, NULL);
    if (size <= 0) return "";
    std::string str(size, 0);
    WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), &str[0], size, NULL, NULL);
    return str;
}

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
    if (out.back() != L'\\' && out.back() != L'/') out.push_back(L'\\');
    out += b;
    return out;
}

std::wstring GetExePath() {
    std::wstring buf(MAX_PATH, 0);
    while (true) {
        DWORD n = GetModuleFileNameW(NULL, &buf[0], (DWORD)buf.size());
        if (n == 0) return L"";
        if (n < buf.size() - 1) {
            buf.resize(n);
            return buf;
        }
        buf.resize(buf.size() * 2);
    }
}

std::wstring GetExeDir() {
    std::wstring p = GetExePath();
    size_t pos = p.find_last_of(L"\\/");
    return pos == std::wstring::npos ? L"." : p.substr(0, pos);
}

std::wstring GetCwd() {
    std::wstring buf(MAX_PATH, 0);
    while (true) {
        DWORD n = GetCurrentDirectoryW((DWORD)buf.size(), &buf[0]);
        if (n == 0) return L"";
        if (n < buf.size() - 1) {
            buf.resize(n);
            return buf;
        }
        buf.resize(buf.size() * 2);
    }
}

std::wstring TempDirPath() {
    std::wstring buf(MAX_PATH, 0);
    while (true) {
        DWORD n = GetTempPathW((DWORD)buf.size(), &buf[0]);
        if (n == 0) return L".";
        if (n < buf.size() - 1) {
            buf.resize(n);
            if (!buf.empty() && (buf.back() == L'\\' || buf.back() == L'/')) buf.pop_back();
            return buf;
        }
        buf.resize(buf.size() * 2);
    }
}

std::wstring NormalizePath(const std::wstring& path) {
    if (path.empty()) return L"";
    DWORD need = GetFullPathNameW(path.c_str(), 0, NULL, NULL);
    if (need == 0) return path;
    std::wstring buf(need, 0);
    DWORD n = GetFullPathNameW(path.c_str(), need, &buf[0], NULL);
    if (n == 0 || n >= need) return path;
    buf.resize(n);
    while (buf.size() > 3 && (buf.back() == L'\\' || buf.back() == L'/')) buf.pop_back();
    return buf;
}

bool FileExists(const std::wstring& path) {
    DWORD a = GetFileAttributesW(path.c_str());
    return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY);
}

bool DirExists(const std::wstring& path) {
    DWORD a = GetFileAttributesW(path.c_str());
    return a != INVALID_FILE_ATTRIBUTES && (a & FILE_ATTRIBUTE_DIRECTORY);
}

uint64_t FileSizeOrZero(const std::wstring& path) {
    WIN32_FILE_ATTRIBUTE_DATA fad;
    if (!GetFileAttributesExW(path.c_str(), GetFileExInfoStandard, &fad)) return 0;
    if (fad.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) return 0;
    return ((uint64_t)fad.nFileSizeHigh << 32) | fad.nFileSizeLow;
}

bool DeleteFileQuiet(const std::wstring& path) {
    SetFileAttributesW(path.c_str(), FILE_ATTRIBUTE_NORMAL);
    return DeleteFileW(path.c_str()) != 0;
}

bool RemoveDirRecursive(const std::wstring& dir) {
    if (!DirExists(dir)) return true;
    std::wstring pattern = JoinPath(dir, L"*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return false;
    bool ok = true;
    do {
        std::wstring name = fd.cFileName;
        if (name == L"." || name == L"..") continue;
        std::wstring full = JoinPath(dir, name);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (!RemoveDirRecursive(full)) ok = false;
        } else {
            SetFileAttributesW(full.c_str(), FILE_ATTRIBUTE_NORMAL);
            if (!DeleteFileW(full.c_str())) ok = false;
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    if (!RemoveDirectoryW(dir.c_str())) ok = false;
    return ok;
}

bool CreateDirs(const std::wstring& dir) {
    if (dir.empty()) return false;
    if (DirExists(dir)) return true;
    std::wstring norm = NormalizePath(dir);
    if (norm.empty()) return false;
    size_t pos = 0;
    // Skip a drive root like C:\
    if (norm.size() >= 2 && norm[1] == L':') pos = 3;
    while (true) {
        pos = norm.find(L'\\', pos);
        std::wstring part = (pos == std::wstring::npos) ? norm : norm.substr(0, pos);
        if (!part.empty() && !DirExists(part)) {
            if (!CreateDirectoryW(part.c_str(), NULL) && GetLastError() != ERROR_ALREADY_EXISTS) {
                return false;
            }
        }
        if (pos == std::wstring::npos) break;
        pos++;
    }
    return DirExists(norm);
}

bool WriteFileBytes(const std::wstring& path, const void* data, size_t len) {
    HANDLE h = CreateFileW(path.c_str(), GENERIC_WRITE, 0, NULL, CREATE_ALWAYS,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return false;
    const unsigned char* p = (const unsigned char*)data;
    size_t left = len;
    bool ok = true;
    while (left > 0) {
        DWORD chunk = (DWORD)(left > (1u << 20) ? (1u << 20) : left);
        DWORD written = 0;
        if (!WriteFile(h, p, chunk, &written, NULL) || written != chunk) {
            ok = false;
            break;
        }
        p += written;
        left -= written;
    }
    FlushFileBuffers(h);
    CloseHandle(h);
    if (!ok) DeleteFileQuiet(path);
    return ok;
}

bool WriteFileAtomic(const std::wstring& path, const std::string& bytes) {
    std::wstring tmp = path + L".tmp" + std::to_wstring(GetCurrentProcessId());
    if (!WriteFileBytes(tmp, bytes.data(), bytes.size())) {
        DeleteFileQuiet(tmp);
        return false;
    }
    if (!MoveFileExW(tmp.c_str(), path.c_str(),
                     MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH)) {
        DeleteFileQuiet(tmp);
        return false;
    }
    return true;
}

bool ReadFileBytes(const std::wstring& path, std::string& out, uint64_t maxBytes) {
    out.clear();
    HANDLE h = CreateFileW(path.c_str(), GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                           FILE_ATTRIBUTE_NORMAL, NULL);
    if (h == INVALID_HANDLE_VALUE) return false;
    LARGE_INTEGER size;
    if (!GetFileSizeEx(h, &size)) {
        CloseHandle(h);
        return false;
    }
    if (maxBytes && size.QuadPart > (LONGLONG)maxBytes) {
        CloseHandle(h);
        return false;
    }
    out.resize((size_t)size.QuadPart);
    size_t off = 0;
    bool ok = true;
    while (off < out.size()) {
        DWORD chunk = (DWORD)((out.size() - off) > (1u << 20) ? (1u << 20) : (out.size() - off));
        DWORD got = 0;
        if (!ReadFile(h, &out[off], chunk, &got, NULL) || got == 0) {
            ok = false;
            break;
        }
        off += got;
    }
    CloseHandle(h);
    if (!ok) out.clear();
    return ok;
}

uint64_t FreeDiskSpaceBytes(const std::wstring& dir) {
    ULARGE_INTEGER freeAvailable;
    if (!GetDiskFreeSpaceExW(dir.c_str(), &freeAvailable, NULL, NULL)) return 0;
    return freeAvailable.QuadPart;
}

static void DirSizeWalk(const std::wstring& dir, uint64_t& total) {
    std::wstring pattern = JoinPath(dir, L"*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        std::wstring name = fd.cFileName;
        if (name == L"." || name == L"..") continue;
        std::wstring full = JoinPath(dir, name);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            DirSizeWalk(full, total);
        } else {
            total += ((uint64_t)fd.nFileSizeHigh << 32) | fd.nFileSizeLow;
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

uint64_t DirSizeBytes(const std::wstring& dir) {
    uint64_t total = 0;
    DirSizeWalk(dir, total);
    return total;
}

static void ListWalk(const std::wstring& root, const std::wstring& dir,
                     std::vector<std::wstring>& out) {
    std::wstring pattern = JoinPath(dir, L"*");
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(pattern.c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    do {
        std::wstring name = fd.cFileName;
        if (name == L"." || name == L"..") continue;
        std::wstring full = JoinPath(dir, name);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            ListWalk(root, full, out);
        } else {
            std::wstring rel = full.substr(root.size());
            if (!rel.empty() && (rel[0] == L'\\' || rel[0] == L'/')) rel.erase(0, 1);
            for (auto& c : rel)
                if (c == L'\\') c = L'/';
            out.push_back(rel);
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
}

bool ListFilesRecursive(const std::wstring& dir, std::vector<std::wstring>& out, std::string& err) {
    out.clear();
    if (!DirExists(dir)) {
        err = "directory does not exist";
        return false;
    }
    ListWalk(NormalizePath(dir), NormalizePath(dir), out);
    return true;
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
std::string TimeNowIso8601Utc() {
    SYSTEMTIME st;
    GetSystemTime(&st);
    char buf[40];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02dZ", st.wYear, st.wMonth, st.wDay,
             st.wHour, st.wMinute, st.wSecond);
    return buf;
}

int64_t UnixNowSeconds() {
    FILETIME ft;
    GetSystemTimeAsFileTime(&ft);
    ULARGE_INTEGER u;
    u.LowPart = ft.dwLowDateTime;
    u.HighPart = ft.dwHighDateTime;
    return (int64_t)(u.QuadPart / 10000000ULL) - 11644473600LL;
}

bool ParseIso8601Utc(const std::string& s, int64_t& out) {
    int y = 0, mo = 0, d = 0, h = 0, mi = 0, se = 0;
    if (sscanf(s.c_str(), "%4d-%2d-%2dT%2d:%2d:%2d", &y, &mo, &d, &h, &mi, &se) != 6) return false;
    if (y < 1970 || y > 2200 || mo < 1 || mo > 12 || d < 1 || d > 31) return false;
    SYSTEMTIME st = {};
    st.wYear = (WORD)y;
    st.wMonth = (WORD)mo;
    st.wDay = (WORD)d;
    st.wHour = (WORD)h;
    st.wMinute = (WORD)mi;
    st.wSecond = (WORD)se;
    FILETIME ft;
    if (!SystemTimeToFileTime(&st, &ft)) return false;
    ULARGE_INTEGER u;
    u.LowPart = ft.dwLowDateTime;
    u.HighPart = ft.dwHighDateTime;
    out = (int64_t)(u.QuadPart / 10000000ULL) - 11644473600LL;
    return true;
}

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

// ----------------------------------------------------------------- logging --
namespace {
std::mutex g_logMutex;
std::wstring g_logPath;
}  // namespace

void SetLogPath(const std::wstring& path) {
    std::lock_guard<std::mutex> lock(g_logMutex);
    g_logPath = path;
}

std::string GetLogPathUtf8() { return WideToUtf8(g_logPath); }

void LogMsg(const std::string& msg) {
    std::lock_guard<std::mutex> lock(g_logMutex);
    std::wstring path = g_logPath;
    if (path.empty()) path = JoinPath(GetCwd(), L"launcher.log");
    FILE* f = _wfopen(path.c_str(), L"ab");
    if (!f) return;
    SYSTEMTIME st;
    GetLocalTime(&st);
    char line[4096];
    int n = snprintf(line, sizeof(line), "[%04d-%02d-%02d %02d:%02d:%02d] %s\n", st.wYear,
                     st.wMonth, st.wDay, st.wHour, st.wMinute, st.wSecond, msg.c_str());
    if (n > 0) fwrite(line, 1, (size_t)n, f);
    fclose(f);
}

// ---------------------------------------------------------------- processes --
bool IsProcessRunning(DWORD pid) {
    HANDLE h = OpenProcess(SYNCHRONIZE, FALSE, pid);
    if (!h) return false;
    DWORD w = WaitForSingleObject(h, 0);
    CloseHandle(h);
    return w == WAIT_TIMEOUT;
}

std::vector<RunningProcess> SnapshotProcesses() {
    std::vector<RunningProcess> result;
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return result;
    PROCESSENTRY32W pe;
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            RunningProcess rp;
            rp.pid = pe.th32ProcessID;
            rp.name = pe.szExeFile;
            HANDLE h = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pe.th32ProcessID);
            if (h) {
                std::wstring buf(MAX_PATH, 0);
                DWORD size = (DWORD)buf.size();
                if (QueryFullProcessImageNameW(h, 0, &buf[0], &size)) {
                    buf.resize(size);
                    rp.imagePath = buf;
                }
                CloseHandle(h);
            }
            result.push_back(std::move(rp));
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    return result;
}

bool IsGameRunning(const std::wstring& installRoot,
                   const std::vector<std::wstring>& extraNames,
                   std::vector<RunningProcess>* matches) {
    DWORD self = GetCurrentProcessId();
    std::wstring versionsPrefix = JoinPath(NormalizePath(installRoot), L"versions");
    std::vector<RunningProcess> found;
    for (const auto& p : SnapshotProcesses()) {
        if (p.pid == self || p.pid == 0) continue;
        bool hit = false;
        if (!p.imagePath.empty()) {
            if (PathStartsWithCI(NormalizePath(p.imagePath), versionsPrefix)) hit = true;
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
        L"..\\client_config.json",
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
    s("last_username", g_config.lastUsername);
    if (root.has("remember_me")) g_config.rememberMe = root.boolean("remember_me", true);

    s("release_base_url", g_config.releaseBaseUrl);
    s("status_url", g_config.statusUrl);
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

bool SaveConfig(const std::wstring& explicitPath) {
    std::wstring path = explicitPath;
    if (path.empty()) path = g_configPath;
    if (path.empty()) path = DefaultConfigPath();

    JsonValue root = g_configExtraValid && g_configExtra.isObject() ? g_configExtra : JsonValue::Obj();
    root.set("server_ip", JsonValue::Str(WideToUtf8(g_config.serverIp)));
    root.set("server_port", JsonValue::Int(g_config.serverPort));
    root.set("api_port", JsonValue::Int(g_config.apiPort));
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
