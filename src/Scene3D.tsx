import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { EffectComposer } from 'three/addons/postprocessing/EffectComposer.js';
import { RenderPass } from 'three/addons/postprocessing/RenderPass.js';
import { UnrealBloomPass } from 'three/addons/postprocessing/UnrealBloomPass.js';
import { OutputPass } from 'three/addons/postprocessing/OutputPass.js';

export type SatelliteKind = 'task' | 'objective' | 'process';
export type SceneEventKind = 'success' | 'failure' | 'reply';
export type SceneState = {
  page: string;
  busy: boolean;
  connected: boolean;
  /** 0..1, how much work is in flight (drives rotation speed and plasma agitation). */
  load: number;
  satellites: SatelliteKind[];
  /** Bumping `seq` fires one shockwave of the given kind. */
  event: { seq: number; kind: SceneEventKind } | null;
};

const ION = 0x5ce1e6, PLASMA = 0x9b7bff, SIGNAL = 0xffb547, ABYSS = 0x0a0e1f, MIST = 0xc9d2f0, OK = 0x4fd69c, KO = 0xff6b7a;
const SATELLITE_COLOR: Record<SatelliteKind, number> = { process: ION, task: SIGNAL, objective: PLASMA };
const SATELLITE_RING: Record<SatelliteKind, number> = { process: 0, task: 1, objective: 2 };
const EVENT_COLOR: Record<SceneEventKind, number> = { success: OK, failure: KO, reply: ION };
const MAX_SATELLITES = 24;
const TRAIL_POINTS = 22;
const TRAIL_SPACING = 0.045; // radians between trail points
const WAVE_POOL = 6;
const WAVE_SECONDS = 1.6;

// Agent page: core floats above the hero text. Other pages: camera slides so the core rises into the top-right corner.
type Pose = { camera: [number, number, number]; look: [number, number, number] };
const POSES: Record<string, Pose> = { agent: { camera: [0, -1.2, 11.5], look: [0, -2.3, 0] } };
const DEFAULT_POSE: Pose = { camera: [-4.4, -2.4, 12], look: [-4.4, -3.3, 0] };
/** Half the sidebar width, so the core centres on the main column rather than the window. */
const sidebarShift = (width: number) => (width > 850 ? 118 : width > 600 ? 98 : 0);

// Plasma body: two octaves of travelling sine waves displace the sphere along its normals.
const PLASMA_VERTEX = /* glsl */ `
  uniform float uTime;
  uniform float uEnergy;
  varying float vWave;
  varying vec3 vNormal;
  varying vec3 vView;
  float wave(vec3 p, float t) {
    return sin(p.x * 3.1 + t) * sin(p.y * 2.7 + t * 1.3) * sin(p.z * 3.4 + t * 0.7)
         + 0.5 * sin(p.x * 6.3 - t * 1.7) * sin(p.y * 5.9 + t * 1.1) * sin(p.z * 6.7 - t * 0.9);
  }
  void main() {
    float w = wave(position, uTime * (0.6 + uEnergy));
    vWave = w;
    vec3 displaced = position + normal * w * (0.05 + uEnergy * 0.16);
    vec4 mv = modelViewMatrix * vec4(displaced, 1.0);
    vNormal = normalize(normalMatrix * normal);
    vView = normalize(-mv.xyz);
    gl_Position = projectionMatrix * mv;
  }
`;
const PLASMA_FRAGMENT = /* glsl */ `
  uniform vec3 uColorA;
  uniform vec3 uColorB;
  uniform float uIntensity;
  varying float vWave;
  varying vec3 vNormal;
  varying vec3 vView;
  void main() {
    float fresnel = pow(1.0 - max(dot(vNormal, vView), 0.0), 2.2);
    vec3 color = mix(uColorA, uColorB, smoothstep(-0.9, 0.9, vWave));
    gl_FragColor = vec4(color * (0.18 + fresnel * 1.0) * uIntensity, 0.45 + fresnel * 0.5);
  }
`;

