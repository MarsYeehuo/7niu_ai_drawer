import os
from datetime import datetime

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "log")


def _ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def log_instruction(
    user_text: str,
    model: str,
    context_before: dict,
    thinking: str | None,
    raw_response: str | None,
    parsed_commands: list[dict],
    has_effect: bool,
    tts_feedback: str,
):
    _ensure_dir()
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    filepath = os.path.join(LOG_DIR, f"{date_str}.log")

    lines = []
    lines.append("=" * 56)
    lines.append(f"时间: {ts}")
    lines.append(f"用户指令: {user_text}")
    lines.append(f"模型: {model}")
    lines.append("")

    ctx = context_before
    lines.append("【画布上下文】")
    lines.append(f"  尺寸: {ctx.get('width', '?')}x{ctx.get('height', '?')}")
    objects = ctx.get("objects", [])
    if objects:
        lines.append(f"  已有对象 ({len(objects)} 个):")
        for o in objects:
            pos = f"({o.get('x', '?')},{o.get('y', '?')})" if o.get('x') is not None else "(unknown)"
            lines.append(f"    [{o.get('id','?')}] {o.get('color','')} {o.get('shape','')} at {pos}")
    else:
        lines.append("  已有对象: 无")
    lines.append("")

    if thinking:
        lines.append("【模型思考过程】")
        lines.append(thinking.strip())
        lines.append("")

    if raw_response:
        lines.append("【原始响应】")
        lines.append(raw_response.strip())
        lines.append("")

    lines.append("【解析结果】")
    for cmd in parsed_commands:
        parts = [f"  {cmd.get('action', '?')}"]
        shape = cmd.get("shape")
        if shape:
            parts.append(shape)
        color = cmd.get("color", "")
        if color:
            parts.append(f"({color})")
        coord_fields = ["x", "y", "x1", "y1", "x2", "y2", "x3", "y3", "width", "height", "radius", "radius_x", "radius_y"]
        coord_strs = []
        for f in coord_fields:
            v = cmd.get(f)
            if v is not None:
                coord_strs.append(f"{f}={v}")
        if coord_strs:
            parts.append("at " + ", ".join(coord_strs))
        lines.append(" ".join(parts))

    if not parsed_commands:
        lines.append("  (空 - 未产生任何指令)")

    lines.append(f"效果: {'✅ 有变更' if has_effect else '❌ 无变更'}")
    lines.append(f"TTS反馈: {tts_feedback}")
    lines.append("")

    with open(filepath, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
