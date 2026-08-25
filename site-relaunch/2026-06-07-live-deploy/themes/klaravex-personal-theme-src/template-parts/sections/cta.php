<?php
$headline = kvxp_mod('kvxp_cta_headline', "Ready to stop fighting with your tech?");
$btn      = kvxp_mod('kvxp_cta_btn',      'Get help now');
if (preg_match('/get help today|book a session|chat with klaravex ai/i', $btn)) {
  $btn = 'Get help now';
}
$email    = kvxp_mod('kvxp_cta_email',     'hello@klaravex.com');
// Wrap last word in em for gradient effect
$parts = explode(' ', $headline);
$last  = array_pop($parts);
$h_html = implode(' ', $parts) . ' <em>' . $last . '</em>';
?>
<section class="cta-section" id="cta">
  <div class="wrap">
    <div class="cta-inner">
      <h2 class="reveal"><?php echo wp_kses_post($h_html); ?></h2>
      <div class="cta-actions reveal d2">
        <a href="mailto:<?php echo esc_attr($email); ?>" class="btn-light">
          <i class="ph ph-chat-circle-text" aria-hidden="true"></i>
          <?php echo esc_html($btn); ?>
        </a>
        <a href="#pricing" class="btn-ghost-light">
          <?php esc_html_e('See pricing','klaravex-personal'); ?>
          <i class="ph ph-arrow-right" aria-hidden="true"></i>
        </a>
      </div>
    </div>
  </div>
</section>
