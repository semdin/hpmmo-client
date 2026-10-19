// POSIX (Linux, macOS) implementations of the platform functions declared in
// common.h; common_win.cpp is the Windows counterpart. Paths stay std::wstring
// in the core and are UTF-8 at every system call made here.
#include "common.h"

#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <mutex>

#ifdef __APPLE__
#include <libproc.h>
#include <mach-o/dyld.h>
#endif

namespace hpmmo {

const char* HostPlatform() {
#if defined(__APPLE__)
    return "macos-universal";
#elif defined(__aarch64__)
    return "linux-arm64";
#else
    return "linux-x86_64";
#endif
}

namespace {

std::string U8(const std::wstring& p) { return WideToUtf8(p); }

bool StatPath(const std::wstring& path, struct stat& st) { return stat(U8(path).c_str(), &st) == 0; }

}  // namespace

// ---------------------------------------------------------------- strings --
// wchar_t is UTF-32 here; invalid input becomes U+FFFD instead of failing.
std::wstring Utf8ToWide(const std::string& str) {
    std::wstring out;
    out.reserve(str.size());
    size_t i = 0;
    while (i < str.size()) {
        unsigned char c = (unsigned char)str[i];
        uint32_t cp = 0;
        size_t extra = 0;
        if (c < 0x80) {
            cp = c;
        } else if ((c & 0xE0) == 0xC0) {
            cp = c & 0x1F;
            extra = 1;
        } else if ((c & 0xF0) == 0xE0) {
            cp = c & 0x0F;
            extra = 2;
        } else if ((c & 0xF8) == 0xF0) {
            cp = c & 0x07;
            extra = 3;
        } else {
            out.push_back(0xFFFD);
            i++;
            continue;
        }
        if (extra && i + extra >= str.size()) {  // truncated sequence
            out.push_back(0xFFFD);
            break;
        }
        bool ok = true;
        for (size_t k = 1; k <= extra; k++) {
            unsigned char cc = (unsigned char)str[i + k];
            if ((cc & 0xC0) != 0x80) {
                ok = false;
                break;
            }
            cp = (cp << 6) | (cc & 0x3F);
        }
        if (!ok) {
            out.push_back(0xFFFD);
            i++;
            continue;
        }
        out.push_back((wchar_t)cp);
        i += extra + 1;
    }
    return out;
}

std::string WideToUtf8(const std::wstring& wstr) {
    std::string out;
    out.reserve(wstr.size());
    for (wchar_t wc : wstr) {
        uint32_t cp = (uint32_t)wc;
        if (cp < 0x80) {
            out.push_back((char)cp);
        } else if (cp < 0x800) {
            out.push_back((char)(0xC0 | (cp >> 6)));
            out.push_back((char)(0x80 | (cp & 0x3F)));
        } else if (cp < 0x10000) {
            out.push_back((char)(0xE0 | (cp >> 12)));
            out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back((char)(0x80 | (cp & 0x3F)));
        } else if (cp < 0x110000) {
            out.push_back((char)(0xF0 | (cp >> 18)));
            out.push_back((char)(0x80 | ((cp >> 12) & 0x3F)));
            out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
            out.push_back((char)(0x80 | (cp & 0x3F)));
        }
    }
    return out;
}

// ------------------------------------------------------------------ paths --
std::wstring GetExePath() {
    // Inside an AppImage the binary runs from a temporary mount; the file the
    // user owns (and that self-update must replace) is $APPIMAGE.
    const char* appimage = getenv("APPIMAGE");
    if (appimage && *appimage && access(appimage, F_OK) == 0) return Utf8ToWide(appimage);
#ifdef __APPLE__
    uint32_t size = 0;
    _NSGetExecutablePath(nullptr, &size);
    std::string buf(size, '\0');
    if (_NSGetExecutablePath(&buf[0], &size) != 0) return L"";
    buf.resize(strlen(buf.c_str()));
    char real[PATH_MAX];
    if (realpath(buf.c_str(), real)) return Utf8ToWide(real);
    return Utf8ToWide(buf);
#else
    std::string buf(4096, '\0');
    ssize_t n = readlink("/proc/self/exe", &buf[0], buf.size() - 1);
    if (n <= 0) return L"";
    buf.resize((size_t)n);
    return Utf8ToWide(buf);
#endif
}

std::wstring GetCwd() {
    char buf[PATH_MAX];
    if (!getcwd(buf, sizeof(buf))) return L"";
    return Utf8ToWide(buf);
}

std::wstring TempDirPath() {
    const char* t = getenv("TMPDIR");
    std::string dir = (t && *t) ? t : "/tmp";
    while (dir.size() > 1 && dir.back() == '/') dir.pop_back();
    return Utf8ToWide(dir);
}

// Lexical: absolute, "." and ".." resolved, no trailing slash. Symlinks are
// not resolved (the Windows version does not resolve junctions either).
std::wstring NormalizePath(const std::wstring& path) {
    if (path.empty()) return L"";
    std::wstring p = path;
    for (auto& c : p)
        if (c == L'\\') c = L'/';
    if (p[0] != L'/') p = GetCwd() + L"/" + p;
    std::vector<std::wstring> parts;
    size_t start = 0;
    while (start <= p.size()) {
        size_t end = p.find(L'/', start);
        std::wstring part = p.substr(start, end == std::wstring::npos ? std::wstring::npos : end - start);
        if (part.empty() || part == L".") {
        } else if (part == L"..") {
            if (!parts.empty()) parts.pop_back();
        } else {
            parts.push_back(part);
        }
        if (end == std::wstring::npos) break;
        start = end + 1;
    }
    std::wstring out;
    for (const auto& part : parts) out += L"/" + part;
    return out.empty() ? L"/" : out;
}

bool FileExists(const std::wstring& path) {
    struct stat st;
    return StatPath(path, st) && S_ISREG(st.st_mode);
}

bool DirExists(const std::wstring& path) {
    struct stat st;
    return StatPath(path, st) && S_ISDIR(st.st_mode);
}

uint64_t FileSizeOrZero(const std::wstring& path) {
    struct stat st;
    if (!StatPath(path, st) || !S_ISREG(st.st_mode)) return 0;
    return (uint64_t)st.st_size;
}

bool DeleteFileQuiet(const std::wstring& path) { return unlink(U8(path).c_str()) == 0; }

bool RemoveDirRecursive(const std::wstring& dir) {
    if (!DirExists(dir)) return true;
    std::string d = U8(dir);
    DIR* h = opendir(d.c_str());
    if (!h) return false;
    bool ok = true;
    while (struct dirent* e = readdir(h)) {
        std::string name = e->d_name;
        if (name == "." || name == "..") continue;
        std::string full = d + "/" + name;
        struct stat st;
        if (lstat(full.c_str(), &st) != 0) {
            ok = false;
            continue;
        }
        if (S_ISDIR(st.st_mode)) {
            if (!RemoveDirRecursive(Utf8ToWide(full))) ok = false;
        } else if (unlink(full.c_str()) != 0) {
            ok = false;
        }
    }
    closedir(h);
    if (rmdir(d.c_str()) != 0) ok = false;
    return ok;
}

bool CreateDirs(const std::wstring& dir) {
    if (dir.empty()) return false;
    if (DirExists(dir)) return true;
    std::string norm = U8(NormalizePath(dir));
    size_t pos = 1;
    while (true) {
        pos = norm.find('/', pos);
        std::string part = (pos == std::string::npos) ? norm : norm.substr(0, pos);
        if (!part.empty() && mkdir(part.c_str(), 0755) != 0 && errno != EEXIST) return false;
        if (pos == std::string::npos) break;
        pos++;
    }
    return DirExists(Utf8ToWide(norm));
}

bool WriteFileBytes(const std::wstring& path, const void* data, size_t len) {
    std::string p = U8(path);
    int fd = open(p.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0644);
    if (fd < 0) return false;
    const unsigned char* b = (const unsigned char*)data;
    size_t left = len;
    bool ok = true;
    while (left > 0) {
        ssize_t n = write(fd, b, left);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) {
            ok = false;
            break;
        }
        b += n;
        left -= (size_t)n;
    }
    if (fsync(fd) != 0) ok = false;
    close(fd);
    if (!ok) unlink(p.c_str());
    return ok;
}

