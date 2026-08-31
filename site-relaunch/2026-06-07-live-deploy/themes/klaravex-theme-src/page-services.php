<?php
/**
 * Template Name: Services Index
 * Description: Main services page template that loads when the Services index page (ID 14) is accessed.
 *              This page uses the standard theme layout and renders content in .kx-service-content.
 */

get_header();
?>
<main id="main" role="main" class="kx-page kx-services">
  <?php while ( have_posts() ) : the_post(); ?>
    <article id="post-<?php the_ID(); ?>" <?php post_class(); ?>>
      <div class="entry-content kx-service-content"><?php the_content(); ?></div>
    </article>
  <?php endwhile; ?>
</main>
<?php get_footer(); ?>