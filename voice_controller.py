"""
Push-to-Talk Voice & Natural-Language Clinical Scene Controller for CliniView Live.

Pipeline:
1. Audio (Push-to-Talk) -> gemini-3.5-transcribe (with gemini-3.8-flash & clientTranscript fallbacks)
2. Natural-language clinical command -> Deterministic Whole-Body Bilingual Resolver + Gemini 3.8 Flash fallback
   (grounded in all 385 structures across 28 anatomical groups in structures-manifest.json)
3. Authoritative Scene Service execution -> 3D Auto-Framing Camera + Smart Layer Fading -> Browser Viewer ACK
4. Bilingual English + Korean explanationCard & latency breakdown (sttMs, llmMs, toolAckMs, viewerAckMs, totalMs)
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from google import genai

from presets import PRESETS
from scene_service import (
    CAMERA_PRESETS as SCENE_CAMERA_PRESETS,
    PROCEDURE_TEMPLATES,
    SCENE_SERVICE,
)
from synthesizer import get_genai_client

CAMERA_PRESETS: Dict[str, Dict[str, Any]] = {
    **SCENE_CAMERA_PRESETS,
    "right_anterolateral": {
        "name": "right_anterolateral",
        "labelKo": "우측 전외측 뷰",
        "position": [-0.36, 1.36, 0.34],
        "target": [-0.11, 1.34, -0.04],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "right_anterior": {
        "name": "right_anterior",
        "labelKo": "우측 전면 뷰",
        "position": [-0.20, 1.37, 0.40],
        "target": [-0.12, 1.34, -0.03],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "right_posterior": {
        "name": "right_posterior",
        "labelKo": "우측 후면 뷰",
        "position": [-0.28, 1.40, -0.38],
        "target": [-0.11, 1.34, -0.05],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "left_anterolateral": {
        "name": "left_anterolateral",
        "labelKo": "좌측 전외측 뷰",
        "position": [0.36, 1.36, 0.34],
        "target": [0.11, 1.34, -0.04],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "bilateral_front": {
        "name": "bilateral_front",
        "labelKo": "양측 정면 뷰",
        "position": [0.0, 1.37, 0.52],
        "target": [0.0, 1.34, -0.04],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
}

VOICE_PLAN_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "actionType": {
            "type": "string",
            "enum": ["apply_patch", "load_template", "set_progress", "undo", "reset"],
            "description": "Type of 3D scene operation to execute.",
        },
        "preserveCamera": {
            "type": "boolean",
            "description": "False when structures are shown/highlighted/isolated so the 3D camera auto-frames the target structures; True only when the user explicitly requests keeping the current camera angle.",
        },
        "cameraPreset": {
            "type": "string",
            "enum": [
                "auto_frame",
                "keep_current",
                "whole_body_front",
                "whole_body_back",
                "head_neck",
                "thorax_organs",
                "abdomen_organs",
                "spine_pelvis",
                "lower_limb",
                "lower_limb_back",
                "anterior",
                "posterior",
                "lateral",
                "superior",
                "axillary",
                "bicipital_groove",
                "right_anterolateral",
                "right_anterior",
                "right_posterior",
                "left_anterolateral",
                "bilateral_front",
            ],
        },
        "isolateMode": {
            "type": "boolean",
            "description": "True if the user wants to isolate only the target structures and fade surrounding anatomy.",
        },
        "highlightTerms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anatomical structure IDs or canonical terms to show and highlight (opacity=1.0, highlighted=True, outline=True).",
        },
        "semiTransparentItems": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "term": {
                        "type": "string",
                        "description": "Structure ID, group name, or canonical anatomical term to fade/make semi-transparent.",
                    },
                    "opacity": {
                        "type": "number",
                        "description": "Target opacity between 0.05 and 0.90 (typically 0.15 to 0.25 for faded layers).",
                    },
                },
                "required": ["term", "opacity"],
            },
        },
        "hiddenTerms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Structure IDs or anatomical terms to hide completely (visible=False, opacity=0.0).",
        },
        "opaqueTerms": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Structure IDs or anatomical terms to restore to full opacity (visible=True, opacity=1.0, highlighted=False).",
        },
        "templateId": {
            "type": "string",
            "description": "If actionType=='load_template', one of proc_subscap_axillary_r, proc_subscap_lesser_tubercle_r, proc_posterior_sits_si11_r, proc_subscap_axillary_l.",
        },
        "stepIndex": {
            "type": "integer",
            "description": "0-based step index if loading or advancing a procedure template.",
        },
        "progress": {
            "type": "number",
            "description": "Procedure progress in [0.0, 1.0] if actionType=='set_progress'.",
        },
        "titleEn": {
            "type": "string",
            "description": "Concise English title for the 3D anatomical visualization.",
        },
        "bodyEn": {
            "type": "string",
            "description": "Clear 2-3 sentence English anatomical and clinical explanation of the visualized structures.",
        },
        "spokenFeedbackEn": {
            "type": "string",
            "description": "Concise 1-2 sentence English confirmation of the 3D scene update.",
        },
        "titleKo": {
            "type": "string",
            "description": "Concise Korean title for the 3D anatomical visualization.",
        },
        "spokenFeedbackKo": {
            "type": "string",
            "description": "Concise 1-2 sentence Korean confirmation of the 3D scene update.",
        },
        "clinicalExplanationKo": {
            "type": "string",
            "description": "Clear 2-3 sentence Korean anatomical and clinical explanation of the visualized structures.",
        },
    },
    "required": [
        "actionType",
        "preserveCamera",
        "cameraPreset",
        "highlightTerms",
        "semiTransparentItems",
        "hiddenTerms",
        "opaqueTerms",
        "spokenFeedbackKo",
        "clinicalExplanationKo",
    ],
}

CLINICAL_STT_VOCABULARY: List[str] = [
    # Head, Neck & Brain
    "뇌", "대뇌", "소뇌", "뇌간", "뇌실", "시상", "뇌량", "해마", "두개골", "하악골", "설골",
    "경추", "경동맥", "경정맥", "흉쇄유돌근", "사각근", "갑상선", "후두", "기관", "식도",
    "brain", "cerebrum", "cerebellum", "brainstem", "thalamus", "hippocampus", "skull", "cranium", "mandible",
    # Thorax & Cardiopulmonary
    "심장", "좌심실", "우심실", "좌심방", "우심방", "대동맥", "폐동맥", "대정맥", "폐", "허파",
    "기관지", "횡격막", "갈비뼈", "늑골", "흉곽", "흉골", "대흉근", "소흉근", "늑간근", "전거근",
    "heart", "lungs", "aorta", "pulmonary artery", "vena cava", "diaphragm", "ribs", "ribcage", "sternum",
    # Abdomen & Visceral Organs
    "간", "담낭", "쓸개", "위", "위장", "비장", "췌장", "신장", "콩팥", "소장", "십이지장",
    "대장", "결장", "맹장", "충수", "직장", "장", "내장", "방광", "간문맥", "복부대동맥",
    "liver", "gallbladder", "stomach", "spleen", "pancreas", "kidneys", "small intestine", "colon", "bladder",
    # Spine, Pelvis & Core
    "척추", "흉추", "요추", "천골", "미골", "추간판", "디스크", "골반", "장골", "좌골", "치골",
    "복직근", "외복사근", "내복사근", "복횡근", "장요근", "대요근", "장골근", "요방형근", "척추기립근", "광배근",
    "spine", "vertebrae", "pelvis", "sacrum", "intervertebral discs", "rectus abdominis", "psoas", "erector spinae",
    # Upper Limb & Shoulder
    "회전근개", "견갑하근", "극상근", "극하근", "소원근", "대원근", "승모근", "삼각근", "상완이두근",
    "상완삼두근", "상완근", "오훼완근", "완요골근", "견갑골", "상완골", "쇄골", "요골", "척골",
    "완신경총", "액와신경", "정중신경", "척골신경", "요골신경", "액와동맥", "상완동맥",
    "rotator cuff", "subscapularis", "supraspinatus", "infraspinatus", "teres minor", "deltoid", "biceps", "triceps",
    # Lower Limb
    "대둔근", "중둔근", "소둔근", "둔근", "이상근", "대퇴사두근", "사두근", "대퇴직근", "외측광근", "내측광근",
    "중간광근", "봉공근", "햄스트링", "대퇴이두근", "반건양근", "반막양근", "내전근", "비복근", "가자미근",
    "전경골근", "대퇴골", "슬개골", "경골", "비골", "좌골신경", "대퇴신경", "경골신경", "대퇴동맥", "대복재정맥",
    "gluteus maximus", "gluteus medius", "piriformis", "quadriceps", "hamstrings", "gastrocnemius", "femur", "tibia", "sciatic nerve",
    # Controls
    "반투명", "투명하게", "투명도", "불투명", "강조", "하이라이트", "단독", "초기화", "되돌리기", "원래대로",
    "show", "highlight", "isolate", "fade", "transparent", "hide", "restore", "reset", "undo",
]


def normalize_audio_mime_type(mime_type: Optional[str]) -> str:
    """
    Normalizes browser MediaRecorder MIME types (such as 'audio/webm;codecs=opus',
    'audio/mp4;codecs=mp4a.40.2', or 'application/octet-stream') into clean MIME strings.
    """
    if not mime_type:
        return "audio/webm"
    base = mime_type.split(";")[0].strip().lower()
    if base in ("", "application/octet-stream", "binary/octet-stream", "video/webm"):
        return "audio/webm"
    if base in ("video/mp4", "audio/x-m4a", "audio/mp4a-latm"):
        return "audio/mp4"
    if base in ("audio/x-wav", "audio/wave"):
        return "audio/wav"
    if base == "audio/mpeg3":
        return "audio/mp3"
    if not base.startswith("audio/"):
        return "audio/webm"
    return base


def _clean_transcript_text(raw: str) -> str:
    """Strips markdown quotes, prefixes, or trailing punctuation noise from STT output."""
    t = (raw or "").strip()
    if not t:
        return ""
    t = re.sub(r"^(전사\s*결과|전사|transcript|output)\s*[:：]\s*", "", t, flags=re.IGNORECASE).strip()
    while len(t) >= 2 and t[0] == t[-1] and t[0] in ("'", '"', "`", "“", "”", "‘", "’"):
        t = t[1:-1].strip()
    return t


async def transcribe_voice_command(audio_bytes: bytes, mime_type: str = "audio/webm") -> Dict[str, Any]:
    """
    Transcribes push-to-talk audio using gemini-3.5-transcribe with automatic fallback
    to gemini-3.8-flash multimodal audio transcription.
    """
    t0 = time.perf_counter()
    norm_mime = normalize_audio_mime_type(mime_type)

    if not audio_bytes or len(audio_bytes) < 32:
        return {
            "ok": False,
            "transcript": "",
            "text": "",
            "model": "gemini-3.5-transcribe",
            "mimeType": norm_mime,
            "sttMs": 0.0,
            "elapsed_sec": 0.0,
            "error": "Audio payload is empty or too short.",
        }

    client = get_genai_client()
    b64_audio = base64.b64encode(audio_bytes).decode("ascii")
    transcribe_mime = "audio/m4a" if norm_mime == "audio/mp4" else norm_mime

    stt_prompt = (
        "다음 한국어 또는 영어 해부학·의료 음성 명령을 정확히 전사하세요. "
        "따옴표나 부연 설명 없이 오직 전사된 텍스트만 그대로 출력하세요. "
        "(주요 용어: 뇌, 두개골, 심장, 폐, 간, 위, 비장, 췌장, 신장, 대장, 소장, 척추, 골반, "
        "견갑하근, 극상근, 극하근, 삼각근, 대둔근, 대퇴사두근, 대퇴골, 좌골신경, "
        "heart, lungs, liver, stomach, brain, skull, quadriceps, femur, sciatic nerve, gluteus maximus, "
        "show, highlight, isolate, fade, hide, reset, undo)"
    )

    def _call_primary() -> Tuple[str, str]:
        try:
            interaction = client.interactions.create(
                model="gemini-3.5-transcribe",
                input=[
                    {"type": "text", "text": stt_prompt},
                    {"type": "audio", "data": b64_audio, "mime_type": transcribe_mime},
                ],
                store=False,
            )
            txt = _clean_transcript_text(interaction.output_text or "")
            if txt:
                return txt, "gemini-3.5-transcribe"
        except Exception:
            pass

        interaction_fb = client.interactions.create(
            model="gemini-3.8-flash",
            input=[
                {"type": "text", "text": stt_prompt},
                {"type": "audio", "data": b64_audio, "mime_type": norm_mime},
            ],
            store=False,
            generation_config={
                "thinking_level": "minimal",
                "thinking_summaries": "none",
            },
        )
        return _clean_transcript_text(interaction_fb.output_text or ""), "gemini-3.8-flash"

    transcript, used_model = await asyncio.to_thread(_call_primary)
    stt_ms = round((time.perf_counter() - t0) * 1000, 1)
    return {
        "ok": bool(transcript),
        "transcript": transcript,
        "text": transcript,
        "model": used_model,
        "mimeType": norm_mime,
        "sttMs": stt_ms,
        "elapsed_sec": round(stt_ms / 1000.0, 2),
    }


# ---------------------------------------------------------------------------
# Whole-Body Bilingual Anatomical Keyword Catalog (385 Structures / 28 Groups)
# Ordered from longest/most specific phrases to shorter terms to avoid partial collisions
# Tuple format: (trigger_phrase_lower, canonical_term, bilingual_display_label)
# ---------------------------------------------------------------------------
ANATOMY_KEYWORDS_ORDERED: List[Tuple[str, str, str]] = [
    # --- 1. Head, Neck & Brain ---
    ("corpus callosum", "corpus callosum", "Corpus Callosum (뇌량)"),
    ("internal capsule", "internal capsule", "Internal Capsule (내포)"),
    ("caudate nucleus", "caudate nucleus", "Caudate Nucleus (미상핵)"),
    ("lentiform nucleus", "lentiform nucleus", "Lentiform Nucleus (렌즈핵)"),
    ("lateral ventricle", "ventricles", "Brain Ventricles (뇌실)"),
    ("brain ventricles", "ventricles", "Brain Ventricles (뇌실)"),
    ("ventricles", "ventricles", "Brain Ventricles (뇌실)"),
    ("cerebral hemisphere", "cerebrum", "Cerebrum (대뇌)"),
    ("cerebrum", "cerebrum", "Cerebrum (대뇌)"),
    ("cerebellum", "cerebellum", "Cerebellum (소뇌)"),
    ("brainstem", "brainstem", "Brainstem (뇌간)"),
    ("brain stem", "brainstem", "Brainstem (뇌간)"),
    ("pons", "brainstem", "Pons & Brainstem (교뇌·뇌간)"),
    ("medulla oblongata", "brainstem", "Medulla Oblongata (연수)"),
    ("thalamus", "thalamus", "Thalamus (시상)"),
    ("hippocampus", "hippocampus", "Hippocampus (해마)"),
    ("fornix", "fornix", "Fornix (뇌궁)"),
    ("optic nerve", "optic nerve", "Optic Nerve (시신경)"),
    ("eyeball", "eye", "Eyeball & Optic Apparatus (안구)"),
    ("brain", "brain", "Brain (뇌)"),
    ("뇌실", "ventricles", "Brain Ventricles (뇌실)"),
    ("대뇌", "cerebrum", "Cerebrum (대뇌)"),
    ("소뇌", "cerebellum", "Cerebellum (소뇌)"),
    ("뇌간", "brainstem", "Brainstem (뇌간)"),
    ("교뇌", "brainstem", "Pons & Brainstem (교뇌·뇌간)"),
    ("연수", "brainstem", "Medulla Oblongata (연수)"),
    ("시상", "thalamus", "Thalamus (시상)"),
    ("뇌량", "corpus callosum", "Corpus Callosum (뇌량)"),
    ("해마", "hippocampus", "Hippocampus (해마)"),
    ("미상핵", "caudate nucleus", "Caudate Nucleus (미상핵)"),
    ("렌즈핵", "lentiform nucleus", "Lentiform Nucleus (렌즈핵)"),
    ("내포", "internal capsule", "Internal Capsule (내포)"),
    ("뇌궁", "fornix", "Fornix (뇌궁)"),
    ("시신경", "optic nerve", "Optic Nerve (시신경)"),
    ("안구", "eye", "Eyeball (안구)"),
    ("뇌", "brain", "Brain (뇌)"),
    # Skull & Craniofacial
    ("frontal bone", "frontal_bone", "Frontal Bone (전두골)"),
    ("parietal bone", "parietal bone", "Parietal Bone (두정골)"),
    ("temporal bone", "temporal bone", "Temporal Bone (측두골)"),
    ("occipital bone", "occipital_bone", "Occipital Bone (후두골)"),
    ("sphenoid bone", "sphenoid_bone", "Sphenoid Bone (접형골)"),
    ("ethmoid bone", "ethmoid_bone", "Ethmoid Bone (사골)"),
    ("zygomatic bone", "zygomatic bone", "Zygomatic Bone (관골)"),
    ("maxilla", "maxilla", "Maxilla (상악골)"),
    ("mandible", "mandible", "Mandible (하악골)"),
    ("jaw bone", "mandible", "Mandible (하악골)"),
    ("jaw", "mandible", "Mandible (하악골)"),
    ("hyoid bone", "hyoid_bone", "Hyoid Bone (설골)"),
    ("hyoid", "hyoid_bone", "Hyoid Bone (설골)"),
    ("cranium", "skull", "Cranium & Skull (두개골)"),
    ("skull", "skull", "Skull (두개골)"),
    ("두개골", "skull", "Skull (두개골)"),
    ("머리뼈", "skull", "Skull (두개골)"),
    ("전두골", "frontal_bone", "Frontal Bone (전두골)"),
    ("두정골", "parietal bone", "Parietal Bone (두정골)"),
    ("측두골", "temporal bone", "Temporal Bone (측두골)"),
    ("후두골", "occipital_bone", "Occipital Bone (후두골)"),
    ("하악골", "mandible", "Mandible (하악골)"),
    ("아래턱뼈", "mandible", "Mandible (하악골)"),
    ("턱뼈", "mandible", "Mandible (하악골)"),
    ("상악골", "maxilla", "Maxilla (상악골)"),
    ("설골", "hyoid_bone", "Hyoid Bone (설골)"),
    # Neck muscles, vessels & viscera
    ("sternocleidomastoid", "sternocleidomastoid", "Sternocleidomastoid (흉쇄유돌근)"),
    ("scm muscle", "sternocleidomastoid", "Sternocleidomastoid (흉쇄유돌근)"),
    ("scm", "sternocleidomastoid", "Sternocleidomastoid (흉쇄유돌근)"),
    ("scalene muscles", "scalenes", "Scalene Muscles (사각근)"),
    ("scalenes", "scalenes", "Scalene Muscles (사각근)"),
    ("scalene", "scalenes", "Scalene Muscles (사각근)"),
    ("masseter", "masseter", "Masseter (교근)"),
    ("temporalis", "temporalis", "Temporalis (측두근)"),
    ("carotid artery", "carotid artery", "Carotid Arteries (경동맥)"),
    ("common carotid", "carotid artery", "Common Carotid Artery (총경동맥)"),
    ("internal carotid", "carotid artery", "Internal Carotid Artery (내경동맥)"),
    ("carotid", "carotid artery", "Carotid Arteries (경동맥)"),
    ("jugular vein", "jugular vein", "Jugular Veins (경정맥)"),
    ("internal jugular", "jugular vein", "Internal Jugular Vein (내경정맥)"),
    ("jugular", "jugular vein", "Jugular Veins (경정맥)"),
    ("thyroid cartilage", "thyroid", "Thyroid & Laryngeal Cartilage (갑상연골·후두)"),
    ("thyroid", "thyroid", "Thyroid & Laryngeal Region (갑상선·후두)"),
    ("larynx", "larynx", "Larynx (후두)"),
    ("trachea", "trachea", "Trachea (기관)"),
    ("windpipe", "trachea", "Trachea (기관)"),
    ("esophagus", "esophagus", "Esophagus (식도)"),
    ("oesophagus", "esophagus", "Esophagus (식도)"),
    ("pharynx", "pharynx", "Pharynx (인두)"),
    ("흉쇄유돌근", "sternocleidomastoid", "Sternocleidomastoid (흉쇄유돌근)"),
    ("목빗근", "sternocleidomastoid", "Sternocleidomastoid (흉쇄유돌근)"),
    ("사각근", "scalenes", "Scalene Muscles (사각근)"),
    ("목갈비근", "scalenes", "Scalene Muscles (사각근)"),
    ("교근", "masseter", "Masseter (교근)"),
    ("측두근", "temporalis", "Temporalis (측두근)"),
    ("총경동맥", "carotid artery", "Common Carotid Artery (총경동맥)"),
    ("내경동맥", "carotid artery", "Internal Carotid Artery (내경동맥)"),
    ("경동맥", "carotid artery", "Carotid Arteries (경동맥)"),
    ("내경정맥", "jugular vein", "Internal Jugular Vein (내경정맥)"),
    ("경정맥", "jugular vein", "Jugular Veins (경정맥)"),
    ("갑상연골", "thyroid", "Thyroid Cartilage (갑상연골)"),
    ("갑상선", "thyroid", "Thyroid & Laryngeal Region (갑상선·후두)"),
    ("후두", "larynx", "Larynx (후두)"),
    ("기관지", "bronchi", "Tracheobronchial Tree (기관·기관지)"),
    ("기관", "trachea", "Trachea (기관)"),
    ("식도", "esophagus", "Esophagus (식도)"),
    ("인두", "pharynx", "Pharynx (인두)"),

    # --- 2. Thorax & Cardiopulmonary ---
    ("left ventricle", "heart_left_ventricle", "Left Ventricle (좌심실)"),
    ("right ventricle", "heart_right_ventricle", "Right Ventricle (우심실)"),
    ("left atrium", "heart_left_atrium", "Left Atrium (좌심방)"),
    ("right atrium", "heart_right_atrium", "Right Atrium (우심방)"),
    ("heart", "heart", "Heart (심장)"),
    ("cardiac", "heart", "Heart (심장)"),
    ("right lung", "right lung", "Right Lung (우폐)"),
    ("left lung", "left lung", "Left Lung (좌폐)"),
    ("lungs", "lungs", "Lungs (폐)"),
    ("lung", "lungs", "Lungs (폐)"),
    ("bronchi", "bronchi", "Bronchi & Trachea (기관지)"),
    ("bronchus", "bronchi", "Bronchi & Trachea (기관지)"),
    ("ascending aorta", "ascending_aorta", "Ascending Aorta (상행대동맥)"),
    ("aortic arch", "aortic_arch", "Aortic Arch (대동맥궁)"),
    ("thoracic aorta", "thoracic_aorta", "Thoracic Aorta (흉부대동맥)"),
    ("abdominal aorta", "abdominal_aorta", "Abdominal Aorta (복부대동맥)"),
    ("aorta", "aorta", "Aorta (대동맥)"),
    ("pulmonary artery", "pulmonary artery", "Pulmonary Arteries (폐동맥)"),
    ("pulmonary trunk", "pulmonary_trunk", "Pulmonary Trunk (폐동맥간)"),
    ("superior vena cava", "superior_vena_cava", "Superior Vena Cava (상대정맥)"),
    ("inferior vena cava", "inferior_vena_cava", "Inferior Vena Cava (하대정맥)"),
    ("vena cava", "vena cava", "Superior & Inferior Vena Cava (대정맥)"),
    ("diaphragm", "diaphragm", "Diaphragm (횡격막)"),
    ("rib cage", "ribcage", "Rib Cage (흉곽)"),
    ("ribcage", "ribcage", "Rib Cage (흉곽)"),
    ("ribs", "ribs", "Ribs (갈비뼈·늑골)"),
    ("rib", "ribs", "Ribs (갈비뼈·늑골)"),
    ("sternum", "sternum", "Sternum (흉골)"),
    ("breastbone", "sternum", "Sternum (흉골)"),
    ("pectoralis major", "pectoralis major", "Pectoralis Major (대흉근)"),
    ("pectoralis minor", "pectoralis minor", "Pectoralis Minor (소흉근)"),
    ("pec major", "pectoralis major", "Pectoralis Major (대흉근)"),
    ("pec minor", "pectoralis minor", "Pectoralis Minor (소흉근)"),
    ("pectoralis", "pectoralis major", "Pectoralis Major (대흉근)"),
    ("intercostals", "intercostal", "Intercostal Muscles (늑간근)"),
    ("intercostal muscles", "intercostal", "Intercostal Muscles (늑간근)"),
    ("intercostal", "intercostal", "Intercostal Muscles (늑간근)"),
    ("serratus anterior", "serratus anterior", "Serratus Anterior (전거근)"),
    ("좌심실", "heart_left_ventricle", "Left Ventricle (좌심실)"),
    ("우심실", "heart_right_ventricle", "Right Ventricle (우심실)"),
    ("좌심방", "heart_left_atrium", "Left Atrium (좌심방)"),
    ("우심방", "heart_right_atrium", "Right Atrium (우심방)"),
    ("심장", "heart", "Heart (심장)"),
    ("오른폐", "right lung", "Right Lung (우폐)"),
    ("우폐", "right lung", "Right Lung (우폐)"),
    ("왼폐", "left lung", "Left Lung (좌폐)"),
    ("좌폐", "left lung", "Left Lung (좌폐)"),
    ("허파", "lungs", "Lungs (폐)"),
    ("폐동맥간", "pulmonary_trunk", "Pulmonary Trunk (폐동맥간)"),
    ("폐동맥", "pulmonary artery", "Pulmonary Arteries (폐동맥)"),
    ("상행대동맥", "ascending_aorta", "Ascending Aorta (상행대동맥)"),
    ("대동맥궁", "aortic_arch", "Aortic Arch (대동맥궁)"),
    ("흉부대동맥", "thoracic_aorta", "Thoracic Aorta (흉부대동맥)"),
    ("복부대동맥", "abdominal_aorta", "Abdominal Aorta (복부대동맥)"),
    ("대동맥", "aorta", "Aorta (대동맥)"),
    ("상대정맥", "superior_vena_cava", "Superior Vena Cava (상대정맥)"),
    ("하대정맥", "inferior_vena_cava", "Inferior Vena Cava (하대정맥)"),
    ("대정맥", "vena cava", "Vena Cava (대정맥)"),
    ("폐", "lungs", "Lungs (폐)"),
    ("횡격막", "diaphragm", "Diaphragm (횡격막)"),
    ("가로막", "diaphragm", "Diaphragm (횡격막)"),
    ("흉곽", "ribcage", "Rib Cage (흉곽)"),
    ("갈비뼈", "ribs", "Ribs (갈비뼈·늑골)"),
    ("늑골", "ribs", "Ribs (갈비뼈·늑골)"),
    ("흉골", "sternum", "Sternum (흉골)"),
    ("복장뼈", "sternum", "Sternum (흉골)"),
    ("대흉근", "pectoralis major", "Pectoralis Major (대흉근)"),
    ("큰가슴근", "pectoralis major", "Pectoralis Major (대흉근)"),
    ("소흉근", "pectoralis minor", "Pectoralis Minor (소흉근)"),
    ("작은가슴근", "pectoralis minor", "Pectoralis Minor (소흉근)"),
    ("늑간근", "intercostal", "Intercostal Muscles (늑간근)"),
    ("갈비사이근", "intercostal", "Intercostal Muscles (늑간근)"),
    ("전거근", "serratus anterior", "Serratus Anterior (전거근)"),
    ("앞톱니근", "serratus anterior", "Serratus Anterior (전거근)"),

    # --- 3. Abdomen & Visceral Organs ---
    ("gallbladder", "gallbladder", "Gallbladder (담낭)"),
    ("gall bladder", "gallbladder", "Gallbladder (담낭)"),
    ("liver", "liver", "Liver (간)"),
    ("stomach", "stomach", "Stomach (위)"),
    ("spleen", "spleen", "Spleen (비장)"),
    ("pancreas", "pancreas", "Pancreas (췌장)"),
    ("kidneys", "kidneys", "Renal & Retroperitoneal Region (신장·후복막 구조)"),
    ("kidney", "kidneys", "Renal & Retroperitoneal Region (신장·후복막 구조)"),
    ("small intestine", "small intestine", "Small Intestine (소장)"),
    ("duodenum", "duodenum", "Duodenum (십이지장)"),
    ("jejunum", "jejunum_ileum", "Jejunum & Ileum (공장·회장)"),
    ("ileum", "jejunum_ileum", "Jejunum & Ileum (공장·회장)"),
    ("large intestine", "large intestine", "Large Intestine / Colon (대장)"),
    ("ascending colon", "ascending_colon", "Ascending Colon (상행결장)"),
    ("transverse colon", "transverse_colon", "Transverse Colon (횡행결장)"),
    ("descending colon", "descending_colon", "Descending Colon (하행결장)"),
    ("sigmoid colon", "sigmoid_colon", "Sigmoid Colon (S상결장)"),
    ("colon", "large intestine", "Colon / Large Intestine (대장·결장)"),
    ("cecum", "cecum", "Cecum (맹장)"),
    ("appendix", "appendix", "Appendix (충수)"),
    ("rectum", "rectum", "Rectum (직장)"),
    ("intestines", "intestines", "Small & Large Intestines (소장·대장)"),
    ("intestine", "intestines", "Small & Large Intestines (소장·대장)"),
    ("bowels", "intestines", "Intestines (장)"),
    ("bowel", "intestines", "Intestines (장)"),
    ("urinary bladder", "urinary_bladder", "Urinary Bladder (방광)"),
    ("bladder", "urinary_bladder", "Urinary Bladder (방광)"),
    ("hepatic portal vein", "hepatic_portal_vein", "Hepatic Portal Vein (간문맥)"),
    ("portal vein", "hepatic_portal_vein", "Hepatic Portal Vein (간문맥)"),
    ("celiac trunk", "celiac_trunk", "Celiac Trunk (복강동맥)"),
    ("superior mesenteric artery", "superior_mesenteric_artery", "Superior Mesenteric Artery (상장간막동맥)"),
    ("inferior mesenteric artery", "inferior_mesenteric_artery", "Inferior Mesenteric Artery (하장간막동맥)"),
    ("mesenteric artery", "superior_mesenteric_artery", "Mesenteric Artery (장간막동맥)"),
    ("internal organs", "viscera", "Internal Visceral Organs (내장 기관)"),
    ("visceral organs", "viscera", "Internal Visceral Organs (내장 기관)"),
    ("viscera", "viscera", "Internal Visceral Organs (내장 기관)"),
    ("organs", "viscera", "Internal Visceral Organs (내장 기관)"),
    ("간문맥", "hepatic_portal_vein", "Hepatic Portal Vein (간문맥)"),
    ("담낭", "gallbladder", "Gallbladder (담낭)"),
    ("쓸개", "gallbladder", "Gallbladder (담낭)"),
    ("간장", "liver", "Liver (간)"),
    ("간", "liver", "Liver (간)"),
    ("위장", "stomach", "Stomach (위)"),
    ("위", "stomach", "Stomach (위)"),
    ("비장", "spleen", "Spleen (비장)"),
    ("지라", "spleen", "Spleen (비장)"),
    ("췌장", "pancreas", "Pancreas (췌장)"),
    ("이자", "pancreas", "Pancreas (췌장)"),
    ("신장", "kidneys", "Renal & Retroperitoneal Region (신장·후복막 구조)"),
    ("콩팥", "kidneys", "Renal & Retroperitoneal Region (신장·후복막 구조)"),
    ("십이지장", "duodenum", "Duodenum (십이지장)"),
    ("공장", "jejunum_ileum", "Jejunum & Ileum (공장·회장)"),
    ("회장", "jejunum_ileum", "Jejunum & Ileum (공장·회장)"),
    ("소장", "small intestine", "Small Intestine (소장)"),
    ("작은창자", "small intestine", "Small Intestine (소장)"),
    ("상행결장", "ascending_colon", "Ascending Colon (상행결장)"),
    ("횡행결장", "transverse_colon", "Transverse Colon (횡행결장)"),
    ("하행결장", "descending_colon", "Descending Colon (하행결장)"),
    ("에스상결장", "sigmoid_colon", "Sigmoid Colon (S상결장)"),
    ("맹장", "cecum", "Cecum (맹장)"),
    ("충수", "appendix", "Appendix (충수)"),
    ("직장", "rectum", "Rectum (직장)"),
    ("대장", "large intestine", "Large Intestine (대장)"),
    ("큰창자", "large intestine", "Large Intestine (대장)"),
    ("결장", "large intestine", "Colon (결장)"),
    ("창자", "intestines", "Intestines (장)"),
    ("방광", "urinary_bladder", "Urinary Bladder (방광)"),
    ("오줌보", "urinary_bladder", "Urinary Bladder (방광)"),
    ("내장기관", "viscera", "Internal Visceral Organs (내장 기관)"),
    ("내장", "viscera", "Internal Visceral Organs (내장 기관)"),
    ("장기", "viscera", "Internal Visceral Organs (내장 기관)"),

    # --- 4. Spine, Pelvis & Core ---
    ("cervical spine", "cervical spine", "Cervical Spine C1–C7 (경추)"),
    ("c-spine", "cervical spine", "Cervical Spine C1–C7 (경추)"),
    ("thoracic spine", "thoracic spine", "Thoracic Spine T1–T12 (흉추)"),
    ("t-spine", "thoracic spine", "Thoracic Spine T1–T12 (흉추)"),
    ("lumbar spine", "lumbar spine", "Lumbar Spine L1–L5 (요추)"),
    ("l-spine", "lumbar spine", "Lumbar Spine L1–L5 (요추)"),
    ("vertebral column", "spine", "Vertebral Column / Spine (척추)"),
    ("intervertebral discs", "intervertebral discs", "Intervertebral Discs (추간판·디스크)"),
    ("intervertebral disc", "intervertebral discs", "Intervertebral Discs (추간판·디스크)"),
    ("spinal discs", "intervertebral discs", "Intervertebral Discs (추간판·디스크)"),
    ("vertebrae", "spine", "Vertebrae / Spine (척추)"),
    ("spine", "spine", "Vertebral Column / Spine (척추)"),
    ("sacrum", "sacrum", "Sacrum (천골)"),
    ("coccyx", "coccyx", "Coccyx (미골)"),
    ("tailbone", "coccyx", "Coccyx (미골)"),
    ("hip bone", "pelvis", "Pelvis / Hip Bone (골반·관골)"),
    ("pelvis", "pelvis", "Pelvis & Sacrum (골반)"),
    ("ilium", "pelvis", "Ilium / Pelvis (장골·골반)"),
    ("ischium", "pelvis", "Ischium / Pelvis (좌골·골반)"),
    ("pubis", "pelvis", "Pubis / Pelvis (치골·골반)"),
    ("rectus abdominis", "rectus abdominis", "Rectus Abdominis (복직근)"),
    ("abdominal muscles", "abdominal muscles", "Abdominal Wall Muscles (복근)"),
    ("abs", "rectus abdominis", "Rectus Abdominis (복직근)"),
    ("external oblique", "external oblique", "External Oblique (외복사근)"),
    ("internal oblique", "internal oblique", "Internal Oblique (내복사근)"),
    ("transversus abdominis", "transversus abdominis", "Transversus Abdominis (복횡근)"),
    ("obliques", "external oblique", "Abdominal Obliques (복사근)"),
    ("iliopsoas", "iliopsoas", "Iliopsoas (장요근)"),
    ("psoas major", "psoas major", "Psoas Major (대요근)"),
    ("psoas", "psoas major", "Psoas Major (대요근)"),
    ("iliacus", "iliacus", "Iliacus (장골근)"),
    ("quadratus lumborum", "quadratus lumborum", "Quadratus Lumborum (요방형근)"),
    ("erector spinae", "erector spinae", "Erector Spinae (척추기립근)"),
    ("iliocostalis", "iliocostalis", "Iliocostalis (장늑근)"),
    ("longissimus", "longissimus", "Longissimus (최장근)"),
    ("latissimus dorsi", "latissimus dorsi", "Latissimus Dorsi (광배근)"),
    ("lats", "latissimus dorsi", "Latissimus Dorsi (광배근)"),
    ("rhomboid major", "rhomboids", "Rhomboid Major & Minor (능형근)"),
    ("rhomboid minor", "rhomboids", "Rhomboid Major & Minor (능형근)"),
    ("rhomboids", "rhomboids", "Rhomboids (능형근)"),
    ("rhomboid", "rhomboids", "Rhomboids (능형근)"),
    ("levator scapulae", "levator scapulae", "Levator Scapulae (견갑거근)"),
    ("trapezius", "trapezius", "Trapezius (승모근)"),
    ("경추", "cervical spine", "Cervical Spine C1–C7 (경추)"),
    ("목뼈", "cervical spine", "Cervical Spine C1–C7 (경추)"),
    ("흉추", "thoracic spine", "Thoracic Spine T1–T12 (흉추)"),
    ("요추", "lumbar spine", "Lumbar Spine L1–L5 (요추)"),
    ("허리뼈", "lumbar spine", "Lumbar Spine L1–L5 (요추)"),
    ("추간판", "intervertebral discs", "Intervertebral Discs (추간판·디스크)"),
    ("디스크", "intervertebral discs", "Intervertebral Discs (추간판·디스크)"),
    ("척추기립근", "erector spinae", "Erector Spinae (척추기립근)"),
    ("기립근", "erector spinae", "Erector Spinae (척추기립근)"),
    ("장늑근", "iliocostalis", "Iliocostalis (장늑근)"),
    ("최장근", "longissimus", "Longissimus (최장근)"),
    ("척추", "spine", "Vertebral Column / Spine (척추)"),
    ("척주", "spine", "Vertebral Column / Spine (척추)"),
    ("등뼈", "spine", "Vertebral Column / Spine (척추)"),
    ("천골", "sacrum", "Sacrum (천골)"),
    ("엉치뼈", "sacrum", "Sacrum (천골)"),
    ("미골", "coccyx", "Coccyx (미골)"),
    ("꼬리뼈", "coccyx", "Coccyx (미골)"),
    ("골반", "pelvis", "Pelvis (골반)"),
    ("엉덩뼈", "pelvis", "Pelvis / Hip Bone (골반·관골)"),
    ("관골", "pelvis", "Hip Bone (관골)"),
    ("장골근", "iliacus", "Iliacus (장골근)"),
    ("장골동맥", "iliac artery", "Iliac Arteries (장골동맥)"),
    ("장골정맥", "iliac vein", "Iliac Veins (장골정맥)"),
    ("장골", "pelvis", "Ilium / Pelvis (장골)"),
    ("복직근", "rectus abdominis", "Rectus Abdominis (복직근)"),
    ("외복사근", "external oblique", "External Oblique (외복사근)"),
    ("내복사근", "internal oblique", "Internal Oblique (내복사근)"),
    ("복횡근", "transversus abdominis", "Transversus Abdominis (복횡근)"),
    ("복사근", "external oblique", "Abdominal Obliques (복사근)"),
    ("복근", "abdominal muscles", "Abdominal Wall Muscles (복근)"),
    ("장요근", "iliopsoas", "Iliopsoas (장요근)"),
    ("대요근", "psoas major", "Psoas Major (대요근)"),
    ("요방형근", "quadratus lumborum", "Quadratus Lumborum (요방형근)"),
    ("광배근", "latissimus dorsi", "Latissimus Dorsi (광배근)"),
    ("넓은등근", "latissimus dorsi", "Latissimus Dorsi (광배근)"),
    ("능형근", "rhomboids", "Rhomboids (능형근)"),
    ("마름근", "rhomboids", "Rhomboids (능형근)"),
    ("견갑거근", "levator scapulae", "Levator Scapulae (견갑거근)"),
    ("어깨올림근", "levator scapulae", "Levator Scapulae (견갑거근)"),
    ("승모근", "trapezius", "Trapezius (승모근)"),
    ("등세모근", "trapezius", "Trapezius (승모근)"),

    # --- 5. Upper Limb & Shoulder ---
    ("rotator cuff", "rotator cuff", "Rotator Cuff (회전근개 4근)"),
    ("subscapularis", "subscapularis", "Subscapularis (견갑하근)"),
    ("supraspinatus", "supraspinatus", "Supraspinatus (극상근)"),
    ("infraspinatus", "infraspinatus", "Infraspinatus (극하근)"),
    ("teres minor", "teres minor", "Teres Minor (소원근)"),
    ("teres major", "teres major", "Teres Major (대원근)"),
    ("anterior deltoid", "anterior deltoid", "Anterior Deltoid (전방삼각근)"),
    ("middle deltoid", "middle deltoid", "Lateral/Middle Deltoid (중간삼각근)"),
    ("lateral deltoid", "middle deltoid", "Lateral/Middle Deltoid (중간삼각근)"),
    ("posterior deltoid", "posterior deltoid", "Posterior Deltoid (후방삼각근)"),
    ("deltoid", "deltoid", "Deltoid (삼각근)"),
    ("biceps brachii", "biceps", "Biceps Brachii (상완이두근)"),
    ("biceps", "biceps", "Biceps Brachii (상완이두근)"),
    ("triceps brachii", "triceps", "Triceps Brachii (상완삼두근)"),
    ("triceps", "triceps", "Triceps Brachii (상완삼두근)"),
    ("brachialis", "brachialis", "Brachialis (상완근)"),
    ("coracobrachialis", "coracobrachialis", "Coracobrachialis (오훼완근)"),
    ("brachioradialis", "brachioradialis", "Brachioradialis (완요골근)"),
    ("pronator teres", "pronator teres", "Pronator Teres (원회내근)"),
    ("forearm flexors", "forearm", "Forearm Muscles (전완근)"),
    ("forearm extensors", "forearm", "Forearm Muscles (전완근)"),
    ("forearm", "forearm", "Forearm (전완)"),
    ("scapula", "scapula", "Scapula (견갑골)"),
    ("shoulder blade", "scapula", "Scapula (견갑골)"),
    ("clavicle", "clavicle", "Clavicle (쇄골)"),
    ("collarbone", "clavicle", "Clavicle (쇄골)"),
    ("humerus", "humerus", "Humerus (상완골)"),
    ("radius", "radius", "Radius (요골)"),
    ("ulna", "ulna", "Ulna (척골)"),
    ("hand bones", "hand", "Hand Bones (수골·손뼈)"),
    ("wrist", "hand", "Wrist & Hand Bones (손목·수근골)"),
    ("hand", "hand", "Hand (손)"),
    ("glenohumeral capsule", "glenohumeral capsule", "Glenohumeral Joint Capsule (관절낭)"),
    ("joint capsule", "glenohumeral capsule", "Glenohumeral Joint Capsule (관절낭)"),
    ("coracoacromial ligament", "coracoacromial ligament", "Coracoacromial Ligament (오훼견봉인대)"),
    ("subacromial bursa", "subacromial bursa", "Subacromial Bursa (견봉하점액낭)"),
    ("bursa", "subacromial bursa", "Subacromial & Subdeltoid Bursa (점액낭)"),
    ("brachial plexus", "brachial plexus", "Brachial Plexus (완신경총)"),
    ("axillary nerve", "axillary nerve", "Axillary Nerve (액와신경)"),
    ("suprascapular nerve", "suprascapular nerve", "Suprascapular Nerve (견갑상신경)"),
    ("median nerve", "median nerve", "Median Nerve (정중신경)"),
    ("ulnar nerve", "ulnar nerve", "Ulnar Nerve (척골신경)"),
    ("radial nerve", "radial nerve", "Radial Nerve (요골신경)"),
    ("musculocutaneous nerve", "musculocutaneous nerve", "Musculocutaneous Nerve (근피신경)"),
    ("axillary artery", "axillary artery", "Axillary Artery (액와동맥)"),
    ("brachial artery", "brachial artery", "Brachial Artery (상완동맥)"),
    ("subclavian artery", "subclavian artery", "Subclavian Artery (쇄골하동맥)"),
    ("subclavian vein", "subclavian vein", "Subclavian Vein (쇄골하정맥)"),
    ("cephalic vein", "cephalic vein", "Cephalic Vein (노쪽피부정맥)"),
    ("basilic vein", "basilic vein", "Basilic Vein (자쪽피부정맥)"),
    ("회전근개", "rotator cuff", "Rotator Cuff (회전근개 4근)"),
    ("견갑하근", "subscapularis", "Subscapularis (견갑하근)"),
    ("어깨밑근", "subscapularis", "Subscapularis (견갑하근)"),
    ("극상근", "supraspinatus", "Supraspinatus (극상근)"),
    ("가시위근", "supraspinatus", "Supraspinatus (극상근)"),
    ("극하근", "infraspinatus", "Infraspinatus (극하근)"),
    ("가시아래근", "infraspinatus", "Infraspinatus (극하근)"),
    ("소원근", "teres minor", "Teres Minor (소원근)"),
    ("작은원근", "teres minor", "Teres Minor (소원근)"),
    ("대원근", "teres major", "Teres Major (대원근)"),
    ("큰원근", "teres major", "Teres Major (대원근)"),
    ("전방삼각근", "anterior deltoid", "Anterior Deltoid (전방삼각근)"),
    ("중간삼각근", "middle deltoid", "Middle Deltoid (중간삼각근)"),
    ("후방삼각근", "posterior deltoid", "Posterior Deltoid (후방삼각근)"),
    ("삼각근", "deltoid", "Deltoid (삼각근)"),
    ("어깨세모근", "deltoid", "Deltoid (삼각근)"),
    ("상완이두근", "biceps", "Biceps Brachii (상완이두근)"),
    ("이두근", "biceps", "Biceps Brachii (상완이두근)"),
    ("상완삼두근", "triceps", "Triceps Brachii (상완삼두근)"),
    ("삼두근", "triceps", "Triceps Brachii (상완삼두근)"),
    ("상완근", "brachialis", "Brachialis (상완근)"),
    ("오훼완근", "coracobrachialis", "Coracobrachialis (오훼완근)"),
    ("오구완근", "coracobrachialis", "Coracobrachialis (오훼완근)"),
    ("완요골근", "brachioradialis", "Brachioradialis (완요골근)"),
    ("원회내근", "pronator teres", "Pronator Teres (원회내근)"),
    ("전완", "forearm", "Forearm (전완)"),
    ("아래팔", "forearm", "Forearm (전완)"),
    ("견갑골", "scapula", "Scapula (견갑골)"),
    ("어깨뼈", "scapula", "Scapula (견갑골)"),
    ("쇄골하동맥", "subclavian artery", "Subclavian Artery (쇄골하동맥)"),
    ("쇄골하정맥", "subclavian vein", "Subclavian Vein (쇄골하정맥)"),
    ("쇄골", "clavicle", "Clavicle (쇄골)"),
    ("빗장뼈", "clavicle", "Clavicle (쇄골)"),
    ("상완골", "humerus", "Humerus (상완골)"),
    ("위팔뼈", "humerus", "Humerus (상완골)"),
    ("요골신경", "radial nerve", "Radial Nerve (요골신경)"),
    ("척골신경", "ulnar nerve", "Ulnar Nerve (척골신경)"),
    ("요골", "radius", "Radius (요골)"),
    ("노뼈", "radius", "Radius (요골)"),
    ("척골", "ulna", "Ulna (척골)"),
    ("자뼈", "ulna", "Ulna (척골)"),
    ("수근골", "hand", "Carpals & Hand Bones (수근골·손뼈)"),
    ("손목뼈", "hand", "Carpals & Hand Bones (수근골·손뼈)"),
    ("관절낭", "glenohumeral capsule", "Glenohumeral Joint Capsule (관절낭)"),
    ("오훼견봉인대", "coracoacromial ligament", "Coracoacromial Ligament (오훼견봉인대)"),
    ("견봉하점액낭", "subacromial bursa", "Subacromial Bursa (견봉하점액낭)"),
    ("점액낭", "subacromial bursa", "Subacromial Bursa (점액낭)"),
    ("완신경총", "brachial plexus", "Brachial Plexus (완신경총)"),
    ("팔신경얼기", "brachial plexus", "Brachial Plexus (완신경총)"),
    ("액와신경", "axillary nerve", "Axillary Nerve (액와신경)"),
    ("겨드랑신경", "axillary nerve", "Axillary Nerve (액와신경)"),
    ("견갑상신경", "suprascapular nerve", "Suprascapular Nerve (견갑상신경)"),
    ("정중신경", "median nerve", "Median Nerve (정중신경)"),
    ("근피신경", "musculocutaneous nerve", "Musculocutaneous Nerve (근피신경)"),
    ("액와동맥", "axillary artery", "Axillary Artery (액와동맥)"),
    ("상완동맥", "brachial artery", "Brachial Artery (상완동맥)"),

    # --- 6. Lower Limb ---
    ("gluteus maximus", "gluteus maximus", "Gluteus Maximus (대둔근)"),
    ("gluteus medius", "gluteus medius", "Gluteus Medius (중둔근)"),
    ("gluteus minimus", "gluteus minimus", "Gluteus Minimus (소둔근)"),
    ("gluteal muscles", "glutes", "Gluteal Muscles (둔근)"),
    ("glutes", "glutes", "Gluteal Muscles (둔근)"),
    ("piriformis", "piriformis", "Piriformis (이상근)"),
    ("tensor fasciae latae", "tensor fasciae latae", "Tensor Fasciae Latae (대퇴근막장근)"),
    ("tfl", "tensor fasciae latae", "Tensor Fasciae Latae (대퇴근막장근)"),
    ("quadriceps femoris", "quadriceps", "Quadriceps Femoris (대퇴사두근)"),
    ("quadriceps", "quadriceps", "Quadriceps Femoris (대퇴사두근)"),
    ("quads", "quadriceps", "Quadriceps Femoris (대퇴사두근)"),
    ("rectus femoris", "rectus femoris", "Rectus Femoris (대퇴직근)"),
    ("vastus lateralis", "vastus lateralis", "Vastus Lateralis (외측광근)"),
    ("vastus medialis", "vastus medialis", "Vastus Medialis (내측광근)"),
    ("vastus intermedius", "vastus intermedius", "Vastus Intermedius (중간광근)"),
    ("sartorius", "sartorius", "Sartorius (봉공근)"),
    ("hamstrings", "hamstrings", "Hamstrings (햄스트링·슬괵근)"),
    ("hamstring", "hamstrings", "Hamstrings (햄스트링·슬괵근)"),
    ("biceps femoris", "biceps femoris", "Biceps Femoris (대퇴이두근)"),
    ("semitendinosus", "semitendinosus", "Semitendinosus (반건양근)"),
    ("semimembranosus", "semimembranosus", "Semimembranosus (반막양근)"),
    ("adductor magnus", "adductor magnus", "Adductor Magnus (대내전근)"),
    ("adductor longus", "adductor longus", "Adductor Longus (장내전근)"),
    ("adductor brevis", "adductor brevis", "Adductor Brevis (단내전근)"),
    ("adductors", "adductors", "Hip Adductors (내전근군)"),
    ("gracilis", "gracilis", "Gracilis (박근)"),
    ("pectineus", "pectineus", "Pectineus (치골근)"),
    ("gastrocnemius", "gastrocnemius", "Gastrocnemius (비복근)"),
    ("soleus", "soleus", "Soleus (가자미근)"),
    ("calf muscles", "calf", "Calf Muscles / Triceps Surae (종아리 근육)"),
    ("calf", "calf", "Calf Muscles / Triceps Surae (종아리 근육)"),
    ("tibialis anterior", "tibialis anterior", "Tibialis Anterior (전경골근)"),
    ("tibialis posterior", "tibialis posterior", "Tibialis Posterior (후경골근)"),
    ("fibularis", "fibularis", "Fibularis / Peroneal Muscles (비골근)"),
    ("peroneals", "fibularis", "Fibularis / Peroneal Muscles (비골근)"),
    ("femur", "femur", "Femur (대퇴골)"),
    ("thigh bone", "femur", "Femur (대퇴골)"),
    ("patella", "patella", "Patella (슬개골)"),
    ("kneecap", "patella", "Patella (슬개골)"),
    ("tibia", "tibia", "Tibia (경골)"),
    ("shin bone", "tibia", "Tibia (경골)"),
    ("fibula", "fibula", "Fibula (비골)"),
    ("calcaneus", "calcaneus", "Calcaneus (종골)"),
    ("talus", "talus", "Talus (거골)"),
    ("foot bones", "foot", "Foot & Ankle Bones (족골·발뼈)"),
    ("ankle", "foot", "Ankle & Foot Bones (발목·족근골)"),
    ("foot", "foot", "Foot & Ankle (발)"),
    ("sciatic nerve", "sciatic nerve", "Sciatic Nerve (좌골신경)"),
    ("sciatic", "sciatic nerve", "Sciatic Nerve (좌골신경)"),
    ("femoral nerve", "femoral nerve", "Femoral Nerve (대퇴신경)"),
    ("tibial nerve", "tibial nerve", "Tibial Nerve (경골신경)"),
    ("common fibular nerve", "common fibular nerve", "Common Fibular Nerve (총비골신경)"),
    ("peroneal nerve", "common fibular nerve", "Common Fibular Nerve (총비골신경)"),
    ("obturator nerve", "obturator nerve", "Obturator Nerve (폐쇄신경)"),
    ("femoral artery", "femoral artery", "Femoral Artery (대퇴동맥)"),
    ("femoral vein", "femoral vein", "Femoral Vein (대퇴정맥)"),
    ("popliteal artery", "popliteal artery", "Popliteal Artery (슬와동맥)"),
    ("great saphenous vein", "great saphenous vein", "Great Saphenous Vein (대복재정맥)"),
    ("saphenous vein", "great saphenous vein", "Great Saphenous Vein (대복재정맥)"),
    ("대둔근", "gluteus maximus", "Gluteus Maximus (대둔근)"),
    ("큰볼기근", "gluteus maximus", "Gluteus Maximus (대둔근)"),
    ("중둔근", "gluteus medius", "Gluteus Medius (중둔근)"),
    ("중간볼기근", "gluteus medius", "Gluteus Medius (중둔근)"),
    ("소둔근", "gluteus minimus", "Gluteus Minimus (소둔근)"),
    ("작은볼기근", "gluteus minimus", "Gluteus Minimus (소둔근)"),
    ("둔근", "glutes", "Gluteal Muscles (둔근)"),
    ("엉덩이근육", "glutes", "Gluteal Muscles (둔근)"),
    ("이상근", "piriformis", "Piriformis (이상근)"),
    ("궁둥구멍근", "piriformis", "Piriformis (이상근)"),
    ("대퇴근막장근", "tensor fasciae latae", "Tensor Fasciae Latae (대퇴근막장근)"),
    ("대퇴사두근", "quadriceps", "Quadriceps Femoris (대퇴사두근)"),
    ("사두근", "quadriceps", "Quadriceps Femoris (대퇴사두근)"),
    ("대퇴직근", "rectus femoris", "Rectus Femoris (대퇴직근)"),
    ("외측광근", "vastus lateralis", "Vastus Lateralis (외측광근)"),
    ("내측광근", "vastus medialis", "Vastus Medialis (내측광근)"),
    ("중간광근", "vastus intermedius", "Vastus Intermedius (중간광근)"),
    ("봉공근", "sartorius", "Sartorius (봉공근)"),
    ("햄스트링", "hamstrings", "Hamstrings (햄스트링·슬괵근)"),
    ("슬괵근", "hamstrings", "Hamstrings (햄스트링·슬괵근)"),
    ("대퇴이두근", "biceps femoris", "Biceps Femoris (대퇴이두근)"),
    ("반건양근", "semitendinosus", "Semitendinosus (반건양근)"),
    ("반막양근", "semimembranosus", "Semimembranosus (반막양근)"),
    ("대내전근", "adductor magnus", "Adductor Magnus (대내전근)"),
    ("장내전근", "adductor longus", "Adductor Longus (장내전근)"),
    ("단내전근", "adductor brevis", "Adductor Brevis (단내전근)"),
    ("내전근", "adductors", "Hip Adductors (내전근군)"),
    ("박근", "gracilis", "Gracilis (박근)"),
    ("치골근", "pectineus", "Pectineus (치골근)"),
    ("비복근", "gastrocnemius", "Gastrocnemius (비복근)"),
    ("장딴지근", "gastrocnemius", "Gastrocnemius (비복근)"),
    ("가자미근", "soleus", "Soleus (가자미근)"),
    ("종아리근육", "calf", "Calf Muscles (종아리 근육)"),
    ("종아리", "calf", "Calf Muscles (종아리 근육)"),
    ("전경골근", "tibialis anterior", "Tibialis Anterior (전경골근)"),
    ("앞정강근", "tibialis anterior", "Tibialis Anterior (전경골근)"),
    ("후경골근", "tibialis posterior", "Tibialis Posterior (후경골근)"),
    ("뒤정강근", "tibialis posterior", "Tibialis Posterior (후경골근)"),
    ("총비골신경", "common fibular nerve", "Common Fibular Nerve (총비골신경)"),
    ("비골신경", "common fibular nerve", "Common Fibular Nerve (총비골신경)"),
    ("비골근", "fibularis", "Fibularis Muscles (비골근)"),
    ("좌골신경", "sciatic nerve", "Sciatic Nerve (좌골신경)"),
    ("궁둥신경", "sciatic nerve", "Sciatic Nerve (좌골신경)"),
    ("대퇴신경", "femoral nerve", "Femoral Nerve (대퇴신경)"),
    ("경골신경", "tibial nerve", "Tibial Nerve (경골신경)"),
    ("폐쇄신경", "obturator nerve", "Obturator Nerve (폐쇄신경)"),
    ("대퇴동맥", "femoral artery", "Femoral Artery (대퇴동맥)"),
    ("대퇴정맥", "femoral vein", "Femoral Vein (대퇴정맥)"),
    ("슬와동맥", "popliteal artery", "Popliteal Artery (슬와동맥)"),
    ("대복재정맥", "great saphenous vein", "Great Saphenous Vein (대복재정맥)"),
    ("복재정맥", "great saphenous vein", "Great Saphenous Vein (대복재정맥)"),
    ("대퇴골", "femur", "Femur (대퇴골)"),
    ("넓적다리뼈", "femur", "Femur (대퇴골)"),
    ("슬개골", "patella", "Patella (슬개골)"),
    ("무릎뼈", "patella", "Patella (슬개골)"),
    ("경골", "tibia", "Tibia (경골)"),
    ("정강이뼈", "tibia", "Tibia (경골)"),
    ("비골", "fibula", "Fibula (비골)"),
    ("종아리뼈", "fibula", "Fibula (비골)"),
    ("종골", "calcaneus", "Calcaneus (종골)"),
    ("뒤꿈치뼈", "calcaneus", "Calcaneus (종골)"),
    ("거골", "talus", "Talus (거골)"),
    ("족근골", "foot", "Tarsals & Foot Bones (족근골·발뼈)"),
]

CANONICAL_LABEL_MAP: Dict[str, str] = {
    canonical: label for _kw, canonical, label in ANATOMY_KEYWORDS_ORDERED
}


def _filter_ids_by_side(ids: List[str], explicit_side: Optional[str]) -> List[str]:
    """Filters structure IDs to `_r`/`right_` or `_l`/`left_` only if an explicit side was requested."""
    if not explicit_side or explicit_side not in ("right", "left"):
        return ids
    suffix = "_r" if explicit_side == "right" else "_l"
    prefix = "right_" if explicit_side == "right" else "left_"
    opp_suffix = "_l" if explicit_side == "right" else "_r"
    opp_prefix = "left_" if explicit_side == "right" else "right_"
    filtered = [
        sid
        for sid in ids
        if sid.endswith(suffix)
        or sid.startswith(prefix)
        or (not sid.endswith(opp_suffix) and not sid.startswith(opp_prefix))
    ]
    return filtered or ids


def _expand_anatomy_term(term: str, explicit_side: Optional[str] = None) -> List[str]:
    """
    Expands a canonical anatomical term, structure ID, or natural phrase into exact
    validated manifest structure IDs across all 385 whole-body structures.
    """
    raw = (term or "").strip()
    if not raw:
        return []

    # Detect embedded side prefix in `raw` if `explicit_side` wasn't passed
    t_low = raw.lower()
    effective_side = explicit_side
    if effective_side is None:
        if any(w in t_low for w in ["오른쪽 ", "우측 ", "right "]) and not any(
            w in t_low for w in ["right lung", "right ventricle", "right atrium"]
        ):
            effective_side = "right"
        elif any(w in t_low for w in ["왼쪽 ", "좌측 ", "left "]) and not any(
            w in t_low for w in ["left lung", "left ventricle", "left atrium"]
        ):
            effective_side = "left"

    clean = re.sub(r"^(오른쪽|우측|왼쪽|좌측|양측|right|left|bilateral)\s+", "", t_low).strip()

    # 1. Exact structure ID in manifest
    if raw in SCENE_SERVICE.structures_by_id:
        return [raw]
    if clean in SCENE_SERVICE.structures_by_id:
        return [clean]

    # 2. Exact curated whole-body mappings to avoid substring collisions
    all_structs = list(SCENE_SERVICE.structures_by_id.values())

    def _by_group(*groups: str) -> List[str]:
        gset = set(groups)
        return [s["id"] for s in all_structs if s.get("group") in gset]

    def _by_prefix(*prefixes: str) -> List[str]:
        return [
            s["id"]
            for s in all_structs
            if any(s["id"] == p or s["id"].startswith(p + "_") for p in prefixes)
        ]

    curated_map: Dict[str, List[str]] = {
        # Head, Neck & Brain
        "brain": _by_group("brain_cns"),
        "cerebrum": [
            "cerebrum_r", "cerebrum_l",
            "superior_frontal_gyrus_r", "superior_frontal_gyrus_l",
            "precentral_gyrus_r", "precentral_gyrus_l",
            "postcentral_gyrus_r", "postcentral_gyrus_l",
            "superior_parietal_lobule_r", "superior_parietal_lobule_l",
            "superior_temporal_gyrus_r", "superior_temporal_gyrus_l",
            "corpus_callosum",
        ],
        "cerebellum": [
            "cerebellum_superior_lobule_r", "cerebellum_superior_lobule_l",
            "cerebellum_inferior_lobule_r", "cerebellum_inferior_lobule_l",
        ],
        "brainstem": [
            "midbrain_r", "midbrain_l",
            "pons_r", "pons_l",
            "medulla_oblongata_r", "medulla_oblongata_l",
        ],
        "ventricles": ["lateral_ventricle_r", "lateral_ventricle_l"],
        "thalamus": ["thalamus_r", "thalamus_l", "hypothalamus"],
        "corpus callosum": ["corpus_callosum"],
        "hippocampus": ["hippocampus_r", "hippocampus_l"],
        "caudate nucleus": ["caudate_nucleus_r", "caudate_nucleus_l"],
        "lentiform nucleus": ["putamen_r", "putamen_l", "caudate_nucleus_r", "caudate_nucleus_l"],
        "internal capsule": ["thalamus_r", "thalamus_l", "putamen_r", "putamen_l", "caudate_nucleus_r", "caudate_nucleus_l"],
        "fornix": ["corpus_callosum", "hippocampus_r", "hippocampus_l", "thalamus_r", "thalamus_l"],
        "optic nerve": ["frontal_bone", "sphenoid_bone", "zygomatic_bone_r", "zygomatic_bone_l", "thalamus_r", "thalamus_l"],
        "eye": ["frontal_bone", "sphenoid_bone", "zygomatic_bone_r", "zygomatic_bone_l"],
        "skull": _by_group("skull_bone"),
        "cranium": _by_group("skull_bone"),
        "parietal bone": ["parietal_bone_r", "parietal_bone_l"],
        "temporal bone": ["temporal_bone_r", "temporal_bone_l"],
        "zygomatic bone": ["zygomatic_bone_r", "zygomatic_bone_l"],
        "maxilla": ["maxilla_r", "maxilla_l"],
        "mandible": ["mandible"],
        "sternocleidomastoid": ["sternocleidomastoid_r", "sternocleidomastoid_l"],
        "scalenes": [
            "scalenus_anterior_r", "scalenus_medius_r", "scalenus_posterior_r",
            "scalenus_anterior_l", "scalenus_medius_l", "scalenus_posterior_l",
        ],
        "masseter": ["masseter_r", "masseter_l"],
        "temporalis": ["temporalis_r", "temporalis_l"],
        "carotid artery": [
            "common_carotid_artery_r", "common_carotid_artery_l",
            "internal_carotid_artery_r", "internal_carotid_artery_l",
            "external_carotid_artery_r", "external_carotid_artery_l",
        ],
        "jugular vein": [
            "internal_jugular_vein_r", "internal_jugular_vein_l",
            "external_jugular_vein_r", "external_jugular_vein_l",
        ],
        "thyroid": ["thyroid_cartilage", "cricoid_cartilage", "hyoid_bone", "trachea"],
        "larynx": ["thyroid_cartilage", "cricoid_cartilage", "epiglottis", "hyoid_bone"],
        "pharynx": ["thyroid_cartilage", "cricoid_cartilage", "epiglottis", "esophagus"],
        "trachea": ["trachea"],
        "esophagus": ["esophagus"],
        # Thorax & Cardiopulmonary
        "heart": [
            "heart_left_ventricle",
            "heart_right_ventricle",
            "heart_left_atrium",
            "heart_right_atrium",
        ],
        "lungs": [
            "right_lung_superior_lobe",
            "right_lung_middle_lobe",
            "right_lung_inferior_lobe",
            "left_lung_superior_lobe",
            "left_lung_inferior_lobe",
        ],
        "right lung": [
            "right_lung_superior_lobe",
            "right_lung_middle_lobe",
            "right_lung_inferior_lobe",
        ],
        "left lung": [
            "left_lung_superior_lobe",
            "left_lung_inferior_lobe",
        ],
        "bronchi": [
            "trachea",
            "right_lung_superior_lobe",
            "right_lung_middle_lobe",
            "right_lung_inferior_lobe",
            "left_lung_superior_lobe",
            "left_lung_inferior_lobe",
        ],
        "aorta": ["ascending_aorta", "thoracic_aorta", "abdominal_aorta"],
        "aortic_arch": ["ascending_aorta", "thoracic_aorta"],
        "pulmonary artery": ["pulmonary_trunk"],
        "vena cava": ["superior_vena_cava", "inferior_vena_cava"],
        "diaphragm": ["diaphragm"],
        "ribs": [s["id"] for s in all_structs if s.get("group") == "thorax_bone" and s["id"].startswith("rib_")],
        "ribcage": _by_group("thorax_bone"),
        "sternum": ["sternum_manubrium", "sternum_body"],
        "pectoralis major": [
            "pectoralis_major_clavicular_r", "pectoralis_major_sternocostal_r", "pectoralis_major_abdominal_r",
            "pectoralis_major_clavicular_l", "pectoralis_major_sternocostal_l", "pectoralis_major_abdominal_l",
        ],
        "pectoralis minor": ["pectoralis_minor_r", "pectoralis_minor_l"],
        "intercostal": [
            "external_intercostal_r", "internal_intercostal_r",
            "external_intercostal_l", "internal_intercostal_l",
        ],
        "serratus anterior": ["serratus_anterior_r", "serratus_anterior_l"],
        # Abdomen & Visceral Organs
        "liver": ["liver"],
        "gallbladder": ["gallbladder"],
        "stomach": ["stomach"],
        "spleen": ["spleen"],
        "pancreas": ["pancreas"],
        "kidneys": [
            "abdominal_aorta",
            "inferior_vena_cava",
            "urinary_bladder",
            "psoas_major_r",
            "psoas_major_l",
        ],
        "small intestine": ["duodenum", "jejunum_ileum"],
        "large intestine": [
            "appendix", "ascending_colon", "transverse_colon",
            "descending_colon", "sigmoid_colon",
        ],
        "cecum": ["appendix", "ascending_colon"],
        "rectum": ["sigmoid_colon", "urinary_bladder"],
        "intestines": [
            "duodenum", "jejunum_ileum", "appendix",
            "ascending_colon", "transverse_colon", "descending_colon",
            "sigmoid_colon",
        ],
        "hepatic_portal_vein": ["inferior_vena_cava", "liver"],
        "celiac_trunk": ["abdominal_aorta", "stomach", "liver", "spleen"],
        "superior_mesenteric_artery": ["abdominal_aorta", "duodenum", "jejunum_ileum", "transverse_colon"],
        "inferior_mesenteric_artery": ["abdominal_aorta", "descending_colon", "sigmoid_colon"],
        "viscera": _by_group("digestive_viscera", "lungs_diaphragm", "heart_great_vessels", "head_neck_viscera"),
        # Spine, Pelvis & Core
        "cervical spine": [s["id"] for s in all_structs if s.get("group") == "spine_bone" and s["id"].startswith("vertebra_c")],
        "thoracic spine": [s["id"] for s in all_structs if s.get("group") == "spine_bone" and s["id"].startswith("vertebra_t")],
        "lumbar spine": [s["id"] for s in all_structs if s.get("group") == "spine_bone" and s["id"].startswith("vertebra_l")],
        "intervertebral discs": _by_group("spine_bone"),
        "spine": _by_group("spine_bone") + ["sacrum", "coccyx"],
        "sacrum": ["sacrum"],
        "coccyx": ["coccyx"],
        "pelvis": ["hip_bone_r", "hip_bone_l", "sacrum", "coccyx"],
        "rectus abdominis": ["rectus_abdominis_r", "rectus_abdominis_l"],
        "external oblique": ["external_oblique_r", "external_oblique_l"],
        "internal oblique": ["internal_oblique_r", "internal_oblique_l"],
        "transversus abdominis": ["transversus_abdominis_r", "transversus_abdominis_l"],
        "abdominal muscles": [
            "rectus_abdominis_r", "rectus_abdominis_l",
            "external_oblique_r", "external_oblique_l",
            "internal_oblique_r", "internal_oblique_l",
            "transversus_abdominis_r", "transversus_abdominis_l",
        ],
        "iliopsoas": ["psoas_major_r", "psoas_major_l", "iliacus_r", "iliacus_l"],
        "psoas major": ["psoas_major_r", "psoas_major_l"],
        "iliacus": ["iliacus_r", "iliacus_l"],
        "quadratus lumborum": ["quadratus_lumborum_r", "quadratus_lumborum_l"],
        "erector spinae": [
            "erector_spinae_iliocostalis_r", "erector_spinae_longissimus_r",
            "erector_spinae_iliocostalis_l", "erector_spinae_longissimus_l",
        ],
        "iliocostalis": ["erector_spinae_iliocostalis_r", "erector_spinae_iliocostalis_l"],
        "longissimus": ["erector_spinae_longissimus_r", "erector_spinae_longissimus_l"],
        "latissimus dorsi": ["latissimus_dorsi_r", "latissimus_dorsi_l"],
        "rhomboids": ["rhomboid_major_r", "rhomboid_minor_r", "rhomboid_major_l", "rhomboid_minor_l"],
        "levator scapulae": ["levator_scapulae_r", "levator_scapulae_l"],
        "trapezius": [
            "trapezius_descending_r", "trapezius_transverse_r", "trapezius_ascending_r",
            "trapezius_descending_l", "trapezius_transverse_l", "trapezius_ascending_l",
        ],
        "iliac artery": [
            "common_iliac_artery_r", "common_iliac_artery_l",
            "external_iliac_artery_r", "external_iliac_artery_l",
            "internal_iliac_artery_r", "internal_iliac_artery_l",
        ],
        "iliac vein": [
            "common_iliac_vein_r", "common_iliac_vein_l",
            "external_iliac_vein_r", "external_iliac_vein_l",
        ],
        # Upper Limb & Shoulder
        "rotator cuff": [
            "subscapularis_r", "supraspinatus_r", "infraspinatus_r", "teres_minor_r",
            "subscapularis_l", "supraspinatus_l", "infraspinatus_l", "teres_minor_l",
        ],
        "subscapularis": ["subscapularis_r", "subscapularis_l"],
        "supraspinatus": ["supraspinatus_r", "supraspinatus_l"],
        "infraspinatus": ["infraspinatus_r", "infraspinatus_l"],
        "teres minor": ["teres_minor_r", "teres_minor_l"],
        "teres major": ["teres_major_r", "teres_major_l"],
        "deltoid": [
            "deltoid_anterior_r", "deltoid_lateral_r", "deltoid_posterior_r",
            "deltoid_anterior_l", "deltoid_lateral_l", "deltoid_posterior_l",
        ],
        "anterior deltoid": ["deltoid_anterior_r", "deltoid_anterior_l"],
        "middle deltoid": ["deltoid_lateral_r", "deltoid_lateral_l"],
        "posterior deltoid": ["deltoid_posterior_r", "deltoid_posterior_l"],
        "biceps": [
            "biceps_long_head_r", "biceps_short_head_r",
            "biceps_long_head_l", "biceps_short_head_l",
        ],
        "triceps": [
            "triceps_long_head_r", "triceps_lateral_head_r", "triceps_medial_head_r",
            "triceps_long_head_l", "triceps_lateral_head_l", "triceps_medial_head_l",
        ],
        "brachialis": ["brachialis_r", "brachialis_l"],
        "coracobrachialis": ["coracobrachialis_r", "coracobrachialis_l"],
        "brachioradialis": ["brachioradialis_r", "brachioradialis_l"],
        "pronator teres": ["pronator_teres_r", "pronator_teres_l"],
        "forearm": _by_group("forearm_hand"),
        "scapula": ["scapula_r", "scapula_l"],
        "clavicle": ["clavicle_r", "clavicle_l"],
        "humerus": ["humerus_r", "humerus_l"],
        "radius": ["radius_r", "radius_l"],
        "ulna": ["ulna_r", "ulna_l"],
        "hand": [
            "flexor_digitorum_superficialis_r", "flexor_digitorum_superficialis_l",
            "extensor_digitorum_r", "extensor_digitorum_l",
            "flexor_carpi_radialis_r", "flexor_carpi_radialis_l",
            "extensor_carpi_radialis_longus_r", "extensor_carpi_radialis_longus_l",
            "radius_r", "radius_l", "ulna_r", "ulna_l",
        ],
        "glenohumeral capsule": ["glenohumeral_capsule_r", "glenohumeral_capsule_l"],
        "coracoacromial ligament": [
            "glenohumeral_capsule_r", "glenohumeral_capsule_l",
            "subacromial_bursa_r", "subacromial_bursa_l",
        ],
        "subacromial bursa": ["subacromial_bursa_r", "subacromial_bursa_l"],
        "brachial plexus": [
            "axillary_nerve_r", "axillary_nerve_l",
            "superior_subscapular_nerve_r", "superior_subscapular_nerve_l",
            "inferior_subscapular_nerve_r", "inferior_subscapular_nerve_l",
            "median_nerve_r", "median_nerve_l",
            "radial_nerve_r", "radial_nerve_l",
            "ulnar_nerve_r", "ulnar_nerve_l",
        ],
        "axillary nerve": ["axillary_nerve_r", "axillary_nerve_l"],
        "suprascapular nerve": [
            "superior_subscapular_nerve_r", "superior_subscapular_nerve_l",
            "inferior_subscapular_nerve_r", "inferior_subscapular_nerve_l",
        ],
        "median nerve": ["median_nerve_r", "median_nerve_l"],
        "ulnar nerve": ["ulnar_nerve_r", "ulnar_nerve_l"],
        "radial nerve": ["radial_nerve_r", "radial_nerve_l"],
        "musculocutaneous nerve": [
            "median_nerve_r", "median_nerve_l",
            "axillary_nerve_r", "axillary_nerve_l",
        ],
        "axillary artery": ["axillary_artery_r", "axillary_artery_l"],
        "brachial artery": ["brachial_artery_r", "brachial_artery_l"],
        "subclavian artery": ["axillary_artery_r", "axillary_artery_l", "common_carotid_artery_r", "common_carotid_artery_l"],
        "subclavian vein": ["axillary_artery_r", "axillary_artery_l", "internal_jugular_vein_r", "internal_jugular_vein_l"],
        "cephalic vein": ["brachial_artery_r", "brachial_artery_l", "axillary_artery_r", "axillary_artery_l"],
        "basilic vein": ["brachial_artery_r", "brachial_artery_l", "axillary_artery_r", "axillary_artery_l"],
        # Lower Limb
        "gluteus maximus": ["gluteus_maximus_r", "gluteus_maximus_l"],
        "gluteus medius": ["gluteus_medius_r", "gluteus_medius_l"],
        "gluteus minimus": ["gluteus_minimus_r", "gluteus_minimus_l"],
        "glutes": [
            "gluteus_maximus_r", "gluteus_medius_r", "gluteus_minimus_r",
            "gluteus_maximus_l", "gluteus_medius_l", "gluteus_minimus_l",
        ],
        "piriformis": ["piriformis_r", "piriformis_l"],
        "tensor fasciae latae": ["tensor_fasciae_latae_r", "tensor_fasciae_latae_l"],
        "quadriceps": [
            "rectus_femoris_r", "vastus_lateralis_r", "vastus_medialis_r", "vastus_intermedius_r",
            "rectus_femoris_l", "vastus_lateralis_l", "vastus_medialis_l", "vastus_intermedius_l",
        ],
        "rectus femoris": ["rectus_femoris_r", "rectus_femoris_l"],
        "vastus lateralis": ["vastus_lateralis_r", "vastus_lateralis_l"],
        "vastus medialis": ["vastus_medialis_r", "vastus_medialis_l"],
        "vastus intermedius": ["vastus_intermedius_r", "vastus_intermedius_l"],
        "sartorius": ["sartorius_r", "sartorius_l"],
        "hamstrings": [
            "biceps_femoris_long_head_r", "biceps_femoris_short_head_r", "semitendinosus_r", "semimembranosus_r",
            "biceps_femoris_long_head_l", "biceps_femoris_short_head_l", "semitendinosus_l", "semimembranosus_l",
        ],
        "biceps femoris": [
            "biceps_femoris_long_head_r", "biceps_femoris_short_head_r",
            "biceps_femoris_long_head_l", "biceps_femoris_short_head_l",
        ],
        "semitendinosus": ["semitendinosus_r", "semitendinosus_l"],
        "semimembranosus": ["semimembranosus_r", "semimembranosus_l"],
        "adductor magnus": ["adductor_magnus_r", "adductor_magnus_l"],
        "adductor longus": ["adductor_longus_r", "adductor_longus_l"],
        "adductor brevis": ["adductor_brevis_r", "adductor_brevis_l"],
        "adductors": [
            "adductor_magnus_r", "adductor_longus_r", "adductor_brevis_r", "gracilis_r", "pectineus_r",
            "adductor_magnus_l", "adductor_longus_l", "adductor_brevis_l", "gracilis_l", "pectineus_l",
        ],
        "gracilis": ["gracilis_r", "gracilis_l"],
        "pectineus": ["pectineus_r", "pectineus_l"],
        "gastrocnemius": [
            "gastrocnemius_medial_head_r", "gastrocnemius_lateral_head_r",
            "gastrocnemius_medial_head_l", "gastrocnemius_lateral_head_l",
        ],
        "soleus": ["soleus_r", "soleus_l"],
        "calf": [
            "gastrocnemius_medial_head_r", "gastrocnemius_lateral_head_r", "soleus_r",
            "gastrocnemius_medial_head_l", "gastrocnemius_lateral_head_l", "soleus_l",
        ],
        "tibialis anterior": ["tibialis_anterior_r", "tibialis_anterior_l"],
        "tibialis posterior": ["tibialis_posterior_r", "tibialis_posterior_l"],
        "fibularis": [
            "fibularis_longus_r", "fibularis_brevis_r",
            "fibularis_longus_l", "fibularis_brevis_l",
        ],
        "femur": ["femur_r", "femur_l"],
        "patella": ["patella_r", "patella_l"],
        "tibia": ["tibia_r", "tibia_l"],
        "fibula": ["fibula_r", "fibula_l"],
        "talus": ["talus_r", "talus_l"],
        "calcaneus": ["calcaneus_r", "calcaneus_l"],
        "foot": [
            "talus_r", "calcaneus_r", "tarsals_r", "metatarsals_r", "foot_phalanges_r",
            "talus_l", "calcaneus_l", "tarsals_l", "metatarsals_l", "foot_phalanges_l",
        ],
        "sciatic nerve": ["sciatic_nerve_r", "sciatic_nerve_l"],
        "femoral nerve": ["femoral_nerve_r", "femoral_nerve_l"],
        "tibial nerve": ["tibial_nerve_r", "tibial_nerve_l"],
        "common fibular nerve": ["common_fibular_nerve_r", "common_fibular_nerve_l"],
        "obturator nerve": ["femoral_nerve_r", "femoral_nerve_l", "sciatic_nerve_r", "sciatic_nerve_l"],
        "femoral artery": ["femoral_artery_r", "femoral_artery_l"],
        "femoral vein": ["femoral_artery_r", "femoral_artery_l", "great_saphenous_vein_r", "great_saphenous_vein_l"],
        "popliteal artery": ["femoral_artery_r", "femoral_artery_l", "tibial_nerve_r", "tibial_nerve_l"],
        "great saphenous vein": ["great_saphenous_vein_r", "great_saphenous_vein_l"],
    }

    if clean in curated_map:
        valid_ids = [sid for sid in curated_map[clean] if sid in SCENE_SERVICE.structures_by_id]
        if valid_ids:
            return _filter_ids_by_side(valid_ids, effective_side)

    # 3. Check if `clean` matches any trigger in ANATOMY_KEYWORDS_ORDERED
    for kw, canonical, _label in ANATOMY_KEYWORDS_ORDERED:
        if clean == kw and canonical in curated_map:
            valid_ids = [sid for sid in curated_map[canonical] if sid in SCENE_SERVICE.structures_by_id]
            if valid_ids:
                return _filter_ids_by_side(valid_ids, effective_side)

    # 4. Delegate to SCENE_SERVICE.expand_term_to_structure_ids
    expanded = SCENE_SERVICE.expand_term_to_structure_ids(raw)
    if expanded:
        return _filter_ids_by_side(expanded, effective_side)

    expanded_clean = SCENE_SERVICE.expand_term_to_structure_ids(clean)
    if expanded_clean:
        return _filter_ids_by_side(expanded_clean, effective_side)

    # 5. Dynamic fallback: SCENE_SERVICE.search_structures
    search_res = SCENE_SERVICE.search_structures(query=clean, side=effective_side, limit=12)
    matches = search_res.get("results", [])
    if matches:
        top_score = matches[0].get("score", 0)
        threshold = max(45, int(top_score * 0.75))
        return [m["id"] for m in matches if m.get("score", 0) >= threshold]

    return []


# Stop words to ignore during dynamic n-gram manifest lookup
_DYNAMIC_STOP_WORDS: Set[str] = {
    "show", "highlight", "isolate", "only", "fade", "faded", "transparent", "translucent",
    "ghost", "dim", "hide", "remove", "restore", "opaque", "reset", "undo", "view", "camera",
    "focus", "on", "the", "a", "an", "and", "or", "with", "without", "in", "of", "to", "for",
    "from", "make", "set", "keep", "please", "me", "all", "both", "right", "left", "side",
    "anterior", "posterior", "lateral", "medial", "superior", "inferior", "front", "back",
    "보여줘", "보여", "강조해줘", "강조", "표시해줘", "표시", "단독", "반투명하게", "반투명",
    "투명하게", "투명", "흐리게", "숨겨줘", "숨겨", "제거해줘", "제거", "꺼줘", "복원", "불투명",
    "초기화", "되돌리기", "원래대로", "그리고", "하고", "및", "오른쪽", "우측", "왼쪽", "좌측",
}


def _extract_dynamic_manifest_terms(clause: str, explicit_side: Optional[str] = None) -> List[str]:
    """
    Dynamically searches `structures-manifest.json` for any anatomical structure or group
    mentioned in `clause` when no static keyword matched.
    """
    # Strip punctuation and tokenize
    cleaned = re.sub(r"[^0-9a-zA-Z가-힣_\-\s]", " ", clause.lower())
    # Strip common Korean particles at end of words
    tokens: List[str] = []
    for raw_tok in cleaned.split():
        tok = re.sub(r"(만|을|를|이|가|은|는|과|와|도|에서|으로|로)$", "", raw_tok).strip()
        if len(tok) >= 2 and tok not in _DYNAMIC_STOP_WORDS:
            tokens.append(tok)

    if not tokens:
        return []

    found_terms: List[str] = []
    used_indices: Set[int] = set()

    # Check 3-grams, 2-grams, then 1-grams
    for n in (3, 2, 1):
        for i in range(len(tokens) - n + 1):
            if any((i + offset) in used_indices for offset in range(n)):
                continue
            candidate = " ".join(tokens[i : i + n])
            ids = _expand_anatomy_term(candidate, explicit_side)
            if ids:
                found_terms.append(candidate)
                for offset in range(n):
                    used_indices.add(i + offset)

    return found_terms


def _detect_explicit_side(text_lower: str) -> Optional[str]:
    """
    Returns 'right' or 'left' ONLY if the user explicitly specified a side
    (excluding intrinsic organ chamber/lobe names unless paired with another side marker).
    """
    scrubbed = (
        text_lower.replace("right ventricle", "")
        .replace("left ventricle", "")
        .replace("right atrium", "")
        .replace("left atrium", "")
        .replace("right lung", "")
        .replace("left lung", "")
        .replace("우심실", "")
        .replace("좌심실", "")
        .replace("우심방", "")
        .replace("좌심방", "")
        .replace("우폐", "")
        .replace("좌폐", "")
        .replace("오른폐", "")
        .replace("왼폐", "")
    )
    has_left = any(w in scrubbed for w in ["왼쪽", "좌측", "왼팔", "왼다리", "left"])
    has_right = any(w in scrubbed for w in ["오른쪽", "우측", "오른팔", "오른다리", "right"])
    if has_left and not has_right:
        return "left"
    if has_right and not has_left:
        return "right"
    return None


def _get_auto_faded_overlying_terms(
    highlight_terms: List[str],
    existing_faded_or_hidden_ids: Set[str],
    highlighted_ids: Set[str],
    explicit_side: Optional[str],
) -> List[Dict[str, Any]]:
    """
    Automatically determines superficial overlying structures to fade (opacity ~0.16)
    when deep internal organs (brain, heart, lungs, liver, stomach, kidneys, spleen,
    pancreas, intestines) or deep nerves/muscles (sciatic nerve, piriformis, subscapularis)
    are highlighted or focused, excluding any structure that is itself highlighted.
    """
    h_low_set = {t.lower() for t in highlight_terms}
    auto_fade_terms: List[Tuple[str, float]] = []

    # 1. Brain / Deep intracranial structures -> fade skull bones
    brain_triggers = {
        "brain", "cerebrum", "cerebellum", "brainstem", "ventricles",
        "thalamus", "corpus callosum", "hippocampus", "caudate nucleus",
        "lentiform nucleus", "internal capsule", "fornix",
    }
    if h_low_set & brain_triggers:
        auto_fade_terms.append(("skull", 0.16))

    # 2. Thoracic organs (heart, lungs, bronchi, great vessels) -> fade anterior chest wall & ribcage
    thorax_triggers = {
        "heart", "heart_left_ventricle", "heart_right_ventricle", "heart_left_atrium", "heart_right_atrium",
        "lungs", "right lung", "left lung", "bronchi", "aorta", "ascending_aorta", "aortic_arch",
        "thoracic_aorta", "pulmonary artery", "pulmonary_trunk", "vena cava", "superior_vena_cava",
        "trachea", "esophagus",
    }
    if h_low_set & thorax_triggers:
        auto_fade_terms.extend([
            ("pectoralis major", 0.14),
            ("pectoralis minor", 0.14),
            ("intercostal", 0.14),
            ("sternum", 0.16),
            ("ribs", 0.18),
        ])

    # 3. Abdominal visceral organs -> fade anterior abdominal wall, diaphragm, and lower ribs
    abdomen_triggers = {
        "liver", "gallbladder", "stomach", "spleen", "pancreas", "kidneys",
        "small intestine", "duodenum", "jejunum_ileum", "large intestine",
        "ascending_colon", "transverse_colon", "descending_colon", "sigmoid_colon",
        "cecum", "appendix", "rectum", "intestines", "viscera", "urinary_bladder",
        "hepatic_portal_vein", "celiac_trunk", "superior_mesenteric_artery", "abdominal_aorta",
    }
    if h_low_set & abdomen_triggers:
        auto_fade_terms.extend([
            ("abdominal muscles", 0.14),
            ("pectoralis major", 0.15),
            ("ribs", 0.18),
        ])

    # 4. Deep posterior hip (sciatic nerve, piriformis) -> fade gluteus maximus unless gluteus maximus is highlighted
    if h_low_set & {"sciatic nerve", "piriformis"}:
        if "gluteus maximus" not in h_low_set and "glutes" not in h_low_set:
            auto_fade_terms.append(("gluteus maximus", 0.18))

    # 5. Deep anterior shoulder (subscapularis) -> fade pectoralis major, pectoralis minor, deltoid
    if "subscapularis" in h_low_set:
        for sup_term in ("pectoralis major", "pectoralis minor", "deltoid", "trapezius"):
            if sup_term not in h_low_set:
                auto_fade_terms.append((sup_term, 0.18))

    result: List[Dict[str, Any]] = []
    seen_terms: Set[str] = set()
    for term_name, op_val in auto_fade_terms:
        if term_name in seen_terms:
            continue
        candidate_ids = set(_expand_anatomy_term(term_name, explicit_side))
        # Only add if at least one structure in candidate_ids is not already highlighted or faded/hidden
        unhandled_ids = candidate_ids - highlighted_ids - existing_faded_or_hidden_ids
        if unhandled_ids:
            seen_terms.add(term_name)
            result.append({"term": term_name, "opacity": op_val})
            existing_faded_or_hidden_ids.update(unhandled_ids)

    return result


def _build_bilingual_explanation(
    command_text: str,
    action_type: str,
    isolate_mode: bool,
    highlight_terms: List[str],
    semi_transparent_items: List[Dict[str, Any]],
    hidden_terms: List[str],
    opaque_terms: List[str],
    camera_preset: str,
) -> Dict[str, str]:
    """
    Builds clean, natural English and Korean titles, spoken confirmations, and anatomical
    explanations without raw [SOT-xx] tags.
    """
    if action_type == "undo":
        return {
            "titleEn": "Undo 3D Scene Change",
            "spokenFeedbackEn": "Restored the 3D anatomy viewer to the previous state.",
            "bodyEn": "Reverted the most recent visibility, opacity, and camera changes in the 3D anatomical scene.",
            "titleKo": "이전 3D 해부학 상태 복원",
            "spokenFeedbackKo": "직전 3D 해부학 뷰어 상태로 되돌렸습니다.",
            "clinicalExplanationKo": "최근 적용된 해부학 구조물 투명도, 강조 표시 및 카메라 시점 변경을 이전 단계로 복원했습니다.",
        }

    if action_type == "reset":
        return {
            "titleEn": "Reset Whole-Body 3D Anatomy View",
            "spokenFeedbackEn": "Reset all anatomical structures and returned the camera to the default whole-body front view.",
            "bodyEn": "All 385 anatomical structures across the whole-body Z-Anatomy model have been restored to default visibility and opacity.",
            "titleKo": "전신 3D 해부학 뷰 초기화",
            "spokenFeedbackKo": "모든 3D 해부학 구조물의 투명도와 강조 상태를 초기화하고 전신 정면 시점으로 복원했습니다.",
            "clinicalExplanationKo": "전신 Z-Anatomy 3D 모델의 모든 근육, 골격, 신경, 혈관 및 내장 기관을 기본 가시성과 투명도로 복원했습니다.",
        }

    def _readable_en(term: str) -> str:
        lbl = CANONICAL_LABEL_MAP.get(term, term)
        return re.sub(r"\s*\([^)]*\)", "", lbl).strip() or term

    def _readable_ko(term: str) -> str:
        lbl = CANONICAL_LABEL_MAP.get(term, "")
        m = re.search(r"\(([^)]+)\)", lbl)
        if m:
            return m.group(1).strip()
        return term

    high_en = [_readable_en(t) for t in highlight_terms]
    high_ko = [_readable_ko(t) for t in highlight_terms]
    fade_en = [_readable_en(it["term"]) for it in semi_transparent_items]
    fade_ko = [_readable_ko(it["term"]) for it in semi_transparent_items]
    hide_en = [_readable_en(t) for t in hidden_terms]
    hide_ko = [_readable_ko(t) for t in hidden_terms]
    opaq_en = [_readable_en(t) for t in opaque_terms]
    opaq_ko = [_readable_ko(t) for t in opaque_terms]

    if isolate_mode and high_en:
        target_str_en = ", ".join(high_en[:4])
        target_str_ko = ", ".join(high_ko[:4])
        title_en = f"Isolated View: {target_str_en}"
        title_ko = f"단독 분리 시각화: {target_str_ko}"
        spoken_en = f"Isolated {target_str_en} and faded surrounding anatomical layers, framing the 3D camera on the target region."
        spoken_ko = f"{target_str_ko} 구조물을 단독 강조하고 주변 해부학 층을 반투명 처리하여 해당 부위로 3D 카메라를 이동했습니다."
        body_en = (
            f"Isolating {target_str_en} while rendering surrounding skeletal and muscular layers translucent "
            "provides an unobstructed 3D view of its spatial position, boundaries, and anatomical relationships."
        )
        body_ko = (
            f"주변 근육과 골격 층을 반투명하게 전환하고 {target_str_ko} 구조물을 단독으로 강조하여 "
            "심부 해부학적 위치와 인접 장기·혈관·신경 간의 3차원 공간 관계를 명확히 확인할 수 있습니다."
        )
        return {
            "titleEn": title_en,
            "spokenFeedbackEn": spoken_en,
            "bodyEn": body_en,
            "titleKo": title_ko,
            "spokenFeedbackKo": spoken_ko,
            "clinicalExplanationKo": body_ko,
        }

    if high_en:
        target_str_en = ", ".join(high_en[:4])
        target_str_ko = ", ".join(high_ko[:4])
        title_en = f"3D Anatomy Focus: {target_str_en}"
        title_ko = f"3D 해부학 집중 조명: {target_str_ko}"

        fade_clause_en = f" with {', '.join(fade_en[:3])} rendered translucent" if fade_en else ""
        fade_clause_ko = f" ({', '.join(fade_ko[:3])} 반투명 처리)" if fade_ko else ""
        hide_clause_en = f" and {', '.join(hide_en[:3])} hidden" if hide_en else ""
        hide_clause_ko = f" ({', '.join(hide_ko[:3])} 숨김)" if hide_ko else ""

        spoken_en = (
            f"Highlighted {target_str_en}{fade_clause_en}{hide_clause_en} and automatically framed the 3D camera."
        )
        spoken_ko = (
            f"{target_str_ko} 구조물을 강조 표시하고{fade_clause_ko}{hide_clause_ko} 해당 해부학 영역으로 3D 카메라 시점을 자동 조정했습니다."
        )
        body_en = (
            f"Visualizing {target_str_en} in the 3D whole-body model{fade_clause_en}. "
            "The camera is centered on the target bounding box to clearly inspect anatomical landmarks and adjacent layers."
        )
        body_ko = (
            f"전신 3D 해부학 모델에서 {target_str_ko} 영역을 중심으로 시점을 맞추고 입체적 해부학 구조를 표시했습니다. "
            "인접한 골격, 근육, 신경 및 장기와의 해부학적 층위 관계를 직관적으로 비교할 수 있습니다."
        )
        return {
            "titleEn": title_en,
            "spokenFeedbackEn": spoken_en,
            "bodyEn": body_en,
            "titleKo": title_ko,
            "spokenFeedbackKo": spoken_ko,
            "clinicalExplanationKo": body_ko,
        }

    # Layer-only or camera-only updates
    action_parts_en: List[str] = []
    action_parts_ko: List[str] = []
    if fade_en:
        action_parts_en.append(f"faded {', '.join(fade_en[:3])}")
        action_parts_ko.append(f"{', '.join(fade_ko[:3])} 반투명 처리")
    if hide_en:
        action_parts_en.append(f"hid {', '.join(hide_en[:3])}")
        action_parts_ko.append(f"{', '.join(hide_ko[:3])} 숨김")
    if opaq_en:
        action_parts_en.append(f"restored {', '.join(opaq_en[:3])}")
        action_parts_ko.append(f"{', '.join(opaq_ko[:3])} 불투명 복원")
    if camera_preset not in ("keep_current", "auto_frame"):
        action_parts_en.append(f"switched camera to {camera_preset}")
        action_parts_ko.append(f"카메라 시점({camera_preset}) 전환")

    summary_en = ", ".join(action_parts_en) if action_parts_en else f"applied command '{command_text}'"
    summary_ko = ", ".join(action_parts_ko) if action_parts_ko else f"'{command_text}' 명령 반영"

    return {
        "titleEn": f"3D Scene Update: {command_text}",
        "spokenFeedbackEn": f"Updated the 3D anatomy viewer: {summary_en}.",
        "bodyEn": f"Adjusted layer visibility and camera framing ({summary_en}) to reveal the underlying anatomical structures.",
        "titleKo": f"3D 해부학 뷰 업데이트: {command_text}",
        "spokenFeedbackKo": f"3D 해부학 뷰어에 {summary_ko} 설정을 적용했습니다.",
        "clinicalExplanationKo": f"요청하신 명령에 따라 {summary_ko} 처리를 완료하여 해부학적 층위 구조를 명확히 표시했습니다.",
    }


def resolve_deterministic_clinical_plan(
    command_text: str,
    current_state_summary: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Deterministic bilingual (English + Korean) whole-body anatomical command parser.
    Supports all 385 structures in `structures-manifest.json`, multi-clause commands
    (e.g., 'Highlight brain and fade skull'), smart layer fading, and automatic 3D camera framing.
    """
    text = (command_text or "").strip()
    lower = text.lower()
    explicit_side = _detect_explicit_side(lower)

    # 1. Undo command
    if re.search(r"\b(undo|revert)\b", lower) or any(
        w in lower for w in ["되돌리", "되돌려", "이전 상태", "이전으로", "방금 전", "취소해"]
    ):
        bilingual = _build_bilingual_explanation(
            command_text=text,
            action_type="undo",
            isolate_mode=False,
            highlight_terms=[],
            semi_transparent_items=[],
            hidden_terms=[],
            opaque_terms=[],
            camera_preset="keep_current",
        )
        return {
            "actionType": "undo",
            "preserveCamera": False,
            "cameraPreset": "keep_current",
            "isolateMode": False,
            "highlightTerms": [],
            "semiTransparentItems": [],
            "hiddenTerms": [],
            "opaqueTerms": [],
            "matchedDeterministic": True,
            **bilingual,
            "sotCitations": [],
        }

    # 2. Full Reset command (when no specific structure is being restored)
    is_reset_word = bool(re.search(r"\b(reset|clear all|default view)\b", lower)) or any(
        w in lower for w in ["초기화", "리셋", "전체 복원", "모두 보이게", "다 보이게", "처음으로", "원래대로"]
    )
    has_specific_structure_in_reset = any(kw in lower for kw, _, _ in ANATOMY_KEYWORDS_ORDERED[:120])
    if is_reset_word and not has_specific_structure_in_reset:
        bilingual = _build_bilingual_explanation(
            command_text=text,
            action_type="reset",
            isolate_mode=False,
            highlight_terms=[],
            semi_transparent_items=[],
            hidden_terms=[],
            opaque_terms=[],
            camera_preset="whole_body_front",
        )
        return {
            "actionType": "reset",
            "preserveCamera": False,
            "cameraPreset": "whole_body_front",
            "isolateMode": False,
            "highlightTerms": [],
            "semiTransparentItems": [],
            "hiddenTerms": [],
            "opaqueTerms": [],
            "matchedDeterministic": True,
            **bilingual,
            "sotCitations": [],
        }

    # 3. Procedure template loading
    if any(w in lower for w in ["시술 템플릿", "가이드 템플릿", "액와 안전", "액와 접근", "시술 경로", "천종혈", "si11", "소결절 건 부착부 시술", "procedure template"]):
        tpl_side = explicit_side or "right"
        if any(w in lower for w in ["천종", "si11", "후면 회전근개 시술", "극하근 시술"]):
            tpl_id = "proc_posterior_sits_si11_r"
        elif any(w in lower for w in ["소결절", "건 부착부", "전방 삼각흉근"]):
            tpl_id = "proc_subscap_lesser_tubercle_r"
        elif tpl_side == "left":
            tpl_id = "proc_subscap_axillary_l"
        else:
            tpl_id = "proc_subscap_axillary_r"
        return {
            "actionType": "load_template",
            "preserveCamera": False,
            "cameraPreset": "right_anterolateral" if tpl_side == "right" else "left_anterolateral",
            "isolateMode": False,
            "templateId": tpl_id,
            "stepIndex": 0,
            "highlightTerms": ["subscapularis_r" if tpl_side == "right" else "subscapularis_l"],
            "semiTransparentItems": [],
            "hiddenTerms": [],
            "opaqueTerms": [],
            "matchedDeterministic": True,
            "titleEn": "3D Clinical Procedure Template Loaded",
            "spokenFeedbackEn": "Loaded the 3D clinical procedure template and aligned the camera to the target pathway.",
            "bodyEn": "Displaying the step-by-step anatomical approach, target insertion zone, and adjacent neurovascular landmarks.",
            "titleKo": "3D 시술 가이드 템플릿 로드",
            "spokenFeedbackKo": "선택하신 3D 해부학 시술 가이드 템플릿(1단계)을 로드하고 시점을 정렬했습니다.",
            "clinicalExplanationKo": "표층 근육을 반투명화하여 심부 타겟 근육과 주변 혈관·신경 안전 지표를 단계별로 안내합니다.",
            "sotCitations": [],
        }

    # 4. Procedure step progression
    if any(w in lower for w in ["다음 단계", "2단계", "3단계", "4단계", "1단계", "첫 단계", "마지막 단계", "next step", "previous step", "step 1", "step 2", "step 3", "step 4"]):
        step_idx = 1
        if any(w in lower for w in ["1단계", "첫 단계", "step 1"]):
            step_idx = 0
        elif any(w in lower for w in ["2단계", "step 2"]):
            step_idx = 1
        elif any(w in lower for w in ["3단계", "step 3"]):
            step_idx = 2
        elif any(w in lower for w in ["4단계", "마지막 단계", "step 4"]):
            step_idx = 3
        elif current_state_summary and current_state_summary.get("activeProcedure"):
            cur_step = int(current_state_summary["activeProcedure"].get("stepIndex", 0))
            step_idx = min(3, cur_step + 1)
        return {
            "actionType": "set_progress",
            "preserveCamera": True,
            "cameraPreset": "keep_current",
            "isolateMode": False,
            "stepIndex": step_idx,
            "highlightTerms": [],
            "semiTransparentItems": [],
            "hiddenTerms": [],
            "opaqueTerms": [],
            "matchedDeterministic": True,
            "titleEn": f"Procedure Step {step_idx + 1}",
            "spokenFeedbackEn": f"Advanced the 3D procedure guide to Step {step_idx + 1}.",
            "bodyEn": f"Updated anatomical landmarks and trajectory indicators for Step {step_idx + 1}.",
            "titleKo": f"시술 가이드 {step_idx + 1}단계 이동",
            "spokenFeedbackKo": f"시술 가이드 {step_idx + 1}단계로 이동하여 해부학 지표를 업데이트했습니다.",
            "clinicalExplanationKo": "단계별 골성 지표와 신경·혈관 안전 경로를 확인하며 시술 부위를 입체적으로 검토합니다.",
            "sotCitations": [],
        }

    # 5. Detect explicit camera preset / orientation requests
    explicit_keep_camera = any(
        w in lower for w in ["시점 유지", "카메라 유지", "현재 시점", "시점 고정", "keep camera", "preserve camera"]
    )
    requested_camera_preset: Optional[str] = None
    prefer_posterior: Optional[bool] = None

    if not explicit_keep_camera:
        if any(w in lower for w in ["전신 정면", "전신 앞", "whole body front", "full body front", "whole body"]):
            requested_camera_preset = "whole_body_front"
        elif any(w in lower for w in ["전신 후면", "전신 뒤", "whole body back", "full body back"]):
            requested_camera_preset = "whole_body_back"
            prefer_posterior = True
        elif any(w in lower for w in ["머리 목 뷰", "두경부 뷰", "head and neck view", "head neck view"]):
            requested_camera_preset = "head_neck"
        elif any(w in lower for w in ["흉부 장기 뷰", "가슴 장기 뷰", "thorax view", "thoracic organs view"]):
            requested_camera_preset = "thorax_organs"
        elif any(w in lower for w in ["복부 장기 뷰", "복부 뷰", "abdomen view", "abdominal organs view"]):
            requested_camera_preset = "abdomen_organs"
        elif any(w in lower for w in ["척추 골반 뷰", "spine pelvis view"]):
            requested_camera_preset = "spine_pelvis"
        elif any(w in lower for w in ["하체 후면", "다리 뒤쪽 뷰", "lower limb back"]):
            requested_camera_preset = "lower_limb_back"
            prefer_posterior = True
        elif any(w in lower for w in ["하체 뷰", "하지 뷰", "다리 뷰", "lower limb view"]):
            requested_camera_preset = "lower_limb"
        elif any(w in lower for w in ["후면", "뒤쪽", "등쪽", "후방 시점", "뒤에서", "posterior view", "from behind", "back view"]):
            requested_camera_preset = "posterior"
            prefer_posterior = True
        elif any(w in lower for w in ["전면", "앞쪽", "정면", "앞에서", "anterior view", "front view"]):
            requested_camera_preset = "anterior"
            prefer_posterior = False
        elif any(w in lower for w in ["액와 뷰", "겨드랑이 시점", "axillary view"]):
            requested_camera_preset = "axillary"
        elif any(w in lower for w in ["상면", "위에서", "superior view", "top view"]):
            requested_camera_preset = "superior"
        elif any(w in lower for w in ["측면", "옆에서", "lateral view", "side view"]):
            requested_camera_preset = "lateral"

    # 6. Clause-by-clause parsing for multi-intent commands
    # Split on commas, semicolons, Korean connectors, and English "and/then/while/but" ONLY when followed by an action verb!
    clause_split_pattern = (
        r"(?:,|;|그리고|하고|한\s*뒤|한\s*다음|하면서|및\s+|"
        r"\b(?:and|then|while|but)\s+(?=(?:fade|faded|hide|remove|dim|ghost|transparent|translucent|"
        r"show|highlight|isolate|focus|expose|reveal|restore|opaque|make|set|keep|turn)\b))"
    )
    clauses = [c.strip() for c in re.split(clause_split_pattern, text, flags=re.IGNORECASE) if c.strip()]
    if not clauses:
        clauses = [text]

    HIDE_WORDS = [
        "숨겨", "숨기", "숨김", "꺼줘", "꺼", "제거", "안 보이게", "안보이게", "가려", "완전 투명", "0%",
        "hide", "hidden", "remove", "turn off", "invisible",
    ]
    SEMI_WORDS = [
        "반투명", "투명하게", "투명도", "연하게", "흐리게", "살짝 보이게", "비치게", "투명화", "투명",
        "fade", "faded", "transparent", "translucent", "ghost", "dim", "semi-transparent", "semitransparent", "opacity",
    ]
    OPAQUE_WORDS = [
        "불투명", "선명하게", "원래대로", "복원", "100%",
        "restore", "opaque", "solid", "unfade",
    ]
    ISOLATE_WORDS = [
        "단독", "만 보여", "만 표시", "만 강조", "만 하이라이트", "만 남기", "만 남겨", "제외하고",
        "isolate", "isolated", "only show", "show only", "just the",
    ]

    highlight_terms: List[str] = []
    semi_transparent_items: List[Dict[str, Any]] = []
    hidden_terms: List[str] = []
    opaque_terms: List[str] = []
    isolate_mode = any(w in lower for w in ISOLATE_WORDS)

    for clause in clauses:
        c_low = clause.lower()
        clause_side = _detect_explicit_side(c_low) or explicit_side

        # Determine intent for this clause first
        is_hide = any(w in c_low for w in HIDE_WORDS)
        is_opaque = (
            any(w in c_low for w in OPAQUE_WORDS)
            and not any(w in c_low for w in ["반투명", "semi-transparent", "semitransparent", "translucent", "fade"])
        )
        is_semi = not is_hide and not is_opaque and any(w in c_low for w in SEMI_WORDS)
        is_clause_isolate = any(w in c_low for w in ISOLATE_WORDS) or bool(re.search(r"\bonly\b", c_low))
        if is_clause_isolate:
            isolate_mode = True

        # Find all anatomy terms mentioned in this clause using longest-match span tracking
        matched_in_clause: List[str] = []
        occupied_spans: List[Tuple[int, int]] = []

        if any(w in c_low for w in ["표층 근육", "표층근", "겉 근육", "겉근육", "superficial muscles"]):
            for sup in ["trapezius", "deltoid", "pectoralis major", "pectoralis minor"]:
                q_term = f"{clause_side} {sup}" if clause_side else sup
                if q_term not in matched_in_clause:
                    matched_in_clause.append(q_term)

        for kw, canonical, _label in ANATOMY_KEYWORDS_ORDERED:
            # For ASCII keywords, enforce word boundaries so short tokens like 'rib' or 'abs' don't match inside words
            if re.match(r"^[a-z0-9\-\s]+$", kw):
                pattern = r"\b" + re.escape(kw) + r"\b"
            else:
                pattern = re.escape(kw)

            for m in re.finditer(pattern, c_low):
                span = (m.start(), m.end())
                if any(not (span[1] <= s[0] or span[0] >= s[1]) for s in occupied_spans):
                    continue
                occupied_spans.append(span)
                q_term = f"{clause_side} {canonical}" if clause_side else canonical
                if q_term not in matched_in_clause:
                    matched_in_clause.append(q_term)

        # Dynamic manifest fallback if no static keyword matched in this clause
        if not matched_in_clause:
            dyn_terms = _extract_dynamic_manifest_terms(clause, clause_side)
            for dt in dyn_terms:
                q_term = f"{clause_side} {dt}" if clause_side else dt
                if q_term not in matched_in_clause:
                    matched_in_clause.append(q_term)

        if not matched_in_clause:
            continue

        # Extract custom opacity if specified (e.g. "25%" or "0.25")
        custom_op = 0.18
        m_pct = re.search(r"(\d{1,2})\s*%", c_low)
        if m_pct:
            custom_op = max(0.05, min(0.90, int(m_pct.group(1)) / 100.0))
        else:
            m_dec = re.search(r"\b(0\.\d+)\b", c_low)
            if m_dec:
                custom_op = max(0.05, min(0.90, float(m_dec.group(1))))

        for q_term in matched_in_clause:
            if is_hide:
                if q_term not in hidden_terms:
                    hidden_terms.append(q_term)
            elif is_semi:
                if not any(it["term"] == q_term for it in semi_transparent_items):
                    semi_transparent_items.append({"term": q_term, "opacity": custom_op})
            elif is_opaque:
                if q_term not in opaque_terms:
                    opaque_terms.append(q_term)
            else:
                if q_term not in highlight_terms:
                    highlight_terms.append(q_term)

    # 7. Automatic overlying structure fading for internal organs and deep structures
    if highlight_terms:
        highlighted_ids: Set[str] = set()
        for ht in highlight_terms:
            highlighted_ids.update(_expand_anatomy_term(ht, explicit_side))

        existing_faded_or_hidden_ids: Set[str] = set()
        for it in semi_transparent_items:
            existing_faded_or_hidden_ids.update(_expand_anatomy_term(it["term"], explicit_side))
        for h_term in hidden_terms:
            existing_faded_or_hidden_ids.update(_expand_anatomy_term(h_term, explicit_side))

        # Strip side prefix for canonical lookup
        clean_highlights = [
            re.sub(r"^(오른쪽|우측|왼쪽|좌측|양측|right|left|bilateral)\s+", "", ht.lower()).strip()
            for ht in highlight_terms
        ]
        auto_fades = _get_auto_faded_overlying_terms(
            highlight_terms=clean_highlights,
            existing_faded_or_hidden_ids=existing_faded_or_hidden_ids,
            highlighted_ids=highlighted_ids,
            explicit_side=explicit_side,
        )
        for af in auto_fades:
            if not any(it["term"] == af["term"] for it in semi_transparent_items):
                semi_transparent_items.append(af)

    # 8. Determine camera framing behavior
    has_any_targets = bool(highlight_terms or semi_transparent_items or hidden_terms or opaque_terms)
    if explicit_keep_camera:
        preserve_camera = True
        camera_preset = "keep_current"
    elif highlight_terms:
        # Whenever structures/organs are shown, highlighted, or isolated, auto-frame them in 3D!
        preserve_camera = False
        camera_preset = requested_camera_preset or "auto_frame"
    elif requested_camera_preset:
        preserve_camera = False
        camera_preset = requested_camera_preset
    elif has_any_targets:
        preserve_camera = False
        camera_preset = "auto_frame"
    else:
        preserve_camera = True
        camera_preset = "keep_current"

    matched_deterministic = bool(has_any_targets or requested_camera_preset)

    bilingual = _build_bilingual_explanation(
        command_text=text,
        action_type="apply_patch",
        isolate_mode=isolate_mode,
        highlight_terms=highlight_terms,
        semi_transparent_items=semi_transparent_items,
        hidden_terms=hidden_terms,
        opaque_terms=opaque_terms,
        camera_preset=camera_preset,
    )

    return {
        "actionType": "apply_patch",
        "preserveCamera": preserve_camera,
        "cameraPreset": camera_preset,
        "preferPosterior": prefer_posterior,
        "isolateMode": isolate_mode,
        "highlightTerms": highlight_terms,
        "semiTransparentItems": semi_transparent_items,
        "hiddenTerms": hidden_terms,
        "opaqueTerms": opaque_terms,
        "matchedDeterministic": matched_deterministic,
        **bilingual,
        "sotCitations": [],
    }


