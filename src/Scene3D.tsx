import { useEffect, useRef } from 'react';
import * as THREE from 'three';

export type SatelliteKind = 'task' | 'objective' | 'process';
export type SceneState = {
  page: string;
  busy: boolean;
  connected: boolean;
  /** 0..1, how much work is in flight (drives rotation speed). */
  load: number;
  satellites: SatelliteKind[];
};

const ION = 0x5ce1e6, PLASMA = 0x9b7bff, SIGNAL = 0xffb547, ABYSS = 0x0a0e1f, MIST = 0xc9d2f0;
const SATELLITE_COLOR: Record<SatelliteKind, number> = { process: ION, task: SIGNAL, objective: PLASMA };
const SATELLITE_RING: Record<SatelliteKind, number> = { process: 0, task: 1, objective: 2 };
const MAX_SATELLITES = 24;
// Agent page: core floats above the hero text. Other pages: camera slides so the core rises into the top-right corner.
type Pose = { camera: [number, number, number]; look: [number, number, number] };
const POSES: Record<string, Pose> = { agent: { camera: [0, -1.2, 11.5], look: [0, -2.3, 0] } };
const DEFAULT_POSE: Pose = { camera: [-4.4, -2.4, 12], look: [-4.4, -3.3, 0] };
/** Half the sidebar width, so the core centres on the main column rather than the window. */
const sidebarShift = (width: number) => (width > 850 ? 118 : width > 600 ? 98 : 0);

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
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: 'low-power' });
    } catch {
      return; // No WebGL: the CSS gradient behind the canvas stays as the backdrop.
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    el.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(ABYSS, 0.04);
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 120);
    const disposables: { dispose(): void }[] = [];
    const track = <T extends { dispose(): void }>(item: T) => { disposables.push(item); return item; };

    // Core: faceted shell, glowing vertices, and an inner plasma body.
    const core = new THREE.Group();
    scene.add(core);
    const shellGeo = track(new THREE.IcosahedronGeometry(1.6, 1));
    const shellMat = track(new THREE.MeshBasicMaterial({ color: ION, wireframe: true, transparent: true, opacity: 0.5 }));
    core.add(new THREE.Mesh(shellGeo, shellMat));
    const vertexMat = track(new THREE.PointsMaterial({ color: ION, size: 0.08, transparent: true, opacity: 0.95,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    core.add(new THREE.Points(shellGeo, vertexMat));
    const innerMat = track(new THREE.MeshBasicMaterial({ color: PLASMA, transparent: true, opacity: 0.32,
      blending: THREE.AdditiveBlending, depthWrite: false }));
    const inner = new THREE.Mesh(track(new THREE.IcosahedronGeometry(0.85, 3)), innerMat);
    core.add(inner);
    const haloMat = track(new THREE.MeshBasicMaterial({ color: ION, transparent: true, opacity: 0.06,
      blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.BackSide }));
    core.add(new THREE.Mesh(track(new THREE.SphereGeometry(2.3, 32, 32)), haloMat));

    // Three tilted orbits: processes, tasks, objectives.
    const ringMat = track(new THREE.MeshBasicMaterial({ color: MIST, transparent: true, opacity: 0.1, side: THREE.DoubleSide }));
    const orbits = [2.7, 3.4, 4.1].map((radius, index) => {
      const orbit = new THREE.Group();
      orbit.rotation.set(Math.PI / 2 + (index - 1) * 0.38, index * 0.5, 0);
      orbit.add(new THREE.Mesh(track(new THREE.RingGeometry(radius - 0.006, radius + 0.006, 160)), ringMat));
      scene.add(orbit);
      return { group: orbit, radius, speed: 0.35 - index * 0.08 };
    });
    const satelliteGeo = track(new THREE.SphereGeometry(0.075, 16, 16));
    const satellites = Array.from({ length: MAX_SATELLITES }, () => {
      const mesh = new THREE.Mesh(satelliteGeo, track(new THREE.MeshBasicMaterial({ color: ION })));
      mesh.visible = false;
      return mesh;
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
    const stars = new THREE.Points(starGeo, track(new THREE.PointsMaterial({ color: MIST, size: 0.09, transparent: true, opacity: 0.55, depthWrite: false })));
    scene.add(stars);

    const clock = new THREE.Clock();
    const pointer = { x: 0, y: 0 };
    const cameraGoal = new THREE.Vector3();
    const lookAt = new THREE.Vector3();
    const lookGoal = new THREE.Vector3();
    const tint = new THREE.Color();
    const initialPose = POSES[live.current.page] ?? DEFAULT_POSE;
    camera.position.set(...initialPose.camera);
    lookAt.set(...initialPose.look);
    let raf = 0;

    function frame() {
      const s = live.current;
      const dt = Math.min(clock.getDelta(), 0.05);
      const t = clock.elapsedTime;
      const ease = reduced ? 1 : 1 - Math.pow(0.02, dt); // frame-rate independent smoothing
      const energy = s.connected ? 0.35 + s.load * 0.65 + (s.busy ? 0.7 : 0) : 0.1;

      core.rotation.y += dt * 0.3 * energy;
      core.rotation.x += dt * 0.07 * energy;
      inner.rotation.y -= dt * 0.5 * energy;
      inner.scale.setScalar(s.busy ? 1 + Math.sin(t * 4.2) * 0.07 : 1 + Math.sin(t * 1.1) * 0.025);
      tint.set(!s.connected ? SIGNAL : s.busy ? PLASMA : ION);
      shellMat.color.lerp(tint, ease);
      vertexMat.color.lerp(tint, ease);
      haloMat.color.lerp(tint, ease);
      haloMat.opacity += ((s.busy ? 0.14 : 0.06) - haloMat.opacity) * ease;

      const perRing = [0, 0, 0];
      satellites.forEach((mesh, index) => {
        const kind = s.satellites[index];
        if (!kind) { mesh.visible = false; return; }
        const ring = SATELLITE_RING[kind];
        const orbit = orbits[ring];
        if (mesh.parent !== orbit.group) orbit.group.add(mesh);
        (mesh.material as THREE.MeshBasicMaterial).color.setHex(SATELLITE_COLOR[kind]);
        const angle = perRing[ring]++ * 1.3 + t * orbit.speed * (0.6 + energy);
        mesh.position.set(Math.cos(angle) * orbit.radius, Math.sin(angle) * orbit.radius, 0);
        mesh.visible = true;
      });
      stars.rotation.y += dt * 0.008;

      const pose = POSES[s.page] ?? DEFAULT_POSE;
      cameraGoal.set(pose.camera[0] + pointer.x * 0.5, pose.camera[1] + pointer.y * 0.35, pose.camera[2]);
      lookGoal.set(...pose.look);
      camera.position.lerp(cameraGoal, ease * 0.6);
      lookAt.lerp(lookGoal, ease * 0.6);
      camera.lookAt(lookAt);
    }

    const loop = () => {
      raf = 0;
      frame();
      renderer.render(scene, camera);
      if (!reduced && !document.hidden) raf = requestAnimationFrame(loop);
    };
    wake.current = () => { if (!raf) raf = requestAnimationFrame(loop); };

    const resize = () => {
      const { clientWidth: width, clientHeight: height } = el;
      renderer.setSize(width, height);
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
    const onVisibility = () => { if (!document.hidden) { clock.getDelta(); wake.current(); } };
    if (!reduced) window.addEventListener('pointermove', onPointer);
    document.addEventListener('visibilitychange', onVisibility);
    resize();

    return () => {
      cancelAnimationFrame(raf);
      wake.current = () => {};
      observer.disconnect();
      window.removeEventListener('pointermove', onPointer);
      document.removeEventListener('visibilitychange', onVisibility);
      disposables.forEach(item => item.dispose());
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, []);

  // In reduced-motion mode nothing loops, so each state change renders one settled frame.
  useEffect(() => { wake.current(); }, [state]);

  return <div className="scene" ref={host} aria-hidden="true" />;
}
