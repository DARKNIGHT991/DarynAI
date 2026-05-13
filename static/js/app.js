const BACKEND_URL = "";

marked.setOptions({
  highlight: function(code, lang) {
    return hljs.highlight(code, { language: hljs.getLanguage(lang) ? lang : "plaintext" }).value;
  }
});

let currentUserEmail    = "guest";
let currentMode         = "chat";
let attachedFile        = null;
let lastUserMessage     = "";
let selectedUpgradePlan = null;
let userPlanData        = null;

// ── CHAT STATE ─────────────────────────────────────────────────
let currentChatId    = null;   // active chat_id (null = guest/unsaved)
let allChats         = [];     // [{id, title, updated_at}, ...]
let currentAbortCtrl = null;   // AbortController for stop generation
let isGenerating     = false;

// ================================================================
// ЧАСТИЦЫ
// ================================================================
(function(){
  const canvas = document.getElementById("particles-canvas");
  const ctx    = canvas.getContext("2d");
  let W, H, particles = [];
  let mouse = { x:-9999, y:-9999 };
  let isLandingVisible = true;
  const COLORS = ["#3b82f6","#0ea5e9","#10b981","#6366f1","#38bdf8"];
  const COUNT  = window.innerWidth < 768 ? 70 : 130;

  function rand(a,b){ return Math.random()*(b-a)+a; }
  function createParticle(fy){
    return {
      x:rand(0,W), y:fy!==undefined?fy:rand(0,H),
      vx:rand(-0.25,0.25), vy:rand(-0.5,-0.15),
      size:rand(1,2.8), alpha:rand(0.3,1), baseAlpha:rand(0.3,1),
      color:COLORS[Math.floor(Math.random()*COLORS.length)],
      twinkleSpeed:rand(0.006,0.022),
      pulse:rand(0,Math.PI*2)
    };
  }
  function resize(){ W=canvas.width=window.innerWidth; H=canvas.height=window.innerHeight; }
  function init(){ resize(); particles=Array.from({length:COUNT},()=>createParticle()); }
  function hexToRgb(h){ const r=parseInt(h.slice(1,3),16),g=parseInt(h.slice(3,5),16),b=parseInt(h.slice(5,7),16); return `${r},${g},${b}`; }
  function drawConnections(){
    for(let i=0;i<particles.length;i++){
      for(let j=i+1;j<particles.length;j++){
        const dx=particles[i].x-particles[j].x, dy=particles[i].y-particles[j].y;
        const d=Math.sqrt(dx*dx+dy*dy);
        if(d<110){ ctx.beginPath(); ctx.strokeStyle=`rgba(59,130,246,${0.15*(1-d/110)})`; ctx.lineWidth=0.6; ctx.moveTo(particles[i].x,particles[i].y); ctx.lineTo(particles[j].x,particles[j].y); ctx.stroke(); }
      }
    }
  }
  function animate(){
    if(!isLandingVisible){ requestAnimationFrame(animate); return; }
    ctx.clearRect(0,0,W,H);
    const bg=ctx.createRadialGradient(W*.5,H*.4,0,W*.5,H*.5,W*.85);
    bg.addColorStop(0,"#0b0b18"); bg.addColorStop(.5,"#070710"); bg.addColorStop(1,"#050505");
    ctx.fillStyle=bg; ctx.fillRect(0,0,W,H);
    const cg=ctx.createRadialGradient(W*.5,H*.5,0,W*.5,H*.5,W*.4);
    cg.addColorStop(0,"rgba(59,130,246,0.04)"); cg.addColorStop(1,"rgba(0,0,0,0)");
    ctx.fillStyle=cg; ctx.fillRect(0,0,W,H);
    drawConnections();
    particles.forEach(p=>{
      p.pulse+=p.twinkleSpeed;
      p.alpha=p.baseAlpha*(0.6+0.4*Math.sin(p.pulse));
      const dx=p.x-mouse.x, dy=p.y-mouse.y, d=Math.sqrt(dx*dx+dy*dy);
      if(d<90&&d>0){ const f=(90-d)/90; p.x+=(dx/d)*f*1.2; p.y+=(dy/d)*f*1.2; }
      p.x+=p.vx; p.y+=p.vy;
      if(p.y<-8){ p.y=H+8; p.x=rand(0,W); }
      if(p.x<-8) p.x=W+8; if(p.x>W+8) p.x=-8;
      const rgb=hexToRgb(p.color);
      ctx.save(); ctx.globalAlpha=p.alpha*0.35; ctx.beginPath(); ctx.arc(p.x,p.y,p.size*3,0,Math.PI*2); ctx.fillStyle=`rgba(${rgb},0.15)`; ctx.fill(); ctx.restore();
      ctx.save(); ctx.globalAlpha=p.alpha; ctx.shadowBlur=10; ctx.shadowColor=p.color; ctx.beginPath(); ctx.arc(p.x,p.y,p.size,0,Math.PI*2); ctx.fillStyle=`rgba(${rgb},1)`; ctx.fill(); ctx.restore();
    });
    requestAnimationFrame(animate);
  }
  window.addEventListener("resize",resize);
  window.addEventListener("mousemove",e=>{ mouse.x=e.clientX; mouse.y=e.clientY; });
  window.addEventListener("mouseleave",()=>{ mouse.x=-9999; mouse.y=-9999; });
  window._stopParticles=function(){ isLandingVisible=false; canvas.style.display="none"; };
  window._showParticles=function(){ isLandingVisible=true;  canvas.style.display="block"; };
  init(); animate();
})();

// ================================================================
// PWA — SERVICE WORKER
// ================================================================
if("serviceWorker" in navigator){
  window.addEventListener("load", async()=>{
    try{
      const reg = await navigator.serviceWorker.register("/sw.js");
      console.log("[PWA] SW зарегистрирован:", reg.scope);
      setInterval(()=>reg.update(), 60000);
      reg.addEventListener("updatefound",()=>{
        const nw = reg.installing;
        nw.addEventListener("statechange",()=>{
          if(nw.state==="installed" && navigator.serviceWorker.controller) showUpdateBanner();
        });
      });
    } catch(e){ console.warn("[PWA] SW ошибка:", e); }
  });
}

function showUpdateBanner(){
  if(document.getElementById("update-banner")) return;
  const b = document.createElement("div");
  b.id = "update-banner";
  b.style.cssText = `
    position:fixed; bottom:80px; left:50%; transform:translateX(-50%);
    background:rgba(15,15,15,0.95); border:1px solid rgba(59,130,246,0.4);
    color:#fff; padding:12px 20px; border-radius:12px; font-size:13px;
    z-index:9999; display:flex; align-items:center; gap:12px;
    box-shadow:0 8px 30px rgba(0,0,0,0.5); backdrop-filter:blur(10px);
    font-family:'Inter',sans-serif; white-space:nowrap;
  `;
  b.innerHTML = `
    <span>🔄 Обновление доступно</span>
    <button onclick="location.reload()" style="background:#3b82f6;border:none;color:#fff;padding:6px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;">Обновить</button>
    <button onclick="this.parentElement.remove()" style="background:none;border:none;color:#888;cursor:pointer;font-size:16px;">✕</button>
  `;
  document.body.appendChild(b);
  setTimeout(()=>b?.remove(), 10000);
}

let deferredPrompt = null;

window.addEventListener("beforeinstallprompt", event=>{
  event.preventDefault();
  deferredPrompt = event;
  setTimeout(showInstallBanner, 3000);
});

window.addEventListener("appinstalled",()=>{
  hideInstallBanner();
  deferredPrompt = null;
  showToast("✅ Daryn AI установлен!");
});

