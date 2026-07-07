#include "pdcode_simplify/pdcode_simplify.hpp"

#include <fstream>
#include <iostream>
#include <iterator>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

void print_help(const char* program) {
    std::cout
        << "Usage: " << program << " [--max-paths N] [--json] [--input FILE] [PD_CODE]\n"
        << "\n"
        << "Find a mid-simplification witness in a knot or link PD code.\n"
        << "If PD_CODE and --input are omitted, input is read from standard input.\n";
}

std::string read_file(const std::string& path) {
    std::ifstream input(path);
    if (!input) {
        throw std::runtime_error("Could not open input file: " + path);
    }
    std::ostringstream buffer;
    buffer << input.rdbuf();
    return buffer.str();
}

std::string read_stdin() {
    return std::string(std::istreambuf_iterator<char>(std::cin), std::istreambuf_iterator<char>());
}

void print_vector_endpoints(const std::vector<pdcode_simplify::Endpoint>& endpoints) {
    std::cout << '[';
    for (std::size_t i = 0; i < endpoints.size(); ++i) {
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << pdcode_simplify::format_endpoint(endpoints[i]);
    }
    std::cout << ']';
}

void print_vector_ints(const std::vector<int>& values) {
    std::cout << '[';
    for (std::size_t i = 0; i < values.size(); ++i) {
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << values[i];
    }
    std::cout << ']';
}

void print_text_result(const pdcode_simplify::SimplificationResult& result) {
    std::cout << "simplification_found: " << (result.found ? "yes" : "no") << '\n';
    std::cout << "tested_red_paths: " << result.tested_red_paths << '\n';
    std::cout << "tested_green_paths: " << result.tested_green_paths << '\n';
    if (!result.found) {
        return;
    }

    std::cout << "direction: " << pdcode_simplify::format_direction(result.direction) << '\n';
    std::cout << "red_path: ";
    print_vector_endpoints(result.red_path);
    std::cout << '\n';
    std::cout << "green_path: ";
    print_vector_ints(result.green_path);
    std::cout << '\n';
    std::cout << "green_crossings: [";
    for (std::size_t i = 0; i < result.green_crossings.size(); ++i) {
        const auto& crossing = result.green_crossings[i];
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << '(' << crossing.from_face << ", " << crossing.to_face
                  << ", " << crossing.strand_level << ')';
    }
    std::cout << "]\n";
}

void print_json_result(const pdcode_simplify::SimplificationResult& result) {
    std::cout << "{\n";
    std::cout << "  \"simplification_found\": " << (result.found ? "true" : "false") << ",\n";
    std::cout << "  \"tested_red_paths\": " << result.tested_red_paths << ",\n";
    std::cout << "  \"tested_green_paths\": " << result.tested_green_paths;
    if (!result.found) {
        std::cout << "\n}\n";
        return;
    }
    std::cout << ",\n";
    std::cout << "  \"direction\": \"" << pdcode_simplify::format_direction(result.direction) << "\",\n";
    std::cout << "  \"red_path\": [";
    for (std::size_t i = 0; i < result.red_path.size(); ++i) {
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << "{\"crossing\":" << result.red_path[i].crossing
                  << ",\"strand\":" << result.red_path[i].strand << '}';
    }
    std::cout << "],\n";
    std::cout << "  \"green_path\": [";
    for (std::size_t i = 0; i < result.green_path.size(); ++i) {
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << result.green_path[i];
    }
    std::cout << "],\n";
    std::cout << "  \"green_crossings\": [";
    for (std::size_t i = 0; i < result.green_crossings.size(); ++i) {
        const auto& crossing = result.green_crossings[i];
        if (i != 0) {
            std::cout << ", ";
        }
        std::cout << "{\"from_face\":" << crossing.from_face
                  << ",\"to_face\":" << crossing.to_face
                  << ",\"strand_level\":\"" << crossing.strand_level << "\"}";
    }
    std::cout << "]\n";
    std::cout << "}\n";
}

}  // namespace

int main(int argc, char** argv) {
    try {
        pdcode_simplify::SimplifierOptions options;
        bool json = false;
        std::string input_text;
        std::vector<std::string> positional;

        for (int i = 1; i < argc; ++i) {
            const std::string arg = argv[i];
            if (arg == "--help" || arg == "-h") {
                print_help(argv[0]);
                return 0;
            }
            if (arg == "--json") {
                json = true;
            } else if (arg == "--max-paths") {
                if (i + 1 >= argc) {
                    throw std::invalid_argument("--max-paths requires a value");
                }
                options.max_paths = std::stoi(argv[++i]);
            } else if (arg == "--input" || arg == "-i") {
                if (i + 1 >= argc) {
                    throw std::invalid_argument("--input requires a file path");
                }
                input_text = read_file(argv[++i]);
            } else {
                positional.push_back(arg);
            }
        }

        if (input_text.empty()) {
            if (!positional.empty()) {
                std::ostringstream joined;
                for (std::size_t i = 0; i < positional.size(); ++i) {
                    if (i != 0) {
                        joined << ' ';
                    }
                    joined << positional[i];
                }
                input_text = joined.str();
            } else {
                input_text = read_stdin();
            }
        }

        const auto code = pdcode_simplify::parse_pd_code(input_text);
        const auto result = pdcode_simplify::find_simplification(code, options);
        if (json) {
            print_json_result(result);
        } else {
            print_text_result(result);
        }
        return result.found ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 2;
    }
}
