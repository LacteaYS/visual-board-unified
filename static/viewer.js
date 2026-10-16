/**
 * CliniView Live — Authoritative Three.js 3D Shoulder Anatomy Viewer & MCP/Voice Sync Client
 *
 * Features:
 * - Loads Z-Anatomy extracted `shoulder.glb` (91 structures) + `structures-manifest.json`
 * - Handles mirrored `.l` negative-scale meshes cleanly via `THREE.DoubleSide` & normal recomputation
 * - Prevents transparency depth-sorting artifacts (`depthWrite = opacity >= 0.85`, `renderOrder` separation,
 *   and `THREE.EdgesGeometry` highlight silhouettes for deep target muscles like `subscapularis_r`)
 * - Bidirectional WebSocket sync (`/ws/scene/default`) with real Viewer ACK (`type: "ack"`) and
 *   live WebGL canvas screenshot capture (`type: "capture_response"`)
 * - Preserves mouse OrbitControls camera state across patches unless camera change is explicitly requested
 */

import * as THREE from "./vendor/three/three.module.js";
import { OrbitControls } from "./vendor/three/OrbitControls.js";
import { GLTFLoader } from "./vendor/three/GLTFLoader.js";
import { VoiceCommandController } from "./voice-ui.js";

const SESSION_ID = "default";

// Category base colors (whole-body anatomical palette)
const CATEGORY_COLORS = {
  // Skeletal muscles across all regions
  rotator_cuff: 0xd9534f,        // Rich deep muscle crimson
  trapezius: 0xc96557,           // Superficial muscle terracotta
  deltoid: 0xcc5c52,             // Deltoid warm muscle red
  pectoralis: 0xc75b50,          // Pectoral muscle red
  scapular_stabilizer: 0xbf564c, // Scapular muscle red
  upper_arm: 0xc45d52,           // Upper arm muscle red
  forearm_muscle: 0xc85a4e,      // Forearm muscle red
  head_neck_muscle: 0xcf5d53,    // Head/neck muscle red
  abdomen_muscle: 0xc85a4e,      // Abdominal muscle terracotta
  back_muscle: 0xc5584d,         // Back muscle terracotta
  gluteal_muscle: 0xc95b4f,      // Gluteal muscle red
  thigh_muscle: 0xcc5c50,        // Thigh muscle red
  leg_muscle: 0xc85a4e,          // Lower leg muscle red
  muscle: 0xc85a4e,              // General skeletal muscle red

  // Bones across all regions
  bone: 0xefe7d6,                // Warm anatomical ivory bone
  skull_bone: 0xefe7d6,          // Cranium/facial bone ivory
  thorax_bone: 0xe7dfd0,         // Rib/sternum ivory
  spine_bone: 0xe7dfd0,          // Vertebrae ivory
  pelvis_bone: 0xefe7d6,         // Pelvis/sacrum ivory
  upper_limb_bone: 0xefe7d6,     // Upper limb bone ivory
  lower_limb_bone: 0xefe7d6,     // Lower limb bone ivory

  // Brain & Nervous system
  brain: 0xf5b792,               // Soft warm beige-pink brain tissue
  nervous: 0xfacc15,             // Bright anatomical nerve yellow
  neurovascular_nerve: 0xfacc15, // Nerve bright yellow

  // Cardiovascular (Heart, Arteries, Veins)
  heart: 0xdc2626,               // Rich crimson red
  cardiovascular: 0xdc2626,      // Arterial/cardiac crimson red
  neurovascular_artery: 0xdc2626,// Artery bright red
  vein: 0x3b82f6,                // Anatomical venous blue
  neurovascular_vein: 0x3b82f6,  // Venous blue

  // Lungs & Respiratory
  lung: 0xf472b6,                // Soft rose-coral lung
  respiratory: 0xf472b6,         // Respiratory soft rose-coral

  // Digestive, Hepatic, Urinary & Visceral Organs
  liver: 0x9a3412,               // Deep hepatic reddish-brown
  gallbladder: 0x16a34a,         // Bile green
  visceral_organ: 0xea580c,      // Warm organ coral
  digestive: 0xea580c,           // Warm digestive coral
  stomach: 0xea580c,             // Stomach coral-orange
  esophagus: 0xea580c,           // Esophagus coral-orange
  pancreas: 0xf59e0b,            // Pancreas warm ochre/amber
  spleen: 0x991b1b,              // Spleen deep maroon-red
  intestine: 0xd97706,           // Intestine warm ochre
  colon: 0xd97706,               // Colon warm ochre
  duodenum: 0xd97706,            // Duodenum warm ochre
  jejunum: 0xd97706,             // Jejunum warm ochre
  ileum: 0xd97706,               // Ileum warm ochre
  cecum: 0xd97706,               // Cecum warm ochre
  rectum: 0xd97706,              // Rectum warm ochre
  kidney: 0xb91c1c,              // Renal reddish-brown
  urinary: 0xfbbf24,             // Urinary amber-yellow
  bladder: 0xfbbf24,             // Urinary bladder amber-yellow

  // Landmarks, footprints, bursae
  insertion_footprint: 0xf59e0b, // Origin/insertion footprint amber
  joint_bursa: 0x38bdf8,         // Bursa/capsule translucent sky blue
};

const BONE_CATEGORIES = new Set([
  "bone",
  "skull_bone",
  "thorax_bone",
  "spine_bone",
  "pelvis_bone",
  "upper_limb_bone",
  "lower_limb_bone",
]);

class ShoulderAnatomyViewer {
  constructor() {
    this.manifest = null;
    this.structuresById = new Map();
    this.landmarksById = new Map();
    this.meshNodesById = new Map(); // id -> { rootObj, meshes: [], outlineGroup, baseColorHex, worldBox }
    this.currentState = null;
    this.revision = 1;
    this.ws = null;
    this.wsConnected = false;

    // Three.js core objects
    this.container = document.getElementById("three-canvas-container");
    this.overlayContainer = document.getElementById("landmark-overlay-container");
    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.gridHelper = null;
    this.cameraAnim = null;
    this.raycaster = new THREE.Raycaster();
    this.pointer = new THREE.Vector2();
    this.pointerDownPos = { x: 0, y: 0 };

    // 3D Landmark pins & Procedure guide vectors group
    this.landmark3DGroup = new THREE.Group();
    this.procedure3DGroup = new THREE.Group();
    this.landmarkDomElements = new Map();

    // UI filter states
    this.activeSideFilter = "right"; // "right" | "left" | "all"
    this.searchQuery = "";
    this.procedurePlayTimer = null;
    this.selectedStructureId = "subscapularis_r";
    this.cameraAnim = null;

    // Voice & Waveform Controller
    this.voiceController = null;
  }

  isBoneStructure(meta) {
    if (!meta) return false;
    return (
      BONE_CATEGORIES.has(meta.category) ||
      BONE_CATEGORIES.has(meta.group) ||
      meta.system === "skeletal"
    );
  }

  stripCitations(text) {
    if (!text) return "";
    return String(text)
      .replace(/\s*\[SOT-\d+(?:,\s*SOT-\d+)*\]/gi, "")
      .replace(/\s*\(\[?SOT-\d+[^\)]*\)/gi, "")
      .trim();
  }

  async init() {
    this.setLoadingStatus("Loading 3D Human Anatomy Manifest...");
    const manifestResp = await fetch("/api/manifest");
    this.manifest = await manifestResp.json();

    for (const s of this.manifest.structures || []) {
      this.structuresById.set(s.id, s);
    }
    for (const lm of this.manifest.landmarks || []) {
      this.landmarksById.set(lm.id, lm);
    }

    if (this.structuresById.has("heart")) {
      this.selectedStructureId = "heart";
    } else if (this.structuresById.has("subscapularis_r")) {
      this.selectedStructureId = "subscapularis_r";
    } else if (this.manifest.structures && this.manifest.structures.length > 0) {
      this.selectedStructureId = this.manifest.structures[0].id;
    }

    this.initThreeScene();
    await this.loadShoulderGlb();
    this.buildLandmarkMarkers();
    this.bindUiEvents();
    this.connectWebSocket();
    this.animate();
  }

  setLoadingStatus(msg, hide = false) {
    const el = document.getElementById("viewer-loading-badge");
    if (!el) return;
    el.textContent = msg;
    el.style.display = hide ? "none" : "inline-flex";
  }

  computeManifestMinY() {
    let minY = Infinity;
    for (const s of (this.manifest && this.manifest.structures) || []) {
      const bMin = s.boundsMin || s.minBounds || (s.bbox && s.bbox.min);
      if (Array.isArray(bMin) && bMin.length >= 2 && Number.isFinite(Number(bMin[1]))) {
        minY = Math.min(minY, Number(bMin[1]));
      }
    }
    return Number.isFinite(minY) ? minY : 0.0;
  }

  initThreeScene() {
    const width = this.container.clientWidth || 900;
    const height = this.container.clientHeight || 640;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xf3f4f6);

    this.camera = new THREE.PerspectiveCamera(36, width / height, 0.01, 25.0);
    this.camera.position.set(0.0, 0.92, 2.35);

    // preserveDrawingBuffer: true is required for deterministic `scene.capture` screenshots!
    this.renderer = new THREE.WebGLRenderer({
      antialias: true,
      preserveDrawingBuffer: true,
      powerPreference: "high-performance",
    });
    this.renderer.setSize(width, height);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.container.appendChild(this.renderer.domElement);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.target.set(0.0, 0.90, 0.0);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.minDistance = 0.08;
    this.controls.maxDistance = 4.5;
    this.controls.update();

