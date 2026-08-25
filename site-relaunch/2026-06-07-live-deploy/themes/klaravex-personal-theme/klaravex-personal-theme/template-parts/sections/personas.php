<?php
$personas = [
  [ 'emoji'=>'👩‍💼', 'title'=>__('Busy professionals','klaravex-personal'), 'desc'=>__('Too little time to deal with tech issues. We fix it fast so you can get back to work.','klaravex-personal') ],
  [ 'emoji'=>'👴',   'title'=>__('Parents &amp; seniors','klaravex-personal'), 'desc'=>__('Patient, kind, and always in plain English. No judgment. No rushing.','klaravex-personal') ],
  [ 'emoji'=>'🎓',  'title'=>__('Students &amp; job-seekers','klaravex-personal'), 'desc'=>__('LinkedIn, CVs, job boards, and interview tech — sorted before you apply.','klaravex-personal') ],
  [ 'emoji'=>'🛍️', 'title'=>__('Solo entrepreneurs','klaravex-personal'), 'desc'=>__('Get your business set up properly without the enterprise price tag.','klaravex-personal') ],
];
?>
<section class="personas-section" id="who">
  <div class="wrap">
    <div class="eyebrow reveal"><?php esc_html_e('Who we help','klaravex-personal'); ?></div>
    <h2 class="section-h reveal d1"><?php esc_html_e("If you use tech, we can help.",'klaravex-personal'); ?></h2>
    <p class="section-sub reveal d2"><?php esc_html_e("You don't need to be \"a tech person.\" You just need something to work.",'klaravex-personal'); ?></p>
    <div class="personas-grid">
      <?php foreach ($personas as $i => $p) : ?>
        <div class="persona-card reveal d<?php echo $i+1; ?>">
          <span class="persona-emoji" aria-hidden="true"><?php echo $p['emoji']; ?></span>
          <h3><?php echo wp_kses_post($p['title']); ?></h3>
          <p><?php echo esc_html($p['desc']); ?></p>
        </div>
      <?php endforeach; ?>
    </div>
  </div>
</section>
