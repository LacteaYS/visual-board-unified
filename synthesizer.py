"""
Two-Stage Multimodal & Interactive Synthesis Engine for CliniView Live.

Stage 1 (~4-6s):
  - Parallel execution of:
    (a) `gemini-3.8-flash` -> Grounded clinical/scientific summary + exact [SOT-xx] citation cards + TTS script
    (b) `gemini-3.1-flash-lite-image` (or `gemini-nano-banana-2.1`) -> High-clarity medical/scientific reference illustration

Stage 2 (~15-28s):
  - `gemini-4-argon` -> Synthesizes a self-contained interactive HTML5 / 3D Three.js / Animated SVG simulation
    strictly grounded in the user's Source of Truth and CONTEXT.md
  - Followed by External Independent Stage-Gate Validation:
    Gate 1: DOM + `node --check` JS syntax verification + SHA-256 fingerprint
    Gate 2: `gemini-3.8-flash` Source-of-Truth Grounding & Hallucination Audit
"""

import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
import subprocess
import tempfile
import time
from typing import Any, Dict, Optional

from google import genai
from google.genai import types

from validator import (
    extract_html_document,
    run_source_of_truth_audit_gate,
    validate_code_and_dom_gate,
)


STAGE1_SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {
            "type": "string",
            "description": "One-line clear Korean title for the patient or audience.",
        },
        "patient_or_audience_summary": {
            "type": "string",
            "description": "2-3 sentences in friendly, accurate Korean explaining the core mechanism for the patient/audience.",
        },
        "key_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "sot_citation": {"type": "string", "description": "Exact tag e.g. [SOT-01], [SOT-02], [SOT-12]"},
                },
                "required": ["title", "detail", "sot_citation"],
            },
        },
        "voice_narration_script": {
            "type": "string",
            "description": "Natural spoken Korean script (3-4 sentences, ~20 seconds) suitable for live TTS briefing to the patient or audience.",
        },
        "safety_notice": {
            "type": "string",
            "description": "Clinician/presenter-in-the-loop safety and grounding disclaimer in Korean.",
        },
    },
    "required": [
        "headline",
        "patient_or_audience_summary",
        "key_points",
        "voice_narration_script",
        "safety_notice",
    ],
}


def get_genai_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY environment variable is not set.")
    return genai.Client(api_key=api_key)


def _generate_stage1_grounded_brief(
    client: genai.Client,
    user_prompt: str,
    source_of_truth: str,
    context_md: str,
) -> Dict[str, Any]:
    t0 = time.time()
    prompt = f"""당신은 의료·의과학 시각 설명 코파일럿 'CliniView Live'의 Stage 1 즉각 브리핑 엔진입니다.
반드시 아래 [SOURCE OF TRUTH] 원문에 있는 해부학·생화학적 사실만 사용하여 [USER REQUEST]에 대한 즉각 브리핑 카드와 음성 설명 대본을 생성하세요.
원문에 없는 내용을 지어내지 말고, 각 핵심 포인트마다 정확한 `[SOT-xx]` 인용 코드를 표기하세요.

[USER REQUEST]
{user_prompt}

[SOURCE OF TRUTH]
{source_of_truth}

[CONTEXT.MD]
{context_md}
"""
    interaction = client.interactions.create(
        model="gemini-3.8-flash",
        input=prompt,
        generation_config={"thinking_level": "low"},
        response_format=STAGE1_SUMMARY_SCHEMA,
    )
    raw_text = (interaction.output_text or "{}").strip()
    data = json.loads(raw_text)
    data["elapsed_sec"] = round(time.time() - t0, 2)
    data["model"] = "gemini-3.8-flash"
    return data


