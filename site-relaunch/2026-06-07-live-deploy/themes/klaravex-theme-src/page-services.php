<?php
/**
 * Template Name: Services Index
 * Description: Themed services index (4 pillars, 14 services). Auto-applied by
 *              kvx_services_template() to the Services index page (id 14).
 *
 * Content mirrors the live /business/services/ page — nothing invented.
 */

get_header();

$services_hero_sub = 'Every engagement starts with your environment, not a product catalog. Platform-agnostic. Opinionated about quality. Delivered by a certified senior engineer.';

/* ────────────────────────────────────────────────────────────
   PILLARS + CARDS  (exact copy + URLs from the live page)
   icon = Phosphor icon name; url = existing service URL (kept intact)
──────────────────────────────────────────────────────────── */
$pillars = [
    [
        'num'   => '01',
        'label' => 'Pillar 01 — Network &amp; Security',
        'title' => 'Network &amp; Security',
        'desc'  => 'Hands-on firewall expertise across 7 enterprise platforms. No vendor bias — the right tool for your environment.',
        'cards' => [
            [
                'icon'  => 'ph-shield-check',
                'title' => 'Firewall &amp; Network Security',
                'desc'  => 'Deployment, rule set design, policy hardening, and ongoing management across all major enterprise firewall platforms. Vendor-neutral assessment.',
                'tags'  => 'Palo Alto · FortiGate · Cisco · Check Point · SonicWall · pfSense',
                'url'   => '/business/services/firewall-network-security/',
            ],
            [
                'icon'  => 'ph-magnifying-glass',
                'title' => 'IT Security Audit',
                'desc'  => 'Structured security review of your existing infrastructure: firewall rules, identity attack surface, logging gaps, data exposure risks. Prioritised findings with remediation steps.',
                'tags'  => 'Firewall audit · Attack surface · HIPAA / SOC 2 · Remediation roadmap',
                'url'   => '/business/services/it-security-audit/',
            ],
            [
                'icon'  => 'ph-bug',
                'title' => 'Penetration Testing',
                'desc'  => 'Network and application penetration testing. Internal, external, and wireless scopes. Written report with CVE-referenced findings and prioritised remediation.',
                'tags'  => 'External · Internal · Social engineering · Written report',
                'url'   => '/business/services/penetration-testing/',
            ],
            [
                'icon'  => 'ph-lock-key',
                'title' => 'Zero Trust Architecture',
                'desc'  => 'Identity-first access, microsegmentation, device trust, application-level controls, and continuous verification. Cloud-native and network-layer Zero Trust patterns.',
                'tags'  => 'Identity-first · Microsegmentation · Least privilege · Continuous verification',
                'url'   => '/business/services/firewall-network-security/',
            ],
        ],
    ],
    [
        'num'   => '02',
        'label' => 'Pillar 02 — Strategy &amp; Transformation',
        'title' => 'Strategy &amp; Transformation',
        'desc'  => 'Strategic IT at the level above tickets. For founders who need a trusted technical advisor — not a vendor sales channel.',
        'promo' => [
            'text' => '→ Cyber Insurance Readiness Assessment',
            'url'  => '/business/services/cyber-insurance-readiness/',
        ],
        'cards' => [
            [
                'icon'  => 'ph-compass',
                'title' => 'IT Strategy &amp; vCIO',
                'desc'  => 'Part-time strategic technology leadership. IT roadmap, budget planning, vendor evaluation, board-level IT reporting, and technology governance for growing companies.',
                'tags'  => 'IT Roadmap · Budget planning · Risk governance · Board reporting',
                'url'   => '/business/services/it-strategy-vcio/',
            ],
            [
                'icon'  => 'ph-robot',
                'title' => 'AI Automation &amp; Workflow Engineering',
                'desc'  => 'Practical AI integration: workflow automation, internal tooling, document processing, AI-assisted reporting. Python and PowerShell pipelines. API integrations that get used, not demoed.',
                'tags'  => 'Workflow automation · API integration · Python · Document processing',
                'url'   => '/business/services/ai-automation/',
            ],
            [
                'icon'  => 'ph-shopping-cart',
                'title' => 'IT Procurement',
                'desc'  => 'Vendor-neutral hardware and software procurement. Specification, sourcing, comparison, and purchasing. No reseller agreements — recommendations based entirely on your requirements.',
                'tags'  => 'Vendor-neutral · Hardware · Software licensing · No commissions',
                'url'   => '/business/services/it-procurement/',
            ],
        ],
    ],
    [
        'num'   => '03',
        'label' => 'Pillar 03 — Cloud &amp; Productivity',
        'title' => 'Cloud &amp; Productivity',
        'desc'  => 'The full Microsoft stack, deployed to enterprise standards. Setup, migration, hardening, and ongoing management.',
        'cards' => [
            [
                'icon'  => 'ph-cloud',
                'title' => 'Microsoft Azure',
                'desc'  => 'IaaS/PaaS deployment, subscription architecture, cost optimization, migration from on-premises or competing clouds, security hardening.',
                'tags'  => 'IaaS / PaaS · Migration · Cost optimization · Azure Monitor',
                'url'   => '/business/services/microsoft-azure/',
            ],
            [
                'icon'  => 'ph-tray',
                'title' => 'Microsoft 365',
                'desc'  => 'Tenant setup, Exchange Online, Teams, SharePoint, OneDrive. Email security (DKIM/DMARC/SPF), DLP, compliance config. Migration from Google Workspace or on-premises Exchange.',
                'tags'  => 'Exchange Online · Teams · Email security · DLP',
                'url'   => '/business/services/microsoft-365/',
            ],
            [
                'icon'  => 'ph-device-mobile',
                'title' => 'Microsoft Intune',
                'desc'  => 'MDM/MAM for Windows, macOS, iOS, Android. Compliance policies, Autopilot provisioning, BYOD programs, Conditional Access integration.',
                'tags'  => 'MDM / MAM · Autopilot · Compliance policies · BYOD',
                'url'   => '/business/services/intune-endpoint-management/',
            ],
            [
                'icon'  => 'ph-fingerprint',
                'title' => 'Entra ID &amp; Identity',
                'desc'  => 'Hybrid identity, SSO, MFA enforcement, Conditional Access, Privileged Identity Management. SAML/OIDC integrations. Legacy authentication lockdown.',
                'tags'  => 'SSO / MFA · Conditional Access · PIM · SAML / OIDC',
                'url'   => '/business/services/intune-endpoint-management/',
            ],
        ],
    ],
    [
        'num'   => '04',
        'label' => 'Pillar 04 — Infrastructure &amp; Support',
        'title' => 'Infrastructure &amp; Support',
        'desc'  => 'The unglamorous foundation that everything else depends on. Remote support nationwide.',
        'cards' => [
            [
                'icon'  => 'ph-server',
                'title' => 'Windows Server &amp; Active Directory',
                'desc'  => 'Domain design, DNS, DHCP, Group Policy, AD security hardening (LAPS, Kerberoasting mitigation, tiered admin model), hybrid join to Entra ID.',
                'tags'  => 'Active Directory · Group Policy · LAPS · Hybrid join',
                'url'   => '/business/services/windows-server-infrastructure/',
            ],
            [
                'icon'  => 'ph-database',
                'title' => 'Backup &amp; Disaster Recovery',
                'desc'  => 'Veeam-based backup design, RPO/RTO definition, backup validation, test restores, DR runbooks. Know how long recovery takes before you need to find out the hard way.',
                'tags'  => 'Veeam · RPO / RTO · DR testing · Failover runbooks',
                'url'   => '/business/services/backup-disaster-recovery/',
            ],
            [
                'icon'  => 'ph-terminal-window',
                'title' => 'PowerShell Automation',
                'desc'  => 'Provisioning, reporting, compliance checking, and operational tasks automated via PowerShell and Microsoft Graph API for M365, Entra ID, and Intune.',
                'tags'  => 'PowerShell · Graph API · Provisioning · Automation',
                'url'   => '/business/services/powershell-automation/',
            ],
            [
                'icon'  => 'ph-headset',
                'title' => 'Remote IT Support &amp; Monitoring',
                'desc'  => '2-hour remote response for US businesses nationwide. Proactive network and endpoint monitoring — issues flagged before they become outages.',
                'tags'  => '2hr SLA · Nationwide · Proactive monitoring · Endpoint management',
                'url'   => '/business/services/remote-it-support/',
            ],
        ],
    ],
];
?>
<main id="main" role="main" class="kx-services-index">

  <!-- HERO -->
  <section class="hero kx-svc-hero" id="services-hero">
    <div class="hero-photo" role="img" aria-label="<?php esc_attr_e('Managed IT and security environment','klaravex'); ?>"></div>
    <div class="hero-mesh" aria-hidden="true"></div>
    <div class="hero-grid" aria-hidden="true"></div>

    <div class="wrap">
      <div class="hero-body">
        <div class="hero-eyebrow reveal">
          <div class="hero-eyebrow-dot" aria-hidden="true"></div>
          <?php esc_html_e('Services','klaravex'); ?>
        </div>

        <h1 class="reveal reveal-d1"><?php esc_html_e('Four pillars.', 'klaravex'); ?> <span class="accent"><?php esc_html_e('Fourteen services.', 'klaravex'); ?></span></h1>

        <p class="hero-sub reveal reveal-d2"><?php echo esc_html( $services_hero_sub ); ?></p>
      </div>
    </div>
  </section>

  <!-- PILLARS -->
  <?php foreach ( $pillars as $i => $pillar ) :
      $delay = 'd' . ( $i + 1 ); ?>
  <section class="svc-pillar" id="pillar-<?php echo esc_attr( $pillar['num'] ); ?>">
    <div class="wrap">
      <div class="section-label reveal"><?php echo wp_kses_post( $pillar['label'] ); ?></div>
      <h2 class="section-h reveal reveal-d1"><?php echo wp_kses_post( $pillar['title'] ); ?></h2>
      <p class="section-sub reveal reveal-d2"><?php echo esc_html( $pillar['desc'] ); ?></p>

      <div class="svc-grid">
        <?php foreach ( $pillar['cards'] as $ci => $card ) :
            $cdelay = 'd' . ( $ci + 1 ); ?>
        <div class="service-card svc-card reveal reveal-<?php echo esc_attr( $cdelay ); ?>">
          <div class="service-ico" aria-hidden="true"><i class="ph <?php echo esc_attr( $card['icon'] ); ?>"></i></div>
          <h3><?php echo wp_kses_post( $card['title'] ); ?></h3>
          <p class="svc-desc"><?php echo esc_html( $card['desc'] ); ?></p>
          <div class="svc-tags"><?php echo esc_html( $card['tags'] ); ?></div>
          <a href="<?php echo esc_url( $card['url'] ); ?>" class="service-link">
            <?php esc_html_e('View service','klaravex'); ?>
            <i class="ph ph-arrow-right" aria-hidden="true"></i>
          </a>
        </div>
        <?php endforeach; ?>
      </div>

      <?php if ( ! empty( $pillar['promo'] ) ) : ?>
      <div class="svc-promo reveal">
        <i class="ph ph-arrow-right" aria-hidden="true"></i>
        <a href="<?php echo esc_url( $pillar['promo']['url'] ); ?>"><?php echo esc_html( $pillar['promo']['text'] ); ?></a>
      </div>
      <?php endif; ?>
    </div>
  </section>
  <?php endforeach; ?>

  <!-- CTA -->
  <section class="cta-section" id="cta">
    <div class="wrap">
      <div class="cta-inner">
        <div class="section-label reveal"><?php esc_html_e('Free offer','klaravex'); ?></div>
        <h2 class="section-h reveal reveal-d1"><?php esc_html_e('Not sure which service you need?','klaravex'); ?></h2>
        <p class="cta-body reveal reveal-d2"><?php esc_html_e('Start with the Free IT Assessment. A 45-minute call and written report that tells you exactly where to focus first — no obligation to engage further.','klaravex'); ?></p>

        <div class="cta-actions reveal reveal-d3">
          <a href="/free-assessment/" class="btn-primary" style="font-size:15px;padding:15px 30px;">
            <i class="ph ph-calendar-check" aria-hidden="true"></i>
            <?php esc_html_e('Get a Free IT Assessment','klaravex'); ?>
          </a>
          <a href="/managed-it-support-plans/" class="btn-ghost">
            <?php esc_html_e('View managed plans','klaravex'); ?>
            <i class="ph ph-arrow-right" aria-hidden="true"></i>
          </a>
        </div>

        <div class="cta-actions cta-actions--second reveal reveal-d4">
          <a href="https://calendly.com/klaravex/30min?hide_event_type_details=1&#038;hide_gdpr_banner=1" class="cta-calendly" target="_blank" rel="noopener">
            <i class="ph ph-calendar-plus" aria-hidden="true"></i>
            <?php esc_html_e('Book a 30-minute discovery call','klaravex'); ?>
          </a>
        </div>
      </div>
    </div>
  </section>

</main>
<?php get_footer(); ?>