function showInstallBanner(){
  if(document.getElementById("install-banner")) return;
  if(window.matchMedia("(display-mode:standalone)").matches) return;
  const dismissed = localStorage.getItem("pwa_dismissed");
  if(dismissed && Date.now()-parseInt(dismissed) < 3*24*60*60*1000) return;
  const lang = localStorage.getItem("daryn_lang") || "ru";
  const T = {
    ru:{ title:"Установить Daryn AI", desc:"Добавьте на главный экран для быстрого доступа", btn:"Установить", later:"Позже" },
    kk:{ title:"Daryn AI орнату", desc:"Жылдам қол жеткізу үшін негізгі экранға қосыңыз", btn:"Орнату", later:"Кейінірек" },
    en:{ title:"Install Daryn AI", desc:"Add to home screen for quick access", btn:"Install", later:"Later" },
  };
  const t = T[lang] || T.ru;
  const b = document.createElement("div");
  b.id = "install-banner";
  b.style.cssText = `
    position:fixed; bottom:20px; left:50%; transform:translateX(-50%);
    background:rgba(15,15,15,0.97); border:1px solid rgba(59,130,246,0.5);
    border-radius:16px; padding:16px 20px; z-index:5000;
    width:calc(100% - 40px); max-width:400px;
    box-shadow:0 8px 40px rgba(0,0,0,0.6); backdrop-filter:blur(20px);
    font-family:'Inter',sans-serif; animation:slideUp 0.4s cubic-bezier(0.4,0,0.2,1);
  `;
  b.innerHTML = `
    <div style="display:flex;align-items:center;gap:14px;margin-bottom:14px;">
      <div style="width:48px;height:48px;border-radius:12px;background:rgba(59,130,246,0.15);border:1px solid rgba(59,130,246,0.3);display:flex;align-items:center;justify-content:center;flex-shrink:0;">
        <svg viewBox="0 0 24 24" fill="none" stroke="#3b82f6" stroke-width="2" style="width:28px;">
          <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2"></polygon>
          <path d="M9 8h3.5a4 4 0 1 1 0 8H9v-8z"></path>
        </svg>
      </div>
      <div>
        <div style="font-weight:700;font-size:15px;margin-bottom:4px;">${t.title}</div>
        <div style="color:#888;font-size:12px;line-height:1.4;">${t.desc}</div>
      </div>
    </div>
    <div style="display:flex;gap:10px;">
      <button id="pwa-install-btn" style="flex:1;background:#3b82f6;border:none;color:#fff;padding:12px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;">${t.btn}</button>
      <button id="pwa-later-btn"   style="flex:1;background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.1);color:#888;padding:12px;border-radius:10px;font-size:14px;cursor:pointer;">${t.later}</button>
    </div>
  `;
  document.body.appendChild(b);
  document.getElementById("pwa-install-btn").addEventListener("click", async()=>{
    if(!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    deferredPrompt = null;
    hideInstallBanner();
  });
  document.getElementById("pwa-later-btn").addEventListener("click",()=>{
    localStorage.setItem("pwa_dismissed", Date.now().toString());
    hideInstallBanner();
  });
}

function hideInstallBanner(){
  const b = document.getElementById("install-banner");
  if(b){ b.style.animation="slideDown 0.3s ease forwards"; setTimeout(()=>b?.remove(),300); }
}

function showToast(msg, dur=3000){
  const t = document.createElement("div");
  t.style.cssText = `
    position:fixed; top:20px; left:50%; transform:translateX(-50%);
    background:rgba(16,185,129,0.15); border:1px solid rgba(16,185,129,0.4);
    color:#10b981; padding:10px 20px; border-radius:10px;
    font-size:13px; font-weight:500; z-index:9999;
    backdrop-filter:blur(10px); font-family:'Inter',sans-serif;
    animation:fadeIn 0.3s ease; white-space:nowrap;
  `;
  t.innerText = msg;
  document.body.appendChild(t);
  setTimeout(()=>t?.remove(), dur);
}

window.addEventListener("online",()=>{
  const l = localStorage.getItem("daryn_lang")||"ru";
  showToast(l==="en"?"✅ Connection restored":l==="kk"?"✅ Байланыс қалпына келді":"✅ Соединение восстановлено");
});
window.addEventListener("offline",()=>{
  const l = localStorage.getItem("daryn_lang")||"ru";
  showToast(l==="en"?"⚠ No internet":l==="kk"?"⚠ Интернет жоқ":"⚠ Нет интернета", 5000);
});

// ================================================================
// i18n
// ================================================================
const i18n = {
  ru:{
    "hero-reg":"Регистрация","hero-login":"Войти","hero-guest":"Гость",
    "hero-pricing":"💎 Тарифы","hero-scroll":"Изучать ядро",
    "core-llm-desc":"Высокоскоростной стриминг токенов (LPU). Встроенная мультимодальность: парсинг Base64 изображений и анализ контекста на лету.",
    "core-backend-desc":"Асинхронная обработка маршрутов. Строгая типизация через Pydantic. Нативная работа с бинарниками через io.BytesIO и PyPDF2.",
    "core-db-desc":"Реляционное хранение сессий и юзеров. Хэширование паролей с солью. Защита от SQL-инъекций.",
    "core-net-desc":"Встроенные скрипты для инженеров. Системные пинги и асинхронное сканирование портов (TCP/IP).",
    "specs-header":">_ ТЕХНИЧЕСКИЕ СПЕЦИФИКАЦИИ",
    "spec-arch":"Вычислительная архитектура","spec-arch-val":"Асинхронный Stateless API (FastAPI)",
    "spec-speed":"Скорость генерации (LPU)","spec-speed-val":"~800 токенов в секунду",
    "spec-ctx":"Контекстное окно","spec-ctx-val":"131,072 токенов (Long Context)",
    "spec-db":"Система хранения данных","spec-db-val":"Реляционная СУБД (PostgreSQL)",
    "spec-sec":"Протоколы безопасности","spec-sec-val":"Bcrypt Hashing / CORS / ENV Encryption",
    "mission-1":"Проект основан в 2026 году разработчиком <strong>Daryn</strong>.",
    "mission-2":"Главная цель — создать мощный, независимый и универсальный инструмент, который стирает границы между человеком и технологиями.",
    "pricing-title":"ТАРИФЫ","pricing-subtitle":"Выберите план под ваши задачи",
    "plan-popular":"★ ПОПУЛЯРНЫЙ",
    "plan-free-1":"✅ 20 сообщений / день","plan-free-2":"✅ 5 генераций фото / день",
    "plan-free-3":"✅ Анализ PDF (до 5 MB)","plan-free-4":"✅ Голосовой ввод",
    "plan-free-5":"✅ Код и сканирование","plan-free-6":"✅ RU / KK / EN",
    "plan-free-7":"✅ PWA приложение","plan-free-8":"❌ Голосовой ответ AI",
    "plan-free-btn":"Начать бесплатно",
    "plan-pro-1":"✅ 500 сообщений / день","plan-pro-2":"✅ 50 генераций фото / день",
    "plan-pro-3":"✅ Анализ PDF (до 25 MB)","plan-pro-4":"✅ Голосовой ввод",
    "plan-pro-5":"✅ Код и сканирование","plan-pro-6":"✅ RU / KK / EN",
    "plan-pro-7":"✅ Голосовой ответ AI","plan-pro-8":"✅ Контекст 32K токенов",
    "plan-pro-btn":"Получить Pro",
    "plan-prem-1":"✅ Безлимит сообщений","plan-prem-2":"✅ 200 генераций фото / день",
    "plan-prem-3":"✅ Анализ PDF (до 100 MB)","plan-prem-4":"✅ Голосовой ввод + ответ AI",
    "plan-prem-5":"✅ Код и сканирование","plan-prem-6":"✅ RU / KK / EN",
    "plan-prem-7":"✅ Голосовой ответ AI","plan-prem-8":"✅ Контекст 131K токенов",
    "plan-prem-btn":"Получить Premium",
    "upg-step1":"Отправьте оплату на указанные реквизиты",
    "upg-step2":"Укажите в комментарии ваш Email",
    "upg-step3":"Нажмите «Я оплатил» и введите ID транзакции",
    "upg-step4":"Ожидайте подтверждения до 24 часов",
    "upg-btn":"✅ Я оплатил — отправить заявку",
    "auth-login-title":"Вход в систему","auth-login-sub":"Укажите данные для доступа",
    "auth-reg-title":"Регистрация","auth-reg-sub":"Создайте новый профиль доступа",
    "ph-email":"Email","ph-pass":"Пароль","ph-name":"Имя пользователя",
    "pass-hint":"Минимум 8 символов, буква и цифра","auth-or":"или",
    "btn-login":"Авторизация","btn-reg":"Создать",
    "prof-title":"Ваш профиль","ph-new-name":"Новое имя",
    "btn-save":"Сохранить имя","btn-clear":"Очистить БД","btn-close":"Закрыть настройки",
    "sb-new":"Новая сессия","sb-guest":"Гость","tb-logout":"Выйти",
    "init-msg":"Система инициализирована. Выберите инструмент, задайте вопрос или прикрепите файл.",
    "tool-code":"Код","tool-img":"Фото","tool-scan":"Скан","tool-export":"Экспорт",
    "ph-input":"Команда терминалу...","ph-input-code":"Команда для парсинга кода...",
    "ph-input-scan":"IP или домен цели...","ph-input-img":"Анализ изображения...",
    "loading":"⏳ Обработка запроса ядром...","sys-err":"[SYS_ERROR] Ошибка ответа сервера."
  },
  kk:{
    "hero-reg":"Тіркелу","hero-login":"Кіру","hero-guest":"Қонақ",
    "hero-pricing":"💎 Тарифтер","hero-scroll":"Ядроны зерттеу",
    "core-llm-desc":"Токендердің жоғары жылдамдықты стримингі (LPU). Base64 суреттерін талдау және контекстті бірден өңдеу.",
    "core-backend-desc":"Маршруттарды асинхронды өңдеу. Pydantic арқылы қатаң типтеу. io.BytesIO және PyPDF2 қолдауы.",
    "core-db-desc":"Сессиялар мен пайдаланушыларды реляциялық сақтау. Тұзбен хэштеу. SQL-инъекциялардан қорғау.",
    "core-net-desc":"Инженерлерге арналған скрипттер. Серверлерді пингтеу және порттарды сканерлеу (TCP/IP).",
    "specs-header":">_ ТЕХНИКАЛЫҚ СИПАТТАМАЛАР",
    "spec-arch":"Есептеу архитектурасы","spec-arch-val":"Асинхронды Stateless API (FastAPI)",
    "spec-speed":"Генерация жылдамдығы (LPU)","spec-speed-val":"секундына ~800 токен",
    "spec-ctx":"Контексттік терезе","spec-ctx-val":"131,072 токен (Long Context)",
    "spec-db":"Деректерді сақтау жүйесі","spec-db-val":"Реляциялық ДҚБЖ (PostgreSQL)",
    "spec-sec":"Қауіпсіздік хаттамалары","spec-sec-val":"Bcrypt Hashing / CORS / ENV Encryption",
    "mission-1":"Жобаның негізін 2026 жылы <strong>Daryn</strong> атты әзірлеуші қалаған.",
    "mission-2":"Басты мақсат — адам мен технология арасындағы шекараны жоятын қуатты, тәуелсіз және әмбебап құрал жасау.",
    "pricing-title":"ТАРИФТЕР","pricing-subtitle":"Міндеттеріңізге сай жоспарды таңдаңыз",
    "plan-popular":"★ ТАНЫМАЛ",
    "plan-free-1":"✅ 20 хабарлама / күн","plan-free-2":"✅ 5 сурет / күн",
    "plan-free-3":"✅ PDF (5 MB дейін)","plan-free-4":"✅ Дауыстық енгізу",
    "plan-free-5":"✅ Код және сканерлеу","plan-free-6":"✅ RU / KK / EN",
    "plan-free-7":"✅ PWA қолданбасы","plan-free-8":"❌ AI дауыстық жауабы",
    "plan-free-btn":"Тегін бастау",
    "plan-pro-1":"✅ 500 хабарлама / күн","plan-pro-2":"✅ 50 сурет / күн",
    "plan-pro-3":"✅ PDF (25 MB дейін)","plan-pro-4":"✅ Дауыстық енгізу",
    "plan-pro-5":"✅ Код және сканерлеу","plan-pro-6":"✅ RU / KK / EN",
    "plan-pro-7":"✅ AI дауыстық жауабы","plan-pro-8":"✅ 32K токен контексті",
    "plan-pro-btn":"Pro алу",
    "plan-prem-1":"✅ Шексіз хабарламалар","plan-prem-2":"✅ 200 сурет / күн",
    "plan-prem-3":"✅ PDF (100 MB дейін)","plan-prem-4":"✅ Дауыстық енгізу + жауап",
    "plan-prem-5":"✅ Код және сканерлеу","plan-prem-6":"✅ RU / KK / EN",
    "plan-prem-7":"✅ AI дауыстық жауабы","plan-prem-8":"✅ 131K токен контексті",
    "plan-prem-btn":"Premium алу",
    "upg-step1":"Көрсетілген деректемелерге төлем жіберіңіз",
    "upg-step2":"Пікірде Email-іңізді көрсетіңіз",
    "upg-step3":"«Төледім» басып, транзакция ID-ін енгізіңіз",
    "upg-step4":"24 сағатқа дейін растауды күтіңіз",
    "upg-btn":"✅ Төледім — өтінім жіберу",
    "auth-login-title":"Жүйеге кіру","auth-login-sub":"Мәліметтерді енгізіңіз",
    "auth-reg-title":"Тіркелу","auth-reg-sub":"Жаңа профиль жасаңыз",
    "ph-email":"Электрондық пошта","ph-pass":"Құпия сөз","ph-name":"Пайдаланушы аты",
    "pass-hint":"Кемінде 8 таңба, әріп және сан","auth-or":"немесе",
    "btn-login":"Авторизация","btn-reg":"Жасау",
    "prof-title":"Сіздің профиліңіз","ph-new-name":"Жаңа есім",
    "btn-save":"Есімді сақтау","btn-clear":"ДҚ тазарту","btn-close":"Баптауларды жабу",
    "sb-new":"Жаңа сессия","sb-guest":"Қонақ","tb-logout":"Шығу",
    "init-msg":"Жүйе іске қосылды. Құралды таңдаңыз, сұрақ қойыңыз немесе файл тіркеңіз.",
    "tool-code":"Код","tool-img":"Сурет","tool-scan":"Скан","tool-export":"Экспорт",
    "ph-input":"Терминал командасы...","ph-input-code":"Кодты талдау командасы...",
    "ph-input-scan":"IP немесе домен...","ph-input-img":"Суретті талдау...",
    "loading":"⏳ Ядро өңдеуде...","sys-err":"[SYS_ERROR] Сервер қатесі."
  },
  en:{
    "hero-reg":"Sign Up","hero-login":"Log In","hero-guest":"Guest",
    "hero-pricing":"💎 Pricing","hero-scroll":"Explore Core",
    "core-llm-desc":"High-speed token streaming (LPU). Built-in multimodality: Base64 image parsing and on-the-fly context analysis.",
    "core-backend-desc":"Async route processing. Strict typing via Pydantic. Native binary handling using io.BytesIO and PyPDF2.",
    "core-db-desc":"Relational session and user storage. Salted password hashing. SQL injection protection.",
    "core-net-desc":"Built-in scripts for engineers. System pinging and async port scanning (TCP/IP).",
    "specs-header":">_ TECHNICAL SPECIFICATIONS",
    "spec-arch":"Computing Architecture","spec-arch-val":"Async Stateless API (FastAPI)",
    "spec-speed":"Generation Speed (LPU)","spec-speed-val":"~800 tokens per second",
    "spec-ctx":"Context Window","spec-ctx-val":"131,072 tokens (Long Context)",
    "spec-db":"Data Storage System","spec-db-val":"Relational RDBMS (PostgreSQL)",
    "spec-sec":"Security Protocols","spec-sec-val":"Bcrypt Hashing / CORS / ENV Encryption",
    "mission-1":"The project was founded in 2026 by developer <strong>Daryn</strong>.",
    "mission-2":"The main goal is to create a powerful, independent, and universal tool that blurs the lines between humans and technology.",
    "pricing-title":"PRICING","pricing-subtitle":"Choose a plan for your needs",
    "plan-popular":"★ POPULAR",
    "plan-free-1":"✅ 20 messages / day","plan-free-2":"✅ 5 image generations / day",
    "plan-free-3":"✅ PDF analysis (up to 5 MB)","plan-free-4":"✅ Voice input",
    "plan-free-5":"✅ Code & scanning","plan-free-6":"✅ RU / KK / EN",
    "plan-free-7":"✅ PWA app","plan-free-8":"❌ AI voice response",
    "plan-free-btn":"Start for free",
    "plan-pro-1":"✅ 500 messages / day","plan-pro-2":"✅ 50 image generations / day",
    "plan-pro-3":"✅ PDF analysis (up to 25 MB)","plan-pro-4":"✅ Voice input",
    "plan-pro-5":"✅ Code & scanning","plan-pro-6":"✅ RU / KK / EN",
    "plan-pro-7":"✅ AI voice response","plan-pro-8":"✅ 32K token context",
    "plan-pro-btn":"Get Pro",
    "plan-prem-1":"✅ Unlimited messages","plan-prem-2":"✅ 200 image generations / day",
    "plan-prem-3":"✅ PDF analysis (up to 100 MB)","plan-prem-4":"✅ Voice input + AI response",
    "plan-prem-5":"✅ Code & scanning","plan-prem-6":"✅ RU / KK / EN",
    "plan-prem-7":"✅ AI voice response","plan-prem-8":"✅ 131K token context",
    "plan-prem-btn":"Get Premium",
    "upg-step1":"Send payment to the specified details",
    "upg-step2":"Include your Email in the comment",
    "upg-step3":"Click 'I paid' and enter the transaction ID",
    "upg-step4":"Wait for confirmation within 24 hours",
    "upg-btn":"✅ I paid — send request",
    "auth-login-title":"System Login","auth-login-sub":"Enter your credentials",
    "auth-reg-title":"Registration","auth-reg-sub":"Create a new profile",
    "ph-email":"Email","ph-pass":"Password","ph-name":"Username",
    "pass-hint":"At least 8 characters, a letter and a number","auth-or":"or",
    "btn-login":"Authorize","btn-reg":"Create",
    "prof-title":"Your Profile","ph-new-name":"New name",
    "btn-save":"Save name","btn-clear":"Clear DB","btn-close":"Close settings",
    "sb-new":"New Session","sb-guest":"Guest","tb-logout":"Log Out",
    "init-msg":"System initialized. Select a tool, ask a question, or attach a file.",
    "tool-code":"Code","tool-img":"Image","tool-scan":"Scan","tool-export":"Export",
    "ph-input":"Terminal command...","ph-input-code":"Code parsing command...",
    "ph-input-scan":"Target IP or domain...","ph-input-img":"Image analysis...",
    "loading":"⏳ Core processing...","sys-err":"[SYS_ERROR] Server error."
  }
};

let currentLang = localStorage.getItem("daryn_lang") || "ru";

function setLanguage(lang){
  currentLang = lang;
  localStorage.setItem("daryn_lang", lang);
  document.querySelectorAll(".lang-btn").forEach(b=>b.classList.toggle("active",b.innerText.toLowerCase()===lang));
  document.querySelectorAll("[data-i18n]").forEach(el=>{
    const k = el.getAttribute("data-i18n");
    if(i18n[lang]&&i18n[lang][k]){
      if(el.tagName==="INPUT") el.placeholder=i18n[lang][k];
      else el.innerHTML=i18n[lang][k];
    }
  });
  updatePlaceholder();
}

function updatePlaceholder(){
  const inp = document.getElementById("user-input");
  if(!inp) return;
  if(currentMode==="code")       inp.placeholder=i18n[currentLang]["ph-input-code"];
  else if(currentMode==="scan")  inp.placeholder=i18n[currentLang]["ph-input-scan"];
  else if(currentMode==="image") inp.placeholder=i18n[currentLang]["ph-input-img"];
  else                           inp.placeholder=i18n[currentLang]["ph-input"];
}

document.addEventListener("DOMContentLoaded",()=>{
  setLanguage(currentLang);
  loadGoogleAuthConfig();
  const obs = new IntersectionObserver(entries=>{
    entries.forEach(e=>{ if(e.isIntersecting) e.target.classList.add("active"); });
  },{ threshold:0.1 });
  document.querySelectorAll(".reveal").forEach(el=>obs.observe(el));
});

// ================================================================
// AUTH
// ================================================================
function openAuth(type){
  document.getElementById("login-error").style.display="none";
  document.getElementById("reg-error").style.display="none";
  if(type==="login"){
    document.getElementById("auth-title").innerText=i18n[currentLang]["auth-login-title"];
    document.getElementById("auth-subtitle").innerText=i18n[currentLang]["auth-login-sub"];
    document.getElementById("form-login").style.display="flex";
    document.getElementById("form-register").style.display="none";
  } else {
    document.getElementById("auth-title").innerText=i18n[currentLang]["auth-reg-title"];
    document.getElementById("auth-subtitle").innerText=i18n[currentLang]["auth-reg-sub"];
    document.getElementById("form-login").style.display="none";
    document.getElementById("form-register").style.display="flex";
  }
  const s=document.getElementById("auth-screen");
  s.style.display="flex";
  setTimeout(()=>s.style.opacity="1",10);
}

function closeAuth(){
  const s=document.getElementById("auth-screen");
  s.style.opacity="0";
  setTimeout(()=>s.style.display="none",300);
}

async function enterApp(){
  document.getElementById("auth-screen").style.opacity="0";
  document.getElementById("landing-screen").style.opacity="0";
  setTimeout(()=>{
    document.getElementById("auth-screen").style.display="none";
    document.getElementById("landing-screen").style.display="none";
    document.getElementById("app-container").style.display="flex";
    if(window._stopParticles) window._stopParticles();
  },500);
  await loadChats();
  await loadUserPlan();
}


function getAuthMessage(key){
  const messages={
    fill:{ru:"Заполните все поля",kk:"Барлық өрістерді толтырыңыз",en:"Fill all fields"},
    email:{ru:"Введите корректный email",kk:"Дұрыс email енгізіңіз",en:"Enter a valid email"},
    password:{ru:"Пароль должен быть не короче 8 символов и содержать букву и цифру",kk:"Құпия сөз кемінде 8 таңба, әріп және сан қамтуы керек",en:"Password must be at least 8 characters and include a letter and a number"},
    name:{ru:"Имя должно быть не короче 2 символов",kk:"Аты кемінде 2 таңба болуы керек",en:"Name must be at least 2 characters"},
    server:{ru:"Ошибка сервера",kk:"Сервер қатесі",en:"Server error"},
    googleOff:{ru:"Google вход не настроен",kk:"Google арқылы кіру бапталмаған",en:"Google sign-in is not configured"}
  };
  return (messages[key]&&messages[key][currentLang])||messages[key]?.ru||key;
}

function isValidEmail(email){
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((email||"").trim());
}

function isStrongPassword(password){
  return typeof password==="string" && password.length>=8 && /[A-Za-z]/.test(password) && /\d/.test(password);
}

function setAuthError(id,message){
  const err=document.getElementById(id);
  if(!err) return;
  err.innerText=message;
  err.style.display="block";
}

function clearAuthError(id){
  const err=document.getElementById(id);
  if(!err) return;
  err.innerText="";
  err.style.display="none";
}

let googleClientId="";
let googleButtonsRendered=false;

async function loadGoogleAuthConfig(){
  try{
    const res=await fetch(`${BACKEND_URL}/auth/config`);
    const d=await res.json();
    googleClientId=d.google_client_id||"";
    renderGoogleButtons();
  } catch(e){ console.warn("Google auth config unavailable",e); }
}

function renderGoogleButtons(){
  const slots=[document.getElementById("google-login-btn"),document.getElementById("google-register-btn")].filter(Boolean);
  if(!googleClientId){
    slots.forEach(el=>{ el.style.display="none"; });
    return;
  }
  slots.forEach(el=>{ el.style.display="flex"; });
  if(googleButtonsRendered || !window.google || !google.accounts || !google.accounts.id) return;
  google.accounts.id.initialize({
    client_id:googleClientId,
    callback:handleGoogleCredential,
    ux_mode:"popup"
  });
  slots.forEach(el=>{
    google.accounts.id.renderButton(el,{ theme:"outline", size:"large", width:260, text:"continue_with" });
  });
  googleButtonsRendered=true;
}

window.handleGoogleCredential=async function(response){
  const loginVisible=document.getElementById("form-login")?.style.display!=="none";
  const errId=loginVisible?"login-error":"reg-error";
  clearAuthError(errId);
  try{
    const res=await fetch(`${BACKEND_URL}/auth/google`,{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({credential:response.credential})
    });
    const d=await res.json();
    if(d.status==="success"){
      currentUserEmail=d.email;
      document.getElementById("sidebar-username").innerText=d.username;
      enterApp();
    } else {
      setAuthError(errId,d.message||getAuthMessage("googleOff"));
    }
  } catch {
    setAuthError(errId,getAuthMessage("server"));
  }
};

window.addEventListener("load",()=>setTimeout(renderGoogleButtons,300));

async function registerUser(){
  const name=document.getElementById("reg-name").value.trim();
  const email=document.getElementById("reg-email").value.trim().toLowerCase();
  const pass=document.getElementById("reg-pass").value;
  clearAuthError("reg-error");
  if(!name||!email||!pass){ setAuthError("reg-error",getAuthMessage("fill")); return; }
  if(name.length<2){ setAuthError("reg-error",getAuthMessage("name")); return; }
  if(!isValidEmail(email)){ setAuthError("reg-error",getAuthMessage("email")); return; }
  if(!isStrongPassword(pass)){ setAuthError("reg-error",getAuthMessage("password")); return; }
  try{
    const res=await fetch(`${BACKEND_URL}/register`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({username:name,email,password:pass}) });
    const d=await res.json();
    if(d.status==="success"){ currentUserEmail=d.email; document.getElementById("sidebar-username").innerText=d.username; enterApp(); }
    else { setAuthError("reg-error",d.message); }
  } catch { setAuthError("reg-error",getAuthMessage("server")); }
}

