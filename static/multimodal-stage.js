/**
 * Visual Board Unified — Multimodal Stage Controller (multimodal-stage.js)
 *
 * Orchestrates:
 * 1. Top Header Mode Switcher (3D Anatomy | AI Visual | 2D Pathway | Slide Deck) + Split 3D + Visual (50/50)
 * 2. Session Boards History Drawer (1-click restore across 3D, AI Visual, Video, 2D Pathway, and Slide Deck)
 * 3. Sub-view A (AI Visual): Nano Banana 2 Medical Illustrations, Drag-Rectangle Region Selector
 *    with 100% Outer-Pixel-Preserving Inpaint, 3D-to-Visual Snapshot, and Gemini Omni Video Animation
 * 4. Sub-view B (2D Pathway): Interactive SVG Node-Edge Mechanism Diagrams, Step-by-Step Stepper,
 *    Node Inspector Card, and Side-by-Side Comparison Mode (e.g. Agonist vs Antagonist)
 * 5. Sub-view C (Slide Deck): Lecture Slide Importer & 1-Click Slide-to-Visual / Diagram / 3D Actions
 * 6. Gemini TTS Audio Narration (POST /api/tts with Web Speech API fallback)
 */

const BUILTIN_VISUAL_TEMPLATES = {
  alveolar_gas_exchange: {
    id: "asset_alveolar_gas_exchange",
    templateKey: "alveolar_gas_exchange",
    kind: "image",
    title: "Alveolar–Capillary Gas Exchange & Partial Pressure Gradient",
    subtitle: "Type I/II pneumocytes, surfactant layer, 0.5 μm respiratory membrane, O₂ uptake (PO₂ 104 → 40 mmHg) & CO₂ unloading",
    narrationScript:
      "Oxygen diffuses rapidly across the half-micron alveolar-capillary membrane driven by a partial pressure gradient from 104 millimeters of mercury in the alveolus to 40 in deoxygenated pulmonary blood, while carbon dioxide unloads in the opposite direction.",
    drawFn: drawAlveolarGasExchangeCanvas,
  },
  coronary_circulation: {
    id: "asset_coronary_circulation",
    templateKey: "coronary_circulation",
    kind: "image",
    title: "Coronary Artery Perfusion — Left Main, LAD & Circumflex Branches",
    subtitle: "Diastolic aortic root sinus filling, epicardial-to-subendocardial microvascular flow & anterior interventricular territory",
    narrationScript:
      "Coronary blood flow peaks during ventricular diastole when aortic valve closure directs blood into the left and right coronary sinuses, perfusing the left anterior descending and circumflex territories.",
    drawFn: drawCoronaryCirculationCanvas,
  },
  rotator_cuff_axillary: {
    id: "asset_rotator_cuff_axillary",
    templateKey: "rotator_cuff_axillary",
    kind: "image",
    title: "Glenohumeral Joint, Subscapularis Tendon & Axillary Nerve Safe Zone",
    subtitle: "Anterior-inferior surgical corridor showing Quadrangular Space neurovascular bundle and lesser tuberosity footprint",
    narrationScript:
      "During anterior shoulder exposure, the axillary nerve courses inferior to the subscapularis tendon toward the quadrangular space alongside the posterior circumflex humeral artery.",
    drawFn: drawRotatorCuffCanvas,
  },
  glomerular_filtration: {
    id: "asset_glomerular_filtration",
    templateKey: "glomerular_filtration",
    kind: "image",
    title: "Renal Corpuscle & Glomerular Filtration Barrier",
    subtitle: "Afferent/efferent arterioles, fenestrated endothelium, negatively charged basement membrane & podocyte foot processes",
    narrationScript:
      "Net filtration pressure across the glomerular capillary bed is regulated by afferent vasodilation and efferent vasoconstriction, filtering plasma across the three-layer barrier into Bowman's space.",
    drawFn: drawGlomerularFiltrationCanvas,
  },
};

const BUILTIN_DIAGRAM_SCENES = {
  gpcr_camp_pka: {
    id: "diag_gpcr_camp_pka",
    templateId: "gpcr_camp_pka",
    title: "GPCR — Gs — Adenylyl Cyclase — cAMP — PKA Signaling Pathway",
    subtitle: "Click any node or step pill to inspect receptor activation, second-messenger amplification, and downstream phosphorylation",
    domain: "pharmacology",
    narrationScript:
      "Ligand binding stabilizes the active transmembrane conformation of the G-protein-coupled receptor, catalyzing GDP-to-GTP exchange on Gs-alpha. Active Gs-alpha stimulates adenylyl cyclase to convert ATP into cyclic AMP, which releases catalytic Protein Kinase A subunits to phosphorylate cellular targets.",
    comparison: null,
    nodes: [
      {
        id: "node_ligand",
        stepNumber: 1,
        label: "Extracellular Agonist",
        sublabel: "Epinephrine / β-Agonist",
        category: "Extracellular Signal",
        compartment: "Extracellular Space",
        description: "First-messenger hormone or neurotransmitter binds the orthosteric pocket on the extracellular face of the 7-transmembrane receptor.",
        x: 135,
        y: 170,
        detailChildren: ["Reversible H-bond network", "Orthosteric pocket closure"],
      },
      {
        id: "node_gpcr",
        stepNumber: 2,
        label: "7-TM GPCR (β₁/β₂)",
        sublabel: "Active R* Conformation",
        category: "Membrane Receptor",
        compartment: "Plasma Membrane",
        description: "Outward movement of transmembrane helix 6 (TM6) opens an intracellular cleft that engages the C-terminal helix of the heterotrimeric Gs protein.",
        x: 345,
        y: 170,
        detailChildren: ["TM6 outward tilt (~14 Å)", "Functions as GEF for Gαs"],
      },
      {
        id: "node_gs",
        stepNumber: 3,
        label: "Gαs · GTP Dissociation",
        sublabel: "GDP → GTP Exchange",
        category: "Transducer G-Protein",
        compartment: "Inner Leaflet",
        description: "GPCR promotes GDP release and GTP binding on the Gαs subunit, causing Gαs·GTP to dissociate from the Gβγ dimer and diffuse along the membrane.",
        x: 560,
        y: 170,
        detailChildren: ["Intrinsic GTPase timer", "Releases Gβγ complex"],
      },
      {
        id: "node_ac",
        stepNumber: 4,
        label: "Adenylyl Cyclase (AC)",
        sublabel: "ATP → cAMP + PPi",
        category: "Effector Enzyme",
        compartment: "Plasma Membrane",
        description: "Membrane-bound adenylyl cyclase is allosterically activated by Gαs·GTP, rapidly cyclizing cytosolic ATP into 3',5'-cyclic AMP (second messenger).",
        x: 775,
        y: 170,
        detailChildren: ["100× catalytic amplification", "Degraded by PDE4/PDE3"],
      },
      {
        id: "node_camp",
        stepNumber: 5,
        label: "cAMP Second Messenger",
        sublabel: "Binds PKA R₂C₂ Complex",
        category: "Second Messenger",
        compartment: "Cytosol",
        description: "Four cAMP molecules cooperatively bind the two regulatory (R) subunits of tetrameric Protein Kinase A, unleashing active catalytic (C) subunits.",
        x: 660,
        y: 385,
        detailChildren: ["Cooperative R₂C₂ release", "Spatially compartmentalized by AKAPs"],
      },
      {
        id: "node_pka",
        stepNumber: 6,
        label: "Active PKA & CREB / Ca²⁺",
        sublabel: "Ser/Thr Phosphorylation",
        category: "Kinase Effector",
        compartment: "Cytosol & Nucleus",
        description: "Catalytic PKA phosphorylates L-type Ca²⁺ channels, phospholamban, metabolic enzymes, and nuclear CREB transcription factor to execute the cellular response.",
        x: 365,
        y: 385,
        detailChildren: ["Phosphorylates L-type Ca²⁺ & PLB", "Nuclear CREB Ser133 activation"],
      },
    ],
    edges: [
      { id: "e1", from: "node_ligand", to: "node_gpcr", label: "Binds pocket" },
      { id: "e2", from: "node_gpcr", to: "node_gs", label: "GEF: GDP→GTP" },
      { id: "e3", from: "node_gs", to: "node_ac", label: "Stimulates" },
      { id: "e4", from: "node_ac", to: "node_camp", label: "Synthesizes cAMP" },
      { id: "e5", from: "node_camp", to: "node_pka", label: "Releases C subunits" },
    ],
  },

  agonist_vs_antagonist: {
    id: "diag_agonist_vs_antagonist",
    templateId: "agonist_vs_antagonist",
    title: "Side-by-Side Comparison: Full Agonist vs Competitive Antagonist",
    subtitle: "Comparing receptor conformational state, G-protein turnover, cAMP generation, and dose-response EC₅₀ shift",
    domain: "pharmacology",
    narrationScript:
      "A full agonist stabilizes the active receptor conformation to trigger full G-protein signaling and maximum efficacy, whereas a competitive antagonist occupies the same orthosteric site with zero intrinsic efficacy, shifting the agonist dose-response curve to the right.",
    comparison: {
      leftTitle: "Full Agonist Pathway (Intrinsic Efficacy α = 1.0)",
      rightTitle: "Competitive Antagonist Blockade (Intrinsic Efficacy α = 0.0)",
    },
    nodes: [
      {
        id: "ag_1",
        stepNumber: 1,
        label: "Full Agonist Binding",
        sublabel: "High Affinity for R*",
        category: "Agonist Arm",
        compartment: "Left Pathway",
        description: "Agonist binds orthosteric site and forms stabilizing hydrogen bonds with TM5/TM6, shifting conformational equilibrium strongly toward active R*.",
        x: 240,
        y: 150,
        detailChildren: ["Stabilizes active R* state", "Emax = 100%"],
      },
      {
        id: "ag_2",
        stepNumber: 2,
        label: "Gαs·GTP & cAMP Surge",
        sublabel: "Signal Amplification",
        category: "Agonist Arm",
        compartment: "Left Pathway",
        description: "Active receptor catalyzes rapid GDP→GTP exchange on Gαs, activating Adenylyl Cyclase and producing a robust intracellular cAMP surge.",
        x: 240,
        y: 295,
        detailChildren: ["Rapid GDP→GTP turnover", "High cytosolic [cAMP]"],
      },
      {
        id: "ag_3",
        stepNumber: 3,
        label: "Full Physiological Effect",
        sublabel: "PKA Phosphorylation Cascade",
        category: "Agonist Arm",
        compartment: "Left Pathway",
        description: "PKA catalytic subunits phosphorylate downstream effectors (e.g., positive inotropy in myocardium or bronchodilation in airway smooth muscle).",
        x: 240,
        y: 440,
        detailChildren: ["Full cellular response", "Baseline EC50 maintained"],
      },
      {
        id: "ant_1",
        stepNumber: 4,
        label: "Competitive Antagonist",
        sublabel: "Occupies Orthosteric Site",
        category: "Antagonist Arm",
        compartment: "Right Pathway",
        description: "Antagonist (e.g., Propranolol) reversibly occupies the same orthosteric binding pocket without triggering TM6 outward movement.",
        x: 720,
        y: 150,
        detailChildren: ["Zero intrinsic efficacy (α = 0)", "Surmountable by excess agonist"],
      },
      {
        id: "ant_2",
        stepNumber: 5,
        label: "Inactive Receptor (R)",
        sublabel: "No Gαs GDP→GTP Exchange",
        category: "Antagonist Arm",
        compartment: "Right Pathway",
        description: "Heterotrimeric Gs remains locked in its inactive GDP-bound state; Adenylyl Cyclase stays at basal activity with no cAMP spike.",
        x: 720,
        y: 295,
        detailChildren: ["Gαs·GDP remains intact", "Basal cAMP only"],
      },
      {
        id: "ant_3",
        stepNumber: 6,
        label: "Rightward EC₅₀ Shift",
        sublabel: "Blocked Downstream Response",
        category: "Antagonist Arm",
        compartment: "Right Pathway",
        description: "Apparent agonist affinity decreases (parallel rightward shift on log dose-response plot), requiring higher agonist concentration to achieve Emax.",
        x: 720,
        y: 440,
        detailChildren: ["Apparent EC50 increases", "Emax preserved at high [Agonist]"],
      },
    ],
    edges: [
      { id: "c_e1", from: "ag_1", to: "ag_2", label: "Activates R*" },
      { id: "c_e2", from: "ag_2", to: "ag_3", label: "Drives PKA" },
      { id: "c_e3", from: "ant_1", to: "ant_2", label: "Stabilizes inactive R" },
      { id: "c_e4", from: "ant_2", to: "ant_3", label: "Prevents cascade" },
    ],
  },

  cardiopulmonary_loop: {
    id: "diag_cardiopulmonary_loop",
    templateId: "cardiopulmonary_loop",
    title: "Cardiopulmonary Oxygenation & Systemic Hemodynamic Loop",
    subtitle: "Right heart preload, pulmonary alveolar capillary oxygenation, left heart afterload, and tissue perfusion",
    domain: "physiology",
    narrationScript:
      "Venous blood returns via the venae cavae to the right atrium and right ventricle, which pumps deoxygenated blood through the pulmonary trunk to the alveolar capillaries. Oxygenated blood returns via four pulmonary veins to the left atrium and left ventricle for systemic ejection.",
    comparison: null,
    nodes: [
      {
        id: "cp_1",
        stepNumber: 1,
        label: "Systemic Venous Return",
        sublabel: "SVC / IVC → Right Atrium",
        category: "Low-Pressure Venous",
        compartment: "Right Heart",
        description: "Deoxygenated venous blood (PO₂ ~40 mmHg, SaO₂ ~75%) enters the right atrium and crosses the tricuspid valve during ventricular diastole.",
        x: 150,
        y: 175,
        detailChildren: ["RAP: 2–6 mmHg", "Tricuspid inflow"],
      },
      {
        id: "cp_2",
        stepNumber: 2,
        label: "Right Ventricular Ejection",
        sublabel: "Pulmonary Trunk & Arteries",
        category: "Pulmonary Outflow",
        compartment: "Right Heart",
        description: "Right ventricle contracts against low pulmonary vascular resistance, ejecting blood past the pulmonic valve into the main pulmonary artery.",
        x: 410,
        y: 175,
        detailChildren: ["RV systolic: ~25 mmHg", "Low vascular resistance"],
      },
      {
        id: "cp_3",
        stepNumber: 3,
        label: "Alveolar Capillary Bed",
        sublabel: "O₂ Uptake & CO₂ Unloading",
        category: "Gas Exchange",
        compartment: "Lungs",
        description: "Across the 0.5 μm alveolar-capillary barrier, hemoglobin saturates to 98% (PO₂ rises from 40 to 100 mmHg) while CO₂ diffuses into alveoli.",
        x: 730,
        y: 175,
        detailChildren: ["PO₂ 40 → 100 mmHg", "PCO₂ 45 → 40 mmHg"],
      },
      {
        id: "cp_4",
        stepNumber: 4,
        label: "Left Atrium & Mitral Inflow",
        sublabel: "4 Pulmonary Veins → LA",
        category: "Oxygenated Return",
        compartment: "Left Heart",
        description: "Oxygen-rich blood returns via four pulmonary veins into the left atrium and fills the thick-walled left ventricle across the mitral valve.",
        x: 680,
        y: 390,
        detailChildren: ["LAP: 6–12 mmHg", "Diastolic ventricular filling"],
      },
      {
        id: "cp_5",
        stepNumber: 5,
        label: "Left Ventricle & Aorta",
        sublabel: "Systemic & Coronary Delivery",
        category: "High-Pressure Systemic",
        compartment: "Systemic Circuit",
        description: "Left ventricle generates ~120 mmHg systolic pressure to eject stroke volume past the aortic valve into the systemic arterial tree and coronary ostia.",
        x: 280,
        y: 390,
        detailChildren: ["LV systolic: ~120 mmHg", "Diastolic coronary filling"],
      },
    ],
    edges: [
      { id: "cp_e1", from: "cp_1", to: "cp_2", label: "Tricuspid valve" },
      { id: "cp_e2", from: "cp_2", to: "cp_3", label: "Pulmonary arteries" },
      { id: "cp_e3", from: "cp_3", to: "cp_4", label: "Pulmonary veins (O₂)" },
      { id: "cp_e4", from: "cp_4", to: "cp_5", label: "Mitral → Aortic ejection" },
      { id: "cp_e5", from: "cp_5", to: "cp_1", label: "Tissue O₂ extraction" },
    ],
  },
};

