<?php
/**
 * Klaravex Personal Theme — functions.php
 */
defined('ABSPATH') || exit;

define('KVXP_VERSION', '1.2.3');
define('KVXP_DIR', get_template_directory());
define('KVXP_URI', get_template_directory_uri());

/* ── SETUP ── */
function kvxp_setup() {
    add_theme_support('title-tag');
    add_theme_support('post-thumbnails');
    add_theme_support('custom-logo', [ 'height' => 60, 'width' => 200, 'flex-height' => true, 'flex-width' => true ]);
    add_theme_support('html5', ['search-form','comment-form','comment-list','gallery','caption','script','style']);
    add_theme_support('responsive-embeds');
    add_image_size('kvxp-hero',     1920, 1080, true);
    add_image_size('kvxp-card',      800,  600, true);
    register_nav_menus([
        'primary' => __('Primary Navigation', 'klaravex-personal'),
        'footer'  => __('Footer Navigation',  'klaravex-personal'),
    ]);
}
add_action('after_setup_theme', 'kvxp_setup');

/* ── ENQUEUE ── */
function kvxp_assets() {
    wp_enqueue_style('kvxp-fonts',
        'https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&display=swap',
        [], null);
    wp_enqueue_script('phosphor-icons',
        'https://unpkg.com/@phosphor-icons/web@2.1.1/src/index.js',
        [], '2.1.1', true);
    wp_enqueue_style('kvxp-main',   KVXP_URI.'/assets/css/main.css', ['kvxp-fonts'], KVXP_VERSION);
    wp_enqueue_script('kvxp-main',  KVXP_URI.'/assets/js/main.js',  [], KVXP_VERSION, true);
    wp_enqueue_script('klara-chat', KVXP_URI.'/assets/js/klara-personal-widget.js', [], KVXP_VERSION, true);
    wp_localize_script('kvxp-main', 'kvxpData', [
        'ajaxUrl' => admin_url('admin-ajax.php'),
        'nonce'   => wp_create_nonce('kvxp_nonce'),
    ]);
}
add_action('wp_enqueue_scripts', 'kvxp_assets');

/* ── CUSTOMIZER ── */
function kvxp_customizer($wp_customize) {
    $wp_customize->add_panel('kvxp_panel', [ 'title' => __('Klaravex Personal', 'klaravex-personal'), 'priority' => 30 ]);

    /* Hero */
    $wp_customize->add_section('kvxp_hero', [ 'title' => __('Hero', 'klaravex-personal'), 'panel' => 'kvxp_panel' ]);
    kvxp_text($wp_customize, 'kvxp_hero', 'kvxp_hero_badge',    __('Badge text',   'klaravex-personal'), 'Plain English. Any hour.');
    kvxp_text($wp_customize, 'kvxp_hero', 'kvxp_hero_headline', __('Headline',      'klaravex-personal'), 'Tech that <em>actually</em> works for you.');
    kvxp_text($wp_customize, 'kvxp_hero', 'kvxp_hero_sub',      __('Subheadline',   'klaravex-personal'), "No jargon. No house call. Klaravex AI does the heavy lifting so a session stays $39 — you'll see that name so you always know who you're talking to.");
    kvxp_text($wp_customize, 'kvxp_hero', 'kvxp_hero_cta',      __('CTA text',      'klaravex-personal'), 'Get help now');
    kvxp_image($wp_customize, 'kvxp_hero', 'kvxp_hero_photo',   __('Background photo', 'klaravex-personal'));

    /* Pricing */
    $wp_customize->add_section('kvxp_pricing', [ 'title' => __('Pricing', 'klaravex-personal'), 'panel' => 'kvxp_panel' ]);
    kvxp_text($wp_customize, 'kvxp_pricing', 'kvxp_price_session',  __('One-time session price', 'klaravex-personal'), '$39');
    kvxp_text($wp_customize, 'kvxp_pricing', 'kvxp_price_monthly',  __('Monthly plan price',     'klaravex-personal'), '$29');
    kvxp_text($wp_customize, 'kvxp_pricing', 'kvxp_price_family',   __('Family plan price',      'klaravex-personal'), '$39');

    /* CTA */
    $wp_customize->add_section('kvxp_cta', [ 'title' => __('CTA Strip', 'klaravex-personal'), 'panel' => 'kvxp_panel' ]);
    kvxp_text($wp_customize, 'kvxp_cta', 'kvxp_cta_headline', __('Headline', 'klaravex-personal'), "Ready to stop fighting with your tech?");
    kvxp_text($wp_customize, 'kvxp_cta', 'kvxp_cta_btn',      __('Button text', 'klaravex-personal'), 'Get help now');
    kvxp_text($wp_customize, 'kvxp_cta', 'kvxp_cta_email',    __('Contact email', 'klaravex-personal'), 'hello@klaravex.com');

    /* Cross-site */
    $wp_customize->add_section('kvxp_xsite', [ 'title' => __('Cross-site Links', 'klaravex-personal'), 'panel' => 'kvxp_panel' ]);
    kvxp_text($wp_customize, 'kvxp_xsite', 'kvxp_biz_url',   __('Business site URL', 'klaravex-personal'), 'https://klaravex.com');
    kvxp_text($wp_customize, 'kvxp_xsite', 'kvxp_footer_legal', __('Footer legal line', 'klaravex-personal'), '© ' . date('Y') . ' Klaravex LLC — Personal IT Help');
}
add_action('customize_register', 'kvxp_customizer');