async function loginUser(){
  const email=document.getElementById("login-email").value.trim().toLowerCase();
  const pass=document.getElementById("login-pass").value;
  clearAuthError("login-error");
  if(!email||!pass){ setAuthError("login-error",getAuthMessage("fill")); return; }
  if(!isValidEmail(email)){ setAuthError("login-error",getAuthMessage("email")); return; }
  try{
    const res=await fetch(`${BACKEND_URL}/login`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email,password:pass}) });
    const d=await res.json();
    if(d.status==="success"){ currentUserEmail=d.email; document.getElementById("sidebar-username").innerText=d.username; enterApp(); }
    else { setAuthError("login-error",d.message); }
  } catch { setAuthError("login-error",getAuthMessage("server")); }
}

function loginAsGuest(){
  currentUserEmail="guest";
  document.getElementById("sidebar-username").innerText=i18n[currentLang]["sb-guest"];
  enterApp();
}

// ================================================================
// CHAT MANAGEMENT — НОВЫЕ ОТДЕЛЬНЫЕ ЧАТЫ
// ================================================================

async function loadChats(){
  if(currentUserEmail==="guest"){
    renderGuestSidebar();
    return;
  }
  try{
    const res=await fetch(`${BACKEND_URL}/chats?email=${encodeURIComponent(currentUserEmail)}`);
    const d=await res.json();
    if(d.status==="success"){
      allChats=d.chats;
      renderChatList(allChats);
      if(allChats.length>0) await openChat(allChats[0].id);
      else await createNewChat();
    }
  } catch(e){ console.error("loadChats:",e); }
}

