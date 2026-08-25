<?php
/**
 * Klaravex Theme — functions.php
 */

defined( 'ABSPATH' ) || exit;

define( 'KVX_VERSION', '1.0.0' );
define( 'KVX_DIR', get_template_directory() );
define( 'KVX_URI', get_template_directory_uri() );

/* ─────────────────────────────────────────────
   THEME SETUP
───────────────────────────────────────────── */
function kvx_setup() {
    add_theme_support( 'title-tag' );
    add_theme_support( 'post-thumbnails' );
    add_theme_support( 'custom-logo', [
        'height'      => 60,
        'width'       => 200,
        'flex-height' => true,
        'flex-width'  => true,
    ]);
    add_theme_support( 'html5', [ 'search-form', 'comment-form', 'comment-list', 'gallery', 'caption', 'script', 'style' ] );
    add_theme_support( 'responsive-embeds' );
    add_theme_support( 'wp-block-styles' );

    // Image sizes
    add_image_size( 'kvx-hero',     1920, 1080, true );
    add_image_size( 'kvx-portrait',  800, 1000, true );
    add_image_size( 'kvx-card',      800,  600, true );
    add_image_size( 'kvx-thumb',     400,  300, true );

    // Menus
    register_nav_menus([
        'primary' => __( 'Primary Navigation', 'klaravex' ),
        'footer'  => __( 'Footer Navigation',  'klaravex' ),
    ]);
}
add_action( 'after_setup_theme', 'kvx_setup' );

/* ─────────────────────────────────────────────
   ENQUEUE ASSETS
───────────────────────────────────────────── */
function kvx_assets() {
    // Google Fonts
    wp_enqueue_style(
        'kvx-fonts',
        'https://fonts.googleapis.com/css2?family=Syne:wght@700;800&family=Inter:wght@400;500;600&display=swap',
        [], null
    );

    // Phosphor Icons
    wp_enqueue_script(
        'phosphor-icons',
        'https://unpkg.com/@phosphor-icons/web@2.1.1/src/index.js',
        [], '2.1.1', true
    );

    // Main stylesheet
    wp_enqueue_style(
        'kvx-main',
        KVX_URI . '/assets/css/main.css',
        [ 'kvx-fonts' ],
        KVX_VERSION
    );

    // Main JS
    wp_enqueue_script(
        'kvx-main',
        KVX_URI . '/assets/js/main.js',
        [], KVX_VERSION, true
    );

    // Pass data to JS
    wp_localize_script( 'kvx-main', 'kvxData', [
        'ajaxUrl' => admin_url( 'admin-ajax.php' ),
        'nonce'   => wp_create_nonce( 'kvx_nonce' ),
    ]);
}
add_action( 'wp_enqueue_scripts', 'kvx_assets' );

/* ─────────────────────────────────────────────
   SERVICES PAGES — TEMPLATE ROUTING + ASSETS
   Routes the Services index (id 14) to page-services.php
   and any descendant page to page-service.php, then
   enqueues services.css on those pages.
───────────────────────────────────────────── */
define( 'KVX_SERVICES_ROOT', 14 );

function kvx_is_services_page( $id ) {
    return (int) $id === KVX_SERVICES_ROOT
        || in_array( KVX_SERVICES_ROOT, (array) get_post_ancestors( $id ), true );
}

function kvx_services_template( $template ) {
    if ( ! is_page() ) {
        return $template;
    }
    $id = get_queried_object_id();

    if ( (int) $id === KVX_SERVICES_ROOT ) {
        $candidate = KVX_DIR . '/page-services.php';
        if ( file_exists( $candidate ) ) {
            return $candidate;
        }
    }

    // Children: only override the default page.php renderer, so a child that
    // explicitly got its own template assigned keeps it.
    if ( in_array( KVX_SERVICES_ROOT, (array) get_post_ancestors( $id ), true )
        && basename( $template ) === 'page.php' ) {
        $candidate = KVX_DIR . '/page-service.php';
        if ( file_exists( $candidate ) ) {
            return $candidate;
        }
    }

    return $template;
}
add_filter( 'template_include', 'kvx_services_template' );

function kvx_services_assets() {
    if ( ! is_page() ) {
        return;
    }
    if ( kvx_is_services_page( get_queried_object_id() ) ) {
        wp_enqueue_style(
            'kvx-services',
            KVX_URI . '/assets/css/services.css',
            [ 'kvx-main' ],
            KVX_VERSION
        );
    }
}
add_action( 'wp_enqueue_scripts', 'kvx_services_assets' );

