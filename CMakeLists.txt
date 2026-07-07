cmake_minimum_required(VERSION 3.16)

project(pdcode_simplify VERSION 0.1.0 LANGUAGES CXX)

option(PDCODE_SIMPLIFY_BUILD_TESTS "Build tests" ON)

add_library(pdcode_simplify
    src/pdcode_simplify.cpp
)

target_include_directories(pdcode_simplify
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

target_compile_features(pdcode_simplify PUBLIC cxx_std_14)

if(MSVC)
    target_compile_options(pdcode_simplify PRIVATE /W4 /permissive-)
else()
    target_compile_options(pdcode_simplify PRIVATE -Wall -Wextra -Wpedantic)
endif()

add_executable(pd_simplify src/main.cpp)
target_link_libraries(pd_simplify PRIVATE pdcode_simplify)

if(PDCODE_SIMPLIFY_BUILD_TESTS)
    enable_testing()
    add_executable(pdcode_simplify_tests tests/test_pdcode_simplify.cpp)
    target_link_libraries(pdcode_simplify_tests PRIVATE pdcode_simplify)
    add_test(NAME pdcode_simplify_tests COMMAND pdcode_simplify_tests)
endif()
