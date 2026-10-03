// Minimal strict JSON parser/writer for the launcher updater.
// No external dependencies; supports the subset the release documents use.
#pragma once

#include <cstdint>
#include <map>
#include <string>
#include <vector>

namespace hpmmo {

class JsonValue {
public:
    enum class Type { Null, Bool, Int, Double, String, Array, Object };

    JsonValue() : type_(Type::Null) {}
    static JsonValue Null() { return JsonValue(); }
    static JsonValue Bool(bool v);
    static JsonValue Int(int64_t v);
    static JsonValue Double(double v);
    static JsonValue Str(const std::string& v);
    static JsonValue Arr();
    static JsonValue Obj();

    Type type() const { return type_; }
    bool isNull() const { return type_ == Type::Null; }
    bool isObject() const { return type_ == Type::Object; }
    bool isArray() const { return type_ == Type::Array; }
    bool isString() const { return type_ == Type::String; }
    bool isNumber() const { return type_ == Type::Int || type_ == Type::Double; }

    bool asBool(bool def = false) const;
    int64_t asInt64(int64_t def = 0) const;
    double asDouble(double def = 0.0) const;
    const std::string& asString() const;

    // Object helpers.
    void set(const std::string& key, JsonValue v);
    bool has(const std::string& key) const;
    const JsonValue* find(const std::string& key) const;
    std::string str(const std::string& key, const std::string& def = "") const;
    int64_t i64(const std::string& key, int64_t def = 0) const;
    bool boolean(const std::string& key, bool def = false) const;
    const std::vector<JsonValue>* arr(const std::string& key) const;

    // Array helpers.
    void push(JsonValue v);
    const std::vector<JsonValue>& items() const { return array_; }

    static bool Parse(const std::string& text, JsonValue& out, std::string& err);
    std::string Dump() const;

private:
    void DumpTo(std::string& out) const;

    Type type_;
    bool bool_ = false;
    int64_t int_ = 0;
    double double_ = 0.0;
    std::string string_;
    std::vector<JsonValue> array_;
    std::map<std::string, JsonValue> object_;
};

}  // namespace hpmmo