bool WriteFileAtomic(const std::wstring& path, const std::string& bytes) {
    std::wstring tmp = path + L".tmp" + std::to_wstring(getpid());
    if (!WriteFileBytes(tmp, bytes.data(), bytes.size())) {
        DeleteFileQuiet(tmp);
        return false;
    }
    if (rename(U8(tmp).c_str(), U8(path).c_str()) != 0) {
        DeleteFileQuiet(tmp);
        return false;
    }
    return true;
}

bool ReadFileBytes(const std::wstring& path, std::string& out, uint64_t maxBytes) {
    out.clear();
    FILE* f = fopen(U8(path).c_str(), "rb");
    if (!f) return false;
    struct stat st;
    if (fstat(fileno(f), &st) != 0 || !S_ISREG(st.st_mode)) {
        fclose(f);
        return false;
    }
    if (maxBytes && (uint64_t)st.st_size > maxBytes) {
        fclose(f);
        return false;
    }
    out.resize((size_t)st.st_size);
    bool ok = out.empty() || fread(&out[0], 1, out.size(), f) == out.size();
    fclose(f);
    if (!ok) out.clear();
    return ok;
}

uint64_t FreeDiskSpaceBytes(const std::wstring& dir) {
    struct statvfs sv;
    if (statvfs(U8(dir).c_str(), &sv) != 0) return 0;
    return (uint64_t)sv.f_bavail * (uint64_t)sv.f_frsize;
}

