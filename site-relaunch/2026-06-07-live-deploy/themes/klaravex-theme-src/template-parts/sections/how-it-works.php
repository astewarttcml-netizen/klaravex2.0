<?php
$steps = [
    [
        'icon'  => 'ph-robot',
        'title' => __('AI takes the call — instantly','klaravex'),
        'body'  => __('Any hour, any day, any time zone. The AI picks up immediately, diagnoses the issue, and starts working on a fix. No queue, no hold music, no ticket number to wait on.','klaravex'),
        'note'  => __('Tier 1 &amp; Tier 2, monitoring alerts, provisioning requests — all handled without a human in the loop.','klaravex'),
        'note_icon' => 'ph-lightning',
    ],
    [
        'icon'  => 'ph-arrows-split',
        'title' => __('89% resolved. 11% escalated.','klaravex'),
        'body'  => __('Most issues are fixed before you notice them. The 11% that need real judgment — complex failures, security incidents, architecture decisions — route to your engineer with full context already documented.','klaravex'),
        'note'  => __('You always know whether you\'re talking to AI or a person. Always labeled. No ambiguity, ever.','klaravex'),
        'note_icon' => 'ph-tag',
    ],
    [
        'icon'  => 'ph-user-gear',
        'title' => __('Your dedicated senior engineer','klaravex'),
        'body'  => __('One certified engineer owns your account end to end. When they take a case, they already have the full picture. Every session ends with a written summary sent directly to you.','klaravex'),
        'note'  => __('PCNSE, AZ-500, CCNP, CEH certified. 12+ years enterprise experience. No juniors, ever.','klaravex'),
        'note_icon' => 'ph-certificate',
    ],
];
?>
<section class="how-section" id="how">
  <div class="wrap">
    <div class="section-label reveal"><?php esc_html_e('How it works','klaravex'); ?></div>
    <h2 class="section-h reveal reveal-d1"><?php esc_html_e('AI first. Humans when it matters.','klaravex'); ?></h2>
    <p class="section-sub reveal reveal-d2"><?php esc_html_e("Most IT companies route every ticket through a human queue. We don't. Here's what actually happens when something breaks.",'klaravex'); ?></p>

    <div class="steps-grid reveal reveal-d3">
      <?php foreach ( $steps as $i => $step ) : ?>
        <div class="step">
          <span class="step-num" aria-hidden="true">0<?php echo $i+1; ?></span>
          <div class="step-icon-wrap" aria-hidden="true">
            <i class="ph <?php echo esc_attr($step['icon']); ?>"></i>
          </div>
          <h3><?php echo esc_html($step['title']); ?></h3>
          <p><?php echo esc_html($step['body']); ?></p>
          <div class="step-note">
            <i class="ph <?php echo esc_attr($step['note_icon']); ?>" aria-hidden="true"></i>
            <?php echo wp_kses_post($step['note']); ?>
          </div>
        </div>
      <?php endforeach; ?>
    </div>
  </div>
</section>
