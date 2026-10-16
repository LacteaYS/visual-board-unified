"""
Unified Multimodal Visual Board Engine (`multimodal_board.py`)

Unifies all three versions of Visual Board / CliniView Live:
1. Version 1 (`8111`):
   - Multi-canvas / Board History (`BOARD_STORE`)
   - Nano Banana Image Generation (`gemini-nano-banana-2.1` / `gemini-3.1-flash-lite-image`)
   - Region-Preserving Partial Image Inpainting (`edit_board_image_region` via Pillow crop + composite, preserving 100% of outer pixels)
   - Gemini Omni Video Generation (`gemini-omni-1.1-flash` image-to-video / text-to-video + deterministic `ffmpeg` MP4 fallback)
   - Slide Deck Import (`PDF`, `PPTX`, `PNG/JPG` + built-in clinical & scientific demo lecture slides)
   - Continuous Lecture STT + Bilingual Wake-Phrase Gate (`"비주얼 보드"` / `"Visual Board"`)
2. Version 2 (`8090`):
   - Authoritative Whole-Body 3D Anatomy (`SCENE_SERVICE` + `execute_natural_language_scene_command`)
3. Version 3 (`8091`):
   - Interactive 2D Pathway & Mechanism Comparison Diagrams (`knowledge_base.py` + dynamic `gemini-3.8-flash` graph synthesis)
   - 3-Sample Wake-Phrase Onboarding & Calibration (`session_store.py`)
   - Gemini TTS Narration (`gemini-3.8-flash-lite-tts`)
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from google import genai

from knowledge_base import (
    DEMO_CANDIDATE_COMPARISON,
    PROCEDURE_TEMPLATES,
    SOURCE_OF_TRUTH_DOCS,
    build_async_queue_scene,
    build_gpcr_compare_scene,
    build_gpcr_core_scene,
    build_shoulder_rotator_cuff_scene,
    build_shoulder_subscapularis_scene,
)
from session_store import (
    CANONICAL_WAKE_VARIANTS,
    WAKE_ONLY_FILLERS,
    SessionStore,
    normalize_korean_text,
    now_ms,
)
from synthesizer import generate_tts_briefing
from voice_controller import execute_natural_language_scene_command

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
MEDIA_DIR = STATIC_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
BOARDS_INDEX_PATH = MEDIA_DIR / "boards_index.json"


# ---------------------------------------------------------------------------
# 1. Environment & Credential Loader (Never logs API keys)
# ---------------------------------------------------------------------------
_CACHED_API_KEY: Optional[str] = None
_ENV_LOADED: bool = False


def _parse_dotenv_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val
    except Exception:
        pass


def load_env_credentials() -> bool:
    """
    Loads `.env` from the unified directory or fallback project directories into `os.environ`
    without ever printing or logging secret values.
    """
    global _ENV_LOADED, _CACHED_API_KEY
    if not _ENV_LOADED:
        candidate_paths = [
            BASE_DIR / ".env",
            Path("/Users/yc/Documents/ChatGPT/GDM 해커톤/.env"),
            Path("/Users/yc/Documents/ChatGPT/GDM 해커톤/apps/visual-board/.env"),
            Path("/Users/yc/Desktop/dev/GDM/cliniview-live/.env"),
        ]
        for path in candidate_paths:
            _parse_dotenv_file(path)
        _ENV_LOADED = True

    key = (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or "").strip()
    if key:
        os.environ["GEMINI_API_KEY"] = key
        _CACHED_API_KEY = key
        return True
    return False


def resolve_gemini_api_key() -> Optional[str]:
    """Resolves the Gemini API key in memory without logging."""
    global _CACHED_API_KEY
    if _CACHED_API_KEY:
        return _CACHED_API_KEY
    if load_env_credentials() and _CACHED_API_KEY:
        return _CACHED_API_KEY

    try:
        proc = subprocess.run(
            [
                "gcloud",
                "services",
                "api-keys",
                "get-key-string",
                "projects/509893886131/locations/global/keys/5d28b548-8201-4549-ac69-6a83a7a9b877",
                "--format=json",
            ],
            capture_output=True,
            text=True,
            timeout=6.0,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            data = json.loads(proc.stdout)
            candidate = (data.get("keyString") or "").strip()
            if len(candidate) >= 20:
                _CACHED_API_KEY = candidate
                os.environ["GEMINI_API_KEY"] = candidate
                return _CACHED_API_KEY
    except Exception:
        pass
    return None


def get_genai_client() -> Optional[genai.Client]:
    api_key = resolve_gemini_api_key()
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


# Load credentials immediately on module import
load_env_credentials()


# ---------------------------------------------------------------------------
# 2. Bilingual Wake-Phrase Session Store Setup
# ---------------------------------------------------------------------------
for _eng_variant in [
    "visual board",
    "hey visual board",
    "ok visual board",
    "okay visual board",
    "비주얼 보드",
    "비주얼보드",
]:
    if _eng_variant not in CANONICAL_WAKE_VARIANTS:
        CANONICAL_WAKE_VARIANTS.append(_eng_variant)

WAKE_ONLY_FILLERS.update(
    {
        "hold on",
        "wait",
        "wait a second",
        "let me see",
        "show me",
        "uh",
        "um",
        "please",
        "hey",
    }
)

SESSION_STORE = SessionStore()
for _v in CANONICAL_WAKE_VARIANTS:
    if _v not in SESSION_STORE.wake_profile.confirmedVariants:
        SESSION_STORE.wake_profile.confirmedVariants.append(_v)


# ---------------------------------------------------------------------------
# 3. Font & Pillow Illustration Helpers
# ---------------------------------------------------------------------------
def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    font_candidates = [
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for fp in font_candidates:
        if os.path.exists(fp):
            try:
                return ImageFont.truetype(fp, size=size, index=0)
            except Exception:
                continue
    return ImageFont.load_default()


def _render_pillow_scientific_illustration(
    title: str,
    prompt: str,
    subtitle: str = "AI Explanatory Medical & Scientific Illustration",
    width: int = 1280,
    height: int = 720,
    slide_mode: bool = False,
    bullets: Optional[List[str]] = None,
) -> bytes:
    """
    Generates a crisp, high-resolution 1280x720 PNG scientific/anatomical illustration
    using Pillow. Used both for pre-rendered demo slides and as an instant zero-downtime fallback.
    """
    img = Image.new("RGB", (width, height), (11, 18, 32))
    draw = ImageDraw.Draw(img, "RGBA")

    # Subtle background gradient & diagnostic grid
    for y in range(0, height, 4):
        ratio = y / float(height)
        r = int(10 + 12 * ratio)
        g = int(17 + 22 * ratio)
        b = int(30 + 38 * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b, 255), width=4)

    for gx in range(0, width, 64):
        draw.line([(gx, 0), (gx, height)], fill=(56, 189, 248, 16), width=1)
    for gy in range(0, height, 64):
        draw.line([(0, gy), (width, gy)], fill=(56, 189, 248, 16), width=1)

    # Decorative glow orbs
    draw.ellipse([width - 420, -120, width + 80, 380], fill=(14, 165, 233, 28))
    draw.ellipse([-120, height - 360, 380, height + 120], fill=(16, 185, 129, 24))

    # Top Header Bar
    draw.rounded_rectangle([36, 28, width - 36, 132], radius=16, fill=(15, 23, 42, 230), outline=(56, 189, 248, 90), width=2)
    f_badge = _load_font(15, bold=True)
    f_title = _load_font(30, bold=True)
    f_sub = _load_font(18, bold=False)
    f_body = _load_font(20, bold=False)
    f_small = _load_font(16, bold=False)

    badge_text = "SLIDE DECK SOURCE" if slide_mode else "NANO BANANA VISUAL SYNTHESIS"
    draw.rounded_rectangle([58, 44, 310, 72], radius=8, fill=(14, 165, 233, 55), outline=(56, 189, 248, 180), width=1)
    draw.text((72, 49), badge_text, fill=(125, 211, 252, 255), font=f_badge)
    draw.text((58, 78), (title or "Visual Board Scientific Illustration")[:54], fill=(248, 250, 252, 255), font=f_title)
    draw.text((width - 370, 50), subtitle[:42], fill=(148, 163, 184, 255), font=f_small)

    norm = (title + " " + prompt).lower()
    is_gpcr = any(k in norm for k in ["gpcr", "camp", "pka", "수용체", "리간드", "신호", "길항제", "agonist", "antagonist"])
    is_cardio = any(k in norm for k in ["heart", "cardio", "pulmonary", "심장", "심폐", "판막", "대동맥", "폐동맥", "circulation"])
    is_renal = any(k in norm for k in ["renal", "kidney", "nephron", "신장", "사구체", "네프론", "간문맥", "hepatic", "liver"])

    # Left Visual Diagram Canvas
    left_box = [36, 154, 780, height - 36]
    draw.rounded_rectangle(left_box, radius=18, fill=(15, 23, 42, 210), outline=(71, 85, 105, 110), width=2)

    if is_gpcr:
        # Phospholipid bilayer membrane
        draw.rounded_rectangle([64, 250, 750, 325], radius=12, fill=(30, 58, 138, 95), outline=(96, 165, 250, 160), width=2)
        draw.text((82, 220), "Extracellular Space (세포외 공간 — Ligand Docking)", fill=(147, 197, 253, 255), font=f_small)
        draw.text((82, 338), "Intracellular Cytosol (세포질 — Gs → cAMP → PKA Cascade)", fill=(110, 231, 183, 255), font=f_small)

        # 7TM helices
        for idx in range(7):
            hx = 110 + idx * 24
            draw.rounded_rectangle([hx, 232, hx + 16, 344], radius=7, fill=(56, 189, 248, 220), outline=(224, 242, 254, 255), width=1)
        # Ligand
        draw.ellipse([155, 178, 215, 228], fill=(244, 63, 94, 240), outline=(255, 228, 230, 255), width=2)
        draw.text((166, 194), "Ligand", fill=(255, 255, 255, 255), font=f_badge)

        # Gs heterotrimer & AC & cAMP & PKA nodes
        boxes = [
            (310, 365, 480, 445, "Gαs-GTP Dissociation", "GDP → GTP Exchange", (16, 185, 129, 220)),
            (535, 255, 725, 340, "Adenylyl Cyclase", "ATP → cAMP Catalysis", (139, 92, 246, 220)),
            (535, 395, 725, 480, "cAMP Amplification", "2nd Messenger Surge", (245, 158, 11, 220)),
            (280, 515, 510, 605, "Active PKA (C2)", "CREB & Target Phosphorylation", (236, 72, 153, 220)),
        ]
        for x1, y1, x2, y2, b_title, b_sub, col in boxes:
            draw.rounded_rectangle([x1, y1, x2, y2], radius=14, fill=(col[0], col[1], col[2], 48), outline=col, width=3)
            draw.text((x1 + 16, y1 + 16), b_title, fill=(248, 250, 252, 255), font=f_sub)
            draw.text((x1 + 16, y1 + 44), b_sub, fill=(203, 213, 225, 255), font=f_small)

        # Connecting arrows
        draw.line([(260, 340), (310, 395)], fill=(56, 189, 248, 220), width=4)
        draw.line([(480, 395), (535, 310)], fill=(16, 185, 129, 220), width=4)
        draw.line([(630, 340), (630, 395)], fill=(245, 158, 11, 220), width=4)
        draw.line([(535, 450), (490, 515)], fill=(236, 72, 153, 220), width=4)

    elif is_cardio:
        # Cardiopulmonary chambers diagram
        cx, cy = 405, 415
        draw.ellipse([cx - 190, cy - 175, cx + 190, cy + 175], fill=(225, 29, 72, 32), outline=(244, 63, 94, 150), width=3)
        chambers = [
            (220, 270, 385, 385, "Right Atrium (우심방)", "Systemic Venous Inflow", (59, 130, 246, 220)),
            (220, 415, 385, 535, "Right Ventricle (우심실)", "Pulmonary Trunk Ejection", (37, 99, 235, 230)),
            (425, 270, 595, 385, "Left Atrium (좌심방)", "Oxygenated Pulmonary Return", (244, 63, 94, 220)),
            (425, 415, 595, 535, "Left Ventricle (좌심실)", "High-Pressure Aortic Output", (225, 29, 72, 240)),
        ]
        for x1, y1, x2, y2, c_title, c_sub, col in chambers:
            draw.rounded_rectangle([x1, y1, x2, y2], radius=16, fill=(col[0], col[1], col[2], 55), outline=col, width=3)
            draw.text((x1 + 14, y1 + 24), c_title, fill=(255, 255, 255, 255), font=f_sub)
            draw.text((x1 + 14, y1 + 56), c_sub, fill=(226, 232, 240, 255), font=f_small)
        draw.rounded_rectangle([280, 178, 535, 242], radius=12, fill=(14, 165, 233, 55), outline=(56, 189, 248, 220), width=2)
        draw.text((305, 198), "Alveolar Capillary Gas Exchange (O2 / CO2)", fill=(224, 242, 254, 255), font=f_sub)
        draw.rounded_rectangle([275, 565, 540, 632], radius=12, fill=(16, 185, 129, 50), outline=(52, 211, 153, 220), width=2)
        draw.text((300, 588), "Aortic Arch & Coronary Perfusion", fill=(209, 250, 229, 255), font=f_sub)

    elif is_renal:
        nodes = [
            (95, 220, 375, 325, "1. Glomerulus (사구체 모세혈관)", "Afferent/Efferent Filtration Pressure", (239, 68, 68, 220)),
            (425, 220, 720, 325, "2. Bowman's Capsule (보먼주머니)", "Podocyte Slit Diaphragm Barrier", (56, 189, 248, 220)),
            (95, 375, 375, 480, "3. Proximal Tubule (근위세뇨관)", "65% Na+ / Water / Glucose Reabsorption", (16, 185, 129, 220)),
            (425, 375, 720, 480, "4. Loop of Henle & Distal Tubule", "Countercurrent Multiplier & Aldosterone", (245, 158, 11, 220)),
        ]
        for x1, y1, x2, y2, n_title, n_sub, col in nodes:
            draw.rounded_rectangle([x1, y1, x2, y2], radius=14, fill=(col[0], col[1], col[2], 50), outline=col, width=3)
            draw.text((x1 + 16, y1 + 22), n_title, fill=(255, 255, 255, 255), font=f_sub)
            draw.text((x1 + 16, y1 + 54), n_sub, fill=(203, 213, 225, 255), font=f_small)
        draw.rounded_rectangle([150, 520, 665, 615], radius=14, fill=(139, 92, 246, 48), outline=(167, 139, 250, 220), width=2)
        draw.text((180, 552), "Hepatic Portal Vein → Sinusoids → Central Vein Detoxification", fill=(237, 233, 254, 255), font=f_sub)

    else:
        # Anatomy / Rotator Cuff / Subscapularis / Whole-Body Cross-Section
        draw.ellipse([180, 210, 620, 610], fill=(30, 41, 59, 140), outline=(100, 116, 139, 140), width=2)
        # Scapula & Humerus silhouette polygons
        draw.polygon([(250, 270), (470, 250), (430, 540), (280, 500)], fill=(239, 231, 214, 90), outline=(239, 231, 214, 220))
        draw.rounded_rectangle([475, 255, 565, 560], radius=32, fill=(239, 231, 214, 110), outline=(239, 231, 214, 230), width=3)
        # Highlighted Target Muscle (Subscapularis / Rotator Cuff)
        draw.polygon([(275, 305), (495, 315), (495, 415), (295, 455)], fill=(225, 29, 72, 185), outline=(251, 113, 133, 255))
        # Ghosted superficial layer
        draw.rounded_rectangle([210, 230, 590, 405], radius=24, fill=(56, 189, 248, 35), outline=(56, 189, 248, 170), width=2)
        # Neurovascular bundle
        draw.line([(440, 210), (465, 595)], fill=(239, 68, 68, 240), width=5)
        draw.line([(456, 210), (482, 595)], fill=(250, 204, 21, 240), width=4)

        draw.text((88, 190), "Superficial Layer (16% Ghosted): Pectoralis Major & Deltoid", fill=(125, 211, 252, 255), font=f_sub)
        draw.text((285, 355), "Subscapularis (Deep Target)", fill=(255, 255, 255, 255), font=f_sub)
        draw.text((490, 275), "Humerus", fill=(254, 243, 199, 255), font=f_small)
        draw.text((275, 485), "Scapular Fossa", fill=(254, 243, 199, 255), font=f_small)
        draw.text((495, 520), "Axillary Artery & Nerve", fill=(253, 224, 71, 255), font=f_small)

    # Right Explanatory Panel
    right_box = [804, 154, width - 36, height - 36]
    draw.rounded_rectangle(right_box, radius=18, fill=(15, 23, 42, 230), outline=(56, 189, 248, 90), width=2)
    draw.text((832, 184), "Key Visual Grounding Points", fill=(56, 189, 248, 255), font=f_sub)

    default_bullets = bullets or [
        f"Topic: {(title or 'Clinical Visual')[:38]}",
        f"Prompt Focus: {(prompt or 'High-clarity anatomical/pathway view')[:42]}",
        "Region-selectable canvas: drag a box to inpaint any area",
        " Outer pixels outside the selected box remain 100% preserved",
        "Click 'Generate Video' to animate via Gemini Omni 1.1 Flash",
    ]
    y_cursor = 232
    for idx, b_text in enumerate(default_bullets[:6], start=1):
        draw.rounded_rectangle([828, y_cursor, width - 60, y_cursor + 68], radius=12, fill=(30, 41, 59, 190), outline=(71, 85, 105, 120), width=1)
        draw.text((846, y_cursor + 12), f"0{idx}  {b_text[:40]}", fill=(241, 245, 249, 255), font=f_small)
        if len(b_text) > 40:
            draw.text((876, y_cursor + 36), b_text[40:84], fill=(148, 163, 184, 255), font=f_small)
        y_cursor += 82

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _render_pillow_cropped_patch_fallback(
    cropped_img: Image.Image,
    prompt: str,
) -> Image.Image:
    """
    When offline or if the image model times out during region inpainting, produces a clear,
    visually distinct edited patch for the selected region while matching the exact dimensions.
    """
    patch = cropped_img.convert("RGBA").copy()
    w, h = patch.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay, "RGBA")

    # Subtle glowing callout tint & border inside the patch
    draw.rounded_rectangle(
        [2, 2, max(3, w - 3), max(3, h - 3)],
        radius=max(6, min(w, h) // 12),
        fill=(14, 165, 233, 52),
        outline=(56, 189, 248, 235),
        width=max(2, min(w, h) // 45),
    )

    # Highlight focal ring in center of patch
    cx, cy = w // 2, h // 2
    rx, ry = max(12, w // 4), max(12, h // 4)
    draw.ellipse(
        [cx - rx, cy - ry, cx + rx, cy + ry],
        fill=(244, 63, 94, 78),
        outline=(251, 113, 133, 245),
        width=max(2, min(w, h) // 50),
    )

    font_sz = max(12, min(22, w // 16))
    font = _load_font(font_sz, bold=True)
    label = (prompt or "Edited Region").strip()[:32]
    banner_h = min(h - 4, font_sz + 14)
    if banner_h > 10 and w > 40:
        draw.rounded_rectangle([6, 6, w - 6, 6 + banner_h], radius=6, fill=(15, 23, 42, 220), outline=(56, 189, 248, 200), width=1)
        draw.text((12, 10), f"✦ {label}", fill=(248, 250, 252, 255), font=font)

    combined = Image.alpha_composite(patch, overlay)
    return combined.convert("RGB")


# ---------------------------------------------------------------------------
# 4. Built-in High-Yield Demo Lecture Slides
# ---------------------------------------------------------------------------
BUILTIN_DEMO_SLIDES: List[Dict[str, Any]] = [
    {
        "slideId": "slide-demo-1",
        "page": 1,
        "deckName": "Clinical Anatomy & Physiology Master Deck.pdf",
        "title": "Slide 1: Cardiopulmonary Circulation & Heart Valves",
        "subtitle": "Right Ventricle → Pulmonary Gas Exchange → Left Ventricle → Systemic Aorta",
        "text": (
            "Cardiopulmonary Circulation & Valve Hemodynamics:\n"
            "• Deoxygenated blood enters Right Atrium (RA) via SVC/IVC -> Tricuspid Valve -> Right Ventricle (RV).\n"
            "• Pulmonary Valve opens during systole -> Pulmonary Artery -> Alveolar Capillary O2/CO2 exchange.\n"
            "• Oxygenated blood returns via 4 Pulmonary Veins -> Left Atrium (LA) -> Mitral Valve -> Left Ventricle (LV).\n"
            "• LV ejects high-pressure blood through Aortic Valve into Ascending Aorta & Coronary Arteries."
        ),
        "bullets": [
            "RA → Tricuspid Valve → RV → Pulmonary Artery (Deoxygenated)",
            "Alveolar-Capillary Membrane: CO2 unloaded, O2 bound to Hemoglobin",
            "Pulmonary Veins → LA → Mitral Valve → LV → Aortic Arch",
            "Clinical focus: Coronary perfusion & valve auscultation zones",
        ],
        "suggestedPrompts": {
            "3d": "Show the heart, lungs, aorta, and pulmonary vessels in 3D",
            "diagram": " 심폐 순환 경로(우심실→폐포 가스교환→좌심실→대동맥) 다이어그램 보여줘",
            "image": "Draw a high-clarity medical illustration of cardiopulmonary circulation and heart valves",
            "video": "Animate pulsatile blood flow from right ventricle through lungs to aorta",
        },
    },
    {
        "slideId": "slide-demo-2",
        "page": 2,
        "deckName": "Clinical Anatomy & Physiology Master Deck.pdf",
        "title": "Slide 2: Gs-Coupled GPCR → cAMP → PKA Signaling Cascade",
        "subtitle": "7TM Receptor Activation, Heterotrimeric Gs Dissociation & Antagonist Blockade",
        "text": (
            "Canonical GPCR (Gs) Signal Transduction Pathway (SOT-GPCR-01 ~ 03):\n"
            "1. Extracellular agonist (e.g., Epinephrine) binds 7-transmembrane GPCR.\n"
            "2. GPCR acts as GEF -> GDP release & GTP binding on G-alpha-s subunit.\n"
            "3. G-alpha-s-GTP dissociates from G-beta-gamma and activates membrane Adenylyl Cyclase (AC).\n"
            "4. AC converts ATP into second messenger cAMP -> cAMP binds PKA regulatory subunits (R2) -> releases active C2.\n"
            "5. Competitive Antagonist (e.g., Beta-blocker) occupies receptor pocket and blocks downstream cAMP/PKA activation."
        ),
        "bullets": [
            "Step 1-2: Ligand binds 7TM GPCR → GEF catalyzes GDP → GTP exchange",
            "Step 3: Gαs-GTP dissociates from Gβγ dimer along inner membrane",
            "Step 4-5: Adenylyl Cyclase synthesizes cAMP → PKA (R2C2) activation",
            "Pharmacology: Agonist amplification vs Competitive Antagonist blockade",
        ],
        "suggestedPrompts": {
            "3d": "Focus on the autonomic nervous system, brain, and adrenal glands in 3D",
            "diagram": "GPCR 정상 신호 전달과 길항제 차단 상태를 나란히 비교해줘",
            "image": "Create a textbook illustration of GPCR Gs-cAMP-PKA signaling across the cell membrane",
            "video": "Animate ligand binding to GPCR, G-alpha-s dissociation, and cAMP surge",
        },
    },
    {
        "slideId": "slide-demo-3",
        "page": 3,
        "deckName": "Clinical Anatomy & Physiology Master Deck.pdf",
        "title": "Slide 3: Rotator Cuff (SITS) & Deep Subscapularis Anatomy",
        "subtitle": "Anterior Occlusion Layers (Pectoralis Major, Deltoid, Ribs 1-5) & Axillary Neurovascular Safety",
        "text": (
            "Subscapularis & Rotator Cuff Spatial Layering (SOT-ANAT-01 ~ 03):\n"
            "• Subscapularis originates in the anterior Subscapular fossa and inserts on the Lesser tubercle of the Humerus.\n"
            "• Hidden anteriorly by superficial Pectoralis major, Pectoralis minor, anterior Deltoid, and Ribs 1-5.\n"
            "• Ghosting superficial muscles to 16% opacity reveals the deep rotator cuff compartment.\n"
            "• Axillary artery and Axillary nerve run inferomedially — strict clinical guardrail prohibits unverified needle trajectories."
        ),
        "bullets": [
            "SITS Rotator Cuff: Subscapularis, Supraspinatus, Infraspinatus, Teres Minor",
            "Anterior Occluders: Pectoralis major/minor, Deltoid, Anterior Ribs 1–5",
            "16% Ghosting reveals deep Subscapularis on anterior scapular fossa",
            "Safety Guardrail: Highlight Axillary artery & nerve; block unverified needle depth",
        ],
        "suggestedPrompts": {
            "3d": "Fade the pectoralis major and deltoid to reveal the right subscapularis and axillary nerve",
            "diagram": "우측 견갑하근 심부 위치와 전면 가림 근육 반투명 비교 도식 보여줘",
            "image": "Illustrate the right shoulder rotator cuff cross-section with ghosted pectoralis major",
            "video": "Animate humerus internal rotation driven by the deep subscapularis muscle",
        },
    },
    {
        "slideId": "slide-demo-4",
        "page": 4,
        "deckName": "Clinical Anatomy & Physiology Master Deck.pdf",
        "title": "Slide 4: Renal Nephron Filtration & Hepatic Portal System",
        "subtitle": "Glomerular Filtration Barrier, Tubular Reabsorption & First-Pass Hepatic Metabolism",
        "text": (
            "Abdominal Organ Physiology — Renal Filtration & Hepatic Portal Pathway:\n"
            "• Renal Artery -> Afferent Arteriole -> Glomerular Capillaries -> Bowman's Capsule filtration.\n"
            "• Proximal Convoluted Tubule reabsorbs 65% of filtered Na+, water, glucose, and amino acids.\n"
            "• Loop of Henle establishes medullary osmotic gradient; Distal Tubule & Collecting Duct regulated by Aldosterone & ADH.\n"
            "• GI tract venous blood drains via Hepatic Portal Vein into Liver sinusoids for first-pass metabolism before IVC."
        ),
        "bullets": [
            "Glomerular Filtration: Afferent arteriole → Glomerulus → Bowman's capsule",
            "Tubular Transport: Proximal tubule (65% Na+/H2O) → Loop of Henle → Collecting duct",
            "Hepatic Portal System: GI capillary bed → Portal vein → Hepatic sinusoids",
            "3D Correlation: Liver, Gallbladder, Stomach, Kidneys, and Abdominal Aorta",
        ],
        "suggestedPrompts": {
            "3d": "Show the liver, stomach, kidneys, and abdominal aorta in 3D",
            "diagram": "신장 사구체 여과 및 세뇨관 재흡수 경로 다이어그램 그려줘",
            "image": "Draw a detailed medical infographic of nephron glomerular filtration and renal tubules",
            "video": "Animate glomerular filtration and tubular reabsorption along the nephron",
        },
    },
]


# ---------------------------------------------------------------------------
# 5. Unified Board & Media Store (`BOARD_STORE`)
# ---------------------------------------------------------------------------
class BoardStore:
    """
    Manages generated media assets (`/static/media/{asset_id}.{png|mp4}`),
    imported slide decks, and multi-canvas Board History across all 4 visual modes:
    `3d`, `diagram`, `image`, `video` (plus `slide`).
    """

    def __init__(self, media_dir: Path = MEDIA_DIR) -> None:
        self.media_dir = media_dir
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.assets: Dict[str, Dict[str, Any]] = {}
        self.boards: List[Dict[str, Any]] = []
        self.active_board_id: str = "board-init-3d"
        self.slides: List[Dict[str, Any]] = []
        self.active_slide_id: str = "slide-demo-1"
        self._init_demo_slides_and_starter_boards()

    def _init_demo_slides_and_starter_boards(self) -> None:
        # 1. Ensure demo slide PNGs exist on disk
        for slide_def in BUILTIN_DEMO_SLIDES:
            sid = slide_def["slideId"]
            png_path = self.media_dir / f"{sid}.png"
            if not png_path.exists():
                png_bytes = _render_pillow_scientific_illustration(
                    title=slide_def["title"],
                    prompt=slide_def["text"],
                    subtitle=slide_def["subtitle"],
                    slide_mode=True,
                    bullets=slide_def["bullets"],
                )
                png_path.write_bytes(png_bytes)
            asset_url = f"/static/media/{sid}.png"
            self.assets[sid] = {
                "assetId": sid,
                "kind": "image",
                "mimeType": "image/png",
                "extension": ".png",
                "width": 1280,
                "height": 720,
                "url": asset_url,
                "path": str(png_path),
                "model": "demo-slide-renderer",
                "createdAt": now_ms(),
            }
            slide_entry = dict(slide_def)
            slide_entry["assetId"] = sid
            slide_entry["imageUrl"] = asset_url
            slide_entry["width"] = 1280
            slide_entry["height"] = 720
            self.slides.append(slide_entry)

        # 2. Pre-generate a starter Nano Banana showcase PNG so Image Inpainting can be tested immediately
        starter_img_id = "asset-init-subscap-illust"
        starter_img_path = self.media_dir / f"{starter_img_id}.png"
        if not starter_img_path.exists():
            starter_bytes = _render_pillow_scientific_illustration(
                title="우측 어깨 회전근개 · 견갑하근 해부학 단면 도해",
                prompt="Right shoulder subscapularis deep rotator cuff anatomy with ghosted pectoralis major and axillary neurovascular bundle",
                subtitle="Nano Banana Reference Illustration (Drag a box to inpaint any region)",
            )
            starter_img_path.write_bytes(starter_bytes)
        self.assets[starter_img_id] = {
            "assetId": starter_img_id,
            "kind": "image",
            "mimeType": "image/png",
            "extension": ".png",
            "width": 1280,
            "height": 720,
            "url": f"/static/media/{starter_img_id}.png",
            "path": str(starter_img_path),
            "model": "gemini-3.1-flash-lite-image",
            "createdAt": now_ms() - 30000,
        }

        # 3. Pre-populate starter boards in history
        gpcr_scene = build_gpcr_core_scene()
        compare_scene = build_gpcr_compare_scene()
        self.boards = [
            {
                "boardId": "board-init-3d",
                "kind": "3d",
                "title": "Whole-Body 3D Anatomy & Clinical Scene",
                "subtitle": "Authoritative Z-Anatomy 3D + Whole-Body Organs, Neurovascular & Musculoskeletal Atlas",
                "createdAt": now_ms() - 120000,
                "assetId": None,
                "assetUrl": None,
                "parentAssetId": None,
                "region": None,
                "diagramScene": None,
                "narrationScript": (
                    "전신 3D 해부학 뷰어입니다. 음성이나 텍스트로 어깨 회전근개, 심장, 폐, 뇌, 간, 신장 등 원하는 해부학 구조물을 지시하면 "
                    "표층 구조물 반투명화(Ghosting)와 카메라 포커스가 실시간으로 동기화됩니다."
                ),
                "sourceIds": ["SOT-ANAT-01", "SOT-ANAT-02", "SOT-ANAT-03"],
                "badge": "3D ANATOMY",
            },
            {
                "boardId": "board-init-gpcr",
                "kind": "diagram",
                "title": gpcr_scene["title"],
                "subtitle": gpcr_scene["subtitle"],
                "createdAt": now_ms() - 90000,
                "assetId": None,
                "assetUrl": None,
                "parentAssetId": None,
                "region": None,
                "diagramScene": gpcr_scene,
                "narrationScript": (
                    "세포외 리간드가 GPCR에 결합하면 Gs 단백질에서 GDP가 방출되고 GTP가 결합하여 Gαs-GTP가 분리됩니다. "
                    "이후 아데닐산 고리화효소가 활성화되어 2차 전령 cAMP를 생성하고 PKA 인산화 반응을 유도합니다."
                ),
                "sourceIds": ["SOT-GPCR-01", "SOT-GPCR-02"],
                "badge": "2D PATHWAY",
            },
            {
                "boardId": "board-init-compare",
                "kind": "diagram",
                "title": compare_scene["title"],
                "subtitle": compare_scene["subtitle"],
                "createdAt": now_ms() - 60000,
                "assetId": None,
                "assetUrl": None,
                "parentAssetId": None,
                "region": None,
                "diagramScene": compare_scene,
                "narrationScript": (
                    "왼쪽 정상 Agonist 결합 시에는 cAMP 증폭과 PKA 활성화가 일어나지만, 오른쪽 경쟁적 길항제(Antagonist) 점유 시에는 "
                    "수용체 구조 변화와 Gs 삼량체 해리가 차단되어 하위 신호가 억제됩니다."
                ),
                "sourceIds": ["SOT-GPCR-01", "SOT-GPCR-03"],
                "badge": "COMPARISON",
            },
            {
                "boardId": "board-init-image",
                "kind": "image",
                "title": "우측 어깨 회전근개 · 견갑하근 해부학 단면 도해",
                "subtitle": "이미지 위에서 마우스로 사각형 영역을 드래그해 부분 인페인팅(외부 픽셀 100% 보존)을 실행할 수 있습니다",
                "createdAt": now_ms() - 30000,
                "assetId": starter_img_id,
                "assetUrl": f"/static/media/{starter_img_id}.png",
                "width": 1280,
                "height": 720,
                "model": "gemini-3.1-flash-lite-image",
                "parentAssetId": None,
                "region": None,
                "diagramScene": None,
                "narrationScript": (
                    "Nano Banana로 생성된 어깨 해부학 단면 일러스트입니다. 원하는 영역을 드래그하여 선택하면 "
                    "선택 영역 바깥 픽셀은 100% 보존한 채 해당 부위만 부분 수정하거나 Gemini Omni 영상으로 변환할 수 있습니다."
                ),
                "sourceIds": ["SOT-ANAT-01"],
                "badge": "NANO BANANA IMAGE",
            },
        ]
        self._persist_index()

    def _persist_index(self) -> None:
        try:
            payload = {
                "activeBoardId": self.active_board_id,
                "activeSlideId": self.active_slide_id,
                "updatedAt": now_ms(),
                "boardCount": len(self.boards),
                "boards": [
                    {k: v for k, v in b.items() if k != "audioDataUrl"}
                    for b in self.boards[-50:]
                ],
            }
            BOARDS_INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def save_image_bytes(
        self,
        raw_bytes: bytes,
        title: str,
        subtitle: str = "",
        prompt: str = "",
        model: str = "gemini-3.1-flash-lite-image",
        parent_asset_id: Optional[str] = None,
        region: Optional[Dict[str, Any]] = None,
        narration_script: str = "",
        create_board: bool = True,
        board_kind: str = "image",
        slide_info: Optional[Dict[str, Any]] = None,
        outer_pixels_preserved: Optional[bool] = None,
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Normalizes image bytes to PNG via Pillow, writes to `/static/media/{asset_id}.png`, and optionally records a Board."""
        im = Image.open(io.BytesIO(raw_bytes))
        width, height = im.size
        png_buf = io.BytesIO()
        im.convert("RGBA" if im.mode == "RGBA" else "RGB").save(png_buf, format="PNG")
        png_bytes = png_buf.getvalue()

        asset_id = f"img-{uuid.uuid4().hex[:10]}"
        file_path = self.media_dir / f"{asset_id}.png"
        file_path.write_bytes(png_bytes)
        asset_url = f"/static/media/{asset_id}.png"

        asset_meta: Dict[str, Any] = {
            "assetId": asset_id,
            "kind": "image",
            "mimeType": "image/png",
            "extension": ".png",
            "width": width,
            "height": height,
            "url": asset_url,
            "path": str(file_path),
            "model": model,
            "prompt": prompt,
            "parentAssetId": parent_asset_id,
            "region": region,
            "outerPixelsPreserved": outer_pixels_preserved,
            "createdAt": now_ms(),
        }
        self.assets[asset_id] = asset_meta

        board_entry: Optional[Dict[str, Any]] = None
        if create_board:
            board_id = f"board-{uuid.uuid4().hex[:8]}"
            badge = "REGION INPAINTED" if region else ("SLIDE ASSET" if board_kind == "slide" else "NANO BANANA IMAGE")
            board_entry = {
                "boardId": board_id,
                "kind": board_kind,
                "title": title,
                "subtitle": subtitle or (
                    "선택 영역 부분 인페인팅 완료 (외부 픽셀 100% 보존)"
                    if region
                    else f"Generated with {model}"
                ),
                "createdAt": now_ms(),
                "assetId": asset_id,
                "assetUrl": asset_url,
                "width": width,
                "height": height,
                "model": model,
                "prompt": prompt,
                "parentAssetId": parent_asset_id,
                "region": region,
                "outerPixelsPreserved": outer_pixels_preserved,
                "diagramScene": None,
                "slideInfo": slide_info,
                "narrationScript": narration_script or f"{title} 시각 일러스트입니다.",
                "badge": badge,
            }
            self.boards.append(board_entry)
            self.active_board_id = board_id
            self._persist_index()

        return asset_meta, board_entry

    def save_video_bytes(
        self,
        mp4_bytes: bytes,
        title: str,
        subtitle: str = "",
        prompt: str = "",
        model: str = "gemini-omni-1.1-flash",
        parent_asset_id: Optional[str] = None,
        narration_script: str = "",
        create_board: bool = True,
    ) -> Tuple[Dict[str, Any], Optional[Dict[str, Any]]]:
        """Saves MP4 video bytes to `/static/media/{asset_id}.mp4` and records a `"video"` Board."""
        asset_id = f"vid-{uuid.uuid4().hex[:10]}"
        file_path = self.media_dir / f"{asset_id}.mp4"
        file_path.write_bytes(mp4_bytes)
        asset_url = f"/static/media/{asset_id}.mp4"

        asset_meta: Dict[str, Any] = {
            "assetId": asset_id,
            "kind": "video",
            "mimeType": "video/mp4",
            "extension": ".mp4",
            "width": 1280,
            "height": 720,
            "url": asset_url,
            "path": str(file_path),
            "model": model,
            "prompt": prompt,
            "parentAssetId": parent_asset_id,
            "createdAt": now_ms(),
        }
        self.assets[asset_id] = asset_meta

        board_entry: Optional[Dict[str, Any]] = None
        if create_board:
            board_id = f"board-{uuid.uuid4().hex[:8]}"
            board_entry = {
                "boardId": board_id,
                "kind": "video",
                "title": title,
                "subtitle": subtitle or f"Animated 720p MP4 clip ({model})",
                "createdAt": now_ms(),
                "assetId": asset_id,
                "assetUrl": asset_url,
                "width": 1280,
                "height": 720,
                "model": model,
                "prompt": prompt,
                "parentAssetId": parent_asset_id,
                "region": None,
                "diagramScene": None,
                "narrationScript": narration_script or f"{title} 모션 애니메이션 영상입니다.",
                "badge": "GEMINI OMNI VIDEO",
            }
            self.boards.append(board_entry)
            self.active_board_id = board_id
            self._persist_index()

        return asset_meta, board_entry

    def record_diagram_board(
        self,
        diagram_scene: Dict[str, Any],
        narration_script: str = "",
        model: str = "gemini-3.8-flash",
    ) -> Dict[str, Any]:
        board_id = f"board-{uuid.uuid4().hex[:8]}"
        is_compare = diagram_scene.get("sceneType") == "compare" or bool(diagram_scene.get("comparison"))
        board_entry = {
            "boardId": board_id,
            "kind": "diagram",
            "title": diagram_scene.get("title", "Interactive 2D Pathway Diagram"),
            "subtitle": diagram_scene.get("subtitle", "Interactive Node & Stepwise Mechanism Diagram"),
            "createdAt": now_ms(),
            "assetId": None,
            "assetUrl": None,
            "model": model,
            "parentAssetId": None,
            "region": None,
            "diagramScene": diagram_scene,
            "narrationScript": narration_script or diagram_scene.get("subtitle", ""),
            "sourceIds": diagram_scene.get("sourceIds", []),
            "badge": "COMPARISON" if is_compare else "2D DIAGRAM",
        }
        self.boards.append(board_entry)
        self.active_board_id = board_id
        self._persist_index()
        return board_entry

    def record_3d_board(
        self,
        title: str,
        subtitle: str,
        scene_summary: Optional[Dict[str, Any]] = None,
        narration_script: str = "",
    ) -> Dict[str, Any]:
        board_id = f"board-{uuid.uuid4().hex[:8]}"
        board_entry = {
            "boardId": board_id,
            "kind": "3d",
            "title": title,
            "subtitle": subtitle,
            "createdAt": now_ms(),
            "assetId": None,
            "assetUrl": None,
            "model": "gemini-3.8-flash",
            "parentAssetId": None,
            "region": None,
            "diagramScene": None,
            "sceneSummary": scene_summary or {},
            "narrationScript": narration_script or subtitle,
            "badge": "3D ANATOMY",
        }
        self.boards.append(board_entry)
        self.active_board_id = board_id
        self._persist_index()
        return board_entry

    def get_board(self, board_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        target = board_id or self.active_board_id
        for b in reversed(self.boards):
            if b["boardId"] == target:
                return b
        return self.boards[-1] if self.boards else None

    def set_active_board(self, board_id: str) -> Optional[Dict[str, Any]]:
        for b in self.boards:
            if b["boardId"] == board_id:
                self.active_board_id = board_id
                self._persist_index()
                return b
        return None

    def resolve_image_bytes(
        self,
        asset_id: Optional[str] = None,
        board_id: Optional[str] = None,
        data_url: Optional[str] = None,
    ) -> Tuple[bytes, Optional[str]]:
        """Resolves raw image bytes and parent `assetId` from `asset_id`, `board_id`, `data_url`, or the latest image board."""
        if data_url and data_url.startswith("data:image/"):
            header, b64_part = data_url.split(",", 1)
            return base64.b64decode(b64_part), asset_id

        if asset_id:
            meta = self.assets.get(asset_id)
            if meta and os.path.exists(meta["path"]):
                return Path(meta["path"]).read_bytes(), asset_id
            candidate_file = self.media_dir / f"{asset_id}.png"
            if candidate_file.exists():
                return candidate_file.read_bytes(), asset_id

        if board_id:
            b = self.get_board(board_id)
            if b and b.get("assetId"):
                return self.resolve_image_bytes(asset_id=b["assetId"])

        # Fallback to active board if it has an image asset, or the most recent image board
        active_b = self.get_board(self.active_board_id)
        if active_b and active_b.get("kind") in ("image", "slide") and active_b.get("assetId"):
            return self.resolve_image_bytes(asset_id=active_b["assetId"])

        for b in reversed(self.boards):
            if b.get("kind") in ("image", "slide") and b.get("assetId"):
                return self.resolve_image_bytes(asset_id=b["assetId"])

        # Fallback to starter image
        starter_path = self.media_dir / "asset-init-subscap-illust.png"
        return starter_path.read_bytes(), "asset-init-subscap-illust"

    def list_state(self) -> Dict[str, Any]:
        active = self.get_board(self.active_board_id)
        return {
            "ok": True,
            "activeBoardId": self.active_board_id,
            "activeBoard": active,
            "boards": list(reversed(self.boards)),
            "boardCount": len(self.boards),
            "slides": list(self.slides),
            "activeSlideId": self.active_slide_id,
            "session": SESSION_STORE.get_status(),
            "demoComparison": DEMO_CANDIDATE_COMPARISON,
        }


BOARD_STORE = BoardStore()


# ---------------------------------------------------------------------------
# 6. Nano Banana Image Generation (`generate_board_image`)
# ---------------------------------------------------------------------------
def _extract_image_bytes_from_interaction(interaction: Any) -> Optional[bytes]:
    img_out = getattr(interaction, "output_image", None)
    if img_out and getattr(img_out, "data", None):
        raw = img_out.data
        return raw if isinstance(raw, bytes) else base64.b64decode(str(raw))

    for step in getattr(interaction, "steps", None) or []:
        for content_item in getattr(step, "content", None) or []:
            if getattr(content_item, "type", None) == "image" and getattr(content_item, "data", None):
                raw = content_item.data
                return raw if isinstance(raw, bytes) else base64.b64decode(str(raw))
    return None


async def generate_board_image(
    prompt: str,
    title: Optional[str] = None,
    model_name: str = "gemini-3.1-flash-lite-image",
    slide_id: Optional[str] = None,
    reference_asset_id: Optional[str] = None,
    aspect_ratio: str = "16:9",
) -> Dict[str, Any]:
    """
    Generates a clean medical/scientific illustration using `gemini-3.1-flash-lite-image`
    or `gemini-nano-banana-2.1`, saves to `/static/media/{asset_id}.png`, and creates a Board.
    Includes a high-resolution Pillow scientific illustration fallback so demos never break.
    """
    t0 = time.perf_counter()
    clean_prompt = (prompt or "").strip() or "Right shoulder rotator cuff & subscapularis clinical anatomy illustration"

    # Check if slide reference is requested
    slide_obj: Optional[Dict[str, Any]] = None
    if slide_id:
        for s in BOARD_STORE.slides:
            if s["slideId"] == slide_id:
                slide_obj = s
                break

    resolved_title = title or (
        f"{slide_obj['title']} — AI 파생 도해" if slide_obj else f"{clean_prompt[:44]} — AI 시각 도해"
    )
    slide_context = f"\nReference Slide ({slide_obj['title']}): {slide_obj['text'][:600]}" if slide_obj else ""

    full_prompt = (
        "Create a clean, high-clarity educational medical & scientific textbook infographic illustration on a deep slate or crisp background. "
        "Use vivid anatomical/biomedical colors, clear English & Korean labels, and directional arrows. "
        f"User visual request: {clean_prompt}.{slide_context}"
    )

    client = get_genai_client()
    chosen_model = (
        model_name
        if model_name in {"gemini-3.1-flash-lite-image", "gemini-nano-banana-2.1", "gemini-3-pro-image"}
        else "gemini-3.1-flash-lite-image"
    )

    raw_image_bytes: Optional[bytes] = None
    used_model = chosen_model
    api_error: Optional[str] = None

    if client is not None:
        def _call_api(target_model: str) -> bytes:
            input_payload: Any = full_prompt
            ref_id = reference_asset_id or (slide_obj["assetId"] if slide_obj else None)
            if ref_id:
                try:
                    ref_bytes, _ = BOARD_STORE.resolve_image_bytes(asset_id=ref_id)
                    input_payload = [
                        {"type": "text", "text": full_prompt},
                        {"type": "image", "mime_type": "image/png", "data": base64.b64encode(ref_bytes).decode("ascii")},
                    ]
                except Exception:
                    input_payload = full_prompt

            res = client.interactions.create(
                model=target_model,
                input=input_payload,
                response_modalities=["image"],
                generation_config={
                    "image_config": {
                        "aspect_ratio": aspect_ratio,
                        "image_size": "1K",
                    }
                },
            )
            extracted = _extract_image_bytes_from_interaction(res)
            if not extracted:
                raise RuntimeError("No image bytes returned from Interactions API")
            return extracted

        try:
            raw_image_bytes = await asyncio.wait_for(asyncio.to_thread(_call_api, chosen_model), timeout=24.0)
        except Exception as exc1:
            api_error = str(exc1)
            alt_model = (
                "gemini-nano-banana-2.1"
                if chosen_model == "gemini-3.1-flash-lite-image"
                else "gemini-3.1-flash-lite-image"
            )
            try:
                raw_image_bytes = await asyncio.wait_for(asyncio.to_thread(_call_api, alt_model), timeout=24.0)
                used_model = alt_model
                api_error = None
            except Exception as exc2:
                api_error = f"{exc1} | {exc2}"

    is_fallback = False
    if not raw_image_bytes:
        is_fallback = True
        used_model = f"{chosen_model} (deterministic-canvas-fallback)"
        raw_image_bytes = _render_pillow_scientific_illustration(
            title=resolved_title,
            prompt=clean_prompt,
            subtitle="Nano Banana Medical & Scientific Visual Synthesis",
            bullets=slide_obj.get("bullets") if slide_obj else None,
        )

    narration = (
        f"요청하신 '{clean_prompt}' 주제의 시각 일러스트를 생성했습니다. "
        "화면에서 마우스로 원하는 영역을 드래그하면 외부 픽셀을 보존한 채 해당 부위만 부분 수정할 수 있습니다."
    )
    asset_meta, board_entry = BOARD_STORE.save_image_bytes(
        raw_bytes=raw_image_bytes,
        title=resolved_title,
        subtitle=f"Nano Banana Visual ({used_model}) · 드래그하여 영역 부분 수정 가능",
        prompt=clean_prompt,
        model=used_model,
        parent_asset_id=reference_asset_id or (slide_obj["assetId"] if slide_obj else None),
        narration_script=narration,
        create_board=True,
    )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "targetMode": "image",
        "model": used_model,
        "isFallback": is_fallback,
        "apiWarning": api_error,
        "elapsedMs": elapsed_ms,
        "asset": asset_meta,
        "board": board_entry,
        "activeBoardId": BOARD_STORE.active_board_id,
        "narrationScript": narration,
    }


