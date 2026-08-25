<?php
$services = [
  [ 'icon'=>'ph-wrench',         'tag'=>'popular', 'tag_label'=>__('Most popular','klaravex-personal'),  'title'=>__('IT Help &amp; Repairs','klaravex-personal'),       'desc'=>__("Slow computer, broken Wi-Fi, printer won't cooperate, emails acting up — we walk you through the fix in plain English.",'klaravex-personal'), 'price'=>kvxp_mod('kvxp_price_session','$39'), 'price_note'=>__('/ session · Remote · any hour','klaravex-personal'), 'url'=>'#cta', 'link_label'=>__('Get help now','klaravex-personal') ],
  [ 'icon'=>'ph-users',          'tag'=>'core',    'tag_label'=>__('Family favourite','klaravex-personal'),'title'=>__('Family &amp; Senior Tech','klaravex-personal'),    'desc'=>__('Video calls, smartphones, tablets, scam protection — patient, no rushing, no talking down. Built for parents and grandparents.','klaravex-personal'), 'price'=>'$65', 'price_note'=>__('/ session · Extra time, no rushing','klaravex-personal'), 'url'=>'#cta', 'link_label'=>__('Get help now','klaravex-personal') ],
  [ 'icon'=>'ph-lock-key',       'tag'=>'core',    'tag_label'=>__('Essential','klaravex-personal'),      'title'=>__('Privacy &amp; Security','klaravex-personal'),       'desc'=>__('Identity cleanup, password managers, two-factor authentication, privacy settings across all your devices. Stay safe without the complexity.','klaravex-personal'), 'price'=>'$95', 'price_note'=>__('/ session · Full privacy health check included','klaravex-personal'), 'url'=>'#cta', 'link_label'=>__('Get help now','klaravex-personal') ],
  [ 'icon'=>'ph-robot',          'tag'=>'new',     'tag_label'=>__('New','klaravex-personal'),            'title'=>__('AI Skills Coaching','klaravex-personal'),           'desc'=>__('Learn how to use ChatGPT, Claude, and AI tools in your daily life — writing, organising, researching. No tech background needed.','klaravex-personal'), 'price'=>'$85', 'price_note'=>__('/ session · Practical, hands-on coaching','klaravex-personal'), 'url'=>'#cta', 'link_label'=>__('Get help now','klaravex-personal') ],
  [ 'icon'=>'ph-magnifying-glass','tag'=>'popular','tag_label'=>__('Career','klaravex-personal'),         'title'=>__('Job-Hunt Tech Kit','klaravex-personal'),            'desc'=>__('LinkedIn optimisation, ATS-friendly CV formatting, job board setup, email organisation — everything tech for a successful job search.','klaravex-personal'), 'price'=>'$120', 'price_note'=>__('/ package · 2 sessions + written action plan','klaravex-personal'), 'url'=>'#cta', 'link_label'=>__('Get started','klaravex-personal') ],
  [ 'icon'=>'ph-storefront',     'tag'=>'new',     'tag_label'=>__('For starters','klaravex-personal'),  'title'=>__('Solo-Business Launch Kit','klaravex-personal'),     'desc'=>__("Starting out on your own? We walk you through email, website tools, payments, and cloud storage so a one-person business looks professional.",'klaravex-personal'), 'price'=>'$180', 'price_note'=>__('/ package · 3 sessions · Full setup included','klaravex-personal'), 'url'=>'#cta', 'link_label'=>__('Get started','klaravex-personal') ],
];
$tag_classes = [ 'popular'=>'tag-popular', 'new'=>'tag-new', 'core'=>'tag-core' ];
?>
<section class="services-section" id="services">
  <div class="wrap">
    <div class="eyebrow reveal"><?php esc_html_e('What we help with','klaravex-personal'); ?></div>
    <h2 class="section-h reveal d1"><?php esc_html_e('Everything tech. Explained simply.','klaravex-personal'); ?></h2>
    <p class="section-sub reveal d2"><?php esc_html_e('From a broken laptop to family privacy settings. No problem too small. Help is Klaravex AI — named clearly, so you always know.','klaravex-personal'); ?></p>
    <div class="services-grid">
      <?php foreach ($services as $i => $s) :
        $delay = 'd' . (($i % 3) + 1); ?>
        <div class="service-card reveal <?php echo $delay; ?>">
          <div class="service-tag <?php echo esc_attr($tag_classes[$s['tag']] ?? 'tag-core'); ?>">
            <?php echo esc_html($s['tag_label']); ?>
          </div>
          <div class="service-ico" aria-hidden="true"><i class="ph <?php echo esc_attr($s['icon']); ?>"></i></div>
          <h3><?php echo wp_kses_post($s['title']); ?></h3>
          <p><?php echo esc_html($s['desc']); ?></p>
          <div class="service-price"><?php echo esc_html($s['price']); ?></div>
          <div class="service-price-note"><?php echo esc_html($s['price_note']); ?></div>
          <a href="<?php echo esc_url($s['url']); ?>" class="service-link">
            <?php echo esc_html($s['link_label']); ?>
            <i class="ph ph-arrow-right" aria-hidden="true"></i>
          </a>
        </div>
      <?php endforeach; ?>
    </div>
  </div>
</section>
