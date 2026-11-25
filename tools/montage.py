#!/usr/bin/env python3
"""Full YouTube cut: cold-open hook, dead-time removal, zoom punch-ins, flash
transitions, then the same grade / captions / export as edit.py.

  python3 tools/montage.py raw.mp4 projects/<name>/plan.txt projects/<name>/captions.txt -o out.mp4
  (add --preview-at 5:35 to render only 12 s of the EDITED timeline around that raw time)

plan.txt (all times are positions in the RAW recording):
  hook 5:34.5-5:39.5 | caption shown over the hook
  keep 0:00-0:50
  keep 1:07-6:34
  zoom 5:35-5:39
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edit as E  # noqa: E402


def parse_range(r):
    a, b = r.split("-")
    return E.ts_to_s(a.strip()), E.ts_to_s(b.strip())


def parse_plan(path):
    hook, keeps, zooms = None, [], []
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip() if not raw.strip().startswith("hook") else raw.strip()
        if not line:
            continue
        kind, rest = line.split(None, 1)
        if kind == "hook":
            rng, _, text = rest.partition("|")
            hook = (*parse_range(rng.strip()), text.strip())
        elif kind == "keep":
            keeps.append(parse_range(rest))
        elif kind == "zoom":
            zooms.append(parse_range(rest))
    return hook, keeps, zooms


class Timeline:
    def __init__(self, hook, keeps):
        self.base = (hook[1] - hook[0]) if hook else 0.0
        self.segs = []  # (raw_a, raw_b, edit_a)
        t = self.base
        for a, b in keeps:
            self.segs.append((a, b, t))
            t += b - a
        self.length = t

    def map(self, t):
        for a, b, ea in self.segs:
            if a <= t <= b:
                return ea + (t - a)
        return None

    def map_range(self, a, b):
        """Clip [a,b] to the kept segment containing a (or the next one it overlaps)."""
        for sa, sb, ea in self.segs:
            lo, hi = max(a, sa), min(b, sb)
            if hi - lo > 0.3:
                return ea + (lo - sa), ea + (hi - sa)
        return None

    def cuts(self):
        pts = [ea for _, _, ea in self.segs]
        return [p for p in pts if p > 0.01]


def zoom_expr(ranges, amount=0.12):
    terms = [f"between(it,{a:.3f},{b:.3f})*min(min(1,(it-{a:.3f})/0.25),max(0,({b:.3f}-it)/0.4))"
             for a, b in ranges]
    return f"1+{amount}*min(1," + "+".join(terms) + ")" if terms else "1"


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-2000:]); raise SystemExit(r.returncode)


def pieces(hook, keeps, zooms):
    """Split the edit into pieces: (raw_a, raw_b, zoom?, fade_in?, fade_out?)."""
    out = []
    if hook:
        out.append((hook[0], hook[1], True, True, True))
    for a, b in keeps:
        cuts = sorted({a, b} | {t for za, zb in zooms for t in (za, zb) if a < t < b})
        for x, y in zip(cuts, cuts[1:]):
            z = any(za <= x and y <= zb for za, zb in zooms)
            out.append((x, y, z, x == a, y == b))
    return out


def cut_pass(src, plan, work):
    """Pass 1: frame-accurate pieces at 1080p60 (zoom punch-ins applied only to
    zoom pieces), PCM audio so pieces join without gaps, then concat."""
    hook, keeps, zooms = parse_plan(plan)
    work.mkdir(parents=True, exist_ok=True)
    lst = []
    ps = pieces(hook, keeps, zooms)
    for i, (a, b, z, fin, fout) in enumerate(ps):
        d = b - a
        vf = "fps=60,setsar=1,scale=1920:1080"
        if z:
            env = f"min(min(1,it/0.25),max(0,({d:.3f}-it)/0.4))"
            vf += (f",zoompan=z='1+0.12*{env}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                   f":d=1:s=1920x1080:fps=60")
        af = ["aresample=48000"]
        if fin:
            af.append("afade=t=in:d=0.04")
        if fout:
            af.append(f"afade=t=out:st={max(0, d - 0.06):.3f}:d=0.06")
        f = work / f"p{i:03d}.mkv"
        run(["ffmpeg", "-hide_banner", "-y", "-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", str(src),
             "-vf", vf, "-af", ",".join(af), "-c:v", "libx264", "-preset", "veryfast", "-crf", "12",
             "-pix_fmt", "yuv420p", "-g", "60", "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(f)])
        lst.append(f"file '{f}'")
        print(f"  piece {i + 1}/{len(ps)}  {a:.1f}-{b:.1f}{'  zoom' if z else ''}", flush=True)
    (work / "list.txt").write_text("\n".join(lst) + "\n")
    joined = work / "cut.mkv"
    run(["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0", "-i", str(work / "list.txt"),
         "-c", "copy", str(joined)])
    return joined


def finish_pass(cut, plan, captions, out, res=1440, strength=1.0, window=None):
    """Pass 2: grade + glow + sharpen + 1440p + vignette + flash transitions + captions."""
    hook, keeps, _ = parse_plan(plan)
    tl = Timeline(hook, keeps)
    hook_len = tl.base
    items = []
    if hook:
        items.append(("hype", 0.25, hook_len - 0.1, hook[2], ""))
    for kind, a, b, text, extra in E.parse_captions(captions):
        m = tl.map_range(a, b)
        if m:
            items.append((kind, m[0], m[1], text, extra))
        else:
            print(f"  (caption dropped, falls in a cut: {text})")
    off = window[0] if window else 0.0
    cuts = [c - off for c in tl.cuts()]

    font = "Anton" if not (E.FONTS / "impact.ttf").exists() and (E.FONTS / "Anton-Regular.ttf").exists() else "Impact"
    ass = Path(out).with_suffix(".ass")
    E.write_hype_ass(items, ass, font, off)
    lut = E.GRADE_DIR / f"vicecity_{strength:.2f}.cube"
    if not lut.exists():
        subprocess.run([sys.executable, str(E.ROOT / "tools" / "make_lut.py"),
                        "--strength", str(strength), "-o", str(lut)], check=True)

    flash1 = "+".join(f"between(t,{c:.3f},{c + 0.05:.3f})" for c in cuts) or "0"
    flash2 = "+".join(f"between(t,{c + 0.05:.3f},{c + 0.15:.3f})" for c in cuts) or "0"
    graph = (f"[0:v]format=gbrp,lut3d=file='{E.esc(lut)}':interp=tetrahedral,split[base][hl];"
             "[hl]curves=all='0/0 0.62/0 1/1',scale=iw/4:ih/4,gblur=sigma=12,scale=iw*4:ih*4:flags=bilinear[glow];"
             "[base][glow]blend=all_mode=screen:all_opacity=0.14,cas=strength=0.35,"
             f"scale=-2:{res}:flags=lanczos,vignette=angle=PI/10:mode=forward,format=yuv420p,"
             f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.7:t=fill:enable='{flash1}',"
             f"drawbox=x=0:y=0:w=iw:h=ih:color=white@0.3:t=fill:enable='{flash2}',"
             f"ass='{E.esc(ass)}':fontsdir='{E.esc(E.FONTS)}',format=yuv420p[v]")
    gfile = Path(out).with_suffix(".graph.txt")
    gfile.write_text(graph)
    win = ["-ss", f"{window[0]:.3f}", "-t", f"{window[1] - window[0]:.3f}"] if window else []
    cmd = ["ffmpeg", "-hide_banner", "-y", *win, "-i", str(cut), "-filter_complex_script", str(gfile),
           "-map", "[v]", "-map", "0:a",
           "-c:v", "libx264", "-preset", E.PRESET, "-crf", E.CRF, "-maxrate", "32M", "-bufsize", "64M",
           "-profile:v", "high", "-pix_fmt", "yuv420p", "-g", "30", "-bf", "2", "-flags", "+cgop",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-c:a", "aac", "-b:a", "320k", "-ar", "48000", "-fps_mode", "cfr", "-movflags", "+faststart", str(out)]
    print(f"edited length {int(tl.length // 60)}:{tl.length % 60:04.1f}  captions {len(items)}  cuts {len(cuts)}", flush=True)
    subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("plan")
    ap.add_argument("captions")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--res", type=int, default=1440)
    ap.add_argument("--preview-at", help="raw time; render 12 s of the edited video around it")
    ap.add_argument("--chapters", help="file of 'raw_time | title' lines to remap for YouTube")
    a = ap.parse_args()

    hook, keeps, _ = parse_plan(a.plan)
    tl = Timeline(hook, keeps)
    if a.chapters:
        for raw in Path(a.chapters).read_text().splitlines():
            if "|" in raw:
                t, title = [x.strip() for x in raw.split("|", 1)]
                m = 0.0 if E.ts_to_s(t) == 0 else tl.map(E.ts_to_s(t))
                if m is not None:
                    print(f"{int(m // 60)}:{int(m % 60):02d} {title}")
        return
    window = None
    if a.preview_at:
        c = 0.0 if a.preview_at == "hook" else tl.map(E.ts_to_s(a.preview_at))
        window = (max(0, c - 4), max(0, c - 4) + 12)
    work = Path(a.output).resolve().parent / "montage_work"
    cut = work / "cut.mkv"
    if not cut.exists():
        cut = cut_pass(a.input, a.plan, work)
    finish_pass(cut, a.plan, a.captions, a.output, a.res, window=window)


if __name__ == "__main__":
    main()
