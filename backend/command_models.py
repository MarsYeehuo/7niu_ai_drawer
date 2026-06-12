from pydantic import BaseModel
from typing import Optional


class CanvasObject(BaseModel):
    """A single object currently on the canvas, used for context."""
    id: int
    shape: str
    color: str
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    radius: Optional[float] = None
    radius_x: Optional[float] = None
    radius_y: Optional[float] = None
    text: Optional[str] = None
    font_size: Optional[float] = None
    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    x3: Optional[float] = None
    y3: Optional[float] = None
    fill: bool = True
    stroke_width: float = 2


class CanvasContext(BaseModel):
    """Current canvas state sent from frontend."""
    width: float
    height: float
    objects: list[CanvasObject] = []


class CommandRequest(BaseModel):
    """Request from frontend containing voice text, canvas context, and model name."""
    text: str
    context: Optional[CanvasContext] = None
    model: Optional[str] = None  # Override the default model per-request


class DrawingCommand(BaseModel):
    """A single drawing operation parsed by the LLM."""
    action: str  # draw_shape, clear_canvas, resize_canvas, set_background, undo, add_text, error
    shape: Optional[str] = None
    color: Optional[str] = None
    x: Optional[float] = None
    y: Optional[float] = None
    width: Optional[float] = None
    height: Optional[float] = None
    radius: Optional[float] = None
    radius_x: Optional[float] = None
    radius_y: Optional[float] = None
    text: Optional[str] = None
    font_size: Optional[float] = None
    x1: Optional[float] = None
    y1: Optional[float] = None
    x2: Optional[float] = None
    y2: Optional[float] = None
    x3: Optional[float] = None
    y3: Optional[float] = None
    fill: bool = True
    stroke_width: float = 2


class CommandResponse(BaseModel):
    """Response sent back to frontend."""
    commands: list[DrawingCommand]
    tts_feedback: str = ""
