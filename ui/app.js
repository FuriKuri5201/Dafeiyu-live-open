let currentConfig = {};
let isLive = false;

const $ = (id) => document.getElementById(id);

function toast(msg, ms = 2600) {
  const el = $('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => el.classList.remove('show'), ms);
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  });
  return res.json();
}

// 顶部标签页切换
document.querySelectorAll('.tab-btn').forEach((btn) => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab-btn').forEach((b) => b.classList.remove('active'));
    document.querySelectorAll('.tab').forEach((t) => t.classList.remove('active'));
    btn.classList.add('active');
    $('tab-' + btn.dataset.tab).classList.add('active');
  });
});

function togglePwd(id) {
  const el = $(id);
  el.type = el.type === 'password' ? 'text' : 'password';
}

function toggleTheme() {
  const isLight = document.body.classList.toggle('light');
  localStorage.setItem('dfyzb_theme', isLight ? 'light' : 'dark');
  const btn = $('btnTheme');
  if (btn) btn.textContent = isLight ? '🌙' : '☀️';
}

if (localStorage.getItem('dfyzb_theme') === 'light') {
  document.body.classList.add('light');
  const btn = $('btnTheme');
  if (btn) btn.textContent = '🌙';
}

function applyLlmPreset(name) {
  const presets = {
    deepseek: { base: 'https://api.deepseek.com/v1', model: 'deepseek-chat' },
    qwen: { base: 'https://dashscope.aliyuncs.com/compatible-mode/v1', model: 'qwen-plus' },
    openai: { base: 'https://api.openai.com/v1', model: 'gpt-4o-mini' },
    ollama: { base: 'http://127.0.0.1:11434/v1', model: 'qwen2.5:7b' },
  };
  const p = presets[name];
  if (!p) return;
  $('llm_base_url').value = p.base;
  $('llm_model').value = p.model;
  toast(`已填充 ${name} 预设，请填入对应 Key 并保存`);
}

function updateTtsHints() {
  const p = $('tts_provider').value;
  if (p === 'edge' && !$('tts_voice').value) $('tts_voice').value = 'zh-CN-XiaoxiaoNeural';
  if (p === 'cosyvoice') {
    if (!$('tts_model').value) $('tts_model').value = 'cosyvoice-v2';
    if ($('tts_voice').value.startsWith('zh-CN-')) $('tts_voice').value = 'longxiaochun_v2';
  }
  if (p === 'openai') {
    if (!$('tts_model').value) $('tts_model').value = 'tts-1';
    if ($('tts_voice').value.startsWith('zh-CN-')) $('tts_voice').value = 'alloy';
  }
}

function fillForm(cfg) {
  currentConfig = cfg;
  const llm = cfg.llm || {};
  const tts = cfg.tts || {};
  const draw = cfg.draw || {};
  const st = cfg.streamer || {};
  const col = cfg.collectors || {};
  const dy = col.douyin || {};
  const bi = col.bilibili || {};
  const mus = cfg.music || {};
  const gift = cfg.gift || {};
  const feats = cfg.features || {};

  $('llm_base_url').value = llm.base_url || '';
  $('llm_model').value = llm.model || '';
  $('llm_api_key').value = llm.api_key || '';
  $('llm_memory_enable').checked = !!llm.memory_enable;
  $('llm_memory_turns').value = llm.memory_turns ?? 12;

  $('streamer_name').value = st.name || '大肥鱼AI';
  $('streamer_persona').value = st.persona || '';
  $('reply_cooldown_sec').value = st.reply_cooldown_sec ?? 3.0;

  $('tts_provider').value = tts.provider || 'edge';
  $('tts_api_key').value = tts.api_key || '';
  $('tts_base_url').value = tts.base_url || '';
  $('tts_model').value = tts.model || (tts.provider === 'cosyvoice' ? tts.cosy_model : tts.openai_model) || '';
  $('tts_voice').value = tts.voice || 'zh-CN-XiaoxiaoNeural';
  $('tts_rate').value = tts.rate || '+5%';

  $('draw_provider').value = draw.provider || 'wanx';
  $('draw_base_url').value = draw.base_url || '';
  $('draw_api_key').value = draw.api_key || '';
  $('draw_model').value = draw.model || '';
  $('draw_style_prompt').value = draw.style_prompt || '';
  $('draw_reuse_tts_key').checked = draw.reuse_tts_key !== false;

  $('dy_room_url').value = dy.room_url || '';
  $('dy_headless').checked = !!dy.headless;
  $('bili_room_id').value = bi.room_id || '';
  $('bili_headless').checked = !!bi.headless;
  $('browser_path').value = col.browser_path || '';

  $('music_dirs').value = (mus.dirs || ['music']).join('\n');
  $('music_volume').value = mus.volume ?? 0.45;
  $('music_duck_volume').value = mus.duck_volume ?? 0.14;
  $('music_auto_next').checked = mus.auto_next !== false;

  $('gift_template').value = gift.thank_template || '';
  $('gift_thank_enable').checked = gift.thank_enable !== false;
  $('gift_use_llm').checked = !!gift.use_llm_thank;

  const vts = cfg.vts || {};
  $('vts_host').value = vts.host || '127.0.0.1';
  $('vts_port').value = vts.port ?? 8001;
  $('vts_mouth_param').value = vts.mouth_param || 'MouthOpen';

  document.querySelectorAll('input[data-feature]').forEach((cb) => {
    cb.checked = !!feats[cb.dataset.feature];
  });
}