/** Soft radial glow drawn once to a canvas: replaces the CSS gradient now that the canvas is opaque. */
function nebulaTexture() {
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = 256;
  const ctx = canvas.getContext('2d')!;
  const gradient = ctx.createRadialGradient(128, 128, 0, 128, 128, 128);
  gradient.addColorStop(0, 'rgba(36, 46, 110, 0.55)');
  gradient.addColorStop(0.45, 'rgba(22, 28, 70, 0.25)');
  gradient.addColorStop(1, 'rgba(10, 14, 31, 0)');
  ctx.fillStyle = gradient;
  ctx.fillRect(0, 0, 256, 256);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

export default function Scene3D({ state }: { state: SceneState }) {
  const host = useRef<HTMLDivElement>(null);
  const live = useRef(state);
  live.current = state;
  const wake = useRef<() => void>(() => {});

  useEffect(() => {
    const el = host.current;
    if (!el) return;
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: 'low-power' });
    } catch {
      return; // No WebGL: the CSS gradient behind the canvas stays as the backdrop.
    }
    const pixelRatio = Math.min(window.devicePixelRatio, 1.5);
    renderer.setPixelRatio(pixelRatio);
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    // scene.background is colour-managed; a raw clear colour came out double-encoded (too light) through OutputPass.
    scene.background = new THREE.Color(ABYSS);
    scene.fog = new THREE.FogExp2(ABYSS, 0.035);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 120);
    const disposables: { dispose(): void }[] = [];
    const track = <T extends { dispose(): void }>(item: T) => { disposables.push(item); return item; };
    const additive = { transparent: true, blending: THREE.AdditiveBlending, depthWrite: false } as const;

    const nebula = new THREE.Sprite(track(new THREE.SpriteMaterial({ map: track(nebulaTexture()), depthWrite: false, fog: false })));
    nebula.scale.setScalar(34);
    nebula.position.z = -8;
    scene.add(nebula);

    // Core: faceted shell, glowing vertices, plasma body, halo.
    const core = new THREE.Group();
    scene.add(core);
    const shellGeo = track(new THREE.IcosahedronGeometry(1.6, 1));
    const shellMat = track(new THREE.MeshBasicMaterial({ color: ION, wireframe: true, transparent: true, opacity: 0.45 }));
    const shell = new THREE.Mesh(shellGeo, shellMat);
    core.add(shell);
    const vertexMat = track(new THREE.PointsMaterial({ color: ION, size: 0.09, opacity: 1, ...additive }));
    shell.add(new THREE.Points(shellGeo, vertexMat));
    const plasmaUniforms = {
      uTime: { value: 0 },
      uEnergy: { value: 0.3 },
      uIntensity: { value: 1 },
      uColorA: { value: new THREE.Color(PLASMA) },
      uColorB: { value: new THREE.Color(ION) },
    };
    const plasmaMat = track(new THREE.ShaderMaterial({ uniforms: plasmaUniforms, vertexShader: PLASMA_VERTEX,
      fragmentShader: PLASMA_FRAGMENT, transparent: true, depthWrite: false }));
    const plasma = new THREE.Mesh(track(new THREE.IcosahedronGeometry(0.95, 20)), plasmaMat);
    core.add(plasma);
    const haloMat = track(new THREE.MeshBasicMaterial({ color: ION, opacity: 0.05, side: THREE.BackSide, ...additive }));
    core.add(new THREE.Mesh(track(new THREE.SphereGeometry(2.3, 32, 32)), haloMat));

    // Three tilted orbits: processes, tasks, objectives.
    const ringMat = track(new THREE.MeshBasicMaterial({ color: MIST, transparent: true, opacity: 0.08, side: THREE.DoubleSide }));
    const orbits = [2.7, 3.4, 4.1].map((radius, index) => {
      const orbit = new THREE.Group();
      orbit.rotation.set(Math.PI / 2 + (index - 1) * 0.38, index * 0.5, 0);
      orbit.add(new THREE.Mesh(track(new THREE.RingGeometry(radius - 0.006, radius + 0.006, 160)), ringMat));
      scene.add(orbit);
      return { group: orbit, radius, speed: 0.35 - index * 0.08 };
    });

    // Satellites, each with a fading trail drawn along its own orbit.
    const satelliteGeo = track(new THREE.SphereGeometry(0.08, 16, 16));
    const trailMat = track(new THREE.LineBasicMaterial({ vertexColors: true, ...additive }));
    const satellites = Array.from({ length: MAX_SATELLITES }, () => {
      const mesh = new THREE.Mesh(satelliteGeo, track(new THREE.MeshBasicMaterial({ color: ION })));
      const trailGeo = track(new THREE.BufferGeometry());
      trailGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(TRAIL_POINTS * 3), 3));
      trailGeo.setAttribute('color', new THREE.BufferAttribute(new Float32Array(TRAIL_POINTS * 3), 3));
      const trail = new THREE.Line(trailGeo, trailMat);
      trail.frustumCulled = false;
      mesh.visible = trail.visible = false;
      return { mesh, trail, color: new THREE.Color() };
    });

    // Energy beams from the core to every visible satellite (world space, rebuilt each frame).
    const beamPositions = new Float32Array(MAX_SATELLITES * 2 * 3);
    const beamColors = new Float32Array(MAX_SATELLITES * 2 * 3);
    const beamGeo = track(new THREE.BufferGeometry());
    beamGeo.setAttribute('position', new THREE.BufferAttribute(beamPositions, 3));
    beamGeo.setAttribute('color', new THREE.BufferAttribute(beamColors, 3));
    const beamMat = track(new THREE.LineBasicMaterial({ vertexColors: true, opacity: 0.35, ...additive }));
    const beams = new THREE.LineSegments(beamGeo, beamMat);
    beams.frustumCulled = false;
    scene.add(beams);

    // Shockwaves fired by task results and agent replies.
    const waveGeo = track(new THREE.RingGeometry(0.92, 1, 128));
    const waves = Array.from({ length: WAVE_POOL }, () => {
      const material = track(new THREE.MeshBasicMaterial({ color: ION, opacity: 0, side: THREE.DoubleSide, ...additive }));
      const mesh = new THREE.Mesh(waveGeo, material);
      mesh.visible = false;
      scene.add(mesh);
      return { mesh, material, age: WAVE_SECONDS };
    });

    // Distant star field.
    const starCount = 1400;
    const starPositions = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount; i++) {
      const radius = 22 + Math.random() * 40;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      starPositions.set([radius * Math.sin(phi) * Math.cos(theta), radius * Math.cos(phi), radius * Math.sin(phi) * Math.sin(theta)], i * 3);
    }
    const starGeo = track(new THREE.BufferGeometry());
    starGeo.setAttribute('position', new THREE.BufferAttribute(starPositions, 3));
    const stars = new THREE.Points(starGeo, track(new THREE.PointsMaterial({ color: MIST, size: 0.08, transparent: true, opacity: 0.45, depthWrite: false })));
    scene.add(stars);

    // Post-processing: render, bloom (the neon glow), then colour-space output.
    const composer = new EffectComposer(renderer);
    composer.setPixelRatio(pixelRatio);
    composer.addPass(new RenderPass(scene, camera));
    // strength, radius, threshold: the threshold keeps the dark backdrop and nebula out of the glow.
    const bloom = new UnrealBloomPass(new THREE.Vector2(256, 256), 0.8, 0.5, 0.22);
    composer.addPass(bloom);
    const outputPass = new OutputPass();
    composer.addPass(outputPass);

    const timer = new THREE.Timer();
    timer.connect(document); // ignores time spent in a hidden tab
    const pointer = { x: 0, y: 0 };
    const cameraGoal = new THREE.Vector3();
    const lookAt = new THREE.Vector3();
    const lookGoal = new THREE.Vector3();
    const worldPos = new THREE.Vector3();
    const tint = new THREE.Color();
    const flashColor = new THREE.Color();
    const dim = new THREE.Color(0x1a2050);
    const initialPose = POSES[live.current.page] ?? DEFAULT_POSE;
    camera.position.set(...initialPose.camera);
    lookAt.set(...initialPose.look);
    let lastEventSeq = live.current.event?.seq ?? 0;
    let kick = 0; // 1 right after an event, decays to 0
    let raf = 0;

    function fireWave(kind: SceneEventKind) {
      const wave = waves.find(item => item.age >= WAVE_SECONDS) ?? waves[0];
      wave.age = 0;
      wave.material.color.setHex(EVENT_COLOR[kind]);
      wave.mesh.visible = true;
      flashColor.setHex(EVENT_COLOR[kind]);
      kick = 1;
    }

    function frame() {
      const s = live.current;
      timer.update();
      const dt = Math.min(timer.getDelta(), 0.05);
      const t = timer.getElapsed();
      const ease = reduced ? 1 : 1 - Math.pow(0.02, dt); // frame-rate independent smoothing
      const energy = s.connected ? 0.35 + s.load * 0.65 + (s.busy ? 0.7 : 0) : 0.1;

      if (s.event && s.event.seq !== lastEventSeq) {
        lastEventSeq = s.event.seq;
        if (!reduced) fireWave(s.event.kind);
      }
      kick = Math.max(0, kick - dt * 1.4);

      // Core motion, colour and plasma agitation.
      core.rotation.y += dt * 0.3 * energy;
      core.rotation.x += dt * 0.07 * energy;
      plasma.rotation.y -= dt * 0.4 * energy;
      shell.scale.setScalar(1 + kick * 0.16 + (s.busy ? Math.sin(t * 4.2) * 0.02 : 0));
      tint.set(!s.connected ? SIGNAL : s.busy ? PLASMA : ION);
      if (kick > 0) tint.lerp(flashColor, kick);
      shellMat.color.lerp(tint, ease);
      vertexMat.color.lerp(tint, ease);
      haloMat.color.lerp(tint, ease);
      haloMat.opacity += ((s.busy ? 0.05 : 0.025) + kick * 0.1 - haloMat.opacity) * ease;
      plasmaUniforms.uTime.value = t;
      plasmaUniforms.uEnergy.value += (Math.min(energy, 1.4) / 1.4 - plasmaUniforms.uEnergy.value) * ease;
      plasmaUniforms.uIntensity.value = (s.connected ? 1 : 0.55) + kick * 0.5;
      plasmaUniforms.uColorA.value.lerp(tint.setHex(s.connected ? PLASMA : SIGNAL), ease);

      // Satellites and their trails.
      const perRing = [0, 0, 0];
      let visible = 0;
      satellites.forEach((sat, index) => {
        const kind = s.satellites[index];
        if (!kind) { sat.mesh.visible = sat.trail.visible = false; return; }
        const ring = SATELLITE_RING[kind];
        const orbit = orbits[ring];
        if (sat.mesh.parent !== orbit.group) { orbit.group.add(sat.mesh); orbit.group.add(sat.trail); }
        sat.color.setHex(SATELLITE_COLOR[kind]);
        (sat.mesh.material as THREE.MeshBasicMaterial).color.copy(sat.color);
        const speed = orbit.speed * (0.6 + energy);
        const angle = perRing[ring]++ * 1.3 + t * speed;
        sat.mesh.position.set(Math.cos(angle) * orbit.radius, Math.sin(angle) * orbit.radius, 0);
        const positions = sat.trail.geometry.attributes.position as THREE.BufferAttribute;
        const colors = sat.trail.geometry.attributes.color as THREE.BufferAttribute;
        for (let k = 0; k < TRAIL_POINTS; k++) {
          const trailAngle = angle - k * TRAIL_SPACING * Math.sign(speed || 1);
          const fade = Math.pow(1 - k / TRAIL_POINTS, 1.6);
          positions.setXYZ(k, Math.cos(trailAngle) * orbit.radius, Math.sin(trailAngle) * orbit.radius, 0);
          colors.setXYZ(k, sat.color.r * fade, sat.color.g * fade, sat.color.b * fade);
        }
        positions.needsUpdate = colors.needsUpdate = true;
        sat.mesh.visible = sat.trail.visible = true;
        visible++;
      });

      // Beams: need world positions, so refresh matrices first.
      scene.updateMatrixWorld();
      let beam = 0;
      satellites.forEach(sat => {
        if (!sat.mesh.visible) return;
        sat.mesh.getWorldPosition(worldPos);
        beamPositions.set([0, 0, 0, worldPos.x, worldPos.y, worldPos.z], beam * 6);
        beamColors.set([dim.r, dim.g, dim.b, sat.color.r, sat.color.g, sat.color.b], beam * 6);
        beam++;
      });
      beamGeo.setDrawRange(0, visible * 2);
      beamGeo.attributes.position.needsUpdate = beamGeo.attributes.color.needsUpdate = true;
      beamMat.opacity = 0.22 + 0.12 * Math.sin(t * 5) + kick * 0.3;

      // Shockwaves expand from the shell and fade, always facing the camera.
      waves.forEach(wave => {
        if (wave.age >= WAVE_SECONDS) { wave.mesh.visible = false; return; }
        wave.age += dt;
        const progress = Math.min(wave.age / WAVE_SECONDS, 1);
        wave.mesh.scale.setScalar(1.7 + progress * 5.5);
        wave.material.opacity = (1 - progress) * 0.9;
        wave.mesh.quaternion.copy(camera.quaternion);
      });

      stars.rotation.y += dt * 0.008;

      const pose = POSES[s.page] ?? DEFAULT_POSE;
      cameraGoal.set(pose.camera[0] + pointer.x * 0.5, pose.camera[1] + pointer.y * 0.35, pose.camera[2]);
      lookGoal.set(...pose.look);
      camera.position.lerp(cameraGoal, ease * 0.6);
      lookAt.lerp(lookGoal, ease * 0.6);
      camera.lookAt(lookAt);
      nebula.position.set(lookAt.x, lookAt.y + 2, -8);
    }

    const loop = () => {
      raf = 0;
      frame();
      composer.render();
      // Keep looping while animating; in reduced-motion mode one frame per state change is enough.
      if (!reduced && !document.hidden) raf = requestAnimationFrame(loop);
    };
    wake.current = () => { if (!raf) raf = requestAnimationFrame(loop); };

    const resize = () => {
      const { clientWidth: width, clientHeight: height } = el;
      renderer.setSize(width, height);
      composer.setSize(width, height);
      camera.aspect = width / Math.max(height, 1);
      camera.setViewOffset(width, height, -sidebarShift(width), 0, width, height);
      camera.updateProjectionMatrix();
      wake.current();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    const onPointer = (event: PointerEvent) => {
      pointer.x = (event.clientX / window.innerWidth) * 2 - 1;
      pointer.y = -((event.clientY / window.innerHeight) * 2 - 1);
    };
    const onVisibility = () => { if (!document.hidden) wake.current(); };
    if (!reduced) window.addEventListener('pointermove', onPointer);
    document.addEventListener('visibilitychange', onVisibility);
    resize();

    return () => {
      cancelAnimationFrame(raf);
      wake.current = () => {};
      timer.dispose();
      observer.disconnect();
      window.removeEventListener('pointermove', onPointer);
      document.removeEventListener('visibilitychange', onVisibility);
      disposables.forEach(item => item.dispose());
      bloom.dispose();
      outputPass.dispose();
      composer.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  // In reduced-motion mode nothing loops, so each state change renders one settled frame.
  useEffect(() => { wake.current(); }, [state]);

  return <div className="scene" ref={host} aria-hidden="true" />;
}
