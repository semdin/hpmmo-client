// HPMMO Launcher (GUI) for Linux and macOS.
//
// The same launcher as the Windows build (main.cpp): it installs, updates and
// starts the game, and the logic is shared (launcher_app.cpp). Only the shell
// differs: an SDL3 window showing a frame drawn by the software painter
// (painter.cpp) that mirrors the GDI+ design pixel for pixel in layout. The
// background art and the two fonts are embedded (embedded_assets.cpp, made by
// CMake), so a lone binary / AppImage renders the complete design.
//
// Test hooks (no display needed): --screenshot <file.png> paints the live
// state after --screenshot-after <ms> (default 4000) into a PNG and exits;
// --exit-after <ms> closes the window loop on its own (SDL_VIDEODRIVER=offscreen).
#include <SDL3/SDL.h>

#include <fcntl.h>
#include <sys/file.h>
#include <unistd.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "common.h"
#include "launcher_app.h"
#include "painter.h"
#include "updater.h"

namespace hpmmo {
namespace assets {
extern const unsigned char kBackground[];
extern const size_t kBackgroundSize;
extern const unsigned char kFontTitle[];
extern const size_t kFontTitleSize;
extern const unsigned char kFontBody[];
extern const size_t kFontBodySize;
extern const unsigned char kIconPng[];
extern const size_t kIconPngSize;
}  // namespace assets
}  // namespace hpmmo

