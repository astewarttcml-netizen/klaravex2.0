# Outreach Plan: Neighborhood Christian Legal Clinic

## Company Overview
- **Company**: Neighborhood Christian Legal Clinic
- **Domain**: nclegalclinic.org
- **Contact**: Dakota Truelove (IT Operations Manager)
- **Location**: Indianapolis, Indiana
- **Employee Count**: 46

## Key Security Findings
Based on our security research, we've identified several critical vulnerabilities in your website that need immediate attention:

### Critical Issues:
1. **Missing Security Headers** (web-01, web-02, web-03):
   - Missing Content-Security-Policy header
   - Missing Referrer-Policy header  
   - Missing Permissions-Policy header

2. **Infrastructure Concerns** (web-04, web-05):
   - Server: Squarespace (no version hardening)
   - CMS: Squarespace (no additional security layers)

3. **Email Security Vulnerabilities** (web-06, web-07):
   - Email: Microsoft 365 (requires proper configuration)
   - SSL: Using Let's Encrypt (free cert — no EV/OV validation)

4. **DNS Security Issues** (web-08, web-09):
   - DMARC policy is 'none' — monitoring only, no enforcement
   - SPF uses ~all (softfail) instead of -all (hardfail)

## Outreach Strategy

### Personalized Message for Dakota Truelove:
Subject: Security Recommendations for nclegalclinic.org

Hi Dakota,

I hope this message finds you well. I'm reaching out from [Your Company Name] to share some important security insights regarding your website at nclegalclinic.org.

Our research has identified several critical vulnerabilities that could pose risks to your organization and the sensitive data of your clients:

1. Missing essential security headers (Content-Security-Policy, Referrer-Policy, Permissions-Policy)
2. Weak email security configurations
3. DNS security issues with DMARC and SPF policies

These findings are particularly concerning given the sensitive nature of legal clinic work and client information. 

Would you be open to a brief discussion about how we might help strengthen your digital security posture?

Best regards,
[Your Name]
[Your Title]
[Your Company Name]
[Your Contact Information]

### Follow-up Approach:
- Send initial outreach via email
- If no response within 3 days, send a follow-up message
- Offer to schedule a brief call or meeting to discuss solutions

## Next Steps
1. Prepare technical documentation outlining the specific security issues
2. Develop a value proposition highlighting how improved security can benefit their legal practice
3. Create a presentation deck for potential meetings