// HPMMO launcher - shared utilities (Release pipeline updater support).
#pragma once

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>

#include <cstdint>
#include <string>
#include <vector>

namespace hpmmo {

// ---------------------------------------------------------------- strings --
std::wstring Utf8ToWide(const std::string& str);
std::string WideToUtf8(const std::wstring& wstr);
std::wstring ToLower(std::wstring s);
bool EqualsCI(const std::wstring& a, const std::wstring& b);
bool PathStartsWithCI(const std::wstring& path, const std::wstring& prefix);
std::string HexLower(const unsigned char* data, size_t len);
bool HexToBytes(const std::string& hex, std::vector<unsigned char>& out);
std::string Trim(const std::string& s);
std::string FormatU64(uint64_t v);
std::wstring FormatBytesW(uint64_t v);

// ------------------------------------------------------------------ paths --
std::wstring JoinPath(const std::wstring& a, const std::wstring& b);
std::wstring GetExePath();
std::wstring GetExeDir();
std::wstring GetCwd();
std::wstring TempDirPath();
std::wstring NormalizePath(const std::wstring& path);
bool FileExists(const std::wstring& path);
bool DirExists(const std::wstring& path);
uint64_t FileSizeOrZero(const std::wstring& path);
bool DeleteFileQuiet(const std::wstring& path);
bool RemoveDirRecursive(const std::wstring& dir);
bool CreateDirs(const std::wstring& dir);
bool WriteFileBytes(const std::wstring& path, const void* data, size_t len);
bool WriteFileAtomic(const std::wstring& path, const std::string& bytes);
bool ReadFileBytes(const std::wstring& path, std::string& out, uint64_t maxBytes = 0);
uint64_t FreeDiskSpaceBytes(const std::wstring& dir);
uint64_t DirSizeBytes(const std::wstring& dir);
// Recursively list files under dir (relative paths, forward slashes).
bool ListFilesRecursive(const std::wstring& dir, std::vector<std::wstring>& out, std::string& err);

// ------------------------------------------------------------------ version --
// Returns -1/0/1. Numeric dotted comparison; a pre-release suffix sorts lower.
int CompareVersions(const std::string& a, const std::string& b);
bool IsVersionString(const std::string& s);

// -------------------------------------------------------------------- time --
std::string TimeNowIso8601Utc();
int64_t UnixNowSeconds();
// Accepts 2026-10-04T12:00:00Z / with offset; returns unix seconds.
bool ParseIso8601Utc(const std::string& s, int64_t& out);
std::string FormatDuration(int64_t seconds);

// ----------------------------------------------------------------- logging --
void SetLogPath(const std::wstring& path);
void LogMsg(const std::string& msg);
std::string GetLogPathUtf8();

// ----------------------------------------------------------------- processes --
bool IsProcessRunning(DWORD pid);
struct RunningProcess {
    DWORD pid = 0;
    std::wstring name;
    std::wstring imagePath;
};
std::vector<RunningProcess> SnapshotProcesses();
// True when any process image lives under dirPrefix (case-insensitive) or its
// name is in extraNames. Never matches the current process.
bool IsGameRunning(const std::wstring& installRoot,
                   const std::vector<std::wstring>& extraNames,
                   std::vector<RunningProcess>* matches);

// ------------------------------------------------------------------- config --
struct AppConfig {
    // Existing launcher fields (behaviour preserved).
    std::wstring serverIp = L"213.250.145.75";
    int serverPort = 7777;
    int apiPort = 8081;
    std::wstring lastUsername;
    bool rememberMe = true;

    // the release pipeline updater fields (all optional; empty/0 disables the updater).
    std::wstring releaseBaseUrl;      // e.g. https://releases.example/hpmmo/stable
    std::wstring statusUrl;           // default: <release_base>/status.json
    std::wstring releasePublicKey;    // base64, 32-byte pinned Ed25519 public key
    std::wstring releasePublicKeyId;  // documented key id (informational)
    std::wstring releaseChannel;      // optional expected channel
    std::wstring pinnedSpkiSha256;    // hex sha256 of the pinned certificate SPKI
    std::wstring installRoot;         // empty = launcher exe directory
    std::wstring userDataDir;         // empty = <installRoot>/user
    std::wstring gameExeName;         // empty = auto-detect
    std::vector<std::wstring> gameProcessNames;  // extra process names to detect
    uint64_t stagingQuotaBytes = 0;   // 0 = only the real disk-free check
};

AppConfig& Config();
std::wstring DefaultConfigPath();
bool LoadConfig(const std::wstring& explicitPath = L"");
bool SaveConfig(const std::wstring& explicitPath = L"");
std::wstring LastLoadedConfigPath();

// ------------------------------------------------------------ base64 decoding --
bool Base64Decode(const std::string& in, std::vector<unsigned char>& out);

}  // namespace hpmmo
