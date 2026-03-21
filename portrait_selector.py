#!/usr/bin/env python3
"""
HoI4 포트레잇 관리자 v6
- Custom pipeline: rembg → grayscale bg template + color tint → composite → scanline (glow)
- Preview before save
- Big/Small separate or set
- API key settings
- Add character
- Generic for any HoI4 mod
"""

import sys, os, json, re, traceback, argparse, shutil, uuid, colorsys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pathlib import Path
from io import BytesIO
from flask import Flask, render_template_string, request, jsonify, send_file
from dotenv import load_dotenv
from PIL import Image, ImageEnhance, ImageChops, ImageOps
import numpy as np

load_dotenv(Path(__file__).parent / ".env")

MOD_ROOT = None
CACHE_DIR = Path("/tmp/hoi4_portrait_cache")
PREVIEW_DIR = CACHE_DIR / "previews"
CACHE_DIR.mkdir(exist_ok=True)
PREVIEW_DIR.mkdir(exist_ok=True)

# Default templates (downloaded on first run)
SCRIPT_DIR = Path(__file__).parent
BG_TEMPLATE_PATH = SCRIPT_DIR / "templates" / "bg_template.png"
SCANLINE_TEMPLATE_PATH = SCRIPT_DIR / "templates" / "scanline_template.png"
BG_TEMPLATE_URL = "https://lh7-rt.googleusercontent.com/docsz/AD_4nXckqiaPTkkaRZsTbnhYMwA-YITaIcD1paXsYZmjQlyPoh4QGgzL_1ByLyJANxwvPNJdPpifwNpP08YP0xuu_AOLJ8zrpJItKxbEE53Ik93lStB4IASznNqORGVGByj0o0c8AhOT_JQKnKRsmHpx6tr0nM7a?key=uYxRgrNhFV2QxpW26n3zOw"
SCANLINE_TEMPLATE_URL = "https://lh7-rt.googleusercontent.com/docsz/AD_4nXd-ZhDo-pR3t14vHEJXPj2ZnXJkmeB4jL7Ec8O4RqH7bymRvur2PXhzR4KlWFodDQdjLEi0kwvDjlSOP9QBZq_Q5YWszoy5P0zwCV8bbPIRUnrjUisNpwZFDi0nafFHOZ-SH7jWWxXk34Sg8EKgwqylc3M6?key=uYxRgrNhFV2QxpW26n3zOw"
PORTRAIT_W, PORTRAIT_H = 156, 210

# Runtime settings
settings = {
    "gemini_key": os.environ.get("GEMINI_API_KEY", ""),
    "tavily_key": os.environ.get("TAVILY_API_KEY", ""),
    "bg_color": "#4a6741",  # tint color for background
    "scanlines": True,
    "scanline_blend": "overlay",  # overlay, glow(screen), soft_light
    "gen_mode": "set",  # set, big_only, small_only
}

app = Flask(__name__)

SKIP_ID = {"characters","portraits","civilian","army","navy","air",
           "country_leader","field_marshal","corps_commander","navy_leader",
           "advisor","traits","spriteType","spriteTypes"}
SKIP_NAME = ["vergilius","don_quixote","kali_char","ricardo_char","sancho_char",
             "limbus","artyom","nothing_char","generic","dummy",
             "collective_leadership","peoples_assembly","bundestag",
             "european_commission","A24_"]

def ensure_templates():
    import requests as rq
    for path, url in [(BG_TEMPLATE_PATH, BG_TEMPLATE_URL), (SCANLINE_TEMPLATE_PATH, SCANLINE_TEMPLATE_URL)]:
        if not path.exists():
            try:
                r = rq.get(url, timeout=15)
                r.raise_for_status()
                path.write_bytes(r.content)
                print(f"Downloaded template: {path.name}")
            except Exception as e:
                print(f"Template download failed: {e}")

def detect_mod_root():
    base = Path(__file__).parent
    for d in sorted(base.parent.iterdir()):
        if d.is_dir() and (d / "descriptor.mod").exists(): return d
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / "descriptor.mod").exists(): return d
    if (base / "descriptor.mod").exists(): return base
    return None

# ── Custom Portrait Pipeline ──

def remove_background(img):
    """Remove background using rembg."""
    try:
        from hoi4_agent.tools.portrait.rembg_wrapper import remove_background as rb
        return rb(img)
    except ImportError:
        from rembg import remove, new_session
        session = new_session("birefnet-portrait")
        buf = BytesIO()
        img.save(buf, format="PNG")
        result = remove(buf.getvalue(), session=session)
        return Image.open(BytesIO(result)).convert("RGBA")

def tint_grayscale(img, hex_color):
    """Convert image to grayscale then apply color tint."""
    gray = ImageOps.grayscale(img.convert("RGB"))
    r_t = int(hex_color[1:3], 16)
    g_t = int(hex_color[3:5], 16)
    b_t = int(hex_color[5:7], 16)
    arr = np.array(gray, dtype=np.float32) / 255.0
    tinted = np.stack([arr * r_t, arr * g_t, arr * b_t], axis=-1).clip(0, 255).astype(np.uint8)
    result = Image.fromarray(tinted, "RGB")
    if img.mode == "RGBA":
        result = result.convert("RGBA")
        result.putalpha(img.split()[-1])
    return result

def screen_blend(base, overlay):
    """Screen (Glow) blend mode: 1 - (1-a)(1-b)"""
    b = np.array(base.convert("RGB"), dtype=np.float32) / 255.0
    o = np.array(overlay.convert("RGB"), dtype=np.float32) / 255.0
    result = 1.0 - (1.0 - b) * (1.0 - o)
    return Image.fromarray((result * 255).clip(0, 255).astype(np.uint8), "RGB")

def overlay_blend(base, overlay):
    """Overlay blend mode."""
    b = np.array(base.convert("RGB"), dtype=np.float32) / 255.0
    o = np.array(overlay.convert("RGB"), dtype=np.float32) / 255.0
    mask = b < 0.5
    result = np.where(mask, 2 * b * o, 1 - 2 * (1 - b) * (1 - o))
    return Image.fromarray((result * 255).clip(0, 255).astype(np.uint8), "RGB")

