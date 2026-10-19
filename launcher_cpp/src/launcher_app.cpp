// Launcher logic shared by every UI shell (Windows GDI+ main.cpp, SDL
// main_sdl.cpp): the update/status workers, the play action and the state the
// shells draw. Moved verbatim from main.cpp (L2, 2026-10-19); the shells only
// draw TakeSnapshot() and forward input.
#include "launcher_app.h"

#include <algorithm>
#include <atomic>
#include <mutex>
#include <string>
#include <thread>

#include "http.h"
#include "json.h"
#include "updater.h"

namespace hpmmo {
namespace app {

namespace {

Hooks g_Hooks;

void PostRefresh() {
    if (g_Hooks.refresh) g_Hooks.refresh();
}

}  // namespace


namespace {
std::mutex g_Mutex;
Phase g_Phase = Phase::Checking;
std::wstring g_Title = L"Güncellemeler kontrol ediliyor";
std::wstring g_Detail;
std::wstring g_Notes;          // release notes of the newest release
std::string g_InstalledVersion;
std::string g_ReleaseVersion;
std::wstring g_ServerState = L"UNKNOWN";  // ONLINE | MAINTENANCE | OFFLINE | UNKNOWN
std::atomic<uint64_t> g_Done{0};
std::atomic<uint64_t> g_Total{0};
std::atomic<bool> g_WorkerBusy{false};
std::atomic<bool> g_StatusBusy{false};
std::atomic<bool> g_Cancel{false};

hpmmo::AppConfig g_Cfg;
}  // namespace

Snapshot TakeSnapshot() {
    std::lock_guard<std::mutex> lock(g_Mutex);
    return Snapshot{g_Phase, g_Title, g_Detail, g_Notes, g_ServerState, g_InstalledVersion, g_ReleaseVersion};
}

std::wstring PlayLabel(Phase p) {
    switch (p) {
        case Phase::Ready:
        case Phase::ReadyStale: return L"OYNA";
        case Phase::Failed: return L"TEKRAR DENE";
        case Phase::GameRunning: return L"OYUN AÇIK";
        case Phase::Downloading:
        case Phase::Installing:
        case Phase::SelfUpdating: return L"GÜNCELLENİYOR";
        default: return L"KONTROL…";
    }
}

bool PlayEnabled(Phase p) {
    return p == Phase::Ready || p == Phase::ReadyStale || p == Phase::Failed;
}

void SetState(Phase p, const std::wstring& title, const std::wstring& detail) {
    {
        std::lock_guard<std::mutex> lock(g_Mutex);
        g_Phase = p;
        g_Title = title;
        g_Detail = detail;
    }
    PostRefresh();
}

Phase CurrentPhase() {
    std::lock_guard<std::mutex> lock(g_Mutex);
    return g_Phase;
}

// ------------------------------------------------------------------ workers
// "24.2 MB": one decimal, integer arithmetic only (no printf dialect issues).
std::wstring BytesText(uint64_t v) {
    const wchar_t* unit = L"KB";
    uint64_t div = 1024;
    if (v >= (1ull << 30)) {
        unit = L"GB";
        div = 1ull << 30;
    } else if (v >= (1ull << 20)) {
        unit = L"MB";
        div = 1ull << 20;
    }
    uint64_t tenths = (v * 10 + div / 2) / div;
    return std::to_wstring(tenths / 10) + L"." + std::to_wstring(tenths % 10) + L" " + unit;
}

std::wstring FriendlyError(const std::string& raw, int code) {
    // Linux loads libcurl at run time (http_curl.cpp); a system without it
    // would otherwise read as a network problem.
    if (raw.find("libcurl is not installed") != std::string::npos)
        return L"Sistemde libcurl bulunamadı. \"curl\" paketini kurup launcher'ı yeniden aç.";
    switch (code) {
        case hpmmo::kExitNetwork: return L"Güncelleme sunucusuna ulaşılamadı. İnternet bağlantını kontrol et.";
        case hpmmo::kExitSignature: return L"Güncelleme doğrulanamadı (imza/sertifika hatası).";
        case hpmmo::kExitDiskSpace: return L"Diskte yeterli boş alan yok.";
        case hpmmo::kExitGameRunning: return L"Oyun açıkken güncelleme yapılamaz. Önce oyunu kapat.";
        case hpmmo::kExitIntegrity: return L"İndirilen dosya bozuk görünüyor; tekrar denenecek.";
        case hpmmo::kExitDownload: return L"İndirme tamamlanamadı. Bağlantını kontrol edip tekrar dene.";
        case hpmmo::kExitProtocol: return L"Bu sürüm sunucuyla uyumsuz; yeni bir güncelleme bekleniyor.";
        case hpmmo::kExitSelfUpdateFailed: return L"Launcher kendini güncelleyemedi.";
        case hpmmo::kExitConfig: return L"Launcher yapılandırması hatalı.";
        default: break;
    }
    if (raw.empty()) return L"Bilinmeyen bir hata oluştu.";
    return hpmmo::Utf8ToWide(raw);
}

bool InstalledGamePresent() {
    hpmmo::UpdaterPaths paths = hpmmo::ResolvePathsForGui(g_Cfg);
    return !paths.gameExe.empty() && hpmmo::FileExists(paths.gameExe);
}

void ApplySummary(const hpmmo::CheckSummary& s) {
    std::lock_guard<std::mutex> lock(g_Mutex);
    g_InstalledVersion = s.installedVersion;
    g_ReleaseVersion = s.releaseVersion;
    g_Notes = hpmmo::Utf8ToWide(s.releaseNotes);
    // The server pill belongs to StatusWorker (it understands services that
    // predate /api/status); the check may only add "under maintenance".
    if (s.maintenance) g_ServerState = L"MAINTENANCE";
}

std::wstring ReadyDetail() {
    std::lock_guard<std::mutex> lock(g_Mutex);
    std::wstring d = L"Sürüm " + hpmmo::Utf8ToWide(g_InstalledVersion);
    if (g_ServerState == L"MAINTENANCE") d += L"  ·  Sunucu şu an bakımda; bakım bitince giriş yapabilirsin.";
    else if (g_ServerState == L"OFFLINE") d += L"  ·  Oyun sunucusuna şu an ulaşılamıyor.";
    else d += L"  ·  Her şey hazır.";
    return d;
}

// Check -> (self-update | download + install) -> ready. Runs on its own thread.
void UpdateWorker(bool repair) {
    g_Cancel = false;
    hpmmo::CliOptions cli;
    auto status = [](const std::wstring&) {};
    auto progress = [](uint64_t done, uint64_t total) {
        g_Done = done;
        g_Total = total;
        Phase p = CurrentPhase();
        if (p == Phase::Downloading || p == Phase::SelfUpdating) {
            int pct = total ? (int)((done * 100) / total) : 0;
            std::wstring d = L"%" + std::to_wstring(pct) + L"  ·  " + BytesText(done) + L" / " + BytesText(total);
            std::lock_guard<std::mutex> lock(g_Mutex);
            g_Detail = d;
        }
        PostRefresh();
    };

    if (repair) {
        g_Done = 0;
        g_Total = 0;
        SetState(Phase::Installing, L"Oyun dosyaları onarılıyor", L"Dosyalar doğrulanıyor ve eksikler indiriliyor…");
        hpmmo::CommandResult r = hpmmo::DoRepair(cli, g_Cfg, &g_Cancel, status);
        if (r.code != hpmmo::kExitOk) {
            hpmmo::LogMsg("[Launcher] repair failed: " + r.json);
        }
    }

    SetState(Phase::Checking, L"Güncellemeler kontrol ediliyor", L"Yeni sürüm olup olmadığına bakılıyor…");
    hpmmo::CheckSummary s = hpmmo::DoCheck(cli, g_Cfg, &g_Cancel, status);
    if (!s.ok) {
        hpmmo::LogMsg("[Launcher] update check failed: " + s.error);
        if (InstalledGamePresent()) {
            SetState(Phase::ReadyStale, L"Güncelleme kontrol edilemedi",
                     FriendlyError(s.error, s.errorCode) + L" Mevcut sürümle oynayabilirsin.");
        } else {
            SetState(Phase::Failed, L"Oyun indirilemedi", FriendlyError(s.error, s.errorCode));
        }
        g_WorkerBusy = false;
        PostRefresh();
        return;
    }
    ApplySummary(s);

    if (s.gameRunning) {
        SetState(Phase::GameRunning, L"Oyun şu an açık", L"Güncelleme, oyun kapandıktan sonra yapılacak.");
        g_WorkerBusy = false;
        PostRefresh();
        return;
    }

    if (s.selfUpdateRequired || s.updateRequired || s.updateAvailable) {
        g_Done = 0;
        g_Total = 0;
        if (s.selfUpdateRequired) {
            SetState(Phase::SelfUpdating, L"Launcher güncelleniyor", L"Yeni launcher indiriliyor…");
        } else {
            std::wstring what = s.installedVersion.empty() ? L"Oyun indiriliyor" : L"Güncelleme indiriliyor";
            SetState(Phase::Downloading, what + L"  ·  v" + hpmmo::Utf8ToWide(s.releaseVersion), L"Başlıyor…");
        }
        std::atomic<bool> installingShown{false};
        auto status2 = [&](const std::wstring& text) {
            if (!installingShown && text.find(L"Verifying") != std::wstring::npos) {
                installingShown = true;
                SetState(Phase::Installing, L"Güncelleme kuruluyor", L"Dosyalar doğrulanıyor ve yerleştiriliyor…");
            }
        };
        hpmmo::CommandResult r = hpmmo::DoUpdate(cli, g_Cfg, &g_Cancel, status2, progress);
        if (r.code == hpmmo::kExitSelfUpdateDone) {
            SetState(Phase::SelfUpdating, L"Launcher güncellendi", L"Yeniden başlatılıyor…");
            if (g_Hooks.exitForSelfUpdate) g_Hooks.exitForSelfUpdate();
            return;
        }
        if (r.code != hpmmo::kExitOk) {
            hpmmo::LogMsg("[Launcher] update failed: " + r.json);
            std::string message;
            hpmmo::JsonValue root;
            std::string perr;
            if (hpmmo::JsonValue::Parse(r.json, root, perr) && root.isObject()) message = root.str("message");
            if (InstalledGamePresent() && r.code != hpmmo::kExitProtocol) {
                SetState(Phase::ReadyStale, L"Güncelleme tamamlanamadı",
                         FriendlyError(message, r.code) + L" Mevcut sürümle oynayabilirsin.");
            } else {
                SetState(Phase::Failed, L"Güncelleme başarısız", FriendlyError(message, r.code));
            }
            g_WorkerBusy = false;
            PostRefresh();
            return;
        }
        // Refresh what is installed now.
        hpmmo::CheckSummary after = hpmmo::DoCheck(cli, g_Cfg, &g_Cancel, status);
        if (after.ok) ApplySummary(after);
    }

    SetState(Phase::Ready, L"Oyun hazır", ReadyDetail());
    g_WorkerBusy = false;
    PostRefresh();
}

void StartWorker(bool repair) {
    bool expected = false;
    if (!g_WorkerBusy.compare_exchange_strong(expected, true)) return;
    std::thread(UpdateWorker, repair).detach();
}

// Server status only (cheap, plain HTTP): keeps the pill honest while idle.
void StatusWorker() {
    hpmmo::HttpRequestOptions opts;
    opts.url = hpmmo::StatusUrl(hpmmo::CliOptions{}, g_Cfg);
    opts.allowPlainHttp = true;
    opts.systemTrust = true;
    opts.maxBodyBytes = 64 * 1024;
    opts.receiveTimeoutMs = 8000;
    std::string body;
    hpmmo::HttpOutcome out = hpmmo::HttpGetToString(opts, body);
    std::wstring state = L"OFFLINE";
    if (out.ok) {
        hpmmo::JsonValue root;
        std::string err;
        if (hpmmo::JsonValue::Parse(body, root, err) && root.isObject()) {
            state = root.boolean("maintenance", false) ? L"MAINTENANCE" : L"ONLINE";
        }
    } else if (out.status == 404) {
        state = L"ONLINE";   // a service that predates /api/status
    } else if (out.status == 503) {
        state = L"MAINTENANCE";
    }
    {
        std::lock_guard<std::mutex> lock(g_Mutex);
        g_ServerState = state;
        if (g_Phase == Phase::Ready) g_Detail.clear();
    }
    if (CurrentPhase() == Phase::Ready) {
        std::wstring d = ReadyDetail();
        std::lock_guard<std::mutex> lock(g_Mutex);
        g_Detail = d;
    }
    g_StatusBusy = false;
    PostRefresh();
}

void StartStatusPoll() {
    if (hpmmo::StatusUrl(hpmmo::CliOptions{}, g_Cfg).empty()) return;
    bool expected = false;
    if (!g_StatusBusy.compare_exchange_strong(expected, true)) return;
    std::thread(StatusWorker).detach();
}

bool OnPlay() {
    Phase p = CurrentPhase();
    if (p == Phase::Failed) {
        StartWorker();
        return false;
    }
    if (p != Phase::Ready && p != Phase::ReadyStale) return false;
    hpmmo::UpdaterPaths paths = hpmmo::ResolvePathsForGui(g_Cfg);
    std::string version;
    {
        std::lock_guard<std::mutex> lock(g_Mutex);
        version = g_InstalledVersion;
    }
    if (!hpmmo::LaunchGameClient(paths, g_Cfg, version)) {
        SetState(Phase::Failed, L"Oyun başlatılamadı", L"Oyun dosyaları eksik olabilir. \"Dosyaları onar\" ile düzeltebilirsin.");
        return false;
    }
    SetState(Phase::GameRunning, L"Oyun açık", L"İyi oyunlar! Launcher arka planda bekliyor.");
    return true;
}

bool PollGame() {
    if (CurrentPhase() != Phase::GameRunning) return false;
    hpmmo::UpdaterPaths paths = hpmmo::ResolvePathsForGui(g_Cfg);
    if (!hpmmo::IsGameRunningNow(paths, g_Cfg, nullptr)) {
        // The game closed: look for an update that may have landed meanwhile.
        StartWorker();
        return false;
    }
    return true;
}

void Init(const AppConfig& cfg, Hooks hooks) {
    g_Cfg = cfg;
    g_Hooks = std::move(hooks);
}

uint64_t ProgressDone() { return g_Done.load(); }
uint64_t ProgressTotal() { return g_Total.load(); }
void Cancel() { g_Cancel = true; }

void RequestRepair() {
    Phase p = CurrentPhase();
    if (p == Phase::Ready || p == Phase::ReadyStale || p == Phase::Failed) StartWorker(true);
}

void OnRecheckTimer() {
    Phase p = CurrentPhase();
    if (p == Phase::Ready || p == Phase::ReadyStale) StartWorker();
}

}  // namespace app
}  // namespace hpmmo
