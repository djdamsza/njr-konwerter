cmake_minimum_required(VERSION 3.16)
project(njr_engine_export CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)

set(BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
# macOS/Linux: bundled SQLite z libdjinterop. Windows CI: systemowe pakiety vcpkg (patrz workflow).
if(WIN32)
  set(SYSTEM_SQLITE ON CACHE BOOL "" FORCE)
  set(SYSTEM_DATE_H ON CACHE BOOL "" FORCE)
  set(SYSTEM_SQLITE_MODERN_CPP ON CACHE BOOL "" FORCE)
else()
  set(SYSTEM_SQLITE OFF CACHE BOOL "" FORCE)
endif()

FetchContent_Declare(
  libdjinterop
  GIT_REPOSITORY https://github.com/xsco/libdjinterop.git
  GIT_TAG 6cf7429fb605a6cd528c21e8a2bb2e050d40da2a
)
FetchContent_Declare(
  json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG v3.11.3
)

FetchContent_MakeAvailable(libdjinterop json)

add_executable(njr_engine_export njr_engine_export.cpp)
target_link_libraries(njr_engine_export PRIVATE DjInterop nlohmann_json::nlohmann_json)
set_target_properties(njr_engine_export PROPERTIES OUTPUT_NAME "njr-engine-export")