def crop_face_center(img, target_w, target_h):
    """Detect face and crop/resize so head fills ~65% of frame.
    Guide proportions (156x210):
      top empty ~5%, hair ~21%, face ~40%, neck ~17%, clothes ~17%
      → face center at ~38% from top, head fills 60-65% of height
    """
    import cv2
    img_rgb = img.convert("RGB")
    arr = np.array(img_rgb)

    # Try face detection
    face_rect = None
    try:
        from hoi4_agent.tools.portrait.core.face_detector import FaceDetector
        fd = FaceDetector()
        faces = fd.detect_faces(arr)
        if faces:
            face_rect = faces[0]  # (x, y, w, h)
    except:
        pass

    if face_rect is None:
        # OpenCV Haar cascade fallback
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(30, 30))
        if len(faces) > 0:
            face_rect = max(faces, key=lambda f: f[2] * f[3])  # largest face

    if face_rect is not None:
        fx, fy, fw, fh = int(face_rect[0]), int(face_rect[1]), int(face_rect[2]), int(face_rect[3])
        ih, iw = arr.shape[:2]

        # Target: face+hair = 85-90% of frame
        # face detection gives forehead-to-chin, head with hair ≈ face * 1.4
        # head should fill 87% → face = 87/1.4 ≈ 62% of frame
        desired_h = fh / 0.50
        desired_w = desired_h * (target_w / target_h)

        # Scale to fit
        scale = desired_h / target_h

        # Horizontally centered, vertically top-aligned (small gap above hair)
        face_cx = fx + fw // 2
        hair_top = fy - int(fh * 0.2)  # hair top ≈ 20% above face detection top

        # Crop region in original image
        crop_h = int(target_h * scale)
        crop_w = int(target_w * scale)
        # Hair top at 10% from crop top (visible gap above head)
        crop_top = int(hair_top - crop_h * 0.10)
        crop_left = int(face_cx - crop_w // 2)

        # Clamp to image bounds
        crop_top = max(0, min(crop_top, ih - crop_h))
        crop_left = max(0, min(crop_left, iw - crop_w))
        crop_h = min(crop_h, ih - crop_top)
        crop_w = min(crop_w, iw - crop_left)

        if crop_w > 10 and crop_h > 10:
            cropped = img.crop((crop_left, crop_top, crop_left + crop_w, crop_top + crop_h))
            return cropped.resize((target_w, target_h), Image.LANCZOS).convert("RGBA")

    # Fallback: center crop with face bias
    w, h = img.size
    ratio = max(target_w / w, target_h / h) * 1.3  # zoom in more
    resized = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    rw, rh = resized.size
    left = (rw - target_w) // 2
    top = max(0, (rh - target_h) // 5)  # bias strongly toward top
    return resized.crop((left, top, left + target_w, top + target_h)).convert("RGBA")

def generate_portrait_custom(input_path, bg_color="#4a6741", use_scanlines=True, scanline_blend="glow", style_prompt=None):
    """Custom portrait pipeline:
    1. Load source → crop/resize to 156x210
    2. Remove background
    3. Create tinted background from template
    4. Composite person on background
    5. Apply scanline overlay (glow blend)
    """
    ensure_templates()

    # Load and crop source
    src = Image.open(input_path).convert("RGBA")
    cropped = crop_face_center(src, PORTRAIT_W, PORTRAIT_H)

    # Remove background
    nobg = remove_background(cropped)

    # Gemini style transfer (style ONLY, no bg/scanlines) — uses google.genai (new SDK)
    gk = settings.get("gemini_key") or os.environ.get("GEMINI_API_KEY", "")
    if gk:
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gk)
            prompt = style_prompt or (
                "You are a photo editor. Apply ONLY color grading to this real photograph. "
                "DO NOT redraw, repaint, illustrate, or stylize the image in any way.\n\n"
                "ABSOLUTE RULE: The output must be a REAL PHOTOGRAPH. "
                "If the result looks like a painting, illustration, game art, anime, cartoon, "
                "digital art, oil painting, or any non-photographic style, YOU HAVE FAILED.\n\n"
                "ALLOWED edits (color grading ONLY):\n"
                "1. Desaturate ~40%\n"
                "2. Shift color temperature slightly warm\n"
                "3. Lower brightness ~10%, increase contrast ~20%\n"
                "4. Remove or simplify background to uniform color\n\n"
                "The output MUST look like a real photo with a color filter applied, nothing more."
            )
            response = client.models.generate_content(
                model="gemini-3.1-flash-image-preview",
                contents=[prompt, nobg],
                config=types.GenerateContentConfig(
                    response_modalities=["TEXT", "IMAGE"],
                ),
            )
            for part in response.candidates[0].content.parts:
                if part.inline_data is not None:
                    styled = Image.open(BytesIO(part.inline_data.data)).convert("RGBA")
                    # Preserve alpha mask from rembg
                    if nobg.mode == "RGBA":
                        styled = styled.resize(nobg.size, Image.LANCZOS)
                        styled.putalpha(nobg.split()[-1])
                    nobg = styled
                    break
        except Exception as e:
            print(f"Gemini style transfer: {e}")
            traceback.print_exc()

    # Create tinted background
    bg_template = Image.open(BG_TEMPLATE_PATH).convert("RGBA")
    bg_template = bg_template.resize((PORTRAIT_W, PORTRAIT_H), Image.LANCZOS)
    bg_tinted = tint_grayscale(bg_template, bg_color)

    # Optional Gemini style transfer on person
    if style_prompt and settings.get("gemini_key"):
        try:
            from hoi4_agent.tools.portrait.pipeline.portrait_pipeline import PortraitPipeline
            pp = PortraitPipeline(mode="gemini", gemini_api_key=settings["gemini_key"], style_prompt=style_prompt)
            tmp = PREVIEW_DIR / f"styled_{uuid.uuid4().hex[:6]}.png"
            nobg.save(tmp)
            pp.process_single(tmp, tmp)
            nobg = Image.open(tmp).convert("RGBA")
        except Exception as e:
            print(f"Gemini style transfer failed: {e}")

    # Composite person on background
    composite = Image.new("RGBA", (PORTRAIT_W, PORTRAIT_H))
    composite.paste(bg_tinted, (0, 0))
    composite = Image.alpha_composite(composite.convert("RGBA"), nobg)

    # Apply scanlines
    if use_scanlines and SCANLINE_TEMPLATE_PATH.exists():
        scanline = Image.open(SCANLINE_TEMPLATE_PATH).convert("RGBA")
        scanline = scanline.resize((PORTRAIT_W, PORTRAIT_H), Image.LANCZOS)
        if scanline_blend == "glow":
            rgb_result = screen_blend(composite, scanline)
        elif scanline_blend == "overlay":
            rgb_result = overlay_blend(composite, scanline)
        else:
            rgb_result = screen_blend(composite, scanline)
        composite = rgb_result.convert("RGBA")

    # Save preview
    preview_path = PREVIEW_DIR / f"preview_{uuid.uuid4().hex[:8]}.png"
    composite.convert("RGB").save(preview_path, "PNG")
    return str(preview_path)

def generate_small_icon(large_path, small_path):
    """Generate 62x67 advisor icon: full portrait scaled into rotated rectangle inside frame.
    1. Load frame mask → find inner white rectangle
    2. Scale full portrait to fit inside that area
    3. Rotate 3.24° to match frame angle
    4. Composite: portrait → mask alpha → frame overlay
    """
    from hoi4_agent.tools.portrait.minister.minister_icon import (
        _load_border_frame, _load_frame_mask, _load_inner_offset,
        MINISTER_WIDTH, MINISTER_HEIGHT, ROTATION_ANGLE
    )

    portrait = Image.open(large_path).convert("RGB")
    frame_mask = _load_frame_mask()  # 62x67, L mode, white = content area
    border_frame = _load_border_frame()  # 62x67, RGBA
    offset_x, offset_y = _load_inner_offset()

    # Measure inner white area from mask
    mask_arr = np.array(frame_mask)
    white_rows = np.where(mask_arr.max(axis=1) > 128)[0]
    white_cols = np.where(mask_arr.max(axis=0) > 128)[0]
    inner_h = white_rows[-1] - white_rows[0] if len(white_rows) else 55
    inner_w = white_cols[-1] - white_cols[0] if len(white_cols) else 48

    # Account for rotation: usable area inside rotated rect is smaller
    import math
    rad = math.radians(ROTATION_ANGLE)
    # Shrink slightly to fit inside rotated bounds
    usable_w = int(inner_w * 0.92)
    usable_h = int(inner_h * 0.92)

    # Scale full portrait to fit inside usable area (no crop)
    pw, ph = portrait.size
    scale = min(usable_w / pw, usable_h / ph)
    new_w = int(pw * scale)
    new_h = int(ph * scale)
    resized = portrait.resize((new_w, new_h), Image.LANCZOS).convert("RGBA")

    # Place on transparent canvas at 62x67
    canvas = Image.new("RGBA", (MINISTER_WIDTH, MINISTER_HEIGHT), (0, 0, 0, 0))
    # Center portrait exactly on white rectangle center (no offset bias)
    inner_cx = (white_cols[0] + white_cols[-1]) / 2.0 if len(white_cols) else 31
    inner_cy = (white_rows[0] + white_rows[-1]) / 2.0 if len(white_rows) else 33
    paste_x = int(round(inner_cx - new_w / 2.0))
    paste_y = int(round(inner_cy - new_h / 2.0))
    canvas.paste(resized, (paste_x, paste_y), resized)

    # Rotate to match frame angle
    canvas = canvas.rotate(ROTATION_ANGLE, resample=Image.BICUBIC, center=(inner_cx, inner_cy), fillcolor=(0, 0, 0, 0))

    # Apply mask + frame
    canvas.putalpha(frame_mask)
    result = Image.alpha_composite(canvas, border_frame)

    out = Path(small_path); out.parent.mkdir(parents=True, exist_ok=True)
    result.save(out)
    return True

# ── Character Extraction ──

def extract_all_characters():
    loc = {}
    for lf in (MOD_ROOT / "localisation").rglob("*_l_english.yml"):
        try:
            for line in lf.read_text(encoding="utf-8-sig").split("\n"):
                m = re.match(r'\s+(\S+):\s*"([^"]*)"', line)
                if m: loc[m.group(1)] = m.group(2)
        except: pass
    chars = []
    char_dir = MOD_ROOT / "common" / "characters"
    if not char_dir.exists(): return chars
    for cf in sorted(char_dir.glob("*.txt")):
        try: content = cf.read_text(encoding="utf-8-sig")
        except: continue
        for cb in re.finditer(r'(\t|\s{1,4})(\w+)\s*=\s*\{', content):
            cid = cb.group(2)
            if cid in SKIP_ID or any(s in cid.lower() for s in SKIP_NAME): continue
            start, depth, pos = cb.end(), 1, cb.end()
            while pos < len(content) and depth > 0:
                if content[pos] == '{': depth += 1
                elif content[pos] == '}': depth -= 1
                pos += 1
            block = content[start:pos-1]
            variants = []
            cm = re.search(r'civilian\s*=\s*\{[^}]*?large\s*=\s*"([^"]*)"', block, re.DOTALL)
            if cm: variants.append({"type":"civilian","size":"large","path":cm.group(1)})
            am = re.search(r'army\s*=\s*\{[^}]*?large\s*=\s*"([^"]*)"', block, re.DOTALL)
            if am: variants.append({"type":"army","size":"large","path":am.group(1)})
            asm = re.search(r'army\s*=\s*\{[^}]*?small\s*=\s*"?([^"\n]*)"?', block, re.DOTALL)
            if asm and "gfx" in asm.group(1):
                variants.append({"type":"advisor","size":"small","path":asm.group(1).strip().strip('"')})
            roles = []
            if 'country_leader' in block: roles.append('leader')
            if 'field_marshal' in block: roles.append('field_marshal')
            if 'corps_commander' in block: roles.append('general')
            if 'navy_leader' in block: roles.append('admiral')
            if re.search(r'advisor\s*=\s*\{', block): roles.append('advisor')
            if not variants: continue
            tag = cid.split("_")[0]
            name = loc.get(cid, " ".join(w.capitalize() for w in cid.replace("_char","").split("_")[1:]))
            chars.append({"id":cid,"tag":tag,"name":name,"variants":variants,"roles":roles,"file":cf.name})
    return chars

def do_search(name, title, tag, native_name=None, max_results=15):
    from hoi4_agent.tools.portrait.search.multi_search import MultiSourceSearch
    s = MultiSourceSearch(cache_dir=CACHE_DIR)
    try: return [str(p) for p in s.search_person(person_name=name, native_name=native_name, title=title, country_tag=tag, max_results=max_results)]
    except: traceback.print_exc(); return []

def add_character_to_file(tag, char_id, name, portrait_path, role, ideology):
    char_file = None
    for f in (MOD_ROOT/"common/characters").glob("*.txt"):
        c = f.read_text(encoding="utf-8-sig")
        if f"{tag}_" in c: char_file = f; break
    if not char_file:
        char_file = MOD_ROOT/f"common/characters/characters_{tag}.txt"
        if not char_file.exists(): char_file.write_text("characters = {\n}\n", encoding="utf-8")
    content = char_file.read_text(encoding="utf-8-sig")
    rb = ""
    if role == "leader": rb = f'\tcountry_leader = {{\n\t\tideology = {ideology}\n\t\texpire = "1.1.1.1"\n\t\tid = -1\n\t}}'
    elif role == "general": rb = '\tcorps_commander = {\n\t\tskill = 2\n\t\tattack_skill = 2\n\t\tdefense_skill = 1\n\t\tplanning_skill = 1\n\t\tlogistics_skill = 1\n\t}'
    elif role == "field_marshal": rb = '\tfield_marshal = {\n\t\tskill = 3\n\t\tattack_skill = 2\n\t\tdefense_skill = 2\n\t\tplanning_skill = 2\n\t\tlogistics_skill = 2\n\t}'
    elif role == "admiral": rb = '\tnavy_leader = {\n\t\tskill = 2\n\t\tattack_skill = 2\n\t\tdefense_skill = 1\n\t\tplanning_skill = 1\n\t\tlogistics_skill = 1\n\t}'
    pt = "army" if role in ("general","field_marshal","admiral") else "civilian"
    nc = f'\n\t{char_id} = {{\n\t\tportraits = {{\n\t\t\t{pt} = {{\n\t\t\t\tlarge = "{portrait_path}"\n\t\t\t}}\n\t\t}}\n{rb}\n\t}}'
    lb = content.rfind("}")
    if lb >= 0: content = content[:lb] + nc + "\n" + content[lb:]
    char_file.write_text(content, encoding="utf-8")
    for hf in (MOD_ROOT/"history/countries").glob(f"{tag} - *.txt"):
        hc = hf.read_text(encoding="utf-8-sig")
        if f"recruit_character = {char_id}" not in hc:
            lines = hc.split("\n"); ii = -1
            for i, l in enumerate(lines):
                if "recruit_character" in l: ii = i
            if ii >= 0: lines.insert(ii+1, f"\trecruit_character = {char_id}")
            hf.write_text("\n".join(lines), encoding="utf-8")
    for lf in (MOD_ROOT/"localisation").rglob("*characters*l_english.yml"):
        lc = lf.read_text(encoding="utf-8-sig")
        if f" {char_id}:" not in lc:
            lc += f'\n {char_id}: "{name}"'
            lf.write_text(lc, encoding="utf-8"); break
    return True

# ── HTML ──
HTML = r"""
<!DOCTYPE html><html><head><meta charset="utf-8"><title>HoI4 포트레잇 관리자</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#eee;padding:12px;font-size:13px}
.hdr{display:flex;justify-content:space-between;align-items:center;padding:5px 8px;background:#16213e;border-radius:6px;margin-bottom:8px;flex-wrap:wrap;gap:5px}
.hdr h1{font-size:0.95em}.mod{font-size:0.65em;color:#888}
.prog{background:#e94560;padding:2px 8px;border-radius:10px;font-weight:bold;font-size:0.7em}
.info{background:#16213e;padding:6px;border-radius:5px;margin-bottom:6px}
.info h2{color:#e94560;font-size:0.9em}
.tag{color:#fff;background:#0f3460;padding:1px 4px;border-radius:3px;font-size:0.6em}
.rl{color:#000;padding:1px 3px;border-radius:2px;font-size:0.6em;margin-left:2px}
.rl.admiral{background:#4488ff}.rl.general{background:#88cc44}.rl.leader{background:#e94560}.rl.field_marshal{background:#ff8800}.rl.advisor{background:#aa88ff}
.sm{color:#555;font-size:0.65em}
.pb{background:#0d1b2a;padding:5px;border-radius:4px;margin-bottom:6px}
.pb label{font-size:0.65em;color:#777;display:block;margin-bottom:1px}
.pb input,.pb textarea,.pb select{width:100%;padding:3px;background:#1b2838;color:#fff;border:1px solid #333;border-radius:3px;font-size:0.8em}
.pgrid{display:grid;grid-template-columns:1fr 1fr 1fr auto;gap:4px;align-items:end}
.vars{display:flex;gap:5px;margin-bottom:6px;flex-wrap:wrap}
.var{background:#16213e;border:2px solid #333;border-radius:5px;padding:4px;text-align:center;min-width:90px;cursor:pointer}
.var.act{border-color:#e94560}.var img{height:70px;border-radius:3px}
.var .vt{font-size:0.6em;color:#777;margin-top:2px}
.cands{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px;margin:6px 0}
.cand{border:3px solid #333;border-radius:5px;overflow:hidden;cursor:pointer;transition:all 0.1s;background:#16213e}
.cand:hover{border-color:#e94560;transform:scale(1.02)}
.cand.sel{border-color:#00ff88;box-shadow:0 0 8px rgba(0,255,136,0.3)}
.cand img{width:100%;height:170px;object-fit:cover}
.cand .lb{padding:2px;text-align:center;font-size:0.55em;color:#777}
.pv{display:none;background:#0d1b2a;border:2px solid #e94560;border-radius:6px;padding:10px;margin:8px 0;text-align:center}
.pv img{height:210px;border-radius:3px;image-rendering:auto}
.pv h3{color:#e94560;margin-bottom:6px;font-size:0.85em}
.acts{display:flex;gap:4px;flex-wrap:wrap;margin-top:5px}
.btn{padding:4px 10px;border:none;border-radius:3px;cursor:pointer;font-size:0.8em;font-weight:bold}
.bg{background:#00ff88;color:#000}.bs{background:#444;color:#ccc}.br{background:#e94560;color:#fff}
.bi{background:#4488ff;color:#fff}.by{background:#ffd700;color:#000}.bp{background:#aa44ff;color:#fff}
.btn:hover{opacity:0.85}.btn:disabled{opacity:0.4;cursor:not-allowed}
.ld{text-align:center;padding:12px;color:#555}
.st{margin-top:4px;padding:4px;border-radius:3px;font-size:0.75em}
.st.ok{background:#1a4a2a;color:#00ff88}.st.er{background:#4a1a1a;color:#ff4444}
.nav input{width:42px;padding:2px;background:#333;color:#fff;border:1px solid #555;border-radius:3px;text-align:center;font-size:0.75em}
.fl input,.fl select{padding:2px 4px;background:#333;color:#fff;border:1px solid #555;border-radius:3px;font-size:0.75em}
.modal{position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.8);display:none;justify-content:center;align-items:center;z-index:100}
.modal-box{background:#16213e;padding:15px;border-radius:8px;width:480px;max-width:95%;max-height:90vh;overflow-y:auto}
.modal-box h3{color:#e94560;margin-bottom:8px;font-size:0.95em}
.modal-box .row{margin-bottom:6px}
.modal-box label{display:block;font-size:0.75em;color:#888;margin-bottom:1px}
.modal-box input,.modal-box select{width:100%;padding:4px;background:#1b2838;color:#fff;border:1px solid #333;border-radius:3px;font-size:0.85em}
.vbtns{display:flex;gap:3px;margin-bottom:5px}
.vb{padding:2px 7px;background:#333;color:#aaa;border:1px solid #555;border-radius:3px;cursor:pointer;font-size:0.7em}
.vb.act{background:#e94560;color:#fff;border-color:#e94560}
</style></head><body>
<div class="hdr">
  <div><h1>HoI4 포트레잇 관리자</h1><div class="mod" id="modN"></div></div>
  <div class="fl" style="display:flex;gap:3px;align-items:center">
    <input id="tagF" placeholder="TAG" style="width:50px" onchange="filt()">
    <select id="roleF" onchange="filt()" style="width:70px"><option value="">전체</option><option value="leader">지도자</option><option value="general">장군</option><option value="field_marshal">원수</option><option value="admiral">제독</option><option value="advisor">고문</option></select>
  </div>
  <div class="nav" style="display:flex;gap:2px;align-items:center">
    <button class="btn bs" onclick="go(-1)">&lt;</button>
    <input type="number" id="jmp" min="0" onchange="goTo(this.value)">
    <button class="btn bs" onclick="go(1)">&gt;</button>
  </div>
  <button class="btn bp" onclick="showM('addM')">+추가</button>
  <button class="btn bs" onclick="showM('setM')" style="font-size:0.7em">설정</button>
  <button class="btn bs" onclick="clearCache()" style="font-size:0.7em">캐시 비우기</button>
  <div class="prog" id="prog">...</div>
</div>
<div id="ct"><div class="ld">불러오는 중...</div></div>
<div id="st"></div>

<!-- Settings Modal -->
<div class="modal" id="setM"><div class="modal-box">
  <h3>설정</h3>
  <div class="row"><label>Gemini API 키</label><input id="kG" type="password"></div>
  <div class="row"><label>Tavily API 키</label><input id="kT" type="password"></div>
  <div class="row"><label>배경 틴트 색상</label><input id="sBg" type="color" value="#4a6741"></div>
  <div class="row"><label>주사선</label><select id="sScan"><option value="on">On</option><option value="off">Off</option></select></div>
  <div class="row"><label>주사선 블렌드</label><select id="sBlend"><option value="glow">글로우 (Screen)</option><option value="overlay">Overlay</option></select></div>
  <div class="row"><label>생성 모드</label><select id="sGen"><option value="set">세트 (큰→자동 작은)</option><option value="big_only">큰 것만</option><option value="small_only">작은 것만</option></select></div>
  <div class="row"><label>커스텀 배경 템플릿 (파일 경로 또는 URL)</label><input id="sBgTpl" placeholder="default"></div>
  <div class="row"><label>커스텀 주사선 템플릿</label><input id="sScanTpl" placeholder="default"></div>
  <div class="acts"><button class="btn bg" onclick="saveSets()">저장</button><button class="btn bs" onclick="hideM('setM')">닫기</button></div>
  <div id="setSt"></div>
</div></div>

<!-- Add Character Modal -->
<div class="modal" id="addM"><div class="modal-box">
  <h3>새 캐릭터 추가</h3>
  <div class="row"><label>태그</label><input id="n태그" placeholder="KOR"></div>
  <div class="row"><label>ID</label><input id="nId" placeholder="자동"></div>
  <div class="row"><label>Name</label><input id="nName" placeholder="전체 이름"></div>
  <div class="row"><label>역할</label><select id="n역할"><option value="leader">지도자</option><option value="general">장군</option><option value="field_marshal">원수</option><option value="admiral">제독</option></select></div>
  <div class="row"><label>이데올로기</label><input id="nIdeo" value="centrist"></div>
  <div class="row"><label>포트레잇 경로</label><input id="nPath" placeholder="자동"></div>
  <div class="acts"><button class="btn bg" onclick="doAdd()">생성</button><button class="btn bs" onclick="hideM('addM')">취소</button></div>
  <div id="addSt"></div>
</div></div>

<script>
let A=[],C=[],ci=0,cands=[],sel=null,cv=0,pvPath=null;
let S={bg_color:'#4a6741',scanlines:true,scanline_blend:'glow',gen_mode:'set'};

async function init(){
  let info=await(await fetch('/api/info')).json();
  document.getElementById('modN').textContent=info.mod_name+' — '+info.mod_root;
  S=await(await fetch('/api/settings')).json();
  document.getElementById('sBg').value=S.bg_color||'#4a6741';
  A=await(await fetch('/api/characters')).json();C=A;show(0);
}
function filt(){
  let t=document.getElementById('tagF').value.toUpperCase().trim(),r=document.getElementById('roleF').value;
  C=A.filter(c=>{if(t&&c.tag!==t)return false;if(r&&!c.roles.includes(r))return false;return true});show(0);
}
function go(d){show(ci+d)}function goTo(i){show(parseInt(i))}
function showM(id){document.getElementById(id).style.display='flex'}
function hideM(id){document.getElementById(id).style.display='none'}
async function clearCache(){
  if(!confirm('캐시를 비울까요? 검색 결과와 미리보기가 삭제됩니다.'))return;
  let r=await(await fetch('/api/clear-cache',{method:'POST'})).json();
  document.getElementById('st').innerHTML=`<div class="st ok">${r.message}</div>`;
  cands=[];document.getElementById('cn')&&(document.getElementById('cn').innerHTML='');
}

async function saveSets(){
  let d={gemini_key:document.getElementById('kG').value,tavily_key:document.getElementById('kT').value,
    bg_color:document.getElementById('sBg').value,scanlines:document.getElementById('sScan').value==='on',
    scanline_blend:document.getElementById('sBlend').value,gen_mode:document.getElementById('sGen').value,
    bg_template:document.getElementById('sBgTpl').value,scanline_template:document.getElementById('sScanTpl').value};
  let r=await(await fetch('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)})).json();
  S=r;document.getElementById('setSt').innerHTML='<div class="st ok">Saved</div>';
  setTimeout(()=>hideM('setM'),800);
}

function show(i){
  if(i<0||i>=C.length)return;ci=i;sel=null;cv=0;pvPath=null;cands=[];
  let c=C[i];
  document.getElementById('prog').textContent=`${i+1}/${C.length} (${A.length})`;
  document.getElementById('jmp').value=i;document.getElementById('st').innerHTML='';
  let rl=c.roles.map(r=>`<span class="rl ${r}">${r}</span>`).join('');
  let dt=c.roles.some(r=>['general','field_marshal'].includes(r))?'military general official portrait':
         c.roles.includes('admiral')?'admiral navy official portrait':'politician official portrait';
  let vt='<div class="vbtns">';
  c.variants.forEach((v,vi)=>{vt+=`<div class="vb ${vi===0?'act':''}" onclick="sv(${vi})" id="vt${vi}">${v.type}</div>`;});
  vt+='</div>';
  let vp='<div class="vars">';
  c.variants.forEach((v,vi)=>{vp+=`<div class="var ${vi===0?'act':''}" id="vp${vi}" onclick="sv(${vi})"><img src="/api/file?p=${encodeURIComponent(v.path)}" onerror="this.style.opacity=0.15"><div class="vt">${v.type} ${v.size}</div></div>`;});
  vp+='</div>';
  document.getElementById('ct').innerHTML=`<div class="info"><h2>${c.name} <span class="tag">${c.tag}</span> ${rl}</h2><div class="sm">${c.id} | ${c.file}</div></div>
  ${vt}${vp}
  <div class="pb"><div class="pgrid">
    <div><label>Name</label><input id="sN" value="${c.name}"></div>
    <div><label>Title</label><input id="sT" value="${dt}"></div>
    <div><label>Native</label><input id="sV" placeholder="현지어"></div>
    <div><button class="btn br" onclick="doS()">검색</button></div>
  </div></div>
  <div class="pb"><div style="display:grid;grid-template-columns:1fr auto 1fr auto;gap:4px;align-items:end">
    <div><label>이미지 URL</label><input id="cUrl" placeholder="https://..."></div>
    <div><button class="btn bi" onclick="addUrl()">URL 추가</button></div>
    <div><label>사진 업로드</label><input type="file" id="fUpload" accept="image/*" onchange="uploadFile()" style="font-size:0.7em"></div>
    <div></div>
  </div></div>
  <div class="cands" id="cn"></div>
  <div class="pv" id="pvA"><h3>미리보기</h3><img id="pvI">
    <div class="pb" style="margin-top:8px;text-align:left"><label>스타일 프롬프트 (재생성 시 적용)</label>
      <input id="regenPrompt" placeholder="e.g. military uniform, formal suit, younger, older...">
    </div>
    <div class="acts" style="justify-content:center;margin-top:6px">
    <button class="btn bg" onclick="doSave()">저장</button>
    <button class="btn by" onclick="doSaveAs()">다른 이름 저장...</button>
    <button class="btn br" onclick="doG()">재생성</button>
    <button class="btn bs" onclick="hidePv()">취소</button>
  </div></div>
  <div class="acts" id="mA">
    <button class="btn bg" id="gB" onclick="doG()" disabled>사진 선택</button>
    <button class="btn bi" id="iB" onclick="doI()" style="display:none">아이콘</button>
    <button class="btn bs" onclick="go(1)">건너뛰기 &gt;</button>
  </div>`;
}
function sv(vi){
  cv=vi;document.querySelectorAll('.vb').forEach(e=>e.classList.remove('act'));
  document.querySelectorAll('.var').forEach(e=>e.classList.remove('act'));
  document.getElementById('vt'+vi)?.classList.add('act');document.getElementById('vp'+vi)?.classList.add('act');
  let v=C[ci].variants[vi],st=document.getElementById('sT');
  if(v?.type==='army')st.value='military uniform official portrait';
  else st.value='politician official portrait';
}
async function doS(){
  document.getElementById('cn').innerHTML='<div class="ld">검색 중...</div>';
  let u=`/api/search?name=${encodeURIComponent(document.getElementById('sN').value)}&tag=${C[ci].tag}&title=${encodeURIComponent(document.getElementById('sT').value)}&skip=${cands.length}`;
  let nt=document.getElementById('sV').value;if(nt)u+=`&native=${encodeURIComponent(nt)}`;
  let newCands=await(await fetch(u)).json();
  // 재검색: 기존 결과에 새 결과 추가 (중복 제거)
  let existing=new Set(cands);
  newCands.forEach(p=>{if(!existing.has(p)){cands.push(p);}});
  if(!cands.length) cands=newCands;
  renderC();
}
async function addUrl(){
  let url=document.getElementById('cUrl').value.trim();if(!url)return;
  let r=await(await fetch('/api/fetch-url',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({url})})).json();
  if(r.path){cands.push(r.path);renderC();}else alert(r.error);
}
async function uploadFile(){
  let f=document.getElementById('fUpload').files[0];if(!f)return;
  let fd=new FormData();fd.append('file',f);
  let r=await(await fetch('/api/upload',{method:'POST',body:fd})).json();
  if(r.path){cands.unshift(r.path);renderC();pick(0);}else alert(r.error);
}
function renderC(){
  let h='';cands.forEach((p,i)=>{h+=`<div class="cand" id="c${i}" onclick="pick(${i})"><img src="/api/file?p=${encodeURIComponent(p)}"><div class="lb">${p.split('/').pop()}</div></div>`;});
  if(!cands.length)h='<div class="ld">결과 없음</div>';
  document.getElementById('cn').innerHTML=h;
}
function pick(i){
  document.querySelectorAll('.cand').forEach(e=>e.classList.remove('sel'));
  document.getElementById('c'+i).classList.add('sel');sel=cands[i];
  let b=document.getElementById('gB');b.disabled=false;b.textContent='미리보기 생성';
  if(C[ci].variants.some(v=>v.type==='advisor'))document.getElementById('iB').style.display='inline-block';
}
async function doG(){
  if(!sel)return;
  let b=document.getElementById('gB');b.textContent='생성 중...';b.disabled=true;
  // Show generating state in preview area
  document.getElementById('pvA').style.display='block';
  document.getElementById('mA').style.display='none';
  document.getElementById('pvI').style.display='none';
  document.querySelector('#pvA h3').textContent='생성 중...';
  document.querySelector('#pvA .acts').style.display='none';
  let r=await(await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({input_path:sel,style_prompt:document.getElementById('regenPrompt')?.value||null})})).json();
  if(r.preview_path){
    pvPath=r.preview_path;
    document.getElementById('pvI').src='/api/file?p='+encodeURIComponent(r.preview_path)+'&t='+Date.now();
    document.getElementById('pvI').style.display='';
    document.querySelector('#pvA h3').textContent='미리보기';
    document.querySelector('#pvA .acts').style.display='flex';
  } else {
    document.getElementById('st').innerHTML=`<div class="st er">${r.error}</div>`;
    document.getElementById('pvA').style.display='none';
    document.getElementById('mA').style.display='flex';
  }
  b.textContent='미리보기 생성';b.disabled=false;
}
function hidePv(){document.getElementById('pvA').style.display='none';document.getElementById('mA').style.display='flex';pvPath=null;}
async function doSave(){
  if(!pvPath)return;let v=C[ci].variants[cv];
  let r=await(await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({preview_path:pvPath,output_path:v.path,char_id:C[ci].id})})).json();
  if(r.success){
    let msg=`<div class="st ok">저장 완료: ${v.path}</div>`;
    if(r.icon_path) msg+=`<div class="st ok">아이콘 자동 생성: ${r.icon_path}</div>`;
    document.getElementById('st').innerHTML=msg;
    hidePv();
    if(cv<C[ci].variants.length-1&&C[ci].variants[cv+1].type!=='advisor'){sv(cv+1);}
    else setTimeout(()=>go(1),800);
  } else document.getElementById('st').innerHTML=`<div class="st er">${r.error}</div>`;
}
async function doSaveAs(){
  if(!pvPath)return;let np=prompt('Save as:',C[ci].variants[cv].path);if(!np)return;
  let r=await(await fetch('/api/save',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({preview_path:pvPath,output_path:np})})).json();
  document.getElementById('st').innerHTML=r.success?`<div class="st ok">저장 완료: ${np}</div>`:`<div class="st er">${r.error}</div>`;
}
async function doI(){
  let c=C[ci],lg=c.variants.find(v=>v.type==='civilian'||v.type==='army'),sm=c.variants.find(v=>v.type==='advisor');
  if(!lg||!sm)return;
  let r=await(await fetch('/api/gen-icon',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({large_path:lg.path,small_path:sm.path})})).json();
  document.getElementById('st').innerHTML=r.success?`<div class="st ok">아이콘 완료</div>`:`<div class="st er">${r.error}</div>`;
}
async function doAdd(){
  let d={tag:document.getElementById('n태그').value.trim().toUpperCase(),char_id:document.getElementById('nId').value.trim(),
    name:document.getElementById('nName').value.trim(),role:document.getElementById('n역할').value,
    ideology:document.getElementById('nIdeo').value.trim()||'centrist',portrait_path:document.getElementById('nPath').value.trim()};
  if(!d.tag||!d.char_id||!d.name||!d.portrait_path){alert('모든 항목을 입력하세요');return}
  let r=await(await fetch('/api/add-char',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)})).json();
  if(r.success){document.getElementById('addSt').innerHTML='<div class="st ok">Added</div>';A=await(await fetch('/api/characters')).json();C=A;filt();setTimeout(()=>hideM('addM'),800);}
  else document.getElementById('addSt').innerHTML=`<div class="st er">${r.error}</div>`;
}
document.getElementById('nName')?.addEventListener('input',function(){
  let t=document.getElementById('n태그').value.trim().toUpperCase(),n=this.value.trim().replace(/\s+/g,'_').toLowerCase();
  if(t){document.getElementById('nId').value=`${t}_${n}_char`;
  let rl=document.getElementById('n역할').value,sub=rl==='admiral'?'admirals/':rl==='leader'?'':'generals/';
  document.getElementById('nPath').value=`gfx/Leaders/${t}/${sub}${t}_${n}.png`;}
});
document.getElementById('n태그')?.addEventListener('input',function(){document.getElementById('nName').dispatchEvent(new Event('input'))});
init();
</script></body></html>
"""

# ── Routes ──
@app.route("/")
def index(): return render_template_string(HTML)
@app.route("/api/info")
def api_info(): return jsonify({"mod_name":MOD_ROOT.name,"mod_root":str(MOD_ROOT)})
@app.route("/api/characters")
def api_chars(): return jsonify(extract_all_characters())
@app.route("/api/settings", methods=["GET","POST"])
def api_settings():
    global settings
    if request.method == "POST":
        d = request.json
        if d.get("gemini_key"): settings["gemini_key"] = d["gemini_key"]; os.environ["GEMINI_API_KEY"] = d["gemini_key"]
        if d.get("tavily_key"): settings["tavily_key"] = d["tavily_key"]; os.environ["TAVILY_API_KEY"] = d["tavily_key"]
        if d.get("bg_color"): settings["bg_color"] = d["bg_color"]
        settings["scanlines"] = d.get("scanlines", True)
        settings["scanline_blend"] = d.get("scanline_blend", "glow")
        settings["gen_mode"] = d.get("gen_mode", "set")
        if d.get("bg_template"):
            p = Path(d["bg_template"])
            if p.exists(): shutil.copy2(p, BG_TEMPLATE_PATH)
        if d.get("scanline_template"):
            p = Path(d["scanline_template"])
            if p.exists(): shutil.copy2(p, SCANLINE_TEMPLATE_PATH)
    return jsonify(settings)
@app.route("/api/search")
def api_search():
    return jsonify(do_search(request.args.get("name",""),request.args.get("title",""),
        request.args.get("tag",""),request.args.get("native",None) or None))
@app.route("/api/file")
def api_file():
    p=request.args.get("p","")
    for fp in [Path(p), MOD_ROOT/p]:
        if fp.exists(): return send_file(fp)
    return "",404
@app.route("/api/preview", methods=["POST"])
def api_preview():
    d=request.json
    try:
        pv = generate_portrait_custom(d["input_path"], settings["bg_color"], settings["scanlines"], settings["scanline_blend"], d.get("style_prompt"))
        return jsonify({"preview_path":pv})
    except Exception as e: traceback.print_exc(); return jsonify({"error":str(e)})
@app.route("/api/save", methods=["POST"])
def api_save():
    d=request.json
    try:
        out=str(MOD_ROOT/d["output_path"])
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(d["preview_path"], out)
        # Auto-generate small icon for ALL characters
        icon_path = None
        if settings["gen_mode"] != "small_only":
            try:
                # Derive icon path from portrait path: gfx/Leaders/TAG/name.png → gfx/interface/ideas/TAG/advisors/name.png
                rel = d["output_path"]
                parts = rel.replace("\\","/").split("/")
                # Extract tag and filename
                fname = parts[-1]
                tag = None
                for p in parts:
                    if len(p) == 3 and p.isupper():
                        tag = p; break
                if not tag and len(parts) >= 3:
                    tag = parts[2]  # gfx/Leaders/TAG/...
                if tag:
                    icon_rel = f"gfx/interface/ideas/{tag}/advisors/{fname}"
                    icon_out = str(MOD_ROOT / icon_rel)
                    generate_small_icon(out, icon_out)
                    icon_path = icon_rel
                    print(f"Auto icon: {icon_rel}")
            except Exception as ie:
                print(f"Auto icon error: {ie}")
                traceback.print_exc()
        return jsonify({"success":True,"path":out,"icon_path":icon_path})
    except Exception as e: traceback.print_exc(); return jsonify({"success":False,"error":str(e)})
@app.route("/api/gen-icon", methods=["POST"])
def api_icon():
    d=request.json
    try:
        lg=str(MOD_ROOT/d["large_path"]) if not Path(d["large_path"]).is_absolute() else d["large_path"]
        return jsonify({"success":generate_small_icon(lg,str(MOD_ROOT/d["small_path"]))})
    except Exception as e: traceback.print_exc(); return jsonify({"success":False,"error":str(e)})
@app.route("/api/fetch-url", methods=["POST"])
def api_fetch():
    import requests as rq
    url=request.json.get("url","")
    try:
        r=rq.get(url,timeout=15,headers={"User-Agent":"Mozilla/5.0"});r.raise_for_status()
        fn=re.sub(r'[^\w.]','_',url.split('/')[-1].split('?')[0])[:60]+'.png'
        p=CACHE_DIR/fn;p.write_bytes(r.content);return jsonify({"path":str(p)})
    except Exception as e: return jsonify({"error":str(e)})
@app.route("/api/upload", methods=["POST"])
def api_upload():
    f = request.files.get("file")
    if not f: return jsonify({"error":"No file"})
    try:
        fn = re.sub(r'[^\w.]','_', f.filename or "upload")[:60]
        p = CACHE_DIR / f"upload_{uuid.uuid4().hex[:6]}_{fn}"
        f.save(p)
        return jsonify({"path":str(p)})
    except Exception as e: return jsonify({"error":str(e)})

@app.route("/api/clear-cache", methods=["POST"])
def api_clear_cache():
    import glob
    count = 0
    for f in glob.glob(str(CACHE_DIR / "*")):
        if Path(f).is_file():
            os.remove(f); count += 1
    for f in glob.glob(str(PREVIEW_DIR / "*")):
        if Path(f).is_file():
            os.remove(f); count += 1
    return jsonify({"message": f"캐시 {count}개 파일 삭제 완료"})

@app.route("/api/add-char", methods=["POST"])
def api_add():
    d=request.json
    try:
        add_character_to_file(d["tag"],d["char_id"],d["name"],d["portrait_path"],d["role"],d["ideology"])
        return jsonify({"success":True})
    except Exception as e: traceback.print_exc(); return jsonify({"success":False,"error":str(e)})

if __name__=="__main__":
    parser = argparse.ArgumentParser(description="HoI4 포트레잇 관리자")
    parser.add_argument("--mod", type=str, help="Mod directory path")
    parser.add_argument("--port", type=int, default=5555)
    args = parser.parse_args()
    MOD_ROOT = Path(args.mod) if args.mod else detect_mod_root()
    if not MOD_ROOT or not MOD_ROOT.exists():
        print("오류: 모드 폴더를 찾을 수 없습니다. Use --mod /path/to/mod"); sys.exit(1)
    ensure_templates()
    print(f"\n{'='*50}\nHoI4 포트레잇 관리자 v6\nMod: {MOD_ROOT.name}\n{MOD_ROOT}\nhttp://localhost:{args.port}\n{'='*50}\n")
    app.run(host="0.0.0.0", port=args.port, debug=False)
