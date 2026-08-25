<?php
$p_session = kvxp_mod('kvxp_price_session', '$39');
$p_monthly = kvxp_mod('kvxp_price_monthly', '$29');
$p_family  = kvxp_mod('kvxp_price_family',  '$39');
$plans = [
  [
    'name'     => __('One-time','klaravex-personal'),
    'price'    => $p_session, 'period' => __('/ session','klaravex-personal'),
    'desc'     => __('Pay when you need help. No commitment, no house call.','klaravex-personal'),
    'featured' => false,
    'features' => [ __('Remote only — no in-person visits','klaravex-personal'), __('Klaravex AI — named in the chat','klaravex-personal'), __('Written session summary','klaravex-personal'), __('Follow-up in chat or email','klaravex-personal') ],
    'btn_class'=> 'btn-outline', 'btn_text' => __('Get help now','klaravex-personal'),
  ],
  [
    'name'     => __('Monthly support','klaravex-personal'),
    'price'    => $p_monthly, 'period' => __('/ month','klaravex-personal'),
    'desc'     => __('Help whenever something comes up. Two sessions per month, priority response.','klaravex-personal'),
    'featured' => true,
    'features' => [ __('2 sessions / month','klaravex-personal'), __('Priority same-day response','klaravex-personal'), __('Unlimited quick questions','klaravex-personal'), __('Annual tech health check','klaravex-personal'), __('Cancel any time','klaravex-personal') ],
    'btn_class'=> 'btn-indigo', 'btn_text' => __('Get started','klaravex-personal'),
  ],
  [
    'name'     => __('Family plan','klaravex-personal'),
    'price'    => $p_family, 'period' => __('/ month','klaravex-personal'),
    'desc'     => __('Cover everyone in your household. Built for parents, kids, and grandparents.','klaravex-personal'),
    'featured' => false,
    'features' => [ __('Up to 4 people','klaravex-personal'), __('4 sessions / month','klaravex-personal'), __('Goes slowly with parents and grandparents','klaravex-personal'), __('Priority response','klaravex-personal'), __('Cancel any time','klaravex-personal') ],
    'btn_class'=> 'btn-outline', 'btn_text' => __('Get started','klaravex-personal'),
  ],
];
?>
<section class="pricing-section" id="pricing">
  <div class="wrap">
    <div class="eyebrow reveal"><?php esc_html_e('Simple pricing','klaravex-personal'); ?></div>
    <h2 class="section-h reveal d1"><?php esc_html_e('No surprises. No small print.','klaravex-personal'); ?></h2>
    <p class="section-sub reveal d2"><?php esc_html_e('Klaravex AI does the heavy lifting — no truck roll, no dispatch fee — so a session stays $39 instead of a house call. Every chat is named Klaravex AI so you always know who you\'re talking to.','klaravex-personal'); ?></p>
    <div class="pricing-grid">
      <?php foreach ($plans as $i => $plan) : ?>
        <div class="pricing-card<?php echo $plan['featured'] ? ' featured' : ''; ?> reveal d<?php echo $i+1; ?>">
          <?php if ($plan['featured']) : ?>
            <div class="pricing-popular"><?php esc_html_e('Most popular','klaravex-personal'); ?></div>
          <?php endif; ?>
          <div class="pricing-name"><?php echo esc_html($plan['name']); ?></div>
          <div class="pricing-price"><?php echo esc_html($plan['price']); ?> <span><?php echo esc_html($plan['period']); ?></span></div>
          <div class="pricing-desc"><?php echo esc_html($plan['desc']); ?></div>
          <ul class="pricing-features">
            <?php foreach ($plan['features'] as $feat) : ?>
              <li><i class="ph ph-check-circle" aria-hidden="true"></i><?php echo esc_html($feat); ?></li>
            <?php endforeach; ?>
          </ul>
          <a href="#cta" class="<?php echo esc_attr($plan['btn_class']); ?>" style="width:100%;justify-content:center;">
            <?php echo esc_html($plan['btn_text']); ?>
          </a>
        </div>
      <?php endforeach; ?>
    </div>
  </div>
</section>
