"""KB content: 2 missing articles + 4 category pages for klaravex.com."""
from gen import article, category, section

P = lambda *ps: ''.join(f'<p>{x}</p>' for x in ps)
def UL(*items): return '<ul>' + ''.join(f'<li>{i}</li>' for i in items) + '</ul>'

# ---------- ARTICLE: Microsoft Secure Score ----------
def secure_score():
    secs = (
        section('The basics', 'What Microsoft Secure Score actually measures',
            P("Microsoft Secure Score is a security posture rating built into the Microsoft 365 admin center (Microsoft Defender portal). It scores your tenant against a list of recommended security controls — things like enforcing multi-factor authentication, blocking legacy authentication, and limiting admin accounts — and gives you a single percentage and a points total.",
              "The score is <strong>relative</strong>, not absolute. A higher score means you have turned on more of Microsoft's recommended protections; it does not guarantee you are unbreachable. Think of it as a prioritized to-do list with a progress bar, not a compliance certificate.")) + \
        section('How it works', 'Points, categories, and comparison',
            P("Each recommended action is worth a set number of points. You earn the points by implementing the control (or by marking it as covered by a third-party tool or accepted as a risk). Actions are grouped into three areas:") +
            UL("<strong>Identity</strong> — accounts, MFA, conditional access, admin hygiene",
               "<strong>Devices</strong> — endpoint protection, patching, device compliance (if you use Intune/Defender for Endpoint)",
               "<strong>Apps &amp; Data</strong> — email protection, sharing controls, DLP") +
            P("Microsoft also shows how your score compares to organizations of similar size and industry, which is useful context when you report to leadership.")) + \
        section('The work', 'The highest-impact actions to do first',
            P("Most small businesses can move their score substantially in an afternoon by doing the high-value, low-friction items first:") +
            UL("Require MFA for <em>all</em> users (and especially every admin)",
               "Block legacy/basic authentication protocols",
               "Reduce the number of Global Administrators to two or three, and use a separate admin account",
               "Turn on Safe Links and Safe Attachments in Defender for Office 365",
               "Enable a conditional access policy that blocks sign-ins from unexpected countries") +
            P("Avoid chasing the last few percent for its own sake. Some actions require licenses you may not have, or introduce friction that is not worth the points for your environment.")) + \
        callout_block())
    faqs = [
        ("What is a good Microsoft Secure Score?",
         "There is no universal pass mark. Many small businesses sit in the 30&ndash;45% range before any hardening and can reach 60&ndash;75% with the licenses they already own. The right target is &ldquo;all the controls that make sense for our risk and licensing,&rdquo; not a round number."),
        ("Does a high Secure Score mean we are compliant with HIPAA or SOC 2?",
         "No. Secure Score is a Microsoft-specific posture metric. It overlaps with many compliance controls but is not a substitute for a framework assessment. It is, however, strong supporting evidence that you take technical controls seriously."),
        ("Will improving our score annoy our users?",
         "Some actions add friction (MFA prompts, blocked legacy apps). The trick is sequencing: roll out MFA and conditional access carefully with exclusions and communication. A managed provider does this without locking people out."),
        ("How often should we check it?",
         "Review it monthly. The score drifts as Microsoft adds new recommendations and as your configuration changes. We monitor it continuously for managed clients and act on regressions automatically."),
    ]
    return article('Security Guide',
        'What is a Microsoft Secure Score and how do you improve it?',
        'A plain-English guide to the security rating built into Microsoft 365 — what it measures, which actions matter most, and how far to take it.',
        'microsoft-secure-score', secs, faqs,
        'Want us to raise your Secure Score for you?',
        'We harden Microsoft 365 the right way &mdash; MFA, conditional access, and email protection &mdash; without locking your team out. Most clients see a major jump in week one.')

def callout_block():
    from gen import callout
    return callout('The trap: turning on everything at once',
        'It is tempting to implement every recommendation in one session to maximize the number. Don&rsquo;t. Enabling conditional access and blocking legacy auth without a rollout plan can lock out shared mailboxes, scanners, and older line-of-business apps. Stage changes, use report-only mode first, and communicate with your team.')

