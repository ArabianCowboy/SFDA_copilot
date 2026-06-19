/**
 * SFDA Copilot — Lightweight Particle Background System
 * 
 * Creates a constellation-style particle effect for the landing page.
 * Performance-optimized with requestAnimationFrame and canvas rendering.
 * Respects prefers-reduced-motion.
 *
 * @author SFDA Copilot Team
 * @version 1.0.0
 */

export class ParticleBackground {
  constructor(container, options = {}) {
    this.container = container;
    this.canvas = null;
    this.ctx = null;
    this.particles = [];
    this.animationId = null;
    this.isActive = false;
    this.mouse = { x: null, y: null };

    this.options = {
      particleCount: options.particleCount || 60,
      maxDistance: options.maxDistance || 120,
      particleSpeed: options.particleSpeed || 0.3,
      particleMinSize: options.particleMinSize || 1.5,
      particleMaxSize: options.particleMaxSize || 3,
      lineOpacity: options.lineOpacity || 0.15,
      particleOpacity: options.particleOpacity || 0.4,
      colors: options.colors || [
        'rgba(59, 130, 246, 0.55)',  /* blue */
        'rgba(96, 165, 250, 0.50)',  /* light blue */
        'rgba(100, 116, 139, 0.45)', /* slate-blue */
        'rgba(147, 197, 253, 0.35)', /* pale blue */
      ],
      mouseRadius: options.mouseRadius || 150,
      mouseForce: options.mouseForce || 0.02,
      fps: options.fps || 30,
    };

    this._lastFrameTime = 0;
    this._frameInterval = 1000 / this.options.fps;
    this._onMouseMove = this._onMouseMove.bind(this);
    this._onMouseLeave = this._onMouseLeave.bind(this);
    this._resize = this._resize.bind(this);
    this._animate = this._animate.bind(this);
  }

  init() {
    /* Respect reduced motion preference */
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

    this._createCanvas();
    this._createParticles();
    this._bindEvents();
    this.isActive = true;
    this._animate(0);
  }

  destroy() {
    this.isActive = false;
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
    this._unbindEvents();
    if (this.canvas && this.canvas.parentNode) {
      this.canvas.parentNode.removeChild(this.canvas);
    }
    this.particles = [];
    this.canvas = null;
    this.ctx = null;
  }

  _createCanvas() {
    this.canvas = document.createElement('canvas');
    this.canvas.style.cssText = `
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      z-index: 0;
    `;
    this.container.style.position = 'relative';
    this.container.insertBefore(this.canvas, this.container.firstChild);
    this.ctx = this.canvas.getContext('2d');
    this._resize();
  }

  _resize() {
    if (!this.canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = this.container.getBoundingClientRect();
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.canvas.style.width = `${rect.width}px`;
    this.canvas.style.height = `${rect.height}px`;
    this.ctx.scale(dpr, dpr);
    this.width = rect.width;
    this.height = rect.height;
  }

  _createParticles() {
    const { particleCount, particleMinSize, particleMaxSize, particleSpeed, colors } = this.options;
    this.particles = [];

    for (let i = 0; i < particleCount; i++) {
      this.particles.push({
        x: Math.random() * this.width,
        y: Math.random() * this.height,
        vx: (Math.random() - 0.5) * particleSpeed * 2,
        vy: (Math.random() - 0.5) * particleSpeed * 2,
        size: particleMinSize + Math.random() * (particleMaxSize - particleMinSize),
        color: colors[Math.floor(Math.random() * colors.length)],
        pulsePhase: Math.random() * Math.PI * 2,
        pulseSpeed: 0.005 + Math.random() * 0.01,
      });
    }
  }

  _bindEvents() {
    this.container.addEventListener('mousemove', this._onMouseMove, { passive: true });
    this.container.addEventListener('mouseleave', this._onMouseLeave, { passive: true });
    window.addEventListener('resize', this._resize, { passive: true });
  }

  _unbindEvents() {
    this.container.removeEventListener('mousemove', this._onMouseMove);
    this.container.removeEventListener('mouseleave', this._onMouseLeave);
    window.removeEventListener('resize', this._resize);
  }

  _onMouseMove(e) {
    const rect = this.container.getBoundingClientRect();
    this.mouse.x = e.clientX - rect.left;
    this.mouse.y = e.clientY - rect.top;
  }

  _onMouseLeave() {
    this.mouse.x = null;
    this.mouse.y = null;
  }

  _animate(timestamp) {
    if (!this.isActive) return;

    this.animationId = requestAnimationFrame(this._animate);

    const elapsed = timestamp - this._lastFrameTime;
    if (elapsed < this._frameInterval) return;
    this._lastFrameTime = timestamp - (elapsed % this._frameInterval);

    this.ctx.clearRect(0, 0, this.width, this.height);
    this._updateParticles();
    this._drawConnections();
    this._drawParticles();
  }

  _updateParticles() {
    const { maxDistance, mouseRadius, mouseForce } = this.options;

    for (const p of this.particles) {
      /* Mouse interaction */
      if (this.mouse.x !== null && this.mouse.y !== null) {
        const dx = this.mouse.x - p.x;
        const dy = this.mouse.y - p.y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < mouseRadius) {
          const force = (1 - dist / mouseRadius) * mouseForce;
          p.vx += dx * force;
          p.vy += dy * force;
        }
      }

      /* Damping */
      p.vx *= 0.99;
      p.vy *= 0.99;

      /* Move */
      p.x += p.vx;
      p.y += p.vy;

      /* Pulse */
      p.pulsePhase += p.pulseSpeed;

      /* Wrap around edges */
      if (p.x < -10) p.x = this.width + 10;
      if (p.x > this.width + 10) p.x = -10;
      if (p.y < -10) p.y = this.height + 10;
      if (p.y > this.height + 10) p.y = -10;
    }
  }

  _drawParticles() {
    for (const p of this.particles) {
      const pulse = Math.sin(p.pulsePhase) * 0.3 + 0.7;
      const size = p.size * pulse;

      this.ctx.beginPath();
      this.ctx.arc(p.x, p.y, size, 0, Math.PI * 2);
      this.ctx.fillStyle = p.color;
      this.ctx.fill();

      /* Subtle glow */
      this.ctx.beginPath();
      this.ctx.arc(p.x, p.y, size * 2.5, 0, Math.PI * 2);
      const gradient = this.ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, size * 2.5);
      gradient.addColorStop(0, p.color);
      gradient.addColorStop(1, 'transparent');
      this.ctx.fillStyle = gradient;
      this.ctx.fill();
    }
  }

  _drawConnections() {
    const { maxDistance, lineOpacity } = this.options;

    for (let i = 0; i < this.particles.length; i++) {
      for (let j = i + 1; j < this.particles.length; j++) {
        const dx = this.particles[i].x - this.particles[j].x;
        const dy = this.particles[i].y - this.particles[j].y;
        const dist = Math.sqrt(dx * dx + dy * dy);

        if (dist < maxDistance) {
          const opacity = (1 - dist / maxDistance) * lineOpacity;
          this.ctx.beginPath();
          this.ctx.moveTo(this.particles[i].x, this.particles[i].y);
          this.ctx.lineTo(this.particles[j].x, this.particles[j].y);
          this.ctx.strokeStyle = `rgba(59, 130, 246, ${opacity})`;
          this.ctx.lineWidth = 0.5;
          this.ctx.stroke();
        }
      }
    }
  }
}