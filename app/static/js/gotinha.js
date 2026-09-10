class GotinhaAssetRegistry {
  constructor(manifest) {
    this.manifest = manifest || {};
    this.emotions = this.manifest.emotions || {};
    this.transitions = this.manifest.transitions || {};
    this.fallbackAsset = this.manifest.fallbackAsset || "/static/img/mascote_novo.png";
  }

  emotionAsset(emotion) {
    return this.emotions[emotion] || this.fallbackAsset;
  }

  transitionAssets(previousEmotion, nextEmotion) {
    const key = `${previousEmotion}>${nextEmotion}`;
    return Array.isArray(this.transitions[key]) ? this.transitions[key] : [];
  }
}

class GotinhaStateController {
  constructor(initialEmotion = "ALEGRIA") {
    this.previousEmotion = null;
    this.currentEmotion = initialEmotion;
    this.isTransitioning = false;
  }

  setEmotion(nextEmotion) {
    if (!nextEmotion || nextEmotion === this.currentEmotion) {
      return false;
    }
    this.previousEmotion = this.currentEmotion;
    this.currentEmotion = nextEmotion;
    this.isTransitioning = true;
    return true;
  }

  finishTransition() {
    this.isTransitioning = false;
  }
}

class GotinhaRuleEngine {
  suggestEmotion() {
    return null;
  }
}

class GotinhaTransitionPlayer {
  constructor(root, registry, controller, options = {}) {
    this.root = root;
    this.registry = registry;
    this.controller = controller;
    this.frameDuration = options.frameDuration || 180;
    this.crossfadeDuration = options.crossfadeDuration || 320;
    this.image = root.querySelector("[data-gotinha-image]");
    this.nextImage = root.querySelector("[data-gotinha-next-image]");
    this.status = root.querySelector("[data-gotinha-status]");
    this.previous = root.querySelector("[data-gotinha-previous]");
    this.current = root.querySelector("[data-gotinha-current]");
    this.reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.playToken = 0;
    this.timer = null;
  }

  mount() {
    this.image.src = this.registry.emotionAsset(this.controller.currentEmotion);
    this.image.alt = `Gotinha em estado ${this.controller.currentEmotion}`;
    this.renderState("stable");
  }

  async setEmotion(nextEmotion) {
    const changed = this.controller.setEmotion(nextEmotion);
    if (!changed) return;

    const token = this.cancel();
    const frames = this.registry.transitionAssets(this.controller.previousEmotion, this.controller.currentEmotion);
    this.renderState(frames.length ? "transition" : "crossfade");

    if (frames.length && !this.reducedMotion) {
      await this.playFrames(frames, token);
    } else {
      await this.crossfadeTo(this.registry.emotionAsset(this.controller.currentEmotion), token);
    }

    if (token !== this.playToken) return;
    this.image.src = this.registry.emotionAsset(this.controller.currentEmotion);
    this.image.alt = `Gotinha em estado ${this.controller.currentEmotion}`;
    this.nextImage.classList.remove("is-visible");
    this.controller.finishTransition();
    this.renderState("stable");
  }

  cancel() {
    this.playToken += 1;
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    return this.playToken;
  }

  async playFrames(frames, token) {
    for (const frame of frames) {
      if (token !== this.playToken) return;
      this.image.src = frame;
      await this.wait(this.frameDuration);
    }
  }

  async crossfadeTo(asset, token) {
    if (token !== this.playToken) return;
    this.nextImage.src = asset;
    this.nextImage.alt = `Gotinha em estado ${this.controller.currentEmotion}`;
    this.nextImage.classList.add("is-visible");
    await this.wait(this.reducedMotion ? 0 : this.crossfadeDuration);
    if (token !== this.playToken) return;
    this.image.src = asset;
  }

  wait(duration) {
    return new Promise((resolve) => {
      this.timer = setTimeout(resolve, duration);
    });
  }

  renderState(mode) {
    if (this.previous) this.previous.textContent = this.controller.previousEmotion || "-";
    if (this.current) this.current.textContent = this.controller.currentEmotion;
    if (this.status) {
      this.status.textContent = mode === "transition"
        ? "Transição por frames"
        : mode === "crossfade"
          ? "Fallback crossfade"
          : "Estado estável";
    }
  }
}

window.CentralAguasGotinha = {
  GotinhaAssetRegistry,
  GotinhaStateController,
  GotinhaTransitionPlayer,
  GotinhaRuleEngine,
};
