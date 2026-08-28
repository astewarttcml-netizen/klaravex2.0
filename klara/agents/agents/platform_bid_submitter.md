# Platform Bid Submitter Agent

## Overview

The `PlatformBidSubmitterAgent` is responsible for submitting bids to freelance platforms (Freelancer.com, Upwork, Guru, and PeoplePerHour) based on qualified projects. It implements a daily cap mechanism to prevent excessive submissions and includes comprehensive error handling.

This agent runs every 30 minutes during business hours (08:00-20:00 CET weekdays) as part of the freelance platform pipeline. It processes queued bids from the `PlatformBid` table and submits them to appropriate platforms with daily cap protection.

## Key Features

1. **Daily Cap Enforcement**: Prevents submitting more than 50 bids per day on Freelancer.com
2. **Platform-Specific Handling**:
   - Freelancer.com: Uses API for automated submissions via the `growth/adapters/freelancer.py` adapter
   - Upwork, Guru, PeoplePerHour: Uses session cookies for HTTP session-based submissions
3. **Comprehensive Error Handling**: Tracks submission failures and logs detailed error information
4. **Status Management**: Updates bid statuses in the database after submission attempts

## Agent Flow

1. Fetch all queued bids from the `PlatformBid` table (status = 'queued')
2. For each bid:
   - Check if the platform is supported (Freelancer.com, Upwork, Guru, PeoplePerHour)
   - Validate the bid's eligibility for submission
   - Submit to the appropriate platform:
     - **Freelancer.com**: API call using `growth/adapters/freelancer.py` with daily cap enforcement
     - **Other platforms**: Session-based HTTP requests using cookies from `growth/sessions/vault.py`
3. Update bid statuses in the database based on submission results
4. Log statistics about submissions, errors, and manual requirements

## Daily Cap Mechanism

The agent implements a daily cap of 50 bids for Freelancer.com to prevent account restrictions or rate limiting. It:
- Tracks bid submissions within the current day using the `growth/adapters/freelancer.py` adapter
- Prevents exceeding the cap
- Logs skipped submissions when cap is reached

## Error Handling

The agent handles various error scenarios:
- API connection failures (Freelancer.com)
- Invalid bid data
- Platform-specific errors (session cookies, authentication)
- Database update failures

All errors are logged with detailed information and bid statuses are updated accordingly.

## Database Integration

The agent interacts with the `PlatformBid` table to:
1. Query queued bids (status = 'queued')
2. Update bid statuses after submission attempts
3. Track submission results

## Usage in Pipeline

This agent is scheduled to run every 30 minutes during business hours:
```bash
# Scheduled task in Celery
run_bid_submission  # Every 30 minutes (08:00-20:00 CET weekdays)
```

The agent is registered in `klara/agents/agents/registry.py` and called from `klara/agents/tasks/freelance_tasks.py`.

## Integration with Growth Adapters

The agent leverages the existing growth adapter system:
- **Freelancer.com**: Uses `growth/adapters/freelancer.py` which integrates with `growth/sessions/vault.py` for OAuth token management
- **Other platforms**: Use session-based approaches via `growth/sessions/vault.py` and `growth/sessions/login.py`

## Environment Requirements

Set the required environment variables:
```bash
# For Freelancer.com
export FREELANCER_ACCESS_TOKEN="your_oauth_token_here"

# For other platforms, cookies are managed through the session vault system
```