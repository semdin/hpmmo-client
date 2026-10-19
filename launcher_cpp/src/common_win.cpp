// Win32 implementations of the platform functions declared in common.h.
// Moved verbatim from common.cpp when the core became portable (L0, 2026-10-19);
// common_posix.cpp is the Linux/macOS counterpart.
#include "common.h"

#include <tlhelp32.h>

#include <cstdio>
#include <cstring>
#include <mutex>

namespace hpmmo {

const char* HostPlatform() { return "windows-x86_64"; }

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

// ------------------------------------------------------------------ paths --
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
bool IsProcessRunning(uint32_t pid) {
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

// ------------------------------------------------------- portable helpers --
std::vector<std::wstring> ListSubdirs(const std::wstring& dir) {
    std::vector<std::wstring> out;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(JoinPath(dir, L"*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return out;
    do {
        if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) continue;
        std::wstring name = fd.cFileName;
        if (name == L"." || name == L"..") continue;
        out.push_back(name);
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return out;
}

bool MoveReplace(const std::wstring& from, const std::wstring& to, bool writeThrough) {
    DWORD flags = MOVEFILE_REPLACE_EXISTING | (writeThrough ? MOVEFILE_WRITE_THROUGH : 0);
    return MoveFileExW(from.c_str(), to.c_str(), flags) != 0;
}

bool MoveNoReplace(const std::wstring& from, const std::wstring& to) {
    return MoveFileExW(from.c_str(), to.c_str(), 0) != 0;
}

bool CopyFilePlain(const std::wstring& src, const std::wstring& dst) {
    return CopyFileW(src.c_str(), dst.c_str(), FALSE) != 0;
}

bool MakeExecutable(const std::wstring&) { return true; }

FILE* OpenFileW(const std::wstring& path, const wchar_t* mode) { return _wfopen(path.c_str(), mode); }

bool SeekFile64(FILE* f, uint64_t offset) { return _fseeki64(f, (long long)offset, SEEK_SET) == 0; }

uint64_t TellFile64(FILE* f) { return (uint64_t)_ftelli64(f); }

int LastErrorCode() { return (int)GetLastError(); }

std::wstring GetEnvW(const wchar_t* name) {
    DWORD n = GetEnvironmentVariableW(name, NULL, 0);
    if (n == 0) return L"";
    std::wstring v(n, 0);
    n = GetEnvironmentVariableW(name, &v[0], n);
    v.resize(n);
    return v;
}

std::wstring UserDataRoot() {
    wchar_t local[MAX_PATH] = {0};
    DWORD n = GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAX_PATH);
    if (n > 0 && n < MAX_PATH) return local;
    return L"";
}

uint32_t CurrentProcessId() { return (uint32_t)GetCurrentProcessId(); }

}  // namespace hpmmo
