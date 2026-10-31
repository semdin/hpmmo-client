// HPMMO Launcher (GUI).
//
// The launcher only installs, updates and starts the game: signing in happens
// on the game's own login screen. On start it checks the signed release
// manifest (GitHub Releases, see common.h HPMMO_DEFAULT_RELEASE_BASE),
// replaces itself first when the release ships a newer launcher, downloads and
// activates a newer client when there is one, and then offers PLAY.
//
// The window is borderless and fully custom drawn with GDI+; the background
// art and the two fonts are embedded resources (app.rc), so a lone
// HPMMO_Launcher.exe renders the complete design. Every network call runs on a
// worker thread; the UI thread only reads the shared state under g_Mutex.
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <objidl.h>
#include <gdiplus.h>
#include <windowsx.h>
#include <shellapi.h>
#include <shlwapi.h>
#include <dwmapi.h>

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#include "http.h"
#include "json.h"
#include "launcher_app.h"
#include "updater.h"

using namespace Gdiplus;

#define IDI_MAIN 101
#define IDR_BACKGROUND 201
#define IDR_FONT_TITLE 202
#define IDR_FONT_BODY 203
#define IDR_LOGO 204

#define WM_APP_REFRESH (WM_APP + 1)   // worker -> UI: state changed, repaint
#define WM_APP_EXIT (WM_APP + 2)      // worker -> UI: self-update handed off, quit