function collectForm() {
  const cfg = structuredClone(currentConfig || {});
  cfg.llm = {
    ...(cfg.llm || {}),
    base_url: $('llm_base_url').value.trim(),
    model: $('llm_model').value.trim(),
    api_key: $('llm_api_key').value.trim(),
    memory_enable: $('llm_memory_enable').checked,
    memory_turns: Number($('llm_memory_turns').value || 12),
  };
  cfg.streamer = {
    ...(cfg.streamer || {}),
    name: $('streamer_name').value.trim() || '大肥鱼AI',
    persona: $('streamer_persona').value.trim(),
    reply_cooldown_sec: Number($('reply_cooldown_sec').value || 3.0),
  };
  const ttsProv = $('tts_provider').value;
  cfg.tts = {
    ...(cfg.tts || {}),
    provider: ttsProv,
    api_key: $('tts_api_key').value.trim(),
    base_url: $('tts_base_url').value.trim(),
    model: $('tts_model').value.trim(),
    voice: $('tts_voice').value.trim(),
    rate: $('tts_rate').value.trim() || '+5%',
    cosy_model: ttsProv === 'cosyvoice' ? ($('tts_model').value.trim() || 'cosyvoice-v2') : (cfg.tts?.cosy_model || 'cosyvoice-v2'),
    cosy_voice: ttsProv === 'cosyvoice' ? ($('tts_voice').value.trim() || 'longxiaochun_v2') : (cfg.tts?.cosy_voice || 'longxiaochun_v2'),
    openai_model: ttsProv === 'openai' ? ($('tts_model').value.trim() || 'tts-1') : (cfg.tts?.openai_model || 'tts-1'),
    openai_voice: ttsProv === 'openai' ? ($('tts_voice').value.trim() || 'alloy') : (cfg.tts?.openai_voice || 'alloy'),
  };
  cfg.draw = {
    ...(cfg.draw || {}),
    provider: $('draw_provider').value,
    base_url: $('draw_base_url').value.trim(),
    api_key: $('draw_api_key').value.trim(),
    model: $('draw_model').value.trim(),
    style_prompt: $('draw_style_prompt').value.trim(),
    reuse_tts_key: $('draw_reuse_tts_key').checked,
  };
  cfg.collectors = {
    ...(cfg.collectors || {}),
    browser_path: $('browser_path').value.trim(),
    douyin: {
      ...(cfg.collectors?.douyin || {}),
      room_url: $('dy_room_url').value.trim(),
      headless: $('dy_headless').checked,
    },
    bilibili: {
      ...(cfg.collectors?.bilibili || {}),
      room_id: $('bili_room_id').value.trim(),
      headless: $('bili_headless').checked,
    },
  };
  cfg.music = {
    ...(cfg.music || {}),
    dirs: $('music_dirs').value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean),
    volume: Number($('music_volume').value || 0.45),
    duck_volume: Number($('music_duck_volume').value || 0.14),
    auto_next: $('music_auto_next').checked,
  };
  cfg.gift = {
    ...(cfg.gift || {}),
    thank_template: $('gift_template').value.trim(),
    thank_enable: $('gift_thank_enable').checked,
    use_llm_thank: $('gift_use_llm').checked,
  };
  cfg.vts = {
    ...(cfg.vts || {}),
    host: $('vts_host').value.trim() || '127.0.0.1',
    port: Number($('vts_port').value || 8001),
    mouth_param: $('vts_mouth_param').value.trim() || 'MouthOpen',
  };
  cfg.features = cfg.features || {};
  document.querySelectorAll('input[data-feature]').forEach((cb) => {
    cfg.features[cb.dataset.feature] = cb.checked;
  });
  return cfg;
}