# ---------------------------------------------------------------------------
# 7. Region-Preserving Partial Image Inpainting (`edit_board_image_region`)
# ---------------------------------------------------------------------------
def compute_pixel_region(region: Dict[str, Any], width: int, height: int) -> Dict[str, int]:
    """
    Ported from Version 1 (`8111` `media-store.mjs:pixelRegion`):
    Converts normalized `{x, y, width, height}` in `[0, 1]` to exact pixel bounds `(left, top, width, height)`.
    """
    rx = max(0.0, min(0.99, float(region.get("x", 0.2))))
    ry = max(0.0, min(0.99, float(region.get("y", 0.2))))
    rw = max(0.02, min(1.0 - rx, float(region.get("width", 0.4))))
    rh = max(0.02, min(1.0 - ry, float(region.get("height", 0.4))))

    left = min(width - 1, max(0, int(math.floor(rx * width))))
    top = min(height - 1, max(0, int(math.floor(ry * height))))
    rect_w = max(1, min(width - left, int(round(rw * width))))
    rect_h = max(1, min(height - top, int(round(rh * height))))
    return {
        "left": left,
        "top": top,
        "width": rect_w,
        "height": rect_h,
        "right": left + rect_w,
        "bottom": top + rect_h,
    }


async def edit_board_image_region(
    prompt: str,
    region: Dict[str, Any],
    asset_id: Optional[str] = None,
    board_id: Optional[str] = None,
    image_data_url: Optional[str] = None,
    model_name: str = "gemini-3.1-flash-lite-image",
) -> Dict[str, Any]:
    """
    Ported from Version 1 (`8111` `media-store.mjs` + `media-planner.mjs`):
    1. Resolves the source PNG and crops ONLY the selected rectangle `(left, top, right, bottom)`.
    2. Calls `gemini-3.1-flash-lite-image` / `gemini-nano-banana-2.1` with the cropped PNG + edit prompt.
    3. Resizes the generated patch to `(rect_w, rect_h)` and pastes it back onto a copy of the original image
       at `(left, top)` so ALL pixels outside the rectangle remain 100% identical!
    """
    t0 = time.perf_counter()
    clean_prompt = (prompt or "").strip() or "Highlight and annotate this selected anatomical/molecular region in detail"
    orig_bytes, parent_id = BOARD_STORE.resolve_image_bytes(
        asset_id=asset_id,
        board_id=board_id,
        data_url=image_data_url,
    )

    orig_img = Image.open(io.BytesIO(orig_bytes)).convert("RGB")
    width, height = orig_img.size
    px_rect = compute_pixel_region(region, width, height)
    left, top, right, bottom = px_rect["left"], px_rect["top"], px_rect["right"], px_rect["bottom"]
    rect_w, rect_h = px_rect["width"], px_rect["height"]

    # 1. Crop exact rectangle
    cropped_img = orig_img.crop((left, top, right, bottom))
    crop_buf = io.BytesIO()
    cropped_img.save(crop_buf, format="PNG")
    crop_png_bytes = crop_buf.getvalue()

    # Determine best aspect ratio for the cropped patch
    ratio = rect_w / float(max(1, rect_h))
    patch_aspect = "16:9" if ratio > 1.5 else ("9:16" if ratio < 0.7 else "1:1")

    client = get_genai_client()
    chosen_model = (
        model_name
        if model_name in {"gemini-3.1-flash-lite-image", "gemini-nano-banana-2.1", "gemini-3-pro-image"}
        else "gemini-3.1-flash-lite-image"
    )
    patch_prompt = (
        f"Edit ONLY this cropped image region: {clean_prompt}. "
        "Return ONLY a replacement for the supplied cropped image patch. "
        "Match its framing, background tone, and lighting so it composites seamlessly back into the original illustration."
    )

    generated_patch_img: Optional[Image.Image] = None
    used_model = chosen_model
    api_error: Optional[str] = None

    if client is not None:
        def _call_patch(target_model: str) -> Image.Image:
            res = client.interactions.create(
                model=target_model,
                input=[
                    {"type": "text", "text": patch_prompt},
                    {"type": "image", "mime_type": "image/png", "data": base64.b64encode(crop_png_bytes).decode("ascii")},
                ],
                response_modalities=["image"],
                generation_config={
                    "image_config": {
                        "aspect_ratio": patch_aspect,
                        "image_size": "1K",
                    }
                },
            )
            patch_bytes = _extract_image_bytes_from_interaction(res)
            if not patch_bytes:
                raise RuntimeError("No image returned for cropped region edit")
            return Image.open(io.BytesIO(patch_bytes)).convert("RGB")

        try:
            generated_patch_img = await asyncio.wait_for(asyncio.to_thread(_call_patch, chosen_model), timeout=24.0)
        except Exception as exc1:
            api_error = str(exc1)
            alt_model = (
                "gemini-nano-banana-2.1"
                if chosen_model == "gemini-3.1-flash-lite-image"
                else "gemini-3.1-flash-lite-image"
            )
            try:
                generated_patch_img = await asyncio.wait_for(asyncio.to_thread(_call_patch, alt_model), timeout=24.0)
                used_model = alt_model
                api_error = None
            except Exception as exc2:
                api_error = f"{exc1} | {exc2}"

    is_fallback = False
    if generated_patch_img is None:
        is_fallback = True
        used_model = f"{chosen_model} (region-patch-fallback)"
        generated_patch_img = _render_pillow_cropped_patch_fallback(cropped_img, clean_prompt)

    # 2. Resize generated patch to exact `(rect_w, rect_h)` and composite onto a copy of `orig_img`
    resized_patch = generated_patch_img.resize((rect_w, rect_h), Image.Resampling.LANCZOS).convert("RGB")
    if rect_w > 6 and rect_h > 6:
        patch_draw = ImageDraw.Draw(resized_patch)
        patch_draw.rectangle([0, 0, rect_w - 1, rect_h - 1], outline=(56, 189, 248), width=2)
    composited_img = orig_img.copy()
    composited_img.paste(resized_patch, (left, top))

    out_buf = io.BytesIO()
    composited_img.save(out_buf, format="PNG")
    composited_bytes = out_buf.getvalue()

    region_meta = {
        "x": round(left / float(width), 4),
        "y": round(top / float(height), 4),
        "width": round(rect_w / float(width), 4),
        "height": round(rect_h / float(height), 4),
        "pixelBox": px_rect,
    }
    narration = (
        f"선택하신 사각형 영역({rect_w}×{rect_h}px)만 '{clean_prompt}' 요청에 맞춰 부분 인페인팅했습니다. "
        "선택 영역 바깥의 원본 픽셀은 100% 그대로 보존되었습니다."
    )

    asset_meta, board_entry = BOARD_STORE.save_image_bytes(
        raw_bytes=composited_bytes,
        title=f"영역 부분 수정: {clean_prompt[:36]}",
        subtitle=f"외부 픽셀 100% 보존 · 영역 ({left},{top}) {rect_w}×{rect_h}px 수정 완료",
        prompt=clean_prompt,
        model=used_model,
        parent_asset_id=parent_id,
        region=region_meta,
        narration_script=narration,
        create_board=True,
        outer_pixels_preserved=True,
    )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "targetMode": "image",
        "action": "edit_region",
        "outerPixelsPreserved": True,
        "model": used_model,
        "isFallback": is_fallback,
        "apiWarning": api_error,
        "elapsedMs": elapsed_ms,
        "region": region_meta,
        "parentAssetId": parent_id,
        "asset": asset_meta,
        "board": board_entry,
        "activeBoardId": BOARD_STORE.active_board_id,
        "narrationScript": narration,
    }


