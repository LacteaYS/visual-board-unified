from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = ROOT_DIR / "assets"
STRUCTURES_MANIFEST_PATH = ASSETS_DIR / "structures-manifest.json"
PROVENANCE_MANIFEST_PATH = ASSETS_DIR / "provenance-manifest.json"


def load_structures_manifest() -> dict[str, Any]:
    if STRUCTURES_MANIFEST_PATH.exists():
        return json.loads(STRUCTURES_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {"schemaVersion": "1.0.0", "structureCount": 0, "structures": [], "groupDefinitions": {}}


def load_provenance_manifest() -> dict[str, Any]:
    if PROVENANCE_MANIFEST_PATH.exists():
        return json.loads(PROVENANCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {}


SOURCE_OF_TRUTH_DOCS: list[dict[str, Any]] = [
    {
        "id": "SOT-GPCR-01",
        "domain": "biology_pathway",
        "title": "Gs-결합 GPCR → cAMP → PKA 표준 신호 전달 경로",
        "summary": (
            "1단계: 세포외 리간드(에피네프린 등)가 막관통 7-헬릭스 수용체(GPCR)에 결합해 구조 변화를 유도한다. "
            "2단계: 활성화된 GPCR이 구아닌 뉴클레오타이드 교환 인자(GEF)로 작동해 삼량체 Gs 단백질의 Gαs 서브유닛에서 GDP 방출과 GTP 결합을 촉진한다. "
            "3단계: GTP가 결합한 Gαs-GTP가 Gβγ 복합체로부터 분리되어 막 결합 효소인 아데닐산 고리화효소(Adenylyl Cyclase, AC)로 이동한다. "
            "4단계: 활성화된 Adenylyl Cyclase가 ATP를 2차 전령인 cAMP(고리형 AMP)로 전환하여 세포 내 cAMP 농도를 높인다. "
            "5단계: cAMP 4분자가 단백질 인산화효소 A(PKA)의 조절 서브유닛(R2)에 결합하면 촉매 서브유닛(C2)이 유리되어 활성화된다. "
            "6단계: 활성 PKA 촉매 서브유닛이 세포질 표적 효소 및 핵 내 전사인자 CREB을 인산화하여 세포 반응을 유도한다."
        ),
        "verified": True,
        "citation": "Canonical GPCR-Gs-cAMP-PKA Cascade (Reviewed Educational SOT)",
    },
    {
        "id": "SOT-GPCR-02",
        "domain": "biology_pathway",
        "title": "G 단백질(Gs) 활성화 및 서브유닛 분리 세부 기전 (3단계 상세)",
        "summary": (
            "비활성 상태에서 Gαs는 GDP와 결합한 채 Gβγ 이량체와 삼량체(Heterotrimer)를 이룬다. "
            "리간드 결합 GPCR의 세포질 측 구조 변화가 Gαs의 α5 헬릭스와 상호작용하면 뉴클레오타이드 결합 포켓이 열리며 GDP가 이탈한다. "
            "세포 내 농도가 높은 GTP가 즉시 결합하면 Gαs의 Switch I/II 영역 구조가 바뀌어 Gβγ와의 친화력이 급감하고, "
            "활성 Gαs-GTP와 유리 Gβγ로 분리되어 각각 하위 효과기(Adenylyl Cyclase 등)를 조절한다."
        ),
        "verified": True,
        "citation": "Heterotrimeric G-Protein Activation Cycle (Reviewed Educational SOT)",
    },
    {
        "id": "SOT-GPCR-03",
        "domain": "biology_pathway",
        "title": "정상 신호 전달 vs 길항제(Antagonist) / PDE 분해 비교",
        "summary": (
            "경쟁적 길항제(예: 베타 차단제)가 수용체 결합 부위를 점유하면 리간드 결합과 GPCR 구조 변화가 차단되어 "
            "Gαs-GTP 분리, Adenylyl Cyclase 활성화, cAMP 생성 및 PKA 활성화가 모두 억제된다. "
            "또한 포스포디에스테라아제(PDE)는 생성된 cAMP를 5'-AMP로 가수분해하여 신호를 종결시킨다."
        ),
        "verified": True,
        "citation": "GPCR Pharmacology & Signal Termination (Reviewed Educational SOT)",
    },
    {
        "id": "SOT-ANAT-01",
        "domain": "anatomy_3d",
        "title": "견갑하근(Subscapularis)의 해부학적 위치와 전면 가림 구조",
        "summary": (
            "견갑하근(Subscapularis muscle)은 견갑골 전면의 견갑하와(Subscapular fossa)에서 기시하여 상완골 소결절(Lesser tubercle)에 정지한다. "
            "신체 전면에서 바라볼 때 대흉근(Pectoralis major), 소흉근(Pectoralis minor), 전면 삼각근(Deltoid), 그리고 전방 늑골(Ribs 1-5)과 "
            "견갑골 오구돌기/쇄골 구조에 의해 중첩되어 직접 노출되지 않고 깊은 층(심부)에 위치한다."
        ),
        "verified": True,
        "citation": "Z-Anatomy CC BY-SA 4.0 + Clinical Anatomy SOT-01",
    },
    {
        "id": "SOT-ANAT-02",
        "domain": "anatomy_3d",
        "title": "회전근개(Rotator Cuff, SITS) 4대 근육 구성과 기능",
        "summary": (
            "회전근개는 견갑하근(Subscapularis, 내회전), 극상근(Supraspinatus, 외전 개시), "
            "극하근(Infraspinatus, 외회전), 소원근(Teres minor, 외회전)의 4개 근육으로 구성되며 상완골두를 관절와에 안정화한다."
        ),
        "verified": True,
        "citation": "Z-Anatomy CC BY-SA 4.0 + Clinical Anatomy SOT-02",
    },
    {
        "id": "SOT-ANAT-03",
        "domain": "anatomy_3d",
        "title": "액와 신경·혈관 안전 구조물 및 침습 경로 안전 원칙",
        "summary": (
            "견갑하근 전하방 및 액와 부위에는 액와동맥(Axillary artery), 견갑하동맥(Subscapular artery), 액와신경(Axillary nerve), "
            "상·하견갑하신경(Upper/Lower subscapular nerves)이 주행한다. "
            "검증된 침습 템플릿 없이 임의의 자입 각도·깊이(cm)나 바늘 궤적을 추측하여 생성해서는 안 되며, 해부학적 층위와 안전 구역만 표시한다."
        ),
        "verified": True,
        "citation": "Clinical Safety Guardrail SOT-03",
    },
    {
        "id": "SOT-SYS-01",
        "domain": "system_architecture",
        "title": "비동기 작업 큐 및 워커 백프레셔 아키텍처",
        "summary": (
            "API 게이트웨이는 요청을 동기 처리하지 않고 메시지 큐(Queue)에 적재한 뒤 즉시 수락 응답(202 Accepted)을 반환한다. "
            "워커 풀(Worker Pool)이 큐에서 작업을 소비하며, 처리 실패 시 재시도 정책을 거쳐 Dead Letter Queue(DLQ)로 격리한다."
        ),
        "verified": True,
        "citation": "Distributed Systems Architecture SOT-01",
    },
]


DEMO_CANDIDATE_COMPARISON: dict[str, Any] = {
    "recommendedPrimary": "gpcr_pathway",
    "recommendedSecondary": "shoulder_anatomy_3d",
    "recommendationSummary": (
        "주 시연 시나리오로 'GPCR 신호 전달 경로(구조화 다이어그램 + 단계 상세 확장 + 나란히 비교)'를 권장하고, "
        "보조 시연으로 'Z-Anatomy 3D 어깨 해부학(전면 가림 구조 반투명화 + 회전근개 공간 탐색)'을 연결하는 구성을 추천합니다. "
        "이렇게 하면 해부학 전용 뷰어로 오해받지 않으면서 '설명자의 머릿속 생각을 청중 눈앞에서 구체화한다'는 범용 설명 도구의 정체성과 "
        "2D 구조화 도식 + 3D 공간 장면 양쪽의 기술적 깊이를 동시에 입증할 수 있습니다."
    ),
    "candidates": [
        {
            "id": "gpcr_pathway",
            "title": "후보 1: GPCR (Gs-cAMP-PKA) 세포 신호 전달 경로",
            "sceneTypes": ["diagram", "compare"],
            "implementationDifficulty": "낮음~중간 (결정론적 그래프 레이아웃 + 단계별 서브그래프 확장 + 좌우 비교 뷰)",
            "assetReadiness": "100% 완료 (검증된 6단계 생화학 경로 SOT 및 3단계 GDP/GTP 교환 서브노드, 길항제 비교 템플릿 내장)",
            "demoImpact": "최상 (비전공 심사위원도 '설명 → 질문 → 비주얼 보드 호출 → 도식 생성 → 여기만 자세히 → 비교' 흐름을 10초 내 직관적으로 이해)",
            "latencyProfile": "평균 0.8~4.2초 (Gemini 3.8 Flash 구조화 출력 기준, 목표 30초 대비 충분한 여유)",
            "safetyRisk": "매우 낮음 (임상 시술 수치나 미검증 해부 경로 왜곡 위험 없음, mRNA 백신 등 무관한 선행 발화 혼입 방지 검증 완료)",
        },
        {
            "id": "shoulder_anatomy_3d",
            "title": "후보 2: Z-Anatomy 3D 어깨·견갑하근 층위 및 진료 설명",
            "sceneTypes": ["anatomy_3d"],
            "implementationDifficulty": "중간~높음 (Three.js GLB 91개 구조물 제어, 카메라 궤도 유지, 표층 근육 반투명화 및 안전 가드레일)",
            "assetReadiness": "95% 완료 (shoulder.glb 4.0MB, 91개 구조물 매니페스트 및 라이선스 출처 검증 완료; 블렌더 원본에 스켈레탈 리깅은 없어 시점/투명도로 설명)",
            "demoImpact": "높음 ('왜 앞쪽에서 견갑하근이 바로 안 보이나요?' 질문에 표층 대흉근·삼각근·늑골을 반투명화해 심부 근육을 드러내는 3D 시각 효과 탁월)",
            "latencyProfile": "평균 0.9~4.5초 (초기 GLB 로드 후 패치 적용은 수백 ms 이내)",
            "safetyRisk": "중간 (임의의 주사 바늘 경로/깊이 생성 금지 가드레일 필수 적용 완료)",
        },
        {
            "id": "async_queue_system",
            "title": "후보 3: 비동기 작업 큐 및 워커 백프레셔 시스템 설명",
            "sceneTypes": ["diagram"],
            "implementationDifficulty": "낮음 (컴포넌트 흐름도 및 병목 강조)",
            "assetReadiness": "100% 완료 (API Gateway → Queue → Worker Pool → DLQ SOT 내장)",
            "demoImpact": "중간 (소프트웨어 엔지니어에게는 친숙하나 해커톤 무대 시각적 임팩트는 후보 1·2 조합보다 낮음)",
            "latencyProfile": "평균 0.8~3.8초",
            "safetyRisk": "매우 낮음",
        },
    ],
}


def build_gpcr_core_scene() -> dict[str, Any]:
    return {
        "sceneType": "diagram",
        "domain": "biology_pathway",
        "title": "Gs-결합 GPCR → cAMP → PKA 신호 전달 경로",
        "subtitle": "리간드 결합부터 2차 전령 cAMP 생성 및 PKA 활성화까지의 6단계 흐름",
        "sourceIds": ["SOT-GPCR-01"],
        "groundingMode": "strict_sot",
        "camera": {"zoom": 1.0, "panX": 0, "panY": 0, "preset": "overview"},
        "nodes": [
            {
                "id": "step1_ligand_gpcr",
                "stepNumber": 1,
                "label": "리간드 결합 & GPCR 활성화",
                "sublabel": "7TM 수용체 구조 변화",
                "category": "receptor",
                "compartment": "세포막 (Plasma Membrane)",
                "description": "세포외 호르몬/신경전달물질이 GPCR에 결합해 세포질 측 헬릭스 구조를 활성화합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 90,
                "y": 140,
            },
            {
                "id": "step2_gs_activation",
                "stepNumber": 2,
                "label": "Gs 단백질 GDP→GTP 교환",
                "sublabel": "Gαs 서브유닛 활성화",
                "category": "transducer",
                "compartment": "세포막 내측",
                "description": "활성 GPCR이 GEF로 작용하여 Gαs에서 GDP가 방출되고 GTP가 결합합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 310,
                "y": 140,
            },
            {
                "id": "step3_subunit_dissociation",
                "stepNumber": 3,
                "label": "Gαs-GTP / Gβγ 분리",
                "sublabel": "삼량체 해리 및 효과기 이동",
                "category": "transducer",
                "compartment": "세포막 내측",
                "description": "GTP 결합으로 Switch 영역 구조가 변해 Gαs-GTP가 Gβγ 복합체와 분리됩니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 530,
                "y": 140,
                "detailChildren": [
                    {
                        "id": "step3a_gdp_pocket_open",
                        "label": "3-A. α5 헬릭스 결합 & 포켓 개방",
                        "detail": "활성 GPCR이 Gαs의 뉴클레오타이드 결합 포켓을 열어 GDP 친화도를 낮춤",
                    },
                    {
                        "id": "step3b_gtp_switch",
                        "label": "3-B. GTP 결합 & Switch I/II 변화",
                        "detail": "세포 내 고농도 GTP가 결합하며 Gαs Switch I/II 입체구조 전환",
                    },
                    {
                        "id": "step3c_effector_targeting",
                        "label": "3-C. Gαs-GTP 유리 & AC 결합",
                        "detail": "Gβγ에서 분리된 Gαs-GTP가 막을 따라 Adenylyl Cyclase 촉매 도메인에 결합",
                    },
                ],
            },
            {
                "id": "step4_adenylyl_cyclase",
                "stepNumber": 4,
                "label": "Adenylyl Cyclase 활성화",
                "sublabel": "ATP → cAMP 전환 촉매",
                "category": "enzyme",
                "compartment": "세포막 (Plasma Membrane)",
                "description": "Gαs-GTP가 결합한 아데닐산 고리화효소가 ATP를 고리형 AMP(cAMP)로 전환합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 530,
                "y": 320,
            },
            {
                "id": "step5_camp_pka",
                "stepNumber": 5,
                "label": "2차 전령 cAMP 증폭 & PKA 해리",
                "sublabel": "R2C2 → 활성 촉매 서브유닛(C)",
                "category": "second_messenger",
                "compartment": "세포질 (Cytosol)",
                "description": "cAMP가 PKA 조절 서브유닛(R2)에 결합하여 활성 촉매 서브유닛(C2)을 방출합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 310,
                "y": 320,
            },
            {
                "id": "step6_target_response",
                "stepNumber": 6,
                "label": "표적 단백질 & CREB 인산화",
                "sublabel": "대사 효소 조절 및 유전자 전사",
                "category": "effector_response",
                "compartment": "세포질 / 핵 (Nucleus)",
                "description": "활성 PKA가 세포질 표적 효소와 핵 내 CREB 전사인자를 인산화해 세포 반응을 완성합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 90,
                "y": 320,
            },
        ],
        "edges": [
            {"id": "e1_2", "from": "step1_ligand_gpcr", "to": "step2_gs_activation", "label": "구조 변화 전달 (GEF)"},
            {"id": "e2_3", "from": "step2_gs_activation", "to": "step3_subunit_dissociation", "label": "GTP 결합"},
            {"id": "e3_4", "from": "step3_subunit_dissociation", "to": "step4_adenylyl_cyclase", "label": "Gαs-GTP 이동"},
            {"id": "e4_5", "from": "step4_adenylyl_cyclase", "to": "step5_camp_pka", "label": "ATP → cAMP 생성"},
            {"id": "e5_6", "from": "step5_camp_pka", "to": "step6_target_response", "label": "촉매 서브유닛 유리"},
        ],
        "annotations": [
            {
                "id": "note_sot_gpcr",
                "targetId": "step3_subunit_dissociation",
                "title": "핵심 분기점",
                "body": "Gαs-GTP 분리가 일어나야 하위 Adenylyl Cyclase 및 cAMP 증폭이 시작됩니다.",
                "badge": "SOT-GPCR-01",
            }
        ],
        "comparison": None,
        "anatomy": None,
    }


def build_gpcr_compare_scene() -> dict[str, Any]:
    base = build_gpcr_core_scene()
    base["sceneType"] = "compare"
    base["title"] = "GPCR 신호 전달: 정상 활성화 vs 길항제 차단 비교"
    base["subtitle"] = "리간드 결합에 의한 cAMP-PKA 증폭 경로와 경쟁적 길항제(Antagonist) 차단 상태의 대조"
    base["sourceIds"] = ["SOT-GPCR-01", "SOT-GPCR-03"]
    base["comparison"] = {
        "leftTitle": "정상 Gs 신호 활성화 (Agonist 결합)",
        "leftStatus": "ACTIVE",
        "leftSummary": "리간드 결합 → Gαs-GTP 분리 → Adenylyl Cyclase 활성 → cAMP 상승 → PKA 인산화 반응 진행",
        "leftSteps": [
            {"step": "1. 수용체 결합", "state": "Agonist 결합 (활성 7TM 구조)", "status": "active"},
            {"step": "2-3. Gs 단백질", "state": "GDP 방출 · GTP 결합 · Gαs-GTP 분리", "status": "active"},
            {"step": "4. Adenylyl Cyclase", "state": "촉매 활성화 (ATP → cAMP 다량 합성)", "status": "active"},
            {"step": "5-6. PKA & 표적", "state": "촉매 서브유닛 유리 → CREB/표적 인산화", "status": "active"},
        ],
        "rightTitle": "수용체 길항제 차단 (Antagonist 점유)",
        "rightStatus": "BLOCKED",
        "rightSummary": "길항제가 결합 포켓을 점유해 구조 변화 차단 → Gαs-GDP 삼량체 유지 → cAMP 미생성 → 하위 반응 억제",
        "rightSteps": [
            {"step": "1. 수용체 결합", "state": "Antagonist 점유 (비활성 구조 고정)", "status": "blocked"},
            {"step": "2-3. Gs 단백질", "state": "Gαs-GDP · Gβγ 삼량체 해리 불능", "status": "blocked"},
            {"step": "4. Adenylyl Cyclase", "state": "기저 상태 유지 (cAMP 농도 상승 없음)", "status": "blocked"},
            {"step": "5-6. PKA & 표적", "state": "R2C2 비활성 복합체 유지 (하위 인산화 중단)", "status": "blocked"},
        ],
    }
    return base


def build_shoulder_subscapularis_scene(ghost_superficial: bool = True) -> dict[str, Any]:
    superficial_labels = {
        "pectoralis_major_r": ("우측 대흉근 (표층 가림근)", "#c85a50"),
        "pectoralis_minor_r": ("우측 소흉근 (중간층 가림근)", "#c4564c"),
        "clavicular_part_of_deltoid_r": ("우측 전면 삼각근 (쇄골부)", "#c25248"),
        "deltoid_r": ("우측 삼각근", "#c25248"),
        "ribs_1_to_5_r": ("우측 1~5번 늑골 (전방 흉벽)", "#efe7d6"),
        "costal_cartilages_1_to_5_r": ("우측 1~5번 늑연골", "#dce6ea"),
        "serratus_anterior_r": ("우측 전거근", "#c4584e"),
        "biceps_brachii_r": ("우측 상완이두근", "#cc5c52"),
        "coracobrachialis_r": ("우측 오구완근", "#cc5c52"),
    }
    states: dict[str, dict[str, Any]] = {
        "subscapularis_r": {
            "visible": True,
            "opacity": 1.0,
            "highlighted": True,
            "color": "#e11d48",
            "category": "rotator_cuff",
            "labelKo": "우측 견갑하근 (심부 표적)",
        },
        "supraspinatus_r": {
            "visible": True,
            "opacity": 0.92,
            "highlighted": False,
            "color": "#d9534f",
            "category": "rotator_cuff",
            "labelKo": "우측 극상근 (회전근개)",
        },
        "infraspinatus_r": {
            "visible": True,
            "opacity": 0.92,
            "highlighted": False,
            "color": "#d9534f",
            "category": "rotator_cuff",
            "labelKo": "우측 극하근 (회전근개)",
        },
        "teres_minor_r": {
            "visible": True,
            "opacity": 0.92,
            "highlighted": False,
            "color": "#d9534f",
            "category": "rotator_cuff",
            "labelKo": "우측 소원근 (회전근개)",
        },
        "scapula_r": {
            "visible": True,
            "opacity": 0.95,
            "highlighted": False,
            "color": "#efe7d6",
            "category": "bone",
            "labelKo": "우측 견갑골 (뼈)",
        },
        "humerus_r": {
            "visible": True,
            "opacity": 0.95,
            "highlighted": False,
            "color": "#efe7d6",
            "category": "bone",
            "labelKo": "우측 상완골 (뼈)",
        },
        "clavicle_r": {
            "visible": True,
            "opacity": 0.72,
            "highlighted": False,
            "color": "#efe7d6",
            "category": "bone",
            "labelKo": "우측 쇄골 (뼈)",
        },
        "axillary_artery_r": {
            "visible": True,
            "opacity": 0.96,
            "highlighted": False,
            "color": "#ef4444",
            "category": "artery",
            "labelKo": "우측 액와동맥 (혈관)",
        },
        "axillary_nerve_r": {
            "visible": True,
            "opacity": 0.96,
            "highlighted": False,
            "color": "#facc15",
            "category": "nerve",
            "labelKo": "우측 액와신경 (신경)",
        },
    }
    for sid, (label_ko, hex_color) in superficial_labels.items():
        states[sid] = {
            "visible": True,
            "opacity": 0.16 if ghost_superficial else 0.95,
            "highlighted": False,
            "color": hex_color,
            "labelKo": label_ko,
        }

    return {
        "sceneType": "anatomy_3d",
        "domain": "anatomy_3d",
        "title": (
            "우측 견갑하근 심부 위치: 전면 가림 근육 반투명 비교"
            if ghost_superficial
            else "우측 어깨 전면 표준 해부 구조 (표층 근육 포함)"
        ),
        "subtitle": (
            "대흉근·소흉근·삼각근·전방 늑골을 16% 반투명 처리하여 견갑하와(Subscapular fossa)에 위치한 견갑하근을 노출"
            if ghost_superficial
            else "표층 근육과 흉벽에 가려져 전면에서 견갑하근이 직접 보이지 않는 상태"
        ),
        "sourceIds": ["SOT-ANAT-01", "SOT-ANAT-02"],
        "groundingMode": "strict_sot",
        "camera": {
            "preset": "right_anterior_oblique",
            "position": [-0.36, 1.38, 0.58],
            "target": [-0.14, 1.34, -0.05],
            "fov": 38,
        },
        "nodes": [
            {
                "id": "subscapularis_r",
                "stepNumber": 1,
                "label": "우측 견갑하근 (Subscapularis)",
                "sublabel": "견갑하와(전면 심부) → 상완골 소결절",
                "category": "target_muscle",
                "compartment": "심부 회전근개 (Deep Layer)",
                "description": "견갑골 앞쪽 오목면(견갑하와)에 밀착되어 있어 전면 표층 근육과 흉벽 뒤쪽에 가려집니다.",
                "highlighted": True,
                "expanded": False,
                "opacity": 1.0,
                "x": 140,
                "y": 180,
            },
            {
                "id": "pectoralis_major_r",
                "stepNumber": 2,
                "label": "대흉근 · 소흉근 (전면 가림층)",
                "sublabel": "투명도 16% 반투명화" if ghost_superficial else "표층 100% 불투명",
                "category": "occluder",
                "compartment": "전방 표층 흉벽",
                "description": "어깨와 흉곽 전면을 덮어 견갑하근으로의 전면 시야를 가리는 표층 근육군입니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 0.16 if ghost_superficial else 0.95,
                "x": 400,
                "y": 140,
            },
            {
                "id": "ribs_1_to_5_r",
                "stepNumber": 3,
                "label": "우측 1~5번 늑골 (흉벽 장벽)",
                "sublabel": "견갑하근 전면과 마주 보는 골격",
                "category": "bone_barrier",
                "compartment": "흉곽 골격",
                "description": "견갑하근의 전면과 흉벽 사이를 가로막는 늑골 구조물입니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 0.16 if ghost_superficial else 0.95,
                "x": 400,
                "y": 280,
            },
        ],
        "edges": [
            {"id": "occ_1", "from": "pectoralis_major_r", "to": "subscapularis_r", "label": "전면 시야 가림 (Ghosting 처리)"},
            {"id": "occ_2", "from": "ribs_1_to_5_r", "to": "subscapularis_r", "label": "전방 흉벽 장벽"},
        ],
        "annotations": [
            {
                "id": "anat_note_1",
                "targetId": "subscapularis_r",
                "title": "전면 가림 해소",
                "body": "대흉근·소흉근·삼각근 및 늑골을 반투명(16%)으로 낮춰 심부 견갑하근을 노출했습니다.",
                "badge": "SOT-ANAT-01",
            }
        ],
        "comparison": None,
        "anatomy": {
            "modelId": "z-anatomy-shoulder-v1",
            "glbUrl": "/assets/shoulder.glb",
            "focusedStructureId": "subscapularis_r",
            "ghostSuperficial": ghost_superficial,
            "structureStates": states,
            "safetyNotice": "임의의 바늘 궤적이나 자입 깊이(cm)는 생성하지 않으며 검증된 해부학적 층위만 표시합니다 (SOT-ANAT-03).",
        },
    }


def build_shoulder_rotator_cuff_scene() -> dict[str, Any]:
    scene = build_shoulder_subscapularis_scene(ghost_superficial=True)
    scene["title"] = "우측 회전근개 (SITS 4대 근육) 입체 구성"
    scene["subtitle"] = "견갑하근 · 극상근 · 극하근 · 소원근의 공간 배치와 상완골두 안정화"
    scene["sourceIds"] = ["SOT-ANAT-02", "SOT-ANAT-01"]
    sits_ids = ["subscapularis_r", "supraspinatus_r", "infraspinatus_r", "teres_minor_r"]
    for sid in sits_ids:
        scene["anatomy"]["structureStates"].setdefault(sid, {})
        scene["anatomy"]["structureStates"][sid].update({
            "visible": True,
            "opacity": 1.0,
            "highlighted": True,
            "color": "#e11d48",
        })
    return scene


def build_async_queue_scene() -> dict[str, Any]:
    return {
        "sceneType": "diagram",
        "domain": "system_architecture",
        "title": "비동기 작업 큐 & 워커 백프레셔 처리 흐름",
        "subtitle": "급증하는 요청을 메시지 큐로 완충하고 워커 풀과 DLQ로 안정성을 확보하는 구조",
        "sourceIds": ["SOT-SYS-01"],
        "groundingMode": "strict_sot",
        "camera": {"zoom": 1.0, "panX": 0, "panY": 0, "preset": "overview"},
        "nodes": [
            {
                "id": "sys_step1_producer",
                "stepNumber": 1,
                "label": "Client & API Gateway",
                "sublabel": "비동기 요청 접수 (202 Accepted)",
                "category": "ingress",
                "compartment": "Edge Layer",
                "description": "클라이언트 요청을 동기 대기 없이 검증 후 즉시 큐에 발행합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 90,
                "y": 180,
            },
            {
                "id": "sys_step2_queue",
                "stepNumber": 2,
                "label": "Message Queue (버퍼링)",
                "sublabel": "트래픽 스파이크 흡수 · 백프레셔 제어",
                "category": "queue",
                "compartment": "Broker Layer",
                "description": "생산 속도가 소비 속도를 초과할 때 큐 길이를 모니터링하며 부하를 완충합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 310,
                "y": 180,
                "detailChildren": [
                    {
                        "id": "sys_step2a_partition",
                        "label": "2-A. 우선순위 파티션 분리",
                        "detail": "실시간 대화형 작업과 배치 작업을 별도 큐로 분리",
                    },
                    {
                        "id": "sys_step2b_visibility",
                        "label": "2-B. Visibility Timeout & ACK",
                        "detail": "워커 장애 시 미확인 메시지를 자동으로 재전달",
                    },
                ],
            },
            {
                "id": "sys_step3_workers",
                "stepNumber": 3,
                "label": "Worker Pool (병렬 소비)",
                "sublabel": "오토스케일링 작업 실행기",
                "category": "compute",
                "compartment": "Worker Layer",
                "description": "처리 가능한 속도로 작업을 가져와 실행하고 결과를 저장소에 기록합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 530,
                "y": 140,
            },
            {
                "id": "sys_step4_dlq",
                "stepNumber": 4,
                "label": "Dead Letter Queue (DLQ)",
                "sublabel": "반복 실패 메시지 격리 · 알림",
                "category": "fallback",
                "compartment": "Recovery Layer",
                "description": "최대 재시도 횟수를 초과한 독성 메시지(Poison Pill)를 격리해 큐 정체를 방지합니다.",
                "highlighted": False,
                "expanded": False,
                "opacity": 1.0,
                "x": 530,
                "y": 300,
            },
        ],
        "edges": [
            {"id": "se1", "from": "sys_step1_producer", "to": "sys_step2_queue", "label": "Enqueue"},
            {"id": "se2", "from": "sys_step2_queue", "to": "sys_step3_workers", "label": "Pull & Process"},
            {"id": "se3", "from": "sys_step2_queue", "to": "sys_step4_dlq", "label": "Max Retries 초과 시 격리"},
        ],
        "annotations": [
            {
                "id": "sys_note_1",
                "targetId": "sys_step2_queue",
                "title": "백프레셔 핵심",
                "body": "큐 깊이를 기준으로 워커 오토스케일링과 유입 속도 제한을 동작시킵니다.",
                "badge": "SOT-SYS-01",
            }
        ],
        "comparison": None,
        "anatomy": None,
    }


PROCEDURE_TEMPLATES: list[dict[str, Any]] = [
    {
        "templateId": "gpcr_gs_camp_pka",
        "domain": "biology_pathway",
        "title": "GPCR (Gs) → Adenylyl Cyclase → cAMP → PKA 신호 전달",
        "description": "리간드 결합부터 Gαs-GTP 해리, cAMP 생성, PKA 활성화까지 6단계 표준 도식",
        "sourceIds": ["SOT-GPCR-01", "SOT-GPCR-02"],
        "steps": [
            "리간드 결합 및 7TM 수용체 구조 변화",
            "Gs 단백질 GDP 방출 및 GTP 결합",
            "Gαs-GTP와 Gβγ 분리 및 이동",
            "Adenylyl Cyclase 활성화 (ATP → cAMP)",
            "cAMP 결합에 의한 PKA 촉매 서브유닛 해리",
            "표적 단백질 및 CREB 전사인자 인산화",
        ],
    },
    {
        "templateId": "gpcr_antagonist_comparison",
        "domain": "biology_pathway",
        "title": "GPCR 정상 활성화 vs 길항제(Antagonist) 신호 차단 비교",
        "description": "정상 Agonist 신호 전달과 경쟁적 길항제에 의한 하위 신호 억제를 좌우 나란히 비교",
        "sourceIds": ["SOT-GPCR-01", "SOT-GPCR-03"],
        "steps": [
            "수용체 점유 상태 비교 (Agonist vs Antagonist)",
            "Gs 삼량체 분리 여부 비교",
            "Adenylyl Cyclase 및 cAMP 농도 변화 비교",
            "PKA 하위 인산화 반응 비교",
        ],
    },
    {
        "templateId": "shoulder_subscapularis_reveal",
        "domain": "anatomy_3d",
        "title": "우측 견갑하근 심부 노출 (전면 표층 근육 반투명화)",
        "description": "대흉근·소흉근·삼각근 및 전방 늑골을 반투명 처리하여 견갑하와 심부의 견갑하근 위치를 설명",
        "sourceIds": ["SOT-ANAT-01", "SOT-ANAT-02", "SOT-ANAT-03"],
        "steps": [
            "전면 표준 시점 확인 (표층 근육에 의한 가림)",
            "대흉근·소흉근·삼각근 16% 반투명화",
            "전방 1~5번 늑골 반투명화 및 견갑하근 강조",
            "액와 신경·혈관 안전 구역 확인 (침습 바늘 경로 미생성)",
        ],
    },
    {
        "templateId": "shoulder_rotator_cuff_sits",
        "domain": "anatomy_3d",
        "title": "회전근개 4대 근육 (SITS) 입체 비교",
        "description": "견갑하근, 극상근, 극하근, 소원근의 부착 부위와 기능적 역할을 3D로 확인",
        "sourceIds": ["SOT-ANAT-02"],
        "steps": [
            "견갑하근 (전면 내회전)",
            "극상근 (상부 외전 개시)",
            "극하근 및 소원근 (후면 외회전)",
        ],
    },
    {
        "templateId": "async_queue_backpressure",
        "domain": "system_architecture",
        "title": "비동기 작업 큐 및 워커 백프레셔 아키텍처",
        "description": "API Gateway, Message Queue, Worker Pool, DLQ로 구성된 비동기 처리 흐름도",
        "sourceIds": ["SOT-SYS-01"],
        "steps": [
            "Producer & API Gateway 비동기 접수",
            "Message Queue 버퍼링 및 백프레셔",
            "Worker Pool 병렬 소비",
            "Dead Letter Queue 격리 및 복구",
        ],
    },
]
