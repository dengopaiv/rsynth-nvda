add_executable(test_api test_api.c)
target_link_libraries(test_api PRIVATE rsynth)

# The DLL has to sit beside the test on Windows.
if(WIN32)
  add_custom_command(TARGET test_api POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E copy_if_different
            $<TARGET_FILE:rsynth> $<TARGET_FILE_DIR:test_api>)
endif()

add_test(NAME api COMMAND test_api "${CMAKE_CURRENT_SOURCE_DIR}/golden.txt")
