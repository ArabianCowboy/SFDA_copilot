/**
 * SFDA Copilot — "Sunny" the mascot
 *
 * Single source of truth for the friendly companion robot. The SVG is generated
 * once here and mounted wherever a robot is needed (landing hero, chat companion
 * and inline chat avatars), removing the previous triple-duplication in the HTML.
 *
 * Visual language: teal body with a warm "sunrise" core — a glowing amber→coral
 * sun on the antenna and chest, expressive cyan eyes.
 *
 * State classes (idle / thinking / talking / happy / error) are toggled on the
 * wrapper elements and driven by robot.css.
 */

import { prefersReducedMotion } from './config.js';

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
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200" width="${size}" height="${size}"${idAttr} class="sunny-svg" role="img" aria-label="Sunny, the SFDA Copilot mascot">
    <defs>
      <linearGradient id="body-${u}" x1="0%" y1="0%" x2="100%" y2="100%">
        <stop offset="0%" stop-color="#14b8a6"/>
        <stop offset="100%" stop-color="#2dd4bf"/>
      </linearGradient>
      <linearGradient id="visor-${u}" x1="0%" y1="0%" x2="0%" y2="100%">
        <stop offset="0%" stop-color="#0b1120"/>
        <stop offset="100%" stop-color="#1e293b"/>
      </linearGradient>
      <radialGradient id="sun-${u}" cx="50%" cy="45%" r="60%">
        <stop offset="0%" stop-color="#fff7ed"/>
        <stop offset="45%" stop-color="#fbbf24"/>
        <stop offset="100%" stop-color="#fb7185"/>
      </radialGradient>
      <radialGradient id="sunglow-${u}" cx="50%" cy="50%" r="50%">
        <stop offset="0%" stop-color="#fbbf24" stop-opacity="0.75"/>
        <stop offset="100%" stop-color="#fb7185" stop-opacity="0"/>
      </radialGradient>
      <filter id="glow-${u}"><feGaussianBlur stdDeviation="2.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <filter id="soft-${u}" x="-30%" y="-30%" width="160%" height="160%"><feDropShadow dx="0" dy="5" stdDeviation="6" flood-color="#0f766e" flood-opacity="0.35"/></filter>
    </defs>

    <!-- Antenna with a little sun -->
    <g class="robot-antenna">
      <circle cx="100" cy="26" r="24" fill="url(#sunglow-${u})" class="antenna-glow" opacity="0"/>
      <rect x="97" y="40" width="6" height="20" rx="3" fill="#cbd5e1"/>
      <circle cx="100" cy="28" r="11" fill="url(#sun-${u})" class="antenna-ball" filter="url(#glow-${u})">
        <animate attributeName="r" values="10;12;10" dur="2.4s" repeatCount="indefinite"/>
      </circle>
    </g>

    <!-- Side ears / headphones -->
    <rect x="38" y="74" width="14" height="30" rx="7" fill="#cbd5e1"/>
    <rect x="148" y="74" width="14" height="30" rx="7" fill="#cbd5e1"/>

    <!-- Head -->
    <g class="robot-head">
      <rect x="50" y="50" width="100" height="78" rx="28" fill="url(#body-${u})" filter="url(#soft-${u})"/>
      <rect x="54" y="54" width="92" height="30" rx="22" fill="rgba(255,255,255,0.18)"/>
      <rect x="62" y="62" width="76" height="52" rx="20" fill="url(#visor-${u})" stroke="#334155" stroke-width="1.5"/>
      <g class="robot-eye-left">
        <ellipse cx="80" cy="86" rx="13" ry="13" fill="#5eead4" opacity="0.16" class="eye-glow"/>
        <circle cx="80" cy="86" r="7.5" fill="#5eead4" class="eye-pupil-left" filter="url(#glow-${u})">
          <animate attributeName="r" values="6.5;8;6.5" dur="3s" repeatCount="indefinite"/>
        </circle>
        <circle cx="82.5" cy="83.5" r="3" fill="#ffffff" opacity="0.95"/>
      </g>
      <g class="robot-eye-right">
        <ellipse cx="120" cy="86" rx="13" ry="13" fill="#5eead4" opacity="0.16" class="eye-glow"/>
        <circle cx="120" cy="86" r="7.5" fill="#5eead4" class="eye-pupil-right" filter="url(#glow-${u})">
          <animate attributeName="r" values="6.5;8;6.5" dur="3s" repeatCount="indefinite" begin="0.15s"/>
        </circle>
        <circle cx="122.5" cy="83.5" r="3" fill="#ffffff" opacity="0.95"/>
      </g>
      <g class="robot-blink-left" opacity="0"><rect x="70" y="82" width="20" height="8" rx="4" fill="#0b1120"/></g>
      <g class="robot-blink-right" opacity="0"><rect x="110" y="82" width="20" height="8" rx="4" fill="#0b1120"/></g>
      <path class="robot-mouth-idle" d="M 86 101 Q 100 112 114 101" fill="none" stroke="#fbbf24" stroke-width="3" stroke-linecap="round" filter="url(#glow-${u})"/>
      <ellipse class="robot-mouth-talk" cx="100" cy="104" rx="9" ry="7" fill="#fbbf24" opacity="0" filter="url(#glow-${u})"/>
      <circle cx="66" cy="100" r="6" fill="#fb7185" opacity="0.18" class="robot-cheek-left"/>
      <circle cx="134" cy="100" r="6" fill="#fb7185" opacity="0.18" class="robot-cheek-right"/>
    </g>

    <!-- Body with a glowing sun core -->
    <g class="robot-body">
      <rect x="92" y="126" width="16" height="10" rx="4" fill="#cbd5e1"/>
      <rect x="56" y="134" width="88" height="46" rx="20" fill="url(#body-${u})" filter="url(#soft-${u})"/>
      <rect x="60" y="138" width="80" height="18" rx="13" fill="rgba(255,255,255,0.14)"/>
      <circle cx="100" cy="158" r="11" fill="url(#sunglow-${u})" opacity="0.9"/>
      <circle cx="100" cy="158" r="7" fill="#0b1120" stroke="#fbbf24" stroke-width="2"/>
      <circle cx="100" cy="158" r="4" fill="url(#sun-${u})" class="chest-light" filter="url(#glow-${u})">
        <animate attributeName="opacity" values="0.65;1;0.65" dur="2.4s" repeatCount="indefinite"/>
      </circle>
    </g>

    <!-- Arms -->
    <g class="robot-arm-left"><rect x="32" y="140" width="26" height="12" rx="6" fill="#cbd5e1"/><circle cx="28" cy="146" r="7" fill="#cbd5e1"/></g>
    <g class="robot-arm-right"><rect x="142" y="140" width="26" height="12" rx="6" fill="#cbd5e1"/><circle cx="172" cy="146" r="7" fill="#cbd5e1"/></g>
  </svg>`;
}

/* ——————————————— ROBOT STATE MANAGER ——————————————— */

export const RobotStateManager = {
  _currentState: 'idle',
  _revertTimer: null,
  _thinkingTimeout: null,

  VALID_STATES: ['idle', 'thinking', 'talking', 'happy', 'error'],
  STATUS_MESSAGES: {
    idle: 'Ready to help',
    thinking: 'Processing your question...',
    talking: "Here's what I found",
    happy: 'Great question!',
    error: 'Something went wrong',
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
    if (status) status.textContent = this.STATUS_MESSAGES[state] || 'Ready to help';
  },

  /** User sent a message: celebrate, then drift into thinking. */
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
    if (landingStatus) landingStatus.textContent = 'See you in the chat! 🚀';

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

  _spawnReactionParticles() {
    this._getAvatars().forEach(avatar => this._spawnReactionAt(avatar));
  },

  /** Burst of warm sparks emitted from an element. */
  _spawnReactionAt(element) {
    if (!element) return;
    element.querySelector('.robot-reaction-particles')?.remove();

    const container = document.createElement('div');
    container.className = 'robot-reaction-particles';

    const dirs = [
      { px: '22px', py: '-28px' }, { px: '-20px', py: '-22px' },
      { px: '18px', py: '18px' }, { px: '-25px', py: '12px' },
      { px: '6px', py: '-32px' },
    ];

    dirs.forEach(dir => {
      const p = document.createElement('div');
      p.className = 'robot-reaction-particle';
      p.style.setProperty('--px', dir.px);
      p.style.setProperty('--py', dir.py);
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
  const status = document.getElementById('landing-robot-status');
  if (!body) return;

  let wiggleTimer = null;
  body.addEventListener('mouseenter', () => {
    if (RobotStateManager._currentState !== 'idle') return;
    clearTimeout(wiggleTimer);
    body.style.transition = 'transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
    body.style.transform = 'scale(1.12) translateY(-5px) rotate(4deg)';
    if (status) status.textContent = 'Wave! 👋';
    wiggleTimer = setTimeout(() => {
      body.style.transform = '';
      if (status) status.textContent = 'Hello! 👋';
    }, 2000);
  });
  body.addEventListener('mouseleave', () => {
    clearTimeout(wiggleTimer);
    body.style.transition = 'transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
    body.style.transform = '';
    if (status) status.textContent = 'Hello! 👋';
  });
  body.addEventListener('click', () => {
    if (RobotStateManager._currentState !== 'idle') return;
    body.style.transition = 'transform 0.15s ease';
    body.style.transform = 'scale(0.9)';
    setTimeout(() => {
      body.style.transition = 'transform 0.3s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
      body.style.transform = 'scale(1.1) translateY(-8px)';
      if (status) status.textContent = 'Click! ⚡';
      setTimeout(() => {
        body.style.transform = '';
        if (status) status.textContent = 'Hello! 👋';
      }, 800);
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