function renderGuestSidebar(){
  const sh=document.getElementById("sidebar-history");
  sh.innerHTML=`<div style="padding:12px;color:#555;font-size:12px;font-family:monospace;">История недоступна для гостей</div>`;
}

function renderChatList(chats){
  const sh=document.getElementById("sidebar-history");
  sh.innerHTML="";
  if(!chats.length){
    sh.innerHTML=`<div style="padding:12px;color:#555;font-size:12px;">Нет чатов</div>`;
    return;
  }
  chats.forEach(c=>{
    const el=document.createElement("div");
    el.className="history-item"+(c.id===currentChatId?" active":"");
    el.dataset.chatId=c.id;
    el.dataset.title=(c.title||"").toLowerCase();
    el.innerHTML=`
      <span class="chat-title">${escHtml(c.title||"Новый чат")}</span>
      <div class="chat-actions">
        <button class="chat-act-btn" title="Переименовать" onclick="event.stopPropagation();renameChatPrompt(${c.id},'${escHtml(c.title||"")}')">
          <svg viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"></path><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"></path></svg>
        </button>
        <button class="chat-act-btn" title="Удалить" onclick="event.stopPropagation();deleteChatConfirm(${c.id})" style="color:#ef444488;">
          <svg viewBox="0 0 24 24"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
        </button>
      </div>
    `;
    el.addEventListener("click",()=>openChat(c.id));
    sh.appendChild(el);
  });
}

