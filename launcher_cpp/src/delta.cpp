#include "delta.h"

#include "common.h"

#include "json.h"
#include "sha256.h"
#include "libdeflate.h"

#include <algorithm>
#include <atomic>
#include <cstdio>
#include <map>
#include <mutex>
#include <set>
#include <thread>
#include <vector>

namespace hpmmo {

namespace {

// Ranges are merged across gaps up to this size (fewer requests beat a few
// wasted bytes) but never grow beyond kMaxRange (bounded memory per request).
constexpr uint64_t kMergeGap = 512u * 1024;
constexpr uint64_t kMaxRange = 16u * 1024 * 1024;
constexpr uint64_t kMaxChunk = 64u * 1024 * 1024;
// Ranges in flight at once (each holds at most kMaxRange in memory, twice).
constexpr size_t kParallelRanges = 6;

std::string ToLowerString(std::string s) {
    for (auto& c : s) c = (char)tolower((unsigned char)c);
    return s;
}

bool SafeRelPath(const std::string& p) {
    if (p.empty() || p[0] == '/' || p.find('\\') != std::string::npos || p.find(':') != std::string::npos) return false;
    size_t start = 0;
    while (start <= p.size()) {
        size_t end = p.find('/', start);
        std::string part = p.substr(start, end == std::string::npos ? std::string::npos : end - start);
        if (part.empty() || part == "." || part == "..") return false;
        if (end == std::string::npos) break;
        start = end + 1;
    }
    return true;
}

std::wstring NativePath(const std::wstring& root, const std::string& rel) {
    std::wstring w = Utf8ToWide(rel);
    std::replace(w.begin(), w.end(), L'/', kPathSep);
    return JoinPath(root, w);
}

// Reads chunks out of a few large files. One handle per file stays open
// (an fopen per chunk was ~3,600 opens an update), and the buffer only grows:
// clearing it first made every read zero-fill the whole chunk.
class ChunkReader {
public:
    ~ChunkReader() { Close(); }
    void Close() {
        for (auto& kv : open_) fclose(kv.second);
        open_.clear();
    }
    bool Read(const std::wstring& path, uint64_t offset, uint64_t len, std::string& out) {
        auto it = open_.find(path);
        if (it == open_.end()) {
            FILE* f = OpenFileW(path, L"rb");
            if (!f) return false;
            it = open_.emplace(path, f).first;
        }
        if (!SeekFile64(it->second, offset)) return false;
        out.resize((size_t)len);
        return len == 0 || fread(&out[0], 1, (size_t)len, it->second) == len;
    }

private:
    std::map<std::wstring, FILE*> open_;
};

// One libdeflate decompressor per download worker.
struct Inflater {
    libdeflate_decompressor* d = libdeflate_alloc_decompressor();
    ~Inflater() {
        if (d) libdeflate_free_decompressor(d);
    }
    // Inflates exactly `clen` raw-DEFLATE bytes into exactly `length` bytes.
    bool Run(const unsigned char* in, size_t clen, size_t length, std::string& out) {
        if (!d) return false;
        out.resize(length);
        size_t usedIn = 0, produced = 0;
        libdeflate_result r = libdeflate_deflate_decompress_ex(d, in, clen, length ? &out[0] : nullptr, length,
                                                               &usedIn, &produced);
        return r == LIBDEFLATE_SUCCESS && usedIn == clen && produced == length;
    }
};

bool ParseChunks(const JsonValue& file, size_t sourceCount, ContentFile& out, std::string& err) {
    const auto* chunks = file.arr("chunks");
    if (!chunks) {
        err = "content index: file without chunks";
        return false;
    }
    uint64_t total = 0;
    for (const auto& c : *chunks) {
        const auto& v = c.items();
        if (!c.isArray() || v.size() != 5 || !v[0].isString()) {
            err = "content index: malformed chunk entry";
            return false;
        }
        ContentChunk ch;
        ch.sha256 = v[0].asString();
        ch.length = (uint64_t)v[1].asInt64();
        int64_t src = v[2].asInt64(-1);
        ch.offset = (uint64_t)v[3].asInt64();
        ch.clen = (uint64_t)v[4].asInt64();
        if (ch.sha256.size() != 64 || src < 0 || (size_t)src >= sourceCount || ch.length == 0 ||
            ch.length > kMaxChunk || ch.clen == 0 || ch.clen > kMaxChunk + 1024) {
            err = "content index: chunk entry out of range";
            return false;
        }
        ch.source = (int)src;
        total += ch.length;
        out.chunks.push_back(ch);
    }
    if (total != out.size) {
        err = "content index: chunks of " + out.path + " do not add up to its size";
        return false;
    }
    return true;
}

}  // namespace

bool ParseContentIndex(const std::string& raw, ContentIndex& out, std::string& err) {
    out = ContentIndex{};
    JsonValue root;
    if (!JsonValue::Parse(raw, root, err) || !root.isObject()) {
        if (err.empty()) err = "content index is not a JSON object";
        return false;
    }
    if (root.i64("format", 0) != 1) {
        err = "content index has an unsupported format";
        return false;
    }
    out.clientVersion = root.str("client_version");
    const auto* sources = root.arr("sources");
    const auto* files = root.arr("files");
    if (!sources || !files) {
        err = "content index lacks sources or files";
        return false;
    }
    for (const auto& s : *sources) {
        if (!s.isString() || s.asString().rfind("https://", 0) != 0) {
            err = "content index: every chunk source must be an https URL";
            return false;
        }
        out.sources.push_back(s.asString());
    }
    std::set<std::string> seen;
    for (const auto& f : *files) {
        ContentFile cf;
        cf.path = f.str("path");
        cf.size = (uint64_t)f.i64("size", -1);
        cf.sha256 = ToLowerString(f.str("sha256"));
        if (!SafeRelPath(cf.path) || cf.sha256.size() != 64 || !seen.insert(ToLowerString(cf.path)).second) {
            err = "content index: unsafe or duplicate path '" + cf.path + "'";
            return false;
        }
        if (!ParseChunks(f, out.sources.size(), cf, err)) return false;
        out.files.push_back(std::move(cf));
    }
    if (out.files.empty()) {
        err = "content index lists no files";
        return false;
    }
    return true;
}

bool BuildFromChunks(const ContentIndex& index, const LocalInstall& local, const std::wstring& stagedDir,
                     const std::wstring& storeDir, const DeltaCallbacks& cb, std::vector<ExtractedFile>& files,
                     DeltaStats& stats, bool& cancelled, std::string& err) {
    cancelled = false;
    files.clear();
    auto stop = [&]() { return cb.cancel && cb.cancel->load(); };

    struct Ref {
        std::wstring path;
        uint64_t offset = 0;
        uint64_t length = 0;
    };

    // 1. What the installed version offers: chunk positions from its content
    //    index, and whole files by hash (an install made from a zip package).
    std::map<std::string, Ref> localChunks;
    std::map<std::string, std::wstring> localWhole;
    if (!local.dir.empty()) {
        if (!local.contentJson.empty()) {
            ContentIndex old;
            std::string perr;
            if (ParseContentIndex(local.contentJson, old, perr)) {
                for (const auto& f : old.files) {
                    std::wstring p = NativePath(local.dir, f.path);
                    uint64_t pos = 0;
                    for (const auto& c : f.chunks) {
                        localChunks.emplace(c.sha256, Ref{p, pos, c.length});
                        pos += c.length;
                    }
                    localWhole.emplace(f.sha256, p);
                }
            } else {
                LogMsg("[Delta] ignoring the installed content index: " + perr);
            }
        }
        for (const auto& f : local.files) localWhole.emplace(ToLowerString(f.sha256), NativePath(local.dir, f.relPath));
    }

    // 2. Whole files that are already present (verified by hashing them).
    std::set<std::string> wholeOk;   // new-file sha256 values copied whole
    std::map<std::string, std::wstring> wholeSource;
    for (const auto& f : index.files) {
        auto it = localWhole.find(f.sha256);
        if (it == localWhole.end() || wholeOk.count(f.sha256)) continue;
        if (FileSizeOrZero(it->second) == f.size && Sha256FileHex(it->second) == f.sha256) {
            wholeOk.insert(f.sha256);
            wholeSource[f.sha256] = it->second;
        }
        if (stop()) return cancelled = true, false;
    }

    // 3. Chunks still needed, and which of them the local install holds intact.
    std::map<std::string, const ContentChunk*> needed;
    for (const auto& f : index.files) {
        if (wholeOk.count(f.sha256)) continue;
        for (const auto& c : f.chunks) needed.emplace(c.sha256, &c);
    }
    std::map<std::string, Ref> verifiedLocal;
    std::string buf;
    {
        // In file order: reading 3,600 chunks in hash order jumped all over a
        // 1.2 GB file.
        std::vector<std::pair<const Ref*, const std::string*>> candidates;
        for (const auto& kv : needed) {
            auto it = localChunks.find(kv.first);
            if (it == localChunks.end() || it->second.length != kv.second->length) continue;
            candidates.emplace_back(&it->second, &kv.first);
        }
        std::sort(candidates.begin(), candidates.end(), [](const auto& a, const auto& b) {
            return a.first->path != b.first->path ? a.first->path < b.first->path : a.first->offset < b.first->offset;
        });
        ChunkReader reader;
        for (const auto& cand : candidates) {
            if (reader.Read(cand.first->path, cand.first->offset, cand.first->length, buf) &&
                Sha256Hex(buf.data(), buf.size()) == *cand.second) {
                verifiedLocal.emplace(*cand.second, *cand.first);
            }
            if (stop()) return cancelled = true, false;
        }
    }

    // 4. The chunk store: downloads survive an interrupted update.
    CreateDirs(storeDir);
    std::wstring storeBin = JoinPath(storeDir, L"chunks.bin");
    std::wstring storeIdx = JoinPath(storeDir, L"chunks.idx");
    std::map<std::string, Ref> stored;
    {
        std::string idxText;
        uint64_t binSize = FileSizeOrZero(storeBin);
        if (ReadFileBytes(storeIdx, idxText, 16u << 20)) {
            ChunkReader reader;   // closed before the workers append to the store
            size_t pos = 0;
            while (pos < idxText.size()) {
                size_t nl = idxText.find('\n', pos);
                std::string line = idxText.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
                pos = nl == std::string::npos ? idxText.size() : nl + 1;
                char hash[65] = {0};
                unsigned long long off = 0, len = 0;
                if (sscanf(line.c_str(), "%64s %llu %llu", hash, &off, &len) != 3) continue;
                if (off + len > binSize || !needed.count(hash)) continue;
                if (reader.Read(storeBin, off, len, buf) && Sha256Hex(buf.data(), buf.size()) == hash) {
                    stored.emplace(hash, Ref{storeBin, off, len});
                }
            }
        }
    }

    // 5. Download what is missing, merged into few ranged requests per source.
    std::map<int, std::vector<const ContentChunk*>> bySource;
    for (const auto& kv : needed) {
        if (verifiedLocal.count(kv.first) || stored.count(kv.first)) continue;
        bySource[kv.second->source].push_back(kv.second);
    }
    struct Group {
        int source;
        uint64_t first, last;
        std::vector<const ContentChunk*> chunks;
    };
    std::vector<Group> groups;
    uint64_t totalBytes = 0;
    for (auto& kv : bySource) {
        auto& list = kv.second;
        std::sort(list.begin(), list.end(), [](const ContentChunk* a, const ContentChunk* b) { return a->offset < b->offset; });
        for (const ContentChunk* c : list) {
            uint64_t end = c->offset + c->clen - 1;
            if (!groups.empty() && groups.back().source == kv.first && c->offset <= groups.back().last + 1 + kMergeGap &&
                end + 1 - groups.back().first <= kMaxRange) {
                groups.back().last = std::max(groups.back().last, end);
                groups.back().chunks.push_back(c);
            } else {
                groups.push_back(Group{kv.first, c->offset, end, {c}});
            }
        }
    }
    for (const auto& g : groups) totalBytes += g.last - g.first + 1;
    // The store keeps every download inflated until the files are assembled, so
    // a fresh install needs about twice the game's size on disk, not once.
    uint64_t storeBytes = 0;
    for (const auto& kv : bySource)
        for (const ContentChunk* c : kv.second) storeBytes += c->length;
    if (cb.reserve) {
        std::string rmsg;
        if (!cb.reserve(storeBytes, rmsg)) {
            stats.noSpace = true;
            err = rmsg;
            return false;
        }
    }
    LogMsg("[Delta] " + std::to_string(needed.size()) + " chunks needed: " + std::to_string(verifiedLocal.size()) +
           " local, " + std::to_string(stored.size()) + " already downloaded, " + std::to_string(groups.size()) +
           " range request(s) for " + std::to_string(totalBytes) + " bytes; " + std::to_string(wholeOk.size()) +
           " file(s) unchanged");

    // Several ranges download at once: one connection to the release CDN was
    // the limit (a 1 GB install crawled on a fast line). Each worker fetches,
    // inflates and verifies its range; only the append to the chunk store and
    // the progress report are serialised. A finished range is in the store, so
    // a failed or cancelled run resumes from it next time.
    uint64_t done = 0;
    if (cb.progress) cb.progress(0, totalBytes);
    std::mutex mu;
    std::atomic<size_t> next{0};
    std::atomic<bool> failed{false};
    auto fail = [&](const std::string& message) {
        std::lock_guard<std::mutex> lock(mu);
        if (!failed.exchange(true)) err = message;
    };
    auto worker = [&]() {
        std::string body;
        std::vector<std::string> plains;
        Inflater inflater;
        while (!failed.load() && !stop()) {
            size_t gi = next.fetch_add(1);
            if (gi >= groups.size()) return;
            const Group& g = groups[gi];
            std::string ferr;
            if (!cb.fetchRange(index.sources[g.source], g.first, g.last, body, ferr)) {
                if (!stop()) fail("chunk download failed: " + ferr);
                return;
            }
            if (body.size() != g.last - g.first + 1) {
                fail("chunk download returned " + std::to_string(body.size()) + " bytes, expected " +
                     std::to_string(g.last - g.first + 1));
                return;
            }
            plains.assign(g.chunks.size(), std::string());
            for (size_t ci = 0; ci < g.chunks.size(); ci++) {
                const ContentChunk* c = g.chunks[ci];
                std::string& plain = plains[ci];
                bool ok = inflater.Run(reinterpret_cast<const unsigned char*>(body.data()) + (c->offset - g.first),
                                       (size_t)c->clen, (size_t)c->length, plain);
                if (!ok || plain.size() != c->length || Sha256Hex(plain.data(), plain.size()) != c->sha256) {
                    fail("a downloaded chunk failed verification (" + c->sha256.substr(0, 12) + ")");
                    return;
                }
            }
            std::lock_guard<std::mutex> lock(mu);
            if (failed.load()) return;
            FILE* bin = OpenFileW(storeBin, L"ab");
            FILE* idx = OpenFileW(storeIdx, L"ab");
            if (!bin || !idx) {
                if (bin) fclose(bin);
                if (idx) fclose(idx);
                failed = true;
                err = "cannot write the chunk store";
                return;
            }
            bool wrote = true;
            for (size_t ci = 0; ci < g.chunks.size() && wrote; ci++) {
                const ContentChunk* c = g.chunks[ci];
                const std::string& plain = plains[ci];
#ifdef _WIN32
                _fseeki64(bin, 0, SEEK_END);
#else
                fseeko(bin, 0, SEEK_END);
#endif
                uint64_t off = TellFile64(bin);
                // An unchecked short write (a full disk) only surfaced later as
                // "a chunk failed verification" and a retry that could never work.
                wrote = fwrite(plain.data(), 1, plain.size(), bin) == plain.size() && fflush(bin) == 0 &&
                        fprintf(idx, "%s %llu %llu\n", c->sha256.c_str(), (unsigned long long)off,
                                (unsigned long long)plain.size()) > 0;
                if (wrote) stored.emplace(c->sha256, Ref{storeBin, off, (uint64_t)plain.size()});
            }
            wrote = (fflush(idx) == 0) && wrote;
            wrote = (fclose(bin) == 0) && wrote;
            wrote = (fclose(idx) == 0) && wrote;
            if (!wrote) {
                failed = true;
                stats.noSpace = true;
                err = "writing the chunk store failed - is the disk full?";
                return;
            }
            stats.requests++;
            stats.downloadBytes += body.size();
            done += body.size();
            if (cb.progress) cb.progress(done, totalBytes);
        }
    };
    size_t workers = std::min<size_t>(kParallelRanges, groups.size());
    if (workers <= 1) {
        worker();
    } else {
        std::vector<std::thread> pool;
        for (size_t i = 0; i < workers; i++) pool.emplace_back(worker);
        for (auto& t : pool) t.join();
    }
    if (failed.load()) return false;
    if (stop()) return cancelled = true, false;

    // 6. Assemble every file and prove it byte-for-byte while it is written:
    //    each chunk was already verified, and hashing the stream as it goes
    //    out proves their order without reading 1.3 GB back (twice). Every
    //    file is forced to the disk before the version can be activated.
    ChunkReader reader;
    for (const auto& f : index.files) {
        if (stop()) return cancelled = true, false;
        std::wstring dest = NativePath(stagedDir, f.path);
        size_t slash = dest.find_last_of(kPathSep);
        if (slash != std::wstring::npos) CreateDirs(dest.substr(0, slash));
        if (wholeOk.count(f.sha256)) {
            // Hashed in step 2; the copy is checked by its size.
            if (!CopyFilePlain(wholeSource[f.sha256], dest) || FileSizeOrZero(dest) != f.size) {
                stats.noSpace = true;
                err = "cannot copy " + f.path + " from the installed version - is the disk full?";
                return false;
            }
            stats.reusedBytes += f.size;
        } else {
            FILE* out = OpenFileW(dest, L"wb");
            if (!out) {
                err = "cannot create " + f.path;
                return false;
            }
            Sha256Stream hash;
            uint64_t written = 0;
            for (const auto& c : f.chunks) {
                const Ref* ref = nullptr;
                auto lit = verifiedLocal.find(c.sha256);
                if (lit != verifiedLocal.end()) {
                    ref = &lit->second;
                    stats.reusedBytes += c.length;
                } else {
                    auto sit = stored.find(c.sha256);
                    if (sit != stored.end()) ref = &sit->second;
                }
                if (!ref || !reader.Read(ref->path, ref->offset, ref->length, buf)) {
                    fclose(out);
                    err = "cannot assemble " + f.path;
                    return false;
                }
                if (fwrite(buf.data(), 1, buf.size(), out) != buf.size()) {
                    fclose(out);
                    stats.noSpace = true;
                    err = "cannot write " + f.path + " - is the disk full?";
                    return false;
                }
                hash.Update(buf.data(), buf.size());
                written += buf.size();
            }
            bool closed = fflush(out) == 0;
            closed = (fclose(out) == 0) && closed;
            if (!closed) {
                stats.noSpace = true;
                err = "cannot finish " + f.path + " - is the disk full?";
                return false;
            }
            if (written != f.size || hash.FinishHex() != f.sha256) {
                err = "assembled " + f.path + " does not match the content index";
                return false;
            }
        }
        if (!FlushToDisk(dest)) {
            err = "cannot flush " + f.path + " to the disk";
            return false;
        }
        ExtractedFile ef;
        ef.relPath = f.path;
        ef.size = f.size;
        ef.sha256 = f.sha256;
        files.push_back(ef);
    }
    return true;
}

}  // namespace hpmmo
