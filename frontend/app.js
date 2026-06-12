/* ===== Configuration ===== */
const IDLE_TIMEOUT = 1500;
const IDLE_TIMEOUT_FINAL = 3000;
const DEFAULT_MODEL = "deepseek-v4-flash";

const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
const WS_URL = `${protocol}//${window.location.host}/ws`;

/* ===== State ===== */
let canvas, ctx;
let canvasObjects = [];
let nextObjectId = 0;
let undoStack = [];
let bgColor = "#ffffff";

let ws = null;
let wsReconnectTimer = null;

let recognition = null;
let isListening = false;
let speechErrorCount = 0;
const MAX_SPEECH_RETRIES = 3;
let idleTimer = null;
let lastTranscript = "";
let pendingFinal = "";
let isSpeaking = false;

/* ===== DOM refs ===== */
const $ = (id) => document.getElementById(id);
const statusDot = $("status-dot");
const statusText = $("status-text");
const modelInput = $("modelInput");
const resetModelBtn = $("resetModelBtn");
const micBtn = $("micBtn");
const listeningIndicator = $("listening-indicator");
const transcriptEl = $("transcript");
const feedbackEl = $("feedback");
const canvasSizeEl = $("canvasSize");
const objectCountEl = $("objectCount");

/* ===== Canvas ===== */
function initCanvas(width, height) {
    canvas = $("drawingCanvas");
    ctx = canvas.getContext("2d");
    resizeCanvas(width || 800, height || 600, true);
}

function resizeCanvas(w, h, resetObjects) {
    canvas.width = w;
    canvas.height = h;
    if (resetObjects) {
        canvasObjects = [];
        undoStack = [];
        nextObjectId = 0;
        bgColor = "#ffffff";
    }
    render();
    updateCanvasInfo();
}

function render() {
    if (!ctx) return;
    ctx.fillStyle = bgColor;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    for (const obj of canvasObjects) drawObject(obj);
}

function drawObject(obj) {
    ctx.fillStyle = obj.color;
    ctx.strokeStyle = obj.color;
    ctx.lineWidth = obj.stroke_width || 2;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";

    switch (obj.shape) {
        case "circle": {
            ctx.beginPath();
            ctx.arc(obj.x, obj.y, obj.radius || 50, 0, Math.PI * 2);
            ctx.closePath();
            if (obj.fill !== false) ctx.fill();
            ctx.stroke();
            break;
        }
        case "rectangle": {
            if (obj.fill !== false) ctx.fillRect(obj.x, obj.y, obj.width, obj.height);
            ctx.strokeRect(obj.x, obj.y, obj.width, obj.height);
            break;
        }
        case "triangle": {
            ctx.beginPath();
            ctx.moveTo(obj.x1, obj.y1);
            ctx.lineTo(obj.x2, obj.y2);
            ctx.lineTo(obj.x3, obj.y3);
            ctx.closePath();
            if (obj.fill !== false) ctx.fill();
            ctx.stroke();
            break;
        }
        case "line": {
            ctx.beginPath();
            ctx.moveTo(obj.x1, obj.y1);
            ctx.lineTo(obj.x2, obj.y2);
            ctx.stroke();
            break;
        }
        case "ellipse": {
            ctx.beginPath();
            ctx.ellipse(obj.x, obj.y, obj.radius_x || 40, obj.radius_y || 30, 0, 0, Math.PI * 2);
            ctx.closePath();
            if (obj.fill !== false) ctx.fill();
            ctx.stroke();
            break;
        }
        case "point": {
            ctx.beginPath();
            ctx.arc(obj.x, obj.y, obj.radius || 3, 0, Math.PI * 2);
            ctx.closePath();
            ctx.fill();
            break;
        }
        case "text": {
            const size = obj.font_size || 20;
            ctx.font = `${size}px "Microsoft YaHei", "PingFang SC", sans-serif`;
            ctx.textAlign = "center";
            ctx.textBaseline = "middle";
            ctx.fillText(obj.text || "", obj.x, obj.y);
            break;
        }
    }
}