namespace {

// Walks regular files below dir without following symlinks.
template <typename Fn>
void WalkFiles(const std::string& dir, Fn&& fn) {
    DIR* h = opendir(dir.c_str());
    if (!h) return;
    while (struct dirent* e = readdir(h)) {
        std::string name = e->d_name;
        if (name == "." || name == "..") continue;
        std::string full = dir + "/" + name;
        struct stat st;
        if (lstat(full.c_str(), &st) != 0) continue;
        if (S_ISDIR(st.st_mode)) {
            WalkFiles(full, fn);
        } else if (S_ISREG(st.st_mode)) {
            fn(full, (uint64_t)st.st_size);
        }
    }
    closedir(h);
}

}  // namespace

uint64_t DirSizeBytes(const std::wstring& dir) {
    uint64_t total = 0;
    WalkFiles(U8(dir), [&](const std::string&, uint64_t size) { total += size; });
    return total;
}

bool ListFilesRecursive(const std::wstring& dir, std::vector<std::wstring>& out, std::string& err) {
    out.clear();
    if (!DirExists(dir)) {
        err = "directory does not exist";
        return false;
    }
    std::string root = U8(NormalizePath(dir));
    WalkFiles(root, [&](const std::string& full, uint64_t) {
        std::string rel = full.substr(root.size());
        if (!rel.empty() && rel[0] == '/') rel.erase(0, 1);
        out.push_back(Utf8ToWide(rel));
    });
    return true;
}

std::vector<std::wstring> ListSubdirs(const std::wstring& dir) {
    std::vector<std::wstring> out;
    std::string d = U8(dir);
    DIR* h = opendir(d.c_str());
    if (!h) return out;
    while (struct dirent* e = readdir(h)) {
        std::string name = e->d_name;
        if (name == "." || name == "..") continue;
        struct stat st;
        if (lstat((d + "/" + name).c_str(), &st) == 0 && S_ISDIR(st.st_mode)) out.push_back(Utf8ToWide(name));
    }
    closedir(h);
    return out;
}