namespace {

using hpmmo::app::Phase;
using hpmmo::app::kGameTitle;
using hpmmo::app::Snapshot;
using hpmmo::app::TakeSnapshot;
using hpmmo::app::PlayLabel;
using hpmmo::app::PlayEnabled;
using hpmmo::app::CurrentPhase;
using hpmmo::app::StartWorker;
using hpmmo::app::StartStatusPoll;

// ------------------------------------------------------------------ palette
// The GDI+ mirror of the game theme (client/assets/ui/hpmmo.tres).
namespace Pal {
const Color Ink(255, 11, 13, 18);
const Color Night(255, 18, 20, 27);
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
constexpr UINT_PTR kTimerAnim = 1;
constexpr UINT_PTR kTimerStatus = 2;
constexpr UINT_PTR kTimerGame = 3;
constexpr UINT_PTR kTimerRecheck = 4;
constexpr UINT kStatusPollMs = 30000;
constexpr UINT kRecheckMs = 10 * 60 * 1000;   // look for a new release while idle

// ------------------------------------------------------------------ state
enum class Hit { None, Play, Close, Minimize, Repair };

HWND g_Wnd = NULL;
float g_Scale = 1.0f;
Hit g_Hover = Hit::None;
Hit g_Pressed = Hit::None;
float g_Anim = 0.0f;
bool g_Tracking = false;

ULONG_PTR g_GdiToken = 0;
PrivateFontCollection* g_Fonts = nullptr;
FontFamily* g_TitleFamily = nullptr;
FontFamily* g_BodyFamily = nullptr;
Bitmap* g_Background = nullptr;
Bitmap* g_BackgroundScaled = nullptr;   // cover-scaled to the client size
Bitmap* g_Logo = nullptr;               // the crest: horizontal game logo
int g_ScaledW = 0, g_ScaledH = 0;


int S(float v) { return (int)std::lround(v * g_Scale); }
float SF(float v) { return v * g_Scale; }

// ------------------------------------------------------------------ resources
bool LoadResourceBytes(int id, const void** data, DWORD* size) {
    HRSRC res = FindResourceW(NULL, MAKEINTRESOURCEW(id), MAKEINTRESOURCEW(10) /* RT_RCDATA */);
    if (!res) return false;
    HGLOBAL h = LoadResource(NULL, res);
    if (!h) return false;
    *data = LockResource(h);
    *size = SizeofResource(NULL, res);
    return *data != nullptr && *size > 0;
}

FontFamily* FamilyOrFallback(const wchar_t* name, const wchar_t* fallback) {
    FontFamily* fam = new FontFamily(name, g_Fonts);
    if (fam->GetLastStatus() == Ok) return fam;
    delete fam;
    fam = new FontFamily(fallback);
    if (fam->GetLastStatus() == Ok) return fam;
    delete fam;
    return FontFamily::GenericSerif()->Clone();
}

// An embedded image, decoded and copied out of its stream (nullptr on failure).
Bitmap* LoadResourceBitmap(int id) {
    const void* data = nullptr;
    DWORD size = 0;
    if (!LoadResourceBytes(id, &data, &size)) return nullptr;
    IStream* stream = SHCreateMemStream((const BYTE*)data, (UINT)size);
    if (!stream) return nullptr;
    Bitmap* copy = nullptr;
    Bitmap* decoded = Bitmap::FromStream(stream);
    if (decoded && decoded->GetLastStatus() == Ok)
        copy = decoded->Clone(0, 0, decoded->GetWidth(), decoded->GetHeight(), PixelFormat32bppPARGB);
    delete decoded;
    stream->Release();
    return copy;
}

void LoadAssets() {
    g_Fonts = new PrivateFontCollection();
    const void* data = nullptr;
    DWORD size = 0;
    if (LoadResourceBytes(IDR_FONT_TITLE, &data, &size)) g_Fonts->AddMemoryFont(data, (INT)size);
    if (LoadResourceBytes(IDR_FONT_BODY, &data, &size)) g_Fonts->AddMemoryFont(data, (INT)size);
    g_TitleFamily = FamilyOrFallback(L"Cinzel Decorative", L"Georgia");
    g_BodyFamily = FamilyOrFallback(L"Marcellus", L"Georgia");

    g_Background = LoadResourceBitmap(IDR_BACKGROUND);
    g_Logo = LoadResourceBitmap(IDR_LOGO);
}

void FreeAssets() {
    delete g_BackgroundScaled;
    delete g_Background;
    delete g_Logo;
    g_Logo = nullptr;
    delete g_TitleFamily;
    delete g_BodyFamily;
    delete g_Fonts;
    g_BackgroundScaled = g_Background = nullptr;
    g_TitleFamily = g_BodyFamily = nullptr;
    g_Fonts = nullptr;
}

// A font of the family's first available style (the title face only ships Bold).
Font* MakeFont(FontFamily* fam, float px, INT wanted = FontStyleRegular) {
    INT style = wanted;
    if (!fam->IsStyleAvailable(style)) style = fam->IsStyleAvailable(FontStyleBold) ? FontStyleBold : FontStyleRegular;
    return new Font(fam, SF(px), style, UnitPixel);
}

// ------------------------------------------------------------------ drawing
void RoundedPath(GraphicsPath& path, const RectF& r, float radius) {
    float d = std::min(radius * 2.0f, std::min(r.Width, r.Height));
    if (d <= 0.5f) {
        path.AddRectangle(r);
        return;
    }
    path.AddArc(r.X, r.Y, d, d, 180, 90);
    path.AddArc(r.X + r.Width - d, r.Y, d, d, 270, 90);
    path.AddArc(r.X + r.Width - d, r.Y + r.Height - d, d, d, 0, 90);
    path.AddArc(r.X, r.Y + r.Height - d, d, d, 90, 90);
    path.CloseFigure();
}

void FillRound(Graphics& g, const RectF& r, float radius, const Brush& brush) {
    GraphicsPath path;
    RoundedPath(path, r, radius);
    g.FillPath(&brush, &path);
}

void StrokeRound(Graphics& g, const RectF& r, float radius, const Color& c, float width) {
    GraphicsPath path;
    RoundedPath(path, r, radius);
    Pen pen(c, width);
    g.DrawPath(&pen, &path);
}

Color WithAlpha(const Color& c, BYTE a) { return Color(a, c.GetR(), c.GetG(), c.GetB()); }

void DrawStr(Graphics& g, const std::wstring& text, Font* font, const RectF& box, const Color& color,
              StringAlignment h = StringAlignmentNear, StringAlignment v = StringAlignmentNear,
              bool ellipsis = false) {
    StringFormat fmt;
    fmt.SetAlignment(h);
    fmt.SetLineAlignment(v);
    if (ellipsis) {
        fmt.SetTrimming(StringTrimmingEllipsisCharacter);
        fmt.SetFormatFlags(StringFormatFlagsNoWrap);
    }
    SolidBrush brush(color);
    g.DrawString(text.c_str(), (INT)text.size(), font, box, &fmt, &brush);
}

// Text with a soft dark halo, for type laid straight over the key art.
void DrawStrHalo(Graphics& g, const std::wstring& text, Font* font, const RectF& box, const Color& color,
                  StringAlignment h = StringAlignmentNear) {
    for (int dx = -2; dx <= 2; dx++) {
        for (int dy = -2; dy <= 2; dy++) {
            if (dx == 0 && dy == 0) continue;
            RectF b(box.X + dx * g_Scale * 0.6f, box.Y + dy * g_Scale * 0.6f, box.Width, box.Height);
            DrawStr(g, text, font, b, Color(70, 0, 0, 0), h);
        }
    }
    DrawStr(g, text, font, box, color, h);
}

// Layout rectangles in client pixels.
struct Layout {
    float w = 0, h = 0;
    RectF close, minimize, play, progress, repair, pill, notes;
};

Layout ComputeLayout(int cw, int ch) {
    Layout L;
    L.w = (float)cw;
    L.h = (float)ch;
    L.close = RectF(L.w - SF(46), 0, SF(46), SF(38));
    L.minimize = RectF(L.w - SF(92), 0, SF(46), SF(38));
    L.play = RectF(L.w - SF(48 + 250), L.h - SF(118), SF(250), SF(72));
    L.progress = RectF(SF(48), L.h - SF(58), L.play.X - SF(48) - SF(28), SF(10));
    L.repair = RectF(SF(48), L.h - SF(34), SF(150), SF(22));
    L.pill = RectF(SF(52), SF(262), SF(230), SF(34));
    L.notes = RectF(SF(48), SF(316), SF(390), SF(100));
    return L;
}

Layout CurrentLayout() {
    RECT rc;
    GetClientRect(g_Wnd, &rc);
    return ComputeLayout(rc.right - rc.left, rc.bottom - rc.top);
}

bool Contains(const RectF& r, int x, int y) {
    return x >= r.X && y >= r.Y && x < r.X + r.Width && y < r.Y + r.Height;
}

void EnsureScaledBackground(int cw, int ch) {
    if (!g_Background || (g_BackgroundScaled && g_ScaledW == cw && g_ScaledH == ch)) return;
    delete g_BackgroundScaled;
    g_BackgroundScaled = new Bitmap(cw, ch, PixelFormat32bppPARGB);
    Graphics g(g_BackgroundScaled);
    g.SetInterpolationMode(InterpolationModeHighQualityBicubic);
    float iw = (float)g_Background->GetWidth(), ih = (float)g_Background->GetHeight();
    float scale = std::max(cw / iw, ch / ih);
    float dw = iw * scale, dh = ih * scale;
    // Anchor slightly right of centre: the hero stays in view on the right.
    float dx = (cw - dw) * 0.65f, dy = (ch - dh) * 0.5f;
    g.DrawImage(g_Background, RectF(dx, dy, dw, dh));
    g_ScaledW = cw;
    g_ScaledH = ch;
}


void Paint(HDC hdc, int cw, int ch) {
    Bitmap frame(cw, ch, PixelFormat32bppPARGB);
    Graphics g(&frame);
    g.SetSmoothingMode(SmoothingModeAntiAlias);
    g.SetTextRenderingHint(TextRenderingHintAntiAliasGridFit);
    g.SetPixelOffsetMode(PixelOffsetModeHalf);

    Layout L = ComputeLayout(cw, ch);
    Snapshot s = TakeSnapshot();

    // --- backdrop
    EnsureScaledBackground(cw, ch);
    if (g_BackgroundScaled) {
        g.DrawImage(g_BackgroundScaled, 0, 0);
    } else {
        SolidBrush ink(Pal::Ink);
        g.FillRectangle(&ink, 0, 0, cw, ch);
    }
    {
        // Gradient vectors overshoot their fill rectangles by a few pixels and
        // flip at the ends: GDI+ otherwise wraps the first colour onto the last
        // pixel row and draws a visible seam.
        // Left shade behind the text column.
        float shadeW = L.w * 0.62f;
        LinearGradientBrush left(PointF(-4, 0), PointF(shadeW + 4, 0), Color(235, 6, 7, 11), Color(0, 6, 7, 11));
        Color colors[] = {Color(235, 6, 7, 11), Color(190, 6, 7, 11), Color(0, 6, 7, 11)};
        REAL pos[] = {0.0f, 0.5f, 1.0f};
        left.SetInterpolationColors(colors, pos, 3);
        left.SetWrapMode(WrapModeTileFlipXY);
        g.FillRectangle(&left, RectF(0, 0, shadeW, L.h));
        // Bottom deck.
        float deckTop = L.h - SF(170);
        LinearGradientBrush deck(PointF(0, deckTop - 4), PointF(0, L.h + 4), Color(0, 5, 6, 10), Color(245, 5, 6, 10));
        deck.SetWrapMode(WrapModeTileFlipXY);
        g.FillRectangle(&deck, RectF(0, deckTop, L.w, L.h - deckTop));
        // Top bar wash.
        LinearGradientBrush top(PointF(0, -4), PointF(0, SF(70) + 4), Color(170, 0, 0, 0), Color(0, 0, 0, 0));
        top.SetWrapMode(WrapModeTileFlipXY);
        g.FillRectangle(&top, RectF(0, 0, L.w, SF(70)));
    }

    // --- top bar
    Font* small = MakeFont(g_BodyFamily, 13);
    Font* tiny = MakeFont(g_BodyFamily, 12);
    DrawStr(g, L"THOUSAND REALMS  ·  LAUNCHER", small, RectF(SF(22), SF(12), SF(300), SF(22)), WithAlpha(Pal::GoldLt, 220));
    for (Hit which : {Hit::Minimize, Hit::Close}) {
        const RectF& r = which == Hit::Close ? L.close : L.minimize;
        if (g_Hover == which) {
            SolidBrush hb(which == Hit::Close ? Color(230, 180, 32, 40) : Color(60, 255, 255, 255));
            g.FillRectangle(&hb, r);
        }
        Pen pen(g_Hover == which ? Pal::Parchment : Pal::Text, SF(1.4f));
        float cx = r.X + r.Width / 2, cy = r.Y + r.Height / 2, k = SF(5.5f);
        if (which == Hit::Close) {
            g.DrawLine(&pen, cx - k, cy - k, cx + k, cy + k);
            g.DrawLine(&pen, cx - k, cy + k, cx + k, cy - k);
        } else {
            g.DrawLine(&pen, cx - k, cy, cx + k, cy);
        }
    }

    // --- crest
    Font* title = MakeFont(g_TitleFamily, 48, FontStyleBold);
    RectF titleBox(SF(44), SF(130), SF(560), SF(74));
    if (g_Logo) {
        g.SetInterpolationMode(InterpolationModeHighQualityBicubic);
        float lw = SF(384), lh = lw * g_Logo->GetHeight() / g_Logo->GetWidth();
        g.DrawImage(g_Logo, RectF(SF(40), SF(202) - lh, lw, lh));
    } else {
        // Without the logo: the name in gold, with a warm glow under it.
        for (int i = 6; i >= 1; i--) {
            float o = SF((float)i * 1.2f);
            for (float ox : {-o, o}) {
                DrawStr(g, kGameTitle, title, RectF(titleBox.X + ox, titleBox.Y, titleBox.Width, titleBox.Height),
                         Color((BYTE)(10 + i * 4), 255, 140, 40));
            }
        }
        DrawStr(g, kGameTitle, title, RectF(titleBox.X + SF(2), titleBox.Y + SF(3), titleBox.Width, titleBox.Height),
                 Color(200, 20, 8, 2));
        LinearGradientBrush gold(PointF(0, titleBox.Y + SF(10)), PointF(0, titleBox.Y + SF(60)), Pal::GoldHi,
                                 Pal::GoldLt);
        StringFormat fmt;
        g.DrawString(kGameTitle, -1, title, titleBox, &fmt, &gold);
    }
    Font* subtitle = MakeFont(g_TitleFamily, 15, FontStyleBold);
    DrawStrHalo(g, L"B Ü Y Ü C Ü L Ü K   D İ Y A R I", subtitle, RectF(SF(54), SF(204), SF(520), SF(26)),
                 Pal::GoldLt);
    {
        Pen rule(WithAlpha(Pal::Gold, 200), SF(1));
        float y = SF(242);
        g.DrawLine(&rule, SF(54), y, SF(200), y);
        g.DrawLine(&rule, SF(222), y, SF(368), y);
        GraphicsPath gem;
        PointF pts[] = {PointF(SF(211), y - SF(5)), PointF(SF(216), y), PointF(SF(211), y + SF(5)),
                        PointF(SF(206), y)};
        gem.AddPolygon(pts, 4);
        SolidBrush gb(Pal::GoldLt);
        g.FillPath(&gb, &gem);
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
        SolidBrush bg(Color(190, 8, 10, 15));
        FillRound(g, L.pill, L.pill.Height / 2, bg);
        StrokeRound(g, L.pill, L.pill.Height / 2, WithAlpha(Pal::GoldDk, 230), SF(1));
        float pulse = (s.server == L"MAINTENANCE") ? (0.6f + 0.4f * std::sin(g_Anim * 4.0f)) : 1.0f;
        SolidBrush halo(WithAlpha(dot, (BYTE)(70 * pulse)));
        SolidBrush db(WithAlpha(dot, (BYTE)(255 * pulse)));
        float cx = L.pill.X + SF(18), cy = L.pill.Y + L.pill.Height / 2;
        g.FillEllipse(&halo, cx - SF(8), cy - SF(8), SF(16), SF(16));
        g.FillEllipse(&db, cx - SF(4.5f), cy - SF(4.5f), SF(9), SF(9));
        Font* pf = MakeFont(g_BodyFamily, 14);
        DrawStr(g, text, pf, RectF(L.pill.X + SF(34), L.pill.Y, L.pill.Width - SF(40), L.pill.Height), Pal::Text,
                 StringAlignmentNear, StringAlignmentCenter);
        delete pf;
    }

    // --- what's new
    if (!s.notes.empty() || !s.release.empty()) {
        SolidBrush bg(Color(170, 8, 10, 15));
        FillRound(g, L.notes, SF(8), bg);
        StrokeRound(g, L.notes, SF(8), WithAlpha(Pal::Steel, 200), SF(1));
        SolidBrush accent(Pal::Gold);
        g.FillRectangle(&accent, RectF(L.notes.X, L.notes.Y + SF(12), SF(3), L.notes.Height - SF(24)));
        Font* head = MakeFont(g_TitleFamily, 13, FontStyleBold);
        std::wstring caption = L"YENİLİKLER";
        if (!s.release.empty()) caption += L"  ·  v" + hpmmo::Utf8ToWide(s.release);
        DrawStr(g, caption, head, RectF(L.notes.X + SF(18), L.notes.Y + SF(12), L.notes.Width - SF(30), SF(20)),
                 Pal::GoldLt);
        Font* body = MakeFont(g_BodyFamily, 13);
        std::wstring notes = s.notes.empty() ? L"Bu sürüm için not eklenmemiş." : s.notes;
        StringFormat fmt;
        fmt.SetTrimming(StringTrimmingEllipsisWord);
        SolidBrush tb(Pal::Text);
        RectF nb(L.notes.X + SF(18), L.notes.Y + SF(38), L.notes.Width - SF(32), L.notes.Height - SF(48));
        g.DrawString(notes.c_str(), (INT)notes.size(), body, nb, &fmt, &tb);
        delete head;
        delete body;
    }

    // --- status block
    Font* statusTitle = MakeFont(g_BodyFamily, 19);
    Font* statusDetail = MakeFont(g_BodyFamily, 14);
    float statusY = L.h - SF(120);
    DrawStrHalo(g, s.title, statusTitle, RectF(SF(48), statusY, L.progress.Width, SF(28)), Pal::Parchment);
    Color detailColor = Pal::Dim;
    if (s.phase == Phase::Failed) detailColor = Pal::Bad;
    if (s.phase == Phase::ReadyStale) detailColor = Pal::Warn;
    DrawStr(g, s.detail, statusDetail, RectF(SF(48), statusY + SF(30), L.progress.Width, SF(22)), detailColor,
             StringAlignmentNear, StringAlignmentNear, true);

    // --- progress bar
    {
        SolidBrush track(Color(200, 4, 5, 8));
        FillRound(g, L.progress, L.progress.Height / 2, track);
        StrokeRound(g, L.progress, L.progress.Height / 2, WithAlpha(Pal::Steel, 220), SF(1));
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
            RectF inner(L.progress.X + SF(2), L.progress.Y + SF(2), L.progress.Width - SF(4), L.progress.Height - SF(4));
            RectF fill = inner;
            if (frac >= 0.0f) {
                fill.Width = std::max(inner.Height, inner.Width * frac);
            } else {
                float seg = inner.Width * 0.22f;
                float t = std::fmod(g_Anim * 0.45f, 1.0f);
                fill.X = inner.X + (inner.Width + seg) * t - seg;
                fill.Width = seg;
                float x0 = std::max(fill.X, inner.X);
                float x1 = std::min(fill.X + fill.Width, inner.X + inner.Width);
                fill.X = x0;
                fill.Width = std::max(0.0f, x1 - x0);
            }
            if (fill.Width > 0.5f) {
                LinearGradientBrush fb(PointF(fill.X, 0), PointF(fill.X + std::max(fill.Width, 1.0f), 0), Pal::Gold,
                                       Pal::GoldHi);
                FillRound(g, fill, fill.Height / 2, fb);
                if (frac > 0.0f && frac < 1.0f) {
                    // A travelling sheen on the filled part while downloading.
                    float sx = fill.X + std::fmod(g_Anim * SF(160), std::max(fill.Width, 1.0f));
                    LinearGradientBrush sheen(PointF(sx - SF(30), 0), PointF(sx + SF(30), 0), Color(0, 255, 255, 255),
                                              Color(0, 255, 255, 255));
                    Color sc[] = {Color(0, 255, 255, 255), Color(120, 255, 250, 220), Color(0, 255, 255, 255)};
                    REAL sp[] = {0.0f, 0.5f, 1.0f};
                    sheen.SetInterpolationColors(sc, sp, 3);
                    g.SetClip(fill);
                    g.FillRectangle(&sheen, RectF(sx - SF(30), fill.Y, SF(60), fill.Height));
                    g.ResetClip();
                }
            }
        }
    }

