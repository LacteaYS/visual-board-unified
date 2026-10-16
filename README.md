# Visual Board Unified (CliniView Live 3.0)

**Voice-Driven Multimodal Visual Co-Pilot for Medical & Scientific Education**  
*Track 3: Google AI for Social Good (Health & Education)*

- **Live Google Cloud Run URL**: **https://visual-board-unified-509893886131.asia-northeast3.run.app**
- **Public GitHub Repository**: **https://github.com/LacteaYS/visual-board-unified**

Visual Board Unified integrates **whole-body 3D anatomy**, **Nano Banana region-preserving medical illustration & inpainting**, **Gemini Omni 1.1 Flash educational video synthesis**, **interactive 2D mechanism & signaling diagrams**, and **bilingual wake-phrase voice control (`"Visual Board"` / `"비주얼 보드"`)** into a single minimalist stage.

---

## Key Capabilities

1. **Whole-Body & Regional 3D Anatomy Engine (`3D Anatomy`)**
   - Powered by Z-Anatomy (`whole_body.glb` & `shoulder.glb`, 385 indexed anatomical structures across 28 functional groups).
   - **Smart Layer Fading & Auto-Camera Framing**: Natural-language or voice commands (e.g., *"Show heart and lungs"*, *"Highlight brain and fade skull"*, *"Isolate liver and stomach"*, *"Show sciatic nerve and gluteus maximus"*) automatically fade obstructing superficial layers (ribcage, skull, abdominal wall) to `0.12–0.15` opacity and fly the camera to the target bounding box with real-time WebSocket Viewer ACK verification.
   - **3D-to-Visual Bridge**: Capture any 3D anatomical view directly into the AI Visual board for region-specific annotation or video animation.

2. **AI Visual Board & Region-Preserving Inpainting (`AI Visual`)**
   - **Medical & Scientific Illustration**: Generates high-clarity illustrations grounded in source-of-truth clinical documents using `gemini-3.1-flash-lite-image` (`gemini-nano-banana-2.1`).
   - **100% Outer-Pixel Preserving Region Inpainting (`⬚ Select Region to Edit`)**: Drag a bounding box over any region of an illustration or 3D snapshot to regenerate only the selected patch via Pillow crop-and-composite while preserving 100% of surrounding pixels.
   - **Educational Video Generation (`🎬 Animate to Video`)**: Converts static medical visuals into 720p 16:9 MP4 motion clips using `gemini-omni-1.1-flash` with deterministic `ffmpeg` fallback.

3. **Interactive 2D Pathway & Mechanism Diagrams (`2D Pathway`)**
   - Step-by-step interactive node-edge signaling pathways (`GPCR–Gs–cAMP–PKA Signaling`, `Agonist vs Antagonist Comparison`, `Cardiopulmonary Flow`, `Neuromuscular Excitation`) with dynamic Gemini 3.8 Flash graph synthesis and TTS narration.

4. **Slide Deck Transformation (`Slide Deck`) & 50:50 Split View (`Split 3D + Visual`)**
   - Import `.pdf`, `.pptx`, or `.png`/`.jpg` lecture slides and transform them in one click into 3D anatomy scenes, AI illustrations, or interactive 2D diagrams.
   - Side-by-side **50:50 Split View** lets educators and clinicians compare 3D anatomical structures alongside AI illustrations or signaling pathways simultaneously.

5. **Dual Voice Pipeline & Bilingual Wake-Phrase Gate**
   - **Push-to-Talk (`🎙️ Voice Command`)**: Direct voice command execution via `gemini-3.5-transcribe` and `gemini-3.8-flash`.
   - **Continuous Lecture Mode (`🎧 Wake Word "Visual Board"`)**: Buffers ordinary lecture speech without distraction and triggers visual board generation only when the presenter invokes `"Visual Board, ..."` or `"비주얼 보드, ..."` (includes 3-sample wake-word calibration).
   - **Gemini TTS Briefing (`🔊 Narrate`)**: Synthesizes spoken explanations via `gemini-3.8-flash-lite-tts`.

---

## Architecture & Google AI Models Used

| Component | Model / Technology | Role |
| :--- | :--- | :--- |
| **Smart Router & Scene Planner** | `gemini-3.8-flash` | Classifies voice/text intent across 3D anatomy, image generation, region inpainting, video animation, and 2D diagrams |
| **Interactive Simulation & Audit** | `gemini-4-argon` + `gemini-3.8-flash` | Stage-2 interactive HTML5/3D synthesis + independent DOM/JS syntax & Source-of-Truth grounding audit |
| **Medical Illustration & Inpainting** | `gemini-3.1-flash-lite-image` (`gemini-nano-banana-2.1`) | Medical illustration generation & cropped bounding-box region inpainting |
| **Educational Video Animation** | `gemini-omni-1.1-flash` + `ffmpeg` | 5-second 720p MP4 physiological motion synthesis from board visuals |
| **Speech-to-Text & TTS Narration** | `gemini-3.5-transcribe` & `gemini-3.8-flash-lite-tts` | Real-time bilingual voice command transcription and audio narration |

---

## Local Development

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="your-gemini-api-key"
uvicorn app:app --host 0.0.0.0 --port 8200
```

Open `http://127.0.0.1:8200` in Chrome.

---

## Google Cloud Run Deployment

```bash
gcloud run deploy visual-board-unified \
  --source . \
  --project h2gdm-hack26icn-2631 \
  --region asia-northeast3 \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --set-secrets="GEMINI_API_KEY=visual-board-gemini:latest"
```
