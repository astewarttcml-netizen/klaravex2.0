<?php get_header(); ?>
<main id="main" class="wrap" role="main" style="padding-top:80px; padding-bottom:80px;">
  <?php if ( have_posts() ) :
    while ( have_posts() ) : the_post(); ?>
      <article id="post-<?php the_ID(); ?>" <?php post_class(); ?>>
        <h1 style="font-family:var(--font-display);font-size:clamp(28px,4vw,48px);font-weight:800;letter-spacing:-0.03em;margin-bottom:24px;"><?php the_title(); ?></h1>
        <div class="entry-content" style="color:var(--dim);line-height:1.7;max-width:700px;"><?php the_content(); ?></div>
      </article>
    <?php endwhile;
  else : ?>
    <p style="color:var(--dim);"><?php esc_html_e('No content found.','klaravex'); ?></p>
  <?php endif; ?>
</main>
<?php get_footer(); ?>
