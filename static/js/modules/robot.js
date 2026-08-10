/**
 * SFDA Copilot — "Sunny" the mascot
 *
 * Single source of truth for the friendly companion robot. The SVG is generated
 * once here and mounted wherever a robot is needed (landing hero, chat companion
 * and inline chat avatars), removing the previous triple-duplication in the HTML.
 *
 * Visual language: the Dossier signal blue for the shell and antenna, with the
 * confidence green in the eyes. Every colour is a CSS custom property on the
 * <svg>, so a state change is a token override rather than a set of per-class
 * fill rules — and the mascot follows the light/dark theme with no JS.
 *
 * Sunny is not decoration: its antenna pulses once per retrieved passage and
 * its status line reports the real retrieval stage, so the face is the
 * progress indicator.
 *
 * State classes (idle / searching / retrieved / thinking / talking / happy /
 * error) are toggled on the wrapper elements and driven by robot.css.
 */

import { prefersReducedMotion } from './config.js';
import { I18n } from './i18n.js';

let uidCounter = 0;

/**
 * Build the mascot SVG markup.
 * @param {object} opts
 * @param {number} [opts.size=180]  Rendered width/height in px.
 * @param {string} [opts.svgId]     Optional id for the <svg> (used for eye tracking).
 * @returns {string} SVG markup string.
 */
