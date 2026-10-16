"""
Authoritative Source-of-Truth documents and CONTEXT.md presets for CliniView Live.
Users can also edit these live in the UI or upload their own .md / .txt files.
"""

PRESETS = {
    "mode_a_clinic": {
        "id": "mode_a_clinic",
        "title": "Mode A · 한의원 근골격계 진료실 (견갑하근·회전근개 설명)",
        "subtitle": "환자 맞춤형 근육 분리·투명도 조절·내회전 기전 및 치료 포인트 3D/인터랙티브 설명",
        "badge": "Clinical Patient Communication",
        "default_voice_prompt": (
            "환자분 왼쪽 어깨 앞쪽 깊숙한 통증이 회전근개 중에서도 '견갑하근(Subscapularis)' 문제 때문이라는 걸 설명하려고 해. "
            "견갑골 앞쪽 면(견갑하와)에서 시작해서 상완골 소결절에 붙는 구조랑, 팔을 안으로 돌리는 내회전 작용, "
            "그리고 열중쉬어 동작(Lift-off)에서 왜 아픈지, 오늘 침 치료할 핵심 포인트를 주변 근육(삼각근·대흉근·극상근)은 "
            "반투명 슬라이더로 조절해서 볼 수 있게 3D 인터랙티브 뷰어로 만들어줘."
        ),
        "quick_prompts": [
            {
                "label": "견갑하근(Subscapularis) 단독 분리 & 내회전·침 치료 포인트 설명",
                "prompt": (
                    "환자분 어깨 전면 심부 통증의 원인인 견갑하근(Subscapularis)을 설명할 거야. "
                    "견갑골 전면(견갑하와) 기시부부터 상완골 소결절 정지부까지 하이라이트하고, "
                    "삼각근과 대흉근 등 겉 근육은 투명도 슬라이더로 뺄 수 있게 해줘. "
                    "팔을 안으로 돌리는 내회전(Internal Rotation) 및 열중쉬어(Lift-off) 각도 슬라이더와 "
                    "액와 전연 안전 치료 포인트·통증 방사 구역을 클릭해서 볼 수 있는 3D 인터랙티브 화면을 만들어줘."
                ),
            },
            {
                "label": "회전근개 4대 근육(SITS) 비교 & 극상근 외전 충돌 증후군 설명",
                "prompt": (
                    "환자분께 회전근개 4개 근육(견갑하근, 극상근, 극하근, 소원근) 중 왜 견갑하근과 극상근이 함께 긴장했는지 비교해서 보여줘. "
                    "4개 근육을 각각 켜고 끄거나 투명도를 조절하는 토글과, 팔을 옆으로 들어올릴 때(외전) 상완골두를 아래로 잡아주는 "
                    "견갑하근의 동적 안정화 역할을 시뮬레이션으로 보여줘."
                ),
            },
        ],
        "source_of_truth": """# [SOURCE OF TRUTH] 회전근개(Rotator Cuff) 및 견갑하근(Subscapularis) 임상 해부학·침구 치료 레퍼런스

## [SOT-01] 회전근개 4대 근육(SITS) 구조 및 기능 개요
회전근개(Rotator cuff)는 견관절(Glenohumeral joint)을 감싸며 동적 안정성(Dynamic stability)을 제공하는 4개의 핵심 근육군이다.
1. **견갑하근 (Subscapularis)** — 견갑골 전면(유일한 전면 회전근개) / 상완골 소결절 정지 / 강력한 **내회전(Internal rotation)** 및 상완골두 전방·상방 전위 억제
2. **극상근 (Supraspinatus)** — 견갑골 후면 극상와(Supraspinous fossa) 기시 / 상완골 대결절 상면 정지 / 견관절 **외전(Abduction, 초기 0°~15°)** 개시
3. **극하근 (Infraspinatus)** — 견갑골 후면 극하와(Infraspinous fossa) 기시 / 상완골 대결절 중면 정지 / 견관절 **외회전(External rotation)**
4. **소원근 (Teres minor)** — 견갑골 외측연 상부 기시 / 상완골 대결절 하면 정지 / 견관절 **외회전(External rotation)** 및 내전 보조

## [SOT-02] 견갑하근 (Subscapularis) 정밀 해부학
- **기시 (Origin)**: 견갑골 전면의 오목한 면인 **견갑하와(Subscapular fossa)** 전체 영역 (늑골면과 마주 보는 견갑골 앞면)
- **정지 (Insertion)**: 상완골 근위부 전면의 **소결절(Lesser tubercle of humerus)** 및 견관절낭(Joint capsule) 전면부
- **신경지배 (Innervation)**: **상견갑하신경 및 하견갑하신경 (Upper and lower subscapular nerves, C5–C6)** — 완신경총 후신경속(Posterior cord) 분지
- **주요 작용 (Primary Actions)**:
  1. **견관절 내회전 (Internal / Medial rotation of humerus)**: 회전근개 중 가장 단면적이 크고 강력한 내회전 주동근
  2. **동적 관절 안정화 (Dynamic Humeral Head Stabilization)**: 삼각근(Deltoid)이 팔을 들어올릴 때 상완골두(Humeral head)가 위로 딸려 올라가거나 앞으로 빠지지 않도록 아래·뒤쪽으로 잡아당기는 하방 압박력(Depressor force couple) 제공
  3. **외전 및 내전 보조**: 팔의 위치에 따라 전방 관절낭 보호

## [SOT-03] 견갑하근 임상 증상 및 이학적 검사 (Clinical Presentation & Tests)
- **특징적 통증 양상 (Pain & Referred Pain Pattern)**:
  - **어깨 전면 심부 통증 (Deep anterior shoulder pain)**: 환자가 "어깨 앞쪽 깊숙한 곳이 쑤신다"고 표현하나 겉 근육(삼각근·대흉근)에 가려져 직접 만지기 어려움
  - **연관통 (Referred pain)**: 견갑골 후면(어깨뼈 뒤쪽), 상완 후면, 그리고 **손목 등쪽(Dorsal aspect of the wrist)**까지 띠 모양의 방사통이 특징적으로 나타남
- **동작 제한 및 이학적 검사**:
  - **열중쉬어 동작 제한 / Gerber's Lift-off Test**: 손등을 허리 뒤(요추부)에 대고 손바닥을 뒤로 밀어 올리는 동작에서 통증 또는 근력 약화 발생
  - **Belly-Press Test (Napoleon Test)**: 손바닥으로 배를 누르면서 팔꿈치를 앞으로 유지하는 검사에서 견갑하근 기능 저하 시 팔꿈치가 뒤로 빠짐
  - 투구 동작(야구·배드민턴·테니스 스매싱) 또는 장시간 라운드 숄더(내회전 단축 자세)에서 과부하 빈발

## [SOT-04] 한의학적 치료 포인트 및 해부학적 주의사항 (Acupuncture & Trigger Point Therapy)
- **심부 통증유발점 (Myofascial Trigger Points — TrP1, TrP2, TrP3)**:
  - **외측연 TrP (Lateral border cluster)**: 견갑골 외측연(겨드랑이 뒤쪽 주름 깊숙한 앞면)을 따라 위치
  - **상완골 소결절 부착부 (Tendinous insertion point)**: 오구돌기(Coracoid process) 외하방, 결절간구 내측의 소결절 정지 건 부위
- **한의원 자침 및 도침/약침 접근법**:
  - **측와위 또는 앙와위 외전 자세**: 환자의 팔을 약간 외전·외회전시켜 견갑골을 외측으로 유도한 뒤, 광배근·대원근 전연과 흉벽 사이(액와 후벽 전면)로 견갑골 늑골면(견갑하와)을 향해 안전하게 사자(Oblique insertion)
  - **전면 소결절 접근**: 팔을 외회전시켜 소결절을 전면으로 노출한 뒤 정지부 건 주위 치료
  - **협조 경혈**: 극천(HT1, 액와 신경·혈관 주의하여 외측 후방 안전구역 활용), 천종(SI11), 견우(LI15), 견전(Ex-UE), 수삼리(LI10)/곡지(LI11)
- **안전 수칙 (Safety Guardrails)**:
  - 액와(Axilla) 중앙의 액와동맥(Axillary artery) 및 완신경총(Brachial plexus) 주행 부위를 반드시 피하고 견갑골 골면(견갑하와)을 기준점(Bony landmark)으로 삼아 자침할 것.
  - 본 시각 자료는 담당 한의사의 진료 설명을 돕는 교육·소통 보조 도구이며, 단독 자동 진단을 대체하지 않음.
""",
        "context_md": """# [CONTEXT.md] 진료실 환자 설명 코파일럿 설정 (가천대 한의대 클리닉 프로토콜)

## 1. 사용자(술자) 및 대상(환자) 정의
- **사용자(Clinician)**: 한의원 진료실에서 근골격계 통증 환자에게 병태생리와 오늘 시행할 침/약침/추나 치료 부위를 설명하는 한의사
- **대상(Patient)**: 의학 용어가 낯설고 "왜 어깨 앞쪽이 아픈데 겨드랑이 안쪽이나 어깨뼈 앞면을 치료하는지" 직관적으로 이해하고 싶은 환자

## 2. 왜 기존 도구(Complete Anatomy 등) 대신 이 뷰어가 필요한가?
- 기존 3D 아틀라스는 수백 개 근육이 한꺼번에 렌더링되어 진료 중 30초 안에 삼각근·대흉근·늑골을 투명하게 빼고 **오직 환자에게 해당하는 근육(예: 견갑하근)과 기시·정지·치료 포인트만 하이라이트**하기가 번거로움.
- 따라서 생성되는 인터랙티브 뷰어는 **클릭 한 번으로 겉 근육(삼각근·대흉근) 투명도를 조절**하고, **견갑골 전면(견갑하와) → 상완골 소결절 주행 경로**와 **내회전/열중쉬어 동작 메커니즘**을 즉시 조작할 수 있어야 함.

## 3. 인터랙티브 시각 디자인 및 기능 필수 요건
1. **3D / Interactive Anatomy Canvas**:
   - 견갑골(Scapula), 상완골(Humerus, 소결절·대결절 구분), 쇄골(Clavicle)의 입체적 골격 구조 표현
   - **타겟 근육(견갑하근 Subscapularis)**: 에메랄드/시안 네온 컬러로 견갑골 전면(견갑하와)에서 상완골 소결절까지 근육 섬유 결을 따라 선명하게 하이라이트
   - **주변 근육 레이어 컨트롤**: 삼각근(Deltoid), 대흉근(Pectoralis major), 기타 회전근개(극상근·극하근·소원근)의 **투명도 슬라이더(0~100%)** 및 ON/OFF 토글 제공
   - **동작 시뮬레이션 슬라이더**: 팔의 내회전(Internal Rotation) / 외회전(External Rotation) 각도 조절 및 '열중쉬어(Lift-off test)' 자세 시 근육 수축·신장 시각화
   - **클릭형 임상 핫스팟 핀(Hotspots)**: ① 기시부(견갑하와), ② 정지부(상완골 소결절), ③ 액와 외측연 치료 포인트(TrP), ④ 손목/견갑 후면 연관통(Referred pain) 클릭 시 상세 설명 카드 표시
2. **언어 및 톤앤매너**:
   - 모든 주요 해부학 명칭은 **한국어(영어 병기)**로 표기 (예: `견갑하근 (Subscapularis)`, `상완골 소결절 (Lesser Tubercle)`)
   - 환자 눈높이의 친절한 한 줄 요약과 원문 근거 번호(`[SOT-01]` ~ `[SOT-04]`)를 반드시 표기할 것.
""",
    },
    "mode_b_gpcr": {
        "id": "mode_b_gpcr",
        "title": "Mode B · 의학·바이오 라이브 학술 발표 (mRNA 백신 발표 중 즉석 GPCR 경로 생성)",
        "subtitle": "슬라이드 발표 도중 청중 질문/보충 설명에 맞춰 1분 내 단계별 세포 신호전달 인터랙티브 다이어그램 생성",
        "badge": "Live Academic Presentation",
        "default_voice_prompt": (
            "지금 COVID-19 mRNA 백신 면역 반응 슬라이드를 발표 중인데, 청중에서 세포막 수용체 신호전달 비교 질문이 나왔어. "
            "리간드가 GPCR(7-막관통 수용체)에 결합해서 G-protein 알파 서브유닛이 GDP를 버리고 GTP와 결합해 분리되고, "
            "Adenylyl cyclase를 활성화해서 ATP를 cAMP로 증폭시켜 PKA 신호전달을 켜는 5단계 패스웨이를 "
            "클릭하고 재생하면서 설명할 수 있는 인터랙티브 다이어그램으로 바로 띄워줘."
        ),
        "quick_prompts": [
            {
                "label": "GPCR (Gαs → Adenylyl Cyclase → cAMP → PKA) 5단계 신호전달 인터랙티브 시뮬레이터",
                "prompt": (
                    "발표 중 즉석 보충 슬라이드로 GPCR 신호전달 경로(G-protein coupled receptor pathway)를 설명해야 해. "
                    "세포막 인지질 이중층을 가로지르는 7개 막관통 알파 나선(TM1~TM7) 구조와 "
                    "Step 1(휴지기 GDP 결합) → Step 2(리간드 결합 및 수용체 구조 변화) → Step 3(GDP/GTP 교환 및 Gαs 분리) → "
                    "Step 4(Adenylyl Cyclase 활성화 및 ATP→cAMP 2차 전령 증폭) → Step 5(PKA 활성화 및 GTPase 종료)까지 "
                    "단계별 버튼과 자동 재생, cAMP 증폭 농도 슬라이더가 있는 인터랙티브 다이어그램을 만들어줘."
                ),
            },
            {
                "label": "mRNA-LNP 세포 내 전달(Endosomal Escape) vs 수용체 매개 신호전달 비교 뷰",
                "prompt": (
                    "COVID-19 mRNA 백신의 지질나노입자(LNP) 세포 유입·리보솜 스파이크 번역 경로와, "
                    "발현된 항원/사이토카인이 세포 표면 GPCR 수용체를 자극해 하위 cAMP-PKA 신호를 전달하는 과정을 "
                    "한 화면에서 나란히 비교하고 단계별로 클릭해 볼 수 있는 인터랙티브 다이어그램을 만들어줘."
                ),
            },
        ],
        "source_of_truth": r"""# [SOURCE OF TRUTH] mRNA 백신 메커니즘 및 GPCR (G-Protein Coupled Receptor) 신호전달 경로 학술 레퍼런스

## [SOT-10] 발표 배경 컨텍스트: COVID-19 mRNA 백신 작용 기전
- 지질나노입자(LNP, Lipid Nanoparticle)에 봉입된 뉴클레오시드 변형 mRNA(N1-methylpseudouridine)가 근육 주사 후 세포 내 엔도사이토시스(Endocytosis)로 유입됨.
- 엔도솜 탈출(Endosomal escape) 후 세포질 내 리보솜(Ribosome)에서 SARS-CoV-2 스파이크(Spike) 단백질로 번역되며, 프로테아좀 분해를 거쳐 MHC Class I 및 MHC Class II 경로로 항원이 제시됨.
- 이 과정에서 분비되는 케모카인·사이토카인 및 생리활성 리간드들은 표적 면역세포 표면의 **GPCR (G-Protein Coupled Receptor)** 등 막 수용체를 통해 세포 내 신호전달(Signal transduction)을 개시함.

## [SOT-11] GPCR (G-단백질 결합 수용체) 구조적 특징
- **7-막관통 도메인 (7-Transmembrane $\alpha$-Helices, TM1–TM7)**: 세포막 인지질 이중층(Phospholipid bilayer)을 7번 관통하는 단일 폴리펩타이드 사슬 구조
- **세포외 도메인 (Extracellular domain & Ligand pocket)**: N-말단 및 세포외 루프(ECL1–ECL3)가 제1전령(First messenger / Agonist ligand: 호르몬, 신경전달물질, 케모카인 등)과 결합
- **세포내 도메인 및 이종삼량체 G-단백질 (Heterotrimeric G-Protein)**: C-말단 및 세포내 루프(특히 ICL3)가 세포막 내측에 고정된 **$G\alpha, G\beta, G\gamma$ 삼량체 복합체**와 상호작용

## [SOT-12] GPCR — $G\alpha_s$ / cAMP / PKA 신호전달 5단계 메커니즘 (Canonical Pathway)
1. **Step 1 — 휴지기 상태 (Resting / Inactive State)**:
   - 수용체(GPCR)에 리간드가 결합하지 않은 상태.
   - $G\alpha$ 서브유닛의 뉴클레오타이드 결합 포켓에 **GDP (Guanosine diphosphate)**가 결합되어 있으며, $G\beta\gamma$ 이량체(Dimer)와 결합한 불활성 삼량체($G\alpha_{\text{GDP}}\beta\gamma$) 상태를 유지함.
2. **Step 2 — 리간드 결합 및 수용체 구조 변화 (Ligand Binding & Conformational Shift)**:
   - 세포외 리간드(Agonist)가 GPCR 결합 포켓에 결합함.
   - 막관통 나선(특히 **TM5 및 TM6**)이 바깥쪽으로 회전·이동하는 구조적 변화(Conformational change)가 일어나 수용체가 **구아닌 뉴클레오타이드 교환 인자(GEF, Guanine nucleotide exchange factor)**로 작동함.
3. **Step 3 — GDP-GTP 교환 및 G-단백질 해리 (Nucleotide Exchange & Subunit Dissociation)**:
   - 활성화된 GPCR이 $G\alpha$ 서브유닛의 구조를 열어 **GDP를 방출**시키고, 세포질 내 농도가 높은 **GTP (Guanosine triphosphate)**가 결합함.
   - GTP 결합으로 인해 **$G\alpha_s\text{-GTP}$ 활성 서브유닛**과 **$G\beta\gamma$ 이량체**가 서로 분리(Dissociation)되어 세포막 내측면을 따라 표적 효소로 이동함.
4. **Step 4 — 이펙터 효소 활성화 및 2차 전령 증폭 (Adenylyl Cyclase Activation & cAMP Amplification)**:
   - 분리된 **$G\alpha_s\text{-GTP}$**가 막 결합 효소인 **아데닐산 고리화효소(Adenylyl Cyclase, AC)**에 결합하여 활성화함.
   - Adenylyl Cyclase는 기질인 **ATP**를 고리형 AMP인 **cAMP (3',5'-cyclic adenosine monophosphate, 제2전령 / Second messenger)**와 피로인산($\text{PP}_i$)으로 빠르게 전환함 (1개의 수용체 활성화가 수백~수천 분자의 cAMP를 생성하는 신호 증폭 효과).
5. **Step 5 — PKA 인산화 캐스케이드 및 신호 종료 (PKA Activation & Signal Termination)**:
   - 생성된 **cAMP 4분자**가 불활성 **PKA (Protein Kinase A)**의 조절 서브유닛($R_2$)에 결합하면, 활성 **촉매 서브유닛($C_2$, Catalytic subunits)**이 분리되어 세포질 및 핵 내 표적 단백질(예: 전사인자 **CREB**)을 인산화(Phosphorylation)함.
   - **신호 종료(Termination)**: $G\alpha$ 서브유닛의 내재적 **GTPase 활성**(RGS 단백질에 의해 가속)이 GTP를 다시 **GDP + $\text{P}_i$**로 가수분해하여 $G\alpha_{\text{GDP}}\beta\gamma$ 휴지기 삼량체로 재결합하며, **포스포디에스테라아제(PDE, Phosphodiesterase)**가 cAMP를 5'-AMP로 분해하여 신호를 초기화함.
""",
        "context_md": r"""# [CONTEXT.md] 의학·생명과학 라이브 학술 발표 비서 설정

## 1. 사용자(발표자) 및 대상(청중) 정의
- **사용자(Presenter)**: COVID-19 mRNA 백신 면역학 슬라이드를 발표 중인 의학·생명과학 연구자
- **대상(Audience)**: 학회/세미나 참석 연구자 및 학생. 발표 도중 나온 질문이나 심화 기전(예: GPCR 신호전달 경로)을 정적인 텍스트가 아닌 **단계별 애니메이션 다이어그램**으로 즉석에서 보며 이해하고자 함.

## 2. 인터랙티브 시각 디자인 및 기능 필수 요건
1. **Live Pathway State Machine (Step 1 ~ Step 5 인터랙티브 컨트롤)**:
   - 상단 또는 하단에 **Step 1 (Resting) → Step 2 (Ligand Binding) → Step 3 (GDP→GTP & Dissociation) → Step 4 (Adenylyl Cyclase & cAMP Burst) → Step 5 (PKA Cascade & GTPase Reset)** 단계별 버튼 및 **Auto-Play / Pause** 버튼 필수 제공
   - **신호 증폭 슬라이더 (Ligand Concentration / cAMP Amplification Gain)**: 리간드 자극 강도에 따라 ATP → cAMP 입자 생성 속도와 PKA/CREB 활성도가 실시간으로 변하는 시각적 피드백 제공
2. **시각적 구성 요소 (Canvas / SVG / 3D Molecular View)**:
   - 세포외 공간(Extracellular) / 세포막 인지질 이중층(Phospholipid Bilayer) / 세포질(Cytosol) / 핵(Nucleus - CREB) 구획을 명확히 구분
   - 7-막관통 나선(TM1–TM7), 리간드(Agonist), $G\alpha_s$, $G\beta\gamma$, GDP/GTP 상태 배지, Adenylyl Cyclase, cAMP 확산 입자, PKA ($R_2C_2$), PDE/GTPase 종료 루프를 직관적인 컬러 코딩과 부드러운 애니메이션으로 표현
   - 각 분자/단백질을 클릭하면 우측 또는 하단 패널에 **Source of Truth 근거 문장(`[SOT-10]` ~ `[SOT-12]`)**과 생화학적 역할이 즉시 표시되도록 구현할 것.
""",
    },
}
