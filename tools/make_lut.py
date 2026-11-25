#!/usr/bin/env python3
"""Generate the "Vice City" colour-grade LUT (GTA 6 trailer inspired look).

Look goals:
  * warm golden-hour highlights with a pink/magenta sunset tint
  * teal/cyan shadows, skies and water
  * rich, deep blacks with a filmic S-curve and soft highlight roll-off
  * boosted but controlled saturation (vibrance, so skin and already-saturated
    colours don't blow out)

Writes a standard .cube file that works in ffmpeg, DaVinci Resolve, Premiere
Pro, CapCut, OBS, etc.

Usage: python3 tools/make_lut.py [--strength 1.0] [--size 33] [-o grade/vicecity.cube]
"""
import argparse
import numpy as np


def smoothstep(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    m = d > 1e-6
    rc = np.where(m, (mx - r) / np.where(m, d, 1), 0)
    gc = np.where(m, (mx - g) / np.where(m, d, 1), 0)
    bc = np.where(m, (mx - b) / np.where(m, d, 1), 0)
    h = np.where(r == mx, bc - gc, h)
    h = np.where(g == mx, 2.0 + rc - bc, h)
    h = np.where(b == mx, 4.0 + gc - rc, h)
    h = np.where(m, (h / 6.0) % 1.0, 0)
    s = np.where(mx > 1e-6, d / np.where(mx > 1e-6, mx, 1), 0)
    return np.stack([h, s, mx], -1)


def hsv_to_rgb(hsv):
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    i = np.floor(h * 6.0).astype(int) % 6
    f = h * 6.0 - np.floor(h * 6.0)
    p, q, t = v * (1 - s), v * (1 - s * f), v * (1 - s * (1 - f))
    choices = [
        np.stack([v, t, p], -1), np.stack([q, v, p], -1), np.stack([p, v, t], -1),
        np.stack([p, q, v], -1), np.stack([t, p, v], -1), np.stack([v, p, q], -1),
    ]
    out = np.zeros_like(hsv)
    for k in range(6):
        out = np.where((i == k)[..., None], choices[k], out)
    return out


def hue_dist(h, center):
    d = np.abs(h - center)
    return np.minimum(d, 1 - d)


def grade(rgb):
    x = rgb.copy()
    luma = lambda c: c[..., 0] * 0.2126 + c[..., 1] * 0.7152 + c[..., 2] * 0.0722

    # 1. Filmic S-curve on luminance (deep blacks, punchy mids, soft roll-off)
    y = luma(x)
    y_c = np.clip(y, 0, 1)
    s_curve = y_c + 0.22 * (smoothstep(0, 1, y_c) - y_c)        # contrast
    s_curve = s_curve - 0.035 * (1 - smoothstep(0.0, 0.25, y_c)) * (1 - y_c)  # crush shadows a touch
    s_curve = np.where(y_c > 0.82, 0.82 + (s_curve - 0.82) * 0.85, s_curve)    # highlight roll-off
    ratio = np.where(y > 1e-4, s_curve / np.maximum(y, 1e-4), 1.0)
    x = x * ratio[..., None]

    # 2. Split toning: teal shadows, warm orange/pink highlights
    y = np.clip(luma(x), 0, 1)
    sh = (1 - smoothstep(0.0, 0.45, y))[..., None]
    hi = smoothstep(0.45, 1.0, y)[..., None]
    x = x + sh * np.array([-0.012, 0.004, 0.020])
    x = x + hi * np.array([0.040, 0.010, -0.025])
    # sunset magenta kiss in the upper-mids
    mid_hi = (smoothstep(0.35, 0.65, y) * (1 - smoothstep(0.75, 1.0, y)))[..., None]
    x = x + mid_hi * np.array([0.018, -0.012, 0.010])
    x = np.clip(x, 0, 1)

    # 3. Selective hue work + vibrance
    hsv = rgb_to_hsv(x)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]

    # blues/cyans -> Miami teal, a bit richer
    w_blue = np.clip(1 - hue_dist(h, 0.56) / 0.09, 0, 1)
    h = h - 0.018 * w_blue
    s = s + 0.10 * w_blue * s
    # greens -> lush tropical yellow-green
    w_green = np.clip(1 - hue_dist(h, 0.30) / 0.10, 0, 1)
    h = h - 0.015 * w_green
    s = s + 0.08 * w_green * s
    # oranges/skin: protect (less saturation boost), slight warm push
    w_skin = np.clip(1 - hue_dist(h, 0.07) / 0.06, 0, 1)
    # magentas/pinks (neon, sunsets) -> pop
    w_pink = np.clip(1 - hue_dist(h, 0.90) / 0.08, 0, 1)
    s = s + 0.15 * w_pink * s

    vib = 0.38 * (1 - s) * (1 - 0.6 * w_skin)                   # vibrance
    s = s * (1 + 0.12 * (1 - 0.5 * w_skin)) + vib * s
    s = np.where(v < 0.15, s * (v / 0.15) ** 0.7, s)             # keep blacks clean
    hsv = np.stack([h % 1.0, np.clip(s, 0, 1), v], -1)
    x = hsv_to_rgb(hsv)

    # 4. Slight black lift tint + overall warmth
    x = x * 0.995 + np.array([0.000, 0.002, 0.004])
    x = x * np.array([1.012, 1.0, 0.985])
    return np.clip(x, 0, 1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=33)
    ap.add_argument("--strength", type=float, default=1.0, help="0 = no grade, 1 = full look")
    ap.add_argument("-o", "--out", default="grade/vicecity.cube")
    a = ap.parse_args()

    n = a.size
    lin = np.linspace(0, 1, n)
    # .cube order: red changes fastest
    b, g, r = np.meshgrid(lin, lin, lin, indexing="ij")
    ident = np.stack([r, g, b], -1).reshape(-1, 3)
    out = ident + a.strength * (grade(ident) - ident)
    out = np.clip(out, 0, 1)

    with open(a.out, "w") as f:
        f.write('TITLE "Vice City grade"\n')
        f.write(f"LUT_3D_SIZE {n}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n")
        for row in out:
            f.write(f"{row[0]:.6f} {row[1]:.6f} {row[2]:.6f}\n")
    print(f"wrote {a.out} ({n}^3, strength {a.strength})")


if __name__ == "__main__":
    main()