async function saveConfig(silent = false) {
  const cfg = collectForm();
  const r = await api('/api/config', { method: 'POST', body: JSON.stringify(cfg) });
  if (r.ok) {
    currentConfig = r.config;
    if (!silent) toast('✅ 配置已保存');
  }
  return r.ok;
}

$('btnSave').addEventListener('click', () => saveConfig(false));

async function toggleLive() {
  await saveConfig(true);
  if (!isLive) {
    const r = await api('/api/live/start', { method: 'POST' });
    toast(r.message || '已启动');
  } else {
    const r = await api('/api/live/stop', { method: 'POST' });
    toast(r.message || '已停止');
  }
  refreshStatus();
}

// 独立模块开关
document.querySelectorAll('input[data-feature]').forEach((cb) => {
  cb.addEventListener('change', async () => {
    await saveConfig(true);
    const name = cb.dataset.feature;
    const r = await api(`/api/feature/${name}`, {
      method: 'POST',
      body: JSON.stringify({ enabled: cb.checked }),
    });
    if (!r.ok) cb.checked = false;
    toast(r.message || (r.ok ? '已更新' : '操作失败'));
    refreshStatus();
  });
});

// 测试与动作函数
async function testLLM() {
  await saveConfig(true);
  toast('正在测试对话模型连通性...');
  const r = await api('/api/test/llm', { method: 'POST' });
  if (r.ok) toast('✅ 回复成功：' + r.reply.slice(0, 40), 4000);
  else toast('❌ 失败：' + r.error, 4500);
}

async function testTTS() {
  await saveConfig(true);
  toast('正在合成并播报测试语音...');
  const r = await api('/api/test/tts', {
    method: 'POST',
    body: JSON.stringify({ text: `你好呀，我是${$('streamer_name').value || 'AI主播'}，语音测试一切正常！` }),
  });
  if (r.ok) toast('✅ 语音播报完成');
  else toast('❌ 语音失败：' + (r.error || '未知错误'), 4000);
}

async function testDraw() {
  await saveConfig(true);
  const r = await api('/api/test/draw', {
    method: 'POST',
    body: JSON.stringify({ prompt: '一只戴着耳机直播的赛博朋克小橘猫' }),
  });
  toast(r.message || (r.ok ? '已提交测试画作' : '画室测试失败'), 3500);
}

async function sendQuickTest() {
  await saveConfig(true);
  const text = $('quick_test_text').value.trim();
  if (!text) return;
  const r = await api('/api/test/event', {
    method: 'POST',
    body: JSON.stringify({ kind: 'comment', user: '测试观众', text }),
  });
  if (r.ok) toast('💬 已发送测试弹幕，稍等 AI 回复~');
}

async function sendSimComment() {
  await saveConfig(true);
  const r = await api('/api/test/event', {
    method: 'POST',
    body: JSON.stringify({
      kind: 'comment',
      user: $('sim_user').value.trim() || '测试观众',
      text: $('sim_text').value.trim(),
    }),
  });
  if (r.ok) toast('💬 已注入测试弹幕');
}

async function sendSimGift() {
  await saveConfig(true);
  const r = await api('/api/test/event', {
    method: 'POST',
    body: JSON.stringify({
      kind: 'gift',
      user: $('sim_gift_user').value.trim() || '老板',
      gift: $('sim_gift_name').value.trim() || '小心心',
      count: Number($('sim_gift_count').value || 1),
    }),
  });
  if (r.ok) toast('🎁 已注入测试礼物');
}

async function openMusicDir() {
  const r = await api('/api/music/open_dir', { method: 'POST' });
  toast(r.ok ? '📂 已打开本地曲库文件夹' : ('❌ 打开失败：' + (r.error || '未知错误')));
}

async function scanMusic() {
  await saveConfig(true);
  const r = await api('/api/music/scan', { method: 'POST' });
  toast(r.message || '扫描完成');
  refreshStatus();
}

async function skipMusic() {
  const r = await api('/api/music/skip', { method: 'POST' });
  toast(r.message || '已切歌');
}

async function clearMemory() {
  const r = await api('/api/memory/clear', { method: 'POST' });
  toast(r.message || '已清空');
}

async function resetGifts() {
  const r = await api('/api/gift/reset', { method: 'POST' });
  toast(r.message || '已重置');
}