/* ===== Command Execution ===== */
function executeCommands(response) {
    const { commands, tts_feedback } = response;

    for (const cmd of commands) {
        switch (cmd.action) {
            case "draw_shape": {
                const obj = { id: nextObjectId++, ...cmd };
                canvasObjects.push(obj);
                undoStack.push({ type: "add", id: obj.id });
                break;
            }
            case "clear_canvas": {
                undoStack.push({ type: "clear", objects: [...canvasObjects], bg: bgColor });
                canvasObjects = [];
                bgColor = "#ffffff";
                break;
            }
            case "undo": {
                const last = undoStack.pop();
                if (!last) break;
                if (last.type === "add") {
                    canvasObjects = canvasObjects.filter((o) => o.id !== last.id);
                } else if (last.type === "clear") {
                    bgColor = last.bg || "#ffffff";
                } else if (last.type === "bg") {
                    bgColor = last.prevBg || "#ffffff";
                }
                break;
            }
            case "resize_canvas": {
                const w = Math.round(cmd.width) || canvas.width;
                const h = Math.round(cmd.height) || canvas.height;
                canvas.width = w;
                canvas.height = h;
                break;
            }
            case "set_background": {
                undoStack.push({ type: "bg", prevBg: bgColor });
                bgColor = cmd.color || "#ffffff";
                break;
            }
            case "add_text": {
                const textObj = { id: nextObjectId++, ...cmd, shape: "text" };
                canvasObjects.push(textObj);
                undoStack.push({ type: "add", id: textObj.id });
                break;
            }
            case "error":
                break;
        }
    }

    render();
    updateCanvasInfo();

    if (tts_feedback) {
        speak(tts_feedback);
        appendFeedback(tts_feedback);
    }
}

/* ===== WebSocket ===== */
function connectWebSocket() {
    if (ws && ws.readyState === WebSocket.OPEN) return;

    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        setStatus(true, "已连接");
        if (wsReconnectTimer) {
            clearTimeout(wsReconnectTimer);
            wsReconnectTimer = null;
        }
    };

    ws.onclose = () => {
        setStatus(false, "已断开，3秒后重连...");
        wsReconnectTimer = setTimeout(connectWebSocket, 3000);
    };

    ws.onerror = () => setStatus(false, "连接错误");

    ws.onmessage = (event) => {
        try {
            executeCommands(JSON.parse(event.data));
        } catch (e) {
            console.error("Failed to parse server response:", e);
        }
    };
}

function sendCommand(text) {
    if (!text || !text.trim()) return;

    if (!ws || ws.readyState !== WebSocket.OPEN) {
        speak("WebSocket 未连接");
        appendFeedback("WebSocket 未连接");
        return;
    }

    const model = modelInput.value.trim() || DEFAULT_MODEL;

    const payload = {
        text: text.trim(),
        model: model,
        context: {
            width: canvas.width,
            height: canvas.height,
            objects: canvasObjects.map((o) => ({
                id: o.id, shape: o.shape, color: o.color,
                x: o.x, y: o.y, width: o.width, height: o.height,
                radius: o.radius, radius_x: o.radius_x, radius_y: o.radius_y,
                text: o.text, font_size: o.font_size,
                x1: o.x1, y1: o.y1, x2: o.x2, y2: o.y2, x3: o.x3, y3: o.y3,
                fill: o.fill, stroke_width: o.stroke_width,
            })),
        },
    };

    ws.send(JSON.stringify(payload));
    appendTranscript(`[${model}] → ${text.trim()}`, "me");
}