bool MoveReplace(const std::wstring& from, const std::wstring& to, bool writeThrough) {
    if (rename(U8(from).c_str(), U8(to).c_str()) != 0) return false;
    if (writeThrough) {
        std::wstring parent = to.substr(0, to.find_last_of(L'/'));
        int fd = open(U8(parent.empty() ? L"/" : parent).c_str(), O_RDONLY | O_CLOEXEC);
        if (fd >= 0) {
            fsync(fd);
            close(fd);
        }
    }
    return true;
}

bool MoveNoReplace(const std::wstring& from, const std::wstring& to) {
    struct stat st;
    if (lstat(U8(to).c_str(), &st) == 0) {
        errno = EEXIST;
        return false;
    }
    return rename(U8(from).c_str(), U8(to).c_str()) == 0;
}

bool CopyFilePlain(const std::wstring& src, const std::wstring& dst) {
    FILE* in = fopen(U8(src).c_str(), "rb");
    if (!in) return false;
    struct stat st;
    mode_t mode = 0644;
    if (fstat(fileno(in), &st) == 0) mode = st.st_mode & 0777;
    std::string d = U8(dst);
    int fd = open(d.c_str(), O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, mode);
    if (fd < 0) {
        fclose(in);
        return false;
    }
    std::vector<char> buf(1 << 20);
    bool ok = true;
    size_t got;
    while ((got = fread(buf.data(), 1, buf.size(), in)) > 0) {
        const char* p = buf.data();
        size_t left = got;
        while (left > 0) {
            ssize_t n = write(fd, p, left);
            if (n < 0 && errno == EINTR) continue;
            if (n <= 0) {
                ok = false;
                break;
            }
            p += n;
            left -= (size_t)n;
        }
        if (!ok) break;
    }
    if (ferror(in)) ok = false;
    fclose(in);
    fchmod(fd, mode);
    if (close(fd) != 0) ok = false;
    if (!ok) unlink(d.c_str());
    return ok;
}

bool MakeExecutable(const std::wstring& path) {
    struct stat st;
    std::string p = U8(path);
    if (stat(p.c_str(), &st) != 0) return false;
    return chmod(p.c_str(), (st.st_mode & 0777) | 0111) == 0;
}

FILE* OpenFileW(const std::wstring& path, const wchar_t* mode) {
    return fopen(U8(path).c_str(), U8(mode).c_str());
}

bool SeekFile64(FILE* f, uint64_t offset) { return fseeko(f, (off_t)offset, SEEK_SET) == 0; }

uint64_t TellFile64(FILE* f) { return (uint64_t)ftello(f); }

int LastErrorCode() { return errno; }

std::wstring GetEnvW(const wchar_t* name) {
    const char* v = getenv(U8(name).c_str());
    return v ? Utf8ToWide(v) : L"";
}

std::wstring UserDataRoot() {
    std::string home = getenv("HOME") ? getenv("HOME") : "";
#ifdef __APPLE__
    if (home.empty()) return L"";
    return Utf8ToWide(home + "/Library/Application Support");
#else
    const char* xdg = getenv("XDG_DATA_HOME");
    if (xdg && *xdg == '/') return Utf8ToWide(xdg);
    if (home.empty()) return L"";
    return Utf8ToWide(home + "/.local/share");
#endif
}

uint32_t CurrentProcessId() { return (uint32_t)getpid(); }

// -------------------------------------------------------------------- time --
std::string TimeNowIso8601Utc() {
    time_t now = time(nullptr);
    struct tm t;
    gmtime_r(&now, &t);
    char buf[40];
    snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02dZ", t.tm_year + 1900, t.tm_mon + 1,
             t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec);
    return buf;
}

int64_t UnixNowSeconds() { return (int64_t)time(nullptr); }

