<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
  <meta charset="<?php bloginfo('charset'); ?>"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>

<!-- Cross-site banner -->
<div class="xsite-banner">
  <div class="wrap">
    <div class="xsite-banner-inner">
      <span><?php esc_html_e('Looking for','klaravex-personal'); ?> <strong><?php esc_html_e('business IT support?','klaravex-personal'); ?></strong></span>
      <span class="xsite-divider">|</span>
      <a href="<?php echo esc_url(kvxp_mod('kvxp_biz_url','https://klaravex.com')); ?>" class="xsite-link">
        <?php esc_html_e('Visit klaravex.com','klaravex-personal'); ?> <i class="ph ph-arrow-right"></i>
      </a>
    </div>
  </div>
</div>

<!-- Nav -->
<nav class="site-nav" role="navigation" aria-label="<?php esc_attr_e('Primary Navigation','klaravex-personal'); ?>">
  <div class="wrap">
    <div class="nav-inner">
      <a href="<?php echo esc_url(home_url('/')); ?>" class="site-logo">
        <?php if (has_custom_logo()) : the_custom_logo();
        else : ?>
          <div class="logo-mark" aria-hidden="true">K</div>
          <span><?php bloginfo('name'); ?></span>
        <?php endif; ?>
        <span class="logo-personal"><?php esc_html_e('Personal','klaravex-personal'); ?></span>
      </a>

      <?php wp_nav_menu([
        'theme_location' => 'primary',
        'menu_class'     => 'nav-menu',
        'container'      => false,
        'fallback_cb'    => function() { ?>
          <ul class="nav-menu">
            <li><a href="#services"><?php esc_html_e('Services','klaravex-personal'); ?></a></li>
            <li><a href="#how"><?php esc_html_e('How It Works','klaravex-personal'); ?></a></li>
            <li><a href="#pricing"><?php esc_html_e('Pricing','klaravex-personal'); ?></a></li>
            <li><a href="#cta" class="nav-cta"><?php echo esc_html(kvxp_mod('kvxp_hero_cta','Get help now')); ?></a></li>
          </ul>
        <?php },
      ]); ?>

      <button class="nav-toggle" aria-label="<?php esc_attr_e('Toggle navigation','klaravex-personal'); ?>" aria-expanded="false">
        <i class="ph ph-list"></i>
      </button>
    </div>
  </div>
</nav>