    // --- repair link + launcher version
    {
        bool busy = !(s.phase == Phase::Ready || s.phase == Phase::ReadyStale || s.phase == Phase::Failed);
        Color c = busy ? WithAlpha(Pal::Dim, 110) : (g_Hover == Hit::Repair ? Pal::GoldHi : Pal::Dim);
        DrawStr(g, L"Dosyaları onar", tiny, L.repair, c, StringAlignmentNear, StringAlignmentCenter);
        std::wstring ver = L"Launcher v" + hpmmo::Utf8ToWide(hpmmo::kLauncherVersion);
        if (!s.installed.empty()) ver = L"Oyun v" + hpmmo::Utf8ToWide(s.installed) + L"   ·   " + ver;
        DrawStr(g, ver, tiny, RectF(L.play.X - SF(400), L.h - SF(34), SF(400) - SF(28), SF(22)),
                 WithAlpha(Pal::Dim, 200), StringAlignmentFar, StringAlignmentCenter);
    }

    // --- play button
    {
        bool enabled = PlayEnabled(s.phase);
        bool hover = enabled && g_Hover == Hit::Play;
        bool pressed = hover && g_Pressed == Hit::Play;
        RectF r = L.play;
        if (pressed) r.Y += SF(1);
        if (enabled) {
            // Outer glow, breathing while the button is the next step.
            float breathe = (s.phase == Phase::Ready) ? (0.55f + 0.45f * std::sin(g_Anim * 2.2f)) : 0.4f;
            for (int i = 4; i >= 1; i--) {
                RectF gr(r.X - SF(i * 2.5f), r.Y - SF(i * 2.5f), r.Width + SF(i * 5.0f), r.Height + SF(i * 5.0f));
                SolidBrush glow(Color((BYTE)((hover ? 26 : 16) * breathe * (5 - i)), 255, 170, 60));
                FillRound(g, gr, SF(10 + i * 2.5f), glow);
            }
        }
        Color top = enabled ? (hover ? Pal::BloodLt : Pal::Blood) : Color(255, 34, 34, 38);
        Color bottom = enabled ? (pressed ? Pal::BloodDk : Color(255, 58, 12, 20)) : Color(255, 24, 24, 28);
        LinearGradientBrush fill(PointF(0, r.Y), PointF(0, r.Y + r.Height), top, bottom);
        FillRound(g, r, SF(9), fill);
        // Inner bevel highlight.
        LinearGradientBrush bevel(PointF(0, r.Y), PointF(0, r.Y + r.Height * 0.5f), Color(enabled ? 60 : 20, 255, 230, 200),
                                  Color(0, 255, 230, 200));
        FillRound(g, RectF(r.X + SF(2), r.Y + SF(2), r.Width - SF(4), r.Height * 0.5f), SF(8), bevel);
        StrokeRound(g, r, SF(9), enabled ? (hover ? Pal::GoldHi : Pal::GoldLt) : Pal::Steel, SF(1.5f));
        StrokeRound(g, RectF(r.X + SF(4), r.Y + SF(4), r.Width - SF(8), r.Height - SF(8)), SF(6),
                    WithAlpha(enabled ? Pal::Gold : Pal::Steel, 110), SF(1));
        std::wstring label = PlayLabel(s.phase);
        Font* pf = MakeFont(g_TitleFamily, label.size() > 6 ? 19.0f : 28.0f, FontStyleBold);
        DrawStr(g, label, pf, RectF(r.X, r.Y + SF(1), r.Width, r.Height), Color(160, 20, 4, 4), StringAlignmentCenter,
                 StringAlignmentCenter);
        DrawStr(g, label, pf, r, enabled ? Pal::GoldHi : Pal::Dim, StringAlignmentCenter, StringAlignmentCenter);
        delete pf;
    }

