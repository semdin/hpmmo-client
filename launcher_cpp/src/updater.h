// HPMMO launcher updater (Release pipeline): CHECK -> COMPARE -> DOWNLOAD -> VERIFY ->
// STAGE -> ACTIVATE -> LAUNCH, plus repair and launcher self-update.
#pragma once

#include <atomic>
#include <functional>
#include <string>
#include <vector>

#include "common.h"
#include "json.h"

namespace hpmmo {

// The running launcher's version. Compared against manifest.min_launcher_version.
constexpr const char* kLauncherVersion = "2.0.0";
// Default documented key id; the real id comes from client_config.json.
constexpr const char* kDefaultPinnedKeyId = "hpmmo-release-key-unprovisioned";

// Documented exit codes (also printed by --help).
enum ExitCode {
    kExitOk = 0,                 // success / up to date / repaired
    kExitUsage = 2,              // bad command line
    kExitConfig = 3,             // bad or missing configuration
    kExitNetwork = 10,           // manifest/status unreachable
    kExitSignature = 11,         // certificate pin or manifest signature failure
    kExitProtocol = 12,          // protocol incompatibility
    kExitDownload = 13,          // download failed after retries
    kExitDiskSpace = 14,         // insufficient disk space
    kExitGameRunning = 15,       // game process is running; refusing to write
    kExitIntegrity = 16,         // hash/size/archive integrity failure
    kExitMaintenance = 17,       // server state blocks launching (--for-launch)
    kExitSelfUpdateDone = 18,    // launcher self-update handed off
    kExitSelfUpdateFailed = 19,  // launcher self-update required but failed
    kExitLocalVerify = 20,       // --verify/--repair found an unhealthy install
    kExitCancelled = 21,         // cancelled by the user
};

struct CliOptions {
    std::string command;  // check | update | repair | verify | print-state | help
    std::wstring configPath;
    std::wstring installRoot;
    std::wstring userDataDir;
    std::wstring releaseBase;
    std::wstring statusUrl;
    std::wstring pinnedSpkiHex;
    std::wstring publicKeyB64;
    std::wstring publicKeyId;
    std::wstring channel;
    uint64_t stagingQuota = 0;
    std::string stopAfter;  // "" | check | download | verify | stage | activate
    bool forLaunch = false; // --check --for-launch
    bool cleanStaging = false;  // --clean-staging (remove stale .part/.tmp)
    // Internal helper modes.
    std::string helper;  // self-update-swap | print-cert-pin
    std::wstring helperPid;
    std::wstring helperTarget;
    std::wstring helperUrl;
    bool relaunch = false;
};

struct Artifact {
    std::string kind;
    std::string fromVersion;
    std::string url;
    std::string sha256;
    uint64_t size = 0;
};

struct ReleaseManifest {
    std::string channel, clientVersion, minLauncherVersion;
    std::string protocolVersion, protocolMin, protocolMax;
    std::string contentVersion, contentSha256;
    std::string serverVersion, schemaVersion, platform, publishedAt, releaseNotes;
    std::vector<Artifact> artifacts;
    std::string raw;     // exact signed bytes
    std::string sha256;  // hash of raw
};

struct StatusDoc {
    std::string state = "UNKNOWN";
    std::string release, previousRelease, since, message, until, protocolVersion;
};

struct InstalledState {
    bool present = false;
    std::string version;
    std::wstring dir;  // absolute
    std::string previous, activatedAt, manifestSha256;
};

struct UpdaterPaths {
    std::wstring installRoot;
    std::wstring stagingDir;
    std::wstring versionsDir;
    std::wstring userDir;       // stable user data; activation never touches it
    std::wstring currentFile;
    std::wstring journalFile;
    std::wstring stateFile;
    std::wstring logFile;
    std::wstring gameExe;       // resolved active game executable, if any
};

UpdaterPaths ComputePaths(const CliOptions& cli, const AppConfig& cfg);
std::wstring ReleaseBaseUrl(const CliOptions& cli, const AppConfig& cfg);
std::wstring StatusUrl(const CliOptions& cli, const AppConfig& cfg);

struct UpdaterContext {
    CliOptions cli;
    AppConfig cfg;
    UpdaterPaths paths;
    std::wstring releaseBase;
    std::wstring statusUrl;
    std::wstring pinnedSpkiHex;
    uint64_t stagingQuotaBytes = 0;
    std::string pinnedKeyB64;
    std::string keyId;
    std::atomic<bool>* cancel = nullptr;
    std::function<void(const std::wstring&)> status;  // progress text (GUI)
    bool interactive = false;
};

struct CommandResult {
    int code = kExitOk;
    std::string json;  // exactly one line
};

// Summary used by the GUI (and by --check).
struct CheckSummary {
    bool ok = false;
    std::string state = "UNKNOWN";
    std::string message, releaseVersion, previousRelease, since, until;
    std::string installedVersion, releaseNotes, channel, serverVersion;
    bool updateAvailable = false;
    bool updateRequired = false;
    bool maintenance = false;
    bool protocolOk = true;
    bool selfUpdateRequired = false;
    bool gameRunning = false;
    std::string error;
    int errorCode = kExitOk;
};

CommandResult RunCliCommand(const CliOptions& opts);

// Command-line parsing shared by the console CLI and the GUI launcher.
bool ParseCliArgs(int argc, char** argv, CliOptions& opts, std::string& err);
void PrintUsage(void* fileHandle);  // FILE* (void* keeps stdio out of the header)

// GUI-facing helpers.
CheckSummary DoCheck(const CliOptions& opts, AppConfig cfg, std::atomic<bool>* cancel,
                     const std::function<void(const std::wstring&)>& status);
// Runs the full update (or self-update); returns the exit code and a message.
CommandResult DoUpdate(const CliOptions& opts, AppConfig cfg, std::atomic<bool>* cancel,
                       const std::function<void(const std::wstring&)>& status);
CommandResult DoRepair(const CliOptions& opts, AppConfig cfg, std::atomic<bool>* cancel,
                       const std::function<void(const std::wstring&)>& status);
bool IsGameRunningNow(const UpdaterPaths& paths, const AppConfig& cfg,
                      std::vector<RunningProcess>* matches);
bool LaunchInstalledGame(const UpdaterPaths& paths, const AppConfig& cfg, bool solo,
                         const std::wstring& username, const std::wstring& ticket);

// Helper entry points (invoked via command-line flags).
int RunSelfUpdateSwap(const std::string& pidStr, const std::wstring& target,
                      const std::wstring& newExe, bool relaunch);
int RunPrintCertPin(const std::wstring& url);

}  // namespace hpmmo
