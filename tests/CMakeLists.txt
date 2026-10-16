add_executable(test_api test_api.c)
target_link_libraries(test_api PRIVATE rsynth)

# The DLL has to sit beside the test on Windows.
if(WIN32)
  add_custom_command(TARGET test_api POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:rsynth> $<TARGET_FILE_DIR:test_api>)
endif()

add_test(NAME api COMMAND test_api "${CMAKE_CURRENT_SOURCE_DIR}/golden.txt")

# The same checks against the static library the GUI links: the golden
# hashes must agree, so the GUI says exactly what the add-on says.
add_executable(test_api_static test_api.c)
target_link_libraries(test_api_static PRIVATE rsynth_static)
add_test(NAME api_static
         COMMAND test_api_static "${CMAKE_CURRENT_SOURCE_DIR}/golden.txt")