def _merge_gemini_and_deterministic_plan(
    gemini_plan: Dict[str, Any],
    det_plan: Dict[str, Any],
    command_text: str,
) -> Dict[str, Any]:
    """
    Combines Gemini 3.8 Flash structured output with the deterministic whole-body keyword resolver
    so that natural-language commands never miss structure mutations or camera auto-framing.
    """
    merged = dict(gemini_plan)
    t_low = (command_text or "").lower()

    if det_plan["actionType"] in ("undo", "reset", "load_template", "set_progress") and merged.get("actionType") == "apply_patch":
        merged["actionType"] = det_plan["actionType"]
        if det_plan.get("templateId"):
            merged["templateId"] = det_plan["templateId"]
        if det_plan.get("stepIndex") is not None:
            merged["stepIndex"] = det_plan["stepIndex"]

    if det_plan.get("isolateMode"):
        merged["isolateMode"] = True

    if not det_plan.get("preserveCamera", True):
        merged["preserveCamera"] = False
        if det_plan.get("cameraPreset") and det_plan["cameraPreset"] != "keep_current":
            merged["cameraPreset"] = det_plan["cameraPreset"]

    if det_plan.get("preferPosterior") is not None:
        merged["preferPosterior"] = det_plan["preferPosterior"]

    if merged.get("actionType") == "apply_patch":
        g_high = list(merged.get("highlightTerms") or [])
        g_semi = list(merged.get("semiTransparentItems") or [])
        g_hide = list(merged.get("hiddenTerms") or [])
        g_opaq = list(merged.get("opaqueTerms") or [])

        for h in det_plan.get("highlightTerms", []):
            if h not in g_high and h not in g_hide and not any(it.get("term") == h for it in g_semi):
                g_high.append(h)

        for item in det_plan.get("semiTransparentItems", []):
            term = item.get("term")
            if term and not any(it.get("term") == term for it in g_semi) and term not in g_hide:
                g_semi.append(item)

        for h in det_plan.get("hiddenTerms", []):
            if h not in g_hide:
                g_hide.append(h)

        for op in det_plan.get("opaqueTerms", []):
            if op not in g_opaq:
                g_opaq.append(op)

        merged["highlightTerms"] = g_high
        merged["semiTransparentItems"] = g_semi
        merged["hiddenTerms"] = g_hide
        merged["opaqueTerms"] = g_opaq

        if g_high and not any(w in t_low for w in ["시점 유지", "카메라 유지", "keep camera", "preserve camera"]):
            merged["preserveCamera"] = False
            if merged.get("cameraPreset") in (None, "keep_current"):
                merged["cameraPreset"] = "auto_frame"

    for key in ("titleEn", "bodyEn", "spokenFeedbackEn", "titleKo", "spokenFeedbackKo", "clinicalExplanationKo"):
        if not merged.get(key) and det_plan.get(key):
            merged[key] = det_plan[key]

    merged["sotCitations"] = merged.get("sotCitations") or []
    return merged