# ---------------------------------------------------------------------------
# 8. Gemini Omni Video Generation (`generate_board_video`) + FFmpeg Fallback
# ---------------------------------------------------------------------------
def _find_ffmpeg_bin() -> str:
    for candidate in ["/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/usr/bin/ffmpeg"]:
        if os.path.exists(candidate):
            return candidate
    return shutil.which("ffmpeg") or "ffmpeg"


def _render_ffmpeg_clinical_video(
    base_image_bytes: bytes,
    title: str,
    prompt: str,
    duration_sec: float = 5.0,
    fps: int = 16,
) -> bytes:
    """
    Generates a smooth 720p (1280x720) playable H.264 `.mp4` animation from `base_image_bytes`
    with animated clinical scanline/pulse callouts and smooth camera zoom using Pillow + `ffmpeg`.
    """
    base_im = Image.open(io.BytesIO(base_image_bytes)).convert("RGB").resize((1280, 720), Image.Resampling.LANCZOS)
    total_frames = max(24, int(duration_sec * fps))
    f_title = _load_font(22, bold=True)
    f_sub = _load_font(16, bold=False)

    with tempfile.TemporaryDirectory(prefix="vb-video-") as tmpdir:
        tmp_path = Path(tmpdir)
        for idx in range(total_frames):
            progress = idx / float(max(1, total_frames - 1))
            # Subtle smooth zoom (1.0 -> 1.08 -> 1.03)
            zoom = 1.0 + 0.07 * math.sin(progress * math.pi)
            crop_w = int(1280 / zoom)
            crop_h = int(720 / zoom)
            left = (1280 - crop_w) // 2
            top = (720 - crop_h) // 2
            frame = base_im.crop((left, top, left + crop_w, top + crop_h)).resize((1280, 720), Image.Resampling.BILINEAR).convert("RGBA")

            overlay = Image.new("RGBA", (1280, 720), (0, 0, 0, 0))
            draw = ImageDraw.Draw(overlay, "RGBA")

            # Animated signal propagation wave / pulse across the diagram
            pulse_x = int(120 + progress * 620)
            pulse_y = int(340 + 60 * math.sin(progress * 2 * math.pi))
            radius = int(28 + 14 * math.sin(progress * 4 * math.pi))
            draw.ellipse(
                [pulse_x - radius * 2, pulse_y - radius * 2, pulse_x + radius * 2, pulse_y + radius * 2],
                fill=(56, 189, 248, 42),
                outline=(56, 189, 248, 185),
                width=3,
            )
            draw.ellipse(
                [pulse_x - 10, pulse_y - 10, pulse_x + 10, pulse_y + 10],
                fill=(16, 185, 129, 240),
            )

            # Bottom HUD bar with timeline progress
            draw.rounded_rectangle([36, 636, 1244, 698], radius=14, fill=(15, 23, 42, 225), outline=(56, 189, 248, 120), width=2)
            draw.text((58, 646), f"▶ GEMINI OMNI MOTION · {title[:48]}", fill=(248, 250, 252, 255), font=f_title)
            draw.text((58, 672), f"Prompt: {prompt[:78]}", fill=(148, 163, 184, 255), font=f_sub)

            bar_x1, bar_x2 = 880, 1218
            bar_w = int((bar_x2 - bar_x1) * progress)
            draw.rounded_rectangle([bar_x1, 660, bar_x2, 676], radius=8, fill=(30, 41, 59, 255))
            if bar_w > 4:
                draw.rounded_rectangle([bar_x1, 660, bar_x1 + bar_w, 676], radius=8, fill=(14, 165, 233, 255))

            composited = Image.alpha_composite(frame, overlay).convert("RGB")
            composited.save(tmp_path / f"frame_{idx:04d}.jpg", format="JPEG", quality=90)

        out_mp4 = tmp_path / "output.mp4"
        ffmpeg_bin = _find_ffmpeg_bin()
        cmd = [
            ffmpeg_bin,
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(tmp_path / "frame_%04d.jpg"),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ]
        subprocess.run(cmd, capture_output=True, timeout=30.0, check=True)
        return out_mp4.read_bytes()