function filterChats(query){
  const q=query.toLowerCase().trim();
  if(!q){ renderChatList(allChats); return; }
  const filtered=allChats.filter(c=>(c.title||"").toLowerCase().includes(q));
  renderChatList(filtered);
}

async function createNewChat(){
  if(currentUserEmail==="guest"){
    clearChatUI();
    currentChatId=null;
    return;
  }
  try{
    const res=await fetch(`${BACKEND_URL}/chats/create`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:currentUserEmail,title:"Новый чат"}) });
    const d=await res.json();
    if(d.status==="success"){
      const newChat={ id:d.chat_id, title:"Новый чат", updated_at:new Date().toISOString() };
      allChats.unshift(newChat);
      renderChatList(allChats);
      await openChat(d.chat_id);
    }
  } catch(e){ console.error("createNewChat:",e); }
  if(window.innerWidth<=768) toggleSidebar();
}

async function openChat(chatId){
  currentChatId=chatId;
  // Highlight active
  document.querySelectorAll(".history-item").forEach(el=>{
    el.classList.toggle("active",parseInt(el.dataset.chatId)===chatId);
  });
  clearChatUI();
  if(currentUserEmail==="guest") return;
  try{
    const res=await fetch(`${BACKEND_URL}/chats/history`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:currentUserEmail,chat_id:chatId}) });
    const d=await res.json();
    const chat=document.getElementById("chat");
    if(d.status==="success"&&d.history.length>0){
      chat.innerHTML="";
      d.history.forEach(msg=>{
        if(msg.role==="user") chat.innerHTML+=`<div class="message user">${escHtml(msg.content)}</div>`;
        else chat.innerHTML+=`<div class="message ai"><div class="md-content">${marked.parse(msg.content)}</div>${getActionsHtml()}</div>`;
      });
    } else {
      chat.innerHTML=`<div class="message ai"><div class="md-content">${i18n[currentLang]["init-msg"]}</div></div>`;
    }
    chat.scrollTop=chat.scrollHeight;
    // Show export btn if has messages
    const exportBtn=document.getElementById("export-chat-btn");
    if(exportBtn) exportBtn.style.display=d.history.length>0?"flex":"none";
  } catch(e){ console.error("openChat:",e); }
}

