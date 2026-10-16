# rsynth-nvda: Nick Ing-Simmons' RSynth as a native library, a command-line
# speaker and an NVDA add-on. See README.md and docs/.
#
# 64-bit only (x64, ARM64). There is no 32-bit configuration and none should
# be added.

cmake_minimum_required(VERSION 3.20)
project(rsynth VERSION 3.0.0 LANGUAGES C)

set(CMAKE_C_STANDARD 17)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

if(CMAKE_SIZEOF_VOID_P EQUAL 4)
  message(FATAL_ERROR "rsynth-nvda builds 64-bit only. Configure with -A x64 "
                      "(Visual Studio) or a 64-bit toolchain.")
endif()

if(MSVC)
  # english.c and charset.c hold ISO-8859-1 byte literals ('é' and friends).
  # Read and emit them as code page 1252, which agrees with ISO-8859-1 on
  # every byte those files use, rather than whatever the machine's ANSI code
  # page happens to be.
  add_compile_options(/source-charset:.1252 /execution-charset:.1252)
  # The original sources use fopen, sprintf, strcpy and friends.
  add_compile_definitions(_CRT_SECURE_NO_WARNINGS)
  # Static CRT: an add-on DLL that needs a redistributable the user lacks
  # fails by NVDA silently not listing the synth.
  set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

# ---------------------------------------------------------------------------
# The original engine sources, exactly as listed for `say` in Makefile.am,
# minus the audio drivers, the command-line parser, the GDBM dictionary and
# the German front end, none of which a library needs.
set(RSYNTH_ENGINE_SOURCES
  opsynth.c
  elements.c
  holmes.c
  trie.c
  phtoelm.c
  darray.c
  say.c
  phones.c
  text.c
  english.c
  charset.c
)

# ---------------------------------------------------------------------------
# The dictionary: CMU Pronouncing Dictionary compiled into a C table by
# mkdicttab, a host tool carrying mkdictdb.c's conversion rules.
set(RSYNTH_CMUDICT "${CMAKE_CURRENT_SOURCE_DIR}/dict/cmudict/cmudict.dict"
    CACHE FILEPATH "CMU Pronouncing Dictionary source (cmudict.dict format)")

add_executable(mkdicttab tools/mkdicttab.c trie.c phones.c)
target_include_directories(mkdicttab PRIVATE port ${CMAKE_CURRENT_SOURCE_DIR})

set(RSYNTH_DICT_C "${CMAKE_CURRENT_BINARY_DIR}/cmudict_table.c")
add_custom_command(
  OUTPUT "${RSYNTH_DICT_C}"
  COMMAND mkdicttab "${RSYNTH_CMUDICT}" "${RSYNTH_DICT_C}"
  DEPENDS mkdicttab "${RSYNTH_CMUDICT}"
  COMMENT "Compiling the CMU dictionary into a C table"
  VERBATIM)

# ---------------------------------------------------------------------------
# The library.
add_library(rsynth SHARED
  ${RSYNTH_ENGINE_SOURCES}
  port/rsynth_api.c
  port/frontend.c
  port/dict_builtin.c
  "${RSYNTH_DICT_C}")
target_include_directories(rsynth
  PRIVATE port ${CMAKE_CURRENT_SOURCE_DIR}
  PUBLIC  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>)
target_compile_definitions(rsynth PRIVATE RSYNTH_BUILDING_DLL)
if(NOT MSVC)
  target_link_libraries(rsynth PRIVATE m)
  set_target_properties(rsynth PROPERTIES C_VISIBILITY_PRESET hidden)
endif()

# ---------------------------------------------------------------------------
# rsynth_say: text in, WAV out, over the public API only.
add_executable(rsynth_say cli/rsynth_say.c)
target_link_libraries(rsynth_say PRIVATE rsynth)

# ---------------------------------------------------------------------------
enable_testing()
add_subdirectory(tests)