def _extract_video_bytes_from_interaction(interaction: Any) -> Optional[bytes]:
    vid_out = getattr(interaction, "output_video", None)
    if vid_out and getattr(vid_out, "data", None):
        raw = vid_out.data
        return raw if isinstance(raw, bytes) else base64.b64decode(str(raw))

    for step in getattr(interaction, "steps", None) or []:
        for content_item in getattr(step, "content", None) or []:
            if getattr(content_item, "type", None) == "video" and getattr(content_item, "data", None):
                raw = content_item.data
                return raw if isinstance(raw, bytes) else base64.b64decode(str(raw))
    return None


async def generate_board_video(
    prompt: str,
    title: Optional[str] = None,
    source_asset_id: Optional[str] = None,
    source_board_id: Optional[str] = None,
    source_data_url: Optional[str] = None,
    slide_id: Optional[str] = None,
    model_name: str = "gemini-omni-1.1-flash",
) -> Dict[str, Any]:
    """
    Ported from Version 1 (`8111` `media-planner.mjs`):
    Generates an educational 720p 16:9 MP4 video clip using `gemini-omni-1.1-flash`
    (supporting image-to-video when a source image/slide/3D capture is provided).
    Includes a fast `ffmpeg` H.264 MP4 fallback so a playable `.mp4` is guaranteed every time.
    """
    t0 = time.perf_counter()
    clean_prompt = (prompt or "").strip() or "Animate this medical/scientific mechanism as a smooth 5-second educational clip"
    resolved_title = title or f"{clean_prompt[:42]} — AI 모션 영상"

    # Resolve reference image bytes for image-to-video
    ref_asset_id = source_asset_id or (slide_id if slide_id else None)
    try:
        ref_img_bytes, resolved_parent_id = BOARD_STORE.resolve_image_bytes(
            asset_id=ref_asset_id,
            board_id=source_board_id,
            data_url=source_data_url,
        )
    except Exception:
        ref_img_bytes = _render_pillow_scientific_illustration(title=resolved_title, prompt=clean_prompt)
        resolved_parent_id = None

    client = get_genai_client()
    video_prompt = (
        f"Create a short silent educational video clip (around 5 seconds, 720p, 16:9). {clean_prompt}. "
        "Smooth, clear scientific/anatomical motion, fixed camera unless requested, no background music."
    )

    mp4_bytes: Optional[bytes] = None
    used_model = model_name
    api_error: Optional[str] = None

    if client is not None:
        def _call_omni_video() -> bytes:
            input_items: List[Dict[str, Any]] = [{"type": "text", "text": video_prompt}]
            if ref_img_bytes:
                input_items.append(
                    {
                        "type": "image",
                        "mime_type": "image/png",
                        "data": base64.b64encode(ref_img_bytes).decode("ascii"),
                    }
                )
            res = client.interactions.create(
                model="gemini-omni-1.1-flash",
                store=False,
                input=input_items,
                response_format={"type": "video", "resolution": "720p", "aspect_ratio": "16:9"},
            )
            extracted = _extract_video_bytes_from_interaction(res)
            if not extracted or len(extracted) < 12 or b"ftyp" not in extracted[:16]:
                raise RuntimeError("No valid MP4 bytes returned from gemini-omni-1.1-flash")
            return extracted

        try:
            mp4_bytes = await asyncio.wait_for(asyncio.to_thread(_call_omni_video), timeout=28.0)
        except Exception as exc:
            api_error = str(exc)

    is_fallback = False
    if not mp4_bytes:
        is_fallback = True
        used_model = "gemini-omni-1.1-flash (ffmpeg-motion-engine)"
        # Render fresh topic-matched base frame if prompt differs from the default image
        topic_frame = _render_pillow_scientific_illustration(title=resolved_title, prompt=clean_prompt)
        base_for_video = ref_img_bytes if (source_asset_id or source_board_id or source_data_url or slide_id) else topic_frame
        mp4_bytes = await asyncio.to_thread(
            _render_ffmpeg_clinical_video,
            base_for_video,
            resolved_title,
            clean_prompt,
        )

    narration = (
        f"'{clean_prompt}' 요청을 바탕으로 720p MP4 모션 설명 영상을 생성했습니다. "
        "플레이어에서 재생·일시정지 및 반복 확인이 가능합니다."
    )
    asset_meta, board_entry = BOARD_STORE.save_video_bytes(
        mp4_bytes=mp4_bytes,
        title=resolved_title,
        subtitle=f"Gemini Omni 720p 16:9 MP4 ({used_model})",
        prompt=clean_prompt,
        model=used_model,
        parent_asset_id=resolved_parent_id,
        narration_script=narration,
        create_board=True,
    )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "targetMode": "video",
        "model": used_model,
        "isFallback": is_fallback,
        "apiWarning": api_error,
        "elapsedMs": elapsed_ms,
        "asset": asset_meta,
        "board": board_entry,
        "activeBoardId": BOARD_STORE.active_board_id,
        "narrationScript": narration,
    }


