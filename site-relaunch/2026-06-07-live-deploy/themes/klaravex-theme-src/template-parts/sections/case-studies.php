<?php
$cases = [
    [
        'industry' => kvx_mod('case1_industry', 'Professional services'),
        'stat'     => kvx_mod('case1_stat',     '78%'),
        'label'    => kvx_mod('case1_label',    'Microsoft Secure Score'),
        'desc'     => kvx_mod('case1_desc',     '<strong>An engagement I led: 32% to 78% in under 60 days.</strong> M365 hardening, MFA enforcement, Conditional Access, email security. Now cyber-insurance ready.'),
        'viz'      => 'progress',
        'viz_from' => 'Before 32%',
        'viz_to'   => 'After 78%',
        'bar_width'=> '78',
    ],
    [
        'industry' => kvx_mod('case2_industry', 'Legal services'),
        'stat'     => kvx_mod('case2_stat',     '1 wk'),
        'label'    => kvx_mod('case2_label',    'Zero-loss M365 migration'),
        'desc'     => kvx_mod('case2_desc',     '<strong>An engagement I led: 28 users migrated in one week. Zero data loss, zero downtime.</strong> Complete on-premises Exchange cutover with no billable hours lost.'),
        'viz'      => 'timeline',
        'viz_from' => 'Day 1 — planning',
        'viz_to'   => 'Day 7 — live',
    ],
    [
        'industry' => kvx_mod('case3_industry', 'Multi-site SMB'),
        'stat'     => kvx_mod('case3_stat',     '4 hrs'),
        'label'    => kvx_mod('case3_label',    'Network infrastructure cutover'),
        'desc'     => kvx_mod('case3_desc',     '<strong>An engagement I led: full firewall and switching replacement over a weekend.</strong> Back online Monday morning — staff noticed faster WiFi and nothing else.'),
        'viz'      => 'timeline',
        'viz_from' => 'Friday shutdown',
        'viz_to'   => 'Monday — zero impact',
    ],
];
?>
<section class="cases-section" id="cases">
  <div class="wrap">
    <div class="section-label reveal"><?php esc_html_e('Engagements I led','klaravex'); ?></div>
    <h2 class="section-h reveal reveal-d1"><?php esc_html_e('What good IT work actually looks like.','klaravex'); ?></h2>
    <p class="section-sub reveal reveal-d2"><?php esc_html_e('Results from work I performed as a senior engineer. Client names withheld. These were not Klaravex contracts. No vendor commissions meant no vendor agenda.','klaravex'); ?></p>

    <div class="cases-grid">
      <?php foreach ( $cases as $i => $c ) :
        $delay = 'd' . ($i+1); ?>
        <article class="case-card g-border reveal reveal-<?php echo $delay; ?>">
          <div class="case-industry"><?php echo esc_html($c['industry']); ?></div>
          <div class="case-stat" aria-label="<?php echo esc_attr($c['stat']); ?>"><?php echo esc_html($c['stat']); ?></div>
          <div class="case-stat-label"><?php echo esc_html($c['label']); ?></div>
          <div class="case-desc"><?php echo wp_kses_post($c['desc']); ?></div>
          <div class="case-viz">
            <?php if ( $c['viz'] === 'progress' ) : ?>
              <div class="prog-labels">
                <span><?php echo esc_html($c['viz_from']); ?></span>
                <span><?php echo esc_html($c['viz_to']); ?></span>
              </div>
              <div class="prog-track">
                <div class="prog-fill" style="width:<?php echo esc_attr($c['bar_width']); ?>%"></div>
              </div>
            <?php else : ?>
              <div class="tl-row" aria-hidden="true">
                <div class="tl-dot"></div>
                <div class="tl-line"></div>
                <div class="tl-dot"></div>
              </div>
              <div class="tl-labels">
                <span><?php echo esc_html($c['viz_from']); ?></span>
                <span><?php echo esc_html($c['viz_to']); ?></span>
              </div>
            <?php endif; ?>
          </div>
        </article>
      <?php endforeach; ?>
    </div>
  </div>
</section>
