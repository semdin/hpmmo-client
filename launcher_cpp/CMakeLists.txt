cmake_minimum_required(VERSION 3.16)
project(HPMMO_Launcher LANGUAGES C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

set(VENDOR_ED25519 ${CMAKE_CURRENT_SOURCE_DIR}/vendor/ed25519)

# The launcher's own version (self-update compares it with the manifest's
# launcher_version). CI passes -DHPMMO_LAUNCHER_VERSION=3.0.<unix time of the
# last commit touching launcher_cpp/>, so only launcher changes trigger it.
set(HPMMO_LAUNCHER_VERSION "3.0.0" CACHE STRING "Launcher version stamped into the build")
add_compile_definitions(HPMMO_LAUNCHER_VERSION="${HPMMO_LAUNCHER_VERSION}")
if(WIN32)
    # Vista+/Win10 APIs (QueryFullProcessImageNameW, SHCreateMemStream, DWM, DPI):
    # GCC mingw-w64 defaults to an older _WIN32_WINNT and hides them.
    add_compile_definitions(_WIN32_WINNT=0x0A00 WINVER=0x0A00 _WIN32_IE=0x0A00)
endif()

# Shared launcher/updater core. Ed25519 (vendored, public-domain-style zlib
# license - see vendor/PROVENANCE.md) is the only third-party code; libcurl is
# the HTTP transport on Linux/macOS (WinHTTP on Windows).
if(WIN32)
    set(HPMMO_PLATFORM_SOURCES src/common_win.cpp src/http_winhttp.cpp)
else()
    set(HPMMO_PLATFORM_SOURCES src/common_posix.cpp src/http_curl.cpp)
endif()
add_library(hpmmo_core STATIC
    ${HPMMO_PLATFORM_SOURCES}
    src/common.cpp
    src/json.cpp
    src/sha256.cpp
    src/inflate.cpp
    src/zip.cpp
    src/updater.cpp
    src/updater_cli.cpp
    src/delta.cpp
    ${VENDOR_ED25519}/fe.c
    ${VENDOR_ED25519}/ge.c
    ${VENDOR_ED25519}/sc.c
    ${VENDOR_ED25519}/sha512.c
    ${VENDOR_ED25519}/verify.c
)
target_include_directories(hpmmo_core PUBLIC src ${VENDOR_ED25519})
if(WIN32)
    target_link_libraries(hpmmo_core PUBLIC
        bcrypt
        crypt32
        winhttp
        ws2_32
    )
else()
    find_package(CURL REQUIRED)
    find_package(Threads REQUIRED)
    target_link_libraries(hpmmo_core PUBLIC CURL::libcurl Threads::Threads)
endif()
target_compile_options(hpmmo_core PRIVATE -O2)

if(WIN32)
    # GUI launcher: update/install/play only (signing in happens in the game).
    # app.rc embeds the exe/taskbar/titlebar icon + version info.
    add_executable(HPMMO_Launcher WIN32
        src/main.cpp
        app.rc
    )
    # windres finds the embedded art/fonts (app.rc) through the include path.
    target_include_directories(HPMMO_Launcher PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
    target_link_libraries(HPMMO_Launcher PRIVATE
        hpmmo_core
        ws2_32
        winhttp
        gdiplus
        gdi32
        user32
        kernel32
        comctl32
        shlwapi
        ole32
        dwmapi
    )
endif()

# Headless CLI used by the release tests and by operators.
add_executable(HPMMO_UpdaterCLI
    src/updater_main.cpp
)
target_link_libraries(HPMMO_UpdaterCLI PRIVATE hpmmo_core)

if(WIN32)
    set(HPMMO_EXE_TARGETS HPMMO_Launcher HPMMO_UpdaterCLI)
else()
    set(HPMMO_EXE_TARGETS HPMMO_UpdaterCLI)
endif()
foreach(tgt ${HPMMO_EXE_TARGETS})
    target_compile_options(${tgt} PRIVATE -O2)
    if(WIN32)
        target_link_options(${tgt} PRIVATE -static -static-libgcc -static-libstdc++)
    endif()
endforeach()

if(WIN32)
add_custom_command(TARGET HPMMO_Launcher POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
    $<TARGET_FILE:HPMMO_Launcher>
    ${CMAKE_SOURCE_DIR}/../HPMMO_Launcher.exe
)
add_custom_command(TARGET HPMMO_UpdaterCLI POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
    $<TARGET_FILE:HPMMO_UpdaterCLI>
    ${CMAKE_SOURCE_DIR}/../HPMMO_UpdaterCLI.exe
)
endif()
