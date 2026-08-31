<?php
$headline = kvx_mod('hero_headline', '89% of IT issues resolved before you finish your coffee.');
$subhead  = kvx_mod('hero_subhead',  "Klaravex AI handles Tier 1, Tier 2, monitoring, provisioning, and reporting — <strong>in minutes, 24/7, across every time zone.</strong> When a problem needs real judgment, your senior engineer takes over with full context.");
$eyebrow  = kvx_mod('hero_eyebrow',  'Managed IT &amp; Security — Always-On Support');
$cta_text = kvx_mod('hero_cta_text', 'Book a Senior Engineer — Not a Sales Call');
$cta_url  = kvx_mod('cta_btn_url',   '#cta');

// Enhanced healthcare project detection
$healthcare_project = false;
$project_indicators = [
    'healthcare',
    'medical',
    'hospital',
    'clinic',
    'pharmacy',
    'lab',
    'emergency',
    'telemedicine',
    'patient',
    'HIPAA',
    'SOC 2'
];

// Check if we're in a healthcare context
if (isset($_GET['healthcare']) || isset($_GET['medical'])) {
    $healthcare_project = true;
}

// Headline: wrap first line in .accent span automatically if it contains a %
$headline_html = preg_replace('/(\d+%)/', '<span class="accent">$1</span>', esc_html($headline));
?>
<section class="hero" id="home">
  <div class="hero-photo" role="img" aria-label="<?php esc_attr_e('Professional office environment','klaravex'); ?>"></div>
  <div class="hero-mesh" aria-hidden="true"></div>
  <div class="hero-grid" aria-hidden="true"></div>

  <div class="wrap">
    <div class="hero-body">

      <div class="hero-eyebrow reveal">
        <div class="hero-eyebrow-dot" aria-hidden="true"></div>
        <?php echo $eyebrow; ?>
      </div>

      <h1 class="reveal reveal-d1"><?php echo $headline_html; ?></h1>

      <p class="hero-sub reveal reveal-d2"><?php echo $subhead; ?></p>

      <?php if ($healthcare_project): ?>
      <div class="healthcare-hero-highlight reveal reveal-d2" style="background: rgba(99,102,241,0.1); border-left: 4px solid var(--indigo); padding: 16px; margin: 20px 0; border-radius: 0 8px 8px 0;">
        <strong><?php esc_html_e('Healthcare Security Specialization','klaravex'); ?></strong>
        <p><?php esc_html_e('Specialized support for healthcare organizations with focus on HIPAA compliance, patient data protection, and regulatory requirements.','klaravex'); ?></p>
      </div>
      <?php endif; ?>

      <div class="hero-actions reveal reveal-d3">
        <a href="<?php echo esc_url($cta_url); ?>" class="btn-primary">
          <i class="ph ph-calendar-check" aria-hidden="true"></i>
          <?php echo esc_html($cta_text); ?>
        </a>
        <a href="#how" class="btn-ghost">
          <?php esc_html_e('See how it works','klaravex'); ?>
          <i class="ph ph-arrow-right" aria-hidden="true"></i>
        </a>
      </div>

      <div class="hero-stats reveal reveal-d4" role="list" aria-label="<?php esc_attr_e('Key statistics','klaravex'); ?>">
        <?php
        $stats = [
            [ kvx_mod('stat1_num','89%'),  kvx_mod('stat1_label','Issues resolved in minutes'), 'grad' ],
            [ kvx_mod('stat2_num','24/7'), kvx_mod('stat2_label','Support coverage, every time zone'), '' ],
            [ kvx_mod('stat3_num','2hr'),  kvx_mod('stat3_label','Human senior engineer SLA'), '' ],
            [ kvx_mod('stat4_num','$0'),   kvx_mod('stat4_label','Vendor commissions, ever'), '' ],
        ];
        foreach ( $stats as [$num,$label,$cls] ) : ?>
          <div class="hero-stat" role="listitem">
            <div class="hero-stat-num <?php echo esc_attr($cls); ?>"><?php echo esc_html($num); ?></div>
            <div class="hero-stat-label"><?php echo esc_html($label); ?></div>
          </div>
        <?php endforeach; ?>
      </div>

    </div>
  </div>
</section>
