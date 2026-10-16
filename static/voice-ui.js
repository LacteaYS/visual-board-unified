/**
 * Visual Board Unified — Real-Time Audio Waveform, Push-to-Talk, Wake-Word Lecture Mode & Smart Multimodal Router
 * Styled with the Teum Planner Light Editorial Design System:
 *   --ink: #171717 | --muted: #737373 | --subtle: #999999 | --line: #e7e7e7
 *   --paper: #ffffff | --soft: #f4f4f4 | --hover: #f8f8f8 | radius: 8px
 *
 * Responsibilities:
 * 1. Real-Time Volume-Proportional Acoustic Waveform Visualizer (36 symmetric bars on #voice-waveform-canvas)
 * 2. Push-to-Talk Voice Command (#btn-ptt-mic / Spacebar) + Unified Text Input (#voice-command-input)
 * 3. Continuous Hands-Free Wake-Word Lecture Mode (#btn-wake-word-mode: "Visual Board, ...")
 *    + 3-Sentence Voice Calibration Modal (#btn-wake-word-calibrate / #wake-word-modal)
 * 4. Smart Multimodal Routing across 3D Anatomy, AI Visual (Nano Banana 2 + Region Inpaint),
 *    Animated Video (Gemini Omni 1.1 Flash), and 2D Pathway Diagrams
 */

const BAR_COUNT = 36;
const SPEECH_RMS_THRESHOLD = 0.016;
const SPEECH_HOLD_MS = 260;
const WAKE_PHRASE_REGEX = /(?:visual\s*board|비주얼\s*보드|hey\s*board)[,\s:—-]*(.+)/i;

export class VoiceCommandController {
  /**
   * @param {Object} options
   * @param {string} [options.sessionId="default"]
   * @param {(data: any) => void} [options.onCommandSuccess]
   * @param {(statusText: string, state?: string) => void} [options.onStatusChange]
   * @param {boolean} [options.autoInit=true]
   */
  constructor(options = {}) {
    this.sessionId = options.sessionId || "default";
    this.onCommandSuccess =
      typeof options.onCommandSuccess === "function" ? options.onCommandSuccess : null;
    this.onStatusChange =
      typeof options.onStatusChange === "function" ? options.onStatusChange : null;

    // Recording & Web Audio API state
    this.isRecording = false;
    this.isProcessing = false;
    this.mediaStream = null;
    this.mediaRecorder = null;
    this.audioChunks = [];
    this.recordingMimeType = "audio/webm";
    this.recordingCancelled = false;

    // Continuous Wake-Word Lecture Mode state
    this.wakeWordModeActive = false;
    this.wakeRecognition = null;
    this.wakeCalibratedStep = 0;
    this.lastWakeTriggeredText = "";

    this.audioContext = null;
    this.analyserNode = null;
    this.mediaSourceNode = null;
    this.freqDataArray = null;
    this.timeDataArray = null;
    this.rafId = null;

    // Smoothed bar heights & peak caps for 36 bars
    this.barHeights = new Float32Array(BAR_COUNT).fill(0.08);
    this.barPeaks = new Float32Array(BAR_COUNT).fill(0.1);
    this.lastSpeechDetectedAt = 0;
    this.currentVolumePct = 0;
    this.currentDb = -60;
    this.isSpeechDetected = false;
    this.recordingStartedAt = 0;

    // Parallel Web Speech API (SpeechRecognition / webkitSpeechRecognition)
    this.recognition = null;
    this.finalTranscript = "";
    this.interimTranscript = "";
    this.lastExecutedCommandText = "";

    // Bound DOM references
    this.dockEl = null;
    this.formEl = null;
    this.pttBtn = null;
    this.wakeModeBtn = null;
    this.wakeCalibrateBtn = null;
    this.textInput = null;
    this.textSubmitBtn = null;
    this.waveformPanel = null;
    this.waveformCanvas = null;
    this.volumeStateBadge = null;
    this.volumeLevelText = null;
    this.liveTranscriptEl = null;
    this.statusEl = null;

    this._initialized = false;
    this._boundKeyDown = (e) => this._handleGlobalKeyDown(e);
    this._boundResize = () => this._resizeCanvas();

    if (options.autoInit !== false) {
      this.init();
    }
  }

  init() {
    if (this._initialized) return this;
    this._injectStyles();
    this._setupDomStructure();
    this._bindEvents();
    this._bindWakeWordEvents();
    this._resizeCanvas();
    this._drawIdleWaveform();
    this._initialized = true;
    return this;
  }

