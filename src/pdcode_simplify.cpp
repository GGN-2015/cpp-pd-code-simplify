#include "pdcode_simplify/pdcode_simplify.hpp"

#include <algorithm>
#include <cctype>
#include <deque>
#include <limits>
#include <map>
#include <numeric>
#include <set>
#include <sstream>
#include <stdexcept>
#include <unordered_map>
#include <unordered_set>

namespace pdcode_simplify {
namespace {

constexpr int kBlockedWeight = 10000;

int positive_mod(int value, int modulus) {
    int result = value % modulus;
    return result < 0 ? result + modulus : result;
}

int endpoint_key(const Endpoint& endpoint) {
    return endpoint.crossing * 4 + endpoint.strand;
}

Endpoint endpoint_from_key(int key) {
    return Endpoint{key / 4, key % 4};
}

long long face_pair_key(int a, int b) {
    if (a > b) {
        std::swap(a, b);
    }
    return (static_cast<long long>(a) << 32) ^ static_cast<unsigned int>(b);
}

struct CrossingState {
    std::array<Endpoint, 4> adjacent{};
    bool directions[4][4]{};
    int sign = 0;
};

struct Diagram {
    PDCode code;
    std::vector<CrossingState> crossings;

    explicit Diagram(PDCode input) : code(std::move(input)), crossings(code.size()) {
        build_adjacency();
        auto starts = component_starts_from_pd();
        orient_crossings(starts);
    }

    Endpoint opposite(const Endpoint& endpoint) const {
        return crossings.at(endpoint.crossing).adjacent.at(endpoint.strand);
    }

    Endpoint next(const Endpoint& endpoint) const {
        return crossings.at(endpoint.crossing).adjacent.at((endpoint.strand + 2) % 4);
    }

    Endpoint next_corner(const Endpoint& endpoint) const {
        return crossings.at(endpoint.crossing).adjacent.at((endpoint.strand + 1) % 4);
    }

    Endpoint rotate_endpoint(const Endpoint& endpoint, int offset) const {
        return Endpoint{endpoint.crossing, positive_mod(endpoint.strand + offset, 4)};
    }

    std::vector<Endpoint> crossing_entries() const {
        std::vector<Endpoint> entries;
        entries.reserve(crossings.size() * 2);
        for (int c = 0; c < static_cast<int>(crossings.size()); ++c) {
            if (crossings[c].sign == -1) {
                entries.push_back(Endpoint{c, 0});
                entries.push_back(Endpoint{c, 1});
            } else if (crossings[c].sign == 1) {
                entries.push_back(Endpoint{c, 0});
                entries.push_back(Endpoint{c, 3});
            } else {
                throw std::logic_error("Crossing was not oriented");
            }
        }
        return entries;
    }

private:
    void build_adjacency() {
        std::map<int, std::vector<Endpoint>> gluings;
        for (int c = 0; c < static_cast<int>(code.size()); ++c) {
            for (int i = 0; i < 4; ++i) {
                gluings[code[c][i]].push_back(Endpoint{c, i});
            }
        }

        for (std::map<int, std::vector<Endpoint>>::const_iterator it = gluings.begin();
             it != gluings.end();
             ++it) {
            const int label = it->first;
            const std::vector<Endpoint>& endpoints = it->second;
            if (endpoints.size() != 2) {
                std::ostringstream message;
                message << "PD label " << label << " appears " << endpoints.size()
                        << " times; each label must appear exactly twice";
                throw std::invalid_argument(message.str());
            }
            const Endpoint a = endpoints[0];
            const Endpoint b = endpoints[1];
            crossings[a.crossing].adjacent[a.strand] = b;
            crossings[b.crossing].adjacent[b.strand] = a;
        }
    }