# ---------- ARTICLE: HIPAA for a small practice ----------
def hipaa():
    from gen import callout
    secs = (
        section('Start here', 'HIPAA is about safeguards, not a single checkbox',
            P("HIPAA does not certify software or hand out a pass/fail badge. It requires &ldquo;reasonable and appropriate&rdquo; administrative, physical, and technical safeguards for protected health information (PHI). For a small practice, that translates into a manageable set of concrete steps &mdash; not a six-figure project.",
              "The core obligations come from two rules: the <strong>Privacy Rule</strong> (who can access PHI and how it&rsquo;s used) and the <strong>Security Rule</strong> (how electronic PHI is protected technically and operationally).")) + \
        section('The essentials', 'What a small practice actually needs',
            UL("<strong>A risk analysis.</strong> A documented assessment of where PHI lives and what could go wrong. This is the single most commonly missing item in audits.",
               "<strong>Business Associate Agreements (BAAs).</strong> Signed with every vendor that touches PHI &mdash; your EHR, email provider, cloud backup, billing service, and IT provider. Microsoft and Google both sign BAAs on eligible plans.",
               "<strong>Access controls.</strong> Unique logins per person, MFA, and least-privilege access &mdash; no shared &lsquo;frontdesk&rsquo; accounts.",
               "<strong>Encryption.</strong> Encrypted laptops/phones and encrypted email when PHI is sent externally.",
               "<strong>Audit logging &amp; backups.</strong> The ability to see who accessed records, plus tested backups you can actually restore.",
               "<strong>Policies &amp; training.</strong> Written policies and annual staff training, with records that it happened.")) + \
        section('Common gaps', 'Where small practices usually fall short',
            P("In our experience the failures are rarely exotic. They are:") +
            UL("No documented risk analysis (or one done years ago and never updated)",
               "Texting or emailing PHI without encryption",
               "A missing BAA with the IT company or a backup vendor",
               "Staff sharing a single login to the practice management system",
               "No tested backup &mdash; backups &lsquo;running&rsquo; but never restore-tested")) + \
        callout('The &ldquo;HIPAA-compliant software&rdquo; myth',
            'No product can make you HIPAA compliant on its own. A vendor can be HIPAA-<em>eligible</em> and sign a BAA, but compliance is about how <em>you</em> configure and operate it. Be skeptical of any tool marketed as &ldquo;instant HIPAA compliance.&rdquo;')
    )
    faqs = [
        ("Do we need a HIPAA certification?",
         "There is no official government HIPAA certification. Third-party assessments and attestations exist and can be useful for demonstrating diligence, but no certificate makes you &lsquo;HIPAA certified&rsquo; in a legal sense. What matters is documented safeguards and a current risk analysis."),
        ("Is regular email HIPAA compliant?",
         "Standard email is not, by itself. You need encryption for PHI sent outside your organization and a BAA with your email provider. Microsoft 365 and Google Workspace can both be configured for this on the right plans."),
        ("How much does HIPAA readiness cost a small practice?",
         "Far less than most expect. The big costs are usually a proper risk analysis and closing technical gaps (MFA, encryption, backup). For most small practices it is a modest project plus ongoing maintenance &mdash; not a major capital expense."),
        ("What happens if we have a breach?",
         "The Breach Notification Rule requires notifying affected individuals (and, above certain thresholds, HHS and the media) within set timeframes. Having a documented risk analysis, encryption, and an incident plan dramatically reduces both the likelihood and the penalty exposure."),
    ]
    return article('Compliance Guide',
        'What HIPAA actually requires of a small medical practice',
        'The core safeguards in plain English &mdash; what you genuinely need, where small practices usually fall short, and what to ignore.',
        'hipaa-small-practice', secs, faqs,
        'Need to get your practice HIPAA-ready?',
        'We run the risk analysis, close the technical gaps, and put the BAAs and policies in place &mdash; then keep you compliant year-round. A certified engineer owns the outcome.')

# ---------- CATEGORY PAGES ----------
def cat_security():
    return category('Security', 'Security', 'Passwords, MFA, phishing, and what actually protects your accounts and data.', 'security', [
        ('What to do if you think you&rsquo;ve been hacked', 'A calm, step-by-step response for the first 60 minutes after a suspected breach.', '/knowledge-base/what-to-do-if-hacked/'),
        ('How to set up multi-factor authentication on every account', 'MFA done right across Microsoft 365, Google, Apple, and LinkedIn.', '/knowledge-base/multi-factor-authentication-setup/'),
        ('What is a Microsoft Secure Score and how do you improve it?', 'Understand the M365 security rating and the highest-impact actions.', '/knowledge-base/microsoft-secure-score/'),
        ('Locked out of your account? How to reset access', 'Recover access safely without making the problem worse.', '/knowledge-base/password-account-lockout/'),
    ])
def cat_m365():
    return category('Microsoft 365 &amp; Cloud', 'Microsoft 365 &amp; Cloud', 'Setup, migration, admin, and getting the most out of M365 and Google Workspace.', 'microsoft-365', [
        ('Microsoft 365 vs Google Workspace: which is right for you?', 'A no-agenda comparison across the five dimensions that matter.', '/knowledge-base/m365-vs-google-workspace/'),
        ('Setting up email on Outlook, Gmail, and iPhone', 'Get business email working correctly on every device.', '/knowledge-base/email-setup/'),
    ])
def cat_business():
    return category('Business IT', 'Business IT', 'The everyday fixes that keep a business running &mdash; networks, devices, and access.', 'business-it', [
        ('Setting up and troubleshooting VPN on Windows and Mac', 'Secure remote access that actually connects.', '/knowledge-base/vpn-setup/'),
        ('Computer running slow? How to speed it up', 'Practical fixes before you replace the hardware.', '/knowledge-base/slow-computer/'),
        ('WiFi not working? Common fixes for Windows and Mac', 'Diagnose and fix the most common connectivity problems.', '/knowledge-base/wifi-troubleshooting/'),
        ('Printer not working? Step-by-step fixes', 'Get printing again without a technician visit.', '/knowledge-base/printer-troubleshooting/'),
        ('Browser problems? Fixes for Chrome, Edge, and Safari', 'Clear up crashes, slowness, and broken sites.', '/knowledge-base/browser-issues/'),
        ('Windows updates &mdash; what to do when it keeps asking to restart', 'Handle updates without losing work.', '/knowledge-base/windows-update/'),
    ])
def cat_readiness():
    return category('IT Readiness', 'IT Readiness', 'HIPAA, SOC 2, cyber insurance &mdash; what small and mid-sized businesses really need.', 'it-readiness', [
        ('What HIPAA actually requires of a small medical practice', 'The core safeguards in plain English &mdash; and what to ignore.', '/knowledge-base/hipaa-small-practice/'),
    ])

PAGES = {
    'article-microsoft-secure-score': secure_score,
    'article-hipaa-small-practice': hipaa,
    'cat-security': cat_security,
    'cat-microsoft-365': cat_m365,
    'cat-business-it': cat_business,
    'cat-it-readiness': cat_readiness,
}