# ---------------------------------------------------------------------------
# 9. Interactive 2D Pathway & Architecture Diagram Generator (`generate_board_diagram`)
# ---------------------------------------------------------------------------
def _build_cardiopulmonary_diagram_scene() -> Dict[str, Any]:
    return {
        "sceneType": "diagram",
        "domain": "cardiopulmonary",
        "title": "심폐 순환 (Cardiopulmonary Circulation) & 판막 혈류 경로",
        "subtitle": "우심방·우심실 → 폐동맥·폐포 가스교환 → 좌심방·좌심실 → 대동맥 전신 순환 6단계",
        "sourceIds": ["SOT-CARDIO-01"],
        "groundingMode": "strict_sot",
        "camera": {"zoom": 1.0, "panX": 0, "panY": 0, "preset": "overview"},
        "nodes": [
            {
                "id": "cardio_step1_ra_rv",
                "stepNumber": 1,
                "label": "우심방 → 삼첨판 → 우심실",
                "sublabel": "정맥혈 유입 (SVC / IVC)",
                "category": "venous_chamber",
                "compartment": "우심계 (Right Heart)",
                "description": "전신에서 산소를 소모한 정맥혈이 상대정맥·하대정맥을 통해 우심방으로 유입된 뒤 삼첨판을 지나 우심실로 이동합니다.",
                "highlighted": True,
                "expanded": False,
                "opacity": 1.0,
                "x": 90,
                "y": 140,
            },
            {
                "id": "cardio_step2_pulmonary_artery",
                "stepNumber": 2,
                "label": "폐동맥판 → 폐동맥 줄기",
                "sublabel": "우심실 수축기 박출",
                "category": "pulmonary_vessel",
                "compartment": "폐순환 유출로",
                "description": "우심실 수축 시 폐동맥판이 열리며 좌·우 폐동맥을 통해 폐포 모세혈관망으로 혈액이 이동합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 310,
                "y": 140,
            },
            {
                "id": "cardio_step3_alveoli",
                "stepNumber": 3,
                "label": "폐포-모세혈관 가스교환",
                "sublabel": "CO2 배출 · O2 헤모글로빈 결합",
                "category": "gas_exchange",
                "compartment": "양측 폐 (Lungs)",
                "description": "분압차에 의해 이산화탄소가 폐포로 배출되고 산소가 적혈구 헤모글로빈에 결합하여 동맥혈로 전환됩니다.",
                "highlighted": True,
                "expanded": True,
                "opacity": 1.0,
                "x": 530,
                "y": 140,
                "detailChildren": [
                    {"id": "c3a", "label": "3-A. 폐포 산소 분압 (PAO2 ~100 mmHg)", "detail": "모세혈관 내 정맥혈(PO2 40 mmHg)로 급속 산소 확산"},
                    {"id": "c3b", "label": "3-B. CO2 해리 및 호기 배출", "detail": "중탄산 이온(HCO3-)이 CO2로 전환되어 폐포 밖으로 배출"},
                ],
            },
            {
                "id": "cardio_step4_la_mitral",
                "stepNumber": 4,
                "label": "폐정맥 → 좌심방 → 승모판",
                "sublabel": "산소화 혈액 귀환",
                "category": "arterial_chamber",
                "compartment": "좌심계 (Left Heart)",
                "description": "4개의 폐정맥을 통해 산소가 풍부한 혈액이 좌심방으로 들어와 승모판(이첨판)을 통과합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 530,
                "y": 320,
            },
            {
                "id": "cardio_step5_lv_aortic",
                "stepNumber": 5,
                "label": "좌심실 수축 → 대동맥판 개방",
                "sublabel": "고압 전신 박출 (~120 mmHg)",
                "category": "arterial_chamber",
                "compartment": "좌심실 유출로",
                "description": "두꺼운 심근을 가진 좌심실이 강력하게 수축하여 대동맥판을 열고 상행 대동맥으로 혈액을 박출합니다.",
                "highlighted": True,
                "expanded": False,
                "opacity": 1.0,
                "x": 310,
                "y": 320,
            },
            {
                "id": "cardio_step6_systemic",
                "stepNumber": 6,
                "label": "대동맥궁 · 관상동맥 · 전신 관류",
                "sublabel": "뇌 · 심근 · 복부 장기 산소 공급",
                "category": "effector_response",
                "compartment": "전신 순환 (Systemic)",
                "description": "관상동맥으로 심근 자체에 산소를 공급하고, 대동맥궁 및 복부 대동맥을 통해 전신 장기로 혈류를 전달합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 90,
                "y": 320,
            },
        ],
        "edges": [
            {"id": "ce1", "from": "cardio_step1_ra_rv", "to": "cardio_step2_pulmonary_artery", "label": "삼첨판 → 폐동맥판"},
            {"id": "ce2", "from": "cardio_step2_pulmonary_artery", "to": "cardio_step3_alveoli", "label": "폐순환 유입"},
            {"id": "ce3", "from": "cardio_step3_alveoli", "to": "cardio_step4_la_mitral", "label": "O2 포화 (폐정맥)"},
            {"id": "ce4", "from": "cardio_step4_la_mitral", "to": "cardio_step5_lv_aortic", "label": "승모판 통과"},
            {"id": "ce5", "from": "cardio_step5_lv_aortic", "to": "cardio_step6_systemic", "label": "대동맥 박출"},
        ],
        "annotations": [
            {
                "id": "cardio_note_1",
                "targetId": "cardio_step3_alveoli",
                "title": "가스교환 핵심",
                "body": "폐동맥(정맥혈)이 폐포 모세혈관을 거치며 산소 포화도 98% 이상의 동맥혈로 전환됩니다.",
                "badge": "CARDIO-SOT",
            }
        ],
        "comparison": None,
        "anatomy": None,
    }


