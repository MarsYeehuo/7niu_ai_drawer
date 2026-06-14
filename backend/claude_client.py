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
Use any standard color name (red, blue, green, yellow, purple, orange, pink, brown, gray, cyan, magenta, lime, navy, teal, olive, coral, gold, silver, violet, indigo, turquoise) or hex codes like #FF4500.

## Positioning Rules
1. Leave 20-40px margin from canvas edges (objects at the edge look cut off).
2. Distribute elements to create balanced composition — avoid clustering everything at center.
3. For relative positioning ("right of", "above"), estimate pixel offset relative to object sizes. Example: "right of a 100px-wide circle" ≈ 150px horizontal offset.
4. Main subject should occupy roughly 30-50% of the canvas area.

## Layering Technique
Build each visible object using 2-4 overlapping shapes:
- **Main shape**: base size, base color
- **Highlight**: 10-20% smaller than main, lighter version of base color, offset slightly (-3 to -5px) toward upper-left
- **Shadow/depth**: slightly shifted (3-6px) toward lower-right, darker color, drawn behind the main shape if needed
- **Accent**: small shape (20-30% of main) in bright/white color to create shine/sparkle

Examples:
- **Circle**: main (r:50, red) + highlight (r:40, #FF6666, offset -3,-3) + shine dot (r:10, white, offset -10,-10)
- **Tree**: trunk (brown rect, 12x60, bottom-center) + canopy main (green circle, r:50, above trunk) + canopy highlight (lighter green circle, r:40, offset -5,-5) + canopy shine (lime circle, r:15, offset -12,-12)
- **House**: wall (brown rect, 120x100, center) + roof (darker triangle above wall) + door (dark brown rect, 30x60, bottom-center of wall) + window (yellow rect, 25x25, upper area)
- **Mountains**: back mountain (darker triangle, large, upper area) + front mountain (slightly lighter triangle, overlapping) + snow cap (white triangle, top portion)

Use fill=true for all layers. stroke_width=0 for fill-only layers, stroke_width=1 for outlines.

## Rules
1. Output ONLY valid JSON — no markdown, no code fences, no extra text.
2. Calculate pixel positions using canvas dimensions from context. Apply the Positioning Rules above.
3. For relative positioning ("to the right of", "above", "next to"), estimate pixel offsets.
4. For unclear instructions: make a reasonable guess and proceed.
5. For completely unintelligible text: set action to "error".
6. CRITICAL: Your tts_feedback MUST accurately reflect the commands you produce. If you output no draw_shape or other modification commands, do NOT claim success in tts_feedback.
7. CRITICAL: You MUST ONLY use the actions listed in the Supported Actions table above. Never invent new action names.

## Output Format
{"commands":[{"action":"draw_shape","shape":"circle","color":"red","x":400,"y":300,"radius":50,"fill":true,"stroke_width":2}],"tts_feedback":"好的，已画好一个红色圆形"}

For errors:
{"commands":[{"action":"error"}],"tts_feedback":"抱歉，我没有理解您的指令"}

COMMAND COUNT: For simple instructions ("draw a circle"), use 2-4 commands (main shape + highlight + shadow). For complex descriptions ("a house", "a landscape"), use 5-15 layered commands.

IMPORTANT: ONLY output the JSON object, nothing else."""


PLAN_PROMPT = """You are a scene composition planner. Given a drawing instruction, output a JSON plan.

Output ONLY valid JSON — no markdown, no code fences, no extra text.

{
  "scene": "brief scene description",
  "palette": ["color1", "color2", "color3"],
  "composition": [
    {"z": 0, "name": "background", "description": "what to draw, with shapes, colors, relative position/size"},
    {"z": 1, "name": "midground", "description": "..."},
    {"z": 2, "name": "foreground", "description": "..."}
  ]
}

Rules:
1. Palette: choose 3-5 harmonious colors. Use at least one light/white and one dark for contrast.
2. Composition: arrange layers back-to-front. Every scene needs a clear focal point — don't center everything.
3. Layer count: 2-6 layers for simple scenes, up to 12 for complex scenes.
4. Descriptions MUST include: what shapes to use, what colors, relative size (large/small), and spatial arrangement (left/center/right, top/bottom).
5. For complex objects (tree, house, mountain), list their layered sub-parts in the description.
6. Do NOT include pixel coordinates.
7. CRITICAL: the plan must be executable with only 6 shapes: circle, rectangle, triangle, line, ellipse, point.

IMPORTANT: ONLY output the JSON object, nothing else."""


EXECUTE_PROMPT = """You are a drawing command generator. Your job is to mechanically translate a scene plan into drawing commands.

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
Use any standard color name (red, blue, green, yellow, purple, orange, pink, brown, gray, cyan, magenta, lime, navy, teal, olive, coral, gold, silver, violet, indigo, turquoise) or hex codes like #FF4500.

## Positioning Rules
1. Leave 20-40px margin from canvas edges (objects at the edge look cut off).
2. Distribute elements to create balanced composition — avoid clustering everything at center.
3. For relative positioning ("right of", "above"), estimate pixel offset relative to object sizes. Example: "right of a 100px-wide circle" ≈ 150px horizontal offset.
4. Main subject should occupy roughly 30-50% of the canvas area.

## Layering Technique
Build each visible object using 2-4 overlapping shapes:
- **Main shape**: base size, base color
- **Highlight**: 10-20% smaller than main, lighter version of base color, offset slightly (-3 to -5px) toward light source (upper-left)
- **Shadow/depth**: slightly shifted (3-6px) toward lower-right, darker color, drawn behind the main shape if needed
- **Accent**: small shape (20-30% of main) in bright/white color to create shine/sparkle

Examples:
- **Circle**: main (r:50, red) + highlight (r:40, #FF6666, offset -3,-3) + shine dot (r:10, white, offset -10,-10)
- **Tree**: trunk (brown rect, 12x60, bottom-center) + canopy main (green circle, r:50, above trunk) + canopy highlight (lighter green circle, r:40, offset -5,-5) + canopy shine (lime circle, r:15, offset -12,-12)
- **House**: wall (brown rect, 120x100, center) + roof (darker triangle above wall) + door (dark brown rect, 30x60, bottom-center of wall) + window (yellow rect, 25x25, upper area)
- **Mountains**: back mountain (darker triangle, large, upper area) + front mountain (slightly lighter triangle, overlapping) + snow cap (white triangle, top portion)

Use fill=true for all layers. stroke_width=0 for fill-only layers, stroke_width=1 for outlines.

## Rules
1. Output ONLY valid JSON — no markdown, no code fences, no extra text.
2. Build each object using 2-4 overlapping shapes with the Layering Technique above.
3. Calculate pixel positions using canvas dimensions from context. Apply the Positioning Rules above.
4. For unclear positions: make a reasonable guess and proceed.
5. CRITICAL: You MUST ONLY use the actions listed in the Supported Actions table above.
6. CRITICAL: Your tts_feedback MUST accurately reflect the commands you produce.

## Output Format
{"commands":[{"action":"draw_shape","shape":"circle","color":"red","x":400,"y":300,"radius":50,"fill":true,"stroke_width":2}],"tts_feedback":"好的，已画好一个红色圆形"}

For errors:
{"commands":[{"action":"error"}],"tts_feedback":"抱歉，我没有理解您的指令"}

## Execution Mode
You will receive a scene plan JSON together with the original instruction. Translate each element of the plan into precise drawing commands. Follow the plan exactly — do NOT add objects or change the composition. Use the layering technique to make each object visually rich.

## Efficiency
Keep your reasoning concise. Calculate coordinates directly and output commands. Aim for 5-15 commands per scene.

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


def _call_llm(system, messages, model, max_tokens=2048, thinking_disabled=False):
    """Call the LLM via Anthropic SDK format with optional thinking control."""
    client = Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": messages,
    }
    if thinking_disabled:
        kwargs["thinking"] = {"type": "disabled"}
    return client.messages.create(**kwargs)


def _build_context_str(request: CommandRequest) -> str:
    """Build context description string for LLM messages."""
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
    return "\n".join(context_parts)


def _plan_scene(request: CommandRequest, model: str) -> tuple:
    """Step 1: Plan the scene composition (thinking disabled, fast)."""
    context_str = _build_context_str(request)
    user_msg = f"{context_str}\n\nUser instruction: {request.text}"

    response = _call_llm(
        system=PLAN_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        model=model,
        max_tokens=1024,
        thinking_disabled=True,
    )

    thinking = _extract_thinking(response) or None
    raw_text = _extract_text(response)
    content = _clean_json(raw_text)
    plan_data = json.loads(content)

    return plan_data, thinking, raw_text


def _execute_plan(plan_data: dict, request: CommandRequest, model: str) -> tuple:
    """Step 2: Translate scene plan into drawing commands (no thinking for reliable output)."""
    context_str = _build_context_str(request)
    plan_json = json.dumps(plan_data, ensure_ascii=False, indent=2)
    user_msg = (
        f"{context_str}\n\n"
        f"Scene Plan:\n{plan_json}\n\n"
        f"Original instruction: {request.text}\n\n"
        f"Translate this plan into drawing commands."
    )

    response = _call_llm(
        system=EXECUTE_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
        model=model,
        max_tokens=4096,
        thinking_disabled=True,
    )

    thinking = _extract_thinking(response) or None
    raw_text = _extract_text(response)
    content = _clean_json(raw_text)
    data = json.loads(content)

    commands_data = data.get("commands", [])
    tts_feedback = data.get("tts_feedback", "指令已执行")
    return commands_data, tts_feedback, thinking, raw_text


def _build_ctx_dict(request: CommandRequest) -> dict:
    """Build context dictionary for logging."""
    ctx_dict = {"width": 800, "height": 600, "objects": []}
    if request.context:
        ctx_dict = {
            "width": request.context.width,
            "height": request.context.height,
            "objects": [o.model_dump() for o in request.context.objects],
        }
    return ctx_dict


def parse_command(request: CommandRequest) -> CommandResponse:
    """Send user text to LLM and parse into drawing commands.

    Uses a two-step approach: plan (no thinking) -> execute (no thinking).
    Falls back to the original single-step method if the two-step process fails.
    """
    model = request.model or DEFAULT_LLM_MODEL
    ctx_dict = _build_ctx_dict(request)

    if not LLM_API_KEY or LLM_API_KEY == "your-api-key-here":
        return CommandResponse(
            commands=[DrawingCommand(action="error")],
            tts_feedback="请在 .env 文件中配置 ANTHROPIC_API_KEY",
        )

    # === Two-step approach: plan (no thinking) -> execute (with thinking) ===
    plan_thinking = None
    plan_raw = None
    exec_thinking = None
    exec_raw = None
    commands_data = []
    tts_feedback = ""
    used_two_step = False

    try:
        plan_data, plan_thinking, plan_raw = _plan_scene(request, model)
        commands_data, tts_feedback, exec_thinking, exec_raw = _execute_plan(plan_data, request, model)
        used_two_step = True
    except Exception:
        pass

    # === Fallback: original single-step approach ===
    if not used_two_step:
        try:
            client = Anthropic(api_key=LLM_API_KEY, base_url=LLM_BASE_URL)
            context_str = _build_context_str(request)
            response = client.messages.create(
                model=model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"{context_str}\n\nUser instruction: {request.text}"}],
            )
            exec_thinking = _extract_thinking(response) or None
            exec_raw = _extract_text(response)
            content = _clean_json(exec_raw)
            data = json.loads(content)
            commands_data = data.get("commands", [])
            tts_feedback = data.get("tts_feedback", "指令已执行")
        except Exception as e1:
            err_msg = str(e1)[:80]
            # Second fallback: simpler prompt
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
                exec_raw = _extract_text(response)
                content = _clean_json(exec_raw)
                data = json.loads(content)
                commands_data = data.get("commands", [])
                tts_feedback = data.get("tts_feedback", "抱歉，解析失败，请重新描述")
            except Exception as e2:
                log_instruction(
                    user_text=request.text,
                    model=model,
                    context_before=ctx_dict,
                    thinking=exec_thinking,
                    raw_response=exec_raw,
                    parsed_commands=[],
                    has_effect=False,
                    tts_feedback=f"API 调用失败: {err_msg or str(e2)[:80]}",
                )
                return CommandResponse(
                    commands=[DrawingCommand(action="error")],
                    tts_feedback=f"API 调用失败: {err_msg or str(e2)[:80]}",
                )

    # === Common post-processing ===
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

    # Combine thinking traces for logging
    combined_thinking = None
    if used_two_step:
        if plan_thinking and exec_thinking:
            combined_thinking = f"[Planning phase]\n{plan_thinking}\n\n[Execution phase]\n{exec_thinking}"
        elif plan_thinking:
            combined_thinking = plan_thinking
        elif exec_thinking:
            combined_thinking = exec_thinking
    else:
        combined_thinking = exec_thinking

    # Combine raw responses for logging
    raw_response = exec_raw
    if used_two_step and plan_raw:
        raw_response = json.dumps(
            {"plan_response": plan_raw, "execute_response": exec_raw},
            ensure_ascii=False,
        )

    log_instruction(
        user_text=request.text,
        model=model,
        context_before=ctx_dict,
        thinking=combined_thinking,
        raw_response=raw_response,
        parsed_commands=[cmd.model_dump() for cmd in commands],
        has_effect=has_effect,
        tts_feedback=tts_feedback,
    )

    return CommandResponse(commands=commands, tts_feedback=tts_feedback)
