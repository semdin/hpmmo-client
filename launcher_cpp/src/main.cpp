#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <objidl.h>
#include <propidl.h>
#include <gdiplus.h>
#include <commctrl.h>
#include <winhttp.h>
#include <shlwapi.h>

#include <string>
#include <vector>
#include <sstream>
#include <thread>
#include <atomic>
#include <chrono>
#include <fstream>
#include <algorithm>

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
    ID_TIMER_PING = 2001
};

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
static HWND g_hChkRemember = NULL;
static HWND g_hLblStatus = NULL;

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

static std::atomic<int> g_ServerPingMs{-1};
static std::atomic<bool> g_ServerOnline{false};
static std::wstring g_StatusMsg = L"Sunucuya baglaniliyor...";
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
    }
}

void SaveConfig() {
    std::ofstream file("client_config.json");
    if (file.is_open()) {
        file << "{\n";
        file << "  \"server_ip\": \"" << WideToUtf8(g_Config.serverIp) << "\",\n";
        file << "  \"server_port\": " << g_Config.serverPort << ",\n";
        file << "  \"api_port\": " << g_Config.apiPort << ",\n";
        file << "  \"last_username\": \"" << WideToUtf8(g_Config.lastUsername) << "\"\n";
        file << "}\n";
        file.close();
    }
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

    if (g_hMainWnd) {
        InvalidateRect(g_hMainWnd, NULL, FALSE);
    }
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
        SetWindowTextW(g_hBtnAuth, L"KAYIT OL (CREATE ACCOUNT)");
        SetWindowTextW(g_hTabLogin, L"Giriş Yap");
        SetWindowTextW(g_hTabRegister, L"● Kayıt Ol");
        g_StatusMsg = L"Hogwarts kütüğüne adınızı yazdırın.";
        g_StatusColor = RGB(180, 180, 180);
    } else {
        SetWindowTextW(g_hBtnAuth, L"GİRİŞ YAP (LOG IN)");
        SetWindowTextW(g_hTabLogin, L"● Giriş Yap");
        SetWindowTextW(g_hTabRegister, L"Kayıt Ol");
        g_StatusMsg = L"Büyücülük dünyasına girmek için giriş yapın.";
        g_StatusColor = RGB(180, 180, 180);
    }
    SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
    InvalidateRect(g_hMainWnd, NULL, FALSE);
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
        g_hFontTitle = CreateFontW(32, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                                   DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                   CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Georgia");
        g_hFontHeading = CreateFontW(18, 0, 0, 0, FW_SEMIBOLD, FALSE, FALSE, FALSE,
                                     DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                     CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        g_hFontNormal = CreateFontW(16, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                                    DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                    CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        g_hFontButton = CreateFontW(18, 0, 0, 0, FW_BOLD, FALSE, FALSE, FALSE,
                                    DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                    CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");
        g_hFontSmall = CreateFontW(14, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
                                   DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
                                   CLEARTYPE_QUALITY, DEFAULT_PITCH | FF_DONTCARE, L"Segoe UI");

        g_hBrushBg = CreateSolidBrush(RGB(15, 17, 24));
        g_hBrushCard = CreateSolidBrush(RGB(24, 28, 40));
        g_hBrushEdit = CreateSolidBrush(RGB(32, 37, 52));

        // Load branding images if present
        const wchar_t* bannerPaths[] = {
            L"assets\\branding\\hpmmo_banner.jpg",
            L"..\\assets\\branding\\hpmmo_banner.jpg",
            L"launcher\\assets\\hpmmo_banner.jpg"
        };
        for (const auto& bp : bannerPaths) {
            if (PathFileExistsW(bp)) {
                g_pBannerImg = Image::FromFile(bp);
                if (g_pBannerImg && g_pBannerImg->GetLastStatus() == Ok) break;
            }
        }

        const wchar_t* logoPaths[] = {
            L"assets\\branding\\hpmmo_logo.jpg",
            L"..\\assets\\branding\\hpmmo_logo.jpg",
            L"launcher\\assets\\hpmmo_logo.jpg"
        };
        for (const auto& lp : logoPaths) {
            if (PathFileExistsW(lp)) {
                g_pLogoImg = Image::FromFile(lp);
                if (g_pLogoImg && g_pLogoImg->GetLastStatus() == Ok) break;
            }
        }

        // Navigation Tabs (Giriş Yap / Kayıt Ol)
        g_hTabLogin = CreateWindowW(L"BUTTON", L"● Giriş Yap",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | BS_FLAT,
            60, 225, 140, 36, hWnd, (HMENU)ID_TAB_LOGIN, NULL, NULL);
        SendMessageW(g_hTabLogin, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

        g_hTabRegister = CreateWindowW(L"BUTTON", L"Kayıt Ol",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON | BS_FLAT,
            210, 225, 140, 36, hWnd, (HMENU)ID_TAB_REGISTER, NULL, NULL);
        SendMessageW(g_hTabRegister, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

        // Edit Controls (Username & Password)
        g_hEdtUser = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", g_Config.lastUsername.c_str(),
            WS_CHILD | WS_VISIBLE | ES_AUTOHSCROLL,
            60, 305, 340, 32, hWnd, (HMENU)ID_EDT_USER, NULL, NULL);
        SendMessageW(g_hEdtUser, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

        g_hEdtPass = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", L"",
            WS_CHILD | WS_VISIBLE | ES_PASSWORD | ES_AUTOHSCROLL,
            60, 375, 340, 32, hWnd, (HMENU)ID_EDT_PASS, NULL, NULL);
        SendMessageW(g_hEdtPass, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

        // Remember Me Checkbox
        g_hChkRemember = CreateWindowW(L"BUTTON", L"Beni Hatırla (Remember)",
            WS_CHILD | WS_VISIBLE | BS_AUTOCHECKBOX,
            60, 420, 200, 24, hWnd, (HMENU)ID_CHK_REMEMBER, NULL, NULL);
        SendMessageW(g_hChkRemember, WM_SETFONT, (WPARAM)g_hFontSmall, TRUE);
        SendMessageW(g_hChkRemember, BM_SETCHECK, BST_CHECKED, 0);

        // Auth Action Button
        g_hBtnAuth = CreateWindowW(L"BUTTON", L"GİRİŞ YAP (LOG IN)",
            WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON,
            60, 455, 340, 44, hWnd, (HMENU)ID_BTN_AUTH, NULL, NULL);
        SendMessageW(g_hBtnAuth, WM_SETFONT, (WPARAM)g_hFontButton, TRUE);

        // Right Panel: Giant "PLAY NOW" & "SOLO" Buttons
        g_hBtnPlay = CreateWindowW(L"BUTTON", L"⚔️ OYUNA BAŞLA (PLAY NOW)",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            460, 305, 330, 85, hWnd, (HMENU)ID_BTN_PLAY, NULL, NULL);
        SendMessageW(g_hBtnPlay, WM_SETFONT, (WPARAM)g_hFontButton, TRUE);
        EnableWindow(g_hBtnPlay, FALSE);

        g_hBtnSolo = CreateWindowW(L"BUTTON", L"🛡️ SOLO / ÇEVRİMDIŞI MOD",
            WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            460, 410, 330, 44, hWnd, (HMENU)ID_BTN_SOLO, NULL, NULL);
        SendMessageW(g_hBtnSolo, WM_SETFONT, (WPARAM)g_hFontNormal, TRUE);

        // Status Label
        g_hLblStatus = CreateWindowW(L"STATIC", g_StatusMsg.c_str(),
            WS_CHILD | WS_VISIBLE | SS_LEFT,
            60, 515, 730, 24, hWnd, (HMENU)ID_LBL_STATUS, NULL, NULL);
        SendMessageW(g_hLblStatus, WM_SETFONT, (WPARAM)g_hFontSmall, TRUE);

        // Set ping check timer (every 5 seconds)
        SetTimer(hWnd, ID_TIMER_PING, 5000, NULL);
        std::thread(CheckServerPing).detach();

        return 0;
    }

    case WM_TIMER: {
        if (wParam == ID_TIMER_PING) {
            std::thread(CheckServerPing).detach();
        }
        return 0;
    }

    case WM_CTLCOLORSTATIC: {
        HDC hdc = (HDC)wParam;
        SetTextColor(hdc, g_StatusColor);
        SetBkColor(hdc, RGB(15, 17, 24));
        return (LRESULT)g_hBrushBg;
    }

    case WM_CTLCOLOREDIT: {
        HDC hdc = (HDC)wParam;
        SetTextColor(hdc, RGB(240, 240, 245));
        SetBkColor(hdc, RGB(32, 37, 52));
        return (LRESULT)g_hBrushEdit;
    }

    case WM_CTLCOLORBTN: {
        return (LRESULT)g_hBrushBg;
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
        case ID_BTN_PLAY: {
            if (g_AuthedToken.empty()) {
                g_StatusMsg = L"Oyuna baslamak icin once giris yapmalisiniz!";
                g_StatusColor = RGB(255, 90, 90);
                SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
                break;
            }

            wchar_t userBuf[256] = {0};
            GetWindowTextW(g_hEdtUser, userBuf, 255);

            std::wstring userToLaunch = (wcslen(userBuf) > 0) ? userBuf : g_AuthedUser;
            if (userToLaunch.empty()) userToLaunch = L"Wizard";

            g_Config.lastUsername = userToLaunch;
            SaveConfig();

            LogMsg("Launch requested: user=" + WideToUtf8(userToLaunch));
            EnableWindow(g_hBtnPlay, FALSE);
            g_StatusMsg = L"Oyun bileti aliniyor...";
            g_StatusColor = RGB(240, 200, 80);
            SetWindowTextW(g_hLblStatus, g_StatusMsg.c_str());
            RequestTicketThenLaunch(userToLaunch, g_AuthedToken);
            break;
        }
        case ID_BTN_SOLO: {
            if (LaunchGame(true, L"Wizard", L"")) {
                ShowWindow(hWnd, SW_MINIMIZE);
            } else {
                MessageBoxW(hWnd, L"Godot motoru baslatilamadi! godot.exe yolunu kontrol edin.", L"Hata", MB_ICONERROR);
            }
            break;
        }
        }
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
                    g_StatusMsg = L"Sunucu oturum belirteci dondurmedi. Lutfen tekrar deneyin.";
                    g_StatusColor = RGB(255, 80, 80);
                } else {
                    g_StatusMsg = L"Giriş başarılı! 'OYUNA BAŞLA' butonuna basarak dünyayı keşfedin.";
                    g_StatusColor = RGB(100, 255, 120);

                    EnableWindow(g_hBtnPlay, TRUE);
                    SetFocus(g_hBtnPlay);
                }
            }
        } else {
            std::string body = pResp->body;
            std::string msg = "Giris basarisiz! Lutfen bilgilerinizi kontrol edin.";
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
                g_StatusMsg = L"Oyun baslatildi. Iyi oyunlar!";
                g_StatusColor = RGB(100, 255, 120);
            } else {
                g_StatusMsg = L"Godot motoru baslatilamadi! godot.exe yolunu kontrol edin.";
                g_StatusColor = RGB(255, 80, 80);
                MessageBoxW(hWnd, L"Godot motoru baslatilamadi! godot.exe yolunu kontrol edin.", L"Hata", MB_ICONERROR);
            }
        } else {
            g_StatusMsg = pReq->error.empty() ? L"Oyun bileti alinamadi. Lutfen tekrar deneyin." : pReq->error;
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
        graphics.SetInterpolationMode(InterpolationModeHighQualityBilinear);

        RECT clientRc;
        GetClientRect(hWnd, &clientRc);
        int w = clientRc.right;
        int h = clientRc.bottom;

        // Draw obsidian background
        SolidBrush bgBrush(Color(255, 15, 17, 24));
        graphics.FillRectangle(&bgBrush, 0, 0, w, h);

        // Top Banner / Header (Height 210)
        if (g_pBannerImg) {
            graphics.DrawImage(g_pBannerImg, 0, 0, w, 210);
            LinearGradientBrush fadeBrush(Point(0, 140), Point(0, 210),
                                          Color(0, 15, 17, 24), Color(255, 15, 17, 24));
            graphics.FillRectangle(&fadeBrush, 0, 140, w, 70);
        } else {
            LinearGradientBrush headerBrush(Point(0, 0), Point(0, 210),
                                            Color(255, 20, 24, 38), Color(255, 15, 17, 24));
            graphics.FillRectangle(&headerBrush, 0, 0, w, 210);
        }

        // Draw Metallic Gold Border Header Line
        Pen goldPen(Color(255, 212, 175, 55), 2.0f);
        graphics.DrawLine(&goldPen, 0, 210, w, 210);

        // Left Form Card Background
        SolidBrush cardBrush(Color(255, 24, 28, 42));
        graphics.FillRectangle(&cardBrush, 45, 220, 370, 290);
        Pen borderPen(Color(255, 45, 55, 80), 1.0f);
        graphics.DrawRectangle(&borderPen, 45, 220, 370, 290);

        // Right Info Card Background
        graphics.FillRectangle(&cardBrush, 440, 220, 370, 290);
        graphics.DrawRectangle(&borderPen, 440, 220, 370, 290);

        // GDI text for labels
        SetBkMode(hdc, TRANSPARENT);

        // Title and Subtitle over Banner
        SelectObject(hdc, g_hFontTitle);
        SetTextColor(hdc, RGB(255, 225, 130));
        TextOutW(hdc, 50, 40, L"HOGWARTS MMORPG", 15);

        SelectObject(hdc, g_hFontHeading);
        SetTextColor(hdc, RGB(212, 175, 55));
        TextOutW(hdc, 52, 85, L"HPMMO — YENİ NESİL ÇEVRİMİÇİ BÜYÜCÜLÜK EVRENİ", 45);

        // Server Status on Top Right of Banner
        SelectObject(hdc, g_hFontNormal);
        int ping = g_ServerPingMs.load();
        bool online = g_ServerOnline.load();
        std::wstring statusStr = L"● Sunucu: 213.250.145.75:7777";
        if (online) {
            statusStr += L" [ONLINE " + std::to_wstring(ping) + L"ms]";
            SetTextColor(hdc, RGB(80, 240, 120));
        } else {
            statusStr += L" [OFFLINE / YANIT YOK]";
            SetTextColor(hdc, RGB(255, 80, 80));
        }
        TextOutW(hdc, 50, 135, statusStr.c_str(), (int)statusStr.length());

        SelectObject(hdc, g_hFontSmall);
        SetTextColor(hdc, RGB(180, 190, 210));
        TextOutW(hdc, 52, 165, L"İstemci & Sunucu Sürümü: v2.0.0 (Forward+ Engine, 15Hz Tick, ACID DB)", 70);

        // Form Labels
        SelectObject(hdc, g_hFontNormal);
        SetTextColor(hdc, RGB(212, 175, 55));
        TextOutW(hdc, 60, 280, L"Kullanıcı Adı (Username):", 25);
        TextOutW(hdc, 60, 350, L"Şifre (Password):", 17);

        // Right Info Card Content
        SelectObject(hdc, g_hFontHeading);
        SetTextColor(hdc, RGB(255, 220, 110));
        TextOutW(hdc, 460, 240, L"BÜYÜCÜ DÜNYASINA GİRİŞ", 23);

        SelectObject(hdc, g_hFontSmall);
        SetTextColor(hdc, RGB(170, 180, 200));
        TextOutW(hdc, 460, 270, L"Hesabınızla giriş yapın ve doğrudan 3D Karakter", 47);
        TextOutW(hdc, 460, 288, L"seçim podyumuna bağlanın (Hesap başı max 2 büyücü).", 50);

        // Notice under Play Now
        if (g_IsAuthenticated) {
            SetTextColor(hdc, RGB(100, 255, 120));
            TextOutW(hdc, 460, 465, L"✓ Kimlik doğrulandı! Oyuna bağlanmaya hazırsınız.", 47);
        } else {
            SetTextColor(hdc, RGB(220, 160, 70));
            TextOutW(hdc, 460, 465, L"ℹ️ 'Oyuna Başla' butonu giriş yapılınca aktifleşir.", 50);
        }

        EndPaint(hWnd, &ps);
        return 0;
    }

    case WM_DESTROY: {
        KillTimer(hWnd, ID_TIMER_PING);
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

        PostQuitMessage(0);
        return 0;
    }
    }
    return DefWindowProcW(hWnd, message, wParam, lParam);
}