function kvxp_text($wpc, $section, $id, $label, $default = '') {
    $wpc->add_setting($id, ['default' => $default, 'sanitize_callback' => 'wp_kses_post']);
    $wpc->add_control($id, ['label' => $label, 'section' => $section, 'type' => 'textarea']);
}
function kvxp_image($wpc, $section, $id, $label) {
    $wpc->add_setting($id, ['default' => '', 'sanitize_callback' => 'esc_url_raw']);
    $wpc->add_control(new WP_Customize_Image_Control($wpc, $id, ['label' => $label, 'section' => $section]));
}

/* ── CUSTOMIZER CSS OUTPUT ── */
function kvxp_customizer_css() {
    $photo = get_theme_mod('kvxp_hero_photo');
    if ($photo) : ?>
    <style>.hero-photo { --hero-photo-url: url('<?php echo esc_url($photo); ?>'); }</style>
    <?php endif;
}
add_action('wp_head', 'kvxp_customizer_css');

/* ── HELPER ── */
function kvxp_mod($key, $fallback = '') {
    return wp_kses_post(get_theme_mod($key, $fallback));
}

/**
 * Personal is remote-only. Klaravex AI does the heavy lifting so prices
 * stay at session rates instead of house-call rates. Rewrite leftover
 * in-person / human-dispatch claims in page HTML until wp-admin is edited.
 */