function clearChatUI(){
  const chat=document.getElementById("chat");
  chat.innerHTML=`<div class="message ai"><div class="md-content">${i18n[currentLang]["init-msg"]}</div></div>`;
  const exportBtn=document.getElementById("export-chat-btn");
  if(exportBtn) exportBtn.style.display="none";
}

async function renameChatPrompt(chatId, currentTitle){
  const newTitle=prompt("Новое название чата:", currentTitle);
  if(!newTitle||newTitle.trim()===currentTitle) return;
  try{
    await fetch(`${BACKEND_URL}/chats/rename`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:currentUserEmail,chat_id:chatId,title:newTitle.trim()}) });
    const c=allChats.find(c=>c.id===chatId);
    if(c){ c.title=newTitle.trim(); renderChatList(allChats); }
  } catch(e){ console.error(e); }
}

async function deleteChatConfirm(chatId){
  const l=currentLang;
  const msg=l==="kk"?"Чатты жоясыз ба?":l==="en"?"Delete this chat?":"Удалить этот чат?";
  if(!confirm(msg)) return;
  try{
    await fetch(`${BACKEND_URL}/chats/delete`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:currentUserEmail,chat_id:chatId}) });
    allChats=allChats.filter(c=>c.id!==chatId);
    renderChatList(allChats);
    if(currentChatId===chatId){
      if(allChats.length>0) await openChat(allChats[0].id);
      else await createNewChat();
    }
  } catch(e){ console.error(e); }
}

// ── 4. ЭКСПОРТ ЧАТА ───────────────────────────────────────────
async function exportCurrentChat(){
  if(!currentChatId||currentUserEmail==="guest") return;
  const url=`${BACKEND_URL}/chats/export?email=${encodeURIComponent(currentUserEmail)}&chat_id=${currentChatId}`;
  const a=document.createElement("a");
  a.href=url;
  a.download=`chat_${currentChatId}.md`;
  document.body.appendChild(a); a.click(); document.body.removeChild(a);
}

// ── 5. ОСТАНОВКА ГЕНЕРАЦИИ ────────────────────────────────────
function setGenerating(v){
  isGenerating=v;
  const stopBtn=document.getElementById("stop-btn");
  const sendBtn=document.getElementById("send-btn");
  if(stopBtn){ stopBtn.classList.toggle("visible",v); }
  if(sendBtn){ sendBtn.style.display=v?"none":"flex"; }
}

function stopGeneration(){
  if(currentAbortCtrl){ currentAbortCtrl.abort(); currentAbortCtrl=null; }
  setGenerating(false);
}

// ================================================================
// ПЛАНЫ
// ================================================================
async function loadUserPlan(){
  if(currentUserEmail==="guest"){ showPlanBadge({badge:"FREE",color:"#6b7280"}); return; }
  try{
    const res=await fetch(`${BACKEND_URL}/my_plan`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:currentUserEmail}) });
    const d=await res.json();
    if(d.status==="success"){ userPlanData=d; showPlanBadge(d); updateLimitIndicators(d); updateUpgradeButtons(d); }
  } catch(e){ console.error("loadUserPlan:",e); }
}

function showPlanBadge(d){
  const el=document.getElementById("plan-badge-sidebar");
  if(!el) return;
  const badge=d.badge||"FREE", color=d.color||"#6b7280";
  el.className="plan-indicator";
  el.style.background=color+"22"; el.style.color=color; el.style.border=`1px solid ${color}44`;
  el.innerText=badge;
}

function updateLimitIndicators(d){
  if(!d||!d.usage) return;
  const bar=document.getElementById("plan-limits-bar");
  if(!bar) return;
  const msgLeft=d.limits.msg_per_day-d.usage.msg_count;
  const imgLeft=d.usage.credits_left;
  const mc=msgLeft<5?"#ef4444":msgLeft<20?"#f59e0b":"#10b981";
  const ic=imgLeft<2?"#ef4444":imgLeft<5?"#f59e0b":"#10b981";
  const showUpg=!["premium","admin"].includes(d.plan);
  bar.style.display="flex";
  bar.innerHTML=`
    <div class="limit-row">
      <span>💬 ${currentLang==="kk"?"Хабарламалар":currentLang==="en"?"Messages":"Сообщения"}</span>
      <span style="color:${mc};font-weight:700;">${Math.max(0,msgLeft)}/${d.limits.msg_per_day}</span>
    </div>
    <div class="limit-row">
      <span>🖼 ${currentLang==="kk"?"Суреттер":currentLang==="en"?"Images":"Изображения"}</span>
      <span style="color:${ic};font-weight:700;">${imgLeft}/${d.limits.images_per_day}</span>
    </div>
    ${d.expires?`<div style="color:#555;font-size:10px;">${currentLang==="en"?"Expires":"Истекает"}: ${d.expires}</div>`:""}
    ${showUpg?`<button class="upgrade-mini-btn" onclick="showUpgradeModal('pro')">⬆ ${currentLang==="kk"?"Жоспарды арттыру":currentLang==="en"?"Upgrade plan":"Upgrade план"}</button>`:""}
  `;
}

function updateUpgradeButtons(d){
  if(!d) return;
  const show=!["premium","admin"].includes(d.plan);
  const pb=document.getElementById("profile-upgrade-btn");
  if(pb) pb.style.display=show?"block":"none";
  const tb=document.getElementById("upgrade-tool-btn");
  if(tb) tb.style.display=show?"flex":"none";
  const planEl=document.getElementById("profile-plan-badge");
  if(planEl&&d.badge){
    planEl.innerHTML=`
      <span style="display:inline-block;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700;letter-spacing:1px;background:${d.color}22;color:${d.color};border:1px solid ${d.color}44;">${d.badge} — ${d.name}</span>
      ${d.expires?`<span style="color:#555;font-size:12px;margin-left:8px;">до ${d.expires}</span>`:""}
    `;
  }
}

function showUpgradeModal(plan){
  selectedUpgradePlan=plan;
  const INFO={
    pro:{ badge:"PRO", bg:"rgba(59,130,246,0.2)", color:"#3b82f6", title:"Daryn AI Pro", price:"$9.99 / мес" },
    premium:{ badge:"PREMIUM", bg:"rgba(245,158,11,0.2)", color:"#f59e0b", title:"Daryn AI Premium", price:"$24.99 / мес" }
  };
  const d=INFO[plan]; if(!d) return;
  const be=document.getElementById("upgrade-badge");
  be.innerText=d.badge; be.style.background=d.bg; be.style.color=d.color;
  document.getElementById("upgrade-title").innerText=d.title;
  const pe=document.getElementById("upgrade-price");
  pe.innerText=d.price; pe.style.color=d.color;
  document.getElementById("upgrade-error").style.display="none";
  document.getElementById("upgrade-success").style.display="none";
  document.getElementById("tx-id-input").value="";
  document.getElementById("wallet-address").innerText="TXXXXXXXXXXYourWalletAddressHere";
  document.getElementById("upgrade-modal").style.display="flex";
}