def _generate_stage1_reference_image(
    client: genai.Client,
    user_prompt: str,
    source_of_truth: str,
    image_model: str = "gemini-3.1-flash-lite-image",
) -> Dict[str, Any]:
    t0 = time.time()
    sot_snippet = source_of_truth[:1200]
    img_prompt = (
        "Create a clean, high-contrast, modern medical & scientific textbook infographic illustration on a deep slate background (#0b1220). "
        "Highlight the target anatomical structure or molecular signaling pathway in glowing cyan/emerald with clear English anatomical/molecular labels and directional arrows. "
        f"Topic request: {user_prompt}\n"
        f"Key authoritative facts to depict accurately: {sot_snippet}"
    )
    try:
        interaction = client.interactions.create(
            model=image_model,
            input=img_prompt,
            response_modalities=["image"],
            generation_config={
                "image_config": {
                    "aspect_ratio": "16:9",
                    "image_size": "1K",
                }
            },
        )
        for step in interaction.steps or []:
            for content_item in getattr(step, "content", None) or []:
                if getattr(content_item, "type", None) == "image" and getattr(content_item, "data", None):
                    mime = getattr(content_item, "mime_type", None) or "image/jpeg"
                    raw_data = content_item.data
                    if isinstance(raw_data, bytes):
                        b64_str = base64.b64encode(raw_data).decode("ascii")
                    else:
                        b64_str = str(raw_data)
                    return {
                        "ok": True,
                        "data_url": f"data:{mime};base64,{b64_str}",
                        "model": image_model,
                        "elapsed_sec": round(time.time() - t0, 2),
                    }
    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
            "model": image_model,
            "elapsed_sec": round(time.time() - t0, 2),
        }

    return {
        "ok": False,
        "error": "No image returned from model.",
        "model": image_model,
        "elapsed_sec": round(time.time() - t0, 2),
    }


def run_stage1_parallel(
    user_prompt: str,
    source_of_truth: str,
    context_md: str,
    image_model: str = "gemini-3.1-flash-lite-image",
) -> Dict[str, Any]:
    """Run Stage 1 grounded text brief and reference medical illustration concurrently (~4-6s total)."""
    t0 = time.time()
    client = get_genai_client()
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut_brief = pool.submit(
            _generate_stage1_grounded_brief,
            client,
            user_prompt,
            source_of_truth,
            context_md,
        )
        fut_img = pool.submit(
            _generate_stage1_reference_image,
            client,
            user_prompt,
            source_of_truth,
            image_model,
        )
        brief_res = fut_brief.result()
        img_res = fut_img.result()

    return {
        "stage": "stage1_instant",
        "total_elapsed_sec": round(time.time() - t0, 2),
        "brief": brief_res,
        "image": img_res,
    }


