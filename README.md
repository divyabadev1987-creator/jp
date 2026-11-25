# jp — YouTube gaming edit pipeline

One command: **Vice City colour grade** (GTA 6 trailer–inspired) + **Impact subtitles** + **high-quality YouTube export**.

## Setup
- `ffmpeg` (with libass) and Python 3 + `numpy`
- Copy `impact.ttf` into `fonts/` (Windows: `C:\Windows\Fonts\impact.ttf`)
- Optional auto-captions: `pip install faster-whisper`

## Use
```bash
python3 tools/edit.py gameplay.mp4 --preview --start 60          # 10s test + before/after PNG
python3 tools/edit.py gameplay.mp4 --subs gameplay.srt           # full edit, captions from .srt
python3 tools/edit.py gameplay.mp4 --auto-subs                   # full edit, auto captions
python3 tools/edit.py gameplay.mp4 --strength 0.7 --res 2160     # lighter grade, 4K export
python3 tools/edit.py gameplay.mp4 --captions projects/<name>/captions.txt   # narration captions + race titles
```

### Caption file (Jp_gamerZ narration style)
```
0:40-0:45 | 283 km/h on a bike at night. Don't try this at home.
1:04-1:08 | TITLE | Final E-Vent | Electric Odyssey      -> "Race: Final E-Vent (Electric Odyssey)"
```
White Impact, sentence case, top-centre, thin black outline. If `fonts/impact.ttf` is missing,
the free look-alike **Anton** (`fonts/Anton-Regular.ttf`) is used.

## What it does
| Step | Detail |
|---|---|
| Grade | `grade/vicecity_*.cube` 3D LUT: filmic S-curve, teal shadows/skies, warm-pink sunset highlights, vibrance (skin-protected). Also works in Premiere/Resolve/CapCut. |
| Finish | soft highlight bloom, CAS sharpen, light vignette |
| Captions | Impact, white + thick black outline + shadow, ALL CAPS, max 4 words, pop-in animation |
| Export | upscaled to 1440p (forces YouTube's higher-quality VP9/AV1 encode), H.264 High CRF 16 slow, BT.709, original fps, AAC 320k, faststart |

Tweak with `--bloom`, `--sharpen`, `--no-vignette`, `--font-size`, `--words`, `--no-caps`, `--no-pop`.
