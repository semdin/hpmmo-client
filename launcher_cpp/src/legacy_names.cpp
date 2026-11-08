// Thousand Realms first shipped as "HPMMO". Launchers downloaded then carry
// the old file name (HPMMO_Launcher.exe, HPMMO_Launcher-x86_64.AppImage,
// "HPMMO Launcher.app"); an old launcher self-updates by writing the new
// binary over its own file, so the name survives the update. The GUI renames
// its own file once on start and points the player's shortcuts at the new
// name. The install folder moves in updater.cpp (MigrateLegacyInstallRoot).
// docs/launcher-and-releases.md, "Rename from HPMMO".
#include "common.h"

#include <string>
#include <vector>

#ifdef _WIN32
#include <objbase.h>
#include <knownfolders.h>
#include <shlobj.h>
#include <shobjidl.h>
#else
#include <cstdlib>
#include <cstring>
#include <dirent.h>
#include <sys/stat.h>
#endif

namespace hpmmo {

namespace {

// "HPMMO_Launcher(...)" -> "ThousandRealms_Launcher(...)": keeps whatever the
// browser appended ("HPMMO_Launcher (1).exe") and the extension.
std::wstring RenamedFileName(const std::wstring& name, const std::wstring& legacyPrefix,
                             const std::wstring& newPrefix) {
    if (name.size() < legacyPrefix.size()) return L"";
    if (!EqualsCI(name.substr(0, legacyPrefix.size()), legacyPrefix)) return L"";
    return newPrefix + name.substr(legacyPrefix.size());
}

void SplitPath(const std::wstring& path, std::wstring& dir, std::wstring& name) {
    size_t slash = path.find_last_of(L"\\/");
    dir = slash == std::wstring::npos ? L"." : path.substr(0, slash);
    name = slash == std::wstring::npos ? path : path.substr(slash + 1);
}

#ifdef _WIN32

std::wstring KnownFolder(REFKNOWNFOLDERID id) {
    PWSTR raw = nullptr;
    std::wstring out;
    if (SUCCEEDED(SHGetKnownFolderPath(id, 0, NULL, &raw)) && raw) out = raw;
    if (raw) CoTaskMemFree(raw);
    return out;
}

std::wstring ExpandEnv(const std::wstring& s) {
    if (s.find(L'%') == std::wstring::npos) return s;
    wchar_t buf[MAX_PATH * 2] = {0};
    DWORD n = ExpandEnvironmentStringsW(s.c_str(), buf, MAX_PATH * 2);
    return n > 0 && n <= MAX_PATH * 2 ? std::wstring(buf) : s;
}

// Rewrites one .lnk whose target is oldExe. Returns true when it was changed.
bool RetargetShortcut(const std::wstring& lnk, const std::wstring& oldExe, const std::wstring& newExe) {
    IShellLinkW* link = nullptr;
    if (FAILED(CoCreateInstance(CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, IID_IShellLinkW, (void**)&link)))
        return false;
    bool changed = false;
    IPersistFile* file = nullptr;
    if (SUCCEEDED(link->QueryInterface(IID_IPersistFile, (void**)&file))) {
        if (SUCCEEDED(file->Load(lnk.c_str(), STGM_READ))) {
            wchar_t target[MAX_PATH * 2] = {0};
            if (SUCCEEDED(link->GetPath(target, MAX_PATH * 2, NULL, SLGP_RAWPATH)) &&
                EqualsCI(NormalizePath(ExpandEnv(target)), NormalizePath(oldExe))) {
                link->SetPath(newExe.c_str());
                wchar_t icon[MAX_PATH * 2] = {0};
                int index = 0;
                if (FAILED(link->GetIconLocation(icon, MAX_PATH * 2, &index))) icon[0] = 0;
                if (icon[0] == 0 || EqualsCI(NormalizePath(ExpandEnv(icon)), NormalizePath(oldExe)))
                    link->SetIconLocation(newExe.c_str(), index);
                wchar_t desc[INFOTIPSIZE] = {0};
                if (SUCCEEDED(link->GetDescription(desc, INFOTIPSIZE)) &&
                    ToLower(desc).find(L"hpmmo") != std::wstring::npos)
                    link->SetDescription(L"Thousand Realms");
                changed = SUCCEEDED(file->Save(lnk.c_str(), TRUE));
                LogMsg(std::string("[Launcher] shortcut ") + (changed ? "updated: " : "could not be updated: ") +
                       WideToUtf8(lnk));
            }
        }
        file->Release();
    }
    link->Release();
    return changed;
}

void FixShortcutsIn(const std::wstring& dir, int depth, bool renameFiles, const std::wstring& oldExe,
                    const std::wstring& newExe, int& budget, int& changed) {
    if (dir.empty() || depth < 0 || budget <= 0) return;
    WIN32_FIND_DATAW fd;
    HANDLE h = FindFirstFileW(JoinPath(dir, L"*").c_str(), &fd);
    if (h == INVALID_HANDLE_VALUE) return;
    std::vector<std::wstring> subdirs;
    do {
        std::wstring name = fd.cFileName;
        if (name == L"." || name == L"..") continue;
        std::wstring full = JoinPath(dir, name);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT)) subdirs.push_back(full);
            continue;
        }
        if (name.size() < 4 || !EqualsCI(name.substr(name.size() - 4), L".lnk")) continue;
        if (--budget <= 0) break;
        if (!RetargetShortcut(full, oldExe, newExe)) continue;
        changed++;
        // A desktop / Start menu entry named after the old game takes the new
        // name; pinned items keep theirs (the taskbar tracks them by name).
        if (renameFiles && ToLower(name).find(L"hpmmo") != std::wstring::npos) {
            std::wstring renamed = JoinPath(dir, L"Thousand Realms.lnk");
            if (!FileExists(renamed)) MoveFileExW(full.c_str(), renamed.c_str(), 0);
        }
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    for (const auto& sub : subdirs) FixShortcutsIn(sub, depth - 1, renameFiles, oldExe, newExe, budget, changed);
}

