<?php

$host = $_SERVER['HTTP_HOST'];
$dir  = dirname(__FILE__);

$parts = explode('.', $host);
$s = array_shift($parts);

// this just makes our loop simpler
$parts[] = '';

while ($parts) {
	if (is_dir($dir . '/' . $s)) {
		$sites[$host] = $s;
		break;
	}
	$s .= '.' . array_shift($parts);
}