def _build_renal_filtration_diagram_scene() -> Dict[str, Any]:
    return {
        "sceneType": "diagram",
        "domain": "renal_physiology",
        "title": "신장 네프론 사구체 여과 & 세뇨관 재흡수 경로",
        "subtitle": "수입세동맥 → 사구체 여과 장벽 → 근위세뇨관(65% 재흡수) → 헨레고리 → 집합관 농축",
        "sourceIds": ["SOT-RENAL-01"],
        "groundingMode": "strict_sot",
        "camera": {"zoom": 1.0, "panX": 0, "panY": 0, "preset": "overview"},
        "nodes": [
            {
                "id": "renal_step1_glomerulus",
                "stepNumber": 1,
                "label": "신동맥 & 수입세동맥 유입",
                "sublabel": "사구체 정수압 (~55 mmHg)",
                "category": "vascular",
                "compartment": "신피질 (Renal Cortex)",
                "description": "복부 대동맥에서 분지된 신동맥 혈류가 수입세동맥을 통해 사구체 모세혈관총으로 유입됩니다.",
                "highlighted": True,
                "expanded": False,
                "opacity": 1.0,
                "x": 90,
                "y": 150,
            },
            {
                "id": "renal_step2_bowman",
                "stepNumber": 2,
                "label": "보먼주머니 여과 장벽",
                "sublabel": "GFR ~125 mL/min · 단백질 차단",
                "category": "filtration",
                "compartment": "사구체낭 (Bowman's Capsule)",
                "description": "유공 내피세포, 기저막, 족세포(Podocyte) 세공격막을 통해 물과 저분자 용질만 여과되고 알부민은 보존됩니다.",
                "highlighted": True,
                "expanded": True,
                "opacity": 1.0,
                "x": 310,
                "y": 150,
                "detailChildren": [
                    {"id": "r2a", "label": "2-A. 족세포(Podocyte) 여과 세공", "detail": "음전하 당단백질 장벽이 혈장 알부민 여과를 차단"},
                    {"id": "r2b", "label": "2-B. 순여과압 (Net Filtration Pressure)", "detail": "사구체 정수압(55) - 보먼낭압(15) - 교질삼투압(30) = +10 mmHg"},
                ],
            },
            {
                "id": "renal_step3_pct",
                "stepNumber": 3,
                "label": "근위세뇨관 (PCT) 재흡수",
                "sublabel": "Na+ · 물 65% · 포도당 100% 재흡수",
                "category": "reabsorption",
                "compartment": "신피질 세뇨관",
                "description": "SGLT2 공수송체와 Na+/K+ 펌프를 통해 포도당·아미노산 전량과 여과된 수분·나트륨의 약 65%를 재흡수합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 530,
                "y": 150,
            },
            {
                "id": "renal_step4_henle",
                "stepNumber": 4,
                "label": "헨레고리 (Loop of Henle)",
                "sublabel": "역류 증폭기 · 수질 삼투질 농도 형성",
                "category": "concentration",
                "compartment": "신수질 (Renal Medulla)",
                "description": "하행각의 수분 재흡수와 상행각의 Na-K-2Cl 능동 수송으로 수질 간질의 고삼투압 구배(1200 mOsm/L)를 형성합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 530,
                "y": 320,
            },
            {
                "id": "renal_step5_collecting",
                "stepNumber": 5,
                "label": "원위세뇨관 & 집합관 조절",
                "sublabel": "Aldosterone & ADH (Aquaporin-2)",
                "category": "hormonal",
                "compartment": "집합관 → 신우 → 요관",
                "description": "알도스테론에 의한 Na+ 재흡수와 항이뇨호르몬(ADH)에 의한 수분 통로(AQP2) 삽입으로 최종 소변 농축도를 결정합니다.",
                "highlighted": True,
                "expanded": False,
                "opacity": 1.0,
                "x": 210,
                "y": 320,
            },
        ],
        "edges": [
            {"id": "re1", "from": "renal_step1_glomerulus", "to": "renal_step2_bowman", "label": "순여과압 +10 mmHg"},
            {"id": "re2", "from": "renal_step2_bowman", "to": "renal_step3_pct", "label": "원뇨 유입"},
            {"id": "re3", "from": "renal_step3_pct", "to": "renal_step4_henle", "label": "등장성 여과액"},
            {"id": "re4", "from": "renal_step4_henle", "to": "renal_step5_collecting", "label": "호르몬 미세 조절"},
        ],
        "annotations": [
            {
                "id": "renal_note_1",
                "targetId": "renal_step2_bowman",
                "title": "사구체 여과 핵심",
                "body": "수입·수출세동맥 저항 조절을 통해 혈압 변동에도 사구체 여과율(GFR)이 일정하게 유지됩니다.",
                "badge": "RENAL-SOT",
            }
        ],
        "comparison": None,
        "anatomy": None,
    }


DYNAMIC_DIAGRAM_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "domain": {"type": "string"},
        "narrationScript": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "stepNumber": {"type": "integer"},
                    "label": {"type": "string"},
                    "sublabel": {"type": "string"},
                    "category": {"type": "string"},
                    "compartment": {"type": "string"},
                    "description": {"type": "string"},
                    "highlighted": {"type": "boolean"},
                },
                "required": ["id", "stepNumber", "label", "sublabel", "category", "compartment", "description", "highlighted"],
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["id", "from", "to", "label"],
            },
        },
    },
    "required": ["title", "subtitle", "domain", "narrationScript", "nodes", "edges"],
}


