// Chunked (delta) installation: builds a client version from content-defined
// chunks (tools/release/chunk_release.py). Chunks already on disk - in the
// installed version - are copied; only the missing ones are downloaded, with
// HTTP Range requests into the releases' chunks-<ver>.bin files. Every chunk is
// verified against its SHA-256 from the signed content index.
#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

#include "zip.h"   // ExtractedFile

namespace hpmmo {

struct ContentChunk {
    std::string sha256;
    uint64_t length = 0;
    int source = 0;
    uint64_t offset = 0;   // in the source, compressed bytes
    uint64_t clen = 0;     // compressed length (raw DEFLATE)
};

struct ContentFile {
    std::string path;      // forward slashes, relative
    uint64_t size = 0;
    std::string sha256;
    std::vector<ContentChunk> chunks;
};

struct ContentIndex {
    std::string clientVersion;
    std::vector<std::string> sources;   // absolute URLs
    std::vector<ContentFile> files;
};

bool ParseContentIndex(const std::string& raw, ContentIndex& out, std::string& err);

// What the installed version can contribute.
struct LocalInstall {
    std::wstring dir;            // installed version directory ("" = none)
    std::string contentJson;     // its .content.json ("" = installed from a zip)
    std::vector<ExtractedFile> files;  // its install record (path, size, sha256)
};

struct DeltaCallbacks {
    // Fetches bytes [first, last] (inclusive) of url into body.
    std::function<bool(const std::string& url, uint64_t first, uint64_t last, std::string& body,
                       std::string& err)>
        fetchRange;
    std::function<void(uint64_t done, uint64_t total)> progress;   // compressed bytes
    // Once the plan is known: may the build use `storeBytes` more disk for the
    // chunk store (inflated downloads) on top of the staged files? false with
    // a message refuses before anything is downloaded.
    std::function<bool(uint64_t storeBytes, std::string& message)> reserve;
    std::atomic<bool>* cancel = nullptr;
    // Stop once every missing chunk is in the chunk store: nothing is
    // assembled and `files` stays empty (the updater's --stop-after download).
    bool downloadOnly = false;
};

struct DeltaStats {
    uint64_t reusedBytes = 0;      // copied from the local install
    uint64_t downloadBytes = 0;    // fetched over the network (compressed)
    uint64_t requests = 0;
    // The build stopped for lack of disk space (refused up front, or a write
    // to the chunk store or a staged file failed).
    bool noSpace = false;
};

// Builds every file of `index` under stagedDir. storeDir keeps downloaded
// chunks across interruptions (resumable). Returns false with err on failure;
// `cancelled` is set when the cancel flag stopped it.
bool BuildFromChunks(const ContentIndex& index, const LocalInstall& local, const std::wstring& stagedDir,
                     const std::wstring& storeDir, const DeltaCallbacks& cb, std::vector<ExtractedFile>& files,
                     DeltaStats& stats, bool& cancelled, std::string& err);

}  // namespace hpmmo
