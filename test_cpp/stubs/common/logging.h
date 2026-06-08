#pragma once
#include <cstdio>
// Minimal stubs — just print to stderr
#define LOG_ERROR(cls, fmt, ...)   std::fprintf(stderr, "[ERROR] " fmt "\n", ##__VA_ARGS__)
#define LOG_WARNING(cls, fmt, ...) std::fprintf(stderr, "[WARN]  " fmt "\n", ##__VA_ARGS__)
#define LOG_INFO(cls, fmt, ...)    std::fprintf(stderr, "[INFO]  " fmt "\n", ##__VA_ARGS__)