def _build_argon_synthesis_prompt(
    user_prompt: str,
    source_of_truth: str,
    context_md: str,
    repair_error: Optional[str] = None,
) -> str:
    repair_block = ""
    if repair_error:
        repair_block = f"""
[CRITICAL STAGE-GATE REPAIR INSTRUCTION]
The previous draft failed external validation with: {repair_error}
Fix all JavaScript syntax errors, ensure all tags close properly, and include interactive <input type="range"> sliders, <button> controls, and an interactive <svg> or <canvas> viewport.
"""

    return f"""You are the Stage 2 Interactive Medical & Scientific Simulation Architect powered by `gemini-4-argon`.
Generate a SINGLE, complete, self-contained HTML5 document (`<!DOCTYPE html>...</html>`) that lets a clinician or academic presenter interactively explain the [USER REQUEST] to a patient or audience in real time.

{repair_block}
[STRICT GROUNDING & SAFETY RULES]
1. Use ONLY anatomical, physiological, and biochemical facts from [SOURCE OF TRUTH].
2. Every major structure, step, and clinical hotspot MUST display both Korean and English names (e.g. `견갑하근 (Subscapularis)` or `아데닐산 고리화효소 (Adenylyl Cyclase)`) and its exact citation badge (`[SOT-01]`, `[SOT-02]`, `[SOT-12]`, etc.).
3. Follow all layout and interaction requirements in [CONTEXT.MD].

[HIGH-SPEED, HIGH-PRECISION ARCHITECTURE REQUIREMENTS]
- Output ONLY raw HTML starting with `<!DOCTYPE html>` and ending with `</html>`. Do NOT wrap in explanations.
- Use `<script src="https://cdn.tailwindcss.com"></script>` for styling so you write almost zero custom CSS boilerplate and keep total output concise (~130-165 lines) for fast generation.
- Theme: Deep medical slate background (`bg-slate-950 text-slate-100`), high-contrast interactive viewport on the left (7 cols), and live Control + Source-of-Truth Inspector panel on the right (5 cols).
- Interactive Viewport MUST use a rich, multi-layered interactive `<svg viewBox="0 0 800 540">` (or HTML5 `<canvas>` / Three.js) with:
  * Distinct anatomical/molecular layers with `id` attributes whose opacity, rotation/transform, and glow respond smoothly in real time to `<input type="range">` sliders and state `<button>` clicks.
  * For Musculoskeletal / Anatomy requests (e.g. Subscapularis / Rotator Cuff):
    - Render detailed anatomical silhouettes of Scapula (견갑골 & 견갑하와 Subscapular fossa), Humerus (상완골 소결절 Lesser tubercle & 대결절 Greater tubercle), Clavicle, Ribcage, Glowing Target Muscle fibers (견갑하근 Subscapularis running from Subscapular fossa to Lesser tubercle), and overlying Deltoid (삼각근) & Pectoralis Major (대흉근) layers.
    - Provide working sliders for: (1) Overlying Muscle Opacity (삼각근·대흉근 투명도 0-100%), (2) Internal Rotation / Lift-off Test Angle (내회전·열중쉬어 각도 0-90° with dynamic humeral rotation & muscle contraction animation), and (3) Trigger Point / Referred Pain Overlay (치료 포인트·손목 후면 연관통 표시).
    - Provide clickable hotspot pins (① 견갑하와 기시부 `[SOT-02]`, ② 상완골 소결절 정지부 `[SOT-02]`, ③ 액와 전연 안전 치료 포인트 `[SOT-04]`, ④ 견갑 후면·손목 등쪽 연관통 `[SOT-03]`) that update the right-side Clinical Inspector Card when clicked.
  * For Cellular / Molecular Pathway requests (e.g. GPCR / mRNA-LNP signaling):
    - Render Extracellular space, Phospholipid Bilayer membrane, 7-Transmembrane Helices (TM1-TM7 of GPCR), Ligand (Agonist), Heterotrimeric G-protein (Gαs, Gβγ, GDP/GTP badge), Adenylyl Cyclase, animated cAMP messenger particles, PKA (R2C2 -> active C subunits), and CREB/PDE reset loop.
    - Provide interactive Step 1 to Step 5 state machine buttons + Auto-Play toggle + Ligand/cAMP Amplification slider (`<input type="range">`) that visually animates ligand docking, TM5/TM6 shift, Gαs-GTP dissociation toward Adenylyl Cyclase, cAMP burst, and PKA activation with `[SOT-10]`~`[SOT-12]` inspector updates.
- Ensure 100% valid vanilla JavaScript inside a single `<script>` tag with zero syntax errors.

[USER REQUEST]
{user_prompt}

[SOURCE OF TRUTH]
{source_of_truth}

[CONTEXT.MD]
{context_md}
"""


