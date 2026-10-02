cmake_minimum_required(VERSION 3.16)
project(HPMMO_Launcher LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_executable(HPMMO_Launcher WIN32
    src/main.cpp
)

target_link_libraries(HPMMO_Launcher PRIVATE
    ws2_32
    winhttp
    gdiplus
    gdi32
    user32
    kernel32
    comctl32
    shlwapi
    ole32
)

target_compile_options(HPMMO_Launcher PRIVATE -O2)
target_link_options(HPMMO_Launcher PRIVATE -static -static-libgcc -static-libstdc++)

add_custom_command(TARGET HPMMO_Launcher POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
    $<TARGET_FILE:HPMMO_Launcher>
    ${CMAKE_SOURCE_DIR}/../HPMMO_Launcher.exe
)
