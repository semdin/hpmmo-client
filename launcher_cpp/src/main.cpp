#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <objidl.h>
#include <propidl.h>
#include <gdiplus.h>
#include <commctrl.h>
#include <windowsx.h>
#include <winhttp.h>
#include <shlwapi.h>
#include <shellapi.h>

#include <cstdio>
#include <string>
#include <vector>
#include <sstream>
#include <thread>
#include <atomic>
#include <chrono>
#include <fstream>
#include <algorithm>
#include <mutex>

#include "updater.h"

using namespace Gdiplus;

// Control IDs
enum {
    ID_TAB_LOGIN = 1001,
    ID_TAB_REGISTER = 1002,
    ID_EDT_USER = 1003,
    ID_EDT_PASS = 1004,
    ID_BTN_AUTH = 1005,
    ID_BTN_PLAY = 1006,
    ID_BTN_SOLO = 1007,
    ID_CHK_REMEMBER = 1008,
    ID_LBL_STATUS = 1009,
    ID_BTN_UPDATE = 1010,
    ID_BTN_RECHECK = 1011,
    ID_BTN_NOTES = 1012,
    ID_CHK_SHOWPW = 1013,
    ID_TIMER_PING = 2001,
    ID_TIMER_UPDATE = 2002,
    ID_TIMER_ANIM = 2003
};

// Modern dark-wizard theme palette (single source of truth for GDI + GDI+).
namespace Theme {
    constexpr COLORREF Bg        = RGB(13, 16, 23);
    constexpr COLORREF Card      = RGB(22, 27, 38);
    constexpr COLORREF CardEdge  = RGB(42, 51, 72);
    constexpr COLORREF EditBg    = RGB(13, 17, 26);
    constexpr COLORREF EditEdge  = RGB(58, 70, 99);
    constexpr COLORREF Text      = RGB(232, 236, 244);
    constexpr COLORREF Muted     = RGB(154, 165, 189);
    constexpr COLORREF Gold      = RGB(212, 175, 55);
    constexpr COLORREF GoldLight = RGB(240, 216, 120);
    constexpr COLORREF GoldDark  = RGB(150, 115, 30);
    constexpr COLORREF Green     = RGB(52, 209, 123);
    constexpr COLORREF GreenDark = RGB(29, 166, 92);
    constexpr COLORREF Blue      = RGB(74, 144, 217);
    constexpr COLORREF BlueDark  = RGB(47, 107, 179);
    constexpr COLORREF Red       = RGB(255, 107, 107);
    constexpr COLORREF Disabled  = RGB(58, 65, 85);
}

// Hovered owner-draw button (for hover glow). Set on WM_MOUSEMOVE.
static HWND g_HoverBtn = NULL;

// Resource IDs (must match app.rc).
#define IDI_MAIN 101

// Main-thread messages posted by updater workers.
#define WM_UPDATER_CHECKED (WM_USER + 200)
#define WM_UPDATER_STATUS (WM_USER + 201)
#define WM_UPDATER_DONE (WM_USER + 202)

// Application Configuration
struct AppConfig {
    std::wstring serverIp = L"213.250.145.75";
    int serverPort = 7777;
    int apiPort = 8081;
    std::wstring lastUsername = L"";
    bool rememberMe = true;
};

static AppConfig g_Config;
static bool g_IsRegisterMode = false;
static bool g_IsAuthenticated = false;
static std::wstring g_AuthedUser = L"";
// In-memory login session token (never logged, never written to disk). The
// account password is never retained after authentication.
static std::wstring g_AuthedToken = L"";

static HWND g_hMainWnd = NULL;
static HWND g_hTabLogin = NULL;
static HWND g_hTabRegister = NULL;
static HWND g_hEdtUser = NULL;
static HWND g_hEdtPass = NULL;
static HWND g_hBtnAuth = NULL;
static HWND g_hBtnPlay = NULL;
static HWND g_hBtnSolo = NULL;
static HWND g_hBtnUpdate = NULL;
static HWND g_hBtnRecheck = NULL;
static HWND g_hBtnNotes = NULL;
static HWND g_hChkRemember = NULL;
static HWND g_hChkShowPw = NULL;
static HWND g_hLblStatus = NULL;

// the release pipeline: updater state shared with the UI thread.
static std::mutex g_UpdMutex;
static hpmmo::CheckSummary g_UpdSummary;
static std::wstring g_UpdLine1;
static std::wstring g_UpdLine2;
static std::wstring g_UpdProgress;
static std::atomic<bool> g_UpdBusy{false};
static std::atomic<bool> g_UpdCancel{false};
static std::atomic<int> g_UpdLastCheckSeconds{0};

static HFONT g_hFontTitle = NULL;
static HFONT g_hFontHeading = NULL;
static HFONT g_hFontNormal = NULL;
static HFONT g_hFontButton = NULL;
static HFONT g_hFontSmall = NULL;

static HBRUSH g_hBrushBg = NULL;
static HBRUSH g_hBrushCard = NULL;
static HBRUSH g_hBrushEdit = NULL;

static ULONG_PTR g_gdiplusToken = 0;
static Image* g_pBannerImg = nullptr;
static Image* g_pLogoImg = nullptr;

// ---- Optional UI kit art (client/assets/ui, nine-patch PNGs)
// The launcher is GDI+, so the kit would be blitted as nine-patch PNGs rather
// than as Godot styleboxes. The art is not shipped: every pointer stays null and
// each draw site falls back to the flat rounded-rect chrome, which is what the
// client theme looks like too.
static Image* g_UiFrame = nullptr;      // ornate window frame
static Image* g_UiInset = nullptr;      // recessed input bed
static Image* g_UiRibbon = nullptr;     // red title ribbon
static Image* g_UiDivider = nullptr;    // gold rule
static Image* g_UiCoin = nullptr;
static Image* g_UiBtn[4] = {nullptr, nullptr, nullptr, nullptr};  // normal, hover, pressed, disabled
// These match the borders such a kit draws, so the stretch strips stay flat and
// the corners never smear.
static const int kBtnMargin = 8;
static const int kFrameMargin = 16;
static const int kInsetMargin = 8;

static std::atomic<int> g_ServerPingMs{-1};
static std::atomic<bool> g_ServerOnline{false};
static std::wstring g_StatusMsg = L"Sunucuya bağlanılıyor…";
static COLORREF g_StatusColor = RGB(200, 200, 200);

// Helper: Convert string types
std::wstring Utf8ToWide(const std::string& str) {
    if (str.empty()) return L"";
    int size = MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), NULL, 0);
    std::wstring wstr(size, 0);
    MultiByteToWideChar(CP_UTF8, 0, str.c_str(), (int)str.size(), &wstr[0], size);
    return wstr;
}

std::string WideToUtf8(const std::wstring& wstr) {
    if (wstr.empty()) return "";
    int size = WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), NULL, 0, NULL, NULL);
    std::string str(size, 0);
    WideCharToMultiByte(CP_UTF8, 0, wstr.c_str(), (int)wstr.size(), &str[0], size, NULL, NULL);
    return str;
}

// ---- Owner-draw button helpers (modern rounded theme, no extra deps) ----
static void FillRoundedRect(Graphics& g, const Rect& rc, int radius,
                            const Color& top, const Color& bottom) {
    GraphicsPath path;
    int d = radius * 2;
    path.AddArc(rc.X, rc.Y, d, d, 180, 90);
    path.AddArc(rc.X + rc.Width - d - 1, rc.Y, d, d, 270, 90);
    path.AddArc(rc.X + rc.Width - d - 1, rc.Y + rc.Height - d - 1, d, d, 0, 90);
    path.AddArc(rc.X, rc.Y + rc.Height - d - 1, d, d, 90, 90);
    path.CloseFigure();
    LinearGradientBrush brush(Point(rc.X, rc.Y), Point(rc.X, rc.Y + rc.Height), top, bottom);
    g.FillPath(&brush, &path);
}

static void StrokeRoundedRect(Graphics& g, const Rect& rc, int radius,
                              const Color& color, float width = 1.0f) {
    GraphicsPath path;
    int d = radius * 2;
    path.AddArc(rc.X, rc.Y, d, d, 180, 90);
    path.AddArc(rc.X + rc.Width - d - 1, rc.Y, d, d, 270, 90);
    path.AddArc(rc.X + rc.Width - d - 1, rc.Y + rc.Height - d - 1, d, d, 0, 90);
    path.AddArc(rc.X, rc.Y + rc.Height - d - 1, d, d, 90, 90);
    path.CloseFigure();
    Pen pen(color, width);
    g.DrawPath(&pen, &path);
}

// ---- Generated UI kit helpers ----

// The exe runs from either the workspace root or launcher_cpp/, so probe the
// same relative roots the banner and logo already use.
static Image* LoadUiImage(const wchar_t* file) {
    const wchar_t* roots[] = {
        L"assets\\ui\\", L"..\\assets\\ui\\", L"..\\..\\assets\\ui\\",
    };
    for (const wchar_t* root : roots) {
        std::wstring path = std::wstring(root) + file;
        Image* img = Image::FromFile(path.c_str());
        if (img && img->GetLastStatus() == Ok) return img;
        delete img;
    }
    return nullptr;
}

static void LoadUiKit() {
    g_UiFrame   = LoadUiImage(L"frame_window.png");
    g_UiInset   = LoadUiImage(L"frame_inset.png");
    g_UiRibbon  = LoadUiImage(L"ribbon_title.png");
    g_UiDivider = LoadUiImage(L"divider_ornate.png");
    g_UiCoin    = LoadUiImage(L"coin.png");
    g_UiBtn[0]  = LoadUiImage(L"button_normal.png");
    g_UiBtn[1]  = LoadUiImage(L"button_hover.png");
    g_UiBtn[2]  = LoadUiImage(L"button_pressed.png");
    g_UiBtn[3]  = LoadUiImage(L"button_grey.png");
}

static void FreeUiKit() {
    Image** all[] = {&g_UiFrame, &g_UiInset, &g_UiRibbon, &g_UiDivider, &g_UiCoin,
                     &g_UiBtn[0], &g_UiBtn[1], &g_UiBtn[2], &g_UiBtn[3]};
    for (Image** p : all) { delete *p; *p = nullptr; }
}

// Stretch a nine-patch into `r`. The middle strips take the slack, so the
// corner ornaments keep their proportions at any window size - the same thing
// StyleBoxTexture does on the Godot side.
static void DrawNinePatch(Graphics& g, Image* img, int margin, const Rect& r) {
    if (!img || img->GetLastStatus() != Ok) return;
    const int iw = (int)img->GetWidth(), ih = (int)img->GetHeight();
    if (iw <= 0 || ih <= 0) return;
    int mh = margin, mv = margin;
    if (2 * mh >= iw) mh = iw / 3;
    if (2 * mv >= ih) mv = ih / 3;

    const int w = r.Width, h = r.Height;
    const int cw = (mh < w / 2) ? mh : w / 2;
    const int ch = (mv < h / 2) ? mv : h / 2;

    const int sx[3] = {0, mh, iw - mh};
    const int sw[3] = {mh, iw - 2 * mh, mh};
    const int dx[3] = {r.X, r.X + cw, r.X + w - cw};
    const int dw[3] = {cw, w - 2 * cw, cw};
    const int sy[3] = {0, mv, ih - mv};
    const int sh[3] = {mv, ih - 2 * mv, mv};
    const int dy[3] = {r.Y, r.Y + ch, r.Y + h - ch};
    const int dh[3] = {ch, h - 2 * ch, ch};

    for (int col = 0; col < 3; ++col)
        for (int row = 0; row < 3; ++row)
            g.DrawImage(img, Rect(dx[col], dy[row], dw[col], dh[row]),
                        sx[col], sy[row], sw[col], sh[row], UnitPixel);
}

