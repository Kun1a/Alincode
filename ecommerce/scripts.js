/* ================================================================
   脑力研究所 — Brainwave Canvas + Scroll Animations
   ================================================================ */

document.addEventListener("DOMContentLoaded", () => {

  /* --------------------------------------------------------------
     BRAINWAVE CANVAS
     -------------------------------------------------------------- */
  const canvas = document.getElementById("brainwave");
  if (canvas) {
    initBrainwave(canvas);
  }

  function initBrainwave(canvas) {
    const ctx = canvas.getContext("2d");
    const hero = document.getElementById("hero");
    let w, h, centerY;
    let time = 0;
    let rafId = null;

    // Wave configuration: each has [amplitude, frequency, speed, color, lineWidth]
    const waves = [
      { amp: 38, freq: 0.018, speed: 0.006, color: "#7C5CFC", lw: 2.5 },
      { amp: 24, freq: 0.032, speed: 0.009, color: "#00D4AA", lw: 1.8 },
      { amp: 14, freq: 0.048, speed: 0.013, color: "rgba(124, 92, 252, 0.3)", lw: 1.2 },
    ];

    function resize() {
      const rect = hero.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      w = rect.width;
      h = rect.height;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + "px";
      canvas.style.height = h + "px";
      ctx.scale(dpr, dpr);
      centerY = h * 0.55;
    }

    function draw() {
      ctx.clearRect(0, 0, w, h);

      // Draw each wave
      const sw = 1; // stagger offset between waves for visual depth
      waves.forEach((wave, idx) => {
        ctx.beginPath();
        // Start slightly off-screen to avoid edge clipping
        const startX = -4;
        ctx.moveTo(startX, centerY + Math.sin(startX * wave.freq + time * wave.speed + idx * sw) * wave.amp);

        for (let x = 0; x <= w + 4; x += 1) {
          const phase = x * wave.freq + time * wave.speed + idx * sw;
          const harmonic = Math.sin(phase * 2.3) * wave.amp * 0.25;
          const envelope = 1 - Math.abs((x / w) * 2 - 1) * 0.15; // slightly dip at edges
          const y = centerY + (Math.sin(phase) * wave.amp + harmonic) * envelope;

          ctx.lineTo(x, y);
        }

        ctx.strokeStyle = wave.color;
        ctx.lineWidth = wave.lw;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.stroke();
      });

      // Draw subtle glow under the main wave
      ctx.beginPath();
      const baseWave = waves[0];
      for (let x = 0; x <= w; x += 2) {
        const y = centerY + Math.sin(x * baseWave.freq + time * baseWave.speed) * baseWave.amp;
        x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
      }
      ctx.strokeStyle = "rgba(124, 92, 252, 0.06)";
      ctx.lineWidth = 40;
      ctx.stroke();

      time++;
      rafId = requestAnimationFrame(draw);
    }

    resize();
    draw();

    // Debounced resize handler
    let resizeTimer;
    window.addEventListener("resize", () => {
      cancelAnimationFrame(rafId);
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        resize();
        draw();
      }, 100);
    });

    // Cleanup on page unload (optional but good practice)
    window.addEventListener("beforeunload", () => {
      if (rafId) cancelAnimationFrame(rafId);
    });
  }

  /* --------------------------------------------------------------
     NAVIGATION — scrolled state
     -------------------------------------------------------------- */
  const nav = document.querySelector(".nav");
  if (nav) {
    let ticking = false;
    window.addEventListener("scroll", () => {
      if (!ticking) {
        requestAnimationFrame(() => {
          nav.classList.toggle("nav--scrolled", window.scrollY > 20);
          ticking = false;
        });
        ticking = true;
      }
    });
  }

  /* --------------------------------------------------------------
     SCROLL REVEAL — Intersection Observer
     -------------------------------------------------------------- */
  const revealElements = document.querySelectorAll("[data-reveal]");
  if (revealElements.length > 0) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("revealed");
            observer.unobserve(entry.target);
          }
        });
      },
      {
        threshold: 0.12,
        rootMargin: "0px 0px -40px 0px",
      }
    );

    revealElements.forEach((el) => observer.observe(el));
  }

  /* --------------------------------------------------------------
     CART BUTTON — simple counter demo
     -------------------------------------------------------------- */
  const addButtons = document.querySelectorAll(".product-card__btn");
  const cartCount = document.querySelector(".nav__cart-count");

  if (addButtons.length > 0 && cartCount) {
    let count = 0;
    addButtons.forEach((btn) => {
      btn.addEventListener("click", () => {
        count++;
        cartCount.textContent = count;
        // Brief visual feedback
        cartCount.style.transform = "scale(1.3)";
        cartCount.style.transition = "transform 0.15s ease";
        setTimeout(() => {
          cartCount.style.transform = "scale(1)";
        }, 150);
      });
    });
  }
});
