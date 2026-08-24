"""
app/agents/registry.py
──────────────────────
Agent registry — single source of truth for all registered agents.

Usage:
    from app.agents.registry import registry
    agent = registry.get("lead_qualification")
    result = await agent(context, input_data)

Adding a new agent:
    1. Create app/agents/<name>.py implementing BaseAgent
    2. Import it here and call registry.register(MyAgent())
"""
from __future__ import annotations

from typing import Iterator

import structlog

from klara.rarv.runtime import BaseAgent

logger = structlog.get_logger(__name__)


class AgentRegistry:
    def __init__(self):
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        if agent.name in self._agents:
            raise ValueError(f"Agent '{agent.name}' is already registered.")
        self._agents[agent.name] = agent
        logger.debug("agent.registered", name=agent.name, level=agent.permission_level.value)

    def get(self, name: str) -> BaseAgent:
        agent = self._agents.get(name)
        if not agent:
            raise KeyError(f"No agent named '{name}'. Registered: {list(self._agents)}")
        return agent

    def all(self) -> list[BaseAgent]:
        return list(self._agents.values())

    def list_meta(self) -> list[dict]:
        return [a.meta() for a in self._agents.values()]

    def __iter__(self) -> Iterator[BaseAgent]:
        return iter(self._agents.values())

    def __len__(self) -> int:
        return len(self._agents)


# ── Singleton registry ────────────────────────────────────────────────────────
registry = AgentRegistry()