    std::vector<Endpoint> component_starts_from_pd() const {
        std::set<int> labels;
        std::map<int, std::vector<Endpoint>> gluings;
        for (int c = 0; c < static_cast<int>(code.size()); ++c) {
            for (int i = 0; i < 4; ++i) {
                labels.insert(code[c][i]);
                gluings[code[c][i]].push_back(Endpoint{c, i});
            }
        }

        std::vector<Endpoint> starts;
        while (!labels.empty()) {
            const int m = *labels.begin();
            labels.erase(labels.begin());
            const auto& gluing = gluings.at(m);
            const Endpoint first = gluing[0];
            const Endpoint second = gluing[1];

            Endpoint direction;
            int next_label = m;

            if (first.crossing == second.crossing) {
                std::set<int> crossing_labels(code[first.crossing].begin(), code[first.crossing].end());
                crossing_labels.erase(m);
                if (crossing_labels.empty()) {
                    throw std::invalid_argument("A PD self-loop crossing must have another label");
                }
                next_label = *crossing_labels.begin();
                direction = Endpoint{first.crossing, index_of_label(first.crossing, next_label)};
            } else {
                const int j1 = (first.strand + 2) % 4;
                const int j2 = (second.strand + 2) % 4;
                const int l1 = code[first.crossing][j1];
                const int l2 = code[second.crossing][j2];
                if (l1 < l2) {
                    next_label = l1;
                    direction = Endpoint{first.crossing, j1};
                } else if (l2 < l1) {
                    next_label = l2;
                    direction = Endpoint{second.crossing, j2};
                } else {
                    next_label = l1;
                    if (code[second.crossing][0] == l1 || code[first.crossing][0] == m) {
                        direction = Endpoint{first.crossing, j1};
                    } else {
                        direction = Endpoint{second.crossing, j2};
                    }
                }
            }

            starts.push_back(direction);
            while (next_label != m) {
                auto removed = labels.erase(next_label);
                if (removed == 0) {
                    throw std::invalid_argument("PD component traversal encountered a repeated label");
                }
                const auto& next_gluing = gluings.at(next_label);
                const int index = next_gluing[0] == direction ? 0 : (next_gluing[1] == direction ? 1 : -1);
                if (index == -1) {
                    throw std::invalid_argument("PD component traversal lost its current endpoint");
                }
                const Endpoint other = next_gluing[1 - index];
                direction = Endpoint{other.crossing, (other.strand + 2) % 4};
                next_label = code[direction.crossing][direction.strand];
            }
        }

        return starts;
    }

    int index_of_label(int crossing, int label) const {
        for (int i = 0; i < 4; ++i) {
            if (code[crossing][i] == label) {
                return i;
            }
        }
        throw std::logic_error("Label was not present at the requested crossing");
    }

    void make_tail(int crossing, int strand) {
        const int head = (strand + 2) % 4;
        if (crossings[crossing].directions[head][strand]) {
            throw std::invalid_argument("The same crossing strand was oriented twice");
        }
        crossings[crossing].directions[strand][head] = true;
    }

    void orient_crossings(std::vector<Endpoint> starts) {
        std::set<int> remaining;
        for (int c = 0; c < static_cast<int>(crossings.size()); ++c) {
            for (int i = 0; i < 4; ++i) {
                remaining.insert(endpoint_key(Endpoint{c, i}));
            }
        }

        while (!remaining.empty()) {
            Endpoint start;
            if (!starts.empty()) {
                start = starts.back();
                starts.pop_back();
            } else {
                start = endpoint_from_key(*remaining.begin());
            }

            Endpoint current = start;
            while (true) {
                const Endpoint other = crossings[current.crossing].adjacent[current.strand];
                make_tail(other.crossing, other.strand);
                remaining.erase(endpoint_key(current));
                remaining.erase(endpoint_key(other));
                current = Endpoint{other.crossing, (other.strand + 2) % 4};
                if (current == start) {
                    break;
                }
            }
        }

        for (int c = 0; c < static_cast<int>(crossings.size()); ++c) {
            orient_crossing(c);
        }
    }