    // Window edge.
    Pen edge(WithAlpha(Pal::GoldDk, 255), 1.0f);
    g.DrawRectangle(&edge, 0, 0, cw - 1, ch - 1);

    delete small;
    delete tiny;
    delete title;
    delete subtitle;
    delete statusTitle;
    delete statusDetail;

    Graphics screen(hdc);
    screen.DrawImage(&frame, 0, 0);
}

void Repaint() {
    if (g_Wnd) InvalidateRect(g_Wnd, NULL, FALSE);
}


// ------------------------------------------------------------------ actions

Hit HitTest(int x, int y) {
    Layout L = CurrentLayout();
    if (Contains(L.close, x, y)) return Hit::Close;
    if (Contains(L.minimize, x, y)) return Hit::Minimize;
    if (Contains(L.play, x, y)) return Hit::Play;
    if (Contains(L.repair, x, y)) return Hit::Repair;
    return Hit::None;
}

void Activate(Hit h) {
    switch (h) {
        case Hit::Close: PostMessageW(g_Wnd, WM_CLOSE, 0, 0); break;
        case Hit::Minimize: ShowWindow(g_Wnd, SW_MINIMIZE); break;
        case Hit::Play:
            if (PlayEnabled(CurrentPhase()) && hpmmo::app::OnPlay()) {
                SetTimer(g_Wnd, kTimerGame, 2500, NULL);
                ShowWindow(g_Wnd, SW_MINIMIZE);
            }
            break;
        case Hit::Repair:
            hpmmo::app::RequestRepair();
            break;
        default: break;
    }
}

LRESULT CALLBACK WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
        case WM_CREATE:
            g_Wnd = hWnd;
            SetTimer(hWnd, kTimerAnim, 33, NULL);
            SetTimer(hWnd, kTimerStatus, kStatusPollMs, NULL);
            SetTimer(hWnd, kTimerRecheck, kRecheckMs, NULL);
            StartWorker();
            StartStatusPoll();
            return 0;
        case WM_TIMER:
            if (wParam == kTimerAnim) {
                g_Anim += 0.033f;
                if (!IsIconic(hWnd)) Repaint();
            } else if (wParam == kTimerStatus) {
                StartStatusPoll();
            } else if (wParam == kTimerGame) {
                if (!hpmmo::app::PollGame()) KillTimer(hWnd, kTimerGame);
            } else if (wParam == kTimerRecheck) {
                hpmmo::app::OnRecheckTimer();
            }
            return 0;
        case WM_APP_REFRESH:
            Repaint();
            return 0;
        case WM_APP_EXIT:
            DestroyWindow(hWnd);
            return 0;
        case WM_NCHITTEST: {
            LRESULT r = DefWindowProcW(hWnd, msg, wParam, lParam);
            if (r != HTCLIENT) return r;
            POINT pt = {GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam)};
            ScreenToClient(hWnd, &pt);
            if (pt.y < S(kTopBar) && HitTest(pt.x, pt.y) == Hit::None) return HTCAPTION;
            return HTCLIENT;
        }
        case WM_MOUSEMOVE: {
            if (!g_Tracking) {
                TRACKMOUSEEVENT tme = {sizeof(tme), TME_LEAVE, hWnd, 0};
                TrackMouseEvent(&tme);
                g_Tracking = true;
            }
            Hit h = HitTest(GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam));
            if (h != g_Hover) {
                g_Hover = h;
                Repaint();
            }
            return 0;
        }
        case WM_MOUSELEAVE:
            g_Tracking = false;
            g_Hover = Hit::None;
            g_Pressed = Hit::None;
            Repaint();
            return 0;
        case WM_SETCURSOR: {
            if (LOWORD(lParam) == HTCLIENT) {
                bool hand = g_Hover == Hit::Play ? PlayEnabled(CurrentPhase()) : g_Hover != Hit::None;
                SetCursor(LoadCursor(NULL, hand ? IDC_HAND : IDC_ARROW));
                return TRUE;
            }
            break;
        }
        case WM_LBUTTONDOWN:
            g_Pressed = HitTest(GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam));
            SetCapture(hWnd);
            Repaint();
            return 0;
        case WM_LBUTTONUP: {
            ReleaseCapture();
            Hit h = HitTest(GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam));
            Hit pressed = g_Pressed;
            g_Pressed = Hit::None;
            Repaint();
            if (h == pressed) Activate(h);
            return 0;
        }
        case WM_KEYDOWN:
            if (wParam == VK_RETURN || wParam == VK_SPACE) Activate(Hit::Play);
            if (wParam == VK_ESCAPE) ShowWindow(hWnd, SW_MINIMIZE);
            return 0;
        case WM_ERASEBKGND:
            return 1;
        case WM_PAINT: {
            PAINTSTRUCT ps;
            HDC hdc = BeginPaint(hWnd, &ps);
            RECT rc;
            GetClientRect(hWnd, &rc);
            if (rc.right > 0 && rc.bottom > 0) Paint(hdc, rc.right, rc.bottom);
            EndPaint(hWnd, &ps);
            return 0;
        }
        case WM_CLOSE: {
            Phase p = CurrentPhase();
            if (p == Phase::Downloading || p == Phase::Installing) {
                int answer = MessageBoxW(hWnd, L"Güncelleme sürüyor. Şimdi kapatırsan indirme bir sonraki açılışta kaldığı yerden devam eder.\n\nKapatılsın mı?",
                                         L"Thousand Realms", MB_YESNO | MB_ICONQUESTION);
                if (answer != IDYES) return 0;
                hpmmo::app::Cancel();
            }
            DestroyWindow(hWnd);
            return 0;
        }
        case WM_DESTROY:
            KillTimer(hWnd, kTimerAnim);
            KillTimer(hWnd, kTimerStatus);
            KillTimer(hWnd, kTimerGame);
            KillTimer(hWnd, kTimerRecheck);
            PostQuitMessage(0);
            return 0;
    }
    return DefWindowProcW(hWnd, msg, wParam, lParam);
}