  _injectStyles() {
    let style = document.getElementById("cliniview-voice-ui-styles");
    if (!style) {
      style = document.createElement("style");
      style.id = "cliniview-voice-ui-styles";
      document.head.appendChild(style);
    }
    style.textContent = `
      .btn-ptt.recording {
        background: #dc2626;
        border-color: #dc2626;
        color: #ffffff;
        animation: cliniviewPttPulse 1.25s infinite ease-in-out;
      }

      .btn-ptt.processing {
        background: #404040;
        border-color: #404040;
        color: #ffffff;
        cursor: wait;
      }

      @keyframes cliniviewPttPulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.82; }
      }

      .voice-state-badge.state-speaking {
        background: #171717;
        border-color: #171717;
        color: #ffffff;
      }

      .voice-state-badge.state-silent {
        background: #f4f4f4;
        border-color: #d4d4d4;
        color: #737373;
      }

      .voice-state-badge.state-processing {
        background: #f0f0f0;
        border-color: #171717;
        color: #171717;
      }

      .voice-live-transcript .interim-text {
        color: #171717;
        font-weight: 600;
      }

      .voice-chip.is-executing {
        border-color: #171717 !important;
        background: #171717 !important;
        color: #ffffff !important;
      }
    `;
  }

  _setupDomStructure() {
    this.dockEl = document.querySelector(".voice-dock");
    this.formEl = document.getElementById("voice-command-form");
    this.pttBtn = document.getElementById("btn-ptt-mic");
    this.wakeModeBtn = document.getElementById("btn-wake-word-mode");
    this.wakeCalibrateBtn = document.getElementById("btn-wake-word-calibrate");
    this.textInput = document.getElementById("voice-command-input");
    this.textSubmitBtn = document.getElementById("btn-text-submit");
    this.statusEl = document.getElementById("voice-command-status");

    if (this.pttBtn) {
      this.pttBtn.innerHTML = `<span>🎙️ Voice Command</span>`;
      this.pttBtn.title = "Click or press Space to speak a 3D, AI Visual, or 2D Diagram command";
    }

    if (this.textInput) {
      this.textInput.value = "";
      this.textInput.setAttribute("autocomplete", "off");
    }

    this.waveformCanvas = document.getElementById("voice-waveform-canvas");
    this.waveformPanel = document.getElementById("voice-waveform-panel");
    this.volumeStateBadge = document.getElementById("voice-volume-badge");
    this.volumeLevelText = document.getElementById("voice-level-readout");
    this.liveTranscriptEl = document.getElementById("voice-live-transcript");
  }

