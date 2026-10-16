# rsynth_gui: the desktop GUI (docs/07-gui.md). Windows only: it is plain
# Win32 controls, which is what makes it readable by NVDA without any
# accessibility layer of its own. The engine is linked in statically, so
# the program is one 64-bit exe with nothing beside it.

enable_language(CXX)

add_executable(rsynth_gui WIN32 rsynth_gui.cpp rsynth_gui.manifest)
set_target_properties(rsynth_gui PROPERTIES
  CXX_STANDARD 17
  CXX_STANDARD_REQUIRED ON
  CXX_EXTENSIONS OFF)
target_compile_definitions(rsynth_gui PRIVATE UNICODE _UNICODE)
target_link_libraries(rsynth_gui PRIVATE
  rsynth_static comctl32 comdlg32 winmm)
if(MSVC)
  target_compile_options(rsynth_gui PRIVATE /W4 /EHsc)
endif()