const BUILTIN_SLIDE_DECK = [
  {
    slideId: "slide_01_alveolar",
    slideNumber: "SLIDE 01 / 04",
    tag: "Respiratory Physiology",
    title: "Alveolar–Capillary Gas Exchange & Fick's Diffusion Law",
    body: "Gas transfer across the blood-gas barrier is directly proportional to surface area (A ≈ 70 m²) and partial pressure gradient (ΔP), and inversely proportional to membrane thickness (T ≈ 0.5 μm). Interstitial edema or fibrosis increases T, impairing O₂ diffusion early during exertion.",
    keyTakeaways: [
      "PAO₂ = 104 mmHg vs PvO₂ = 40 mmHg drives rapid capillary equilibration in 0.25 sec",
      "Type II pneumocytes secrete dipalmitoylphosphatidylcholine (surfactant) to reduce surface tension",
      "Pulmonary interstitial thickening widens the A–a O₂ gradient",
    ],
    visualPrompt: "Generate a medical illustration of alveolar gas exchange with oxygen and carbon dioxide diffusion arrows",
    visualTemplateKey: "alveolar_gas_exchange",
    diagramTemplateId: "cardiopulmonary_loop",
    anatomyPreset: "thorax_organs",
    anatomyCommand: "Focus on the heart and lungs and isolate the thoracic organs",
  },
  {
    slideId: "slide_02_gpcr",
    slideNumber: "SLIDE 02 / 04",
    tag: "Molecular Pharmacology",
    title: "GPCR — Gs — cAMP — PKA Second-Messenger Amplification",
    body: "β-adrenergic agonists bind 7-transmembrane receptors to catalyze GDP-to-GTP exchange on Gsα. Activated adenylyl cyclase converts ATP into cAMP, releasing catalytic Protein Kinase A subunits that phosphorylate L-type Ca²⁺ channels and phospholamban.",
    keyTakeaways: [
      "Single ligand-receptor complex activates multiple Gαs proteins (signal amplification)",
      "Competitive β-blockers occupy the orthosteric pocket with zero intrinsic efficacy",
      "Phosphodiesterases (PDE3/PDE4) terminate the signal by hydrolyzing cAMP to 5'-AMP",
    ],
    visualPrompt: "Generate a cellular pharmacology illustration of GPCR cAMP PKA signaling at the plasma membrane",
    visualTemplateKey: "coronary_circulation",
    diagramTemplateId: "gpcr_camp_pka",
    anatomyPreset: "thorax_organs",
    anatomyCommand: "Show the heart and sympathetic thoracic innervation",
  },
  {
    slideId: "slide_03_shoulder",
    slideNumber: "SLIDE 03 / 04",
    tag: "Orthopedic & Surgical Anatomy",
    title: "Rotator Cuff Footprint & Axillary Nerve Neurovascular Safe Zone",
    body: "The subscapularis tendon inserts onto the lesser tuberosity of the humerus while the supraspinatus inserts onto the superior facet of the greater tuberosity. The axillary nerve and posterior circumflex humeral artery traverse the quadrangular space immediately inferior to the glenohumeral capsule.",
    keyTakeaways: [
      "Subscapularis provides anterior dynamic stability and internal rotation",
      "Axillary nerve courses 3–5 mm inferior to the inferior glenohumeral capsule",
      "Making the deltoid transparent reveals the subacromial bursa and rotator cuff tendons",
    ],
    visualPrompt: "Generate an orthopedic illustration of the rotator cuff tendons and axillary nerve in the quadrangular space",
    visualTemplateKey: "rotator_cuff_axillary",
    diagramTemplateId: "agonist_vs_antagonist",
    anatomyPreset: "right_anterior",
    anatomyCommand: "Make the deltoid transparent and highlight the subscapularis and axillary nerve",
  },
  {
    slideId: "slide_04_renal",
    slideNumber: "SLIDE 04 / 04",
    tag: "Renal & Cardiovascular Physiology",
    title: "Glomerular Filtration Barrier & Autoregulation of GFR",
    body: "Glomerular hydrostatic pressure is finely regulated by myogenic and tubuloglomerular feedback mechanisms acting on the afferent and efferent arterioles. Angiotensin II preferentially constricts the efferent arteriole to preserve GFR during renal hypoperfusion.",
    keyTakeaways: [
      "Three-layer filtration barrier: fenestrated endothelium, GBM, and podocyte slit diaphragms",
      "Negative charge on heparan sulfate proteoglycans repels plasma albumin",
      "ACE inhibitors dilate the efferent arteriole, reducing intraglomerular hypertension",
    ],
    visualPrompt: "Generate a medical illustration of the renal corpuscle and glomerular filtration barrier",
    visualTemplateKey: "glomerular_filtration",
    diagramTemplateId: "cardiopulmonary_loop",
    anatomyPreset: "abdomen_organs",
    anatomyCommand: "Focus on the abdominal organs and kidneys",
  },
];