bool ParseIso8601Utc(const std::string& s, int64_t& out) {
    int y = 0, mo = 0, d = 0, h = 0, mi = 0, se = 0;
    if (sscanf(s.c_str(), "%4d-%2d-%2dT%2d:%2d:%2d", &y, &mo, &d, &h, &mi, &se) != 6) return false;
    if (y < 1970 || y > 2200 || mo < 1 || mo > 12 || d < 1 || d > 31) return false;
    if (h < 0 || h > 23 || mi < 0 || mi > 59 || se < 0 || se > 60) return false;
    struct tm t = {};
    t.tm_year = y - 1900;
    t.tm_mon = mo - 1;
    t.tm_mday = d;
    t.tm_hour = h;
    t.tm_min = mi;
    t.tm_sec = se;
    out = (int64_t)timegm(&t);
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
    FILE* f = fopen(U8(path).c_str(), "ab");
    if (!f) return;
    time_t now = time(nullptr);
    struct tm t;
    localtime_r(&now, &t);
    char line[4096];
    int n = snprintf(line, sizeof(line), "[%04d-%02d-%02d %02d:%02d:%02d] %s\n", t.tm_year + 1900,
                     t.tm_mon + 1, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, msg.c_str());
    if (n > 0) fwrite(line, 1, (size_t)(n < (int)sizeof(line) ? n : (int)sizeof(line) - 1), f);
    fclose(f);
}

// ---------------------------------------------------------------- processes --
bool IsProcessRunning(uint32_t pid) {
    if (pid == 0) return false;
    if (kill((pid_t)pid, 0) == 0) return true;
    return errno == EPERM;  // exists, owned by someone else
}

std::vector<RunningProcess> SnapshotProcesses() {
    std::vector<RunningProcess> result;
#ifdef __APPLE__
    int count = proc_listallpids(nullptr, 0);
    if (count <= 0) return result;
    std::vector<pid_t> pids((size_t)count + 64);
    count = proc_listallpids(pids.data(), (int)(pids.size() * sizeof(pid_t)));
    for (int i = 0; i < count; i++) {
        if (pids[i] <= 0) continue;
        RunningProcess rp;
        rp.pid = (uint32_t)pids[i];
        char path[PROC_PIDPATHINFO_MAXSIZE];
        if (proc_pidpath(pids[i], path, sizeof(path)) > 0) {
            rp.imagePath = Utf8ToWide(path);
            const char* slash = strrchr(path, '/');
            rp.name = Utf8ToWide(slash ? slash + 1 : path);
        }
        result.push_back(std::move(rp));
    }
#else
    DIR* h = opendir("/proc");
    if (!h) return result;
    while (struct dirent* e = readdir(h)) {
        const char* n = e->d_name;
        if (*n < '1' || *n > '9') continue;
        bool numeric = true;
        for (const char* c = n; *c; c++)
            if (*c < '0' || *c > '9') numeric = false;
        if (!numeric) continue;
        RunningProcess rp;
        rp.pid = (uint32_t)strtoul(n, nullptr, 10);
        std::string base = std::string("/proc/") + n;
        char buf[4096];
        ssize_t len = readlink((base + "/exe").c_str(), buf, sizeof(buf) - 1);
        if (len > 0) {
            buf[len] = 0;
            std::string exe = buf;
            const std::string deleted = " (deleted)";
            if (exe.size() > deleted.size() && exe.compare(exe.size() - deleted.size(), deleted.size(), deleted) == 0)
                exe.resize(exe.size() - deleted.size());
            rp.imagePath = Utf8ToWide(exe);
            size_t slash = exe.find_last_of('/');
            rp.name = Utf8ToWide(slash == std::string::npos ? exe : exe.substr(slash + 1));
        } else if (FILE* f = fopen((base + "/comm").c_str(), "rb")) {
            size_t got = fread(buf, 1, sizeof(buf) - 1, f);
            fclose(f);
            buf[got] = 0;
            std::string comm = Trim(buf);
            rp.name = Utf8ToWide(comm);
        }
        result.push_back(std::move(rp));
    }
    closedir(h);
#endif
    return result;
}

}  // namespace hpmmo
