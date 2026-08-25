<?php
$steps = [
  [ 'num'=>'1', 'title'=>__("Tell us what's wrong",'klaravex-personal'), 'body'=>__("Open chat any hour. No ticket forms, no hold music. Use your own words — even if you're not sure what it's called.",'klaravex-personal'), 'note'=>__('A reply in seconds, day or night.','klaravex-personal'), 'note_icon'=>'ph-clock' ],
  [ 'num'=>'2', 'title'=>__('We go step by step','klaravex-personal'),   'body'=>__("You stay in control of your screen. Nothing happens without your say-so. We explain as we go, in plain English.",'klaravex-personal'), 'note'=>__('You can stop or ask “why?” at any time.','klaravex-personal'), 'note_icon'=>'ph-shield-check' ],
  [ 'num'=>'3', 'title'=>__('You leave with it written down','klaravex-personal'),   'body'=>__("A short summary of what was checked and what to do if it happens again — so you don't have to remember the tech.",'klaravex-personal'), 'note'=>__('Sent after every session.','klaravex-personal'), 'note_icon'=>'ph-notepad' ],
];
?>
<section class="how-section" id="how">
  <div class="wrap">
    <div class="eyebrow reveal"><?php esc_html_e('How it works','klaravex-personal'); ?></div>
    <h2 class="section-h reveal d1"><?php esc_html_e('Three steps to sorted.','klaravex-personal'); ?></h2>
    <p class="section-sub reveal d2"><?php esc_html_e("Patient, plain English, no rushing. Help is Klaravex AI — you'll see that name so there's no guessing.",'klaravex-personal'); ?></p>
    <div class="how-steps">
      <?php foreach ($steps as $i => $step) : ?>
        <div class="how-step reveal d<?php echo $i+1; ?>">
          <div class="how-step-num" aria-hidden="true"><?php echo esc_html($step['num']); ?></div>
          <h3><?php echo esc_html($step['title']); ?></h3>
          <p><?php echo esc_html($step['body']); ?></p>
          <div class="how-step-note">
            <i class="ph <?php echo esc_attr($step['note_icon']); ?>" aria-hidden="true"></i>
            <?php echo esc_html($step['note']); ?>
          </div>
        </div>
      <?php endforeach; ?>
    </div>
  </div>
</section>
