import json
import re
from anthropic import Anthropic
from .config import LLM_API_KEY, LLM_BASE_URL, DEFAULT_LLM_MODEL
from .command_models import CommandRequest, CommandResponse, DrawingCommand


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


def parse_command(request: CommandRequest) -> CommandResponse:
    """Send user text to LLM (via Anthropic SDK format) and parse into drawing commands."""
    model = request.model or DEFAULT_LLM_MODEL

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
            def _obj_pos(o):
                if o.x is not None and o.y is not None:
                    return f"({int(o.x)},{int(o.y)})"
                if o.x1 is not None and o.y1 is not None:
                    return f"({int(o.x1)},{int(o.y1)})"
                return "(unknown)"
            summaries = [f"  [{o.id}] {o.color} {o.shape} at {_obj_pos(o)}"
                         for o in ctx.objects]
            context_parts.append("Existing objects:\n" + "\n".join(summaries))
        else:
            context_parts.append("Canvas is empty.")

    context_str = "\n".join(context_parts)
    user_msg = f"{context_str}\n\nUser instruction: {request.text}"

    # Primary call
    try:
        client = Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
        response = client.messages.create(
            model=model,
            max_tokens=2048,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        content = _clean_json(_extract_text(response))
        data = json.loads(content)
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
            content = _clean_json(_extract_text(response))
            data = json.loads(content)
        except Exception as e2:
            return CommandResponse(
                commands=[DrawingCommand(action="error")],
                tts_feedback=f"API 调用失败: {err_msg or str(e2)[:80]}",
            )

    commands_data = data.get("commands", [])
    commands = [DrawingCommand(**cmd) for cmd in commands_data]
    tts_feedback = data.get("tts_feedback", "指令已执行")
    return CommandResponse(commands=commands, tts_feedback=tts_feedback)
