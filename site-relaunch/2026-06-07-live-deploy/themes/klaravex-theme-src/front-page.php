<?php get_header(); ?>

<main id="main" role="main">

  <?php
  // Trust strip industries
  $industries = [
    __('Law Firms','klaravex'), __('Medical Practices','klaravex'),
    __('Accounting Firms','klaravex'), __('Financial Advisory','klaravex'),
    __('Architecture Firms','klaravex'), __('Real Estate Brokerages','klaravex'),
  ];
  ?>

  <?php get_template_part('template-parts/sections/hero'); ?>

  <!-- Trust strip -->
  <div class="trust">
    <div class="wrap">
      <div class="trust-inner">
        <span class="trust-label"><?php esc_html_e('Built for','klaravex'); ?></span>
        <div class="trust-items">
          <?php foreach ( $industries as $ind ) : ?>
            <span class="trust-item"><?php echo esc_html($ind); ?></span>
          <?php endforeach; ?>
        </div>
      </div>
    </div>
  </div>

  <?php get_template_part('template-parts/sections/how-it-works'); ?>
  <?php get_template_part('template-parts/sections/ai-capabilities'); ?>
  <?php get_template_part('template-parts/sections/case-studies'); ?>
  <?php get_template_part('template-parts/sections/services'); ?>
  <?php get_template_part('template-parts/sections/portal'); ?>
  <?php get_template_part('template-parts/sections/cta'); ?>

</main>

<?php get_footer(); ?>
