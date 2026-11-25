#!/usr/bin/env python3
"""One-command YouTube gaming edit: Vice City colour grade + Impact subtitles +
high-quality YouTube export.

Examples
  # grade + burn subtitles from an .srt you already have
  python3 tools/edit.py input.mp4 --subs input.srt

  # grade + auto-generate subtitles (needs `pip install faster-whisper` and
  # network access to huggingface.co for the first model download)
  python3 tools/edit.py input.mp4 --auto-subs

  # grade only, 4K export, lighter look
  python3 tools/edit.py input.mp4 --res 2160 --strength 0.7

  # 10-second preview + before/after still, to check the look fast
  python3 tools/edit.py input.mp4 --preview

Fonts: put impact.ttf in ./fonts (on Windows it's C:\\Windows\\Fonts\\impact.ttf).
"""
import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
GRADE_DIR = ROOT / "grade"


# ---------------------------------------------------------------- subtitles
def ts_to_s(t):
    h, m, s = t.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def s_to_ass(t):
    t = max(t, 0)
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def parse_srt(path):
    txt = Path(path).read_text(encoding="utf-8-sig")
    out = []
    for block in re.split(r"\n\s*\n", txt.strip()):
        lines = block.strip().splitlines()
        tl = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if tl is None:
            continue
        a, b = [x.strip() for x in lines[tl].split("-->")]
        text = " ".join(lines[tl + 1:]).strip()
        text = re.sub(r"<[^>]+>", "", text)
        if text:
            out.append((ts_to_s(a), ts_to_s(b.split()[0]), text))
    return out


def chunk_segments(segs, max_words):
    """Split long lines into short punchy chunks (gaming-YouTube style),
    distributing time by character length."""
    out = []
    for a, b, text in segs:
        words = text.split()
        groups = [words[i:i + max_words] for i in range(0, len(words), max_words)]
        total = sum(len(" ".join(g)) for g in groups) or 1
        t = a
        for g in groups:
            d = (b - a) * len(" ".join(g)) / total
            out.append((t, t + d, " ".join(g)))
            t += d
    return out


def auto_transcribe(video, max_words):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        sys.exit("faster-whisper not installed: pip install faster-whisper")
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    segments, _ = model.transcribe(str(video), word_timestamps=True, vad_filter=True)
    out, cur = [], []
    for seg in segments:
        for w in seg.words or []:
            cur.append(w)
            end_sentence = w.word.strip()[-1:] in ".?!,"
            if len(cur) >= max_words or end_sentence:
                out.append((cur[0].start, cur[-1].end, "".join(x.word for x in cur).strip()))
                cur = []
        if cur:
            out.append((cur[0].start, cur[-1].end, "".join(x.word for x in cur).strip()))
            cur = []
    return out


def write_ass(segs, path, font, size, upper, pop):
    # Colours are &HAABBGGRR. White text, thick black outline + soft shadow.
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Main,{font},{size},&H00FFFFFF,&H000000FF,&H00000000,&H96000000,0,0,0,0,100,100,1,0,1,5,3,2,120,120,110,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    anim = r"{\fscx80\fscy80\t(0,90,\fscx108\fscy108)\t(90,160,\fscx100\fscy100)}" if pop else ""
    lines = []
    for a, b, text in segs:
        t = text.upper() if upper else text
        t = t.replace("{", "(").replace("}", ")").replace("\n", " ")
        lines.append(f"Dialogue: 0,{s_to_ass(a)},{s_to_ass(b)},Main,,0,0,0,,{anim}{t}")
    Path(path).write_text(header + "\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- video
def probe(video):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                        "stream=width,height,r_frame_rate", "-of", "json", str(video)],
                       capture_output=True, text=True, check=True)
    s = json.loads(r.stdout)["streams"][0]
    num, den = s["r_frame_rate"].split("/")
    return s["width"], s["height"], float(num) / float(den)


def esc(p):
    """Escape a path for use inside an ffmpeg filtergraph."""
    return str(p).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")


def build_filter(lut, res, bloom, sharpen, vignette, ass):
    f = [f"[0:v]format=gbrp,lut3d=file='{esc(lut)}':interp=tetrahedral[g]"]
    if bloom > 0:
        f.append("[g]split[base][hl]")
        f.append("[hl]curves=all='0/0 0.62/0 1/1',scale=iw/4:ih/4,gblur=sigma=12,"
                 "scale=iw*4:ih*4:flags=bilinear[glow]")
        f.append(f"[base][glow]blend=all_mode=screen:all_opacity={bloom}[g]")
    chain = "[g]"
    steps = [f"scale=-2:{res}:flags=lanczos"]
    if sharpen > 0:
        steps.append(f"cas=strength={sharpen}")
    if vignette:
        steps.append("vignette=angle=PI/5:mode=forward")
    if ass:
        steps.append(f"ass='{esc(ass)}':fontsdir='{esc(FONTS)}'")
    steps.append("format=yuv420p")
    f.append(chain + ",".join(steps) + "[v]")
    return ";".join(f)


