// Small anti-aliased software painter for the SDL launcher UI (Linux/macOS).
//
// Draws into an opaque RGBA8 canvas (byte order R,G,B,A = SDL_PIXELFORMAT_RGBA32)
// that the shell uploads to a texture; the same canvas is written to PNG for
// headless screenshots. It covers exactly what the GDI+ launcher design uses:
// rounded rectangles, linear gradients, circles, lines, a diamond, clipping,
// a cover-scaled JPEG and TrueType text (stb_truetype) with alignment,
// ellipsis and word wrap.
#pragma once

#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <vector>

namespace hpmmo {
namespace paint {

struct Color {
    uint8_t r = 0, g = 0, b = 0, a = 255;
    Color() = default;
    // Same argument order as Gdiplus::Color(a, r, g, b).
    constexpr Color(uint8_t a_, uint8_t r_, uint8_t g_, uint8_t b_) : r(r_), g(g_), b(b_), a(a_) {}
    Color WithAlpha(uint8_t na) const { return Color(na, r, g, b); }
};

struct RectF {
    float x = 0, y = 0, w = 0, h = 0;
    RectF() = default;
    RectF(float x_, float y_, float w_, float h_) : x(x_), y(y_), w(w_), h(h_) {}
    bool Contains(float px, float py) const { return px >= x && py >= y && px < x + w && py < y + h; }
};

// Colour as a function of the pixel centre (solid colours and gradients).
using Fill = std::function<Color(float x, float y)>;
Fill Solid(Color c);
// Linear gradient from (x0,y0) to (x1,y1) through evenly given stops; clamped.
Fill Linear(float x0, float y0, float x1, float y1, std::vector<std::pair<float, Color>> stops);

struct Image {
    int w = 0, h = 0;
    std::vector<uint8_t> rgba;
    bool Decode(const void* data, size_t size);
};

class Font {
public:
    bool Load(const void* data, size_t size);
    bool ok() const { return ok_; }
    // Pixel em size like Gdiplus::Font(..., UnitPixel).
    float Advance(uint32_t cp, float px) const;
    float Kern(uint32_t a, uint32_t b, float px) const;
    float Ascent(float px) const;
    float LineHeight(float px) const;
    struct Glyph {
        int w = 0, h = 0, xoff = 0, yoff = 0;
        std::vector<uint8_t> alpha;
    };
    const Glyph& GetGlyph(uint32_t cp, float px) const;

private:
    struct Impl;
    std::shared_ptr<Impl> impl_;
    bool ok_ = false;
};

enum class Align { Near, Center, Far };

struct TextStyle {
    const Font* font = nullptr;
    float px = 14;
    Align h = Align::Near;
    Align v = Align::Near;
    bool ellipsis = false;   // single line, "…" when it does not fit
    bool wrap = false;       // word wrap; the last visible line ends with "…"
};

class Canvas {
public:
    void Resize(int w, int h);
    int width() const { return w_; }
    int height() const { return h_; }
    uint8_t* data() { return px_.data(); }
    const uint8_t* data() const { return px_.data(); }
    void CopyFrom(const Canvas& other) { px_ = other.px_; w_ = other.w_; h_ = other.h_; }

    void SetClip(const RectF& r);
    void ResetClip();

    void Clear(Color c);
    void FillRect(const RectF& r, const Fill& fill);
    void FillRound(const RectF& r, float radius, const Fill& fill);
    void StrokeRound(const RectF& r, float radius, Color c, float width);
    void FillCircle(float cx, float cy, float radius, Color c);
    void Line(float x0, float y0, float x1, float y1, Color c, float width);
    void FillDiamond(float cx, float cy, float rx, float ry, Color c);
    // Scales `img` to cover the canvas, anchored at (ax, ay) in [0,1].
    void DrawCover(const Image& img, float ax, float ay);

    float MeasureText(const std::wstring& text, const Font& font, float px) const;
    void DrawText(const std::wstring& text, const RectF& box, const TextStyle& st, const Fill& fill);

    bool WritePng(const std::string& path) const;

private:
    void Blend(int x, int y, Color c, float coverage);
    template <typename CoverageFn>
    void Shade(float x0, float y0, float x1, float y1, const Fill& fill, CoverageFn cov);
    void DrawLine(const std::wstring& line, float x, float baseline, const Font& font, float px, const Fill& fill);

    int w_ = 0, h_ = 0;
    std::vector<uint8_t> px_;
    bool clip_ = false;
    RectF clipRect_;
};

}  // namespace paint
}  // namespace hpmmo