namespace {

using hpmmo::app::Phase;
using hpmmo::paint::Align;
using hpmmo::paint::Canvas;
using hpmmo::paint::Color;
using hpmmo::paint::Fill;
using hpmmo::paint::Linear;
using hpmmo::paint::RectF;
using hpmmo::paint::Solid;
using hpmmo::paint::TextStyle;

// ------------------------------------------------------------------ palette
// Same values as main.cpp (client/assets/ui/hpmmo.tres).
namespace Pal {
const Color Ink(255, 11, 13, 18);
const Color Steel(255, 58, 65, 82);
const Color Parchment(255, 236, 225, 192);
const Color Text(255, 207, 202, 186);
const Color Dim(255, 153, 152, 142);
const Color Gold(255, 168, 137, 47);
const Color GoldLt(255, 216, 182, 74);
const Color GoldHi(255, 244, 226, 160);
const Color GoldDk(255, 90, 69, 32);
const Color Blood(255, 92, 22, 32);
const Color BloodLt(255, 124, 31, 43);
const Color BloodDk(255, 58, 13, 18);
const Color Good(255, 92, 201, 74);
const Color Warn(255, 255, 189, 92);
const Color Bad(255, 236, 104, 92);
}  // namespace Pal

constexpr int kBaseW = 980;
constexpr int kBaseH = 580;
constexpr int kTopBar = 44;

enum class Hit { None, Play, Close, Minimize, Repair };

struct View {
    float scale = 1.0f;
    Hit hover = Hit::None;
    Hit pressed = Hit::None;
    float anim = 0.0f;
};

hpmmo::paint::Font g_TitleFont, g_BodyFont;
hpmmo::paint::Image g_Background;
Canvas g_Base;          // background + static decoration, rebuilt on resize
Canvas g_Frame;

float SF(const View& v, float x) { return x * v.scale; }

struct Layout {
    float w = 0, h = 0;
    RectF close, minimize, play, progress, repair, pill, notes;
};

Layout ComputeLayout(const View& v, int cw, int ch) {
    Layout L;
    L.w = (float)cw;
    L.h = (float)ch;
    L.close = RectF(L.w - SF(v, 46), 0, SF(v, 46), SF(v, 38));
    L.minimize = RectF(L.w - SF(v, 92), 0, SF(v, 46), SF(v, 38));
    L.play = RectF(L.w - SF(v, 48 + 250), L.h - SF(v, 118), SF(v, 250), SF(v, 72));
    L.progress = RectF(SF(v, 48), L.h - SF(v, 58), L.play.x - SF(v, 48) - SF(v, 28), SF(v, 10));
    L.repair = RectF(SF(v, 48), L.h - SF(v, 34), SF(v, 150), SF(v, 22));
    L.pill = RectF(SF(v, 52), SF(v, 262), SF(v, 230), SF(v, 34));
    L.notes = RectF(SF(v, 48), SF(v, 316), SF(v, 390), SF(v, 100));
    return L;
}

Hit HitTest(const View& v, int cw, int ch, float x, float y) {
    Layout L = ComputeLayout(v, cw, ch);
    if (L.close.Contains(x, y)) return Hit::Close;
    if (L.minimize.Contains(x, y)) return Hit::Minimize;
    if (L.play.Contains(x, y)) return Hit::Play;
    if (L.repair.Contains(x, y)) return Hit::Repair;
    return Hit::None;
}

TextStyle Style(const hpmmo::paint::Font& f, float px, Align h = Align::Near, Align va = Align::Near,
                bool ellipsis = false) {
    TextStyle st;
    st.font = &f;
    st.px = px;
    st.h = h;
    st.v = va;
    st.ellipsis = ellipsis;
    return st;
}

// Text with a soft dark halo, for type laid straight over the key art.
void DrawStrHalo(Canvas& c, const View& v, const std::wstring& text, const RectF& box, const TextStyle& st,
                 Color color) {
    for (int dx = -2; dx <= 2; dx++)
        for (int dy = -2; dy <= 2; dy++) {
            if (dx == 0 && dy == 0) continue;
            RectF b(box.x + dx * v.scale * 0.6f, box.y + dy * v.scale * 0.6f, box.w, box.h);
            c.DrawText(text, b, st, Solid(Color(70, 0, 0, 0)));
        }
    c.DrawText(text, box, st, Solid(color));
}

// Everything that only changes with the window size.
void BuildBase(const View& v, int cw, int ch) {
    g_Base.Resize(cw, ch);
    if (!g_Background.rgba.empty()) {
        // Anchor slightly right of centre: the hero stays in view on the right.
        g_Base.DrawCover(g_Background, 0.65f, 0.5f);
    } else {
        g_Base.Clear(Pal::Ink);
    }
    Layout L = ComputeLayout(v, cw, ch);
    float shadeW = L.w * 0.62f;
    g_Base.FillRect(RectF(0, 0, shadeW, L.h),
                    Linear(0, 0, shadeW, 0,
                           {{0.0f, Color(235, 6, 7, 11)}, {0.5f, Color(190, 6, 7, 11)}, {1.0f, Color(0, 6, 7, 11)}}));
    float deckTop = L.h - SF(v, 170);
    g_Base.FillRect(RectF(0, deckTop, L.w, L.h - deckTop),
                    Linear(0, deckTop, 0, L.h, {{0.0f, Color(0, 5, 6, 10)}, {1.0f, Color(245, 5, 6, 10)}}));
    g_Base.FillRect(RectF(0, 0, L.w, SF(v, 70)),
                    Linear(0, 0, 0, SF(v, 70), {{0.0f, Color(170, 0, 0, 0)}, {1.0f, Color(0, 0, 0, 0)}}));

    // Top bar caption.
    g_Base.DrawText(L"HPMMO  ·  LAUNCHER", RectF(SF(v, 22), SF(v, 12), SF(v, 300), SF(v, 22)),
                    Style(g_BodyFont, SF(v, 13)), Solid(Pal::GoldLt.WithAlpha(220)));

    // Crest.
    TextStyle title = Style(g_TitleFont, SF(v, 74));
    RectF titleBox(SF(v, 44), SF(v, 108), SF(v, 520), SF(v, 100));
    for (int i = 6; i >= 1; i--) {
        float o = SF(v, (float)i * 1.2f);
        for (float ox : {-o, o})
            g_Base.DrawText(L"HPMMO", RectF(titleBox.x + ox, titleBox.y, titleBox.w, titleBox.h), title,
                            Solid(Color((uint8_t)(10 + i * 4), 255, 140, 40)));
    }
    g_Base.DrawText(L"HPMMO", RectF(titleBox.x + SF(v, 2), titleBox.y + SF(v, 3), titleBox.w, titleBox.h), title,
                    Solid(Color(200, 20, 8, 2)));
    g_Base.DrawText(L"HPMMO", titleBox, title,
                    Linear(0, titleBox.y + SF(v, 14), 0, titleBox.y + SF(v, 88), {{0.0f, Pal::GoldHi}, {1.0f, Pal::GoldLt}}));
    DrawStrHalo(g_Base, v, L"B Ü Y Ü C Ü L Ü K   D İ Y A R I", RectF(SF(v, 54), SF(v, 204), SF(v, 520), SF(v, 26)),
                Style(g_TitleFont, SF(v, 15)), Pal::GoldLt);
    float y = SF(v, 242);
    g_Base.Line(SF(v, 54), y, SF(v, 200), y, Pal::Gold.WithAlpha(200), SF(v, 1));
    g_Base.Line(SF(v, 222), y, SF(v, 368), y, Pal::Gold.WithAlpha(200), SF(v, 1));
    g_Base.FillDiamond(SF(v, 211), y, SF(v, 5), SF(v, 5), Pal::GoldLt);
}

void Paint(const View& v, int cw, int ch) {
    if (g_Base.width() != cw || g_Base.height() != ch) BuildBase(v, cw, ch);
    Canvas& g = g_Frame;
    g.CopyFrom(g_Base);
    Layout L = ComputeLayout(v, cw, ch);
    hpmmo::app::Snapshot s = hpmmo::app::TakeSnapshot();

    // --- window buttons
    for (Hit which : {Hit::Minimize, Hit::Close}) {
        const RectF& r = which == Hit::Close ? L.close : L.minimize;
        if (v.hover == which) g.FillRect(r, Solid(which == Hit::Close ? Color(230, 180, 32, 40) : Color(60, 255, 255, 255)));
        Color pen = v.hover == which ? Pal::Parchment : Pal::Text;
        float cx = r.x + r.w / 2, cy = r.y + r.h / 2, k = SF(v, 5.5f);
        if (which == Hit::Close) {
            g.Line(cx - k, cy - k, cx + k, cy + k, pen, SF(v, 1.4f));
            g.Line(cx - k, cy + k, cx + k, cy - k, pen, SF(v, 1.4f));
        } else {
            g.Line(cx - k, cy, cx + k, cy, pen, SF(v, 1.4f));
        }
    }

    // --- server pill
    {
        Color dot = Pal::Dim;
        std::wstring text = L"Sunucu durumu alınıyor…";
        if (s.server == L"ONLINE") {
            dot = Pal::Good;
            text = L"Sunucu çevrimiçi";
        } else if (s.server == L"MAINTENANCE") {
            dot = Pal::Warn;
            text = L"Sunucu bakımda";
        } else if (s.server == L"OFFLINE") {
            dot = Pal::Bad;
            text = L"Sunucuya ulaşılamıyor";
        }
        g.FillRound(L.pill, L.pill.h / 2, Solid(Color(190, 8, 10, 15)));
        g.StrokeRound(L.pill, L.pill.h / 2, Pal::GoldDk.WithAlpha(230), SF(v, 1));
        float pulse = (s.server == L"MAINTENANCE") ? (0.6f + 0.4f * std::sin(v.anim * 4.0f)) : 1.0f;
        float cx = L.pill.x + SF(v, 18), cy = L.pill.y + L.pill.h / 2;
        g.FillCircle(cx, cy, SF(v, 8), dot.WithAlpha((uint8_t)(70 * pulse)));
        g.FillCircle(cx, cy, SF(v, 4.5f), dot.WithAlpha((uint8_t)(255 * pulse)));
        g.DrawText(text, RectF(L.pill.x + SF(v, 34), L.pill.y, L.pill.w - SF(v, 40), L.pill.h),
                   Style(g_BodyFont, SF(v, 14), Align::Near, Align::Center), Solid(Pal::Text));
    }

    // --- what's new
    if (!s.notes.empty() || !s.release.empty()) {
        g.FillRound(L.notes, SF(v, 8), Solid(Color(170, 8, 10, 15)));
        g.StrokeRound(L.notes, SF(v, 8), Pal::Steel.WithAlpha(200), SF(v, 1));
        g.FillRect(RectF(L.notes.x, L.notes.y + SF(v, 12), SF(v, 3), L.notes.h - SF(v, 24)), Solid(Pal::Gold));
        std::wstring caption = L"YENİLİKLER";
        if (!s.release.empty()) caption += L"  ·  v" + hpmmo::Utf8ToWide(s.release);
        g.DrawText(caption, RectF(L.notes.x + SF(v, 18), L.notes.y + SF(v, 12), L.notes.w - SF(v, 30), SF(v, 20)),
                   Style(g_TitleFont, SF(v, 13)), Solid(Pal::GoldLt));
        std::wstring notes = s.notes.empty() ? L"Bu sürüm için not eklenmemiş." : s.notes;
        TextStyle body = Style(g_BodyFont, SF(v, 13));
        body.wrap = true;
        g.DrawText(notes, RectF(L.notes.x + SF(v, 18), L.notes.y + SF(v, 38), L.notes.w - SF(v, 32), L.notes.h - SF(v, 48)),
                   body, Solid(Pal::Text));
    }

    // --- status block
    float statusY = L.h - SF(v, 120);
    DrawStrHalo(g, v, s.title, RectF(SF(v, 48), statusY, L.progress.w, SF(v, 28)), Style(g_BodyFont, SF(v, 19)),
                Pal::Parchment);
    Color detailColor = Pal::Dim;
    if (s.phase == Phase::Failed) detailColor = Pal::Bad;
    if (s.phase == Phase::ReadyStale) detailColor = Pal::Warn;
    g.DrawText(s.detail, RectF(SF(v, 48), statusY + SF(v, 30), L.progress.w, SF(v, 22)),
               Style(g_BodyFont, SF(v, 14), Align::Near, Align::Near, true), Solid(detailColor));

    // --- progress bar
    {
        g.FillRound(L.progress, L.progress.h / 2, Solid(Color(200, 4, 5, 8)));
        g.StrokeRound(L.progress, L.progress.h / 2, Pal::Steel.WithAlpha(220), SF(v, 1));
        float frac = -1.0f;   // < 0: indeterminate
        bool show = true;
        switch (s.phase) {
            case Phase::Downloading: {
                uint64_t t = hpmmo::app::ProgressTotal(), d = hpmmo::app::ProgressDone();
                frac = t ? std::min(1.0f, (float)d / (float)t) : -1.0f;
                break;
            }
            case Phase::Ready:
            case Phase::GameRunning: frac = 1.0f; break;
            case Phase::ReadyStale:
            case Phase::Failed: show = false; break;
            default: break;
        }
        if (show) {
            RectF inner(L.progress.x + SF(v, 2), L.progress.y + SF(v, 2), L.progress.w - SF(v, 4), L.progress.h - SF(v, 4));
            RectF fill = inner;
            if (frac >= 0.0f) {
                fill.w = std::max(inner.h, inner.w * frac);
            } else {
                float seg = inner.w * 0.22f;
                float t = std::fmod(v.anim * 0.45f, 1.0f);
                fill.x = inner.x + (inner.w + seg) * t - seg;
                fill.w = seg;
                float x0 = std::max(fill.x, inner.x);
                float x1 = std::min(fill.x + fill.w, inner.x + inner.w);
                fill.x = x0;
                fill.w = std::max(0.0f, x1 - x0);
            }
            if (fill.w > 0.5f) {
                g.FillRound(fill, fill.h / 2,
                            Linear(fill.x, 0, fill.x + std::max(fill.w, 1.0f), 0, {{0.0f, Pal::Gold}, {1.0f, Pal::GoldHi}}));
                if (frac > 0.0f && frac < 1.0f) {
                    // A travelling sheen on the filled part while downloading.
                    float sx = fill.x + std::fmod(v.anim * SF(v, 160), std::max(fill.w, 1.0f));
                    g.SetClip(fill);
                    g.FillRect(RectF(sx - SF(v, 30), fill.y, SF(v, 60), fill.h),
                               Linear(sx - SF(v, 30), 0, sx + SF(v, 30), 0,
                                      {{0.0f, Color(0, 255, 255, 255)}, {0.5f, Color(120, 255, 250, 220)},
                                       {1.0f, Color(0, 255, 255, 255)}}));
                    g.ResetClip();
                }
            }
        }
    }

    // --- repair link + launcher version
    {
        bool busy = !(s.phase == Phase::Ready || s.phase == Phase::ReadyStale || s.phase == Phase::Failed);
        Color c = busy ? Pal::Dim.WithAlpha(110) : (v.hover == Hit::Repair ? Pal::GoldHi : Pal::Dim);
        g.DrawText(L"Dosyaları onar", L.repair, Style(g_BodyFont, SF(v, 12), Align::Near, Align::Center), Solid(c));
        std::wstring ver = L"Launcher v" + hpmmo::Utf8ToWide(hpmmo::kLauncherVersion);
        if (!s.installed.empty()) ver = L"Oyun v" + hpmmo::Utf8ToWide(s.installed) + L"   ·   " + ver;
        g.DrawText(ver, RectF(L.play.x - SF(v, 400), L.h - SF(v, 34), SF(v, 400) - SF(v, 28), SF(v, 22)),
                   Style(g_BodyFont, SF(v, 12), Align::Far, Align::Center), Solid(Pal::Dim.WithAlpha(200)));
    }

    // --- play button
    {
        bool enabled = hpmmo::app::PlayEnabled(s.phase);
        bool hover = enabled && v.hover == Hit::Play;
        bool pressed = hover && v.pressed == Hit::Play;
        RectF r = L.play;
        if (pressed) r.y += SF(v, 1);
        if (enabled) {
            // Outer glow, breathing while the button is the next step.
            float breathe = (s.phase == Phase::Ready) ? (0.55f + 0.45f * std::sin(v.anim * 2.2f)) : 0.4f;
            for (int i = 4; i >= 1; i--) {
                RectF gr(r.x - SF(v, i * 2.5f), r.y - SF(v, i * 2.5f), r.w + SF(v, i * 5.0f), r.h + SF(v, i * 5.0f));
                g.FillRound(gr, SF(v, 10 + i * 2.5f), Solid(Color((uint8_t)((hover ? 26 : 16) * breathe * (5 - i)), 255, 170, 60)));
            }
        }
        Color top = enabled ? (hover ? Pal::BloodLt : Pal::Blood) : Color(255, 34, 34, 38);
        Color bottom = enabled ? (pressed ? Pal::BloodDk : Color(255, 58, 12, 20)) : Color(255, 24, 24, 28);
        g.FillRound(r, SF(v, 9), Linear(0, r.y, 0, r.y + r.h, {{0.0f, top}, {1.0f, bottom}}));
        g.FillRound(RectF(r.x + SF(v, 2), r.y + SF(v, 2), r.w - SF(v, 4), r.h * 0.5f), SF(v, 8),
                    Linear(0, r.y, 0, r.y + r.h * 0.5f,
                           {{0.0f, Color(enabled ? 60 : 20, 255, 230, 200)}, {1.0f, Color(0, 255, 230, 200)}}));
        g.StrokeRound(r, SF(v, 9), enabled ? (hover ? Pal::GoldHi : Pal::GoldLt) : Pal::Steel, SF(v, 1.5f));
        g.StrokeRound(RectF(r.x + SF(v, 4), r.y + SF(v, 4), r.w - SF(v, 8), r.h - SF(v, 8)), SF(v, 6),
                      (enabled ? Pal::Gold : Pal::Steel).WithAlpha(110), SF(v, 1));
        std::wstring label = hpmmo::app::PlayLabel(s.phase);
        TextStyle pf = Style(g_TitleFont, SF(v, label.size() > 6 ? 19.0f : 28.0f), Align::Center, Align::Center);
        g.DrawText(label, RectF(r.x, r.y + SF(v, 1), r.w, r.h), pf, Solid(Color(160, 20, 4, 4)));
        g.DrawText(label, r, pf, Solid(enabled ? Pal::GoldHi : Pal::Dim));
    }

    // Window edge.
    g.StrokeRound(RectF(0.5f, 0.5f, (float)cw - 1, (float)ch - 1), 0, Pal::GoldDk, 1.0f);
}

bool LoadAssets() {
    bool ok = g_TitleFont.Load(hpmmo::assets::kFontTitle, hpmmo::assets::kFontTitleSize);
    ok = g_BodyFont.Load(hpmmo::assets::kFontBody, hpmmo::assets::kFontBodySize) && ok;
    if (!g_Background.Decode(hpmmo::assets::kBackground, hpmmo::assets::kBackgroundSize))
        hpmmo::LogMsg("[Launcher] background art could not be decoded");
    return ok;
}

// ------------------------------------------------------------------ CLI
// Same contract as the Windows GUI executable: updater flags make it a
// headless updater (and the self-update helper) instead of opening a window.
int RunHeadless(int argc, char** argv) {
    if (argc < 2) return -1;
    hpmmo::CliOptions opts;
    std::string err;
    if (!hpmmo::ParseCliArgs(argc, argv, opts, err)) return -1;
    if (opts.command == "help") {
        hpmmo::PrintUsage(stdout);
        fflush(stdout);
        return 0;
    }
    if (opts.helper.empty() && opts.command.empty()) return -1;
    if (opts.helper == "self-update-swap")
        return hpmmo::RunSelfUpdateSwap(hpmmo::WideToUtf8(opts.helperPid), opts.helperTarget, hpmmo::GetExePath(),
                                        opts.relaunch);
    if (opts.helper == "print-cert-pin") return hpmmo::RunPrintCertPin(opts.helperUrl);
    hpmmo::CommandResult r = hpmmo::RunCliCommand(opts);
    printf("%s\n", r.json.c_str());
    fflush(stdout);
    return r.code;
}

bool HasArg(int argc, char** argv, const char* flag) {
    for (int i = 1; i < argc; i++)
        if (strcmp(argv[i], flag) == 0) return true;
    return false;
}

const char* ArgValue(int argc, char** argv, const char* flag) {
    for (int i = 1; i + 1 < argc; i++)
        if (strcmp(argv[i], flag) == 0) return argv[i + 1];
    return nullptr;
}

// One launcher at a time (a relaunch after self-update waits for the old one).
int AcquireSingleInstance(bool waitForOld) {
    std::wstring dir = hpmmo::JoinPath(hpmmo::UserDataRoot(), L"HPMMO");
    hpmmo::CreateDirs(dir);
    std::string path = hpmmo::WideToUtf8(hpmmo::JoinPath(dir, L"launcher.lock"));
    int fd = open(path.c_str(), O_RDWR | O_CREAT | O_CLOEXEC, 0644);
    if (fd < 0) return -2;   // no lock possible: run anyway
    for (int attempt = 0; attempt < 20; attempt++) {
        if (flock(fd, LOCK_EX | LOCK_NB) == 0) return fd;
        if (!waitForOld) break;
        std::this_thread::sleep_for(std::chrono::milliseconds(250));
    }
    close(fd);
    return -1;
}

// --screenshot: run the real workers, paint their state into a PNG, exit.
int RunScreenshot(const char* out, int afterMs) {
    View v;
    hpmmo::app::Hooks hooks;
    hpmmo::app::Init(hpmmo::Config(), hooks);
    hpmmo::app::StartWorker();
    hpmmo::app::StartStatusPoll();
    std::this_thread::sleep_for(std::chrono::milliseconds(afterMs));
    v.anim = afterMs / 1000.0f;
    Paint(v, kBaseW, kBaseH);
    bool ok = g_Frame.WritePng(out);
    hpmmo::app::Cancel();
    printf("%s %s\n", ok ? "wrote" : "FAILED", out);
    fflush(stdout);
    _exit(ok ? 0 : 1);   // detached workers may still be blocked in network calls
}

Uint32 g_EvRefresh = 0;
Uint32 g_EvExit = 0;
View g_View;
SDL_Window* g_Window = nullptr;

SDL_HitTestResult HitTestCb(SDL_Window* win, const SDL_Point* pt, void*) {
    int w = 0, h = 0;
    SDL_GetWindowSize(win, &w, &h);
    View logical = g_View;
    logical.scale = 1.0f;   // hit testing in window coordinates
    if (pt->y < kTopBar && HitTest(logical, w, h, (float)pt->x, (float)pt->y) == Hit::None) return SDL_HITTEST_DRAGGABLE;
    return SDL_HITTEST_NORMAL;
}

bool ConfirmCloseDuringUpdate() {
    const SDL_MessageBoxButtonData buttons[] = {
        {SDL_MESSAGEBOX_BUTTON_ESCAPEKEY_DEFAULT, 0, "Hayır"},
        {SDL_MESSAGEBOX_BUTTON_RETURNKEY_DEFAULT, 1, "Evet"},
    };
    SDL_MessageBoxData data = {};
    data.flags = SDL_MESSAGEBOX_INFORMATION;
    data.window = g_Window;
    data.title = "HPMMO Launcher";
    data.message = "Güncelleme sürüyor. Şimdi kapatırsan indirme bir sonraki açılışta kaldığı yerden devam eder.\n\nKapatılsın mı?";
    data.numbuttons = 2;
    data.buttons = buttons;
    int answer = 0;
    if (!SDL_ShowMessageBox(&data, &answer)) return true;
    return answer == 1;
}

}  // namespace

