import json
import re
from anthropic import Anthropic
from .config import LLM_API_KEY, LLM_BASE_URL, DEFAULT_LLM_MODEL
from .command_models import CommandRequest, CommandResponse, DrawingCommand
from .logger import log_instruction

VALID_ACTIONS = {
    "draw_shape", "clear_canvas", "resize_canvas",
    "set_background", "undo", "add_text", "error",
}


SYSTEM_PROMPT = """You are an AI drawing assistant. Parse natural language drawing instructions into structured JSON commands.

## Canvas
- Coordinates: (0,0) = top-left, x→right, y→down. Values in pixels.
- Canvas width and height are provided in the context.

## Supported Actions
| action | description | required fields |
|--------|-------------|-----------------|
| draw_shape | Draw a shape | shape, color, position + shape-specific fields |
| clear_canvas | Remove everything | none |
| resize_canvas | Change canvas size | width, height |
| set_background | Fill background | color |
| undo | Remove last object | none |
| add_text | Draw text | text, x, y, color, font_size |

## Supported Shapes (for draw_shape)
| shape | required fields |
|-------|----------------|
| circle | x, y, radius |
| rectangle | x, y, width, height |
| triangle | x1, y1, x2, y2, x3, y3 |
| line | x1, y1, x2, y2 |
| ellipse | x, y, radius_x, radius_y |
| point | x, y, radius (small dot) |

## Standard Colors
red, blue, green, yellow, black, white, purple, orange, pink, brown, gray, cyan, magenta, lime, navy, teal, maroon, olive, coral, gold, silver, beige, violet, indigo, turquoise. You may also use hex codes like #FF4500.

## Rules
1. Output ONLY valid JSON — no markdown, no code fences, no extra text.
2. Decompose complex objects (house = rectangle + triangle, tree = rectangle + circle) into multiple draw_shape commands.
3. Calculate pixel positions using canvas dimensions from context.
4. For relative positioning ("to the right of", "above", "next to"), estimate pixel offsets.
5. For unclear instructions: make a reasonable guess and proceed.
6. For completely unintelligible text: set action to "error".
7. CRITICAL: Your tts_feedback MUST accurately reflect the commands you produce. If you output no draw_shape or other modification commands, do NOT claim success in tts_feedback. Say what actually happened (e.g. "I don't see what to draw" or "please give me a clearer instruction").
8. CRITICAL: You MUST ONLY use the actions listed in the Supported Actions table above. Never invent new action names like "modify", "adjust_color", "draw_mountains", "change_color", or any other custom action. If you want to change an existing object's appearance, you must use "draw_shape" to draw a new shape on top of it with the same position and dimensions but new color.

## Output Format
{"commands":[{"action":"draw_shape","shape":"circle","color":"red","x":400,"y":300,"radius":50,"fill":true,"stroke_width":2}],"tts_feedback":"好的，已画好一个红色圆形"}

For errors:
{"commands":[{"action":"error"}],"tts_feedback":"抱歉，我没有理解您的指令"}

IMPORTANT: ONLY output the JSON object, nothing else."""


def _clean_json(text: str) -> str:
    """Extract JSON from LLM response, stripping markdown fences if present."""
    json_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if json_match:
        return json_match.group(1).strip()
    return text.strip()


def _extract_text(response) -> str:
    """Extract text content from an Anthropic SDK response, handling ThinkingBlock."""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            return block.text
    return ""


def _extract_thinking(response) -> str:
    """Extract thinking/reasoning content from ThinkingBlocks."""
    parts = []
    for block in response.content:
        if hasattr(block, "thinking") and block.thinking:
            parts.append(block.thinking)
    return "\n".join(parts)


