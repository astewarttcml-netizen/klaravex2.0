<?php
$ai_items = [
    [ 'ph-ticket',       __('Tier 1 &amp; Tier 2 support','klaravex'),            __('Password resets, software installs, connectivity, account lockouts, application faults — resolved without escalation.','klaravex') ],
    [ 'ph-monitor-play', __('24/7 monitoring &amp; auto-remediation','klaravex'), __('Watches your systems continuously. Patches common issues and alerts before users notice anything is wrong.','klaravex') ],
    [ 'ph-user-plus',    __('Onboarding &amp; provisioning','klaravex'),          __('New hire setup, device enrollment, M365 creation, access provisioning, Intune/Autopilot — executed automatically.','klaravex') ],
    [ 'ph-file-text',    __('Reporting &amp; documentation','klaravex'),          __('Session summaries, incident reports, compliance docs, and audit trails — generated and delivered after every interaction.','klaravex') ],
];
$human_items = [
    [ 'ph-warning-octagon', __('Security incidents &amp; breaches','klaravex'),    __('Active intrusions, ransomware response, forensic investigation — cases where stakes are too high for automation alone.','klaravex') ],
    [ 'ph-blueprint',       __('Architecture &amp; strategy','klaravex'),          __('Cloud migrations, network redesigns, Zero Trust implementation, vCIO roadmap sessions — decisions that require judgment.','klaravex') ],
    [ 'ph-handshake',       __('Vendor negotiations &amp; procurement','klaravex'),__('Evaluating vendors, reviewing contracts, recommending solutions — with zero vendor commission conflict of interest.','klaravex') ],
    [ 'ph-scales',          __('Compliance &amp; audit support','klaravex'),       __('HIPAA, SOC 2, GDPR, cyber insurance readiness — guidance a certified engineer can sign their name to.','klaravex') ],
];
?>
<section class="ai-section" id="ai">
  <div class="wrap">
    <div class="section-label reveal"><?php esc_html_e('What the AI handles','klaravex'); ?></div>
    <h2 class="section-h reveal reveal-d1"><?php esc_html_e('The full operational layer — automated.','klaravex'); ?></h2>
    <p class="section-sub reveal reveal-d2"><?php esc_html_e("Our proprietary hybrid system isn't a chatbot. It runs your IT operations.",'klaravex'); ?></p>

    <div class="ai-layout">
      <!-- AI column -->
      <div class="reveal reveal-d2">
        <div class="ai-col-head ai">
          <i class="ph ph-robot" aria-hidden="true"></i>
          <?php esc_html_e('Handled by AI — 89%','klaravex'); ?>
        </div>
        <div class="ai-items">
          <?php foreach ( $ai_items as [$icon,$title,$desc] ) : ?>
            <div class="ai-item g-border">
              <div class="ai-item-icon"><i class="ph <?php echo esc_attr($icon); ?>" aria-hidden="true"></i></div>
              <div>
                <div class="ai-item-title"><?php echo wp_kses_post($title); ?></div>
                <div class="ai-item-desc"><?php echo esc_html($desc); ?></div>
              </div>
            </div>
          <?php endforeach; ?>
        </div>

        <div class="resolution-meter" id="meter">
          <div class="meter-header">
            <div class="meter-ai-pct">89%</div>
            <div class="meter-human-pct"><?php esc_html_e('11% human','klaravex'); ?></div>
          </div>
          <div class="meter-track">
            <div class="meter-fill" id="meter-fill"></div>
          </div>
          <div class="meter-labels">
            <span><?php esc_html_e('AI resolution','klaravex'); ?></span>
            <span><?php esc_html_e('Human escalation','klaravex'); ?></span>
          </div>
        </div>

        <span class="proprietary-tag">
          <i class="ph ph-lock-key" aria-hidden="true"></i>
          <?php esc_html_e('Proprietary hybrid system — not an off-the-shelf chatbot','klaravex'); ?>
        </span>
      </div>

      <!-- Human column -->
      <div class="reveal reveal-d3">
        <div class="ai-col-head human">
          <i class="ph ph-user-gear" aria-hidden="true"></i>
          <?php esc_html_e('Handled by humans — 11%','klaravex'); ?>
        </div>
        <div class="ai-items">
          <?php foreach ( $human_items as [$icon,$title,$desc] ) : ?>
            <div class="ai-item">
              <div class="ai-item-icon"><i class="ph <?php echo esc_attr($icon); ?>" aria-hidden="true"></i></div>
              <div>
                <div class="ai-item-title"><?php echo wp_kses_post($title); ?></div>
                <div class="ai-item-desc"><?php echo esc_html($desc); ?></div>
              </div>
            </div>
          <?php endforeach; ?>
        </div>
      </div>
    </div>
  </div>
</section>
