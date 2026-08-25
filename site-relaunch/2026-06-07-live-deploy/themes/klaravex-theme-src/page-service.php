<?php
/**
 * Template Name: Service Page
 * Description: Themed wrapper for child service pages under the Services index.
 *              Auto-applied by kvx_services_template() to any descendant of
 *              page 14. The page's Gutenberg content renders inside
 *              .kx-service-content and is restyled by assets/css/services.css.
 */

get_header();
?>
<main id="main" role="main" class="kx-page kx-service">
  <?php while ( have_posts() ) : the_post(); ?>
    <article id="post-<?php the_ID(); ?>" <?php post_class(); ?>>
      <div class="entry-content kx-service-content"><?php the_content(); ?></div>
    </article>
  <?php endwhile; ?>
</main>
<?php get_footer(); ?>