    void orient_crossing(int crossing) {
        if (crossings[crossing].directions[2][0]) {
            rotate_crossing_180(crossing);
        }

        if (crossings[crossing].directions[3][1]) {
            crossings[crossing].sign = 1;
        } else if (crossings[crossing].directions[1][3]) {
            crossings[crossing].sign = -1;
        } else {
            throw std::invalid_argument("Could not determine crossing sign from PD orientation");
        }
    }

    void rotate_crossing_180(int crossing) {
        auto old_adjacent = crossings[crossing].adjacent;
        bool old_directions[4][4]{};
        for (int a = 0; a < 4; ++a) {
            for (int b = 0; b < 4; ++b) {
                old_directions[a][b] = crossings[crossing].directions[a][b];
                crossings[crossing].directions[a][b] = false;
            }
        }

        for (int i = 0; i < 4; ++i) {
            const Endpoint other = old_adjacent[(i + 2) % 4];
            if (other.crossing != crossing) {
                crossings[other.crossing].adjacent[other.strand] = Endpoint{crossing, i};
                crossings[crossing].adjacent[i] = other;
            } else {
                crossings[crossing].adjacent[i] = Endpoint{crossing, positive_mod(other.strand - 2, 4)};
            }
        }

        for (int a = 0; a < 4; ++a) {
            for (int b = 0; b < 4; ++b) {
                if (old_directions[a][b]) {
                    crossings[crossing].directions[(a + 2) % 4][(b + 2) % 4] = true;
                }
            }
        }
    }
};

struct GraphEdge {
    int u = -1;
    int v = -1;
    int interface_u = -1;
    int interface_v = -1;
    int weight = 1;
};

struct DualGraph {
    std::vector<int> edge_to_face;
    std::vector<int> face_assignment_order;
    std::vector<std::vector<int>> faces;
    std::vector<GraphEdge> edges;
    std::vector<std::vector<int>> adjacency;
    std::unordered_map<long long, int> edge_by_faces;

    explicit DualGraph(const Diagram& diagram) {
        build_faces(diagram);
        build_edges(diagram);
    }

    int edge_index(int a, int b) const {
        const auto found = edge_by_faces.find(face_pair_key(a, b));
        if (found == edge_by_faces.end()) {
            return -1;
        }
        return found->second;
    }

    const GraphEdge* edge(int a, int b) const {
        const int index = edge_index(a, b);
        if (index < 0) {
            return nullptr;
        }
        return &edges[index];
    }

    GraphEdge* mutable_edge(int a, int b) {
        const int index = edge_index(a, b);
        if (index < 0) {
            return nullptr;
        }
        return &edges[index];
    }

    int interface_for_face(const GraphEdge& edge, int face) const {
        if (edge.u == face) {
            return edge.interface_u;
        }
        if (edge.v == face) {
            return edge.interface_v;
        }
        throw std::logic_error("Face is not incident to the requested dual edge");
    }

private:
    void build_faces(const Diagram& diagram) {
        const int endpoint_count = static_cast<int>(diagram.crossings.size() * 4);
        edge_to_face.assign(endpoint_count, -1);
        std::vector<char> present(endpoint_count, true);
        int remaining = endpoint_count;

        while (remaining > 0) {
            int first_key = -1;
            for (int key = endpoint_count - 1; key >= 0; --key) {
                if (present[key]) {
                    first_key = key;
                    break;
                }
            }
            if (first_key == -1) {
                break;
            }

            const int face_index = static_cast<int>(faces.size());
            std::vector<int> face;
            Endpoint first = endpoint_from_key(first_key);
            Endpoint current = first;
            present[first_key] = false;
            --remaining;
            edge_to_face[first_key] = face_index;
            face_assignment_order.push_back(first_key);
            face.push_back(first_key);

            while (true) {
                Endpoint next = diagram.next_corner(current);
                if (next == first) {
                    faces.push_back(std::move(face));
                    break;
                }
                const int next_key = endpoint_key(next);
                edge_to_face[next_key] = face_index;
                face_assignment_order.push_back(next_key);
                if (present[next_key]) {
                    present[next_key] = false;
                    --remaining;
                }
                face.push_back(next_key);
                current = next;
            }
        }
    }

