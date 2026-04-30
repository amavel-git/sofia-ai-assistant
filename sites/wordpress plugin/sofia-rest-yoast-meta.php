<?php
/**
 * Plugin Name: Sofia REST Yoast Meta
 * Description: Exposes selected Yoast SEO fields to the WordPress REST API for Sofia.
 * Version: 1.0
 */

add_action('init', function () {
    $post_types = ['post', 'page'];

    $meta_keys = [
        '_yoast_wpseo_title',
        '_yoast_wpseo_metadesc',
        '_yoast_wpseo_focuskw'
    ];

    foreach ($post_types as $post_type) {
        foreach ($meta_keys as $meta_key) {
            register_post_meta($post_type, $meta_key, [
                'single' => true,
                'type' => 'string',
                'show_in_rest' => true,
                'auth_callback' => function () {
                    return current_user_can('edit_posts');
                },
                'sanitize_callback' => 'sanitize_text_field'
            ]);
        }
    }
});