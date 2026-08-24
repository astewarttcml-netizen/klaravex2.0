"""
app/services/atera_client.py
─────────────────────────────
Async wrapper for the Atera REST API v3.

Auth: Bearer JWT — set via ATERA_API_KEY env var (see app/config.py).
Base URL: https://app.atera.com/api/v3

Endpoints used:
  GET  /customers             — look up "Personal Clients" customer
  POST /customers             — create consumer customer bucket on first use
  GET  /contacts              — find existing contact by email
  POST /contacts              — create contact (end-user) under customer
  POST /tickets               — create support ticket
  GET  /tickets/{id}          — verify ticket was created

Pattern: Atera's POST endpoints return {"ActionID": "<int>"} where the
ActionID IS the new record's ID.  We do a quick verify GET to confirm.
"""
from __future__ import annotations

import asyncio
import httpx
import structlog

logger = structlog.get_logger(__name__)

_BASE = "https://app.atera.com/api/v3"
_PERSONAL_CUSTOMER_NAME = "Personal Clients"


class AteraError(Exception):
    pass


class AteraClient:
    def __init__(self, api_key: str):
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_BASE,
            headers=self._headers,
            timeout=30.0,
        )

    # ── Customers ─────────────────────────────────────────────────────────────

    async def get_or_create_personal_customer(self) -> int:
        """
        Return the CustomerID for "Personal Clients", creating it if needed.
        All consumer support contacts live under this single customer bucket.
        """
        async with self._client() as c:
            r = await c.get("/customers", params={"page": 1, "itemsInPage": 50})
            r.raise_for_status()
            for item in r.json().get("items", []):
                if item["CustomerName"] == _PERSONAL_CUSTOMER_NAME:
                    return item["CustomerID"]

            # Not found — create it
            r2 = await c.post("/customers", json={
                "CustomerName": _PERSONAL_CUSTOMER_NAME,
                "Country": "US",
            })
            r2.raise_for_status()
            customer_id = int(r2.json()["ActionID"])
            logger.info("atera.customer_created", customer_id=customer_id)
            return customer_id

    # ── Contacts ──────────────────────────────────────────────────────────────

    async def get_or_create_contact(
        self,
        customer_id: int,
        email: str,
        firstname: str,
        lastname: str,
        phone: str = "",
    ) -> int:
        """
        Return EndUserID for this email, creating the contact if not found.
        Retries once on 5xx in case the parent customer was just created.
        """
        async with self._client() as c:
            # Search by email (Atera does partial match, we exact-match in Python)
            r = await c.get("/contacts", params={
                "page": 1,
                "itemsInPage": 50,
                "Email": email,
            })
            r.raise_for_status()
            for item in r.json().get("items", []):
                if item.get("Email", "").lower() == email.lower():
                    return item["EndUserID"]

            # Create new contact — retry once on 5xx (race with freshly-created customer)
            payload = {
                "CustomerID": customer_id,
                "Firstname": firstname or "Unknown",
                "Lastname": lastname or "Client",
                "Email": email,
                "IsContactPerson": True,
            }
            if phone:
                payload["Phone"] = phone

            for attempt in range(2):
                r2 = await c.post("/contacts", json=payload)
                if r2.status_code < 500 or attempt == 1:
                    r2.raise_for_status()
                    break
                logger.warning("atera.contact_create_retry", attempt=attempt, status=r2.status_code)
                await asyncio.sleep(1.5)

            contact_id = int(r2.json()["ActionID"])
            logger.info("atera.contact_created", contact_id=contact_id, email=email)
            return contact_id

    # ── Tickets ───────────────────────────────────────────────────────────────

    async def create_ticket(
        self,
        end_user_id: int,
        title: str,
        first_comment: str,
        priority: str = "Medium",
        ticket_type: str = "Problem",
    ) -> dict:
        """
        Create a support ticket and return {"ticket_id": int, "ticket_number": str}.
        Priority: Low | Medium | High | Critical
        """
        async with self._client() as c:
            payload = {
                "TicketTitle": title[:100],
                "TicketType": ticket_type,
                "TicketPriority": priority,
                "TicketImpact": "NoImpact",
                "TicketSource": "Chat",
                "TicketStatus": "Open",
                "EndUserID": end_user_id,
                "FirstComment": first_comment,
            }
            r = await c.post("/tickets", json=payload)
            r.raise_for_status()
            ticket_id = int(r.json()["ActionID"])

            # Fetch to get ticket number — retry once, Atera may need a moment to index
            ticket: dict = {}
            for attempt in range(3):
                await asyncio.sleep(1.0)
                r2 = await c.get(f"/tickets/{ticket_id}")
                if r2.status_code == 200:
                    ticket = r2.json()
                    break
                if attempt == 2:
                    r2.raise_for_status()

            logger.info(
                "atera.ticket_created",
                ticket_id=ticket_id,
                number=ticket.get("TicketNumber"),
            )
            return {
                "ticket_id": ticket_id,
                "ticket_number": ticket.get("TicketNumber", str(ticket_id)),
            }

    # ── Convenience: full consumer onboarding in one call ─────────────────────

    async def onboard_consumer(
        self,
        name: str,
        email: str,
        problem: str,
        device: str = "",
        phone: str = "",
    ) -> dict:
        """
        Single call that:
          1. Gets/creates the Personal Clients customer
          2. Gets/creates the consumer contact
          3. Creates a ticket with full problem description

        Returns {customer_id, contact_id, ticket_id, ticket_number}.
        """
        parts = (name.strip().split(" ", 1) + [""])[:2]
        firstname, lastname = parts[0], parts[1] or "Client"

        title = f"Remote Support: {problem[:60]}"
        body = f"Device: {device or 'not specified'}\n\nProblem:\n{problem}"

        customer_id = await self.get_or_create_personal_customer()
        contact_id = await self.get_or_create_contact(
            customer_id, email, firstname, lastname, phone
        )
        ticket = await self.create_ticket(
            end_user_id=contact_id,
            title=title,
            first_comment=body,
        )
        return {
            "customer_id": customer_id,
            "contact_id": contact_id,
            "ticket_id": ticket["ticket_id"],
            "ticket_number": ticket["ticket_number"],
        }
