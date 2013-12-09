<?php

umask(0002);
$conf['error_level'] = 0;
$conf['reverse_proxy'] = 1;
$conf['reverse_proxy_addresses'] = array('10.1.3.187');
$conf['cache'] = 1;
$conf['preprocess_css'] = 1;
$conf['preprocess_js'] = 1;
$conf['page_compression'] = 1;

/*$conf['site_mail_sender'] = 'postmaster@advocacy-engine.com'; */

$conf['mail_system'] = array(
  'default-system' => 'MimeMailSystem',
  'forward_forward' => 'ForwardMailSystem',
);

