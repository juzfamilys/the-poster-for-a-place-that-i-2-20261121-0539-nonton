#!/usr/bin/env python3
"""NIMBARA -- a travel poster for a place that isn't there.

Draws a vintage-style travel poster for NIMBARA, a chain of floating
islands drifting above a sea of clouds, crowned by a lighthouse that
guides airships home. Pure Python standard library only: the image is
painted pixel by pixel into an RGB buffer, the lettering comes from a
hand-built 5x7 bitmap font, and the PNG file is assembled by hand with
zlib + struct. No fonts, no image libraries, no network.

Output: /output/entry.png (768 x 1024, RGB PNG).
"""

import math
import os
import struct
import zlib

W, H = 768, 1024

# ---------------------------------------------------------------- palette
INK       = (24, 18, 52)      # deep indigo, outlines and shadows
CREAM     = (245, 233, 201)   # poster cream, title and frame
GOLD      = (255, 217, 122)   # sun and tagline
CORAL     = (224, 122, 95)    # horizon warmth
ROSE      = (138, 74, 125)    # dusk violet
SKY_TOP   = (20, 27, 61)
SKY_MID   = (59, 47, 107)
ROCK      = (88, 58, 102)
ROCK_DARK = (58, 38, 74)
GRASS     = (88, 176, 140)
GRASS_DK  = (58, 138, 108)
TOWER     = (250, 244, 224)
BAND_RED  = (198, 64, 64)
WATER     = (190, 224, 240)
CLOUD_A   = (247, 232, 255)
CLOUD_B   = (226, 205, 245)
CLOUD_C   = (196, 172, 228)

# Sky gradient stops: (fraction of height, colour)
SKY_STOPS = [
    (0.00, SKY_TOP),
    (0.30, SKY_MID),
    (0.50, ROSE),
    (0.62, CORAL),
    (0.68, (242, 166, 90)),
    (1.00, (42, 35, 80)),
]


def lerp(a, b, t):
    return a + (b - a) * t


def lerp_color(c1, c2, t):
    return (int(lerp(c1[0], c2[0], t)),
            int(lerp(c1[1], c2[1], t)),
            int(lerp(c1[2], c2[2], t)))


def sky_color(y):
    """Vertical sky gradient, sampled from SKY_STOPS."""
    f = y / (H - 1)
    for i in range(len(SKY_STOPS) - 1):
        f0, c0 = SKY_STOPS[i]
        f1, c1 = SKY_STOPS[i + 1]
        if f0 <= f <= f1:
            t = 0.0 if f1 == f0 else (f - f0) / (f1 - f0)
            return lerp_color(c0, c1, t)
    return SKY_STOPS[-1][1]