function renderObsList() {
  const base = location.origin;
  const pages = [
    { name: '💬 OBS 透明弹幕板', url: `${base}/stage/danmaku.html`, desc: '实时滚动显示抖音/B站弹幕' },
    { name: '🎙️ OBS 主播实时字幕', url: `${base}/stage/subtitle.html`, desc: 'AI 开口说话时底部浮现字幕' },
    { name: '🎁 OBS 礼物播报 & 贡献榜', url: `${base}/stage/gift_board.html`, desc: '礼物横幅与本场排行榜' },
    { name: '🎵 OBS 点歌单 / 当前播放', url: `${base}/stage/playlist.html`, desc: '展示正在播放的歌曲与队列' },
    { name: '🎨 OBS AI 画室画板', url: `${base}/stage/draw.html`, desc: '展示观众点画的最新 AI 作品' },
  ];
  $('obsList').innerHTML = pages.map((p) => `
    <div class="obs-item">
      <div class="obs-info">
        <div class="obs-name">${p.name} <span class="muted">· ${p.desc}</span></div>
        <div class="obs-url">${p.url}</div>
      </div>
      <div style="display:flex;gap:8px;">
        <button class="btn small secondary" onclick="copyUrl('${p.url}')">复制地址</button>
        <button class="btn small primary" onclick="window.open('${p.url}', '_blank')">预览</button>
      </div>
    </div>
  `).join('');
}

function copyUrl(url) {
  navigator.clipboard.writeText(url).then(() => toast('📋 已复制 OBS 地址'));
}

function setStateLabel(id, running, text) {
  const el = $(id);
  if (!el) return;
  el.textContent = text;
  el.classList.toggle('on', !!running);
}

async function refreshStatus() {
  try {
    const r = await api('/api/status');
    if (!r.ok) return;
    isLive = !!r.live_active;
    const badge = $('liveBadge');
    const btn = $('btnLive');
    const btnTop = $('btnLiveTop');
    badge.textContent = isLive ? '● LIVE ON AIR' : '○ 待机中';
    badge.className = 'badge ' + (isLive ? 'live' : 'idle');
    if (btn) {
      btn.textContent = isLive ? '⏹ 一键停播' : '🚀 保存并一键开播';
      btn.className = 'btn hero-live' + (isLive ? ' danger' : '');
    }
    if (btnTop) {
      btnTop.textContent = isLive ? '⏹ 停播' : '🚀 一键开播';
      btnTop.className = 'btn ' + (isLive ? 'danger' : 'primary');
    }

    const f = r.features || {};
    setStateLabel('st-douyin', f.douyin?.running, f.douyin?.running ? `运行中 · 已收 ${f.douyin.events} 条` : '未启动');
    setStateLabel('st-bilibili', f.bilibili?.running, f.bilibili?.running ? `运行中 · 已收 ${f.bilibili.events} 条` : '未启动');
    setStateLabel('st-chat', f.chat?.running, f.chat?.running ? (f.chat.speaking ? '播报中...' : '已开启') : '已暂停');
    setStateLabel('st-gift', f.gift?.running, f.gift?.running ? `已开启 · 本场 ${f.gift.total_count} 个` : '已暂停');
    setStateLabel('st-music', f.music?.running, f.music?.running ? `运行中 · 曲库 ${f.music.library_count} 首` : `未启动 · 曲库 ${f.music?.library_count ?? 0} 首`);
    setStateLabel('st-draw', f.draw?.running, f.draw?.running ? `运行中 · 排队 ${f.draw.queued}` : '未启动');
    setStateLabel('st-vts', f.vts?.connected, f.vts?.connected ? '已连接 VTube Studio' : (f.vts?.running ? '连接中/待授权...' : '未连接'));
    setStateLabel('st-obs_stage', f.obs_stage?.running, f.obs_stage?.running ? `已开启 · ${f.obs_stage.clients} 个页面连接` : '已暂停');
  } catch {}
}

async function refreshLogs() {
  try {
    const r = await api('/api/logs');
    if (!r.ok) return;
    const logs = r.logs || [];
    $('logCount').textContent = `${logs.length} 条`;
    const box = $('logBox');
    const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    box.innerHTML = logs.map((l) => `<div class="log-line ${l.level}">[${l.ts}] ${l.message}</div>`).join('');
    if (atBottom) box.scrollTop = box.scrollHeight;
  } catch {}
}

(async function init() {
  const r = await api('/api/config');
  if (r.ok) fillForm(r.config);
  renderObsList();
  refreshStatus();
  refreshLogs();
  setInterval(refreshStatus, 2500);
  setInterval(refreshLogs, 2000);
})();
