"""Pydantic v2 request/response contracts."""

from app.schemas.admin import (
    AnalyticsOut,
    ResolveRequest,
    TicketOut,
    TicketStatusRequest,
)
from app.schemas.auth import LoginRequest, TokenOut, UserOut
from app.schemas.barrier import (
    BarrierConfirmRequest,
    BarrierConfirmResponse,
    BarrierListOut,
    BarrierOut,
    BarrierReportResponse,
    CVResultOut,
)
from app.schemas.campus import CampusNetworkOut, GraphStatsOut, PresetOut
from app.schemas.routing import RoutePlanRequest, RoutePlanResponse

__all__ = [
    "AnalyticsOut",
    "BarrierConfirmRequest",
    "BarrierConfirmResponse",
    "BarrierListOut",
    "BarrierOut",
    "BarrierReportResponse",
    "CVResultOut",
    "CampusNetworkOut",
    "GraphStatsOut",
    "LoginRequest",
    "PresetOut",
    "ResolveRequest",
    "RoutePlanRequest",
    "RoutePlanResponse",
    "TicketOut",
    "TicketStatusRequest",
    "TokenOut",
    "UserOut",
]
