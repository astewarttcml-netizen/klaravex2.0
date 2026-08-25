<?php
/**
 * Klaravex — Contact Form 7 → Notion (IT Experts Bookings)
 * On successful CF7 submit, create a row in the Notion database.
 *
 * SETUP: paste your Notion internal integration token below.
 *   1. notion.so/my-integrations → New internal integration → copy "secret_..."
 *   2. Open the "IT Experts Bookings" DB → ••• → Connections → add your integration
 *   3. Paste the token into KLARAVEX_NOTION_TOKEN below
 */

if ( ! defined( 'KLARAVEX_NOTION_TOKEN' ) ) {
    define( 'KLARAVEX_NOTION_TOKEN', 'PASTE_secret_TOKEN_HERE' );  // ← your token
}
define( 'KLARAVEX_NOTION_DB', '777fd994-2bae-4cd8-92f5-d935f49fd67c' );

add_action( 'wpcf7_mail_sent', function ( $contact_form ) {

    // Only the contact form (skip if you add others later). Form id 234-ish; allow all for now.
    $submission = WPCF7_Submission::get_instance();
    if ( ! $submission ) return;
    $data = $submission->get_posted_data();

    $name    = trim( $data['your-name']    ?? '' );
    $company = trim( $data['your-company'] ?? '' );
    $email   = trim( $data['your-email']   ?? '' );
    $phone   = trim( $data['your-phone']   ?? '' );
    $message = trim( $data['your-message'] ?? '' );

    if ( $name === '' && $email === '' ) return;  // nothing to log

    // Build Notion properties payload
    $properties = [
        'Name'    => [ 'title'     => [ [ 'text' => [ 'content' => $name ?: 'Website lead' ] ] ] ],
        'Status'  => [ 'select'    => [ 'name' => 'New' ] ],
        'Submitted' => [ 'date'    => [ 'start' => gmdate( 'Y-m-d' ) ] ],
    ];
    if ( $email )   $properties['Email']   = [ 'email'        => $email ];
    if ( $phone )   $properties['Phone']   = [ 'phone_number' => $phone ];
    if ( $company ) $properties['Company'] = [ 'rich_text'    => [ [ 'text' => [ 'content' => $company ] ] ] ];
    if ( $message ) $properties['Message'] = [ 'rich_text'    => [ [ 'text' => [ 'content' => mb_substr( $message, 0, 2000 ) ] ] ] ];

    $body = [
        'parent'     => [ 'database_id' => KLARAVEX_NOTION_DB ],
        'properties' => $properties,
    ];

    $resp = wp_remote_post( 'https://api.notion.com/v1/pages', [
        'timeout' => 12,
        'headers' => [
            'Authorization'  => 'Bearer ' . KLARAVEX_NOTION_TOKEN,
            'Content-Type'   => 'application/json',
            'Notion-Version' => '2022-06-28',
        ],
        'body' => wp_json_encode( $body ),
    ] );

    // Log failures so they're visible without breaking the user's submit
    if ( is_wp_error( $resp ) ) {
        error_log( '[Klaravex→Notion] ' . $resp->get_error_message() );
    } else {
        $code = wp_remote_retrieve_response_code( $resp );
        if ( $code < 200 || $code >= 300 ) {
            error_log( '[Klaravex→Notion] HTTP ' . $code . ' — ' . wp_remote_retrieve_body( $resp ) );
        }
    }
}, 10, 1 );