function closeUpgradeModal(){
  document.getElementById("upgrade-modal").style.display="none";
  selectedUpgradePlan=null;
}

async function confirmUpgrade(){
  if(!selectedUpgradePlan) return;
  if(currentUserEmail==="guest"){
    document.getElementById("upgrade-error").innerText=currentLang==="en"?"Please log in":currentLang==="kk"?"Жүйеге кіріңіз":"Войдите в систему";
    document.getElementById("upgrade-error").style.display="block"; return;
  }
  const txId=document.getElementById("tx-id-input").value.trim();
  const err=document.getElementById("upgrade-error");
  const succ=document.getElementById("upgrade-success");
  const btn=document.getElementById("upgrade-confirm-btn");
  if(!txId){ err.innerText=currentLang==="en"?"Enter TX ID":currentLang==="kk"?"TX ID енгізіңіз":"Введите ID транзакции"; err.style.display="block"; return; }
  btn.innerText="⏳..."; btn.disabled=true;
  try{
    const res=await fetch(`${BACKEND_URL}/upgrade_plan`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:currentUserEmail,plan:selectedUpgradePlan,tx_id:txId}) });
    const d=await res.json();
    if(d.status==="success"){
      err.style.display="none";
      succ.innerText=currentLang==="en"?"✅ Request sent! Wait up to 24h.":currentLang==="kk"?"✅ Өтінім жіберілді! 24 сағат күтіңіз.":"✅ Заявка отправлена! Ожидайте до 24 часов.";
      succ.style.display="block";
      setTimeout(closeUpgradeModal,3000);
    } else { err.innerText=d.message; err.style.display="block"; }
  } catch { err.innerText=currentLang==="en"?"Connection error":currentLang==="kk"?"Қосылу қатесі":"Ошибка подключения"; err.style.display="block"; }
  finally { btn.innerText=i18n[currentLang]["upg-btn"]; btn.disabled=false; }
}

// ================================================================
// ПРОФИЛЬ
// ================================================================
function openProfile(){
  if(currentUserEmail==="guest") return;
  document.getElementById("profile-email").innerText=currentUserEmail;
  document.getElementById("profile-name-input").value=document.getElementById("sidebar-username").innerText;
  document.getElementById("profile-overlay").style.display="block";
  document.getElementById("profile-modal").style.display="block";
  document.getElementById("profile-error").style.display="none";
  document.getElementById("profile-success").style.display="none";
  if(userPlanData) updateUpgradeButtons(userPlanData);
  if(window.innerWidth<=768) toggleSidebar();
}

function closeProfile(){
  document.getElementById("profile-overlay").style.display="none";
  document.getElementById("profile-modal").style.display="none";
}

async function saveProfile(){
  const n=document.getElementById("profile-name-input").value.trim();
  const err=document.getElementById("profile-error");
  const succ=document.getElementById("profile-success");
  if(!n){ err.innerText="Error"; err.style.display="block"; succ.style.display="none"; return; }
  try{
    const res=await fetch(`${BACKEND_URL}/update_profile`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:currentUserEmail,new_username:n}) });
    const d=await res.json();
    if(d.status==="success"){ document.getElementById("sidebar-username").innerText=n; err.style.display="none"; succ.innerText="✅ OK"; succ.style.display="block"; setTimeout(closeProfile,1500); }
    else { err.innerText=d.message; err.style.display="block"; succ.style.display="none"; }
  } catch { err.innerText="Network Error."; err.style.display="block"; succ.style.display="none"; }
}

async function clearUserHistory(){
  if(!confirm("Delete DB?")) return;
  const err=document.getElementById("profile-error");
  const succ=document.getElementById("profile-success");
  try{
    const res=await fetch(`${BACKEND_URL}/clear_history`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({email:currentUserEmail}) });
    const d=await res.json();
    if(d.status==="success"){
      clearChatUI();
      allChats=[]; renderChatList(allChats);
      err.style.display="none"; succ.innerText="✅ OK!"; succ.style.display="block";
      setTimeout(closeProfile,1500);
    } else { err.innerText=d.message; err.style.display="block"; succ.style.display="none"; }
  } catch { err.innerText="Network Error."; err.style.display="block"; succ.style.display="none"; }
}

// ================================================================
// MESSAGE ACTIONS
// ================================================================
const getActionsHtml=()=>`
  <div class="message-actions">
    <button class="action-btn" onclick="copyMessageText(this)" title="Копировать">
      <svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
    </button>
    <button class="action-btn" onclick="rateMessage(this,'good')" title="Хороший ответ">
      <svg viewBox="0 0 24 24"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg>
    </button>
    <button class="action-btn" onclick="rateMessage(this,'bad')" title="Плохой ответ">
      <svg viewBox="0 0 24 24"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3zm7-13h3a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-3"></path></svg>
    </button>
    <button class="action-btn" onclick="regenerateMessage()" title="Повторить">
      <svg viewBox="0 0 24 24"><polyline points="23 4 23 10 17 10"></polyline><polyline points="1 20 1 14 7 14"></polyline><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"></path></svg>
    </button>
  </div>
`;

function copyMessageText(btn){
  const md=btn.closest(".message.ai").querySelector(".md-content");
  navigator.clipboard.writeText(md.innerText.trim());
  const orig=btn.innerHTML;
  btn.innerHTML=`<svg viewBox="0 0 24 24" stroke="#10b981"><polyline points="20 6 9 17 4 12"></polyline></svg>`;
  setTimeout(()=>btn.innerHTML=orig,2000);
}

function rateMessage(btn,type){
  btn.parentElement.querySelectorAll(".action-btn").forEach(b=>{ b.classList.remove("active-good","active-bad"); });
  btn.classList.add(type==="good"?"active-good":"active-bad");
}

function regenerateMessage(){
  if(!lastUserMessage) return;
  document.getElementById("user-input").value=lastUserMessage;
  sendMessage();
}

// ================================================================
// ФАЙЛЫ
// ================================================================
function handleFileSelect(event){
  const file=event.target.files[0];
  if(!file) return;
  if(file.size>100*1024*1024){ alert("File too large!"); event.target.value=""; return; }
  const reader=new FileReader();
  reader.onload=function(e){
    attachedFile={ name:file.name, type:file.type||"application/octet-stream", data:e.target.result.split(",")[1] };
    document.getElementById("fname-text").innerText=file.name;
    document.getElementById("file-preview").style.display="flex";
  };
  reader.readAsDataURL(file);
}

function removeFile(){
  attachedFile=null;
  document.getElementById("file-upload").value="";
  document.getElementById("file-preview").style.display="none";
}

// ================================================================
// SIDEBAR
// ================================================================
function toggleSidebar(){
  const sb=document.getElementById("sidebar"), ov=document.getElementById("sidebar-overlay");
  sb.classList.toggle("open");
  if(window.innerWidth<=768) ov.classList.toggle("active",sb.classList.contains("open"));
}

function useTool(type,event){
  if(currentMode===type){ currentMode="chat"; event.currentTarget.classList.remove("active"); }
  else { currentMode=type; document.querySelectorAll(".tool-btn").forEach(b=>b.classList.remove("active")); event.currentTarget.classList.add("active"); }
  updatePlaceholder();
  document.getElementById("user-input").focus();
}

function handleKeyPress(e){ if(e.key==="Enter") sendMessage(); }

