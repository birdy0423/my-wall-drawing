/* One virtual board; offscreen pixels are authoritative, including exports. */
const VIRTUAL_WIDTH = 1920, VIRTUAL_HEIGHT = 1080;
const params = new URLSearchParams(location.search);
const room = params.get("room") || "room1";
const name = params.get("name") || ("user_" + crypto.randomUUID());
const canvas = document.getElementById("canvas"), ctx = canvas.getContext("2d");
const offscreen = document.createElement("canvas");
offscreen.width = VIRTUAL_WIDTH; offscreen.height = VIRTUAL_HEIGHT;
const offCtx = offscreen.getContext("2d");
const storyBox = document.getElementById("storyBox");
const storyButton = document.getElementById("aiStory");
let currentLang = "zh", mode = "pen", currentColor = "#000000", currentSize = 5;
let leftOpen = true, rightOpen = true, connected = false, drawing = false;
let lastX = 0, lastY = 0, strokeId = null, pointerId = null;
let frame = null, dirty = false, stopped = false, renderCount = 0, receivedDrawCount = 0;
let storyController = null;
const remotePaths = new Map();
const connectionStatus = document.createElement("div");
connectionStatus.id = "connectionStatus";
connectionStatus.setAttribute("role", "status");
connectionStatus.style.cssText = "position:fixed;top:12px;left:50%;transform:translateX(-50%);z-index:10000;background:#7f1d1d;color:white;padding:8px 14px;border-radius:8px;pointer-events:none";
document.body.appendChild(connectionStatus);

