from __future__ import annotations

import hashlib
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from knowledge_base import SOURCE_OF_TRUTH_DOCS


CANONICAL_WAKE_VARIANTS: list[str] = [
    "비주얼 보드",
    "비주얼보드",
    "비쥬얼 보드",
    "비쥬얼보드",
    "비주얼 보트",
    "비주얼보트",
    "비주얼 포드",
    "비주얼포드",
    "비주얼 보도",
    "비쥬얼 보트",
    "visual board",
]

# Phrases where "비주얼 보드" is mentioned as a noun/topic in lecture rather than a command invocation
META_MENTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"^비[주쥬]얼\s*보[드트도포][드]?[은는이가을를]\s*(?:음성|호출|도구|시스템|제품|서비스|화면|기능|설명)"),
    re.compile(r"^비[주쥬]얼\s*보[드트도포][드]?(?:라는|란|라고|에\s*대해|의\s*장점|를\s*소개|를\s*만들)"),
]

# Phrases that only open the request window without containing the actual visual command yet
WAKE_ONLY_FILLERS: set[str] = {
    "",
    "잠깐",
    "잠깐만",
    "잠시만",
    "잠시만요",
    "어",
    "음",
    "그",
    "자",
    "여기",
    "봐봐",
    "보여줘봐",
}

TOPIC_SHIFT_MARKERS: list[str] = [
    "이제 본론으로",
    "이번에는",
    "다음 주제로",
    "본격적으로",
    "한편 지금 설명할",
    "다시 돌아와서",
    "여기서부터는",
]


def now_ms() -> int:
    return int(time.time() * 1000)