def encode(src, dst, fgraph, fps, extra_in=(), extra_out=()):
    gop = max(1, round(fps / 2))  # YouTube recommends keyframe every half-second-ish / closed GOP
    cmd = ["ffmpeg", "-hide_banner", "-y", *extra_in, "-i", str(src),
           "-filter_complex", fgraph, "-map", "[v]", "-map", "0:a?",
           "-c:v", "libx264", "-preset", "slow", "-crf", "16", "-profile:v", "high",
           "-pix_fmt", "yuv420p", "-g", str(gop), "-bf", "2", "-flags", "+cgop",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv",
           "-c:a", "aac", "-b:a", "320k", "-ar", "48000",
           "-movflags", "+faststart", *extra_out, str(dst)]
    print(" ".join(cmd)); subprocess.run(cmd, check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input")
    ap.add_argument("-o", "--output")
    ap.add_argument("--subs", help=".srt or .ass subtitle file")
    ap.add_argument("--auto-subs", action="store_true", help="transcribe with faster-whisper")
    ap.add_argument("--strength", type=float, default=1.0, help="grade strength 0..1")
    ap.add_argument("--res", type=int, default=1440,
                    help="output height. 1440 (default) or 2160 makes YouTube use its higher-bitrate VP9/AV1 encode")
    ap.add_argument("--bloom", type=float, default=0.14, help="highlight glow opacity, 0 to disable")
    ap.add_argument("--sharpen", type=float, default=0.35, help="CAS sharpen strength, 0 to disable")
    ap.add_argument("--no-vignette", action="store_true")
    ap.add_argument("--font", default="Impact")
    ap.add_argument("--font-size", type=int, default=86)
    ap.add_argument("--words", type=int, default=4, help="max words per caption")
    ap.add_argument("--no-caps", action="store_true", help="don't uppercase captions")
    ap.add_argument("--no-pop", action="store_true", help="disable caption pop-in animation")
    ap.add_argument("--preview", action="store_true", help="render 10s sample + before/after PNG")
    ap.add_argument("--start", default="0", help="preview start time (seconds or hh:mm:ss)")
    a = ap.parse_args()

    src = Path(a.input).resolve()
    out = Path(a.output) if a.output else src.with_name(src.stem + ("_preview" if a.preview else "_edit") + ".mp4")
    work = out.with_suffix("")
    w, h, fps = probe(src)
    print(f"input {w}x{h} @ {fps:.2f}fps -> {a.res}p")

    if not (FONTS / "impact.ttf").exists() and not (FONTS / "Impact.ttf").exists() and a.font == "Impact":
        print("WARNING: fonts/impact.ttf not found; libass will substitute another font.")

    GRADE_DIR.mkdir(exist_ok=True)
    lut = GRADE_DIR / f"vicecity_{a.strength:.2f}.cube"
    if not lut.exists():
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_lut.py"),
                        "--strength", str(a.strength), "-o", str(lut)], check=True)

    ass = None
    if a.subs and a.subs.lower().endswith(".ass"):
        ass = Path(a.subs).resolve()
    elif a.subs or a.auto_subs:
        segs = chunk_segments(parse_srt(a.subs), a.words) if a.subs else auto_transcribe(src, a.words)
        if a.preview:
            st = ts_to_s(a.start) if ":" in a.start else float(a.start)
            segs = [(x - st, y - st, t) for x, y, t in segs if y > st]
        ass = work.with_suffix(".ass")
        write_ass(segs, ass, a.font, a.font_size, not a.no_caps, not a.no_pop)
        print(f"captions: {len(segs)} -> {ass}")

    fg = build_filter(lut, a.res, a.bloom, a.sharpen, not a.no_vignette, ass)
    if a.preview:
        encode(src, out, fg, fps, extra_in=["-ss", a.start, "-t", "10"])
        # side-by-side still at the middle of the preview
        still = out.with_name(out.stem + "_before_after.png")
        subprocess.run(["ffmpeg", "-hide_banner", "-y", "-ss", "5", "-i", str(out),
                        "-ss", str((ts_to_s(a.start) if ":" in a.start else float(a.start)) + 5), "-i", str(src),
                        "-filter_complex", f"[1:v]scale=-2:{a.res}[b];[b][0:v]hstack,scale=1920:-2",
                        "-frames:v", "1", str(still)], check=True)
        print(f"before/after still: {still}")
    else:
        encode(src, out, fg, fps)
    print(f"done: {out}")


if __name__ == "__main__":
    main()
