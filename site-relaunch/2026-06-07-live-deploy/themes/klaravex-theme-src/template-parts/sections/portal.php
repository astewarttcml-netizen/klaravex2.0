<?php
$headline   = kvx_mod('portal_headline', 'Your IT, visible. Your team, covered.');
$sub        = kvx_mod('portal_sub',      "Every client gets a private portal. See what's happening with your systems in real time, talk to AI instantly, and always know who your engineer is.");
$portal_url = kvx_mod('portal_url',      'portal.klaravex.com');
$features   = [
    [ 'ph-activity',           __('Live systems status','klaravex'),   __('See the health of every service, device, and environment at a glance — updated in real time, 24/7.','klaravex') ],
    [ 'ph-robot',              __('AI chat — always on','klaravex'),   __('Talk to your AI agent instantly. It already knows your environment. No re-explaining, no ticket forms.','klaravex') ],
    [ 'ph-user-gear',          __('Your dedicated engineer','klaravex'), __('See who your engineer is, when they\'re available, and everything they\'ve done for your account.','klaravex') ],
    [ 'ph-file-text',          __('Reports &amp; documentation','klaravex'), __('Every session, incident, and resolution — documented automatically and delivered to your portal.','klaravex') ],
];
?>
<section class="portal-section" id="portal">
  <div class="wrap">
    <div class="portal-layout">

      <!-- Copy -->
      <div>
        <div class="section-label reveal"><?php esc_html_e('Client portal','klaravex'); ?></div>
        <h2 class="section-h reveal reveal-d1"><?php echo wp_kses_post($headline); ?></h2>
        <p class="section-sub reveal reveal-d2"><?php echo esc_html($sub); ?></p>

        <div class="portal-features reveal reveal-d2">
          <?php foreach ( $features as [$icon,$title,$desc] ) : ?>
            <div class="portal-feature">
              <div class="portal-feature-ico"><i class="ph <?php echo esc_attr($icon); ?>" aria-hidden="true"></i></div>
              <div>
                <div class="portal-feature-title"><?php echo wp_kses_post($title); ?></div>
                <div class="portal-feature-desc"><?php echo esc_html($desc); ?></div>
              </div>
            </div>
          <?php endforeach; ?>
        </div>

        <div class="reveal reveal-d3">
          <a href="#cta" class="early-access-badge">
            <i class="ph ph-sparkle" aria-hidden="true"></i>
            <?php esc_html_e('Request Early Portal Access','klaravex'); ?>
            <i class="ph ph-arrow-right" aria-hidden="true"></i>
          </a>
          <div class="portal-access-note"><?php esc_html_e('Included with all managed plans · No extra cost','klaravex'); ?></div>
        </div>
      </div>

      <!-- Mock dashboard -->
      <div class="reveal reveal-d2" aria-label="<?php esc_attr_e('Client portal preview','klaravex'); ?>" role="img">
        <div class="portal-mock">
          <div class="mock-chrome" aria-hidden="true">
            <div class="mock-dots">
              <div class="mock-dot mock-dot-r"></div>
              <div class="mock-dot mock-dot-y"></div>
              <div class="mock-dot mock-dot-g"></div>
            </div>
            <div class="mock-url"><?php echo esc_html($portal_url); ?></div>
          </div>
          <div class="mock-app" aria-hidden="true">
            <div class="mock-sidebar">
              <div class="mock-sidebar-logo">
                <div class="mock-sidebar-k">K</div>
                <span class="mock-sidebar-brand">Klaravex</span>
              </div>
              <div class="mock-nav-section">Main</div>
              <div class="mock-nav-item active"><i class="ph ph-squares-four"></i> Dashboard</div>
              <div class="mock-nav-item"><i class="ph ph-chat-circle-text"></i> AI Support</div>
              <div class="mock-nav-item"><i class="ph ph-ticket"></i> Tickets</div>
              <div class="mock-nav-item"><i class="ph ph-activity"></i> Systems</div>
              <div class="mock-nav-section">Account</div>
              <div class="mock-nav-item"><i class="ph ph-file-text"></i> Reports</div>
              <div class="mock-nav-item"><i class="ph ph-user-gear"></i> My Engineer</div>
              <div class="mock-nav-item"><i class="ph ph-gear"></i> Settings</div>
            </div>
            <div class="mock-main">
              <div class="mock-topbar">
                <div class="mock-greeting">Good morning, Alex <span>— everything looks good</span></div>
                <div class="mock-engineer-pill">
                  <div class="mock-avatar">AI</div>
                  <div class="mock-online-dot"></div>
                  Atlas — online
                </div>
              </div>
              <div class="mock-status-row">
                <div class="mock-stat-card"><div class="mock-stat-label">Systems</div><div class="mock-stat-val green">All OK</div><div class="mock-stat-sub">14 / 14 healthy</div></div>
                <div class="mock-stat-card"><div class="mock-stat-label">Resolved this month</div><div class="mock-stat-val ind">47</div><div class="mock-stat-sub">89% by AI</div></div>
                <div class="mock-stat-card"><div class="mock-stat-label">Avg response</div><div class="mock-stat-val" style="color:var(--white)">0:42</div><div class="mock-stat-sub">minutes</div></div>
                <div class="mock-stat-card"><div class="mock-stat-label">Secure score</div><div class="mock-stat-val ind">81%</div><div class="mock-stat-sub">↑ 4pts this week</div></div>
              </div>
              <div class="mock-bottom-grid">
                <div class="mock-panel">
                  <div class="mock-panel-head">Recent activity <span class="mock-panel-head-link">View all →</span></div>
                  <div class="mock-ticket"><span class="mock-ticket-badge badge-ai">AI</span><span class="mock-ticket-badge badge-ok">Resolved</span><span class="mock-ticket-title">VPN timeout — Sarah's laptop</span><span class="mock-ticket-time">2m ago</span></div>
                  <div class="mock-ticket"><span class="mock-ticket-badge badge-ai">AI</span><span class="mock-ticket-badge badge-ok">Resolved</span><span class="mock-ticket-title">M365 MFA re-enroll — 3 users</span><span class="mock-ticket-time">1h ago</span></div>
                  <div class="mock-ticket"><span class="mock-ticket-badge badge-eng">Engineer</span><span class="mock-ticket-badge badge-ok">Done</span><span class="mock-ticket-title">Firewall rule review</span><span class="mock-ticket-time">Yesterday</span></div>
                  <div class="mock-ticket"><span class="mock-ticket-badge badge-ai">AI</span><span class="mock-ticket-badge badge-ok">Resolved</span><span class="mock-ticket-title">New hire provisioning — Tom K.</span><span class="mock-ticket-time">2d ago</span></div>
                </div>
                <div class="mock-panel mock-engineer-card">
                  <div class="mock-panel-head">Your AI strategy engineer</div>
                  <div class="mock-eng-profile">
                    <div class="mock-eng-avatar">AI</div>
                    <div>
                      <div class="mock-eng-name">Atlas — AI Strategy Engineer</div>
                      <div class="mock-eng-title">Klaravex AI · Every recommendation reviewed by a human</div>
                      <div class="mock-eng-status"><div class="mock-online-dot"></div> Always on</div>
                    </div>
                  </div>
                  <div class="mock-eng-stat-row">
                    <div class="mock-eng-stat"><div class="mock-eng-stat-val">24/7</div><div class="mock-eng-stat-label">Monitoring your account</div></div>
                    <div class="mock-eng-stat"><div class="mock-eng-stat-val">98%</div><div class="mock-eng-stat-label">Satisfaction score</div></div>
                  </div>
                  <div class="mock-chat-teaser"><i class="ph ph-chat-circle-text"></i> Ask Atlas or reach a human engineer →</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

    </div>
  </div>
</section>