function scheduleRender() {
  dirty = true;
  if (!stopped && frame === null) frame = requestAnimationFrame(render);
}
function render() {
  frame = null;
  if (stopped || !dirty) return;
  dirty = false;
  ctx.clearRect(0, 0, VIRTUAL_WIDTH, VIRTUAL_HEIGHT);
  ctx.drawImage(offscreen, 0, 0);
  renderCount++;
  window.dispatchEvent(new Event("showwall:canvas-rendered"));
}
function drawLine(x1, y1, x2, y2, brush, color, size) {
  offCtx.lineCap = "round"; offCtx.lineJoin = "round";
  offCtx.lineWidth = Math.max(1, Math.min(100, Number(size) || 5));
  offCtx.strokeStyle = brush === "eraser" ? "#fff" : color;
  offCtx.beginPath(); offCtx.moveTo(x1, y1); offCtx.lineTo(x2, y2); offCtx.stroke();
  scheduleRender();
}
function clearBoard() {
  drawing = false; strokeId = null;
  remotePaths.clear();
  offCtx.clearRect(0, 0, VIRTUAL_WIDTH, VIRTUAL_HEIGHT);
  scheduleRender();
}
function resize() {
  if (canvas.width !== VIRTUAL_WIDTH) canvas.width = VIRTUAL_WIDTH;
  if (canvas.height !== VIRTUAL_HEIGHT) canvas.height = VIRTUAL_HEIGHT;
  const leftW = leftOpen ? 200 : 0, rightW = rightOpen ? 160 : 0;
  const scale = Math.max(0.01, Math.min((window.innerWidth-leftW-rightW)/VIRTUAL_WIDTH, window.innerHeight/VIRTUAL_HEIGHT));
  canvas.style.width = VIRTUAL_WIDTH*scale + "px";
  canvas.style.height = VIRTUAL_HEIGHT*scale + "px";
  canvas.style.left = "calc(50% + " + (leftW-rightW)/2 + "px)";
  scheduleRender();
}
function connectionChanged(online, text) {
  connected = online;
  connectionStatus.textContent = text;
  connectionStatus.style.display = online ? "none" : "block";
  canvas.style.pointerEvents = online ? "auto" : "none";
  for (const id of ["clear", "aiTheme", "aiStory"]) document.getElementById(id).disabled = !online || (id === "aiStory" && storyController !== null);
  if (!online) {
    drawing = false; strokeId = null; remotePaths.clear();
  }
}
const ws = new WebSocket((location.protocol === "https:" ? "wss" : "ws") + "://" + location.host + "/ws/" + encodeURIComponent(room));
connectionChanged(false, "正在連線…");
ws.onopen = () => connectionChanged(true, "");
ws.onclose = () => connectionChanged(false, "連線已中斷，繪畫已暫停。請重新開啟房間以連線。");
ws.onerror = () => {
  connectionChanged(false, "連線發生錯誤，繪畫已暫停。請重新開啟房間以連線。");
  ws.close();
};
function send(data) {
  if (!connected || ws.readyState !== WebSocket.OPEN) return false;
  try { ws.send(JSON.stringify({...data, sender: name})); return true; }
  catch { connectionChanged(false, "連線中斷，繪畫已暫停。請重新開啟房間以連線。"); ws.close(); return false; }
}
ws.onmessage = e => {
  let m;
  try { m = JSON.parse(e.data); } catch { return; }
  if (!m || typeof m !== "object") return;
  if (m.type === "draw") { receivedDrawCount++; drawFromServer(m); }
  else if (m.type === "clear") clearBoard();
  else if (m.type === "topic") document.getElementById("themeText").textContent = "🎨 " + m.value;
  else if (m.type === "story") showStory("📖 " + m.title + "\n\n" + m.story);
  else if (m.type === "error") showStory(m.detail || "操作失敗，請稍後再試。");
};
function getVirtualPos(e) {
  const r = canvas.getBoundingClientRect();
  return {x: (e.clientX-r.left)*VIRTUAL_WIDTH/r.width, y: (e.clientY-r.top)*VIRTUAL_HEIGHT/r.height};
}
function drawMessage(extra = {}) {
  return {type:"draw", strokeId, mode, color:currentColor, size:currentSize, x:lastX, y:lastY, ...extra};
}
function startDraw(p) {
  if (!connected) return;
  lastX = p.x; lastY = p.y;
  strokeId = crypto.randomUUID();
  if (!send(drawMessage({begin:true}))) { strokeId = null; return; }
  drawing = true;
  drawLine(lastX, lastY, lastX, lastY, mode, currentColor, currentSize);
}
function moveDraw(p) {
  if (!drawing || !connected) return;
  const x = lastX, y = lastY;
  lastX = p.x; lastY = p.y;
  if (!send(drawMessage())) { drawing = false; return; }
  drawLine(x, y, lastX, lastY, mode, currentColor, currentSize);
}
function endDraw() {
  if (drawing && connected) send(drawMessage({end:true}));
  drawing = false; strokeId = null;
  if (pointerId !== null && canvas.hasPointerCapture(pointerId)) canvas.releasePointerCapture(pointerId);
  pointerId = null;
}
canvas.onpointerdown = e => {
  if (drawing || !connected || (e.pointerType === "mouse" && e.button !== 0)) return;
  e.preventDefault();
  pointerId = e.pointerId; canvas.setPointerCapture(pointerId);
  startDraw(getVirtualPos(e));
};
canvas.onpointermove = e => {
  if (drawing && e.pointerId === pointerId) {
    e.preventDefault();
    const points = e.getCoalescedEvents ? e.getCoalescedEvents() : [];
    for (const point of points.length ? points : [e]) moveDraw(getVirtualPos(point));
  }
};
canvas.onpointerup = e => {
  if (e.pointerId === pointerId) { if (drawing) moveDraw(getVirtualPos(e)); endDraw(); }
};
canvas.onpointercancel = e => { if (e.pointerId === pointerId) endDraw(); };
canvas.onlostpointercapture = () => endDraw();
canvas.style.touchAction = "none";

