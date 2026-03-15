"""Claude Vision scene analysis — photos → structured SceneAnalysis."""

import json
import logging
from pathlib import Path

from backend.app.core.claude import ClaudeClient
from backend.app.core.config import get_settings
from backend.app.core.prompts import load_prompt
from backend.app.models.space import (
    Dimensions,
    SceneAnalysis,
    SceneReconstruction,
    SpaceModel,
)

__all__ = ["analyze_scene", "build_space_model", "validate_analysis"]

logger = logging.getLogger(__name__)

_MAX_RETRIES = 2


async def analyze_scene(
    client: ClaudeClient,
    photos: list[Path],
    reconstruction: SceneReconstruction,
) -> SceneAnalysis:
    """Analyze room photos + reconstruction data via Claude Vision.

    Args:
        client: Claude API client.
        photos: List of room photo file paths.
        reconstruction: Scene reconstruction result.

    Returns:
        Structured scene analysis with zones, equipment, doors, windows.

    Raises:
        ValueError: If Claude returns unparseable response after retries.
    """
    system_prompt = load_prompt("vision_analysis")
    dims = reconstruction.dimensions
    text = _format_analysis_request(dims)

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES + 1):
        try:
            response = await client.send_vision_message(
                system=system_prompt,
                images=photos,
                text=text,
                model=get_settings().vision_model,
            )
            analysis = _parse_analysis_response(response)
            return validate_analysis(analysis, dims)
        except (ValueError, json.JSONDecodeError) as exc:
            last_error = exc
            logger.warning(
                "Analysis attempt %d/%d failed: %s",
                attempt + 1,
                _MAX_RETRIES + 1,
                exc,
            )

    raise ValueError(
        f"Failed to parse scene analysis after {_MAX_RETRIES + 1} attempts: {last_error}"
    )


def build_space_model(
    reconstruction: SceneReconstruction,
    analysis: SceneAnalysis,
) -> SpaceModel:
    """Merge reconstruction and analysis into a complete SpaceModel.

    Args:
        reconstruction: Scene reconstruction data.
        analysis: Claude Vision analysis results.

    Returns:
        Complete room model for simulation.
    """
    return SpaceModel(
        dimensions=reconstruction.dimensions,
        zones=analysis.zones,
        existing_equipment=analysis.existing_equipment,
        doors=analysis.doors,
        windows=analysis.windows,
        reconstruction=reconstruction,
    )


def validate_analysis(
    analysis: SceneAnalysis,
    dims: Dimensions,
) -> SceneAnalysis:
    """Validate and clamp analysis values to reasonable ranges.

    Args:
        analysis: Parsed scene analysis from Claude.
        dims: Room dimensions for bounds checking.

    Returns:
        Validated SceneAnalysis with clamped values.
    """
    validated_equipment = []
    for eq in analysis.existing_equipment:
        pos = (
            _clamp(eq.position[0], 0.0, dims.width_m),
            _clamp(eq.position[1], 0.0, dims.length_m),
            0.0 if eq.mounting == "floor" else eq.position[2],
        )
        eq_dims = tuple(_clamp(d, 0.05, max(dims.width_m, dims.length_m)) for d in eq.dimensions)
        if pos != eq.position or eq_dims != eq.dimensions:
            logger.warning(
                "Clamped equipment '%s': pos %s→%s, dims %s→%s",
                eq.name,
                eq.position,
                pos,
                eq.dimensions,
                eq_dims,
            )
        validated_equipment.append(
            eq.model_copy(
                update={
                    "position": pos,
                    "dimensions": eq_dims,
                }
            )
        )

    return analysis.model_copy(
        update={
            "existing_equipment": validated_equipment,
        }
    )


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value to a range.

    Args:
        value: Value to clamp.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        Clamped value.
    """
    return max(min_val, min(value, max_val))


def _format_analysis_request(dims: Dimensions) -> str:
    """Format the text portion of the vision analysis request.

    Args:
        dims: Room dimensions from reconstruction.

    Returns:
        Formatted request text.
    """
    return (
        f"Room dimensions from 3D reconstruction:\n"
        f"  Width (X-axis): {dims.width_m:.2f}m\n"
        f"  Length (Y-axis): {dims.length_m:.2f}m\n"
        f"  Ceiling height: {dims.ceiling_m:.2f}m\n"
        f"  Area: {dims.area_m2:.2f}m²\n\n"
        f"Wall reference:\n"
        f"  North wall: Y = {dims.length_m:.2f}\n"
        f"  South wall: Y = 0\n"
        f"  East wall: X = {dims.width_m:.2f}\n"
        f"  West wall: X = 0\n\n"
        f"Analyze these photos and return a JSON with:\n"
        f"1. Functional zones (name, polygon, area)\n"
        f"2. Existing equipment with estimated dimensions [w, d, h], "
        f"orientation_deg, rgba color, mounting type, shape\n"
        f"3. Doors with wall assignment and height\n"
        f"4. Windows with wall assignment, height, and sill_height_m\n\n"
        f"Return ONLY valid JSON matching the schema in the system prompt."
    )


def _parse_analysis_response(response: str) -> SceneAnalysis:
    """Parse Claude's response into a SceneAnalysis model.

    Args:
        response: Raw response text from Claude.

    Returns:
        Parsed SceneAnalysis.

    Raises:
        ValueError: If response cannot be parsed.
    """
    json_str = _extract_json(response)
    return SceneAnalysis.model_validate_json(json_str)


def _extract_json(text: str) -> str:
    """Extract JSON from text, handling markdown code blocks.

    Args:
        text: Raw text that may contain JSON in code blocks.

    Returns:
        Extracted JSON string.
    """
    if "```json" in text:
        start = text.index("```json") + len("```json")
        end = text.index("```", start)
        return text[start:end].strip()
    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()
    return text.strip()
