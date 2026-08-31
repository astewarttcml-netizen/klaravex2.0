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
      <?php
      // Check if this is a healthcare project and add appropriate styling
      $is_healthcare_project = kvx_is_healthcare_project();
      if ($is_healthcare_project) {
          echo '<div class="healthcare-project-wrapper">';
      }
      ?>
      <div class="entry-content kx-service-content"><?php the_content(); ?></div>
      <?php
      if ($is_healthcare_project) {
          echo '</div>';
      }
      ?>
    </article>
  <?php endwhile; ?>
</main>
<?php get_footer(); ?>