    // Notify authoritative Scene Service whenever user finishes moving camera with mouse
    this.controls.addEventListener("end", () => {
      this.sendCameraUpdateToServer();
      this.updateCameraHud();
    });
    this.controls.addEventListener("change", () => {
      this.updateCameraHud();
    });

    // Studio Clinical Lighting (3-point + hemisphere so whole-body & deep organs are well lit)
    const hemiLight = new THREE.HemisphereLight(0xffffff, 0xcbd5e1, 1.2);
    hemiLight.position.set(0, 2.2, 0);
    this.scene.add(hemiLight);

    const keyLight = new THREE.DirectionalLight(0xffffff, 1.35);
    keyLight.position.set(-0.6, 1.9, 0.8);
    this.scene.add(keyLight);

    const fillLight = new THREE.DirectionalLight(0xe2e8f0, 0.85);
    fillLight.position.set(0.7, 1.4, 0.6);
    this.scene.add(fillLight);

    const backLight = new THREE.DirectionalLight(0xfef3c7, 0.75);
    backLight.position.set(0.0, 1.6, -0.9);
    this.scene.add(backLight);

    // Subtle reference grid at the lowest structure bound (minY from manifest, or 0.0)
    const minY = this.computeManifestMinY();
    this.gridHelper = new THREE.GridHelper(2.0, 20, 0xd4d8e0, 0xe4e7ed);
    this.gridHelper.position.set(0, minY, 0);
    this.scene.add(this.gridHelper);

    this.scene.add(this.landmark3DGroup);
    this.scene.add(this.procedure3DGroup);