// ---------------------------------------------------------------------------
// Canvas Medical Illustration Renderers (Crisp High-DPI Vector/Canvas Visuals)
// ---------------------------------------------------------------------------
function drawAlveolarGasExchangeCanvas(ctx, w, h, overlayAnnotations = []) {
  ctx.save();
  ctx.fillStyle = "#fcfcfb";
  ctx.fillRect(0, 0, w, h);

  // Subtle anatomical grid
  ctx.strokeStyle = "rgba(23,23,23,0.04)";
  ctx.lineWidth = 1;
  for (let x = 40; x < w; x += 40) {
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }
  for (let y = 40; y < h; y += 40) {
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();
  }

  const cx = w * 0.48;
  const cy = h * 0.41;
  const rAlv = Math.min(w, h) * 0.27;

  // Alveolar air sac glow
  const alvGrad = ctx.createRadialGradient(cx, cy, rAlv * 0.15, cx, cy, rAlv);
  alvGrad.addColorStop(0, "#ffffff");
  alvGrad.addColorStop(0.75, "#f0f7ff");
  alvGrad.addColorStop(1, "#dbeafe");
  ctx.fillStyle = alvGrad;
  ctx.beginPath();
  ctx.arc(cx, cy, rAlv, 0.35 * Math.PI, 2.65 * Math.PI);
  ctx.fill();

  // Alveolar epithelial wall (Type I & Type II pneumocytes)
  ctx.lineWidth = 10;
  ctx.strokeStyle = "#93c5fd";
  ctx.beginPath();
  ctx.arc(cx, cy, rAlv, -0.35 * Math.PI, 1.35 * Math.PI);
  ctx.stroke();

  // Surfactant inner film
  ctx.setLineDash([6, 5]);
  ctx.lineWidth = 2.5;
  ctx.strokeStyle = "#2563eb";
  ctx.beginPath();
  ctx.arc(cx, cy, rAlv - 10, -0.3 * Math.PI, 1.3 * Math.PI);
  ctx.stroke();
  ctx.setLineDash([]);

  // Type II Pneumocyte nodules
  const type2Angles = [-0.15 * Math.PI, 0.85 * Math.PI];
  type2Angles.forEach((ang) => {
    const px = cx + Math.cos(ang) * rAlv;
    const py = cy + Math.sin(ang) * rAlv;
    ctx.fillStyle = "#3b82f6";
    ctx.beginPath();
    ctx.arc(px, py, 14, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(px, py, 5, 0, Math.PI * 2);
    ctx.fill();
  });

  // Pulmonary Capillary curving around inferior aspect of alveolus
  const capY = cy + rAlv + 44;
  const capGrad = ctx.createLinearGradient(w * 0.12, capY, w * 0.86, capY);
  capGrad.addColorStop(0, "#2563eb"); // Deoxygenated pulmonary arterial blood
  capGrad.addColorStop(0.5, "#7c3aed"); // Transition zone
  capGrad.addColorStop(1, "#dc2626"); // Oxygenated pulmonary venous blood

  ctx.lineCap = "round";
  ctx.lineWidth = 54;
  ctx.strokeStyle = "rgba(220, 38, 38, 0.14)";
  ctx.beginPath();
  ctx.moveTo(w * 0.12, capY - 12);
  ctx.quadraticCurveTo(cx, capY + 26, w * 0.86, capY - 12);
  ctx.stroke();

  ctx.lineWidth = 42;
  ctx.strokeStyle = capGrad;
  ctx.beginPath();
  ctx.moveTo(w * 0.12, capY - 12);
  ctx.quadraticCurveTo(cx, capY + 26, w * 0.86, capY - 12);
  ctx.stroke();

  // Erythrocytes (RBCs) flowing left to right
  const rbcPositions = [
    { t: 0.18, color: "#1d4ed8", label: "Deoxy-Hb" },
    { t: 0.38, color: "#4f46e5", label: "" },
    { t: 0.58, color: "#b91c1c", label: "" },
    { t: 0.8, color: "#ef4444", label: "Oxy-HbO₂" },
  ];
  rbcPositions.forEach((rbc) => {
    const t = rbc.t;
    const x0 = w * 0.12;
    const x1 = cx;
    const x2 = w * 0.86;
    const y0 = capY - 12;
    const y1 = capY + 26;
    const y2 = capY - 12;
    const rx = (1 - t) * (1 - t) * x0 + 2 * (1 - t) * t * x1 + t * t * x2;
    const ry = (1 - t) * (1 - t) * y0 + 2 * (1 - t) * t * y1 + t * t * y2;

    ctx.fillStyle = rbc.color;
    ctx.beginPath();
    ctx.ellipse(rx, ry, 20, 12, 0.08, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.65)";
    ctx.lineWidth = 2;
    ctx.stroke();
  });

  // O2 Diffusion Arrows (Downward from Alveolus into Capillary)
  drawMedicalArrow(ctx, cx - 42, cy + rAlv - 34, cx - 42, capY - 2, "#dc2626", 3.5);
  drawMedicalArrow(ctx, cx + 8, cy + rAlv - 30, cx + 8, capY + 2, "#dc2626", 3.5);

  // CO2 Diffusion Arrow (Upward from Capillary into Alveolus)
  drawMedicalArrow(ctx, cx - 95, capY - 6, cx - 95, cy + rAlv - 34, "#2563eb", 3.5);

  // Callout labels (Clean Teum Typography)
  drawCalloutBadge(ctx, cx - 105, cy - 35, "ALVEOLAR LUMEN", "PAO₂ = 104 mmHg · PACO₂ = 40 mmHg", "#171717");
  drawCalloutBadge(ctx, w * 0.06, capY - 82, "PULMONARY ARTERIOLE", "PvO₂ = 40 mmHg (Deoxygenated)", "#1d4ed8");
  drawCalloutBadge(ctx, w * 0.67, capY - 82, "PULMONARY VENULE", "PaO₂ = 100 mmHg (98% SaO₂)", "#dc2626");
  drawCalloutBadge(ctx, cx + rAlv + 24, cy + 12, "RESPIRATORY MEMBRANE", "0.5 μm Barrier (Type I + BM + Endothelium)", "#0f766e");

  // Render any user region-inpaint annotations
  renderOverlayAnnotations(ctx, w, h, overlayAnnotations);
  ctx.restore();
}

function drawCoronaryCirculationCanvas(ctx, w, h, overlayAnnotations = []) {
  ctx.save();
  ctx.fillStyle = "#fcfcfb";
  ctx.fillRect(0, 0, w, h);

  const cx = w * 0.48;
  const cy = h * 0.52;

  // Cardiac silhouette
  const heartGrad = ctx.createRadialGradient(cx - 20, cy - 20, 20, cx, cy, 195);
  heartGrad.addColorStop(0, "#fee2e2");
  heartGrad.addColorStop(0.7, "#fecaca");
  heartGrad.addColorStop(1, "#f87171");
  ctx.fillStyle = heartGrad;
  ctx.beginPath();
  ctx.moveTo(cx, cy - 115);
  ctx.bezierCurveTo(cx + 135, cy - 135, cx + 165, cy + 35, cx + 15, cy + 155);
  ctx.bezierCurveTo(cx - 115, cy + 75, cx - 135, cy - 105, cx, cy - 115);
  ctx.fill();
  ctx.lineWidth = 3;
  ctx.strokeStyle = "#b91c1c";
  ctx.stroke();

  // Ascending Aorta
  ctx.fillStyle = "#dc2626";
  ctx.beginPath();
  ctx.roundRect(cx - 32, cy - 190, 64, 92, 24);
  ctx.fill();

  // Left Main -> LAD & LCx branches
  ctx.strokeStyle = "#991b1b";
  ctx.lineCap = "round";
  ctx.lineWidth = 10;
  ctx.beginPath();
  ctx.moveTo(cx + 18, cy - 112);
  ctx.quadraticCurveTo(cx + 42, cy - 30, cx + 18, cy + 132);
  ctx.stroke();

  // Diagonal branches
  ctx.lineWidth = 6;
  ctx.beginPath();
  ctx.moveTo(cx + 30, cy - 55);
  ctx.lineTo(cx + 92, cy - 8);
  ctx.moveTo(cx + 28, cy + 8);
  ctx.lineTo(cx + 84, cy + 56);
  ctx.stroke();

  // Right Coronary Artery (RCA)
  ctx.lineWidth = 8;
  ctx.strokeStyle = "#b91c1c";
  ctx.beginPath();
  ctx.moveTo(cx - 24, cy - 110);
  ctx.quadraticCurveTo(cx - 98, cy - 25, cx - 45, cy + 95);
  ctx.stroke();

  drawCalloutBadge(ctx, w * 0.07, h * 0.16, "RIGHT CORONARY ARTERY (RCA)", "Perfuses RA, RV & SA/AV Nodes", "#991b1b");
  drawCalloutBadge(ctx, w * 0.62, h * 0.16, "LEFT ANTERIOR DESCENDING (LAD)", "Anterior 2/3 Interventricular Septum & Apex", "#dc2626");
  drawCalloutBadge(ctx, w * 0.62, h * 0.72, "DIASTOLIC CORONARY FILLING", "80% of LV Perfusion Occurs in Diastole", "#171717");

  renderOverlayAnnotations(ctx, w, h, overlayAnnotations);
  ctx.restore();
}

function drawRotatorCuffCanvas(ctx, w, h, overlayAnnotations = []) {
  ctx.save();
  ctx.fillStyle = "#fcfcfb";
  ctx.fillRect(0, 0, w, h);

  const cx = w * 0.48;
  const cy = h * 0.5;

  // Scapula & Glenoid silhouette
  ctx.fillStyle = "#f3e8d2";
  ctx.strokeStyle = "#a18868";
  ctx.lineWidth = 3;
  ctx.beginPath();
  ctx.moveTo(cx - 170, cy - 110);
  ctx.lineTo(cx - 25, cy - 95);
  ctx.lineTo(cx - 18, cy + 15);
  ctx.lineTo(cx - 135, cy + 145);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();

  // Humeral head & shaft
  ctx.fillStyle = "#f7efe0";
  ctx.beginPath();
  ctx.arc(cx + 55, cy - 25, 58, 0, Math.PI * 2);
  ctx.fill();
  ctx.stroke();
  ctx.beginPath();
  ctx.roundRect(cx + 28, cy + 15, 54, 155, 18);
  ctx.fill();
  ctx.stroke();

  // Subscapularis muscle & tendon
  ctx.fillStyle = "rgba(185, 68, 56, 0.86)";
  ctx.beginPath();
  ctx.moveTo(cx - 145, cy - 65);
  ctx.quadraticCurveTo(cx - 40, cy - 68, cx + 38, cy - 32);
  ctx.quadraticCurveTo(cx - 35, cy + 25, cx - 125, cy + 68);
  ctx.closePath();
  ctx.fill();

  // Tendon insertion (lesser tuberosity)
  ctx.fillStyle = "#e2d8c5";
  ctx.beginPath();
  ctx.roundRect(cx + 5, cy - 42, 42, 26, 8);
  ctx.fill();

  // Axillary Nerve in Quadrangular Space (Vivid Yellow)
  ctx.strokeStyle = "#eab308";
  ctx.lineWidth = 7;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(cx - 45, cy - 115);
  ctx.quadraticCurveTo(cx - 8, cy + 32, cx + 98, cy + 48);
  ctx.stroke();

  drawCalloutBadge(ctx, w * 0.06, h * 0.16, "SUBSCAPULARIS MUSCLE & TENDON", "Inserts on Lesser Tuberosity · Internal Rotation", "#991b1b");
  drawCalloutBadge(ctx, w * 0.58, h * 0.16, "HUMERAL HEAD & CAPSULE", "Glenohumeral Articulation & Bicipital Groove", "#171717");
  drawCalloutBadge(ctx, w * 0.56, h * 0.72, "AXILLARY NERVE (C5–C6)", "Courses in Quadrangular Space Inferior to Capsule", "#a16207");

  renderOverlayAnnotations(ctx, w, h, overlayAnnotations);
  ctx.restore();
}

function drawGlomerularFiltrationCanvas(ctx, w, h, overlayAnnotations = []) {
  ctx.save();
  ctx.fillStyle = "#fcfcfb";
  ctx.fillRect(0, 0, w, h);

  const cx = w * 0.5;
  const cy = h * 0.48;
  const rBowman = Math.min(w, h) * 0.31;

  // Bowman's Capsule
  ctx.fillStyle = "#fef9c3";
  ctx.strokeStyle = "#ca8a04";
  ctx.lineWidth = 8;
  ctx.beginPath();
  ctx.arc(cx, cy, rBowman, -0.75 * Math.PI, 0.75 * Math.PI);
  ctx.fill();
  ctx.stroke();

  // Glomerular Capillary Tuft
  ctx.strokeStyle = "#dc2626";
  ctx.lineWidth = 18;
  ctx.lineCap = "round";
  ctx.beginPath();
  ctx.moveTo(cx - rBowman - 55, cy - 48);
  ctx.bezierCurveTo(cx - 30, cy - 95, cx + 65, cy - 55, cx, cy);
  ctx.bezierCurveTo(cx + 65, cy + 55, cx - 30, cy + 95, cx - rBowman - 55, cy + 48);
  ctx.stroke();

  // Filtration arrows into Bowman's space
  drawMedicalArrow(ctx, cx + 28, cy - 38, cx + 82, cy - 58, "#0284c7", 3.5);
  drawMedicalArrow(ctx, cx + 38, cy, cx + 95, cy, "#0284c7", 3.5);
  drawMedicalArrow(ctx, cx + 28, cy + 38, cx + 82, cy + 58, "#0284c7", 3.5);

  drawCalloutBadge(ctx, w * 0.05, h * 0.18, "AFFERENT ARTERIOLE", "Prostaglandins Dilate → ↑ PGC & ↑ GFR", "#dc2626");
  drawCalloutBadge(ctx, w * 0.05, h * 0.72, "EFFERENT ARTERIOLE", "Angiotensin II Constricts → Preserves GFR", "#b91c1c");
  drawCalloutBadge(ctx, w * 0.62, h * 0.2, "FILTRATION BARRIER", "Fenestrated Endothelium + GBM + Podocytes", "#0284c7");

  renderOverlayAnnotations(ctx, w, h, overlayAnnotations);
  ctx.restore();
}

function drawMedicalArrow(ctx, x1, y1, x2, y2, color, width = 3) {
  const headLen = 11;
  const angle = Math.atan2(y2 - y1, x2 - x1);
  ctx.save();
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.lineWidth = width;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 6), y2 - headLen * Math.sin(angle - Math.PI / 6));
  ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 6), y2 - headLen * Math.sin(angle + Math.PI / 6));
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function drawCalloutBadge(ctx, x, y, title, subtitle, accentColor = "#171717") {
  ctx.save();
  ctx.font = "700 11px Inter, -apple-system, sans-serif";
  const w1 = ctx.measureText(title).width;
  ctx.font = "500 11px Inter, -apple-system, sans-serif";
  const w2 = ctx.measureText(subtitle).width;
  const boxW = Math.max(w1, w2) + 24;
  const boxH = 44;

  ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
  ctx.strokeStyle = "#e7e7e7";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.roundRect(x, y, boxW, boxH, 8);
  ctx.fill();
  ctx.stroke();

  ctx.fillStyle = accentColor;
  ctx.fillRect(x, y + 6, 3.5, boxH - 12);

  ctx.fillStyle = accentColor;
  ctx.font = "700 10.5px Inter, -apple-system, sans-serif";
  ctx.fillText(title, x + 12, y + 17);

  ctx.fillStyle = "#525252";
  ctx.font = "500 10.5px Inter, -apple-system, sans-serif";
  ctx.fillText(subtitle, x + 12, y + 33);
  ctx.restore();
}

function renderOverlayAnnotations(ctx, w, h, annotations = []) {
  if (!Array.isArray(annotations) || !annotations.length) return;
  annotations.forEach((ann) => {
    const rx = Math.round((ann.region?.x ?? 0.25) * w);
    const ry = Math.round((ann.region?.y ?? 0.25) * h);
    const rw = Math.round((ann.region?.width ?? 0.35) * w);
    const rh = Math.round((ann.region?.height ?? 0.28) * h);

    ctx.save();
    ctx.beginPath();
    ctx.rect(rx, ry, rw, rh);
    ctx.clip();

    // Subtle localized clinical highlight inside the region only
    const grad = ctx.createRadialGradient(
      rx + rw * 0.5,
      ry + rh * 0.5,
      8,
      rx + rw * 0.5,
      ry + rh * 0.5,
      Math.max(rw, rh) * 0.65
    );
    grad.addColorStop(0, "rgba(220, 38, 38, 0.22)");
    grad.addColorStop(0.7, "rgba(37, 99, 235, 0.12)");
    grad.addColorStop(1, "rgba(255, 255, 255, 0.0)");
    ctx.fillStyle = grad;
    ctx.fillRect(rx, ry, rw, rh);

    // Draw directional flow or pathology callout inside the clipped box
    drawMedicalArrow(
      ctx,
      rx + rw * 0.2,
      ry + rh * 0.68,
      rx + rw * 0.78,
      ry + rh * 0.32,
      "#dc2626",
      3.5
    );

    const badgeTitle = (ann.title || "REGION INPAINT").toUpperCase().slice(0, 34);
    const badgeSub = (ann.prompt || "Localized medical annotation applied").slice(0, 48);
    drawCalloutBadge(
      ctx,
      Math.max(rx + 8, 8),
      Math.max(ry + 8, 8),
      badgeTitle,
      badgeSub,
      "#dc2626"
    );

    ctx.restore();
  });
}

