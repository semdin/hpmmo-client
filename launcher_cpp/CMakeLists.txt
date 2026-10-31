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
    src/launcher_app.cpp
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
    if(APPLE)
        target_link_libraries(hpmmo_core PUBLIC CURL::libcurl Threads::Threads)
    else()
        # Linux loads libcurl at run time (http_curl.cpp): headers only here.
        target_include_directories(hpmmo_core PRIVATE ${CURL_INCLUDE_DIRS})
        target_link_libraries(hpmmo_core PUBLIC Threads::Threads ${CMAKE_DL_LIBS})
    endif()
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

if(NOT WIN32)
    # GUI launcher for Linux/macOS: an SDL3 window showing frames from the
    # software painter (painter.cpp + vendored stb). SDL3 is built statically
    # from a pinned, hash-checked release so the binary only needs the
    # system's display libraries (X11/Wayland/Cocoa), loaded at run time.
    include(FetchContent)
    set(SDL_SHARED OFF CACHE BOOL "" FORCE)
    set(SDL_STATIC ON CACHE BOOL "" FORCE)
    set(SDL_TEST_LIBRARY OFF CACHE BOOL "" FORCE)
    set(SDL_TESTS OFF CACHE BOOL "" FORCE)
    set(SDL_EXAMPLES OFF CACHE BOOL "" FORCE)
    set(SDL_INSTALL OFF CACHE BOOL "" FORCE)
    foreach(sub AUDIO JOYSTICK HAPTIC HIDAPI CAMERA SENSOR POWER GPU)
        set(SDL_${sub} OFF CACHE BOOL "" FORCE)
    endforeach()
    FetchContent_Declare(SDL3
        URL https://github.com/libsdl-org/SDL/releases/download/release-3.4.16/SDL3-3.4.16.tar.gz
        URL_HASH SHA256=7322236cd12090c3eb40b9728be4d49c76f66ad17d04369584d4ecad5cf77c68)
    FetchContent_MakeAvailable(SDL3)

    include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/EmbedAssets.cmake)
    set(HPMMO_EMBEDDED ${CMAKE_CURRENT_BINARY_DIR}/embedded_assets.cpp)
    hpmmo_embed_assets(${HPMMO_EMBEDDED}
        Background ${CMAKE_CURRENT_SOURCE_DIR}/assets/launcher_bg.jpg
        FontTitle ${CMAKE_CURRENT_SOURCE_DIR}/assets/CinzelDecorative-Bold.ttf
        FontBody ${CMAKE_CURRENT_SOURCE_DIR}/assets/Marcellus-Regular.ttf
        IconPng ${CMAKE_CURRENT_SOURCE_DIR}/assets/hpmmo_256.png
        LogoPng ${CMAKE_CURRENT_SOURCE_DIR}/assets/thousand_realms_logo.png)

    add_executable(HPMMO_Launcher
        src/main_sdl.cpp
        src/painter.cpp
        ${HPMMO_EMBEDDED}
    )
    target_include_directories(HPMMO_Launcher PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/vendor/stb)
    target_link_libraries(HPMMO_Launcher PRIVATE hpmmo_core SDL3::SDL3-static)
endif()

# Headless CLI used by the release tests and by operators.
add_executable(HPMMO_UpdaterCLI
    src/updater_main.cpp
)
target_link_libraries(HPMMO_UpdaterCLI PRIVATE hpmmo_core)

if(WIN32)
    set(HPMMO_EXE_TARGETS HPMMO_Launcher HPMMO_UpdaterCLI)
else()
    set(HPMMO_EXE_TARGETS HPMMO_Launcher HPMMO_UpdaterCLI)
endif()
foreach(tgt ${HPMMO_EXE_TARGETS})
    target_compile_options(${tgt} PRIVATE -O2)
    if(WIN32)
        target_link_options(${tgt} PRIVATE -static -static-libgcc -static-libstdc++)
    elseif(NOT APPLE)
        # Only glibc stays dynamic: the binaries run on older distributions.
        target_link_options(${tgt} PRIVATE -static-libgcc -static-libstdc++)
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