def run_stage2_interactive_synthesis(
    user_prompt: str,
    source_of_truth: str,
    context_md: str,
    thinking_level: str = "low",
) -> Dict[str, Any]:
    """
    Synthesize interactive simulation using `gemini-4-argon` + run External Independent Stage-Gate Validation.
    Includes automatic repair if Gate 1 detects syntax/DOM issues.
    """
    t0 = time.time()
    client = get_genai_client()
    if thinking_level not in ("minimal", "low", "medium", "high"):
        thinking_level = "low"

    attempts = 0
    max_attempts = 2
    repair_error: Optional[str] = None
    html_code = ""
    gate1_result: Dict[str, Any] = {}
    argon_elapsed = 0.0

    while attempts < max_attempts:
        attempts += 1
        t_gen = time.time()
        prompt = _build_argon_synthesis_prompt(
            user_prompt=user_prompt,
            source_of_truth=source_of_truth,
            context_md=context_md,
            repair_error=repair_error,
        )
        # IMPORTANT: gemini-4-argon strictly uses client.interactions.create with thinking_level only
        # (never pass temperature, top_p, top_k, or thinking_budget)
        interaction = client.interactions.create(
            model="gemini-4-argon",
            input=prompt,
            generation_config={"thinking_level": thinking_level},
        )
        argon_elapsed = round(time.time() - t_gen, 2)
        raw_output = interaction.output_text or ""

        html_code = extract_html_document(raw_output)
        gate1_result = validate_code_and_dom_gate(html_code)

        if gate1_result["passed"]:
            break
        repair_error = "; ".join(gate1_result.get("issues", [])) or gate1_result.get("js_error_detail", "Syntax issue")

    # Run Independent Stage-Gate 2: Source-of-Truth Medical/Scientific Audit via gemini-3.8-flash
    gate2_result = run_source_of_truth_audit_gate(
        client=client,
        html_code=html_code,
        source_of_truth=source_of_truth,
        context_md=context_md,
        user_prompt=user_prompt,
    )

    total_elapsed = round(time.time() - t0, 2)

    return {
        "stage": "stage2_interactive",
        "model": "gemini-4-argon",
        "thinking_level": thinking_level,
        "attempts": attempts,
        "argon_generation_sec": argon_elapsed,
        "total_elapsed_sec": total_elapsed,
        "html": html_code,
        "validation": {
            "overall_passed": bool(gate1_result.get("passed") and gate2_result.get("passed", True)),
            "human_approval_required": True,
            "gate1_code_dom": gate1_result,
            "gate2_sot_audit": gate2_result,
        },
    }


def generate_tts_briefing(script_text: str, voice_name: str = "Kore") -> Dict[str, Any]:
    """Generate spoken Korean voice briefing for patient/audience using gemini-3.8-flash-lite-tts."""
    t0 = time.time()
    client = get_genai_client()
    response = client.models.generate_content(
        model="gemini-3.8-flash-lite-tts",
        contents=script_text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name,
                    )
                )
            ),
        ),
    )
    part = response.candidates[0].content.parts[0]
    audio_bytes = part.inline_data.data
    mime_type = part.inline_data.mime_type or "audio/L16;rate=24000"

    # Convert raw PCM (audio/L16;rate=24000) to standard WAV header so browsers can play it directly via <audio>
    wav_bytes = _pcm16_to_wav(audio_bytes, sample_rate=24000, channels=1)
    b64_wav = base64.b64encode(wav_bytes).decode("ascii")

    return {
        "ok": True,
        "model": "gemini-3.8-flash-lite-tts",
        "voice": voice_name,
        "elapsed_sec": round(time.time() - t0, 2),
        "audio_data_url": f"data:audio/wav;base64,{b64_wav}",
    }


def _pcm16_to_wav(pcm_data: bytes, sample_rate: int = 24000, channels: int = 1) -> bytes:
    """Wrap raw 16-bit little-endian PCM bytes in a RIFF WAV header for universal browser playback."""
    import io
    import wave

    if pcm_data[:4] == b"RIFF":
        return pcm_data
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buf.getvalue()


def transcribe_voice_input(audio_bytes: bytes, mime_type: str = "audio/webm") -> Dict[str, Any]:
    """Transcribe clinician/presenter spoken audio using gemini-3.5-transcribe."""
    t0 = time.time()
    client = get_genai_client()
    response = client.models.generate_content(
        model="gemini-3.5-transcribe",
        contents=[
            types.Content(
                parts=[
                    types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
                    types.Part.from_text(
                        text="Transcribe this Korean/English medical or scientific voice request accurately. Output only the transcribed text."
                    ),
                ]
            )
        ],
    )
    return {
        "ok": True,
        "model": "gemini-3.5-transcribe",
        "text": (response.text or "").strip(),
        "elapsed_sec": round(time.time() - t0, 2),
    }
