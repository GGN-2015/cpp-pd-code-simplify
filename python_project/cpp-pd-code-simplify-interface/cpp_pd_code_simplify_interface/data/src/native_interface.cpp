#include "pdcode_simplify/pdcode_simplify.hpp"

#include <cstdlib>
#include <cstring>
#include <exception>
#include <sstream>
#include <string>
#include <vector>

namespace {

bool denotes_crossingless_unknot(const std::string& text) {
    std::string compact;
    for (char c : text) {
        if (c != ' ' && c != '\t' && c != '\r' && c != '\n') {
            compact.push_back(c);
        }
    }
    return compact == "PD[]" || compact == "[]";
}

std::string json_escape(const std::string& text) {
    std::ostringstream escaped;
    for (char c : text) {
        switch (c) {
            case '\\':
                escaped << "\\\\";
                break;
            case '"':
                escaped << "\\\"";
                break;
            case '\n':
                escaped << "\\n";
                break;
            case '\r':
                escaped << "\\r";
                break;
            case '\t':
                escaped << "\\t";
                break;
            default:
                escaped << c;
                break;
        }
    }
    return escaped.str();
}

void append_component_counts(
    std::ostringstream& out,
    const pdcode_simplify::ComponentAnalysis& analysis) {
    out << "\"components_with_crossings\":" << analysis.components_with_crossings()
        << ",\"crossingless_components\":" << analysis.crossingless_components
        << ",\"total_components\":" << analysis.total_components();
}

std::string result_to_json(
    const pdcode_simplify::SimplificationResult& result,
    const pdcode_simplify::ComponentAnalysis& input_components,
    const pdcode_simplify::ComponentAnalysis* after_removal_components,
    const pdcode_simplify::PDSimplificationResult& pd_simplification,
    const pdcode_simplify::ComponentAnalysis& search_components) {
    std::ostringstream out;
    out << "{";
    out << "\"simplification_found\":" << (result.found ? "true" : "false") << ",";
    out << "\"input_components\":{";
    append_component_counts(out, input_components);
    out << "},";
    if (after_removal_components != nullptr) {
        out << "\"after_removal_components\":{";
        append_component_counts(out, *after_removal_components);
        out << "},";
    }
    out << "\"pd_simplification\":{"
        << "\"enabled\":true,"
        << "\"reidemeister_i_moves\":" << pd_simplification.reidemeister_i_moves << ","
        << "\"nugatory_crossing_moves\":" << pd_simplification.nugatory_crossing_moves << ","
        << "\"output_crossings\":" << pd_simplification.code.size()
        << "},";
    out << "\"search_components\":{";
    append_component_counts(out, search_components);
    out << "},";
    out << "\"tested_red_paths\":" << result.tested_red_paths << ",";
    out << "\"tested_green_paths\":" << result.tested_green_paths;
    if (result.found) {
        out << ",";
        out << "\"direction\":\"" << pdcode_simplify::format_direction(result.direction) << "\",";
        out << "\"red_path\":[";
        for (std::size_t i = 0; i < result.red_path.size(); ++i) {
            if (i != 0) {
                out << ",";
            }
            out << "{\"crossing\":" << result.red_path[i].crossing
                << ",\"strand\":" << result.red_path[i].strand << "}";
        }
        out << "],";
        out << "\"green_path\":[";
        for (std::size_t i = 0; i < result.green_path.size(); ++i) {
            if (i != 0) {
                out << ",";
            }
            out << result.green_path[i];
        }
        out << "],";
        out << "\"green_crossings\":[";
        for (std::size_t i = 0; i < result.green_crossings.size(); ++i) {
            if (i != 0) {
                out << ",";
            }
            const auto& crossing = result.green_crossings[i];
            out << "{\"from_face\":" << crossing.from_face
                << ",\"to_face\":" << crossing.to_face
                << ",\"strand_level\":\"" << json_escape(crossing.strand_level) << "\"}";
        }
        out << "]";
    }
    out << "}";
    return out.str();
}

char* copy_string(const std::string& text) {
    char* result = static_cast<char*>(std::malloc(text.size() + 1));
    if (result == nullptr) {
        return nullptr;
    }
    std::memcpy(result, text.c_str(), text.size() + 1);
    return result;
}

}  // namespace

extern "C" {

#if defined(_WIN32)
__declspec(dllexport)
#endif
char* pdcode_simplify_run_json(
    const char* pd_text,
    int max_paths,
    unsigned long long known_crossingless_components,
    const int* removed_crossings,
    unsigned long long removed_crossing_count) {
    try {
        if (pd_text == nullptr) {
            return copy_string("{\"error\":\"pd_text must not be null\"}");
        }

        const std::string text(pd_text);
        pdcode_simplify::SimplifierOptions options;
        options.max_paths = max_paths;

        const pdcode_simplify::PDCode code = pdcode_simplify::parse_pd_code(text);
        std::size_t crossingless = static_cast<std::size_t>(known_crossingless_components);
        if (denotes_crossingless_unknot(text)) {
            ++crossingless;
        }

        const auto input_components = pdcode_simplify::analyze_components(code, crossingless);
        pdcode_simplify::ComponentAnalysis after_removal_components;
        const bool has_removal = removed_crossings != nullptr && removed_crossing_count > 0;
        if (has_removal) {
            std::vector<int> removed(
                removed_crossings,
                removed_crossings + static_cast<std::size_t>(removed_crossing_count));
            after_removal_components =
                pdcode_simplify::analyze_components_after_removing_crossings(
                    code, removed, crossingless);
        }

        const auto pd_simplification = pdcode_simplify::simplify_pd_code(code, crossingless);
        const auto search_components = pdcode_simplify::analyze_components(
            pd_simplification.code,
            pd_simplification.crossingless_components);
        const auto result = pdcode_simplify::find_simplification(pd_simplification.code, options);
        return copy_string(result_to_json(
            result,
            input_components,
            has_removal ? &after_removal_components : nullptr,
            pd_simplification,
            search_components));
    } catch (const std::exception& error) {
        return copy_string(std::string("{\"error\":\"") + json_escape(error.what()) + "\"}");
    } catch (...) {
        return copy_string("{\"error\":\"unknown C++ exception\"}");
    }
}

#if defined(_WIN32)
__declspec(dllexport)
#endif
void pdcode_simplify_free_string(char* text) {
    std::free(text);
}

}  // extern "C"