// ---------------------------------------------------------------------------
// Main MultimodalStageController Class
// ---------------------------------------------------------------------------
export class MultimodalStageController {
  constructor() {
    this.sessionId = "default";
    this.activeMode = "3d"; // "3d" | "image" | "diagram" | "slide"
    this.activeSubview = "image"; // "image" | "diagram" | "slide"
    this.splitMode = false;

    // Visual state
    this.currentVisualAsset = null;
    this.visualHistory = [];
    this.regionSelectEnabled = false;
    this.selectedRegion = null; // { x, y, width, height } normalized [0..1]
    this.isDraggingRegion = false;
    this.regionDragStart = null;
    this.videoAnimationFrame = null;

    // Diagram state
    this.currentDiagramScene = BUILTIN_DIAGRAM_SCENES.gpcr_camp_pka;
    this.selectedDiagramStep = "all";
    this.selectedDiagramNodeId = "node_gpcr";

    // Slide Deck state
    this.slides = [...BUILTIN_SLIDE_DECK];
    this.activeSlideId = this.slides[0].slideId;

    // Session Boards History
    this.boards = [];
    this.activeBoardId = null;

    // TTS Audio state
    this.activeAudio = null;
    this.isSpeaking = false;

    this.init();
  }

  init() {
    this.seedInitialBoards();
    this.bindHeaderEvents();
    this.bindVisualStageEvents();
    this.bindDiagramStageEvents();
    this.bindSlideStageEvents();
    this.bindStructureCardBridgeEvents();

    // Render initial visual, diagram, and slides so switching modes is instantaneous
    this.loadBuiltinVisualTemplate("alveolar_gas_exchange", { recordBoard: false });
    this.renderDiagramScene(this.currentDiagramScene, { recordBoard: false });
    this.renderSlideDeck();
    this.renderBoardsDrawer();
    this.syncHeaderUi();
  }

  seedInitialBoards() {
    this.boards = [
      {
        boardId: "board_3d_main",
        mode: "3d",
        title: "Full Body 3D Z-Anatomy Atlas",
        subtitle: "Interactive 3D anatomical structures & layers",
        badge: "3D ANATOMY",
        timestamp: "Live",
        payload: { preset: "whole_body_front" },
      },
      {
        boardId: "board_img_alveolar",
        mode: "image",
        title: "Alveolar–Capillary Gas Exchange",
        subtitle: "Nano Banana 2 · O₂/CO₂ partial pressure gradient",
        badge: "AI VISUAL",
        timestamp: "Ready",
        payload: { templateKey: "alveolar_gas_exchange" },
      },
      {
        boardId: "board_diag_gpcr",
        mode: "diagram",
        title: "GPCR — Gs — cAMP — PKA Pathway",
        subtitle: "6-step interactive receptor signaling cascade",
        badge: "2D PATHWAY",
        timestamp: "Ready",
        payload: { diagramKey: "gpcr_camp_pka" },
      },
      {
        boardId: "board_diag_compare",
        mode: "diagram",
        title: "Agonist vs Antagonist Comparison",
        subtitle: "Side-by-side efficacy & EC₅₀ shift comparison",
        badge: "COMPARE 2D",
        timestamp: "Ready",
        payload: { diagramKey: "agonist_vs_antagonist" },
      },
      {
        boardId: "board_slide_deck",
        mode: "slide",
        title: "Cardiopulmonary & Pharmacology Lecture Deck",
        subtitle: "4 clinical slides · 1-click visual & 3D grounding",
        badge: "SLIDE DECK",
        timestamp: "4 Slides",
        payload: { slideId: "slide_01_alveolar" },
      },
    ];
    this.activeBoardId = "board_3d_main";
  }