/* ===== Web Speech ===== */
function initSpeech() {
    const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        setStatus(false, "浏览器不支持语音识别");
        micBtn.disabled = true;
        micBtn.textContent = "❌ 浏览器不支持";
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = "zh-CN";

    recognition.onresult = (event) => {
        let final = "";
        let interim = "";
        for (let i = event.resultIndex; i < event.results.length; i++) {
            const t = event.results[i][0].transcript;
            if (event.results[i].isFinal) final += t;
            else interim += t;
        }

        if (final) {
            pendingFinal += final;
            lastTranscript = pendingFinal;
            updateTranscript(pendingFinal);
        } else if (interim) {
            lastTranscript = pendingFinal + interim;
            updateTranscript(lastTranscript);
        }

        clearTimeout(idleTimer);
        idleTimer = setTimeout(
            submitPending,
            final ? IDLE_TIMEOUT : IDLE_TIMEOUT_FINAL
        );
    };

    recognition.onend = () => {
        if (isListening && speechErrorCount < MAX_SPEECH_RETRIES) {
            // Small delay to avoid rapid restart loops
            setTimeout(() => {
                try { recognition.start(); } catch (e) { /* ignore */ }
            }, 300);
        }
    };

    recognition.onerror = (event) => {
        if (event.error === "no-speech") return;

        speechErrorCount++;

        if (event.error === "network" || speechErrorCount >= MAX_SPEECH_RETRIES) {
            // Non-recoverable — stop auto-retry, user must click to restart
            isListening = false;
            micBtn.classList.remove("listening");
            micBtn.textContent = "🎤 重新开始语音输入";
            listeningIndicator.classList.add("hidden");
            clearTimeout(idleTimer);
            setStatus(false, `语音服务异常 (${event.error})，请点击按钮重试`);
            return;
        }

        setStatus(false, "语音错误: " + event.error);
    };
}

function submitPending() {
    clearTimeout(idleTimer);
    const text = pendingFinal.trim();
    if (text) {
        pendingFinal = "";
        lastTranscript = "";
        updateTranscript("");
        sendCommand(text);
    }
}

function toggleListening() {
    if (!recognition) initSpeech();
    if (!recognition) return;

    if (isListening) {
        isListening = false;
        try { recognition.stop(); } catch (e) { /* ignore */ }
        micBtn.classList.remove("listening");
        micBtn.textContent = "🎤 开始语音输入";
        listeningIndicator.classList.add("hidden");
        clearTimeout(idleTimer);
        if (pendingFinal.trim()) submitPending();
    } else {
        speechErrorCount = 0; // Reset retry counter on manual start
        pendingFinal = "";
        lastTranscript = "";
        updateTranscript("");
        isListening = true;
        micBtn.classList.add("listening");
        micBtn.textContent = "🎤 点击停止";
        listeningIndicator.classList.remove("hidden");
        try { recognition.start(); } catch (e) { /* ignore */ }
    }
}

/* ===== TTS ===== */
function speak(text) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();

    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 1.0;
    isSpeaking = true;

    const wasListening = isListening;
    if (wasListening) {
        try { recognition && recognition.stop(); } catch (e) { /* ignore */ }
    }

    utterance.onend = () => {
        isSpeaking = false;
        if (wasListening && isListening) {
            try { recognition && recognition.start(); } catch (e) { /* ignore */ }
        }
    };
    utterance.onerror = () => {
        isSpeaking = false;
        if (wasListening && isListening) {
            try { recognition && recognition.start(); } catch (e) { /* ignore */ }
        }
    };

    window.speechSynthesis.speak(utterance);
}

/* ===== UI Updates ===== */
function setStatus(online, text) {
    statusDot.className = online ? "dot-online" : "dot-offline";
    statusText.textContent = text;
}

function updateTranscript(text) {
    transcriptEl.textContent = text || "";
}

function appendTranscript(text, className) {
    const line = document.createElement("div");
    line.textContent = text;
    if (className) line.className = className;
    transcriptEl.appendChild(line);
    transcriptEl.scrollTop = transcriptEl.scrollHeight;
}

function appendFeedback(text) {
    const line = document.createElement("div");
    line.textContent = "🤖 " + text;
    line.className = "bot";
    feedbackEl.appendChild(line);
    feedbackEl.scrollTop = feedbackEl.scrollHeight;
}

function updateCanvasInfo() {
    canvasSizeEl.textContent = `尺寸: ${canvas.width} × ${canvas.height}`;
    objectCountEl.textContent = `对象数: ${canvasObjects.length}`;
}

/* ===== Init ===== */
document.addEventListener("DOMContentLoaded", () => {
    initCanvas(800, 600);
    connectWebSocket();

    micBtn.addEventListener("click", toggleListening);

    // Reset model to default
    resetModelBtn.addEventListener("click", () => {
        modelInput.value = DEFAULT_MODEL;
    });

    // Keyboard shortcut: Space to toggle listening
    document.addEventListener("keydown", (e) => {
        if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
        if (e.code === "Space") {
            e.preventDefault();
            toggleListening();
        }
    });
});