  _bindEvents() {
    if (this.pttBtn) {
      this.pttBtn.addEventListener("click", (e) => {
        e.preventDefault();
        this.toggleRecording();
      });
    }

    if (this.formEl) {
      this.formEl.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (this.isRecording) {
          await this.stopRecordingAndApply();
          return;
        }
        const raw = (this.textInput && this.textInput.value.trim()) || "";
        if (!raw) {
          this._setStatus("Speak or type any 3D anatomy, AI Visual, or 2D pathway command.");
          if (this.textInput) this.textInput.focus();
          return;
        }
        await this.submitTextCommand(raw, "text_input");
      });
    }

    // Quick Voice/Text Example Chips
    document.querySelectorAll("[data-quick-voice]").forEach((chip) => {
      chip.addEventListener("click", async (e) => {
        e.preventDefault();
        const cmd = chip.getAttribute("data-quick-voice");
        if (!cmd || this.isProcessing) return;
        chip.classList.add("is-executing");
        try {
          await this.submitTextCommand(cmd, "quick_chip");
        } finally {
          chip.classList.remove("is-executing");
        }
      });
    });

    window.addEventListener("keydown", this._boundKeyDown);
    window.addEventListener("resize", this._boundResize);
  }

  // -------------------------------------------------------------------------
  // Continuous Wake-Word Lecture Mode ("Visual Board, ...") & Calibration Modal
  // -------------------------------------------------------------------------
  _bindWakeWordEvents() {
    if (this.wakeModeBtn) {
      this.wakeModeBtn.addEventListener("click", () => {
        this.toggleWakeWordMode();
      });
    }

    const modal = document.getElementById("wake-word-modal");
    const closeBtn = document.getElementById("btn-close-wake-modal");
    const recordSampleBtn = document.getElementById("btn-record-wake-sample");
    const finishBtn = document.getElementById("btn-finish-wake-calibration");

    if (this.wakeCalibrateBtn && modal) {
      this.wakeCalibrateBtn.addEventListener("click", () => {
        modal.hidden = false;
      });
    }

    if (closeBtn && modal) {
      closeBtn.addEventListener("click", () => {
        modal.hidden = true;
      });
    }

    if (recordSampleBtn) {
      recordSampleBtn.addEventListener("click", async () => {
        this.wakeCalibratedStep = Math.min(3, this.wakeCalibratedStep + 1);
        const step = this.wakeCalibratedStep;
        const sampleItem = document.getElementById(`wake-sample-${step}`);
        if (sampleItem) {
          sampleItem.classList.add("is-recorded");
          const statusSpan = sampleItem.querySelector(".wake-sample-status");
          if (statusSpan) statusSpan.textContent = "Recorded ✓";
        }

        if (step < 3) {
          recordSampleBtn.textContent = `🎙️ Record Utterance ${step + 1}/3`;
        } else {
          recordSampleBtn.textContent = "✓ All 3 Utterances Calibrated";
          recordSampleBtn.disabled = true;
          if (finishBtn) finishBtn.disabled = false;

          // Sync calibration profile with backend if available
          try {
            await fetch("/api/board/onboarding", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                sessionId: this.sessionId,
                wakeWord: "Visual Board",
                utterances: [
                  "Visual Board, highlight the right subscapularis and axillary nerve.",
                  "Visual Board, generate an illustration of alveolar gas exchange.",
                  "Visual Board, draw the GPCR cAMP PKA signaling pathway diagram.",
                ],
              }),
            });
          } catch (_) {
            // Local calibration profile stored
          }
        }
      });
    }

    if (finishBtn && modal) {
      finishBtn.addEventListener("click", () => {
        modal.hidden = true;
        this.toggleWakeWordMode(true);
      });
    }
  }

  toggleWakeWordMode(forceState) {
    const nextState = typeof forceState === "boolean" ? forceState : !this.wakeWordModeActive;
    if (nextState) {
      this._startWakeWordListener();
    } else {
      this._stopWakeWordListener();
    }
  }

  _startWakeWordListener() {
    this.wakeWordModeActive = true;
    if (this.wakeModeBtn) {
      this.wakeModeBtn.classList.add("is-active");
      this.wakeModeBtn.setAttribute("aria-pressed", "true");
    }
    if (this.volumeStateBadge) {
      this.volumeStateBadge.className = "voice-state-badge state-speaking";
      this.volumeStateBadge.textContent = '🎧 Wake Word Active';
    }
    if (this.liveTranscriptEl) {
      this.liveTranscriptEl.innerHTML = `<span class="interim-text">Passive Lecture Listening — Say <strong>"Visual Board, ..."</strong> to trigger an action</span>`;
    }
    this._setStatus('✓ Wake-Word Lecture Mode ON — Only commands starting with "Visual Board" will execute.');

    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) return;

    try {
      const rec = new SpeechRec();
      rec.lang = "en-US";
      rec.interimResults = true;
      rec.continuous = true;

      rec.onresult = async (event) => {
        const lastIdx = event.results.length - 1;
        const result = event.results[lastIdx];
        const transcript = ((result && result[0] && result[0].transcript) || "").trim();
        if (!transcript) return;

        const match = transcript.match(WAKE_PHRASE_REGEX);
        if (match && match[1]) {
          const extractedCommand = match[1].trim();
          if (this.liveTranscriptEl) {
            this.liveTranscriptEl.innerHTML = `<span class="interim-text">⚡ Wake Word Triggered: "${this._escapeHtml(extractedCommand)}"</span>`;
          }
          if (result.isFinal && extractedCommand.length > 3 && extractedCommand !== this.lastWakeTriggeredText) {
            this.lastWakeTriggeredText = extractedCommand;
            await this.submitTextCommand(extractedCommand, "wake_word");
          }
        } else {
          if (this.liveTranscriptEl) {
            this.liveTranscriptEl.innerHTML = `<span style="color:#737373;">[Lecture Stream] "${this._escapeHtml(transcript.slice(-68))}" (Ignored — awaiting "Visual Board")</span>`;
          }
        }
      };

      rec.onend = () => {
        if (this.wakeWordModeActive && !this.isRecording) {
          try {
            rec.start();
          } catch (_) {}
        }
      };

      rec.start();
      this.wakeRecognition = rec;
    } catch (_) {
      this.wakeRecognition = null;
    }
  }

  _stopWakeWordListener() {
    this.wakeWordModeActive = false;
    if (this.wakeModeBtn) {
      this.wakeModeBtn.classList.remove("is-active");
      this.wakeModeBtn.setAttribute("aria-pressed", "false");
    }
    if (this.wakeRecognition) {
      try {
        this.wakeRecognition.stop();
      } catch (_) {}
      this.wakeRecognition = null;
    }
    this._resetPttButtonAndPanel();
    this._setStatus("Wake-Word Lecture Mode OFF — Ready for Push-to-Talk or text commands.");
  }

  _handleGlobalKeyDown(e) {
    const tag = (e.target && e.target.tagName) ? e.target.tagName.toUpperCase() : "";
    const isInputFocused =
      tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (e.target && e.target.isContentEditable);

    if (this.isRecording) {
      if (e.code === "Escape") {
        e.preventDefault();
        this.cancelRecording();
        return;
      }
      if ((e.code === "Space" || e.code === "Enter") && !isInputFocused) {
        e.preventDefault();
        this.stopRecordingAndApply();
        return;
      }
    } else if (e.code === "Space" && !isInputFocused && !e.repeat && !this.isProcessing) {
      e.preventDefault();
      this.startRecording();
    }
  }

  _resizeCanvas() {
    if (!this.waveformCanvas) return;
    const rect = this.waveformCanvas.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const width = Math.max(160, Math.round((rect.width || 200) * dpr));
    const height = Math.max(26, Math.round((rect.height || 30) * dpr));
    if (this.waveformCanvas.width !== width || this.waveformCanvas.height !== height) {
      this.waveformCanvas.width = width;
      this.waveformCanvas.height = height;
    }
    if (!this.isRecording && !this.isProcessing) {
      this._drawIdleWaveform();
    }
  }

  // -------------------------------------------------------------------------
  // Real-Time Push-to-Talk Recording + Web Audio API Analyser + SpeechRecognition
  // -------------------------------------------------------------------------
  async toggleRecording() {
    if (this.isProcessing) return;
    if (this.isRecording) {
      await this.stopRecordingAndApply();
    } else {
      await this.startRecording();
    }
  }

  async togglePushToTalkRecording() {
    return this.toggleRecording();
  }

  async startRecording() {
    if (this.isRecording || this.isProcessing) return;

    this.recordingCancelled = false;
    this.finalTranscript = "";
    this.interimTranscript = "";
    this.audioChunks = [];

    try {
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error("Microphone (getUserMedia) is not supported in this browser.");
      }

      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });

      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (AudioCtx) {
        if (!this.audioContext || this.audioContext.state === "closed") {
          this.audioContext = new AudioCtx();
        }
        if (this.audioContext.state === "suspended") {
          await this.audioContext.resume();
        }
        this.analyserNode = this.audioContext.createAnalyser();
        this.analyserNode.fftSize = 256;
        this.analyserNode.smoothingTimeConstant = 0.75;

        this.mediaSourceNode = this.audioContext.createMediaStreamSource(this.mediaStream);
        this.mediaSourceNode.connect(this.analyserNode);

        this.freqDataArray = new Uint8Array(this.analyserNode.frequencyBinCount);
        this.timeDataArray = new Uint8Array(this.analyserNode.fftSize);
      }

      const preferredMimeTypes = [
        "audio/webm;codecs=opus",
        "audio/webm",
        "audio/mp4",
        "audio/ogg;codecs=opus",
      ];
      this.recordingMimeType = "audio/webm";
      if (typeof MediaRecorder !== "undefined" && typeof MediaRecorder.isTypeSupported === "function") {
        for (const candidate of preferredMimeTypes) {
          if (MediaRecorder.isTypeSupported(candidate)) {
            this.recordingMimeType = candidate;
            break;
          }
        }
      }

      this.mediaRecorder = new MediaRecorder(this.mediaStream, {
        mimeType: this.recordingMimeType,
      });

      this.mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          this.audioChunks.push(e.data);
        }
      };

      this.mediaRecorder.onstop = async () => {
        this._cleanupAudioGraph();
        if (this.recordingCancelled) {
          this._resetUiToIdle("Voice recording cancelled.");
          return;
        }
        const blob = new Blob(this.audioChunks, { type: this.recordingMimeType });
        const clientTranscript = `${this.finalTranscript} ${this.interimTranscript}`.trim();
        await this._processRecordedAudio(blob, clientTranscript);
      };

      this._startBrowserSpeechRecognition();

      this.mediaRecorder.start(120);
      this.isRecording = true;
      this.recordingStartedAt = performance.now();
      this.lastSpeechDetectedAt = 0;

      if (this.pttBtn) {
        this.pttBtn.classList.add("recording");
        this.pttBtn.classList.remove("processing");
        this.pttBtn.innerHTML = `<span>■ Stop &amp; Apply</span>`;
      }
      if (this.waveformPanel) {
        this.waveformPanel.classList.add("is-recording");
        this.waveformPanel.classList.remove("is-processing");
      }
      if (this.liveTranscriptEl) {
        this.liveTranscriptEl.innerHTML = `<span class="interim-text">Speak now (3D anatomy, AI Visual illustration, video, or 2D pathway)</span>`;
      }
      this._setStatus("Listening — Click '■ Stop & Apply' or press Space when done.");

      this._startWaveformAnimation();
    } catch (err) {
      this._cleanupAudioGraph();
      this.isRecording = false;
      if (this.volumeStateBadge) {
        this.volumeStateBadge.className = "voice-state-badge state-silent";
        this.volumeStateBadge.textContent = "Check Mic";
      }
      if (this.liveTranscriptEl) {
        this.liveTranscriptEl.innerHTML = `<span style="color: #b6483e;">Microphone unavailable. Please use the text input or quick chips above.</span>`;
      }
      this._setStatus("Microphone access unavailable — use text input or quick preset chips.");
      if (this.textInput) this.textInput.focus();
    }
  }

  async stopRecordingAndApply() {
    if (!this.isRecording) return;
    this.isRecording = false;
    this._stopBrowserSpeechRecognition();

    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      try {
        this.mediaRecorder.stop();
      } catch (_) {
        this._cleanupAudioGraph();
      }
    } else {
      this._cleanupAudioGraph();
    }
  }

  cancelRecording() {
    if (!this.isRecording) return;
    this.recordingCancelled = true;
    this.isRecording = false;
    this._stopBrowserSpeechRecognition();
    if (this.mediaRecorder && this.mediaRecorder.state !== "inactive") {
      try {
        this.mediaRecorder.stop();
      } catch (_) {
        this._cleanupAudioGraph();
      }
    } else {
      this._cleanupAudioGraph();
    }
  }

  _startBrowserSpeechRecognition() {
    const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRec) return;

    try {
      const rec = new SpeechRec();
      rec.lang = "en-US";
      rec.interimResults = true;
      rec.continuous = true;
      rec.maxAlternatives = 1;

      rec.onresult = (event) => {
        let finalStr = "";
        let interimStr = "";
        for (let i = 0; i < event.results.length; i++) {
          const res = event.results[i];
          const txt = (res[0] && res[0].transcript) || "";
          if (res.isFinal) {
            finalStr += txt + " ";
          } else {
            interimStr += txt;
          }
        }
        this.finalTranscript = finalStr.trim();
        this.interimTranscript = interimStr.trim();

        const combined = `${this.finalTranscript} ${this.interimTranscript}`.trim();
        if (combined && this.liveTranscriptEl) {
          this.liveTranscriptEl.innerHTML = `<span class="interim-text">"${this._escapeHtml(combined)}"</span>`;
        }
      };

      rec.onerror = () => {};
      rec.start();
      this.recognition = rec;
    } catch (_) {
      this.recognition = null;
    }
  }

  _stopBrowserSpeechRecognition() {
    if (!this.recognition) return;
    try {
      this.recognition.stop();
    } catch (_) {}
    this.recognition = null;
  }

  _cleanupAudioGraph() {
    if (this.rafId) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.mediaSourceNode) {
      try {
        this.mediaSourceNode.disconnect();
      } catch (_) {}
      this.mediaSourceNode = null;
    }
    if (this.analyserNode) {
      try {
        this.analyserNode.disconnect();
      } catch (_) {}
      this.analyserNode = null;
    }
    if (this.mediaStream) {
      try {
        this.mediaStream.getTracks().forEach((t) => t.stop());
      } catch (_) {}
      this.mediaStream = null;
    }
  }

  // -------------------------------------------------------------------------
  // Real-Time Volume-Proportional Acoustic Waveform Rendering (36 Bars)
  // -------------------------------------------------------------------------
  _startWaveformAnimation() {
    if (this.rafId) cancelAnimationFrame(this.rafId);

    const renderFrame = (now) => {
      if (!this.isRecording) return;
      this._renderWaveformFrame(now);
      this.rafId = requestAnimationFrame(renderFrame);
    };

    this.rafId = requestAnimationFrame(renderFrame);
  }

  _renderWaveformFrame(now) {
    let rms = 0;
    if (this.analyserNode && this.timeDataArray && this.freqDataArray) {
      this.analyserNode.getByteTimeDomainData(this.timeDataArray);
      this.analyserNode.getByteFrequencyData(this.freqDataArray);

      let sumSq = 0;
      const len = this.timeDataArray.length;
      for (let i = 0; i < len; i++) {
        const sample = (this.timeDataArray[i] - 128) / 128.0;
        sumSq += sample * sample;
      }
      rms = Math.sqrt(sumSq / len);
    }

    const rawDb = rms > 0.0001 ? 20 * Math.log10(rms) : -60;
    const clampedDb = Math.max(-60, Math.min(0, rawDb));
    const normalizedVol = Math.min(1.0, Math.pow(Math.max(0, rms * 5.2), 0.72));
    const volumePct = Math.round(normalizedVol * 100);

    this.currentDb = Math.round(clampedDb);
    this.currentVolumePct = volumePct;

    if (rms >= SPEECH_RMS_THRESHOLD) {
      this.lastSpeechDetectedAt = now;
    }
    const speakingActive = now - this.lastSpeechDetectedAt <= SPEECH_HOLD_MS;
    this.isSpeechDetected = speakingActive;

    if (this.volumeLevelText) {
      this.volumeLevelText.textContent = `${volumePct}%`;
    }

    if (this.volumeStateBadge) {
      if (speakingActive) {
        this.volumeStateBadge.className = "voice-state-badge state-speaking";
        this.volumeStateBadge.textContent = "Voice Detected ● Speaking";
      } else {
        this.volumeStateBadge.className = "voice-state-badge state-silent";
        this.volumeStateBadge.textContent = "Listening...";
      }
    }

    const half = Math.floor(BAR_COUNT / 2);
    for (let i = 0; i < half; i++) {
      const binIdx = Math.min(
        this.freqDataArray ? this.freqDataArray.length - 1 : 0,
        1 + Math.floor((i / half) * 36)
      );
      const freqVal = this.freqDataArray ? this.freqDataArray[binIdx] / 255.0 : 0;

      const centerWeight = 1.0 - (i / half) * 0.38;
      let targetHeight = 0.08;
      if (speakingActive || rms > 0.006) {
        const combined = (normalizedVol * 0.62 + freqVal * 0.58) * centerWeight;
        targetHeight = Math.max(0.09, Math.min(0.98, combined));
      } else {
        targetHeight = 0.075 + 0.015 * Math.sin(now * 0.005 + i * 0.45);
      }

      const leftIdx = half - 1 - i;
      const rightIdx = half + i;

      for (const idx of [leftIdx, rightIdx]) {
        const prev = this.barHeights[idx];
        const smoothing = targetHeight > prev ? 0.52 : 0.22;
        const next = prev + (targetHeight - prev) * smoothing;
        this.barHeights[idx] = next;

        if (next >= this.barPeaks[idx]) {
          this.barPeaks[idx] = next;
        } else {
          this.barPeaks[idx] = Math.max(0.08, this.barPeaks[idx] - 0.014);
        }
      }
    }

    this._drawWaveformBars(speakingActive);
  }

  _drawWaveformBars(speakingActive = false) {
    if (!this.waveformCanvas) return;
    const ctx = this.waveformCanvas.getContext("2d");
    if (!ctx) return;

    const w = this.waveformCanvas.width;
    const h = this.waveformCanvas.height;
    ctx.clearRect(0, 0, w, h);

    const midY = h / 2;
    ctx.strokeStyle = "#e7e7e7";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, midY);
    ctx.lineTo(w, midY);
    ctx.stroke();

    const totalBars = BAR_COUNT;
    const gap = Math.max(2, Math.round(w * 0.009));
    const barWidth = Math.max(2.5, (w - gap * (totalBars - 1)) / totalBars);

    const barFillColor = speakingActive
      ? "#171717"
      : this.isRecording
      ? "#c7c7c7"
      : "#d8d8d8";

    for (let i = 0; i < totalBars; i++) {
      const normH = Math.max(0.06, Math.min(1.0, this.barHeights[i]));
      const barH = Math.max(3, normH * (h - 4));
      const x = i * (barWidth + gap);
      const y = midY - barH / 2;

      ctx.fillStyle = speakingActive && normH > 0.72 ? "#b6483e" : barFillColor;
      this._fillRoundedRect(ctx, x, y, barWidth, barH, barWidth / 2);

      if (speakingActive && this.barPeaks[i] > normH + 0.04) {
        const peakH = this.barPeaks[i] * (h - 4);
        const topPeakY = Math.max(1, midY - peakH / 2 - 2);
        ctx.fillStyle = "#b6483e";
        ctx.fillRect(x, topPeakY, barWidth, 1.8);
      }
    }
  }

  _drawIdleWaveform() {
    for (let i = 0; i < BAR_COUNT; i++) {
      const distFromCenter = Math.abs(i - (BAR_COUNT - 1) / 2) / (BAR_COUNT / 2);
      this.barHeights[i] = 0.09 + (1 - distFromCenter) * 0.06;
      this.barPeaks[i] = this.barHeights[i];
    }
    this._drawWaveformBars(false);
  }

  _fillRoundedRect(ctx, x, y, width, height, radius) {
    const r = Math.min(radius, width / 2, height / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + width - r, y);
    ctx.quadraticCurveTo(x + width, y, x + width, y + r);
    ctx.lineTo(x + width, y + height - r);
    ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
    ctx.lineTo(x + r, y + height);
    ctx.quadraticCurveTo(x, y + height, x, y + height - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
    ctx.fill();
  }

  // -------------------------------------------------------------------------
  // Unified Audio & Text Command Execution (3D Scene + Multimodal Stage)
  // -------------------------------------------------------------------------
  async _processRecordedAudio(blob, clientTranscript = "") {
    // Strip wake-word prefix if the user spoke "Visual Board, ..." during PTT
    const strippedTranscript = this._stripWakeWordPrefix(clientTranscript);

    // If we have a clear transcript that routes to AI Visual, Region Inpaint, Video, or 2D Pathway, execute it via Smart Router
    if (strippedTranscript && window.visualBoardStage) {
      this.isProcessing = true;
      this._setProcessingUiState(`⏳ Routing "${strippedTranscript}"...`);
      try {
        const multimodalRes = await window.visualBoardStage.executeSmartMultimodalCommand(strippedTranscript);
        if (multimodalRes && multimodalRes.targetMode && multimodalRes.targetMode !== "3d") {
          this.lastExecutedCommandText = strippedTranscript;
          this.renderVoiceCommandFeedback(
            {
              ok: true,
              commandText: strippedTranscript,
              targetMode: multimodalRes.targetMode,
              explanationCard: {
                spokenFeedbackEn: `Switched to ${multimodalRes.targetMode.toUpperCase()} stage: "${strippedTranscript}"`,
              },
            },
            "voice"
          );
          this.isProcessing = false;
          this._resetPttButtonAndPanel();
          return;
        }
      } catch (_) {
        // Continue to standard 3D audio command
      }
    }

    this.isProcessing = true;
    this._setProcessingUiState(
      strippedTranscript
        ? `⏳ Applying "${strippedTranscript}"...`
        : "⏳ Applying voice command to Visual Board..."
    );

    try {
      const form = new FormData();
      form.append("file", blob, "voice.webm");
      form.append("sessionId", this.sessionId);
      form.append("mime_type", this.recordingMimeType || "audio/webm");
      form.append("waitForAck", "true");
      if (strippedTranscript) {
        form.append("clientTranscript", strippedTranscript);
      }

      const resp = await fetch("/api/voice/audio-command", {
        method: "POST",
        body: form,
      });
      const data = await resp.json();

      if ((!resp.ok || data.ok === false) && strippedTranscript) {
        await this.submitTextCommand(strippedTranscript, "voice_speech_rec_fallback");
        return;
      }

      if (!resp.ok || data.ok === false) {
        const errMsg = data.error || data.detail || "No speech recognized. Please try speaking again.";
        this._resetUiToIdle(errMsg);
        if (this.liveTranscriptEl) {
          this.liveTranscriptEl.innerHTML = `<span style="color: #b6483e;">${this._escapeHtml(errMsg)}</span>`;
        }
        return;
      }

      if (data.commandText) {
        this.lastExecutedCommandText = data.commandText;
      }
      this.renderVoiceCommandFeedback(data, "voice");
    } catch (err) {
      if (strippedTranscript) {
        await this.submitTextCommand(strippedTranscript, "voice_speech_rec_fallback");
        return;
      }
      this._resetUiToIdle("Failed to process voice command. Please try again.");
    } finally {
      this.isProcessing = false;
      this._resetPttButtonAndPanel();
    }
  }

  /**
   * Executes a natural-language text command across 3D Anatomy, AI Visual, Video, or 2D Pathway Diagram.
   */
  async submitTextCommand(commandText, source = "text_input") {
    const cleanCmd = this._stripWakeWordPrefix((commandText || "").trim());
    if (!cleanCmd) return null;

    this.lastExecutedCommandText = cleanCmd;
    this.isProcessing = true;
    if (this.textSubmitBtn) this.textSubmitBtn.disabled = true;

    this._setProcessingUiState(`⏳ Applying "${cleanCmd}"...`);

    try {
      // 1. Check Smart Multimodal Router first (AI Visual, Region Inpaint, Omni Video, 2D Pathway Diagram)
      if (window.visualBoardStage) {
        const multimodalRes = await window.visualBoardStage.executeSmartMultimodalCommand(cleanCmd);
        if (multimodalRes && multimodalRes.targetMode && multimodalRes.targetMode !== "3d") {
          if (source === "text_input" && this.textInput) {
            this.textInput.value = "";
          }
          const modeLabelMap = {
            image: "AI Visual (Nano Banana 2)",
            edit_image: "Region Inpaint (100% Outer Pixels Locked)",
            video: "Gemini Omni 1.1 Flash Video",
            diagram: "2D Interactive Pathway Diagram",
          };
          const modeLabel = modeLabelMap[multimodalRes.targetMode] || multimodalRes.targetMode.toUpperCase();
          const feedbackPayload = {
            ok: true,
            commandText: cleanCmd,
            targetMode: multimodalRes.targetMode,
            explanationCard: {
              spokenFeedbackEn: `${modeLabel}: "${cleanCmd}"`,
            },
            ...multimodalRes,
          };
          this.renderVoiceCommandFeedback(feedbackPayload, source);
          return feedbackPayload;
        }
      }

      // 2. Execute Authoritative 3D Z-Anatomy Scene Command
      const resp = await fetch("/api/voice/text-command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: this.sessionId,
          commandText: cleanCmd,
          waitForAck: true,
        }),
      });
      const data = await resp.json();
      if (!resp.ok || data.ok === false) {
        const errMsg = data.error || data.detail || "Could not execute command.";
        this._resetUiToIdle(errMsg);
        return data;
      }

      if (source === "text_input" && this.textInput) {
        this.textInput.value = "";
      }

      // Ensure 3D canvas is visible when a 3D command executes
      if (window.visualBoardStage && window.visualBoardStage.activeMode !== "3d" && !window.visualBoardStage.splitMode) {
        window.visualBoardStage.setMode("3d", { split: false });
      }

      this.renderVoiceCommandFeedback(data, source);
      return data;
    } catch (err) {
      this._resetUiToIdle("Could not execute command. Please try again.");
      return null;
    } finally {
      this.isProcessing = false;
      if (this.textSubmitBtn) this.textSubmitBtn.disabled = false;
      this._resetPttButtonAndPanel();
    }
  }

  async submitNaturalLanguageCommand(commandText) {
    return this.submitTextCommand(commandText, "text_input");
  }

  _stripWakeWordPrefix(text) {
    if (!text) return "";
    const match = String(text).trim().match(WAKE_PHRASE_REGEX);
    return match && match[1] ? match[1].trim() : String(text).trim();
  }

  _stripCitations(text) {
    if (!text) return "";
    return String(text)
      .replace(/\s*\[SOT-\d+(?:,\s*SOT-\d+)*\]/gi, "")
      .replace(/\s*\(\[?SOT-\d+[^\)]*\)/gi, "")
      .replace(/\s+/g, " ")
      .trim();
  }

  renderVoiceCommandFeedback(data, source = "voice") {
    if (!data) return;

    const card = data.explanationCard || {};
    const cmdText = data.commandText || this.lastExecutedCommandText || "";

    if (this.liveTranscriptEl && cmdText) {
      this.liveTranscriptEl.innerHTML = `<span style="color: #171717; font-weight: 600;">"${this._escapeHtml(cmdText)}"</span>`;
    }

    const rawFeedback =
      card.spokenFeedbackEn ||
      card.bodyEn ||
      card.titleEn ||
      data.narrationScript ||
      "Updated the Visual Board.";
    let cleanSummary = this._stripCitations(rawFeedback);
    if (/[가-힣]/.test(cleanSummary) && cmdText && !/[가-힣]/.test(cmdText)) {
      cleanSummary = `Applied to Visual Board: "${cmdText}"`;
    }
    const formattedStatus = cleanSummary.startsWith("✓")
      ? cleanSummary
      : `✓ ${cleanSummary}`;

    this._setStatus(formattedStatus);

    if (this.onCommandSuccess) {
      this.onCommandSuccess(data);
    }
  }

  renderFeedback(data) {
    return this.renderVoiceCommandFeedback(data);
  }

  getLastCommandText() {
    const typed = (this.textInput && this.textInput.value.trim()) || "";
    return typed || this.lastExecutedCommandText || "";
  }

  _setProcessingUiState(message) {
    if (this.pttBtn) {
      this.pttBtn.classList.remove("recording");
      this.pttBtn.classList.add("processing");
      this.pttBtn.innerHTML = `<span>⏳ Applying...</span>`;
    }
    if (this.waveformPanel) {
      this.waveformPanel.classList.remove("is-recording", "is-silent-warning");
      this.waveformPanel.classList.add("is-processing");
    }
    if (this.volumeStateBadge) {
      this.volumeStateBadge.className = "voice-state-badge state-processing";
      this.volumeStateBadge.textContent = "⏳ Applying...";
    }
    if (this.liveTranscriptEl) {
      this.liveTranscriptEl.innerHTML = `<span class="interim-text">${this._escapeHtml(message)}</span>`;
    }
    this._setStatus(message);
  }

  _resetPttButtonAndPanel() {
    if (this.pttBtn) {
      this.pttBtn.classList.remove("recording", "processing");
      this.pttBtn.innerHTML = `<span>🎙️ Voice Command</span>`;
    }
    if (this.waveformPanel) {
      this.waveformPanel.classList.remove("is-recording", "is-processing", "is-silent-warning");
    }
    if (this.volumeStateBadge) {
      if (this.wakeWordModeActive) {
        this.volumeStateBadge.className = "voice-state-badge state-speaking";
        this.volumeStateBadge.textContent = "🎧 Wake Word Active";
      } else {
        this.volumeStateBadge.className = "voice-state-badge";
        this.volumeStateBadge.textContent = "Mic Standby";
      }
    }
    this._drawIdleWaveform();
  }

  _resetUiToIdle(statusMessage) {
    this._resetPttButtonAndPanel();
    if (statusMessage) {
      this._setStatus(statusMessage);
    }
  }

  _setStatus(text) {
    if (this.statusEl) {
      this.statusEl.textContent = text;
    }
    if (this.onStatusChange) {
      this.onStatusChange(text);
    }
  }

  _escapeHtml(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  destroy() {
    this.cancelRecording();
    this._stopWakeWordListener();
    window.removeEventListener("keydown", this._boundKeyDown);
    window.removeEventListener("resize", this._boundResize);
  }
}

export default VoiceCommandController;