def normalize_korean_text(text: str) -> str:
    cleaned = re.sub(r"[^\w\s가-힣a-zA-Z0-9]", " ", text or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


def compact_no_space(text: str) -> str:
    return re.sub(r"\s+", "", normalize_korean_text(text))


@dataclass
class WakePhraseProfile:
    profileId: str = "default-presenter"
    targetCount: int = 3
    samples: list[dict[str, Any]] = field(default_factory=list)
    confirmedVariants: list[str] = field(default_factory=lambda: list(CANONICAL_WAKE_VARIANTS))
    inputSensitivity: float = 0.75
    completed: bool = False
    updatedAtMs: int = field(default_factory=now_ms)
    disclaimer: str = (
        "이 온보딩은 개인 음성 모델을 새로 학습하거나 화자 인증(Speaker Verification)을 수행하지 않습니다. "
        "발표자의 마이크로 입력된 '비주얼 보드' 발화 결과의 텍스트 변형(예: 띄어쓰기, 철자 변형)과 입력 감도를 보정하고, "
        "인식 실패 시 즉시 사용할 수 있는 UI 호출 버튼 대안을 함께 제공합니다."
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "profileId": self.profileId,
            "targetCount": self.targetCount,
            "completedCount": sum(1 for s in self.samples if s.get("recognized")),
            "samples": list(self.samples),
            "confirmedVariants": list(dict.fromkeys(self.confirmedVariants)),
            "inputSensitivity": self.inputSensitivity,
            "completed": self.completed,
            "updatedAtMs": self.updatedAtMs,
            "disclaimer": self.disclaimer,
            "prompts": [
                {"step": 1, "type": "기본 호출", "script": "비주얼 보드"},
                {"step": 2, "type": "자연스러운 연결", "script": "비주얼 보드, 잠깐만"},
                {"step": 3, "type": "실제 요청 톤", "script": "비주얼 보드, 방금 설명한 거 보여줘"},
            ],
        }


class SessionStore:
    def __init__(self) -> None:
        self.session_id: str = f"sess-{uuid.uuid4().hex[:8]}"
        self.state: str = "idle"  # idle | onboarding | transcribing | collecting_request | executing | paused | ended
        self.retention_policy: str = "session_only"  # session_only | local_saved
        self.started_at_ms: int = now_ms()
        self.wake_profile: WakePhraseProfile = WakePhraseProfile()

        # Transcript storage
        self.segments: list[dict[str, Any]] = []
        self._segment_by_id: dict[str, int] = {}
        self.rolling_summary: str = ""
        self.active_topic_domain: str = "biology_pathway"

        # Request collection state
        self.collecting_since_ms: int | None = None
        self.collecting_cutoff_segment_id: str | None = None
        self.collecting_cutoff_timestamp_ms: int | None = None
        self.collecting_buffer: list[str] = []
        self.silence_timeout_ms: int = 6000

        # Idempotency & request tracking
        self.processed_event_ids: dict[str, dict[str, Any]] = {}
        self.processed_request_fingerprints: dict[str, dict[str, Any]] = {}
        self.requests: dict[str, dict[str, Any]] = {}
        self.active_request_id: str | None = None

    def reset_session(self, retention_policy: str = "session_only") -> dict[str, Any]:
        keep_profile = self.wake_profile
        self.__init__()
        self.wake_profile = keep_profile
        self.retention_policy = retention_policy
        self.state = "transcribing"
        return self.get_status()

    def delete_session_data(self) -> dict[str, Any]:
        """Cascading deletion of transcript segments, context snapshots, and request logs."""
        deleted_segments = len(self.segments)
        deleted_requests = len(self.requests)
        self.segments.clear()
        self._segment_by_id.clear()
        self.rolling_summary = ""
        self.processed_event_ids.clear()
        self.processed_request_fingerprints.clear()
        self.requests.clear()
        self.active_request_id = None
        self.collecting_since_ms = None
        self.collecting_cutoff_segment_id = None
        self.collecting_cutoff_timestamp_ms = None
        self.collecting_buffer.clear()
        self.state = "idle"
        return {
            "deleted": True,
            "deletedSegments": deleted_segments,
            "deletedRequests": deleted_requests,
            "state": self.state,
        }

    def export_session_data(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "startedAtMs": self.started_at_ms,
            "exportedAtMs": now_ms(),
            "retentionPolicy": self.retention_policy,
            "state": self.state,
            "rollingSummary": self.rolling_summary,
            "segments": list(self.segments),
            "requests": list(self.requests.values()),
            "wakeProfile": self.wake_profile.to_dict(),
        }

    def set_session_state(self, target_state: str) -> dict[str, Any]:
        valid = {"idle", "onboarding", "transcribing", "collecting_request", "executing", "paused", "ended"}
        if target_state not in valid:
            raise ValueError(f"Unsupported session state: {target_state}")
        self.state = target_state
        if target_state != "collecting_request":
            self.collecting_since_ms = None
            self.collecting_buffer.clear()
        return self.get_status()

    # ------------------------------------------------------------------
    # Onboarding (3-utterance Wake Phrase Check & Calibration)
    # ------------------------------------------------------------------
    def start_onboarding(self, reset_samples: bool = True) -> dict[str, Any]:
        self.state = "onboarding"
        if reset_samples:
            self.wake_profile.samples.clear()
            self.wake_profile.completed = False
        return {
            "state": self.state,
            "wakeProfile": self.wake_profile.to_dict(),
        }

    def record_onboarding_sample(
        self,
        transcript: str,
        step_index: int | None = None,
        volume_level: float = 0.82,
    ) -> dict[str, Any]:
        """
        Evaluates an onboarding utterance for '비주얼 보드' without triggering scene generation.
        """
        raw = (transcript or "").strip()
        norm = normalize_korean_text(raw)
        match_info = self._match_wake_phrase(raw)
        recognized = match_info["matched"] and volume_level >= 0.08
        extracted_variant = match_info.get("matchedSurface") or ""

        if not recognized and norm:
            # Check loose phonetic similarity for Korean STT variations during onboarding
            m = re.search(r"(비\s*[주쥬즈지]\s*[얼울원]\s*[보포버]\s*[드트도더])", raw)
            if m and volume_level >= 0.08:
                recognized = True
                extracted_variant = re.sub(r"\s+", " ", m.group(1)).strip()

        if recognized and extracted_variant:
            for candidate in [extracted_variant, extracted_variant.replace(" ", "")]:
                if candidate and candidate not in self.wake_profile.confirmedVariants:
                    self.wake_profile.confirmedVariants.append(candidate)

        sample_num = step_index or (len(self.wake_profile.samples) + 1)
        if volume_level < 0.08:
            coaching = "입력 음량이 너무 작습니다. 마이크 가까이에서 '비주얼 보드'라고 다시 말씀해 주세요."
        elif recognized:
            coaching = f"호출어 인식 성공 ('{extracted_variant}') — 현재 발음 변형이 호출 사전에 등록되었습니다."
        else:
            coaching = f"'{raw or '(무음)'}'에서 호출어 '비주얼 보드'가 감지되지 않았습니다. 재시도하거나 우측 호출 버튼을 사용할 수 있습니다."

        sample_entry = {
            "step": sample_num,
            "rawTranscript": raw,
            "normalizedTranscript": norm,
            "recognized": recognized,
            "extractedVariant": extracted_variant if recognized else None,
            "volumeLevel": round(float(volume_level), 2),
            "coachingMessage": coaching,
            "timestampMs": now_ms(),
            "triggeredSceneGeneration": False,  # Onboarding never triggers scene generation
        }

        # Replace existing step sample if retrying the same step, otherwise append
        replaced = False
        for idx, existing in enumerate(self.wake_profile.samples):
            if existing.get("step") == sample_num:
                self.wake_profile.samples[idx] = sample_entry
                replaced = True
                break
        if not replaced:
            self.wake_profile.samples.append(sample_entry)

        recognized_count = sum(1 for s in self.wake_profile.samples if s.get("recognized"))
        self.wake_profile.completed = recognized_count >= self.wake_profile.targetCount
        self.wake_profile.updatedAtMs = now_ms()
        if self.wake_profile.completed and self.state == "onboarding":
            self.state = "transcribing"

        return {
            "sample": sample_entry,
            "wakeProfile": self.wake_profile.to_dict(),
            "sessionState": self.state,
        }

    # ------------------------------------------------------------------
    # Wake Phrase Detection & Splitting
    # ------------------------------------------------------------------
    def _match_wake_phrase(self, text: str) -> dict[str, Any]:
        """
        Finds the wake phrase in `text`, returning prefix (lecture before wake),
        matched surface form, and suffix (command after wake).
        """
        if not text or not text.strip():
            return {"matched": False}

        # Build regex matching confirmed variants + canonical phonetic pattern
        escaped_variants = [
            re.escape(v).replace(r"\ ", r"\s*")
            for v in sorted(self.wake_profile.confirmedVariants, key=len, reverse=True)
            if v.strip()
        ]
        phonetic_pattern = r"(?:비\s*[주쥬즈]\s*[얼울]|visual(?:ize)?)\s*(?:[보포]\s*[드트도]|board)"
        combined_pattern = "|".join(escaped_variants + [phonetic_pattern])
        regex = re.compile(f"({combined_pattern})", re.IGNORECASE)

        match = regex.search(text)
        if not match:
            return {"matched": False}

        start_idx, end_idx = match.span()
        prefix = text[:start_idx].strip(" ,.·:-")
        matched_surface = match.group(1).strip()
        raw_suffix = text[end_idx:].strip()

        # Check if this is a meta-mention / quotation rather than a command invocation
        tail_from_wake = text[start_idx:].strip()
        for meta_re in META_MENTION_PATTERNS:
            if meta_re.search(tail_from_wake):
                return {
                    "matched": False,
                    "isMetaMention": True,
                    "matchedSurface": matched_surface,
                }

        # Strip polite vocative particles or punctuation immediately following wake phrase
        # e.g., "비주얼 보드, 방금 설명한 거 보여줘" or "비주얼 보드야 여기만 자세히"
        cleaned_suffix = re.sub(r"^(?:야|아)?[\s,.:·\-]+", "", raw_suffix).strip()
        if cleaned_suffix == raw_suffix:
            cleaned_suffix = re.sub(r"^[\s,.:·\-]+", "", raw_suffix).strip()

        return {
            "matched": True,
            "isMetaMention": False,
            "prefixLecture": prefix,
            "matchedSurface": matched_surface,
            "requestSuffix": cleaned_suffix,
        }

    # ------------------------------------------------------------------
    # Continuous STT Ingestion & Request Gate
    # ------------------------------------------------------------------
    def ingest_transcript_segment(
        self,
        text: str,
        is_final: bool = True,
        segment_id: str | None = None,
        event_id: str | None = None,
        timestamp_ms: int | None = None,
        speaker: str = "presenter",
        explicit_ui_request: bool = False,
        selected_element_ids: list[str] | None = None,
        base_scene_revision: int = 0,
    ) -> dict[str, Any]:
        """
        Core pipeline:
        1. Deduplicates replayed/reconnected events.
        2. If in `onboarding` mode, delegates to onboarding calibration without triggering generation.
        3. Updates partial/final transcript segment with timestamps.
        4. Applies strict RequestGate (`LECTURE_ONLY`, `META_MENTION_IGNORED`, `COLLECTING_REQUEST`, `EXECUTE_REQUEST`, `DUPLICATE_SUPPRESSED`).
        5. Freezes `ContextSnapshot` when transitioning to `executing`.
        """
        ts = timestamp_ms or now_ms()
        raw_text = (text or "").strip()
        seg_id = segment_id or f"seg-{uuid.uuid4().hex[:8]}"

        # 0. Event-level idempotency check (for reconnect / duplicate event delivery)
        if event_id and event_id in self.processed_event_ids:
            cached = dict(self.processed_event_ids[event_id])
            cached["gateDecision"] = "DUPLICATE_SUPPRESSED"
            cached["triggered"] = False
            cached["duplicateReason"] = f"Duplicate eventId '{event_id}' ignored"
            return cached

        # 1. Onboarding mode guard: never trigger scene generation during onboarding
        if self.state == "onboarding" and not explicit_ui_request:
            onboard_res = self.record_onboarding_sample(raw_text)
            result = {
                "gateDecision": "ONBOARDING_SAMPLE_RECORDED",
                "triggered": False,
                "sessionState": self.state,
                "onboarding": onboard_res,
            }
            if event_id:
                self.processed_event_ids[event_id] = result
            return result

        if self.state in {"idle", "ended"}:
            self.state = "transcribing"

        # 2. Check if this is a duplicate final segment already finalized with identical text
        if seg_id in self._segment_by_id:
            existing_idx = self._segment_by_id[seg_id]
            existing_seg = self.segments[existing_idx]
            if existing_seg.get("isFinal") and is_final and normalize_korean_text(existing_seg.get("text", "")) == normalize_korean_text(raw_text):
                dup_res = {
                    "gateDecision": "DUPLICATE_SUPPRESSED",
                    "triggered": False,
                    "duplicateReason": f"Segment '{seg_id}' already finalized",
                    "segment": existing_seg,
                    "sessionState": self.state,
                    "requestId": existing_seg.get("triggeredRequestId"),
                }
                if event_id:
                    self.processed_event_ids[event_id] = dup_res
                return dup_res

        # 3. Evaluate explicit UI request vs voice Wake Phrase
        if explicit_ui_request:
            wake_match = {
                "matched": True,
                "isMetaMention": False,
                "prefixLecture": "",
                "matchedSurface": "[UI 호출 버튼]",
                "requestSuffix": raw_text,
            }
        else:
            wake_match = self._match_wake_phrase(raw_text)

        # 4. Partial segment handling (`isFinal == False`):
        # Update live transcript preview and wake indicator, but NEVER execute scene generation yet.
        if not is_final:
            seg_record = self._upsert_segment(
                seg_id=seg_id,
                text=raw_text,
                is_final=False,
                timestamp_ms=ts,
                speaker=speaker,
                role="command_preview" if wake_match.get("matched") else "lecture_partial",
            )
            preview_res = {
                "gateDecision": "PARTIAL_PREVIEW",
                "triggered": False,
                "wakeDetectedInPartial": bool(wake_match.get("matched")),
                "segment": seg_record,
                "sessionState": self.state,
            }
            if event_id:
                self.processed_event_ids[event_id] = preview_res
            return preview_res

        # 5. Final segment handling (`isFinal == True`)
        # Case A: Currently in `collecting_request` (user previously said "비주얼 보드" and now speaks the request)
        if self.state == "collecting_request" and not wake_match.get("matched"):
            cleaned_followup = raw_text.strip()
            if normalize_korean_text(cleaned_followup) in WAKE_ONLY_FILLERS:
                seg_record = self._upsert_segment(
                    seg_id=seg_id,
                    text=raw_text,
                    is_final=True,
                    timestamp_ms=ts,
                    speaker=speaker,
                    role="wake_filler",
                )
                return {
                    "gateDecision": "COLLECTING_REQUEST",
                    "triggered": False,
                    "segment": seg_record,
                    "sessionState": self.state,
                }

            self.collecting_buffer.append(cleaned_followup)
            combined_request = " ".join(self.collecting_buffer).strip()
            seg_record = self._upsert_segment(
                seg_id=seg_id,
                text=raw_text,
                is_final=True,
                timestamp_ms=ts,
                speaker=speaker,
                role="voice_request",
            )
            return self._finalize_and_gate_request(
                request_text=combined_request,
                trigger_segment=seg_record,
                cutoff_segment_id=self.collecting_cutoff_segment_id,
                cutoff_timestamp_ms=self.collecting_cutoff_timestamp_ms or ts,
                selected_element_ids=selected_element_ids or [],
                base_scene_revision=base_scene_revision,
                trigger_source="voice_followup",
                event_id=event_id,
            )

        # Case B: Wake phrase matched in this utterance (or explicit UI trigger)
        if wake_match.get("matched"):
            prefix_lecture = wake_match.get("prefixLecture", "").strip()
            request_suffix = wake_match.get("requestSuffix", "").strip()

            # If speaker said lecture content right before "비주얼 보드" in the same breath, save prefix as lecture first!
            if prefix_lecture:
                prefix_seg_id = f"{seg_id}-pre"
                self._upsert_segment(
                    seg_id=prefix_seg_id,
                    text=prefix_lecture,
                    is_final=True,
                    timestamp_ms=ts - 50,
                    speaker=speaker,
                    role="lecture",
                )
                self._update_rolling_summary()

            cutoff_seg_id = self._get_latest_lecture_segment_id()
            cutoff_ts = ts

            # Check if the utterance only had "비주얼 보드" (or filler like "비주얼 보드, 잠깐만")
            if normalize_korean_text(request_suffix) in WAKE_ONLY_FILLERS:
                self.state = "collecting_request"
                self.collecting_since_ms = ts
                self.collecting_cutoff_segment_id = cutoff_seg_id
                self.collecting_cutoff_timestamp_ms = cutoff_ts
                self.collecting_buffer.clear()
                seg_record = self._upsert_segment(
                    seg_id=seg_id,
                    text=raw_text,
                    is_final=True,
                    timestamp_ms=ts,
                    speaker=speaker,
                    role="wake_call",
                )
                res = {
                    "gateDecision": "COLLECTING_REQUEST",
                    "triggered": False,
                    "segment": seg_record,
                    "sessionState": self.state,
                    "cutoffSegmentId": cutoff_seg_id,
                    "message": "호출어 '비주얼 보드'가 감지되었습니다. 이어서 요청을 말씀해 주세요.",
                }
                if event_id:
                    self.processed_event_ids[event_id] = res
                return res

            # Single-utterance wake + valid request (e.g. "비주얼 보드, 방금 설명한 것을 보여줘")
            seg_record = self._upsert_segment(
                seg_id=seg_id,
                text=raw_text,
                is_final=True,
                timestamp_ms=ts,
                speaker=speaker,
                role="voice_request" if not explicit_ui_request else "ui_request",
            )
            return self._finalize_and_gate_request(
                request_text=request_suffix,
                trigger_segment=seg_record,
                cutoff_segment_id=cutoff_seg_id,
                cutoff_timestamp_ms=cutoff_ts,
                selected_element_ids=selected_element_ids or [],
                base_scene_revision=base_scene_revision,
                trigger_source="ui_button" if explicit_ui_request else "voice_wake",
                event_id=event_id,
            )

        # Case C: Normal lecture speech (or meta-mention of "비주얼 보드")
        role = "lecture_meta" if wake_match.get("isMetaMention") else "lecture"
        seg_record = self._upsert_segment(
            seg_id=seg_id,
            text=raw_text,
            is_final=True,
            timestamp_ms=ts,
            speaker=speaker,
            role=role,
        )
        self._update_rolling_summary()
        # Note: if currently `executing`, we keep `executing` state while continuing transcription!
        if self.state not in {"executing", "paused"}:
            self.state = "transcribing"

        gate_decision = "META_MENTION_IGNORED" if wake_match.get("isMetaMention") else "LECTURE_ONLY"
        res = {
            "gateDecision": gate_decision,
            "triggered": False,
            "segment": seg_record,
            "sessionState": self.state,
            "rollingSummary": self.rolling_summary,
        }
        if event_id:
            self.processed_event_ids[event_id] = res
        return res

    def check_collection_timeout(self, current_ts_ms: int | None = None) -> dict[str, Any]:
        ts = current_ts_ms or now_ms()
        if self.state == "collecting_request" and self.collecting_since_ms is not None:
            elapsed = ts - self.collecting_since_ms
            if elapsed >= self.silence_timeout_ms:
                self.state = "transcribing"
                self.collecting_since_ms = None
                self.collecting_buffer.clear()
                return {
                    "timedOut": True,
                    "gateDecision": "COLLECTION_TIMEOUT",
                    "sessionState": self.state,
                    "elapsedMs": elapsed,
                }
        return {"timedOut": False, "sessionState": self.state}

    def _finalize_and_gate_request(
        self,
        request_text: str,
        trigger_segment: dict[str, Any],
        cutoff_segment_id: str | None,
        cutoff_timestamp_ms: int,
        selected_element_ids: list[str],
        base_scene_revision: int,
        trigger_source: str,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        norm_req = normalize_korean_text(request_text)
        fingerprint_raw = f"{norm_req}|{cutoff_segment_id or 'none'}|{'_'.join(sorted(selected_element_ids))}"
        fingerprint = hashlib.sha256(fingerprint_raw.encode("utf-8")).hexdigest()[:16]

        # Suppress duplicate request execution within 5 seconds ONLY if the exact same fingerprint
        # was the most recently executed voice request (prevents reconnect/partial-final double execution
        # while never blocking switching back and forth between scenes).
        existing_req = self.processed_request_fingerprints.get(fingerprint)
        if (
            trigger_source != "ui_button"
            and getattr(self, "_last_executed_fingerprint", None) == fingerprint
            and existing_req
            and (now_ms() - existing_req.get("createdAtMs", 0) < 5000)
        ):
            dup_res = {
                "gateDecision": "DUPLICATE_SUPPRESSED",
                "triggered": False,
                "duplicateReason": "Identical request + context fingerprint already triggered",
                "requestId": existing_req["requestId"],
                "contextSnapshot": existing_req["contextSnapshot"],
                "segment": trigger_segment,
                "sessionState": self.state,
            }
            if event_id:
                self.processed_event_ids[event_id] = dup_res
            return dup_res

        request_id = f"req-{uuid.uuid4().hex[:8]}"
        context_snapshot = self.build_context_snapshot(
            request_id=request_id,
            request_text=request_text,
            cutoff_segment_id=cutoff_segment_id,
            cutoff_timestamp_ms=cutoff_timestamp_ms,
            selected_element_ids=selected_element_ids,
            base_scene_revision=base_scene_revision,
            trigger_source=trigger_source,
        )

        # Reset collecting state and transition to executing
        self.collecting_since_ms = None
        self.collecting_buffer.clear()
        self.state = "executing"
        self.active_request_id = request_id
        self._last_executed_fingerprint = fingerprint
        trigger_segment["triggeredRequestId"] = request_id

        req_entry = {
            "requestId": request_id,
            "requestText": request_text,
            "normalizedRequest": norm_req,
            "triggerSource": trigger_source,
            "status": "executing",
            "createdAtMs": now_ms(),
            "cutoffSegmentId": cutoff_segment_id,
            "cutoffTimestampMs": cutoff_timestamp_ms,
            "baseSceneRevision": base_scene_revision,
            "contextSnapshot": context_snapshot,
        }
        self.requests[request_id] = req_entry
        self.processed_request_fingerprints[fingerprint] = req_entry

        res = {
            "gateDecision": "EXECUTE_REQUEST",
            "triggered": True,
            "requestId": request_id,
            "requestText": request_text,
            "contextSnapshot": context_snapshot,
            "segment": trigger_segment,
            "sessionState": self.state,
        }
        if event_id:
            self.processed_event_ids[event_id] = res
        return res

    def mark_request_completed(self, request_id: str, result_summary: dict[str, Any] | None = None) -> None:
        req = self.requests.get(request_id)
        if req and req.get("status") != "cancelled":
            req["status"] = "completed"
            req["completedAtMs"] = now_ms()
            if result_summary:
                req["resultSummary"] = result_summary
        if self.active_request_id == request_id:
            self.active_request_id = None
            if self.state == "executing":
                self.state = "transcribing"

    def mark_request_cancelled(self, request_id: str | None = None) -> dict[str, Any]:
        target_id = request_id or self.active_request_id
        if not target_id or target_id not in self.requests:
            if self.state == "executing":
                self.state = "transcribing"
            return {"cancelled": False, "requestId": target_id, "sessionState": self.state}

        req = self.requests[target_id]
        req["status"] = "cancelled"
        req["cancelledAtMs"] = now_ms()
        if self.active_request_id == target_id:
            self.active_request_id = None
        if self.state == "executing":
            self.state = "transcribing"
        return {
            "cancelled": True,
            "requestId": target_id,
            "sessionState": self.state,
        }

    def is_request_cancelled(self, request_id: str) -> bool:
        req = self.requests.get(request_id)
        if not req:
            return False
        return req.get("status") == "cancelled"

    # ------------------------------------------------------------------
    # Context Builder & Topic Boundary Resolution
    # ------------------------------------------------------------------
    def build_context_snapshot(
        self,
        request_id: str,
        request_text: str,
        cutoff_segment_id: str | None,
        cutoff_timestamp_ms: int,
        selected_element_ids: list[str],
        base_scene_revision: int,
        trigger_source: str,
    ) -> dict[str, Any]:
        """
        Builds a frozen ContextSnapshot strictly bounded by `cutoff_segment_id` / `cutoff_timestamp_ms`.
        Separates the active topic window from earlier unrelated examples (e.g. mRNA vaccine intro vs GPCR topic).
        """
        lecture_segments: list[dict[str, Any]] = []
        for seg in self.segments:
            if not seg.get("isFinal"):
                continue
            if seg.get("role") not in {"lecture", "lecture_meta"}:
                continue
            if seg.get("timestampMs", 0) <= cutoff_timestamp_ms:
                lecture_segments.append(seg)
            if cutoff_segment_id and seg.get("segmentId") == cutoff_segment_id:
                break

        # Detect topic shift boundary so "방금 설명한 것" binds to the active topic
        topic_start_idx = 0
        for idx, seg in enumerate(lecture_segments):
            txt = seg.get("text", "")
            if any(marker in txt for marker in TOPIC_SHIFT_MARKERS):
                topic_start_idx = idx

        active_window_segments = lecture_segments[topic_start_idx:] if lecture_segments else []
        excluded_prior_segments = lecture_segments[:topic_start_idx] if topic_start_idx > 0 else []

        active_text = " ".join(s.get("text", "") for s in active_window_segments)
        # If the user's explicit request text names a specific domain, prioritize it over prior active_text
        explicit_req_domain = self._infer_explicit_domain(request_text)
        if explicit_req_domain:
            inferred_domain = explicit_req_domain
        else:
            inferred_domain = self._infer_domain(active_text + " " + request_text)
        self.active_topic_domain = inferred_domain

        matched_sot = [
            doc for doc in SOURCE_OF_TRUTH_DOCS if doc["domain"] == inferred_domain
        ]

        return {
            "requestId": request_id,
            "requestText": request_text,
            "triggerSource": trigger_source,
            "cutoffSegmentId": cutoff_segment_id,
            "cutoffTimestampMs": cutoff_timestamp_ms,
            "baseSceneRevision": base_scene_revision,
            "selectedElementIds": list(selected_element_ids),
            "inferredDomain": inferred_domain,
            "activeTopicText": active_text,
            "activeTopicSegments": [
                {"segmentId": s["segmentId"], "text": s["text"], "timestampMs": s["timestampMs"]}
                for s in active_window_segments[-8:]
            ],
            "excludedPriorTopics": [
                {"segmentId": s["segmentId"], "text": s["text"], "reason": "Prior topic before transition marker"}
                for s in excluded_prior_segments
            ],
            "rollingSummary": self.rolling_summary,
            "connectedSources": [
                {"id": doc["id"], "title": doc["title"], "summary": doc["summary"], "citation": doc["citation"]}
                for doc in matched_sot
            ],
        }

    def _infer_explicit_domain(self, text: str) -> str | None:
        norm = normalize_korean_text(text)
        anatomy_keywords = ["견갑하근", "회전근개", "어깨", "대흉근", "소흉근", "삼각근", "늑골", "견갑골", "상완골", "액와", "극상근", "근육"]
        system_keywords = ["큐", "워커", "백프레셔", "게이트웨이", "dlq", "비동기", "메시지"]
        gpcr_keywords = ["gpcr", "수용체", "리간드", "camp", "pka", "아데닐산", "신호", "길항제", "단백질", "gtp", "gdp", "3단계", "서브유닛"]

        anat_score = sum(1 for k in anatomy_keywords if k in norm)
        sys_score = sum(1 for k in system_keywords if k in norm)
        gpcr_score = sum(1 for k in gpcr_keywords if k in norm)

        if anat_score > gpcr_score and anat_score > sys_score:
            return "anatomy_3d"
        if sys_score > gpcr_score and sys_score > anat_score:
            return "system_architecture"
        if gpcr_score > anat_score and gpcr_score > sys_score:
            return "biology_pathway"
        return None

    def _infer_domain(self, text: str) -> str:
        explicit = self._infer_explicit_domain(text)
        if explicit:
            return explicit
        return self.active_topic_domain or "biology_pathway"

    def _upsert_segment(
        self,
        seg_id: str,
        text: str,
        is_final: bool,
        timestamp_ms: int,
        speaker: str,
        role: str,
    ) -> dict[str, Any]:
        record = {
            "segmentId": seg_id,
            "text": text,
            "isFinal": is_final,
            "timestampMs": timestamp_ms,
            "speaker": speaker,
            "role": role,
        }
        if seg_id in self._segment_by_id:
            idx = self._segment_by_id[seg_id]
            self.segments[idx].update(record)
            return self.segments[idx]
        self._segment_by_id[seg_id] = len(self.segments)
        self.segments.append(record)
        return record

    def _get_latest_lecture_segment_id(self) -> str | None:
        for seg in reversed(self.segments):
            if seg.get("isFinal") and seg.get("role") in {"lecture", "lecture_meta"}:
                return seg["segmentId"]
        return None

    def _update_rolling_summary(self) -> None:
        lecture_segs = [
            s for s in self.segments if s.get("isFinal") and s.get("role") in {"lecture", "lecture_meta"}
        ]
        if not lecture_segs:
            self.rolling_summary = ""
            return
        recent_texts = [s["text"] for s in lecture_segs[-5:]]
        self.rolling_summary = " / ".join(recent_texts)
        self.active_topic_domain = self._infer_domain(" ".join(recent_texts))

    def get_status(self) -> dict[str, Any]:
        return {
            "sessionId": self.session_id,
            "state": self.state,
            "retentionPolicy": self.retention_policy,
            "startedAtMs": self.started_at_ms,
            "segmentCount": len(self.segments),
            "rollingSummary": self.rolling_summary,
            "activeTopicDomain": self.active_topic_domain,
            "activeRequestId": self.active_request_id,
            "wakeProfile": self.wake_profile.to_dict(),
            "recentSegments": self.segments[-20:],
        }
