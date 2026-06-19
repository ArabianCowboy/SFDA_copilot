/**
 * SFDA Copilot — Cinematic effects
 * Particle background, scroll/mouse parallax, feature-card reveal + 3D tilt,
 * and button ripples. All effects bail out under `prefers-reduced-motion`.
 */

import { CONFIG, prefersReducedMotion } from './config.js';
import { DOMCache } from './dom.js';
import { AppState } from './state.js';
import { Utils } from './utils.js';
import { ParticleBackground } from '../particles.js';

export const Effects = {
  _particleInstance: null,

  initParticles() {
    if (prefersReducedMotion()) return;

    const container = DOMCache.get(CONFIG.SELECTORS.PARTICLES_CONTAINER);
    if (!container) return;

    this._particleInstance?.destroy();

    this._particleInstance = new ParticleBackground(container, {
      particleCount: window.innerWidth < 768 ? 30 : 50,
      maxDistance: 100,
      particleSpeed: 0.25,
      fps: 24,
    });
    this._particleInstance.init();
    AppState.set('particleBackground', this._particleInstance);
  },

  initCardAnimations() {
    const cards = DOMCache.getAll(`.${CONFIG.CLASSES.ANIMATE_CARD}`);
    if (!cards.length) return;

    if (prefersReducedMotion()) {
      cards.forEach(card => card.classList.add(CONFIG.CLASSES.REVEALED));
      return;
    }

    const observer = new IntersectionObserver(
      (entries, obs) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            const delay = parseInt(entry.target.dataset.delay || '0', 10);
            setTimeout(() => entry.target.classList.add(CONFIG.CLASSES.REVEALED), delay);
            obs.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.1, rootMargin: '0px 0px -50px 0px' }
    );

    cards.forEach(card => observer.observe(card));
    this.initCardTilt3D(cards);
  },

  initCardTilt3D(cards) {
    if (prefersReducedMotion()) return;

    cards.forEach(card => {
      card.addEventListener('mousemove', (e) => {
        const rect = card.getBoundingClientRect();
        const mouseX = e.clientX - (rect.left + rect.width / 2);
        const mouseY = e.clientY - (rect.top + rect.height / 2);

        const rotateX = -(mouseY / rect.height) * 10;
        const rotateY = (mouseX / rect.width) * 10;

        card.style.transform = `perspective(800px) rotateX(${rotateX}deg) rotateY(${rotateY}deg) scale(1.03) translateZ(10px)`;
        card.style.transition = 'transform 0.1s ease-out';

        const glowX = ((e.clientX - rect.left) / rect.width) * 100;
        const glowY = ((e.clientY - rect.top) / rect.height) * 100;
        card.style.background = `radial-gradient(circle at ${glowX}% ${glowY}%, rgba(var(--accent-warm-rgb) / 0.12) 0%, transparent 55%), var(--glass-bg)`;
      });

      card.addEventListener('mouseleave', () => {
        card.style.transform = 'perspective(800px) rotateX(0) rotateY(0) scale(1) translateZ(0)';
        card.style.transition = 'transform 0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
        card.style.background = '';
      });
    });
  },

  initHeroParallax() {
    if (prefersReducedMotion()) return;

    const hero = document.querySelector('.landing-hero');
    const heroImage = document.querySelector('.hero-visual img');
    const orbs = document.querySelectorAll('.hero-floating-orb');

    if (heroImage) {
      let rafId = null;
      window.addEventListener('scroll', () => {
        if (rafId) return;
        rafId = requestAnimationFrame(() => {
          const scrolled = window.pageYOffset;
          heroImage.style.transform = `translateY(${scrolled * 0.04}px)`;
          orbs.forEach((orb, i) => {
            orb.style.transform = `translateY(${scrolled * (0.02 + i * 0.01)}px)`;
          });
          rafId = null;
        });
      }, { passive: true });
    }

    if (hero) {
      hero.addEventListener('mousemove', (e) => {
        const rect = hero.getBoundingClientRect();
        const mouseX = (e.clientX - rect.left) / rect.width - 0.5;
        const mouseY = (e.clientY - rect.top) / rect.height - 0.5;
        hero.style.transform = `perspective(1200px) rotateY(${mouseX * 3}deg) rotateX(${-mouseY * 3}deg)`;
        orbs.forEach((orb, i) => {
          const strength = 5 + i * 3;
          orb.style.transform = `translate(${mouseX * strength}px, ${mouseY * strength}px)`;
        });
      });

      hero.addEventListener('mouseleave', () => {
        hero.style.transform = 'perspective(1200px) rotateY(0) rotateX(0)';
        hero.style.transition = 'transform 0.8s cubic-bezier(0.25, 0.46, 0.45, 0.94)';
        orbs.forEach(orb => { orb.style.transform = ''; });
        setTimeout(() => { hero.style.transition = ''; }, 800);
      });
    }
  },

  initButtonRipples() {
    document.addEventListener('click', (e) => {
      const button = e.target.closest('.unified-button, #send-button, .faq-button, .suggested-question-enhanced');
      if (button) Utils.addRippleEffect(button, e);
    });
  },
};