# ---------------------------------------------------------------- canvas
class Canvas:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.px = [bytearray(w * 3) for _ in range(h)]

    def set(self, x, y, color):
        if 0 <= x < self.w and 0 <= y < self.h:
            i = x * 3
            row = self.px[y]
            row[i] = color[0]
            row[i + 1] = color[1]
            row[i + 2] = color[2]

    def blend(self, x, y, color, alpha):
        """Paint color over the pixel with opacity alpha (0..1)."""
        if 0 <= x < self.w and 0 <= y < self.h and alpha > 0.0:
            i = x * 3
            row = self.px[y]
            a = max(0.0, min(1.0, alpha))
            row[i] = int(row[i] + (color[0] - row[i]) * a)
            row[i + 1] = int(row[i + 1] + (color[1] - row[i + 1]) * a)
            row[i + 2] = int(row[i + 2] + (color[2] - row[i + 2]) * a)

    def get(self, x, y):
        row = self.px[y]
        i = x * 3
        return (row[i], row[i + 1], row[i + 2])

    def rect(self, x0, y0, x1, y1, color, alpha=1.0):
        x0, x1 = max(0, x0), min(self.w - 1, x1)
        y0, y1 = max(0, y0), min(self.h - 1, y1)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                if alpha >= 1.0:
                    self.set(x, y, color)
                else:
                    self.blend(x, y, color, alpha)

    def disc(self, cx, cy, r, color, alpha=1.0):
        r2 = r * r
        for y in range(cy - r, cy + r + 1):
            dy = y - cy
            dx = int(math.sqrt(max(0, r2 - dy * dy)))
            for x in range(cx - dx, cx + dx + 1):
                if alpha >= 1.0:
                    self.set(x, y, color)
                else:
                    self.blend(x, y, color, alpha)

    def ellipse(self, cx, cy, rx, ry, color, alpha=1.0):
        for y in range(cy - ry, cy + ry + 1):
            dy = (y - cy) / ry
            rem = 1.0 - dy * dy
            if rem < 0:
                continue
            dx = int(rx * math.sqrt(rem))
            for x in range(cx - dx, cx + dx + 1):
                if alpha >= 1.0:
                    self.set(x, y, color)
                else:
                    self.blend(x, y, color, alpha)

    def line(self, x0, y0, x1, y1, color, width=1, alpha=1.0):
        """Simple Bresenham line with a square brush of `width`."""
        dx, dy = abs(x1 - x0), abs(y1 - y0)
        sx = 1 if x0 < x1 else -1
        sy = 1 if y0 < y1 else -1
        err = dx - dy
        x, y = x0, y0
        half = width // 2
        while True:
            for oy in range(-half, half + 1):
                for ox in range(-half, half + 1):
                    if alpha >= 1.0:
                        self.set(x + ox, y + oy, color)
                    else:
                        self.blend(x + ox, y + oy, color, alpha)
            if x == x1 and y == y1:
                break
            e2 = 2 * err
            if e2 > -dy:
                err -= dy
                x += sx
            if e2 < dx:
                err += dx
                y += sy

    def polygon(self, points, color, alpha=1.0):
        """Scanline fill of a simple polygon given as [(x, y), ...]."""
        if len(points) < 3:
            return
        ys = [p[1] for p in points]
        for y in range(max(0, min(ys)), min(self.h - 1, max(ys)) + 1):
            xs = []
            n = len(points)
            for i in range(n):
                x0, y0 = points[i]
                x1, y1 = points[(i + 1) % n]
                if (y0 <= y < y1) or (y1 <= y < y0):
                    t = (y - y0) / (y1 - y0)
                    xs.append(x0 + t * (x1 - x0))
            xs.sort()
            for k in range(0, len(xs) - 1, 2):
                xa, xb = int(math.ceil(xs[k])), int(math.floor(xs[k + 1]))
                for x in range(max(0, xa), min(self.w - 1, xb) + 1):
                    if alpha >= 1.0:
                        self.set(x, y, color)
                    else:
                        self.blend(x, y, color, alpha)


