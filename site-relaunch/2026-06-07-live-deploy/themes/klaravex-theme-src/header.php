<!DOCTYPE html>
<html <?php language_attributes(); ?>>
<head>
  <meta charset="<?php bloginfo('charset'); ?>"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <link rel="profile" href="https://gmpg.org/xfn/11"/>
  <?php if (is_front_page() || is_home()) : ?>
    <meta name="description" content="Klaravex provides managed IT, security, and compliance readiness for US businesses. Always-on support resolves 89% of issues in minutes, 24/7, with senior engineers on a 2-hour SLA."/>
  <?php elseif (is_single() || is_page()) : ?>
    <meta name="description" content="<?php echo esc_attr(wp_trim_words(get_the_excerpt() ?: get_the_content(), 25, '...')); ?>"/>
  <?php endif; ?>
  <?php if (is_singular()) : ?>
    <link rel="canonical" href="<?php echo esc_url(get_permalink()); ?>"/>
  <?php else : ?>
    <link rel="canonical" href="<?php echo esc_url(home_url($_SERVER['REQUEST_URI'] ?? '/')); ?>"/>
  <?php endif; ?>
  <?php wp_head(); ?>
</head>
<body <?php body_class(); ?>>
<?php wp_body_open(); ?>

<!-- ANNOUNCE BAR -->
<div class="announce">
  <div class="wrap">
    <div class="announce-inner">
      <div class="announce-dot"></div>
      <span class="announce-badge">Always-on</span>
      <span class="announce-text">Most issues resolved in minutes by <strong>Klaravex AI</strong> — the rest reach your senior engineer within 2 hours</span>
    </div>
  </div>
</div>

<!-- NAV -->
<nav class="site-nav" role="navigation" aria-label="<?php esc_attr_e('Primary Navigation','klaravex'); ?>">
  <div class="wrap">
    <div class="nav-inner">

      <!-- Logo -->
      <a href="<?php echo esc_url(home_url('/')); ?>" class="site-logo">
        <div class="logo-mark" aria-hidden="true">K</div>
          <span>KLARAVEX</span>
      </a>

      <!-- Primary menu -->
      <?php wp_nav_menu([
          'theme_location' => 'primary',
          'menu_class'     => 'nav-menu',
          'container'      => false,
          'fallback_cb'    => function() { ?>
            <ul class="nav-menu">
              <li><a href="#services">Services</a></li>
              <li><a href="#how">How It Works</a></li>
              <li><a href="#cases">Results</a></li>
              <li><a href="#portal">Client Portal</a></li>
              <li><a href="#">About</a></li>
              <li><a href="#cta" class="nav-cta"><i class="ph ph-calendar-check"></i> Free Assessment</a></li>
            </ul>
          <?php },
      ]); ?>

      <!-- Mobile toggle -->
      <button class="nav-toggle" aria-label="<?php esc_attr_e('Toggle navigation','klaravex'); ?>" aria-expanded="false">
        <i class="ph ph-list"></i>
      </button>

    </div>
  </div>
</nav>
