#!/usr/bin/env sh
set -eu

BUILD_DIR="${BUILD_DIR:-build}"
CONFIG="${CONFIG:-Release}"

cmake -S . -B "$BUILD_DIR" -DCMAKE_BUILD_TYPE="$CONFIG"
cmake --build "$BUILD_DIR" --config "$CONFIG"
ctest --test-dir "$BUILD_DIR" --build-config "$CONFIG" --output-on-failure