function drawFromServer(m) {
  if (m.sender === name || typeof m.sender !== "string" || !m.strokeId || !Number.isFinite(m.x) || !Number.isFinite(m.y)) return;
  const key = m.sender + ":" + m.strokeId;
  const now = Date.now();
  for (const [k, path] of remotePaths) if (now-path.at > 30000 || (m.begin && path.sender === m.sender)) remotePaths.delete(k);
  const previous = remotePaths.get(key);
  if (m.begin) drawLine(m.x, m.y, m.x, m.y, m.mode, m.color, m.size);
  else if (previous) drawLine(previous.x, previous.y, m.x, m.y, m.mode, m.color, m.size);
  if (m.end) remotePaths.delete(key);
  else remotePaths.set(key, {x:m.x, y:m.y, sender:m.sender, at:now});
}
document.getElementById("pen").onclick = () => setMode("pen");
document.getElementById("eraser").onclick = () => setMode("eraser");
function setMode(value) {
  mode = value;
  for (const id of ["pen", "eraser"]) document.getElementById(id).classList.toggle("active", id === value);
}
document.getElementById("colorPicker").oninput = e => { currentColor = e.target.value; };
document.getElementById("sizePicker").oninput = e => { currentSize = Number(e.target.value); };
document.getElementById("clear").onclick = () => {
  if (!connected) return;
  endDraw();
  if (send({type:"clear"})) clearBoard();
};
document.getElementById("save").onclick = () => {
  const a = document.createElement("a");
  a.download = "canvas_" + Date.now() + ".png"; a.href = offscreen.toDataURL(); a.click();
};
document.getElementById("aiTheme").onclick = () => send({type:"generateTheme"});
document.getElementById("langToggle").onclick = () => {
  currentLang = currentLang === "zh" ? "en" : "zh";
  document.getElementById("langToggle").textContent = currentLang === "zh" ? "🌐 中文" : "🌐 English";
};
function showStory(text) { storyBox.style.display = "block"; storyBox.textContent = text; scheduleRender(); }
storyButton.onclick = async () => {
  if (storyController || !connected) return;
  const controller = new AbortController();
  storyController = controller; storyButton.disabled = true;
  showStory("🧠 AI 生成中…");
  const timeout = setTimeout(() => controller.abort(), 65000);
  try {
    const res = await fetch("/ai/story", {
      method:"POST", headers:{"Content-Type":"application/json"}, signal:controller.signal,
      body:JSON.stringify({room, canvas:offscreen.toDataURL(), lang:currentLang})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "故事生成失敗，請稍後再試。");
    showStory("📖 " + data.title + "\n\n" + data.story);
  } catch (error) {
    if (!stopped) showStory(error.name === "AbortError" ? "故事生成逾時，請稍後再試。" : error.message || "故事生成失敗，請稍後再試。");
  } finally {
    clearTimeout(timeout);
    if (storyController === controller) storyController = null;
    storyButton.disabled = !connected;
  }
};
function toggleTools(side) {
  if (side === "left") leftOpen = !leftOpen; else rightOpen = !rightOpen;
  const open = side === "left" ? leftOpen : rightOpen;
  document.getElementById(side+"Tools").classList.toggle("closed", !open);
  document.getElementById(side+"Handle").classList.toggle("closed", !open);
  resize();
}
document.getElementById("leftHandle").onclick = () => toggleTools("left");
document.getElementById("rightHandle").onclick = () => toggleTools("right");
if (window.QRCode) QRCode.toCanvas(document.getElementById("qrCode"), location.origin + "?room=" + encodeURIComponent(room), {width:100});
document.getElementById("closeWebsite").onclick = () => {
  if (window.showwallCanvas) window.showwallCanvas.close(); else window.close();
};
window.addEventListener("resize", resize);
window.addEventListener("pageshow", () => { stopped = false; scheduleRender(); });
window.addEventListener("pagehide", () => {
  endDraw(); stopped = true;
  if (frame !== null) cancelAnimationFrame(frame);
  frame = null; remotePaths.clear(); ws.close(); storyController?.abort();
});
function canvasRuntimeMetrics() {
  return {renderCount, receivedDrawCount, remotePaths:remotePaths.size, pendingFrame:frame !== null, connected};
}
resize(); setMode("pen");
