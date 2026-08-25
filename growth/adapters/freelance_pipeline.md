# Freelance Bid Pipeline

The Freelance Bid Pipeline is a comprehensive system for managing bid submissions across multiple freelance platforms with enhanced scoring and management capabilities.

## Features

- **Multi-Platform Support**: Submit bids to Freelancer.com, Freelancermap_de, and manual platforms
- **Project Scoring**: AI-powered project scoring using Claude LLM 
- **Bid Validation**: Platform-specific bid amount validation
- **Bid Management**: Daily caps, kill switches, and status tracking
- **Error Handling**: Comprehensive error handling with detailed logging
- **Security**: Cookie renewal and emergency kill switch functionality

## Endpoints

### Core Functionality
- `POST /freelance/score_project` - Score projects based on various factors
- `POST /freelance/submit_bid` - Submit a bid to one or more platforms
- `POST /freelance/submit_multiple_bids` - Submit multiple bids in parallel

### Management
- `GET /freelance/bid_status/{project_id}` - Get status of bids for a project
- `POST /freelance/renew_cookies` - Renew cookies for all platforms
- `POST /freelance/kill_switch` - Toggle kill switch for bid submissions
- `GET /freelance/bid_statistics` - Get bid submission statistics

### Utility
- `POST /freelance/validate_skills` - Validate skills against platform requirements
- `GET /freelance/health` - Health check endpoint

## Platform Configuration

The pipeline supports the following platforms:
- `freelancer`: Freelancer.com adapter
- `freelancermap_de`: Freelancermap.de adapter  
- `manual`: Manual bid submission adapter

## Implementation Details

The system uses a modular approach with dedicated adapters for each platform, ensuring clean separation of concerns while maintaining a unified interface for bid management.