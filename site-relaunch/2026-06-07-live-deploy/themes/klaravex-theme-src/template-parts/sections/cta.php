<?php
$headline = kvx_mod('cta_headline',      'Book a Senior Engineer — Not a Sales Call.');
$body     = kvx_mod('cta_body',          '45 minutes. Written report. No obligation. We review your infrastructure, cloud environment, security posture, and backup coverage — and tell you honestly what\'s working and what isn\'t.');
$btn_text = kvx_mod('cta_btn_text',      'Request Your Free Assessment');
$btn_url  = kvx_mod('cta_btn_url',       '#');
$pricing  = kvx_mod('cta_pricing_anchor','$X per user/month');
?>
<section class="cta-section" id="cta">
  <div class="wrap">
    <div class="cta-inner">
      <div class="section-label reveal"><?php esc_html_e('Free offer','klaravex'); ?></div>
      <h2 class="section-h reveal reveal-d1"><?php echo wp_kses_post($headline); ?></h2>
      <p class="cta-body reveal reveal-d2"><?php echo esc_html($body); ?></p>

      <div class="guarantee reveal reveal-d2">
        <i class="ph ph-seal-check" aria-hidden="true"></i>
        <?php esc_html_e("If we miss our 2-hour response commitment, you receive a service credit — no questions asked.",'klaravex'); ?>
      </div>

      <div class="cta-points reveal reveal-d3">
        <div class="cta-point">
          <div class="cta-point-ico"><i class="ph ph-robot" aria-hidden="true"></i></div>
          <span><?php printf( wp_kses_post( __('<strong>89%% of issues resolved by AI</strong> — instantly, any hour. The other 11%% go straight to a senior engineer with full context already documented.','klaravex') ) ); ?></span>
        </div>
        <div class="cta-point">
          <div class="cta-point-ico"><i class="ph ph-certificate" aria-hidden="true"></i></div>
          <span><?php printf( wp_kses_post( __('Engineers average <strong>12 years of enterprise experience</strong> — PCNSE, AZ-500, CCNP, CEH certified.','klaravex') ) ); ?></span>
        </div>
        <div class="cta-point">
          <div class="cta-point-ico"><i class="ph ph-tag" aria-hidden="true"></i></div>
          <span><?php printf( wp_kses_post( __('<strong>AI is always labeled.</strong> You always know whether you\'re talking to a machine or a person.','klaravex') ) ); ?></span>
        </div>
        <div class="cta-point">
          <div class="cta-point-ico"><i class="ph ph-currency-dollar" aria-hidden="true"></i></div>
          <span><?php printf( wp_kses_post( __('Flat monthly fee from <strong>%s</strong> — no per-ticket billing, no surprise invoices.','klaravex') ), esc_html($pricing) ); ?></span>
        </div>
      </div>

      <div class="cta-actions reveal reveal-d4">
        <a href="<?php echo esc_url($btn_url); ?>" class="btn-primary" style="font-size:15px;padding:15px 30px;">
          <i class="ph ph-calendar-check" aria-hidden="true"></i>
          <?php echo esc_html($btn_text); ?>
        </a>
        <span class="cta-fine"><?php esc_html_e('US businesses only · Remote delivery · Response within one business day','klaravex'); ?></span>
      </div>
    </div>
  </div>
</section>