# ------------------------------------------------------- 5x7 bitmap font
# '#' is a set pixel, '.' is empty. Rows are top to bottom.
FONT = {
    'A': (" ### ", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    'B': ("#### ", "#   #", "#   #", "#### ", "#   #", "#   #", "#### "),
    'C': (" ####", "#    ", "#    ", "#    ", "#    ", "#    ", " ####"),
    'D': ("#### ", "#   #", "#   #", "#   #", "#   #", "#   #", "#### "),
    'E': ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#####"),
    'F': ("#####", "#    ", "#    ", "#### ", "#    ", "#    ", "#    "),
    'G': (" ####", "#    ", "#    ", "# ###", "#   #", "#   #", " ### "),
    'H': ("#   #", "#   #", "#   #", "#####", "#   #", "#   #", "#   #"),
    'I': ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "#####"),
    'J': ("  ###", "   # ", "   # ", "   # ", "   # ", "#  # ", " ##  "),
    'K': ("#   #", "#  # ", "# #  ", "##   ", "# #  ", "#  # ", "#   #"),
    'L': ("#    ", "#    ", "#    ", "#    ", "#    ", "#    ", "#####"),
    'M': ("#   #", "## ##", "# # #", "# # #", "#   #", "#   #", "#   #"),
    'N': ("#   #", "##  #", "##  #", "# # #", "#  ##", "#  ##", "#   #"),
    'O': (" ### ", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    'P': ("#### ", "#   #", "#   #", "#### ", "#    ", "#    ", "#    "),
    'Q': (" ### ", "#   #", "#   #", "#   #", "# # #", "#  # ", " ## #"),
    'R': ("#### ", "#   #", "#   #", "#### ", "# #  ", "#  # ", "#   #"),
    'S': (" ####", "#    ", "#    ", " ### ", "    #", "    #", "#### "),
    'T': ("#####", "  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "  #  "),
    'U': ("#   #", "#   #", "#   #", "#   #", "#   #", "#   #", " ### "),
    'V': ("#   #", "#   #", "#   #", "#   #", "#   #", " # # ", "  #  "),
    'W': ("#   #", "#   #", "#   #", "# # #", "# # #", "## ##", "#   #"),
    'X': ("#   #", "#   #", " # # ", "  #  ", " # # ", "#   #", "#   #"),
    'Y': ("#   #", "#   #", " # # ", "  #  ", "  #  ", "  #  ", "  #  "),
    'Z': ("#####", "    #", "   # ", "  #  ", " #   ", "#    ", "#####"),
    '0': (" ### ", "#  ##", "# # #", "##  #", "#   #", "#   #", " ### "),
    '1': ("  #  ", " ##  ", "  #  ", "  #  ", "  #  ", "  #  ", " ### "),
    '2': (" ### ", "#   #", "    #", "   # ", "  #  ", " #   ", "#####"),
    '3': ("#### ", "    #", "    #", " ### ", "    #", "    #", "#### "),
    '4': ("   # ", "  ## ", " # # ", "#  # ", "#####", "   # ", "   # "),
    '5': ("#####", "#    ", "#### ", "    #", "    #", "#   #", " ### "),
    '6': (" ### ", "#    ", "#    ", "#### ", "#   #", "#   #", " ### "),
    '7': ("#####", "    #", "   # ", "  #  ", "  #  ", "  #  ", "  #  "),
    '8': (" ### ", "#   #", "#   #", " ### ", "#   #", "#   #", " ### "),
    '9': (" ### ", "#   #", "#   #", " ####", "    #", "    #", " ### "),
    ' ': ("     ", "     ", "     ", "     ", "     ", "     ", "     "),
    '.': ("     ", "     ", "     ", "     ", "     ", " ##  ", " ##  "),
    ',': ("     ", "     ", "     ", "     ", " ##  ", " ##  ", " #   "),
    "'": ("  #  ", "  #  ", " #   ", "     ", "     ", "     ", "     "),
    '-': ("     ", "     ", "     ", " ### ", "     ", "     ", "     "),
    '!': ("  #  ", "  #  ", "  #  ", "  #  ", "  #  ", "     ", "  #  "),
    ':': ("     ", " ##  ", " ##  ", "     ", " ##  ", " ##  ", "     "),
}


def text_width(text, scale, spacing=None):
    if spacing is None:
        spacing = scale
    return len(text) * 5 * scale + max(0, len(text) - 1) * spacing


def draw_text(cv, text, x, y, scale, color, spacing=None):
    """Draw text with the bitmap font; returns the width drawn."""
    if spacing is None:
        spacing = scale
    cx = x
    for ch in text.upper():
        glyph = FONT.get(ch, FONT[' '])
        for row in range(7):
            for col in range(5):
                if glyph[row][col] == '#':
                    cv.rect(cx + col * scale, y + row * scale,
                            cx + col * scale + scale - 1,
                            y + row * scale + scale - 1, color)
        cx += 5 * scale + spacing
    return cx - x - (spacing if text else 0)


def draw_text_centered(cv, text, cx, y, scale, color, spacing=None):
    w = text_width(text, scale, spacing)
    draw_text(cv, text, cx - w // 2, y, scale, color, spacing)


# ------------------------------------------------------------ deterministic
def lcg(seed):
    """Tiny deterministic pseudo-random generator (no `random` import)."""
    state = seed & 0x7FFFFFFF
    while True:
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        yield state / 0x7FFFFFFF


# ------------------------------------------------------------------ scene
def paint_sky(cv):
    for y in range(H):
        c = sky_color(y)
        row = cv.px[y]
        for x in range(W):
            i = x * 3
            row[i], row[i + 1], row[i + 2] = c


def paint_stars(cv):
    rnd = lcg(20261121)
    for _ in range(110):
        x = int(next(rnd) * W)
        y = int(next(rnd) * 400)
        a = 0.25 + next(rnd) * 0.65
        s = 1 if next(rnd) < 0.8 else 2
        cv.rect(x, y, x + s - 1, y + s - 1, (255, 244, 214), alpha=a)


def paint_sun(cv):
    # halo, then the disc
    for r, a in ((150, 0.10), (120, 0.14), (95, 0.20), (76, 0.30)):
        cv.disc(548, 318, r, (255, 196, 92), alpha=a)
    cv.disc(548, 318, 62, GOLD)
    cv.disc(548, 318, 50, (255, 228, 150))
    # sun's reflection shimmer on the cloud sea horizon
    for k in range(9):
        wdt = 150 - k * 12
        cv.rect(548 - wdt // 2, 640 + k * 9, 548 + wdt // 2,
                646 + k * 9, (255, 196, 120), alpha=0.20 - k * 0.018)


def paint_mountains(cv):
    # far ridge, violet
    for x in range(W):
        yb = int(618 + 34 * math.sin(x * 0.011 + 1.2)
                 + 18 * math.sin(x * 0.027 + 4.0))
        for y in range(yb, 700):
            cv.set(x, y, (74, 54, 112))
    # near ridge, darker, lower
    for x in range(W):
        yb = int(648 + 26 * math.sin(x * 0.017 + 3.1)
                 + 14 * math.sin(x * 0.041 + 0.6))
        for y in range(yb, 720):
            cv.set(x, y, (51, 37, 90))


def paint_cloud_sea(cv):
    # base: soft gradient from warm dusk to deep night at the bottom
    for y in range(660, H):
        t = (y - 660) / (H - 660)
        c = lerp_color((232, 190, 205), (38, 28, 66), t)
        row = cv.px[y]
        for x in range(W):
            i = x * 3
            row[i], row[i + 1], row[i + 2] = c
    # billowing cloud puffs
    rnd = lcg(777)
    puffs = []
    for _ in range(46):
        x = int(next(rnd) * W)
        y = 680 + int(next(rnd) * 320)
        rx = 55 + int(next(rnd) * 110)
        ry = 16 + int(next(rnd) * 26)
        col = (CLOUD_A if next(rnd) < 0.4 else
               CLOUD_B if next(rnd) < 0.7 else CLOUD_C)
        a = 0.30 + next(rnd) * 0.38
        puffs.append((y, x, rx, ry, col, a))
    puffs.sort()  # paint back to front by height
    for _y, x, rx, ry, col, a in puffs:
        cv.ellipse(x, _y, rx, ry, col, alpha=a)
    # a few small high clouds in the sky
    for (x, y, rx, ry, a) in ((120, 250, 70, 14, 0.35),
                              (660, 150, 60, 12, 0.30),
                              (420, 90, 48, 10, 0.28)):
        cv.ellipse(x, y, rx, ry, CLOUD_A, alpha=a)


def paint_tree(cv, x, y, s):
    cv.line(x, y, x, y - 10 * s // 4, (46, 32, 54), width=2)
    for k, (wdt, dy) in enumerate(((10, 0), (8, 4), (6, 8))):
        w2 = wdt * s // 4
        cv.polygon([(x - w2, y - dy * s // 4),
                    (x + w2, y - dy * s // 4),
                    (x, y - (dy + 9) * s // 4)], GRASS_DK)


def paint_island(cv, cx, top_y, half_w, depth, with_lighthouse=True):
    """A floating island: grassy plateau, rocky underside, waterfall."""
    # rocky underside tapering to a point
    cv.polygon([(cx - half_w, top_y),
                (cx + half_w, top_y),
                (cx + half_w // 3, top_y + depth * 3 // 5),
                (cx, top_y + depth),
                (cx - half_w // 3, top_y + depth * 3 // 5)],
               ROCK)
    # darker shadow on the left underside
    cv.polygon([(cx - half_w, top_y),
                (cx - half_w // 4, top_y),
                (cx - half_w // 6, top_y + depth * 3 // 5),
                (cx, top_y + depth),
                (cx - half_w // 3, top_y + depth * 3 // 5)],
               ROCK_DARK, alpha=0.55)
    # grassy cap
    cv.ellipse(cx, top_y, half_w, 16, GRASS)
    cv.ellipse(cx, top_y - 3, half_w - 8, 10, (110, 196, 158))
    # waterfall spilling off the right edge into the clouds
    wx = cx + half_w - 26
    for k in range(3):
        x0 = wx + k * 7
        for y in range(top_y + 6, top_y + depth + 130, 2):
            wob = int(3 * math.sin(y * 0.09 + k))
            cv.set(x0 + wob, y, WATER)
            cv.set(x0 + wob + 1, y, WATER)
    if with_lighthouse:
        paint_lighthouse(cv, cx - 8, top_y)
    # a couple of trees
    paint_tree(cv, cx - half_w + 34, top_y - 4, 3)
    paint_tree(cv, cx + half_w - 46, top_y - 4, 2)


def paint_lighthouse(cv, x, base_y):
    """White tower with red bands and a glowing lamp, on the island."""
    top_y = base_y - 128
    # light beams fanning across the sky
    cv.polygon([(x, top_y + 16), (x - 300, top_y - 34), (x - 300, top_y + 6)],
               (255, 240, 170), alpha=0.20)
    cv.polygon([(x, top_y + 16), (x + 300, top_y - 34), (x + 300, top_y + 6)],
               (255, 240, 170), alpha=0.20)
    # tower: slightly tapered
    cv.polygon([(x - 15, base_y), (x + 15, base_y),
                (x + 11, top_y + 22), (x - 11, top_y + 22)], TOWER)
    # red bands
    for y0, y1 in ((base_y - 34, base_y - 18), (base_y - 78, base_y - 62)):
        cv.polygon([(x - 14, y1), (x + 14, y1),
                    (x + 12, y0), (x - 12, y0)], BAND_RED)
    # gallery + lamp room
    cv.rect(x - 18, top_y + 14, x + 18, top_y + 22, INK)
    cv.rect(x - 10, top_y + 2, x + 10, top_y + 14, (255, 226, 140))
    cv.disc(x, top_y + 8, 7, (255, 240, 170))
    cv.polygon([(x - 13, top_y + 2), (x + 13, top_y + 2), (x, top_y - 10)],
               INK)
    # warm glow around the lamp
    cv.disc(x, top_y + 8, 26, (255, 220, 120), alpha=0.25)
    cv.disc(x, top_y + 8, 16, (255, 230, 150), alpha=0.35)


def paint_airship(cv):
    cx, cy = 138, 238
    # envelope: cream with coral stripes
    cv.ellipse(cx, cy, 52, 28, CREAM)
    for dx in (-30, -10, 10, 30):
        for y in range(cy - 28, cy + 29):
            dy = (y - cy) / 28
            rem = 1.0 - dy * dy
            if rem < 0:
                continue
            span = int(52 * math.sqrt(rem))
            x0 = cx + dx - 5
            for x in range(max(cx - span, x0), min(cx + span, x0 + 10)):
                cv.set(x, y, CORAL)
    # gondola and rigging
    cv.line(cx - 34, cy + 24, cx - 16, cy + 44, INK, width=2)
    cv.line(cx + 34, cy + 24, cx + 16, cy + 44, INK, width=2)
    cv.rect(cx - 18, cy + 44, cx + 18, cy + 58, (122, 74, 44))
    cv.rect(cx - 18, cy + 44, cx + 18, cy + 48, (90, 52, 30))
    # tiny tail fin
    cv.polygon([(cx - 52, cy - 4), (cx - 70, cy - 18), (cx - 52, cy - 16)],
               BAND_RED)


def paint_birds(cv):
    for (x, y, s) in ((430, 180, 9), (470, 205, 7), (395, 225, 6),
                      (610, 250, 8), (250, 150, 7)):
        cv.line(x - s, y, x, y + s // 2, INK, width=2)
        cv.line(x, y + s // 2, x + s, y, INK, width=2)


def paint_type(cv):
    # title with a soft shadow so it reads against the sky
    title_y = 66
    draw_text_centered(cv, "NIMBARA", W // 2 + 4, title_y + 5, 13, INK)
    draw_text_centered(cv, "NIMBARA", W // 2, title_y, 13, CREAM)
    # thin rules flanking the tagline
    tag_y = 196
    tw = text_width("WHERE THE CLOUDS COME TO REST", 3)
    rule_y = tag_y + 10
    cv.rect(W // 2 - tw // 2 - 92, rule_y, W // 2 - tw // 2 - 18,
            rule_y + 2, GOLD)
    cv.rect(W // 2 + tw // 2 + 18, rule_y, W // 2 + tw // 2 + 92,
            rule_y + 2, GOLD)
    draw_text_centered(cv, "WHERE THE CLOUDS COME TO REST",
                       W // 2, tag_y, 3, GOLD)
    # footer line on a darkened band at the foot of the poster
    cv.rect(0, 948, W - 1, H - 1, INK, alpha=0.45)
    draw_text_centered(cv, "BEYOND THE EDGE OF THE MAP",
                       W // 2, 972, 3, CREAM)


def paint_frame(cv):
    cv.rect(0, 0, W - 1, 15, CREAM)
    cv.rect(0, H - 16, W - 1, H - 1, CREAM)
    cv.rect(0, 0, 15, H - 1, CREAM)
    cv.rect(W - 16, 0, W - 1, H - 1, CREAM)
    cv.rect(22, 22, W - 23, 23, INK, alpha=0.55)
    cv.rect(22, H - 24, W - 23, H - 23, INK, alpha=0.55)
    cv.rect(22, 22, 23, H - 23, INK, alpha=0.55)
    cv.rect(W - 24, 22, W - 23, H - 23, INK, alpha=0.55)


# -------------------------------------------------------------------- png
def png_chunk(kind, data):
    chunk = struct.pack(">I", len(data)) + kind + data
    chunk += struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return chunk


def write_png(cv, path):
    ihdr = struct.pack(">IIBBBBB", cv.w, cv.h, 8, 2, 0, 0, 0)
    raw = bytearray()
    for y in range(cv.h):
        raw.append(0)  # filter: none
        raw += cv.px[y]
    data = b"\x89PNG\r\n\x1a\n"
    data += png_chunk(b"IHDR", ihdr)
    data += png_chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    data += png_chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


# -------------------------------------------------------------------- main
def build():
    cv = Canvas(W, H)
    paint_sky(cv)
    paint_stars(cv)
    paint_sun(cv)
    paint_airship(cv)
    paint_birds(cv)
    paint_mountains(cv)
    paint_cloud_sea(cv)
    # small islet, far right, with a lone pine
    paint_island(cv, 640, 560, 74, 96, with_lighthouse=False)
    # tiny islet, far left, with a watchtower
    paint_island(cv, 108, 500, 52, 70, with_lighthouse=False)
    cv.rect(96, 462, 120, 500, TOWER)
    cv.polygon([(92, 462), (124, 462), (108, 448)], BAND_RED)
    # the main island and its lighthouse
    paint_island(cv, 330, 618, 150, 190, with_lighthouse=True)
    paint_type(cv)
    paint_frame(cv)
    return cv


def main():
    cv = build()
    try:
        os.makedirs("/output", exist_ok=True)
        path = "/output/entry.png"
    except OSError:
        os.makedirs("output", exist_ok=True)
        path = os.path.join("output", "entry.png")
    size = write_png(cv, path)
    print("wrote %s (%dx%d, %d bytes)" % (path, W, H, size))


if __name__ == "__main__":
    main()