void FixShortcuts(const std::wstring& oldExe, const std::wstring& newExe) {
    HRESULT init = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED | COINIT_DISABLE_OLE1DDE);
    int budget = 4000;
    int changed = 0;
    FixShortcutsIn(KnownFolder(FOLDERID_Desktop), 0, true, oldExe, newExe, budget, changed);
    FixShortcutsIn(KnownFolder(FOLDERID_PublicDesktop), 0, true, oldExe, newExe, budget, changed);
    FixShortcutsIn(KnownFolder(FOLDERID_Programs), 3, true, oldExe, newExe, budget, changed);
    FixShortcutsIn(KnownFolder(FOLDERID_CommonPrograms), 3, true, oldExe, newExe, budget, changed);
    // Taskbar and Start pins live under Quick Launch\User Pinned.
    std::wstring roaming = KnownFolder(FOLDERID_RoamingAppData);
    if (!roaming.empty())
        FixShortcutsIn(JoinPath(roaming, L"Microsoft\\Internet Explorer\\Quick Launch"), 3, false, oldExe, newExe,
                       budget, changed);
    if (changed > 0) SHChangeNotify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST, NULL, NULL);
    if (SUCCEEDED(init)) CoUninitialize();
}

#elif !defined(__APPLE__)

std::string HomeDir() {
    const char* home = getenv("HOME");
    return home ? home : "";
}

// XDG_DESKTOP_DIR from user-dirs.dirs (a Turkish desktop is ~/Masaüstü).
std::string DesktopDir() {
    std::string home = HomeDir();
    if (home.empty()) return "";
    const char* xdg = getenv("XDG_CONFIG_HOME");
    std::string cfg = (xdg && *xdg == '/') ? std::string(xdg) : home + "/.config";
    std::string text;
    if (ReadFileBytes(Utf8ToWide(cfg + "/user-dirs.dirs"), text, 1u << 16)) {
        size_t at = text.find("XDG_DESKTOP_DIR=\"");
        if (at != std::string::npos) {
            at += 17;
            size_t end = text.find('"', at);
            if (end != std::string::npos) {
                std::string v = text.substr(at, end - at);
                if (v.rfind("$HOME", 0) == 0) v = home + v.substr(5);
                if (!v.empty() && v[0] == '/') return v;
            }
        }
    }
    return home + "/Desktop";
}

void ReplaceAll(std::string& s, const std::string& from, const std::string& to) {
    if (from.empty()) return;
    for (size_t at = s.find(from); at != std::string::npos; at = s.find(from, at + to.size()))
        s.replace(at, from.size(), to);
}

