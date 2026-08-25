<footer class="site-footer" role="contentinfo">
  <div class="wrap">
    <div class="footer-top">
      <div>
        <a href="<?php echo esc_url(home_url('/')); ?>" class="site-logo">
          <div class="logo-mark" aria-hidden="true">K</div>
          <span><?php bloginfo('name'); ?></span>
          <span class="logo-personal"><?php esc_html_e('Personal','klaravex-personal'); ?></span>
        </a>
        <p class="footer-desc"><?php esc_html_e('Plain English, any hour, remote only. Klaravex AI does the heavy lifting so we can pass the savings on to you.','klaravex-personal'); ?></p>
      </div>
      <div class="footer-col">
        <h4><?php esc_html_e('Services','klaravex-personal'); ?></h4>
        <ul>
          <li><a href="/it-help-repairs/"><?php esc_html_e('IT Help &amp; Repairs','klaravex-personal'); ?></a></li>
          <li><a href="/family-senior-tech/"><?php esc_html_e('Family &amp; Senior Tech','klaravex-personal'); ?></a></li>
          <li><a href="/privacy-security/"><?php esc_html_e('Privacy &amp; Security','klaravex-personal'); ?></a></li>
          <li><a href="/ai-skills-coaching/"><?php esc_html_e('AI Skills Coaching','klaravex-personal'); ?></a></li>
          <li><a href="/job-hunt-tech-kit/"><?php esc_html_e('Job-Hunt Tech Kit','klaravex-personal'); ?></a></li>
          <li><a href="/solo-business-launch-kit/"><?php esc_html_e('Solo-Business Launch Kit','klaravex-personal'); ?></a></li>
        </ul>
      </div>
      <div class="footer-col">
        <h4><?php esc_html_e('Help','klaravex-personal'); ?></h4>
        <ul>
          <li><a href="#cta"><?php esc_html_e('Get help now','klaravex-personal'); ?></a></li>
          <li><a href="#pricing"><?php esc_html_e('Pricing','klaravex-personal'); ?></a></li>
          <li><a href="/faq/"><?php esc_html_e('FAQ','klaravex-personal'); ?></a></li>
          <li><a href="/contact/"><?php esc_html_e('Contact','klaravex-personal'); ?></a></li>
        </ul>
      </div>
    </div>
    <div class="footer-bottom">
      <p><?php echo kvxp_mod('kvxp_footer_legal', '&copy; ' . date('Y') . ' Klaravex LLC &mdash; Personal IT Help'); ?></p>
      <a href="<?php echo esc_url(kvxp_mod('kvxp_biz_url','https://klaravex.com')); ?>" class="footer-biz-link">
        <i class="ph ph-buildings" aria-hidden="true"></i>
        <?php esc_html_e('Business IT Support → klaravex.com','klaravex-personal'); ?>
      </a>
    </div>
  </div>
</footer>
<?php wp_footer(); ?>
</body>
</html>