function kvxp_rewrite_public_copy($html) {
    if (!is_string($html) || $html === '') {
        return $html;
    }
    $map = [
        'Remote or in-person' => 'Remote, any hour',
        'remote or in-person' => 'remote, any hour',
        'Remote and in-person across the US.' => 'Remote, any hour. Klaravex AI does the heavy lifting so we can pass the savings on to you.',
        'Remote and in-person across the US' => 'Remote, any hour. Klaravex AI does the heavy lifting so we can pass the savings on to you',
        'or in-person if needed' => 'remotely, step by step',
        'In-person is available in some areas — just ask.' => 'Help is remote only — no house calls. That is how a session stays $39 instead of a truck roll.',
        'In-person is available in some areas — just ask' => 'Help is remote only — no house calls. That is how a session stays $39 instead of a truck roll',
        'with our team available when you need a real person.' => 'Klaravex AI handles every session (you will see that name). AI does the heavy lifting so you are not paying for a dispatch.',
        'with our team available when you need a real person' => 'Klaravex AI handles every session (you will see that name). AI does the heavy lifting so you are not paying for a dispatch',
        "If it's urgent, Sam escalates to a human engineer immediately." => 'If it is urgent, Klaravex AI stays with you and walks the next steps in plain English.',
        'If it&#8217;s urgent, Sam escalates to a human engineer immediately.' => 'If it is urgent, Klaravex AI stays with you and walks the next steps in plain English.',
        'Tech help for real people. Plain English, no judgment, no jargon. Remote and in-person across the US.' => 'Plain English, any hour. Klaravex AI does the heavy lifting so we can pass the savings on to you.',
        'Friendly Tech Support for Real People' => 'Plain-English tech help, any hour',
        'Real help from real experts' => 'Plain English. Any hour.',
        'Talk to a person' => 'Get help now',
        'Talk to a human' => 'Get help now',
        'We combine AI-powered drafting with human strategy' => 'Klaravex AI does the heavy lifting on drafts and ATS formatting; you stay in control of every word',
        'Human review is available. P1 and P2 issues are escalated to a senior engineer.' => 'Klaravex Personal is delivered by Klaravex AI. You will see that name in the chat.',
        'Klaravex AI handles approximately 60-70% of interactions autonomously; complex matters are escalated to a human.' => 'Klaravex AI handles the session. Complex next steps are explained in plain English so you can decide. AI does the heavy lifting so pricing stays at a session, not a house call.',
        'Klaravex AI handles approximately 60–70% of interactions autonomously; complex matters are escalated to a human.' => 'Klaravex AI handles the session. Complex next steps are explained in plain English so you can decide. AI does the heavy lifting so pricing stays at a session, not a house call.',
        'We typically respond within one business day.' => 'Klaravex AI typically responds within minutes — start a chat and it will pick up right away.',
        'We typically respond within one business day' => 'Klaravex AI typically responds within minutes — start a chat and it will pick up right away',
    ];
    return str_replace(array_keys($map), array_values($map), $html);
}
add_filter('the_content', 'kvxp_rewrite_public_copy', 20);

function kvxp_ob_start() {
    if (is_admin() || wp_doing_ajax() || wp_doing_cron()) {
        return;
    }
    ob_start('kvxp_rewrite_public_copy');
}
add_action('template_redirect', 'kvxp_ob_start', 0);

function kvxp_document_title_parts($parts) {
    if (!empty($parts['tagline']) && preg_match('/real people|real experts/i', $parts['tagline'])) {
        $parts['tagline'] = 'Plain-English tech help, any hour';
    }
    return $parts;
}
add_filter('document_title_parts', 'kvxp_document_title_parts');

add_filter('option_blogdescription', function ($value) {
    if (is_string($value) && preg_match('/real people|in-person|in person/i', $value)) {
        return 'Plain-English tech help, any hour';
    }
    return $value;
});

add_action('wp_head', function () {
    if (is_front_page() || is_home()) {
        echo '<meta name="description" content="Plain-English tech help, remote only, any hour. Klaravex AI does the heavy lifting so we can pass the savings on to you. Sessions from $39 or monthly from $29." />' . "\n";
    }
}, 1);

/* ── CONTACT FORM AJAX ── */
function kvxp_handle_contact() {
    check_ajax_referer('kvxp_nonce', 'nonce');
    $name    = sanitize_text_field($_POST['name']    ?? '');
    $email   = sanitize_email($_POST['email']        ?? '');
    $service = sanitize_text_field($_POST['service'] ?? '');
    $message = sanitize_textarea_field($_POST['message'] ?? '');
    if (empty($name) || !is_email($email)) {
        wp_send_json_error(['message' => 'Please fill in your name and a valid email address.']);
    }
    $to      = get_option('admin_email');
    $subject = "New enquiry from {$name}" . ($service ? " — {$service}" : '');
    $body    = "Name: {$name}\nEmail: {$email}\nService: {$service}\n\nMessage:\n{$message}";
    $headers = ['Content-Type: text/plain; charset=UTF-8', "Reply-To: {$name} <{$email}>"];
    wp_mail($to, $subject, $body, $headers);
    wp_send_json_success(['message' => "Thanks {$name}! We'll be in touch shortly."]);
}
add_action('wp_ajax_kvxp_contact',        'kvxp_handle_contact');
add_action('wp_ajax_nopriv_kvxp_contact', 'kvxp_handle_contact');