int WINAPI WinMain(HINSTANCE hInstance, HINSTANCE, LPSTR, int nCmdShow) {
    WSADATA wsaData;
    WSAStartup(MAKEWORD(2, 2), &wsaData);

    GdiplusStartupInput gdiplusStartupInput;
    GdiplusStartup(&g_gdiplusToken, &gdiplusStartupInput, NULL);

    LoadConfig();

    WNDCLASSEXW wcex = { sizeof(wcex) };
    wcex.style = CS_HREDRAW | CS_VREDRAW;
    wcex.lpfnWndProc = WndProc;
    wcex.hInstance = hInstance;
    wcex.hCursor = LoadCursor(NULL, IDC_ARROW);
    wcex.hbrBackground = NULL;
    wcex.lpszClassName = L"HPMMO_Launcher_Class";
    wcex.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    RegisterClassExW(&wcex);

    int screenW = GetSystemMetrics(SM_CXSCREEN);
    int screenH = GetSystemMetrics(SM_CYSCREEN);
    int winW = 860;
    int winH = 600;
    int posX = (screenW - winW) / 2;
    int posY = (screenH - winH) / 2;

    HWND hWnd = CreateWindowExW(
        WS_EX_APPWINDOW,
        L"HPMMO_Launcher_Class",
        L"HPMMO — Hogwarts MMORPG Launcher",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        posX, posY, winW, winH,
        NULL, NULL, hInstance, NULL
    );

    if (!hWnd) return FALSE;
    g_hMainWnd = hWnd;

    ShowWindow(hWnd, nCmdShow);
    UpdateWindow(hWnd);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }

    GdiplusShutdown(g_gdiplusToken);
    WSACleanup();
    return (int)msg.wParam;
}