/* ─────────────────────────────────────────────
   CUSTOMIZER OPTIONS
───────────────────────────────────────────── */
function kvx_customizer( $wp_customize ) {

    // Panel
    $wp_customize->add_panel( 'kvx_panel', [
        'title'    => __( 'Klaravex Theme', 'klaravex' ),
        'priority' => 30,
    ]);

    /* ── Hero section ── */
    $wp_customize->add_section( 'kvx_hero', [
        'title' => __( 'Hero Section', 'klaravex' ),
        'panel' => 'kvx_panel',
    ]);
    kvx_add_text(  $wp_customize, 'kvx_hero', 'hero_eyebrow',  __( 'Eyebrow',    'klaravex' ), 'Managed IT &amp; Security — AI-Powered' );
    kvx_add_text(  $wp_customize, 'kvx_hero', 'hero_headline', __( 'Headline',   'klaravex' ), '89% of IT issues resolved before you finish your coffee.' );
    kvx_add_text(  $wp_customize, 'kvx_hero', 'hero_subhead',  __( 'Subheadline','klaravex' ), "Klaravex's AI handles Tier 1, Tier 2, monitoring, provisioning, and reporting — instantly, 24/7, across every time zone." );
    kvx_add_image( $wp_customize, 'kvx_hero', 'hero_photo',    __( 'Background Photo', 'klaravex' ) );
    kvx_add_text(  $wp_customize, 'kvx_hero', 'hero_cta_text', __( 'CTA Button Text', 'klaravex' ), 'Book a Senior Engineer — Not a Sales Call' );

    /* ── Stats ── */
    $wp_customize->add_section( 'kvx_stats', [
        'title' => __( 'Hero Stats', 'klaravex' ),
        'panel' => 'kvx_panel',
    ]);
    kvx_add_text( $wp_customize, 'kvx_stats', 'stat1_num',   __( 'Stat 1 Number', 'klaravex' ), '89%' );
    kvx_add_text( $wp_customize, 'kvx_stats', 'stat1_label', __( 'Stat 1 Label',  'klaravex' ), 'Issues resolved by AI' );
    kvx_add_text( $wp_customize, 'kvx_stats', 'stat2_num',   __( 'Stat 2 Number', 'klaravex' ), '24/7' );
    kvx_add_text( $wp_customize, 'kvx_stats', 'stat2_label', __( 'Stat 2 Label',  'klaravex' ), 'AI coverage, every time zone' );
    kvx_add_text( $wp_customize, 'kvx_stats', 'stat3_num',   __( 'Stat 3 Number', 'klaravex' ), '2hr' );
    kvx_add_text( $wp_customize, 'kvx_stats', 'stat3_label', __( 'Stat 3 Label',  'klaravex' ), 'Human senior engineer SLA' );
    kvx_add_text( $wp_customize, 'kvx_stats', 'stat4_num',   __( 'Stat 4 Number', 'klaravex' ), '$0' );
    kvx_add_text( $wp_customize, 'kvx_stats', 'stat4_label', __( 'Stat 4 Label',  'klaravex' ), 'Vendor commissions, ever' );

    /* ── Case Studies ── */
    $wp_customize->add_section( 'kvx_cases', [
        'title' => __( 'Case Studies', 'klaravex' ),
        'panel' => 'kvx_panel',
    ]);
    for ( $i = 1; $i <= 3; $i++ ) {
        kvx_add_text( $wp_customize, 'kvx_cases', "case{$i}_industry", __( "Case {$i} Industry", 'klaravex' ), '' );
        kvx_add_text( $wp_customize, 'kvx_cases', "case{$i}_stat",     __( "Case {$i} Stat",     'klaravex' ), '' );
        kvx_add_text( $wp_customize, 'kvx_cases', "case{$i}_label",    __( "Case {$i} Label",    'klaravex' ), '' );
        kvx_add_text( $wp_customize, 'kvx_cases', "case{$i}_desc",     __( "Case {$i} Desc",     'klaravex' ), '' );
    }

    /* ── Portal section ── */
    $wp_customize->add_section( 'kvx_portal', [
        'title' => __( 'Portal Section', 'klaravex' ),
        'panel' => 'kvx_panel',
    ]);
    kvx_add_text( $wp_customize, 'kvx_portal', 'portal_headline', __( 'Headline', 'klaravex' ), 'Your IT, visible. Your team, covered.' );
    kvx_add_text( $wp_customize, 'kvx_portal', 'portal_sub',      __( 'Subtext',  'klaravex' ), 'Every client gets a private portal. See what\'s happening with your systems in real time, talk to AI instantly, and always know who your engineer is.' );
    kvx_add_text( $wp_customize, 'kvx_portal', 'portal_url',      __( 'Portal URL', 'klaravex' ), 'portal.klaravex.com' );

    /* ── CTA section ── */
    $wp_customize->add_section( 'kvx_cta', [
        'title' => __( 'CTA Section', 'klaravex' ),
        'panel' => 'kvx_panel',
    ]);
    kvx_add_text( $wp_customize, 'kvx_cta', 'cta_headline',   __( 'Headline',   'klaravex' ), 'Book a Senior Engineer — Not a Sales Call.' );
    kvx_add_text( $wp_customize, 'kvx_cta', 'cta_body',       __( 'Body',       'klaravex' ), '45 minutes. Written report. No obligation.' );
    kvx_add_text( $wp_customize, 'kvx_cta', 'cta_btn_text',   __( 'Button Text','klaravex' ), 'Request Your Free Assessment' );
    kvx_add_text( $wp_customize, 'kvx_cta', 'cta_btn_url',    __( 'Button URL', 'klaravex' ), '#' );
    kvx_add_text( $wp_customize, 'kvx_cta', 'cta_pricing_anchor', __( 'Pricing Anchor', 'klaravex' ), '$X per user/month' );

    /* ── Contact / Footer ── */
    $wp_customize->add_section( 'kvx_footer', [
        'title' => __( 'Footer', 'klaravex' ),
        'panel' => 'kvx_panel',
    ]);
    kvx_add_text( $wp_customize, 'kvx_footer', 'footer_desc',    __( 'Brand Description', 'klaravex' ), 'Senior-level managed IT and security for businesses that run lean.' );
    kvx_add_text( $wp_customize, 'kvx_footer', 'footer_legal',   __( 'Legal Line',        'klaravex' ), '© ' . date('Y') . ' Klaravex LLC — United States' );
}
add_action( 'customize_register', 'kvx_customizer' );