// Headless CLI modes: the GUI executable also answers --check/--update/...,
// --print-cert-pin and the self-update helper so a single distributed binary
// can act as its own updater bootstrap.
int RunHeadlessFromGuiArgs() {
    int argcW = 0;
    LPWSTR* argvW = CommandLineToArgvW(GetCommandLineW(), &argcW);
    if (!argvW || argcW < 2) {
        if (argvW) LocalFree(argvW);
        return -1;  // no updater arguments: continue to the GUI
    }
    std::vector<std::string> narrow;
    narrow.reserve(argcW);
    for (int i = 0; i < argcW; i++) narrow.push_back(hpmmo::WideToUtf8(argvW[i]));
    std::vector<char*> argv;
    argv.reserve(argcW);
    for (auto& s : narrow) argv.push_back(&s[0]);
    LocalFree(argvW);

    hpmmo::CliOptions opts;
    std::string err;
    if (!hpmmo::ParseCliArgs(argcW, argv.data(), opts, err)) return -1;

    // A GUI-subsystem process only has console handles when the parent
    // redirected them; otherwise reattach to the parent console so operator
    // output is visible. Redirected pipes are left untouched.
    HANDLE stdoutHandle = GetStdHandle(STD_OUTPUT_HANDLE);
    bool haveStdout = stdoutHandle != NULL && stdoutHandle != INVALID_HANDLE_VALUE;
    if (!haveStdout && AttachConsole(ATTACH_PARENT_PROCESS)) {
        freopen("CONOUT$", "w", stdout);
        freopen("CONOUT$", "w", stderr);
    }

    if (opts.command == "help") {
        hpmmo::PrintUsage(stdout);
        fflush(stdout);
        return 0;
    }
    if (opts.helper.empty() && opts.command.empty()) return -1;
    int code = 0;
    if (opts.helper == "self-update-swap") {
        code = hpmmo::RunSelfUpdateSwap(hpmmo::WideToUtf8(opts.helperPid), opts.helperTarget, hpmmo::GetExePath(),
                                        opts.relaunch);
    } else if (opts.helper == "print-cert-pin") {
        code = hpmmo::RunPrintCertPin(opts.helperUrl);
    } else {
        hpmmo::CommandResult r = hpmmo::RunCliCommand(opts);
        printf("%s\n", r.json.c_str());
        fflush(stdout);
        code = r.code;
    }
    return code;
}