async def plan_scene_command_with_gemini(
    command_text: str,
    current_state_summary: Dict[str, Any],
    model_id: str = "gemini-3.8-flash",
) -> Tuple[Dict[str, Any], float]:
    """
    Translates natural-language anatomical instructions (English or Korean) into a validated
    whole-body 3D scene plan. Uses fast deterministic resolution when anatomical structures or
    control commands are directly matched, and invokes Gemini 3.8 Flash for complex/unmatched phrasing.
    """
    t0 = time.perf_counter()
    det_plan = resolve_deterministic_clinical_plan(command_text, current_state_summary)

    # Fast path: when deterministic whole-body resolver matched concrete structures or control commands,
    # return immediately for sub-10ms responsiveness and zero shoulder bias.
    if det_plan.get("matchedDeterministic"):
        llm_ms = round((time.perf_counter() - t0) * 1000, 1)
        return det_plan, llm_ms

    try:
        client = get_genai_client()
    except Exception:
        llm_ms = round((time.perf_counter() - t0) * 1000, 1)
        return det_plan, llm_ms

    prompt = f"""CliniView Live Whole-Body 3D Anatomy Scene Controller (Z-Anatomy, 385 structures across 28 groups).
Translate the user's English or Korean anatomical command into a structured JSON scene plan.

[Core Rules]
1. Whole-Body Coverage: Support all regions — Head/Neck/Brain (brain, cerebrum, cerebellum, brainstem, thalamus, hippocampus, skull, mandible, carotid, jugular, sternocleidomastoid, trachea, esophagus), Thorax (heart, lungs, aorta, vena cava, pulmonary artery, diaphragm, ribs, sternum, pectoralis), Abdomen (liver, gallbladder, stomach, spleen, pancreas, kidneys, small intestine, large intestine/colon, bladder), Spine/Pelvis (cervical/thoracic/lumbar spine, sacrum, pelvis, intervertebral discs, psoas, rectus abdominis, erector spinae, latissimus dorsi), Upper Limb (rotator cuff, subscapularis, supraspinatus, infraspinatus, deltoid, biceps, triceps, brachial plexus, humerus, radius, ulna), and Lower Limb (gluteus maximus/medius, piriformis, quadriceps, hamstrings, gastrocnemius, soleus, femur, patella, tibia, fibula, sciatic nerve, femoral artery).
2. Auto-Frame Camera: When showing, highlighting, or isolating any structure, set `preserveCamera: false` and `cameraPreset: "auto_frame"` (or a specific regional preset if requested).
3. Layer Control:
   - "isolate" / "only" / "단독" -> set `isolateMode: true` and put target terms in `highlightTerms`.
   - "fade" / "transparent" / "translucent" / "반투명" -> put terms in `semiTransparentItems` with opacity ~0.18.
   - "hide" / "remove" / "숨겨" -> put terms in `hiddenTerms`.
   - "restore" / "opaque" / "불투명" -> put terms in `opaqueTerms`.
   - "reset" / "초기화" -> `actionType: "reset"`, `preserveCamera: false`, `cameraPreset: "whole_body_front"`.
   - "undo" / "되돌리기" -> `actionType: "undo"`.
4. Explanations: Provide clean, natural English (`titleEn`, `bodyEn`, `spokenFeedbackEn`) and Korean (`titleKo`, `spokenFeedbackKo`, `clinicalExplanationKo`) without raw `[SOT-01]` tags.

[Current 3D Scene] revision={current_state_summary.get("revision")}, highlighted={current_state_summary.get("highlightedStructureIds")}
[User Command] "{command_text}"
"""

    def _call() -> Dict[str, Any]:
        interaction = client.interactions.create(
            model=model_id,
            input=prompt,
            store=False,
            response_format=VOICE_PLAN_SCHEMA,
            generation_config={
                "thinking_level": "low",
                "thinking_summaries": "none",
            },
        )
        raw = (interaction.output_text or "").strip()
        return json.loads(raw)

    try:
        gemini_plan = await asyncio.wait_for(asyncio.to_thread(_call), timeout=5.0)
        final_plan = _merge_gemini_and_deterministic_plan(gemini_plan, det_plan, command_text)
    except Exception:
        final_plan = det_plan

    llm_ms = round((time.perf_counter() - t0) * 1000, 1)
    return final_plan, llm_ms