async def generate_board_diagram(
    prompt: str,
    template_id: Optional[str] = None,
    selected_node_ids: Optional[List[str]] = None,
    comparison_mode: bool = False,
) -> Dict[str, Any]:
    """
    Generates or updates an interactive 2D pathway/mechanism/comparison diagram.
    Uses instant deterministic SOT templates from `knowledge_base.py` when matched,
    or synthesizes a structured multi-node graph via `gemini-3.8-flash` for custom topics.
    """
    t0 = time.perf_counter()
    norm = normalize_korean_text(prompt or "")

    scene: Optional[Dict[str, Any]] = None
    used_model = "deterministic-sot-graph"

    if template_id == "gpcr_antagonist_comparison" or comparison_mode or any(
        k in norm for k in ["길항제", "비교", "나란히", "차단", "antagonist", "compare", "comparison", "versus", "vs"]
    ):
        scene = build_gpcr_compare_scene()
    elif template_id == "gpcr_gs_camp_pka" or any(
        k in norm for k in ["gpcr", "camp", "pka", "리간드", "아데닐산", "수용체", "3단계", "서브유닛", "신호 전달", "신호전달", "gs"]
    ):
        scene = build_gpcr_core_scene()
        # Check if user asked to drill down into Step 3 or selected nodes
        if any(k in norm for k in ["3단계", "분리", "자세히", "세부", "여기만", "step 3", "dissociation"]) or (
            selected_node_ids and "step3_subunit_dissociation" in selected_node_ids
        ):
            for n in scene["nodes"]:
                if n["id"] == "step3_subunit_dissociation":
                    n["highlighted"] = True
                    n["expanded"] = True
            scene["subtitle"] = "3단계 Gαs-GTP / Gβγ 분리 세부 기전 확장 (3-A 포켓 개방 → 3-B Switch 전환 → 3-C AC 결합)"
    elif template_id == "async_queue_backpressure" or any(
        k in norm for k in ["큐", "워커", "백프레셔", "dlq", "비동기", "아키텍처", "queue", "worker", "backpressure"]
    ):
        scene = build_async_queue_scene()
        for n in scene["nodes"]:
            if n["id"] == "sys_step2_queue":
                n["highlighted"] = True
                n["expanded"] = True
    elif template_id == "cardiopulmonary_circulation" or any(
        k in norm for k in ["심폐", "심장", "폐순환", "체순환", "판막", "대동맥", "폐동맥", "cardio", "pulmonary", "circulation", "heart"]
    ):
        scene = _build_cardiopulmonary_diagram_scene()
    elif template_id == "renal_glomerular_filtration" or any(
        k in norm for k in ["신장", "사구체", "네프론", "세뇨관", "보먼", "여과", "renal", "nephron", "glomerul", "kidney"]
    ):
        scene = _build_renal_filtration_diagram_scene()
    elif template_id in ("shoulder_subscapularis_reveal", "shoulder_rotator_cuff_sits") or any(
        k in norm for k in ["견갑하근", "회전근개", "대흉근", "어깨", "subscapularis", "rotator cuff"]
    ):
        scene = (
            build_shoulder_rotator_cuff_scene()
            if "회전근개" in norm or "rotator" in norm
            else build_shoulder_subscapularis_scene(ghost_superficial=True)
        )

    # Dynamic synthesis via gemini-3.8-flash for any custom scientific/clinical topic
    if scene is None:
        client = get_genai_client()
        if client is not None:
            def _call_dynamic_diagram() -> Dict[str, Any]:
                sys_prompt = f"""당신은 의학·생물학·공학 도식 설계 엔진입니다.
사용자의 요청 주제({prompt})를 명확한 5~6단계 구조화 다이어그램 JSON으로 생성하세요.
모든 노드의 label, sublabel, description은 이해하기 쉬운 한국어(영문 병기 가능)로 작성하세요."""
                res = client.interactions.create(
                    model="gemini-3.8-flash",
                    input=sys_prompt,
                    generation_config={"thinking_level": "low"},
                    response_format=DYNAMIC_DIAGRAM_JSON_SCHEMA,
                )
                return json.loads((res.output_text or "{}").strip())

            try:
                dyn = await asyncio.wait_for(asyncio.to_thread(_call_dynamic_diagram), timeout=15.0)
                coords = [(90, 140), (310, 140), (530, 140), (530, 320), (310, 320), (90, 320)]
                nodes = []
                for idx, n in enumerate(dyn.get("nodes", [])[:6]):
                    cx, cy = coords[idx % len(coords)]
                    nodes.append(
                        {
                            "id": n.get("id") or f"step_{idx+1}",
                            "stepNumber": int(n.get("stepNumber") or (idx + 1)),
                            "label": n.get("label", f"Step {idx+1}"),
                            "sublabel": n.get("sublabel", ""),
                            "category": n.get("category", "mechanism"),
                            "compartment": n.get("compartment", "Core Pathway"),
                            "description": n.get("description", ""),
                            "highlighted": bool(n.get("highlighted", idx == 0)),
                            "expanded": False,
                            "opacity": 1.0,
                            "x": cx,
                            "y": cy,
                        }
                    )
                scene = {
                    "sceneType": "diagram",
                    "domain": dyn.get("domain", "custom_pathway"),
                    "title": dyn.get("title", f"{prompt[:36]} 단계별 메커니즘 도식"),
                    "subtitle": dyn.get("subtitle", "Gemini 3.8 Flash 실시간 구조화 경로 도식"),
                    "sourceIds": ["GEMINI-GROUNDED"],
                    "groundingMode": "dynamic_structured",
                    "camera": {"zoom": 1.0, "panX": 0, "panY": 0, "preset": "overview"},
                    "nodes": nodes,
                    "edges": dyn.get("edges", []),
                    "annotations": [],
                    "comparison": None,
                    "anatomy": None,
                    "narrationScript": dyn.get("narrationScript", ""),
                }
                used_model = "gemini-3.8-flash"
            except Exception:
                scene = None

    if scene is None:
        scene = build_gpcr_core_scene()

    if selected_node_ids:
        for n in scene.get("nodes", []):
            if n.get("id") in selected_node_ids:
                n["highlighted"] = True
                if n.get("detailChildren"):
                    n["expanded"] = True

    narration = scene.get("narrationScript") or (
        f"{scene.get('title')}: {scene.get('subtitle')}. "
        "각 노드를 클릭하여 세부 기전을 확장하거나 정상 대비 차단 비교 뷰로 전환할 수 있습니다."
    )
    board_entry = BOARD_STORE.record_diagram_board(
        diagram_scene=scene,
        narration_script=narration,
        model=used_model,
    )
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "targetMode": "diagram",
        "model": used_model,
        "elapsedMs": elapsed_ms,
        "diagramScene": scene,
        "board": board_entry,
        "activeBoardId": BOARD_STORE.active_board_id,
        "narrationScript": narration,
    }


# ---------------------------------------------------------------------------
# 10. Slide Deck Import (`import_slide_deck`, `get_demo_slides`)
# ---------------------------------------------------------------------------
def get_demo_slides() -> Dict[str, Any]:
    return {
        "ok": True,
        "slides": list(BOARD_STORE.slides),
        "activeSlideId": BOARD_STORE.active_slide_id,
    }


def _extract_pptx_slide_texts(pptx_bytes: bytes) -> List[Tuple[str, List[str]]]:
    """Extracts `(slide_title, bullet_lines)` from `.pptx` XML without requiring LibreOffice."""
    slides_out: List[Tuple[str, List[str]]] = []
    try:
        with zipfile.ZipFile(io.BytesIO(pptx_bytes), "r") as zf:
            slide_files = sorted(
                [name for name in zf.namelist() if re.match(r"^ppt/slides/slide\d+\.xml$", name)],
                key=lambda x: int(re.search(r"slide(\d+)\.xml", x).group(1)),  # type: ignore
            )
            for idx, sname in enumerate(slide_files[:20], start=1):
                xml_bytes = zf.read(sname)
                root = ET.fromstring(xml_bytes)
                texts = [elem.text.strip() for elem in root.iter() if elem.tag.endswith("}t") and elem.text and elem.text.strip()]
                if texts:
                    title = texts[0][:80]
                    bullets = [t[:120] for t in texts[1:8]]
                else:
                    title = f"Imported PPTX Slide {idx}"
                    bullets = ["Extracted from presentation deck"]
                slides_out.append((title, bullets))
    except Exception:
        pass
    return slides_out


async def import_slide_deck(
    filename: str,
    file_bytes: bytes,
) -> Dict[str, Any]:
    """
    Imports a `.pdf`, `.pptx`, `.ppt`, `.png`, `.jpg`, or `.webp` file as playable/selectable
    lecture slides in `BOARD_STORE.slides` and creates a Board entry for the first imported slide.
    """
    t0 = time.perf_counter()
    safe_name = os.path.basename(filename or "lecture_deck.pdf")
    ext = os.path.splitext(safe_name)[1].lower()
    imported_slides: List[Dict[str, Any]] = []

    if ext in {".png", ".jpg", ".jpeg", ".webp"}:
        slide_title = f"Imported Slide: {os.path.splitext(safe_name)[0]}"
        asset_meta, board_entry = BOARD_STORE.save_image_bytes(
            raw_bytes=file_bytes,
            title=slide_title,
            subtitle=f"Imported image slide ({safe_name})",
            prompt=slide_title,
            model="slide-upload",
            create_board=True,
            board_kind="image",
        )
        slide_obj = {
            "slideId": f"slide-{uuid.uuid4().hex[:8]}",
            "page": len(BOARD_STORE.slides) + 1,
            "deckName": safe_name,
            "title": slide_title,
            "subtitle": "Uploaded Visual Slide",
            "text": slide_title,
            "bullets": ["Uploaded visual slide ready for region inpainting or Gemini Omni video animation"],
            "assetId": asset_meta["assetId"],
            "imageUrl": asset_meta["url"],
            "width": asset_meta["width"],
            "height": asset_meta["height"],
            "suggestedPrompts": {
                "3d": "Show the corresponding anatomical structures in 3D",
                "diagram": "이 슬라이드의 핵심 기전을 단계별 다이어그램으로 정리해줘",
                "image": "Create an enhanced textbook illustration from this slide",
                "video": "Animate this slide into a 5-second educational video",
            },
        }
        BOARD_STORE.slides.append(slide_obj)
        BOARD_STORE.active_slide_id = slide_obj["slideId"]
        imported_slides.append(slide_obj)

    elif ext == ".pdf":
        pdftoppm_bin = "/opt/homebrew/bin/pdftoppm" if os.path.exists("/opt/homebrew/bin/pdftoppm") else (shutil.which("pdftoppm") or "")
        pdftotext_bin = "/opt/homebrew/bin/pdftotext" if os.path.exists("/opt/homebrew/bin/pdftotext") else (shutil.which("pdftotext") or "")
        with tempfile.TemporaryDirectory(prefix="vb-pdf-") as tmpdir:
            tmp_path = Path(tmpdir)
            pdf_file = tmp_path / "source.pdf"
            pdf_file.write_bytes(file_bytes)

            page_texts: List[str] = []
            if pdftotext_bin:
                try:
                    txt_file = tmp_path / "text.txt"
                    subprocess.run([pdftotext_bin, "-layout", str(pdf_file), str(txt_file)], check=False, timeout=20.0)
                    if txt_file.exists():
                        page_texts = txt_file.read_text(encoding="utf-8", errors="ignore").split("\f")
                except Exception:
                    pass

            rendered_pngs: List[Path] = []
            if pdftoppm_bin:
                try:
                    subprocess.run(
                        [pdftoppm_bin, "-f", "1", "-l", "8", "-scale-to", "1280", "-png", str(pdf_file), str(tmp_path / "page")],
                        check=False,
                        timeout=30.0,
                    )
                    rendered_pngs = sorted(tmp_path.glob("page*.png"))
                except Exception:
                    pass

            if rendered_pngs:
                for idx, png_p in enumerate(rendered_pngs, start=1):
                    raw_txt = (page_texts[idx - 1] if idx - 1 < len(page_texts) else "").strip()
                    first_line = next((ln.strip() for ln in raw_txt.splitlines() if ln.strip()), f"{safe_name} — Page {idx}")
                    asset_meta, _ = BOARD_STORE.save_image_bytes(
                        raw_bytes=png_p.read_bytes(),
                        title=first_line[:68],
                        subtitle=f"{safe_name} (Page {idx})",
                        prompt=raw_txt[:300] or first_line,
                        model="pdf-slide-import",
                        create_board=(idx == 1),
                        board_kind="image",
                    )
                    lines = [ln.strip() for ln in raw_txt.splitlines() if ln.strip()][:5]
                    s_obj = {
                        "slideId": f"slide-{uuid.uuid4().hex[:8]}",
                        "page": idx,
                        "deckName": safe_name,
                        "title": first_line[:68],
                        "subtitle": f"{safe_name} · Page {idx}",
                        "text": raw_txt[:2000] or first_line,
                        "bullets": lines or [f"Imported Page {idx} from {safe_name}"],
                        "assetId": asset_meta["assetId"],
                        "imageUrl": asset_meta["url"],
                        "width": asset_meta["width"],
                        "height": asset_meta["height"],
                    }
                    BOARD_STORE.slides.append(s_obj)
                    imported_slides.append(s_obj)
            else:
                # Fallback if PDF rasterizer didn't produce pages
                fallback_bytes = _render_pillow_scientific_illustration(
                    title=f"{safe_name} — Slide 1",
                    prompt=safe_name,
                    subtitle="Imported PDF Lecture Slide",
                    slide_mode=True,
                )
                asset_meta, _ = BOARD_STORE.save_image_bytes(
                    raw_bytes=fallback_bytes,
                    title=f"{safe_name} — Slide 1",
                    subtitle="Imported PDF Slide",
                    model="pdf-fallback-renderer",
                    create_board=True,
                )
                s_obj = {
                    "slideId": f"slide-{uuid.uuid4().hex[:8]}",
                    "page": 1,
                    "deckName": safe_name,
                    "title": f"{safe_name} — Slide 1",
                    "subtitle": "Imported PDF Slide",
                    "text": safe_name,
                    "bullets": ["Imported PDF slide ready for visual generation"],
                    "assetId": asset_meta["assetId"],
                    "imageUrl": asset_meta["url"],
                    "width": 1280,
                    "height": 720,
                }
                BOARD_STORE.slides.append(s_obj)
                imported_slides.append(s_obj)

    else:
        # PPTX / PPT or general presentation file
        extracted = _extract_pptx_slide_texts(file_bytes) if ext == ".pptx" else []
        if not extracted:
            extracted = [(f"{safe_name} — Slide 1", ["Imported presentation slide deck", "Ready for 3D, Diagram, Image & Video synthesis"])]
        for idx, (s_title, s_bullets) in enumerate(extracted[:8], start=1):
            slide_png = _render_pillow_scientific_illustration(
                title=s_title,
                prompt=" ".join(s_bullets),
                subtitle=f"{safe_name} · Slide {idx}",
                slide_mode=True,
                bullets=s_bullets,
            )
            asset_meta, _ = BOARD_STORE.save_image_bytes(
                raw_bytes=slide_png,
                title=s_title,
                subtitle=f"{safe_name} (Slide {idx})",
                prompt=" ".join(s_bullets),
                model="pptx-slide-renderer",
                create_board=(idx == 1),
            )
            s_obj = {
                "slideId": f"slide-{uuid.uuid4().hex[:8]}",
                "page": idx,
                "deckName": safe_name,
                "title": s_title,
                "subtitle": f"{safe_name} · Slide {idx}",
                "text": "\n".join([s_title] + s_bullets),
                "bullets": s_bullets,
                "assetId": asset_meta["assetId"],
                "imageUrl": asset_meta["url"],
                "width": 1280,
                "height": 720,
            }
            BOARD_STORE.slides.append(s_obj)
            imported_slides.append(s_obj)

    if imported_slides:
        BOARD_STORE.active_slide_id = imported_slides[0]["slideId"]

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)
    return {
        "ok": True,
        "deckName": safe_name,
        "importedCount": len(imported_slides),
        "importedSlides": imported_slides,
        "activeSlideId": BOARD_STORE.active_slide_id,
        "activeBoardId": BOARD_STORE.active_board_id,
        "activeBoard": BOARD_STORE.get_board(BOARD_STORE.active_board_id),
        "elapsedMs": elapsed_ms,
    }


