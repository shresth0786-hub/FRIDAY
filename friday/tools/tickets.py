"""
Ticketing tools — log issues to a Supabase table.

Setup (one-time, in the Supabase SQL editor):

    create table tickets (
        id bigint generated always as identity primary key,
        created_at timestamptz not null default now(),
        title text not null,
        details text,
        status text not null default 'open'
    );

Then set SUPABASE_URL and SUPABASE_API_KEY in .env.
"""

import httpx

from friday.config import config


def _headers() -> dict:
    return {
        "apikey": config.SUPABASE_API_KEY,
        "Authorization": f"Bearer {config.SUPABASE_API_KEY}",
        "Content-Type": "application/json",
    }


def _configured() -> bool:
    return bool(
        config.SUPABASE_API_KEY
        and config.SUPABASE_API_KEY != "your-supabase-api-key"
        and config.SUPABASE_URL
        and "your-project-id" not in config.SUPABASE_URL
    )


def register(mcp):

    @mcp.tool()
    async def create_ticket(title: str, details: str = "") -> str:
        """
        Create a support ticket for a problem the user reports.
        Use when the user reports an issue, asks to log or raise something.
        Returns the new ticket's reference number.
        """
        if not _configured():
            return (
                "Ticketing isn't configured yet, boss — "
                "Supabase keys are missing from the environment."
            )

        payload = {
            "title": title[:200],
            "details": details[:2000],
            "status": "open",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{config.SUPABASE_URL}/tickets",
                    headers=_headers(),
                    json=payload,
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            return f"I couldn't file that ticket ({exc.__class__.__name__}), boss."

        ticket = resp.json()
        ticket_id = ticket.get("id", "?")
        return f"Ticket #{ticket_id} filed, boss. I've logged: {title}"

    @mcp.tool()
    async def list_tickets(status: str = "open") -> str:
        """
        List support tickets, newest first. Default shows open tickets only.
        """
        if not _configured():
            return (
                "Ticketing isn't configured yet, boss — "
                "Supabase keys are missing from the environment."
            )

        params = {
            "select": "id,created_at,title,status",
            "status": f"eq.{status}",
            "order": "created_at.desc",
            "limit": "10",
        }
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{config.SUPABASE_URL}/tickets",
                    headers=_headers(),
                    params=params,
                )
                resp.raise_for_status()
        except httpx.HTTPError as exc:
            return f"I couldn't pull the ticket list ({exc.__class__.__name__}), boss."

        tickets = resp.json()
        if not tickets:
            return f"No {status} tickets right now, boss."

        lines = [f"### TICKETS ({status})\n"]
        for t in tickets:
            when = t.get("created_at", "")[:10]
            lines.append(f"#{t['id']} [{when}] {t['title']} — {t.get('status', 'open')}")
        return "\n".join(lines)