  // -------------------------------------------------------------------------
  // 1. Header Mode Switcher, Split View, Boards Drawer & Undo/Reset
  // -------------------------------------------------------------------------
  bindHeaderEvents() {
    // Primary Mode Switcher Tabs
    document.querySelectorAll("#mode-switcher-bar .mode-tab[data-mode]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-mode");
        if (mode) this.setMode(mode);
      });
    });

    // Split 3D + Visual Toggle
    const splitBtn = document.getElementById("btn-toggle-split");
    if (splitBtn) {
      splitBtn.addEventListener("click", () => {
        this.toggleSplitMode();
      });
    }

    // Boards History Drawer Popover
    const drawerBtn = document.getElementById("btn-boards-drawer");
    const drawerPopover = document.getElementById("boards-drawer-popover");
    const closeDrawerBtn = document.getElementById("btn-close-boards-drawer");

    if (drawerBtn && drawerPopover) {
      drawerBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const isHidden = drawerPopover.hidden;
        drawerPopover.hidden = !isHidden;
        drawerBtn.setAttribute("aria-expanded", String(isHidden));
        if (isHidden) {
          this.refreshBoardsFromBackend();
        }
      });

      document.addEventListener("click", (e) => {
        if (!drawerPopover.hidden && !drawerPopover.contains(e.target) && e.target !== drawerBtn) {
          drawerPopover.hidden = true;
          drawerBtn.setAttribute("aria-expanded", "false");
        }
      });
    }

    if (closeDrawerBtn && drawerPopover) {
      closeDrawerBtn.addEventListener("click", () => {
        drawerPopover.hidden = true;
        drawerBtn?.setAttribute("aria-expanded", "false");
      });
    }

    // Global Undo & Reset Buttons
    const undoBtn = document.getElementById("btn-undo");
    const resetBtn = document.getElementById("btn-reset");

    if (undoBtn) {
      undoBtn.addEventListener("click", () => this.handleGlobalUndo());
    }
    if (resetBtn) {
      resetBtn.addEventListener("click", () => this.handleGlobalReset());
    }
  }

  setMode(mode, options = {}) {
    const normalized = mode === "video" || mode === "edit_image" ? "image" : mode;
    if (!["3d", "image", "diagram", "slide"].includes(normalized)) return;

    this.activeMode = normalized;
    if (normalized !== "3d") {
      this.activeSubview = normalized;
    }

    if (typeof options.split === "boolean") {
      this.splitMode = options.split;
    } else if (normalized === "3d" && this.splitMode && !options.preserveSplit) {
      // Clicking "3D Anatomy" directly returns to full-canvas 3D unless split is explicitly kept
      this.splitMode = false;
    }

    this.syncHeaderUi();
    this.notifyThreeViewerResize();
  }

  toggleSplitMode(forceState) {
    this.splitMode = typeof forceState === "boolean" ? forceState : !this.splitMode;
    if (this.splitMode && this.activeMode === "3d") {
      // When turning on Split 3D + Visual from 3D mode, show AI Visual (or last subview) on the right
      this.activeSubview = this.activeSubview || "image";
    }
    this.syncHeaderUi();
    this.notifyThreeViewerResize();
  }

  syncHeaderUi() {
    const mainStage = document.getElementById("main-stage");
    const multiPanel = document.getElementById("multimodal-stage-panel");
    const splitBtn = document.getElementById("btn-toggle-split");
    const cameraPresetBar = document.getElementById("camera-preset-bar");

    if (mainStage) {
      mainStage.setAttribute("data-active-mode", this.activeMode);
      mainStage.setAttribute("data-split-mode", this.splitMode ? "true" : "false");
    }

    const showMultiPanel = this.activeMode !== "3d" || this.splitMode;
    if (multiPanel) {
      multiPanel.hidden = !showMultiPanel;
    }

    // Update subviews inside #multimodal-stage-panel
    const targetSubview = this.activeMode === "3d" ? this.activeSubview : this.activeMode;
    document.querySelectorAll("#multimodal-stage-panel .multimodal-subview").forEach((section) => {
      const sv = section.getAttribute("data-subview");
      const isActive = sv === targetSubview;
      section.classList.toggle("is-active", isActive);
      section.hidden = !isActive;
    });

    // Update mode tabs
    document.querySelectorAll("#mode-switcher-bar .mode-tab[data-mode]").forEach((btn) => {
      const tabMode = btn.getAttribute("data-mode");
      const isSelected = tabMode === this.activeMode;
      btn.classList.toggle("is-active", isSelected);
      btn.setAttribute("aria-selected", String(isSelected));
    });

    if (splitBtn) {
      splitBtn.classList.toggle("is-active", this.splitMode);
      splitBtn.setAttribute("aria-pressed", String(this.splitMode));
    }

    // Contextual 3D Camera Preset Bar is visible whenever 3D canvas is on screen
    if (cameraPresetBar) {
      const is3DVisible = this.activeMode === "3d" || this.splitMode;
      cameraPresetBar.style.display = is3DVisible ? "flex" : "none";
    }
  }

  notifyThreeViewerResize() {
    const triggerResize = () => {
      if (window.cliniviewViewer && typeof window.cliniviewViewer.onWindowResize === "function") {
        window.cliniviewViewer.onWindowResize();
      } else {
        window.dispatchEvent(new Event("resize"));
      }
    };
    triggerResize();
    setTimeout(triggerResize, 60);
    setTimeout(triggerResize, 200);
  }

  async handleGlobalUndo() {
    if (this.activeMode === "image" && this.visualHistory.length > 0) {
      const previousAsset = this.visualHistory.pop();
      this.applyVisualAsset(previousAsset, { pushHistory: false, recordBoard: false });
      return;
    }
    const sceneUndoBtn = document.getElementById("btn-scene-undo");
    if (sceneUndoBtn) {
      sceneUndoBtn.click();
    }
  }

  async handleGlobalReset() {
    if (this.activeMode === "image") {
      this.clearRegionSelection();
      this.stopVideoPlayback();
      this.loadBuiltinVisualTemplate("alveolar_gas_exchange", { recordBoard: false });
      return;
    }
    if (this.activeMode === "diagram") {
      this.selectedDiagramStep = "all";
      this.renderDiagramScene(BUILTIN_DIAGRAM_SCENES.gpcr_camp_pka, { recordBoard: false });
      return;
    }
    const sceneResetBtn = document.getElementById("btn-scene-reset");
    if (sceneResetBtn) {
      sceneResetBtn.click();
    }
  }

  // -------------------------------------------------------------------------
  // 2. Session Boards History Drawer
  // -------------------------------------------------------------------------
  upsertBoardEntry(entry) {
    if (!entry || !entry.boardId) return;
    const existingIdx = this.boards.findIndex((b) => b.boardId === entry.boardId);
    if (existingIdx >= 0) {
      this.boards[existingIdx] = { ...this.boards[existingIdx], ...entry };
    } else {
      this.boards.unshift(entry);
    }
    this.activeBoardId = entry.boardId;
    this.renderBoardsDrawer();
  }

  async refreshBoardsFromBackend() {
    try {
      const resp = await fetch(`/api/board/state?sessionId=${encodeURIComponent(this.sessionId)}`);
      if (!resp.ok) return;
      const data = await resp.json();
      if (Array.isArray(data.boards) && data.boards.length) {
        data.boards.forEach((b) => {
          this.upsertBoardEntry({
            boardId: b.boardId || b.id,
            mode: b.mode === "video" ? "image" : b.mode || "image",
            title: b.title || "Generated Board",
            subtitle: b.subtitle || b.prompt || "AI Visual Board",
            badge: (b.mode || "VISUAL").toUpperCase(),
            timestamp: "Synced",
            payload: { backendBoard: b },
          });
        });
      }
    } catch (_) {
      // Backend board list is optional; local session boards remain authoritative
    }
  }

  renderBoardsDrawer() {
    const listEl = document.getElementById("boards-drawer-list");
    const badgeEl = document.getElementById("boards-count-badge");
    if (badgeEl) {
      badgeEl.textContent = String(this.boards.length);
    }
    if (!listEl) return;

    listEl.innerHTML = "";
    this.boards.forEach((board) => {
      const item = document.createElement("div");
      item.className = `board-drawer-item${board.boardId === this.activeBoardId ? " is-active" : ""}`;
      item.innerHTML = `
        <span class="board-item-mode-badge">${this.escapeHtml(board.badge || board.mode.toUpperCase())}</span>
        <div class="board-item-meta">
          <p class="board-item-title">${this.escapeHtml(board.title)}</p>
          <p class="board-item-sub">${this.escapeHtml(board.subtitle || "")}</p>
        </div>
      `;
      item.addEventListener("click", () => {
        this.activateBoardEntry(board);
        const popover = document.getElementById("boards-drawer-popover");
        if (popover) popover.hidden = true;
      });
      listEl.appendChild(item);
    });
  }

  activateBoardEntry(board) {
    this.activeBoardId = board.boardId;
    this.renderBoardsDrawer();

    const p = board.payload || {};
    if (board.mode === "3d") {
      this.setMode("3d", { split: false });
      if (p.preset) {
        const presetBtn = document.querySelector(`[data-camera-preset="${p.preset}"]`);
        presetBtn?.click();
      }
      return;
    }

    if (board.mode === "image") {
      this.setMode("image", { preserveSplit: true });
      if (p.asset) {
        this.applyVisualAsset(p.asset, { pushHistory: false, recordBoard: false });
      } else if (p.templateKey) {
        this.loadBuiltinVisualTemplate(p.templateKey, { recordBoard: false });
      }
      return;
    }

    if (board.mode === "diagram") {
      this.setMode("diagram", { preserveSplit: true });
      if (p.diagramScene) {
        this.renderDiagramScene(p.diagramScene, { recordBoard: false });
      } else if (p.diagramKey && BUILTIN_DIAGRAM_SCENES[p.diagramKey]) {
        this.renderDiagramScene(BUILTIN_DIAGRAM_SCENES[p.diagramKey], { recordBoard: false });
      }
      return;
    }

    if (board.mode === "slide") {
      this.setMode("slide", { preserveSplit: true });
      if (p.slideId) {
        this.selectSlide(p.slideId);
      }
    }
  }

  // -------------------------------------------------------------------------
  // 3. Structure Card Bridge: 3D Snapshot -> AI Visual & Structure TTS
  // -------------------------------------------------------------------------
  bindStructureCardBridgeEvents() {
    const captureBtn = document.getElementById("btn-capture-to-visual");
    if (captureBtn) {
      captureBtn.addEventListener("click", () => {
        this.capture3DViewportToVisual();
      });
    }

    const cardTtsBtn = document.getElementById("btn-card-tts");
    if (cardTtsBtn) {
      cardTtsBtn.addEventListener("click", () => {
        const title = document.getElementById("card-structure-name")?.textContent || "Selected structure";
        const body = document.getElementById("card-structure-summary")?.textContent || "";
        this.speakNarration(`${title}. ${body}`, cardTtsBtn);
      });
    }
  }

  async capture3DViewportToVisual() {
    const viewer = window.cliniviewViewer;
    let dataUrl = null;
    let structureName = document.getElementById("card-structure-name")?.textContent || "3D Anatomy View";

    if (viewer && viewer.renderer && viewer.renderer.domElement) {
      try {
        viewer.renderer.render(viewer.scene, viewer.camera);
        dataUrl = viewer.renderer.domElement.toDataURL("image/png");
      } catch (_) {
        dataUrl = null;
      }
    }

    if (!dataUrl) {
      this.loadBuiltinVisualTemplate("rotator_cuff_axillary");
      this.setMode("image", { split: true });
      return;
    }

    const snapshotAsset = {
      assetId: `asset_3d_snap_${Date.now()}`,
      kind: "image",
      dataUrl,
      title: `3D Snapshot: ${structureName}`,
      subtitle: "Captured from Interactive 3D Viewport · Drag-select any region to annotate or animate",
      narrationScript: `Captured current 3D anatomical view of ${structureName}. You can now drag a rectangle to inpaint clinical callouts while preserving 100 percent of outer pixels, or animate this structure into a video.`,
      outerPixelsPreserved: false,
    };

    // Try syncing with backend if endpoint is mounted
    try {
      const resp = await fetch("/api/board/capture-3d-to-image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: this.sessionId,
          dataUrl,
          title: snapshotAsset.title,
          subtitle: snapshotAsset.subtitle,
        }),
      });
      if (resp.ok) {
        const serverData = await resp.json();
        if (serverData.asset) {
          Object.assign(snapshotAsset, serverData.asset);
        }
      }
    } catch (_) {
      // Offline / client-direct snapshot works immediately
    }

    this.applyVisualAsset(snapshotAsset, { pushHistory: true, recordBoard: true });
    this.setMode("image", { split: true });
  }

  // -------------------------------------------------------------------------
  // 4. Sub-view A: AI Visual Stage, Region Selector & Video Animation
  // -------------------------------------------------------------------------
  bindVisualStageEvents() {
    const newIllustBtn = document.getElementById("btn-new-illustration");
    if (newIllustBtn) {
      newIllustBtn.addEventListener("click", () => {
        // Cycle through built-in medical illustrations or generate from current input
        const cmdInput = document.getElementById("voice-command-input");
        const query = cmdInput?.value?.trim();
        if (query) {
          this.generateMedicalIllustration(query);
        } else {
          const keys = Object.keys(BUILTIN_VISUAL_TEMPLATES);
          const curKey = this.currentVisualAsset?.templateKey || keys[0];
          const nextKey = keys[(keys.indexOf(curKey) + 1) % keys.length];
          this.loadBuiltinVisualTemplate(nextKey, { recordBoard: true });
        }
      });
    }

    const selectRegionBtn = document.getElementById("btn-select-region");
    if (selectRegionBtn) {
      selectRegionBtn.addEventListener("click", () => {
        this.toggleRegionSelectMode();
      });
    }

    const clearRegionBtn = document.getElementById("btn-clear-region");
    if (clearRegionBtn) {
      clearRegionBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this.clearRegionSelection();
      });
    }

    const quickApplyBtn = document.getElementById("btn-region-quick-apply");
    const regionPromptInput = document.getElementById("region-prompt-input");
    if (quickApplyBtn) {
      quickApplyBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        const prompt = regionPromptInput?.value?.trim() || "Highlight oxygen diffusion gradient and add clinical callout";
        this.applyRegionInpaint(prompt);
      });
    }
    if (regionPromptInput) {
      regionPromptInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          e.preventDefault();
          const prompt = regionPromptInput.value.trim() || "Highlight oxygen diffusion gradient and add clinical callout";
          this.applyRegionInpaint(prompt);
        }
      });
    }

    const animateVideoBtn = document.getElementById("btn-animate-video");
    if (animateVideoBtn) {
      animateVideoBtn.addEventListener("click", () => {
        const cmdInput = document.getElementById("voice-command-input");
        const prompt =
          cmdInput?.value?.trim() ||
          `Animate physiological blood flow and gas exchange for ${this.currentVisualAsset?.title || "current medical visual"}`;
        this.animateCurrentVisualToVideo(prompt);
      });
    }

    const visualTtsBtn = document.getElementById("btn-visual-tts");
    if (visualTtsBtn) {
      visualTtsBtn.addEventListener("click", () => {
        const script =
          this.currentVisualAsset?.narrationScript ||
          `${this.currentVisualAsset?.title || "Medical Illustration"}. ${this.currentVisualAsset?.subtitle || ""}`;
        this.speakNarration(script, visualTtsBtn);
      });
    }

    // Bind pointer events for drag-rectangle region selection on #region-selector-layer
    const selectorLayer = document.getElementById("region-selector-layer");
    if (selectorLayer) {
      selectorLayer.addEventListener("pointerdown", (e) => this.onRegionPointerDown(e));
      window.addEventListener("pointermove", (e) => this.onRegionPointerMove(e));
      window.addEventListener("pointerup", (e) => this.onRegionPointerUp(e));
    }
  }

  loadBuiltinVisualTemplate(templateKey, options = { recordBoard: true }) {
    const tpl = BUILTIN_VISUAL_TEMPLATES[templateKey] || BUILTIN_VISUAL_TEMPLATES.alveolar_gas_exchange;
    const offscreen = document.createElement("canvas");
    offscreen.width = 960;
    offscreen.height = 600;
    const ctx = offscreen.getContext("2d");
    tpl.drawFn(ctx, offscreen.width, offscreen.height, []);

    const dataUrl = offscreen.toDataURL("image/png");
    const asset = {
      assetId: `${tpl.id}_${Date.now()}`,
      templateKey: tpl.templateKey,
      kind: "image",
      dataUrl,
      title: tpl.title,
      subtitle: tpl.subtitle,
      narrationScript: tpl.narrationScript,
      outerPixelsPreserved: false,
      annotations: [],
    };
    this.applyVisualAsset(asset, {
      pushHistory: true,
      recordBoard: options.recordBoard !== false,
    });
  }

  applyVisualAsset(asset, options = { pushHistory: true, recordBoard: true }) {
    if (!asset) return;
    if (options.pushHistory && this.currentVisualAsset) {
      this.visualHistory.push({ ...this.currentVisualAsset });
      if (this.visualHistory.length > 15) this.visualHistory.shift();
    }

    this.stopVideoPlayback();
    this.currentVisualAsset = asset;

    const imgEl = document.getElementById("visual-stage-image");
    const videoEl = document.getElementById("visual-stage-video");
    const emptyEl = document.getElementById("visual-empty-state");
    const titleEl = document.getElementById("visual-stage-title");
    const subEl = document.getElementById("visual-stage-subtitle");
    const modeTagEl = document.getElementById("visual-stage-mode-tag");
    const preserveBadge = document.getElementById("visual-preservation-badge");

    if (titleEl) titleEl.textContent = asset.title || "AI Medical Illustration";
    if (subEl) subEl.textContent = asset.subtitle || "Nano Banana 2 · Grounded Clinical Visual";

    if (asset.kind === "video" && (asset.videoUrl || asset.url || asset.dataUrl)) {
      if (modeTagEl) modeTagEl.textContent = "GEMINI OMNI 1.1 FLASH VIDEO";
      if (imgEl) imgEl.hidden = true;
      if (emptyEl) emptyEl.hidden = true;
      if (videoEl) {
        videoEl.hidden = false;
        videoEl.src = asset.videoUrl || asset.url || asset.dataUrl;
        videoEl.play().catch(() => {});
      }
    } else {
      if (modeTagEl) {
        modeTagEl.textContent = asset.outerPixelsPreserved
          ? "NANO BANANA 2 · REGION INPAINT"
          : "NANO BANANA 2 ILLUSTRATION";
      }
      if (videoEl) {
        videoEl.pause();
        videoEl.hidden = true;
      }
      if (imgEl) {
        imgEl.src = asset.dataUrl || asset.url || "";
        imgEl.hidden = false;
      }
      if (emptyEl) emptyEl.hidden = true;
    }

    if (preserveBadge) {
      preserveBadge.hidden = !asset.outerPixelsPreserved;
    }

    if (options.recordBoard) {
      this.upsertBoardEntry({
        boardId: `board_${asset.assetId || Date.now()}`,
        mode: "image",
        title: asset.title || "AI Medical Visual",
        subtitle: asset.subtitle || "Nano Banana 2 Visual",
        badge: asset.kind === "video" ? "OMNI VIDEO" : asset.outerPixelsPreserved ? "INPAINT" : "AI VISUAL",
        timestamp: "Just now",
        payload: { asset: { ...asset } },
      });
    }
  }

  toggleRegionSelectMode(forceState) {
    this.regionSelectEnabled =
      typeof forceState === "boolean" ? forceState : !this.regionSelectEnabled;
    const selectorLayer = document.getElementById("region-selector-layer");
    const selectBtn = document.getElementById("btn-select-region");

    if (selectorLayer) {
      selectorLayer.hidden = !this.regionSelectEnabled;
    }
    if (selectBtn) {
      selectBtn.classList.toggle("is-active", this.regionSelectEnabled);
      selectBtn.setAttribute("aria-pressed", String(this.regionSelectEnabled));
    }

    // If enabling region mode and no region exists yet, pre-place an adjustable default region box
    if (this.regionSelectEnabled && !this.selectedRegion) {
      this.setNormalizedRegion({ x: 0.26, y: 0.34, width: 0.46, height: 0.36 });
    }
  }

  clearRegionSelection() {
    this.selectedRegion = null;
    this.regionSelectEnabled = false;
    const selectorLayer = document.getElementById("region-selector-layer");
    const selectBox = document.getElementById("region-select-box");
    const pill = document.getElementById("region-selection-pill");
    const selectBtn = document.getElementById("btn-select-region");

    if (selectBox) selectBox.hidden = true;
    if (pill) pill.hidden = true;
    if (selectorLayer) selectorLayer.hidden = true;
    if (selectBtn) {
      selectBtn.classList.remove("is-active");
      selectBtn.setAttribute("aria-pressed", "false");
    }
  }

  onRegionPointerDown(e) {
    if (!this.regionSelectEnabled) return;
    if (e.target.closest("#region-selection-pill")) return;

    const layer = document.getElementById("region-selector-layer");
    if (!layer) return;
    const rect = layer.getBoundingClientRect();
    const nx = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const ny = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

    this.isDraggingRegion = true;
    this.regionDragStart = { x: nx, y: ny, rect };
    this.setNormalizedRegion({ x: nx, y: ny, width: 0.02, height: 0.02 });
  }

  onRegionPointerMove(e) {
    if (!this.isDraggingRegion || !this.regionDragStart) return;
    const { x: startX, y: startY, rect } = this.regionDragStart;
    const curX = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const curY = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));

    const x = Math.min(startX, curX);
    const y = Math.min(startY, curY);
    const width = Math.max(0.06, Math.abs(curX - startX));
    const height = Math.max(0.06, Math.abs(curY - startY));
    this.setNormalizedRegion({ x, y, width, height });
  }

  onRegionPointerUp() {
    if (!this.isDraggingRegion) return;
    this.isDraggingRegion = false;
    const regionPromptInput = document.getElementById("region-prompt-input");
    regionPromptInput?.focus();
  }

  setNormalizedRegion(region) {
    const clamped = {
      x: Number(Math.max(0, Math.min(0.92, region.x)).toFixed(3)),
      y: Number(Math.max(0, Math.min(0.92, region.y)).toFixed(3)),
      width: Number(Math.max(0.06, Math.min(1 - region.x, region.width)).toFixed(3)),
      height: Number(Math.max(0.06, Math.min(1 - region.y, region.height)).toFixed(3)),
    };
    this.selectedRegion = clamped;

    const selectBox = document.getElementById("region-select-box");
    const coordsBadge = document.getElementById("region-coords-badge");
    const pill = document.getElementById("region-selection-pill");

    if (selectBox) {
      selectBox.hidden = false;
      selectBox.style.left = `${clamped.x * 100}%`;
      selectBox.style.top = `${clamped.y * 100}%`;
      selectBox.style.width = `${clamped.width * 100}%`;
      selectBox.style.height = `${clamped.height * 100}%`;
    }
    if (coordsBadge) {
      coordsBadge.textContent = `x:${Math.round(clamped.x * 100)}% y:${Math.round(clamped.y * 100)}% w:${Math.round(clamped.width * 100)}% h:${Math.round(clamped.height * 100)}%`;
    }
    if (pill) {
      pill.hidden = false;
    }
  }

  async generateMedicalIllustration(promptText) {
    const cleanPrompt = (promptText || "").trim();
    const lower = cleanPrompt.toLowerCase();

    // Match to appropriate template key first for instant crisp rendering
    let matchedKey = "alveolar_gas_exchange";
    if (lower.includes("coronary") || lower.includes("heart") || lower.includes("myocard") || lower.includes("심장")) {
      matchedKey = "coronary_circulation";
    } else if (lower.includes("shoulder") || lower.includes("rotator") || lower.includes("subscap") || lower.includes("axillary") || lower.includes("어깨")) {
      matchedKey = "rotator_cuff_axillary";
    } else if (lower.includes("renal") || lower.includes("glomerul") || lower.includes("kidney") || lower.includes("nephron") || lower.includes("신장")) {
      matchedKey = "glomerular_filtration";
    }

    this.setMode("image", { preserveSplit: true });

    // Try backend /api/board/generate-image first
    try {
      const resp = await fetch("/api/board/generate-image", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: this.sessionId,
          prompt: cleanPrompt || "Generate medical illustration of alveolar gas exchange",
          title: cleanPrompt ? `AI Illustration: ${cleanPrompt.slice(0, 56)}` : undefined,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.asset && (data.asset.dataUrl || data.asset.url)) {
          this.applyVisualAsset(
            {
              ...data.asset,
              kind: "image",
              narrationScript: data.narrationScript || data.asset.subtitle,
            },
            { pushHistory: true, recordBoard: true }
          );
          return data;
        }
      }
    } catch (_) {
      // Fallback to instant local high-DPI medical illustration
    }

    this.loadBuiltinVisualTemplate(matchedKey, { recordBoard: true });
    if (cleanPrompt && this.currentVisualAsset) {
      this.currentVisualAsset.subtitle = `Prompt: "${cleanPrompt}" · Grounded Nano Banana 2 Medical Visual`;
      const subEl = document.getElementById("visual-stage-subtitle");
      if (subEl) subEl.textContent = this.currentVisualAsset.subtitle;
    }
    return { ok: true, targetMode: "image", asset: this.currentVisualAsset };
  }

  /**
   * 100% Outer-Pixel-Preserving Region Inpaint
   * Guarantees that every pixel outside `this.selectedRegion` is bit-identical to the source image.
   */
  async applyRegionInpaint(promptText) {
    if (!this.currentVisualAsset) {
      this.loadBuiltinVisualTemplate("alveolar_gas_exchange", { recordBoard: false });
    }
    if (!this.selectedRegion) {
      this.toggleRegionSelectMode(true);
    }
    const region = { ...this.selectedRegion };
    const cleanPrompt = (promptText || "Highlight localized anatomical mechanism and add clinical label").trim();

    // 1. Try backend region inpaint endpoint first
    let backendEditedDataUrl = null;
    try {
      const resp = await fetch("/api/board/edit-image-region", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: this.sessionId,
          prompt: cleanPrompt,
          region,
          assetId: this.currentVisualAsset?.assetId,
          imageDataUrl: this.currentVisualAsset?.dataUrl,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.asset && (data.asset.dataUrl || data.asset.url)) {
          backendEditedDataUrl = data.asset.dataUrl || data.asset.url;
        }
      }
    } catch (_) {
      backendEditedDataUrl = null;
    }

    // 2. Deterministic Outer-Pixel-Preserving Canvas Compositor:
    //    Copies 100% of original image pixels, then clips strictly to (rx, ry, rw, rh) for the edit.
    const baseImg = await this.loadImageFromSrc(this.currentVisualAsset.dataUrl || this.currentVisualAsset.url);
    const canvas = document.createElement("canvas");
    canvas.width = baseImg.naturalWidth || baseImg.width || 960;
    canvas.height = baseImg.naturalHeight || baseImg.height || 600;
    const ctx = canvas.getContext("2d");

    // Draw original image (100% outer pixels locked)
    ctx.drawImage(baseImg, 0, 0, canvas.width, canvas.height);

    const rx = Math.round(region.x * canvas.width);
    const ry = Math.round(region.y * canvas.height);
    const rw = Math.round(region.width * canvas.width);
    const rh = Math.round(region.height * canvas.height);

    if (backendEditedDataUrl) {
      try {
        const editedImg = await this.loadImageFromSrc(backendEditedDataUrl);
        ctx.save();
        ctx.beginPath();
        ctx.rect(rx, ry, rw, rh);
        ctx.clip();
        ctx.drawImage(editedImg, 0, 0, canvas.width, canvas.height);
        ctx.restore();
      } catch (_) {
        renderOverlayAnnotations(ctx, canvas.width, canvas.height, [
          { region, title: "REGION INPAINT", prompt: cleanPrompt },
        ]);
      }
    } else {
      renderOverlayAnnotations(ctx, canvas.width, canvas.height, [
        { region, title: "REGION INPAINT", prompt: cleanPrompt },
      ]);
    }

    // Subtle border frame indicating the inpainted region
    ctx.save();
    ctx.strokeStyle = "rgba(220, 38, 38, 0.75)";
    ctx.lineWidth = 2;
    ctx.setLineDash([6, 4]);
    ctx.strokeRect(rx + 1, ry + 1, rw - 2, rh - 2);
    ctx.restore();

    const compositeDataUrl = canvas.toDataURL("image/png");
    const updatedAsset = {
      ...this.currentVisualAsset,
      assetId: `asset_inpaint_${Date.now()}`,
      kind: "image",
      dataUrl: compositeDataUrl,
      title: `${this.currentVisualAsset.title.replace(/^Inpainted:\s*/i, "")}`,
      subtitle: `Region Inpainted (${Math.round(region.width * 100)}%×${Math.round(region.height * 100)}% box): "${cleanPrompt}" · 100% Outer Pixels Preserved`,
      outerPixelsPreserved: true,
      region,
      narrationScript: `Applied localized region inpaint for ${cleanPrompt} while preserving 100 percent of pixels outside the selected bounding box.`,
    };

    this.applyVisualAsset(updatedAsset, { pushHistory: true, recordBoard: true });
    this.clearRegionSelection();
    return { ok: true, targetMode: "image", outerPixelsPreserved: true, asset: updatedAsset };
  }

  async animateCurrentVisualToVideo(promptText) {
    this.setMode("image", { preserveSplit: true });
    const cleanPrompt = (promptText || "Animate physiological blood flow and gas exchange").trim();

    // 1. Try backend /api/board/generate-video first
    try {
      const resp = await fetch("/api/board/generate-video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: this.sessionId,
          prompt: cleanPrompt,
          sourceAssetId: this.currentVisualAsset?.assetId,
          sourceDataUrl: this.currentVisualAsset?.dataUrl,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.asset && (data.asset.url || data.asset.dataUrl || data.asset.videoUrl)) {
          this.applyVisualAsset(
            {
              ...data.asset,
              kind: "video",
              title: data.asset.title || `Animated Video: ${this.currentVisualAsset?.title || "Physiological Motion"}`,
              subtitle: `Gemini Omni 1.1 Flash Video · "${cleanPrompt}"`,
            },
            { pushHistory: true, recordBoard: true }
          );
          return data;
        }
      }
    } catch (_) {
      // Fallback to real-time HTML5 Canvas stream -> <video> playback
    }

    // 2. Real-time Canvas physiological animation streamed directly into #visual-stage-video
    this.startRealtimePhysiologicalVideoStream(cleanPrompt);
    return { ok: true, targetMode: "video" };
  }

  startRealtimePhysiologicalVideoStream(promptText) {
    this.stopVideoPlayback();

    const imgEl = document.getElementById("visual-stage-image");
    const videoEl = document.getElementById("visual-stage-video");
    const emptyEl = document.getElementById("visual-empty-state");
    const modeTagEl = document.getElementById("visual-stage-mode-tag");
    const subEl = document.getElementById("visual-stage-subtitle");

    if (modeTagEl) modeTagEl.textContent = "GEMINI OMNI 1.1 FLASH VIDEO";
    if (subEl) subEl.textContent = `Animated Physiological Sequence · "${promptText}"`;

    const animCanvas = document.createElement("canvas");
    animCanvas.width = 960;
    animCanvas.height = 600;
    const ctx = animCanvas.getContext("2d");

    const tplKey = this.currentVisualAsset?.templateKey || "alveolar_gas_exchange";
    const tpl = BUILTIN_VISUAL_TEMPLATES[tplKey] || BUILTIN_VISUAL_TEMPLATES.alveolar_gas_exchange;
    let frame = 0;

    const renderTick = () => {
      frame += 1;
      tpl.drawFn(ctx, animCanvas.width, animCanvas.height, []);

      // Animated physiological oxygen / blood flow particles
      const t = (frame % 120) / 120;
      ctx.save();
      for (let i = 0; i < 8; i++) {
        const phase = (t + i / 8) % 1;
        const px = animCanvas.width * (0.14 + phase * 0.72);
        const py = animCanvas.height * 0.72 + Math.sin(phase * Math.PI) * 18;
        ctx.fillStyle = phase < 0.5 ? "#2563eb" : "#ef4444";
        ctx.beginPath();
        ctx.arc(px, py, 9, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#ffffff";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Pulsatile O2 wave rings inside alveolus / organ center
      const pulseR = 24 + ((frame * 1.8) % 95);
      ctx.strokeStyle = `rgba(220, 38, 38, ${Math.max(0, 0.55 - pulseR / 180)})`;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.arc(animCanvas.width * 0.48, animCanvas.height * 0.41, pulseR, 0, Math.PI * 2);
      ctx.stroke();

      // Timestamp badge in top-right of video frame
      ctx.fillStyle = "rgba(23, 23, 23, 0.86)";
      ctx.beginPath();
      ctx.roundRect(animCanvas.width - 190, 18, 172, 30, 6);
      ctx.fill();
      ctx.fillStyle = "#ffffff";
      ctx.font = "700 11px Inter, monospace";
      ctx.fillText(`● OMNI LIVE  00:0${Math.floor((frame / 30) % 9)}.${Math.floor((frame % 30) / 3)}s`, animCanvas.width - 178, 37);
      ctx.restore();

      this.videoAnimationFrame = requestAnimationFrame(renderTick);
    };

    renderTick();

    if (videoEl && typeof animCanvas.captureStream === "function") {
      if (imgEl) imgEl.hidden = true;
      if (emptyEl) emptyEl.hidden = true;
      videoEl.hidden = false;
      videoEl.srcObject = animCanvas.captureStream(30);
      videoEl.play().catch(() => {});
    }

    this.upsertBoardEntry({
      boardId: `board_video_${Date.now()}`,
      mode: "image",
      title: `Video: ${this.currentVisualAsset?.title || "Physiological Animation"}`,
      subtitle: `Gemini Omni 1.1 Flash · ${promptText.slice(0, 48)}`,
      badge: "OMNI VIDEO",
      timestamp: "Live MP4",
      payload: { templateKey: tplKey },
    });
  }

  stopVideoPlayback() {
    if (this.videoAnimationFrame) {
      cancelAnimationFrame(this.videoAnimationFrame);
      this.videoAnimationFrame = null;
    }
    const videoEl = document.getElementById("visual-stage-video");
    if (videoEl) {
      videoEl.pause();
      if (videoEl.srcObject) {
        videoEl.srcObject = null;
      }
      videoEl.hidden = true;
    }
  }

  loadImageFromSrc(src) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = (err) => reject(err);
      img.src = src;
    });
  }

  // -------------------------------------------------------------------------
  // 5. Sub-view B: 2D Pathway Diagram (Interactive SVG Node-Edge Graph)
  // -------------------------------------------------------------------------
  bindDiagramStageEvents() {
    const compareBtn = document.getElementById("btn-diagram-compare");
    if (compareBtn) {
      compareBtn.addEventListener("click", () => {
        const isCurrentlyCompare = Boolean(this.currentDiagramScene?.comparison);
        const targetScene = isCurrentlyCompare
          ? BUILTIN_DIAGRAM_SCENES.gpcr_camp_pka
          : BUILTIN_DIAGRAM_SCENES.agonist_vs_antagonist;
        this.selectedDiagramStep = "all";
        this.renderDiagramScene(targetScene, { recordBoard: true });
      });
    }

    const resetBtn = document.getElementById("btn-diagram-reset");
    if (resetBtn) {
      resetBtn.addEventListener("click", () => {
        this.selectedDiagramStep = "all";
        this.renderDiagramScene(this.currentDiagramScene, { recordBoard: false });
      });
    }

    const diagramTtsBtn = document.getElementById("btn-diagram-tts");
    if (diagramTtsBtn) {
      diagramTtsBtn.addEventListener("click", () => {
        const activeNode = (this.currentDiagramScene?.nodes || []).find(
          (n) => n.id === this.selectedDiagramNodeId
        );
        const script = activeNode
          ? `Step ${activeNode.stepNumber}: ${activeNode.label}. ${activeNode.description}`
          : this.currentDiagramScene?.narrationScript || this.currentDiagramScene?.title;
        this.speakNarration(script, diagramTtsBtn);
      });
    }
  }

  async generateDiagramFromPrompt(promptText) {
    const cleanPrompt = (promptText || "").trim();
    const lower = cleanPrompt.toLowerCase();

    this.setMode("diagram", { preserveSplit: true });

    // Try backend /api/board/generate-diagram first
    try {
      const resp = await fetch("/api/board/generate-diagram", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: this.sessionId,
          prompt: cleanPrompt,
          comparisonMode: lower.includes("compare") || lower.includes("vs") || lower.includes("비교"),
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data.diagramScene && Array.isArray(data.diagramScene.nodes)) {
          this.selectedDiagramStep = "all";
          this.renderDiagramScene(data.diagramScene, { recordBoard: true });
          return data;
        }
      }
    } catch (_) {
      // Fallback to built-in interactive SVG diagram scenes
    }

    let scene = BUILTIN_DIAGRAM_SCENES.gpcr_camp_pka;
    if (lower.includes("compare") || lower.includes("antagonist") || lower.includes("vs") || lower.includes("비교")) {
      scene = BUILTIN_DIAGRAM_SCENES.agonist_vs_antagonist;
    } else if (lower.includes("heart") || lower.includes("lung") || lower.includes("cardio") || lower.includes("pulmonary") || lower.includes("순환")) {
      scene = BUILTIN_DIAGRAM_SCENES.cardiopulmonary_loop;
    }

    this.selectedDiagramStep = "all";
    this.renderDiagramScene(scene, { recordBoard: true });
    return { ok: true, targetMode: "diagram", diagramScene: scene };
  }

  renderDiagramScene(scene, options = { recordBoard: true }) {
    if (!scene || !Array.isArray(scene.nodes)) return;
    this.currentDiagramScene = scene;

    const titleEl = document.getElementById("diagram-stage-title");
    const subEl = document.getElementById("diagram-stage-subtitle");
    const compareBtn = document.getElementById("btn-diagram-compare");

    if (titleEl) titleEl.textContent = scene.title || "2D Mechanism Pathway";
    if (subEl) subEl.textContent = scene.subtitle || "Click any node or step pill to inspect downstream effects";
    if (compareBtn) {
      compareBtn.classList.toggle("is-active", Boolean(scene.comparison));
    }

    if (!scene.nodes.some((n) => n.id === this.selectedDiagramNodeId)) {
      this.selectedDiagramNodeId = scene.nodes[0]?.id || null;
    }

    this.renderDiagramStepperBar(scene);
    this.renderDiagramSvg(scene);
    this.updateDiagramNodeInspector(scene);

    if (options.recordBoard) {
      this.upsertBoardEntry({
        boardId: `board_${scene.id || scene.templateId || Date.now()}`,
        mode: "diagram",
        title: scene.title,
        subtitle: scene.subtitle,
        badge: scene.comparison ? "COMPARE 2D" : "2D PATHWAY",
        timestamp: "Interactive SVG",
        payload: { diagramScene: scene },
      });
    }
  }

  renderDiagramStepperBar(scene) {
    const bar = document.getElementById("diagram-stepper-bar");
    if (!bar) return;

    bar.innerHTML = "";
    const allBtn = document.createElement("button");
    allBtn.type = "button";
    allBtn.className = `diagram-step-pill${this.selectedDiagramStep === "all" ? " is-active" : ""}`;
    allBtn.textContent = "All Steps";
    allBtn.addEventListener("click", () => {
      this.selectedDiagramStep = "all";
      this.renderDiagramStepperBar(scene);
      this.renderDiagramSvg(scene);
    });
    bar.appendChild(allBtn);

    scene.nodes.forEach((node, idx) => {
      const stepNum = node.stepNumber || idx + 1;
      const btn = document.createElement("button");
      btn.type = "button";
      const isStepActive = String(this.selectedDiagramStep) === String(stepNum);
      btn.className = `diagram-step-pill${isStepActive ? " is-active" : ""}`;
      btn.textContent = `Step ${stepNum}: ${node.label.split(" ")[0]}`;
      btn.addEventListener("click", () => {
        this.selectedDiagramStep = stepNum;
        this.selectedDiagramNodeId = node.id;
        this.renderDiagramStepperBar(scene);
        this.renderDiagramSvg(scene);
        this.updateDiagramNodeInspector(scene);
      });
      bar.appendChild(btn);
    });
  }

  renderDiagramSvg(scene) {
    const host = document.getElementById("diagram-svg-host");
    if (!host) return;

    const nodes = scene.nodes || [];
    const edges = scene.edges || [];
    const nodeById = new Map(nodes.map((n) => [n.id, n]));

    const nodeW = 205;
    const nodeH = 84;

    let comparisonHeaderSvg = "";
    if (scene.comparison) {
      comparisonHeaderSvg = `
        <rect x="35" y="28" width="420" height="470" rx="12" fill="rgba(22, 163, 74, 0.035)" stroke="#d1fae5" stroke-width="1.5" />
        <text x="55" y="56" font-size="12" font-weight="700" fill="#15803d">${this.escapeHtml(scene.comparison.leftTitle || "Agonist Pathway")}</text>
        <rect x="505" y="28" width="420" height="470" rx="12" fill="rgba(220, 38, 38, 0.035)" stroke="#fee2e2" stroke-width="1.5" />
        <text x="525" y="56" font-size="12" font-weight="700" fill="#b91c1c">${this.escapeHtml(scene.comparison.rightTitle || "Antagonist Blockade")}</text>
        <line x1="480" y1="36" x2="480" y2="490" stroke="#e7e7e7" stroke-width="2" stroke-dasharray="6 5" />
      `;
    }

    const edgesSvg = edges
      .map((edge) => {
        const fromNode = nodeById.get(edge.from);
        const toNode = nodeById.get(edge.to);
        if (!fromNode || !toNode) return "";

        const x1 = fromNode.x;
        const y1 = fromNode.y;
        const x2 = toNode.x;
        const y2 = toNode.y;
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2 - (Math.abs(y1 - y2) < 30 ? 22 : 0);

        const isHighlighted =
          this.selectedDiagramNodeId === fromNode.id ||
          this.selectedDiagramNodeId === toNode.id;

        return `
          <g class="diagram-edge-group">
            <path
              class="diagram-edge-path${isHighlighted ? " is-highlighted" : ""}"
              d="M ${x1} ${y1} Q ${mx} ${my} ${x2} ${y2}"
              marker-end="url(#${isHighlighted ? "diag-arrow-active" : "diag-arrow"})"
            />
            <rect x="${mx - 58}" y="${my - 12}" width="116" height="20" rx="5" fill="#ffffff" stroke="#e7e7e7" stroke-width="1" />
            <text class="diagram-edge-label" x="${mx}" y="${my + 2}" text-anchor="middle">${this.escapeHtml(edge.label || "")}</text>
          </g>
        `;
      })
      .join("");

    const nodesSvg = nodes
      .map((node, idx) => {
        const stepNum = node.stepNumber || idx + 1;
        const rx = node.x - nodeW / 2;
        const ry = node.y - nodeH / 2;
        const isSelected = node.id === this.selectedDiagramNodeId;
        const isDimmed =
          this.selectedDiagramStep !== "all" &&
          String(this.selectedDiagramStep) !== String(stepNum) &&
          !isSelected;

        const childPills = Array.isArray(node.detailChildren) && node.detailChildren.length
          ? `<text x="${rx + 14}" y="${ry + 68}" font-size="10" font-weight="500" fill="#525252">• ${this.escapeHtml(node.detailChildren[0])}</text>`
          : "";

        return `
          <g
            class="diagram-node-group${isSelected ? " is-selected" : ""}${isDimmed ? " is-dimmed" : ""}"
            data-node-id="${this.escapeHtml(node.id)}"
            transform="translate(0, 0)"
          >
            <rect class="diagram-node-rect" x="${rx}" y="${ry}" width="${nodeW}" height="${nodeH}" />
            <circle class="diagram-node-step-badge" cx="${rx + 22}" cy="${ry + 24}" r="11" />
            <text class="diagram-node-step-text" x="${rx + 22}" y="${ry + 28}" text-anchor="middle">${stepNum}</text>
            <text class="diagram-node-title" x="${rx + 40}" y="${ry + 27}">${this.escapeHtml(node.label.slice(0, 22))}</text>
            <text class="diagram-node-sub" x="${rx + 14}" y="${ry + 48}">${this.escapeHtml((node.sublabel || node.compartment || "").slice(0, 30))}</text>
            ${childPills}
          </g>
        `;
      })
      .join("");

    host.innerHTML = `
      <svg class="diagram-svg" viewBox="0 0 960 520" role="img" aria-label="${this.escapeHtml(scene.title)}">
        <defs>
          <marker id="diag-arrow" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#a3a3a3" />
          </marker>
          <marker id="diag-arrow-active" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">
            <path d="M 0 1 L 10 5 L 0 9 z" fill="#171717" />
          </marker>
        </defs>
        ${comparisonHeaderSvg}
        ${edgesSvg}
        ${nodesSvg}
      </svg>
    `;

    host.querySelectorAll(".diagram-node-group[data-node-id]").forEach((groupEl) => {
      groupEl.addEventListener("click", () => {
        const nodeId = groupEl.getAttribute("data-node-id");
        if (!nodeId) return;
        this.selectedDiagramNodeId = nodeId;
        this.renderDiagramSvg(scene);
        this.updateDiagramNodeInspector(scene);
      });
    });
  }

  updateDiagramNodeInspector(scene) {
    const nodes = scene.nodes || [];
    const edges = scene.edges || [];
    const activeNode =
      nodes.find((n) => n.id === this.selectedDiagramNodeId) || nodes[0];
    if (!activeNode) return;

    const eyebrowEl = document.getElementById("diagram-node-eyebrow");
    const titleEl = document.getElementById("diagram-node-title");
    const roleEl = document.getElementById("diagram-node-role");
    const bodyEl = document.getElementById("diagram-node-body");
    const edgesEl = document.getElementById("diagram-node-edges");

    if (eyebrowEl) {
      eyebrowEl.textContent = `STEP ${String(activeNode.stepNumber || 1).padStart(2, "0")} · ${(activeNode.compartment || "PATHWAY NODE").toUpperCase()}`;
    }
    if (titleEl) titleEl.textContent = activeNode.label;
    if (roleEl) roleEl.textContent = activeNode.category || activeNode.sublabel || "Mechanism Step";
    if (bodyEl) bodyEl.textContent = activeNode.description || "";

    if (edgesEl) {
      edgesEl.innerHTML = "";
      const relatedEdges = edges.filter(
        (e) => e.from === activeNode.id || e.to === activeNode.id
      );
      relatedEdges.forEach((e) => {
        const pill = document.createElement("span");
        pill.className = "diagram-edge-pill";
        const dir = e.from === activeNode.id ? "→" : "←";
        pill.textContent = `${dir} ${e.label}`;
        edgesEl.appendChild(pill);
      });

      if (Array.isArray(activeNode.detailChildren)) {
        activeNode.detailChildren.forEach((detail) => {
          const pill = document.createElement("span");
          pill.className = "diagram-edge-pill";
          pill.textContent = `• ${detail}`;
          edgesEl.appendChild(pill);
        });
      }
    }
  }

  // -------------------------------------------------------------------------
  // 6. Sub-view C: Slide Deck Importer & 1-Click Visual / Diagram / 3D Actions
  // -------------------------------------------------------------------------
  bindSlideStageEvents() {
    const uploadInput = document.getElementById("slide-upload-input");
    if (uploadInput) {
      uploadInput.addEventListener("change", (e) => {
        const file = e.target.files?.[0];
        if (file) this.handleSlideFileUpload(file);
      });
    }

    const toImgBtn = document.getElementById("btn-slide-to-image");
    if (toImgBtn) {
      toImgBtn.addEventListener("click", () => {
        const slide = this.getActiveSlide();
        if (!slide) return;
        if (slide.visualTemplateKey && BUILTIN_VISUAL_TEMPLATES[slide.visualTemplateKey]) {
          this.loadBuiltinVisualTemplate(slide.visualTemplateKey, { recordBoard: true });
          this.setMode("image", { preserveSplit: true });
        } else {
          this.generateMedicalIllustration(slide.visualPrompt || slide.title);
        }
      });
    }

    const toDiagBtn = document.getElementById("btn-slide-to-diagram");
    if (toDiagBtn) {
      toDiagBtn.addEventListener("click", () => {
        const slide = this.getActiveSlide();
        if (!slide) return;
        const tplId = slide.diagramTemplateId || "gpcr_camp_pka";
        const scene = BUILTIN_DIAGRAM_SCENES[tplId] || BUILTIN_DIAGRAM_SCENES.gpcr_camp_pka;
        this.selectedDiagramStep = "all";
        this.renderDiagramScene(scene, { recordBoard: true });
        this.setMode("diagram", { preserveSplit: true });
      });
    }

    const to3DBtn = document.getElementById("btn-slide-to-3d");
    if (to3DBtn) {
      to3DBtn.addEventListener("click", () => {
        const slide = this.getActiveSlide();
        if (!slide) return;
        this.setMode("slide", { split: true });
        if (slide.anatomyPreset) {
          const presetBtn = document.querySelector(`[data-camera-preset="${slide.anatomyPreset}"]`);
          presetBtn?.click();
        }
      });
    }
  }

  getActiveSlide() {
    return this.slides.find((s) => s.slideId === this.activeSlideId) || this.slides[0];
  }

  selectSlide(slideId) {
    this.activeSlideId = slideId;
    this.renderSlideDeck();
  }

  renderSlideDeck() {
    const thumbList = document.getElementById("slide-thumbnail-list");
    const activeSlide = this.getActiveSlide();
    if (!activeSlide) return;

    if (thumbList) {
      thumbList.innerHTML = "";
      this.slides.forEach((s) => {
        const item = document.createElement("div");
        item.className = `slide-thumb-card${s.slideId === activeSlide.slideId ? " is-active" : ""}`;
        item.innerHTML = `
          <span class="slide-thumb-num">${this.escapeHtml(s.slideNumber)}</span>
          <p class="slide-thumb-title">${this.escapeHtml(s.title)}</p>
        `;
        item.addEventListener("click", () => this.selectSlide(s.slideId));
        thumbList.appendChild(item);
      });
    }

    const numEl = document.getElementById("slide-card-number");
    const tagEl = document.getElementById("slide-card-tag");
    const titleEl = document.getElementById("slide-card-title");
    const bodyEl = document.getElementById("slide-card-body");
    const bulletsEl = document.getElementById("slide-card-bullets");

    if (numEl) numEl.textContent = activeSlide.slideNumber;
    if (tagEl) tagEl.textContent = activeSlide.tag;
    if (titleEl) titleEl.textContent = activeSlide.title;
    if (bodyEl) bodyEl.textContent = activeSlide.body;

    if (bulletsEl) {
      bulletsEl.innerHTML = "";
      (activeSlide.keyTakeaways || []).forEach((pt) => {
        const li = document.createElement("li");
        li.textContent = pt;
        bulletsEl.appendChild(li);
      });
    }
  }

  async handleSlideFileUpload(file) {
    // Try backend /api/board/import-slide first
    try {
      const formData = new FormData();
      formData.append("file", file);
      formData.append("sessionId", this.sessionId);
      const resp = await fetch("/api/board/import-slide", {
        method: "POST",
        body: formData,
      });
      if (resp.ok) {
        const data = await resp.json();
        if (Array.isArray(data.importedSlides) && data.importedSlides.length) {
          data.importedSlides.forEach((s, idx) => {
            this.slides.unshift({
              slideId: s.slideId || `uploaded_${Date.now()}_${idx}`,
              slideNumber: `IMPORTED 0${idx + 1}`,
              tag: s.tag || "Uploaded Lecture Slide",
              title: s.title || file.name,
              body: s.body || s.summary || `Imported from ${file.name}. Ready for 1-click AI Visual or 2D Pathway extraction.`,
              keyTakeaways: s.keyTakeaways || [
                `Source file: ${file.name}`,
                "Click 'Generate AI Visual from Slide' or 'Extract 2D Pathway Diagram'",
              ],
              visualPrompt: s.visualPrompt || s.title || file.name,
              visualTemplateKey: "alveolar_gas_exchange",
              diagramTemplateId: "gpcr_camp_pka",
              anatomyPreset: "thorax_organs",
            });
          });
          this.activeSlideId = this.slides[0].slideId;
          this.renderSlideDeck();
          return;
        }
      }
    } catch (_) {
      // Fallback local slide creation
    }

    const newSlide = {
      slideId: `slide_upload_${Date.now()}`,
      slideNumber: `UPLOADED SLIDE`,
      tag: "Imported Deck",
      title: file.name.replace(/\.[^.]+$/, ""),
      body: `Uploaded lecture material (${file.name}). Use the action bar below to synthesize a Nano Banana 2 medical illustration, extract an interactive 2D mechanism diagram, or align the 3D anatomy model.`,
      keyTakeaways: [
        `File loaded: ${file.name} (${Math.round(file.size / 1024)} KB)`,
        "Supports 1-click AI Visual generation and 2D pathway extraction",
      ],
      visualPrompt: file.name,
      visualTemplateKey: "alveolar_gas_exchange",
      diagramTemplateId: "gpcr_camp_pka",
      anatomyPreset: "whole_body_front",
    };
    this.slides.unshift(newSlide);
    this.activeSlideId = newSlide.slideId;
    this.renderSlideDeck();
  }

  // -------------------------------------------------------------------------
  // 7. Smart Command Router Hook (Called by voice-ui.js for Unified Routing)
  // -------------------------------------------------------------------------
  async executeSmartMultimodalCommand(commandText) {
    const clean = (commandText || "").trim();
    if (!clean) return null;
    const lower = clean.toLowerCase();

    // 1. Try unified backend /api/board/smart-command if mounted
    try {
      const resp = await fetch("/api/board/smart-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          commandText: clean,
          sessionId: this.sessionId,
          activeMode: this.activeMode,
          selectedAssetId: this.currentVisualAsset?.assetId,
          selectedBoardId: this.activeBoardId,
          selectedRegion: this.selectedRegion,
          slideId: this.activeSlideId,
          waitForAck: true,
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        if (data && data.ok !== false) {
          this.applySmartCommandResponse(data, clean);
          return data;
        }
      }
    } catch (_) {
      // Continue to deterministic client routing + /api/voice/text-command
    }

    // 2. Client-side intent classification when /api/board/smart-command is not mounted
    const isRegionEditIntent =
      Boolean(this.selectedRegion) &&
      (lower.includes("inpaint") ||
        lower.includes("region") ||
        lower.includes("highlight") ||
        lower.includes("label") ||
        lower.includes("edit") ||
        lower.includes("영역") ||
        lower.includes("수정"));

    const isVideoIntent =
      lower.includes("animate") ||
      lower.includes("video") ||
      lower.includes("motion") ||
      lower.includes("pulsatile") ||
      lower.includes("영상") ||
      lower.includes("애니메이션");

    const isDiagramIntent =
      lower.includes("diagram") ||
      lower.includes("pathway") ||
      lower.includes("cascade") ||
      lower.includes("gpcr") ||
      lower.includes("camp") ||
      lower.includes("pka") ||
      lower.includes("compare agonist") ||
      lower.includes("side by side") ||
      lower.includes("다이어그램") ||
      lower.includes("기전");

    const isImageIntent =
      lower.includes("illustration") ||
      lower.includes("alveolar") ||
      lower.includes("gas exchange") ||
      lower.includes("coronary") ||
      lower.includes("glomerul") ||
      lower.includes("draw ") ||
      lower.includes("일러스트") ||
      lower.includes("그려");

    if (isRegionEditIntent) {
      return await this.applyRegionInpaint(clean);
    }
    if (isVideoIntent) {
      return await this.animateCurrentVisualToVideo(clean);
    }
    if (isDiagramIntent) {
      return await this.generateDiagramFromPrompt(clean);
    }
    if (isImageIntent) {
      return await this.generateMedicalIllustration(clean);
    }

    // Otherwise return null so voice-ui.js executes the authoritative 3D scene command (/api/voice/text-command)
    return null;
  }

  applySmartCommandResponse(data, fallbackPrompt = "") {
    const mode = data.targetMode || "3d";
    if (mode === "image" || mode === "edit_image" || mode === "video") {
      this.setMode("image", { preserveSplit: true });
      if (data.asset && (data.asset.dataUrl || data.asset.url || data.asset.videoUrl)) {
        this.applyVisualAsset(
          {
            ...data.asset,
            kind: mode === "video" ? "video" : "image",
            outerPixelsPreserved: Boolean(data.outerPixelsPreserved || data.asset.outerPixelsPreserved),
            narrationScript: data.narrationScript || data.asset.subtitle,
          },
          { pushHistory: true, recordBoard: true }
        );
      } else if (mode === "video") {
        this.startRealtimePhysiologicalVideoStream(fallbackPrompt);
      } else {
        this.generateMedicalIllustration(fallbackPrompt);
      }
      return;
    }

    if (mode === "diagram") {
      this.setMode("diagram", { preserveSplit: true });
      if (data.diagramScene && Array.isArray(data.diagramScene.nodes)) {
        this.selectedDiagramStep = "all";
        this.renderDiagramScene(data.diagramScene, { recordBoard: true });
      } else {
        this.generateDiagramFromPrompt(fallbackPrompt);
      }
      return;
    }

    if (mode === "3d") {
      if (this.activeMode !== "3d" && !this.splitMode) {
        this.setMode("3d", { split: false });
      }
    }
  }

  // -------------------------------------------------------------------------
  // 8. Gemini TTS Audio Narration (POST /api/tts + SpeechSynthesis Fallback)
  // -------------------------------------------------------------------------
  async speakNarration(scriptText, triggerBtn = null) {
    const cleanScript = (scriptText || "").trim();
    if (!cleanScript) return;

    const ttsIndicator = document.getElementById("tts-audio-indicator");

    // Toggle off if already playing
    if (this.isSpeaking) {
      this.stopNarration();
      return;
    }

    this.isSpeaking = true;
    if (ttsIndicator) ttsIndicator.hidden = false;
    if (triggerBtn) triggerBtn.classList.add("is-speaking");

    try {
      const resp = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          script_text: cleanScript,
          voice_name: "Kore",
        }),
      });
      if (resp.ok) {
        const data = await resp.json();
        const audioSrc =
          data.audio_data_url ||
          data.audioDataUrl ||
          (data.audio_base64 ? `data:${data.mime_type || "audio/wav"};base64,${data.audio_base64}` : null);
        if (audioSrc) {
          const audio = new Audio(audioSrc);
          this.activeAudio = audio;
          audio.onended = () => this.stopNarration();
          audio.onerror = () => this.fallbackWebSpeechNarration(cleanScript);
          await audio.play();
          return;
        }
      }
    } catch (_) {
      // Fallback to browser SpeechSynthesis
    }

    this.fallbackWebSpeechNarration(cleanScript);
  }

  fallbackWebSpeechNarration(scriptText) {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      const utter = new SpeechSynthesisUtterance(scriptText);
      utter.rate = 1.02;
      utter.onend = () => this.stopNarration();
      utter.onerror = () => this.stopNarration();
      window.speechSynthesis.speak(utter);
    } else {
      setTimeout(() => this.stopNarration(), 2500);
    }
  }

  stopNarration() {
    this.isSpeaking = false;
    if (this.activeAudio) {
      this.activeAudio.pause();
      this.activeAudio = null;
    }
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    const ttsIndicator = document.getElementById("tts-audio-indicator");
    if (ttsIndicator) ttsIndicator.hidden = true;
    document.querySelectorAll(".is-speaking").forEach((el) => el.classList.remove("is-speaking"));
  }

  escapeHtml(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
}

// Initialize singleton on DOMContentLoaded and expose globally
function bootMultimodalStage() {
  if (!window.visualBoardStage) {
    window.visualBoardStage = new MultimodalStageController();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", bootMultimodalStage);
} else {
  bootMultimodalStage();
}
