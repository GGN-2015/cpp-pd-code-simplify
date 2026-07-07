#include "pdcode_simplify/pdcode_simplify.hpp"

#include <fstream>
#include <cctype>
#include <iostream>
#include <iterator>
#include <set>
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
        << "Use --known-crossingless-components N when the input already has\n"
        << "components that cannot be represented by a PD code.\n"
        << "Use --remove-crossings LIST to report component counts after a\n"
        << "zero-based crossing-removal simulation.\n"
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

std::vector<int> parse_integer_list(const std::string& text) {
    std::vector<int> values;
    for (std::size_t i = 0; i < text.size();) {
        if (text[i] == '-' || std::isdigit(static_cast<unsigned char>(text[i]))) {
            const std::size_t start = i;
            if (text[i] == '-') {
                ++i;
            }
            while (i < text.size() && std::isdigit(static_cast<unsigned char>(text[i]))) {
                ++i;
            }
            values.push_back(std::stoi(text.substr(start, i - start)));
        } else {
            ++i;
        }
    }
    return values;
}

void print_component_counts(const pdcode_simplify::ComponentAnalysis& analysis, const char* prefix) {
    std::cout << prefix << "_components_with_crossings: "
              << analysis.components_with_crossings() << '\n';
    std::cout << prefix << "_crossingless_components: "
              << analysis.crossingless_components << '\n';
    std::cout << prefix << "_total_components: "
              << analysis.total_components() << '\n';
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

void print_text_result(
    const pdcode_simplify::SimplificationResult& result,
    const pdcode_simplify::ComponentAnalysis& input_components,
    const pdcode_simplify::ComponentAnalysis* after_removal_components) {
    std::cout << "simplification_found: " << (result.found ? "yes" : "no") << '\n';
    print_component_counts(input_components, "input");
    if (after_removal_components != nullptr) {
        print_component_counts(*after_removal_components, "after_removal");
    }
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

void print_json_component_counts(const pdcode_simplify::ComponentAnalysis& analysis) {
    std::cout << "\"components_with_crossings\":" << analysis.components_with_crossings()
              << ",\"crossingless_components\":" << analysis.crossingless_components
              << ",\"total_components\":" << analysis.total_components();
}

void print_json_result(
    const pdcode_simplify::SimplificationResult& result,
    const pdcode_simplify::ComponentAnalysis& input_components,
    const pdcode_simplify::ComponentAnalysis* after_removal_components) {
    std::cout << "{\n";
    std::cout << "  \"simplification_found\": " << (result.found ? "true" : "false") << ",\n";
    std::cout << "  \"input_components\": {";
    print_json_component_counts(input_components);
    std::cout << "},\n";
    if (after_removal_components != nullptr) {
        std::cout << "  \"after_removal_components\": {";
        print_json_component_counts(*after_removal_components);
        std::cout << "},\n";
    }
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
        std::size_t known_crossingless_components = 0;
        std::vector<int> removed_crossings;
        bool has_removal_simulation = false;
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
            } else if (arg == "--known-crossingless-components") {
                if (i + 1 >= argc) {
                    throw std::invalid_argument("--known-crossingless-components requires a value");
                }
                const int value = std::stoi(argv[++i]);
                if (value < 0) {
                    throw std::invalid_argument("--known-crossingless-components cannot be negative");
                }
                known_crossingless_components = static_cast<std::size_t>(value);
            } else if (arg == "--remove-crossings") {
                if (i + 1 >= argc) {
                    throw std::invalid_argument("--remove-crossings requires a list");
                }
                removed_crossings = parse_integer_list(argv[++i]);
                has_removal_simulation = true;
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
        const auto input_components = pdcode_simplify::analyze_components(
            code, known_crossingless_components);
        pdcode_simplify::ComponentAnalysis after_removal_components;
        if (has_removal_simulation) {
            after_removal_components = pdcode_simplify::analyze_components_after_removing_crossings(
                code, removed_crossings, known_crossingless_components);
        }
        const auto result = pdcode_simplify::find_simplification(code, options);
        if (json) {
            print_json_result(
                result,
                input_components,
                has_removal_simulation ? &after_removal_components : nullptr);
        } else {
            print_text_result(
                result,
                input_components,
                has_removal_simulation ? &after_removal_components : nullptr);
        }
        return result.found ? 0 : 1;
    } catch (const std::exception& error) {
        std::cerr << "error: " << error.what() << '\n';
        return 2;
    }
}