def _bootstrap() -> None:
    """
    Import and register all agents.
    Called once at module load — lazy imports keep startup fast.
    """
    # ── Core infrastructure ───────────────────────────────────────────────────
    from app.agents.context_manager import ContextManagerAgent
    from app.agents.policy_guard import PolicyGuardAgent
    from app.agents.approval_manager import ApprovalManagerAgent
    from app.agents.approval_notifier import ApprovalNotifierAgent
    from app.agents.audit_logger import AuditLoggerAgent

    # ── Intake ────────────────────────────────────────────────────────────────
    from app.agents.chat_intake import ChatIntakeAgent
    from app.agents.form_intake import FormIntakeAgent
    from app.agents.callback_intake import CallbackIntakeAgent
    # ── Consumer support pipeline ─────────────────────────────────────────────
    from app.agents.consumer_intake import ConsumerIntakeAgent
    from app.agents.atera_ticket_creator import AteraTicketCreatorAgent

    # ── Qualification pipeline ────────────────────────────────────────────────
    from app.agents.lead_qualification import LeadQualificationAgent
    from app.agents.lead_scoring import LeadScoringAgent
    from app.agents.routing import RoutingAgent

    # ── Notifications ─────────────────────────────────────────────────────────
    from app.agents.lead_alert import LeadAlertAgent

    # ── Engagement / nurture (P2) ─────────────────────────────────────────────
    from app.agents.calendar_integration import CalendarIntegrationAgent
    from app.agents.followup_nurture import FollowupNurtureAgent

    # ── Sales conversation ────────────────────────────────────────────────────
    from app.agents.discovery_call_prep import DiscoveryCallPrepAgent
    from app.agents.objection_handler import ObjectionHandlerAgent
    from app.agents.faq_responder import FaqResponderAgent

    # ── Outbound / outreach ───────────────────────────────────────────────────
    from app.agents.outreach_email import OutreachEmailAgent
    from app.agents.lead_reactivation import LeadReactivationAgent
    from app.agents.cold_nurture import ColdNurtureAgent

    # ── Prospecting pipeline (Phase 4.5) ──────────────────────────────────────
    from app.agents.prospecting_outreach import ProspectingOutreachAgent
    from app.agents.lead_enrichment import LeadEnrichmentAgent

    # ── Pre-qualification enrichment ──────────────────────────────────────────
    from app.agents.post_call_processor import PostCallProcessorAgent

    # ── Proposals / contracts ─────────────────────────────────────────────────
    from app.agents.proposal_drafting import ProposalDraftingAgent
    from app.agents.proposal_followup import ProposalFollowupAgent
    from app.agents.contract_generator import ContractGeneratorAgent

    # ── Client lifecycle ──────────────────────────────────────────────────────
    from app.agents.client_onboarding import ClientOnboardingAgent
    from app.agents.project_kickoff import ProjectKickoffAgent
    from app.agents.portal_notifier import PortalNotifierAgent
    from app.agents.invoice_reminder import InvoiceReminderAgent
    from app.agents.invoice_generator import InvoiceGeneratorAgent
    from app.agents.client_satisfaction import ClientSatisfactionAgent
    from app.agents.testimonial_requester import TestimonialRequesterAgent
    from app.agents.referral_campaign import ReferralCampaignAgent

    # ── Content / publishing (P3) ─────────────────────────────────────────────
    from app.agents.seo_content_writer import SeoContentWriterAgent
    from app.agents.social_media_manager import SocialMediaManagerAgent
    from app.agents.website_deploy import WebsiteDeployAgent
    from app.agents.translation_sync import TranslationSyncAgent
    from app.agents.translation_agent import TranslationAgent

    # ── Product delivery agents (P2/P3) ───────────────────────────────────────
    from app.agents.network_monitor_onboarding import NetworkMonitorOnboardingAgent
    from app.agents.patch_compliance_reporter import PatchComplianceReporterAgent
    from app.agents.security_scoping import SecurityScopingAgent
    from app.agents.task_automator import TaskAutomatorAgent
    from app.agents.kb_lookup import KbLookupAgent

    # ── Reply intent + conversion (Phase 4) ───────────────────────────────────
    from app.agents.reply_intent import ReplyIntentAgent
    from app.agents.reply_draft import ReplyDraftAgent
    # ── Inbound email triage (Phase 19) ───────────────────────────────────────
    from app.agents.inbound_email import InboundEmailAgent
    # ── LinkedIn outreach (Phase 20) ──────────────────────────────────────────
    from app.agents.linkedin_outreach import LinkedinOutreachAgent

    # ── Integrations / recovery (Phase 21-25) ────────────────────────────────
    from app.agents.crm_integration import CrmIntegrationAgent
    from app.agents.email_integration import EmailIntegrationAgent
    from app.agents.rollback_recovery import RollbackRecoveryAgent

    # ── Content editors / validators (Phase 26-32) ────────────────────────────
    from app.agents.test_harness import TestHarnessAgent
    from app.agents.homepage_about_editor import HomepageAboutEditorAgent
    from app.agents.services_pricing_editor import ServicesPricingEditorAgent
    from app.agents.german_copy_editor import GermanCopyEditorAgent
    from app.agents.blog_case_study_draft import BlogCaseStudyDraftAgent
    from app.agents.security_validator import SecurityValidatorAgent
    from app.agents.auth_permissions_validator import AuthPermissionsValidatorAgent

    # ── Bilingual outreach system (Phase 3) ────────────────────────────────────
    from app.agents.language_detection_agent import LanguageDetectionAgent
    from app.agents.consent_validation_agent import ConsentValidationAgent
    from app.agents.bilingual_outreach_agent import BilingualOutreachAgent
    from app.agents.bilingual_proposal_agent import BilingualProposalAgent
    from app.agents.bilingual_reporting_agent import BilingualReportingAgent

    # ── Division coordinators ─────────────────────────────────────────────────
    from app.agents.sales_division import SalesDivisionAgent
    from app.agents.engineering_division import EngineeringDivisionAgent
    from app.agents.design_division import DesignDivisionAgent

    # ── Freelance platform pipeline (Phase 5) ─────────────────────────────────
    from app.agents.freelance_scout import FreelanceScoutAgent
    from app.agents.bid_strategist import BidStrategyAgent
    from app.agents.platform_bid_submitter import PlatformBidSubmitterAgent
    from app.agents.platform_client_converter import PlatformClientConverterAgent
    from app.agents.voice_call_agent import VoiceCallAgent
    from app.agents.vapi_webhook_processor import VapiWebhookProcessorAgent
    from app.agents.calendly_webhook import CalendlyWebhookAgent

    # ── Batch refresh ─────────────────────────────────────────────────────────
    from app.agents.lead_scoring_refresh import LeadScoringRefreshAgent

    # ── Reporting ─────────────────────────────────────────────────────────────
    from app.agents.daily_report import DailyReportAgent
    from app.agents.pipeline_reporter import PipelineReporterAgent

    # ── Client intelligence (Phase 6) ─────────────────────────────────────────
    from app.agents.revenue_analytics import RevenueAnalyticsAgent
    from app.agents.client_health import ClientHealthAgent
    from app.agents.upsell_opportunity import UpsellOpportunityAgent

    # ── Reporting enhancements (Phase 7) ──────────────────────────────────────
    from app.agents.weekly_report import WeeklyReportAgent
    from app.agents.kpi_dashboard import KPIDashboardAgent

    # ── Market intelligence (Phase 7) ─────────────────────────────────────────
    from app.agents.competitor_monitor import CompetitorMonitorAgent
    from app.agents.seo_opportunity import SEOOpportunityAgent

    # ── Content & lifecycle (Phase 7) ─────────────────────────────────────────
    from app.agents.content_calendar import ContentCalendarAgent
    from app.agents.contract_renewal import ContractRenewalAgent

    # ── RARV journal team (single write path into the vault) ──────────────────
    from klara.rarv.journal import (
        RARVReasonerAgent,
        RARVReflectorAgent,
        RARVVerifierAgent,
        RARVWriterAgent,
    )

    # ── Klara AI orchestrator (registered last — depends on all others) ───────────
    from app.agents.loki_orchestrator import LokiOrchestratorAgent

    for agent_cls in [
        # Core
        ContextManagerAgent,
        PolicyGuardAgent,
        ApprovalManagerAgent,
        ApprovalNotifierAgent,
        AuditLoggerAgent,
        # Intake
        ChatIntakeAgent,
        FormIntakeAgent,
        CallbackIntakeAgent,
        # Consumer support pipeline
        ConsumerIntakeAgent,
        AteraTicketCreatorAgent,
        # Qualification
        LeadQualificationAgent,
        LeadScoringAgent,
        RoutingAgent,
        # Notifications
        LeadAlertAgent,
        # Engagement / nurture
        CalendarIntegrationAgent,
        FollowupNurtureAgent,
        # Sales conversation
        DiscoveryCallPrepAgent,
        ObjectionHandlerAgent,
        FaqResponderAgent,
        # Outbound / outreach
        OutreachEmailAgent,
        LeadReactivationAgent,
        ColdNurtureAgent,
        # Prospecting
        ProspectingOutreachAgent,
        LeadEnrichmentAgent,
        # Post-call
        PostCallProcessorAgent,
        # Proposals / contracts
        ProposalDraftingAgent,
        ProposalFollowupAgent,
        ContractGeneratorAgent,
        # Client lifecycle
        ClientOnboardingAgent,
        ProjectKickoffAgent,
        PortalNotifierAgent,
        InvoiceReminderAgent,
        InvoiceGeneratorAgent,
        ClientSatisfactionAgent,
        TestimonialRequesterAgent,
        ReferralCampaignAgent,
        # Content / publishing
        SeoContentWriterAgent,
        SocialMediaManagerAgent,
        WebsiteDeployAgent,
        TranslationSyncAgent,
        TranslationAgent,
        # Product delivery
        NetworkMonitorOnboardingAgent,
        PatchComplianceReporterAgent,
        SecurityScopingAgent,
        TaskAutomatorAgent,
        KbLookupAgent,
        # Reply intent + conversion (Phase 4)
        ReplyIntentAgent,
        ReplyDraftAgent,
        # Inbound email triage (Phase 19)
        InboundEmailAgent,
        # LinkedIn outreach (Phase 20)
        LinkedinOutreachAgent,
        # Integrations / recovery (Phase 21-25)
        CrmIntegrationAgent,
        EmailIntegrationAgent,
        RollbackRecoveryAgent,
        # Content editors / validators (Phase 26-32)
        TestHarnessAgent,
        HomepageAboutEditorAgent,
        ServicesPricingEditorAgent,
        GermanCopyEditorAgent,
        BlogCaseStudyDraftAgent,
        SecurityValidatorAgent,
        AuthPermissionsValidatorAgent,
        # Bilingual outreach (Phase 3)
        LanguageDetectionAgent,
        ConsentValidationAgent,
        BilingualOutreachAgent,
        BilingualProposalAgent,
        BilingualReportingAgent,
        # Division coordinators
        SalesDivisionAgent,
        EngineeringDivisionAgent,
        DesignDivisionAgent,
        # Freelance platform pipeline (Phase 5)
        FreelanceScoutAgent,
        BidStrategyAgent,
        PlatformBidSubmitterAgent,
        PlatformClientConverterAgent,
        VoiceCallAgent,
        VapiWebhookProcessorAgent,
        CalendlyWebhookAgent,
        # Batch refresh
        LeadScoringRefreshAgent,
        # Reporting
        DailyReportAgent,
        PipelineReporterAgent,
        # Client intelligence (Phase 6)
        RevenueAnalyticsAgent,
        ClientHealthAgent,
        UpsellOpportunityAgent,
        # Reporting enhancements (Phase 7)
        WeeklyReportAgent,
        KPIDashboardAgent,
        # Market intelligence (Phase 7)
        CompetitorMonitorAgent,
        SEOOpportunityAgent,
        # Content & lifecycle (Phase 7)
        ContentCalendarAgent,
        ContractRenewalAgent,
        # RARV journal team -- write path into the vault
        RARVReasonerAgent,
        RARVWriterAgent,
        RARVReflectorAgent,
        RARVVerifierAgent,
        # Orchestrator (last)
        LokiOrchestratorAgent,
    ]:
        registry.register(agent_cls())


_bootstrap()
