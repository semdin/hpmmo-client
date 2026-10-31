#include "painter.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_JPEG
#define STBI_ONLY_PNG
#define STBI_NO_STDIO
#include "stb_image.h"
#define STB_TRUETYPE_IMPLEMENTATION
#include "stb_truetype.h"
#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

namespace hpmmo {
namespace paint {

namespace {

inline float Clamp01(float v) { return v < 0.0f ? 0.0f : (v > 1.0f ? 1.0f : v); }

inline uint8_t Lerp8(uint8_t a, uint8_t b, float t) { return (uint8_t)std::lround(a + (b - a) * t); }

Color LerpColor(Color a, Color b, float t) {
    return Color(Lerp8(a.a, b.a, t), Lerp8(a.r, b.r, t), Lerp8(a.g, b.g, t), Lerp8(a.b, b.b, t));
}

// Signed distance to a rounded rectangle (negative inside).
float RoundRectSdf(const RectF& r, float radius, float px, float py) {
    float hw = r.w * 0.5f, hh = r.h * 0.5f;
    float rad = std::min(radius, std::min(hw, hh));
    float qx = std::fabs(px - (r.x + hw)) - (hw - rad);
    float qy = std::fabs(py - (r.y + hh)) - (hh - rad);
    float ox = std::max(qx, 0.0f), oy = std::max(qy, 0.0f);
    return std::sqrt(ox * ox + oy * oy) + std::min(std::max(qx, qy), 0.0f) - rad;
}

}  // namespace

Fill Solid(Color c) {
    return [c](float, float) { return c; };
}

Fill Linear(float x0, float y0, float x1, float y1, std::vector<std::pair<float, Color>> stops) {
    float dx = x1 - x0, dy = y1 - y0;
    float len2 = dx * dx + dy * dy;
    if (len2 < 1e-6f) len2 = 1e-6f;
    return [=](float x, float y) {
        float t = Clamp01(((x - x0) * dx + (y - y0) * dy) / len2);
        if (t <= stops.front().first) return stops.front().second;
        for (size_t i = 1; i < stops.size(); i++) {
            if (t <= stops[i].first) {
                float span = stops[i].first - stops[i - 1].first;
                float k = span > 0 ? (t - stops[i - 1].first) / span : 1.0f;
                return LerpColor(stops[i - 1].second, stops[i].second, k);
            }
        }
        return stops.back().second;
    };
}

// ------------------------------------------------------------------ image
bool Image::Decode(const void* data, size_t size) {
    int n = 0;
    unsigned char* p = stbi_load_from_memory((const stbi_uc*)data, (int)size, &w, &h, &n, 4);
    if (!p) return false;
    rgba.assign(p, p + (size_t)w * h * 4);
    stbi_image_free(p);
    return true;
}

// ------------------------------------------------------------------- font
struct Font::Impl {
    std::vector<unsigned char> data;
    stbtt_fontinfo info;
    mutable std::map<std::pair<uint32_t, int>, Glyph> cache;
};

bool Font::Load(const void* data, size_t size) {
    impl_ = std::make_shared<Impl>();
    impl_->data.assign((const unsigned char*)data, (const unsigned char*)data + size);
    ok_ = stbtt_InitFont(&impl_->info, impl_->data.data(), stbtt_GetFontOffsetForIndex(impl_->data.data(), 0)) != 0;
    return ok_;
}

float Font::Advance(uint32_t cp, float px) const {
    int adv = 0, lsb = 0;
    stbtt_GetCodepointHMetrics(&impl_->info, (int)cp, &adv, &lsb);
    return adv * stbtt_ScaleForMappingEmToPixels(&impl_->info, px);
}

float Font::Kern(uint32_t a, uint32_t b, float px) const {
    return stbtt_GetCodepointKernAdvance(&impl_->info, (int)a, (int)b) * stbtt_ScaleForMappingEmToPixels(&impl_->info, px);
}

float Font::Ascent(float px) const {
    int asc = 0, desc = 0, gap = 0;
    stbtt_GetFontVMetrics(&impl_->info, &asc, &desc, &gap);
    return asc * stbtt_ScaleForMappingEmToPixels(&impl_->info, px);
}

float Font::LineHeight(float px) const {
    int asc = 0, desc = 0, gap = 0;
    stbtt_GetFontVMetrics(&impl_->info, &asc, &desc, &gap);
    return (asc - desc + gap) * stbtt_ScaleForMappingEmToPixels(&impl_->info, px);
}

const Font::Glyph& Font::GetGlyph(uint32_t cp, float px) const {
    auto key = std::make_pair(cp, (int)std::lround(px * 16.0f));
    auto it = impl_->cache.find(key);
    if (it != impl_->cache.end()) return it->second;
    Glyph g;
    float scale = stbtt_ScaleForMappingEmToPixels(&impl_->info, px);
    unsigned char* bmp = stbtt_GetCodepointBitmap(&impl_->info, scale, scale, (int)cp, &g.w, &g.h, &g.xoff, &g.yoff);
    if (bmp) {
        g.alpha.assign(bmp, bmp + (size_t)g.w * g.h);
        stbtt_FreeBitmap(bmp, nullptr);
    }
    return impl_->cache.emplace(key, std::move(g)).first->second;
}

// ----------------------------------------------------------------- canvas
void Canvas::Resize(int w, int h) {
    w_ = w;
    h_ = h;
    px_.assign((size_t)w * h * 4, 255);
}

void Canvas::SetClip(const RectF& r) {
    clip_ = true;
    clipRect_ = r;
}

void Canvas::ResetClip() { clip_ = false; }

void Canvas::Clear(Color c) {
    for (size_t i = 0; i < px_.size(); i += 4) {
        px_[i] = c.r;
        px_[i + 1] = c.g;
        px_[i + 2] = c.b;
        px_[i + 3] = 255;
    }
}

void Canvas::Blend(int x, int y, Color c, float coverage) {
    float a = (c.a / 255.0f) * coverage;
    if (a <= 0.0f) return;
    uint8_t* p = &px_[((size_t)y * w_ + x) * 4];
    float ia = 1.0f - a;
    p[0] = (uint8_t)(c.r * a + p[0] * ia + 0.5f);
    p[1] = (uint8_t)(c.g * a + p[1] * ia + 0.5f);
    p[2] = (uint8_t)(c.b * a + p[2] * ia + 0.5f);
}

template <typename CoverageFn>
void Canvas::Shade(float x0, float y0, float x1, float y1, const Fill& fill, CoverageFn cov) {
    if (clip_) {
        x0 = std::max(x0, clipRect_.x);
        y0 = std::max(y0, clipRect_.y);
        x1 = std::min(x1, clipRect_.x + clipRect_.w);
        y1 = std::min(y1, clipRect_.y + clipRect_.h);
    }
    int ix0 = std::max(0, (int)std::floor(x0)), iy0 = std::max(0, (int)std::floor(y0));
    int ix1 = std::min(w_, (int)std::ceil(x1)), iy1 = std::min(h_, (int)std::ceil(y1));
    for (int y = iy0; y < iy1; y++) {
        for (int x = ix0; x < ix1; x++) {
            float cx = x + 0.5f, cy = y + 0.5f;
            float c = cov(cx, cy, x, y);
            if (c <= 0.0f) continue;
            Blend(x, y, fill(cx, cy), std::min(c, 1.0f));
        }
    }
}

void Canvas::FillRect(const RectF& r, const Fill& fill) {
    Shade(r.x, r.y, r.x + r.w, r.y + r.h, fill, [&](float, float, int x, int y) {
        float cx = std::min((float)x + 1, r.x + r.w) - std::max((float)x, r.x);
        float cy = std::min((float)y + 1, r.y + r.h) - std::max((float)y, r.y);
        return Clamp01(cx) * Clamp01(cy);
    });
}

void Canvas::FillRound(const RectF& r, float radius, const Fill& fill) {
    Shade(r.x - 1, r.y - 1, r.x + r.w + 1, r.y + r.h + 1, fill,
          [&](float cx, float cy, int, int) { return Clamp01(0.5f - RoundRectSdf(r, radius, cx, cy)); });
}

void Canvas::StrokeRound(const RectF& r, float radius, Color c, float width) {
    float half = width * 0.5f;
    Shade(r.x - half - 1, r.y - half - 1, r.x + r.w + half + 1, r.y + r.h + half + 1, Solid(c),
          [&](float cx, float cy, int, int) {
              return Clamp01(half + 0.5f - std::fabs(RoundRectSdf(r, radius, cx, cy)));
          });
}

void Canvas::FillCircle(float cx0, float cy0, float radius, Color c) {
    Shade(cx0 - radius - 1, cy0 - radius - 1, cx0 + radius + 1, cy0 + radius + 1, Solid(c),
          [&](float cx, float cy, int, int) {
              float d = std::sqrt((cx - cx0) * (cx - cx0) + (cy - cy0) * (cy - cy0)) - radius;
              return Clamp01(0.5f - d);
          });
}

void Canvas::Line(float x0, float y0, float x1, float y1, Color c, float width) {
    float half = width * 0.5f;
    float dx = x1 - x0, dy = y1 - y0;
    float len2 = std::max(dx * dx + dy * dy, 1e-6f);
    Shade(std::min(x0, x1) - half - 1, std::min(y0, y1) - half - 1, std::max(x0, x1) + half + 1,
          std::max(y0, y1) + half + 1, Solid(c), [&](float cx, float cy, int, int) {
              float t = Clamp01(((cx - x0) * dx + (cy - y0) * dy) / len2);
              float px = x0 + dx * t - cx, py = y0 + dy * t - cy;
              return Clamp01(half + 0.5f - std::sqrt(px * px + py * py));
          });
}

void Canvas::FillDiamond(float cx0, float cy0, float rx, float ry, Color c) {
    float m = std::min(rx, ry);
    Shade(cx0 - rx - 1, cy0 - ry - 1, cx0 + rx + 1, cy0 + ry + 1, Solid(c), [&](float cx, float cy, int, int) {
        float d = (std::fabs(cx - cx0) / rx + std::fabs(cy - cy0) / ry - 1.0f) * m * 0.7071f;
        return Clamp01(0.5f - d);
    });
}

void Canvas::DrawCover(const Image& img, float ax, float ay) {
    if (img.w <= 0 || img.h <= 0) return;
    float scale = std::max((float)w_ / img.w, (float)h_ / img.h);
    float dw = img.w * scale, dh = img.h * scale;
    float dx = (w_ - dw) * ax, dy = (h_ - dh) * ay;
    // Downscaling: average a few bilinear taps per pixel (GDI+ used bicubic).
    int taps = scale < 0.75f ? 3 : 1;
    auto sample = [&](float sx, float sy, float out[3]) {
        sx = std::min(std::max(sx, 0.0f), (float)img.w - 1.001f);
        sy = std::min(std::max(sy, 0.0f), (float)img.h - 1.001f);
        int x = (int)sx, y = (int)sy;
        float fx = sx - x, fy = sy - y;
        const uint8_t* p00 = &img.rgba[((size_t)y * img.w + x) * 4];
        const uint8_t* p10 = p00 + 4;
        const uint8_t* p01 = p00 + (size_t)img.w * 4;
        const uint8_t* p11 = p01 + 4;
        for (int k = 0; k < 3; k++) {
            float a = p00[k] + (p10[k] - p00[k]) * fx;
            float b = p01[k] + (p11[k] - p01[k]) * fx;
            out[k] += a + (b - a) * fy;
        }
    };
    for (int y = 0; y < h_; y++) {
        for (int x = 0; x < w_; x++) {
            float acc[3] = {0, 0, 0};
            for (int ty = 0; ty < taps; ty++)
                for (int tx = 0; tx < taps; tx++) {
                    float px = x + (tx + 0.5f) / taps, py = y + (ty + 0.5f) / taps;
                    sample((px - dx) / scale - 0.5f, (py - dy) / scale - 0.5f, acc);
                }
            uint8_t* p = &px_[((size_t)y * w_ + x) * 4];
            float n = (float)(taps * taps);
            for (int k = 0; k < 3; k++) p[k] = (uint8_t)std::min(255.0f, acc[k] / n + 0.5f);
            p[3] = 255;
        }
    }
}

void Canvas::DrawImage(const Image& img, const RectF& dst) {
    if (img.w <= 0 || img.h <= 0 || dst.w <= 0 || dst.h <= 0) return;
    float scale = dst.w / img.w;
    int taps = scale < 0.75f ? 3 : 1;
    int x0 = std::max(0, (int)std::floor(dst.x)), x1 = std::min(w_, (int)std::ceil(dst.x + dst.w));
    int y0 = std::max(0, (int)std::floor(dst.y)), y1 = std::min(h_, (int)std::ceil(dst.y + dst.h));
    if (clip_) {
        x0 = std::max(x0, (int)clipRect_.x);
        y0 = std::max(y0, (int)clipRect_.y);
        x1 = std::min(x1, (int)(clipRect_.x + clipRect_.w));
        y1 = std::min(y1, (int)(clipRect_.y + clipRect_.h));
    }
    // Bilinear taps in premultiplied colour, so transparent texels add no fringe.
    auto sample = [&](float sx, float sy, float out[4]) {
        sx = std::min(std::max(sx, 0.0f), (float)img.w - 1.001f);
        sy = std::min(std::max(sy, 0.0f), (float)img.h - 1.001f);
        int x = (int)sx, y = (int)sy;
        float fx = sx - x, fy = sy - y;
        const uint8_t* p[4] = {&img.rgba[((size_t)y * img.w + x) * 4], nullptr, nullptr, nullptr};
        p[1] = p[0] + 4;
        p[2] = p[0] + (size_t)img.w * 4;
        p[3] = p[2] + 4;
        float wgt[4] = {(1 - fx) * (1 - fy), fx * (1 - fy), (1 - fx) * fy, fx * fy};
        for (int i = 0; i < 4; i++) {
            float a = p[i][3] * wgt[i];
            out[0] += p[i][0] * a;
            out[1] += p[i][1] * a;
            out[2] += p[i][2] * a;
            out[3] += a;
        }
    };
    for (int y = y0; y < y1; y++) {
        for (int x = x0; x < x1; x++) {
            float acc[4] = {0, 0, 0, 0};
            for (int ty = 0; ty < taps; ty++)
                for (int tx = 0; tx < taps; tx++) {
                    float px = x + (tx + 0.5f) / taps, py = y + (ty + 0.5f) / taps;
                    sample((px - dst.x) / scale - 0.5f, (py - dst.y) / scale - 0.5f, acc);
                }
            if (acc[3] <= 0.0f) continue;
            float n = (float)(taps * taps);
            Color c((uint8_t)std::min(255.0f, acc[3] / n + 0.5f), (uint8_t)std::min(255.0f, acc[0] / acc[3] + 0.5f),
                    (uint8_t)std::min(255.0f, acc[1] / acc[3] + 0.5f), (uint8_t)std::min(255.0f, acc[2] / acc[3] + 0.5f));
            Blend(x, y, c, 1.0f);
        }
    }
}

// ------------------------------------------------------------------- text
float Canvas::MeasureText(const std::wstring& text, const Font& font, float px) const {
    float w = 0;
    for (size_t i = 0; i < text.size(); i++) {
        w += font.Advance((uint32_t)text[i], px);
        if (i + 1 < text.size()) w += font.Kern((uint32_t)text[i], (uint32_t)text[i + 1], px);
    }
    return w;
}

void Canvas::DrawLine(const std::wstring& line, float x, float baseline, const Font& font, float px,
                      const Fill& fill) {
    float pen = x;
    for (size_t i = 0; i < line.size(); i++) {
        uint32_t cp = (uint32_t)line[i];
        const Font::Glyph& g = font.GetGlyph(cp, px);
        int gx = (int)std::lround(pen) + g.xoff, gy = (int)std::lround(baseline) + g.yoff;
        for (int yy = 0; yy < g.h; yy++) {
            int y = gy + yy;
            if (y < 0 || y >= h_) continue;
            if (clip_ && (y + 0.5f < clipRect_.y || y + 0.5f >= clipRect_.y + clipRect_.h)) continue;
            for (int xx = 0; xx < g.w; xx++) {
                int x2 = gx + xx;
                if (x2 < 0 || x2 >= w_) continue;
                if (clip_ && (x2 + 0.5f < clipRect_.x || x2 + 0.5f >= clipRect_.x + clipRect_.w)) continue;
                uint8_t a = g.alpha[(size_t)yy * g.w + xx];
                if (a) Blend(x2, y, fill(x2 + 0.5f, y + 0.5f), a / 255.0f);
            }
        }
        pen += font.Advance(cp, px);
        if (i + 1 < line.size()) pen += font.Kern(cp, (uint32_t)line[i + 1], px);
    }
}

void Canvas::DrawText(const std::wstring& text, const RectF& box, const TextStyle& st, const Fill& fill) {
    if (!st.font || !st.font->ok() || text.empty()) return;
    const Font& font = *st.font;
    // GDI+ DrawString keeps ~1/6 em of padding at both line ends.
    float pad = st.px / 6.0f;
    float avail = std::max(0.0f, box.w - 2 * pad);
    const std::wstring ell = L"…";

    auto fitEllipsis = [&](std::wstring s) {   // character-wise (StringTrimmingEllipsisCharacter)
        while (!s.empty() && MeasureText(s + ell, font, st.px) > avail) s.pop_back();
        while (!s.empty() && s.back() == L' ') s.pop_back();
        return s + ell;
    };

    std::vector<std::wstring> lines;
    float lh = font.LineHeight(st.px);
    if (st.wrap) {
        // Wrap every paragraph, then keep what fits; the last kept line ends
        // with an ellipsis at a word boundary when text was cut
        // (StringTrimmingEllipsisWord).
        std::vector<std::wstring> all;
        size_t start = 0;
        while (start <= text.size()) {
            size_t nl = text.find(L'\n', start);
            std::wstring para = text.substr(start, nl == std::wstring::npos ? std::wstring::npos : nl - start);
            std::wstring line;
            size_t pos = 0;
            while (pos <= para.size()) {
                size_t sp = para.find(L' ', pos);
                std::wstring word = para.substr(pos, sp == std::wstring::npos ? std::wstring::npos : sp - pos);
                std::wstring cand = line.empty() ? word : line + L" " + word;
                if (!line.empty() && MeasureText(cand, font, st.px) > avail) {
                    all.push_back(line);
                    line = word;
                } else {
                    line = cand;
                }
                if (sp == std::wstring::npos) break;
                pos = sp + 1;
            }
            all.push_back(line);
            if (nl == std::wstring::npos) break;
            start = nl + 1;
        }
        size_t maxLines = std::max<size_t>(1, (size_t)std::floor(box.h / lh));
        if (all.size() > maxLines) {
            all.resize(maxLines);
            // Drop whole words until "line…" fits.
            std::wstring s = all.back();
            while (!s.empty() && MeasureText(s + ell, font, st.px) > avail) {
                size_t sp = s.find_last_of(L' ');
                s = sp == std::wstring::npos ? s.substr(0, s.size() - 1) : s.substr(0, sp);
            }
            while (!s.empty() && s.back() == L' ') s.pop_back();
            all.back() = s + ell;
        }
        lines = std::move(all);
    } else {
        std::wstring line = text;
        if (st.ellipsis && MeasureText(line, font, st.px) > avail) line = fitEllipsis(line);
        lines.push_back(line);
    }

    float blockH = lh * lines.size();
    float y = box.y;
    if (st.v == Align::Center) y = box.y + (box.h - blockH) * 0.5f;
    if (st.v == Align::Far) y = box.y + box.h - blockH;
    float ascent = font.Ascent(st.px);
    for (const auto& line : lines) {
        float w = MeasureText(line, font, st.px);
        float x = box.x + pad;
        if (st.h == Align::Center) x = box.x + (box.w - w) * 0.5f;
        if (st.h == Align::Far) x = box.x + box.w - pad - w;
        DrawLine(line, x, y + ascent, font, st.px, fill);
        y += lh;
    }
}

bool Canvas::WritePng(const std::string& path) const {
    return stbi_write_png(path.c_str(), w_, h_, 4, px_.data(), w_ * 4) != 0;
}

}  // namespace paint
}  // namespace hpmmo