struct BtnLook {
    Color top{255, 40, 48, 66};
    Color bottom{255, 28, 35, 52};
    Color edge{255, 58, 70, 99};
    Color text{255, 232, 236, 244};
    int radius = 10;
    bool goldText = false;
};

// Per-button look. Tabs are drawn flat with an active underline instead.
static BtnLook LookForButton(int id, bool pressed, bool hover, bool disabled,
                             bool* isTab = nullptr) {
    BtnLook look;
    if (isTab) *isTab = false;
    if (id == ID_TAB_LOGIN || id == ID_TAB_REGISTER) {
        if (isTab) *isTab = true;
        return look;
    }
    if (disabled) {
        look.top = look.bottom = Color(255, 40, 46, 62);
        look.edge = Color(255, 52, 60, 80);
        look.text = Color(255, 130, 140, 165);
        return look;
    }
    auto lighten = [&](Color c) {
        auto up = [](BYTE v) -> BYTE { int n = (int)v + 18; return (BYTE)(n > 255 ? 255 : n); };
        return Color(c.GetA(), up(c.GetR()), up(c.GetG()), up(c.GetB()));
    };
    auto darken = [&](Color c) {
        auto dn = [](BYTE v) -> BYTE { int n = (int)v - 22; return (BYTE)(n < 0 ? 0 : n); };
        return Color(c.GetA(), dn(c.GetR()), dn(c.GetG()), dn(c.GetB()));
    };
    switch (id) {
    case ID_BTN_AUTH:
        look.top = Color(255, 240, 216, 120);
        look.bottom = Color(255, 190, 140, 40);
        look.edge = Color(255, 255, 230, 150);
        look.text = Color(255, 26, 20, 8);
        break;
    case ID_BTN_PLAY:
        look.top = Color(255, 52, 209, 123);
        look.bottom = Color(255, 29, 166, 92);
        look.edge = Color(255, 120, 240, 170);
        look.text = Color(255, 255, 255, 255);
        look.radius = 12;
        break;
    case ID_BTN_UPDATE:
        look.top = Color(255, 74, 144, 217);
        look.bottom = Color(255, 47, 107, 179);
        look.edge = Color(255, 130, 180, 240);
        look.text = Color(255, 255, 255, 255);
        look.radius = 8;
        break;
    default:  // SOLO + small ghost buttons
        look.top = Color(255, 35, 42, 61);
        look.bottom = Color(255, 24, 29, 44);
        look.edge = Color(255, 70, 84, 120);
        look.text = Color(255, 220, 226, 238);
        look.radius = (id == ID_BTN_SOLO) ? 10 : 8;
        break;
    }
    if (pressed) {
        look.top = darken(look.top);
        look.bottom = darken(look.bottom);
    } else if (hover) {
        look.top = lighten(look.top);
        look.bottom = lighten(look.bottom);
    }
    return look;
}

static void DrawOwnerButton(LPDRAWITEMSTRUCT di) {
    Graphics g(di->hDC);
    g.SetSmoothingMode(SmoothingModeAntiAlias);
    g.SetTextRenderingHint(TextRenderingHintClearTypeGridFit);
    RECT r = di->rcItem;
    int w = r.right - r.left;
    int h = r.bottom - r.top;
    g.TranslateTransform((REAL)r.left, (REAL)r.top);

    int id = (int)di->CtlID;
    bool pressed = (di->itemState & ODS_SELECTED) != 0;
    bool disabled = (di->itemState & ODS_DISABLED) != 0;
    bool hover = (!disabled && (di->hwndItem == g_HoverBtn));
    bool isTab = false;
    BtnLook look = LookForButton(id, pressed, hover, disabled, &isTab);

    wchar_t text[256] = {0};
    GetWindowTextW(di->hwndItem, text, 255);

    if (isTab) {
        bool active = false;
        if (id == ID_TAB_LOGIN) active = !g_IsRegisterMode;
        if (id == ID_TAB_REGISTER) active = g_IsRegisterMode;
        SolidBrush bg(Color(0, 0, 0, 0));
        g.FillRectangle(&bg, 0, 0, w, h);
        FontFamily ff(L"Segoe UI");
        Gdiplus::Font font(&ff, 15, active ? FontStyleBold : FontStyleRegular, UnitPixel);
        SolidBrush fg(active ? Color(255, 240, 216, 120) : Color(255, 154, 165, 189));
        StringFormat sf;
        sf.SetAlignment(StringAlignmentCenter);
        sf.SetLineAlignment(StringAlignmentCenter);
        RectF layout(0, 0, (REAL)w, (REAL)(h - 3));
        g.DrawString(text, -1, &font, layout, &sf, &fg);
        if (active) {
            SolidBrush bar(Color(255, 212, 175, 55));
            g.FillRectangle(&bar, w / 2 - 34, h - 3, 68, 3);
        }
        return;
    }

    Rect rc(1, 1, w - 2, h - 2);
    Image* plate = disabled ? g_UiBtn[3]
                 : pressed  ? g_UiBtn[2]
                 : hover    ? g_UiBtn[1]
                            : g_UiBtn[0];
    if (!plate) plate = g_UiBtn[0];
    if (plate) {
        // Painted plate from the kit. `g` is already translated to the button's
        // top-left, so the destination rect starts at the origin.
        DrawNinePatch(g, plate, kBtnMargin, Rect(0, 0, w, h));
    } else {
        FillRoundedRect(g, rc, look.radius, look.top, look.bottom);
        Color edge = look.edge;
        if (hover && !pressed) edge = Color(255, 255, 230, 150);
        StrokeRoundedRect(g, rc, look.radius, edge, (id == ID_BTN_PLAY) ? 1.5f : 1.0f);
    }

    // Top gloss highlight for primary buttons (only on the fallback chrome).
    if (!plate && !disabled && (id == ID_BTN_AUTH || id == ID_BTN_PLAY)) {
        GraphicsPath gloss;
        gloss.AddArc(rc.X + 3, rc.Y + 2, (rc.Width - 6), (rc.Height), 180, 90);
        gloss.AddArc(rc.X + 3, rc.Y + 2, (rc.Width - 6), (rc.Height), 270, 90);
        LinearGradientBrush sheen(Point(0, 0), Point(0, h / 2),
                                 Color(90, 255, 255, 255), Color(0, 255, 255, 255));
        Pen sheenPen(&sheen, 1.0f);
        g.DrawLine(&sheenPen, rc.X + look.radius, rc.Y + 2, rc.X + rc.Width - look.radius, rc.Y + 2);
    }

    HFONT hFont = g_hFontButton;
    if (id == ID_BTN_UPDATE || id == ID_BTN_RECHECK || id == ID_BTN_NOTES) hFont = g_hFontSmall;
    if (id == ID_BTN_SOLO) hFont = g_hFontNormal;
    HDC hdc = di->hDC;
    SetBkMode(hdc, TRANSPARENT);
    COLORREF tc = RGB(look.text.GetR(), look.text.GetG(), look.text.GetB());
    if (disabled) tc = RGB(130, 140, 165);
    SetTextColor(hdc, tc);
    SelectObject(hdc, hFont);
    RECT tr = {r.left, r.top, r.right, r.bottom};
    UINT fmt = DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX;
    if (disabled) {
        SetTextColor(hdc, RGB(20, 22, 30));
        RECT tr2 = tr;
        tr2.left += 1;
        tr2.top += 1;
        DrawTextW(hdc, text, -1, &tr2, fmt);
        SetTextColor(hdc, tc);
    }
    DrawTextW(hdc, text, -1, &tr, fmt);
}

// ---- Shared layout (single source of truth for paint + invalidation) ----
namespace Layout {
    constexpr int HeaderH = 150;
    constexpr int LeftX = 40, LeftW = 392, CardY = 178, CardH = 396;
    constexpr int RightX = 448, RightW = 396;
    constexpr int StatusY = 606;
    constexpr int PillW = 236, PillH = 38;

    inline RECT PillRect(int clientW) {
        RECT r = {clientW - PillW - 28, 30, clientW - 28, 30 + PillH + 24};
        return r;
    }
    inline RECT RightCardRect() {
        RECT r = {RightX, CardY, RightX + RightW, CardY + CardH};
        return r;
    }
    inline RECT LeftCardRect() {
        RECT r = {LeftX, CardY, LeftX + LeftW, CardY + CardH};
        return r;
    }
}

// Cached full-window cover background (banner center-cropped + all static
// overlays). Rebuilt only when the client size changes, so WM_PAINT is a
// single 1:1 blit plus cheap text/cards — no per-frame scaling, no stutter.
static Bitmap* g_CoverCache = nullptr;
static int g_CoverW = 0, g_CoverH = 0;

static void RebuildCoverCache(int w, int h) {
    delete g_CoverCache;
    g_CoverCache = new Bitmap(w, h, PixelFormat32bppARGB);
    Graphics g(g_CoverCache);
    g.SetInterpolationMode(InterpolationModeHighQualityBilinear);

    if (g_pBannerImg && g_pBannerImg->GetLastStatus() == Ok) {
        UINT iw = g_pBannerImg->GetWidth(), ih = g_pBannerImg->GetHeight();
        // Cover (center-crop): scale to fill, never distort.
        double sx_ = (double)w / (double)iw, sy_ = (double)h / (double)ih;
        double s = (sx_ > sy_) ? sx_ : sy_;
        int sw = (int)(w / s), sh = (int)(h / s);
        int sx = (int)((iw - sw) / 2), sy = (int)((ih - sh) / 2);
        g.DrawImage(g_pBannerImg, Rect(0, 0, w, h), sx, sy, sw, sh, UnitPixel);
    } else {
        LinearGradientBrush fallback(Point(0, 0), Point(w, h),
                                     Color(255, 32, 38, 62), Color(255, 13, 16, 23));
        g.FillRectangle(&fallback, 0, 0, w, h);
    }

    // Cinematic darkening: readable text everywhere, artwork still visible.
    LinearGradientBrush shadeTop(Point(0, 0), Point(0, Layout::HeaderH + 60),
                                 Color(205, 6, 9, 15), Color(0, 6, 9, 15));
    g.FillRectangle(&shadeTop, 0, 0, w, Layout::HeaderH + 60);
    LinearGradientBrush shadeBottom(Point(0, h - 420), Point(0, h),
                                    Color(0, 6, 9, 15), Color(235, 6, 9, 15));
    g.FillRectangle(&shadeBottom, 0, h - 420, w, 420);
    SolidBrush veil(Color(110, 6, 9, 15));
    g.FillRectangle(&veil, 0, 0, w, h);

    // Gold hairline under the header.
    LinearGradientBrush goldLine(Point(0, 0), Point(w, 0),
                                 Color(255, 110, 90, 28), Color(255, 240, 216, 120));
    Pen p(&goldLine, 2.0f);
    g.DrawLine(&p, 0, Layout::HeaderH, w, Layout::HeaderH);
}

