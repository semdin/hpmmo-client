// Headless launcher updater CLI (console subsystem).
//
// Every command prints exactly one JSON line on stdout and exits with one of
// the documented codes below.
#include "updater.h"

#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

namespace hpmmo {

namespace {

bool NeedsValue(const char* flag, int i, int argc) {
    if (i + 1 >= argc) {
        fprintf(stderr, "missing value for %s\n", flag);
        return false;
    }
    return true;
}

}  // namespace

void PrintUsage(void* file) {
    FILE* f = (FILE*)file;
    fprintf(f, "HPMMO launcher updater (Phase 7)\n\n");
    fprintf(f, "Usage: HPMMO_UpdaterCLI <command> [options]\n\n");
    fprintf(f, "Commands:\n");
    fprintf(f, "  --check         Fetch status+manifest, compare versions, print one JSON line\n");
    fprintf(f, "  --update        Download, verify, stage, activate the newest release\n");
    fprintf(f, "  --repair        Verify the active install and replace missing/corrupt files\n");
    fprintf(f, "  --verify        Verify the active install against its authenticated record\n");
    fprintf(f, "  --print-state   Print local state (no network)\n\n");
    fprintf(f, "Options:\n");
    fprintf(f, "  --config <path>          client_config.json to use\n");
    fprintf(f, "  --install-root <dir>     install root (default: launcher exe dir / config)\n");
    fprintf(f, "  --user-dir <dir>         stable user-data directory (settings/logs/screenshots)\n");
    fprintf(f, "  --release-base <url>     HTTPS base URL holding manifest.json/status.json\n");
    fprintf(f, "  --status-url <url>       override the status document URL\n");
    fprintf(f, "  --pinned-spki <hex>      sha256 of the pinned certificate SPKI\n");
    fprintf(f, "  --public-key <base64>    pinned Ed25519 release public key (32 bytes)\n");
    fprintf(f, "  --public-key-id <id>     documented key id (informational)\n");
    fprintf(f, "  --channel <name>         expected release channel\n");
    fprintf(f, "  --staging-quota <bytes>  cap the staging directory (disk-space simulation)\n");
    fprintf(f, "  --for-launch             with --check: exit 12/17 when launching must be refused\n");
    fprintf(f, "  --stop-after <phase>     download|verify|stage (test hook for interruption)\n");
    fprintf(f, "  --clean-staging          delete staging/*.part and staging/*.tmp first\n");
    fprintf(f, "  --print-cert-pin <url>   print the observed certificate SPKI sha256 as JSON\n");
    fprintf(f, "  --self-update-swap <pid> <target.exe>  internal self-update helper\n");
    fprintf(f, "  --relaunch               helper: start <target.exe> after the swap\n");
    fprintf(f, "  --help                   this text\n\n");
    fprintf(f, "Exit codes:\n");
    fprintf(f, "   0 success (up to date / updated / repaired / healthy)\n");
    fprintf(f, "   1 internal error\n");
    fprintf(f, "   2 usage error\n");
    fprintf(f, "   3 configuration error (missing key, channel mismatch, ...)\n");
    fprintf(f, "  10 network error (manifest/status unreachable)\n");
    fprintf(f, "  11 certificate pin or manifest signature verification failed\n");
    fprintf(f, "  12 protocol incompatible (client range does not include the server)\n");
    fprintf(f, "  13 download failed after retries\n");
    fprintf(f, "  14 insufficient disk space\n");
    fprintf(f, "  15 the game is running; refusing to write\n");
    fprintf(f, "  16 integrity failure (hash/size/unsafe archive entry)\n");
    fprintf(f, "  17 server maintenance blocks launching (--check --for-launch)\n");
    fprintf(f, "  18 launcher self-update handed off (restart required)\n");
    fprintf(f, "  19 launcher self-update required but failed\n");
    fprintf(f, "  20 local install unhealthy (--verify/--repair)\n");
    fprintf(f, "  21 cancelled\n");
}

bool ParseCliArgs(int argc, char** argv, CliOptions& opts, std::string& err) {
    bool haveCommand = false;
    for (int i = 1; i < argc; i++) {
        std::string a = argv[i];
        auto value = [&](std::wstring& dst) -> bool {
            if (!NeedsValue(a.c_str(), i, argc)) return false;
            dst = Utf8ToWide(argv[++i]);
            return true;
        };
        if (a == "--help" || a == "-h" || a == "/?") {
            opts.command = "help";
            return true;
        } else if (a == "--check" || a == "--update" || a == "--repair" || a == "--verify" ||
                   a == "--print-state") {
            opts.command = a.substr(2);
            haveCommand = true;
        } else if (a == "--config") {
            if (!value(opts.configPath)) return false;
        } else if (a == "--install-root") {
            if (!value(opts.installRoot)) return false;
        } else if (a == "--user-dir") {
            if (!value(opts.userDataDir)) return false;
        } else if (a == "--release-base") {
            if (!value(opts.releaseBase)) return false;
        } else if (a == "--status-url") {
            if (!value(opts.statusUrl)) return false;
        } else if (a == "--pinned-spki") {
            if (!value(opts.pinnedSpkiHex)) return false;
        } else if (a == "--public-key") {
            if (!value(opts.publicKeyB64)) return false;
        } else if (a == "--public-key-id") {
            if (!value(opts.publicKeyId)) return false;
        } else if (a == "--channel") {
            if (!value(opts.channel)) return false;
        } else if (a == "--staging-quota") {
            std::wstring v;
            if (!value(v)) return false;
            try {
                opts.stagingQuota = std::stoull(WideToUtf8(v));
            } catch (...) {
                err = "invalid --staging-quota";
                return false;
            }
        } else if (a == "--stop-after") {
            std::wstring v;
            if (!value(v)) return false;
            opts.stopAfter = WideToUtf8(v);
            if (opts.stopAfter != "download" && opts.stopAfter != "verify" &&
                opts.stopAfter != "stage") {
                err = "invalid --stop-after (download|verify|stage)";
                return false;
            }
        } else if (a == "--for-launch") {
            opts.forLaunch = true;
        } else if (a == "--clean-staging") {
            opts.cleanStaging = true;
        } else if (a == "--relaunch") {
            opts.relaunch = true;
        } else if (a == "--print-cert-pin") {
            if (!value(opts.helperUrl)) return false;
            opts.helper = "print-cert-pin";
        } else if (a == "--self-update-swap") {
            if (!value(opts.helperPid)) return false;
            if (!value(opts.helperTarget)) return false;
            opts.helper = "self-update-swap";
        } else {
            err = "unknown argument: " + a;
            return false;
        }
    }
    (void)haveCommand;
    if (!opts.helper.empty()) return true;
    if (opts.command.empty()) {
        err = "no command given";
        return false;
    }
    return true;
}

}  // namespace hpmmo