bool HasArg(const wchar_t* flag) {
    int argcW = 0;
    LPWSTR* argvW = CommandLineToArgvW(GetCommandLineW(), &argcW);
    bool found = false;
    if (argvW) {
        for (int i = 1; i < argcW; i++)
            if (_wcsicmp(argvW[i], flag) == 0) found = true;
        LocalFree(argvW);
    }
    return found;
}

}  // namespace

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int nCmdShow) {
    {
        int headless = RunHeadlessFromGuiArgs();
        if (headless >= 0) return headless;
    }
    if (HasArg(L"--post-self-update")) {
        hpmmo::SetLogPath(hpmmo::JoinPath(hpmmo::GetExeDir(), L"launcher.log"));
        hpmmo::LogMsg("[Launcher] restarted after self-update");
        wchar_t flag[8] = {0};
        if (GetEnvironmentVariableW(L"HPMMO_TEST_NO_GUI", flag, 8) > 0) return 0;
    }

    // One launcher at a time: a second start brings the first to the front.
    // (A relaunch after self-update waits briefly for the old process to exit.)
    HANDLE single = NULL;
    for (int attempt = 0; attempt < 20; attempt++) {
        single = CreateMutexW(NULL, TRUE, L"Local\\HPMMO_Launcher_Singleton");
        if (GetLastError() != ERROR_ALREADY_EXISTS) break;
        CloseHandle(single);
        single = NULL;
        if (!HasArg(L"--post-self-update")) {
            HWND other = FindWindowW(L"HPMMO_Launcher_Class", NULL);
            if (other) {
                ShowWindow(other, SW_RESTORE);
                SetForegroundWindow(other);
            }
            return 0;
        }
        Sleep(250);
    }

    SetProcessDPIAware();
    {
        HDC screen = GetDC(NULL);
        g_Scale = GetDeviceCaps(screen, LOGPIXELSX) / 96.0f;
        ReleaseDC(NULL, screen);
        if (g_Scale < 1.0f) g_Scale = 1.0f;
    }

    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);
    GdiplusStartupInput gdiplusStartupInput;
    GdiplusStartup(&g_GdiToken, &gdiplusStartupInput, NULL);
    LoadAssets();

    hpmmo::LoadConfig();
    hpmmo::app::Hooks hooks;
    hooks.refresh = [] {
        if (g_Wnd) PostMessageW(g_Wnd, WM_APP_REFRESH, 0, 0);
    };
    hooks.exitForSelfUpdate = [] { PostMessageW(g_Wnd, WM_APP_EXIT, 0, 0); };
    hpmmo::app::Init(hpmmo::Config(), hooks);

    WNDCLASSEXW wcex = {sizeof(wcex)};
    wcex.style = CS_HREDRAW | CS_VREDRAW | CS_DROPSHADOW;
    wcex.lpfnWndProc = WndProc;
    wcex.hInstance = hInstance;
    wcex.hCursor = LoadCursor(NULL, IDC_ARROW);
    wcex.hbrBackground = NULL;
    wcex.lpszClassName = L"HPMMO_Launcher_Class";
    wcex.hIcon = LoadIconW(hInstance, MAKEINTRESOURCEW(IDI_MAIN));
    if (!wcex.hIcon) wcex.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    wcex.hIconSm = wcex.hIcon;
    RegisterClassExW(&wcex);

    int winW = S(kBaseW), winH = S(kBaseH);
    RECT work;
    SystemParametersInfoW(SPI_GETWORKAREA, 0, &work, 0);
    int posX = work.left + ((work.right - work.left) - winW) / 2;
    int posY = work.top + ((work.bottom - work.top) - winH) / 2;

    HWND hWnd = CreateWindowExW(WS_EX_APPWINDOW, L"HPMMO_Launcher_Class", L"Thousand Realms",
                                WS_POPUP | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN, posX, posY, winW, winH,
                                NULL, NULL, hInstance, NULL);
    if (!hWnd) return 1;
    // Windows 11: rounded corners on the borderless window (ignored elsewhere).
    DWORD corner = 2;  // DWMWCP_ROUND
    DwmSetWindowAttribute(hWnd, 33 /* DWMWA_WINDOW_CORNER_PREFERENCE */, &corner, sizeof(corner));

    ShowWindow(hWnd, nCmdShow);
    UpdateWindow(hWnd);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    hpmmo::app::Cancel();
    FreeAssets();
    GdiplusShutdown(g_GdiToken);
    WSACleanup();
    if (single) {
        ReleaseMutex(single);
        CloseHandle(single);
    }
    return (int)msg.wParam;
}
