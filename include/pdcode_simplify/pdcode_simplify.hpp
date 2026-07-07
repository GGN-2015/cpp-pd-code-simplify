#pragma once

#include <array>
#include <cstddef>
#include <iosfwd>
#include <string>
#include <vector>

namespace pdcode_simplify {

struct Endpoint {
    int crossing = -1;
    int strand = -1;

    friend bool operator==(const Endpoint& lhs, const Endpoint& rhs) {
        return lhs.crossing == rhs.crossing && lhs.strand == rhs.strand;
    }

    friend bool operator!=(const Endpoint& lhs, const Endpoint& rhs) {
        return !(lhs == rhs);
    }
};

using Crossing = std::array<int, 4>;
using PDCode = std::vector<Crossing>;

enum class Direction {
    Left,
    Right
};

struct GreenCrossing {
    int from_face = -1;
    int to_face = -1;
    std::string strand_level;
};

struct SimplifierOptions {
    int max_paths = 100;
};

struct SimplificationResult {
    bool found = false;
    Direction direction = Direction::Left;
    std::vector<Endpoint> red_path;
    std::vector<int> green_path;
    std::vector<GreenCrossing> green_crossings;
    std::size_t tested_red_paths = 0;
    std::size_t tested_green_paths = 0;
};

PDCode parse_pd_code(const std::string& text);
std::string format_pd_code(const PDCode& code);
std::string format_endpoint(const Endpoint& endpoint);
std::string format_direction(Direction direction);

SimplificationResult find_simplification(
    const PDCode& code,
    const SimplifierOptions& options = SimplifierOptions{});

std::ostream& operator<<(std::ostream& out, const Endpoint& endpoint);

}  // namespace pdcode_simplify
