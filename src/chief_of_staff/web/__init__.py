"""Secure local-only briefing and correction interface."""

from chief_of_staff.web.app import close_application, create_app
from chief_of_staff.web.presentation import presentation_from_plan

__all__ = ("close_application", "create_app", "presentation_from_plan")