static void BlitCover(Graphics& g, int w, int h) {
    if (!g_CoverCache || w != g_CoverW || h != g_CoverH) {
        RebuildCoverCache(w, h);
        g_CoverW = w;
        g_CoverH = h;
    }
    g.DrawImage(g_CoverCache, 0, 0);
}

// Invalidate only the server-status pill (used by the ping thread).
static void InvalidatePill() {
    if (!g_hMainWnd) return;
    RECT rc;
    GetClientRect(g_hMainWnd, &rc);
    RECT pill = Layout::PillRect(rc.right);
    InvalidateRect(g_hMainWnd, &pill, FALSE);
}

// Invalidate only the right (status/updater) card.
static void InvalidateRightCard() {
    if (!g_hMainWnd) return;
    RECT r = Layout::RightCardRect();
    InflateRect(&r, 2, 2);
    InvalidateRect(g_hMainWnd, &r, FALSE);
}

// ---- Modern borderless edit: vertical centering + focus ring ----
static WNDPROC g_EditProcOrig = nullptr;

// Field chrome is painted by the parent; this returns the chrome rect
// (edit rect inflated) in parent client coordinates.
static RECT FieldChromeRect(HWND hed) {
    RECT er;
    GetWindowRect(hed, &er);
    MapWindowPoints(HWND_DESKTOP, g_hMainWnd, (LPPOINT)&er, 2);
    InflateRect(&er, 3, 3);
    return er;
}

static LRESULT CALLBACK EditSubclassProc(HWND hEd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_NCCALCSIZE: {
        // Vertically center single-line text: split the leftover
        // (field height - text height) into top/bottom padding.
        LRESULT r = CallWindowProcW(g_EditProcOrig, hEd, msg, wParam, lParam);
        if (wParam) {
            NCCALCSIZE_PARAMS* p = (NCCALCSIZE_PARAMS*)lParam;
            HDC hdc = GetDC(hEd);
            HFONT hf = (HFONT)SendMessageW(hEd, WM_GETFONT, 0, 0);
            HFONT old = (HFONT)SelectObject(hdc, hf);
            TEXTMETRICW tm;
            GetTextMetricsW(hdc, &tm);
            SelectObject(hdc, old);
            ReleaseDC(hEd, hdc);
            RECT wr;
            GetWindowRect(hEd, &wr);
            int fieldH = wr.bottom - wr.top;
            int pad = (fieldH - tm.tmHeight) / 2;
            if (pad < 0) pad = 0;
            p->rgrc[0].top += pad - 2;
            p->rgrc[0].bottom -= 2;
            p->rgrc[0].left += 12;
            p->rgrc[0].right -= 8;
        }
        return r;
    }
    case WM_SETFOCUS:
    case WM_KILLFOCUS: {
        LRESULT r = CallWindowProcW(g_EditProcOrig, hEd, msg, wParam, lParam);
        if (g_hMainWnd) {
            RECT chrome = FieldChromeRect(hEd);
            InvalidateRect(g_hMainWnd, &chrome, FALSE);
        }
        // Keep the caret visible after the non-client adjustment.
        InvalidateRect(hEd, NULL, FALSE);
        return r;
    }
    }
    return CallWindowProcW(g_EditProcOrig, hEd, msg, wParam, lParam);
}

// Config file management
void LoadConfig() {
    std::ifstream file("client_config.json");
    if (!file.is_open()) {
        file.open("../client_config.json");
    }
    if (file.is_open()) {
        std::string content((std::istreambuf_iterator<char>(file)), std::istreambuf_iterator<char>());
        file.close();

        auto extractStr = [&](const std::string& key) -> std::string {
            size_t pos = content.find("\"" + key + "\"");
            if (pos == std::string::npos) return "";
            size_t colon = content.find(":", pos);
            if (colon == std::string::npos) return "";
            size_t q1 = content.find("\"", colon);
            if (q1 == std::string::npos) return "";
            size_t q2 = content.find("\"", q1 + 1);
            if (q2 == std::string::npos) return "";
            return content.substr(q1 + 1, q2 - q1 - 1);
        };
        auto extractInt = [&](const std::string& key, int def) -> int {
            size_t pos = content.find("\"" + key + "\"");
            if (pos == std::string::npos) return def;
            size_t colon = content.find(":", pos);
            if (colon == std::string::npos) return def;
            try {
                return std::stoi(content.substr(colon + 1));
            } catch (...) { return def; }
        };

        std::string ip = extractStr("server_ip");
        if (!ip.empty()) g_Config.serverIp = Utf8ToWide(ip);
        g_Config.serverPort = extractInt("server_port", 7777);
        g_Config.apiPort = extractInt("api_port", 8081);
        std::string user = extractStr("last_username");
        if (!user.empty()) g_Config.lastUsername = Utf8ToWide(user);
        // remember_me defaults to true for older configs.
        size_t rpos = content.find("\"remember_me\"");
        if (rpos != std::string::npos) {
            size_t colon = content.find(":", rpos);
            std::string tail = content.substr(colon + 1, 8);
            g_Config.rememberMe = (tail.find("true") != std::string::npos);
            if (!g_Config.rememberMe) g_Config.lastUsername.clear();
        }
    }
}

void SaveConfig() {
    // The GUI owns four keys; everything else in client_config.json belongs to
    // someone else (the release pipeline updater keys release_base_url, status_url,
    // release_channel, release_public_key, release_public_key_id and
    // pinned_spki_sha256 are read by the updater CLI). Rewriting the file from
    // scratch here used to delete them on the next Play click, silently
    // un-wiring the updater. Preserve the whole object instead.
    hpmmo::JsonValue root = hpmmo::JsonValue::Obj();
    std::string existing;
    if (hpmmo::ReadFileBytes(L"client_config.json", existing, 4u * 1024 * 1024)) {
        hpmmo::JsonValue parsed;
        std::string err;
        if (hpmmo::JsonValue::Parse(existing, parsed, err) && parsed.isObject()) {
            root = parsed;
        }
    }
    root.set("server_ip", hpmmo::JsonValue::Str(WideToUtf8(g_Config.serverIp)));
    root.set("server_port", hpmmo::JsonValue::Int(g_Config.serverPort));
    root.set("api_port", hpmmo::JsonValue::Int(g_Config.apiPort));
    root.set("remember_me", hpmmo::JsonValue::Bool(g_Config.rememberMe));
    root.set("last_username", hpmmo::JsonValue::Str(
        g_Config.rememberMe ? WideToUtf8(g_Config.lastUsername) : ""));
    hpmmo::WriteFileAtomic(L"client_config.json", root.Dump() + "\n");
}

// Extract a flat string field from a JSON response. The API only returns
// simple fields the launcher needs ("token", "ticket", "message").
std::string ExtractJsonString(const std::string& json, const std::string& key) {
    size_t pos = json.find("\"" + key + "\"");
    if (pos == std::string::npos) return "";
    size_t colon = json.find(":", pos);
    if (colon == std::string::npos) return "";
    size_t q1 = json.find("\"", colon);
    if (q1 == std::string::npos) return "";
    size_t q2 = json.find("\"", q1 + 1);
    if (q2 == std::string::npos) return "";
    return json.substr(q1 + 1, q2 - q1 - 1);
}

// WinHTTP POST Request
struct HttpResponse {
    bool success = false;
    int statusCode = 0;
    std::string body;
};

HttpResponse HttpPost(const std::wstring& host, WORD port, const std::wstring& path,
                      const std::string& jsonBody, const std::wstring& bearerToken = L"") {
    HttpResponse resp;
    HINTERNET hSession = WinHttpOpen(L"HPMMO_Launcher/2.0",
                                     WINHTTP_ACCESS_TYPE_DEFAULT_PROXY,
                                     WINHTTP_NO_PROXY_NAME,
                                     WINHTTP_NO_PROXY_BYPASS, 0);
    if (!hSession) return resp;

    WinHttpSetTimeouts(hSession, 4000, 4000, 4000, 4000);

    HINTERNET hConnect = WinHttpConnect(hSession, host.c_str(), port, 0);
    if (!hConnect) {
        WinHttpCloseHandle(hSession);
        return resp;
    }

    HINTERNET hRequest = WinHttpOpenRequest(hConnect, L"POST", path.c_str(),
                                           NULL, WINHTTP_NO_REFERER,
                                           WINHTTP_DEFAULT_ACCEPT_TYPES, 0);
    if (!hRequest) {
        WinHttpCloseHandle(hConnect);
        WinHttpCloseHandle(hSession);
        return resp;
    }

    std::wstring headers = L"Content-Type: application/json\r\n";
    if (!bearerToken.empty()) {
        headers += L"Authorization: Bearer " + bearerToken + L"\r\n";
    }
    BOOL bResults = WinHttpSendRequest(hRequest,
                                       headers.c_str(), (DWORD)-1L,
                                       (LPVOID)jsonBody.c_str(), (DWORD)jsonBody.length(),
                                       (DWORD)jsonBody.length(), 0);

    if (bResults) {
        bResults = WinHttpReceiveResponse(hRequest, NULL);
    }

    if (bResults) {
        DWORD dwStatusCode = 0;
        DWORD dwSize = sizeof(dwStatusCode);
        WinHttpQueryHeaders(hRequest,
                            WINHTTP_QUERY_STATUS_CODE | WINHTTP_QUERY_FLAG_NUMBER,
                            WINHTTP_HEADER_NAME_BY_INDEX,
                            &dwStatusCode, &dwSize, WINHTTP_NO_HEADER_INDEX);
        resp.statusCode = (int)dwStatusCode;

        DWORD dwDownloaded = 0;
        do {
            dwSize = 0;
            if (!WinHttpQueryDataAvailable(hRequest, &dwSize)) break;
            if (dwSize == 0) break;

            std::vector<char> buffer(dwSize + 1);
            if (WinHttpReadData(hRequest, &buffer[0], dwSize, &dwDownloaded)) {
                buffer[dwDownloaded] = 0;
                resp.body.append(&buffer[0], dwDownloaded);
            }
        } while (dwSize > 0);

        resp.success = true;
    }

    WinHttpCloseHandle(hRequest);
    WinHttpCloseHandle(hConnect);
    WinHttpCloseHandle(hSession);
    return resp;
}

void LogMsg(const std::string& msg) {
    std::ofstream f("launcher.log", std::ios::app);
    if (f.is_open()) {
        auto now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
        char timeBuf[32];
        strftime(timeBuf, sizeof(timeBuf), "%Y-%m-%d %H:%M:%S", localtime(&now));
        f << "[" << timeBuf << "] " << msg << "\n";
    }
}