/* ── Helpers ── */
function kvx_add_text( $wp_customize, $section, $id, $label, $default = '' ) {
    $wp_customize->add_setting( $id, [ 'default' => $default, 'sanitize_callback' => 'wp_kses_post' ] );
    $wp_customize->add_control( $id, [ 'label' => $label, 'section' => $section, 'type' => 'textarea' ] );
}
function kvx_add_image( $wp_customize, $section, $id, $label ) {
    $wp_customize->add_setting( $id, [ 'default' => '', 'sanitize_callback' => 'esc_url_raw' ] );
    $wp_customize->add_control( new WP_Customize_Image_Control( $wp_customize, $id, [ 'label' => $label, 'section' => $section ] ) );
}

/* ── Output customizer settings ── */
function kvx_customizer_css() {
    $hero_photo = get_theme_mod( 'hero_photo' );
    if ( $hero_photo ) : ?>
    <style>
      .hero-photo { --hero-photo-url: url('<?php echo esc_url( $hero_photo ); ?>'); }
    </style>
    <?php endif;
}
add_action( 'wp_head', 'kvx_customizer_css' );

/* ─────────────────────────────────────────────
   HELPER: get customizer value with fallback
───────────────────────────────────────────── */
function kvx_mod( $key, $fallback = '' ) {
    return wp_kses_post( get_theme_mod( $key, $fallback ) );
}

/* ─────────────────────────────────────────────
   CONTACT FORM AJAX HANDLER
   (works with any basic contact form plugin
    or the simple form in the CTA section)
───────────────────────────────────────────── */
function kvx_handle_contact() {
    check_ajax_referer( 'kvx_nonce', 'nonce' );
    $name    = sanitize_text_field( $_POST['name']    ?? '' );
    $email   = sanitize_email(      $_POST['email']   ?? '' );
    $company = sanitize_text_field( $_POST['company'] ?? '' );
    $message = sanitize_textarea_field( $_POST['message'] ?? '' );

    if ( empty( $name ) || ! is_email( $email ) ) {
        wp_send_json_error( [ 'message' => 'Please fill in all required fields.' ] );
    }

    $to      = get_option( 'admin_email' );
    $subject = "New assessment request from {$name} — {$company}";
    $body    = "Name: {$name}\nEmail: {$email}\nCompany: {$company}\n\nMessage:\n{$message}";
    $headers = [ 'Content-Type: text/plain; charset=UTF-8', "Reply-To: {$name} <{$email}>" ];

    wp_mail( $to, $subject, $body, $headers );
    wp_send_json_success( [ 'message' => 'Thank you. We\'ll respond within one business day.' ] );
}
add_action( 'wp_ajax_kvx_contact',        'kvx_handle_contact' );
add_action( 'wp_ajax_nopriv_kvx_contact', 'kvx_handle_contact' );