def parse_command(request: CommandRequest) -> CommandResponse:
    """Send user text to LLM (via Anthropic SDK format) and parse into drawing commands."""
    model = request.model or DEFAULT_LLM_MODEL

    # Build context dict for logging
    ctx_dict = {"width": 800, "height": 600, "objects": []}
    if request.context:
        ctx_dict = {
            "width": request.context.width,
            "height": request.context.height,
            "objects": [o.model_dump() for o in request.context.objects],
        }

    if not LLM_API_KEY or LLM_API_KEY == "your-api-key-here":
        return CommandResponse(
            commands=[DrawingCommand(action="error")],
            tts_feedback="请在 .env 文件中配置 ANTHROPIC_API_KEY",
        )

    # Build context string
    context_parts = []
    if request.context:
        ctx = request.context
        context_parts.append(f"Canvas size: {int(ctx.width)}x{int(ctx.height)}")
        if ctx.objects:
            def _obj_detail(o):
                parts = []
                if o.x is not None and o.y is not None:
                    parts.append(f"pos=({int(o.x)},{int(o.y)})")
                if o.x1 is not None:
                    coords = f"x1={int(o.x1)} y1={int(o.y1)} x2={int(o.x2)} y2={int(o.y2)}"
                    if o.x3 is not None:
                        coords += f" x3={int(o.x3)} y3={int(o.y3)}"
                    parts.append(coords)
                    return " ".join(parts)
                if o.radius is not None:
                    parts.append(f"radius={o.radius}")
                if o.radius_x is not None:
                    parts.append(f"radius_x={o.radius_x} radius_y={o.radius_y}")
                if o.width is not None:
                    parts.append(f"w={int(o.width)} h={int(o.height)}")
                return " ".join(parts) if parts else "(unknown)"
            summaries = [f"  [{o.id}] {o.color} {o.shape} {_obj_detail(o)}"
                         for o in ctx.objects]
            context_parts.append("Existing objects:\n" + "\n".join(summaries))
        else:
            context_parts.append("Canvas is empty.")

    context_str = "\n".join(context_parts)
    user_msg = f"{context_str}\n\nUser instruction: {request.text}"

    thinking = None
    raw_text = None
    commands_data = []
    tts_feedback = ""

    # Primary call
    try:
        client = Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        thinking = _extract_thinking(response) or None
        raw_text = _extract_text(response)
        content = _clean_json(raw_text)
        data = json.loads(content)
        commands_data = data.get("commands", [])
        tts_feedback = data.get("tts_feedback", "指令已执行")
    except Exception as e1:
        err_msg = str(e1)[:80]
        # Fallback: simpler prompt
        try:
            client = Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system="Parse the following drawing instruction and output JSON. "
                       'If all else fails, output: {"commands":[{"action":"error"}],'
                       '"tts_feedback":"抱歉，解析失败，请重新描述"}',
                messages=[{"role": "user", "content": request.text}],
            )
            raw_text = _extract_text(response)
            content = _clean_json(raw_text)
            data = json.loads(content)
            commands_data = data.get("commands", [])
            tts_feedback = data.get("tts_feedback", "抱歉，解析失败，请重新描述")
        except Exception as e2:
            log_instruction(
                user_text=request.text,
                model=model,
                context_before=ctx_dict,
                thinking=thinking,
                raw_response=raw_text,
                parsed_commands=[],
                has_effect=False,
                tts_feedback=f"API 调用失败: {err_msg or str(e2)[:80]}",
            )
            return CommandResponse(
                commands=[DrawingCommand(action="error")],
                tts_feedback=f"API 调用失败: {err_msg or str(e2)[:80]}",
            )

    commands = [DrawingCommand(**cmd) for cmd in commands_data]
    if not tts_feedback:
        tts_feedback = "指令已执行"

    # Reject hallucinated actions (model sometimes invents custom actions)
    cleaned = []
    seen_bad_action = False
    for cmd in commands:
        if cmd.action not in VALID_ACTIONS:
            seen_bad_action = True
        else:
            cleaned.append(cmd)
    commands = cleaned
    if seen_bad_action:
        tts_feedback = "指令中包含不支持的绘图操作，请重新描述"

    # Safety net: if no actual drawing/change commands, override misleading feedback
    EFFECTIVE_ACTIONS = {"draw_shape", "clear_canvas", "resize_canvas", "set_background", "add_text"}
    has_effect = any(cmd.action in EFFECTIVE_ACTIONS for cmd in commands)
    if not has_effect and commands:
        tts_feedback = "指令已收到，但在画布上没有产生变化"
    elif not commands:
        tts_feedback = "未识别到绘图指令，请重新描述"

    # Log the instruction and result
    log_instruction(
        user_text=request.text,
        model=model,
        context_before=ctx_dict,
        thinking=thinking,
        raw_response=raw_text,
        parsed_commands=[cmd.model_dump() for cmd in commands],
        has_effect=has_effect,
        tts_feedback=tts_feedback,
    )

    return CommandResponse(commands=commands, tts_feedback=tts_feedback)
