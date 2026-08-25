<?php get_header(); ?>
<main id="main" class="wrap page-content" role="main">
  <?php if (have_posts()) : while (have_posts()) : the_post(); ?>
    <article id="post-<?php the_ID(); ?>" <?php post_class(); ?>>
      <h1><?php the_title(); ?></h1>
      <div class="entry-content"><?php the_content(); ?></div>
    </article>
  <?php endwhile; else : ?>
    <p><?php esc_html_e('No content found.','klaravex-personal'); ?></p>
  <?php endif; ?>
</main>
<?php get_footer(); ?>
