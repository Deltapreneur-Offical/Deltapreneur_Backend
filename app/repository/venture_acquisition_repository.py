"""Backward-compatible import path for venture pitch repository."""

from app.repository.venture_pitch_repository import (
    VentureAcquisitionRepository,
    VenturePitchRepository,
)

__all__ = ["VentureAcquisitionRepository", "VenturePitchRepository"]