    window.addEventListener("resize", () => this.onWindowResize());
  }

  onWindowResize() {
    if (!this.container || !this.renderer || !this.camera) return;
    const w = this.container.clientWidth || 800;
    const h = this.container.clientHeight || 600;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h);
  }

  getBaseColorForStructure(meta) {
    if (!meta) return 0xc85a4e;
    const id = String(meta.id || "").toLowerCase();
    const cat = String(meta.category || "").toLowerCase();
    const grp = String(meta.group || "").toLowerCase();

    // 1. Bones across all regions
    if (this.isBoneStructure(meta)) {
      if (cat === "thorax_bone" || cat === "spine_bone") return 0xe7dfd0;
      return 0xefe7d6;
    }

    // 2. Brain & Nervous system
    if (
      cat === "brain" ||
      id.includes("cerebr") ||
      id.includes("brain") ||
      id.includes("thalam") ||
      id.includes("pons") ||
      id.includes("medulla") ||
      id.includes("putamen") ||
      id.includes("caudate") ||
      id.includes("hippocamp") ||
      id.includes("corpus_callosum")
    ) {
      return 0xf5b792;
    }
    if (
      cat === "nervous" ||
      cat === "neurovascular_nerve" ||
      id.includes("nerve") ||
      id.includes("spinal_cord") ||
      id.includes("plexus") ||
      id.includes("ganglion") ||
      id.includes("trunk")
    ) {
      return 0xfacc15;
    }

    // 3. Veins vs Heart & Arteries
    if (
      cat === "vein" ||
      cat === "neurovascular_vein" ||
      id.includes("vein") ||
      id.includes("vena_cava") ||
      id.includes("jugular")
    ) {
      return 0x3b82f6;
    }
    if (
      cat === "heart" ||
      cat === "cardiovascular" ||
      cat === "neurovascular_artery" ||
      id.includes("heart") ||
      id.includes("ventricle") ||
      id.includes("atrium") ||
      id.includes("myocard") ||
      id.includes("aorta") ||
      id.includes("artery") ||
      id.includes("carotid")
    ) {
      return 0xdc2626;
    }
    if (cat === "neurovascular") {
      return id.includes("artery") || id.includes("aorta")
        ? CATEGORY_COLORS.neurovascular_artery
        : CATEGORY_COLORS.neurovascular_nerve;
    }

    // 4. Lungs & Respiratory
    if (id.includes("trachea") || id.includes("bronch") || id.includes("laryn") || id.includes("thyroid_cartilage")) {
      return 0x93c5fd;
    }
    if (cat === "lung" || cat === "respiratory" || id.includes("lung")) {
      return 0xf472b6;
    }

    // 5. Liver & Gallbladder
    if (id.includes("gallbladder")) {
      return 0x16a34a;
    }
    if (id.includes("liver") || cat === "liver") {
      return 0x9a3412;
    }

    // 6. Stomach, Pancreas, Spleen, Intestines/Colon, Kidneys & Bladder
    if (id.includes("stomach") || id.includes("esophagus") || cat === "stomach" || cat === "esophagus") {
      return 0xea580c;
    }
    if (id.includes("pancreas") || cat === "pancreas") {
      return 0xf59e0b;
    }
    if (id.includes("spleen") || cat === "spleen") {
      return 0x991b1b;
    }
    if (id.includes("kidney") || id.includes("renal") || cat === "kidney") {
      return 0xb91c1c;
    }
    if (id.includes("bladder") || id.includes("ureter") || cat === "bladder" || cat === "urinary") {
      return 0xfbbf24;
    }
    if (
      id.includes("intestine") ||
      id.includes("colon") ||
      id.includes("duodenum") ||
      id.includes("jejunum") ||
      id.includes("ileum") ||
      id.includes("cecum") ||
      id.includes("rectum") ||
      id.includes("appendix")
    ) {
      return 0xd97706;
    }
    if (cat === "visceral_organ" || cat === "digestive") {
      return 0xea580c;
    }

    // 7. Skeletal muscles & remaining categories
    return CATEGORY_COLORS[cat] || CATEGORY_COLORS[grp] || 0xc85a4e;
  }

  async loadShoulderGlb() {
    this.setLoadingStatus("전신 3D 해부학 모델(whole_body.glb) 로딩 중...");
    const loader = new GLTFLoader();
    const loadUrl = (url) =>
      new Promise((resolve, reject) => {
        loader.load(
          url,
          (g) => resolve(g),
          undefined,
          (err) => reject(err)
        );
      });

    let gltf = null;
    try {
      gltf = await loadUrl("/static/assets/whole_body.glb");
    } catch (_) {
      this.setLoadingStatus("shoulder.glb 로딩 중...");
      gltf = await loadUrl("/static/assets/shoulder.glb");
    }

    const root = gltf.scene;
    this.scene.add(root);
    root.updateMatrixWorld(true);

    let sceneMinY = Infinity;

    // Index all structure nodes
    root.traverse((obj) => {
      const sid =
        (obj.userData && obj.userData.structure_id) ||
        (this.structuresById.has(obj.name) ? obj.name : null);

      if (sid && this.structuresById.has(sid) && !this.meshNodesById.has(sid)) {
        const meta = this.structuresById.get(sid);
        const baseColorHex = this.getBaseColorForStructure(meta);
        const meshes = [];
        const outlineGroup = new THREE.Group();
        outlineGroup.visible = false;

        obj.traverse((child) => {
          if (child.isMesh) {
            if (child.geometry) {
              child.geometry.computeVertexNormals();
            }
            const isBone = this.isBoneStructure(meta);
            const isVesselOrNerve =
              meta.category === "neurovascular" ||
              meta.category === "nervous" ||
              meta.category === "cardiovascular" ||
              meta.category === "heart" ||
              meta.category === "vein" ||
              meta.category === "neurovascular_artery" ||
              meta.category === "neurovascular_nerve" ||
              meta.category === "neurovascular_vein";

            const mat = new THREE.MeshStandardMaterial({
              color: new THREE.Color(baseColorHex),
              roughness: isBone ? 0.55 : isVesselOrNerve ? 0.32 : 0.44,
              metalness: isVesselOrNerve ? 0.15 : 0.04,
              // CRITICAL: Z-Anatomy `.l` meshes use negative scale [-1,-1,-1] sharing `.r` geometry.
              // DoubleSide prevents inside-out culling on mirrored meshes and improves semi-transparent layering.
              side: THREE.DoubleSide,
              transparent: false,
              opacity: 1.0,
              depthWrite: true,
            });

            child.material = mat;
            child.userData.structureId = sid;
            meshes.push(child);

            // Create clean edge silhouette lines for target highlight mode
            if (child.geometry) {
              try {
                const edgesGeo = new THREE.EdgesGeometry(child.geometry, 28);
                const edgesMat = new THREE.LineBasicMaterial({
                  color: 0x38bdf8,
                  transparent: true,
                  opacity: 0.9,
                  depthTest: false, // Allows highlighted deep target outline to remain visible through semi-transparent muscles
                });
                const lineSeg = new THREE.LineSegments(edgesGeo, edgesMat);
                lineSeg.renderOrder = 999;
                child.add(lineSeg);
                child.userData.outlineLine = lineSeg;
                lineSeg.visible = false;
              } catch (_) {
                // Ignore edge generation errors on very dense/non-manifold meshes
              }
            }
          }
        });

        const worldBox = new THREE.Box3().setFromObject(obj);
        if (!worldBox.isEmpty() && Number.isFinite(worldBox.min.y)) {
          sceneMinY = Math.min(sceneMinY, worldBox.min.y);
        }

        this.meshNodesById.set(sid, {
          id: sid,
          meta,
          rootObj: obj,
          meshes,
          baseColorHex,
          worldBox,
        });
      }
    });

    if (this.gridHelper) {
      const manifestMinY = this.computeManifestMinY();
      const finalMinY =
        manifestMinY !== 0.0
          ? manifestMinY
          : Number.isFinite(sceneMinY)
          ? sceneMinY
          : 0.0;
      this.gridHelper.position.y = finalMinY;
    }

    this.setLoadingStatus(`Z-Anatomy 3D 로드 완료 (${this.meshNodesById.size}개 구조물)`, true);
    this.renderStructureListUi();
  }

  /**
   * Applies visibility, opacity, highlight color, depthWrite, and edge outline to a single structure.
   */
  applyStructureVisualState(sid, st) {
    const entry = this.meshNodesById.get(sid);
    if (!entry) return;

    const visible = st.visible !== undefined ? Boolean(st.visible) : true;
    const opacity = st.opacity !== undefined ? Math.max(0.0, Math.min(1.0, Number(st.opacity))) : 1.0;
    const highlighted = Boolean(st.highlighted);
    const showOutline = Boolean(st.outline || highlighted);
    const customColor = st.colorHex || (highlighted ? "#ef4444" : null);

    entry.rootObj.visible = visible && opacity > 0.005;

    for (const mesh of entry.meshes) {
      const mat = mesh.material;
      if (!mat) continue;

      if (customColor) {
        mat.color.set(customColor);
        mat.emissive.set(highlighted ? customColor : "#000000");
        mat.emissiveIntensity = highlighted ? 0.28 : 0.0;
      } else {
        mat.color.setHex(entry.baseColorHex);
        mat.emissive.setHex(0x000000);
        mat.emissiveIntensity = 0.0;
      }

      const isTranslucent = opacity < 0.98;
      mat.transparent = isTranslucent;
      mat.opacity = opacity;
      // Key anti-artifact rule from ANTIGRAVITY_HANDOFF.md:
      // Disable depthWrite on semi-transparent overlying muscles (< 0.85) so deep opaque target muscles render cleanly!
      mat.depthWrite = opacity >= 0.85;
      mat.needsUpdate = true;

      if (highlighted) {
        mesh.renderOrder = 10;
      } else if (isTranslucent) {
        mesh.renderOrder = 25;
      } else {
        mesh.renderOrder = 5;
      }

      if (mesh.userData.outlineLine) {
        mesh.userData.outlineLine.visible = visible && showOutline;
        if (highlighted) {
          mesh.userData.outlineLine.material.color.set(customColor === "#ef4444" ? "#fde047" : "#38bdf8");
        }
      }
    }
  }

  /**
   * Builds 3D sphere markers + HTML floating badges for grounded surface landmarks & acupoints (SI11, LI15, TrP, Hazard).
   */
  buildLandmarkMarkers() {
    this.landmark3DGroup.clear();
    if (this.overlayContainer) {
      this.overlayContainer.innerHTML = "";
    }
    this.landmarkDomElements.clear();

    const COLOR_BY_TYPE = {
      anatomical_origin: 0xf59e0b,
      anatomical_insertion: 0x06b6d4,
      clinical_target: 0x10b981,
      acupoint: 0x3b82f6,
      safety_hazard: 0xef4444,
    };

    for (const [lid, lm] of this.landmarksById.entries()) {
      const pos = lm.positionThreeJs;
      if (!pos || pos.length !== 3) continue;

      const colorHex = COLOR_BY_TYPE[lm.landmarkType] || 0x38bdf8;
      const radius = lm.landmarkType === "safety_hazard" ? 0.0065 : 0.0048;

      const geo = new THREE.SphereGeometry(radius, 20, 20);
      const mat = new THREE.MeshBasicMaterial({
        color: colorHex,
        depthTest: false,
        transparent: true,
        opacity: 0.95,
      });
      const sphere = new THREE.Mesh(geo, mat);
      sphere.position.set(pos[0], pos[1], pos[2]);
      sphere.renderOrder = 1000;
      sphere.userData.landmarkId = lid;
      this.landmark3DGroup.add(sphere);

      // Create floating HTML badge
      if (this.overlayContainer) {
        const badge = document.createElement("button");
        badge.className = `landmark-pin landmark-type-${lm.landmarkType}`;
        badge.dataset.landmarkId = lid;
        badge.innerHTML = `<span class="pin-dot"></span><span class="pin-text">${lm.nameKo.replace(/^(우측|좌측)\s*/, "")}</span>`;
        badge.title = `${lm.nameKo}\n${this.stripCitations(lm.descriptionKo)}`;
        badge.addEventListener("click", (e) => {
          e.stopPropagation();
          this.showLandmarkDetailCard(lm);
        });
        this.overlayContainer.appendChild(badge);
        this.landmarkDomElements.set(lid, { lm, sphere, badge });
      }
    }
  }

  /**
   * Renders 3D educational guide vectors and hazard zones for the active procedure template.
   */
  updateProcedure3DVectors(activeProcedure) {
    this.procedure3DGroup.clear();
    if (!activeProcedure || !Array.isArray(activeProcedure.guideVectors)) return;

    const progress =
      activeProcedure.progress !== undefined ? Number(activeProcedure.progress) : 1.0;

    for (const vec of activeProcedure.guideVectors) {
      if (vec.type === "hazard_zone" && vec.centerPositionThreeJs) {
        const c = vec.centerPositionThreeJs;
        const r = vec.radiusMeters || 0.02;
        const geo = new THREE.SphereGeometry(r, 24, 24);
        const mat = new THREE.MeshBasicMaterial({
          color: vec.colorHex || "#ef4444",
          transparent: true,
          opacity: 0.24,
          depthWrite: false,
          side: THREE.DoubleSide,
        });
        const hazardMesh = new THREE.Mesh(geo, mat);
        hazardMesh.position.set(c[0], c[1], c[2]);
        hazardMesh.renderOrder = 900;
        this.procedure3DGroup.add(hazardMesh);
      } else if (vec.entryPositionThreeJs && vec.targetPositionThreeJs) {
        const start = new THREE.Vector3(...vec.entryPositionThreeJs);
        const end = new THREE.Vector3(...vec.targetPositionThreeJs);
        const fullDir = new THREE.Vector3().subVectors(end, start);
        const totalLen = fullDir.length();
        if (totalLen < 1e-4) continue;

        const dirNorm = fullDir.clone().normalize();
        const activeLen = Math.max(0.015, totalLen * Math.max(0.2, progress));

        const arrow = new THREE.ArrowHelper(
          dirNorm,
          start,
          activeLen,
          new THREE.Color(vec.colorHex || "#10b981"),
          0.016,
          0.009
        );
        arrow.renderOrder = 995;
        this.procedure3DGroup.add(arrow);
      }
    }
  }

  updateLandmarkOverlayPositions() {
    if (!this.camera || !this.renderer) return;
    const showAll = this.currentState ? Boolean(this.currentState.landmarksVisible) : false;
    const activeSet = new Set(
      (this.currentState && this.currentState.activeLandmarkIds) || []
    );

    const width = this.container.clientWidth || 800;
    const height = this.container.clientHeight || 600;
    const placedBoxes = [];

    for (const [lid, item] of this.landmarkDomElements.entries()) {
      const isVisible = showAll && (activeSet.size === 0 || activeSet.has(lid));
      item.sphere.visible = isVisible;
      if (!isVisible) {
        item.badge.style.display = "none";
        continue;
      }

      const worldPos = item.sphere.position.clone();
      worldPos.project(this.camera);

      if (worldPos.z < -1 || worldPos.z > 1) {
        item.badge.style.display = "none";
        continue;
      }

      const x = (worldPos.x * 0.5 + 0.5) * width;
      let y = (-worldPos.y * 0.5 + 0.5) * height;

      // Prevent vertical badge overlap when anterior & posterior landmarks project near the same screen Y
      for (const box of placedBoxes) {
        if (Math.abs(x - box.x) < 150 && Math.abs(y - box.y) < 26) {
          y = box.y + 28;
        }
      }
      placedBoxes.push({ x, y });

      item.badge.style.display = "inline-flex";
      item.badge.style.transform = `translate(-50%, -120%) translate(${Math.round(x)}px, ${Math.round(y)}px)`;
    }
  }

  // -------------------------------------------------------------------------
  // WebSocket Sync + Real Viewer ACK + Real Canvas Screenshot Capture
  // -------------------------------------------------------------------------
  connectWebSocket() {
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${proto}//${window.location.host}/ws/scene/${SESSION_ID}`;
    this.ws = new WebSocket(wsUrl);

    this.ws.onopen = () => {
      this.wsConnected = true;
      this.updateConnectionBadge(true);
    };

    this.ws.onclose = () => {
      this.wsConnected = false;
      this.updateConnectionBadge(false);
      setTimeout(() => this.connectWebSocket(), 1500);
    };

    this.ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        this.handleServerMessage(msg);
      } catch (err) {
        console.error("Failed to parse scene WS message:", err);
      }
    };
  }

  updateConnectionBadge(connected) {
    const badge = document.getElementById("ws-status-badge");
    if (!badge) return;
    badge.textContent = connected
      ? `● Scene WS Connected (Rev #${this.revision})`
      : "○ Scene WS Reconnecting...";
    badge.className = connected ? "status-pill status-ok" : "status-pill status-warn";
  }

  handleServerMessage(msg) {
    const type = msg.type;

    if (type === "scene.init" || type === "scene.full_sync") {
      const st = msg.state;
      this.currentState = st;
      this.revision = msg.revision || st.revision || 1;

      if (msg.templates) {
        this.populateProcedureTemplatesDropdown(msg.templates);
      }

      this.applyAuthoritativeSceneState(st, {
        applyCamera: type === "scene.init" || Boolean(msg.cameraChanged),
        animateCamera: type !== "scene.init",
      });

      // Render immediately before sending ACK so the frame is guaranteed live on screen
      this.renderer.render(this.scene, this.camera);

      if (msg.commandId) {
        this.sendViewerAck(msg.commandId, this.revision);
      }
      return;
    }

    if (type === "scene.patch") {
      this.revision = msg.revision || this.revision + 1;
      if (!this.currentState) {
        this.currentState = { structures: {} };
      }
      this.currentState.revision = this.revision;

      if (msg.resetToDefault && msg.structures) {
        this.currentState.structures = msg.structures;
        for (const [sid, structState] of Object.entries(msg.structures)) {
          this.applyStructureVisualState(sid, structState);
        }
      } else if (msg.structures) {
        for (const [sid, delta] of Object.entries(msg.structures)) {
          const merged = Object.assign(
            {},
            this.currentState.structures[sid] || {},
            delta
          );
          this.currentState.structures[sid] = merged;
          this.applyStructureVisualState(sid, merged);
        }
      }

      if (msg.cameraChanged && msg.camera) {
        this.currentState.camera = msg.camera;
        this.applyCameraFromServer(msg.camera, true);
      }

      if (msg.selectedStructureIds) {
        this.currentState.selectedStructureIds = msg.selectedStructureIds;
      }
      if (msg.landmarksVisible !== undefined) {
        this.currentState.landmarksVisible = msg.landmarksVisible;
      }
      if (msg.activeLandmarkIds) {
        this.currentState.activeLandmarkIds = msg.activeLandmarkIds;
      }
      if (msg.activeProcedure !== undefined) {
        this.currentState.activeProcedure = msg.activeProcedure;
        this.updateProcedure3DVectors(msg.activeProcedure);
      }
      if (msg.explanationCard) {
        this.currentState.lastExplanationCard = msg.explanationCard;
      }

      this.syncUiFromAuthoritativeState();
      this.renderer.render(this.scene, this.camera);

      if (msg.commandId) {
        this.sendViewerAck(msg.commandId, this.revision);
      }
      return;
    }

    if (type === "procedure.update") {
      this.revision = msg.revision || this.revision + 1;
      if (this.currentState) {
        this.currentState.revision = this.revision;
        this.currentState.activeProcedure = msg.activeProcedure;
        if (msg.activeLandmarkIds) {
          this.currentState.activeLandmarkIds = msg.activeLandmarkIds;
        }
        if (msg.explanationCard) {
          this.currentState.lastExplanationCard = msg.explanationCard;
        }
      }
      this.updateProcedure3DVectors(msg.activeProcedure);
      this.syncUiFromAuthoritativeState();
      this.renderer.render(this.scene, this.camera);

      if (msg.commandId) {
        this.sendViewerAck(msg.commandId, this.revision);
      }
      return;
    }

    if (type === "scene.capture_request") {
      // If a smooth camera transition is in flight, snap immediately to its destination before capturing
      if (this.cameraAnim && this.camera && this.controls) {
        this.camera.position.copy(this.cameraAnim.endPos);
        this.controls.target.copy(this.cameraAnim.endTarget);
        this.cameraAnim = null;
        this.controls.update();
      }
      // Render a fresh frame with overlays settled, then capture real WebGL canvas PNG
      this.renderer.render(this.scene, this.camera);
      const mime = msg.format === "jpg" || msg.format === "jpeg" ? "image/jpeg" : "image/png";
      const dataUrl = this.renderer.domElement.toDataURL(mime);
      if (this.ws && this.wsConnected) {
        this.ws.send(
          JSON.stringify({
            type: "capture_response",
            sessionId: SESSION_ID,
            captureId: msg.captureId,
            revision: this.revision,
            width: this.renderer.domElement.width,
            height: this.renderer.domElement.height,
            dataUrl,
          })
        );
      }
    }
  }

  applyAuthoritativeSceneState(st, options = {}) {
    if (!st) return;
    const { applyCamera = true, animateCamera = true } = options;

    for (const [sid, structState] of Object.entries(st.structures || {})) {
      this.applyStructureVisualState(sid, structState);
    }

    if (applyCamera && st.camera) {
      this.applyCameraFromServer(st.camera, animateCamera);
    }

    this.updateProcedure3DVectors(st.activeProcedure);
    this.syncUiFromAuthoritativeState();
  }

  sendViewerAck(commandId, appliedRevision) {
    if (!this.ws || !this.wsConnected) return;
    this.ws.send(
      JSON.stringify({
        type: "ack",
        sessionId: SESSION_ID,
        commandId,
        appliedRevision,
        timestamp: Date.now(),
        errors: [],
      })
    );
    const ackBadge = document.getElementById("last-ack-badge");
    if (ackBadge) {
      ackBadge.textContent = `Viewer ACK: ${commandId} (Rev #${appliedRevision})`;
    }
  }

  sendCameraUpdateToServer() {
    if (!this.ws || !this.wsConnected || !this.camera || !this.controls) return;
    const p = this.camera.position;
    const t = this.controls.target;
    const u = this.camera.up;
    this.ws.send(
      JSON.stringify({
        type: "viewer.camera_update",
        sessionId: SESSION_ID,
        camera: {
          position: [Number(p.x.toFixed(5)), Number(p.y.toFixed(5)), Number(p.z.toFixed(5))],
          target: [Number(t.x.toFixed(5)), Number(t.y.toFixed(5)), Number(t.z.toFixed(5))],
          up: [Number(u.x.toFixed(5)), Number(u.y.toFixed(5)), Number(u.z.toFixed(5))],
        },
      })
    );
  }

  animateCameraTo(posArr, targetArr, durationMs = 550, onComplete = null) {
    if (!this.camera || !this.controls) return;
    const endPos =
      Array.isArray(posArr) && posArr.length === 3
        ? new THREE.Vector3(posArr[0], posArr[1], posArr[2])
        : this.camera.position.clone();
    const endTarget =
      Array.isArray(targetArr) && targetArr.length === 3
        ? new THREE.Vector3(targetArr[0], targetArr[1], targetArr[2])
        : this.controls.target.clone();

    if (durationMs <= 0) {
      this.cameraAnim = null;
      this.camera.position.copy(endPos);
      this.controls.target.copy(endTarget);
      this.controls.update();
      this.updateCameraHud();
      if (typeof onComplete === "function") onComplete();
      return;
    }

    this.cameraAnim = {
      startPos: this.camera.position.clone(),
      endPos,
      startTarget: this.controls.target.clone(),
      endTarget,
      startTime: performance.now(),
      durationMs,
      onComplete,
    };
  }

  applyCameraFromServer(cam, animate = true) {
    if (!cam || !this.camera || !this.controls) return;
    if (Array.isArray(cam.up) && cam.up.length === 3) {
      this.camera.up.set(cam.up[0], cam.up[1], cam.up[2]);
    }
    const hasPos = Array.isArray(cam.position) && cam.position.length === 3;
    const hasTarget = Array.isArray(cam.target) && cam.target.length === 3;
    if (animate && (hasPos || hasTarget)) {
      this.animateCameraTo(
        hasPos ? cam.position : null,
        hasTarget ? cam.target : null,
        550
      );
      return;
    }
    this.cameraAnim = null;
    if (hasPos) {
      this.camera.position.set(cam.position[0], cam.position[1], cam.position[2]);
    }
    if (hasTarget) {
      this.controls.target.set(cam.target[0], cam.target[1], cam.target[2]);
    }
    this.controls.update();
    this.updateCameraHud();
  }

  updateCameraHud() {
    const el = document.getElementById("camera-hud-coords");
    if (!el || !this.camera || !this.controls) return;
    const p = this.camera.position;
    const t = this.controls.target;
    el.textContent = `Cam [${p.x.toFixed(2)}, ${p.y.toFixed(2)}, ${p.z.toFixed(2)}] → Target [${t.x.toFixed(2)}, ${t.y.toFixed(2)}, ${t.z.toFixed(2)}]`;
  }

  // -------------------------------------------------------------------------
  // UI Binding & Synchronized Controls
  // -------------------------------------------------------------------------
  bindUiEvents() {
    // 1. Canvas click-to-select raycasting
    const dom = this.renderer.domElement;
    dom.addEventListener("pointerdown", (e) => {
      this.pointerDownPos = { x: e.clientX, y: e.clientY };
    });
    dom.addEventListener("pointerup", (e) => {
      const dx = Math.abs(e.clientX - this.pointerDownPos.x);
      const dy = Math.abs(e.clientY - this.pointerDownPos.y);
      if (dx < 5 && dy < 5) {
        this.handleCanvasClick(e);
      }
    });

    // 2. Quick Clinical Action Presets
    document.getElementById("btn-preset-subscap-focus")?.addEventListener("click", () => {
      this.applyQuickSubscapularisFocus(true);
    });
    document.getElementById("btn-preset-safe-proc")?.addEventListener("click", () => {
      this.loadProcedureTemplate("proc_subscap_axillary_r", 0, true);
    });
    document.getElementById("btn-preset-lesser-tubercle")?.addEventListener("click", () => {
      this.loadProcedureTemplate("proc_subscap_lesser_tubercle_r", 0, true);
    });
    document.getElementById("btn-preset-posterior-si11")?.addEventListener("click", () => {
      this.loadProcedureTemplate("proc_posterior_sits_si11_r", 0, true);
    });
    document.getElementById("btn-scene-undo")?.addEventListener("click", () => {
      fetch("/api/scene/undo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionId: SESSION_ID }),
      });
    });
    document.getElementById("btn-scene-reset")?.addEventListener("click", () => {
      this.sendPatchToServer({
        resetToDefault: true,
        landmarksVisible: false,
        preserveCamera: true,
      });
    });

    // Minimal Floating Structure Card Action Buttons (#minimal-info-card)
    document.getElementById("btn-card-focus")?.addEventListener("click", () => {
      this.applySelectedStructureFocus();
    });
    document.getElementById("btn-card-isolate")?.addEventListener("click", () => {
      this.applySelectedStructureIsolate();
    });
    document.getElementById("btn-card-reset")?.addEventListener("click", () => {
      this.sendPatchToServer({
        resetToDefault: true,
        landmarksVisible: false,
        preserveCamera: true,
      });
    });

    // 3. Camera Angle Buttons (Whole-Body & Regional Presets)
    document.querySelectorAll("[data-camera-preset]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const preset = btn.getAttribute("data-camera-preset");
        const presets = {
          whole_body_front: { position: [0.0, 0.92, 2.35], target: [0.0, 0.90, 0.0], up: [0, 1, 0] },
          posterior: { position: [0.0, 0.95, -2.35], target: [0.0, 0.92, 0.0], up: [0, 1, 0] },
          head_neck: { position: [0.0, 1.62, 0.52], target: [0.0, 1.58, 0.0], up: [0, 1, 0] },
          thorax_organs: { position: [0.0, 1.26, 0.68], target: [0.0, 1.24, 0.0], up: [0, 1, 0] },
          abdomen_organs: { position: [0.0, 0.98, 0.72], target: [0.0, 0.96, 0.0], up: [0, 1, 0] },
          spine_pelvis: { position: [0.0, 0.92, -1.15], target: [0.0, 0.90, 0.0], up: [0, 1, 0] },
          right_anterior: { position: [-0.22, 1.34, 0.55], target: [-0.14, 1.32, -0.02], up: [0, 1, 0] },
          lower_limb: { position: [0.0, 0.55, 1.45], target: [0.0, 0.52, 0.0], up: [0, 1, 0] },
          right_anterolateral: { position: [-0.36, 1.36, 0.34], target: [-0.11, 1.34, -0.04], up: [0, 1, 0] },
          right_posterior: { position: [-0.28, 1.40, -0.38], target: [-0.11, 1.34, -0.05], up: [0, 1, 0] },
          left_anterolateral: { position: [0.36, 1.36, 0.34], target: [0.11, 1.34, -0.04], up: [0, 1, 0] },
          bilateral_front: { position: [0.0, 1.37, 0.52], target: [0.0, 1.34, -0.04], up: [0, 1, 0] },
        };
        if (presets[preset]) {
          document.querySelectorAll("[data-camera-preset]").forEach((b) => b.classList.remove("active"));
          btn.classList.add("active");
          const p = presets[preset];
          this.animateCameraTo(p.position, p.target, 550, () => {
            this.sendCameraUpdateToServer();
          });
        }
      });
    });

    // 4. Side Filter Tabs (Right / Left / All)
    document.querySelectorAll("[data-side-filter]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll("[data-side-filter]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        this.activeSideFilter = btn.getAttribute("data-side-filter") || "right";
        this.renderStructureListUi();
      });
    });

    // 5. Structure Search Input
    const searchInput = document.getElementById("structure-search-input");
    if (searchInput) {
      searchInput.addEventListener("input", (e) => {
        this.searchQuery = (e.target.value || "").trim().toLowerCase();
        this.renderStructureListUi();
      });
    }

    // 6. Group Opacity Sliders
    document.querySelectorAll("[data-group-slider]").forEach((slider) => {
      slider.addEventListener("input", (e) => {
        const grpKey = slider.getAttribute("data-group-slider");
        const val = parseFloat(e.target.value);
        const labelEl = document.getElementById(`group-val-${grpKey}`);
        if (labelEl) labelEl.textContent = `${Math.round(val * 100)}%`;
        this.applyGroupOpacitySlider(grpKey, val);
      });
    });

    // 7. Landmark visibility toggle
    const lmToggle = document.getElementById("toggle-landmarks-visible");
    if (lmToggle) {
      lmToggle.addEventListener("change", (e) => {
        this.sendPatchToServer({
          landmarksVisible: Boolean(e.target.checked),
          preserveCamera: true,
        });
      });
    }

    // 8. Procedure Template controls
    document.getElementById("btn-load-selected-template")?.addEventListener("click", () => {
      const sel = document.getElementById("procedure-template-select");
      if (sel && sel.value) {
        this.loadProcedureTemplate(sel.value, 0, true);
      }
    });

    const procSlider = document.getElementById("procedure-progress-slider");
    if (procSlider) {
      procSlider.addEventListener("input", (e) => {
        const p = parseFloat(e.target.value);
        fetch("/api/procedure/progress", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            sessionId: SESSION_ID,
            progress: p,
            preserveCamera: true,
          }),
        });
      });
    }

    document.getElementById("btn-proc-play-toggle")?.addEventListener("click", () => {
      this.toggleProcedureAutoPlay();
    });

    // 9. Real-Time Volume Waveform + Voice (Auto-Apply on Stop) & Text (Enter) Controller
    this.voiceController = new VoiceCommandController({
      sessionId: SESSION_ID,
      onCommandSuccess: (data) => {
        this.renderVoiceCommandFeedback(data);
      },
    });

    // 10. Supplementary Stage 1 & Stage 2 Generative Visual Synthesis Buttons
    document.getElementById("btn-generate-stage1")?.addEventListener("click", () => {
      this.runSupplementaryStage1();
    });
    document.getElementById("btn-generate-stage2")?.addEventListener("click", () => {
      this.runSupplementaryStage2();
    });
  }

  handleCanvasClick(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    this.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    this.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.pointer, this.camera);
    const pickableMeshes = [];
    for (const entry of this.meshNodesById.values()) {
      if (!entry.rootObj.visible) continue;
      for (const m of entry.meshes) {
        // Skip ultra-faint structures (< 0.12 opacity) when raycasting so users can click deep organs/muscles underneath!
        if (m.material && m.material.opacity >= 0.12) {
          pickableMeshes.push(m);
        }
      }
    }

    const hits = this.raycaster.intersectObjects(pickableMeshes, false);
    if (hits.length > 0) {
      const sid = hits[0].object.userData.structureId;
      if (sid) {
        this.selectStructureInUi(sid, event.shiftKey);
      }
    }
  }

  selectStructureInUi(sid, highlightOnShift = false) {
    const meta = this.structuresById.get(sid);
    if (!meta) return;
    this.selectedStructureId = sid;

    // Immediately update the floating Selected Structure Card (#minimal-info-card)
    this.updateSelectedStructureCard(meta);

    if (this.ws && this.wsConnected) {
      this.ws.send(
        JSON.stringify({
          type: "viewer.select_structure",
          sessionId: SESSION_ID,
          structureId: sid,
        })
      );
    }

    if (highlightOnShift) {
      this.sendPatchToServer({
        highlightIds: [sid],
        highlightedStructureIds: [sid],
        preserveCamera: true,
      });
    }
  }

  getStructureWorldBox(sid) {
    const entry = this.meshNodesById.get(sid);
    if (entry && entry.worldBox && !entry.worldBox.isEmpty()) {
      return entry.worldBox.clone();
    }
    const meta = this.structuresById.get(sid);
    if (!meta) return null;
    const bMin = meta.boundsMin || meta.minBounds || (meta.bbox && meta.bbox.min);
    const bMax = meta.boundsMax || meta.maxBounds || (meta.bbox && meta.bbox.max);
    if (Array.isArray(bMin) && Array.isArray(bMax) && bMin.length === 3 && bMax.length === 3) {
      return new THREE.Box3(
        new THREE.Vector3(Number(bMin[0]), Number(bMin[1]), Number(bMin[2])),
        new THREE.Vector3(Number(bMax[0]), Number(bMax[1]), Number(bMax[2]))
      );
    }
    return null;
  }

  /**
   * Minimal Card Button 1 (#btn-card-focus / "Fade Surrounding"):
   * Works across the entire human body: keeps the selected structure at 1.0 opacity + highlighted,
   * and dims surrounding/covering structures (overlapping 3D bounding box, same anatomical region,
   * superficial muscles, or covering ribcage/skull around deep organs) to 0.15 opacity.
   */
  applySelectedStructureFocus() {
    const targetId =
      this.selectedStructureId ||
      (this.structuresById.has("heart") ? "heart" : "subscapularis_r");
    const targetMeta = this.structuresById.get(targetId);
    const targetBox = this.getStructureWorldBox(targetId);
    const expandedTargetBox = targetBox ? targetBox.clone().expandByScalar(0.06) : null;
    const targetRegion = targetMeta ? targetMeta.region || "" : "";
    const targetCategory = targetMeta ? targetMeta.category || "" : "";

    const sfx = targetId.endsWith("_l") ? "_l" : "_r";
    const shoulderOccluderGroups = {
      trapezius: [`trapezius_descending${sfx}`, `trapezius_transverse${sfx}`, `trapezius_ascending${sfx}`],
      deltoid: [`deltoid_clavicular${sfx}`, `deltoid_acromial${sfx}`, `deltoid_spinal${sfx}`],
      pectoralis: [`pectoralis_major${sfx}`, `pectoralis_minor${sfx}`],
      posterior_sits: [`supraspinatus${sfx}`, `infraspinatus${sfx}`, `teres_minor${sfx}`],
    };

    const structures = {};

    // 1. Check all structures in manifest for spatial overlap or shared region/covering layer
    for (const s of (this.manifest && this.manifest.structures) || []) {
      if (s.id === targetId) continue;

      let shouldFade = false;

      // Same anatomical region (e.g., head_neck, thorax, abdomen, pelvis, upper_limb, lower_limb)
      if (targetRegion && s.region && s.region === targetRegion) {
        shouldFade = true;
      }

      // 3D bounding-box proximity / overlap
      if (!shouldFade && expandedTargetBox) {
        const otherBox = this.getStructureWorldBox(s.id);
        if (otherBox && expandedTargetBox.intersectsBox(otherBox)) {
          shouldFade = true;
        }
      }

      // If target is a thoracic or abdominal organ, also fade ribcage/sternum/pectoralis/abdominal wall
      if (
        !shouldFade &&
        (targetCategory.includes("heart") ||
          targetCategory.includes("lung") ||
          targetCategory.includes("liver") ||
          targetCategory.includes("stomach") ||
          targetCategory.includes("digestive") ||
          targetCategory.includes("kidney") ||
          targetCategory.includes("spleen") ||
          targetCategory.includes("pancreas") ||
          targetCategory.includes("gallbladder"))
      ) {
        const cat = (s.category || "").toLowerCase();
        if (
          cat.includes("thorax_bone") ||
          cat.includes("rib") ||
          cat.includes("pectoralis") ||
          cat.includes("abdominal") ||
          cat.includes("thorax_muscle")
        ) {
          shouldFade = true;
        }
      }

      // If target is brain, fade skull_bone / head_muscle
      if (!shouldFade && targetCategory.includes("brain")) {
        const cat = (s.category || "").toLowerCase();
        if (cat.includes("skull") || cat.includes("head") || cat.includes("neck")) {
          shouldFade = true;
        }
      }

      if (shouldFade) {
        structures[s.id] = {
          visible: true,
          opacity: 0.15,
          highlighted: false,
          outline: false,
        };
      }
    }

    // 2. Also ensure classic shoulder superficial occluders are faded when focusing a shoulder structure
    for (const ids of Object.values(shoulderOccluderGroups)) {
      if (ids.includes(targetId)) continue;
      for (const id of ids) {
        if (this.structuresById.has(id) && !structures[id]) {
          structures[id] = {
            visible: true,
            opacity: 0.15,
            highlighted: false,
            outline: false,
          };
        }
      }
    }

    structures[targetId] = {
      visible: true,
      opacity: 1.0,
      highlighted: true,
      colorHex: "#ef4444",
      outline: true,
    };

    this.sendPatchToServer({
      structures,
      highlightedStructureIds: [targetId],
      highlightIds: [targetId],
      selectedStructureIds: [targetId],
      preserveCamera: true,
    });
  }

  /**
   * Minimal Card Button 2 (#btn-card-isolate / "Isolate"):
   * Sets target structure to 1.0 opacity, skeletal bones across the entire body to 0.35 opacity
   * for anatomical context, and all other muscles/organs/structures to 0.05 opacity.
   */
  applySelectedStructureIsolate() {
    const targetId =
      this.selectedStructureId ||
      (this.structuresById.has("heart") ? "heart" : "subscapularis_r");
    const structures = {};

    for (const s of (this.manifest && this.manifest.structures) || []) {
      if (s.id === targetId) {
        structures[s.id] = {
          visible: true,
          opacity: 1.0,
          highlighted: true,
          colorHex: "#ef4444",
          outline: true,
        };
      } else if (this.isBoneStructure(s)) {
        structures[s.id] = {
          visible: true,
          opacity: 0.35,
          highlighted: false,
          outline: false,
        };
      } else {
        structures[s.id] = {
          visible: true,
          opacity: 0.05,
          highlighted: false,
          outline: false,
        };
      }
    }

    this.sendPatchToServer({
      structures,
      highlightedStructureIds: [targetId],
      highlightIds: [targetId],
      selectedStructureIds: [targetId],
      preserveCamera: true,
    });
  }

  /**
   * Core Scenario Preset: Highlight Right Subscapularis (1.0) + make Trapezius, Supraspinatus, Deltoid, Pectoralis semi-transparent, preserving current camera!
   */
  applyQuickSubscapularisFocus(preserveCamera = true) {
    const sfx = this.activeSideFilter === "left" ? "_l" : "_r";
    const sideKo = sfx === "_l" ? "좌측" : "우측";
    const structures = {};
    structures[`subscapularis${sfx}`] = {
      visible: true,
      opacity: 1.0,
      highlighted: true,
      colorHex: "#ef4444",
      outline: true,
    };
    structures[`subscapularis_origin${sfx}`] = {
      visible: true,
      opacity: 0.95,
      highlighted: true,
      colorHex: "#f59e0b",
      outline: false,
    };
    structures[`subscapularis_insertion${sfx}`] = {
      visible: true,
      opacity: 0.95,
      highlighted: true,
      colorHex: "#f59e0b",
      outline: false,
    };

    const semiList = [
      `trapezius_descending${sfx}`,
      `trapezius_transverse${sfx}`,
      `trapezius_ascending${sfx}`,
      `supraspinatus${sfx}`,
      `deltoid_clavicular${sfx}`,
      `deltoid_acromial${sfx}`,
      `deltoid_spinal${sfx}`,
      `pectoralis_major${sfx}`,
      `pectoralis_minor${sfx}`,
    ];
    for (const id of semiList) {
      structures[id] = {
        visible: true,
        opacity: 0.2,
        highlighted: false,
        outline: false,
      };
    }

    this.sendPatchToServer({
      structures,
      selectedStructureIds: [`subscapularis${sfx}`],
      preserveCamera,
      explanationCard: {
        titleKo: `${sideKo} 견갑하근 집중 강조 & 주변 표층 근육 반투명화`,
        bodyKo:
          `${sideKo} 견갑하근을 선명하게 강조하고 승모근, 극상근, 삼각근, 대흉근·소흉근을 반투명하게 조절했습니다.`,
      },
    });
  }

  applyGroupOpacitySlider(groupKey, opacityVal) {
    const sfxList =
      this.activeSideFilter === "all"
        ? ["_r", "_l"]
        : this.activeSideFilter === "left"
        ? ["_l"]
        : ["_r"];

    const GROUP_STEMS = {
      trapezius: ["trapezius_descending", "trapezius_transverse", "trapezius_ascending"],
      posterior_sits: ["supraspinatus", "infraspinatus", "teres_minor"],
      subscapularis: ["subscapularis"],
      deltoid: ["deltoid_clavicular", "deltoid_acromial", "deltoid_spinal"],
      pectoralis: ["pectoralis_major", "pectoralis_minor"],
      scapular_stabilizer: [
        "teres_major",
        "latissimus_dorsi",
        "serratus_anterior",
        "rhomboid_major",
        "rhomboid_minor",
        "levator_scapulae",
      ],
      upper_arm: [
        "biceps_long_head",
        "biceps_short_head",
        "coracobrachialis",
        "triceps_long_head",
        "triceps_lateral_head",
      ],
      bone: ["scapula", "humerus", "clavicle"],
      neurovascular: [
        "axillary_artery",
        "subscapular_artery",
        "axillary_nerve",
        "superior_subscapular_nerve",
        "inferior_subscapular_nerve",
      ],
    };

    const stems = GROUP_STEMS[groupKey] || [];
    const structures = {};
    for (const stem of stems) {
      for (const sfx of sfxList) {
        const sid = `${stem}${sfx}`;
        if (this.structuresById.has(sid)) {
          structures[sid] = {
            visible: opacityVal > 0.01,
            opacity: Number(opacityVal.toFixed(2)),
          };
        }
      }
    }

    this.sendPatchToServer({
      structures,
      preserveCamera: true,
    });
  }

  sendPatchToServer(changes) {
    fetch("/api/scene/patch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: SESSION_ID,
        changes,
        waitForAck: false,
      }),
    });
  }

  loadProcedureTemplate(templateId, stepIndex = 0, preserveCamera = true) {
    fetch("/api/procedure/load", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        sessionId: SESSION_ID,
        templateId,
        stepIndex,
        preserveCamera,
      }),
    });
  }

  toggleProcedureAutoPlay() {
    const btn = document.getElementById("btn-proc-play-toggle");
    if (this.procedurePlayTimer) {
      clearInterval(this.procedurePlayTimer);
      this.procedurePlayTimer = null;
      if (btn) btn.textContent = "▶ 단계 자동 재생";
      return;
    }

    if (btn) btn.textContent = "⏸ 일시정지";
    this.procedurePlayTimer = setInterval(() => {
      const proc = this.currentState && this.currentState.activeProcedure;
      if (!proc) {
        this.loadProcedureTemplate("proc_subscap_axillary_r", 0, true);
        return;
      }
      const nextStep = ((proc.stepIndex || 0) + 1) % (proc.stepCount || 5);
      fetch("/api/procedure/progress", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          sessionId: SESSION_ID,
          stepIndex: nextStep,
          preserveCamera: true,
        }),
      });
    }, 2800);
  }

  populateProcedureTemplatesDropdown(templates) {
    const sel = document.getElementById("procedure-template-select");
    if (!sel || sel.options.length > 0) return;
    for (const tpl of templates) {
      const opt = document.createElement("option");
      opt.value = tpl.id;
      opt.textContent = tpl.titleKo;
      sel.appendChild(opt);
    }
  }

  renderStructureListUi() {
    const listEl = document.getElementById("structure-list-container");
    if (!listEl || !this.manifest) return;

    const q = this.searchQuery;
    const sideFilter = this.activeSideFilter;

    const items = (this.manifest.structures || []).filter((s) => {
      if (sideFilter !== "all" && s.side !== sideFilter && s.side !== "midline") {
        return false;
      }
      if (!q) return true;
      const hay = `${s.id} ${s.nameKo} ${s.nameEn} ${s.baseNameKo || ""} ${(s.aliases || []).join(" ")}`.toLowerCase();
      return hay.includes(q);
    });

    const countEl = document.getElementById("structure-filter-count");
    if (countEl) countEl.textContent = `${items.length}개 구조물`;

    listEl.innerHTML = "";
    for (const s of items) {
      const st =
        (this.currentState && this.currentState.structures && this.currentState.structures[s.id]) || {
          visible: true,
          opacity: s.defaultOpacity ?? 1.0,
          highlighted: false,
        };

      const row = document.createElement("div");
      row.className = `structure-row ${st.highlighted ? "is-highlighted" : ""}`;
      row.innerHTML = `
        <div class="structure-row-top">
          <button class="structure-name-btn" title="${s.nameEn}">
            <span class="side-tag side-${s.side}">${s.side === "right" ? "R" : s.side === "left" ? "L" : "M"}</span>
            <span class="ko-name">${s.nameKo}</span>
          </button>
          <div class="structure-actions">
            <button class="btn-mini ${st.highlighted ? "active-hl" : ""}" data-action="highlight" title="강조">★</button>
            <span class="opacity-readout">${Math.round((st.opacity ?? 1) * 100)}%</span>
          </div>
        </div>
        <input type="range" min="0" max="1" step="0.05" value="${st.opacity ?? 1}" class="structure-opacity-slider" />
      `;

      row.querySelector(".structure-name-btn")?.addEventListener("click", () => {
        this.selectStructureInUi(s.id, false);
      });

      row.querySelector('[data-action="highlight"]')?.addEventListener("click", () => {
        const nextHl = !st.highlighted;
        const patch = {};
        patch[s.id] = {
          visible: true,
          opacity: nextHl ? 1.0 : st.opacity,
          highlighted: nextHl,
          outline: nextHl,
          colorHex: nextHl ? "#ef4444" : null,
        };
        this.sendPatchToServer({
          structures: patch,
          selectedStructureIds: [s.id],
          preserveCamera: true,
        });
      });

      row.querySelector(".structure-opacity-slider")?.addEventListener("input", (e) => {
        const val = parseFloat(e.target.value);
        const readout = row.querySelector(".opacity-readout");
        if (readout) readout.textContent = `${Math.round(val * 100)}%`;
        const patch = {};
        patch[s.id] = {
          visible: val > 0.01,
          opacity: val,
        };
        this.sendPatchToServer({
          structures: patch,
          preserveCamera: true,
        });
      });

      listEl.appendChild(row);
    }
  }

  syncUiFromAuthoritativeState() {
    this.updateConnectionBadge(this.wsConnected);
    this.renderStructureListUi();

    if (!this.currentState) return;

    // Sync Section 2 Group Opacity Sliders with authoritative state
    const sfx = this.activeSideFilter === "left" ? "_l" : "_r";
    const groupRepresentativeMap = {
      trapezius: `trapezius_descending${sfx}`,
      posterior_sits: `supraspinatus${sfx}`,
      subscapularis: `subscapularis${sfx}`,
      deltoid: `deltoid_acromial${sfx}`,
      pectoralis: `pectoralis_major${sfx}`,
      scapular_stabilizer: `teres_major${sfx}`,
      bone: `scapula${sfx}`,
    };
    const stMap = this.currentState.structures || {};
    for (const [grpKey, repId] of Object.entries(groupRepresentativeMap)) {
      const repState = stMap[repId];
      if (repState && repState.opacity !== undefined) {
        const opVal = repState.visible === false ? 0 : Number(repState.opacity);
        const sliderEl = document.querySelector(`[data-group-slider="${grpKey}"]`);
        const labelEl = document.getElementById(`group-val-${grpKey}`);
        if (sliderEl) sliderEl.value = String(opVal);
        if (labelEl) labelEl.textContent = `${Math.round(opVal * 100)}%`;
      }
    }

    const selIds = this.currentState.selectedStructureIds || [];
    if (selIds.length > 0) {
      this.selectedStructureId = selIds[0];
      this.updateSelectedStructureCard(selIds[0]);
    }

    // Update explanation card if available
    const card = this.currentState.lastExplanationCard;
    if (card) {
      const titleEl = document.getElementById("clinical-card-title");
      const bodyEl = document.getElementById("clinical-card-body");
      if (titleEl && card.titleKo) titleEl.textContent = this.stripCitations(card.titleKo);
      if (bodyEl && card.bodyKo) bodyEl.textContent = this.stripCitations(card.bodyKo);
    }

    // Update procedure step panel
    const proc = this.currentState.activeProcedure;
    const procBox = document.getElementById("procedure-step-status");
    const procSlider = document.getElementById("procedure-progress-slider");
    const stepsContainer = document.getElementById("procedure-steps-pills");
    if (proc && procBox) {
      const stepObj = proc.currentStep || {};
      procBox.innerHTML = `
        <div class="proc-active-title">${this.stripCitations(proc.titleKo)}</div>
        <div class="proc-step-headline">${this.stripCitations(stepObj.titleKo || "")}</div>
        <div class="proc-step-desc">${this.stripCitations(stepObj.descriptionKo || "")}</div>
        <div class="proc-disclaimer">${this.stripCitations(proc.safetyDisclaimerKo || "")}</div>
      `;
      if (procSlider && proc.progress !== undefined) {
        procSlider.value = String(proc.progress);
      }
      if (stepsContainer && Array.isArray(proc.steps)) {
        stepsContainer.innerHTML = "";
        for (const stp of proc.steps) {
          const b = document.createElement("button");
          b.className = `step-pill ${stp.stepIndex === proc.stepIndex ? "active" : ""}`;
          b.textContent = `Step ${stp.stepIndex + 1}`;
          b.addEventListener("click", () => {
            fetch("/api/procedure/progress", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                sessionId: SESSION_ID,
                stepIndex: stp.stepIndex,
                preserveCamera: true,
              }),
            });
          });
          stepsContainer.appendChild(b);
        }
      }
    }
  }

  formatStructureSubtitleEn(struct) {
    if (!struct) return "Human Anatomy · Whole-Body Atlas";
    const REGION_LABELS = {
      head_neck: "Head & Neck",
      thorax: "Thorax",
      abdomen: "Abdomen",
      pelvis: "Pelvis",
      spine: "Spine & Back",
      upper_limb: "Upper Limb",
      lower_limb: "Lower Limb",
    };
    const CATEGORY_LABELS = {
      brain: "Central Nervous System",
      skull_bone: "Cranial & Facial Skeleton",
      head_muscle: "Cranial & Cervical Musculature",
      neck_muscle: "Cervical Musculature",
      heart_great_vessels: "Cardiovascular System",
      heart: "Cardiovascular System",
      artery: "Arterial System",
      vein: "Venous System",
      lungs_respiratory: "Respiratory System",
      lung: "Respiratory System",
      respiratory: "Respiratory System",
      liver_biliary: "Hepatobiliary System",
      liver: "Hepatobiliary System",
      gallbladder: "Hepatobiliary System",
      digestive_tract: "Digestive System",
      stomach: "Digestive System",
      digestive: "Digestive System",
      pancreas_spleen: "Digestive & Lymphatic Organs",
      pancreas: "Endocrine & Exocrine Organ",
      spleen: "Lymphatic System",
      urinary: "Urinary System",
      kidney: "Urinary System",
      bladder: "Urinary System",
      thorax_bone: "Thoracic Cage Skeleton",
      spine_bone: "Vertebral Column",
      pelvis_bone: "Pelvic Girdle Skeleton",
      upper_limb_bone: "Upper Limb Skeleton",
      lower_limb_bone: "Lower Limb Skeleton",
      bone: "Skeletal System",
      major_nerve: "Peripheral Nervous System",
      nerve: "Peripheral Nervous System",
      neurovascular: "Neurovascular Bundle",
      rotator_cuff_anterior: "Rotator Cuff (Anterior)",
      rotator_cuff_posterior: "Rotator Cuff (Posterior)",
      superficial_posterior: "Superficial Back Musculature",
      deltoid: "Glenohumeral Abductor",
      pectoralis: "Anterior Chest Wall",
      scapular_stabilizer: "Scapular Stabilizer",
      upper_arm: "Brachial Musculature",
      forearm_muscle: "Forearm Musculature",
      abdominal_muscle: "Abdominal Wall Musculature",
      back_muscle: "Intrinsic Back Musculature",
      gluteal_hip_muscle: "Gluteal & Hip Musculature",
      thigh_muscle: "Thigh Musculature",
      lower_leg_muscle: "Lower Leg Musculature",
      attachment_zone: "Origin & Insertion Footprint",
    };

    const rawRegion = (struct.region || "").toLowerCase();
    const rawCat = (struct.category || struct.group || struct.system || "").toLowerCase();
    const regionLabel =
      REGION_LABELS[rawRegion] ||
      (struct.side === "right"
        ? "Right Side"
        : struct.side === "left"
        ? "Left Side"
        : "Midline / Axial");
    const catLabel =
      CATEGORY_LABELS[rawCat] ||
      (rawCat
        ? rawCat
            .replace(/_/g, " ")
            .replace(/\b\w/g, (c) => c.toUpperCase())
        : "Anatomical Structure");

    return `${regionLabel} · ${catLabel}`;
  }

  getStructureNoteEn(struct) {
    if (!struct) return "";
    const enCandidate =
      struct.clinicalNoteEn ||
      struct.descriptionEn ||
      struct.summaryEn ||
      "";
    if (enCandidate) {
      return this.stripCitations(enCandidate);
    }
    const koCandidate = this.stripCitations(struct.clinicalNoteKo || struct.descriptionKo || "");
    if (koCandidate && !/[가-힣]/.test(koCandidate)) {
      return koCandidate;
    }

    const name = this.stripCitations(struct.nameEn || struct.id);
    const cat = (struct.category || struct.group || "").toLowerCase();
    if (cat.includes("heart")) {
      return `${name} — Central muscular pump of the cardiovascular system within the middle mediastinum, propelling oxygenated blood through the aorta and systemic circulation.`;
    }
    if (cat.includes("lung") || cat.includes("respiratory")) {
      return `${name} — Primary respiratory organ within the thoracic cavity responsible for alveolar gas exchange between inhaled air and the pulmonary circulation.`;
    }
    if (cat.includes("liver") || cat.includes("biliary") || cat.includes("gallbladder")) {
      return `${name} — Key hepatobiliary organ in the right upper abdominal quadrant supporting metabolism, detoxification, and bile production for digestion.`;
    }
    if (cat.includes("stomach") || cat.includes("digestive") || cat.includes("pancreas") || cat.includes("spleen")) {
      return `${name} — Visceral abdominal organ involved in enzymatic digestion, nutrient absorption, metabolic regulation, or immune filtration.`;
    }
    if (cat.includes("kidney") || cat.includes("urinary") || cat.includes("bladder")) {
      return `${name} — Retroperitoneal/pelvic urinary structure responsible for blood filtration, fluid-electrolyte homeostasis, and urine transport.`;
    }
    if (cat.includes("brain")) {
      return `${name} — Primary neural center enclosed within the neurocranium coordinating sensory integration, motor control, cognition, and autonomic regulation.`;
    }
    if (cat.includes("nerve") || cat.includes("neurovascular") || cat.includes("artery") || cat.includes("vein")) {
      return `${name} — Critical neurovascular pathway supplying motor/sensory innervation or blood perfusion; key anatomical landmark to protect during clinical procedures.`;
    }
    if (this.isBoneStructure(struct)) {
      return `${name} — Skeletal element providing structural support, biomechanical leverage for muscle attachments, and protection for deeper visceral and neurovascular structures.`;
    }
    if (cat.includes("rotator_cuff")) {
      return `${name} — Dynamic stabilizer of the glenohumeral joint originating on the scapula and inserting on the humeral tubercles to control shoulder rotation and abduction.`;
    }
    return `${name} — Interactive 3D anatomical structure. Use "Fade Surrounding" to dim adjacent tissues or "Isolate" to inspect its 3D geometry against the skeleton.`;
  }

  updateSelectedStructureCard(structOrId) {
    const struct =
      typeof structOrId === "string"
        ? this.structuresById.get(structOrId)
        : structOrId;
    if (!struct) return;

    this.selectedStructureId = struct.id;
    const st =
      (this.currentState && this.currentState.structures && this.currentState.structures[struct.id]) || {
        opacity: 1.0,
        highlighted: false,
      };

    const nameEl = document.getElementById("selected-struct-name");
    const enEl = document.getElementById("selected-struct-en");
    const noteEl = document.getElementById("selected-struct-note");
    const metaEl = document.getElementById("selected-struct-meta");

    const cleanNameEn = this.stripCitations(struct.nameEn || struct.nameKo || struct.id);
    if (nameEl) nameEl.textContent = cleanNameEn;
    if (enEl) enEl.textContent = this.formatStructureSubtitleEn(struct);
    if (noteEl) noteEl.textContent = this.getStructureNoteEn(struct);
    if (metaEl) {
      metaEl.textContent = `Opacity: ${Math.round((st.opacity ?? 1) * 100)}%`;
    }
  }

  showLandmarkDetailCard(lm) {
    const titleEl = document.getElementById("clinical-card-title");
    const bodyEl = document.getElementById("clinical-card-body");
    const lmName = this.stripCitations(lm.nameEn || lm.nameKo || lm.id);
    const lmDesc = this.stripCitations(lm.descriptionEn || lm.descriptionKo || "");
    if (titleEl) titleEl.textContent = `📍 ${lmName}`;
    if (bodyEl) bodyEl.textContent = lmDesc;

    // Also reflect clicked landmark info cleanly in the minimal info card
    const nameEl = document.getElementById("selected-struct-name");
    const enEl = document.getElementById("selected-struct-en");
    const noteEl = document.getElementById("selected-struct-note");
    if (!titleEl && nameEl) {
      nameEl.textContent = lmName;
      if (enEl) enEl.textContent = "Anatomical Landmark · 3D Coordinate";
      if (noteEl) noteEl.textContent = lmDesc || `${lmName} — Surface or deep anatomical reference point.`;
    }
  }

  // -------------------------------------------------------------------------
  // Voice & Natural-Language Command Execution
  // -------------------------------------------------------------------------
  async submitNaturalLanguageCommand(commandText) {
    if (this.voiceController) {
      return this.voiceController.submitTextCommand(commandText, "text_input");
    }
  }

  renderVoiceCommandFeedback(data) {
    const statusEl = document.getElementById("voice-command-status");
    if (!data || !statusEl) return;

    const card = data.explanationCard || {};
    const cmdText = data.commandText || "";
    const rawMsg =
      card.spokenFeedbackEn ||
      card.bodyEn ||
      card.titleEn ||
      card.spokenFeedbackKo ||
      card.bodyKo ||
      card.titleKo ||
      "Updated the 3D human anatomy view.";
    let cleanMsg = this.stripCitations(rawMsg).replace(/\s+/g, " ").trim();
    if (/[가-힣]/.test(cleanMsg) && cmdText && !/[가-힣]/.test(cmdText)) {
      cleanMsg = `Applied to 3D scene: "${cmdText}"`;
    }
    statusEl.textContent = cleanMsg.startsWith("✓") ? cleanMsg : `✓ ${cleanMsg}`;

    // Also update the floating info card if the explanationCard provides an English headline/body
    if (card.titleEn || card.bodyEn) {
      const nameEl = document.getElementById("selected-struct-name");
      const noteEl = document.getElementById("selected-struct-note");
      if (nameEl && card.titleEn) nameEl.textContent = this.stripCitations(card.titleEn);
      if (noteEl && card.bodyEn) noteEl.textContent = this.stripCitations(card.bodyEn);
    }
  }

  // -------------------------------------------------------------------------
  // Supplementary Stage 1 & Stage 2 Generative Visuals
  // -------------------------------------------------------------------------
  async runSupplementaryStage1() {
    const outBox = document.getElementById("supplementary-visual-output");
    if (!outBox) return;
    outBox.innerHTML = `<div class="supp-loading">Generating patient explanation card...</div>`;

    const promptInput = document.getElementById("voice-command-input");
    const userPrompt =
      (promptInput && promptInput.value.trim()) ||
      "Explain the anatomy and clinical significance of the selected structure in clear patient-friendly terms.";

    try {
      const resp = await fetch("/api/stage1-instant", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_prompt: userPrompt }),
      });
      const data = await resp.json();
      const brief = data.brief || {};
      const img = data.illustration || {};
      outBox.innerHTML = `
        <div class="supp-result-card">
          <div class="supp-header">
            <strong>${brief.headline_ko || "Clinical Summary"}</strong>
            <span class="lat-chip">${data.total_elapsed_sec || ""}s</span>
          </div>
          <p class="supp-summary">${brief.patient_friendly_explanation_ko || ""}</p>
          ${
            img.image_data_url
              ? `<img src="${img.image_data_url}" alt="Clinical Illustration" class="supp-image" />`
              : ""
          }
        </div>
      `;
    } catch (err) {
      outBox.innerHTML = `<div class="supp-loading">Stage 1 generation failed: ${err}</div>`;
    }
  }

  async runSupplementaryStage2() {
    const outBox = document.getElementById("supplementary-visual-output");
    if (!outBox) return;
    outBox.innerHTML = `<div class="supp-loading">Synthesizing interactive mechanism diagram...</div>`;

    const promptInput = document.getElementById("voice-command-input");
    const userPrompt =
      (promptInput && promptInput.value.trim()) ||
      "Interactive anatomical mechanism diagram for the selected structure";

    try {
      const resp = await fetch("/api/stage2-interactive", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_prompt: userPrompt, thinking_level: "low" }),
      });
      const data = await resp.json();
      if (data.html) {
        outBox.innerHTML = `
          <div class="supp-result-card">
            <div class="supp-header">
              <strong>Interactive Mechanism Diagram</strong>
              <span class="lat-chip">Validation: ${data.validation?.passed ? "PASS" : "CHECK"}</span>
            </div>
            <iframe sandbox="allow-scripts" class="supp-iframe" srcdoc="${data.html
              .replace(/&/g, "&amp;")
              .replace(/"/g, "&quot;")}"></iframe>
          </div>
        `;
      }
    } catch (err) {
      outBox.innerHTML = `<div class="supp-loading">Stage 2 generation failed: ${err}</div>`;
    }
  }

  animate() {
    requestAnimationFrame(() => this.animate());

    if (this.cameraAnim && this.camera && this.controls) {
      const elapsed = performance.now() - this.cameraAnim.startTime;
      const rawT = Math.min(1.0, elapsed / Math.max(1, this.cameraAnim.durationMs));
      // Cubic ease-in-out
      const easeT =
        rawT < 0.5
          ? 4 * rawT * rawT * rawT
          : 1 - Math.pow(-2 * rawT + 2, 3) / 2;

      this.camera.position.lerpVectors(
        this.cameraAnim.startPos,
        this.cameraAnim.endPos,
        easeT
      );
      this.controls.target.lerpVectors(
        this.cameraAnim.startTarget,
        this.cameraAnim.endTarget,
        easeT
      );
      this.controls.update();
      this.updateCameraHud();

      if (rawT >= 1.0) {
        const cb = this.cameraAnim.onComplete;
        this.cameraAnim = null;
        if (typeof cb === "function") cb();
      }
    } else if (this.controls) {
      this.controls.update();
    }

    this.updateLandmarkOverlayPositions();
    if (this.renderer && this.scene && this.camera) {
      this.renderer.render(this.scene, this.camera);
    }
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const viewer = new ShoulderAnatomyViewer();
  window.cliniviewViewer = viewer;
  viewer.init().catch((err) => {
    console.error("Viewer initialization failed:", err);
    viewer.setLoadingStatus(`Load Error: ${err.message}`, false);
  });
});