export function createRobot({ size = 180, svgId = '' } = {}) {
  const u = `sn${++uidCounter}`;
  const idAttr = svgId ? ` id="${svgId}"` : '';

  /* The --sunny-* palette lives in robot.css on .sunny-svg, NOT inline here.
     An inline style would set the properties on the <svg> itself, which beats
     any value inherited from a state class on an ancestor wrapper — so
     `.robot-searching { --sunny-eye: ... }` would silently never apply. */
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="${size}" height="${size}"${idAttr} class="sunny-svg" role="img" aria-label="Sunny, the SFDA Copilot mascot">
    <defs>
      <linearGradient id="body-${u}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="var(--sunny-shell)"/>
        <stop offset="100%" stop-color="var(--sunny-shell-deep)"/>
      </linearGradient>
      <linearGradient id="visor-${u}" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="var(--sunny-visor-top)"/>
        <stop offset="100%" stop-color="var(--sunny-visor-bottom)"/>
      </linearGradient>
      <radialGradient id="sun-${u}" cx="50%" cy="45%" r="60%">
        <stop offset="0%" stop-color="var(--sunny-core)"/>
        <stop offset="55%" stop-color="var(--sunny-signal)"/>
        <stop offset="100%" stop-color="var(--sunny-signal)"/>
      </radialGradient>
      <radialGradient id="sunglow-${u}" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="var(--sunny-signal)" stop-opacity="0.7"/>
        <stop offset="100%" stop-color="var(--sunny-signal)" stop-opacity="0"/>
      </radialGradient>
      <filter id="glow-${u}"><feGaussianBlur stdDeviation="2.2" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>

    <!-- Flat ground shadow. A drop-shadow filter on every robot on the page is
         a per-frame blur; an ellipse is free and reads the same at this size. -->
    <ellipse class="robot-ground" cx="100" cy="186" rx="42" ry="6" fill="var(--sunny-ink)" opacity="0.10"/>

    <!-- Antenna: the retrieval indicator. Pulses once per passage found. -->
    <g class="robot-antenna">
      <circle cx="100" cy="26" r="24" fill="url(#sunglow-${u})" class="antenna-glow" opacity="0"/>
      <rect x="97" y="40" width="6" height="20" rx="3" fill="var(--sunny-chrome)"/>
      <circle cx="100" cy="28" r="11" fill="url(#sun-${u})" class="antenna-ball" filter="url(#glow-${u})"/>
    </g>

    <!-- Side ears / headphones -->
    <rect x="38" y="74" width="14" height="30" rx="7" fill="var(--sunny-chrome)"/>
    <rect x="148" y="74" width="14" height="30" rx="7" fill="var(--sunny-chrome)"/>

    <!-- Head -->
    <g class="robot-head">
      <rect x="50" y="50" width="100" height="78" rx="28" fill="url(#body-${u})"
            stroke="var(--sunny-shell-deep)" stroke-width="1"/>
      <rect x="54" y="54" width="92" height="30" rx="22" fill="var(--sunny-core)" opacity="0.14"/>
      <rect x="62" y="62" width="76" height="52" rx="20" fill="url(#visor-${u})"
            stroke="var(--sunny-shell-deep)" stroke-width="1.5"/>
      <g class="robot-eye-left">
        <ellipse cx="80" cy="86" rx="13" ry="13" fill="var(--sunny-eye)" opacity="0.16" class="eye-glow"/>
        <circle cx="80" cy="86" r="7.5" fill="var(--sunny-eye)" class="eye-pupil-left" filter="url(#glow-${u})"/>
        <circle cx="82.5" cy="83.5" r="3" fill="var(--sunny-core)" opacity="0.95"/>
      </g>
      <g class="robot-eye-right">
        <ellipse cx="120" cy="86" rx="13" ry="13" fill="var(--sunny-eye)" opacity="0.16" class="eye-glow"/>
        <circle cx="120" cy="86" r="7.5" fill="var(--sunny-eye)" class="eye-pupil-right" filter="url(#glow-${u})"/>
        <circle cx="122.5" cy="83.5" r="3" fill="var(--sunny-core)" opacity="0.95"/>
      </g>
      <g class="robot-blink-left" opacity="0"><rect x="70" y="82" width="20" height="8" rx="4" fill="var(--sunny-visor-top)"/></g>
      <g class="robot-blink-right" opacity="0"><rect x="110" y="82" width="20" height="8" rx="4" fill="var(--sunny-visor-top)"/></g>
      <path class="robot-mouth-idle" d="M 86 101 Q 100 112 114 101" fill="none" stroke="var(--sunny-mouth)" stroke-width="3" stroke-linecap="round"/>
      <ellipse class="robot-mouth-talk" cx="100" cy="104" rx="9" ry="7" fill="var(--sunny-mouth)" opacity="0"/>
      <circle cx="66" cy="100" r="6" fill="var(--sunny-cheek)" opacity="0.5" class="robot-cheek-left"/>
      <circle cx="134" cy="100" r="6" fill="var(--sunny-cheek)" opacity="0.5" class="robot-cheek-right"/>
    </g>

    <!-- Body -->
    <g class="robot-body">
      <rect x="92" y="126" width="16" height="10" rx="4" fill="var(--sunny-chrome)"/>
      <rect x="56" y="134" width="88" height="46" rx="20" fill="url(#body-${u})"
            stroke="var(--sunny-shell-deep)" stroke-width="1"/>
      <rect x="60" y="138" width="80" height="18" rx="13" fill="var(--sunny-core)" opacity="0.12"/>
      <circle cx="100" cy="158" r="11" fill="url(#sunglow-${u})" opacity="0.9"/>
      <circle cx="100" cy="158" r="7" fill="var(--sunny-visor-top)" stroke="var(--sunny-signal)" stroke-width="2"/>
      <circle cx="100" cy="158" r="4" fill="url(#sun-${u})" class="chest-light" filter="url(#glow-${u})"/>
    </g>

    <!-- Arms -->
    <g class="robot-arm-left"><rect x="32" y="140" width="26" height="12" rx="6" fill="var(--sunny-chrome)"/><circle cx="28" cy="146" r="7" fill="var(--sunny-chrome)"/></g>
    <g class="robot-arm-right"><rect x="142" y="140" width="26" height="12" rx="6" fill="var(--sunny-chrome)"/><circle cx="172" cy="146" r="7" fill="var(--sunny-chrome)"/></g>
  </svg>`;
}

/* ——————————————— ROBOT STATE MANAGER ——————————————— */

export const RobotStateManager = {
  _currentState: 'idle',
  _revertTimer: null,
  _thinkingTimeout: null,

  VALID_STATES: ['idle', 'thinking', 'talking', 'happy', 'error', 'searching', 'retrieved'],
  /* Keys, not literals — resolved at use so a language switch is picked up. */
  STATUS_KEYS: {
    idle: 'robot.idle',
    thinking: 'robot.thinking',
    talking: 'robot.talking',
    happy: 'robot.happy',
    error: 'robot.error',
    searching: 'robot.searching',
    retrieved: 'robot.retrieved',
  },

  _getAvatars() {
    return document.querySelectorAll('.robot-avatar-wrapper');
  },

  _getCompanionBody() {
    return document.getElementById('robot-companion-body');
  },

  _getStatusText() {
    return document.getElementById('robot-status-text');
  },

  _cancelRevert() {
    if (this._revertTimer) {
      clearTimeout(this._revertTimer);
      this._revertTimer = null;
    }
  },

  _scheduleRevert(delayMs) {
    this._cancelRevert();
    this._revertTimer = setTimeout(() => {
      if (this._currentState !== 'idle') this.setState('idle');
    }, delayMs);
  },

  /** Apply an animation state to every robot on the page. */
  setState(state) {
    if (!this.VALID_STATES.includes(state)) return;

    this._currentState = state;
    this._cancelRevert();

    const states = this.VALID_STATES;

    this._getAvatars().forEach(avatar => {
      states.forEach(s => avatar.classList.remove(`robot-${s}`));
      avatar.classList.add(`robot-${state}`);
    });

    const body = this._getCompanionBody();
    if (body) {
      states.forEach(s => body.classList.remove(`robot-${s}`));
      body.classList.add(`robot-${state}`);
    }

    const status = this._getStatusText();
    if (status) status.textContent = I18n.t(this.STATUS_KEYS[state] || 'robot.idle');
  },

  /** User sent a message: celebrate, then drift into thinking.
   *  Under streaming the real `stage` events take over almost immediately, so
   *  the timer below is only a fallback for the blocking path. */
  reactToUser() {
    this.setState('happy');
    this._spawnReactionParticles();
    this._scheduleRevert(1500);

    this._thinkingTimeout = setTimeout(() => {
      if (this._currentState === 'happy' || this._currentState === 'idle') {
        this.setState('thinking');
      }
    }, 800);
  },

  /**
   * Drive the mascot from real server progress rather than a blind timer.
   * This is the whole argument for keeping Sunny: it reports actual work.
   */
  onStage(stage, data = {}) {
    if (this._thinkingTimeout) {
      clearTimeout(this._thinkingTimeout);
      this._thinkingTimeout = null;
    }
    this._cancelRevert();

    switch (stage) {
      case 'searching':
        this.setState('searching');
        break;
      case 'retrieved':
        this.setState('retrieved');
        this._pulseAntenna(data.count || 0);
        this._setStatus(I18n.plural(data.count, 'robot.foundPassage', 'robot.foundPassages'));
        break;
      case 'drafting':
        this.setState('thinking');
        this._setStatus(I18n.t('robot.draftingStatus'));
        break;
      case 'finalizing':
        this._setStatus(I18n.t('robot.finalizingStatus'));
        break;
      default:
        break;
    }
  },

  _setStatus(text) {
    const status = this._getStatusText();
    if (status) status.textContent = text;
  },

  /** One antenna flash per retrieved passage, capped so eight doesn't strobe. */
  /**
   * Sources opened or closed.
   *
   * Deliberately NOT a VALID_STATE. The state machine is driven by the stream
   * — searching, retrieved, drafting — and a reader can open the panel at any
   * point during it; making this a state would clobber whatever stage Sunny
   * was reporting. It layers on top instead, so he can be mid-search and
   * presenting at once.
   *
   * While the evidence is on screen his eyes take the provenance colour. Teal
   * means "this came from a document" everywhere else in the transcript, so
   * his face reports what the reader is looking at rather than decorating it.
   */
  presentSources(isOpen) {
    const body = this._getCompanionBody();
    if (!body) return;

    body.classList.toggle('robot-presenting', !!isOpen);
    if (!isOpen || prefersReducedMotion()) return;

    // One dip toward the shelf, then back. Restarted by hand so opening a
    // second answer's sources plays it again rather than sitting finished.
    this._pulseAntenna(1);
    body.classList.remove('robot-presents');
    void body.offsetWidth;
    body.classList.add('robot-presents');
    clearTimeout(this._presentTimer);
    this._presentTimer = setTimeout(() => body.classList.remove('robot-presents'), 700);
  },

  _pulseAntenna(count) {
    if (prefersReducedMotion() || count <= 0) return;
    const balls = document.querySelectorAll('.antenna-ball');
    const flashes = Math.min(count, 8);

    for (let i = 0; i < flashes; i++) {
      setTimeout(() => {
        balls.forEach(ball => {
          ball.classList.remove('antenna-flash');
          void ball.offsetWidth;      // restart the animation
          ball.classList.add('antenna-flash');
        });
      }, i * 70);
    }
  },

  startThinking() {
    if (this._thinkingTimeout) {
      clearTimeout(this._thinkingTimeout);
      this._thinkingTimeout = null;
    }
    this.setState('thinking');
  },

  startTalking() {
    this.setState('talking');
  },

  showError() {
    this.setState('error');
    this._scheduleRevert(2000);
  },

  returnToIdle(delayMs = 3000) {
    if (this._currentState === 'talking' || this._currentState === 'thinking') {
      this._scheduleRevert(delayMs);
    }
  },

  /** Cancel pending reactions and restore the neutral state immediately. */
  resetToIdle() {
    if (this._thinkingTimeout) {
      clearTimeout(this._thinkingTimeout);
      this._thinkingTimeout = null;
    }
    this.setState('idle');
  },

  /** Public reaction API for view coordinators and interaction handlers. */
  celebrate(element = null) {
    if (element) {
      this._spawnReactionAt(element);
      return;
    }
    this._spawnReactionParticles();
  },

  /** Animate the landing robot out and the chat companion into view. */
  transitionToAuthenticatedView() {
    const landingRobot = document.getElementById('landing-robot');
    const landingBody = document.getElementById('landing-robot-body');
    const landingStatus = document.getElementById('landing-robot-status');
    const companionBody = document.getElementById('robot-companion-body');
    const companion = document.getElementById('robot-companion');

    if (landingRobot) {
      landingRobot.classList.add('robot-exit');
      this.celebrate(landingBody);
    }
    if (landingStatus) landingStatus.textContent = I18n.t('robot.farewell');

    setTimeout(() => {
      if (companionBody) {
        companionBody.style.animation = 'none';
        companionBody.offsetHeight; /* force reflow */
        companionBody.style.animation = 'robotCompanionEntrance 1.2s cubic-bezier(0.25, 0.46, 0.45, 0.94) both';
        companionBody.classList.add('robot-entrance');
      }
      if (companion) companion.style.opacity = '1';
      this.celebrate();
    }, 600);
  },

  /** Bring the landing mascot back when the reader logs out.
   *
   * This exists because .robot-exit animates with `forwards`, so its final
   * frame (opacity 0, 160px up, 40% scale) PERSISTS. Nothing on the logout
   * path used to clear it, so Sunny was still on stage — just invisible and
   * off-position — every time the landing came back. Four states were stuck:
   * the exit class, the farewell status text, the eye-tracking guard that
   * keys off that same class, and any inline transform left by a hover.
   * All four are cleared here, in one place, so the landing view can never
   * again be shown with the mascot mid-exit.
   */
  transitionToUnauthenticatedView() {
    const landingRobot = document.getElementById('landing-robot');
    const landingBody = document.getElementById('landing-robot-body');
    const landingStatus = document.getElementById('landing-robot-status');
    const companion = document.getElementById('robot-companion');
    const companionBody = document.getElementById('robot-companion-body');

    /* Park the companion so its entrance replays cleanly on the next login
       rather than being stuck at the end of its own `both` animation. */
    if (companion) companion.style.opacity = '';
    if (companionBody) {
      companionBody.style.animation = '';
      companionBody.classList.remove('robot-entrance');
    }

    this.setState('idle');

    if (!landingRobot) return;

    /* Hover handlers write inline transforms; a logout mid-hover would
       otherwise leave Sunny frozen scaled-up under the return animation. */
    if (landingBody) {
      landingBody.style.transition = '';
      landingBody.style.transform = '';
    }
    if (landingStatus && landingStatus.dataset.greeting) {
      landingStatus.textContent = landingStatus.dataset.greeting;
    }

    landingRobot.classList.remove('robot-exit', 'robot-return');

    if (prefersReducedMotion()) return;

    /* Force a reflow between removing and re-adding, or the browser
       coalesces both mutations and the animation never restarts. */
    void landingRobot.offsetWidth;
    landingRobot.classList.add('robot-return');
    landingRobot.addEventListener(
      'animationend',
      () => landingRobot.classList.remove('robot-return'),
      { once: true },
    );
  },

  _spawnReactionParticles() {
    this._getAvatars().forEach(avatar => this._spawnReactionAt(avatar));
  },

  /** Burst of warm sparks emitted from an element. */
  _spawnReactionAt(element) {
    if (!element) return;
    element.querySelector('.robot-reaction-particles')?.remove();

    const container = document.createElement('div');
    container.className = 'robot-reaction-particles';

    /* Horizontal offsets are mirrored under RTL so the burst still fans away
       from the mascot rather than into it. */
    const flip = getComputedStyle(document.documentElement).direction === 'rtl' ? -1 : 1;
    const dirs = [
      { px: 22, py: -28 }, { px: -20, py: -22 },
      { px: 18, py: 18 }, { px: -25, py: 12 },
      { px: 6, py: -32 },
    ];

    dirs.forEach(dir => {
      const p = document.createElement('div');
      p.className = 'robot-reaction-particle';
      p.style.setProperty('--px', `${dir.px * flip}px`);
      p.style.setProperty('--py', `${dir.py}px`);
      container.appendChild(p);
    });

    element.appendChild(container);
    setTimeout(() => container.remove(), 1000);
  },

  /** Inline avatar markup used inside bot chat bubbles. */
  createAvatarHTML(size = 42) {
    return `<div class="robot-avatar-wrapper robot-idle">${createRobot({ size })}</div>`;
  },
};

/* ——————————————— MOUNTING + INTERACTIVITY ——————————————— */

/** Inject the landing + companion robots into their mount points. */
export function mountRobots() {
  const landingBody = document.getElementById('landing-robot-body');
  if (landingBody && !landingBody.dataset.mounted) {
    landingBody.innerHTML = createRobot({ size: 120, svgId: 'landing-robot-svg' });
    landingBody.dataset.mounted = 'true';
  }

  const companionBody = document.getElementById('robot-companion-body');
  if (companionBody && !companionBody.dataset.mounted) {
    companionBody.innerHTML = createRobot({ size: 180, svgId: 'robot-main-svg' });
    companionBody.dataset.mounted = 'true';
  }

  /* The greeting is a server-rendered page.* string, which never reaches
     window.__I18N, so JS cannot look it up. Stash the rendered text once and
     restore from it — that keeps the reset correct in both languages. */
  const landingStatus = document.getElementById('landing-robot-status');
  if (landingStatus && !landingStatus.dataset.greeting) {
    landingStatus.dataset.greeting = landingStatus.textContent.trim();
  }

  const welcomeAvatar = document.getElementById('welcome-robot-avatar');
  if (welcomeAvatar && !welcomeAvatar.dataset.mounted) {
    welcomeAvatar.innerHTML = createRobot({ size: 42 });
    welcomeAvatar.classList.add('robot-idle');
    welcomeAvatar.dataset.mounted = 'true';
  }
}

/** Eye tracking: move a pair of pupils toward the cursor. */
function trackPupils(svg, { baseLeft = 80, baseRight = 120, baseY = 86, max = 4, guard } = {}) {
  if (prefersReducedMotion()) return;
  const leftPupil = svg.querySelector('.eye-pupil-left');
  const rightPupil = svg.querySelector('.eye-pupil-right');
  if (!leftPupil || !rightPupil) return;

  document.addEventListener('mousemove', (e) => {
    if (guard && guard()) return;
    const rect = svg.getBoundingClientRect();
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height * 0.43;
    const dx = e.clientX - cx;
    const dy = e.clientY - cy;
    const dist = Math.sqrt(dx * dx + dy * dy) || 1;
    const mx = (dx / dist) * Math.min(max, dist * 0.03);
    const my = (dy / dist) * Math.min(max, dist * 0.03);
    leftPupil.setAttribute('cx', baseLeft + mx);
    leftPupil.setAttribute('cy', baseY + my);
    rightPupil.setAttribute('cx', baseRight + mx);
    rightPupil.setAttribute('cy', baseY + my);
  });
}

/** Landing hero robot: eye tracking + playful hover/click reactions. */
export function initLandingRobot() {
  const svg = document.getElementById('landing-robot-svg');
  if (!svg) return;

  trackPupils(svg, {
    max: 6,
    guard: () => document.getElementById('landing-robot')?.classList.contains('robot-exit'),
  });

  const body = document.getElementById('landing-robot-body');
  if (!body) return;

  /* The reaction is physical only. These handlers used to write 'Wave! 👋',
     'Hello! 👋' and 'Click! ⚡' as hardcoded English literals, which showed
     English to Arabic readers and permanently overwrote the localized
     greeting. Motion carries the personality; the status line keeps saying
     the one true thing it was rendered with. */
  let wiggleTimer = null;
  body.addEventListener('mouseenter', () => {
    if (RobotStateManager._currentState !== 'idle') return;
    clearTimeout(wiggleTimer);
    body.style.transition = 'transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
    body.style.transform = 'scale(1.08) translateY(-5px) rotate(3deg)';
    wiggleTimer = setTimeout(() => { body.style.transform = ''; }, 2000);
  });
  body.addEventListener('mouseleave', () => {
    clearTimeout(wiggleTimer);
    body.style.transition = 'transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
    body.style.transform = '';
  });
  body.addEventListener('click', () => {
    if (RobotStateManager._currentState !== 'idle') return;
    body.style.transition = 'transform 0.15s ease';
    body.style.transform = 'scale(0.92)';
    setTimeout(() => {
      body.style.transition = 'transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
      body.style.transform = 'scale(1.08) translateY(-8px)';
      setTimeout(() => { body.style.transform = ''; }, 800);
    }, 150);
    RobotStateManager.celebrate(body);
  });
}

/* ——————————————— LARGE CHAT COMPANION ——————————————— */

export const RobotCompanion = {
  _eyeTrackingActive: false,
  _idleInterval: null,

  init() {
    this.initEyeTracking();
    this.initIdleBehaviors();
    this.initHoverInteraction();
  },

  initEyeTracking() {
    const svg = document.getElementById('robot-main-svg');
    if (!svg) return;
    this._eyeTrackingActive = true;
    trackPupils(svg, { max: 3, guard: () => !this._eyeTrackingActive });
  },

  initIdleBehaviors() {
    if (prefersReducedMotion()) return;

    const body = document.getElementById('robot-companion-body');
    if (!body) return;

    const behaviors = [
      () => {
        body.style.transition = 'transform 0.5s ease';
        body.style.transform = 'rotate(-3deg) translateY(-5px)';
        setTimeout(() => { body.style.transform = ''; }, 1500);
      },
      () => {
        body.style.transition = 'transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
        body.style.transform = 'scale(1.05) translateY(-8px)';
        setTimeout(() => { body.style.transform = ''; }, 800);
      },
    ];

    const scheduleNext = () => {
      const delay = 5000 + Math.random() * 3000;
      this._idleInterval = setTimeout(() => {
        if (RobotStateManager._currentState === 'idle') {
          behaviors[Math.floor(Math.random() * behaviors.length)]();
        }
        scheduleNext();
      }, delay);
    };

    scheduleNext();
  },

  initHoverInteraction() {
    const body = document.getElementById('robot-companion-body');
    if (!body) return;

    body.addEventListener('mouseenter', () => {
      if (RobotStateManager._currentState === 'idle') {
        body.style.transition = 'transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
        body.style.transform = 'scale(1.08) translateY(-10px) rotate(2deg)';
      }
    });
    body.addEventListener('mouseleave', () => {
      body.style.transition = 'transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
      body.style.transform = '';
    });
    body.addEventListener('click', () => {
      body.style.transition = 'transform 0.15s ease';
      body.style.transform = 'scale(0.95)';
      setTimeout(() => {
        body.style.transition = 'transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
        body.style.transform = 'scale(1.05) translateY(-8px)';
        setTimeout(() => { body.style.transform = ''; }, 500);
      }, 150);
      RobotStateManager.celebrate(body);
    });
  },

  destroy() {
    if (this._idleInterval) clearTimeout(this._idleInterval);
    this._eyeTrackingActive = false;
  },
};