// ================================================================
// SEND MESSAGE
// ================================================================
async function sendMessage(){
  if(isGenerating) return;
  const input=document.getElementById("user-input");
  const chat=document.getElementById("chat");
  const text=input.value.trim();
  if(text===""&&!attachedFile) return;
  lastUserMessage=text;

  // Создаём чат если нет (гость пропускает)
  if(currentUserEmail!=="guest"&&!currentChatId){
    await createNewChat();
  }

  let dm=text;
  if(attachedFile) dm=`📎 [${escHtml(attachedFile.name)}]<br>`+escHtml(text);
  else dm=escHtml(text);
  chat.innerHTML+=`<div class="message user">${dm}</div>`;
  input.value="";
  chat.scrollTop=chat.scrollHeight;

  const lid="ai-"+Date.now();
  chat.innerHTML+=`<div class="message ai" id="${lid}"><div class="md-content">${i18n[currentLang]["loading"]}</div></div>`;
  chat.scrollTop=chat.scrollHeight;

  const payload={ text, email:currentUserEmail, mode:currentMode, chat_id:currentChatId,
    file_name:attachedFile?attachedFile.name:null, file_type:attachedFile?attachedFile.type:null, file_data:attachedFile?attachedFile.data:null };
  removeFile();

  currentAbortCtrl=new AbortController();
  setGenerating(true);

  try{
    const response=await fetch(`${BACKEND_URL}/chat`,{ method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload), signal:currentAbortCtrl.signal });
    const msgEl=document.getElementById(lid);
    const mdC=msgEl.querySelector(".md-content");

    if(currentMode==="image"){
      mdC.innerHTML=await response.text();
      chat.scrollTop=chat.scrollHeight;
      if(currentUserEmail!=="guest") await loadUserPlan();
      setGenerating(false);
      // Show export btn
      const exportBtn=document.getElementById("export-chat-btn");
      if(exportBtn) exportBtn.style.display="flex";
      return;
    }

    const reader=response.body.getReader(), decoder=new TextDecoder("utf-8");
    mdC.innerHTML="";
    let cq=[], ia=false, cam="";
    function pq(){
      if(cq.length>0){ ia=true; cam+=cq.shift(); mdC.innerHTML=marked.parse(cam); chat.scrollTop=chat.scrollHeight; setTimeout(pq,15); }
      else { ia=false; }
    }
    while(true){
      const {done,value}=await reader.read();
      if(done){
        const ck=setInterval(()=>{
          if(!ia){
            clearInterval(ck);
            msgEl.innerHTML+=getActionsHtml();
            chat.scrollTop=chat.scrollHeight;
            setGenerating(false);
            if(currentUserEmail!=="guest") loadUserPlan();
            // Show export btn & refresh chat list for auto-title
            const exportBtn=document.getElementById("export-chat-btn");
            if(exportBtn) exportBtn.style.display="flex";
            setTimeout(()=>refreshChatTitles(),1500);
          }
        },50);
        break;
      }
      cq.push(...decoder.decode(value,{stream:true}).split(""));
      if(!ia) pq();
    }
  } catch(e){
    if(e.name==="AbortError"){
      const msgEl=document.getElementById(lid);
      if(msgEl){
        const mdC=msgEl.querySelector(".md-content");
        if(mdC&&!mdC.innerText.trim()) mdC.innerHTML=`<span style="color:#888;">[Генерация остановлена]</span>`;
        msgEl.innerHTML+=getActionsHtml();
      }
    } else {
      const el=document.getElementById(lid);
      if(el) el.querySelector(".md-content").innerHTML=`<span style="color:#ef4444;">${i18n[currentLang]["sys-err"]}</span>`;
    }
    setGenerating(false);
  }
}

// Refresh chat list titles (after auto-naming)
async function refreshChatTitles(){
  if(currentUserEmail==="guest"||!currentChatId) return;
  try{
    const res=await fetch(`${BACKEND_URL}/chats?email=${encodeURIComponent(currentUserEmail)}`);
    const d=await res.json();
    if(d.status==="success"){
      allChats=d.chats;
      renderChatList(allChats);
    }
  } catch {}
}

// ================================================================
// ГОЛОСОВОЙ ЧАТ
// ================================================================
let mediaRecorder=null, audioChunks=[], isRecording=false;

function setVoiceState(state){
  const btn=document.getElementById("voice-btn");
  const iM=document.getElementById("voice-icon-mic");
  const iS=document.getElementById("voice-icon-stop");
  const iSp=document.getElementById("voice-icon-spin");
  btn.classList.remove("recording","processing");
  iM.style.display=iS.style.display=iSp.style.display="none";
  if(state==="idle"){ iM.style.display="block"; btn.disabled=false; }
  else if(state==="recording"){ btn.classList.add("recording"); iS.style.display="block"; btn.disabled=false; }
  else if(state==="processing"){ btn.classList.add("processing"); iSp.style.display="block"; btn.disabled=true; }
}

async function toggleVoiceRecording(){ if(isRecording) stopRecording(); else await startRecording(); }

async function startRecording(){
  try{
    const stream=await navigator.mediaDevices.getUserMedia({audio:true});
    const mt=MediaRecorder.isTypeSupported("audio/webm;codecs=opus")?"audio/webm;codecs=opus":MediaRecorder.isTypeSupported("audio/webm")?"audio/webm":"audio/ogg";
    mediaRecorder=new MediaRecorder(stream,{mimeType:mt});
    audioChunks=[];
    mediaRecorder.ondataavailable=e=>{ if(e.data.size>0) audioChunks.push(e.data); };
    mediaRecorder.onstop=async()=>{ stream.getTracks().forEach(t=>t.stop()); await sendAudioToServer(mt); };
    mediaRecorder.start(250);
    isRecording=true; setVoiceState("recording");
  } catch {
    alert(currentLang==="kk"?"Микрофонға қол жоқ.":currentLang==="en"?"Microphone access denied.":"Нет доступа к микрофону.");
    setVoiceState("idle");
  }
}

function stopRecording(){ if(mediaRecorder&&isRecording){ isRecording=false; mediaRecorder.stop(); setVoiceState("processing"); } }

async function sendAudioToServer(mt){
  const input=document.getElementById("user-input");
  try{
    const bm=mt.split(";")[0];
    const blob=new Blob(audioChunks,{type:bm});
    if(blob.size<1000){ setVoiceState("idle"); return; }
    const fd=new FormData(); fd.append("file",blob,"audio.webm");
    const res=await fetch(`${BACKEND_URL}/transcribe`,{method:"POST",body:fd});
    const d=await res.json();
    if(d.status==="success"&&d.text&&d.text.trim()){ input.value=d.text.trim(); setVoiceState("idle"); sendMessage(); }
    else { input.placeholder=currentLang==="kk"?"⚠ Тану мүмкін болмады":currentLang==="en"?"⚠ Could not recognize":"⚠ Не удалось распознать"; setVoiceState("idle"); setTimeout(()=>updatePlaceholder(),2500); }
  } catch { input.placeholder=currentLang==="kk"?"⚠ Сервер қатесі":currentLang==="en"?"⚠ Server error":"⚠ Ошибка сервера"; setVoiceState("idle"); setTimeout(()=>updatePlaceholder(),2500); }
}

// ================================================================
// СКАЧАТЬ ИЗОБРАЖЕНИЕ
// ================================================================
async function downloadGeneratedImage(url,name){
  try{
    const r=await fetch(url), b=await r.blob();
    const bu=URL.createObjectURL(b);
    const a=document.createElement("a"); a.href=bu; a.download=name;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(bu);
  } catch { alert(currentLang==="kk"?"Жүктеу мүмкін болмады.":currentLang==="en"?"Failed to download.":"Не удалось скачать."); }
}

// ================================================================
// UTILS
// ================================================================
function escHtml(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;"); }
