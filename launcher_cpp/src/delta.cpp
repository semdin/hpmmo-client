#include "delta.h"

#include "common.h"
#include "inflate.h"
#include "json.h"
#include "sha256.h"

#include <algorithm>
#include <cstdio>
#include <map>
#include <set>

namespace hpmmo {

namespace {

// Ranges are merged across gaps up to this size (fewer requests beat a few
// wasted bytes) but never grow beyond kMaxRange (bounded memory per request).
constexpr uint64_t kMergeGap = 512u * 1024;
constexpr uint64_t kMaxRange = 16u * 1024 * 1024;
constexpr uint64_t kMaxChunk = 64u * 1024 * 1024;

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

bool ReadAt(const std::wstring& path, uint64_t offset, uint64_t len, std::string& out) {
    out.clear();
    FILE* f = OpenFileW(path, L"rb");
    if (!f) return false;
    bool ok = SeekFile64(f, offset);
    if (ok) {
        out.resize((size_t)len);
        ok = len == 0 || fread(&out[0], 1, (size_t)len, f) == len;
    }
    fclose(f);
    return ok;
}

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
    for (const auto& kv : needed) {
        auto it = localChunks.find(kv.first);
        if (it == localChunks.end() || it->second.length != kv.second->length) continue;
        if (ReadAt(it->second.path, it->second.offset, it->second.length, buf) && Sha256Hex(buf.data(), buf.size()) == kv.first) {
            verifiedLocal.emplace(kv.first, it->second);
        }
        if (stop()) return cancelled = true, false;
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
            size_t pos = 0;
            while (pos < idxText.size()) {
                size_t nl = idxText.find('\n', pos);
                std::string line = idxText.substr(pos, nl == std::string::npos ? std::string::npos : nl - pos);
                pos = nl == std::string::npos ? idxText.size() : nl + 1;
                char hash[65] = {0};
                unsigned long long off = 0, len = 0;
                if (sscanf(line.c_str(), "%64s %llu %llu", hash, &off, &len) != 3) continue;
                if (off + len > binSize || !needed.count(hash)) continue;
                if (ReadAt(storeBin, off, len, buf) && Sha256Hex(buf.data(), buf.size()) == hash) {
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
    LogMsg("[Delta] " + std::to_string(needed.size()) + " chunks needed: " + std::to_string(verifiedLocal.size()) +
           " local, " + std::to_string(stored.size()) + " already downloaded, " + std::to_string(groups.size()) +
           " range request(s) for " + std::to_string(totalBytes) + " bytes; " + std::to_string(wholeOk.size()) +
           " file(s) unchanged");

    uint64_t done = 0;
    if (cb.progress) cb.progress(0, totalBytes);
    std::string body, plain;
    for (const auto& g : groups) {
        if (stop()) return cancelled = true, false;
        std::string ferr;
        if (!cb.fetchRange(index.sources[g.source], g.first, g.last, body, ferr)) {
            err = "chunk download failed: " + ferr;
            return false;
        }
        if (body.size() != g.last - g.first + 1) {
            err = "chunk download returned " + std::to_string(body.size()) + " bytes, expected " +
                  std::to_string(g.last - g.first + 1);
            return false;
        }
        stats.requests++;
        stats.downloadBytes += body.size();
        FILE* bin = OpenFileW(storeBin, L"ab");
        FILE* idx = OpenFileW(storeIdx, L"ab");
        if (!bin || !idx) {
            if (bin) fclose(bin);
            if (idx) fclose(idx);
            err = "cannot write the chunk store";
            return false;
        }
        for (const ContentChunk* c : g.chunks) {
            plain.clear();
            plain.reserve((size_t)c->length);
            uint64_t produced = 0;
            std::string ierr;
            bool ok = InflateDecompress(reinterpret_cast<const unsigned char*>(body.data()) + (c->offset - g.first),
                                        (size_t)c->clen, c->length,
                                        [&](const unsigned char* d, size_t n) {
                                            plain.append(reinterpret_cast<const char*>(d), n);
                                            return true;
                                        },
                                        &produced, ierr);
            if (!ok || plain.size() != c->length || Sha256Hex(plain.data(), plain.size()) != c->sha256) {
                fclose(bin);
                fclose(idx);
                err = "a downloaded chunk failed verification (" + c->sha256.substr(0, 12) + ")";
                return false;
            }
#ifdef _WIN32
            _fseeki64(bin, 0, SEEK_END);
#else
            fseeko(bin, 0, SEEK_END);
#endif
            uint64_t off = TellFile64(bin);
            fwrite(plain.data(), 1, plain.size(), bin);
            fprintf(idx, "%s %llu %llu\n", c->sha256.c_str(), (unsigned long long)off, (unsigned long long)plain.size());
            stored.emplace(c->sha256, Ref{storeBin, off, (uint64_t)plain.size()});
        }
        fflush(bin);
        fflush(idx);
        fclose(bin);
        fclose(idx);
        done += body.size();
        if (cb.progress) cb.progress(done, totalBytes);
    }

    // 6. Assemble every file, then prove it byte-for-byte.
    for (const auto& f : index.files) {
        if (stop()) return cancelled = true, false;
        std::wstring dest = NativePath(stagedDir, f.path);
        size_t slash = dest.find_last_of(kPathSep);
        if (slash != std::wstring::npos) CreateDirs(dest.substr(0, slash));
        if (wholeOk.count(f.sha256)) {
            if (!CopyFilePlain(wholeSource[f.sha256], dest)) {
                err = "cannot copy " + f.path + " from the installed version";
                return false;
            }
            stats.reusedBytes += f.size;
        } else {
            FILE* out = OpenFileW(dest, L"wb");
            if (!out) {
                err = "cannot create " + f.path;
                return false;
            }
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
                if (!ref || !ReadAt(ref->path, ref->offset, ref->length, buf) ||
                    fwrite(buf.data(), 1, buf.size(), out) != buf.size()) {
                    fclose(out);
                    err = "cannot assemble " + f.path;
                    return false;
                }
            }
            fclose(out);
        }
        unsigned char digest[32];
        uint64_t size = 0;
        std::string herr;
        if (!Sha256File(dest, digest, &size, herr) || HexLower(digest, 32) != f.sha256 || size != f.size) {
            err = "assembled " + f.path + " does not match the content index";
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