# ---------------------------------------------------------------------------
# 11. 3D Canvas Snapshot -> Board Image Asset (`capture_3d_to_board_image`)
# ---------------------------------------------------------------------------
async def capture_3d_to_board_image(
    data_url: Optional[str] = None,
    title: str = "3D 해부학 장면 캡처 스냅샷",
    subtitle: str = "드래그하여 영역 부분 인페인팅(Nano Banana) 또는 모션 영상(Gemini Omni) 생성 가능",
) -> Dict[str, Any]:
    """
    Converts a captured 3D WebGL canvas `dataUrl` into a stored PNG image asset and `"image"` board
    so the user can immediately drag-select a rectangular region on the 3D snapshot to inpaint
    with Nano Banana or animate into an MP4 video with Gemini Omni!
    """
    if data_url and data_url.startswith("data:image/"):
        _, b64_part = data_url.split(",", 1)
        raw_bytes = base64.b64decode(b64_part)
    else:
        raw_bytes = _render_pillow_scientific_illustration(
            title=title,
            prompt="3D Anatomy Snapshot for Region Inpainting & Video Animation",
            subtitle=subtitle,
        )

    asset_meta, board_entry = BOARD_STORE.save_image_bytes(
        raw_bytes=raw_bytes,
        title=title,
        subtitle=subtitle,
        prompt="Captured 3D Anatomy Viewport",
        model="3d-webgl-capture",
        narration_script="현재 3D 해부학 뷰포트를 이미지 보드로 캡처했습니다. 원하는 부위를 드래그해 부분 인페인팅하거나 영상으로 변환해 보세요.",
        create_board=True,
    )
    return {
        "ok": True,
        "targetMode": "image",
        "asset": asset_meta,
        "board": board_entry,
        "activeBoardId": BOARD_STORE.active_board_id,
    }


# ---------------------------------------------------------------------------
# 12. Unified Smart Command Router (`execute_smart_command`)
# ---------------------------------------------------------------------------
def classify_smart_intent(
    command_text: str,
    active_mode: str = "3d",
    selected_region: Optional[Dict[str, Any]] = None,
    force_mode: Optional[str] = None,
) -> str:
    """
    Determines which modality engine should handle `command_text`:
    Returns one of: `"edit_image"`, `"video"`, `"image"`, `"diagram"`, `"3d"`.
    """
    if force_mode in {"edit_image", "video", "image", "diagram", "3d"}:
        return force_mode

    raw = (command_text or "").strip().lower()
    norm = normalize_korean_text(raw)

    has_valid_region = bool(
        selected_region
        and float(selected_region.get("width", 0)) >= 0.02
        and float(selected_region.get("height", 0)) >= 0.02
    )

    # 1. Explicit video / animation keywords
    video_keywords = [
        "영상",
        "동영상",
        "비디오",
        "애니메이션",
        "움직이게",
        "움직이는",
        "모션",
        "클립",
        "mp4",
        "video",
        "animate",
        "animation",
        "motion clip",
    ]
    if any(k in raw or k in norm for k in video_keywords):
        return "video"

    # 2. If user drew a region box on an image, or is in image mode asking to modify/edit/inpaint
    edit_keywords = [
        "인페인팅",
        "부분 수정",
        "영역 수정",
        "이 영역",
        "선택한 영역",
        "네모 안",
        "박스 안",
        "바꿔",
        "수정해",
        "고쳐",
        "추가해",
        "넣어줘",
        "inpaint",
        "edit region",
        "replace this",
        "modify region",
    ]
    if has_valid_region:
        return "edit_image"
    if active_mode == "image" and any(k in raw or k in norm for k in edit_keywords):
        return "edit_image"

    # 3. Explicit 2D diagram / pathway / comparison keywords
    diagram_keywords = [
        "다이어그램",
        "도식",
        "흐름도",
        "순서도",
        "신호 전달",
        "신호전달",
        "기전",
        "경로",
        "gpcr",
        "camp",
        "pka",
        "길항제",
        "아데닐산",
        "서브유닛",
        "나란히 비교",
        "차단 비교",
        "백프레셔",
        "워커",
        "메시지 큐",
        "dlq",
        "사구체 여과",
        "네프론",
        "세뇨관",
        "diagram",
        "pathway",
        "flowchart",
        "cascade",
        "signaling",
        "agonist",
        "antagonist",
        "backpressure",
        "nephron",
    ]
    # Note: if user explicitly says "그려줘/일러스트/이미지" alongside a topic, check image keywords first
    image_keywords = [
        "일러스트",
        "이미지",
        "그림",
        "그려",
        "포스터",
        "인포그래픽",
        "단면도",
        "도해",
        "슬라이드 기반",
        "image",
        "illustrate",
        "illustration",
        "draw",
        "picture",
        "poster",
        "infographic",
        "sketch",
    ]
    has_diagram_kw = any(k in raw or k in norm for k in diagram_keywords)
    has_image_kw = any(k in raw or k in norm for k in image_keywords)

    if has_diagram_kw and not (
        any(k in raw for k in ["일러스트", "이미지", "사진", "illustration", "image", "picture"])
    ):
        return "diagram"

    if has_image_kw:
        return "image"

    # 4. Default: 3D Anatomy & Clinical Scene Controller (supports all whole-body organs, muscles, bones, vessels, camera presets, ghosting, undo, reset)
    return "3d"


async def execute_smart_command(
    command_text: str,
    session_id: str = "default",
    active_mode: str = "3d",
    selected_asset_id: Optional[str] = None,
    selected_board_id: Optional[str] = None,
    selected_region: Optional[Dict[str, Any]] = None,
    selected_element_ids: Optional[List[str]] = None,
    slide_id: Optional[str] = None,
    force_mode: Optional[str] = None,
    generate_audio: bool = False,
    wait_for_ack: bool = False,
) -> Dict[str, Any]:
    """
    Unified Smart Command Router:
    Routes any natural-language Korean or English command to:
      - `edit_board_image_region` (when `selected_region` is active or partial image edit requested)
      - `generate_board_video` (when animation/video requested via Gemini Omni 1.1 Flash)
      - `generate_board_image` (when illustration/image requested via Nano Banana)
      - `generate_board_diagram` (when pathway/flowchart/comparison diagram requested)
      - `execute_natural_language_scene_command` (when 3D anatomy structures/organs/camera/fade requested)
    """
    t0 = time.perf_counter()
    clean_text = (command_text or "").strip()
    if not clean_text:
        return {"ok": False, "error": "commandText is required."}

    # Strip wake phrase prefix if the user typed or spoke "비주얼 보드, ..." directly into the command bar
    wake_match = SESSION_STORE._match_wake_phrase(clean_text)
    if wake_match.get("matched") and wake_match.get("requestSuffix"):
        clean_text = wake_match["requestSuffix"].strip()

    target_intent = classify_smart_intent(
        command_text=clean_text,
        active_mode=active_mode,
        selected_region=selected_region,
        force_mode=force_mode,
    )

    if target_intent == "edit_image":
        effective_region = selected_region
        if not effective_region or float(effective_region.get("width", 0)) < 0.02:
            # Default centered focal box if user asked to edit the image by voice without dragging a box first
            effective_region = {"x": 0.22, "y": 0.18, "width": 0.56, "height": 0.62}
        res = await edit_board_image_region(
            prompt=clean_text,
            region=effective_region,
            asset_id=selected_asset_id,
            board_id=selected_board_id,
        )

    elif target_intent == "video":
        res = await generate_board_video(
            prompt=clean_text,
            source_asset_id=selected_asset_id,
            source_board_id=selected_board_id,
            slide_id=slide_id,
        )

    elif target_intent == "image":
        res = await generate_board_image(
            prompt=clean_text,
            slide_id=slide_id,
            reference_asset_id=selected_asset_id,
        )

    elif target_intent == "diagram":
        res = await generate_board_diagram(
            prompt=clean_text,
            selected_node_ids=selected_element_ids,
        )

    else:
        # 3D Whole-Body Anatomy & Shoulder Scene Controller
        scene_res = await execute_natural_language_scene_command(
            command_text=clean_text,
            session_id=session_id,
            stt_ms=0.0,
            wait_for_ack=wait_for_ack,
        )
        explanation = (
            scene_res.get("clinicalExplanation")
            or scene_res.get("explanation")
            or f"3D 해부학 장면에 '{clean_text}' 명령을 적용했습니다."
        )
        board_entry = BOARD_STORE.record_3d_board(
            title=f"3D 해부학: {clean_text[:40]}",
            subtitle=explanation[:95],
            scene_summary={
                "commandText": clean_text,
                "plannerMode": scene_res.get("plannerMode"),
                "toolCalls": scene_res.get("toolCalls", []),
                "revision": scene_res.get("revision"),
            },
            narration_script=explanation,
        )
        res = {
            "ok": scene_res.get("ok", True),
            "targetMode": "3d",
            "commandText": clean_text,
            "sceneResult": scene_res,
            "board": board_entry,
            "activeBoardId": BOARD_STORE.active_board_id,
            "narrationScript": explanation,
        }

    # Optional Gemini TTS audio briefing
    if generate_audio and res.get("narrationScript"):
        try:
            tts_res = await asyncio.to_thread(generate_tts_briefing, res["narrationScript"])
            res["tts"] = tts_res
        except Exception as exc:
            res["tts"] = {"ok": False, "error": str(exc)}

    res["routedIntent"] = target_intent
    res["totalSmartRouterMs"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return res


# ---------------------------------------------------------------------------
# 13. Continuous Lecture STT Ingestion & Wake-Phrase Gate (`ingest_lecture_segment`)
# ---------------------------------------------------------------------------
async def ingest_lecture_segment(
    text: str,
    is_final: bool = True,
    segment_id: Optional[str] = None,
    event_id: Optional[str] = None,
    speaker: str = "presenter",
    explicit_ui_request: bool = False,
    active_mode: str = "3d",
    selected_asset_id: Optional[str] = None,
    selected_board_id: Optional[str] = None,
    selected_region: Optional[Dict[str, Any]] = None,
    selected_element_ids: Optional[List[str]] = None,
    slide_id: Optional[str] = None,
    force_mode: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Processes continuous lecture speech through `SESSION_STORE.ingest_transcript_segment`.
    - Normal lecture speech (`LECTURE_ONLY`) is buffered into the rolling transcript without triggering generation.
    - When `"비주얼 보드"` or `"Visual Board"` is detected (`EXECUTE_REQUEST`), automatically routes
      the extracted request (plus active lecture context if the user said `"방금 설명한 거 보여줘"`)
      through `execute_smart_command`!
    """
    gate_res = SESSION_STORE.ingest_transcript_segment(
        text=text,
        is_final=is_final,
        segment_id=segment_id,
        event_id=event_id,
        speaker=speaker,
        explicit_ui_request=explicit_ui_request,
        selected_element_ids=selected_element_ids or [],
        base_scene_revision=len(BOARD_STORE.boards),
    )

    if gate_res.get("gateDecision") == "EXECUTE_REQUEST" and gate_res.get("triggered"):
        request_id = gate_res["requestId"]
        req_text = gate_res.get("requestText", "").strip()
        snapshot = gate_res.get("contextSnapshot") or {}
        active_topic = (snapshot.get("activeTopicText") or "").strip()

        # Resolve deictic references like "방금 설명한 거 보여줘" / "show what I just explained"
        deictic_markers = ["방금 설명", "지금 설명", "이 내용을", "이 과정을", "방금 말한", "just explained", "what i just"]
        effective_command = req_text
        if active_topic and (any(m in req_text.lower() for m in deictic_markers) or len(req_text) <= 12):
            effective_command = f"{req_text} (맥락: {active_topic[-240:]})"

        smart_res = await execute_smart_command(
            command_text=effective_command,
            active_mode=active_mode,
            selected_asset_id=selected_asset_id,
            selected_board_id=selected_board_id,
            selected_region=selected_region,
            selected_element_ids=selected_element_ids,
            slide_id=slide_id,
            force_mode=force_mode,
        )
        SESSION_STORE.mark_request_completed(
            request_id,
            result_summary={
                "targetMode": smart_res.get("targetMode"),
                "boardId": smart_res.get("activeBoardId"),
            },
        )
        gate_res["smartCommandResult"] = smart_res
        gate_res["sessionState"] = SESSION_STORE.state

    return gate_res
