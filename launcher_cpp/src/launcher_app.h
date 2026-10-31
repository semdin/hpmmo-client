// Launcher logic shared by the UI shells (main.cpp on Windows, main_sdl.cpp on
// Linux/macOS): what the launcher is doing (Phase), the update and server
// status workers, and the play / repair actions. Shells draw TakeSnapshot(),
// forward input here, and get told to repaint through Hooks.
#pragma once

#include <cstdint>
#include <functional>
#include <string>

#include "common.h"

namespace hpmmo {
namespace app {

enum class Phase {
    Checking,       // reading the manifest
    Downloading,    // fetching the client package (progress known)
    Installing,     // verifying / extracting / activating
    SelfUpdating,   // a newer launcher is being installed; we exit
    Ready,          // installed and current: PLAY
    ReadyStale,     // installed, but the update check or the update failed
    Failed,         // nothing installed and the update failed: RETRY
    GameRunning,    // the game is open
};

struct Snapshot {
    Phase phase;
    std::wstring title, detail, notes, server;
    std::string installed, release;
};

// Called from worker threads: the shell must marshal them to its UI thread.
struct Hooks {
    std::function<void()> refresh;             // state changed: repaint
    std::function<void()> exitForSelfUpdate;   // the update helper took over: quit
};

// The game's name as the shells draw it (crest, window title). Files, folders
// and executables keep the HPMMO name: installs and self-updates depend on it.
inline constexpr const wchar_t* kGameTitle = L"Thousand Realms";

// How often the shells poll the server status and look for a new release.
constexpr unsigned kStatusPollMs = 30000;
constexpr unsigned kRecheckMs = 10 * 60 * 1000;
constexpr unsigned kGamePollMs = 2500;

void Init(const AppConfig& cfg, Hooks hooks);

Snapshot TakeSnapshot();
Phase CurrentPhase();
std::wstring PlayLabel(Phase p);
bool PlayEnabled(Phase p);
uint64_t ProgressDone();
uint64_t ProgressTotal();

void StartWorker(bool repair = false);   // check -> (self-update | update) -> ready
void StartStatusPoll();
void OnRecheckTimer();
void RequestRepair();
void Cancel();                           // stop a running download (on exit)

// Starts the installed game; true when it is running (the shell then hides
// itself and calls PollGame every kGamePollMs until it returns false).
bool OnPlay();
bool PollGame();

}  // namespace app
}  // namespace hpmmo
