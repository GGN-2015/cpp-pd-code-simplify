#include "pdcode_simplify/pdcode_simplify.hpp"

#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <string>

namespace {

void require(bool condition, const std::string& message) {
    if (!condition) {
        throw std::runtime_error(message);
    }
}

void test_parser() {
    const auto code = pdcode_simplify::parse_pd_code("[(0, 1, 2, 3), (2, 3, 0, 1)]");
    require(code.size() == 2, "parser should create two crossings");
    require(code[0][0] == 0 && code[1][3] == 1, "parser should preserve labels");
}

void test_empty_code() {
    const auto result = pdcode_simplify::find_simplification({});
    require(!result.found, "empty PD code should not have a simplification witness");
}

void test_invalid_code() {
    bool threw = false;
    try {
        const auto code = pdcode_simplify::parse_pd_code("[(0, 1, 2, 3)]");
        (void)pdcode_simplify::find_simplification(code);
    } catch (const std::invalid_argument&) {
        threw = true;
    }
    require(threw, "labels that do not appear twice should be rejected");
}

void test_reference_sample() {
    const char* sample = R"PD(
[(15, 7, 16, 6),
 (7, 15, 8, 14),
 (18, 61, 19, 0),
 (20, 12, 21, 11),
 (12, 24, 13, 23),
 (13, 26, 14, 27),
 (29, 22, 30, 23),
 (21, 30, 22, 31),
 (28, 33, 29, 34),
 (5, 36, 6, 37),
 (8, 36, 9, 35),
 (34, 27, 35, 28),
 (1, 41, 2, 40),
 (19, 43, 20, 42),
 (43, 25, 44, 24),
 (25, 45, 26, 44),
 (16, 45, 17, 46),
 (37, 46, 38, 47),
 (48, 39, 49, 40),
 (0, 50, 1, 49),
 (10, 51, 11, 52),
 (31, 53, 32, 52),
 (41, 50, 42, 51),
 (55, 3, 56, 2),
 (54, 9, 55, 10),
 (53, 33, 54, 32),
 (3, 57, 4, 56),
 (57, 5, 58, 4),
 (60, 17, 61, 18),
 (59, 38, 60, 39),
 (58, 47, 59, 48)]
)PD";
    const auto code = pdcode_simplify::parse_pd_code(sample);
    pdcode_simplify::SimplifierOptions options;
    options.max_paths = 100;
    const auto result = pdcode_simplify::find_simplification(code, options);
    require(result.found, "reference PD code should have a simplification witness");
    require(!result.red_path.empty(), "witness should include a red path");
    require(!result.green_path.empty(), "witness should include a green path");
}

}  // namespace

int main() {
    try {
        test_parser();
        test_empty_code();
        test_invalid_code();
        test_reference_sample();
        std::cout << "All tests passed\n";
        return EXIT_SUCCESS;
    } catch (const std::exception& error) {
        std::cerr << "Test failed: " << error.what() << '\n';
        return EXIT_FAILURE;
    }
}
