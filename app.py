"""
FastAPI Backend & Unified Multimodal Visual Board Hub (CliniView Live + Visual Board 3.0)
Track 3: Google AI for Social Good (Health & Education)

Unifies:
1. Z-Anatomy Whole-Body & Shoulder 3D Authoritative Scene Service + WebSocket Viewer ACK Sync (/ws/scene/{session_id})
2. 8 Anatomy & Procedure MCP Contract Endpoints (/api/mcp/{tool_name} & REST endpoints)
3. Gemini Push-to-Talk Voice & Natural-Language Scene Controller (/api/voice/*)
4. Unified Multimodal Visual Board (/api/board/*):
   - Multi-Board History & Asset Store (`BOARD_STORE`)
   - Nano Banana Image Generation (`gemini-3.1-flash-lite-image` / `gemini-nano-banana-2.1`)
   - Region-Preserving Partial Image Inpainting (`edit_board_image_region` with 100% outer-pixel preservation)
   - Gemini Omni Video Generation (`gemini-omni-1.1-flash` + 720p MP4 `ffmpeg` engine)
   - Interactive 2D Pathway & Mechanism Comparison Diagrams (`knowledge_base.py` + `gemini-3.8-flash`)
   - Slide Deck Import (`PDF`, `PPTX`, `PNG/JPG` + built-in clinical/scientific lecture slides)
   - Continuous Lecture STT + Bilingual Wake-Phrase Gate (`"비주얼 보드"` / `"Visual Board"`)
5. Supplementary Stage 1 & Stage 2 Visual Synthesis (/api/stage1-instant, /api/stage2-interactive)
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from multimodal_board import (
    BOARD_STORE,
    SESSION_STORE,
    capture_3d_to_board_image,
    edit_board_image_region,
    execute_smart_command,
    generate_board_diagram,
    generate_board_image,
    generate_board_video,
    get_demo_slides,
    import_slide_deck,
    ingest_lecture_segment,
    load_env_credentials,
    resolve_gemini_api_key,
)

# Ensure .env credentials are loaded before downstream modules initialize
load_env_credentials()

from presets import PRESETS
from scene_service import SCENE_SERVICE
from synthesizer import (
    generate_tts_briefing,
    run_stage1_parallel,
    run_stage2_interactive_synthesis,
    transcribe_voice_input,
)
from voice_controller import (
    execute_natural_language_scene_command,
    normalize_audio_mime_type,
    transcribe_voice_command,
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Visual Board Unified — 3D Anatomy, 2D Pathway Diagram, Region Inpainting & Gemini Omni Video Co-Pilot",
    description=(
        "Unified Multimodal Visual Board combining Z-Anatomy + Whole-Body 3D Scene Service, "
        "Interactive 2D Pathway Diagrams, Nano Banana Region-Preserving Image Inpainting, "
        "Gemini Omni 1.1 Flash Video Generation, Slide Deck Import, and Bilingual Wake-Phrase Voice Control"
    ),
    version="3.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Request Models
# ---------------------------------------------------------------------------
class SearchStructuresRequest(BaseModel):
    query: str = ""
    side: Optional[str] = None
    category: Optional[str] = None
    group: Optional[str] = None
    limit: int = 25


class SceneStateRequest(BaseModel):
    sessionId: str = "default"
    compact: bool = False


class ScenePatchRequest(BaseModel):
    sessionId: str = "default"
    expectedRevision: Optional[int] = None
    commandId: Optional[str] = None
    changes: Dict[str, Any] = Field(default_factory=dict)
    waitForAck: bool = True
    timeoutSec: float = 3.5


class SceneUndoRequest(BaseModel):
    sessionId: str = "default"
    commandId: Optional[str] = None
    waitForAck: bool = True


class SceneCaptureRequest(BaseModel):
    sessionId: str = "default"
    format: str = "png"
    timeoutSec: float = 4.5


class ProcedureListRequest(BaseModel):
    side: Optional[str] = None


class ProcedureLoadRequest(BaseModel):
    sessionId: str = "default"
    templateId: str = "proc_subscap_axillary_r"
    stepIndex: int = 0
    preserveCamera: bool = True
    waitForAck: bool = True


class ProcedureProgressRequest(BaseModel):
    sessionId: str = "default"
    progress: Optional[float] = None
    stepIndex: Optional[int] = None
    playState: Optional[str] = None
    preserveCamera: bool = True
    waitForAck: bool = True


class VoiceTextCommandRequest(BaseModel):
    sessionId: str = "default"
    commandText: str
    waitForAck: bool = True


class Stage1Request(BaseModel):
    user_prompt: str
    source_of_truth: Optional[str] = None
    context_md: Optional[str] = None
    image_model: str = "gemini-3.1-flash-lite-image"


class Stage2Request(BaseModel):
    user_prompt: str
    source_of_truth: Optional[str] = None
    context_md: Optional[str] = None
    thinking_level: str = "low"


class TTSRequest(BaseModel):
    script_text: str
    voice_name: str = "Kore"


class BoardSelectRequest(BaseModel):
    boardId: Optional[str] = None
    board_id: Optional[str] = None
    slideId: Optional[str] = None
    slide_id: Optional[str] = None


class SmartCommandRequest(BaseModel):
    commandText: Optional[str] = None
    prompt: Optional[str] = None
    text: Optional[str] = None
    command: Optional[str] = None
    sessionId: str = "default"
    activeMode: str = "3d"
    mode: Optional[str] = None
    selectedAssetId: Optional[str] = None
    assetId: Optional[str] = None
    selectedBoardId: Optional[str] = None
    boardId: Optional[str] = None
    selectedRegion: Optional[Dict[str, Any]] = None
    region: Optional[Dict[str, Any]] = None
    selectedElementIds: Optional[List[str]] = None
    selectedNodeIds: Optional[List[str]] = None
    slideId: Optional[str] = None
    forceMode: Optional[str] = None
    generateAudio: bool = False
    waitForAck: bool = False


class BoardGenerateImageRequest(BaseModel):
    prompt: Optional[str] = None
    commandText: Optional[str] = None
    title: Optional[str] = None
    model: str = "gemini-3.1-flash-lite-image"
    modelName: Optional[str] = None
    slideId: Optional[str] = None
    referenceAssetId: Optional[str] = None
    assetId: Optional[str] = None
    aspectRatio: str = "16:9"


class BoardEditImageRequest(BaseModel):
    prompt: Optional[str] = None
    commandText: Optional[str] = None
    region: Optional[Dict[str, Any]] = None
    selectedRegion: Optional[Dict[str, Any]] = None
    assetId: Optional[str] = None
    selectedAssetId: Optional[str] = None
    sourceAssetId: Optional[str] = None
    boardId: Optional[str] = None
    selectedBoardId: Optional[str] = None
    imageDataUrl: Optional[str] = None
    dataUrl: Optional[str] = None
    model: str = "gemini-3.1-flash-lite-image"
    modelName: Optional[str] = None


class BoardGenerateVideoRequest(BaseModel):
    prompt: Optional[str] = None
    commandText: Optional[str] = None
    title: Optional[str] = None
    sourceAssetId: Optional[str] = None
    assetId: Optional[str] = None
    selectedAssetId: Optional[str] = None
    sourceBoardId: Optional[str] = None
    boardId: Optional[str] = None
    selectedBoardId: Optional[str] = None
    sourceDataUrl: Optional[str] = None
    dataUrl: Optional[str] = None
    imageDataUrl: Optional[str] = None
    slideId: Optional[str] = None
    model: str = "gemini-omni-1.1-flash"
    modelName: Optional[str] = None


class BoardGenerateDiagramRequest(BaseModel):
    prompt: str = ""
    commandText: Optional[str] = None
    templateId: Optional[str] = None
    template_id: Optional[str] = None
    selectedNodeIds: Optional[List[str]] = None
    selectedElementIds: Optional[List[str]] = None
    comparisonMode: bool = False


class BoardIngestSpeechRequest(BaseModel):
    text: Optional[str] = None
    transcript: Optional[str] = None
    commandText: Optional[str] = None
    isFinal: bool = True
    is_final: Optional[bool] = None
    segmentId: Optional[str] = None
    eventId: Optional[str] = None
    speaker: str = "presenter"
    explicitUiRequest: bool = False
    activeMode: str = "3d"
    selectedAssetId: Optional[str] = None
    selectedBoardId: Optional[str] = None
    selectedRegion: Optional[Dict[str, Any]] = None
    selectedElementIds: Optional[List[str]] = None
    slideId: Optional[str] = None
    forceMode: Optional[str] = None


class BoardOnboardingRequest(BaseModel):
    sampleIndex: int = 1
    transcript: str = "비주얼 보드"
    samples: Optional[List[str]] = None
    reset: bool = False


class BoardCapture3DRequest(BaseModel):
    sessionId: str = "default"
    dataUrl: Optional[str] = None
    imageDataUrl: Optional[str] = None
    title: str = "3D 해부학 장면 캡처 스냅샷"
    subtitle: str = "드래그하여 영역 부분 인페인팅(Nano Banana) 또는 모션 영상(Gemini Omni) 생성 가능"


# ---------------------------------------------------------------------------
# Health, Manifest & Presets
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health_check():
    has_key = bool(resolve_gemini_api_key())
    default_session = SCENE_SERVICE.get_or_create_session("default")
    return {
        "status": "ok",
        "service": "visual-board-unified",
        "version": "3.0.0",
        "gemini_api_key_configured": has_key,
        "structureCount": len(SCENE_SERVICE.structures_by_id),
        "landmarkCount": len(SCENE_SERVICE.landmarks_by_id),
        "procedureTemplateCount": len(SCENE_SERVICE.list_templates()["templates"]),
        "defaultSessionRevision": default_session.revision,
        "connectedViewers": len(default_session.websockets),
        "boardCount": len(BOARD_STORE.boards),
        "slideCount": len(BOARD_STORE.slides),
        "activeBoardId": BOARD_STORE.active_board_id,
        "activeSlideId": BOARD_STORE.active_slide_id,
        "models": {
            "voice_scene_planner": "gemini-3.8-flash",
            "voice_transcription": "gemini-3.5-transcribe",
            "voice_tts": "gemini-3.8-flash-lite-tts",
            "stage1_brief_and_auditor": "gemini-3.8-flash",
            "stage1_fast_illustration": "gemini-3.1-flash-lite-image",
            "stage1_pro_illustration": "gemini-nano-banana-2.1",
            "region_inpainting": "gemini-3.1-flash-lite-image / gemini-nano-banana-2.1",
            "video_generation": "gemini-omni-1.1-flash",
            "diagram_synthesis": "gemini-3.8-flash",
            "stage2_interactive_architect": "gemini-4-argon",
        },
    }


@app.get("/api/manifest")
def get_manifest():
    return JSONResponse(SCENE_SERVICE.manifest)


@app.get("/api/provenance")
def get_provenance():
    return JSONResponse(SCENE_SERVICE.provenance)


@app.get("/api/presets")
def get_presets():
    return {"presets": PRESETS}


# ---------------------------------------------------------------------------
# 8 Authoritative Scene & Anatomy MCP Contract Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/anatomy/search")
def api_search_structures_get(
    query: str = Query(""),
    side: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    group: Optional[str] = Query(None),
    limit: int = Query(25),
):
    return SCENE_SERVICE.search_structures(
        query=query, side=side, category=category, group=group, limit=limit
    )


@app.post("/api/anatomy/search")
def api_search_structures_post(req: SearchStructuresRequest):
    return SCENE_SERVICE.search_structures(
        query=req.query,
        side=req.side,
        category=req.category,
        group=req.group,
        limit=req.limit,
    )


@app.get("/api/scene/state")
def api_get_scene_state(
    sessionId: str = Query("default"),
    compact: bool = Query(False),
):
    return SCENE_SERVICE.get_state(session_id=sessionId, compact=compact)


@app.post("/api/scene/patch")
async def api_apply_scene_patch(req: ScenePatchRequest):
    res = await SCENE_SERVICE.apply_patch(
        session_id=req.sessionId,
        changes=req.changes,
        expected_revision=req.expectedRevision,
        command_id=req.commandId,
        wait_for_ack=req.waitForAck,
        timeout_sec=req.timeoutSec,
        source="http_patch",
    )
    if not res.get("ok", False):
        return JSONResponse(status_code=409 if res.get("errorCode") == "REVISION_CONFLICT" else 400, content=res)
    return res


@app.post("/api/scene/undo")
async def api_scene_undo(req: SceneUndoRequest):
    res = await SCENE_SERVICE.undo(
        session_id=req.sessionId,
        command_id=req.commandId,
        wait_for_ack=req.waitForAck,
    )
    if not res.get("ok", False):
        return JSONResponse(status_code=400, content=res)
    return res


@app.post("/api/scene/capture")
async def api_scene_capture(req: SceneCaptureRequest):
    res = await SCENE_SERVICE.capture_scene(
        session_id=req.sessionId,
        image_format=req.format,
        timeout_sec=req.timeoutSec,
    )
    if not res.get("ok", False):
        return JSONResponse(status_code=400, content=res)
    return res


@app.get("/api/procedure/templates")
def api_list_procedure_templates(side: Optional[str] = Query(None)):
    return SCENE_SERVICE.list_templates(side=side)


@app.post("/api/procedure/load")
async def api_load_procedure_template(req: ProcedureLoadRequest):
    res = await SCENE_SERVICE.load_template(
        session_id=req.sessionId,
        template_id=req.templateId,
        step_index=req.stepIndex,
        preserve_camera=req.preserveCamera,
        wait_for_ack=req.waitForAck,
    )
    if not res.get("ok", False):
        return JSONResponse(status_code=400, content=res)
    return res


@app.post("/api/procedure/progress")
async def api_set_procedure_progress(req: ProcedureProgressRequest):
    res = await SCENE_SERVICE.set_procedure_progress(
        session_id=req.sessionId,
        progress=req.progress,
        step_index=req.stepIndex,
        play_state=req.playState,
        preserve_camera=req.preserveCamera,
        wait_for_ack=req.waitForAck,
    )
    if not res.get("ok", False):
        return JSONResponse(status_code=400, content=res)
    return res


@app.post("/api/mcp/{tool_name}")
async def api_mcp_dispatch(tool_name: str, payload: Dict[str, Any]):
    """Unified dispatcher used by the Antigravity Anatomy MCP Server (`apps/anatomy-mcp/dist/index.js`)."""
    tn = tool_name.strip()
    if tn in ("anatomy.search_structures", "anatomy_search_structures"):
        return SCENE_SERVICE.search_structures(
            query=payload.get("query", ""),
            side=payload.get("side"),
            category=payload.get("category"),
            group=payload.get("group"),
            limit=int(payload.get("limit", 25)),
        )
    if tn in ("scene.get_state", "scene_get_state"):
        return SCENE_SERVICE.get_state(
            session_id=payload.get("sessionId", "default"),
            compact=bool(payload.get("compact", False)),
        )
    if tn in ("scene.apply_patch", "scene_apply_patch"):
        return await SCENE_SERVICE.apply_patch(
            session_id=payload.get("sessionId", "default"),
            changes=payload.get("changes", {}),
            expected_revision=payload.get("expectedRevision"),
            command_id=payload.get("commandId"),
            wait_for_ack=bool(payload.get("waitForAck", True)),
            timeout_sec=float(payload.get("timeoutSec", 3.5)),
            source="anatomy_mcp",
        )
    if tn in ("scene.undo", "scene_undo"):
        return await SCENE_SERVICE.undo(
            session_id=payload.get("sessionId", "default"),
            command_id=payload.get("commandId"),
            wait_for_ack=bool(payload.get("waitForAck", True)),
        )
    if tn in ("scene.capture", "scene_capture"):
        return await SCENE_SERVICE.capture_scene(
            session_id=payload.get("sessionId", "default"),
            image_format=payload.get("format", "png"),
            timeout_sec=float(payload.get("timeoutSec", 4.5)),
        )
    if tn in ("procedure.list_templates", "procedure_list_templates"):
        return SCENE_SERVICE.list_templates(side=payload.get("side"))
    if tn in ("procedure.load_template", "procedure_load_template"):
        return await SCENE_SERVICE.load_template(
            session_id=payload.get("sessionId", "default"),
            template_id=payload.get("templateId", "proc_subscap_axillary_r"),
            step_index=int(payload.get("stepIndex", 0)),
            preserve_camera=bool(payload.get("preserveCamera", True)),
            wait_for_ack=bool(payload.get("waitForAck", True)),
        )
    if tn in ("procedure.set_progress", "procedure_set_progress"):
        return await SCENE_SERVICE.set_procedure_progress(
            session_id=payload.get("sessionId", "default"),
            progress=payload.get("progress"),
            step_index=payload.get("stepIndex"),
            play_state=payload.get("playState"),
            preserve_camera=bool(payload.get("preserveCamera", True)),
            wait_for_ack=bool(payload.get("waitForAck", True)),
        )
    raise HTTPException(status_code=404, detail=f"Unknown MCP tool: {tool_name}")


# ---------------------------------------------------------------------------
# WebSocket Endpoint for Real-Time 3D Viewer Sync & Viewer ACK
# ---------------------------------------------------------------------------
@app.websocket("/ws/scene/{session_id}")
async def websocket_scene_endpoint(websocket: WebSocket, session_id: str = "default"):
    await websocket.accept()
    await SCENE_SERVICE.register_websocket(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            await SCENE_SERVICE.handle_viewer_message(session_id, websocket, data)
    except WebSocketDisconnect:
        SCENE_SERVICE.unregister_websocket(session_id, websocket)
    except Exception:
        SCENE_SERVICE.unregister_websocket(session_id, websocket)


# ---------------------------------------------------------------------------
# Push-to-Talk Voice & Natural-Language Clinical Scene Controller
# ---------------------------------------------------------------------------
@app.post("/api/voice/text-command")
async def api_voice_text_command(req: VoiceTextCommandRequest):
    if not req.commandText.strip():
        raise HTTPException(status_code=400, detail="commandText is required.")
    try:
        res = await execute_natural_language_scene_command(
            command_text=req.commandText.strip(),
            session_id=req.sessionId,
            stt_ms=0.0,
            wait_for_ack=req.waitForAck,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Voice text command failed: {exc}") from exc


@app.post("/api/voice/audio-command")
async def api_voice_audio_command(
    file: Optional[UploadFile] = File(None),
    sessionId: str = Form("default"),
    mime_type: Optional[str] = Form(None),
    waitForAck: bool = Form(True),
    clientTranscript: Optional[str] = Form(None),
):
    try:
        audio_bytes = await file.read() if file is not None else b""
        raw_mime = mime_type or (file.content_type if file is not None else None) or "audio/webm"
        detected_mime = normalize_audio_mime_type(raw_mime)

        live_client_transcript = (clientTranscript or "").strip()
        if live_client_transcript:
            transcript = live_client_transcript
            stt_res = {
                "transcript": transcript,
                "text": transcript,
                "sttMs": 12.0,
                "model": "gemini-3.5-transcribe (live-stream)",
                "mimeType": detected_mime,
            }
        elif audio_bytes:
            stt_res = await transcribe_voice_command(audio_bytes=audio_bytes, mime_type=detected_mime)
            transcript = (stt_res.get("transcript") or "").strip()
        else:
            transcript = ""
            stt_res = {
                "transcript": "",
                "text": "",
                "sttMs": 0.0,
                "model": "none",
                "mimeType": detected_mime,
            }

        if not transcript:
            return JSONResponse(
                status_code=400,
                content={
                    "ok": False,
                    "error": "No speech recognized in audio recording.",
                    "stt": stt_res,
                },
            )
        res = await execute_natural_language_scene_command(
            command_text=transcript,
            session_id=sessionId,
            stt_ms=float(stt_res.get("sttMs", 0.0)),
            wait_for_ack=waitForAck,
        )
        res["stt"] = stt_res
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Voice audio command failed: {exc}") from exc


@app.post("/api/voice/transcribe")
async def api_voice_transcribe(file: UploadFile = File(...), mime_type: Optional[str] = Form(None)):
    try:
        audio_bytes = await file.read()
        detected_mime = normalize_audio_mime_type(mime_type or file.content_type or "audio/webm")
        result = await transcribe_voice_command(audio_bytes=audio_bytes, mime_type=detected_mime)
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Voice audio transcription failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Supplementary Stage 1 & Stage 2 Generative Visual Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/stage1-instant")
def api_stage1_instant(req: Stage1Request):
    if not req.user_prompt.strip():
        raise HTTPException(status_code=400, detail="user_prompt is required.")
    sot = req.source_of_truth or PRESETS["mode_a_clinic"]["source_of_truth"]
    ctx = req.context_md or PRESETS["mode_a_clinic"]["context_md"]
    try:
        result = run_stage1_parallel(
            user_prompt=req.user_prompt,
            source_of_truth=sot,
            context_md=ctx,
            image_model=req.image_model,
        )
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stage 1 synthesis failed: {exc}") from exc


@app.post("/api/stage2-interactive")
def api_stage2_interactive(req: Stage2Request):
    if not req.user_prompt.strip():
        raise HTTPException(status_code=400, detail="user_prompt is required.")
    sot = req.source_of_truth or PRESETS["mode_a_clinic"]["source_of_truth"]
    ctx = req.context_md or PRESETS["mode_a_clinic"]["context_md"]
    try:
        result = run_stage2_interactive_synthesis(
            user_prompt=req.user_prompt,
            source_of_truth=sot,
            context_md=ctx,
            thinking_level=req.thinking_level,
        )
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stage 2 synthesis failed: {exc}") from exc


@app.post("/api/tts")
def api_tts(req: TTSRequest):
    if not req.script_text.strip():
        raise HTTPException(status_code=400, detail="script_text is required.")
    try:
        result = generate_tts_briefing(script_text=req.script_text, voice_name=req.voice_name)
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS generation failed: {exc}") from exc


@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...), mime_type: Optional[str] = Form(None)):
    try:
        audio_bytes = await file.read()
        detected_mime = normalize_audio_mime_type(mime_type or file.content_type or "audio/webm")
        result = await transcribe_voice_command(audio_bytes=audio_bytes, mime_type=detected_mime)
        return JSONResponse(result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Audio transcription failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Unified Multimodal Visual Board Endpoints (/api/board/*)
# ---------------------------------------------------------------------------
@app.get("/api/board/list")
@app.get("/api/board/state")
def api_board_list():
    """Returns all boards, activeBoardId, activeBoard, slides, activeSlideId, session status, and demoComparison."""
    return JSONResponse(BOARD_STORE.list_state())


@app.post("/api/board/select")
def api_board_select(req: BoardSelectRequest):
    """Selects an active board or slide and returns the updated board list state."""
    target_board = req.boardId or req.board_id
    target_slide = req.slideId or req.slide_id

    if target_board:
        found = BOARD_STORE.set_active_board(target_board)
        if not found:
            raise HTTPException(status_code=404, detail=f"Board not found: {target_board}")

    if target_slide:
        slide_match = next((s for s in BOARD_STORE.slides if s["slideId"] == target_slide), None)
        if not slide_match:
            raise HTTPException(status_code=404, detail=f"Slide not found: {target_slide}")
        BOARD_STORE.active_slide_id = target_slide
        # If the user selected a slide and didn't specify a board, also surface or create an image board for this slide
        if not target_board:
            existing_board = next(
                (b for b in reversed(BOARD_STORE.boards) if b.get("assetId") == slide_match.get("assetId")),
                None,
            )
            if existing_board:
                BOARD_STORE.set_active_board(existing_board["boardId"])
            else:
                raw_bytes, _ = BOARD_STORE.resolve_image_bytes(asset_id=slide_match.get("assetId"))
                BOARD_STORE.save_image_bytes(
                    raw_bytes=raw_bytes,
                    title=slide_match.get("title", "Selected Lecture Slide"),
                    subtitle=slide_match.get("subtitle", "Lecture Slide"),
                    prompt=slide_match.get("text", ""),
                    model="slide-deck",
                    create_board=True,
                    board_kind="image",
                )

    return JSONResponse(BOARD_STORE.list_state())


@app.post("/api/board/smart-command")
async def api_board_smart_command(req: SmartCommandRequest):
    """
    Unified Smart Command Router:
    Automatically routes any natural-language Korean or English command to:
      - 3D Anatomy & Clinical Scene Service
      - Interactive 2D Pathway & Comparison Diagram Generator
      - Nano Banana Image Generation
      - Region-Preserving Partial Image Inpainting (when a region is selected)
      - Gemini Omni 1.1 Flash Video Generation
    """
    cmd_text = (req.commandText or req.prompt or req.text or req.command or "").strip()
    if not cmd_text:
        raise HTTPException(status_code=400, detail="commandText (or prompt) is required.")
    try:
        res = await execute_smart_command(
            command_text=cmd_text,
            session_id=req.sessionId,
            active_mode=req.mode or req.activeMode,
            selected_asset_id=req.selectedAssetId or req.assetId,
            selected_board_id=req.selectedBoardId or req.boardId,
            selected_region=req.selectedRegion or req.region,
            selected_element_ids=req.selectedElementIds or req.selectedNodeIds,
            slide_id=req.slideId,
            force_mode=req.forceMode,
            generate_audio=req.generateAudio,
            wait_for_ack=req.waitForAck,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Smart command failed: {exc}") from exc


@app.post("/api/board/generate-image")
async def api_board_generate_image(req: BoardGenerateImageRequest):
    """Generates a medical/scientific illustration via Nano Banana (`gemini-3.1-flash-lite-image` / `gemini-nano-banana-2.1`)."""
    prompt_str = (req.prompt or req.commandText or "").strip()
    if not prompt_str and not req.slideId:
        raise HTTPException(status_code=400, detail="prompt or slideId is required.")
    try:
        res = await generate_board_image(
            prompt=prompt_str,
            title=req.title,
            model_name=req.modelName or req.model,
            slide_id=req.slideId,
            reference_asset_id=req.referenceAssetId or req.assetId,
            aspect_ratio=req.aspectRatio,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Image generation failed: {exc}") from exc


@app.post("/api/board/edit-image")
@app.post("/api/board/edit-image-region")
async def api_board_edit_image(req: BoardEditImageRequest):
    """
    Region-Preserving Partial Image Inpainting:
    Crops ONLY the selected rectangle `{x, y, width, height}`, generates a replacement patch via Nano Banana,
    and composites it back onto the original image so 100% of outer pixels are preserved.
    """
    prompt_str = (req.prompt or req.commandText or "").strip()
    region_box = req.region or req.selectedRegion or {"x": 0.22, "y": 0.18, "width": 0.56, "height": 0.62}
    try:
        res = await edit_board_image_region(
            prompt=prompt_str,
            region=region_box,
            asset_id=req.assetId or req.selectedAssetId or req.sourceAssetId,
            board_id=req.boardId or req.selectedBoardId,
            image_data_url=req.imageDataUrl or req.dataUrl,
            model_name=req.modelName or req.model,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Region image inpainting failed: {exc}") from exc


@app.post("/api/board/generate-video")
async def api_board_generate_video(req: BoardGenerateVideoRequest):
    """Generates a 720p 16:9 MP4 educational animation clip via `gemini-omni-1.1-flash` (with `ffmpeg` fallback)."""
    prompt_str = (req.prompt or req.commandText or "").strip()
    try:
        res = await generate_board_video(
            prompt=prompt_str,
            title=req.title,
            source_asset_id=req.sourceAssetId or req.assetId or req.selectedAssetId,
            source_board_id=req.sourceBoardId or req.boardId or req.selectedBoardId,
            source_data_url=req.sourceDataUrl or req.dataUrl or req.imageDataUrl,
            slide_id=req.slideId,
            model_name=req.modelName or req.model,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Video generation failed: {exc}") from exc


@app.post("/api/board/generate-diagram")
async def api_board_generate_diagram(req: BoardGenerateDiagramRequest):
    """Generates or updates an interactive 2D pathway/mechanism/comparison diagram."""
    prompt_str = (req.prompt or req.commandText or "").strip()
    try:
        res = await generate_board_diagram(
            prompt=prompt_str,
            template_id=req.templateId or req.template_id,
            selected_node_ids=req.selectedNodeIds or req.selectedElementIds,
            comparison_mode=req.comparisonMode,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Diagram generation failed: {exc}") from exc


@app.get("/api/board/slides")
def api_board_get_slides():
    """Returns built-in and imported lecture slides."""
    return JSONResponse(get_demo_slides())


@app.post("/api/board/import-slide")
async def api_board_import_slide(
    request: Request,
    file: Optional[UploadFile] = File(None),
):
    """
    Imports a `.pdf`, `.pptx`, `.ppt`, `.png`, `.jpg`, or `.webp` lecture slide deck.
    Supports both `multipart/form-data` (`file`) and JSON payloads (`{ filename, dataUrl }`).
    """
    try:
        if file is not None:
            raw_bytes = await file.read()
            fname = file.filename or "uploaded_slide.pdf"
        else:
            body = await request.json()
            fname = body.get("filename") or "uploaded_slide.png"
            data_url = body.get("dataUrl") or body.get("base64Data") or ""
            if "," in data_url:
                _, b64_part = data_url.split(",", 1)
                raw_bytes = base64.b64decode(b64_part)
            elif data_url:
                raw_bytes = base64.b64decode(data_url)
            else:
                raise HTTPException(status_code=400, detail="Either multipart file or JSON dataUrl is required.")

        res = await import_slide_deck(filename=fname, file_bytes=raw_bytes)
        return JSONResponse(res)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Slide deck import failed: {exc}") from exc


@app.post("/api/board/ingest-speech")
async def api_board_ingest_speech(req: BoardIngestSpeechRequest):
    """
    Ingests continuous lecture STT segments through the bilingual wake-phrase gate (`"비주얼 보드"` / `"Visual Board"`).
    Normal lecture segments (`LECTURE_ONLY`) are buffered without triggering generation;
    wake-phrase segments (`EXECUTE_REQUEST`) automatically trigger `execute_smart_command`.
    """
    speech_text = (req.text or req.transcript or req.commandText or "").strip()
    is_final = req.is_final if req.is_final is not None else req.isFinal
    try:
        res = await ingest_lecture_segment(
            text=speech_text,
            is_final=bool(is_final),
            segment_id=req.segmentId,
            event_id=req.eventId,
            speaker=req.speaker,
            explicit_ui_request=req.explicitUiRequest,
            active_mode=req.activeMode,
            selected_asset_id=req.selectedAssetId,
            selected_board_id=req.selectedBoardId,
            selected_region=req.selectedRegion,
            selected_element_ids=req.selectedElementIds,
            slide_id=req.slideId,
            force_mode=req.forceMode,
        )
        return JSONResponse(res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Lecture speech ingestion failed: {exc}") from exc


@app.get("/api/board/onboarding")
def api_board_get_onboarding():
    """Returns current 3-sample wake-phrase onboarding profile & session state."""
    return JSONResponse(
        {
            "ok": True,
            "wakeProfile": SESSION_STORE.wake_profile.to_dict(),
            "session": SESSION_STORE.get_status(),
        }
    )


@app.post("/api/board/onboarding")
def api_board_post_onboarding(req: BoardOnboardingRequest):
    """Records 1 or 3 wake-phrase calibration utterances (`"비주얼 보드"` / `"Visual Board"`) without triggering scene generation."""
    if req.reset:
        SESSION_STORE.start_onboarding(reset_samples=True)

    last_sample = None
    if req.samples:
        for idx, samp in enumerate(req.samples[:3], start=1):
            last_sample = SESSION_STORE.record_onboarding_sample(transcript=samp, step_index=idx)
    else:
        last_sample = SESSION_STORE.record_onboarding_sample(
            transcript=req.transcript,
            step_index=req.sampleIndex,
        )

    return JSONResponse(
        {
            "ok": True,
            "sampleResult": last_sample,
            "wakeProfile": SESSION_STORE.wake_profile.to_dict(),
            "session": SESSION_STORE.get_status(),
        }
    )


@app.post("/api/board/capture-3d-to-image")
async def api_board_capture_3d_to_image(req: BoardCapture3DRequest):
    """
    Captures the current 3D Anatomy scene into a Board Image asset so the user can immediately
    drag-select a region on the 3D snapshot for Nano Banana inpainting or Gemini Omni video animation.
    """
    data_url = req.dataUrl or req.imageDataUrl
    if not data_url:
        try:
            cap_res = await SCENE_SERVICE.capture_scene(
                session_id=req.sessionId,
                image_format="png",
                timeout_sec=2.0,
            )
            if cap_res.get("ok") and cap_res.get("dataUrl"):
                data_url = cap_res["dataUrl"]
        except Exception:
            data_url = None

    res = await capture_3d_to_board_image(
        data_url=data_url,
        title=req.title,
        subtitle=req.subtitle,
    )
    return JSONResponse(res)


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        return JSONResponse({"message": "CliniView Live 3D UI is initializing."})
    return FileResponse(str(index_path))