// Background Ping Thread (WinSock UDP ping or WinHTTP probe)
bool ProbeUdpPort(const std::wstring& host, int port, int& rttMs) {
    auto t1 = std::chrono::high_resolution_clock::now();
    SOCKET s = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (s == INVALID_SOCKET) return false;

    DWORD timeout = 1200;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char*)&timeout, sizeof(timeout));

    sockaddr_in addr = {};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    std::string ipStr = WideToUtf8(host);
    inet_pton(AF_INET, ipStr.c_str(), &addr.sin_addr);

    const char pingPacket[] = { '\x00', '\x00', '\x00', '\x01', '\x00', '\x00', '\x00', '\x00' };
    int sent = sendto(s, pingPacket, sizeof(pingPacket), 0, (sockaddr*)&addr, sizeof(addr));
    closesocket(s);

    if (sent > 0) {
        auto t2 = std::chrono::high_resolution_clock::now();
        rttMs = (int)std::chrono::duration_cast<std::chrono::milliseconds>(t2 - t1).count();
        if (rttMs <= 0) rttMs = 12;
        return true;
    }
    return false;
}

void CheckServerPing() {
    int udpRtt = 0;
    bool udpOk = ProbeUdpPort(g_Config.serverIp, g_Config.serverPort, udpRtt);

    auto startTime = std::chrono::high_resolution_clock::now();
    HttpResponse res = HttpPost(g_Config.serverIp, (WORD)g_Config.apiPort, L"/api/health", "{}");
    auto endTime = std::chrono::high_resolution_clock::now();

    if (res.success && (res.statusCode == 200 || res.statusCode == 400 || res.statusCode == 404)) {
        int ms = (int)std::chrono::duration_cast<std::chrono::milliseconds>(endTime - startTime).count();
        g_ServerPingMs = ms;
        g_ServerOnline = true;
        LogMsg("[Ping] Server ONLINE via HTTP 8081 (" + std::to_string(ms) + " ms)");
    } else if (udpOk) {
        g_ServerPingMs = udpRtt;
        g_ServerOnline = true;
        LogMsg("[Ping] Server ONLINE via Game Port 7777 UDP (" + std::to_string(udpRtt) + " ms)");
    } else {
        g_ServerPingMs = -1;
        g_ServerOnline = false;
        LogMsg("[Ping] Server OFFLINE: Ports 8081 and 7777 unreachable");
    }

    // Repaint only the status pill — never the whole window (flicker-free).
    InvalidatePill();
}

// ------------------------------------------------------- the release pipeline updater UI --

static std::wstring g_UpdResult = L"";

void PostUpdaterStatus(const std::wstring& text) {
    if (g_hMainWnd) PostMessageW(g_hMainWnd, WM_UPDATER_STATUS, 0, (LPARAM)new std::wstring(text));
}

void RefreshUpdaterUi();

void RunUpdaterCheck() {
    if (g_UpdBusy.exchange(true)) return;
    g_UpdCancel = false;
    std::thread([]() {
        hpmmo::CliOptions opts;
        hpmmo::AppConfig cfg = hpmmo::Config();
        hpmmo::CheckSummary sum = hpmmo::DoCheck(opts, cfg, &g_UpdCancel, PostUpdaterStatus);
        {
            std::lock_guard<std::mutex> lock(g_UpdMutex);
            g_UpdSummary = sum;
        }
        g_UpdBusy = false;
        if (g_hMainWnd) PostMessageW(g_hMainWnd, WM_UPDATER_CHECKED, 0, 0);
    }).detach();
    RefreshUpdaterUi();
}

void RunUpdaterUpdate() {
    if (g_UpdBusy.exchange(true)) return;
    g_UpdCancel = false;
    std::thread([]() {
        hpmmo::CliOptions opts;
        hpmmo::AppConfig cfg = hpmmo::Config();
        hpmmo::CommandResult res = hpmmo::DoUpdate(opts, cfg, &g_UpdCancel, PostUpdaterStatus);
        std::wstring resultMsg;
        {
            hpmmo::JsonValue j;
            std::string err;
            if (hpmmo::JsonValue::Parse(res.json, j, err)) {
                std::string msg = j.str("message");
                if (msg.empty() && res.code == hpmmo::kExitSelfUpdateDone) {
                    msg = "Launcher guncellemesi uygulaniyor; uygulama yeniden baslatilacak.";
                }
                resultMsg = Utf8ToWide(msg);
            }
        }
        hpmmo::CheckSummary sum = hpmmo::DoCheck(opts, cfg, &g_UpdCancel, PostUpdaterStatus);
        {
            std::lock_guard<std::mutex> lock(g_UpdMutex);
            g_UpdSummary = sum;
            g_UpdResult = resultMsg;
        }
        g_UpdBusy = false;
        if (g_hMainWnd) PostMessageW(g_hMainWnd, WM_UPDATER_DONE, (WPARAM)res.code, 0);
    }).detach();
    RefreshUpdaterUi();
}

void RefreshUpdaterUi() {
    if (!g_hMainWnd) return;
    bool busy = g_UpdBusy.load();
    hpmmo::CheckSummary sum;
    {
        std::lock_guard<std::mutex> lock(g_UpdMutex);
        sum = g_UpdSummary;
    }
    std::wstring stateLine = L"● Sunucu durumu bilinmiyor — kontrol için “Tekrar Dene”";
    std::wstring infoLine;
    if (sum.ok) {
        std::string st = sum.state;
        if (st == "MAINTENANCE") {
            stateLine = L"● BAKIM: " + Utf8ToWide(sum.message);
            if (!sum.until.empty()) {
                int64_t until = 0;
                if (hpmmo::ParseIso8601Utc(sum.until, until)) {
                    int64_t left = until - hpmmo::UnixNowSeconds();
                    if (left > 0) {
                        stateLine += L" (~" + Utf8ToWide(hpmmo::FormatDuration(left)) + L" kaldı)";
                    }
                }
            }
        } else if (st == "ONLINE") {
            stateLine = L"● ÇEVRİMİÇİ";
        } else if (st == "OFFLINE") {
            stateLine = L"● ÇEVRİMDIŞI (sunucu yanıt vermiyor)";
        }
        if (!sum.protocolOk) {
            infoLine = L"⚠ " + Utf8ToWide(sum.error) + L" — güncelleme gerekli";
        } else if (sum.selfUpdateRequired) {
            infoLine = L"Launcher güncellemesi gerekli (GÜNCELLE).";
        } else if (sum.updateAvailable) {
            infoLine = L"Yeni sürüm hazır: " + Utf8ToWide(sum.installedVersion) + L" → " +
                       Utf8ToWide(sum.releaseVersion) + L"  (GÜNCELLE)";
        } else {
            infoLine = L"Sürüm güncel: " + Utf8ToWide(sum.installedVersion.empty() ? "yok"
                                                                                    : sum.installedVersion);
        }
    } else if (!sum.error.empty()) {
        stateLine = L"● Bağlantı hatası";
        infoLine = Utf8ToWide(sum.error) + L"  (“Tekrar Dene”)";
    }
    if (!g_UpdResult.empty()) infoLine = g_UpdResult;
    {
        std::lock_guard<std::mutex> lock(g_UpdMutex);
        g_UpdLine1 = stateLine;
        g_UpdLine2 = infoLine;
    }
    bool canUpdate = sum.ok && (sum.updateAvailable || sum.selfUpdateRequired);
    if (busy) {
        // The Update button doubles as Cancel while a transfer is in flight.
        SetWindowTextW(g_hBtnUpdate, L"İptal Et");
        EnableWindow(g_hBtnUpdate, TRUE);
    } else {
        SetWindowTextW(g_hBtnUpdate, L"Güncelle");
        EnableWindow(g_hBtnUpdate, canUpdate ? TRUE : FALSE);
    }
    EnableWindow(g_hBtnRecheck, busy ? FALSE : TRUE);
    EnableWindow(g_hBtnNotes, (!sum.releaseNotes.empty()) ? TRUE : FALSE);
    if (busy) {
        SetWindowTextW(g_hLblStatus, L"Güncelleme işleniyor…");
        g_StatusColor = RGB(240, 200, 80);
    } else if (canUpdate) {
        SetWindowTextW(g_hLblStatus, (stateLine + L"  " + infoLine).c_str());
        g_StatusColor = RGB(240, 200, 80);
    }
    // The status STATIC repaints itself; the parent only needs the right card.
    InvalidateRightCard();
}

// Gate online play on the last check: maintenance, protocol mismatch and a
// required launcher/self update all refuse with a clear message (no login loop).
bool LaunchGateAllows(std::wstring& reason) {
    hpmmo::CheckSummary sum;
    {
        std::lock_guard<std::mutex> lock(g_UpdMutex);
        sum = g_UpdSummary;
    }
    if (!sum.ok) return true;  // no fresh data: keep the existing login flow
    if (sum.selfUpdateRequired) {
        reason = L"Launcher güncellemesi gerekli. Lütfen “Güncelle”ye basın.";
        return false;
    }
    if (sum.state == "MAINTENANCE") {
        reason = L"Sunucu bakımda: " + Utf8ToWide(sum.message) +
                 L"\nBakım bitince tekrar deneyin.";
        return false;
    }
    if (!sum.protocolOk) {
        reason = L"Bu istemci sunucunun protokolüyle uyumlu değil:\n" + Utf8ToWide(sum.error) +
                 L"\nLütfen launcher'ı güncelleyin.";
        return false;
    }
    return true;
}

// Locate Godot Executable
std::wstring FindGodotPath() {
    const wchar_t* candidates[] = {
        L"godot.exe",
        L"..\\godot.exe",
        L"C:\\Users\\mehme\\AppData\\Local\\Microsoft\\WinGet\\Links\\godot.exe",
        L"C:\\Users\\mehme\\AppData\\Local\\Microsoft\\WinGet\\Packages\\GodotEngine.GodotEngine_Microsoft.Winget.Source_8wekyb3d8bbwe\\Godot_v4.7.2-stable_win64.exe"
    };

    for (const auto& path : candidates) {
        if (PathFileExistsW(path)) {
            return path;
        }
    }

    wchar_t pathBuf[MAX_PATH];
    if (SearchPathW(NULL, L"godot.exe", NULL, MAX_PATH, pathBuf, NULL) > 0) {
        return pathBuf;
    }

    return L"godot.exe";
}

