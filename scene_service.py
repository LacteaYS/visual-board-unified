"""
Authoritative Whole-Body 3D Scene Service & Command Processor for CliniView Live.

Shares a single authoritative scene state across:
1. Three.js Interactive 3D Whole-Body & Regional Anatomy Viewer (Mouse / Touch / UI Sliders)
2. Antigravity Anatomy MCP Server (stdio JSON-RPC -> HTTP/WS Scene Service)
3. Gemini Push-to-Talk Voice & Function-Calling Controller

Enforces:
- Automatic hot-reloading of structures-manifest.json on disk (supports both 91-structure shoulder and 250-320+ whole-body Z-Anatomy manifests without restart)
- Structure ID & anatomical term validation against structures-manifest.json
- Automatic 3D Bounding-Box Camera Framing (compute_camera_for_structures) for any structure or organ
- Whole-body and regional camera presets (defaulting to whole_body_front on startup & reset)
- Opacity validation in [0.0, 1.0]
- Revision control (expectedRevision) & commandId idempotency
- Camera preservation when preserveCamera is True
- Real Browser Viewer ACK tracking over WebSocket before reporting visual apply completion
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import WebSocket

BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "static" / "assets"
CAPTURES_DIR = BASE_DIR / "static" / "captures"
CAPTURES_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = ASSETS_DIR / "structures-manifest.json"
STRUCTURES_MANIFEST_PATH = MANIFEST_PATH
PROVENANCE_PATH = ASSETS_DIR / "provenance-manifest.json"


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# Whole-Body & Regional 3D Camera Presets (Three.js Y-up meters)
CAMERA_PRESETS: Dict[str, Dict[str, Any]] = {
    "whole_body_front": {
        "name": "whole_body_front",
        "labelKo": "전신 정면",
        "position": [0.0, 0.92, 2.35],
        "target": [0.0, 0.90, 0.0],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "whole_body_back": {
        "name": "whole_body_back",
        "labelKo": "전신 후면",
        "position": [0.0, 0.92, -2.35],
        "target": [0.0, 0.90, 0.0],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "head_neck": {
        "name": "head_neck",
        "labelKo": "두경부·뇌",
        "position": [0.0, 1.58, 0.58],
        "target": [0.0, 1.56, 0.0],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "thorax_organs": {
        "name": "thorax_organs",
        "labelKo": "흉부·심폐",
        "position": [0.0, 1.28, 0.82],
        "target": [0.0, 1.26, 0.0],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "abdomen_organs": {
        "name": "abdomen_organs",
        "labelKo": "복부·장기",
        "position": [0.0, 1.00, 0.85],
        "target": [0.0, 0.98, 0.0],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "spine_pelvis": {
        "name": "spine_pelvis",
        "labelKo": "척추·골반 후면",
        "position": [0.0, 1.05, -1.05],
        "target": [0.0, 1.02, -0.04],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "lower_limb": {
        "name": "lower_limb",
        "labelKo": "하지·무릎",
        "position": [0.0, 0.48, 1.38],
        "target": [0.0, 0.46, 0.0],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "lower_limb_back": {
        "name": "lower_limb_back",
        "labelKo": "하지 후면(햄스트링·종아리)",
        "position": [0.0, 0.48, -1.38],
        "target": [0.0, 0.46, 0.0],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    # Regional shoulder / upper-limb presets
    "right_anterior": {
        "name": "right_anterior",
        "labelKo": "우측 어깨 전면",
        "position": [-0.20, 1.37, 0.40],
        "target": [-0.12, 1.34, -0.03],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "right_posterior": {
        "name": "right_posterior",
        "labelKo": "우측 어깨 후면",
        "position": [-0.28, 1.40, -0.38],
        "target": [-0.11, 1.34, -0.05],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "right_axillary": {
        "name": "right_axillary",
        "labelKo": "우측 전외측(액와)",
        "position": [-0.36, 1.36, 0.34],
        "target": [-0.11, 1.34, -0.04],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "right_anterolateral": {
        "name": "right_anterolateral",
        "labelKo": "우측 전외측",
        "position": [-0.36, 1.36, 0.34],
        "target": [-0.11, 1.34, -0.04],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "left_anterolateral": {
        "name": "left_anterolateral",
        "labelKo": "좌측 전외측",
        "position": [0.36, 1.36, 0.34],
        "target": [0.11, 1.34, -0.04],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
    "bilateral_front": {
        "name": "bilateral_front",
        "labelKo": "양측 상체 정면",
        "position": [0.0, 1.37, 0.52],
        "target": [0.0, 1.34, -0.04],
        "up": [0.0, 1.0, 0.0],
        "fov": 36,
    },
}

# Tokens for posterior vs anterior structure orientation detection in compute_camera_for_structures
POSTERIOR_STRUCTURE_TOKENS: Tuple[str, ...] = (
    "gluteus",
    "gluteal",
    "piriformis",
    "hamstring",
    "biceps_femoris",
    "semitendinosus",
    "semimembranosus",
    "gastrocnemius",
    "soleus",
    "calcaneal_tendon",
    "achilles",
    "sciatic_nerve",
    "sciatic",
    "latissimus",
    "trapezius",
    "rhomboid",
    "infraspinatus",
    "teres",
    "erector",
    "spinalis",
    "longissimus",
    "iliocostalis",
    "multifidus",
    "sacrum",
    "coccyx",
    "cerebellum",
    "occipital",
    "splenius",
    "semispinalis",
    "levator_scapulae",
    "popliteus",
    "triceps",
)

ANTERIOR_PREFERRED_TOKENS: Tuple[str, ...] = (
    "subscapularis",
    "pectoralis",
    "biceps_brachii",
    "biceps_long",
    "biceps_short",
    "coracobrachialis",
    "brachialis",
    "brachioradialis",
    "rectus_abdominis",
    "oblique",
    "transversus_abdominis",
    "psoas",
    "iliacus",
    "iliopsoas",
    "quadriceps",
    "rectus_femoris",
    "vastus",
    "sartorius",
    "adductor",
    "gracilis",
    "pectineus",
    "tibialis_anterior",
    "patella",
    "sternocleidomastoid",
    "scalene",
    "masseter",
    "temporalis",
    "heart",
    "lung",
    "liver",
    "stomach",
    "gallbladder",
    "pancreas",
    "spleen",
    "intestine",
    "duodenum",
    "jejunum",
    "ileum",
    "colon",
    "cecum",
    "appendix",
    "bladder",
    "thyroid",
    "trachea",
    "esophagus",
    "aorta",
    "vena_cava",
    "carotid",
    "jugular",
    "cerebrum",
    "frontal",
    "brainstem",
    "mandible",
    "maxilla",
    "sternum",
)

# Comprehensive Whole-Body Korean/English Keyword -> Stem & Search Token Map
WHOLE_BODY_KEYWORD_MAP: Dict[str, List[str]] = {
    # --- 1. 뇌·두경부 (Head, Neck & Brain) ---
    "뇌": ["brain", "cerebrum", "cerebral", "cerebellum", "brainstem", "encephalon", "pons", "medulla", "midbrain", "diencephalon", "thalamus", "corpus_callosum"],
    "brain": ["brain", "cerebrum", "cerebral", "cerebellum", "brainstem", "encephalon", "pons", "medulla"],
    "대뇌": ["cerebrum", "cerebral", "telencephalon", "frontal_lobe", "parietal_lobe", "temporal_lobe", "occipital_lobe", "insula", "corpus_callosum", "brain"],
    "cerebrum": ["cerebrum", "cerebral", "telencephalon", "brain"],
    "소뇌": ["cerebellum", "cerebellar"],
    "cerebellum": ["cerebellum", "cerebellar"],
    "뇌간": ["brainstem", "brain_stem", "pons", "medulla", "midbrain", "mesencephalon", "diencephalon", "thalamus"],
    "brainstem": ["brainstem", "brain_stem", "pons", "medulla", "midbrain", "mesencephalon"],
    "두개골": ["skull", "cranium", "cranial", "frontal_bone", "parietal_bone", "occipital_bone", "temporal_bone", "sphenoid", "ethmoid", "zygomatic", "maxilla", "nasal_bone", "mandible"],
    "머리뼈": ["skull", "cranium", "frontal_bone", "parietal_bone", "occipital_bone", "temporal_bone", "sphenoid", "ethmoid", "zygomatic", "maxilla", "mandible"],
    "skull": ["skull", "cranium", "frontal_bone", "parietal_bone", "occipital_bone", "temporal_bone", "sphenoid", "zygomatic", "maxilla", "mandible"],
    "머리": ["skull", "cranium", "frontal_bone", "parietal_bone", "occipital_bone", "temporal_bone", "brain", "cerebrum", "cerebellum", "masseter", "temporalis", "mandible"],
    "전두골": ["frontal_bone", "frontal"],
    "두정골": ["parietal_bone", "parietal"],
    "후두골": ["occipital_bone", "occipital"],
    "측두골": ["temporal_bone", "temporal"],
    "턱뼈": ["mandible", "maxilla"],
    "하악골": ["mandible", "mandibular"],
    "mandible": ["mandible", "mandibular"],
    "상악골": ["maxilla", "maxillary"],
    "저작근": ["masseter", "temporalis", "pterygoid", "lateral_pterygoid", "medial_pterygoid"],
    "교근": ["masseter"],
    "masseter": ["masseter"],
    "측두근": ["temporalis", "temporal_muscle"],
    "temporalis": ["temporalis", "temporal_muscle"],
    "흉쇄유돌근": ["sternocleidomastoid"],
    "sternocleidomastoid": ["sternocleidomastoid"],
    "사각근": ["scalenus", "scalene", "anterior_scalene", "middle_scalene", "posterior_scalene", "scalenus_anterior", "scalenus_medius", "scalenus_posterior"],
    "scalene": ["scalenus", "scalene", "anterior_scalene", "middle_scalene", "posterior_scalene"],
    "갑상선": ["thyroid", "thyroid_gland", "thyroid_cartilage"],
    "thyroid": ["thyroid", "thyroid_gland", "thyroid_cartilage"],
    "후두": ["larynx", "thyroid_cartilage", "cricoid", "epiglottis", "hyoid"],
    "기관": ["trachea", "bronchus", "bronchi"],
    "trachea": ["trachea", "bronchus"],
    "경동맥": ["carotid", "common_carotid", "internal_carotid", "external_carotid"],
    "carotid": ["carotid", "common_carotid", "internal_carotid", "external_carotid"],
    "경정맥": ["jugular", "internal_jugular", "external_jugular"],
    "jugular": ["jugular", "internal_jugular", "external_jugular"],

    # --- 2. 흉부·심폐 (Thorax & Cardiopulmonary) ---
    "심장": ["heart", "cardiac", "myocardium", "ventricle", "atrium", "pericardium"],
    "heart": ["heart", "cardiac", "myocardium", "ventricle", "atrium"],
    "폐": ["lung", "right_lung", "left_lung", "lung_r", "lung_l", "upper_lobe", "middle_lobe", "lower_lobe", "pulmonary"],
    "허파": ["lung", "right_lung", "left_lung", "lung_r", "lung_l", "pulmonary"],
    "lungs": ["lung", "right_lung", "left_lung", "lung_r", "lung_l", "pulmonary"],
    "lung": ["lung", "right_lung", "left_lung", "lung_r", "lung_l", "pulmonary"],
    "우폐": ["lung_r", "right_lung"],
    "좌폐": ["lung_l", "left_lung"],
    "횡격막": ["diaphragm", "thoracic_diaphragm"],
    "가로막": ["diaphragm", "thoracic_diaphragm"],
    "diaphragm": ["diaphragm", "thoracic_diaphragm"],
    "대동맥": ["aorta", "ascending_aorta", "aortic_arch", "arch_of_aorta", "descending_aorta", "thoracic_aorta", "abdominal_aorta"],
    "aorta": ["aorta", "ascending_aorta", "aortic_arch", "arch_of_aorta", "descending_aorta", "thoracic_aorta", "abdominal_aorta"],
    "대정맥": ["vena_cava", "superior_vena_cava", "inferior_vena_cava"],
    "vena cava": ["vena_cava", "superior_vena_cava", "inferior_vena_cava"],
    "식도": ["esophagus", "oesophagus"],
    "esophagus": ["esophagus", "oesophagus"],
    "갈비뼈": ["rib", "rib_1", "rib_2", "rib_3", "rib_4", "rib_5", "rib_6", "rib_7", "rib_8", "rib_9", "rib_10", "rib_11", "rib_12", "ribs", "costal", "thoracic_cage"],
    "늑골": ["rib", "rib_1", "rib_2", "rib_3", "rib_4", "rib_5", "rib_6", "rib_7", "rib_8", "rib_9", "rib_10", "rib_11", "rib_12", "ribs", "costal", "thoracic_cage"],
    "ribcage": ["sternum", "rib", "rib_1", "rib_2", "rib_3", "rib_4", "rib_5", "rib_6", "rib_7", "rib_8", "rib_9", "rib_10", "rib_11", "rib_12", "ribs", "costal", "thoracic_cage"],
    "rib cage": ["sternum", "rib", "rib_1", "rib_2", "rib_3", "rib_4", "rib_5", "rib_6", "rib_7", "rib_8", "rib_9", "rib_10", "rib_11", "rib_12", "ribs", "costal", "thoracic_cage"],
    "thoracic cage": ["sternum", "rib", "rib_1", "rib_2", "rib_3", "rib_4", "rib_5", "rib_6", "rib_7", "rib_8", "rib_9", "rib_10", "rib_11", "rib_12", "ribs", "costal", "thoracic_cage"],
    "ribs": ["rib", "rib_1", "rib_2", "rib_3", "rib_4", "rib_5", "rib_6", "rib_7", "rib_8", "rib_9", "rib_10", "rib_11", "rib_12", "ribs", "costal"],
    "rib": ["rib", "rib_1", "rib_2", "rib_3", "rib_4", "rib_5", "rib_6", "rib_7", "rib_8", "rib_9", "rib_10", "rib_11", "rib_12", "ribs", "costal"],
    "흉곽": ["sternum", "rib", "rib_1", "rib_2", "rib_3", "rib_4", "rib_5", "rib_6", "rib_7", "rib_8", "rib_9", "rib_10", "rib_11", "rib_12", "ribs", "costal", "thoracic_cage"],
    "흉골": ["sternum", "manubrium", "xiphoid"],
    "sternum": ["sternum", "manubrium", "xiphoid"],
    "대흉근": ["pectoralis_major"],
    "pectoralis major": ["pectoralis_major"],
    "소흉근": ["pectoralis_minor"],
    "pectoralis minor": ["pectoralis_minor"],
    "흉근": ["pectoralis_major", "pectoralis_minor"],
    "pectoralis": ["pectoralis_major", "pectoralis_minor"],

    # --- 3. 복부·소화기·내장 (Abdomen, Digestive & Viscera) ---
    "간": ["liver", "hepatic"],
    "간장": ["liver", "hepatic"],
    "liver": ["liver", "hepatic"],
    "위장": ["stomach", "gastric"],
    "위": ["stomach", "gastric"],
    "stomach": ["stomach", "gastric"],
    "쓸개": ["gallbladder", "gall_bladder", "biliary"],
    "담낭": ["gallbladder", "gall_bladder", "biliary"],
    "gallbladder": ["gallbladder", "gall_bladder"],
    "췌장": ["pancreas", "pancreatic"],
    "이자": ["pancreas", "pancreatic"],
    "pancreas": ["pancreas", "pancreatic"],
    "비장": ["spleen", "splenic"],
    "지라": ["spleen", "splenic"],
    "spleen": ["spleen", "splenic"],
    "신장": ["kidney", "renal"],
    "콩팥": ["kidney", "renal"],
    "kidneys": ["kidney", "renal"],
    "kidney": ["kidney", "renal"],
    "부신": ["adrenal", "suprarenal"],
    "adrenal": ["adrenal", "suprarenal"],
    "요관": ["ureter"],
    "ureter": ["ureter"],
    "방광": ["bladder", "urinary_bladder"],
    "bladder": ["bladder", "urinary_bladder"],
    "소장": ["small_intestine", "duodenum", "jejunum", "ileum", "intestine_small"],
    "small intestine": ["small_intestine", "duodenum", "jejunum", "ileum"],
    "intestines": ["small_intestine", "duodenum", "jejunum", "ileum", "large_intestine", "colon", "cecum", "rectum"],
    "intestine": ["small_intestine", "duodenum", "jejunum", "ileum", "large_intestine", "colon", "cecum", "rectum"],
    "십이지장": ["duodenum", "small_intestine"],
    "duodenum": ["duodenum", "small_intestine"],
    "공장": ["jejunum", "small_intestine"],
    "jejunum": ["jejunum", "small_intestine"],
    "회장": ["ileum", "small_intestine"],
    "ileum": ["ileum", "small_intestine"],
    "대장": ["large_intestine", "colon", "ascending_colon", "transverse_colon", "descending_colon", "sigmoid_colon", "cecum", "rectum", "appendix"],
    "large intestine": ["large_intestine", "colon", "ascending_colon", "transverse_colon", "descending_colon", "sigmoid_colon", "cecum", "rectum"],
    "결장": ["colon", "large_intestine", "ascending_colon", "transverse_colon", "descending_colon", "sigmoid_colon"],
    "colon": ["colon", "large_intestine", "ascending_colon", "transverse_colon", "descending_colon", "sigmoid_colon"],
    "맹장": ["cecum", "appendix", "large_intestine", "colon"],
    "cecum": ["cecum", "appendix", "colon"],
    "직장": ["rectum", "colon", "large_intestine"],
    "rectum": ["rectum", "colon"],
    "소화기관": ["esophagus", "stomach", "liver", "gallbladder", "pancreas", "small_intestine", "duodenum", "jejunum", "ileum", "large_intestine", "colon", "cecum", "rectum"],
    "소화기": ["esophagus", "stomach", "liver", "gallbladder", "pancreas", "small_intestine", "duodenum", "jejunum", "ileum", "large_intestine", "colon", "cecum", "rectum"],
    "digestive organs": ["esophagus", "stomach", "liver", "gallbladder", "pancreas", "small_intestine", "duodenum", "jejunum", "ileum", "large_intestine", "colon", "cecum", "rectum"],
    "digestive system": ["esophagus", "stomach", "liver", "gallbladder", "pancreas", "small_intestine", "duodenum", "jejunum", "ileum", "large_intestine", "colon", "cecum", "rectum"],
    "digestive": ["esophagus", "stomach", "liver", "gallbladder", "pancreas", "small_intestine", "duodenum", "jejunum", "ileum", "large_intestine", "colon", "cecum", "rectum"],
    "복직근": ["rectus_abdominis"],
    "rectus abdominis": ["rectus_abdominis"],
    "외복사근": ["external_oblique", "obliquus_externus", "abdominal_external_oblique"],
    "external oblique": ["external_oblique", "obliquus_externus"],
    "내복사근": ["internal_oblique", "obliquus_internus", "abdominal_internal_oblique"],
    "internal oblique": ["internal_oblique", "obliquus_internus"],
    "복횡근": ["transversus_abdominis", "transverse_abdominis"],
    "transversus abdominis": ["transversus_abdominis", "transverse_abdominis"],
    "복근": ["rectus_abdominis", "external_oblique", "internal_oblique", "transversus_abdominis", "obliquus_externus", "obliquus_internus"],
    "복벽": ["rectus_abdominis", "external_oblique", "internal_oblique", "transversus_abdominis"],
    "abdominal wall": ["rectus_abdominis", "external_oblique", "internal_oblique", "transversus_abdominis"],
    "abdominal muscles": ["rectus_abdominis", "external_oblique", "internal_oblique", "transversus_abdominis"],
    "abdominals": ["rectus_abdominis", "external_oblique", "internal_oblique", "transversus_abdominis"],
    "장요근": ["iliopsoas", "psoas_major", "psoas_minor", "psoas", "iliacus"],
    "iliopsoas": ["iliopsoas", "psoas_major", "psoas_minor", "psoas", "iliacus"],
    "대요근": ["psoas_major", "psoas", "iliopsoas"],
    "psoas": ["psoas_major", "psoas_minor", "psoas", "iliopsoas"],
    "장골근": ["iliacus", "iliopsoas"],
    "iliacus": ["iliacus", "iliopsoas"],
    "요방형근": ["quadratus_lumborum"],
    "quadratus lumborum": ["quadratus_lumborum"],

    # --- 4. 척추·등·골반 (Spine, Back & Pelvis) ---
    "척추": ["vertebra", "cervical", "thoracic", "lumbar", "sacrum", "coccyx", "spine", "atlas", "axis", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10", "t11", "t12", "l1", "l2", "l3", "l4", "l5", "intervertebral"],
    "spine": ["vertebra", "cervical", "thoracic", "lumbar", "sacrum", "coccyx", "spine", "c1", "c2", "c3", "c4", "c5", "c6", "c7", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10", "t11", "t12", "l1", "l2", "l3", "l4", "l5"],
    "경추": ["cervical", "atlas", "axis", "vertebra_c1", "vertebra_c2", "vertebra_c3", "vertebra_c4", "vertebra_c5", "vertebra_c6", "vertebra_c7", "c1", "c2", "c3", "c4", "c5", "c6", "c7"],
    "목뼈": ["cervical", "atlas", "axis", "vertebra_c1", "vertebra_c2", "vertebra_c3", "vertebra_c4", "vertebra_c5", "vertebra_c6", "vertebra_c7"],
    "흉추": ["thoracic_vertebra", "vertebra_t1", "vertebra_t2", "vertebra_t3", "vertebra_t4", "vertebra_t5", "vertebra_t6", "vertebra_t7", "vertebra_t8", "vertebra_t9", "vertebra_t10", "vertebra_t11", "vertebra_t12", "t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10", "t11", "t12"],
    "등뼈": ["thoracic_vertebra", "vertebra_t1", "vertebra_t2", "vertebra_t3", "vertebra_t4", "vertebra_t5", "vertebra_t6", "vertebra_t7", "vertebra_t8", "vertebra_t9", "vertebra_t10", "vertebra_t11", "vertebra_t12"],
    "요추": ["lumbar", "vertebra_l1", "vertebra_l2", "vertebra_l3", "vertebra_l4", "vertebra_l5", "l1", "l2", "l3", "l4", "l5"],
    "허리뼈": ["lumbar", "vertebra_l1", "vertebra_l2", "vertebra_l3", "vertebra_l4", "vertebra_l5", "l1", "l2", "l3", "l4", "l5"],
    "lumbar": ["lumbar", "vertebra_l1", "vertebra_l2", "vertebra_l3", "vertebra_l4", "vertebra_l5", "l1", "l2", "l3", "l4", "l5"],
    "천골": ["sacrum", "sacral"],
    "엉치뼈": ["sacrum", "sacral"],
    "sacrum": ["sacrum", "sacral"],
    "미골": ["coccyx", "coccygeal"],
    "꼬리뼈": ["coccyx", "coccygeal"],
    "골반": ["pelvis", "hip_bone", "ilium", "ischium", "pubis", "os_coxae", "sacrum", "coccyx", "pelvic"],
    "pelvis": ["pelvis", "hip_bone", "ilium", "ischium", "pubis", "os_coxae", "sacrum", "coccyx"],
    "장골": ["ilium", "hip_bone", "pelvis", "os_coxae"],
    "관골": ["hip_bone", "ilium", "ischium", "pubis", "os_coxae"],
    "척수": ["spinal_cord", "spinal_nerve", "cauda_equina"],
    "spinal cord": ["spinal_cord", "spinal_nerve"],
    "광배근": ["latissimus_dorsi", "latissimus"],
    "latissimus": ["latissimus_dorsi", "latissimus"],
    "척추기립근": ["erector_spinae", "iliocostalis", "longissimus", "spinalis", "multifidus"],
    "기립근": ["erector_spinae", "iliocostalis", "longissimus", "spinalis", "multifidus"],
    "erector spinae": ["erector_spinae", "iliocostalis", "longissimus", "spinalis", "multifidus"],
    "다열근": ["multifidus"],
    "승모근": ["trapezius_descending", "trapezius_transverse", "trapezius_ascending", "trapezius"],
    "trapezius": ["trapezius_descending", "trapezius_transverse", "trapezius_ascending", "trapezius"],
    "능형근": ["rhomboid_major", "rhomboid_minor", "rhomboid"],
    "rhomboid": ["rhomboid_major", "rhomboid_minor", "rhomboid"],
    "견갑거근": ["levator_scapulae"],
    "levator scapulae": ["levator_scapulae"],
    "전거근": ["serratus_anterior"],
    "serratus": ["serratus_anterior"],

    # --- 5. 어깨·상지·팔 (Shoulder, Upper Limb & Arm) ---
    "어깨": ["subscapularis", "supraspinatus", "infraspinatus", "teres_minor", "deltoid_clavicular", "deltoid_acromial", "deltoid_spinal", "scapula", "humerus", "clavicle"],
    "회전근개": ["subscapularis", "supraspinatus", "infraspinatus", "teres_minor"],
    "rotator cuff": ["subscapularis", "supraspinatus", "infraspinatus", "teres_minor"],
    "견갑하근": ["subscapularis"],
    "subscapularis": ["subscapularis"],
    "극상근": ["supraspinatus"],
    "supraspinatus": ["supraspinatus"],
    "극하근": ["infraspinatus"],
    "infraspinatus": ["infraspinatus"],
    "소원근": ["teres_minor"],
    "teres minor": ["teres_minor"],
    "대원근": ["teres_major"],
    "teres major": ["teres_major"],
    "삼각근": ["deltoid_clavicular", "deltoid_acromial", "deltoid_spinal", "deltoid"],
    "deltoid": ["deltoid_clavicular", "deltoid_acromial", "deltoid_spinal", "deltoid"],
    "상완이두근": ["biceps_long_head", "biceps_short_head", "biceps_brachii", "biceps"],
    "이두근": ["biceps_long_head", "biceps_short_head", "biceps_brachii", "biceps"],
    "biceps": ["biceps_long_head", "biceps_short_head", "biceps_brachii", "biceps"],
    "상완삼두근": ["triceps_long_head", "triceps_lateral_head", "triceps_medial_head", "triceps_brachii", "triceps"],
    "삼두근": ["triceps_long_head", "triceps_lateral_head", "triceps_medial_head", "triceps_brachii", "triceps"],
    "triceps": ["triceps_long_head", "triceps_lateral_head", "triceps_medial_head", "triceps_brachii", "triceps"],
    "상완근": ["brachialis"],
    "brachialis": ["brachialis"],
    "오구완근": ["coracobrachialis"],
    "coracobrachialis": ["coracobrachialis"],
    "완요골근": ["brachioradialis"],
    "brachioradialis": ["brachioradialis"],
    "전완근": ["brachioradialis", "pronator_teres", "flexor_carpi", "extensor_carpi", "flexor_digitorum", "extensor_digitorum", "supinator", "forearm"],
    "팔뚝": ["brachioradialis", "pronator_teres", "flexor_carpi", "extensor_carpi", "flexor_digitorum", "extensor_digitorum"],
    "견갑골": ["scapula"],
    "날개뼈": ["scapula"],
    "scapula": ["scapula"],
    "상완골": ["humerus"],
    "humerus": ["humerus"],
    "쇄골": ["clavicle"],
    "clavicle": ["clavicle"],
    "요골": ["radius"],
    "radius": ["radius"],
    "척골": ["ulna"],
    "ulna": ["ulna"],
    "정중신경": ["median_nerve", "median"],
    "median nerve": ["median_nerve", "median"],
    "요골신경": ["radial_nerve", "radial"],
    "radial nerve": ["radial_nerve", "radial"],
    "척골신경": ["ulnar_nerve", "ulnar"],
    "ulnar nerve": ["ulnar_nerve", "ulnar"],
    "액와동맥": ["axillary_artery"],
    "액와신경": ["axillary_nerve"],
    "완신경총": ["brachial_plexus", "axillary_nerve", "median_nerve", "radial_nerve", "ulnar_nerve", "musculocutaneous_nerve", "superior_subscapular_nerve", "inferior_subscapular_nerve"],
    "신경혈관": ["axillary_artery", "subscapular_artery", "axillary_nerve", "superior_subscapular_nerve", "inferior_subscapular_nerve"],

    # --- 6. 하지·엉덩이·허벅지·무릎·종아리·발 (Lower Limb, Hip, Thigh, Knee, Calf & Foot) ---
    "둔근": ["gluteus_maximus", "gluteus_medius", "gluteus_minimus", "piriformis", "tensor_fasciae_latae"],
    "엉덩이": ["gluteus_maximus", "gluteus_medius", "gluteus_minimus", "piriformis"],
    "gluteus": ["gluteus_maximus", "gluteus_medius", "gluteus_minimus"],
    "대둔근": ["gluteus_maximus"],
    "gluteus maximus": ["gluteus_maximus"],
    "중둔근": ["gluteus_medius"],
    "gluteus medius": ["gluteus_medius"],
    "소둔근": ["gluteus_minimus"],
    "gluteus minimus": ["gluteus_minimus"],
    "이상근": ["piriformis"],
    "piriformis": ["piriformis"],
    "대퇴근막장근": ["tensor_fasciae_latae", "iliotibial"],
    "허벅지": ["rectus_femoris", "vastus_lateralis", "vastus_medialis", "vastus_intermedius", "sartorius", "biceps_femoris", "semitendinosus", "semimembranosus", "adductor", "gracilis", "pectineus", "femur"],
    "대퇴사두근": ["rectus_femoris", "vastus_lateralis", "vastus_medialis", "vastus_intermedius", "quadriceps"],
    "사두근": ["rectus_femoris", "vastus_lateralis", "vastus_medialis", "vastus_intermedius", "quadriceps"],
    "quadriceps": ["rectus_femoris", "vastus_lateralis", "vastus_medialis", "vastus_intermedius", "quadriceps"],
    "대퇴직근": ["rectus_femoris"],
    "rectus femoris": ["rectus_femoris"],
    "외측광근": ["vastus_lateralis"],
    "vastus lateralis": ["vastus_lateralis"],
    "내측광근": ["vastus_medialis"],
    "vastus medialis": ["vastus_medialis"],
    "중간광근": ["vastus_intermedius"],
    "vastus intermedius": ["vastus_intermedius"],
    "봉공근": ["sartorius"],
    "sartorius": ["sartorius"],
    "내전근": ["adductor_magnus", "adductor_longus", "adductor_brevis", "adductor", "pectineus", "gracilis"],
    "adductor": ["adductor_magnus", "adductor_longus", "adductor_brevis", "adductor", "pectineus", "gracilis"],
    "박근": ["gracilis"],
    "치골근": ["pectineus"],
    "햄스트링": ["biceps_femoris", "biceps_femoris_long", "biceps_femoris_short", "semitendinosus", "semimembranosus", "hamstring"],
    "hamstring": ["biceps_femoris", "biceps_femoris_long", "biceps_femoris_short", "semitendinosus", "semimembranosus", "hamstring"],
    "대퇴이두근": ["biceps_femoris", "biceps_femoris_long", "biceps_femoris_short"],
    "biceps femoris": ["biceps_femoris", "biceps_femoris_long", "biceps_femoris_short"],
    "반건양근": ["semitendinosus"],
    "semitendinosus": ["semitendinosus"],
    "반막양근": ["semimembranosus"],
    "semimembranosus": ["semimembranosus"],
    "무릎": ["patella", "patellar_ligament", "femur", "tibia", "fibula", "meniscus", "cruciate", "collateral_ligament", "knee"],
    "knee": ["patella", "patellar_ligament", "femur", "tibia", "fibula", "meniscus", "knee"],
    "슬개골": ["patella", "patellar_ligament"],
    "patella": ["patella", "patellar_ligament"],
    "대퇴골": ["femur"],
    "femur": ["femur"],
    "경골": ["tibia"],
    "정강뼈": ["tibia"],
    "tibia": ["tibia"],
    "비골": ["fibula"],
    "fibula": ["fibula"],
    "종아리": ["gastrocnemius", "gastrocnemius_medial", "gastrocnemius_lateral", "soleus", "calcaneal_tendon", "achilles", "tibialis_anterior", "tibialis_posterior", "fibularis", "peroneus"],
    "calf": ["gastrocnemius", "gastrocnemius_medial", "gastrocnemius_lateral", "soleus", "calcaneal_tendon"],
    "비복근": ["gastrocnemius", "gastrocnemius_medial", "gastrocnemius_lateral"],
    "장딴지근": ["gastrocnemius", "gastrocnemius_medial", "gastrocnemius_lateral"],
    "gastrocnemius": ["gastrocnemius", "gastrocnemius_medial", "gastrocnemius_lateral"],
    "가자미근": ["soleus"],
    "soleus": ["soleus"],
    "전경골근": ["tibialis_anterior"],
    "tibialis anterior": ["tibialis_anterior"],
    "후경골근": ["tibialis_posterior"],
    "아킬레스건": ["calcaneal_tendon", "achilles_tendon", "achilles"],
    "아킬레스": ["calcaneal_tendon", "achilles_tendon", "achilles"],
    "종골건": ["calcaneal_tendon", "achilles_tendon", "achilles"],
    "achilles": ["calcaneal_tendon", "achilles_tendon", "achilles"],
    "calcaneal tendon": ["calcaneal_tendon", "achilles_tendon", "achilles"],
    "좌골신경": ["sciatic_nerve", "sciatic", "tibial_nerve", "common_fibular_nerve"],
    "sciatic": ["sciatic_nerve", "sciatic", "tibial_nerve", "common_fibular_nerve"],
    "대퇴신경": ["femoral_nerve"],
    "femoral nerve": ["femoral_nerve"],
    "대퇴동맥": ["femoral_artery", "external_iliac_artery"],
    "femoral artery": ["femoral_artery"],
    "대퇴정맥": ["femoral_vein"],
    "하지": ["femur", "patella", "tibia", "fibula", "gluteus_maximus", "gluteus_medius", "gluteus_minimus", "piriformis", "rectus_femoris", "vastus_lateralis", "vastus_medialis", "vastus_intermedius", "sartorius", "biceps_femoris", "semitendinosus", "semimembranosus", "adductor", "gracilis", "gastrocnemius", "soleus", "tibialis_anterior", "calcaneal_tendon", "sciatic_nerve", "femoral_nerve", "femoral_artery"],
    "다리": ["femur", "patella", "tibia", "fibula", "gluteus_maximus", "gluteus_medius", "rectus_femoris", "vastus_lateralis", "vastus_medialis", "vastus_intermedius", "sartorius", "biceps_femoris", "semitendinosus", "semimembranosus", "adductor", "gastrocnemius", "soleus", "tibialis_anterior", "calcaneal_tendon", "sciatic_nerve", "femoral_nerve", "femoral_artery"],
}

# Midline / Unpaired or Bilateral-by-default keywords (when side is not explicitly specified in query)
BILATERAL_OR_MIDLINE_KEYWORDS: Tuple[str, ...] = (
    "뇌", "대뇌", "소뇌", "뇌간", "두개골", "머리", "머리뼈", "전두골", "두정골", "후두골", "측두골",
    "턱뼈", "하악골", "상악골", "저작근", "갑상선", "후두", "기관", "경동맥", "경정맥",
    "심장", "폐", "허파", "횡격막", "가로막", "대동맥", "대정맥", "식도", "갈비뼈", "늑골", "흉곽", "흉골",
    "간", "간장", "위", "위장", "쓸개", "담낭", "췌장", "이자", "비장", "지라", "신장", "콩팥", "부신", "요관", "방광",
    "소장", "십이지장", "공장", "회장", "대장", "결장", "맹장", "직장", "소화기관", "소화기", "내장", "장기",
    "복직근", "복근", "복벽", "외복사근", "내복사근", "복횡근", "장요근", "대요근",
    "척추", "경추", "목뼈", "흉추", "등뼈", "요추", "허리뼈", "천골", "엉치뼈", "미골", "꼬리뼈", "골반", "장골", "관골", "척수", "척추기립근", "기립근",
    "brain", "cerebrum", "cerebellum", "brainstem", "skull", "mandible", "thyroid", "trachea",
    "heart", "lung", "lungs", "diaphragm", "aorta", "vena cava", "esophagus", "rib", "ribs", "sternum",
    "liver", "stomach", "gallbladder", "pancreas", "spleen", "kidney", "bladder",
    "small intestine", "duodenum", "jejunum", "ileum", "large intestine", "colon", "cecum", "rectum",
    "rectus abdominis", "spine", "lumbar", "sacrum", "pelvis", "spinal cord", "erector spinae",
)

# Reviewed Clinical & Educational Procedure Templates
# Grounded in SOT-01..SOT-04 and anchored to surface landmarks in structures-manifest.json
PROCEDURE_TEMPLATES: Dict[str, Dict[str, Any]] = {
    "proc_subscap_axillary_r": {
        "id": "proc_subscap_axillary_r",
        "titleKo": "우측 견갑하근 외측연(액와 후벽) 골면 기준 안전 접근 템플릿",
        "titleEn": "Right Subscapularis Lateral Border (Axillary Posterior Wall) Safe Approach",
        "side": "right",
        "targetStructureIds": ["subscapularis_r", "subscapularis_insertion_r", "subscapularis_origin_r"],
        "sotReferences": ["[SOT-01]", "[SOT-02]", "[SOT-03]", "[SOT-04]"],
        "clinicalSummaryKo": (
            "견갑하근은 견갑골 전면(견갑하와)과 흉곽 사이에 깊이 위치하므로 후면에서는 견갑골 몸통에 가려지고 "
            "전면에서는 대흉근·소흉근 및 액와 신경·혈관 다발이 위치합니다. 따라서 표층 근육(승모근·극상근·삼각근·대흉근)을 "
            "반투명화하여 3D 공간 관계를 먼저 확인하고, 액와 후벽(견갑골 외측연 앞면)에서 견갑골 골면을 기준으로 접근 경로를 설명합니다."
        ),
        "safetyDisclaimerKo": (
            "[교육·설명용 3D 가이드] 본 템플릿의 3D 벡터와 표면 경혈/랜드마크는 Z-Anatomy 표준 인체 모델 위의 교육용 시각화이며, "
            "실제 환자의 체형·견갑골 위치·초음파/촉진 소견을 대체하는 자율 시술 처방이 아닙니다."
        ),
        "recommendedCamera": {
            "position": [-0.36, 1.36, 0.34],
            "target": [-0.11, 1.34, -0.04],
            "up": [0.0, 1.0, 0.0],
            "labelKo": "우측 전외측(Anterolateral) 견갑하근 관찰 시점",
        },
        "guideVectors": [
            {
                "id": "vec_subscap_lateral_safe_r",
                "labelKo": "견갑하근 외측연 골면 지향 교육용 가이드 벡터",
                "type": "safe_educational_vector",
                "entryPositionThreeJs": [-0.205, 1.295, 0.025],
                "targetPositionThreeJs": [-0.12818, 1.34275, -0.05128],
                "targetLandmarkId": "lm_subscap_lateral_trp_r",
                "colorHex": "#10b981",
                "noteKo": "액와 중앙(액와동맥·완신경총)을 피해 견갑골 외측연에서 견갑하와 골면 방향으로 향하는 교육용 방향 표시",
            },
            {
                "id": "vec_axillary_hazard_zone_r",
                "labelKo": "액와 신경·혈관 다발(Axillary Artery & Plexus) 회피 구역",
                "type": "hazard_zone",
                "centerPositionThreeJs": [-0.1362, 1.36537, -0.00936],
                "radiusMeters": 0.022,
                "targetLandmarkId": "hazard_axillary_neurovascular_r",
                "colorHex": "#ef4444",
                "noteKo": "액와 중앙부 심부 침습 금지 구역 (액와동맥·정맥 및 완신경총 주행)",
            },
        ],
        "landmarkIds": [
            "lm_subscap_origin_r",
            "lm_lesser_tubercle_r",
            "lm_subscap_lateral_trp_r",
            "acupoint_SI11_r",
            "acupoint_LI15_r",
            "hazard_axillary_neurovascular_r",
        ],
        "baseStructurePatch": {
            "subscapularis_r": {"visible": True, "opacity": 1.0, "highlighted": True, "colorHex": "#ef4444", "outline": True},
            "subscapularis_origin_r": {"visible": True, "opacity": 0.95, "highlighted": True, "colorHex": "#f59e0b", "outline": False},
            "subscapularis_insertion_r": {"visible": True, "opacity": 0.95, "highlighted": True, "colorHex": "#f59e0b", "outline": False},
            "trapezius_descending_r": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "trapezius_transverse_r": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "trapezius_ascending_r": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "supraspinatus_r": {"visible": True, "opacity": 0.24, "highlighted": False, "outline": False},
            "deltoid_clavicular_r": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "deltoid_acromial_r": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "deltoid_spinal_r": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "pectoralis_major_r": {"visible": True, "opacity": 0.15, "highlighted": False, "outline": False},
            "pectoralis_minor_r": {"visible": True, "opacity": 0.20, "highlighted": False, "outline": False},
            "serratus_anterior_r": {"visible": True, "opacity": 0.20, "highlighted": False, "outline": False},
            "latissimus_dorsi_r": {"visible": True, "opacity": 0.22, "highlighted": False, "outline": False},
            "teres_major_r": {"visible": True, "opacity": 0.35, "highlighted": False, "outline": False},
            "biceps_long_head_r": {"visible": True, "opacity": 0.25, "highlighted": False, "outline": False},
            "biceps_short_head_r": {"visible": True, "opacity": 0.25, "highlighted": False, "outline": False},
            "coracobrachialis_r": {"visible": True, "opacity": 0.25, "highlighted": False, "outline": False},
            "scapula_r": {"visible": True, "opacity": 0.96, "highlighted": False, "outline": False},
            "humerus_r": {"visible": True, "opacity": 0.92, "highlighted": False, "outline": False},
            "clavicle_r": {"visible": True, "opacity": 0.85, "highlighted": False, "outline": False},
            "axillary_artery_r": {"visible": True, "opacity": 1.0, "highlighted": True, "colorHex": "#dc2626", "outline": False},
            "subscapular_artery_r": {"visible": True, "opacity": 1.0, "highlighted": False, "outline": False},
            "axillary_nerve_r": {"visible": True, "opacity": 1.0, "highlighted": True, "colorHex": "#facc15", "outline": False},
            "superior_subscapular_nerve_r": {"visible": True, "opacity": 1.0, "highlighted": False, "outline": False},
            "inferior_subscapular_nerve_r": {"visible": True, "opacity": 1.0, "highlighted": False, "outline": False},
        },
        "steps": [
            {
                "stepIndex": 0,
                "progressRange": [0.0, 0.20],
                "titleKo": "1단계: 표층 근육 반투명화 및 심부 견갑하근 위치 확인",
                "descriptionKo": (
                    "승모근(상·중·하), 극상근, 삼각근, 대흉근을 반투명하게 조절하여 견갑골 전면(견갑하와)에 위치한 "
                    "우측 견갑하근(Subscapularis)의 전체 형태를 노출합니다. [SOT-01, SOT-02]"
                ),
                "activeLandmarks": ["lm_subscap_origin_r", "lm_lesser_tubercle_r"],
                "vectorProgress": 0.0,
            },
            {
                "stepIndex": 1,
                "progressRange": [0.20, 0.45],
                "titleKo": "2단계: 기시부(견갑하와) 및 정지부(상완골 소결절) 주행 확인",
                "descriptionKo": (
                    "견갑골 전면 오목면(견갑하와)에서 기시하여 외측으로 수렴한 뒤 상완골 근위부 전면 소결절(Lesser tubercle)에 "
                    "부착하는 다우상 섬유 주행과 내회전·관절두 안정화 기전을 설명합니다. [SOT-02, SOT-03]"
                ),
                "activeLandmarks": ["lm_subscap_origin_r", "lm_lesser_tubercle_r", "acupoint_LI15_r"],
                "vectorProgress": 0.25,
            },
            {
                "stepIndex": 2,
                "progressRange": [0.45, 0.70],
                "titleKo": "3단계: 액와 신경·혈관 다발(Axillary Bundle) 회피 구역 확인",
                "descriptionKo": (
                    "견갑하근 전면 내측을 지나는 액와동맥(Axillary artery) 및 액와신경/견갑하신경의 위치를 확인하고, "
                    "액와 정중앙 심부로 향하는 위험 방향을 회피해야 함을 시각적으로 안내합니다. [SOT-04]"
                ),
                "activeLandmarks": ["hazard_axillary_neurovascular_r", "lm_subscap_lateral_trp_r"],
                "vectorProgress": 0.55,
            },
            {
                "stepIndex": 3,
                "progressRange": [0.70, 0.90],
                "titleKo": "4단계: 견갑골 외측연(액와 후벽) 골면 기준 안전 접근 설명",
                "descriptionKo": (
                    "상완 외전 상태에서 대원근·광배근과 견갑골 외측연 사이(액와 후벽)를 촉진하고, 흉강이 아닌 "
                    "견갑골 늑골면(골면)을 향해 비스듬히 접근하는 교육용 안전 경로를 시연합니다. [SOT-03, SOT-04]"
                ),
                "activeLandmarks": ["lm_subscap_lateral_trp_r", "hazard_axillary_neurovascular_r"],
                "vectorProgress": 1.0,
            },
            {
                "stepIndex": 4,
                "progressRange": [0.90, 1.00],
                "titleKo": "5단계: 협조 경혈(천종 SI11 · 견우 LI15) 및 외회전 가동성 회복 안내",
                "descriptionKo": (
                    "견갑골 후면의 천종혈(SI11, 극하와 중앙)과 전면 외측의 견우혈(LI15, 견봉 전하방)을 함께 표시하여 "
                    "전·후면 회전근개 균형 치료와 시술 후 점진적 외회전 스트레칭 계획을 설명합니다. [SOT-03, SOT-04]"
                ),
                "activeLandmarks": [
                    "lm_subscap_origin_r",
                    "lm_lesser_tubercle_r",
                    "lm_subscap_lateral_trp_r",
                    "acupoint_SI11_r",
                    "acupoint_LI15_r",
                ],
                "vectorProgress": 1.0,
            },
        ],
    },
    "proc_subscap_lesser_tubercle_r": {
        "id": "proc_subscap_lesser_tubercle_r",
        "titleKo": "우측 상완골 소결절(견갑하근 정지부) 및 견우혈(LI15) 전면 설명 템플릿",
        "titleEn": "Right Subscapularis Insertion (Lesser Tubercle) & LI15 Anterior Guide",
        "side": "right",
        "targetStructureIds": ["subscapularis_r", "subscapularis_insertion_r"],
        "sotReferences": ["[SOT-01]", "[SOT-02]", "[SOT-04]"],
        "clinicalSummaryKo": (
            "전면 삼각근과 대흉근을 반투명하게 하여 상완골 소결절(Lesser tubercle)에 부착하는 견갑하근 건(Tendon) 정지부와 "
            "이두근 장두건 구(Bicipital groove), 견우혈(LI15)의 해부학적 인접 관계를 명확히 보여줍니다."
        ),
        "safetyDisclaimerKo": (
            "[교육·설명용 3D 가이드] Z-Anatomy 표준 인체 모델 기반의 시각 자료이며, 실제 환자 시술 시 촉진 및 초음파 확인이 필수입니다."
        ),
        "recommendedCamera": {
            "position": [-0.22, 1.38, 0.36],
            "target": [-0.15, 1.36, -0.02],
            "up": [0.0, 1.0, 0.0],
            "labelKo": "우측 전면(Anterior) 소결절 정지부 관찰 시점",
        },
        "guideVectors": [
            {
                "id": "vec_lesser_tubercle_ant_r",
                "labelKo": "상완골 소결절 정지부 전면 촉진·접근 방향",
                "type": "safe_educational_vector",
                "entryPositionThreeJs": [-0.185, 1.395, 0.055],
                "targetPositionThreeJs": [-0.16954, 1.38246, -0.00189],
                "targetLandmarkId": "lm_lesser_tubercle_r",
                "colorHex": "#06b6d4",
                "noteKo": "상완 외회전 시 전면으로 노출되는 소결절(Lesser tubercle) 정지부 방향",
            }
        ],
        "landmarkIds": [
            "lm_lesser_tubercle_r",
            "acupoint_LI15_r",
            "hazard_axillary_neurovascular_r",
        ],
        "baseStructurePatch": {
            "subscapularis_r": {"visible": True, "opacity": 1.0, "highlighted": True, "colorHex": "#ef4444", "outline": True},
            "subscapularis_insertion_r": {"visible": True, "opacity": 1.0, "highlighted": True, "colorHex": "#f59e0b", "outline": True},
            "deltoid_clavicular_r": {"visible": True, "opacity": 0.16, "highlighted": False, "outline": False},
            "deltoid_acromial_r": {"visible": True, "opacity": 0.16, "highlighted": False, "outline": False},
            "pectoralis_major_r": {"visible": True, "opacity": 0.14, "highlighted": False, "outline": False},
            "pectoralis_minor_r": {"visible": True, "opacity": 0.22, "highlighted": False, "outline": False},
            "biceps_long_head_r": {"visible": True, "opacity": 0.45, "highlighted": False, "outline": False},
            "biceps_short_head_r": {"visible": True, "opacity": 0.25, "highlighted": False, "outline": False},
            "coracobrachialis_r": {"visible": True, "opacity": 0.25, "highlighted": False, "outline": False},
            "trapezius_descending_r": {"visible": True, "opacity": 0.22, "highlighted": False, "outline": False},
            "supraspinatus_r": {"visible": True, "opacity": 0.30, "highlighted": False, "outline": False},
        },
        "steps": [
            {
                "stepIndex": 0,
                "progressRange": [0.0, 0.33],
                "titleKo": "1단계: 전면 삼각근·대흉근 반투명화",
                "descriptionKo": "어깨 전면을 덮는 삼각근(전·측부)과 대흉근을 반투명하게 낮춰 상완골두 전면 구조를 노출합니다.",
                "activeLandmarks": ["acupoint_LI15_r"],
                "vectorProgress": 0.0,
            },
            {
                "stepIndex": 1,
                "progressRange": [0.33, 0.66],
                "titleKo": "2단계: 상완골 소결절(Lesser Tubercle) 정지부 확인",
                "descriptionKo": "견갑하근 건이 부착하는 상완골 소결절 정지부와 외측의 이두근 장두건 위치를 비교합니다. [SOT-02]",
                "activeLandmarks": ["lm_lesser_tubercle_r", "acupoint_LI15_r"],
                "vectorProgress": 0.6,
            },
            {
                "stepIndex": 2,
                "progressRange": [0.66, 1.00],
                "titleKo": "3단계: 전면 압통점 및 견우혈(LI15) 연계 설명",
                "descriptionKo": "견우혈(LI15)과 소결절 정지부의 입체적 위치 차이를 환자에게 직관적으로 설명합니다. [SOT-04]",
                "activeLandmarks": ["lm_lesser_tubercle_r", "acupoint_LI15_r", "hazard_axillary_neurovascular_r"],
                "vectorProgress": 1.0,
            },
        ],
    },
    "proc_posterior_sits_si11_r": {
        "id": "proc_posterior_sits_si11_r",
        "titleKo": "우측 전·후면 회전근개(견갑하근 vs 극상·극하근) 및 천종혈(SI11) 입체 비교",
        "titleEn": "Right Anterior vs Posterior Rotator Cuff & SI11 Acupoint Comparison",
        "side": "right",
        "targetStructureIds": ["subscapularis_r", "supraspinatus_r", "infraspinatus_r", "teres_minor_r"],
        "sotReferences": ["[SOT-01]", "[SOT-02]", "[SOT-03]", "[SOT-04]"],
        "clinicalSummaryKo": (
            "환자가 흔히 혼동하는 '등 뒤 날개뼈 통증(천종혈 SI11 · 극하근)'과 '날개뼈 앞면 심부 통증(견갑하근)'의 차이를 "
            "승모근과 후면 삼각근을 반투명하게 하여 견갑골 양면에서 동시에 비교 설명합니다."
        ),
        "safetyDisclaimerKo": (
            "[교육·설명용 3D 가이드] Z-Anatomy 표준 인체 모델 기반의 시각 자료이며, 실제 환자 시술 시 촉진 확인이 필수입니다."
        ),
        "recommendedCamera": {
            "position": [-0.32, 1.42, -0.34],
            "target": [-0.11, 1.34, -0.05],
            "up": [0.0, 1.0, 0.0],
            "labelKo": "우측 후외측(Posterolateral) 견갑골 양면 비교 시점",
        },
        "guideVectors": [
            {
                "id": "vec_si11_infraspinatus_r",
                "labelKo": "천종혈(SI11) 극하와 골면 방향 가이드 표시",
                "type": "safe_educational_vector",
                "entryPositionThreeJs": [-0.130, 1.315, -0.145],
                "targetPositionThreeJs": [-0.1233, 1.33501, -0.08522],
                "targetLandmarkId": "acupoint_SI11_r",
                "colorHex": "#3b82f6",
                "noteKo": "견갑골 후면 극하와 중앙(천종혈 SI11) 위치 표시 — 견갑골을 사이에 두고 전면 견갑하근과 마주 봄",
            }
        ],
        "landmarkIds": [
            "acupoint_SI11_r",
            "lm_subscap_origin_r",
            "lm_subscap_lateral_trp_r",
        ],
        "baseStructurePatch": {
            "subscapularis_r": {"visible": True, "opacity": 1.0, "highlighted": True, "colorHex": "#ef4444", "outline": True},
            "supraspinatus_r": {"visible": True, "opacity": 0.45, "highlighted": False, "outline": False},
            "infraspinatus_r": {"visible": True, "opacity": 0.55, "highlighted": False, "outline": False},
            "teres_minor_r": {"visible": True, "opacity": 0.65, "highlighted": False, "outline": False},
            "trapezius_descending_r": {"visible": True, "opacity": 0.15, "highlighted": False, "outline": False},
            "trapezius_transverse_r": {"visible": True, "opacity": 0.15, "highlighted": False, "outline": False},
            "trapezius_ascending_r": {"visible": True, "opacity": 0.15, "highlighted": False, "outline": False},
            "deltoid_spinal_r": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "deltoid_acromial_r": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "scapula_r": {"visible": True, "opacity": 0.55, "highlighted": False, "outline": False},
        },
        "steps": [
            {
                "stepIndex": 0,
                "progressRange": [0.0, 0.5],
                "titleKo": "1단계: 승모근·삼각근 반투명화 및 후면 회전근개(극상근·극하근) 확인",
                "descriptionKo": "승모근을 반투명하게 낮추어 견갑극 위쪽의 극상근과 아래쪽의 극하근·천종혈(SI11)을 확인합니다.",
                "activeLandmarks": ["acupoint_SI11_r"],
                "vectorProgress": 0.5,
            },
            {
                "stepIndex": 1,
                "progressRange": [0.5, 1.0],
                "titleKo": "2단계: 견갑골 반투명화 및 전면 견갑하근과의 전·후면 길항 관계 비교",
                "descriptionKo": "견갑골을 반투명(0.55)하게 하여 극하근(외회전) 바로 앞면(늑골면)에 견갑하근(내회전)이 마주 보고 있음을 입체적으로 설명합니다.",
                "activeLandmarks": ["acupoint_SI11_r", "lm_subscap_origin_r", "lm_subscap_lateral_trp_r"],
                "vectorProgress": 1.0,
            },
        ],
    },
    "proc_subscap_axillary_l": {
        "id": "proc_subscap_axillary_l",
        "titleKo": "좌측 견갑하근 외측연(액와 후벽) 골면 기준 안전 접근 템플릿",
        "titleEn": "Left Subscapularis Lateral Border Safe Approach",
        "side": "left",
        "targetStructureIds": ["subscapularis_l", "subscapularis_insertion_l", "subscapularis_origin_l"],
        "sotReferences": ["[SOT-01]", "[SOT-02]", "[SOT-03]", "[SOT-04]"],
        "clinicalSummaryKo": (
            "좌측 표층 근육(승모근·극상근·삼각근·대흉근)을 반투명하게 조절하고 좌측 견갑하근(Subscapularis.l)을 강조하여 "
            "우측과 대칭 비교하거나 좌측 병변을 설명할 때 사용하는 템플릿입니다."
        ),
        "safetyDisclaimerKo": (
            "[교육·설명용 3D 가이드] Z-Anatomy 표준 인체 모델 기반의 시각 자료이며, 실제 환자 시술 시 촉진 확인이 필수입니다."
        ),
        "recommendedCamera": {
            "position": [0.36, 1.36, 0.34],
            "target": [0.11, 1.34, -0.04],
            "up": [0.0, 1.0, 0.0],
            "labelKo": "좌측 전외측(Anterolateral) 견갑하근 관찰 시점",
        },
        "guideVectors": [
            {
                "id": "vec_subscap_lateral_safe_l",
                "labelKo": "좌측 견갑하근 외측연 골면 지향 교육용 가이드 벡터",
                "type": "safe_educational_vector",
                "entryPositionThreeJs": [0.205, 1.295, 0.025],
                "targetPositionThreeJs": [0.12818, 1.34275, -0.05128],
                "targetLandmarkId": "lm_subscap_lateral_trp_l",
                "colorHex": "#10b981",
                "noteKo": "좌측 액와 중앙 신경·혈관 다발을 피해 견갑골 외측연에서 견갑하와 골면 방향으로 향하는 교육용 방향 표시",
            }
        ],
        "landmarkIds": [
            "lm_subscap_origin_l",
            "lm_lesser_tubercle_l",
            "lm_subscap_lateral_trp_l",
            "acupoint_SI11_l",
            "acupoint_LI15_l",
            "hazard_axillary_neurovascular_l",
        ],
        "baseStructurePatch": {
            "subscapularis_l": {"visible": True, "opacity": 1.0, "highlighted": True, "colorHex": "#ef4444", "outline": True},
            "subscapularis_origin_l": {"visible": True, "opacity": 0.95, "highlighted": True, "colorHex": "#f59e0b", "outline": False},
            "subscapularis_insertion_l": {"visible": True, "opacity": 0.95, "highlighted": True, "colorHex": "#f59e0b", "outline": False},
            "trapezius_descending_l": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "trapezius_transverse_l": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "trapezius_ascending_l": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "supraspinatus_l": {"visible": True, "opacity": 0.24, "highlighted": False, "outline": False},
            "deltoid_clavicular_l": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "deltoid_acromial_l": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "deltoid_spinal_l": {"visible": True, "opacity": 0.18, "highlighted": False, "outline": False},
            "pectoralis_major_l": {"visible": True, "opacity": 0.15, "highlighted": False, "outline": False},
            "pectoralis_minor_l": {"visible": True, "opacity": 0.20, "highlighted": False, "outline": False},
        },
        "steps": [
            {
                "stepIndex": 0,
                "progressRange": [0.0, 0.5],
                "titleKo": "1단계: 좌측 표층 근육 반투명화 및 견갑하근 노출",
                "descriptionKo": "좌측 승모근, 극상근, 삼각근, 대흉근을 반투명하게 조절하여 좌측 견갑하근을 노출합니다.",
                "activeLandmarks": ["lm_subscap_origin_l", "lm_lesser_tubercle_l"],
                "vectorProgress": 0.3,
            },
            {
                "stepIndex": 1,
                "progressRange": [0.5, 1.0],
                "titleKo": "2단계: 좌측 견갑골 외측연 기준 안전 경로 및 랜드마크 확인",
                "descriptionKo": "좌측 액와 신경·혈관 주의 구역을 회피하여 견갑골 늑골면 방향으로 접근하는 경로를 설명합니다.",
                "activeLandmarks": ["lm_subscap_lateral_trp_l", "hazard_axillary_neurovascular_l", "acupoint_SI11_l", "acupoint_LI15_l"],
                "vectorProgress": 1.0,
            },
        ],
    },
}


class SessionSceneState:
    """Holds the authoritative state, undo history, and active WebSocket clients for one session."""

    def __init__(self, session_id: str, manifest: Dict[str, Any]) -> None:
        self.session_id = session_id
        self.manifest = manifest
        self.revision: int = 1
        self.updated_at: float = time.time()
        self.last_command_id: Optional[str] = None
        self.processed_commands: Dict[str, Dict[str, Any]] = {}
        self.undo_stack: List[Dict[str, Any]] = []
        self.max_undo: int = 30

        # Active WebSocket clients (browser 3D viewers)
        self.websockets: List[WebSocket] = []
        # Pending ACK futures keyed by commandId
        self.pending_acks: Dict[str, asyncio.Future] = {}
        # Pending capture futures keyed by captureId
        self.pending_captures: Dict[str, asyncio.Future] = {}

        # Initialize default structure states from manifest
        self.structures: Dict[str, Dict[str, Any]] = {}
        self.reset_structures_to_default()

        # Default camera on startup & reset: whole_body_front so user sees the full 3D human body
        self.camera: Dict[str, Any] = copy.deepcopy(CAMERA_PRESETS["whole_body_front"])
        self.selected_structure_ids: List[str] = []
        self.landmarks_visible: bool = False
        self.active_landmark_ids: List[str] = [
            "lm_subscap_origin_r",
            "lm_lesser_tubercle_r",
            "lm_subscap_lateral_trp_r",
            "acupoint_SI11_r",
            "acupoint_LI15_r",
            "hazard_axillary_neurovascular_r",
        ]
        self.active_procedure: Optional[Dict[str, Any]] = None
        self.last_explanation_card: Optional[Dict[str, Any]] = None

    @property
    def camera_position(self) -> List[float]:
        return list(self.camera.get("position", [0.0, 0.92, 2.35]))

    @camera_position.setter
    def camera_position(self, value: List[float]) -> None:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            self.camera["position"] = [round(float(x), 5) for x in value[:3]]

    @property
    def camera_target(self) -> List[float]:
        return list(self.camera.get("target", [0.0, 0.90, 0.0]))

    @camera_target.setter
    def camera_target(self, value: List[float]) -> None:
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            self.camera["target"] = [round(float(x), 5) for x in value[:3]]

    def reset_structures_to_default(self) -> None:
        self.structures = {}
        for item in self.manifest.get("structures", []):
            sid = item["id"]
            is_footprint = item.get("category") == "insertion_footprint"
            self.structures[sid] = {
                "visible": bool(item.get("defaultVisible", True)),
                "opacity": float(item.get("defaultOpacity", 0.85 if is_footprint else 1.0)),
                "highlighted": False,
                "colorHex": None,
                "outline": False,
            }

    def sync_with_manifest(self, manifest: Dict[str, Any]) -> None:
        """Synchronizes session structures when structures-manifest.json is hot-reloaded on disk."""
        self.manifest = manifest
        valid_ids = set()
        for item in manifest.get("structures", []):
            sid = item["id"]
            valid_ids.add(sid)
            if sid not in self.structures:
                is_footprint = item.get("category") == "insertion_footprint"
                self.structures[sid] = {
                    "visible": bool(item.get("defaultVisible", True)),
                    "opacity": float(item.get("defaultOpacity", 0.85 if is_footprint else 1.0)),
                    "highlighted": False,
                    "colorHex": None,
                    "outline": False,
                }
        for old_id in list(self.structures.keys()):
            if old_id not in valid_ids:
                self.structures.pop(old_id, None)

    def snapshot_for_undo(self) -> Dict[str, Any]:
        return {
            "structures": copy.deepcopy(self.structures),
            "camera": copy.deepcopy(self.camera),
            "selected_structure_ids": copy.deepcopy(self.selected_structure_ids),
            "landmarks_visible": self.landmarks_visible,
            "active_landmark_ids": copy.deepcopy(self.active_landmark_ids),
            "active_procedure": copy.deepcopy(self.active_procedure),
            "last_explanation_card": copy.deepcopy(self.last_explanation_card),
        }

    def restore_snapshot(self, snap: Dict[str, Any]) -> None:
        self.structures = copy.deepcopy(snap["structures"])
        self.camera = copy.deepcopy(snap["camera"])
        self.selected_structure_ids = copy.deepcopy(snap["selected_structure_ids"])
        self.landmarks_visible = bool(snap["landmarks_visible"])
        self.active_landmark_ids = copy.deepcopy(snap["active_landmark_ids"])
        self.active_procedure = copy.deepcopy(snap["active_procedure"])
        self.last_explanation_card = copy.deepcopy(snap.get("last_explanation_card"))

    def to_dict(self, compact: bool = False) -> Dict[str, Any]:
        """Serialize current scene state."""
        non_default_structures = {}
        highlighted_ids = []
        transparent_ids = []
        hidden_ids = []
        for sid, st in self.structures.items():
            if st.get("highlighted"):
                highlighted_ids.append(sid)
            if not st.get("visible", True):
                hidden_ids.append(sid)
            elif st.get("opacity", 1.0) < 0.98:
                transparent_ids.append({"id": sid, "opacity": round(float(st["opacity"]), 3)})
            if compact:
                if (
                    st.get("highlighted")
                    or not st.get("visible", True)
                    or abs(float(st.get("opacity", 1.0)) - 1.0) > 1e-3
                    or st.get("colorHex")
                    or st.get("outline")
                ):
                    non_default_structures[sid] = st

        return {
            "sessionId": self.session_id,
            "revision": self.revision,
            "updatedAt": self.updated_at,
            "lastCommandId": self.last_command_id,
            "connectedViewerCount": len(self.websockets),
            "camera": self.camera,
            "cameraPresets": CAMERA_PRESETS,
            "selectedStructureIds": self.selected_structure_ids,
            "highlightedStructureIds": highlighted_ids,
            "transparentStructuresSummary": transparent_ids,
            "hiddenStructureIds": hidden_ids,
            "landmarksVisible": self.landmarks_visible,
            "activeLandmarkIds": self.active_landmark_ids,
            "activeProcedure": self.active_procedure,
            "lastExplanationCard": self.last_explanation_card,
            "undoDepth": len(self.undo_stack),
            "structures": non_default_structures if compact else self.structures,
        }


class AnatomySceneService:
    """Singleton service managing structures-manifest.json (with automatic disk hot-reload), sessions, MCP tools, and WebSocket viewers."""

    def __init__(self) -> None:
        self._manifest: Dict[str, Any] = {}
        self.provenance: Dict[str, Any] = {}
        self._manifest_mtime: float = 0.0
        self._provenance_mtime: float = 0.0
        self.structures_by_id: Dict[str, Dict[str, Any]] = {}
        self.landmarks_by_id: Dict[str, Dict[str, Any]] = {}
        self.groups: Dict[str, List[str]] = {}
        self.sessions: Dict[str, SessionSceneState] = {}

        # Initial load from disk
        self.reload_manifest_if_needed(force=True)
        # Create default session immediately
        self.get_or_create_session("default")

    @property
    def manifest(self) -> Dict[str, Any]:
        self.reload_manifest_if_needed()
        return self._manifest

    @manifest.setter
    def manifest(self, value: Dict[str, Any]) -> None:
        self._manifest = value
        self._rebuild_indices_from_manifest(value)

    def _rebuild_indices_from_manifest(self, manifest_data: Dict[str, Any]) -> None:
        structures = manifest_data.get("structures", [])
        self.structures_by_id = {s["id"]: s for s in structures if "id" in s}
        self.landmarks_by_id = {
            lm["id"]: lm for lm in manifest_data.get("landmarks", []) if "id" in lm
        }
        groups_map: Dict[str, List[str]] = {}
        for s in structures:
            sid = s.get("id")
            if not sid:
                continue
            for key_field in ("group", "category", "region", "system"):
                g_val = s.get(key_field)
                if g_val:
                    g_norm = str(g_val).strip()
                    if sid not in groups_map.setdefault(g_norm, []):
                        groups_map[g_norm].append(sid)
        self.groups = groups_map

        # Sync existing sessions so newly added whole-body structures are immediately tracked
        for session in self.sessions.values():
            session.sync_with_manifest(manifest_data)

    def reload_manifest_if_needed(self, force: bool = False) -> bool:
        """
        Checks STRUCTURES_MANIFEST_PATH.stat().st_mtime and automatically reloads
        structures_by_id, landmarks_by_id, and groups if updated on disk.
        """
        reloaded = False
        try:
            if STRUCTURES_MANIFEST_PATH.exists():
                mtime = STRUCTURES_MANIFEST_PATH.stat().st_mtime
                if force or mtime != self._manifest_mtime or not self._manifest:
                    new_manifest = _load_json(STRUCTURES_MANIFEST_PATH)
                    if isinstance(new_manifest, dict) and "structures" in new_manifest:
                        self._manifest = new_manifest
                        self._manifest_mtime = mtime
                        self._rebuild_indices_from_manifest(new_manifest)
                        reloaded = True
        except Exception:
            # If file is mid-write by Blender export, keep existing in-memory manifest until next check
            pass

        try:
            if PROVENANCE_PATH.exists():
                p_mtime = PROVENANCE_PATH.stat().st_mtime
                if force or p_mtime != self._provenance_mtime or not self.provenance:
                    self.provenance = _load_json(PROVENANCE_PATH)
                    self._provenance_mtime = p_mtime
        except Exception:
            pass

        return reloaded

    def get_or_create_session(self, session_id: str = "default") -> SessionSceneState:
        self.reload_manifest_if_needed()
        if not session_id:
            session_id = "default"
        if session_id not in self.sessions:
            self.sessions[session_id] = SessionSceneState(session_id, self._manifest)
        return self.sessions[session_id]

    # ------------------------------------------------------------------
    # Automatic 3D Bounding-Box Camera Framing
    # ------------------------------------------------------------------
    def compute_camera_for_structures(
        self,
        structure_ids: List[str],
        prefer_posterior: Optional[bool] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Computes an optimal Three.js Y-up camera position and target that frames one or more
        anatomical structures using their `boundsThreeJsYUp` bounding boxes in structures-manifest.json.
        """
        self.reload_manifest_if_needed()
        if not structure_ids:
            return None

        resolved_ids: List[str] = []
        for raw_id in structure_ids:
            if not raw_id:
                continue
            if raw_id in self.structures_by_id:
                if raw_id not in resolved_ids:
                    resolved_ids.append(raw_id)
            else:
                for exp_id in self.expand_term_to_structure_ids(str(raw_id)):
                    if exp_id in self.structures_by_id and exp_id not in resolved_ids:
                        resolved_ids.append(exp_id)

        if not resolved_ids:
            return None

        mins: List[List[float]] = []
        maxs: List[List[float]] = []
        posterior_hits = 0
        anterior_hits = 0

        for sid in resolved_ids:
            s = self.structures_by_id.get(sid)
            if not s:
                continue
            bounds = s.get("boundsThreeJsYUp") or {}
            b_min = bounds.get("min")
            b_max = bounds.get("max")
            b_ctr = bounds.get("center")
            if isinstance(b_min, list) and len(b_min) == 3 and isinstance(b_max, list) and len(b_max) == 3:
                mins.append([float(b_min[0]), float(b_min[1]), float(b_min[2])])
                maxs.append([float(b_max[0]), float(b_max[1]), float(b_max[2])])
            elif isinstance(b_ctr, list) and len(b_ctr) == 3:
                cx, cy, cz = float(b_ctr[0]), float(b_ctr[1]), float(b_ctr[2])
                mins.append([cx - 0.05, cy - 0.05, cz - 0.05])
                maxs.append([cx + 0.05, cy + 0.05, cz + 0.05])

            meta_blob = " ".join(
                [
                    sid.lower(),
                    str(s.get("nameEn", "")).lower(),
                    str(s.get("baseNameEn", "")).lower(),
                    str(s.get("group", "")).lower(),
                    str(s.get("category", "")).lower(),
                    str(s.get("region", "")).lower(),
                ]
            )
            if any(tok in meta_blob for tok in POSTERIOR_STRUCTURE_TOKENS):
                posterior_hits += 1
            if any(tok in meta_blob for tok in ANTERIOR_PREFERRED_TOKENS):
                anterior_hits += 1

        if not mins or not maxs:
            return None

        min_pt = [min(p[i] for p in mins) for i in range(3)]
        max_pt = [max(p[i] for p in maxs) for i in range(3)]
        center = [(min_pt[i] + max_pt[i]) / 2.0 for i in range(3)]

        dx = max_pt[0] - min_pt[0]
        dy = max_pt[1] - min_pt[1]
        dz = max_pt[2] - min_pt[2]
        extent = max(dx, dy, dz, 0.14)

        if prefer_posterior is not None:
            is_posterior = bool(prefer_posterior)
        elif posterior_hits > anterior_hits:
            is_posterior = True
        elif anterior_hits > 0:
            is_posterior = False
        else:
            is_posterior = bool(center[2] < -0.055)

        dist = max(0.42, min(2.35, extent * 2.35))
        camera_target = [round(center[0], 5), round(center[1], 5), round(center[2], 5)]
        camera_position = [
            round(center[0] * 0.6, 5),
            round(center[1] + extent * 0.08, 5),
            round(center[2] + (-dist if is_posterior else dist), 5),
        ]

        return {
            "position": camera_position,
            "target": camera_target,
            "cameraPosition": camera_position,
            "cameraTarget": camera_target,
            "up": [0.0, 1.0, 0.0],
            "fov": 36,
            "isPosterior": is_posterior,
            "extent": round(extent, 5),
        }

    # ------------------------------------------------------------------
    # 1. anatomy.search_structures
    # ------------------------------------------------------------------
    def search_structures(
        self,
        query: str = "",
        side: Optional[str] = None,
        category: Optional[str] = None,
        group: Optional[str] = None,
        region: Optional[str] = None,
        limit: int = 25,
    ) -> Dict[str, Any]:
        self.reload_manifest_if_needed()
        q_raw = (query or "").strip().lower()
        side_norm = (side or "").strip().lower() or None
        cat_norm = (category or "").strip().lower() or None
        grp_norm = (group or "").strip().lower() or None
        reg_norm = (region or "").strip().lower() or None

        # Detect side hints inside Korean/English query if side not explicitly passed
        inferred_side = side_norm
        if not inferred_side:
            if any(tok in q_raw for tok in ["우측", "오른쪽", "오른", "우폐", "right", "_r", ".r"]):
                inferred_side = "right"
            elif any(tok in q_raw for tok in ["좌측", "왼쪽", "왼", "좌폐", "left", "_l", ".l"]):
                inferred_side = "left"

        # Strip side words for core anatomical term matching
        q_clean = q_raw
        for tok in ["우측", "오른쪽", "좌측", "왼쪽", "양측", "양쪽", "right", "left", "both", "bilateral", "근육", "muscle"]:
            q_clean = q_clean.replace(tok, " ").strip()
        q_tokens = [t for t in q_clean.split() if t]

        # Expand query tokens with whole-body stem hints if query matches WHOLE_BODY_KEYWORD_MAP
        stem_hints: List[str] = []
        for kw, stems in WHOLE_BODY_KEYWORD_MAP.items():
            if kw in q_raw or (q_clean and kw in q_clean):
                for st in stems:
                    if st not in stem_hints:
                        stem_hints.append(st.lower())

        scored: List[Tuple[float, Dict[str, Any]]] = []
        for s in self._manifest.get("structures", []):
            s_side = str(s.get("side", "")).lower()
            if side_norm and s_side != side_norm and s_side not in ("center", "midline", "both", "none", ""):
                continue
            if cat_norm and str(s.get("category", "")).lower() != cat_norm:
                continue
            if grp_norm and str(s.get("group", "")).lower() != grp_norm:
                continue
            if reg_norm and str(s.get("region", "")).lower() != reg_norm:
                continue

            score = 0.0
            sid = s["id"].lower()
            sid_base = sid[:-2] if sid.endswith(("_r", "_l")) else sid
            name_ko = str(s.get("nameKo", "")).lower()
            base_ko = str(s.get("baseNameKo", "")).lower()
            name_en = str(s.get("nameEn", "")).lower()
            base_en = str(s.get("baseNameEn", "")).lower()
            aliases = [str(a).lower() for a in s.get("aliases", [])]
            grp = str(s.get("group", "")).lower()
            cat = str(s.get("category", "")).lower()
            reg = str(s.get("region", "")).lower()

            if not q_raw:
                score = 1.0
            else:
                if q_raw == sid or q_raw == name_ko or q_raw == name_en:
                    score += 100.0
                if q_clean and (q_clean == base_ko or q_clean == base_en or q_clean == sid_base):
                    score += 85.0
                if q_clean and (
                    q_clean in base_ko
                    or q_clean in name_ko
                    or q_clean in base_en
                    or q_clean in name_en
                    or q_clean in sid
                ):
                    score += 55.0
                for al in aliases:
                    if q_raw == al or (q_clean and q_clean == al):
                        score += 50.0
                    elif q_clean and q_clean in al:
                        score += 25.0
                for st_hint in stem_hints:
                    if st_hint == sid_base or st_hint == sid:
                        score += 80.0
                    elif sid_base.startswith(st_hint) or st_hint in sid or st_hint in base_en or st_hint in name_en:
                        score += 45.0
                    elif st_hint == grp or st_hint == cat or st_hint == reg:
                        score += 35.0
                for tok in q_tokens:
                    if (
                        tok in base_ko
                        or tok in name_ko
                        or tok in base_en
                        or tok in name_en
                        or tok in sid
                        or tok in grp
                        or tok in cat
                        or tok in reg
                    ):
                        score += 20.0
                    elif any(tok in al for al in aliases):
                        score += 10.0

                if score > 0 and inferred_side:
                    if s_side == inferred_side:
                        score += 30.0
                    elif s_side in ("left", "right") and s_side != inferred_side:
                        score -= 25.0

                # Prefer primary mesh over insertion_footprint when query doesn't mention 기시/정지/origin/insertion
                if (
                    score > 0
                    and cat == "insertion_footprint"
                    and not any(k in q_raw for k in ["기시", "정지", "origin", "insertion", "부착"])
                ):
                    score -= 22.0

            if score > 0:
                scored.append((score, s))

        scored.sort(key=lambda x: (-x[0], x[1]["id"]))
        matches = [
            {
                "id": item["id"],
                "nameKo": item.get("nameKo", item["id"]),
                "nameEn": item.get("nameEn", item["id"]),
                "baseNameKo": item.get("baseNameKo"),
                "side": item.get("side"),
                "category": item.get("category"),
                "group": item.get("group"),
                "region": item.get("region"),
                "defaultOpacity": item.get("defaultOpacity", 1.0),
                "boundsThreeJsYUp": item.get("boundsThreeJsYUp"),
                "sotReference": item.get("sotReference"),
                "clinicalNoteKo": item.get("clinicalNoteKo"),
                "score": round(sc, 1),
            }
            for sc, item in scored[: max(1, min(limit, 200))]
        ]
        return {
            "query": query,
            "sideFilter": side_norm or inferred_side,
            "categoryFilter": cat_norm,
            "groupFilter": grp_norm,
            "regionFilter": reg_norm,
            "totalMatches": len(scored),
            "returnedCount": len(matches),
            "structures": matches,
        }

    def _match_structures_by_stems(
        self,
        stems: List[str],
        side: str = "right",
        include_footprints: bool = False,
    ) -> List[str]:
        """Matches structures in self._manifest using stem prefixes/substrings and side preference."""
        matched_right: List[str] = []
        matched_left: List[str] = []
        matched_midline: List[str] = []

        for s in self._manifest.get("structures", []):
            sid = s.get("id", "")
            if not sid:
                continue
            cat = str(s.get("category", "")).lower()
            if cat == "insertion_footprint" and not include_footprints:
                continue

            sid_low = sid.lower()
            sid_base = sid_low[:-2] if sid_low.endswith(("_r", "_l")) else sid_low
            name_en = str(s.get("nameEn", "")).lower()
            base_en = str(s.get("baseNameEn", "")).lower()
            name_ko = str(s.get("nameKo", "")).lower()
            base_ko = str(s.get("baseNameKo", "")).lower()
            grp = str(s.get("group", "")).lower()
            reg = str(s.get("region", "")).lower()
            aliases = [str(a).lower() for a in s.get("aliases", [])]

            hit = False
            for st in stems:
                st_l = st.lower()
                if (
                    sid_low == st_l
                    or sid_base == st_l
                    or sid_base.startswith(f"{st_l}_")
                    or st_l in sid_base
                    or st_l == grp
                    or st_l == cat
                    or st_l == reg
                    or st_l in base_en
                    or st_l in name_en
                    or st_l == base_ko
                    or st_l in name_ko
                    or any(st_l == al or st_l in al for al in aliases)
                ):
                    hit = True
                    break

            if not hit:
                continue

            s_side = str(s.get("side", "")).lower()
            if s_side == "right" or sid_low.endswith("_r"):
                if sid not in matched_right:
                    matched_right.append(sid)
            elif s_side == "left" or sid_low.endswith("_l"):
                if sid not in matched_left:
                    matched_left.append(sid)
            else:
                if sid not in matched_midline:
                    matched_midline.append(sid)

        if side == "both":
            return matched_midline + matched_right + matched_left
        if side == "left":
            if matched_left:
                return matched_midline + matched_left
            return matched_midline + matched_right
        # side == "right"
        if matched_right:
            return matched_midline + matched_right
        return matched_midline + matched_left

    def expand_term_to_structure_ids(self, term: str, default_side: str = "right") -> List[str]:
        """
        Expands Korean/English anatomical terms, system names, or group names across the whole body
        into exact structure IDs from structures-manifest.json.
        """
        self.reload_manifest_if_needed()
        t = (term or "").strip().lower()
        if not t:
            return []
        if t in self.structures_by_id:
            return [t]

        # Determine side preference
        side = default_side
        explicit_side = False
        if any(w in t for w in ["좌측", "왼쪽", "왼팔", "왼다리", "좌폐", "left", "_l", ".l"]):
            side = "left"
            explicit_side = True
        elif any(w in t for w in ["우측", "오른쪽", "오른팔", "오른다리", "우폐", "right", "_r", ".r"]):
            side = "right"
            explicit_side = True
        elif any(w in t for w in ["양측", "양쪽", "전체", "전신", "both", "bilateral", "all_"]):
            side = "both"
            explicit_side = True

        # Strip side qualifiers to get clean term
        t_clean = t
        for w in ["우측", "오른쪽", "좌측", "왼쪽", "양측", "양쪽", "전신", "전체", "right", "left", "both", "bilateral"]:
            t_clean = t_clean.replace(w, " ").strip()

        if not explicit_side:
            if any(bk in t or (t_clean and bk in t_clean) for bk in BILATERAL_OR_MIDLINE_KEYWORDS):
                side = "both"

        # 1. Check special whole-body system / layer macro-groups
        all_structs = self._manifest.get("structures", [])
        if t in ("all_bones", "골격", "골격계", "뼈", "뼈 전체", "전신 골격", "skeleton", "skeletal") or t_clean in (
            "골격",
            "골격계",
            "뼈",
            "뼈만",
            "skeleton",
        ):
            return [
                s["id"]
                for s in all_structs
                if "bone" in str(s.get("category", "")).lower()
                or "bone" in str(s.get("group", "")).lower()
                or "skeletal" in str(s.get("category", "")).lower()
                or any(
                    b_tok in s["id"].lower()
                    for b_tok in (
                        "skull", "cranium", "frontal", "parietal", "occipital", "temporal", "mandible", "maxilla",
                        "vertebra", "cervical", "thoracic", "lumbar", "sacrum", "coccyx", "spine",
                        "clavicle", "scapula", "sternum", "rib", "humerus", "radius", "ulna",
                        "pelvis", "ilium", "ischium", "pubis", "hip_bone", "femur", "patella", "tibia", "fibula",
                        "carpal", "metacarpal", "tarsal", "metatarsal", "calcaneus", "talus", "phalan",
                    )
                )
            ]

        if t in ("all_muscles", "근육", "근육계", "전신 근육", "근육 전체", "muscles", "muscular") or t_clean in (
            "근육",
            "근육계",
            "근육만",
            "muscles",
        ):
            return [
                s["id"]
                for s in all_structs
                if str(s.get("category", "")).lower() in ("muscle", "rotator_cuff", "muscular")
                or "muscle" in str(s.get("group", "")).lower()
                or "muscle" in str(s.get("nameEn", "")).lower()
            ]

        if t in ("all_organs", "내장", "장기", "내장계", "장기 전체", "오장육부", "viscera", "organs", "internal_organs") or t_clean in (
            "내장",
            "장기",
            "내장만",
            "장기만",
            "내장 기관",
            "오장육부",
            "viscera",
            "organs",
        ):
            return self._match_structures_by_stems(
                [
                    "organ", "viscera", "digestive", "respiratory", "urogenital", "cardiovascular_organ",
                    "heart", "lung", "trachea", "bronchus", "esophagus", "diaphragm", "thyroid", "larynx",
                    "liver", "stomach", "gallbladder", "pancreas", "spleen", "kidney", "adrenal", "ureter",
                    "bladder", "urinary_bladder", "small_intestine", "duodenum", "jejunum", "ileum",
                    "large_intestine", "colon", "cecum", "appendix", "rectum",
                ],
                side="both",
            )

        if t in ("all_nerves", "신경", "신경계", "전신 신경", "nerves", "nervous_system") or t_clean in (
            "신경",
            "신경계",
            "신경만",
            "nerves",
        ):
            return self._match_structures_by_stems(
                [
                    "nerve", "brain", "cerebrum", "cerebellum", "brainstem", "spinal_cord",
                    "plexus", "sciatic", "femoral_nerve", "tibial_nerve", "fibular_nerve",
                    "median_nerve", "radial_nerve", "ulnar_nerve", "axillary_nerve", "subscapular_nerve",
                ],
                side="both",
            )

        if t in ("all_vessels", "순환계", "혈관", "혈관계", "전신 혈관", "vessels", "cardiovascular") or t_clean in (
            "순환계",
            "혈관",
            "혈관계",
            "혈관만",
            "vessels",
        ):
            return self._match_structures_by_stems(
                [
                    "artery", "vein", "vessel", "vascular", "heart", "aorta", "vena_cava",
                    "carotid", "jugular", "subclavian", "axillary_artery", "brachial_artery",
                    "iliac", "femoral_artery", "femoral_vein", "popliteal", "portal", "mesenteric", "renal_artery",
                ],
                side="both",
            )

        if t in ("all_neurovascular", "혈관·신경", "신경·혈관", "혈관신경", "신경혈관 전체") or t_clean in (
            "혈관·신경",
            "신경·혈관",
            "혈관신경",
        ):
            return self._match_structures_by_stems(
                [
                    "neurovascular", "nerve", "artery", "vein", "vessel", "aorta", "vena_cava",
                    "carotid", "jugular", "axillary_artery", "axillary_nerve", "sciatic",
                    "femoral_nerve", "femoral_artery", "median_nerve", "radial_nerve", "ulnar_nerve",
                    "brain", "cerebrum", "cerebellum", "brainstem", "spinal_cord",
                ],
                side=side,
            )

        # 2. Check direct group / category / region name in self.groups
        for g_name, g_ids in self.groups.items():
            if t == g_name.lower() or (t_clean and t_clean == g_name.lower()):
                if side == "both":
                    return list(g_ids)
                filtered = [
                    sid
                    for sid in g_ids
                    if str(self.structures_by_id[sid].get("side", "")).lower() in (side, "center", "midline", "both", "")
                ]
                return filtered if filtered else list(g_ids)

        # 3. Match via WHOLE_BODY_KEYWORD_MAP (preferring longer/more specific keyword matches first)
        include_fp = any(k in t for k in ["기시", "정지", "origin", "insertion", "부착"])
        matched_stems: List[str] = []
        for kw, stems in sorted(WHOLE_BODY_KEYWORD_MAP.items(), key=lambda kv: -len(kv[0])):
            if kw == t or kw == t_clean or (len(kw) >= 2 and (kw in t_clean or kw in t)):
                for st in stems:
                    if st not in matched_stems:
                        matched_stems.append(st)
                # If exact match on keyword, no need to accumulate unrelated shorter substrings
                if kw == t or kw == t_clean:
                    break

        if matched_stems:
            res_ids = self._match_structures_by_stems(matched_stems, side=side, include_footprints=include_fp)
            if res_ids:
                return res_ids

        # 4. Dynamic fallback search across all structures in structures-manifest.json
        sr = self.search_structures(query=term, side=None if side == "both" else side, limit=12)
        if sr["structures"]:
            top_score = sr["structures"][0]["score"]
            if top_score >= 25.0:
                return [
                    item["id"]
                    for item in sr["structures"]
                    if item["score"] >= max(25.0, top_score - 18.0)
                ]
        return []

    # ------------------------------------------------------------------
    # 2. scene.get_state
    # ------------------------------------------------------------------
    def get_state(self, session_id: str = "default", compact: bool = False) -> Dict[str, Any]:
        self.reload_manifest_if_needed()
        session = self.get_or_create_session(session_id)
        return session.to_dict(compact=compact)

    # ------------------------------------------------------------------
    # 3. scene.apply_patch (with Revision Check, Validation, Auto-Framing & Viewer ACK)
    # ------------------------------------------------------------------
    async def apply_patch(
        self,
        session_id: str = "default",
        changes: Optional[Dict[str, Any]] = None,
        expected_revision: Optional[int] = None,
        command_id: Optional[str] = None,
        wait_for_ack: bool = True,
        timeout_sec: float = 3.5,
        source: str = "mcp_or_agent",
    ) -> Dict[str, Any]:
        self.reload_manifest_if_needed()
        session = self.get_or_create_session(session_id)
        changes = changes or {}
        cmd_id = command_id or f"cmd-{uuid.uuid4().hex[:10]}"

        # Idempotency check
        if cmd_id in session.processed_commands:
            cached = copy.deepcopy(session.processed_commands[cmd_id])
            cached["idempotentReplay"] = True
            return cached

        # Revision conflict check
        if expected_revision is not None and int(expected_revision) != session.revision:
            return {
                "ok": False,
                "errorCode": "REVISION_CONFLICT",
                "message": (
                    f"expectedRevision={expected_revision} does not match current server revision={session.revision}. "
                    "Call scene.get_state first to sync latest revision."
                ),
                "currentRevision": session.revision,
                "sessionId": session.session_id,
            }

        # Validate structure changes before mutating state
        validation_errors: List[str] = []
        normalized_struct_changes: Dict[str, Dict[str, Any]] = {}

        # Optional reset flag inside changes
        reset_all = bool(changes.get("resetToDefault", False))

        raw_structures = changes.get("structures", {})
        if isinstance(raw_structures, list):
            converted = {}
            for entry in raw_structures:
                if isinstance(entry, dict) and "id" in entry:
                    converted[entry["id"]] = {k: v for k, v in entry.items() if k != "id"}
            raw_structures = converted

        for key_or_id, patch_val in raw_structures.items():
            if not isinstance(patch_val, dict):
                validation_errors.append(f"Invalid patch value for '{key_or_id}': must be an object.")
                continue

            # Resolve exact ID or group/anatomical alias
            target_ids = (
                [key_or_id]
                if key_or_id in self.structures_by_id
                else self.expand_term_to_structure_ids(key_or_id)
            )
            if not target_ids:
                validation_errors.append(
                    f"Unknown structure ID or term '{key_or_id}' (not in structures-manifest.json)."
                )
                continue

            for tid in target_ids:
                clean_entry: Dict[str, Any] = {}
                if "visible" in patch_val and patch_val["visible"] is not None:
                    clean_entry["visible"] = bool(patch_val["visible"])
                if "opacity" in patch_val and patch_val["opacity"] is not None:
                    try:
                        op = float(patch_val["opacity"])
                    except (TypeError, ValueError):
                        validation_errors.append(f"Invalid opacity '{patch_val['opacity']}' for '{tid}'.")
                        continue
                    if op < 0.0 or op > 1.0:
                        validation_errors.append(
                            f"Opacity out of range [0.0, 1.0] for '{tid}': received {op}."
                        )
                        continue
                    clean_entry["opacity"] = round(op, 4)
                    if op == 0.0 and "visible" not in clean_entry:
                        clean_entry["visible"] = False
                    elif op > 0.0 and "visible" not in clean_entry:
                        clean_entry["visible"] = True
                if "highlighted" in patch_val and patch_val["highlighted"] is not None:
                    clean_entry["highlighted"] = bool(patch_val["highlighted"])
                if "colorHex" in patch_val:
                    clean_entry["colorHex"] = patch_val["colorHex"]
                if "outline" in patch_val and patch_val["outline"] is not None:
                    clean_entry["outline"] = bool(patch_val["outline"])

                if tid not in normalized_struct_changes:
                    normalized_struct_changes[tid] = {}
                normalized_struct_changes[tid].update(clean_entry)

        # Also support convenience arrays in `changes`: highlightIds / highlightedStructureIds
        highlight_ids_list = (
            changes["highlightIds"]
            if isinstance(changes.get("highlightIds"), list)
            else changes["highlightedStructureIds"]
            if isinstance(changes.get("highlightedStructureIds"), list)
            else None
        )
        if highlight_ids_list is not None:
            clear_other_highlights = bool(changes.get("clearOtherHighlights", True))
            if clear_other_highlights:
                for sid in self.structures_by_id:
                    if session.structures.get(sid, {}).get("highlighted"):
                        normalized_struct_changes.setdefault(sid, {})["highlighted"] = False
                        normalized_struct_changes[sid]["outline"] = False
                        normalized_struct_changes[sid]["colorHex"] = None
            for raw_hid in highlight_ids_list:
                resolved = (
                    [raw_hid]
                    if raw_hid in self.structures_by_id
                    else self.expand_term_to_structure_ids(str(raw_hid))
                )
                if not resolved:
                    validation_errors.append(f"Unknown structure in highlightIds: '{raw_hid}'")
                for tid in resolved:
                    entry = normalized_struct_changes.setdefault(tid, {})
                    entry["visible"] = True
                    entry.setdefault("opacity", 1.0)
                    entry["highlighted"] = True
                    entry.setdefault("outline", True)
                    entry.setdefault("colorHex", "#ef4444")

        if validation_errors:
            return {
                "ok": False,
                "errorCode": "VALIDATION_ERROR",
                "errors": validation_errors,
                "currentRevision": session.revision,
                "sessionId": session.session_id,
            }

        # Push undo snapshot before mutating
        session.undo_stack.append(session.snapshot_for_undo())
        if len(session.undo_stack) > session.max_undo:
            session.undo_stack.pop(0)

        if reset_all:
            session.reset_structures_to_default()
            session.active_procedure = None
            session.landmarks_visible = False

        # Apply structure mutations
        for tid, patch_entry in normalized_struct_changes.items():
            if tid in session.structures:
                session.structures[tid].update(patch_entry)

        # Determine highlighted structures after mutation
        highlighted_now = [
            tid for tid, st in normalized_struct_changes.items() if st.get("highlighted")
        ]

        # Camera handling: preserve camera when preserveCamera is True;
        # otherwise apply explicit cameraPreset / camera / cameraPosition or auto-frame targets
        camera_changed = False
        explicit_camera_provided = False
        preserve_camera = changes.get("preserveCamera")

        if preserve_camera is not True:
            preset_name = changes.get("cameraPreset")
            if isinstance(preset_name, str) and preset_name in CAMERA_PRESETS:
                preset_cam = CAMERA_PRESETS[preset_name]
                session.camera["name"] = preset_cam.get("name", preset_name)
                session.camera["labelKo"] = preset_cam.get("labelKo", "")
                session.camera_position = preset_cam["position"]
                session.camera_target = preset_cam["target"]
                session.camera["up"] = list(preset_cam.get("up", [0.0, 1.0, 0.0]))
                session.camera["fov"] = preset_cam.get("fov", 36)
                camera_changed = True
                explicit_camera_provided = True

            if "camera" in changes and isinstance(changes["camera"], dict):
                cam = changes["camera"]
                if "name" in cam and cam["name"] in CAMERA_PRESETS and "position" not in cam:
                    preset_cam = CAMERA_PRESETS[cam["name"]]
                    session.camera["name"] = preset_cam["name"]
                    session.camera["labelKo"] = preset_cam.get("labelKo", "")
                    session.camera_position = preset_cam["position"]
                    session.camera_target = preset_cam["target"]
                    session.camera["up"] = list(preset_cam.get("up", [0.0, 1.0, 0.0]))
                    session.camera["fov"] = preset_cam.get("fov", 36)
                    camera_changed = True
                    explicit_camera_provided = True
                else:
                    if "position" in cam and isinstance(cam["position"], (list, tuple)) and len(cam["position"]) == 3:
                        session.camera_position = list(cam["position"])
                        camera_changed = True
                        explicit_camera_provided = True
                    if "target" in cam and isinstance(cam["target"], (list, tuple)) and len(cam["target"]) == 3:
                        session.camera_target = list(cam["target"])
                        camera_changed = True
                        explicit_camera_provided = True
                    if "up" in cam and isinstance(cam["up"], (list, tuple)) and len(cam["up"]) == 3:
                        session.camera["up"] = [round(float(x), 5) for x in cam["up"]]
                        camera_changed = True
                    if "fov" in cam and cam["fov"] is not None:
                        session.camera["fov"] = float(cam["fov"])
                    if "name" in cam:
                        session.camera["name"] = cam["name"]
                    if "labelKo" in cam:
                        session.camera["labelKo"] = cam["labelKo"]

            if isinstance(changes.get("cameraPosition"), (list, tuple)) and len(changes["cameraPosition"]) == 3:
                session.camera_position = list(changes["cameraPosition"])
                camera_changed = True
                explicit_camera_provided = True
            if isinstance(changes.get("cameraTarget"), (list, tuple)) and len(changes["cameraTarget"]) == 3:
                session.camera_target = list(changes["cameraTarget"])
                camera_changed = True
                explicit_camera_provided = True

            # Automatic 3D bounding-box camera framing when autoFrameTargets is True
            # or when highlightedStructureIds is non-empty and preserveCamera is False and no explicit camera was given
            auto_frame_flag = bool(changes.get("autoFrameTargets", False))
            if not explicit_camera_provided and (
                auto_frame_flag or (bool(highlighted_now) and preserve_camera is False)
            ):
                frame_targets = highlighted_now or list(normalized_struct_changes.keys())
                framed = self.compute_camera_for_structures(
                    frame_targets,
                    prefer_posterior=changes.get("preferPosterior"),
                )
                if framed:
                    session.camera_position = framed["position"]
                    session.camera_target = framed["target"]
                    session.camera["up"] = [0.0, 1.0, 0.0]
                    session.camera["fov"] = framed.get("fov", 36)
                    session.camera["name"] = "auto_framed"
                    camera_changed = True

            # If resetting to default and preserveCamera is False (and no other camera was set), reset to whole_body_front
            if reset_all and not camera_changed and preserve_camera is False:
                session.camera = copy.deepcopy(CAMERA_PRESETS["whole_body_front"])
                camera_changed = True

        if "selectedStructureIds" in changes and isinstance(changes["selectedStructureIds"], list):
            valid_sel = [s for s in changes["selectedStructureIds"] if s in self.structures_by_id]
            session.selected_structure_ids = valid_sel
        elif highlight_ids_list is not None and highlighted_now:
            session.selected_structure_ids = highlighted_now

        if "landmarksVisible" in changes and changes["landmarksVisible"] is not None:
            session.landmarks_visible = bool(changes["landmarksVisible"])

        if "activeLandmarkIds" in changes and isinstance(changes["activeLandmarkIds"], list):
            session.active_landmark_ids = [
                lid for lid in changes["activeLandmarkIds"] if lid in self.landmarks_by_id
            ]

        if "explanationCard" in changes and isinstance(changes["explanationCard"], dict):
            session.last_explanation_card = changes["explanationCard"]

        session.revision += 1
        session.updated_at = time.time()
        session.last_command_id = cmd_id

        # Broadcast to connected browser viewers and wait for real Viewer ACK
        ack_result = await self._broadcast_and_wait_ack(
            session=session,
            command_id=cmd_id,
            event_type="scene.patch",
            payload={
                "type": "scene.patch",
                "sessionId": session.session_id,
                "commandId": cmd_id,
                "revision": session.revision,
                "source": source,
                "resetToDefault": reset_all,
                "cameraChanged": camera_changed,
                "camera": session.camera if camera_changed else None,
                "structures": session.structures if reset_all else normalized_struct_changes,
                "selectedStructureIds": session.selected_structure_ids,
                "landmarksVisible": session.landmarks_visible,
                "activeLandmarkIds": session.active_landmark_ids,
                "activeProcedure": session.active_procedure,
                "explanationCard": session.last_explanation_card,
            },
            wait_for_ack=wait_for_ack,
            timeout_sec=timeout_sec,
        )

        result = {
            "ok": True,
            "sessionId": session.session_id,
            "commandId": cmd_id,
            "appliedRevision": session.revision,
            "cameraPreserved": not camera_changed,
            "camera": session.camera,
            "modifiedStructureCount": len(normalized_struct_changes),
            "modifiedStructureIds": list(normalized_struct_changes.keys()),
            "selectedStructureIds": session.selected_structure_ids,
            "viewerAck": ack_result,
        }
        session.processed_commands[cmd_id] = result
        return result

    # ------------------------------------------------------------------
    # 4. scene.undo
    # ------------------------------------------------------------------
    async def undo(
        self,
        session_id: str = "default",
        command_id: Optional[str] = None,
        wait_for_ack: bool = True,
        timeout_sec: float = 3.5,
    ) -> Dict[str, Any]:
        session = self.get_or_create_session(session_id)
        if not session.undo_stack:
            return {
                "ok": False,
                "errorCode": "EMPTY_UNDO_STACK",
                "message": "No previous scene state available to undo.",
                "currentRevision": session.revision,
                "sessionId": session.session_id,
            }

        snap = session.undo_stack.pop()
        session.restore_snapshot(snap)
        session.revision += 1
        session.updated_at = time.time()
        cmd_id = command_id or f"undo-{uuid.uuid4().hex[:10]}"
        session.last_command_id = cmd_id

        ack_result = await self._broadcast_and_wait_ack(
            session=session,
            command_id=cmd_id,
            event_type="scene.full_sync",
            payload={
                "type": "scene.full_sync",
                "sessionId": session.session_id,
                "commandId": cmd_id,
                "revision": session.revision,
                "source": "scene.undo",
                "state": session.to_dict(compact=False),
            },
            wait_for_ack=wait_for_ack,
            timeout_sec=timeout_sec,
        )

        return {
            "ok": True,
            "sessionId": session.session_id,
            "commandId": cmd_id,
            "appliedRevision": session.revision,
            "remainingUndoDepth": len(session.undo_stack),
            "viewerAck": ack_result,
        }

    # ------------------------------------------------------------------
    # 5. procedure.list_templates / load_template / set_progress
    # ------------------------------------------------------------------
    def list_templates(self, side: Optional[str] = None) -> Dict[str, Any]:
        side_norm = (side or "").strip().lower() or None
        items = []
        for tpl_id, tpl in PROCEDURE_TEMPLATES.items():
            if side_norm and tpl.get("side") != side_norm:
                continue
            items.append(
                {
                    "id": tpl["id"],
                    "titleKo": tpl["titleKo"],
                    "titleEn": tpl["titleEn"],
                    "side": tpl["side"],
                    "targetStructureIds": tpl["targetStructureIds"],
                    "sotReferences": tpl["sotReferences"],
                    "clinicalSummaryKo": tpl["clinicalSummaryKo"],
                    "safetyDisclaimerKo": tpl["safetyDisclaimerKo"],
                    "stepCount": len(tpl["steps"]),
                    "steps": tpl["steps"],
                }
            )
        return {"count": len(items), "templates": items}

    async def load_template(
        self,
        session_id: str = "default",
        template_id: str = "proc_subscap_axillary_r",
        step_index: int = 0,
        preserve_camera: bool = True,
        wait_for_ack: bool = True,
        timeout_sec: float = 3.5,
    ) -> Dict[str, Any]:
        self.reload_manifest_if_needed()
        if template_id not in PROCEDURE_TEMPLATES:
            return {
                "ok": False,
                "errorCode": "UNKNOWN_TEMPLATE",
                "message": f"Unknown procedure template '{template_id}'. Available: {list(PROCEDURE_TEMPLATES.keys())}",
            }

        session = self.get_or_create_session(session_id)
        tpl = PROCEDURE_TEMPLATES[template_id]
        steps = tpl["steps"]
        clamped_step = max(0, min(int(step_index), len(steps) - 1))
        step_obj = steps[clamped_step]

        # Push undo snapshot
        session.undo_stack.append(session.snapshot_for_undo())
        if len(session.undo_stack) > session.max_undo:
            session.undo_stack.pop(0)

        # Reset structures to clean baseline, then apply template baseStructurePatch
        session.reset_structures_to_default()
        for sid, patch_val in tpl.get("baseStructurePatch", {}).items():
            if sid in session.structures:
                session.structures[sid].update(patch_val)

        session.selected_structure_ids = list(tpl.get("targetStructureIds", ["subscapularis_r"]))
        session.landmarks_visible = True
        session.active_landmark_ids = list(step_obj.get("activeLandmarks") or tpl.get("landmarkIds", []))

        camera_changed = False
        if not preserve_camera and tpl.get("recommendedCamera"):
            rc = tpl["recommendedCamera"]
            session.camera = {
                "position": list(rc["position"]),
                "target": list(rc["target"]),
                "up": list(rc.get("up", [0.0, 1.0, 0.0])),
                "fov": 36,
            }
            camera_changed = True

        session.active_procedure = {
            "templateId": tpl["id"],
            "titleKo": tpl["titleKo"],
            "titleEn": tpl["titleEn"],
            "side": tpl["side"],
            "sotReferences": tpl["sotReferences"],
            "clinicalSummaryKo": tpl["clinicalSummaryKo"],
            "safetyDisclaimerKo": tpl["safetyDisclaimerKo"],
            "stepIndex": clamped_step,
            "stepCount": len(steps),
            "currentStep": step_obj,
            "steps": steps,
            "progress": float(step_obj.get("vectorProgress", 1.0)),
            "playState": "paused",
            "guideVectors": tpl.get("guideVectors", []),
            "recommendedCamera": tpl.get("recommendedCamera"),
        }

        session.last_explanation_card = {
            "titleKo": f"{tpl['titleKo']} — {step_obj['titleKo']}",
            "bodyKo": step_obj["descriptionKo"],
            "sotReferences": tpl["sotReferences"],
            "safetyDisclaimerKo": tpl["safetyDisclaimerKo"],
        }

        session.revision += 1
        session.updated_at = time.time()
        cmd_id = f"proc-load-{uuid.uuid4().hex[:8]}"
        session.last_command_id = cmd_id

        ack_result = await self._broadcast_and_wait_ack(
            session=session,
            command_id=cmd_id,
            event_type="scene.full_sync",
            payload={
                "type": "scene.full_sync",
                "sessionId": session.session_id,
                "commandId": cmd_id,
                "revision": session.revision,
                "source": "procedure.load_template",
                "cameraChanged": camera_changed,
                "state": session.to_dict(compact=False),
            },
            wait_for_ack=wait_for_ack,
            timeout_sec=timeout_sec,
        )

        return {
            "ok": True,
            "sessionId": session.session_id,
            "commandId": cmd_id,
            "appliedRevision": session.revision,
            "cameraPreserved": not camera_changed,
            "activeProcedure": session.active_procedure,
            "viewerAck": ack_result,
        }

    async def set_procedure_progress(
        self,
        session_id: str = "default",
        progress: Optional[float] = None,
        step_index: Optional[int] = None,
        play_state: Optional[str] = None,
        preserve_camera: bool = True,
        wait_for_ack: bool = True,
        timeout_sec: float = 3.5,
    ) -> Dict[str, Any]:
        session = self.get_or_create_session(session_id)
        if not session.active_procedure:
            await self.load_template(
                session_id=session_id,
                template_id="proc_subscap_axillary_r",
                step_index=step_index or 0,
                preserve_camera=preserve_camera,
                wait_for_ack=False,
            )

        proc = session.active_procedure
        assert proc is not None
        tpl = PROCEDURE_TEMPLATES.get(proc["templateId"], PROCEDURE_TEMPLATES["proc_subscap_axillary_r"])
        steps = tpl["steps"]

        if step_index is not None:
            clamped_idx = max(0, min(int(step_index), len(steps) - 1))
            step_obj = steps[clamped_idx]
            proc["stepIndex"] = clamped_idx
            proc["currentStep"] = step_obj
            proc["progress"] = float(progress if progress is not None else step_obj.get("vectorProgress", 1.0))
            session.active_landmark_ids = list(step_obj.get("activeLandmarks") or tpl.get("landmarkIds", []))
        elif progress is not None:
            p = max(0.0, min(1.0, float(progress)))
            proc["progress"] = round(p, 4)
            chosen_step = steps[-1]
            for stp in steps:
                lo, hi = stp.get("progressRange", [0.0, 1.0])
                if lo <= p <= hi:
                    chosen_step = stp
                    break
            proc["stepIndex"] = chosen_step["stepIndex"]
            proc["currentStep"] = chosen_step
            session.active_landmark_ids = list(chosen_step.get("activeLandmarks") or tpl.get("landmarkIds", []))

        if play_state in ("playing", "paused"):
            proc["playState"] = play_state

        cur_step = proc["currentStep"]
        session.last_explanation_card = {
            "titleKo": f"{tpl['titleKo']} — {cur_step['titleKo']}",
            "bodyKo": cur_step["descriptionKo"],
            "sotReferences": tpl["sotReferences"],
            "safetyDisclaimerKo": tpl["safetyDisclaimerKo"],
        }

        session.revision += 1
        session.updated_at = time.time()
        cmd_id = f"proc-step-{uuid.uuid4().hex[:8]}"
        session.last_command_id = cmd_id

        ack_result = await self._broadcast_and_wait_ack(
            session=session,
            command_id=cmd_id,
            event_type="procedure.update",
            payload={
                "type": "procedure.update",
                "sessionId": session.session_id,
                "commandId": cmd_id,
                "revision": session.revision,
                "activeProcedure": session.active_procedure,
                "activeLandmarkIds": session.active_landmark_ids,
                "explanationCard": session.last_explanation_card,
            },
            wait_for_ack=wait_for_ack,
            timeout_sec=timeout_sec,
        )

        return {
            "ok": True,
            "sessionId": session.session_id,
            "commandId": cmd_id,
            "appliedRevision": session.revision,
            "activeProcedure": session.active_procedure,
            "viewerAck": ack_result,
        }

    # ------------------------------------------------------------------
    # 6. scene.capture (Real Screenshot from Connected Browser Viewer)
    # ------------------------------------------------------------------
    async def capture_scene(
        self,
        session_id: str = "default",
        image_format: str = "png",
        timeout_sec: float = 4.5,
    ) -> Dict[str, Any]:
        session = self.get_or_create_session(session_id)
        if not session.websockets:
            return {
                "ok": False,
                "errorCode": "NO_ACTIVE_VIEWER",
                "message": (
                    "No browser 3D viewer is currently connected via WebSocket to capture a real WebGL frame. "
                    "Open http://127.0.0.1:8090 in a browser first."
                ),
                "currentRevision": session.revision,
                "sessionId": session.session_id,
            }

        capture_id = f"cap-{uuid.uuid4().hex[:10]}"
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        session.pending_captures[capture_id] = fut

        req_payload = {
            "type": "scene.capture_request",
            "sessionId": session.session_id,
            "captureId": capture_id,
            "format": image_format,
            "expectedRevision": session.revision,
        }

        await self._send_to_session_websockets(session, req_payload)

        try:
            cap_data = await asyncio.wait_for(fut, timeout=timeout_sec)
        except asyncio.TimeoutError:
            session.pending_captures.pop(capture_id, None)
            return {
                "ok": False,
                "errorCode": "CAPTURE_TIMEOUT",
                "message": f"Browser viewer did not return canvas screenshot within {timeout_sec}s.",
                "currentRevision": session.revision,
                "sessionId": session.session_id,
            }
        finally:
            session.pending_captures.pop(capture_id, None)

        data_url: str = cap_data.get("dataUrl", "")
        saved_path: Optional[str] = None
        saved_url: Optional[str] = None
        byte_size: int = 0

        if data_url.startswith("data:image/"):
            try:
                header, b64_part = data_url.split(",", 1)
                raw_bytes = base64.b64decode(b64_part)
                byte_size = len(raw_bytes)
                ext = "jpg" if "jpeg" in header else "png"
                filename = f"scene_{session.session_id}_rev{cap_data.get('revision', session.revision)}_{capture_id}.{ext}"
                file_path = CAPTURES_DIR / filename
                with open(file_path, "wb") as f:
                    f.write(raw_bytes)
                saved_path = str(file_path)
                saved_url = f"/static/captures/{filename}"
            except Exception as exc:
                saved_path = f"decode_error: {exc}"

        return {
            "ok": True,
            "sessionId": session.session_id,
            "captureId": capture_id,
            "capturedRevision": cap_data.get("revision", session.revision),
            "width": cap_data.get("width"),
            "height": cap_data.get("height"),
            "byteSize": byte_size,
            "filePath": saved_path,
            "staticUrl": saved_url,
            "camera": session.camera,
            "highlightedStructureIds": [
                sid for sid, st in session.structures.items() if st.get("highlighted")
            ],
        }

    # ------------------------------------------------------------------
    # WebSocket Synchronization & Real Viewer ACK Handling
    # ------------------------------------------------------------------
    async def register_websocket(self, session_id: str, ws: WebSocket) -> SessionSceneState:
        self.reload_manifest_if_needed()
        session = self.get_or_create_session(session_id)
        if ws not in session.websockets:
            session.websockets.append(ws)
        await ws.send_json(
            {
                "type": "scene.init",
                "sessionId": session.session_id,
                "revision": session.revision,
                "state": session.to_dict(compact=False),
                "templates": self.list_templates()["templates"],
                "cameraPresets": CAMERA_PRESETS,
            }
        )
        return session

    def unregister_websocket(self, session_id: str, ws: WebSocket) -> None:
        session = self.get_or_create_session(session_id)
        if ws in session.websockets:
            session.websockets.remove(ws)

    async def handle_viewer_message(
        self, session_id: str, ws: WebSocket, msg: Dict[str, Any]
    ) -> None:
        """Processes messages sent from the browser Three.js viewer (ACKs, mouse camera/UI updates, captures)."""
        session = self.get_or_create_session(session_id)
        msg_type = msg.get("type")

        if msg_type == "ack":
            cmd_id = msg.get("commandId")
            if cmd_id and cmd_id in session.pending_acks:
                fut = session.pending_acks[cmd_id]
                if not fut.done():
                    fut.set_result(
                        {
                            "ackStatus": "VIEWER_ACKED",
                            "commandId": cmd_id,
                            "appliedRevision": msg.get("appliedRevision", session.revision),
                            "viewerTimestamp": msg.get("timestamp"),
                            "errors": msg.get("errors", []),
                        }
                    )
            return

        if msg_type == "capture_response":
            cap_id = msg.get("captureId")
            if cap_id and cap_id in session.pending_captures:
                fut = session.pending_captures[cap_id]
                if not fut.done():
                    fut.set_result(msg)
            return

        if msg_type == "viewer.camera_update":
            cam = msg.get("camera")
            if isinstance(cam, dict):
                if "position" in cam and len(cam["position"]) == 3:
                    session.camera_position = list(cam["position"])
                if "target" in cam and len(cam["target"]) == 3:
                    session.camera_target = list(cam["target"])
                if "up" in cam and len(cam["up"]) == 3:
                    session.camera["up"] = [round(float(x), 5) for x in cam["up"]]
                session.updated_at = time.time()
            return

        if msg_type == "viewer.select_structure":
            sid = msg.get("structureId")
            if sid and sid in self.structures_by_id:
                session.selected_structure_ids = [sid]
                session.updated_at = time.time()
            elif sid is None:
                session.selected_structure_ids = []
            return

        if msg_type == "viewer.ui_patch":
            changes = msg.get("changes", {})
            await self.apply_patch(
                session_id=session_id,
                changes=changes,
                expected_revision=None,
                command_id=msg.get("commandId"),
                wait_for_ack=False,
                source="viewer_ui",
            )

    async def _send_to_session_websockets(
        self, session: SessionSceneState, payload: Dict[str, Any]
    ) -> int:
        dead: List[WebSocket] = []
        sent_count = 0
        for ws in list(session.websockets):
            try:
                await ws.send_json(payload)
                sent_count += 1
            except Exception:
                dead.append(ws)
        for ws in dead:
            if ws in session.websockets:
                session.websockets.remove(ws)
        return sent_count

    async def _broadcast_and_wait_ack(
        self,
        session: SessionSceneState,
        command_id: str,
        event_type: str,
        payload: Dict[str, Any],
        wait_for_ack: bool = True,
        timeout_sec: float = 3.5,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()
        if not session.websockets:
            return {
                "ackStatus": "NO_ACTIVE_VIEWER_QUEUED",
                "commandId": command_id,
                "appliedRevision": session.revision,
                "ackLatencyMs": 0.0,
                "note": "Authoritative server state updated; will sync immediately when browser viewer connects.",
            }

        loop = asyncio.get_running_loop()
        fut: Optional[asyncio.Future] = None
        if wait_for_ack:
            fut = loop.create_future()
            session.pending_acks[command_id] = fut

        sent_count = await self._send_to_session_websockets(session, payload)
        if sent_count == 0:
            session.pending_acks.pop(command_id, None)
            return {
                "ackStatus": "NO_ACTIVE_VIEWER_QUEUED",
                "commandId": command_id,
                "appliedRevision": session.revision,
                "ackLatencyMs": 0.0,
            }

        if not wait_for_ack or fut is None:
            return {
                "ackStatus": "BROADCAST_SENT",
                "commandId": command_id,
                "appliedRevision": session.revision,
                "ackLatencyMs": round((time.perf_counter() - t0) * 1000, 1),
            }

        try:
            ack_data = await asyncio.wait_for(fut, timeout=timeout_sec)
            ack_data["ackLatencyMs"] = round((time.perf_counter() - t0) * 1000, 1)
            return ack_data
        except asyncio.TimeoutError:
            return {
                "ackStatus": "ACK_TIMEOUT",
                "commandId": command_id,
                "appliedRevision": session.revision,
                "ackLatencyMs": round((time.perf_counter() - t0) * 1000, 1),
            }
        finally:
            session.pending_acks.pop(command_id, None)


# Singleton instance
SCENE_SERVICE = AnatomySceneService()
