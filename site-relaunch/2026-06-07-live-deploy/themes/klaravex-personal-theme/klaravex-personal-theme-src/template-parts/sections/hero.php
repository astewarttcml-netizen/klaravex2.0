<?php
$badge    = kvxp_mod('kvxp_hero_badge',    'Plain English. Any hour.');
$headline = kvxp_mod('kvxp_hero_headline', 'Tech that <em>actually</em> works for you.');
$sub      = kvxp_mod('kvxp_hero_sub',      "No jargon. No house call. Klaravex AI does the heavy lifting so a session stays $39 — you'll see that name so you always know who you're talking to.");
$cta      = kvxp_mod('kvxp_hero_cta',      'Get help now');
if (preg_match('/real expert|real people|real person/i', $badge)) {
  $badge = 'Plain English. Any hour.';
}
if (preg_match("/we've got you|we’ve got you|never as a person|in-person|real person/i", $sub)) {
  $sub = "No jargon. No house call. Klaravex AI does the heavy lifting so a session stays $39 — you'll see that name so you always know who you're talking to.";
}
if (preg_match('/get help today|book a session|chat with klaravex ai/i', $cta)) {
  $cta = 'Get help now';
}
?>
<section class="hero" id="home">
  <div class="hero-photo" role="img" aria-label="<?php esc_attr_e('Friendly tech help','klaravex-personal'); ?>"></div>
  <div class="hero-orb-1" aria-hidden="true"></div>
  <div class="hero-orb-2" aria-hidden="true"></div>
  <div class="wrap">
    <div class="hero-body">
      <?php if ($badge) : ?>
        <div class="hero-badge reveal">
          <i class="ph ph-sparkle" aria-hidden="true"></i>
          <?php echo esc_html($badge); ?>
        </div>
      <?php endif; ?>
      <h1 class="reveal d1"><?php echo wp_kses_post($headline); ?></h1>
      <p class="hero-sub reveal d2"><?php echo esc_html($sub); ?></p>
      <div class="hero-actions reveal d3">
        <a href="#cta" class="btn-indigo"><i class="ph ph-chat-circle-text" aria-hidden="true"></i><?php echo esc_html($cta); ?></a>
        <a href="#services" class="btn-outline"><?php esc_html_e('See what we help with','klaravex-personal'); ?> <i class="ph ph-arrow-right" aria-hidden="true"></i></a>
      </div>
    </div>
  </div>
</section>