int main(int argc, char** argv) {
    {
        int headless = RunHeadless(argc, argv);
        if (headless >= 0) return headless;
    }
    bool postSelfUpdate = HasArg(argc, argv, "--post-self-update");
    if (postSelfUpdate) {
        hpmmo::SetLogPath(hpmmo::JoinPath(hpmmo::GetExeDir(), L"launcher.log"));
        hpmmo::LogMsg("[Launcher] restarted after self-update");
        if (!hpmmo::GetEnvW(L"HPMMO_TEST_NO_GUI").empty()) return 0;
    }

    hpmmo::LoadConfig();
    if (!LoadAssets()) hpmmo::LogMsg("[Launcher] embedded fonts could not be loaded");

    if (const char* shot = ArgValue(argc, argv, "--screenshot")) {
        const char* after = ArgValue(argc, argv, "--screenshot-after");
        return RunScreenshot(shot, after ? atoi(after) : 4000);
    }

    int lock = AcquireSingleInstance(postSelfUpdate);
    if (lock == -1) {
        hpmmo::LogMsg("[Launcher] another launcher is already running");
        return 0;
    }

    if (!SDL_Init(SDL_INIT_VIDEO)) {
        fprintf(stderr, "SDL_Init failed: %s\n", SDL_GetError());
        return 1;
    }
    g_EvRefresh = SDL_RegisterEvents(2);
    g_EvExit = g_EvRefresh + 1;

    g_Window = SDL_CreateWindow("HPMMO Launcher", kBaseW, kBaseH,
                                SDL_WINDOW_BORDERLESS | SDL_WINDOW_HIGH_PIXEL_DENSITY | SDL_WINDOW_HIDDEN);
    if (!g_Window) {
        fprintf(stderr, "SDL_CreateWindow failed: %s\n", SDL_GetError());
        SDL_Quit();
        return 1;
    }
    {
        hpmmo::paint::Image icon;
        if (icon.Decode(hpmmo::assets::kIconPng, hpmmo::assets::kIconPngSize)) {
            SDL_Surface* surf = SDL_CreateSurfaceFrom(icon.w, icon.h, SDL_PIXELFORMAT_RGBA32, icon.rgba.data(), icon.w * 4);
            if (surf) {
                SDL_SetWindowIcon(g_Window, surf);
                SDL_DestroySurface(surf);
            }
        }
    }
    SDL_SetWindowHitTest(g_Window, HitTestCb, nullptr);
    SDL_Renderer* renderer = SDL_CreateRenderer(g_Window, nullptr);
    if (!renderer) {
        fprintf(stderr, "SDL_CreateRenderer failed: %s\n", SDL_GetError());
        SDL_DestroyWindow(g_Window);
        SDL_Quit();
        return 1;
    }
    SDL_SetRenderVSync(renderer, 1);
    SDL_Cursor* hand = SDL_CreateSystemCursor(SDL_SYSTEM_CURSOR_POINTER);
    SDL_Cursor* arrow = SDL_CreateSystemCursor(SDL_SYSTEM_CURSOR_DEFAULT);
    SDL_ShowWindow(g_Window);

    hpmmo::app::Hooks hooks;
    hooks.refresh = [] {
        SDL_Event e = {};
        e.type = g_EvRefresh;
        SDL_PushEvent(&e);
    };
    hooks.exitForSelfUpdate = [] {
        SDL_Event e = {};
        e.type = g_EvExit;
        SDL_PushEvent(&e);
    };
    hpmmo::app::Init(hpmmo::Config(), hooks);
    hpmmo::app::StartWorker();
    hpmmo::app::StartStatusPoll();

    const char* exitAfterArg = ArgValue(argc, argv, "--exit-after");
    Uint64 exitAt = exitAfterArg ? SDL_GetTicks() + (Uint64)atoi(exitAfterArg) : 0;
    Uint64 nextStatus = SDL_GetTicks() + hpmmo::app::kStatusPollMs;
    Uint64 nextRecheck = SDL_GetTicks() + hpmmo::app::kRecheckMs;
    Uint64 nextGamePoll = 0;   // 0: the game is not running
    SDL_Texture* tex = nullptr;
    int texW = 0, texH = 0;
    bool running = true;
    Uint64 start = SDL_GetTicks();

    auto pixelPoint = [&](float x, float y, float& px, float& py) {
        int ww = 0, wh = 0, pw = 0, ph = 0;
        SDL_GetWindowSize(g_Window, &ww, &wh);
        SDL_GetWindowSizeInPixels(g_Window, &pw, &ph);
        px = ww ? x * pw / ww : x;
        py = wh ? y * ph / wh : y;
    };
    auto hitAt = [&](float x, float y) {
        int pw = 0, ph = 0;
        SDL_GetWindowSizeInPixels(g_Window, &pw, &ph);
        float px, py;
        pixelPoint(x, y, px, py);
        return HitTest(g_View, pw, ph, px, py);
    };
    auto activate = [&](Hit h) {
        switch (h) {
            case Hit::Close: {
                SDL_Event e = {};
                e.type = SDL_EVENT_QUIT;
                SDL_PushEvent(&e);
                break;
            }
            case Hit::Minimize: SDL_MinimizeWindow(g_Window); break;
            case Hit::Play:
                if (hpmmo::app::PlayEnabled(hpmmo::app::CurrentPhase()) && hpmmo::app::OnPlay()) {
                    nextGamePoll = SDL_GetTicks() + hpmmo::app::kGamePollMs;
                    SDL_MinimizeWindow(g_Window);
                }
                break;
            case Hit::Repair: hpmmo::app::RequestRepair(); break;
            default: break;
        }
    };
    auto quitRequested = [&]() {
        Phase p = hpmmo::app::CurrentPhase();
        if (p == Phase::Downloading || p == Phase::Installing) {
            if (!ConfirmCloseDuringUpdate()) return false;
            hpmmo::app::Cancel();
        }
        return true;
    };

    while (running) {
        SDL_Event e;
        bool got = SDL_WaitEventTimeout(&e, 33);
        while (got) {
            if (e.type == SDL_EVENT_QUIT || e.type == SDL_EVENT_WINDOW_CLOSE_REQUESTED) {
                if (quitRequested()) running = false;
            } else if (e.type == g_EvExit) {
                running = false;
            } else if (e.type == SDL_EVENT_MOUSE_MOTION) {
                g_View.hover = hitAt(e.motion.x, e.motion.y);
                bool handCursor = g_View.hover == Hit::Play ? hpmmo::app::PlayEnabled(hpmmo::app::CurrentPhase())
                                                           : g_View.hover != Hit::None;
                SDL_SetCursor(handCursor ? hand : arrow);
            } else if (e.type == SDL_EVENT_WINDOW_MOUSE_LEAVE) {
                g_View.hover = Hit::None;
                g_View.pressed = Hit::None;
            } else if (e.type == SDL_EVENT_MOUSE_BUTTON_DOWN && e.button.button == SDL_BUTTON_LEFT) {
                g_View.pressed = hitAt(e.button.x, e.button.y);
            } else if (e.type == SDL_EVENT_MOUSE_BUTTON_UP && e.button.button == SDL_BUTTON_LEFT) {
                Hit h = hitAt(e.button.x, e.button.y);
                Hit pressed = g_View.pressed;
                g_View.pressed = Hit::None;
                if (h == pressed) activate(h);
            } else if (e.type == SDL_EVENT_KEY_DOWN) {
                if (e.key.key == SDLK_RETURN || e.key.key == SDLK_SPACE) activate(Hit::Play);
                if (e.key.key == SDLK_ESCAPE) SDL_MinimizeWindow(g_Window);
            }
            got = SDL_PollEvent(&e);
        }
        if (!running) break;

        Uint64 now = SDL_GetTicks();
        if (exitAt && now >= exitAt) break;
        if (now >= nextStatus) {
            hpmmo::app::StartStatusPoll();
            nextStatus = now + hpmmo::app::kStatusPollMs;
        }
        if (now >= nextRecheck) {
            hpmmo::app::OnRecheckTimer();
            nextRecheck = now + hpmmo::app::kRecheckMs;
        }
        if (nextGamePoll && now >= nextGamePoll) {
            nextGamePoll = hpmmo::app::PollGame() ? now + hpmmo::app::kGamePollMs : 0;
        }

        if (SDL_GetWindowFlags(g_Window) & SDL_WINDOW_MINIMIZED) continue;
        int pw = 0, ph = 0, ww = 0, wh = 0;
        SDL_GetWindowSizeInPixels(g_Window, &pw, &ph);
        SDL_GetWindowSize(g_Window, &ww, &wh);
        if (pw <= 0 || ph <= 0) continue;
        float scale = ww ? (float)pw / ww : 1.0f;
        if (scale != g_View.scale) {
            g_View.scale = scale;
            g_Base.Resize(0, 0);   // rebuild the static layer at the new density
        }
        g_View.anim = (now - start) / 1000.0f;
        Paint(g_View, pw, ph);
        if (!tex || texW != pw || texH != ph) {
            if (tex) SDL_DestroyTexture(tex);
            tex = SDL_CreateTexture(renderer, SDL_PIXELFORMAT_RGBA32, SDL_TEXTUREACCESS_STREAMING, pw, ph);
            texW = pw;
            texH = ph;
        }
        if (tex) {
            SDL_UpdateTexture(tex, nullptr, g_Frame.data(), pw * 4);
            SDL_RenderClear(renderer);
            SDL_RenderTexture(renderer, tex, nullptr, nullptr);
            SDL_RenderPresent(renderer);
        }
    }

    hpmmo::app::Cancel();
    if (tex) SDL_DestroyTexture(tex);
    SDL_DestroyCursor(hand);
    SDL_DestroyCursor(arrow);
    SDL_DestroyRenderer(renderer);
    SDL_DestroyWindow(g_Window);
    SDL_Quit();
    if (lock >= 0) close(lock);
    // Detached workers may still be blocked in network calls.
    fflush(nullptr);
    _exit(0);
}