    void build_edges(const Diagram& diagram) {
        adjacency.assign(faces.size(), {});
        for (int key : face_assignment_order) {
            const Endpoint endpoint = endpoint_from_key(key);
            const Endpoint opposite = diagram.opposite(endpoint);
            const int opposite_key = endpoint_key(opposite);
            const int face = edge_to_face[key];
            const int neighbor = edge_to_face[opposite_key];
            if (face >= neighbor) {
                continue;
            }

            const long long pair_key = face_pair_key(face, neighbor);
            const auto found = edge_by_faces.find(pair_key);
            if (found == edge_by_faces.end()) {
                GraphEdge edge;
                edge.u = face;
                edge.v = neighbor;
                edge.interface_u = key;
                edge.interface_v = opposite_key;
                edge.weight = 1;
                const int edge_index = static_cast<int>(edges.size());
                edge_by_faces[pair_key] = edge_index;
                edges.push_back(edge);
                adjacency[face].push_back(edge_index);
                adjacency[neighbor].push_back(edge_index);
            } else {
                GraphEdge& edge = edges[found->second];
                if (edge.u == face) {
                    edge.interface_u = key;
                    edge.interface_v = opposite_key;
                } else {
                    edge.interface_u = opposite_key;
                    edge.interface_v = key;
                }
            }
        }
    }
};

enum class Level {
    Under,
    Over
};

std::string level_to_string(Level level) {
    return level == Level::Under ? "under" : "over";
}

Level opposite_level(Level level) {
    return level == Level::Under ? Level::Over : Level::Under;
}

std::vector<std::vector<Endpoint>> possible_red_lines(const Diagram& diagram) {
    std::vector<std::vector<Endpoint>> long_lines;
    std::vector<Endpoint> entries = diagram.crossing_entries();

    while (!entries.empty()) {
        std::vector<Endpoint> red_line;
        Endpoint endpoint = entries.back();
        entries.pop_back();
        red_line.push_back(endpoint);
        std::unordered_set<int> crossings;
        crossings.insert(endpoint.crossing);

        while (true) {
            endpoint = diagram.next(endpoint);
            red_line.push_back(endpoint);
            if (crossings.count(endpoint.crossing) != 0) {
                break;
            }
            crossings.insert(endpoint.crossing);
        }
        long_lines.push_back(std::move(red_line));
    }

    std::vector<std::vector<Endpoint>> candidates;
    for (const auto& line : long_lines) {
        if (line.size() < 3) {
            continue;
        }
        for (std::size_t i = 0; i < line.size() - 2; ++i) {
            candidates.emplace_back(line.begin(), line.end() - static_cast<std::ptrdiff_t>(i));
        }
    }
    return candidates;
}

void reset_weights(DualGraph& graph) {
    for (auto& edge : graph.edges) {
        edge.weight = 1;
    }
}

void collect_simple_paths_dfs(
    const DualGraph& graph,
    int current,
    int target,
    int cutoff,
    int max_paths,
    std::vector<char>& visited,
    std::vector<int>& current_path,
    std::vector<std::vector<int>>& paths) {
    if (static_cast<int>(current_path.size()) - 1 >= cutoff) {
        return;
    }

    for (int edge_index : graph.adjacency[current]) {
        const GraphEdge& edge = graph.edges[edge_index];
        const int next = edge.u == current ? edge.v : edge.u;
        if (visited[next]) {
            continue;
        }

        current_path.push_back(next);
        visited[next] = true;

        if (next == target) {
            int path_weight = 0;
            for (std::size_t i = 0; i + 1 < current_path.size(); ++i) {
                const GraphEdge* path_edge = graph.edge(current_path[i], current_path[i + 1]);
                if (path_edge == nullptr) {
                    throw std::logic_error("Missing dual edge while weighing a path");
                }
                path_weight += path_edge->weight;
                if (path_weight >= cutoff) {
                    break;
                }
            }
            if (path_weight < cutoff) {
                paths.push_back(current_path);
            }
            if (max_paths != -1 && static_cast<int>(paths.size()) > max_paths) {
                visited[next] = false;
                current_path.pop_back();
                return;
            }
        } else {
            collect_simple_paths_dfs(graph, next, target, cutoff, max_paths, visited, current_path, paths);
            if (max_paths != -1 && static_cast<int>(paths.size()) > max_paths) {
                visited[next] = false;
                current_path.pop_back();
                return;
            }
        }

        visited[next] = false;
        current_path.pop_back();
    }
}

std::vector<std::vector<int>> collect_simple_paths(
    const DualGraph& graph,
    int source,
    int target,
    int cutoff,
    int max_paths) {
    std::vector<std::vector<int>> paths;
    if (source == target || source < 0 || target < 0 ||
        source >= static_cast<int>(graph.faces.size()) ||
        target >= static_cast<int>(graph.faces.size()) ||
        cutoff <= 0) {
        return paths;
    }

    std::vector<char> visited(graph.faces.size(), false);
    std::vector<int> current_path{source};
    visited[source] = true;
    collect_simple_paths_dfs(graph, source, target, cutoff, max_paths, visited, current_path, paths);
    return paths;
}

bool contains_endpoint_key(const std::vector<int>& endpoints, int key) {
    return std::find(endpoints.begin(), endpoints.end(), key) != endpoints.end();
}

bool do_check(
    const Diagram& diagram,
    const DualGraph& graph,
    const std::vector<Endpoint>& red_path,
    const std::vector<int>& green_path,
    Direction direction,
    SimplificationResult& result) {
    std::vector<int> green_left_cross;
    green_left_cross.reserve(green_path.size());

    for (std::size_t i = 0; i + 1 < green_path.size(); ++i) {
        const int f1 = green_path[i];
        const int f2 = green_path[i + 1];
        const GraphEdge* edge = graph.edge(f1, f2);
        if (edge == nullptr) {
            return false;
        }
        const int face_for_interface = direction == Direction::Right ? f1 : f2;
        green_left_cross.push_back(graph.interface_for_face(*edge, face_for_interface));
    }

    std::unordered_set<int> red_boundary_crossings;
    std::deque<int> to_check;
    std::unordered_set<int> queued;
    std::unordered_map<int, Level> check_result;

    auto enqueue = [&](int key) {
        if (queued.insert(key).second) {
            to_check.push_back(key);
        }
    };

    auto erase_queued = [&](int key) {
        auto found = queued.find(key);
        if (found != queued.end()) {
            queued.erase(found);
            auto it = std::find(to_check.begin(), to_check.end(), key);
            if (it != to_check.end()) {
                to_check.erase(it);
            }
        }
    };

    for (std::size_t i = 0; i + 1 < red_path.size(); ++i) {
        const Endpoint red_endpoint = red_path[i];
        red_boundary_crossings.insert(red_endpoint.crossing);
        const int offset = direction == Direction::Right ? 3 : 1;
        const Endpoint cross_strand = diagram.rotate_endpoint(red_endpoint, offset);
        const int key = endpoint_key(cross_strand);
        enqueue(key);
        check_result[key] = (cross_strand.strand % 2 == 0) ? Level::Under : Level::Over;
    }

    std::vector<GreenCrossing> green_crossings;
    std::unordered_map<int, int> green_index;
    for (int i = 0; i < static_cast<int>(green_path.size()); ++i) {
        green_index[green_path[i]] = i;
    }

    bool good_path = true;
    while (!to_check.empty() && good_path) {
        const int start_key = to_check.back();
        to_check.pop_back();
        queued.erase(start_key);
        Endpoint cross_strand = endpoint_from_key(start_key);

        while (true) {
            const int cross_key = endpoint_key(cross_strand);
            const Level current_level = check_result.at(cross_key);
            const Endpoint opposite = diagram.opposite(cross_strand);
            const int opposite_key = endpoint_key(opposite);
            const auto opposite_result = check_result.find(opposite_key);
            if (opposite_result != check_result.end() && opposite_result->second != current_level) {
                good_path = false;
                break;
            }

            if (contains_endpoint_key(green_left_cross, cross_key)) {
                const int f1 = graph.edge_to_face[cross_key];
                const int f2 = graph.edge_to_face[opposite_key];
                const auto f1_index = green_index.find(f1);
                const auto f2_index = green_index.find(f2);
                if (f1_index == green_index.end() || f2_index == green_index.end()) {
                    good_path = false;
                    break;
                }
                const bool forward = f1_index->second < f2_index->second;
                GreenCrossing green_crossing;
                green_crossing.from_face = forward ? f1 : f2;
                green_crossing.to_face = forward ? f2 : f1;
                green_crossing.strand_level = level_to_string(opposite_level(current_level));
                green_crossings.push_back(std::move(green_crossing));
                break;
            }

            check_result[opposite_key] = current_level;
            erase_queued(opposite_key);

            if (red_boundary_crossings.count(opposite.crossing) != 0) {
                break;
            }

            cross_strand = opposite;
            const Endpoint side1 = diagram.rotate_endpoint(cross_strand, 1);
            const Endpoint side2 = diagram.rotate_endpoint(cross_strand, 3);
            const int side1_key = endpoint_key(side1);
            const int side2_key = endpoint_key(side2);

            if (cross_strand.strand % 2 == 1 && current_level == Level::Under) {
                auto first = check_result.find(side1_key);
                auto second = check_result.find(side2_key);
                if ((first != check_result.end() && first->second == Level::Over) ||
                    (second != check_result.end() && second->second == Level::Over)) {
                    good_path = false;
                    break;
                }
                if (first == check_result.end()) {
                    check_result[side1_key] = Level::Under;
                    enqueue(side1_key);
                }
                if (second == check_result.end()) {
                    check_result[side2_key] = Level::Under;
                    enqueue(side2_key);
                }
            }

            if (cross_strand.strand % 2 == 0 && current_level == Level::Over) {
                auto first = check_result.find(side1_key);
                auto second = check_result.find(side2_key);
                if ((first != check_result.end() && first->second == Level::Under) ||
                    (second != check_result.end() && second->second == Level::Under)) {
                    good_path = false;
                    break;
                }
                if (first == check_result.end()) {
                    check_result[side1_key] = Level::Over;
                    enqueue(side1_key);
                }
                if (second == check_result.end()) {
                    check_result[side2_key] = Level::Over;
                    enqueue(side2_key);
                }
            }

            const Endpoint across_same_crossing = diagram.rotate_endpoint(cross_strand, 2);
            const int across_key = endpoint_key(across_same_crossing);
            check_result[across_key] = current_level;
            cross_strand = across_same_crossing;
        }
    }

    if (!good_path) {
        return false;
    }

    result.found = true;
    result.direction = direction;
    result.red_path = red_path;
    result.green_path = green_path;
    result.green_crossings = std::move(green_crossings);
    return true;
}

}  // namespace

PDCode parse_pd_code(const std::string& text) {
    std::vector<int> numbers;
    for (std::size_t i = 0; i < text.size();) {
        if (text[i] == '-' || std::isdigit(static_cast<unsigned char>(text[i]))) {
            const std::size_t start = i;
            if (text[i] == '-') {
                ++i;
                if (i >= text.size() || !std::isdigit(static_cast<unsigned char>(text[i]))) {
                    throw std::invalid_argument("A minus sign must be followed by digits");
                }
            }
            while (i < text.size() && std::isdigit(static_cast<unsigned char>(text[i]))) {
                ++i;
            }
            const std::string token = text.substr(start, i - start);
            numbers.push_back(std::stoi(token));
        } else {
            ++i;
        }
    }

    if (numbers.empty()) {
        return {};
    }
    if (numbers.size() % 4 != 0) {
        throw std::invalid_argument("The input must contain a multiple of four integers");
    }

    PDCode code;
    code.reserve(numbers.size() / 4);
    for (std::size_t i = 0; i < numbers.size(); i += 4) {
        code.push_back(Crossing{numbers[i], numbers[i + 1], numbers[i + 2], numbers[i + 3]});
    }
    return code;
}

std::string format_pd_code(const PDCode& code) {
    std::ostringstream out;
    out << '[';
    for (std::size_t i = 0; i < code.size(); ++i) {
        if (i != 0) {
            out << ", ";
        }
        out << '(' << code[i][0] << ", " << code[i][1] << ", "
            << code[i][2] << ", " << code[i][3] << ')';
    }
    out << ']';
    return out.str();
}

std::string format_endpoint(const Endpoint& endpoint) {
    std::ostringstream out;
    out << '(' << endpoint.crossing << ", " << endpoint.strand << ')';
    return out.str();
}

std::string format_direction(Direction direction) {
    return direction == Direction::Left ? "left" : "right";
}

SimplificationResult find_simplification(
    const PDCode& code,
    const SimplifierOptions& options) {
    SimplificationResult result;
    Diagram diagram(code);
    DualGraph graph(diagram);
    const auto red_lines = possible_red_lines(diagram);

    for (const auto& red_path : red_lines) {
        ++result.tested_red_paths;
        reset_weights(graph);

        const Endpoint start = red_path.front();
        const Endpoint end = red_path.back();
        const int start_face = graph.edge_to_face[endpoint_key(start)];
        const int start_opposite_face = graph.edge_to_face[endpoint_key(diagram.opposite(start))];
        const int end_face = graph.edge_to_face[endpoint_key(end)];
        const int end_opposite_face = graph.edge_to_face[endpoint_key(diagram.opposite(end))];
        const std::array<int, 2> sources{start_face, start_opposite_face};
        const std::array<int, 2> destinations{end_face, end_opposite_face};

        for (std::size_t i = 1; i + 1 < red_path.size(); ++i) {
            const Endpoint endpoint = red_path[i];
            const int right_region = graph.edge_to_face[endpoint_key(endpoint)];
            const int left_region = graph.edge_to_face[endpoint_key(diagram.opposite(endpoint))];
            if (GraphEdge* edge = graph.mutable_edge(right_region, left_region)) {
                edge->weight = kBlockedWeight;
            }
        }

        std::vector<std::vector<int>> paths;
        const int cutoff = static_cast<int>(red_path.size()) - 1;
        for (int source : sources) {
            for (int destination : destinations) {
                auto found_paths = collect_simple_paths(graph, source, destination, cutoff, options.max_paths);
                paths.insert(paths.end(), found_paths.begin(), found_paths.end());
                if (options.max_paths != -1 && static_cast<int>(paths.size()) > options.max_paths) {
                    break;
                }
            }
        }

        for (const auto& green_path : paths) {
            ++result.tested_green_paths;
            if (green_path.size() >= red_path.size()) {
                continue;
            }
            if (do_check(diagram, graph, red_path, green_path, Direction::Left, result)) {
                return result;
            }
            if (do_check(diagram, graph, red_path, green_path, Direction::Right, result)) {
                return result;
            }
        }
    }

    return result;
}

std::ostream& operator<<(std::ostream& out, const Endpoint& endpoint) {
    out << format_endpoint(endpoint);
    return out;
}

}  // namespace pdcode_simplify
