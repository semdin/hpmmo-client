#include "json.h"

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace hpmmo {

namespace {

constexpr int kMaxDepth = 64;
constexpr size_t kMaxStringBytes = 4u * 1024 * 1024;

std::string ErrAt(size_t pos, const std::string& what) {
    return what + " at offset " + std::to_string(pos);
}

bool IsWs(unsigned char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\n';
}

void AppendUtf8(std::string& out, unsigned int cp) {
    if (cp <= 0x7F) {
        out.push_back((char)cp);
    } else if (cp <= 0x7FF) {
        out.push_back((char)(0xC0 | (cp >> 6)));
        out.push_back((char)(0x80 | (cp & 0x3F)));
    } else if (cp <= 0xFFFF) {
        out.push_back((char)(0xE0 | (cp >> 12)));
        out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back((char)(0x80 | (cp & 0x3F)));
    } else {
        out.push_back((char)(0xF0 | (cp >> 18)));
        out.push_back((char)(0x80 | ((cp >> 12) & 0x3F)));
        out.push_back((char)(0x80 | ((cp >> 6) & 0x3F)));
        out.push_back((char)(0x80 | (cp & 0x3F)));
    }
}

class Parser {
public:
    Parser(const std::string& s) : s_(s) {}

    bool Parse(JsonValue& out, std::string& err) {
        SkipWs();
        if (!ParseValue(out, 0, err)) return false;
        SkipWs();
        if (pos_ != s_.size()) {
            err = ErrAt(pos_, "trailing data");
            return false;
        }
        return true;
    }

private:
    void SkipWs() {
        while (pos_ < s_.size() && IsWs((unsigned char)s_[pos_])) pos_++;
    }

    bool Peek(char c) { return pos_ < s_.size() && s_[pos_] == c; }

    bool ParseValue(JsonValue& out, int depth, std::string& err) {
        if (depth > kMaxDepth) {
            err = ErrAt(pos_, "nesting too deep");
            return false;
        }
        if (pos_ >= s_.size()) {
            err = ErrAt(pos_, "unexpected end of input");
            return false;
        }
        char c = s_[pos_];
        switch (c) {
            case '{': return ParseObject(out, depth, err);
            case '[': return ParseArray(out, depth, err);
            case '"': {
                std::string str;
                if (!ParseString(str, err)) return false;
                out = JsonValue::Str(str);
                return true;
            }
            case 't':
                if (s_.compare(pos_, 4, "true") == 0) {
                    pos_ += 4;
                    out = JsonValue::Bool(true);
                    return true;
                }
                err = ErrAt(pos_, "invalid literal");
                return false;
            case 'f':
                if (s_.compare(pos_, 5, "false") == 0) {
                    pos_ += 5;
                    out = JsonValue::Bool(false);
                    return true;
                }
                err = ErrAt(pos_, "invalid literal");
                return false;
            case 'n':
                if (s_.compare(pos_, 4, "null") == 0) {
                    pos_ += 4;
                    out = JsonValue::Null();
                    return true;
                }
                err = ErrAt(pos_, "invalid literal");
                return false;
            default: return ParseNumber(out, err);
        }
    }

    bool ParseObject(JsonValue& out, int depth, std::string& err) {
        pos_++;  // '{'
        out = JsonValue::Obj();
        SkipWs();
        if (Peek('}')) {
            pos_++;
            return true;
        }
        while (true) {
            SkipWs();
            if (!Peek('"')) {
                err = ErrAt(pos_, "expected object key");
                return false;
            }
            std::string key;
            if (!ParseString(key, err)) return false;
            SkipWs();
            if (!Peek(':')) {
                err = ErrAt(pos_, "expected ':'");
                return false;
            }
            pos_++;
            SkipWs();
            JsonValue v;
            if (!ParseValue(v, depth + 1, err)) return false;
            out.set(key, std::move(v));
            SkipWs();
            if (Peek(',')) {
                pos_++;
                continue;
            }
            if (Peek('}')) {
                pos_++;
                return true;
            }
            err = ErrAt(pos_, "expected ',' or '}'");
            return false;
        }
    }

    bool ParseArray(JsonValue& out, int depth, std::string& err) {
        pos_++;  // '['
        out = JsonValue::Arr();
        SkipWs();
        if (Peek(']')) {
            pos_++;
            return true;
        }
        while (true) {
            SkipWs();
            JsonValue v;
            if (!ParseValue(v, depth + 1, err)) return false;
            out.push(std::move(v));
            SkipWs();
            if (Peek(',')) {
                pos_++;
                continue;
            }
            if (Peek(']')) {
                pos_++;
                return true;
            }
            err = ErrAt(pos_, "expected ',' or ']'");
            return false;
        }
    }

    bool ParseHex4(unsigned int& out, std::string& err) {
        if (pos_ + 4 > s_.size()) {
            err = ErrAt(pos_, "truncated \\u escape");
            return false;
        }
        unsigned int v = 0;
        for (int i = 0; i < 4; i++) {
            char c = s_[pos_ + i];
            v <<= 4;
            if (c >= '0' && c <= '9') v |= (unsigned int)(c - '0');
            else if (c >= 'a' && c <= 'f') v |= (unsigned int)(c - 'a' + 10);
            else if (c >= 'A' && c <= 'F') v |= (unsigned int)(c - 'A' + 10);
            else {
                err = ErrAt(pos_ + i, "invalid hex digit");
                return false;
            }
        }
        pos_ += 4;
        out = v;
        return true;
    }

    bool ParseString(std::string& out, std::string& err) {
        out.clear();
        pos_++;  // '"'
        while (true) {
            if (pos_ >= s_.size()) {
                err = ErrAt(pos_, "unterminated string");
                return false;
            }
            unsigned char c = (unsigned char)s_[pos_];
            if (c == '"') {
                pos_++;
                return true;
            }
            if (c == '\\') {
                pos_++;
                if (pos_ >= s_.size()) {
                    err = ErrAt(pos_, "unterminated escape");
                    return false;
                }
                char e = s_[pos_++];
                switch (e) {
                    case '"': out.push_back('"'); break;
                    case '\\': out.push_back('\\'); break;
                    case '/': out.push_back('/'); break;
                    case 'b': out.push_back('\b'); break;
                    case 'f': out.push_back('\f'); break;
                    case 'n': out.push_back('\n'); break;
                    case 'r': out.push_back('\r'); break;
                    case 't': out.push_back('\t'); break;
                    case 'u': {
                        unsigned int cp = 0;
                        if (!ParseHex4(cp, err)) return false;
                        if (cp >= 0xD800 && cp <= 0xDBFF) {
                            // High surrogate: needs a low surrogate.
                            if (pos_ + 1 < s_.size() && s_[pos_] == '\\' && s_[pos_ + 1] == 'u') {
                                pos_ += 2;
                                unsigned int lo = 0;
                                if (!ParseHex4(lo, err)) return false;
                                if (lo >= 0xDC00 && lo <= 0xDFFF) {
                                    cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
                                } else {
                                    AppendUtf8(out, 0xFFFD);
                                    cp = lo;
                                }
                            } else {
                                cp = 0xFFFD;
                            }
                        } else if (cp >= 0xDC00 && cp <= 0xDFFF) {
                            cp = 0xFFFD;
                        }
                        AppendUtf8(out, cp);
                        break;
                    }
                    default:
                        err = ErrAt(pos_ - 1, "invalid escape");
                        return false;
                }
                if (out.size() > kMaxStringBytes) {
                    err = "string too large";
                    return false;
                }
                continue;
            }
            if (c < 0x20) {
                err = ErrAt(pos_, "raw control character in string");
                return false;
            }
            out.push_back((char)c);
            pos_++;
            if (out.size() > kMaxStringBytes) {
                err = "string too large";
                return false;
            }
        }
    }

    bool ParseNumber(JsonValue& out, std::string& err) {
        size_t start = pos_;
        if (Peek('-')) pos_++;
        if (pos_ >= s_.size() || !std::isdigit((unsigned char)s_[pos_])) {
            err = ErrAt(start, "invalid value");
            return false;
        }
        if (s_[pos_] == '0') {
            pos_++;
        } else {
            while (pos_ < s_.size() && std::isdigit((unsigned char)s_[pos_])) pos_++;
        }
        bool isDouble = false;
        if (Peek('.')) {
            isDouble = true;
            pos_++;
            if (pos_ >= s_.size() || !std::isdigit((unsigned char)s_[pos_])) {
                err = ErrAt(pos_, "invalid fraction");
                return false;
            }
            while (pos_ < s_.size() && std::isdigit((unsigned char)s_[pos_])) pos_++;
        }
        if (Peek('e') || Peek('E')) {
            isDouble = true;
            pos_++;
            if (Peek('+') || Peek('-')) pos_++;
            if (pos_ >= s_.size() || !std::isdigit((unsigned char)s_[pos_])) {
                err = ErrAt(pos_, "invalid exponent");
                return false;
            }
            while (pos_ < s_.size() && std::isdigit((unsigned char)s_[pos_])) pos_++;
        }
        std::string tok = s_.substr(start, pos_ - start);
        if (!isDouble) {
            errno = 0;
            char* end = nullptr;
            long long v = std::strtoll(tok.c_str(), &end, 10);
            if (errno == 0 && end && *end == '\0') {
                out = JsonValue::Int((int64_t)v);
                return true;
            }
        }
        out = JsonValue::Double(std::strtod(tok.c_str(), nullptr));
        return true;
    }

    const std::string& s_;
    size_t pos_ = 0;
};

}  // namespace

JsonValue JsonValue::Bool(bool v) {
    JsonValue j;
    j.type_ = Type::Bool;
    j.bool_ = v;
    return j;
}
JsonValue JsonValue::Int(int64_t v) {
    JsonValue j;
    j.type_ = Type::Int;
    j.int_ = v;
    return j;
}
JsonValue JsonValue::Double(double v) {
    JsonValue j;
    j.type_ = Type::Double;
    j.double_ = v;
    return j;
}
JsonValue JsonValue::Str(const std::string& v) {
    JsonValue j;
    j.type_ = Type::String;
    j.string_ = v;
    return j;
}
JsonValue JsonValue::Arr() {
    JsonValue j;
    j.type_ = Type::Array;
    return j;
}
JsonValue JsonValue::Obj() {
    JsonValue j;
    j.type_ = Type::Object;
    return j;
}

bool JsonValue::asBool(bool def) const {
    if (type_ == Type::Bool) return bool_;
    if (type_ == Type::Int) return int_ != 0;
    return def;
}
int64_t JsonValue::asInt64(int64_t def) const {
    if (type_ == Type::Int) return int_;
    if (type_ == Type::Double) return (int64_t)double_;
    return def;
}
double JsonValue::asDouble(double def) const {
    if (type_ == Type::Double) return double_;
    if (type_ == Type::Int) return (double)int_;
    return def;
}
const std::string& JsonValue::asString() const {
    static const std::string kEmpty;
    return type_ == Type::String ? string_ : kEmpty;
}

void JsonValue::set(const std::string& key, JsonValue v) {
    type_ = Type::Object;
    object_[key] = std::move(v);
}
bool JsonValue::has(const std::string& key) const {
    return type_ == Type::Object && object_.count(key) != 0;
}
const JsonValue* JsonValue::find(const std::string& key) const {
    if (type_ != Type::Object) return nullptr;
    auto it = object_.find(key);
    return it == object_.end() ? nullptr : &it->second;
}
std::string JsonValue::str(const std::string& key, const std::string& def) const {
    const JsonValue* v = find(key);
    return (v && v->type_ == Type::String) ? v->string_ : def;
}
int64_t JsonValue::i64(const std::string& key, int64_t def) const {
    const JsonValue* v = find(key);
    return (v && v->isNumber()) ? v->asInt64() : def;
}
bool JsonValue::boolean(const std::string& key, bool def) const {
    const JsonValue* v = find(key);
    return (v && v->type_ == Type::Bool) ? v->bool_ : def;
}
const std::vector<JsonValue>* JsonValue::arr(const std::string& key) const {
    const JsonValue* v = find(key);
    return (v && v->type_ == Type::Array) ? &v->array_ : nullptr;
}
void JsonValue::push(JsonValue v) {
    type_ = Type::Array;
    array_.push_back(std::move(v));
}

bool JsonValue::Parse(const std::string& text, JsonValue& out, std::string& err) {
    Parser p(text);
    return p.Parse(out, err);
}

void JsonValue::DumpTo(std::string& out) const {
    switch (type_) {
        case Type::Null: out += "null"; break;
        case Type::Bool: out += bool_ ? "true" : "false"; break;
        case Type::Int: {
            char buf[32];
            snprintf(buf, sizeof(buf), "%lld", (long long)int_);
            out += buf;
            break;
        }
        case Type::Double: {
            char buf[64];
            if (std::isfinite(double_) && double_ == (double)(int64_t)double_) {
                snprintf(buf, sizeof(buf), "%lld", (long long)double_);
            } else {
                snprintf(buf, sizeof(buf), "%.17g", double_);
            }
            out += buf;
            break;
        }
        case Type::String: {
            out += '"';
            for (unsigned char c : string_) {
                switch (c) {
                    case '"': out += "\\\""; break;
                    case '\\': out += "\\\\"; break;
                    case '\b': out += "\\b"; break;
                    case '\f': out += "\\f"; break;
                    case '\n': out += "\\n"; break;
                    case '\r': out += "\\r"; break;
                    case '\t': out += "\\t"; break;
                    default:
                        if (c < 0x20) {
                            char buf[8];
                            snprintf(buf, sizeof(buf), "\\u%04x", c);
                            out += buf;
                        } else {
                            out.push_back((char)c);
                        }
                }
            }
            out += '"';
            break;
        }
        case Type::Array: {
            out += '[';
            for (size_t i = 0; i < array_.size(); i++) {
                if (i) out += ',';
                array_[i].DumpTo(out);
            }
            out += ']';
            break;
        }
        case Type::Object: {
            out += '{';
            bool first = true;
            for (const auto& kv : object_) {
                if (!first) out += ',';
                first = false;
                JsonValue::Str(kv.first).DumpTo(out);
                out += ':';
                kv.second.DumpTo(out);
            }
            out += '}';
            break;
        }
    }
}

std::string JsonValue::Dump() const {
    std::string out;
    DumpTo(out);
    return out;
}

}  // namespace hpmmo