// Build the child process environment for an online launch: the inherited
// environment plus HPMMO_TICKET (single-use game ticket) and HPMMO_API_URL
// (the API host the launcher authenticated against). The ticket is delivered
// only here - never on the command line, in a log, or in a file.
std::vector<wchar_t> BuildLaunchEnvironment(const std::wstring& ticket) {
    std::vector<std::wstring> entries;
    LPWCH current = GetEnvironmentStringsW();
    if (current) {
        for (LPWCH p = current; *p; p += wcslen(p) + 1) {
            if (_wcsnicmp(p, L"HPMMO_TICKET=", 13) == 0) continue;
            if (_wcsnicmp(p, L"HPMMO_API_URL=", 14) == 0) continue;
            entries.emplace_back(p);
        }
        FreeEnvironmentStringsW(current);
    }

    entries.push_back(L"HPMMO_API_URL=http://" + g_Config.serverIp + L":" +
                      std::to_wstring(g_Config.apiPort));
    entries.push_back(L"HPMMO_TICKET=" + ticket);
    std::sort(entries.begin(), entries.end());

    std::vector<wchar_t> block;
    for (const auto& entry : entries) {
        block.insert(block.end(), entry.begin(), entry.end());
        block.push_back(L'\0');
    }
    block.push_back(L'\0');
    return block;
}

// Launch Game Process. Online launches receive the game ticket through the
// child environment; the account password is never placed on the command line.
bool LaunchGame(bool soloMode, const std::wstring& username, const std::wstring& ticket) {
    // Prefer an activated, verified installation from the updater layout.
    hpmmo::AppConfig updCfg = hpmmo::Config();
    hpmmo::CliOptions updCli;
    hpmmo::UpdaterPaths updPaths = hpmmo::ComputePaths(updCli, updCfg);
    if (!updPaths.gameExe.empty()) {
        if (hpmmo::LaunchInstalledGame(updPaths, updCfg, soloMode, username, ticket)) return true;
    }

    std::wstring godotPath = FindGodotPath();
    std::wstring cmd;
    std::vector<wchar_t> envBlock;
    LPVOID envPtr = NULL;
    DWORD creationFlags = 0;

    if (soloMode) {
        cmd = L"\"" + godotPath + L"\" scenes/main/main_menu.tscn --solo";
    } else {
        cmd = L"\"" + godotPath + L"\" scenes/main/main_menu.tscn --user \"" +
              username + L"\" --ip \"" + g_Config.serverIp +
              L"\" --port " + std::to_wstring(g_Config.serverPort) + L" --autologin";
        envBlock = BuildLaunchEnvironment(ticket);
        envPtr = envBlock.data();
        creationFlags = CREATE_UNICODE_ENVIRONMENT;
    }

    STARTUPINFOW si = { sizeof(si) };
    PROCESS_INFORMATION pi;
    std::vector<wchar_t> cmdBuffer(cmd.begin(), cmd.end());
    cmdBuffer.push_back(0);

    if (CreateProcessW(NULL, cmdBuffer.data(), NULL, NULL, FALSE, creationFlags, envPtr, NULL, &si, &pi)) {
        CloseHandle(pi.hProcess);
        CloseHandle(pi.hThread);
        return true;
    }
    return false;
}

// Result of the asynchronous game-ticket request, delivered to the UI thread.
struct TicketLaunchRequest {
    bool ok = false;
    std::wstring username;
    std::wstring ticket;
    std::wstring error;
};

// Request a single-use game ticket with the login token and hand the result to
// the UI thread, which launches the game on success. Runs on a background
// thread because the HTTP call blocks.
void RequestTicketThenLaunch(const std::wstring& username, const std::wstring& token) {
    std::thread([username, token]() {
        HttpResponse res = HttpPost(g_Config.serverIp, (WORD)g_Config.apiPort,
                                    L"/api/game-ticket", "{}", token);
        TicketLaunchRequest* req = new TicketLaunchRequest();
        req->username = username;
        if (res.success && (res.statusCode == 200 || res.statusCode == 201)) {
            std::string ticket = ExtractJsonString(res.body, "ticket");
            if (!ticket.empty()) {
                req->ok = true;
                req->ticket = Utf8ToWide(ticket);
            } else {
                req->error = L"Sunucu gecerli bir oyun bileti dondurmedi. Lutfen tekrar deneyin.";
            }
        } else {
            std::string message = ExtractJsonString(res.body, "message");
            req->error = message.empty()
                ? std::wstring(L"Oyun bileti alinamadi (sunucuya ulasilamiyor veya oturum gecersiz).")
                : Utf8ToWide(message);
        }
        PostMessageW(g_hMainWnd, WM_USER + 101, 0, (LPARAM)req);
    }).detach();
}

// UI Mode Switching
void SetUIMode(bool isRegister) {
    g_IsRegisterMode = isRegister;
    if (g_IsRegisterMode) {
        SetWindowTextW(g_hBtnAuth, L"Hesap Oluştur");
        g_StatusMsg = L"Hogwarts kütüğüne adınızı yazdırın.";
        g_StatusColor = RGB(180, 180, 180);
    } else {
        SetWindowTextW(g_hBtnAuth, L"Giriş Yap");
        g_StatusMsg = L"Büyücülük dünyasına girmek için giriş yapın.";
        g_StatusColor = RGB(180, 180, 180);
    }
    SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
    // Tabs repaint themselves via DRAWITEM; only the left card chrome changes.
    if (g_hMainWnd) {
        RECT r = Layout::LeftCardRect();
        InflateRect(&r, 2, 2);
        InvalidateRect(g_hMainWnd, &r, FALSE);
    }
}

// Authentication Worker
void PerformAuthentication() {
    wchar_t userBuf[256] = {0};
    wchar_t passBuf[256] = {0};
    GetWindowTextW(g_hEdtUser, userBuf, 255);
    GetWindowTextW(g_hEdtPass, passBuf, 255);

    std::wstring wUser(userBuf);
    std::wstring wPass(passBuf);

    if (wUser.length() < 3) {
        g_StatusMsg = L"Kullanıcı adı en az 3 karakter olmalıdır!";
        g_StatusColor = RGB(255, 90, 90);
        SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
        return;
    }
    if (wPass.length() < 4) {
        g_StatusMsg = L"Şifre en az 4 karakter olmalıdır!";
        g_StatusColor = RGB(255, 90, 90);
        SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
        return;
    }

    EnableWindow(g_hBtnAuth, FALSE);
    g_StatusMsg = g_IsRegisterMode ? L"Hesap oluşturuluyor..." : L"Giriş yapılıyor...";
    g_StatusColor = RGB(240, 200, 80);
    SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());

    std::thread([wUser, wPass]() {
        std::string jsonBody = "{\"username\":\"" + WideToUtf8(wUser) + "\",\"password\":\"" + WideToUtf8(wPass) + "\"}";
        std::wstring endpoint = g_IsRegisterMode ? L"/api/register" : L"/api/login";

        HttpResponse res = HttpPost(g_Config.serverIp, (WORD)g_Config.apiPort, endpoint, jsonBody);

        PostMessageW(g_hMainWnd, WM_USER + 100, (WPARAM)res.success, (LPARAM)new HttpResponse(res));
    }).detach();
}

