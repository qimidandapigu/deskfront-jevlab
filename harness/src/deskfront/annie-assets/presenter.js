import * as THREE from 'three';
import { Character } from './packages/core/src/character.js';
import { analyseSamples, featureAt, MOUTH_LEAD } from './packages/core/src/lipsync.js';

const params = new URLSearchParams(location.search), session = params.get('session');
const canvas = document.getElementById('avatar'), status = document.getElementById('status');
const debug = { loaded: false, speaking: false, entryId: null, decision: null, mouthFrames: 0, renderedFrames: 0, errors: [] };
window.anniePresenter = debug;
const notify = message => window.chrome?.webview?.postMessage(message);
function fail(text) { status.textContent = text; debug.errors.push(text); notify({ action: 'error', error: text }); notify({ action: 'presentation', visible: false }); }
const api = async (action, post = false) => {
  const response = await fetch('/api/deskfront/annie/' + encodeURIComponent(session) + '/' + action,
    post ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' } : { cache: 'no-store' });
  if (!response.ok) throw Error('presenter-service-' + response.status);
  return response.json();
};

try {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2)); renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.setClearColor(0x000000, 0); renderer.shadowMap.enabled = false;
  const scene = new THREE.Scene();
  scene.add(new THREE.HemisphereLight(0xfff8ed, 0x76856b, 2.2));
  const key = new THREE.DirectionalLight(0xfff1dc, 2.5); key.position.set(-1, 2, 3); scene.add(key);
  const rim = new THREE.DirectionalLight(0xe3eacc, .7); rim.position.set(1, 1, -2); scene.add(rim);
  const camera = new THREE.PerspectiveCamera(29, innerWidth / innerHeight, .1, 30);
  camera.position.set(0, 1.22, 1.65); camera.lookAt(0, 1.22, 0);
  let nativeLayout = null;
  // A native portrait frame has explicit pixel dimensions. CSS viewport sizes
  // can lag DPR changes and are not the Win32 child dimensions at 125%/150%.
  const resize = () => {
    const width = nativeLayout?.width ?? innerWidth, height = nativeLayout?.height ?? innerHeight;
    renderer.setSize(width, height, false); camera.aspect = width / height; camera.updateProjectionMatrix();
  };
  resize(); addEventListener('resize', resize);
  const character = await Character.load({ url: new URL('./assets/avatars/annie-b/model.vrm', import.meta.url).href, scene, camera,
    hide: { materials: ['Tops_01_CLOTH'], springs: 'CoatSkirt' } });
  // Small conversational gestures, rather than counting/listing a report.
  character.talk?.sched?.setProfile("toy-child");
  debug.loaded = true; notify({ action: 'ready', avatar: 'annie-b', fpsLimit: 30 });
  let state = {}, decoded = null, track = null, loading = null, epoch = 0, lastDecision = null;
  let lastFrame = 0, lastPoll = 0, lastTelemetry = 0, lastSpeaking = false, stopped = false;
  let framePending = false, lastNativeFrame = 0;
  let pendingGesture = null, accentGesture = null, animationTime = 0, motionStart = null, transcriptEntry = null, transcriptLength = 0;
  // Bound the transparent native transport to one frame in flight. Backpressure
  // drops an old animation frame rather than queuing images behind live speech.
  window.chrome?.webview?.addEventListener('message', event => {
    if (event.data?.action === 'frame-presented') framePending = false;
    const layout = event.data;
    if (layout?.action === 'frame-layout' && Number.isSafeInteger(layout.revision) && layout.revision > 0
      && Number.isSafeInteger(layout.width) && layout.width > 0 && layout.width <= 2048
      && Number.isSafeInteger(layout.height) && layout.height > 0 && layout.height <= 2048
      && (!nativeLayout || layout.revision > nativeLayout.revision)) {
      nativeLayout = { revision: layout.revision, width: layout.width, height: layout.height }; resize();
    }
  });
  const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
  async function decodeAudio(id) {
    loading = id; const generation = ++epoch;
    try {
      const response = await fetch('/api/deskfront/annie/' + encodeURIComponent(session) + '/audio/' + encodeURIComponent(id));
      if (!response.ok) return;
      const context = new OfflineAudioContext(1, 1, 16000);
      const buffer = await context.decodeAudioData(await response.arrayBuffer());
      const mono = new Float32Array(buffer.length);
      for (let channel = 0; channel < buffer.numberOfChannels; channel++) {
        const data = buffer.getChannelData(channel); for (let i = 0; i < mono.length; i++) mono[i] += data[i] / buffer.numberOfChannels;
      }
      const features = analyseSamples(mono, buffer.sampleRate, 30);
      if (generation === epoch && state.entry?.id === id) { decoded = { id, duration: buffer.duration }; track = features; }
    } catch { if (generation === epoch) status.textContent = '口型音频暂不可用，解说仍在游戏中播放'; }
  }
  async function poll() {
    if (stopped) return;
    // Keep the cheap state poll alive while the child is parked offscreen,
    // so the next native subtitle can wake its portrait without rendering idle frames.
    try {
      state = await api('state'); lastPoll = performance.now();
      if (state.entry) {
        debug.entryId = state.entry.id;
        if (loading !== state.entry.id) { decoded = null; track = null; void decodeAudio(state.entry.id); }
      } else { epoch++; loading = null; decoded = null; track = null; debug.entryId = null; }
      const choice = state.decision;
      if (choice && choice.entryId === state.entry?.id && lastDecision !== choice.entryId) {
        lastDecision = choice.entryId; character.setFace(choice.face, 1); character.energy = choice.energy;
        pendingGesture = choice;
        accentGesture = choice;
        debug.decision = choice;
        notify({ action: 'decision', entryId: choice.entryId, face: choice.face, clip: choice.clip, accent: choice.accent, source: choice.source });
      }
      status.textContent = state.speaking ? '正在解说 · 与游戏声音同步' : state.status === 'model-unavailable' ? '动作模型暂不可用 · 正常待机' : state.status === 'budget' ? '本局动作额度用完 · 正常待机' : '正在看战况';
      notify({ action: 'presentation', visible: !!state.visible, entryId: debug.entryId,
        phase: state.phase, subtitleRect: state.placement?.subtitle_rect, viewportSize: state.placement?.viewport_size });
      if (!state.visible && lastSpeaking) {
        lastSpeaking = false; debug.speaking = false;
        notify({ action: 'playback', entryId: debug.entryId, speaking: false, audioDecoded: false,
          mouthOpen: 0, mouthFrames: debug.mouthFrames, renderedFrames: debug.renderedFrames });
      }
    } catch { state = {}; status.textContent = '等待 Harness 连接'; notify({ action: 'presentation', visible: false }); }
    setTimeout(poll, 400);
  }
  function frame(ms) {
    requestAnimationFrame(frame);
    const visible = !!state.visible && ms - lastPoll < 1600;
    document.body.dataset.speaking = String(visible);
    if (document.hidden || !visible || ms - lastFrame < 1000 / 30) return;
    const dt = Math.min(.06, lastFrame ? (ms - lastFrame) / 1000 : 1 / 30); lastFrame = ms;
    animationTime += dt; const t = animationTime;
    let feature = null;
    const speaking = !!state.speaking && ms - lastPoll < 1600;
    if (speaking && pendingGesture?.entryId === state.entry?.id) {
      const choice = pendingGesture; pendingGesture = null;
      const accepted = !reduced && choice.clip !== 'none' && character.playClip(choice.clip, { energy: choice.energy });
      motionStart = { entryId: choice.entryId, clip: choice.clip, t, before: character.head.quaternion.clone(), sampled: false };
      notify({ action: 'motion-started', entryId: choice.entryId, clip: choice.clip, accepted, naturalTalk: choice.clip === 'none', reducedMotion: reduced });
    }
    if (speaking && decoded?.id === state.entry?.id && state.playback) {
      const remaining = Math.max(0, state.playback.remaining_ms - (Date.now() - state.playback.updated_at));
      const cursor = Math.max(0, decoded.duration - remaining / 1000);
      feature = featureAt(track, cursor + MOUTH_LEAD);
      // Approximate text progress; actual audio onsets still time the hand strokes.
      // Do not feed the whole completed transcript before the first syllable.
      if (transcriptEntry !== state.entry.id) { transcriptEntry = state.entry.id; transcriptLength = 0; character.transcript('', t); }
      const text = state.entry.text;
      const length = Math.min(text.length, Math.ceil((cursor + .35) / decoded.duration * text.length));
      if (length > transcriptLength) { transcriptLength = length; character.transcript(text.slice(0, length), t); }
      if (accentGesture?.entryId === state.entry.id && cursor >= decoded.duration * .55) {
        const choice = accentGesture;
        if (!choice.accent || choice.accent === 'none' || choice.accent === choice.clip || remaining < 2200 || reduced) accentGesture = null;
        else if (character.current?.idle) {
          accentGesture = null;
          const accepted = character.playClip(choice.accent, { energy: choice.energy });
          motionStart = { entryId: choice.entryId, clip: choice.accent, t, before: character.head.quaternion.clone(), sampled: false };
          notify({ action: 'motion-started', entryId: choice.entryId, clip: choice.accent, slot: 'accent', accepted, reducedMotion: reduced });
        }
      }
    }
    const mouth = character.lips.update(feature, t, dt);
    character.setMouth(mouth, speaking && character.lips.speaking);
    character.hear(t, feature, false, 0); character.update(t, dt); renderer.render(scene, camera);
    if (motionStart && !motionStart.sampled && t - motionStart.t >= 1) {
      motionStart.sampled = true;
      notify({ action: 'motion-sampled', entryId: motionStart.entryId, requested: motionStart.clip, playing: character.current?.name,
        headAngleDegrees: motionStart.before.angleTo(character.head.quaternion) * 180 / Math.PI, talkLayerLoaded: !!character.talk });
    }
    if (window.chrome?.webview && nativeLayout && !framePending && ms - lastNativeFrame >= 50) {
      framePending = true; lastNativeFrame = ms;
      notify({ action: 'rgba-frame', png: canvas.toDataURL('image/png').split(',')[1], entryId: debug.entryId,
        renderSize: [nativeLayout.width, nativeLayout.height], layoutRevision: nativeLayout.revision });
    }
    debug.speaking = speaking; debug.renderedFrames++; if (mouth.open > .05) debug.mouthFrames++;
    if (speaking !== lastSpeaking || (speaking && ms - lastTelemetry >= 1000)) {
      lastTelemetry = ms; lastSpeaking = speaking;
      notify({ action: 'playback', entryId: debug.entryId, speaking, audioDecoded: !!decoded,
        mouthOpen: mouth.open, mouthFrames: debug.mouthFrames, renderedFrames: debug.renderedFrames,
        talkGesture: character.talk?.phrase?.name, talkGestureStats: character.talk?.sched?.stats });
    }
  }
  requestAnimationFrame(frame);
  if (session) { await api('start', true); void poll(); }
  else status.textContent = '接入对局后，人物随底部字幕出现';
  addEventListener('pagehide', () => { stopped = true; epoch++; renderer.dispose(); });
} catch (error) { fail('主播加载失败，可关闭后重开。' + String(error.message).slice(0, 70)); }
