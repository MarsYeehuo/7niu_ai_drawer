# AI 语音绘图工具

纯语音控制的绘图 Web 应用。用户通过语音指令完成绘图创作，无需鼠标或键盘。

## 系统架构

```
浏览器 (Canvas + Web Speech API)  ←→  Python FastAPI (WebSocket)  ←→  LLM API (Anthropic SDK 格式)
```

## 快速开始

### 1. 配置 API Key

在项目根目录创建 `.env` 文件（已提供模板）：

```
ANTHROPIC_API_KEY=sk-your-key-here
LLM_BASE_URL=https://api.anthropic.com
DEFAULT_LLM_MODEL=deepseek-v4-flash
```

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ANTHROPIC_API_KEY` | API 密钥 | — |
| `LLM_BASE_URL` | API 端点（Anthropic 格式兼容） | `https://api.anthropic.com` |
| `DEFAULT_LLM_MODEL` | 默认模型名 | `deepseek-v4-flash` |

### 2. 安装依赖

```bash
pip install anthropic fastapi uvicorn python-dotenv websockets
```

### 3. 启动服务

```bash
python -m backend.main
```

### 4. 打开应用

浏览器访问 `http://127.0.0.1:8765`

点击「开始语音输入」按钮，允许麦克风权限，开始说话。可在右侧面板切换模型。

## 支持的指令

| 类别 | 示例 |
|------|------|
| 基本形状 | "画一个红色的圆"、"画一个蓝色正方形" |
| 颜色控制 | "把圆改成蓝色" |
| 画布控制 | "清空画布"、"把画布设为1024x768"、"撤销" |
| 位置指定 | "在左上角画一个圆"、"在中间画一条线" |
| 尺寸指定 | "画一个大圆" |
| 复合物体 | "画一个房子"、"画一棵树" |
| 相对定位 | "在红色圆的右边画一个蓝色正方形" |
| 场景描述 | "画一个宁静的乡村傍晚" |
| 文本绘制 | "写上'Hello'在右上角" |

## Web Speech API 限制说明

本应用使用浏览器内置的 Web Speech API 进行语音识别，存在以下限制：

1. **浏览器兼容性**：仅支持 **Google Chrome** 和 **Microsoft Edge**（基于 Chromium）。
2. **HTTPS / localhost 要求**：需在安全上下文（HTTPS）或 localhost 下工作。
3. **语言支持**：设置为中文（zh-CN），方言和中英文混合场景识别率下降。
4. **麦克风权限**：首次使用需用户授权。
5. **环境噪音**：背景噪音会显著影响识别准确率。
6. **TTS 反馈回路**：应用已做防反馈处理，播报时暂停语音识别。

## 技术栈

- **前端**：Vanilla JS + HTML5 Canvas
- **语音输入**：Web Speech API (SpeechRecognition)
- **语音反馈**：Web Speech Synthesis (SpeechSynthesis)
- **后端**：Python FastAPI + WebSocket
- **指令解析**：LLM (Anthropic SDK 格式，支持多模型切换)