// Window Procedure
LRESULT CALLBACK WndProc(HWND hWnd, UINT message, WPARAM wParam, LPARAM lParam) {
    switch (message) {
    case WM_CREATE: {
        // Create Fonts
        g_hFontTitle = CreateFontW(30, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                                   DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                   CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        g_hFontHeading = CreateFontW(17, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
                                     DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                     CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        g_hFontNormal = CreateFontW(16, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                                    DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                    CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        g_hFontButton = CreateFontW(17, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                                    DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                    CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        g_hFontSmall = CreateFontW(14, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                                   DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                   CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");

        g_hBrushBg = CreateSolidBrush(Theme::Bg);
        g_hBrushCard = CreateSolidBrush(Theme::Card);
        g_hBrushEdit = CreateSolidBrush(Theme::EditBg);

        // Load branding images if present
        const wchar_t* bannerPaths[] = {
            L"assets\\branding\\hpmmo_banner.jpg",
            L"..\\assets\\branding\\hpmmo_banner.jpg"
        };
        for (const auto& bp : bannerPaths) {
            if (PathFileExistsW(bp)) {
                g_pBannerImg = Image::FromFile(bp);
                if (g_pBannerImg && g_pBannerImg->GetLastStatus() == Ok) break;
            }
        }

        const wchar_t* logoPaths[] = {
            L"assets\\branding\\hpmmo_logo.jpg",
            L"..\\assets\\branding\\hpmmo_logo.jpg"
        };
        for (const auto& lp : logoPaths) {
            if (PathFileExistsW(lp)) {
                g_pLogoImg = Image::FromFile(lp);
                if (g_pLogoImg && g_pLogoImg->GetLastStatus() == Ok) break;
            }
        }

        // Left card (auth): segmented tabs, borderless modern edits.
        g_hTabLogin = CreateWindowW(L"BUTTON", L"Giriş Yap",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
            64, 232, 168, 36, hWnd, (HMENU)ID_TAB_LOGIN, NULL, NULL);

        g_hTabRegister = CreateWindowW(L"BUTTON", L"Kayıt Ol",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
            240, 232, 168, 36, hWnd, (HMENU)ID_TAB_REGISTER, NULL, NULL);

        // Edit Controls (Username & Password) — borderless; the parent paints
        // the rounded field chrome (see WM_PAINT). Subclassed for vertical
        // text centering (WM_NCCALCSIZE) and focus-ring repaints.
        g_hEdtUser = CreateWindowExW(0, L"EDIT", g_Config.lastUsername.c_str(),
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
            67, 303, 338, 30, hWnd, (HMENU)ID_EDT_USER, NULL, NULL);
        SendMessageW(g_hEdtUser, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);
        SendMessageW(g_hEdtUser, EM_SETCUEBANNER, TRUE, (LPARAM)L"Büyücü adınız");
        SendMessageW(g_hEdtUser, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(12, 8));
        g_EditProcOrig = (WNDPROC)SetWindowLongPtrW(
            g_hEdtUser, GWLP_WNDPROC, (LONG_PTR)EditSubclassProc);
        // Apply the centering immediately (forces NCCALCSIZE now).
        SetWindowPos(g_hEdtUser, NULL, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);

        g_hEdtPass = CreateWindowExW(0, L"EDIT", L"",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_PASSWORD | ES_AUTOHSCROLL,
            67, 367, 338, 30, hWnd, (HMENU)ID_EDT_PASS, NULL, NULL);
        SendMessageW(g_hEdtPass, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);
        SendMessageW(g_hEdtPass, EM_SETCUEBANNER, TRUE, (LPARAM)L"Şifreniz");
        SendMessageW(g_hEdtPass, EM_SETMARGINS, EC_LEFTMARGIN | EC_RIGHTMARGIN, MAKELPARAM(12, 8));
        SetWindowLongPtrW(g_hEdtPass, GWLP_WNDPROC, (LONG_PTR)EditSubclassProc);
        SetWindowPos(g_hEdtPass, NULL, 0, 0, 0, 0,
                     SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED);

        // Remember Me + Show password checkboxes (native, dark-colored).
        g_hChkRemember = CreateWindowW(L"BUTTON", L"Beni hatırla",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX,
            64, 410, 150, 24, hWnd, (HMENU)ID_CHK_REMEMBER, NULL, NULL);
        SendMessageW(g_hChkRemember, WM_SETFONT, (WPARAM)g_hFontSmall, TRUE);
        SendMessageW(g_hChkRemember, BM_SETCHECK,
                     g_Config.rememberMe ? BST_CHECKED : BST_UNCHECKED, 0);

        g_hChkShowPw = CreateWindowW(L"BUTTON", L"Şifreyi göster",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_AUTOCHECKBOX,
            258, 410, 150, 24, hWnd, (HMENU)ID_CHK_SHOWPW, NULL, NULL);
        SendMessageW(g_hChkShowPw, WM_SETFONT, (WPARAM)g_hFontSmall, TRUE);

        // Auth Action Button (owner-drawn gold primary, default for Enter).
        g_hBtnAuth = CreateWindowW(L"BUTTON", L"Giriş Yap",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW | BS_DEFPUSHBUTTON,
            64, 442, 344, 50, hWnd, (HMENU)ID_BTN_AUTH, NULL, NULL);

        // Right card: big Play + Solo + updater row.
        g_hBtnPlay = CreateWindowW(L"BUTTON", L"Oyuna Başla",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
            472, 392, 352, 64, hWnd, (HMENU)ID_BTN_PLAY, NULL, NULL);
        EnableWindow(g_hBtnPlay, FALSE);

        g_hBtnSolo = CreateWindowW(L"BUTTON", L"Çevrimdışı Oyna",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
            472, 464, 352, 42, hWnd, (HMENU)ID_BTN_SOLO, NULL, NULL);

        // the release pipeline: updater controls (right card, below Solo).
        g_hBtnUpdate = CreateWindowW(L"BUTTON", L"Güncelle",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
            472, 514, 112, 34, hWnd, (HMENU)ID_BTN_UPDATE, NULL, NULL);
        EnableWindow(g_hBtnUpdate, FALSE);

        g_hBtnRecheck = CreateWindowW(L"BUTTON", L"Tekrar Dene",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
            592, 514, 112, 34, hWnd, (HMENU)ID_BTN_RECHECK, NULL, NULL);

        g_hBtnNotes = CreateWindowW(L"BUTTON", L"Sürüm Notları",
            WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_OWNERDRAW,
            712, 514, 112, 34, hWnd, (HMENU)ID_BTN_NOTES, NULL, NULL);
        EnableWindow(g_hBtnNotes, FALSE);

        // Status Label
        g_hLblStatus = CreateWindowW(L"STATIC", g_StatusMsg.c_str(),
            WS_CHILD | WS_VISIBLE | SS_LEFT,
            64, 602, 760, 24, hWnd, (HMENU)ID_LBL_STATUS, NULL, NULL);
        SendMessageW(g_hLblStatus, WM_SETFONT, (WPARAM)g_hFontSmall, TRUE);

        // Set ping check timer (every 5 seconds)
        SetTimer(hWnd, ID_TIMER_PING, 5000, NULL);
        // Progress-bar animation timer (only repaints while busy).
        SetTimer(hWnd, ID_TIMER_ANIM, 100, NULL);
        std::thread(CheckServerPing).detach();

        // the release pipeline: initial release check (only when a release base is configured).
        SetTimer(hWnd, ID_TIMER_UPDATE, 60000, NULL);
        if (!hpmmo::Config().releaseBaseUrl.empty()) {
            RunUpdaterCheck();
        } else {
            std::lock_guard<std::mutex> lock(g_UpdMutex);
            g_UpdLine1 = L"● Güncelleme sunucusu yapılandırılmadı";
            g_UpdLine2 = L"client_config.json içine release_base_url ekleyin.";
        }

        return 0;
    }

    case WM_TIMER: {
        if (wParam == ID_TIMER_PING) {
            std::thread(CheckServerPing).detach();
        } else if (wParam == ID_TIMER_UPDATE) {
            // Periodic re-check, but never while a transfer is in flight.
            static int ticks = 0;
            ticks++;
            if (ticks >= 5 && !g_UpdBusy.load() && !hpmmo::Config().releaseBaseUrl.empty()) {
                ticks = 0;
                RunUpdaterCheck();
            }
        } else if (wParam == ID_TIMER_ANIM) {
            // Repaint the progress bar while a transfer is in flight.
            if (g_UpdBusy.load() && g_hMainWnd) {
                RECT rc = {472, 368, 824, 382};
                InvalidateRect(g_hMainWnd, &rc, FALSE);
            }
        }
        return 0;
    }

    case WM_MOUSEMOVE: {
        POINT pt = {GET_X_LPARAM(lParam), GET_Y_LPARAM(lParam)};
        HWND child = ChildWindowFromPoint(hWnd, pt);
        HWND newHover = NULL;
        if (child != hWnd && child != NULL) {
            LONG_PTR style = GetWindowLongPtrW(child, GWL_STYLE);
            if (style & BS_OWNERDRAW) newHover = child;
        }
        if (newHover != g_HoverBtn) {
            HWND old = g_HoverBtn;
            g_HoverBtn = newHover;
            if (old) InvalidateRect(old, NULL, FALSE);
            if (newHover) {
                InvalidateRect(newHover, NULL, FALSE);
                TRACKMOUSEEVENT tme = {sizeof(tme), TME_LEAVE, hWnd, 0};
                TrackMouseEvent(&tme);
            }
        }
        return 0;
    }

    case WM_MOUSELEAVE: {
        if (g_HoverBtn) {
            HWND old = g_HoverBtn;
            g_HoverBtn = NULL;
            InvalidateRect(old, NULL, FALSE);
        }
        return 0;
    }

    case WM_DRAWITEM: {
        DrawOwnerButton((LPDRAWITEMSTRUCT)lParam);
        return TRUE;
    }

    case WM_ERASEBKGND: {
        // We paint the entire client area in WM_PAINT; erasing here would
        // flash a solid color every 5 s (ping) / on every status update.
        return TRUE;
    }

    case WM_CTLCOLORSTATIC: {
        HDC hdc = (HDC)wParam;
        HWND ctrl = (HWND)lParam;
        // Transparent: the parent paints frosted cards / photo behind.
        SetBkMode(hdc, TRANSPARENT);
        if (ctrl == g_hLblStatus) {
            SetTextColor(hdc, g_StatusColor);
        } else {
            // Checkboxes: soft muted text over the card.
            SetTextColor(hdc, Theme::Muted);
        }
        return (LRESULT)GetStockObject(NULL_BRUSH);
    }

    case WM_CTLCOLOREDIT: {
        HDC hdc = (HDC)wParam;
        SetTextColor(hdc, Theme::Text);
        SetBkColor(hdc, Theme::EditBg);
        return (LRESULT)g_hBrushEdit;
    }

    case WM_CTLCOLORBTN: {
        HDC hdc = (HDC)wParam;
        SetTextColor(hdc, Theme::Muted);
        SetBkColor(hdc, Theme::Card);
        return (LRESULT)g_hBrushCard;
    }

    case WM_COMMAND: {
        int wmId = LOWORD(wParam);
        switch (wmId) {
        case ID_TAB_LOGIN:
            SetUIMode(false);
            break;
        case ID_TAB_REGISTER:
            SetUIMode(true);
            break;
        case ID_BTN_AUTH:
            PerformAuthentication();
            break;
        case ID_CHK_SHOWPW: {
            bool show = (SendMessageW(g_hChkShowPw, BM_GETCHECK, 0, 0) == BST_CHECKED);
            SendMessageW(g_hEdtPass, EM_SETPASSWORDCHAR, show ? 0 : (WPARAM)L'•', 0);
            InvalidateRect(g_hEdtPass, NULL, FALSE);
            break;
        }
        case ID_BTN_PLAY: {
            std::wstring gateReason;
            if (!LaunchGateAllows(gateReason)) {
                g_StatusMsg = gateReason;
                g_StatusColor = RGB(255, 90, 90);
                SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
                MessageBoxW(hWnd, gateReason.c_str(), L"Uyumluluk Kontrolü", MB_ICONWARNING);
                break;
            }
            if (g_AuthedToken.empty()) {
                g_StatusMsg = L"Oyuna başlamak için önce giriş yapmalısınız!";
                g_StatusColor = RGB(255, 90, 90);
                SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
                break;
            }

            wchar_t userBuf[256] = {0};
            GetWindowTextW(g_hEdtUser, userBuf, 255);

            std::wstring userToLaunch = (wcslen(userBuf) > 0) ? userBuf : g_AuthedUser;
            if (userToLaunch.empty()) userToLaunch = L"Wizard";

            g_Config.rememberMe =
                (SendMessageW(g_hChkRemember, BM_GETCHECK, 0, 0) == BST_CHECKED);
            g_Config.lastUsername = userToLaunch;
            SaveConfig();

            LogMsg("Launch requested: user=" + WideToUtf8(userToLaunch));
            EnableWindow(g_hBtnPlay, FALSE);
            g_StatusMsg = L"Oyun bileti alınıyor…";
            g_StatusColor = RGB(240, 200, 80);
            SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
            RequestTicketThenLaunch(userToLaunch, g_AuthedToken);
            break;
        }
        case ID_BTN_SOLO: {
            if (LaunchGame(true, L"Wizard", L"")) {
                ShowWindow(hWnd, SW_MINIMIZE);
            } else {
                MessageBoxW(hWnd, L"Godot motoru başlatılamadı! godot.exe yolunu kontrol edin.", L"Hata", MB_ICONERROR);
            }
            break;
        }
        case ID_BTN_UPDATE:
            if (g_UpdBusy.load()) {
                g_UpdCancel = true;
                g_StatusMsg = L"Güncelleme iptal ediliyor...";
                g_StatusColor = RGB(240, 200, 80);
                SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
            } else {
                RunUpdaterUpdate();
            }
            break;
        case ID_BTN_RECHECK:
            RunUpdaterCheck();
            break;
        case ID_BTN_NOTES: {
            std::lock_guard<std::mutex> lock(g_UpdMutex);
            std::wstring notes = Utf8ToWide(g_UpdSummary.releaseNotes);
            if (!notes.empty()) {
                MessageBoxW(hWnd, notes.c_str(), L"Sürüm Notları", MB_ICONINFORMATION);
            }
            break;
        }
        }
        return 0;
    }

    case WM_UPDATER_CHECKED: {
        RefreshUpdaterUi();
        return 0;
    }

    case WM_UPDATER_STATUS: {
        std::wstring* text = (std::wstring*)lParam;
        if (text) {
            {
                std::lock_guard<std::mutex> lock(g_UpdMutex);
                g_UpdProgress = *text;
            }
            SetWindowTextW(g_hLblStatus, text->c_str());
            delete text;
        }
        return 0;
    }

    case WM_UPDATER_DONE: {
        int code = (int)wParam;
        {
            std::lock_guard<std::mutex> lock(g_UpdMutex);
            g_UpdProgress.clear();
        }
        if (code == hpmmo::kExitSelfUpdateDone) {
            MessageBoxW(hWnd,
                        L"Launcher güncellemesi indirildi ve doğrulandı.\n"
                        L"Uygulama şimdi kapanacak; güncel sürüm otomatik olarak başlatılacak.",
                        L"Launcher Güncellemesi", MB_ICONINFORMATION);
            DestroyWindow(hWnd);
            return 0;
        }
        RefreshUpdaterUi();
        hpmmo::CheckSummary sum;
        {
            std::lock_guard<std::mutex> lock(g_UpdMutex);
            sum = g_UpdSummary;
        }
        if (code == hpmmo::kExitOk) {
            g_StatusMsg = L"Güncelleme tamamlandı.";
            g_StatusColor = RGB(100, 255, 120);
        } else {
            g_StatusMsg = Utf8ToWide(sum.error);
            g_StatusColor = RGB(255, 90, 90);
        }
        SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
        InvalidateRect(hWnd, NULL, FALSE);
        return 0;
    }

    case WM_USER + 100: {
        EnableWindow(g_hBtnAuth, TRUE);
        HttpResponse* pResp = (HttpResponse*)lParam;
        if (!pResp) return 0;

        if (pResp->success && (pResp->statusCode == 200 || pResp->statusCode == 201)) {
            wchar_t userBuf[256] = {0};
            GetWindowTextW(g_hEdtUser, userBuf, 255);

            if (g_IsRegisterMode) {
                g_StatusMsg = L"Hesabınız başarıyla oluşturuldu! Şimdi giriş yapabilirsiniz.";
                g_StatusColor = RGB(100, 255, 120);
                SetUIMode(false);
            } else {
                g_IsAuthenticated = true;
                g_AuthedUser = userBuf;
                g_AuthedToken = Utf8ToWide(ExtractJsonString(pResp->body, "token"));
                // The password is not needed anymore: drop it from the form so
                // it is not retained for the launcher's lifetime.
                SetWindowTextW(g_hEdtPass, L"");

                if (g_AuthedToken.empty()) {
                    g_IsAuthenticated = false;
                    g_StatusMsg = L"Sunucu oturum belirteci döndürmedi. Lütfen tekrar deneyin.";
                    g_StatusColor = RGB(255, 80, 80);
                } else {
                    g_StatusMsg = L"Giriş başarılı! “Oyuna Başla” ile dünyayı keşfedin.";
                    g_StatusColor = RGB(100, 255, 120);

                    EnableWindow(g_hBtnPlay, TRUE);
                    SetFocus(g_hBtnPlay);
                }
            }
        } else {
            std::string body = pResp->body;
            std::string msg = "Giriş başarısız! Lütfen bilgilerinizi kontrol edin.";
            size_t mPos = body.find("\"message\"");
            if (mPos != std::string::npos) {
                size_t q1 = body.find("\"", mPos + 9);
                size_t q2 = body.find("\"", q1 + 1);
                if (q1 != std::string::npos && q2 != std::string::npos) {
                    msg = body.substr(q1 + 1, q2 - q1 - 1);
                }
            }
            g_StatusMsg = Utf8ToWide(msg);
            g_StatusColor = RGB(255, 80, 80);
        }

        SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
        delete pResp;
        InvalidateRect(hWnd, NULL, FALSE);
        return 0;
    }

    case WM_USER + 101: {
        TicketLaunchRequest* pReq = (TicketLaunchRequest*)lParam;
        if (!pReq) return 0;

        EnableWindow(g_hBtnPlay, TRUE);
        if (pReq->ok) {
            if (LaunchGame(false, pReq->username, pReq->ticket)) {
                ShowWindow(hWnd, SW_MINIMIZE);
                g_StatusMsg = L"Oyun başlatıldı. İyi oyunlar!";
                g_StatusColor = RGB(100, 255, 120);
            } else {
                g_StatusMsg = L"Godot motoru başlatılamadı! godot.exe yolunu kontrol edin.";
                g_StatusColor = RGB(255, 80, 80);
                MessageBoxW(hWnd, L"Godot motoru başlatılamadı! godot.exe yolunu kontrol edin.", L"Hata", MB_ICONERROR);
            }
        } else {
            g_StatusMsg = pReq->error.empty() ? L"Oyun bileti alınamadı. Lütfen tekrar deneyin." : pReq->error;
            g_StatusColor = RGB(255, 80, 80);
        }

        SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
        delete pReq;
        InvalidateRect(hWnd, NULL, FALSE);
        return 0;
    }

    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC hdc = BeginPaint(hWnd, &ps);

        Graphics graphics(hdc);
        graphics.SetSmoothingMode(SmoothingModeAntiAlias);
        graphics.SetInterpolationMode(InterpolationModeHighQualityBilinear);
        graphics.SetTextRenderingHint(TextRenderingHintClearTypeGridFit);

        RECT clientRc;
        GetClientRect(hWnd, &clientRc);
        int w = clientRc.right;
        int h = clientRc.bottom;
        const int kHeaderH = Layout::HeaderH;

        // Full-window cinematic cover (cached: 1:1 blit, no per-frame scaling).
        BlitCover(graphics, w, h);

        // Frosted cards (rounded, translucent so the artwork breathes through).
        Rect leftCard(Layout::LeftX, Layout::CardY, Layout::LeftW, Layout::CardH);
        Rect rightCard(Layout::RightX, Layout::CardY, Layout::RightW, Layout::CardH);
        if (g_UiFrame) {
            DrawNinePatch(graphics, g_UiFrame, kFrameMargin, leftCard);
            DrawNinePatch(graphics, g_UiFrame, kFrameMargin, rightCard);
        } else {
            FillRoundedRect(graphics, leftCard, 16, Color(238, 26, 32, 47), Color(238, 17, 22, 33));
            StrokeRoundedRect(graphics, leftCard, 16, Color(255, 52, 63, 88));
            FillRoundedRect(graphics, rightCard, 16, Color(238, 26, 32, 47), Color(238, 17, 22, 33));
            StrokeRoundedRect(graphics, rightCard, 16, Color(255, 52, 63, 88));
        }

        // Input field chrome: filled rounded bed + border (gold when focused).
        for (int i = 0; i < 2; i++) {
            HWND hed = (i == 0) ? g_hEdtUser : g_hEdtPass;
            if (!hed) continue;
            RECT er;
            GetWindowRect(hed, &er);
            MapWindowPoints(HWND_DESKTOP, hWnd, (LPPOINT)&er, 2);
            Rect chrome(er.left - 3, er.top - 3,
                        (er.right - er.left) + 6, (er.bottom - er.top) + 6);
            bool focused = (GetFocus() == hed);
            if (g_UiInset) {
                DrawNinePatch(graphics, g_UiInset, kInsetMargin, chrome);
                if (focused) {
                    Pen glow(Color(255, 232, 190, 110), 1.6f);
                    graphics.DrawRectangle(&glow, chrome);
                }
            } else {
                FillRoundedRect(graphics, chrome, 9, Color(255, 12, 16, 25), Color(255, 16, 21, 32));
                StrokeRoundedRect(graphics, chrome, 9,
                                  focused ? Color(255, 232, 190, 90) : Color(255, 62, 74, 104),
                                  focused ? 1.6f : 1.0f);
            }
        }

        SetBkMode(hdc, TRANSPARENT);

        // Logo medallion (circle-clipped).
        if (g_pLogoImg && g_pLogoImg->GetLastStatus() == Ok) {
            GraphicsPath clip;
            clip.AddEllipse(30, 20, 56, 56);
            graphics.SetClip(&clip);
            graphics.DrawImage(g_pLogoImg, 30, 20, 56, 56);
            graphics.ResetClip();
            Pen ring(Color(255, 212, 175, 55), 1.6f);
            graphics.DrawEllipse(&ring, 30, 20, 56, 56);
        }

        // Title block (left of pill, with soft drop shadow for legibility).
        const int tx = (g_pLogoImg ? 98 : 40);
        if (g_UiRibbon) {
            // A nine-patch band behind the title only: the rounded ends stay
            // crisp where a single stretched DrawImage smears the whole ribbon.
            DrawNinePatch(graphics, g_UiRibbon, 8, Rect(tx - 18, 10, 430, 48));
        }
        auto shadowText = [&](int x, int y, const wchar_t* s, int n) {
            SetTextColor(hdc, RGB(0, 0, 0));
            TextOutW(hdc, x + 1, y + 2, s, n);
        };
        // Title and tagline are stacked with fixed rows so they never overlap;
        // each row is sized to the font above it.
        SelectObject(hdc, g_hFontTitle);
        shadowText(tx, 20, L"HOGWARTS MMORPG", 15);
        SetTextColor(hdc, RGB(240, 216, 120));
        TextOutW(hdc, tx, 20, L"HOGWARTS MMORPG", 15);

        SelectObject(hdc, g_hFontHeading);
        shadowText(tx + 2, 66, L"Çevrimiçi Büyücülük Evreni", 25);
        SetTextColor(hdc, RGB(208, 180, 88));
        TextOutW(hdc, tx + 2, 66, L"Çevrimiçi Büyücülük Evreni", 25);

        SelectObject(hdc, g_hFontSmall);
        SetTextColor(hdc, RGB(162, 172, 198));
        TextOutW(hdc, tx + 2, 96, L"v2.0.0  •  Forward+  •  15 Hz Tick  •  ACID DB", 43);

        // Server status pill (top-right, frosted).
        {
            int ping = g_ServerPingMs.load();
            bool online = g_ServerOnline.load();
            std::wstring pill = online ? L"ÇEVRİMİÇİ" : L"ÇEVRİMDIŞI";
            if (online && ping >= 0) pill += L"  •  " + std::to_wstring(ping) + L" ms";
            const int pillX = w - Layout::PillW - 28, pillY = 30;
            Rect pillRc(pillX, pillY, Layout::PillW, Layout::PillH);
            FillRoundedRect(graphics, pillRc, 19, Color(215, 20, 26, 38), Color(215, 14, 19, 30));
            StrokeRoundedRect(graphics, pillRc, 19,
                              online ? Color(255, 52, 209, 123) : Color(255, 255, 107, 107));
            SolidBrush dotBrush(online ? Color(255, 52, 209, 123) : Color(255, 255, 107, 107));
            graphics.FillEllipse(&dotBrush, pillX + 16, pillY + Layout::PillH / 2 - 5, 10, 10);
            SelectObject(hdc, g_hFontSmall);
            SetTextColor(hdc, online ? RGB(125, 242, 165) : RGB(255, 142, 142));
            RECT tr = {pillX + 34, pillY, pillX + Layout::PillW - 8, pillY + Layout::PillH};
            DrawTextW(hdc, pill.c_str(), -1, &tr, DT_LEFT | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX);
            // Realm line under pill
            SetTextColor(hdc, RGB(150, 160, 185));
            RECT rr = {pillX, pillY + Layout::PillH + 5, pillX + Layout::PillW, pillY + Layout::PillH + 25};
            DrawTextW(hdc, L"◇ 213.250.145.75 : 7777", -1, &rr,
                      DT_RIGHT | DT_SINGLELINE | DT_NOPREFIX);
        }

        // Left card: section caption + field labels (small caps, gold-tinted).
        SelectObject(hdc, g_hFontSmall);
        SetTextColor(hdc, RGB(196, 168, 92));
        TextOutW(hdc, 66, 200, L"H E S A P", 9);
        SetTextColor(hdc, RGB(178, 150, 82));
        TextOutW(hdc, 66, 280, L"KULLANICI ADI", 13);
        TextOutW(hdc, 66, 344, L"ŞİFRE", 5);

        // Right card content: title + gold rule.
        SelectObject(hdc, g_hFontHeading);
        SetTextColor(hdc, RGB(246, 226, 135));
        TextOutW(hdc, 472, 200, L"Oyuna Giriş", 10);
        {
            LinearGradientBrush rule(Point(472, 0), Point(600, 0),
                                     Color(255, 212, 175, 55), Color(0, 212, 175, 55));
            Pen rp(&rule, 2.0f);
            graphics.DrawLine(&rp, 472, 228, 600, 228);
        }

        std::wstring line1, line2, progress;
        hpmmo::CheckSummary sum;
        {
            std::lock_guard<std::mutex> lock(g_UpdMutex);
            line1 = g_UpdLine1;
            line2 = g_UpdLine2;
            progress = g_UpdProgress;
            sum = g_UpdSummary;
        }

        auto drawRow = [&](int y, const std::wstring& s, COLORREF c) {
            if (s.empty()) return;
            SelectObject(hdc, g_hFontSmall);
            SetTextColor(hdc, c);
            RECT tr = {472, y, 824, y + 20};
            DrawTextW(hdc, s.c_str(), -1, &tr, DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS | DT_NOPREFIX);
        };

        COLORREF c1 = RGB(220, 160, 70);
        if (sum.ok && sum.state == "MAINTENANCE") c1 = RGB(255, 170, 60);
        else if (sum.ok) c1 = RGB(110, 240, 140);
        if (!line1.empty()) drawRow(256, line1, c1);
        if (!line2.empty()) drawRow(278, line2, RGB(170, 180, 200));
        if (sum.ok) {
            std::wstring meta = L"Sürüm: " +
                                Utf8ToWide(sum.installedVersion.empty() ? "yok" : sum.installedVersion) +
                                L" → " + Utf8ToWide(sum.releaseVersion) + L"   •   Protokol: " +
                                Utf8ToWide(sum.serverVersion);
            drawRow(300, meta, RGB(140, 150, 175));
            if (!sum.releaseNotes.empty()) {
                std::wstring notes = Utf8ToWide(sum.releaseNotes);
                drawRow(322, notes, RGB(130, 140, 165));
            }
        }
        if (!progress.empty()) drawRow(344, progress, RGB(240, 200, 80));

        // Progress bar (animated marquee while busy)
        {
            Rect track(472, 368, 352, 8);
            bool busy = g_UpdBusy.load();
            if (busy) {
                SolidBrush trackBrush(Color(255, 30, 36, 52));
                GraphicsPath tp;
                int td = 8;
                tp.AddArc(track.X, track.Y, td, td, 180, 90);
                tp.AddArc(track.X + track.Width - td, track.Y, td, td, 270, 90);
                tp.AddArc(track.X + track.Width - td, track.Y + track.Height - td, td, td, 0, 90);
                tp.AddArc(track.X, track.Y + track.Height - td, td, td, 90, 90);
                tp.CloseFigure();
                graphics.FillPath(&trackBrush, &tp);
                DWORD tick = GetTickCount();
                int span = 110;
                int x = track.X + (int)((tick / 8) % (track.Width + span)) - span;
                LinearGradientBrush fill(Point(x, 0), Point(x + span, 0),
                                         Color(0, 212, 175, 55), Color(255, 240, 216, 120));
                graphics.SetClip(tp.Clone());
                graphics.FillRectangle(&fill, x, track.Y, span, track.Height);
                graphics.ResetClip();
            }
        }

        // Auth hint inside right card
        SelectObject(hdc, g_hFontSmall);
        if (g_IsAuthenticated) {
            SetTextColor(hdc, RGB(110, 240, 140));
            TextOutW(hdc, 472, 554, L"✓ Kimlik doğrulandı — oyuna bağlanmaya hazırsınız.", 47);
        } else {
            SetTextColor(hdc, RGB(154, 165, 189));
            TextOutW(hdc, 472, 554, L"“Oyuna Başla” giriş yaptıktan sonra aktifleşir.", 44);
        }

        // Left card footer: build identity.
        SelectObject(hdc, g_hFontSmall);
        SetTextColor(hdc, RGB(120, 130, 155));
        TextOutW(hdc, 66, 548, L"HPMMO Launcher v2.0.0  •  doğrulamalı güncelleme", 46);

        // Bottom status separator + dot
        {
            Pen sep(Color(255, 34, 42, 60), 1.0f);
            graphics.DrawLine(&sep, 40, 592, w - 40, 592);
            COLORREF sc = g_StatusColor;
            SolidBrush dot(Color(255, GetRValue(sc), GetGValue(sc), GetBValue(sc)));
            graphics.FillEllipse(&dot, 46, 606, 9, 9);
        }

        EndPaint(hWnd, &ps);
        return 0;
    }

    case WM_DESTROY: {
        KillTimer(hWnd, ID_TIMER_PING);
        KillTimer(hWnd, ID_TIMER_UPDATE);
        KillTimer(hWnd, ID_TIMER_ANIM);
        if (g_hFontTitle) DeleteObject(g_hFontTitle);
        if (g_hFontHeading) DeleteObject(g_hFontHeading);
        if (g_hFontNormal) DeleteObject(g_hFontNormal);
        if (g_hFontButton) DeleteObject(g_hFontButton);
        if (g_hFontSmall) DeleteObject(g_hFontSmall);
        if (g_hBrushBg) DeleteObject(g_hBrushBg);
        if (g_hBrushCard) DeleteObject(g_hBrushCard);
        if (g_hBrushEdit) DeleteObject(g_hBrushEdit);
        if (g_pBannerImg) delete g_pBannerImg;
        if (g_pLogoImg) delete g_pLogoImg;
        if (g_CoverCache) { delete g_CoverCache; g_CoverCache = nullptr; }

        PostQuitMessage(0);
        return 0;
    }
    }
    return DefWindowProcW(hWnd, message, wParam, lParam);
}

// Headless CLI modes: the GUI executable also answers --check/--update/...,
// --print-cert-pin and the self-update helper so a single distributed binary
// can act as its own updater bootstrap.
static int RunHeadlessFromGuiArgs() {
    int argcW = 0;
    LPWSTR* argvW = CommandLineToArgvW(GetCommandLineW(), &argcW);
    if (!argvW || argcW < 2) {
        if (argvW) LocalFree(argvW);
        return -1;  // no updater arguments: continue to the GUI
    }
    std::vector<std::string> narrow;
    narrow.reserve(argcW);
    for (int i = 0; i < argcW; i++) narrow.push_back(WideToUtf8(argvW[i]));
    std::vector<char*> argv;
    argv.reserve(argcW);
    for (auto& s : narrow) argv.push_back(&s[0]);

    hpmmo::CliOptions opts;
    std::string err;
    bool parsed = hpmmo::ParseCliArgs(argcW, argv.data(), opts, err);
    bool postSelfUpdate = false;
    for (int i = 1; i < argcW; i++) {
        if (narrow[i] == "--post-self-update") postSelfUpdate = true;
    }
    LocalFree(argvW);
    if (!parsed) return -1;

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
        code = hpmmo::RunSelfUpdateSwap(WideToUtf8(opts.helperPid), opts.helperTarget,
                                        hpmmo::GetExePath(), opts.relaunch);
    } else if (opts.helper == "print-cert-pin") {
        code = hpmmo::RunPrintCertPin(opts.helperUrl);
    } else {
        hpmmo::CommandResult r = hpmmo::RunCliCommand(opts);
        printf("%s\n", r.json.c_str());
        fflush(stdout);
        code = r.code;
    }
    (void)postSelfUpdate;
    return code;
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int nCmdShow) {
    {
        int headless = RunHeadlessFromGuiArgs();
        if (headless >= 0) return headless;
    }
    // A relaunch after self-update continues into the GUI (unless the test
    // harness asks the process to exit immediately).
    {
        int argcW = 0;
        LPWSTR* argvW = CommandLineToArgvW(GetCommandLineW(), &argcW);
        if (argvW) {
            for (int i = 1; i < argcW; i++) {
                if (_wcsicmp(argvW[i], L"--post-self-update") == 0) {
                    hpmmo::SetLogPath(hpmmo::JoinPath(hpmmo::GetExeDir(), L"launcher.log"));
                    hpmmo::LogMsg("[Launcher] restarted after self-update");
                    wchar_t flag[8] = {0};
                    if (GetEnvironmentVariableW(L"HPMMO_TEST_NO_GUI", flag, 8) > 0) {
                        LocalFree(argvW);
                        return 0;
                    }
                }
            }
            LocalFree(argvW);
        }
    }

    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);

    GdiplusStartupInput gdiplusStartupInput;
    GdiplusStartup(&g_gdiplusToken, &gdiplusStartupInput, NULL);
    LoadUiKit();

    LoadConfig();

    WNDCLASSEXW wcex = { sizeof(wcex) };
    wcex.style = CS_HREDRAW | CS_VREDRAW;
    wcex.lpfnWndProc = WndProc;
    wcex.hInstance = hInstance;
    wcex.hCursor = LoadCursor(NULL, IDC_ARROW);
    wcex.hbrBackground = NULL;
    wcex.lpszClassName = L"HPMMO_Launcher_Class";
    // Embedded icon (app.rc); fall back to the system icon if missing.
    wcex.hIcon = LoadIconW(hInstance, MAKEINTRESOURCEW(IDI_MAIN));
    if (!wcex.hIcon) wcex.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    wcex.hIconSm = LoadIconW(hInstance, MAKEINTRESOURCEW(IDI_MAIN));
    RegisterClassExW(&wcex);

    int screenW = GetSystemMetrics(SM_CXSCREEN);
    int screenH = GetSystemMetrics(SM_CYSCREEN);
    int winW = 900;
    int winH = 700;
    int posX = (screenW - winW) / 2;
    int posY = (screenH - winH) / 2;

    HWND hWnd = CreateWindowExW(
        WS_EX_APPWINDOW,
        L"HPMMO_Launcher_Class",
        L"HPMMO — Hogwarts MMORPG Launcher",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_CLIPCHILDREN,
        posX, posY, winW, winH,
        NULL, NULL, hInstance, NULL
    );

    if (!hWnd) return FALSE;
    g_hMainWnd = hWnd;

    ShowWindow(hWnd, nCmdShow);
    UpdateWindow(hWnd);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        // Dialog-style keyboard handling: Tab / Shift+Tab moves between
        // inputs and buttons, Enter activates the default button (Giriş Yap),
        // arrow keys work inside checkboxes. Without this the window eats Tab.
        if (g_hMainWnd && IsDialogMessageW(g_hMainWnd, &msg)) continue;
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    FreeUiKit();
    GdiplusShutdown(g_gdiplusToken);
    WSACleanup();
    return (int)msg.wParam;
}