void FixDesktopEntriesIn(const std::string& dir, const std::string& oldPath, const std::string& newPath) {
    DIR* h = opendir(dir.c_str());
    if (!h) return;
    int budget = 2000;
    while (struct dirent* e = readdir(h)) {
        std::string name = e->d_name;
        if (--budget <= 0) break;
        if (name.size() < 9 || name.compare(name.size() - 8, 8, ".desktop") != 0) continue;
        std::wstring full = Utf8ToWide(dir + "/" + name);
        std::string text;
        if (!ReadFileBytes(full, text, 1u << 18) || text.find(oldPath) == std::string::npos) continue;
        ReplaceAll(text, oldPath, newPath);
        // Name=HPMMO... lines (the menu label) become the game's name.
        size_t at = 0;
        while ((at = text.find("\nName=", at)) != std::string::npos) {
            size_t end = text.find('\n', at + 1);
            std::string line = text.substr(at + 6, end == std::string::npos ? std::string::npos : end - at - 6);
            if (line.find("HPMMO") != std::string::npos)
                text.replace(at + 6, line.size(), "Thousand Realms");
            at += 6;
        }
        // Rewritten in place: keeps the file's mode (a trusted, executable
        // desktop launcher stays one).
        FILE* f = OpenFileW(full, L"wb");
        bool ok = f && fwrite(text.data(), 1, text.size(), f) == text.size();
        if (f) fclose(f);
        LogMsg(std::string("[Launcher] desktop entry ") + (ok ? "updated: " : "could not be updated: ") +
               WideToUtf8(full));
    }
    closedir(h);
}

void FixShortcuts(const std::wstring& oldExe, const std::wstring& newExe) {
    std::string from = WideToUtf8(oldExe), to = WideToUtf8(newExe);
    std::wstring data = UserDataRoot();
    if (!data.empty()) FixDesktopEntriesIn(WideToUtf8(JoinPath(data, L"applications")), from, to);
    std::string desktop = DesktopDir();
    if (!desktop.empty()) FixDesktopEntriesIn(desktop, from, to);
}

#endif

}  // namespace

void MigrateLegacyLauncherFile() {
    std::wstring exe = GetExePath();
    if (exe.empty()) return;
#ifdef __APPLE__
    // ".../HPMMO Launcher.app/Contents/MacOS/HPMMO_Launcher": the bundle is
    // what Finder and the Dock show, so the bundle folder is renamed (the Dock
    // follows a rename on the same volume by itself).
    size_t at = exe.find(L".app/Contents/MacOS/");
    if (at == std::wstring::npos) return;
    std::wstring bundle = exe.substr(0, at + 4);
    std::wstring dir, name;
    SplitPath(bundle, dir, name);
    std::wstring renamed = RenamedFileName(name, L"HPMMO Launcher", L"Thousand Realms Launcher");
    if (renamed.empty()) return;
    std::wstring target = JoinPath(dir, renamed);
    if (DirExists(target) || FileExists(target)) {
        LogMsg("[Launcher] " + WideToUtf8(target) + " already exists; keeping " + WideToUtf8(name));
        return;
    }
    // A quarantined app runs from a read-only translocation mount: the rename
    // fails there and is tried again once the player moves the app.
    if (!MoveNoReplace(bundle, target)) {
        LogMsg("[Launcher] cannot rename " + WideToUtf8(bundle) + " (" + std::to_string(LastErrorCode()) + ")");
        return;
    }
    SetExePathOverride(target + exe.substr(at + 4));
    LogMsg("[Launcher] renamed " + WideToUtf8(bundle) + " -> " + WideToUtf8(target));
#else
    std::wstring dir, name;
    SplitPath(exe, dir, name);
    std::wstring renamed = RenamedFileName(name, L"HPMMO_Launcher", L"ThousandRealms_Launcher");
    if (renamed.empty()) return;
    std::wstring target = JoinPath(dir, renamed);
    if (FileExists(target) || DirExists(target)) {
        LogMsg("[Launcher] " + WideToUtf8(target) + " already exists; keeping " + WideToUtf8(name));
        return;
    }
    // Windows renames a running executable (it only refuses to delete or
    // overwrite it); POSIX renames anything.
    if (!MoveNoReplace(exe, target)) {
        LogMsg("[Launcher] cannot rename " + WideToUtf8(exe) + " (" + std::to_string(LastErrorCode()) + ")");
        return;
    }
    SetExePathOverride(target);
#ifndef _WIN32
    // GetExePath reads $APPIMAGE; children (the update helper) inherit it.
    const char* appimage = getenv("APPIMAGE");
    if (appimage && WideToUtf8(exe) == appimage) setenv("APPIMAGE", WideToUtf8(target).c_str(), 1);
#endif
    LogMsg("[Launcher] renamed " + WideToUtf8(exe) + " -> " + WideToUtf8(target));
    FixShortcuts(exe, target);
#endif
}

}  // namespace hpmmo
