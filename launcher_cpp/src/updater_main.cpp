// Console entry point for the headless updater CLI.
#include "updater.h"

#include <cstdio>
#include <string>

int main(int argc, char** argv) {
    using namespace hpmmo;
    CliOptions opts;
    std::string err;
    if (!ParseCliArgs(argc, argv, opts, err)) {
        fprintf(stderr, "error: %s\n\n", err.c_str());
        PrintUsage(stderr);
        return kExitUsage;
    }
    if (opts.command == "help") {
        PrintUsage(stdout);
        return kExitOk;
    }
    if (opts.helper == "print-cert-pin") {
        return RunPrintCertPin(opts.helperUrl);
    }
    if (opts.helper == "self-update-swap") {
        return RunSelfUpdateSwap(WideToUtf8(opts.helperPid), opts.helperTarget, GetExePath(),
                                 opts.relaunch);
    }
    CommandResult r = RunCliCommand(opts);
    printf("%s\n", r.json.c_str());
    fflush(stdout);
    return r.code;
}