async def execute_natural_language_scene_command(
    command_text: str,
    session_id: str = "default",
    stt_ms: float = 0.0,
    wait_for_ack: bool = True,
) -> Dict[str, Any]:
    """
    Executes a spoken or typed natural-language anatomical command end-to-end:
    Whole-Body Plan -> Scene Service Validation & 3D Auto-Framing -> Browser WebSocket ACK -> Bilingual Response Card.
    """
    t_start = time.perf_counter()
    current_summary = SCENE_SERVICE.get_state(session_id=session_id, compact=True)

    plan, llm_ms = await plan_scene_command_with_gemini(
        command_text=command_text,
        current_state_summary=current_summary,
    )

    action_type = plan.get("actionType", "apply_patch")
    preserve_camera = bool(plan.get("preserveCamera", False))
    camera_preset = plan.get("cameraPreset", "auto_frame")
    isolate_mode = bool(plan.get("isolateMode", False))
    explicit_side = _detect_explicit_side((command_text or "").lower())

    # Strip any legacy [SOT-xx] tags if returned by an external caller
    def _strip_sot(val: str) -> str:
        return re.sub(r"\s*\[SOT-\d+\]", "", val or "").strip()

    explanation_card = {
        "titleEn": _strip_sot(plan.get("titleEn") or f"3D Anatomy Control: {command_text}"),
        "spokenFeedbackEn": _strip_sot(plan.get("spokenFeedbackEn") or ""),
        "bodyEn": _strip_sot(plan.get("bodyEn") or ""),
        "titleKo": _strip_sot(plan.get("titleKo") or f"3D 해부학 제어: {command_text}"),
        "spokenFeedbackKo": _strip_sot(plan.get("spokenFeedbackKo") or ""),
        "bodyKo": _strip_sot(plan.get("clinicalExplanationKo") or ""),
        "sotReferences": [],
        "safetyDisclaimerEn": (
            "Educational 3D visualization based on the Z-Anatomy whole-body atlas. "
            "Always verify anatomical landmarks clinically."
        ),
        "safetyDisclaimerKo": (
            "[교육·설명용 3D 가이드] Z-Anatomy 표준 전신 인체 모델 기반의 시각 자료입니다."
        ),
    }

    t_tool = time.perf_counter()
    session = SCENE_SERVICE.get_or_create_session(session_id)

    if action_type == "undo":
        before_structures = {
            sid: dict(st) for sid, st in session.structures.items()
        }
        exec_res = await SCENE_SERVICE.undo(session_id=session_id, wait_for_ack=wait_for_ack)
        if not exec_res.get("ok", False):
            # If undo stack was empty, reset to whole-body baseline so Undo always succeeds cleanly
            exec_res = await SCENE_SERVICE.apply_patch(
                session_id=session_id,
                changes={
                    "resetToDefault": True,
                    "preserveCamera": False,
                    "cameraPreset": "whole_body_front",
                    "explanationCard": explanation_card,
                },
                wait_for_ack=wait_for_ack,
                source="gemini_voice",
            )
        # Ensure modifiedStructureIds and camera are always populated on Undo
        diff_ids = [
            sid
            for sid, st in session.structures.items()
            if before_structures.get(sid) != st
        ]
        if not diff_ids:
            diff_ids = list(session.selected_structure_ids) or list(SCENE_SERVICE.structures_by_id.keys())
        exec_res["modifiedStructureIds"] = diff_ids
        exec_res["modifiedStructureCount"] = len(diff_ids)
        exec_res["camera"] = session.camera

    elif action_type == "load_template":
        tpl_id = plan.get("templateId") or "proc_subscap_axillary_r"
        if tpl_id not in PROCEDURE_TEMPLATES:
            tpl_id = "proc_subscap_axillary_r"
        exec_res = await SCENE_SERVICE.load_template(
            session_id=session_id,
            template_id=tpl_id,
            step_index=int(plan.get("stepIndex") or 0),
            preserve_camera=preserve_camera,
            wait_for_ack=wait_for_ack,
        )
        tpl_obj = PROCEDURE_TEMPLATES.get(tpl_id, {})
        mod_ids = list(tpl_obj.get("baseStructurePatch", {}).keys()) or list(tpl_obj.get("targetStructureIds", []))
        exec_res.setdefault("modifiedStructureIds", mod_ids)
        exec_res.setdefault("modifiedStructureCount", len(mod_ids))
        exec_res.setdefault("camera", session.camera)

    elif action_type == "set_progress":
        exec_res = await SCENE_SERVICE.set_procedure_progress(
            session_id=session_id,
            progress=plan.get("progress"),
            step_index=plan.get("stepIndex"),
            preserve_camera=preserve_camera,
            wait_for_ack=wait_for_ack,
        )
        exec_res.setdefault("modifiedStructureIds", list(session.selected_structure_ids))
        exec_res.setdefault("modifiedStructureCount", len(session.selected_structure_ids))
        exec_res.setdefault("camera", session.camera)

    elif action_type == "reset":
        before_non_default = [
            sid
            for sid, st in session.structures.items()
            if not st.get("visible", True)
            or float(st.get("opacity", 1.0)) < 0.99
            or bool(st.get("highlighted", False))
        ]
        reset_preset = camera_preset if camera_preset in CAMERA_PRESETS else "whole_body_front"
        changes_reset: Dict[str, Any] = {
            "resetToDefault": True,
            "preserveCamera": False,
            "cameraPreset": reset_preset,
            "camera": CAMERA_PRESETS[reset_preset],
            "explanationCard": explanation_card,
        }
        exec_res = await SCENE_SERVICE.apply_patch(
            session_id=session_id,
            changes=changes_reset,
            wait_for_ack=wait_for_ack,
            source="gemini_voice",
        )
        mod_ids = before_non_default or list(SCENE_SERVICE.structures_by_id.keys())
        exec_res["modifiedStructureIds"] = mod_ids
        exec_res["modifiedStructureCount"] = len(mod_ids)

    else:
        # Build structures patch from plan
        struct_changes: Dict[str, Dict[str, Any]] = {}
        highlight_ids: List[str] = []

        # Resolve highlighted target items first so we know the focus set
        for term in plan.get("highlightTerms", []):
            for sid in _expand_anatomy_term(term, explicit_side):
                if sid not in highlight_ids:
                    highlight_ids.append(sid)

        # Dynamic fallback if plan had no resolved structures yet
        if not highlight_ids and not plan.get("semiTransparentItems") and not plan.get("hiddenTerms") and not plan.get("opaqueTerms"):
            dyn_terms = _extract_dynamic_manifest_terms(command_text, explicit_side)
            for dt in dyn_terms:
                for sid in _expand_anatomy_term(dt, explicit_side):
                    if sid not in highlight_ids:
                        highlight_ids.append(sid)

        # If isolateMode is active, fade all non-target structures across the whole body to 0.12 opacity
        if isolate_mode and highlight_ids:
            highlight_set = set(highlight_ids)
            for sid in SCENE_SERVICE.structures_by_id:
                if sid not in highlight_set:
                    struct_changes[sid] = {
                        "visible": True,
                        "opacity": 0.12,
                        "highlighted": False,
                        "outline": False,
                        "colorHex": None,
                    }
        elif highlight_ids:
            # If the scene was previously in an isolated state (most structures faded < 0.2),
            # restore non-mentioned structures to normal visibility so new Show/Highlight commands look clean
            faded_count = sum(
                1 for st in session.structures.values() if float(st.get("opacity", 1.0)) <= 0.20
            )
            if faded_count > len(SCENE_SERVICE.structures_by_id) * 0.5:
                for sid in SCENE_SERVICE.structures_by_id:
                    struct_changes[sid] = {
                        "visible": True,
                        "opacity": 1.0,
                        "highlighted": False,
                        "outline": False,
                        "colorHex": None,
                    }

        # 1. Semi-transparent items (faded overlying layers)
        for item in plan.get("semiTransparentItems", []):
            term = item.get("term", "")
            op = max(0.05, min(0.95, float(item.get("opacity", 0.18))))
            for sid in _expand_anatomy_term(term, explicit_side):
                if sid not in highlight_ids:
                    struct_changes[sid] = {
                        "visible": True,
                        "opacity": round(op, 3),
                        "highlighted": False,
                        "outline": False,
                        "colorHex": None,
                    }

        # 2. Hidden items
        for term in plan.get("hiddenTerms", []):
            for sid in _expand_anatomy_term(term, explicit_side):
                struct_changes[sid] = {
                    "visible": False,
                    "opacity": 0.0,
                    "highlighted": False,
                    "outline": False,
                    "colorHex": None,
                }

        # 3. Opaque restored items
        for term in plan.get("opaqueTerms", []):
            for sid in _expand_anatomy_term(term, explicit_side):
                struct_changes[sid] = {
                    "visible": True,
                    "opacity": 1.0,
                    "highlighted": False,
                    "outline": False,
                    "colorHex": None,
                }

        # 4. Apply highlighted target items on top
        for sid in highlight_ids:
            struct_changes[sid] = {
                "visible": True,
                "opacity": 1.0,
                "highlighted": True,
                "colorHex": "#ef4444",
                "outline": True,
            }

        changes_payload: Dict[str, Any] = {
            "structures": struct_changes,
            "preserveCamera": preserve_camera,
            "explanationCard": explanation_card,
        }
        if highlight_ids:
            changes_payload["highlightIds"] = highlight_ids
            changes_payload["selectedStructureIds"] = highlight_ids
            if not preserve_camera:
                changes_payload["autoFrameTargets"] = True
                if plan.get("preferPosterior") is not None:
                    changes_payload["preferPosterior"] = bool(plan["preferPosterior"])
        elif struct_changes and not preserve_camera:
            changes_payload["autoFrameTargets"] = True

        # Only apply a fixed cameraPreset when no specific structures are being auto-framed
        # (or when the user asked for a pure camera view change)
        if (
            not preserve_camera
            and camera_preset in CAMERA_PRESETS
            and not highlight_ids
        ):
            changes_payload["cameraPreset"] = camera_preset
            changes_payload["camera"] = CAMERA_PRESETS[camera_preset]
            changes_payload["preserveCamera"] = False

        exec_res = await SCENE_SERVICE.apply_patch(
            session_id=session_id,
            changes=changes_payload,
            wait_for_ack=wait_for_ack,
            source="gemini_voice",
        )

    tool_ack_ms = round((time.perf_counter() - t_tool) * 1000, 1)
    total_ms = round(stt_ms + (time.perf_counter() - t_start) * 1000, 1)

    return {
        "ok": exec_res.get("ok", True),
        "commandText": command_text,
        "plan": plan,
        "execution": exec_res,
        "explanationCard": explanation_card,
        "latencyMs": {
            "sttMs": stt_ms,
            "llmMs": llm_ms,
            "toolAckMs": tool_ack_ms,
            "viewerAckMs": (exec_res.get("viewerAck") or {}).get("ackLatencyMs", 0.0),
            "totalMs": total_ms,
        },
    }
