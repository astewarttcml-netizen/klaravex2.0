<?php
$services = [
    [
        'icon'  => 'ph-cloud',
        'title' => __('Cloud &amp; Productivity','klaravex'),
        'desc'  => __('Microsoft Azure, Microsoft 365, Intune endpoint management, Entra ID &amp; SSO, AWS, and Google Workspace — migrations, hardening, and day-to-day administration.','klaravex'),
        'url'   => '/services/cloud-productivity/',
    ],
    [
        'icon'  => 'ph-shield-check',
        'title' => __('Network &amp; Security','klaravex'),
        'desc'  => __('Firewall management (Palo Alto, FortiGate, Cisco), Zero Trust architecture, security audits, HIPAA/SOC 2 compliance, penetration testing, and 24/7 monitoring.','klaravex'),
        'url'   => '/services/network-security/',
    ],
    [
        'icon'  => 'ph-chart-line-up',
        'title' => __('Strategy &amp; Transformation','klaravex'),
        'desc'  => __('Virtual CIO, IT roadmap and budget planning, AI workflow automation, PowerShell and Python pipelines, technology governance, and board-level IT reporting.','klaravex'),
        'url'   => '/services/strategy-transformation/',
    ],
];
?>
<section class="services-section" id="services">
  <div class="wrap">
    <div class="section-label reveal"><?php esc_html_e('What we do','klaravex'); ?></div>
    <h2 class="section-h reveal reveal-d1"><?php esc_html_e("Everything your business needs. Nothing you don't.",'klaravex'); ?></h2>
    <p class="section-sub reveal reveal-d2"><?php esc_html_e('Three practice areas covering the full stack of SMB IT.','klaravex'); ?></p>

    <div class="services-grid">
      <?php foreach ( $services as $i => $s ) :
        $delay = 'd' . ($i+1); ?>
        <div class="service-card reveal reveal-<?php echo $delay; ?>">
          <div class="service-ico" aria-hidden="true"><i class="ph <?php echo esc_attr($s['icon']); ?>"></i></div>
          <h3><?php echo wp_kses_post($s['title']); ?></h3>
          <p><?php echo wp_kses_post($s['desc']); ?></p>
          <a href="<?php echo esc_url($s['url']); ?>" class="service-link">
            <?php esc_html_e('View services','klaravex'); ?>
            <i class="ph ph-arrow-right" aria-hidden="true"></i>
          </a>
        </div>
      <?php endforeach; ?>
    </div>
  </div>
</section>
