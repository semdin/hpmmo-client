/**
 * HPMMO Launcher Frontend Controller
 * Metin2 Wand Combat & Hogwarts Wizarding Realm
 */

document.addEventListener('DOMContentLoaded', () => {
  // DOM Elements
  const realmStatusPill = document.getElementById('realmStatusPill');
  const statusDot = document.getElementById('statusDot');
  const statusText = document.getElementById('statusText');
  const pingTag = document.getElementById('pingTag');
  const clientVerBadge = document.getElementById('clientVerBadge');
  const serverVerTag = document.getElementById('serverVerTag');

  const tabLogin = document.getElementById('tabLogin');
  const tabRegister = document.getElementById('tabRegister');
  const usernameInput = document.getElementById('usernameInput');
  const passwordInput = document.getElementById('passwordInput');
  const rememberMe = document.getElementById('rememberMe');
  const authNotice = document.getElementById('authNotice');
  const authActionRow = document.getElementById('authActionRow');
  const btnSubmitRegister = document.getElementById('btnSubmitRegister');
  const authModeHint = document.getElementById('authModeHint');

  const btnPlayNow = document.getElementById('btnPlayNow');
  const btnSoloOffline = document.getElementById('btnSoloOffline');
  const btnGameFolder = document.getElementById('btnGameFolder');
  const btnRefreshPing = document.getElementById('btnRefreshPing');
  const btnSettingsToggle = document.getElementById('btnSettingsToggle');

  const settingsPanel = document.getElementById('settingsPanel');
  const presetOfficial = document.getElementById('presetOfficial');
  const presetLocal = document.getElementById('presetLocal');
  const serverIpInput = document.getElementById('serverIpInput');
  const serverPortInput = document.getElementById('serverPortInput');
  const btnSaveConfig = document.getElementById('btnSaveConfig');

  const footerStatusMsg = document.getElementById('footerStatusMsg');
  const progressBarFill = document.getElementById('progressBarFill');
  const progressPercent = document.getElementById('progressPercent');
  const footerServerIp = document.getElementById('footerServerIp');

  const btnMinimize = document.getElementById('btnMinimize');
  const btnClose = document.getElementById('btnClose');

  let currentAuthMode = 'login'; // 'login' or 'register'
  let clientConfig = {
    server_ip: '213.250.145.75',
    server_port: 7777,
    last_username: 'Wizard',
    remember_me: true
  };

  // 1. Initialize Particles Background
  initAmbientParticles();

  // 2. Load Local Config from Backend
  loadConfiguration();

  // 3. Setup Polling for Server Ping & Health
  checkServerStatus();
  setInterval(checkServerStatus, 10000); // Check every 10s

  // 4. Tab Switching (Login vs. Register)
  tabLogin.addEventListener('click', () => setAuthMode('login'));
  tabRegister.addEventListener('click', () => setAuthMode('register'));

  function setAuthMode(mode) {
    currentAuthMode = mode;
    hideNotice();

    if (mode === 'login') {
      tabLogin.classList.add('active');
      tabRegister.classList.remove('active');
      authActionRow.style.display = 'none';
      authModeHint.textContent = 'Karakterleriniz PostgreSQL\'e kaydedilir.';
    } else {
      tabRegister.classList.add('active');
      tabLogin.classList.remove('active');
      authActionRow.style.display = 'block';
      authModeHint.textContent = 'Kayıt sonrası tek tıkla oyuna girebilirsiniz.';
    }
  }

  // 5. Register Button Inside Card
  btnSubmitRegister.addEventListener('click', async () => {
    const user = usernameInput.value.trim();
    const pass = passwordInput.value.trim();

    if (user.length < 3) {
      showNotice('Kullanıcı adı en az 3 karakter olmalıdır.', 'error');
      return;
    }
    if (pass.length < 4) {
      showNotice('Şifre en az 4 karakter olmalıdır.', 'error');
      return;
    }

    showNotice('Sunucuya kayıt isteği gönderiliyor...', '');
    try {
      const res = await fetch('/api/auth/register', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username: user, password: pass })
      });
      const data = await res.json();
      if (data.success) {
        showNotice('✅ Hesap başarıyla oluşturuldu! Şimdi "OYUNA BAŞLA" butonuna basabilirsiniz.', 'success');
        setAuthMode('login');
      } else {
        showNotice('❌ Hata: ' + (data.message || 'Kayıt başarısız.'), 'error');
      }
    } catch (e) {
      showNotice('Sunucuya ulaşılamadı. Lütfen sunucu IP kontrolü yapın.', 'error');
    }
  });

  // 6. Play Now (Online Launch)
  btnPlayNow.addEventListener('click', async () => {
    const user = usernameInput.value.trim() || 'Wizard';
    const pass = passwordInput.value.trim();

    footerStatusMsg.textContent = 'HPMMO başlatılıyor... Büyü dünyasına bağlanılıyor...';
    playSpellSound();

    try {
      const res = await fetch('/api/launch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          mode: 'online',
          username: user,
          password: pass,
          server_ip: serverIpInput.value.trim(),
          server_port: parseInt(serverPortInput.value.trim(), 10) || 7777,
          remember_me: rememberMe.checked
        })
      });
      const data = await res.json();
      if (data.success) {
        footerStatusMsg.textContent = '⚡ HPMMO başlatıldı! İyi oyunlar.';
      } else {
        footerStatusMsg.textContent = 'Başlatma hatası: ' + (data.message || 'Bilinmeyen hata');
        showNotice(data.message, 'error');
      }
    } catch (e) {
      footerStatusMsg.textContent = 'Launcher API hatası: ' + e.message;
    }
  });

  // 7. Solo Offline Mode Launch
  btnSoloOffline.addEventListener('click', async () => {
    footerStatusMsg.textContent = 'Solo Çevrimdışı Mod başlatılıyor...';
    playSpellSound();

    try {
      const res = await fetch('/api/launch', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: 'solo' })
      });
      const data = await res.json();
      if (data.success) {
        footerStatusMsg.textContent = '🕹️ Solo HPMMO başlatıldı!';
      }
    } catch (e) {
      footerStatusMsg.textContent = 'Başlatma hatası: ' + e.message;
    }
  });

  // 8. Settings & Presets
  btnSettingsToggle.addEventListener('click', () => {
    const isHidden = settingsPanel.style.display === 'none';
    settingsPanel.style.display = isHidden ? 'flex' : 'none';
  });

  presetOfficial.addEventListener('click', () => {
    presetOfficial.classList.add('active');
    presetLocal.classList.remove('active');
    serverIpInput.value = '213.250.145.75';
    serverPortInput.value = '7777';
    saveSettings();
  });

  presetLocal.addEventListener('click', () => {
    presetLocal.classList.add('active');
    presetOfficial.classList.remove('active');
    serverIpInput.value = '127.0.0.1';
    serverPortInput.value = '7777';
    saveSettings();
  });

  btnSaveConfig.addEventListener('click', () => {
    saveSettings();
    settingsPanel.style.display = 'none';
  });

  async function saveSettings() {
    const ip = serverIpInput.value.trim() || '213.250.145.75';
    const port = parseInt(serverPortInput.value.trim(), 10) || 7777;

    footerServerIp.textContent = `${ip}:${port}`;
    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_ip: ip,
          server_port: port,
          last_username: usernameInput.value.trim(),
          remember_me: rememberMe.checked
        })
      });
      checkServerStatus();
    } catch (e) {
      console.error(e);
    }
  }

  // 9. Utilities
  btnGameFolder.addEventListener('click', () => {
    fetch('/api/open_folder', { method: 'POST' });
  });

  btnRefreshPing.addEventListener('click', () => {
    checkServerStatus();
  });

  btnMinimize.addEventListener('click', () => {
    fetch('/api/window/minimize', { method: 'POST' });
  });

  btnClose.addEventListener('click', () => {
    fetch('/api/window/close', { method: 'POST' });
    setTimeout(() => window.close(), 200);
  });

  // 10. Status / Ping Checker
  async function checkServerStatus() {
    statusDot.className = 'status-dot';
    statusText.textContent = 'Pinging Realm...';

    try {
      const res = await fetch('/api/status');
      const data = await res.json();

      if (data.online) {
        statusDot.className = 'status-dot online';
        statusText.textContent = 'Realm Online';
        pingTag.textContent = `${data.ping_ms} ms`;
        footerStatusMsg.textContent = `⚡ Hogwarts Sunucusu Aktif (${data.ping_ms}ms) • Sürüm: ${data.version || '1.1.0'}`;
      } else {
        statusDot.className = 'status-dot offline';
        statusText.textContent = 'Realm Offline';
        pingTag.textContent = 'OFFLINE';
        footerStatusMsg.textContent = 'Sunucu çevrimdışı veya bakımda. Dilerseniz Solo Mod ile oynayabilirsiniz.';
      }

      if (data.version) {
        serverVerTag.textContent = `Realm: v${data.version}`;
      }
    } catch (e) {
      statusDot.className = 'status-dot offline';
      statusText.textContent = 'Standby';
      pingTag.textContent = '--';
    }
  }

  // 11. Configuration Loader
  async function loadConfiguration() {
    try {
      const res = await fetch('/api/config');
      const data = await res.json();
      clientConfig = data;

      if (data.last_username) usernameInput.value = data.last_username;
      if (data.server_ip) {
        serverIpInput.value = data.server_ip;
        footerServerIp.textContent = `${data.server_ip}:${data.server_port || 7777}`;
        if (data.server_ip === '127.0.0.1') {
          presetLocal.classList.add('active');
          presetOfficial.classList.remove('active');
        } else {
          presetOfficial.classList.add('active');
          presetLocal.classList.remove('active');
        }
      }
      if (data.server_port) serverPortInput.value = data.server_port;
      if (data.client_version) clientVerBadge.textContent = `Client v${data.client_version}`;
    } catch (e) {
      console.warn('Could not load config:', e);
    }
  }

  function showNotice(msg, type) {
    authNotice.textContent = msg;
    authNotice.className = 'auth-notice ' + (type || '');
    authNotice.style.display = 'block';
  }

  function hideNotice() {
    authNotice.style.display = 'none';
  }

  // Synthesized magical UI chime sound
  function playSpellSound() {
    try {
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(440, ctx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(880, ctx.currentTime + 0.15);
      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.25);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.25);
    } catch (e) {
      // AudioContext blocked
    }
  }

  // Floating magical ember particles canvas
  function initAmbientParticles() {
    const canvas = document.createElement('canvas');
    canvas.id = 'particleCanvas';
    canvas.style.position = 'absolute';
    canvas.style.top = '0';
    canvas.style.left = '0';
    canvas.style.width = '100%';
    canvas.style.height = '100%';
    canvas.style.pointerEvents = 'none';
    document.getElementById('particles-bg').appendChild(canvas);

    const ctx = canvas.getContext('2d');
    let width = canvas.width = window.innerWidth;
    let height = canvas.height = window.innerHeight;

    window.addEventListener('resize', () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    const particles = [];
    const count = 38;

    for (let i = 0; i < count; i++) {
      particles.push({
        x: Math.random() * width,
        y: Math.random() * height,
        radius: Math.random() * 2 + 0.8,
        color: Math.random() > 0.4 ? 'rgba(229, 193, 88,' : 'rgba(0, 229, 255,',
        alpha: Math.random() * 0.7 + 0.2,
        speedY: Math.random() * 0.7 + 0.3,
        speedX: (Math.random() - 0.5) * 0.4
      });
    }

    function render() {
      ctx.clearRect(0, 0, width, height);

      for (let p of particles) {
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
        ctx.fillStyle = p.color + p.alpha + ')';
        ctx.shadowBlur = 6;
        ctx.shadowColor = p.color + '0.8)';
        ctx.fill();

        p.y -= p.speedY;
        p.x += p.speedX;

        if (p.y < -10) {
          p.y = height + 10;
          p.x = Math.random() * width;
        }
      }
      requestAnimationFrame(render);
    }
    render();
  }
});
